"""Trajectory physics module for generating 3D ball trajectories.

This module extracts launch parameters from early ball detections (first ~100ms)
and generates a complete physics-based 3D trajectory.

Coordinate System (3D):
- X: left/right deviation (negative = draw for RH, positive = fade)
- Y: height above ground
- Z: distance toward target (away from camera)
"""

import math
from dataclasses import dataclass
from typing import List, Optional, Tuple


@dataclass
class LaunchParameters:
    """Extracted launch characteristics from early ball detections."""

    origin: Tuple[float, float]  # Screen position (x, y) at impact
    launch_angle_deg: float  # Vertical launch angle (typically 10-30°)
    lateral_angle_deg: float  # Left/right deviation (-15° to +15°)
    initial_speed: float  # Estimated initial speed (pixels/second)
    estimated_flight_time: float  # Estimated total flight duration
    shot_shape: str  # "draw", "fade", or "straight"


@dataclass
class Trajectory3D:
    """Complete 3D trajectory with timestamps."""

    points: List[Tuple[float, float, float]]  # (x, y, z) at each timestamp
    timestamps: List[float]  # Time for each point
    apex_index: int  # Index of highest point
    landing_index: int  # Index of landing point


class TrajectoryPhysics:
    """Generate physics-based ball trajectories from early detections.

    This class extracts launch parameters from the first ~6 detected ball
    positions (covering approximately 100ms after impact) and uses projectile
    motion physics to generate a complete 3D trajectory.
    """

    # Physics constants (calibrated for normalized screen coordinates)
    # These values are tuned to produce visually appealing arcs that:
    # - Rise from y=0.8 to apex around y=0.3-0.5
    # - Last 3-5 seconds (typical golf shot flight time)
    GRAVITY = 0.15  # normalized units/s² - creates visible parabolic arc
    DEFAULT_FLIGHT_TIME = 4.0  # seconds

    # Minimum trajectory parameters for aesthetics
    MIN_FLIGHT_TIME = 2.5  # seconds - ensures tracer is visible long enough
    MIN_APEX_HEIGHT = 0.25  # normalized - ball should rise at least 25% of frame

    # Shot shape classification thresholds
    STRAIGHT_THRESHOLD_DEG = 2.0  # ±2° is considered straight

    def __init__(
        self,
        gravity: float = GRAVITY,
        straight_threshold_deg: float = STRAIGHT_THRESHOLD_DEG,
    ):
        """Initialize the trajectory physics calculator.

        Args:
            gravity: Gravity constant in pixels/s². Default 500 provides
                     realistic-looking arcs in typical golf video.
            straight_threshold_deg: Lateral angle threshold for classifying
                                    a shot as "straight".
        """
        self.gravity = gravity
        self.straight_threshold_deg = straight_threshold_deg

    def extract_launch_params(
        self,
        early_detections: List[dict],
        frame_width: int,
        frame_height: int,
    ) -> LaunchParameters:
        """Extract launch parameters from early ball detections.

        Uses position differences to calculate velocities and derive launch
        angle, lateral direction, and shot shape.

        Args:
            early_detections: List of dicts with 'timestamp', 'x', 'y'
                              (normalized 0-1 coordinates)
            frame_width: Video frame width for denormalization
            frame_height: Video frame height for denormalization

        Returns:
            LaunchParameters with extracted characteristics
        """
        if len(early_detections) < 2:
            raise ValueError("Need at least 2 detections to extract launch params")

        # Convert normalized coords to pixels
        points = []
        timestamps = []
        for det in early_detections:
            px = det["x"] * frame_width
            py = det["y"] * frame_height
            points.append((px, py))
            timestamps.append(det["timestamp"])

        origin = (early_detections[0]["x"], early_detections[0]["y"])
        origin_px = points[0]

        # Calculate velocities from position differences
        velocities_x = []
        velocities_y = []

        for i in range(1, len(points)):
            dt = timestamps[i] - timestamps[i - 1]
            if dt <= 0:
                continue

            dx = points[i][0] - points[i - 1][0]
            dy = points[i][1] - points[i - 1][1]

            velocities_x.append(dx / dt)
            velocities_y.append(-dy / dt)  # Invert Y since screen Y is inverted

        if not velocities_x:
            raise ValueError("Could not calculate velocities from detections")

        # Average velocities (more stable than single frame)
        avg_vx = sum(velocities_x) / len(velocities_x)
        avg_vy = sum(velocities_y) / len(velocities_y)

        # Estimate Z velocity (depth toward target)
        # Since we can't measure Z directly from 2D, estimate from vertical velocity
        # Higher vertical velocity suggests higher launch angle with similar overall speed
        estimated_total_speed = math.sqrt(avg_vx**2 + avg_vy**2) * 3.0
        avg_vz = max(estimated_total_speed * 0.8, 200.0)  # Z component is typically larger

        # Calculate launch angle (vertical)
        launch_angle_rad = math.atan2(avg_vy, avg_vz)
        launch_angle_deg = math.degrees(launch_angle_rad)

        # Clamp to realistic range
        launch_angle_deg = max(5.0, min(45.0, launch_angle_deg))

        # Calculate lateral angle
        lateral_angle_rad = math.atan2(avg_vx, avg_vz)
        lateral_angle_deg = math.degrees(lateral_angle_rad)

        # Calculate curve rate from acceleration
        curve_rate = self._calculate_curve_rate(velocities_x, timestamps[1:])

        # Classify shot shape
        shot_shape = self.classify_shot_shape(lateral_angle_deg, curve_rate)

        # Estimate initial speed in pixels/second
        initial_speed = math.sqrt(avg_vx**2 + avg_vy**2 + avg_vz**2)

        # Estimate flight time from launch angle
        estimated_flight_time = self._estimate_flight_time(launch_angle_deg)

        return LaunchParameters(
            origin=origin,
            launch_angle_deg=launch_angle_deg,
            lateral_angle_deg=lateral_angle_deg,
            initial_speed=initial_speed,
            estimated_flight_time=estimated_flight_time,
            shot_shape=shot_shape,
        )

    def generate_trajectory(
        self,
        launch_params: LaunchParameters,
        duration: float = 4.0,
        sample_rate: float = 30.0,
    ) -> Trajectory3D:
        """Generate complete 3D trajectory from launch parameters.

        Uses projectile motion equations in NORMALIZED screen coordinates:
        - The trajectory is designed to create visually appealing arcs
        - X/Y/Z are in normalized screen units (0-1 range)
        - X: lateral deviation from center (draw negative, fade positive)
        - Y: height above origin (0 = ground, positive = up)
        - Z: depth toward target (used for perspective but not directly visible)

        Args:
            launch_params: Extracted launch characteristics
            duration: Maximum flight duration to simulate (seconds)
            sample_rate: How many points per second to generate

        Returns:
            Trajectory3D with full flight path
        """
        # Ensure minimum flight time for visual appeal
        flight_duration = max(self.MIN_FLIGHT_TIME, min(duration, launch_params.estimated_flight_time))
        num_points = int(flight_duration * sample_rate) + 1

        # Calculate initial velocities in NORMALIZED screen units
        # These values are calibrated to produce visible arcs:
        # - Ball should rise from y=0 (origin) to apex around y=0.3-0.5 (screen coords)
        # - Ball should travel ~0.4-0.6 in Z direction (toward horizon)
        launch_rad = math.radians(launch_params.launch_angle_deg)
        lateral_rad = math.radians(launch_params.lateral_angle_deg)

        # Base speed calibrated for normalized coordinates
        # Adjusted so that a typical shot creates a visible arc
        base_vertical_speed = 0.35  # Will create apex around 0.4 above origin
        base_horizontal_speed = 0.15  # Lateral movement rate

        # Scale speeds based on launch angle
        # Higher launch = more vertical, less horizontal
        v_y = base_vertical_speed * (0.5 + 0.5 * math.sin(launch_rad))
        v_horizontal = base_horizontal_speed

        # Lateral velocity based on lateral angle
        v_x = v_horizontal * math.sin(lateral_rad) * 0.5  # Scaled down for subtlety
        v_z = v_horizontal * math.cos(lateral_rad)

        # Curve acceleration for draw/fade (subtle effect)
        curve_accel = self._get_curve_acceleration(launch_params.shot_shape)

        # Generate trajectory points
        points = []
        timestamps = []
        apex_index = 0
        max_y = 0

        for i in range(num_points):
            t = i / sample_rate

            # Physics equations in normalized coords
            x = v_x * t + curve_accel * t * t
            y = v_y * t - 0.5 * self.gravity * t * t
            z = v_z * t

            # Track apex
            if y > max_y:
                max_y = y
                apex_index = i

            # Stop if ball hits ground (y < 0) after apex
            if y < 0 and i > apex_index:
                # Interpolate to exact landing point
                t_land = 2 * v_y / self.gravity if self.gravity > 0 else flight_duration
                x_land = v_x * t_land + curve_accel * t_land * t_land
                y_land = 0.0
                z_land = v_z * t_land

                points.append((x_land, y_land, z_land))
                timestamps.append(t_land)
                break

            points.append((x, y, z))
            timestamps.append(t)

        landing_index = len(points) - 1

        return Trajectory3D(
            points=points,
            timestamps=timestamps,
            apex_index=apex_index,
            landing_index=landing_index,
        )

    def classify_shot_shape(
        self,
        lateral_angle_deg: float,
        curve_rate: float,
    ) -> str:
        """Classify shot as draw, fade, or straight.

        For a right-handed golfer looking down the line:
        - Draw: ball curves right-to-left (negative lateral angle)
        - Fade: ball curves left-to-right (positive lateral angle)
        - Straight: minimal lateral deviation

        Args:
            lateral_angle_deg: Initial lateral launch angle in degrees
            curve_rate: Rate of lateral curve (acceleration)

        Returns:
            "draw", "fade", or "straight"
        """
        # Combine lateral angle and curve rate for classification
        effective_deviation = lateral_angle_deg + curve_rate * 10.0

        if abs(effective_deviation) <= self.straight_threshold_deg:
            return "straight"
        elif effective_deviation < 0:
            return "draw"
        else:
            return "fade"

    def _calculate_curve_rate(
        self,
        velocities_x: List[float],
        timestamps: List[float],
    ) -> float:
        """Calculate the rate of lateral curve from velocity changes.

        A positive curve rate indicates fade, negative indicates draw.
        """
        if len(velocities_x) < 2:
            return 0.0

        # Calculate acceleration (change in velocity over time)
        accelerations = []
        for i in range(1, len(velocities_x)):
            if i < len(timestamps):
                dt = timestamps[i] - timestamps[i - 1]
                if dt > 0:
                    dv = velocities_x[i] - velocities_x[i - 1]
                    accelerations.append(dv / dt)

        if not accelerations:
            return 0.0

        return sum(accelerations) / len(accelerations)

    def _estimate_flight_time(self, launch_angle_deg: float) -> float:
        """Estimate flight time based on launch angle.

        Typical golf shot flight times:
        - Driver (10-15°): 4-6 seconds
        - Iron (20-30°): 3-5 seconds
        - Wedge (30-45°): 2-4 seconds
        """
        # Higher launch angles have shorter flight times (more height, less distance)
        if launch_angle_deg < 15:
            return 5.0  # Driver-like
        elif launch_angle_deg < 25:
            return 4.0  # Iron-like
        elif launch_angle_deg < 35:
            return 3.5  # Short iron
        else:
            return 3.0  # Wedge

    def _get_curve_acceleration(self, shot_shape: str) -> float:
        """Get curve acceleration based on shot shape.

        Returns acceleration in normalized units/s² for lateral curve.
        These values are calibrated for subtle, realistic-looking curves.
        """
        if shot_shape == "draw":
            return -0.015  # Curves left (for RH golfer)
        elif shot_shape == "fade":
            return 0.015  # Curves right
        else:
            return 0.0  # Straight

    def _find_landing_time(self, initial_vy: float) -> float:
        """Calculate exact landing time when y = 0.

        Using y = vy*t - 0.5*g*t²
        Setting y = 0: t = 2*vy/g
        """
        if self.gravity <= 0:
            return self.DEFAULT_FLIGHT_TIME

        t_land = 2 * initial_vy / self.gravity
        return max(0.1, t_land)  # Ensure positive time
