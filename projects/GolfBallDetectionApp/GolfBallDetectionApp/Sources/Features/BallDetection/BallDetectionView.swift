import SwiftUI
import PhotosUI
import GolfAnalysisKit

struct BallDetectionView: View {
    @StateObject private var viewModel = BallDetectionViewModel()
    @State private var showingVideoPicker = false
    @State private var showingReplay = false

    var body: some View {
        NavigationStack {
            List {
                Section("视频分析") {
                    Button("选择视频") {
                        showingVideoPicker = true
                    }
                    .disabled(viewModel.isAnalyzing)

                    Picker("球杆", selection: $viewModel.selectedClub) {
                        ForEach(ClubType.allCases, id: \.self) { club in
                            Text(club.rawValue).tag(club)
                        }
                    }

                    if viewModel.isAnalyzing {
                        ProgressView(value: viewModel.analysisProgress) {
                            Text(viewModel.statusMessage)
                                .font(.caption)
                        }
                    } else if !viewModel.statusMessage.isEmpty {
                        Text(viewModel.statusMessage)
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                    }
                }

                if viewModel.prediction != nil || viewModel.ballFlightMetrics != nil {
                    Section("弹道概览") {
                        FlightDataPanel(
                            prediction: viewModel.prediction,
                            ballFlightMetrics: viewModel.ballFlightMetrics,
                            isExpanded: false
                        )
                        .listRowInsets(EdgeInsets())
                        .listRowBackground(Color.clear)

                        if viewModel.selectedVideoURL != nil {
                            Button("查看回放 + 轨迹叠加") {
                                showingReplay = true
                            }
                        }
                    }
                }

                Section("数据集状态") {
                    Text(viewModel.manifestSummary)
                        .font(.footnote)
                }

                Section("检测结果 (\(viewModel.records.count))") {
                    if viewModel.records.isEmpty {
                        Text("暂无检测结果")
                            .foregroundStyle(.secondary)
                    } else {
                        ForEach(viewModel.records.suffix(100)) { record in
                            VStack(alignment: .leading, spacing: 4) {
                                HStack {
                                    Text("帧 \(record.frameIndex)")
                                        .font(.footnote.bold())
                                    Spacer()
                                    Text(record.source)
                                        .font(.caption2)
                                        .padding(.horizontal, 6)
                                        .padding(.vertical, 2)
                                        .background(.blue.opacity(0.15))
                                        .clipShape(Capsule())
                                }
                                Text("置信度: \(record.confidence, specifier: "%.2f")  位置: (\(record.centerX, specifier: "%.0f"), \(record.centerY, specifier: "%.0f"))  半径: \(record.radius, specifier: "%.1f")")
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                        }
                    }
                }
            }
            .navigationTitle("高尔夫球检测")
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button("刷新清单") {
                        viewModel.refreshManifestSummary()
                    }
                }
            }
            .sheet(isPresented: $showingVideoPicker) {
                VideoPickerView { url in
                    if let url {
                        viewModel.analyzeVideo(url: url)
                    }
                }
            }
            .navigationDestination(isPresented: $showingReplay) {
                if let url = viewModel.selectedVideoURL {
                    VideoReplayView(
                        videoURL: url,
                        detectionRecords: viewModel.records,
                        prediction: viewModel.prediction,
                        ballFlightMetrics: viewModel.ballFlightMetrics
                    )
                }
            }
        }
    }
}

struct VideoPickerView: UIViewControllerRepresentable {
    let onPick: (URL?) -> Void

    func makeUIViewController(context: Context) -> UIImagePickerController {
        let picker = UIImagePickerController()
        picker.sourceType = .photoLibrary
        picker.mediaTypes = ["public.movie"]
        picker.delegate = context.coordinator
        return picker
    }

    func updateUIViewController(_ uiViewController: UIImagePickerController, context: Context) {}

    func makeCoordinator() -> Coordinator { Coordinator(onPick: onPick) }

    class Coordinator: NSObject, UIImagePickerControllerDelegate, UINavigationControllerDelegate {
        let onPick: (URL?) -> Void
        init(onPick: @escaping (URL?) -> Void) { self.onPick = onPick }

        func imagePickerController(_ picker: UIImagePickerController, didFinishPickingMediaWithInfo info: [UIImagePickerController.InfoKey: Any]) {
            let url = info[.mediaURL] as? URL
            picker.dismiss(animated: true)
            onPick(url)
        }

        func imagePickerControllerDidCancel(_ picker: UIImagePickerController) {
            picker.dismiss(animated: true)
            onPick(nil)
        }
    }
}

#Preview {
    BallDetectionView()
}
