"""Kalman filter predictor for ball tracking.

This module provides a Kalman filter implementation for tracking golf balls in flight.
The filter uses a 6-state model [x, y, vx, vy, ax, ay] with gravity effects.

Key features:
- Predicts where the ball should be next frame
- Provides search region for detection
- Smooths noisy detections
- Handles missing detections (occlusions)
- Rejects false positives far from prediction
"""

from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np


# Default noise parameters
POSITION_NOISE = 2.0
VELOCITY_NOISE = 5.0
ACCELERATION_NOISE = 0.5
MEASUREMENT_NOISE = 5.0


@dataclass
class KalmanState:
    """Current state of the Kalman filter.

    Attributes:
        x: X position in pixels
        y: Y position in pixels
        vx: X velocity in pixels/frame
        vy: Y velocity in pixels/frame
        ax: X acceleration in pixels/frame^2
        ay: Y acceleration in pixels/frame^2
        covariance: 6x6 covariance matrix
    """
    x: float
    y: float
    vx: float
    vy: float
    ax: float
    ay: float
    covariance: np.ndarray


@dataclass
class KalmanPrediction:
    """Prediction from Kalman filter.

    Attributes:
        x: Predicted X position
        y: Predicted Y position
        vx: Predicted X velocity
        vy: Predicted Y velocity
        uncertainty_x: Uncertainty in X position (1-sigma)
        uncertainty_y: Uncertainty in Y position (1-sigma)
        search_radius: Recommended search radius for detection
    """
    x: float
    y: float
    vx: float
    vy: float
    uncertainty_x: float
    uncertainty_y: float
    search_radius: float


