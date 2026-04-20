import Foundation
import CoreImage
import Accelerate

/// Analyses motion blur in video frames to extract supplementary speed information.
///
/// Motion blur is encoded velocity: blur_length (pixels) = speed (m/s) × exposure_time (s) × pixels_per_metre
/// Therefore: speed = blur_length / (exposure_time × pixels_per_metre)
///
/// This provides an independent speed estimate that can be fused with frame-to-frame tracking
/// for improved accuracy, especially near impact where tracking is least reliable.
struct MotionBlurAnalyser {

    // MARK: - Blur Streak Detection

    /// Detect the motion blur streak length and direction in a region of interest.
    ///
    /// Uses gradient analysis to find the dominant motion direction and blur extent.
    /// The blur streak appears as an elongated region with consistent gradient direction.
    ///
    /// - Parameters:
    ///   - pixelBuffer: Frame to analyse
    ///   - roi: Region of interest (in pixel coordinates) where the club head is expected
    ///   - roiSize: Size of the analysis window around the ROI center
    /// - Returns: Blur analysis result with streak length, direction, and confidence
    static func detectBlurStreak(
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

        // Define ROI bounds
        let halfSize = roiSize / 2
        let minX = max(0, Int(roi.x) - halfSize)
        let maxX = min(width - 1, Int(roi.x) + halfSize)
        let minY = max(0, Int(roi.y) - halfSize)
        let maxY = min(height - 1, Int(roi.y) + halfSize)

        guard maxX > minX + 4, maxY > minY + 4 else { return nil }

        // Extract grayscale values and compute gradients
        var gradientMagnitudes: [Float] = []
        var gradientAngles: [Float] = []

        for y in (minY + 1)..<maxY {
            let rowPtr = baseAddress.advanced(by: y * bytesPerRow)
            let prevRowPtr = baseAddress.advanced(by: (y - 1) * bytesPerRow)
            let nextRowPtr = baseAddress.advanced(by: (y + 1) * bytesPerRow)

            for x in (minX + 1)..<maxX {
                // Sobel-like gradient using green channel (index 1 in BGRA)
                let offset = x * 4 + 1

                let left = Float(rowPtr.load(fromByteOffset: offset - 4, as: UInt8.self))
                let right = Float(rowPtr.load(fromByteOffset: offset + 4, as: UInt8.self))
                let above = Float(prevRowPtr.load(fromByteOffset: offset, as: UInt8.self))
                let below = Float(nextRowPtr.load(fromByteOffset: offset, as: UInt8.self))

                let gx = right - left
                let gy = below - above
                let magnitude = sqrt(gx * gx + gy * gy)
                let angle = atan2(gy, gx) // Radians

                if magnitude > 10 { // Ignore very weak gradients
                    gradientMagnitudes.append(magnitude)
                    gradientAngles.append(angle)
                }
            }
        }

        guard gradientMagnitudes.count >= 10 else { return nil }

        // Find dominant gradient direction using histogram
        let dominantAngle = findDominantAngle(angles: gradientAngles, magnitudes: gradientMagnitudes)

        // The blur direction is perpendicular to the dominant gradient direction
        let blurAngle = dominantAngle + .pi / 2

        // Estimate blur length by profiling intensity along the blur direction
        let blurLength = measureBlurLength(
            baseAddress: baseAddress,
            bytesPerRow: bytesPerRow,
            width: width,
            height: height,
            center: roi,
            direction: blurAngle,
            maxLength: Float(roiSize)
        )

        guard blurLength > 2 else { return nil } // Less than 2 pixels = no meaningful blur

        // Confidence based on gradient consistency
        let angleVariance = computeAngleVariance(angles: gradientAngles, dominantAngle: dominantAngle)
        let confidence = max(0.0, min(1.0, 1.0 - Double(angleVariance) / (.pi / 4)))

        return BlurAnalysisResult(
            streakLengthPixels: CGFloat(blurLength),
            streakAngleRadians: Double(blurAngle),
            confidence: confidence
        )
    }

    // MARK: - Speed from Blur

