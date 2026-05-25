from __future__ import annotations

import numpy as np

from tools.lib.cotracker_crosscheck import CoTracker3OnlineTracker, apply_cotracker_crosscheck


def _trajectory() -> dict:
    return {
        "frames": [
            {"frameIndex": 0, "x": 10.0, "y": 20.0, "visible": True, "confidence": 0.9, "needsReview": False},
            {"frameIndex": 1, "x": 20.0, "y": 20.0, "visible": True, "confidence": 0.9, "needsReview": False},
            {"frameIndex": 2, "x": 30.0, "y": 20.0, "visible": True, "confidence": 0.9, "needsReview": False},
        ]
    }


def test_marks_agreement_and_disagreement_by_pixel_distance():
    checked = apply_cotracker_crosscheck(
        _trajectory(),
        cotracker_frames=[
            {"frameIndex": 0, "x": 11.0, "y": 21.0, "visible": True, "confidence": 0.8},
            {"frameIndex": 1, "x": 50.0, "y": 50.0, "visible": True, "confidence": 0.8},
            {"frameIndex": 2, "x": 30.0, "y": 20.0, "visible": False, "confidence": 0.2},
        ],
        max_distance_px=5.0,
    )

    assert checked["crossCheck"]["model"] == "cotracker3"
    assert checked["frames"][0]["crossCheck"]["status"] == "agree"
    assert checked["frames"][0]["needsReview"] is False
    assert checked["frames"][1]["crossCheck"]["status"] == "disagree"
    assert checked["frames"][1]["needsReview"] is True
    assert checked["frames"][2]["crossCheck"]["status"] == "cotracker_not_visible"
    assert checked["frames"][2]["needsReview"] is True


def test_marks_missing_cotracker_frame_for_review():
    checked = apply_cotracker_crosscheck(_trajectory(), cotracker_frames=[], max_distance_px=5.0)

    assert checked["frames"][0]["crossCheck"]["status"] == "missing"
    assert all(frame["needsReview"] for frame in checked["frames"])


def test_missing_frames_before_online_cotracker_start_do_not_force_review():
    checked = apply_cotracker_crosscheck(
        _trajectory(),
        cotracker_frames=[
            {"frameIndex": 1, "x": 20.0, "y": 20.0, "visible": True, "confidence": 0.9},
        ],
        max_distance_px=5.0,
    )

    assert checked["frames"][0]["crossCheck"]["status"] == "not_evaluated_before_cotracker_start"
    assert checked["frames"][0]["needsReview"] is False
    assert checked["frames"][2]["crossCheck"]["status"] == "missing"
    assert checked["frames"][2]["needsReview"] is True


def test_cotracker_online_convert_tracks_maps_frame_stride_to_original_frame_indices():
    tracker = CoTracker3OnlineTracker.__new__(CoTracker3OnlineTracker)

    class FakeTensor:
        def __init__(self, value):
            self.value = value

        def __getitem__(self, item):
            return FakeTensor(self.value[item])

        def detach(self):
            return self

        def float(self):
            return self

        def cpu(self):
            return self

        def numpy(self):
            return self.value

    tracks = FakeTensor(np.array([[[[10.0, 20.0]], [[20.0, 30.0]], [[30.0, 40.0]]]]))
    visibility = FakeTensor(np.array([[[True], [False], [True]]]))

    output = tracker._convert_tracks(
        tracks,
        visibility,
        frame_indices=[654, 658, 662],
        target_size=(100, 50),
        original_size=(200, 100),
    )

    assert [frame["frameIndex"] for frame in output] == [654, 658, 662]
    assert output[0]["x"] == 20.0
    assert output[0]["y"] == 40.0
    assert output[1]["visible"] is False
