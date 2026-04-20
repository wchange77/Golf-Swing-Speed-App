import SwiftUI

/// Displays the results of automated post-capture swing analysis.
///
/// Shown after `PostCaptureAnalysisEngine` finishes processing a captured swing video.
/// Presents the impact speed prominently, a speed curve chart, analysis metadata
/// (frames analysed, processing time, confidence), and lag metrics when available.
///
/// The user can save the result, open manual frame analysis for review, or discard.
struct AnalysisResultView: View {
    let result: PostCaptureAnalysisEngine.AnalysisResult
    let videoURL: URL
    let calibration: CalibrationSnapshot
    let clubType: ClubType

    /// Called when the user taps "Save & Close" — parent should persist the swing record.
    var onSave: (() -> Void)?
    /// Called when the user taps "Discard" — parent should clean up the recording.
    var onDiscard: (() -> Void)?
    /// Called when the user taps "View Frames" — parent should present FrameAnalysisView.
    var onViewFrames: (() -> Void)?

    @Environment(\.dismiss) private var dismiss
    @State private var showDiscardConfirmation = false

    var body: some View {
        ScrollView {
            VStack(spacing: 24) {
                // MARK: - Impact Speed Headline
                speedHeadline

                // MARK: - Speed Curve Chart
                speedCurveSection

                // MARK: - Analysis Details
                analysisDetailsSection

                // MARK: - Lag Analysis
                if let lagMetrics = result.lagMetrics {
                    lagAnalysisSection(lagMetrics)
                }

                // MARK: - Action Buttons
                actionButtons
            }
            .padding()
        }
        .background(Color.black.ignoresSafeArea())
        .preferredColorScheme(.dark)
        .confirmationDialog(
            "Discard this swing?",
            isPresented: $showDiscardConfirmation,
            titleVisibility: .visible
        ) {
            Button("Discard", role: .destructive) {
                onDiscard?()
                dismiss()
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("The recorded video and analysis data will be deleted.")
        }
    }

    // MARK: - Speed Headline

    private var speedHeadline: some View {
        VStack(spacing: 8) {
            if let speed = result.impactSpeedMph {
                Text(speed.formattedSpeed)
                    .font(.system(size: 72, weight: .bold, design: .rounded))
                    .foregroundStyle(.white)

                Text("mph at impact")
                    .font(.title3)
                    .foregroundStyle(.gray)
            } else {
                Text("--")
                    .font(.system(size: 72, weight: .bold, design: .rounded))
                    .foregroundStyle(.white.opacity(0.4))

                Text("Speed not detected")
                    .font(.title3)
                    .foregroundStyle(.gray)
            }

            HStack(spacing: 12) {
                Label(clubType.displayName, systemImage: "figure.golf")
                    .font(.subheadline)
                    .foregroundStyle(.white.opacity(0.8))

                Spacer()

                confidenceBadge
            }
        }
        .padding()
        .background(Color.white.opacity(0.08), in: RoundedRectangle(cornerRadius: 16))
    }

    // MARK: - Speed Curve Section

    private var speedCurveSection: some View {
        Group {
            if let profile = result.speedProfile, !profile.isEmpty {
                SpeedCurveChart(profile: profile)
            } else {
                noSpeedDataPlaceholder
            }
        }
    }

    private var noSpeedDataPlaceholder: some View {
        VStack(spacing: 12) {
            Text("Speed Curve")
                .font(.headline)
                .foregroundStyle(.white)
                .frame(maxWidth: .infinity, alignment: .leading)

            RoundedRectangle(cornerRadius: 12)
                .fill(Color.white.opacity(0.05))
                .frame(height: 200)
                .overlay {
                    VStack(spacing: 8) {
                        Image(systemName: "waveform.path.ecg")
                            .font(.largeTitle)
                            .foregroundStyle(.gray)

                        Text("Not enough tracking data for a speed curve.")
                            .font(.subheadline)
                            .foregroundStyle(.gray)

                        Text("Try View Frames to manually mark club positions.")
                            .font(.caption)
                            .foregroundStyle(.gray.opacity(0.7))
                    }
                }
        }
        .padding()
        .background(Color.white.opacity(0.08), in: RoundedRectangle(cornerRadius: 16))
    }

    // MARK: - Analysis Details

    private var analysisDetailsSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Analysis Details")
                .font(.headline)
                .foregroundStyle(.white)

            LabeledContent {
                Text("\(result.framesAnalysed) of \(result.totalFrames)")
                    .foregroundStyle(.white.opacity(0.8))
            } label: {
                Text("Frames Analysed")
                    .foregroundStyle(.gray)
            }

            LabeledContent {
                Text(String(format: "%.1fs", result.processingTimeSeconds))
                    .foregroundStyle(.white.opacity(0.8))
            } label: {
                Text("Processing Time")
                    .foregroundStyle(.gray)
            }

            LabeledContent {
                HStack(spacing: 6) {
                    Circle()
                        .fill(confidenceColor)
                        .frame(width: 8, height: 8)
                    Text(String(format: "%.0f%%", result.confidenceScore * 100))
                        .foregroundStyle(.white.opacity(0.8))
                }
            } label: {
                Text("Confidence")
                    .foregroundStyle(.gray)
            }

            if let profile = result.speedProfile {
                LabeledContent {
                    Text("\(profile.peakSpeedMph.formattedSpeed) mph")
                        .foregroundStyle(.orange)
                } label: {
                    Text("Peak Speed")
                        .foregroundStyle(.gray)
                }

                LabeledContent {
                    Text(String(format: "%.2fs", profile.swingDurationSeconds))
                        .foregroundStyle(.white.opacity(0.8))
                } label: {
                    Text("Swing Duration")
                        .foregroundStyle(.gray)
                }
            }
        }
        .padding()
        .background(Color.white.opacity(0.08), in: RoundedRectangle(cornerRadius: 16))
    }

    // MARK: - Lag Analysis

    private func lagAnalysisSection(_ lag: LagMetrics) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Lag Analysis")
                .font(.headline)
                .foregroundStyle(.white)

            LabeledContent {
                Text(String(format: "%.2f", lag.lagRetentionIndex))
                    .foregroundStyle(.white.opacity(0.8))
            } label: {
                Text("Lag Retention Index")
                    .foregroundStyle(.gray)
            }

            LabeledContent {
                Text("\(lag.releasePointDegrees.formattedAngle) before impact")
                    .foregroundStyle(.white.opacity(0.8))
            } label: {
                Text("Release Point")
                    .foregroundStyle(.gray)
            }

            LabeledContent {
                Text(lag.lagAngleAtTop.formattedAngle)
                    .foregroundStyle(.white.opacity(0.8))
            } label: {
                Text("Lag at Top")
                    .foregroundStyle(.gray)
            }

            LabeledContent {
                Text("\(lag.shaftLeanAtImpact > 0 ? "+" : "")\(lag.shaftLeanAtImpact.formattedAngle)")
                    .foregroundStyle(.white.opacity(0.8))
            } label: {
                Text("Shaft Lean at Impact")
                    .foregroundStyle(.gray)
            }

            if lag.castingDetected {
                Label("Early release detected", systemImage: "exclamationmark.triangle.fill")
                    .foregroundStyle(.orange)
                    .font(.subheadline)
            } else {
                Label("Good lag retention", systemImage: "checkmark.circle.fill")
                    .foregroundStyle(.green)
                    .font(.subheadline)
            }

            if let speedLoss = lag.estimatedSpeedLossMph {
                Label(
                    "Estimated speed loss: \(speedLoss.formattedSpeed) mph",
                    systemImage: "arrow.down.right"
                )
                .foregroundStyle(.red.opacity(0.8))
                .font(.caption)
            }
        }
        .padding()
        .background(Color.white.opacity(0.08), in: RoundedRectangle(cornerRadius: 16))
    }

    // MARK: - Action Buttons

    private var actionButtons: some View {
        VStack(spacing: 12) {
            Button {
                onSave?()
                dismiss()
            } label: {
                Label("Save & Close", systemImage: "checkmark.circle.fill")
                    .font(.headline)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 14)
            }
            .buttonStyle(.borderedProminent)
            .tint(.green)

            Button {
                onViewFrames?()
            } label: {
                Label("View Frames", systemImage: "film.stack")
                    .font(.headline)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 14)
            }
            .buttonStyle(.bordered)
            .tint(.blue)

            Button(role: .destructive) {
                showDiscardConfirmation = true
            } label: {
                Label("Discard", systemImage: "trash")
                    .font(.subheadline)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 10)
            }
            .buttonStyle(.bordered)
            .tint(.red.opacity(0.7))
        }
        .padding(.top, 8)
    }

    // MARK: - Confidence Badge

    private var confidenceBadge: some View {
        HStack(spacing: 4) {
            Circle()
                .fill(confidenceColor)
                .frame(width: 8, height: 8)
            Text(confidenceLabel)
                .font(.caption)
                .foregroundStyle(.gray)
        }
    }

    private var confidenceColor: Color {
        if result.confidenceScore > 0.7 { return .green }
        if result.confidenceScore > 0.4 { return .yellow }
        return .red
    }

    private var confidenceLabel: String {
        if result.confidenceScore > 0.7 { return "High confidence" }
        if result.confidenceScore > 0.4 { return "Medium confidence" }
        return "Low confidence"
    }
}

