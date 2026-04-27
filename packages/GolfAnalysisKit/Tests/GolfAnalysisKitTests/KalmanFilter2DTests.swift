import XCTest
@testable import GolfAnalysisKit

final class KalmanFilter2DTests: XCTestCase {

    func testInitialPosition() {
        let kf = KalmanFilter2D(initialPosition: CGPoint(x: 100, y: 200))
        XCTAssertEqual(kf.position.x, 100, accuracy: 0.01)
        XCTAssertEqual(kf.position.y, 200, accuracy: 0.01)
        XCTAssertFalse(kf.isTrackLost)
    }

    func testPredictMovesState() {
        var kf = KalmanFilter2D(
            initialPosition: CGPoint(x: 100, y: 200),
            initialVelocity: CGPoint(x: 10, y: -5)
        )
        kf.predict(dt: 1.0)
        XCTAssertEqual(kf.position.x, 110, accuracy: 1.0)
        XCTAssertEqual(kf.position.y, 195, accuracy: 1.0)
    }

    func testUpdateCorrects() {
        var kf = KalmanFilter2D(initialPosition: CGPoint(x: 100, y: 200))
        kf.predict(dt: 0.01)
        kf.update(measurement: CGPoint(x: 105, y: 198))
        XCTAssertEqual(kf.framesWithoutDetection, 0)
    }

    func testTrackLostAfterMaxFrames() {
        var kf = KalmanFilter2D(initialPosition: CGPoint(x: 100, y: 200))
        for _ in 0...KalmanFilter2D.maxPredictionFrames {
            kf.predict(dt: 0.01)
        }
        XCTAssertTrue(kf.isTrackLost)
    }

    func testSpeedCalculatorInstantaneous() {
        let p1 = TrackedPosition(
            frameTimestamp: 0.0,
            position2D: CGPoint(x: 0, y: 0),
            confidence: 1.0,
            source: .yoloDetection
        )
        let p2 = TrackedPosition(
            frameTimestamp: 1.0,
            position2D: CGPoint(x: 100, y: 0),
            confidence: 1.0,
            source: .yoloDetection
        )
        let cal = CalibrationSnapshot(
            method: .manual,
            pixelsPerMetre: 100.0,
            impactZoneX: 0,
            impactZoneY: 0
        )
        let speed = SpeedCalculator.instantaneousSpeed(from: p1, to: p2, calibration: cal)
        XCTAssertNotNil(speed)
        XCTAssertEqual(speed!, GolfConstants.Speed.metersPerSecondToMph, accuracy: 0.01)
    }
}
