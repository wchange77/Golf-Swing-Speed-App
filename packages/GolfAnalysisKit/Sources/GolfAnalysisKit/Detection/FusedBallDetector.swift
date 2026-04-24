import Foundation
import CoreVideo
import CoreGraphics

public actor FusedBallDetector: BallDetector {

    public struct Config: Sendable {
        public var yoloConfidenceThreshold: Double = 0.5
        public var frameDiffConfidenceScale: Double = 0.7
        public var matchDistanceThreshold: CGFloat = 30.0

        public init(
            yoloConfidenceThreshold: Double = 0.5,
            frameDiffConfidenceScale: Double = 0.7,
            matchDistanceThreshold: CGFloat = 30.0
        ) {
            self.yoloConfidenceThreshold = yoloConfidenceThreshold
            self.frameDiffConfidenceScale = frameDiffConfidenceScale
            self.matchDistanceThreshold = matchDistanceThreshold
        }
    }

    private let yoloDetector: (any BallDetector)?
    private let frameDiffDetector: FrameDifferenceBallDetector
    private let config: Config

    public init(
        yoloDetector: (any BallDetector)? = nil,
        frameDiffDetector: FrameDifferenceBallDetector = FrameDifferenceBallDetector(),
        config: Config = Config()
    ) {
        self.yoloDetector = yoloDetector
        self.frameDiffDetector = frameDiffDetector
        self.config = config
    }

    public func detect(in pixelBuffer: CVPixelBuffer) async -> [BallDetection] {
        async let yoloResults = yoloDetector?.detect(in: pixelBuffer) ?? []
        async let diffResults = frameDiffDetector.detect(in: pixelBuffer)

        let yolo = await yoloResults
        let diff = await diffResults

        let confidentYolo = yolo.filter { $0.confidence >= config.yoloConfidenceThreshold }

        if !confidentYolo.isEmpty && diff.isEmpty {
            return confidentYolo
        }

        if confidentYolo.isEmpty && !diff.isEmpty {
            return diff.map { detection in
                var d = detection
                d.confidence *= config.frameDiffConfidenceScale
                return d
            }
        }

        if confidentYolo.isEmpty && diff.isEmpty {
            return yolo
        }

        return fuseDetections(yolo: confidentYolo, diff: diff)
    }

    private func fuseDetections(yolo: [BallDetection], diff: [BallDetection]) -> [BallDetection] {
        var result: [BallDetection] = []
        var usedDiff = Set<Int>()

        for yoloDet in yolo {
            var best: (index: Int, distance: CGFloat)?
            for (i, diffDet) in diff.enumerated() where !usedDiff.contains(i) {
                let dx = yoloDet.center.x - diffDet.center.x
                let dy = yoloDet.center.y - diffDet.center.y
                let dist = sqrt(dx * dx + dy * dy)
                if dist < config.matchDistanceThreshold {
                    if best == nil || dist < best!.distance {
                        best = (i, dist)
                    }
                }
            }

            if let match = best {
                usedDiff.insert(match.index)
                var fused = yoloDet
                fused.confidence = min(1.0, yoloDet.confidence * 1.2)
                fused.source = .fused
                result.append(fused)
            } else {
                result.append(yoloDet)
            }
        }

        for (i, diffDet) in diff.enumerated() where !usedDiff.contains(i) {
            var d = diffDet
            d.confidence *= config.frameDiffConfidenceScale
            result.append(d)
        }

        return result.sorted { $0.confidence > $1.confidence }
    }
}
