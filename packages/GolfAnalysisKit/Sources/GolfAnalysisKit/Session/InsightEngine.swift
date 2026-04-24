import Foundation

public struct Insight: Identifiable, Sendable {
    public var id: UUID
    public var category: InsightCategory
    public var title: String
    public var detail: String
    public var priority: InsightPriority
    public var relatedClub: ClubType?

    public init(
        id: UUID = UUID(),
        category: InsightCategory,
        title: String,
        detail: String,
        priority: InsightPriority,
        relatedClub: ClubType? = nil
    ) {
        self.id = id
        self.category = category
        self.title = title
        self.detail = detail
        self.priority = priority
        self.relatedClub = relatedClub
    }
}

public enum InsightCategory: String, Codable, Sendable {
    case strength
    case improvement
    case trend
    case gapping
    case consistency
    case milestone
}

public enum InsightPriority: Int, Codable, Sendable, Comparable {
    case low = 0
    case medium = 1
    case high = 2

    public static func < (lhs: InsightPriority, rhs: InsightPriority) -> Bool {
        lhs.rawValue < rhs.rawValue
    }
}

public struct InsightEngine {

    public static func generate(sessions: [SwingSession]) -> [Insight] {
        guard sessions.count >= 3 else { return [earlyStageInsight(count: sessions.count)] }

        var insights: [Insight] = []
        insights.append(contentsOf: strengthInsights(sessions: sessions))
        insights.append(contentsOf: improvementInsights(sessions: sessions))
        insights.append(contentsOf: trendInsights(sessions: sessions))
        insights.append(contentsOf: gappingInsights(sessions: sessions))
        insights.append(contentsOf: consistencyInsights(sessions: sessions))
        insights.append(contentsOf: milestoneInsights(sessions: sessions))
        insights.sort { $0.priority > $1.priority }
        return insights
    }

    private static func earlyStageInsight(count: Int) -> Insight {
        Insight(
            category: .milestone,
            title: "继续积累数据",
            detail: "已记录 \(count) 次挥杆，再多几次就能生成个性化分析。建议至少 5 次以上。",
            priority: .medium
        )
    }

    private static func strengthInsights(sessions: [SwingSession]) -> [Insight] {
        var results: [Insight] = []
        let stats = PersonalStatsCalculator.allClubStats(sessions: sessions)

        for stat in stats where stat.sessionCount >= 3 {
            if stat.consistencyScore > 0.75 {
                results.append(Insight(
                    category: .strength,
                    title: "\(stat.club.displayName) 稳定性出色",
                    detail: "Carry 标准差仅 \(String(format: "%.1f", stat.carryStdDev)) 码，一致性评分 \(Int(stat.consistencyScore * 100))%。",
                    priority: .medium,
                    relatedClub: stat.club
                ))
            }

            let expectedSpeed = LaunchConditionEstimator.typicalClubHeadSpeed(for: stat.club)
            if stat.avgClubHeadSpeedMph > expectedSpeed * 1.05 {
                results.append(Insight(
                    category: .strength,
                    title: "\(stat.club.displayName) 杆头速度高于平均",
                    detail: "平均 \(String(format: "%.0f", stat.avgClubHeadSpeedMph)) mph，高于业余平均 \(String(format: "%.0f", expectedSpeed)) mph。",
                    priority: .low,
                    relatedClub: stat.club
                ))
            }
        }
        return results
    }

    private static func improvementInsights(sessions: [SwingSession]) -> [Insight] {
        var results: [Insight] = []
        let stats = PersonalStatsCalculator.allClubStats(sessions: sessions)

        for stat in stats where stat.sessionCount >= 3 {
            if stat.consistencyScore < 0.4 {
                results.append(Insight(
                    category: .improvement,
                    title: "\(stat.club.displayName) 稳定性需提升",
                    detail: "Carry 标准差 \(String(format: "%.1f", stat.carryStdDev)) 码，建议在练习场多做重复练习。",
                    priority: .high,
                    relatedClub: stat.club
                ))
            }

            let sliceCount = stat.shapeCounts[.slice, default: 0]
            let hookCount = stat.shapeCounts[.hook, default: 0]
            let total = stat.sessionCount
            if Double(sliceCount) / Double(total) > 0.5 {
                results.append(Insight(
                    category: .improvement,
                    title: "\(stat.club.displayName) 右曲球偏多",
                    detail: "\(Int(Double(sliceCount) / Double(total) * 100))% 的球为 Slice，建议检查握杆和挥杆路径。",
                    priority: .high,
                    relatedClub: stat.club
                ))
            } else if Double(hookCount) / Double(total) > 0.5 {
                results.append(Insight(
                    category: .improvement,
                    title: "\(stat.club.displayName) 左曲球偏多",
                    detail: "\(Int(Double(hookCount) / Double(total) * 100))% 的球为 Hook，建议检查杆面角度。",
                    priority: .high,
                    relatedClub: stat.club
                ))
            }
        }
        return results
    }

