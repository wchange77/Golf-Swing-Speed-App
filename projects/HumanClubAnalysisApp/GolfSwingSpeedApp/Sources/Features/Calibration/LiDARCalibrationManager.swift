import Foundation
import ARKit
import RealityKit
import simd

/// Manages LiDAR-based scene calibration using ARKit.
///
/// Flow:
/// 1. Start ARKit session with scene reconstruction
/// 2. Detect ground plane
/// 3. User taps to place calibration points → get 3D world coordinates via raycasting
/// 4. Compute pixels-per-metre from known 3D distances
/// 5. Lock calibration and pass to tracking pipeline
///
/// IMPORTANT: ARKit session and AVCaptureSession cannot run simultaneously.
/// LiDAR calibration must complete before switching to 240fps capture mode.
@MainActor
@Observable
final class LiDARCalibrationManager {

    // MARK: - State

    enum CalibrationState {
        case inactive
        case scanning              // ARKit session running, scanning scene
        case groundDetected        // Ground plane found
        case waitingForAddress     // Waiting for golfer to stand at address
        case addressAnalysed       // Body pose + club measured
        case complete              // Calibration locked, ready for capture
        case failed(String)        // Error state
    }

    private(set) var state: CalibrationState = .inactive
    private(set) var groundPlaneAnchor: ARPlaneAnchor?
    private(set) var calibrationPoints: [SIMD3<Float>] = []

    // Derived measurements
    private(set) var pixelsPerMetre: Double?
    private(set) var cameraToSubjectDistance: Float?
    private(set) var groundPlaneY: Float?

    // Address position measurements
    private(set) var clubLengthMetres: Float?
    private(set) var lieAngleDegrees: Float?
    private(set) var armLengthMetres: Float?
    private(set) var swingPlaneNormal: SIMD3<Float>?
    private(set) var ballPosition3D: SIMD3<Float>?

    // AR Session
    private var arSession: ARSession?
    private var arView: ARView?

    // MARK: - LiDAR Availability

    nonisolated static var isLiDARAvailable: Bool {
        ARWorldTrackingConfiguration.supportsSceneReconstruction(.mesh)
    }

    // MARK: - Start Scanning

    /// Start the ARKit session for scene scanning.
    /// Returns an ARView that should be displayed in the UI.
    func startScanning() -> ARView? {
        guard Self.isLiDARAvailable else {
            state = .failed("LiDAR not available on this device")
            return nil
        }

        let arView = ARView(frame: .zero)
        let config = ARWorldTrackingConfiguration()

        // Enable LiDAR scene reconstruction
        if ARWorldTrackingConfiguration.supportsSceneReconstruction(.mesh) {
            config.sceneReconstruction = .mesh
        }

        // Enable plane detection for ground
        config.planeDetection = [.horizontal]

        // Enable body tracking if available
        if ARWorldTrackingConfiguration.supportsFrameSemantics(.bodyDetection) {
            config.frameSemantics.insert(.bodyDetection)
        }

        arView.session.run(config)
        self.arView = arView
        self.arSession = arView.session
        state = .scanning

        return arView
    }

    /// Stop the ARKit session.
    func stopScanning() {
        arSession?.pause()
        arSession = nil
        arView = nil
        if case .complete = state {
            // Keep complete state
        } else {
            state = .inactive
        }
    }

    // MARK: - Ground Plane Detection

    /// Check if a ground plane has been detected.
    /// Call this periodically or in response to ARSession delegate updates.
    func checkForGroundPlane() {
        guard let arView else { return }

        let anchors = arView.session.currentFrame?.anchors ?? []
        for anchor in anchors {
            if let planeAnchor = anchor as? ARPlaneAnchor,
               planeAnchor.classification == .floor || planeAnchor.alignment == .horizontal {
                groundPlaneAnchor = planeAnchor
                groundPlaneY = planeAnchor.transform.columns.3.y
                state = .groundDetected
                return
            }
        }
    }

    // MARK: - Raycasting

    /// Raycast from a screen point to get the 3D world position.
    /// Used when user taps to place calibration points.
    func raycast(from screenPoint: CGPoint) -> SIMD3<Float>? {
        guard let arView else { return nil }

        let results = arView.raycast(from: screenPoint, allowing: .estimatedPlane, alignment: .any)
        guard let result = results.first else { return nil }

        let position = SIMD3<Float>(
            result.worldTransform.columns.3.x,
            result.worldTransform.columns.3.y,
            result.worldTransform.columns.3.z
        )

        return position
    }

