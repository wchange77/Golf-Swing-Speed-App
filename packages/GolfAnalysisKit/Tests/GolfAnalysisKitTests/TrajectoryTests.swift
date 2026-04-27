import XCTest
@testable import GolfAnalysisKit

final class LaunchConditionEstimatorTests: XCTestCase {

    func testDriverLaunchConditions() {
        let lc = LaunchConditionEstimator.estimate(
            clubHeadSpeedMph: 100,
            club: .driver
        )
        XCTAssertGreaterThan(lc.ballSpeedMs, 50, "Driver ball speed should be significant")
        XCTAssertEqual(lc.ballSpeedMph, 149, accuracy: 5)
        XCTAssertGreaterThan(lc.launchAngleDegrees, 8)
        XCTAssertLessThan(lc.launchAngleDegrees, 18)
        XCTAssertGreaterThan(lc.backspinRPM, 2000)
        XCTAssertLessThan(lc.backspinRPM, 4000)
    }

    func testSevenIronLaunchConditions() {
        let lc = LaunchConditionEstimator.estimate(
            clubHeadSpeedMph: 80,
            club: .sevenIron
        )
        XCTAssertGreaterThan(lc.launchAngleDegrees, 14)
        XCTAssertLessThan(lc.launchAngleDegrees, 35)
        XCTAssertGreaterThan(lc.backspinRPM, 5000)
    }

    func testShaftLeanReducesLaunchAngle() {
        let noLean = LaunchConditionEstimator.estimate(
            clubHeadSpeedMph: 80,
            club: .sevenIron,
            shaftLeanDegrees: 0
        )
        let withLean = LaunchConditionEstimator.estimate(
            clubHeadSpeedMph: 80,
            club: .sevenIron,
            shaftLeanDegrees: 5
        )
        XCTAssertLessThan(withLean.launchAngleDegrees, noLean.launchAngleDegrees,
                          "Forward shaft lean should reduce launch angle")
    }

    func testDistancePlausibility() {
        XCTAssertTrue(LaunchConditionEstimator.isDistancePlausible(
            predictedYards: 230, club: .driver))
        XCTAssertFalse(LaunchConditionEstimator.isDistancePlausible(
            predictedYards: 400, club: .driver))
        XCTAssertFalse(LaunchConditionEstimator.isDistancePlausible(
            predictedYards: 50, club: .driver))
    }

    func testSmashFactorConsistency() {
        let lc = LaunchConditionEstimator.estimate(
            clubHeadSpeedMph: 100, club: .driver)
        let expectedBallSpeed = 100 * BallSpeedCalculator.smashFactor(for: .driver)
        XCTAssertEqual(lc.ballSpeedMph, expectedBallSpeed, accuracy: 0.1)
    }
}

final class EnvironmentModelTests: XCTestCase {

    func testStandardAirDensity() {
        let rho = EnvironmentModel.airDensity(conditions: .standard)
        XCTAssertEqual(rho, 1.225, accuracy: 0.02,
                       "Standard conditions should give ~1.225 kg/m³")
    }

    func testHighAltitudeReducesDensity() {
        let highAlt = EnvironmentConditions(altitudeMeters: 1500)
        let rho = EnvironmentModel.airDensity(conditions: highAlt)
        XCTAssertLessThan(rho, 1.1, "1500m altitude should reduce air density")
        XCTAssertGreaterThan(rho, 0.9)
    }

    func testHighTemperatureReducesDensity() {
        let hot = EnvironmentConditions(temperatureCelsius: 35)
        let cold = EnvironmentConditions(temperatureCelsius: 5)
        let rhoHot = EnvironmentModel.airDensity(conditions: hot)
        let rhoCold = EnvironmentModel.airDensity(conditions: cold)
        XCTAssertLessThan(rhoHot, rhoCold,
                          "Hot air should be less dense than cold air")
    }

    func testWindComponents() {
        let headwindConditions = EnvironmentConditions(
            windSpeedMs: 5, windDirectionDegrees: 180)
        let (headwind, crosswind) = EnvironmentModel.windComponents(
            conditions: headwindConditions, shotDirectionDegrees: 0)
        XCTAssertGreaterThan(headwind, 4, "180° wind = headwind")
        XCTAssertEqual(crosswind, 0, accuracy: 0.1)
    }

