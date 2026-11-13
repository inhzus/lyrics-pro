import Foundation
import Testing
@testable import LyricsPro

/// Runs a shell-script stand-in at the bundled worker path; no Python or Music needed.
@MainActor
struct WorkerProcessTests {
    enum Outcome: Sendable, Equatable {
        case ready, exited(Int32), invalidOutput, writeFailed
    }

    private static let ready = #"{"version":2,"type":"ready","generation":0,"track":null,"payload":{}}"#

    private func launch(_ script: String) throws -> (WorkerProcess, AsyncStream<Outcome>, URL) {
        let bundle = FileManager.default.temporaryDirectory
            .appendingPathComponent("WorkerProcessTests-\(UUID()).app", isDirectory: true)
        let launch = BackendLaunch(bundleURL: bundle, inheritedEnvironment: [:])
        try FileManager.default.createDirectory(at: launch.executable.deletingLastPathComponent(),
                                                withIntermediateDirectories: true)
        try FileManager.default.createDirectory(at: launch.workingDirectory, withIntermediateDirectories: true)
        try Data("#!/bin/sh\n\(script)\n".utf8).write(to: launch.executable)
        try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: launch.executable.path)
        let (outcomes, continuation) = AsyncStream.makeStream(of: Outcome.self)
        // Keep diagnostics out of the user's real log folder.
        let log = AppLog(directory: bundle.appendingPathComponent("Logs", isDirectory: true))
        let worker = WorkerProcess(
            launch: launch, arguments: [], log: log,
            onEvent: { _, event, _ in if case .ready = event.payload { continuation.yield(.ready) } },
            onFailure: { _, failure in
                switch failure {
                case .exited(let status): continuation.yield(.exited(status))
                case .invalidOutput: continuation.yield(.invalidOutput)
                case .writeFailed: continuation.yield(.writeFailed)
                }
            })
        try worker.start()
        return (worker, outcomes, bundle)
    }

    @Test func eventsArriveAndStopEndsTheWorkerPromptly() async throws {
        // Ignoring SIGTERM leaves only stdin EOF to end `cat` before the 2 s kill deadline.
        let (worker, outcomes, bundle) = try launch("trap '' TERM; printf '%s\\n' '\(Self.ready)'; cat > /dev/null")
        defer { try? FileManager.default.removeItem(at: bundle) }
        var iterator = outcomes.makeAsyncIterator()
        #expect(await iterator.next() == .ready)
        worker.send(.setLanguage(.hokkien, requestID: 1))
        let started = Date()
        await worker.stop()
        #expect(!worker.isRunning)
        #expect(Date().timeIntervalSince(started) < 1.5)  // Well inside the 2 s kill deadline.
        #expect(await iterator.next() == .exited(0))
    }

    @Test func crashIsReportedWithItsStatus() async throws {
        let (worker, outcomes, bundle) = try launch("printf '%s\\n' '\(Self.ready)'; read line; exit 3")
        defer { try? FileManager.default.removeItem(at: bundle) }
        var iterator = outcomes.makeAsyncIterator()
        #expect(await iterator.next() == .ready)
        worker.send(.listRecordings(requestID: 1, generation: 0))
        #expect(await iterator.next() == .exited(3))
    }

    @Test func invalidOutputIsReported() async throws {
        let (worker, outcomes, bundle) = try launch("echo 'not json'; cat > /dev/null")
        defer { try? FileManager.default.removeItem(at: bundle) }
        var iterator = outcomes.makeAsyncIterator()
        #expect(await iterator.next() == .invalidOutput)
        await worker.stop()
    }
}
