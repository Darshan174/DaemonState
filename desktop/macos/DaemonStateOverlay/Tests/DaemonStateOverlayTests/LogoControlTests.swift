import AppKit
import Foundation
import Testing
@testable import DaemonStateOverlay

@Suite(.serialized)
struct LogoControlTests {
    @Test
    @MainActor
    func firstMouseIsAcceptedWithoutMakingThePanelKey() {
        let control = LogoControl(frame: NSRect(x: 0, y: 0, width: 56, height: 56))
        let panelController = OverlayPanelController(savedOrigin: nil)
        var showedAccessibleMenu = false
        control.onContextMenu = { _ in showedAccessibleMenu = true }

        #expect(control.acceptsFirstMouse(for: nil))
        #expect(control.isAccessibilityElement())
        #expect(control.accessibilityPerformShowMenu())
        #expect(showedAccessibleMenu)
        #expect(panelController.window?.canBecomeKey == false)
        #expect(panelController.window?.canBecomeMain == false)
    }

    @Test
    @MainActor
    func selectedPromptsArmTheLogoAndDropdownAccessibilityState() {
        let control = LogoControl(frame: NSRect(x: 0, y: 0, width: 56, height: 56))
        let menuButton = PromptMenuButton(
            frame: NSRect(x: 0, y: 0, width: 24, height: 24)
        )

        control.selectedPromptCount = 2
        menuButton.selectedPromptCount = 2

        #expect(control.accessibilityLabel() == "Paste selected prompts")
        #expect(control.accessibilityValue() as? String == "2 prompts selected")
        #expect(control.toolTip?.contains("2 prompts selected") == true)
        #expect(menuButton.accessibilityValue() as? String == "2 prompts selected")

        control.selectedPromptCount = 0
        menuButton.selectedPromptCount = 0

        #expect(control.accessibilityLabel() == "Insert Session Context")
        #expect(control.accessibilityValue() as? String == "Session Context")
        #expect(menuButton.accessibilityValue() as? String == "No prompts selected")
    }

