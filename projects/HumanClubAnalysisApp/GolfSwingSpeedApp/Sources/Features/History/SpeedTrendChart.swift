import SwiftUI
import Charts

/// Shows speed trend over time across multiple swings.
/// Helps golfers track their progress during training sessions.
struct SpeedTrendChart: View {
    let swings: [SwingRecord]

    private var swingsWithSpeed: [SwingRecord] {
        swings.filter { $0.impactSpeedMph != nil }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text("Speed Trend")
                    .font(.headline)
                Spacer()
                if swingsWithSpeed.count >= 2 {
                    trendIndicator
                }
            }

            if swingsWithSpeed.count < 2 {
                Text("Record 2+ swings to see your trend")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, alignment: .center)
                    .padding(.vertical, 20)
            } else {
                Chart {
                    ForEach(Array(swingsWithSpeed.enumerated()), id: \.offset) { index, swing in
                        if let speed = swing.impactSpeedMph {
                            LineMark(
                                x: .value("Swing", index + 1),
                                y: .value("Speed", speed)
                            )
                            .foregroundStyle(.blue)
                            .lineStyle(StrokeStyle(lineWidth: 2))

                            PointMark(
                                x: .value("Swing", index + 1),
                                y: .value("Speed", speed)
                            )
                            .foregroundStyle(speedPointColor(speed))
                            .symbolSize(30)
                        }
                    }

                    // Average line
                    let avg = averageSpeed
                    RuleMark(y: .value("Average", avg))
                        .foregroundStyle(.gray.opacity(0.5))
                        .lineStyle(StrokeStyle(lineWidth: 1, dash: [5, 5]))
                        .annotation(position: .trailing, alignment: .trailing) {
                            Text("Avg \(avg.formattedSpeed)")
                                .font(.caption2)
                                .foregroundStyle(.secondary)
                        }
                }
                .chartYAxisLabel("mph")
                .chartXAxisLabel("Swing #")
                .frame(height: 160)

                // Session summary
                HStack(spacing: 16) {
                    StatBadge(label: "Swings", value: "\(swingsWithSpeed.count)", color: .blue)
                    StatBadge(label: "Average", value: "\(averageSpeed.formattedSpeed) mph", color: .blue)
                    StatBadge(label: "Best", value: "\(bestSpeed.formattedSpeed) mph", color: .green)

                    if swingsWithSpeed.count >= 3 {
                        StatBadge(
                            label: "Last 3 Avg",
                            value: "\(lastThreeAverage.formattedSpeed) mph",
                            color: lastThreeAverage > averageSpeed ? .green : .orange
                        )
                    }
                }
            }
        }
        .padding()
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 16))
    }

    // MARK: - Computed Stats

    private var averageSpeed: Double {
        let speeds = swingsWithSpeed.compactMap { $0.impactSpeedMph }
        guard !speeds.isEmpty else { return 0 }
        return speeds.reduce(0, +) / Double(speeds.count)
    }

    private var bestSpeed: Double {
        swingsWithSpeed.compactMap { $0.impactSpeedMph }.max() ?? 0
    }

    private var lastThreeAverage: Double {
        let recent = Array(swingsWithSpeed.suffix(3))
        let speeds = recent.compactMap { $0.impactSpeedMph }
        guard !speeds.isEmpty else { return 0 }
        return speeds.reduce(0, +) / Double(speeds.count)
    }

    // MARK: - Trend Indicator

    private var trendIndicator: some View {
        let speeds = swingsWithSpeed.compactMap { $0.impactSpeedMph }
        guard speeds.count >= 2 else { return AnyView(EmptyView()) }

        let recentAvg = Array(speeds.suffix(3)).reduce(0, +) / Double(min(3, speeds.count))
        let earlyAvg = Array(speeds.prefix(3)).reduce(0, +) / Double(min(3, speeds.count))
        let trend = recentAvg - earlyAvg

        return AnyView(
            HStack(spacing: 4) {
                Image(systemName: trend > 1 ? "arrow.up.right" : trend < -1 ? "arrow.down.right" : "arrow.right")
                    .font(.caption)
                Text("\(trend > 0 ? "+" : "")\(trend.formattedSpeed)")
                    .font(.caption)
                    .fontWeight(.semibold)
            }
            .foregroundStyle(trend > 1 ? .green : trend < -1 ? .red : .secondary)
        )
    }

    private func speedPointColor(_ speed: Double) -> Color {
        if speed >= bestSpeed { return .green }
        if speed >= averageSpeed { return .blue }
        return .orange
    }
}
