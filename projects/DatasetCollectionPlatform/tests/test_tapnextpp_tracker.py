from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from tools.lib.tapnextpp_tracker import (
    SeedPoint,
    TapNextPPTracker,
    _read_next_resized_rgb_frame,
    _tapnext_point_to_image_xy,
    build_tapnextpp_trajectory,
    frames_needing_review,
    install_tapnet_import_shim,
)


def _shot() -> dict:
    return {
        "sessionId": "sess_001",
        "shotId": "shot_001",
        "sampleId": "sample_001",
        "sourceVideo": "/data/video.mov",
        "frameCount": 3,
        "fps": 239.9,
        "frameWidth": 320,
        "frameHeight": 180,
    }


def test_builds_tracknet_trajectory_from_tapnextpp_output():
    seed = SeedPoint(sample_id="sample_001", frame_index=0, x=80.0, y=90.0)

    trajectory = build_tapnextpp_trajectory(
        shot=_shot(),
        seed=seed,
        tracks_xy=[(80.0, 90.0), (84.5, 89.0), (90.0, 87.5)],
        occluded=[False, False, True],
        confidence=[0.99, 0.87, 0.20],
        checkpoint=Path("/home/data_0/models/tapnet/tapnextpp_checkpoint.pt"),
    )

    assert trajectory["sampleId"] == "sample_001"
    assert trajectory["model"]["name"] == "tapnextpp"
    assert trajectory["seed"] == {"frameIndex": 0, "x": 80.0, "y": 90.0}
    assert trajectory["frames"] == [
        {"frameIndex": 0, "x": 80.0, "y": 90.0, "visible": True, "confidence": 0.99, "needsReview": False, "source": "tapnextpp_seed_tracker"},
        {"frameIndex": 1, "x": 84.5, "y": 89.0, "visible": True, "confidence": 0.87, "needsReview": False, "source": "tapnextpp_seed_tracker"},
        {"frameIndex": 2, "x": 90.0, "y": 87.5, "visible": False, "confidence": 0.2, "needsReview": True, "source": "tapnextpp_seed_tracker"},
    ]


def test_marks_low_confidence_out_of_bounds_and_missing_frames_for_review():
    seed = SeedPoint(sample_id="sample_001", frame_index=0, x=80.0, y=90.0)

    trajectory = build_tapnextpp_trajectory(
        shot=_shot(),
        seed=seed,
        tracks_xy=[(80.0, 90.0), (999.0, 89.0)],
        occluded=[False, False],
        confidence=[0.49, 0.95],
        checkpoint=Path("/home/data_0/models/tapnet/tapnextpp_checkpoint.pt"),
    )

    assert [frame["frameIndex"] for frame in frames_needing_review(trajectory)] == [0, 1, 2]
    assert trajectory["frames"][0]["needsReview"] is True
    assert trajectory["frames"][1]["needsReview"] is True
    assert trajectory["frames"][2]["visible"] is False
    assert trajectory["frames"][2]["confidence"] == 0.0


def test_builds_sampled_trajectory_with_non_contiguous_original_frame_indices():
    seed = SeedPoint(sample_id="sample_001", frame_index=240, x=80.0, y=90.0)

    trajectory = build_tapnextpp_trajectory(
        shot=_shot(),
        seed=seed,
        tracks_xy=[(80.0, 90.0), (84.5, 89.0), (90.0, 87.5)],
        occluded=[False, False, False],
        confidence=[0.99, 0.87, 0.75],
        checkpoint=Path("/home/data_0/models/tapnet/tapnextpp_checkpoint.pt"),
        frame_indices=[240, 244, 248],
        frame_stride=4,
    )

    assert trajectory["frameCount"] == 3
    assert trajectory["sourceFrameCount"] == 3
    assert trajectory["sampling"] == {"startFrame": 240, "frameStride": 4, "sampledFrameCount": 3}
    assert [frame["frameIndex"] for frame in trajectory["frames"]] == [240, 244, 248]


def test_tapnet_import_shim_bypasses_legacy_tensorflow_init(tmp_path, monkeypatch):
    repo = tmp_path / "tapnet_repo"
    package = repo / "tapnet"
    tapnext = package / "tapnext"
    tapnext.mkdir(parents=True)
    (package / "__init__.py").write_text("raise RuntimeError('legacy init executed')\n", encoding="utf-8")
    (tapnext / "demo_module.py").write_text("VALUE = 42\n", encoding="utf-8")

    monkeypatch.syspath_prepend(str(repo))
    install_tapnet_import_shim(repo)

    import importlib

    module = importlib.import_module("tapnet.tapnext.demo_module")

    assert module.VALUE == 42


