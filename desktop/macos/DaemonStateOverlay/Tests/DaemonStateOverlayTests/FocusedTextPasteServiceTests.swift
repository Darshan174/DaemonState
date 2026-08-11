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

        #expect(outcome == .pasted)
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

        #expect(outcome == .pasted)
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

        #expect(outcome == .pasted)
        #expect(
            accessibility.insertedValues
                == ["Retry this insertion", "Retry this insertion"]
        )
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

        #expect(outcome == .pasted)
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

        #expect(outcome == .pasted)
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
    let processIdentifier: pid_t = 42_424
    var trusted = true
    var frontmostPID: pid_t? = 42_424
    var hasFocusedElement = true
    var focusedElementMatchesCapture = true
    var role: String?
    var subrole: String?
    var enabled: Bool? = true
    var settableAttributes: Set<String> = []
    var setResults: [AXError] = [.success]
    private(set) var insertedValues: [String] = []

    func isTrusted(prompt: Bool) -> Bool {
        trusted
    }

    func frontmostProcessIdentifier() -> pid_t? {
        frontmostPID
    }

    func focusedElement() -> AXUIElement? {
        hasFocusedElement ? element : nil
    }

    func processIdentifier(for element: AXUIElement) -> pid_t? {
        processIdentifier
    }

    func stringAttribute(
        _ attribute: CFString,
        from element: AXUIElement
    ) -> String? {
        let name = attribute as String
        if name == kAXRoleAttribute as String {
            return role
        }
        if name == kAXSubroleAttribute as String {
            return subrole
        }
        return nil
    }

    func boolAttribute(
        _ attribute: CFString,
        from element: AXUIElement
    ) -> Bool? {
        attribute as String == kAXEnabledAttribute as String ? enabled : nil
    }

    func isAttributeSettable(
        _ attribute: CFString,
        on element: AXUIElement
    ) -> Bool {
        settableAttributes.contains(attribute as String)
    }

    func setAttribute(
        _ attribute: CFString,
        to value: CFTypeRef,
        on element: AXUIElement
    ) -> AXError {
        if attribute as String == kAXSelectedTextAttribute as String,
           let string = value as? String
        {
            insertedValues.append(string)
        }
        return setResults.isEmpty ? .success : setResults.removeFirst()
    }

    func elementsAreEqual(_ lhs: AXUIElement, _ rhs: AXUIElement) -> Bool {
        focusedElementMatchesCapture
    }
}
