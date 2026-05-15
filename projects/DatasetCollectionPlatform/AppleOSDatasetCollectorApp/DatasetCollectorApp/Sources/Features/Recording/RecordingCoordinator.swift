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
        var surface: String = "mat"
        var cameraHeightMeters: Double = 1.0
        var cameraAngleDegrees: Double = 0.0
        var referenceDevice: String = ""
        var radarClubSpeedMph: String = ""
        var radarBallSpeedMph: String = ""
        var carryDistanceMeters: String = ""
        var totalDistanceMeters: String = ""
        var launchAngleDegrees: String = ""
        var spinRateRpm: String = ""
        var referenceNotes: String = ""
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
    private var safetyStopTask: Task<Void, Never>?
    private var recordingStartTime: Date?

    private let maxRecordingDuration: TimeInterval = 60.0
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
        guard state == .guidanceStep3, metadataIsComplete else { return }
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
        safetyStopTask?.cancel()
        safetyStopTask = nil
        Task { await finishCapture() }
    }

    func reset() {
        countdownTask?.cancel()
        safetyStopTask?.cancel()
        countdownTask = nil
        safetyStopTask = nil
        state = .guidanceStep1
        validationResult = nil
        recordedVideoURL = nil
        recordingDuration = 0
        humanDetected = false
    }

    func retryRecording() {
        countdownTask?.cancel()
        safetyStopTask?.cancel()
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

    var referenceMeasurements: [CollectorReferenceMeasurement] {
        makeReferenceMeasurements(capturedAt: DatasetCollectorDateFormatter.nowISO8601())
    }

    private func makeReferenceMeasurements(capturedAt: String) -> [CollectorReferenceMeasurement] {
        let clubSpeed = parseOptionalDouble(metadata.radarClubSpeedMph)
        let ballSpeed = parseOptionalDouble(metadata.radarBallSpeedMph)
        let carryDistance = parseOptionalDouble(metadata.carryDistanceMeters)
        let totalDistance = parseOptionalDouble(metadata.totalDistanceMeters)
        let launchAngle = parseOptionalDouble(metadata.launchAngleDegrees)
        let spinRate = parseOptionalDouble(metadata.spinRateRpm)
        let device = metadata.referenceDevice.trimmingCharacters(in: .whitespacesAndNewlines)
        let notes = metadata.referenceNotes.trimmingCharacters(in: .whitespacesAndNewlines)
        let hasReference = [
            clubSpeed,
            ballSpeed,
            carryDistance,
            totalDistance,
            launchAngle,
            spinRate
        ].contains { $0 != nil } || !device.isEmpty || !notes.isEmpty
        guard hasReference else { return [] }

        let source = device.localizedCaseInsensitiveContains("trackman")
            ? "trackman_manual"
            : "radar_or_launch_monitor_manual"
        return [
            CollectorReferenceMeasurement(
                source: source,
                device: device.isEmpty ? nil : device,
                capturedAt: capturedAt,
                clubSpeedMph: clubSpeed,
                ballSpeedMph: ballSpeed,
                carryDistanceMeters: carryDistance,
                totalDistanceMeters: totalDistance,
                launchAngleDegrees: launchAngle,
                spinRateRpm: spinRate,
                landingLocation: nil,
                notes: notes.isEmpty ? nil : notes
            )
        ]
    }

    var metadataIsComplete: Bool {
        let required = [
            metadata.clubType,
            metadata.handedness,
            metadata.swingIntensity,
            metadata.surface
        ]
        guard required.allSatisfy({ !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && $0 != "unknown" }) else {
            return false
        }
        return metadata.cameraHeightMeters > 0 && metadata.cameraAngleDegrees >= -45 && metadata.cameraAngleDegrees <= 45
    }

    func canStartRecording(session: CollectorSessionRecord?) -> Bool {
        guard metadataIsComplete, let session else { return false }
        guard !session.environment.sceneType.isEmpty,
              !session.environment.lighting.isEmpty,
              session.environment.tripod,
              let distance = session.environment.distanceMeters else {
            return false
        }
        return distance >= 3.0 && distance <= 5.0
    }

    private func parseOptionalDouble(_ text: String) -> Double? {
        let normalized = text
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .replacingOccurrences(of: ",", with: ".")
        guard !normalized.isEmpty else { return nil }
        return Double(normalized)
    }

    private func beginCapture() {
        do {
            cameraManager.poseDetectionEnabled = false
            let url = try cameraManager.startRecording()
            recordedVideoURL = url
            recordingStartTime = Date()
            state = .recording

            safetyStopTask = Task {
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
