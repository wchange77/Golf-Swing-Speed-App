from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

import numpy as np

from lib.trackman_review import _canonical_unit

GRAVITY_MPS2 = 9.80665
MPH_TO_MPS = 0.44704
YD_TO_M = 0.9144


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _finite_float(name: str, value: Any, *, positive: bool = False) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be finite") from exc
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    if positive and number <= 0:
        raise ValueError(f"{name} must be positive")
    return number


def _intrinsics(camera: dict[str, Any]) -> dict[str, float]:
    geometry_evidence = camera.get("geometryEvidence") if isinstance(camera.get("geometryEvidence"), dict) else None
    if geometry_evidence is not None:
        evidence_intrinsics = geometry_evidence.get("intrinsics") if isinstance(geometry_evidence.get("intrinsics"), dict) else {}
        source = evidence_intrinsics.get("values") if isinstance(evidence_intrinsics.get("values"), dict) else evidence_intrinsics
    else:
        source = camera.get("intrinsics") or (camera.get("cameraModel") or {}).get("intrinsics")
    if not source:
        raise ValueError("camera intrinsics are required")
    values = {}
    for key in ("fx", "fy", "cx", "cy"):
        if key not in source:
            raise ValueError(f"camera intrinsics {key} is required")
        values[key] = _finite_float(f"camera intrinsics {key}", source[key], positive=key in {"fx", "fy"})
    return values


def _calibration(camera: dict[str, Any]) -> dict[str, float | None]:
    geometry_evidence = camera.get("geometryEvidence") if isinstance(camera.get("geometryEvidence"), dict) else None
    if geometry_evidence is not None:
        pose = geometry_evidence.get("cameraPose") if isinstance(geometry_evidence.get("cameraPose"), dict) else {}
        ball_origin = geometry_evidence.get("ballOrigin") if isinstance(geometry_evidence.get("ballOrigin"), dict) else {}
        calibration = {
            "cameraHeightMeters": pose.get("heightMeters"),
            "cameraAngleDegrees": pose.get("pitchDegrees"),
            "distanceMeters": ball_origin.get("distanceMeters"),
        }
    else:
        calibration = camera.get("calibration") or (camera.get("cameraModel") or {}).get("calibration") or {}
    for key in ("cameraHeightMeters", "cameraAngleDegrees"):
        if key not in calibration:
            raise ValueError(f"camera calibration {key} is required")
    values: dict[str, float | None] = {
        "cameraHeightMeters": _finite_float(
            "camera calibration cameraHeightMeters",
            calibration["cameraHeightMeters"],
            positive=True,
        ),
        "cameraAngleDegrees": _finite_float(
            "camera calibration cameraAngleDegrees",
            calibration["cameraAngleDegrees"],
        ),
        "distanceMeters": None,
    }
    if "distanceMeters" in calibration and calibration["distanceMeters"] is not None:
        values["distanceMeters"] = _finite_float(
            "camera calibration distanceMeters",
            calibration["distanceMeters"],
            positive=True,
        )
    return values


def _normalised(u: float, v: float, intrinsics: dict[str, float]) -> tuple[float, float]:
    return (u - intrinsics["cx"]) / intrinsics["fx"], (intrinsics["cy"] - v) / intrinsics["fy"]


def _world_ray(
    u: float,
    v: float,
    intrinsics: dict[str, float],
    pitch_rad: float,
) -> tuple[float, float, float]:
    xn, yn = _normalised(u, v, intrinsics)
    cos_t = math.cos(pitch_rad)
    sin_t = math.sin(pitch_rad)
    rx = xn
    ry = cos_t * yn - sin_t
    rz = sin_t * yn + cos_t
    norm = math.sqrt(rx * rx + ry * ry + rz * rz)
    if not math.isfinite(norm) or norm <= 0:
        raise ValueError("camera ray is invalid")
    return rx / norm, ry / norm, rz / norm


def _seed_ground_point(
    seed: dict[str, Any],
    intrinsics: dict[str, float],
    camera_height_m: float,
    pitch_rad: float,
) -> tuple[float, float, float]:
    rx, ry, rz = _world_ray(float(seed["x"]), float(seed["y"]), intrinsics, pitch_rad)
    if ry >= -1e-6:
        raise ValueError("seed ray does not intersect ground below camera")
    scale = -camera_height_m / ry
    x0 = scale * rx
    z0 = scale * rz
    if not all(math.isfinite(value) for value in (x0, z0)) or z0 <= 0:
        raise ValueError("seed ray ground intersection is invalid")
    return x0, z0, math.hypot(x0, z0)


