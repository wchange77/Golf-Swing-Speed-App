import Foundation
import AVFoundation
import Vision
import CoreImage

/// Orchestrates the full post-capture analysis pipeline.
///
/// After a swing is captured as a video file, this engine:
/// 1. Pass 1: Fast phase detection (~30fps) to classify swing segments
/// 2. Pass 2: Adaptive frame selection based on phase
/// 3. For each selected frame: 3D body pose + club head detection/tracking
/// 4. Speed calculation from tracked positions
/// 5. Lag angle analysis from 3D pose + club positions
/// 6. Build final SwingRecord with all metrics
actor PostCaptureAnalysisEngine {

    // MARK: - Analysis Result

    struct AnalysisResult {
        var speedProfile: SpeedProfile?
        var lagMetrics: LagMetrics?
        var impactTimestamp: TimeInterval?
        var impactSpeedMph: Double?
        var confidenceScore: Double
        var framesAnalysed: Int
        var totalFrames: Int
        var processingTimeSeconds: Double
    }

    // MARK: - Progress

    enum AnalysisPhase: String {
        case loadingVideo = "Loading video"
        case phaseDetection = "Detecting swing phases"
        case frameSelection = "Selecting analysis frames"
        case bodyPose = "Analysing body pose"
        case clubTracking = "Tracking club head"
        case speedCalculation = "Calculating speed"
        case lagAnalysis = "Analysing lag"
        case complete = "Complete"
    }

    var onProgress: ((AnalysisPhase, Double) -> Void)?

    func setProgressCallback(_ callback: @escaping (AnalysisPhase, Double) -> Void) {
        onProgress = callback
    }

    // MARK: - Dependencies

    private let trackingPipeline: TrackingPipeline
    private let clubHeadDetector: ClubHeadDetector?

    init(
        trackingPipeline: TrackingPipeline = TrackingPipeline(),
        clubHeadDetector: ClubHeadDetector? = nil
    ) {
        self.trackingPipeline = trackingPipeline
        self.clubHeadDetector = clubHeadDetector
    }

    // MARK: - Analyse

    /// Run full analysis pipeline on a captured swing video.
    func analyse(
        videoURL: URL,
        calibration: CalibrationSnapshot,
        audioImpactTimestamp: TimeInterval?,
        isRightHanded: Bool = true
    ) async throws -> AnalysisResult {
        let startTime = CFAbsoluteTimeGetCurrent()

        // Step 1: Load video and extract frame info
        onProgress?(.loadingVideo, 0)
        let asset = AVURLAsset(url: videoURL)
        let videoTrack = try await asset.loadTracks(withMediaType: .video).first
        guard let track = videoTrack else {
            throw AnalysisError.noVideoTrack
        }

        let duration = try await asset.load(.duration)
        let nominalFPS = try await track.load(.nominalFrameRate)
        let totalFrameCount = Int(CMTimeGetSeconds(duration) * Double(nominalFPS))

        // Step 2: Fast pass — extract motion magnitudes at ~30fps for phase detection
        onProgress?(.phaseDetection, 0.1)
        let (timestamps, motionMagnitudes) = try await extractMotionData(
            asset: asset,
            sampleFPS: 30,
            totalFrameCount: totalFrameCount
        )

        // Step 3: Classify phases and select frames
        onProgress?(.frameSelection, 0.15)
        let phases = AdaptiveFrameSampler.classifyPhases(
            frameTimestamps: timestamps,
            motionMagnitudes: motionMagnitudes,
            impactTimestamp: audioImpactTimestamp,
            captureFPS: Double(nominalFPS)
        )

        let selectedIndices = AdaptiveFrameSampler.selectFrames(
            phases: phases,
            totalFrameCount: totalFrameCount,
            captureFPS: Double(nominalFPS)
        )

        let report = AdaptiveFrameSampler.samplingReport(
            selectedCount: selectedIndices.count,
            totalCount: totalFrameCount
        )

        // Step 4: Process selected frames — 3D body pose + club tracking
        onProgress?(.bodyPose, 0.2)
        var bodyPoses: [BodyPoseFrame] = []
        var trackedPositions: [TrackedPosition] = []

        await trackingPipeline.reset()

        let reader = try AVAssetReader(asset: asset)
        let outputSettings: [String: Any] = [
            kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA
        ]
        let readerOutput = AVAssetReaderTrackOutput(track: track, outputSettings: outputSettings)
        reader.add(readerOutput)
        reader.startReading()

        var frameIndex = 0
        var selectedSet = Set(selectedIndices)
        var previousTimestamp: TimeInterval?

        while let sampleBuffer = readerOutput.copyNextSampleBuffer() {
            defer { frameIndex += 1 }

            guard selectedSet.contains(frameIndex) else { continue }

            let pts = CMSampleBufferGetPresentationTimeStamp(sampleBuffer)
            let timestamp = CMTimeGetSeconds(pts)

            guard let pixelBuffer = CMSampleBufferGetImageBuffer(sampleBuffer) else { continue }

            // 3D Body Pose
            let poseRequest = VNDetectHumanBodyPose3DRequest()
            let handler = VNImageRequestHandler(cvPixelBuffer: pixelBuffer, options: [:])
            try? handler.perform([poseRequest])

            if let observation = poseRequest.results?.first {
                if let poseFrame = BodyPoseFrame.from(
                    observation: observation,
                    timestamp: timestamp,
                    isRightHanded: isRightHanded
                ) {
                    bodyPoses.append(poseFrame)
                }
            }

            // Club head tracking
            let wristPosition = bodyPoses.last?.leadWrist2D
            if let tracked = await trackingPipeline.processFrame(
                pixelBuffer: pixelBuffer,
                timestamp: timestamp,
                previousTimestamp: previousTimestamp,
                wristPosition: wristPosition,
                clubHeadDetector: clubHeadDetector
            ) {
                trackedPositions.append(tracked)
            }

            previousTimestamp = timestamp

            // Progress update
            let progress = 0.2 + 0.6 * Double(frameIndex) / Double(totalFrameCount)
            onProgress?(.clubTracking, progress)
        }

        // Step 5: Speed calculation
        onProgress?(.speedCalculation, 0.85)
        let speedProfile = SpeedCalculator.buildSpeedProfile(
            from: trackedPositions,
            calibration: calibration,
            impactTimestamp: audioImpactTimestamp
        )

        // Step 6: Lag analysis
        onProgress?(.lagAnalysis, 0.9)
        let lagMetrics = LagAnalyser.analyse(
            bodyPoses: bodyPoses,
            clubHeadPositions: trackedPositions,
            impactTimestamp: audioImpactTimestamp ?? speedProfile?.impactTimestamp,
            calibration: calibration
        )

        // Step 7: Build result
        onProgress?(.complete, 1.0)
        let processingTime = CFAbsoluteTimeGetCurrent() - startTime

        let confidence: Double
        if let dataPoints = speedProfile?.dataPoints, !dataPoints.isEmpty {
            let sum = dataPoints.map(\.confidence).reduce(0.0, +)
            confidence = sum / Double(dataPoints.count)
        } else {
            confidence = 0.0
        }

        return AnalysisResult(
            speedProfile: speedProfile,
            lagMetrics: lagMetrics,
            impactTimestamp: audioImpactTimestamp ?? speedProfile?.impactTimestamp,
            impactSpeedMph: speedProfile?.impactSpeedMph,
            confidenceScore: confidence,
            framesAnalysed: selectedIndices.count,
            totalFrames: totalFrameCount,
            processingTimeSeconds: processingTime
        )
    }

    // MARK: - Motion Data Extraction (Fast Pass)

    /// Extract motion magnitudes at a lower sample rate for phase detection.
    private func extractMotionData(
        asset: AVURLAsset,
        sampleFPS: Int,
        totalFrameCount: Int
    ) async throws -> (timestamps: [TimeInterval], magnitudes: [Double]) {
        guard let track = try await asset.loadTracks(withMediaType: .video).first else {
            throw AnalysisError.noVideoTrack
        }

        let reader = try AVAssetReader(asset: asset)
        let outputSettings: [String: Any] = [
            kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA
        ]
        let readerOutput = AVAssetReaderTrackOutput(track: track, outputSettings: outputSettings)
        reader.add(readerOutput)
        reader.startReading()

        let nominalFPS = try await track.load(.nominalFrameRate)
        let skipInterval = max(1, Int(nominalFPS) / sampleFPS)

        var timestamps: [TimeInterval] = []
        var magnitudes: [Double] = []
        var previousBuffer: CVPixelBuffer?
        var frameIndex = 0

        while let sampleBuffer = readerOutput.copyNextSampleBuffer() {
            defer { frameIndex += 1 }
            guard frameIndex % skipInterval == 0 else { continue }

            let pts = CMSampleBufferGetPresentationTimeStamp(sampleBuffer)
            guard let pixelBuffer = CMSampleBufferGetImageBuffer(sampleBuffer) else { continue }

            let timestamp = CMTimeGetSeconds(pts)
            timestamps.append(timestamp)

            if let prev = previousBuffer {
                let motion = MotionDetector.frameDifference(current: pixelBuffer, previous: prev)
                magnitudes.append(motion)
            } else {
                magnitudes.append(0)
            }

            previousBuffer = pixelBuffer
        }

        return (timestamps, magnitudes)
    }
}

// MARK: - Errors

enum AnalysisError: LocalizedError {
    case noVideoTrack
    case insufficientFrames
    case trackingFailed
    case calibrationInvalid

    var errorDescription: String? {
        switch self {
        case .noVideoTrack: return "No video track found in recording"
        case .insufficientFrames: return "Not enough frames captured for analysis"
        case .trackingFailed: return "Could not track club head in this swing"
        case .calibrationInvalid: return "Calibration data is invalid or missing"
        }
    }
}
