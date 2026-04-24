import Foundation

public struct TrajectoryResult: Sendable {
    public var points: [TrajectoryPoint]
    public var carryDistanceYards: Double
    public var totalDistanceYards: Double
    public var apexHeightMeters: Double
    public var flightTimeSeconds: Double
    public var landingAngleDegrees: Double
    public var landingSpeedMs: Double

    public init(
        points: [TrajectoryPoint],
        carryDistanceYards: Double,
        totalDistanceYards: Double,
        apexHeightMeters: Double,
        flightTimeSeconds: Double,
        landingAngleDegrees: Double,
        landingSpeedMs: Double
    ) {
        self.points = points
        self.carryDistanceYards = carryDistanceYards
        self.totalDistanceYards = totalDistanceYards
        self.apexHeightMeters = apexHeightMeters
        self.flightTimeSeconds = flightTimeSeconds
        self.landingAngleDegrees = landingAngleDegrees
        self.landingSpeedMs = landingSpeedMs
    }
}

public struct TrajectoryPhysicsModel {

    public struct BallProperties: Sendable {
        public var mass: Double = 0.04593
        public var radius: Double = 0.02135
        public var crossSectionArea: Double
        public var dragCoefficient: Double = 0.25
        public var liftCoefficient: Double = 0.18

        public init(
            mass: Double = 0.04593,
            radius: Double = 0.02135,
            dragCoefficient: Double = 0.25,
            liftCoefficient: Double = 0.18
        ) {
            self.mass = mass
            self.radius = radius
            self.crossSectionArea = .pi * radius * radius
            self.dragCoefficient = dragCoefficient
            self.liftCoefficient = liftCoefficient
        }
    }

    private static let gravity: Double = 9.81
    private static let metersToYards: Double = 1.09361

    public static func simulate(
        launch: LaunchConditions,
        environment: EnvironmentConditions = .standard,
        ball: BallProperties = BallProperties(),
        dt: Double = 0.001,
        maxTime: Double = 15.0
    ) -> TrajectoryResult {
        let rho = EnvironmentModel.airDensity(conditions: environment)
        let wind = EnvironmentModel.windComponents(conditions: environment)

        let launchRad = launch.launchAngleDegrees * .pi / 180.0
        let dirRad = launch.launchDirectionDegrees * .pi / 180.0

        var vx = launch.ballSpeedMs * cos(launchRad) * sin(dirRad)
        var vy = launch.ballSpeedMs * sin(launchRad)
        var vz = launch.ballSpeedMs * cos(launchRad) * cos(dirRad)

        var x = 0.0, y = 0.0, z = 0.0
        var t = 0.0
        var apexHeight = 0.0
        var points: [TrajectoryPoint] = []
        points.reserveCapacity(Int(maxTime / dt / 10) + 1)

        let spinAxis = spinAxisVector(
            backspinRPM: launch.backspinRPM,
            sidespinRPM: launch.sidespinRPM
        )
        let spinMagnitude = sqrt(
            launch.backspinRPM * launch.backspinRPM
            + launch.sidespinRPM * launch.sidespinRPM
        ) * 2.0 * .pi / 60.0

        let sampleInterval = Swift.max(1, Int(0.01 / dt))
        var step = 0

        while t < maxTime {
            if step % sampleInterval == 0 {
                points.append(TrajectoryPoint(x: x, y: y, z: z, time: t))
            }
            apexHeight = Swift.max(apexHeight, y)

            let k1 = derivatives(
                vx: vx, vy: vy, vz: vz,
                rho: rho, ball: ball,
                spinAxis: spinAxis, spinMag: spinMagnitude,
                windX: wind.crosswind, windZ: -wind.headwind
            )
            let k2 = derivatives(
                vx: vx + k1.dvx * dt * 0.5,
                vy: vy + k1.dvy * dt * 0.5,
                vz: vz + k1.dvz * dt * 0.5,
                rho: rho, ball: ball,
                spinAxis: spinAxis, spinMag: spinMagnitude,
                windX: wind.crosswind, windZ: -wind.headwind
            )
            let k3 = derivatives(
                vx: vx + k2.dvx * dt * 0.5,
                vy: vy + k2.dvy * dt * 0.5,
                vz: vz + k2.dvz * dt * 0.5,
                rho: rho, ball: ball,
                spinAxis: spinAxis, spinMag: spinMagnitude,
                windX: wind.crosswind, windZ: -wind.headwind
            )
            let k4 = derivatives(
                vx: vx + k3.dvx * dt,
                vy: vy + k3.dvy * dt,
                vz: vz + k3.dvz * dt,
                rho: rho, ball: ball,
                spinAxis: spinAxis, spinMag: spinMagnitude,
                windX: wind.crosswind, windZ: -wind.headwind
            )

            vx += (k1.dvx + 2*k2.dvx + 2*k3.dvx + k4.dvx) * dt / 6.0
            vy += (k1.dvy + 2*k2.dvy + 2*k3.dvy + k4.dvy) * dt / 6.0
            vz += (k1.dvz + 2*k2.dvz + 2*k3.dvz + k4.dvz) * dt / 6.0

            x += vx * dt
            y += vy * dt
            z += vz * dt
            t += dt
            step += 1

            if y < 0 && t > 0.1 { break }
        }

        points.append(TrajectoryPoint(x: x, y: Swift.max(0, y), z: z, time: t))

        let carryDistance = sqrt(x * x + z * z) * metersToYards
        let landingSpeed = sqrt(vx * vx + vy * vy + vz * vz)
        let horizontalSpeed = sqrt(vx * vx + vz * vz)
        let landingAngle = horizontalSpeed > 0
            ? atan2(-vy, horizontalSpeed) * 180.0 / .pi
            : 90.0

        let rollYards = estimateRoll(
            landingAngle: landingAngle,
            landingSpeedMs: landingSpeed,
            environment: environment
        )

        return TrajectoryResult(
            points: points,
            carryDistanceYards: carryDistance,
            totalDistanceYards: carryDistance + rollYards,
            apexHeightMeters: apexHeight,
            flightTimeSeconds: t,
            landingAngleDegrees: landingAngle,
            landingSpeedMs: landingSpeed
        )
    }

