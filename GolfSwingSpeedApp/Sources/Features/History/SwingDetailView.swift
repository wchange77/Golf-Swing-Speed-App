import SwiftUI

struct SwingDetailView: View {
    let swing: SwingRecord

    var body: some View {
        ScrollView {
            VStack(spacing: 24) {
                // Speed headline
                speedCard

                // Swing info
                infoSection

                // Speed curve chart
                if let profile = swing.speedProfile, !profile.isEmpty {
                    SpeedCurveChart(profile: profile)
                } else {
                    speedCurvePlaceholder
                }

                // Lag metrics placeholder (Premium)
                lagMetricsPlaceholder
            }
            .padding()
        }
        .navigationTitle("Swing Detail")
        .navigationBarTitleDisplayMode(.inline)
    }

    // MARK: - Speed Card

    private var speedCard: some View {
        VStack(spacing: 8) {
            if let speed = swing.impactSpeedMph {
                Text(speed.formattedSpeed)
                    .font(.system(size: 64, weight: .bold, design: .rounded))
                Text("mph at impact")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            } else {
                Text("No speed data")
                    .font(.title2)
                    .foregroundStyle(.secondary)
            }

            HStack {
                Label(swing.club.displayName, systemImage: "figure.golf")
                Spacer()
                confidenceBadge
            }
            .font(.subheadline)
        }
        .padding()
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 16))
    }

    // MARK: - Info Section

    private var infoSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            LabeledContent("Date", value: swing.timestamp.mediumDateString)
            LabeledContent("Time", value: swing.timestamp.shortTimeString)
            if let profile = swing.speedProfile {
                LabeledContent("Peak Speed", value: "\(profile.peakSpeedMph.formattedSpeed) mph")
                LabeledContent("Duration", value: String(format: "%.2fs", profile.swingDurationSeconds))
            }
        }
        .padding()
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 16))
    }

    // MARK: - Speed Curve Placeholder

    private var speedCurvePlaceholder: some View {
        VStack(alignment: .leading) {
            Text("Speed Curve")
                .font(.headline)
            RoundedRectangle(cornerRadius: 12)
                .fill(.gray.opacity(0.1))
                .frame(height: 200)
                .overlay {
                    Text("Speed curve chart — Phase 4")
                        .foregroundStyle(.secondary)
                }
        }
        .padding()
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 16))
    }

    // MARK: - Lag Metrics Placeholder

    private var lagMetricsPlaceholder: some View {
        VStack(alignment: .leading) {
            HStack {
                Text("Lag Analysis")
                    .font(.headline)
                Spacer()
                Text("PREMIUM")
                    .font(.caption2)
                    .fontWeight(.bold)
                    .padding(.horizontal, 6)
                    .padding(.vertical, 2)
                    .background(.blue, in: Capsule())
                    .foregroundStyle(.white)
            }

            if let lag = swing.lagMetrics {
                VStack(alignment: .leading, spacing: 8) {
                    LabeledContent("Lag at Top", value: lag.lagAngleAtTop.formattedAngle)
                    LabeledContent("Lag at Arm Parallel", value: lag.lagAngleAtArmParallel.formattedAngle)
                    LabeledContent("Lag Retention Index", value: String(format: "%.2f", lag.lagRetentionIndex))
                    LabeledContent("Release Point", value: "\(lag.releasePointDegrees.formattedAngle) before impact")
                    LabeledContent("Shaft Lean", value: "\(lag.shaftLeanAtImpact > 0 ? "+" : "")\(lag.shaftLeanAtImpact.formattedAngle)")

                    if lag.castingDetected {
                        Label("Early release detected", systemImage: "exclamationmark.triangle.fill")
                            .foregroundStyle(.orange)
                    } else {
                        Label("Good lag retention", systemImage: "checkmark.circle.fill")
                            .foregroundStyle(.green)
                    }
                }
            } else {
                Text("Lag analysis available with Premium")
                    .foregroundStyle(.secondary)
            }
        }
        .padding()
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 16))
    }

    // MARK: - Confidence Badge

    private var confidenceBadge: some View {
        HStack(spacing: 4) {
            Circle()
                .fill(confidenceColor)
                .frame(width: 8, height: 8)
            Text(confidenceLabel)
                .font(.caption)
                .foregroundStyle(.secondary)
        }
    }

    private var confidenceColor: Color {
        if swing.confidenceScore > 0.7 { return .green }
        if swing.confidenceScore > 0.4 { return .yellow }
        return .red
    }

    private var confidenceLabel: String {
        if swing.confidenceScore > 0.7 { return "High confidence" }
        if swing.confidenceScore > 0.4 { return "Medium confidence" }
        return "Low confidence"
    }
}
