from __future__ import annotations

import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any, Iterable

import numpy as np

try:
    from lib.tracknet_m1_camera_model import build_camera_model_for_shot
except Exception:  # pragma: no cover - CLI/runtime fallback when imported outside tools path.
    build_camera_model_for_shot = None  # type: ignore[assignment]


SUPPORTED_VARIANTS = ("image_only", "metric_sidecar")
GRAVITY_MPS2 = 9.80665
MPS_TO_MPH = 2.2369362920544
MIN_OBSERVED_VERTICAL_RISE_PX = 18.0
MIN_OBSERVED_FLIGHT_DISPLACEMENT_PX = 30.0
MIN_REVIEW_FIT_POINTS = 12
LEGACY_TRAINING_LABEL_POLICY = "legacy_debug_review_only_never_training_truth"
LEGACY_TRAINING_LABEL_REJECTION_REASON = "legacy_predicted_flight_not_training_truth"
FORMAL_M2_REPLACEMENT = ["videoOnly3d", "trackmanConstrained3d"]


class PredictedFlightError(ValueError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(path)


def _legacy_predicted_flight(payload: dict[str, Any]) -> dict[str, Any]:
    guarded = dict(payload)
    guarded.update({
        "legacy": True,
        "reviewOnly": True,
        "formalM2": False,
        "labelEligible": False,
        "trainingLabelPolicy": LEGACY_TRAINING_LABEL_POLICY,
        "trainingLabelRejectionReason": LEGACY_TRAINING_LABEL_REJECTION_REASON,
        "formalM2Replacement": FORMAL_M2_REPLACEMENT,
    })
    frames = guarded.get("frames")
    if isinstance(frames, list):
        guarded["frames"] = [
            {
                **frame,
                "labelEligible": False,
                "trainingLabelRejectionReason": LEGACY_TRAINING_LABEL_REJECTION_REASON,
            }
            if isinstance(frame, dict)
            else frame
            for frame in frames
        ]
    return guarded


def _safe_name(value: str, fallback: str = "sample") -> str:
    text = value.strip() or fallback
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in text)
    cleaned = cleaned.strip("._") or fallback
    if cleaned in {".", ".."} or ".." in cleaned:
        return fallback
    return cleaned[:140]


def _round(value: float | int | None, digits: int = 3) -> float | None:
    if value is None:
        return None
    if not math.isfinite(float(value)):
        return None
    return round(float(value), digits)


def _fps(trajectory: dict[str, Any]) -> float:
    fps = float(trajectory.get("fps") or 240.0)
    return fps if fps > 1 else 240.0


def _frame_key(frame: dict[str, Any]) -> int:
    return int(frame["frameIndex"])


def _visible_ball_frames(trajectory: dict[str, Any]) -> list[dict[str, Any]]:
    frames = trajectory.get("frames") if isinstance(trajectory.get("frames"), list) else []
    visible = []
    for frame in frames:
        if not isinstance(frame, dict) or not frame.get("visible"):
            continue
        if frame.get("x") is None or frame.get("y") is None or frame.get("frameIndex") is None:
            continue
        visible.append(frame)
    return sorted(visible, key=_frame_key)


def detect_launch_frame(
    trajectory: dict[str, Any],
    *,
    displacement_threshold_px: float = 5.0,
    confirmation_frames: int = 2,
) -> int | None:
    seed = trajectory.get("seed") if isinstance(trajectory.get("seed"), dict) else {}
    seed_frame = int(seed.get("frameIndex", 0))
    seed_x = float(seed.get("x", 0.0))
    seed_y = float(seed.get("y", 0.0))
    visible = [frame for frame in _visible_ball_frames(trajectory) if int(frame["frameIndex"]) >= seed_frame]
    for index, frame in enumerate(visible):
        dx = float(frame["x"]) - seed_x
        dy = float(frame["y"]) - seed_y
        if math.hypot(dx, dy) < displacement_threshold_px:
            continue
        lookahead = visible[index : index + max(1, confirmation_frames)]
        if len(lookahead) < confirmation_frames:
            return int(frame["frameIndex"])
        if all(math.hypot(float(item["x"]) - seed_x, float(item["y"]) - seed_y) >= displacement_threshold_px for item in lookahead):
            return int(frame["frameIndex"])
    return int(visible[0]["frameIndex"]) if visible else None


