import Foundation

struct TrackIdentity: Codable, Equatable, Sendable {
    let title: String
    let artist: String
    let album: String
    let duration: Double
}

enum PlayerState: String, Decodable, Sendable {
    case playing, paused, stopped, closed, rewinding
    case fastForwarding = "fast forwarding"

    var isPlaying: Bool { self == .playing }
    /// Music reports no current track while stopped or not running.
    var hasTrack: Bool { self != .stopped && self != .closed }
}

struct MusicSnapshot: Decodable, Sendable {
    let state: PlayerState
    let title: String
    let artist: String
    let album: String
    let duration: Double
    let position: Double

    var hasTrack: Bool { !title.isEmpty && state.hasTrack }
    var progress: Double { duration > 0 ? min(1, max(0, position / duration)) : 0 }
    var elapsed: String { Self.timeLabel(min(max(0, position), max(0, duration))) }
    var total: String { Self.timeLabel(duration) }

    static func timeLabel(_ seconds: Double) -> String {
        guard seconds.isFinite, seconds >= 0, seconds < 1_000_000_000 else { return "0:00" }
        let value = Int(seconds)
        return String(format: "%d:%02d", value / 60, value % 60)
    }
}

struct ControlResult: Decodable, Sendable {
    let commandID: Int
    let ok: Bool
    var code: String? = nil
    var message: String? = nil

    enum CodingKeys: String, CodingKey {
        case commandID = "command_id", ok, code, message
    }
}

/// Saved user data, reported by the worker; nil sizes mean the cache could not be read.
struct DataStats: Decodable, Sendable, Equatable {
    let lyricsEntries: Int?
    let lyricsBytes: Int?
    let recordingChoices: Int
    let songLanguages: Int
    let message: String

    enum CodingKeys: String, CodingKey {
        case lyricsEntries = "lyrics_entries", lyricsBytes = "lyrics_bytes"
        case recordingChoices = "recording_choices", songLanguages = "song_languages", message
    }

    var isValid: Bool {
        [lyricsEntries ?? 0, lyricsBytes ?? 0, recordingChoices, songLanguages].allSatisfy { $0 >= 0 }
    }
}

/// One worker event (docs/protocol.md). Decoding validates the payload for its type.
struct BridgeEvent: Decodable, Sendable {
    enum Payload: Sendable {
        case ready
        case playback(MusicSnapshot, completedControlID: Int)
        case artwork(image: String?)
        case status(code: String, message: String)
        case lyrics(LyricUpdate)
        case recordings(RecordingUpdate)
        case controlResult(ControlResult)
        case dataStats(DataStats)
    }

    static let version = 2

    let generation: Int
    let track: TrackIdentity?
    let payload: Payload

    private enum CodingKeys: String, CodingKey { case version, type, generation, track, payload }
    private enum PlaybackKeys: String, CodingKey { case snapshot, completedControlID = "completed_control_id" }
    private enum ArtworkKeys: String, CodingKey { case image }
    private enum StatusKeys: String, CodingKey { case code, message }

    init(from decoder: any Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        guard try values.decode(Int.self, forKey: .version) == Self.version else { throw BridgeError.invalidEvent }
        generation = try values.decode(Int.self, forKey: .generation)
        track = try values.decodeIfPresent(TrackIdentity.self, forKey: .track)
        guard generation >= 0 else { throw BridgeError.invalidEvent }
        switch try values.decode(String.self, forKey: .type) {
        case "ready":
            payload = .ready
        case "playback":
            let body = try values.nestedContainer(keyedBy: PlaybackKeys.self, forKey: .payload)
            let snapshot = try body.decode(MusicSnapshot.self, forKey: .snapshot)
            let completed = try body.decode(Int.self, forKey: .completedControlID)
            guard completed >= 0, snapshot.duration.isFinite, snapshot.position.isFinite,
                  snapshot.hasTrack == (track != nil) else { throw BridgeError.invalidEvent }
            payload = .playback(snapshot, completedControlID: completed)
        case "artwork":
            let body = try values.nestedContainer(keyedBy: ArtworkKeys.self, forKey: .payload)
            payload = .artwork(image: try body.decodeIfPresent(String.self, forKey: .image))
        case "status":
            let body = try values.nestedContainer(keyedBy: StatusKeys.self, forKey: .payload)
            payload = .status(code: try body.decode(String.self, forKey: .code),
                              message: try body.decode(String.self, forKey: .message))
        case "lyrics":
            let update = try values.decode(LyricUpdate.self, forKey: .payload)
            guard track != nil, update.isValid else { throw BridgeError.invalidEvent }
            payload = .lyrics(update)
        case "recordings":
            let update = try values.decode(RecordingUpdate.self, forKey: .payload)
            guard track != nil, update.isValid else { throw BridgeError.invalidEvent }
            payload = .recordings(update)
        case "data_stats":
            let stats = try values.decode(DataStats.self, forKey: .payload)
            guard stats.isValid else { throw BridgeError.invalidEvent }
            payload = .dataStats(stats)
        case "control_result":
            let result = try values.decode(ControlResult.self, forKey: .payload)
            guard result.commandID > 0 else { throw BridgeError.invalidEvent }
            payload = .controlResult(result)
        default:
            throw BridgeError.invalidEvent
        }
    }

