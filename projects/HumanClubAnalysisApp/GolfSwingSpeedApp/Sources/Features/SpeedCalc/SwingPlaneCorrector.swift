import Foundation
import simd

/// Corrects 2D tracked positions to account for 3D swing plane geometry.
///
/// The club head moves through a tilted plane (the swing plane). A front-on camera
/// sees only the 2D projection of this 3D arc. This corrector converts 2D pixel
/// positions back to 3D positions on the swing plane, giving true arc speed.
///
/// Key insight: at impact, the club moves roughly perpendicular to the camera axis
/// (toward the target), so the 2D measurement is most accurate where it matters most.
/// During backswing/downswing, the club has significant depth motion that 2D misses.
struct SwingPlaneCorrector {

    // MARK: - Swing Plane Model

    /// Defines the swing plane in 3D space.
    /// The swing plane passes through the golfer's spine and is tilted at an angle.
    struct SwingPlaneModel {
        /// Normal vector of the swing plane (unit vector)
        let planeNormal: SIMD3<Float>

        /// A point on the swing plane (typically the golfer's hands at address)
        let planeOrigin: SIMD3<Float>

        /// Swing arc radius in metres (from pivot point to club head)
        let arcRadius: Float

        /// Pivot point of the swing (approximately the lead shoulder)
        let pivotPoint: SIMD3<Float>

        /// Camera position in world coordinates
        let cameraPosition: SIMD3<Float>

        /// Camera-to-subject distance in metres
        let cameraDistance: Float
    }

    // MARK: - Create Swing Plane from Calibration

    /// Build a swing plane model from address position calibration data.
    ///
    /// - Parameters:
    ///   - leadShoulder: 3D position of lead shoulder (pivot point)
    ///   - leadWrist: 3D position of lead wrist at address
    ///   - clubHead: 3D position of club head at address
    ///   - spine: 3D position of spine/root joint
    ///   - cameraDistance: Distance from camera to golfer in metres
    static func buildSwingPlane(
        leadShoulder: SIMD3<Float>,
        leadWrist: SIMD3<Float>,
        clubHead: SIMD3<Float>,
        spine: SIMD3<Float>,
        cameraDistance: Float
    ) -> SwingPlaneModel {
        // Swing plane is defined by three points: spine, hands, club head
        let v1 = leadWrist - spine
        let v2 = clubHead - spine

        // Normal = cross product of two vectors in the plane
        var normal = simd_cross(v1, v2)
        let normalLength = simd_length(normal)
        if normalLength > 0 {
            normal = normal / normalLength
        } else {
            // Degenerate case — use a default tilted plane (45° from vertical)
            normal = SIMD3<Float>(0, 0.707, 0.707)
        }

        // Arc radius = distance from pivot (shoulder) to club head
        let arcRadius = simd_distance(leadShoulder, clubHead)

        // Camera assumed to be along the Z axis from the golfer
        let cameraPosition = SIMD3<Float>(0, 0, cameraDistance)

        return SwingPlaneModel(
            planeNormal: normal,
            planeOrigin: leadWrist,
            arcRadius: arcRadius,
            pivotPoint: leadShoulder,
            cameraPosition: cameraPosition,
            cameraDistance: cameraDistance
        )
    }

    /// Build a default swing plane model when no LiDAR data is available.
    /// Uses typical swing geometry assumptions from TrackMan data.
    ///
    /// - Parameters:
    ///   - clubLengthMetres: Known club length from calibration
    ///   - cameraDistanceMetres: Estimated camera-to-golfer distance
    ///   - swingPlaneTiltDegrees: Swing plane tilt from vertical (use AppConstants.SwingPlane.angle for club-specific)
    ///   - clubType: If provided, uses club-specific swing plane angle from TrackMan data
    static func buildDefaultSwingPlane(
        clubLengthMetres: Float,
        cameraDistanceMetres: Float = 2.5,
        swingPlaneTiltDegrees: Float = 48,
        clubType: ClubType? = nil
    ) -> SwingPlaneModel {
        // Use club-specific plane angle if club type is provided
        let planeAngle: Float
        if let club = clubType {
            planeAngle = Float(AppConstants.SwingPlane.angle(for: club))
        } else {
            planeAngle = swingPlaneTiltDegrees
        }
        let tiltRadians = planeAngle * .pi / 180.0

        // Default swing plane tilted toward the camera
        let normal = SIMD3<Float>(0, sin(tiltRadians), cos(tiltRadians))

        // Approximate positions based on typical golfer geometry
        let shoulderHeight: Float = 1.45 // metres
        let pivotPoint = SIMD3<Float>(0, shoulderHeight, 0)
        let wristAtAddress = SIMD3<Float>(0, 0.9, 0.3)

        // Arc radius ≈ arm length + club length
        let armLength: Float = 0.7 // typical lead arm length
        let arcRadius = armLength + clubLengthMetres

        let cameraPosition = SIMD3<Float>(0, 1.2, cameraDistanceMetres)

        return SwingPlaneModel(
            planeNormal: simd_normalize(normal),
            planeOrigin: wristAtAddress,
            arcRadius: arcRadius,
            pivotPoint: pivotPoint,
            cameraPosition: cameraPosition,
            cameraDistance: cameraDistanceMetres
        )
    }

    // MARK: - Speed Correction

