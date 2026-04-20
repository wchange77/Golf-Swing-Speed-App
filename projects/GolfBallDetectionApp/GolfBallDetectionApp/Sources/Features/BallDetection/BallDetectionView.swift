import SwiftUI

struct BallDetectionView: View {
    @StateObject private var viewModel = BallDetectionViewModel()

    var body: some View {
        NavigationStack {
            List {
                Section("数据集状态") {
                    Text(viewModel.manifestSummary)
                        .font(.footnote)
                    Text("Manifest 路径: \(BallDatasetBridge.manifestPath())")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }

                Section("检测记录") {
                    if viewModel.records.isEmpty {
                        Text("暂无检测结果")
                            .foregroundStyle(.secondary)
                    } else {
                        ForEach(viewModel.records) { record in
                            VStack(alignment: .leading, spacing: 4) {
                                Text(record.timestamp, style: .time)
                                Text("置信度: \(record.confidence, specifier: "%.2f")  圆心: (\(record.centerX, specifier: "%.2f"), \(record.centerY, specifier: "%.2f"))")
                                    .font(.footnote)
                                    .foregroundStyle(.secondary)
                            }
                        }
                    }
                }
            }
            .navigationTitle("高尔夫球检测")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button(viewModel.isSessionRunning ? "停止" : "开始") {
                        viewModel.toggleSession()
                    }
                }
                ToolbarItem(placement: .topBarLeading) {
                    Button("刷新清单") {
                        viewModel.refreshManifestSummary()
                    }
                }
            }
        }
    }
}

#Preview {
    BallDetectionView()
}