    func testCrosswind() {
        let crosswindConditions = EnvironmentConditions(
            windSpeedMs: 5, windDirectionDegrees: 90)
        let (headwind, crosswind) = EnvironmentModel.windComponents(
            conditions: crosswindConditions, shotDirectionDegrees: 0)
        XCTAssertEqual(headwind, 0, accuracy: 0.1)
        XCTAssertGreaterThan(abs(crosswind), 4)
    }

    func testRainReducesRoll() {
        let dry = EnvironmentConditions(isRaining: false)
        let wet = EnvironmentConditions(isRaining: true)
        XCTAssertEqual(EnvironmentModel.rollDistanceMultiplier(conditions: dry), 1.0)
        XCTAssertLessThan(EnvironmentModel.rollDistanceMultiplier(conditions: wet), 1.0)
    }
}

final class TrajectoryPhysicsModelTests: XCTestCase {

    func testDriverTrajectory() {
        let launch = LaunchConditions(
            ballSpeedMs: 67.0,
            launchAngleDegrees: 12.0,
            backspinRPM: 2700
        )
        let result = TrajectoryPhysicsModel.simulate(launch: launch)
        XCTAssertGreaterThan(result.carryDistanceYards, 150,
                             "Driver should carry > 150 yards")
        XCTAssertLessThan(result.carryDistanceYards, 300,
                          "Driver carry should be < 300 yards")
        XCTAssertGreaterThan(result.apexHeightMeters, 15)
        XCTAssertGreaterThan(result.flightTimeSeconds, 3)
        XCTAssertLessThan(result.flightTimeSeconds, 10)
        XCTAssertGreaterThan(result.landingAngleDegrees, 20)
    }

    func testWedgeHigherApex() {
        let wedge = LaunchConditions(
            ballSpeedMs: 40.0,
            launchAngleDegrees: 32.0,
            backspinRPM: 10000
        )
        let driver = LaunchConditions(
            ballSpeedMs: 67.0,
            launchAngleDegrees: 12.0,
            backspinRPM: 2700
        )
        let wedgeResult = TrajectoryPhysicsModel.simulate(launch: wedge)
        let driverResult = TrajectoryPhysicsModel.simulate(launch: driver)
        XCTAssertLessThan(wedgeResult.carryDistanceYards, driverResult.carryDistanceYards)
        XCTAssertGreaterThan(wedgeResult.landingAngleDegrees, driverResult.landingAngleDegrees,
                             "Wedge should land steeper than driver")
    }

    func testHeadwindReducesDistance() {
        let launch = LaunchConditions(
            ballSpeedMs: 67.0,
            launchAngleDegrees: 12.0,
            backspinRPM: 2700
        )
        let calm = TrajectoryPhysicsModel.simulate(launch: launch)
        let windy = TrajectoryPhysicsModel.simulate(
            launch: launch,
            environment: EnvironmentConditions(
                windSpeedMs: 10, windDirectionDegrees: 180)
        )
        XCTAssertLessThan(windy.carryDistanceYards, calm.carryDistanceYards,
                          "Headwind should reduce carry distance")
    }

    func testHighAltitudeIncreasesDistance() {
        let launch = LaunchConditions(
            ballSpeedMs: 67.0,
            launchAngleDegrees: 12.0,
            backspinRPM: 2700
        )
        let seaLevel = TrajectoryPhysicsModel.simulate(launch: launch)
        let highAlt = TrajectoryPhysicsModel.simulate(
            launch: launch,
            environment: EnvironmentConditions(altitudeMeters: 1500)
        )
        XCTAssertGreaterThan(highAlt.carryDistanceYards, seaLevel.carryDistanceYards,
                             "High altitude (thinner air) should increase distance")
    }

    func testTrajectoryPointsAreOrdered() {
        let launch = LaunchConditions(
            ballSpeedMs: 50.0,
            launchAngleDegrees: 20.0,
            backspinRPM: 6000
        )
        let result = TrajectoryPhysicsModel.simulate(launch: launch)
        XCTAssertGreaterThan(result.points.count, 10)
        for i in 1..<result.points.count {
            XCTAssertGreaterThanOrEqual(result.points[i].time, result.points[i-1].time)
        }
    }

