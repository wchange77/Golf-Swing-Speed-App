import Foundation
import CoreImage
import Accelerate

/// Detects motion between consecutive video frames using frame differencing.
/// Used for swing onset/completion detection and basic motion magnitude measurement.
struct MotionDetector {

    /// Calculate the average absolute pixel difference between two frames.
    /// Returns a single scalar representing overall motion magnitude.
    static func frameDifference(
        current: CVPixelBuffer,
        previous: CVPixelBuffer
    ) -> Double {
        let width = CVPixelBufferGetWidth(current)
        let height = CVPixelBufferGetHeight(current)

        guard width == CVPixelBufferGetWidth(previous),
              height == CVPixelBufferGetHeight(previous) else {
            return 0
        }

        CVPixelBufferLockBaseAddress(current, .readOnly)
        CVPixelBufferLockBaseAddress(previous, .readOnly)
        defer {
            CVPixelBufferUnlockBaseAddress(current, .readOnly)
            CVPixelBufferUnlockBaseAddress(previous, .readOnly)
        }

        guard let currentBase = CVPixelBufferGetBaseAddress(current),
              let previousBase = CVPixelBufferGetBaseAddress(previous) else {
            return 0
        }

        let currentStride = CVPixelBufferGetBytesPerRow(current)
        let previousStride = CVPixelBufferGetBytesPerRow(previous)
        let totalPixels = width * height

        // Sample every Nth pixel for performance (don't need every pixel for motion detection)
        let sampleStride = 4 // Check every 4th pixel
        var totalDiff: Double = 0
        var sampleCount: Double = 0

        for y in stride(from: 0, to: height, by: sampleStride) {
            let currentRow = currentBase.advanced(by: y * currentStride)
            let previousRow = previousBase.advanced(by: y * previousStride)

            for x in stride(from: 0, to: width * 4, by: sampleStride * 4) {
                // BGRA format — use green channel as luminance proxy
                let currentG = currentRow.load(fromByteOffset: x + 1, as: UInt8.self)
                let previousG = previousRow.load(fromByteOffset: x + 1, as: UInt8.self)

                let diff = abs(Int(currentG) - Int(previousG))
                totalDiff += Double(diff)
                sampleCount += 1
            }
        }

        return sampleCount > 0 ? totalDiff / sampleCount : 0
    }

    /// Detect which region of the frame has the most motion.
    /// Divides frame into a grid and returns the cell with highest motion.
    /// Used to roughly locate the swing arc area.
    static func motionHeatmap(
        current: CVPixelBuffer,
        previous: CVPixelBuffer,
        gridSize: Int = 8
    ) -> [[Double]] {
        let width = CVPixelBufferGetWidth(current)
        let height = CVPixelBufferGetHeight(current)
        let cellWidth = width / gridSize
        let cellHeight = height / gridSize

        var heatmap = Array(repeating: Array(repeating: 0.0, count: gridSize), count: gridSize)

        CVPixelBufferLockBaseAddress(current, .readOnly)
        CVPixelBufferLockBaseAddress(previous, .readOnly)
        defer {
            CVPixelBufferUnlockBaseAddress(current, .readOnly)
            CVPixelBufferUnlockBaseAddress(previous, .readOnly)
        }

        guard let currentBase = CVPixelBufferGetBaseAddress(current),
              let previousBase = CVPixelBufferGetBaseAddress(previous) else {
            return heatmap
        }

        let currentStride = CVPixelBufferGetBytesPerRow(current)
        let previousStride = CVPixelBufferGetBytesPerRow(previous)
        let sampleStep = 8 // Sample every 8th pixel within each cell

        for gridY in 0..<gridSize {
            for gridX in 0..<gridSize {
                var cellDiff: Double = 0
                var cellSamples: Double = 0

                let startY = gridY * cellHeight
                let startX = gridX * cellWidth

                for y in stride(from: startY, to: min(startY + cellHeight, height), by: sampleStep) {
                    let currentRow = currentBase.advanced(by: y * currentStride)
                    let previousRow = previousBase.advanced(by: y * previousStride)

                    for x in stride(from: startX * 4, to: min((startX + cellWidth) * 4, width * 4), by: sampleStep * 4) {
                        let cG = currentRow.load(fromByteOffset: x + 1, as: UInt8.self)
                        let pG = previousRow.load(fromByteOffset: x + 1, as: UInt8.self)
                        cellDiff += Double(abs(Int(cG) - Int(pG)))
                        cellSamples += 1
                    }
                }

                heatmap[gridY][gridX] = cellSamples > 0 ? cellDiff / cellSamples : 0
            }
        }

        return heatmap
    }

    /// Find the centre of motion in the frame (weighted centroid of motion heatmap).
    static func motionCentroid(heatmap: [[Double]]) -> CGPoint? {
        var totalWeight: Double = 0
        var weightedX: Double = 0
        var weightedY: Double = 0

        for (y, row) in heatmap.enumerated() {
            for (x, value) in row.enumerated() {
                totalWeight += value
                weightedX += Double(x) * value
                weightedY += Double(y) * value
            }
        }

        guard totalWeight > 0 else { return nil }

        let gridSize = Double(heatmap.count)
        return CGPoint(
            x: weightedX / totalWeight / gridSize,
            y: weightedY / totalWeight / gridSize
        )
    }
}
