import Foundation
import Testing
@testable import LyricsPro

struct PlaybackControlTests {
    @Test func lyricSeekSurvivesMusicRoundingAndRejectsNonSeekableRows() throws {
        let line = LiveLyricLine(text: "Target", time: 46.76, pronunciation: nil)
        let target = try #require(LyricSeek.position(for: line, synced: true))
        let reported = Double(Float(target))
        let lyrics = LiveLyrics(lines: [LiveLyricLine(text: "Previous", time: 41, pronunciation: nil), line],
                                source: "Test", synced: true, instrumental: false)
        #expect(LyricTimeline(lyrics).selection(at: reported).active == 1)
        #expect(LyricSeek.position(for: line, synced: false) == nil)
        for invalid in [LiveLyricLine(text: "  ", time: 10, pronunciation: nil),
                        LiveLyricLine(text: "Text", time: nil, pronunciation: nil),
                        LiveLyricLine(text: "Text", time: -1, pronunciation: nil)] {
            #expect(LyricSeek.position(for: invalid, synced: true) == nil)
        }
    }
    private func result(id: Int = 1, generation: Int = 2, ok: Bool = true) throws -> BridgeEvent {
        try BridgeEvent.decode(Data("""
        {"version":2,"type":"control_result","generation":\(generation),"track":null,"payload":{"command_id":\(id),"ok":\(ok),"code":"control_failed","message":"Could not seek"}}
        """.utf8))
    }

    private func snapshot(position: Double = 12, playing: Bool = false, revision: Int = 0,
                          generation: Int = 2) throws -> BridgeEvent {
        try BridgeEvent.decode(Data("""
        {"version":2,"type":"playback","generation":\(generation),
        "track":{"title":"A","artist":"Artist","album":"Album","duration":200},
        "payload":{"completed_control_id":\(revision),"snapshot":{"state":"\(playing ? "playing" : "paused")",
        "title":"A","artist":"Artist","album":"Album","duration":200,"position":\(position)}}}
        """.utf8))
    }

    private static let track = TrackIdentity(title: "A", artist: "Artist", album: "Album", duration: 200)

    private func command(_ id: Int, _ action: PlaybackAction, position: Double? = nil,
                         generation: Int = 2) throws -> PlaybackCommand {
        PlaybackCommand(commandID: id, action: action, generation: generation, track: Self.track, position: position)
    }

    @Test func clicksUpdateImmediatelyAndRapidPlayPauseSettlesOnFinalIntent() throws {
        var state = PlaybackControlState()
        state.receive(try snapshot(), now: 0)
        state.enqueue(try command(1, .play), resumeFollowing: false, now: 0)
        #expect(state.presentation(at: 0).playing)
        #expect(state.takeNext(now: 0)?.action == .play)
        state.enqueue(try command(2, .pause), resumeFollowing: false, now: 0.2)
        #expect(!state.presentation(at: 0.2).playing)
        state.enqueue(try command(3, .play), resumeFollowing: false, now: 0.3)
        #expect(state.queued.count == 1)
        #expect(state.queued.first?.id == 3)
        #expect(state.takeNext(now: 0.3) == nil)
        state.receive(try snapshot(), now: 0.5) // Read from before either command.
        #expect(state.presentation(at: 0.5).playing)
        state.receive(try result(), now: 0.6)
        #expect(state.takeNext(now: 0.6)?.commandID == 3)
        state.receive(try snapshot(position: 13, playing: true, revision: 3), now: 1)
        state.receive(try result(id: 3), now: 1)
        #expect(state.presentation(at: 2).position == 14)
        #expect(!state.isUpdating(at: 2))
    }

