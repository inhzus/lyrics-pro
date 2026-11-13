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
    @Published private(set) var dataStats: DataStats?
    /// Settings asked for data stats; every new worker is asked again after `ready`.
    private var wantsDataStats = false
    private var clockTask: Task<Void, Never>?
    private static var now: Double { ProcessInfo.processInfo.systemUptime }
    private var controlRevision = 0
    private var worker: WorkerProcess?
    private var receivedReady = false

    func start() {
        guard worker == nil else { return }
        AppLog.shared.write("worker_start_requested")
        state = LiveMusicState()
        controls = PlaybackControlState()
        refreshPresentation()
        artworkImage = nil
        let launch = BackendLaunch(bundleURL: Bundle.main.bundleURL,
                                   inheritedEnvironment: ProcessInfo.processInfo.environment)
        guard FileManager.default.isExecutableFile(atPath: launch.executable.path) else {
            state.fail("Lyrics Pro's bundled worker is missing. Replace the app with a complete copy, then reopen it.")
            return
        }
        let worker = WorkerProcess(
            launch: launch, arguments: ["--language", language.rawValue],
            onEvent: { [weak self] worker, event, artwork in self?.receive(event, from: worker, artwork: artwork) },
            onFailure: { [weak self] worker, failure in self?.workerFailed(worker, failure) })
        do {
            try worker.start()
        } catch {
            AppLog.shared.write("worker_start_failed", String(describing: error))
            state.fail("Could not start the Music connection: \(error.localizedDescription)")
            return
        }
        self.worker = worker
        receivedReady = false
        startClock()
        watchReady(worker)
    }

    /// Expires unconfirmed controls and advances the shared playback clock.
    private func startClock() {
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
    }

    private func watchReady(_ worker: WorkerProcess) {
        Task { [weak self] in
            try? await Task.sleep(for: .seconds(8))
            guard let self, self.worker === worker, !self.receivedReady else { return }
            self.stop(worker, explaining: "The Music worker did not start. Check the Python environment and choose Reconnect.")
        }
    }

    private func workerFailed(_ worker: WorkerProcess, _ failure: WorkerProcess.Failure) {
        guard self.worker === worker else { return }
        switch failure {
        case .exited(let status):
            self.worker = nil
            artworkImage = nil
            state.fail("The Music connection stopped (exit \(status)). Choose Reconnect to try again.")
            controls.disconnect()
            clockTask?.cancel()
            refreshPresentation()
        case .invalidOutput:
            stop(worker, explaining: "The Music worker returned invalid data. Rebuild the app and choose Reconnect.")
        case .writeFailed:
            stop(worker, explaining: "Could not send a request to the Music worker. Choose Reconnect to try again.")
        }
    }

    /// Stops `worker` if it is still current and reports why.
    private func stop(_ worker: WorkerProcess, explaining explanation: String) {
        Task {
            guard self.worker === worker else { return }
            await shutdown()
            state.fail(explanation)
        }
    }

    private func receive(_ event: BridgeEvent, from worker: WorkerProcess, artwork: DecodedArtwork?) {
        guard self.worker === worker else { return }
        if case .ready = event.payload {
            receivedReady = true
            if wantsDataStats { worker.send(.getDataStats) }
        }
        if case .dataStats(let stats) = event.payload { dataStats = stats }
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

    var canManageData: Bool { worker?.isRunning == true }

    func requestDataStats() {
        wantsDataStats = true
        guard let worker, worker.isRunning else { return }
        worker.send(.getDataStats)
    }

    func clearData(_ targets: [DataTarget]) {
        guard let worker, worker.isRunning, !targets.isEmpty else { return }
        AppLog.shared.write("data_clear_requested", targets.map(\.rawValue).joined(separator: ","))
        worker.send(.clearData(targets))
    }

    var canControl: Bool {
        demo == nil && state.phase == .live &&
        [.playing, .paused].contains(state.playback?.state)
    }

    var canSeek: Bool {
        canControl && (state.playback?.duration ?? 0) > 0
    }

    func control(_ action: PlaybackAction, position: Double? = nil, resumeFollowing: Bool = false,
                 expectedGeneration: Int? = nil) {
        guard canControl, let track = state.identity, worker?.isRunning == true else { return }
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
              let worker, worker.isRunning,
              let command = controls.takeNext(now: Self.now) else { return }
        worker.send(.playbackControl(command))
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
        guard let worker, worker.isRunning else { return }
        worker.send(make(state.nextLyricRequestID(), state.generation))
    }

    func shutdown() async {
        AppLog.shared.write("worker_shutdown_requested")
        let worker = self.worker
        self.worker = nil // Ignore all output queued by the previous worker.
        clockTask?.cancel()
        clockTask = nil
        controls.disconnect()
        refreshPresentation()
        await worker?.stop()
    }
}
