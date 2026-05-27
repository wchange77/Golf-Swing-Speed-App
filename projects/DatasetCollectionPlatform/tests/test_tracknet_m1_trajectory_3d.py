from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLATFORM_ROOT / "tools"))

from lib.tracknet_m1_trajectory_3d import (
    GRAVITY_MPS2,
    build_trackman_constrained_3d_trajectory,
    build_video_only_3d_trajectory,
)
from run_tracknet_m1_3d_reconstruction import run_3d_reconstruction


def _visible_artifact() -> dict:
    return {
        "sampleId": "sample_001",
        "shotId": "shot_001",
        "sessionId": "sess_001",
        "fps": 240.0,
        "frameWidth": 1920,
        "frameHeight": 1080,
        "seed": {"ballCenter": {"frameIndex": 100, "x": 908.0, "y": 911.0}},
        "launchFrame": 120,
        "lastReliableFrame": 180,
        "ballSmoothVisibleFrames": [
            {"frameIndex": 121, "x": 900.0, "y": 820.0, "visible": True, "confidence": 0.9},
            {"frameIndex": 130, "x": 875.0, "y": 590.0, "visible": True, "confidence": 0.9},
            {"frameIndex": 150, "x": 850.0, "y": 410.0, "visible": True, "confidence": 0.9},
            {"frameIndex": 180, "x": 836.0, "y": 350.0, "visible": True, "confidence": 0.9},
        ],
    }


def _camera() -> dict:
    return {
        "intrinsics": {"fx": 1272.5, "fy": 1272.5, "cx": 960.0, "cy": 540.0},
        "calibration": {"cameraHeightMeters": 1.0, "cameraAngleDegrees": 0.0, "distanceMeters": 4.0},
    }


def _assert_unavailable_schema(trajectory: dict, status: str, reason_match: str):
    assert trajectory["version"] == "1.0"
    assert trajectory["stage"] == "m1_3d_reconstruction"
    assert trajectory["generatedAt"].endswith("Z")
    assert trajectory["sampleId"] == "sample_001"
    assert trajectory["shotId"] == "shot_001"
    assert trajectory["sessionId"] == "sess_001"
    assert trajectory["status"] == status
    assert reason_match in trajectory["reason"]
    assert trajectory["frames"] == []


def test_video_only_3d_trajectory_lands_on_ground_plane():
    result = build_video_only_3d_trajectory(_visible_artifact(), _camera())

    trajectory = result["videoOnly3d"]
    assert trajectory["status"] == "needs_review"
    assert trajectory["landingFrame"] == trajectory["frames"][-1]["frameIndex"]
    assert trajectory["frames"][-1]["worldMeters"]["height"] <= 0.05
    assert 0 <= trajectory["landingPointImage"]["x"] < 1920
    assert 0 <= trajectory["landingPointImage"]["y"] < 1080
    assert all(frame["labelEligible"] is False for frame in trajectory["frames"])


def test_3d_trajectory_schemas_carry_source_video():
    artifact = _visible_artifact()
    artifact["sourceVideo"] = "/data/sample.mov"
    confirmed = {
        "metricsUsable": True,
        "correctedFields": {
            "ballSpeed": {"normalizedValue": 100.0, "normalizedUnit": "mph"},
            "launchAngle": {"normalizedValue": 16.0, "normalizedUnit": "deg"},
        },
    }
    unconfirmed = {"metricsUsable": False, "correctedFields": {}}

    video = build_video_only_3d_trajectory(artifact, _camera())["videoOnly3d"]
    trackman = build_trackman_constrained_3d_trajectory(artifact, _camera(), confirmed)["trackmanConstrained3d"]
    unavailable = build_trackman_constrained_3d_trajectory(artifact, _camera(), unconfirmed)["trackmanConstrained3d"]

    assert video["sourceVideo"] == "/data/sample.mov"
    assert trackman["sourceVideo"] == "/data/sample.mov"
    assert unavailable["sourceVideo"] == "/data/sample.mov"


def test_video_only_3d_trajectory_accepts_prebuilt_geometry_evidence():
    geometry_evidence = {
        "status": "ok",
        "intrinsics": {
            "source": "avfoundation_intrinsics",
            "role": "strong_geometry",
            "values": {"fx": 1272.5, "fy": 1272.5, "cx": 960.0, "cy": 540.0},
        },
        "cameraPose": {"heightMeters": 1.0, "pitchDegrees": 0.0},
        "ballOrigin": {"distanceMeters": 4.0, "role": "strong_geometry"},
    }

    result = build_video_only_3d_trajectory(_visible_artifact(), {"geometryEvidence": geometry_evidence})

    trajectory = result["videoOnly3d"]
    assert trajectory["status"] == "needs_review"
    assert trajectory["model"]["calibrationUsed"] == {
        "cameraHeightMeters": 1.0,
        "cameraAngleDegrees": 0.0,
        "distanceMeters": 4.0,
    }
    assert trajectory["frames"]


