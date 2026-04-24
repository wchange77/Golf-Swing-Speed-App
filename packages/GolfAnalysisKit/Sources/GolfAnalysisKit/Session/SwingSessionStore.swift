import Foundation

public actor SwingSessionStore {
    private let fileURL: URL
    private var sessions: [SwingSession] = []
    private var loaded = false

    private static let encoder: JSONEncoder = {
        let e = JSONEncoder()
        e.dateEncodingStrategy = .iso8601
        return e
    }()

    private static let decoder: JSONDecoder = {
        let d = JSONDecoder()
        d.dateDecodingStrategy = .iso8601
        return d
    }()

    public init(directory: URL? = nil) {
        let dir = directory ?? FileManager.default.urls(
            for: .documentDirectory, in: .userDomainMask
        ).first!.appendingPathComponent("GolfAnalysisKit", isDirectory: true)

        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        self.fileURL = dir.appendingPathComponent("swing_sessions.jsonl")
    }

    public func save(_ session: SwingSession) throws {
        try ensureLoaded()
        sessions.append(session)
        let line = try Self.encoder.encode(session)
        var data = line
        data.append(contentsOf: [UInt8(ascii: "\n")])
        if FileManager.default.fileExists(atPath: fileURL.path) {
            let handle = try FileHandle(forWritingTo: fileURL)
            handle.seekToEndOfFile()
            handle.write(data)
            handle.closeFile()
        } else {
            try data.write(to: fileURL)
        }
    }

    public func allSessions() throws -> [SwingSession] {
        try ensureLoaded()
        return sessions
    }

    public func sessions(for club: ClubType) throws -> [SwingSession] {
        try ensureLoaded()
        return sessions.filter { $0.club == club }
    }

    public func sessions(from startDate: Date, to endDate: Date) throws -> [SwingSession] {
        try ensureLoaded()
        return sessions.filter { $0.date >= startDate && $0.date <= endDate }
    }

    public func recentSessions(count: Int) throws -> [SwingSession] {
        try ensureLoaded()
        let sorted = sessions.sorted { $0.date > $1.date }
        return Array(sorted.prefix(count))
    }

    public func delete(id: UUID) throws {
        try ensureLoaded()
        sessions.removeAll { $0.id == id }
        try rewriteFile()
    }

    public func update(_ session: SwingSession) throws {
        try ensureLoaded()
        guard let idx = sessions.firstIndex(where: { $0.id == session.id }) else { return }
        sessions[idx] = session
        try rewriteFile()
    }

    public func sessionCount() throws -> Int {
        try ensureLoaded()
        return sessions.count
    }

    private func ensureLoaded() throws {
        guard !loaded else { return }
        loaded = true
        guard FileManager.default.fileExists(atPath: fileURL.path) else { return }
        let data = try Data(contentsOf: fileURL)
        let lines = data.split(separator: UInt8(ascii: "\n"))
        for line in lines {
            if let session = try? Self.decoder.decode(SwingSession.self, from: Data(line)) {
                sessions.append(session)
            }
        }
    }

    private func rewriteFile() throws {
        var data = Data()
        for session in sessions {
            let line = try Self.encoder.encode(session)
            data.append(line)
            data.append(contentsOf: [UInt8(ascii: "\n")])
        }
        try data.write(to: fileURL, options: .atomic)
    }
}
