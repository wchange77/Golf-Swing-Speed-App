import SwiftUI

struct DatasetCollectorView: View {
    @StateObject private var viewModel = DatasetCollectorViewModel()
    @StateObject private var locationManager = DatasetLocationManager()
    @State private var selectedTab = 0
    @StateObject private var cameraManager = DatasetCameraManager()
    @State private var coordinator: RecordingCoordinator?
    @State private var registeredSampleIds: [String] = []
    @State private var isSavingRecording = false
    @State private var hasSavedRecording = false
    @State private var saveStatusMessage: String?
    @State private var saveErrorMessage: String?
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
            locationManager.requestPermissionAndLocation()
        }
    }

    // MARK: - Tab 1: 会话

    private var sessionTab: some View {
        NavigationStack {
            Form {
                Section("会话配置") {
                    TextField("会话名称（如 1、2、3）", text: $viewModel.sessionName)
                        .keyboardType(.numbersAndPunctuation)
                    TextField("采集人", text: $viewModel.collector)
                    TextField("设备", text: $viewModel.device)
                    TextField("设备档案", text: $viewModel.deviceProfile)
                    TextField("iOS 版本", text: $viewModel.iosVersion)
                    TextField("App 版本", text: $viewModel.appVersion)
                    TextField("场景类型", text: $viewModel.sceneType)
                    TextField("光照", text: $viewModel.lighting)
                    Toggle("三脚架", isOn: $viewModel.tripod)
                    TextField("相机距离（米）", value: $viewModel.distanceMeters, format: .number)
                        .keyboardType(.decimalPad)
                    TextField("备注", text: $viewModel.notes, axis: .vertical)
                }

                Section("会话控制") {
                    Button("创建采集会话") {
                        locationManager.requestLocation()
                        viewModel.createSession(location: locationManager.latestLocation)
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(!viewModel.canCreateSession || locationManager.latestLocation == nil)

                    if !viewModel.canCreateSession {
                        Text(viewModel.sessionValidationMessage)
                            .font(.caption)
                            .foregroundStyle(.red)
                    } else if locationManager.latestLocation == nil {
                        Text("创建会话前必须获取当前 GPS 定位")
                            .font(.caption)
                            .foregroundStyle(.red)
                    }

                    if let session = viewModel.activeSession {
                        Text("当前会话: \(session.sessionName ?? session.sessionId)")
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                        if let location = session.location {
                            Text(String(format: "GPS: %.6f, %.6f / 精度 %.1f 米", location.latitude, location.longitude, location.horizontalAccuracyMeters))
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                    } else {
                        Text("尚未创建会话")
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                    }

                    Text(locationManager.statusText)
                        .font(.caption)
                        .foregroundStyle(.secondary)
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
                                resetRecordingSaveState()
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
                RecordingGuidanceView(
                    coordinator: coordinator,
                    cameraManager: cameraManager,
                    session: viewModel.activeSession
                )
            case .countdown, .recording, .validating:
                DatasetRecordingView(coordinator: coordinator, cameraManager: cameraManager)
            case .result:
                if let result = coordinator.validationResult {
                    RecordingResultView(
                        result: result,
                        registeredSampleIds: registeredSampleIds,
                        referenceMeasurements: coordinator.referenceMeasurements,
                        isSaving: isSavingRecording,
                        hasSaved: hasSavedRecording,
                        saveStatusMessage: saveStatusMessage,
                        saveErrorMessage: saveErrorMessage,
                        videoURL: coordinator.recordedVideoURL,
                        onSave: { saveRecordingSamples(coordinator: coordinator) },
                        onRetry: {
                            coordinator.retryRecording()
                            resetRecordingSaveState()
                        },
                        onDone: {
                            coordinator.reset()
                            self.coordinator = nil
                            cameraManager.stopSession()
                            resetRecordingSaveState()
                        },
                        onPlaybackAnalysis: {
                            showPlaybackAnalysis = true
                        }
                    )
                }
            }
        }
    }

    private func saveRecordingSamples(coordinator: RecordingCoordinator) {
        guard !isSavingRecording, !hasSavedRecording else { return }
        guard let session = viewModel.activeSession,
              let videoURL = coordinator.recordedVideoURL else {
            saveErrorMessage = "缺少会话或录制视频，无法保存"
            return
        }

        isSavingRecording = true
        saveStatusMessage = nil
        saveErrorMessage = nil
        Task {
            defer { isSavingRecording = false }
            do {
                let depthSamples = cameraManager.capturedDepthSamples
                let samples = try viewModel.service.registerVideoSample(
                    videoURL: videoURL,
                    activeSession: session,
                    clubType: coordinator.metadata.clubType,
                    handedness: coordinator.metadata.handedness,
                    swingIntensity: coordinator.metadata.swingIntensity,
                    surface: coordinator.metadata.surface,
                    cameraHeightMeters: coordinator.metadata.cameraHeightMeters,
                    cameraAngleDegrees: coordinator.metadata.cameraAngleDegrees,
                    validationResult: coordinator.validationResult,
                    captureTimestamps: cameraManager.capturedTimestamps,
                    depthSamples: depthSamples,
                    lidarCalibration: coordinator.lidarCalibration,
                    hasLiDAR: cameraManager.hasLiDAR,
                    referenceMeasurements: coordinator.referenceMeasurements
                )
                registeredSampleIds = samples.map(\.sampleId)
                hasSavedRecording = true
                saveStatusMessage = samples.isEmpty
                    ? "视频与已有样本重复，已记录重复项"
                    : "已保存视频、质量记录和 TrackMan/参考数据"
                viewModel.refreshStats()
            } catch {
                saveErrorMessage = error.localizedDescription
                viewModel.errorMessage = error.localizedDescription
            }
        }
    }

    private func resetRecordingSaveState() {
        registeredSampleIds = []
        isSavingRecording = false
        hasSavedRecording = false
        saveStatusMessage = nil
        saveErrorMessage = nil
    }

    // MARK: - Tab 3: 数据

    private var dataTab: some View {
        DataBrowserView(service: viewModel.service)
    }
}

#Preview {
    DatasetCollectorView()
}
