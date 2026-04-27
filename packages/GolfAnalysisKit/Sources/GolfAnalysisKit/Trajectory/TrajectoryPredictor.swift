import Foundation
import CoreGraphics

public struct TrajectoryPrediction: Sendable {
    public var physicsResult: TrajectoryResult
    public var bezierPoints: [TrajectoryPoint]
    public var launchConditions: LaunchConditions
    public var environment: EnvironmentConditions
    public var club: ClubType
    public var trajectoryShape: TrajectoryShape
    public var isDistancePlausible: Bool
    public var overallConfidence: Double

    public var carryDistanceYards: Double { physicsResult.carryDistanceYards }
    public var totalDistanceYards: Double { physicsResult.totalDistanceYards }
    public var apexHeightMeters: Double { physicsResult.apexHeightMeters }
    public var flightTimeSeconds: Double { physicsResult.flightTimeSeconds }
}

public struct TrajectoryPredictor {

    public struct Config: Sendable {
        public var physicsDt: Double
        public var physicsMaxTime: Double
        public var bezierSampleCount: Int
        public var distancePlausibilityTolerance: Double

        public init(
            physicsDt: Double = 0.001,
            physicsMaxTime: Double = 15.0,
            bezierSampleCount: Int = 60,
            distancePlausibilityTolerance: Double = 0.3
        ) {
            self.physicsDt = physicsDt
            self.physicsMaxTime = physicsMaxTime
            self.bezierSampleCount = bezierSampleCount
            self.distancePlausibilityTolerance = distancePlausibilityTolerance
        }
    }

    public static func predict(
        clubHeadSpeedMph: Double,
        club: ClubType,
        environment: EnvironmentConditions = .standard,
        shaftLeanDegrees: Double? = nil,
        sidespinDirection: Double? = nil,
        config: Config = Config()
    ) -> TrajectoryPrediction {
        let launch = LaunchConditionEstimator.estimate(
            clubHeadSpeedMph: clubHeadSpeedMph,
            club: club,
            shaftLeanDegrees: shaftLeanDegrees,
            sidespinDirection: sidespinDirection
        )

        return predict(
            launch: launch,
            club: club,
            environment: environment,
            config: config
        )
    }

    public static func predict(
        launch: LaunchConditions,
        club: ClubType,
        environment: EnvironmentConditions = .standard,
        config: Config = Config()
    ) -> TrajectoryPrediction {
        let physicsResult = TrajectoryPhysicsModel.simulate(
            launch: launch,
            environment: environment,
            dt: config.physicsDt,
            maxTime: config.physicsMaxTime
        )

        let shape = TrajectoryShape.from(sidespinRPM: launch.sidespinRPM)
        let origin = CGPoint(x: 0.1, y: 0.85)
        let normalizedDist = Swift.min(1.0, physicsResult.carryDistanceYards / 300.0)
        let landing = CGPoint(x: 0.1 + normalizedDist * 0.8, y: 0.85)

        let bezierConfig = BezierTrajectoryModel.Config(
            sampleCount: config.bezierSampleCount,
            height: TrajectoryHeight.from(club: club),
            shape: shape
        )
        let bezierPoints = BezierTrajectoryModel.generate(
            origin: origin,
            landing: landing,
            config: bezierConfig
        )

        let plausible = LaunchConditionEstimator.isDistancePlausible(
            predictedYards: physicsResult.carryDistanceYards,
            club: club,
            tolerance: config.distancePlausibilityTolerance
        )

        var confidence = launch.confidence
        if !plausible { confidence *= 0.5 }
        let densityRatio = EnvironmentModel.densityRatio(conditions: environment)
        if abs(1.0 - densityRatio) > 0.15 { confidence *= 0.9 }

        return TrajectoryPrediction(
            physicsResult: physicsResult,
            bezierPoints: bezierPoints,
            launchConditions: launch,
            environment: environment,
            club: club,
            trajectoryShape: shape,
            isDistancePlausible: plausible,
            overallConfidence: Swift.min(1.0, Swift.max(0.0, confidence))
        )
    }
}
