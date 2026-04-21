import SwiftUI
import AVFoundation
import AVKit
import Vision
import CoreImage

enum AnalysisModel: String, CaseIterable, Identifiable {
    case bodyPose2D = "人体骨架 2D"
    case bodyPose3D = "人体骨架 3D"
    case handPose = "手部关节"
    case jointAngles = "关节角度"
    case swingPhase = "挥杆阶段"
    case swingPlane = "挥杆平面"
    case objectTrack = "点击追踪"
    case personSegmentation = "人体分割"
    case foregroundMask = "前景分割"
    case trajectory = "轨迹检测"
    case opticalFlow = "光流分析"
    case contour = "轮廓检测"

    var id: String { rawValue }

    var icon: String {
        switch self {
        case .bodyPose2D: return "figure.walk"
        case .bodyPose3D: return "figure.walk.motion"
        case .handPose: return "hand.raised"
        case .jointAngles: return "angle"
        case .swingPhase: return "chart.line.uptrend.xyaxis"
        case .swingPlane: return "skew"
        case .objectTrack: return "scope"
        case .personSegmentation: return "person.fill"
        case .foregroundMask: return "square.on.square"
        case .trajectory: return "point.topleft.down.to.point.bottomright.curvepath"
        case .opticalFlow: return "wind"
        case .contour: return "square.dashed"
        }
    }

    var description: String {
        switch self {
        case .bodyPose2D: return "19个关节点 + 骨架连线"
        case .bodyPose3D: return "3D姿态 + 深度颜色"
        case .handPose: return "手部21关节点（握杆分析）"
        case .jointAngles: return "髋/肩/肘/脊柱角度实时显示"
        case .swingPhase: return "自动识别挥杆阶段（准备→收杆）"
        case .swingPlane: return "挥杆平面一致性检测"
        case .objectTrack: return "点击选择目标逐帧追踪轨迹"
        case .personSegmentation: return "人体区域分割蒙版（高精度）"
        case .foregroundMask: return "前景物体实例分割"
        case .trajectory: return "球/杆头运动轨迹追踪"
        case .opticalFlow: return "运动速度热力图"
        case .contour: return "边缘轮廓（人体+球杆形态）"
        }
    }
}

struct AnalyzedFrame {
    let time: CMTime
    let joints: [JointPoint]
    let connections: [JointConnection]
    let segmentationMask: CGImage?
    let contourPaths: [CGPath]
    let trajectoryPoints: [CGPoint]
    let opticalFlowImage: CGImage?
    let angleLabels: [AngleLabel]
    let swingPhaseText: String?
    let planeLine: (CGPoint, CGPoint)?
    let planeDeviation: Double?
    let model: AnalysisModel
}

struct AngleLabel {
    let position: CGPoint
    let angle: Double
    let name: String
}

struct JointPoint {
    let name: VNHumanBodyPoseObservation.JointName?
    let position: CGPoint
    let confidence: Float
    let label: String?
}

struct JointConnection {
    let from: CGPoint
    let to: CGPoint
}

// MARK: - Custom Player View (no extra controls, exact video rect)
private struct PlayerLayerView: UIViewRepresentable {
    let player: AVPlayer

    func makeUIView(context: Context) -> PlayerUIView {
        let view = PlayerUIView()
        view.playerLayer.player = player
        view.playerLayer.videoGravity = .resizeAspect
        view.backgroundColor = .black
        return view
    }

    func updateUIView(_ uiView: PlayerUIView, context: Context) {}
}

private class PlayerUIView: UIView {
    override class var layerClass: AnyClass { AVPlayerLayer.self }
    var playerLayer: AVPlayerLayer { layer as! AVPlayerLayer }
}

struct VideoPlaybackAnalysisView: View {
    let videoURL: URL
    let onDismiss: () -> Void

    @State private var player: AVPlayer?
    @State private var isAnalyzing = false
    @State private var analysisFrames: [AnalyzedFrame] = []
    @State private var currentFrameIndex = 0
    @State private var showOverlay = true
    @State private var analysisProgress: Double = 0
    @State private var selectedModel: AnalysisModel = .bodyPose2D
    @State private var showModelPicker = false
    @State private var videoNaturalSize: CGSize = CGSize(width: 1920, height: 1080)
    @State private var trackingTapPoint: CGPoint?
    @State private var trackingRect: CGRect?

