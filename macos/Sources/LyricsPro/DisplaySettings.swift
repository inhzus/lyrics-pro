import Foundation

/// How Chinese lyric text is displayed. Only the visible lyric lines change:
/// pronunciation, matching, caches, and track metadata keep the provider's text.
enum ChineseScript: String, CaseIterable, Identifiable, Sendable {
    case original, simplified, traditional

    static let preferenceKey = "lyricsChineseScript"
    var id: Self { self }

    var label: String {
        switch self {
        case .original: "As provided"
        case .simplified: "Simplified (简体)"
        case .traditional: "Traditional (繁體)"
        }
    }

    /// macOS's ICU transforms convert phrases (头发 → 頭髮), not just characters.
    private var transform: StringTransform? {
        switch self {
        case .original: nil
        case .simplified: StringTransform("Hant-Hans")
        case .traditional: StringTransform("Hans-Hant")
        }
    }

    func convert(_ text: String) -> String {
        guard let transform, !text.isEmpty else { return text }
        return text.applyingTransform(transform, reverse: false) ?? text
    }

    func convert(_ lyrics: LiveLyrics) -> LiveLyrics {
        guard self != .original else { return lyrics }
        let lines = lyrics.lines.map { LiveLyricLine(text: convert($0.text), time: $0.time, pronunciation: $0.pronunciation) }
        return LiveLyrics(lines: lines, source: lyrics.source, synced: lyrics.synced, instrumental: lyrics.instrumental,
                          proofread: lyrics.proofread, recordingID: lyrics.recordingID)
    }
}

/// Lyric size as a multiple of the layout's base size; pronunciation scales with it.
enum LyricTextScale {
    static let preferenceKey = "lyricsTextScale"
    static let range: ClosedRange<Double> = 0.8...1.5
    static let step = 0.1
    static let standard = 1.0

    /// Snaps to a 10 % step inside the range; unreadable stored values reset.
    static func clamped(_ value: Double) -> Double {
        guard value.isFinite else { return standard }
        let snapped = (value / step).rounded() * step
        return min(range.upperBound, max(range.lowerBound, (snapped * 100).rounded() / 100))
    }

    static func bigger(_ value: Double) -> Double { clamped(clamped(value) + step) }
    static func smaller(_ value: Double) -> Double { clamped(clamped(value) - step) }
    static func label(_ value: Double) -> String { "\(Int((clamped(value) * 100).rounded())) %" }
}

/// Remembers the last conversion so frequent view updates do not reconvert lyrics.
@MainActor
final class ScriptConversionCache {
    private var source: LiveLyrics?
    private var script = ChineseScript.original
    private var result: LiveLyrics?

    func lyrics(_ lyrics: LiveLyrics, in script: ChineseScript) -> LiveLyrics {
        if let result, script == self.script, source == lyrics { return result }
        let converted = script.convert(lyrics)
        (source, self.script, result) = (lyrics, script, converted)
        return converted
    }
}
