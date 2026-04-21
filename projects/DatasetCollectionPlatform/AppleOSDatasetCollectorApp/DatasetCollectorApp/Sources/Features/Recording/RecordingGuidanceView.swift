import SwiftUI
import AVFoundation

struct RecordingGuidanceView: View {
    @Bindable var coordinator: RecordingCoordinator
    @ObservedObject var cameraManager: DatasetCameraManager

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
        VStack(spacing: 32) {
            Spacer()

            Image(systemName: "iphone.landscape")
                .font(.system(size: 80))
                .foregroundStyle(.blue)

            Text("第 1 步：摆放手机")
                .font(.title2)
                .fontWeight(.bold)

            VStack(alignment: .leading, spacing: 16) {
                guidanceRow(icon: "camera.on.rectangle", text: "将手机固定在三脚架上")
                guidanceRow(icon: "arrow.left.and.right", text: "距离击球位 2-3 米")
                guidanceRow(icon: "rectangle.landscape", text: "横屏放置，后置摄像头对准击球区")
                guidanceRow(icon: "arrow.up.and.down", text: "手机高度约 1 米（腰部高度）")
                guidanceRow(icon: "sun.max", text: "确保光线充足，避免逆光")
            }
            .padding(.horizontal, 24)

            Spacer()

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

                Text("2-3米")
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

            Spacer()

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

            if !humanDetected {
                VStack {
                    Spacer()
                    Image(systemName: "figure.stand")
                        .font(.system(size: 120))
                        .foregroundStyle(.white.opacity(0.3))
                    Spacer()
                }
            }

            VStack {
                VStack(spacing: 8) {
                    Text("第 2 步：确认人在画面中")
                        .font(.headline)
                        .foregroundStyle(.white)
                    Text("请让挥杆者站到画面中央")
                        .font(.subheadline)
                        .foregroundStyle(.white.opacity(0.8))
                }
                .padding()
                .background(.black.opacity(0.6), in: RoundedRectangle(cornerRadius: 12))
                .padding(.top, 60)

                Spacer()

                HStack(spacing: 12) {
                    Image(systemName: humanDetected ? "checkmark.circle.fill" : "xmark.circle")
                        .font(.title2)
                        .foregroundStyle(humanDetected ? .green : .red)
                    Text(humanDetected ? "已检测到人体" : "未检测到人体，请站入画面")
                        .font(.headline)
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

                if !humanDetected {
                    Button(action: onNext) {
                        Text("跳过检测")
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                    }
                }
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
    let onStart: () -> Void

    var body: some View {
        VStack(spacing: 24) {
            Spacer()

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
                    Text("人体球杆 + 球检测")
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
            }
            .padding()
            .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 12))
            .padding(.horizontal, 24)

            Spacer()

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
            .padding(.horizontal, 24)
            .padding(.bottom, 32)
        }
    }
}

struct CameraPreviewView: UIViewRepresentable {
    let session: AVCaptureSession

    func makeUIView(context: Context) -> CameraPreviewUIView {
        let view = CameraPreviewUIView()
        view.previewLayer.session = session
        view.previewLayer.videoGravity = .resizeAspectFill
        return view
    }

    func updateUIView(_ uiView: CameraPreviewUIView, context: Context) {}
}

final class CameraPreviewUIView: UIView {
    override class var layerClass: AnyClass { AVCaptureVideoPreviewLayer.self }
    var previewLayer: AVCaptureVideoPreviewLayer { layer as! AVCaptureVideoPreviewLayer }
}
