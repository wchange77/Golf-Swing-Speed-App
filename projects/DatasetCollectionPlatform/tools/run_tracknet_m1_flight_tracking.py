from __future__ import annotations

import argparse
import inspect
import json
from pathlib import Path
from typing import Any

from lib.sota_tracker_paths import SotaTrackerPaths
from lib.tapnextpp_tracker import SeedPoint
from lib.tracknet_m1_flight_tracker import SeededFlightTracker


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(path)


def _seed_point_from_item(item: dict[str, Any], sample_id: str) -> SeedPoint:
    points = item.get("points") if isinstance(item.get("points"), dict) else {}
    ball = points.get("ball_center") if isinstance(points.get("ball_center"), dict) else None
    clubhead = points.get("clubhead_center") if isinstance(points.get("clubhead_center"), dict) else None
    frame_index = item.get("frameIndex", item.get("seedFrame"))
    if ball is not None:
        x = ball.get("x")
        y = ball.get("y")
    else:
        x = item.get("x")
        y = item.get("y")
    clubhead_center = None
    if isinstance(clubhead, dict):
        clubhead_center = {
            "x": float(clubhead["x"]),
            "y": float(clubhead["y"]),
            "visible": bool(clubhead.get("visible", True)),
        }
    seed = SeedPoint(
        sample_id=sample_id,
        frame_index=int(frame_index),
        x=float(x),
        y=float(y),
    )
    if clubhead_center is not None:
        object.__setattr__(seed, "clubhead_center", clubhead_center)
    return seed


def _seed_points(path: Path) -> dict[str, SeedPoint]:
    payload = _load_json(path)
    seeds = payload.get("seeds") if isinstance(payload, dict) else None
    if not isinstance(seeds, list):
        raise RuntimeError(f"could not locate seeds in {path}")
    output: dict[str, SeedPoint] = {}
    for item in seeds:
        sample_id = str(item.get("sampleId") or "")
        if not sample_id:
            continue
        output[sample_id] = _seed_point_from_item(item, sample_id)
    return output


def _valid_sample_id_for_path(sample_id: str) -> bool:
    return bool(sample_id) and "/" not in sample_id and "\\" not in sample_id and ".." not in sample_id


def _trajectory_filename(sample_id: str) -> str:
    if _valid_sample_id_for_path(sample_id):
        return f"{sample_id}.json"
    safe = "".join(character if character.isalnum() or character in {"-", "_"} else "_" for character in sample_id)
    safe = safe.strip("._") or "invalid_sample_id"
    return f"{safe}.json"


def _camera_model_summary(camera_model_dir: Path | str, sample_id: str) -> tuple[dict[str, Any], str | None]:
    if not _valid_sample_id_for_path(sample_id):
        return {"status": "missing", "reason": "invalid_sample_id"}, None
    path = Path(camera_model_dir) / f"{sample_id}.camera_model.json"
    if not path.exists():
        return {"status": "missing"}, None
    payload = _load_json(path)
    camera_model = payload.get("cameraModel") if isinstance(payload, dict) else None
    if not isinstance(camera_model, dict):
        return {"status": "missing"}, str(path)
    intrinsics = camera_model.get("intrinsics") if isinstance(camera_model.get("intrinsics"), dict) else {}
    summary = {
        "status": str(payload.get("status") or "ok"),
        "source": camera_model.get("source"),
        "fx": camera_model.get("fx", intrinsics.get("fx")),
        "fy": camera_model.get("fy", intrinsics.get("fy")),
        "cx": camera_model.get("cx", intrinsics.get("cx")),
        "cy": camera_model.get("cy", intrinsics.get("cy")),
    }
    if "confidences" in camera_model:
        summary["confidences"] = camera_model["confidences"]
    return {key: value for key, value in summary.items() if value is not None}, str(path)


def _camera_kwargs_supported(call_target: Any) -> bool:
    try:
        parameters = inspect.signature(call_target).parameters
    except (TypeError, ValueError):
        return True
    if any(parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in parameters.values()):
        return True
    return "camera_model_summary" in parameters and "camera_model_path" in parameters


def _track_with_camera_model(
    tracker: Any,
    shot: dict[str, Any],
    seed: SeedPoint,
    camera_summary: dict[str, Any],
    camera_path: str | None,
) -> dict[str, Any]:
    call_target = getattr(tracker, "track", None)
    if call_target is None:
        if not callable(tracker):
            raise TypeError("tracker must provide .track(...) or be callable")
        call_target = tracker
    if _camera_kwargs_supported(call_target):
        return call_target(
            shot,
            seed,
            camera_model_summary=camera_summary,
            camera_model_path=camera_path,
        )
    try:
        return call_target(
            shot,
            seed,
            camera_model_summary=camera_summary,
            camera_model_path=camera_path,
        )
    except TypeError:
        return call_target(shot, seed)


