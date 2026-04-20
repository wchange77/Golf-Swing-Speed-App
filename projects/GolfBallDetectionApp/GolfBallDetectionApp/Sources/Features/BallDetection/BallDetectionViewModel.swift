import Foundation

@MainActor
final class BallDetectionViewModel: ObservableObject {
    @Published private(set) var records: [BallDetectionRecord] = []
    @Published private(set) var manifestSummary: String = "未加载数据集清单"
    @Published private(set) var isSessionRunning = false

    private let cameraSession = BallCameraSession()

    init() {
        refreshManifestSummary()
    }

    func toggleSession() {
        if isSessionRunning {
            cameraSession.stop()
            isSessionRunning = false
        } else {
            cameraSession.start()
            isSessionRunning = true
            // Stub result to validate integration path.
            records.insert(BallDetectionRecord(confidence: 0.92, centerX: 0.52, centerY: 0.48, radius: 0.06), at: 0)
        }
    }

    func refreshManifestSummary() {
        guard let manifest = BallDatasetBridge.loadManifest() else {
            manifestSummary = "未找到数据集清单: \(BallDatasetBridge.manifestPath())"
            return
        }

        let ball = manifest.dataset?.key == "golf_ball_detection"
            ? manifest.dataset
            : manifest.datasets?.first(where: { $0.key == "golf_ball_detection" })
        if let ball {
            manifestSummary = "球数据集样本: \(ball.samples) (\(ball.format))"
        } else {
            manifestSummary = "清单已加载，但未找到 golf_ball_detection 条目"
        }
    }
}
