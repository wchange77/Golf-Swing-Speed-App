import Foundation

public struct EnvironmentConditions: Sendable, Codable {
    public var temperatureCelsius: Double
    public var altitudeMeters: Double
    public var windSpeedMs: Double
    public var windDirectionDegrees: Double
    public var humidity: Double
    public var isRaining: Bool

    public static let standard = EnvironmentConditions(
        temperatureCelsius: 15.0,
        altitudeMeters: 0,
        windSpeedMs: 0,
        windDirectionDegrees: 0,
        humidity: 0.5,
        isRaining: false
    )

    public init(
        temperatureCelsius: Double = 15.0,
        altitudeMeters: Double = 0,
        windSpeedMs: Double = 0,
        windDirectionDegrees: Double = 0,
        humidity: Double = 0.5,
        isRaining: Bool = false
    ) {
        self.temperatureCelsius = temperatureCelsius
        self.altitudeMeters = altitudeMeters
        self.windSpeedMs = windSpeedMs
        self.windDirectionDegrees = windDirectionDegrees
        self.humidity = humidity
        self.isRaining = isRaining
    }
}

public struct EnvironmentModel {

    public static let seaLevelAirDensity: Double = 1.225
    public static let seaLevelPressurePa: Double = 101325.0
    public static let airGasConstant: Double = 287.058
    public static let scaleHeight: Double = 8500.0

    public static func airDensity(conditions: EnvironmentConditions) -> Double {
        let tempK = conditions.temperatureCelsius + 273.15
        let altFactor = exp(-conditions.altitudeMeters / scaleHeight)
        let pressure = seaLevelPressurePa * altFactor
        let dryDensity = pressure / (airGasConstant * tempK)

        let satPressure = 610.78 * exp(17.27 * conditions.temperatureCelsius / (conditions.temperatureCelsius + 237.3))
        let vaporPressure = conditions.humidity * satPressure
        let humidityCorrection = 1.0 - 0.378 * vaporPressure / pressure

        return dryDensity * humidityCorrection
    }

    public static func windComponents(
        conditions: EnvironmentConditions,
        shotDirectionDegrees: Double = 0
    ) -> (headwind: Double, crosswind: Double) {
        let relativeAngle = (conditions.windDirectionDegrees - shotDirectionDegrees) * .pi / 180.0
        let headwind = -conditions.windSpeedMs * cos(relativeAngle)
        let crosswind = conditions.windSpeedMs * sin(relativeAngle)
        return (headwind, crosswind)
    }

    public static func densityRatio(conditions: EnvironmentConditions) -> Double {
        airDensity(conditions: conditions) / seaLevelAirDensity
    }

    public static func rollDistanceMultiplier(conditions: EnvironmentConditions) -> Double {
        conditions.isRaining ? 0.6 : 1.0
    }
}