class BallKalmanFilter:
    """Kalman filter for tracking golf balls with physics model.

    Uses a 6-state vector [x, y, vx, vy, ax, ay] with constant acceleration model.
    Gravity is incorporated as a constant acceleration in the y direction.

    Example:
        kf = BallKalmanFilter(fps=60.0)
        kf.initialize(x=500, y=800, vx=10, vy=-20)

        # Each frame:
        pred = kf.predict()
        if detection_found:
            state = kf.update(measured_x, measured_y)
        else:
            state = kf.update_no_measurement()
    """

    def __init__(
        self,
        fps: float = 60.0,
        gravity_pixels_per_s2: float = 500.0,
        position_noise: float = POSITION_NOISE,
        velocity_noise: float = VELOCITY_NOISE,
        acceleration_noise: float = ACCELERATION_NOISE,
        measurement_noise: float = MEASUREMENT_NOISE,
    ):
        """Initialize Kalman filter.

        Args:
            fps: Video frame rate (frames per second)
            gravity_pixels_per_s2: Gravity acceleration in pixels/s^2 (positive = downward)
            position_noise: Process noise for position
            velocity_noise: Process noise for velocity
            acceleration_noise: Process noise for acceleration
            measurement_noise: Measurement noise (detector accuracy)
        """
        self.fps = fps
        self.dt = 1.0 / fps  # Time step in seconds
        self.gravity_pixels_per_s2 = gravity_pixels_per_s2

        # Convert gravity to pixels/frame^2
        self.gravity_per_frame2 = gravity_pixels_per_s2 * (self.dt ** 2)

        # Noise parameters
        self.position_noise = position_noise
        self.velocity_noise = velocity_noise
        self.acceleration_noise = acceleration_noise
        self.measurement_noise = measurement_noise

        # State: [x, y, vx, vy, ax, ay]
        self._state: Optional[np.ndarray] = None
        self._covariance: Optional[np.ndarray] = None
        self._predicted_state: Optional[np.ndarray] = None
        self._predicted_covariance: Optional[np.ndarray] = None

        # State transition matrix (constant acceleration model)
        # x' = x + vx*dt + 0.5*ax*dt^2
        # vx' = vx + ax*dt
        # ax' = ax
        self._F = np.array([
            [1, 0, self.dt, 0,      0.5*self.dt**2, 0            ],
            [0, 1, 0,       self.dt, 0,              0.5*self.dt**2],
            [0, 0, 1,       0,      self.dt,        0            ],
            [0, 0, 0,       1,      0,              self.dt      ],
            [0, 0, 0,       0,      1,              0            ],
            [0, 0, 0,       0,      0,              1            ],
        ], dtype=np.float64)

        # Control input for gravity (affects ay state)
        # We model gravity as a constant acceleration added each step
        self._B = np.zeros(6, dtype=np.float64)
        # Gravity affects vy through ay, so we add it to the ay state
        # Actually, we'll handle gravity by setting initial ay and letting it propagate

        # Measurement matrix (we only observe position)
        self._H = np.array([
            [1, 0, 0, 0, 0, 0],
            [0, 1, 0, 0, 0, 0],
        ], dtype=np.float64)

        # Process noise covariance
        self._Q = np.diag([
            position_noise ** 2,
            position_noise ** 2,
            velocity_noise ** 2,
            velocity_noise ** 2,
            acceleration_noise ** 2,
            acceleration_noise ** 2,
        ]).astype(np.float64)

        # Measurement noise covariance
        self._R = np.diag([
            measurement_noise ** 2,
            measurement_noise ** 2,
        ]).astype(np.float64)

    def initialize(
        self,
        x: float,
        y: float,
        vx: float = 0.0,
        vy: float = 0.0,
        ax: float = 0.0,
        ay: Optional[float] = None,
    ) -> None:
        """Initialize the filter with starting state.

        Args:
            x: Initial X position
            y: Initial Y position
            vx: Initial X velocity (pixels/frame)
            vy: Initial Y velocity (pixels/frame, negative = upward)
            ax: Initial X acceleration (pixels/frame^2)
            ay: Initial Y acceleration (pixels/frame^2). If None, uses gravity.
        """
        # If ay not specified, use gravity (positive = downward in screen coords)
        if ay is None:
            ay = self.gravity_per_frame2

        self._state = np.array([x, y, vx, vy, ax, ay], dtype=np.float64)

        # Initial covariance - fairly uncertain about velocity and acceleration
        self._covariance = np.diag([
            10.0,    # x position uncertainty
            10.0,    # y position uncertainty
            50.0,    # vx uncertainty
            50.0,    # vy uncertainty
            10.0,    # ax uncertainty
            10.0,    # ay uncertainty
        ]).astype(np.float64)

        self._predicted_state = None
        self._predicted_covariance = None

    def predict(self) -> KalmanPrediction:
        """Predict next state.

        Returns:
            KalmanPrediction with predicted position and uncertainties

        Raises:
            RuntimeError: If filter not initialized
        """
        if self._state is None or self._covariance is None:
            raise RuntimeError("Kalman filter not initialized. Call initialize() first.")

        # State prediction: x' = F * x
        self._predicted_state = self._F @ self._state

        # Covariance prediction: P' = F * P * F^T + Q
        self._predicted_covariance = self._F @ self._covariance @ self._F.T + self._Q

        # Extract uncertainties from covariance
        uncertainty_x = np.sqrt(self._predicted_covariance[0, 0])
        uncertainty_y = np.sqrt(self._predicted_covariance[1, 1])

        # Search radius is max of x/y uncertainty scaled for 3-sigma
        search_radius = 3.0 * max(uncertainty_x, uncertainty_y)

        return KalmanPrediction(
            x=float(self._predicted_state[0]),
            y=float(self._predicted_state[1]),
            vx=float(self._predicted_state[2]),
            vy=float(self._predicted_state[3]),
            uncertainty_x=float(uncertainty_x),
            uncertainty_y=float(uncertainty_y),
            search_radius=float(search_radius),
        )

    def update(
        self,
        measured_x: float,
        measured_y: float,
        measurement_confidence: float = 1.0,
    ) -> KalmanState:
        """Update state with measurement.

        Args:
            measured_x: Measured X position
            measured_y: Measured Y position
            measurement_confidence: Confidence in measurement (0-1).
                Lower confidence increases measurement noise.

        Returns:
            Updated KalmanState

        Raises:
            RuntimeError: If predict() not called first
        """
        if self._predicted_state is None or self._predicted_covariance is None:
            raise RuntimeError("Must call predict() before update()")

        # Adjust measurement noise based on confidence
        R = self._R.copy()
        if measurement_confidence < 1.0 and measurement_confidence > 0:
            # Higher noise for lower confidence
            noise_scale = 1.0 / measurement_confidence
            R = R * noise_scale

        # Measurement
        z = np.array([measured_x, measured_y], dtype=np.float64)

        # Innovation (measurement residual)
        y = z - self._H @ self._predicted_state

        # Innovation covariance
        S = self._H @ self._predicted_covariance @ self._H.T + R

        # Kalman gain
        K = self._predicted_covariance @ self._H.T @ np.linalg.inv(S)

        # State update
        self._state = self._predicted_state + K @ y

        # Covariance update (Joseph form for numerical stability)
        I = np.eye(6)
        IKH = I - K @ self._H
        self._covariance = IKH @ self._predicted_covariance @ IKH.T + K @ R @ K.T

        # Reset predicted state (must call predict() again)
        self._predicted_state = None
        self._predicted_covariance = None

        return self.get_state()

    def update_no_measurement(self) -> KalmanState:
        """Update state when no measurement available.

        Uses predicted state as the new state, with increased uncertainty.

        Returns:
            Updated KalmanState

        Raises:
            RuntimeError: If predict() not called first
        """
        if self._predicted_state is None or self._predicted_covariance is None:
            raise RuntimeError("Must call predict() before update_no_measurement()")

        # Use predicted state directly
        self._state = self._predicted_state.copy()
        self._covariance = self._predicted_covariance.copy()

        # Reset predicted state (must call predict() again)
        self._predicted_state = None
        self._predicted_covariance = None

        return self.get_state()

    def get_state(self) -> Optional[KalmanState]:
        """Get current state.

        Returns:
            Current KalmanState or None if not initialized
        """
        if self._state is None or self._covariance is None:
            return None

        return KalmanState(
            x=float(self._state[0]),
            y=float(self._state[1]),
            vx=float(self._state[2]),
            vy=float(self._state[3]),
            ax=float(self._state[4]),
            ay=float(self._state[5]),
            covariance=self._covariance.copy(),
        )

    def is_measurement_plausible(
        self,
        measured_x: float,
        measured_y: float,
        sigma_threshold: float = 3.0,
    ) -> bool:
        """Check if measurement is plausible given current prediction.

        Uses Mahalanobis distance to determine if measurement is within
        acceptable range of predicted position.

        Args:
            measured_x: Measured X position
            measured_y: Measured Y position
            sigma_threshold: Number of standard deviations for acceptance

        Returns:
            True if measurement is plausible, False otherwise

        Raises:
            RuntimeError: If predict() not called first
        """
        if self._predicted_state is None or self._predicted_covariance is None:
            raise RuntimeError("Must call predict() before is_measurement_plausible()")

        # Measurement
        z = np.array([measured_x, measured_y], dtype=np.float64)

        # Innovation (measurement residual)
        innovation = z - self._H @ self._predicted_state

        # Innovation covariance
        S = self._H @ self._predicted_covariance @ self._H.T + self._R

        # Mahalanobis distance squared
        try:
            S_inv = np.linalg.inv(S)
            mahal_dist_sq = float(innovation.T @ S_inv @ innovation)
        except np.linalg.LinAlgError:
            # If covariance is singular, fall back to Euclidean distance
            dist = np.sqrt(innovation[0]**2 + innovation[1]**2)
            max_dist = sigma_threshold * max(
                np.sqrt(self._predicted_covariance[0, 0]),
                np.sqrt(self._predicted_covariance[1, 1])
            )
            return dist <= max_dist

        # Chi-squared threshold for 2 DOF
        # At 3 sigma, chi-squared threshold is about 11.83 for 2 DOF
        # For simpler comparison, use sigma_threshold^2 * 2
        chi_sq_threshold = (sigma_threshold ** 2) * 2

        return mahal_dist_sq <= chi_sq_threshold

    def get_search_region(
        self,
        sigma_multiplier: float = 3.0,
    ) -> Tuple[int, int, int, int]:
        """Get bounding box for detection search region.

        Args:
            sigma_multiplier: Number of standard deviations for region size

        Returns:
            Tuple of (x_min, y_min, x_max, y_max) in pixels

        Raises:
            RuntimeError: If predict() not called first
        """
        if self._predicted_state is None or self._predicted_covariance is None:
            raise RuntimeError("Must call predict() before get_search_region()")

        pred_x = self._predicted_state[0]
        pred_y = self._predicted_state[1]

        uncertainty_x = np.sqrt(self._predicted_covariance[0, 0])
        uncertainty_y = np.sqrt(self._predicted_covariance[1, 1])

        margin_x = sigma_multiplier * uncertainty_x
        margin_y = sigma_multiplier * uncertainty_y

        return (
            int(pred_x - margin_x),
            int(pred_y - margin_y),
            int(pred_x + margin_x),
            int(pred_y + margin_y),
        )

    def reset(self) -> None:
        """Reset filter to uninitialized state."""
        self._state = None
        self._covariance = None
        self._predicted_state = None
        self._predicted_covariance = None
