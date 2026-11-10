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

struct LiveLyrics: Decodable, Sendable {
    let lines: [LiveLyricLine]
    let source: String
    let synced: Bool
    let instrumental: Bool

    var sourceName: String { String(source.split(separator: " ", maxSplits: 1).first ?? "Lyrics") }
    var sourceURL: URL? {
        let parts = source.split(separator: " ", maxSplits: 1)
        guard parts.count == 2, let url = URL(string: String(parts[1])),
              url.scheme == "https", ["music.163.com", "lrclib.net"].contains(url.host),
              url.user == nil, url.password == nil else { return nil }
        return url
    }
}

enum LyricStatus: String, Decodable, Sendable {
    case loading, ready, plain, instrumental, unavailable, error
}

struct LyricUpdate: Decodable, Sendable {
    let requestID: Int
    let language: PronunciationLanguage
    let selectedLanguage: PronunciationLanguage?
    let reason: String
    let status: LyricStatus
    let message: String
    let lyrics: LiveLyrics?

    enum CodingKeys: String, CodingKey {
        case requestID = "request_id", selectedLanguage = "selected_language"
        case language, reason, status, message, lyrics
    }

    var languageDescription: String {
        if language == .original { return "Original lyrics only" }
        if language == .auto {
            guard let selectedLanguage else { return "Auto · Choose a language to add pronunciation" }
            return "Auto · \(selectedLanguage.label) · Artist-based guess"
        }
        return language.label
    }

    var isValid: Bool {
        guard requestID >= 0,
              selectedLanguage == nil || selectedLanguage == .cantonese || selectedLanguage == .hokkien else { return false }
        if let lyrics {
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
