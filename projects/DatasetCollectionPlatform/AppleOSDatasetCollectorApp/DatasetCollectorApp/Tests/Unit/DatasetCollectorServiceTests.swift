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
                sessionName: "1",
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
                location: nil,
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

    func testRegisterVideoSampleWritesSidecarsAndExtendedMetadata() throws {
        let tempDir = FileManager.default.temporaryDirectory
            .appendingPathComponent("dataset-collector-tests-\(UUID().uuidString)", isDirectory: true)
        defer { try? FileManager.default.removeItem(at: tempDir) }

        let store = JSONLFileStore(customBaseDirectory: tempDir)
        let service = DatasetCollectorService(store: store)
        let session = try service.createSession(
            CreateSessionRequest(
                sessionName: "2",
                collector: "tester",
                device: "iPhone17Max",
                deviceProfile: "iphone17max",
                iosVersion: "iOS 26",
                appVersion: "0.1.0",
                notes: "sidecar test",
                fps: 240,
                resolution: "1920x1080",
                sceneType: "indoor",
                lighting: "indoor_led",
                tripod: true,
                distanceMeters: 4.0,
                location: CollectorLocation(
                    latitude: 37.3318,
                    longitude: -122.0312,
                    horizontalAccuracyMeters: 3.5,
                    altitudeMeters: 12.0,
                    verticalAccuracyMeters: 5.0,
                    capturedAt: "2026-04-24T00:00:00.000Z",
                    source: "unit_test"
                ),
                targetDomains: [.humanClub, .golfBallDetection]
            )
        )

        let videoURL = tempDir.appendingPathComponent("sample.mov")
        try Data("fake video payload".utf8).write(to: videoURL)
        let metrics = RecordingQualityMetrics(
            frameCount: 240,
            durationSeconds: 1.0,
            estimatedFPS: 240,
            frameRateJitterPercent: 1.2,
            sampledFrameCount: 5,
            humanDetectionRatio: 1.0,
            averageBodyCoverageRatio: 0.22,
            bodyCenterStability: 0.03,
            bodyBoundingBoxStability: 0.08,
            croppedBodyRatio: 0.0,
            averageSharpness: 20,
            averageBrightness: 120,
            underexposedPixelRatio: 0.01,
            overexposedPixelRatio: 0.02,
            videoWidth: 1920,
            videoHeight: 1080,
            orientation: "landscape",
            swingWindowCandidateAvailable: true,
            generatedAt: "2026-04-24T00:00:00.000Z"
        )
        let validation = ValidationResult(
            passed: true,
            checks: [
                ValidationCheck(name: "帧数", passed: true, detail: "共 240 帧"),
                ValidationCheck(name: "亮度", passed: true, detail: "亮度 120")
            ],
            metrics: metrics
        )

        let samples = try service.registerVideoSample(
            videoURL: videoURL,
            activeSession: session,
            clubType: "driver",
            handedness: "right",
            swingIntensity: "normal",
            surface: "mat",
            validationResult: validation,
            captureTimestamps: [0, 1.0 / 240.0, 2.0 / 240.0],
            depthSamples: [DepthSample(timestamp: 0.1, centerDepth: 3.2)],
            lidarCalibration: nil,
            hasLiDAR: true,
            referenceMeasurements: [
                CollectorReferenceMeasurement(
                    source: "radar_or_launch_monitor_manual",
                    device: "test radar",
                    capturedAt: "2026-04-24T00:00:01.000Z",
                    clubSpeedMph: 101.5,
                    ballSpeedMph: 148.2,
                    carryDistanceMeters: 225.0,
                    totalDistanceMeters: 238.0,
                    launchAngleDegrees: 12.4,
                    spinRateRpm: 2600,
                    landingLocation: nil,
                    notes: "unit test"
                )
            ]
        )

        XCTAssertEqual(session.sessionName, "2")
        XCTAssertEqual(session.location?.source, "unit_test")
        XCTAssertEqual(samples.count, 2)
        for sample in samples {
            XCTAssertEqual(sample.takeIndex, 1)
            XCTAssertEqual(sample.metadata.surface, "mat")
            XCTAssertEqual(sample.metadata.sceneType, "indoor")
            XCTAssertEqual(sample.metadata.qualityPassed, true)
            XCTAssertEqual(sample.metadata.qualityScore, 1.0)
            XCTAssertEqual(sample.metadata.labelStatus, "needs_review")
            XCTAssertEqual(sample.metadata.exportStatus, "ready_for_review_export")
            XCTAssertEqual(sample.metadata.metadataComplete, true)
            XCTAssertEqual(sample.metadata.calibrationStatus, "needs_lidar_review")
            XCTAssertEqual(sample.metadata.calibrationMethod, "manual_distance_lidar_available")
            XCTAssertEqual(sample.metadata.frameCount, 240)
            XCTAssertEqual(sample.metadata.referenceMeasurements?.first?.clubSpeedMph, 101.5)

            let sidecars = try XCTUnwrap(sample.metadata.sidecars)
            XCTAssertTrue(fileExists(sidecars.timeline, base: tempDir))
            XCTAssertTrue(fileExists(sidecars.quality, base: tempDir))
            XCTAssertTrue(fileExists(sidecars.camera, base: tempDir))
            XCTAssertTrue(fileExists(sidecars.labelCandidates, base: tempDir))
            XCTAssertTrue(sample.isExportReady)
        }
    }

    private func fileExists(_ relativePath: String?, base: URL) -> Bool {
        guard let relativePath else { return false }
        let suffix: String
        if relativePath.hasPrefix("ios_export/") {
            suffix = String(relativePath.dropFirst("ios_export/".count))
        } else {
            suffix = relativePath
        }
        return FileManager.default.fileExists(atPath: base.appendingPathComponent(suffix).path)
    }
}
