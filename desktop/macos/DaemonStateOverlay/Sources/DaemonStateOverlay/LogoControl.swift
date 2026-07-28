import AppKit
import QuartzCore
import DaemonStateOverlayCore

@MainActor
final class LogoControl: NSControl {
    enum VisualState {
        case idle
        case loading
        case success
        case failure
    }

    var onSingleClick: (() -> Void)?
    var onTripleClick: (() -> Void)?
    var onGestureBegan: (() -> Void)?
    var onGestureCancelled: (() -> Void)?
    var onContextMenu: ((NSPoint) -> Void)?
    var onMove: ((NSPoint) -> Void)?

    var scope: ContextScope = .defaultScope {
        didSet {
            updateAccessibility()
            needsDisplay = true
        }
    }

    var visualState: VisualState = .idle {
        didSet {
            needsDisplay = true
            animateStateChange()
        }
    }

    private var pendingSingleClick: DispatchWorkItem?
    private var trackingAreaReference: NSTrackingArea?
    private var hovering = false
    private var dragged = false
    private var dragStartMouseLocation = NSPoint.zero
    private var dragStartWindowOrigin = NSPoint.zero

    override var isFlipped: Bool { true }

    override init(frame frameRect: NSRect) {
        super.init(frame: frameRect)
        wantsLayer = true
        layer?.masksToBounds = false
        toolTip = tooltipText
        setAccessibilityRole(.button)
        updateAccessibility()
    }

    required init?(coder: NSCoder) {
        nil
    }

    override func acceptsFirstMouse(for event: NSEvent?) -> Bool {
        true
    }

