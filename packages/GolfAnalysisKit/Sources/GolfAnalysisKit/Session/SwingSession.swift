import Foundation

public struct SwingSession: Codable, Identifiable, Sendable {
    public var id: UUID
    public var date: Date
    public var club: ClubType
    public var clubHeadSpeedMph: Double
    public var ballSpeedMph: Double
    public var launchAngleDegrees: Double
    public var carryDistanceYards: Double
    public var totalDistanceYards: Double
    public var apexHeightMeters: Double
    public var flightTimeSeconds: Double
    public var landingAngleDegrees: Double
    public var backspinRPM: Double
    public var sidespinRPM: Double
    public var trajectoryShape: TrajectoryShape
    public var confidence: Double
    public var notes: String

    public init(
        id: UUID = UUID(),
        date: Date = Date(),
        club: ClubType,
        clubHeadSpeedMph: Double,
        ballSpeedMph: Double,
        launchAngleDegrees: Double,
        carryDistanceYards: Double,
        totalDistanceYards: Double,
        apexHeightMeters: Double = 0,
        flightTimeSeconds: Double = 0,
        landingAngleDegrees: Double = 0,
        backspinRPM: Double = 0,
        sidespinRPM: Double = 0,
        trajectoryShape: TrajectoryShape = .straight,
        confidence: Double = 0.5,
        notes: String = ""
    ) {
        self.id = id
        self.date = date
        self.club = club
        self.clubHeadSpeedMph = clubHeadSpeedMph
        self.ballSpeedMph = ballSpeedMph
        self.launchAngleDegrees = launchAngleDegrees
        self.carryDistanceYards = carryDistanceYards
        self.totalDistanceYards = totalDistanceYards
        self.apexHeightMeters = apexHeightMeters
        self.flightTimeSeconds = flightTimeSeconds
        self.landingAngleDegrees = landingAngleDegrees
        self.backspinRPM = backspinRPM
        self.sidespinRPM = sidespinRPM
        self.trajectoryShape = trajectoryShape
        self.confidence = confidence
        self.notes = notes
    }

    public static func from(prediction: TrajectoryPrediction, club: ClubType) -> SwingSession {
        let clubHeadSpeed = prediction.launchConditions.ballSpeedMph
            / BallSpeedCalculator.smashFactor(for: club)
        return SwingSession(
            club: club,
            clubHeadSpeedMph: clubHeadSpeed,
            ballSpeedMph: prediction.launchConditions.ballSpeedMph,
            launchAngleDegrees: prediction.launchConditions.launchAngleDegrees,
            carryDistanceYards: prediction.carryDistanceYards,
            totalDistanceYards: prediction.totalDistanceYards,
            apexHeightMeters: prediction.apexHeightMeters,
            flightTimeSeconds: prediction.flightTimeSeconds,
            landingAngleDegrees: prediction.physicsResult.landingAngleDegrees,
            backspinRPM: prediction.launchConditions.backspinRPM,
            sidespinRPM: prediction.launchConditions.sidespinRPM,
            trajectoryShape: prediction.trajectoryShape,
            confidence: prediction.overallConfidence
        )
    }
}
