import Foundation
import CoreImage
import Vision
import CoreML

/// Tracks the club head through a sequence of video frames using a hybrid approach:
/// 1. YOLO detection for initial localisation and re-acquisition
/// 2. Apple Vision VNTrackObjectRequest for frame-to-frame tracking
/// 3. Kalman filter for prediction through blur/occlusion and trajectory smoothing
/// 4. Calibration constraints (club length from wrist, swing plane)
actor TrackingPipeline {

    // MARK: - Configuration

    struct Config {
        var clubLengthPixels: Float?        // From calibration — constrains max distance from wrist
        var swingPlane: SIMD3<Float>?       // Normal vector of predicted swing plane
        var confidenceThreshold: Float = 0.3 // Minimum YOLO confidence to accept detection
        var redetectionInterval: Int = 10    // Frames between forced YOLO re-detections
        var isPostCapture: Bool = true       // Use .accurate tracking for post-capture (vs .fast for real-time)
    }

    private var config: Config
    private var kalman: KalmanFilter2D?
    private var trackedPositions: [TrackedPosition] = []
    private var frameCount: Int = 0
    private var lastDetectionFrame: Int = 0

    // Vision tracking
    private var visionTracker: VNTrackObjectRequest?
    private var trackingObservation: VNDetectedObjectObservation?

    // Optical flow tracking (fallback when no ML model available)
    private let opticalFlowTracker = OpticalFlowTracker()

    init(config: Config = Config()) {
        self.config = config
    }

    // MARK: - Process Frame

    /// Process a single video frame. Returns the tracked club head position or nil if lost.
    func processFrame(
        pixelBuffer: CVPixelBuffer,
        timestamp: TimeInterval,
        previousTimestamp: TimeInterval?,
        wristPosition: CGPoint?,
        clubHeadDetector: ClubHeadDetector?
    ) async -> TrackedPosition? {

        frameCount += 1
        let dt = Float(timestamp - (previousTimestamp ?? timestamp))

        // Step 1: Predict with Kalman filter
        if var k = kalman, dt > 0 {
            k.predictConstrained(
                dt: dt,
                wristPosition: wristPosition,
                maxRadiusPixels: config.clubLengthPixels
            )
            kalman = k
        }

        // Step 2: Try to detect/track the club head
        var detection: CGPoint?
        var source: TrackingSource = .kalmanPrediction
        var confidence: Double = 0.0

        // Use YOLO detection periodically or when track is uncertain
        let needsRedetection = kalman == nil
            || kalman!.isTrackLost
            || (frameCount - lastDetectionFrame) >= config.redetectionInterval

        if needsRedetection, let detector = clubHeadDetector {
            if let result = await detector.detect(in: pixelBuffer) {
                detection = result.center
                confidence = result.confidence
                source = .yoloDetection
                lastDetectionFrame = frameCount

                // Initialise or reset Vision tracking with this detection
                initVisionTracking(boundingBox: result.boundingBox)
            }
        }

        // If no YOLO detection, try Vision framework tracking
        if detection == nil, let _ = trackingObservation {
            if let tracked = performVisionTracking(on: pixelBuffer) {
                detection = tracked.center
                confidence = Double(tracked.confidence)
                source = .visionTracking
            }
        }

        // If no Vision tracking, try optical flow (works without ML model)
        if detection == nil {
            if let flowPosition = await opticalFlowTracker.track(
                in: pixelBuffer,
                roiCenter: kalman?.position
            ) {
                detection = flowPosition
                confidence = 0.6 // Lower confidence for optical flow
                source = .opticalFlow
            }
        }

        // Step 3: Update Kalman filter with detection (if available)
        if let detected = detection {
            if kalman != nil {
                kalman!.update(measurement: detected)
            } else {
                kalman = KalmanFilter2D(initialPosition: detected)
            }
        }

        // Step 4: Use Kalman state as the tracked position
        guard let k = kalman, !k.isTrackLost else {
            return nil
        }

        let position = TrackedPosition(
            frameTimestamp: timestamp,
            position2D: k.position,
            position3D: nil, // Populated later by 3D pose pipeline
            confidence: detection != nil ? confidence : max(0.1, confidence - Double(k.framesWithoutDetection) * 0.1),
            source: detection != nil ? source : .kalmanPrediction
        )

        trackedPositions.append(position)
        return position
    }

    // MARK: - Vision Tracking

    private func initVisionTracking(boundingBox: CGRect) {
        let observation = VNDetectedObjectObservation(boundingBox: boundingBox)
        trackingObservation = observation
        visionTracker = VNTrackObjectRequest(detectedObjectObservation: observation)
        // Use .accurate for post-capture analysis (no real-time constraint)
        // Use .fast for live preview/real-time scenarios
        visionTracker?.trackingLevel = config.isPostCapture ? .accurate : .fast
    }

    private func performVisionTracking(on pixelBuffer: CVPixelBuffer) -> (center: CGPoint, confidence: Float)? {
        guard let tracker = visionTracker else { return nil }

        let handler = VNImageRequestHandler(cvPixelBuffer: pixelBuffer, options: [:])
        try? handler.perform([tracker])

        guard let result = tracker.results?.first as? VNDetectedObjectObservation else {
            return nil
        }

        // Update for next frame
        trackingObservation = result
        visionTracker = VNTrackObjectRequest(detectedObjectObservation: result)
        visionTracker?.trackingLevel = .fast

        let bbox = result.boundingBox
        let center = CGPoint(
            x: bbox.midX * CGFloat(CVPixelBufferGetWidth(pixelBuffer)),
            y: (1 - bbox.midY) * CGFloat(CVPixelBufferGetHeight(pixelBuffer))
        )

        return (center, result.confidence)
    }

    // MARK: - Results

    func getTrackedPositions() -> [TrackedPosition] {
        trackedPositions
    }

    func reset() async {
        kalman = nil
        trackedPositions = []
        frameCount = 0
        lastDetectionFrame = 0
        visionTracker = nil
        trackingObservation = nil
        await opticalFlowTracker.reset()
    }

    /// Set the initial club head position for optical flow tracking
    /// (e.g., from calibration address position).
    func setInitialClubHeadPosition(_ position: CGPoint) async {
        await opticalFlowTracker.setInitialPosition(position)
    }
}