def _observed_flight_evidence(
    trajectory: dict[str, Any],
    launch_frame: int,
    *,
    min_vertical_rise_px: float = MIN_OBSERVED_VERTICAL_RISE_PX,
    min_total_displacement_px: float = MIN_OBSERVED_FLIGHT_DISPLACEMENT_PX,
) -> dict[str, Any]:
    visible = [frame for frame in _visible_ball_frames(trajectory) if int(frame["frameIndex"]) >= launch_frame]
    if len(visible) < 2:
        return {
            "visibleFrameCount": len(visible),
            "verticalRisePx": 0.0,
            "maxDisplacementPx": 0.0,
            "hasVisibleFlight": False,
        }
    anchor = visible[0]
    anchor_x = float(anchor["x"])
    anchor_y = float(anchor["y"])
    vertical_rise = max(0.0, anchor_y - min(float(frame["y"]) for frame in visible))
    max_displacement = max(math.hypot(float(frame["x"]) - anchor_x, float(frame["y"]) - anchor_y) for frame in visible)
    return {
        "visibleFrameCount": len(visible),
        "verticalRisePx": _round(vertical_rise, 3),
        "maxDisplacementPx": _round(max_displacement, 3),
        "minVerticalRisePx": float(min_vertical_rise_px),
        "minDisplacementPx": float(min_total_displacement_px),
        "hasVisibleFlight": vertical_rise >= min_vertical_rise_px and max_displacement >= min_total_displacement_px,
    }


def _is_reliable_fit_frame(
    frame: dict[str, Any],
    *,
    min_confidence: float,
    max_crosscheck_px: float,
    max_patch_spread_px: float,
) -> bool:
    confidence = frame.get("confidence")
    if confidence is not None and float(confidence) < min_confidence:
        return False
    cross_check = frame.get("crossCheck") if isinstance(frame.get("crossCheck"), dict) else {}
    if cross_check:
        distance = cross_check.get("distancePx")
        status = str(cross_check.get("status") or "agree")
        if status not in {"", "agree"}:
            return False
        if distance is not None and float(distance) > max_crosscheck_px:
            return False
    spread = frame.get("pointSpreadPx")
    if spread is not None and float(spread) > max_patch_spread_px:
        return False
    return True


def _patch_frame_map(trajectory: dict[str, Any]) -> dict[int, dict[str, Any]]:
    frames = trajectory.get("patchFrames") if isinstance(trajectory.get("patchFrames"), list) else []
    return {int(frame["frameIndex"]): frame for frame in frames if isinstance(frame, dict) and frame.get("frameIndex") is not None}


def _select_fit_frames(
    trajectory: dict[str, Any],
    launch_frame: int,
    *,
    min_confidence: float = 0.35,
    max_crosscheck_px: float = 12.0,
    max_patch_spread_px: float = 32.0,
    max_fit_frames: int = 90,
    min_strict_fit_frames: int = 12,
    fallback_max_patch_spread_px: float = 48.0,
    fallback_min_confidence: float = 0.2,
    fallback_search_frames: int = 240,
) -> list[dict[str, Any]]:
    patch_by_frame = _patch_frame_map(trajectory)
    fit_frames = []
    expected_next: int | None = None
    for frame in _visible_ball_frames(trajectory):
        frame_index = int(frame["frameIndex"])
        if frame_index < launch_frame:
            continue
        merged = {**patch_by_frame.get(frame_index, {}), **frame}
        if expected_next is not None and frame_index > expected_next:
            break
        if not _is_reliable_fit_frame(
            merged,
            min_confidence=min_confidence,
            max_crosscheck_px=max_crosscheck_px,
            max_patch_spread_px=max_patch_spread_px,
        ):
            break
        fit_frames.append(merged)
        expected_next = frame_index + 1
        if len(fit_frames) >= max_fit_frames:
            break
    if len(fit_frames) >= min_strict_fit_frames:
        return fit_frames

    fallback_frames = []
    for frame in _visible_ball_frames(trajectory):
        frame_index = int(frame["frameIndex"])
        if frame_index < launch_frame:
            continue
        if frame_index > launch_frame + fallback_search_frames and len(fallback_frames) >= 2:
            break
        merged = {**patch_by_frame.get(frame_index, {}), **frame}
        confidence = merged.get("confidence")
        if confidence is not None and float(confidence) < fallback_min_confidence:
            continue
        spread = merged.get("pointSpreadPx")
        if spread is not None and float(spread) > fallback_max_patch_spread_px:
            continue
        merged["fitSelection"] = "tapnext_fallback_crosscheck_not_required"
        fallback_frames.append(merged)
        if len(fallback_frames) >= max_fit_frames:
            break

    if len(fallback_frames) < 2:
        seed = trajectory.get("seed") if isinstance(trajectory.get("seed"), dict) else {}
        seed_frame = seed.get("frameIndex")
        if fallback_frames and seed_frame is not None and int(seed_frame) < int(fallback_frames[0]["frameIndex"]):
            fallback_frames.insert(0, {
                "frameIndex": int(seed_frame),
                "x": float(seed.get("x", fallback_frames[0]["x"])),
                "y": float(seed.get("y", fallback_frames[0]["y"])),
                "visible": True,
                "confidence": 0.5,
                "fitSelection": "seed_fallback",
            })
    return fallback_frames


