import AppKit
import ApplicationServices

enum PasteDeliveryOutcome: Equatable {
    case pasted
    case copiedOnly(String)
}

enum PasteDeliveryError: LocalizedError {
    case clipboardUnavailable
    case clipboardChanged
    case keyboardEventUnavailable

    var errorDescription: String? {
        switch self {
        case .clipboardUnavailable:
            return "The verified context could not be written to the clipboard."
        case .clipboardChanged:
            return "The clipboard changed before paste. Click the control to try again."
        case .keyboardEventUnavailable:
            return "The context was copied, but macOS could not create the paste command."
        }
    }
}

@MainActor
protocol AccessibilityElementClient: AnyObject {
    func isTrusted(prompt: Bool) -> Bool
    func focusedElement() -> AXUIElement?
    func processIdentifier(for element: AXUIElement) -> pid_t?
    func stringAttribute(
        _ attribute: CFString,
        from element: AXUIElement
    ) -> String?
    func boolAttribute(
        _ attribute: CFString,
        from element: AXUIElement
    ) -> Bool?
    func isAttributeSettable(
        _ attribute: CFString,
        on element: AXUIElement
    ) -> Bool
    func setAttribute(
        _ attribute: CFString,
        to value: CFTypeRef,
        on element: AXUIElement
    ) -> AXError
    func elementsAreEqual(_ lhs: AXUIElement, _ rhs: AXUIElement) -> Bool
}

@MainActor
final class SystemAccessibilityElementClient: AccessibilityElementClient {
    func isTrusted(prompt: Bool) -> Bool {
        let key = kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String
        let options = [key: prompt] as CFDictionary
        return AXIsProcessTrustedWithOptions(options)
    }

    func focusedElement() -> AXUIElement? {
        let systemWide = AXUIElementCreateSystemWide()
        var value: CFTypeRef?
        guard AXUIElementCopyAttributeValue(
            systemWide,
            kAXFocusedUIElementAttribute as CFString,
            &value
        ) == .success,
        let value
        else {
            return nil
        }
        return (value as! AXUIElement)
    }

    func processIdentifier(for element: AXUIElement) -> pid_t? {
        var processIdentifier: pid_t = 0
        guard AXUIElementGetPid(element, &processIdentifier) == .success else {
            return nil
        }
        return processIdentifier
    }

    func stringAttribute(
        _ attribute: CFString,
        from element: AXUIElement
    ) -> String? {
        var value: CFTypeRef?
        guard AXUIElementCopyAttributeValue(element, attribute, &value) == .success
        else {
            return nil
        }
        return value as? String
    }

    func boolAttribute(
        _ attribute: CFString,
        from element: AXUIElement
    ) -> Bool? {
        var value: CFTypeRef?
        guard AXUIElementCopyAttributeValue(element, attribute, &value) == .success
        else {
            return nil
        }
        return value as? Bool
    }

    func isAttributeSettable(
        _ attribute: CFString,
        on element: AXUIElement
    ) -> Bool {
        var settable = DarwinBoolean(false)
        guard AXUIElementIsAttributeSettable(
            element,
            attribute,
            &settable
        ) == .success else {
            return false
        }
        return settable.boolValue
    }

    func setAttribute(
        _ attribute: CFString,
        to value: CFTypeRef,
        on element: AXUIElement
    ) -> AXError {
        AXUIElementSetAttributeValue(element, attribute, value)
    }

    func elementsAreEqual(_ lhs: AXUIElement, _ rhs: AXUIElement) -> Bool {
        CFEqual(lhs, rhs)
    }
}

@MainActor
protocol TextPasteboard: AnyObject {
    var changeCount: Int { get }

    @discardableResult
    func clearContents() -> Int

    func setString(
        _ string: String,
        forType dataType: NSPasteboard.PasteboardType
    ) -> Bool

    func string(forType dataType: NSPasteboard.PasteboardType) -> String?
}

extension NSPasteboard: TextPasteboard {}

@MainActor
final class FocusedTextPasteService {
    enum TargetCapture {
        case editable(FocusedTarget)
        case accessibilityUnavailable
        case unavailable(String)
    }

    struct FocusedTarget {
        fileprivate let element: AXUIElement
        fileprivate let processIdentifier: pid_t
    }

    private let accessibility: any AccessibilityElementClient
    private let pasteboard: any TextPasteboard
    private let postCommandV: @MainActor (pid_t) -> Bool

    init() {
        accessibility = SystemAccessibilityElementClient()
        pasteboard = NSPasteboard.general
        postCommandV = Self.postCommandV
    }

    init(
        accessibility: any AccessibilityElementClient,
        pasteboard: any TextPasteboard,
        postCommandV: @escaping @MainActor (pid_t) -> Bool
    ) {
        self.accessibility = accessibility
        self.pasteboard = pasteboard
        self.postCommandV = postCommandV
    }

