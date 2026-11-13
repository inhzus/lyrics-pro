import SwiftUI

struct MusicArtworkView: View {
    let image: NSImage?
    let loading: Bool

    var body: some View {
        GeometryReader { geometry in
            ZStack {
                // Translucent, so the artwork-tinted background shows through the placeholder.
                Color.white.opacity(0.05)
                if let image {
                    Image(nsImage: image)
                        .resizable()
                        .scaledToFill()
                        .frame(width: geometry.size.width, height: geometry.size.height)
                        .clipped()
                } else if loading {
                    ProgressView().controlSize(.small)
                } else {
                    Image(systemName: "music.note")
                        .font(.system(size: geometry.size.width * 0.16, weight: .light))
                        .foregroundStyle(.white.opacity(0.25))
                }
            }
        }
        .aspectRatio(1, contentMode: .fit)
        .clipShape(RoundedRectangle(cornerRadius: 14))
        .overlay(RoundedRectangle(cornerRadius: 14).strokeBorder(.white.opacity(0.10)))
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(image == nil ? (loading ? "Loading artwork" : "Artwork unavailable") : "Current song artwork")
    }
}

/// One layout for every empty, waiting, and error state in the lyric column.
struct StatusPanel: View {
    struct Action {
        let title: String
        var disabled = false
        let perform: () -> Void
    }

    /// Nil shows a quiet progress line instead of a headline.
    let icon: String?
    let title: String
    var detail: String = ""
    let accent: Color
    var action: Action?

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            Spacer()
            if let icon {
                Image(systemName: icon)
                    .font(.system(size: 32, weight: .light))
                    .foregroundStyle(accent)
                    .accessibilityHidden(true)
                Text(title)
                    .font(.system(size: 32, weight: .bold))
                    .fixedSize(horizontal: false, vertical: true)
                if !detail.isEmpty {
                    Text(detail)
                        .font(.system(size: 15))
                        .foregroundStyle(.white.opacity(0.6))
                        .lineSpacing(5)
                        .fixedSize(horizontal: false, vertical: true)
                }
                if let action {
                    Button(action.title, action: action.perform)
                        .buttonStyle(.bordered)
                        .disabled(action.disabled)
                }
            } else {
                HStack(spacing: 10) {
                    ProgressView().controlSize(.small)
                    Text(title)
                        .font(.system(size: 15, weight: .medium))
                        .foregroundStyle(.white.opacity(0.6))
                }
                .accessibilityElement(children: .combine)
            }
            Spacer()
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
    }
}

struct MusicStatusView: View {
    @ObservedObject var connection: MusicConnection
    let accent: Color

    var body: some View {
        let phase = connection.state.phase
        let reconnect = StatusPanel.Action(title: "Reconnect", disabled: connection.restarting) { connection.reconnect() }
        switch phase {
        case .connecting, .live:
            StatusPanel(icon: nil, title: "Connecting to Music…", accent: accent)
        case .closed:
            StatusPanel(icon: "waveform", title: "Open Music to begin",
                        detail: "Choose a song in Apple Music. Lyrics Pro connects automatically.", accent: accent)
        case .stopped:
            StatusPanel(icon: "waveform", title: "Ready when you are",
                        detail: "Play a song in Apple Music to see its lyrics here.", accent: accent)
        case .denied:
            StatusPanel(icon: "lock", title: "Allow access to Music", detail: connection.state.message,
                        accent: accent, action: reconnect)
        case .failed:
            StatusPanel(icon: "exclamationmark.circle", title: "Connection interrupted", detail: connection.state.message,
                        accent: accent, action: reconnect)
        }
    }
}
