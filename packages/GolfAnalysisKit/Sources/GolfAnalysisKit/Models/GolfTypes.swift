import Foundation

public enum SwingPhase: String, Codable, CaseIterable, Sendable {
    case address
    case backswing
    case top
    case earlyDownswing
    case lateDownswing
    case impact
    case postImpact
    case followThrough
}

public enum ClubType: String, Codable, CaseIterable, Identifiable, Sendable {
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

    public var id: String { rawValue }

    public var displayName: String {
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

public enum CalibrationMethod: String, Codable, Sendable {
    case manual
    case lidar
}

public struct CalibrationSnapshot: Codable, Sendable {
    public var method: CalibrationMethod
    public var pixelsPerMetre: Double
    public var impactZoneX: Double
    public var impactZoneY: Double
    public var cameraToSubjectDistance: Double?
    public var clubLength: Double?
    public var lieAngle: Double?
    public var armLength: Double?
    public var swingPlaneNormalX: Float?
    public var swingPlaneNormalY: Float?
    public var swingPlaneNormalZ: Float?
    public var groundPlaneY: Float?

    public init(
        method: CalibrationMethod,
        pixelsPerMetre: Double,
        impactZoneX: Double,
        impactZoneY: Double,
        cameraToSubjectDistance: Double? = nil,
        clubLength: Double? = nil,
        lieAngle: Double? = nil,
        armLength: Double? = nil,
        swingPlaneNormalX: Float? = nil,
        swingPlaneNormalY: Float? = nil,
        swingPlaneNormalZ: Float? = nil,
        groundPlaneY: Float? = nil
    ) {
        self.method = method
        self.pixelsPerMetre = pixelsPerMetre
        self.impactZoneX = impactZoneX
        self.impactZoneY = impactZoneY
        self.cameraToSubjectDistance = cameraToSubjectDistance
        self.clubLength = clubLength
        self.lieAngle = lieAngle
        self.armLength = armLength
        self.swingPlaneNormalX = swingPlaneNormalX
        self.swingPlaneNormalY = swingPlaneNormalY
        self.swingPlaneNormalZ = swingPlaneNormalZ
        self.groundPlaneY = groundPlaneY
    }
}

public enum SpeedUnit: String, Codable, CaseIterable, Sendable {
    case mph
    case kmh
    case ms

    public var displayName: String {
        switch self {
        case .mph: return "mph"
        case .kmh: return "km/h"
        case .ms: return "m/s"
        }
    }

    public func convert(fromMph speed: Double) -> Double {
        switch self {
        case .mph: return speed
        case .kmh: return speed * 1.60934
        case .ms: return speed * 0.44704
        }
    }
}
