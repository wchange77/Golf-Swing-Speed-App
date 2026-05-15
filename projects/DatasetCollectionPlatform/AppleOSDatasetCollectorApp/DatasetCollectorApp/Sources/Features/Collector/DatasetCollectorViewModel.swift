import Foundation

@MainActor
final class DatasetCollectorViewModel: ObservableObject {
    @Published var sessionName: String = "1"
    @Published var collector: String = "collector_a"
    @Published var device: String = "iPhone17Max"
    @Published var deviceProfile: String = "iphone17max"
    @Published var iosVersion: String = "iOS 26"
    @Published var appVersion: String = "0.1.0"
    @Published var notes: String = "indoor baseline"
    @Published var fps: Int = 240
    @Published var resolution: String = "1920x1080"
    @Published var sceneType: String = "indoor"
    @Published var lighting: String = "indoor_led"
    @Published var tripod: Bool = true
    @Published var distanceMeters: Double = 4.0
    @Published var targetDomains: Set<DatasetDomain> = [.humanClub, .golfBallDetection]

    @Published private(set) var activeSession: CollectorSessionRecord?
    @Published private(set) var statsSummary: String = "会话 0 / 样本 0 / 重复 0"
    @Published private(set) var exportPath: String = "未导出"
    @Published private(set) var logs: [String] = []
    @Published var errorMessage: String?

    let service: DatasetCollectorService
    private var humanCounter = 0
    private var ballCounter = 0

    var canCreateSession: Bool {
        sessionValidationMessage == "OK"
    }

    var sessionValidationMessage: String {
        if sessionName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { return "会话名称不能为空" }
        if collector.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { return "采集人不能为空" }
        if device.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { return "设备不能为空" }
        if deviceProfile.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { return "设备档案不能为空" }
        if !["indoor", "outdoor", "mixed"].contains(sceneType) { return "场景类型必须是 indoor / outdoor / mixed" }
        if lighting.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { return "光照不能为空" }
        if !tripod { return "高质量采集必须使用三脚架" }
        if distanceMeters < 3.0 || distanceMeters > 5.0 { return "相机距离需在 3-5 米" }
        if fps < 120 { return "帧率需至少 120fps，推荐 240fps" }
        if resolution.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { return "分辨率不能为空" }
        if targetDomains.isEmpty { return "至少选择一个目标域" }
        return "OK"
    }

    init(service: DatasetCollectorService = DatasetCollectorService()) {
        self.service = service
        refreshStats()
        refreshSuggestedSessionName()
    }

    func createSession(location: CollectorLocation?) {
        guard canCreateSession else {
            setError(sessionValidationMessage)
            return
        }
        do {
            let request = CreateSessionRequest(
                sessionName: sessionName,
                collector: collector,
                device: device,
                deviceProfile: deviceProfile,
                iosVersion: iosVersion,
                appVersion: appVersion,
                notes: notes,
                fps: fps,
                resolution: resolution,
                sceneType: sceneType,
                lighting: lighting,
                tripod: tripod,
                distanceMeters: distanceMeters,
                location: location,
                targetDomains: Array(targetDomains).sorted { $0.rawValue < $1.rawValue }
            )
            let session = try service.createSession(request)
            activeSession = session
            appendLog("创建会话: \(session.sessionName ?? session.sessionId)")
            refreshStats()
            refreshExportPath()
            refreshSuggestedSessionName()
        } catch {
            setError(error.localizedDescription)
        }
    }

    func addHumanClubSample(seed: String? = nil) {
        registerSample(domain: .humanClub, seed: seed ?? "human_seed_\(humanCounter)")
        humanCounter += 1
    }

    func addBallSample(seed: String? = nil) {
        registerSample(domain: .golfBallDetection, seed: seed ?? "ball_seed_\(ballCounter)")
        ballCounter += 1
    }

    func addIntentionalDuplicate() {
        registerSample(domain: .humanClub, seed: "duplicate_seed")
        registerSample(domain: .humanClub, seed: "duplicate_seed")
    }

    func refreshStats() {
        do {
            let stats = try service.loadStats()
            statsSummary = "会话 \(stats.sessions) / 样本 \(stats.samples) / 重复 \(stats.duplicates)"
        } catch {
            setError(error.localizedDescription)
        }
    }

    func refreshExportPath() {
        do {
            exportPath = try service.exportDirectoryURL().path
        } catch {
            setError(error.localizedDescription)
        }
    }

    func refreshSuggestedSessionName() {
        do {
            let names = try service.loadAllSessions().compactMap { $0.sessionName }
            let maxNumber = names.compactMap { Int($0.trimmingCharacters(in: .whitespacesAndNewlines)) }.max() ?? 0
            sessionName = "\(maxNumber + 1)"
        } catch {
            sessionName = "1"
        }
    }

    private func registerSample(domain: DatasetDomain, seed: String) {
        guard let activeSession else {
            setError(DatasetCollectorServiceError.noActiveSession.localizedDescription)
            return
        }
        let nextIndex = domain == .humanClub ? humanCounter + 1 : ballCounter + 1
        let shotId = "\(domain.rawValue)_\(nextIndex)"
        let metadata = CollectorSampleMetadata(
            fps: fps,
            resolution: resolution,
            clubType: domain == .humanClub ? "driver" : "none",
            handedness: "right",
            swingIntensity: "normal",
            surface: domain == .golfBallDetection ? "mat" : "indoor",
            sceneType: sceneType,
            lighting: lighting,
            tripod: tripod,
            distanceMeters: distanceMeters,
            shotPurpose: domain.rawValue,
            qualityPassed: nil,
            qualityScore: nil,
            qualityFailedChecks: [],
            actualFPS: nil,
            frameCount: nil,
            durationSeconds: nil,
            captureOrientation: nil,
            labelStatus: "mock",
            sidecars: nil
        )

        do {
            let sample = try service.registerMockSample(
                domain: domain,
                activeSession: activeSession,
                shotId: shotId,
                takeIndex: nextIndex,
                tags: ["ios", "collector_app", domain.rawValue],
                metadata: metadata,
                payloadSeed: seed
            )
            if let sample {
                appendLog("登记样本: \(sample.sampleId)")
            } else {
                appendLog("发现重复样本: seed=\(seed)")
            }
            refreshStats()
            refreshExportPath()
        } catch {
            setError(error.localizedDescription)
        }
    }

    private func appendLog(_ line: String) {
        logs.insert("[\(DatasetCollectorDateFormatter.nowISO8601())] \(line)", at: 0)
        errorMessage = nil
    }

    private func setError(_ message: String?) {
        errorMessage = message
        if let message {
            logs.insert("[\(DatasetCollectorDateFormatter.nowISO8601())] ERROR: \(message)", at: 0)
        }
    }
}
