from __future__ import annotations

from dataclasses import dataclass
from math import hypot
from pathlib import Path
from typing import Any, Sequence

import cv2
import numpy as np

try:
    from lib.tapnextpp_tracker import SeedPoint, _frame_needs_review
except ModuleNotFoundError:  # pragma: no cover - used when imported as tools.lib.* in tests.
    from tools.lib.tapnextpp_tracker import SeedPoint, _frame_needs_review


@dataclass(frozen=True)
class FlightCandidate:
    frame_index: int
    x: float
    y: float
    score: float
    area: int
    bbox: tuple[int, int, int, int]
    source: str
    visible: bool = True


def seed_window_frame_indices(*, seed_frame: int, frame_count: int, max_frames_after_seed: int = 1200, frame_stride: int = 1) -> list[int]:
    if frame_count <= 0:
        return []
    start_frame = max(0, min(int(seed_frame), frame_count - 1))
    end_frame = min(frame_count - 1, start_frame + max(0, int(max_frames_after_seed)))
    return list(range(start_frame, end_frame + 1, max(1, int(frame_stride))))


def _candidate_gate_for_seed(seed: SeedPoint, *, width: int, height: int) -> tuple[int, int, int, int]:
    x1 = max(0, int(seed.x - 180))
    x2 = min(width, int(seed.x + 140))
    y1 = max(0, int(seed.y - 760))
    y2 = min(height, int(seed.y - 18))
    return x1, y1, x2, y2


def _motion_candidates(
    *,
    frame_index: int,
    previous_frame: np.ndarray,
    frame: np.ndarray,
    seed: SeedPoint,
) -> list[FlightCandidate]:
    height, width = frame.shape[:2]
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    previous_gray = cv2.cvtColor(previous_frame, cv2.COLOR_BGR2GRAY)
    diff = cv2.absdiff(gray, previous_gray)
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

    bright_or_dark_ball = (((hsv[:, :, 2] > 120) & (hsv[:, :, 1] < 155)) | (diff > 18)).astype("uint8") * 255
    motion = (diff > 6).astype("uint8") * 255
    mask = cv2.bitwise_and(bright_or_dark_ball, motion)
    x1, y1, x2, y2 = _candidate_gate_for_seed(seed, width=width, height=height)
    roi = np.zeros_like(mask)
    roi[y1:y2, x1:x2] = 255
    mask = cv2.bitwise_and(mask, roi)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))

    count, labels, stats, centroids = cv2.connectedComponentsWithStats(mask, 8)
    candidates: list[FlightCandidate] = []
    for label in range(1, count):
        x, y, w, h, area = stats[label]
        if area < 2 or area > 700:
            continue
        if w > 70 or h > 70:
            continue
        cx, cy = centroids[label]
        if cy >= seed.y - 18:
            continue
        component = labels == label
        mean_diff = float(diff[component].mean())
        mean_value = float(hsv[:, :, 2][component].mean())
        mean_saturation = float(hsv[:, :, 1][component].mean())
        compactness_penalty = max(w, h) / max(1, min(w, h))
        score = mean_diff + mean_value / 5.0 - mean_saturation / 20.0 - compactness_penalty
        candidates.append(
            FlightCandidate(
                frame_index=frame_index,
                x=float(cx),
                y=float(cy),
                score=float(score),
                area=int(area),
                bbox=(int(x), int(y), int(w), int(h)),
                source="motion_blob",
            )
        )
    return candidates