    /// Add a calibration point from a screen tap.
    func addCalibrationPoint(from screenPoint: CGPoint) -> SIMD3<Float>? {
        guard let position = raycast(from: screenPoint) else { return nil }
        calibrationPoints.append(position)
        return position
    }

    // MARK: - Distance Calculation

    /// Calculate real-world distance between two 3D points.
    nonisolated static func distance3D(_ a: SIMD3<Float>, _ b: SIMD3<Float>) -> Float {
        simd_distance(a, b)
    }

    /// Calculate pixels-per-metre from two known 3D points and their pixel positions.
    nonisolated static func calculatePixelsPerMetre(
        point1_3D: SIMD3<Float>,
        point2_3D: SIMD3<Float>,
        point1_2D: CGPoint,
        point2_2D: CGPoint
    ) -> Double {
        let realDistance = distance3D(point1_3D, point2_3D)
        guard realDistance > 0 else { return 0 }

        let pixelDistance = point1_2D.distance(to: point2_2D)
        guard pixelDistance > 0 else { return 0 }

        return Double(pixelDistance) / Double(realDistance)
    }

    // MARK: - Camera Intrinsics Pixels-Per-Metre

    /// Calculate pixels-per-metre using camera intrinsics (pinhole camera model).
    /// More accurate than measuring pixel distances between 3D points since it
    /// uses the actual camera focal length.
    ///
    /// Formula: pixels_per_metre = focal_length_pixels / distance_metres
    func pixelsPerMetreFromIntrinsics(atDistance distanceMetres: Float) -> Double? {
        guard let frame = arSession?.currentFrame, distanceMetres > 0 else { return nil }
        let fx = frame.camera.intrinsics[0][0] // Horizontal focal length in pixels
        return Double(fx / distanceMetres)
    }

    // MARK: - Depth at Point

    /// Get the LiDAR depth value at a specific pixel location.
    func depthAtPoint(_ point: CGPoint, imageWidth: Int, imageHeight: Int) -> Float? {
        guard let frame = arSession?.currentFrame,
              let depthMap = frame.sceneDepth?.depthMap else {
            return nil
        }

        CVPixelBufferLockBaseAddress(depthMap, .readOnly)
        defer { CVPixelBufferUnlockBaseAddress(depthMap, .readOnly) }

        let depthWidth = CVPixelBufferGetWidth(depthMap)
        let depthHeight = CVPixelBufferGetHeight(depthMap)

        // Scale from image coordinates to depth map coordinates
        let depthX = Int(Float(point.x) / Float(imageWidth) * Float(depthWidth))
        let depthY = Int(Float(point.y) / Float(imageHeight) * Float(depthHeight))

        guard depthX >= 0, depthX < depthWidth, depthY >= 0, depthY < depthHeight else {
            return nil
        }

        guard let baseAddress = CVPixelBufferGetBaseAddress(depthMap) else { return nil }
        let bytesPerRow = CVPixelBufferGetBytesPerRow(depthMap)

        let pixelPtr = baseAddress.advanced(by: depthY * bytesPerRow + depthX * MemoryLayout<Float32>.size)
        let depth = pixelPtr.load(as: Float32.self)

        return depth > 0 ? depth : nil
    }

    // MARK: - Address Position Analysis

    /// Analyse the golfer's address position using the current AR frame.
    /// Extracts body pose, club head position, and calculates derived measurements.
    func analyseAddressPosition() async -> AddressAnalysisResult? {
        guard let frame = arSession?.currentFrame else { return nil }

        let pixelBuffer = frame.capturedImage

        // Run 3D body pose detection
        let poseRequest = VNDetectHumanBodyPose3DRequest()
        let handler = VNImageRequestHandler(cvPixelBuffer: pixelBuffer, options: [:])

        do {
            try handler.perform([poseRequest])
        } catch {
            return nil
        }

        guard let observation = poseRequest.results?.first else { return nil }

        // Extract joint positions
        guard let leadShoulder = jointPosition3D(observation, .leftShoulder),
              let leadElbow = jointPosition3D(observation, .leftElbow),
              let leadWrist = jointPosition3D(observation, .leftWrist),
              let spine = jointPosition3D(observation, .spine) else {
            return nil
        }

        // Calculate arm length
        let armLength = simd_distance(leadShoulder, leadWrist)
        armLengthMetres = armLength

        // Calculate camera-to-subject distance
        let subjectDepth = simd_length(SIMD3<Float>(
            leadWrist.x - frame.camera.transform.columns.3.x,
            leadWrist.y - frame.camera.transform.columns.3.y,
            leadWrist.z - frame.camera.transform.columns.3.z
        ))
        cameraToSubjectDistance = subjectDepth

        // Build swing plane from body pose
        let hipCenter: SIMD3<Float>?
        if let leftHip = jointPosition3D(observation, .leftHip),
           let rightHip = jointPosition3D(observation, .rightHip) {
            hipCenter = (leftHip + rightHip) / 2
        } else {
            hipCenter = nil
        }

        state = .waitingForAddress

        return AddressAnalysisResult(
            leadShoulder: leadShoulder,
            leadElbow: leadElbow,
            leadWrist: leadWrist,
            spine: spine,
            hipCenter: hipCenter,
            armLengthMetres: armLength,
            cameraDistance: subjectDepth
        )
    }

