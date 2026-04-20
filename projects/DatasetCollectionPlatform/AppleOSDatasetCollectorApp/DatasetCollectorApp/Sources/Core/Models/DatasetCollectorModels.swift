import Foundation

enum DatasetDomain: String, Codable, CaseIterable, Identifiable {
    case humanClub = "human_club"
    case golfBallDetection = "golf_ball_detection"

    var id: String { rawValue }

    var title: String {
        switch self {
        case .humanClub:
            return "人体+球杆"
        case .golfBallDetection:
            return "高尔夫球检测"
        }
    }
}

struct CollectorCaptureConfig: Codable {
    let fps: Int
    let resolution: String
}

struct CollectorEnvironment: Codable {
    let sceneType: String
    let lighting: String
    let tripod: Bool
    let distanceMeters: Double?
}

struct CollectorSessionRecord: Codable, Identifiable {
    let sessionId: String
    var id: String { sessionId }
    let collector: String
    let device: String
    let deviceProfile: String
    let createdAt: String
    let status: String
    let iosVersion: String
    let appVersion: String
    let captureConfig: CollectorCaptureConfig
    let environment: CollectorEnvironment
    let targetDomains: [String]
    let notes: String
}

struct CollectorSampleMetadata: Codable {
    let fps: Int
    let resolution: String
    let clubType: String
    let handedness: String
    let swingIntensity: String
    let surface: String
}

struct CollectorSampleRecord: Codable, Identifiable {
    let sampleId: String
    var id: String { sampleId }
    let domain: String
    let sha256: String
    let hashAlgorithm: String
    let assetPath: String
    let annotationPath: String?
    let fileSize: Int
    let sessionId: String
    let collector: String
    let device: String
    let deviceProfile: String
    let capturedAt: String
    let sourcePath: String
    let shotId: String?
    let takeIndex: Int
    let tags: [String]
    let metadata: CollectorSampleMetadata
    let status: String
}

struct CollectorDuplicateRecord: Codable {
    let duplicateAt: String
    let domain: String
    let sha256: String
    let incomingFile: String
    let incomingSourcePath: String
    let existingSampleId: String
    let sessionId: String
    let collector: String
    let metadata: CollectorSampleMetadata
}
