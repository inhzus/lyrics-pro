import Foundation
import Testing
@testable import LyricsPro

struct LyricProtocolTests {
    @Test func suppliedSpellingIsEffectiveLanguageWithoutAddingAMenuChoice() throws {
        let lyrics = LiveLyrics(lines: [LiveLyricLine(text: "甲", time: 2, pronunciation: "á")],
            source: "Proofread https://lrclib.net/api/get/42", synced: true, instrumental: false,
            proofread: ProofreadMetadata(asset_id: "sample", revision: "1", language: "supplied", attribution: "User"),
            recordingID: "proofread:sample")
        let update = LyricUpdate(requestID: 1, language: .auto, selectedLanguage: .supplied,
            reason: "proofread transcription", status: .ready, message: "", lyrics: lyrics, selectionRevision: 0)
        #expect(update.isValid && update.languageDescription.contains("Supplied spelling"))
        #expect(PronunciationLanguage.choices == [.auto, .cantonese, .hokkien, .original])
        #expect(RecordingCandidate.validReference("lrclib:42"))
        let invalid = LyricUpdate(requestID: 1, language: .supplied, selectedLanguage: .supplied,
            reason: "", status: .ready, message: "", lyrics: lyrics, selectionRevision: 0)
        #expect(!invalid.isValid)
        for status in [LyricStatus.loading, .error] {
            let transition = LyricUpdate(requestID: 1, language: .auto, selectedLanguage: .supplied,
                reason: "proofread transcription", status: status, message: "Preparing", lyrics: nil, selectionRevision: 0)
            #expect(transition.isValid)
        }
        let ordinary = LiveLyrics(lines: lyrics.lines, source: lyrics.source, synced: true, instrumental: false)
        let missingMetadata = LyricUpdate(requestID: 1, language: .auto, selectedLanguage: .supplied,
            reason: "", status: .ready, message: "", lyrics: ordinary, selectionRevision: 0)
        #expect(!missingMetadata.isValid)
    }

    @Test func proofreadIdentityIsIndependentOfItsTimingSource() throws {
        var payload: [String: Any] = ["source": "NetEase https://music.163.com/song?id=5237870",
            "synced": true, "instrumental": false,
            "lines": [["text": "少年吔,安啦!", "time": 51.02, "pronunciation": "siàu-liân leh an lah!"]]]
        func decode() throws -> LiveLyrics {
            try JSONDecoder().decode(LiveLyrics.self, from: JSONSerialization.data(withJSONObject: payload))
        }
        #expect(try decode().proofread == nil)
        #expect(try decode().recordingID == nil)
        payload["source"] = "Proofread https://music.163.com/song?id=5237870"
        payload["recording_id"] = "proofread:shao-nian-eh-an-la"
        payload["proofread"] = ["asset_id": "test", "revision": "1", "language": "hokkien", "attribution": "台語拼音：關德樂"]
        let lyrics = try decode()
        #expect(lyrics.proofread?.attribution == "台語拼音：關德樂")
        #expect(lyrics.sourceName == "Proofread" && lyrics.sourceURL?.host == "music.163.com")
        #expect(lyrics.recordingID == "proofread:shao-nian-eh-an-la")
        #expect(lyrics.lines[0].pronunciation == "siàu-liân leh an lah!")
        let update = LyricUpdate(requestID: 1, language: .auto, selectedLanguage: .hokkien,
            reason: "proofread transcription", status: .ready, message: "", lyrics: lyrics, selectionRevision: 0)
        #expect(update.isValid && update.languageDescription.contains("Proofread transcription"))
        #expect(!update.languageDescription.contains("Artist-based guess"))
    }