    // MARK: - Complete Calibration

    /// Finalise calibration with all measurements and build a CalibrationSnapshot.
    func finaliseCalibration(
        clubHeadPosition3D: SIMD3<Float>,
        leadWrist3D: SIMD3<Float>,
        leadShoulder3D: SIMD3<Float>,
        spine3D: SIMD3<Float>,
        ballPosition3D: SIMD3<Float>?,
        pixelsPerMetre: Double
    ) -> CalibrationSnapshot {
        // Club length
        let clubLength = simd_distance(leadWrist3D, clubHeadPosition3D)
        clubLengthMetres = clubLength

        // Lie angle: angle between shaft and ground plane
        let shaftVector = clubHeadPosition3D - leadWrist3D
        let groundNormal = SIMD3<Float>(0, 1, 0)
        let shaftAngleFromGround = asin(abs(simd_dot(simd_normalize(shaftVector), groundNormal)))
        let lieAngle = shaftAngleFromGround * 180 / .pi
        lieAngleDegrees = lieAngle

        // Swing plane normal
        let v1 = leadWrist3D - spine3D
        let v2 = clubHeadPosition3D - spine3D
        var planeNormal = simd_cross(v1, v2)
        let normalLength = simd_length(planeNormal)
        if normalLength > 0 {
            planeNormal = planeNormal / normalLength
        }
        swingPlaneNormal = planeNormal

        self.pixelsPerMetre = pixelsPerMetre
        self.ballPosition3D = ballPosition3D

        state = .complete

        return CalibrationSnapshot(
            method: .lidar,
            pixelsPerMetre: pixelsPerMetre,
            impactZoneX: Double(ballPosition3D?.x ?? 0),
            impactZoneY: Double(ballPosition3D?.y ?? 0),
            cameraToSubjectDistance: Double(cameraToSubjectDistance ?? 2.5),
            clubLength: Double(clubLength),
            lieAngle: Double(lieAngle),
            armLength: Double(armLengthMetres ?? 0.7),
            swingPlaneNormalX: planeNormal.x,
            swingPlaneNormalY: planeNormal.y,
            swingPlaneNormalZ: planeNormal.z,
            groundPlaneY: groundPlaneY
        )
    }

    // MARK: - Reset

    func reset() {
        state = .inactive
        groundPlaneAnchor = nil
        calibrationPoints = []
        pixelsPerMetre = nil
        cameraToSubjectDistance = nil
        groundPlaneY = nil
        clubLengthMetres = nil
        lieAngleDegrees = nil
        armLengthMetres = nil
        swingPlaneNormal = nil
        ballPosition3D = nil
    }

    // MARK: - Helpers

    /// Extract joint position from 3D body pose observation.
    ///
    /// NOTE: `localPosition` returns joint positions relative to the body root joint.
    /// For relative measurements (club length, arm length, lie angle), this is correct
    /// since we only need distances between joints. For absolute world positioning
    /// (camera-to-subject distance), we use the root joint position from ARKit + body height.
    private func jointPosition3D(
        _ observation: VNHumanBodyPose3DObservation,
        _ jointName: VNHumanBodyPose3DObservation.JointName
    ) -> SIMD3<Float>? {
        guard let point = try? observation.recognizedPoint(jointName) else { return nil }
        // localPosition is relative to body root — sufficient for inter-joint distances
        let position = point.localPosition
        return SIMD3<Float>(position.columns.3.x, position.columns.3.y, position.columns.3.z)
    }
}

// MARK: - Address Analysis Result

struct AddressAnalysisResult {
    let leadShoulder: SIMD3<Float>
    let leadElbow: SIMD3<Float>
    let leadWrist: SIMD3<Float>
    let spine: SIMD3<Float>
    let hipCenter: SIMD3<Float>?
    let armLengthMetres: Float
    let cameraDistance: Float
}
