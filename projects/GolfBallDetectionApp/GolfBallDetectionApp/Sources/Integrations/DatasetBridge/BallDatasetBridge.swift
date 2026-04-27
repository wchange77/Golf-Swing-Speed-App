import Foundation

struct SharedDatasetManifest: Codable {
    struct DatasetEntry: Codable {
        let key: String
        let path: String
        let samples: Int
        let format: String
    }

    let version: String
    let generatedAt: String
    let dataset: DatasetEntry?
    let datasets: [DatasetEntry]?
}

enum BallDatasetBridge {
    private static let defaultRelativePath = "../DatasetCollectionPlatform/exports/dataset_manifest.json"

    static func manifestPath() -> String {
        if let envPath = ProcessInfo.processInfo.environment["GOLF_BALL_MANIFEST_PATH"], !envPath.isEmpty {
            return envPath
        }
        if let envPath = ProcessInfo.processInfo.environment["DATASET_MANIFEST_PATH"], !envPath.isEmpty {
            return envPath
        }

        let candidates = sourceRelativeManifestCandidates() + [
            "../DatasetCollectionPlatform/exports/consumers/golf_ball_detection_app.json",
            defaultRelativePath,
            "../../DatasetCollectionPlatform/exports/consumers/golf_ball_detection_app.json",
            "../../DatasetCollectionPlatform/exports/dataset_manifest.json",
            "../../../DatasetCollectionPlatform/exports/consumers/golf_ball_detection_app.json",
            "../../../DatasetCollectionPlatform/exports/dataset_manifest.json",
            "projects/DatasetCollectionPlatform/exports/consumers/golf_ball_detection_app.json",
            "projects/DatasetCollectionPlatform/exports/dataset_manifest.json",
        ]

        let fileManager = FileManager.default
        for candidate in candidates where fileManager.fileExists(atPath: candidate) {
            return candidate
        }

        return defaultRelativePath
    }

    private static func sourceRelativeManifestCandidates() -> [String] {
        let sourceFile = URL(fileURLWithPath: #filePath)
        let projectsDir = (0..<6).reduce(sourceFile) { url, _ in
            url.deletingLastPathComponent()
        }
        let datasetRoot = projectsDir.appendingPathComponent("DatasetCollectionPlatform")
        return [
            datasetRoot.appendingPathComponent("exports/consumers/golf_ball_detection_app.json").path,
            datasetRoot.appendingPathComponent("exports/dataset_manifest.json").path,
        ]
    }

    static func loadManifest() -> SharedDatasetManifest? {
        let url = URL(fileURLWithPath: manifestPath())
        guard let data = try? Data(contentsOf: url) else { return nil }
        return try? JSONDecoder().decode(SharedDatasetManifest.self, from: data)
    }

    static func ballSampleCount() -> Int? {
        guard let manifest = loadManifest() else { return nil }
        if let dataset = manifest.dataset, dataset.key == "golf_ball_detection" {
            return dataset.samples
        }
        return manifest.datasets?.first(where: { $0.key == "golf_ball_detection" })?.samples
    }
}
