import Foundation
import CoreGraphics
import simd

public struct KalmanFilter2D {
    private(set) public var state: SIMD4<Float>
    private(set) public var covariance: simd_float4x4
    private let processNoise: simd_float4x4
    private let measurementNoise: simd_float2x2
    private(set) public var framesWithoutDetection: Int = 0
    public static let maxPredictionFrames = 10

    public var position: CGPoint {
        CGPoint(x: CGFloat(state.x), y: CGFloat(state.y))
    }

    public var velocity: CGPoint {
        CGPoint(x: CGFloat(state.z), y: CGFloat(state.w))
    }

    public var speed: Float {
        sqrt(state.z * state.z + state.w * state.w)
    }

    public var isTrackLost: Bool {
        framesWithoutDetection > Self.maxPredictionFrames
    }

    public init(
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
        self.covariance = simd_float4x4(diagonal: SIMD4<Float>(100, 100, 1000, 1000))
        self.processNoise = simd_float4x4(diagonal: SIMD4<Float>(
            processNoiseScale,
            processNoiseScale,
            processNoiseScale * 10,
            processNoiseScale * 10
        ))
        self.measurementNoise = simd_float2x2(diagonal: SIMD2<Float>(
            measurementNoiseScale,
            measurementNoiseScale
        ))
    }

    public mutating func predict(dt: Float) {
        let F = simd_float4x4(rows: [
            SIMD4<Float>(1, 0, dt, 0),
            SIMD4<Float>(0, 1, 0, dt),
            SIMD4<Float>(0, 0, 1, 0),
            SIMD4<Float>(0, 0, 0, 1)
        ])
        let Q = processNoise * (dt * dt)
        state = F * state
        covariance = F * covariance * F.transpose + Q
        framesWithoutDetection += 1
    }

    public mutating func update(measurement: CGPoint) {
        let z = SIMD2<Float>(Float(measurement.x), Float(measurement.y))
        let predicted = SIMD2<Float>(state.x, state.y)
        let innovation = z - predicted

        let S = simd_float2x2(
            SIMD2<Float>(covariance[0][0], covariance[0][1]),
            SIMD2<Float>(covariance[1][0], covariance[1][1])
        ) + measurementNoise

        let S_inv = S.inverse
        let PHt_col0 = SIMD4<Float>(covariance[0][0], covariance[1][0], covariance[2][0], covariance[3][0])
        let PHt_col1 = SIMD4<Float>(covariance[0][1], covariance[1][1], covariance[2][1], covariance[3][1])

        let K_col0 = PHt_col0 * S_inv[0][0] + PHt_col1 * S_inv[1][0]
        let K_col1 = PHt_col0 * S_inv[0][1] + PHt_col1 * S_inv[1][1]

        state = state + K_col0 * innovation.x + K_col1 * innovation.y

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

    public mutating func predictConstrained(
        dt: Float,
        wristPosition: CGPoint?,
        maxRadiusPixels: Float?
    ) {
        predict(dt: dt)
        if let wrist = wristPosition, let maxRadius = maxRadiusPixels {
            let dx = state.x - Float(wrist.x)
            let dy = state.y - Float(wrist.y)
            let distance = sqrt(dx * dx + dy * dy)
            if distance > maxRadius {
                let scale = maxRadius / distance
                state.x = Float(wrist.x) + dx * scale
                state.y = Float(wrist.y) + dy * scale
            }
        }
    }
}

extension simd_float4x4 {
    public init(rows: [SIMD4<Float>]) {
        precondition(rows.count == 4)
        self.init(
            SIMD4<Float>(rows[0].x, rows[1].x, rows[2].x, rows[3].x),
            SIMD4<Float>(rows[0].y, rows[1].y, rows[2].y, rows[3].y),
            SIMD4<Float>(rows[0].z, rows[1].z, rows[2].z, rows[3].z),
            SIMD4<Float>(rows[0].w, rows[1].w, rows[2].w, rows[3].w)
        )
    }
}
