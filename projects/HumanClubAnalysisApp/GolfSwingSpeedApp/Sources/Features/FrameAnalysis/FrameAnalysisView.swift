import SwiftUI

/// Manual frame-by-frame analysis view.
/// User scrubs through captured frames and taps to mark club head position.
/// Speed is calculated from marked positions using calibration data.
struct FrameAnalysisView: View {
    let videoURL: URL
    let calibration: CalibrationSnapshot?
    var onComplete: ((Double?, SpeedProfile?) -> Void)?

    @State private var frames: [VideoFrameExtractor.FrameInfo] = []
    @State private var currentFrameIndex: Int = 0
    @State private var markedPositions: [Int: CGPoint] = [:] // frameIndex → tap position
    @State private var isLoading = true
    @State private var loadingProgress: Double = 0
    @State private var errorMessage: String?
    @State private var calculatedSpeedMph: Double?
    @State private var speedProfile: SpeedProfile?
    @State private var videoFPS: Double = 0
    @State private var imageSize: CGSize = .zero

    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                if isLoading {
                    loadingView
                } else if frames.isEmpty {
                    ContentUnavailableView(
                        "No Frames",
                        systemImage: "film",
                        description: Text(errorMessage ?? "Could not extract frames from video.")
                    )
                } else {
                    frameViewer
                    controlsBar
                    markedFramesSummary
                }
            }
            .navigationTitle("Frame Analysis")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button("Close") { dismiss() }
                }
                ToolbarItem(placement: .topBarTrailing) {
                    if !markedPositions.isEmpty {
                        Button("Calculate") {
                            calculateSpeed()
                        }
                        .fontWeight(.semibold)
                    }
                }
            }
            .task {
                await loadFrames()
            }
        }
    }

    // MARK: - Loading View

    private var loadingView: some View {
        VStack(spacing: 16) {
            ProgressView(value: loadingProgress) {
                Text("Extracting frames...")
            }
            .padding(.horizontal, 40)

            Text("\(Int(loadingProgress * 100))%")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .frame(maxHeight: .infinity)
    }

    // MARK: - Frame Viewer

    private var frameViewer: some View {
        GeometryReader { geometry in
            ZStack {
                // Current frame image
                if currentFrameIndex < frames.count {
                    Image(uiImage: frames[currentFrameIndex].image)
                        .resizable()
                        .aspectRatio(contentMode: .fit)
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                        .background(
                            GeometryReader { imgGeometry in
                                Color.clear.onAppear {
                                    imageSize = imgGeometry.size
                                }
                                .onChange(of: imgGeometry.size) { _, newSize in
                                    imageSize = newSize
                                }
                            }
                        )
                }

                // Marked position for current frame
                if let position = markedPositions[currentFrameIndex] {
                    ClubHeadMarker(position: position)
                }

                // Previous frame's marker (ghosted) for reference
                if currentFrameIndex > 0, let prevPosition = markedPositions[currentFrameIndex - 1] {
                    ClubHeadMarker(position: prevPosition, isGhost: true)
                }
            }
            .contentShape(Rectangle())
            .onTapGesture { location in
                markedPositions[currentFrameIndex] = location
            }
        }
        .background(.black)
    }

    // MARK: - Controls Bar

    private var controlsBar: some View {
        VStack(spacing: 8) {
            // Frame scrubber
            HStack {
                Button {
                    if currentFrameIndex > 0 { currentFrameIndex -= 1 }
                } label: {
                    Image(systemName: "chevron.left")
                        .font(.title3)
                }
                .disabled(currentFrameIndex == 0)

                Slider(
                    value: Binding(
                        get: { Double(currentFrameIndex) },
                        set: { currentFrameIndex = Int($0) }
                    ),
                    in: 0...Double(max(frames.count - 1, 0)),
                    step: 1
                )

                Button {
                    if currentFrameIndex < frames.count - 1 { currentFrameIndex += 1 }
                } label: {
                    Image(systemName: "chevron.right")
                        .font(.title3)
                }
                .disabled(currentFrameIndex >= frames.count - 1)
            }
            .padding(.horizontal)

            // Frame info
            HStack {
                Text("Frame \(currentFrameIndex + 1) / \(frames.count)")
                    .font(.caption)
                    .monospacedDigit()

                Spacer()

                if currentFrameIndex < frames.count {
                    Text(String(format: "%.3fs", frames[currentFrameIndex].timestamp))
                        .font(.caption)
                        .monospacedDigit()
                }

                Spacer()

                // Mark/unmark button
                if markedPositions[currentFrameIndex] != nil {
                    Button("Clear Mark") {
                        markedPositions.removeValue(forKey: currentFrameIndex)
                    }
                    .font(.caption)
                    .tint(.red)
                } else {
                    Text("Tap frame to mark club head")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            .padding(.horizontal)

            // Speed result
            if let speed = calculatedSpeedMph {
                HStack {
                    Image(systemName: "speedometer")
                    Text("Impact Speed: \(speed.formattedSpeed) mph")
                        .fontWeight(.bold)
                }
                .font(.headline)
                .foregroundStyle(.green)
                .padding(.vertical, 4)
            }
        }
        .padding(.vertical, 8)
        .background(.regularMaterial)
    }

    // MARK: - Marked Frames Summary

    private var markedFramesSummary: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text("Marked: \(markedPositions.count) frames")
                    .font(.caption)
                    .fontWeight(.semibold)

                Spacer()

                if markedPositions.count >= 2 {
                    Button("Clear All") {
                        markedPositions.removeAll()
                        calculatedSpeedMph = nil
                        speedProfile = nil
                    }
                    .font(.caption)
                    .tint(.red)
                }
            }

            // Thumbnail strip of marked frames
            if !markedPositions.isEmpty {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 4) {
                        ForEach(markedPositions.keys.sorted(), id: \.self) { index in
                            if index < frames.count {
                                Button {
                                    currentFrameIndex = index
                                } label: {
                                    Image(uiImage: frames[index].image)
                                        .resizable()
                                        .aspectRatio(contentMode: .fill)
                                        .frame(width: 50, height: 30)
                                        .clipShape(RoundedRectangle(cornerRadius: 4))
                                        .overlay {
                                            RoundedRectangle(cornerRadius: 4)
                                                .stroke(
                                                    currentFrameIndex == index ? .blue : .clear,
                                                    lineWidth: 2
                                                )
                                        }
                                }
                            }
                        }
                    }
                }
            }

            if markedPositions.count < 2 {
                Text("Mark at least 2 frames to calculate speed")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            }
        }
        .padding(.horizontal)
        .padding(.vertical, 8)
        .background(.regularMaterial)
    }

    // MARK: - Frame Loading

    private func loadFrames() async {
        let extractor = VideoFrameExtractor(url: videoURL)

        do {
            let info = try await extractor.videoInfo()
            videoFPS = info.fps

            // Extract a manageable number of frames for the scrubber
            // For a typical 1-3 second swing at 240fps, that's 240-720 frames
            // Extract every Nth frame to keep it at ~60-100 thumbnails
            let targetFrameCount = min(info.frameCount, 100)

            let extracted = try await extractor.extractFrames(count: targetFrameCount)

            await MainActor.run {
                frames = extracted
                isLoading = false
            }
        } catch {
            await MainActor.run {
                errorMessage = error.localizedDescription
                isLoading = false
            }
        }
    }

    // MARK: - Speed Calculation

    private func calculateSpeed() {
        guard let calibration, calibration.pixelsPerMetre > 0 else {
            errorMessage = "Calibration required for speed calculation"
            return
        }

        let sortedIndices = markedPositions.keys.sorted()
        guard sortedIndices.count >= 2 else { return }

        // Build TrackedPosition array from manual marks
        var positions: [TrackedPosition] = []
        for index in sortedIndices {
            guard index < frames.count,
                  let point = markedPositions[index] else { continue }

            let frame = frames[index]
            positions.append(TrackedPosition(
                frameTimestamp: frame.timestamp,
                position2D: point,
                position3D: nil,
                confidence: 1.0, // Manual marking = full confidence
                source: .manual
            ))
        }

        // Calculate speed profile
        let profile = SpeedCalculator.buildSpeedProfile(
            from: positions,
            calibration: calibration,
            impactTimestamp: nil // User hasn't marked impact specifically
        )

        speedProfile = profile
        calculatedSpeedMph = profile?.impactSpeedMph

        // Notify parent
        onComplete?(calculatedSpeedMph, speedProfile)
    }
}

// MARK: - Club Head Marker

struct ClubHeadMarker: View {
    let position: CGPoint
    var isGhost: Bool = false

    var body: some View {
        ZStack {
            Circle()
                .fill(isGhost ? .yellow.opacity(0.2) : .yellow.opacity(0.4))
                .frame(width: 24, height: 24)
            Circle()
                .stroke(isGhost ? .yellow.opacity(0.3) : .yellow, lineWidth: 2)
                .frame(width: 24, height: 24)

            if !isGhost {
                Circle()
                    .fill(.yellow)
                    .frame(width: 4, height: 4)
            }
        }
        .position(position)
    }
}

#Preview {
    FrameAnalysisView(
        videoURL: URL(fileURLWithPath: "/tmp/test.mov"),
        calibration: nil
    )
}
