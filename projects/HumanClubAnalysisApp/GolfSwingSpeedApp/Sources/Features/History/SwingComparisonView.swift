import SwiftUI
import SwiftData
import Charts

/// Compares two swings side-by-side — speed curves, metrics, and lag analysis.
struct SwingComparisonView: View {
    let swing1: SwingRecord
    let swing2: SwingRecord

    var body: some View {
        ScrollView {
            VStack(spacing: 20) {
                // Speed headline comparison
                speedComparison

                // Speed curves overlaid
                if let profile1 = swing1.speedProfile, let profile2 = swing2.speedProfile {
                    overlaidSpeedCurves(profile1: profile1, profile2: profile2)
                }

                // Metrics comparison table
                metricsTable

                // Lag analysis comparison
                if swing1.lagMetrics != nil || swing2.lagMetrics != nil {
                    lagComparison
                }
            }
            .padding()
        }
        .navigationTitle("Compare Swings")
        .navigationBarTitleDisplayMode(.inline)
    }

    // MARK: - Speed Comparison

    private var speedComparison: some View {
        HStack(spacing: 0) {
            // Swing 1
            swingCard(swing: swing1, label: "Swing 1", color: .blue)

            // VS divider
            VStack {
                Text("VS")
                    .font(.caption)
                    .fontWeight(.bold)
                    .foregroundStyle(.secondary)

                if let speed1 = swing1.impactSpeedMph, let speed2 = swing2.impactSpeedMph {
                    let diff = speed2 - speed1
                    Text("\(diff > 0 ? "+" : "")\(diff.formattedSpeed)")
                        .font(.caption)
                        .fontWeight(.bold)
                        .foregroundStyle(diff > 0 ? .green : diff < 0 ? .red : .secondary)
                }
            }
            .frame(width: 50)

            // Swing 2
            swingCard(swing: swing2, label: "Swing 2", color: .orange)
        }
        .padding()
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 16))
    }

    private func swingCard(swing: SwingRecord, label: String, color: Color) -> some View {
        VStack(spacing: 4) {
            Text(label)
                .font(.caption)
                .foregroundStyle(color)

            if let speed = swing.impactSpeedMph {
                Text(speed.formattedSpeed)
                    .font(.system(size: 36, weight: .bold, design: .rounded))
                    .foregroundStyle(color)

                Text("mph")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            } else {
                Text("--")
                    .font(.title)
                    .foregroundStyle(.secondary)
            }

            Text(swing.club.displayName)
                .font(.caption2)
                .foregroundStyle(.secondary)

            Text(swing.timestamp.shortTimeString)
                .font(.caption2)
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity)
    }

    // MARK: - Overlaid Speed Curves

    private func overlaidSpeedCurves(profile1: SpeedProfile, profile2: SpeedProfile) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Speed Curves")
                .font(.headline)

            Chart {
                // Swing 1 curve (blue)
                ForEach(Array(profile1.dataPoints.enumerated()), id: \.offset) { _, point in
                    LineMark(
                        x: .value("Time", point.frameTimestamp - profile1.dataPoints.first!.frameTimestamp),
                        y: .value("Speed", point.speedMph),
                        series: .value("Swing", "Swing 1")
                    )
                    .foregroundStyle(.blue)
                    .lineStyle(StrokeStyle(lineWidth: 2))
                }

                // Swing 2 curve (orange)
                ForEach(Array(profile2.dataPoints.enumerated()), id: \.offset) { _, point in
                    LineMark(
                        x: .value("Time", point.frameTimestamp - profile2.dataPoints.first!.frameTimestamp),
                        y: .value("Speed", point.speedMph),
                        series: .value("Swing", "Swing 2")
                    )
                    .foregroundStyle(.orange)
                    .lineStyle(StrokeStyle(lineWidth: 2))
                }
            }
            .chartYAxisLabel("mph")
            .chartXAxisLabel("Time (s)")
            .chartForegroundStyleScale(["Swing 1": .blue, "Swing 2": .orange])
            .frame(height: 200)
        }
        .padding()
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 16))
    }

    // MARK: - Metrics Table

    private var metricsTable: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Metrics")
                .font(.headline)

            ComparisonRow(
                label: "Impact Speed",
                value1: swing1.impactSpeedMph?.formattedSpeed.appending(" mph"),
                value2: swing2.impactSpeedMph?.formattedSpeed.appending(" mph"),
                higherIsBetter: true
            )

            if let p1 = swing1.speedProfile, let p2 = swing2.speedProfile {
                ComparisonRow(
                    label: "Peak Speed",
                    value1: p1.peakSpeedMph.formattedSpeed + " mph",
                    value2: p2.peakSpeedMph.formattedSpeed + " mph",
                    higherIsBetter: true
                )

                ComparisonRow(
                    label: "Duration",
                    value1: String(format: "%.2fs", p1.swingDurationSeconds),
                    value2: String(format: "%.2fs", p2.swingDurationSeconds),
                    higherIsBetter: false
                )
            }

            ComparisonRow(
                label: "Confidence",
                value1: String(format: "%.0f%%", swing1.confidenceScore * 100),
                value2: String(format: "%.0f%%", swing2.confidenceScore * 100),
                higherIsBetter: true
            )
        }
        .padding()
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 16))
    }

    // MARK: - Lag Comparison

    private var lagComparison: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Lag Analysis")
                .font(.headline)

            let lag1 = swing1.lagMetrics
            let lag2 = swing2.lagMetrics

            ComparisonRow(
                label: "Lag at Top",
                value1: lag1?.lagAngleAtTop.formattedAngle,
                value2: lag2?.lagAngleAtTop.formattedAngle,
                higherIsBetter: true
            )

            ComparisonRow(
                label: "Retention Index",
                value1: lag1.map { String(format: "%.2f", $0.lagRetentionIndex) },
                value2: lag2.map { String(format: "%.2f", $0.lagRetentionIndex) },
                higherIsBetter: true
            )

            ComparisonRow(
                label: "Release Point",
                value1: lag1?.releasePointDegrees.formattedAngle,
                value2: lag2?.releasePointDegrees.formattedAngle,
                higherIsBetter: false
            )

            ComparisonRow(
                label: "Shaft Lean",
                value1: lag1?.shaftLeanAtImpact.formattedAngle,
                value2: lag2?.shaftLeanAtImpact.formattedAngle,
                higherIsBetter: true
            )
        }
        .padding()
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 16))
    }
}

