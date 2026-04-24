import Foundation
import CoreGraphics

public struct TrajectoryPoint: Sendable, Codable {
    public var x: Double
    public var y: Double
    public var z: Double
    public var time: Double

    public var cgPoint: CGPoint { CGPoint(x: x, y: y) }

    public init(x: Double, y: Double, z: Double = 0, time: Double = 0) {
        self.x = x
        self.y = y
        self.z = z
        self.time = time
    }
}

public enum TrajectoryShape: String, Codable, Sendable, CaseIterable {
    case hook
    case draw
    case straight
    case fade
    case slice

    public var curveOffset: Double {
        switch self {
        case .hook: return -0.15
        case .draw: return -0.08
        case .straight: return 0
        case .fade: return 0.08
        case .slice: return 0.15
        }
    }

    public static func from(sidespinRPM: Double) -> TrajectoryShape {
        switch sidespinRPM {
        case ..<(-300): return .hook
        case -300..<(-100): return .draw
        case -100...100: return .straight
        case 100...300: return .fade
        default: return .slice
        }
    }
}

public enum TrajectoryHeight: String, Codable, Sendable {
    case low
    case medium
    case high

    public var heightMultiplier: Double {
        switch self {
        case .low: return 0.15
        case .medium: return 0.25
        case .high: return 0.35
        }
    }

    public static func from(club: ClubType) -> TrajectoryHeight {
        switch club {
        case .driver, .threeWood: return .low
        case .hybrid, .fiveIron, .sixIron, .sevenIron: return .medium
        case .eightIron, .nineIron, .pitchingWedge: return .medium
        case .gapWedge, .sandWedge, .lobWedge: return .high
        case .speedStick: return .low
        case .other: return .medium
        }
    }
}

public struct BezierTrajectoryModel {

    public struct Config: Sendable {
        public var sampleCount: Int
        public var height: TrajectoryHeight
        public var shape: TrajectoryShape

        public init(
            sampleCount: Int = 60,
            height: TrajectoryHeight = .medium,
            shape: TrajectoryShape = .straight
        ) {
            self.sampleCount = sampleCount
            self.height = height
            self.shape = shape
        }
    }

    public static func generate(
        origin: CGPoint,
        landing: CGPoint,
        config: Config = Config()
    ) -> [TrajectoryPoint] {
        let apexX = (origin.x + landing.x) / 2.0
        let apexY = Swift.min(Double(origin.y), Double(landing.y)) - config.height.heightMultiplier
        let controlX = 2.0 * apexX - 0.5 * (Double(origin.x) + Double(landing.x))
        let controlY = 2.0 * apexY - 0.5 * (Double(origin.y) + Double(landing.y))

        let n = Swift.max(10, config.sampleCount)
        var points: [TrajectoryPoint] = []
        points.reserveCapacity(n + 1)

        for i in 0...n {
            let t = Double(i) / Double(n)
            let oneMinusT = 1.0 - t

            let curveX = config.shape.curveOffset * t
            let bx = oneMinusT * oneMinusT * Double(origin.x)
                + 2.0 * oneMinusT * t * (controlX + curveX)
                + t * t * Double(landing.x)
            let by = oneMinusT * oneMinusT * Double(origin.y)
                + 2.0 * oneMinusT * t * controlY
                + t * t * Double(landing.y)

            points.append(TrajectoryPoint(x: bx, y: by, z: 0, time: t))
        }

        return points
    }

    public static func generate(
        origin: CGPoint,
        distanceYards: Double,
        club: ClubType,
        sidespinRPM: Double = 0,
        frameWidth: Double = 1920,
        frameHeight: Double = 1080
    ) -> [TrajectoryPoint] {
        let normalizedDistance = Swift.min(1.0, distanceYards / 300.0)
        let landingX = Double(origin.x) + normalizedDistance * (frameWidth - Double(origin.x))
        let landingY = Double(origin.y)
        let landing = CGPoint(x: landingX, y: landingY)

        let config = Config(
            sampleCount: 60,
            height: TrajectoryHeight.from(club: club),
            shape: TrajectoryShape.from(sidespinRPM: sidespinRPM)
        )

        return generate(origin: origin, landing: landing, config: config)
    }
}
