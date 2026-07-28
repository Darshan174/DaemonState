import AppKit

@MainActor
final class StatusPanelController: NSWindowController {
    private static let windowLevel = NSWindow.Level(
        rawValue: NSWindow.Level.screenSaver.rawValue + 1
    )

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
        // The feedback must stay above the floating control itself. Otherwise
        // scope changes and insert failures disappear behind full-screen apps.
        panel.level = Self.windowLevel
        panel.hidesOnDeactivate = false
        panel.canHide = false
        panel.worksWhenModal = true
        panel.ignoresMouseEvents = true
        panel.collectionBehavior = [
            .canJoinAllSpaces,
            .fullScreenAuxiliary,
            .ignoresCycle,
        ]
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
        label.lineBreakMode = .byWordWrapping
        label.maximumNumberOfLines = 2
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
        guard let panel = window else { return }
        // Reassert the cross-Space behavior for the same reason as the main
        // overlay: a long-lived panel can otherwise retain a stale Space.
        panel.level = Self.windowLevel
        panel.collectionBehavior = [
            .canJoinAllSpaces,
            .fullScreenAuxiliary,
            .ignoresCycle,
        ]
        panel.orderFrontRegardless()

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
        let textWidth = width - 28
        let bounds = (message as NSString).boundingRect(
            with: NSSize(
                width: textWidth,
                height: .greatestFiniteMagnitude
            ),
            options: [.usesLineFragmentOrigin, .usesFontLeading],
            attributes: attributes
        )
        let textHeight = min(max(ceil(bounds.height), 20), 36)
        let height = max(textHeight + 20, 42)
        window?.setContentSize(NSSize(width: width, height: height))
        label.frame = NSRect(
            x: 14,
            y: (height - textHeight) / 2,
            width: textWidth,
            height: textHeight
        )
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
