import SwiftUI

/// The app's Settings window (⌘,). Display settings apply immediately and are
/// stored in UserDefaults; none of them change lookups, caches, or Music.
struct SettingsView: View {
    @ObservedObject var connection: MusicConnection
    @AppStorage(ChineseScript.preferenceKey) private var script = ChineseScript.original

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
            }
        }
        .formStyle(.grouped)
        .frame(width: 480)
        .fixedSize(horizontal: false, vertical: true)
    }
}