// MARK: - Comparison Row

struct ComparisonRow: View {
    let label: String
    let value1: String?
    let value2: String?
    let higherIsBetter: Bool

    var body: some View {
        HStack {
            Text(value1 ?? "--")
                .font(.subheadline)
                .fontWeight(.semibold)
                .foregroundStyle(winnerColor(isFirst: true))
                .frame(maxWidth: .infinity, alignment: .trailing)

            Text(label)
                .font(.caption)
                .foregroundStyle(.secondary)
                .frame(width: 100, alignment: .center)

            Text(value2 ?? "--")
                .font(.subheadline)
                .fontWeight(.semibold)
                .foregroundStyle(winnerColor(isFirst: false))
                .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private func winnerColor(isFirst: Bool) -> Color {
        guard let v1 = value1, let v2 = value2,
              let n1 = Double(v1.replacingOccurrences(of: "[^0-9.]", with: "", options: .regularExpression)),
              let n2 = Double(v2.replacingOccurrences(of: "[^0-9.]", with: "", options: .regularExpression)) else {
            return .primary
        }

        let winner = higherIsBetter ? (n1 > n2) : (n1 < n2)
        if isFirst {
            return winner ? .green : (n1 == n2 ? .primary : .secondary)
        } else {
            return !winner ? .green : (n1 == n2 ? .primary : .secondary)
        }
    }
}