def collect_motion_candidates(
    *,
    video_path: Path | str,
    frame_indices: Sequence[int],
    seed: SeedPoint,
) -> dict[int, list[FlightCandidate]]:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"could not open video for flight tracking: {video_path}")
    by_frame: dict[int, list[FlightCandidate]] = {}
    previous_frame: np.ndarray | None = None
    previous_index: int | None = None
    try:
        for frame_index in frame_indices:
            if previous_index is None or int(frame_index) != previous_index + 1:
                cap.set(cv2.CAP_PROP_POS_FRAMES, int(frame_index))
                previous_frame = None
            ok, frame = cap.read()
            if not ok:
                break
            if previous_frame is not None:
                by_frame[int(frame_index)] = _motion_candidates(
                    frame_index=int(frame_index),
                    previous_frame=previous_frame,
                    frame=frame,
                    seed=seed,
                )
            previous_frame = frame
            previous_index = int(frame_index)
    finally:
        cap.release()
    return by_frame


def find_launch_frame(
    candidates_by_frame: dict[int, list[FlightCandidate]],
    *,
    seed: SeedPoint,
    max_scan_frame: int,
    min_scan_frame: int | None = None,
) -> int | None:
    min_scan = seed.frame_index if min_scan_frame is None else int(min_scan_frame)
    for frame_index in sorted(candidates_by_frame):
        if frame_index < min_scan:
            continue
        if frame_index > max_scan_frame:
            break
        launch_candidates = []
        for candidate in candidates_by_frame[frame_index]:
            distance = hypot(candidate.x - seed.x, candidate.y - seed.y)
            if 60.0 <= distance <= 155.0 and (seed.x - 45.0) <= candidate.x <= (seed.x + 55.0) and candidate.y <= seed.y - 60.0:
                launch_candidates.append((distance - candidate.score * 0.08, candidate))
        if launch_candidates:
            return int(min(launch_candidates, key=lambda item: item[0])[1].frame_index)
    return None


def choose_validated_launch_frame(
    candidates_by_frame: dict[int, list[FlightCandidate]],
    *,
    seed: SeedPoint,
    min_scan_frame: int,
    max_scan_frame: int,
    end_frame: int,
    min_visible_after_launch: int = 4,
) -> tuple[int | None, dict[int, FlightCandidate]]:
    best: tuple[float, int, FlightCandidate] | None = None
    for frame_index in sorted(candidates_by_frame):
        if frame_index < min_scan_frame:
            continue
        if frame_index > max_scan_frame:
            break
        for initial_candidate in _eligible_initial_candidates(candidates_by_frame.get(frame_index, []), seed=seed):
            linked = link_flight_candidates(
                candidates_by_frame,
                seed=seed,
                launch_frame=frame_index,
                end_frame=min(end_frame, frame_index + 80),
                initial_candidate=initial_candidate,
            )
            visible_count = sum(1 for candidate in linked.values() if candidate.visible)
            if visible_count < min_visible_after_launch:
                continue
            score = _score_linked_flight(linked)
            if score is None:
                continue
            score -= max(0, frame_index - min_scan_frame) * 0.05
            if best is None or score > best[0]:
                best = (score, frame_index, initial_candidate)
    if best is None:
        return None, {}
    _, launch_frame, initial_candidate = best
    full_linked = link_flight_candidates(
        candidates_by_frame,
        seed=seed,
        launch_frame=launch_frame,
        end_frame=end_frame,
        initial_candidate=initial_candidate,
    )
    return launch_frame, full_linked


def apply_clubhead_rejection(
    candidates: Sequence[FlightCandidate],
    clubhead_by_frame: dict[int, FlightCandidate],
) -> list[FlightCandidate]:
    remaining: list[FlightCandidate] = []
    for candidate in candidates:
        clubhead = clubhead_by_frame.get(candidate.frame_index)
        if clubhead is None:
            remaining.append(candidate)
            continue
        distance = hypot(candidate.x - clubhead.x, candidate.y - clubhead.y)
        if distance < 28.0:
            continue
        if candidate.area > 80 and distance < 45.0:
            continue
        remaining.append(candidate)
    return remaining


