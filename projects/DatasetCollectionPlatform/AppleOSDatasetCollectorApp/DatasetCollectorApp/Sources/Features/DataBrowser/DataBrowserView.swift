import SwiftUI

struct DataBrowserView: View {
    let service: DatasetCollectorService
    @State private var samples: [CollectorSampleRecord] = []
    @State private var sessions: [CollectorSessionRecord] = []
    @State private var selectedDomain: String? = nil
    @State private var selectedSession: String? = nil
    @State private var selectedQuality: String? = nil
    @State private var showDeleteAlert = false
    @State private var sampleToDelete: CollectorSampleRecord?
    @State private var selectedSample: CollectorSampleRecord?
    @State private var errorMessage: String?

    var filteredSamples: [CollectorSampleRecord] {
        samples.filter { sample in
            if let domain = selectedDomain, sample.domain != domain { return false }
            if let session = selectedSession, sample.sessionId != session { return false }
            if let selectedQuality {
                switch selectedQuality {
                case "passed":
                    if sample.metadata.qualityPassed != true { return false }
                case "failed":
                    if sample.metadata.qualityPassed != false { return false }
                case "needs_review":
                    if sample.metadata.labelStatus != "needs_review" { return false }
                case "export_ready":
                    if !sample.isExportReady { return false }
                default:
                    break
                }
            }
            return true
        }
    }

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                filterBar
                sampleList
            }
            .navigationTitle("数据集")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Text("\(filteredSamples.count) 条")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            .onAppear { loadData() }
            .alert("确认删除", isPresented: $showDeleteAlert) {
                Button("取消", role: .cancel) {}
                Button("删除", role: .destructive) {
                    if let sample = sampleToDelete {
                        deleteSample(sample)
                    }
                }
            } message: {
                Text("删除后无法恢复，确定要删除此样本？")
            }
            .sheet(item: $selectedSample) { sample in
                SampleDetailView(sample: sample, service: service) {
                    selectedSample = nil
                    loadData()
                }
            }
        }
    }

    private var filterBar: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                FilterChip(title: "全部", isSelected: selectedDomain == nil) {
                    selectedDomain = nil
                }
                FilterChip(title: "人体+球杆", isSelected: selectedDomain == "human_club") {
                    selectedDomain = "human_club"
                }
                FilterChip(title: "球检测", isSelected: selectedDomain == "golf_ball_detection") {
                    selectedDomain = "golf_ball_detection"
                }

                Divider().frame(height: 20)

                FilterChip(title: "待复核", isSelected: selectedQuality == "needs_review") {
                    selectedQuality = selectedQuality == "needs_review" ? nil : "needs_review"
                }
                FilterChip(title: "合格", isSelected: selectedQuality == "passed") {
                    selectedQuality = selectedQuality == "passed" ? nil : "passed"
                }
                FilterChip(title: "不合格", isSelected: selectedQuality == "failed") {
                    selectedQuality = selectedQuality == "failed" ? nil : "failed"
                }
                FilterChip(title: "可导出", isSelected: selectedQuality == "export_ready") {
                    selectedQuality = selectedQuality == "export_ready" ? nil : "export_ready"
                }

                Divider().frame(height: 20)

                if !sessions.isEmpty {
                    Menu {
                        Button("全部会话") { selectedSession = nil }
                        ForEach(sessions) { session in
                            Button(session.sessionId.prefix(12) + "...") {
                                selectedSession = session.sessionId
                            }
                        }
                    } label: {
                        HStack(spacing: 4) {
                            Image(systemName: "line.3.horizontal.decrease.circle")
                            Text(selectedSession == nil ? "会话" : "已筛选")
                        }
                        .font(.caption)
                        .padding(.horizontal, 10)
                        .padding(.vertical, 6)
                        .background(.ultraThinMaterial, in: Capsule())
                    }
                }
            }
            .padding(.horizontal)
            .padding(.vertical, 8)
        }
    }

    private var sampleList: some View {
        Group {
            if filteredSamples.isEmpty {
                ContentUnavailableView(
                    "暂无样本",
                    systemImage: "tray",
                    description: Text("录制完成后样本会显示在这里")
                )
            } else {
                List {
                    ForEach(filteredSamples) { sample in
                        SampleRowView(sample: sample)
                            .contentShape(Rectangle())
                            .onTapGesture {
                                selectedSample = sample
                            }
                    }
                    .onDelete { indexSet in
                        if let index = indexSet.first {
                            sampleToDelete = filteredSamples[index]
                            showDeleteAlert = true
                        }
                    }
                }
                .listStyle(.plain)
            }
        }
    }

    private func loadData() {
        do {
            samples = try service.loadAllSamples()
            sessions = try service.loadAllSessions()
            errorMessage = nil
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func deleteSample(_ sample: CollectorSampleRecord) {
        do {
            try service.deleteSample(sampleId: sample.sampleId)
            loadData()
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}

private struct FilterChip: View {
    let title: String
    let isSelected: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Text(title)
                .font(.caption)
                .fontWeight(isSelected ? .semibold : .regular)
                .padding(.horizontal, 12)
                .padding(.vertical, 6)
                .background(isSelected ? Color.blue : Color.clear, in: Capsule())
                .foregroundStyle(isSelected ? .white : .primary)
                .overlay(Capsule().stroke(isSelected ? Color.clear : Color.gray.opacity(0.3)))
        }
    }
}

private struct SampleRowView: View {
    let sample: CollectorSampleRecord

    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: sample.domain == "human_club" ? "figure.golf" : "circle.fill")
                .font(.title3)
                .foregroundStyle(sample.domain == "human_club" ? .blue : .orange)
                .frame(width: 32)

            VStack(alignment: .leading, spacing: 4) {
                Text(sample.sampleId.prefix(20) + "...")
                    .font(.subheadline)
                    .fontWeight(.medium)
                    .lineLimit(1)

                HStack(spacing: 8) {
                    Label(sample.metadata.clubType, systemImage: "sportscourt")
                    Label(sample.metadata.handedness == "right" ? "右手" : "左手", systemImage: "hand.raised")
                    Label(qualityLabel, systemImage: qualityIcon)
                }
                .font(.caption2)
                .foregroundStyle(.secondary)
            }

            Spacer()

            VStack(alignment: .trailing, spacing: 4) {
                Text(formatFileSize(sample.fileSize))
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Text(formatDate(sample.capturedAt))
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
            }
        }
        .padding(.vertical, 4)
    }

    private func formatFileSize(_ bytes: Int) -> String {
        if bytes > 1_000_000 {
            return String(format: "%.1f MB", Double(bytes) / 1_000_000)
        } else if bytes > 1_000 {
            return String(format: "%.0f KB", Double(bytes) / 1_000)
        }
        return "\(bytes) B"
    }

    private func formatDate(_ iso: String) -> String {
        String(iso.prefix(16).replacingOccurrences(of: "T", with: " "))
    }

    private var qualityLabel: String {
        if sample.metadata.labelStatus == "needs_review" {
            return sample.isExportReady ? "可导出" : "待复核"
        }
        guard let passed = sample.metadata.qualityPassed else {
            return "未验证"
        }
        return passed ? "合格" : "不合格"
    }

    private var qualityIcon: String {
        if sample.metadata.labelStatus == "needs_review" {
            return sample.isExportReady ? "square.and.arrow.up" : "tag"
        }
        guard let passed = sample.metadata.qualityPassed else {
            return "questionmark.circle"
        }
        return passed ? "checkmark.seal" : "exclamationmark.triangle"
    }
}
