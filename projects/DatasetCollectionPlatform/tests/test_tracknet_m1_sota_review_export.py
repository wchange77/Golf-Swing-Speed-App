from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import numpy as np

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLATFORM_ROOT / "tools"))

from export_tracknet_m1_sota_review import export_sota_review_tasks


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _make_video(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 60.0, (320, 180))
    assert writer.isOpened()
    try:
        for idx in range(5):
            frame = np.zeros((180, 320, 3), dtype=np.uint8)
            cv2.circle(frame, (80 + idx, 90), 3, (255, 255, 255), -1)
            writer.write(frame)
    finally:
        writer.release()


def test_export_sota_review_tasks_uses_only_needs_review_frames(tmp_path):
    video_path = tmp_path / "video.mov"
    _make_video(video_path)
    trajectory_path = tmp_path / "m1_sota_tracking/trajectories/sample_001.json"
    _write_json(trajectory_path, {
        "version": "1.0",
        "sampleId": "sample_001",
        "sessionId": "sess_001",
        "shotId": "shot_001",
        "sourceVideo": str(video_path),
        "frameCount": 3,
        "fps": 60.0,
        "frameWidth": 320,
        "frameHeight": 180,
        "trackman": {"timeDeltaSeconds": 0.027},
        "model": {"name": "tapnextpp", "checkpoint": "/home/data_0/models/tapnet/tapnextpp_checkpoint.pt"},
        "frames": [
            {"frameIndex": 0, "x": 80.0, "y": 90.0, "visible": True, "confidence": 0.99, "needsReview": False},
            {"frameIndex": 1, "x": 84.0, "y": 90.0, "visible": True, "confidence": 0.30, "needsReview": True},
            {"frameIndex": 2, "x": 130.0, "y": 140.0, "visible": True, "confidence": 0.88, "needsReview": True, "crossCheck": {"status": "disagree"}},
        ],
    })

    report = export_sota_review_tasks([trajectory_path], tmp_path / "review")

    tasks_path = tmp_path / "review/labelstudio/tracknet_m1_tasks.json"
    tasks = json.loads(tasks_path.read_text(encoding="utf-8"))
    assert report["tasks"] == 2
    assert [task["data"]["frame_index"] for task in tasks] == [1, 2]
    assert tasks[0]["data"]["source_video"] == str(video_path)
    assert tasks[0]["data"]["trackman"]["timeDeltaSeconds"] == 0.027
    assert tasks[0]["predictions"][0]["model_version"] == "tapnextpp_cotracker3_sota"
    assert tasks[0]["predictions"][0]["result"][0]["value"]["keypointlabels"] == ["ball"]
    assert Path(tasks[0]["data"]["image"].replace("file://", "")).exists()


def test_export_sota_review_tasks_sanitizes_frame_output_path_segments(tmp_path):
    trajectory_path = tmp_path / "m1_sota_tracking/trajectories/bad.json"
    _write_json(trajectory_path, {
        "version": "1.0",
        "sampleId": "sample_001",
        "sessionId": "../sess",
        "shotId": "../shot",
        "sourceVideo": str(tmp_path / "missing.mov"),
        "frameWidth": 320,
        "frameHeight": 180,
        "frames": [
            {"frameIndex": 1, "x": 84.0, "y": 90.0, "visible": True, "confidence": 0.30, "needsReview": True},
        ],
    })

    export_sota_review_tasks([trajectory_path], tmp_path / "review")

    tasks = json.loads((tmp_path / "review/labelstudio/tracknet_m1_tasks.json").read_text(encoding="utf-8"))
    frame_path = Path(tasks[0]["data"]["image"].replace("file://", "")).resolve()
    frames_root = (tmp_path / "review/frames").resolve()
    assert frame_path.is_relative_to(frames_root)
    assert not (tmp_path / "review/sess").exists()
    assert not (tmp_path / "review/shot").exists()
