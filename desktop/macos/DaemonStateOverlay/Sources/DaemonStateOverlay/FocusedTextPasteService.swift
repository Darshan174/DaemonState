import AppKit
import ApplicationServices
import Darwin
import OSLog

enum PasteDeliveryOutcome: Equatable {
    /// Accessibility insertion was confirmed by exact full-value readback when
    /// the capture requested strict verification.
    case insertedWithAccessibility
    /// A provider-seeded identity marker was replaced through targeted
    /// Accessibility mutation. A harmless type/delete handshake then proves
    /// the web editor synchronized its own input state, and exact full readback
    /// confirms the final draft.
    case markerReplacedWithVerifiedInputSync
    /// A positively attested, initially empty OpenCode composer received the
    /// content through targeted Accessibility mutation, followed by the same
    /// input-state synchronization handshake and exact readback.
    case insertedIntoVerifiedEmptyComposerWithInputSync
    /// A stable, project-attested OpenCode composer already exposed content
    /// exactly matching the request.
    case alreadyPresentInVerifiedOpenCodeComposer
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
    let bundlePath: String?
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
    func frame(of element: AXUIElement) -> CGRect?
    func elementIsHitTestVisible(
        _ element: AXUIElement,
        at point: CGPoint,
        processIdentifier: pid_t
    ) -> Bool
    func rangeAttribute(
        _ attribute: CFString,
        from element: AXUIElement
    ) -> CFRange?
    func isAttributeSettable(
        _ attribute: CFString,
        on element: AXUIElement
    ) -> Bool
    func setAttribute(
        _ attribute: CFString,
        to value: CFTypeRef,
        on element: AXUIElement
    ) -> AXError
    func performAction(
        _ action: CFString,
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
            bundleIdentifier: application.bundleIdentifier,
            bundlePath: application.bundleURL?
                .standardizedFileURL.resolvingSymlinksInPath().path
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
        if let string = value as? String {
            return string
        }
        // Chromium exposes AXURL as a CFURL on some macOS releases and as a
        // string on others. Normalize both without weakening the caller's
        // exact pathname comparison.
        if attribute as String == kAXURLAttribute as String,
           let url = value as? URL
        {
            return url.absoluteString
        }
        return nil
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

    func frame(of element: AXUIElement) -> CGRect? {
        var positionValue: CFTypeRef?
        var sizeValue: CFTypeRef?
        guard AXUIElementCopyAttributeValue(
            element,
            kAXPositionAttribute as CFString,
            &positionValue
        ) == .success,
        AXUIElementCopyAttributeValue(
            element,
            kAXSizeAttribute as CFString,
            &sizeValue
        ) == .success,
        let positionValue,
        let sizeValue,
        CFGetTypeID(positionValue) == AXValueGetTypeID(),
        CFGetTypeID(sizeValue) == AXValueGetTypeID()
        else {
            return nil
        }
        var position = CGPoint.zero
        var size = CGSize.zero
        guard AXValueGetValue(
            positionValue as! AXValue,
            .cgPoint,
            &position
        ), AXValueGetValue(
            sizeValue as! AXValue,
            .cgSize,
            &size
        ) else {
            return nil
        }
        return CGRect(origin: position, size: size)
    }

    func elementIsHitTestVisible(
        _ element: AXUIElement,
        at point: CGPoint,
        processIdentifier: pid_t
    ) -> Bool {
        let application = AXUIElementCreateApplication(processIdentifier)
        var hitElement: AXUIElement?
        guard AXUIElementCopyElementAtPosition(
            application,
            Float(point.x),
            Float(point.y),
            &hitElement
        ) == .success,
        var current = hitElement
        else {
            return false
        }
        var visited: [AXUIElement] = []
        for _ in 0..<32 {
            if CFEqual(current, element) {
                return true
            }
            guard !visited.contains(where: { CFEqual($0, current) }) else {
                return false
            }
            visited.append(current)
            var parentValue: CFTypeRef?
            guard AXUIElementCopyAttributeValue(
                current,
                kAXParentAttribute as CFString,
                &parentValue
            ) == .success,
            let parentValue,
            CFGetTypeID(parentValue) == AXUIElementGetTypeID()
            else {
                return false
            }
            current = (parentValue as! AXUIElement)
        }
        return false
    }

    func rangeAttribute(
        _ attribute: CFString,
        from element: AXUIElement
    ) -> CFRange? {
        var value: CFTypeRef?
        guard AXUIElementCopyAttributeValue(
            element,
            attribute,
            &value
        ) == .success,
        let value,
        CFGetTypeID(value) == AXValueGetTypeID()
        else {
            return nil
        }
        var range = CFRange()
        guard AXValueGetValue(value as! AXValue, .cfRange, &range) else {
            return nil
        }
        return range
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

    func performAction(
        _ action: CFString,
        on element: AXUIElement
    ) -> AXError {
        AXUIElementPerformAction(element, action)
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
    private static let openCodeBundleIdentifier = "ai.opencode.desktop"
    private static let pasteLogger = Logger(
        subsystem: "com.daemonstate.overlay",
        category: "paste"
    )
    private static let openCodeRouteFailureMessage = (
        "OpenCode did not expose the requested active project and exactly "
            + "one verified empty chat composer in the captured window; "
            + "try the floating action again."
    )
    private static let openCodeRetainedDraftMessage = (
        "OpenCode exposed a different nonempty draft instead of a fresh "
            + "composer for the requested project, so DaemonState did not "
            + "overwrite it. Send or clear that draft, then try the floating "
            + "action again."
    )
    private static let openCodeLegacySyncResidueMessage = (
        "OpenCode retained the requested context with a leftover one-space "
            + "sync marker before its final line break. DaemonState did not "
            + "modify the draft or request a new session. Review or clear "
            + "the draft before trying again."
    )

    enum TargetCapture {
        case editable(FocusedTarget)
        case application(ApplicationTarget)
        case openCodeNewComposer(OpenCodeRouteTarget)
        case copyOnly(String)
        case accessibilityUnavailable
        case unavailable(String)
    }

    struct FocusedTarget {
        fileprivate let element: AXUIElement
        fileprivate let processIdentifier: pid_t
        fileprivate let requiresExactInsertionReadback: Bool
        fileprivate let expectedInitialValue: String?
        /// Chromium exposes a brand-new OpenCode contenteditable as either an
        /// empty string or one structural line feed. Keep that state distinct
        /// from a provider-supplied identity marker.
        fileprivate let expectedInitialValueIsEmptyComposer: Bool
        fileprivate let requiresOpenCodeChatIdentity: Bool
        /// Present only for the interactive floating OpenCode workflow. The
        /// strict marker-based one-shot helper intentionally leaves this nil.
        fileprivate let floatingOpenCodeWindow: AXUIElement?
        fileprivate let floatingOpenCodeApplication: FrontmostApplicationIdentity?
        fileprivate let floatingRequiresNewSessionEvidence: Bool
        /// True only when this exact V2 AXTextArea was initially proven to be
        /// the empty normal-mode composer by its bound placeholder while
        /// Chromium omitted AXDOMClassList. The placeholder disappears after
        /// insertion, so later checks pair this immutable capture fact with
        /// the still-visible normal-mode control row.
        fileprivate let openCodeV2PromptFallbackWasAttested: Bool
        /// Exact OpenCode 1.18.18 persisted active-draft identity. Production
        /// markerless V2 delivery re-reads this immediately before every
        /// mutation boundary so a project/tab change fails closed.
        fileprivate let openCodeWindowStateAttestation:
            OpenCodeWindowStateAttestation?

        fileprivate init(
            element: AXUIElement,
            processIdentifier: pid_t,
            requiresExactInsertionReadback: Bool,
            expectedInitialValue: String?,
            expectedInitialValueIsEmptyComposer: Bool,
            requiresOpenCodeChatIdentity: Bool,
            floatingOpenCodeWindow: AXUIElement?,
            floatingOpenCodeApplication: FrontmostApplicationIdentity?,
            floatingRequiresNewSessionEvidence: Bool,
            openCodeV2PromptFallbackWasAttested: Bool = false,
            openCodeWindowStateAttestation:
                OpenCodeWindowStateAttestation? = nil
        ) {
            self.element = element
            self.processIdentifier = processIdentifier
            self.requiresExactInsertionReadback = requiresExactInsertionReadback
            self.expectedInitialValue = expectedInitialValue
            self.expectedInitialValueIsEmptyComposer =
                expectedInitialValueIsEmptyComposer
            self.requiresOpenCodeChatIdentity = requiresOpenCodeChatIdentity
            self.floatingOpenCodeWindow = floatingOpenCodeWindow
            self.floatingOpenCodeApplication = floatingOpenCodeApplication
            self.floatingRequiresNewSessionEvidence =
                floatingRequiresNewSessionEvidence
            self.openCodeV2PromptFallbackWasAttested =
                openCodeV2PromptFallbackWasAttested
            self.openCodeWindowStateAttestation =
                openCodeWindowStateAttestation
        }
    }

    struct ApplicationTarget {
        fileprivate let processIdentifier: pid_t
        fileprivate let requiresMissingFocusedElement: Bool
    }

    struct OpenCodeRouteTarget {
        fileprivate let processIdentifier: pid_t
        fileprivate let bundleIdentifier: String
        fileprivate let bundlePath: String
        fileprivate let focusedWindow: AXUIElement
    }

    struct OpenCodeWindowStateAttestation: Equatable {
        let filePath: String
        let device: UInt64
        let inode: UInt64
        let size: Int64
        let modifiedSeconds: Int64
        let modifiedNanoseconds: Int64
        let activeDraftID: String
        let projectDirectory: String
    }

    private struct OpenCodeStateFileRead {
        let data: Data
        let device: UInt64
        let inode: UInt64
        let size: Int64
        let modifiedSeconds: Int64
        let modifiedNanoseconds: Int64
    }

    private enum OpenCodeNewSessionPreparation {
        /// The requested project/new-session controls have not yet hydrated.
        case pending
        /// Workspace mode exposes an exact active project-scoped new-session
        /// link, so the deep link itself supplies fresh-session evidence.
        case ready
        /// Single-workspace mode exposes only a persistent button. Activate
        /// that exact project-scoped control before accepting any composer.
        case activate(AXUIElement)
    }

    private enum OpenCodeRoutedComposerInspection {
        case empty(TargetCapture)
        case retained(element: AXUIElement, value: String)
        case accessibilityUnavailable
        case unavailable
    }

    private enum OpenCodeNewSessionRouteResult {
        case editable(TargetCapture)
        case requestedContentPresent
        case copyOnly(String)
        case accessibilityUnavailable
    }

    private enum OpenCodeRetainedContentMatch {
        case exact
        case legacySyncResidue
    }

    private struct OpenCodeRetainedComposerObservation {
        let element: AXUIElement
        let value: String
        let observedAt: ContinuousClock.Instant
    }

    private enum OpenCodeComposerPresentationFailure: String {
        case deadline
        case windowFrameMissing = "window_frame_missing"
        case composerFrameMissing = "composer_frame_missing"
        case windowFrameInvalid = "window_frame_invalid"
        case composerFrameInvalid = "composer_frame_invalid"
        case outsideWindow = "outside_window"
        case windowOwnerMissing = "window_owner_missing"
        case windowOwnerMismatch = "window_owner_mismatch"
        case hitTest = "hit_test"
        case topLevelOwnerMismatch = "top_level_owner_mismatch"
        case processOwnerMismatch = "process_owner_mismatch"
        case hidden
        case invisible
        case parentMissing = "parent_missing"
        case parentCycle = "parent_cycle"
        case parentDepth = "parent_depth"
    }

    private let accessibility: any AccessibilityElementClient
    private let pasteboard: any TextPasteboard
    private let postCommandV: @MainActor (pid_t) -> Bool
    private let postSpace: @MainActor (pid_t) -> Bool
    private let postDeleteBackward: @MainActor (pid_t) -> Bool
    private let openURL: @MainActor (URL, String) -> Bool
    private let validateOpenCodeApplication: @MainActor (String) -> Bool
    private let openCodeRouteTimeoutMilliseconds: Int
    private let openCodeRouteGraceMilliseconds: Int
    private let openCodeFocusSettleMilliseconds: Int
    private let openCodeRoutePollMilliseconds: Int
    private let allowsLegacyOpenCodeEmptyComposerFallback: Bool
    private let allowsOpenCodeURLRouting: Bool
    private let attestOpenCodeWindowState: @MainActor (
        String
    ) -> OpenCodeWindowStateAttestation?

    init(
        allowsLegacyOpenCodeEmptyComposerFallback: Bool = true,
        allowsOpenCodeURLRouting: Bool = true
    ) {
        accessibility = SystemAccessibilityElementClient()
        pasteboard = NSPasteboard.general
        postCommandV = Self.postCommandV
        postSpace = Self.postSpace
        postDeleteBackward = Self.postDeleteBackward
        openURL = Self.openOpenCodeRoute
        validateOpenCodeApplication = Self.isTrustedOpenCodeApplication
        openCodeRouteTimeoutMilliseconds = 6_000
        openCodeRouteGraceMilliseconds = 1_250
        openCodeFocusSettleMilliseconds = 550
        openCodeRoutePollMilliseconds = 100
        self.allowsLegacyOpenCodeEmptyComposerFallback =
            allowsLegacyOpenCodeEmptyComposerFallback
        self.allowsOpenCodeURLRouting = allowsOpenCodeURLRouting
        attestOpenCodeWindowState = Self.readOpenCodeWindowStateAttestation
    }

    init(
        accessibility: any AccessibilityElementClient,
        pasteboard: any TextPasteboard,
        postCommandV: @escaping @MainActor (pid_t) -> Bool,
        postSpace: @escaping @MainActor (pid_t) -> Bool = { _ in false },
        postDeleteBackward: @escaping @MainActor (pid_t) -> Bool = { _ in false },
        openURL: (@MainActor (URL, String) -> Bool)? = nil,
        validateOpenCodeApplication: (@MainActor (String) -> Bool)? = nil,
        openCodeRouteTimeoutMilliseconds: Int = 6_000,
        openCodeRouteGraceMilliseconds: Int = 1_250,
        openCodeFocusSettleMilliseconds: Int = 550,
        openCodeRoutePollMilliseconds: Int = 100,
        allowsLegacyOpenCodeEmptyComposerFallback: Bool = true,
        allowsOpenCodeURLRouting: Bool = true,
        attestOpenCodeWindowState: (@MainActor (
            String
        ) -> OpenCodeWindowStateAttestation?)? = nil
    ) {
        self.accessibility = accessibility
        self.pasteboard = pasteboard
        self.postCommandV = postCommandV
        self.postSpace = postSpace
        self.postDeleteBackward = postDeleteBackward
        self.openURL = openURL ?? Self.openOpenCodeRoute
        self.validateOpenCodeApplication = validateOpenCodeApplication
            ?? Self.isTrustedOpenCodeApplication
        self.openCodeRouteTimeoutMilliseconds = max(
            1,
            openCodeRouteTimeoutMilliseconds
        )
        self.openCodeRouteGraceMilliseconds = max(
            0,
            openCodeRouteGraceMilliseconds
        )
        self.openCodeFocusSettleMilliseconds = max(
            0,
            openCodeFocusSettleMilliseconds
        )
        self.openCodeRoutePollMilliseconds = max(
            1,
            openCodeRoutePollMilliseconds
        )
        self.allowsLegacyOpenCodeEmptyComposerFallback =
            allowsLegacyOpenCodeEmptyComposerFallback
        self.allowsOpenCodeURLRouting = allowsOpenCodeURLRouting
        self.attestOpenCodeWindowState = attestOpenCodeWindowState
            ?? Self.readOpenCodeWindowStateAttestation
    }

    func openCodeApplicationSupportsVerifiedComposer(
        at bundlePath: String
    ) -> Bool {
        validateOpenCodeApplication(bundlePath)
    }

    func captureTarget(
        expectedBundleIdentifiers: Set<String> = [],
        allowNonEditableApplicationFallback: Bool = true,
        allowMissingFocusedElementFallback: Bool = true,
        requireMissingFocusedElementForApplicationPaste: Bool = false,
        requireExactInsertionReadback: Bool = false,
        requireFocusedEmptyOpenCodeComposer: Bool = false,
        discoverEditableWithExactValue requiredEditableValue: String? = nil,
        attestingOpenCodeProjectDirectory: String? = nil,
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
            let requiresOpenCodeIdentity = (
                expectedBundleIdentifiers == [Self.openCodeBundleIdentifier]
            )
            let expectedOpenCodeWindow = requiresOpenCodeIdentity
                ? focusedWindow(
                    in: frontmostApplication.processIdentifier,
                    deadline: discoveryDeadline
                )
                : nil
            guard !requiresOpenCodeIdentity || expectedOpenCodeWindow != nil,
                  let element = uniqueEditableElement(
                in: frontmostApplication.processIdentifier,
                    withExactValue: requiredEditableValue,
                    requireOpenCodeChatIdentity: requiresOpenCodeIdentity,
                    expectedFocusedWindow: expectedOpenCodeWindow,
                    attestingProjectDirectory: (
                        attestingOpenCodeProjectDirectory
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
                expectedOpenCodeWindow: expectedOpenCodeWindow,
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
                    expectedInitialValueIsEmptyComposer: false,
                    requiresOpenCodeChatIdentity: requiresOpenCodeIdentity,
                    floatingOpenCodeWindow: nil,
                    floatingOpenCodeApplication: nil,
                    floatingRequiresNewSessionEvidence: false
                )
            )
        }
        let requiresOpenCodeChatIdentity = (
            frontmostApplication.bundleIdentifier == Self.openCodeBundleIdentifier
        )
        if requiresOpenCodeChatIdentity {
            let clock = ContinuousClock()
            let openCodeDiscoveryDeadline = discoveryDeadline
                ?? clock.now.advanced(by: .milliseconds(1_500))
            guard let focusedWindow = focusedWindow(
                in: frontmostApplication.processIdentifier,
                deadline: openCodeDiscoveryDeadline
            ) else {
                return .copyOnly(
                    "DaemonState could not verify the focused OpenCode window."
                )
            }
            guard let bundlePath = frontmostApplication.bundlePath,
                  validateOpenCodeApplication(bundlePath)
            else {
                return .copyOnly(
                    "DaemonState could not verify the focused OpenCode installation."
                )
            }
            let canonicalProjectDirectory = canonicalExistingDirectory(
                attestingOpenCodeProjectDirectory
            )
            if requireFocusedEmptyOpenCodeComposer || !allowsOpenCodeURLRouting {
                let diagnosticTarget = OpenCodeRouteTarget(
                    processIdentifier: frontmostApplication.processIdentifier,
                    bundleIdentifier: Self.openCodeBundleIdentifier,
                    bundlePath: bundlePath,
                    focusedWindow: focusedWindow
                )
                guard let element = uniqueEditableElement(
                    in: frontmostApplication.processIdentifier,
                    withExactValue: "",
                    requireOpenCodeChatIdentity: true,
                    expectedFocusedWindow: focusedWindow,
                    requireNewSessionEvidence: false,
                    acceptOpenCodeStructuralEmptyValue: true,
                    deadline: openCodeDiscoveryDeadline
                ) else {
                    logOpenCodeComposerCandidateDiagnostics(
                        diagnosticTarget,
                        phase: "focused_capture"
                    )
                    Self.pasteLogger.error(
                        "opencode_focused_capture=rejected reason=composer"
                    )
                    return .copyOnly(
                        "Open exactly one empty normal OpenCode chat composer, "
                            + "then try again."
                    )
                }
                guard focusAndVerify(
                    element,
                    processIdentifier: frontmostApplication.processIdentifier,
                    expectedOpenCodeWindow: focusedWindow,
                    deadline: openCodeDiscoveryDeadline
                ) else {
                    Self.pasteLogger.error(
                        "opencode_focused_capture=rejected reason=focus"
                    )
                    return .copyOnly(
                        "Open exactly one empty normal OpenCode chat composer, "
                            + "then try again."
                    )
                }
                guard let initialValue = accessibility.stringAttribute(
                    kAXValueAttribute as CFString,
                    from: element
                ), isOpenCodeEmptyComposerValue(initialValue) else {
                    Self.pasteLogger.error(
                        "opencode_focused_capture=rejected reason=value"
                    )
                    return .copyOnly(
                        "Open exactly one empty normal OpenCode chat composer, "
                            + "then try again."
                    )
                }
                Self.pasteLogger.notice(
                    "opencode_focused_capture=accepted"
                )
                return .editable(
                    FocusedTarget(
                        element: element,
                        processIdentifier: frontmostApplication.processIdentifier,
                        requiresExactInsertionReadback: true,
                        expectedInitialValue: initialValue,
                        expectedInitialValueIsEmptyComposer: true,
                        requiresOpenCodeChatIdentity: true,
                        floatingOpenCodeWindow: focusedWindow,
                        floatingOpenCodeApplication: frontmostApplication,
                        floatingRequiresNewSessionEvidence: false,
                        openCodeV2PromptFallbackWasAttested:
                            openCodeV2PromptFallbackIsInitiallyAttested(
                                element,
                                deadline: openCodeDiscoveryDeadline
                            )
                    )
                )
            }
            // OpenCode's integrated terminal and inactive tabs can both leave
            // editable AXTextAreas in the window tree. The floating control
            // may use the fast path only when the one empty, attested normal
            // composer is already the system-focused, visibly presented
            // element. Capture must never manufacture focus on a stale node.
            if allowsOpenCodeURLRouting,
               allowsLegacyOpenCodeEmptyComposerFallback,
               let element = uniqueEditableElement(
                in: frontmostApplication.processIdentifier,
                withExactValue: "",
                requireOpenCodeChatIdentity: true,
                expectedFocusedWindow: focusedWindow,
                attestingProjectDirectory: canonicalProjectDirectory,
                requireNewSessionEvidence: true,
                acceptOpenCodeStructuralEmptyValue: true,
                deadline: openCodeDiscoveryDeadline
            ), let alreadyFocused = accessibility.focusedElement(),
            accessibility.processIdentifier(for: alreadyFocused)
                == frontmostApplication.processIdentifier,
            accessibility.elementsAreEqual(alreadyFocused, element),
            openCodeComposerIsVisiblyPresented(
                element,
                in: focusedWindow,
                processIdentifier: frontmostApplication.processIdentifier,
                deadline: openCodeDiscoveryDeadline
            ), let initialValue = accessibility.stringAttribute(
                kAXValueAttribute as CFString,
                from: element
            ), isOpenCodeEmptyComposerValue(initialValue) {
                return .editable(
                    FocusedTarget(
                        element: element,
                        processIdentifier: frontmostApplication.processIdentifier,
                        requiresExactInsertionReadback: true,
                        // Preserve the renderer's exact initial serialization
                        // so a focus/draft race still fails closed.
                        expectedInitialValue: initialValue,
                        expectedInitialValueIsEmptyComposer: true,
                        requiresOpenCodeChatIdentity: true,
                        floatingOpenCodeWindow: focusedWindow,
                        floatingOpenCodeApplication: frontmostApplication,
                        floatingRequiresNewSessionEvidence: true,
                        openCodeV2PromptFallbackWasAttested:
                            openCodeV2PromptFallbackIsInitiallyAttested(
                                element,
                                deadline: openCodeDiscoveryDeadline
                            )
                    )
                )
            }
            return .openCodeNewComposer(
                OpenCodeRouteTarget(
                    processIdentifier: frontmostApplication.processIdentifier,
                    bundleIdentifier: Self.openCodeBundleIdentifier,
                    bundlePath: bundlePath,
                    focusedWindow: focusedWindow
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
                        expectedInitialValueIsEmptyComposer: false,
                        requiresOpenCodeChatIdentity: false,
                        floatingOpenCodeWindow: nil,
                        floatingOpenCodeApplication: nil,
                        floatingRequiresNewSessionEvidence: false
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
        let isEmpty = target.expectedInitialValueIsEmptyComposer
            ? isOpenCodeEmptyComposerValue(value)
            : value.isEmpty
        return isEmpty ? .empty : .nonempty
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
        to capture: TargetCapture,
        openCodeProjectDirectory: String? = nil
    ) async throws -> PasteDeliveryOutcome {
        switch capture {
        case .editable(_), .application(_), .openCodeNewComposer(_), .copyOnly(_):
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
        return try await deliverCopiedContent(
            content,
            to: capture,
            verifiedChangeCount: verifiedChangeCount,
            openCodeProjectDirectory: openCodeProjectDirectory
        )
    }

    private func deliverCopiedContent(
        _ content: String,
        to capture: TargetCapture,
        verifiedChangeCount: Int,
        openCodeProjectDirectory: String?
    ) async throws -> PasteDeliveryOutcome {
        switch capture {
        case let .editable(capturedTarget):
            if capturedTarget.floatingOpenCodeWindow != nil {
                guard floatingOpenCodeTargetIsStillAttested(
                    capturedTarget,
                    projectDirectory: openCodeProjectDirectory
                ) else {
                    return .notPasted(
                        "OpenCode's captured window and selected project "
                            + "could not be verified. The context was copied."
                    )
                }
            }
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
                        capturedTarget.expectedInitialValueIsEmptyComposer
                            ? "The verified OpenCode chat composer is no longer empty. "
                                + "The context was copied; clear the draft and try again."
                            : "The verified composer marker changed before automatic paste."
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
                if capturedTarget.requiresOpenCodeChatIdentity {
                    let mode = capturedTarget.expectedInitialValueIsEmptyComposer
                        ? "opencode_empty"
                        : "opencode_marker"
                    Self.pasteLogger.notice(
                        "paste_result=verified mode=\(mode, privacy: .public)"
                    )
                }
                guard capturedTarget.expectedInitialValue != nil else {
                    return .insertedWithAccessibility
                }
                return capturedTarget.expectedInitialValueIsEmptyComposer
                    ? .insertedIntoVerifiedEmptyComposerWithInputSync
                    : .markerReplacedWithVerifiedInputSync
            case let .acknowledgedButUnverified(phase):
                let mode = capturedTarget.requiresOpenCodeChatIdentity
                    ? (
                        capturedTarget.expectedInitialValueIsEmptyComposer
                            ? "opencode_empty"
                            : "opencode_marker"
                    )
                    : "strict_ax"
                Self.pasteLogger.error(
                    "paste_result=unverified mode=\(mode, privacy: .public) phase=\(phase.rawValue, privacy: .public)"
                )
                return .accessibilityInsertionUnverified(
                    "macOS acknowledged the context insertion, but the editor "
                        + "did not expose the exact inserted value for verification."
                )
            case .notPerformed:
                break
            }
            if capturedTarget.expectedInitialValue != nil {
                return .notPasted(
                    capturedTarget.expectedInitialValueIsEmptyComposer
                        ? "OpenCode’s verified chat composer did not allow safe "
                            + "automatic insertion. The context was copied."
                        : "The verified chat composer did not allow a safe marker replacement."
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
        case let .openCodeNewComposer(routeTarget):
            let routedCapture = await routeOpenCodeNewSessionComposer(
                routeTarget,
                projectDirectory: openCodeProjectDirectory,
                requestedContent: content
            )
            guard pasteboard.changeCount == verifiedChangeCount,
                  pasteboard.string(forType: .string) == content
            else {
                throw PasteDeliveryError.clipboardChanged
            }
            switch routedCapture {
            case let .editable(capture):
                guard openCodeRouteTargetMatches(routeTarget),
                      validateOpenCodeApplication(routeTarget.bundlePath)
                else {
                    return .notPasted(
                        "OpenCode's verified application identity changed "
                            + "before insertion. The context was copied."
                    )
                }
                return try await deliverCopiedContent(
                    content,
                    to: capture,
                    verifiedChangeCount: verifiedChangeCount,
                    openCodeProjectDirectory: openCodeProjectDirectory
                )
            case .requestedContentPresent:
                return .alreadyPresentInVerifiedOpenCodeComposer
            case let .copyOnly(message):
                return .notPasted(message + " The context was copied.")
            case .accessibilityUnavailable:
                return .notPasted(
                    "Accessibility access changed while OpenCode was opening. "
                        + "The context was copied."
                )
            }
        case let .copyOnly(message):
            return .notPasted(message + " The context was copied.")
        case .accessibilityUnavailable:
            return .notPasted(
                "Accessibility access changed while OpenCode was opening. "
                    + "The context was copied."
            )
        case let .unavailable(message):
            return .notPasted(message + " The context was copied.")
        }
    }

    private func routeOpenCodeNewSessionComposer(
        _ target: OpenCodeRouteTarget,
        projectDirectory: String?,
        requestedContent: String
    ) async -> OpenCodeNewSessionRouteResult {
        guard openCodeRouteTargetMatches(target) else {
            return .copyOnly(
                "OpenCode changed before a new-session composer could be requested."
            )
        }
        guard validateOpenCodeApplication(target.bundlePath) else {
            return .copyOnly(
                "DaemonState could not verify the focused OpenCode installation."
            )
        }
        guard let projectDirectory = canonicalExistingDirectory(
            projectDirectory
        ) else {
            return .copyOnly(
                "OpenCode needs a readable local project directory to open a new chat."
            )
        }

        if !allowsOpenCodeURLRouting {
            return await captureExistingFocusedOpenCodeNewSessionComposer(
                target,
                projectDirectory: projectDirectory
            ) ?? .copyOnly(
                "OpenCode must already show exactly one empty new-session "
                    + "composer for the selected project. DaemonState stopped "
                    + "without navigating or activating OpenCode."
            )
        }

        // A previous strict delivery may already have populated the captured
        // project's current composer. Prove that state before dispatching a
        // deep link or pressing New session; either action could detach the
        // very composer needed for idempotent retry recognition.
        if allowsLegacyOpenCodeEmptyComposerFallback,
           let retainedMatch = await retainedOpenCodeComposerContentMatch(
                target,
                projectDirectory: projectDirectory,
                requestedContent: requestedContent
           )
        {
            switch retainedMatch {
            case .exact:
                return .requestedContentPresent
            case .legacySyncResidue:
                return .copyOnly(Self.openCodeLegacySyncResidueMessage)
            }
        }

        let routeMarker = newOpenCodeRouteMarker()
        guard let routeURL = openCodeNewSessionURL(
            projectDirectory: projectDirectory,
            prompt: routeMarker
        ), openCodeRouteTargetMatches(target),
        openURL(routeURL, target.bundlePath) else {
            return .copyOnly(
                "macOS could not request a new OpenCode chat composer."
            )
        }

        let clock = ContinuousClock()
        var deadline = clock.now.advanced(
            by: .milliseconds(openCodeRouteTimeoutMilliseconds)
        )
        var stableSince: ContinuousClock.Instant?
        var retainedDraftObservation: OpenCodeRetainedComposerObservation?
        var newSessionPrepared = false
        while clock.now < deadline {
            let now = clock.now
            if openCodeRouteTargetMatches(target) {
                if stableSince == nil {
                    stableSince = now
                }
                let graceComplete = stableSince.map {
                    now >= $0.advanced(
                        by: .milliseconds(openCodeRouteGraceMilliseconds)
                    )
                } ?? false
                if graceComplete,
                   let markerCapture = captureRoutedOpenCodeMarkerComposer(
                       target,
                       marker: routeMarker,
                       deadline: deadline
                   )
                {
                    if openCodeFocusSettleMilliseconds > 0 {
                        try? await Task.sleep(
                            for: .milliseconds(
                                openCodeFocusSettleMilliseconds
                            )
                        )
                    }
                    guard clock.now < deadline,
                          openCodeRouteTargetMatches(target),
                          validateOpenCodeApplication(target.bundlePath),
                          let settledMarkerCapture =
                            captureRoutedOpenCodeMarkerComposer(
                                target,
                                marker: routeMarker,
                                deadline: deadline
                            ), capturesSameEditableTarget(
                                markerCapture,
                                settledMarkerCapture
                            ), editableTargetHasExactContent(
                                settledMarkerCapture,
                                expected: routeMarker
                            )
                    else {
                        stableSince = nil
                        continue
                    }
                    return .editable(settledMarkerCapture)
                }
                if graceComplete
                    && !allowsLegacyOpenCodeEmptyComposerFallback
                {
                    // OpenCode 1.18 supports a directory-bound prompt nonce.
                    // Never mutate a merely empty composer if that exact nonce
                    // did not materialize; it could be a stale node or another
                    // draft/window. The old sidebar fallback remains available
                    // only to explicit legacy integrations.
                    try? await Task.sleep(
                        for: .milliseconds(openCodeRoutePollMilliseconds)
                    )
                    continue
                }
                var mayCaptureComposer = graceComplete && newSessionPrepared
                if graceComplete && !newSessionPrepared {
                    switch openCodeNewSessionPreparation(
                        target,
                        projectDirectory: projectDirectory,
                        deadline: deadline
                    ) {
                    case .pending:
                        break
                    case .ready:
                        // Navigation/project hydration has its own bounded
                        // phase. Once freshness is positively attested, give
                        // composer discovery and settling a complete bounded
                        // phase instead of spending whatever happens to remain
                        // from the renderer-navigation budget.
                        deadline = clock.now.advanced(
                            by: .milliseconds(openCodeRouteTimeoutMilliseconds)
                        )
                        newSessionPrepared = true
                        mayCaptureComposer = true
                    case let .activate(newSessionButton):
                        guard openCodeRouteTargetMatches(target),
                              accessibility.performAction(
                                  kAXPressAction as CFString,
                                  on: newSessionButton
                              ) == .success,
                              openCodeRouteTargetMatches(target)
                        else {
                            return .copyOnly(
                                "OpenCode's verified New session control "
                                    + "could not be activated."
                            )
                        }
                        // AXPress is the freshness boundary in OpenCode's
                        // workspaces-disabled layout. Give the renderer a full
                        // post-action grace interval before inspecting the
                        // resulting composer, even if the deep link appeared
                        // to have navigated already.
                        deadline = clock.now.advanced(
                            by: .milliseconds(openCodeRouteTimeoutMilliseconds)
                        )
                        newSessionPrepared = true
                        stableSince = clock.now
                        mayCaptureComposer = false
                    }
                }
                if mayCaptureComposer {
                    let inspection = captureRoutedOpenCodeComposer(
                        target,
                        projectDirectory: projectDirectory,
                        deadline: deadline
                    )
                    switch inspection {
                    case .accessibilityUnavailable:
                        return .accessibilityUnavailable
                    case let .retained(element, value):
                        let observedAt = clock.now
                        if let previous = retainedDraftObservation,
                           accessibility.elementsAreEqual(
                               previous.element,
                               element
                           ), previous.value == value
                        {
                            // Keep the first observation as the settle
                            // baseline. Resetting it on every poll would make
                            // a responsive, unchanged renderer wait forever.
                            if observedAt >= previous.observedAt.advanced(
                                by: .milliseconds(
                                    max(
                                        openCodeFocusSettleMilliseconds,
                                        openCodeRoutePollMilliseconds
                                    )
                                )
                            ), openCodeRouteTargetMatches(target),
                            validateOpenCodeApplication(target.bundlePath) {
                                if let retainedMatch = openCodeRetainedContentMatch(
                                    value,
                                    deliveredContent: requestedContent
                                ) {
                                    if case .legacySyncResidue = retainedMatch {
                                        return .copyOnly(
                                            Self.openCodeLegacySyncResidueMessage
                                        )
                                    }
                                    return .requestedContentPresent
                                }
                                return .copyOnly(
                                    Self.openCodeRetainedDraftMessage
                                )
                            }
                        } else {
                            retainedDraftObservation = OpenCodeRetainedComposerObservation(
                                element: element,
                                value: value,
                                observedAt: observedAt
                            )
                        }
                    case let .empty(capture):
                        retainedDraftObservation = nil
                        if openCodeFocusSettleMilliseconds > 0 {
                            try? await Task.sleep(
                                for: .milliseconds(
                                    openCodeFocusSettleMilliseconds
                                )
                            )
                        }
                        guard clock.now < deadline,
                              openCodeRouteTargetMatches(target)
                        else {
                            break
                        }
                        let settledCapture = captureRoutedOpenCodeComposer(
                            target,
                            projectDirectory: projectDirectory,
                            deadline: deadline
                        )
                        if case let .empty(settledTarget) = settledCapture,
                           capturesSameEditableTarget(
                            capture,
                            settledTarget
                           ), editableTargetContentState(settledTarget) == .empty,
                           openCodeRouteTargetMatches(target),
                           validateOpenCodeApplication(target.bundlePath)
                        {
                            return .editable(settledTarget)
                        }
                    case .unavailable:
                        retainedDraftObservation = nil
                    }
                }
            } else {
                Self.pasteLogger.notice(
                    "route_result=cancelled phase=focus_changed"
                )
                return .copyOnly(
                    "OpenCode lost focus, so DaemonState cancelled the handoff "
                        + "and will not reactivate it."
                )
            }
            try? await Task.sleep(
                for: .milliseconds(openCodeRoutePollMilliseconds)
            )
        }
        let phase = newSessionPrepared
            ? "composer_discovery"
            : "route_preparation"
        Self.pasteLogger.error(
            "route_result=unavailable phase=\(phase, privacy: .public)"
        )
        return .copyOnly(Self.openCodeRouteFailureMessage)
    }

    private func captureExistingFocusedOpenCodeNewSessionComposer(
        _ target: OpenCodeRouteTarget,
        projectDirectory: String
    ) async -> OpenCodeNewSessionRouteResult? {
        let clock = ContinuousClock()
        let deadline = clock.now.advanced(
            by: .milliseconds(min(openCodeRouteTimeoutMilliseconds, 1_500))
        )
        guard openCodeRouteTargetMatches(target) else {
            return rejectExistingOpenCodeComposer(
                phase: "initial",
                reason: "target"
            )
        }
        guard validateOpenCodeApplication(target.bundlePath) else {
            return rejectExistingOpenCodeComposer(
                phase: "initial",
                reason: "app"
            )
        }
        guard openCodeExpectedFocusedWindowIsRegistered(target) else {
            return rejectExistingOpenCodeComposer(
                phase: "initial",
                reason: "focused_window_membership"
            )
        }
        guard let firstState = attestOpenCodeWindowState(projectDirectory)
        else {
            return rejectExistingOpenCodeComposer(
                phase: "initial",
                reason: "state"
            )
        }
        guard let firstElement = uniqueEditableElement(
            in: target.processIdentifier,
            withExactValue: "",
            requireOpenCodeChatIdentity: true,
            expectedFocusedWindow: target.focusedWindow,
            acceptOpenCodeStructuralEmptyValue: true,
            deadline: deadline
        ) else {
            logOpenCodeComposerCandidateDiagnostics(
                target,
                phase: "initial"
            )
            return rejectExistingOpenCodeComposer(
                phase: "initial",
                reason: "composer"
            )
        }
        guard let firstValue = accessibility.stringAttribute(
            kAXValueAttribute as CFString,
            from: firstElement
        ), isOpenCodeEmptyComposerValue(firstValue) else {
            return rejectExistingOpenCodeComposer(
                phase: "initial",
                reason: "value"
            )
        }
        guard openCodeRouteTargetMatches(target) else {
            return rejectExistingOpenCodeComposer(
                phase: "initial",
                reason: "target"
            )
        }
        if openCodeFocusSettleMilliseconds > 0 {
            try? await Task.sleep(
                for: .milliseconds(openCodeFocusSettleMilliseconds)
            )
        }
        guard clock.now < deadline else {
            return rejectExistingOpenCodeComposer(
                phase: "settle",
                reason: "deadline"
            )
        }
        guard openCodeRouteTargetMatches(target) else {
            return rejectExistingOpenCodeComposer(
                phase: "settle",
                reason: "target"
            )
        }
        guard validateOpenCodeApplication(target.bundlePath) else {
            return rejectExistingOpenCodeComposer(
                phase: "settle",
                reason: "app"
            )
        }
        guard openCodeExpectedFocusedWindowIsRegistered(target) else {
            return rejectExistingOpenCodeComposer(
                phase: "settle",
                reason: "focused_window_membership"
            )
        }
        guard attestOpenCodeWindowState(projectDirectory) == firstState else {
            return rejectExistingOpenCodeComposer(
                phase: "settle",
                reason: "state"
            )
        }
        guard let secondElement = uniqueEditableElement(
            in: target.processIdentifier,
            withExactValue: "",
            requireOpenCodeChatIdentity: true,
            expectedFocusedWindow: target.focusedWindow,
            acceptOpenCodeStructuralEmptyValue: true,
            deadline: deadline
        ), accessibility.elementsAreEqual(firstElement, secondElement) else {
            logOpenCodeComposerCandidateDiagnostics(
                target,
                phase: "settle"
            )
            return rejectExistingOpenCodeComposer(
                phase: "settle",
                reason: "composer"
            )
        }
        guard accessibility.stringAttribute(
            kAXValueAttribute as CFString,
            from: secondElement
        ) == firstValue else {
            return rejectExistingOpenCodeComposer(
                phase: "settle",
                reason: "value"
            )
        }
        // Clicking the non-activating floating control does not guarantee that
        // Chromium reports the composer as AX-focused. Once the exact app,
        // sole window, stable project draft and unique visible empty V2
        // composer are all attested, focusing that exact element is safe. The
        // helper checks the captured app/window before and after AX mutation,
        // so a user switch to another app remains a terminal cancellation.
        guard focusAndVerify(
            secondElement,
            processIdentifier: target.processIdentifier,
            expectedOpenCodeWindow: target.focusedWindow,
            deadline: deadline
        ) else {
            return rejectExistingOpenCodeComposer(
                phase: "settle",
                reason: "focus"
            )
        }
        guard openCodeRouteTargetMatches(target) else {
            return rejectExistingOpenCodeComposer(
                phase: "focused",
                reason: "target"
            )
        }
        guard validateOpenCodeApplication(target.bundlePath) else {
            return rejectExistingOpenCodeComposer(
                phase: "focused",
                reason: "app"
            )
        }
        guard openCodeExpectedFocusedWindowIsRegistered(target) else {
            return rejectExistingOpenCodeComposer(
                phase: "focused",
                reason: "focused_window_membership"
            )
        }
        guard attestOpenCodeWindowState(projectDirectory) == firstState else {
            return rejectExistingOpenCodeComposer(
                phase: "focused",
                reason: "state"
            )
        }
        guard accessibility.stringAttribute(
            kAXValueAttribute as CFString,
            from: secondElement
        ) == firstValue else {
            return rejectExistingOpenCodeComposer(
                phase: "focused",
                reason: "value"
            )
        }
        Self.pasteLogger.notice(
            "opencode_state_attestation=accepted phase=settle"
        )
        return .editable(
            routedOpenCodeCapture(
                secondElement,
                initialValue: firstValue,
                target: target,
                windowStateAttestation: firstState
            )
        )
    }

    private func rejectExistingOpenCodeComposer(
        phase: String,
        reason: String
    ) -> OpenCodeNewSessionRouteResult? {
        Self.pasteLogger.error(
            "opencode_state_attestation=rejected phase=\(phase, privacy: .public) reason=\(reason, privacy: .public)"
        )
        return nil
    }

    private func logOpenCodeComposerCandidateDiagnostics(
        _ target: OpenCodeRouteTarget,
        phase: String
    ) {
        let scanDeadline = ContinuousClock().now.advanced(
            by: .milliseconds(500)
        )
        let maximumDepth = 32
        let maximumElements = 2_048
        let maximumLoggedCandidates = 16
        var pending: [(AXUIElement, Int)] = [(target.focusedWindow, 0)]
        var visited = Set<AXUIElement>()
        var loggedCandidates: [(AXUIElement, String?)] = []
        var candidateCount = 0
        var index = 0
        var scanComplete = true

        while index < pending.count,
              visited.count < maximumElements,
              deadlineAllowsWork(scanDeadline)
        {
            let (element, depth) = pending[index]
            index += 1
            guard visited.insert(element).inserted else { continue }
            let role = accessibility.stringAttribute(
                kAXRoleAttribute as CFString,
                from: element
            )
            if isEditable(element, deadline: scanDeadline) {
                candidateCount += 1
                if loggedCandidates.count < maximumLoggedCandidates {
                    loggedCandidates.append((element, role))
                }
            }
            if depth >= maximumDepth {
                if let children = accessibility.elementArrayAttribute(
                    kAXChildrenAttribute as CFString,
                    from: element,
                    maximumCount: 1
                ), !children.isEmpty {
                    scanComplete = false
                }
                continue
            }
            if isKnownAccessibilityLeaf(role) { continue }
            let remainingCapacity = maximumElements - pending.count
            guard remainingCapacity >= 0,
                  let children = accessibility.elementArrayAttribute(
                      kAXChildrenAttribute as CFString,
                      from: element,
                      maximumCount: min(256, remainingCapacity)
                  )
            else {
                scanComplete = false
                break
            }
            pending.append(contentsOf: children.map { ($0, depth + 1) })
        }
        if index < pending.count
            || visited.count >= maximumElements
            || !deadlineAllowsWork(scanDeadline)
        {
            scanComplete = false
        }
        Self.pasteLogger.error(
            "opencode_composer_candidates phase=\(phase, privacy: .public) count=\(candidateCount, privacy: .public) logged=\(loggedCandidates.count, privacy: .public) scan_complete=\(scanComplete, privacy: .public)"
        )

        let detailDeadline = ContinuousClock().now.advanced(
            by: .milliseconds(500)
        )
        for (candidateIndex, candidate) in loggedCandidates.enumerated() {
            let roleCategory: String
            if candidate.1 == kAXTextAreaRole as String {
                roleCategory = "textarea"
            } else if candidate.1 == kAXTextFieldRole as String {
                roleCategory = "textfield"
            } else if candidate.1 == nil {
                roleCategory = "none"
            } else {
                roleCategory = "other"
            }
            let names = [
                accessibility.stringAttribute(
                    kAXDescriptionAttribute as CFString,
                    from: candidate.0
                ),
                accessibility.stringAttribute(
                    kAXTitleAttribute as CFString,
                    from: candidate.0
                ),
                accessibility.stringAttribute(
                    kAXHelpAttribute as CFString,
                    from: candidate.0
                ),
            ].compactMap { value in
                value?.trimmingCharacters(in: .whitespacesAndNewlines)
                    .lowercased()
            }.filter { !$0.isEmpty }
            let nameCategory: String
            if names.contains("prompt") {
                nameCategory = "prompt"
            } else if names.contains(where: { $0.hasPrefix("ask anything") }) {
                nameCategory = "ask"
            } else if names.isEmpty {
                nameCategory = "none"
            } else {
                nameCategory = "other"
            }
            let domClasses = accessibility.stringArrayAttribute(
                "AXDOMClassList" as CFString,
                from: candidate.0
            )
            let classAvailability = domClasses == nil ? "missing" : "available"
            let classCount = min(domClasses?.count ?? 0, 256)
            let value = accessibility.stringAttribute(
                kAXValueAttribute as CFString,
                from: candidate.0
            )
            let valueState: String
            if let value {
                valueState = isOpenCodeEmptyComposerValue(value)
                    ? "empty"
                    : "nonempty"
            } else {
                valueState = "unavailable"
            }
            let presentation = openCodeComposerPresentationFailure(
                candidate.0,
                in: target.focusedWindow,
                processIdentifier: target.processIdentifier,
                deadline: detailDeadline
            )?.rawValue ?? "pass"
            let placeholderLevels = nameCategory == "prompt"
                ? openCodePlaceholderNeighborhoodCategories(
                    candidate.0,
                    deadline: detailDeadline
                )
                : ["not_prompt", "not_prompt", "not_prompt", "not_prompt"]
            Self.pasteLogger.error(
                "opencode_composer_candidate phase=\(phase, privacy: .public) index=\(candidateIndex, privacy: .public) role=\(roleCategory, privacy: .public) name=\(nameCategory, privacy: .public) dom_classes=\(classAvailability, privacy: .public) dom_class_count=\(classCount, privacy: .public) value=\(valueState, privacy: .public) presentation=\(presentation, privacy: .public) placeholder_l0=\(placeholderLevels[0], privacy: .public) placeholder_l1=\(placeholderLevels[1], privacy: .public) placeholder_l2=\(placeholderLevels[2], privacy: .public) placeholder_l3=\(placeholderLevels[3], privacy: .public)"
            )
        }
    }

    private func openCodePlaceholderNeighborhoodCategories(
        _ element: AXUIElement,
        deadline: ContinuousClock.Instant
    ) -> [String] {
        var result: [String] = []
        var current = element
        var visited: [AXUIElement] = []
        for _ in 0..<4 {
            guard deadlineAllowsWork(deadline),
                  let parent = accessibility.elementAttribute(
                      kAXParentAttribute as CFString,
                      from: current
                  ), !visited.contains(where: {
                      accessibility.elementsAreEqual($0, parent)
                  }), let children = accessibility.elementArrayAttribute(
                      kAXChildrenAttribute as CFString,
                      from: parent,
                      maximumCount: 64
                  )
            else {
                result.append("unreadable")
                current = parentOrSame(current, visited: &visited)
                continue
            }
            var hasNormal = false
            var hasShell = false
            for child in children {
                let normalized = [
                    accessibility.stringAttribute(
                        kAXValueAttribute as CFString,
                        from: child
                    ),
                    accessibility.stringAttribute(
                        kAXDescriptionAttribute as CFString,
                        from: child
                    ),
                    accessibility.stringAttribute(
                        kAXTitleAttribute as CFString,
                        from: child
                    ),
                ].compactMap { value in
                    value?.trimmingCharacters(in: .whitespacesAndNewlines)
                        .lowercased()
                }
                hasNormal = hasNormal || normalized.contains(
                    "ask anything, / for commands, @ for context..."
                )
                hasShell = hasShell || normalized.contains(
                    "enter shell command..."
                )
            }
            switch (hasNormal, hasShell) {
            case (true, true): result.append("both")
            case (true, false): result.append("normal")
            case (false, true): result.append("shell")
            case (false, false): result.append("none")
            }
            visited.append(current)
            current = parent
        }
        while result.count < 4 { result.append("unreadable") }
        return Array(result.prefix(4))
    }

    private func parentOrSame(
        _ element: AXUIElement,
        visited: inout [AXUIElement]
    ) -> AXUIElement {
        guard let parent = accessibility.elementAttribute(
            kAXParentAttribute as CFString,
            from: element
        ), !visited.contains(where: {
            accessibility.elementsAreEqual($0, parent)
        }) else {
            return element
        }
        visited.append(element)
        return parent
    }

    private func openCodeNewSessionPreparation(
        _ target: OpenCodeRouteTarget,
        projectDirectory: String,
        deadline: ContinuousClock.Instant
    ) -> OpenCodeNewSessionPreparation {
        guard accessibility.isTrusted(prompt: false),
              openCodeRouteTargetMatches(target),
              let focusedWindow = focusedWindow(
                  in: target.processIdentifier,
                  deadline: deadline
              ),
              accessibility.elementsAreEqual(
                  focusedWindow,
                  target.focusedWindow
              )
        else {
            return .pending
        }

        var activeNewSessionLinkCount = 0
        var expectedProjectLinkCount = 0
        var activeCurrentLinkCount = 0
        var localNewSessionButtons: [(AXUIElement, AXUIElement)] = []
        var expectedLocalProjectContainers: [AXUIElement] = []
        var pending: [(AXUIElement, Int)] = [(focusedWindow, 0)]
        var visited = Set<AXUIElement>()
        var index = 0
        let maximumDepth = 32
        let maximumElements = 8_192

        while index < pending.count,
              visited.count < maximumElements,
              deadlineAllowsWork(deadline)
        {
            let (element, depth) = pending[index]
            index += 1
            guard visited.insert(element).inserted else { continue }
            let role = accessibility.stringAttribute(
                kAXRoleAttribute as CFString,
                from: element
            )
            if role == "AXLink",
               accessibility.stringAttribute(
                   "AXARIACurrent" as CFString,
                   from: element
               )?.trimmingCharacters(in: .whitespacesAndNewlines)
                .lowercased() == "page"
            {
                activeCurrentLinkCount += 1
                if openCodeElementNamesNewSession(element) {
                    activeNewSessionLinkCount += 1
                    if openCodeNewSessionLinkPath(for: projectDirectory)
                        == accessibility.stringAttribute(
                            kAXURLAttribute as CFString,
                            from: element
                        ).flatMap(openCodeURLPath)
                    {
                        expectedProjectLinkCount += 1
                    }
                }
            }
            if role == kAXButtonRole as String,
               openCodeElementNamesNewSession(element),
               let container = openCodeLocalWorkspaceContainer(
                   containing: element,
                   processIdentifier: target.processIdentifier,
                   expectedWindow: focusedWindow,
                   deadline: deadline
               )
            {
                localNewSessionButtons.append((element, container))
            }
            if role == kAXStaticTextRole as String,
               openCodeElement(
                   element,
                   displaysProjectDirectory: projectDirectory
               ),
               let container = openCodeLocalWorkspaceContainer(
                   containing: element,
                   processIdentifier: target.processIdentifier,
                   expectedWindow: focusedWindow,
                   deadline: deadline
               ), let directParent = accessibility.elementAttribute(
                   kAXParentAttribute as CFString,
                   from: element
               ), accessibility.elementsAreEqual(directParent, container),
               openCodeElementIsLocalProjectPath(
                   element,
                   in: container,
                   deadline: deadline
               )
            {
                expectedLocalProjectContainers.append(container)
            }
            guard depth < maximumDepth else {
                guard let children = accessibility.elementArrayAttribute(
                    kAXChildrenAttribute as CFString,
                    from: element,
                    maximumCount: 1
                ), children.isEmpty else {
                    return .pending
                }
                continue
            }
            guard !isKnownAccessibilityLeaf(role) else { continue }
            let remainingCapacity = maximumElements - pending.count
            guard remainingCapacity >= 0,
                  let children = accessibility.elementArrayAttribute(
                      kAXChildrenAttribute as CFString,
                      from: element,
                      maximumCount: min(256, remainingCapacity)
                  )
            else {
                return .pending
            }
            pending.append(contentsOf: children.map { ($0, depth + 1) })
        }

        guard deadlineAllowsWork(deadline),
              index >= pending.count,
              focusedWindowMatches(
                  processIdentifier: target.processIdentifier,
                  expectedWindow: focusedWindow,
                  deadline: deadline
              )
        else {
            return .pending
        }
        if activeCurrentLinkCount == 1,
           activeNewSessionLinkCount == 1,
           expectedProjectLinkCount == 1
        {
            return .ready
        }
        if localNewSessionButtons.count == 1,
           expectedLocalProjectContainers.count == 1,
           accessibility.elementsAreEqual(
               localNewSessionButtons[0].1,
               expectedLocalProjectContainers[0]
           )
        {
            return .activate(localNewSessionButtons[0].0)
        }
        return .pending
    }

    private func captureRoutedOpenCodeComposer(
        _ target: OpenCodeRouteTarget,
        projectDirectory: String,
        deadline: ContinuousClock.Instant
    ) -> OpenCodeRoutedComposerInspection {
        guard accessibility.isTrusted(prompt: false) else {
            return .accessibilityUnavailable
        }

        // First prove there is exactly one normal composer of any value in the
        // attested project/window without conflating project identity with
        // fresh-session evidence. This lets an exact retained request be
        // recognized safely, while an empty composer still has to pass the
        // stronger freshness proof below before it can be mutated.
        guard let projectAttested = projectAttestedOpenCodeComposer(
            target,
            projectDirectory: projectDirectory,
            deadline: deadline
        ) else {
            return .unavailable
        }
        let projectAttestedElement = projectAttested.element
        let initialValue = projectAttested.value
        guard isOpenCodeEmptyComposerValue(initialValue) else {
            return .retained(
                element: projectAttestedElement,
                value: initialValue
            )
        }
        guard let freshElement = uniqueEditableElement(
            in: target.processIdentifier,
            withExactValue: nil,
            requireOpenCodeChatIdentity: true,
            expectedFocusedWindow: target.focusedWindow,
            attestingProjectDirectory: projectDirectory,
            requireNewSessionEvidence: true,
            deadline: deadline
        ), accessibility.elementsAreEqual(
            freshElement,
            projectAttestedElement
        ) else {
            return .unavailable
        }
        guard focusAndVerify(
            freshElement,
            processIdentifier: target.processIdentifier,
            expectedOpenCodeWindow: target.focusedWindow,
            deadline: deadline
        ), let focusedValue = accessibility.stringAttribute(
            kAXValueAttribute as CFString,
            from: freshElement
        ), focusedValue == initialValue,
        isOpenCodeEmptyComposerValue(focusedValue)
        else {
            return .unavailable
        }
        return .empty(
            routedOpenCodeCapture(
                freshElement,
                initialValue: focusedValue,
                target: target
            )
        )
    }

    private func captureRoutedOpenCodeMarkerComposer(
        _ target: OpenCodeRouteTarget,
        marker: String,
        deadline: ContinuousClock.Instant
    ) -> TargetCapture? {
        guard !marker.isEmpty,
              openCodeRouteTargetMatches(target),
              let element = uniqueEditableElement(
                  in: target.processIdentifier,
                  withExactValue: marker,
                  requireOpenCodeChatIdentity: true,
                  expectedFocusedWindow: target.focusedWindow,
                  requireNewSessionEvidence: false,
                  deadline: deadline
              ), let focusedElement = accessibility.focusedElement(),
              accessibility.processIdentifier(for: focusedElement)
                == target.processIdentifier,
              accessibility.elementsAreEqual(focusedElement, element),
              openCodeRouteTargetMatches(target),
              accessibility.stringAttribute(
                  kAXValueAttribute as CFString,
                  from: element
              ) == marker,
              openCodeRouteTargetMatches(target)
        else {
            return nil
        }
        return .editable(
            FocusedTarget(
                element: element,
                processIdentifier: target.processIdentifier,
                requiresExactInsertionReadback: true,
                expectedInitialValue: marker,
                expectedInitialValueIsEmptyComposer: false,
                requiresOpenCodeChatIdentity: true,
                floatingOpenCodeWindow: target.focusedWindow,
                floatingOpenCodeApplication: FrontmostApplicationIdentity(
                    processIdentifier: target.processIdentifier,
                    bundleIdentifier: target.bundleIdentifier,
                    bundlePath: target.bundlePath
                ),
                // The route nonce is exact, unique evidence that this visible
                // composer was seeded by this invocation's directory-bound
                // OpenCode deep link. Sidebar freshness heuristics are only a
                // compatibility fallback for older OpenCode builds.
                floatingRequiresNewSessionEvidence: false
            )
        )
    }

    private func projectAttestedOpenCodeComposer(
        _ target: OpenCodeRouteTarget,
        projectDirectory: String,
        deadline: ContinuousClock.Instant
    ) -> (element: AXUIElement, value: String)? {
        guard let element = uniqueEditableElement(
            in: target.processIdentifier,
            withExactValue: nil,
            requireOpenCodeChatIdentity: true,
            expectedFocusedWindow: target.focusedWindow,
            attestingProjectDirectory: projectDirectory,
            requireNewSessionEvidence: false,
            deadline: deadline
        ), let value = accessibility.stringAttribute(
            kAXValueAttribute as CFString,
            from: element
        ) else {
            return nil
        }
        return (element, value)
    }

    private func retainedOpenCodeComposerContentMatch(
        _ target: OpenCodeRouteTarget,
        projectDirectory: String,
        requestedContent: String
    ) async -> OpenCodeRetainedContentMatch? {
        let clock = ContinuousClock()
        let deadline = clock.now.advanced(
            by: .milliseconds(
                min(openCodeRouteTimeoutMilliseconds, 1_500)
            )
        )
        guard openCodeRouteTargetMatches(target),
              validateOpenCodeApplication(target.bundlePath),
              let first = projectAttestedOpenCodeComposer(
                  target,
                  projectDirectory: projectDirectory,
                  deadline: deadline
              ), !isOpenCodeEmptyComposerValue(first.value),
              let firstMatch = openCodeRetainedContentMatch(
                  first.value,
                  deliveredContent: requestedContent
              )
        else {
            return nil
        }
        if openCodeFocusSettleMilliseconds > 0 {
            try? await Task.sleep(
                for: .milliseconds(openCodeFocusSettleMilliseconds)
            )
        }
        guard clock.now < deadline,
              openCodeRouteTargetMatches(target),
              validateOpenCodeApplication(target.bundlePath),
              let second = projectAttestedOpenCodeComposer(
                  target,
                  projectDirectory: projectDirectory,
                  deadline: deadline
              ), accessibility.elementsAreEqual(
                  first.element,
                  second.element
              ), second.value == first.value,
              openCodeRetainedContentMatch(
                  second.value,
                  deliveredContent: requestedContent
              ) != nil, openCodeRouteTargetMatches(target)
        else {
            return nil
        }
        return firstMatch
    }

    private func routedOpenCodeCapture(
        _ element: AXUIElement,
        initialValue: String,
        target: OpenCodeRouteTarget,
        windowStateAttestation: OpenCodeWindowStateAttestation? = nil
    ) -> TargetCapture {
        .editable(
            FocusedTarget(
                element: element,
                processIdentifier: target.processIdentifier,
                requiresExactInsertionReadback: true,
                expectedInitialValue: initialValue,
                expectedInitialValueIsEmptyComposer: true,
                requiresOpenCodeChatIdentity: true,
                floatingOpenCodeWindow: target.focusedWindow,
                floatingOpenCodeApplication: FrontmostApplicationIdentity(
                    processIdentifier: target.processIdentifier,
                    bundleIdentifier: target.bundleIdentifier,
                    bundlePath: target.bundlePath
                ),
                floatingRequiresNewSessionEvidence: true,
                openCodeV2PromptFallbackWasAttested:
                    openCodeV2PromptFallbackIsInitiallyAttested(
                        element,
                        deadline: nil
                    ),
                openCodeWindowStateAttestation: windowStateAttestation
            )
        )
    }

    private func openCodeRouteTargetMatches(
        _ target: OpenCodeRouteTarget
    ) -> Bool {
        frontmostApplicationMatches(target)
            && focusedWindowMatches(
                processIdentifier: target.processIdentifier,
                expectedWindow: target.focusedWindow,
                deadline: nil
            )
    }

    private func openCodeExpectedFocusedWindowIsRegistered(
        _ target: OpenCodeRouteTarget
    ) -> Bool {
        openCodeExpectedFocusedWindowIsRegistered(
            processIdentifier: target.processIdentifier,
            expectedWindow: target.focusedWindow
        )
    }

    private func openCodeExpectedFocusedWindowIsRegistered(
        processIdentifier: pid_t,
        expectedWindow: AXUIElement
    ) -> Bool {
        guard let application = accessibility.applicationElement(
                  for: processIdentifier
              ), let windows = accessibility.elementArrayAttribute(
                  kAXWindowsAttribute as CFString,
                  from: application,
                  maximumCount: 128
              )
        else {
            return false
        }
        // Electron exposes utility/title/menu windows alongside its browser
        // window. Those auxiliary windows are not independent chat targets.
        // Bind to the exact window captured while OpenCode was frontmost and
        // require that object to occur once in the bounded AXWindows list.
        // A second real OpenCode browser window remains rejected separately by
        // the one-window-state-file draft attestation.
        let expectedMatches = windows.filter { window in
            accessibility.elementsAreEqual(window, expectedWindow)
        }
        guard expectedMatches.count == 1,
              accessibility.processIdentifier(for: expectedMatches[0])
                == processIdentifier,
              accessibility.stringAttribute(
                  kAXRoleAttribute as CFString,
                  from: expectedMatches[0]
              ) == kAXWindowRole as String
        else {
            return false
        }
        return focusedWindowMatches(
            processIdentifier: processIdentifier,
            expectedWindow: expectedWindow,
            deadline: nil
        )
    }

    private func floatingOpenCodeTargetIsStillAttested(
        _ target: FocusedTarget,
        projectDirectory: String?
    ) -> Bool {
        guard let expectedWindow = target.floatingOpenCodeWindow,
              let expectedApplication = target.floatingOpenCodeApplication,
              accessibility.frontmostApplication() == expectedApplication,
              expectedApplication.bundleIdentifier
                == Self.openCodeBundleIdentifier,
              let bundlePath = expectedApplication.bundlePath,
              validateOpenCodeApplication(bundlePath)
        else {
            return false
        }
        if let stateAttestation = target.openCodeWindowStateAttestation {
            guard let requestedProjectDirectory = canonicalExistingDirectory(
                projectDirectory
            ), requestedProjectDirectory == stateAttestation.projectDirectory,
            openCodeExpectedFocusedWindowIsRegistered(
                processIdentifier: target.processIdentifier,
                expectedWindow: expectedWindow
            ), attestOpenCodeWindowState(requestedProjectDirectory)
                == stateAttestation
            else {
                Self.pasteLogger.error(
                    "opencode_state_attestation=rejected phase=final"
                )
                return false
            }
        }
        let canonicalProjectDirectory: String?
        if target.floatingRequiresNewSessionEvidence,
           target.openCodeWindowStateAttestation == nil
        {
            guard let projectDirectory = canonicalExistingDirectory(
                projectDirectory
            ) else {
                return false
            }
            canonicalProjectDirectory = projectDirectory
        } else {
            canonicalProjectDirectory = nil
        }
        let expectedValue = target.expectedInitialValueIsEmptyComposer
            ? ""
            : target.expectedInitialValue
        let deadline = ContinuousClock().now.advanced(
            by: .milliseconds(1_500)
        )
        guard let attestedElement = uniqueEditableElement(
            in: target.processIdentifier,
            withExactValue: expectedValue,
            requireOpenCodeChatIdentity: true,
            expectedFocusedWindow: expectedWindow,
            attestingProjectDirectory: canonicalProjectDirectory,
            requireNewSessionEvidence: (
                target.floatingRequiresNewSessionEvidence
                    && target.openCodeWindowStateAttestation == nil
            ),
            acceptOpenCodeStructuralEmptyValue: (
                target.expectedInitialValueIsEmptyComposer
            ),
            deadline: deadline
        ) else {
            return false
        }
        return accessibility.elementsAreEqual(attestedElement, target.element)
    }

    private func frontmostApplicationMatches(
        _ target: OpenCodeRouteTarget
    ) -> Bool {
        guard let current = accessibility.frontmostApplication() else {
            return false
        }
        return current.processIdentifier == target.processIdentifier
            && current.bundleIdentifier == target.bundleIdentifier
            && current.bundlePath == target.bundlePath
    }

    private func canonicalExistingDirectory(_ value: String?) -> String? {
        guard let value = value?.trimmingCharacters(
            in: .whitespacesAndNewlines
        ), value.hasPrefix("/") else {
            return nil
        }
        let url = URL(fileURLWithPath: value, isDirectory: true)
            .standardizedFileURL.resolvingSymlinksInPath()
        var isDirectory = ObjCBool(false)
        guard FileManager.default.fileExists(
            atPath: url.path,
            isDirectory: &isDirectory
        ), isDirectory.boolValue,
        FileManager.default.isReadableFile(atPath: url.path)
        else {
            return nil
        }
        return url.path
    }

    private static func readOpenCodeWindowStateAttestation(
        expectedProjectDirectory: String
    ) -> OpenCodeWindowStateAttestation? {
        guard let canonicalExpectedDirectory = canonicalReadableDirectory(
            expectedProjectDirectory
        ), let applicationSupport = FileManager.default.urls(
            for: .applicationSupportDirectory,
            in: .userDomainMask
        ).first else {
            return nil
        }
        let stateDirectory = applicationSupport.appendingPathComponent(
            "ai.opencode.desktop",
            isDirectory: true
        )
        guard let entries = try? FileManager.default.contentsOfDirectory(
            at: stateDirectory,
            includingPropertiesForKeys: nil,
            options: [.skipsHiddenFiles]
        ) else {
            return nil
        }
        let prefix = "opencode.window."
        let suffix = ".dat"
        let candidates = entries.filter { url in
            let name = url.lastPathComponent
            guard name.hasPrefix(prefix), name.hasSuffix(suffix) else {
                return false
            }
            let identifierStart = name.index(
                name.startIndex,
                offsetBy: prefix.count
            )
            let identifierEnd = name.index(
                name.endIndex,
                offsetBy: -suffix.count
            )
            return UUID(
                uuidString: String(name[identifierStart..<identifierEnd])
            ) != nil
        }
        guard candidates.count == 1,
              let fileRead = readOwnedRegularOpenCodeStateFile(
                  candidates[0]
              ), let outer = try? JSONSerialization.jsonObject(
                  with: fileRead.data,
                  options: []
              ) as? [String: Any]
        else {
            return nil
        }
        let outerKeys = Set(outer.keys)
        let requiredOuterKeys: Set<String> = ["tabs", "tabs.recent"]
        let knownOuterKeys: Set<String> = [
            "tabs",
            "tabs.recent",
            "tabs.info",
            "tabs.closed",
        ]
        guard requiredOuterKeys.isSubset(of: outerKeys),
              outerKeys.isSubset(of: knownOuterKeys),
              let tabsString = outer["tabs"] as? String,
              let recentString = outer["tabs.recent"] as? String,
              let tabsData = tabsString.data(using: .utf8),
              let recentData = recentString.data(using: .utf8),
              let tabs = try? JSONSerialization.jsonObject(
                  with: tabsData,
                  options: []
              ) as? [[String: Any]],
              tabs.count <= 64,
              let recent = try? JSONSerialization.jsonObject(
                  with: recentData,
                  options: []
              ) as? [String: Any],
              Set(recent.keys) == ["key"],
              let activeKey = recent["key"] as? String,
              !activeKey.isEmpty,
              activeKey.utf8.count <= 128
        else {
            return nil
        }

        let activeDrafts = tabs.compactMap { tab -> (String, String)? in
            guard tab["type"] as? String == "draft",
                  let draftID = tab["draftID"] as? String,
                  UUID(uuidString: draftID) != nil,
                  activeKey == "draft:\(draftID)",
                  let directory = tab["directory"] as? String,
                  let canonicalDirectory = canonicalReadableDirectory(directory)
            else {
                return nil
            }
            return (draftID, canonicalDirectory)
        }
        guard activeDrafts.count == 1,
              activeDrafts[0].1 == canonicalExpectedDirectory
        else {
            return nil
        }
        return OpenCodeWindowStateAttestation(
            filePath: candidates[0].path,
            device: fileRead.device,
            inode: fileRead.inode,
            size: fileRead.size,
            modifiedSeconds: fileRead.modifiedSeconds,
            modifiedNanoseconds: fileRead.modifiedNanoseconds,
            activeDraftID: activeDrafts[0].0,
            projectDirectory: canonicalExpectedDirectory
        )
    }

    private static func canonicalReadableDirectory(_ value: String) -> String? {
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        guard trimmed.hasPrefix("/") else { return nil }
        let url = URL(fileURLWithPath: trimmed, isDirectory: true)
            .standardizedFileURL.resolvingSymlinksInPath()
        var isDirectory = ObjCBool(false)
        guard FileManager.default.fileExists(
            atPath: url.path,
            isDirectory: &isDirectory
        ), isDirectory.boolValue,
        FileManager.default.isReadableFile(atPath: url.path)
        else {
            return nil
        }
        return url.path
    }

    private static func readOwnedRegularOpenCodeStateFile(
        _ url: URL
    ) -> OpenCodeStateFileRead? {
        let maximumBytes: off_t = 1_048_576
        let descriptor = Darwin.open(
            url.path,
            O_RDONLY | O_CLOEXEC | O_NOFOLLOW
        )
        guard descriptor >= 0 else { return nil }
        defer { Darwin.close(descriptor) }

        var before = Darwin.stat()
        guard Darwin.fstat(descriptor, &before) == 0,
              before.st_uid == Darwin.geteuid(),
              (before.st_mode & S_IFMT) == S_IFREG,
              before.st_size > 0,
              before.st_size <= maximumBytes
        else {
            return nil
        }
        let expectedCount = Int(before.st_size)
        var data = Data(count: expectedCount)
        let completelyRead = data.withUnsafeMutableBytes { buffer -> Bool in
            guard let baseAddress = buffer.baseAddress else { return false }
            var offset = 0
            while offset < expectedCount {
                let count = Darwin.read(
                    descriptor,
                    baseAddress.advanced(by: offset),
                    expectedCount - offset
                )
                if count < 0, errno == EINTR { continue }
                guard count > 0 else { return false }
                offset += count
            }
            return true
        }
        var after = Darwin.stat()
        guard completelyRead,
              Darwin.fstat(descriptor, &after) == 0,
              before.st_dev == after.st_dev,
              before.st_ino == after.st_ino,
              before.st_uid == after.st_uid,
              before.st_mode == after.st_mode,
              before.st_size == after.st_size,
              before.st_mtimespec.tv_sec == after.st_mtimespec.tv_sec,
              before.st_mtimespec.tv_nsec == after.st_mtimespec.tv_nsec,
              before.st_ctimespec.tv_sec == after.st_ctimespec.tv_sec,
              before.st_ctimespec.tv_nsec == after.st_ctimespec.tv_nsec
        else {
            return nil
        }
        return OpenCodeStateFileRead(
            data: data,
            device: UInt64(before.st_dev),
            inode: UInt64(before.st_ino),
            size: Int64(before.st_size),
            modifiedSeconds: Int64(before.st_mtimespec.tv_sec),
            modifiedNanoseconds: Int64(before.st_mtimespec.tv_nsec)
        )
    }

    private func openCodeNewSessionURL(
        projectDirectory: String,
        prompt: String
    ) -> URL? {
        guard !prompt.isEmpty else { return nil }
        var components = URLComponents()
        components.scheme = "opencode"
        components.host = "new-session"
        components.path = ""
        components.queryItems = [
            URLQueryItem(name: "directory", value: projectDirectory),
            URLQueryItem(name: "prompt", value: prompt),
        ]
        return components.url
    }

    private func newOpenCodeRouteMarker() -> String {
        "ds-" + UUID().uuidString
            .replacingOccurrences(of: "-", with: "")
            .lowercased()
    }

    private static func openOpenCodeRoute(
        _ routeURL: URL,
        _ bundlePath: String
    ) -> Bool {
        let applicationURL = URL(fileURLWithPath: bundlePath, isDirectory: true)
            .standardizedFileURL.resolvingSymlinksInPath()
        var isDirectory = ObjCBool(false)
        guard FileManager.default.fileExists(
            atPath: applicationURL.path,
            isDirectory: &isDirectory
        ), isDirectory.boolValue else {
            return false
        }
        let configuration = openCodeRouteConfiguration()
        NSWorkspace.shared.open(
            [routeURL],
            withApplicationAt: applicationURL,
            configuration: configuration,
            completionHandler: nil
        )
        return true
    }

    static func openCodeRouteConfiguration() -> NSWorkspace.OpenConfiguration {
        let configuration = NSWorkspace.OpenConfiguration()
        // The user's OpenCode action explicitly requests a foreground, fresh
        // composer. Permit this one activation. After dispatch, the route loop
        // still cancels permanently on the first app/window focus change and
        // never issues a second activation request.
        configuration.activates = true
        configuration.promptsUserIfNeeded = false
        configuration.addsToRecentItems = false
        configuration.allowsRunningApplicationSubstitution = false
        return configuration
    }

    private static func isTrustedOpenCodeApplication(
        _ bundlePath: String
    ) -> Bool {
        let claimedURL = URL(fileURLWithPath: bundlePath, isDirectory: true)
            .standardizedFileURL.resolvingSymlinksInPath()
        let applicationRoots = [
            URL(fileURLWithPath: "/Applications", isDirectory: true),
            URL(fileURLWithPath: "/System/Applications", isDirectory: true),
            FileManager.default.homeDirectoryForCurrentUser
                .appendingPathComponent("Applications", isDirectory: true),
        ]
        let matchesAuditedInstallation = applicationRoots.contains { root in
            root.appendingPathComponent("OpenCode.app", isDirectory: true)
                .standardizedFileURL.resolvingSymlinksInPath().path
                == claimedURL.path
        }
        guard matchesAuditedInstallation,
              let bundle = Bundle(url: claimedURL),
              bundle.bundleIdentifier == openCodeBundleIdentifier,
              bundle.object(
                  forInfoDictionaryKey: "CFBundleShortVersionString"
              ) as? String == "1.18.18",
              bundle.object(
                  forInfoDictionaryKey: "CFBundleVersion"
              ) as? String == "1.18.18"
        else {
            return false
        }
        return true
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
        if let stateAttestation = target.openCodeWindowStateAttestation {
            guard let expectedWindow = target.floatingOpenCodeWindow,
                  openCodeExpectedFocusedWindowIsRegistered(
                      processIdentifier: target.processIdentifier,
                      expectedWindow: expectedWindow
                  ), attestOpenCodeWindowState(
                      stateAttestation.projectDirectory
                  ) == stateAttestation
            else {
                Self.pasteLogger.error(
                    "opencode_state_attestation=rejected phase=mutation"
                )
                return false
            }
        }
        guard accessibility.frontmostApplication()?.processIdentifier
                == target.processIdentifier,
              let current = accessibility.focusedElement(),
              accessibility.processIdentifier(for: current)
                == target.processIdentifier,
              accessibility.elementsAreEqual(current, target.element),
              isEditable(current),
              !target.requiresOpenCodeChatIdentity
                || (
                    target.openCodeV2PromptFallbackWasAttested
                        ? openCodeV2PromptFallbackRemainsAttested(
                            current,
                            deadline: nil
                        )
                        : isVerifiedOpenCodeChatComposer(
                            current,
                            deadline: nil
                        )
                )
        else {
            return false
        }
        if target.requiresOpenCodeChatIdentity {
            guard let expectedWindow = target.floatingOpenCodeWindow
                    ?? focusedWindow(
                        in: target.processIdentifier,
                        deadline: nil
                    ), openCodeWindowRemainsFrontmost(
                        processIdentifier: target.processIdentifier,
                        expectedWindow: expectedWindow,
                        deadline: nil
                    ), openCodeComposerIsVisiblyPresented(
                        current,
                        in: expectedWindow,
                        processIdentifier: target.processIdentifier,
                        deadline: nil
                    )
            else {
                return false
            }
        }
        return true
    }

    private func uniqueEditableElement(
        in processIdentifier: pid_t,
        withExactValue expectedValue: String?,
        requireOpenCodeChatIdentity: Bool,
        expectedFocusedWindow: AXUIElement? = nil,
        attestingProjectDirectory expectedProjectDirectory: String? = nil,
        requireNewSessionEvidence: Bool = false,
        acceptOpenCodeStructuralEmptyValue: Bool = false,
        deadline: ContinuousClock.Instant?
    ) -> AXUIElement? {
        var matches: [AXUIElement] = []
        var deadlineExpired = false
        var activeNewSessionLinkCount = 0
        var expectedProjectLinkCount = 0
        var localNewSessionContainers: [AXUIElement] = []
        var expectedLocalProjectContainers: [AXUIElement] = []
        var activeLocalWorkspaceContainers: [AXUIElement] = []
        var activeCurrentLinkCount = 0
        var exactNewSessionDocumentCount = 0
        var visibleNewSessionProjectContainers: [AXUIElement] = []
        func appendMatchIfNeeded(
            _ element: AXUIElement,
            knownRole: String?,
            focusedWindow: AXUIElement
        ) {
            guard deadlineAllowsWork(deadline) else {
                deadlineExpired = true
                return
            }
            guard accessibility.processIdentifier(for: element)
                    == processIdentifier,
                  deadlineAllowsWork(deadline),
                  !requireOpenCodeChatIdentity
                    || isVerifiedOpenCodeChatComposer(
                        element,
                        knownRole: knownRole,
                        deadline: deadline
                    ),
                  !requireOpenCodeChatIdentity
                    || openCodeComposerIsVisiblyPresented(
                        element,
                        in: focusedWindow,
                        processIdentifier: processIdentifier,
                        deadline: deadline
                    ),
                  deadlineAllowsWork(deadline),
                  isEditable(element, deadline: deadline),
                  deadlineAllowsWork(deadline),
                  let actualValue = accessibility.stringAttribute(
                      kAXValueAttribute as CFString,
                      from: element
                  ),
                  expectedValue.map({ expectedValue in
                      actualValue == expectedValue
                        || (
                            acceptOpenCodeStructuralEmptyValue
                                && expectedValue.isEmpty
                                && isOpenCodeEmptyComposerValue(actualValue)
                        )
                  }) ?? true,
                  !matches.contains(where: {
                      accessibility.elementsAreEqual($0, element)
                  })
            else {
                return
            }
            matches.append(element)
        }

        guard let focusedWindow = focusedWindow(
            in: processIdentifier,
            deadline: deadline
        ), expectedFocusedWindow.map({ expected in
            accessibility.elementsAreEqual(expected, focusedWindow)
        }) ?? true
        else {
            return nil
        }

        var pending: [(AXUIElement, Int)] = [(focusedWindow, 0)]
        var visited = Set<AXUIElement>()
        var index = 0
        let maximumDepth = 32
        // Electron exposes many leaf nodes (static text, buttons, inputs). A
        // role-first scan can prove uniqueness without asking those leaves for
        // children, which avoids the dominant cross-process AX round trips.
        // The element and time ceilings still fail closed on an unexpectedly
        // large or unresponsive tree.
        let maximumElements = 8_192
        while index < pending.count,
              visited.count < maximumElements,
              matches.count < 2,
              deadlineAllowsWork(deadline)
        {
            let (element, depth) = pending[index]
            index += 1
            guard visited.insert(element).inserted else { continue }
            let role = accessibility.stringAttribute(
                kAXRoleAttribute as CFString,
                from: element
            )
            if role == "AXLink",
               accessibility.stringAttribute(
                   "AXARIACurrent" as CFString,
                   from: element
               )?.trimmingCharacters(in: .whitespacesAndNewlines)
                .lowercased() == "page"
            {
                // A local-mode fresh route has no active saved-session link.
                // Count every current link in the captured window so missing
                // or unusually deep AXParent data cannot hide stale state.
                activeCurrentLinkCount += 1
                if let container = openCodeLocalWorkspaceContainer(
                    containing: element,
                    processIdentifier: processIdentifier,
                    expectedWindow: focusedWindow,
                    deadline: deadline
                ) {
                    activeLocalWorkspaceContainers.append(container)
                }
                if openCodeElementNamesNewSession(element) {
                    activeNewSessionLinkCount += 1
                    if let expectedProjectDirectory,
                       openCodeNewSessionLinkPath(
                           for: expectedProjectDirectory
                       ) == accessibility.stringAttribute(
                           kAXURLAttribute as CFString,
                           from: element
                       ).flatMap(openCodeURLPath)
                    {
                        expectedProjectLinkCount += 1
                    }
                }
            }
            if let expectedProjectDirectory,
               role == "AXWebArea",
               openCodeNewSessionLinkPath(for: expectedProjectDirectory)
                == accessibility.stringAttribute(
                    kAXURLAttribute as CFString,
                    from: element
                ).flatMap(openCodeURLPath)
            {
                // In OpenCode's compact landing layout the project sidebar is
                // absent, but Chromium exposes the current SPA document URL.
                // Its directory-derived slug is exact project identity and the
                // bare /session route is fresh-new-session evidence. Count the
                // complete focused-window tree so duplicate documents fail.
                exactNewSessionDocumentCount += 1
            }
            if let expectedProjectDirectory,
               role == kAXStaticTextRole as String,
               let container = openCodeVisibleNewSessionProjectContainer(
                   containing: element,
                   projectDirectory: expectedProjectDirectory,
                   processIdentifier: processIdentifier,
                   expectedWindow: focusedWindow,
                   deadline: deadline
               ), !visibleNewSessionProjectContainers.contains(where: {
                   accessibility.elementsAreEqual($0, container)
               })
            {
                visibleNewSessionProjectContainers.append(container)
            }
            if role == "AXButton",
               openCodeElementNamesNewSession(element),
               let container = openCodeLocalWorkspaceContainer(
                   containing: element,
                   processIdentifier: processIdentifier,
                   expectedWindow: focusedWindow,
                   deadline: deadline
               )
            {
                localNewSessionContainers.append(container)
            }
            if let expectedProjectDirectory,
               role == kAXStaticTextRole as String,
               openCodeElement(
                   element,
                   displaysProjectDirectory: expectedProjectDirectory
               ),
               let container = openCodeLocalWorkspaceContainer(
                   containing: element,
                   processIdentifier: processIdentifier,
                   expectedWindow: focusedWindow,
                   deadline: deadline
               ), let directParent = accessibility.elementAttribute(
                   kAXParentAttribute as CFString,
                   from: element
               ), accessibility.elementsAreEqual(directParent, container),
               openCodeElementIsLocalProjectPath(
                   element,
                   in: container,
                   deadline: deadline
               )
            {
                // The canonical project path is the local-workspace header's
                // direct text child. Session titles are nested inside links
                // and must never be accepted as project identity, even if a
                // user renames one to look exactly like a filesystem path.
                expectedLocalProjectContainers.append(container)
            }
            appendMatchIfNeeded(
                element,
                knownRole: role,
                focusedWindow: focusedWindow
            )
            if deadlineExpired { return nil }
            guard depth < maximumDepth else {
                // A shallow match is not unique if the scan simply stops at
                // its depth ceiling. Prove the capped node has no children;
                // any child (or an unbounded/unreadable child list) makes the
                // traversal incomplete and therefore unsafe.
                guard let children = accessibility.elementArrayAttribute(
                    kAXChildrenAttribute as CFString,
                    from: element,
                    maximumCount: 1
                ), children.isEmpty else {
                    return nil
                }
                continue
            }
            guard !isKnownAccessibilityLeaf(role) else { continue }
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
        let exactActiveLinkEvidence = activeCurrentLinkCount == 1
            && activeNewSessionLinkCount == 1
            && expectedProjectLinkCount == 1
        let exactLocalWorkspaceBaseEvidence = localNewSessionContainers.count == 1
            && expectedLocalProjectContainers.count == 1
            && accessibility.elementsAreEqual(
                localNewSessionContainers[0],
                expectedLocalProjectContainers[0]
            )
        let exactScopedRetainedSessionEvidence = activeCurrentLinkCount == 1
            && activeLocalWorkspaceContainers.count == 1
            && exactLocalWorkspaceBaseEvidence
            && accessibility.elementsAreEqual(
                activeLocalWorkspaceContainers[0],
                expectedLocalProjectContainers[0]
            )
        // Project identity and new-session freshness are separate facts. A
        // retained active session can still be bound to the exact requested
        // local workspace, but only a workspace with no active session is a
        // fresh target that may receive new content.
        let exactLocalProjectEvidence = exactLocalWorkspaceBaseEvidence
            && (
                activeCurrentLinkCount == 0
                    || exactScopedRetainedSessionEvidence
            )
        let exactLocalNewSessionEvidence = exactLocalWorkspaceBaseEvidence
            && activeCurrentLinkCount == 0
        let exactDocumentNewSessionEvidence =
            exactNewSessionDocumentCount == 1
        // The audited 1.18.18 NewSessionView uniquely renders the canonical
        // project root as the direct parent-directory + filename text pair.
        // Its visible title varies between "Build anything" and the wordmark,
        // so the exact split path—not localized/decorative title text—is the
        // stable landing-page identity.
        let exactVisibleNewSessionLandingEvidence =
            visibleNewSessionProjectContainers.count == 1
        let requestedProjectIsAttested = expectedProjectDirectory == nil
            || exactActiveLinkEvidence
            || exactLocalProjectEvidence
            || exactDocumentNewSessionEvidence
            || exactVisibleNewSessionLandingEvidence
        let requestedNewSessionIsAttested = !requireNewSessionEvidence
            || (
                expectedProjectDirectory == nil
                    ? activeCurrentLinkCount == 1
                        && activeNewSessionLinkCount == 1
                    : exactActiveLinkEvidence
                        || exactLocalNewSessionEvidence
                        || exactDocumentNewSessionEvidence
                        || exactVisibleNewSessionLandingEvidence
            )
        guard !deadlineExpired,
              deadlineAllowsWork(deadline),
              index >= pending.count,
              requestedNewSessionIsAttested,
              requestedProjectIsAttested,
              focusedWindowMatches(
                  processIdentifier: processIdentifier,
                  expectedWindow: focusedWindow,
                  deadline: deadline
              )
        else {
            return nil
        }
        return matches.count == 1 ? matches[0] : nil
    }

    private func openCodeElementNamesNewSession(
        _ element: AXUIElement
    ) -> Bool {
        let accessibleNames = [
            accessibility.stringAttribute(
                kAXValueAttribute as CFString,
                from: element
            ),
            accessibility.stringAttribute(
                kAXTitleAttribute as CFString,
                from: element
            ),
            accessibility.stringAttribute(
                kAXDescriptionAttribute as CFString,
                from: element
            ),
            accessibility.stringAttribute(
                kAXHelpAttribute as CFString,
                from: element
            ),
        ].compactMap { value in
            value?.trimmingCharacters(in: .whitespacesAndNewlines)
        }
        return accessibleNames.contains { value in
            value.caseInsensitiveCompare("New session") == .orderedSame
        }
    }

    private func openCodeVisibleNewSessionProjectContainer(
        containing element: AXUIElement,
        projectDirectory: String,
        processIdentifier: pid_t,
        expectedWindow: AXUIElement,
        deadline: ContinuousClock.Instant?
    ) -> AXUIElement? {
        guard deadlineAllowsWork(deadline),
              accessibility.processIdentifier(for: element)
                == processIdentifier,
              openCodeComposerIsVisiblyPresented(
                  element,
                  in: expectedWindow,
                  processIdentifier: processIdentifier,
                  deadline: deadline
              ), let parent = accessibility.elementAttribute(
                  kAXParentAttribute as CFString,
                  from: element
              ), !accessibility.elementsAreEqual(parent, expectedWindow),
              accessibility.processIdentifier(for: parent) == processIdentifier,
              let siblings = accessibility.elementArrayAttribute(
                  kAXChildrenAttribute as CFString,
                  from: parent,
                  maximumCount: 16
              )
        else {
            return nil
        }

        // OpenCode 1.18.18's compact NewSessionView renders the authoritative
        // project root as two adjacent text nodes: its parent directory and a
        // nested filename span. The older sidebar renders it as one text node.
        // Reconstruct only direct, visibly presented static-text siblings in
        // DOM order; unrelated titles elsewhere in the window cannot combine.
        let visibleText = siblings.compactMap { sibling -> String? in
            guard accessibility.stringAttribute(
                    kAXRoleAttribute as CFString,
                    from: sibling
                  ) == kAXStaticTextRole as String,
                  openCodeComposerIsVisiblyPresented(
                      sibling,
                      in: expectedWindow,
                      processIdentifier: processIdentifier,
                      deadline: deadline
                  )
            else {
                return nil
            }
            return [
                accessibility.stringAttribute(
                    kAXValueAttribute as CFString,
                    from: sibling
                ),
                accessibility.stringAttribute(
                    kAXTitleAttribute as CFString,
                    from: sibling
                ),
                accessibility.stringAttribute(
                    kAXDescriptionAttribute as CFString,
                    from: sibling
                ),
            ].compactMap { value in
                value?.trimmingCharacters(in: .whitespacesAndNewlines)
            }.first(where: { !$0.isEmpty })
        }
        guard !visibleText.isEmpty else { return nil }
        let reconstructed = visibleText.joined()
        return openCodeProjectDirectoryDisplays(projectDirectory).contains(
            reconstructed
        ) ? parent : nil
    }

    private func openCodeElement(
        _ element: AXUIElement,
        displaysProjectDirectory canonicalProjectDirectory: String
    ) -> Bool {
        let expectedDisplays = openCodeProjectDirectoryDisplays(
            canonicalProjectDirectory
        )
        let values = [
            accessibility.stringAttribute(
                kAXValueAttribute as CFString,
                from: element
            ),
            accessibility.stringAttribute(
                kAXTitleAttribute as CFString,
                from: element
            ),
            accessibility.stringAttribute(
                kAXDescriptionAttribute as CFString,
                from: element
            ),
            accessibility.stringAttribute(
                kAXHelpAttribute as CFString,
                from: element
            ),
        ].compactMap { value in
            value?.trimmingCharacters(in: .whitespacesAndNewlines)
        }
        return values.contains(where: expectedDisplays.contains)
    }

    private func openCodeElementIsLocalProjectPath(
        _ element: AXUIElement,
        in container: AXUIElement,
        deadline: ContinuousClock.Instant?
    ) -> Bool {
        guard deadlineAllowsWork(deadline),
              let siblings = accessibility.elementArrayAttribute(
                  kAXChildrenAttribute as CFString,
                  from: container,
                  maximumCount: 32
              ),
              let index = siblings.firstIndex(where: { sibling in
                  accessibility.elementsAreEqual(sibling, element)
              }),
              index > siblings.startIndex,
              siblings.index(after: index) < siblings.endIndex
        else {
            return false
        }
        let previous = siblings[siblings.index(before: index)]
        let next = siblings[siblings.index(after: index)]
        // Chromium omits AXDOMClassList on both header text spans. Its stable
        // native hierarchy still distinguishes them: the user-editable project
        // name is the preceding AXStaticText, the canonical path is this text,
        // and the project options pop-up follows it. A path-shaped project name
        // or nested saved-session title therefore cannot impersonate authority.
        return accessibility.stringAttribute(
            kAXRoleAttribute as CFString,
            from: previous
        ) == kAXStaticTextRole as String
            && accessibility.stringAttribute(
                kAXRoleAttribute as CFString,
                from: next
            ) == kAXPopUpButtonRole as String
    }

    private func openCodeProjectDirectoryDisplays(
        _ canonicalProjectDirectory: String
    ) -> Set<String> {
        var values: Set<String> = [canonicalProjectDirectory]
        let homeDirectory = FileManager.default.homeDirectoryForCurrentUser
            .standardizedFileURL.resolvingSymlinksInPath().path
        if canonicalProjectDirectory == homeDirectory {
            values.insert("~")
        } else if canonicalProjectDirectory.hasPrefix(homeDirectory + "/") {
            values.insert(
                "~" + canonicalProjectDirectory.dropFirst(homeDirectory.count)
            )
        }
        return values
    }

    private func openCodeLocalWorkspaceContainer(
        containing element: AXUIElement,
        processIdentifier: pid_t,
        expectedWindow: AXUIElement,
        deadline: ContinuousClock.Instant?
    ) -> AXUIElement? {
        var current = element
        var visited: [AXUIElement] = []
        for _ in 0..<16 {
            guard deadlineAllowsWork(deadline),
                  let parent = accessibility.elementAttribute(
                      kAXParentAttribute as CFString,
                      from: current
                  ),
                  accessibility.processIdentifier(for: parent)
                    == processIdentifier,
                  !visited.contains(where: {
                      accessibility.elementsAreEqual($0, parent)
                  })
            else {
                return nil
            }
            if accessibility.elementsAreEqual(parent, expectedWindow) {
                return nil
            }
            let parentRole = accessibility.stringAttribute(
                kAXRoleAttribute as CFString,
                from: parent
            )
            let parentDescription = accessibility.stringAttribute(
                kAXDescriptionAttribute as CFString,
                from: parent
            )?.trimmingCharacters(in: .whitespacesAndNewlines)
            if parentRole == kAXGroupRole as String,
               parentDescription?.caseInsensitiveCompare("Projects and sessions")
                == .orderedSame
            {
                // The region also lists inactive projects. Authority comes
                // from the local-workspace group immediately beneath it: the
                // exact path and New-session button must share that group.
                return accessibility.stringAttribute(
                    kAXRoleAttribute as CFString,
                    from: current
                ) == kAXGroupRole as String ? current : nil
            }
            visited.append(parent)
            current = parent
        }
        return nil
    }

    private func isOpenCodeEmptyComposerValue(_ value: String) -> Bool {
        // OpenCode 1.18.18 PromptInputV2 uses an exact U+200B structural
        // placeholder for an otherwise empty contenteditable. Chromium may
        // expose that marker through AXValue, optionally followed by its
        // structural line feed. Keep this finite so ordinary whitespace and
        // user-authored drafts never become "empty" by normalization.
        switch value {
        case "", "\n", "\u{200B}", "\u{200B}\n":
            return true
        default:
            return false
        }
    }

    private func openCodeRetainedContentMatch(
        _ value: String,
        deliveredContent: String
    ) -> OpenCodeRetainedContentMatch? {
        if value == deliveredContent {
            return .exact
        }
        // A failed build of the old input-sync handshake could leave exactly
        // its one typed sentinel immediately before Chromium's structural
        // terminal line feed. Recognize only that exact representation so the
        // caller can stop before routing or mutation and require review. No
        // trimming or broader whitespace equivalence is allowed.
        guard openCodeStructuralSentinelReadback(
            for: deliveredContent
        )?.value == value else {
            return nil
        }
        return .legacySyncResidue
    }

    private func openCodeComposerIsVisiblyPresented(
        _ element: AXUIElement,
        in expectedWindow: AXUIElement,
        processIdentifier: pid_t,
        deadline: ContinuousClock.Instant?
    ) -> Bool {
        openCodeComposerPresentationFailure(
            element,
            in: expectedWindow,
            processIdentifier: processIdentifier,
            deadline: deadline
        ) == nil
    }

    private func openCodeComposerPresentationFailure(
        _ element: AXUIElement,
        in expectedWindow: AXUIElement,
        processIdentifier: pid_t,
        deadline: ContinuousClock.Instant?
    ) -> OpenCodeComposerPresentationFailure? {
        guard deadlineAllowsWork(deadline) else { return .deadline }
        guard let windowFrame = accessibility.frame(of: expectedWindow)
        else {
            return .windowFrameMissing
        }
        guard let composerFrame = accessibility.frame(of: element) else {
            return .composerFrameMissing
        }
        guard frameIsFiniteAndPositive(windowFrame) else {
            return .windowFrameInvalid
        }
        guard frameIsFiniteAndPositive(composerFrame) else {
            return .composerFrameInvalid
        }
        let intersection = windowFrame.intersection(composerFrame)
        let composerCenter = CGPoint(
            x: composerFrame.midX,
            y: composerFrame.midY
        )
        guard !intersection.isNull,
              intersection.width > 1,
              intersection.height > 1,
              windowFrame.contains(composerCenter)
        else {
            return .outsideWindow
        }

        // Electron can retain accessibility nodes for inactive tabs and
        // unmounted routes. If either native ownership attribute is exposed,
        // it must name this exact focused window. A bounded parent walk is
        // still required so a stale node cannot borrow window-global project
        // or New-session evidence from the active landing page.
        guard let windowOwner = accessibility.elementAttribute(
            kAXWindowAttribute as CFString,
            from: element
        ) else {
            return .windowOwnerMissing
        }
        guard accessibility.elementsAreEqual(windowOwner, expectedWindow)
        else {
            return .windowOwnerMismatch
        }
        let hitTestVisible = accessibility.elementIsHitTestVisible(
            element,
            at: composerCenter,
            processIdentifier: processIdentifier
        )
        if !hitTestVisible {
            // PromptInputV2 can place its visible placeholder/control overlay
            // over the contenteditable, so Chromium may return that sibling
            // from a center hit-test. Accept this only when macOS identifies
            // this exact editor as focused; window ownership, geometry, and
            // the bounded parent chain remain mandatory below.
            guard let focused = accessibility.focusedElement(),
                  accessibility.processIdentifier(for: focused)
                    == processIdentifier,
                  accessibility.elementsAreEqual(focused, element)
            else {
                return .hitTest
            }
        }
        if let topLevelOwner = accessibility.elementAttribute(
            "AXTopLevelUIElement" as CFString,
            from: element
        ), !accessibility.elementsAreEqual(topLevelOwner, expectedWindow) {
            return .topLevelOwnerMismatch
        }

        var current = element
        var visited: [AXUIElement] = []
        for _ in 0..<48 {
            guard deadlineAllowsWork(deadline) else { return .deadline }
            guard accessibility.processIdentifier(for: current)
                    == processIdentifier
            else {
                return .processOwnerMismatch
            }
            if accessibility.boolAttribute(
                "AXHidden" as CFString,
                from: current
            ) == true {
                return .hidden
            }
            if accessibility.boolAttribute(
                "AXVisible" as CFString,
                from: current
            ) == false {
                return .invisible
            }
            if accessibility.elementsAreEqual(current, expectedWindow) {
                return nil
            }
            guard let parent = accessibility.elementAttribute(
                kAXParentAttribute as CFString,
                from: current
            ) else {
                return .parentMissing
            }
            guard !visited.contains(where: {
                accessibility.elementsAreEqual($0, parent)
            }) else {
                return .parentCycle
            }
            visited.append(current)
            current = parent
        }
        return .parentDepth
    }

    private func frameIsFiniteAndPositive(_ frame: CGRect) -> Bool {
        frame.origin.x.isFinite
            && frame.origin.y.isFinite
            && frame.width.isFinite
            && frame.height.isFinite
            && frame.width > 1
            && frame.height > 1
    }

    private func isVerifiedOpenCodeChatComposer(
        _ element: AXUIElement,
        knownRole: String? = nil,
        deadline: ContinuousClock.Instant?
    ) -> Bool {
        guard deadlineAllowsWork(deadline) else { return false }
        let role = knownRole ?? accessibility.stringAttribute(
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
        let hasExactV2PromptName = accessibleNames.contains("prompt")
        guard deadlineAllowsWork(deadline) else { return false }
        let domClassList = accessibility.stringArrayAttribute(
            "AXDOMClassList" as CFString,
            from: element
        )
        let domClasses = Set(domClassList ?? [])
        guard !domClasses.contains("font-mono!") else { return false }
        let normalPromptClassSignature: Set<String> = [
            "select-text",
            "w-full",
            "text-14-regular",
            "whitespace-pre-wrap",
        ]
        let hasNormalPromptClassSignature = normalPromptClassSignature
            .isSubset(of: domClasses)
        // OpenCode 1.18's PromptInputV2 changed both the accessible label and
        // the Tailwind signature. Keep the class proof deliberately narrow:
        // `Prompt` is shared by normal and shell modes and therefore cannot be
        // the sole identity. These tokens exclude the terminal/search inputs
        // that can coexist in the same window.
        let normalV2PromptClassSignature: Set<String> = [
            "min-h-[60px]",
            "max-h-[180px]",
            "w-full",
            "overflow-y-auto",
            "whitespace-pre-wrap",
            "text-v2-text-text-base",
            "focus:outline-none",
        ]
        let hasNormalV2PromptClassSignature = normalV2PromptClassSignature
            .isSubset(of: domClasses)
        // Chromium does not expose AXDOMClassList on every macOS build. The
        // audited 1.18.18 V2 editor's accessible name is exactly `Prompt` in
        // both normal and shell modes, so that name is accepted only for an
        // AXTextArea whose empty-state normal placeholder is structurally and
        // geometrically bound to the editor. The shell placeholder is an
        // explicit rejection. If neither placeholder is exposed, fail closed.
        let hasAttestedV2PromptWithoutDOMClasses = domClassList == nil
            && role == kAXTextAreaRole as String
            && hasExactV2PromptName
            && openCodeV2PromptHasBoundNormalPlaceholder(
                element,
                deadline: deadline
            )
        return hasKnownNormalPromptName
            || hasNormalPromptClassSignature
            || hasNormalV2PromptClassSignature
            || hasAttestedV2PromptWithoutDOMClasses
    }

    private func openCodeV2PromptFallbackIsInitiallyAttested(
        _ editor: AXUIElement,
        deadline: ContinuousClock.Instant?
    ) -> Bool {
        guard deadlineAllowsWork(deadline),
              accessibility.stringAttribute(
                kAXRoleAttribute as CFString,
                from: editor
              ) == kAXTextAreaRole as String,
              accessibility.stringArrayAttribute(
                "AXDOMClassList" as CFString,
                from: editor
              ) == nil
        else {
            return false
        }
        let names = openCodeNormalizedAccessibleNames(editor)
        guard names.contains("prompt"),
              !names.contains(where: {
                $0.contains("terminal input") || $0.contains("shell command")
              })
        else {
            return false
        }
        return openCodeV2PromptHasBoundNormalPlaceholder(
            editor,
            deadline: deadline
        )
    }

    private func openCodeV2PromptFallbackRemainsAttested(
        _ editor: AXUIElement,
        deadline: ContinuousClock.Instant?
    ) -> Bool {
        guard deadlineAllowsWork(deadline),
              accessibility.stringAttribute(
                kAXRoleAttribute as CFString,
                from: editor
              ) == kAXTextAreaRole as String
        else {
            return false
        }
        let names = openCodeNormalizedAccessibleNames(editor)
        guard names.contains("prompt"),
              !names.contains(where: {
                $0.contains("terminal input") || $0.contains("shell command")
              })
        else {
            return false
        }
        if let domClassList = accessibility.stringArrayAttribute(
            "AXDOMClassList" as CFString,
            from: editor
        ) {
            let domClasses = Set(domClassList)
            guard !domClasses.contains("font-mono!") else { return false }
            let normalV2PromptClassSignature: Set<String> = [
                "min-h-[60px]",
                "max-h-[180px]",
                "w-full",
                "overflow-y-auto",
                "whitespace-pre-wrap",
                "text-v2-text-text-base",
                "focus:outline-none",
            ]
            return normalV2PromptClassSignature.isSubset(of: domClasses)
        }
        return openCodeV2PromptHasBoundNormalPlaceholder(
            editor,
            deadline: deadline
        ) || openCodeV2PromptHasBoundNormalControl(
            editor,
            deadline: deadline
        )
    }

    private func openCodeNormalizedAccessibleNames(
        _ element: AXUIElement
    ) -> [String] {
        [
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
    }

    private func openCodeV2PromptHasBoundNormalPlaceholder(
        _ editor: AXUIElement,
        deadline: ContinuousClock.Instant?
    ) -> Bool {
        guard deadlineAllowsWork(deadline),
              let processIdentifier = accessibility.processIdentifier(
                  for: editor
              ), let editorFrame = accessibility.frame(of: editor),
              frameIsFiniteAndPositive(editorFrame)
        else {
            return false
        }
        let normalPlaceholder =
            "ask anything, / for commands, @ for context..."
        let shellPlaceholder = "enter shell command..."
        var current = editor
        var ancestors: [AXUIElement] = [editor]

        // The V2 DOM places the contenteditable and its empty-state placeholder
        // under the same relative container. Chromium may flatten one or more
        // generic DOM wrappers in AX, so inspect a small bounded neighborhood
        // at each of the first four ancestors. Frame overlap prevents matching
        // identical text elsewhere in the window.
        for _ in 0..<4 {
            guard deadlineAllowsWork(deadline),
                  let parent = accessibility.elementAttribute(
                      kAXParentAttribute as CFString,
                      from: current
                  ), accessibility.processIdentifier(for: parent)
                    == processIdentifier,
                  !ancestors.contains(where: {
                      accessibility.elementsAreEqual($0, parent)
                  })
            else {
                return false
            }
            ancestors.append(parent)

            var pending: [(AXUIElement, Int)] = [(parent, 0)]
            var visited = Set<AXUIElement>()
            var index = 0
            var normalMatchCount = 0
            var shellMatchCount = 0
            let maximumElements = 128
            let maximumDepth = 3
            while index < pending.count,
                  visited.count < maximumElements,
                  deadlineAllowsWork(deadline)
            {
                let (candidate, depth) = pending[index]
                index += 1
                guard visited.insert(candidate).inserted else { continue }
                let candidateRole = accessibility.stringAttribute(
                    kAXRoleAttribute as CFString,
                    from: candidate
                )
                if candidateRole == kAXStaticTextRole as String,
                   accessibility.processIdentifier(for: candidate)
                    == processIdentifier,
                   accessibility.boolAttribute(
                    "AXHidden" as CFString,
                    from: candidate
                   ) != true,
                   accessibility.boolAttribute(
                    "AXVisible" as CFString,
                    from: candidate
                   ) != false,
                   let candidateFrame = accessibility.frame(of: candidate),
                   frameIsFiniteAndPositive(candidateFrame)
                {
                    let intersection = editorFrame.intersection(candidateFrame)
                    if !intersection.isNull,
                       intersection.width > 1,
                       intersection.height > 1
                    {
                        let names = [
                            accessibility.stringAttribute(
                                kAXValueAttribute as CFString,
                                from: candidate
                            ),
                            accessibility.stringAttribute(
                                kAXDescriptionAttribute as CFString,
                                from: candidate
                            ),
                            accessibility.stringAttribute(
                                kAXTitleAttribute as CFString,
                                from: candidate
                            ),
                        ].compactMap { value in
                            value?.trimmingCharacters(
                                in: .whitespacesAndNewlines
                            ).lowercased()
                        }
                        if names.contains(normalPlaceholder) {
                            normalMatchCount += 1
                        }
                        if names.contains(shellPlaceholder) {
                            shellMatchCount += 1
                        }
                    }
                }
                guard depth < maximumDepth,
                      !isKnownAccessibilityLeaf(candidateRole),
                      let children = accessibility.elementArrayAttribute(
                        kAXChildrenAttribute as CFString,
                        from: candidate,
                        maximumCount: maximumElements - pending.count
                      )
                else {
                    continue
                }
                pending.append(contentsOf: children.map { ($0, depth + 1) })
            }
            guard deadlineAllowsWork(deadline),
                  index >= pending.count,
                  visited.count < maximumElements,
                  shellMatchCount == 0,
                  normalMatchCount <= 1
            else {
                return false
            }
            if normalMatchCount == 1 { return true }
            current = parent
        }
        return false
    }

    private func openCodeV2PromptHasBoundNormalControl(
        _ editor: AXUIElement,
        deadline: ContinuousClock.Instant?
    ) -> Bool {
        guard deadlineAllowsWork(deadline),
              let processIdentifier = accessibility.processIdentifier(
                for: editor
              ), let editorFrame = accessibility.frame(of: editor),
              frameIsFiniteAndPositive(editorFrame)
        else {
            return false
        }
        var current = editor
        var ancestors: [AXUIElement] = [editor]

        // In audited OpenCode 1.18.18 normal mode, the prompt's left control
        // row exposes this exact button. Shell mode sets the whole row
        // aria-hidden and inert. Bind the button to the editor through a small
        // common-ancestor neighborhood and screen proximity; an identically
        // named control elsewhere in the window cannot satisfy this proof.
        for _ in 0..<4 {
            guard deadlineAllowsWork(deadline),
                  let parent = accessibility.elementAttribute(
                    kAXParentAttribute as CFString,
                    from: current
                  ), accessibility.processIdentifier(for: parent)
                    == processIdentifier,
                  !ancestors.contains(where: {
                    accessibility.elementsAreEqual($0, parent)
                  })
            else {
                return false
            }
            ancestors.append(parent)

            var pending: [(AXUIElement, Int)] = [(parent, 0)]
            var visited = Set<AXUIElement>()
            var index = 0
            var normalControlMatchCount = 0
            var shellPlaceholderMatchCount = 0
            let maximumElements = 128
            let maximumDepth = 4
            while index < pending.count,
                  visited.count < maximumElements,
                  deadlineAllowsWork(deadline)
            {
                let (candidate, depth) = pending[index]
                index += 1
                guard visited.insert(candidate).inserted else { continue }
                let candidateRole = accessibility.stringAttribute(
                    kAXRoleAttribute as CFString,
                    from: candidate
                )
                if accessibility.processIdentifier(for: candidate)
                    == processIdentifier,
                   accessibility.boolAttribute(
                    "AXHidden" as CFString,
                    from: candidate
                   ) != true,
                   accessibility.boolAttribute(
                    "AXVisible" as CFString,
                    from: candidate
                   ) != false,
                   let candidateFrame = accessibility.frame(of: candidate),
                   frameIsFiniteAndPositive(candidateFrame)
                {
                    let names = [
                        accessibility.stringAttribute(
                            kAXValueAttribute as CFString,
                            from: candidate
                        ),
                        accessibility.stringAttribute(
                            kAXDescriptionAttribute as CFString,
                            from: candidate
                        ),
                        accessibility.stringAttribute(
                            kAXTitleAttribute as CFString,
                            from: candidate
                        ),
                        accessibility.stringAttribute(
                            kAXHelpAttribute as CFString,
                            from: candidate
                        ),
                    ].compactMap { value in
                        value?.trimmingCharacters(
                            in: .whitespacesAndNewlines
                        ).lowercased()
                    }
                    if candidateRole == kAXStaticTextRole as String {
                        let intersection = editorFrame.intersection(
                            candidateFrame
                        )
                        if !intersection.isNull,
                           intersection.width > 1,
                           intersection.height > 1,
                           names.contains("enter shell command...")
                        {
                            shellPlaceholderMatchCount += 1
                        }
                    }
                    if candidateRole == kAXButtonRole as String,
                       accessibility.boolAttribute(
                        kAXEnabledAttribute as CFString,
                        from: candidate
                       ) != false,
                       names.contains("add images and files"),
                       openCodePromptControlFrame(
                        candidateFrame,
                        isNear: editorFrame
                       )
                    {
                        normalControlMatchCount += 1
                    }
                }
                guard depth < maximumDepth,
                      !isKnownAccessibilityLeaf(candidateRole),
                      let children = accessibility.elementArrayAttribute(
                        kAXChildrenAttribute as CFString,
                        from: candidate,
                        maximumCount: maximumElements - pending.count
                      )
                else {
                    continue
                }
                pending.append(contentsOf: children.map { ($0, depth + 1) })
            }
            guard deadlineAllowsWork(deadline),
                  index >= pending.count,
                  visited.count < maximumElements,
                  shellPlaceholderMatchCount == 0,
                  normalControlMatchCount <= 1
            else {
                return false
            }
            if normalControlMatchCount == 1 { return true }
            current = parent
        }
        return false
    }

    private func openCodePromptControlFrame(
        _ controlFrame: CGRect,
        isNear editorFrame: CGRect
    ) -> Bool {
        let horizontalOverlap = min(controlFrame.maxX, editorFrame.maxX)
            - max(controlFrame.minX, editorFrame.minX)
        let verticalGap = max(
            0,
            max(
                editorFrame.minY - controlFrame.maxY,
                controlFrame.minY - editorFrame.maxY
            )
        )
        return horizontalOverlap > 1 && verticalGap <= 96
    }

    private func isKnownAccessibilityLeaf(_ role: String?) -> Bool {
        guard let role else { return false }
        // Only roles that cannot contain an independent chat-composer target
        // are pruned. Unknown and structural roles are still traversed, so
        // uniqueness is never inferred from a partial role taxonomy.
        let knownLeafRoles: Set<String> = [
            "AXButton",
            "AXCheckBox",
            "AXImage",
            "AXLink",
            "AXMenuItem",
            "AXRadioButton",
            "AXSlider",
            "AXStaticText",
            "AXTextArea",
            "AXTextField",
        ]
        return knownLeafRoles.contains(role)
    }

    private func openCodeNewSessionLinkPath(
        for canonicalProjectDirectory: String
    ) -> String {
        let slug = Data(canonicalProjectDirectory.utf8).base64EncodedString()
            .replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "=", with: "")
        return "/\(slug)/session"
    }

    private func openCodeURLPath(_ value: String) -> String? {
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return nil }
        if trimmed.hasPrefix("/") {
            return URLComponents(
                string: "https://opencode.invalid\(trimmed)"
            )?.path
        }
        return URLComponents(string: trimmed)?.path
    }

    private func focusedWindow(
        in processIdentifier: pid_t,
        deadline: ContinuousClock.Instant?
    ) -> AXUIElement? {
        guard deadlineAllowsWork(deadline),
              let application = accessibility.applicationElement(
                  for: processIdentifier
              ),
              deadlineAllowsWork(deadline),
              let window = accessibility.elementAttribute(
                  kAXFocusedWindowAttribute as CFString,
                  from: application
              ),
              deadlineAllowsWork(deadline),
              accessibility.processIdentifier(for: window) == processIdentifier,
              !accessibility.elementsAreEqual(application, window),
              accessibility.stringAttribute(
                  kAXRoleAttribute as CFString,
                  from: window
              ) == kAXWindowRole as String
        else {
            return nil
        }
        return window
    }

    private func focusedWindowMatches(
        processIdentifier: pid_t,
        expectedWindow: AXUIElement,
        deadline: ContinuousClock.Instant?
    ) -> Bool {
        guard let current = focusedWindow(
            in: processIdentifier,
            deadline: deadline
        ) else {
            return false
        }
        return accessibility.elementsAreEqual(current, expectedWindow)
    }

    private func focusAndVerify(
        _ element: AXUIElement,
        processIdentifier: pid_t,
        expectedOpenCodeWindow: AXUIElement? = nil,
        deadline: ContinuousClock.Instant?
    ) -> Bool {
        guard deadlineAllowsWork(deadline),
              expectedOpenCodeWindow.map({ expectedWindow in
                  openCodeWindowRemainsFrontmost(
                      processIdentifier: processIdentifier,
                      expectedWindow: expectedWindow,
                      deadline: deadline
                  )
              }) ?? true,
              expectedOpenCodeWindow.map({ expectedWindow in
                  openCodeComposerIsVisiblyPresented(
                      element,
                      in: expectedWindow,
                      processIdentifier: processIdentifier,
                      deadline: deadline
                  )
              }) ?? true
        else {
            return false
        }
        if let focused = accessibility.focusedElement(),
           accessibility.processIdentifier(for: focused) == processIdentifier,
           accessibility.elementsAreEqual(focused, element)
        {
            return true
        }
        let attribute = kAXFocusedAttribute as CFString
        guard deadlineAllowsWork(deadline),
              expectedOpenCodeWindow.map({ expectedWindow in
                  openCodeWindowRemainsFrontmost(
                      processIdentifier: processIdentifier,
                      expectedWindow: expectedWindow,
                      deadline: deadline
                  )
              }) ?? true,
              accessibility.isAttributeSettable(attribute, on: element),
              deadlineAllowsWork(deadline),
              expectedOpenCodeWindow.map({ expectedWindow in
                  openCodeWindowRemainsFrontmost(
                      processIdentifier: processIdentifier,
                      expectedWindow: expectedWindow,
                      deadline: deadline
                  )
              }) ?? true,
              accessibility.setAttribute(
                  attribute,
                  to: kCFBooleanTrue,
                  on: element
              ) == .success,
              deadlineAllowsWork(deadline),
              expectedOpenCodeWindow.map({ expectedWindow in
                  openCodeWindowRemainsFrontmost(
                      processIdentifier: processIdentifier,
                      expectedWindow: expectedWindow,
                      deadline: deadline
                  ) && openCodeComposerIsVisiblyPresented(
                    element,
                    in: expectedWindow,
                    processIdentifier: processIdentifier,
                    deadline: deadline
                  )
              }) ?? true,
              let focused = accessibility.focusedElement(),
              accessibility.processIdentifier(for: focused) == processIdentifier,
              accessibility.elementsAreEqual(focused, element)
        else {
            return false
        }
        return true
    }

    private func openCodeWindowRemainsFrontmost(
        processIdentifier: pid_t,
        expectedWindow: AXUIElement,
        deadline: ContinuousClock.Instant?
    ) -> Bool {
        guard deadlineAllowsWork(deadline),
              let frontmost = accessibility.frontmostApplication(),
              frontmost.processIdentifier == processIdentifier,
              frontmost.bundleIdentifier == Self.openCodeBundleIdentifier
        else {
            return false
        }
        return focusedWindowMatches(
            processIdentifier: processIdentifier,
            expectedWindow: expectedWindow,
            deadline: deadline
        )
    }

    private func deadlineAllowsWork(
        _ deadline: ContinuousClock.Instant?
    ) -> Bool {
        guard let deadline else { return true }
        return ContinuousClock().now < deadline
    }

    private enum AccessibilityInsertionAttempt {
        case verified
        case acknowledgedButUnverified(AccessibilityInsertionFailurePhase)
        case notPerformed
    }

    private enum AccessibilityInsertionFailurePhase: String {
        case initialExactReadback = "initial_exact_readback"
        case cursorOrSpaceDispatch = "cursor_or_space_dispatch"
        case sentinelReadback = "sentinel_readback"
        case sentinelSelectionOrDelete = "sentinel_selection_or_delete"
        case finalExactReadback = "final_exact_readback"
    }

    private struct OpenCodeSentinelReadback {
        let value: String
        let range: CFRange
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
        guard targetIsStillFocused(target) else { return .notPerformed }
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
                return .acknowledgedButUnverified(.initialExactReadback)
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
        return .acknowledgedButUnverified(.initialExactReadback)
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
        guard targetIsStillFocused(target),
              accessibility.setAttribute(
            valueAttribute,
            to: content as CFString,
            on: target.element
        ) == .success else {
            return .notPerformed
        }
        let initialReadback = await exactReadbackResult(
            content,
            target: target,
            failurePhase: .initialExactReadback
        )
        guard case .verified = initialReadback else {
            return initialReadback
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
              targetIsStillFocused(target),
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
              let confirmedCursorRange = accessibility.rangeAttribute(
                  selectedRangeAttribute,
                  from: target.element
              ), confirmedCursorRange.location == cursorRange.location,
              confirmedCursorRange.length == cursorRange.length,
              targetIsStillFocused(target),
              postSpace(target.processIdentifier)
        else {
            return .acknowledgedButUnverified(.cursorOrSpaceDispatch)
        }
        guard let sentinelReadback = await openCodeSentinelReadback(
            for: content,
            target: target
        ) else {
            return .acknowledgedButUnverified(.sentinelReadback)
        }

        var sentinelRange = sentinelReadback.range
        guard let sentinelRangeValue = AXValueCreate(.cfRange, &sentinelRange),
              targetIsStillFocused(target),
              accessibility.setAttribute(
                  selectedRangeAttribute,
                  to: sentinelRangeValue,
                  on: target.element
              ) == .success,
              targetIsStillFocused(target),
              accessibility.stringAttribute(
                  kAXValueAttribute as CFString,
                  from: target.element
              ) == sentinelReadback.value,
              accessibility.stringAttribute(
                  selectedTextAttribute,
                  from: target.element
              ) == " ",
              let selectedRange = accessibility.rangeAttribute(
                  selectedRangeAttribute,
                  from: target.element
              ), selectedRange.location == sentinelRange.location,
              selectedRange.length == sentinelRange.length,
              targetIsStillFocused(target),
              postDeleteBackward(target.processIdentifier)
        else {
            return .acknowledgedButUnverified(.sentinelSelectionOrDelete)
        }
        return await exactReadbackResult(
            content,
            target: target,
            failurePhase: .finalExactReadback
        )
    }

    private func openCodeSentinelReadback(
        for content: String,
        target: FocusedTarget
    ) async -> OpenCodeSentinelReadback? {
        let appended = OpenCodeSentinelReadback(
            value: content + " ",
            range: CFRange(location: content.utf16.count, length: 1)
        )
        var accepted = [appended]
        if let structural = openCodeStructuralSentinelReadback(for: content) {
            accepted.append(structural)
        }

        for attempt in 0..<10 {
            guard targetIsStillFocused(target) else { return nil }
            if let value = accessibility.stringAttribute(
                kAXValueAttribute as CFString,
                from: target.element
            ), let match = accepted.first(where: { $0.value == value }) {
                return match
            }
            if attempt < 9 {
                try? await Task.sleep(for: .milliseconds(50))
            }
        }
        return nil
    }

    private func openCodeStructuralSentinelReadback(
        for content: String
    ) -> OpenCodeSentinelReadback? {
        guard content.last == "\n", !content.utf16.isEmpty else { return nil }
        // Chromium serializes a Space typed at the logical end of a
        // contenteditable immediately before its structural final line feed.
        // This is still one exact U+0020 sentinel, not a broad whitespace
        // normalization. Preserve its UTF-16 range so only that character can
        // ever be selected and removed.
        return OpenCodeSentinelReadback(
            value: String(content.dropLast()) + " \n",
            range: CFRange(
                location: content.utf16.count - 1,
                length: 1
            )
        )
    }

    private func exactReadbackResult(
        _ expectedValue: String,
        target: FocusedTarget,
        failurePhase: AccessibilityInsertionFailurePhase
    ) async -> AccessibilityInsertionAttempt {
        // OpenCode's paste/input handler and Chromium's AX tree can settle on
        // different frames. Bound the wait to under half a second.
        for attempt in 0..<10 {
            guard targetIsStillFocused(target) else {
                return .acknowledgedButUnverified(failurePhase)
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
        return .acknowledgedButUnverified(failurePhase)
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
