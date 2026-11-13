import Foundation
import Testing
@testable import LyricsPro

struct DisplaySettingsTests {
    private let lyrics = LiveLyrics(
        lines: [LiveLyricLine(text: "头发乱了", time: 1, pronunciation: "tau4 faat3 lyun6 liu5"),
                LiveLyricLine(text: "穿過樹的風 Live!", time: 2, pronunciation: nil),
                LiveLyricLine(text: "", time: 3, pronunciation: nil)],
        source: "NetEase https://music.163.com/song?id=1", synced: true, instrumental: false,
        recordingID: "netease:1")

    @Test func scriptConversionChangesOnlyLyricText() {
        let traditional = ChineseScript.traditional.convert(lyrics)
        #expect(traditional.lines.map(\.text) == ["頭髮亂了", "穿過樹的風 Live!", ""])
        #expect(ChineseScript.simplified.convert(lyrics).lines.map(\.text) == ["头发乱了", "穿过树的风 Live!", ""])
        // Readings, timing, and identity stay as the worker sent them.
        #expect(traditional.lines.map(\.pronunciation) == lyrics.lines.map(\.pronunciation))
        #expect(traditional.lines.map(\.time) == lyrics.lines.map(\.time))
        #expect(traditional.source == lyrics.source && traditional.recordingID == lyrics.recordingID)
        #expect(ChineseScript.original.convert(lyrics) == lyrics)
    }

    @Test func unknownStoredScriptIsNotAChoice() {
        #expect(ChineseScript(rawValue: "hong-kong") == nil)
        #expect(ChineseScript.allCases.map(\.rawValue) == ["original", "simplified", "traditional"])
    }

    @MainActor @Test func conversionIsCachedUntilLyricsOrScriptChange() {
        let cache = ScriptConversionCache()
        let first = cache.lyrics(lyrics, in: .traditional)
        #expect(cache.lyrics(lyrics, in: .traditional) == first)
        #expect(cache.lyrics(lyrics, in: .simplified).lines[0].text == "头发乱了")
        let other = LiveLyrics(lines: [LiveLyricLine(text: "发现", time: 1, pronunciation: nil)],
                               source: lyrics.source, synced: true, instrumental: false)
        #expect(cache.lyrics(other, in: .simplified).lines[0].text == "发现")
        #expect(cache.lyrics(other, in: .traditional).lines[0].text == "發現")
    }

    @Test func textScaleStepsSnapAndStayInRange() {
        #expect(LyricTextScale.bigger(1.0) == 1.1 && LyricTextScale.smaller(1.0) == 0.9)
        #expect(LyricTextScale.bigger(1.5) == 1.5 && LyricTextScale.smaller(0.8) == 0.8)
        #expect(LyricTextScale.clamped(1.1000000000000001) == 1.1 && LyricTextScale.clamped(1.04) == 1.0)
        #expect(LyricTextScale.clamped(9) == 1.5 && LyricTextScale.clamped(-1) == 0.8)
        #expect(LyricTextScale.clamped(.nan) == 1.0 && LyricTextScale.clamped(.infinity) == 1.0)
        #expect(LyricTextScale.label(1.2) == "120 %")
        var value = 0.8
        for _ in 0..<7 { value = LyricTextScale.bigger(value) }
        #expect(value == 1.5)
    }

    @Test func timingDelayShiftsHighlightAndRoundTripsLyricSeeks() {
        #expect(LyricTiming.lyricPosition(atAudio: 10, delay: 0.5) == 9.5)
        #expect(LyricTiming.lyricPosition(atAudio: 10, delay: -0.5) == 10.5)
        #expect(LyricTiming.audioPosition(forLyric: 0.2, delay: -1) == 0)
        #expect(LyricTiming.lyricPosition(atAudio: 10, delay: 99) == 7)  // Clamped to 3 s.
        // A clicked line seeks to the audio time at which that same line is highlighted.
        let line = LiveLyricLine(text: "Target", time: 46.76, pronunciation: nil)
        let lines = [LiveLyricLine(text: "Previous", time: 41, pronunciation: nil), line]
        let timeline = LyricTimeline(LiveLyrics(lines: lines, source: "Test", synced: true, instrumental: false))
        for delay in [-1.3, 0, 0.7] {
            let target = LyricSeek.position(for: line, synced: true)!
            let audio = LyricTiming.audioPosition(forLyric: target, delay: delay)
            #expect(timeline.selection(at: LyricTiming.lyricPosition(atAudio: audio, delay: delay)).active == 1)
        }
        #expect(LyricTiming.label(0) == "In sync" && LyricTiming.label(0.5) == "0.5 s later")
        #expect(LyricTiming.label(-1.2) == "1.2 s earlier" && LyricTiming.label(-1.21) == "1.2 s earlier")
    }
}
