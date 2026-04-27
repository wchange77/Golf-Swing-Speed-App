import Foundation
import CoreGraphics

public struct KalmanFilter6D: Sendable {

    public struct State: Sendable {
        public var x: Float
        public var y: Float
        public var vx: Float
        public var vy: Float
        public var ax: Float
        public var ay: Float

        public var position: CGPoint { CGPoint(x: CGFloat(x), y: CGFloat(y)) }
        public var velocity: CGPoint { CGPoint(x: CGFloat(vx), y: CGFloat(vy)) }
        public var speed: Float { sqrt(vx * vx + vy * vy) }
        public var acceleration: CGPoint { CGPoint(x: CGFloat(ax), y: CGFloat(ay)) }
    }

    public struct Prediction: Sendable {
        public var position: CGPoint
        public var velocity: CGPoint
        public var uncertaintyX: Float
        public var uncertaintyY: Float
        public var searchRadius: Float
    }

    public struct Config: Sendable {
        public var gravityPixelsPerS2: Float = 500.0
        public var positionNoise: Float = 2.0
        public var velocityNoise: Float = 5.0
        public var accelerationNoise: Float = 0.5
        public var measurementNoise: Float = 5.0
        public var maxPredictionFrames: Int = 15
        public var mahalanobisThreshold: Float = 3.0

        public init(
            gravityPixelsPerS2: Float = 500.0,
            positionNoise: Float = 2.0,
            velocityNoise: Float = 5.0,
            accelerationNoise: Float = 0.5,
            measurementNoise: Float = 5.0,
            maxPredictionFrames: Int = 15,
            mahalanobisThreshold: Float = 3.0
        ) {
            self.gravityPixelsPerS2 = gravityPixelsPerS2
            self.positionNoise = positionNoise
            self.velocityNoise = velocityNoise
            self.accelerationNoise = accelerationNoise
            self.measurementNoise = measurementNoise
            self.maxPredictionFrames = maxPredictionFrames
            self.mahalanobisThreshold = mahalanobisThreshold
        }
    }

    private var config: Config
    private var state: [Float] // 6 elements: [x, y, vx, vy, ax, ay]
    private var covariance: [Float] // 6×6 = 36 elements, row-major
    private var processNoiseDiag: [Float] // 6 elements
    private var measurementNoiseDiag: [Float] // 2 elements
    private(set) public var framesWithoutDetection: Int = 0
    private(set) public var isInitialized: Bool = false

    public var currentState: State? {
        guard isInitialized else { return nil }
        return State(x: state[0], y: state[1], vx: state[2], vy: state[3], ax: state[4], ay: state[5])
    }

    public var isTrackLost: Bool {
        framesWithoutDetection > config.maxPredictionFrames
    }

    public init(config: Config = Config()) {
        self.config = config
        self.state = [Float](repeating: 0, count: 6)
        self.covariance = [Float](repeating: 0, count: 36)
        self.processNoiseDiag = [
            config.positionNoise * config.positionNoise,
            config.positionNoise * config.positionNoise,
            config.velocityNoise * config.velocityNoise,
            config.velocityNoise * config.velocityNoise,
            config.accelerationNoise * config.accelerationNoise,
            config.accelerationNoise * config.accelerationNoise,
        ]
        self.measurementNoiseDiag = [
            config.measurementNoise * config.measurementNoise,
            config.measurementNoise * config.measurementNoise,
        ]
    }

    public mutating func initialize(
        position: CGPoint,
        velocity: CGPoint = .zero,
        acceleration: CGPoint? = nil
    ) {
        let ay = acceleration.map { Float($0.y) } ?? (config.gravityPixelsPerS2)
        let ax = acceleration.map { Float($0.x) } ?? 0

        state = [Float(position.x), Float(position.y), Float(velocity.x), Float(velocity.y), ax, ay]

        covariance = Self.diagonal6x6([10, 10, 50, 50, 10, 10])
        framesWithoutDetection = 0
        isInitialized = true
    }

    public mutating func predict(dt: Float) -> Prediction? {
        guard isInitialized else { return nil }

        let dt2 = dt * dt
        // F matrix: constant acceleration model
        // x' = x + vx*dt + 0.5*ax*dt²
        let F = Self.transitionMatrix(dt: dt)

        // State prediction
        let predictedState = Self.matVec6(F, state)

        // Covariance prediction: P' = F*P*F^T + Q
        let FP = Self.matMul6x6(F, covariance)
        let Ft = Self.transpose6x6(F)
        var predictedCov = Self.matMul6x6(FP, Ft)

        // Add process noise scaled by dt²
        for i in 0..<6 {
            predictedCov[i * 6 + i] += processNoiseDiag[i] * dt2
        }

        state = predictedState
        covariance = predictedCov
        framesWithoutDetection += 1

        let ux = sqrt(covariance[0])
        let uy = sqrt(covariance[7])
        let searchRadius = config.mahalanobisThreshold * max(ux, uy)

        return Prediction(
            position: CGPoint(x: CGFloat(state[0]), y: CGFloat(state[1])),
            velocity: CGPoint(x: CGFloat(state[2]), y: CGFloat(state[3])),
            uncertaintyX: ux,
            uncertaintyY: uy,
            searchRadius: searchRadius
        )
    }

