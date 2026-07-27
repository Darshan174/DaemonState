import AppKit

@MainActor
final class OverlayPanelController: NSWindowController {
    let logoControl: LogoControl

    init(savedOrigin: NSPoint?) {
        logoControl = LogoControl(frame: NSRect(x: 8, y: 8, width: 56, height: 56))
        let rootView = NSView(frame: NSRect(x: 0, y: 0, width: 72, height: 72))
        rootView.wantsLayer = true
        rootView.layer?.backgroundColor = NSColor.clear.cgColor
        rootView.addSubview(logoControl)

        let panel = NSPanel(
            contentRect: rootView.bounds,
            styleMask: [.borderless, .nonactivatingPanel],
            backing: .buffered,
            defer: false
        )
        panel.contentView = rootView
        panel.isOpaque = false
        panel.backgroundColor = .clear
        panel.hasShadow = false
        panel.level = .statusBar
        panel.hidesOnDeactivate = false
        panel.becomesKeyOnlyIfNeeded = true
        panel.collectionBehavior = [
            .canJoinAllSpaces,
            .fullScreenAuxiliary,
            .stationary,
        ]
        panel.isReleasedWhenClosed = false
        panel.setAccessibilityTitle("DaemonState")

        super.init(window: panel)
        if let savedOrigin {
            panel.setFrameOrigin(constrainedOrigin(savedOrigin, for: panel))
        } else {
            placeAtBottomCenter(panel)
        }
    }

    required init?(coder: NSCoder) {
        nil
    }

    func show() {
        window?.orderFrontRegardless()
    }

    func hide() {
        window?.orderOut(nil)
    }

    private func placeAtBottomCenter(_ panel: NSPanel) {
        guard let frame = NSScreen.main?.visibleFrame else { return }
        let origin = NSPoint(
            x: frame.midX - panel.frame.width / 2,
            y: frame.minY + 28
        )
        panel.setFrameOrigin(origin)
    }

    private func constrainedOrigin(_ origin: NSPoint, for panel: NSPanel) -> NSPoint {
        let screens = NSScreen.screens
        let matchingScreen = screens.first { screen in
            screen.visibleFrame.insetBy(dx: -40, dy: -40).contains(origin)
        } ?? NSScreen.main
        guard let visibleFrame = matchingScreen?.visibleFrame else {
            return origin
        }
        return NSPoint(
            x: min(
                max(origin.x, visibleFrame.minX),
                visibleFrame.maxX - panel.frame.width
            ),
            y: min(
                max(origin.y, visibleFrame.minY),
                visibleFrame.maxY - panel.frame.height
            )
        )
    }
}
