from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLATFORM_ROOT / "tools"))

from lib.tracknet_m1_predicted_flight import (
    build_predicted_flight,
    detect_launch_frame,
    validate_predictions,
)
from validate_tracknet_m1_predicted_flight import validate_prediction_root


def _trajectory() -> dict:
    frames = [
        {"frameIndex": 10, "x": 100.0, "y": 100.0, "visible": True, "confidence": 0.98, "crossCheck": {"distancePx": 0.5}},
        {"frameIndex": 11, "x": 100.5, "y": 100.2, "visible": True, "confidence": 0.97, "crossCheck": {"distancePx": 0.6}},
        *[
            {
                "frameIndex": 12 + offset,
                "x": 106.0 + offset * 7.0,
                "y": 95.0 - offset * 5.5 + offset * offset * 0.06,
                "visible": True,
                "confidence": 0.96 - min(offset, 18) * 0.01,
                "crossCheck": {"distancePx": 0.8 + offset * 0.1},
            }
            for offset in range(28)
        ],
    ]
    return {
        "version": "1.0",
        "sampleId": "sample_001",
        "shotId": "shot_001",
        "sessionId": "sess_001",
        "sourceVideo": "/data/sample_001.mov",
        "frameWidth": 1920,
        "frameHeight": 1080,
        "frameCount": 60,
        "fps": 240.0,
        "seed": {"frameIndex": 10, "x": 100.0, "y": 100.0},
        "frames": frames,
        "patchFrames": [
            {**frame, "pointSpreadPx": 5.0 + index, "visiblePointCount": 9, "totalPointCount": 9}
            for index, frame in enumerate(frames)
        ],
        "clubheadTrack": [
            {"frameIndex": 10 + index, "x": 40.0 + index * 5, "y": 110.0 - index, "visible": True, "confidence": 0.9}
            for index in range(30)
        ],
        "clubheadCoTrackerTrack": [
            {"frameIndex": 10 + index, "x": 41.0 + index * 5, "y": 111.0 - index, "visible": True, "confidence": 1.0}
            for index in range(30)
        ],
    }


def _sidecar() -> dict:
    return {
        "calibration": {
            "distanceMeters": 4.0,
            "cameraHeightMeters": 1.0,
            "cameraAngleDegrees": 0.0,
            "method": "manual_distance_lidar_available",
            "confidence": 0.45,
        },
        "intrinsics": {"fx": 1272.5, "fy": 1272.5, "cx": 960.0, "cy": 540.0},
    }


def test_detect_launch_frame_skips_static_seed_frames():
    assert detect_launch_frame(_trajectory()) == 12


def test_image_only_prediction_extends_to_requested_frame():
    prediction = build_predicted_flight(_trajectory(), variant="image_only", output_frame_count=40)

    predicted_flight = prediction["predictedFlight"]
    assert predicted_flight["status"] == "needs_review"
    assert predicted_flight["variant"] == "image_only"
    assert predicted_flight["launchFrame"] == 12
    assert predicted_flight["frames"][-1]["frameIndex"] == 49
    assert predicted_flight["frames"][-1]["source"] == "predicted_image_only"
    assert predicted_flight["frames"][-1]["labelEligible"] is False


@pytest.mark.parametrize("variant", ["image_only", "metric_sidecar"])
def test_prediction_outputs_are_legacy_debug_review_only(variant):
    kwargs = {"camera_sidecar": _sidecar()} if variant == "metric_sidecar" else {}

    prediction = build_predicted_flight(_trajectory(), variant=variant, output_frame_count=18, **kwargs)

    predicted_flight = prediction["predictedFlight"]
    assert predicted_flight["legacy"] is True
    assert predicted_flight["reviewOnly"] is True
    assert predicted_flight["formalM2"] is False
    assert predicted_flight["labelEligible"] is False
    assert predicted_flight["trainingLabelPolicy"] == "legacy_debug_review_only_never_training_truth"
    assert predicted_flight["trainingLabelRejectionReason"] == "legacy_predicted_flight_not_training_truth"
    assert predicted_flight["formalM2Replacement"] == ["videoOnly3d", "trackmanConstrained3d"]
    assert all(frame["labelEligible"] is False for frame in predicted_flight["frames"])
    assert all(frame["trainingLabelRejectionReason"] == "legacy_predicted_flight_not_training_truth" for frame in predicted_flight["frames"])


def test_metric_sidecar_uses_camera_calibration_and_marks_depth_source():
    prediction = build_predicted_flight(
        _trajectory(),
        variant="metric_sidecar",
        camera_sidecar=_sidecar(),
        output_frame_count=40,
    )

    predicted_flight = prediction["predictedFlight"]
    assert predicted_flight["status"] == "needs_review"
    assert predicted_flight["variant"] == "metric_sidecar"
    assert predicted_flight["model"]["gravityMetersPerSecond2"] == 9.80665
    assert predicted_flight["metricEstimates"]["calibration"]["distanceMeters"] == 4.0
    assert predicted_flight["metricEstimates"]["monocularDepthSource"] == "not_available"
    assert predicted_flight["frames"][-1]["source"] == "predicted_metric_sidecar"


