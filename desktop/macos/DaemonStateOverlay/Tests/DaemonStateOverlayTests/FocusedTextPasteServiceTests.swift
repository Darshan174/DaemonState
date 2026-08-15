import AppKit
import ApplicationServices
import Testing
@testable import DaemonStateOverlay

@Suite(.serialized)
struct FocusedTextPasteServiceTests {
    @Test
    @MainActor
    func insertsDirectlyIntoAWebEditorWithAWritableSelection() async throws {
        let accessibility = FakeAccessibilityElementClient()
        accessibility.role = kAXGroupRole as String
        accessibility.settableAttributes = [kAXSelectedTextAttribute as String]
        let pasteboard = FakeTextPasteboard()
        var postedProcessIdentifiers: [pid_t] = []
        let service = FocusedTextPasteService(
            accessibility: accessibility,
            pasteboard: pasteboard,
            postCommandV: {
                postedProcessIdentifiers.append($0)
                return true
            }
        )

        let outcome = try await service.deliver(
            "Explain this change",
            to: service.captureTarget()
        )

        #expect(outcome == .insertedWithAccessibility)
        #expect(accessibility.insertedValues == ["Explain this change"])
        #expect(postedProcessIdentifiers.isEmpty)
    }

    @Test
    @MainActor
    func fallsBackToCommandPasteForAStandardTextArea() async throws {
        let accessibility = FakeAccessibilityElementClient()
        accessibility.role = kAXTextAreaRole as String
        accessibility.settableAttributes = [kAXValueAttribute as String]
        let pasteboard = FakeTextPasteboard()
        var postedProcessIdentifiers: [pid_t] = []
        let service = FocusedTextPasteService(
            accessibility: accessibility,
            pasteboard: pasteboard,
            postCommandV: {
                postedProcessIdentifiers.append($0)
                return true
            }
        )

        let outcome = try await service.deliver(
            "Use the selected prompt",
            to: service.captureTarget()
        )

        #expect(outcome == .commandVDispatched)
        #expect(accessibility.insertedValues.isEmpty)
        #expect(postedProcessIdentifiers == [accessibility.processIdentifier])
        #expect(pasteboard.string(forType: .string) == "Use the selected prompt")
    }