def test_video_only_3d_trajectory_requires_three_visible_points():
    artifact = _visible_artifact()
    artifact["ballSmoothVisibleFrames"] = artifact["ballSmoothVisibleFrames"][:2]

    with pytest.raises(ValueError, match="three visible"):
        build_video_only_3d_trajectory(artifact, _camera())


def test_video_only_3d_trajectory_uses_nonzero_camera_pitch_and_records_calibration():
    camera = _camera()
    camera["calibration"]["cameraAngleDegrees"] = 10.0

    result = build_video_only_3d_trajectory(_visible_artifact(), camera)

    trajectory = result["videoOnly3d"]
    assert trajectory["status"] == "needs_review"
    assert trajectory["frames"][-1]["worldMeters"]["height"] <= 0.05
    assert trajectory["model"]["calibrationUsed"] == {
        "cameraHeightMeters": 1.0,
        "cameraAngleDegrees": 10.0,
        "distanceMeters": 4.0,
    }
    qc = trajectory["qc"]
    assert qc["seedGroundDistanceMeters"] > 0
    assert qc["distanceResidualMeters"] == pytest.approx(qc["seedGroundDistanceMeters"] - 4.0)
    assert qc["fit"]["rank"] == 3
    assert qc["fit"]["rmsResidualMeters"] <= qc["fit"]["residualThresholdMeters"]
    assert all(frame["labelEligible"] is False for frame in trajectory["frames"])


@pytest.mark.parametrize("missing_key", ["cameraHeightMeters", "cameraAngleDegrees"])
def test_video_only_3d_trajectory_requires_explicit_calibration_values(missing_key: str):
    camera = _camera()
    del camera["calibration"][missing_key]

    with pytest.raises(ValueError, match=missing_key):
        build_video_only_3d_trajectory(_visible_artifact(), camera)


@pytest.mark.parametrize(
    ("intrinsics_update", "message"),
    [
        ({"fx": 0.0}, "fx"),
        ({"fy": float("nan")}, "fy"),
        ({"cx": None}, "cx"),
    ],
)
def test_video_only_3d_trajectory_rejects_invalid_intrinsics(intrinsics_update: dict, message: str):
    camera = _camera()
    camera["intrinsics"].update(intrinsics_update)

    with pytest.raises(ValueError, match=message):
        build_video_only_3d_trajectory(_visible_artifact(), camera)


def test_video_only_3d_trajectory_rejects_downward_only_observations():
    artifact = _visible_artifact()
    artifact["ballSmoothVisibleFrames"] = [
        {"frameIndex": 121, "x": 907.0, "y": 920.0, "visible": True, "confidence": 0.9},
        {"frameIndex": 130, "x": 906.0, "y": 932.0, "visible": True, "confidence": 0.9},
        {"frameIndex": 150, "x": 905.0, "y": 948.0, "visible": True, "confidence": 0.9},
    ]

    with pytest.raises(ValueError, match="positive vertical velocity"):
        build_video_only_3d_trajectory(artifact, _camera())


def test_video_only_3d_trajectory_rejects_rank_deficient_visible_points():
    artifact = _visible_artifact()
    artifact["ballSmoothVisibleFrames"] = [
        {"frameIndex": 121, "x": 875.0, "y": 590.0, "visible": True, "confidence": 0.9},
        {"frameIndex": 130, "x": 875.0, "y": 590.0, "visible": True, "confidence": 0.9},
        {"frameIndex": 150, "x": 875.0, "y": 590.0, "visible": True, "confidence": 0.9},
    ]

    with pytest.raises(ValueError, match="rank-deficient"):
        build_video_only_3d_trajectory(artifact, _camera())


def test_video_only_3d_trajectory_rejects_high_residual_visible_points():
    artifact = _visible_artifact()
    artifact["ballSmoothVisibleFrames"] = [
        {"frameIndex": 121, "x": 900.0, "y": 820.0, "visible": True, "confidence": 0.9},
        {"frameIndex": 130, "x": 875.0, "y": 590.0, "visible": True, "confidence": 0.9},
        {"frameIndex": 150, "x": 850.0, "y": 410.0, "visible": True, "confidence": 0.9},
        {"frameIndex": 5000, "x": 850.0, "y": 410.0, "visible": True, "confidence": 0.9},
    ]

    with pytest.raises(ValueError, match="residual"):
        build_video_only_3d_trajectory(artifact, _camera())


