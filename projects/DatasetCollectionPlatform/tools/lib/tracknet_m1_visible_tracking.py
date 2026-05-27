from __future__ import annotations

from datetime import datetime, timezone
from math import hypot
from typing import Any


CLUBHEAD_IMPACT_RADIUS_PX = 42.0


def _rounded_float(value: Any) -> float:
    return round(float(value), 3)


def _confidence(frame: dict[str, Any], visible: bool) -> float:
    if frame.get("confidence") is None:
        return 1.0 if visible else 0.0
    return float(frame["confidence"])


def _normalise_ball_frame(frame: dict[str, Any]) -> dict[str, Any]:
    visible = bool(frame.get("visible", False))
    normalised = dict(frame)
    normalised["frameIndex"] = int(frame["frameIndex"])
    if frame.get("x") is not None:
        normalised["x"] = _rounded_float(frame["x"])
    else:
        normalised.pop("x", None)
    if frame.get("y") is not None:
        normalised["y"] = _rounded_float(frame["y"])
    else:
        normalised.pop("y", None)
    normalised["visible"] = visible
    normalised["confidence"] = _confidence(frame, visible)
    normalised["labelEligible"] = False
    if "source" not in normalised:
        normalised["source"] = "observed_ball_point"
    return normalised


def _normalise_clubhead_frame(frame: dict[str, Any]) -> dict[str, Any]:
    visible = bool(frame.get("visible", True))
    normalised = dict(frame)
    normalised["frameIndex"] = int(frame["frameIndex"])
    if visible and frame.get("x") is not None:
        normalised["x"] = _rounded_float(frame["x"])
    else:
        normalised.pop("x", None)
    if visible and frame.get("y") is not None:
        normalised["y"] = _rounded_float(frame["y"])
    else:
        normalised.pop("y", None)
    normalised["visible"] = visible
    normalised["confidence"] = _confidence(frame, visible)
    normalised["labelEligible"] = False
    if "source" not in normalised:
        normalised["source"] = "clubhead_track"
    return normalised


def _normalise_seed_point(point: dict[str, Any]) -> dict[str, Any]:
    normalised = {
        "frameIndex": int(point["frameIndex"]),
        "x": _rounded_float(point["x"]),
        "y": _rounded_float(point["y"]),
    }
    if "visible" in point:
        normalised["visible"] = bool(point["visible"])
    return normalised


def _normalise_seed(ball_trajectory: dict[str, Any]) -> dict[str, Any]:
    seed = ball_trajectory.get("seed")
    if isinstance(seed, dict):
        if isinstance(seed.get("ballCenter"), dict):
            normalised = {"ballCenter": _normalise_seed_point(seed["ballCenter"])}
            if isinstance(seed.get("clubheadCenter"), dict):
                normalised["clubheadCenter"] = _normalise_seed_point(seed["clubheadCenter"])
            return normalised
        if {"frameIndex", "x", "y"}.issubset(seed):
            return {"ballCenter": _normalise_seed_point(seed)}
    for frame in ball_trajectory.get("frames", []):
        if isinstance(frame, dict) and frame.get("source") == "manual_seed_static":
            return {"ballCenter": _normalise_seed_point(frame)}
    raise ValueError("ball trajectory must include seed.ballCenter, a flat seed, or a manual_seed_static frame")


def _ball_seed_center(seed: dict[str, Any]) -> dict[str, Any]:
    ball_center = seed.get("ballCenter") if isinstance(seed.get("ballCenter"), dict) else seed
    return ball_center


def _impact_window(ball_trajectory: dict[str, Any]) -> dict[str, int | None]:
    impact = ball_trajectory.get("impact") if isinstance(ball_trajectory.get("impact"), dict) else {}
    launch_frame = impact.get("launchFrame")
    occlusion_start = impact.get("occlusionStartFrame")
    return {
        "startFrame": int(occlusion_start) if occlusion_start is not None else None,
        "launchFrame": int(launch_frame) if launch_frame is not None else None,
    }


