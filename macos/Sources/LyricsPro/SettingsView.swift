import SwiftUI

/// The app's Settings window (⌘,). Display settings apply immediately and are
/// stored in UserDefaults; none of them change lookups, caches, or Music.
struct SettingsView: View {
    @ObservedObject var connection: MusicConnection
    @AppStorage(ChineseScript.preferenceKey) private var script = ChineseScript.original
    @AppStorage(LyricTextScale.preferenceKey) private var textScale = LyricTextScale.standard
    @AppStorage(WindowSettings.keepOnTopKey) private var keepOnTop = false

    var body: some View {
        Form {
            Section("Lyrics") {
                Picker("Chinese text", selection: $script) {
                    ForEach(ChineseScript.allCases) { option in
                        Text(option.label).tag(option)
                    }
                }
                Text("Converts displayed lyrics only. Pronunciation, song titles, and lyric lookup are unchanged.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                LabeledContent("Text size") {
                    HStack {
                        Slider(value: Binding(get: { LyricTextScale.clamped(textScale) },
                                              set: { textScale = LyricTextScale.clamped($0) }),
                               in: LyricTextScale.range, step: LyricTextScale.step) {
                            Text("Text size")
                        } minimumValueLabel: {
                            Image(systemName: "textformat.size.smaller")
                        } maximumValueLabel: {
                            Image(systemName: "textformat.size.larger")
                        }
                        .labelsHidden()
                        Text(LyricTextScale.label(textScale))
                            .monospacedDigit()
                            .frame(width: 48, alignment: .trailing)
                    }
                }
                .help("Bigger ⌘=, Smaller ⌘−, Actual Size ⌘0")
            }
            Section("Pronunciation") {
                // Same setting as the footer menu's Global Default; both go through the connection.
                Picker("Default pronunciation", selection: Binding(get: { connection.language },
                                                                   set: connection.selectLanguage)) {
                    ForEach(PronunciationLanguage.choices, id: \.self) { option in
                        Text(option.label).tag(option)
                    }
                }
                Text("Used for songs without their own choice. Proofread lyrics can supply their own spelling.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            Section("Window") {
                Toggle("Keep window on top", isOn: $keepOnTop)
            }
        }
        .formStyle(.grouped)
        .frame(width: 480)
        .fixedSize(horizontal: false, vertical: true)
    }
}
