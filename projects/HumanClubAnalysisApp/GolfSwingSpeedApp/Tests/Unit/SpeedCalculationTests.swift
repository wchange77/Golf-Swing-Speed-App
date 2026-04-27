import Testing
import Foundation
@testable import GolfSwingSpeedApp

@Suite("Speed Calculation Tests")
struct SpeedCalculationTests {

    @Test("Convert m/s to mph correctly")
    func metersPerSecondToMph() {
        let mps = 44.704 // 100 mph in m/s
        let mph = mps * AppConstants.Speed.metersPerSecondToMph
        #expect(abs(mph - 100.0) < 0.1)
    }

    @Test("Speed unit conversion - mph to km/h")
    func mphToKmh() {
        let result = SpeedUnit.kmh.convert(fromMph: 100.0)
        #expect(abs(result - 160.934) < 0.1)
    }

    @Test("Speed unit conversion - mph to m/s")
    func mphToMs() {
        let result = SpeedUnit.ms.convert(fromMph: 100.0)
        #expect(abs(result - 44.704) < 0.1)
    }

    @Test("Pixel-to-metre conversion with calibration")
    func pixelToMetreConversion() {
        let calibration = CalibrationSnapshot(
            method: .manual,
            pixelsPerMetre: 500.0, // 500 pixels per metre
            impactZoneX: 960,
            impactZoneY: 540
        )

        // 100 pixels should be 0.2 metres
        let distance = Double(100) / calibration.pixelsPerMetre
        #expect(abs(distance - 0.2) < 0.001)
    }

    @Test("Instantaneous speed calculation uses actual timestamps")
    func instantaneousSpeedUsesActualTimestamps() {
        let calibration = CalibrationSnapshot(
            method: .manual,
            pixelsPerMetre: 500.0,
            impactZoneX: 960,
            impactZoneY: 540
        )

        // Simulate two frames: 40 pixels apart, 0.005s apart (200fps actual)
        let p1 = TrackedPosition(
            frameTimestamp: 1.000,
            position2D: CGPoint(x: 100, y: 100),
            position3D: nil,
            confidence: 0.9,
            source: .yoloDetection
        )

        let p2 = TrackedPosition(
            frameTimestamp: 1.005, // 5ms later (actual timestamp, NOT assumed 1/240)
            position2D: CGPoint(x: 140, y: 100),
            position3D: nil,
            confidence: 0.9,
            source: .opticalFlow
        )

        let speed = SpeedCalculator.instantaneousSpeed(from: p1, to: p2, calibration: calibration)

        // 40px / 500ppm = 0.08m; 0.08m / 0.005s = 16 m/s = 35.8 mph
        #expect(speed != nil)
        if let speed {
            #expect(abs(speed - 35.8) < 0.5)
        }
    }

    @Test("CGPoint distance calculation")
    func pointDistance() {
        let p1 = CGPoint(x: 0, y: 0)
        let p2 = CGPoint(x: 3, y: 4)
        #expect(abs(p1.distance(to: p2) - 5.0) < 0.001)
    }

    @Test("Lag Retention Index thresholds")
    func lagRetentionThresholds() {
        // Good lag: LRI > 0.5
        #expect(0.6 > AppConstants.LagAnalysis.goodLagLRIThreshold)

        // Casting: LRI < 0.4
        #expect(0.3 < AppConstants.LagAnalysis.castingLRIThreshold)
    }

    @Test("Multi-frame regression matches expected speed")
    func multiFrameRegression() {
        let calibration = CalibrationSnapshot(
            method: .manual,
            pixelsPerMetre: 500.0,
            impactZoneX: 960,
            impactZoneY: 540
        )

        // Simulate 100 mph = 44.7 m/s = 22,350 px/s at 500 ppm
        // At 240fps, that's 93.1 px/frame
        let pixelsPerFrame: CGFloat = 93.1
        var positions: [TrackedPosition] = []
        for i in 0..<7 {
            let t = 1.0 + Double(i) / 240.0
            positions.append(TrackedPosition(
                frameTimestamp: t,
                position2D: CGPoint(x: 960 - CGFloat(i) * pixelsPerFrame, y: 540),
                position3D: nil,
                confidence: 0.9,
                source: .opticalFlow
            ))
        }

        let speed = SpeedCalculator.regressionSpeed(
            positions: positions,
            nearTimestamp: 1.012, // ~3rd frame
            calibration: calibration,
            windowFrames: 5
        )

        #expect(speed != nil)
        if let speed {
            #expect(abs(speed - 100.0) < 2.0,
                    "Regression speed should be ~100 mph for simulated data, got \(speed)")
        }
    }

    @Test("Regression handles noisy positions better than two-frame")
    func regressionVsTwoFrame() {
        let calibration = CalibrationSnapshot(
            method: .manual,
            pixelsPerMetre: 500.0,
            impactZoneX: 960,
            impactZoneY: 540
        )

        // Simulated positions with noise
        let basePixelsPerFrame: CGFloat = 93.1 // 100 mph
        var positions: [TrackedPosition] = []
        let noise: [CGFloat] = [0, 3, -5, 2, -4, 1, -3] // Pixel noise

        for i in 0..<7 {
            let t = 1.0 + Double(i) / 240.0
            positions.append(TrackedPosition(
                frameTimestamp: t,
                position2D: CGPoint(x: 960 - CGFloat(i) * basePixelsPerFrame + noise[i], y: 540),
                position3D: nil,
                confidence: 0.8,
                source: .opticalFlow
            ))
        }

        let regressionSpeed = SpeedCalculator.regressionSpeed(
            positions: positions,
            nearTimestamp: 1.012,
            calibration: calibration,
            windowFrames: 5
        )

        // Two-frame speed between two noisy adjacent frames
        let twoFrameSpeed = SpeedCalculator.instantaneousSpeed(
            from: positions[2], to: positions[3], calibration: calibration
        )

        // Regression should be closer to 100 mph than two-frame
        #expect(regressionSpeed != nil)
        #expect(twoFrameSpeed != nil)
        if let regression = regressionSpeed, let twoFrame = twoFrameSpeed {
            let regressionError = abs(regression - 100.0)
            let twoFrameError = abs(twoFrame - 100.0)
            #expect(regressionError <= twoFrameError + 1.0,
                    "Regression (\(regression)) should be at least as accurate as two-frame (\(twoFrame)) for noisy data")
        }
    }

    @Test("Speed loss per 10 degrees lag")
    func speedLossFromLag() {
        // Chu et al.: 10° retained lag ≈ 5 mph
        let degreesLost = 20.0
        let estimatedLoss = (degreesLost / 10.0) * AppConstants.LagAnalysis.speedLossPerTenDegreesLag
        #expect(abs(estimatedLoss - 10.0) < 0.001)
    }
}
