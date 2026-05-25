from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import numpy as np

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLATFORM_ROOT / "tools"))

from lib.tracknet_m1_review import export_review_tasks


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _make_video(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 60.0, (320, 180))
    assert writer.isOpened()
    try:
        for idx in range(40):
            frame = np.zeros((180, 320, 3), dtype=np.uint8)
            frame[:, :] = (24, 96, 28)
            cv2.circle(frame, (80 + idx, 120 - idx // 2), 3, (255, 255, 255), -1)
            writer.write(frame)
    finally:
        writer.release()


def _make_batch_fixture(
    tmp_path: Path,
    *,
    with_candidates: bool = True,
    session_id: str = "sess_001",
    shot_id: str = "shot_001",
    source_video: Path | None = None,
) -> Path:
    video_path = tmp_path / "DatasetCollectorExport/assets/golf_ball_detection/aa/ball.mov"
    if source_video is None:
        _make_video(video_path)
    else:
        video_path = source_video
    observations_path = tmp_path / "autolabel/samples/sess_001/shot_001/ball_observations.json"
    frames = []
    if with_candidates:
        frames = [
            {"frameIndex": 31, "selected": {"x": 82.0, "y": 119.0, "score": 0.9}, "autoConfirmed": True},
            {"frameIndex": 32, "selected": {"x": 87.0, "y": 117.0, "score": 0.88}, "autoConfirmed": True},
        ]
    _write_json(observations_path, {
        "sample": {"sampleId": "sample_001", "sessionId": session_id, "shotId": shot_id},
        "video": {"fps": 60.0, "frameCount": 40, "width": 320, "height": 180},
        "frames": frames,
    })
    batch_path = tmp_path / "m1_batch/batch_index.json"
    _write_json(batch_path, {
        "version": "1.0",
        "sourceExportDir": str(tmp_path / "DatasetCollectorExport"),
        "shots": [{
            "sessionId": session_id,
            "shotId": shot_id,
            "sampleId": "sample_001",
            "sourceVideo": str(video_path),
            "candidateObservationsPath": str(observations_path),
            "frameWidth": 320,
            "frameHeight": 180,
            "frameCount": 40,
            "fps": 60.0,
            "trackmanMatch": {"timeDeltaSeconds": 1.25, "metrics": {"ballSpeedMph": 145.0}},
        }],
        "unusableSamples": [],
        "summary": {"usableShots": 1},
    })
    return batch_path


def test_export_review_tasks_writes_labelstudio_tasks_and_frame_images(tmp_path):
    batch_index_path = _make_batch_fixture(tmp_path)
    output_dir = tmp_path / "review"
    report = export_review_tasks(batch_index_path, output_dir, frames_per_shot=2)
    assert report["tasks"] == 2
    assert (output_dir / "labelstudio" / "tracknet_m1_tasks.json").exists()
    assert (output_dir / "labelstudio" / "tracknet_m1_config.xml").exists()
    tasks = json.loads((output_dir / "labelstudio" / "tracknet_m1_tasks.json").read_text(encoding="utf-8"))
    assert tasks[0]["data"]["sample_id"] == "sample_001"
    assert tasks[0]["data"]["shot_id"] == "shot_001"
    assert tasks[0]["data"]["trackman"]["timeDeltaSeconds"] == 1.25
    assert tasks[0]["predictions"][0]["result"][0]["type"] == "keypointlabels"
    assert tasks[0]["predictions"][0]["result"][0]["value"]["keypointlabels"] == ["ball"]
    assert Path(tasks[0]["data"]["image"].replace("file://", "")).exists()


def test_export_review_tasks_does_not_export_candidate_free_shot(tmp_path):
    batch_index_path = _make_batch_fixture(tmp_path, with_candidates=False)
    output_dir = tmp_path / "review"
    report = export_review_tasks(batch_index_path, output_dir, frames_per_shot=2)
    assert report["skipped"] == 1
    assert report["tasks"] == 0
    tasks = json.loads((output_dir / "labelstudio" / "tracknet_m1_tasks.json").read_text(encoding="utf-8"))
    assert tasks == []


def test_export_review_tasks_sanitizes_frame_output_path_segments(tmp_path):
    batch_index_path = _make_batch_fixture(
        tmp_path,
        session_id="../sess",
        shot_id="../shot",
        source_video=tmp_path / "missing.mov",
    )
    output_dir = tmp_path / "review"

    export_review_tasks(batch_index_path, output_dir, frames_per_shot=1)

    tasks = json.loads((output_dir / "labelstudio" / "tracknet_m1_tasks.json").read_text(encoding="utf-8"))
    frame_path = Path(tasks[0]["data"]["image"].replace("file://", "")).resolve()
    frames_root = (output_dir / "frames").resolve()
    assert frame_path.is_relative_to(frames_root)
    assert not (output_dir / "sess").exists()
    assert not (output_dir / "shot").exists()
