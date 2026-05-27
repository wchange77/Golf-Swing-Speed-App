from __future__ import annotations

import json
from pathlib import Path
import sys

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLATFORM_ROOT / "tools"))

from render_tracknet_m1_3d_review_pages import render_3d_review_pages


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _trajectory(video_path: Path) -> dict:
    return {
        "videoOnly3d": {
            "sampleId": "sample_001",
            "sourceVideo": str(video_path),
            "status": "needs_review",
            "launchFrame": 120,
            "landingFrame": 200,
            "landingPointImage": {"x": 800, "y": 560},
            "model": {
                "type": "video_only_ground_plane_ballistic_3d",
                "gravityMetersPerSecond2": 9.80665,
                "calibrationUsed": {
                    "cameraHeightMeters": 1.0,
                    "cameraAngleDegrees": 5.0,
                    "distanceMeters": 4.0,
                },
            },
            "qc": {
                "seedGroundDistanceMeters": 4.1,
                "distanceResidualMeters": 0.1,
                "fit": {"rank": 3, "rmsResidualMeters": 0.12},
                "issues": [],
            },
            "frames": [
                {
                    "frameIndex": 120,
                    "x": 900,
                    "y": 800,
                    "visible": True,
                    "labelEligible": False,
                    "worldMeters": {"x": 0.0, "height": 0.0, "z": 4.0},
                },
                {
                    "frameIndex": 160,
                    "x": 850,
                    "y": 450,
                    "visible": True,
                    "labelEligible": False,
                    "worldMeters": {"x": 0.5, "height": 6.0, "z": 18.0},
                },
            ],
        },
        "trackmanConstrained3d": {
            "sampleId": "sample_001",
            "status": "unavailable_unconfirmed_trackman",
            "reason": "TrackMan metrics were not human-confirmed usable",
            "frames": [],
        },
    }


def _visible_artifact(video_path: Path) -> dict:
    return {
        "sampleId": "sample_001",
        "sourceVideo": str(video_path),
        "fps": 240.0,
        "launchFrame": 120,
        "impactWindow": {"startFrame": 118, "launchFrame": 120},
        "lastReliableFrame": 160,
        "clubheadTrackToImpact": [
            {"frameIndex": 100, "x": 700.0, "y": 850.0, "visible": True, "labelEligible": False},
            {"frameIndex": 120, "x": 900.0, "y": 800.0, "visible": True, "labelEligible": False},
        ],
        "ballRawObservedFrames": [
            {"frameIndex": 118, "x": 910.0, "y": 812.0, "visible": False, "source": "occluded_by_clubhead"},
            {"frameIndex": 120, "x": 900.0, "y": 800.0, "visible": True, "source": "reacquired_ball"},
        ],
        "ballSmoothVisibleFrames": [
            {"frameIndex": 120, "x": 900.0, "y": 800.0, "visible": True, "labelEligible": False},
            {"frameIndex": 160, "x": 850.0, "y": 450.0, "visible": True, "labelEligible": False},
        ],
    }


def test_render_3d_review_pages_writes_one_video_per_sample_with_overlay_data(tmp_path: Path):
    video_path = tmp_path / "source.mov"
    video_path.write_bytes(b"video")
    _write_json(tmp_path / "trajectories/sample_001.trajectory_3d.json", _trajectory(video_path))
    _write_json(tmp_path / "visible/sample_001.json", _visible_artifact(video_path))

    report = render_3d_review_pages(
        trajectories_dir=tmp_path / "trajectories",
        visible_trajectories_dir=tmp_path / "visible",
        output_dir=tmp_path / "out",
    )

    assert report["sampleCount"] == 1
    assert report["samples"][0]["videoOnlyFrameCount"] == 2
    assert report["samples"][0]["rawBallPointCount"] == 2
    assert report["samples"][0]["smoothBallPointCount"] == 2
    assert report["samples"][0]["clubheadPointCount"] == 2
    assert report["samples"][0]["trackmanStatus"] == "unavailable_unconfirmed_trackman"
    assert (tmp_path / "out/index.html").exists()
    assert (tmp_path / "out/review_report.json").exists()
    sample_page = tmp_path / "out/samples/sample_001.html"
    assert sample_page.exists()
    html = sample_page.read_text(encoding="utf-8")
    assert "<video" in html
    assert "<canvas" in html
    assert "../assets/sample_001.mov" in html
    assert "clubheadToImpact" in html
    assert "rawBallObserved" in html
    assert "smoothBallVisible" in html
    assert "videoOnly3d" in html
    assert "trackmanConstrained3d" in html
    assert "unavailable_unconfirmed_trackman" in html
    assert "curveModelingStatus" in html
    assert "not_modeled_gravity_only" in html
    assert "labelEligible" in html
    assert "false" in html
    assert (tmp_path / "out/assets/sample_001.mov").exists()


def test_render_3d_review_pages_reports_trackman_endpoint_curve_model(tmp_path: Path):
    video_path = tmp_path / "source.mov"
    video_path.write_bytes(b"video")
    trajectory = _trajectory(video_path)
    trajectory["trackmanConstrained3d"] = {
        "sampleId": "sample_001",
        "status": "needs_review",
        "model": {"type": "trackman_constrained_endpoint_curve_3d"},
        "trackmanInputs": {"carryYd": 150.0, "apexYd": 30.0, "sideYd": 12.0, "sideSourceField": "carrySide"},
        "qc": {"trackmanComparison": {"issues": []}},
        "frames": [
            {"frameIndex": 120, "x": 900, "y": 800, "visible": True, "labelEligible": False},
            {"frameIndex": 200, "x": 760, "y": 560, "visible": True, "labelEligible": False},
        ],
    }
    _write_json(tmp_path / "trajectories/sample_001.trajectory_3d.json", trajectory)
    _write_json(tmp_path / "visible/sample_001.json", _visible_artifact(video_path))

    report = render_3d_review_pages(
        trajectories_dir=tmp_path / "trajectories",
        visible_trajectories_dir=tmp_path / "visible",
        output_dir=tmp_path / "out",
    )

    html = (tmp_path / "out/samples/sample_001.html").read_text(encoding="utf-8")
    assert report["samples"][0]["curveModelingStatus"] == "trackman_endpoint_curve_modeled"
    assert "trackman_endpoint_curve_modeled" in html
    assert "not_modeled_gravity_only" not in html


