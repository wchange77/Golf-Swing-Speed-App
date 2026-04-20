import Foundation
import XCTest
@testable import DatasetCollectorApp

final class DatasetCollectorServiceTests: XCTestCase {
    func testRegisterDuplicateSample() throws {
        let tempDir = FileManager.default.temporaryDirectory
            .appendingPathComponent("dataset-collector-tests-\(UUID().uuidString)", isDirectory: true)
        defer { try? FileManager.default.removeItem(at: tempDir) }

        let store = JSONLFileStore(customBaseDirectory: tempDir)
        let service = DatasetCollectorService(store: store)

        let session = try service.createSession(
            CreateSessionRequest(
                collector: "tester",
                device: "iPhone17Max",
                deviceProfile: "iphone17max",
                iosVersion: "iOS 26",
                appVersion: "0.1.0",
                notes: "test",
                fps: 240,
                resolution: "1920x1080",
                sceneType: "indoor",
                lighting: "indoor_led",
                tripod: true,
                distanceMeters: nil,
                targetDomains: [.humanClub]
            )
        )

        let metadata = CollectorSampleMetadata(
            fps: 240,
            resolution: "1920x1080",
            clubType: "driver",
            handedness: "right",
            swingIntensity: "normal",
            surface: "unknown"
        )

        let first = try service.registerMockSample(
            domain: .humanClub,
            activeSession: session,
            shotId: "shot_a",
            takeIndex: 1,
            tags: ["test"],
            metadata: metadata,
            payloadSeed: "same_seed"
        )
        XCTAssertNotNil(first)

        let second = try service.registerMockSample(
            domain: .humanClub,
            activeSession: session,
            shotId: "shot_b",
            takeIndex: 2,
            tags: ["test"],
            metadata: metadata,
            payloadSeed: "same_seed"
        )
        XCTAssertNil(second)

        let stats = try service.loadStats()
        XCTAssertEqual(stats.sessions, 1)
        XCTAssertEqual(stats.samples, 1)
        XCTAssertEqual(stats.duplicates, 1)
    }
}
