import Foundation
import CoreGraphics

/// Calculates club head speed from tracked positions using calibration data.
/// Supports both 2D (manual calibration) and 3D (LiDAR calibration) modes.
/// CRITICAL: All calculations use ACTUAL frame timestamps, never assumed intervals.
struct SpeedCalculator {

    // MARK: - Full Speed Profile

    /// Build a complete speed profile from an array of tracked positions.
    static func buildSpeedProfile(
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

            // Weighted average if both frame-to-frame and previous exist
            let smoothedSpeed = if dataPoints.isEmpty {
                speed
            } else {
                speed * 0.7 + dataPoints.last!.speedMph * 0.3 // Simple exponential smoothing
            }

            let confidence = (prev.confidence + curr.confidence) / 2.0

            // Determine swing phase from timestamp relative to impact
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

        // Impact speed: closest data point to impact timestamp, or peak speed
        let impactSpeed: Double
        let impactTs: TimeInterval
        if let impact = impactTimestamp {
            let closest = dataPoints.min(by: {
                abs($0.frameTimestamp - impact) < abs($1.frameTimestamp - impact)
            })
            impactSpeed = closest?.speedMph ?? peakSpeed
            impactTs = closest?.frameTimestamp ?? peakTimestamp
        } else {
            // No impact timestamp — use peak speed as proxy
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

    // MARK: - Instantaneous Speed

    /// Calculate speed between two tracked positions using actual frame timestamps.
    /// CRITICAL: Never assume consistent frame intervals — use actual timestamps.
    static func instantaneousSpeed(
        from p1: TrackedPosition,
        to p2: TrackedPosition,
        calibration: CalibrationSnapshot
    ) -> Double? {
        let timeDelta = p2.frameTimestamp - p1.frameTimestamp
        guard timeDelta > 0 else { return nil }

        // Prefer 3D positions if available (LiDAR calibration)
        if let pos3d1 = p1.position3D, let pos3d2 = p2.position3D {
            let distance = pos3d1.distance(to: pos3d2)
            let speedMs = Double(distance) / timeDelta
            return speedMs * AppConstants.Speed.metersPerSecondToMph
        }

        // Fallback to 2D with calibration scale
        guard calibration.pixelsPerMetre > 0 else { return nil }
        let pixelDistance = p1.position2D.distance(to: p2.position2D)
        let realDistance = Double(pixelDistance) / calibration.pixelsPerMetre
        let speedMs = realDistance / timeDelta
        return speedMs * AppConstants.Speed.metersPerSecondToMph
    }

    // MARK: - Motion Blur Speed Estimate

    /// Supplementary speed estimate from motion blur streak length.
    /// blur_length (pixels) = speed (m/s) × exposure_time (s) × pixels_per_metre
    /// Therefore: speed = blur_length / (exposure_time × pixels_per_metre)
    static func speedFromMotionBlur(
        blurLengthPixels: CGFloat,
        exposureTimeSeconds: Double,
        calibration: CalibrationSnapshot
    ) -> Double? {
        guard exposureTimeSeconds > 0, calibration.pixelsPerMetre > 0 else { return nil }
        let blurLengthMetres = Double(blurLengthPixels) / calibration.pixelsPerMetre
        let speedMs = blurLengthMetres / exposureTimeSeconds
        return speedMs * AppConstants.Speed.metersPerSecondToMph
    }

    // MARK: - Fused Speed Estimate

    /// Combine frame-to-frame tracking speed with motion blur speed estimate.
    /// Frame-to-frame is primary; blur is supplementary with lower weight.
    static func fusedSpeed(
        trackingSpeedMph: Double,
        trackingConfidence: Double,
        blurSpeedMph: Double?,
        blurWeight: Double = 0.25
    ) -> Double {
        guard let blur = blurSpeedMph else { return trackingSpeedMph }

        // Weight blur estimate more when tracking confidence is low
        let adjustedBlurWeight = blurWeight * (1.0 - trackingConfidence * 0.5)
        let trackingWeight = 1.0 - adjustedBlurWeight

        return trackingSpeedMph * trackingWeight + blur * adjustedBlurWeight
    }

    // MARK: - Confidence Score

    /// Calculate confidence score for a speed measurement.
    static func confidenceScore(
        trackingConfidence: Double,
        consecutiveTrackedFrames: Int,
        trackingBlurAgreement: Double? // How close tracking and blur estimates are (0-1)
    ) -> Double {
        var score = trackingConfidence

        // Bonus for consecutive tracking (smooth trajectory = more reliable)
        let consecutiveBonus = min(Double(consecutiveTrackedFrames) * 0.05, 0.2)
        score += consecutiveBonus

        // Bonus if tracking and blur estimates agree
        if let agreement = trackingBlurAgreement {
            score += agreement * 0.1
        }

        return min(1.0, max(0.0, score))
    }

    // MARK: - Multi-Frame Regression Speed

    /// Calculate speed using linear regression over multiple frames near the target timestamp.
    /// More robust than two-frame differencing — reduces noise and handles variable frame intervals.
    ///
    /// Fits position-vs-time to a line using least squares. The slope is velocity.
    /// Uses `windowFrames` frames centered on the target.
    static func regressionSpeed(
        positions: [TrackedPosition],
        nearTimestamp: TimeInterval,
        calibration: CalibrationSnapshot,
        windowFrames: Int = 5
    ) -> Double? {
        guard positions.count >= 3, calibration.pixelsPerMetre > 0 else { return nil }

        // Find frames closest to target timestamp
        let sorted = positions.sorted { abs($0.frameTimestamp - nearTimestamp) < abs($1.frameTimestamp - nearTimestamp) }
        let window = Array(sorted.prefix(windowFrames))

        guard window.count >= 3 else { return nil }

        // Convert pixel positions to real-world distances (1D arc length from first position)
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

        // Linear regression: fit distance = a + b * time
        // b = velocity in metres/second
        guard let slopeX = linearRegressionSlope(x: times, y: distancesX),
              let slopeY = linearRegressionSlope(x: times, y: distancesY) else {
            return nil
        }

        // Speed = magnitude of velocity vector
        let speedMs = sqrt(slopeX * slopeX + slopeY * slopeY)
        return speedMs * AppConstants.Speed.metersPerSecondToMph
    }

    /// Simple linear regression — returns the slope (b in y = a + bx).
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

    // MARK: - Phase Classification

    /// Classify the swing phase for a given frame based on speed and timing.
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
