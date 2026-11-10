import SwiftUI
import AppKit

private typealias HeightStorage = State<[Int: CGFloat]>
private typealias VisibleRowStorage = State<Int?>
private typealias ScrollingStorage = State<Bool>
private typealias DragDeadlineStorage = State<Date>
private typealias HoveredRowStorage = State<Int?>

private struct LyricFrames: PreferenceKey {
    static let defaultValue: [Int: CGRect] = [:]
    static func reduce(value: inout [Int: CGRect], nextValue: () -> [Int: CGRect]) {
        value.merge(nextValue(), uniquingKeysWith: { _, new in new })
    }
}

private struct LyricLayout: Equatable {
    let generation: Int
    let request: Int
    let size: CGSize
}

struct FollowingLyricsView: View {
    let lyrics: LiveLyrics
    let generation: Int
    let requestID: Int
    let position: Double
    let accent: Color
    let fontSize: CGFloat
    @Binding var following: LyricFollowingState
    let canSeek: Bool
    let followRevision: Int
    let seek: (Double) -> Void
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @HeightStorage private var heights: [Int: CGFloat] = [:]
    @VisibleRowStorage private var visibleRow: Int?
    @ScrollingStorage private var userIsScrolling = false
    @DragDeadlineStorage private var suppressClickUntil = Date.distantPast
    @HoveredRowStorage private var hoveredRow: Int?

