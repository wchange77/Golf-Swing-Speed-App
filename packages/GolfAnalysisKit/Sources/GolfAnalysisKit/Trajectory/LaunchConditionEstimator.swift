import Foundation

public struct LaunchConditions: Sendable, Codable {
    public var ballSpeedMs: Double
    public var launchAngleDegrees: Double
    public var launchDirectionDegrees: Double
    public var backspinRPM: Double
    public var sidespinRPM: Double
    public var confidence: Double

    public var ballSpeedMph: Double { ballSpeedMs * GolfConstants.Speed.metersPerSecondToMph }

    public init(
        ballSpeedMs: Double,
        launchAngleDegrees: Double,
        launchDirectionDegrees: Double = 0,
        backspinRPM: Double,
        sidespinRPM: Double = 0,
        confidence: Double = 0.5
    ) {
        self.ballSpeedMs = ballSpeedMs
        self.launchAngleDegrees = launchAngleDegrees
        self.launchDirectionDegrees = launchDirectionDegrees
        self.backspinRPM = backspinRPM
        self.sidespinRPM = sidespinRPM
        self.confidence = confidence
    }
}

public struct LaunchConditionEstimator {

    // MARK: - Loft angles (degrees) — static club property
    public static let loftAngle: [ClubType: Double] = [
        .driver: 10.5,
        .threeWood: 15.0,
        .hybrid: 21.0,
        .fiveIron: 27.0,
        .sixIron: 30.0,
        .sevenIron: 34.0,
        .eightIron: 38.0,
        .nineIron: 42.0,
        .pitchingWedge: 46.0,
        .gapWedge: 50.0,
        .sandWedge: 56.0,
        .lobWedge: 60.0,
        .speedStick: 10.5,
        .other: 34.0,
    ]

    // MARK: - Typical attack angle (degrees, negative = downward)
    public static let typicalAttackAngle: [ClubType: Double] = [
        .driver: 4.0,
        .threeWood: -0.5,
        .hybrid: -1.5,
        .fiveIron: -3.0,
        .sixIron: -3.5,
        .sevenIron: -4.0,
        .eightIron: -4.5,
        .nineIron: -4.5,
        .pitchingWedge: -5.0,
        .gapWedge: -5.0,
        .sandWedge: -5.5,
        .lobWedge: -5.5,
        .speedStick: 4.0,
        .other: -3.0,
    ]

    // MARK: - Typical backspin (RPM) — TrackMan averages
    public static let typicalBackspin: [ClubType: Double] = [
        .driver: 2700,
        .threeWood: 3700,
        .hybrid: 4500,
        .fiveIron: 5200,
        .sixIron: 6000,
        .sevenIron: 7000,
        .eightIron: 8000,
        .nineIron: 9000,
        .pitchingWedge: 9500,
        .gapWedge: 10000,
        .sandWedge: 10500,
        .lobWedge: 10800,
        .speedStick: 2700,
        .other: 6000,
    ]

    // MARK: - Expected carry distance (yards) — amateur averages
    public static let expectedCarryYards: [ClubType: Double] = [
        .driver: 230,
        .threeWood: 215,
        .hybrid: 185,
        .fiveIron: 170,
        .sixIron: 160,
        .sevenIron: 150,
        .eightIron: 140,
        .nineIron: 130,
        .pitchingWedge: 120,
        .gapWedge: 100,
        .sandWedge: 85,
        .lobWedge: 70,
        .speedStick: 230,
        .other: 150,
    ]

    public static func estimate(
        clubHeadSpeedMph: Double,
        club: ClubType,
        shaftLeanDegrees: Double? = nil,
        sidespinDirection: Double? = nil
    ) -> LaunchConditions {
        let smash = BallSpeedCalculator.smashFactor(for: club)
        let ballSpeedMph = clubHeadSpeedMph * smash
        let ballSpeedMs = ballSpeedMph / GolfConstants.Speed.metersPerSecondToMph

        let loft = loftAngle[club] ?? 34.0
        let attackAngle = typicalAttackAngle[club] ?? -3.0
        let leanCorrection = (shaftLeanDegrees ?? 0) * 0.7
        let launchAngle = loft + attackAngle * 0.7 - leanCorrection

        let backspin = typicalBackspin[club] ?? 6000
        let speedRatio = clubHeadSpeedMph / typicalClubHeadSpeed(for: club)
        let adjustedBackspin = backspin * (2.0 - speedRatio).clamped(to: 0.7...1.3)

        let sidespin = sidespinDirection ?? 0

        var confidence = 0.5
        if shaftLeanDegrees != nil { confidence += 0.15 }
        if sidespinDirection != nil { confidence += 0.1 }
        let speedDeviation = abs(1.0 - speedRatio)
        confidence += Swift.max(0, 0.25 - speedDeviation * 0.5)

        return LaunchConditions(
            ballSpeedMs: ballSpeedMs,
            launchAngleDegrees: Swift.max(0, Swift.min(60, launchAngle)),
            launchDirectionDegrees: 0,
            backspinRPM: adjustedBackspin,
            sidespinRPM: sidespin,
            confidence: Swift.min(1.0, Swift.max(0.0, confidence))
        )
    }

    public static func typicalClubHeadSpeed(for club: ClubType) -> Double {
        switch club {
        case .driver: return 100
        case .threeWood: return 95
        case .hybrid: return 90
        case .fiveIron: return 85
        case .sixIron: return 83
        case .sevenIron: return 80
        case .eightIron: return 77
        case .nineIron: return 75
        case .pitchingWedge: return 72
        case .gapWedge: return 70
        case .sandWedge: return 68
        case .lobWedge: return 65
        case .speedStick: return 100
        case .other: return 80
        }
    }

    public static func isDistancePlausible(
        predictedYards: Double,
        club: ClubType,
        tolerance: Double = 0.3
    ) -> Bool {
        guard let expected = expectedCarryYards[club] else { return true }
        let lower = expected * (1.0 - tolerance)
        let upper = expected * (1.0 + tolerance)
        return predictedYards >= lower && predictedYards <= upper
    }
}

private extension Double {
    func clamped(to range: ClosedRange<Double>) -> Double {
        Swift.min(range.upperBound, Swift.max(range.lowerBound, self))
    }
}
