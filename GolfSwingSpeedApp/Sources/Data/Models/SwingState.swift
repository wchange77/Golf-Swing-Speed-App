import Foundation

enum SwingState: String {
    case idle
    case playerDetected
    case ready
    case swingInProgress
    case swingComplete
    case processing
    case result
}

enum SwingPhase: String, Codable, CaseIterable {
    case address
    case backswing
    case top
    case earlyDownswing
    case lateDownswing
    case impact
    case postImpact
    case followThrough
}

enum ClubType: String, Codable, CaseIterable, Identifiable {
    case driver
    case threeWood = "3-wood"
    case hybrid
    case fiveIron = "5-iron"
    case sixIron = "6-iron"
    case sevenIron = "7-iron"
    case eightIron = "8-iron"
    case nineIron = "9-iron"
    case pitchingWedge = "PW"
    case gapWedge = "GW"
    case sandWedge = "SW"
    case lobWedge = "LW"
    case speedStick = "Speed Stick"
    case other

    var id: String { rawValue }

    var displayName: String {
        switch self {
        case .driver: return "Driver"
        case .threeWood: return "3-Wood"
        case .hybrid: return "Hybrid"
        case .fiveIron: return "5 Iron"
        case .sixIron: return "6 Iron"
        case .sevenIron: return "7 Iron"
        case .eightIron: return "8 Iron"
        case .nineIron: return "9 Iron"
        case .pitchingWedge: return "Pitching Wedge"
        case .gapWedge: return "Gap Wedge"
        case .sandWedge: return "Sand Wedge"
        case .lobWedge: return "Lob Wedge"
        case .speedStick: return "Speed Stick"
        case .other: return "Other"
        }
    }
}

enum CalibrationMethod: String, Codable {
    case manual
    case lidar
}

struct CalibrationSnapshot: Codable, Sendable {
    var method: CalibrationMethod
    var pixelsPerMetre: Double
    var impactZoneX: Double
    var impactZoneY: Double
    var cameraToSubjectDistance: Double?
    var clubLength: Double?
    var lieAngle: Double?
    var armLength: Double?
    var swingPlaneNormalX: Float?
    var swingPlaneNormalY: Float?
    var swingPlaneNormalZ: Float?
    var groundPlaneY: Float?
}

enum AudioFeedbackMode: String, Codable, CaseIterable {
    case beep
    case voice
    case off

    var displayName: String {
        switch self {
        case .beep: return "Beep"
        case .voice: return "Voice"
        case .off: return "Off"
        }
    }
}

enum SpeedUnit: String, Codable, CaseIterable {
    case mph
    case kmh
    case ms

    var displayName: String {
        switch self {
        case .mph: return "mph"
        case .kmh: return "km/h"
        case .ms: return "m/s"
        }
    }

    func convert(fromMph speed: Double) -> Double {
        switch self {
        case .mph: return speed
        case .kmh: return speed * 1.60934
        case .ms: return speed * 0.44704
        }
    }
}
