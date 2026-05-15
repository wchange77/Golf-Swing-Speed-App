import Foundation

enum DatasetDomain: String, Codable, CaseIterable, Identifiable {
    case humanClub = "human_club"
    case golfBallDetection = "golf_ball_detection"

    var id: String { rawValue }

    var title: String {
        switch self {
        case .humanClub:
            return "人体+球杆"
        case .golfBallDetection:
            return "高尔夫球检测"
        }
    }
}

struct CollectorCaptureConfig: Codable {
    let fps: Int
    let resolution: String
}

struct CollectorEnvironment: Codable {
    let sceneType: String
    let lighting: String
    let tripod: Bool
    let distanceMeters: Double?
}

struct CollectorLocation: Codable, Equatable {
    let latitude: Double
    let longitude: Double
    let horizontalAccuracyMeters: Double
    let altitudeMeters: Double?
    let verticalAccuracyMeters: Double?
    let capturedAt: String
    let source: String
}

struct CollectorSessionRecord: Codable, Identifiable {
    let sessionId: String
    var id: String { sessionId }
    let sessionName: String?
    let collector: String
    let device: String
    let deviceProfile: String
    let createdAt: String
    let status: String
    let iosVersion: String
    let appVersion: String
    let captureConfig: CollectorCaptureConfig
    let environment: CollectorEnvironment
    let targetDomains: [String]
    let location: CollectorLocation?
    let notes: String
}

struct CollectorReferenceMeasurement: Codable, Equatable {
    let source: String
    let device: String?
    let capturedAt: String
    let clubSpeedMph: Double?
    let ballSpeedMph: Double?
    let carryDistanceMeters: Double?
    let totalDistanceMeters: Double?
    let launchAngleDegrees: Double?
    let spinRateRpm: Double?
    let landingLocation: CollectorLocation?
    let notes: String?
}

struct CollectorSampleMetadata: Codable {
    let fps: Int
    let resolution: String
    let clubType: String
    let handedness: String
    let swingIntensity: String
    let surface: String
    var sceneType: String? = nil
    var lighting: String? = nil
    var tripod: Bool? = nil
    var distanceMeters: Double? = nil
    var shotPurpose: String? = nil
    var qualityPassed: Bool? = nil
    var qualityScore: Double? = nil
    var qualityFailedChecks: [String]? = nil
    var actualFPS: Double? = nil
    var frameCount: Int? = nil
    var durationSeconds: Double? = nil
    var captureOrientation: String? = nil
    var labelStatus: String? = nil
    var exportStatus: String? = nil
    var metadataComplete: Bool? = nil
    var calibrationStatus: String? = nil
    var calibrationMethod: String? = nil
    var calibrationSource: String? = nil
    var pixelsPerMetre: Double? = nil
    var cameraHeightMeters: Double? = nil
    var cameraAngleDegrees: Double? = nil
    var referenceMeasurements: [CollectorReferenceMeasurement]? = nil
    var sidecars: CollectorSidecarPaths? = nil
}

struct CollectorSampleRecord: Codable, Identifiable {
    let sampleId: String
    var id: String { sampleId }
    let domain: String
    let sha256: String
    let hashAlgorithm: String
    let assetPath: String
    let annotationPath: String?
    let fileSize: Int
    let sessionId: String
    let collector: String
    let device: String
    let deviceProfile: String
    let capturedAt: String
    let sourcePath: String
    let shotId: String?
    let takeIndex: Int
    let tags: [String]
    let metadata: CollectorSampleMetadata
    let status: String
}

struct CollectorDuplicateRecord: Codable {
    let duplicateAt: String
    let domain: String
    let sha256: String
    let incomingFile: String
    let incomingSourcePath: String
    let existingSampleId: String
    let sessionId: String
    let collector: String
    let metadata: CollectorSampleMetadata
}

struct CollectorSidecarPaths: Codable {
    let timeline: String?
    let quality: String?
    let camera: String?
    let labelCandidates: String?
    let audio: String?

    init(
        timeline: String?,
        quality: String?,
        camera: String?,
        labelCandidates: String?,
        audio: String? = nil
    ) {
        self.timeline = timeline
        self.quality = quality
        self.camera = camera
        self.labelCandidates = labelCandidates
        self.audio = audio
    }

    var all: [String] {
        [timeline, quality, camera, labelCandidates, audio].compactMap { $0 }
    }
}

struct RecordingQualityMetrics: Codable {
    var frameCount: Int
    var durationSeconds: Double
    var estimatedFPS: Double
    var frameRateJitterPercent: Double
    var sampledFrameCount: Int
    var humanDetectionRatio: Double?
    var averageBodyCoverageRatio: Double?
    var bodyCenterStability: Double?
    var bodyBoundingBoxStability: Double?
    var croppedBodyRatio: Double?
    var averageSharpness: Double?
    var averageBrightness: Double?
    var underexposedPixelRatio: Double?
    var overexposedPixelRatio: Double?
    var videoWidth: Int?
    var videoHeight: Int?
    var orientation: String
    var swingWindowCandidateAvailable: Bool?
    var generatedAt: String

