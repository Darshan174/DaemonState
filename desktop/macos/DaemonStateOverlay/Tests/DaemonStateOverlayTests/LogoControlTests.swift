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
        #expect(panelController.window?.canBecomeKey == false)
        #expect(panelController.window?.canBecomeMain == false)
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