def _output_frame_range(trajectory: dict[str, Any], output_frame_count: int | None) -> list[int]:
    frames = trajectory.get("frames") if isinstance(trajectory.get("frames"), list) else []
    seed = trajectory.get("seed") if isinstance(trajectory.get("seed"), dict) else {}
    if frames:
        start = min(int(frame["frameIndex"]) for frame in frames if isinstance(frame, dict) and frame.get("frameIndex") is not None)
        default_count = max(int(frame["frameIndex"]) for frame in frames if isinstance(frame, dict) and frame.get("frameIndex") is not None) - start + 1
    else:
        start = int(seed.get("frameIndex", 0))
        default_count = 1
    count = max(1, int(output_frame_count if output_frame_count is not None else default_count))
    source_count = trajectory.get("sourceFrameCount") or trajectory.get("frameCount")
    if source_count is not None:
        count = min(count, max(1, int(source_count) - start))
    return list(range(start, start + count))


def _fit_image_only(fit_frames: list[dict[str, Any]], launch_frame: int, fps: float) -> dict[str, Any]:
    times = np.array([(int(frame["frameIndex"]) - launch_frame) / fps for frame in fit_frames], dtype=np.float64)
    xs = np.array([float(frame["x"]) for frame in fit_frames], dtype=np.float64)
    ys = np.array([float(frame["y"]) for frame in fit_frames], dtype=np.float64)
    degree = min(2, len(fit_frames) - 1)
    x_coeff = np.polyfit(times, xs, degree)
    y_coeff = np.polyfit(times, ys, degree)
    x_fit = np.polyval(x_coeff, times)
    y_fit = np.polyval(y_coeff, times)
    residuals = np.sqrt((x_fit - xs) ** 2 + (y_fit - ys) ** 2)
    vx_px = float(np.polyder(np.poly1d(x_coeff))(0.0)) if degree >= 1 else 0.0
    vy_px = float(np.polyder(np.poly1d(y_coeff))(0.0)) if degree >= 1 else 0.0
    return {
        "type": "image_only_quadratic_pixel_fit",
        "xCoefficients": [float(value) for value in x_coeff],
        "yCoefficients": [float(value) for value in y_coeff],
        "reprojectionErrorsPx": residuals,
        "pixelVelocityAtLaunch": {"vxPxPerSecond": vx_px, "vyPxPerSecond": vy_px, "speedPxPerSecond": math.hypot(vx_px, vy_px)},
        "predict": lambda t: (float(np.polyval(x_coeff, t)), float(np.polyval(y_coeff, t))),
    }


def _intrinsics(camera_sidecar: dict[str, Any]) -> dict[str, Any] | None:
    intrinsics = camera_sidecar.get("intrinsics")
    if isinstance(intrinsics, dict):
        return intrinsics
    camera_model = camera_sidecar.get("cameraModel") if isinstance(camera_sidecar.get("cameraModel"), dict) else {}
    intrinsics = camera_model.get("intrinsics")
    return intrinsics if isinstance(intrinsics, dict) else None


def _calibration(camera_sidecar: dict[str, Any]) -> dict[str, Any]:
    calibration = camera_sidecar.get("calibration")
    if isinstance(calibration, dict):
        return calibration
    camera_model = camera_sidecar.get("cameraModel") if isinstance(camera_sidecar.get("cameraModel"), dict) else {}
    calibration = camera_model.get("calibration")
    return calibration if isinstance(calibration, dict) else {}


def _distance_meters(camera_sidecar: dict[str, Any]) -> float | None:
    calibration = _calibration(camera_sidecar)
    environment = camera_sidecar.get("environment") if isinstance(camera_sidecar.get("environment"), dict) else {}
    value = calibration.get("distanceMeters", environment.get("distanceMeters"))
    if value is None:
        return None
    distance = float(value)
    return distance if distance > 0 else None


