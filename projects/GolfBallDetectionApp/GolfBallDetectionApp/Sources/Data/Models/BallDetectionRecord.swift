import Foundation

struct BallDetectionRecord: Identifiable, Codable {
    let id: UUID
    let timestamp: Date
    let confidence: Double
    let centerX: Double
    let centerY: Double
    let radius: Double
    let frameIndex: Int
    let frameTimestamp: Double
    let source: String

    init(
        id: UUID = UUID(),
        timestamp: Date = Date(),
        confidence: Double,
        centerX: Double,
        centerY: Double,
        radius: Double,
        frameIndex: Int = 0,
        frameTimestamp: Double = 0,
        source: String = "frameDifference"
    ) {
        self.id = id
        self.timestamp = timestamp
        self.confidence = confidence
        self.centerX = centerX
        self.centerY = centerY
        self.radius = radius
        self.frameIndex = frameIndex
        self.frameTimestamp = frameTimestamp
        self.source = source
    }
}
