import Foundation
import GolfAnalysisKit

@MainActor
final class SessionHistoryViewModel: ObservableObject {
    @Published private(set) var sessions: [SwingSession] = []
    @Published private(set) var isLoading = true
    @Published private(set) var totalCount = 0

    private let store = SwingSessionStore()

    var usedClubs: [ClubType] {
        let clubs = Set(sessions.map(\.club))
        return ClubType.allCases.filter { clubs.contains($0) }
    }

    func load() async {
        isLoading = true
        do {
            let all = try await store.allSessions()
            sessions = all.sorted { $0.date > $1.date }
            totalCount = all.count
        } catch {
            sessions = []
            totalCount = 0
        }
        isLoading = false
    }

    func delete(session: SwingSession) {
        Task {
            try? await store.delete(id: session.id)
            sessions.removeAll { $0.id == session.id }
            totalCount = sessions.count
        }
    }
}
