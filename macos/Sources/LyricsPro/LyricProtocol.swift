import Foundation

enum PronunciationLanguage: String, CaseIterable, Decodable, Sendable {
    case cantonese, hokkien, original, supplied
    case inherit = "default"

    // Supplied spelling is an effective backend language, never a user preference.
    static let choices: [Self] = [.cantonese, .hokkien, .original]
    static let songChoices: [Self] = [.inherit] + choices

    static let preferenceKey = "pronunciationLanguage"
    var shortLabel: String {
        switch self {
        case .inherit: "Default"
        case .cantonese: "Jyutping"
        case .hokkien: "Tâi-lô"
        case .original: "Original"
        case .supplied: "Supplied"
        }
    }
    var label: String {
        switch self {
        case .inherit: "Use Default"
        case .cantonese: "Cantonese · Jyutping"
        case .hokkien: "Hokkien · Tâi-lô"
        case .original: "Original only"
        case .supplied: "Supplied spelling"
        }
    }
    static func saved(in defaults: UserDefaults = .standard) -> Self {
        let value = Self(rawValue: defaults.string(forKey: preferenceKey) ?? "") ?? .cantonese
        let migrated = choices.contains(value) ? value : .cantonese
        defaults.set(migrated.rawValue, forKey: preferenceKey)
        return migrated
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
        if id.hasPrefix("lrclib:") { return "LRCLIB" }
        return id.hasPrefix("lrcapi:") ? "LrcAPI" : "NetEase"
    }
    enum CodingKeys: String, CodingKey {
        case id = "recording_id", title, artists, album, duration
    }
    var isValid: Bool {
        Self.validReference(id) && !title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty &&
        !artists.isEmpty && artists.allSatisfy { !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty } &&
        duration.isFinite && duration > 0
    }
    static func validReference(_ id: String) -> Bool {
        id.count <= 220 && id.range(of: "^((?:netease|lrclib):[1-9][0-9]*|(?:lrcapi|proofread):[A-Za-z0-9_-]{1,180})$", options: .regularExpression) != nil
    }
}

/// Why the worker chose the effective pronunciation language.
enum LyricReason: String, Decodable, Sendable {
    case songPreference = "song preference"
    case proofread = "proofread transcription"
    case globalDefault = "global default"

    var label: String {
        switch self {
        case .songPreference: "Song preference"
        case .proofread: "Proofread default"
        case .globalDefault: "Global default"
        }
    }
}

struct LyricUpdate: Decodable, Sendable {
    let requestID: Int
    let language: PronunciationLanguage
    let selectedLanguage: PronunciationLanguage?
    let reason: LyricReason
    let status: LyricStatus
    let message: String
    let lyrics: LiveLyrics?
    let selectionRevision: Int?
    var songLanguage: PronunciationLanguage? = nil
    var preferenceWarning: String? = nil

    enum CodingKeys: String, CodingKey {
        case requestID = "request_id", selectedLanguage = "selected_language"
        case selectionRevision = "selection_revision"
        case songLanguage = "song_language", preferenceWarning = "preference_warning"
        case language, reason, status, message, lyrics
    }

    var languageDescription: String {
        let effective = selectedLanguage ?? .original
        return "\(reason.label) · \(effective.label)"
    }

    var isValid: Bool {
        guard requestID >= 0,
              PronunciationLanguage.choices.contains(language),
              songLanguage == nil || PronunciationLanguage.songChoices.contains(songLanguage!),
              (selectionRevision ?? 0) >= 0,
              selectedLanguage == nil || selectedLanguage == .cantonese || selectedLanguage == .hokkien ||
              (selectedLanguage == .supplied && (lyrics == nil || lyrics?.proofread?.language == "supplied")) else { return false }
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

enum RecordingStatus: String, Decodable, Sendable {
    case idle, loading, ready, error
    var isSearching: Bool { self == .idle || self == .loading }
}

struct RecordingUpdate: Decodable, Sendable, Equatable {
    let requestID: Int
    let status: RecordingStatus
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
    var isValid: Bool {
        requestID >= 0 && selectionRevision >= 0 &&
        (selectedID == nil || RecordingCandidate.validReference(selectedID!)) && candidates.count <= 30 && candidates.allSatisfy(\.isValid) &&
        Set(candidates.map(\.id)).count == candidates.count
    }
    var sourceName: String { String(source.split(separator: " ").first ?? "") }
}
