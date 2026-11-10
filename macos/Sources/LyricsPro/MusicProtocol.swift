import Foundation

struct TrackIdentity: Codable, Equatable, Sendable {
    let title: String
    let artist: String
    let album: String
    let duration: Double

    init(from decoder: any Decoder) throws {
        var values = try decoder.unkeyedContainer()
        title = try values.decode(String.self)
        artist = try values.decode(String.self)
        album = try values.decode(String.self)
        duration = try values.decode(Double.self)
    }

    func encode(to encoder: any Encoder) throws {
        var values = encoder.unkeyedContainer()
        try values.encode(title)
        try values.encode(artist)
        try values.encode(album)
        try values.encode(duration)
    }
}

struct MusicSnapshot: Decodable, Sendable {
    let state: String
    let title: String
    let artist: String
    let album: String
    let duration: Double
    let position: Double

    var hasTrack: Bool { !title.isEmpty && state != "closed" && state != "stopped" }
    var progress: Double { duration > 0 ? min(1, max(0, position / duration)) : 0 }
    var elapsed: String { Self.timeLabel(min(max(0, position), max(0, duration))) }
    var total: String { Self.timeLabel(duration) }

    static func timeLabel(_ seconds: Double) -> String {
        guard seconds.isFinite, seconds >= 0, seconds < 1_000_000_000 else { return "0:00" }
        let value = Int(seconds)
        return String(format: "%d:%02d", value / 60, value % 60)
    }
}

struct BridgeEvent: Decodable, Sendable {
    let version: Int
    let type: String
    let generation: Int
    let track: TrackIdentity?
    let playback: MusicSnapshot?
    let image: String?
    let code: String?
    let message: String?
    let lyric: LyricUpdate?
    let recordings: RecordingUpdate?
    let command_id: Int?
    let completed_control_id: Int?
    let ok: Bool?

    static func decode(_ data: Data) throws -> BridgeEvent {
        let event = try JSONDecoder().decode(Self.self, from: data)
        guard event.version == 1, event.generation >= 0,
              ["ready", "playback", "artwork", "status", "lyrics", "recordings", "control_result"].contains(event.type) else {
            throw BridgeError.invalidEvent
        }
        if event.type == "playback" {
            if let revision = event.completed_control_id, revision < 0 { throw BridgeError.invalidEvent }
            guard let p = event.playback, p.duration.isFinite, p.position.isFinite,
                  ["playing", "paused", "stopped", "closed", "fast forwarding", "rewinding"].contains(p.state),
                  p.hasTrack == (event.track != nil) else { throw BridgeError.invalidEvent }
        }
        if event.type == "lyrics" {
            guard event.track != nil, event.lyric?.isValid == true else { throw BridgeError.invalidEvent }
        }
        if event.type == "recordings" {
            guard event.track != nil, event.recordings?.isValid == true else { throw BridgeError.invalidEvent }
        }
        if event.type == "control_result" {
            guard let id = event.command_id, id > 0, event.ok != nil else { throw BridgeError.invalidEvent }
        }
        return event
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
    var recordings: RecordingUpdate?
    var lyricRequestID = 0

    mutating func prepareLyrics(requestID: Int, preserve: Bool = false) {
        lyricRequestID = requestID
        if !preserve { lyric = nil }
    }

    mutating func apply(_ event: BridgeEvent) {
        guard event.generation >= generation else { return }
        switch event.type {
        case "playback":
            guard let snapshot = event.playback else { return }
            if event.generation == generation, identity != event.track { return }
            if identity != event.track || generation != event.generation {
                artwork = nil
                artworkReceived = false
                lyric = nil
                recordings = nil
            }
            generation = event.generation
            identity = event.track
            playback = snapshot
            phase = snapshot.state == "closed" ? .closed : (snapshot.state == "stopped" ? .stopped : .live)
            message = snapshot.state == "paused" ? "Paused in Music" : "Following Apple Music"
        case "artwork":
            guard event.generation == generation, let identity, identity == event.track, phase == .live else { return }
            artwork = event.image.flatMap { Data(base64Encoded: $0) }
            artworkReceived = true
        case "lyrics":
            guard event.generation == generation, let identity, identity == event.track,
                  phase == .live, let update = event.lyric, update.requestID == lyricRequestID else { return }
            lyric = update
        case "recordings":
            guard event.generation == generation, let identity, identity == event.track,
                  phase == .live, let update = event.recordings, update.requestID == lyricRequestID else { return }
            recordings = update
        case "status":
            generation = event.generation
            identity = nil
            playback = nil
            artwork = nil
            artworkReceived = false
            lyric = nil
            recordings = nil
            phase = event.code == "permission_denied" ? .denied : .failed
            message = event.message ?? "Cannot read Apple Music. Waiting to reconnect."
        default: break
        }
    }

    mutating func fail(_ explanation: String) {
        phase = .failed
        playback = nil
        identity = nil
        artwork = nil
        artworkReceived = false
        lyric = nil
        recordings = nil
        message = explanation
    }
}