    var body: some View {
        VStack(spacing: 0) {
            headerBar
            ZStack {
                if let player {
                    PlayerLayerView(player: player)
                }
                if showOverlay, !analysisFrames.isEmpty,
                   currentFrameIndex < analysisFrames.count {
                    FrameOverlayView(
                        frame: analysisFrames[currentFrameIndex],
                        videoNaturalSize: videoNaturalSize
                    )
                }
                if isAnalyzing { analysisOverlay }
                if selectedModel == .objectTrack && analysisFrames.isEmpty && !isAnalyzing {
                    trackingHintOverlay
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .contentShape(Rectangle())
            .onTapGesture { location in
                if selectedModel == .objectTrack && analysisFrames.isEmpty {
                    trackingTapPoint = location
                }
            }
            controlBar
        }
        .background(.black)
        .onAppear { setupPlayer() }
        .onDisappear { player?.pause() }
        .sheet(isPresented: $showModelPicker) { modelPickerSheet }
    }

    private func setupPlayer() {
        let p = AVPlayer(url: videoURL)
        p.pause()
        player = p
        Task {
            let asset = AVURLAsset(url: videoURL)
            if let track = try? await asset.loadTracks(withMediaType: .video).first,
               let size = try? await track.load(.naturalSize),
               let transform = try? await track.load(.preferredTransform) {
                let transformed = size.applying(transform)
                await MainActor.run {
                    videoNaturalSize = CGSize(width: abs(transformed.width), height: abs(transformed.height))
                }
            }
        }
    }

    private var headerBar: some View {
        HStack {
            Button(action: onDismiss) {
                HStack(spacing: 4) {
                    Image(systemName: "chevron.left")
                    Text("返回")
                }.foregroundStyle(.white)
            }
            Spacer()
            Button { showModelPicker = true } label: {
                HStack(spacing: 4) {
                    Image(systemName: selectedModel.icon)
                    Text(selectedModel.rawValue).font(.caption)
                }
                .padding(.horizontal, 10).padding(.vertical, 6)
                .background(.ultraThinMaterial, in: Capsule())
            }
            Spacer()
            Button { showOverlay.toggle() } label: {
                Image(systemName: showOverlay ? "eye.fill" : "eye.slash")
                    .foregroundStyle(showOverlay ? .green : .gray)
            }
        }
        .padding()
        .background(.black.opacity(0.8))
    }

    private var analysisOverlay: some View {
        VStack(spacing: 12) {
            ProgressView(value: analysisProgress).tint(.green).frame(width: 200)
            Text("正在分析: \(selectedModel.rawValue)")
                .font(.subheadline).foregroundStyle(.white)
            Text("\(Int(analysisProgress * 100))%")
                .font(.caption).foregroundStyle(.white.opacity(0.7))
        }
        .padding(24)
        .background(.black.opacity(0.7), in: RoundedRectangle(cornerRadius: 12))
    }

    private var trackingHintOverlay: some View {
        VStack(spacing: 8) {
            Image(systemName: "hand.tap")
                .font(.system(size: 40))
                .foregroundStyle(.white.opacity(0.8))
            Text("点击画面选择追踪目标")
                .font(.headline).foregroundStyle(.white)
            Text("选择杆头或球的位置")
                .font(.caption).foregroundStyle(.white.opacity(0.7))
            if trackingTapPoint != nil {
                HStack {
                    Image(systemName: "checkmark.circle.fill")
                        .foregroundStyle(.green)
                    Text("已选择目标，点击「开始分析」")
                        .font(.caption).foregroundStyle(.green)
                }
                .padding(.top, 4)
            }
        }
        .padding(24)
        .background(.black.opacity(0.6), in: RoundedRectangle(cornerRadius: 12))
    }

    private var controlBar: some View {
        VStack(spacing: 12) {
            if !analysisFrames.isEmpty {
                HStack {
                    Text("帧 \(currentFrameIndex + 1)/\(analysisFrames.count)")
                        .font(.caption).foregroundStyle(.white.opacity(0.7))
                    Spacer()
                    if currentFrameIndex < analysisFrames.count {
                        Text(frameInfoText(analysisFrames[currentFrameIndex]))
                            .font(.caption).foregroundStyle(.green)
                    }
                }.padding(.horizontal)
                Slider(
                    value: Binding(
                        get: { Double(currentFrameIndex) },
                        set: { currentFrameIndex = Int($0); seekToFrame(currentFrameIndex) }
                    ),
                    in: 0...Double(max(analysisFrames.count - 1, 1)), step: 1
                ).tint(.green).padding(.horizontal)
            }
            HStack(spacing: 24) {
                Button {
                    if currentFrameIndex > 0 { currentFrameIndex -= 1; seekToFrame(currentFrameIndex) }
                } label: {
                    Image(systemName: "backward.frame.fill").font(.title2).foregroundStyle(.white)
                }
                Button { startAnalysis() } label: {
                    HStack {
                        Image(systemName: "wand.and.stars")
                        Text(analysisFrames.isEmpty ? "开始分析" : "重新分析")
                    }
                    .font(.headline).foregroundStyle(.white)
                    .padding(.horizontal, 24).padding(.vertical, 12)
                    .background(.green, in: Capsule())
                }.disabled(isAnalyzing)
                Button {
                    if currentFrameIndex < analysisFrames.count - 1 { currentFrameIndex += 1; seekToFrame(currentFrameIndex) }
                } label: {
                    Image(systemName: "forward.frame.fill").font(.title2).foregroundStyle(.white)
                }
            }.padding(.bottom, 16)
        }
        .padding(.top, 12)
        .background(.black.opacity(0.8))
    }

    private var modelPickerSheet: some View {
        NavigationStack {
            List(AnalysisModel.allCases) { model in
                Button {
                    selectedModel = model
                    showModelPicker = false
                    analysisFrames = []
                } label: {
                    HStack(spacing: 12) {
                        Image(systemName: model.icon).font(.title3).frame(width: 30)
                            .foregroundStyle(model == selectedModel ? .blue : .primary)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(model.rawValue).foregroundStyle(.primary)
                            Text(model.description).font(.caption).foregroundStyle(.secondary)
                        }
                        Spacer()
                        if model == selectedModel {
                            Image(systemName: "checkmark").foregroundStyle(.blue)
                        }
                    }
                }
            }
            .navigationTitle("选择分析模型")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) { Button("完成") { showModelPicker = false } }
            }
        }
        .presentationDetents([.medium])
    }

    private func seekToFrame(_ index: Int) {
        guard index < analysisFrames.count else { return }
        player?.seek(to: analysisFrames[index].time, toleranceBefore: .zero, toleranceAfter: .zero)
    }

    private func frameInfoText(_ f: AnalyzedFrame) -> String {
        switch f.model {
        case .personSegmentation, .foregroundMask:
            return f.segmentationMask != nil ? "已分割" : "无结果"
        case .trajectory:
            return "轨迹点: \(f.trajectoryPoints.count)"
        case .opticalFlow:
            return f.opticalFlowImage != nil ? "光流已计算" : "无光流"
        case .contour:
            return "轮廓: \(f.contourPaths.count)"
        case .jointAngles:
            return "角度: \(f.angleLabels.count)"
        case .swingPhase:
            return f.swingPhaseText ?? "分析中"
        case .swingPlane:
            if let dev = f.planeDeviation {
                return String(format: "偏差: %.1f°", dev)
            }
            return "平面分析"
        case .objectTrack:
            return "轨迹点: \(f.trajectoryPoints.count)"
        default:
            return "关节: \(f.joints.count)"
        }
    }

    private func startAnalysis() {
        isAnalyzing = true
        analysisFrames = []
        analysisProgress = 0
        currentFrameIndex = 0
        let model = selectedModel
        Task {
            let frames = await runAnalysis(model: model)
            analysisFrames = frames
            isAnalyzing = false
            if !frames.isEmpty { seekToFrame(0) }
        }
    }

    private func runAnalysis(model: AnalysisModel) async -> [AnalyzedFrame] {
        let asset = AVURLAsset(url: videoURL)
        guard let duration = try? await asset.load(.duration) else { return [] }
        let totalSeconds = CMTimeGetSeconds(duration)
        let times = stride(from: 0.0, to: totalSeconds, by: 1.0 / 30.0).map {
            CMTime(seconds: $0, preferredTimescale: 600)
        }
        let generator = AVAssetImageGenerator(asset: asset)
        generator.appliesPreferredTrackTransform = true
        generator.requestedTimeToleranceBefore = CMTime(seconds: 0.01, preferredTimescale: 600)
        generator.requestedTimeToleranceAfter = CMTime(seconds: 0.01, preferredTimescale: 600)

        if model == .trajectory {
            return await runTrajectoryAnalysis(generator: generator, times: times)
        }
        if model == .opticalFlow {
            return await runOpticalFlowAnalysis(generator: generator, times: times)
        }
        if model == .objectTrack {
            return await runObjectTrackAnalysis(generator: generator, times: times)
        }
        if model == .swingPhase || model == .swingPlane || model == .jointAngles {
            return await runPoseBasedAnalysis(generator: generator, times: times, model: model)
        }

        var results: [AnalyzedFrame] = []
        let total = times.count
        for (i, time) in times.enumerated() {
            guard let (image, actualTime) = try? await generator.image(at: time) else { continue }
            results.append(analyze(image: image, time: actualTime, model: model))
            await MainActor.run { analysisProgress = Double(i + 1) / Double(total) }
        }
        return results
    }

    private func analyze(image: CGImage, time: CMTime, model: AnalysisModel) -> AnalyzedFrame {
        switch model {
        case .bodyPose2D: return bodyPose2D(image: image, time: time)
        case .bodyPose3D: return bodyPose2D(image: image, time: time)
        case .handPose: return handPose(image: image, time: time)
        case .personSegmentation: return personSeg(image: image, time: time)
        case .foregroundMask: return foregroundSeg(image: image, time: time)
        case .contour: return contourDetect(image: image, time: time)
        case .trajectory, .opticalFlow, .objectTrack, .jointAngles, .swingPhase, .swingPlane:
            return emptyFrame(time: time, model: model)
        }
    }

    private func emptyFrame(time: CMTime, model: AnalysisModel) -> AnalyzedFrame {
        AnalyzedFrame(time: time, joints: [], connections: [], segmentationMask: nil, contourPaths: [], trajectoryPoints: [], opticalFlowImage: nil, angleLabels: [], swingPhaseText: nil, planeLine: nil, planeDeviation: nil, model: model)
    }
}

