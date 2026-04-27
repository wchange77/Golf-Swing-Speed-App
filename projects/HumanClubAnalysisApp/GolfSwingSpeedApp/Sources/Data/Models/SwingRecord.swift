import Foundation
import SwiftData

@Model
final class SwingRecord {
    var id: UUID
    var timestamp: Date
    var impactSpeedMph: Double?
    var confidenceScore: Double
    var clubType: String
    var sessionId: UUID?
    var videoURL: URL?
    var isBookmarked: Bool

    // Stored as JSON-encoded data for SwiftData compatibility
    var speedProfileData: Data?
    var lagMetricsData: Data?
    var calibrationSnapshotData: Data?

    init(
        id: UUID = UUID(),
        timestamp: Date = Date(),
        impactSpeedMph: Double? = nil,
        confidenceScore: Double = 0.0,
        clubType: ClubType = .driver,
        sessionId: UUID? = nil,
        videoURL: URL? = nil,
        isBookmarked: Bool = false
    ) {
        self.id = id
        self.timestamp = timestamp
        self.impactSpeedMph = impactSpeedMph
        self.confidenceScore = confidenceScore
        self.clubType = clubType.rawValue
        self.sessionId = sessionId
        self.videoURL = videoURL
        self.isBookmarked = isBookmarked
    }

    var speedProfile: SpeedProfile? {
        get {
            guard let data = speedProfileData else { return nil }
            return try? JSONDecoder().decode(SpeedProfile.self, from: data)
        }
        set {
            speedProfileData = try? JSONEncoder().encode(newValue)
        }
    }

    var lagMetrics: LagMetrics? {
        get {
            guard let data = lagMetricsData else { return nil }
            return try? JSONDecoder().decode(LagMetrics.self, from: data)
        }
        set {
            lagMetricsData = try? JSONEncoder().encode(newValue)
        }
    }

    var calibrationSnapshot: CalibrationSnapshot? {
        get {
            guard let data = calibrationSnapshotData else { return nil }
            return try? JSONDecoder().decode(CalibrationSnapshot.self, from: data)
        }
        set {
            calibrationSnapshotData = try? JSONEncoder().encode(newValue)
        }
    }

    var club: ClubType {
        ClubType(rawValue: clubType) ?? .driver
    }
}
