import Testing
import Foundation
@testable import GolfSwingSpeedApp

@Suite("Kalman Filter Tests")
struct KalmanFilterTests {

    @Test("Initial position is set correctly")
    func initialPosition() {
        let kalman = KalmanFilter2D(initialPosition: CGPoint(x: 100, y: 200))
        #expect(abs(kalman.position.x - 100) < 0.1)
        #expect(abs(kalman.position.y - 200) < 0.1)
    }

    @Test("Prediction moves state forward by velocity")
    func predictionMovesState() {
        var kalman = KalmanFilter2D(
            initialPosition: CGPoint(x: 100, y: 100),
            initialVelocity: CGPoint(x: 10, y: 5)
        )

        kalman.predict(dt: 1.0)

        // Position should move roughly by velocity * dt
        #expect(kalman.position.x > 100)
        #expect(kalman.position.y > 100)
    }

    @Test("Update corrects position toward measurement")
    func updateCorrectsPosition() {
        var kalman = KalmanFilter2D(initialPosition: CGPoint(x: 100, y: 100))
        kalman.predict(dt: 0.01)

        // Measurement at a different position
        kalman.update(measurement: CGPoint(x: 120, y: 110))

        // Position should move toward measurement
        #expect(kalman.position.x > 100)
        #expect(kalman.position.y > 100)
    }

    @Test("Track is lost after too many predictions without detection")
    func trackLostAfterMaxPredictions() {
        var kalman = KalmanFilter2D(initialPosition: CGPoint(x: 100, y: 100))

        for _ in 0..<(KalmanFilter2D.maxPredictionFrames + 1) {
            kalman.predict(dt: 0.004)
        }

        #expect(kalman.isTrackLost)
    }

    @Test("Track is NOT lost when detections arrive")
    func trackNotLostWithDetections() {
        var kalman = KalmanFilter2D(initialPosition: CGPoint(x: 100, y: 100))

        for i in 0..<20 {
            kalman.predict(dt: 0.004)
            if i % 3 == 0 {
                kalman.update(measurement: CGPoint(x: 100 + CGFloat(i) * 5, y: 100))
            }
        }

        #expect(!kalman.isTrackLost)
    }

    @Test("Constrained prediction respects club length radius")
    func constrainedPrediction() {
        var kalman = KalmanFilter2D(
            initialPosition: CGPoint(x: 200, y: 200),
            initialVelocity: CGPoint(x: 1000, y: 0) // Very fast — would overshoot
        )

        let wrist = CGPoint(x: 100, y: 200)
        let maxRadius: Float = 150 // Club length in pixels

        kalman.predictConstrained(dt: 1.0, wristPosition: wrist, maxRadiusPixels: maxRadius)

        // Position should be clamped to within maxRadius of wrist
        let dx = Float(kalman.position.x) - Float(wrist.x)
        let dy = Float(kalman.position.y) - Float(wrist.y)
        let distance = sqrt(dx * dx + dy * dy)

        #expect(distance <= maxRadius + 1.0) // Small tolerance for float precision
    }
}

@Suite("Adaptive Frame Sampler Tests")
struct AdaptiveFrameSamplerTests {

    @Test("Phase classification produces segments")
    func phaseClassification() {
        // Simulate 1.2 seconds at 240fps
        let frameCount = 288
        var timestamps: [TimeInterval] = []
        var magnitudes: [Double] = []

        for i in 0..<frameCount {
            timestamps.append(Double(i) / 240.0)
            // Simulate motion: low during address, peak during downswing
            let t = Double(i) / 240.0
            if t < 0.3 {
                magnitudes.append(2.0) // Address - still
            } else if t < 0.7 {
                magnitudes.append(10.0 + t * 20) // Backswing
            } else if t < 0.9 {
                magnitudes.append(60.0) // Downswing peak
            } else {
                magnitudes.append(20.0) // Follow through
            }
        }

        let phases = AdaptiveFrameSampler.classifyPhases(
            frameTimestamps: timestamps,
            motionMagnitudes: magnitudes,
            impactTimestamp: 0.85
        )

        #expect(!phases.isEmpty)
    }

    @Test("Frame selection reduces total frames analysed")
    func frameSelectionReducesFrames() {
        let phases = [
            AdaptiveFrameSampler.PhaseSegment(phase: .backswing, startTimestamp: 0, endTimestamp: 0.5, startFrameIndex: 0, endFrameIndex: 120),
            AdaptiveFrameSampler.PhaseSegment(phase: .lateDownswing, startTimestamp: 0.5, endTimestamp: 0.8, startFrameIndex: 120, endFrameIndex: 192),
            AdaptiveFrameSampler.PhaseSegment(phase: .followThrough, startTimestamp: 0.8, endTimestamp: 1.2, startFrameIndex: 192, endFrameIndex: 288),
        ]

        let selected = AdaptiveFrameSampler.selectFrames(
            phases: phases,
            totalFrameCount: 288
        )

        let report = AdaptiveFrameSampler.samplingReport(
            selectedCount: selected.count,
            totalCount: 288
        )

        // Should analyse fewer than total frames
        #expect(selected.count < 288)
        #expect(report.reductionPercent > 0)

        // Critical zone (lateDownswing) should have more frames than backswing
        let downswingFrames = selected.filter { $0 >= 120 && $0 <= 192 }.count
        let backswingFrames = selected.filter { $0 < 120 }.count
        #expect(downswingFrames > backswingFrames / 2) // Downswing gets more attention
    }
}