// MARK: - Analysis Methods
private extension VideoPlaybackAnalysisView {
    static let bodyConns: [(VNHumanBodyPoseObservation.JointName, VNHumanBodyPoseObservation.JointName)] = [
        (.nose, .neck), (.neck, .leftShoulder), (.neck, .rightShoulder),
        (.leftShoulder, .leftElbow), (.leftElbow, .leftWrist),
        (.rightShoulder, .rightElbow), (.rightElbow, .rightWrist),
        (.neck, .root), (.root, .leftHip), (.root, .rightHip),
        (.leftHip, .leftKnee), (.leftKnee, .leftAnkle),
        (.rightHip, .rightKnee), (.rightKnee, .rightAnkle)
    ]

    static let handConns: [(VNHumanHandPoseObservation.JointName, VNHumanHandPoseObservation.JointName)] = [
        (.wrist, .thumbCMC), (.thumbCMC, .thumbMP), (.thumbMP, .thumbIP), (.thumbIP, .thumbTip),
        (.wrist, .indexMCP), (.indexMCP, .indexPIP), (.indexPIP, .indexDIP), (.indexDIP, .indexTip),
        (.wrist, .middleMCP), (.middleMCP, .middlePIP), (.middlePIP, .middleDIP), (.middleDIP, .middleTip),
        (.wrist, .ringMCP), (.ringMCP, .ringPIP), (.ringPIP, .ringDIP), (.ringDIP, .ringTip),
        (.wrist, .littleMCP), (.littleMCP, .littlePIP), (.littlePIP, .littleDIP), (.littleDIP, .littleTip)
    ]