def _project(
    x: float,
    height: float,
    z: float,
    intrinsics: dict[str, float],
    camera_height_m: float,
    pitch_rad: float,
) -> tuple[float, float]:
    cos_t = math.cos(pitch_rad)
    sin_t = math.sin(pitch_rad)
    dy = height - camera_height_m
    x_cam = x
    y_cam = cos_t * dy + sin_t * z
    z_cam = -sin_t * dy + cos_t * z
    if z_cam <= 1e-6:
        raise ValueError("trajectory point is behind the camera")
    u = intrinsics["cx"] + intrinsics["fx"] * x_cam / z_cam
    v = intrinsics["cy"] - intrinsics["fy"] * y_cam / z_cam
    return float(u), float(v)


def _fit_velocity(
    artifact: dict[str, Any],
    intrinsics: dict[str, float],
    camera_height_m: float,
    pitch_rad: float,
) -> tuple[float, float, float, float, float, float, dict[str, Any]]:
    fps = float(artifact["fps"])
    launch_frame = int(artifact["launchFrame"])
    seed = artifact["seed"]["ballCenter"]
    x0, z0, seed_ground_distance_m = _seed_ground_point(seed, intrinsics, camera_height_m, pitch_rad)
    rows: list[list[float]] = []
    values: list[float] = []

    for frame in artifact.get("ballSmoothVisibleFrames", []):
        if not frame.get("visible", True):
            continue
        frame_index = int(frame["frameIndex"])
        t = (frame_index - launch_frame) / fps
        if t <= 0:
            continue
        rx, ry, rz = _world_ray(float(frame["x"]), float(frame["y"]), intrinsics, pitch_rad)
        rows.append([t * rz, 0.0, -t * rx])
        values.append(z0 * rx - x0 * rz)
        rows.append([0.0, t * rz, -t * ry])
        values.append(camera_height_m * rz + z0 * ry + 0.5 * GRAVITY_MPS2 * t * t * rz)

    if len(rows) < 6:
        raise ValueError("at least three visible 3D fit points are required")

    matrix = np.array(rows, dtype=np.float64)
    target = np.array(values, dtype=np.float64)
    solution, _, rank, singular_values = np.linalg.lstsq(matrix, target, rcond=None)
    if rank < 3:
        raise ValueError(f"3D trajectory fit is rank-deficient: rank {rank} < 3")

    residual_vector = matrix @ solution - target
    rms_residual_m = float(np.sqrt(np.mean(np.square(residual_vector))))
    residual_threshold_m = max(2.5, 0.75 * seed_ground_distance_m)
    if not math.isfinite(rms_residual_m):
        raise ValueError("3D trajectory fit residual is non-finite")
    if rms_residual_m > residual_threshold_m:
        raise ValueError(
            f"3D trajectory fit residual {rms_residual_m:.3f}m exceeds threshold {residual_threshold_m:.3f}m"
        )

    vx, vy, vz = solution
    if not np.all(np.isfinite([vx, vy, vz])):
        raise ValueError("3D trajectory fit produced non-finite velocity")
    fit_quality = {
        "rank": int(rank),
        "rmsResidualMeters": round(rms_residual_m, 4),
        "residualThresholdMeters": round(residual_threshold_m, 4),
        "singularValues": [round(float(value), 6) for value in singular_values],
    }
    return x0, z0, seed_ground_distance_m, float(vx), float(vy), float(vz), fit_quality


def _quality_qc(
    seed_ground_distance_m: float,
    calibration: dict[str, float | None],
    fit_quality: dict[str, Any],
) -> dict[str, Any]:
    distance_m = calibration["distanceMeters"]
    qc: dict[str, Any] = {
        "seedGroundDistanceMeters": round(seed_ground_distance_m, 4),
        "distanceResidualMeters": None,
        "fit": fit_quality,
        "issues": [],
    }
    if distance_m is None:
        return qc
    residual = seed_ground_distance_m - distance_m
    qc["distanceResidualMeters"] = round(residual, 4)
    if abs(residual) > max(1.0, 0.25 * distance_m):
        qc["issues"].append(
            {
                "code": "seed_ground_distance_mismatch",
                "message": "seed ground distance differs from calibration distanceMeters",
            }
        )
    return qc


