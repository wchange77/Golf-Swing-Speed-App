import SwiftUI
import GolfAnalysisKit

struct InsightsDashboardView: View {
    @StateObject private var viewModel = InsightsDashboardViewModel()

    var body: some View {
        NavigationStack {
            ScrollView {
                if viewModel.isLoading {
                    ProgressView()
                        .padding(.top, 40)
                } else if viewModel.sessionCount == 0 {
                    emptyState
                } else {
                    VStack(spacing: 16) {
                        summaryCards
                        if !viewModel.clubStats.isEmpty {
                            clubStatsSection
                        }
                        if !viewModel.insights.isEmpty {
                            insightsSection
                        }
                        if !viewModel.personalBests.isEmpty {
                            personalBestsSection
                        }
                    }
                    .padding(.horizontal, 16)
                    .padding(.bottom, 20)
                }
            }
            .navigationTitle("洞察")
            .task { await viewModel.load() }
        }
    }

    private var emptyState: some View {
        VStack(spacing: 12) {
            Image(systemName: "chart.bar.xaxis")
                .font(.system(size: 48))
                .foregroundStyle(.secondary)
            Text("暂无数据")
                .font(.headline)
            Text("完成几次球检测分析后，这里会显示个性化洞察。")
                .font(.subheadline)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
        }
        .padding(.top, 60)
        .padding(.horizontal, 40)
    }

    private var summaryCards: some View {
        LazyVGrid(columns: [
            GridItem(.flexible()),
            GridItem(.flexible()),
        ], spacing: 10) {
            SummaryCard(
                title: "总挥杆",
                value: "\(viewModel.sessionCount)",
                icon: "figure.golf"
            )
            SummaryCard(
                title: "使用球杆",
                value: "\(viewModel.clubStats.count)",
                icon: "bag.fill"
            )
            SummaryCard(
                title: "一致性",
                value: "\(Int(viewModel.overallConsistency * 100))%",
                icon: "target"
            )
            SummaryCard(
                title: "最远 Carry",
                value: "\(String(format: "%.0f", viewModel.bestCarry)) 码",
                icon: "arrow.up.right"
            )
        }
    }

    private var clubStatsSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("球杆数据")
                .font(.headline)
                .padding(.leading, 4)

            ForEach(viewModel.clubStats, id: \.club) { stat in
                ClubStatCard(stat: stat)
            }
        }
    }

    private var insightsSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("个性化建议")
                .font(.headline)
                .padding(.leading, 4)

            ForEach(viewModel.insights) { insight in
                InsightCard(insight: insight)
            }
        }
    }

    private var personalBestsSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("个人最佳")
                .font(.headline)
                .padding(.leading, 4)

            LazyVGrid(columns: [
                GridItem(.flexible()),
                GridItem(.flexible()),
            ], spacing: 8) {
                ForEach(viewModel.personalBests.prefix(8), id: \.sessionId) { best in
                    PersonalBestCard(best: best)
                }
            }
        }
    }
}

struct SummaryCard: View {
    let title: String
    let value: String
    let icon: String

    var body: some View {
        VStack(spacing: 6) {
            Image(systemName: icon)
                .font(.title3)
                .foregroundStyle(.accentColor)
            Text(value)
                .font(.system(.title3, design: .rounded, weight: .semibold))
            Text(title)
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 12)
        .background(.ultraThinMaterial)
        .clipShape(RoundedRectangle(cornerRadius: 12))
    }
}

