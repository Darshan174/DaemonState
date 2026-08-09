import AppKit
import QuartzCore

@MainActor
final class OverlayTrackingView: NSView {
    var onHoverChanged: ((Bool) -> Void)?

    private var trackingAreaReference: NSTrackingArea?

    override func updateTrackingAreas() {
        super.updateTrackingAreas()
        if let trackingAreaReference {
            removeTrackingArea(trackingAreaReference)
        }
        let area = NSTrackingArea(
            rect: bounds,
            options: [
                .activeAlways,
                .inVisibleRect,
                .mouseEnteredAndExited,
            ],
            owner: self,
            userInfo: nil
        )
        addTrackingArea(area)
        trackingAreaReference = area
    }

    override func mouseEntered(with event: NSEvent) {
        onHoverChanged?(true)
    }

    override func mouseExited(with event: NSEvent) {
        onHoverChanged?(false)
    }
}

@MainActor
final class SessionFanButton: NSButton {
    let session: OverlaySelectedSession
    var onPress: ((OverlaySelectedSession) -> Void)?
    var onFocusChanged: ((Bool) -> Void)?

    private var hovering = false
    private var trackingAreaReference: NSTrackingArea?
    private let logoImage: NSImage?
    private(set) var lastRevealDelay: TimeInterval = 0

    init(session: OverlaySelectedSession, frame: NSRect) {
        self.session = session
        logoImage = Self.loadProviderLogo(session.provider)
        super.init(frame: frame)
        title = ""
        isBordered = false
        focusRingType = .none
        target = self
        action = #selector(pressed)
        wantsLayer = true
        toolTip = "Paste Session \(session.ordinalLabel) Context · \(session.providerDisplayName) · \(session.title)"
        setAccessibilityElement(true)
        setAccessibilityRole(.button)
        setAccessibilityIdentifier(
            "selected-session-\(session.ordinal)-\(session.provider)"
        )
        updateAccessibility()
    }

    required init?(coder: NSCoder) {
        nil
    }

    override var acceptsFirstResponder: Bool { true }

    override func acceptsFirstMouse(for event: NSEvent?) -> Bool {
        true
    }

    override func becomeFirstResponder() -> Bool {
        let accepted = super.becomeFirstResponder()
        if accepted {
            onFocusChanged?(true)
            needsDisplay = true
        }
        return accepted
    }

