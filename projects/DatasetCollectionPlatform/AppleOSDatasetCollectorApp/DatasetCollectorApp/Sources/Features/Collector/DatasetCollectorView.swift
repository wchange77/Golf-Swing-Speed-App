import SwiftUI

struct DatasetCollectorView: View {
    @StateObject private var viewModel = DatasetCollectorViewModel()

    var body: some View {
        NavigationStack {
            Form {
                Section("会话配置") {
                    TextField("采集人", text: $viewModel.collector)
                    TextField("设备", text: $viewModel.device)
                    TextField("设备档案", text: $viewModel.deviceProfile)
                    TextField("iOS 版本", text: $viewModel.iosVersion)
                    TextField("App 版本", text: $viewModel.appVersion)
                    TextField("场景类型", text: $viewModel.sceneType)
                    TextField("光照", text: $viewModel.lighting)
                    Toggle("三脚架", isOn: $viewModel.tripod)
                    TextField("备注", text: $viewModel.notes, axis: .vertical)
                }

                Section("会话控制") {
                    Button("创建采集会话") {
                        viewModel.createSession()
                    }
                    .buttonStyle(.borderedProminent)

                    if let session = viewModel.activeSession {
                        Text("当前会话: \(session.sessionId)")
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                    } else {
                        Text("尚未创建会话")
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                    }
                }

                Section("样本采集（模拟）") {
                    Button("登记 human_club 样本") {
                        viewModel.addHumanClubSample()
                    }
                    Button("登记 golf_ball_detection 样本") {
                        viewModel.addBallSample()
                    }
                    Button("制造一次重复样本") {
                        viewModel.addIntentionalDuplicate()
                    }
                }

                Section("状态") {
                    Text(viewModel.statsSummary)
                    Text("导出目录: \(viewModel.exportPath)")
                        .font(.footnote)
                        .textSelection(.enabled)
                    if let error = viewModel.errorMessage {
                        Text("错误: \(error)")
                            .foregroundStyle(.red)
                    }
                }

                Section("操作日志") {
                    if viewModel.logs.isEmpty {
                        Text("暂无日志")
                            .foregroundStyle(.secondary)
                    } else {
                        ForEach(viewModel.logs, id: \.self) { line in
                            Text(line)
                                .font(.caption2)
                                .textSelection(.enabled)
                        }
                    }
                }
            }
            .navigationTitle("Dataset Collector")
            .onAppear {
                viewModel.refreshStats()
                viewModel.refreshExportPath()
            }
        }
    }
}

#Preview {
    DatasetCollectorView()
}
