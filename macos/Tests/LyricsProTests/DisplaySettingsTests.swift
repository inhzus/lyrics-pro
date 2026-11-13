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
}
