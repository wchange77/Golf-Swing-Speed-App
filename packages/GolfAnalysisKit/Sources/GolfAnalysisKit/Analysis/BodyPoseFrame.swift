import Foundation
import Vision
import simd

public struct BodyPoseFrame: Sendable {
    public var timestamp: TimeInterval

    public var leadShoulder3D: SIMD3<Float>?
    public var leadElbow3D: SIMD3<Float>?
    public var leadWrist3D: SIMD3<Float>?
    public var trailShoulder3D: SIMD3<Float>?
    public var trailElbow3D: SIMD3<Float>?
    public var trailWrist3D: SIMD3<Float>?
    public var spine3D: SIMD3<Float>?
    public var leftHip3D: SIMD3<Float>?
    public var rightHip3D: SIMD3<Float>?

    public var leadElbow2D: CGPoint?
    public var leadWrist2D: CGPoint?

    public var leadArmAngleToVertical: Double? {
        guard let shoulder = leadShoulder3D, let wrist = leadWrist3D else { return nil }
        let armVector = wrist - shoulder
        let vertical = SIMD3<Float>(0, -1, 0)
        let dot = simd_dot(simd_normalize(armVector), vertical)
        return Double(acos(Swift.max(-1, Swift.min(1, dot))).toDegrees)
    }

    public init(
        timestamp: TimeInterval,
        leadShoulder3D: SIMD3<Float>? = nil,
        leadElbow3D: SIMD3<Float>? = nil,
        leadWrist3D: SIMD3<Float>? = nil,
        trailShoulder3D: SIMD3<Float>? = nil,
        trailElbow3D: SIMD3<Float>? = nil,
        trailWrist3D: SIMD3<Float>? = nil,
        spine3D: SIMD3<Float>? = nil,
        leftHip3D: SIMD3<Float>? = nil,
        rightHip3D: SIMD3<Float>? = nil,
        leadElbow2D: CGPoint? = nil,
        leadWrist2D: CGPoint? = nil
    ) {
        self.timestamp = timestamp
        self.leadShoulder3D = leadShoulder3D
        self.leadElbow3D = leadElbow3D
        self.leadWrist3D = leadWrist3D
        self.trailShoulder3D = trailShoulder3D
        self.trailElbow3D = trailElbow3D
        self.trailWrist3D = trailWrist3D
        self.spine3D = spine3D
        self.leftHip3D = leftHip3D
        self.rightHip3D = rightHip3D
        self.leadElbow2D = leadElbow2D
        self.leadWrist2D = leadWrist2D
    }
}

extension BodyPoseFrame {
    public static func from(
        observation: VNHumanBodyPose3DObservation,
        timestamp: TimeInterval,
        isRightHanded: Bool = true
    ) -> BodyPoseFrame? {
        var frame = BodyPoseFrame(timestamp: timestamp)

        if isRightHanded {
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
        let position = point.localPosition
        return SIMD3<Float>(position.columns.3.x, position.columns.3.y, position.columns.3.z)
    }
}
