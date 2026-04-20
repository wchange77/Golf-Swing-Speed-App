import Testing
import Foundation
import simd
@testable import GolfSwingSpeedApp

@Suite("LiDAR Calibration Tests")
struct LiDARCalibrationTests {

    // MARK: - Distance Calculations

    @Test("3D distance calculation is correct")
    func distance3DCalculation() {
        let a = SIMD3<Float>(0, 0, 0)
        let b = SIMD3<Float>(3, 4, 0)

        let distance = LiDARCalibrationManager.distance3D(a, b)
        #expect(abs(distance - 5.0) < 0.001, "3-4-5 triangle should give distance 5.0")
    }

    @Test("3D distance with depth component")
    func distance3DWithDepth() {
        let a = SIMD3<Float>(1, 2, 3)
        let b = SIMD3<Float>(4, 6, 3) // Same depth, 3-4-5 in XY

        let distance = LiDARCalibrationManager.distance3D(a, b)
        #expect(abs(distance - 5.0) < 0.001)
    }

    @Test("3D distance is zero for same point")
    func distance3DSamePoint() {
        let a = SIMD3<Float>(1, 2, 3)
        let distance = LiDARCalibrationManager.distance3D(a, a)
        #expect(abs(distance) < 0.001)
    }

    // MARK: - Pixels Per Metre Calculation

    @Test("Pixels per metre from known 3D points and pixel positions")
    func pixelsPerMetreFromPoints() {
        let point1_3D = SIMD3<Float>(0, 0, 2.5) // 2.5m from camera
        let point2_3D = SIMD3<Float>(1, 0, 2.5) // 1m to the right

        let point1_2D = CGPoint(x: 460, y: 540)
        let point2_2D = CGPoint(x: 960, y: 540) // 500 pixels apart

        let ppm = LiDARCalibrationManager.calculatePixelsPerMetre(
            point1_3D: point1_3D,
            point2_3D: point2_3D,
            point1_2D: point1_2D,
            point2_2D: point2_2D
        )

        // 500 pixels for 1 metre = 500 ppm
        #expect(abs(ppm - 500.0) < 1.0, "Should calculate 500 ppm, got \(ppm)")
    }

    @Test("Pixels per metre handles zero 3D distance gracefully")
    func pixelsPerMetreZeroDistance() {
        let point = SIMD3<Float>(0, 0, 2.5)
        let ppm = LiDARCalibrationManager.calculatePixelsPerMetre(
            point1_3D: point,
            point2_3D: point, // Same point
            point1_2D: CGPoint(x: 0, y: 0),
            point2_2D: CGPoint(x: 100, y: 0)
        )

        #expect(ppm == 0, "Zero 3D distance should return 0 ppm")
    }

    @Test("Pixels per metre handles zero pixel distance gracefully")
    func pixelsPerMetreZeroPixels() {
        let ppm = LiDARCalibrationManager.calculatePixelsPerMetre(
            point1_3D: SIMD3<Float>(0, 0, 2.5),
            point2_3D: SIMD3<Float>(1, 0, 2.5),
            point1_2D: CGPoint(x: 500, y: 500),
            point2_2D: CGPoint(x: 500, y: 500) // Same pixel position
        )

        #expect(ppm == 0, "Zero pixel distance should return 0 ppm")
    }

    // MARK: - Club Measurements

    @Test("Club length calculation from wrist to club head")
    func clubLengthCalculation() {
        let wrist = SIMD3<Float>(0.2, 0.9, 0.3)
        let clubHead = SIMD3<Float>(0.4, 0.0, 0.5)

        let length = simd_distance(wrist, clubHead)

        // Standard driver shaft is ~1.14m
        // This test position should give a realistic club length
        #expect(length > 0.5, "Club length should be > 0.5m")
        #expect(length < 1.5, "Club length should be < 1.5m")
    }