// MARK: - Club Head Detector (Core ML YOLO wrapper)

/// Wraps a Core ML YOLO model for club head detection in individual frames.
actor ClubHeadDetector {

    struct Detection {
        var center: CGPoint       // In pixel coordinates
        var boundingBox: CGRect   // In normalised Vision coordinates (0-1)
        var confidence: Double
    }

    private var model: VNCoreMLModel?

    init(modelName: String = "ClubHeadDetector") {
        // Load Core ML model
        // In production, this loads the .mlmodel from the bundle
        // For now, this is a placeholder — model will be trained and added later
        if let mlModel = try? MLModel(contentsOf: Bundle.main.url(
            forResource: modelName, withExtension: "mlmodelc"
        ) ?? URL(fileURLWithPath: "")) {
            self.model = try? VNCoreMLModel(for: mlModel)
        }
    }

    func detect(in pixelBuffer: CVPixelBuffer) async -> Detection? {
        guard let model else { return nil }

        let request = VNCoreMLRequest(model: model)
        request.imageCropAndScaleOption = .scaleFill

        let handler = VNImageRequestHandler(cvPixelBuffer: pixelBuffer, options: [:])
        try? handler.perform([request])

        // Find the highest-confidence club head detection
        guard let results = request.results as? [VNRecognizedObjectObservation] else {
            return nil
        }

        let best = results
            .filter { $0.labels.first?.identifier == "club_head" }
            .max(by: { $0.confidence < $1.confidence })

        guard let detection = best else { return nil }

        let bbox = detection.boundingBox
        let imageWidth = CGFloat(CVPixelBufferGetWidth(pixelBuffer))
        let imageHeight = CGFloat(CVPixelBufferGetHeight(pixelBuffer))

        let center = CGPoint(
            x: bbox.midX * imageWidth,
            y: (1 - bbox.midY) * imageHeight // Vision uses bottom-left origin
        )

        return Detection(
            center: center,
            boundingBox: bbox,
            confidence: Double(detection.confidence)
        )
    }
}

// MARK: - Tracked Position (moved from placeholder)

struct TrackedPosition: Codable {
    var frameTimestamp: TimeInterval
    var position2D: CGPoint
    var position3D: SIMD3<Float>?
    var confidence: Double
    var source: TrackingSource

    /// Pixel displacement to another position
    func pixelDistance(to other: TrackedPosition) -> CGFloat {
        position2D.distance(to: other.position2D)
    }

    /// Time delta to another position
    func timeDelta(to other: TrackedPosition) -> TimeInterval {
        other.frameTimestamp - frameTimestamp
    }
}

enum TrackingSource: String, Codable {
    case yoloDetection
    case opticalFlow
    case kalmanPrediction
    case visionTracking
    case manual
}