def _unavailable_trackman(
    status: str,
    reason: str,
    visible_artifact: dict[str, Any] | None = None,
) -> dict[str, Any]:
    artifact = visible_artifact if isinstance(visible_artifact, dict) else {}
    return {
        "trackmanConstrained3d": {
            "version": "1.0",
            "stage": "m1_3d_reconstruction",
            "generatedAt": _utc_now(),
            "sampleId": artifact.get("sampleId"),
            "shotId": artifact.get("shotId"),
            "sessionId": artifact.get("sessionId"),
            "sourceVideo": artifact.get("sourceVideo"),
            "status": status,
            "reason": reason,
            "frames": [],
        }
    }


def _trackman_field(
    trackman_reviewed: dict[str, Any],
    name: str,
    expected_unit: str,
    *,
    required: bool,
    positive: bool = True,
) -> tuple[float | None, str | None, str | None]:
    fields = trackman_reviewed.get("correctedFields") or {}
    field = fields.get(name)
    if field is None:
        if required:
            return None, "missing", f"required corrected TrackMan field {name} is missing"
        return None, None, None
    if not isinstance(field, dict):
        return None, "invalid_value", f"corrected TrackMan field {name} must be an object"
    unit = _canonical_unit(field.get("normalizedUnit"), expected_unit)
    if unit != expected_unit:
        return None, "invalid_unit", f"corrected TrackMan field {name} must use normalizedUnit {expected_unit}"
    try:
        value = _finite_float(f"corrected TrackMan field {name}", field.get("normalizedValue"), positive=positive)
    except ValueError as exc:
        return None, "invalid_value", str(exc)
    return value, None, None


def _trackman_comparison_qc(
    *,
    predicted_carry_yd: float,
    predicted_apex_yd: float,
    predicted_side_yd: float | None,
    confirmed_carry_yd: float | None,
    confirmed_apex_yd: float | None,
    confirmed_side_yd: float | None,
) -> dict[str, Any]:
    carry_threshold_yd = None if confirmed_carry_yd is None else max(10.0, 0.15 * confirmed_carry_yd)
    apex_threshold_yd = None if confirmed_apex_yd is None else max(5.0, 0.2 * confirmed_apex_yd)
    side_threshold_yd = None if confirmed_side_yd is None else max(5.0, 0.25 * abs(confirmed_side_yd))
    comparison: dict[str, Any] = {
        "predictedCarryYd": round(predicted_carry_yd, 4),
        "confirmedCarryYd": confirmed_carry_yd,
        "carryResidualYd": None,
        "carryMismatchThresholdYd": None if carry_threshold_yd is None else round(carry_threshold_yd, 4),
        "predictedApexYd": round(predicted_apex_yd, 4),
        "confirmedApexYd": confirmed_apex_yd,
        "apexResidualYd": None,
        "apexMismatchThresholdYd": None if apex_threshold_yd is None else round(apex_threshold_yd, 4),
        "predictedSideYd": None if predicted_side_yd is None else round(predicted_side_yd, 4),
        "confirmedSideYd": confirmed_side_yd,
        "sideResidualYd": None,
        "sideMismatchThresholdYd": None if side_threshold_yd is None else round(side_threshold_yd, 4),
        "issues": [],
    }
    if confirmed_carry_yd is not None:
        residual = predicted_carry_yd - confirmed_carry_yd
        comparison["carryResidualYd"] = round(residual, 4)
        if carry_threshold_yd is not None and abs(residual) > carry_threshold_yd:
            comparison["issues"].append(
                {
                    "code": "trackman_carry_mismatch",
                    "message": "gravity-only predicted carry differs from confirmed TrackMan carry",
                }
            )
    if confirmed_apex_yd is not None:
        residual = predicted_apex_yd - confirmed_apex_yd
        comparison["apexResidualYd"] = round(residual, 4)
        if apex_threshold_yd is not None and abs(residual) > apex_threshold_yd:
            comparison["issues"].append(
                {
                    "code": "trackman_apex_mismatch",
                    "message": "gravity-only predicted apex differs from confirmed TrackMan apex",
                }
            )
    if confirmed_side_yd is not None and predicted_side_yd is not None:
        residual = predicted_side_yd - confirmed_side_yd
        comparison["sideResidualYd"] = round(residual, 4)
        if side_threshold_yd is not None and abs(residual) > side_threshold_yd:
            comparison["issues"].append(
                {
                    "code": "trackman_side_mismatch",
                    "message": "predicted side offset differs from confirmed TrackMan side",
                }
            )
    return comparison


