import Foundation
import simd

/// 2D Kalman filter for tracking a point (club head) through video frames.
/// State vector: [x, y, vx, vy] — position and velocity.
/// Handles prediction through occlusion and smoothing of noisy detections.
struct KalmanFilter2D {
    /// State: [x, y, vx, vy]
    private(set) var state: SIMD4<Float>

    /// State covariance matrix (4x4)
    private(set) var covariance: simd_float4x4

    /// Process noise covariance
    private let processNoise: simd_float4x4

    /// Measurement noise covariance (2x2 for [x, y] observations)
    private let measurementNoise: simd_float2x2

    /// Number of consecutive frames without a detection
    private(set) var framesWithoutDetection: Int = 0

    /// Maximum frames to predict without detection before declaring track lost
    static let maxPredictionFrames = 10

    var position: CGPoint {
        CGPoint(x: CGFloat(state.x), y: CGFloat(state.y))
    }

    var velocity: CGPoint {
        CGPoint(x: CGFloat(state.z), y: CGFloat(state.w))
    }

    var speed: Float {
        sqrt(state.z * state.z + state.w * state.w)
    }

    var isTrackLost: Bool {
        framesWithoutDetection > Self.maxPredictionFrames
    }

    // MARK: - Initialisation

    init(
        initialPosition: CGPoint,
        initialVelocity: CGPoint = .zero,
        processNoiseScale: Float = 100.0,
        measurementNoiseScale: Float = 4.0
    ) {
        self.state = SIMD4<Float>(
            Float(initialPosition.x),
            Float(initialPosition.y),
            Float(initialVelocity.x),
            Float(initialVelocity.y)
        )

        // Initial covariance — moderate uncertainty
        self.covariance = simd_float4x4(diagonal: SIMD4<Float>(100, 100, 1000, 1000))

        // Process noise — how much we expect the motion to deviate from constant velocity
        // Higher values for golf (acceleration through downswing is extreme)
        self.processNoise = simd_float4x4(diagonal: SIMD4<Float>(
            processNoiseScale,
            processNoiseScale,
            processNoiseScale * 10, // velocity changes rapidly
            processNoiseScale * 10
        ))

        // Measurement noise — how noisy our detections are (in pixels)
        self.measurementNoise = simd_float2x2(diagonal: SIMD2<Float>(
            measurementNoiseScale,
            measurementNoiseScale
        ))
    }

    // MARK: - Predict

    /// Predict the next state given a time delta.
    /// Call this for every frame, even when no detection is available.
    mutating func predict(dt: Float) {
        // State transition matrix: constant velocity model
        // x' = x + vx * dt
        // y' = y + vy * dt
        // vx' = vx
        // vy' = vy
        let F = simd_float4x4(rows: [
            SIMD4<Float>(1, 0, dt, 0),
            SIMD4<Float>(0, 1, 0, dt),
            SIMD4<Float>(0, 0, 1, 0),
            SIMD4<Float>(0, 0, 0, 1)
        ])

        // Scale process noise by dt to account for variable frame intervals
        let Q = processNoise * (dt * dt)

        // Predict state
        state = F * state

        // Predict covariance: P' = F * P * F^T + Q
        covariance = F * covariance * F.transpose + Q

        framesWithoutDetection += 1
    }

    // MARK: - Update

    /// Update the state with a new detection.
    /// Call this when the club head is successfully detected in a frame.
    mutating func update(measurement: CGPoint) {
        let z = SIMD2<Float>(Float(measurement.x), Float(measurement.y))

        // Measurement matrix H: maps state to measurement space
        // We observe [x, y] from state [x, y, vx, vy]
        // H = [[1, 0, 0, 0], [0, 1, 0, 0]]

        // Innovation (measurement residual)
        let predicted = SIMD2<Float>(state.x, state.y)
        let innovation = z - predicted

        // Innovation covariance: S = H * P * H^T + R
        let S = simd_float2x2(
            SIMD2<Float>(covariance[0][0], covariance[0][1]),
            SIMD2<Float>(covariance[1][0], covariance[1][1])
        ) + measurementNoise

        // Kalman gain: K = P * H^T * S^-1
        let S_inv = S.inverse

        // K is 4x2: P[4x4] * H^T[4x2] * S^-1[2x2]
        // H^T columns are [1,0,0,0] and [0,1,0,0]
        let PHt_col0 = SIMD4<Float>(covariance[0][0], covariance[1][0], covariance[2][0], covariance[3][0])
        let PHt_col1 = SIMD4<Float>(covariance[0][1], covariance[1][1], covariance[2][1], covariance[3][1])

        let K_col0 = PHt_col0 * S_inv[0][0] + PHt_col1 * S_inv[1][0]
        let K_col1 = PHt_col0 * S_inv[0][1] + PHt_col1 * S_inv[1][1]

        // Update state: x = x + K * innovation
        state = state + K_col0 * innovation.x + K_col1 * innovation.y

        // Update covariance: P = (I - K * H) * P
        // K*H is 4x4
        let KH = simd_float4x4(
            SIMD4<Float>(K_col0.x, K_col1.x, 0, 0),
            SIMD4<Float>(K_col0.y, K_col1.y, 0, 0),
            SIMD4<Float>(K_col0.z, K_col1.z, 0, 0),
            SIMD4<Float>(K_col0.w, K_col1.w, 0, 0)
        )

        let I = simd_float4x4(diagonal: SIMD4<Float>(repeating: 1))
        covariance = (I - KH) * covariance

        framesWithoutDetection = 0
    }

    // MARK: - Constrained Prediction

    /// Predict with a constraint that the club head must be within a maximum radius
    /// of the wrist position (club length constraint from calibration).
    mutating func predictConstrained(
        dt: Float,
        wristPosition: CGPoint?,
        maxRadiusPixels: Float?
    ) {
        predict(dt: dt)

        // Apply club length constraint if available
        if let wrist = wristPosition, let maxRadius = maxRadiusPixels {
            let dx = state.x - Float(wrist.x)
            let dy = state.y - Float(wrist.y)
            let distance = sqrt(dx * dx + dy * dy)

            if distance > maxRadius {
                // Project back to the constraint boundary
                let scale = maxRadius / distance
                state.x = Float(wrist.x) + dx * scale
                state.y = Float(wrist.y) + dy * scale
            }
        }
    }
}

// MARK: - simd_float4x4 helpers

extension simd_float4x4 {
    init(rows: [SIMD4<Float>]) {
        precondition(rows.count == 4)
        // simd_float4x4 stores columns, but we want to init from rows
        self.init(
            SIMD4<Float>(rows[0].x, rows[1].x, rows[2].x, rows[3].x),
            SIMD4<Float>(rows[0].y, rows[1].y, rows[2].y, rows[3].y),
            SIMD4<Float>(rows[0].z, rows[1].z, rows[2].z, rows[3].z),
            SIMD4<Float>(rows[0].w, rows[1].w, rows[2].w, rows[3].w)
        )
    }
}
