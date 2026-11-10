import AppKit
import Combine
import Foundation

private struct BackendConfiguration: Decodable {
    let projectRoot: String
    let python: String
}

@MainActor
final class MusicConnection: ObservableObject {
    @Published var demo: DemoSong? {
        didSet {
            controls.clearIntents(now: Self.now)
            refreshPresentation()
        }
    }
    @Published private(set) var state = LiveMusicState()
    @Published private(set) var artworkImage: NSImage?
    @Published private(set) var restarting = false
    @Published private(set) var language = PronunciationLanguage.saved()
    @Published private(set) var controls = PlaybackControlState()
    @Published private(set) var presentation = PlaybackPresentation()
    @Published private(set) var updatingMusic = false
    private var clockTask: Task<Void, Never>?
    private static var now: Double { ProcessInfo.processInfo.systemUptime }
    private var controlRevision = 0
    private var process: Process?
    private var input: FileHandle?
    private var session: UUID?
    private var receivedReady = false
    private let commandQueue = DispatchQueue(label: "lyrics-pro.commands")

    func start() {
        guard process == nil else { return }
        // A worker can exit between isRunning and a pipe write. Report EPIPE
        // through the connection state instead of terminating the native app.
        signal(SIGPIPE, SIG_IGN)
        state = LiveMusicState()
        controls = PlaybackControlState()
        refreshPresentation()
        artworkImage = nil
        do {
            guard let configURL = Bundle.main.url(forResource: "Backend", withExtension: "json") else {
                state.fail("Backend configuration is missing. Rebuild Lyrics Pro using scripts/build-macos.fish.")
                return
            }
            let config = try JSONDecoder().decode(BackendConfiguration.self, from: Data(contentsOf: configURL))
            guard FileManager.default.isExecutableFile(atPath: config.python),
                  FileManager.default.fileExists(atPath: config.projectRoot + "/src/lyrics_pro/bridge.py") else {
                state.fail("Python environment or project is missing. Run uv sync --locked in the project, then rebuild the app if the project moved.")
                return
            }
            let worker = Process()
            let stdin = Pipe(), stdout = Pipe(), stderr = Pipe()
            let run = UUID()
            session = run
            receivedReady = false
            worker.executableURL = URL(fileURLWithPath: config.python)
            worker.arguments = ["-u", "-m", "lyrics_pro.bridge", "--language", language.rawValue]
            worker.currentDirectoryURL = URL(fileURLWithPath: config.projectRoot)
            var environment = ProcessInfo.processInfo.environment
            environment["PYTHONPATH"] = config.projectRoot + "/src"
            environment["PYTHONUNBUFFERED"] = "1"
            worker.environment = environment
            worker.standardInput = stdin
            worker.standardOutput = stdout
            worker.standardError = stderr
            worker.terminationHandler = { [weak self] finished in
                // Reap orphaned scripts even after an unexpected worker crash.
                kill(-finished.processIdentifier, SIGTERM)
                Task { @MainActor [weak self] in
                    guard let self, self.session == run else { return }
                    self.session = nil
                    self.process = nil
                    self.closeInput()
                    self.artworkImage = nil
                    self.state.fail("The Music connection stopped (exit \(finished.terminationStatus)). Choose Reconnect to try again.")
                    self.controls.disconnect()
                    self.clockTask?.cancel()
                    self.refreshPresentation()
                }
            }
            try worker.run()
            process = worker
            input = stdin.fileHandleForWriting
            clockTask?.cancel()
            clockTask = Task { [weak self] in
                while !Task.isCancelled {
                    try? await Task.sleep(for: .milliseconds(100))
                    guard !Task.isCancelled, let self else { return }
                    var updated = self.controls
                    if updated.expire(now: Self.now) { self.controls = updated }
                    self.dispatchNextControl()
                    self.refreshPresentation()
                }
            }
            // Closing the parent's copies ensures EOF is observable on process exit.
            try? stdin.fileHandleForReading.close()
            try? stdout.fileHandleForWriting.close()
            try? stderr.fileHandleForWriting.close()

            DispatchQueue(label: "lyrics-pro.events").async { [weak self] in
                let handle = stdout.fileHandleForReading
                defer { try? handle.close() }
                do {
                    try EventStream.read(from: handle) { event in
                        DispatchQueue.main.async { [weak self] in self?.receive(event, session: run) }
                    }
                } catch {
                    Task { @MainActor [weak self] in
                        guard let self, self.session == run else { return }
                        await self.shutdown()
                        self.state.fail("The Music worker returned invalid data. Rebuild the app and choose Reconnect.")
                    }
                }
            }
            // Drain stderr separately so diagnostics can never fill a pipe and stall polling.
            DispatchQueue(label: "lyrics-pro.diagnostics").async {
                let handle = stderr.fileHandleForReading
                defer { try? handle.close() }
                while true {
                    let data = handle.availableData
                    if data.isEmpty { break }
                    NSLog("Lyrics Pro worker: %@", String(decoding: data, as: UTF8.self))
                }
            }
            Task { [weak self] in
                try? await Task.sleep(for: .seconds(8))
                guard let self, self.session == run, !self.receivedReady else { return }
                await self.shutdown()
                self.state.fail("The Music worker did not start. Check the Python environment and choose Reconnect.")
            }
        } catch {
            process = nil
            session = nil
            state.fail("Could not start the Music connection: \(error.localizedDescription)")
        }
    }