def test_read_next_resized_rgb_frame_reads_sequentially_without_frame_seek():
    class FakeCapture:
        def __init__(self):
            self.frames = [
                np.zeros((4, 6, 3), dtype=np.uint8),
                np.ones((4, 6, 3), dtype=np.uint8) * 255,
            ]
            self.set_calls = []

        def set(self, *args):
            self.set_calls.append(args)

        def read(self):
            if not self.frames:
                return False, None
            return True, self.frames.pop(0)

    cap = FakeCapture()

    first = _read_next_resized_rgb_frame(cap, size=(8, 8))
    second = _read_next_resized_rgb_frame(cap, size=(8, 8))

    assert cap.set_calls == []
    assert first.shape == (8, 8, 3)
    assert second.shape == (8, 8, 3)


def test_tapnext_model_point_is_yx_and_converts_to_image_xy():
    x, y = _tapnext_point_to_image_xy([120.0, 121.0], width=1920, height=1080)

    assert round(x, 3) == 907.5
    assert round(y, 3) == 506.25


def test_tapnext_tracker_starts_at_seed_as_local_frame_zero_and_maps_sampled_frames(monkeypatch):
    torch = pytest.importorskip("torch")

    class FakeCapture:
        CAP_PROP_POS_FRAMES = 1

        instances = []

        def __init__(self, path):
            self.path = path
            self.current = 0
            self.set_calls = []
            self.read_indices = []
            FakeCapture.instances.append(self)

        def isOpened(self):
            return True

        def get(self, prop):
            return {7: 20, 3: 320, 4: 180}.get(prop, 0)

        def set(self, prop, value):
            self.set_calls.append((prop, int(value)))
            self.current = int(value)

        def read(self):
            if self.current >= 20:
                return False, None
            self.read_indices.append(self.current)
            value = self.current
            self.current += 1
            frame = np.full((18, 32, 3), value, dtype=np.uint8)
            return True, frame

        def release(self):
            pass

    class FakeModel:
        def __init__(self):
            self.queries = []
            self.calls = 0

        def __call__(self, *, video, query_points=None, state=None):
            self.calls += 1
            if query_points is not None:
                self.queries.append(query_points.detach().cpu())
            point_yx = torch.tensor([[[[128.0 + self.calls, 64.0 + self.calls]]]], dtype=torch.float32)
            track_logits = torch.ones((1, 1, 1, 512), dtype=torch.float32)
            visible_logits = torch.ones((1, 1, 1, 1), dtype=torch.float32)
            return point_yx, track_logits, visible_logits, object()

    monkeypatch.setattr("tools.lib.tapnextpp_tracker.cv2.VideoCapture", FakeCapture)
    monkeypatch.setattr("tools.lib.tapnextpp_tracker.cv2.CAP_PROP_FRAME_COUNT", 7)
    monkeypatch.setattr("tools.lib.tapnextpp_tracker.cv2.CAP_PROP_FRAME_WIDTH", 3)
    monkeypatch.setattr("tools.lib.tapnextpp_tracker.cv2.CAP_PROP_FRAME_HEIGHT", 4)
    monkeypatch.setattr("tools.lib.tapnextpp_tracker.cv2.CAP_PROP_POS_FRAMES", 1)

    tracker = TapNextPPTracker.__new__(TapNextPPTracker)
    tracker.checkpoint = Path("/home/data_0/models/tapnet/tapnextpp_checkpoint.pt")
    tracker.model = FakeModel()
    tracker.tracker_certainty = lambda pred_tracks, track_logits, radius: torch.ones((1, 1, 1, 1))
    tracker.device = "cpu"
    tracker.use_certainty = False
    tracker.certainty_radius = 8
    tracker.confidence_threshold = 0.5
    tracker.max_frames_after_seed = 4
    tracker.frame_stride = 2

    result = tracker.track(_shot() | {"frameCount": 20, "frameWidth": 320, "frameHeight": 180}, SeedPoint("sample_001", 10, 80.0, 90.0))

    capture = FakeCapture.instances[0]
    assert capture.set_calls == [(1, 10), (1, 12), (1, 14)]
    assert capture.read_indices == [10, 12, 14]
    assert result["frame_indices"] == [10, 12, 14]
    query = tracker.model.queries[0]
    assert query[0, 0, 0].item() == 0.0
    assert query[0, 0, 1].item() == 128.0
    assert query[0, 0, 2].item() == 64.0