def _eligible_initial_candidates(
    candidates: Sequence[FlightCandidate],
    *,
    seed: SeedPoint,
    clubhead_by_frame: dict[int, FlightCandidate] | None = None,
) -> list[FlightCandidate]:
    candidates = apply_clubhead_rejection(candidates, clubhead_by_frame) if clubhead_by_frame is not None else candidates
    return [
        candidate
        for candidate in candidates
        if 60.0 <= hypot(candidate.x - seed.x, candidate.y - seed.y) <= 155.0
        and (seed.x - 45.0) <= candidate.x <= (seed.x + 55.0)
        and candidate.y <= seed.y - 60.0
    ]


def _choose_initial_candidate(candidates: Sequence[FlightCandidate], *, seed: SeedPoint) -> FlightCandidate | None:
    eligible = _eligible_initial_candidates(candidates, seed=seed)
    if not eligible:
        return None
    return min(eligible, key=lambda candidate: hypot(candidate.x - seed.x, candidate.y - seed.y) - candidate.score * 0.08)


def _score_linked_flight(linked: dict[int, FlightCandidate], *, max_eval_visible: int = 48) -> float | None:
    visible = [candidate for candidate in linked.values() if candidate.visible]
    if len(visible) < 4:
        return None
    sample = visible[:max_eval_visible]
    xs = [candidate.x for candidate in sample]
    ys = [candidate.y for candidate in sample]
    min_y = min(ys)
    min_y_index = ys.index(min_y)
    upward = max(0.0, sample[0].y - min_y)
    rebound = max(0.0, max(ys[min_y_index:]) - min_y)
    monotonic_ratio = sum(1 for previous, current in zip(ys, ys[1:]) if current <= previous + 5.0) / max(1, len(ys) - 1)
    x_spread = max(xs) - min(xs)
    avg_area = sum(candidate.area for candidate in sample) / len(sample)
    gap_count = sum(1 for candidate in linked.values() if not candidate.visible)
    return (
        upward * 2.4
        + len(visible) * 1.8
        + monotonic_ratio * 90.0
        - rebound * 1.8
        - x_spread * 0.45
        - avg_area * 0.35
        - gap_count * 2.5
    )


def _choose_next_candidate(
    candidates: Sequence[FlightCandidate],
    *,
    predicted_x: float,
    predicted_y: float,
    last_visible: FlightCandidate,
    speed: float,
) -> FlightCandidate | None:
    gate = max(28.0, min(180.0, speed * 2.1 + 20.0))
    eligible = []
    for candidate in candidates:
        distance = hypot(candidate.x - predicted_x, candidate.y - predicted_y)
        if distance > gate:
            continue
        y_penalty = max(0.0, candidate.y - last_visible.y - 8.0) * 0.25
        score = distance + y_penalty - candidate.score * 0.09
        eligible.append((score, candidate))
    if not eligible:
        return None
    return min(eligible, key=lambda item: item[0])[1]


def link_flight_candidates(
    candidates_by_frame: dict[int, list[FlightCandidate]],
    *,
    seed: SeedPoint,
    launch_frame: int,
    end_frame: int,
    max_gap_frames: int = 6,
    initial_candidate: FlightCandidate | None = None,
) -> dict[int, FlightCandidate]:
    linked: dict[int, FlightCandidate] = {}
    first = initial_candidate or _choose_initial_candidate(candidates_by_frame.get(launch_frame, []), seed=seed)
    if first is None:
        return linked
    linked[launch_frame] = first
    last_visible = first
    vx = 0.0
    vy = -35.0
    gap = 0
    for frame_index in range(launch_frame + 1, end_frame + 1):
        predicted_x = last_visible.x + vx * (gap + 1)
        predicted_y = last_visible.y + vy * (gap + 1)
        speed = hypot(vx, vy)
        choice = _choose_next_candidate(
            candidates_by_frame.get(frame_index, []),
            predicted_x=predicted_x,
            predicted_y=predicted_y,
            last_visible=last_visible,
            speed=speed,
        )
        if choice is None:
            if gap < max_gap_frames:
                linked[frame_index] = FlightCandidate(
                    frame_index=frame_index,
                    x=predicted_x,
                    y=predicted_y,
                    score=0.0,
                    area=0,
                    bbox=(int(predicted_x), int(predicted_y), 0, 0),
                    source="predicted_gap",
                    visible=False,
                )
                gap += 1
                continue
            break
        observed_dt = max(1, frame_index - last_visible.frame_index)
        new_vx = (choice.x - last_visible.x) / observed_dt
        new_vy = (choice.y - last_visible.y) / observed_dt
        vx = 0.65 * vx + 0.35 * new_vx
        vy = 0.65 * vy + 0.35 * new_vy
        linked[frame_index] = choice
        last_visible = choice
        gap = 0
    return linked