// MARK: - Preview

#Preview("With Full Data") {
    AnalysisResultView(
        result: .init(
            speedProfile: SpeedProfile(
                dataPoints: [
                    .init(frameTimestamp: 0.0, speedMph: 5, confidence: 0.8, swingPhase: .backswing),
                    .init(frameTimestamp: 0.3, speedMph: 25, confidence: 0.85, swingPhase: .top),
                    .init(frameTimestamp: 0.5, speedMph: 60, confidence: 0.9, swingPhase: .earlyDownswing),
                    .init(frameTimestamp: 0.65, speedMph: 95, confidence: 0.88, swingPhase: .lateDownswing),
                    .init(frameTimestamp: 0.7, speedMph: 105, confidence: 0.82, swingPhase: .impact),
                    .init(frameTimestamp: 0.8, speedMph: 85, confidence: 0.75, swingPhase: .followThrough)
                ],
                peakSpeedMph: 108.3,
                peakSpeedTimestamp: 0.68,
                impactSpeedMph: 105.2,
                impactTimestamp: 0.7,
                swingDurationSeconds: 0.8
            ),
            lagMetrics: LagMetrics(
                lagAngleAtTop: 90,
                lagAngleAtArmParallel: 72,
                lagRetentionIndex: 0.80,
                releasePointDegrees: 35,
                shaftLeanAtImpact: 4.2,
                castingDetected: false,
                estimatedSpeedLossMph: nil,
                lagCurve: []
            ),
            impactTimestamp: 0.7,
            impactSpeedMph: 105.2,
            confidenceScore: 0.85,
            framesAnalysed: 142,
            totalFrames: 312,
            processingTimeSeconds: 6.3
        ),
        videoURL: URL(fileURLWithPath: "/tmp/test.mov"),
        calibration: CalibrationSnapshot(
            method: .lidar,
            pixelsPerMetre: 500,
            impactZoneX: 540,
            impactZoneY: 960
        ),
        clubType: .driver
    )
}

#Preview("No Speed Data") {
    AnalysisResultView(
        result: .init(
            speedProfile: nil,
            lagMetrics: nil,
            impactTimestamp: nil,
            impactSpeedMph: nil,
            confidenceScore: 0.15,
            framesAnalysed: 42,
            totalFrames: 312,
            processingTimeSeconds: 3.1
        ),
        videoURL: URL(fileURLWithPath: "/tmp/test.mov"),
        calibration: CalibrationSnapshot(
            method: .manual,
            pixelsPerMetre: 450,
            impactZoneX: 540,
            impactZoneY: 960
        ),
        clubType: .sevenIron
    )
}
