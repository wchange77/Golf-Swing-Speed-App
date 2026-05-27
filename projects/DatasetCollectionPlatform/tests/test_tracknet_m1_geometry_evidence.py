
from __future__ import annotations

import json
from pathlib import Path
import sys

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLATFORM_ROOT / "tools"))

from build_tracknet_m1_geometry_evidence import build_geometry_evidence_batch
from lib.tracknet_m1_geometry_evidence import build_geometry_evidence


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _visible(sample_id: str = "sample_001") -> dict:
    return {
        "sampleId": sample_id,
        "shotId": "shot_001",
        "sessionId": "session_001",
        "sourceVideo": f"/data/{sample_id}.mov",
        "seed": {"ballCenter": {"frameIndex": 100, "x": 900.0, "y": 910.0, "visible": True}},
    }


def test_geometry_evidence_prefers_avfoundation_and_manual_sidecar():
    camera_model = {
        "sampleId": "sample_001",
        "status": "ok",
        "cameraModel": {
            "source": "avfoundation_intrinsics",
            "intrinsics": {"fx": 1000.0, "fy": 1001.0, "cx": 960.0, "cy": 540.0},
            "sourceConfidence": 0.9,
        },
    }
    sidecar = {
        "calibration": {"cameraHeightMeters": 1.15, "cameraAngleDegrees": 7.5, "distanceMeters": 4.2},
        "groundPlane": {"normal": [0.0, 1.0, 0.0], "heightMeters": 0.0},
    }

    evidence = build_geometry_evidence(_visible(), camera_model, sidecar=sidecar)

    assert evidence["status"] == "ok"
    assert evidence["sampleId"] == "sample_001"
    assert evidence["intrinsics"]["source"] == "avfoundation_intrinsics"
    assert evidence["intrinsics"]["role"] == "strong_geometry"
    assert evidence["groundPlane"]["source"] == "manual_sidecar"
    assert evidence["ballOrigin"]["distanceMeters"] == 4.2
    assert evidence["cameraPose"] == {"heightMeters": 1.15, "pitchDegrees": 7.5}
    assert evidence["confidence"] >= 0.8
    assert evidence["missingFields"] == []
    assert evidence["failureReason"] is None


def test_geometry_evidence_marks_quicktime_as_low_confidence_fallback():
    camera_model = {
        "sampleId": "sample_001",
        "status": "ok",
        "cameraModel": {
            "source": "quicktime_lens_metadata",
            "intrinsics": {"fx": 1272.5, "fy": 1272.5, "cx": 960.0, "cy": 540.0},
            "sourceConfidence": 0.9,
            "metricGeometryConfidence": 0.65,
            "calibration": {"cameraHeightMeters": 1.0, "cameraAngleDegrees": 0.0, "distanceMeters": 4.0},
        },
    }

    evidence = build_geometry_evidence(_visible(), camera_model)

    assert evidence["status"] == "ok"
    assert evidence["intrinsics"]["source"] == "quicktime_lens_metadata"
    assert evidence["intrinsics"]["role"] == "fallback_intrinsics"
    assert evidence["confidence"] < 0.75
    assert "quicktime_missing_distortion_full_calibration" in evidence["warnings"]


def test_geometry_evidence_treats_depth_anything_as_auxiliary_not_strong_geometry():
    depth_evidence = {"source": "depth_anything_metric", "absoluteDepthMeters": 4.1, "confidence": 0.72}

    evidence = build_geometry_evidence(_visible(), {}, depth_evidence=depth_evidence)

    assert evidence["status"] == "failed"
    assert evidence["sources"]["depth"]["role"] == "auxiliary_depth"
    assert evidence["sources"]["depth"]["source"] == "depth_anything_metric"
    assert "intrinsics" in evidence["missingFields"]
    assert "groundPlane" in evidence["missingFields"]
    assert "Depth Anything" in evidence["failureReason"]


def test_geometry_evidence_fails_when_required_geometry_is_missing():
    camera_model = {
        "sampleId": "sample_001",
        "status": "missing_camera_model",
        "cameraModel": None,
    }

    evidence = build_geometry_evidence(_visible(), camera_model)

    assert evidence["status"] == "failed"
    assert evidence["missingFields"] == ["intrinsics", "cameraPose", "groundPlane", "ballOrigin"]
    assert evidence["confidence"] == 0.0
    assert evidence["failureReason"] == "missing required geometry: intrinsics, cameraPose, groundPlane, ballOrigin"


def test_build_geometry_evidence_batch_writes_files_and_report(tmp_path: Path):
    _write_json(tmp_path / "visible/sample_001.json", _visible())
    _write_json(
        tmp_path / "camera/sample_001.camera_model.json",
        {
            "sampleId": "sample_001",
            "status": "ok",
            "cameraModel": {
                "source": "avfoundation_intrinsics",
                "intrinsics": {"fx": 1000, "fy": 1000, "cx": 960, "cy": 540},
                "calibration": {"cameraHeightMeters": 1.0, "cameraAngleDegrees": 4.0, "distanceMeters": 3.8},
            },
        },
    )

    report = build_geometry_evidence_batch(
        visible_trajectories_dir=tmp_path / "visible",
        camera_models_dir=tmp_path / "camera",
        output_dir=tmp_path / "out",
    )

    output_path = tmp_path / "out/evidence/sample_001.geometry_evidence.json"
    assert output_path.exists()
    assert report["processed"] == 1
    assert report["statusCounts"] == {"ok": 1}
    assert report["evidence"][0]["path"] == str(output_path)
