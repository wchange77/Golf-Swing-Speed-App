import CryptoKit
import Foundation

enum DatasetCollectorServiceError: LocalizedError {
    case noActiveSession
    case domainNotInSession
    case unableToCreateAsset

    var errorDescription: String? {
        switch self {
        case .noActiveSession:
            return "未创建采集会话，无法登记样本。"
        case .domainNotInSession:
            return "当前会话未声明该数据域，拒绝登记样本。"
        case .unableToCreateAsset:
            return "无法创建模拟样本文件。"
        }
    }
}

struct CreateSessionRequest {
    let collector: String
    let device: String
    let deviceProfile: String
    let iosVersion: String
    let appVersion: String
    let notes: String
    let fps: Int
    let resolution: String
    let sceneType: String
    let lighting: String
    let tripod: Bool
    let distanceMeters: Double?
    let targetDomains: [DatasetDomain]
}

final class DatasetCollectorService {
    private let store: JSONLFileStore

    init(store: JSONLFileStore = JSONLFileStore()) {
        self.store = store
    }

    func createSession(_ request: CreateSessionRequest) throws -> CollectorSessionRecord {
        let session = CollectorSessionRecord(
            sessionId: "sess_\(UUID().uuidString.replacingOccurrences(of: "-", with: "").prefix(12))",
            collector: request.collector,
            device: request.device,
            deviceProfile: request.deviceProfile,
            createdAt: DatasetCollectorDateFormatter.nowISO8601(),
            status: "active",
            iosVersion: request.iosVersion,
            appVersion: request.appVersion,
            captureConfig: CollectorCaptureConfig(fps: request.fps, resolution: request.resolution),
            environment: CollectorEnvironment(
                sceneType: request.sceneType,
                lighting: request.lighting,
                tripod: request.tripod,
                distanceMeters: request.distanceMeters
            ),
            targetDomains: request.targetDomains.map(\.rawValue),
            notes: request.notes
        )
        try store.append(session, to: store.sessionsFileURL)
        return session
    }

    func registerMockSample(
        domain: DatasetDomain,
        activeSession: CollectorSessionRecord,
        shotId: String,
        takeIndex: Int,
        tags: [String],
        metadata: CollectorSampleMetadata,
        payloadSeed: String
    ) throws -> CollectorSampleRecord? {
        guard activeSession.targetDomains.contains(domain.rawValue) else {
            throw DatasetCollectorServiceError.domainNotInSession
        }

        let payload = "domain=\(domain.rawValue);seed=\(payloadSeed)"
        guard let payloadData = payload.data(using: .utf8) else {
            throw DatasetCollectorServiceError.unableToCreateAsset
        }
        let hash = sha256Hex(payloadData)

        let existing = try store.readRecords(CollectorSampleRecord.self, from: store.samplesFileURL)
        if let matched = existing.first(where: { $0.domain == domain.rawValue && $0.sha256 == hash && $0.status == "active" }) {
            let duplicate = CollectorDuplicateRecord(
                duplicateAt: DatasetCollectorDateFormatter.nowISO8601(),
                domain: domain.rawValue,
                sha256: hash,
                incomingFile: "ios://mock/\(shotId)",
                incomingSourcePath: "ios://capture/\(activeSession.sessionId)/\(shotId)",
                existingSampleId: matched.sampleId,
                sessionId: activeSession.sessionId,
                collector: activeSession.collector,
                metadata: metadata
            )
            try store.append(duplicate, to: store.duplicatesFileURL)
            return nil
        }

        let assetURL = try writeAsset(
            data: payloadData,
            domain: domain,
            hash: hash,
            fileExtension: "txt"
        )
        let sample = CollectorSampleRecord(
            sampleId: "\(domain.rawValue)_\(hash.prefix(12))",
            domain: domain.rawValue,
            sha256: hash,
            hashAlgorithm: "sha256",
            assetPath: store.relativeExportPath(for: assetURL),
            annotationPath: nil,
            fileSize: payloadData.count,
            sessionId: activeSession.sessionId,
            collector: activeSession.collector,
            device: activeSession.device,
            deviceProfile: activeSession.deviceProfile,
            capturedAt: DatasetCollectorDateFormatter.nowISO8601(),
            sourcePath: "ios://capture/\(activeSession.sessionId)/\(shotId)",
            shotId: shotId,
            takeIndex: takeIndex,
            tags: tags,
            metadata: metadata,
            status: "active"
        )
        try store.append(sample, to: store.samplesFileURL)
        return sample
    }

    func loadStats() throws -> (sessions: Int, samples: Int, duplicates: Int) {
        let sessions = try store.readRecords(CollectorSessionRecord.self, from: store.sessionsFileURL).count
        let samples = try store.readRecords(CollectorSampleRecord.self, from: store.samplesFileURL).count
        let duplicates = try store.readRecords(CollectorDuplicateRecord.self, from: store.duplicatesFileURL).count
        return (sessions, samples, duplicates)
    }

    func exportDirectoryURL() throws -> URL {
        try store.exportDirectory()
    }