    override func resignFirstResponder() -> Bool {
        let resigned = super.resignFirstResponder()
        if resigned {
            onFocusChanged?(false)
            needsDisplay = true
        }
        return resigned
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

    override func keyDown(with event: NSEvent) {
        if event.keyCode == 36 || event.keyCode == 49 {
            pressed()
        } else {
            super.keyDown(with: event)
        }
    }

    override func accessibilityPerformPress() -> Bool {
        pressed()
        return true
    }

    override func draw(_ dirtyRect: NSRect) {
        NSGraphicsContext.current?.imageInterpolation = .high
        let cardRect = bounds.insetBy(dx: 2.5, dy: 2.5)
        let card = NSBezierPath(
            roundedRect: cardRect,
            xRadius: 15,
            yRadius: 15
        )

        NSGraphicsContext.saveGraphicsState()
        let shadow = NSShadow()
        shadow.shadowColor = NSColor.black.withAlphaComponent(0.14)
        shadow.shadowBlurRadius = 6
        shadow.shadowOffset = NSSize(width: 0, height: -1)
        shadow.set()
        (hovering
            ? NSColor(calibratedWhite: 1, alpha: 1)
            : NSColor(calibratedWhite: 0.98, alpha: 0.98)
        ).setFill()
        card.fill()
        NSGraphicsContext.restoreGraphicsState()

        NSColor.black.withAlphaComponent(hovering ? 0.30 : 0.16).setStroke()
        card.lineWidth = 1
        card.stroke()

        let logoRect = NSRect(
            x: bounds.midX - 10,
            y: bounds.midY - 10,
            width: 20,
            height: 20
        )
        if let logoImage {
            logoImage.draw(
                in: logoRect,
                from: .zero,
                operation: .sourceOver,
                fraction: 1,
                respectFlipped: true,
                hints: nil
            )
        } else {
            drawFallbackLogo(in: logoRect)
        }

        let badgeRect = NSRect(
            x: bounds.maxX - 18,
            y: bounds.maxY - 18,
            width: 16,
            height: 16
        )
        let badge = NSBezierPath(
            roundedRect: badgeRect,
            xRadius: 7,
            yRadius: 7
        )
        NSColor(calibratedWhite: 0.10, alpha: 0.96).setFill()
        badge.fill()
        let attributes: [NSAttributedString.Key: Any] = [
            .font: NSFont.monospacedDigitSystemFont(ofSize: 8, weight: .bold),
            .foregroundColor: NSColor.white,
        ]
        let ordinal = session.ordinalLabel
        let size = ordinal.size(withAttributes: attributes)
        ordinal.draw(
            at: NSPoint(
                x: badgeRect.midX - size.width / 2,
                y: badgeRect.midY - size.height / 2
            ),
            withAttributes: attributes
        )

        if window?.firstResponder === self {
            NSColor.keyboardFocusIndicatorColor.setStroke()
            let focus = NSBezierPath(
                roundedRect: cardRect.insetBy(dx: 2, dy: 2),
                xRadius: 12,
                yRadius: 12
            )
            focus.lineWidth = 2
            focus.stroke()
        }
    }

    func animateReveal(
        from hubCenter: NSPoint,
        delay: TimeInterval,
        animated: Bool
    ) {
        lastRevealDelay = delay
        guard let layer else { return }
        layer.removeAnimation(forKey: "session-fan-reveal")
        alphaValue = 1
        guard animated else { return }

        let position = CABasicAnimation(keyPath: "position")
        position.fromValue = NSValue(point: hubCenter)
        position.toValue = NSValue(point: layer.position)

        let scale = CAKeyframeAnimation(keyPath: "transform.scale")
        scale.values = [0.46, 1.06, 1]
        scale.keyTimes = [0, 0.72, 1]

        let opacity = CABasicAnimation(keyPath: "opacity")
        opacity.fromValue = 0
        opacity.toValue = 1

        let group = CAAnimationGroup()
        group.animations = [position, scale, opacity]
        group.duration = 0.24
        group.beginTime = layer.convertTime(CACurrentMediaTime(), from: nil) + delay
        group.fillMode = .backwards
        group.isRemovedOnCompletion = true
        group.timingFunction = CAMediaTimingFunction(name: .easeOut)
        layer.add(group, forKey: "session-fan-reveal")
    }

    func stopRevealAnimation() {
        layer?.removeAnimation(forKey: "session-fan-reveal")
        alphaValue = 1
    }

    @objc private func pressed() {
        onPress?(session)
    }

    private func updateAccessibility() {
        setAccessibilityLabel(
            "Session \(session.ordinalLabel), \(session.providerDisplayName), \(session.title)"
        )
        setAccessibilityValue("Pastes immediately")
        setAccessibilityHelp(
            "Prepare and paste this exact Session Context into the focused editor."
        )
    }

    private static func loadProviderLogo(_ provider: String) -> NSImage? {
        let resourceName: String
        switch provider {
        case "codex":
            resourceName = "openai"
        case "claude":
            resourceName = "claude"
        case "opencode":
            resourceName = "opencode"
        default:
            return nil
        }
        guard let url = Bundle.module.url(
            forResource: resourceName,
            withExtension: "svg"
        ) else {
            return nil
        }
        return NSImage(contentsOf: url)
    }

    private func drawFallbackLogo(in rect: NSRect) {
        let label: String
        switch session.provider {
        case "codex": label = "O"
        case "claude": label = "A"
        case "opencode": label = "[]"
        default: label = "AI"
        }
        let attributes: [NSAttributedString.Key: Any] = [
            .font: NSFont.systemFont(ofSize: label.count > 1 ? 10 : 15, weight: .bold),
            .foregroundColor: NSColor.black,
        ]
        let size = label.size(withAttributes: attributes)
        label.draw(
            at: NSPoint(
                x: rect.midX - size.width / 2,
                y: rect.midY - size.height / 2
            ),
            withAttributes: attributes
        )
    }
}
