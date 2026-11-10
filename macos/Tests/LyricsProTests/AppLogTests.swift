import Foundation
import Testing
@testable import LyricsPro

struct AppLogTests {
    @Test func rotationBoundsFilesAndRetainsRecentEvents() throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: directory) }
        let log = AppLog(directory: directory, maxBytes: 160, backups: 2)
        for index in 0..<20 { log.write("test", "event-\(index) " + String(repeating: "x", count: 60)) }
        log.flush()
        let files = try FileManager.default.contentsOfDirectory(at: directory, includingPropertiesForKeys: nil)
        #expect(files.count == 3)
        for file in files { #expect(try Data(contentsOf: file).count <= 160) }
        let current = try String(contentsOf: directory.appendingPathComponent("app.log"), encoding: .utf8)
        #expect(current.contains("event-19"))
        log.write("large", String(repeating: "y", count: 10000))
        log.flush()
        #expect(try Data(contentsOf: directory.appendingPathComponent("app.log")).count <= 160)
    }

    @Test func invalidLogDirectoryDoesNotInterruptCaller() throws {
        let file = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try Data("not a directory".utf8).write(to: file)
        defer { try? FileManager.default.removeItem(at: file) }
        let log = AppLog(directory: file)
        log.write("test")
        log.flush()
        #expect(try String(contentsOf: file, encoding: .utf8) == "not a directory")
    }
}
