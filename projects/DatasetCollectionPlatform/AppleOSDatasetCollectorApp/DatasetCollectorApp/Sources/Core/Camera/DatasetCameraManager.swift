import AVFoundation
import ARKit
import UIKit
import Vision

enum DatasetCameraError: LocalizedError {
    case deviceNotFound
    case cannotAddInput
    case cannotAddOutput
    case highFPSNotSupported
    case alreadyRecording
    case notRecording
    case recordingFailed(Error)
    case permissionDenied

    var errorDescription: String? {
        switch self {
        case .deviceNotFound: return "未找到后置摄像头"
        case .cannotAddInput: return "无法配置摄像头输入"
        case .cannotAddOutput: return "无法配置摄像头输出"
        case .highFPSNotSupported: return "设备不支持高帧率"
        case .alreadyRecording: return "已在录制中"
        case .notRecording: return "当前未在录制"
        case .recordingFailed(let e): return "录制失败: \(e.localizedDescription)"
        case .permissionDenied: return "相机权限被拒绝"
        }
    }
}

struct LiDARCalibrationData: Codable {
    let cameraToGroundDistance: Double
    let groundPlaneY: Float
    let cameraHeight: Double
    let cameraAngle: Double
    let capturedAt: String
}

struct DepthSample: Codable {
    let timestamp: TimeInterval
    let centerDepth: Float
}

final class DatasetCameraManager: NSObject, ObservableObject {
    let captureSession = AVCaptureSession()

    @Published var isConfigured = false
    @Published var isRunning = false
    @Published var isRecording = false
    @Published var actualFPS: Double = 0
    @Published var hasLiDAR = false
    @Published var humanDetected = false

    var poseDetectionEnabled: Bool {
        get { frameCollector.poseDetectionEnabled }
        set {
            frameCollector.poseDetectionEnabled = newValue
            if !newValue {
                humanDetected = false
            }
        }
    }

    private var movieOutput: AVCaptureMovieFileOutput?
    private var videoDataOutput: AVCaptureVideoDataOutput?
    private var videoDevice: AVCaptureDevice?
    private let frameCollector = DatasetFrameTimestampCollector()

    private var recordingURL: URL?
    private var recordingContinuation: CheckedContinuation<URL, Error>?

    private let sessionQueue = DispatchQueue(label: "com.datasetcollector.session")
    private let videoQueue = DispatchQueue(label: "com.datasetcollector.videodata", qos: .userInitiated)

    var capturedTimestamps: [TimeInterval] { frameCollector.timestamps }
    var capturedDepthSamples: [DepthSample] { frameCollector.depthSamples }

    static var deviceHasLiDAR: Bool {
        ARWorldTrackingConfiguration.supportsSceneReconstruction(.mesh)
    }

    func configure() throws {
        guard !isConfigured else { return }

        guard let device = AVCaptureDevice.default(
            .builtInWideAngleCamera, for: .video, position: .back
        ) else {
            throw DatasetCameraError.deviceNotFound
        }

        videoDevice = device
        captureSession.beginConfiguration()
        captureSession.sessionPreset = .inputPriority

        let input = try AVCaptureDeviceInput(device: device)
        guard captureSession.canAddInput(input) else {
            throw DatasetCameraError.cannotAddInput
        }
        captureSession.addInput(input)

        try configureHighFPS(device: device)

        let dataOutput = AVCaptureVideoDataOutput()
        dataOutput.alwaysDiscardsLateVideoFrames = true
        dataOutput.videoSettings = [
            kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA
        ]
        guard captureSession.canAddOutput(dataOutput) else {
            throw DatasetCameraError.cannotAddOutput
        }
        captureSession.addOutput(dataOutput)
        videoDataOutput = dataOutput
        dataOutput.setSampleBufferDelegate(frameCollector, queue: videoQueue)

        let movieOut = AVCaptureMovieFileOutput()
        guard captureSession.canAddOutput(movieOut) else {
            throw DatasetCameraError.cannotAddOutput
        }
        captureSession.addOutput(movieOut)
        movieOutput = movieOut

        captureSession.commitConfiguration()

        videoDataOutput?.connection(with: .video)?.setDatasetCollectorLandscapeOrientation()
        movieOutput?.connection(with: .video)?.setDatasetCollectorLandscapeOrientation()

        frameCollector.onHumanDetected = { [weak self] detected in
            self?.humanDetected = detected
        }

        isConfigured = true
        hasLiDAR = Self.deviceHasLiDAR
    }

    private func configureHighFPS(device: AVCaptureDevice) throws {
        var bestFormat: AVCaptureDevice.Format?
        var bestFPS: Float64 = 0

        for format in device.formats {
            let dims = CMVideoFormatDescriptionGetDimensions(format.formatDescription)
            guard dims.width == 1920, dims.height == 1080 else { continue }
            for range in format.videoSupportedFrameRateRanges {
                if range.maxFrameRate > bestFPS {
                    bestFPS = range.maxFrameRate
                    bestFormat = format
                }
            }
        }

        guard let format = bestFormat, bestFPS >= 120 else {
            throw DatasetCameraError.highFPSNotSupported
        }

        try device.lockForConfiguration()
        device.activeFormat = format
        device.activeVideoMinFrameDuration = CMTime(value: 1, timescale: CMTimeScale(bestFPS))
        device.activeVideoMaxFrameDuration = CMTime(value: 1, timescale: CMTimeScale(bestFPS))
        device.unlockForConfiguration()

        DispatchQueue.main.async {
            self.actualFPS = bestFPS
        }
    }

