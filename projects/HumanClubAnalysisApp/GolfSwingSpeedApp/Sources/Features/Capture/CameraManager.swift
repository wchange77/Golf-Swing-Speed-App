import AVFoundation
import UIKit

actor CameraManager {
    private let captureSession = AVCaptureSession()
    private var videoOutput: AVCaptureVideoDataOutput?
    private var movieOutput: AVCaptureMovieFileOutput?
    private var photoOutput: AVCapturePhotoOutput?
    private var videoDevice: AVCaptureDevice?
    private let frameTimestampCollector = FrameTimestampCollector()

    private(set) var isConfigured = false
    private(set) var isRecording = false
    private(set) var actualFPS: Double = 0

    // Frame buffer for post-capture analysis
    var capturedFrameTimestamps: [TimeInterval] {
        frameTimestampCollector.timestamps
    }
    private var recordingURL: URL?
    private var recordingDelegate: MovieRecordingDelegate?

    /// Get the capture session for creating a preview layer on the main thread.
    nonisolated var session: AVCaptureSession {
        captureSession
    }

    // MARK: - Configuration

    func configure() throws {
        guard !isConfigured else { return }

        guard let device = AVCaptureDevice.default(
            .builtInWideAngleCamera,
            for: .video,
            position: .back
        ) else {
            throw CameraError.deviceNotFound
        }

        videoDevice = device
        captureSession.beginConfiguration()
        captureSession.sessionPreset = .inputPriority

        // Add video input
        let input = try AVCaptureDeviceInput(device: device)
        guard captureSession.canAddInput(input) else {
            throw CameraError.cannotAddInput
        }
        captureSession.addInput(input)

        // Configure for highest available FPS at 1080p
        try configureHighFPS(device: device)

        // Add video data output for frame-level access
        let dataOutput = AVCaptureVideoDataOutput()
        dataOutput.alwaysDiscardsLateVideoFrames = true
        dataOutput.videoSettings = [
            kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA
        ]
        guard captureSession.canAddOutput(dataOutput) else {
            throw CameraError.cannotAddOutput
        }
        captureSession.addOutput(dataOutput)
        videoOutput = dataOutput

        // Set sample buffer delegate to collect frame timestamps during recording
        let delegateQueue = DispatchQueue(label: "com.golfswingspeed.videodata", qos: .userInitiated)
        dataOutput.setSampleBufferDelegate(frameTimestampCollector, queue: delegateQueue)

        // Add movie file output for recording
        let movieOut = AVCaptureMovieFileOutput()
        guard captureSession.canAddOutput(movieOut) else {
            throw CameraError.cannotAddOutput
        }
        captureSession.addOutput(movieOut)
        movieOutput = movieOut

        // Add photo output for calibration snapshots
        let photoOut = AVCapturePhotoOutput()
        guard captureSession.canAddOutput(photoOut) else {
            throw CameraError.cannotAddOutput
        }
        captureSession.addOutput(photoOut)
        photoOutput = photoOut

        captureSession.commitConfiguration()
        isConfigured = true
    }

    private func configureHighFPS(device: AVCaptureDevice) throws {
        // Find the best format: 1080p at highest FPS available
        var bestFormat: AVCaptureDevice.Format?
        var bestFPS: Float64 = 0

        for format in device.formats {
            let dimensions = CMVideoFormatDescriptionGetDimensions(format.formatDescription)
            guard dimensions.width == Int32(AppConstants.Camera.captureWidth),
                  dimensions.height == Int32(AppConstants.Camera.captureHeight) else {
                continue
            }

            for range in format.videoSupportedFrameRateRanges {
                if range.maxFrameRate > bestFPS {
                    bestFPS = range.maxFrameRate
                    bestFormat = format
                }
            }
        }

        guard let format = bestFormat else {
            throw CameraError.highFPSNotSupported
        }

        try device.lockForConfiguration()
        device.activeFormat = format
        device.activeVideoMinFrameDuration = CMTime(value: 1, timescale: CMTimeScale(bestFPS))
        device.activeVideoMaxFrameDuration = CMTime(value: 1, timescale: CMTimeScale(bestFPS))
        device.unlockForConfiguration()

        actualFPS = bestFPS
    }

    // MARK: - Session Control

    func startSession() {
        guard isConfigured, !captureSession.isRunning else { return }
        captureSession.startRunning()
    }

    func stopSession() {
        guard captureSession.isRunning else { return }
        captureSession.stopRunning()
    }

    // MARK: - Recording

    func startRecording() throws -> URL {
        guard let movieOutput, !isRecording else {
            throw CameraError.alreadyRecording
        }

        let tempDir = FileManager.default.temporaryDirectory
        let fileName = "swing_\(UUID().uuidString).mov"
        let url = tempDir.appendingPathComponent(fileName)

        frameTimestampCollector.startCollecting()
        recordingURL = url

        let delegate = MovieRecordingDelegate()
        recordingDelegate = delegate
        movieOutput.startRecording(to: url, recordingDelegate: delegate)
        isRecording = true

        return url
    }

    func stopRecording() async throws -> URL {
        guard let movieOutput, isRecording, let url = recordingURL else {
            throw CameraError.notRecording
        }

        movieOutput.stopRecording()
        isRecording = false
        frameTimestampCollector.stopCollecting()

        // Wait for recording to finish
        if let delegate = recordingDelegate {
            try await delegate.waitForCompletion()
        }

        return url
    }

    // MARK: - Photo Capture

    func takePhoto() async throws -> UIImage {
        guard let photoOutput else {
            throw CameraError.cannotAddOutput
        }

        let settings = AVCapturePhotoSettings()
        let delegate = PhotoCaptureDelegate()
        photoOutput.capturePhoto(with: settings, delegate: delegate)
        return try await delegate.waitForPhoto()
    }

    // Frame timestamp collection is handled by FrameTimestampCollector (sample buffer delegate)

    // MARK: - Permission

    static func requestPermission() async -> Bool {
        let status = AVCaptureDevice.authorizationStatus(for: .video)
        switch status {
        case .authorized:
            return true
        case .notDetermined:
            return await AVCaptureDevice.requestAccess(for: .video)
        default:
            return false
        }
    }

    static var isAuthorized: Bool {
        AVCaptureDevice.authorizationStatus(for: .video) == .authorized
    }
}

