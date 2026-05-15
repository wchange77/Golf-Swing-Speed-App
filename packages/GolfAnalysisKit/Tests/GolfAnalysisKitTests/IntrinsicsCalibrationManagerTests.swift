import XCTest
@testable import GolfAnalysisKit

final class IntrinsicsCalibrationManagerTests: XCTestCase {
    func testLoadIntrinsicsFromTopLevel() throws {
        let json = """
        {
            "intrinsics": {
                "fx": 1560.0,
                "fy": 1560.0,
                "cx": 960.0,
                "cy": 540.0,
                "referenceWidth": 1920,
                "referenceHeight": 1080,
                "capturedAt": "2026-05-09T12:00:00Z"
            }
        }
        """.data(using: .utf8)!
        let sample = try IntrinsicsCalibrationManager.loadIntrinsics(fromJSON: json)
        XCTAssertEqual(sample.fx, 1560.0, accuracy: 0.0001)
        XCTAssertEqual(sample.referenceWidth, 1920)
    }

    func testLoadIntrinsicsFromCalibrationBlock() throws {
        let json = """
        {
            "calibration": {
                "intrinsics": {
                    "fx": 1600.0, "fy": 1600.0, "cx": 960.0, "cy": 540.0,
                    "referenceWidth": 1920, "referenceHeight": 1080
                }
            }
        }
        """.data(using: .utf8)!
        let sample = try IntrinsicsCalibrationManager.loadIntrinsics(fromJSON: json)
        XCTAssertEqual(sample.fx, 1600.0, accuracy: 0.0001)
        XCTAssertNil(sample.capturedAt)
    }

    func testMissingIntrinsicsThrows() {
        let json = "{}".data(using: .utf8)!
        XCTAssertThrowsError(try IntrinsicsCalibrationManager.loadIntrinsics(fromJSON: json))
    }

    func testPixelsPerMetre() {
        let sample = GolfIntrinsicsSample(
            fx: 1600, fy: 1600, cx: 960, cy: 540,
            referenceWidth: 1920, referenceHeight: 1080
        )
        XCTAssertEqual(sample.pixelsPerMetre(atDistanceMeters: 2.0) ?? 0, 800, accuracy: 0.0001)
        XCTAssertNil(sample.pixelsPerMetre(atDistanceMeters: 0))
    }
}
