from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable

import cv2

from lib.tracknet_m1_review import LABEL_STUDIO_CONFIG_XML


def _read_frame(video_path: Path, frame_index: int):
    cap = cv2.VideoCapture(str(video_path))
    try:
        if not cap.isOpened():
            return None
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(frame_index))
        ok, frame = cap.read()
        return frame if ok else None
    finally:
        cap.release()


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
        raise RuntimeError(f"unsafe frame path outside {root}")
    return child


def _prediction(trajectory: dict[str, Any], frame: dict[str, Any]) -> dict[str, Any]:
    width = int(trajectory.get("frameWidth") or 0)
    height = int(trajectory.get("frameHeight") or 0)
    return {
        "model_version": "tapnextpp_cotracker3_sota",
        "score": float(frame.get("confidence", 0.0)),
        "result": [{
            "from_name": "ball_center",
            "to_name": "image",
            "type": "keypointlabels",
            "value": {
                "x": float(frame.get("x", 0.0)) / max(width, 1) * 100.0,
                "y": float(frame.get("y", 0.0)) / max(height, 1) * 100.0,
                "width": 0.5,
                "keypointlabels": ["ball"],
            },
        }],
        "trackman": trajectory.get("trackman", {}),
        "sota": {
            "model": trajectory.get("model", {}),
            "crossCheck": frame.get("crossCheck"),
            "needsReview": bool(frame.get("needsReview")),
        },
    }


def _task(trajectory: dict[str, Any], frame: dict[str, Any], image_path: Path) -> dict[str, Any]:
    return {
        "data": {
            "image": image_path.resolve().as_uri(),
            "sample_id": str(trajectory.get("sampleId") or ""),
            "session_id": str(trajectory.get("sessionId") or ""),
            "shot_id": str(trajectory.get("shotId") or ""),
            "frame_index": int(frame["frameIndex"]),
            "frame_width": int(trajectory.get("frameWidth") or 0),
            "frame_height": int(trajectory.get("frameHeight") or 0),
            "source_video": str(trajectory.get("sourceVideo") or ""),
            "trackman": trajectory.get("trackman", {}),
            "sota": {
                "model": trajectory.get("model", {}),
                "crossCheck": frame.get("crossCheck"),
                "confidence": float(frame.get("confidence", 0.0)),
            },
        },
        "predictions": [_prediction(trajectory, frame)],
    }


def export_sota_review_tasks(
    trajectory_paths: Iterable[Path | str],
    output_dir: Path | str,
    *,
    include_all: bool = False,
) -> dict[str, Any]:
    output_dir = Path(output_dir)
    frame_root = output_dir / "frames"
    tasks: list[dict[str, Any]] = []
    trajectories = 0
    skipped_frames = 0
    for item in trajectory_paths:
        trajectory_path = Path(item)
        trajectory = _load_json(trajectory_path)
        trajectories += 1
        session_id = _safe_path_segment(trajectory.get("sessionId"), "unknown_session")
        shot_id = _safe_path_segment(trajectory.get("shotId"), "unknown_shot")
        video_path = Path(str(trajectory.get("sourceVideo") or ""))
        for frame in trajectory.get("frames", []):
            if not include_all and not frame.get("needsReview"):
                skipped_frames += 1
                continue
            frame_index = int(frame["frameIndex"])
            image_dir = _contained_child(frame_root, session_id, shot_id)
            image_dir.mkdir(parents=True, exist_ok=True)
            image_path = image_dir / f"frame_{frame_index:06d}.jpg"
            image = _read_frame(video_path, frame_index)
            if image is not None:
                cv2.imwrite(str(image_path), image, [cv2.IMWRITE_JPEG_QUALITY, 92])
            else:
                image_path.write_bytes(b"")
            tasks.append(_task(trajectory, frame, image_path))

    labelstudio_dir = output_dir / "labelstudio"
    labelstudio_dir.mkdir(parents=True, exist_ok=True)
    tasks_path = labelstudio_dir / "tracknet_m1_tasks.json"
    tasks_path.write_text(json.dumps(tasks, ensure_ascii=False, indent=2), encoding="utf-8")
    (labelstudio_dir / "tracknet_m1_config.xml").write_text(LABEL_STUDIO_CONFIG_XML, encoding="utf-8")
    report = {
        "outputDir": str(output_dir),
        "trajectories": trajectories,
        "tasks": len(tasks),
        "skippedFrames": skipped_frames,
        "labelStudioTasks": str(tasks_path),
    }
    (output_dir / "review_index.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _default_annotation_root() -> Path:
    return Path(__file__).resolve().parents[4] / "tracknetv6-dataset-annotation"


def main(argv: list[str] | None = None) -> int:
    annotation_root = _default_annotation_root()
    parser = argparse.ArgumentParser(description="Export TAPNext++/CoTracker3 trajectories for M1 manual review")
    parser.add_argument("--trajectory", type=Path, action="append", default=[])
    parser.add_argument("--trajectories-dir", type=Path, default=annotation_root / "work/m1_sota_tracking/trajectories")
    parser.add_argument("--output-dir", type=Path, default=annotation_root / "review/m1_sota")
    parser.add_argument("--include-all", action="store_true")
    args = parser.parse_args(argv)
    paths = args.trajectory or sorted(args.trajectories_dir.glob("*.json"))
    report = export_sota_review_tasks(paths, args.output_dir, include_all=args.include_all)
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
