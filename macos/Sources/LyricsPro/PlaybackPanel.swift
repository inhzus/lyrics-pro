import SwiftUI

private typealias ScrubStorage = State<TimelineScrubState>
private typealias TransportHoverStorage = State<Bool>

struct PlaybackPanel: View {
    @ObservedObject var connection: MusicConnection
    let accent: Color
    @ScrubStorage private var scrub = TimelineScrubState()

    private var duration: Double { connection.presentation.duration }
    private var position: Double { min(duration, max(0, scrub.preview ?? connection.presentation.position)) }
    private var paused: Bool { !connection.presentation.playing }

    var body: some View {
        VStack(spacing: 5) {
            Slider(value: Binding(get: { position }, set: { value in
                if scrub.isEditing {
                    scrub.update(value)
                } else {
                    // Native keyboard/accessibility adjustment has no drag session.
                    connection.control(.seek, position: value)
                }
            }), in: 0...max(1, duration), onEditingChanged: { editing in
                if editing {
                    scrub.begin(generation: connection.state.generation, position: position)
                } else if let target = scrub.finish(generation: connection.state.generation, duration: duration) {
                    connection.control(.seek, position: target)
                }
            })
            .tint(.white.opacity(0.65))
            .controlSize(.small)
            .disabled(!connection.canSeek)
            .accessibilityLabel("Playback position")
            .accessibilityValue("\(MusicSnapshot.timeLabel(position)) of \(MusicSnapshot.timeLabel(duration))")
            .help("Click or drag to seek in Apple Music")

            HStack {
                Text(MusicSnapshot.timeLabel(position))
                Spacer()
                Text(MusicSnapshot.timeLabel(duration))
            }
            .font(.system(size: 11).monospacedDigit())
            .foregroundStyle(.white.opacity(0.4))

            HStack(spacing: 24) {
                transport("Previous song", icon: "backward.end.fill", action: .previous)
                transport(paused ? "Play" : "Pause", icon: paused ? "play.fill" : "pause.fill",
                          action: paused ? .play : .pause, prominent: true)
                transport("Next song", icon: "forward.end.fill", action: .next)
            }
            .frame(maxWidth: .infinity)
            .padding(.top, 7)
            .disabled(!connection.canControl)

            if connection.updatingMusic {
                HStack(spacing: 6) {
                    ProgressView().controlSize(.mini)
                    Text("Updating Music…").font(.system(size: 11))
                }
                .foregroundStyle(.white.opacity(0.55))
                .accessibilityElement(children: .combine)
            }
            if let message = connection.controls.message {
                Text(message)
                    .font(.system(size: 11))
                    .foregroundStyle(.white.opacity(0.65))
                    .fixedSize(horizontal: false, vertical: true)
                    .accessibilityLabel("Playback control: \(message)")
            }
        }
        .onChange(of: connection.state.generation) { _, _ in scrub.cancel() }
        .onChange(of: connection.state.phase) { _, phase in
            if phase != .live { scrub.cancel() }
        }
        .onDisappear { scrub.cancel() }
    }

    private func transport(_ label: String, icon: String, action: PlaybackAction, prominent: Bool = false) -> some View {
        Button { connection.control(action) } label: {
            Image(systemName: icon)
                .font(.system(size: prominent ? 29 : 20, weight: .semibold))
                .frame(width: 48, height: 44)
                .contentShape(Rectangle())
        }
        .buttonStyle(TransportStyle(accent: accent, available: connection.canControl))
        .disabled(action.isSkip && connection.controls.skipBusy)
        .accessibilityLabel(label)
        .help("\(label) in Apple Music")
    }
}

private struct TransportStyle: ButtonStyle {
    let accent: Color
    let available: Bool
    func makeBody(configuration: Configuration) -> some View {
        TransportBody(configuration: configuration, accent: accent, available: available)
    }
    private struct TransportBody: View {
        let configuration: Configuration
        let accent: Color
        let available: Bool
        @TransportHoverStorage private var hovering = false
        @Environment(\.isFocused) private var focused
        @Environment(\.isEnabled) private var enabled
        var body: some View {
            configuration.label
                .foregroundStyle(.white.opacity(available ? 0.85 : 0.28))
                .background(.white.opacity(configuration.isPressed ? 0.14 : (hovering && enabled ? 0.07 : 0)),
                            in: RoundedRectangle(cornerRadius: 10))
                .overlay(RoundedRectangle(cornerRadius: 10).stroke(focused ? accent : .clear, lineWidth: 2))
                .onHover { hovering = $0 }
        }
    }
}