    @Test
    @MainActor
    func retriesAWebEditorWhenAccessibilityIsTemporarilyBusy() async throws {
        let accessibility = FakeAccessibilityElementClient()
        accessibility.role = kAXGroupRole as String
        accessibility.settableAttributes = [kAXSelectedTextAttribute as String]
        accessibility.setResults = [.cannotComplete, .success]
        let service = FocusedTextPasteService(
            accessibility: accessibility,
            pasteboard: FakeTextPasteboard(),
            postCommandV: { _ in false }
        )

        let outcome = try await service.deliver(
            "Retry this insertion",
            to: service.captureTarget()
        )

        #expect(outcome == .insertedWithAccessibility)
        #expect(
            accessibility.insertedValues
                == ["Retry this insertion", "Retry this insertion"]
        )
    }

    @Test
    @MainActor
    func strictAccessibilityInsertionRequiresExactFullValueReadback() async throws {
        let accessibility = FakeAccessibilityElementClient()
        accessibility.role = kAXGroupRole as String
        accessibility.value = ""
        accessibility.reflectSuccessfulInsertionInValue = true
        accessibility.settableAttributes = [kAXSelectedTextAttribute as String]
        var posted = false
        let service = FocusedTextPasteService(
            accessibility: accessibility,
            pasteboard: FakeTextPasteboard(),
            postCommandV: { _ in
                posted = true
                return true
            }
        )

        let outcome = try await service.deliver(
            "Verified insertion",
            to: service.captureTarget(requireExactInsertionReadback: true)
        )

        #expect(outcome == .insertedWithAccessibility)
        #expect(accessibility.value == "Verified insertion")
        #expect(!posted)
    }

    @Test
    @MainActor
    func acknowledgedInsertionWithoutExactReadbackNeverSendsCommandV() async throws {
        let accessibility = FakeAccessibilityElementClient()
        accessibility.role = kAXGroupRole as String
        accessibility.value = ""
        accessibility.settableAttributes = [kAXSelectedTextAttribute as String]
        var posted = false
        let service = FocusedTextPasteService(
            accessibility: accessibility,
            pasteboard: FakeTextPasteboard(),
            postCommandV: { _ in
                posted = true
                return true
            }
        )

        let outcome = try await service.deliver(
            "Potentially inserted once",
            to: service.captureTarget(requireExactInsertionReadback: true)
        )

        #expect(
            outcome == .accessibilityInsertionUnverified(
                "macOS acknowledged the context insertion, but the editor "
                    + "did not expose the exact inserted value for verification."
            )
        )
        #expect(accessibility.insertedValues == ["Potentially inserted once"])
        #expect(!posted)
    }

    @Test
    @MainActor
    func pastesAutomaticallyWhenAWebEditorHasNoAXFocusedElement() async throws {
        let accessibility = FakeAccessibilityElementClient()
        accessibility.hasFocusedElement = false
        let pasteboard = FakeTextPasteboard()
        var postedProcessIdentifiers: [pid_t] = []
        let service = FocusedTextPasteService(
            accessibility: accessibility,
            pasteboard: pasteboard,
            postCommandV: {
                postedProcessIdentifiers.append($0)
                return true
            }
        )

        let outcome = try await service.deliver(
            "Paste into the Electron chat editor",
            to: service.captureTarget()
        )

        #expect(outcome == .commandVDispatched)
        #expect(postedProcessIdentifiers == [accessibility.processIdentifier])
        #expect(
            pasteboard.string(forType: .string)
                == "Paste into the Electron chat editor"
        )
    }

    @Test
    @MainActor
    func pastesAutomaticallyThroughANonEditableWebContainer() async throws {
        let accessibility = FakeAccessibilityElementClient()
        accessibility.role = kAXGroupRole as String
        let pasteboard = FakeTextPasteboard()
        var postedProcessIdentifiers: [pid_t] = []
        let service = FocusedTextPasteService(
            accessibility: accessibility,
            pasteboard: pasteboard,
            postCommandV: {
                postedProcessIdentifiers.append($0)
                return true
            }
        )

        let outcome = try await service.deliver(
            "Paste through the focused web container",
            to: service.captureTarget()
        )

        #expect(outcome == .commandVDispatched)
        #expect(postedProcessIdentifiers == [accessibility.processIdentifier])
    }

    @Test
    @MainActor
    func doesNotPasteIfTheFrontmostAppChangesAfterCapture() async throws {
        let accessibility = FakeAccessibilityElementClient()
        accessibility.hasFocusedElement = false
        var posted = false
        let service = FocusedTextPasteService(
            accessibility: accessibility,
            pasteboard: FakeTextPasteboard(),
            postCommandV: { _ in
                posted = true
                return true
            }
        )
        let capture = service.captureTarget()
        accessibility.frontmostPID = 99_999

        let outcome = try await service.deliver(
            "Do not paste into a different app",
            to: capture
        )

        #expect(
            outcome
                == .notPasted(
                    "The target app changed before automatic paste."
                )
        )
        #expect(!posted)
    }

    @Test
    @MainActor
    func neverInsertsIntoASecureTextField() async throws {
        let accessibility = FakeAccessibilityElementClient()
        accessibility.role = kAXTextFieldRole as String
        accessibility.subrole = "AXSecureTextField"
        accessibility.settableAttributes = [kAXSelectedTextAttribute as String]
        var posted = false
        let pasteboard = FakeTextPasteboard()
        let service = FocusedTextPasteService(
            accessibility: accessibility,
            pasteboard: pasteboard,
            postCommandV: { _ in
                posted = true
                return true
            }
        )

        let outcome = try await service.deliver(
            "Do not put this in a password field",
            to: service.captureTarget()
        )

        #expect(
            outcome
                == .notPasted(
                    "Automatic paste is disabled for secure and search fields."
                )
        )
        #expect(accessibility.insertedValues.isEmpty)
        #expect(!posted)
        #expect(pasteboard.string(forType: .string) == nil)
    }

    @Test
    @MainActor
    func refusesADifferentFrontmostApplicationBeforeClipboardDelivery() async throws {
        let accessibility = FakeAccessibilityElementClient()
        accessibility.bundleIdentifier = "com.apple.TextEdit"
        let pasteboard = FakeTextPasteboard()
        var posted = false
        let service = FocusedTextPasteService(
            accessibility: accessibility,
            pasteboard: pasteboard,
            postCommandV: { _ in
                posted = true
                return true
            }
        )

        let capture = service.captureTarget(
            expectedBundleIdentifiers: ["com.openai.codex"]
        )
        let outcome = try await service.deliver(
            "Never paste into another application",
            to: capture
        )

        #expect(
            outcome
                == .notPasted(
                    "The selected AI desktop app is not focused yet."
                )
        )
        #expect(!posted)
        #expect(pasteboard.string(forType: .string) == nil)
    }

    @Test
    @MainActor
    func boundedComposerInputAccumulatesMultiplePipeSizedChunks() throws {
        let payload = Data(repeating: 0x61, count: 150_000)
        let url = FileManager.default.temporaryDirectory.appendingPathComponent(
            "composer-input-\(UUID().uuidString)"
        )
        defer { try? FileManager.default.removeItem(at: url) }
        try payload.write(to: url)
        let handle = try FileHandle(forReadingFrom: url)
        defer { try? handle.close() }

        let received = ComposerPasteCommand.readBoundedInput(
            from: handle,
            maximumBytes: 200_000
        )

        #expect(received == payload)
    }

    @Test
    @MainActor
    func boundedComposerInputReadsOneOverflowByte() throws {
        let payload = Data(repeating: 0x62, count: 70_001)
        let url = FileManager.default.temporaryDirectory.appendingPathComponent(
            "composer-overflow-\(UUID().uuidString)"
        )
        defer { try? FileManager.default.removeItem(at: url) }
        try payload.write(to: url)
        let handle = try FileHandle(forReadingFrom: url)
        defer { try? handle.close() }

        let received = ComposerPasteCommand.readBoundedInput(
            from: handle,
            maximumBytes: 70_000
        )

        #expect(received.count == 70_001)
        #expect(received == payload)
    }

    @Test
    @MainActor
    func openCodeOneShotConfigurationRequiresStrictTargetAttestation() {
        let base = [
            "DaemonStateOverlay",
            "--paste-stdin",
            "--expected-bundle-id",
            "ai.opencode.desktop",
            "--expected-bundle-path",
            "/Applications/OpenCode.app",
        ]

        #expect(ComposerPasteConfiguration.parse(arguments: base) == nil)
        #expect(
            ComposerPasteConfiguration.parse(
                arguments: base + [
                    "--target-policy",
                    "opencode-chat-composer-v1",
                    "--target-marker",
                    "ds-0123456789abcdef0123456789abcdef",
                ]
            )?.targetPolicy == .openCodeChatComposerV1
        )
    }

    @Test
    @MainActor
    func oneShotEditorRequiresAnExplicitEmptyFullValue() {
        let accessibility = FakeAccessibilityElementClient()
        accessibility.role = kAXTextAreaRole as String
        accessibility.settableAttributes = [kAXSelectedTextAttribute as String]
        let service = FocusedTextPasteService(
            accessibility: accessibility,
            pasteboard: FakeTextPasteboard(),
            postCommandV: { _ in false }
        )
        let capture = service.captureTarget()

        accessibility.value = nil
        accessibility.selectedText = ""
        #expect(service.editableTargetContentState(capture) == .unknown)

        accessibility.value = "Existing draft"
        #expect(service.editableTargetContentState(capture) == .nonempty)

        accessibility.value = ""
        #expect(service.editableTargetContentState(capture) == .empty)
    }

    @Test
    @MainActor
    func oneShotEditorIdentityMustRemainTheSame() {
        let accessibility = FakeAccessibilityElementClient()
        accessibility.role = kAXTextAreaRole as String
        accessibility.settableAttributes = [kAXSelectedTextAttribute as String]
        let service = FocusedTextPasteService(
            accessibility: accessibility,
            pasteboard: FakeTextPasteboard(),
            postCommandV: { _ in false }
        )
        let first = service.captureTarget()
        let second = service.captureTarget()
        #expect(service.capturesSameEditableTarget(first, second))

        accessibility.focusedElementMatchesCapture = false
        #expect(!service.capturesSameEditableTarget(first, second))
    }

    @Test
    @MainActor
    func strictOpenCodeTargetRejectsAMarkerValuedTerminal() async throws {
        let marker = "ds-0123456789abcdef"
        let accessibility = FakeAccessibilityElementClient()
        accessibility.bundleIdentifier = "ai.opencode.desktop"
        accessibility.role = kAXTextAreaRole as String
        accessibility.descriptionText = "Terminal input"
        accessibility.value = marker
        accessibility.settableAttributes = [
            kAXSelectedTextAttribute as String,
        ]
        var posted = false
        let service = FocusedTextPasteService(
            accessibility: accessibility,
            pasteboard: FakeTextPasteboard(),
            postCommandV: { _ in
                posted = true
                return true
            }
        )

        let capture = service.captureTarget(
            expectedBundleIdentifiers: ["ai.opencode.desktop"],
            allowNonEditableApplicationFallback: false,
            allowMissingFocusedElementFallback: false,
            requireExactInsertionReadback: true,
            discoverEditableWithExactValue: marker
        )
        let outcome = try await service.deliver(
            "Multiline context that must never reach a terminal",
            to: capture
        )

        #expect(
            outcome == .notPasted(
                "The selected AI desktop app has not exposed its verified composer yet."
            )
        )
        #expect(accessibility.insertedValues.isEmpty)
        #expect(!posted)
    }

    @Test
    @MainActor
    func strictOpenCodeTargetFocusesAndSynchronizesTheUniqueMarker() async throws {
        let marker = "ds-0123456789abcdef"
        let accessibility = FakeAccessibilityElementClient()
        accessibility.bundleIdentifier = "ai.opencode.desktop"
        accessibility.role = kAXGroupRole as String
        accessibility.descriptionText = "Ask anything..."
        accessibility.value = marker
        accessibility.secondaryRole = kAXTextAreaRole as String
        accessibility.secondaryDescriptionText = "Fragen Sie alles..."
        accessibility.secondaryDOMClasses = [
            "select-text",
            "w-full",
            "text-14-regular",
            "whitespace-pre-wrap",
        ]
        accessibility.secondaryValue = marker
        accessibility.focusedWindowChildren = [
            accessibility.nestedContainerElement,
        ]
        accessibility.nestedContainerChildren = [
            accessibility.element,
            accessibility.secondaryElement,
        ]
        accessibility.settableAttributes = [
            kAXFocusedAttribute as String,
            kAXSelectedTextAttribute as String,
            kAXSelectedTextRangeAttribute as String,
            kAXValueAttribute as String,
        ]
        accessibility.reflectSuccessfulInsertionInValue = true
        var commandVPosted = false
        var spacePosted = false
        var deletePosted = false
        let service = FocusedTextPasteService(
            accessibility: accessibility,
            pasteboard: FakeTextPasteboard(),
            postCommandV: { _ in
                commandVPosted = true
                return true
            },
            postSpace: { _ in
                spacePosted = true
                accessibility.secondaryValue = "Verified chat context "
                return true
            },
            postDeleteBackward: { _ in
                deletePosted = true
                accessibility.secondaryValue = "Verified chat context"
                return true
            }
        )

        let capture = service.captureTarget(
            expectedBundleIdentifiers: ["ai.opencode.desktop"],
            allowNonEditableApplicationFallback: false,
            allowMissingFocusedElementFallback: false,
            requireExactInsertionReadback: true,
            discoverEditableWithExactValue: marker
        )
        let outcome = try await service.deliver(
            "Verified chat context",
            to: capture
        )

        #expect(outcome == .markerReplacedWithVerifiedInputSync)
        #expect(accessibility.secondaryValue == "Verified chat context")
        #expect(accessibility.focusedElementMatches(accessibility.secondaryElement))
        #expect(accessibility.insertedValues.isEmpty)
        #expect(!commandVPosted)
        #expect(spacePosted)
        #expect(deletePosted)
    }

    @Test
    @MainActor
    func strictOpenCodeInputWithoutApplicationStateReadbackIsUnverified() async throws {
        let marker = "ds-0123456789abcdef"
        let accessibility = FakeAccessibilityElementClient()
        accessibility.bundleIdentifier = "ai.opencode.desktop"
        accessibility.role = kAXTextAreaRole as String
        accessibility.descriptionText = "Ask anything..."
        accessibility.value = marker
        accessibility.settableAttributes = [
            kAXFocusedAttribute as String,
            kAXSelectedTextAttribute as String,
            kAXSelectedTextRangeAttribute as String,
            kAXValueAttribute as String,
        ]
        accessibility.reflectSuccessfulInsertionInValue = true
        var postCount = 0
        let service = FocusedTextPasteService(
            accessibility: accessibility,
            pasteboard: FakeTextPasteboard(),
            postCommandV: { _ in false },
            postSpace: { _ in
                postCount += 1
                return true
            }
        )

        let capture = service.captureTarget(
            expectedBundleIdentifiers: ["ai.opencode.desktop"],
            allowNonEditableApplicationFallback: false,
            allowMissingFocusedElementFallback: false,
            requireExactInsertionReadback: true,
            discoverEditableWithExactValue: marker
        )
        let outcome = try await service.deliver("Unverified context", to: capture)

        #expect(
            outcome == .accessibilityInsertionUnverified(
                "macOS acknowledged the context insertion, but the editor "
                    + "did not expose the exact inserted value for verification."
            )
        )
        #expect(accessibility.value == "Unverified context")
        #expect(accessibility.insertedValues.isEmpty)
        #expect(postCount == 1)
    }

    @Test
    @MainActor
    func strictOpenCodeTargetRejectsAnAmbiguousMarker() async throws {
        let marker = "ds-0123456789abcdef"
        let accessibility = FakeAccessibilityElementClient()
        accessibility.bundleIdentifier = "ai.opencode.desktop"
        accessibility.role = kAXTextAreaRole as String
        accessibility.descriptionText = "Ask anything..."
        accessibility.value = marker
        accessibility.secondaryRole = kAXTextAreaRole as String
        accessibility.secondaryDescriptionText = "Ask anything..."
        accessibility.secondaryValue = marker
        accessibility.focusedWindowChildren = [
            accessibility.element,
            accessibility.secondaryElement,
        ]
        accessibility.settableAttributes = [
            kAXFocusedAttribute as String,
            kAXSelectedTextAttribute as String,
        ]
        var posted = false
        let service = FocusedTextPasteService(
            accessibility: accessibility,
            pasteboard: FakeTextPasteboard(),
            postCommandV: { _ in
                posted = true
                return true
            }
        )

        let capture = service.captureTarget(
            expectedBundleIdentifiers: ["ai.opencode.desktop"],
            allowNonEditableApplicationFallback: false,
            allowMissingFocusedElementFallback: false,
            requireExactInsertionReadback: true,
            discoverEditableWithExactValue: marker
        )
        let outcome = try await service.deliver("Context", to: capture)

        #expect(
            outcome == .notPasted(
                "The selected AI desktop app has not exposed its verified composer yet."
            )
        )
        #expect(!posted)
    }

    @Test
    @MainActor
    func strictOpenCodeTargetNeverFallsBackToCommandV() async throws {
        let marker = "ds-0123456789abcdef"
        let accessibility = FakeAccessibilityElementClient()
        accessibility.bundleIdentifier = "ai.opencode.desktop"
        accessibility.role = kAXTextAreaRole as String
        accessibility.descriptionText = "Ask anything..."
        accessibility.value = marker
        accessibility.settableAttributes = [
            kAXFocusedAttribute as String,
            kAXSelectedTextAttribute as String,
        ]
        var posted = false
        let service = FocusedTextPasteService(
            accessibility: accessibility,
            pasteboard: FakeTextPasteboard(),
            postCommandV: { _ in
                posted = true
                return true
            }
        )

        let capture = service.captureTarget(
            expectedBundleIdentifiers: ["ai.opencode.desktop"],
            allowNonEditableApplicationFallback: false,
            allowMissingFocusedElementFallback: false,
            requireExactInsertionReadback: true,
            discoverEditableWithExactValue: marker
        )
        let outcome = try await service.deliver("Context", to: capture)

        #expect(
            outcome == .notPasted(
                "The verified chat composer did not allow a safe marker replacement."
            )
        )
        #expect(!posted)
    }

    @Test
    @MainActor
    func strictOpenCodeTargetRejectsShellMode() async throws {
        let marker = "ds-0123456789abcdef"
        let accessibility = FakeAccessibilityElementClient()
        accessibility.bundleIdentifier = "ai.opencode.desktop"
        accessibility.role = kAXTextAreaRole as String
        // Shell-only DOM evidence must dominate even a stale/contradictory
        // normal English accessible name.
        accessibility.descriptionText = "Ask anything..."
        accessibility.domClasses = [
            "select-text",
            "w-full",
            "text-14-regular",
            "whitespace-pre-wrap",
            "font-mono!",
        ]
        accessibility.value = marker
        accessibility.settableAttributes = [
            kAXFocusedAttribute as String,
            kAXSelectedTextAttribute as String,
            kAXSelectedTextRangeAttribute as String,
        ]
        var posted = false
        let service = FocusedTextPasteService(
            accessibility: accessibility,
            pasteboard: FakeTextPasteboard(),
            postCommandV: { _ in
                posted = true
                return true
            }
        )

        let capture = service.captureTarget(
            expectedBundleIdentifiers: ["ai.opencode.desktop"],
            allowNonEditableApplicationFallback: false,
            allowMissingFocusedElementFallback: false,
            requireExactInsertionReadback: true,
            discoverEditableWithExactValue: marker
        )
        let outcome = try await service.deliver("rm must never run", to: capture)

        #expect(
            outcome == .notPasted(
                "The selected AI desktop app has not exposed its verified composer yet."
            )
        )
        #expect(accessibility.insertedValues.isEmpty)
        #expect(!posted)
    }

    @Test
    @MainActor
    func strictOpenCodeTargetRechecksNormalModeBeforeReplacement() async throws {
        let marker = "ds-0123456789abcdef"
        let accessibility = FakeAccessibilityElementClient()
        accessibility.bundleIdentifier = "ai.opencode.desktop"
        accessibility.role = kAXTextAreaRole as String
        accessibility.descriptionText = "Ask anything..."
        accessibility.value = marker
        accessibility.settableAttributes = [
            kAXFocusedAttribute as String,
            kAXSelectedTextAttribute as String,
            kAXSelectedTextRangeAttribute as String,
        ]
        var posted = false
        let service = FocusedTextPasteService(
            accessibility: accessibility,
            pasteboard: FakeTextPasteboard(),
            postCommandV: { _ in
                posted = true
                return true
            }
        )
        let capture = service.captureTarget(
            expectedBundleIdentifiers: ["ai.opencode.desktop"],
            allowNonEditableApplicationFallback: false,
            allowMissingFocusedElementFallback: false,
            requireExactInsertionReadback: true,
            discoverEditableWithExactValue: marker
        )

        accessibility.descriptionText = "Enter shell command..."
        let outcome = try await service.deliver("Must stay out of shell", to: capture)

        #expect(
            outcome == .notPasted(
                "The target chat box changed before automatic paste."
            )
        )
        #expect(accessibility.value == marker)
        #expect(accessibility.insertedValues.isEmpty)
        #expect(!posted)
    }

    @Test
    @MainActor
    func strictOpenCodeDiscoveryHonorsAnExpiredDeadline() async throws {
        let marker = "ds-0123456789abcdef"
        let accessibility = FakeAccessibilityElementClient()
        accessibility.bundleIdentifier = "ai.opencode.desktop"
        accessibility.role = kAXTextAreaRole as String
        accessibility.descriptionText = "Ask anything..."
        accessibility.value = marker
        accessibility.settableAttributes = [
            kAXFocusedAttribute as String,
            kAXSelectedTextAttribute as String,
        ]
        let service = FocusedTextPasteService(
            accessibility: accessibility,
            pasteboard: FakeTextPasteboard(),
            postCommandV: { _ in false }
        )

        let capture = service.captureTarget(
            expectedBundleIdentifiers: ["ai.opencode.desktop"],
            allowNonEditableApplicationFallback: false,
            allowMissingFocusedElementFallback: false,
            requireExactInsertionReadback: true,
            discoverEditableWithExactValue: marker,
            discoveryDeadline: ContinuousClock().now
        )
        let outcome = try await service.deliver("Context", to: capture)

        #expect(
            outcome == .notPasted(
                "The selected AI desktop app has not exposed its verified composer yet."
            )
        )
        #expect(accessibility.value == marker)
        #expect(accessibility.insertedValues.isEmpty)
    }
}

