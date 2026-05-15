import ARKit
import Foundation
import simd

@MainActor
final class LiDARCalibrationManager: NSObject, ObservableObject {
    enum Status {
        case idle
        case running
        case success(LiDARCalibrationData)
        case failure(String)

        var isRunning: Bool {
            if case .running = self { return true }
            return false
        }

        var message: String {
            switch self {
            case .idle: return "尚未标定"
            case .running: return "正在检测地平面…"
            case .success(let data):
                return String(
                    format: "已标定：高度 %.2f 米 / 距地 %.2f 米 / 俯仰 %.1f°",
                    data.cameraHeight,
                    data.cameraToGroundDistance,
                    data.cameraAngle
                )
            case .failure(let reason):
                return "标定失败：\(reason)"
            }
        }
    }

    @Published private(set) var status: Status = .idle
    @Published private(set) var isSupported: Bool = ARWorldTrackingConfiguration.supportsSceneReconstruction(.mesh)

    private var session: ARSession?
    private var timeoutTask: Task<Void, Never>?
    private var continuation: CheckedContinuation<LiDARCalibrationData?, Never>?
    private var bestPlaneY: Float?
    private var bestPlaneExtent: Float = 0
    private var sampleCount: Int = 0
    private let minSampleCount = 4
    private let minPlaneExtent: Float = 0.25

    @discardableResult
    func runStaticCalibration(timeoutSeconds: TimeInterval = 5.0) async -> LiDARCalibrationData? {
        if case .running = status { return nil }

        guard ARWorldTrackingConfiguration.isSupported else {
            status = .failure("当前设备不支持 ARKit")
            return nil
        }

        resetWorkingState()
        status = .running

        let session = ARSession()
        self.session = session
        session.delegate = self

        let config = ARWorldTrackingConfiguration()
        config.planeDetection = [.horizontal]
        if ARWorldTrackingConfiguration.supportsSceneReconstruction(.mesh) {
            config.sceneReconstruction = .mesh
        }
        if ARWorldTrackingConfiguration.supportsFrameSemantics(.sceneDepth) {
            config.frameSemantics.insert(.sceneDepth)
        }
        session.run(config, options: [.resetTracking, .removeExistingAnchors])

        let result = await withCheckedContinuation { (cont: CheckedContinuation<LiDARCalibrationData?, Never>) in
            self.continuation = cont
            self.timeoutTask = Task { [weak self] in
                try? await Task.sleep(for: .seconds(timeoutSeconds))
                guard let self, !Task.isCancelled else { return }
                await self.finishWithTimeout()
            }
        }

        return result
    }

    func cancel() {
        timeoutTask?.cancel()
        timeoutTask = nil
        tearDownSession()
        resolve(nil, failure: "已取消")
    }

    private func finishWithTimeout() {
        if let snapshot = buildSnapshotIfPossible() {
            tearDownSession()
            status = .success(snapshot)
            resolve(snapshot, failure: nil)
        } else {
            tearDownSession()
            resolve(nil, failure: "未检测到稳定地平面，请对准地面再试")
        }
    }

    private func buildSnapshotIfPossible() -> LiDARCalibrationData? {
        guard let planeY = bestPlaneY,
              let frame = session?.currentFrame,
              sampleCount >= minSampleCount else { return nil }

        let cameraY = Double(frame.camera.transform.columns.3.y)
        let height = cameraY - Double(planeY)
        let toGround = abs(height)
        let pitchDegrees = Double(frame.camera.eulerAngles.x) * 180.0 / .pi

        return LiDARCalibrationData(
            cameraToGroundDistance: toGround,
            groundPlaneY: planeY,
            cameraHeight: height,
            cameraAngle: pitchDegrees,
            capturedAt: DatasetCollectorDateFormatter.nowISO8601()
        )
    }

    private func resolve(_ data: LiDARCalibrationData?, failure: String?) {
        if let failure, data == nil {
            status = .failure(failure)
        }
        let cont = continuation
        continuation = nil
        cont?.resume(returning: data)
    }

    private func tearDownSession() {
        session?.pause()
        session?.delegate = nil
        session = nil
    }

    private func resetWorkingState() {
        bestPlaneY = nil
        bestPlaneExtent = 0
        sampleCount = 0
    }

    private func considerPlane(_ plane: ARPlaneAnchor) {
        guard plane.alignment == .horizontal else { return }
        let extent = max(plane.planeExtent.width, plane.planeExtent.height)
        let worldY = plane.transform.columns.3.y
        sampleCount += 1
        if extent >= minPlaneExtent && extent >= bestPlaneExtent {
            bestPlaneY = worldY
            bestPlaneExtent = extent
        } else if bestPlaneY == nil {
            bestPlaneY = worldY
            bestPlaneExtent = extent
        }
    }
}

extension LiDARCalibrationManager: ARSessionDelegate {
    nonisolated func session(_ session: ARSession, didAdd anchors: [ARAnchor]) {
        Task { @MainActor in
            anchors.compactMap { $0 as? ARPlaneAnchor }.forEach(considerPlane)
        }
    }

    nonisolated func session(_ session: ARSession, didUpdate anchors: [ARAnchor]) {
        Task { @MainActor in
            anchors.compactMap { $0 as? ARPlaneAnchor }.forEach(considerPlane)
        }
    }

    nonisolated func session(_ session: ARSession, didFailWithError error: Error) {
        Task { @MainActor in
            self.timeoutTask?.cancel()
            self.timeoutTask = nil
            self.tearDownSession()
            self.resolve(nil, failure: error.localizedDescription)
        }
    }
}
