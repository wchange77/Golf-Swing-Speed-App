import SwiftUI
import Charts

/// Displays the speed-over-time curve for a swing using Swift Charts.
/// Marks the impact point and colour-codes swing phases.
struct SpeedCurveChart: View {
    let profile: SpeedProfile

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Speed Curve")
                .font(.headline)

            Chart {
                // Speed line
                ForEach(Array(profile.dataPoints.enumerated()), id: \.offset) { _, point in
                    LineMark(
                        x: .value("Time", point.frameTimestamp),
                        y: .value("Speed", point.speedMph)
                    )
                    .foregroundStyle(.blue)
                    .lineStyle(StrokeStyle(lineWidth: 2))

                    AreaMark(
                        x: .value("Time", point.frameTimestamp),
                        y: .value("Speed", point.speedMph)
                    )
                    .foregroundStyle(.blue.opacity(0.1))
                }

                // Impact marker
                RuleMark(x: .value("Impact", profile.impactTimestamp))
                    .foregroundStyle(.red)
                    .lineStyle(StrokeStyle(lineWidth: 1.5, dash: [4, 4]))
                    .annotation(position: .top, alignment: .center) {
                        Text("Impact")
                            .font(.caption2)
                            .foregroundStyle(.red)
                    }

                // Peak speed marker
                PointMark(
                    x: .value("Time", profile.peakSpeedTimestamp),
                    y: .value("Speed", profile.peakSpeedMph)
                )
                .foregroundStyle(.orange)
                .symbolSize(60)
                .annotation(position: .top) {
                    Text("\(profile.peakSpeedMph.formattedSpeed)")
                        .font(.caption2)
                        .fontWeight(.bold)
                        .foregroundStyle(.orange)
                }
            }
            .chartYAxisLabel("mph")
            .chartXAxisLabel("Time (s)")
            .chartYScale(domain: 0...(profile.peakSpeedMph * 1.15))
            .frame(height: 200)

            // Summary stats
            HStack(spacing: 16) {
                StatBadge(label: "Peak", value: "\(profile.peakSpeedMph.formattedSpeed) mph", color: .orange)
                StatBadge(label: "Impact", value: "\(profile.impactSpeedMph.formattedSpeed) mph", color: .red)
                StatBadge(label: "Duration", value: String(format: "%.2fs", profile.swingDurationSeconds), color: .blue)
            }
        }
        .padding()
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 16))
    }
}

struct StatBadge: View {
    let label: String
    let value: String
    let color: Color

    var body: some View {
        VStack(spacing: 2) {
            Text(label)
                .font(.caption2)
                .foregroundStyle(.secondary)
            Text(value)
                .font(.caption)
                .fontWeight(.semibold)
                .foregroundStyle(color)
        }
    }
}
