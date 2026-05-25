from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Callable

from lib.cotracker_crosscheck import CoTracker3OnlineTracker, CoTracker3Tracker, apply_cotracker_crosscheck
from lib.sota_tracker_paths import SotaTrackerPaths
from lib.tapnextpp_tracker import SeedPoint, TapNextPPTracker, build_tapnextpp_trajectory


_UNSET = object()


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _safe_path_segment(value: object, fallback: str) -> str:
    text = str(value or fallback).strip() or fallback
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in text)
    cleaned = cleaned.strip("._") or fallback
    if cleaned in {".", ".."} or ".." in cleaned:
        cleaned = fallback
    return cleaned[:120]


def _contained_child(root: Path, *parts: str) -> Path:
    root_resolved = root.resolve()
    child = root.joinpath(*parts).resolve()
    if not child.is_relative_to(root_resolved):
        raise RuntimeError(f"unsafe output path outside {root}")
    return child


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
    by_sample: dict[str, SeedPoint] = {}
    for item in seeds:
        sample_id = str(item.get("sampleId") or "")
        if not sample_id:
            continue
        by_sample[sample_id] = _seed_point_from_item(item, sample_id)
    return by_sample


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(path)


def _default_tapnext_tracker(paths: SotaTrackerPaths, *, device: str | None = None, max_frames_after_seed: int = 240, frame_stride: int = 1) -> TapNextPPTracker:
    return TapNextPPTracker(
        tapnet_repo=paths.tapnet_repo,
        checkpoint=paths.tapnextpp_checkpoint,
        device=device,
        use_certainty=True,
        max_frames_after_seed=max_frames_after_seed,
        frame_stride=frame_stride,
    )


def _default_cotracker(paths: SotaTrackerPaths, *, device: str | None = None, mode: str = "online", max_frames_after_seed: int = 240, frame_stride: int = 1) -> CoTracker3Tracker | CoTracker3OnlineTracker:
    if mode == "online":
        return CoTracker3OnlineTracker(
            cotracker_repo=paths.cotracker_repo,
            checkpoint=paths.cotracker_online_checkpoint,
            device=device,
            max_frames_after_seed=max_frames_after_seed,
            frame_stride=frame_stride,
        )
    if mode == "offline":
        return CoTracker3Tracker(
            cotracker_repo=paths.cotracker_repo,
            checkpoint=paths.cotracker_offline_checkpoint,
            device=device,
            backward_tracking=True,
            max_frames_after_seed=max_frames_after_seed,
            frame_stride=frame_stride,
        )
    raise RuntimeError(f"unsupported CoTracker3 mode: {mode}")


