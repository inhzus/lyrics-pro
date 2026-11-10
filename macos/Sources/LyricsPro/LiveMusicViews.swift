import SwiftUI

struct MusicArtworkView: View {
    let image: NSImage?
    let loading: Bool

    var body: some View {
        GeometryReader { geometry in
            ZStack {
                LinearGradient(colors: [Color(red: 0.10, green: 0.20, blue: 0.24), Color(red: 0.03, green: 0.07, blue: 0.10)], startPoint: .topLeading, endPoint: .bottomTrailing)
                if let image {
                    Image(nsImage: image)
                        .resizable()
                        .scaledToFill()
                        .frame(width: geometry.size.width, height: geometry.size.height)
                        .clipped()
                } else {
                    VStack(spacing: 16) {
                        Image(systemName: "music.note")
                            .font(.system(size: geometry.size.width * 0.18, weight: .light))
                        Text(loading ? "Loading artwork…" : "No artwork available")
                            .font(.system(size: 14))
                    }
                    .foregroundStyle(.white.opacity(0.4))
                }
            }
        }
        .aspectRatio(1, contentMode: .fit)
        .clipShape(RoundedRectangle(cornerRadius: 14))
        .overlay(RoundedRectangle(cornerRadius: 14).strokeBorder(.white.opacity(0.10)))
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(image == nil ? "Artwork unavailable" : "Current song artwork")
    }
}

struct MusicStatusView: View {
    @ObservedObject var connection: MusicConnection
    let accent: Color

    private var heading: String {
        switch connection.state.phase {
        case .connecting: "Connecting to Music"
        case .live: "Your music, in view."
        case .closed: "Open Music to begin."
        case .stopped: "Ready when you are."
        case .denied: "Allow access to Music."
        case .failed: "Connection interrupted."
        }
    }

    private var detail: String {
        switch connection.state.phase {
        case .connecting: "Waiting for the current song and artwork."
        case .live: "Preparing lyrics for the current song."
        case .closed: "Open Apple Music and choose a song.\nLyrics Pro will connect automatically."
        case .stopped: "Play a song in Apple Music to see it here."
        case .denied, .failed: connection.state.message
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 22) {
            Text("APPLE MUSIC")
                .font(.system(size: 10, weight: .semibold))
                .tracking(2)
                .foregroundStyle(accent.opacity(0.8))
            Spacer()
            Image(systemName: connection.state.phase == .denied ? "lock.open" : "waveform")
                .font(.system(size: 36, weight: .light))
                .foregroundStyle(accent)
                .accessibilityHidden(true)
            Text(heading)
                .font(.system(size: 34, weight: .bold))
                .fixedSize(horizontal: false, vertical: true)
            Text(detail)
                .font(.system(size: 16))
                .foregroundStyle(.white.opacity(0.58))
                .lineSpacing(6)
                .fixedSize(horizontal: false, vertical: true)
            if connection.state.phase == .failed || connection.state.phase == .denied {
                Button("Reconnect") { connection.reconnect() }
                    .buttonStyle(.bordered)
                    .disabled(connection.restarting)
            }
            Spacer()
            Label("Playback is controlled in Apple Music", systemImage: "music.note")
                .font(.system(size: 12))
                .foregroundStyle(.white.opacity(0.35))
                .padding(.bottom, 32)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
    }
}
