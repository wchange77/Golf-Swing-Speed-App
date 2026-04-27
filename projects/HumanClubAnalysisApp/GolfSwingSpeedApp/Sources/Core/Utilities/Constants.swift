import Foundation

enum AppConstants {
    static let appName = "Golf Swing Speed App"
    static let appVersion = "0.02.10"

    enum Camera {
        static let targetFPS: Double = 240
        static let fallbackFPS: Double = 120
        static let captureWidth: Int = 1920
        static let captureHeight: Int = 1080
    }

    enum Calibration {
        static let minLieAngleDegrees: Double = 50
        static let maxLieAngleDegrees: Double = 70
        static let minClubLengthMetres: Double = 0.60
        static let maxClubLengthMetres: Double = 1.25
        static let recommendedCameraDistanceMetres: Double = 2.0
        static let maxCameraDistanceMetres: Double = 3.0
    }

    enum SwingDetection {
        static let stillnessThresholdSeconds: Double = 0.5
        static let minSwingDurationSeconds: Double = 0.5
        static let maxSwingDurationSeconds: Double = 3.0
        static let motionOnsetThreshold: Double = 15.0
    }

    enum Speed {
        static let metersPerSecondToMph: Double = 2.23694
        static let metersPerSecondToKmh: Double = 3.6
    }

    enum LagAnalysis {
        static let castingLRIThreshold: Double = 0.4
        static let goodLagLRIThreshold: Double = 0.5
        static let castingReleasePointThreshold: Double = 90.0
        static let goodReleasePointThreshold: Double = 50.0
        static let speedLossPerTenDegreesLag: Double = 5.0
    }

    enum History {
        static let freeSwingLimit: Int = 50
    }

    /// Swing plane angles from ground, in degrees.
    /// Source: TrackMan data for scratch golfers.
    /// More upright planes (irons/wedges) need less 3D correction than flatter planes (driver).
    enum SwingPlane {
        static let angles: [ClubType: Double] = [
            .driver: 48.0,
            .threeWood: 51.0,
            .hybrid: 55.0,
            .fiveIron: 57.0,
            .sixIron: 59.0,
            .sevenIron: 60.0,
            .eightIron: 61.0,
            .nineIron: 62.0,
            .pitchingWedge: 63.0,
            .gapWedge: 63.5,
            .sandWedge: 64.0,
            .lobWedge: 64.5,
            .speedStick: 48.0,
            .other: 55.0,
        ]

        /// Average swing radii (arm + club length, in metres).
        static let typicalSwingRadius: [ClubType: Double] = [
            .driver: 1.75,
            .threeWood: 1.70,
            .hybrid: 1.60,
            .fiveIron: 1.55,
            .sixIron: 1.50,
            .sevenIron: 1.45,
            .eightIron: 1.40,
            .nineIron: 1.35,
            .pitchingWedge: 1.30,
            .gapWedge: 1.28,
            .sandWedge: 1.25,
            .lobWedge: 1.22,
            .speedStick: 1.70,
            .other: 1.50,
        ]

        /// Get the swing plane angle for a club type, falling back to default.
        static func angle(for club: ClubType) -> Double {
            angles[club] ?? 55.0
        }

        /// Get the typical swing radius for a club type, falling back to default.
        static func radius(for club: ClubType) -> Double {
            typicalSwingRadius[club] ?? 1.50
        }
    }
}
