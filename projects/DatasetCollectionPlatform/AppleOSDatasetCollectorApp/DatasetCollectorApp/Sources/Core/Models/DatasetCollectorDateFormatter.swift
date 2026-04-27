import Foundation

enum DatasetCollectorDateFormatter {
    private static let formatter: ISO8601DateFormatter = {
        let value = ISO8601DateFormatter()
        value.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return value
    }()

    static func nowISO8601() -> String {
        formatter.string(from: Date())
    }
}
