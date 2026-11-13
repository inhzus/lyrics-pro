import SwiftUI

// The Command Line Tools toolchain lacks the State macro plugin; see AGENTS.md.
private typealias PendingClearStorage = State<DataTarget?>

/// The app's Settings window (⌘,). Display settings apply immediately and are
/// stored in UserDefaults; none of them change lookups, caches, or Music.
struct SettingsView: View {
    @ObservedObject var connection: MusicConnection
    @AppStorage(ChineseScript.preferenceKey) private var script = ChineseScript.original
    @AppStorage(LyricTextScale.preferenceKey) private var textScale = LyricTextScale.standard
    @AppStorage(WindowSettings.keepOnTopKey) private var keepOnTop = false
    @AppStorage(LyricTiming.preferenceKey) private var timingDelay = LyricTiming.setting.standard
    @PendingClearStorage private var pendingClear: DataTarget?

    var body: some View {
        Form {
            Section("Lyrics") {
                Picker(selection: $script) {
                    ForEach(ChineseScript.allCases) { option in
                        Text(option.label).tag(option)
                    }
                } label: {
                    Text("Chinese text")
                    Text("Converts displayed lyrics only. Pronunciation, song titles, and lyric lookup are unchanged.")
                }
                sliderRow("Text size", subtitle: "Bigger ⌘=, Smaller ⌘−, Actual Size ⌘0",
                          value: Binding(get: { LyricTextScale.clamped(textScale) },
                                         set: { textScale = LyricTextScale.clamped($0) }),
                          range: LyricTextScale.range,
                          low: Text("A").font(.system(size: 10)), high: Text("A").font(.system(size: 16)),
                          valueText: LyricTextScale.label(textScale),
                          isStandard: LyricTextScale.clamped(textScale) == LyricTextScale.standard,
                          reset: { textScale = LyricTextScale.standard })
                sliderRow("Timing", subtitle: "Moves the highlight for lyrics that drift. Music is not changed.",
                          value: Binding(get: { LyricTiming.setting.clamped(timingDelay) },
                                         set: { timingDelay = LyricTiming.setting.clamped($0) }),
                          range: LyricTiming.setting.range,
                          low: Text("−3 s").font(.caption), high: Text("+3 s").font(.caption),
                          valueText: LyricTiming.label(timingDelay),
                          isStandard: LyricTiming.setting.clamped(timingDelay) == LyricTiming.setting.standard,
                          reset: { timingDelay = LyricTiming.setting.standard })
            }
            Section("Pronunciation") {
                // Same setting as the footer menu's Global Default; both go through the connection.
                Picker(selection: Binding(get: { connection.language }, set: connection.selectLanguage)) {
                    ForEach(PronunciationLanguage.choices, id: \.self) { option in
                        Text(option.label).tag(option)
                    }
                } label: {
                    Text("Default pronunciation")
                    Text("For songs without their own choice. Proofread lyrics can supply their own spelling.")
                }
            }
            Section("Window") {
                Toggle(isOn: $keepOnTop) {
                    Text("Keep window on top")
                    Text("Float the player above other apps while you sing along.")
                }
            }
            Section {
                dataRow(.lyricsCache, title: "Lyrics cache", detail: cacheDetail)
                dataRow(.recordingChoices, title: "Saved recording choices",
                        detail: connection.dataStats.map { count($0.recordingChoices, "song") })
                dataRow(.songLanguages, title: "Song pronunciation choices",
                        detail: connection.dataStats.map { count($0.songLanguages, "song") })
                if let message = connection.dataStats?.message, !message.isEmpty {
                    Text(message).font(.caption).foregroundStyle(.secondary)
                }
            } header: {
                Text("Data")
            } footer: {
                Text("Clearing never removes the lyrics on screen; it affects later lookups.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        .formStyle(.grouped)
        .task { connection.requestDataStats() }
        .confirmationDialog(pendingClear.map(confirmationTitle) ?? "", isPresented: Binding(
            get: { pendingClear != nil }, set: { if !$0 { pendingClear = nil } }), titleVisibility: .visible) {
            Button("Clear", role: .destructive) {
                if let target = pendingClear { connection.clearData([target]) }
                pendingClear = nil
            }
        } message: {
            Text(pendingClear == .lyricsCache ? "Lyrics will be downloaded again when needed."
                                              : "This can’t be undone.")
        }
        .frame(width: 540)
        .fixedSize(horizontal: false, vertical: true)
    }

    /// One layout for every slider so tracks, values, and Reset buttons line up. Sliders
    /// have no `step:` (tick marks change the knob's shape); bindings snap instead.
    private func sliderRow(_ title: String, subtitle: String, value: Binding<Double>, range: ClosedRange<Double>,
                           low: Text, high: Text, valueText: String, isStandard: Bool,
                           reset: @escaping () -> Void) -> some View {
        LabeledContent {
            HStack(spacing: 10) {
                Slider(value: value, in: range) {
                    Text(title)
                } minimumValueLabel: {
                    low.frame(width: 30, alignment: .trailing)
                } maximumValueLabel: {
                    high.frame(width: 30, alignment: .leading)
                }
                .labelsHidden()
                .frame(width: 230)
                Text(valueText)
                    .monospacedDigit()
                    .foregroundStyle(.secondary)
                    .frame(width: 92, alignment: .trailing)
                Button("Reset", action: reset)
                    .controlSize(.small)
                    .disabled(isStandard)
            }
        } label: {
            Text(title)
            Text(subtitle)
        }
    }

    private var cacheDetail: String? {
        guard let stats = connection.dataStats else { return nil }
        guard let entries = stats.lyricsEntries, let bytes = stats.lyricsBytes else { return "Unavailable" }
        if entries == 0 { return "Empty" }
        return "\(count(entries, "song")) · \(ByteCountFormatter.string(fromByteCount: Int64(bytes), countStyle: .file))"
    }

    /// Nothing to clear, or counts not known yet.
    private func isEmpty(_ target: DataTarget) -> Bool {
        guard let stats = connection.dataStats else { return true }
        switch target {
        case .lyricsCache: return stats.lyricsEntries == 0
        case .recordingChoices: return stats.recordingChoices == 0
        case .songLanguages: return stats.songLanguages == 0
        }
    }

    private func count(_ value: Int, _ noun: String) -> String { "\(value) \(noun)\(value == 1 ? "" : "s")" }

    private func confirmationTitle(_ target: DataTarget) -> String {
        switch target {
        case .lyricsCache: "Clear the lyrics cache?"
        case .recordingChoices: "Forget saved recording choices?"
        case .songLanguages: "Forget song pronunciation choices?"
        }
    }

    private func dataRow(_ target: DataTarget, title: String, detail: String?) -> some View {
        LabeledContent {
            HStack {
                if let detail {
                    Text(detail).monospacedDigit().foregroundStyle(.secondary)
                } else if connection.canManageData {
                    ProgressView().controlSize(.small)
                } else {
                    Text("Not connected").foregroundStyle(.secondary)
                }
                Button("Clear…") { pendingClear = target }
                    .disabled(!connection.canManageData || isEmpty(target))
            }
        } label: {
            Text(title)
        }
    }
}
