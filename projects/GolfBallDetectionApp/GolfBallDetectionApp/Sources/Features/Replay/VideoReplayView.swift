import SwiftUI
import AVFoundation
import GolfAnalysisKit

struct VideoReplayView: View {
    let videoURL: URL
    let detectionRecords: [BallDetectionRecord]
    let prediction: TrajectoryPrediction?
    let ballFlightMetrics: BallFlightMetrics?

    @State private var player: AVPlayer?
    @State private var isPlaying = false
    @State private var currentTime: Double = 0
    @State private var duration: Double = 1
    @State private var playbackRate: Float = 1.0
    @State private var showDataPanel = true
    @State private var trajectoryProgress: Double = 1.0
    @State private var videoSize: CGSize = CGSize(width: 1920, height: 1080)
    @Environment(\.dismiss) private var dismiss

    private let rates: [Float] = [0.1, 0.25, 0.5, 1.0]

    var body: some View {
        GeometryReader { geo in
            ZStack {
                Color.black.ignoresSafeArea()

                VStack(spacing: 0) {
                    videoArea(size: geo.size)
                    controlBar
                    if showDataPanel {
                        FlightDataPanel(
                            prediction: prediction,
                            ballFlightMetrics: ballFlightMetrics,
                            isExpanded: true
                        )
                        .padding(.horizontal, 12)
                        .padding(.bottom, 8)
                        .transition(.move(edge: .bottom).combined(with: .opacity))
                    }
                }
            }
        }
        .onAppear(perform: setupPlayer)
        .onDisappear { player?.pause() }
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Button(showDataPanel ? "隐藏数据" : "显示数据") {
                    withAnimation { showDataPanel.toggle() }
                }
                .font(.caption)
            }
        }
    }

    @ViewBuilder
    private func videoArea(size: CGSize) -> some View {
        let videoAspect = videoSize.width / videoSize.height
        let availableHeight = size.height - 120 - (showDataPanel ? 260 : 0)
        let displayWidth = size.width
        let displayHeight = min(availableHeight, displayWidth / videoAspect)

        ZStack {
            VideoPlayerLayer(player: player ?? AVPlayer())
                .frame(width: displayWidth, height: displayHeight)

            TrajectoryOverlayView(
                bezierPoints: prediction?.bezierPoints ?? [],
                detectionPoints: visibleDetectionPoints,
                impactPoint: detectionRecords.first.map {
                    CGPoint(x: $0.centerX, y: $0.centerY)
                },
                landingPoint: prediction.map { pred in
                    let norm = min(1.0, pred.carryDistanceYards / 300.0)
                    return CGPoint(x: 0.1 + norm * 0.8, y: 0.85)
                },
                frameSize: videoSize,
                animationProgress: trajectoryProgress
            )
            .frame(width: displayWidth, height: displayHeight)
            .allowsHitTesting(false)
        }
        .frame(maxWidth: .infinity)
    }

    private var controlBar: some View {
        VStack(spacing: 8) {
            Slider(
                value: Binding(
                    get: { currentTime },
                    set: { seekTo($0) }
                ),
                in: 0...max(0.01, duration)
            )
            .tint(.yellow)
            .padding(.horizontal, 16)

            HStack(spacing: 20) {
                Button(action: stepBackward) {
                    Image(systemName: "backward.frame.fill")
                        .font(.title3)
                }

                Button(action: togglePlayPause) {
                    Image(systemName: isPlaying ? "pause.fill" : "play.fill")
                        .font(.title2)
                }

                Button(action: stepForward) {
                    Image(systemName: "forward.frame.fill")
                        .font(.title3)
                }

                Spacer()

                Text(formatTime(currentTime))
                    .font(.caption.monospacedDigit())
                    .foregroundStyle(.secondary)

                Menu {
                    ForEach(rates, id: \.self) { rate in
                        Button(rate == 1.0 ? "1x" : "\(rate, specifier: "%.2g")x") {
                            playbackRate = rate
                            player?.rate = isPlaying ? rate : 0
                        }
                    }
                } label: {
                    Text("\(playbackRate, specifier: "%.2g")x")
                        .font(.caption.bold())
                        .padding(.horizontal, 8)
                        .padding(.vertical, 4)
                        .background(.quaternary)
                        .clipShape(Capsule())
                }
            }
            .padding(.horizontal, 16)
            .padding(.bottom, 8)
        }
        .foregroundStyle(.white)
    }

    private var visibleDetectionPoints: [CGPoint] {
        detectionRecords
            .filter { $0.frameTimestamp <= currentTime }
            .map { CGPoint(x: $0.centerX, y: $0.centerY) }
    }

    private func setupPlayer() {
        let avPlayer = AVPlayer(url: videoURL)
        self.player = avPlayer

        Task {
            let asset = AVURLAsset(url: videoURL)
            if let dur = try? await asset.load(.duration) {
                duration = CMTimeGetSeconds(dur)
            }
            if let track = try? await asset.loadTracks(withMediaType: .video).first {
                let size = try? await track.load(.naturalSize)
                if let s = size { videoSize = s }
            }
        }

        let interval = CMTime(seconds: 1.0 / 30.0, preferredTimescale: 600)
        avPlayer.addPeriodicTimeObserver(forInterval: interval, queue: .main) { time in
            currentTime = CMTimeGetSeconds(time)
            if duration > 0 {
                trajectoryProgress = min(1.0, currentTime / duration)
            }
        }
    }

    private func togglePlayPause() {
        guard let player else { return }
        if isPlaying {
            player.pause()
        } else {
            player.rate = playbackRate
        }
        isPlaying.toggle()
    }

    private func seekTo(_ time: Double) {
        let cmTime = CMTime(seconds: time, preferredTimescale: 600)
        player?.seek(to: cmTime, toleranceBefore: .zero, toleranceAfter: .zero)
    }

    private func stepForward() {
        let fps = 240.0
        seekTo(min(duration, currentTime + 1.0 / fps))
    }

    private func stepBackward() {
        let fps = 240.0
        seekTo(max(0, currentTime - 1.0 / fps))
    }

    private func formatTime(_ seconds: Double) -> String {
        let mins = Int(seconds) / 60
        let secs = Int(seconds) % 60
        let ms = Int((seconds - Double(Int(seconds))) * 100)
        return String(format: "%d:%02d.%02d", mins, secs, ms)
    }
}

struct VideoPlayerLayer: UIViewRepresentable {
    let player: AVPlayer

    func makeUIView(context: Context) -> PlayerUIView {
        let view = PlayerUIView()
        view.playerLayer.player = player
        view.playerLayer.videoGravity = .resizeAspect
        view.backgroundColor = .black
        return view
    }

    func updateUIView(_ uiView: PlayerUIView, context: Context) {
        uiView.playerLayer.player = player
    }

    class PlayerUIView: UIView {
        override class var layerClass: AnyClass { AVPlayerLayer.self }
        var playerLayer: AVPlayerLayer { layer as! AVPlayerLayer }
    }
}
