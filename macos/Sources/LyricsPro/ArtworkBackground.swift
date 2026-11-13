import AppKit
import SwiftUI

private typealias BackgroundState<Value> = State<Value>

struct ArtworkBackground: View {
    let artwork: Data?
    let generation: Int
    let loading: Bool
    let connected: Bool
    let playing: Bool
    /// Owned by the player so its accent can follow the artwork too.
    @Binding var palette: ArtworkPalette
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @BackgroundState private var visible = false
    @BackgroundState private var clock = BackgroundMotionClock()

    private struct Input: Hashable {
        let artwork: Data?
        let generation: Int
        let loading: Bool
        let connected: Bool
    }
    private var input: Input {
        Input(artwork: artwork, generation: generation, loading: loading, connected: connected)
    }
    private var running: Bool { visible && !reduceMotion && connected && playing }

    var body: some View {
        TimelineView(.animation(minimumInterval: 1.0 / 30, paused: !running)) { _ in
            let time = reduceMotion ? 0 : clock.time(at: ProcessInfo.processInfo.systemUptime)
            ZStack {
                Color(red: 0.09, green: 0.11, blue: 0.14)
                PaletteField(palette: palette, time: time)
                    .id(palette)
                    .transition(.opacity)
                LinearGradient(colors: [.black.opacity(0.28), .black.opacity(0.48)],
                               startPoint: .topLeading, endPoint: .bottomTrailing)
            }
        }
        .background(WindowVisibilityObserver(visible: $visible))
        .onChange(of: running, initial: true) { _, value in
            clock.setRunning(value, at: ProcessInfo.processInfo.systemUptime)
        }
        .task(id: input) {
            let request = input
            let next: ArtworkPalette
            if !request.connected {
                next = .neutral
            } else if let data = request.artwork {
                guard let loaded = await ArtworkPalette.load(from: data) else { return }
                next = loaded
            } else if request.loading {
                return // Avoid a neutral flash while the next cover is being fetched.
            } else { next = .neutral }
            guard !Task.isCancelled else { return }
            withAnimation(reduceMotion ? nil : .easeInOut(duration: 1.2)) { palette = next }
        }
        .clipped()
        .ignoresSafeArea()
        .allowsHitTesting(false)
        .accessibilityHidden(true)
    }
}

private struct PaletteField: View {
    let palette: ArtworkPalette
    let time: Double
    private let centers: [CGPoint] = [CGPoint(x: 0.12, y: 0.15), CGPoint(x: 0.88, y: 0.18),
                                      CGPoint(x: 0.20, y: 0.88), CGPoint(x: 0.83, y: 0.82)]
    var body: some View {
        GeometryReader { geometry in
            ZStack {
                let first = palette.colors[0]
                Color(red: first.red * 0.65, green: first.green * 0.65, blue: first.blue * 0.65)
                ForEach(0..<4) { index in
                    let color = palette.colors[index]
                    let phase = time * 2 * .pi / Double(30 + index * 7) + Double(index) * 1.7
                    let center = UnitPoint(x: centers[index].x + sin(phase) * 0.09,
                                           y: centers[index].y + cos(phase * 0.87) * 0.07)
                    RadialGradient(stops: [
                        .init(color: Color(red: color.red, green: color.green, blue: color.blue), location: 0),
                        .init(color: Color(red: color.red, green: color.green, blue: color.blue).opacity(0.65), location: 0.4),
                        .init(color: Color(red: color.red, green: color.green, blue: color.blue).opacity(0), location: 1)
                    ], center: center, startRadius: 0,
                       endRadius: max(geometry.size.width, geometry.size.height) * 0.75)
                }
            }
        }
    }
}

/// Observe the actual player window, including occlusion, without treating loss of focus as hidden.
private struct WindowVisibilityObserver: NSViewRepresentable {
    @Binding var visible: Bool
    func makeNSView(context: Context) -> VisibilityView {
        let view = VisibilityView()
        view.changed = { value in
            Task { @MainActor in if visible != value { visible = value } }
        }
        return view
    }
    func updateNSView(_ view: VisibilityView, context: Context) {}
    static func dismantleNSView(_ view: VisibilityView, coordinator: ()) { view.stop() }

    final class VisibilityView: NSView {
        var changed: ((Bool) -> Void)?
        private var observers: [NSObjectProtocol] = []
        override func viewDidMoveToWindow() {
            super.viewDidMoveToWindow()
            stop()
            guard let window else { changed?(false); return }
            for name in [NSWindow.didChangeOcclusionStateNotification, NSWindow.didMiniaturizeNotification,
                         NSWindow.didDeminiaturizeNotification, NSWindow.willCloseNotification] {
                observers.append(NotificationCenter.default.addObserver(forName: name, object: window, queue: .main) { [weak self] _ in
                    Task { @MainActor in self?.refresh() }
                })
            }
            for name in [NSApplication.didHideNotification, NSApplication.didUnhideNotification] {
                observers.append(NotificationCenter.default.addObserver(forName: name, object: nil, queue: .main) { [weak self] _ in
                    Task { @MainActor in self?.refresh() }
                })
            }
            refresh()
        }
        private func refresh() {
            changed?(window.map { $0.isVisible && !$0.isMiniaturized && $0.occlusionState.contains(.visible) && !NSApp.isHidden } ?? false)
        }
        func stop() {
            observers.forEach { NotificationCenter.default.removeObserver($0) }
            observers.removeAll()
        }
    }
}
