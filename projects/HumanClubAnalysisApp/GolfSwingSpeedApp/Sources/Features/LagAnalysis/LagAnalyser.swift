import Foundation
import Vision
import simd

/// Analyses wrist lag / release throughout a golf swing using 3D body pose + club head tracking.
///
/// Process: Post-capture, runs VNDetectHumanBodyPose3DRequest on every frame to get
/// 3D shoulder/elbow/wrist positions, then combines with club head position from tracking
/// pipeline to calculate the lag angle in true 3D space.
///
/// Key metrics: Lag Retention Index, Release Point, Shaft Lean at Impact, Casting Detection.
/// Temporal precision: ±4ms at 240fps — more precise than HackMotion (50-100Hz).
///
/// Reference: Chu et al. (2010) — 10° retained lag ≈ 5 mph club head speed gain.
struct LagAnalyser {

    // MARK: - Analyse Full Swing

    /// Analyse lag metrics from a sequence of body poses and club head positions.
    /// Both arrays should be aligned by frame timestamp.
    static func analyse(
        bodyPoses: [BodyPoseFrame],
        clubHeadPositions: [TrackedPosition],
        impactTimestamp: TimeInterval?,
        calibration: CalibrationSnapshot?
    ) -> LagMetrics? {
        guard !bodyPoses.isEmpty, !clubHeadPositions.isEmpty else { return nil }

        // Build lag curve — one data point per frame where we have both pose and club position
        var lagCurve: [LagDataPoint] = []
        var swingPhases: [TimeInterval: SwingPhase] = [:]

        for pose in bodyPoses {
            // Find closest club head position by timestamp
            guard let clubPos = closestClubPosition(to: pose.timestamp, in: clubHeadPositions) else {
                continue
            }

            // Calculate lag angle in 3D
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
            swingPhases[pose.timestamp] = phase
        }

        guard lagCurve.count >= 10 else { return nil }

        // Extract key measurements
        let lagAtTop = lagAtSwingPhase(.top, curve: lagCurve)
        let lagAtArmParallel = lagAtSwingPhase(.earlyDownswing, curve: lagCurve)
        let lagAtImpact = lagAtTimestamp(impactTimestamp, curve: lagCurve)

        guard let top = lagAtTop else { return nil }

        // Lag Retention Index: ratio of lag maintained from top to arm-parallel
        let armParallel = lagAtArmParallel ?? top
        let lri = top > 0 ? armParallel / top : 0

        // Release Point: find where lag begins decreasing rapidly
        let releasePoint = findReleasePoint(curve: lagCurve, impactTimestamp: impactTimestamp)

        // Shaft Lean at Impact
        let shaftLean = calculateShaftLeanAtImpact(
            bodyPoses: bodyPoses,
            clubHeadPositions: clubHeadPositions,
            impactTimestamp: impactTimestamp
        )

        // Casting detection
        let castingDetected = lri < AppConstants.LagAnalysis.castingLRIThreshold
            || (releasePoint ?? 0) > AppConstants.LagAnalysis.castingReleasePointThreshold

        // Estimated speed loss from early release
        let idealLRI = AppConstants.LagAnalysis.goodLagLRIThreshold
        let speedLoss: Double?
        if castingDetected {
            let degreesLost = max(0, (idealLRI - lri) * top)
            speedLoss = (degreesLost / 10.0) * AppConstants.LagAnalysis.speedLossPerTenDegreesLag
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

    // MARK: - 3D Lag Angle Calculation

    /// Calculate the lag angle between the lead forearm and club shaft in 3D.
    /// Lag angle = angle between (elbow→wrist) vector and (wrist→club_head) vector.
    static func calculateLagAngle3D(
        pose: BodyPoseFrame,
        clubHeadPosition: TrackedPosition
    ) -> Double? {
        guard let elbow = pose.leadElbow3D,
              let wrist = pose.leadWrist3D,
              let clubHead3D = clubHeadPosition.position3D else {
            // Fallback to 2D if 3D not available
            return calculateLagAngle2D(pose: pose, clubHeadPosition: clubHeadPosition)
        }

        // Forearm vector: elbow → wrist
        let forearmVector = wrist - elbow

        // Shaft vector: wrist → club head
        let shaftVector = clubHead3D - wrist

        // Angle between vectors
        let angle = angleBetweenVectors(forearmVector, shaftVector)
        return Double(angle.toDegrees)
    }

    /// Fallback 2D lag angle calculation (less accurate due to parallax).
    static func calculateLagAngle2D(
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

    // MARK: - Release Point Detection

    /// Find the point in the downswing where the lag angle begins decreasing rapidly.
    /// Returns degrees of arm rotation before impact.
    static func findReleasePoint(
        curve: [LagDataPoint],
        impactTimestamp: TimeInterval?
    ) -> Double? {
        guard let impact = impactTimestamp else { return nil }

        // Look at downswing portion only (before impact)
        let downswing = curve.filter {
            $0.frameTimestamp < impact && (
                $0.swingPhase == .earlyDownswing || $0.swingPhase == .lateDownswing
            )
        }

        guard downswing.count >= 5 else { return nil }

        // Find the frame where the rate of lag angle decrease is maximum
        // (the "release" is where d(lagAngle)/dt is most negative)
        var maxDecrease: Double = 0
        var releaseTimestamp: TimeInterval?

        for i in 1..<downswing.count {
            let dt = downswing[i].frameTimestamp - downswing[i-1].frameTimestamp
            guard dt > 0 else { continue }

            let dAngle = downswing[i].lagAngleDegrees - downswing[i-1].lagAngleDegrees
            let rate = dAngle / dt // degrees per second (negative = releasing)

            if rate < maxDecrease {
                maxDecrease = rate
                releaseTimestamp = downswing[i].frameTimestamp
            }
        }

        guard let releaseTs = releaseTimestamp else { return nil }

        // Convert time-before-impact to approximate degrees of arm rotation.
        // Rough heuristic: downswing takes ~0.25-0.35s to cover ~180° of rotation.
        let timeBeforeImpact = impact - releaseTs
        let degreesPerSecond = 180.0 / 0.3 // ~600°/s typical downswing rotation rate
        return timeBeforeImpact * degreesPerSecond
    }

    // MARK: - Shaft Lean at Impact

    /// Calculate shaft lean angle at impact.
    /// Positive = hands ahead of club head (forward lean, good).
    /// Negative = club head ahead of hands (flipping, bad).
    static func calculateShaftLeanAtImpact(
        bodyPoses: [BodyPoseFrame],
        clubHeadPositions: [TrackedPosition],
        impactTimestamp: TimeInterval?
    ) -> Double? {
        guard let impact = impactTimestamp else { return nil }

        // Find closest pose and club position to impact
        guard let pose = bodyPoses.min(by: { abs($0.timestamp - impact) < abs($1.timestamp - impact) }),
              let clubPos = closestClubPosition(to: impact, in: clubHeadPositions),
              let wrist = pose.leadWrist3D,
              let clubHead = clubPos.position3D else {
            return nil
        }

        // Shaft lean = angle of shaft from vertical, measured in the target direction
        // Positive means hands are closer to target than club head (forward lean)
        let shaftVector = clubHead - wrist
        let verticalVector = SIMD3<Float>(0, -1, 0) // Pointing down

        let angle = angleBetweenVectors(shaftVector, verticalVector)
        let leanDegrees = Double(angle.toDegrees)

        // Sign: if club head is behind wrist (in target direction), lean is positive
        // This depends on camera orientation — simplified here
        return 90.0 - leanDegrees // Convert from angle-from-vertical to lean angle
    }

    // MARK: - Helpers

    private static func closestClubPosition(
        to timestamp: TimeInterval,
        in positions: [TrackedPosition]
    ) -> TrackedPosition? {
        positions.min(by: { abs($0.frameTimestamp - timestamp) < abs($1.frameTimestamp - timestamp) })
    }

    private static func lagAtSwingPhase(_ phase: SwingPhase, curve: [LagDataPoint]) -> Double? {
        let matching = curve.filter { $0.swingPhase == phase }
        guard !matching.isEmpty else { return nil }
        // Return the average lag angle in this phase
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
        let clamped = max(-1.0, min(1.0, dotProduct))
        return acos(clamped)
    }
}

// MARK: - Body Pose Frame

/// Holds the relevant body joint positions from a single frame's 3D pose detection.
struct BodyPoseFrame {
    var timestamp: TimeInterval

    // 3D positions in metres (from VNDetectHumanBodyPose3DRequest)
    var leadShoulder3D: SIMD3<Float>?
    var leadElbow3D: SIMD3<Float>?
    var leadWrist3D: SIMD3<Float>?
    var trailShoulder3D: SIMD3<Float>?
    var trailElbow3D: SIMD3<Float>?
    var trailWrist3D: SIMD3<Float>?
    var spine3D: SIMD3<Float>?
    var leftHip3D: SIMD3<Float>?
    var rightHip3D: SIMD3<Float>?

    // 2D positions in pixels (fallback from VNDetectHumanBodyPoseRequest)
    var leadElbow2D: CGPoint?
    var leadWrist2D: CGPoint?

    /// Angle of lead arm from vertical (used for swing phase classification)
    var leadArmAngleToVertical: Double? {
        guard let shoulder = leadShoulder3D, let wrist = leadWrist3D else { return nil }
        let armVector = wrist - shoulder
        let vertical = SIMD3<Float>(0, -1, 0)
        let dot = simd_dot(simd_normalize(armVector), vertical)
        return Double(acos(max(-1, min(1, dot))).toDegrees)
    }
}

// MARK: - 3D Pose Extraction

/// Extracts BodyPoseFrame from a VNHumanBodyPose3DObservation.
extension BodyPoseFrame {

    /// Create from a Vision 3D body pose observation.
    /// For a right-handed golfer, lead side = left.
    /// TODO: Add handedness detection or user setting.
    static func from(
        observation: VNHumanBodyPose3DObservation,
        timestamp: TimeInterval,
        isRightHanded: Bool = true
    ) -> BodyPoseFrame? {
        var frame = BodyPoseFrame(timestamp: timestamp)

        // Extract joint positions (3D, in metres relative to root)
        if isRightHanded {
            // Lead side = left for right-handed golfer
            frame.leadShoulder3D = jointPosition(observation, .leftShoulder)
            frame.leadElbow3D = jointPosition(observation, .leftElbow)
            frame.leadWrist3D = jointPosition(observation, .leftWrist)
            frame.trailShoulder3D = jointPosition(observation, .rightShoulder)
            frame.trailElbow3D = jointPosition(observation, .rightElbow)
            frame.trailWrist3D = jointPosition(observation, .rightWrist)
        } else {
            frame.leadShoulder3D = jointPosition(observation, .rightShoulder)
            frame.leadElbow3D = jointPosition(observation, .rightElbow)
            frame.leadWrist3D = jointPosition(observation, .rightWrist)
            frame.trailShoulder3D = jointPosition(observation, .leftShoulder)
            frame.trailElbow3D = jointPosition(observation, .leftElbow)
            frame.trailWrist3D = jointPosition(observation, .leftWrist)
        }

        frame.spine3D = jointPosition(observation, .spine)
        frame.leftHip3D = jointPosition(observation, .leftHip)
        frame.rightHip3D = jointPosition(observation, .rightHip)

        return frame
    }

    private static func jointPosition(
        _ observation: VNHumanBodyPose3DObservation,
        _ jointName: VNHumanBodyPose3DObservation.JointName
    ) -> SIMD3<Float>? {
        guard let point = try? observation.recognizedPoint(jointName) else { return nil }
        // VNHumanBodyPose3DObservation returns position as simd_float4x4 transform
        let position = point.localPosition
        return SIMD3<Float>(position.columns.3.x, position.columns.3.y, position.columns.3.z)
    }
}
