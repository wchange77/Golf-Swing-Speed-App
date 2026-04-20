import Foundation
import AVFoundation

/// Orchestrates the full automated swing capture flow:
///
/// 1. IDLE: Audio monitoring active (low power), camera preview running
/// 2. Audio detects swing onset → start 240fps recording
/// 3. Audio detects impact → record timestamp
/// 4. Audio detects completion OR timeout → stop recording
/// 5. PostCaptureAnalysisEngine processes recorded video
/// 6. Results returned via delegate
///
/// This coordinator replaces the manual record button flow.
/// When auto-capture is enabled, the user just swings and gets results.
@MainActor
@Observable
final class SwingCaptureCoordinator {

    // MARK: - State

    enum CaptureMode {
        case manual     // User presses record button
        case automatic  // Audio-triggered recording
    }

    enum CoordinatorState: Equatable {
        case idle
        case listening          // Audio monitoring, waiting for swing
        case recording          // 240fps capture in progress
        case analysing          // Post-capture analysis running
        case result             // Analysis complete, showing results
        case error(String)      // Error state

        static func == (lhs: CoordinatorState, rhs: CoordinatorState) -> Bool {
            switch (lhs, rhs) {
            case (.idle, .idle), (.listening, .listening), (.recording, .recording),
                 (.analysing, .analysing), (.result, .result):
                return true
            case (.error(let a), .error(let b)):
                return a == b
            default:
                return false
            }
        }
    }

    private(set) var state: CoordinatorState = .idle
    private(set) var lastResult: PostCaptureAnalysisEngine.AnalysisResult?
    private(set) var lastRecordingURL: URL?
    private(set) var analysisProgress: Double = 0
    private(set) var analysisPhase: PostCaptureAnalysisEngine.AnalysisPhase = .loadingVideo

    var captureMode: CaptureMode = .manual

    // MARK: - Dependencies

    private let cameraManager: CameraManager
    private let audioDetector: SwingAudioDetector
    private let audioFeedback: AudioFeedbackManager
    private var calibration: CalibrationSnapshot?
    private var isRightHanded: Bool = true

    // Recording state
    private var recordingStartTime: Date?
    private var audioImpactTimestamp: TimeInterval?
    private var recordingTimeoutTask: Task<Void, Never>?
    private let maxRecordingDuration: TimeInterval = 4.0 // Safety timeout

    // MARK: - Init

    init(
        cameraManager: CameraManager,
        audioDetector: SwingAudioDetector = SwingAudioDetector(),
        audioFeedback: AudioFeedbackManager = AudioFeedbackManager()
    ) {
        self.cameraManager = cameraManager
        self.audioDetector = audioDetector
        self.audioFeedback = audioFeedback

        setupAudioCallbacks()
    }

    // MARK: - Configuration

    func configure(calibration: CalibrationSnapshot?, isRightHanded: Bool = true) {
        self.calibration = calibration
        self.isRightHanded = isRightHanded
    }

    // MARK: - Auto Capture Control

    /// Start listening for swings (auto-capture mode).
    func startListening() throws {
        guard captureMode == .automatic else { return }

        try audioDetector.startMonitoring()
        state = .listening
        audioFeedback.ready()
    }

    /// Stop listening.
    func stopListening() {
        audioDetector.stopMonitoring()
        if state == .listening {
            state = .idle
        }
    }

    // MARK: - Manual Capture Control

    /// Manually start recording (manual mode).
    func startManualRecording() async throws -> URL {
        let url = try await cameraManager.startRecording()
        recordingStartTime = Date()
        audioImpactTimestamp = nil
        lastRecordingURL = url
        state = .recording

        // Start a safety timeout (cancel previous if any)
        recordingTimeoutTask?.cancel()
        recordingTimeoutTask = Task { [weak self] in
            try? await Task.sleep(for: .seconds(self?.maxRecordingDuration ?? 4.0))
            guard let self, self.state == .recording else { return }
            try? await self.stopRecordingAndAnalyse()
        }

        return url
    }

    /// Manually stop recording and trigger analysis.
    func stopRecordingAndAnalyse() async throws {
        guard state == .recording else { return }

        recordingTimeoutTask?.cancel()
        recordingTimeoutTask = nil

        let url = try await cameraManager.stopRecording()
        lastRecordingURL = url
        audioFeedback.swingCaptured()
        state = .analysing

        await runAnalysis(videoURL: url)
    }

    // MARK: - Audio Callbacks

    private func setupAudioCallbacks() {
        audioDetector.onSwingOnset = { [weak self] in
            Task { @MainActor in
                await self?.handleSwingOnset()
            }
        }

        audioDetector.onImpactDetected = { [weak self] timestamp in
            Task { @MainActor in
                self?.audioImpactTimestamp = timestamp
            }
        }

        audioDetector.onSwingComplete = { [weak self] in
            Task { @MainActor in
                await self?.handleSwingComplete()
            }
        }
    }

    private func handleSwingOnset() async {
        guard state == .listening else { return }

        do {
            let url = try await cameraManager.startRecording()
            recordingStartTime = Date()
            lastRecordingURL = url
            state = .recording
        } catch {
            state = .error("Failed to start recording: \(error.localizedDescription)")
        }
    }

    private func handleSwingComplete() async {
        guard state == .recording else { return }

        do {
            try await stopRecordingAndAnalyse()
        } catch {
            state = .error("Failed to stop recording: \(error.localizedDescription)")
        }
    }

    // MARK: - Analysis

    private func runAnalysis(videoURL: URL) async {
        guard let calibration else {
            state = .error("No calibration data — please calibrate first")
            return
        }

        let engine = PostCaptureAnalysisEngine()

        // Set progress callback inside actor context
        await engine.setProgressCallback { [weak self] phase, progress in
            Task { @MainActor in
                self?.analysisPhase = phase
                self?.analysisProgress = progress
            }
        }

        do {
            let result = try await engine.analyse(
                videoURL: videoURL,
                calibration: calibration,
                audioImpactTimestamp: audioImpactTimestamp,
                isRightHanded: isRightHanded
            )

            await MainActor.run {
                lastResult = result
                state = .result

                if let speed = result.impactSpeedMph {
                    audioFeedback.speedResult(mph: speed)
                }
            }
        } catch {
            await MainActor.run {
                state = .error("Analysis failed: \(error.localizedDescription)")
            }
        }
    }

    // MARK: - Reset

    func reset() {
        recordingTimeoutTask?.cancel()
        recordingTimeoutTask = nil
        state = captureMode == .automatic ? .listening : .idle
        lastResult = nil
        lastRecordingURL = nil
        analysisProgress = 0
        audioImpactTimestamp = nil
        audioDetector.reset()
    }
}
