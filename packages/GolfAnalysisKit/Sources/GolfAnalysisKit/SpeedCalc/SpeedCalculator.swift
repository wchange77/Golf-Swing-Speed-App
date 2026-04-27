import Foundation
import CoreGraphics

public struct SpeedCalculator {

    public static func buildSpeedProfile(
        from positions: [TrackedPosition],
        calibration: CalibrationSnapshot,
        impactTimestamp: TimeInterval?
    ) -> SpeedProfile? {
        guard positions.count >= 2 else { return nil }

        var dataPoints: [SpeedDataPoint] = []
        var peakSpeed: Double = 0
        var peakTimestamp: TimeInterval = 0

        for i in 1..<positions.count {
            let prev = positions[i - 1]
            let curr = positions[i]

            guard let speed = instantaneousSpeed(from: prev, to: curr, calibration: calibration) else {
                continue
            }

            let smoothedSpeed = if dataPoints.isEmpty {
                speed
            } else {
                speed * 0.7 + dataPoints.last!.speedMph * 0.3
            }

            let confidence = (prev.confidence + curr.confidence) / 2.0
            let phase = classifyPhase(
                timestamp: curr.frameTimestamp,
                impactTimestamp: impactTimestamp,
                speed: smoothedSpeed,
                allPositions: positions
            )

            let point = SpeedDataPoint(
                frameTimestamp: curr.frameTimestamp,
                speedMph: smoothedSpeed,
                confidence: confidence,
                swingPhase: phase
            )
            dataPoints.append(point)

            if smoothedSpeed > peakSpeed {
                peakSpeed = smoothedSpeed
                peakTimestamp = curr.frameTimestamp
            }
        }

        guard !dataPoints.isEmpty else { return nil }

        let impactSpeed: Double
        let impactTs: TimeInterval
        if let impact = impactTimestamp {
            let closest = dataPoints.min(by: {
                abs($0.frameTimestamp - impact) < abs($1.frameTimestamp - impact)
            })
            impactSpeed = closest?.speedMph ?? peakSpeed
            impactTs = closest?.frameTimestamp ?? peakTimestamp
        } else {
            impactSpeed = peakSpeed
            impactTs = peakTimestamp
        }

        let duration = (positions.last?.frameTimestamp ?? 0) - (positions.first?.frameTimestamp ?? 0)

        return SpeedProfile(
            dataPoints: dataPoints,
            peakSpeedMph: peakSpeed,
            peakSpeedTimestamp: peakTimestamp,
            impactSpeedMph: impactSpeed,
            impactTimestamp: impactTs,
            swingDurationSeconds: duration
        )
    }

    public static func instantaneousSpeed(
        from p1: TrackedPosition,
        to p2: TrackedPosition,
        calibration: CalibrationSnapshot
    ) -> Double? {
        let timeDelta = p2.frameTimestamp - p1.frameTimestamp
        guard timeDelta > 0 else { return nil }

        if let pos3d1 = p1.position3D, let pos3d2 = p2.position3D {
            let distance = pos3d1.distance(to: pos3d2)
            let speedMs = Double(distance) / timeDelta
            return speedMs * GolfConstants.Speed.metersPerSecondToMph
        }

        guard calibration.pixelsPerMetre > 0 else { return nil }
        let pixelDistance = p1.position2D.distance(to: p2.position2D)
        let realDistance = Double(pixelDistance) / calibration.pixelsPerMetre
        let speedMs = realDistance / timeDelta
        return speedMs * GolfConstants.Speed.metersPerSecondToMph
    }

    public static func speedFromMotionBlur(
        blurLengthPixels: CGFloat,
        exposureTimeSeconds: Double,
        calibration: CalibrationSnapshot
    ) -> Double? {
        guard exposureTimeSeconds > 0, calibration.pixelsPerMetre > 0 else { return nil }
        let blurLengthMetres = Double(blurLengthPixels) / calibration.pixelsPerMetre
        let speedMs = blurLengthMetres / exposureTimeSeconds
        return speedMs * GolfConstants.Speed.metersPerSecondToMph
    }

