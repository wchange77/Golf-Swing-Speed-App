import XCTest
@testable import GolfAnalysisKit

final class SwingSessionStoreTests: XCTestCase {

    private var tempDir: URL!

    override func setUp() {
        super.setUp()
        tempDir = FileManager.default.temporaryDirectory
            .appendingPathComponent("SwingSessionStoreTests_\(UUID().uuidString)")
        try? FileManager.default.createDirectory(at: tempDir, withIntermediateDirectories: true)
    }

    override func tearDown() {
        try? FileManager.default.removeItem(at: tempDir)
        super.tearDown()
    }

    func testSaveAndLoadSession() async throws {
        let store = SwingSessionStore(directory: tempDir)
        let session = makeSession(club: .driver, carry: 230)
        try await store.save(session)

        let all = try await store.allSessions()
        XCTAssertEqual(all.count, 1)
        XCTAssertEqual(all[0].id, session.id)
        XCTAssertEqual(all[0].carryDistanceYards, 230, accuracy: 0.01)
    }

    func testMultipleSessions() async throws {
        let store = SwingSessionStore(directory: tempDir)
        try await store.save(makeSession(club: .driver, carry: 230))
        try await store.save(makeSession(club: .sevenIron, carry: 150))
        try await store.save(makeSession(club: .driver, carry: 240))

        let all = try await store.allSessions()
        XCTAssertEqual(all.count, 3)

        let drivers = try await store.sessions(for: .driver)
        XCTAssertEqual(drivers.count, 2)
    }

    func testDeleteSession() async throws {
        let store = SwingSessionStore(directory: tempDir)
        let s1 = makeSession(club: .driver, carry: 230)
        let s2 = makeSession(club: .sevenIron, carry: 150)
        try await store.save(s1)
        try await store.save(s2)

        try await store.delete(id: s1.id)
        let all = try await store.allSessions()
        XCTAssertEqual(all.count, 1)
        XCTAssertEqual(all[0].id, s2.id)
    }

    func testPersistenceAcrossInstances() async throws {
        let store1 = SwingSessionStore(directory: tempDir)
        try await store1.save(makeSession(club: .driver, carry: 230))
        try await store1.save(makeSession(club: .sevenIron, carry: 150))

        let store2 = SwingSessionStore(directory: tempDir)
        let all = try await store2.allSessions()
        XCTAssertEqual(all.count, 2)
    }

    func testRecentSessions() async throws {
        let store = SwingSessionStore(directory: tempDir)
        for i in 0..<5 {
            var s = makeSession(club: .driver, carry: Double(200 + i * 10))
            s.date = Date().addingTimeInterval(Double(i) * 60)
            try await store.save(s)
        }

        let recent = try await store.recentSessions(count: 3)
        XCTAssertEqual(recent.count, 3)
        XCTAssertTrue(recent[0].date > recent[1].date)
    }

    private func makeSession(club: ClubType, carry: Double) -> SwingSession {
        SwingSession(
            club: club,
            clubHeadSpeedMph: 100,
            ballSpeedMph: 149,
            launchAngleDegrees: 12,
            carryDistanceYards: carry,
            totalDistanceYards: carry + 20
        )
    }
}

final class PersonalStatsCalculatorTests: XCTestCase {

    func testClubStatsAverages() {
        let sessions = [
            makeSession(club: .driver, speed: 100, carry: 230),
            makeSession(club: .driver, speed: 105, carry: 240),
            makeSession(club: .driver, speed: 95, carry: 220),
        ]

        let stats = PersonalStatsCalculator.clubStats(sessions: sessions, club: .driver)
        XCTAssertNotNil(stats)
        XCTAssertEqual(stats!.avgClubHeadSpeedMph, 100, accuracy: 0.1)
        XCTAssertEqual(stats!.avgCarryYards, 230, accuracy: 0.1)
        XCTAssertEqual(stats!.sessionCount, 3)
    }

    func testConsistencyScore() {
        let consistent = [
            makeSession(club: .sevenIron, speed: 80, carry: 150),
            makeSession(club: .sevenIron, speed: 80, carry: 151),
            makeSession(club: .sevenIron, speed: 80, carry: 149),
        ]
        let stats = PersonalStatsCalculator.clubStats(sessions: consistent, club: .sevenIron)!
        XCTAssertGreaterThan(stats.consistencyScore, 0.9)

        let inconsistent = [
            makeSession(club: .sevenIron, speed: 80, carry: 100),
            makeSession(club: .sevenIron, speed: 80, carry: 200),
            makeSession(club: .sevenIron, speed: 80, carry: 50),
        ]
        let stats2 = PersonalStatsCalculator.clubStats(sessions: inconsistent, club: .sevenIron)!
        XCTAssertLessThan(stats2.consistencyScore, 0.5)
    }