def test_prediction_falls_back_to_tapnext_points_when_cotracker_disagrees():
    trajectory = _trajectory()
    for frame in trajectory["frames"]:
        frame["crossCheck"] = {"status": "disagree", "distancePx": 45.0}
    for frame in trajectory["patchFrames"]:
        frame["crossCheck"] = {"status": "disagree", "distancePx": 45.0}

    prediction = build_predicted_flight(trajectory, variant="image_only", output_frame_count=12)

    predicted_flight = prediction["predictedFlight"]
    assert predicted_flight["status"] == "needs_review"
    assert predicted_flight["quality"]["confidence"] < 0.6
    assert predicted_flight["fitPointCount"] >= 3


def test_prediction_rejects_seed_patch_track_without_visible_flight_displacement():
    trajectory = _trajectory()
    trajectory["frames"] = [
        {"frameIndex": 10 + index, "x": 100.0 + (index % 3), "y": 100.0 - (index % 2), "visible": True, "confidence": 0.9}
        for index in range(30)
    ]
    trajectory["patchFrames"] = [
        {**frame, "pointSpreadPx": 7.0, "visiblePointCount": 9, "totalPointCount": 9}
        for frame in trajectory["frames"]
    ]

    prediction = build_predicted_flight(trajectory, variant="image_only", output_frame_count=40)

    predicted_flight = prediction["predictedFlight"]
    assert predicted_flight["status"] == "failed"
    assert predicted_flight["reason"] == "insufficient visible flight displacement"
    assert predicted_flight["legacy"] is True
    assert predicted_flight["labelEligible"] is False
    assert predicted_flight["observationEvidence"]["verticalRisePx"] < 24.0


def test_prediction_with_too_few_fit_points_is_failed_not_drawn_as_full_trajectory():
    trajectory = _trajectory()
    trajectory["frames"] = [
        {"frameIndex": 10, "x": 100.0, "y": 100.0, "visible": True, "confidence": 1.0},
        {"frameIndex": 12, "x": 106.0, "y": 95.0, "visible": True, "confidence": 0.9},
        {"frameIndex": 13, "x": 113.0, "y": 60.0, "visible": True, "confidence": 0.9},
        {"frameIndex": 14, "x": 121.0, "y": 40.0, "visible": True, "confidence": 0.9},
    ]
    trajectory["patchFrames"] = [{**frame, "pointSpreadPx": 5.0} for frame in trajectory["frames"]]

    prediction = build_predicted_flight(trajectory, variant="image_only", output_frame_count=100)

    assert prediction["predictedFlight"]["status"] == "failed"
    assert prediction["predictedFlight"]["reason"] == "insufficient fit points for review trajectory"
    assert prediction["predictedFlight"]["fitPointCount"] < 12


def test_prediction_falls_back_when_strict_fit_stops_after_only_a_few_frames():
    trajectory = _trajectory()
    frames = []
    for offset in range(40):
        confidence = 0.1 if offset == 5 else 0.75
        frames.append({
            "frameIndex": 12 + offset,
            "x": 106.0 + offset * 2.0,
            "y": 95.0 - offset * 5.0 + offset * offset * 0.04,
            "visible": True,
            "confidence": confidence,
        })
    trajectory["frames"] = [
        {"frameIndex": 10, "x": 100.0, "y": 100.0, "visible": True, "confidence": 1.0},
        {"frameIndex": 11, "x": 100.5, "y": 100.0, "visible": True, "confidence": 1.0},
        *frames,
    ]
    trajectory["patchFrames"] = [
        {**frame, "pointSpreadPx": 7.0, "visiblePointCount": 9, "totalPointCount": 9}
        for frame in trajectory["frames"]
    ]

    prediction = build_predicted_flight(trajectory, variant="image_only", output_frame_count=80)

    predicted_flight = prediction["predictedFlight"]
    assert predicted_flight["status"] == "needs_review"
    assert predicted_flight["fitPointCount"] >= 24
    assert predicted_flight["fitFrameRange"][1] >= 35


def test_validate_predictions_does_not_compare_unconfirmed_trackman_ocr():
    prediction = build_predicted_flight(_trajectory(), variant="image_only", output_frame_count=12)

    report = validate_predictions(
        [prediction],
        trackman_ocr_report={
            "items": [
                {
                    "sampleId": "sample_001",
                    "ocrStatus": "ok",
                    "lineCount": 126,
                    "needsHumanConfirmation": True,
                }
            ]
        },
    )

    item = report["items"][0]
    assert item["quality"]["fitPointCount"] >= 12
    assert item["quality"]["reprojectionRmsePx"] >= 0
    assert item["legacyReviewOnly"] is True
    assert item["formalM2"] is False
    assert item["trackmanComparison"]["status"] == "unavailable_unconfirmed_ocr"
    assert item["trackmanComparison"]["ocrStatus"] == "ok"
    assert report["summary"]["legacyReviewOnlyCount"] == 1