    static func fallback(frameCount: Int, durationSeconds: Double) -> RecordingQualityMetrics {
        RecordingQualityMetrics(
            frameCount: frameCount,
            durationSeconds: durationSeconds,
            estimatedFPS: durationSeconds > 0 ? Double(frameCount) / durationSeconds : 0,
            frameRateJitterPercent: 0,
            sampledFrameCount: 0,
            humanDetectionRatio: nil,
            averageBodyCoverageRatio: nil,
            bodyCenterStability: nil,
            bodyBoundingBoxStability: nil,
            croppedBodyRatio: nil,
            averageSharpness: nil,
            averageBrightness: nil,
            underexposedPixelRatio: nil,
            overexposedPixelRatio: nil,
            videoWidth: nil,
            videoHeight: nil,
            orientation: "unknown",
            swingWindowCandidateAvailable: nil,
            generatedAt: DatasetCollectorDateFormatter.nowISO8601()
        )
    }
}

struct CollectorQualityThresholds: Codable {
    let minFrameCount: Int
    let minDurationSeconds: Double
    let maxDurationSeconds: Double
    let maxFrameRateJitterPercent: Double
    let minHumanDetectionRatio: Double
    let minSharpness: Double
    let minBrightness: Double
    let maxBrightness: Double
    let minLongSidePixels: Int
    let minShortSidePixels: Int
    let minEstimatedFPS: Double
    let minBodyCoverageRatio: Double
    let maxBodyCoverageRatio: Double
    let maxBodyCenterStability: Double
    let maxBodyBoundingBoxStability: Double
    let maxCroppedBodyRatio: Double
    let maxUnderexposedPixelRatio: Double
    let maxOverexposedPixelRatio: Double
    let minSwingWindowDurationSeconds: Double

    /// 经验阈值，需真实采集后校准；当前先作为采集端阻断低质量样本的保守基线。
    static let baseline = CollectorQualityThresholds(
        minFrameCount: 120,
        minDurationSeconds: 0.5,
        maxDurationSeconds: 60.0,
        maxFrameRateJitterPercent: 15.0,
        minHumanDetectionRatio: 0.8,
        minSharpness: 8.0,
        minBrightness: 30.0,
        maxBrightness: 230.0,
        minLongSidePixels: 1920,
        minShortSidePixels: 1080,
        minEstimatedFPS: 220.0,
        minBodyCoverageRatio: 0.06,
        maxBodyCoverageRatio: 0.72,
        maxBodyCenterStability: 0.35,
        maxBodyBoundingBoxStability: 0.45,
        maxCroppedBodyRatio: 0.2,
        maxUnderexposedPixelRatio: 0.18,
        maxOverexposedPixelRatio: 0.12,
        minSwingWindowDurationSeconds: 0.25
    )
}

struct CollectorQualityCheckRecord: Codable {
    let name: String
    let passed: Bool
    let detail: String
}

struct CollectorQualitySidecar: Codable {
    let version: String
    let generatedAt: String
    let passed: Bool
    let score: Double
    let checks: [CollectorQualityCheckRecord]
    let metrics: RecordingQualityMetrics
    let thresholds: CollectorQualityThresholds
}

struct CollectorCameraSidecar: Codable {
    let version: String
    let generatedAt: String
    let device: String
    let deviceProfile: String
    let iosVersion: String
    let appVersion: String
    let captureConfig: CollectorCaptureConfig
    let environment: CollectorEnvironment
    let captureOrientation: String
    let hasLiDAR: Bool
    let calibration: CollectorCalibrationSnapshot
    let lidarCalibration: LiDARCalibrationData?
    let intrinsics: CameraIntrinsicsSample?
}

struct CollectorCalibrationSnapshot: Codable {
    let status: String
    let method: String
    let source: String
    let distanceMeters: Double?
    let cameraHeightMeters: Double?
    let cameraAngleDegrees: Double?
    let pixelsPerMetre: Double?
    let groundPlaneY: Float?
    let clubLengthMeters: Double?
    let lieAngleDegrees: Double?
    let armLengthMeters: Double?
    let swingPlaneNormalX: Float?
    let swingPlaneNormalY: Float?
    let swingPlaneNormalZ: Float?
    let ballPositionX: Double?
    let ballPositionY: Double?
    let ballPositionZ: Double?
    let confidence: Double
    let notes: String
    let intrinsics: CameraIntrinsicsSample?