@MainActor
private final class FakeTextPasteboard: TextPasteboard {
    private(set) var changeCount = 0
    private var content: String?

    @discardableResult
    func clearContents() -> Int {
        content = nil
        changeCount += 1
        return changeCount
    }

    func setString(
        _ string: String,
        forType dataType: NSPasteboard.PasteboardType
    ) -> Bool {
        guard dataType == .string else { return false }
        content = string
        return true
    }

    func string(forType dataType: NSPasteboard.PasteboardType) -> String? {
        dataType == .string ? content : nil
    }
}

@MainActor
private final class FakeAccessibilityElementClient: AccessibilityElementClient {
    let element = AXUIElementCreateSystemWide()
    let secondaryElement = AXUIElementCreateApplication(42_425)
    let nestedContainerElement = AXUIElementCreateApplication(42_427)
    private let applicationAXElement = AXUIElementCreateApplication(42_424)
    private let focusedWindowElement = AXUIElementCreateApplication(42_426)
    let processIdentifier: pid_t = 42_424
    var trusted = true
    var frontmostPID: pid_t? = 42_424
    var bundleIdentifier: String? = "com.openai.codex"
    var hasFocusedElement = true
    var focusedElementMatchesCapture = true
    var role: String?
    var secondaryRole: String?
    var descriptionText: String?
    var secondaryDescriptionText: String?
    var domClasses: [String]?
    var secondaryDOMClasses: [String]?
    var subrole: String?
    var enabled: Bool? = true
    var value: String?
    var secondaryValue: String?
    var selectedText: String?
    var reflectSuccessfulInsertionInValue = false
    var settableAttributes: Set<String> = []
    var setResults: [AXError] = [.success]
    var focusedWindowChildren: [AXUIElement] = []
    var nestedContainerChildren: [AXUIElement] = []
    private var focusedElementOverride: AXUIElement?
    private(set) var insertedValues: [String] = []