    @Test
    @MainActor
    func selectedSessionFanOrbitsTheHubInStaggeredOrdinalOrder() async throws {
        let controller = OverlayPanelController(savedOrigin: nil)
        defer { controller.hide() }
        let sessions = selectedSessionFixtures()
        var chosenSession: OverlaySelectedSession?
        controller.onSelectSession = {
            chosenSession = $0
        }

        controller.setSelectedSessions(sessions)

        #expect(controller.window?.frame.width == 72)
        #expect(controller.sessionButtons.count == 3)
        #expect(controller.sessionButtons.allSatisfy { $0.isHidden })

        controller.expand()

        #expect(controller.isExpanded)
        #expect(controller.window?.frame.width == 200)
        #expect(controller.window?.frame.height == 152)
        #expect(controller.sessionButtons.allSatisfy { !$0.isHidden })
        let first = try #require(controller.sessionButtons[safe: 0])
        let second = try #require(controller.sessionButtons[safe: 1])
        let third = try #require(controller.sessionButtons[safe: 2])
        let hubFrame = controller.logoControl.frame
        #expect(first.frame.midX < hubFrame.midX)
        #expect(second.frame.midX > hubFrame.midX)
        #expect(third.frame.midY > first.frame.midY)
        #expect(first.lastRevealDelay == 0)
        #expect(abs(second.lastRevealDelay - 0.075) < 0.001)
        #expect(abs(third.lastRevealDelay - 0.15) < 0.001)
        #expect(
            second.accessibilityLabel()
                == "Session 2, Claude Code, Review the architecture"
        )
        #expect(
            second.toolTip?.hasPrefix("Paste Session 2 Context · Claude Code") == true
        )
        #expect(second.accessibilityPerformPress())
        #expect(chosenSession == sessions[1])
        #expect(second.accessibilityValue() as? String == "Pastes immediately")

        controller.collapse()

        #expect(!controller.isExpanded)
        #expect(controller.window?.frame.width == 200)
        #expect(controller.sessionButtons.allSatisfy { !$0.isHidden })
        #expect(abs(first.lastCollapseDelay - 0.09) < 0.001)
        #expect(abs(second.lastCollapseDelay - 0.045) < 0.001)
        #expect(third.lastCollapseDelay == 0)

        controller.expand()
        try await Task<Never, Never>.sleep(nanoseconds: 350_000_000)

        #expect(controller.isExpanded)
        #expect(controller.window?.frame.width == 200)
        #expect(controller.sessionButtons.allSatisfy { !$0.isHidden })

        controller.collapse()
        try await Task<Never, Never>.sleep(nanoseconds: 350_000_000)

        #expect(!controller.isExpanded)
        #expect(controller.window?.frame.width == 72)
        #expect(controller.sessionButtons.allSatisfy { $0.isHidden })
    }

    @Test
    @MainActor
    func anthropicSessionButtonUsesAFullTanCardWithATransparentBlackMark() throws {
        let anthropic = try #require(
            SessionFanButton.cardFillColor(
                for: "claude",
                hovering: false
            ).usingColorSpace(.sRGB)
        )
        let hoveredAnthropic = try #require(
            SessionFanButton.cardFillColor(
                for: "claude",
                hovering: true
            ).usingColorSpace(.sRGB)
        )
        let codex = try #require(
            SessionFanButton.cardFillColor(
                for: "codex",
                hovering: false
            ).usingColorSpace(.sRGB)
        )

        #expect(abs(anthropic.redComponent - (201.0 / 255.0)) < 0.001)
        #expect(abs(anthropic.greenComponent - (158.0 / 255.0)) < 0.001)
        #expect(abs(anthropic.blueComponent - (123.0 / 255.0)) < 0.001)
        #expect(hoveredAnthropic == anthropic)
        #expect(codex.redComponent > 0.97)
        #expect(codex.greenComponent > 0.97)
        #expect(codex.blueComponent > 0.97)

        let logoURL = try #require(
            SessionFanButton.providerLogoURL("claude")
        )
        let logoSource = try String(contentsOf: logoURL, encoding: .utf8)
        #expect(logoURL.pathExtension == "svg")
        #expect(logoSource.contains("fill=\"#252525\""))
        #expect(!logoSource.contains("<rect"))
    }

    @Test
    @MainActor
    func workspaceScopeUsesDistinctAccessibilityWithoutSessionArming() {
        let control = LogoControl(frame: NSRect(x: 0, y: 0, width: 56, height: 56))

        control.scope = .project
        #expect(control.accessibilityLabel() == "Insert Workspace Context")
        #expect(control.accessibilityValue() as? String == "Workspace Context")
        #expect(control.toolTip?.contains("switch and insert") == true)

        control.scope = .session
        #expect(control.accessibilityLabel() == "Insert Session Context")
        #expect(control.accessibilityValue() as? String == "Session Context")
    }

    @Test
    @MainActor
    func longStatusMessageWrapsWithoutClipping() throws {
        let controller = StatusPanelController()
        defer { controller.hide() }

        let message = (
            "Current Session Context is unavailable: the service did not "
            + "return a complete checkpoint at the current session tip"
        )

        controller.show(
            message,
            relativeTo: nil,
            dismissAfter: nil
        )

        let panel = try #require(controller.window)
        let label = try #require(panel.contentView?.subviews
            .compactMap { $0 as? NSTextField }
            .first)
        let requiredBounds = (message as NSString).boundingRect(
            with: NSSize(
                width: label.frame.width,
                height: .greatestFiniteMagnitude
            ),
            options: [.usesLineFragmentOrigin, .usesFontLeading],
            attributes: [.font: label.font as Any]
        )

        #expect(panel.frame.width == 340)
        #expect(panel.frame.height > 42)
        #expect(label.frame.width == 312)
        #expect(label.maximumNumberOfLines == 4)
        #expect(label.frame.height >= ceil(requiredBounds.height))
    }

    @Test
    @MainActor
    func statusFeedbackStaysAboveTheFloatingControlAcrossSpaces() {
        let overlay = OverlayPanelController(savedOrigin: nil)
        let status = StatusPanelController()
        defer { status.hide() }

        status.show(
            "Workspace Context pasted",
            relativeTo: overlay.window,
            dismissAfter: nil
        )

        let panel = status.window
        #expect(
            panel?.level.rawValue ?? 0
                > (overlay.window?.level.rawValue ?? 0)
        )
        #expect(panel?.collectionBehavior.contains(.canJoinAllSpaces) == true)
        #expect(panel?.collectionBehavior.contains(.fullScreenAuxiliary) == true)
    }

    @Test
    @MainActor
    func statusFeedbackUsesThemeAdaptiveSemanticColors() {
        let light = StatusPanelController.textColor(
            for: .success,
            darkMode: false
        ).usingColorSpace(.deviceRGB)
        let dark = StatusPanelController.textColor(
            for: .success,
            darkMode: true
        ).usingColorSpace(.deviceRGB)

        #expect((light?.greenComponent ?? 1) < 0.5)
        #expect((dark?.greenComponent ?? 0) > 0.9)
        #expect(light != dark)
    }

    @Test
    @MainActor
    func promptEditorExplicitlyTakesInputFocus() {
        let controller = PromptDropdownViewController()
        let panel = InputTestPanel(
            contentRect: NSRect(x: 0, y: 0, width: 360, height: 466),
            styleMask: [.borderless],
            backing: .buffered,
            defer: false
        )
        panel.contentViewController = controller
        panel.makeKeyAndOrderFront(nil)
        defer { panel.orderOut(nil) }

        #expect(controller.focusEditor())
        #expect(controller.editorHasInputFocus)
    }

    @Test
    @MainActor
    func openingPromptPopoverFocusesItsEditor() async throws {
        let overlay = OverlayPanelController(savedOrigin: nil)
        let controller = PromptDropdownController()
        overlay.show()
        controller.toggle(relativeTo: overlay.promptMenuButton)
        defer {
            controller.close()
            overlay.hide()
        }

        try await Task<Never, Never>.sleep(nanoseconds: 100_000_000)

        #expect(controller.editorHasInputFocus)
    }

    @Test
    @MainActor
    func promptTextViewHandlesCommandPasteDirectly() {
        let application = NSApplication.shared
        let previousMenu = application.mainMenu
        defer { application.mainMenu = previousMenu }
        OverlayApplicationMenu.install(on: application)
        let editMenu = application.mainMenu?.items.first {
            $0.submenu?.title == "Edit"
        }?.submenu
        let pasteItem = editMenu?.items.first {
            $0.action == #selector(NSText.paste(_:))
        }
        #expect(pasteItem?.keyEquivalent == "v")
        #expect(pasteItem?.target == nil)

        let probe = PasteActionProbeTextView(
            frame: NSRect(x: 0, y: 0, width: 100, height: 40)
        )
        let panel = InputTestPanel(
            contentRect: probe.frame,
            styleMask: [.borderless],
            backing: .buffered,
            defer: false
        )
        panel.contentView = probe
        panel.makeKeyAndOrderFront(nil)
        defer { panel.orderOut(nil) }
        #expect(panel.makeFirstResponder(probe))

        let event = NSEvent.keyEvent(
            with: .keyDown,
            location: .zero,
            modifierFlags: [.command],
            timestamp: ProcessInfo.processInfo.systemUptime,
            windowNumber: panel.windowNumber,
            context: nil,
            characters: "v",
            charactersIgnoringModifiers: "v",
            isARepeat: false,
            keyCode: 9
        )!

        #expect(panel.performKeyEquivalent(with: event))
        #expect(probe.receivedPaste)
    }

    @Test
    @MainActor
    func heldSubsequentPressesCancelInsertionBeforeTheirRelease() async throws {
        let control = LogoControl(frame: NSRect(x: 0, y: 0, width: 56, height: 56))
        var insertions = 0
        var toggles = 0
        var targetCaptures = 0
        var targetDiscards = 0
        control.onSingleClick = { insertions += 1 }
        control.onTripleClick = { toggles += 1 }
        control.onGestureBegan = { targetCaptures += 1 }
        control.onGestureCancelled = { targetDiscards += 1 }

        control.mouseDown(with: mouseEvent(type: .leftMouseDown, clickCount: 1))
        control.mouseUp(with: mouseEvent(type: .leftMouseUp, clickCount: 1))
        control.mouseDown(with: mouseEvent(type: .leftMouseDown, clickCount: 2))

        try await waitPastClickDeadline()
        #expect(insertions == 0)
        #expect(targetCaptures == 1)

        control.mouseUp(with: mouseEvent(type: .leftMouseUp, clickCount: 2))
        control.mouseDown(with: mouseEvent(type: .leftMouseDown, clickCount: 3))

        try await waitPastClickDeadline()
        #expect(insertions == 0)
        #expect(targetDiscards == 1)

        control.mouseUp(with: mouseEvent(type: .leftMouseUp, clickCount: 3))
        #expect(insertions == 0)
        #expect(toggles == 1)

        // AppKit continues the sequence with click count four when the user
        // immediately clicks to insert the newly selected context.
        control.mouseDown(with: mouseEvent(type: .leftMouseDown, clickCount: 4))
        control.mouseUp(with: mouseEvent(type: .leftMouseUp, clickCount: 4))

        try await waitPastClickDeadline()
        #expect(targetCaptures == 2)
        #expect(insertions == 1)
        #expect(toggles == 1)
    }

    @MainActor
    private func mouseEvent(
        type: NSEvent.EventType,
        clickCount: Int
    ) -> NSEvent {
        NSEvent.mouseEvent(
            with: type,
            location: .zero,
            modifierFlags: [],
            timestamp: ProcessInfo.processInfo.systemUptime,
            windowNumber: 0,
            context: nil,
            eventNumber: clickCount,
            clickCount: clickCount,
            pressure: 0
        )!
    }

    private func waitPastClickDeadline() async throws {
        let milliseconds = Int((NSEvent.doubleClickInterval + 0.14) * 1_000)
        try await Task.sleep(for: .milliseconds(milliseconds))
    }

    private func selectedSessionFixtures() -> [OverlaySelectedSession] {
        [
            OverlaySelectedSession(
                provider: "codex",
                sessionID: "codex-session-1",
                title: "Implement the control",
                ordinal: 1
            ),
            OverlaySelectedSession(
                provider: "claude",
                sessionID: "claude-session-2",
                title: "Review the architecture",
                ordinal: 2
            ),
            OverlaySelectedSession(
                provider: "opencode",
                sessionID: "opencode-session-3",
                title: "Test the overlay",
                ordinal: 3
            ),
        ]
    }
}

private extension Collection {
    subscript(safe index: Index) -> Element? {
        indices.contains(index) ? self[index] : nil
    }
}

@MainActor
private final class InputTestPanel: NSPanel {
    override var canBecomeKey: Bool { true }
}

@MainActor
private final class PasteActionProbeTextView: PromptTextView {
    var receivedPaste = false

    override func paste(_ sender: Any?) {
        receivedPaste = true
    }
}