def _clubhead_frames(clubhead_trajectory: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(clubhead_trajectory, dict):
        return []
    frames = clubhead_trajectory.get("clubheadTrack")
    if not isinstance(frames, list):
        return []
    return sorted(
        (_normalise_clubhead_frame(frame) for frame in frames if isinstance(frame, dict)),
        key=lambda frame: frame["frameIndex"],
    )


def _clip_clubhead_track_to_impact(
    clubhead_frames: list[dict[str, Any]],
    *,
    seed: dict[str, Any],
    launch_frame: int | None,
) -> tuple[list[dict[str, Any]], bool]:
    if not clubhead_frames:
        return [], False

    stop_frame: int | None = None
    for frame in clubhead_frames:
        if not frame.get("visible", True):
            continue
        if frame.get("x") is None or frame.get("y") is None:
            continue
        ball_seed = _ball_seed_center(seed)
        distance = hypot(float(frame["x"]) - float(ball_seed["x"]), float(frame["y"]) - float(ball_seed["y"]))
        if distance <= CLUBHEAD_IMPACT_RADIUS_PX:
            stop_frame = int(frame["frameIndex"])
            break
    if stop_frame is None:
        stop_frame = launch_frame
    if stop_frame is None:
        return [], False
    return [frame for frame in clubhead_frames if int(frame["frameIndex"]) <= int(stop_frame)], True


def _ball_raw_frames(ball_trajectory: dict[str, Any]) -> list[dict[str, Any]]:
    frames = ball_trajectory.get("frames")
    if not isinstance(frames, list):
        frames = ball_trajectory.get("ballRawObservedFrames", [])
    if not isinstance(frames, list):
        return []
    return sorted(
        (_normalise_ball_frame(frame) for frame in frames if isinstance(frame, dict)),
        key=lambda frame: frame["frameIndex"],
    )


def _smooth_visible_frames(raw_frames: list[dict[str, Any]], *, min_reliable_confidence: float) -> list[dict[str, Any]]:
    smooth_frames: list[dict[str, Any]] = []
    for frame in raw_frames:
        if not frame.get("visible"):
            continue
        if frame.get("source") == "manual_seed_static":
            continue
        if frame.get("x") is None or frame.get("y") is None:
            continue
        if float(frame.get("confidence", 0.0)) < float(min_reliable_confidence):
            continue
        smooth_frames.append(
            {
                "frameIndex": int(frame["frameIndex"]),
                "x": _rounded_float(frame["x"]),
                "y": _rounded_float(frame["y"]),
                "visible": True,
                "confidence": float(frame["confidence"]),
                "source": "filtered_visible_observation",
                "labelEligible": False,
            }
        )
    return smooth_frames


def _qc(
    clubhead_track_to_impact: list[dict[str, Any]],
    smooth_visible_frames: list[dict[str, Any]],
    *,
    raw_frames: list[dict[str, Any]],
    impact_window: dict[str, int | None],
    clubhead_clipped_to_impact: bool,
    last_reliable_frame: int | None,
    min_reliable_confidence: float,
) -> dict[str, Any]:
    issues: list[str] = []
    if impact_window.get("launchFrame") is None:
        issues.append("missing_launch_frame")
    if impact_window.get("startFrame") is None:
        issues.append("missing_occlusion_start_frame")
    if not clubhead_track_to_impact:
        issues.append("missing_clubhead_track_to_impact")
    if not clubhead_clipped_to_impact:
        issues.append("unclipped_clubhead_track_to_impact")
    if len(smooth_visible_frames) < 12:
        issues.append("insufficient_smooth_visible_frames")
    if last_reliable_frame is not None:
        has_low_confidence_tail = any(
            frame.get("visible") is True
            and int(frame["frameIndex"]) > int(last_reliable_frame)
            and float(frame.get("confidence", 0.0)) < float(min_reliable_confidence)
            for frame in raw_frames
        )
        if has_low_confidence_tail:
            issues.append("raw_observation_after_last_reliable_low_confidence")
    if issues:
        return {"status": "needs_review", "issues": issues, "needsHumanReview": True}
    return {"status": "ok", "issues": [], "needsHumanReview": False}


def _generated_at() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _training_label_policy() -> dict[str, Any]:
    return {
        "automaticFramesLabelEligible": False,
        "summary": (
            "Automatic raw and filtered visible points are prelabels/evidence only; "
            "they are not TrackNet training truth until manual review and acceptance."
        ),
    }


def build_visible_tracking_artifact(
    ball_trajectory: dict,
    clubhead_trajectory: dict | None = None,
    *,
    min_reliable_confidence: float = 0.35,
) -> dict:
    seed = _normalise_seed(ball_trajectory)
    impact_window = _impact_window(ball_trajectory)
    raw_frames = _ball_raw_frames(ball_trajectory)
    smooth_frames = _smooth_visible_frames(raw_frames, min_reliable_confidence=min_reliable_confidence)
    clubhead_track_to_impact, clubhead_clipped_to_impact = _clip_clubhead_track_to_impact(
        _clubhead_frames(clubhead_trajectory),
        seed=seed,
        launch_frame=impact_window["launchFrame"],
    )
    last_reliable_frame = smooth_frames[-1]["frameIndex"] if smooth_frames else None

    artifact = {
        "version": "1.0",
        "stage": "m1_visible_tracking",
        "generatedAt": _generated_at(),
        "sampleId": ball_trajectory.get("sampleId"),
        "shotId": ball_trajectory.get("shotId"),
        "sessionId": ball_trajectory.get("sessionId"),
        "sourceVideo": ball_trajectory.get("sourceVideo"),
        "fps": ball_trajectory.get("fps"),
        "frameWidth": ball_trajectory.get("frameWidth"),
        "frameHeight": ball_trajectory.get("frameHeight"),
        "trainingLabelPolicy": _training_label_policy(),
        "seed": seed,
        "provenance": {
            "sourceStage": "m1_visible_tracking",
            "inputSampleId": ball_trajectory.get("sampleId"),
            "inputHasClubheadTrajectory": isinstance(clubhead_trajectory, dict) and bool(clubhead_trajectory),
            "minReliableConfidence": float(min_reliable_confidence),
        },
        "clubheadTrackToImpact": clubhead_track_to_impact,
        "ballRawObservedFrames": raw_frames,
        "ballSmoothVisibleFrames": smooth_frames,
        "curveType": "filtered_observed_points",
        "impactWindow": impact_window,
        "launchFrame": impact_window["launchFrame"],
        "lastReliableFrame": last_reliable_frame,
    }
    artifact["qc"] = _qc(
        clubhead_track_to_impact,
        smooth_frames,
        raw_frames=raw_frames,
        impact_window=impact_window,
        clubhead_clipped_to_impact=clubhead_clipped_to_impact,
        last_reliable_frame=last_reliable_frame,
        min_reliable_confidence=min_reliable_confidence,
    )
    return artifact
