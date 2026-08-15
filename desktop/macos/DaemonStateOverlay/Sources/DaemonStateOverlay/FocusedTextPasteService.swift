import AppKit
import ApplicationServices

enum PasteDeliveryOutcome: Equatable {
    /// Accessibility insertion was confirmed by exact full-value readback when
    /// the capture requested strict verification.
    case insertedWithAccessibility
    /// A provider-seeded identity marker was selected in the exact verified
    /// editor and replaced through targeted Accessibility mutation. A harmless
    /// type/delete handshake then proves the web editor synchronized its own
    /// input state, and exact full readback confirms the final draft.
    case markerReplacedWithVerifiedInputSync
    /// Accessibility acknowledged the set, but exact readback did not confirm
    /// it. A Command-V fallback would risk duplicating content, so none is sent.
    case accessibilityInsertionUnverified(String)
    /// macOS accepted a Command-V event for the verified target process. The
    /// destination editor cannot be read back reliably, so this is requested,
    /// not verified, delivery.
    case commandVDispatched
    case notPasted(String)
}

enum EditableTargetContentState: Equatable {
    case empty
    case nonempty
    case unknown
}

struct FrontmostApplicationIdentity: Equatable {
    let processIdentifier: pid_t
    let bundleIdentifier: String?
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
            return "The clipboard changed before automatic paste. Click the control to try again."
        case .keyboardEventUnavailable:
            return "macOS could not create the automatic paste command."
        }
    }
}

@MainActor
protocol AccessibilityElementClient: AnyObject {
    func isTrusted(prompt: Bool) -> Bool
    func frontmostApplication() -> FrontmostApplicationIdentity?
    func focusedElement() -> AXUIElement?
    func applicationElement(for processIdentifier: pid_t) -> AXUIElement?
    func processIdentifier(for element: AXUIElement) -> pid_t?
    func elementAttribute(
        _ attribute: CFString,
        from element: AXUIElement
    ) -> AXUIElement?
    func elementArrayAttribute(
        _ attribute: CFString,
        from element: AXUIElement,
        maximumCount: Int
    ) -> [AXUIElement]?
    func stringAttribute(
        _ attribute: CFString,
        from element: AXUIElement
    ) -> String?
    func stringArrayAttribute(
        _ attribute: CFString,
        from element: AXUIElement
    ) -> [String]?
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
    init() {
        _ = AXUIElementSetMessagingTimeout(
            AXUIElementCreateSystemWide(),
            0.35
        )
    }

    func isTrusted(prompt: Bool) -> Bool {
        let key = kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String
        let options = [key: prompt] as CFDictionary
        return AXIsProcessTrustedWithOptions(options)
    }