    @Test func repeatedSeeksIgnoreOldSnapshotsAndAcknowledgements() throws {
        var state = PlaybackControlState()
        state.receive(try snapshot(), now: 0)
        state.enqueue(try command(1, .seek, position: 50), resumeFollowing: true, now: 0)
        #expect(state.followRevision == 1 && state.presentation(at: 0).position == 50)
        _ = state.takeNext(now: 0)
        state.enqueue(try command(2, .seek, position: 70), resumeFollowing: false, now: 0.1)
        state.enqueue(try command(3, .seek, position: 90), resumeFollowing: true, now: 0.2)
        #expect(state.queued.count == 1 && state.queued.first?.id == 3)
        state.receive(try snapshot(position: 50, revision: 1), now: 0.5)
        state.receive(try result(), now: 0.5)
        #expect(state.presentation(at: 0.5).position == 90)
        #expect(state.followRevision == 2)
        _ = state.takeNext(now: 0.5)
        state.receive(try result(id: 3), now: 0.7)
        state.receive(try snapshot(position: 90, revision: 1), now: 0.8)
        #expect(state.isUpdating(at: 2)) // Target alone is insufficient; revision is stale.
        state.receive(try snapshot(position: 90, revision: 3), now: 2)
        #expect(!state.isUpdating(at: 2) && state.presentation(at: 2).position == 90)
        state.receive(try snapshot(position: 50, revision: 1), now: 2.1)
        #expect(state.presentation(at: 2.1).position == 90)
    }

    @Test func lateExecutionAcceptsElapsedPositionAndPauseFreezesClock() throws {
        var state = PlaybackControlState()
        state.receive(try snapshot(playing: true), now: 0)
        #expect(state.presentation(at: 1).position == 13)
        state.enqueue(try command(1, .seek, position: 60), resumeFollowing: false, now: 1)
        _ = state.takeNext(now: 1)
        #expect(state.presentation(at: 4).position == 63)
        state.receive(try snapshot(position: 60.5, playing: true, revision: 1), now: 4)
        state.receive(try result(), now: 4)
        #expect(!state.isUpdating(at: 4))
        state.enqueue(try command(2, .pause), resumeFollowing: false, now: 4)
        #expect(state.presentation(at: 8).position == 60.5)
        #expect(!state.presentation(at: 8).playing)
    }

    @Test func failuresAndTimeoutsRestoreConfirmedStateWithoutUndoingNewerClicks() throws {
        var state = PlaybackControlState()
        state.receive(try snapshot(), now: 0)
        state.enqueue(try command(1, .seek, position: 50), resumeFollowing: false, now: 0)
        _ = state.takeNext(now: 0)
        state.enqueue(try command(2, .seek, position: 90), resumeFollowing: false, now: 0.2)
        state.receive(try result(ok: false), now: 1)
        #expect(state.presentation(at: 1).position == 90 && state.message == nil)
        _ = state.takeNext(now: 1)
        state.receive(try result(id: 2, ok: false), now: 2)
        #expect(state.presentation(at: 2).position == 12 && state.message != nil)
        state.enqueue(try command(3, .play), resumeFollowing: false, now: 3)
        _ = state.takeNext(now: 3)
        #expect(!state.isUpdating(at: 3.5))
        #expect(state.isUpdating(at: 4))
        let expired = state.expire(now: 13)
        #expect(expired)
        #expect(!state.presentation(at: 13).playing && state.inFlight == nil)
        state.receive(try result(id: 3), now: 14)
        #expect(!state.presentation(at: 14).playing)
    }

    @Test func skipGuardAndTrackTransitionsKeepOldIntentsOffTheNewTrack() throws {
        var state = PlaybackControlState()
        state.receive(try snapshot(), now: 0)
        #expect(state.enqueue(try command(1, .next), resumeFollowing: false, now: 0))
        _ = state.takeNext(now: 0)
        #expect(!state.enqueue(try command(2, .previous), resumeFollowing: false, now: 0.1))
        #expect(state.enqueue(try command(3, .seek, position: 90), resumeFollowing: true, now: 0.2))
        state.receive(try snapshot(position: 0, generation: 3), now: 1)
        #expect(!state.skipBusy && state.queued.isEmpty)
        #expect(state.presentation(at: 1).position == 0)
        #expect(state.inFlight != nil) // Real command remains serialized until it finishes.
        state.receive(try result(generation: 3), now: 1)
        #expect(state.inFlight == nil)
        #expect(!state.enqueue(try command(4, .seek, position: 90), resumeFollowing: true, now: 1))
        state.enqueue(try command(5, .play, generation: 3), resumeFollowing: false, now: 2)
        state.clearIntents(now: 2) // Demo transition.
        #expect(state.queued.isEmpty && !state.presentation(at: 2).playing)
        state.disconnect()
        #expect(state.inFlight == nil && state.queued.isEmpty)
        #expect(state.presentation(at: 2).duration == 0)
    }

