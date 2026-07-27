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

    func captureTarget() -> TargetCapture {
        guard accessibilityIsTrusted(prompt: false) else {
            return .accessibilityUnavailable
        }
        guard let element = focusedElement(),
              let processIdentifier = processIdentifier(for: element),
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
        _ = accessibilityIsTrusted(prompt: true)
    }

    func deliver(
        _ content: String,
        to capture: TargetCapture
    ) async throws -> PasteDeliveryOutcome {
        let pasteboard = NSPasteboard.general
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

        // Give the pasteboard change a moment to become visible to the target
        // process while the non-activating overlay leaves its focus untouched.
        try? await Task.sleep(for: .milliseconds(45))

        guard pasteboard.changeCount == verifiedChangeCount,
              pasteboard.string(forType: .string) == content else {
            throw PasteDeliveryError.clipboardChanged
        }
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
            throw PasteDeliveryError.keyboardEventUnavailable
        }

        keyDown.flags = .maskCommand
        keyUp.flags = .maskCommand
        // Keep the exact AX target check as the final operation before
        // posting, minimizing the remaining same-process focus race.
        guard targetIsStillFocused(target) else {
            return .copiedOnly(
                "Copied — the focused chat box changed before paste."
            )
        }
        keyDown.postToPid(target.processIdentifier)
        keyUp.postToPid(target.processIdentifier)
        return .pasted
    }

    private func accessibilityIsTrusted(prompt: Bool) -> Bool {
        let key = kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String
        let options = [key: prompt] as CFDictionary
        return AXIsProcessTrustedWithOptions(options)
    }

    private func focusedElement() -> AXUIElement? {
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

    private func processIdentifier(for element: AXUIElement) -> pid_t? {
        var processIdentifier: pid_t = 0
        guard AXUIElementGetPid(element, &processIdentifier) == .success else {
            return nil
        }
        return processIdentifier
    }

    private func targetIsStillFocused(_ target: FocusedTarget) -> Bool {
        guard let current = focusedElement(),
              processIdentifier(for: current) == target.processIdentifier,
              CFEqual(current, target.element),
              isEditable(current)
        else {
            return false
        }
        return true
    }

    private func isEditable(_ element: AXUIElement) -> Bool {
        let role = stringAttribute(kAXRoleAttribute as CFString, from: element)
        let subrole = stringAttribute(kAXSubroleAttribute as CFString, from: element)
        guard !["AXSecureTextField", "AXSearchField"].contains(subrole) else {
            return false
        }

        let allowedRoles: Set<String> = [
            kAXTextAreaRole as String,
            kAXTextFieldRole as String,
        ]
        guard let role, allowedRoles.contains(role) else {
            return false
        }

        if let enabled = boolAttribute(kAXEnabledAttribute as CFString, from: element),
           !enabled
        {
            return false
        }

        var valueIsSettable = DarwinBoolean(false)
        guard AXUIElementIsAttributeSettable(
            element,
            kAXValueAttribute as CFString,
            &valueIsSettable
        ) == .success
        else {
            return false
        }
        return valueIsSettable.boolValue
    }

    private func stringAttribute(
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

    private func boolAttribute(
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
}
