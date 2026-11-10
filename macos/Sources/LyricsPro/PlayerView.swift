import SwiftUI

struct PlayerView: View {
    @ObservedObject var connection: MusicConnection
    private var demo: DemoSong? { connection.demo }

    private var song: DemoSong { demo ?? .cantonese }
    private var snapshot: MusicSnapshot? { connection.state.playback }
    private var title: String { demo != nil ? song.title : (snapshot?.hasTrack == true ? snapshot!.title : "Apple Music") }
    private var subtitle: String {
        if demo != nil { return song.subtitle }
        guard let snapshot, snapshot.hasTrack else { return "Your listening companion" }
        return [snapshot.artist, snapshot.album].filter { !$0.isEmpty }.joined(separator: " — ")
    }
    private var status: String {
        switch connection.state.phase {
        case .connecting: "Connecting…"
        case .live: snapshot?.state == "paused" ? "Paused" : "Playing"
        case .closed, .stopped: "Waiting for Music"
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
            let artworkSide = min(440, (geometry.size.width - inset * 2 - gap) * 0.38, (geometry.size.height - 240) * 0.70)
            ZStack {
                background
                VStack(spacing: 0) {
                    header
                    HStack(spacing: gap) {
                        albumPanel(side: artworkSide)
                            .frame(width: artworkSide)
                        Group {
                            if demo != nil {
                                lyricsPanel(fontSize: compact ? 30 : 38)
                            } else if connection.state.phase == .live {
                                LiveLyricsView(connection: connection, accent: song.accent,
                                               fontSize: compact ? 30 : 38)
                            } else {
                                MusicStatusView(connection: connection, accent: song.accent)
                            }
                        }
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                    }
                    .padding(.horizontal, inset)
                    .padding(.top, 28)
                    .padding(.bottom, 24)
                    footer
                }
            }
        }
    }

    private var background: some View {
        GeometryReader { geometry in
            ZStack {
                Color(red: 0.055, green: 0.08, blue: 0.10)
                cover
                    .frame(width: max(geometry.size.width, geometry.size.height) * 1.3)
                    .blur(radius: 100)
                    .opacity(0.40)
                    .position(x: geometry.size.width * 0.35, y: geometry.size.height * 0.65)
                LinearGradient(colors: [.black.opacity(0.05), .black.opacity(0.40)], startPoint: .topLeading, endPoint: .bottomTrailing)
            }
            .clipped()
        }
        .ignoresSafeArea()
        .accessibilityHidden(true)
    }

    private var header: some View {
        HStack(spacing: 9) {
            Image(systemName: "waveform")
                .foregroundStyle(song.accent)
            Text("Lyrics Pro")
                .font(.system(size: 13, weight: .semibold))
                .foregroundStyle(.white.opacity(0.80))
            Spacer()
            if demo != nil || connection.state.phase != .live {
                Text(demo != nil ? "Demo · \(song.rawValue)" : status)
                    .font(.system(size: 12, weight: .medium))
                    .foregroundStyle(.white.opacity(0.55))
                    .fixedSize()
            }
        }
        .padding(.leading, 24)
        .padding(.trailing, 24)
        .frame(height: 48)
    }

    private func albumPanel(side: CGFloat) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            cover
                .frame(width: side, height: side)
                .shadow(color: .black.opacity(0.3), radius: 25, y: 16)
            Text(title)
                .font(.system(size: 22, weight: .semibold))
                .foregroundStyle(.white.opacity(0.95))
                .padding(.top, 25)
                .lineLimit(3)
                .help(title)
            Text(subtitle)
                .font(.system(size: 14))
                .foregroundStyle(.white.opacity(0.50))
                .padding(.top, 6)
                .fixedSize(horizontal: false, vertical: true)
                .lineLimit(2)
                .help(subtitle)
            if demo == nil {
                PlaybackPanel(connection: connection, accent: song.accent)
                    .padding(.top, 20)
                    .textSelection(.disabled)
            } else {
                VStack(spacing: 9) {
                    GeometryReader { geometry in
                        ZStack(alignment: .leading) {
                            Capsule().fill(.white.opacity(0.13))
                            Capsule().fill(.white.opacity(0.65)).frame(width: geometry.size.width * 0.28)
                        }
                    }
                    .frame(height: 4)
                    HStack {
                        Text("0:42")
                        Spacer()
                        Text("2:30")
                    }
                    .overlay {
                        Text("DEMO TIMELINE")
                            .font(.system(size: 9, weight: .medium)).tracking(1.4)
                    }
                    .font(.system(size: 11, design: .monospaced))
                    .foregroundStyle(.white.opacity(0.35))
                }
                .padding(.top, 25)
                .accessibilityElement(children: .ignore)
                .accessibilityLabel("Demo progress: 42 seconds of 2 minutes 30 seconds")
            }
        }
        .textSelection(.enabled)
    }

    private func lyricsPanel(fontSize: CGFloat) -> some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack(spacing: 8) {
                Text(song.language)
                Circle().fill(song.accent).frame(width: 3, height: 3)
                Text(song.system)
            }
            .font(.system(size: 10, weight: .semibold))
            .tracking(2)
            .foregroundStyle(song.accent.opacity(0.8))
            ScrollView {
                VStack(alignment: .leading, spacing: 36) {
                    Color.clear.frame(height: 28).accessibilityHidden(true)
                    ForEach(song.lines) { line in
                        lyricRow(line, fontSize: fontSize)
                    }
                    Color.clear.frame(height: 100).accessibilityHidden(true)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.trailing, 14)
            }
            .id(song)
            .scrollIndicators(.hidden)
            .mask {
                VStack(spacing: 0) {
                    LinearGradient(colors: [.clear, .black], startPoint: .top, endPoint: .bottom).frame(height: 24)
                    Color.black
                    LinearGradient(colors: [.black, .clear], startPoint: .top, endPoint: .bottom).frame(height: 64)
                }
            }
        }
    }

    private func lyricRow(_ line: DemoLine, fontSize: CGFloat) -> some View {
        let active = line.id == 1
        return VStack(alignment: .leading, spacing: 12) {
            Text(line.text)
                .font(.system(size: fontSize, weight: .bold))
                .foregroundStyle(.white.opacity(active ? 0.98 : 0.28))
                .lineSpacing(9)
            if let pronunciation = line.pronunciation {
                Text(pronunciation)
                    .font(.system(size: fontSize * 0.44, weight: .medium))
                    .foregroundStyle(active ? song.accent : .white.opacity(0.25))
                    .lineSpacing(6)
            }
        }
        .fixedSize(horizontal: false, vertical: true)
        .frame(maxWidth: .infinity, alignment: .leading)
        .textSelection(.enabled)
        .accessibilityElement(children: .combine)
    }

    private var footer: some View {
        HStack(spacing: 7) {
            Image(systemName: demo != nil ? "sparkle" : "music.note").foregroundStyle(song.accent.opacity(0.65))
            Text(demo != nil ? "Original demo lyrics & artwork" : "Live metadata & artwork from Apple Music")
            Spacer()
            if demo != nil {
                Text("Demo content · Switch to Live Music for your song")
            } else {
                PronunciationMenu(language: connection.language, accent: song.accent,
                                  select: connection.selectLanguage)
            }
        }
        .font(.system(size: 11))
        .foregroundStyle(.white.opacity(0.36))
        .padding(.horizontal, 26)
        .frame(height: 52)
    }
}
