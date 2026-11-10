import SwiftUI

private typealias FollowingStorage = State<LyricFollowingState>

struct LiveLyricsView: View {
    @ObservedObject var connection: MusicConnection
    let accent: Color
    let fontSize: CGFloat
    @FollowingStorage private var following = LyricFollowingState()

    private var update: LyricUpdate? { connection.state.lyric }

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            HStack(spacing: 16) {
                if let lyrics = update?.lyrics {
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
                }
                Spacer(minLength: 0)
                if update?.savedChoice == true {
                    Button("Forget recording choice") { connection.forgetRecording() }
                        .buttonStyle(PlayerCapsuleStyle(accent: accent))
                        .help("Clear the saved lyric recording for this song and search again")
                }
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
            if let update, (update.status == .ready || update.status == .plain), let lyrics = update.lyrics {
                FollowingLyricsView(lyrics: lyrics, generation: connection.state.generation,
                                    requestID: update.requestID, position: connection.presentation.position,
                                    accent: accent, fontSize: fontSize, following: $following,
                                    canSeek: connection.canSeek, followRevision: connection.controls.followRevision,
                                    seek: { [generation = connection.state.generation] position in
                                        connection.control(.seek, position: position, resumeFollowing: true,
                                                           expectedGeneration: generation)
                                    })
            } else if update?.status == .chooseRecording {
                recordingChooser
            } else {
                statusPanel
            }
        }
    }

    private var recordingChooser: some View {
        let generation = connection.state.generation
        let requestID = update?.requestID ?? 0
        return ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                Text("Choose your recording")
                    .font(.system(size: 26, weight: .semibold))
                    .foregroundStyle(.white.opacity(0.95))
                Text("The title and duration match, but we couldn’t verify the artist. Select your recording to use its lyrics.")
                    .font(.system(size: 14))
                    .foregroundStyle(.white.opacity(0.6))
                if let track = connection.state.playback {
                    Text("Apple Music · \(track.artist) · \(track.album) · \(MusicSnapshot.timeLabel(track.duration))")
                        .font(.system(size: 12))
                        .foregroundStyle(accent)
                }
                ForEach(update?.candidates ?? []) { candidate in
                    Button {
                        connection.chooseRecording(candidate, generation: generation, requestID: requestID)
                    } label: {
                        VStack(alignment: .leading, spacing: 6) {
                            HStack {
                                Text(candidate.title).font(.system(size: 17, weight: .semibold))
                                Spacer()
                                Text(MusicSnapshot.timeLabel(candidate.duration)).monospacedDigit()
                            }
                            Text(candidate.artists.joined(separator: " & "))
                            Text("\(candidate.album.isEmpty ? "Unknown album" : candidate.album) · NetEase")
                                .foregroundStyle(.white.opacity(0.55))
                        }
                        .font(.system(size: 13))
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(16)
                    }
                    .buttonStyle(RecordingChoiceStyle())
                }
                Text("Your choice is remembered for this song only. If none match, leave them unselected.")
                    .font(.system(size: 12))
                    .foregroundStyle(.white.opacity(0.45))
            }
            .padding(.vertical, 12)
            .padding(.trailing, 16)
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

private struct RecordingChoiceStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .foregroundStyle(.white.opacity(0.9))
            .background(.white.opacity(configuration.isPressed ? 0.12 : 0.055),
                        in: RoundedRectangle(cornerRadius: 12))
            .overlay(RoundedRectangle(cornerRadius: 12).strokeBorder(.white.opacity(0.12)))
            .contentShape(RoundedRectangle(cornerRadius: 12))
    }
}
