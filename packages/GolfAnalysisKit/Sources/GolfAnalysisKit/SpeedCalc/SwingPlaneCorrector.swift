import Foundation
import simd

public struct SwingPlaneCorrector {

    public struct SwingPlaneModel: Sendable {
        public let planeNormal: SIMD3<Float>
        public let planeOrigin: SIMD3<Float>
        public let arcRadius: Float
        public let pivotPoint: SIMD3<Float>
        public let cameraPosition: SIMD3<Float>
        public let cameraDistance: Float

        public init(
            planeNormal: SIMD3<Float>,
            planeOrigin: SIMD3<Float>,
            arcRadius: Float,
            pivotPoint: SIMD3<Float>,
            cameraPosition: SIMD3<Float>,
            cameraDistance: Float
        ) {
            self.planeNormal = planeNormal
            self.planeOrigin = planeOrigin
            self.arcRadius = arcRadius
            self.pivotPoint = pivotPoint
            self.cameraPosition = cameraPosition
            self.cameraDistance = cameraDistance
        }
    }

    public static func buildSwingPlane(
        leadShoulder: SIMD3<Float>,
        leadWrist: SIMD3<Float>,
        clubHead: SIMD3<Float>,
        spine: SIMD3<Float>,
        cameraDistance: Float
    ) -> SwingPlaneModel {
        let v1 = leadWrist - spine
        let v2 = clubHead - spine

        var normal = simd_cross(v1, v2)
        let normalLength = simd_length(normal)
        if normalLength > 0 {
            normal = normal / normalLength
        } else {
            normal = SIMD3<Float>(0, 0.707, 0.707)
        }

        let arcRadius = simd_distance(leadShoulder, clubHead)
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

    public static func buildDefaultSwingPlane(
        clubLengthMetres: Float,
        cameraDistanceMetres: Float = 2.5,
        swingPlaneTiltDegrees: Float = 48,
        clubType: ClubType? = nil
    ) -> SwingPlaneModel {
        let planeAngle: Float
        if let club = clubType {
            planeAngle = Float(GolfConstants.SwingPlane.angle(for: club))
        } else {
            planeAngle = swingPlaneTiltDegrees
        }
        let tiltRadians = planeAngle * .pi / 180.0

        let normal = SIMD3<Float>(0, sin(tiltRadians), cos(tiltRadians))
        let shoulderHeight: Float = 1.45
        let pivotPoint = SIMD3<Float>(0, shoulderHeight, 0)
        let wristAtAddress = SIMD3<Float>(0, 0.9, 0.3)
        let armLength: Float = 0.7
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

    public static func speedCorrectionFactor(
        trackedPosition2D: CGPoint,
        imageWidth: Int,
        imageHeight: Int,
        plane: SwingPlaneModel
    ) -> Double {
        let nx = Float(trackedPosition2D.x) / Float(imageWidth) * 2.0 - 1.0
        let ny = Float(trackedPosition2D.y) / Float(imageHeight) * 2.0 - 1.0

        let rayDir = simd_normalize(SIMD3<Float>(nx * 0.5, -ny * 0.5, -1.0))
        let denom = simd_dot(plane.planeNormal, rayDir)
        guard abs(denom) > 0.001 else { return 1.0 }

        let t = simd_dot(plane.planeNormal, plane.planeOrigin - plane.cameraPosition) / denom
        let point3D = plane.cameraPosition + t * rayDir

        let radiusVector = point3D - plane.pivotPoint
        let tangentDir = simd_normalize(simd_cross(plane.planeNormal, radiusVector))
        let viewDir = simd_normalize(point3D - plane.cameraPosition)

        let tangentAlongView = simd_dot(tangentDir, viewDir) * viewDir
        let visibleTangent = tangentDir - tangentAlongView
        let visibleComponent = simd_length(visibleTangent)

        let clampedVisible = Swift.max(0.3, Swift.min(1.0, visibleComponent))
        return Double(1.0 / clampedVisible)
    }

    public static func impactZoneCorrectionFactor(
        plane: SwingPlaneModel
    ) -> Double {
        let impactTangentDir = SIMD3<Float>(1, 0, 0)
        let viewDir = SIMD3<Float>(0, 0, -1)

        let visibleComponent = abs(simd_dot(impactTangentDir, simd_cross(viewDir, SIMD3<Float>(0, 1, 0))))
        let clamped = Swift.max(0.5, Swift.min(1.0, visibleComponent))
        return Double(1.0 / clamped)
    }

    public static func perspectiveScaleCorrection(
        depthAtCalibration: Float,
        depthAtMeasurement: Float
    ) -> Double {
        guard depthAtCalibration > 0, depthAtMeasurement > 0 else { return 1.0 }
        return Double(depthAtCalibration / depthAtMeasurement)
    }

    public static func correctedSpeed(
        from position1: TrackedPosition,
        to position2: TrackedPosition,
        calibration: CalibrationSnapshot,
        plane: SwingPlaneModel?,
        imageWidth: Int = 1920,
        imageHeight: Int = 1080
    ) -> Double? {
        guard let baseSpeed = SpeedCalculator.instantaneousSpeed(
            from: position1, to: position2, calibration: calibration
        ) else {
            return nil
        }

        guard let plane else { return baseSpeed }

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
