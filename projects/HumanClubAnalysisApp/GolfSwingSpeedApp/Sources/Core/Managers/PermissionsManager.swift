import AVFoundation

@Observable
final class PermissionsManager {
    var cameraAuthorized = false
    var microphoneAuthorized = false

    func checkPermissions() {
        cameraAuthorized = AVCaptureDevice.authorizationStatus(for: .video) == .authorized
        microphoneAuthorized = AVCaptureDevice.authorizationStatus(for: .audio) == .authorized
    }

    func requestCameraPermission() async -> Bool {
        let status = AVCaptureDevice.authorizationStatus(for: .video)
        switch status {
        case .authorized:
            cameraAuthorized = true
            return true
        case .notDetermined:
            let granted = await AVCaptureDevice.requestAccess(for: .video)
            cameraAuthorized = granted
            return granted
        default:
            cameraAuthorized = false
            return false
        }
    }

    func requestMicrophonePermission() async -> Bool {
        let status = AVCaptureDevice.authorizationStatus(for: .audio)
        switch status {
        case .authorized:
            microphoneAuthorized = true
            return true
        case .notDetermined:
            let granted = await AVCaptureDevice.requestAccess(for: .audio)
            microphoneAuthorized = granted
            return granted
        default:
            microphoneAuthorized = false
            return false
        }
    }

    var allPermissionsGranted: Bool {
        cameraAuthorized && microphoneAuthorized
    }

    static var hasLiDAR: Bool {
        ARConfiguration.supportsLiDAR
    }
}

// MARK: - ARKit support check
import ARKit

private extension ARConfiguration {
    static var supportsLiDAR: Bool {
        ARWorldTrackingConfiguration.supportsSceneReconstruction(.mesh)
    }
}
