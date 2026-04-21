import SwiftUI

struct RecordingResultView: View {
    let result: ValidationResult
    let registeredSampleIds: [String]
    let videoURL: URL?
    let onRetry: () -> Void
    let onDone: () -> Void
    let onPlaybackAnalysis: () -> Void

    var body: some View {
        VStack(spacing: 24) {
            Spacer()

            if result.passed {
                passedContent
            } else {
                failedContent
            }

            Spacer()

            VStack(alignment: .leading, spacing: 8) {
                Text("验证详情")
                    .font(.headline)

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

            Spacer()

            if result.passed {
                VStack(spacing: 12) {
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
    }

    private var passedContent: some View {
        VStack(spacing: 16) {
            Image(systemName: "checkmark.circle.fill")
                .font(.system(size: 80))
                .foregroundStyle(.green)

            Text("样本合格")
                .font(.title)
                .fontWeight(.bold)

            if !registeredSampleIds.isEmpty {
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
}
