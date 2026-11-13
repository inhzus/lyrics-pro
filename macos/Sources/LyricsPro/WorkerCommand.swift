import Foundation

/// One command to the worker (docs/protocol.md), encoded as a version 2 envelope.
enum WorkerCommand: Encodable, Sendable {
    case setLanguage(PronunciationLanguage, requestID: Int)
    case setSongLanguage(PronunciationLanguage, requestID: Int, generation: Int, track: TrackIdentity)
    case retryLyrics(requestID: Int, generation: Int, retryArtwork: Bool)
    case listRecordings(requestID: Int, generation: Int)
    case chooseRecording(String, requestID: Int, generation: Int, choiceRequestID: Int)
    case forgetRecording(requestID: Int, generation: Int)
    case playbackControl(PlaybackCommand)

    private enum CodingKeys: String, CodingKey { case version, type, payload }
    private enum PayloadKeys: String, CodingKey {
        case language, requestID = "request_id", generation, track, songLanguage = "song_language"
        case retryArtwork = "retry_artwork", recordingID = "recording_id", choiceRequestID = "choice_request_id"
        case commandID = "command_id", action, position
    }

    var type: String {
        switch self {
        case .setLanguage: "set_language"
        case .setSongLanguage: "set_song_language"
        case .retryLyrics: "retry_lyrics"
        case .listRecordings: "list_recordings"
        case .chooseRecording: "choose_recording"
        case .forgetRecording: "forget_recording"
        case .playbackControl: "playback_control"
        }
    }

    func encode(to encoder: any Encoder) throws {
        var envelope = encoder.container(keyedBy: CodingKeys.self)
        try envelope.encode(BridgeEvent.version, forKey: .version)
        try envelope.encode(type, forKey: .type)
        var payload = envelope.nestedContainer(keyedBy: PayloadKeys.self, forKey: .payload)
        switch self {
        case .setLanguage(let language, let requestID):
            try payload.encode(language.rawValue, forKey: .language)
            try payload.encode(requestID, forKey: .requestID)
        case .setSongLanguage(let language, let requestID, let generation, let track):
            try payload.encode(requestID, forKey: .requestID)
            try payload.encode(generation, forKey: .generation)
            try payload.encode(track, forKey: .track)
            try payload.encode(language.rawValue, forKey: .songLanguage)
        case .retryLyrics(let requestID, let generation, let retryArtwork):
            try payload.encode(requestID, forKey: .requestID)
            try payload.encode(generation, forKey: .generation)
            try payload.encode(retryArtwork, forKey: .retryArtwork)
        case .listRecordings(let requestID, let generation), .forgetRecording(let requestID, let generation):
            try payload.encode(requestID, forKey: .requestID)
            try payload.encode(generation, forKey: .generation)
        case .chooseRecording(let recordingID, let requestID, let generation, let choiceRequestID):
            try payload.encode(requestID, forKey: .requestID)
            try payload.encode(generation, forKey: .generation)
            try payload.encode(recordingID, forKey: .recordingID)
            try payload.encode(choiceRequestID, forKey: .choiceRequestID)
        case .playbackControl(let command):
            try payload.encode(command.commandID, forKey: .commandID)
            try payload.encode(command.generation, forKey: .generation)
            try payload.encode(command.track, forKey: .track)
            try payload.encode(command.action, forKey: .action)
            // Explicit null keeps the documented field present for non-seek actions.
            try payload.encode(command.position, forKey: .position)
        }
    }

    /// One NDJSON frame.
    func frame() throws -> Data {
        var data = try JSONEncoder().encode(self)
        data.append(10)
        return data
    }
}
