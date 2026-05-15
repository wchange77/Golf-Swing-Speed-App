import SwiftUI
import AVFoundation

struct RecordingGuidanceView: View {
    @Bindable var coordinator: RecordingCoordinator
    @ObservedObject var cameraManager: DatasetCameraManager
    let session: CollectorSessionRecord?

    var body: some View {
        switch coordinator.state {
        case .guidanceStep1:
            GuidanceStep1View(onNext: { coordinator.advanceFromStep1() })
        case .guidanceStep2:
            GuidanceStep2View(
                cameraManager: cameraManager,
                humanDetected: coordinator.humanDetected,
                onHumanDetected: { coordinator.setHumanDetected($0) },
                onNext: { coordinator.advanceFromStep2() }
            )
        case .guidanceStep3:
            GuidanceStep3View(
                coordinator: coordinator,
                cameraManager: cameraManager,
                session: session,
                onStart: { coordinator.startRecording() }
            )
        default:
            EmptyView()
        }
    }
}

private struct GuidanceStep1View: View {
    let onNext: () -> Void

    var body: some View {
        ScrollView {
            VStack(spacing: 32) {
            Image(systemName: "iphone.landscape")
                .font(.system(size: 80))
                .foregroundStyle(.blue)

            Text("第 1 步：摆放手机")
                .font(.title2)
                .fontWeight(.bold)

            VStack(alignment: .leading, spacing: 16) {
                guidanceRow(icon: "camera.on.rectangle", text: "将手机固定在三脚架上")
                guidanceRow(icon: "arrow.left.and.right", text: "距离击球位 3-5 米")
                guidanceRow(icon: "rectangle.landscape", text: "横屏放置，后置摄像头对准击球区")
                guidanceRow(icon: "arrow.up.and.down", text: "手机高度约 1 米（腰部高度）")
                guidanceRow(icon: "sun.max", text: "确保光线充足，避免逆光")
            }
            .padding(.horizontal, 24)

            HStack(spacing: 40) {
                VStack {
                    Image(systemName: "iphone.gen3.landscape")
                        .font(.title)
                    Text("手机")
                        .font(.caption)
                }
                .foregroundStyle(.blue)

                Image(systemName: "arrow.right")
                    .font(.title2)
                    .foregroundStyle(.secondary)

                Text("3-5米")
                    .font(.caption)
                    .foregroundStyle(.secondary)

                Image(systemName: "arrow.right")
                    .font(.title2)
                    .foregroundStyle(.secondary)

                VStack {
                    Image(systemName: "figure.golf")
                        .font(.title)
                    Text("击球位")
                        .font(.caption)
                }
                .foregroundStyle(.green)
            }
            .padding()
            .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 12))

            Button(action: onNext) {
                Text("下一步")
                    .font(.headline)
                    .frame(maxWidth: .infinity)
                    .padding()
            }
            .buttonStyle(.borderedProminent)
            .padding(.horizontal, 24)
            .padding(.bottom, 32)
            }
            .padding(.top, 32)
        }
    }

    private func guidanceRow(icon: String, text: String) -> some View {
        HStack(spacing: 12) {
            Image(systemName: icon)
                .frame(width: 24)
                .foregroundStyle(.blue)
            Text(text)
                .font(.body)
        }
    }
}

private struct GuidanceStep2View: View {
    @ObservedObject var cameraManager: DatasetCameraManager
    let humanDetected: Bool
    let onHumanDetected: (Bool) -> Void
    let onNext: () -> Void

    var body: some View {
        ZStack {
            CameraPreviewView(session: cameraManager.captureSession)
                .ignoresSafeArea()

            VStack {
                VStack(spacing: 8) {
                    Text("第 2 步：确认画面构图")
                        .font(.headline)
                        .foregroundStyle(.white)
                    Text("请把击球位摆进画面中央，光线充足即可")
                        .font(.subheadline)
                        .foregroundStyle(.white.opacity(0.8))
                }
                .padding()
                .background(.black.opacity(0.6), in: RoundedRectangle(cornerRadius: 12))
                .padding(.top, 60)

                Spacer()

                HStack(spacing: 12) {
                    Image(systemName: humanDetected ? "checkmark.circle.fill" : "eye")
                        .font(.title2)
                        .foregroundStyle(humanDetected ? .green : .white)
                    Text(humanDetected ? "已检测到人体（仅参考）" : "无需人体检测，画面就绪即可继续")
                        .font(.subheadline)
                        .foregroundStyle(.white)
                }
                .padding()
                .background(.black.opacity(0.6), in: RoundedRectangle(cornerRadius: 12))

                Button(action: onNext) {
                    Text("下一步")
                        .font(.headline)
                        .frame(maxWidth: .infinity)
                        .padding()
                }
                .buttonStyle(.borderedProminent)
                .padding(.horizontal, 24)
            }
            .padding(.bottom, 32)
        }
        .onChange(of: cameraManager.humanDetected) { _, detected in
            onHumanDetected(detected)
        }
    }
}