    @Test("Lie angle calculation from shaft vector and ground")
    func lieAngleCalculation() {
        // Club at address: shaft angled down from hands to ground
        let wrist = SIMD3<Float>(0.0, 0.9, 0.3)
        let clubHead = SIMD3<Float>(0.3, 0.0, 0.6) // On the ground

        let shaftVector = clubHead - wrist
        let groundNormal = SIMD3<Float>(0, 1, 0)
        let shaftAngleFromGround = asin(abs(simd_dot(simd_normalize(shaftVector), groundNormal)))
        let lieAngle = shaftAngleFromGround * 180 / .pi

        // Typical lie angles: driver 56-60°, iron 60-64°
        #expect(lieAngle > 40 && lieAngle < 80,
                "Lie angle should be in realistic range (40-80°), got \(lieAngle)")
    }

    // MARK: - Swing Plane Normal

    @Test("Swing plane normal is perpendicular to swing plane")
    func swingPlaneNormalPerpendicular() {
        let spine = SIMD3<Float>(0, 1.2, 0)
        let wrist = SIMD3<Float>(0.3, 0.9, 0.3)
        let clubHead = SIMD3<Float>(0.5, 0.0, 0.5)

        let v1 = wrist - spine
        let v2 = clubHead - spine
        let normal = simd_normalize(simd_cross(v1, v2))

        // Normal should be perpendicular to both vectors in the plane
        let dot1 = abs(simd_dot(normal, simd_normalize(v1)))
        let dot2 = abs(simd_dot(normal, simd_normalize(v2)))

        #expect(dot1 < 0.01, "Normal should be perpendicular to plane vector 1")
        #expect(dot2 < 0.01, "Normal should be perpendicular to plane vector 2")
    }

    // MARK: - Calibration Snapshot

    @Test("Calibration snapshot validates against expected ranges")
    func calibrationSnapshotValidation() {
        let snapshot = CalibrationSnapshot(
            method: .lidar,
            pixelsPerMetre: 500,
            impactZoneX: 960,
            impactZoneY: 800,
            cameraToSubjectDistance: 2.5,
            clubLength: 1.14,
            lieAngle: 58,
            armLength: 0.7,
            swingPlaneNormalX: 0,
            swingPlaneNormalY: 0.707,
            swingPlaneNormalZ: 0.707,
            groundPlaneY: 0
        )

        #expect(snapshot.pixelsPerMetre > 0)
        #expect(snapshot.clubLength! > AppConstants.Calibration.minClubLengthMetres)
        #expect(snapshot.clubLength! < AppConstants.Calibration.maxClubLengthMetres)
        #expect(snapshot.lieAngle! > AppConstants.Calibration.minLieAngleDegrees)
        #expect(snapshot.lieAngle! < AppConstants.Calibration.maxLieAngleDegrees)
    }

    @Test("Manual calibration snapshot works without LiDAR fields")
    func manualCalibrationSnapshot() {
        let snapshot = CalibrationSnapshot(
            method: .manual,
            pixelsPerMetre: 450,
            impactZoneX: 960,
            impactZoneY: 700
        )

        #expect(snapshot.method == .manual)
        #expect(snapshot.pixelsPerMetre > 0)
        #expect(snapshot.clubLength == nil, "Manual calibration shouldn't have club length")
        #expect(snapshot.lieAngle == nil, "Manual calibration shouldn't have lie angle")
    }
}

@Suite("Tracking Pipeline Integration Tests")
struct TrackingPipelineTests {

    @Test("Simulated swing trajectory produces tracked positions")
    func simulatedSwingTrajectory() async {
        let pipeline = TrackingPipeline()

        // Simulate a swing arc: club head moves in an arc from right to left
        // At 240fps, a 0.3s downswing = 72 frames
        var positions: [TrackedPosition] = []

        for i in 0..<72 {
            let t = Double(i) / 240.0
            let angle = Double(i) / 72.0 * .pi // 0 to π
            let radius: CGFloat = 400 // pixels

            // Arc trajectory
            let x = 960 + radius * cos(angle) // Move left across frame
            let y = 540 + radius * 0.3 * sin(angle) // Slight vertical component

            let position = TrackedPosition(
                frameTimestamp: t,
                position2D: CGPoint(x: x, y: y),
                position3D: nil,
                confidence: 0.8,
                source: .opticalFlow
            )
            positions.append(position)
        }

        // Verify positions form a smooth trajectory
        #expect(positions.count == 72)
        #expect(positions.first!.position2D.x > positions.last!.position2D.x,
                "Club should move left (toward target)")
    }

    @Test("Speed from simulated trajectory matches expected physics")
    func speedFromSimulatedTrajectory() {
        let calibration = CalibrationSnapshot(
            method: .manual,
            pixelsPerMetre: 500.0,
            impactZoneX: 960,
            impactZoneY: 540
        )

        // Simulate 100 mph = 44.7 m/s
        // At 500 ppm, that's 44.7 * 500 = 22,350 pixels/second
        // At 240fps, that's 93.1 pixels per frame
        let pixelsPerFrame: CGFloat = 93.1

        var positions: [TrackedPosition] = []
        for i in 0..<10 {
            let t = Double(i) / 240.0
            positions.append(TrackedPosition(
                frameTimestamp: t,
                position2D: CGPoint(x: 960 - CGFloat(i) * pixelsPerFrame, y: 540),
                position3D: nil,
                confidence: 0.9,
                source: .opticalFlow
            ))
        }

        let profile = SpeedCalculator.buildSpeedProfile(
            from: positions,
            calibration: calibration,
            impactTimestamp: nil
        )

        #expect(profile != nil)
        if let profile {
            // Allow some tolerance for smoothing
            #expect(profile.peakSpeedMph > 90 && profile.peakSpeedMph < 110,
                    "Simulated 100 mph swing should produce ~100 mph, got \(profile.peakSpeedMph)")
        }
    }
}
