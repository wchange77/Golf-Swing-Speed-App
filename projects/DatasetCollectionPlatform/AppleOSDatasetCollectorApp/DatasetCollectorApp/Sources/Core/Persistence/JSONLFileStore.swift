import Foundation

enum JSONLStoreError: LocalizedError {
    case invalidUTF8

    var errorDescription: String? {
        switch self {
        case .invalidUTF8:
            return "无法将数据编码为 UTF-8 文本。"
        }
    }
}

final class JSONLFileStore {
    private let encoder: JSONEncoder
    private let baseDirectory: URL
    private let fileManager = FileManager.default

    init(customBaseDirectory: URL? = nil) {
        self.encoder = JSONEncoder()
        self.encoder.outputFormatting = [.sortedKeys]

        if let customBaseDirectory {
            self.baseDirectory = customBaseDirectory
        } else {
            let documents = fileManager.urls(for: .documentDirectory, in: .userDomainMask).first!
            self.baseDirectory = documents.appendingPathComponent("DatasetCollectorExport", isDirectory: true)
        }
    }

    var sessionsFileURL: URL { baseDirectory.appendingPathComponent("sessions.jsonl") }
    var samplesFileURL: URL { baseDirectory.appendingPathComponent("samples.jsonl") }
    var duplicatesFileURL: URL { baseDirectory.appendingPathComponent("duplicates.jsonl") }
    var assetsDirectoryURL: URL { baseDirectory.appendingPathComponent("assets", isDirectory: true) }
    var annotationsDirectoryURL: URL { baseDirectory.appendingPathComponent("annotations", isDirectory: true) }

    func bootstrap() throws {
        try fileManager.createDirectory(at: baseDirectory, withIntermediateDirectories: true)
        try fileManager.createDirectory(at: assetsDirectoryURL, withIntermediateDirectories: true)
        try fileManager.createDirectory(at: annotationsDirectoryURL, withIntermediateDirectories: true)

        if !fileManager.fileExists(atPath: sessionsFileURL.path) {
            fileManager.createFile(atPath: sessionsFileURL.path, contents: Data())
        }
        if !fileManager.fileExists(atPath: samplesFileURL.path) {
            fileManager.createFile(atPath: samplesFileURL.path, contents: Data())
        }
        if !fileManager.fileExists(atPath: duplicatesFileURL.path) {
            fileManager.createFile(atPath: duplicatesFileURL.path, contents: Data())
        }
    }

    func append<T: Encodable>(_ record: T, to fileURL: URL) throws {
        try bootstrap()
        let data = try encoder.encode(record)
        guard var line = String(data: data, encoding: .utf8) else {
            throw JSONLStoreError.invalidUTF8
        }
        line.append("\n")
        let fh = try FileHandle(forWritingTo: fileURL)
        defer { try? fh.close() }
        try fh.seekToEnd()
        guard let lineData = line.data(using: .utf8) else {
            throw JSONLStoreError.invalidUTF8
        }
        try fh.write(contentsOf: lineData)
    }

    func readRecords<T: Decodable>(_ type: T.Type, from fileURL: URL) throws -> [T] {
        try bootstrap()
        let raw = try String(contentsOf: fileURL, encoding: .utf8)
        if raw.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            return []
        }

        let decoder = JSONDecoder()
        var results: [T] = []
        for line in raw.split(whereSeparator: \.isNewline) {
            let data = Data(line.utf8)
            let record = try decoder.decode(T.self, from: data)
            results.append(record)
        }
        return results
    }

    func exportDirectory() throws -> URL {
        try bootstrap()
        return baseDirectory
    }

    func relativeExportPath(for url: URL) -> String {
        if let range = url.path.range(of: baseDirectory.path) {
            let suffix = String(url.path[range.upperBound...])
            return "ios_export\(suffix.replacingOccurrences(of: "\\", with: "/"))"
        }
        return "ios_export/\(url.lastPathComponent)"
    }
}