    func testPersonalBests() {
        let sessions = [
            makeSession(club: .driver, speed: 100, carry: 230),
            makeSession(club: .driver, speed: 110, carry: 250),
            makeSession(club: .sevenIron, speed: 80, carry: 155),
        ]

        let bests = PersonalStatsCalculator.personalBests(sessions: sessions)
        let driverCarryBest = bests.first { $0.club == .driver && $0.metric == "carry" }
        XCTAssertNotNil(driverCarryBest)
        XCTAssertEqual(driverCarryBest!.value, 250, accuracy: 0.01)
    }

    func testClubGapping() {
        let sessions = [
            makeSession(club: .driver, speed: 100, carry: 230),
            makeSession(club: .sevenIron, speed: 80, carry: 150),
            makeSession(club: .pitchingWedge, speed: 72, carry: 120),
        ]

        let gapping = PersonalStatsCalculator.clubGapping(sessions: sessions)
        XCTAssertEqual(gapping.count, 3)
        XCTAssertTrue(gapping[0].1 > gapping[1].1)
    }

    func testSpeedTrend() {
        var sessions: [SwingSession] = []
        for i in 0..<10 {
            var s = makeSession(club: .driver, speed: Double(90 + i), carry: 220)
            s.date = Date().addingTimeInterval(Double(i) * 3600)
            sessions.append(s)
        }

        let trend = PersonalStatsCalculator.speedTrend(sessions: sessions, club: .driver)
        XCTAssertEqual(trend.count, 10)
        XCTAssertTrue(trend.last!.value > trend.first!.value)
    }

    func testAllClubStats() {
        let sessions = [
            makeSession(club: .driver, speed: 100, carry: 230),
            makeSession(club: .sevenIron, speed: 80, carry: 150),
        ]
        let all = PersonalStatsCalculator.allClubStats(sessions: sessions)
        XCTAssertEqual(all.count, 2)
    }

    private func makeSession(club: ClubType, speed: Double, carry: Double) -> SwingSession {
        SwingSession(
            club: club,
            clubHeadSpeedMph: speed,
            ballSpeedMph: speed * BallSpeedCalculator.smashFactor(for: club),
            launchAngleDegrees: 12,
            carryDistanceYards: carry,
            totalDistanceYards: carry + 20
        )
    }
}

final class InsightEngineTests: XCTestCase {

    func testEarlyStageInsight() {
        let sessions = [makeSession(club: .driver, speed: 100, carry: 230)]
        let insights = InsightEngine.generate(sessions: sessions)
        XCTAssertEqual(insights.count, 1)
        XCTAssertEqual(insights[0].category, .milestone)
    }

    func testGeneratesInsightsWithEnoughData() {
        var sessions: [SwingSession] = []
        for i in 0..<10 {
            sessions.append(makeSession(
                club: .driver, speed: Double(95 + i), carry: Double(220 + i * 3)
            ))
        }
        for _ in 0..<5 {
            sessions.append(makeSession(club: .sevenIron, speed: 80, carry: 150))
        }

        let insights = InsightEngine.generate(sessions: sessions)
        XCTAssertFalse(insights.isEmpty)
    }

    func testInconsistentClubGeneratesImprovement() {
        let sessions = [
            makeSession(club: .driver, speed: 100, carry: 100, shape: .slice),
            makeSession(club: .driver, speed: 100, carry: 250, shape: .slice),
            makeSession(club: .driver, speed: 100, carry: 50, shape: .slice),
            makeSession(club: .driver, speed: 100, carry: 300, shape: .slice),
        ]

        let insights = InsightEngine.generate(sessions: sessions)
        let improvement = insights.filter { $0.category == .improvement }
        XCTAssertFalse(improvement.isEmpty)
    }

    func testGappingDetection() {
        var sessions: [SwingSession] = []
        for _ in 0..<3 {
            sessions.append(makeSession(club: .driver, speed: 100, carry: 230))
            sessions.append(makeSession(club: .threeWood, speed: 95, carry: 228))
        }

        let insights = InsightEngine.generate(sessions: sessions)
        let gapping = insights.filter { $0.category == .gapping }
        XCTAssertFalse(gapping.isEmpty)
    }

    private func makeSession(
        club: ClubType, speed: Double, carry: Double,
        shape: TrajectoryShape = .straight
    ) -> SwingSession {
        SwingSession(
            club: club,
            clubHeadSpeedMph: speed,
            ballSpeedMph: speed * BallSpeedCalculator.smashFactor(for: club),
            launchAngleDegrees: 12,
            carryDistanceYards: carry,
            totalDistanceYards: carry + 20,
            trajectoryShape: shape
        )
    }
}
