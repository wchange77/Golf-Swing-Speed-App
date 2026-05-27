from __future__ import annotations

import math
from statistics import mean, median
from typing import Any

YD_TO_M = 0.9144
SIDE_DIRECTION_THRESHOLD_YD = 0.5
GROUND_LANDING_TOLERANCE_M = 0.25
FORWARD_LANDING_TOLERANCE_M = 1.0


def _section(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    return value if isinstance(value, dict) else {}


def _frames(section: dict[str, Any]) -> list[dict[str, Any]]:
    value = section.get("frames")
    return [frame for frame in value if isinstance(frame, dict)] if isinstance(value, list) else []


def _last_world(frames: list[dict[str, Any]]) -> dict[str, Any]:
    if not frames:
        return {}
    world = frames[-1].get("worldMeters")
    return world if isinstance(world, dict) else {}


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _world(frame: dict[str, Any]) -> dict[str, Any]:
    value = frame.get("worldMeters")
    return value if isinstance(value, dict) else {}


def _parameter_states(video_only: dict[str, Any]) -> dict[str, Any]:
    params = video_only.get("parameters") if isinstance(video_only.get("parameters"), dict) else {}
    return {
        key: value
        for key, value in params.items()
        if isinstance(value, dict) and "status" in value
    }


def _evidence_and_failures(parameter_states: dict[str, Any], section: dict[str, Any]) -> tuple[list[int], list[str]]:
    frames: set[int] = set()
    failures: list[str] = []
    for name, value in parameter_states.items():
        evidence = value.get("evidenceFrames")
        if isinstance(evidence, list):
            for frame in evidence:
                try:
                    frames.add(int(frame))
                except (TypeError, ValueError):
                    continue
        reason = value.get("failureReason")
        if reason:
            failures.append(f"{name}: {reason}")
    section_reason = section.get("reason")
    if section_reason:
        failures.append(f"videoOnly3d: {section_reason}")
    return sorted(frames), failures


def _trajectory_measurements(frames: list[dict[str, Any]]) -> dict[str, float | None]:
    measurements: dict[str, float | None] = {
        "videoOnlyCarryYd": None,
        "videoOnlyApexYd": None,
        "videoOnlySideYd": None,
        "landingXMeters": None,
        "landingZMeters": None,
        "landingHeightMeters": None,
        "landingForwardMeters": None,
    }
    if not frames:
        return measurements
    first_world = _world(frames[0])
    last_world = _world(frames[-1])
    first_x = _number(first_world.get("x"))
    first_z = _number(first_world.get("z"))
    last_x = _number(last_world.get("x"))
    last_z = _number(last_world.get("z"))
    last_height = _number(last_world.get("height"))
    heights = [_number(_world(frame).get("height")) for frame in frames]
    finite_heights = [height for height in heights if height is not None]
    measurements["landingXMeters"] = last_x
    measurements["landingZMeters"] = last_z
    measurements["landingHeightMeters"] = last_height
    if first_x is not None and first_z is not None and last_x is not None and last_z is not None:
        side_m = last_x - first_x
        forward_m = last_z - first_z
        measurements["videoOnlySideYd"] = side_m / YD_TO_M
        measurements["videoOnlyCarryYd"] = forward_m / YD_TO_M
        measurements["landingForwardMeters"] = forward_m
    if finite_heights:
        measurements["videoOnlyApexYd"] = max(finite_heights) / YD_TO_M
    return measurements


def _trackman_inputs(trackman: dict[str, Any], comparison: dict[str, Any]) -> dict[str, float | None]:
    inputs = trackman.get("trackmanInputs") if isinstance(trackman.get("trackmanInputs"), dict) else {}
    return {
        "carryYd": _number(inputs.get("carryYd") if inputs else comparison.get("confirmedCarryYd")),
        "apexYd": _number(inputs.get("apexYd") if inputs else comparison.get("confirmedApexYd")),
        "sideYd": _number(inputs.get("sideYd") if inputs else comparison.get("confirmedSideYd")),
        "curveYd": _number(inputs.get("curveYd")) if inputs else None,
        "totalSideYd": _number(inputs.get("totalSideYd")) if inputs else None,
        "ballSpeedMph": _number(inputs.get("ballSpeedMph")) if inputs else None,
        "launchAngleDeg": _number(inputs.get("launchAngleDeg")) if inputs else None,
    }


def _signed_direction(value: float | None) -> int | None:
    if value is None or abs(value) < SIDE_DIRECTION_THRESHOLD_YD:
        return None
    return -1 if value < 0 else 1


def _curve_direction_status(video_side_yd: float | None, trackman_values: dict[str, float | None]) -> str:
    trackman_direction = None
    # video_side_yd is final landing side, so compare it to TrackMan side first.
    # TrackMan curve can point opposite the final side when the ball starts across
    # the target line and bends back; use curve only when side fields are absent.
    for key in ("sideYd", "totalSideYd", "curveYd"):
        trackman_direction = _signed_direction(trackman_values.get(key))
        if trackman_direction is not None:
            break
    if trackman_direction is None:
        return "unavailable"
    video_direction = _signed_direction(video_side_yd)
    if video_direction is None:
        return "indeterminate"
    return "ok" if video_direction == trackman_direction else "mismatch"


def _landing_errors(frames: list[dict[str, Any]]) -> list[str]:
    if not frames:
        return ["missing_or_empty_video_only_frames"]
    errors: list[str] = []
    first_world = _world(frames[0])
    first_z = _number(first_world.get("z"))
    for frame in frames:
        world = _world(frame)
        x = _number(world.get("x"))
        height = _number(world.get("height"))
        z = _number(world.get("z"))
        if x is None or height is None or z is None:
            errors.append("non_finite_trajectory_point")
            return errors
        if height < -GROUND_LANDING_TOLERANCE_M:
            errors.append("infinite_down_trajectory")
            return errors
    last_world = _world(frames[-1])
    last_height = _number(last_world.get("height"))
    last_z = _number(last_world.get("z"))
    if last_height is None:
        errors.append("non_finite_trajectory_point")
    elif last_height > GROUND_LANDING_TOLERANCE_M:
        errors.append("missing_ground_plane_landing")
    if first_z is not None and last_z is not None and last_z <= first_z + FORWARD_LANDING_TOLERANCE_M:
        errors.append("landing_not_forward_grass")
    return errors


def _video_only_failure_status(video_only: dict[str, Any], errors: list[str]) -> str:
    reason = str(video_only.get("reason") or "").lower()
    video_status = str(video_only.get("status") or "").lower()
    if "geometry" in video_status or "geometry" in reason:
        return "geometry_unavailable"
    if "at least three" in reason or "visible" in reason and "point" in reason:
        return "insufficient_visible_points"
    if "missing_or_empty_video_only_frames" in errors and "visible" in reason:
        return "insufficient_visible_points"
    return "failed"


def summarize_trajectory_file(
    payload: dict[str, Any],
    *,
    max_error_carry_yd: float = 20.0,
    max_reprojection_rmse_px: float = 10.0,
) -> dict[str, Any]:
    video_only = _section(payload, "videoOnly3d")
    trackman = _section(payload, "trackmanConstrained3d")
    sample_id = str(video_only.get("sampleId") or trackman.get("sampleId") or payload.get("sampleId") or "unknown")
    errors: list[str] = []
    warnings: list[str] = []
    video_frames = _frames(video_only)
    trackman_frames = _frames(trackman)
    errors.extend(_landing_errors(video_frames))
    if any(frame.get("labelEligible") is not False for frame in video_frames + trackman_frames):
        errors.append("model_frame_label_eligible")

    trajectory_metrics = _trajectory_measurements(video_frames)
    metrics: dict[str, Any] = {
        "carryErrorYd": None,
        "apexErrorYd": None,
        "sideErrorYd": None,
        "visibleReprojectionRmsePx": None,
        "videoOnlyCarryErrorYd": None,
        "videoOnlyApexErrorYd": None,
        "videoOnlySideErrorYd": None,
        "trackmanCarryYd": None,
        "trackmanApexYd": None,
        "trackmanSideYd": None,
        "trackmanCurveYd": None,
        **trajectory_metrics,
    }
    trackman_status = str(trackman.get("status") or "")
    trackman_available = bool(trackman) and not trackman_status.startswith("unavailable_")
    curve_direction_status = "unavailable"
    if trackman_available:
        qc = trackman.get("qc") if isinstance(trackman.get("qc"), dict) else {}
        comparison = qc.get("trackmanComparison") if isinstance(qc.get("trackmanComparison"), dict) else {}
        visible = qc.get("visibleOverlap") if isinstance(qc.get("visibleOverlap"), dict) else {}
        trackman_values = _trackman_inputs(trackman, comparison)
        metrics["carryErrorYd"] = _number(comparison.get("carryResidualYd"))
        metrics["apexErrorYd"] = _number(comparison.get("apexResidualYd"))
        metrics["sideErrorYd"] = _number(comparison.get("sideResidualYd"))
        metrics["visibleReprojectionRmsePx"] = _number(visible.get("rmsePx"))
        metrics["trackmanCarryYd"] = trackman_values["carryYd"]
        metrics["trackmanApexYd"] = trackman_values["apexYd"]
        metrics["trackmanSideYd"] = trackman_values["sideYd"]
        metrics["trackmanCurveYd"] = trackman_values["curveYd"]
        if metrics["videoOnlyCarryYd"] is not None and trackman_values["carryYd"] is not None:
            metrics["videoOnlyCarryErrorYd"] = metrics["videoOnlyCarryYd"] - trackman_values["carryYd"]
        if metrics["videoOnlyApexYd"] is not None and trackman_values["apexYd"] is not None:
            metrics["videoOnlyApexErrorYd"] = metrics["videoOnlyApexYd"] - trackman_values["apexYd"]
        if metrics["videoOnlySideYd"] is not None and trackman_values["sideYd"] is not None:
            metrics["videoOnlySideErrorYd"] = metrics["videoOnlySideYd"] - trackman_values["sideYd"]
        if metrics["carryErrorYd"] is not None and abs(metrics["carryErrorYd"]) > max_error_carry_yd:
            warnings.append("trackman_carry_error_exceeds_threshold")
        if metrics["visibleReprojectionRmsePx"] is not None and metrics["visibleReprojectionRmsePx"] > max_reprojection_rmse_px:
            warnings.append("visible_reprojection_rmse_exceeds_threshold")
        curve_direction_status = _curve_direction_status(metrics["videoOnlySideYd"], trackman_values)
        if curve_direction_status == "mismatch":
            warnings.append("curve_direction_mismatch")
    else:
        warnings.append("trackman_comparison_unavailable")
    metrics["curveDirectionStatus"] = curve_direction_status

    status = "ok"
    if errors:
        status = _video_only_failure_status(video_only, errors)
    elif warnings:
        if warnings == ["trackman_comparison_unavailable"]:
            status = "trackman_unavailable"
        else:
            status = "needs_review"
    parameter_states = _parameter_states(video_only)
    evidence_frames, failure_reasons = _evidence_and_failures(parameter_states, video_only)
    model = video_only.get("model") if isinstance(video_only.get("model"), dict) else {}
    trackman_model = trackman.get("model") if isinstance(trackman.get("model"), dict) else {}
    return {
        "sampleId": sample_id,
        "status": status,
        "videoOnlyStatus": video_only.get("status"),
        "trackmanStatus": trackman.get("status") if trackman else "not_generated",
        "trackmanComparisonStatus": "available" if trackman_available else "unavailable",
        "modelVersions": {
            "videoOnlyType": model.get("type"),
            "videoOnlyFamily": model.get("modelFamily"),
            "trackmanType": trackman_model.get("type"),
            "trackmanFamily": trackman_model.get("modelFamily"),
        },
        "videoOnlyFrameCount": len(video_frames),
        "trackmanFrameCount": len(trackman_frames),
        "parameterStates": parameter_states,
        "evidenceFrames": evidence_frames,
        "failureReasons": failure_reasons,
        "metrics": metrics,
        "errors": errors,
        "warnings": warnings,
    }


def aggregate_summaries(summaries: list[dict[str, Any]]) -> dict[str, Any]:
    status_counts: dict[str, int] = {}
    carry_errors: list[float] = []
    reprojection_errors: list[float] = []
    for summary in summaries:
        status = str(summary.get("status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
        metrics = summary.get("metrics") if isinstance(summary.get("metrics"), dict) else {}
        carry = _number(metrics.get("carryErrorYd"))
        reprojection = _number(metrics.get("visibleReprojectionRmsePx"))
        if carry is not None:
            carry_errors.append(abs(carry))
        if reprojection is not None:
            reprojection_errors.append(reprojection)
    return {
        "statusCounts": status_counts,
        "trackmanAvailableCount": sum(1 for item in summaries if item.get("trackmanComparisonStatus") == "available"),
        "videoOnlyCount": sum(1 for item in summaries if item.get("videoOnlyFrameCount", 0) > 0),
        "failedCount": status_counts.get("failed", 0),
        "meanAbsCarryErrorYd": mean(carry_errors) if carry_errors else None,
        "medianAbsCarryErrorYd": median(carry_errors) if carry_errors else None,
        "meanReprojectionRmsePx": mean(reprojection_errors) if reprojection_errors else None,
    }
