import Foundation
import simd

public struct LagAnalyser {

    public static func analyse(
        bodyPoses: [BodyPoseFrame],
        clubHeadPositions: [TrackedPosition],
        impactTimestamp: TimeInterval?,
        calibration: CalibrationSnapshot?
    ) -> LagMetrics? {
        guard !bodyPoses.isEmpty, !clubHeadPositions.isEmpty else { return nil }

        var lagCurve: [LagDataPoint] = []

        for pose in bodyPoses {
            guard let clubPos = closestClubPosition(to: pose.timestamp, in: clubHeadPositions) else {
                continue
            }

            guard let lagAngle = calculateLagAngle3D(pose: pose, clubHeadPosition: clubPos) else {
                continue
            }

            let phase = classifySwingPhase(
                timestamp: pose.timestamp,
                impactTimestamp: impactTimestamp,
                lagAngle: lagAngle,
                leadArmAngle: pose.leadArmAngleToVertical
            )

            lagCurve.append(LagDataPoint(
                frameTimestamp: pose.timestamp,
                lagAngleDegrees: lagAngle,
                swingPhase: phase
            ))
        }

        guard lagCurve.count >= 10 else { return nil }

        let lagAtTop = lagAtSwingPhase(.top, curve: lagCurve)
        let lagAtArmParallel = lagAtSwingPhase(.earlyDownswing, curve: lagCurve)

        guard let top = lagAtTop else { return nil }

        let armParallel = lagAtArmParallel ?? top
        let lri = top > 0 ? armParallel / top : 0

        let releasePoint = findReleasePoint(curve: lagCurve, impactTimestamp: impactTimestamp)

        let shaftLean = calculateShaftLeanAtImpact(
            bodyPoses: bodyPoses,
            clubHeadPositions: clubHeadPositions,
            impactTimestamp: impactTimestamp
        )

        let castingDetected = lri < GolfConstants.LagAnalysis.castingLRIThreshold
            || (releasePoint ?? 0) > GolfConstants.LagAnalysis.castingReleasePointThreshold

        let idealLRI = GolfConstants.LagAnalysis.goodLagLRIThreshold
        let speedLoss: Double?
        if castingDetected {
            let degreesLost = max(0, (idealLRI - lri) * top)
            speedLoss = (degreesLost / 10.0) * GolfConstants.LagAnalysis.speedLossPerTenDegreesLag
        } else {
            speedLoss = nil
        }

        return LagMetrics(
            lagAngleAtTop: top,
            lagAngleAtArmParallel: armParallel,
            lagRetentionIndex: min(1.0, max(0.0, lri)),
            releasePointDegrees: releasePoint ?? 0,
            shaftLeanAtImpact: shaftLean ?? 0,
            castingDetected: castingDetected,
            estimatedSpeedLossMph: speedLoss,
            lagCurve: lagCurve
        )
    }

    public static func calculateLagAngle3D(
        pose: BodyPoseFrame,
        clubHeadPosition: TrackedPosition
    ) -> Double? {
        guard let elbow = pose.leadElbow3D,
              let wrist = pose.leadWrist3D,
              let clubHead3D = clubHeadPosition.position3D else {
            return calculateLagAngle2D(pose: pose, clubHeadPosition: clubHeadPosition)
        }

        let forearmVector = wrist - elbow
        let shaftVector = clubHead3D - wrist
        let angle = angleBetweenVectors(forearmVector, shaftVector)
        return Double(angle.toDegrees)
    }

    public static func calculateLagAngle2D(
        pose: BodyPoseFrame,
        clubHeadPosition: TrackedPosition
    ) -> Double? {
        guard let elbow = pose.leadElbow2D,
              let wrist = pose.leadWrist2D else {
            return nil
        }

        let clubHead = clubHeadPosition.position2D

        let forearmDx = wrist.x - elbow.x
        let forearmDy = wrist.y - elbow.y
        let shaftDx = clubHead.x - wrist.x
        let shaftDy = clubHead.y - wrist.y

        let dotProduct = forearmDx * shaftDx + forearmDy * shaftDy
        let forearmLength = sqrt(forearmDx * forearmDx + forearmDy * forearmDy)
        let shaftLength = sqrt(shaftDx * shaftDx + shaftDy * shaftDy)

        guard forearmLength > 0, shaftLength > 0 else { return nil }

        let cosAngle = max(-1, min(1, dotProduct / (forearmLength * shaftLength)))
        return acos(cosAngle) * 180.0 / .pi
    }