    init(
        status: String,
        method: String,
        source: String,
        distanceMeters: Double?,
        cameraHeightMeters: Double?,
        cameraAngleDegrees: Double?,
        pixelsPerMetre: Double?,
        groundPlaneY: Float?,
        clubLengthMeters: Double?,
        lieAngleDegrees: Double?,
        armLengthMeters: Double?,
        swingPlaneNormalX: Float?,
        swingPlaneNormalY: Float?,
        swingPlaneNormalZ: Float?,
        ballPositionX: Double?,
        ballPositionY: Double?,
        ballPositionZ: Double?,
        confidence: Double,
        notes: String,
        intrinsics: CameraIntrinsicsSample? = nil
    ) {
        self.status = status
        self.method = method
        self.source = source
        self.distanceMeters = distanceMeters
        self.cameraHeightMeters = cameraHeightMeters
        self.cameraAngleDegrees = cameraAngleDegrees
        self.pixelsPerMetre = pixelsPerMetre
        self.groundPlaneY = groundPlaneY
        self.clubLengthMeters = clubLengthMeters
        self.lieAngleDegrees = lieAngleDegrees
        self.armLengthMeters = armLengthMeters
        self.swingPlaneNormalX = swingPlaneNormalX
        self.swingPlaneNormalY = swingPlaneNormalY
        self.swingPlaneNormalZ = swingPlaneNormalZ
        self.ballPositionX = ballPositionX
        self.ballPositionY = ballPositionY
        self.ballPositionZ = ballPositionZ
        self.confidence = confidence
        self.notes = notes
        self.intrinsics = intrinsics
    }
}

struct CollectorAudioSidecar: Codable {
    let version: String
    let generatedAt: String
    let sampleRate: Double
    let channelCount: Int
    let durationSeconds: Double
    let peakAmplitude: Double
    let rmsDbfs: Double
    let silenceRatio: Double
    let impactBandPeakHz: Double?
    let impactBandEnergyRatio: Double?
    let frameCount: Int
    let notes: String
}

struct CollectorFrameTimestamp: Codable {
    let index: Int
    let presentationTimeSeconds: Double
    let relativeTimeSeconds: Double
}

struct CollectorDepthPoint: Codable {
    let timestampSeconds: Double
    let centerDepthMeters: Float
}

struct CollectorTimelineSidecar: Codable {
    let version: String
    let generatedAt: String
    let frameCount: Int
    let durationSeconds: Double
    let estimatedFPS: Double
    let frames: [CollectorFrameTimestamp]
    let depthSamples: [CollectorDepthPoint]
}

struct CollectorSwingWindowCandidate: Codable {
    let startTimeSeconds: Double
    let impactTimeSeconds: Double
    let endTimeSeconds: Double
    let source: String
    let confidence: Double
}

struct CollectorKeyFrameCandidate: Codable {
    let role: String
    let timeSeconds: Double
    let frameIndex: Int
    let reason: String
}

struct CollectorHumanPoseCandidate: Codable {
    let timeSeconds: Double
    let frameIndex: Int
    let source: String
    let task: String
}

struct CollectorBallCandidate: Codable {
    let timeSeconds: Double
    let frameIndex: Int
    let source: String
    let task: String
}

struct CollectorLabelCandidateSidecar: Codable {
    let version: String
    let generatedAt: String
    let status: String
    let reviewRequired: Bool
    let domains: [String]
    let swingWindow: CollectorSwingWindowCandidate
    let keyFrames: [CollectorKeyFrameCandidate]
    let humanPoseCandidates: [CollectorHumanPoseCandidate]
    let ballCandidates: [CollectorBallCandidate]
    let notes: String
}

extension CollectorSidecarPaths {
    var hasAllCaptureSidecars: Bool {
        timeline?.isEmpty == false &&
        quality?.isEmpty == false &&
        camera?.isEmpty == false &&
        labelCandidates?.isEmpty == false
    }
}

extension CollectorSampleMetadata {
    var hasRequiredCaptureMetadata: Bool {
        let requiredStrings = [
            clubType,
            handedness,
            swingIntensity,
            surface,
            sceneType ?? "",
            lighting ?? "",
            calibrationStatus ?? "",
            calibrationMethod ?? ""
        ]
        guard requiredStrings.allSatisfy({ !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && $0 != "unknown" }) else {
            return false
        }
        guard fps > 0, !resolution.isEmpty else { return false }
        guard distanceMeters.map({ $0 > 0 }) == true else { return false }
        guard qualityPassed != nil, actualFPS != nil, frameCount != nil, durationSeconds != nil else { return false }
        guard captureOrientation?.isEmpty == false, labelStatus?.isEmpty == false else { return false }
        guard sidecars?.hasAllCaptureSidecars == true else { return false }
        return true
    }
}

extension CollectorSampleRecord {
    var isExportReady: Bool {
        metadata.qualityPassed == true &&
        metadata.hasRequiredCaptureMetadata &&
        metadata.labelStatus == "needs_review" &&
        metadata.exportStatus == "ready_for_review_export"
    }
}
