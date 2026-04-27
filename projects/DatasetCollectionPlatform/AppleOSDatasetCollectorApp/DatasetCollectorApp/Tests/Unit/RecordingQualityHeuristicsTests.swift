import XCTest
@testable import DatasetCollectorApp

final class RecordingQualityHeuristicsTests: XCTestCase {
    func testFrameStatsForStable240FPS() {
        let timestamps = (0..<241).map { Double($0) / 240.0 }

        let stats = RecordingQualityHeuristics.makeFrameStats(timestamps)

        XCTAssertEqual(stats.duration, 1.0, accuracy: 0.0001)
        XCTAssertEqual(stats.estimatedFPS, 240.0, accuracy: 0.001)
        XCTAssertLessThan(stats.jitterRatio, 0.001)
        XCTAssertEqual(stats.intervalCount, 240)
    }

    func testFrameStatsDetectsJitter() {
        let timestamps = [0.0, 0.004, 0.008, 0.020, 0.024, 0.028]

        let stats = RecordingQualityHeuristics.makeFrameStats(timestamps)

        XCTAssertGreaterThan(stats.jitterRatio, 0.3)
    }

    func testSwingWindowRequiresEnoughFramesAndDuration() {
        XCTAssertTrue(
            RecordingQualityHeuristics.hasSwingWindowCandidate(
                frameCount: 180,
                durationSeconds: 0.75,
                minFrameCount: 120,
                minDurationSeconds: 0.25
            )
        )
        XCTAssertFalse(
            RecordingQualityHeuristics.hasSwingWindowCandidate(
                frameCount: 60,
                durationSeconds: 0.75,
                minFrameCount: 120,
                minDurationSeconds: 0.25
            )
        )
    }
}
