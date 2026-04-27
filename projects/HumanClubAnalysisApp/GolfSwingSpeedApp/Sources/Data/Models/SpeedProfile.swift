import Foundation

struct SpeedProfile: Codable {
    var dataPoints: [SpeedDataPoint]
    var peakSpeedMph: Double
    var peakSpeedTimestamp: TimeInterval
    var impactSpeedMph: Double
    var impactTimestamp: TimeInterval
    var swingDurationSeconds: Double

    var isEmpty: Bool { dataPoints.isEmpty }
}

struct SpeedDataPoint: Codable {
    var frameTimestamp: TimeInterval
    var speedMph: Double
    var confidence: Double
    var swingPhase: SwingPhase
}