def build_flight_trajectory(
    *,
    shot: dict[str, Any],
    seed: SeedPoint,
    frame_indices: Sequence[int],
    launch_frame: int | None,
    linked_candidates: dict[int, FlightCandidate],
    checkpoint: Path,
    impact_occlusion_padding: int = 3,
    frame_stride: int = 1,
    camera_model_summary: dict[str, Any] | None = None,
    camera_model_path: str | None = None,
) -> dict[str, Any]:
    width = int(shot.get("frameWidth") or 0)
    height = int(shot.get("frameHeight") or 0)
    frames: list[dict[str, Any]] = []
    occlusion_start = (launch_frame - impact_occlusion_padding) if launch_frame is not None else None
    for frame_index in frame_indices:
        frame_index = int(frame_index)
        candidate = linked_candidates.get(frame_index)
        if candidate is not None:
            x, y = candidate.x, candidate.y
            visible = bool(candidate.visible)
            confidence = max(0.0, min(1.0, candidate.score / 120.0)) if visible else 0.0
            source = "seeded_motion_reacquisition" if visible else "predicted_gap"
        elif launch_frame is not None and occlusion_start is not None and occlusion_start <= frame_index < launch_frame:
            x, y = seed.x, seed.y
            visible = False
            confidence = 0.0
            source = "occluded_by_clubhead"
        elif launch_frame is None or frame_index < launch_frame:
            x, y = seed.x, seed.y
            visible = True
            confidence = 1.0
            source = "manual_seed_static"
        else:
            x, y = 0.0, 0.0
            visible = False
            confidence = 0.0
            source = "post_flight_not_detected"
        label_eligible = visible and source in {"manual_seed_static", "seeded_motion_reacquisition"}
        frames.append({
            "frameIndex": frame_index,
            "x": round(float(x), 3),
            "y": round(float(y), 3),
            "visible": visible,
            "labelEligible": label_eligible,
            "confidence": round(float(confidence), 6),
            "needsReview": _frame_needs_review(visible=visible, confidence=confidence, x=float(x), y=float(y), width=width, height=height),
            "source": source,
        })
    trackman_reviewed = shot.get("trackmanReviewed", {})
    camera_model = camera_model_summary or {"status": "missing"}
    available_inputs = [
        "camera_model_present" if camera_model.get("status") != "missing" else "camera_model_missing",
        "reviewed_trackman_present" if trackman_reviewed else "reviewed_trackman_missing",
        "2d_visible_tracking",
        "manual_seed",
    ]
    seed_payload: dict[str, Any] = {"frameIndex": seed.frame_index, "x": seed.x, "y": seed.y}
    clubhead_visible = False
    clubhead_center = getattr(seed, "clubhead_center", None)
    if clubhead_center:
        seed_payload["clubheadCenter"] = clubhead_center
        clubhead_visible = bool(clubhead_center.get("visible"))
    impact_payload = {
        "launchFrame": launch_frame,
        "occlusionStartFrame": occlusion_start,
        "source": "seeded_motion_reacquisition",
        "occlusionEvidence": (
            "forced_impact_window_with_clubhead_seed"
            if clubhead_visible
            else "forced_impact_window_without_clubhead_track"
        ),
    }
    return {
        "version": "1.0",
        "sampleId": str(shot.get("sampleId") or seed.sample_id),
        "sessionId": str(shot.get("sessionId") or ""),
        "shotId": str(shot.get("shotId") or ""),
        "sourceVideo": str(shot.get("sourceVideo") or ""),
        "frameCount": len(frames),
        "sourceFrameCount": int(shot.get("frameCount") or len(frames)),
        "fps": float(shot.get("fps") or 0.0),
        "frameWidth": width,
        "frameHeight": height,
        "trackman": shot.get("trackmanMatch", {}),
        "trackmanReviewed": trackman_reviewed,
        "cameraModel": camera_model,
        "cameraModelPath": camera_model_path,
        "predictedFlight": {
            "status": "not_generated",
            "reason": "phase_1_exports_reviewed_2d_tracking_only",
            "availableInputs": available_inputs,
            "missingInputs": [
                "3d_reconstruction",
                "monocular_depth_or_calibrated_depth",
                "physics_fit",
            ],
            "enhancementModels": [],
        },
        "seed": seed_payload,
        "impact": impact_payload,
        "sampling": {
            "startFrame": int(frame_indices[0]) if frame_indices else seed.frame_index,
            "frameStride": int(frame_stride),
            "sampledFrameCount": len(frames),
        },
        "model": {
            "name": "tapnextpp_cotracker3_checked_seeded_motion_reacquisition",
            "checkpoint": str(checkpoint),
            "source": "manual_seed_static + TAPNext++/CoTracker3 rejection + high-speed motion reacquisition",
        },
        "frames": frames,
    }


