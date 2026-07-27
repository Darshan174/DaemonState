import AppKit

@MainActor
final class StatusPanelController: NSWindowController {
    enum Tone {
        case neutral
        case success
        case failure
    }

    private let label = NSTextField(labelWithString: "")
    private let effectView = NSVisualEffectView()
    private var dismissWorkItem: DispatchWorkItem?

    init() {
        let panel = NSPanel(
            contentRect: NSRect(x: 0, y: 0, width: 260, height: 42),
            styleMask: [.borderless, .nonactivatingPanel],
            backing: .buffered,
            defer: false
        )
        panel.isOpaque = false
        panel.backgroundColor = .clear
        panel.hasShadow = true
        panel.level = .statusBar
        panel.hidesOnDeactivate = false
        panel.ignoresMouseEvents = true
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary]
        panel.isReleasedWhenClosed = false

        effectView.frame = panel.contentView?.bounds ?? .zero
        effectView.autoresizingMask = [.width, .height]
        effectView.material = .hudWindow
        effectView.blendingMode = .behindWindow
        effectView.state = .active
        effectView.wantsLayer = true
        effectView.layer?.cornerRadius = 13
        effectView.layer?.masksToBounds = true

        label.alignment = .center
        label.font = .systemFont(ofSize: 12.5, weight: .semibold)
        label.lineBreakMode = .byTruncatingTail
        label.frame = NSRect(x: 14, y: 10, width: 232, height: 20)
        label.autoresizingMask = [.width]
        effectView.addSubview(label)
        panel.contentView = effectView

        super.init(window: panel)
    }

    required init?(coder: NSCoder) {
        nil
    }

    func show(
        _ message: String,
        tone: Tone = .neutral,
        relativeTo anchor: NSWindow?,
        dismissAfter: TimeInterval?
    ) {
        dismissWorkItem?.cancel()
        label.stringValue = message
        switch tone {
        case .neutral:
            label.textColor = .labelColor
        case .success:
            label.textColor = NSColor(
                calibratedRed: 0.77,
                green: 0.96,
                blue: 0.42,
                alpha: 1
            )
        case .failure:
            label.textColor = NSColor(
                calibratedRed: 1,
                green: 0.48,
                blue: 0.46,
                alpha: 1
            )
        }

        resize(toFit: message)
        position(relativeTo: anchor)
        window?.orderFrontRegardless()

        guard let dismissAfter else { return }
        let workItem = DispatchWorkItem { [weak self] in
            self?.window?.orderOut(nil)
        }
        dismissWorkItem = workItem
        DispatchQueue.main.asyncAfter(
            deadline: .now() + dismissAfter,
            execute: workItem
        )
    }

    func hide() {
        dismissWorkItem?.cancel()
        dismissWorkItem = nil
        window?.orderOut(nil)
    }

    private func resize(toFit message: String) {
        let attributes: [NSAttributedString.Key: Any] = [.font: label.font as Any]
        let measured = (message as NSString).size(withAttributes: attributes).width
        let width = min(max(measured + 36, 170), 340)
        window?.setContentSize(NSSize(width: width, height: 42))
    }

    private func position(relativeTo anchor: NSWindow?) {
        guard let panel = window,
              let anchor,
              let screen = anchor.screen ?? NSScreen.main
        else {
            return
        }
        let visibleFrame = screen.visibleFrame
        let preferred = NSPoint(
            x: anchor.frame.midX - panel.frame.width / 2,
            y: anchor.frame.maxY + 7
        )
        panel.setFrameOrigin(
            NSPoint(
                x: min(
                    max(preferred.x, visibleFrame.minX + 8),
                    visibleFrame.maxX - panel.frame.width - 8
                ),
                y: min(
                    preferred.y,
                    visibleFrame.maxY - panel.frame.height - 8
                )
            )
        )
    }
}
