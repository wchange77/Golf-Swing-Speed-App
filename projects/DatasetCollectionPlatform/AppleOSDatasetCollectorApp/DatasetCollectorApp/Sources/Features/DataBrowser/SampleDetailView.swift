import SwiftUI
import AVFoundation

struct SampleDetailView: View {
    let sample: CollectorSampleRecord
    let service: DatasetCollectorService
    let onDismiss: () -> Void

    @State private var thumbnail: UIImage?
    @State private var showPlaybackAnalysis = false
    @State private var showDeleteAlert = false

    private var videoURL: URL? {
        let docs = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first!
        let base = docs.appendingPathComponent("DatasetCollectorExport")
        let path = sample.assetPath.replacingOccurrences(of: "ios_export/", with: "")
        let url = base.appendingPathComponent(path)
        return FileManager.default.fileExists(atPath: url.path) ? url : nil
    }

    var body: some View {
        NavigationStack {
            if showPlaybackAnalysis, let url = videoURL {
                VideoPlaybackAnalysisView(videoURL: url) {
                    showPlaybackAnalysis = false
                }
            } else {
                detailContent
            }
        }
    }

    private var detailContent: some View {
        ScrollView {
            VStack(spacing: 20) {
                thumbnailSection
                metadataSection
                actionSection
            }
            .padding()
        }
        .navigationTitle("样本详情")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .topBarLeading) {
                Button("关闭") { onDismiss() }
            }
            ToolbarItem(placement: .topBarTrailing) {
                Button(role: .destructive) {
                    showDeleteAlert = true
                } label: {
                    Image(systemName: "trash")
                        .foregroundStyle(.red)
                }
            }
        }
        .alert("确认删除", isPresented: $showDeleteAlert) {
            Button("取消", role: .cancel) {}
            Button("删除", role: .destructive) {
                try? service.deleteSample(sampleId: sample.sampleId)
                onDismiss()
            }
        } message: {
            Text("删除后无法恢复")
        }
        .onAppear { generateThumbnail() }
    }

    private var thumbnailSection: some View {
        Group {
            if let thumbnail {
                Image(uiImage: thumbnail)
                    .resizable()
                    .aspectRatio(contentMode: .fit)
                    .frame(maxHeight: 200)
                    .clipShape(RoundedRectangle(cornerRadius: 12))
            } else {
                RoundedRectangle(cornerRadius: 12)
                    .fill(.gray.opacity(0.2))
                    .frame(height: 200)
                    .overlay {
                        Image(systemName: "video")
                            .font(.largeTitle)
                            .foregroundStyle(.secondary)
                    }
            }
        }
    }

    private var metadataSection: some View {
        VStack(spacing: 0) {
            metadataRow("样本 ID", sample.sampleId)
            metadataRow("域", sample.domain == "human_club" ? "人体+球杆" : "球检测")
            metadataRow("会话", String(sample.sessionId.prefix(16)))
            metadataRow("采集时间", formatDate(sample.capturedAt))
            metadataRow("文件大小", formatSize(sample.fileSize))
            metadataRow("杆型", sample.metadata.clubType)
            metadataRow("手性", sample.metadata.handedness == "right" ? "右手" : "左手")
            metadataRow("挥速", sample.metadata.swingIntensity)
            metadataRow("帧率", "\(sample.metadata.fps) fps")
            metadataRow("分辨率", sample.metadata.resolution)
            metadataRow("SHA-256", String(sample.sha256.prefix(16)) + "...")
        }
        .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 12))
    }

    private var actionSection: some View {
        VStack(spacing: 12) {
            if videoURL != nil {
                Button {
                    showPlaybackAnalysis = true
                } label: {
                    HStack {
                        Image(systemName: "wand.and.stars")
                        Text("回放骨架分析")
                    }
                    .font(.headline)
                    .frame(maxWidth: .infinity)
                    .padding()
                }
                .buttonStyle(.borderedProminent)
                .tint(.green)
            } else {
                Text("视频文件不存在")
                    .font(.subheadline)
                    .foregroundStyle(.red)
            }
        }
    }

    private func metadataRow(_ label: String, _ value: String) -> some View {
        HStack {
            Text(label)
                .font(.subheadline)
                .foregroundStyle(.secondary)
            Spacer()
            Text(value)
                .font(.subheadline)
                .fontWeight(.medium)
                .lineLimit(1)
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 10)
    }

    private func generateThumbnail() {
        guard let url = videoURL else { return }
        Task.detached {
            let asset = AVURLAsset(url: url)
            let generator = AVAssetImageGenerator(asset: asset)
            generator.appliesPreferredTrackTransform = true
            if let (image, _) = try? await generator.image(at: CMTime(seconds: 0.5, preferredTimescale: 600)) {
                let uiImage = UIImage(cgImage: image)
                await MainActor.run { thumbnail = uiImage }
            }
        }
    }

    private func formatDate(_ iso: String) -> String {
        String(iso.prefix(19).replacingOccurrences(of: "T", with: " "))
    }

    private func formatSize(_ bytes: Int) -> String {
        if bytes > 1_000_000 {
            return String(format: "%.1f MB", Double(bytes) / 1_000_000)
        }
        return String(format: "%.0f KB", Double(bytes) / 1_000)
    }
}