def _fit_metric_sidecar(
    trajectory: dict[str, Any],
    fit_frames: list[dict[str, Any]],
    launch_frame: int,
    fps: float,
    camera_sidecar: dict[str, Any],
) -> dict[str, Any]:
    intrinsics = _intrinsics(camera_sidecar)
    distance = _distance_meters(camera_sidecar)
    if intrinsics is None or distance is None:
        raise PredictedFlightError("metric_sidecar requires intrinsics and distanceMeters")
    fx = float(intrinsics["fx"])
    fy = float(intrinsics["fy"])
    if fx <= 0 or fy <= 0:
        raise PredictedFlightError("metric_sidecar intrinsics must contain positive fx/fy")
    seed = trajectory.get("seed") if isinstance(trajectory.get("seed"), dict) else {}
    seed_x = float(seed.get("x", fit_frames[0]["x"]))
    seed_y = float(seed.get("y", fit_frames[0]["y"]))
    scale_x = distance / fx
    scale_y = distance / fy
    times = np.array([(int(frame["frameIndex"]) - launch_frame) / fps for frame in fit_frames], dtype=np.float64)
    world_x = np.array([(float(frame["x"]) - seed_x) * scale_x for frame in fit_frames], dtype=np.float64)
    world_y = np.array([-(float(frame["y"]) - seed_y) * scale_y for frame in fit_frames], dtype=np.float64)

    x_params = np.polyfit(times, world_x, 1)
    adjusted_y = world_y + 0.5 * GRAVITY_MPS2 * times * times
    y_params = np.polyfit(times, adjusted_y, 1)
    vx = float(x_params[0])
    x0 = float(x_params[1])
    vy = float(y_params[0])
    y0 = float(y_params[1])

    pred_x = x0 + vx * times
    pred_y = y0 + vy * times - 0.5 * GRAVITY_MPS2 * times * times
    pred_px_x = seed_x + pred_x / scale_x
    pred_px_y = seed_y - pred_y / scale_y
    observed_px_x = np.array([float(frame["x"]) for frame in fit_frames], dtype=np.float64)
    observed_px_y = np.array([float(frame["y"]) for frame in fit_frames], dtype=np.float64)
    residuals = np.sqrt((pred_px_x - observed_px_x) ** 2 + (pred_px_y - observed_px_y) ** 2)
    launch_angle = math.degrees(math.atan2(vy, abs(vx))) if abs(vx) > 1e-9 else 90.0
    speed = math.hypot(vx, vy)
    calibration = _calibration(camera_sidecar)
    return {
        "type": "metric_sidecar_gravity_fit",
        "gravityMetersPerSecond2": GRAVITY_MPS2,
        "scaleMetersPerPixel": {"x": scale_x, "y": scale_y},
        "parameters": {"x0Meters": x0, "y0Meters": y0, "vxMps": vx, "vyMps": vy},
        "reprojectionErrorsPx": residuals,
        "metricEstimates": {
            "ballSpeedMps": speed,
            "ballSpeedMph": speed * MPS_TO_MPH,
            "launchAngleDeg": launch_angle,
            "launchDirectionDeg": None,
            "monocularDepthSource": "not_available",
            "calibration": {
                "distanceMeters": distance,
                "cameraHeightMeters": _round(calibration.get("cameraHeightMeters"), 3) if calibration.get("cameraHeightMeters") is not None else None,
                "cameraAngleDegrees": _round(calibration.get("cameraAngleDegrees"), 3) if calibration.get("cameraAngleDegrees") is not None else None,
                "method": calibration.get("method"),
                "confidence": calibration.get("confidence"),
            },
        },
        "predict": lambda t: (float(seed_x + (x0 + vx * t) / scale_x), float(seed_y - (y0 + vy * t - 0.5 * GRAVITY_MPS2 * t * t) / scale_y)),
    }


def _percentile(values: Iterable[float], percentile: float) -> float | None:
    series = [float(value) for value in values if math.isfinite(float(value))]
    if not series:
        return None
    return float(np.percentile(np.array(series, dtype=np.float64), percentile))


def _fit_error_summary(errors: Iterable[float]) -> dict[str, Any]:
    series = [float(value) for value in errors if math.isfinite(float(value))]
    if not series:
        return {"rmsePx": None, "p95Px": None, "maxPx": None}
    arr = np.array(series, dtype=np.float64)
    return {
        "rmsePx": round(float(math.sqrt(np.mean(arr * arr))), 3),
        "p95Px": round(float(np.percentile(arr, 95)), 3),
        "maxPx": round(float(np.max(arr)), 3),
    }


def _crosscheck_agreement_ratio(fit_frames: list[dict[str, Any]]) -> float:
    considered = 0
    agree = 0
    for frame in fit_frames:
        cross_check = frame.get("crossCheck") if isinstance(frame.get("crossCheck"), dict) else None
        if cross_check is None:
            continue
        considered += 1
        if str(cross_check.get("status") or "agree") == "agree":
            agree += 1
    if considered == 0:
        return 1.0
    return agree / considered


def _prediction_confidence(fit_count: int, span_frames: int, rmse_px: float | None, variant: str, crosscheck_agreement_ratio: float = 1.0) -> float:
    count_score = min(1.0, fit_count / 24.0)
    span_score = min(1.0, span_frames / 24.0)
    error_score = 0.5 if rmse_px is None else max(0.0, 1.0 - rmse_px / 24.0)
    variant_penalty = 0.9 if variant == "metric_sidecar" else 0.8
    crosscheck_multiplier = 0.55 + 0.45 * max(0.0, min(1.0, crosscheck_agreement_ratio))
    return round(max(0.0, min(1.0, (0.45 * count_score + 0.25 * span_score + 0.30 * error_score) * variant_penalty * crosscheck_multiplier)), 3)