def test_video_only_3d_trajectory_reports_distance_mismatch_qc_issue():
    camera = _camera()
    camera["calibration"]["distanceMeters"] = 12.0

    result = build_video_only_3d_trajectory(_visible_artifact(), camera)

    qc = result["videoOnly3d"]["qc"]
    assert qc["distanceResidualMeters"] == pytest.approx(qc["seedGroundDistanceMeters"] - 12.0)
    assert qc["issues"] == [
        {
            "code": "seed_ground_distance_mismatch",
            "message": "seed ground distance differs from calibration distanceMeters",
        }
    ]


def test_trackman_constrained_trajectory_uses_confirmed_metrics():
    reviewed = {
        "metricsUsable": True,
        "correctedFields": {
            "ballSpeed": {"normalizedValue": 100.0, "normalizedUnit": "mph"},
            "launchAngle": {"normalizedValue": 16.0, "normalizedUnit": "deg"},
            "carry": {"normalizedValue": 150.0, "normalizedUnit": "yd"},
            "apex": {"normalizedValue": 30.0, "normalizedUnit": "yd"},
            "carrySide": {"normalizedValue": 12.0, "normalizedUnit": "yd", "direction": "right"},
        },
        "reviewer": "human_001",
    }

    result = build_trackman_constrained_3d_trajectory(_visible_artifact(), _camera(), reviewed)

    trajectory = result["trackmanConstrained3d"]
    assert trajectory["status"] == "needs_review"
    assert trajectory["model"]["type"] == "trackman_constrained_endpoint_curve_3d"
    assert trajectory["model"]["gravityMetersPerSecond2"] == GRAVITY_MPS2
    assert trajectory["model"]["verticalAccelerationMetersPerSecond2"] == pytest.approx(-GRAVITY_MPS2)
    assert trajectory["trackmanInputs"] == {
        "ballSpeedMph": 100.0,
        "launchAngleDeg": 16.0,
        "carryYd": 150.0,
        "apexYd": 30.0,
        "sideYd": 12.0,
        "sideSourceField": "carrySide",
    }
    assert trajectory["trackmanInputsProvenance"]["source"] == "human_confirmed_corrected_fields"
    assert trajectory["landingFrame"] == trajectory["frames"][-1]["frameIndex"]
    assert trajectory["frames"][-1]["worldMeters"]["height"] <= 0.05
    landing = trajectory["frames"][-1]["worldMeters"]
    dx = landing["x"] - trajectory["parameters"]["x0Meters"]
    dz = landing["z"] - trajectory["parameters"]["z0Meters"]
    horizontal_carry_m = (dx**2 + dz**2) ** 0.5
    assert horizontal_carry_m == pytest.approx(((150.0**2 + 12.0**2) ** 0.5) * 0.9144, abs=0.2)
    assert trajectory["parameters"]["forwardCarryMeters"] == pytest.approx(150.0 * 0.9144, abs=0.01)
    assert trajectory["parameters"]["sideCarryMeters"] == pytest.approx(12.0 * 0.9144, abs=0.01)
    assert trajectory["parameters"]["apexMeters"] == pytest.approx(30.0 * 0.9144, abs=0.01)
    qc = trajectory["qc"]["trackmanComparison"]
    assert qc["predictedCarryYd"] == pytest.approx(150.0, abs=0.01)
    assert qc["confirmedCarryYd"] == 150.0
    assert qc["carryResidualYd"] == pytest.approx(0.0, abs=0.01)
    assert qc["carryMismatchThresholdYd"] == pytest.approx(22.5)
    assert qc["predictedSideYd"] == pytest.approx(12.0, abs=0.01)
    assert qc["confirmedSideYd"] == 12.0
    assert qc["sideResidualYd"] == pytest.approx(0.0, abs=0.01)
    assert qc["confirmedApexYd"] == 30.0
    assert qc["apexResidualYd"] == pytest.approx(0.0, abs=0.01)
    assert qc["apexMismatchThresholdYd"] == pytest.approx(6.0)
    assert qc["issues"] == []
    assert 0 <= trajectory["landingPointImage"]["x"] < 1920
    assert 0 <= trajectory["landingPointImage"]["y"] < 1080
    assert all(frame["labelEligible"] is False for frame in trajectory["frames"])


