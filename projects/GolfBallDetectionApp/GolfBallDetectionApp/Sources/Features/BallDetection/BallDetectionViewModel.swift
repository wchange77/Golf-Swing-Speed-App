import Foundation
import AVFoundation
import PhotosUI
import GolfAnalysisKit

@MainActor
final class BallDetectionViewModel: ObservableObject {
    @Published private(set) var records: [BallDetectionRecord] = []
    @Published private(set) var manifestSummary: String = "未加载数据集清单"
    @Published private(set) var isAnalyzing = false
    @Published private(set) var analysisProgress: Double = 0
    @Published private(set) var statusMessage: String = ""
    @Published var selectedVideoURL: URL?
    @Published var selectedClub: ClubType = .sevenIron
    @Published private(set) var prediction: TrajectoryPrediction?
    @Published private(set) var ballFlightMetrics: BallFlightMetrics?

    private let frameDiffDetector = FrameDifferenceBallDetector()
    private var yoloDetector: (any BallDetector)?
    private var fusedDetector: FusedBallDetector?
    private let sessionStore = SwingSessionStore()

    init() {
        refreshManifestSummary()
        setupDetectors()
    }

    private func setupDetectors() {
        fusedDetector = FusedBallDetector(
            yoloDetector: yoloDetector,
            frameDiffDetector: frameDiffDetector
        )
    }

    func analyzeVideo(url: URL) {
        guard !isAnalyzing else { return }
        isAnalyzing = true
        analysisProgress = 0
        records = []
        prediction = nil
        ballFlightMetrics = nil
        statusMessage = "正在加载视频..."
        selectedVideoURL = url

        Task {
            await runAnalysis(url: url)
            computeTrajectory()
            isAnalyzing = false
        }
    }

    private func computeTrajectory() {
        guard records.count >= 3 else {
            statusMessage += " | 检测点不足，无法计算弹道"
            return
        }

        let positions = records.map { record in
            TrackedPosition(
                frameTimestamp: record.frameTimestamp,
                position2D: CGPoint(x: record.centerX, y: record.centerY),
                confidence: record.confidence,
                source: .yoloDetection
            )
        }

        let calibration = CalibrationSnapshot(
            method: .manual,
            pixelsPerMetre: 200,
            impactZoneX: records.first.map { $0.centerX } ?? 0,
            impactZoneY: records.first.map { $0.centerY } ?? 0
        )

        let metrics = BallSpeedCalculator.calculateBallFlight(
            positions: positions,
            calibration: calibration
        )
        self.ballFlightMetrics = metrics

        if let metrics {
            let clubHeadSpeed = metrics.ballSpeedMph / BallSpeedCalculator.smashFactor(for: selectedClub)
            prediction = TrajectoryPredictor.predict(
                clubHeadSpeedMph: clubHeadSpeed,
                club: selectedClub
            )
            statusMessage += " | 弹道预测完成: \(String(format: "%.0f", prediction?.carryDistanceYards ?? 0)) 码"

            if let pred = prediction {
                let session = SwingSession.from(prediction: pred, club: selectedClub)
                Task { try? await sessionStore.save(session) }
            }
        }
    }

    private func runAnalysis(url: URL) async {
        let asset = AVURLAsset(url: url)
        guard let track = try? await asset.loadTracks(withMediaType: .video).first else {
            statusMessage = "无法加载视频轨道"
            return
        }

        let duration = try? await asset.load(.duration)
        let totalSeconds = duration.map { CMTimeGetSeconds($0) } ?? 0
        guard totalSeconds > 0 else {
            statusMessage = "视频时长为零"
            return
        }

        let nominalFrameRate = (try? await track.load(.nominalFrameRate)) ?? 240
        let totalFrames = Int(totalSeconds * Double(nominalFrameRate))
        guard totalFrames > 0 else {
            statusMessage = "无法计算帧数"
            return
        }

        statusMessage = "分析中... \(Int(nominalFrameRate))fps, \(totalFrames) 帧"

        let reader: AVAssetReader
        do {
            reader = try AVAssetReader(asset: asset)
        } catch {
            statusMessage = "无法创建 reader: \(error.localizedDescription)"
            return
        }

        let outputSettings: [String: Any] = [
            kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA
        ]
        let output = AVAssetReaderTrackOutput(track: track, outputSettings: outputSettings)
        output.alwaysCopiesSampleData = false
        reader.add(output)

        guard reader.startReading() else {
            statusMessage = "reader 启动失败"
            return
        }

        let detector = fusedDetector ?? FusedBallDetector(frameDiffDetector: frameDiffDetector)
        var frameIndex = 0
        var detectionCount = 0

        while reader.status == .reading {
            guard let sampleBuffer = output.copyNextSampleBuffer(),
                  let pixelBuffer = CMSampleBufferGetImageBuffer(sampleBuffer) else {
                continue
            }

            let detections = await detector.detect(in: pixelBuffer)

            if !detections.isEmpty {
                let best = detections[0]
                let timestamp = CMSampleBufferGetPresentationTimeStamp(sampleBuffer)
                let seconds = CMTimeGetSeconds(timestamp)

                let record = BallDetectionRecord(
                    confidence: best.confidence,
                    centerX: Double(best.center.x),
                    centerY: Double(best.center.y),
                    radius: Double(best.radius),
                    frameIndex: frameIndex,
                    frameTimestamp: seconds,
                    source: best.source.rawValue
                )
                records.append(record)
                detectionCount += 1
            }

            frameIndex += 1
            if frameIndex % 50 == 0 {
                analysisProgress = Double(frameIndex) / Double(totalFrames)
                statusMessage = "帧 \(frameIndex)/\(totalFrames) — 检测到 \(detectionCount) 次"
            }
        }

        analysisProgress = 1.0
        statusMessage = "完成: \(frameIndex) 帧, 检测到 \(detectionCount) 次球"
    }

    func refreshManifestSummary() {
        guard let manifest = BallDatasetBridge.loadManifest() else {
            manifestSummary = "未找到数据集清单"
            return
        }

        let ball = manifest.dataset?.key == "golf_ball_detection"
            ? manifest.dataset
            : manifest.datasets?.first(where: { $0.key == "golf_ball_detection" })
        if let ball {
            manifestSummary = "球数据集样本: \(ball.samples) (\(ball.format))"
        } else {
            manifestSummary = "清单已加载，但未找到 golf_ball_detection 条目"
        }
    }
}
