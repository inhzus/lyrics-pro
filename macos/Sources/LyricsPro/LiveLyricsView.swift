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

struct LyricSourceLabel: View {
    @ObservedObject var connection: MusicConnection

    var body: some View {
        if let lyrics = connection.state.lyric?.lyrics {
            HStack(spacing: 7) {
                if let url = lyrics.sourceURL {
                    Link(lyrics.sourceName, destination: url)
                        .help(lyrics.proofread.map { "\($0.attribution)\nOpen the timing source" } ?? "Open the lyric source")
                } else {
                    Text(lyrics.sourceName)
                }
                Text("·")
                Text(lyrics.instrumental ? "Instrumental" : (lyrics.synced ? "Timed lyrics" : "Untimed lyrics"))
                if let proofread = lyrics.proofread, lyrics.sourceName != "Proofread" {
                    Text("·")
                    Text("Proofread")
                        .help(proofread.attribution)
                }
            }
            .font(.system(size: 11))
            .foregroundStyle(.white.opacity(0.50))
            .lineLimit(1)
        }
    }
}