    @Test func failedSeekRestoresTimeButPreservesANewerPause() throws {
        var state = PlaybackControlState()
        state.receive(try snapshot(playing: true), now: 0)
        state.enqueue(try command(1, .seek, position: 90), resumeFollowing: false, now: 0)
        _ = state.takeNext(now: 0)
        state.enqueue(try command(2, .pause), resumeFollowing: false, now: 0.2)
        state.receive(try result(ok: false), now: 1)
        #expect(state.presentation(at: 1).position == 13)
        #expect(!state.presentation(at: 1).playing)
        #expect(state.queued.first?.command.action == .pause)
    }

    @Test func pendingKindsKeepLatestUserOrderingAndGuardSkipUntilTrackChanges() throws {
        var state = PlaybackControlState()
        state.receive(try snapshot(), now: 0)
        state.enqueue(try command(1, .play), resumeFollowing: false, now: 0)
        _ = state.takeNext(now: 0)
        state.enqueue(try command(2, .seek, position: 90), resumeFollowing: false, now: 0.1)
        state.enqueue(try command(3, .pause), resumeFollowing: false, now: 0.2)
        state.enqueue(try command(4, .seek, position: 50), resumeFollowing: false, now: 0.3)
        #expect(state.queued.map(\.id) == [3, 4])
        state.clearIntents(now: 0.4)
        state.receive(try result(), now: 0.5)
        state.enqueue(try command(5, .next), resumeFollowing: false, now: 1)
        _ = state.takeNext(now: 1)
        state.receive(try result(id: 5), now: 2)
        #expect(state.skipBusy)
        state.expire(now: 11)
        #expect(!state.skipBusy && state.message != nil)
    }

    @Test func dragPreviewSurvivesPollingAndCannotSeekANewTrack() {
        var scrub = TimelineScrubState()
        scrub.begin(generation: 4, position: 12)
        scrub.update(90)
        #expect(scrub.preview == 90)
        #expect(scrub.finish(generation: 4, duration: 200) == 90)
        #expect(!scrub.isEditing && scrub.preview == nil)
        scrub.begin(generation: 4, position: 100)
        #expect(scrub.finish(generation: 5, duration: 200) == nil)
        scrub.begin(generation: 5, position: 100)
        scrub.cancel()
        #expect(scrub.finish(generation: 5, duration: 200) == nil)
    }

    @Test func scrubBoundsAndUnknownDuration() {
        for (position, expected) in [(-10.0, 0.0), (300.0, 200.0)] {
            var scrub = TimelineScrubState()
            scrub.begin(generation: 1, position: position)
            #expect(scrub.finish(generation: 1, duration: 200) == expected)
        }
        var scrub = TimelineScrubState()
        scrub.begin(generation: 1, position: .nan)
        #expect(scrub.finish(generation: 1, duration: 200) == nil)
        scrub.begin(generation: 1, position: 10)
        #expect(scrub.finish(generation: 1, duration: 0) == nil)
    }

    @Test func wireCommandsPreserveTrackIdentityAndResultsAreValidated() throws {
        let command = PlaybackCommand(commandID: 9, action: .seek, generation: 2, track: Self.track, position: 90)
        let frame = try WorkerCommand.playbackControl(command).frame()
        #expect(frame.last == 10)
        let json = try #require(JSONSerialization.jsonObject(with: frame) as? [String: Any])
        let payload = try #require(json["payload"] as? [String: Any])
        #expect(json["version"] as? Int == 2 && json["type"] as? String == "playback_control")
        #expect(payload["command_id"] as? Int == 9 && payload["position"] as? Double == 90)
        #expect((payload["track"] as? [String: Any])?["title"] as? String == "A")
        let skip = PlaybackCommand(commandID: 10, action: .next, generation: 2, track: Self.track, position: nil)
        let skipJSON = try #require(JSONSerialization.jsonObject(with: WorkerCommand.playbackControl(skip).frame()) as? [String: Any])
        #expect((skipJSON["payload"] as? [String: Any])?["position"] is NSNull)
        #expect(throws: (any Error).self) {
            try BridgeEvent.decode(Data("{\"version\":2,\"type\":\"control_result\",\"generation\":0,\"payload\":{}}".utf8))
        }
    }
}
