import Accelerate
import AVFoundation
import ARKit
import UIKit
import Vision
import simd

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

struct CameraIntrinsicsSample: Codable, Equatable {
    let fx: Double
    let fy: Double
    let cx: Double
    let cy: Double
    let referenceWidth: Int
    let referenceHeight: Int
    let capturedAt: String
}

struct RecordingAudioStats: Codable, Equatable {
    let sampleRate: Double
    let channelCount: Int
    let durationSeconds: Double
    let peakAmplitude: Double
    let rmsDbfs: Double
    let silenceRatio: Double
    let impactBandPeakHz: Double?
    let impactBandEnergyRatio: Double?
    let frameCount: Int
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
    private var audioDataOutput: AVCaptureAudioDataOutput?
    private var videoDevice: AVCaptureDevice?
    private var audioInput: AVCaptureDeviceInput?
    private let frameCollector = DatasetFrameTimestampCollector()
    private let audioCollector = DatasetAudioCollector()

    private var recordingURL: URL?
    private var recordingContinuation: CheckedContinuation<URL, Error>?

    private let sessionQueue = DispatchQueue(label: "com.datasetcollector.session")
    private let videoQueue = DispatchQueue(label: "com.datasetcollector.videodata", qos: .userInitiated)
    private let audioQueue = DispatchQueue(label: "com.datasetcollector.audiodata", qos: .userInitiated)

    var capturedTimestamps: [TimeInterval] { frameCollector.timestamps }
    var capturedDepthSamples: [DepthSample] { frameCollector.depthSamples }
    var capturedIntrinsics: CameraIntrinsicsSample? { frameCollector.latestIntrinsics() }
    var capturedAudioStats: RecordingAudioStats? { audioCollector.makeStats() }

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

        let bestFormat = try selectHighFPSFormat(device: device)
        try applyHighFPSFormat(device: device, format: bestFormat.format, fps: bestFormat.fps)

        try configureAudio()

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

        if let videoConnection = dataOutput.connection(with: .video),
           videoConnection.isCameraIntrinsicMatrixDeliverySupported {
            videoConnection.isCameraIntrinsicMatrixDeliveryEnabled = true
        }

        let audioOutput = AVCaptureAudioDataOutput()
        if captureSession.canAddOutput(audioOutput) {
            captureSession.addOutput(audioOutput)
            audioOutput.setSampleBufferDelegate(audioCollector, queue: audioQueue)
            audioDataOutput = audioOutput
        }

        let movieOut = AVCaptureMovieFileOutput()
        guard captureSession.canAddOutput(movieOut) else {
            throw DatasetCameraError.cannotAddOutput
        }
        captureSession.addOutput(movieOut)
        movieOutput = movieOut

        captureSession.commitConfiguration()

        try applyHighFPSFormat(device: device, format: bestFormat.format, fps: bestFormat.fps)
        lockMovieOutputFrameRate(movieOutput: movieOut, fps: bestFormat.fps)

        videoDataOutput?.connection(with: .video)?.setDatasetCollectorLandscapeOrientation()
        movieOutput?.connection(with: .video)?.setDatasetCollectorLandscapeOrientation()

        frameCollector.onHumanDetected = { [weak self] detected in
            self?.humanDetected = detected
        }