    public static func findReleasePoint(
        curve: [LagDataPoint],
        impactTimestamp: TimeInterval?
    ) -> Double? {
        guard let impact = impactTimestamp else { return nil }

        let downswing = curve.filter {
            $0.frameTimestamp < impact && (
                $0.swingPhase == .earlyDownswing || $0.swingPhase == .lateDownswing
            )
        }

        guard downswing.count >= 5 else { return nil }

        var maxDecrease: Double = 0
        var releaseTimestamp: TimeInterval?

        for i in 1..<downswing.count {
            let dt = downswing[i].frameTimestamp - downswing[i-1].frameTimestamp
            guard dt > 0 else { continue }

            let dAngle = downswing[i].lagAngleDegrees - downswing[i-1].lagAngleDegrees
            let rate = dAngle / dt

            if rate < maxDecrease {
                maxDecrease = rate
                releaseTimestamp = downswing[i].frameTimestamp
            }
        }

        guard let releaseTs = releaseTimestamp else { return nil }

        let timeBeforeImpact = impact - releaseTs
        let degreesPerSecond = 180.0 / 0.3
        return timeBeforeImpact * degreesPerSecond
    }

    public static func calculateShaftLeanAtImpact(
        bodyPoses: [BodyPoseFrame],
        clubHeadPositions: [TrackedPosition],
        impactTimestamp: TimeInterval?
    ) -> Double? {
        guard let impact = impactTimestamp else { return nil }

        guard let pose = bodyPoses.min(by: { abs($0.timestamp - impact) < abs($1.timestamp - impact) }),
              let clubPos = closestClubPosition(to: impact, in: clubHeadPositions),
              let wrist = pose.leadWrist3D,
              let clubHead = clubPos.position3D else {
            return nil
        }

        let shaftVector = clubHead - wrist
        let verticalVector = SIMD3<Float>(0, -1, 0)

        let angle = angleBetweenVectors(shaftVector, verticalVector)
        let leanDegrees = Double(angle.toDegrees)

        return 90.0 - leanDegrees
    }

    private static func closestClubPosition(
        to timestamp: TimeInterval,
        in positions: [TrackedPosition]
    ) -> TrackedPosition? {
        positions.min(by: { abs($0.frameTimestamp - timestamp) < abs($1.frameTimestamp - timestamp) })
    }

    private static func lagAtSwingPhase(_ phase: SwingPhase, curve: [LagDataPoint]) -> Double? {
        let matching = curve.filter { $0.swingPhase == phase }
        guard !matching.isEmpty else { return nil }
        return matching.map(\.lagAngleDegrees).reduce(0, +) / Double(matching.count)
    }

    private static func lagAtTimestamp(_ timestamp: TimeInterval?, curve: [LagDataPoint]) -> Double? {
        guard let ts = timestamp else { return nil }
        return curve.min(by: { abs($0.frameTimestamp - ts) < abs($1.frameTimestamp - ts) })?.lagAngleDegrees
    }

    private static func classifySwingPhase(
        timestamp: TimeInterval,
        impactTimestamp: TimeInterval?,
        lagAngle: Double,
        leadArmAngle: Double?
    ) -> SwingPhase {
        guard let impact = impactTimestamp else { return .earlyDownswing }
        let timeToImpact = impact - timestamp
        if timeToImpact > 0.5 { return .backswing }
        if timeToImpact > 0.3 { return .top }
        if timeToImpact > 0.1 { return .earlyDownswing }
        if timeToImpact > 0 { return .lateDownswing }
        if timeToImpact > -0.02 { return .impact }
        if timeToImpact > -0.1 { return .postImpact }
        return .followThrough
    }

    private static func angleBetweenVectors(_ a: SIMD3<Float>, _ b: SIMD3<Float>) -> Float {
        let dotProduct = simd_dot(simd_normalize(a), simd_normalize(b))
        let clamped = Swift.max(-1.0, Swift.min(1.0, dotProduct))
        return acos(clamped)
    }
}
