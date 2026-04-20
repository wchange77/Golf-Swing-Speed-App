import Foundation

final class BallCameraSession {
    private(set) var isRunning = false

    func start() {
        isRunning = true
    }

    func stop() {
        isRunning = false
    }
}
