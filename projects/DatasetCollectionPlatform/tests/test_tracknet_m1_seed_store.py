from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.lib.tracknet_m1_seed_store import SeedValidationError, TrackNetM1SeedStore


def _shot() -> dict:
    return {
        "sessionId": "sess_001",
        "shotId": "shot_001",
        "sampleId": "sample_001",
        "sourceVideo": "/data/video.mov",
        "frameCount": 2400,
        "fps": 239.9,
        "frameWidth": 320,
        "frameHeight": 180,
        "trackmanMatch": {"timeDeltaSeconds": 0.027},
    }


def test_saves_and_loads_one_seed_per_sample(tmp_path: Path):
    store = TrackNetM1SeedStore(tmp_path / "seeds.json", [_shot()])

    saved = store.save_seed("sample_001", {"frameIndex": 12, "x": 80, "y": 90}, reviewer="tester")

    assert saved["sampleId"] == "sample_001"
    assert saved["frameIndex"] == 12
    assert saved["x"] == 80.0
    assert saved["y"] == 90.0
    assert saved["reviewer"] == "tester"
    reloaded = TrackNetM1SeedStore(tmp_path / "seeds.json", [_shot()])
    assert reloaded.seed_for("sample_001")["frameIndex"] == 12


def test_saving_same_sample_updates_seed_instead_of_duplicating(tmp_path: Path):
    store = TrackNetM1SeedStore(tmp_path / "seeds.json", [_shot()])

    store.save_seed("sample_001", {"frameIndex": 12, "x": 80, "y": 90}, reviewer="tester")
    store.save_seed("sample_001", {"frameIndex": 20, "x": 81, "y": 91}, reviewer="tester")

    payload = json.loads((tmp_path / "seeds.json").read_text(encoding="utf-8"))
    assert len(payload["seeds"]) == 1
    assert payload["seeds"][0]["frameIndex"] == 20
    assert store.progress() == {"total": 1, "seeded": 1, "missing": 0}


def test_rejects_unknown_sample_outside_frame_and_outside_image(tmp_path: Path):
    store = TrackNetM1SeedStore(tmp_path / "seeds.json", [_shot()])

    with pytest.raises(SeedValidationError, match="unknown sample"):
        store.save_seed("missing", {"frameIndex": 12, "x": 80, "y": 90}, reviewer="tester")
    with pytest.raises(SeedValidationError, match="outside video"):
        store.save_seed("sample_001", {"frameIndex": 2400, "x": 80, "y": 90}, reviewer="tester")
    with pytest.raises(SeedValidationError, match="outside frame"):
        store.save_seed("sample_001", {"frameIndex": 12, "x": 321, "y": 90}, reviewer="tester")


def test_api_payload_includes_shot_metadata_and_existing_seed(tmp_path: Path):
    store = TrackNetM1SeedStore(tmp_path / "seeds.json", [_shot()])
    store.save_seed("sample_001", {"frameIndex": 12, "x": 80, "y": 90}, reviewer="tester")

    payload = store.api_payload()

    assert payload["progress"] == {"total": 1, "seeded": 1, "missing": 0}
    assert payload["shots"][0]["sampleId"] == "sample_001"
    assert payload["shots"][0]["seed"]["x"] == 80.0
    assert payload["shots"][0]["frameCount"] == 2400


def test_loads_legacy_on_disk_seed_as_normalized_dual_seed(tmp_path: Path):
    seed_path = tmp_path / "seeds.json"
    seed_path.write_text(json.dumps({
        "version": "1.0",
        "seeds": [{
            "sampleId": "sample_001",
            "sessionId": "sess_001",
            "shotId": "shot_001",
            "sourceVideo": "/data/video.mov",
            "frameIndex": 12,
            "x": 80,
            "y": 90,
            "createdAt": "2026-01-01T00:00:00Z",
            "updatedAt": "2026-01-01T00:01:00Z",
        }],
    }), encoding="utf-8")
    store = TrackNetM1SeedStore(seed_path, [_shot()])

    seed = store.seed_for("sample_001")

    assert seed["seedFrame"] == seed["frameIndex"]
    assert seed["points"]["ball_center"] == {"x": 80.0, "y": 90.0, "visible": True}
    assert seed["points"]["clubhead_center"]["visible"] is False
    assert seed["patches"]["ball_patch"] == {"radiusPx": 8, "grid": "3x3"}
    assert seed["patches"]["clubhead_patch"] == {"radiusPx": 18, "grid": "5x5"}
    assert seed["createdAt"] == "2026-01-01T00:00:00Z"
    assert seed["updatedAt"] == "2026-01-01T00:01:00Z"
    assert store.api_payload()["shots"][0]["seed"]["points"]["ball_center"]["visible"] is True


