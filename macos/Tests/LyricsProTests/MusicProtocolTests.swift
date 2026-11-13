import Foundation
import Testing
@testable import LyricsPro

struct MusicProtocolTests {
    @Test func smallPipeEventsArriveBeforeEOF() throws {
        let pipe = Pipe()
        let received = DispatchSemaphore(value: 0)
        let finished = DispatchSemaphore(value: 0)
        DispatchQueue.global().async {
            defer { finished.signal() }
            try? EventStream.read(from: pipe.fileHandleForReading) { _ in received.signal() }
        }
        try pipe.fileHandleForWriting.write(contentsOf: Data("{\"version\":2,\"type\":\"ready\",\"generation\":0,\"track\":null,\"payload\":{}}\n".utf8))
        let delivered = received.wait(timeout: .now() + 1)
        try pipe.fileHandleForWriting.close()
        #expect(finished.wait(timeout: .now() + 1) == .success)
        try pipe.fileHandleForReading.close()
        #expect(delivered == .success)
    }

    private func playback(_ generation: Int, _ title: String = "A", state: String = "playing", position: Double = 12) throws -> BridgeEvent {
        try BridgeEvent.decode(Data("""
        {"version":2,"type":"playback","generation":\(generation),"track":{"title":"\(title)","artist":"Artist","album":"Album","duration":200},"payload":{"completed_control_id":0,"snapshot":{"state":"\(state)","title":"\(title)","artist":"Artist","album":"Album","duration":200,"position":\(position)}}}
        """.utf8))
    }

    private func artwork(_ generation: Int, _ title: String = "A") throws -> BridgeEvent {
        try BridgeEvent.decode(Data("""
        {"version":2,"type":"artwork","generation":\(generation),"track":{"title":"\(title)","artist":"Artist","album":"Album","duration":200},"payload":{"image":"aW1hZ2U="}}
        """.utf8))
    }

    @Test func staleArtworkIncludingABAIsIgnored() throws {
        var state = LiveMusicState()
        state.apply(try playback(1))
        state.apply(try artwork(1))
        #expect(state.artwork != nil)
        state.apply(try playback(2, "B"))
        #expect(state.artwork == nil)
        state.apply(try artwork(1))
        #expect(state.artwork == nil)
        state.apply(try playback(3))
        state.apply(try artwork(1))
        #expect(state.artwork == nil)
        state.apply(try artwork(3))
        #expect(state.artwork == Data("image".utf8))
    }

    @Test func pauseAndExternalSeeksKeepArtworkAndClampProgress() throws {
        var state = LiveMusicState()
        state.apply(try playback(1))
        state.apply(try artwork(1))
        state.apply(try playback(1, state: "paused", position: 90))
        #expect(state.playback?.elapsed == "1:30")
        #expect(state.playback?.progress == 0.45)
        #expect(state.artwork != nil)
        state.apply(try playback(1, position: -10))
        #expect(state.playback?.progress == 0)
        state.apply(try playback(1, position: 1000))
        #expect(state.playback?.progress == 1)
    }

    @Test func permissionFailureClearsSnapshotAndStaleArtwork() throws {
        var state = LiveMusicState()
        state.apply(try playback(1))
        state.apply(try artwork(1))
        state.apply(try BridgeEvent.decode(Data("""
        {"version":2,"type":"status","generation":2,"track":null,"payload":{"code":"permission_denied","message":"Enable Music for Lyrics Pro"}}
        """.utf8)))
        state.apply(try artwork(1))
        #expect(state.phase == .denied)
        #expect(state.playback == nil)
        #expect(state.artwork == nil)
    }