    func isTrusted(prompt: Bool) -> Bool {
        trusted
    }

    func frontmostApplication() -> FrontmostApplicationIdentity? {
        guard let frontmostPID else { return nil }
        return FrontmostApplicationIdentity(
            processIdentifier: frontmostPID,
            bundleIdentifier: bundleIdentifier
        )
    }

    func focusedElement() -> AXUIElement? {
        hasFocusedElement ? (focusedElementOverride ?? element) : nil
    }

    func applicationElement(for processIdentifier: pid_t) -> AXUIElement? {
        applicationAXElement
    }

    func processIdentifier(for element: AXUIElement) -> pid_t? {
        processIdentifier
    }

    func elementAttribute(
        _ attribute: CFString,
        from element: AXUIElement
    ) -> AXUIElement? {
        guard attribute as String == kAXFocusedWindowAttribute as String,
              CFEqual(element, applicationAXElement)
        else {
            return nil
        }
        return focusedWindowElement
    }

    func elementArrayAttribute(
        _ attribute: CFString,
        from element: AXUIElement,
        maximumCount: Int
    ) -> [AXUIElement]? {
        guard attribute as String == kAXChildrenAttribute as String else {
            return []
        }
        if CFEqual(element, focusedWindowElement) {
            guard focusedWindowChildren.count <= maximumCount else {
                return nil
            }
            return focusedWindowChildren.isEmpty ? [self.element] : focusedWindowChildren
        }
        if CFEqual(element, nestedContainerElement) {
            guard nestedContainerChildren.count <= maximumCount else {
                return nil
            }
            return nestedContainerChildren
        }
        return []
    }