def test_saves_dual_seed_with_patch_configuration(tmp_path):
    store = TrackNetM1SeedStore(tmp_path / "seeds.json", [{
        "sampleId": "sample_001",
        "frameCount": 240,
        "frameWidth": 1920,
        "frameHeight": 1080,
    }])

    seed = store.save_seed("sample_001", {
        "seedFrame": 100,
        "points": {
            "ball_center": {"x": 900, "y": 916, "visible": True},
            "clubhead_center": {"x": 860, "y": 930, "visible": True},
        },
        "patches": {
            "ball_patch": {"radiusPx": 8, "grid": "3x3"},
            "clubhead_patch": {"radiusPx": 18, "grid": "5x5"},
        },
    }, reviewer="tester")

    assert seed["points"]["ball_center"]["x"] == 900.0
    assert seed["patches"]["clubhead_patch"]["grid"] == "5x5"
    assert seed["reviewer"] == "tester"


def test_rejects_dual_seed_points_that_are_too_close_without_override(tmp_path):
    store = TrackNetM1SeedStore(tmp_path / "seeds.json", [{
        "sampleId": "sample_001",
        "frameCount": 240,
        "frameWidth": 1920,
        "frameHeight": 1080,
    }])

    with pytest.raises(SeedValidationError, match="too close"):
        store.save_seed("sample_001", {
            "seedFrame": 100,
            "points": {
                "ball_center": {"x": 900, "y": 916, "visible": True},
                "clubhead_center": {"x": 905, "y": 918, "visible": True},
            },
        }, reviewer="tester")


def test_rejects_dual_seed_points_exactly_twelve_pixels_apart_without_override(tmp_path):
    store = TrackNetM1SeedStore(tmp_path / "seeds.json", [{
        "sampleId": "sample_001",
        "frameCount": 240,
        "frameWidth": 1920,
        "frameHeight": 1080,
    }])

    with pytest.raises(SeedValidationError, match="too close"):
        store.save_seed("sample_001", {
            "seedFrame": 100,
            "points": {
                "ball_center": {"x": 900, "y": 916, "visible": True},
                "clubhead_center": {"x": 912, "y": 916, "visible": True},
            },
        }, reviewer="tester")


def test_allows_seed_override_with_reason(tmp_path):
    store = TrackNetM1SeedStore(tmp_path / "seeds.json", [{
        "sampleId": "sample_001",
        "frameCount": 240,
        "frameWidth": 1920,
        "frameHeight": 1080,
    }])

    seed = store.save_seed("sample_001", {
        "seedFrame": 100,
        "overrideReason": "clubhead overlaps ball in address frame",
        "points": {
            "ball_center": {"x": 900, "y": 916, "visible": True},
            "clubhead_center": {"x": 905, "y": 918, "visible": True},
        },
    }, reviewer="tester")

    assert seed["overrideReason"] == "clubhead overlaps ball in address frame"


def test_rejects_malformed_dual_seed_payloads_with_validation_errors(tmp_path):
    store = TrackNetM1SeedStore(tmp_path / "seeds.json", [{
        "sampleId": "sample_001",
        "frameCount": 240,
        "frameWidth": 1920,
        "frameHeight": 1080,
    }])

    with pytest.raises(SeedValidationError, match="seedFrame"):
        store.save_seed("sample_001", {
            "points": {
                "ball_center": {"x": 900, "y": 916, "visible": True},
            },
        }, reviewer="tester")

    with pytest.raises(SeedValidationError, match="points.ball_center"):
        store.save_seed("sample_001", {
            "seedFrame": 100,
            "points": {
                "clubhead_center": {"x": 860, "y": 930, "visible": True},
            },
        }, reviewer="tester")

    with pytest.raises(SeedValidationError, match="clubhead_center"):
        store.save_seed("sample_001", {
            "seedFrame": 100,
            "points": {
                "ball_center": {"x": 900, "y": 916, "visible": True},
            },
        }, reviewer="tester")
