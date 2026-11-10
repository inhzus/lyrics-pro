import SwiftUI

private typealias FollowingStorage = State<LyricFollowingState>

struct LiveLyricsView: View {
    @ObservedObject var connection: MusicConnection
    let accent: Color
    let fontSize: CGFloat
    @FollowingStorage private var following = LyricFollowingState()

    private var update: LyricUpdate? { connection.state.lyric }

    var body: some View {
        Group {
            if let update, (update.status == .ready || update.status == .plain), let lyrics = update.lyrics {
                FollowingLyricsView(lyrics: lyrics, generation: connection.state.generation,
                                    requestID: update.requestID, recordingRevision: update.selectionRevision ?? 0,
                                    position: connection.presentation.position,
                                    accent: accent, fontSize: fontSize, following: $following,
                                    canSeek: connection.canSeek, followRevision: connection.controls.followRevision,
                                    seek: { [generation = connection.state.generation] position in
                                        connection.control(.seek, position: position, resumeFollowing: true,
                                                           expectedGeneration: generation)
                                    })
            } else {
                statusPanel
            }
        }
    }

    private var heading: String {
        switch update?.status {
        case .instrumental: "Just the music."
        case .unavailable: "No lyrics found."
        case .error: "Lyrics unavailable."
        default: "Finding the words…"
        }
    }

    private var detail: String {
        switch update?.status {
        case .instrumental: "The lyric provider marks this recording as instrumental."
        case .unavailable, .error: update?.message ?? "Try looking up this song again."
        default: update?.message ?? "Preparing lyrics for this song…"
        }
    }

    private var statusPanel: some View {
        VStack(alignment: .leading, spacing: 20) {
            Spacer()
            if update == nil || update?.status == .loading {
                ProgressView().controlSize(.small)
            } else {
                Image(systemName: update?.status == .instrumental ? "music.note" : "text.quote")
                    .font(.system(size: 32, weight: .light))
                    .foregroundStyle(accent)
                    .accessibilityHidden(true)
            }
            Text(heading)
                .font(.system(size: 34, weight: .bold))
            Text(detail)
                .font(.system(size: 15))
                .foregroundStyle(.white.opacity(0.58))
                .lineSpacing(5)
                .fixedSize(horizontal: false, vertical: true)
            if update?.status == .unavailable || update?.status == .error {
                Button("Try again") { connection.retryLyrics() }
                    .buttonStyle(.bordered)
            }
            Spacer()
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
    }
}

/// Shares the app's top header, leaving the full right-hand body for lyrics.
struct LiveLyricsHeader: View {
    @ObservedObject var connection: MusicConnection

    var body: some View {
        HStack(spacing: 16) {
            if let lyrics = connection.state.lyric?.lyrics {
                HStack(spacing: 7) {
                    if let url = lyrics.sourceURL {
                        Link(lyrics.sourceName, destination: url)
                            .help("Open the lyric source")
                    } else {
                        Text(lyrics.sourceName)
                    }
                    Text("·")
                    Text(lyrics.instrumental ? "Instrumental" : (lyrics.synced ? "Timed lyrics" : "Untimed lyrics"))
                }
                .font(.system(size: 11))
                .foregroundStyle(.white.opacity(0.50))
                .lineLimit(1)
            }
            Spacer(minLength: 0)
            Button { connection.retryLyrics() } label: {
                Image(systemName: "arrow.clockwise")
                    .font(.system(size: 13, weight: .medium))
                    .frame(width: 30, height: 30)
                    .background(.white.opacity(0.06), in: Circle())
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Retry lyrics")
            .help("Look up lyrics again")
        }
    }
}

