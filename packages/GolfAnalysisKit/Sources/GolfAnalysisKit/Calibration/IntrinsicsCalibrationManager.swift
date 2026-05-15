import Foundation

public struct GolfIntrinsicsSample: Codable, Equatable {
    public let fx: Double
    public let fy: Double
    public let cx: Double
    public let cy: Double
    public let referenceWidth: Int
    public let referenceHeight: Int
    public let capturedAt: String?

    public init(
        fx: Double,
        fy: Double,
        cx: Double,
        cy: Double,
        referenceWidth: Int,
        referenceHeight: Int,
        capturedAt: String? = nil
    ) {
        self.fx = fx
        self.fy = fy
        self.cx = cx
        self.cy = cy
        self.referenceWidth = referenceWidth
        self.referenceHeight = referenceHeight
        self.capturedAt = capturedAt
    }

    public func pixelsPerMetre(atDistanceMeters distance: Double) -> Double? {
        guard distance > 0 else { return nil }
        return fx / distance
    }
}

public enum IntrinsicsCalibrationError: Error {
    case unsupportedFormat
    case missingIntrinsics
}

/// Reads `camera.json` sidecar produced by `AppleOSDatasetCollectorApp` and
/// exposes the `intrinsics` block for consumer apps. `SpeedCalculator` uses
/// `pixelsPerMetre` to convert pixel velocity into real-world speed.
public enum IntrinsicsCalibrationManager {
    private struct CameraSidecarShape: Decodable {
        struct Intrinsics: Decodable {
            let fx: Double
            let fy: Double
            let cx: Double
            let cy: Double
            let referenceWidth: Int
            let referenceHeight: Int
            let capturedAt: String?
        }
        struct Calibration: Decodable {
            let intrinsics: Intrinsics?
        }
        let intrinsics: Intrinsics?
        let calibration: Calibration?
    }

    public static func loadIntrinsics(from url: URL) throws -> GolfIntrinsicsSample {
        let data = try Data(contentsOf: url)
        let decoder = JSONDecoder()
        let shape = try decoder.decode(CameraSidecarShape.self, from: data)
        let source = shape.intrinsics ?? shape.calibration?.intrinsics
        guard let source else { throw IntrinsicsCalibrationError.missingIntrinsics }
        return GolfIntrinsicsSample(
            fx: source.fx,
            fy: source.fy,
            cx: source.cx,
            cy: source.cy,
            referenceWidth: source.referenceWidth,
            referenceHeight: source.referenceHeight,
            capturedAt: source.capturedAt
        )
    }

    public static func loadIntrinsics(fromJSON data: Data) throws -> GolfIntrinsicsSample {
        let shape = try JSONDecoder().decode(CameraSidecarShape.self, from: data)
        let source = shape.intrinsics ?? shape.calibration?.intrinsics
        guard let source else { throw IntrinsicsCalibrationError.missingIntrinsics }
        return GolfIntrinsicsSample(
            fx: source.fx,
            fy: source.fy,
            cx: source.cx,
            cy: source.cy,
            referenceWidth: source.referenceWidth,
            referenceHeight: source.referenceHeight,
            capturedAt: source.capturedAt
        )
    }
}
