import AppKit

private enum SessionFanDirection {
    case above
    case below
}

private struct SessionFanGeometry {
    let size: NSSize
    let hubOffset: NSPoint
    let buttonFrames: [NSRect]
}

@MainActor
final class OverlayPanelController: NSWindowController {
    let logoControl: LogoControl
    let promptMenuButton: PromptMenuButton
    let rootView: OverlayTrackingView

    var onSelectSession: ((OverlaySelectedSession) -> Void)?
    private(set) var sessionButtons: [SessionFanButton] = []
    private(set) var selectedSessions: [OverlaySelectedSession] = []
    private(set) var isExpanded = false

    private let collapsedSize = NSSize(width: 72, height: 72)
    private let fanRevealStagger: TimeInterval = 0.075
    private var hubOffset = NSPoint.zero
    private var focusedSessionIdentities = Set<String>()
    private var collapseWorkItem: DispatchWorkItem?

    init(savedOrigin: NSPoint?) {
        logoControl = LogoControl(frame: NSRect(x: 8, y: 8, width: 56, height: 56))
        promptMenuButton = PromptMenuButton(
            frame: NSRect(x: 48, y: 0, width: 24, height: 24)
        )
        rootView = OverlayTrackingView(
            frame: NSRect(
                origin: .zero,
                size: NSSize(width: 72, height: 72)
            )
        )
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
        rootView.onHoverChanged = { [weak self] hovering in
            if hovering {
                self?.expand()
            } else {
                self?.scheduleCollapse()
            }
        }
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
        collapse()
        window?.orderOut(nil)
    }

    func setSelectedSessions(_ values: [OverlaySelectedSession]) {
        let normalized = normalizedOverlaySelectedSessions(values)
        guard normalized != selectedSessions else { return }
        collapse()
        selectedSessions = normalized
        rebuildSessionButtons()
    }

    func expand() {
        setExpanded(true)
    }

    func collapse() {
        setExpanded(false)
    }

    func collapsedOrigin(forPanelOrigin origin: NSPoint) -> NSPoint {
        NSPoint(
            x: origin.x + hubOffset.x,
            y: origin.y + hubOffset.y
        )
    }

    func setExpanded(_ requestedExpansion: Bool) {
        collapseWorkItem?.cancel()
        collapseWorkItem = nil
        let shouldExpand = requestedExpansion && !selectedSessions.isEmpty
        guard shouldExpand != isExpanded, let panel = window else { return }

        let hubOrigin = collapsedOrigin(forPanelOrigin: panel.frame.origin)
        if shouldExpand {
            let visibleFrame = visibleFrame(containing: hubOrigin, panel: panel)
            let above = sessionFanGeometry(direction: .above)
            let below = sessionFanGeometry(direction: .below)
            let geometry = preferredGeometry(
                above: above,
                below: below,
                hubOrigin: hubOrigin,
                visibleFrame: visibleFrame
            )
            hubOffset = geometry.hubOffset
            let proposedOrigin = NSPoint(
                x: hubOrigin.x - hubOffset.x,
                y: hubOrigin.y - hubOffset.y
            )
            let origin = constrainedOrigin(
                proposedOrigin,
                size: geometry.size,
                visibleFrame: visibleFrame
            )
            panel.setFrame(
                NSRect(origin: origin, size: geometry.size),
                display: true
            )
            rootView.frame = NSRect(origin: .zero, size: geometry.size)
            isExpanded = true
            layoutControls(
                buttonFrames: geometry.buttonFrames,
                revealSessions: true
            )
        } else {
            for button in sessionButtons {
                button.stopRevealAnimation()
                button.isHidden = true
            }
            hubOffset = .zero
            let origin = constrainedOrigin(
                hubOrigin,
                size: collapsedSize,
                visibleFrame: visibleFrame(containing: hubOrigin, panel: panel)
            )
            panel.setFrame(
                NSRect(origin: origin, size: collapsedSize),
                display: true
            )
            rootView.frame = NSRect(origin: .zero, size: collapsedSize)
            isExpanded = false
            layoutControls()
        }
        rootView.updateTrackingAreas()
    }

    private func placeAtBottomCenter(_ panel: NSPanel) {
        guard let frame = NSScreen.main?.visibleFrame else { return }
        let origin = NSPoint(
            x: frame.midX - panel.frame.width / 2,
            y: frame.minY + 28
        )
        panel.setFrameOrigin(origin)
    }

    private func rebuildSessionButtons() {
        for button in sessionButtons {
            button.removeFromSuperview()
        }
        focusedSessionIdentities.removeAll()
        sessionButtons = selectedSessions.map { session in
            let button = SessionFanButton(session: session, frame: .zero)
            button.onPress = { [weak self] selected in
                self?.onSelectSession?(selected)
            }
            button.onFocusChanged = { [weak self] focused in
                self?.sessionButtonFocusChanged(session, focused: focused)
            }
            rootView.addSubview(button, positioned: .below, relativeTo: logoControl)
            return button
        }
        for index in sessionButtons.indices {
            sessionButtons[index].nextKeyView = sessionButtons[
                (index + 1) % sessionButtons.count
            ]
        }
        layoutControls()
    }

