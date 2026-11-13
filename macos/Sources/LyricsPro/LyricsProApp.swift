import SwiftUI
import AppKit

@main
struct LyricsProApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var delegate
    @AppStorage(WindowSettings.keepOnTopKey) private var keepOnTop = false

    var body: some Scene {
        Window("Lyrics Pro", id: "main") {
            PlayerView(connection: delegate.connection)
                .frame(minWidth: 900, minHeight: 600)
                .preferredColorScheme(.dark)
                .task { delegate.connection.start() }
        }
        .defaultSize(width: 1280, height: 800)
        .windowStyle(.hiddenTitleBar)
        .windowResizability(.contentMinSize)
        .windowLevel(keepOnTop ? .floating : .normal)
        .commands {
            CommandGroup(replacing: .appInfo) {
                Button("About Lyrics Pro") { AboutPanel.show() }
            }
            CommandGroup(replacing: .newItem) {}
            CommandGroup(replacing: .help) {
                Button("Open Logs Folder") { AppLog.shared.openFolder() }
            }
            CommandGroup(after: .appSettings) {
                Button("Reconnect to Music") { delegate.connection.reconnect() }
                    .disabled(delegate.connection.restarting)
            }
            DisplayCommands()
            CommandMenu("Preview") {
                Button("Compact Window (900 × 600)") { resizeWindow(width: 900, height: 600) }
                    .keyboardShortcut("1", modifiers: [.command, .option])
                Button("Default Window (1280 × 800)") { resizeWindow(width: 1280, height: 800) }
                    .keyboardShortcut("2", modifiers: [.command, .option])
                Divider()
                Picker("Display", selection: Binding(get: { delegate.connection.demo }, set: { delegate.connection.demo = $0 })) {
                    Text("Live Music").tag(nil as DemoSong?)
                    ForEach(DemoSong.allCases) { sample in
                        Text("Demo · \(sample.rawValue)").tag(Optional(sample))
                    }
                }
            }
        }

        Settings {
            // Follows the system appearance; only the player is always dark.
            SettingsView(connection: delegate.connection)
        }
    }

    private func resizeWindow(width: CGFloat, height: CGFloat) {
        guard let window = NSApplication.shared.mainWindow,
              !window.styleMask.contains(.fullScreen) else { return }
        let oldFrame = window.frame
        let display = window.screen?.visibleFrame
        var frame = window.frameRect(forContentRect: NSRect(x: 0, y: 0, width: width, height: height))
        // Resize in place, preserving the top-left corner and current screen.
        // Avoid a separate resize/center sequence that can choose another monitor.
        frame.origin = NSPoint(x: oldFrame.minX, y: oldFrame.maxY - frame.height)
        if let display {
            frame.origin.x = max(display.minX, min(frame.minX, display.maxX - frame.width))
            frame.origin.y = max(display.minY, min(frame.minY, display.maxY - frame.height))
        }
        window.setFrame(frame, display: true)
    }
}

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    let connection = MusicConnection()

    func applicationDidFinishLaunching(_ notification: Notification) {
        AppLog.shared.write("app_start", "version=\(Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") ?? "unknown")")
    }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        Task {
            await connection.shutdown()
            AppLog.shared.write("app_stop")
            sender.reply(toApplicationShouldTerminate: true)
        }
        return .terminateLater
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
}

/// View menu items for lyric display settings shared with the Settings window.
struct DisplayCommands: Commands {
    @AppStorage(LyricTextScale.preferenceKey) private var textScale = LyricTextScale.standard
    @AppStorage(WindowSettings.keepOnTopKey) private var keepOnTop = false

    var body: some Commands {
        CommandGroup(before: .toolbar) {
            Toggle("Keep Window on Top", isOn: $keepOnTop)
            Divider()
            Button("Bigger") { textScale = LyricTextScale.bigger(textScale) }
                .keyboardShortcut("=", modifiers: .command)
                .disabled(LyricTextScale.clamped(textScale) >= LyricTextScale.range.upperBound)
            Button("Smaller") { textScale = LyricTextScale.smaller(textScale) }
                .keyboardShortcut("-", modifiers: .command)
                .disabled(LyricTextScale.clamped(textScale) <= LyricTextScale.range.lowerBound)
            Button("Actual Size") { textScale = LyricTextScale.standard }
                .keyboardShortcut("0", modifiers: .command)
                .disabled(LyricTextScale.clamped(textScale) == LyricTextScale.standard)
            Divider()
        }
    }
}
