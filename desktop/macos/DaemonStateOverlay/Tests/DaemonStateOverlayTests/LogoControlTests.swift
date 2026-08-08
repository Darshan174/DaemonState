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

        #expect(control.acceptsFirstMouse(for: nil))
        #expect(control.isAccessibilityElement())
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
    func longStatusMessageWrapsWithoutGrowingPastItsPanel() {
        let controller = StatusPanelController()
        defer { controller.hide() }

        controller.show(
            "Current Session Context is unavailable: choose an active session in Library, then try again",
            relativeTo: nil,
            dismissAfter: nil
        )

        let panel = controller.window
        let label = panel?.contentView?.subviews
            .compactMap { $0 as? NSTextField }
            .first
        #expect(panel?.frame.width == 340)
        #expect(panel?.frame.height ?? 0 > 42)
        #expect(label?.frame.width == 312)
        #expect(label?.maximumNumberOfLines == 2)
    }

    @Test
    @MainActor
    func statusFeedbackStaysAboveTheFloatingControlAcrossSpaces() {
        let overlay = OverlayPanelController(savedOrigin: nil)
        let status = StatusPanelController()
        defer { status.hide() }

        status.show(
            "Workspace Context selected",
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
