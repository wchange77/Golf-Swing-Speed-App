import Foundation

@MainActor
final class DatasetCollectorViewModel: ObservableObject {
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

    @Published private(set) var activeSession: CollectorSessionRecord?
    @Published private(set) var statsSummary: String = "会话 0 / 样本 0 / 重复 0"
    @Published private(set) var exportPath: String = "未导出"
    @Published private(set) var logs: [String] = []
    @Published private(set) var errorMessage: String?

    private let service: DatasetCollectorService
    private var humanCounter = 0
    private var ballCounter = 0

    init(service: DatasetCollectorService = DatasetCollectorService()) {
        self.service = service
        refreshStats()
    }

    func createSession() {
        do {
            let request = CreateSessionRequest(
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
                distanceMeters: nil,
                targetDomains: [.humanClub, .golfBallDetection]
            )
            let session = try service.createSession(request)
            activeSession = session
            appendLog("创建会话: \(session.sessionId)")
            refreshStats()
            refreshExportPath()
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
            surface: domain == .golfBallDetection ? "mat" : "unknown"
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