    public mutating func update(measurement: CGPoint, confidence: Float = 1.0) {
        guard isInitialized else { return }

        let z = [Float(measurement.x), Float(measurement.y)]
        let innovation = [z[0] - state[0], z[1] - state[1]]

        let noiseScale: Float = confidence > 0 ? 1.0 / confidence : 10.0

        // S = H*P*H^T + R (2×2)
        // H = [[1,0,0,0,0,0],[0,1,0,0,0,0]], so S = P[0:2,0:2] + R
        let s00 = covariance[0] + measurementNoiseDiag[0] * noiseScale
        let s01 = covariance[1]
        let s10 = covariance[6]
        let s11 = covariance[7] + measurementNoiseDiag[1] * noiseScale

        // S inverse (2×2)
        let det = s00 * s11 - s01 * s10
        guard abs(det) > 1e-12 else { return }
        let invDet = 1.0 / det
        let si00 = s11 * invDet
        let si01 = -s01 * invDet
        let si10 = -s10 * invDet
        let si11 = s00 * invDet

        // K = P*H^T*S^-1 (6×2)
        // P*H^T is columns 0,1 of P
        var K = [Float](repeating: 0, count: 12)
        for i in 0..<6 {
            let ph0 = covariance[i * 6 + 0]
            let ph1 = covariance[i * 6 + 1]
            K[i * 2 + 0] = ph0 * si00 + ph1 * si10
            K[i * 2 + 1] = ph0 * si01 + ph1 * si11
        }

        // State update: x = x + K*innovation
        for i in 0..<6 {
            state[i] += K[i * 2 + 0] * innovation[0] + K[i * 2 + 1] * innovation[1]
        }

        // Covariance update: P = (I - K*H)*P
        // KH is 6×6 where KH[i][j] = K[i][0]*H[0][j] + K[i][1]*H[1][j]
        // H[0][j] = (j==0?1:0), H[1][j] = (j==1?1:0)
        // So KH[i][j] = K[i][0] if j==0, K[i][1] if j==1, 0 otherwise
        var newCov = [Float](repeating: 0, count: 36)
        for i in 0..<6 {
            for j in 0..<6 {
                var ikhij: Float = (i == j) ? 1.0 : 0.0
                if j == 0 { ikhij -= K[i * 2 + 0] }
                if j == 1 { ikhij -= K[i * 2 + 1] }

                var sum: Float = 0
                for k in 0..<6 {
                    sum += ikhij * covariance[k * 6 + j] * ((i == k) ? 1.0 : 0.0)
                }
                newCov[i * 6 + j] = 0
            }
        }

        // Simpler: P = (I-KH)*P directly
        let oldCov = covariance
        for i in 0..<6 {
            for j in 0..<6 {
                var val: Float = 0
                for k in 0..<6 {
                    var ikh: Float = (i == k) ? 1.0 : 0.0
                    if k == 0 { ikh -= K[i * 2 + 0] }
                    if k == 1 { ikh -= K[i * 2 + 1] }
                    val += ikh * oldCov[k * 6 + j]
                }
                covariance[i * 6 + j] = val
            }
        }

        framesWithoutDetection = 0
    }

    public func isMeasurementPlausible(_ measurement: CGPoint) -> Bool {
        guard isInitialized else { return true }

        let dx = Float(measurement.x) - state[0]
        let dy = Float(measurement.y) - state[1]

        let sx = covariance[0] + measurementNoiseDiag[0]
        let sy = covariance[7] + measurementNoiseDiag[1]

        guard sx > 0, sy > 0 else { return true }

        let mahal = (dx * dx) / sx + (dy * dy) / sy
        let threshold = config.mahalanobisThreshold * config.mahalanobisThreshold * 2
        return mahal <= threshold
    }

    public mutating func reset() {
        state = [Float](repeating: 0, count: 6)
        covariance = [Float](repeating: 0, count: 36)
        framesWithoutDetection = 0
        isInitialized = false
    }

    // MARK: - 6×6 Matrix Operations (row-major)

    private static func transitionMatrix(dt: Float) -> [Float] {
        let dt2 = 0.5 * dt * dt
        // Row-major 6×6
        return [
            1, 0, dt, 0,  dt2, 0,
            0, 1, 0,  dt, 0,   dt2,
            0, 0, 1,  0,  dt,  0,
            0, 0, 0,  1,  0,   dt,
            0, 0, 0,  0,  1,   0,
            0, 0, 0,  0,  0,   1,
        ]
    }

    private static func diagonal6x6(_ diag: [Float]) -> [Float] {
        var m = [Float](repeating: 0, count: 36)
        for i in 0..<6 { m[i * 6 + i] = diag[i] }
        return m
    }

    private static func matVec6(_ m: [Float], _ v: [Float]) -> [Float] {
        var result = [Float](repeating: 0, count: 6)
        for i in 0..<6 {
            var sum: Float = 0
            for j in 0..<6 { sum += m[i * 6 + j] * v[j] }
            result[i] = sum
        }
        return result
    }

    private static func matMul6x6(_ a: [Float], _ b: [Float]) -> [Float] {
        var c = [Float](repeating: 0, count: 36)
        for i in 0..<6 {
            for j in 0..<6 {
                var sum: Float = 0
                for k in 0..<6 { sum += a[i * 6 + k] * b[k * 6 + j] }
                c[i * 6 + j] = sum
            }
        }
        return c
    }

    private static func transpose6x6(_ m: [Float]) -> [Float] {
        var t = [Float](repeating: 0, count: 36)
        for i in 0..<6 {
            for j in 0..<6 { t[j * 6 + i] = m[i * 6 + j] }
        }
        return t
    }
}

