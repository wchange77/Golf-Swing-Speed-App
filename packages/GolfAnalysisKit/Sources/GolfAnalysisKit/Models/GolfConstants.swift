import Foundation

public enum GolfConstants {

    public enum Camera {
        public static let targetFPS: Double = 240
        public static let fallbackFPS: Double = 120
        public static let captureWidth: Int = 1920
        public static let captureHeight: Int = 1080
    }

    public enum Calibration {
        public static let minLieAngleDegrees: Double = 50
        public static let maxLieAngleDegrees: Double = 70
        public static let minClubLengthMetres: Double = 0.60
        public static let maxClubLengthMetres: Double = 1.25
        public static let recommendedCameraDistanceMetres: Double = 2.0
        public static let maxCameraDistanceMetres: Double = 3.0
    }

    public enum SwingDetection {
        public static let stillnessThresholdSeconds: Double = 0.5
        public static let minSwingDurationSeconds: Double = 0.5
        public static let maxSwingDurationSeconds: Double = 3.0
        public static let motionOnsetThreshold: Double = 15.0
    }

    public enum Speed {
        public static let metersPerSecondToMph: Double = 2.23694
        public static let metersPerSecondToKmh: Double = 3.6
    }

    public enum LagAnalysis {
        public static let castingLRIThreshold: Double = 0.4
        public static let goodLagLRIThreshold: Double = 0.5
        public static let castingReleasePointThreshold: Double = 90.0
        public static let goodReleasePointThreshold: Double = 50.0
        public static let speedLossPerTenDegreesLag: Double = 5.0
    }

    public enum SwingPlane {
        public static let angles: [ClubType: Double] = [
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

        public static let typicalSwingRadius: [ClubType: Double] = [
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

        public static func angle(for club: ClubType) -> Double {
            angles[club] ?? 55.0
        }

        public static func radius(for club: ClubType) -> Double {
            typicalSwingRadius[club] ?? 1.50
        }
    }
}
