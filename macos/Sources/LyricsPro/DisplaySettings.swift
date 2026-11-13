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

enum WindowSettings {
    /// Floats the player above other apps' windows while you sing along.
    static let keepOnTopKey = "keepWindowOnTop"
}

/// A numeric setting that snaps to steps inside a range; unreadable stored values reset.
struct SteppedSetting: Sendable {
    let range: ClosedRange<Double>
    let step: Double
    let standard: Double

    func clamped(_ value: Double) -> Double {
        guard value.isFinite else { return standard }
        let snapped = ((value / step).rounded() * step * 100).rounded() / 100
        return min(range.upperBound, max(range.lowerBound, snapped))
    }

    func bigger(_ value: Double) -> Double { clamped(clamped(value) + step) }
    func smaller(_ value: Double) -> Double { clamped(clamped(value) - step) }
}

/// Lyric size as a multiple of the layout's base size; pronunciation scales with it.
enum LyricTextScale {
    static let preferenceKey = "lyricsTextScale"
    static let setting = SteppedSetting(range: 0.8...1.5, step: 0.1, standard: 1.0)
    static var range: ClosedRange<Double> { setting.range }
    static var step: Double { setting.step }
    static var standard: Double { setting.standard }

    static func clamped(_ value: Double) -> Double { setting.clamped(value) }
    static func bigger(_ value: Double) -> Double { setting.bigger(value) }
    static func smaller(_ value: Double) -> Double { setting.smaller(value) }
    static func label(_ value: Double) -> String { "\(Int((clamped(value) * 100).rounded()))%" }
}

/// Shifts lyric highlighting against the audio for lyrics that drift. Display only:
/// Music's position and the timeline are unchanged.
enum LyricTiming {
    static let preferenceKey = "lyricsTimingDelay"
    static let setting = SteppedSetting(range: -3...3, step: 0.1, standard: 0)

    /// The lyric time to highlight for an audio position; a positive delay highlights later.
    static func lyricPosition(atAudio position: Double, delay: Double) -> Double {
        position - setting.clamped(delay)
    }

    /// The audio position at which a lyric time is highlighted, for click-to-seek.
    static func audioPosition(forLyric time: Double, delay: Double) -> Double {
        max(0, time + setting.clamped(delay))
    }

    static func label(_ delay: Double) -> String {
        let value = setting.clamped(delay)
        if value == 0 { return "In sync" }
        return String(format: "%.1f s %@", abs(value), value > 0 ? "later" : "earlier")
    }
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
