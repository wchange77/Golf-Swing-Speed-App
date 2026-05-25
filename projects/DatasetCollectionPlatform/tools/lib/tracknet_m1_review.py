from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import cv2

LABEL_STUDIO_CONFIG_XML = """<View>
  <Image name="image" value="$image"/>
  <KeyPointLabels name="ball_center" toName="image" strokeWidth="3">
    <Label value="ball" background="#00FF00"/>
  </KeyPointLabels>
  <Choices name="visibility" toName="image" choice="single">
    <Choice value="visible"/>
    <Choice value="not_visible"/>
    <Choice value="skip"/>
  </Choices>
</View>
"""


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


def _selected_frames(observations: dict[str, Any]) -> list[dict[str, Any]]:
    selected = []
    for frame in observations.get("frames", []):
        if isinstance(frame.get("selected"), dict):
            selected.append(frame)
    return selected


def _prediction(frame: dict[str, Any], frame_width: int, frame_height: int, trackman: dict[str, Any]) -> dict[str, Any]:
    selected = frame["selected"]
    return {
        "model_version": "tracknet_m1_auto_candidate",
        "score": float(selected.get("score", 0.0)),
        "result": [{
            "from_name": "ball_center",
            "to_name": "image",
            "type": "keypointlabels",
            "value": {
                "x": float(selected["x"]) / max(frame_width, 1) * 100.0,
                "y": float(selected["y"]) / max(frame_height, 1) * 100.0,
                "width": 0.5,
                "keypointlabels": ["ball"],
            },
        }],
        "trackman": trackman,
    }


def export_review_tasks(batch_index_path: Path | str, output_dir: Path | str, frames_per_shot: int = 20) -> dict[str, Any]:
    batch_index_path = Path(batch_index_path)
    output_dir = Path(output_dir)
    batch = _load_json(batch_index_path)
    tasks: list[dict[str, Any]] = []
    skipped = 0
    frame_root = output_dir / "frames"
    for shot in batch.get("shots", []):
        observations = _load_json(Path(shot["candidateObservationsPath"]))
        candidates = _selected_frames(observations)
        if not candidates:
            skipped += 1
            continue
        if frames_per_shot > 0:
            candidates = candidates[:frames_per_shot]
        video_path = Path(shot["sourceVideo"])
        frame_width = int(shot["frameWidth"])
        frame_height = int(shot["frameHeight"])
        session_id = _safe_path_segment(shot.get("sessionId"), "unknown_session")
        shot_id = _safe_path_segment(shot.get("shotId"), "unknown_shot")
        sample_id = str(shot["sampleId"])
        for frame in candidates:
            frame_index = int(frame["frameIndex"])
            image_dir = _contained_child(frame_root, session_id, shot_id)
            image_dir.mkdir(parents=True, exist_ok=True)
            image_path = image_dir / f"frame_{frame_index:06d}.jpg"
            image = _read_frame(video_path, frame_index)
            if image is not None:
                cv2.imwrite(str(image_path), image, [cv2.IMWRITE_JPEG_QUALITY, 92])
            else:
                image_path.write_bytes(b"")
            tasks.append({
                "data": {
                    "image": image_path.resolve().as_uri(),
                    "sample_id": sample_id,
                    "session_id": session_id,
                    "shot_id": shot_id,
                    "frame_index": frame_index,
                    "frame_width": frame_width,
                    "frame_height": frame_height,
                    "source_video": str(video_path),
                    "trackman": shot.get("trackmanMatch", {}),
                },
                "predictions": [_prediction(frame, frame_width, frame_height, shot.get("trackmanMatch", {}))],
            })
    labelstudio_dir = output_dir / "labelstudio"
    labelstudio_dir.mkdir(parents=True, exist_ok=True)
    (labelstudio_dir / "tracknet_m1_tasks.json").write_text(
        json.dumps(tasks, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (labelstudio_dir / "tracknet_m1_config.xml").write_text(LABEL_STUDIO_CONFIG_XML, encoding="utf-8")
    report = {
        "batchIndex": str(batch_index_path),
        "outputDir": str(output_dir),
        "tasks": len(tasks),
        "skipped": skipped,
        "labelStudioTasks": str(labelstudio_dir / "tracknet_m1_tasks.json"),
    }
    (output_dir / "review_index.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