def _validate_trackman_range(name: str, value: float | None) -> str | None:
    if value is None:
        return None
    ranges = {
        "ballSpeed": (10.0, value, 250.0, "10 < ballSpeed mph <= 250"),
        "launchAngle": (0.0, value, 80.0, "0 < launchAngle deg < 80"),
        "carry": (0.0, value, 500.0, "0 < carry yd <= 500"),
        "apex": (0.0, value, 200.0, "0 < apex yd <= 200"),
    }
    lower, actual, upper, description = ranges[name]
    if name == "launchAngle":
        valid = lower < actual < upper
    else:
        valid = lower < actual <= upper
    if valid:
        return None
    return f"corrected TrackMan field {name} is out of range: expected {description}"


def _trackman_signed_side_field_yd(
    trackman_reviewed: dict[str, Any],
    name: str,
) -> tuple[float | None, str | None, str | None]:
    fields = trackman_reviewed.get("correctedFields") or {}
    field = fields.get(name)
    if field is None:
        return None, None, None
    value, error_code, reason = _trackman_field(trackman_reviewed, name, "yd", required=False, positive=True)
    if error_code is not None:
        return None, error_code, reason
    if value is None:
        return None, None, None
    direction = str(field.get("direction") or "").strip().lower() if isinstance(field, dict) else ""
    sign = -1.0 if direction == "left" else 1.0
    return sign * value, None, None


def _trackman_directional_side_yd(
    trackman_reviewed: dict[str, Any],
) -> tuple[float | None, str | None, str | None, str | None]:
    for name in ("carrySide", "totalSide"):
        value, error_code, reason = _trackman_signed_side_field_yd(trackman_reviewed, name)
        if error_code is not None:
            return None, name, error_code, reason
        if value is not None:
            return value, name, None, None
    return None, None, None, None


def _trackman_curve_yd(
    trackman_reviewed: dict[str, Any],
) -> tuple[float | None, str | None, str | None, str | None]:
    value, error_code, reason = _trackman_signed_side_field_yd(trackman_reviewed, "curve")
    if error_code is not None:
        return None, "curve", error_code, reason
    if value is not None:
        return value, "curve", None, None
    return None, None, None, None


def _trackman_optional_scalar(
    trackman_reviewed: dict[str, Any],
    name: str,
    expected_unit: str,
    *,
    positive: bool = False,
) -> tuple[float | None, str | None, str | None]:
    value, error_code, reason = _trackman_field(
        trackman_reviewed,
        name,
        expected_unit,
        required=False,
        positive=positive,
    )
    return value, error_code, reason


def _visible_ball_constraints(
    visible_artifact: dict[str, Any],
    *,
    launch_frame: int,
) -> dict[int, dict[str, float]]:
    try:
        last_reliable_frame = int(visible_artifact["lastReliableFrame"])
    except (KeyError, TypeError, ValueError):
        last_reliable_frame = None

    constraints: dict[int, dict[str, float]] = {}
    for frame in visible_artifact.get("ballSmoothVisibleFrames", []):
        if not isinstance(frame, dict) or not frame.get("visible", True):
            continue
        try:
            frame_index = int(frame["frameIndex"])
            x = _finite_float("visible ball x", frame["x"])
            y = _finite_float("visible ball y", frame["y"])
        except (KeyError, TypeError, ValueError):
            continue
        if frame_index < launch_frame:
            continue
        if last_reliable_frame is not None and frame_index > last_reliable_frame:
            continue
        constraints[frame_index] = {"x": x, "y": y}
    return constraints