def build_predicted_flight(
    trajectory: dict[str, Any],
    *,
    variant: str,
    camera_sidecar: dict[str, Any] | None = None,
    output_frame_count: int | None = None,
) -> dict[str, Any]:
    if variant not in SUPPORTED_VARIANTS:
        raise PredictedFlightError(f"unsupported predicted flight variant: {variant}")
    output = json.loads(json.dumps(trajectory, ensure_ascii=False))
    launch_frame = detect_launch_frame(trajectory)
    if launch_frame is None:
        output["predictedFlight"] = _legacy_predicted_flight({
            "status": "failed",
            "variant": variant,
            "reason": "insufficient visible points",
            "generatedAt": _utc_now(),
            "frames": [],
        })
        return output
    observation_evidence = _observed_flight_evidence(trajectory, launch_frame)
    if not observation_evidence["hasVisibleFlight"]:
        output["predictedFlight"] = _legacy_predicted_flight({
            "status": "failed",
            "variant": variant,
            "reason": "insufficient visible flight displacement",
            "launchFrame": launch_frame,
            "generatedAt": _utc_now(),
            "observationEvidence": observation_evidence,
            "frames": [],
        })
        return output
    fit_frames = _select_fit_frames(trajectory, launch_frame)
    if len(fit_frames) < MIN_REVIEW_FIT_POINTS:
        output["predictedFlight"] = _legacy_predicted_flight({
            "status": "failed",
            "variant": variant,
            "reason": "insufficient fit points for review trajectory",
            "launchFrame": launch_frame,
            "fitPointCount": len(fit_frames),
            "generatedAt": _utc_now(),
            "frames": [],
        })
        return output

    fps = _fps(trajectory)
    crosscheck_ratio = _crosscheck_agreement_ratio(fit_frames)
    try:
        if variant == "image_only":
            model = _fit_image_only(fit_frames, launch_frame, fps)
            metric_estimates: dict[str, Any] = {
                "ballSpeedPxPerSecond": _round(model["pixelVelocityAtLaunch"]["speedPxPerSecond"], 3),
                "monocularDepthSource": "not_used",
            }
            source_name = "predicted_image_only"
        else:
            model = _fit_metric_sidecar(trajectory, fit_frames, launch_frame, fps, camera_sidecar or {})
            metric_estimates = model["metricEstimates"]
            source_name = "predicted_metric_sidecar"
    except PredictedFlightError as exc:
        output["predictedFlight"] = _legacy_predicted_flight({
            "status": "failed",
            "variant": variant,
            "reason": str(exc),
            "launchFrame": launch_frame,
            "fitPointCount": len(fit_frames),
            "generatedAt": _utc_now(),
            "frames": [],
        })
        return output

    fit_indices = {int(frame["frameIndex"]) for frame in fit_frames}
    observed_by_frame = {int(frame["frameIndex"]): frame for frame in _visible_ball_frames(trajectory)}
    predicted_frames: list[dict[str, Any]] = []
    for frame_index in _output_frame_range(trajectory, output_frame_count):
        time_seconds = (frame_index - launch_frame) / fps
        if frame_index in fit_indices:
            observed = observed_by_frame[frame_index]
            frame_source = "observed"
            x = float(observed["x"])
            y = float(observed["y"])
            confidence = float(observed.get("confidence", 1.0))
        elif frame_index < launch_frame and frame_index in observed_by_frame:
            observed = observed_by_frame[frame_index]
            frame_source = "observed_prelaunch"
            x = float(observed["x"])
            y = float(observed["y"])
            confidence = float(observed.get("confidence", 1.0))
        else:
            x, y = model["predict"](time_seconds)
            frame_source = source_name
            confidence = _prediction_confidence(
                len(fit_frames),
                int(fit_frames[-1]["frameIndex"]) - int(fit_frames[0]["frameIndex"]) + 1,
                _fit_error_summary(model["reprojectionErrorsPx"])["rmsePx"],
                variant,
                crosscheck_ratio,
            )
        predicted_frames.append({
            "frameIndex": int(frame_index),
            "x": _round(x, 3),
            "y": _round(y, 3),
            "visible": 0 <= x < float(trajectory.get("frameWidth", 0) or 0) and 0 <= y < float(trajectory.get("frameHeight", 0) or 0),
            "source": frame_source,
            "confidence": confidence,
            "labelEligible": False,
        })

    fit_errors = _fit_error_summary(model["reprojectionErrorsPx"])
    fit_range = [int(fit_frames[0]["frameIndex"]), int(fit_frames[-1]["frameIndex"])]
    output["predictedFlight"] = _legacy_predicted_flight({
        "version": "1.0",
        "status": "needs_review",
        "variant": variant,
        "generatedAt": _utc_now(),
        "reviewStatus": "needs_review",
        "launchFrame": int(launch_frame),
        "fitPointCount": len(fit_frames),
        "fitFrameRange": fit_range,
        "fitTimeSpanSeconds": _round((fit_range[1] - fit_range[0]) / fps, 6),
        "inputObservedFrameCount": len(_visible_ball_frames(trajectory)),
        "observationEvidence": observation_evidence,
        "outputFrameCount": len(predicted_frames),
        "quality": {
            "reprojectionRmsePx": fit_errors["rmsePx"],
            "reprojectionP95Px": fit_errors["p95Px"],
            "reprojectionMaxPx": fit_errors["maxPx"],
            "confidence": _prediction_confidence(len(fit_frames), fit_range[1] - fit_range[0] + 1, fit_errors["rmsePx"], variant, crosscheck_ratio),
            "crossCheckAgreementRatio": _round(crosscheck_ratio, 3),
        },
        "model": {key: value for key, value in model.items() if key not in {"predict", "reprojectionErrorsPx", "metricEstimates"}},
        "metricEstimates": metric_estimates,
        "frames": predicted_frames,
    })
    return output


