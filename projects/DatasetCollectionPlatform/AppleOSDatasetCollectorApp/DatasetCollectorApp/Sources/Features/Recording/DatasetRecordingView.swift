import SwiftUI
import AVFoundation

struct DatasetRecordingView: View {
    @Bindable var coordinator: RecordingCoordinator
    @ObservedObject var cameraManager: DatasetCameraManager

    @State private var elapsedTime: TimeInterval = 0
    @State private var timerTask: Task<Void, Never>?

    var body: some View {
        ZStack {
            CameraPreviewView(session: cameraManager.captureSession)
                .ignoresSafeArea()

            switch coordinator.state {
            case .countdown(let seconds):
                countdownOverlay(seconds: seconds)
            case .recording:
                recordingOverlay
            case .validating:
                validatingOverlay
            default:
                EmptyView()
            }
        }
        .onChange(of: coordinator.state) { _, newState in
            if case .recording = newState {
                startTimer()
            } else {
                stopTimer()
            }
        }
    }

    private func countdownOverlay(seconds: Int) -> some View {
        VStack {
            Spacer()

            Text("\(seconds)")
                .font(.system(size: 120, weight: .bold, design: .rounded))
                .foregroundStyle(.white)
                .shadow(radius: 10)

            Text("准备挥杆...")
                .font(.title3)
                .foregroundStyle(.white.opacity(0.8))

            Spacer()
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(.black.opacity(0.4))
    }

    private var recordingOverlay: some View {
        VStack {
            HStack {
                HStack(spacing: 8) {
                    Circle()
                        .fill(.red)
                        .frame(width: 12, height: 12)
                    Text("录制中")
                        .font(.headline)
                        .foregroundStyle(.red)
                }

                Spacer()

                Text(String(format: "%.1f 秒", elapsedTime))
                    .font(.system(.title3, design: .monospaced))
                    .foregroundStyle(.white)
            }
            .padding()
            .background(.black.opacity(0.6), in: RoundedRectangle(cornerRadius: 12))
            .padding(.horizontal)
            .padding(.top, 60)

            Spacer()

            VStack(spacing: 8) {
                Image(systemName: "figure.golf")
                    .font(.system(size: 40))
                    .foregroundStyle(.white.opacity(0.5))
                Text("请挥杆")
                    .font(.title2)
                    .fontWeight(.bold)
                    .foregroundStyle(.white)
                Text("录完后按停止，60 秒安全阀自动截断")
                    .font(.caption)
                    .foregroundStyle(.white.opacity(0.6))
            }

            Spacer()

            Button {
                coordinator.stopRecording()
            } label: {
                HStack {
                    Image(systemName: "stop.fill")
                    Text("停止录制")
                }
                .font(.headline)
                .foregroundStyle(.white)
                .padding(.horizontal, 32)
                .padding(.vertical, 16)
                .background(.red, in: Capsule())
            }
            .padding(.bottom, 40)
        }
    }

    private var validatingOverlay: some View {
        VStack(spacing: 16) {
            ProgressView()
                .scaleEffect(1.5)
                .tint(.white)

            Text("正在验证录制质量...")
                .font(.headline)
                .foregroundStyle(.white)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(.black.opacity(0.6))
    }

    private func startTimer() {
        elapsedTime = 0
        timerTask = Task {
            while !Task.isCancelled {
                try? await Task.sleep(for: .milliseconds(100))
                elapsedTime += 0.1
            }
        }
    }

    private func stopTimer() {
        timerTask?.cancel()
        timerTask = nil
    }
}
