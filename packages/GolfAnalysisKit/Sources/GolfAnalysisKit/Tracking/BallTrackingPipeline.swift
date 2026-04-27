import Foundation
import CoreVideo
import CoreGraphics

public actor BallTrackingPipeline {

    public enum TrackingState: Sendable {
        case idle
        case waitingForImpact
        case tracking
        case completed
        case lost
    }

    public struct Config: Sendable {
        public var fps: Double = GolfConstants.Camera.targetFPS
        public var maxTrackingFrames: Int = 30
        public var minDetectionsForSpeed: Int = 3
        public var impactSearchWindowFrames: Int = 5

        public init(
            fps: Double = GolfConstants.Camera.targetFPS,
            maxTrackingFrames: Int = 30,
            minDetectionsForSpeed: Int = 3,
            impactSearchWindowFrames: Int = 5
        ) {
            self.fps = fps
            self.maxTrackingFrames = maxTrackingFrames
            self.minDetectionsForSpeed = minDetectionsForSpeed
            self.impactSearchWindowFrames = impactSearchWindowFrames
        }
    }

    public struct TrackingResult: Sendable {
        public var positions: [TrackedPosition]
        public var flightMetrics: BallFlightMetrics?
        public var impactTimestamp: TimeInterval?
        public var state: TrackingState
    }

    private let detector: any BallDetector
    private let config: Config
    private var kalman = KalmanFilter6D()
    private var positions: [TrackedPosition] = []
    private var state: TrackingState = .idle
    private var impactTimestamp: TimeInterval?
    private var framesSinceImpact: Int = 0
    private var lastFrameTimestamp: TimeInterval = 0

    public init(detector: any BallDetector, config: Config = Config()) {
        self.detector = detector
        self.config = config
    }

    public func processFrame(
        pixelBuffer: CVPixelBuffer,
        timestamp: TimeInterval,
        impactDetected: Bool = false
    ) async -> TrackingResult {
        let dt = lastFrameTimestamp > 0 ? Float(timestamp - lastFrameTimestamp) : Float(1.0 / config.fps)
        lastFrameTimestamp = timestamp

        switch state {
        case .idle:
            if impactDetected {
                impactTimestamp = timestamp
                state = .waitingForImpact
            }
            return currentResult()

        case .waitingForImpact:
            let detections = await detector.detect(in: pixelBuffer)
            if let best = detections.first {
                kalman.initialize(
                    position: best.center,
                    acceleration: CGPoint(x: 0, y: CGFloat(kalman.currentState?.ay ?? 500))
                )
                let pos = TrackedPosition(
                    frameTimestamp: timestamp,
                    position2D: best.center,
                    confidence: best.confidence,
                    source: best.source == .yolo ? .yoloDetection : .opticalFlow
                )
                positions.append(pos)
                state = .tracking
                framesSinceImpact = 1
            }
            return currentResult()

        case .tracking:
            framesSinceImpact += 1

            if framesSinceImpact > config.maxTrackingFrames || kalman.isTrackLost {
                state = .completed
                return currentResult()
            }

            let prediction = kalman.predict(dt: dt)
            let detections = await detector.detect(in: pixelBuffer)

            let matched = detections.first { det in
                kalman.isMeasurementPlausible(det.center)
            }

            if let match = matched {
                kalman.update(measurement: match.center, confidence: Float(match.confidence))
                let pos = TrackedPosition(
                    frameTimestamp: timestamp,
                    position2D: match.center,
                    confidence: match.confidence,
                    source: match.source == .yolo ? .yoloDetection : .opticalFlow
                )
                positions.append(pos)
            } else if let pred = prediction {
                let pos = TrackedPosition(
                    frameTimestamp: timestamp,
                    position2D: pred.position,
                    confidence: 0.3,
                    source: .kalmanPrediction
                )
                positions.append(pos)
            }

            return currentResult()

        case .completed, .lost:
            return currentResult()
        }
    }

    public func getFlightMetrics(calibration: CalibrationSnapshot) -> BallFlightMetrics? {
        guard positions.count >= config.minDetectionsForSpeed else { return nil }
        return BallSpeedCalculator.calculateBallFlight(
            positions: positions,
            calibration: calibration,
            fps: config.fps
        )
    }

    public func reset() {
        kalman.reset()
        positions = []
        state = .idle
        impactTimestamp = nil
        framesSinceImpact = 0
        lastFrameTimestamp = 0
    }

    public var trackedPositions: [TrackedPosition] { positions }
    public var currentTrackingState: TrackingState { state }

    private func currentResult() -> TrackingResult {
        TrackingResult(
            positions: positions,
            flightMetrics: nil,
            impactTimestamp: impactTimestamp,
            state: state
        )
    }
}
