import Foundation
import CoreMotion

/// Monitors device accelerometer/gyroscope to detect if the camera moves during capture.
///
/// If the phone moves on the tripod (e.g., from vibration or wind), the calibration becomes
/// invalid and speed measurements will be wrong. This detector warns the user.
///
/// Uses Core Motion's CMMotionManager to monitor rotation rate and acceleration.
/// Runs at a low rate (10Hz) to minimise power impact.
@Observable
final class CameraMovementDetector {

    // MARK: - State

    private(set) var isStable = true
    private(set) var totalMovement: Double = 0
    private(set) var warningMessage: String?

    // Thresholds — tuned to avoid false positives from normal sensor noise
    // Normal stationary noise: ~0.01-0.05 rad/s rotation, ~0.01-0.03g acceleration
    private let rotationThreshold: Double = 0.15  // rad/s — significant rotation
    private let accelerationThreshold: Double = 0.12  // g — significant acceleration (gravity removed)
    private let movementWarningThreshold: Double = 3.0  // Accumulated movement score before warning

    // Core Motion
    private let motionManager = CMMotionManager()
    private var isMonitoring = false
    private var movementScore: Double = 0
    private var sampleCount: Int = 0
    private let warmupSamples: Int = 30  // Ignore first 3 seconds (10Hz × 3s)

    // MARK: - Start/Stop

    /// Start monitoring device movement.
    func startMonitoring() {
        guard motionManager.isDeviceMotionAvailable, !isMonitoring else { return }

        motionManager.deviceMotionUpdateInterval = 0.1 // 10Hz — low power
        motionManager.startDeviceMotionUpdates(to: .main) { [weak self] motion, error in
            guard let self, let motion else { return }
            self.processMotion(motion)
        }

        isMonitoring = true
        movementScore = 0
        isStable = true
        warningMessage = nil
    }

    /// Stop monitoring.
    func stopMonitoring() {
        motionManager.stopDeviceMotionUpdates()
        isMonitoring = false
    }

    /// Reset the movement accumulator (e.g., after recalibration).
    func reset() {
        movementScore = 0
        sampleCount = 0
        isStable = true
        warningMessage = nil
        totalMovement = 0
    }

    // MARK: - Motion Processing

    private func processMotion(_ motion: CMDeviceMotion) {
        sampleCount += 1

        // Skip warmup period while sensors stabilise
        guard sampleCount > warmupSamples else { return }

        let rotation = motion.rotationRate
        let userAccel = motion.userAcceleration // Gravity removed

        // Rotation magnitude (rad/s)
        let rotationMagnitude = sqrt(
            rotation.x * rotation.x +
            rotation.y * rotation.y +
            rotation.z * rotation.z
        )

        // Acceleration magnitude (g, gravity removed)
        let accelMagnitude = sqrt(
            userAccel.x * userAccel.x +
            userAccel.y * userAccel.y +
            userAccel.z * userAccel.z
        )

        // Accumulate movement score
        if rotationMagnitude > rotationThreshold {
            movementScore += rotationMagnitude * 10
        }
        if accelMagnitude > accelerationThreshold {
            movementScore += accelMagnitude * 5
        }

        // Slow decay (allows brief vibrations without triggering)
        movementScore *= 0.95

        totalMovement = movementScore

        // Update stability state
        if movementScore > movementWarningThreshold {
            isStable = false
            warningMessage = "Camera moved — recalibrate for accurate results"
        } else {
            isStable = true
            warningMessage = nil
        }
    }
}
