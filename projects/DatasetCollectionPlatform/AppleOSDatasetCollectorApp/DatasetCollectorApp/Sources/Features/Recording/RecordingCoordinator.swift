import AVFoundation
import Foundation

@MainActor
@Observable
final class RecordingCoordinator {

    enum State: Equatable {
        case guidanceStep1
        case guidanceStep2
        case guidanceStep3
        case countdown(Int)
        case recording
        case validating
        case result(passed: Bool)
    }

    struct RecordingMetadata {
        var clubType: String = "driver"
        var handedness: String = "right"
        var swingIntensity: String = "normal"
    }

    private(set) var state: State = .guidanceStep1
    private(set) var validationResult: ValidationResult?
    private(set) var recordedVideoURL: URL?
    private(set) var recordingDuration: TimeInterval = 0
    private(set) var humanDetected = false
    private(set) var lidarCalibration: LiDARCalibrationData?

    var metadata = RecordingMetadata()

    private let cameraManager: DatasetCameraManager
    private let validator = RecordingValidator()
    private var countdownTask: Task<Void, Never>?
    private var autoStopTask: Task<Void, Never>?
    private var recordingStartTime: Date?

    private let maxRecordingDuration: TimeInterval = 4.0
    private let countdownSeconds = 3

    init(cameraManager: DatasetCameraManager) {
        self.cameraManager = cameraManager
    }

    func advanceFromStep1() {
        guard state == .guidanceStep1 else { return }
        state = .guidanceStep2
    }

    func advanceFromStep2() {
        guard state == .guidanceStep2 else { return }
        state = .guidanceStep3
    }

    func startRecording() {
        guard state == .guidanceStep3 else { return }
        state = .countdown(countdownSeconds)
        countdownTask = Task {
            for i in stride(from: countdownSeconds, through: 1, by: -1) {
                state = .countdown(i)
                try? await Task.sleep(for: .seconds(1))
                guard !Task.isCancelled else { return }
            }
            beginCapture()
        }
    }

    func stopRecording() {
        guard state == .recording else { return }
        autoStopTask?.cancel()
        autoStopTask = nil
        Task { await finishCapture() }
    }

    func reset() {
        countdownTask?.cancel()
        autoStopTask?.cancel()
        countdownTask = nil
        autoStopTask = nil
        state = .guidanceStep1
        validationResult = nil
        recordedVideoURL = nil
        recordingDuration = 0
        humanDetected = false
    }

    func retryRecording() {
        countdownTask?.cancel()
        autoStopTask?.cancel()
        state = .guidanceStep3
        validationResult = nil
        recordedVideoURL = nil
        recordingDuration = 0
    }

    func setHumanDetected(_ detected: Bool) {
        humanDetected = detected
    }

    func setLiDARCalibration(_ calibration: LiDARCalibrationData?) {
        lidarCalibration = calibration
    }

    private func beginCapture() {
        do {
            cameraManager.poseDetectionEnabled = false
            let url = try cameraManager.startRecording()
            recordedVideoURL = url
            recordingStartTime = Date()
            state = .recording

            autoStopTask = Task {
                try? await Task.sleep(for: .seconds(maxRecordingDuration))
                guard !Task.isCancelled else { return }
                await finishCapture()
            }
        } catch {
            cameraManager.poseDetectionEnabled = true
            state = .result(passed: false)
            validationResult = ValidationResult(
                passed: false,
                checks: [ValidationCheck(name: "录制", passed: false, detail: error.localizedDescription)]
            )
        }
    }

    private func finishCapture() async {
        cameraManager.poseDetectionEnabled = true
        do {
            let url = try await cameraManager.stopRecording()
            recordedVideoURL = url
            if let start = recordingStartTime {
                recordingDuration = Date().timeIntervalSince(start)
            }

            state = .validating
            let timestamps = cameraManager.capturedTimestamps
            let result = await validator.validate(videoURL: url, timestamps: timestamps)
            validationResult = result
            state = .result(passed: result.passed)
        } catch {
            state = .result(passed: false)
            validationResult = ValidationResult(
                passed: false,
                checks: [ValidationCheck(name: "停止录制", passed: false, detail: error.localizedDescription)]
            )
        }
    }
}
