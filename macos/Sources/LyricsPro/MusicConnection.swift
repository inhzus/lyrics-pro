import AppKit
import Combine
import Foundation

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
        AppLog.shared.write("worker_start_requested")
        // A worker can exit between isRunning and a pipe write. Report EPIPE
        // through the connection state instead of terminating the native app.
        signal(SIGPIPE, SIG_IGN)
        state = LiveMusicState()
        controls = PlaybackControlState()
        refreshPresentation()
        artworkImage = nil
        do {
            let launch = BackendLaunch(bundleURL: Bundle.main.bundleURL,
                                       inheritedEnvironment: ProcessInfo.processInfo.environment)
            guard FileManager.default.isExecutableFile(atPath: launch.executable.path) else {
                state.fail("Lyrics Pro's bundled worker is missing. Replace the app with a complete copy, then reopen it.")
                return
            }
            let worker = Process()
            let stdin = Pipe(), stdout = Pipe(), stderr = Pipe()
            let run = UUID()
            session = run
            receivedReady = false
            worker.executableURL = launch.executable
            worker.arguments = ["--language", language.rawValue]
            worker.currentDirectoryURL = launch.workingDirectory
            worker.environment = launch.environment
            worker.standardInput = stdin
            worker.standardOutput = stdout
            worker.standardError = stderr
            worker.terminationHandler = { [weak self] finished in
                AppLog.shared.write("worker_exit", "status=\(finished.terminationStatus)")
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
                        // Decode/downsample on the event queue; the UI only wraps the immutable bitmap.
                        var artwork: DecodedArtwork?
                        if case .artwork(let image) = event.payload { artwork = DecodedArtwork(base64: image) }
                        DispatchQueue.main.async { [weak self] in self?.receive(event, session: run, artwork: artwork) }
                    }
                } catch {
                    AppLog.shared.write("bridge_read_error", String(describing: error))
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
                    AppLog.shared.write("worker", String(decoding: data.prefix(4096), as: UTF8.self))
                }
            }
            Task { [weak self] in
                try? await Task.sleep(for: .seconds(8))
                guard let self, self.session == run, !self.receivedReady else { return }
                await self.shutdown()
                self.state.fail("The Music worker did not start. Check the Python environment and choose Reconnect.")
            }
        } catch {
            AppLog.shared.write("worker_start_failed", String(describing: error))
            process = nil
            session = nil
            state.fail("Could not start the Music connection: \(error.localizedDescription)")
        }
    }

    private func receive(_ event: BridgeEvent, session run: UUID, artwork: DecodedArtwork?) {
        guard session == run else { return }
        if case .ready = event.payload { receivedReady = true }
        let previousArtwork = state.artwork
        state.apply(event)
        controls.receive(event, now: Self.now)
        if state.phase != .live { controls.disconnect() }
        dispatchNextControl()
        refreshPresentation()
        if state.artwork != previousArtwork {
            artworkImage = state.artwork == nil ? nil : artwork?.image.map { NSImage(cgImage: $0, size: .zero) }
            if artworkImage == nil, state.artwork != nil {
                AppLog.shared.write("artwork_decode_failed")
                artworkImage = nil
                state.artwork = nil
            }
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
        guard PronunciationLanguage.choices.contains(value), language != value else { return }
        language = value
        UserDefaults.standard.set(value.rawValue, forKey: PronunciationLanguage.preferenceKey)
        sendLyricCommand { requestID, _ in .setLanguage(value, requestID: requestID) }
    }

    var songLanguage: PronunciationLanguage { state.pronunciation?.songLanguage ?? .inherit }
    var effectiveLanguage: PronunciationLanguage {
        guard let update = state.pronunciation else { return language }
        return update.selectedLanguage ?? .original
    }
    var canChooseSongLanguage: Bool {
        canControl && !(state.identity?.artist.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ?? true)
    }

    func selectSongLanguage(_ value: PronunciationLanguage) {
        guard canChooseSongLanguage, PronunciationLanguage.songChoices.contains(value),
              let track = state.identity else { return }
        sendLyricCommand { requestID, generation in
            .setSongLanguage(value, requestID: requestID, generation: generation, track: track)
        }
    }

    func retryLyrics() {
        let retryArtwork = artworkImage == nil
        sendLyricCommand { requestID, generation in
            .retryLyrics(requestID: requestID, generation: generation, retryArtwork: retryArtwork)
        }
    }

    func chooseRecording(_ candidate: RecordingCandidate, generation: Int, requestID: Int) {
        guard demo == nil, state.phase == .live, state.generation == generation,
              state.lyricRequestID == requestID,
              state.recordings?.candidates.contains(where: { $0.id == candidate.id }) == true else { return }
        sendLyricCommand { next, generation in
            .chooseRecording(candidate.id, requestID: next, generation: generation, choiceRequestID: requestID)
        }
    }

    func forgetRecording() {
        sendLyricCommand { requestID, generation in .forgetRecording(requestID: requestID, generation: generation) }
    }

    func listRecordings() {
        guard demo == nil, state.phase == .live else { return }
        sendLyricCommand { requestID, generation in .listRecordings(requestID: requestID, generation: generation) }
    }

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
        let command = PlaybackCommand(commandID: id, action: action, generation: state.generation,
                                      track: track, position: target)
        controls.enqueue(command, resumeFollowing: resumeFollowing, now: Self.now)
        dispatchNextControl()
        refreshPresentation()
    }

    private func dispatchNextControl() {
        guard canControl, controls.inFlight == nil, !controls.queued.isEmpty,
              let input, let run = session, process?.isRunning == true,
              let command = controls.takeNext(now: Self.now) else { return }
        guard let data = try? WorkerCommand.playbackControl(command).frame() else { return }
        writeCommand(data, input: input, session: run)
    }

    private func refreshPresentation() {
        let now = Self.now
        let value = controls.presentation(at: now)
        if presentation != value { presentation = value }
        let updating = demo == nil && controls.isUpdating(at: now)
        if updatingMusic != updating { updatingMusic = updating }
    }

    /// Sends a lyric command with a new request revision and the current generation.
    private func sendLyricCommand(_ make: (_ requestID: Int, _ generation: Int) -> WorkerCommand) {
        guard let process, let input, let run = session, process.isRunning else { return }
        let command = make(state.nextLyricRequestID(), state.generation)
        guard let data = try? command.frame() else { return }
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
        AppLog.shared.write("worker_shutdown_requested")
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

    func applicationDidFinishLaunching(_ notification: Notification) {
        AppLog.shared.write("app_start", "version=\(Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") ?? "unknown")")
    }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        Task {
            await connection.shutdown()
            AppLog.shared.write("app_stop")
            sender.reply(toApplicationShouldTerminate: true)
        }
        return .terminateLater
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
}