    deinit {
        pendingSingleClick?.cancel()
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

    override func mouseDown(with event: NSEvent) {
        // Cancel on press rather than release. A held second or third press
        // must never let the earlier deferred single-click action fire.
        pendingSingleClick?.cancel()
        pendingSingleClick = nil
        switch ContextGesture.disposition(forClickCount: event.clickCount) {
        case .scheduleSingle:
            onGestureBegan?()
        case .cancelSingleAndToggle:
            onGestureCancelled?()
        case .rescheduleSingle, .ignore:
            break
        }

        dragged = false
        dragStartMouseLocation = NSEvent.mouseLocation
        dragStartWindowOrigin = window?.frame.origin ?? .zero
        animatePress()
    }

    override func mouseDragged(with event: NSEvent) {
        guard let window else { return }
        let current = NSEvent.mouseLocation
        let deltaX = current.x - dragStartMouseLocation.x
        let deltaY = current.y - dragStartMouseLocation.y
        if !dragged, hypot(deltaX, deltaY) < 4 {
            return
        }
        dragged = true
        pendingSingleClick?.cancel()
        pendingSingleClick = nil
        onGestureCancelled?()
        let desiredOrigin = NSPoint(
            x: dragStartWindowOrigin.x + deltaX,
            y: dragStartWindowOrigin.y + deltaY
        )
        let screen = NSScreen.screens.first {
            NSMouseInRect(current, $0.frame, false)
        } ?? window.screen
        if let visibleFrame = screen?.visibleFrame {
            window.setFrameOrigin(
                NSPoint(
                    x: min(
                        max(desiredOrigin.x, visibleFrame.minX),
                        visibleFrame.maxX - window.frame.width
                    ),
                    y: min(
                        max(desiredOrigin.y, visibleFrame.minY),
                        visibleFrame.maxY - window.frame.height
                    )
                )
            )
        } else {
            window.setFrameOrigin(desiredOrigin)
        }
    }

    override func mouseUp(with event: NSEvent) {
        if dragged {
            if let origin = window?.frame.origin {
                onMove?(origin)
            }
            return
        }
        handleClickCount(event.clickCount)
    }

    override func rightMouseDown(with event: NSEvent) {
        pendingSingleClick?.cancel()
        pendingSingleClick = nil
        onGestureCancelled?()
        onContextMenu?(convert(event.locationInWindow, from: nil))
    }

    override func accessibilityPerformPress() -> Bool {
        pendingSingleClick?.cancel()
        pendingSingleClick = nil
        onGestureBegan?()
        scheduleSingleClick()
        return true
    }

    override func draw(_ dirtyRect: NSRect) {
        super.draw(dirtyRect)
        NSGraphicsContext.current?.imageInterpolation = .high

        let diameter = min(bounds.width, bounds.height) - 10
        let logoRect = NSRect(
            x: (bounds.width - diameter) / 2,
            y: (bounds.height - diameter) / 2,
            width: diameter,
            height: diameter
        )
        drawHalo(around: logoRect)

        let circle = NSBezierPath(ovalIn: logoRect)
        NSColor.white.setFill()
        circle.fill()
        NSColor.black.setStroke()
        circle.lineWidth = 1.35
        circle.stroke()

        drawMark(in: logoRect)
    }

    private func handleClickCount(_ clickCount: Int) {
        switch ContextGesture.disposition(forClickCount: clickCount) {
        case .scheduleSingle:
            scheduleSingleClick()
        case .rescheduleSingle:
            // Restart from the second click so a slower, system-recognized
            // third click can still cancel the action before insertion.
            scheduleSingleClick()
        case .cancelSingleAndToggle:
            pendingSingleClick?.cancel()
            pendingSingleClick = nil
            onTripleClick?()
        case .ignore:
            break
        }
    }

    private func scheduleSingleClick() {
        pendingSingleClick?.cancel()
        let workItem = DispatchWorkItem { [weak self] in
            self?.pendingSingleClick = nil
            self?.onSingleClick?()
        }
        pendingSingleClick = workItem
        DispatchQueue.main.asyncAfter(
            deadline: .now() + NSEvent.doubleClickInterval + 0.06,
            execute: workItem
        )
    }

    private func drawHalo(around logoRect: NSRect) {
        let haloRect = logoRect.insetBy(dx: -4, dy: -4)
        let halo = NSBezierPath(ovalIn: haloRect)
        let color: NSColor?
        switch visualState {
        case .loading:
            color = NSColor(calibratedRed: 0.85, green: 1, blue: 0.41, alpha: 0.88)
        case .success:
            color = NSColor(calibratedRed: 0.46, green: 0.78, blue: 0.46, alpha: 0.9)
        case .failure:
            color = NSColor(calibratedRed: 0.94, green: 0.22, blue: 0.25, alpha: 0.9)
        case .idle:
            if scope == .project {
                color = NSColor(calibratedRed: 0.85, green: 1, blue: 0.41, alpha: 0.96)
            } else if hovering {
                color = NSColor(calibratedWhite: 0, alpha: 0.18)
            } else {
                color = nil
            }
        }
        guard let color else { return }
        color.setStroke()
        halo.lineWidth = visualState == .idle ? 2.5 : 3.5
        halo.stroke()
    }

    private func drawMark(in logoRect: NSRect) {
        let points = [
            NSPoint(x: 13.2, y: 11),
            NSPoint(x: 7.5, y: 20.9),
            NSPoint(x: 16.2, y: 26.7),
            NSPoint(x: 21.1, y: 11),
            NSPoint(x: 26.7, y: 25.9),
            NSPoint(x: 31.5, y: 10.6),
        ].map { point -> NSPoint in
            NSPoint(
                x: logoRect.minX + (point.x / 40) * logoRect.width,
                y: logoRect.minY + (point.y / 40) * logoRect.height
            )
        }

        let mark = NSBezierPath()
        mark.move(to: points[0])
        for point in points.dropFirst() {
            mark.line(to: point)
        }
        mark.lineWidth = max(1.25, logoRect.width * (1.25 / 40))
        mark.lineCapStyle = .round
        mark.lineJoinStyle = .round
        NSColor.black.setStroke()
        mark.stroke()

        for (index, point) in points.dropLast().enumerated() {
            let radius = max(1.4, logoRect.width * (1.4 / 40))
            let node = NSBezierPath(
                ovalIn: NSRect(
                    x: point.x - radius,
                    y: point.y - radius,
                    width: radius * 2,
                    height: radius * 2
                )
            )
            if index == 3 {
                NSColor(calibratedRed: 0.94, green: 0.06, blue: 0.1, alpha: 1).setFill()
            } else {
                NSColor.black.setFill()
            }
            node.fill()
        }
    }

    private func animatePress() {
        guard !NSWorkspace.shared.accessibilityDisplayShouldReduceMotion else {
            return
        }
        let animation = CAKeyframeAnimation(keyPath: "transform.scale")
        animation.values = [1, 0.9, 1.04, 1]
        animation.keyTimes = [0, 0.3, 0.7, 1]
        animation.duration = 0.22
        animation.timingFunction = CAMediaTimingFunction(name: .easeOut)
        layer?.add(animation, forKey: "daemonstate-press")
    }

    private func animateStateChange() {
        guard !NSWorkspace.shared.accessibilityDisplayShouldReduceMotion else {
            return
        }
        switch visualState {
        case .success:
            let animation = CAKeyframeAnimation(keyPath: "transform.scale")
            animation.values = [1, 1.12, 0.98, 1]
            animation.duration = 0.32
            layer?.add(animation, forKey: "daemonstate-success")
        case .failure:
            let animation = CAKeyframeAnimation(keyPath: "transform.translation.x")
            animation.values = [0, -4, 4, -3, 3, 0]
            animation.duration = 0.3
            layer?.add(animation, forKey: "daemonstate-failure")
        case .idle, .loading:
            break
        }
    }

    private var scopeLabel: String {
        scope == .session ? "Session Context" : "Workspace Context"
    }

    private var tooltipText: String {
        "\(scopeLabel) — click to insert; triple-click to switch scope; drag to move"
    }

    private func updateAccessibility() {
        toolTip = tooltipText
        setAccessibilityLabel("Insert \(scopeLabel)")
        setAccessibilityValue(scopeLabel)
        setAccessibilityHelp(
            "Click once to copy and paste verified context. Triple-click to switch between Session and Workspace Context. Right-click for the same controls."
        )
    }
}
