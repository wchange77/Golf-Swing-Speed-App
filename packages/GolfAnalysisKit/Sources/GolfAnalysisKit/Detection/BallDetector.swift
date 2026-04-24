import Foundation
import CoreVideo
import CoreGraphics

public struct BallDetection: Sendable {
    public var center: CGPoint
    public var boundingBox: CGRect
    public var confidence: Double
    public var radius: CGFloat
    public var source: BallDetectionSource

    public init(
        center: CGPoint,
        boundingBox: CGRect,
        confidence: Double,
        radius: CGFloat,
        source: BallDetectionSource
    ) {
        self.center = center
        self.boundingBox = boundingBox
        self.confidence = confidence
        self.radius = radius
        self.source = source
    }
}

public enum BallDetectionSource: String, Codable, Sendable {
    case yolo
    case frameDifference
    case fused
}

public protocol BallDetector: Sendable {
    func detect(in pixelBuffer: CVPixelBuffer) async -> [BallDetection]
}
