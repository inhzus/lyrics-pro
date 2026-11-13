import SwiftUI

struct PlayerView: View {
    @ObservedObject var connection: MusicConnection
    @AppStorage(LyricTextScale.preferenceKey) private var textScale = LyricTextScale.standard
    private var demo: DemoSong? { connection.demo }

    private var song: DemoSong { demo ?? .cantonese }
    private var snapshot: MusicSnapshot? { connection.state.playback }
    private var title: String { demo != nil ? song.title : (snapshot?.hasTrack == true ? snapshot!.title : "") }
    private var subtitle: String {
        if demo != nil { return song.subtitle }
        guard let snapshot, snapshot.hasTrack else { return "" }
        return [snapshot.artist, snapshot.album].filter { !$0.isEmpty }.joined(separator: " — ")
    }
    private var status: String? {
        switch connection.state.phase {
        case .connecting: "Connecting…"
        case .live: snapshot?.state == .paused ? "Paused" : "Playing"
        case .closed, .stopped: nil
        case .denied: "Permission needed"
        case .failed: "Disconnected"
        }
    }

    @ViewBuilder private var cover: some View {
        if demo != nil {
            ArtworkView(song: song)
        } else {
            MusicArtworkView(image: connection.artworkImage,
                             loading: snapshot?.hasTrack == true && !connection.state.artworkReceived)
        }
    }

    var body: some View {
        GeometryReader { geometry in
            let compact = geometry.size.width < 1100
            let inset: CGFloat = compact ? 32 : 64
            let gap: CGFloat = compact ? 40 : 80
            let lyricSize = (compact ? 30 : 38) * LyricTextScale.clamped(textScale)
            let artworkSide = min(440, (geometry.size.width - inset * 2 - gap) * 0.38, (geometry.size.height - 240) * 0.70)
            ZStack {
                background
                VStack(spacing: 0) {
                    header(trailingInset: inset)
                    HStack(spacing: gap) {
                        albumPanel(side: artworkSide)
                            .frame(width: artworkSide)
                            .padding(.top, 20)
                        Group {
                            if demo != nil {
                                DemoLyricsPanel(song: song, fontSize: lyricSize)
                            } else if connection.state.phase == .live {
                                LiveLyricsView(connection: connection, accent: song.accent,
                                               fontSize: lyricSize)
                            } else {
                                MusicStatusView(connection: connection, accent: song.accent)
                            }
                        }
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                    }
                    .padding(.horizontal, inset)
                    .padding(.top, 8)
                    .padding(.bottom, 24)
                    footer
                }
            }
        }
    }

    private var background: some View {
        ArtworkBackground(artwork: connection.state.artwork, generation: connection.state.generation,
                          loading: snapshot?.hasTrack == true && !connection.state.artworkReceived,
                          connected: connection.state.phase == .live,
                          playing: connection.presentation.playing, demo: demo)
    }

    private func header(trailingInset: CGFloat) -> some View {
        HStack(spacing: 0) {
            HStack(spacing: 9) {
                Image(systemName: "waveform")
                    .foregroundStyle(song.accent)
                Text("Lyrics Pro")
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(.white.opacity(0.80))
            }
            Spacer()
            if demo == nil && connection.state.phase == .live {
                Button { connection.retryLyrics() } label: {
                    Image(systemName: "arrow.clockwise")
                        .font(.system(size: 13, weight: .medium))
                        .frame(width: 30, height: 30)
                        .background(.white.opacity(0.06), in: Circle())
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Retry lyrics")
                .help("Look up lyrics again and retry missing artwork")
            } else if let status = demo != nil ? "Demo · \(song.rawValue)" : status {
                Text(status)
                    .font(.system(size: 12, weight: .medium))
                    .foregroundStyle(.white.opacity(0.55))
                    .fixedSize()
            }
        }
        .padding(.leading, 24)
        .padding(.trailing, trailingInset)
        .frame(height: 48)
    }

    private func albumPanel(side: CGFloat) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            cover
                .frame(width: side, height: side)
                .shadow(color: .black.opacity(0.3), radius: 25, y: 16)
            // Reserve the metadata rows without placeholder copy when Music has no song.
            Text(title.isEmpty ? " " : title)
                .font(.system(size: 22, weight: .semibold))
                .foregroundStyle(.white.opacity(0.95))
                .padding(.top, 25)
                .lineLimit(3)
                .help(title)
                .accessibilityHidden(title.isEmpty)
            Text(subtitle.isEmpty ? " " : subtitle)
                .font(.system(size: 14))
                .foregroundStyle(.white.opacity(0.50))
                .padding(.top, 6)
                .fixedSize(horizontal: false, vertical: true)
                .lineLimit(2)
                .help(subtitle)
                .accessibilityHidden(subtitle.isEmpty)
            if demo == nil {
                PlaybackPanel(connection: connection, accent: song.accent)
                    .padding(.top, 20)
                    .textSelection(.disabled)
            } else {
                DemoTimeline()
                    .padding(.top, 25)
            }
        }
        .textSelection(.enabled)
    }

    private var footer: some View {
        HStack(spacing: 7) {
            if demo != nil {
                Image(systemName: "sparkle").foregroundStyle(song.accent.opacity(0.65))
                Text("Original demo lyrics & artwork")
            } else if connection.state.phase == .live {
                LyricSourceLabel(connection: connection)
            }
            Spacer()
            if demo != nil {
                Text("Demo content · Switch to Live Music for your song")
            } else {
                RecordingPicker(connection: connection, accent: song.accent)
                PronunciationMenu(connection: connection, accent: song.accent)
            }
        }
        .font(.system(size: 11))
        .foregroundStyle(.white.opacity(0.36))
        .padding(.horizontal, 26)
        .frame(height: 52)
    }
}
