import Foundation
import CoreVideo
import CoreGraphics

public actor FrameDifferenceBallDetector: BallDetector {

    public struct Config: Sendable {
        public var diffThreshold: UInt8 = 25
        public var minBlobArea: Int = 9
        public var maxBlobArea: Int = 400
        public var minCircularity: Float = 0.5
        public var maxCandidates: Int = 5
        public var edgeMargin: Int = 5

        public init(
            diffThreshold: UInt8 = 25,
            minBlobArea: Int = 9,
            maxBlobArea: Int = 400,
            minCircularity: Float = 0.5,
            maxCandidates: Int = 5,
            edgeMargin: Int = 5
        ) {
            self.diffThreshold = diffThreshold
            self.minBlobArea = minBlobArea
            self.maxBlobArea = maxBlobArea
            self.minCircularity = minCircularity
            self.maxCandidates = maxCandidates
            self.edgeMargin = edgeMargin
        }
    }

    private var config: Config
    private var previousGray: [UInt8]?
    private var previousWidth: Int = 0
    private var previousHeight: Int = 0

    public init(config: Config = Config()) {
        self.config = config
    }

    public func detect(in pixelBuffer: CVPixelBuffer) async -> [BallDetection] {
        let width = CVPixelBufferGetWidth(pixelBuffer)
        let height = CVPixelBufferGetHeight(pixelBuffer)

        let currentGray = extractGrayscale(from: pixelBuffer, width: width, height: height)

        guard let prevGray = previousGray,
              previousWidth == width,
              previousHeight == height else {
            previousGray = currentGray
            previousWidth = width
            previousHeight = height
            return []
        }

        previousGray = currentGray
        previousWidth = width
        previousHeight = height

        var diffImage = [UInt8](repeating: 0, count: width * height)
        for i in 0..<(width * height) {
            let diff = abs(Int(currentGray[i]) - Int(prevGray[i]))
            diffImage[i] = diff >= Int(config.diffThreshold) ? 255 : 0
        }

        morphologicalOpen(&diffImage, width: width, height: height)

        let blobs = findBlobs(in: diffImage, width: width, height: height)

        let filtered = blobs.filter { blob in
            blob.area >= config.minBlobArea
                && blob.area <= config.maxBlobArea
                && blob.circularity >= config.minCircularity
                && blob.centerX > config.edgeMargin
                && blob.centerX < width - config.edgeMargin
                && blob.centerY > config.edgeMargin
                && blob.centerY < height - config.edgeMargin
        }

        let sorted = filtered.sorted { $0.area > $1.area }
        let top = sorted.prefix(config.maxCandidates)

        return top.map { blob in
            let radius = sqrt(Float(blob.area) / .pi)
            let cx = CGFloat(blob.centerX)
            let cy = CGFloat(blob.centerY)
            let r = CGFloat(radius)
            let w = CGFloat(width)
            let h = CGFloat(height)

            let confidence = Double(blob.circularity) * 0.7

            return BallDetection(
                center: CGPoint(x: cx, y: cy),
                boundingBox: CGRect(
                    x: (cx - r) / w,
                    y: 1.0 - (cy + r) / h,
                    width: (2 * r) / w,
                    height: (2 * r) / h
                ),
                confidence: confidence,
                radius: r,
                source: .frameDifference
            )
        }
    }

    public func reset() {
        previousGray = nil
    }

    // MARK: - Grayscale extraction

    private func extractGrayscale(from pixelBuffer: CVPixelBuffer, width: Int, height: Int) -> [UInt8] {
        CVPixelBufferLockBaseAddress(pixelBuffer, .readOnly)
        defer { CVPixelBufferUnlockBaseAddress(pixelBuffer, .readOnly) }

        let bytesPerRow = CVPixelBufferGetBytesPerRow(pixelBuffer)
        guard let baseAddress = CVPixelBufferGetBaseAddress(pixelBuffer) else {
            return [UInt8](repeating: 0, count: width * height)
        }

        var gray = [UInt8](repeating: 0, count: width * height)
        let pixelFormat = CVPixelBufferGetPixelFormatType(pixelBuffer)

        for y in 0..<height {
            let rowPtr = baseAddress.advanced(by: y * bytesPerRow)
            for x in 0..<width {
                let idx = y * width + x
                if pixelFormat == kCVPixelFormatType_32BGRA {
                    let offset = x * 4
                    let b = UInt16(rowPtr.load(fromByteOffset: offset, as: UInt8.self))
                    let g = UInt16(rowPtr.load(fromByteOffset: offset + 1, as: UInt8.self))
                    let r = UInt16(rowPtr.load(fromByteOffset: offset + 2, as: UInt8.self))
                    gray[idx] = UInt8((r * 77 + g * 150 + b * 29) >> 8)
                } else if pixelFormat == kCVPixelFormatType_420YpCbCr8BiPlanarFullRange
                            || pixelFormat == kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange {
                    gray[idx] = rowPtr.load(fromByteOffset: x, as: UInt8.self)
                } else {
                    let offset = x * 4
                    gray[idx] = rowPtr.load(fromByteOffset: offset + 1, as: UInt8.self)
                }
            }
        }
        return gray
    }

    // MARK: - Morphological open (erode then dilate)

    private func morphologicalOpen(_ image: inout [UInt8], width: Int, height: Int) {
        var eroded = [UInt8](repeating: 0, count: width * height)
        for y in 1..<(height - 1) {
            for x in 1..<(width - 1) {
                let idx = y * width + x
                let allSet = image[idx] == 255
                    && image[idx - 1] == 255
                    && image[idx + 1] == 255
                    && image[idx - width] == 255
                    && image[idx + width] == 255
                eroded[idx] = allSet ? 255 : 0
            }
        }

        for y in 1..<(height - 1) {
            for x in 1..<(width - 1) {
                let idx = y * width + x
                let anySet = eroded[idx] == 255
                    || eroded[idx - 1] == 255
                    || eroded[idx + 1] == 255
                    || eroded[idx - width] == 255
                    || eroded[idx + width] == 255
                image[idx] = anySet ? 255 : 0
            }
        }
    }

    // MARK: - Connected component analysis

    private struct Blob {
        var area: Int
        var centerX: Int
        var centerY: Int
        var minX: Int
        var maxX: Int
        var minY: Int
        var maxY: Int
        var circularity: Float
    }

    private func findBlobs(in image: [UInt8], width: Int, height: Int) -> [Blob] {
        var labels = [Int](repeating: 0, count: width * height)
        var currentLabel = 0
        var blobStats: [Int: (sumX: Int, sumY: Int, count: Int, minX: Int, maxX: Int, minY: Int, maxY: Int)] = [:]

        for y in 0..<height {
            for x in 0..<width {
                let idx = y * width + x
                guard image[idx] == 255, labels[idx] == 0 else { continue }

                currentLabel += 1
                let label = currentLabel
                var sumX = 0, sumY = 0, count = 0
                var bMinX = x, bMaxX = x, bMinY = y, bMaxY = y

                var stack = [idx]
                labels[idx] = label

                while let current = stack.popLast() {
                    let cy = current / width
                    let cx = current % width
                    sumX += cx
                    sumY += cy
                    count += 1
                    bMinX = min(bMinX, cx)
                    bMaxX = max(bMaxX, cx)
                    bMinY = min(bMinY, cy)
                    bMaxY = max(bMaxY, cy)

                    if count > config.maxBlobArea * 2 { break }

                    let neighbors = [
                        (cx - 1, cy), (cx + 1, cy),
                        (cx, cy - 1), (cx, cy + 1)
                    ]
                    for (nx, ny) in neighbors {
                        guard nx >= 0, nx < width, ny >= 0, ny < height else { continue }
                        let nIdx = ny * width + nx
                        if image[nIdx] == 255 && labels[nIdx] == 0 {
                            labels[nIdx] = label
                            stack.append(nIdx)
                        }
                    }
                }

                blobStats[label] = (sumX, sumY, count, bMinX, bMaxX, bMinY, bMaxY)
            }
        }

        return blobStats.values.compactMap { stats in
            guard stats.count > 0 else { return nil }
            let cx = stats.sumX / stats.count
            let cy = stats.sumY / stats.count
            let bboxW = Float(stats.maxX - stats.minX + 1)
            let bboxH = Float(stats.maxY - stats.minY + 1)
            let bboxDiag = max(bboxW, bboxH)
            let enclosingCircleArea = Float.pi * (bboxDiag / 2) * (bboxDiag / 2)
            let circularity = enclosingCircleArea > 0 ? Float(stats.count) / enclosingCircleArea : 0

            return Blob(
                area: stats.count,
                centerX: cx,
                centerY: cy,
                minX: stats.minX,
                maxX: stats.maxX,
                minY: stats.minY,
                maxY: stats.maxY,
                circularity: circularity
            )
        }
    }
}

