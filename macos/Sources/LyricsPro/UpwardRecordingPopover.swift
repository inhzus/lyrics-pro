import AppKit
import SwiftUI

/// Re-anchor after asynchronous content changes instead of allowing an existing
/// popover to grow toward the bottom of the display.
struct UpwardRecordingPopover<Content: View>: NSViewRepresentable {
    @Binding var isPresented: Bool
    let update: RecordingUpdate?
    @ViewBuilder let content: (CGFloat) -> Content

    func makeCoordinator() -> Coordinator { Coordinator(parent: self) }

    func makeNSView(context: Context) -> AnchorView {
        let view = AnchorView()
        view.attached = { [weak coordinator = context.coordinator] in coordinator?.schedule() }
        context.coordinator.anchor = view
        return view
    }

    func updateNSView(_ view: AnchorView, context: Context) {
        context.coordinator.parent = self
        context.coordinator.schedule()
    }

    static func dismantleNSView(_ view: AnchorView, coordinator: Coordinator) {
        coordinator.invalidate()
    }

    final class AnchorView: NSView {
        var attached: (() -> Void)?
        override func viewDidMoveToWindow() {
            super.viewDidMoveToWindow()
            attached?()
        }
    }

    @MainActor final class Coordinator: NSObject, NSPopoverDelegate {
        var parent: UpwardRecordingPopover
        weak var anchor: AnchorView?
        private let popover = NSPopover()
        private var hosting: NSHostingController<Content>?
        private var lastUpdate: RecordingUpdate?
        private var lastAnchor: NSRect?
        private var lastAvailableHeight: CGFloat?
        private var scheduled = false
        private var invalidated = false
        private var observers: [NSObjectProtocol] = []
        private weak var observedWindow: NSWindow?

        init(parent: UpwardRecordingPopover) {
            self.parent = parent
            super.init()
            popover.behavior = .transient
            popover.animates = false
            popover.delegate = self
        }

        func schedule() {
            guard !scheduled, !invalidated else { return }
            scheduled = true
            Task { @MainActor [weak self] in
                await Task.yield()
                guard let self, !self.invalidated else { return }
                self.scheduled = false
                self.present()
            }
        }

        private func present() {
            guard parent.isPresented else {
                popover.close()
                return
            }
            guard let anchor, let window = anchor.window, let screen = window.screen,
                  !anchor.bounds.isEmpty else { return }
            if observedWindow !== window {
                observers.forEach { NotificationCenter.default.removeObserver($0) }
                observedWindow = window
                observers = [NSWindow.didMoveNotification, NSWindow.didResizeNotification,
                             NSWindow.didChangeScreenNotification].map { name in
                    NotificationCenter.default.addObserver(forName: name, object: window, queue: .main) { [weak self] _ in
                        Task { @MainActor in self?.schedule() }
                    }
                }
            }
            let rect = window.convertToScreen(anchor.convert(anchor.bounds, to: nil))
            let available = RecordingPopoverGeometry.availableHeight(anchor: rect, screen: screen.visibleFrame)
            let opening = !popover.isShown
            guard opening || lastUpdate != parent.update || lastAnchor != rect || lastAvailableHeight != available else { return }
            lastUpdate = parent.update
            lastAnchor = rect
            lastAvailableHeight = available
            let root = parent.content(available)
            if let hosting { hosting.rootView = root }
            else {
                let controller = NSHostingController(rootView: root)
                controller.sizingOptions = [.preferredContentSize, .minSize, .maxSize]
                hosting = controller
                popover.contentViewController = controller
            }
            guard let hosting else { return }
            hosting.view.layoutSubtreeIfNeeded()
            let fitting = hosting.view.fittingSize
            popover.contentSize = NSSize(width: 300, height: min(available, fitting.height))
            // AppKit's maxY edge is above the button in screen coordinates.
            // Calling show again also updates the anchor for an already-open popup.
            popover.show(relativeTo: anchor.bounds, of: anchor, preferredEdge: .maxY)
            if opening { hosting.view.window?.makeKey() }
        }

        func popoverDidClose(_ notification: Notification) {
            if !invalidated { parent.isPresented = false }
        }

        func invalidate() {
            invalidated = true
            observers.forEach { NotificationCenter.default.removeObserver($0) }
            observers.removeAll()
            popover.close()
        }
    }
}

enum RecordingPopoverGeometry {
    static func availableHeight(anchor: CGRect, screen: CGRect) -> CGFloat {
        max(0, screen.maxY - anchor.maxY - 24)
    }
}