    @Test func closedAndStoppedStates() throws {
        for status in ["closed", "stopped"] {
            var state = LiveMusicState()
            state.apply(try playback(1))
            state.apply(try BridgeEvent.decode(Data("""
            {"version":2,"type":"playback","generation":2,"track":null,"payload":{"completed_control_id":0,"snapshot":{"state":"\(status)","title":"","artist":"","album":"","duration":0,"position":0}}}
            """.utf8)))
            #expect(state.phase.rawValue == status)
            #expect(state.identity == nil)
        }
        #expect(throws: (any Error).self) { try playback(1, state: "buffering") }
        let seeking = try playback(1, state: "fast forwarding")
        guard case .playback(let snapshot, _) = seeking.payload else { Issue.record("Expected playback"); return }
        #expect(snapshot.state == .fastForwarding && snapshot.hasTrack && !snapshot.state.isPlaying)
    }

    @Test func framingHandlesSplitUnicodeAndMultipleEvents() throws {
        let json = "{\"version\":2,\"type\":\"status\",\"generation\":1,\"payload\":{\"code\":\"unavailable\",\"message\":\"朴树\"}}\n"
        let data = Data((json + json).utf8)
        let split = data.firstIndex(of: 0xe6)! + 1
        var framer = EventFramer()
        #expect(try framer.append(data.prefix(split)).isEmpty)
        let result = try framer.append(data.suffix(from: split))
        #expect(result.count == 2)
        guard case .status(_, let message) = result[0].payload else { Issue.record("Expected status"); return }
        #expect(message == "朴树")
    }

    @Test func invalidProtocolAndOversizedFramesAreRejected() {
        #expect(throws: (any Error).self) { try BridgeEvent.decode(Data("{\"version\":1,\"type\":\"ready\",\"generation\":0}".utf8)) }
        #expect(throws: (any Error).self) { try BridgeEvent.decode(Data("{\"version\":2,\"type\":\"retry\",\"generation\":0}".utf8)) }
        #expect(throws: (any Error).self) {
            try BridgeEvent.decode(Data("{\"version\":2,\"type\":\"status\",\"generation\":0,\"payload\":{\"code\":\"x\"}}".utf8))
        }
        #expect(throws: (any Error).self) { try BridgeEvent.decode(Data("not json".utf8)) }
        var framer = EventFramer()
        #expect(throws: (any Error).self) { try framer.append(Data(repeating: 65, count: 8 * 1024 * 1024 + 1)) }
    }

    @Test func dataStatsDecodeAndDataCommandsEncode() throws {
        func decode(_ payload: String) throws -> BridgeEvent {
            try BridgeEvent.decode(Data("{\"version\":2,\"type\":\"data_stats\",\"generation\":3,\"track\":null,\"payload\":\(payload)}".utf8))
        }
        let event = try decode(#"{"lyrics_entries":12,"lyrics_bytes":40960,"recording_choices":2,"song_languages":0,"message":""}"#)
        guard case .dataStats(let stats) = event.payload else { Issue.record("Expected data stats"); return }
        #expect(stats == DataStats(lyricsEntries: 12, lyricsBytes: 40960, recordingChoices: 2, songLanguages: 0, message: ""))
        let unreadable = try decode(#"{"lyrics_entries":null,"lyrics_bytes":null,"recording_choices":0,"song_languages":1,"message":"Couldn’t read the lyrics cache."}"#)
        guard case .dataStats(let partial) = unreadable.payload else { Issue.record("Expected data stats"); return }
        #expect(partial.lyricsEntries == nil && partial.songLanguages == 1)
        #expect(throws: (any Error).self) {
            try decode(#"{"lyrics_entries":-1,"lyrics_bytes":0,"recording_choices":0,"song_languages":0,"message":""}"#)
        }

        func json(_ command: WorkerCommand) throws -> [String: Any] {
            try #require(JSONSerialization.jsonObject(with: command.frame()) as? [String: Any])
        }
        let clear = try json(.clearData([.lyricsCache, .songLanguages]))
        #expect(clear["type"] as? String == "clear_data")
        #expect((clear["payload"] as? [String: Any])?["targets"] as? [String] == ["lyrics_cache", "song_languages"])
        let request = try json(.getDataStats)
        #expect(request["type"] as? String == "get_data_stats" && (request["payload"] as? [String: Any])?.isEmpty == true)
    }
}
