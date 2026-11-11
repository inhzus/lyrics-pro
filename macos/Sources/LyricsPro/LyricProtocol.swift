import Foundation

enum PronunciationLanguage: String, CaseIterable, Decodable, Sendable {
    case auto, cantonese, hokkien, original

    static let preferenceKey = "pronunciationLanguage"
    var shortLabel: String {
        switch self {
        case .auto: "Auto"
        case .cantonese: "Jyutping"
        case .hokkien: "Tâi-lô"
        case .original: "Original"
        }
    }
    var label: String {
        switch self {
        case .auto: "Auto pronunciation"
        case .cantonese: "Cantonese · Jyutping"
        case .hokkien: "Hokkien · Tâi-lô"
        case .original: "Original only"
        }
    }
    static func saved(in defaults: UserDefaults = .standard) -> Self {
        Self(rawValue: defaults.string(forKey: preferenceKey) ?? "") ?? .auto
    }
}

struct LiveLyricLine: Decodable, Sendable {
    let text: String
    let time: Double?
    let pronunciation: String?
}

struct ProofreadMetadata: Decodable, Sendable {
    let asset_id: String
    let revision: String
    let language: String
    let attribution: String
}

struct LiveLyrics: Decodable, Sendable {
    let lines: [LiveLyricLine]
    let source: String
    let synced: Bool
    let instrumental: Bool
    var proofread: ProofreadMetadata? = nil
    var recordingID: String? = nil

    enum CodingKeys: String, CodingKey {
        case lines, source, synced, instrumental, proofread
        case recordingID = "recording_id"
    }

    var sourceName: String { String(source.split(separator: " ", maxSplits: 1).first ?? "Lyrics") }
    var sourceURL: URL? {
        let parts = source.split(separator: " ", maxSplits: 1)
        guard parts.count == 2, let url = URL(string: String(parts[1])),
              url.scheme == "https", ["music.163.com", "lrclib.net", "api.lrc.cx"].contains(url.host),
              url.user == nil, url.password == nil else { return nil }
        return url
    }
}

enum LyricStatus: String, Decodable, Sendable {
    case loading, ready, plain, instrumental, unavailable, error
}

struct RecordingCandidate: Decodable, Sendable, Identifiable, Equatable {
    let id: String
    let title: String
    let artists: [String]
    let album: String
    let duration: Double
    var sourceName: String {
        if id.hasPrefix("proofread:") { return "Proofread" }
        return id.hasPrefix("lrcapi:") ? "LrcAPI" : "NetEase"
    }
    enum CodingKeys: String, CodingKey {
        case songID = "song_id", recordingID = "recording_id"
        case title, artists, album, duration
    }
    init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        if let reference = try values.decodeIfPresent(String.self, forKey: .recordingID) { id = reference }
        else { id = "netease:\(try values.decode(Int.self, forKey: .songID))" }
        title = try values.decode(String.self, forKey: .title)
        artists = try values.decode([String].self, forKey: .artists)
        album = try values.decode(String.self, forKey: .album)
        duration = try values.decode(Double.self, forKey: .duration)
    }
    var isValid: Bool {
        Self.validReference(id) && !title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty &&
        !artists.isEmpty && artists.allSatisfy { !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty } &&
        duration.isFinite && duration > 0
    }
    static func validReference(_ id: String) -> Bool {
        id.count <= 220 && id.range(of: "^(netease:[1-9][0-9]*|(?:lrcapi|proofread):[A-Za-z0-9_-]{1,180})$", options: .regularExpression) != nil
    }
}

struct LyricUpdate: Decodable, Sendable {
    let requestID: Int
    let language: PronunciationLanguage
    let selectedLanguage: PronunciationLanguage?
    let reason: String
    let status: LyricStatus
    let message: String
    let lyrics: LiveLyrics?
    let selectionRevision: Int?

    enum CodingKeys: String, CodingKey {
        case requestID = "request_id", selectedLanguage = "selected_language"
        case selectionRevision = "selection_revision"
        case language, reason, status, message, lyrics
    }

    var languageDescription: String {
        if language == .original { return "Original lyrics only" }
        if language == .auto {
            guard let selectedLanguage else { return "Auto · Choose a language to add pronunciation" }
            let basis = lyrics?.proofread == nil ? "Artist-based guess" : "Proofread transcription"
            return "Auto · \(selectedLanguage.label) · \(basis)"
        }
        return language.label
    }

    var isValid: Bool {
        guard requestID >= 0,
              (selectionRevision ?? 0) >= 0,
              selectedLanguage == nil || selectedLanguage == .cantonese || selectedLanguage == .hokkien else { return false }
        if let lyrics {
            guard lyrics.recordingID == nil || RecordingCandidate.validReference(lyrics.recordingID!) else { return false }
            guard lyrics.lines.allSatisfy({ $0.time == nil || $0.time!.isFinite }) else { return false }
        }
        switch status {
        case .ready: return lyrics?.synced == true && lyrics?.instrumental == false && lyrics?.lines.isEmpty == false
        case .plain: return lyrics?.synced == false && lyrics?.instrumental == false && lyrics?.lines.isEmpty == false
        case .instrumental: return lyrics?.instrumental == true
        case .loading, .unavailable, .error: return lyrics == nil
        }
    }
}

struct RecordingUpdate: Decodable, Sendable, Equatable {
    let requestID: Int
    let status: String
    let candidates: [RecordingCandidate]
    let selectedID: String?
    let source: String
    let manual: Bool
    let switching: Bool
    let message: String
    let selectionRevision: Int

    enum CodingKeys: String, CodingKey {
        case requestID = "request_id", selectedID = "selected_id", selectionRevision = "selection_revision"
        case status, candidates, source, manual, switching, message
    }
    init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        requestID = try values.decode(Int.self, forKey: .requestID)
        selectionRevision = try values.decode(Int.self, forKey: .selectionRevision)
        status = try values.decode(String.self, forKey: .status)
        candidates = try values.decode([RecordingCandidate].self, forKey: .candidates)
        if let number = try? values.decode(Int.self, forKey: .selectedID) { selectedID = "netease:\(number)" }
        else { selectedID = try values.decodeIfPresent(String.self, forKey: .selectedID) }
        source = try values.decode(String.self, forKey: .source)
        manual = try values.decode(Bool.self, forKey: .manual)
        switching = try values.decode(Bool.self, forKey: .switching)
        message = try values.decode(String.self, forKey: .message)
    }
    var isValid: Bool {
        requestID >= 0 && selectionRevision >= 0 && ["idle", "loading", "ready", "error"].contains(status) &&
        (selectedID == nil || RecordingCandidate.validReference(selectedID!)) && candidates.count <= 30 && candidates.allSatisfy(\.isValid) &&
        Set(candidates.map(\.id)).count == candidates.count
    }
    var sourceName: String { String(source.split(separator: " ").first ?? "") }
}