    private static func trendInsights(sessions: [SwingSession]) -> [Insight] {
        var results: [Insight] = []
        let clubs = Set(sessions.map(\.club))

        for club in clubs {
            let trend = PersonalStatsCalculator.speedTrend(sessions: sessions, club: club, last: 10)
            guard trend.count >= 5 else { continue }

            let firstHalf = trend.prefix(trend.count / 2)
            let secondHalf = trend.suffix(trend.count / 2)
            let avgFirst = firstHalf.map(\.value).reduce(0, +) / Double(firstHalf.count)
            let avgSecond = secondHalf.map(\.value).reduce(0, +) / Double(secondHalf.count)

            let change = avgSecond - avgFirst
            if change > 2 {
                results.append(Insight(
                    category: .trend,
                    title: "\(club.displayName) 速度上升趋势",
                    detail: "近期杆头速度平均提升 \(String(format: "%.1f", change)) mph，保持训练节奏。",
                    priority: .medium,
                    relatedClub: club
                ))
            } else if change < -2 {
                results.append(Insight(
                    category: .trend,
                    title: "\(club.displayName) 速度下降趋势",
                    detail: "近期杆头速度平均下降 \(String(format: "%.1f", abs(change))) mph，注意休息和体能。",
                    priority: .high,
                    relatedClub: club
                ))
            }
        }
        return results
    }

    private static func gappingInsights(sessions: [SwingSession]) -> [Insight] {
        let gapping = PersonalStatsCalculator.clubGapping(sessions: sessions)
        guard gapping.count >= 2 else { return [] }

        var results: [Insight] = []
        for i in 1..<gapping.count {
            let gap = gapping[i - 1].1 - gapping[i].1
            if gap < 5 {
                results.append(Insight(
                    category: .gapping,
                    title: "\(gapping[i - 1].0.displayName) 与 \(gapping[i].0.displayName) 距离重叠",
                    detail: "两支杆 Carry 仅差 \(String(format: "%.0f", gap)) 码，考虑调整其中一支。",
                    priority: .medium
                ))
            } else if gap > 25 {
                results.append(Insight(
                    category: .gapping,
                    title: "\(gapping[i - 1].0.displayName) 与 \(gapping[i].0.displayName) 之间有空档",
                    detail: "两支杆 Carry 差距 \(String(format: "%.0f", gap)) 码，可能需要补充中间球杆。",
                    priority: .medium
                ))
            }
        }
        return results
    }

    private static func consistencyInsights(sessions: [SwingSession]) -> [Insight] {
        let overall = PersonalStatsCalculator.overallConsistency(sessions: sessions)
        if overall > 0.7 {
            return [Insight(
                category: .consistency,
                title: "整体稳定性良好",
                detail: "综合一致性评分 \(Int(overall * 100))%，各球杆表现稳定。",
                priority: .low
            )]
        } else if overall < 0.35 && sessions.count >= 10 {
            return [Insight(
                category: .consistency,
                title: "整体稳定性有提升空间",
                detail: "综合一致性评分 \(Int(overall * 100))%，建议集中练习 1-2 支球杆。",
                priority: .high
            )]
        }
        return []
    }

    private static func milestoneInsights(sessions: [SwingSession]) -> [Insight] {
        var results: [Insight] = []
        let milestones = [10, 25, 50, 100, 250, 500]
        for m in milestones where sessions.count == m {
            results.append(Insight(
                category: .milestone,
                title: "达成 \(m) 次挥杆记录",
                detail: "已累计 \(m) 次挥杆数据，数据越多分析越精准。",
                priority: .low
            ))
        }

        let bests = PersonalStatsCalculator.personalBests(sessions: sessions)
        let today = Calendar.current.startOfDay(for: Date())
        for best in bests {
            if Calendar.current.startOfDay(for: best.date) == today {
                results.append(Insight(
                    category: .milestone,
                    title: "\(best.club.displayName) 刷新个人最佳",
                    detail: "\(best.metric == "carry" ? "Carry" : best.metric == "ballSpeed" ? "球速" : "杆头速度") 达到 \(String(format: "%.0f", best.value))\(best.metric == "carry" ? " 码" : " mph")。",
                    priority: .high,
                    relatedClub: best.club
                ))
            }
        }
        return results
    }
}
