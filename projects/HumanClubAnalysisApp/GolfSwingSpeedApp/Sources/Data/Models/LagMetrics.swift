import Foundation

struct LagMetrics: Codable {
    var lagAngleAtTop: Double
    var lagAngleAtArmParallel: Double
    var lagRetentionIndex: Double
    var releasePointDegrees: Double
    var shaftLeanAtImpact: Double
    var castingDetected: Bool
    var estimatedSpeedLossMph: Double?
    var lagCurve: [LagDataPoint]
}

struct LagDataPoint: Codable {
    var frameTimestamp: TimeInterval
    var lagAngleDegrees: Double
    var swingPhase: SwingPhase
}