    func testSidespinCausesCurve() {
        let straight = LaunchConditions(
            ballSpeedMs: 60.0,
            launchAngleDegrees: 15.0,
            backspinRPM: 5000,
            sidespinRPM: 0
        )
        let slice = LaunchConditions(
            ballSpeedMs: 60.0,
            launchAngleDegrees: 15.0,
            backspinRPM: 5000,
            sidespinRPM: 500
        )
        let straightResult = TrajectoryPhysicsModel.simulate(launch: straight)
        let sliceResult = TrajectoryPhysicsModel.simulate(launch: slice)
        let straightFinalX = straightResult.points.last?.x ?? 0
        let sliceFinalX = sliceResult.points.last?.x ?? 0
        XCTAssertNotEqual(straightFinalX, sliceFinalX, accuracy: 1.0,
                          "Sidespin should cause lateral deviation")
    }
}

final class BezierTrajectoryModelTests: XCTestCase {

    func testGenerateReturnsPoints() {
        let points = BezierTrajectoryModel.generate(
            origin: CGPoint(x: 0.1, y: 0.85),
            landing: CGPoint(x: 0.9, y: 0.85)
        )
        XCTAssertGreaterThan(points.count, 10)
        XCTAssertEqual(points.first?.x ?? 0, 0.1, accuracy: 0.01)
        XCTAssertEqual(points.last?.x ?? 0, 0.9, accuracy: 0.01)
    }

    func testApexIsBelowOrigin() {
        let points = BezierTrajectoryModel.generate(
            origin: CGPoint(x: 0.1, y: 0.85),
            landing: CGPoint(x: 0.9, y: 0.85),
            config: .init(height: .high)
        )
        let minY = points.map(\.y).min() ?? 1.0
        XCTAssertLessThan(minY, 0.85, "Apex should be above origin (lower y in screen coords)")
    }

    func testShapeAffectsCurve() {
        let straight = BezierTrajectoryModel.generate(
            origin: CGPoint(x: 0.1, y: 0.85),
            landing: CGPoint(x: 0.9, y: 0.85),
            config: .init(shape: .straight)
        )
        let slice = BezierTrajectoryModel.generate(
            origin: CGPoint(x: 0.1, y: 0.85),
            landing: CGPoint(x: 0.9, y: 0.85),
            config: .init(shape: .slice)
        )
        let midStraight = straight[straight.count / 2].x
        let midSlice = slice[slice.count / 2].x
        XCTAssertNotEqual(midStraight, midSlice, accuracy: 0.001)
    }

    func testTrajectoryShapeFromSidespin() {
        XCTAssertEqual(TrajectoryShape.from(sidespinRPM: 0), .straight)
        XCTAssertEqual(TrajectoryShape.from(sidespinRPM: 500), .slice)
        XCTAssertEqual(TrajectoryShape.from(sidespinRPM: -500), .hook)
        XCTAssertEqual(TrajectoryShape.from(sidespinRPM: 200), .fade)
        XCTAssertEqual(TrajectoryShape.from(sidespinRPM: -200), .draw)
    }
}

final class TrajectoryPredictorTests: XCTestCase {

    func testEndToEndPrediction() {
        let prediction = TrajectoryPredictor.predict(
            clubHeadSpeedMph: 100,
            club: .driver
        )
        XCTAssertGreaterThan(prediction.carryDistanceYards, 150)
        XCTAssertLessThan(prediction.carryDistanceYards, 300)
        XCTAssertGreaterThan(prediction.apexHeightMeters, 10)
        XCTAssertGreaterThan(prediction.bezierPoints.count, 10)
        XCTAssertTrue(prediction.isDistancePlausible)
        XCTAssertGreaterThan(prediction.overallConfidence, 0)
    }

    func testSevenIronPrediction() {
        let prediction = TrajectoryPredictor.predict(
            clubHeadSpeedMph: 80,
            club: .sevenIron
        )
        XCTAssertGreaterThan(prediction.carryDistanceYards, 100)
        XCTAssertLessThan(prediction.carryDistanceYards, 200)
        XCTAssertEqual(prediction.club, .sevenIron)
    }

    func testEnvironmentAffectsPrediction() {
        let calm = TrajectoryPredictor.predict(
            clubHeadSpeedMph: 100, club: .driver)
        let windy = TrajectoryPredictor.predict(
            clubHeadSpeedMph: 100, club: .driver,
            environment: EnvironmentConditions(
                windSpeedMs: 10, windDirectionDegrees: 180))
        XCTAssertLessThan(windy.carryDistanceYards, calm.carryDistanceYards)
    }
}