    func captureTarget() -> TargetCapture {
        guard accessibility.isTrusted(prompt: false) else {
            return .accessibilityUnavailable
        }
        guard let element = accessibility.focusedElement(),
              let processIdentifier = accessibility.processIdentifier(for: element),
              processIdentifier != ProcessInfo.processInfo.processIdentifier,
              isEditable(element)
        else {
            return .unavailable("Copied — focus an editable chat box to paste.")
        }
        return .editable(
            FocusedTarget(
                element: element,
                processIdentifier: processIdentifier
            )
        )
    }

    func requestAccessibilityPermission() {
        _ = accessibility.isTrusted(prompt: true)
    }

    func deliver(
        _ content: String,
        to capture: TargetCapture
    ) async throws -> PasteDeliveryOutcome {
        pasteboard.clearContents()
        guard pasteboard.setString(content, forType: .string) else {
            throw PasteDeliveryError.clipboardUnavailable
        }
        let verifiedChangeCount = pasteboard.changeCount

        let target: FocusedTarget
        switch capture {
        case let .editable(capturedTarget):
            target = capturedTarget
        case .accessibilityUnavailable:
            return .copiedOnly(
                "Copied — allow Accessibility access to paste automatically."
            )
        case let .unavailable(message):
            return .copiedOnly(message)
        }

        guard targetIsStillFocused(target) else {
            return .copiedOnly(
                "Copied — the focused chat box changed before paste."
            )
        }
        if await insertAtFocusedSelection(content, target: target) {
            return .pasted
        }

        // Give the pasteboard change a moment to become visible to the target
        // process while the non-activating overlay leaves its focus untouched.
        try? await Task.sleep(for: .milliseconds(45))

        guard pasteboard.changeCount == verifiedChangeCount,
              pasteboard.string(forType: .string) == content else {
            throw PasteDeliveryError.clipboardChanged
        }
        // Keep the exact AX target check as the final operation before
        // posting, minimizing the remaining same-process focus race.
        guard targetIsStillFocused(target) else {
            return .copiedOnly(
                "Copied — the focused chat box changed before paste."
            )
        }
        guard postCommandV(target.processIdentifier) else {
            throw PasteDeliveryError.keyboardEventUnavailable
        }
        return .pasted
    }

    private func targetIsStillFocused(_ target: FocusedTarget) -> Bool {
        guard let current = accessibility.focusedElement(),
              accessibility.processIdentifier(for: current)
                == target.processIdentifier,
              accessibility.elementsAreEqual(current, target.element),
              isEditable(current)
        else {
            return false
        }
        return true
    }

    private func insertAtFocusedSelection(
        _ content: String,
        target: FocusedTarget
    ) async -> Bool {
        let attribute = kAXSelectedTextAttribute as CFString
        guard accessibility.isAttributeSettable(attribute, on: target.element)
        else {
            return false
        }
        var result = accessibility.setAttribute(
            attribute,
            to: content as CFString,
            on: target.element
        )
        if result == .cannotComplete {
            try? await Task.sleep(for: .milliseconds(20))
            guard targetIsStillFocused(target) else { return false }
            result = accessibility.setAttribute(
                attribute,
                to: content as CFString,
                on: target.element
            )
        }
        return result == .success
    }

    private func isEditable(_ element: AXUIElement) -> Bool {
        let role = accessibility.stringAttribute(
            kAXRoleAttribute as CFString,
            from: element
        )
        let subrole = accessibility.stringAttribute(
            kAXSubroleAttribute as CFString,
            from: element
        )
        guard !["AXSecureTextField", "AXSearchField"].contains(subrole) else {
            return false
        }

        let allowedRoles: Set<String> = [
            kAXTextAreaRole as String,
            kAXTextFieldRole as String,
        ]

        if let enabled = accessibility.boolAttribute(
            kAXEnabledAttribute as CFString,
            from: element
        ),
           !enabled
        {
            return false
        }

        let selectedTextIsSettable = accessibility.isAttributeSettable(
            kAXSelectedTextAttribute as CFString,
            on: element
        )
        if selectedTextIsSettable {
            return true
        }
        guard let role, allowedRoles.contains(role) else { return false }
        return accessibility.isAttributeSettable(
            kAXValueAttribute as CFString,
            on: element
        )
    }

    private static func postCommandV(to processIdentifier: pid_t) -> Bool {
        guard let source = CGEventSource(stateID: .hidSystemState),
              let keyDown = CGEvent(
                keyboardEventSource: source,
                virtualKey: 0x09,
                keyDown: true
              ),
              let keyUp = CGEvent(
                keyboardEventSource: source,
                virtualKey: 0x09,
                keyDown: false
              )
        else {
            return false
        }
        keyDown.flags = .maskCommand
        keyUp.flags = .maskCommand
        keyDown.postToPid(processIdentifier)
        keyUp.postToPid(processIdentifier)
        return true
    }
}
