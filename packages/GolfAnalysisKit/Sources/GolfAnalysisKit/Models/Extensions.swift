import Foundation
import CoreGraphics
import simd

extension CGPoint {
    public func distance(to other: CGPoint) -> CGFloat {
        let dx = x - other.x
        let dy = y - other.y
        return sqrt(dx * dx + dy * dy)
    }
}

extension SIMD3 where Scalar == Float {
    public func distance(to other: SIMD3<Float>) -> Float {
        simd_distance(self, other)
    }

    public func angle(to other: SIMD3<Float>) -> Float {
        let dotProduct = simd_dot(simd_normalize(self), simd_normalize(other))
        let clamped = Swift.max(-1.0, Swift.min(1.0, dotProduct))
        return acos(clamped)
    }
}

extension Float {
    public var toDegrees: Float {
        self * 180.0 / .pi
    }

    public var toRadians: Float {
        self * .pi / 180.0
    }
}
