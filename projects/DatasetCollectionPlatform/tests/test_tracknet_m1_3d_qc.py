from __future__ import annotations

import json
from pathlib import Path
import sys

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLATFORM_ROOT / "tools"))

from lib.tracknet_m1_3d_qc import summarize_trajectory_file
from validate_tracknet_m1_3d_reconstruction import validate_3d_reconstruction


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _trajectory(*, with_trackman: bool = True, failed: bool = False) -> dict:
    if failed:
        return {
            "videoOnly3d": {"sampleId": "failed_sample", "status": "failed", "reason": "no landing", "frames": []}
        }
    payload = {
        "videoOnly3d": {
            "sampleId": "sample_001",
            "status": "needs_review",
            "model": {"type": "video_only_rk4_drag_magnus_3d", "modelFamily": "RK4_drag_magnus"},
            "landingFrame": 200,
            "landingPointImage": {"x": 810, "y": 560},
            "parameters": {
                "ballSpeed": {"status": "estimated", "confidence": 0.62, "evidenceFrames": [120, 160]},
                "launchAngle": {"status": "estimated", "confidence": 0.63, "evidenceFrames": [120, 160]},
                "spin": {"status": "unidentifiable", "confidence": 0.0, "failureReason": "too short"},
            },
            "qc": {
                "fit": {"rmsResidualMeters": 0.12},
                "issues": [],
            },
            "frames": [
                {"frameIndex": 120, "source": "observed_3d", "labelEligible": False, "worldMeters": {"x": 0.0, "height": 0.0, "z": 4.0}},
                {"frameIndex": 160, "source": "predicted_video_only_3d", "labelEligible": False, "worldMeters": {"x": 3.0, "height": 8.0, "z": 60.0}},
                {"frameIndex": 200, "source": "predicted_video_only_3d", "labelEligible": False, "worldMeters": {"x": 10.0, "height": 0.0, "z": 140.0}},
            ],
        }
    }
    if with_trackman:
        payload["trackmanConstrained3d"] = {
            "sampleId": "sample_001",
            "status": "needs_review",
            "trackmanInputs": {"carryYd": 150.0, "apexYd": 30.0, "sideYd": 12.0},
            "qc": {
                "visibleOverlap": {"rmsePx": 2.0, "p95Px": 3.0, "maxPx": 4.0},
                "trackmanComparison": {"carryResidualYd": 4.0, "apexResidualYd": -1.0, "sideResidualYd": 2.0},
            },
            "frames": [
                {"frameIndex": 120, "labelEligible": False, "worldMeters": {"x": 0.0, "height": 0.0, "z": 4.0}},
                {"frameIndex": 200, "labelEligible": False, "worldMeters": {"x": 11.0, "height": 0.0, "z": 141.0}},
            ],
        }
    return payload


def test_summarize_trajectory_file_reports_trackman_errors_and_parameter_states():
    summary = summarize_trajectory_file(_trajectory())

    assert summary["sampleId"] == "sample_001"
    assert summary["status"] == "ok"
    assert summary["trackmanComparisonStatus"] == "available"
    assert summary["metrics"]["carryErrorYd"] == 4.0
    assert summary["metrics"]["apexErrorYd"] == -1.0
    assert summary["metrics"]["sideErrorYd"] == 2.0
    assert summary["metrics"]["visibleReprojectionRmsePx"] == 2.0
    assert summary["metrics"]["videoOnlyCarryErrorYd"] is not None
    assert summary["metrics"]["curveDirectionStatus"] == "ok"
    assert summary["parameterStates"]["spin"]["status"] == "unidentifiable"
    assert summary["evidenceFrames"] == [120, 160]
    assert summary["failureReasons"] == ["spin: too short"]


def test_summarize_trajectory_file_marks_no_trackman_as_unavailable_not_pass():
    summary = summarize_trajectory_file(_trajectory(with_trackman=False))

    assert summary["status"] == "trackman_unavailable"
    assert summary["trackmanComparisonStatus"] == "unavailable"
    assert summary["warnings"] == ["trackman_comparison_unavailable"]


def test_summarize_trajectory_file_marks_failed_for_missing_landing():
    summary = summarize_trajectory_file(_trajectory(failed=True))

    assert summary["sampleId"] == "failed_sample"
    assert summary["status"] == "failed"
    assert "missing_or_empty_video_only_frames" in summary["errors"]


def test_summarize_trajectory_file_marks_curve_direction_mismatch_needs_review():
    payload = _trajectory()
    payload["videoOnly3d"]["frames"][-1]["worldMeters"]["x"] = -10.0

    summary = summarize_trajectory_file(payload)

    assert summary["status"] == "needs_review"
    assert summary["metrics"]["curveDirectionStatus"] == "mismatch"
    assert "curve_direction_mismatch" in summary["warnings"]


def test_summarize_trajectory_file_marks_infinite_down_trajectory_failed():
    payload = _trajectory()
    payload["videoOnly3d"]["frames"][-1]["worldMeters"]["height"] = -5.0

    summary = summarize_trajectory_file(payload)

    assert summary["status"] == "failed"
    assert "infinite_down_trajectory" in summary["errors"]


def test_summarize_trajectory_file_marks_visible_reprojection_residual_needs_review():
    payload = _trajectory()
    payload["trackmanConstrained3d"]["qc"]["visibleOverlap"]["rmsePx"] = 18.0

    summary = summarize_trajectory_file(payload, max_reprojection_rmse_px=5.0)

    assert summary["status"] == "needs_review"
    assert "visible_reprojection_rmse_exceeds_threshold" in summary["warnings"]


def test_validate_3d_reconstruction_writes_json_markdown_and_html(tmp_path: Path):
    _write_json(tmp_path / "trajectories/sample_001.trajectory_3d.json", _trajectory())
    _write_json(tmp_path / "trajectories/sample_002.trajectory_3d.json", _trajectory(with_trackman=False))
    _write_json(tmp_path / "trajectories/sample_003.trajectory_3d.json", _trajectory(failed=True))

    report = validate_3d_reconstruction(
        trajectories_dir=tmp_path / "trajectories",
        output_root=tmp_path / "qc",
        max_error_carry_yd=10.0,
        max_reprojection_rmse_px=5.0,
    )

    assert report["sampleCount"] == 3
    assert report["statusCounts"]["ok"] == 1
    assert report["statusCounts"]["trackman_unavailable"] == 1
    assert report["statusCounts"]["failed"] == 1
    assert report["trackmanAvailableCount"] == 1
    assert report["videoOnlyCount"] == 2
    assert (tmp_path / "qc/trajectory_3d_qc_report.json").exists()
    assert (tmp_path / "qc/trajectory_3d_qc_report.md").exists()
    assert (tmp_path / "qc/trajectory_3d_qc_report.html").exists()
    md = (tmp_path / "qc/trajectory_3d_qc_report.md").read_text(encoding="utf-8")
    assert "TrackMan unavailable" in md
    assert "max_error_carry_yd=10.0" in md
