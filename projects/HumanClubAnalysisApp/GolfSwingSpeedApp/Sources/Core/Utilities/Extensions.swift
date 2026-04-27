import Foundation
import CoreGraphics
import simd

extension Double {
    var formattedSpeed: String {
        String(format: "%.1f", self)
    }

    var formattedAngle: String {
        String(format: "%.0f°", self)
    }
}

extension CGPoint {
    func distance(to other: CGPoint) -> CGFloat {
        let dx = x - other.x
        let dy = y - other.y
        return sqrt(dx * dx + dy * dy)
    }
}

extension SIMD3 where Scalar == Float {
    func distance(to other: SIMD3<Float>) -> Float {
        simd_distance(self, other)
    }

    func angle(to other: SIMD3<Float>) -> Float {
        let dotProduct = simd_dot(simd_normalize(self), simd_normalize(other))
        let clamped = max(-1.0, min(1.0, dotProduct))
        return acos(clamped)
    }

    var degreesFromRadians: Float {
        self.x * 180.0 / .pi
    }
}

extension Float {
    var toDegrees: Float {
        self * 180.0 / .pi
    }

    var toRadians: Float {
        self * .pi / 180.0
    }
}

extension Date {
    var shortTimeString: String {
        let formatter = DateFormatter()
        formatter.timeStyle = .short
        return formatter.string(from: self)
    }

    var mediumDateString: String {
        let formatter = DateFormatter()
        formatter.dateStyle = .medium
        return formatter.string(from: self)
    }
}