    var body: some View {
        GeometryReader { viewport in
            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 18) {
                        ForEach(Array(lyrics.lines.enumerated()), id: \.offset) { index, line in
                            row(line, index: index)
                                .id(index)
                                .background {
                                    GeometryReader { row in
                                        Color.clear.preference(key: LyricFrames.self,
                                                               value: [index: row.frame(in: .named("lyricsViewport"))])
                                    }
                                }
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.vertical, following.timeline.isTimed ? viewport.size.height / 2 : 18)
                    .padding(.trailing, 16)
                }
                .coordinateSpace(name: "lyricsViewport")
                .scrollIndicators(.visible)
                .onScrollPhaseChange { _, phase in
                    switch phase {
                    case .tracking, .interacting, .decelerating:
                        userIsScrolling = true
                        following.userScrolled()
                        if let visibleRow { following.rememberVisibleRow(visibleRow) }
                    case .idle, .animating:
                        userIsScrolling = false
                    @unknown default: break
                    }
                }
                .onPreferenceChange(LyricFrames.self) { frames in
                    let visible = frames.filter { $0.value.maxY > 0 && $0.value.minY < viewport.size.height }
                        .min { $0.value.minY < $1.value.minY }?.key
                    if visibleRow != visible { visibleRow = visible }
                    if userIsScrolling, let visible { following.rememberVisibleRow(visible) }
                    var updatedHeights = heights
                    for (id, frame) in frames { updatedHeights[id] = frame.height }
                    if updatedHeights != heights { heights = updatedHeights }
                }
                .task(id: LyricLayout(generation: generation, request: requestID, size: viewport.size)) {
                    hoveredRow = nil
                    let target = following.load(lyrics, generation: generation, position: position)
                    // Let the stack lay out with its new padding/line heights first.
                    await Task.yield()
                    guard !Task.isCancelled else { return }
                    scroll(to: target, proxy: proxy, viewport: viewport.size, animated: false)
                }
                .onChange(of: position) { _, position in
                    let target = following.advance(to: position)
                    scroll(to: target, proxy: proxy, viewport: viewport.size, animated: true)
                }
                .onChange(of: canSeek) { _, available in
                    if !available { hoveredRow = nil }
                }
                .onChange(of: followRevision) { _, _ in
                    _ = following.advance(to: position)
                    scroll(to: following.resume(), proxy: proxy, viewport: viewport.size, animated: true)
                }
                .onChange(of: heights[following.selection.anchor ?? -1]) { _, height in
                    // A lazy row may be measured only after the first scroll.
                    // Correct very tall targets once their actual height is known.
                    if following.isFollowing, let height, height > viewport.size.height {
                        scroll(to: following.selection.anchor, proxy: proxy, viewport: viewport.size, animated: false)
                    }
                }
                .overlay(alignment: .bottomTrailing) {
                    if following.showsResume {
                        Button {
                            scroll(to: following.resume(), proxy: proxy, viewport: viewport.size, animated: true)
                        } label: {
                            Label("Resume following", systemImage: "arrow.down.to.line")
                        }
                        .buttonStyle(PlayerCapsuleStyle(accent: accent))
                        .background(.ultraThinMaterial, in: Capsule())
                        .padding(.trailing, 18)
                        .padding(.bottom, 12)
                    }
                }
            }
        }
    }

    private func scroll(to row: Int?, proxy: ScrollViewProxy, viewport: CGSize, animated: Bool) {
        guard let row else { return }
        let center = following.isFollowing && following.timeline.isTimed && (heights[row] ?? 0) <= viewport.height
        withAnimation(animated && !reduceMotion ? .easeInOut(duration: 0.3) : nil) {
            proxy.scrollTo(row, anchor: center ? .center : .top)
        }
    }

    @ViewBuilder private func row(_ line: LiveLyricLine, index: Int) -> some View {
        if let target = LyricSeek.position(for: line, synced: lyrics.synced), let time = line.time {
            Button {
                if !userIsScrolling, Date() >= suppressClickUntil { seek(target) }
            } label: {
                rowContent(line, index: index)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .onHover { hovering in
                if hovering && canSeek {
                    hoveredRow = index
                } else if hoveredRow == index {
                    hoveredRow = nil
                }
            }
            .onDisappear {
                if hoveredRow == index { hoveredRow = nil }
            }
            .simultaneousGesture(DragGesture(minimumDistance: 6)
                .onChanged { _ in suppressClickUntil = Date().addingTimeInterval(0.15) }
                .onEnded { _ in suppressClickUntil = Date().addingTimeInterval(0.15) })
            .disabled(!canSeek)
            .help("Seek to \(MusicSnapshot.timeLabel(time))")
            .accessibilityHint("Seek to \(MusicSnapshot.timeLabel(time)) in Apple Music")
            .contextMenu {
                Button("Copy lyric") {
                    NSPasteboard.general.clearContents()
                    NSPasteboard.general.setString(line.text, forType: .string)
                }
            }
        } else {
            rowContent(line, index: index).textSelection(.enabled)
        }
    }

    private func rowContent(_ line: LiveLyricLine, index: Int) -> some View {
        let active = following.selection.active == index
        let dimmed = following.timeline.isTimed && !active
        let hovered = canSeek && !userIsScrolling && hoveredRow == index
            && LyricSeek.position(for: line, synced: lyrics.synced) != nil
        return VStack(alignment: .leading, spacing: 10) {
            Text(line.text.isEmpty ? " " : line.text)
                .font(.system(size: fontSize, weight: .bold))
                .foregroundStyle(.white.opacity(dimmed ? (hovered ? 0.66 : 0.38) : 0.98))
                .lineSpacing(8)
            if let pronunciation = line.pronunciation, !pronunciation.isEmpty, pronunciation != line.text {
                Text(pronunciation)
                    .font(.system(size: fontSize * 0.46, weight: .medium))
                    .foregroundStyle(active || !following.timeline.isTimed ? accent : .white.opacity(hovered ? 0.58 : 0.35))
                    .lineSpacing(6)
            }
        }
        .fixedSize(horizontal: false, vertical: true)
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .background(.white.opacity(hovered ? 0.06 : 0), in: RoundedRectangle(cornerRadius: 12))
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(active ? .isSelected : [])
        .animation(reduceMotion ? nil : .easeInOut(duration: 0.2), value: active)
        .animation(reduceMotion ? nil : .easeInOut(duration: 0.12), value: hovered)
    }
}