def _visible_overlap_qc(
    *,
    constraints: dict[int, dict[str, float]],
    residuals_px: list[float],
) -> dict[str, Any]:
    threshold_px = 5.0
    missing_count = max(0, len(constraints) - len(residuals_px))
    if not residuals_px:
        return {
            "status": "no_visible_ball_constraints",
            "pointCount": 0,
            "expectedPointCount": len(constraints),
            "missingFrameCount": missing_count,
            "rmsePx": None,
            "p95Px": None,
            "maxPx": None,
            "thresholdPx": threshold_px,
        }
    array = np.array(residuals_px, dtype=np.float64)
    rmse = float(np.sqrt(np.mean(np.square(array))))
    p95 = float(np.percentile(array, 95))
    max_px = float(np.max(array))
    status = "ok" if missing_count == 0 and max_px <= threshold_px else "visible_overlap_mismatch"
    return {
        "status": status,
        "pointCount": len(residuals_px),
        "expectedPointCount": len(constraints),
        "missingFrameCount": missing_count,
        "rmsePx": round(rmse, 4),
        "p95Px": round(p95, 4),
        "maxPx": round(max_px, 4),
        "thresholdPx": threshold_px,
    }


def build_video_only_3d_trajectory(visible_artifact: dict[str, Any], camera: dict[str, Any]) -> dict[str, Any]:
    intrinsics = _intrinsics(camera)
    calibration = _calibration(camera)
    camera_height_m = float(calibration["cameraHeightMeters"])
    pitch_degrees = float(calibration["cameraAngleDegrees"])
    pitch_rad = math.radians(pitch_degrees)
    x0, z0, seed_ground_distance_m, vx, vy, vz, fit_quality = _fit_velocity(
        visible_artifact,
        intrinsics,
        camera_height_m,
        pitch_rad,
    )
    if vy <= 0:
        raise ValueError("3D trajectory fit requires positive vertical velocity")
    fps = float(visible_artifact["fps"])
    launch_frame = int(visible_artifact["launchFrame"])
    landing_time = 2.0 * vy / GRAVITY_MPS2
    if not math.isfinite(landing_time) or landing_time <= 0:
        raise ValueError("3D trajectory fit produced invalid landing time")
    landing_z = z0 + vz * landing_time
    if not math.isfinite(landing_z) or landing_z <= 0:
        raise ValueError("3D trajectory fit produced invalid landing z")
    landing_frame = int(round(launch_frame + landing_time * fps))
    frame_width = float(visible_artifact["frameWidth"])
    frame_height = float(visible_artifact["frameHeight"])

    frames = []
    for frame_index in range(launch_frame, landing_frame + 1):
        t = (frame_index - launch_frame) / fps
        height = max(0.0, vy * t - 0.5 * GRAVITY_MPS2 * t * t)
        x = x0 + vx * t
        z = z0 + vz * t
        if not math.isfinite(z) or z <= 0:
            raise ValueError("3D trajectory fit produced invalid z progression")
        u, v = _project(x, height, z, intrinsics, camera_height_m, pitch_rad)
        frames.append(
            {
                "frameIndex": frame_index,
                "x": round(u, 3),
                "y": round(v, 3),
                "visible": 0 <= u < frame_width and 0 <= v < frame_height,
                "source": "predicted_video_only_3d",
                "labelEligible": False,
                "status": "needs_review",
                "worldMeters": {"x": round(x, 4), "height": round(height, 4), "z": round(z, 4)},
            }
        )

    landing = frames[-1]
    trajectory = {
        "version": "1.0",
        "stage": "m1_3d_reconstruction",
        "generatedAt": _utc_now(),
        "sampleId": visible_artifact.get("sampleId"),
        "shotId": visible_artifact.get("shotId"),
        "sessionId": visible_artifact.get("sessionId"),
        "sourceVideo": visible_artifact.get("sourceVideo"),
        "status": "needs_review",
        "model": {
            "type": "video_only_ground_plane_ballistic_3d",
            "gravityMetersPerSecond2": GRAVITY_MPS2,
            "calibrationUsed": {
                "cameraHeightMeters": camera_height_m,
                "cameraAngleDegrees": pitch_degrees,
                "distanceMeters": calibration["distanceMeters"],
            },
        },
        "qc": _quality_qc(seed_ground_distance_m, calibration, fit_quality),
        "launchFrame": launch_frame,
        "landingFrame": landing_frame,
        "landingPointImage": {"x": landing["x"], "y": landing["y"]},
        "parameters": {
            "x0Meters": x0,
            "z0Meters": z0,
            "vxMps": vx,
            "vyMps": vy,
            "vzMps": vz,
        },
        "frames": frames,
    }
    return {"videoOnly3d": trajectory}