// MARK: - Errors

enum CameraError: LocalizedError {
    case deviceNotFound
    case cannotAddInput
    case cannotAddOutput
    case highFPSNotSupported
    case alreadyRecording
    case notRecording
    case recordingFailed(Error)

    var errorDescription: String? {
        switch self {
        case .deviceNotFound: return "No camera found"
        case .cannotAddInput: return "Cannot configure camera input"
        case .cannotAddOutput: return "Cannot configure camera output"
        case .highFPSNotSupported: return "240fps not supported on this device"
        case .alreadyRecording: return "Already recording"
        case .notRecording: return "Not currently recording"
        case .recordingFailed(let error): return "Recording failed: \(error.localizedDescription)"
        }
    }
}

// MARK: - Recording Delegate

final class MovieRecordingDelegate: NSObject, AVCaptureFileOutputRecordingDelegate, Sendable {
    private let continuation = UnsafeContinuation<Void, Error>.self
    private var completionHandler: CheckedContinuation<Void, Error>?

    func fileOutput(
        _ output: AVCaptureFileOutput,
        didFinishRecordingTo outputFileURL: URL,
        from connections: [AVCaptureConnection],
        error: Error?
    ) {
        if let error {
            completionHandler?.resume(throwing: CameraError.recordingFailed(error))
        } else {
            completionHandler?.resume()
        }
    }

    func waitForCompletion() async throws {
        try await withCheckedThrowingContinuation { continuation in
            self.completionHandler = continuation
        }
    }
}

// MARK: - Photo Capture Delegate

final class PhotoCaptureDelegate: NSObject, AVCapturePhotoCaptureDelegate {
    private var photoContinuation: CheckedContinuation<UIImage, Error>?

    func photoOutput(
        _ output: AVCapturePhotoOutput,
        didFinishProcessingPhoto photo: AVCapturePhoto,
        error: Error?
    ) {
        if let error {
            photoContinuation?.resume(throwing: error)
            return
        }

        guard let data = photo.fileDataRepresentation(),
              let image = UIImage(data: data) else {
            photoContinuation?.resume(throwing: CameraError.recordingFailed(
                NSError(domain: "CameraManager", code: -1, userInfo: [NSLocalizedDescriptionKey: "Failed to create image from photo data"])
            ))
            return
        }

        photoContinuation?.resume(returning: image)
    }

    func waitForPhoto() async throws -> UIImage {
        try await withCheckedThrowingContinuation { continuation in
            self.photoContinuation = continuation
        }
    }
}

// MARK: - Frame Timestamp Collector

/// Collects frame timestamps from the video data output during recording.
/// Implements AVCaptureVideoDataOutputSampleBufferDelegate to receive every frame.
final class FrameTimestampCollector: NSObject, AVCaptureVideoDataOutputSampleBufferDelegate {
    private(set) var timestamps: [TimeInterval] = []
    private var isCollecting = false

    func startCollecting() {
        timestamps = []
        isCollecting = true
    }

    func stopCollecting() {
        isCollecting = false
    }

    func captureOutput(
        _ output: AVCaptureOutput,
        didOutput sampleBuffer: CMSampleBuffer,
        from connection: AVCaptureConnection
    ) {
        guard isCollecting else { return }
        let pts = CMSampleBufferGetPresentationTimeStamp(sampleBuffer)
        let timestamp = CMTimeGetSeconds(pts)
        timestamps.append(timestamp)
    }

    func captureOutput(
        _ output: AVCaptureOutput,
        didDrop sampleBuffer: CMSampleBuffer,
        from connection: AVCaptureConnection
    ) {
        // Frame dropped — can log this for diagnostics
    }
}
