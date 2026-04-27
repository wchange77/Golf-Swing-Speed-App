import XCTest
@testable import GolfBallDetectionApp

final class BallDatasetBridgeTests: XCTestCase {
    func testDefaultManifestPathContainsDatasetProject() {
        XCTAssertTrue(BallDatasetBridge.manifestPath().contains("DatasetCollectionPlatform"))
    }
}
