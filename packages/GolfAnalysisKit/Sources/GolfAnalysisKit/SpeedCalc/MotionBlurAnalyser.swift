import Foundation
import CoreImage
import Accelerate

public struct BlurAnalysisResult: Sendable {
    public let streakLengthPixels: CGFloat
    public let streakAngleRadians: Double
    public let confidence: Double

    public init(streakLengthPixels: CGFloat, streakAngleRadians: Double, confidence: Double) {
        self.streakLengthPixels = streakLengthPixels
        self.streakAngleRadians = streakAngleRadians
        self.confidence = confidence
    }
}

public struct MotionBlurAnalyser {

    public static func detectBlurStreak(
        in pixelBuffer: CVPixelBuffer,
        roi: CGPoint,
        roiSize: Int = 60
    ) -> BlurAnalysisResult? {
        CVPixelBufferLockBaseAddress(pixelBuffer, .readOnly)
        defer { CVPixelBufferUnlockBaseAddress(pixelBuffer, .readOnly) }

        let width = CVPixelBufferGetWidth(pixelBuffer)
        let height = CVPixelBufferGetHeight(pixelBuffer)
        let bytesPerRow = CVPixelBufferGetBytesPerRow(pixelBuffer)

        guard let baseAddress = CVPixelBufferGetBaseAddress(pixelBuffer) else { return nil }

        let halfSize = roiSize / 2
        let minX = max(0, Int(roi.x) - halfSize)
        let maxX = min(width - 1, Int(roi.x) + halfSize)
        let minY = max(0, Int(roi.y) - halfSize)
        let maxY = min(height - 1, Int(roi.y) + halfSize)

        guard maxX > minX + 4, maxY > minY + 4 else { return nil }

        var gradientMagnitudes: [Float] = []
        var gradientAngles: [Float] = []

        for y in (minY + 1)..<maxY {
            let rowPtr = baseAddress.advanced(by: y * bytesPerRow)
            let prevRowPtr = baseAddress.advanced(by: (y - 1) * bytesPerRow)
            let nextRowPtr = baseAddress.advanced(by: (y + 1) * bytesPerRow)

            for x in (minX + 1)..<maxX {
                let offset = x * 4 + 1

                let left = Float(rowPtr.load(fromByteOffset: offset - 4, as: UInt8.self))
                let right = Float(rowPtr.load(fromByteOffset: offset + 4, as: UInt8.self))
                let above = Float(prevRowPtr.load(fromByteOffset: offset, as: UInt8.self))
                let below = Float(nextRowPtr.load(fromByteOffset: offset, as: UInt8.self))

                let gx = right - left
                let gy = below - above
                let magnitude = sqrt(gx * gx + gy * gy)
                let angle = atan2(gy, gx)

                if magnitude > 10 {
                    gradientMagnitudes.append(magnitude)
                    gradientAngles.append(angle)
                }
            }
        }

        guard gradientMagnitudes.count >= 10 else { return nil }

        let dominantAngle = findDominantAngle(angles: gradientAngles, magnitudes: gradientMagnitudes)
        let blurAngle = dominantAngle + .pi / 2

        let blurLength = measureBlurLength(
            baseAddress: baseAddress,
            bytesPerRow: bytesPerRow,
            width: width,
            height: height,
            center: roi,
            direction: blurAngle,
            maxLength: Float(roiSize)
        )

        guard blurLength > 2 else { return nil }

        let angleVariance = computeAngleVariance(angles: gradientAngles, dominantAngle: dominantAngle)
        let confidence = max(0.0, min(1.0, 1.0 - Double(angleVariance) / (.pi / 4)))

        return BlurAnalysisResult(
            streakLengthPixels: CGFloat(blurLength),
            streakAngleRadians: Double(blurAngle),
            confidence: confidence
        )
    }

