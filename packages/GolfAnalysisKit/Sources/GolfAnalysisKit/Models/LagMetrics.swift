import Foundation

public struct LagMetrics: Codable, Sendable {
    public var lagAngleAtTop: Double
    public var lagAngleAtArmParallel: Double
    public var lagRetentionIndex: Double
    public var releasePointDegrees: Double
    public var shaftLeanAtImpact: Double
    public var castingDetected: Bool
    public var estimatedSpeedLossMph: Double?
    public var lagCurve: [LagDataPoint]

    public init(
        lagAngleAtTop: Double,
        lagAngleAtArmParallel: Double,
        lagRetentionIndex: Double,
        releasePointDegrees: Double,
        shaftLeanAtImpact: Double,
        castingDetected: Bool,
        estimatedSpeedLossMph: Double? = nil,
        lagCurve: [LagDataPoint]
    ) {
        self.lagAngleAtTop = lagAngleAtTop
        self.lagAngleAtArmParallel = lagAngleAtArmParallel
        self.lagRetentionIndex = lagRetentionIndex
        self.releasePointDegrees = releasePointDegrees
        self.shaftLeanAtImpact = shaftLeanAtImpact
        self.castingDetected = castingDetected
        self.estimatedSpeedLossMph = estimatedSpeedLossMph
        self.lagCurve = lagCurve
    }
}

public struct LagDataPoint: Codable, Sendable {
    public var frameTimestamp: TimeInterval
    public var lagAngleDegrees: Double
    public var swingPhase: SwingPhase

    public init(
        frameTimestamp: TimeInterval,
        lagAngleDegrees: Double,
        swingPhase: SwingPhase
    ) {
        self.frameTimestamp = frameTimestamp
        self.lagAngleDegrees = lagAngleDegrees
        self.swingPhase = swingPhase
    }
}
