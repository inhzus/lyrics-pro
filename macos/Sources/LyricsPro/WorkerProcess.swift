import Foundation

/// The bundled worker process: launch, pipes, stderr capture and bounded termination.
/// It frames commands and events but knows nothing about Music state. Callbacks run
/// on the main actor and name the worker, so callers can ignore a replaced one.
final class WorkerProcess: Sendable {
    enum Failure: Sendable {
        case exited(Int32)
        case invalidOutput
        case writeFailed
    }

    typealias EventHandler = @MainActor @Sendable (WorkerProcess, BridgeEvent, DecodedArtwork?) -> Void
    typealias FailureHandler = @MainActor @Sendable (WorkerProcess, Failure) -> Void

    private let process = Process()
    private let stdin = Pipe(), stdout = Pipe(), stderr = Pipe()
    private let commandQueue = DispatchQueue(label: "lyrics-pro.commands")
    private let onEvent: EventHandler
    private let onFailure: FailureHandler
    private let log: AppLog

    init(launch: BackendLaunch, arguments: [String], log: AppLog = .shared, onEvent: @escaping EventHandler,
         onFailure: @escaping FailureHandler) {
        self.log = log
        self.onEvent = onEvent
        self.onFailure = onFailure
        process.executableURL = launch.executable
        process.arguments = arguments
        process.currentDirectoryURL = launch.workingDirectory
        process.environment = launch.environment
        process.standardInput = stdin
        process.standardOutput = stdout
        process.standardError = stderr
    }

    var isRunning: Bool { process.isRunning }

    func start() throws {
        // A worker can exit between isRunning and a pipe write. Report EPIPE
        // as a failure instead of terminating the native app.
        signal(SIGPIPE, SIG_IGN)
        let log = self.log
        process.terminationHandler = { [weak self] finished in
            log.write("worker_exit", "status=\(finished.terminationStatus)")
            // Reap orphaned scripts even after an unexpected worker crash.
            kill(-finished.processIdentifier, SIGTERM)
            guard let self else { return }
            self.closeInput()
            self.report(.exited(finished.terminationStatus))
        }
        try process.run()
        // Closing the parent's copies ensures EOF is observable on process exit.
        try? stdin.fileHandleForReading.close()
        try? stdout.fileHandleForWriting.close()
        try? stderr.fileHandleForWriting.close()
        readEvents()
        drainDiagnostics()
    }

    func send(_ command: WorkerCommand) {
        guard let data = try? command.frame() else { return }
        let input = stdin.fileHandleForWriting
        commandQueue.async { [weak self] in
            do {
                try input.write(contentsOf: data)
            } catch {
                self?.report(.writeFailed)
            }
        }
    }

    /// Closes stdin (EOF asks the worker to stop), then terminates it within a bounded wait.
    func stop() async {
        closeInput()
        let process = self.process
        if process.isRunning { process.terminate() }
        // Wait away from the UI thread. Signals/EOF normally stop the worker within
        // 100 ms; a bounded group kill also covers a stuck script or worker.
        await Task.detached {
            let deadline = Date().addingTimeInterval(2)
            while process.isRunning && Date() < deadline {
                try? await Task.sleep(for: .milliseconds(50))
            }
            if process.isRunning {
                kill(-process.processIdentifier, SIGKILL)
                kill(process.processIdentifier, SIGKILL)
            }
            process.waitUntilExit()
        }.value
    }

    private func closeInput() {
        let input = stdin.fileHandleForWriting
        commandQueue.async { try? input.close() }
    }

    private func report(_ failure: Failure) {
        Task { @MainActor in onFailure(self, failure) }
    }

    private func readEvents() {
        let handle = stdout.fileHandleForReading
        DispatchQueue(label: "lyrics-pro.events").async { [self] in
            defer { try? handle.close() }
            do {
                try EventStream.read(from: handle) { event in
                    // Decode/downsample on the event queue; the UI only wraps the immutable bitmap.
                    var artwork: DecodedArtwork?
                    if case .artwork(let image) = event.payload { artwork = DecodedArtwork(base64: image) }
                    // The main queue preserves event order.
                    DispatchQueue.main.async { self.onEvent(self, event, artwork) }
                }
            } catch {
                log.write("bridge_read_error", String(describing: error))
                report(.invalidOutput)
            }
        }
    }

    private func drainDiagnostics() {
        // Drain stderr separately so diagnostics can never fill a pipe and stall polling.
        let handle = stderr.fileHandleForReading, log = self.log
        DispatchQueue(label: "lyrics-pro.diagnostics").async {
            defer { try? handle.close() }
            while true {
                let data = handle.availableData
                if data.isEmpty { break }
                log.write("worker", String(decoding: data.prefix(4096), as: UTF8.self))
            }
        }
    }
}
