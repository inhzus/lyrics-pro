import SwiftUI

private typealias HoverState = State<Bool>

struct PronunciationMenu: View {
    let language: PronunciationLanguage
    let accent: Color
    let select: @MainActor @Sendable (PronunciationLanguage) -> Void
    @HoverState private var hovering = false
    @FocusState private var focused: Bool

    var body: some View {
        Menu {
            Picker("Pronunciation", selection: Binding(get: { language }, set: select)) {
                ForEach(PronunciationLanguage.allCases, id: \.self) { option in
                    Text(option.label).tag(option)
                }
            }
            .pickerStyle(.inline)
        } label: {
            HStack(spacing: 7) {
                Image(systemName: "character.bubble")
                Text(language.shortLabel)
                Image(systemName: "chevron.down")
                    .font(.system(size: 9, weight: .semibold))
            }
            .font(.system(size: 12, weight: .medium))
            .foregroundStyle(hovering || focused ? .white : .white.opacity(0.8))
            .padding(.horizontal, 13)
            .padding(.vertical, 8)
            .background(.white.opacity(hovering ? 0.10 : 0.055), in: Capsule())
            .overlay(Capsule().strokeBorder(focused ? accent : .white.opacity(hovering ? 0.20 : 0.10), lineWidth: focused ? 2 : 1))
            .contentShape(Capsule())
        }
        .menuStyle(.button)
        .menuIndicator(.hidden)
        .buttonStyle(.plain)
        .fixedSize()
        .focused($focused)
        .onHover { hovering = $0 }
        .accessibilityLabel("Pronunciation: \(language.label)")
        .help("Auto guesses from the artist. Choose a language to override it.")
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
                .font(.system(size: 12, weight: .medium))
                .foregroundStyle(hovering || focused ? .white : .white.opacity(0.8))
                .padding(.horizontal, 13)
                .padding(.vertical, 8)
                .background(.white.opacity(configuration.isPressed ? 0.16 : (hovering ? 0.10 : 0.055)), in: Capsule())
                .overlay(Capsule().strokeBorder(focused ? accent : .white.opacity(hovering ? 0.20 : 0.10), lineWidth: focused ? 2 : 1))
                .contentShape(Capsule())
                .onHover { hovering = $0 }
        }
    }
}
