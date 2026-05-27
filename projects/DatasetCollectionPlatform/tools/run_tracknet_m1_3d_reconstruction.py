from __future__ import annotations

import argparse
import json
from json import JSONDecodeError
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lib.tracknet_m1_camera_model import build_camera_model_for_shot
from lib.tracknet_m1_trajectory_3d import (
    build_trackman_constrained_3d_trajectory,
    build_video_only_3d_trajectory,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _sample_id(visible_path: Path, visible: dict[str, Any]) -> str:
    sample_id = visible.get("sampleId") or visible_path.stem
    if not isinstance(sample_id, str) or not sample_id:
        raise ValueError("visible artifact sampleId must be a non-empty string")
    if Path(sample_id).name != sample_id or "/" in sample_id or "\\" in sample_id or ".." in sample_id:
        raise ValueError(f"unsafe sampleId: {sample_id}")
    return sample_id


def _load_camera(
    visible: dict[str, Any],
    sample_id: str,
    camera_sidecar_by_sample: dict[str, Path | str],
) -> dict[str, Any]:
    camera_path = camera_sidecar_by_sample.get(sample_id)
    if camera_path is None:
        return build_camera_model_for_shot(visible)
    camera_path = Path(camera_path)
    if not camera_path.exists():
        raise FileNotFoundError(f"camera sidecar not found for {sample_id}: {camera_path}")
    return _read_json(camera_path)


def _identity_mismatch(
    *,
    label: str,
    expected: dict[str, Any],
    actual: dict[str, Any],
) -> str | None:
    for key in ("sampleId", "shotId", "sessionId"):
        expected_value = expected.get(key)
        actual_value = actual.get(key)
        if expected_value is not None and actual_value is not None and expected_value != actual_value:
            return f"{label} {key} mismatch: expected {expected_value}, got {actual_value}"
    return None


def _validate_camera_identity(visible: dict[str, Any], camera: dict[str, Any]) -> None:
    mismatch = _identity_mismatch(label="camera", expected=visible, actual=camera)
    if mismatch is not None:
        raise ValueError(mismatch)


def _normalise_visible_for_3d(visible: dict[str, Any]) -> dict[str, Any]:
    seed = visible.get("seed")
    if isinstance(seed, dict) and "ballCenter" not in seed and {"frameIndex", "x", "y"} <= set(seed):
        visible = dict(visible)
        visible["seed"] = {"ballCenter": seed}
    return visible


def _remove_stale_trajectories(trajectories_dir: Path) -> None:
    if not trajectories_dir.exists():
        return
    for path in trajectories_dir.glob("*.trajectory_3d.json"):
        if path.is_file():
            path.unlink()


def _trajectory_has_unavailable_trackman(payload: dict[str, Any]) -> bool:
    trackman = payload.get("trackmanConstrained3d")
    return isinstance(trackman, dict) and str(trackman.get("status", "")).startswith("unavailable_")


def _unavailable_trackman_payload(visible: dict[str, Any], status: str, reason: str) -> dict[str, Any]:
    return {
        "trackmanConstrained3d": {
            "version": "1.0",
            "stage": "m1_3d_reconstruction",
            "generatedAt": _utc_now(),
            "sampleId": visible.get("sampleId"),
            "shotId": visible.get("shotId"),
            "sessionId": visible.get("sessionId"),
            "sourceVideo": visible.get("sourceVideo"),
            "status": status,
            "reason": reason,
            "frames": [],
        }
    }


def _build_optional_trackman(
    *,
    visible: dict[str, Any],
    camera: dict[str, Any],
    review_path: Path | str,
) -> dict[str, Any]:
    review_path = Path(review_path)
    if not review_path.exists():
        return _unavailable_trackman_payload(
            visible,
            "unavailable_trackman_review_missing",
            f"TrackMan review not found: {review_path}",
        )
    try:
        review = _read_json(review_path)
    except (OSError, JSONDecodeError, UnicodeDecodeError) as exc:
        return _unavailable_trackman_payload(
            visible,
            "unavailable_invalid_trackman_review",
            f"TrackMan review could not be read: {exc}",
        )
    if not isinstance(review, dict):
        return _unavailable_trackman_payload(
            visible,
            "unavailable_invalid_trackman_review",
            "TrackMan review payload must be an object",
        )
    mismatch = _identity_mismatch(label="TrackMan", expected=visible, actual=review)
    if mismatch is not None:
        return _unavailable_trackman_payload(visible, "unavailable_trackman_identity_mismatch", mismatch)
    try:
        return build_trackman_constrained_3d_trajectory(visible, camera, review)
    except Exception as exc:
        return _unavailable_trackman_payload(
            visible,
            "unavailable_trackman_reconstruction_error",
            str(exc),
        )


def trackman_review_by_sample_from_dir(trackman_review_dir: Path | str) -> dict[str, Path]:
    trackman_review_dir = Path(trackman_review_dir)
    if not trackman_review_dir.exists() or not trackman_review_dir.is_dir():
        raise ValueError(f"TrackMan review dir does not exist or is not a directory: {trackman_review_dir}")
    mapping: dict[str, Path] = {}
    for path in sorted(trackman_review_dir.glob("*.trackman_review.json")):
        sample_id = None
        try:
            review = _read_json(path)
        except (OSError, JSONDecodeError, UnicodeDecodeError):
            review = None
        if isinstance(review, dict) and isinstance(review.get("sampleId"), str) and review["sampleId"]:
            sample_id = review["sampleId"]
        elif path.name.endswith(".trackman_review.json"):
            sample_id = path.name[: -len(".trackman_review.json")]
        if not sample_id:
            continue
        if sample_id in mapping:
            continue
        mapping[sample_id] = path
    return mapping


def run_3d_reconstruction(
    *,
    visible_trajectories_dir: Path | str,
    output_dir: Path | str,
    camera_sidecar_by_sample: dict[str, Path | str] | None = None,
    trackman_review_by_sample: dict[str, Path | str] | None = None,
) -> dict[str, Any]:
    visible_trajectories_dir = Path(visible_trajectories_dir)
    output_dir = Path(output_dir)
    if not visible_trajectories_dir.exists() or not visible_trajectories_dir.is_dir():
        raise ValueError(f"visible trajectories dir does not exist or is not a directory: {visible_trajectories_dir}")

    camera_sidecar_by_sample = camera_sidecar_by_sample or {}
    trackman_review_by_sample = trackman_review_by_sample or {}
    trajectories_dir = output_dir / "trajectories"
    _remove_stale_trajectories(trajectories_dir)

    visible_paths = sorted(visible_trajectories_dir.glob("*.json"))
    processed = 0
    trackman_attempted = 0
    trackman_unavailable = 0
    trackman_skipped = 0
    failed: list[dict[str, str]] = []
    outputs: list[str] = []
    samples: list[dict[str, Any]] = []

    for visible_path in visible_paths:
        sample_id = visible_path.stem
        trackman_status = "skipped"
        review_path: Path | str | None = None
        try:
            visible = _read_json(visible_path)
            sample_id = _sample_id(visible_path, visible)
            visible = _normalise_visible_for_3d(visible)
            review_path = trackman_review_by_sample.get(sample_id)
            if review_path is None:
                trackman_skipped += 1
            camera = _load_camera(visible, sample_id, camera_sidecar_by_sample)
            _validate_camera_identity(visible, camera)

            payload = build_video_only_3d_trajectory(visible, camera)
            if review_path is not None:
                trackman_attempted += 1
                payload.update(_build_optional_trackman(visible=visible, camera=camera, review_path=review_path))
                if _trajectory_has_unavailable_trackman(payload):
                    trackman_unavailable += 1
                    trackman_status = "unavailable"
                else:
                    trackman_status = "generated"

            output_path = trajectories_dir / f"{sample_id}.trajectory_3d.json"
            _write_json(output_path, payload)
            outputs.append(str(output_path))
            processed += 1
            samples.append(
                {
                    "sampleId": sample_id,
                    "status": "processed",
                    "trajectoryPath": str(output_path),
                    "trackmanStatus": trackman_status,
                }
            )
        except Exception as exc:
            error = str(exc)
            failed.append({"sampleId": sample_id, "error": error})
            samples.append(
                {
                    "sampleId": sample_id,
                    "status": "failed",
                    "error": error,
                    "trackmanStatus": trackman_status,
                }
            )

    report = {
        "version": "1.0",
        "stage": "m1_3d_reconstruction",
        "generatedAt": _utc_now(),
        "inputDir": str(visible_trajectories_dir),
        "outputDir": str(output_dir),
        "inputCount": len(visible_paths),
        "processed": processed,
        "failedCount": len(failed),
        "failed": failed,
        "trajectories": outputs,
        "samples": samples,
        "trackmanAttempted": trackman_attempted,
        "trackmanUnavailable": trackman_unavailable,
        "trackmanSkipped": trackman_skipped,
        "unavailableTrackman": trackman_unavailable,
    }
    _write_json(output_dir / "reconstruction_report.json", report)
    return report


def _default_annotation_root() -> Path:
    return Path(__file__).resolve().parents[4] / "tracknetv6-dataset-annotation"


def main(argv: list[str] | None = None) -> int:
    annotation_root = _default_annotation_root()
    parser = argparse.ArgumentParser(description="Build M1 3D reconstruction artifacts")
    parser.add_argument(
        "--visible-trajectories-dir",
        type=Path,
        default=annotation_root / "work/m1_visible_tracking/trajectories",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=annotation_root / "work/m1_3d_reconstruction",
    )
    parser.add_argument("--trackman-review-dir", type=Path)
    args = parser.parse_args(argv)
    trackman_review_by_sample = None
    if args.trackman_review_dir is not None:
        trackman_review_by_sample = trackman_review_by_sample_from_dir(args.trackman_review_dir)
    report = run_3d_reconstruction(
        visible_trajectories_dir=args.visible_trajectories_dir,
        output_dir=args.output_dir,
        trackman_review_by_sample=trackman_review_by_sample,
    )
    concise = {
        "processed": report["processed"],
        "failedCount": report["failedCount"],
        "outputDir": report["outputDir"],
        "trackmanAttempted": report["trackmanAttempted"],
        "trackmanUnavailable": report["trackmanUnavailable"],
        "trackmanSkipped": report["trackmanSkipped"],
    }
    print(json.dumps(concise, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
