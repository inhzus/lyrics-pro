import AppKit
import Foundation

/// One native writer owns app + worker log rotation; no writes on the UI thread.
final class AppLog: @unchecked Sendable {
    static let shared = AppLog()
    let directory: URL
    private let queue = DispatchQueue(label: "lyrics-pro.log-writer", qos: .utility)
    private let maxBytes: Int
    private let backups: Int

    init(directory: URL? = nil, maxBytes: Int = 2 * 1024 * 1024, backups: Int = 4) {
        self.directory = directory ?? FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/Lyrics Pro/Logs", isDirectory: true)
        self.maxBytes = maxBytes
        self.backups = backups
    }

    func write(_ event: String, _ detail: String = "") {
        let bounded = String(detail.prefix(4096)).replacingOccurrences(of: "\n", with: " ")
            .replacingOccurrences(of: "\r", with: " ")
        queue.async { [self] in
            let file = directory.appendingPathComponent("app.log")
            let text = "\(ISO8601DateFormatter().string(from: Date())) \(event) \(bounded)\n"
            let data = Data(text.utf8.prefix(maxBytes))
            do {
                let manager = FileManager.default
                try manager.createDirectory(at: directory, withIntermediateDirectories: true)
                let size = (try? manager.attributesOfItem(atPath: file.path)[.size] as? NSNumber)?.intValue ?? 0
                if size + data.count > maxBytes {
                    for index in stride(from: backups, through: 1, by: -1) {
                        let destination = directory.appendingPathComponent("app.log.\(index)")
                        let source = index == 1 ? file : directory.appendingPathComponent("app.log.\(index - 1)")
                        if manager.fileExists(atPath: destination.path) { try manager.removeItem(at: destination) }
                        if manager.fileExists(atPath: source.path) { try manager.moveItem(at: source, to: destination) }
                    }
                }
                if !manager.fileExists(atPath: file.path) { manager.createFile(atPath: file.path, contents: nil) }
                let handle = try FileHandle(forWritingTo: file)
                defer { try? handle.close() }
                try handle.seekToEnd()
                try handle.write(contentsOf: data)
            } catch {
                // Diagnostics must never prevent playback or worker startup.
            }
        }
    }

    func openFolder() {
        queue.async { [self] in
            try? FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
            Task { @MainActor in NSWorkspace.shared.open(self.directory) }
        }
    }

    // Used by tests after queued writes; production code never blocks the UI to flush.
    func flush() { queue.sync {} }
}
