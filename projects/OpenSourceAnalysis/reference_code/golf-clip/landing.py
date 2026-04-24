"""Landing point estimator for golf ball trajectory.

Estimates where the ball lands or exits the frame using multiple methods:
1. Audio-based: Detect the "thud" sound when ball lands
2. Frame exit: Detect when ball leaves the visible frame
3. Physics-based: Calculate landing from launch parameters
"""

import logging
import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from backend.detection.trajectory_physics import LaunchParameters

logger = logging.getLogger(__name__)


@dataclass
class LandingEstimate:
    """Estimated landing point and method used."""

    timestamp: float  # When ball lands (seconds from strike)
    position: Tuple[float, float]  # Screen position (normalized 0-1)
    confidence: float  # 0-1 confidence in estimate
    method: str  # "audio", "frame_exit", or "physics"
    frame_exit_edge: Optional[str] = None  # "top", "left", "right" if method=frame_exit


class LandingEstimator:
    """Estimate ball landing point using multiple methods."""

    # Gravity constant calibrated for pixel-space trajectories
    # This matches the value used in trajectory_physics.py
    GRAVITY_PIXELS_PER_S2 = 500.0

    # Minimum time after strike before looking for landing (ball still in air)
    MIN_FLIGHT_TIME = 1.5

    # Audio detection parameters
    # Landing sounds have lower frequency than strikes
    LANDING_CENTROID_LOW = 800  # Hz
    LANDING_CENTROID_HIGH = 2500  # Hz
    STRIKE_CENTROID_CENTER = 3500  # Hz (for comparison)

    def estimate_from_audio(
        self,
        audio_path: str,
        strike_time: float,
        max_flight_time: float = 6.0,
    ) -> Optional[LandingEstimate]:
        """Detect landing thud in audio track.

        Look for a transient sound 2-6 seconds after strike.
        Landing thuds are typically lower frequency than strikes.

        Args:
            audio_path: Path to audio or video file
            strike_time: When the ball was struck (seconds)
            max_flight_time: Maximum flight duration to search (seconds)

        Returns:
            LandingEstimate if thud detected, None otherwise
        """
        try:
            import librosa
        except ImportError:
            logger.warning("librosa not available for audio landing detection")
            return None

        try:
            # Load audio starting from after the strike
            search_start = strike_time + self.MIN_FLIGHT_TIME
            search_end = strike_time + max_flight_time

            # Load the audio segment
            y, sr = librosa.load(
                audio_path,
                sr=22050,
                offset=search_start,
                duration=max_flight_time - self.MIN_FLIGHT_TIME,
            )

            if len(y) == 0:
                logger.debug("No audio data in landing search window")
                return None

            # Compute onset strength (for detecting transients)
            onset_env = librosa.onset.onset_strength(y=y, sr=sr)

            # Find onset peaks
            onset_frames = librosa.onset.onset_detect(
                y=y, sr=sr, onset_envelope=onset_env, backtrack=False
            )

            if len(onset_frames) == 0:
                logger.debug("No audio onsets found in landing window")
                return None

            # Analyze each onset to find landing-like sounds
            best_landing = None
            best_score = 0.0

            hop_length = 512  # librosa default
            frame_times = librosa.frames_to_time(onset_frames, sr=sr, hop_length=hop_length)

            for i, (frame, rel_time) in enumerate(zip(onset_frames, frame_times)):
                # Get audio segment around this onset
                start_sample = max(0, int((rel_time - 0.05) * sr))
                end_sample = min(len(y), int((rel_time + 0.1) * sr))
                segment = y[start_sample:end_sample]

                if len(segment) < sr * 0.05:
                    continue

                # Compute spectral centroid for this segment
                centroid = librosa.feature.spectral_centroid(y=segment, sr=sr)
                mean_centroid = np.mean(centroid)

                # Compute onset strength at this point
                strength = onset_env[frame] if frame < len(onset_env) else 0

                # Score this onset as a potential landing
                # Landing sounds should have:
                # - Lower centroid than strikes (800-2500 Hz vs 2500-4500 Hz)
                # - Moderate strength (not as sharp as strike)

                # Centroid score: higher if in landing range
                if self.LANDING_CENTROID_LOW <= mean_centroid <= self.LANDING_CENTROID_HIGH:
                    centroid_score = 1.0
                elif mean_centroid < self.LANDING_CENTROID_LOW:
                    centroid_score = 0.5  # Very low might be noise
                elif mean_centroid <= self.STRIKE_CENTROID_CENTER:
                    # Between landing and strike range
                    centroid_score = 0.7
                else:
                    # Too high, more like a strike
                    centroid_score = 0.2

                # Strength score: moderate is best for landing
                if strength > np.mean(onset_env) * 0.5:
                    strength_score = min(1.0, strength / (np.max(onset_env) + 1e-6))
                else:
                    strength_score = 0.3

                # Combined score
                score = centroid_score * 0.6 + strength_score * 0.4

                if score > best_score:
                    best_score = score
                    absolute_time = search_start + rel_time - strike_time
                    best_landing = LandingEstimate(
                        timestamp=absolute_time,
                        position=(0.5, 0.9),  # Approximate ground position
                        confidence=min(0.85, score),
                        method="audio",
                    )

            if best_landing and best_score > 0.5:
                logger.info(
                    f"Audio landing detected at t={best_landing.timestamp:.2f}s "
                    f"(confidence={best_landing.confidence:.2f})"
                )
                return best_landing

            return None

        except Exception as e:
            logger.warning(f"Audio landing detection failed: {e}")
            return None

    def estimate_from_trajectory(
        self,
        trajectory_2d: List[Tuple[float, float]],
        timestamps: List[float],
    ) -> Optional[LandingEstimate]:
        """Estimate landing from trajectory leaving frame or hitting ground.

        Args:
            trajectory_2d: 2D screen coordinates (normalized 0-1)
            timestamps: Timestamp for each point (relative to strike)

        Returns:
            LandingEstimate with frame_exit info if applicable
        """
        if not trajectory_2d or not timestamps:
            return None

        if len(trajectory_2d) != len(timestamps):
            logger.warning("Trajectory and timestamps length mismatch")
            return None

        # Check each point for frame exit
        for i, ((x, y), t) in enumerate(zip(trajectory_2d, timestamps)):
            # Left edge - ball going left (draw for RH golfer)
            if x < 0.02:
                logger.info(f"Ball exits left edge at t={t:.2f}s")
                return LandingEstimate(
                    timestamp=t,
                    position=(0.0, y),
                    confidence=0.7,
                    method="frame_exit",
                    frame_exit_edge="left",
                )

            # Right edge - ball going right (fade for RH golfer)
            if x > 0.98:
                logger.info(f"Ball exits right edge at t={t:.2f}s")
                return LandingEstimate(
                    timestamp=t,
                    position=(1.0, y),
                    confidence=0.7,
                    method="frame_exit",
                    frame_exit_edge="right",
                )

            # Top edge - ball going into distance (toward target)
            # This is the most common case for DTL camera angle
            if y < 0.05:
                logger.info(f"Ball exits top edge at t={t:.2f}s")
                return LandingEstimate(
                    timestamp=t,
                    position=(x, 0.0),
                    confidence=0.8,
                    method="frame_exit",
                    frame_exit_edge="top",
                )

            # Ground level - ball has landed (y approaching bottom of frame)
            # In normalized coords, y=1.0 is bottom, but typical ground level
            # for a golfer is around y=0.85-0.95
            if i > 0 and y > 0.85:
                # Check if ball is descending
                prev_y = trajectory_2d[i - 1][1]
                if y > prev_y:  # y increasing means going down in screen coords
                    # Ball is descending and near ground level
                    logger.info(f"Ball lands at ground level t={t:.2f}s")
                    return LandingEstimate(
                        timestamp=t,
                        position=(x, y),
                        confidence=0.75,
                        method="frame_exit",
                        frame_exit_edge=None,  # Not frame exit, actual landing
                    )

        # If trajectory doesn't exit frame, use the last point
        if trajectory_2d:
            last_x, last_y = trajectory_2d[-1]
            last_t = timestamps[-1]
            logger.info(f"Using trajectory endpoint as landing: t={last_t:.2f}s")
            return LandingEstimate(
                timestamp=last_t,
                position=(last_x, last_y),
                confidence=0.5,
                method="frame_exit",
                frame_exit_edge=None,
            )

        return None

    def estimate_from_physics(
        self,
        launch_angle_deg: float,
        initial_speed: float,
    ) -> LandingEstimate:
        """Estimate landing purely from physics.

        Uses projectile motion equations to estimate flight time
        and landing distance.

        Args:
            launch_angle_deg: Vertical launch angle in degrees
            initial_speed: Initial ball speed in pixels/second

        Returns:
            LandingEstimate with physics-based prediction
        """
        # Convert angle to radians
        launch_angle_rad = math.radians(launch_angle_deg)

        # Vertical component of velocity
        v_y = initial_speed * math.sin(launch_angle_rad)

        # Flight time using projectile motion: t_land = 2 * v_y / g
        # This is when the ball returns to the same height it started
        if v_y > 0 and self.GRAVITY_PIXELS_PER_S2 > 0:
            flight_time = 2.0 * v_y / self.GRAVITY_PIXELS_PER_S2
        else:
            # Fallback for edge cases
            flight_time = 3.0

        # Clamp to reasonable golf shot durations
        # Driver: 4-6s, Iron: 3-5s, Wedge: 2-4s
        flight_time = max(2.0, min(6.0, flight_time))

        # Estimate landing position
        # For DTL camera, ball travels "into" the frame (toward top)
        # Higher launch = more distance = closer to vanishing point
        # Typical landing is around y=0.3-0.5 for well-struck shots
        # that stay in frame, or y < 0.1 for shots that exit top

        # Estimate based on flight time (longer flight = farther = higher on screen)
        if flight_time > 4.0:
            # Long shot, likely exits top of frame
            landing_y = 0.1
            confidence = 0.5
        elif flight_time > 3.0:
            # Medium shot
            landing_y = 0.3
            confidence = 0.55
        else:
            # Short shot, lands more visibly
            landing_y = 0.5
            confidence = 0.6

        # X position typically stays near center for straight shots
        landing_x = 0.5

        logger.info(
            f"Physics landing estimate: t={flight_time:.2f}s at ({landing_x:.2f}, {landing_y:.2f})"
        )

        return LandingEstimate(
            timestamp=flight_time,
            position=(landing_x, landing_y),
            confidence=confidence,
            method="physics",
        )

    def get_best_estimate(
        self,
        audio_path: Optional[str],
        strike_time: float,
        trajectory_2d: List[Tuple[float, float]],
        timestamps: List[float],
        launch_params: "LaunchParameters",
    ) -> LandingEstimate:
        """Get the best landing estimate using all available methods.

        Priority:
        1. Audio detection (most accurate if available)
        2. Frame exit detection (reliable but less precise)
        3. Physics estimation (always available fallback)

        Args:
            audio_path: Path to audio/video file (optional)
            strike_time: When ball was struck (seconds)
            trajectory_2d: 2D trajectory points (normalized 0-1)
            timestamps: Timestamp for each trajectory point
            launch_params: Launch parameters from trajectory physics

        Returns:
            Best available LandingEstimate
        """
        estimates = []

        # Try audio detection first (highest priority if successful)
        if audio_path:
            audio_estimate = self.estimate_from_audio(
                audio_path, strike_time, max_flight_time=6.0
            )
            if audio_estimate:
                estimates.append(audio_estimate)
                logger.debug(f"Audio estimate: t={audio_estimate.timestamp:.2f}s")

        # Try frame exit detection
        trajectory_estimate = self.estimate_from_trajectory(trajectory_2d, timestamps)
        if trajectory_estimate:
            estimates.append(trajectory_estimate)
            logger.debug(f"Trajectory estimate: t={trajectory_estimate.timestamp:.2f}s")

        # Always have physics as fallback
        physics_estimate = self.estimate_from_physics(
            launch_params.launch_angle_deg,
            launch_params.initial_speed,
        )
        estimates.append(physics_estimate)
        logger.debug(f"Physics estimate: t={physics_estimate.timestamp:.2f}s")

        # Select best estimate
        if not estimates:
            # Should never happen since physics always returns something
            logger.warning("No landing estimates available, using default")
            return LandingEstimate(
                timestamp=3.0,
                position=(0.5, 0.3),
                confidence=0.3,
                method="physics",
            )

        # Sort by confidence and method priority
        def estimate_priority(est: LandingEstimate) -> Tuple[float, int]:
            method_priority = {"audio": 3, "frame_exit": 2, "physics": 1}
            return (est.confidence, method_priority.get(est.method, 0))

        estimates.sort(key=estimate_priority, reverse=True)
        best = estimates[0]

        logger.info(
            f"Best landing estimate: method={best.method}, t={best.timestamp:.2f}s, "
            f"confidence={best.confidence:.2f}"
        )

        return best
