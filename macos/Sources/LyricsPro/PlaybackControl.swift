import Foundation

enum PlaybackAction: String, Encodable, Sendable {
    case play, pause, next, previous, seek
    var isSkip: Bool { self == .next || self == .previous }
    var category: Int { isSkip ? 2 : (self == .seek ? 1 : 0) }
}

enum LyricSeek {
    static func position(for line: LiveLyricLine, synced: Bool) -> Double? {
        guard synced, let time = line.time, time.isFinite, time >= 0,
              !line.text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return nil }
        // Music reports single-precision positions (46.76 becomes 46.759998).
        // Seek just inside the line so paused playback highlights the clicked row.
        return time + 0.02
    }
}

struct PlaybackCommand: Sendable {
    let commandID: Int
    let action: PlaybackAction
    let generation: Int
    let track: TrackIdentity
    let position: Double?
}

struct PlaybackPresentation: Equatable {
    var position: Double = 0
    var duration: Double = 0
    var playing = false
}

/// Pure state machine; all times are monotonic seconds supplied by the caller.
struct PlaybackControlState {
    struct Intent {
        let command: PlaybackCommand
        let created: Double
        var sent: Double?
        var acknowledged = false
        var id: Int { command.commandID }
    }
    private(set) var inFlight: Intent?
    private(set) var queued: [Intent] = []
    private var stateIntent: Intent?
    private var seekIntent: Intent?
    private var skipIntent: Intent?
    private var confirmed: MusicSnapshot?
    private var confirmedAt: Double = 0
    private var confirmedRevision = 0
    private var generation = -1
    private var anchor = PlaybackPresentation()
    private var anchorAt: Double = 0
    private(set) var message: String?
    private(set) var followRevision = 0
    var skipBusy: Bool { skipIntent != nil }

    func presentation(at now: Double) -> PlaybackPresentation {
        var result = anchor
        if result.playing { result.position += max(0, now - anchorAt) }
        result.position = min(max(0, result.duration), max(0, result.position))
        return result
    }

    func isUpdating(at now: Double) -> Bool {
        [stateIntent, seekIntent, skipIntent].compactMap { $0 }.contains { now - $0.created >= 1 }
    }

    @discardableResult
    mutating func enqueue(_ command: PlaybackCommand, resumeFollowing: Bool, now: Double) -> Bool {
        guard command.generation == generation, confirmed?.hasTrack == true,
              !(command.action.isSkip && skipBusy) else { return false }
        let intent = Intent(command: command, created: now)
        queued.removeAll { $0.command.action.category == command.action.category }
        queued.append(intent)
        anchor = presentation(at: now)
        anchorAt = now
        switch command.action {
        case .play, .pause:
            stateIntent = intent
            anchor.playing = command.action == .play
        case .seek:
            seekIntent = intent
            anchor.position = min(anchor.duration, max(0, command.position ?? 0))
            if resumeFollowing { followRevision += 1 }
        case .next, .previous:
            skipIntent = intent
        }
        message = nil
        return true
    }

    mutating func takeNext(now: Double) -> PlaybackCommand? {
        guard inFlight == nil, !queued.isEmpty else { return nil }
        var intent = queued.removeFirst()
        intent.sent = now
        inFlight = intent
        if stateIntent?.id == intent.id { stateIntent = intent }
        if seekIntent?.id == intent.id { seekIntent = intent }
        if skipIntent?.id == intent.id { skipIntent = intent }
        return intent.command
    }

    mutating func receive(_ event: BridgeEvent, now: Double) {
        switch event.payload {
        case .playback(let snapshot, let completed) where event.generation >= generation:
            if event.generation == generation, completed < confirmedRevision { return }
            if event.generation != generation {
                clearIntents(now: now)
                generation = event.generation
            }
            confirmed = snapshot
            confirmedAt = now
            confirmedRevision = completed
            reconcile(now: now)
        case .controlResult(let result):
            let id = result.commandID
            if inFlight?.id == id { inFlight = nil }
            if result.ok {
                if stateIntent?.id == id { stateIntent?.acknowledged = true }
                if seekIntent?.id == id { seekIntent?.acknowledged = true }
                // Skip stays guarded until a track change or its confirmation deadline.
                if skipIntent?.id == id { skipIntent?.acknowledged = true }
                reconcile(now: now)
            } else {
                fail(id: id, explanation: result.message ?? "Music could not complete the control.", now: now)
            }
        default:
            break
        }
    }

