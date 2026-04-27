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
                qualitySection
                calibrationSection
                referenceSection
                sidecarSection
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
            metadataRow("场地", sample.metadata.surface)
            metadataRow("场景", sample.metadata.sceneType ?? "未记录")
            metadataRow("光照", sample.metadata.lighting ?? "未记录")
            metadataRow("相机距离", formatDistance(sample.metadata.distanceMeters))
            metadataRow("帧率", "\(sample.metadata.fps) fps")
            metadataRow("分辨率", sample.metadata.resolution)
            metadataRow("SHA-256", String(sample.sha256.prefix(16)) + "...")
        }
        .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 12))
    }

    private var qualitySection: some View {
        VStack(spacing: 0) {
            metadataRow("质量状态", qualityStatusText)
            metadataRow("质量评分", formatQualityScore(sample.metadata.qualityScore))
            metadataRow("实际帧率", formatFPS(sample.metadata.actualFPS))
            metadataRow("帧数", sample.metadata.frameCount.map(String.init) ?? "未记录")
            metadataRow("时长", formatDuration(sample.metadata.durationSeconds))
            metadataRow("方向", sample.metadata.captureOrientation ?? "未记录")
            metadataRow("标注状态", labelStatusText(sample.metadata.labelStatus))
            metadataRow("导出状态", exportStatusText(sample.metadata.exportStatus))
            metadataRow("元数据完整性", sample.metadata.hasRequiredCaptureMetadata ? "完整" : "缺失")
            if let failed = sample.metadata.qualityFailedChecks, !failed.isEmpty {
                metadataRow("失败项", failed.joined(separator: "、"))
            }
        }
        .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 12))
    }

    private var calibrationSection: some View {
        VStack(spacing: 0) {
            metadataRow("标定状态", calibrationStatusText(sample.metadata.calibrationStatus))
            metadataRow("标定方法", sample.metadata.calibrationMethod ?? "未记录")
            metadataRow("标定来源", sample.metadata.calibrationSource ?? "未记录")
            metadataRow("每米像素", formatPixelsPerMetre(sample.metadata.pixelsPerMetre))
            metadataRow("相机高度", formatDistance(sample.metadata.cameraHeightMeters))
            metadataRow("俯仰角", formatAngle(sample.metadata.cameraAngleDegrees))
        }
        .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 12))
    }

    @ViewBuilder
    private var referenceSection: some View {
        if let measurements = sample.metadata.referenceMeasurements, !measurements.isEmpty {
            VStack(spacing: 0) {
                ForEach(Array(measurements.enumerated()), id: \.offset) { index, measurement in
                    if measurements.count > 1 {
                        metadataRow("参考数据", "#\(index + 1)")
                    }
                    metadataRow("来源", measurement.source)
                    metadataRow("设备", measurement.device ?? "未记录")
                    metadataRow("杆头速度", formatSpeed(measurement.clubSpeedMph))
                    metadataRow("球速", formatSpeed(measurement.ballSpeedMph))
                    metadataRow("Carry", formatDistance(measurement.carryDistanceMeters))
                    metadataRow("总距离", formatDistance(measurement.totalDistanceMeters))
                    metadataRow("起飞角", formatAngle(measurement.launchAngleDegrees))
                    metadataRow("倒旋", formatSpin(measurement.spinRateRpm))
                    if let landing = measurement.landingLocation {
                        metadataRow("落点 GPS", String(format: "%.6f, %.6f", landing.latitude, landing.longitude))
                        metadataRow("落点精度", String(format: "%.1f 米", landing.horizontalAccuracyMeters))
                    }
                    if let notes = measurement.notes, !notes.isEmpty {
                        metadataRow("备注", notes)
                    }
                }
            }
            .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 12))
        }
    }

    private var sidecarSection: some View {
        VStack(spacing: 0) {
            metadataRow("timeline.json", sidecarStatus(sample.metadata.sidecars?.timeline))
            metadataRow("quality.json", sidecarStatus(sample.metadata.sidecars?.quality))
            metadataRow("camera.json", sidecarStatus(sample.metadata.sidecars?.camera))
            metadataRow("label_candidates.json", sidecarStatus(sample.metadata.sidecars?.labelCandidates))
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

    private var qualityStatusText: String {
        guard let passed = sample.metadata.qualityPassed else { return "未记录" }
        return passed ? "合格" : "不合格"
    }

    private func formatQualityScore(_ value: Double?) -> String {
        guard let value else { return "未记录" }
        return String(format: "%.0f%%", value * 100)
    }

    private func formatFPS(_ value: Double?) -> String {
        guard let value else { return "未记录" }
        return String(format: "%.1f fps", value)
    }

    private func formatDuration(_ value: Double?) -> String {
        guard let value else { return "未记录" }
        return String(format: "%.2f 秒", value)
    }

    private func formatDistance(_ value: Double?) -> String {
        guard let value else { return "未记录" }
        return String(format: "%.1f 米", value)
    }

    private func labelStatusText(_ value: String?) -> String {
        switch value {
        case "needs_review": return "待人工复核"
        case "mock": return "模拟样本"
        case .some(let raw): return raw
        case .none: return "未记录"
        }
    }

    private func exportStatusText(_ value: String?) -> String {
        switch value {
        case "ready_for_review_export": return "可导出待复核"
        case "blocked_quality": return "质量未通过"
        case "blocked_calibration": return "缺少标定"
        case "blocked_sidecars": return "缺少 sidecar"
        case "blocked_label_status": return "标注状态未就绪"
        case .some(let raw): return raw
        case .none: return sample.isExportReady ? "可导出" : "未记录"
        }
    }

    private func calibrationStatusText(_ value: String?) -> String {
        switch value {
        case "complete": return "完整"
        case "needs_lidar_review": return "待 LiDAR 复核"
        case "manual_distance_recorded": return "已记录手动距离"
        case "missing": return "缺失"
        case .some(let raw): return raw
        case .none: return "未记录"
        }
    }

    private func sidecarStatus(_ path: String?) -> String {
        guard let path, !path.isEmpty else { return "缺失" }
        return service.exportFileExists(at: path) ? "已生成" : "路径存在但文件缺失"
    }

    private func formatPixelsPerMetre(_ value: Double?) -> String {
        guard let value, value > 0 else { return "未记录" }
        return String(format: "%.0f px/m", value)
    }

    private func formatAngle(_ value: Double?) -> String {
        guard let value else { return "未记录" }
        return String(format: "%.1f°", value)
    }

    private func formatSpeed(_ value: Double?) -> String {
        guard let value else { return "未记录" }
        return String(format: "%.1f mph", value)
    }

    private func formatSpin(_ value: Double?) -> String {
        guard let value else { return "未记录" }
        return String(format: "%.0f rpm", value)
    }
}