def test_trackman_constrained_trajectory_uses_curve_separately_from_side_endpoint():
    reviewed = {
        "metricsUsable": True,
        "correctedFields": {
            "ballSpeed": {"normalizedValue": 100.0, "normalizedUnit": "mph"},
            "launchAngle": {"normalizedValue": 16.0, "normalizedUnit": "deg"},
            "carry": {"normalizedValue": 150.0, "normalizedUnit": "yd"},
            "apex": {"normalizedValue": 30.0, "normalizedUnit": "yd"},
            "carrySide": {"normalizedValue": 8.0, "normalizedUnit": "yd", "direction": "left"},
            "curve": {"normalizedValue": 3.0, "normalizedUnit": "yd", "direction": "right"},
        },
    }

    result = build_trackman_constrained_3d_trajectory(_visible_artifact(), _camera(), reviewed)

    trajectory = result["trackmanConstrained3d"]
    inputs = trajectory["trackmanInputs"]
    params = trajectory["parameters"]
    assert inputs["sideYd"] == -8.0
    assert inputs["curveYd"] == 3.0
    assert inputs["curveSourceField"] == "curve"
    assert inputs["launchLineSideYd"] == -11.0
    assert params["sideCarryMeters"] == pytest.approx(-8.0 * 0.9144, abs=0.01)
    assert params["curveMeters"] == pytest.approx(3.0 * 0.9144, abs=0.01)
    assert params["launchLineSideMeters"] == pytest.approx(-11.0 * 0.9144, abs=0.01)


def test_trackman_constrained_trajectory_hard_constrains_visible_ball_projection():
    reviewed = {
        "metricsUsable": True,
        "correctedFields": {
            "ballSpeed": {"normalizedValue": 100.0, "normalizedUnit": "mph"},
            "launchAngle": {"normalizedValue": 16.0, "normalizedUnit": "deg"},
            "carry": {"normalizedValue": 150.0, "normalizedUnit": "yd"},
            "apex": {"normalizedValue": 30.0, "normalizedUnit": "yd"},
            "carrySide": {"normalizedValue": 12.0, "normalizedUnit": "yd", "direction": "right"},
            "curve": {"normalizedValue": 4.0, "normalizedUnit": "yd", "direction": "right"},
        },
    }

    result = build_trackman_constrained_3d_trajectory(_visible_artifact(), _camera(), reviewed)

    trajectory = result["trackmanConstrained3d"]
    by_frame = {frame["frameIndex"]: frame for frame in trajectory["frames"]}
    for observed in _visible_artifact()["ballSmoothVisibleFrames"]:
        if observed["frameIndex"] <= _visible_artifact()["lastReliableFrame"]:
            constrained = by_frame[observed["frameIndex"]]
            assert constrained["x"] == pytest.approx(observed["x"], abs=0.001)
            assert constrained["y"] == pytest.approx(observed["y"], abs=0.001)
            assert constrained["source"] == "visible_ball_hard_constraint"
    qc = trajectory["qc"]["visibleOverlap"]
    assert qc["status"] == "ok"
    assert qc["rmsePx"] == pytest.approx(0.0)
    assert qc["pointCount"] == len(_visible_artifact()["ballSmoothVisibleFrames"])


def test_trackman_constrained_trajectory_records_additional_curve_model_inputs():
    reviewed = {
        "metricsUsable": True,
        "correctedFields": {
            "ballSpeed": {"normalizedValue": 100.0, "normalizedUnit": "mph"},
            "launchAngle": {"normalizedValue": 16.0, "normalizedUnit": "deg"},
            "carry": {"normalizedValue": 150.0, "normalizedUnit": "yd"},
            "apex": {"normalizedValue": 30.0, "normalizedUnit": "yd"},
            "curve": {"normalizedValue": 6.0, "normalizedUnit": "yd", "direction": "left"},
            "carrySide": {"normalizedValue": 10.0, "normalizedUnit": "yd", "direction": "left"},
            "totalSide": {"normalizedValue": 14.0, "normalizedUnit": "yd", "direction": "left"},
            "faceToPath": {"normalizedValue": 2.5, "normalizedUnit": "deg"},
            "clubPath": {"normalizedValue": -1.2, "normalizedUnit": "deg"},
            "faceAngle": {"normalizedValue": 1.3, "normalizedUnit": "deg"},
            "spinRate": {"normalizedValue": 3500.0, "normalizedUnit": "rpm"},
        },
    }

    result = build_trackman_constrained_3d_trajectory(_visible_artifact(), _camera(), reviewed)

    inputs = result["trackmanConstrained3d"]["trackmanInputs"]
    assert inputs["curveYd"] == -6.0
    assert inputs["sideYd"] == -10.0
    assert inputs["totalSideYd"] == -14.0
    assert inputs["faceToPathDeg"] == 2.5
    assert inputs["clubPathDeg"] == -1.2
    assert inputs["faceAngleDeg"] == 1.3
    assert inputs["spinRateRpm"] == 3500.0


def test_trackman_constrained_trajectory_accepts_chinese_unit_aliases():
    reviewed = {
        "metricsUsable": True,
        "correctedFields": {
            "ballSpeed": {"normalizedValue": 100.0, "normalizedUnit": "英里"},
            "launchAngle": {"normalizedValue": 16.0, "normalizedUnit": "度"},
            "carry": {"normalizedValue": 150.0, "normalizedUnit": "码"},
            "apex": {"normalizedValue": 30.0, "normalizedUnit": "码"},
        },
    }

    result = build_trackman_constrained_3d_trajectory(_visible_artifact(), _camera(), reviewed)

    trajectory = result["trackmanConstrained3d"]
    assert trajectory["status"] == "needs_review"
    assert trajectory["frames"]


