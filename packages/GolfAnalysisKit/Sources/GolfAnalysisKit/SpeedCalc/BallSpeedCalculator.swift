import Foundation
import CoreGraphics

public struct BallFlightMetrics: Sendable {
    public var ballSpeedMph: Double
    public var launchAngleDegrees: Double
    public var launchDirectionDegrees: Double
    public var confidence: Double
    public var trackedFrameCount: Int

    public init(
        ballSpeedMph: Double,
        launchAngleDegrees: Double,
        launchDirectionDegrees: Double,
        confidence: Double,
        trackedFrameCount: Int
    ) {
        self.ballSpeedMph = ballSpeedMph
        self.launchAngleDegrees = launchAngleDegrees
        self.launchDirectionDegrees = launchDirectionDegrees
        self.confidence = confidence
        self.trackedFrameCount = trackedFrameCount
    }
}

public struct BallSpeedCalculator {

    public static func calculateBallFlight(
        positions: [TrackedPosition],
        calibration: CalibrationSnapshot,
        fps: Double = GolfConstants.Camera.targetFPS
    ) -> BallFlightMetrics? {
        guard positions.count >= 2, calibration.pixelsPerMetre > 0 else { return nil }

        let sorted = positions.sorted { $0.frameTimestamp < $1.frameTimestamp }

        let regressionSpeed = regressionBallSpeed(
            positions: sorted,
            calibration: calibration
        )

        let instantSpeeds = consecutiveSpeeds(positions: sorted, calibration: calibration)
        let avgInstant = instantSpeeds.isEmpty ? nil : instantSpeeds.reduce(0, +) / Double(instantSpeeds.count)

        let ballSpeed: Double
        if let reg = regressionSpeed, let avg = avgInstant {
            ballSpeed = reg * 0.6 + avg * 0.4
        } else {
            ballSpeed = regressionSpeed ?? avgInstant ?? 0
        }

        guard ballSpeed > 0 else { return nil }

        let launchAngle = calculateLaunchAngle(positions: sorted, calibration: calibration)
        let launchDirection = calculateLaunchDirection(positions: sorted)

        let confidence = calculateConfidence(
            positions: sorted,
            instantSpeeds: instantSpeeds,
            regressionSpeed: regressionSpeed,
            avgInstantSpeed: avgInstant
        )

        return BallFlightMetrics(
            ballSpeedMph: ballSpeed,
            launchAngleDegrees: launchAngle,
            launchDirectionDegrees: launchDirection,
            confidence: confidence,
            trackedFrameCount: sorted.count
        )
    }

    public static func regressionBallSpeed(
        positions: [TrackedPosition],
        calibration: CalibrationSnapshot
    ) -> Double? {
        guard positions.count >= 3, calibration.pixelsPerMetre > 0 else { return nil }

        let refTime = positions[0].frameTimestamp
        let refPos = positions[0].position2D

        var times: [Double] = []
        var distX: [Double] = []
        var distY: [Double] = []

        for pos in positions {
            times.append(pos.frameTimestamp - refTime)
            distX.append(Double(pos.position2D.x - refPos.x) / calibration.pixelsPerMetre)
            distY.append(Double(pos.position2D.y - refPos.y) / calibration.pixelsPerMetre)
        }

        guard let slopeX = linearRegressionSlope(x: times, y: distX),
              let slopeY = linearRegressionSlope(x: times, y: distY) else {
            return nil
        }

        let speedMs = sqrt(slopeX * slopeX + slopeY * slopeY)
        return speedMs * GolfConstants.Speed.metersPerSecondToMph
    }

    public static func consecutiveSpeeds(
        positions: [TrackedPosition],
        calibration: CalibrationSnapshot
    ) -> [Double] {
        guard calibration.pixelsPerMetre > 0 else { return [] }
        var speeds: [Double] = []
        for i in 1..<positions.count {
            if let speed = SpeedCalculator.instantaneousSpeed(
                from: positions[i - 1],
                to: positions[i],
                calibration: calibration
            ) {
                speeds.append(speed)
            }
        }
        return speeds
    }

    public static func calculateLaunchAngle(
        positions: [TrackedPosition],
        calibration: CalibrationSnapshot
    ) -> Double {
        guard positions.count >= 2 else { return 0 }

        let first = positions[0]
        let last = positions[min(positions.count - 1, 4)]

        let dx = Double(last.position2D.x - first.position2D.x)
        let dy = Double(first.position2D.y - last.position2D.y)

        let angleRad = atan2(dy, abs(dx))
        return angleRad * 180.0 / .pi
    }

    public static func calculateLaunchDirection(
        positions: [TrackedPosition]
    ) -> Double {
        guard positions.count >= 2 else { return 0 }

        let first = positions[0]
        let last = positions[min(positions.count - 1, 4)]

        let dx = Double(last.position2D.x - first.position2D.x)
        let dy = Double(last.position2D.y - first.position2D.y)

        return atan2(dx, -dy) * 180.0 / .pi
    }

    public static func smashFactor(for club: ClubType) -> Double {
        switch club {
        case .driver: return 1.49
        case .threeWood: return 1.46
        case .hybrid: return 1.39
        case .fiveIron: return 1.35
        case .sixIron: return 1.33
        case .sevenIron: return 1.29
        case .eightIron: return 1.26
        case .nineIron: return 1.23
        case .pitchingWedge: return 1.19
        case .gapWedge: return 1.16
        case .sandWedge: return 1.13
        case .lobWedge: return 1.10
        case .speedStick: return 1.49
        case .other: return 1.30
        }
    }

    public static func estimatedBallSpeed(
        clubHeadSpeedMph: Double,
        club: ClubType
    ) -> Double {
        clubHeadSpeedMph * smashFactor(for: club)
    }

    private static func calculateConfidence(
        positions: [TrackedPosition],
        instantSpeeds: [Double],
        regressionSpeed: Double?,
        avgInstantSpeed: Double?
    ) -> Double {
        var score = 0.0

        let frameBonus = min(Double(positions.count) * 0.1, 0.3)
        score += frameBonus

        let avgConfidence = positions.map(\.confidence).reduce(0, +) / Double(positions.count)
        score += avgConfidence * 0.3

        if let reg = regressionSpeed, let avg = avgInstantSpeed, avg > 0 {
            let agreement = 1.0 - min(1.0, abs(reg - avg) / avg)
            score += agreement * 0.2
        }

        if instantSpeeds.count >= 2 {
            let mean = instantSpeeds.reduce(0, +) / Double(instantSpeeds.count)
            guard mean > 0 else { return min(1.0, max(0.0, score)) }
            let variance = instantSpeeds.map { ($0 - mean) * ($0 - mean) }.reduce(0, +) / Double(instantSpeeds.count)
            let cv = sqrt(variance) / mean
            let consistency = max(0, 1.0 - cv * 2)
            score += consistency * 0.2
        }

        return min(1.0, max(0.0, score))
    }

    private static func linearRegressionSlope(x: [Double], y: [Double]) -> Double? {
        let n = Double(x.count)
        guard n >= 2 else { return nil }
        let sumX = x.reduce(0, +)
        let sumY = y.reduce(0, +)
        let sumXY = zip(x, y).map(*).reduce(0, +)
        let sumXX = x.map { $0 * $0 }.reduce(0, +)
        let denom = n * sumXX - sumX * sumX
        guard abs(denom) > 1e-12 else { return nil }
        return (n * sumXY - sumX * sumY) / denom
    }
}