def test_validate_predictions_compares_confirmed_structured_trackman_metrics():
    trajectory = _trajectory()
    trajectory["trackman"] = {
        "metricsUsable": True,
        "correctedFields": {
            "ballSpeed": {"normalizedValue": 44.704, "normalizedUnit": "m/s"},
            "launchAngle": {"normalizedValue": 15.0, "normalizedUnit": "deg"},
        },
    }
    prediction = build_predicted_flight(trajectory, variant="metric_sidecar", camera_sidecar=_sidecar(), output_frame_count=12)

    report = validate_predictions([prediction])

    comparison = report["items"][0]["trackmanComparison"]
    assert comparison["status"] == "compared"
    assert comparison["formalM2"] is False
    assert "formal M2 uses video_only_3d and trackman_constrained_3d" in comparison["warning"]
    assert comparison["errors"]["ballSpeedMph"] is not None
    assert comparison["errors"]["launchAngleDeg"] is not None


def test_validate_predictions_compares_confirmed_reviewed_trackman_by_sample():
    prediction = build_predicted_flight(_trajectory(), variant="metric_sidecar", camera_sidecar=_sidecar(), output_frame_count=12)

    report = validate_predictions(
        [prediction],
        trackman_reviewed_by_sample={
            "sample_001": {
                "sampleId": "sample_001",
                "reviewStatus": "accepted",
                "metricsUsable": True,
                "reviewer": "wangwei",
                "correctedFields": {
                    "ballSpeed": {"normalizedValue": 107.9, "normalizedUnit": "mph"},
                    "launchAngle": {"normalizedValue": 16.2, "normalizedUnit": "deg"},
                },
            }
        },
    )

    comparison = report["items"][0]["trackmanComparison"]
    assert comparison["status"] == "compared"
    assert comparison["formalM2"] is False
    assert comparison["trackmanSource"] == "human_confirmed_review"
    assert comparison["trackmanMetrics"]["ballSpeedMph"] == 107.9
    assert comparison["trackmanMetrics"]["launchAngleDeg"] == 16.2


def test_validate_prediction_root_loads_confirmed_trackman_review_dir(tmp_path: Path):
    prediction = build_predicted_flight(_trajectory(), variant="metric_sidecar", camera_sidecar=_sidecar(), output_frame_count=12)
    prediction_dir = tmp_path / "predictions/metric_sidecar/trajectories"
    prediction_dir.mkdir(parents=True)
    (prediction_dir / "sample_001.json").write_text(json.dumps(prediction, ensure_ascii=False), encoding="utf-8")
    review_dir = tmp_path / "trackman_reviewed"
    review_dir.mkdir()
    (review_dir / "sample_001.trackman_review.json").write_text(
        json.dumps(
            {
                "sampleId": "sample_001",
                "reviewStatus": "accepted",
                "metricsUsable": True,
                "reviewer": "wangwei",
                "correctedFields": {
                    "ballSpeed": {"normalizedValue": 107.9, "normalizedUnit": "mph"},
                    "launchAngle": {"normalizedValue": 16.2, "normalizedUnit": "deg"},
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = validate_prediction_root(
        tmp_path / "predictions",
        tmp_path / "qc",
        variants=["metric_sidecar"],
        trackman_review_dir=review_dir,
    )

    assert report["trackmanReviewDir"] == str(review_dir)
    assert report["items"][0]["trackmanComparison"]["status"] == "compared"
    md = (tmp_path / "qc/predicted_flight_qc_report.md").read_text(encoding="utf-8")
    assert "Legacy/debug review-only" in md
    assert "formal M2 uses `video_only_3d` and `trackman_constrained_3d`" in md


def test_build_predictions_writes_variant_outputs(tmp_path: Path):
    source = tmp_path / "source"
    trajectory_path = source / "sample_001.json"
    trajectory_path.parent.mkdir(parents=True)
    trajectory_path.write_text(json.dumps(_trajectory(), ensure_ascii=False), encoding="utf-8")
    video_path = tmp_path / "sample_001.mov"
    video_path.write_bytes(b"")
    payload = json.loads(trajectory_path.read_text(encoding="utf-8"))
    payload["sourceVideo"] = str(video_path)
    trajectory_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    video_path.with_suffix(".camera.json").write_text(json.dumps(_sidecar(), ensure_ascii=False), encoding="utf-8")

    from lib.tracknet_m1_predicted_flight import build_predictions

    report = build_predictions(source, tmp_path / "out", variants=["image_only", "metric_sidecar"], output_frame_count=12)

    assert report["summary"]["variants"] == ["image_only", "metric_sidecar"]
    assert (tmp_path / "out/image_only/trajectories/sample_001.json").exists()
    assert (tmp_path / "out/metric_sidecar/trajectories/sample_001.json").exists()