def test_render_3d_review_pages_uses_stage_one_payload_embedded_in_trajectory(tmp_path: Path):
    video_path = tmp_path / "source.mov"
    video_path.write_bytes(b"video")
    trajectory = _trajectory(video_path)
    trajectory["stageOneVisibleTracking"] = _visible_artifact(video_path)
    _write_json(tmp_path / "trajectories/sample_001.trajectory_3d.json", trajectory)

    report = render_3d_review_pages(
        trajectories_dir=tmp_path / "trajectories",
        output_dir=tmp_path / "out",
    )

    html = (tmp_path / "out/samples/sample_001.html").read_text(encoding="utf-8")
    assert report["samples"][0]["rawBallPointCount"] == 2
    assert "occluded_by_clubhead" in html
    assert "video_only_ground_plane_ballistic_3d" in html


def test_render_3d_review_pages_includes_m2_side_by_side_contract(tmp_path: Path):
    video_path = tmp_path / "source.mov"
    video_path.write_bytes(b"video")
    trajectory = _trajectory(video_path)
    trajectory["videoOnly3d"]["model"]["type"] = "video_only_rk4_drag_magnus_3d"
    trajectory["videoOnly3d"]["model"]["modelFamily"] = "RK4_drag_magnus"
    trajectory["videoOnly3d"]["parameters"] = {
        "ballSpeed": {"value": 43.2, "status": "estimated", "confidence": 0.62, "evidenceFrames": [120, 160]},
        "launchAngle": {"value": 15.2, "status": "estimated", "confidence": 0.63, "evidenceFrames": [120, 160]},
        "launchDirection": {"value": -3.0, "status": "estimated", "confidence": 0.52, "evidenceFrames": [120, 160]},
        "sideOffset": {"value": 5.5, "status": "estimated", "confidence": 0.44, "evidenceFrames": [120, 160]},
        "spin": {"value": None, "status": "unidentifiable", "confidence": 0.0, "failureReason": "too short"},
    }
    trajectory["trackmanConstrained3d"] = {
        "sampleId": "sample_001",
        "status": "needs_review",
        "model": {"type": "trackman_constrained_rk4_drag_magnus_3d", "modelFamily": "RK4_drag_magnus"},
        "usedTrackManFields": ["ballSpeed", "launchAngle", "carry", "apex", "spinRate", "carrySide"],
        "missingTrackManFields": ["totalSide"],
        "trackmanInputs": {"ballSpeedMph": 100.0, "launchAngleDeg": 16.0, "carryYd": 150.0, "apexYd": 30.0},
        "trackmanInputsProvenance": {"source": "human_confirmed_corrected_fields"},
        "qc": {
            "visibleOverlap": {"rmsePx": 0.0, "p95Px": 0.0, "maxPx": 0.0},
            "trackmanComparison": {"carryResidualYd": 0.0, "apexResidualYd": 0.0, "sideResidualYd": 0.0},
        },
        "frames": [
            {"frameIndex": 120, "x": 900, "y": 800, "visible": True, "labelEligible": False, "worldMeters": {"x": 0.0, "height": 0.0, "z": 4.0}},
            {"frameIndex": 200, "x": 760, "y": 560, "visible": True, "labelEligible": False, "worldMeters": {"x": 8.0, "height": 0.0, "z": 140.0}},
        ],
    }
    _write_json(tmp_path / "trajectories/sample_001.trajectory_3d.json", trajectory)
    _write_json(tmp_path / "visible/sample_001.json", _visible_artifact(video_path))

    report = render_3d_review_pages(
        trajectories_dir=tmp_path / "trajectories",
        visible_trajectories_dir=tmp_path / "visible",
        output_dir=tmp_path / "out",
    )

    html = (tmp_path / "out/samples/sample_001.html").read_text(encoding="utf-8")
    assert report["samples"][0]["curveModelingStatus"] == "trackman_rk4_drag_magnus_modeled"
    assert "sideViewPlot" in html
    assert "topViewPlot" in html
    assert "parameterStatuses" in html
    assert "usedTrackManFields" in html
    assert "missingTrackManFields" in html
    assert "carryResidualYd" in html
    assert "visibleOverlap" in html
    assert "trackman_rk4_drag_magnus_modeled" in html


def test_render_3d_review_pages_marks_trackman_comparison_unavailable(tmp_path: Path):
    video_path = tmp_path / "source.mov"
    video_path.write_bytes(b"video")
    _write_json(tmp_path / "trajectories/sample_001.trajectory_3d.json", _trajectory(video_path))
    _write_json(tmp_path / "visible/sample_001.json", _visible_artifact(video_path))

    render_3d_review_pages(
        trajectories_dir=tmp_path / "trajectories",
        visible_trajectories_dir=tmp_path / "visible",
        output_dir=tmp_path / "out",
    )

    html = (tmp_path / "out/samples/sample_001.html").read_text(encoding="utf-8")
    assert "TrackMan comparison unavailable" in html
