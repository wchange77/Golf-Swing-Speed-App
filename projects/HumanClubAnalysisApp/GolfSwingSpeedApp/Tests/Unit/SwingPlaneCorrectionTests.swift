import Testing
import Foundation
import simd
@testable import GolfSwingSpeedApp

@Suite("Swing Plane Correction Tests")
struct SwingPlaneCorrectionTests {

    // MARK: - Swing Plane Model Construction

    @Test("Default swing plane has valid normal vector")
    func defaultSwingPlaneNormal() {
        let plane = SwingPlaneCorrector.buildDefaultSwingPlane(
            clubLengthMetres: 1.14,
            cameraDistanceMetres: 2.5,
            swingPlaneTiltDegrees: 48
        )

        let normalLength = simd_length(plane.planeNormal)
        #expect(abs(normalLength - 1.0) < 0.01, "Plane normal should be unit vector")
    }

    @Test("Default swing plane arc radius includes arm + club length")
    func defaultArcRadius() {
        let clubLength: Float = 1.14 // Driver
        let plane = SwingPlaneCorrector.buildDefaultSwingPlane(
            clubLengthMetres: clubLength
        )

        // Arc radius should be arm length (~0.7m) + club length
        #expect(plane.arcRadius > clubLength, "Arc radius must exceed club length (includes arm)")
        #expect(plane.arcRadius < 2.5, "Arc radius should be less than 2.5m total")
    }

    @Test("Build swing plane from 3D calibration points")
    func buildSwingPlaneFrom3D() {
        let shoulder = SIMD3<Float>(0, 1.5, 0)
        let wrist = SIMD3<Float>(0.3, 0.9, 0.3)
        let clubHead = SIMD3<Float>(0.5, 0.0, 0.5)
        let spine = SIMD3<Float>(0, 1.2, 0)

        let plane = SwingPlaneCorrector.buildSwingPlane(
            leadShoulder: shoulder,
            leadWrist: wrist,
            clubHead: clubHead,
            spine: spine,
            cameraDistance: 2.5
        )

        // Normal should be unit vector
        let normalLength = simd_length(plane.planeNormal)
        #expect(abs(normalLength - 1.0) < 0.01)

        // Arc radius should be shoulder-to-clubhead distance
        let expectedRadius = simd_distance(shoulder, clubHead)
        #expect(abs(plane.arcRadius - expectedRadius) < 0.01)
    }

    // MARK: - Speed Correction Factor

    @Test("Speed correction factor is always >= 1.0")
    func correctionFactorMinimum() {
        let plane = SwingPlaneCorrector.buildDefaultSwingPlane(clubLengthMetres: 1.14)

        // Test at various positions across the image
        let positions: [CGPoint] = [
            CGPoint(x: 960, y: 540),  // Center
            CGPoint(x: 200, y: 300),  // Top-left
            CGPoint(x: 1700, y: 800), // Bottom-right
            CGPoint(x: 960, y: 100),  // Top-center
            CGPoint(x: 960, y: 900),  // Bottom-center
        ]

        for pos in positions {
            let factor = SwingPlaneCorrector.speedCorrectionFactor(
                trackedPosition2D: pos,
                imageWidth: 1920,
                imageHeight: 1080,
                plane: plane
            )

            #expect(factor >= 1.0, "Correction factor must be >= 1.0 (2D always underestimates). Got \(factor) at \(pos)")
        }
    }

