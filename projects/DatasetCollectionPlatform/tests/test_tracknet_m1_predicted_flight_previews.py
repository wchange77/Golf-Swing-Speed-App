from __future__ import annotations

import json
from pathlib import Path
import sys

import numpy as np

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLATFORM_ROOT / "tools"))

import render_tracknet_m1_predicted_flight_previews


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _prediction(path: str, variant: str) -> dict:
    return {
        "sampleId": "sample_001",
        "sourceVideo": path,
        "frameWidth": 1920,
        "frameHeight": 1080,
        "seed": {"frameIndex": 10, "x": 100.0, "y": 100.0},
        "frames": [
            {"frameIndex": 10, "x": 100.0, "y": 100.0, "visible": True},
            {"frameIndex": 11, "x": 110.0, "y": 96.0, "visible": True},
        ],
        "clubheadTrack": [
            {"frameIndex": 10, "x": 60.0, "y": 120.0, "visible": True},
            {"frameIndex": 11, "x": 70.0, "y": 119.0, "visible": True},
        ],
        "predictedFlight": {
            "status": "needs_review",
            "variant": variant,
            "frames": [
                {"frameIndex": 10, "x": 100.0, "y": 100.0, "visible": True, "source": "observed"},
                {"frameIndex": 11, "x": 110.0, "y": 96.0, "visible": True, "source": "predicted_image_only"},
            ],
        },
    }


def test_render_prediction_previews_writes_video_reports_and_index(tmp_path: Path, monkeypatch):
    prediction_path = tmp_path / "predictions/image_only/trajectories/sample_001.json"
    _write_json(prediction_path, _prediction("/data/sample_001.mov", "image_only"))

    class FakeCapture:
        def __init__(self, path):  # noqa: ANN001
            self.path = path
            self.frame = 0

        def isOpened(self):
            return True

        def set(self, prop, value):  # noqa: ANN001
            self.frame = int(value)
            return True

        def read(self):
            image = np.zeros((1080, 1920, 3), dtype=np.uint8)
            image[:, :, 0] = (self.frame * 20) % 255
            self.frame += 1
            return True, image

        def release(self):
            return None

    class FakeWriter:
        instances = []

        def __init__(self, path, fourcc, fps, size):  # noqa: ANN001
            self.path = path
            self.fps = fps
            self.size = size
            self.frames = []
            FakeWriter.instances.append(self)

        def write(self, image):
            self.frames.append(image.copy())

        def release(self):
            return None

    monkeypatch.setattr(render_tracknet_m1_predicted_flight_previews.cv2, "VideoCapture", FakeCapture)
    monkeypatch.setattr(render_tracknet_m1_predicted_flight_previews.cv2, "VideoWriter", FakeWriter)
    monkeypatch.setattr(render_tracknet_m1_predicted_flight_previews.cv2, "VideoWriter_fourcc", lambda *args: 0)

    report = render_tracknet_m1_predicted_flight_previews.render_prediction_previews(
        tmp_path / "predictions",
        tmp_path / "preview",
        variants=["image_only"],
        columns=1,
        cell_size=(320, 180),
        frame_stride=1,
        max_output_frames=2,
    )

    assert report["videos"][0]["variant"] == "image_only"
    assert report["videos"][0]["framesWritten"] == 2
    assert FakeWriter.instances[0].size == (320, 180)
    assert len(FakeWriter.instances[0].frames) == 2
    html = (tmp_path / "preview/index.html").read_text(encoding="utf-8")
    assert "image_only" in html
    assert "Legacy/debug review-only" in html
    assert "video_only_3d" in html
    assert "trackman_constrained_3d" in html