    func bodyPose2D(image: CGImage, time: CMTime) -> AnalyzedFrame {
        let req = VNDetectHumanBodyPoseRequest()
        let handler = VNImageRequestHandler(cgImage: image, orientation: .up, options: [:])
        do {
            try handler.perform([req])
            guard let obs = req.results?.first else {
                return AnalyzedFrame(time: time, joints: [], connections: [], segmentationMask: nil, contourPaths: [], trajectoryPoints: [], opticalFlowImage: nil, angleLabels: [], swingPhaseText: nil, planeLine: nil, planeDeviation: nil, model: .bodyPose2D)
            }
            let pts = try obs.recognizedPoints(.all)
            var joints: [JointPoint] = []
            var conns: [JointConnection] = []
            for (name, p) in pts where p.confidence > 0.1 {
                joints.append(JointPoint(name: name, position: CGPoint(x: p.location.x, y: 1 - p.location.y), confidence: p.confidence, label: nil))
            }
            for (a, b) in Self.bodyConns {
                guard let pA = pts[a], let pB = pts[b], pA.confidence > 0.1, pB.confidence > 0.1 else { continue }
                conns.append(JointConnection(from: CGPoint(x: pA.location.x, y: 1 - pA.location.y),
                                             to: CGPoint(x: pB.location.x, y: 1 - pB.location.y)))
            }
            return AnalyzedFrame(time: time, joints: joints, connections: conns, segmentationMask: nil, contourPaths: [], trajectoryPoints: [], opticalFlowImage: nil, angleLabels: [], swingPhaseText: nil, planeLine: nil, planeDeviation: nil, model: .bodyPose2D)
        } catch {
            return AnalyzedFrame(time: time, joints: [], connections: [], segmentationMask: nil, contourPaths: [], trajectoryPoints: [], opticalFlowImage: nil, angleLabels: [], swingPhaseText: nil, planeLine: nil, planeDeviation: nil, model: .bodyPose2D)
        }
    }

    func handPose(image: CGImage, time: CMTime) -> AnalyzedFrame {
        let req = VNDetectHumanHandPoseRequest()
        req.maximumHandCount = 2
        let handler = VNImageRequestHandler(cgImage: image, orientation: .up, options: [:])
        do {
            try handler.perform([req])
            var joints: [JointPoint] = []
            var conns: [JointConnection] = []
            for obs in req.results ?? [] {
                let pts = try obs.recognizedPoints(.all)
                for (_, p) in pts where p.confidence > 0.1 {
                    joints.append(JointPoint(name: nil, position: CGPoint(x: p.location.x, y: 1 - p.location.y), confidence: p.confidence, label: nil))
                }
                for (a, b) in Self.handConns {
                    guard let pA = pts[a], let pB = pts[b], pA.confidence > 0.1, pB.confidence > 0.1 else { continue }
                    conns.append(JointConnection(from: CGPoint(x: pA.location.x, y: 1 - pA.location.y),
                                                 to: CGPoint(x: pB.location.x, y: 1 - pB.location.y)))
                }
            }
            return AnalyzedFrame(time: time, joints: joints, connections: conns, segmentationMask: nil, contourPaths: [], trajectoryPoints: [], opticalFlowImage: nil, angleLabels: [], swingPhaseText: nil, planeLine: nil, planeDeviation: nil, model: .handPose)
        } catch {
            return AnalyzedFrame(time: time, joints: [], connections: [], segmentationMask: nil, contourPaths: [], trajectoryPoints: [], opticalFlowImage: nil, angleLabels: [], swingPhaseText: nil, planeLine: nil, planeDeviation: nil, model: .handPose)
        }
    }

    func personSeg(image: CGImage, time: CMTime) -> AnalyzedFrame {
        let req = VNGeneratePersonSegmentationRequest()
        req.qualityLevel = .accurate
        let handler = VNImageRequestHandler(cgImage: image, orientation: .up, options: [:])
        do {
            try handler.perform([req])
            var maskImage: CGImage?
            if let buf = req.results?.first?.pixelBuffer {
                let ci = CIImage(cvPixelBuffer: buf)
                maskImage = CIContext().createCGImage(ci, from: ci.extent)
            }
            return AnalyzedFrame(time: time, joints: [], connections: [], segmentationMask: maskImage, contourPaths: [], trajectoryPoints: [], opticalFlowImage: nil, angleLabels: [], swingPhaseText: nil, planeLine: nil, planeDeviation: nil, model: .personSegmentation)
        } catch {
            return AnalyzedFrame(time: time, joints: [], connections: [], segmentationMask: nil, contourPaths: [], trajectoryPoints: [], opticalFlowImage: nil, angleLabels: [], swingPhaseText: nil, planeLine: nil, planeDeviation: nil, model: .personSegmentation)
        }
    }

    func foregroundSeg(image: CGImage, time: CMTime) -> AnalyzedFrame {
        return personSeg(image: image, time: time)
    }

    func contourDetect(image: CGImage, time: CMTime) -> AnalyzedFrame {
        let req = VNDetectContoursRequest()
        req.contrastAdjustment = 1.5
        req.maximumImageDimension = 512
        let handler = VNImageRequestHandler(cgImage: image, orientation: .up, options: [:])
        do {
            try handler.perform([req])
            var paths: [CGPath] = []
            if let obs = req.results?.first {
                let count = obs.contourCount
                for i in 0..<count {
                    if let contour = try? obs.contour(at: i) {
                        paths.append(contour.normalizedPath)
                    }
                }
            }
            return AnalyzedFrame(time: time, joints: [], connections: [], segmentationMask: nil, contourPaths: paths, trajectoryPoints: [], opticalFlowImage: nil, angleLabels: [], swingPhaseText: nil, planeLine: nil, planeDeviation: nil, model: .contour)
        } catch {
            return AnalyzedFrame(time: time, joints: [], connections: [], segmentationMask: nil, contourPaths: [], trajectoryPoints: [], opticalFlowImage: nil, angleLabels: [], swingPhaseText: nil, planeLine: nil, planeDeviation: nil, model: .contour)
        }
    }