def run_flight_tracking(
    *,
    batch_index_path: Path | str,
    seeds_path: Path | str,
    output_dir: Path | str,
    camera_model_dir: Path | str | None = None,
    max_frames_after_seed: int = 1200,
    frame_stride: int = 1,
    tracker: SeededFlightTracker | None = None,
) -> dict[str, Any]:
    batch_index_path = Path(batch_index_path)
    seeds_path = Path(seeds_path)
    output_dir = Path(output_dir)
    camera_model_dir = Path(camera_model_dir) if camera_model_dir is not None else _default_annotation_root() / "work/m1_camera_models/models"
    trajectories_dir = output_dir / "trajectories"
    batch = _load_json(batch_index_path)
    shots = batch.get("shots") if isinstance(batch, dict) else None
    if not isinstance(shots, list):
        raise RuntimeError(f"could not locate shots in {batch_index_path}")
    seeds = _seed_points(seeds_path)
    paths = SotaTrackerPaths.default()
    tracker = tracker or SeededFlightTracker(
        checkpoint=paths.tapnextpp_checkpoint,
        max_frames_after_seed=max_frames_after_seed,
        frame_stride=frame_stride,
    )

    processed = 0
    missing_seeds: list[str] = []
    failed: list[dict[str, str]] = []
    trajectory_paths: list[str] = []
    summaries: list[dict[str, Any]] = []
    for index, shot in enumerate(shots, start=1):
        sample_id = str(shot.get("sampleId") or "")
        seed = seeds.get(sample_id)
        if seed is None:
            missing_seeds.append(sample_id)
            continue
        try:
            print(f"[{index}/{len(shots)}] flight-tracking {sample_id}", flush=True)
            camera_model_summary, camera_model_path = _camera_model_summary(camera_model_dir, sample_id)
            trajectory = _track_with_camera_model(tracker, shot, seed, camera_model_summary, camera_model_path)
            trajectory_path = trajectories_dir / _trajectory_filename(sample_id)
            _write_json(trajectory_path, trajectory)
            trajectory_paths.append(str(trajectory_path))
            processed += 1
            summaries.append({
                "sampleId": sample_id,
                "launchFrame": trajectory.get("impact", {}).get("launchFrame"),
                "visibleFrames": sum(1 for frame in trajectory.get("frames", []) if frame.get("visible")),
                "flightTracking": trajectory.get("flightTracking", {}),
            })
            print(f"[{index}/{len(shots)}] wrote {trajectory_path}", flush=True)
        except Exception as exc:  # noqa: BLE001 - batch report should keep per-sample failures.
            failed.append({"sampleId": sample_id, "error": str(exc)})
            print(f"[{index}/{len(shots)}] failed {sample_id}: {exc}", flush=True)
    report = {
        "status": "ok" if not failed else "partial",
        "batchIndex": str(batch_index_path),
        "seeds": str(seeds_path),
        "outputDir": str(output_dir),
        "cameraModelDir": str(camera_model_dir),
        "processed": processed,
        "missingSeeds": missing_seeds,
        "failed": failed,
        "trajectories": trajectory_paths,
        "trackingWindow": {
            "maxFramesAfterSeed": int(max_frames_after_seed),
            "frameStride": int(frame_stride),
        },
        "summaries": summaries,
    }
    _write_json(output_dir / "tracking_report.json", report)
    return report


def _default_annotation_root() -> Path:
    return Path(__file__).resolve().parents[4] / "tracknetv6-dataset-annotation"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    annotation_root = _default_annotation_root()
    parser = argparse.ArgumentParser(description="Run seed-based golf ball flight tracking for TrackNet M1 review labels")
    parser.add_argument("--batch-index", type=Path, default=annotation_root / "work/m1_reviewed_batch/batch_index.json")
    parser.add_argument("--seeds", type=Path, default=annotation_root / "work/m1_sota_tracking/seeds.json")
    parser.add_argument("--output-dir", type=Path, default=annotation_root / "work/m1_flight_tracking")
    parser.add_argument("--camera-model-dir", type=Path, default=annotation_root / "work/m1_camera_models/models")
    parser.add_argument("--max-frames-after-seed", type=int, default=1200)
    parser.add_argument("--frame-stride", type=int, default=1)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = run_flight_tracking(
        batch_index_path=args.batch_index,
        seeds_path=args.seeds,
        output_dir=args.output_dir,
        camera_model_dir=args.camera_model_dir,
        max_frames_after_seed=args.max_frames_after_seed,
        frame_stride=args.frame_stride,
    )
    print(json.dumps(report, ensure_ascii=False))
    return 0 if not report["failed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
