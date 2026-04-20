import Foundation
import CoreGraphics

@Observable
final class CalibrationManager {
    var firstPoint: CGPoint?
    var secondPoint: CGPoint?
    var impactZone: CGPoint?
    var knownDistanceMetres: Double?
    var calibrationData: CalibrationSnapshot?

    var isCalibrated: Bool {
        calibrationData != nil
    }

    var needsFirstPoint: Bool { firstPoint == nil }
    var needsSecondPoint: Bool { firstPoint != nil && secondPoint == nil }
    var needsDistance: Bool { firstPoint != nil && secondPoint != nil && knownDistanceMetres == nil }
    var needsImpactZone: Bool { knownDistanceMetres != nil && impactZone == nil }

    func setFirstPoint(_ point: CGPoint) {
        firstPoint = point
    }

    func setSecondPoint(_ point: CGPoint) {
        secondPoint = point
    }

    func setKnownDistance(_ metres: Double) {
        knownDistanceMetres = metres
        computeCalibration()
    }

    func setImpactZone(_ point: CGPoint) {
        impactZone = point
        finaliseCalibration()
    }

    func reset() {
        firstPoint = nil
        secondPoint = nil
        impactZone = nil
        knownDistanceMetres = nil
        calibrationData = nil
    }

    private func computeCalibration() {
        guard let p1 = firstPoint,
              let p2 = secondPoint,
              let distance = knownDistanceMetres,
              distance > 0 else { return }

        let pixelDistance = p1.distance(to: p2)
        guard pixelDistance > 0 else { return }

        let ppm = Double(pixelDistance) / distance

        calibrationData = CalibrationSnapshot(
            method: .manual,
            pixelsPerMetre: ppm,
            impactZoneX: 0,
            impactZoneY: 0
        )
    }

    private func finaliseCalibration() {
        guard var data = calibrationData, let zone = impactZone else { return }
        data.impactZoneX = Double(zone.x)
        data.impactZoneY = Double(zone.y)
        calibrationData = data
    }

    func convertPixelDistanceToMetres(_ pixels: CGFloat) -> Double? {
        guard let data = calibrationData, data.pixelsPerMetre > 0 else { return nil }
        return Double(pixels) / data.pixelsPerMetre
    }
}