    private func layoutControls(
        buttonFrames: [NSRect]? = nil,
        revealSessions: Bool = false
    ) {
        logoControl.frame = NSRect(
            x: hubOffset.x + 8,
            y: hubOffset.y + 8,
            width: 56,
            height: 56
        )
        promptMenuButton.frame = NSRect(
            x: hubOffset.x + 48,
            y: hubOffset.y,
            width: 24,
            height: 24
        )
        for (index, button) in sessionButtons.enumerated() {
            guard let buttonFrames,
                  buttonFrames.indices.contains(index),
                  isExpanded else {
                button.stopRevealAnimation()
                button.frame = .zero
                button.isHidden = true
                continue
            }
            let frame = buttonFrames[index]
            button.frame = frame
            button.isHidden = false
            if revealSessions {
                button.animateReveal(
                    from: NSPoint(
                        x: hubOffset.x + collapsedSize.width / 2,
                        y: hubOffset.y + collapsedSize.height / 2
                    ),
                    delay: TimeInterval(index) * fanRevealStagger,
                    animated: !NSWorkspace.shared.accessibilityDisplayShouldReduceMotion
                )
            }
        }
    }

    private func sessionFanGeometry(
        direction: SessionFanDirection
    ) -> SessionFanGeometry {
        let verticalSign: CGFloat = direction == .above ? 1 : -1
        let centerOffsets = [
            NSPoint(x: -72, y: 38 * verticalSign),
            NSPoint(x: 72, y: 38 * verticalSign),
            NSPoint(x: 0, y: 84 * verticalSign),
        ]
        let hubRect = NSRect(origin: .zero, size: collapsedSize)
        let relativeFrames = centerOffsets
            .prefix(sessionButtons.count)
            .map { offset in
                NSRect(
                    x: collapsedSize.width / 2 + offset.x - 24,
                    y: collapsedSize.height / 2 + offset.y - 24,
                    width: 48,
                    height: 48
                )
            }
        var bounds = relativeFrames.reduce(hubRect) { partial, frame in
            partial.union(frame)
        }
        bounds = bounds.insetBy(dx: -4, dy: -4)
        let offset = NSPoint(x: -bounds.minX, y: -bounds.minY)
        return SessionFanGeometry(
            size: bounds.size,
            hubOffset: offset,
            buttonFrames: relativeFrames.map { frame in
                frame.offsetBy(dx: offset.x, dy: offset.y)
            }
        )
    }

    private func preferredGeometry(
        above: SessionFanGeometry,
        below: SessionFanGeometry,
        hubOrigin: NSPoint,
        visibleFrame: NSRect?
    ) -> SessionFanGeometry {
        guard let visibleFrame else { return above }
        let aboveFrame = globalFrame(
            for: above,
            hubOrigin: hubOrigin
        )
        let belowFrame = globalFrame(
            for: below,
            hubOrigin: hubOrigin
        )
        return overflow(of: aboveFrame, outside: visibleFrame)
            <= overflow(of: belowFrame, outside: visibleFrame)
            ? above
            : below
    }

    private func globalFrame(
        for geometry: SessionFanGeometry,
        hubOrigin: NSPoint
    ) -> NSRect {
        NSRect(
            x: hubOrigin.x - geometry.hubOffset.x,
            y: hubOrigin.y - geometry.hubOffset.y,
            width: geometry.size.width,
            height: geometry.size.height
        )
    }

    private func overflow(of frame: NSRect, outside visibleFrame: NSRect) -> CGFloat {
        max(0, visibleFrame.minX - frame.minX)
            + max(0, frame.maxX - visibleFrame.maxX)
            + max(0, visibleFrame.minY - frame.minY)
            + max(0, frame.maxY - visibleFrame.maxY)
    }

    private func sessionButtonFocusChanged(
        _ session: OverlaySelectedSession,
        focused: Bool
    ) {
        if focused {
            focusedSessionIdentities.insert(session.identity)
            expand()
        } else {
            focusedSessionIdentities.remove(session.identity)
            scheduleCollapse()
        }
    }

    private func scheduleCollapse() {
        collapseWorkItem?.cancel()
        let workItem = DispatchWorkItem { [weak self] in
            guard let self, let panel = self.window else { return }
            if NSEvent.pressedMouseButtons != 0 {
                self.scheduleCollapse()
                return
            }
            let pointerIsInside = NSMouseInRect(
                NSEvent.mouseLocation,
                panel.frame,
                false
            )
            guard !pointerIsInside,
                  self.focusedSessionIdentities.isEmpty else { return }
            self.collapse()
        }
        collapseWorkItem = workItem
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.12, execute: workItem)
    }

    private func visibleFrame(
        containing hubOrigin: NSPoint,
        panel: NSWindow
    ) -> NSRect? {
        let hubCenter = NSPoint(
            x: hubOrigin.x + collapsedSize.width / 2,
            y: hubOrigin.y + collapsedSize.height / 2
        )
        return NSScreen.screens.first { $0.frame.contains(hubCenter) }?.visibleFrame
            ?? panel.screen?.visibleFrame
            ?? NSScreen.main?.visibleFrame
    }

    private func constrainedOrigin(
        _ origin: NSPoint,
        size: NSSize,
        visibleFrame: NSRect?
    ) -> NSPoint {
        guard let visibleFrame else { return origin }
        return NSPoint(
            x: min(
                max(origin.x, visibleFrame.minX),
                visibleFrame.maxX - size.width
            ),
            y: min(
                max(origin.y, visibleFrame.minY),
                visibleFrame.maxY - size.height
            )
        )
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