    func startSession() {
        guard isConfigured, !captureSession.isRunning else { return }
        sessionQueue.async { [weak self] in
            guard let self else { return }
            self.captureSession.startRunning()
            DispatchQueue.main.async {
                self.isRunning = true
            }
        }
    }

    func stopSession() {
        guard captureSession.isRunning else { return }
        sessionQueue.async { [weak self] in
            guard let self else { return }
            self.captureSession.stopRunning()
            DispatchQueue.main.async {
                self.isRunning = false
            }
        }
    }

    func startRecording() throws -> URL {
        guard let movieOutput, !isRecording else {
            throw DatasetCameraError.alreadyRecording
        }

        let tempDir = FileManager.default.temporaryDirectory
        let fileName = "dataset_\(UUID().uuidString).mov"
        let url = tempDir.appendingPathComponent(fileName)

        videoDataOutput?.connection(with: .video)?.setDatasetCollectorLandscapeOrientation()
        movieOutput.connection(with: .video)?.setDatasetCollectorLandscapeOrientation()
        frameCollector.startCollecting()
        recordingURL = url
        movieOutput.startRecording(to: url, recordingDelegate: self)
        isRecording = true
        return url
    }

    func stopRecording() async throws -> URL {
        guard let movieOutput, isRecording, let url = recordingURL else {
            throw DatasetCameraError.notRecording
        }

        return try await withCheckedThrowingContinuation { continuation in
            self.recordingContinuation = continuation
            movieOutput.stopRecording()
            self.isRecording = false
            self.frameCollector.stopCollecting()
        }
    }

    static func requestPermission() async -> Bool {
        let status = AVCaptureDevice.authorizationStatus(for: .video)
        switch status {
        case .authorized: return true
        case .notDetermined: return await AVCaptureDevice.requestAccess(for: .video)
        default: return false
        }
    }

    static var isAuthorized: Bool {
        AVCaptureDevice.authorizationStatus(for: .video) == .authorized
    }
}

extension AVCaptureConnection {
    func setDatasetCollectorLandscapeOrientation() {
        guard isVideoOrientationSupported else { return }
        let orientation = UIApplication.shared.connectedScenes
            .compactMap { ($0 as? UIWindowScene)?.interfaceOrientation }
            .first { $0 != .unknown }

        switch orientation {
        case .landscapeLeft:
            videoOrientation = .landscapeLeft
        case .landscapeRight:
            videoOrientation = .landscapeRight
        default:
            videoOrientation = .landscapeRight
        }
    }
}

extension DatasetCameraManager: AVCaptureFileOutputRecordingDelegate {
    func fileOutput(
        _ output: AVCaptureFileOutput,
        didFinishRecordingTo outputFileURL: URL,
        from connections: [AVCaptureConnection],
        error: Error?
    ) {
        if let error {
            recordingContinuation?.resume(throwing: DatasetCameraError.recordingFailed(error))
        } else {
            recordingContinuation?.resume(returning: outputFileURL)
        }
        recordingContinuation = nil
    }
}

final class DatasetFrameTimestampCollector: NSObject, AVCaptureVideoDataOutputSampleBufferDelegate {
    private(set) var timestamps: [TimeInterval] = []
    private(set) var depthSamples: [DepthSample] = []
    private var isCollecting = false
    private var frameCount = 0
    private let poseDetectionInterval = 12
    var poseDetectionEnabled = true

    var onHumanDetected: ((Bool) -> Void)?

    func startCollecting() {
        timestamps = []
        depthSamples = []
        isCollecting = true
        frameCount = 0
    }

    func stopCollecting() {
        isCollecting = false
    }

    func captureOutput(
        _ output: AVCaptureOutput,
        didOutput sampleBuffer: CMSampleBuffer,
        from connection: AVCaptureConnection
    ) {
        let pts = CMSampleBufferGetPresentationTimeStamp(sampleBuffer)
        if isCollecting {
            timestamps.append(CMTimeGetSeconds(pts))
        }

        frameCount += 1
        guard poseDetectionEnabled, frameCount % poseDetectionInterval == 0 else { return }

        guard let pixelBuffer = CMSampleBufferGetImageBuffer(sampleBuffer) else { return }
        let request = VNDetectHumanBodyPoseRequest()
        let handler = VNImageRequestHandler(cvPixelBuffer: pixelBuffer, orientation: .right, options: [:])

        do {
            try handler.perform([request])
            let detected = request.results?.isEmpty == false
            DispatchQueue.main.async { self.onHumanDetected?(detected) }
        } catch {
            DispatchQueue.main.async { self.onHumanDetected?(false) }
        }
    }
}
