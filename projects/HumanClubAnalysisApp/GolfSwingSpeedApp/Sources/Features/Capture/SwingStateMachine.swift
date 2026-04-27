import Foundation
import Combine

/// Manages the swing detection state machine.
/// Transitions: IDLE → PLAYER_DETECTED → READY → SWING_IN_PROGRESS → SWING_COMPLETE → PROCESSING → RESULT
@Observable
final class SwingStateMachine {

    private(set) var currentState: SwingState = .idle
    private(set) var swingStartTimestamp: TimeInterval?
    private(set) var swingEndTimestamp: TimeInterval?

    // Motion tracking
    private var motionHistory: [Double] = []    // Frame difference magnitudes
    private var stillnessTimer: TimeInterval = 0
    private var lastFrameTimestamp: TimeInterval = 0

    // Callbacks
    var onStateChange: ((SwingState, SwingState) -> Void)?
    var onSwingStart: (() -> Void)?
    var onSwingComplete: (() -> Void)?

    // MARK: - Configuration

    private let stillnessThreshold: Double = 5.0
    private let stillnessDuration: TimeInterval = 0.5
    private let motionOnsetThreshold: Double = 15.0
    private let motionCessationThreshold: Double = 8.0
    private let minSwingDuration: TimeInterval = 0.4
    private let maxSwingDuration: TimeInterval = 3.0
    private let waggleSpeedThreshold: Double = 30.0 // Below this = waggle, not a real swing

    // MARK: - State Transitions

    func playerDetected() {
        transition(to: .playerDetected)
    }

    func playerLost() {
        transition(to: .idle)
    }

    /// Feed frame difference data to drive state transitions.
    /// `motionMagnitude` = average pixel difference between consecutive frames.
    func processMotionFrame(motionMagnitude: Double, timestamp: TimeInterval) {
        let dt = timestamp - lastFrameTimestamp
        lastFrameTimestamp = timestamp

        motionHistory.append(motionMagnitude)
        if motionHistory.count > 60 { motionHistory.removeFirst() } // Keep ~0.25s at 240fps

        switch currentState {
        case .idle:
            // Waiting for player — nothing to do with motion data
            break

        case .playerDetected:
            // Waiting for stillness (address position)
            if motionMagnitude < stillnessThreshold {
                stillnessTimer += dt
                if stillnessTimer >= stillnessDuration {
                    transition(to: .ready)
                }
            } else {
                stillnessTimer = 0
            }

        case .ready:
            // Waiting for swing onset
            if motionMagnitude > motionOnsetThreshold {
                // Check it's not just a small waggle — need sustained motion
                swingStartTimestamp = timestamp
                transition(to: .swingInProgress)
                onSwingStart?()
            }

        case .swingInProgress:
            // Monitoring for swing completion
            let elapsed = timestamp - (swingStartTimestamp ?? timestamp)

            // Check for swing completion: motion dropping off after peak
            if elapsed > minSwingDuration {
                let recentAverage = recentMotionAverage(lastN: 15)

                // Swing complete when motion drops significantly from peak
                if recentAverage < motionCessationThreshold {
                    swingEndTimestamp = timestamp
                    transition(to: .swingComplete)
                    onSwingComplete?()
                }
            }

            // Timeout — swing took too long (probably not a real swing)
            if elapsed > maxSwingDuration {
                swingEndTimestamp = timestamp
                transition(to: .swingComplete)
                onSwingComplete?()
            }

        case .swingComplete:
            // Automatically transitions to processing (handled externally)
            break

        case .processing:
            // Waiting for analysis to complete
            break

        case .result:
            // Displaying result — will auto-reset
            break
        }
    }

    /// Feed audio energy data for supplementary swing detection.
    func processAudioEnergy(rmsEnergy: Double, timestamp: TimeInterval) {
        // Phase 3: Audio swing detection integration
        // For now, motion-based detection is primary
    }

    /// Externally trigger transition to processing state.
    func beginProcessing() {
        transition(to: .processing)
    }

    /// Externally trigger transition to result state.
    func showResult() {
        transition(to: .result)
    }

    /// Reset to idle for next swing.
    func reset() {
        transition(to: .idle)
        swingStartTimestamp = nil
        swingEndTimestamp = nil
        motionHistory = []
        stillnessTimer = 0
    }

    /// Check if the most recent swing was likely a waggle (not a real swing).
    var lastSwingWasWaggle: Bool {
        guard let start = swingStartTimestamp, let end = swingEndTimestamp else { return true }
        let duration = end - start
        let peakMotion = motionHistory.max() ?? 0

        return duration < minSwingDuration || peakMotion < waggleSpeedThreshold
    }

    var swingDuration: TimeInterval? {
        guard let start = swingStartTimestamp, let end = swingEndTimestamp else { return nil }
        return end - start
    }

    // MARK: - Private

    private func transition(to newState: SwingState) {
        let oldState = currentState
        guard oldState != newState else { return }
        currentState = newState
        onStateChange?(oldState, newState)
    }

    private func recentMotionAverage(lastN: Int) -> Double {
        let slice = motionHistory.suffix(lastN)
        guard !slice.isEmpty else { return 0 }
        return slice.reduce(0, +) / Double(slice.count)
    }
}