def test_trackman_constrained_trajectory_rejects_unconfirmed_trackman():
    reviewed = {
        "metricsUsable": False,
        "correctedFields": {
            "ballSpeed": {"normalizedValue": 100.0, "normalizedUnit": "mph"},
            "launchAngle": {"normalizedValue": 16.0, "normalizedUnit": "deg"},
        },
    }

    result = build_trackman_constrained_3d_trajectory(_visible_artifact(), _camera(), reviewed)

    _assert_unavailable_schema(
        result["trackmanConstrained3d"],
        "unavailable_unconfirmed_trackman",
        "not human-confirmed usable",
    )


@pytest.mark.parametrize("metrics_usable", ["true", "false", 1])
def test_trackman_constrained_trajectory_requires_metrics_usable_true(metrics_usable):
    reviewed = {
        "metricsUsable": metrics_usable,
        "correctedFields": {
            "ballSpeed": {"normalizedValue": 100.0, "normalizedUnit": "mph"},
            "launchAngle": {"normalizedValue": 16.0, "normalizedUnit": "deg"},
        },
    }

    result = build_trackman_constrained_3d_trajectory(_visible_artifact(), _camera(), reviewed)

    _assert_unavailable_schema(
        result["trackmanConstrained3d"],
        "unavailable_unconfirmed_trackman",
        "not human-confirmed usable",
    )


@pytest.mark.parametrize(
    ("reviewed", "reason_match"),
    [
        ("not a dict", "TrackMan review payload must be an object"),
        ({"metricsUsable": True, "correctedFields": "not a dict"}, "correctedFields must be an object"),
    ],
)
def test_trackman_constrained_trajectory_rejects_malformed_review_payloads(reviewed, reason_match: str):
    result = build_trackman_constrained_3d_trajectory(_visible_artifact(), _camera(), reviewed)

    _assert_unavailable_schema(
        result["trackmanConstrained3d"],
        "unavailable_invalid_trackman_fields",
        reason_match,
    )


@pytest.mark.parametrize(
    ("reviewed", "status", "reason_match"),
    [
        (
            {
                "metricsUsable": True,
                "correctedFields": {
                    "ballSpeed": {"normalizedValue": 100.0, "normalizedUnit": "mph"},
                },
            },
            "unavailable_missing_required_trackman_fields",
            "launchAngle",
        ),
        (
            {
                "metricsUsable": True,
                "correctedFields": {
                    "ballSpeed": {"normalizedValue": 160.0, "normalizedUnit": "kph"},
                    "launchAngle": {"normalizedValue": 16.0, "normalizedUnit": "deg"},
                },
            },
            "unavailable_invalid_trackman_units",
            "ballSpeed",
        ),
    ],
)
def test_trackman_constrained_trajectory_requires_corrected_metrics(reviewed: dict, status: str, reason_match: str):
    result = build_trackman_constrained_3d_trajectory(_visible_artifact(), _camera(), reviewed)

    trajectory = result["trackmanConstrained3d"]
    _assert_unavailable_schema(trajectory, status, reason_match)


@pytest.mark.parametrize(
    ("field_name", "value", "reason_match"),
    [
        ("ballSpeed", 10.0, "ballSpeed"),
        ("ballSpeed", 250.1, "ballSpeed"),
        ("launchAngle", 0.0, "launchAngle"),
        ("launchAngle", 80.0, "launchAngle"),
        ("carry", 500.1, "carry"),
        ("apex", 200.1, "apex"),
    ],
)
def test_trackman_constrained_trajectory_rejects_out_of_range_metrics(
    field_name: str,
    value: float,
    reason_match: str,
):
    corrected_fields = {
        "ballSpeed": {"normalizedValue": 100.0, "normalizedUnit": "mph"},
        "launchAngle": {"normalizedValue": 16.0, "normalizedUnit": "deg"},
        "carry": {"normalizedValue": 150.0, "normalizedUnit": "yd"},
        "apex": {"normalizedValue": 30.0, "normalizedUnit": "yd"},
    }
    corrected_fields[field_name]["normalizedValue"] = value
    reviewed = {"metricsUsable": True, "correctedFields": corrected_fields}

    result = build_trackman_constrained_3d_trajectory(_visible_artifact(), _camera(), reviewed)

    _assert_unavailable_schema(
        result["trackmanConstrained3d"],
        "unavailable_invalid_trackman_fields",
        reason_match,
    )


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_run_3d_reconstruction_writes_video_only_outputs(tmp_path: Path):
    visible_path = tmp_path / "visible/trajectories/sample_001.json"
    camera_path = tmp_path / "sample.camera.json"
    _write_json(visible_path, _visible_artifact())
    _write_json(camera_path, _camera())

    report = run_3d_reconstruction(
        visible_trajectories_dir=tmp_path / "visible/trajectories",
        output_dir=tmp_path / "out",
        camera_sidecar_by_sample={"sample_001": camera_path},
    )

    output_path = tmp_path / "out/trajectories/sample_001.trajectory_3d.json"
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert report["processed"] == 1
    assert report["failed"] == []
    assert report["trajectories"] == [str(output_path)]
    assert payload["videoOnly3d"]["status"] == "needs_review"
    assert payload["videoOnly3d"]["frames"]
    assert "trackmanConstrained3d" not in payload