    public static func speedFromBlur(
        _ blur: BlurAnalysisResult,
        exposureTime: Double,
        calibration: CalibrationSnapshot
    ) -> Double? {
        guard exposureTime > 0, calibration.pixelsPerMetre > 0, blur.streakLengthPixels > 0 else {
            return nil
        }

        let blurLengthMetres = Double(blur.streakLengthPixels) / calibration.pixelsPerMetre
        let speedMs = blurLengthMetres / exposureTime
        return speedMs * GolfConstants.Speed.metersPerSecondToMph
    }

    public static func directionAgreement(
        blurAngleRadians: Double,
        motionAngleRadians: Double
    ) -> Double {
        let angleDiff = abs(blurAngleRadians - motionAngleRadians)
        let normalised = min(angleDiff, 2 * .pi - angleDiff)
        return max(0, 1.0 - normalised / (.pi / 2))
    }

    private static func findDominantAngle(angles: [Float], magnitudes: [Float]) -> Float {
        let numBins = 36
        var histogram = [Float](repeating: 0, count: numBins)

        for i in 0..<angles.count {
            var angle = angles[i]
            if angle < 0 { angle += .pi }
            let bin = Int(angle / .pi * Float(numBins)) % numBins
            histogram[bin] += magnitudes[i]
        }

        var maxBin = 0
        var maxVal: Float = 0
        for i in 0..<numBins {
            if histogram[i] > maxVal {
                maxVal = histogram[i]
                maxBin = i
            }
        }

        let prevBin = (maxBin - 1 + numBins) % numBins
        let nextBin = (maxBin + 1) % numBins
        let total = histogram[prevBin] + histogram[maxBin] + histogram[nextBin]
        guard total > 0 else { return 0 }

        let refinedBin = (Float(prevBin) * histogram[prevBin] +
                          Float(maxBin) * histogram[maxBin] +
                          Float(nextBin) * histogram[nextBin]) / total

        return refinedBin / Float(numBins) * .pi
    }

    private static func measureBlurLength(
        baseAddress: UnsafeMutableRawPointer,
        bytesPerRow: Int,
        width: Int,
        height: Int,
        center: CGPoint,
        direction: Float,
        maxLength: Float
    ) -> Float {
        let dx = cos(direction)
        let dy = sin(direction)

        var intensities: [Float] = []
        let steps = Int(maxLength)

        for i in (-steps/2)..<(steps/2) {
            let sampleX = Int(Float(center.x) + Float(i) * dx)
            let sampleY = Int(Float(center.y) + Float(i) * dy)

            guard sampleX >= 0, sampleX < width, sampleY >= 0, sampleY < height else {
                intensities.append(0)
                continue
            }

            let offset = sampleY * bytesPerRow + sampleX * 4 + 1
            let intensity = Float(baseAddress.load(fromByteOffset: offset, as: UInt8.self))
            intensities.append(intensity)
        }

        guard intensities.count >= 4 else { return 0 }

        let mean = intensities.reduce(0, +) / Float(intensities.count)
        let variance = intensities.map { ($0 - mean) * ($0 - mean) }.reduce(0, +) / Float(intensities.count)
        let stddev = sqrt(variance)
        let threshold = mean - stddev * 0.5

        var firstAbove: Int?
        var lastAbove: Int?

        for i in 0..<intensities.count {
            if intensities[i] > threshold {
                if firstAbove == nil { firstAbove = i }
                lastAbove = i
            }
        }

        var length: Float = 0
        if let first = firstAbove, let last = lastAbove {
            length = Float(last - first)
        }

        return length
    }

    private static func computeAngleVariance(angles: [Float], dominantAngle: Float) -> Float {
        guard !angles.isEmpty else { return .pi }

        var sumCos: Float = 0
        var sumSin: Float = 0

        for angle in angles {
            let diff = angle - dominantAngle
            sumCos += cos(diff)
            sumSin += sin(diff)
        }

        let n = Float(angles.count)
        let meanCos = sumCos / n
        let meanSin = sumSin / n
        let R = sqrt(meanCos * meanCos + meanSin * meanSin)

        return 1.0 - R
    }
}