    /// Calculate the speed correction factor for a given position in the swing arc.
    ///
    /// The correction accounts for the component of club head velocity along the
    /// camera axis (depth), which is invisible to 2D tracking.
    ///
    /// Returns a multiplier: true_speed = measured_2D_speed × correction_factor
    ///
    /// The correction is always ≥ 1.0 (2D speed always underestimates true 3D speed).
    static func speedCorrectionFactor(
        trackedPosition2D: CGPoint,
        imageWidth: Int,
        imageHeight: Int,
        plane: SwingPlaneModel
    ) -> Double {
        // Convert 2D pixel position to normalised image coordinates (-1 to 1)
        let nx = Float(trackedPosition2D.x) / Float(imageWidth) * 2.0 - 1.0
        let ny = Float(trackedPosition2D.y) / Float(imageHeight) * 2.0 - 1.0

        // Project the 2D point onto the swing plane to get estimated 3D position
        // Use the ray from camera through the image point
        let rayDir = simd_normalize(SIMD3<Float>(nx * 0.5, -ny * 0.5, -1.0))

        // Intersect ray with swing plane: plane.normal · (ray_origin + t * ray_dir - plane_origin) = 0
        let denom = simd_dot(plane.planeNormal, rayDir)
        guard abs(denom) > 0.001 else {
            // Ray parallel to plane — no correction possible
            return 1.0
        }

        let t = simd_dot(plane.planeNormal, plane.planeOrigin - plane.cameraPosition) / denom
        let point3D = plane.cameraPosition + t * rayDir

        // Calculate the velocity direction at this point on the arc
        // The velocity is tangent to the arc (perpendicular to radius vector from pivot)
        let radiusVector = point3D - plane.pivotPoint
        let tangentDir = simd_normalize(simd_cross(plane.planeNormal, radiusVector))

        // The correction factor depends on how much of the velocity is visible to the camera.
        // Camera sees velocity projected onto the image plane (perpendicular to view direction).
        let viewDir = simd_normalize(point3D - plane.cameraPosition)

        // Project tangent onto image plane: remove the component along the view direction
        let tangentAlongView = simd_dot(tangentDir, viewDir) * viewDir
        let visibleTangent = tangentDir - tangentAlongView
        let visibleComponent = simd_length(visibleTangent)

        // Correction factor = 1 / visible_component (clamped for stability)
        let clampedVisible = Swift.max(0.3, Swift.min(1.0, visibleComponent))
        return Double(1.0 / clampedVisible)
    }

    /// Calculate the average correction factor for the impact zone.
    ///
    /// For a front-on camera view, this is typically close to 1.0 since the
    /// club moves roughly perpendicular to the camera at impact.
    static func impactZoneCorrectionFactor(
        plane: SwingPlaneModel
    ) -> Double {
        // At impact, the club head is moving approximately toward the target
        // (perpendicular to the camera for a front-on view)
        let impactTangentDir = SIMD3<Float>(1, 0, 0) // Toward target
        let viewDir = SIMD3<Float>(0, 0, -1) // Camera looking at golfer

        let visibleComponent = abs(simd_dot(impactTangentDir, simd_cross(viewDir, SIMD3<Float>(0, 1, 0))))
        let clamped = Swift.max(0.5, Swift.min(1.0, visibleComponent))
        return Double(1.0 / clamped)
    }

    // MARK: - Perspective Correction

    /// Calculate the perspective scale correction at a given depth.
    ///
    /// Objects farther from the camera appear smaller. If the club head moves
    /// toward or away from the camera during the swing, the pixels-per-metre
    /// scale changes.
    ///
    /// Returns a multiplier to apply to the calibrated pixels-per-metre.
    static func perspectiveScaleCorrection(
        depthAtCalibration: Float,
        depthAtMeasurement: Float
    ) -> Double {
        guard depthAtCalibration > 0, depthAtMeasurement > 0 else { return 1.0 }
        // Perspective: apparent size is inversely proportional to depth
        // If object is closer, it appears larger (more pixels per metre)
        return Double(depthAtCalibration / depthAtMeasurement)
    }

    // MARK: - Corrected Speed Calculation

    /// Calculate corrected speed using swing plane model and perspective.
    ///
    /// - Parameters:
    ///   - position1: First tracked position (2D)
    ///   - position2: Second tracked position (2D)
    ///   - calibration: Calibration data with pixels-per-metre
    ///   - plane: Swing plane model (nil = no 3D correction)
    ///   - imageWidth: Frame width in pixels
    ///   - imageHeight: Frame height in pixels
    /// - Returns: Corrected speed in mph, or nil if calculation fails
    static func correctedSpeed(
        from position1: TrackedPosition,
        to position2: TrackedPosition,
        calibration: CalibrationSnapshot,
        plane: SwingPlaneModel?,
        imageWidth: Int = 1920,
        imageHeight: Int = 1080
    ) -> Double? {
        // Base 2D speed calculation
        guard let baseSpeed = SpeedCalculator.instantaneousSpeed(
            from: position1, to: position2, calibration: calibration
        ) else {
            return nil
        }

        // Apply 3D swing plane correction if available
        guard let plane else { return baseSpeed }

        // Use the midpoint position for correction factor
        let midpoint = CGPoint(
            x: (position1.position2D.x + position2.position2D.x) / 2,
            y: (position1.position2D.y + position2.position2D.y) / 2
        )

        let correction = speedCorrectionFactor(
            trackedPosition2D: midpoint,
            imageWidth: imageWidth,
            imageHeight: imageHeight,
            plane: plane
        )

        return baseSpeed * correction
    }
}
