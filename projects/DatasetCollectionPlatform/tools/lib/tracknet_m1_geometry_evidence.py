from __future__ import annotations

from datetime import datetime, timezone
import math
from typing import Any


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _intrinsics_from(camera_model: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None, float, str | None]:
    camera = camera_model.get("cameraModel") if isinstance(camera_model.get("cameraModel"), dict) else camera_model
    if not isinstance(camera, dict):
        return None, None, 0.0, None
    raw = camera.get("intrinsics") if isinstance(camera.get("intrinsics"), dict) else None
    if raw is None:
        return None, None, 0.0, None
    values: dict[str, float] = {}
    for key in ("fx", "fy", "cx", "cy"):
        number = _finite(raw.get(key))
        if number is None or (key in {"fx", "fy"} and number <= 0):
            return None, None, 0.0, None
        values[key] = number
    source = str(camera.get("source") or "unknown_intrinsics")
    if source in {"avfoundation_intrinsics", "arkit_intrinsics"}:
        role = "strong_geometry"
        confidence = float(camera.get("sourceConfidence") or 0.85)
    elif source == "quicktime_lens_metadata":
        role = "fallback_intrinsics"
        confidence = min(float(camera.get("metricGeometryConfidence") or 0.65), 0.65)
    else:
        role = "intrinsics"
        confidence = float(camera.get("sourceConfidence") or 0.5)
    return {"source": source, "role": role, "values": values}, role, confidence, source


def _calibration_from(camera_model: dict[str, Any], sidecar: dict[str, Any] | None) -> dict[str, Any]:
    camera = camera_model.get("cameraModel") if isinstance(camera_model.get("cameraModel"), dict) else camera_model
    camera_calibration = camera.get("calibration") if isinstance(camera, dict) and isinstance(camera.get("calibration"), dict) else {}
    top_calibration = camera_model.get("calibration") if isinstance(camera_model.get("calibration"), dict) else {}
    sidecar_calibration = sidecar.get("calibration") if isinstance(sidecar, dict) and isinstance(sidecar.get("calibration"), dict) else {}
    merged: dict[str, Any] = {}
    merged.update(top_calibration)
    merged.update(camera_calibration)
    merged.update(sidecar_calibration)
    return merged


def _camera_pose(calibration: dict[str, Any]) -> dict[str, float] | None:
    height = _finite(calibration.get("cameraHeightMeters"))
    pitch = _finite(calibration.get("cameraAngleDegrees"))
    if height is None or height <= 0 or pitch is None:
        return None
    return {"heightMeters": height, "pitchDegrees": pitch}


def _ground_plane(sidecar: dict[str, Any] | None, camera_pose: dict[str, float] | None) -> dict[str, Any] | None:
    if isinstance(sidecar, dict) and isinstance(sidecar.get("groundPlane"), dict):
        plane = dict(sidecar["groundPlane"])
        plane.setdefault("source", "manual_sidecar")
        return plane
    if camera_pose is not None:
        return {"source": "camera_pose_ground_plane", "normal": [0.0, 1.0, 0.0], "heightMeters": 0.0}
    return None


def _ball_origin(calibration: dict[str, Any], depth_evidence: dict[str, Any] | None) -> dict[str, Any] | None:
    distance = _finite(calibration.get("distanceMeters"))
    if distance is not None and distance > 0:
        return {"source": "manual_or_lidar_sidecar", "distanceMeters": distance, "role": "strong_geometry"}
    if isinstance(depth_evidence, dict):
        depth = _finite(depth_evidence.get("absoluteDepthMeters") or depth_evidence.get("distanceMeters"))
        if depth is not None and depth > 0:
            return {"source": str(depth_evidence.get("source") or "metric_depth"), "distanceMeters": depth, "role": "auxiliary_depth"}
    return None


def build_geometry_evidence(
    visible_artifact: dict[str, Any],
    camera_model: dict[str, Any],
    *,
    sidecar: dict[str, Any] | None = None,
    depth_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    intrinsics, intrinsics_role, intrinsics_confidence, intrinsics_source = _intrinsics_from(camera_model if isinstance(camera_model, dict) else {})
    calibration = _calibration_from(camera_model if isinstance(camera_model, dict) else {}, sidecar)
    camera_pose = _camera_pose(calibration)
    ground_plane = _ground_plane(sidecar, camera_pose)
    ball_origin = _ball_origin(calibration, depth_evidence)

    warnings: list[str] = []
    sources: dict[str, Any] = {}
    if intrinsics is not None:
        sources["intrinsics"] = {"source": intrinsics["source"], "role": intrinsics["role"]}
        if intrinsics_source == "quicktime_lens_metadata":
            warnings.append("quicktime_missing_distortion_full_calibration")
    if isinstance(sidecar, dict) and sidecar:
        sources["sidecar"] = {"source": str(sidecar.get("source") or "manual_or_lidar_sidecar"), "role": "strong_geometry"}
    if isinstance(depth_evidence, dict) and depth_evidence:
        sources["depth"] = {"source": str(depth_evidence.get("source") or "metric_depth"), "role": "auxiliary_depth"}
        warnings.append("depth_anything_auxiliary_not_strong_geometry")

    missing_fields: list[str] = []
    if intrinsics is None:
        missing_fields.append("intrinsics")
    if camera_pose is None:
        missing_fields.append("cameraPose")
    if ground_plane is None:
        missing_fields.append("groundPlane")
    if ball_origin is None:
        missing_fields.append("ballOrigin")

    if missing_fields:
        status = "failed"
        confidence = 0.0 if intrinsics is None else min(intrinsics_confidence, 0.35)
        if depth_evidence and ("intrinsics" in missing_fields or "groundPlane" in missing_fields):
            failure_reason = "Depth Anything/metric depth is auxiliary and cannot replace missing camera intrinsics or groundPlane"
        else:
            failure_reason = f"missing required geometry: {', '.join(missing_fields)}"
    else:
        status = "ok"
        confidence = intrinsics_confidence
        if ball_origin and ball_origin.get("role") == "auxiliary_depth":
            confidence = min(confidence, 0.55)
        failure_reason = None

    return {
        "version": "1.0",
        "stage": "m1_geometry_evidence",
        "generatedAt": _utc_now(),
        "status": status,
        "sampleId": visible_artifact.get("sampleId"),
        "shotId": visible_artifact.get("shotId"),
        "sessionId": visible_artifact.get("sessionId"),
        "sourceVideo": visible_artifact.get("sourceVideo"),
        "intrinsics": intrinsics,
        "groundPlane": ground_plane,
        "ballOrigin": ball_origin,
        "cameraPose": camera_pose,
        "sources": sources,
        "confidence": round(float(confidence), 4),
        "missingFields": missing_fields,
        "failureReason": failure_reason,
        "warnings": warnings,
    }