    func stringAttribute(
        _ attribute: CFString,
        from element: AXUIElement
    ) -> String? {
        let isSecondary = CFEqual(element, secondaryElement)
        guard isSecondary || CFEqual(element, self.element) else { return nil }
        let name = attribute as String
        if name == kAXRoleAttribute as String {
            return isSecondary ? secondaryRole : role
        }
        if name == kAXSubroleAttribute as String {
            return subrole
        }
        if name == kAXDescriptionAttribute as String {
            return isSecondary ? secondaryDescriptionText : descriptionText
        }
        if name == kAXValueAttribute as String {
            return isSecondary ? secondaryValue : value
        }
        if name == kAXSelectedTextAttribute as String {
            return selectedText
        }
        return nil
    }

    func stringArrayAttribute(
        _ attribute: CFString,
        from element: AXUIElement
    ) -> [String]? {
        guard attribute as String == "AXDOMClassList" else { return nil }
        if CFEqual(element, secondaryElement) {
            return secondaryDOMClasses
        }
        return CFEqual(element, self.element) ? domClasses : nil
    }

    func boolAttribute(
        _ attribute: CFString,
        from element: AXUIElement
    ) -> Bool? {
        guard CFEqual(element, self.element)
                || CFEqual(element, secondaryElement)
        else {
            return nil
        }
        return attribute as String == kAXEnabledAttribute as String ? enabled : nil
    }