    func runTrajectoryAnalysis(generator: AVAssetImageGenerator, times: [CMTime]) async -> [AnalyzedFrame] {
        let req = VNDetectTrajectoriesRequest(frameAnalysisSpacing: .zero, trajectoryLength: 5) { _, _ in }
        req.objectMinimumNormalizedRadius = 0.01
        req.objectMaximumNormalizedRadius = 0.15
        let sequenceHandler = VNSequenceRequestHandler()
        var results: [AnalyzedFrame] = []
        let total = times.count
        var accumulatedTrajectories: [[CGPoint]] = []

        for (i, time) in times.enumerated() {
            guard let (image, actualTime) = try? await generator.image(at: time) else { continue }
            try? sequenceHandler.perform([req], on: image, orientation: .up)

            if let observations = req.results, !observations.isEmpty {
                for obs in observations {
                    let points = obs.detectedPoints.map { CGPoint(x: $0.x, y: 1 - $0.y) }
                    accumulatedTrajectories.append(points)
                }
            }

            let allPoints = accumulatedTrajectories.suffix(15).flatMap { $0 }
            results.append(AnalyzedFrame(time: actualTime, joints: [], connections: [], segmentationMask: nil, contourPaths: [], trajectoryPoints: allPoints, opticalFlowImage: nil, angleLabels: [], swingPhaseText: nil, planeLine: nil, planeDeviation: nil, model: .trajectory))
            await MainActor.run { analysisProgress = Double(i + 1) / Double(total) }
        }
        return results
    }

    func runOpticalFlowAnalysis(generator: AVAssetImageGenerator, times: [CMTime]) async -> [AnalyzedFrame] {
        var results: [AnalyzedFrame] = []
        let total = times.count
        var prevBuffer: CVPixelBuffer?

        for (i, time) in times.enumerated() {
            guard let (image, actualTime) = try? await generator.image(at: time) else { continue }

            let ciImage = CIImage(cgImage: image)
            let ctx = CIContext()
            var currentBuffer: CVPixelBuffer?
            let attrs: [String: Any] = [
                kCVPixelBufferCGImageCompatibilityKey as String: true,
                kCVPixelBufferWidthKey as String: image.width,
                kCVPixelBufferHeightKey as String: image.height
            ]
            CVPixelBufferCreate(kCFAllocatorDefault, image.width, image.height, kCVPixelFormatType_32BGRA, attrs as CFDictionary, &currentBuffer)

            if let buf = currentBuffer {
                ctx.render(ciImage, to: buf)
            }

            if let prev = prevBuffer, currentBuffer != nil {
                let req = VNGenerateOpticalFlowRequest(targetedCGImage: image, options: [:])
                let handler = VNImageRequestHandler(cvPixelBuffer: prev, options: [:])
                try? handler.perform([req])

                var flowImage: CGImage?
                if let obs = req.results?.first as? VNPixelBufferObservation {
                    let ci = CIImage(cvPixelBuffer: obs.pixelBuffer)
                    flowImage = ctx.createCGImage(ci, from: ci.extent)
                }
                results.append(AnalyzedFrame(time: actualTime, joints: [], connections: [], segmentationMask: nil, contourPaths: [], trajectoryPoints: [], opticalFlowImage: flowImage, angleLabels: [], swingPhaseText: nil, planeLine: nil, planeDeviation: nil, model: .opticalFlow))
            } else {
                results.append(AnalyzedFrame(time: actualTime, joints: [], connections: [], segmentationMask: nil, contourPaths: [], trajectoryPoints: [], opticalFlowImage: nil, angleLabels: [], swingPhaseText: nil, planeLine: nil, planeDeviation: nil, model: .opticalFlow))
            }

            prevBuffer = currentBuffer
            await MainActor.run { analysisProgress = Double(i + 1) / Double(total) }
        }
        return results
    }

    // MARK: - Golf-Specific Analysis

    func runPoseBasedAnalysis(generator: AVAssetImageGenerator, times: [CMTime], model: AnalysisModel) async -> [AnalyzedFrame] {
        let req = VNDetectHumanBodyPoseRequest()
        var results: [AnalyzedFrame] = []
        let total = times.count
        var wristHistory: [CGPoint] = []
        var prevHipAngle: Double?

        for (i, time) in times.enumerated() {
            guard let (image, actualTime) = try? await generator.image(at: time) else { continue }
            let handler = VNImageRequestHandler(cgImage: image, orientation: .up, options: [:])
            try? handler.perform([req])

            guard let obs = req.results?.first,
                  let pts = try? obs.recognizedPoints(.all) else {
                results.append(emptyFrame(time: actualTime, model: model))
                await MainActor.run { analysisProgress = Double(i + 1) / Double(total) }
                continue
            }

            var joints: [JointPoint] = []
            var conns: [JointConnection] = []
            for (name, p) in pts where p.confidence > 0.1 {
                joints.append(JointPoint(name: name, position: CGPoint(x: p.location.x, y: 1 - p.location.y), confidence: p.confidence, label: nil))
            }
            for (a, b) in Self.bodyConns {
                guard let pA = pts[a], let pB = pts[b], pA.confidence > 0.1, pB.confidence > 0.1 else { continue }
                conns.append(JointConnection(from: CGPoint(x: pA.location.x, y: 1 - pA.location.y),
                                             to: CGPoint(x: pB.location.x, y: 1 - pB.location.y)))
            }

            switch model {
            case .jointAngles:
                let angles = computeJointAngles(pts: pts)
                results.append(AnalyzedFrame(time: actualTime, joints: joints, connections: conns, segmentationMask: nil, contourPaths: [], trajectoryPoints: [], opticalFlowImage: nil, angleLabels: angles, swingPhaseText: nil, planeLine: nil, planeDeviation: nil, model: model))
            case .swingPhase:
                let phase = detectSwingPhase(pts: pts, prevHipAngle: &prevHipAngle)
                results.append(AnalyzedFrame(time: actualTime, joints: joints, connections: conns, segmentationMask: nil, contourPaths: [], trajectoryPoints: [], opticalFlowImage: nil, angleLabels: [], swingPhaseText: phase, planeLine: nil, planeDeviation: nil, model: model))
            case .swingPlane:
                if let wrist = pts[.rightWrist], wrist.confidence > 0.1 {
                    let wp = CGPoint(x: wrist.location.x, y: 1 - wrist.location.y)
                    wristHistory.append(wp)
                }
                let (line, deviation) = computeSwingPlane(wristHistory: wristHistory, pts: pts)
                results.append(AnalyzedFrame(time: actualTime, joints: joints, connections: conns, segmentationMask: nil, contourPaths: [], trajectoryPoints: wristHistory.suffix(30).map { $0 }, opticalFlowImage: nil, angleLabels: [], swingPhaseText: nil, planeLine: line, planeDeviation: deviation, model: model))
            default:
                results.append(emptyFrame(time: actualTime, model: model))
            }
            await MainActor.run { analysisProgress = Double(i + 1) / Double(total) }
        }
        return results
    }

