import SwiftUI

struct RecordingResultView: View {
    let result: ValidationResult
    let registeredSampleIds: [String]
    let referenceMeasurements: [CollectorReferenceMeasurement]
    let isSaving: Bool
    let hasSaved: Bool
    let saveStatusMessage: String?
    let saveErrorMessage: String?
    let videoURL: URL?
    let onSave: () -> Void
    let onRetry: () -> Void
    let onDone: () -> Void
    let onPlaybackAnalysis: () -> Void

    var body: some View {
        ScrollView {
            VStack(spacing: 24) {
            if result.passed {
                passedContent
            } else {
                failedContent
            }

            VStack(alignment: .leading, spacing: 8) {
                Text("验证详情")
                    .font(.headline)

                if let metrics = result.metrics {
                    VStack(alignment: .leading, spacing: 4) {
                        Text(String(format: "质量摘要：%.1f fps / %.2f 秒 / %d 帧", metrics.estimatedFPS, metrics.durationSeconds, metrics.frameCount))
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        Text("方向：\(metrics.orientation)，分辨率：\(metrics.videoWidth ?? 0)x\(metrics.videoHeight ?? 0)")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        Text(String(format: "人体覆盖：%.1f%%，欠曝/过曝：%.1f%% / %.1f%%",
                                    (metrics.averageBodyCoverageRatio ?? 0) * 100,
                                    (metrics.underexposedPixelRatio ?? 0) * 100,
                                    (metrics.overexposedPixelRatio ?? 0) * 100))
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    .padding(.bottom, 4)
                }

                ForEach(result.checks) { check in
                    HStack(spacing: 8) {
                        Image(systemName: check.passed ? "checkmark.circle.fill" : "xmark.circle.fill")
                            .foregroundStyle(check.passed ? .green : .red)
                        VStack(alignment: .leading) {
                            Text(check.name)
                                .font(.subheadline)
                                .fontWeight(.medium)
                            Text(check.detail)
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                        Spacer()
                    }
                }
            }
            .padding()
            .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 12))
            .padding(.horizontal, 24)

            if result.passed {
                referencePreviewSection
            }

            if result.passed {
                VStack(spacing: 12) {
                    Button(action: onSave) {
                        HStack {
                            if isSaving {
                                ProgressView()
                                    .tint(.white)
                            } else {
                                Image(systemName: hasSaved ? "checkmark.circle.fill" : "square.and.arrow.down")
                            }
                            Text(hasSaved ? "数据已保存" : "保存数据")
                        }
                        .font(.headline)
                        .frame(maxWidth: .infinity)
                        .padding()
                    }
                    .buttonStyle(.borderedProminent)
                    .tint(hasSaved ? .green : .blue)
                    .disabled(isSaving || hasSaved)
                    .padding(.horizontal, 24)

                    Text("保存会写入视频样本、质量 sidecar，并附带录制前填写的 TrackMan/参考数据。")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .padding(.horizontal, 24)

                    if let saveStatusMessage {
                        Text(saveStatusMessage)
                            .font(.caption)
                            .foregroundStyle(.green)
                            .padding(.horizontal, 24)
                    }

                    if let saveErrorMessage {
                        Text("保存失败: \(saveErrorMessage)")
                            .font(.caption)
                            .foregroundStyle(.red)
                            .padding(.horizontal, 24)
                    }

                    if videoURL != nil {
                        Button(action: onPlaybackAnalysis) {
                            HStack {
                                Image(systemName: "figure.walk")
                                Text("回放骨架分析")
                            }
                            .font(.headline)
                            .frame(maxWidth: .infinity)
                            .padding()
                        }
                        .buttonStyle(.borderedProminent)
                        .tint(.green)
                        .padding(.horizontal, 24)
                    }

                    Button(action: onDone) {
                        Text("完成")
                            .font(.headline)
                            .frame(maxWidth: .infinity)
                            .padding()
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(!hasSaved || isSaving)
                    .opacity(hasSaved && !isSaving ? 1 : 0.5)
                    .padding(.horizontal, 24)
                }
            } else {
                VStack(spacing: 12) {
                    Button(action: onRetry) {
                        HStack {
                            Image(systemName: "arrow.clockwise")
                            Text("重新录制")
                        }
                        .font(.headline)
                        .frame(maxWidth: .infinity)
                        .padding()
                    }
                    .buttonStyle(.borderedProminent)
                    .tint(.red)

                    if videoURL != nil {
                        Button(action: onPlaybackAnalysis) {
                            HStack {
                                Image(systemName: "figure.walk")
                                Text("回放骨架分析")
                            }
                            .font(.subheadline)
                            .foregroundStyle(.blue)
                        }
                    }

                    Button(action: onDone) {
                        Text("返回")
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                    }
                }
                .padding(.horizontal, 24)
            }

            Spacer().frame(height: 32)
            }
            .padding(.top, 24)
        }
    }

    private var referencePreviewSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("将保存的 TrackMan/参考数据")
                .font(.headline)

            if referenceMeasurements.isEmpty {
                Text("未填写 TrackMan/参考数据；保存后样本不会包含参考测量。")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            } else {
                ForEach(Array(referenceMeasurements.enumerated()), id: \.offset) { index, measurement in
                    if referenceMeasurements.count > 1 {
                        Text("参考数据 #\(index + 1)")
                            .font(.subheadline)
                            .fontWeight(.medium)
                    }
                    referenceRow("来源", sourceTitle(measurement.source))
                    referenceRow("设备", measurement.device ?? "未记录")
                    referenceRow("杆头速度", formatSpeed(measurement.clubSpeedMph))
                    referenceRow("球速", formatSpeed(measurement.ballSpeedMph))
                    referenceRow("Carry", formatDistance(measurement.carryDistanceMeters))
                    referenceRow("总距离", formatDistance(measurement.totalDistanceMeters))
                    referenceRow("起飞角", formatAngle(measurement.launchAngleDegrees))
                    referenceRow("倒旋", formatSpin(measurement.spinRateRpm))
                    if let notes = measurement.notes, !notes.isEmpty {
                        referenceRow("备注", notes)
                    }
                }
            }
        }
        .padding()
        .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 12))
        .padding(.horizontal, 24)
    }

    private var passedContent: some View {
        VStack(spacing: 16) {
            Image(systemName: "checkmark.circle.fill")
                .font(.system(size: 80))
                .foregroundStyle(.green)

            Text("样本合格")
                .font(.title)
                .fontWeight(.bold)

            if hasSaved && !registeredSampleIds.isEmpty {
                VStack(spacing: 4) {
                    Text("已登记到两个域：")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                    ForEach(registeredSampleIds, id: \.self) { id in
                        Text(id)
                            .font(.caption)
                            .fontWeight(.medium)
                            .padding(.horizontal, 8)
                            .padding(.vertical, 2)
                        .background(.green.opacity(0.1), in: Capsule())
                    }
                }
            } else if hasSaved {
                Text("该视频与已有样本重复，已写入重复记录")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            } else {
                Text("验证通过，点击「保存数据」后写入数据集")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }
        }
    }

    private var failedContent: some View {
        VStack(spacing: 16) {
            Image(systemName: "xmark.circle.fill")
                .font(.system(size: 80))
                .foregroundStyle(.red)

            Text("样本不合格")
                .font(.title)
                .fontWeight(.bold)

            Text("请根据以下原因调整后重新录制")
                .font(.subheadline)
                .foregroundStyle(.secondary)
        }
    }

    private func referenceRow(_ label: String, _ value: String) -> some View {
        HStack {
            Text(label)
                .font(.caption)
                .foregroundStyle(.secondary)
            Spacer()
            Text(value)
                .font(.caption)
                .fontWeight(.medium)
                .multilineTextAlignment(.trailing)
        }
    }

    private func sourceTitle(_ source: String) -> String {
        source == "trackman_manual" ? "TrackMan 手动录入" : "参考设备手动录入"
    }

    private func formatSpeed(_ value: Double?) -> String {
        formatMeasurement(value, unit: "mph")
    }

    private func formatDistance(_ value: Double?) -> String {
        formatMeasurement(value, unit: "米")
    }

    private func formatAngle(_ value: Double?) -> String {
        formatMeasurement(value, unit: "度")
    }

    private func formatSpin(_ value: Double?) -> String {
        guard let value else { return "未记录" }
        return String(format: "%.0f rpm", value)
    }

    private func formatMeasurement(_ value: Double?, unit: String) -> String {
        guard let value else { return "未记录" }
        return String(format: "%.1f %@", value, unit)
    }
}
