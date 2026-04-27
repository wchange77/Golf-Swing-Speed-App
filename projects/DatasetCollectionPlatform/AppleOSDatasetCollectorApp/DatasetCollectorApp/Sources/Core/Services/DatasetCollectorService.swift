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
    let sessionName: String?
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
    let location: CollectorLocation?
    let targetDomains: [DatasetDomain]
}

final class DatasetCollectorService {
    private let store: JSONLFileStore

    init(store: JSONLFileStore = JSONLFileStore()) {
        self.store = store
    }

    func createSession(_ request: CreateSessionRequest) throws -> CollectorSessionRecord {
        let trimmedSessionName = request.sessionName?.trimmingCharacters(in: .whitespacesAndNewlines)
        let session = CollectorSessionRecord(
            sessionId: "sess_\(UUID().uuidString.replacingOccurrences(of: "-", with: "").prefix(12))",
            sessionName: trimmedSessionName?.isEmpty == false ? trimmedSessionName : nil,
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
            location: request.location,
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
        surface: String = "unknown",
        cameraHeightMeters: Double = 1.0,
        cameraAngleDegrees: Double = 0.0,
        validationResult: ValidationResult? = nil,
        captureTimestamps: [TimeInterval] = [],
        depthSamples: [DepthSample],
        lidarCalibration: LiDARCalibrationData?,
        calibration: CollectorCalibrationSnapshot? = nil,
        hasLiDAR: Bool = false,
        referenceMeasurements: [CollectorReferenceMeasurement] = []
    ) throws -> [CollectorSampleRecord] {
        let videoData = try Data(contentsOf: videoURL)
        let hash = sha256Hex(videoData)
        let fallbackMetrics = fallbackMetrics(from: captureTimestamps, configuredFPS: activeSession.captureConfig.fps)
        let metrics = validationResult?.metrics ?? fallbackMetrics
        let qualityScore = score(for: validationResult)
        let failedChecks = validationResult?.failedChecks.map(\.name) ?? []
        let labelStatus = "needs_review"
        let calibrationSnapshot = makeCalibrationSnapshot(
            session: activeSession,
            cameraHeightMeters: cameraHeightMeters,
            cameraAngleDegrees: cameraAngleDegrees,
            lidarCalibration: lidarCalibration,
            calibration: calibration,
            hasLiDAR: hasLiDAR
        )

        var registered: [CollectorSampleRecord] = []
        let existing = try store.readRecords(CollectorSampleRecord.self, from: store.samplesFileURL)
        let shotId = "shot_\(UUID().uuidString.prefix(8))"

        for domain in [DatasetDomain.humanClub, DatasetDomain.golfBallDetection] {
            guard activeSession.targetDomains.contains(domain.rawValue) else { continue }

            if let matched = existing.first(where: { $0.domain == domain.rawValue && $0.sha256 == hash && $0.status == "active" }) {
                let metadata = buildMetadata(
                    session: activeSession,
                    clubType: clubType,
                    handedness: handedness,
                    swingIntensity: swingIntensity,
                    surface: surface,
                    shotPurpose: domain.rawValue,
                    validationResult: validationResult,
                    metrics: metrics,
                    qualityScore: qualityScore,
                    failedChecks: failedChecks,
                    labelStatus: labelStatus,
                    calibration: calibrationSnapshot,
                    referenceMeasurements: referenceMeasurements,
                    sidecars: nil
                )
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

            if let calibration = lidarCalibration {
                let calibrationURL = assetURL.deletingPathExtension().appendingPathExtension("lidar.json")
                let encoder = JSONEncoder()
                encoder.outputFormatting = .prettyPrinted
                let calibrationData = try encoder.encode(calibration)
                try calibrationData.write(to: calibrationURL, options: .atomic)
            }

            if !depthSamples.isEmpty {
                let depthURL = assetURL.deletingPathExtension().appendingPathExtension("depth.csv")
                var csv = "timestamp,center_depth\n"
                for sample in depthSamples {
                    csv += "\(sample.timestamp),\(sample.centerDepth)\n"
                }
                try csv.write(to: depthURL, atomically: true, encoding: .utf8)
            }

            let sidecars = try writeCaptureSidecars(
                assetURL: assetURL,
                domains: [domain.rawValue],
                session: activeSession,
                validationResult: validationResult,
                metrics: metrics,
                qualityScore: qualityScore,
                timestamps: captureTimestamps,
                depthSamples: depthSamples,
                lidarCalibration: lidarCalibration,
                calibration: calibrationSnapshot,
                hasLiDAR: hasLiDAR
            )
            let metadata = buildMetadata(
                session: activeSession,
                clubType: clubType,
                handedness: handedness,
                swingIntensity: swingIntensity,
                surface: surface,
                shotPurpose: domain.rawValue,
                validationResult: validationResult,
                metrics: metrics,
                qualityScore: qualityScore,
                failedChecks: failedChecks,
                labelStatus: labelStatus,
                calibration: calibrationSnapshot,
                referenceMeasurements: referenceMeasurements,
                sidecars: sidecars
            )

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
                takeIndex: 1,
                tags: [clubType, handedness, swingIntensity, surface, labelStatus],
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

    func exportFileExists(at relativePath: String?) -> Bool {
        guard let relativePath, !relativePath.isEmpty else { return false }
        return store.exportFileExists(at: relativePath)
    }

    func deleteSample(sampleId: String) throws {
        let samples = try loadAllSamples()
        guard let sample = samples.first(where: { $0.sampleId == sampleId }) else { return }
        store.deleteAssetFile(at: sample.assetPath)
        sample.metadata.sidecars?.all.forEach { store.deleteExportFile(at: $0) }
        try store.rewriteRecords(CollectorSampleRecord.self, to: store.samplesFileURL) {
            $0.sampleId == sampleId
        }
    }

    func deleteSession(sessionId: String) throws {
        let samples = try loadAllSamples()
        let sessionSamples = samples.filter { $0.sessionId == sessionId }
        for sample in sessionSamples {
            store.deleteAssetFile(at: sample.assetPath)
            sample.metadata.sidecars?.all.forEach { store.deleteExportFile(at: $0) }
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

    private func buildMetadata(
        session: CollectorSessionRecord,
        clubType: String,
        handedness: String,
        swingIntensity: String,
        surface: String,
        shotPurpose: String,
        validationResult: ValidationResult?,
        metrics: RecordingQualityMetrics,
        qualityScore: Double,
        failedChecks: [String],
        labelStatus: String,
        calibration: CollectorCalibrationSnapshot,
        referenceMeasurements: [CollectorReferenceMeasurement],
        sidecars: CollectorSidecarPaths?
    ) -> CollectorSampleMetadata {
        let exportStatus = exportStatus(
            qualityPassed: validationResult?.passed,
            labelStatus: labelStatus,
            calibration: calibration,
            sidecars: sidecars
        )
        return CollectorSampleMetadata(
            fps: session.captureConfig.fps,
            resolution: session.captureConfig.resolution,
            clubType: clubType,
            handedness: handedness,
            swingIntensity: swingIntensity,
            surface: surface,
            sceneType: session.environment.sceneType,
            lighting: session.environment.lighting,
            tripod: session.environment.tripod,
            distanceMeters: session.environment.distanceMeters,
            shotPurpose: shotPurpose,
            qualityPassed: validationResult?.passed,
            qualityScore: qualityScore,
            qualityFailedChecks: failedChecks,
            actualFPS: metrics.estimatedFPS,
            frameCount: metrics.frameCount,
            durationSeconds: metrics.durationSeconds,
            captureOrientation: metrics.orientation,
            labelStatus: labelStatus,
            exportStatus: exportStatus,
            metadataComplete: metadataComplete(
                clubType: clubType,
                handedness: handedness,
                swingIntensity: swingIntensity,
                surface: surface,
                session: session,
                validationResult: validationResult,
                metrics: metrics,
                calibration: calibration,
                sidecars: sidecars
            ),
            calibrationStatus: calibration.status,
            calibrationMethod: calibration.method,
            calibrationSource: calibration.source,
            pixelsPerMetre: calibration.pixelsPerMetre,
            cameraHeightMeters: calibration.cameraHeightMeters,
            cameraAngleDegrees: calibration.cameraAngleDegrees,
            referenceMeasurements: referenceMeasurements.isEmpty ? nil : referenceMeasurements,
            sidecars: sidecars
        )
    }

    private func fallbackMetrics(
        from timestamps: [TimeInterval],
        configuredFPS: Int
    ) -> RecordingQualityMetrics {
        guard let first = timestamps.first, let last = timestamps.last else {
            return RecordingQualityMetrics.fallback(frameCount: timestamps.count, durationSeconds: 0)
        }
        let duration = max(last - first, 0)
        var metrics = RecordingQualityMetrics.fallback(frameCount: timestamps.count, durationSeconds: duration)
        metrics.estimatedFPS = duration > 0 ? Double(max(timestamps.count - 1, 1)) / duration : Double(configuredFPS)
        return metrics
    }

    private func score(for result: ValidationResult?) -> Double {
        guard let result else { return 0 }
        guard !result.checks.isEmpty else { return result.passed ? 1 : 0 }
        let passed = result.checks.filter(\.passed).count
        return Double(passed) / Double(result.checks.count)
    }

    private func writeCaptureSidecars(
        assetURL: URL,
        domains: [String],
        session: CollectorSessionRecord,
        validationResult: ValidationResult?,
        metrics: RecordingQualityMetrics,
        qualityScore: Double,
        timestamps: [TimeInterval],
        depthSamples: [DepthSample],
        lidarCalibration: LiDARCalibrationData?,
        calibration: CollectorCalibrationSnapshot,
        hasLiDAR: Bool
    ) throws -> CollectorSidecarPaths {
        let generatedAt = DatasetCollectorDateFormatter.nowISO8601()
        let quality = CollectorQualitySidecar(
            version: "1.0",
            generatedAt: generatedAt,
            passed: validationResult?.passed ?? false,
            score: qualityScore,
            checks: validationResult?.checks.map {
                CollectorQualityCheckRecord(name: $0.name, passed: $0.passed, detail: $0.detail)
            } ?? [],
            metrics: metrics,
            thresholds: .baseline
        )
        let timeline = makeTimelineSidecar(
            generatedAt: generatedAt,
            timestamps: timestamps,
            depthSamples: depthSamples,
            metrics: metrics
        )
        let camera = CollectorCameraSidecar(
            version: "1.0",
            generatedAt: generatedAt,
            device: session.device,
            deviceProfile: session.deviceProfile,
            iosVersion: session.iosVersion,
            appVersion: session.appVersion,
            captureConfig: session.captureConfig,
            environment: session.environment,
            captureOrientation: metrics.orientation,
            hasLiDAR: hasLiDAR,
            calibration: calibration,
            lidarCalibration: lidarCalibration
        )
        let labelCandidates = makeLabelCandidateSidecar(
            generatedAt: generatedAt,
            domains: domains,
            metrics: metrics
        )

        let qualityURL = try writeSidecar(quality, assetURL: assetURL, suffix: "quality.json")
        let timelineURL = try writeSidecar(timeline, assetURL: assetURL, suffix: "timeline.json")
        let cameraURL = try writeSidecar(camera, assetURL: assetURL, suffix: "camera.json")
        let labelURL = try writeSidecar(labelCandidates, assetURL: assetURL, suffix: "label_candidates.json")

        return CollectorSidecarPaths(
            timeline: store.relativeExportPath(for: timelineURL),
            quality: store.relativeExportPath(for: qualityURL),
            camera: store.relativeExportPath(for: cameraURL),
            labelCandidates: store.relativeExportPath(for: labelURL)
        )
    }

    private func makeTimelineSidecar(
        generatedAt: String,
        timestamps: [TimeInterval],
        depthSamples: [DepthSample],
        metrics: RecordingQualityMetrics
    ) -> CollectorTimelineSidecar {
        let first = timestamps.first ?? 0
        let frames = timestamps.enumerated().map { index, timestamp in
            CollectorFrameTimestamp(
                index: index,
                presentationTimeSeconds: timestamp,
                relativeTimeSeconds: max(0, timestamp - first)
            )
        }
        let depthPoints = depthSamples.map {
            CollectorDepthPoint(timestampSeconds: $0.timestamp, centerDepthMeters: $0.centerDepth)
        }
        return CollectorTimelineSidecar(
            version: "1.0",
            generatedAt: generatedAt,
            frameCount: frames.isEmpty ? metrics.frameCount : frames.count,
            durationSeconds: metrics.durationSeconds,
            estimatedFPS: metrics.estimatedFPS,
            frames: frames,
            depthSamples: depthPoints
        )
    }

    private func makeLabelCandidateSidecar(
        generatedAt: String,
        domains: [String],
        metrics: RecordingQualityMetrics
    ) -> CollectorLabelCandidateSidecar {
        let duration = max(metrics.durationSeconds, 0.5)
        let fps = metrics.estimatedFPS > 1 ? metrics.estimatedFPS : 240
        let impact = min(max(duration * 0.65, 0.2), duration)
        let start = max(0, impact - min(0.45, duration * 0.3))
        let end = min(duration, impact + min(0.45, duration * 0.25))
        let keyFrameSpecs: [(String, Double, String)] = [
            ("address", 0.12, "姿态与球杆初始位置复核"),
            ("backswing_top", 0.42, "人体关键点与球杆顶点复核"),
            ("impact_window", impact / duration, "球与杆头高速运动区域复核"),
            ("follow_through", 0.82, "收杆姿态复核")
        ]
        let keyFrames = keyFrameSpecs.map { role, ratio, reason in
            let time = min(max(duration * ratio, 0), duration)
            return CollectorKeyFrameCandidate(
                role: role,
                timeSeconds: time,
                frameIndex: Int((time * fps).rounded()),
                reason: reason
            )
        }
        let humanCandidates = keyFrames.map {
            CollectorHumanPoseCandidate(
                timeSeconds: $0.timeSeconds,
                frameIndex: $0.frameIndex,
                source: "capture_quality_sampling",
                task: "review_person_bbox_17_keypoints_and_club_bbox"
            )
        }
        let ballCandidateTimes = stride(from: max(0, impact - 0.05), through: min(duration, impact + 0.05), by: 1.0 / min(max(fps, 30), 240))
        let ballCandidates = ballCandidateTimes.enumerated().prefix(9).map { _, time in
            CollectorBallCandidate(
                timeSeconds: time,
                frameIndex: Int((time * fps).rounded()),
                source: "impact_window_inference",
                task: "review_or_draw_yolo_ball_bbox"
            )
        }

        return CollectorLabelCandidateSidecar(
            version: "1.0",
            generatedAt: generatedAt,
            status: "needs_review",
            reviewRequired: true,
            domains: domains,
            swingWindow: CollectorSwingWindowCandidate(
                startTimeSeconds: start,
                impactTimeSeconds: impact,
                endTimeSeconds: end,
                source: "duration_ratio_heuristic",
                confidence: 0.4
            ),
            keyFrames: keyFrames,
            humanPoseCandidates: humanCandidates,
            ballCandidates: Array(ballCandidates),
            notes: "候选仅用于半自动标注入口，最终 COCO/YOLO 标签必须人工复核。"
        )
    }

    private func writeSidecar<T: Encodable>(
        _ value: T,
        assetURL: URL,
        suffix: String
    ) throws -> URL {
        let target = assetURL.deletingPathExtension().appendingPathExtension(suffix)
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        let data = try encoder.encode(value)
        try data.write(to: target, options: .atomic)
        return target
    }

    private func makeCalibrationSnapshot(
        session: CollectorSessionRecord,
        cameraHeightMeters: Double,
        cameraAngleDegrees: Double,
        lidarCalibration: LiDARCalibrationData?,
        calibration: CollectorCalibrationSnapshot?,
        hasLiDAR: Bool
    ) -> CollectorCalibrationSnapshot {
        if let calibration {
            return calibration
        }

        if let lidarCalibration {
            return CollectorCalibrationSnapshot(
                status: "complete",
                method: "lidar_static",
                source: "arkit_lidar_preswing",
                distanceMeters: session.environment.distanceMeters ?? lidarCalibration.cameraToGroundDistance,
                cameraHeightMeters: lidarCalibration.cameraHeight,
                cameraAngleDegrees: lidarCalibration.cameraAngle,
                pixelsPerMetre: nil,
                groundPlaneY: lidarCalibration.groundPlaneY,
                clubLengthMeters: nil,
                lieAngleDegrees: nil,
                armLengthMeters: nil,
                swingPlaneNormalX: nil,
                swingPlaneNormalY: nil,
                swingPlaneNormalZ: nil,
                ballPositionX: nil,
                ballPositionY: nil,
                ballPositionZ: nil,
                confidence: 0.7,
                notes: "LiDAR 仅用于挥杆前静态标定；240fps 捕获阶段不运行 ARKit。"
            )
        }

        if let distance = session.environment.distanceMeters, distance > 0 {
            return CollectorCalibrationSnapshot(
                status: hasLiDAR ? "needs_lidar_review" : "manual_distance_recorded",
                method: hasLiDAR ? "manual_distance_lidar_available" : "manual_distance",
                source: "session_form",
                distanceMeters: distance,
                cameraHeightMeters: cameraHeightMeters,
                cameraAngleDegrees: cameraAngleDegrees,
                pixelsPerMetre: nil,
                groundPlaneY: nil,
                clubLengthMeters: nil,
                lieAngleDegrees: nil,
                armLengthMeters: nil,
                swingPlaneNormalX: nil,
                swingPlaneNormalY: nil,
                swingPlaneNormalZ: nil,
                ballPositionX: nil,
                ballPositionY: nil,
                ballPositionZ: nil,
                confidence: 0.45,
                notes: "记录了相机距离/高度/角度，可用于后续像素到真实尺度复核；建议在第二阶段接入 LiDAR 静态标定。"
            )
        }

        return CollectorCalibrationSnapshot(
            status: "missing",
            method: "none",
            source: "not_recorded",
            distanceMeters: nil,
            cameraHeightMeters: nil,
            cameraAngleDegrees: nil,
            pixelsPerMetre: nil,
            groundPlaneY: nil,
            clubLengthMeters: nil,
            lieAngleDegrees: nil,
            armLengthMeters: nil,
            swingPlaneNormalX: nil,
            swingPlaneNormalY: nil,
            swingPlaneNormalZ: nil,
            ballPositionX: nil,
            ballPositionY: nil,
            ballPositionZ: nil,
            confidence: 0,
            notes: "缺少标定信息；该样本不应作为测速精度评估样本。"
        )
    }

    private func exportStatus(
        qualityPassed: Bool?,
        labelStatus: String,
        calibration: CollectorCalibrationSnapshot,
        sidecars: CollectorSidecarPaths?
    ) -> String {
        guard qualityPassed == true else { return "blocked_quality" }
        guard calibration.status != "missing" else { return "blocked_calibration" }
        guard sidecars?.hasAllCaptureSidecars == true else { return "blocked_sidecars" }
        guard labelStatus == "needs_review" else { return "blocked_label_status" }
        return "ready_for_review_export"
    }

    private func metadataComplete(
        clubType: String,
        handedness: String,
        swingIntensity: String,
        surface: String,
        session: CollectorSessionRecord,
        validationResult: ValidationResult?,
        metrics: RecordingQualityMetrics,
        calibration: CollectorCalibrationSnapshot,
        sidecars: CollectorSidecarPaths?
    ) -> Bool {
        let required = [
            clubType,
            handedness,
            swingIntensity,
            surface,
            session.environment.sceneType,
            session.environment.lighting,
            calibration.status,
            calibration.method
        ]
        guard required.allSatisfy({ !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && $0 != "unknown" }) else {
            return false
        }
        guard session.environment.distanceMeters.map({ $0 > 0 }) == true else { return false }
        guard validationResult?.passed != nil, metrics.frameCount > 0, metrics.durationSeconds > 0 else { return false }
        guard metrics.orientation != "unknown" else { return false }
        guard sidecars?.hasAllCaptureSidecars == true else { return false }
        return calibration.status != "missing"
    }

    private func sha256Hex(_ data: Data) -> String {
        let digest = SHA256.hash(data: data)
        return digest.map { String(format: "%02x", $0) }.joined()
    }
}