def _load_camera_sidecar_for_trajectory(trajectory: dict[str, Any]) -> dict[str, Any] | None:
    source_video = Path(str(trajectory.get("sourceVideo") or ""))
    sidecar_path = source_video.with_suffix(".camera.json")
    sidecar: dict[str, Any] = _read_json(sidecar_path) if sidecar_path.exists() else {}
    if _intrinsics(sidecar) is not None:
        return sidecar
    if build_camera_model_for_shot is not None and source_video.exists():
        try:
            camera_model_payload = build_camera_model_for_shot(trajectory)  # type: ignore[misc]
            camera_model = camera_model_payload.get("cameraModel")
            if isinstance(camera_model, dict):
                merged = dict(sidecar)
                merged["cameraModel"] = camera_model
                if "intrinsics" not in merged and isinstance(camera_model.get("intrinsics"), dict):
                    merged["intrinsics"] = camera_model["intrinsics"]
                return merged
        except Exception:
            return sidecar or None
    return sidecar or None


def build_predictions(
    trajectories_dir: Path | str,
    output_dir: Path | str,
    *,
    variants: Iterable[str] = SUPPORTED_VARIANTS,
    output_frame_count: int | None = None,
) -> dict[str, Any]:
    trajectories_dir = Path(trajectories_dir)
    output_dir = Path(output_dir)
    variant_list = list(variants)
    reports: list[dict[str, Any]] = []
    status_counts: Counter[str] = Counter()
    for variant in variant_list:
        if variant not in SUPPORTED_VARIANTS:
            raise PredictedFlightError(f"unsupported predicted flight variant: {variant}")
        variant_dir = output_dir / variant / "trajectories"
        variant_reports = []
        for trajectory_path in sorted(trajectories_dir.glob("*.json")):
            trajectory = _read_json(trajectory_path)
            sidecar = _load_camera_sidecar_for_trajectory(trajectory) if variant == "metric_sidecar" else None
            prediction = build_predicted_flight(
                trajectory,
                variant=variant,
                camera_sidecar=sidecar,
                output_frame_count=output_frame_count,
            )
            sample_id = _safe_name(str(prediction.get("sampleId") or trajectory_path.stem))
            output_path = variant_dir / f"{sample_id}.json"
            _write_json(output_path, prediction)
            predicted_flight = prediction.get("predictedFlight") if isinstance(prediction.get("predictedFlight"), dict) else {}
            status = str(predicted_flight.get("status") or "unknown")
            status_counts[f"{variant}:{status}"] += 1
            variant_reports.append({
                "sampleId": prediction.get("sampleId"),
                "shotId": prediction.get("shotId"),
                "status": status,
                "path": str(output_path),
                "fitPointCount": predicted_flight.get("fitPointCount"),
                "launchFrame": predicted_flight.get("launchFrame"),
            })
        report = {
            "variant": variant,
            "trajectoryCount": len(variant_reports),
            "trajectories": variant_reports,
        }
        _write_json(output_dir / variant / "prediction_report.json", report)
        reports.append(report)
    combined = {
        "version": "1.0",
        "generatedAt": _utc_now(),
        "sourceTrajectoriesDir": str(trajectories_dir),
        "outputDir": str(output_dir),
        "variants": reports,
        "summary": {
            "variants": variant_list,
            "statusCounts": dict(status_counts),
        },
    }
    _write_json(output_dir / "prediction_report.json", combined)
    return combined


def _distances(values: Iterable[Any]) -> list[float]:
    result: list[float] = []
    for value in values:
        if value is None:
            continue
        number = float(value)
        if math.isfinite(number):
            result.append(number)
    return result


