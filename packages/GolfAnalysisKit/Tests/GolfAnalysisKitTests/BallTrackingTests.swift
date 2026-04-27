import XCTest
@testable import GolfAnalysisKit

final class KalmanFilter6DTests: XCTestCase {

    func testInitialize() {
        var kf = KalmanFilter6D()
        kf.initialize(position: CGPoint(x: 100, y: 200), velocity: CGPoint(x: 10, y: -20))
        XCTAssertTrue(kf.isInitialized)
        XCTAssertFalse(kf.isTrackLost)

        let state = kf.currentState!
        XCTAssertEqual(state.x, 100, accuracy: 0.01)
        XCTAssertEqual(state.y, 200, accuracy: 0.01)
        XCTAssertEqual(state.vx, 10, accuracy: 0.01)
        XCTAssertEqual(state.vy, -20, accuracy: 0.01)
    }

    func testPredictMovesPosition() {
        var kf = KalmanFilter6D()
        kf.initialize(
            position: CGPoint(x: 100, y: 200),
            velocity: CGPoint(x: 50, y: -30),
            acceleration: CGPoint(x: 0, y: 10)
        )

        let prediction = kf.predict(dt: 0.01)
        XCTAssertNotNil(prediction)

        let state = kf.currentState!
        XCTAssertGreaterThan(state.x, 100)
        XCTAssertLessThan(state.y, 200)
    }

    func testUpdateCorrects() {
        var kf = KalmanFilter6D()
        kf.initialize(position: CGPoint(x: 100, y: 200))
        _ = kf.predict(dt: 0.01)
        kf.update(measurement: CGPoint(x: 105, y: 198))
        XCTAssertEqual(kf.framesWithoutDetection, 0)

        let state = kf.currentState!
        XCTAssertEqual(state.x, 105, accuracy: 5)
        XCTAssertEqual(state.y, 198, accuracy: 5)
    }

    func testTrackLostAfterMaxFrames() {
        var kf = KalmanFilter6D(config: .init(maxPredictionFrames: 5))
        kf.initialize(position: CGPoint(x: 100, y: 200))
        for _ in 0...6 {
            _ = kf.predict(dt: 0.01)
        }
        XCTAssertTrue(kf.isTrackLost)
    }

    func testMahalanobisRejectsOutlier() {
        var kf = KalmanFilter6D(config: .init(mahalanobisThreshold: 3.0))
        kf.initialize(position: CGPoint(x: 100, y: 200))
        _ = kf.predict(dt: 0.01)

        let plausible = kf.isMeasurementPlausible(CGPoint(x: 102, y: 199))
        XCTAssertTrue(plausible)

        let outlier = kf.isMeasurementPlausible(CGPoint(x: 500, y: 500))
        XCTAssertFalse(outlier)
    }

    func testGravityAffectsVertical() {
        var kf = KalmanFilter6D(config: .init(gravityPixelsPerS2: 1000))
        kf.initialize(
            position: CGPoint(x: 100, y: 100),
            velocity: CGPoint(x: 0, y: 0)
        )

        for _ in 0..<10 {
            _ = kf.predict(dt: 0.01)
        }

        let state = kf.currentState!
        XCTAssertGreaterThan(state.y, 100, "Gravity should move ball downward (increasing y)")
    }

    func testReset() {
        var kf = KalmanFilter6D()
        kf.initialize(position: CGPoint(x: 100, y: 200))
        kf.reset()
        XCTAssertFalse(kf.isInitialized)
        XCTAssertNil(kf.currentState)
    }
}

final class BallSpeedCalculatorTests: XCTestCase {

    func testSmashFactor() {
        XCTAssertEqual(BallSpeedCalculator.smashFactor(for: .driver), 1.49)
        XCTAssertEqual(BallSpeedCalculator.smashFactor(for: .sevenIron), 1.29)
    }

    func testEstimatedBallSpeed() {
        let speed = BallSpeedCalculator.estimatedBallSpeed(clubHeadSpeedMph: 100, club: .driver)
        XCTAssertEqual(speed, 149, accuracy: 0.01)
    }

    func testLaunchAngle() {
        let positions = [
            TrackedPosition(frameTimestamp: 0, position2D: CGPoint(x: 100, y: 200), confidence: 1.0, source: .yoloDetection),
            TrackedPosition(frameTimestamp: 0.004, position2D: CGPoint(x: 110, y: 190), confidence: 1.0, source: .yoloDetection),
        ]
        let cal = CalibrationSnapshot(method: .manual, pixelsPerMetre: 100, impactZoneX: 0, impactZoneY: 0)
        let angle = BallSpeedCalculator.calculateLaunchAngle(positions: positions, calibration: cal)
        XCTAssertGreaterThan(angle, 0, "Ball moving up should have positive launch angle")
        XCTAssertLessThan(angle, 90)
    }

    func testCalculateBallFlight() {
        let positions = (0..<5).map { i in
            TrackedPosition(
                frameTimestamp: Double(i) * 0.004,
                position2D: CGPoint(x: 100 + Double(i) * 20, y: 200 - Double(i) * 10),
                confidence: 0.9,
                source: .yoloDetection
            )
        }
        let cal = CalibrationSnapshot(method: .manual, pixelsPerMetre: 100, impactZoneX: 0, impactZoneY: 0)
        let metrics = BallSpeedCalculator.calculateBallFlight(positions: positions, calibration: cal)
        XCTAssertNotNil(metrics)
        XCTAssertGreaterThan(metrics!.ballSpeedMph, 0)
        XCTAssertGreaterThan(metrics!.launchAngleDegrees, 0)
        XCTAssertEqual(metrics!.trackedFrameCount, 5)
    }

    func testTooFewPositionsReturnsNil() {
        let positions = [
            TrackedPosition(frameTimestamp: 0, position2D: CGPoint(x: 100, y: 200), confidence: 1.0, source: .yoloDetection),
        ]
        let cal = CalibrationSnapshot(method: .manual, pixelsPerMetre: 100, impactZoneX: 0, impactZoneY: 0)
        let metrics = BallSpeedCalculator.calculateBallFlight(positions: positions, calibration: cal)
        XCTAssertNil(metrics)
    }
}
