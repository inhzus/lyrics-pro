import SwiftUI

private typealias HoverState = State<Bool>

struct PronunciationMenu: View {
    @ObservedObject var connection: MusicConnection
    let accent: Color
    @HoverState private var hovering = false
    @FocusState private var focused: Bool

    var body: some View {
        Menu {
            Picker("This Song", selection: Binding(get: { connection.songLanguage }, set: { connection.selectSongLanguage($0) })) {
                ForEach(PronunciationLanguage.songChoices, id: \.self) { option in
                    Text(option.label).tag(option)
                }
            }
            .pickerStyle(.inline)
            .disabled(!connection.canChooseSongLanguage)
            Divider()
            Picker("Global Default", selection: Binding(get: { connection.language }, set: { connection.selectLanguage($0) })) {
                ForEach(PronunciationLanguage.choices, id: \.self) { option in
                    Text(option.label).tag(option)
                }
            }
            .pickerStyle(.inline)
            if let warning = connection.state.pronunciation?.preferenceWarning, !warning.isEmpty {
                Text(warning)
            }
        } label: {
            HStack(spacing: 7) {
                Image(systemName: "character.bubble")
                Text(connection.effectiveLanguage.shortLabel)
                Image(systemName: "chevron.down")
                    .font(.system(size: 9, weight: .semibold))
            }
            .playerCapsule(accent: accent, hovering: hovering, focused: focused)
        }
        .menuStyle(.button)
        .menuIndicator(.hidden)
        .buttonStyle(.plain)
        .fixedSize()
        .focused($focused)
        .onHover { hovering = $0 }
        .accessibilityLabel("Pronunciation: \(connection.effectiveLanguage.label)")
        .help(connection.state.pronunciation?.languageDescription ?? "Global default · \(connection.language.label)")
    }
}

struct PlayerCapsuleStyle: ButtonStyle {
    let accent: Color

    func makeBody(configuration: Configuration) -> some View {
        CapsuleBody(configuration: configuration, accent: accent)
    }

    private struct CapsuleBody: View {
        let configuration: Configuration
        let accent: Color
        @HoverState private var hovering = false
        @Environment(\.isFocused) private var focused

        var body: some View {
            HStack(spacing: 7) { configuration.label }
                .playerCapsule(accent: accent, hovering: hovering, focused: focused)
                .onHover { hovering = $0 }
        }
    }
}

extension View {
    /// The footer's glass capsule, shared by the Source button, the pronunciation menu,
    /// and Resume following. Interactive glass supplies the hover and press response.
    func playerCapsule(accent: Color, hovering: Bool, focused: Bool) -> some View {
        font(.system(size: 12, weight: .medium))
            .foregroundStyle(hovering || focused ? .white : .white.opacity(0.8))
            .padding(.horizontal, 13)
            .padding(.vertical, 8)
            .glassEffect(.regular.interactive(), in: Capsule())
            .overlay(Capsule().strokeBorder(focused ? accent : .clear, lineWidth: 2))
            .contentShape(Capsule())
    }
}