def test_run_3d_reconstruction_accepts_flat_stage_one_seed_schema(tmp_path: Path):
    visible = _visible_artifact()
    visible["seed"] = visible["seed"]["ballCenter"]
    visible_path = tmp_path / "visible/trajectories/sample_001.json"
    camera_path = tmp_path / "sample.camera.json"
    _write_json(visible_path, visible)
    _write_json(camera_path, _camera())

    report = run_3d_reconstruction(
        visible_trajectories_dir=tmp_path / "visible/trajectories",
        output_dir=tmp_path / "out",
        camera_sidecar_by_sample={"sample_001": camera_path},
    )

    assert report["processed"] == 1
    assert report["failed"] == []
    assert (tmp_path / "out/trajectories/sample_001.trajectory_3d.json").exists()


def test_run_3d_reconstruction_writes_report_and_removes_stale_trajectory_outputs(tmp_path: Path):
    visible_dir = tmp_path / "visible/trajectories"
    stale_path = tmp_path / "out/trajectories/stale.trajectory_3d.json"
    camera_path = tmp_path / "sample.camera.json"
    _write_json(visible_dir / "sample_001.json", _visible_artifact())
    _write_json(camera_path, _camera())
    _write_json(stale_path, {"stale": True})

    report = run_3d_reconstruction(
        visible_trajectories_dir=visible_dir,
        output_dir=tmp_path / "out",
        camera_sidecar_by_sample={"sample_001": camera_path},
    )

    report_path = tmp_path / "out/reconstruction_report.json"
    report_payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert not stale_path.exists()
    assert report_payload == report
    assert report_payload["version"] == "1.0"
    assert report_payload["stage"] == "m1_3d_reconstruction"
    assert report_payload["inputDir"] == str(visible_dir)
    assert report_payload["outputDir"] == str(tmp_path / "out")
    assert report_payload["inputCount"] == 1
    assert report_payload["processed"] == 1
    assert report_payload["failedCount"] == 0
    assert report_payload["trackmanAttempted"] == 0
    assert report_payload["trackmanUnavailable"] == 0
    assert report_payload["trackmanSkipped"] == 1
    assert report_payload["samples"] == [
        {
            "sampleId": "sample_001",
            "status": "processed",
            "trajectoryPath": str(tmp_path / "out/trajectories/sample_001.trajectory_3d.json"),
            "trackmanStatus": "skipped",
        }
    ]


def test_run_3d_reconstruction_records_missing_camera_failure_without_stopping_batch(tmp_path: Path):
    visible_dir = tmp_path / "visible/trajectories"
    camera_path = tmp_path / "sample.camera.json"
    second = _visible_artifact()
    second["sampleId"] = "sample_002"
    _write_json(visible_dir / "sample_001.json", _visible_artifact())
    _write_json(visible_dir / "sample_002.json", second)
    _write_json(camera_path, _camera())

    report = run_3d_reconstruction(
        visible_trajectories_dir=visible_dir,
        output_dir=tmp_path / "out",
        camera_sidecar_by_sample={"sample_001": camera_path, "sample_002": tmp_path / "missing.camera.json"},
    )

    assert report["processed"] == 1
    assert len(report["failed"]) == 1
    assert report["failed"][0]["sampleId"] == "sample_002"
    assert "camera" in report["failed"][0]["error"]
    assert report["failedCount"] == 1
    assert report["trackmanSkipped"] == 2
    assert report["samples"][1]["status"] == "failed"
    assert (tmp_path / "out/trajectories/sample_001.trajectory_3d.json").exists()
    assert not (tmp_path / "out/trajectories/sample_002.trajectory_3d.json").exists()


