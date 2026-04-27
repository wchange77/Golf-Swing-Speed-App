import Foundation
import simd

public struct TrackedPosition: Codable, Sendable {
    public var frameTimestamp: TimeInterval
    public var position2D: CGPoint
    public var position3D: SIMD3<Float>?
    public var confidence: Double
    public var source: TrackingSource

    public init(
        frameTimestamp: TimeInterval,
        position2D: CGPoint,
        position3D: SIMD3<Float>? = nil,
        confidence: Double,
        source: TrackingSource
    ) {
        self.frameTimestamp = frameTimestamp
        self.position2D = position2D
        self.position3D = position3D
        self.confidence = confidence
        self.source = source
    }

    public func pixelDistance(to other: TrackedPosition) -> CGFloat {
        position2D.distance(to: other.position2D)
    }

    public func timeDelta(to other: TrackedPosition) -> TimeInterval {
        other.frameTimestamp - frameTimestamp
    }
}

public enum TrackingSource: String, Codable, Sendable {
    case yoloDetection
    case opticalFlow
    case kalmanPrediction
    case visionTracking
    case manual
}
