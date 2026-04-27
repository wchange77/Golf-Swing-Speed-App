"""Ball origin detection using multiple methods.

Uses geometric constraints and multiple detection methods to reliably
find the golf ball's starting position before impact.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from loguru import logger

from backend.detection.visual import BallDetector


@dataclass
class OriginDetection:
    """Result of ball origin detection."""

    x: float  # X coordinate in pixels
    y: float  # Y coordinate in pixels
    confidence: float  # 0-1, higher = more certain
    method: str  # Which method(s) found it
    golfer_bbox: Optional[tuple[float, float, float, float]] = None  # x1,y1,x2,y2


class BallOriginDetector:
    """Detects the golf ball's starting position using multiple methods.

    Methods:
    1. YOLO person detection - find golfer, estimate ball zone near feet
    2. Hough line detection - find club shaft, follow to ball
    3. YOLO ball detection - directly detect ball in the estimated zone

    If multiple methods agree, confidence is higher.
    """

    # Ball zone parameters (relative to golfer bbox)
    BALL_ZONE_BELOW_FEET = 0.05  # Ball is slightly below feet line
    BALL_ZONE_RADIUS_RATIO = 0.15  # Search radius as ratio of person height

    # Shaft detection parameters
    SHAFT_MIN_LENGTH = 50  # Minimum line length in pixels
    SHAFT_ANGLE_TOLERANCE = 30  # Degrees from vertical to consider as shaft

    # Agreement threshold for multi-method consensus
    AGREEMENT_DISTANCE = 50  # Pixels - if detections within this, they agree

    def __init__(self, ball_detector: Optional[BallDetector] = None):
        """Initialize the origin detector.

        Args:
            ball_detector: Optional existing BallDetector instance to reuse
        """
        self.ball_detector = ball_detector or BallDetector()

    def detect_origin(
        self,
        video_path: Path,
        strike_time: float,
        look_before: float = 2.5,
    ) -> Optional[OriginDetection]:
        """Detect ball origin position at address (before swing).

        Args:
            video_path: Path to video file
            strike_time: Timestamp of ball strike (from audio detection)
            look_before: How many seconds before strike to look for ball.
                        Default 2.5s to reliably catch address position before backswing starts.

        Returns:
            OriginDetection with position and confidence, or None if not found
        """
        # Get frame at address position (before backswing starts)
        # At address, the shaft points directly to the ball
        target_time = strike_time - look_before
        frame = self._get_frame_at_time(video_path, target_time)
        if frame is None:
            logger.warning(f"Could not read frame at {target_time:.2f}s")
            return None

        frame_height, frame_width = frame.shape[:2]

        # Method 1: Find golfer and estimate ball zone
        golfer_result = self._detect_golfer_zone(frame)

        # Method 2: Detect shaft and follow to ball (if golfer found)
        shaft_result = None
        if golfer_result:
            shaft_result = self._detect_shaft_endpoint(
                frame,
                golfer_result["bbox"],
                golfer_result["feet_position"][1],  # feet_y
            )

        # Method 3: YOLO ball detection in zone
        ball_result = None
        search_zone = None
        if golfer_result:
            search_zone = golfer_result["ball_zone"]
        elif shaft_result:
            # Use shaft endpoint as center of search
            search_zone = self._zone_around_point(
                shaft_result["x"], shaft_result["y"],
                radius=100, frame_width=frame_width, frame_height=frame_height
            )

        if search_zone:
            ball_result = self._detect_ball_in_zone(frame, search_zone)

        # Combine results
        return self._combine_detections(
            golfer_result, shaft_result, ball_result, frame_width, frame_height
        )

    def detect_origin_from_frame(
        self,
        frame: np.ndarray,
    ) -> Optional[OriginDetection]:
        """Detect ball origin in a single frame.

        Args:
            frame: BGR image as numpy array

        Returns:
            OriginDetection or None
        """
        frame_height, frame_width = frame.shape[:2]

        # Method 1: Find golfer
        golfer_result = self._detect_golfer_zone(frame)

        # Method 2: Shaft detection
        shaft_result = None
        if golfer_result:
            shaft_result = self._detect_shaft_endpoint(
                frame,
                golfer_result["bbox"],
                golfer_result["feet_position"][1],  # feet_y
            )

        # Method 3: Ball detection
        ball_result = None
        if golfer_result:
            ball_result = self._detect_ball_in_zone(
                frame, golfer_result["ball_zone"]
            )

        return self._combine_detections(
            golfer_result, shaft_result, ball_result, frame_width, frame_height
        )

    def _get_frame_at_time(
        self, video_path: Path, timestamp: float
    ) -> Optional[np.ndarray]:
        """Extract a single frame from video at given timestamp."""
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            return None

        try:
            fps = cap.get(cv2.CAP_PROP_FPS)
            if fps <= 0:
                return None

            frame_num = int(timestamp * fps)
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)

            ret, frame = cap.read()
            return frame if ret else None
        finally:
            cap.release()

    def _detect_golfer_zone(self, frame: np.ndarray) -> Optional[dict]:
        """Detect golfer and estimate ball zone near their feet.

        Returns dict with:
            - bbox: golfer bounding box (x1, y1, x2, y2)
            - feet_position: (x, y) estimated feet center
            - ball_zone: (x1, y1, x2, y2) search region for ball
        """
        # Use existing golfer detection
        golfer = self.ball_detector.detect_golfer_in_frame(frame)
        if golfer is None:
            logger.debug("No golfer detected in frame")
            return None

        x1, y1, x2, y2 = golfer.bbox
        person_height = y2 - y1
        person_width = x2 - x1

        # Feet are at bottom center of bbox
        feet_x = golfer.feet_position[0]
        feet_y = golfer.feet_position[1]

        # Ball zone: area around and slightly in front of feet
        # Golf ball is typically 6-12 inches in front of lead foot
        zone_radius = person_height * self.BALL_ZONE_RADIUS_RATIO
        zone_offset_y = person_height * self.BALL_ZONE_BELOW_FEET

        frame_height, frame_width = frame.shape[:2]

        # Ball zone extends horizontally around feet and slightly below
        zone_x1 = max(0, feet_x - zone_radius)
        zone_x2 = min(frame_width, feet_x + zone_radius)
        zone_y1 = max(0, feet_y - zone_radius / 2)  # Less room above
        zone_y2 = min(frame_height, feet_y + zone_offset_y + zone_radius / 2)

        logger.debug(
            f"Golfer detected at ({feet_x:.0f},{feet_y:.0f}), "
            f"ball zone: ({zone_x1:.0f},{zone_y1:.0f})-({zone_x2:.0f},{zone_y2:.0f})"
        )

        return {
            "bbox": golfer.bbox,
            "feet_position": (feet_x, feet_y),
            "ball_zone": (zone_x1, zone_y1, zone_x2, zone_y2),
            "confidence": golfer.confidence,
            "width": person_width,
            "height": person_height,
        }

    def _detect_shaft_endpoint(
        self,
        frame: np.ndarray,
        golfer_bbox: tuple[float, float, float, float],
        feet_y: float,
    ) -> Optional[dict]:
        """Detect club shaft and find clubhead/ball position.

        Architecture based on geometric constraints:
        1. One end terminates between y-min and y-max of golfer bbox (hands area)
        2. Other end terminates within ~100px of y-max of golfer bbox (feet/ground level)
        3. Line is diagonal, 15-60° from horizontal (negative slope in Cartesian)
        4. Clubhead is at maximum x-value of the line

        Args:
            frame: Full frame
            golfer_bbox: (x1, y1, x2, y2) golfer bounding box
            feet_y: Y coordinate of golfer's feet (bottom of bbox)

        Returns:
            Dict with x, y of clubhead position (ball location)
        """
        gx1, gy1, gx2, gy2 = [int(v) for v in golfer_bbox]
        golfer_height = gy2 - gy1
        golfer_width = gx2 - gx1
        frame_height, frame_width = frame.shape[:2]

        # Search region: around the golfer area where the shaft would be visible
        # Include full golfer height plus some margin below for clubhead
        search_x1 = max(0, gx1 - int(golfer_width * 0.5))
        search_x2 = min(frame_width, gx2 + int(golfer_width * 0.8))
        search_y1 = max(0, gy1)
        search_y2 = min(frame_height, int(gy2 + 100))

        # Extract search region
        region = frame[search_y1:search_y2, search_x1:search_x2]
        if region.size == 0:
            return None

        # Try multiple line detection methods
        lines = self._detect_lines_multi_method(region)

        if lines is None or len(lines) == 0:
            logger.debug("No lines detected in search region")
            return None

        # Filter lines using shaft geometric constraints
        shaft_candidates = []

        for line_coords in lines:
            if len(line_coords) == 4:
                lx1, ly1, lx2, ly2 = line_coords
            else:
                lx1, ly1, lx2, ly2 = line_coords[0]

            # Convert to frame coordinates
            fx1, fy1 = search_x1 + lx1, search_y1 + ly1
            fx2, fy2 = search_x1 + lx2, search_y1 + ly2

            # Identify which end has maximum x (clubhead end)
            if fx1 > fx2:
                clubhead_x, clubhead_y = fx1, fy1
                grip_x, grip_y = fx2, fy2
            else:
                clubhead_x, clubhead_y = fx2, fy2
                grip_x, grip_y = fx1, fy1

            # Calculate line properties
            dx = clubhead_x - grip_x
            dy = clubhead_y - grip_y
            length = np.sqrt(dx ** 2 + dy ** 2)

            if length < 60:  # Shaft must be at least 60px long
                continue

            # Calculate angle from horizontal (y=0 line)
            # In screen coords: positive dx (right), positive dy (down)
            # arctan2(dy, dx) gives angle from horizontal
            angle_from_horizontal = abs(np.degrees(np.arctan2(abs(dy), abs(dx))))

            # Constraint 3: Angle 15-60° from horizontal
            if not (15 <= angle_from_horizontal <= 60):
                continue

            # Constraint: Shaft goes from upper-left to lower-right (negative slope in Cartesian)
            # In screen coords: grip should be above and left of clubhead
            # grip_y should be < clubhead_y (grip is higher on screen)
            # grip_x should be < clubhead_x (grip is to the left)
            if grip_y >= clubhead_y or grip_x >= clubhead_x:
                continue

            # Constraint 1: Grip end (one end) terminates between y-min and y-max of golfer
            # The grip/hands should be somewhere in the golfer's body
            if not (gy1 <= grip_y <= gy2):
                continue

            # Constraint 2: Clubhead end terminates near y-max (feet level)
            # gy2 is y-max of golfer bbox (feet)
            # The clubhead should be AT or slightly ABOVE feet level, not below
            # The ball sits at ground level, which is approximately where the feet are
            # Allow up to 50px above (club can be slightly off ground at address)
            # Allow only 10px below (small tolerance for bbox inaccuracy)
            if clubhead_y < gy2 - 50:  # Too high above feet
                continue
            if clubhead_y > gy2 + 10:  # Too far below feet - truncate the line
                # Calculate where the line intersects gy2 (feet level)
                target_y = gy2
                # Using line equation: y - grip_y = slope * (x - grip_x)
                # slope = (clubhead_y - grip_y) / (clubhead_x - grip_x)
                if clubhead_x != grip_x:
                    slope = (clubhead_y - grip_y) / (clubhead_x - grip_x)
                    # Solve for x when y = target_y
                    clubhead_x = grip_x + (target_y - grip_y) / slope
                clubhead_y = target_y
                # Recalculate length after truncation
                dx = clubhead_x - grip_x
                dy = clubhead_y - grip_y
                length = np.sqrt(dx ** 2 + dy ** 2)

            # Constraint 4: Clubhead at maximum x-value
            # Already ensured by our clubhead/grip assignment above

            # Additional constraint: clubhead position relative to golfer bbox
            # For camera angles from the side or DTL with angle:
            # - Clubhead CAN be significantly to the right of golfer bbox
            # - But grip should still be within/near the golfer's body
            golfer_center_x = (gx1 + gx2) / 2

            # Clubhead must be to the right of golfer center (for RH golfer)
            if clubhead_x < golfer_center_x:
                continue

            # Grip end (hands) should be within the golfer bbox or just slightly outside
            # At address position, hands are roughly centered over the golfer's stance
            # Not too far to the left or right of the golfer's body
            if grip_x < gx1 - golfer_width * 0.1 or grip_x > gx2 + golfer_width * 0.1:
                continue

            # Analyze color along the line to distinguish shaft from grass
            # The shaft should be darker than bright green grass
            color_score = self._analyze_line_color(
                frame, grip_x, grip_y, clubhead_x, clubhead_y
            )

            # Skip lines that look like bright grass (very low score)
            if color_score < 0.2:
                continue

            # Score this candidate
            # Prefer: longer lines, clubhead closer to feet level, good angle, dark color
            angle_score = 1.0 - abs(angle_from_horizontal - 40) / 45  # Prefer ~40° angle
            length_score = min(length / 300, 1.0)  # Normalize length
            y_proximity_score = 1.0 - abs(clubhead_y - gy2) / 100  # Closer to feet = better

            # Weight: color is most important to distinguish from grass
            score = (
                color_score * 0.4 +
                length_score * 0.25 +
                angle_score * 0.2 +
                y_proximity_score * 0.15
            )

            shaft_candidates.append({
                "x": clubhead_x,
                "y": clubhead_y,
                "grip_x": grip_x,
                "grip_y": grip_y,
                "length": length,
                "angle": angle_from_horizontal,
                "color_score": color_score,
                "score": score,
            })

        if not shaft_candidates:
            logger.debug(
                f"No shaft lines found matching constraints. "
                f"Trying clubhead detection fallback. "
                f"Golfer bbox: ({gx1},{gy1})-({gx2},{gy2}), feet_y={feet_y:.0f}"
            )
            # Fallback: detect clubhead as a bright metallic region
            clubhead = self._detect_clubhead_region(frame, golfer_bbox, feet_y)
            if clubhead:
                return clubhead
            return None

        logger.debug(f"Found {len(shaft_candidates)} shaft candidates after filtering")

        # Pick the best shaft candidate by score
        best = max(shaft_candidates, key=lambda s: s["score"])

        # Require minimum quality for shaft detection
        # If score is too low, fall back to clubhead detection
        if best["score"] < 0.75:
            logger.debug(
                f"Best shaft candidate score {best['score']:.2f} below threshold 0.75. "
                f"Trying clubhead detection fallback."
            )
            clubhead = self._detect_clubhead_region(frame, golfer_bbox, feet_y)
            if clubhead:
                return clubhead
            # If clubhead detection also fails, return best shaft candidate anyway
            logger.debug("Clubhead detection also failed, using best shaft candidate")

        # The shaft endpoint is the HOSEL (where shaft meets clubhead).
        # To find the ball position:
        # - Y coordinate: Use the hosel Y (ground level where ball sits)
        # - X coordinate: Detect the clubhead and use its center X

        hosel_x = best['x']
        hosel_y = best['y']

        # Detect the clubhead region near the hosel to get accurate X position
        clubhead_center = self._detect_clubhead_center(
            frame, hosel_x, hosel_y, golfer_bbox
        )

        if clubhead_center:
            ball_x = clubhead_center['x']
            # Y from clubhead center (represents hosel midpoint better than shaft endpoint)
            # The clubhead center Y is at approximately the same level as the hosel midpoint
            ball_y = clubhead_center['y']
            logger.info(
                f"Shaft+clubhead detected: hosel at ({hosel_x:.0f},{hosel_y:.0f}), "
                f"clubhead center at ({clubhead_center['x']:.0f},{clubhead_center['y']:.0f}), "
                f"ball at ({ball_x:.0f},{ball_y:.0f}), "
                f"grip at ({best['grip_x']:.0f},{best['grip_y']:.0f}), "
                f"length={best['length']:.0f}px, angle={best['angle']:.1f}°, score={best['score']:.2f}"
            )
        else:
            # Fallback: use hosel position with small X offset
            # Driver clubhead is ~115mm wide, at 4K that's roughly 40-60px
            ball_x = hosel_x + 30  # Conservative offset to clubhead center
            ball_y = min(hosel_y, gy2)  # Cap at feet level
            logger.info(
                f"Shaft detected (no clubhead): hosel at ({hosel_x:.0f},{hosel_y:.0f}), "
                f"ball at ({ball_x:.0f},{ball_y:.0f}) with fallback offset, "
                f"grip at ({best['grip_x']:.0f},{best['grip_y']:.0f}), "
                f"length={best['length']:.0f}px, angle={best['angle']:.1f}°, score={best['score']:.2f}"
            )

        return {
            "x": ball_x,
            "y": ball_y,
            "hosel_x": hosel_x,
            "hosel_y": hosel_y,
            "grip_x": best['grip_x'],
            "grip_y": best['grip_y'],
            "length": best['length'],
            "angle": best['angle'],
            "color_score": best['color_score'],
            "score": best['score'],
        }

    def _detect_clubhead_region(
        self,
        frame: np.ndarray,
        golfer_bbox: tuple[float, float, float, float],
        feet_y: float,
    ) -> Optional[dict]:
        """Detect clubhead as a bright/metallic region near the feet.

        Fallback method when shaft line detection fails.
        Looks for the driver head (metallic/bright) and estimates ball position.

        Args:
            frame: Full BGR frame
            golfer_bbox: (x1, y1, x2, y2) golfer bounding box
            feet_y: Y coordinate of golfer's feet

        Returns:
            Dict with x, y of estimated ball position
        """
        gx1, gy1, gx2, gy2 = [int(v) for v in golfer_bbox]
        golfer_width = gx2 - gx1
        golfer_center_x = (gx1 + gx2) / 2
        frame_height, frame_width = frame.shape[:2]

        # Search region: to the right of golfer, near feet level
        roi_x1 = int(gx1 + golfer_width * 0.3)
        roi_x2 = int(min(frame_width, gx2 + golfer_width * 1.0))
        roi_y1 = int(feet_y - 100)
        roi_y2 = int(min(frame_height, feet_y + 80))

        roi = frame[roi_y1:roi_y2, roi_x1:roi_x2]
        if roi.size == 0:
            return None

        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)

        # Detect bright regions (clubhead is metallic/reflective)
        v_channel = hsv[:, :, 2]
        _, bright_mask = cv2.threshold(v_channel, 160, 255, cv2.THRESH_BINARY)

        # Clean up
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        bright_mask = cv2.morphologyEx(bright_mask, cv2.MORPH_CLOSE, kernel)

        contours, _ = cv2.findContours(
            bright_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )

        # Find the clubhead - should be a large bright region to the right of golfer
        candidates = []
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < 200 or area > 5000:  # Clubhead area range
                continue

            M = cv2.moments(cnt)
            if M['m00'] == 0:
                continue
            cx = int(M['m10'] / M['m00'])
            cy = int(M['m01'] / M['m00'])

            fx = roi_x1 + cx
            fy = roi_y1 + cy

            # Must be to the right of golfer center
            if fx < golfer_center_x + golfer_width * 0.2:
                continue

            # Near feet level
            if abs(fy - feet_y) > 100:
                continue

            candidates.append({
                'x': fx,
                'y': fy,
                'area': area,
            })

        if not candidates:
            return None

        # Find the candidate closest to expected clubhead position
        # (to the right of golfer but not too far)
        target_x = golfer_center_x + golfer_width * 0.5
        best = min(candidates, key=lambda c: abs(c['x'] - target_x))

        # At address, the ball is directly in front of the clubhead
        # No offset needed - clubhead position IS the ball position
        ball_x = best['x']
        ball_y = max(best['y'], feet_y - 20)  # Ball is at or near ground level

        logger.info(
            f"Clubhead detected at ({best['x']:.0f},{best['y']:.0f}), "
            f"area={best['area']:.0f}. Ball at ({ball_x:.0f},{ball_y:.0f})"
        )

        return {
            'x': ball_x,
            'y': ball_y,
            'method': 'clubhead',
        }

    def _detect_clubhead_center(
        self,
        frame: np.ndarray,
        hosel_x: float,
        hosel_y: float,
        golfer_bbox: tuple[float, float, float, float],
    ) -> Optional[dict]:
        """Detect the clubhead region near the hosel and return its center.

        Used to get accurate X position for the ball (center of clubhead face).
        The Y position comes from the hosel (ground level).

        Args:
            frame: Full BGR frame
            hosel_x: X coordinate of hosel (shaft endpoint)
            hosel_y: Y coordinate of hosel
            golfer_bbox: (x1, y1, x2, y2) golfer bounding box

        Returns:
            Dict with x, y of clubhead center, or None if not found
        """
        gx1, gy1, gx2, gy2 = [int(v) for v in golfer_bbox]
        frame_height, frame_width = frame.shape[:2]

        # Search region: small area around the hosel where clubhead should be
        # Clubhead extends to the right of the hosel (for RH golfer)
        # At 4K, clubhead is roughly 60-100px wide
        search_margin = 80
        roi_x1 = max(0, int(hosel_x - 20))  # Small margin left of hosel
        roi_x2 = min(frame_width, int(hosel_x + search_margin))  # Extend right
        roi_y1 = max(0, int(hosel_y - 40))  # Above hosel
        roi_y2 = min(frame_height, int(hosel_y + 40))  # Below hosel

        roi = frame[roi_y1:roi_y2, roi_x1:roi_x2]
        if roi.size == 0:
            return None

        # Convert to HSV for better color analysis
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)

        # Driver clubheads are typically:
        # - Black (matte): low value, low saturation
        # - Metallic silver: high value, low saturation
        # - White crown: very high value

        # Detect bright/metallic regions (driver crown or silver clubhead)
        v_channel = hsv[:, :, 2]
        s_channel = hsv[:, :, 1]

        # Mask 1: Bright regions (metallic/white)
        bright_mask = v_channel > 140

        # Mask 2: Low saturation (metallic, not grass)
        low_sat_mask = s_channel < 80

        # Combine: bright AND low saturation = likely clubhead
        clubhead_mask = (bright_mask & low_sat_mask).astype(np.uint8) * 255

        # Also detect very dark regions (matte black clubhead)
        dark_mask = (v_channel < 60).astype(np.uint8) * 255

        # Combine both possibilities
        combined_mask = cv2.bitwise_or(clubhead_mask, dark_mask)

        # Clean up with morphology
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        combined_mask = cv2.morphologyEx(combined_mask, cv2.MORPH_CLOSE, kernel)
        combined_mask = cv2.morphologyEx(combined_mask, cv2.MORPH_OPEN, kernel)

        # Find contours
        contours, _ = cv2.findContours(
            combined_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )

        # Find the best clubhead candidate
        candidates = []
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < 100 or area > 8000:  # Clubhead area range at 4K
                continue

            # Get bounding rect
            x, y, w, h = cv2.boundingRect(cnt)

            # Clubhead should be roughly as wide as tall or wider
            aspect_ratio = w / max(h, 1)
            if aspect_ratio < 0.5 or aspect_ratio > 4.0:
                continue

            # Get centroid
            M = cv2.moments(cnt)
            if M['m00'] == 0:
                continue
            cx = int(M['m10'] / M['m00'])
            cy = int(M['m01'] / M['m00'])

            # Convert to frame coordinates
            fx = roi_x1 + cx
            fy = roi_y1 + cy

            # Clubhead center should be to the right of hosel
            if fx < hosel_x:
                continue

            # Should be at similar Y level as hosel
            if abs(fy - hosel_y) > 30:
                continue

            candidates.append({
                'x': fx,
                'y': fy,
                'area': area,
                'width': w,
            })

        if not candidates:
            logger.debug("No clubhead region detected near hosel")
            return None

        # Pick the candidate closest to expected position (just right of hosel)
        # and with reasonable size
        best = max(candidates, key=lambda c: c['area'])

        logger.debug(
            f"Clubhead center detected at ({best['x']:.0f},{best['y']:.0f}), "
            f"area={best['area']:.0f}, width={best['width']:.0f}px"
        )

        return {
            'x': best['x'],
            'y': best['y'],
            'area': best['area'],
        }

    def _analyze_line_color(
        self,
        frame: np.ndarray,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        num_samples: int = 10,
    ) -> float:
        """Analyze color along a line to determine if it's a shaft or grass.

        The club shaft should be:
        - Dark (low brightness)
        - Not green (low green-dominance)
        - Metallic (grayish, low saturation)

        Grass is:
        - Bright green
        - High saturation in green channel

        Args:
            frame: Full BGR frame
            x1, y1: Start point
            x2, y2: End point
            num_samples: Number of points to sample along the line

        Returns:
            Score 0-1 where higher = more likely to be shaft, lower = more like grass
        """
        frame_height, frame_width = frame.shape[:2]
        samples = []

        for i in range(num_samples):
            t = i / max(num_samples - 1, 1)
            px = int(x1 + t * (x2 - x1))
            py = int(y1 + t * (y2 - y1))

            # Clamp to frame bounds
            px = max(0, min(frame_width - 1, px))
            py = max(0, min(frame_height - 1, py))

            # Get BGR color at this point
            b, g, r = frame[py, px]
            samples.append((b, g, r))

        if not samples:
            return 0.5

        # Analyze the samples
        total_brightness = 0

        for b, g, r in samples:
            brightness = (int(b) + int(g) + int(r)) / 3
            total_brightness += brightness

        avg_brightness = total_brightness / len(samples)

        # Score based primarily on darkness
        # Shaft is typically darker than grass
        # Grass brightness ~140-180, shaft ~100-130
        # Use a gentler curve so both can pass but darker is preferred
        if avg_brightness < 100:
            score = 1.0  # Very dark = definitely not grass
        elif avg_brightness < 130:
            score = 0.8  # Dark = likely shaft
        elif avg_brightness < 150:
            score = 0.5  # Medium = could be either
        elif avg_brightness < 180:
            score = 0.3  # Brighter = likely grass but possible
        else:
            score = 0.1  # Very bright = definitely grass

        return score

    def _detect_lines_multi_method(
        self,
        region: np.ndarray,
    ) -> Optional[list]:
        """Detect lines using multiple methods for robustness.

        Tries:
        1. LSD (Line Segment Detector) - often better for actual line segments
        2. Hough with enhanced preprocessing
        3. Hough with different parameters

        Returns list of (x1, y1, x2, y2) line segments.
        """
        gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
        all_lines = []

        # Method 1: LSD (Line Segment Detector)
        # LSD is generally better than Hough for detecting actual line segments
        try:
            lsd = cv2.createLineSegmentDetector(cv2.LSD_REFINE_STD)
            lsd_lines, _, _, _ = lsd.detect(gray)
            if lsd_lines is not None:
                for line in lsd_lines:
                    x1, y1, x2, y2 = line[0]
                    all_lines.append((int(x1), int(y1), int(x2), int(y2)))
                logger.debug(f"LSD found {len(lsd_lines)} line segments")
        except Exception as e:
            logger.debug(f"LSD detection failed: {e}")

        # Method 2: Enhanced Hough with preprocessing
        # Apply CLAHE (Contrast Limited Adaptive Histogram Equalization) to enhance edges
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray)

        # Bilateral filter to reduce noise while preserving edges
        filtered = cv2.bilateralFilter(enhanced, 9, 75, 75)

        # Multi-scale edge detection
        edges_low = cv2.Canny(filtered, 30, 100, apertureSize=3)
        edges_high = cv2.Canny(filtered, 50, 150, apertureSize=3)
        edges = cv2.bitwise_or(edges_low, edges_high)

        # Morphological closing to connect broken edge segments
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel)

        # Hough with different parameter sets
        for threshold, min_length, max_gap in [(20, 50, 20), (30, 80, 15), (15, 40, 25)]:
            hough_lines = cv2.HoughLinesP(
                edges,
                rho=1,
                theta=np.pi / 180,
                threshold=threshold,
                minLineLength=min_length,
                maxLineGap=max_gap,
            )
            if hough_lines is not None:
                for line in hough_lines:
                    x1, y1, x2, y2 = line[0]
                    all_lines.append((x1, y1, x2, y2))

        if all_lines:
            logger.debug(f"Total lines found: {len(all_lines)}")

        return all_lines if all_lines else None

    def _detect_ball_in_zone(
        self, frame: np.ndarray, zone: tuple[float, float, float, float]
    ) -> Optional[dict]:
        """Use YOLO to detect ball in a specific zone.

        Args:
            frame: Full frame
            zone: (x1, y1, x2, y2) search region

        Returns:
            Dict with ball position and confidence
        """
        # Run YOLO on full frame (more context helps detection)
        detection = self.ball_detector.detect_ball_in_frame(frame)

        if detection is None:
            logger.debug("No ball detected by YOLO")
            return None

        # Check if detection is within zone
        ball_x, ball_y = detection["center"]
        x1, y1, x2, y2 = zone

        if x1 <= ball_x <= x2 and y1 <= ball_y <= y2:
            logger.debug(
                f"Ball detected in zone at ({ball_x:.0f},{ball_y:.0f}), "
                f"conf={detection['confidence']:.3f}"
            )
            return {
                "x": ball_x,
                "y": ball_y,
                "confidence": detection["confidence"],
            }

        logger.debug(
            f"Ball detected at ({ball_x:.0f},{ball_y:.0f}) but outside zone"
        )
        return None

    def _zone_around_point(
        self,
        x: float,
        y: float,
        radius: float,
        frame_width: int,
        frame_height: int,
    ) -> tuple[float, float, float, float]:
        """Create a search zone around a point."""
        return (
            max(0, x - radius),
            max(0, y - radius),
            min(frame_width, x + radius),
            min(frame_height, y + radius),
        )

    def _combine_detections(
        self,
        golfer_result: Optional[dict],
        shaft_result: Optional[dict],
        ball_result: Optional[dict],
        frame_width: int,
        frame_height: int,
    ) -> Optional[OriginDetection]:
        """Combine results from multiple detection methods.

        Priority:
        1. If ball detected by YOLO → use that (most direct)
        2. If shaft endpoint found → use that
        3. If only golfer found → estimate from feet position

        Confidence increases if multiple methods agree.
        """
        candidates = []
        methods = []

        if ball_result:
            candidates.append((ball_result["x"], ball_result["y"]))
            methods.append("yolo_ball")

        if shaft_result:
            # Shaft detection points directly to the clubhead/ball position
            # This is the primary method - the bottom of the shaft IS where the ball is
            candidates.append((shaft_result["x"], shaft_result["y"]))
            methods.append("shaft")

        # DO NOT use golfer_feet percentage-based estimate as fallback
        # The user explicitly requested: "DO NOT USE A % OF THE HEIGHT OR WIDTH
        # OF THE GOLFER TO APPROXIMATE THE BALL POSITION"
        # If shaft detection fails, we should return None rather than guess

        if not candidates:
            logger.debug("No origin candidates found by any method")
            return None

        # Check for agreement between methods
        if len(candidates) >= 2:
            # Calculate pairwise distances
            agreements = []
            for i in range(len(candidates)):
                for j in range(i + 1, len(candidates)):
                    dist = np.sqrt(
                        (candidates[i][0] - candidates[j][0]) ** 2 +
                        (candidates[i][1] - candidates[j][1]) ** 2
                    )
                    if dist < self.AGREEMENT_DISTANCE:
                        agreements.append((i, j, dist))

            if agreements:
                # Methods agree - average the agreeing positions
                agreeing_indices = set()
                for i, j, _ in agreements:
                    agreeing_indices.add(i)
                    agreeing_indices.add(j)

                agreeing_positions = [candidates[i] for i in agreeing_indices]
                final_x = sum(p[0] for p in agreeing_positions) / len(agreeing_positions)
                final_y = sum(p[1] for p in agreeing_positions) / len(agreeing_positions)

                agreeing_methods = [methods[i] for i in agreeing_indices]
                confidence = min(1.0, 0.5 + 0.2 * len(agreeing_methods))

                logger.info(
                    f"Ball origin: ({final_x:.0f},{final_y:.0f}) - "
                    f"methods agree: {agreeing_methods}, confidence={confidence:.2f}"
                )

                return OriginDetection(
                    x=final_x,
                    y=final_y,
                    confidence=confidence,
                    method="+".join(agreeing_methods),
                    golfer_bbox=golfer_result["bbox"] if golfer_result else None,
                )

        # No agreement - use priority order
        if ball_result:
            # Direct YOLO detection is most reliable
            confidence = min(0.7, ball_result["confidence"] * 5)  # Scale up low YOLO conf
            method = "yolo_ball"
            x, y = ball_result["x"], ball_result["y"]
        elif shaft_result:
            # Shaft detection points directly to the clubhead/ball
            # The bottom of the shaft at address IS where the ball is
            confidence = 0.65
            method = "shaft"
            x, y = shaft_result["x"], shaft_result["y"]
        else:
            # No valid detection - return None instead of guessing
            # DO NOT use percentage-based estimates from golfer position
            logger.warning(
                "Ball origin detection failed: no shaft or ball detected. "
                "Shaft detection is required for accurate tracer placement."
            )
            return None

        logger.info(
            f"Ball origin: ({x:.0f},{y:.0f}) - method={method}, confidence={confidence:.2f}"
        )

        return OriginDetection(
            x=x,
            y=y,
            confidence=confidence,
            method=method,
            golfer_bbox=golfer_result["bbox"] if golfer_result else None,
        )
