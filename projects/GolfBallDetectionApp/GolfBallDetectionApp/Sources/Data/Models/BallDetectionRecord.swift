import Foundation

struct BallDetectionRecord: Identifiable, Codable {
    let id: UUID
    let timestamp: Date
    let confidence: Double
    let centerX: Double
    let centerY: Double
    let radius: Double

    init(id: UUID = UUID(), timestamp: Date = Date(), confidence: Double, centerX: Double, centerY: Double, radius: Double) {
        self.id = id
        self.timestamp = timestamp
        self.confidence = confidence
        self.centerX = centerX
        self.centerY = centerY
        self.radius = radius
    }
}