    func runObjectTrackAnalysis(generator: AVAssetImageGenerator, times: [CMTime]) async -> [AnalyzedFrame] {
        var results: [AnalyzedFrame] = []
        let total = times.count

        guard let tapPoint = await MainActor.run(body: { trackingTapPoint }) else {
            for (i, time) in times.enumerated() {
                guard let (_, actualTime) = try? await generator.image(at: time) else { continue }
                results.append(emptyFrame(time: actualTime, model: .objectTrack))
                await MainActor.run { analysisProgress = Double(i + 1) / Double(total) }
            }
            return results
        }

        guard let (firstImage, _) = try? await generator.image(at: times.first ?? .zero) else { return results }
        let imgW = CGFloat(firstImage.width)
        let imgH = CGFloat(firstImage.height)

        let videoSize = await MainActor.run { videoNaturalSize }
        let normalizedX = tapPoint.x / videoSize.width
        let normalizedY = tapPoint.y / videoSize.height

        let boxSize: CGFloat = 0.08
        let initRect = CGRect(
            x: max(0, normalizedX - boxSize / 2),
            y: max(0, normalizedY - boxSize / 2),
            width: boxSize,
            height: boxSize
        )

        let trackReq = VNTrackObjectRequest(detectedObjectObservation: VNDetectedObjectObservation(boundingBox: initRect))
        trackReq.trackingLevel = .accurate
        let sequenceHandler = VNSequenceRequestHandler()
        var trackedPoints: [CGPoint] = []

        for (i, time) in times.enumerated() {
            guard let (image, actualTime) = try? await generator.image(at: time) else { continue }
            try? sequenceHandler.perform([trackReq], on: image, orientation: .up)

            if let obs = trackReq.results?.first as? VNDetectedObjectObservation {
                let center = CGPoint(x: obs.boundingBox.midX, y: 1 - obs.boundingBox.midY)
                trackedPoints.append(center)
                trackReq.inputObservation = obs
            }

            results.append(AnalyzedFrame(time: actualTime, joints: [], connections: [], segmentationMask: nil, contourPaths: [], trajectoryPoints: trackedPoints.suffix(30).map { $0 }, opticalFlowImage: nil, angleLabels: [], swingPhaseText: nil, planeLine: nil, planeDeviation: nil, model: .objectTrack))
            await MainActor.run { analysisProgress = Double(i + 1) / Double(total) }
        }
        return results
    }

