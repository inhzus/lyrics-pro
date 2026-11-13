import SwiftUI

private typealias PickerVisibility = State<Bool>
private typealias RowHover = State<Bool>

struct RecordingPicker: View {
    @ObservedObject var connection: MusicConnection
    let accent: Color
    @PickerVisibility private var showing = false
    @FocusState private var triggerFocused: Bool
    private var update: RecordingUpdate? { connection.state.recordings }

    var body: some View {
        Button {
            showing.toggle()
            if showing { connection.listRecordings() }
        } label: {
            Image(systemName: "list.bullet")
            Text("Source")
            Image(systemName: "chevron.down").font(.system(size: 9, weight: .semibold))
        }
        .buttonStyle(PlayerCapsuleStyle(accent: accent))
        .fixedSize()
        .disabled(connection.state.phase != .live)
        .focused($triggerFocused)
        .help("Lyrics source: choose proofread lyrics or an online recording")
        .background {
            UpwardRecordingPopover(isPresented: $showing, update: update) { availableHeight in
                RecordingOptionsView(connection: connection, accent: accent, availableHeight: availableHeight,
                                     dismiss: { showing = false })
            }
        }
        .onChange(of: showing) { _, value in if !value { triggerFocused = true } }
        .onChange(of: connection.state.generation) { _, _ in showing = false }
    }
}

private struct RecordingOptionsView: View {
    @ObservedObject var connection: MusicConnection
    let accent: Color
    let availableHeight: CGFloat
    let dismiss: () -> Void
    @FocusState private var focusedRow: String?
    private var update: RecordingUpdate? { connection.state.recordings }
    private var candidates: [RecordingCandidate] { update?.candidates ?? [] }
    private var hasUnlistedCurrent: Bool {
        guard let update, !update.source.isEmpty else { return false }
        return !candidates.contains { $0.id == update.selectedID }
    }
    private var rowCount: Int { candidates.count + (hasUnlistedCurrent ? 1 : 0) }
    private var searching: Bool { update?.status.isSearching ?? true }

