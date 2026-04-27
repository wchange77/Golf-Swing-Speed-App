import Foundation
import CoreML
import Vision
import CoreVideo
import GolfAnalysisKit

actor YOLOBallDetector: BallDetector {

    struct Config: Sendable {
        var modelName: String = "GolfBallDetector"
        var confidenceThreshold: Float = 0.3
        var targetLabels: Set<String> = ["golf_ball", "sports ball"]

        init(
            modelName: String = "GolfBallDetector",
            confidenceThreshold: Float = 0.3,
            targetLabels: Set<String> = ["golf_ball", "sports ball"]
        ) {
            self.modelName = modelName
            self.confidenceThreshold = confidenceThreshold
            self.targetLabels = targetLabels
        }
    }

    private let config: Config
    private var model: VNCoreMLModel?

    init(config: Config = Config()) {
        self.config = config
        self.model = Self.loadModel(config: config)
    }

    private static func loadModel(config: Config) -> VNCoreMLModel? {
        guard let url = Bundle.main.url(
            forResource: config.modelName,
            withExtension: "mlmodelc"
        ) else { return nil }

        guard let mlModel = try? MLModel(contentsOf: url) else { return nil }
        return try? VNCoreMLModel(for: mlModel)
    }

    var isModelLoaded: Bool { model != nil }

    func detect(in pixelBuffer: CVPixelBuffer) async -> [BallDetection] {
        guard let model else { return [] }

        let request = VNCoreMLRequest(model: model)
        request.imageCropAndScaleOption = .scaleFill

        let handler = VNImageRequestHandler(cvPixelBuffer: pixelBuffer, options: [:])
        do { try handler.perform([request]) } catch { return [] }

        guard let results = request.results as? [VNRecognizedObjectObservation] else {
            return []
        }

        let imageWidth = CGFloat(CVPixelBufferGetWidth(pixelBuffer))
        let imageHeight = CGFloat(CVPixelBufferGetHeight(pixelBuffer))

        return results.compactMap { observation in
            guard observation.confidence >= config.confidenceThreshold else { return nil }

            let hasTargetLabel = observation.labels.contains { label in
                config.targetLabels.contains(label.identifier)
            }
            guard hasTargetLabel else { return nil }

            let bbox = observation.boundingBox
            let center = CGPoint(
                x: bbox.midX * imageWidth,
                y: (1 - bbox.midY) * imageHeight
            )
            let radius = max(bbox.width * imageWidth, bbox.height * imageHeight) / 2

            return BallDetection(
                center: center,
                boundingBox: bbox,
                confidence: Double(observation.confidence),
                radius: radius,
                source: .yolo
            )
        }
    }
}
