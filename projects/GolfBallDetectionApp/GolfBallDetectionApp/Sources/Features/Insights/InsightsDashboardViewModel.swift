import Foundation
import GolfAnalysisKit

@MainActor
final class InsightsDashboardViewModel: ObservableObject {
    @Published private(set) var isLoading = true
    @Published private(set) var sessionCount = 0
    @Published private(set) var clubStats: [ClubStats] = []
    @Published private(set) var insights: [Insight] = []
    @Published private(set) var personalBests: [PersonalBest] = []
    @Published private(set) var overallConsistency: Double = 0
    @Published private(set) var bestCarry: Double = 0

    private let store = SwingSessionStore()

    func load() async {
        isLoading = true
        do {
            let sessions = try await store.allSessions()
            sessionCount = sessions.count
            clubStats = PersonalStatsCalculator.allClubStats(sessions: sessions)
            insights = InsightEngine.generate(sessions: sessions)
            personalBests = PersonalStatsCalculator.personalBests(sessions: sessions)
            overallConsistency = PersonalStatsCalculator.overallConsistency(sessions: sessions)
            bestCarry = sessions.map(\.carryDistanceYards).max() ?? 0
        } catch {
            sessionCount = 0
        }
        isLoading = false
    }
}
