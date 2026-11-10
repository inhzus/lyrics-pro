import Foundation

/// Pure timing/state logic. Scroll geometry and animations belong to the view.
struct LyricTimeline: Sendable {
    struct Selection: Equatable, Sendable {
        var active: Int?
        var anchor: Int?
    }
    private struct Entry: Sendable {
        let time: Double
        let row: Int
        let blank: Bool
        let previousNonblank: Int?
    }
    private var entries: [Entry] = []
    private var firstNonblank: Int?
    var isTimed: Bool { !entries.isEmpty }

    init(_ lyrics: LiveLyrics) {
        guard lyrics.synced, !lyrics.instrumental else { return }
        let sorted = lyrics.lines.enumerated().compactMap { index, line -> (Double, Int, Bool)? in
            guard let time = line.time, time.isFinite else { return nil }
            return (time, index, line.text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
        }.sorted { $0.0 == $1.0 ? $0.1 < $1.1 : $0.0 < $1.0 }
        var previous: Int?
        for (time, row, blank) in sorted {
            if !blank {
                previous = row
                if firstNonblank == nil { firstNonblank = row }
            }
            entries.append(Entry(time: time, row: row, blank: blank, previousNonblank: previous))
        }
    }

    func selection(at position: Double) -> Selection {
        guard isTimed, position.isFinite else { return Selection() }
        // Upper bound chooses the last row at a duplicated timestamp.
        var lower = 0, upper = entries.count
        while lower < upper {
            let mid = (lower + upper) / 2
            if entries[mid].time <= position { lower = mid + 1 } else { upper = mid }
        }
        guard lower > 0 else { return Selection(anchor: firstNonblank) }
        let entry = entries[lower - 1]
        return Selection(active: entry.blank ? nil : entry.row,
                         anchor: entry.previousNonblank ?? firstNonblank)
    }
}

struct LyricFollowingState {
    private(set) var generation = -1
    private(set) var isFollowing = true
    private(set) var selection = LyricTimeline.Selection()
    private(set) var timeline = LyricTimeline(LiveLyrics(lines: [], source: "", synced: false, instrumental: false))
    private(set) var browsedRow: Int?
    private var rowCount = 0

    var showsResume: Bool { timeline.isTimed && !isFollowing }

    mutating func reset(generation: Int) {
        self = Self()
        self.generation = generation
    }

    /// Returns the row to restore after a load, language change, retry, or resize.
    mutating func load(_ lyrics: LiveLyrics, generation: Int, position: Double) -> Int? {
        if self.generation != generation { reset(generation: generation) }
        timeline = LyricTimeline(lyrics)
        rowCount = lyrics.lines.count
        selection = timeline.selection(at: position)
        if isFollowing && timeline.isTimed { return selection.anchor }
        guard rowCount > 0 else { return nil }
        return min(max(0, browsedRow ?? 0), rowCount - 1)
    }

    /// Repeated snapshots and pauses never generate another scroll request.
    mutating func advance(to position: Double) -> Int? {
        let previous = selection
        selection = timeline.selection(at: position)
        guard isFollowing, selection.anchor != previous.anchor else { return nil }
        return selection.anchor
    }

    mutating func userScrolled() {
        isFollowing = false
    }

    mutating func rememberVisibleRow(_ row: Int) {
        guard !isFollowing || !timeline.isTimed else { return }
        browsedRow = row
    }

    mutating func resume() -> Int? {
        isFollowing = true
        browsedRow = nil
        return selection.anchor
    }
}
