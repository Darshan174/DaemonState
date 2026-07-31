import AppKit

@MainActor
final class OverlayPanelController: NSWindowController {
    let logoControl: LogoControl
    let promptMenuButton: PromptMenuButton

    init(savedOrigin: NSPoint?) {
        logoControl = LogoControl(frame: NSRect(x: 8, y: 8, width: 56, height: 56))
        promptMenuButton = PromptMenuButton(
            frame: NSRect(x: 48, y: 0, width: 24, height: 24)
        )
        let rootView = NSView(frame: NSRect(x: 0, y: 0, width: 72, height: 72))
        rootView.wantsLayer = true
        rootView.layer?.backgroundColor = NSColor.clear.cgColor
        rootView.addSubview(logoControl)
        rootView.addSubview(promptMenuButton)

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
        // Keep the control above normal and full-screen application windows.
        // `.statusBar` can be left behind on the Desktop Space after a Space
        // transition even when AppKit still reports the panel as visible.
        panel.level = .screenSaver
        panel.hidesOnDeactivate = false
        panel.canHide = false
        panel.worksWhenModal = true
        panel.becomesKeyOnlyIfNeeded = true
        panel.collectionBehavior = [
            .canJoinAllSpaces,
            .fullScreenAuxiliary,
            .ignoresCycle,
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
        guard let panel = window else { return }
        // Reassert these attributes when runtime control turns the overlay
        // back on. macOS can otherwise retain the previous Space assignment
        // for a long-lived non-activating panel.
        panel.level = .screenSaver
        panel.collectionBehavior = [
            .canJoinAllSpaces,
            .fullScreenAuxiliary,
            .ignoresCycle,
        ]
        panel.orderFrontRegardless()
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

@MainActor
final class PromptMenuButton: NSButton {
    var onPress: (() -> Void)?

    var selectedPromptCount = 0 {
        didSet {
            let normalized = max(0, selectedPromptCount)
            if normalized != selectedPromptCount {
                selectedPromptCount = normalized
                return
            }
            guard selectedPromptCount != oldValue else { return }
            updateAccessibility()
            needsDisplay = true
        }
    }

    private var hovering = false
    private var trackingAreaReference: NSTrackingArea?

    override init(frame frameRect: NSRect) {
        super.init(frame: frameRect)
        title = ""
        isBordered = false
        focusRingType = .none
        target = self
        action = #selector(pressed)
        wantsLayer = true
        setAccessibilityRole(.popUpButton)
        updateAccessibility()
        toolTip = "Reusable prompts"
    }

    required init?(coder: NSCoder) {
        nil
    }

    override func acceptsFirstMouse(for event: NSEvent?) -> Bool {
        true
    }

    override func updateTrackingAreas() {
        super.updateTrackingAreas()
        if let trackingAreaReference {
            removeTrackingArea(trackingAreaReference)
        }
        let area = NSTrackingArea(
            rect: bounds,
            options: [.activeAlways, .mouseEnteredAndExited],
            owner: self,
            userInfo: nil
        )
        addTrackingArea(area)
        trackingAreaReference = area
    }

    override func mouseEntered(with event: NSEvent) {
        hovering = true
        needsDisplay = true
    }

    override func mouseExited(with event: NSEvent) {
        hovering = false
        needsDisplay = true
    }

    override func draw(_ dirtyRect: NSRect) {
        let selected = selectedPromptCount > 0
        let rect = bounds.insetBy(dx: 1.5, dy: 1.5)
        let background = NSBezierPath(roundedRect: rect, xRadius: 8, yRadius: 8)

        if selected {
            NSGraphicsContext.saveGraphicsState()
            let shadow = NSShadow()
            shadow.shadowColor = NSColor(
                calibratedRed: 0.70,
                green: 0.95,
                blue: 0.31,
                alpha: 0.62
            )
            shadow.shadowBlurRadius = 7
            shadow.shadowOffset = .zero
            shadow.set()
            NSColor(calibratedRed: 0.76, green: 1, blue: 0.36, alpha: 1).setFill()
            background.fill()
            NSGraphicsContext.restoreGraphicsState()
        } else {
            NSColor(calibratedWhite: hovering ? 0.12 : 0.04, alpha: 0.92).setFill()
            background.fill()
        }

        (selected
            ? NSColor(calibratedWhite: 0, alpha: 0.78)
            : NSColor(calibratedWhite: 1, alpha: hovering ? 0.9 : 0.65)
        ).setStroke()
        background.lineWidth = 1
        background.stroke()

        if selected {
            let value = selectedPromptCount > 9 ? "9+" : "\(selectedPromptCount)"
            let attributes: [NSAttributedString.Key: Any] = [
                .font: NSFont.systemFont(ofSize: selectedPromptCount > 9 ? 8 : 10, weight: .bold),
                .foregroundColor: NSColor.black,
            ]
            let size = value.size(withAttributes: attributes)
            value.draw(
                at: NSPoint(
                    x: bounds.midX - size.width / 2,
                    y: bounds.midY - size.height / 2
                ),
                withAttributes: attributes
            )
        } else {
            let chevron = NSBezierPath()
            chevron.move(to: NSPoint(x: bounds.midX - 3.5, y: bounds.midY - 1.5))
            chevron.line(to: NSPoint(x: bounds.midX, y: bounds.midY + 2))
            chevron.line(to: NSPoint(x: bounds.midX + 3.5, y: bounds.midY - 1.5))
            chevron.lineWidth = 1.6
            chevron.lineCapStyle = .round
            chevron.lineJoinStyle = .round
            NSColor.white.withAlphaComponent(hovering ? 0.95 : 0.72).setStroke()
            chevron.stroke()
        }
    }

    @objc private func pressed() {
        onPress?()
    }

    private func updateAccessibility() {
        setAccessibilityLabel("Reusable prompts")
        if selectedPromptCount == 0 {
            setAccessibilityValue("No prompts selected")
        } else {
            let noun = selectedPromptCount == 1 ? "prompt" : "prompts"
            setAccessibilityValue("\(selectedPromptCount) \(noun) selected")
        }
        setAccessibilityHelp(
            "Open the reusable prompt dropdown to save or select prompts."
        )
    }
}