    @Test func providerQualifiedIDsAvoidCollisionsAndAllowLrcAPISources() throws {
        let candidates: [[String: Any]] = ["proofread:1", "netease:1", "lrcapi:1"].map { reference in
            ["recording_id": reference, "title": "忽然", "artists": ["李志"], "album": "你好,郑州", "duration": 126.853]
        }
        let payload: [String: Any] = ["request_id": 2, "status": "ready", "candidates": candidates,
            "selected_id": "proofread:1", "source": "Proofread", "manual": true, "switching": false,
            "message": "", "selection_revision": 1]
        let update = try JSONDecoder().decode(RecordingUpdate.self, from: JSONSerialization.data(withJSONObject: payload))
        #expect(update.isValid && update.selectedID == "proofread:1")
        #expect(update.candidates.map(\.sourceName) == ["Proofread", "NetEase", "LrcAPI"])
        #expect(!RecordingCandidate.validReference("lrcapi:https://example.com"))
        #expect(!RecordingCandidate.validReference("proofread:../other"))
        #expect(!RecordingCandidate.validReference("proofread:"))
        let lyrics = LiveLyrics(lines: [], source: "LrcAPI https://api.lrc.cx/jsonapi?title=test#1", synced: false, instrumental: false)
        #expect(lyrics.sourceURL?.host == "api.lrc.cx")
    }

    @Test func recordingAlternativesValidateIndependentlyOfLyrics() throws {
        let candidate: [String: Any] = ["song_id": 5284269, "title": "故乡", "artists": ["罗大佑"],
                                        "album": "新乐园", "duration": 277.676]
        func decode(_ candidates: [[String: Any]], status: String = "ready") throws -> RecordingUpdate {
            let payload: [String: Any] = ["request_id": 4, "status": status, "message": "",
                "candidates": candidates, "manual": false, "switching": false, "selection_revision": 0,
                "source": "NetEase https://music.163.com/song?id=5284269", "selected_id": 5284269]
            return try JSONDecoder().decode(RecordingUpdate.self, from: JSONSerialization.data(withJSONObject: payload))
        }
        let valid = try decode([candidate])
        #expect(valid.isValid && valid.candidates.first?.id == "netease:5284269")
        #expect(valid.manual == false)
        #expect(try decode([]).isValid)
        #expect(try !decode([], status: "unknown").isValid)
        #expect(try !decode([candidate, candidate]).isValid)
        let many = (1...30).map { id in candidate.merging(["song_id": id]) { _, new in new } }
        #expect(try decode(many).isValid)
        #expect(try !decode(many + [candidate]).isValid)
        for patch in [["song_id": -1], ["duration": 0], ["artists": []], ["title": " "]] as [[String: Any]] {
            #expect(try !decode([candidate.merging(patch) { _, new in new }]).isValid)
        }
    }

    @Test func recordingUpdatesPreserveLyricsAndRejectStaleResponses() throws {
        func recordingEvent(generation: Int = 1, request: Int = 1) throws -> BridgeEvent {
            let payload: [String: Any] = ["version": 1, "type": "recordings", "generation": generation,
                "track": ["A", "Artist", "Album", 200],
                "recordings": ["request_id": request, "status": "loading", "message": "",
                    "candidates": [], "manual": false, "switching": true, "selection_revision": 0,
                    "source": "NetEase https://music.163.com/song?id=1", "selected_id": 1]]
            return try BridgeEvent.decode(JSONSerialization.data(withJSONObject: payload))
        }
        var state = LiveMusicState()
        state.apply(try event("playback"))
        state.apply(try event("lyrics"))
        state.prepareLyrics(requestID: 1, preserve: true)
        #expect(state.lyric?.lyrics != nil)
        state.apply(try recordingEvent(request: 0))
        #expect(state.recordings == nil)
        state.apply(try recordingEvent())
        #expect(state.recordings?.switching == true && state.lyric?.lyrics != nil)
        state.apply(try event("playback", generation: 2, title: "B"))
        #expect(state.recordings == nil)
        state.apply(try recordingEvent())
        #expect(state.recordings == nil)
    }

    private func event(_ type: String, generation: Int = 1, title: String = "A", request: Int = 0,
                       language: String = "auto", status: String = "ready", source: String = "NetEase https://music.163.com/song?id=1") throws -> BridgeEvent {
        var payload: [String: Any] = ["version": 1, "type": type, "generation": generation,
                                      "track": [title, "Artist", "Album", 200]]
        if type == "playback" {
            payload["playback"] = ["state": "paused", "title": title, "artist": "Artist", "album": "Album", "duration": 200, "position": 12]
        } else {
            let lyrics: [String: Any] = ["source": source, "synced": status != "plain", "instrumental": status == "instrumental",
                                         "lines": [["text": "令神仙鱼归天要怪谁", "time": status == "plain" ? NSNull() as Any : 21.6 as Any,
                                                    "pronunciation": "ling6 san4 sin1 jyu2 gwai1 tin1 jiu3 gwaai3 seoi4"]]]
            payload["lyric"] = ["request_id": request, "language": language, "selected_language": "cantonese",
                                "reason": "artist-based guess", "status": status, "message": "",
                                "lyrics": ["loading", "unavailable", "error"].contains(status) ? NSNull() as Any : lyrics as Any]
        }
        return try BridgeEvent.decode(JSONSerialization.data(withJSONObject: payload))
    }