    static func decode(_ data: Data) throws -> BridgeEvent {
        try JSONDecoder().decode(Self.self, from: data)
    }
}

enum BridgeError: Error { case invalidEvent, frameTooLarge }

struct EventFramer: Sendable {
    private var buffer = Data()
    mutating func append(_ data: Data) throws -> [BridgeEvent] {
        buffer.append(data)
        var events: [BridgeEvent] = []
        while let newline = buffer.firstIndex(of: 10) {
            let line = Data(buffer[..<newline])
            guard line.count <= 8 * 1024 * 1024 else { throw BridgeError.frameTooLarge }
            buffer.removeSubrange(...newline)
            if !line.isEmpty { events.append(try BridgeEvent.decode(line)) }
        }
        guard buffer.count <= 8 * 1024 * 1024 else { throw BridgeError.frameTooLarge }
        return events
    }
}

enum EventStream {
    static func read(from handle: FileHandle, receive: (BridgeEvent) -> Void) throws {
        var framer = EventFramer()
        while true {
            // read(upToCount:) may wait to fill its requested buffer on a pipe.
            // availableData returns each available chunk so small playback events
            // and the final chunk of a cover are delivered without buffering delay.
            let bytes = handle.availableData
            if bytes.isEmpty { return }
            for event in try framer.append(bytes) { receive(event) }
        }
    }
}

enum ConnectionPhase: String, Sendable {
    case connecting, live, closed, stopped, denied, failed
}

struct LiveMusicState: Sendable {
    var phase: ConnectionPhase = .connecting
    var message = "Connecting to Apple Music…"
    var generation = -1
    var identity: TrackIdentity?
    var playback: MusicSnapshot?
    var artwork: Data?
    var artworkReceived = false
    var lyric: LyricUpdate?
    var pronunciation: LyricUpdate?
    var recordings: RecordingUpdate?
    var lyricRequestID = 0

    /// Starts a lyric command revision. Visible lyrics stay until a newer update replaces them.
    mutating func nextLyricRequestID() -> Int {
        lyricRequestID += 1
        return lyricRequestID
    }

    mutating func apply(_ event: BridgeEvent) {
        guard event.generation >= generation else { return }
        let current = event.generation == generation && identity != nil && identity == event.track && phase == .live
        switch event.payload {
        case .playback(let snapshot, _):
            if event.generation == generation, identity != event.track { return }
            if identity != event.track || generation != event.generation { clearTrackContent() }
            generation = event.generation
            identity = event.track
            playback = snapshot
            phase = snapshot.state == .closed ? .closed : (snapshot.state == .stopped ? .stopped : .live)
            message = snapshot.state == .paused ? "Paused in Music" : "Following Apple Music"
        case .artwork(let image):
            guard current else { return }
            artwork = image.flatMap { Data(base64Encoded: $0) }
            artworkReceived = true
        case .lyrics(let update):
            guard current, update.requestID == lyricRequestID else { return }
            // Keep successful lyrics readable while an explicit refresh is pending.
            pronunciation = update
            if update.status != .loading || lyric?.lyrics == nil { lyric = update }
        case .recordings(let update):
            guard current, update.requestID == lyricRequestID else { return }
            recordings = update
        case .status(let code, let explanation):
            generation = event.generation
            identity = nil
            playback = nil
            clearTrackContent()
            phase = code == "permission_denied" ? .denied : .failed
            message = explanation
        case .ready, .controlResult, .dataStats:
            break
        }
    }

    private mutating func clearTrackContent() {
        artwork = nil
        artworkReceived = false
        lyric = nil
        pronunciation = nil
        recordings = nil
    }

    mutating func fail(_ explanation: String) {
        phase = .failed
        playback = nil
        identity = nil
        clearTrackContent()
        message = explanation
    }
}