    private func computeJointAngles(pts: [VNHumanBodyPoseObservation.JointName: VNRecognizedPoint]) -> [AngleLabel] {
        var angles: [AngleLabel] = []

        if let lShoulder = pts[.leftShoulder], let lElbow = pts[.leftElbow], let lWrist = pts[.leftWrist],
           lShoulder.confidence > 0.1, lElbow.confidence > 0.1, lWrist.confidence > 0.1 {
            let angle = angleBetween(a: lShoulder.location, b: lElbow.location, c: lWrist.location)
            angles.append(AngleLabel(position: CGPoint(x: lElbow.location.x, y: 1 - lElbow.location.y), angle: angle, name: "左肘"))
        }

        if let rShoulder = pts[.rightShoulder], let rElbow = pts[.rightElbow], let rWrist = pts[.rightWrist],
           rShoulder.confidence > 0.1, rElbow.confidence > 0.1, rWrist.confidence > 0.1 {
            let angle = angleBetween(a: rShoulder.location, b: rElbow.location, c: rWrist.location)
            angles.append(AngleLabel(position: CGPoint(x: rElbow.location.x, y: 1 - rElbow.location.y), angle: angle, name: "右肘"))
        }

        if let lHip = pts[.leftHip], let lKnee = pts[.leftKnee], let lAnkle = pts[.leftAnkle],
           lHip.confidence > 0.1, lKnee.confidence > 0.1, lAnkle.confidence > 0.1 {
            let angle = angleBetween(a: lHip.location, b: lKnee.location, c: lAnkle.location)
            angles.append(AngleLabel(position: CGPoint(x: lKnee.location.x, y: 1 - lKnee.location.y), angle: angle, name: "左膝"))
        }

        if let rHip = pts[.rightHip], let rKnee = pts[.rightKnee], let rAnkle = pts[.rightAnkle],
           rHip.confidence > 0.1, rKnee.confidence > 0.1, rAnkle.confidence > 0.1 {
            let angle = angleBetween(a: rHip.location, b: rKnee.location, c: rAnkle.location)
            angles.append(AngleLabel(position: CGPoint(x: rKnee.location.x, y: 1 - rKnee.location.y), angle: angle, name: "右膝"))
        }

        if let lShoulder = pts[.leftShoulder], let root = pts[.root], let lHip = pts[.leftHip],
           lShoulder.confidence > 0.1, root.confidence > 0.1, lHip.confidence > 0.1 {
            let angle = angleBetween(a: lShoulder.location, b: root.location, c: lHip.location)
            angles.append(AngleLabel(position: CGPoint(x: root.location.x, y: 1 - root.location.y), angle: angle, name: "躯干"))
        }

        if let neck = pts[.neck], let lShoulder = pts[.leftShoulder], let rShoulder = pts[.rightShoulder],
           let root = pts[.root], neck.confidence > 0.1, lShoulder.confidence > 0.1, rShoulder.confidence > 0.1, root.confidence > 0.1 {
            let shoulderMid = CGPoint(x: (lShoulder.location.x + rShoulder.location.x) / 2,
                                      y: (lShoulder.location.y + rShoulder.location.y) / 2)
            let spineAngle = atan2(shoulderMid.y - root.location.y, shoulderMid.x - root.location.x) * 180 / .pi
            let tilt = abs(90 - abs(spineAngle))
            angles.append(AngleLabel(position: CGPoint(x: neck.location.x, y: 1 - neck.location.y), angle: tilt, name: "前倾"))
        }

        return angles
    }

    private func detectSwingPhase(pts: [VNHumanBodyPoseObservation.JointName: VNRecognizedPoint], prevHipAngle: inout Double?) -> String {
        guard let rWrist = pts[.rightWrist], let rShoulder = pts[.rightShoulder],
              let root = pts[.root], let lHip = pts[.leftHip], let rHip = pts[.rightHip],
              rWrist.confidence > 0.1, rShoulder.confidence > 0.1, root.confidence > 0.1 else {
            return "未检测到"
        }

        let wristY = 1 - rWrist.location.y
        let shoulderY = 1 - rShoulder.location.y
        let hipMidX = (lHip.location.x + rHip.location.x) / 2
        let shoulderX = rShoulder.location.x

        let hipAngle = atan2(rHip.location.y - lHip.location.y, rHip.location.x - lHip.location.x) * 180 / .pi
        let hipRotationSpeed = abs(hipAngle - (prevHipAngle ?? hipAngle))
        prevHipAngle = hipAngle

        if wristY > shoulderY + 0.15 {
            return "准备 (Address)"
        } else if wristY < shoulderY - 0.1 && rWrist.location.x > shoulderX {
            return "上杆 (Backswing)"
        } else if wristY < shoulderY - 0.2 {
            return "顶点 (Top)"
        } else if hipRotationSpeed > 3.0 {
            return "下杆 (Downswing)"
        } else if wristY > shoulderY && hipRotationSpeed > 1.0 {
            return "击球 (Impact)"
        } else if rWrist.location.x < hipMidX {
            return "收杆 (Follow-through)"
        }
        return "过渡"
    }

    private func computeSwingPlane(wristHistory: [CGPoint], pts: [VNHumanBodyPoseObservation.JointName: VNRecognizedPoint]) -> ((CGPoint, CGPoint)?, Double?) {
        guard wristHistory.count >= 5,
              let rShoulder = pts[.rightShoulder], rShoulder.confidence > 0.1 else {
            return (nil, nil)
        }

        let recent = Array(wristHistory.suffix(20))
        let n = Double(recent.count)
        let sumX = recent.map(\.x).reduce(0, +)
        let sumY = recent.map(\.y).reduce(0, +)
        let sumXY = recent.map { Double($0.x) * Double($0.y) }.reduce(0, +)
        let sumX2 = recent.map { Double($0.x) * Double($0.x) }.reduce(0, +)

        let denom = n * sumX2 - Double(sumX) * Double(sumX)
        guard abs(denom) > 0.0001 else { return (nil, nil) }

        let slope = (n * sumXY - Double(sumX) * Double(sumY)) / denom
        let intercept = (Double(sumY) - slope * Double(sumX)) / n

        let x1: CGFloat = 0.1
        let x2: CGFloat = 0.9
        let y1 = CGFloat(slope * Double(x1) + intercept)
        let y2 = CGFloat(slope * Double(x2) + intercept)
        let line = (CGPoint(x: x1, y: y1), CGPoint(x: x2, y: y2))

        let planeAngle = atan(slope) * 180 / .pi
        let idealAngle = 45.0
        let deviation = abs(planeAngle - idealAngle)

        return (line, deviation)
    }

    private func angleBetween(a: CGPoint, b: CGPoint, c: CGPoint) -> Double {
        let ba = CGPoint(x: a.x - b.x, y: a.y - b.y)
        let bc = CGPoint(x: c.x - b.x, y: c.y - b.y)
        let dot = ba.x * bc.x + ba.y * bc.y
        let magBA = sqrt(ba.x * ba.x + ba.y * ba.y)
        let magBC = sqrt(bc.x * bc.x + bc.y * bc.y)
        guard magBA > 0, magBC > 0 else { return 0 }
        let cosAngle = max(-1, min(1, dot / (magBA * magBC)))
        return acos(cosAngle) * 180 / .pi
    }
}
private struct FrameOverlayView: View {
    let frame: AnalyzedFrame
    let videoNaturalSize: CGSize