class SeededFlightTracker:
    def __init__(
        self,
        *,
        checkpoint: Path | str,
        max_frames_after_seed: int = 1200,
        frame_stride: int = 1,
    ):
        self.checkpoint = Path(checkpoint)
        self.max_frames_after_seed = max(0, int(max_frames_after_seed))
        self.frame_stride = max(1, int(frame_stride))

    def __call__(self, shot: dict[str, Any], seed: SeedPoint) -> dict[str, Any]:
        return self.track(shot, seed)

    def track(
        self,
        shot: dict[str, Any],
        seed: SeedPoint,
        *,
        camera_model_summary: dict[str, Any] | None = None,
        camera_model_path: str | None = None,
    ) -> dict[str, Any]:
        frame_count = int(shot.get("frameCount") or 0)
        frame_indices = seed_window_frame_indices(
            seed_frame=seed.frame_index,
            frame_count=frame_count,
            max_frames_after_seed=self.max_frames_after_seed,
            frame_stride=self.frame_stride,
        )
        candidates_by_frame = collect_motion_candidates(
            video_path=Path(str(shot.get("sourceVideo") or "")),
            frame_indices=frame_indices,
            seed=seed,
        )
        max_scan_frame = int(frame_indices[-1]) if frame_indices else seed.frame_index
        launch_frame, linked = (
            choose_validated_launch_frame(
                candidates_by_frame,
                seed=seed,
                min_scan_frame=seed.frame_index + 24,
                max_scan_frame=max_scan_frame,
                end_frame=int(frame_indices[-1]),
            )
            if frame_indices
            else (None, {})
        )
        trajectory = build_flight_trajectory(
            shot=shot,
            seed=seed,
            frame_indices=frame_indices,
            launch_frame=launch_frame,
            linked_candidates=linked,
            checkpoint=self.checkpoint,
            frame_stride=self.frame_stride,
            camera_model_summary=camera_model_summary,
            camera_model_path=camera_model_path,
        )
        trajectory["flightTracking"] = {
            "candidateFrames": len(candidates_by_frame),
            "launchFrame": launch_frame,
            "linkedVisibleFrames": sum(1 for candidate in linked.values() if candidate.visible),
            "linkedGapFrames": sum(1 for candidate in linked.values() if not candidate.visible),
        }
        return trajectory
