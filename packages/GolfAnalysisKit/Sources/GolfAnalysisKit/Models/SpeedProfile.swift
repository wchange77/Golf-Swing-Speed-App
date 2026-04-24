import Foundation

public struct SpeedProfile: Codable, Sendable {
    public var dataPoints: [SpeedDataPoint]
    public var peakSpeedMph: Double
    public var peakSpeedTimestamp: TimeInterval
    public var impactSpeedMph: Double
    public var impactTimestamp: TimeInterval
    public var swingDurationSeconds: Double

    public var isEmpty: Bool { dataPoints.isEmpty }

    public init(
        dataPoints: [SpeedDataPoint],
        peakSpeedMph: Double,
        peakSpeedTimestamp: TimeInterval,
        impactSpeedMph: Double,
        impactTimestamp: TimeInterval,
        swingDurationSeconds: Double
    ) {
        self.dataPoints = dataPoints
        self.peakSpeedMph = peakSpeedMph
        self.peakSpeedTimestamp = peakSpeedTimestamp
        self.impactSpeedMph = impactSpeedMph
        self.impactTimestamp = impactTimestamp
        self.swingDurationSeconds = swingDurationSeconds
    }
}

public struct SpeedDataPoint: Codable, Sendable {
    public var frameTimestamp: TimeInterval
    public var speedMph: Double
    public var confidence: Double
    public var swingPhase: SwingPhase

    public init(
        frameTimestamp: TimeInterval,
        speedMph: Double,
        confidence: Double,
        swingPhase: SwingPhase
    ) {
        self.frameTimestamp = frameTimestamp
        self.speedMph = speedMph
        self.confidence = confidence
        self.swingPhase = swingPhase
    }
}
