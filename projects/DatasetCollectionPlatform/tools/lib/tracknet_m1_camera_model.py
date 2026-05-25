from __future__ import annotations

import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lib.quicktime_camera_metadata import parse_quicktime_lens_metadata


class CameraModelError(ValueError):
    pass


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def focal_px_from_35mm_equivalent(width: int | float, height: int | float, focal_35mm: int | float) -> float:
    full_frame_diagonal_mm = math.sqrt(36**2 + 24**2)
    image_diagonal_px = math.sqrt(float(width) ** 2 + float(height) ** 2)
    return image_diagonal_px * float(focal_35mm) / full_frame_diagonal_mm


def _sidecar_intrinsics(sidecar: dict[str, Any]) -> dict[str, Any] | None:
    intrinsics = sidecar.get("intrinsics")
    if isinstance(intrinsics, dict):
        return intrinsics
    calibration = sidecar.get("calibration")
    if isinstance(calibration, dict) and isinstance(calibration.get("intrinsics"), dict):
        return calibration["intrinsics"]
    return None


def _base_payload(shot: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": "1.0",
        "generatedAt": _utc_now(),
        "sampleId": shot.get("sampleId"),
        "sessionId": shot.get("sessionId"),
        "shotId": shot.get("shotId"),
        "sourceVideo": shot.get("sourceVideo"),
    }


def _validated_sample_id(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise CameraModelError("unsafe sampleId: missing or non-string value")
    if Path(value).name != value or "/" in value or "\\" in value or ".." in value:
        raise CameraModelError(f"unsafe sampleId: {value}")
    return value


def build_camera_model_for_shot(shot: dict[str, Any]) -> dict[str, Any]:
    payload = _base_payload(shot)
    source_video = Path(str(shot["sourceVideo"]))
    sidecar_path = source_video.with_suffix(".camera.json")
    sidecar = _read_json(sidecar_path) if sidecar_path.exists() else {}
    calibration = sidecar.get("calibration") if isinstance(sidecar.get("calibration"), dict) else None

    intrinsics = _sidecar_intrinsics(sidecar)
    if intrinsics is not None:
        payload.update({
            "status": "ok",
            "cameraModel": {
                "source": "avfoundation_intrinsics",
                "intrinsics": intrinsics,
                "sourceConfidence": 0.85,
                "metricGeometryConfidence": 0.85,
                "calibration": calibration,
            },
        })
        return payload

    quicktime = parse_quicktime_lens_metadata(source_video) if source_video.exists() else {}
    focal_35mm = quicktime.get("focalLength35mmEquivalent")
    if focal_35mm is not None:
        width = int(shot["frameWidth"])
        height = int(shot["frameHeight"])
        focal_px = math.floor(focal_px_from_35mm_equivalent(width, height, float(focal_35mm)) * 2) / 2
        payload.update({
            "status": "ok",
            "cameraModel": {
                "source": "quicktime_lens_metadata",
                "intrinsics": {
                    "fx": focal_px,
                    "fy": focal_px,
                    "cx": width / 2,
                    "cy": height / 2,
                },
                "sourceConfidence": 0.9,
                "metricGeometryConfidence": 0.65,
                "distortionStatus": "unknown",
                "stabilizationCropStatus": "unknown",
                "quicktimeLensMetadata": quicktime,
                "calibration": calibration,
            },
        })
        return payload

    payload.update({
        "status": "missing_camera_model",
        "cameraModel": None,
        "calibration": calibration,
    })
    return payload


def build_camera_models(batch_index_path: Path | str, output_dir: Path | str) -> dict[str, Any]:
    batch_index_path = Path(batch_index_path)
    output_dir = Path(output_dir)
    batch = _read_json(batch_index_path)
    models_dir = output_dir / "models"
    models: list[dict[str, Any]] = []
    source_counts: Counter[str] = Counter()
    status_counts: Counter[str] = Counter()

    for shot in batch.get("shots", []):
        sample_id = _validated_sample_id(shot.get("sampleId"))
        model_path = models_dir / f"{sample_id}.camera_model.json"
        model = build_camera_model_for_shot(shot)
        models.append({
            "sampleId": model.get("sampleId"),
            "shotId": model.get("shotId"),
            "status": model.get("status"),
            "path": str(model_path),
        })
        status_counts[str(model.get("status"))] += 1
        camera_model = model.get("cameraModel")
        if isinstance(camera_model, dict):
            source_counts[str(camera_model.get("source"))] += 1
        _write_json(model_path, model)

    report = {
        "version": "1.0",
        "generatedAt": _utc_now(),
        "batchIndexPath": str(batch_index_path),
        "outputDir": str(output_dir),
        "models": models,
        "sourceCounts": dict(source_counts),
        "statusCounts": dict(status_counts),
        "summary": {
            "totalShots": len(batch.get("shots", [])),
            "modelsWritten": len(models),
            "missingCameraModels": status_counts.get("missing_camera_model", 0),
        },
    }
    _write_json(output_dir / "camera_model_report.json", report)
    return report
