from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

import pytest

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLATFORM_ROOT / "tools"))

from lib.tracknet_m1_camera_model import CameraModelError, build_camera_model_for_shot, build_camera_models


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _box(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I4s", len(payload) + 8, kind) + payload


def _quicktime_lens_movie(path: Path, focal_35mm: float = 25.0) -> None:
    key = "com.apple.quicktime.camera.focal_length.35mm_equivalent"
    key_payload = b"mdta" + key.encode("utf-8")
    keys = _box(b"keys", b"\x00\x00\x00\x00" + struct.pack(">I", 1) + struct.pack(">I", len(key_payload) + 4) + key_payload)
    data = _box(b"data", struct.pack(">II", 23, 0) + struct.pack(">f", focal_35mm))
    ilst = _box(b"ilst", _box(struct.pack(">I", 1), data))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x00\x00\x00\x18ftypqt  \x00\x00\x00\x00qt  " + keys + ilst)


def _shot(video_path: Path) -> dict:
    return {
        "sessionId": "sess_001",
        "shotId": "shot_001",
        "sampleId": "sample_001",
        "sourceVideo": str(video_path),
        "frameWidth": 1920,
        "frameHeight": 1080,
    }


def test_sidecar_intrinsics_take_priority_over_quicktime(tmp_path: Path):
    video_path = tmp_path / "sample.mov"
    _quicktime_lens_movie(video_path, focal_35mm=25.0)
    _write_json(video_path.with_suffix(".camera.json"), {
        "intrinsics": {"fx": 1000, "fy": 1001, "cx": 960, "cy": 540},
        "calibration": {"distortionStatus": "available"},
    })

    result = build_camera_model_for_shot(_shot(video_path))

    assert result["status"] == "ok"
    assert result["cameraModel"]["source"] == "avfoundation_intrinsics"
    assert result["cameraModel"]["intrinsics"]["fx"] == 1000
    assert result["cameraModel"]["sourceConfidence"] == 0.85


def test_quicktime_fallback_uses_dual_confidence(tmp_path: Path):
    video_path = tmp_path / "sample.mov"
    _quicktime_lens_movie(video_path, focal_35mm=25.0)
    _write_json(video_path.with_suffix(".camera.json"), {"calibration": {"device": "fixture"}})

    result = build_camera_model_for_shot(_shot(video_path))

    assert result["status"] == "ok"
    assert result["cameraModel"]["source"] == "quicktime_lens_metadata"
    assert result["cameraModel"]["intrinsics"] == {"fx": 1272.5, "fy": 1272.5, "cx": 960.0, "cy": 540.0}
    assert result["cameraModel"]["sourceConfidence"] == 0.9
    assert result["cameraModel"]["metricGeometryConfidence"] == 0.65
    assert result["cameraModel"]["distortionStatus"] == "unknown"
    assert result["cameraModel"]["stabilizationCropStatus"] == "unknown"


def test_build_camera_models_writes_one_file_per_reviewed_shot(tmp_path: Path):
    video_a = tmp_path / "a.mov"
    video_b = tmp_path / "b.mov"
    _quicktime_lens_movie(video_a, focal_35mm=25.0)
    _quicktime_lens_movie(video_b, focal_35mm=25.0)
    _write_json(video_b.with_suffix(".camera.json"), {"intrinsics": {"fx": 1000, "fy": 1000, "cx": 960, "cy": 540}})
    batch_index = tmp_path / "batch_index.json"
    _write_json(batch_index, {
        "version": "1.0",
        "shots": [
            {**_shot(video_a), "sampleId": "sample_a", "shotId": "shot_a"},
            {**_shot(video_b), "sampleId": "sample_b", "shotId": "shot_b"},
        ],
    })

    report = build_camera_models(batch_index, tmp_path / "camera_models")

    assert (tmp_path / "camera_models/models/sample_a.camera_model.json").exists()
    assert (tmp_path / "camera_models/models/sample_b.camera_model.json").exists()
    assert report["summary"]["totalShots"] == 2
    assert report["sourceCounts"] == {
        "quicktime_lens_metadata": 1,
        "avfoundation_intrinsics": 1,
    }


@pytest.mark.parametrize("sample_id", ["../escape", "bad/name"])
def test_build_camera_models_rejects_unsafe_sample_id(tmp_path: Path, sample_id: str):
    batch_index = tmp_path / "batch_index.json"
    _write_json(batch_index, {
        "version": "1.0",
        "shots": [{**_shot(tmp_path / "sample.mov"), "sampleId": sample_id}],
    })
    output_dir = tmp_path / "camera_models"

    with pytest.raises(CameraModelError, match="unsafe sampleId"):
        build_camera_models(batch_index, output_dir)

    assert not (output_dir / "escape.camera_model.json").exists()
    assert not (output_dir / "models/bad/name.camera_model.json").exists()
