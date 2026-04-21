import SwiftUI

struct DatasetCollectorView: View {
    @StateObject private var viewModel = DatasetCollectorViewModel()
    @State private var selectedTab = 0
    @StateObject private var cameraManager = DatasetCameraManager()
    @State private var coordinator: RecordingCoordinator?
    @State private var registeredSampleIds: [String] = []
    @State private var showPlaybackAnalysis = false

    var body: some View {
        TabView(selection: $selectedTab) {
            sessionTab
                .tabItem {
                    Label("会话", systemImage: "doc.text")
                }
                .tag(0)

            recordingTab
                .tabItem {
                    Label("录制", systemImage: "video.fill")
                }
                .tag(1)

            dataTab
                .tabItem {
                    Label("数据", systemImage: "chart.bar")
                }
                .tag(2)
        }
        .onAppear {
            viewModel.refreshStats()
            viewModel.refreshExportPath()
        }
    }

    // MARK: - Tab 1: 会话

    private var sessionTab: some View {
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

                if let error = viewModel.errorMessage {
                    Section {
                        Text("错误: \(error)")
                            .foregroundStyle(.red)
                    }
                }
            }
            .navigationTitle("会话管理")
        }
    }

    // MARK: - Tab 2: 录制

    private var recordingTab: some View {
        NavigationStack {
            if viewModel.activeSession == nil {
                ContentUnavailableView(
                    "需要先创建会话",
                    systemImage: "exclamationmark.triangle",
                    description: Text("请在「会话」标签页中创建采集会话后再开始录制")
                )
            } else if let coord = coordinator {
                recordingFlowView(coordinator: coord)
            } else {
                VStack(spacing: 20) {
                    Image(systemName: "video.badge.plus")
                        .font(.system(size: 60))
                        .foregroundStyle(.blue)

                    Text("准备开始录制")
                        .font(.title2)

                    Button("进入录制流程") {
                        Task {
                            let granted = await DatasetCameraManager.requestPermission()
                            if granted {
                                try? cameraManager.configure()
                                cameraManager.startSession()
                                let coord = RecordingCoordinator(cameraManager: cameraManager)
                                coordinator = coord
                            } else {
                                viewModel.errorMessage = "相机权限被拒绝，请在设置中开启"
                            }
                        }
                    }
                    .buttonStyle(.borderedProminent)
                }
                .navigationTitle("录制")
            }
        }
    }

    @ViewBuilder
    private func recordingFlowView(coordinator: RecordingCoordinator) -> some View {
        if showPlaybackAnalysis, let videoURL = coordinator.recordedVideoURL {
            VideoPlaybackAnalysisView(videoURL: videoURL) {
                showPlaybackAnalysis = false
            }
        } else {
            switch coordinator.state {
            case .guidanceStep1, .guidanceStep2, .guidanceStep3:
                RecordingGuidanceView(coordinator: coordinator, cameraManager: cameraManager)
            case .countdown, .recording, .validating:
                DatasetRecordingView(coordinator: coordinator, cameraManager: cameraManager)
            case .result(let passed):
                if let result = coordinator.validationResult {
                    RecordingResultView(
                        result: result,
                        registeredSampleIds: registeredSampleIds,
                        videoURL: coordinator.recordedVideoURL,
                        onRetry: { coordinator.retryRecording() },
                        onDone: {
                            coordinator.reset()
                            self.coordinator = nil
                            cameraManager.stopSession()
                        },
                        onPlaybackAnalysis: {
                            showPlaybackAnalysis = true
                        }
                    )
                    .onAppear {
                        if passed {
                            registerSamples(coordinator: coordinator)
                        }
                    }
                }
            }
        }
    }

    private func registerSamples(coordinator: RecordingCoordinator) {
        guard let session = viewModel.activeSession,
              let videoURL = coordinator.recordedVideoURL else { return }

        Task {
            do {
                let depthSamples = cameraManager.capturedDepthSamples
                let samples = try viewModel.service.registerVideoSample(
                    videoURL: videoURL,
                    activeSession: session,
                    clubType: coordinator.metadata.clubType,
                    handedness: coordinator.metadata.handedness,
                    swingIntensity: coordinator.metadata.swingIntensity,
                    depthSamples: depthSamples,
                    lidarCalibration: coordinator.lidarCalibration
                )
                registeredSampleIds = samples.map(\.sampleId)
                viewModel.refreshStats()
            } catch {
                viewModel.errorMessage = error.localizedDescription
            }
        }
    }

    // MARK: - Tab 3: 数据

    private var dataTab: some View {
        DataBrowserView(service: viewModel.service)
    }
}

#Preview {
    DatasetCollectorView()
}
