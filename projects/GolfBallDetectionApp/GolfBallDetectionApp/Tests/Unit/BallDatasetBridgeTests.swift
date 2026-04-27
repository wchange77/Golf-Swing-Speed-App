import XCTest
@testable import GolfBallDetectionApp

final class BallDatasetBridgeTests: XCTestCase {
    func testDefaultManifestPathContainsDatasetProject() {
        XCTAssertTrue(BallDatasetBridge.manifestPath().contains("DatasetCollectionPlatform"))
    }

    func testLoadsCurrentDatasetManifest() {
        let manifest = BallDatasetBridge.loadManifest()
        XCTAssertNotNil(manifest)
        XCTAssertGreaterThanOrEqual(BallDatasetBridge.ballSampleCount() ?? -1, 0)
    }
}