def _median_p95(values: Iterable[Any]) -> dict[str, float | None]:
    series = _distances(values)
    if not series:
        return {"median": None, "p95": None}
    return {"median": round(float(median(series)), 3), "p95": round(float(np.percentile(np.array(series), 95)), 3)}


def _clubhead_agreement(trajectory: dict[str, Any]) -> dict[str, float | None]:
    tap = {
        int(frame["frameIndex"]): frame
        for frame in trajectory.get("clubheadTrack", [])
        if isinstance(frame, dict) and frame.get("visible") and frame.get("frameIndex") is not None
    }
    co = {
        int(frame["frameIndex"]): frame
        for frame in trajectory.get("clubheadCoTrackerTrack", [])
        if isinstance(frame, dict) and frame.get("visible") and frame.get("frameIndex") is not None
    }
    distances = []
    for frame_index, frame in tap.items():
        other = co.get(frame_index)
        if other is None:
            continue
        distances.append(math.hypot(float(frame["x"]) - float(other["x"]), float(frame["y"]) - float(other["y"])))
    return _median_p95(distances)


def _ocr_items_by_sample(trackman_ocr_report: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not isinstance(trackman_ocr_report, dict):
        return {}
    items = trackman_ocr_report.get("items") if isinstance(trackman_ocr_report.get("items"), list) else []
    return {str(item.get("sampleId")): item for item in items if isinstance(item, dict) and item.get("sampleId")}


def _field_value(fields: dict[str, Any], key: str) -> tuple[float, str] | None:
    value = fields.get(key)
    if not isinstance(value, dict):
        return None
    unit = str(value.get("normalizedUnit") or value.get("rawUnit") or "")
    number = value.get("normalizedValue", value.get("rawValue"))
    if number is None:
        return None
    try:
        return float(number), unit
    except (TypeError, ValueError):
        return None


def _trackman_metrics(trackman: dict[str, Any]) -> dict[str, float]:
    if not isinstance(trackman, dict):
        return {}
    metrics = trackman.get("metrics") if isinstance(trackman.get("metrics"), dict) else {}
    result: dict[str, float] = {}
    if metrics.get("ballSpeedMph") is not None:
        result["ballSpeedMph"] = float(metrics["ballSpeedMph"])
    if metrics.get("launchAngleDeg") is not None:
        result["launchAngleDeg"] = float(metrics["launchAngleDeg"])
    if metrics.get("launchDirectionDeg") is not None:
        result["launchDirectionDeg"] = float(metrics["launchDirectionDeg"])

    fields = trackman.get("correctedFields") if isinstance(trackman.get("correctedFields"), dict) else {}
    ball_speed = _field_value(fields, "ballSpeed")
    if ball_speed is not None:
        value, unit = ball_speed
        if unit in {"m/s", "mps"}:
            result["ballSpeedMph"] = value * MPS_TO_MPH
        elif unit in {"mph", "mi/h"}:
            result["ballSpeedMph"] = value
    launch_angle = _field_value(fields, "launchAngle")
    if launch_angle is not None:
        result["launchAngleDeg"] = launch_angle[0]
    launch_direction = _field_value(fields, "launchDirection")
    if launch_direction is not None:
        result["launchDirectionDeg"] = launch_direction[0]
    return result


def _trackman_comparison(
    prediction: dict[str, Any],
    ocr_by_sample: dict[str, dict[str, Any]],
    reviewed_by_sample: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    sample_id = str(prediction.get("sampleId") or "")
    reviewed = reviewed_by_sample.get(sample_id)
    if isinstance(reviewed, dict):
        trackman = reviewed
        trackman_source = "human_confirmed_review"
    else:
        trackman = prediction.get("trackman") if isinstance(prediction.get("trackman"), dict) else {}
        trackman_source = "embedded_prediction_trackman"
    usable = bool(trackman.get("metricsUsable", bool(trackman.get("metrics") or trackman.get("correctedFields"))))
    metrics = _trackman_metrics(trackman) if usable else {}
    predicted_flight = prediction.get("predictedFlight") if isinstance(prediction.get("predictedFlight"), dict) else {}
    estimates = predicted_flight.get("metricEstimates") if isinstance(predicted_flight.get("metricEstimates"), dict) else {}
    legacy_warning = "Legacy predictedFlight TrackMan comparison is debug-only; formal M2 uses video_only_3d and trackman_constrained_3d."
    if metrics:
        errors: dict[str, float | None] = {}
        for key in ("ballSpeedMph", "launchAngleDeg", "launchDirectionDeg"):
            if metrics.get(key) is None or estimates.get(key) is None:
                errors[key] = None
            else:
                errors[key] = round(float(estimates[key]) - float(metrics[key]), 3)
        return {
            "status": "compared",
            "trackmanSource": trackman_source,
            "trackmanMetrics": {key: round(value, 3) for key, value in metrics.items()},
            "predictedMetrics": {key: _round(estimates.get(key), 3) for key in ("ballSpeedMph", "launchAngleDeg", "launchDirectionDeg")},
            "errors": errors,
            "reviewOnly": True,
            "formalM2": False,
            "warning": legacy_warning,
        }
    if isinstance(reviewed, dict):
        return {
            "status": "unavailable_unconfirmed_trackman",
            "trackmanSource": "human_confirmed_review",
            "needsHumanConfirmation": reviewed.get("metricsUsable") is not True,
            "reviewOnly": True,
            "formalM2": False,
            "warning": legacy_warning,
        }
    ocr = ocr_by_sample.get(sample_id)
    if ocr is not None and bool(ocr.get("needsHumanConfirmation", True)):
        return {
            "status": "unavailable_unconfirmed_ocr",
            "ocrStatus": ocr.get("ocrStatus") or ocr.get("status"),
            "lineCount": ocr.get("lineCount"),
            "needsHumanConfirmation": True,
            "reviewOnly": True,
            "formalM2": False,
            "warning": legacy_warning,
        }
    return {"status": "unavailable_no_metrics", "reviewOnly": True, "formalM2": False, "warning": legacy_warning}


def validate_predictions(
    predictions: Iterable[dict[str, Any]],
    *,
    trackman_ocr_report: dict[str, Any] | None = None,
    trackman_reviewed_by_sample: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    ocr_by_sample = _ocr_items_by_sample(trackman_ocr_report)
    reviewed_by_sample = trackman_reviewed_by_sample or {}
    items = []
    status_counts: Counter[str] = Counter()
    legacy_review_only_count = 0
    for prediction in predictions:
        predicted_flight = prediction.get("predictedFlight") if isinstance(prediction.get("predictedFlight"), dict) else {}
        frames = prediction.get("frames") if isinstance(prediction.get("frames"), list) else []
        visible_observed = [frame for frame in frames if isinstance(frame, dict) and frame.get("visible")]
        crosscheck = _median_p95(
            (frame.get("crossCheck") or {}).get("distancePx")
            for frame in visible_observed
            if isinstance(frame.get("crossCheck"), dict)
        )
        patch_spread = _median_p95(frame.get("pointSpreadPx") for frame in prediction.get("patchFrames", []) if isinstance(frame, dict))
        comparison = _trackman_comparison(prediction, ocr_by_sample, reviewed_by_sample)
        status_counts[str(predicted_flight.get("status") or "missing")] += 1
        legacy_review_only = bool(predicted_flight.get("legacy") is True or predicted_flight.get("reviewOnly") is True)
        if legacy_review_only:
            legacy_review_only_count += 1
        items.append({
            "sampleId": prediction.get("sampleId"),
            "shotId": prediction.get("shotId"),
            "variant": predicted_flight.get("variant"),
            "status": predicted_flight.get("status"),
            "legacyReviewOnly": legacy_review_only,
            "formalM2": bool(predicted_flight.get("formalM2") is True),
            "trainingLabelRejectionReason": predicted_flight.get("trainingLabelRejectionReason"),
            "quality": {
                "observedVisibleCount": len(visible_observed),
                "fitPointCount": predicted_flight.get("fitPointCount", 0),
                "fitFrameRange": predicted_flight.get("fitFrameRange"),
                "fitTimeSpanSeconds": predicted_flight.get("fitTimeSpanSeconds"),
                "reprojectionRmsePx": (predicted_flight.get("quality") or {}).get("reprojectionRmsePx"),
                "reprojectionP95Px": (predicted_flight.get("quality") or {}).get("reprojectionP95Px"),
                "confidence": (predicted_flight.get("quality") or {}).get("confidence"),
                "ballCrossCheckDistancePx": crosscheck,
                "ballPatchSpreadPx": patch_spread,
                "clubheadAgreementPx": _clubhead_agreement(prediction),
            },
            "trackmanComparison": comparison,
        })
    return {
        "version": "1.0",
        "generatedAt": _utc_now(),
        "summary": {
            "predictionCount": len(items),
            "statusCounts": dict(status_counts),
            "legacyReviewOnlyCount": legacy_review_only_count,
            "formalM2Count": sum(1 for item in items if item.get("formalM2") is True),
        },
        "items": items,
    }


def load_prediction_files(predictions_root: Path | str, variants: Iterable[str] | None = None) -> list[dict[str, Any]]:
    root = Path(predictions_root)
    if variants is None:
        variant_dirs = [path for path in sorted(root.iterdir()) if path.is_dir() and (path / "trajectories").exists()]
    else:
        variant_dirs = [root / variant for variant in variants]
    predictions = []
    for variant_dir in variant_dirs:
        for path in sorted((variant_dir / "trajectories").glob("*.json")):
            predictions.append(_read_json(path))
    return predictions