def test_run_3d_reconstruction_rejects_mismatched_camera_identity(tmp_path: Path):
    visible_dir = tmp_path / "visible/trajectories"
    camera = _camera()
    camera["sampleId"] = "different_sample"
    camera_path = tmp_path / "sample.camera.json"
    _write_json(visible_dir / "sample_001.json", _visible_artifact())
    _write_json(camera_path, camera)

    report = run_3d_reconstruction(
        visible_trajectories_dir=visible_dir,
        output_dir=tmp_path / "out",
        camera_sidecar_by_sample={"sample_001": camera_path},
    )

    assert report["processed"] == 0
    assert report["failedCount"] == 1
    assert report["failed"][0]["sampleId"] == "sample_001"
    assert "camera sampleId mismatch" in report["failed"][0]["error"]
    assert report["samples"] == [
        {
            "sampleId": "sample_001",
            "status": "failed",
            "error": report["failed"][0]["error"],
            "trackmanStatus": "skipped",
        }
    ]
    assert not (tmp_path / "out/trajectories/sample_001.trajectory_3d.json").exists()


def test_run_3d_reconstruction_missing_trackman_review_still_writes_video_only(tmp_path: Path):
    visible_dir = tmp_path / "visible/trajectories"
    camera_path = tmp_path / "sample.camera.json"
    _write_json(visible_dir / "sample_001.json", _visible_artifact())
    _write_json(camera_path, _camera())

    report = run_3d_reconstruction(
        visible_trajectories_dir=visible_dir,
        output_dir=tmp_path / "out",
        camera_sidecar_by_sample={"sample_001": camera_path},
        trackman_review_by_sample={"sample_001": tmp_path / "missing.trackman_review.json"},
    )

    output_path = tmp_path / "out/trajectories/sample_001.trajectory_3d.json"
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert report["processed"] == 1
    assert report["failed"] == []
    assert report["trackmanAttempted"] == 1
    assert report["trackmanUnavailable"] == 1
    assert report["trackmanSkipped"] == 0
    assert payload["videoOnly3d"]["frames"]
    assert payload["trackmanConstrained3d"]["status"].startswith("unavailable_")
    assert "not found" in payload["trackmanConstrained3d"]["reason"]


def test_run_3d_reconstruction_mismatched_trackman_identity_still_writes_video_only(tmp_path: Path):
    visible_dir = tmp_path / "visible/trajectories"
    camera_path = tmp_path / "sample.camera.json"
    review_path = tmp_path / "sample.trackman_review.json"
    review = {
        "sampleId": "different_sample",
        "metricsUsable": True,
        "correctedFields": {
            "ballSpeed": {"normalizedValue": 100.0, "normalizedUnit": "mph"},
            "launchAngle": {"normalizedValue": 16.0, "normalizedUnit": "deg"},
        },
    }
    _write_json(visible_dir / "sample_001.json", _visible_artifact())
    _write_json(camera_path, _camera())
    _write_json(review_path, review)

    report = run_3d_reconstruction(
        visible_trajectories_dir=visible_dir,
        output_dir=tmp_path / "out",
        camera_sidecar_by_sample={"sample_001": camera_path},
        trackman_review_by_sample={"sample_001": review_path},
    )

    payload = json.loads((tmp_path / "out/trajectories/sample_001.trajectory_3d.json").read_text(encoding="utf-8"))
    assert report["processed"] == 1
    assert report["failed"] == []
    assert report["trackmanAttempted"] == 1
    assert report["trackmanUnavailable"] == 1
    assert payload["videoOnly3d"]["frames"]
    assert payload["trackmanConstrained3d"]["status"] == "unavailable_trackman_identity_mismatch"
    assert "TrackMan sampleId mismatch" in payload["trackmanConstrained3d"]["reason"]


def test_trackman_review_dir_mapping_uses_internal_sample_id(tmp_path: Path):
    from run_tracknet_m1_3d_reconstruction import trackman_review_by_sample_from_dir

    review_dir = tmp_path / "reviews"
    _write_json(review_dir / "arbitrary_filename.trackman_review.json", {"sampleId": "sample_001", "metricsUsable": False})

    mapping = trackman_review_by_sample_from_dir(review_dir)

    assert mapping == {"sample_001": review_dir / "arbitrary_filename.trackman_review.json"}


def test_malformed_trackman_review_dir_file_maps_by_filename_and_stays_optional(tmp_path: Path):
    from run_tracknet_m1_3d_reconstruction import trackman_review_by_sample_from_dir

    visible_dir = tmp_path / "visible/trajectories"
    review_dir = tmp_path / "reviews"
    camera_path = tmp_path / "sample.camera.json"
    bad_review_path = review_dir / "sample_001.trackman_review.json"
    _write_json(visible_dir / "sample_001.json", _visible_artifact())
    _write_json(camera_path, _camera())
    bad_review_path.parent.mkdir(parents=True)
    bad_review_path.write_text("{not valid json", encoding="utf-8")

    mapping = trackman_review_by_sample_from_dir(review_dir)
    report = run_3d_reconstruction(
        visible_trajectories_dir=visible_dir,
        output_dir=tmp_path / "out",
        camera_sidecar_by_sample={"sample_001": camera_path},
        trackman_review_by_sample=mapping,
    )

    payload = json.loads((tmp_path / "out/trajectories/sample_001.trajectory_3d.json").read_text(encoding="utf-8"))
    assert mapping == {"sample_001": bad_review_path}
    assert report["processed"] == 1
    assert report["failed"] == []
    assert report["trackmanAttempted"] == 1
    assert report["trackmanUnavailable"] == 1
    assert payload["videoOnly3d"]["frames"]
    assert payload["trackmanConstrained3d"]["status"] == "unavailable_invalid_trackman_review"