private struct GuidanceStep3View: View {
    @Bindable var coordinator: RecordingCoordinator
    @ObservedObject var cameraManager: DatasetCameraManager
    let session: CollectorSessionRecord?
    let onStart: () -> Void

    @StateObject private var lidarManager = LiDARCalibrationManager()
    @State private var isCalibrating: Bool = false

    private var canStart: Bool {
        coordinator.canStartRecording(session: session)
    }

    var body: some View {
        ScrollView {
            VStack(spacing: 24) {
            Image(systemName: "checkmark.seal.fill")
                .font(.system(size: 60))
                .foregroundStyle(.green)

            Text("第 3 步：确认录制参数")
                .font(.title2)
                .fontWeight(.bold)

            VStack(spacing: 16) {
                HStack {
                    Text("采集域")
                        .foregroundStyle(.secondary)
                    Spacer()
                    Text(sessionDomainsText)
                        .fontWeight(.medium)
                }

                HStack {
                    Text("帧率")
                        .foregroundStyle(.secondary)
                    Spacer()
                    Text("240 帧/秒")
                        .fontWeight(.medium)
                }

                HStack {
                    Text("分辨率")
                        .foregroundStyle(.secondary)
                    Spacer()
                    Text("1920×1080")
                        .fontWeight(.medium)
                }

                HStack {
                    Text("场景/光照")
                        .foregroundStyle(.secondary)
                    Spacer()
                    Text("\(session?.environment.sceneType ?? "未记录") / \(session?.environment.lighting ?? "未记录")")
                        .fontWeight(.medium)
                }

                HStack {
                    Text("距离/三脚架")
                        .foregroundStyle(.secondary)
                    Spacer()
                    Text(sessionDistanceText)
                        .fontWeight(.medium)
                }

                Divider()

                Picker("杆型", selection: $coordinator.metadata.clubType) {
                    Text("一号木").tag("driver")
                    Text("三号木").tag("3wood")
                    Text("混合杆").tag("hybrid")
                    Text("铁杆").tag("iron")
                    Text("挖起杆").tag("wedge")
                }

                Picker("手性", selection: $coordinator.metadata.handedness) {
                    Text("右手").tag("right")
                    Text("左手").tag("left")
                }

                Picker("挥速", selection: $coordinator.metadata.swingIntensity) {
                    Text("热身").tag("warmup")
                    Text("正常").tag("normal")
                    Text("全力").tag("max")
                }

                Picker("场地", selection: $coordinator.metadata.surface) {
                    Text("打击垫").tag("mat")
                    Text("草地").tag("grass")
                    Text("室内").tag("indoor")
                    Text("其他").tag("other")
                }

                HStack {
                    Text("相机高度")
                    Spacer()
                    TextField("米", value: $coordinator.metadata.cameraHeightMeters, format: .number)
                        .keyboardType(.decimalPad)
                        .multilineTextAlignment(.trailing)
                        .frame(width: 90)
                }

                HStack {
                    Text("相机俯仰角")
                    Spacer()
                    TextField("度", value: $coordinator.metadata.cameraAngleDegrees, format: .number)
                        .keyboardType(.numbersAndPunctuation)
                        .multilineTextAlignment(.trailing)
                        .frame(width: 90)
                }

                Text("TrackMan/雷达参数在录制结束后填写，此处只需要设置相机与杆型。")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            .padding()
            .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 12))
            .padding(.horizontal, 24)

            lidarCalibrationSection
                .padding(.horizontal, 24)

            if !canStart {
                Text("请确认 3-5 米距离、三脚架、场景/光照和标定基础信息后再录制")
                    .font(.caption)
                    .foregroundStyle(.red)
                    .padding(.horizontal, 24)
            }

            Button(action: onStart) {
                HStack {
                    Image(systemName: "record.circle")
                    Text("开始录制")
                }
                .font(.headline)
                .frame(maxWidth: .infinity)
                .padding()
            }
            .buttonStyle(.borderedProminent)
            .tint(.red)
            .disabled(!canStart)
            .opacity(canStart ? 1 : 0.5)
            .padding(.horizontal, 24)
            .padding(.bottom, 32)
            }
            .padding(.top, 24)
        }
    }

    private var sessionDistanceText: String {
        guard let environment = session?.environment else { return "未记录" }
        let distance = environment.distanceMeters.map { String(format: "%.1f 米", $0) } ?? "未记录"
        return "\(distance) / \(environment.tripod ? "三脚架" : "非三脚架")"
    }

    private var sessionDomainsText: String {
        guard let targets = session?.targetDomains, !targets.isEmpty else { return "未指定" }
        return targets.compactMap { DatasetDomain(rawValue: $0)?.title ?? $0 }.joined(separator: " + ")
    }

    @ViewBuilder
    private var lidarCalibrationSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 8) {
                Image(systemName: "scanner")
                    .foregroundStyle(.blue)
                Text("LiDAR 标定")
                    .font(.headline)
                if coordinator.lidarCalibration != nil {
                    Image(systemName: "checkmark.seal.fill")
                        .foregroundStyle(.green)
                }
                Spacer()
            }

            Text(lidarStatusText)
                .font(.caption)
                .foregroundStyle(.secondary)

            HStack(spacing: 12) {
                Button {
                    runLiDARCalibration()
                } label: {
                    HStack {
                        if isCalibrating {
                            ProgressView().tint(.primary)
                        }
                        Image(systemName: coordinator.lidarCalibration == nil ? "dot.viewfinder" : "arrow.clockwise")
                        Text(coordinator.lidarCalibration == nil ? "执行 LiDAR 标定" : "重新标定")
                    }
                }
                .buttonStyle(.bordered)
                .disabled(isCalibrating || !lidarManager.isSupported)

                if isCalibrating {
                    Button("取消") {
                        lidarManager.cancel()
                        isCalibrating = false
                    }
                    .buttonStyle(.borderless)
                }

                if coordinator.lidarCalibration != nil && !isCalibrating {
                    Button("跳过标定") {
                        coordinator.setLiDARCalibration(nil)
                    }
                    .buttonStyle(.borderless)
                }
            }

            if !lidarManager.isSupported {
                Text("当前设备不支持 ARKit LiDAR，可跳过")
                    .font(.caption2)
                    .foregroundStyle(.orange)
            } else {
                Text("标定会短暂使用相机与地平面检测，完成后自动释放给 240fps 录制。")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            }
        }
        .padding()
        .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 12))
    }

    private var lidarStatusText: String {
        if let data = coordinator.lidarCalibration {
            return String(
                format: "已记录：相机高度 %.2f 米 / 距地 %.2f 米 / 俯仰 %.1f°",
                data.cameraHeight,
                data.cameraToGroundDistance,
                data.cameraAngle
            )
        }
        return lidarManager.status.message
    }

    private func runLiDARCalibration() {
        guard !isCalibrating else { return }
        isCalibrating = true
        cameraManager.stopSession()
        Task {
            let result = await lidarManager.runStaticCalibration()
            if let result {
                coordinator.setLiDARCalibration(result)
            }
            cameraManager.startSession()
            isCalibrating = false
        }
    }
}

struct CameraPreviewView: UIViewRepresentable {
    let session: AVCaptureSession

    func makeUIView(context: Context) -> CameraPreviewUIView {
        let view = CameraPreviewUIView()
        view.backgroundColor = .black
        view.previewLayer.session = session
        view.previewLayer.videoGravity = .resizeAspect
        view.previewLayer.connection?.setDatasetCollectorLandscapeOrientation()
        return view
    }

    func updateUIView(_ uiView: CameraPreviewUIView, context: Context) {
        uiView.previewLayer.session = session
        uiView.previewLayer.videoGravity = .resizeAspect
        uiView.previewLayer.connection?.setDatasetCollectorLandscapeOrientation()
    }
}

final class CameraPreviewUIView: UIView {
    override class var layerClass: AnyClass { AVCaptureVideoPreviewLayer.self }
    var previewLayer: AVCaptureVideoPreviewLayer { layer as! AVCaptureVideoPreviewLayer }

    override func layoutSubviews() {
        super.layoutSubviews()
        backgroundColor = .black
        previewLayer.frame = bounds
        previewLayer.connection?.setDatasetCollectorLandscapeOrientation()
    }
}
