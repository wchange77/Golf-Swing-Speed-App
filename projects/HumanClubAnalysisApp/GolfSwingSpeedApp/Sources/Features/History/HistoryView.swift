import SwiftUI
import SwiftData

struct HistoryView: View {
    @Query(sort: \SwingRecord.timestamp, order: .reverse) private var swings: [SwingRecord]

    var body: some View {
        NavigationStack {
            Group {
                if swings.isEmpty {
                    emptyState
                } else {
                    swingList
                }
            }
            .navigationTitle("History")
        }
    }

    // MARK: - Empty State

    private var emptyState: some View {
        ContentUnavailableView(
            "No Swings Yet",
            systemImage: "figure.golf",
            description: Text("Captured swings will appear here. Go to the Capture tab to record your first swing.")
        )
    }

    // MARK: - Swing List

    private var swingList: some View {
        List {
            // Stats summary
            if swingsWithSpeed.count >= 2 {
                Section {
                    statsHeader
                }
            }

            // Trend chart
            if swingsWithSpeed.count >= 2 {
                Section {
                    SpeedTrendChart(swings: Array(swingsWithSpeed))
                        .listRowInsets(EdgeInsets())
                        .listRowBackground(Color.clear)
                }
            }

            // Swings
            Section {
                ForEach(swings) { swing in
                    NavigationLink {
                        SwingDetailView(swing: swing)
                    } label: {
                        SwingRowView(swing: swing)
                    }
                }
            }
        }
        .listStyle(.plain)
    }

    // MARK: - Stats Header

    private var swingsWithSpeed: [SwingRecord] {
        swings.filter { $0.impactSpeedMph != nil }
    }

    private var statsHeader: some View {
        let speeds = swingsWithSpeed.compactMap { $0.impactSpeedMph }
        let avg = speeds.reduce(0, +) / Double(speeds.count)
        let maxSpeed = speeds.max() ?? 0

        return HStack(spacing: 0) {
            StatCard(title: "Average", value: "\(avg.formattedSpeed)", unit: "mph", color: .blue)
            StatCard(title: "Max", value: "\(maxSpeed.formattedSpeed)", unit: "mph", color: .green)
            StatCard(title: "Swings", value: "\(swingsWithSpeed.count)", unit: "total", color: .orange)
        }
        .listRowInsets(EdgeInsets())
        .listRowBackground(Color.clear)
    }
}

// MARK: - Stat Card

struct StatCard: View {
    let title: String
    let value: String
    let unit: String
    let color: Color

    var body: some View {
        VStack(spacing: 4) {
            Text(title)
                .font(.caption2)
                .foregroundStyle(.secondary)
            Text(value)
                .font(.title2)
                .fontWeight(.bold)
                .foregroundStyle(color)
                .monospacedDigit()
            Text(unit)
                .font(.caption2)
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 12)
    }
}

// MARK: - Swing Row

struct SwingRowView: View {
    let swing: SwingRecord

    var body: some View {
        HStack {
            VStack(alignment: .leading, spacing: 4) {
                HStack {
                    Text(swing.club.displayName)
                        .font(.subheadline)
                        .fontWeight(.semibold)

                    Spacer()

                    if let speed = swing.impactSpeedMph {
                        Text("\(speed.formattedSpeed) mph")
                            .font(.title3)
                            .fontWeight(.bold)
                            .monospacedDigit()
                    } else {
                        Text("--")
                            .font(.title3)
                            .foregroundStyle(.secondary)
                    }
                }

                HStack {
                    Text(swing.timestamp.mediumDateString)
                    Text(swing.timestamp.shortTimeString)
                }
                .font(.caption)
                .foregroundStyle(.secondary)
            }

            confidenceIndicator
        }
    }

    private var confidenceIndicator: some View {
        Circle()
            .fill(confidenceColor)
            .frame(width: 10, height: 10)
    }

    private var confidenceColor: Color {
        if swing.confidenceScore > 0.7 { return .green }
        if swing.confidenceScore > 0.4 { return .yellow }
        return .red
    }
}

#Preview {
    HistoryView()
        .modelContainer(for: SwingRecord.self, inMemory: true)
}