    private mutating func reconcile(now: Double) {
        guard let confirmed else { return }
        if let intent = stateIntent, intent.acknowledged, confirmedRevision >= intent.id,
           confirmed.state.isPlaying == (intent.command.action == .play) {
            stateIntent = nil
        }
        if let intent = seekIntent, intent.acknowledged, confirmedRevision >= intent.id,
           let target = intent.command.position {
            // A seek may spend time in Music before confirmation. Allow only forward
            // elapsed playback since dispatch, not arbitrary distance from its target.
            let elapsed = confirmed.state.isPlaying ? max(0, confirmedAt - (intent.sent ?? now)) : 0
            if confirmed.position >= target - 1 && confirmed.position <= target + elapsed + 1 {
                seekIntent = nil
            }
        }
        rebase(now: now)
    }

    private mutating func rebase(now: Double, restorePosition: Bool = false) {
        guard let confirmed else { return }
        var current = presentation(at: now)
        current.duration = max(0, confirmed.duration)
        if restorePosition || (seekIntent == nil && stateIntent == nil) {
            current.position = confirmed.position + (confirmed.state.isPlaying ? max(0, now - confirmedAt) : 0)
        }
        current.playing = stateIntent.map { $0.command.action == .play } ?? confirmed.state.isPlaying
        anchor = current
        anchorAt = now
    }

    private mutating func fail(id: Int, explanation: String, now: Double) {
        let relevant = stateIntent?.id == id || seekIntent?.id == id || skipIntent?.id == id
        let restorePosition = seekIntent?.id == id
        if stateIntent?.id == id { stateIntent = nil }
        if seekIntent?.id == id { seekIntent = nil }
        if skipIntent?.id == id { skipIntent = nil }
        queued.removeAll { $0.id == id }
        if relevant { message = explanation }
        rebase(now: now, restorePosition: restorePosition)
    }

    @discardableResult
    mutating func expire(now: Double) -> Bool {
        let expired = ([inFlight, stateIntent, seekIntent, skipIntent].compactMap { $0 } + queued)
            .filter { now - $0.created >= 10 }
        guard !expired.isEmpty else { return false }
        for intent in expired {
            if inFlight?.id == intent.id { inFlight = nil }
            fail(id: intent.id, explanation: "Music did not confirm the control. Check playback before trying again.", now: now)
        }
        return true
    }

    mutating func clearIntents(now: Double) {
        queued = []
        stateIntent = nil
        seekIntent = nil
        skipIntent = nil
        message = nil
        // Keep the physical in-flight slot until its result/timeout. This prevents
        // new-track or demo transitions from issuing concurrent Apple Events.
        rebase(now: now)
    }

    mutating func disconnect() {
        let revision = followRevision
        self = Self()
        followRevision = revision
    }
}

/// A drag belongs to one track generation. Incoming snapshots never replace its preview.
struct TimelineScrubState {
    private(set) var generation: Int?
    private(set) var preview: Double?
    var isEditing: Bool { generation != nil }

    mutating func begin(generation: Int, position: Double) {
        self.generation = generation
        preview = position
    }

    mutating func update(_ position: Double) { preview = position }

    mutating func finish(generation: Int, duration: Double) -> Double? {
        defer { cancel() }
        guard self.generation == generation, let preview, preview.isFinite,
              duration.isFinite, duration > 0 else { return nil }
        return min(duration, max(0, preview))
    }

    mutating func cancel() { generation = nil; preview = nil }
}