    var body: some View {
        let hasMessage = !(update?.message.isEmpty ?? true)
        // Fixed rows above the list, so at most five candidates fit before scrolling.
        let headerHeight: CGFloat = 126 + (update?.switching == true ? 24 : 0)
            + (searching ? 24 : 0) + (hasMessage ? 50 : 0) + (update?.status == .error ? 26 : 0)
        return VStack(alignment: .leading, spacing: 8) {
            Text("Lyrics source").font(.system(size: 13, weight: .semibold))
            Button { connection.forgetRecording() } label: {
                HStack {
                    Image(systemName: update?.manual == true ? "circle" : "checkmark.circle.fill")
                        .foregroundStyle(accent)
                    VStack(alignment: .leading, spacing: 3) {
                        Text("Automatic").fontWeight(.medium)
                        Text("Use the best available match").font(.system(size: 11)).foregroundStyle(.secondary)
                    }
                    Spacer()
                }.padding(6)
            }
            .buttonStyle(RecordingRowStyle())
            .focusable()
            .focusEffectDisabled()
            .focused($focusedRow, equals: "automatic")
            Divider()
            if update?.switching == true {
                HStack(spacing: 7) {
                    ProgressView().controlSize(.small)
                    Text("Loading lyrics source…")
                }.font(.system(size: 12)).foregroundStyle(.secondary)
            }
            if searching {
                HStack(spacing: 7) {
                    ProgressView().controlSize(.small)
                    Text("Finding alternatives…")
                }.font(.system(size: 12)).foregroundStyle(.secondary)
            }
            if let message = update?.message, !message.isEmpty {
                Text(message).font(.system(size: 12)).foregroundStyle(.secondary)
                    .lineLimit(3)
                    .help(message)
                if update?.status == .error {
                    Button("Retry alternatives") { connection.listRecordings() }
                }
            }
            if rowCount > 0 {
                ScrollViewReader { proxy in
                    ScrollView {
                        LazyVStack(spacing: 0) {
                            if hasUnlistedCurrent {
                                HStack(spacing: 10) {
                                    Image(systemName: "checkmark").foregroundStyle(accent).frame(width: 16)
                                    VStack(alignment: .leading, spacing: 4) {
                                        Text("Current source").fontWeight(.medium)
                                        Text("\(update?.sourceName ?? "") · \(update?.manual == true ? "Saved choice" : "Automatic")")
                                            .font(.system(size: 12)).foregroundStyle(.secondary)
                                    }
                                    Spacer()
                                }.padding(.horizontal, 8).frame(height: 64)
                            }
                            ForEach(candidates) { candidate in
                                Button { choose(candidate) } label: { row(candidate) }
                                    .buttonStyle(RecordingRowStyle())
                                    .focusable()
                                    .focusEffectDisabled()
                                    .focused($focusedRow, equals: candidate.id)
                                    .id(candidate.id)
                                    .help(Self.tooltip(candidate))
                                    .accessibilityLabel(Self.spokenLabel(candidate))
                                    .accessibilityAddTraits(update?.selectedID == candidate.id ? .isSelected : [])
                            }
                        }
                    }
                    .frame(height: min(CGFloat(min(5, rowCount)) * 64, max(0, availableHeight - headerHeight)))
                    .onChange(of: focusedRow) { _, id in
                        if let id, id != "automatic" { proxy.scrollTo(id) }
                    }
                }
            } else if update?.status == .ready {
                Text("No alternatives with the same title and a duration within two seconds.")
                    .font(.system(size: 12)).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Text("Manual choices are remembered for this song.")
                .font(.system(size: 11)).foregroundStyle(.secondary)
        }
        .foregroundStyle(Color.primary)
        .padding(10)
        .frame(width: 300)
        .task {
            await Task.yield()
            focusedRow = "automatic"
        }
        .onMoveCommand { direction in
            let ids = ["automatic"] + candidates.map(\.id)
            let current = ids.firstIndex(of: focusedRow ?? "automatic") ?? 0
            if direction == .down { focusedRow = ids[min(ids.count - 1, current + 1)] }
            if direction == .up { focusedRow = ids[max(0, current - 1)] }
        }
        .onKeyPress(.return) {
            if focusedRow == "automatic" { connection.forgetRecording() }
            else if let candidate = candidates.first(where: { $0.id == focusedRow }) { choose(candidate) }
            return .handled
        }
        .onExitCommand { dismiss() }
    }

    private static func details(_ candidate: RecordingCandidate) -> [String] {
        [candidate.album, MusicSnapshot.timeLabel(candidate.duration), candidate.sourceName]
    }

    private static func tooltip(_ candidate: RecordingCandidate) -> String {
        "\(candidate.title) — \(candidate.artists.joined(separator: " & "))\n" + details(candidate).joined(separator: " · ")
    }

    private static func spokenLabel(_ candidate: RecordingCandidate) -> String {
        ([candidate.title, candidate.artists.joined(separator: " & ")] + details(candidate)).joined(separator: ", ")
    }

    private func choose(_ candidate: RecordingCandidate) {
        connection.chooseRecording(candidate, generation: connection.state.generation,
                                   requestID: connection.state.lyricRequestID)
    }

    private func row(_ candidate: RecordingCandidate) -> some View {
        HStack(spacing: 8) {
            Image(systemName: update?.selectedID == candidate.id ? "checkmark" : "circle")
                .foregroundStyle(update?.selectedID == candidate.id ? accent : .clear)
                .frame(width: 12)
            VStack(alignment: .leading, spacing: 3) {
                HStack {
                    Text(candidate.title).font(.system(size: 12, weight: .semibold)).lineLimit(1)
                    Spacer(minLength: 8)
                    Text(MusicSnapshot.timeLabel(candidate.duration)).font(.system(size: 11)).monospacedDigit()
                }
                Text(candidate.artists.joined(separator: " & ")).font(.system(size: 11)).lineLimit(1)
                Text("\(candidate.album.isEmpty ? "Unknown album" : candidate.album) · \(candidate.sourceName)")
                    .font(.system(size: 11)).foregroundStyle(.secondary).lineLimit(1)
            }
        }
        .padding(.horizontal, 8)
        .frame(height: 64)
        .frame(maxWidth: .infinity, alignment: .leading)
        .contentShape(Rectangle())
    }
}

private struct RecordingRowStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View { Row(configuration: configuration) }
    private struct Row: View {
        let configuration: Configuration
        @RowHover private var hovering = false
        @Environment(\.isFocused) private var focused
        var body: some View {
            configuration.label
                .background(.primary.opacity(configuration.isPressed ? 0.12 : (hovering || focused ? 0.07 : 0)),
                            in: RoundedRectangle(cornerRadius: 8))
                .onHover { hovering = $0 }
        }
    }
}