    func isAttributeSettable(
        _ attribute: CFString,
        on element: AXUIElement
    ) -> Bool {
        (CFEqual(element, self.element) || CFEqual(element, secondaryElement))
            && settableAttributes.contains(attribute as String)
    }

    func setAttribute(
        _ attribute: CFString,
        to value: CFTypeRef,
        on element: AXUIElement
    ) -> AXError {
        let name = attribute as String
        if name == kAXFocusedAttribute as String {
            focusedElementOverride = element
            return .success
        }
        if name == kAXSelectedTextRangeAttribute as String {
            let source = CFEqual(element, secondaryElement)
                ? secondaryValue
                : self.value
            guard let source else { return .noValue }
            let sourceText = source as NSString
            var range = CFRange()
            guard CFGetTypeID(value) == AXValueGetTypeID(),
                  AXValueGetValue(value as! AXValue, .cfRange, &range),
                  range.location >= 0,
                  range.length >= 0,
                  range.location + range.length <= sourceText.length
            else {
                return .illegalArgument
            }
            selectedText = sourceText.substring(
                with: NSRange(location: range.location, length: range.length)
            )
            return .success
        }
        let result = setResults.isEmpty ? .success : setResults.removeFirst()
        if attribute as String == kAXSelectedTextAttribute as String,
           let string = value as? String
        {
            insertedValues.append(string)
            if reflectSuccessfulInsertionInValue, result == .success {
                if CFEqual(element, secondaryElement) {
                    secondaryValue = string
                } else {
                    self.value = string
                }
            }
        }
        if name == kAXValueAttribute as String,
           let string = value as? String,
           result == .success
        {
            if CFEqual(element, secondaryElement) {
                secondaryValue = string
            } else {
                self.value = string
            }
        }
        return result
    }

    func elementsAreEqual(_ lhs: AXUIElement, _ rhs: AXUIElement) -> Bool {
        focusedElementMatchesCapture && CFEqual(lhs, rhs)
    }

    func focusedElementMatches(_ expected: AXUIElement) -> Bool {
        guard let focused = focusedElement() else { return false }
        return CFEqual(focused, expected)
    }
}