    func registerVideoSample(
        videoURL: URL,
        activeSession: CollectorSessionRecord,
        clubType: String,
        handedness: String,
        swingIntensity: String,
        depthSamples: [DepthSample],
        lidarCalibration: LiDARCalibrationData?
    ) throws -> [CollectorSampleRecord] {
        let videoData = try Data(contentsOf: videoURL)
        let hash = sha256Hex(videoData)
        let metadata = CollectorSampleMetadata(
            fps: activeSession.captureConfig.fps,
            resolution: activeSession.captureConfig.resolution,
            clubType: clubType,
            handedness: handedness,
            swingIntensity: swingIntensity,
            surface: activeSession.environment.sceneType
        )

        var registered: [CollectorSampleRecord] = []
        let existing = try store.readRecords(CollectorSampleRecord.self, from: store.samplesFileURL)
        let shotId = "shot_\(UUID().uuidString.prefix(8))"

        for domain in [DatasetDomain.humanClub, DatasetDomain.golfBallDetection] {
            guard activeSession.targetDomains.contains(domain.rawValue) else { continue }

            if let matched = existing.first(where: { $0.domain == domain.rawValue && $0.sha256 == hash && $0.status == "active" }) {
                let duplicate = CollectorDuplicateRecord(
                    duplicateAt: DatasetCollectorDateFormatter.nowISO8601(),
                    domain: domain.rawValue,
                    sha256: hash,
                    incomingFile: videoURL.lastPathComponent,
                    incomingSourcePath: "ios://capture/\(activeSession.sessionId)/\(shotId)",
                    existingSampleId: matched.sampleId,
                    sessionId: activeSession.sessionId,
                    collector: activeSession.collector,
                    metadata: metadata
                )
                try store.append(duplicate, to: store.duplicatesFileURL)
                continue
            }

            let assetURL = try writeAsset(
                data: videoData,
                domain: domain,
                hash: hash,
                fileExtension: "mov"
            )

            // Save LiDAR calibration alongside video if available
            if let calibration = lidarCalibration {
                let calibrationURL = assetURL.deletingPathExtension().appendingPathExtension("lidar.json")
                let encoder = JSONEncoder()
                encoder.outputFormatting = .prettyPrinted
                let calibrationData = try encoder.encode(calibration)
                try calibrationData.write(to: calibrationURL, options: .atomic)
            }

            // Save depth samples alongside video
            if !depthSamples.isEmpty {
                let depthURL = assetURL.deletingPathExtension().appendingPathExtension("depth.csv")
                var csv = "timestamp,center_depth\n"
                for sample in depthSamples {
                    csv += "\(sample.timestamp),\(sample.centerDepth)\n"
                }
                try csv.write(to: depthURL, atomically: true, encoding: .utf8)
            }

            let sample = CollectorSampleRecord(
                sampleId: "\(domain.rawValue)_\(hash.prefix(12))",
                domain: domain.rawValue,
                sha256: hash,
                hashAlgorithm: "sha256",
                assetPath: store.relativeExportPath(for: assetURL),
                annotationPath: nil,
                fileSize: videoData.count,
                sessionId: activeSession.sessionId,
                collector: activeSession.collector,
                device: activeSession.device,
                deviceProfile: activeSession.deviceProfile,
                capturedAt: DatasetCollectorDateFormatter.nowISO8601(),
                sourcePath: "ios://capture/\(activeSession.sessionId)/\(shotId)",
                shotId: shotId,
                takeIndex: registered.count,
                tags: [clubType, handedness, swingIntensity],
                metadata: metadata,
                status: "active"
            )
            try store.append(sample, to: store.samplesFileURL)
            registered.append(sample)
        }

        return registered
    }

    func loadAllSamples() throws -> [CollectorSampleRecord] {
        try store.readRecords(CollectorSampleRecord.self, from: store.samplesFileURL)
    }

    func loadAllSessions() throws -> [CollectorSessionRecord] {
        try store.readRecords(CollectorSessionRecord.self, from: store.sessionsFileURL)
    }

    func deleteSample(sampleId: String) throws {
        let samples = try loadAllSamples()
        guard let sample = samples.first(where: { $0.sampleId == sampleId }) else { return }
        store.deleteAssetFile(at: sample.assetPath)
        try store.rewriteRecords(CollectorSampleRecord.self, to: store.samplesFileURL) {
            $0.sampleId == sampleId
        }
    }

    func deleteSession(sessionId: String) throws {
        let samples = try loadAllSamples()
        let sessionSamples = samples.filter { $0.sessionId == sessionId }
        for sample in sessionSamples {
            store.deleteAssetFile(at: sample.assetPath)
        }
        try store.rewriteRecords(CollectorSampleRecord.self, to: store.samplesFileURL) {
            $0.sessionId == sessionId
        }
        try store.rewriteRecords(CollectorSessionRecord.self, to: store.sessionsFileURL) {
            $0.sessionId == sessionId
        }
    }

    private func writeAsset(data: Data, domain: DatasetDomain, hash: String, fileExtension: String) throws -> URL {
        try store.bootstrap()
        let firstTwo = String(hash.prefix(2))
        let domainDir = store.assetsDirectoryURL
            .appendingPathComponent(domain.rawValue, isDirectory: true)
            .appendingPathComponent(firstTwo, isDirectory: true)
        try FileManager.default.createDirectory(at: domainDir, withIntermediateDirectories: true)
        let target = domainDir.appendingPathComponent("\(hash).\(fileExtension)")
        try data.write(to: target, options: .atomic)
        return target
    }

    private func sha256Hex(_ data: Data) -> String {
        let digest = SHA256.hash(data: data)
        return digest.map { String(format: "%02x", $0) }.joined()
    }
}
