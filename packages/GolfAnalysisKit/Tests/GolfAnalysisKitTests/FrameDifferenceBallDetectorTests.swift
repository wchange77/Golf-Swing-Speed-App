import XCTest
import CoreVideo
@testable import GolfAnalysisKit

final class FrameDifferenceBallDetectorTests: XCTestCase {

    private func makePixelBuffer(width: Int, height: Int, fill: UInt8 = 0) -> CVPixelBuffer {
        var buffer: CVPixelBuffer?
        CVPixelBufferCreate(
            kCFAllocatorDefault,
            width, height,
            kCVPixelFormatType_32BGRA,
            nil,
            &buffer
        )
        let pb = buffer!
        CVPixelBufferLockBaseAddress(pb, [])
        let base = CVPixelBufferGetBaseAddress(pb)!
        let bytesPerRow = CVPixelBufferGetBytesPerRow(pb)
        for y in 0..<height {
            let row = base.advanced(by: y * bytesPerRow)
            for x in 0..<width {
                let offset = x * 4
                row.storeBytes(of: fill, toByteOffset: offset, as: UInt8.self)     // B
                row.storeBytes(of: fill, toByteOffset: offset + 1, as: UInt8.self) // G
                row.storeBytes(of: fill, toByteOffset: offset + 2, as: UInt8.self) // R
                row.storeBytes(of: 255, toByteOffset: offset + 3, as: UInt8.self)  // A
            }
        }
        CVPixelBufferUnlockBaseAddress(pb, [])
        return pb
    }

    private func drawCircle(in buffer: CVPixelBuffer, cx: Int, cy: Int, radius: Int, color: UInt8) {
        CVPixelBufferLockBaseAddress(buffer, [])
        let base = CVPixelBufferGetBaseAddress(buffer)!
        let bytesPerRow = CVPixelBufferGetBytesPerRow(buffer)
        let width = CVPixelBufferGetWidth(buffer)
        let height = CVPixelBufferGetHeight(buffer)

        for y in max(0, cy - radius)...min(height - 1, cy + radius) {
            for x in max(0, cx - radius)...min(width - 1, cx + radius) {
                let dx = x - cx
                let dy = y - cy
                if dx * dx + dy * dy <= radius * radius {
                    let row = base.advanced(by: y * bytesPerRow)
                    let offset = x * 4
                    row.storeBytes(of: color, toByteOffset: offset, as: UInt8.self)
                    row.storeBytes(of: color, toByteOffset: offset + 1, as: UInt8.self)
                    row.storeBytes(of: color, toByteOffset: offset + 2, as: UInt8.self)
                }
            }
        }
        CVPixelBufferUnlockBaseAddress(buffer, [])
    }

    func testNoDetectionOnFirstFrame() async {
        let detector = FrameDifferenceBallDetector()
        let frame = makePixelBuffer(width: 200, height: 200)
        let results = await detector.detect(in: frame)
        XCTAssertTrue(results.isEmpty, "First frame should return no detections")
    }

    func testNoDetectionOnIdenticalFrames() async {
        let detector = FrameDifferenceBallDetector()
        let frame1 = makePixelBuffer(width: 200, height: 200)
        let frame2 = makePixelBuffer(width: 200, height: 200)
        _ = await detector.detect(in: frame1)
        let results = await detector.detect(in: frame2)
        XCTAssertTrue(results.isEmpty, "Identical frames should produce no detections")
    }

    func testDetectsMovingBall() async {
        let detector = FrameDifferenceBallDetector(config: .init(
            diffThreshold: 20,
            minBlobArea: 5,
            maxBlobArea: 500,
            minCircularity: 0.3
        ))

        let frame1 = makePixelBuffer(width: 200, height: 200, fill: 30)
        drawCircle(in: frame1, cx: 50, cy: 100, radius: 5, color: 200)

        let frame2 = makePixelBuffer(width: 200, height: 200, fill: 30)
        drawCircle(in: frame2, cx: 70, cy: 100, radius: 5, color: 200)

        _ = await detector.detect(in: frame1)
        let results = await detector.detect(in: frame2)

        XCTAssertFalse(results.isEmpty, "Should detect the moved ball")
        if let best = results.first {
            XCTAssertEqual(best.source, .frameDifference)
            XCTAssertGreaterThan(best.confidence, 0)
        }
    }

    func testResetClearsPreviousFrame() async {
        let detector = FrameDifferenceBallDetector()
        let frame1 = makePixelBuffer(width: 100, height: 100)
        _ = await detector.detect(in: frame1)
        await detector.reset()
        let frame2 = makePixelBuffer(width: 100, height: 100, fill: 128)
        let results = await detector.detect(in: frame2)
        XCTAssertTrue(results.isEmpty, "After reset, first frame should return empty")
    }

    func testBallDetectionProtocolConformance() async {
        let detector: any BallDetector = FrameDifferenceBallDetector()
        let frame = makePixelBuffer(width: 100, height: 100)
        let results = await detector.detect(in: frame)
        XCTAssertNotNil(results)
    }
}
