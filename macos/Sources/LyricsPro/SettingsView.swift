import SwiftUI

/// The app's Settings window (⌘,). Display settings apply immediately and are
/// stored in UserDefaults; none of them change lookups, caches, or Music.
struct SettingsView: View {
    @ObservedObject var connection: MusicConnection
    @AppStorage(ChineseScript.preferenceKey) private var script = ChineseScript.original
    @AppStorage(LyricTextScale.preferenceKey) private var textScale = LyricTextScale.standard

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
        }
        .formStyle(.grouped)
        .frame(width: 480)
        .fixedSize(horizontal: false, vertical: true)
    }
}