    private struct Derivatives {
        var dvx: Double
        var dvy: Double
        var dvz: Double
    }

    private static func derivatives(
        vx: Double, vy: Double, vz: Double,
        rho: Double, ball: BallProperties,
        spinAxis: (x: Double, y: Double, z: Double),
        spinMag: Double,
        windX: Double, windZ: Double
    ) -> Derivatives {
        let vrx = vx - windX
        let vry = vy
        let vrz = vz - windZ
        let vr = sqrt(vrx * vrx + vry * vry + vrz * vrz)
        guard vr > 0.01 else { return Derivatives(dvx: 0, dvy: -gravity, dvz: 0) }

        let dragFactor = -0.5 * ball.dragCoefficient * rho * ball.crossSectionArea / ball.mass
        let fdx = dragFactor * vr * vrx
        let fdy = dragFactor * vr * vry
        let fdz = dragFactor * vr * vrz

        let spinParam = spinMag > 0 ? spinMag * ball.radius / vr : 0
        let refSpinParam = 0.08
        let effectiveCl = ball.liftCoefficient * Swift.min(2.0, spinParam / refSpinParam)

        let liftFactor = 0.5 * effectiveCl * rho * ball.crossSectionArea * vr / ball.mass
        let magnusX = liftFactor * (spinAxis.y * vrz - spinAxis.z * vry)
        let magnusY = liftFactor * (spinAxis.z * vrx - spinAxis.x * vrz)
        let magnusZ = liftFactor * (spinAxis.x * vry - spinAxis.y * vrx)

        return Derivatives(
            dvx: fdx + magnusX,
            dvy: fdy + magnusY - gravity,
            dvz: fdz + magnusZ
        )
    }

    private static func spinAxisVector(
        backspinRPM: Double,
        sidespinRPM: Double
    ) -> (x: Double, y: Double, z: Double) {
        let total = sqrt(backspinRPM * backspinRPM + sidespinRPM * sidespinRPM)
        guard total > 0 else { return (-1, 0, 0) }
        return (-backspinRPM / total, sidespinRPM / total, 0)
    }

    private static func estimateRoll(
        landingAngle: Double,
        landingSpeedMs: Double,
        environment: EnvironmentConditions
    ) -> Double {
        let steepnessFactor = Swift.max(0, 1.0 - landingAngle / 60.0)
        let speedFactor = landingSpeedMs / 30.0
        let baseRollYards = 15.0 * steepnessFactor * speedFactor
        let rollMultiplier = EnvironmentModel.rollDistanceMultiplier(conditions: environment)
        return Swift.max(0, baseRollYards * rollMultiplier)
    }
}
