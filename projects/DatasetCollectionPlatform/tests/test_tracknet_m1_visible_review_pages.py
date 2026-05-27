from __future__ import annotations

import json
from pathlib import Path
import sys

import cv2
import numpy as np

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLATFORM_ROOT / "tools"))

from render_tracknet_m1_visible_review_pages import render_visible_review_pages


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _visible_artifact(video_path: Path | None = None) -> dict:
    return {
        "version": "1.0",
        "stage": "m1_visible_tracking",
        "sampleId": "sample_001",
        "shotId": "shot_001",
        "sessionId": "session_001",
        "sourceVideo": str(video_path) if video_path else "/missing/sample.mov",
        "frameWidth": 160,
        "frameHeight": 90,
        "seed": {
            "ballCenter": {"frameIndex": 0, "x": 20.0, "y": 60.0, "visible": True},
            "clubheadCenter": {"frameIndex": 0, "x": 10.0, "y": 70.0, "visible": True},
        },
        "clubheadTrackToImpact": [
            {"frameIndex": 0, "x": 10.0, "y": 70.0, "visible": True, "confidence": 0.9, "labelEligible": False},
            {"frameIndex": 1, "x": 18.0, "y": 66.0, "visible": True, "confidence": 0.9, "labelEligible": False},
        ],
        "ballRawObservedFrames": [
            {"frameIndex": 0, "x": 20.0, "y": 60.0, "visible": True, "confidence": 1.0, "source": "manual_seed_static", "labelEligible": False},
            {"frameIndex": 1, "visible": False, "source": "occluded_by_clubhead", "confidence": 0.0, "labelEligible": False},
            {"frameIndex": 2, "x": 36.0, "y": 45.0, "visible": True, "confidence": 0.9, "source": "seeded_motion_reacquisition", "labelEligible": False},
            {"frameIndex": 3, "x": 48.0, "y": 35.0, "visible": True, "confidence": 0.86, "source": "seeded_motion_reacquisition", "labelEligible": False},
        ],
        "ballSmoothVisibleFrames": [
            {"frameIndex": 2, "x": 36.0, "y": 45.0, "visible": True, "confidence": 0.9, "source": "filtered_visible_observation", "labelEligible": False},
            {"frameIndex": 3, "x": 48.0, "y": 35.0, "visible": True, "confidence": 0.86, "source": "filtered_visible_observation", "labelEligible": False},
        ],
        "impactWindow": {"startFrame": 1, "launchFrame": 2},
        "launchFrame": 2,
        "lastReliableFrame": 3,
        "qc": {"status": "ok", "issues": [], "needsHumanReview": False},
        "trainingLabelPolicy": {"automaticFramesLabelEligible": False},
    }


def test_visible_review_pages_write_index_and_sample_page(tmp_path: Path):
    _write_json(tmp_path / "visible/sample_001.json", _visible_artifact())

    report = render_visible_review_pages(
        visible_trajectories_dir=tmp_path / "visible",
        output_dir=tmp_path / "out",
    )

    assert report["sampleCount"] == 1
    assert (tmp_path / "out/index.html").exists()
    assert (tmp_path / "out/sample_001.html").exists()
    page = (tmp_path / "out/sample_001.html").read_text(encoding="utf-8")
    assert "window.VISIBLE_TRACKING_DATA" in page
    assert "rawBall" in page
    assert "smoothBall" in page
    assert "clubhead" in page
    assert "impactWindow" in page
    assert "lastReliableFrame" in page


def test_visible_review_page_marks_occluded_frames_not_label_eligible(tmp_path: Path):
    _write_json(tmp_path / "visible/sample_001.json", _visible_artifact())

    render_visible_review_pages(
        visible_trajectories_dir=tmp_path / "visible",
        output_dir=tmp_path / "out",
    )

    page = (tmp_path / "out/sample_001.html").read_text(encoding="utf-8")
    assert "occluded_by_clubhead" in page
    assert '"visible": false' in page
    assert '"labelEligible": false' in page


def test_visible_review_pages_write_single_video_preview(tmp_path: Path):
    video_path = tmp_path / "sample.mp4"
    writer = cv2.VideoWriter(str(video_path), cv2.VideoWriter_fourcc(*"mp4v"), 4.0, (160, 90))
    assert writer.isOpened()
    for index in range(4):
        frame = np.zeros((90, 160, 3), dtype=np.uint8)
        frame[:, :, 1] = 30 + index * 30
        writer.write(frame)
    writer.release()
    _write_json(tmp_path / "visible/sample_001.json", _visible_artifact(video_path))

    report = render_visible_review_pages(
        visible_trajectories_dir=tmp_path / "visible",
        output_dir=tmp_path / "out",
    )

    video_output = tmp_path / "out/videos/sample_001.mp4"
    assert video_output.exists()
    assert video_output.stat().st_size > 0
    assert report["generatedVideos"] == [str(video_output)]
    assert report["missingVideos"] == []
