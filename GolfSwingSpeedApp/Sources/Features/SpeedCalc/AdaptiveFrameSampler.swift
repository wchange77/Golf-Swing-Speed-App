import Foundation

/// Determines which frames to fully analyse based on swing phase.
/// Not all phases need 240fps — backswing and follow-through can be
/// processed at 30-60fps with negligible accuracy loss.
///
/// Two-pass approach:
/// 1. Fast pass (~30fps): classify swing phases from motion magnitude + audio timing
/// 2. Targeted pass: select frames at variable rate per phase
struct AdaptiveFrameSampler {

    /// Target analysis FPS per swing phase.
    /// These are tunable — will be optimised based on measured accuracy impact.
    struct SamplingConfig {
        var addressFPS: Double = 30
        var backswingFPS: Double = 60
        var topTransitionFPS: Double = 120
        var earlyDownswingFPS: Double = 240
        var lateDownswingFPS: Double = 240   // Every frame — critical zone
        var impactFPS: Double = 240          // Every frame — critical zone
        var postImpactFPS: Double = 120
        var followThroughFPS: Double = 60

        func targetFPS(for phase: SwingPhase) -> Double {
            switch phase {
            case .address: return addressFPS
            case .backswing: return backswingFPS
            case .top: return topTransitionFPS
            case .earlyDownswing: return earlyDownswingFPS
            case .lateDownswing: return lateDownswingFPS
            case .impact: return impactFPS
            case .postImpact: return postImpactFPS
            case .followThrough: return followThroughFPS
            }
        }
    }

    /// Result of the fast classification pass.
    struct PhaseSegment {
        var phase: SwingPhase
        var startTimestamp: TimeInterval
        var endTimestamp: TimeInterval
        var startFrameIndex: Int
        var endFrameIndex: Int
    }

    // MARK: - Fast Phase Classification (Pass 1)

    /// Classify swing phases from frame timestamps and motion magnitudes.
    /// Runs at ~30fps equivalent (samples every Nth frame).
    static func classifyPhases(
        frameTimestamps: [TimeInterval],
        motionMagnitudes: [Double],
        impactTimestamp: TimeInterval?,
        captureFPS: Double = 240
    ) -> [PhaseSegment] {
        guard frameTimestamps.count == motionMagnitudes.count,
              !frameTimestamps.isEmpty else {
            return []
        }

        var segments: [PhaseSegment] = []
        var currentPhase: SwingPhase = .address
        var segmentStart = 0

        let peakMotion = motionMagnitudes.max() ?? 0
        let motionThreshold = peakMotion * 0.1

        for i in 0..<frameTimestamps.count {
            let motion = motionMagnitudes[i]
            let timestamp = frameTimestamps[i]
            var newPhase = currentPhase

            if let impact = impactTimestamp {
                let timeToImpact = impact - timestamp
                if timeToImpact > 0.6 {
                    newPhase = motion < motionThreshold ? .address : .backswing
                } else if timeToImpact > 0.35 {
                    newPhase = .backswing
                } else if timeToImpact > 0.25 {
                    newPhase = .top
                } else if timeToImpact > 0.08 {
                    newPhase = .earlyDownswing
                } else if timeToImpact > 0 {
                    newPhase = .lateDownswing
                } else if timeToImpact > -0.02 {
                    newPhase = .impact
                } else if timeToImpact > -0.1 {
                    newPhase = .postImpact
                } else {
                    newPhase = .followThrough
                }
            } else {
                // No impact timestamp — classify from motion pattern
                if motion < motionThreshold * 2 && segments.isEmpty {
                    newPhase = .address
                } else if motion > peakMotion * 0.8 {
                    newPhase = .lateDownswing
                } else if motion > peakMotion * 0.3 {
                    newPhase = segments.last?.phase == .lateDownswing ? .postImpact : .earlyDownswing
                } else {
                    newPhase = segments.last?.phase == .postImpact ? .followThrough : .backswing
                }
            }

            if newPhase != currentPhase || i == frameTimestamps.count - 1 {
                let endIndex = i == frameTimestamps.count - 1 ? i : i - 1
                if endIndex >= segmentStart {
                    segments.append(PhaseSegment(
                        phase: currentPhase,
                        startTimestamp: frameTimestamps[segmentStart],
                        endTimestamp: frameTimestamps[endIndex],
                        startFrameIndex: segmentStart,
                        endFrameIndex: endIndex
                    ))
                }
                segmentStart = i
                currentPhase = newPhase
            }
        }

        return segments
    }

    // MARK: - Frame Selection (Pass 2)

    /// Select which frame indices to fully analyse, based on phase-specific sampling rates.
    static func selectFrames(
        phases: [PhaseSegment],
        totalFrameCount: Int,
        captureFPS: Double = 240,
        config: SamplingConfig = SamplingConfig()
    ) -> [Int] {
        var selectedIndices: Set<Int> = []

        for segment in phases {
            let targetFPS = config.targetFPS(for: segment.phase)
            let frameInterval = max(1, Int(captureFPS / targetFPS))

            for i in stride(from: segment.startFrameIndex, through: segment.endFrameIndex, by: frameInterval) {
                selectedIndices.insert(i)
            }

            // Always include the first and last frame of each segment
            selectedIndices.insert(segment.startFrameIndex)
            selectedIndices.insert(segment.endFrameIndex)
        }

        return selectedIndices.sorted()
    }

    // MARK: - Statistics

    /// Report how many frames will be analysed vs total captured.
    static func samplingReport(
        selectedCount: Int,
        totalCount: Int
    ) -> (framesAnalysed: Int, framesSkipped: Int, reductionPercent: Double) {
        let skipped = totalCount - selectedCount
        let reduction = totalCount > 0 ? Double(skipped) / Double(totalCount) * 100 : 0
        return (selectedCount, skipped, reduction)
    }
}