    public static func fusedSpeed(
        trackingSpeedMph: Double,
        trackingConfidence: Double,
        blurSpeedMph: Double?,
        blurWeight: Double = 0.25
    ) -> Double {
        guard let blur = blurSpeedMph else { return trackingSpeedMph }
        let adjustedBlurWeight = blurWeight * (1.0 - trackingConfidence * 0.5)
        let trackingWeight = 1.0 - adjustedBlurWeight
        return trackingSpeedMph * trackingWeight + blur * adjustedBlurWeight
    }

    public static func confidenceScore(
        trackingConfidence: Double,
        consecutiveTrackedFrames: Int,
        trackingBlurAgreement: Double?
    ) -> Double {
        var score = trackingConfidence
        let consecutiveBonus = min(Double(consecutiveTrackedFrames) * 0.05, 0.2)
        score += consecutiveBonus
        if let agreement = trackingBlurAgreement {
            score += agreement * 0.1
        }
        return min(1.0, max(0.0, score))
    }

    public static func regressionSpeed(
        positions: [TrackedPosition],
        nearTimestamp: TimeInterval,
        calibration: CalibrationSnapshot,
        windowFrames: Int = 5
    ) -> Double? {
        guard positions.count >= 3, calibration.pixelsPerMetre > 0 else { return nil }

        let sorted = positions.sorted { abs($0.frameTimestamp - nearTimestamp) < abs($1.frameTimestamp - nearTimestamp) }
        let window = Array(sorted.prefix(windowFrames))
        guard window.count >= 3 else { return nil }

        let refPos = window.first!.position2D
        let refTime = window.first!.frameTimestamp

        var times: [Double] = []
        var distancesX: [Double] = []
        var distancesY: [Double] = []

        for pos in window {
            times.append(pos.frameTimestamp - refTime)
            distancesX.append(Double(pos.position2D.x - refPos.x) / calibration.pixelsPerMetre)
            distancesY.append(Double(pos.position2D.y - refPos.y) / calibration.pixelsPerMetre)
        }

        guard let slopeX = linearRegressionSlope(x: times, y: distancesX),
              let slopeY = linearRegressionSlope(x: times, y: distancesY) else {
            return nil
        }

        let speedMs = sqrt(slopeX * slopeX + slopeY * slopeY)
        return speedMs * GolfConstants.Speed.metersPerSecondToMph
    }

    private static func linearRegressionSlope(x: [Double], y: [Double]) -> Double? {
        let n = Double(x.count)
        guard n >= 2 else { return nil }
        let sumX = x.reduce(0, +)
        let sumY = y.reduce(0, +)
        let sumXY = zip(x, y).map(*).reduce(0, +)
        let sumXX = x.map { $0 * $0 }.reduce(0, +)
        let denominator = n * sumXX - sumX * sumX
        guard abs(denominator) > 1e-12 else { return nil }
        return (n * sumXY - sumX * sumY) / denominator
    }

    private static func classifyPhase(
        timestamp: TimeInterval,
        impactTimestamp: TimeInterval?,
        speed: Double,
        allPositions: [TrackedPosition]
    ) -> SwingPhase {
        guard let impact = impactTimestamp else { return .earlyDownswing }
        let timeToImpact = impact - timestamp
        if timeToImpact > 0.8 { return .address }
        if timeToImpact > 0.5 { return .backswing }
        if timeToImpact > 0.3 { return .top }
        if timeToImpact > 0.1 { return .earlyDownswing }
        if timeToImpact > 0 { return .lateDownswing }
        if timeToImpact > -0.02 { return .impact }
        if timeToImpact > -0.1 { return .postImpact }
        return .followThrough
    }
}