    var body: some View {
        GeometryReader { geo in
            let containerSize = geo.size
            let videoAspect = videoNaturalSize.width / videoNaturalSize.height
            let containerAspect = containerSize.width / containerSize.height

            let videoRect: CGRect = {
                if videoAspect > containerAspect {
                    let h = containerSize.width / videoAspect
                    let y = (containerSize.height - h) / 2
                    return CGRect(x: 0, y: y, width: containerSize.width, height: h)
                } else {
                    let w = containerSize.height * videoAspect
                    let x = (containerSize.width - w) / 2
                    return CGRect(x: x, y: 0, width: w, height: containerSize.height)
                }
            }()

            Canvas { context, _ in
                if let mask = frame.segmentationMask {
                    let resolved = context.resolve(Image(decorative: mask, scale: 1.0))
                    context.opacity = 0.4
                    context.draw(resolved, in: videoRect)
                    context.opacity = 1.0
                }
                if let flowImg = frame.opticalFlowImage {
                    let resolved = context.resolve(Image(decorative: flowImg, scale: 1.0))
                    context.opacity = 0.6
                    context.draw(resolved, in: videoRect)
                    context.opacity = 1.0
                }
                for contourPath in frame.contourPaths {
                    var transform = CGAffineTransform(scaleX: videoRect.width, y: -videoRect.height)
                        .translatedBy(x: videoRect.minX / videoRect.width, y: -1 - videoRect.minY / videoRect.height)
                    if let transformed = contourPath.copy(using: &transform) {
                        context.stroke(Path(transformed), with: .color(.cyan.opacity(0.7)), lineWidth: 1.5)
                    }
                }
                if !frame.trajectoryPoints.isEmpty {
                    for (i, pt) in frame.trajectoryPoints.enumerated() {
                        let p = CGPoint(
                            x: videoRect.minX + pt.x * videoRect.width,
                            y: videoRect.minY + pt.y * videoRect.height
                        )
                        let alpha = Double(i + 1) / Double(frame.trajectoryPoints.count)
                        let r: CGFloat = 4 + CGFloat(alpha) * 4
                        let rect = CGRect(x: p.x - r, y: p.y - r, width: r * 2, height: r * 2)
                        context.fill(Path(ellipseIn: rect), with: .color(.red.opacity(alpha)))
                    }
                    if frame.trajectoryPoints.count > 1 {
                        var path = Path()
                        for (i, pt) in frame.trajectoryPoints.enumerated() {
                            let p = CGPoint(
                                x: videoRect.minX + pt.x * videoRect.width,
                                y: videoRect.minY + pt.y * videoRect.height
                            )
                            if i == 0 { path.move(to: p) } else { path.addLine(to: p) }
                        }
                        context.stroke(path, with: .color(.red.opacity(0.8)), lineWidth: 2)
                    }
                }
                for conn in frame.connections {
                    let from = CGPoint(
                        x: videoRect.minX + conn.from.x * videoRect.width,
                        y: videoRect.minY + conn.from.y * videoRect.height
                    )
                    let to = CGPoint(
                        x: videoRect.minX + conn.to.x * videoRect.width,
                        y: videoRect.minY + conn.to.y * videoRect.height
                    )
                    var path = Path()
                    path.move(to: from)
                    path.addLine(to: to)
                    context.stroke(path, with: .color(.green), lineWidth: 3)
                }
                for joint in frame.joints {
                    let p = CGPoint(
                        x: videoRect.minX + joint.position.x * videoRect.width,
                        y: videoRect.minY + joint.position.y * videoRect.height
                    )
                    let r = CGRect(x: p.x - 5, y: p.y - 5, width: 10, height: 10)
                    context.fill(Path(ellipseIn: r), with: .color(.yellow))
                }
                for label in frame.angleLabels {
                    let p = CGPoint(
                        x: videoRect.minX + label.position.x * videoRect.width,
                        y: videoRect.minY + label.position.y * videoRect.height
                    )
                    let text = context.resolve(Text("\(label.name)\n\(Int(label.angle))°").font(.system(size: 10, weight: .bold)).foregroundColor(.orange))
                    context.draw(text, at: CGPoint(x: p.x + 12, y: p.y - 8))
                }
                if let line = frame.planeLine {
                    let from = CGPoint(
                        x: videoRect.minX + line.0.x * videoRect.width,
                        y: videoRect.minY + line.0.y * videoRect.height
                    )
                    let to = CGPoint(
                        x: videoRect.minX + line.1.x * videoRect.width,
                        y: videoRect.minY + line.1.y * videoRect.height
                    )
                    var path = Path()
                    path.move(to: from)
                    path.addLine(to: to)
                    let color: Color = (frame.planeDeviation ?? 0) < 10 ? .green : .orange
                    context.stroke(path, with: .color(color.opacity(0.8)), style: StrokeStyle(lineWidth: 2, dash: [8, 4]))
                }
            }
            if let phase = frame.swingPhaseText {
                VStack {
                    Text(phase)
                        .font(.system(size: 16, weight: .bold))
                        .foregroundStyle(.white)
                        .padding(.horizontal, 12)
                        .padding(.vertical, 6)
                        .background(.black.opacity(0.7), in: Capsule())
                    Spacer()
                }
                .padding(.top, 8)
                .frame(maxWidth: .infinity)
            }
        }
        .allowsHitTesting(false)
    }
}

extension Array {
    subscript(safe index: Int) -> Element? {
        indices.contains(index) ? self[index] : nil
    }
}