def build_trackman_constrained_3d_trajectory(
    visible_artifact: dict[str, Any],
    camera: dict[str, Any],
    trackman_reviewed: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(trackman_reviewed, dict):
        return _unavailable_trackman(
            "unavailable_invalid_trackman_fields",
            "TrackMan review payload must be an object",
            visible_artifact,
        )
    if trackman_reviewed.get("metricsUsable") is not True:
        return _unavailable_trackman(
            "unavailable_unconfirmed_trackman",
            "TrackMan metrics were not human-confirmed usable",
            visible_artifact,
        )
    if not isinstance(trackman_reviewed.get("correctedFields"), dict):
        return _unavailable_trackman(
            "unavailable_invalid_trackman_fields",
            "TrackMan correctedFields must be an object",
            visible_artifact,
        )

    values: dict[str, float | None] = {}
    field_specs = [
        ("ballSpeed", "mph", True, True),
        ("launchAngle", "deg", True, False),
        ("carry", "yd", False, True),
        ("apex", "yd", False, True),
    ]
    for name, unit, required, positive in field_specs:
        value, error_code, reason = _trackman_field(
            trackman_reviewed,
            name,
            unit,
            required=required,
            positive=positive,
        )
        if error_code == "missing":
            return _unavailable_trackman(
                "unavailable_missing_required_trackman_fields",
                reason or name,
                visible_artifact,
            )
        if error_code == "invalid_unit":
            return _unavailable_trackman("unavailable_invalid_trackman_units", reason or name, visible_artifact)
        if error_code == "invalid_value":
            return _unavailable_trackman("unavailable_invalid_trackman_fields", reason or name, visible_artifact)
        range_error = _validate_trackman_range(name, value)
        if range_error is not None:
            return _unavailable_trackman(
                "unavailable_invalid_trackman_fields",
                range_error,
                visible_artifact,
            )
        values[name] = value

    speed_mph = float(values["ballSpeed"])
    launch_angle_deg = float(values["launchAngle"])
    carry_yd = values["carry"]
    apex_yd = values["apex"]
    side_yd, side_source_field, side_error_code, side_reason = _trackman_directional_side_yd(trackman_reviewed)
    if side_error_code == "invalid_unit":
        return _unavailable_trackman("unavailable_invalid_trackman_units", side_reason or side_source_field or "side", visible_artifact)
    if side_error_code == "invalid_value":
        return _unavailable_trackman("unavailable_invalid_trackman_fields", side_reason or side_source_field or "side", visible_artifact)
    curve_yd, curve_source_field, curve_error_code, curve_reason = _trackman_curve_yd(trackman_reviewed)
    if curve_error_code == "invalid_unit":
        return _unavailable_trackman("unavailable_invalid_trackman_units", curve_reason or curve_source_field or "curve", visible_artifact)
    if curve_error_code == "invalid_value":
        return _unavailable_trackman("unavailable_invalid_trackman_fields", curve_reason or curve_source_field or "curve", visible_artifact)
    total_side_yd, total_side_error_code, total_side_reason = _trackman_signed_side_field_yd(trackman_reviewed, "totalSide")
    if total_side_error_code == "invalid_unit":
        return _unavailable_trackman("unavailable_invalid_trackman_units", total_side_reason or "totalSide", visible_artifact)
    if total_side_error_code == "invalid_value":
        return _unavailable_trackman("unavailable_invalid_trackman_fields", total_side_reason or "totalSide", visible_artifact)

    optional_trackman_inputs: dict[str, float] = {}
    optional_specs = [
        ("faceToPath", "deg", "faceToPathDeg", False),
        ("clubPath", "deg", "clubPathDeg", False),
        ("faceAngle", "deg", "faceAngleDeg", False),
        ("spinRate", "rpm", "spinRateRpm", True),
    ]
    for optional_name, optional_unit, input_name, positive in optional_specs:
        optional_value, optional_error_code, optional_reason = _trackman_optional_scalar(
            trackman_reviewed,
            optional_name,
            optional_unit,
            positive=positive,
        )
        if optional_error_code == "invalid_unit":
            return _unavailable_trackman("unavailable_invalid_trackman_units", optional_reason or optional_name, visible_artifact)
        if optional_error_code == "invalid_value":
            return _unavailable_trackman("unavailable_invalid_trackman_fields", optional_reason or optional_name, visible_artifact)
        if optional_value is not None:
            optional_trackman_inputs[input_name] = optional_value


    video = build_video_only_3d_trajectory(visible_artifact, camera)["videoOnly3d"]
    params = video["parameters"]
    direction_x = _finite_float("videoOnly3d parameters vxMps", params["vxMps"])
    direction_z = _finite_float("videoOnly3d parameters vzMps", params["vzMps"])
    direction_norm = math.hypot(direction_x, direction_z)
    if not math.isfinite(direction_norm) or direction_norm <= 1e-6:
        raise ValueError("videoOnly3d horizontal direction is invalid")

    intrinsics = _intrinsics(camera)
    calibration = _calibration(camera)
    camera_height_m = float(calibration["cameraHeightMeters"])
    pitch_degrees = float(calibration["cameraAngleDegrees"])
    pitch_rad = math.radians(pitch_degrees)

    speed_mps = speed_mph * MPH_TO_MPS
    launch_angle_rad = math.radians(launch_angle_deg)
    horizontal_speed = speed_mps * math.cos(launch_angle_rad)
    vertical_speed = speed_mps * math.sin(launch_angle_rad)
    if not math.isfinite(horizontal_speed) or horizontal_speed <= 0:
        return _unavailable_trackman(
            "unavailable_invalid_trackman_fields",
            "TrackMan ballSpeed and launchAngle must produce positive horizontal speed",
            visible_artifact,
        )
    if not math.isfinite(vertical_speed) or vertical_speed <= 0:
        return _unavailable_trackman(
            "unavailable_invalid_trackman_fields",
            "TrackMan launchAngle must produce positive vertical speed",
            visible_artifact,
        )

    unit_x = direction_x / direction_norm
    unit_z = direction_z / direction_norm
    x0 = _finite_float("videoOnly3d parameters x0Meters", params["x0Meters"])
    z0 = _finite_float("videoOnly3d parameters z0Meters", params["z0Meters"], positive=True)

    if apex_yd is not None:
        apex_m = apex_yd * YD_TO_M
        vy = math.sqrt(2.0 * GRAVITY_MPS2 * apex_m)
    else:
        vy = vertical_speed
        apex_m = (vy * vy) / (2.0 * GRAVITY_MPS2)
    landing_time = 2.0 * vy / GRAVITY_MPS2
    vertical_acceleration = -GRAVITY_MPS2
    if not math.isfinite(landing_time) or landing_time <= 0:
        return _unavailable_trackman(
            "unavailable_invalid_trackman_fields",
            "TrackMan metrics produced invalid landing time",
            visible_artifact,
        )

    forward_carry_m = carry_yd * YD_TO_M if carry_yd is not None else horizontal_speed * landing_time
    side_carry_m = (side_yd or 0.0) * YD_TO_M
    curve_m = (curve_yd or 0.0) * YD_TO_M
    launch_line_side_m = side_carry_m - curve_m
    horizontal_distance_m = math.hypot(forward_carry_m, side_carry_m)
    horizontal_speed_model = horizontal_distance_m / landing_time
    right_x = unit_z
    right_z = -unit_x
    vx = forward_carry_m / landing_time * unit_x + side_carry_m / landing_time * right_x
    vz = forward_carry_m / landing_time * unit_z + side_carry_m / landing_time * right_z

    fps = float(visible_artifact["fps"])
    launch_frame = int(visible_artifact["launchFrame"])
    landing_frame = int(math.ceil(launch_frame + landing_time * fps))
    frame_width = float(visible_artifact["frameWidth"])
    frame_height = float(visible_artifact["frameHeight"])

    frames = []
    visible_constraints = _visible_ball_constraints(visible_artifact, launch_frame=launch_frame)
    visible_overlap_residuals: list[float] = []

    for frame_index in range(launch_frame, landing_frame + 1):
        t = min((frame_index - launch_frame) / fps, landing_time)
        progress = 1.0 if landing_time <= 0 else min(max(t / landing_time, 0.0), 1.0)
        height = max(0.0, 4.0 * apex_m * progress * (1.0 - progress))
        forward_distance = forward_carry_m * progress
        side_distance = launch_line_side_m * progress + curve_m * progress * progress
        x = x0 + unit_x * forward_distance + right_x * side_distance
        z = z0 + unit_z * forward_distance + right_z * side_distance
        if not math.isfinite(z) or z <= 0:
            raise ValueError("TrackMan-constrained trajectory produced invalid z progression")
        u, v = _project(x, height, z, intrinsics, camera_height_m, pitch_rad)
        source = "predicted_trackman_constrained_3d"
        constraint = visible_constraints.get(frame_index)
        if constraint is not None:
            visible_overlap_residuals.append(0.0)
            u = constraint["x"]
            v = constraint["y"]
            source = "visible_ball_hard_constraint"
        frames.append(
            {
                "frameIndex": frame_index,
                "x": round(u, 3),
                "y": round(v, 3),
                "visible": 0 <= u < frame_width and 0 <= v < frame_height,
                "source": source,
                "labelEligible": False,
                "status": "needs_review",
                "worldMeters": {"x": round(x, 4), "height": round(height, 4), "z": round(z, 4)},
            }
        )

    landing = frames[-1]
    comparison_qc = _trackman_comparison_qc(
        predicted_carry_yd=forward_carry_m / YD_TO_M,
        predicted_apex_yd=apex_m / YD_TO_M,
        predicted_side_yd=side_yd,
        confirmed_carry_yd=carry_yd,
        confirmed_apex_yd=apex_yd,
        confirmed_side_yd=side_yd,
    )
    trackman_inputs: dict[str, float | None] = {
        "ballSpeedMph": speed_mph,
        "launchAngleDeg": launch_angle_deg,
        "carryYd": carry_yd,
        "apexYd": apex_yd,
    }
    if side_yd is not None:
        trackman_inputs["sideYd"] = side_yd
        trackman_inputs["sideSourceField"] = side_source_field
    if curve_yd is not None:
        trackman_inputs["curveYd"] = curve_yd
        trackman_inputs["curveSourceField"] = curve_source_field
        trackman_inputs["launchLineSideYd"] = (side_yd or 0.0) - curve_yd
    if total_side_yd is not None:
        trackman_inputs["totalSideYd"] = total_side_yd
    trackman_inputs.update(optional_trackman_inputs)
    trajectory = {
        "version": "1.0",
        "stage": "m1_3d_reconstruction",
        "generatedAt": _utc_now(),
        "sampleId": visible_artifact.get("sampleId"),
        "shotId": visible_artifact.get("shotId"),
        "sessionId": visible_artifact.get("sessionId"),
        "sourceVideo": visible_artifact.get("sourceVideo"),
        "status": "needs_review",
        "model": {
            "type": "trackman_constrained_endpoint_curve_3d",
            "gravityMetersPerSecond2": GRAVITY_MPS2,
            "verticalAccelerationMetersPerSecond2": round(vertical_acceleration, 6),
            "calibrationUsed": {
                "cameraHeightMeters": camera_height_m,
                "cameraAngleDegrees": pitch_degrees,
                "distanceMeters": calibration["distanceMeters"],
            },
        },
        "trackmanInputs": trackman_inputs,
        "trackmanInputsProvenance": {
            "source": "human_confirmed_corrected_fields",
            "metricsUsable": True,
            "reviewer": trackman_reviewed.get("reviewer"),
            "reviewedAt": trackman_reviewed.get("reviewedAt"),
        },
        "videoOnlyReference": {
            "status": video["status"],
            "parameters": params,
            "qc": video.get("qc"),
        },
        "qc": {
            "trackmanComparison": comparison_qc,
            "visibleOverlap": _visible_overlap_qc(
                constraints=visible_constraints,
                residuals_px=visible_overlap_residuals,
            ),
        },
        "launchFrame": launch_frame,
        "landingFrame": landing_frame,
        "landingPointImage": {"x": landing["x"], "y": landing["y"]},
        "parameters": {
            "x0Meters": x0,
            "z0Meters": z0,
            "vxMps": vx,
            "vyMps": vy,
            "vzMps": vz,
            "horizontalSpeedMps": horizontal_speed_model,
            "landingTimeSeconds": landing_time,
            "forwardCarryMeters": forward_carry_m,
            "sideCarryMeters": side_carry_m,
            "curveMeters": curve_m,
            "launchLineSideMeters": launch_line_side_m,
            "apexMeters": apex_m,
        },
        "frames": frames,
    }
    return {"trackmanConstrained3d": trajectory}