    /// Calculate speed from a blur analysis result.
    ///
    /// - Parameters:
    ///   - blur: Blur analysis result
    ///   - exposureTime: Camera exposure time in seconds (from CMSampleBuffer metadata)
    ///   - calibration: Calibration data with pixels-per-metre
    /// - Returns: Estimated speed in mph
    static func speedFromBlur(
        _ blur: BlurAnalysisResult,
        exposureTime: Double,
        calibration: CalibrationSnapshot
    ) -> Double? {
        guard exposureTime > 0, calibration.pixelsPerMetre > 0, blur.streakLengthPixels > 0 else {
            return nil
        }

        let blurLengthMetres = Double(blur.streakLengthPixels) / calibration.pixelsPerMetre
        let speedMs = blurLengthMetres / exposureTime
        return speedMs * AppConstants.Speed.metersPerSecondToMph
    }

    // MARK: - Blur Direction Validation

    /// Check if the blur direction is consistent with the expected club head motion direction.
    /// Returns a 0-1 score where 1.0 = perfect agreement.
    static func directionAgreement(
        blurAngleRadians: Double,
        motionAngleRadians: Double
    ) -> Double {
        let angleDiff = abs(blurAngleRadians - motionAngleRadians)
        let normalised = min(angleDiff, 2 * .pi - angleDiff) // Handle wrap-around
        return max(0, 1.0 - normalised / (.pi / 2))
    }

    // MARK: - Helpers

    /// Find the dominant gradient direction using a weighted histogram.
    private static func findDominantAngle(angles: [Float], magnitudes: [Float]) -> Float {
        // Bin angles into 36 bins (10° each)
        let numBins = 36
        var histogram = [Float](repeating: 0, count: numBins)

        for i in 0..<angles.count {
            var angle = angles[i]
            if angle < 0 { angle += .pi } // Map to 0-π (gradients are bidirectional)
            let bin = Int(angle / .pi * Float(numBins)) % numBins
            histogram[bin] += magnitudes[i]
        }

        // Find peak bin
        var maxBin = 0
        var maxVal: Float = 0
        for i in 0..<numBins {
            if histogram[i] > maxVal {
                maxVal = histogram[i]
                maxBin = i
            }
        }

        // Refine with weighted average of peak and neighbours
        let prevBin = (maxBin - 1 + numBins) % numBins
        let nextBin = (maxBin + 1) % numBins
        let total = histogram[prevBin] + histogram[maxBin] + histogram[nextBin]
        guard total > 0 else { return 0 }

        let refinedBin = (Float(prevBin) * histogram[prevBin] +
                          Float(maxBin) * histogram[maxBin] +
                          Float(nextBin) * histogram[nextBin]) / total

        return refinedBin / Float(numBins) * .pi
    }

    /// Measure blur streak length by profiling intensity along a direction.
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
        var length: Float = 0

        // Sample intensity along the blur direction
        var intensities: [Float] = []
        let steps = Int(maxLength)

        for i in (-steps/2)..<(steps/2) {
            let sampleX = Int(Float(center.x) + Float(i) * dx)
            let sampleY = Int(Float(center.y) + Float(i) * dy)

            guard sampleX >= 0, sampleX < width, sampleY >= 0, sampleY < height else {
                intensities.append(0)
                continue
            }

            let offset = sampleY * bytesPerRow + sampleX * 4 + 1 // Green channel
            let intensity = Float(baseAddress.load(fromByteOffset: offset, as: UInt8.self))
            intensities.append(intensity)
        }

        guard intensities.count >= 4 else { return 0 }

        // Find the extent of the blur by looking for the region where
        // intensity is above a threshold (mean - stddev)
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

        if let first = firstAbove, let last = lastAbove {
            length = Float(last - first)
        }

        return length
    }

    /// Compute the circular variance of gradient angles around the dominant direction.
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
        let R = sqrt(meanCos * meanCos + meanSin * meanSin) // Mean resultant length

        // Circular variance = 1 - R (0 = no variance, 1 = maximum variance)
        return 1.0 - R
    }
}

// MARK: - Blur Analysis Result

struct BlurAnalysisResult {
    /// Length of the motion blur streak in pixels
    let streakLengthPixels: CGFloat

    /// Direction of the blur streak in radians
    let streakAngleRadians: Double

    /// Confidence in the blur detection (0-1)
    let confidence: Double
}
