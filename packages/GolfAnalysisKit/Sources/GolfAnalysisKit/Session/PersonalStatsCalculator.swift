import Foundation

public struct ClubStats: Sendable {
    public var club: ClubType
    public var sessionCount: Int
    public var avgClubHeadSpeedMph: Double
    public var avgBallSpeedMph: Double
    public var avgCarryYards: Double
    public var avgTotalYards: Double
    public var avgLaunchAngle: Double
    public var bestCarryYards: Double
    public var bestBallSpeedMph: Double
    public var carryStdDev: Double
    public var speedStdDev: Double
    public var shapeCounts: [TrajectoryShape: Int]

    public var consistencyScore: Double {
        guard avgCarryYards > 0 else { return 0 }
        let cv = carryStdDev / avgCarryYards
        return max(0, min(1.0, 1.0 - cv * 3))
    }

    public var dominantShape: TrajectoryShape {
        shapeCounts.max(by: { $0.value < $1.value })?.key ?? .straight
    }
}

public struct TrendPoint: Sendable {
    public var date: Date
    public var value: Double
}

public struct PersonalBest: Sendable {
    public var club: ClubType
    public var metric: String
    public var value: Double
    public var date: Date
    public var sessionId: UUID
}

public struct PersonalStatsCalculator {

    public static func clubStats(sessions: [SwingSession], club: ClubType) -> ClubStats? {
        let filtered = sessions.filter { $0.club == club }
        guard !filtered.isEmpty else { return nil }
        let n = Double(filtered.count)

        let avgCHS = filtered.map(\.clubHeadSpeedMph).reduce(0, +) / n
        let avgBS = filtered.map(\.ballSpeedMph).reduce(0, +) / n
        let avgCarry = filtered.map(\.carryDistanceYards).reduce(0, +) / n
        let avgTotal = filtered.map(\.totalDistanceYards).reduce(0, +) / n
        let avgLA = filtered.map(\.launchAngleDegrees).reduce(0, +) / n
        let bestCarry = filtered.map(\.carryDistanceYards).max() ?? 0
        let bestSpeed = filtered.map(\.ballSpeedMph).max() ?? 0

        let carrySD = stdDev(filtered.map(\.carryDistanceYards))
        let speedSD = stdDev(filtered.map(\.ballSpeedMph))

        var shapes: [TrajectoryShape: Int] = [:]
        for s in filtered { shapes[s.trajectoryShape, default: 0] += 1 }

        return ClubStats(
            club: club,
            sessionCount: filtered.count,
            avgClubHeadSpeedMph: avgCHS,
            avgBallSpeedMph: avgBS,
            avgCarryYards: avgCarry,
            avgTotalYards: avgTotal,
            avgLaunchAngle: avgLA,
            bestCarryYards: bestCarry,
            bestBallSpeedMph: bestSpeed,
            carryStdDev: carrySD,
            speedStdDev: speedSD,
            shapeCounts: shapes
        )
    }

    public static func allClubStats(sessions: [SwingSession]) -> [ClubStats] {
        let clubs = Set(sessions.map(\.club))
        return clubs.compactMap { clubStats(sessions: sessions, club: $0) }
            .sorted { $0.avgCarryYards > $1.avgCarryYards }
    }

    public static func speedTrend(
        sessions: [SwingSession],
        club: ClubType? = nil,
        last count: Int = 30
    ) -> [TrendPoint] {
        var filtered = sessions
        if let club { filtered = filtered.filter { $0.club == club } }
        let sorted = filtered.sorted { $0.date < $1.date }.suffix(count)
        return sorted.map { TrendPoint(date: $0.date, value: $0.clubHeadSpeedMph) }
    }

    public static func carryTrend(
        sessions: [SwingSession],
        club: ClubType? = nil,
        last count: Int = 30
    ) -> [TrendPoint] {
        var filtered = sessions
        if let club { filtered = filtered.filter { $0.club == club } }
        let sorted = filtered.sorted { $0.date < $1.date }.suffix(count)
        return sorted.map { TrendPoint(date: $0.date, value: $0.carryDistanceYards) }
    }

    public static func personalBests(sessions: [SwingSession]) -> [PersonalBest] {
        var bests: [PersonalBest] = []
        let clubs = Set(sessions.map(\.club))

        for club in clubs {
            let clubSessions = sessions.filter { $0.club == club }

            if let best = clubSessions.max(by: { $0.carryDistanceYards < $1.carryDistanceYards }) {
                bests.append(PersonalBest(
                    club: club, metric: "carry",
                    value: best.carryDistanceYards, date: best.date, sessionId: best.id
                ))
            }
            if let best = clubSessions.max(by: { $0.ballSpeedMph < $1.ballSpeedMph }) {
                bests.append(PersonalBest(
                    club: club, metric: "ballSpeed",
                    value: best.ballSpeedMph, date: best.date, sessionId: best.id
                ))
            }
            if let best = clubSessions.max(by: { $0.clubHeadSpeedMph < $1.clubHeadSpeedMph }) {
                bests.append(PersonalBest(
                    club: club, metric: "clubHeadSpeed",
                    value: best.clubHeadSpeedMph, date: best.date, sessionId: best.id
                ))
            }
        }
        return bests
    }

    public static func clubGapping(sessions: [SwingSession]) -> [(ClubType, Double)] {
        let stats = allClubStats(sessions: sessions)
        return stats.map { ($0.club, $0.avgCarryYards) }
            .sorted { $0.1 > $1.1 }
    }

    public static func overallConsistency(sessions: [SwingSession]) -> Double {
        let stats = allClubStats(sessions: sessions)
        guard !stats.isEmpty else { return 0 }
        return stats.map(\.consistencyScore).reduce(0, +) / Double(stats.count)
    }

    private static func stdDev(_ values: [Double]) -> Double {
        guard values.count >= 2 else { return 0 }
        let mean = values.reduce(0, +) / Double(values.count)
        let variance = values.map { ($0 - mean) * ($0 - mean) }.reduce(0, +) / Double(values.count)
        return sqrt(variance)
    }
}
