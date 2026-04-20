import Foundation

struct HumanClubDatasetManifest: Codable {
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

enum HumanClubDatasetBridge {
    private static let defaultRelativePath = "../DatasetCollectionPlatform/exports/dataset_manifest.json"

    static func manifestPath() -> String {
        if let envPath = ProcessInfo.processInfo.environment["HUMAN_CLUB_MANIFEST_PATH"], !envPath.isEmpty {
            return envPath
        }
        if let envPath = ProcessInfo.processInfo.environment["DATASET_MANIFEST_PATH"], !envPath.isEmpty {
            return envPath
        }

        let candidates = [
            "../DatasetCollectionPlatform/exports/consumers/human_club_analysis_app.json",
            defaultRelativePath,
            "../../DatasetCollectionPlatform/exports/consumers/human_club_analysis_app.json",
            "../../DatasetCollectionPlatform/exports/dataset_manifest.json",
            "../../../DatasetCollectionPlatform/exports/consumers/human_club_analysis_app.json",
            "../../../DatasetCollectionPlatform/exports/dataset_manifest.json",
            "projects/DatasetCollectionPlatform/exports/consumers/human_club_analysis_app.json",
            "projects/DatasetCollectionPlatform/exports/dataset_manifest.json",
        ]

        let fileManager = FileManager.default
        for candidate in candidates where fileManager.fileExists(atPath: candidate) {
            return candidate
        }

        return defaultRelativePath
    }

    static func loadManifest() -> HumanClubDatasetManifest? {
        let url = URL(fileURLWithPath: manifestPath())
        guard let data = try? Data(contentsOf: url) else { return nil }
        return try? JSONDecoder().decode(HumanClubDatasetManifest.self, from: data)
    }

    static func humanClubSampleCount() -> Int? {
        guard let manifest = loadManifest() else { return nil }
        if let dataset = manifest.dataset, dataset.key == "human_club" {
            return dataset.samples
        }
        return manifest.datasets?.first(where: { $0.key == "human_club" })?.samples
    }
}