    @Test("Impact zone correction is close to 1.0 for front-on camera")
    func impactZoneCorrectionNearUnity() {
        let plane = SwingPlaneCorrector.buildDefaultSwingPlane(clubLengthMetres: 1.14)

        let correction = SwingPlaneCorrector.impactZoneCorrectionFactor(plane: plane)

        // For a front-on camera, impact zone should be close to 1.0
        // (club moves mostly perpendicular to camera at impact)
        #expect(correction >= 0.9 && correction <= 1.5,
                "Impact zone correction should be near 1.0, got \(correction)")
    }

    // MARK: - Perspective Correction

    @Test("Perspective correction is 1.0 when depth matches calibration")
    func perspectiveCorrectionAtCalibrationDepth() {
        let correction = SwingPlaneCorrector.perspectiveScaleCorrection(
            depthAtCalibration: 2.5,
            depthAtMeasurement: 2.5
        )

        #expect(abs(correction - 1.0) < 0.001)
    }

    @Test("Closer objects get correction > 1.0")
    func perspectiveCorrectionCloser() {
        let correction = SwingPlaneCorrector.perspectiveScaleCorrection(
            depthAtCalibration: 2.5,
            depthAtMeasurement: 2.0 // Closer than calibration
        )

        #expect(correction > 1.0, "Closer objects appear larger, correction should be > 1.0")
    }

    @Test("Farther objects get correction < 1.0")
    func perspectiveCorrectionFarther() {
        let correction = SwingPlaneCorrector.perspectiveScaleCorrection(
            depthAtCalibration: 2.5,
            depthAtMeasurement: 3.0 // Farther than calibration
        )

        #expect(correction < 1.0, "Farther objects appear smaller, correction should be < 1.0")
    }

    @Test("Perspective correction handles zero depth gracefully")
    func perspectiveCorrectionZeroDepth() {
        let correction = SwingPlaneCorrector.perspectiveScaleCorrection(
            depthAtCalibration: 0,
            depthAtMeasurement: 2.5
        )

        #expect(correction == 1.0, "Zero calibration depth should return 1.0")
    }

    // MARK: - Corrected Speed

    @Test("Corrected speed without plane returns base speed")
    func correctedSpeedWithoutPlane() {
        let calibration = CalibrationSnapshot(
            method: .manual,
            pixelsPerMetre: 500.0,
            impactZoneX: 960,
            impactZoneY: 540
        )

        let p1 = TrackedPosition(
            frameTimestamp: 1.000,
            position2D: CGPoint(x: 100, y: 100),
            position3D: nil,
            confidence: 0.9,
            source: .visionTracking
        )

        let p2 = TrackedPosition(
            frameTimestamp: 1.005,
            position2D: CGPoint(x: 140, y: 100),
            position3D: nil,
            confidence: 0.9,
            source: .visionTracking
        )

        let baseSpeed = SpeedCalculator.instantaneousSpeed(from: p1, to: p2, calibration: calibration)
        let correctedSpeed = SwingPlaneCorrector.correctedSpeed(
            from: p1, to: p2, calibration: calibration, plane: nil
        )

        #expect(baseSpeed == correctedSpeed, "Without plane, corrected speed should equal base speed")
    }

    @Test("Corrected speed with plane is >= base speed")
    func correctedSpeedWithPlane() {
        let calibration = CalibrationSnapshot(
            method: .manual,
            pixelsPerMetre: 500.0,
            impactZoneX: 960,
            impactZoneY: 540
        )

        let plane = SwingPlaneCorrector.buildDefaultSwingPlane(clubLengthMetres: 1.14)

        let p1 = TrackedPosition(
            frameTimestamp: 1.000,
            position2D: CGPoint(x: 800, y: 600),
            position3D: nil,
            confidence: 0.9,
            source: .visionTracking
        )

        let p2 = TrackedPosition(
            frameTimestamp: 1.005,
            position2D: CGPoint(x: 850, y: 590),
            position3D: nil,
            confidence: 0.9,
            source: .visionTracking
        )

        let baseSpeed = SpeedCalculator.instantaneousSpeed(from: p1, to: p2, calibration: calibration)
        let correctedSpeed = SwingPlaneCorrector.correctedSpeed(
            from: p1, to: p2, calibration: calibration, plane: plane
        )

        #expect(correctedSpeed != nil)
        #expect(baseSpeed != nil)
        if let corrected = correctedSpeed, let base = baseSpeed {
            #expect(corrected >= base, "3D corrected speed should be >= 2D base speed")
        }
    }

    // MARK: - Physics Validation

    @Test("100 mph swing produces expected pixel displacement at typical calibration")
    func expectedPixelDisplacement() {
        // At 100 mph (44.7 m/s), at 240fps, club moves 0.186m per frame
        // At 500 pixels/metre, that's ~93 pixels per frame
        let speedMph = 100.0
        let speedMs = speedMph / AppConstants.Speed.metersPerSecondToMph
        let frameInterval = 1.0 / 240.0
        let distancePerFrame = speedMs * frameInterval
        let pixelsPerMetre = 500.0
        let pixelDisplacement = distancePerFrame * pixelsPerMetre

        #expect(pixelDisplacement > 80 && pixelDisplacement < 110,
                "100 mph should produce ~93 pixels displacement at 500 ppm, got \(pixelDisplacement)")
    }

    @Test("1 pixel error produces approximately 0.6-1.1 mph speed error")
    func pixelErrorToSpeedError() {
        // speed = pixel_distance / ppm / dt * mps_to_mph
        let ppm = 500.0
        let dt = 1.0 / 240.0
        let errorPixels = 1.0

        let speedErrorMs = errorPixels / ppm / dt
        let speedErrorMph = speedErrorMs * AppConstants.Speed.metersPerSecondToMph

        #expect(speedErrorMph > 0.5 && speedErrorMph < 1.5,
                "1 pixel error should produce ~1 mph speed error, got \(speedErrorMph)")
    }
}
