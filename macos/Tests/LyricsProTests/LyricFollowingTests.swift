import Foundation
import Testing
@testable import LyricsPro

struct LyricFollowingTests {
    private func lyrics(_ values: [(Double?, String)] = [(10, "First"), (20, "Second"), (25, ""), (30, "Last")],
                        synced: Bool = true) -> LiveLyrics {
        LiveLyrics(lines: values.map { LiveLyricLine(text: $0.1, time: $0.0, pronunciation: nil) },
                   source: "Test", synced: synced, instrumental: false)
    }

    @Test func timestampBoundariesGapsAndFinalLine() {
        let timeline = LyricTimeline(lyrics())
        #expect(timeline.selection(at: 0) == .init(active: nil, anchor: 0))
        #expect(timeline.selection(at: 9.999).active == nil)
        #expect(timeline.selection(at: 10).active == 0)
        #expect(timeline.selection(at: 19.999).active == 0)
        #expect(timeline.selection(at: 20).active == 1)
        #expect(timeline.selection(at: 25) == .init(active: nil, anchor: 1))
        #expect(timeline.selection(at: 29).active == nil)
        #expect(timeline.selection(at: 30).active == 3)
        #expect(timeline.selection(at: 1000).active == 3)
    }

    @Test func repeatedAndUnsortedTimestampsUseLastMatchingRow() {
        let timeline = LyricTimeline(lyrics([(20, "Later"), (10, "First"), (10, "Same time"), (nil, "Untimed")]))
        #expect(timeline.selection(at: 10).active == 2)
        #expect(timeline.selection(at: 20).active == 0)
        let blanks = LyricTimeline(lyrics([(10, "Line"), (10, "  "), (20, "Next")]))
        #expect(blanks.selection(at: 10).active == nil)
    }

    @Test func untimedEmptyAndInvalidPositionsDoNotHighlight() {
        for value in [lyrics(synced: false), lyrics([]), lyrics([(nil, "Original only")])] {
            let timeline = LyricTimeline(value)
            #expect(!timeline.isTimed)
            #expect(timeline.selection(at: 20).active == nil)
        }
        #expect(LyricTimeline(lyrics()).selection(at: .nan).active == nil)
        #expect(LyricTimeline(lyrics()).selection(at: .infinity).active == nil)
    }

    @Test func lateArrivalPauseAndSeeksRequestOnlyNecessaryScrolls() {
        var state = LyricFollowingState()
        #expect(state.load(lyrics(), generation: 1, position: 22) == 1)
        #expect(state.selection.active == 1)
        #expect(state.advance(to: 22) == nil) // paused
        #expect(state.advance(to: 24) == nil) // same line
        #expect(state.advance(to: 25) == nil) // blank clears highlight without a jump
        #expect(state.selection.active == nil)
        #expect(state.advance(to: 31) == 3)
        #expect(state.advance(to: 12) == 0) // backward seek
        #expect(state.advance(to: 21) == 1)
        #expect(state.advance(to: 0) == 0) // seek before the first lyric
        #expect(state.selection.active == nil)
    }

    @Test func manualBrowsingKeepsHighlightButBlocksScrollUntilResume() {
        var state = LyricFollowingState()
        _ = state.load(lyrics(), generation: 1, position: 11)
        state.userScrolled()
        state.rememberVisibleRow(0)
        #expect(state.showsResume)
        #expect(state.advance(to: 22) == nil)
        #expect(state.selection.active == 1)
        #expect(state.advance(to: 32) == nil)
        #expect(state.selection.active == 3)
        #expect(state.resume() == 3)
        #expect(!state.showsResume)
        #expect(state.advance(to: 12) == 0)
    }

    @Test func languageReloadRetryAndResizePreserveBrowsing() {
        var state = LyricFollowingState()
        _ = state.load(lyrics(), generation: 1, position: 11)
        state.userScrolled()
        state.rememberVisibleRow(2)
        for _ in 0..<3 {
            #expect(state.load(lyrics(), generation: 1, position: 31) == 2)
            #expect(state.showsResume)
            #expect(state.selection.active == 3)
        }
        // A retry can yield a shorter lyric document. Restore a valid row.
        #expect(state.load(lyrics([(10, "Only row")]), generation: 1, position: 31) == 0)
        #expect(state.showsResume)
    }

    @Test func trackGenerationChangesAndReconnectRestoreFollowing() {
        var state = LyricFollowingState()
        _ = state.load(lyrics(), generation: 1, position: 11)
        state.userScrolled()
        state.rememberVisibleRow(3)
        #expect(state.load(lyrics(), generation: 2, position: 21) == 1)
        #expect(state.isFollowing)
        state.userScrolled()
        #expect(state.load(lyrics(), generation: 3, position: 11) == 0) // A -> B -> A
        #expect(state.isFollowing)
        state.reset(generation: -1)
        #expect(state.load(lyrics(), generation: 1, position: 31) == 3)
        #expect(!state.showsResume)
    }

    @Test func untimedLyricsKeepBrowsePositionWithoutResumeControl() {
        var state = LyricFollowingState()
        let plain = lyrics(synced: false)
        #expect(state.load(plain, generation: 1, position: 22) == 0)
        state.userScrolled()
        state.rememberVisibleRow(2)
        #expect(state.load(plain, generation: 1, position: 30) == 2)
        #expect(state.advance(to: 100) == nil)
        #expect(!state.showsResume)
        #expect(state.selection.active == nil)
    }
}