def test_main_with_bad_trackman_review_dir_does_not_raise(tmp_path: Path, capsys):
    from run_tracknet_m1_3d_reconstruction import main

    visible_dir = tmp_path / "visible/trajectories"
    review_dir = tmp_path / "reviews"
    source_video = tmp_path / "sample.mov"
    camera_sidecar = source_video.with_suffix(".camera.json")
    visible = _visible_artifact()
    visible["sourceVideo"] = str(source_video)
    _write_json(visible_dir / "sample_001.json", visible)
    _write_json(camera_sidecar, _camera())
    review_dir.mkdir(parents=True)
    (review_dir / "sample_001.trackman_review.json").write_text("{not valid json", encoding="utf-8")

    result = main(
        [
            "--visible-trajectories-dir",
            str(visible_dir),
            "--output-dir",
            str(tmp_path / "out"),
            "--trackman-review-dir",
            str(review_dir),
        ]
    )

    printed = json.loads(capsys.readouterr().out)
    assert result == 0
    assert printed["processed"] == 1
    assert printed["failedCount"] == 0
    assert printed["trackmanAttempted"] == 1
    assert printed["trackmanUnavailable"] == 1


def test_run_3d_reconstruction_writes_confirmed_trackman_and_unavailable_unconfirmed_trackman(tmp_path: Path):
    visible_dir = tmp_path / "visible/trajectories"
    camera_path = tmp_path / "sample.camera.json"
    unconfirmed_path = tmp_path / "unconfirmed.trackman.json"
    confirmed_path = tmp_path / "confirmed.trackman.json"
    confirmed = {
        "metricsUsable": True,
        "correctedFields": {
            "ballSpeed": {"normalizedValue": 100.0, "normalizedUnit": "mph"},
            "launchAngle": {"normalizedValue": 16.0, "normalizedUnit": "deg"},
            "carry": {"normalizedValue": 150.0, "normalizedUnit": "yd"},
            "apex": {"normalizedValue": 30.0, "normalizedUnit": "yd"},
        },
        "reviewer": "human_001",
    }
    unconfirmed = {
        "metricsUsable": False,
        "correctedFields": {
            "ballSpeed": {"normalizedValue": 100.0, "normalizedUnit": "mph"},
            "launchAngle": {"normalizedValue": 16.0, "normalizedUnit": "deg"},
        },
    }
    _write_json(visible_dir / "sample_001.json", _visible_artifact())
    _write_json(camera_path, _camera())
    _write_json(confirmed_path, confirmed)
    _write_json(unconfirmed_path, unconfirmed)

    confirmed_report = run_3d_reconstruction(
        visible_trajectories_dir=visible_dir,
        output_dir=tmp_path / "confirmed_out",
        camera_sidecar_by_sample={"sample_001": camera_path},
        trackman_review_by_sample={"sample_001": confirmed_path},
    )
    unconfirmed_report = run_3d_reconstruction(
        visible_trajectories_dir=visible_dir,
        output_dir=tmp_path / "unconfirmed_out",
        camera_sidecar_by_sample={"sample_001": camera_path},
        trackman_review_by_sample={"sample_001": unconfirmed_path},
    )

    confirmed_payload = json.loads(
        (tmp_path / "confirmed_out/trajectories/sample_001.trajectory_3d.json").read_text(encoding="utf-8")
    )
    unconfirmed_payload = json.loads(
        (tmp_path / "unconfirmed_out/trajectories/sample_001.trajectory_3d.json").read_text(encoding="utf-8")
    )
    assert confirmed_report["processed"] == 1
    assert confirmed_report["unavailableTrackman"] == 0
    assert confirmed_payload["trackmanConstrained3d"]["status"] == "needs_review"
    assert confirmed_payload["trackmanConstrained3d"]["frames"]
    assert unconfirmed_report["processed"] == 1
    assert unconfirmed_report["failed"] == []
    assert unconfirmed_report["unavailableTrackman"] == 1
    assert unconfirmed_payload["trackmanConstrained3d"]["status"] == "unavailable_unconfirmed_trackman"
    assert unconfirmed_payload["trackmanConstrained3d"]["frames"] == []