    @Test func languageRevisionRejectsOldResponseEvenAfterSwitchingBack() throws {
        var state = LiveMusicState()
        state.apply(try event("playback"))
        state.apply(try event("lyrics"))
        #expect(state.lyric?.lyrics?.lines.first?.time == 21.6)
        state.prepareLyrics(requestID: 1)
        #expect(state.lyric == nil)
        #expect(state.playback?.title == "A")
        state.apply(try event("lyrics"))
        #expect(state.lyric == nil)
        state.apply(try event("lyrics", request: 1, language: "cantonese"))
        #expect(state.lyric?.language == .cantonese)
        state.prepareLyrics(requestID: 2)
        state.apply(try event("lyrics", request: 1, language: "cantonese"))
        #expect(state.lyric == nil)
        state.apply(try event("lyrics", request: 2))
        #expect(state.lyric?.language == .auto)
    }

    @Test func trackChangesAndDisconnectClearLyricsAndRejectStaleABA() throws {
        var state = LiveMusicState()
        state.apply(try event("playback"))
        state.apply(try event("lyrics"))
        state.apply(try event("playback", generation: 2, title: "B"))
        #expect(state.lyric == nil)
        state.apply(try event("playback", generation: 3))
        state.apply(try event("lyrics"))
        #expect(state.lyric == nil)
        state.apply(try event("lyrics", generation: 3))
        #expect(state.lyric != nil)
        state.fail("Disconnected")
        state.apply(try event("lyrics", generation: 3))
        #expect(state.lyric == nil)
    }

    @Test func statusesAndUntimedLinesDecodeWithoutInventingTimes() throws {
        for status in ["loading", "ready", "plain", "instrumental", "unavailable", "error"] {
            let result = try event("lyrics", status: status)
            #expect(result.lyric?.status.rawValue == status)
            if status == "plain" {
                #expect(result.lyric?.lyrics?.synced == false)
                #expect(result.lyric?.lyrics?.lines.first?.time == nil)
            }
        }
        #expect(throws: (any Error).self) { try event("lyrics", status: "invalid") }
        #expect(throws: (any Error).self) { try event("lyrics", request: -1) }
        #expect(throws: (any Error).self) { try event("lyrics", language: "unsupported") }
    }

    @Test func sourceLinksOnlyUseExpectedHTTPSProviders() throws {
        let netease = try event("lyrics").lyric!.lyrics!
        #expect(netease.sourceName == "NetEase")
        #expect(netease.sourceURL?.host == "music.163.com")
        #expect(try event("lyrics", source: "LRCLIB https://lrclib.net/api/get/1").lyric?.lyrics?.sourceURL != nil)
        for source in ["Example https://example.com", "NetEase javascript:alert(1)", "NetEase http://music.163.com", "NetEase https://music.163.com@example.com", "NetEase"] {
            #expect(try event("lyrics", source: source).lyric?.lyrics?.sourceURL == nil)
        }
    }

    @Test func languagePreferenceDefaultsAndPersists() throws {
        let name = "LyricsProTests.\(UUID())"
        let defaults = try #require(UserDefaults(suiteName: name))
        defer { defaults.removePersistentDomain(forName: name) }
        #expect(PronunciationLanguage.saved(in: defaults) == .auto)
        defaults.set("hokkien", forKey: PronunciationLanguage.preferenceKey)
        #expect(PronunciationLanguage.saved(in: defaults) == .hokkien)
        defaults.set("supplied", forKey: PronunciationLanguage.preferenceKey)
        #expect(PronunciationLanguage.saved(in: defaults) == .auto)
        defaults.set("invalid", forKey: PronunciationLanguage.preferenceKey)
        #expect(PronunciationLanguage.saved(in: defaults) == .auto)
    }
}
