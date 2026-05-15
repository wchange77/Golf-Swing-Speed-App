import CoreLocation
import Foundation

@MainActor
final class DatasetLocationManager: NSObject, ObservableObject {
    @Published private(set) var latestLocation: CollectorLocation?
    @Published private(set) var statusText: String = "定位未启动"
    @Published private(set) var isFetching: Bool = false

    private let manager = CLLocationManager()
    private var timeoutTask: Task<Void, Never>?
    private let timeoutSeconds: TimeInterval = 8.0

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
            statusText = "定位权限未开启（可跳过，会话将不记录 GPS）"
        @unknown default:
            statusText = "定位状态未知"
        }
    }

    func requestLocation() {
        guard manager.authorizationStatus == .authorizedWhenInUse
                || manager.authorizationStatus == .authorizedAlways else {
            statusText = "无定位权限，跳过 GPS"
            return
        }
        cancelTimeout()
        isFetching = true
        statusText = "正在获取 GPS…（最多 \(Int(timeoutSeconds)) 秒）"
        manager.startUpdatingLocation()
        timeoutTask = Task { [timeoutSeconds] in
            try? await Task.sleep(for: .seconds(timeoutSeconds))
            guard !Task.isCancelled else { return }
            await MainActor.run { self.handleTimeout() }
        }
    }

    func cancel() {
        cancelTimeout()
        manager.stopUpdatingLocation()
        isFetching = false
        if latestLocation == nil {
            statusText = "已跳过 GPS（会话不记录位置）"
        }
    }

    private func handleTimeout() {
        manager.stopUpdatingLocation()
        timeoutTask = nil
        isFetching = false
        if latestLocation == nil {
            statusText = "GPS 超时，可继续创建会话（会话不记录位置）"
        }
    }

    private func cancelTimeout() {
        timeoutTask?.cancel()
        timeoutTask = nil
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
        if location.horizontalAccuracy <= 30 {
            cancelTimeout()
            manager.stopUpdatingLocation()
            isFetching = false
        }
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
            cancelTimeout()
            self.manager.stopUpdatingLocation()
            isFetching = false
            statusText = "定位失败：\(error.localizedDescription)（可继续创建会话）"
        }
    }
}
