import Foundation
import Vision
import CoreImage

public actor OpticalFlowTracker {

    public struct Config: Sendable {
        public var roiSize: CGFloat = 40
        public var minFlowMagnitude: Float = 1.0
        public var maxFlowMagnitude: Float = 200.0
        public var computationAccuracy: VNGenerateOpticalFlowRequest.ComputationAccuracy = .high
        public var maxFramesWithoutFlow: Int = 5

        public init(
            roiSize: CGFloat = 40,
            minFlowMagnitude: Float = 1.0,
            maxFlowMagnitude: Float = 200.0,
            computationAccuracy: VNGenerateOpticalFlowRequest.ComputationAccuracy = .high,
            maxFramesWithoutFlow: Int = 5
        ) {
            self.roiSize = roiSize
            self.minFlowMagnitude = minFlowMagnitude
            self.maxFlowMagnitude = maxFlowMagnitude
            self.computationAccuracy = computationAccuracy
            self.maxFramesWithoutFlow = maxFramesWithoutFlow
        }
    }

    private var config: Config
    private var currentPosition: CGPoint?
    private var previousPixelBuffer: CVPixelBuffer?
    private var framesWithoutFlow: Int = 0

    public init(config: Config = Config()) {
        self.config = config
    }

    public func setInitialPosition(_ position: CGPoint) {
        currentPosition = position
        framesWithoutFlow = 0
    }

    public func track(in pixelBuffer: CVPixelBuffer, roiCenter: CGPoint? = nil) async -> CGPoint? {
        let trackPoint = roiCenter ?? currentPosition
        guard let center = trackPoint else { return nil }

        defer { previousPixelBuffer = pixelBuffer }

        guard let prevBuffer = previousPixelBuffer else {
            currentPosition = center
            return center
        }

        let flowResult = await computeOpticalFlow(from: prevBuffer, to: pixelBuffer)

        guard let flowBuffer = flowResult else {
            framesWithoutFlow += 1
            if framesWithoutFlow > config.maxFramesWithoutFlow { return nil }
            return currentPosition
        }

        let displacement = sampleFlowField(
            flowBuffer: flowBuffer,
            at: center,
            roiSize: config.roiSize,
            imageWidth: CVPixelBufferGetWidth(pixelBuffer),
            imageHeight: CVPixelBufferGetHeight(pixelBuffer)
        )

        guard let displacement, isValidDisplacement(displacement) else {
            framesWithoutFlow += 1
            if framesWithoutFlow > config.maxFramesWithoutFlow { return nil }
            return currentPosition
        }

        let newPosition = CGPoint(
            x: center.x + CGFloat(displacement.x),
            y: center.y + CGFloat(displacement.y)
        )
        currentPosition = newPosition
        framesWithoutFlow = 0
        return newPosition
    }

    public var isTrackingActive: Bool {
        currentPosition != nil && framesWithoutFlow <= config.maxFramesWithoutFlow
    }

    public func reset() {
        currentPosition = nil
        previousPixelBuffer = nil
        framesWithoutFlow = 0
    }

    private func computeOpticalFlow(
        from previousBuffer: CVPixelBuffer,
        to currentBuffer: CVPixelBuffer
    ) async -> CVPixelBuffer? {
        let request = VNGenerateOpticalFlowRequest(targetedCVPixelBuffer: currentBuffer)
        request.computationAccuracy = config.computationAccuracy
        let handler = VNImageRequestHandler(cvPixelBuffer: previousBuffer, options: [:])
        do { try handler.perform([request]) } catch { return nil }
        guard let observation = request.results?.first as? VNPixelBufferObservation else { return nil }
        return observation.pixelBuffer
    }

    private func sampleFlowField(
        flowBuffer: CVPixelBuffer,
        at center: CGPoint,
        roiSize: CGFloat,
        imageWidth: Int,
        imageHeight: Int
    ) -> SIMD2<Float>? {
        CVPixelBufferLockBaseAddress(flowBuffer, .readOnly)
        defer { CVPixelBufferUnlockBaseAddress(flowBuffer, .readOnly) }

        let flowWidth = CVPixelBufferGetWidth(flowBuffer)
        let flowHeight = CVPixelBufferGetHeight(flowBuffer)
        let bytesPerRow = CVPixelBufferGetBytesPerRow(flowBuffer)
        guard let baseAddress = CVPixelBufferGetBaseAddress(flowBuffer) else { return nil }

        let scaleX = Float(flowWidth) / Float(imageWidth)
        let scaleY = Float(flowHeight) / Float(imageHeight)
        let flowCenterX = Int(Float(center.x) * scaleX)
        let flowCenterY = Int(Float(center.y) * scaleY)
        let flowRoiHalf = Int(Float(roiSize) * scaleX / 2)

        var flowVectors: [SIMD2<Float>] = []
        let minX = max(0, flowCenterX - flowRoiHalf)
        let maxX = min(flowWidth - 1, flowCenterX + flowRoiHalf)
        let minY = max(0, flowCenterY - flowRoiHalf)
        let maxY = min(flowHeight - 1, flowCenterY + flowRoiHalf)
        let pixelFormat = CVPixelBufferGetPixelFormatType(flowBuffer)

        for y in stride(from: minY, through: maxY, by: 2) {
            let rowPtr = baseAddress.advanced(by: y * bytesPerRow)
            for x in stride(from: minX, through: maxX, by: 2) {
                if pixelFormat == kCVPixelFormatType_TwoComponent32Float {
                    let offset = x * 8
                    let dx = rowPtr.loadUnaligned(fromByteOffset: offset, as: Float.self)
                    let dy = rowPtr.loadUnaligned(fromByteOffset: offset + 4, as: Float.self)
                    flowVectors.append(SIMD2<Float>(dx / scaleX, dy / scaleY))
                } else if pixelFormat == kCVPixelFormatType_TwoComponent16Half {
                    let offset = x * 4
                    let raw0 = rowPtr.loadUnaligned(fromByteOffset: offset, as: UInt16.self)
                    let raw1 = rowPtr.loadUnaligned(fromByteOffset: offset + 2, as: UInt16.self)
                    let dx = Self.float16ToFloat32(raw0)
                    let dy = Self.float16ToFloat32(raw1)
                    flowVectors.append(SIMD2<Float>(dx / scaleX, dy / scaleY))
                }
            }
        }

        guard !flowVectors.isEmpty else { return nil }
        return medianFlow(flowVectors)
    }

    private func medianFlow(_ vectors: [SIMD2<Float>]) -> SIMD2<Float> {
        let sortedX = vectors.map(\.x).sorted()
        let sortedY = vectors.map(\.y).sorted()
        let mid = vectors.count / 2
        return SIMD2<Float>(sortedX[mid], sortedY[mid])
    }

    private func isValidDisplacement(_ displacement: SIMD2<Float>) -> Bool {
        let magnitude = simd_length(displacement)
        return magnitude >= config.minFlowMagnitude && magnitude <= config.maxFlowMagnitude
    }

    private static func float16ToFloat32(_ h: UInt16) -> Float {
        let sign = UInt32(h >> 15) << 31
        let exp = UInt32((h >> 10) & 0x1F)
        let frac = UInt32(h & 0x3FF)
        let bits: UInt32
        if exp == 0 {
            bits = sign
        } else if exp == 31 {
            bits = sign | 0x7F800000 | (frac << 13)
        } else {
            bits = sign | ((exp + 112) << 23) | (frac << 13)
        }
        return Float(bitPattern: bits)
    }
}