def run_sota_tracking(
    *,
    batch_index_path: Path | str,
    seeds_path: Path | str,
    output_dir: Path | str,
    tapnext_tracker: Callable[[dict[str, Any], SeedPoint], dict[str, Any]] | object = _UNSET,
    cotracker_tracker: Callable[[dict[str, Any], SeedPoint], list[dict[str, Any]]] | None | object = _UNSET,
    checkpoint: Path | str | None = None,
    max_distance_px: float = 8.0,
    require_cotracker: bool = True,
    device: str | None = None,
    tapnext_device: str | None = None,
    cotracker_device: str | None = None,
    cotracker_mode: str = "online",
    max_frames_after_seed: int = 240,
    frame_stride: int = 1,
) -> dict[str, Any]:
    batch_index_path = Path(batch_index_path)
    seeds_path = Path(seeds_path)
    output_dir = Path(output_dir)
    trajectories_dir = output_dir / "trajectories"
    batch = _load_json(batch_index_path)
    shots = batch.get("shots") if isinstance(batch, dict) else None
    if not isinstance(shots, list):
        raise RuntimeError(f"could not locate shots in {batch_index_path}")
    seeds = _seed_points(seeds_path)
    paths = SotaTrackerPaths.default()
    checkpoint_path = Path(checkpoint) if checkpoint is not None else paths.tapnextpp_checkpoint

    if tapnext_tracker is _UNSET:
        tapnext_tracker = _default_tapnext_tracker(paths, device=tapnext_device or device, max_frames_after_seed=max_frames_after_seed, frame_stride=frame_stride)
    if cotracker_tracker is _UNSET:
        cotracker_tracker = _default_cotracker(paths, device=cotracker_device or device, mode=cotracker_mode, max_frames_after_seed=max_frames_after_seed, frame_stride=frame_stride)
    if cotracker_tracker is None and require_cotracker:
        raise RuntimeError("CoTracker3 cross-check is required for this workflow")

    processed = 0
    missing_seeds: list[str] = []
    failed: list[dict[str, str]] = []
    trajectory_paths: list[str] = []
    for index, shot in enumerate(shots, start=1):
        sample_id = str(shot.get("sampleId") or "")
        seed = seeds.get(sample_id)
        if seed is None:
            missing_seeds.append(sample_id)
            continue
        try:
            print(f"[{index}/{len(shots)}] tracking {sample_id}", flush=True)
            tap_result = tapnext_tracker(shot, seed)  # type: ignore[operator]
            trajectory = build_tapnextpp_trajectory(
                shot=shot,
                seed=seed,
                tracks_xy=tap_result["tracks_xy"],
                occluded=tap_result["occluded"],
                confidence=tap_result.get("confidence"),
                checkpoint=checkpoint_path,
                frame_indices=tap_result.get("frame_indices"),
                frame_stride=int(tap_result.get("frame_stride") or frame_stride),
            )
            if cotracker_tracker is not None:
                cotracker_frames = cotracker_tracker(shot, seed)  # type: ignore[operator]
                trajectory = apply_cotracker_crosscheck(
                    trajectory,
                    cotracker_frames=cotracker_frames,
                    max_distance_px=max_distance_px,
                )
            trajectory_path = _contained_child(trajectories_dir, f"{_safe_path_segment(sample_id, 'sample')}.json")
            _write_json(trajectory_path, trajectory)
            trajectory_paths.append(str(trajectory_path))
            processed += 1
            print(f"[{index}/{len(shots)}] wrote {trajectory_path}", flush=True)
        except Exception as exc:  # noqa: BLE001 - batch report should retain per-shot failures.
            failed.append({"sampleId": sample_id, "error": str(exc)})
            print(f"[{index}/{len(shots)}] failed {sample_id}: {exc}", flush=True)

    report = {
        "status": "ok" if not failed else "partial",
        "batchIndex": str(batch_index_path),
        "seeds": str(seeds_path),
        "outputDir": str(output_dir),
        "processed": processed,
        "missingSeeds": missing_seeds,
        "failed": failed,
        "trajectories": trajectory_paths,
        "crossCheck": {
            "model": "cotracker3",
            "required": require_cotracker,
            "maxDistancePx": max_distance_px,
            "enabled": cotracker_tracker is not None,
        },
        "trackingWindow": {
            "maxFramesAfterSeed": int(max_frames_after_seed),
            "frameStride": int(frame_stride),
        },
    }
    _write_json(output_dir / "tracking_report.json", report)
    return report


def _default_annotation_root() -> Path:
    return Path(__file__).resolve().parents[4] / "tracknetv6-dataset-annotation"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    annotation_root = _default_annotation_root()
    parser = argparse.ArgumentParser(description="Run TAPNext++ + CoTracker3 tracking from M1 seed labels")
    parser.add_argument("--batch-index", type=Path, default=annotation_root / "work/m1_batch/batch_index.json")
    parser.add_argument("--seeds", type=Path, default=annotation_root / "work/m1_sota_tracking/seeds.json")
    parser.add_argument("--output-dir", type=Path, default=annotation_root / "work/m1_sota_tracking")
    parser.add_argument("--max-distance-px", type=float, default=8.0)
    parser.add_argument("--device", default=None, help="Compatibility fallback device for both models")
    parser.add_argument("--tapnext-device", default=None, help="CUDA device for TAPNext++, e.g. cuda:0")
    parser.add_argument("--cotracker-device", default=None, help="CUDA device for CoTracker3, e.g. cuda:1")
    parser.add_argument("--cotracker-mode", choices=["online", "offline"], default="online")
    parser.add_argument("--max-frames-after-seed", type=int, default=240, help="Maximum original frames after the seed frame to track")
    parser.add_argument("--frame-stride", type=int, default=1, help="Frame sampling stride within the seed-to-impact window")
    parser.add_argument("--allow-missing-cotracker", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = run_sota_tracking(
        batch_index_path=args.batch_index,
        seeds_path=args.seeds,
        output_dir=args.output_dir,
        max_distance_px=args.max_distance_px,
        require_cotracker=not args.allow_missing_cotracker,
        device=args.device,
        tapnext_device=args.tapnext_device,
        cotracker_device=args.cotracker_device,
        cotracker_mode=args.cotracker_mode,
        max_frames_after_seed=args.max_frames_after_seed,
        frame_stride=args.frame_stride,
    )
    print(json.dumps(report, ensure_ascii=False))
    return 0 if not report["failed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