    func frontmostApplication() -> FrontmostApplicationIdentity? {
        guard let application = NSWorkspace.shared.frontmostApplication else {
            return nil
        }
        return FrontmostApplicationIdentity(
            processIdentifier: application.processIdentifier,
            bundleIdentifier: application.bundleIdentifier
        )
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

    func applicationElement(for processIdentifier: pid_t) -> AXUIElement? {
        AXUIElementCreateApplication(processIdentifier)
    }

    func processIdentifier(for element: AXUIElement) -> pid_t? {
        var processIdentifier: pid_t = 0
        guard AXUIElementGetPid(element, &processIdentifier) == .success else {
            return nil
        }
        return processIdentifier
    }

    func elementAttribute(
        _ attribute: CFString,
        from element: AXUIElement
    ) -> AXUIElement? {
        var value: CFTypeRef?
        guard AXUIElementCopyAttributeValue(element, attribute, &value) == .success,
              let value,
              CFGetTypeID(value) == AXUIElementGetTypeID()
        else {
            return nil
        }
        return (value as! AXUIElement)
    }

    func elementArrayAttribute(
        _ attribute: CFString,
        from element: AXUIElement,
        maximumCount: Int
    ) -> [AXUIElement]? {
        guard maximumCount >= 0 else { return nil }
        var count: CFIndex = 0
        let countResult = AXUIElementGetAttributeValueCount(
            element,
            attribute,
            &count
        )
        if countResult == .attributeUnsupported || countResult == .noValue {
            return []
        }
        guard countResult == .success,
              count >= 0,
              count <= maximumCount
        else {
            return nil
        }
        if count == 0 { return [] }
        var values: CFArray?
        guard AXUIElementCopyAttributeValues(
            element,
            attribute,
            0,
            count,
            &values
        ) == .success,
        let elements = values as? [AXUIElement]
        else {
            return nil
        }
        return elements
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

    func stringArrayAttribute(
        _ attribute: CFString,
        from element: AXUIElement
    ) -> [String]? {
        var value: CFTypeRef?
        guard AXUIElementCopyAttributeValue(element, attribute, &value) == .success
        else {
            return nil
        }
        return value as? [String]
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
        case application(ApplicationTarget)
        case accessibilityUnavailable
        case unavailable(String)
    }

    struct FocusedTarget {
        fileprivate let element: AXUIElement
        fileprivate let processIdentifier: pid_t
        fileprivate let requiresExactInsertionReadback: Bool
        fileprivate let expectedInitialValue: String?
        fileprivate let requiresOpenCodeChatIdentity: Bool
    }

    struct ApplicationTarget {
        fileprivate let processIdentifier: pid_t
        fileprivate let requiresMissingFocusedElement: Bool
    }

    private let accessibility: any AccessibilityElementClient
    private let pasteboard: any TextPasteboard
    private let postCommandV: @MainActor (pid_t) -> Bool
    private let postSpace: @MainActor (pid_t) -> Bool
    private let postDeleteBackward: @MainActor (pid_t) -> Bool

    init() {
        accessibility = SystemAccessibilityElementClient()
        pasteboard = NSPasteboard.general
        postCommandV = Self.postCommandV
        postSpace = Self.postSpace
        postDeleteBackward = Self.postDeleteBackward
    }

    init(
        accessibility: any AccessibilityElementClient,
        pasteboard: any TextPasteboard,
        postCommandV: @escaping @MainActor (pid_t) -> Bool,
        postSpace: @escaping @MainActor (pid_t) -> Bool = { _ in false },
        postDeleteBackward: @escaping @MainActor (pid_t) -> Bool = { _ in false }
    ) {
        self.accessibility = accessibility
        self.pasteboard = pasteboard
        self.postCommandV = postCommandV
        self.postSpace = postSpace
        self.postDeleteBackward = postDeleteBackward
    }

    func captureTarget(
        expectedBundleIdentifiers: Set<String> = [],
        allowNonEditableApplicationFallback: Bool = true,
        allowMissingFocusedElementFallback: Bool = true,
        requireMissingFocusedElementForApplicationPaste: Bool = false,
        requireExactInsertionReadback: Bool = false,
        discoverEditableWithExactValue requiredEditableValue: String? = nil,
        discoveryDeadline: ContinuousClock.Instant? = nil
    ) -> TargetCapture {
        guard accessibility.isTrusted(prompt: false) else {
            return .accessibilityUnavailable
        }
        let ownProcessIdentifier = ProcessInfo.processInfo.processIdentifier
        guard let frontmostApplication = accessibility.frontmostApplication(),
              frontmostApplication.processIdentifier != ownProcessIdentifier
        else {
            return .unavailable(
                "Automatic paste could not find a target chat box."
            )
        }
        if !expectedBundleIdentifiers.isEmpty {
            let bundleIdentifier = frontmostApplication.bundleIdentifier ?? ""
            guard expectedBundleIdentifiers.contains(bundleIdentifier) else {
                return .unavailable(
                    "The selected AI desktop app is not focused yet."
                )
            }
        }
        if let requiredEditableValue {
            guard !requiredEditableValue.isEmpty else {
                return .unavailable(
                    "The composer identity marker is invalid."
                )
            }
            guard let element = uniqueEditableElement(
                in: frontmostApplication.processIdentifier,
                withExactValue: requiredEditableValue,
                requireOpenCodeChatIdentity: (
                    expectedBundleIdentifiers == ["ai.opencode.desktop"]
                ),
                deadline: discoveryDeadline
            ) else {
                return .unavailable(
                    "The selected AI desktop app has not exposed its verified composer yet."
                )
            }
            guard focusAndVerify(
                element,
                processIdentifier: frontmostApplication.processIdentifier,
                deadline: discoveryDeadline
            ) else {
                return .unavailable(
                    "The verified composer is not focused yet."
                )
            }
            return .editable(
                FocusedTarget(
                    element: element,
                    processIdentifier: frontmostApplication.processIdentifier,
                    requiresExactInsertionReadback: true,
                    expectedInitialValue: requiredEditableValue,
                    requiresOpenCodeChatIdentity: (
                        expectedBundleIdentifiers == ["ai.opencode.desktop"]
                    )
                )
            )
        }
        if let element = accessibility.focusedElement(),
           let processIdentifier = accessibility.processIdentifier(for: element),
           processIdentifier == frontmostApplication.processIdentifier {
            guard !isProtectedPasteTarget(element) else {
                return .unavailable(
                    "Automatic paste is disabled for secure and search fields."
                )
            }
            if isEditable(element) {
                return .editable(
                    FocusedTarget(
                        element: element,
                        processIdentifier: processIdentifier,
                        requiresExactInsertionReadback: (
                            requireExactInsertionReadback
                        ),
                        expectedInitialValue: nil,
                        requiresOpenCodeChatIdentity: false
                    )
                )
            }
            if allowNonEditableApplicationFallback {
                return .application(
                    ApplicationTarget(
                        processIdentifier: processIdentifier,
                        requiresMissingFocusedElement: (
                            requireMissingFocusedElementForApplicationPaste
                        )
                    )
                )
            }
            return .unavailable(
                "The focused control is not an editable composer."
            )
        }

        if allowMissingFocusedElementFallback {
            return .application(
                ApplicationTarget(
                    processIdentifier: frontmostApplication.processIdentifier,
                    requiresMissingFocusedElement: (
                        requireMissingFocusedElementForApplicationPaste
                    )
                )
            )
        }
        return .unavailable(
            "The selected AI desktop app has not exposed its composer yet."
        )
    }

    func requestAccessibilityPermission() {
        _ = accessibility.isTrusted(prompt: true)
    }

    func capturesSameEditableTarget(
        _ lhs: TargetCapture,
        _ rhs: TargetCapture
    ) -> Bool {
        guard case let .editable(lhsTarget) = lhs,
              case let .editable(rhsTarget) = rhs,
              lhsTarget.processIdentifier == rhsTarget.processIdentifier
        else {
            return false
        }
        return accessibility.elementsAreEqual(
            lhsTarget.element,
            rhsTarget.element
        )
    }

    func editableTargetContentState(
        _ capture: TargetCapture
    ) -> EditableTargetContentState {
        guard case let .editable(target) = capture else { return .unknown }
        // AXValue is the authoritative full editor value. AXSelectedText may
        // be empty merely because there is no selection, so it cannot prove
        // that the whole draft is empty.
        guard let value = accessibility.stringAttribute(
            kAXValueAttribute as CFString,
            from: target.element
        ) else {
            return .unknown
        }
        return value.isEmpty ? .empty : .nonempty
    }

    func editableTargetHasExactContent(
        _ capture: TargetCapture,
        expected: String
    ) -> Bool {
        guard case let .editable(target) = capture else { return false }
        return accessibility.stringAttribute(
            kAXValueAttribute as CFString,
            from: target.element
        ) == expected
    }

    func deliver(
        _ content: String,
        to capture: TargetCapture
    ) async throws -> PasteDeliveryOutcome {
        switch capture {
        case .editable(_), .application(_):
            break
        case .accessibilityUnavailable:
            return .notPasted(
                "Allow Accessibility access to paste automatically."
            )
        case let .unavailable(message):
            return .notPasted(message)
        }

        pasteboard.clearContents()
        guard pasteboard.setString(content, forType: .string) else {
            throw PasteDeliveryError.clipboardUnavailable
        }
        let verifiedChangeCount = pasteboard.changeCount

        switch capture {
        case let .editable(capturedTarget):
            guard targetIsStillFocused(capturedTarget) else {
                return .notPasted(
                    "The target chat box changed before automatic paste."
                )
            }
            let insertion: AccessibilityInsertionAttempt
            if let expectedInitialValue = capturedTarget.expectedInitialValue {
                guard accessibility.stringAttribute(
                    kAXValueAttribute as CFString,
                    from: capturedTarget.element
                ) == expectedInitialValue else {
                    return .notPasted(
                        "The verified composer marker changed before automatic paste."
                    )
                }
                insertion = await replaceMarkerWithVerifiedInputSync(
                    expectedInitialValue,
                    with: content,
                    target: capturedTarget
                )
            } else {
                insertion = await insertAtFocusedSelection(
                    content,
                    target: capturedTarget
                )
            }
            switch insertion {
            case .verified:
                return capturedTarget.expectedInitialValue == nil
                    ? .insertedWithAccessibility
                    : .markerReplacedWithVerifiedInputSync
            case .acknowledgedButUnverified:
                return .accessibilityInsertionUnverified(
                    "macOS acknowledged the context insertion, but the editor "
                        + "did not expose the exact inserted value for verification."
                )
            case .notPerformed:
                break
            }
            if capturedTarget.expectedInitialValue != nil {
                return .notPasted(
                    "The verified chat composer did not allow a safe marker replacement."
                )
            }
            return try await pasteWithCommandV(
                content,
                verifiedChangeCount: verifiedChangeCount,
                processIdentifier: capturedTarget.processIdentifier,
                exactTarget: capturedTarget
            )
        case let .application(applicationTarget):
            return try await pasteWithCommandV(
                content,
                verifiedChangeCount: verifiedChangeCount,
                processIdentifier: applicationTarget.processIdentifier,
                exactTarget: nil,
                requiresMissingFocusedElement: (
                    applicationTarget.requiresMissingFocusedElement
                )
            )
        case .accessibilityUnavailable, .unavailable:
            preconditionFailure("Unavailable targets return before clipboard delivery")
        }
    }

    private func pasteWithCommandV(
        _ content: String,
        verifiedChangeCount: Int,
        processIdentifier: pid_t,
        exactTarget: FocusedTarget?,
        requiresMissingFocusedElement: Bool = false
    ) async throws -> PasteDeliveryOutcome {
        // Give the pasteboard change a moment to become visible to the target
        // process while the non-activating overlay leaves its focus untouched.
        try? await Task.sleep(for: .milliseconds(45))

        guard pasteboard.changeCount == verifiedChangeCount,
              pasteboard.string(forType: .string) == content else {
            throw PasteDeliveryError.clipboardChanged
        }
        if let exactTarget {
            guard targetIsStillFocused(exactTarget) else {
                return .notPasted(
                    "The target chat box changed before automatic paste."
                )
            }
        } else {
            guard applicationTargetIsStillSafe(
                processIdentifier,
                requiresMissingFocusedElement: requiresMissingFocusedElement
            ) else {
                return .notPasted(
                    "The target app changed before automatic paste."
                )
            }
        }
        guard postCommandV(processIdentifier) else {
            throw PasteDeliveryError.keyboardEventUnavailable
        }
        return .commandVDispatched
    }

    private func applicationTargetIsStillSafe(
        _ processIdentifier: pid_t,
        requiresMissingFocusedElement: Bool
    ) -> Bool {
        guard accessibility.frontmostApplication()?.processIdentifier
                == processIdentifier
        else {
            return false
        }
        guard !requiresMissingFocusedElement
                || accessibility.focusedElement() == nil
        else {
            // App-level Command-V is reserved for Electron/web editors that
            // publish no focused AX element. If macOS exposes any element, we
            // must identify and validate an editable target instead of
            // guessing that the current control is a composer.
            return false
        }
        // Electron/web chat editors do not always publish an AX-focused
        // element even while they still own keyboard focus. The strict
        // one-shot continuation mode requires nil focus; the user-initiated
        // floating control retains its captured, frontmost-app fallback.
        return true
    }

    private func targetIsStillFocused(_ target: FocusedTarget) -> Bool {
        guard let current = accessibility.focusedElement(),
              accessibility.processIdentifier(for: current)
                == target.processIdentifier,
              accessibility.elementsAreEqual(current, target.element),
              isEditable(current),
              !target.requiresOpenCodeChatIdentity
                || isVerifiedOpenCodeChatComposer(
                    current,
                    deadline: nil
                )
        else {
            return false
        }
        return true
    }

    private func uniqueEditableElement(
        in processIdentifier: pid_t,
        withExactValue expectedValue: String,
        requireOpenCodeChatIdentity: Bool,
        deadline: ContinuousClock.Instant?
    ) -> AXUIElement? {
        var matches: [AXUIElement] = []
        var deadlineExpired = false
        func appendMatchIfNeeded(_ element: AXUIElement) {
            guard deadlineAllowsWork(deadline) else {
                deadlineExpired = true
                return
            }
            guard accessibility.processIdentifier(for: element)
                    == processIdentifier,
                  deadlineAllowsWork(deadline),
                  isEditable(element, deadline: deadline),
                  deadlineAllowsWork(deadline),
                  accessibility.stringAttribute(
                      kAXValueAttribute as CFString,
                      from: element
                  ) == expectedValue,
                  deadlineAllowsWork(deadline),
                  !requireOpenCodeChatIdentity
                    || isVerifiedOpenCodeChatComposer(
                        element,
                        deadline: deadline
                    ),
                  !matches.contains(where: {
                      accessibility.elementsAreEqual($0, element)
                  })
            else {
                return
            }
            matches.append(element)
        }

        guard deadlineAllowsWork(deadline),
              let application = accessibility.applicationElement(
            for: processIdentifier
        ), deadlineAllowsWork(deadline),
        let focusedWindow = accessibility.elementAttribute(
            kAXFocusedWindowAttribute as CFString,
            from: application
        ), deadlineAllowsWork(deadline),
        accessibility.processIdentifier(for: focusedWindow)
            == processIdentifier
        else {
            return nil
        }

        var pending: [(AXUIElement, Int)] = [(focusedWindow, 0)]
        var visited = Set<AXUIElement>()
        var index = 0
        let maximumDepth = 32
        let maximumElements = 2_048
        while index < pending.count,
              visited.count < maximumElements,
              matches.count < 2,
              deadlineAllowsWork(deadline)
        {
            let (element, depth) = pending[index]
            index += 1
            guard visited.insert(element).inserted else { continue }
            appendMatchIfNeeded(element)
            if deadlineExpired { return nil }
            guard depth < maximumDepth else { continue }
            let remainingCapacity = maximumElements - pending.count
            guard remainingCapacity >= 0,
                  let children = accessibility.elementArrayAttribute(
                      kAXChildrenAttribute as CFString,
                      from: element,
                      maximumCount: min(256, remainingCapacity)
                  )
            else {
                return nil
            }
            guard deadlineAllowsWork(deadline) else { return nil }
            pending.append(contentsOf: children.map { ($0, depth + 1) })
        }
        guard !deadlineExpired,
              deadlineAllowsWork(deadline),
              index >= pending.count
        else {
            return nil
        }
        return matches.count == 1 ? matches[0] : nil
    }

    private func isVerifiedOpenCodeChatComposer(
        _ element: AXUIElement,
        deadline: ContinuousClock.Instant?
    ) -> Bool {
        guard deadlineAllowsWork(deadline) else { return false }
        let role = accessibility.stringAttribute(
            kAXRoleAttribute as CFString,
            from: element
        )
        guard role == kAXTextAreaRole as String
                || role == kAXTextFieldRole as String
        else {
            return false
        }
        guard deadlineAllowsWork(deadline) else { return false }
        let accessibleNames = [
            accessibility.stringAttribute(
                kAXDescriptionAttribute as CFString,
                from: element
            ),
            accessibility.stringAttribute(
                kAXTitleAttribute as CFString,
                from: element
            ),
            accessibility.stringAttribute(
                kAXHelpAttribute as CFString,
                from: element
            ),
        ].compactMap { value in
            value?.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        }
        guard deadlineAllowsWork(deadline) else { return false }
        guard !accessibleNames.contains(where: {
            $0.contains("terminal input") || $0.contains("shell command")
        }) else {
            return false
        }
        let hasKnownNormalPromptName = accessibleNames.contains(where: {
            $0.hasPrefix("ask anything")
                || $0.hasPrefix("summarize comment")
        })
        guard deadlineAllowsWork(deadline) else { return false }
        let domClasses = Set(
            accessibility.stringArrayAttribute(
                "AXDOMClassList" as CFString,
                from: element
            ) ?? []
        )
        guard !domClasses.contains("font-mono!") else { return false }
        let normalPromptClassSignature: Set<String> = [
            "select-text",
            "w-full",
            "text-14-regular",
            "whitespace-pre-wrap",
        ]
        let hasNormalPromptClassSignature = normalPromptClassSignature
            .isSubset(of: domClasses)
        return hasKnownNormalPromptName || hasNormalPromptClassSignature
    }

    private func focusAndVerify(
        _ element: AXUIElement,
        processIdentifier: pid_t,
        deadline: ContinuousClock.Instant?
    ) -> Bool {
        guard deadlineAllowsWork(deadline) else { return false }
        if let focused = accessibility.focusedElement(),
           accessibility.processIdentifier(for: focused) == processIdentifier,
           accessibility.elementsAreEqual(focused, element)
        {
            return true
        }
        let attribute = kAXFocusedAttribute as CFString
        guard deadlineAllowsWork(deadline),
              accessibility.isAttributeSettable(attribute, on: element),
              deadlineAllowsWork(deadline),
              accessibility.setAttribute(
                  attribute,
                  to: kCFBooleanTrue,
                  on: element
              ) == .success,
              deadlineAllowsWork(deadline),
              let focused = accessibility.focusedElement(),
              accessibility.processIdentifier(for: focused) == processIdentifier,
              accessibility.elementsAreEqual(focused, element)
        else {
            return false
        }
        return true
    }

    private func deadlineAllowsWork(
        _ deadline: ContinuousClock.Instant?
    ) -> Bool {
        guard let deadline else { return true }
        return ContinuousClock().now < deadline
    }

    private enum AccessibilityInsertionAttempt {
        case verified
        case acknowledgedButUnverified
        case notPerformed
    }

    private func insertAtFocusedSelection(
        _ content: String,
        target: FocusedTarget
    ) async -> AccessibilityInsertionAttempt {
        let attribute = kAXSelectedTextAttribute as CFString
        guard accessibility.isAttributeSettable(attribute, on: target.element)
        else {
            return .notPerformed
        }
        var result = accessibility.setAttribute(
            attribute,
            to: content as CFString,
            on: target.element
        )
        if result == .cannotComplete {
            try? await Task.sleep(for: .milliseconds(20))
            guard targetIsStillFocused(target) else { return .notPerformed }
            result = accessibility.setAttribute(
                attribute,
                to: content as CFString,
                on: target.element
            )
        }
        guard result == .success else { return .notPerformed }
        guard target.requiresExactInsertionReadback else { return .verified }

        // AX set success only acknowledges the operation. In strict one-shot
        // mode, require an exact full-value readback before claiming that the
        // context is loaded. If readback stays nil or differs, do not send
        // Command-V because the set may already have inserted the content.
        // Chromium can publish the new accessibility value a few frames after
        // the editor updates. Keep this bounded, but allow enough time to avoid
        // a false failure on a busy UI.
        for attempt in 0..<10 {
            guard targetIsStillFocused(target) else {
                return .acknowledgedButUnverified
            }
            if accessibility.stringAttribute(
                kAXValueAttribute as CFString,
                from: target.element
            ) == content {
                return .verified
            }
            if attempt < 9 {
                try? await Task.sleep(for: .milliseconds(50))
            }
        }
        return .acknowledgedButUnverified
    }

    private func replaceMarkerWithVerifiedInputSync(
        _ expectedValue: String,
        with content: String,
        target: FocusedTarget
    ) async -> AccessibilityInsertionAttempt {
        guard targetIsStillFocused(target),
              accessibility.stringAttribute(
                  kAXValueAttribute as CFString,
                  from: target.element
              ) == expectedValue
        else {
            return .notPerformed
        }

        let selectedRangeAttribute = kAXSelectedTextRangeAttribute as CFString
        let selectedTextAttribute = kAXSelectedTextAttribute as CFString
        let valueAttribute = kAXValueAttribute as CFString
        guard accessibility.isAttributeSettable(
            selectedRangeAttribute,
            on: target.element
        ), accessibility.isAttributeSettable(
            valueAttribute,
            on: target.element
        ) else {
            return .notPerformed
        }

        // The full context is written only to the attested AX element. A
        // PID-scoped Command-V could race a focus change and paste material
        // context into OpenCode's terminal, so strict delivery never uses it.
        // Chromium implements AXValue replacement for contenteditables; its
        // selected-text replacement action is not implemented in the renderer.
        guard accessibility.setAttribute(
            valueAttribute,
            to: content as CFString,
            on: target.element
        ) == .success else {
            return .notPerformed
        }
        guard await exactReadbackResult(content, target: target) == .verified
        else {
            return .acknowledgedButUnverified
        }

        // Chromium Accessibility mutation can update rendered text without
        // firing OpenCode's input handler. Append one harmless space through a
        // real key event, prove it landed in this exact composer, then select
        // and delete only that space. Both input events must be reflected in
        // AXValue, proving OpenCode synchronized its internal prompt state.
        var cursorRange = CFRange(
            location: content.utf16.count,
            length: 0
        )
        guard let cursorRangeValue = AXValueCreate(.cfRange, &cursorRange),
              accessibility.setAttribute(
                  selectedRangeAttribute,
                  to: cursorRangeValue,
                  on: target.element
              ) == .success,
              targetIsStillFocused(target),
              accessibility.stringAttribute(
                  kAXValueAttribute as CFString,
                  from: target.element
              ) == content,
              postSpace(target.processIdentifier)
        else {
            return .acknowledgedButUnverified
        }
        let contentWithSentinel = content + " "
        guard await exactReadbackResult(
            contentWithSentinel,
            target: target
        ) == .verified else {
            return .acknowledgedButUnverified
        }

        var sentinelRange = CFRange(
            location: content.utf16.count,
            length: 1
        )
        guard let sentinelRangeValue = AXValueCreate(.cfRange, &sentinelRange),
              accessibility.setAttribute(
                  selectedRangeAttribute,
                  to: sentinelRangeValue,
                  on: target.element
              ) == .success,
              targetIsStillFocused(target),
              accessibility.stringAttribute(
                  kAXValueAttribute as CFString,
                  from: target.element
              ) == contentWithSentinel,
              accessibility.stringAttribute(
                  selectedTextAttribute,
                  from: target.element
              ) == " ",
              postDeleteBackward(target.processIdentifier)
        else {
            return .acknowledgedButUnverified
        }
        return await exactReadbackResult(content, target: target)
    }

    private func exactReadbackResult(
        _ expectedValue: String,
        target: FocusedTarget
    ) async -> AccessibilityInsertionAttempt {
        // OpenCode's paste/input handler and Chromium's AX tree can settle on
        // different frames. Bound the wait to under half a second.
        for attempt in 0..<10 {
            guard targetIsStillFocused(target) else {
                return .acknowledgedButUnverified
            }
            if accessibility.stringAttribute(
                kAXValueAttribute as CFString,
                from: target.element
            ) == expectedValue {
                return .verified
            }
            if attempt < 9 {
                try? await Task.sleep(for: .milliseconds(50))
            }
        }
        return .acknowledgedButUnverified
    }

    private func isEditable(
        _ element: AXUIElement,
        deadline: ContinuousClock.Instant? = nil
    ) -> Bool {
        guard deadlineAllowsWork(deadline) else { return false }
        let role = accessibility.stringAttribute(
            kAXRoleAttribute as CFString,
            from: element
        )
        guard deadlineAllowsWork(deadline),
              !isProtectedPasteTarget(element, deadline: deadline)
        else {
            return false
        }

        let allowedRoles: Set<String> = [
            kAXTextAreaRole as String,
            kAXTextFieldRole as String,
        ]

        guard deadlineAllowsWork(deadline) else { return false }
        if let enabled = accessibility.boolAttribute(
            kAXEnabledAttribute as CFString,
            from: element
        ),
           !enabled
        {
            return false
        }

        guard deadlineAllowsWork(deadline) else { return false }
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

    private func isProtectedPasteTarget(
        _ element: AXUIElement,
        deadline: ContinuousClock.Instant? = nil
    ) -> Bool {
        guard deadlineAllowsWork(deadline) else { return true }
        let subrole = accessibility.stringAttribute(
            kAXSubroleAttribute as CFString,
            from: element
        )
        return ["AXSecureTextField", "AXSearchField"].contains(subrole)
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

    private static func postSpace(to processIdentifier: pid_t) -> Bool {
        postUnmodifiedKey(0x31, to: processIdentifier)
    }

    private static func postDeleteBackward(to processIdentifier: pid_t) -> Bool {
        postUnmodifiedKey(0x33, to: processIdentifier)
    }

    private static func postUnmodifiedKey(
        _ keyCode: CGKeyCode,
        to processIdentifier: pid_t
    ) -> Bool {
        guard let source = CGEventSource(stateID: .hidSystemState),
              let keyDown = CGEvent(
                  keyboardEventSource: source,
                  virtualKey: keyCode,
                  keyDown: true
              ),
              let keyUp = CGEvent(
                  keyboardEventSource: source,
                  virtualKey: keyCode,
                  keyDown: false
              )
        else {
            return false
        }
        keyDown.postToPid(processIdentifier)
        keyUp.postToPid(processIdentifier)
        return true
    }
}
