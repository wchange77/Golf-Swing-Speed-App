import CoreLocation
import Foundation

@MainActor
final class DatasetLocationManager: NSObject, ObservableObject {
    @Published private(set) var latestLocation: CollectorLocation?
    @Published private(set) var statusText: String = "定位未启动"

    private let manager = CLLocationManager()

    override init() {
        super.init()
        manager.delegate = self
        manager.desiredAccuracy = kCLLocationAccuracyBest
        manager.distanceFilter = kCLDistanceFilterNone
    }

    func requestPermissionAndLocation() {
        switch manager.authorizationStatus {
        case .notDetermined:
            statusText = "等待定位授权"
            manager.requestWhenInUseAuthorization()
        case .authorizedWhenInUse, .authorizedAlways:
            requestLocation()
        case .denied, .restricted:
            statusText = "定位权限未开启"
        @unknown default:
            statusText = "定位状态未知"
        }
    }

    func requestLocation() {
        manager.requestLocation()
        statusText = "正在获取定位"
    }

    private func update(with location: CLLocation) {
        latestLocation = CollectorLocation(
            latitude: location.coordinate.latitude,
            longitude: location.coordinate.longitude,
            horizontalAccuracyMeters: max(location.horizontalAccuracy, 0),
            altitudeMeters: location.verticalAccuracy >= 0 ? location.altitude : nil,
            verticalAccuracyMeters: location.verticalAccuracy >= 0 ? location.verticalAccuracy : nil,
            capturedAt: DatasetCollectorDateFormatter.nowISO8601(),
            source: "ios_core_location"
        )
        statusText = String(format: "已定位：%.1f 米精度", max(location.horizontalAccuracy, 0))
    }
}

extension DatasetLocationManager: CLLocationManagerDelegate {
    nonisolated func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        Task { @MainActor in
            requestPermissionAndLocation()
        }
    }

    nonisolated func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        guard let location = locations.last else { return }
        Task { @MainActor in
            update(with: location)
        }
    }

    nonisolated func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {
        Task { @MainActor in
            statusText = "定位失败：\(error.localizedDescription)"
        }
    }
}