struct ClubStatCard: View {
    let stat: ClubStats

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text(stat.club.displayName)
                    .font(.subheadline.bold())
                Spacer()
                Text("\(stat.sessionCount) 次")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                consistencyBadge
            }

            HStack(spacing: 16) {
                miniMetric(label: "杆速", value: String(format: "%.0f", stat.avgClubHeadSpeedMph), unit: "mph")
                miniMetric(label: "球速", value: String(format: "%.0f", stat.avgBallSpeedMph), unit: "mph")
                miniMetric(label: "Carry", value: String(format: "%.0f", stat.avgCarryYards), unit: "码")
                miniMetric(label: "发射角", value: String(format: "%.1f", stat.avgLaunchAngle), unit: "°")
            }
        }
        .padding(12)
        .background(.ultraThinMaterial)
        .clipShape(RoundedRectangle(cornerRadius: 10))
    }

    private var consistencyBadge: some View {
        let score = stat.consistencyScore
        let color: Color = score > 0.7 ? .green : score > 0.4 ? .yellow : .red
        return Text("\(Int(score * 100))%")
            .font(.caption2.bold())
            .padding(.horizontal, 6)
            .padding(.vertical, 2)
            .background(color.opacity(0.15))
            .foregroundStyle(color)
            .clipShape(Capsule())
    }

    private func miniMetric(label: String, value: String, unit: String) -> some View {
        VStack(spacing: 1) {
            Text(label).font(.system(size: 9)).foregroundStyle(.secondary)
            HStack(alignment: .firstTextBaseline, spacing: 1) {
                Text(value).font(.system(size: 13, weight: .semibold, design: .rounded))
                Text(unit).font(.system(size: 8)).foregroundStyle(.secondary)
            }
        }
    }
}

struct InsightCard: View {
    let insight: Insight

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            categoryIcon
                .frame(width: 28, height: 28)
                .background(categoryColor.opacity(0.15))
                .clipShape(Circle())

            VStack(alignment: .leading, spacing: 3) {
                HStack {
                    Text(insight.title)
                        .font(.subheadline.bold())
                    Spacer()
                    priorityBadge
                }
                Text(insight.detail)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(3)
            }
        }
        .padding(12)
        .background(.ultraThinMaterial)
        .clipShape(RoundedRectangle(cornerRadius: 10))
    }

    private var categoryIcon: some View {
        Image(systemName: {
            switch insight.category {
            case .strength: return "star.fill"
            case .improvement: return "arrow.up.circle.fill"
            case .trend: return "chart.line.uptrend.xyaxis"
            case .gapping: return "ruler.fill"
            case .consistency: return "target"
            case .milestone: return "trophy.fill"
            }
        }())
        .font(.caption)
        .foregroundStyle(categoryColor)
    }

    private var categoryColor: Color {
        switch insight.category {
        case .strength: return .green
        case .improvement: return .orange
        case .trend: return .blue
        case .gapping: return .purple
        case .consistency: return .teal
        case .milestone: return .yellow
        }
    }

    private var priorityBadge: some View {
        let (label, color): (String, Color) = {
            switch insight.priority {
            case .high: return ("重要", .red)
            case .medium: return ("建议", .orange)
            case .low: return ("参考", .gray)
            }
        }()
        return Text(label)
            .font(.system(size: 9).bold())
            .padding(.horizontal, 5)
            .padding(.vertical, 1)
            .background(color.opacity(0.15))
            .foregroundStyle(color)
            .clipShape(Capsule())
    }
}

struct PersonalBestCard: View {
    let best: PersonalBest

    var body: some View {
        VStack(spacing: 4) {
            Text(best.club.displayName)
                .font(.caption2)
                .foregroundStyle(.secondary)
            Text(metricLabel)
                .font(.system(size: 9))
                .foregroundStyle(.secondary)
            Text(formattedValue)
                .font(.system(.subheadline, design: .rounded, weight: .bold))
                .foregroundStyle(.yellow)
            Text(best.date, style: .date)
                .font(.system(size: 8))
                .foregroundStyle(.tertiary)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 10)
        .background(.ultraThinMaterial)
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }

    private var metricLabel: String {
        switch best.metric {
        case "carry": return "Carry"
        case "ballSpeed": return "球速"
        case "clubHeadSpeed": return "杆头速度"
        default: return best.metric
        }
    }

    private var formattedValue: String {
        let unit = best.metric == "carry" ? " 码" : " mph"
        return String(format: "%.0f", best.value) + unit
    }
}