    private func receive(_ event: BridgeEvent, session run: UUID) {
        guard session == run else { return }
        if event.type == "ready" { receivedReady = true }
        let previousArtwork = state.artwork
        state.apply(event)
        controls.receive(event, now: Self.now)
        if state.phase != .live { controls.disconnect() }
        dispatchNextControl()
        refreshPresentation()
        if state.artwork != previousArtwork {
            artworkImage = state.artwork.flatMap { NSImage(data: $0) }
        }
    }

    func reconnect() {
        guard !restarting else { return }
        restarting = true
        Task {
            await shutdown()
            start()
            restarting = false
        }
    }

    func selectLanguage(_ value: PronunciationLanguage) {
        guard language != value else { return }
        language = value
        UserDefaults.standard.set(value.rawValue, forKey: PronunciationLanguage.preferenceKey)
        sendLyricCommand("language")
    }

    func retryLyrics() { sendLyricCommand("retry_lyrics") }

    func chooseRecording(_ candidate: RecordingCandidate, generation: Int, requestID: Int) {
        guard demo == nil, state.phase == .live, state.generation == generation,
              state.lyric?.requestID == requestID, state.lyric?.status == .chooseRecording,
              state.lyric?.candidates?.contains(where: { $0.id == candidate.id }) == true else { return }
        sendLyricCommand("choose_recording", extra: ["song_id": candidate.id, "choice_request_id": requestID])
    }

    func forgetRecording() { sendLyricCommand("forget_recording") }

    var canControl: Bool {
        demo == nil && state.phase == .live &&
        ["playing", "paused"].contains(state.playback?.state ?? "")
    }

    var canSeek: Bool {
        canControl && (state.playback?.duration ?? 0) > 0
    }

    func control(_ action: PlaybackAction, position: Double? = nil, resumeFollowing: Bool = false,
                 expectedGeneration: Int? = nil) {
        guard canControl, let track = state.identity,
              let process, process.isRunning else { return }
        guard !action.isSkip || !controls.skipBusy else { return }
        if let expectedGeneration, expectedGeneration != state.generation { return }
        var target = position
        if action == .seek {
            guard canSeek, let position, position.isFinite, let duration = state.playback?.duration else { return }
            target = min(duration, max(0, position))
        }
        controlRevision += 1
        let id = controlRevision
        let command = PlaybackCommand(command_id: id, action: action, generation: state.generation,
                                      track: track, position: target)
        controls.enqueue(command, resumeFollowing: resumeFollowing, now: Self.now)
        dispatchNextControl()
        refreshPresentation()
    }

    private func dispatchNextControl() {
        guard canControl, controls.inFlight == nil, !controls.queued.isEmpty,
              let input, let run = session, process?.isRunning == true,
              let command = controls.takeNext(now: Self.now) else { return }
        guard var data = try? JSONEncoder().encode(command) else { return }
        data.append(10)
        writeCommand(data, input: input, session: run)
    }

    private func refreshPresentation() {
        let now = Self.now
        let value = controls.presentation(at: now)
        if presentation != value { presentation = value }
        let updating = demo == nil && controls.isUpdating(at: now)
        if updatingMusic != updating { updatingMusic = updating }
    }

    private func sendLyricCommand(_ command: String, extra: [String: Any] = [:]) {
        guard let process, let input, let run = session, process.isRunning else { return }
        state.prepareLyrics(requestID: state.lyricRequestID + 1)
        var payload: [String: Any] = ["version": 1, "command": command,
                                      "language": language.rawValue, "request_id": state.lyricRequestID,
                                      "generation": state.generation]
        payload.merge(extra) { _, value in value }
        guard var data = try? JSONSerialization.data(withJSONObject: payload) else { return }
        data.append(10)
        writeCommand(data, input: input, session: run)
    }

    private func writeCommand(_ data: Data, input: FileHandle, session run: UUID) {
        let commandData = data
        commandQueue.async { [weak self] in
            do {
                try input.write(contentsOf: commandData)
            } catch {
                Task { @MainActor [weak self] in
                    guard let self, self.session == run else { return }
                    await self.shutdown()
                    self.state.fail("Could not send a request to the Music worker. Choose Reconnect to try again.")
                }
            }
        }
    }

    private func closeInput() {
        let handle = input
        input = nil
        commandQueue.async { try? handle?.close() }
    }

    func shutdown() async {
        session = nil // Ignore all output queued by the previous worker.
        clockTask?.cancel()
        clockTask = nil
        controls.disconnect()
        refreshPresentation()
        let worker = process
        process = nil
        // EOF is sufficient and avoids writing to a pipe whose worker just died.
        closeInput()
        guard let worker else { return }
        if worker.isRunning { worker.terminate() }
        // Wait away from the UI thread. Signals/EOF normally stop the worker within
        // 100 ms; a bounded group kill also covers a stuck script or worker.
        await Task.detached {
            let deadline = Date().addingTimeInterval(2)
            while worker.isRunning && Date() < deadline {
                try? await Task.sleep(for: .milliseconds(50))
            }
            if worker.isRunning {
                kill(-worker.processIdentifier, SIGKILL)
                kill(worker.processIdentifier, SIGKILL)
            }
            worker.waitUntilExit()
        }.value
    }
}

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    let connection = MusicConnection()

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        Task {
            await connection.shutdown()
            sender.reply(toApplicationShouldTerminate: true)
        }
        return .terminateLater
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
}