        isConfigured = true
        hasLiDAR = Self.deviceHasLiDAR
    }

    private func selectHighFPSFormat(device: AVCaptureDevice) throws -> (format: AVCaptureDevice.Format, fps: Float64) {
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
        return (format, bestFPS)
    }

    private func applyHighFPSFormat(device: AVCaptureDevice, format: AVCaptureDevice.Format, fps: Float64) throws {
        try device.lockForConfiguration()
        device.activeFormat = format
        let duration = CMTimeMake(value: 1, timescale: CMTimeScale(fps))
        device.activeVideoMinFrameDuration = duration
        device.activeVideoMaxFrameDuration = duration
        device.unlockForConfiguration()

        DispatchQueue.main.async {
            self.actualFPS = fps
        }
    }

    private func lockMovieOutputFrameRate(movieOutput: AVCaptureMovieFileOutput, fps: Float64) {
        // iOS 不支持在 AVCaptureConnection 上独立锁帧率，统一由 device.activeVideoMinFrameDuration 控制。
    }

    private func configureAudio() throws {
        #if targetEnvironment(simulator)
        return
        #else
        guard let audioDevice = AVCaptureDevice.default(for: .audio) else { return }
        let input = try AVCaptureDeviceInput(device: audioDevice)
        guard captureSession.canAddInput(input) else { return }
        captureSession.addInput(input)
        audioInput = input
        #endif
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

        if let device = videoDevice, actualFPS >= 120 {
            try? applyHighFPSFormat(device: device, format: device.activeFormat, fps: actualFPS)
            lockMovieOutputFrameRate(movieOutput: movieOutput, fps: actualFPS)
        }

        let tempDir = FileManager.default.temporaryDirectory
        let fileName = "dataset_\(UUID().uuidString).mov"
        let url = tempDir.appendingPathComponent(fileName)

        videoDataOutput?.connection(with: .video)?.setDatasetCollectorLandscapeOrientation()
        movieOutput.connection(with: .video)?.setDatasetCollectorLandscapeOrientation()
        frameCollector.startCollecting()
        audioCollector.startCollecting()
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
            self.audioCollector.stopCollecting()
        }
    }

    static func requestPermission() async -> Bool {
        let videoGranted = await requestAccess(for: .video)
        #if targetEnvironment(simulator)
        return videoGranted
        #else
        let audioGranted = await requestAccess(for: .audio)
        return videoGranted && audioGranted
        #endif
    }

    private static func requestAccess(for mediaType: AVMediaType) async -> Bool {
        let status = AVCaptureDevice.authorizationStatus(for: mediaType)
        switch status {
        case .authorized: return true
        case .notDetermined: return await AVCaptureDevice.requestAccess(for: mediaType)
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
    private let intrinsicsSampleInterval = 30
    var poseDetectionEnabled = true
    private var poseDetectionEnabledBeforeRecording: Bool = true

    var onHumanDetected: ((Bool) -> Void)?

    private let intrinsicsLock = NSLock()
    private var _latestIntrinsics: CameraIntrinsicsSample?

    func latestIntrinsics() -> CameraIntrinsicsSample? {
        intrinsicsLock.lock()
        defer { intrinsicsLock.unlock() }
        return _latestIntrinsics
    }

    func startCollecting() {
        timestamps = []
        depthSamples = []
        isCollecting = true
        frameCount = 0
        poseDetectionEnabledBeforeRecording = poseDetectionEnabled
        poseDetectionEnabled = false
    }

    func stopCollecting() {
        isCollecting = false
        poseDetectionEnabled = poseDetectionEnabledBeforeRecording
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

        if frameCount % intrinsicsSampleInterval == 0 {
            captureIntrinsics(from: sampleBuffer)
        }

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

    private func captureIntrinsics(from sampleBuffer: CMSampleBuffer) {
        guard let attachment = CMGetAttachment(
            sampleBuffer,
            key: kCMSampleBufferAttachmentKey_CameraIntrinsicMatrix,
            attachmentModeOut: nil
        ) as? Data else { return }

        var matrix = matrix_float3x3()
        let byteCount = MemoryLayout<matrix_float3x3>.size
        guard attachment.count >= byteCount else { return }
        attachment.withUnsafeBytes { buffer in
            guard let base = buffer.baseAddress else { return }
            memcpy(&matrix, base, byteCount)
        }

        guard let imageBuffer = CMSampleBufferGetImageBuffer(sampleBuffer) else { return }
        let width = CVPixelBufferGetWidth(imageBuffer)
        let height = CVPixelBufferGetHeight(imageBuffer)
        let sample = CameraIntrinsicsSample(
            fx: Double(matrix.columns.0.x),
            fy: Double(matrix.columns.1.y),
            cx: Double(matrix.columns.2.x),
            cy: Double(matrix.columns.2.y),
            referenceWidth: width,
            referenceHeight: height,
            capturedAt: DatasetCollectorDateFormatter.nowISO8601()
        )

        intrinsicsLock.lock()
        _latestIntrinsics = sample
        intrinsicsLock.unlock()
    }
}

final class DatasetAudioCollector: NSObject, AVCaptureAudioDataOutputSampleBufferDelegate {
    private let lock = NSLock()
    private var isCollecting = false
    private var sampleRate: Double = 0
    private var channelCount: Int = 0
    private var totalSamples: Int = 0
    private var sumSquares: Double = 0
    private var peakAmplitude: Double = 0
    private var silentWindowCount: Int = 0
    private var totalWindowCount: Int = 0
    private var impactEnergy: Double = 0
    private var totalEnergy: Double = 0
    private var impactPeakHz: Double = 0
    private var fftSetup: FFTSetup?
    private let fftLog2N: vDSP_Length = 11
    private var fftWindow: [Float] = []
    private var pendingSamples: [Float] = []

    override init() {
        super.init()
        fftSetup = vDSP_create_fftsetup(fftLog2N, FFTRadix(kFFTRadix2))
        fftWindow = [Float](repeating: 0, count: 1 << Int(fftLog2N))
        vDSP_hann_window(&fftWindow, vDSP_Length(fftWindow.count), Int32(vDSP_HANN_NORM))
    }

    deinit {
        if let fftSetup {
            vDSP_destroy_fftsetup(fftSetup)
        }
    }

    func startCollecting() {
        lock.lock()
        defer { lock.unlock() }
        isCollecting = true
        totalSamples = 0
        sumSquares = 0
        peakAmplitude = 0
        silentWindowCount = 0
        totalWindowCount = 0
        impactEnergy = 0
        totalEnergy = 0
        impactPeakHz = 0
        pendingSamples.removeAll(keepingCapacity: true)
    }

    func stopCollecting() {
        lock.lock()
        defer { lock.unlock() }
        isCollecting = false
    }

    func makeStats() -> RecordingAudioStats? {
        lock.lock()
        defer { lock.unlock() }
        guard totalSamples > 0, sampleRate > 0 else { return nil }
        let duration = Double(totalSamples) / sampleRate / max(Double(channelCount), 1)
        let rms = (sumSquares / Double(totalSamples)).squareRoot()
        let rmsDb = rms > 0 ? 20 * log10(rms) : -120.0
        let silenceRatio = totalWindowCount > 0
            ? Double(silentWindowCount) / Double(totalWindowCount)
            : 1.0
        let impactRatio = totalEnergy > 0 ? impactEnergy / totalEnergy : 0
        return RecordingAudioStats(
            sampleRate: sampleRate,
            channelCount: channelCount,
            durationSeconds: duration,
            peakAmplitude: peakAmplitude,
            rmsDbfs: rmsDb,
            silenceRatio: silenceRatio,
            impactBandPeakHz: impactPeakHz > 0 ? impactPeakHz : nil,
            impactBandEnergyRatio: impactRatio.isFinite ? impactRatio : nil,
            frameCount: totalSamples
        )
    }

    func captureOutput(
        _ output: AVCaptureOutput,
        didOutput sampleBuffer: CMSampleBuffer,
        from connection: AVCaptureConnection
    ) {
        lock.lock()
        let collecting = isCollecting
        lock.unlock()
        guard collecting else { return }

        guard let formatDescription = CMSampleBufferGetFormatDescription(sampleBuffer),
              let asbd = CMAudioFormatDescriptionGetStreamBasicDescription(formatDescription)?.pointee
        else { return }

        let numSamples = CMSampleBufferGetNumSamples(sampleBuffer)
        guard numSamples > 0 else { return }

        var length: Int = 0
        var dataPointer: UnsafeMutablePointer<Int8>? = nil
        guard let blockBuffer = CMSampleBufferGetDataBuffer(sampleBuffer),
              CMBlockBufferGetDataPointer(blockBuffer, atOffset: 0, lengthAtOffsetOut: nil, totalLengthOut: &length, dataPointerOut: &dataPointer) == kCMBlockBufferNoErr,
              let rawPtr = dataPointer else { return }

        let channels = max(Int(asbd.mChannelsPerFrame), 1)
        let floatFlag = asbd.mFormatFlags & kAudioFormatFlagIsFloat != 0
        let bitsPerChannel = Int(asbd.mBitsPerChannel)
        let totalFrames = numSamples

        var monoSamples = [Float](repeating: 0, count: totalFrames)
        if floatFlag && bitsPerChannel == 32 {
            rawPtr.withMemoryRebound(to: Float32.self, capacity: totalFrames * channels) { ptr in
                for i in 0..<totalFrames {
                    var sum: Float = 0
                    for c in 0..<channels {
                        sum += ptr[i * channels + c]
                    }
                    monoSamples[i] = sum / Float(channels)
                }
            }
        } else if bitsPerChannel == 16 {
            rawPtr.withMemoryRebound(to: Int16.self, capacity: totalFrames * channels) { ptr in
                for i in 0..<totalFrames {
                    var sum: Int32 = 0
                    for c in 0..<channels {
                        sum += Int32(ptr[i * channels + c])
                    }
                    monoSamples[i] = Float(sum) / Float(channels) / Float(Int16.max)
                }
            }
        } else {
            return
        }

        lock.lock()
        defer { lock.unlock() }
        sampleRate = asbd.mSampleRate
        channelCount = channels
        totalSamples += totalFrames

        var localSum: Double = 0
        var localPeak: Double = 0
        for sample in monoSamples {
            let v = Double(sample)
            localSum += v * v
            let abs = v < 0 ? -v : v
            if abs > localPeak { localPeak = abs }
        }
        sumSquares += localSum
        if localPeak > peakAmplitude { peakAmplitude = localPeak }

        pendingSamples.append(contentsOf: monoSamples)
        runFFTIfReady()
    }

    private func runFFTIfReady() {
        let frameSize = 1 << Int(fftLog2N)
        guard pendingSamples.count >= frameSize, let fftSetup else { return }
        let halfSize = frameSize / 2
        let nyquist = sampleRate / 2

        while pendingSamples.count >= frameSize {
            var frame = Array(pendingSamples.prefix(frameSize))
            pendingSamples.removeFirst(frameSize)

            var windowed = [Float](repeating: 0, count: frameSize)
            vDSP_vmul(frame, 1, fftWindow, 1, &windowed, 1, vDSP_Length(frameSize))

            var realp = [Float](repeating: 0, count: halfSize)
            var imagp = [Float](repeating: 0, count: halfSize)
            realp.withUnsafeMutableBufferPointer { rBuf in
                imagp.withUnsafeMutableBufferPointer { iBuf in
                    var splitComplex = DSPSplitComplex(realp: rBuf.baseAddress!, imagp: iBuf.baseAddress!)
                    windowed.withUnsafeBufferPointer { wBuf in
                        wBuf.baseAddress!.withMemoryRebound(to: DSPComplex.self, capacity: halfSize) { cPtr in
                            vDSP_ctoz(cPtr, 2, &splitComplex, 1, vDSP_Length(halfSize))
                        }
                    }
                    vDSP_fft_zrip(fftSetup, &splitComplex, 1, fftLog2N, FFTDirection(FFT_FORWARD))
                    var magnitudes = [Float](repeating: 0, count: halfSize)
                    vDSP_zvmags(&splitComplex, 1, &magnitudes, 1, vDSP_Length(halfSize))

                    let binWidth = nyquist / Double(halfSize)
                    let lowBin = max(Int(2000.0 / binWidth), 1)
                    let highBin = min(Int(5000.0 / binWidth), halfSize - 1)
                    var bandEnergy: Float = 0
                    var peakBinMag: Float = 0
                    var peakBinIdx = 0
                    var total: Float = 0
                    for i in 1..<halfSize {
                        total += magnitudes[i]
                        if i >= lowBin && i <= highBin {
                            bandEnergy += magnitudes[i]
                            if magnitudes[i] > peakBinMag {
                                peakBinMag = magnitudes[i]
                                peakBinIdx = i
                            }
                        }
                    }
                    totalEnergy += Double(total)
                    impactEnergy += Double(bandEnergy)
                    let frameRMS = windowed.reduce(0) { $0 + $1 * $1 } / Float(frameSize)
                    totalWindowCount += 1
                    if frameRMS < 1e-6 {
                        silentWindowCount += 1
                    }
                    if peakBinMag > 0 {
                        let hz = Double(peakBinIdx) * binWidth
                        if bandEnergy > Float(impactEnergy - Double(bandEnergy)) * 0.1 {
                            impactPeakHz = hz
                        }
                    }
                }
            }
        }
    }
}
