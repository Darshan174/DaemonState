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
    func floatingChromeFocusedComposerNeverRoutesOrActivatesOpenCode() async throws {
        let accessibility = FakeAccessibilityElementClient()
        accessibility.bundleIdentifier = "com.google.Chrome"
        accessibility.role = kAXTextAreaRole as String
        accessibility.value = ""
        accessibility.settableAttributes = [
            kAXSelectedTextAttribute as String,
        ]
        let pasteboard = FakeTextPasteboard()
        var openedURLCount = 0
        var synthesizedEvents: [String] = []
        let service = FocusedTextPasteService(
            accessibility: accessibility,
            pasteboard: pasteboard,
            postCommandV: { _ in
                synthesizedEvents.append("command-v")
                return true
            },
            postSpace: { _ in
                synthesizedEvents.append("space")
                return true
            },
            postDeleteBackward: { _ in
                synthesizedEvents.append("delete")
                return true
            },
            openURL: { _, _ in
                openedURLCount += 1
                return true
            },
            validateOpenCodeApplication: { _ in true }
        )

        let outcome = try await service.deliver(
            "Keep Chrome in front",
            to: service.captureTarget(),
            openCodeProjectDirectory: FileManager.default.temporaryDirectory.path
        )

        #expect(outcome == .insertedWithAccessibility)
        #expect(openedURLCount == 0)
        #expect(synthesizedEvents.isEmpty)
        #expect(accessibility.performedActions.isEmpty)
        #expect(accessibility.insertedValues == ["Keep Chrome in front"])
        #expect(pasteboard.string(forType: .string) == "Keep Chrome in front")
    }

    @Test
    @MainActor
    func openCodeDeepLinkConfigurationActivatesOnlyForTheRequestedRoute() {
        let configuration = FocusedTextPasteService
            .openCodeRouteConfiguration()

        #expect(configuration.activates)
        #expect(!configuration.promptsUserIfNeeded)
        #expect(!configuration.addsToRecentItems)
        #expect(!configuration.allowsRunningApplicationSubstitution)
    }

    @Test
    @MainActor
    func focusedChromeComposerIsNotMutatedAfterFrontmostAppChanges() async throws {
        let accessibility = FakeAccessibilityElementClient()
        accessibility.bundleIdentifier = "com.google.Chrome"
        accessibility.role = kAXTextAreaRole as String
        accessibility.value = ""
        accessibility.settableAttributes = [
            kAXSelectedTextAttribute as String,
        ]
        var openedURLCount = 0
        var synthesizedEvents: [String] = []
        let service = FocusedTextPasteService(
            accessibility: accessibility,
            pasteboard: FakeTextPasteboard(),
            postCommandV: { _ in
                synthesizedEvents.append("command-v")
                return true
            },
            postSpace: { _ in
                synthesizedEvents.append("space")
                return true
            },
            postDeleteBackward: { _ in
                synthesizedEvents.append("delete")
                return true
            },
            openURL: { _, _ in
                openedURLCount += 1
                return true
            }
        )
        let capture = service.captureTarget()
        // Model a stale AXFocusedUIElement after the user has switched apps.
        accessibility.frontmostPID = 99_999
        accessibility.bundleIdentifier = "com.apple.Safari"

        let outcome = try await service.deliver(
            "Never mutate stale Chrome focus",
            to: capture,
            openCodeProjectDirectory: FileManager.default.temporaryDirectory.path
        )

        #expect(
            outcome == .notPasted(
                "The target chat box changed before automatic paste."
            )
        )
        #expect(openedURLCount == 0)
        #expect(synthesizedEvents.isEmpty)
        #expect(accessibility.performedAttributeMutations.isEmpty)
        #expect(accessibility.insertedValues.isEmpty)
        #expect(accessibility.value == "")
    }

    @Test
    @MainActor
    func floatingOpenCodeRouteStopsBeforeOpeningAfterUserSwitchesToChrome() async throws {
        let accessibility = FakeAccessibilityElementClient()
        accessibility.bundleIdentifier = "ai.opencode.desktop"
        accessibility.role = kAXGroupRole as String
        let pasteboard = FakeTextPasteboard()
        var openedURLCount = 0
        var synthesizedEvents: [String] = []
        let service = FocusedTextPasteService(
            accessibility: accessibility,
            pasteboard: pasteboard,
            postCommandV: { _ in
                synthesizedEvents.append("command-v")
                return true
            },
            postSpace: { _ in
                synthesizedEvents.append("space")
                return true
            },
            postDeleteBackward: { _ in
                synthesizedEvents.append("delete")
                return true
            },
            openURL: { _, _ in
                openedURLCount += 1
                return true
            },
            validateOpenCodeApplication: { _ in true }
        )
        let capture = service.captureTarget()
        accessibility.frontmostPID = 99_999
        accessibility.bundleIdentifier = "com.google.Chrome"

        let outcome = try await service.deliver(
            "Do not take focus back from Chrome",
            to: capture,
            openCodeProjectDirectory: FileManager.default.temporaryDirectory.path
        )

        #expect(
            outcome == .notPasted(
                "OpenCode changed before a new-session composer could be "
                    + "requested. The context was copied."
            )
        )
        #expect(openedURLCount == 0)
        #expect(synthesizedEvents.isEmpty)
        #expect(accessibility.performedActions.isEmpty)
        #expect(accessibility.performedAttributeMutations.isEmpty)
        #expect(
            pasteboard.string(forType: .string)
                == "Do not take focus back from Chrome"
        )
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
    func floatingOpenCodePasteRoutesFromTerminalToTheUniqueEmptyComposer() async throws {
        let accessibility = FakeAccessibilityElementClient()
        accessibility.bundleIdentifier = "ai.opencode.desktop"
        accessibility.role = kAXTextAreaRole as String
        accessibility.descriptionText = "Terminal input"
        accessibility.value = "pwd"
        accessibility.secondaryRole = kAXTextAreaRole as String
        accessibility.secondaryDescriptionText = "Ask anything..."
        accessibility.secondaryValue = ""
        let projectDirectory = FileManager.default.temporaryDirectory.path
        accessibility.exposeOpenCodeWindow(
            children: [
                accessibility.element,
                accessibility.secondaryElement,
            ],
            projectDirectory: projectDirectory,
            newSessionIsCurrent: true
        )
        accessibility.settableAttributes = [
            kAXFocusedAttribute as String,
            kAXSelectedTextRangeAttribute as String,
            kAXValueAttribute as String,
        ]
        let pasteboard = FakeTextPasteboard()
        var commandVPosted = false
        var spacePosted = false
        var deletePosted = false
        let service = FocusedTextPasteService(
            accessibility: accessibility,
            pasteboard: pasteboard,
            postCommandV: { _ in
                commandVPosted = true
                return true
            },
            postSpace: { _ in
                spacePosted = true
                accessibility.secondaryValue = "Verified Workspace Context "
                return true
            },
            postDeleteBackward: { _ in
                deletePosted = true
                accessibility.secondaryValue = "Verified Workspace Context"
                return true
            },
            validateOpenCodeApplication: { _ in true }
        )

        let outcome = try await service.deliver(
            "Verified Workspace Context",
            to: service.captureTarget(),
            openCodeProjectDirectory: projectDirectory
        )

        #expect(outcome == .insertedIntoVerifiedEmptyComposerWithInputSync)
        #expect(accessibility.value == "pwd")
        #expect(accessibility.secondaryValue == "Verified Workspace Context")
        #expect(accessibility.focusedElementMatches(accessibility.secondaryElement))
        #expect(accessibility.insertedValues.isEmpty)
        #expect(!commandVPosted)
        #expect(spacePosted)
        #expect(deletePosted)
        #expect(
            pasteboard.string(forType: .string) == "Verified Workspace Context"
        )
    }

    @Test
    @MainActor
    func floatingOpenCodeAlreadyFocusedEmptyComposerDoesNotOpenAnotherSession() async throws {
        let accessibility = FakeAccessibilityElementClient()
        accessibility.bundleIdentifier = "ai.opencode.desktop"
        accessibility.role = kAXTextAreaRole as String
        accessibility.descriptionText = "Ask anything..."
        accessibility.value = ""
        let projectDirectory = FileManager.default.temporaryDirectory.path
        accessibility.exposeOpenCodeWindow(
            children: [accessibility.element],
            projectDirectory: projectDirectory,
            newSessionIsCurrent: true
        )
        accessibility.settableAttributes = [
            kAXFocusedAttribute as String,
            kAXSelectedTextRangeAttribute as String,
            kAXValueAttribute as String,
        ]
        var openedURLCount = 0
        let service = FocusedTextPasteService(
            accessibility: accessibility,
            pasteboard: FakeTextPasteboard(),
            postCommandV: { _ in false },
            postSpace: { _ in
                accessibility.value = "Retry-safe context "
                return true
            },
            postDeleteBackward: { _ in
                accessibility.value = "Retry-safe context"
                return true
            },
            openURL: { _, _ in
                openedURLCount += 1
                return true
            },
            validateOpenCodeApplication: { _ in true }
        )

        let outcome = try await service.deliver(
            "Retry-safe context",
            to: service.captureTarget(),
            openCodeProjectDirectory: projectDirectory
        )

        #expect(outcome == .insertedIntoVerifiedEmptyComposerWithInputSync)
        #expect(openedURLCount == 0)
        #expect(accessibility.value == "Retry-safe context")
    }

    @Test
    @MainActor
    func floatingOpenCodePromptLabelAloneIsNotAComposerIdentity() {
        let accessibility = FakeAccessibilityElementClient()
        accessibility.bundleIdentifier = "ai.opencode.desktop"
        accessibility.role = kAXTextAreaRole as String
        accessibility.descriptionText = "Prompt"
        accessibility.domClasses = ["w-full", "whitespace-pre-wrap"]
        accessibility.value = ""
        accessibility.exposeOpenCodeWindow(
            children: [accessibility.element],
            projectDirectory: FileManager.default.currentDirectoryPath,
            newSessionIsCurrent: true
        )
        accessibility.settableAttributes = [
            kAXFocusedAttribute as String,
            kAXSelectedTextRangeAttribute as String,
            kAXValueAttribute as String,
        ]
        let service = FocusedTextPasteService(
            accessibility: accessibility,
            pasteboard: FakeTextPasteboard(),
            postCommandV: { _ in false },
            openURL: { _, _ in false },
            validateOpenCodeApplication: { _ in true }
        )

        guard case .openCodeNewComposer = service.captureTarget() else {
            Issue.record(
                "The localized V2 label without its exact class signature must route instead of being accepted as a composer"
            )
            return
        }
        #expect(accessibility.performedAttributeMutations.isEmpty)
    }

    @Test
    @MainActor
    func floatingOpenCodePromptWithoutDOMClassesUsesBoundNormalPlaceholder() {
        let accessibility = FakeAccessibilityElementClient()
        accessibility.bundleIdentifier = "ai.opencode.desktop"
        accessibility.role = kAXTextAreaRole as String
        accessibility.descriptionText = "Prompt"
        accessibility.domClasses = nil
        accessibility.value = ""
        accessibility.secondaryRole = kAXStaticTextRole as String
        accessibility.secondaryValue =
            "Ask anything, / for commands, @ for context..."
        accessibility.elementChildren[accessibility.nestedContainerElement] = [
            accessibility.element,
            accessibility.secondaryElement,
        ]
        accessibility.exposeOpenCodeWindow(
            children: [accessibility.nestedContainerElement],
            projectDirectory: FileManager.default.currentDirectoryPath,
            newSessionIsCurrent: true
        )
        accessibility.settableAttributes = [
            kAXFocusedAttribute as String,
            kAXSelectedTextRangeAttribute as String,
            kAXValueAttribute as String,
        ]
        let service = FocusedTextPasteService(
            accessibility: accessibility,
            pasteboard: FakeTextPasteboard(),
            postCommandV: { _ in false },
            openURL: { _, _ in false },
            validateOpenCodeApplication: { _ in true }
        )

        guard case .editable = service.captureTarget() else {
            Issue.record(
                "The exact V2 Prompt textarea should use its bound normal placeholder when Chromium omits AXDOMClassList"
            )
            return
        }
    }

    @Test
    @MainActor
    func floatingOpenCodePromptWithoutDOMClassesRejectsBoundShellPlaceholder() {
        let accessibility = FakeAccessibilityElementClient()
        accessibility.bundleIdentifier = "ai.opencode.desktop"
        accessibility.role = kAXTextAreaRole as String
        accessibility.descriptionText = "Prompt"
        accessibility.domClasses = nil
        accessibility.value = ""
        accessibility.secondaryRole = kAXStaticTextRole as String
        accessibility.secondaryValue = "Enter shell command..."
        accessibility.elementChildren[accessibility.nestedContainerElement] = [
            accessibility.element,
            accessibility.secondaryElement,
        ]
        accessibility.exposeOpenCodeWindow(
            children: [accessibility.nestedContainerElement],
            projectDirectory: FileManager.default.currentDirectoryPath,
            newSessionIsCurrent: true
        )
        accessibility.settableAttributes = [
            kAXFocusedAttribute as String,
            kAXSelectedTextRangeAttribute as String,
            kAXValueAttribute as String,
        ]
        let service = FocusedTextPasteService(
            accessibility: accessibility,
            pasteboard: FakeTextPasteboard(),
            postCommandV: { _ in false },
            openURL: { _, _ in false },
            validateOpenCodeApplication: { _ in true }
        )

        guard case .openCodeNewComposer = service.captureTarget() else {
            Issue.record(
                "The shared V2 Prompt label must not identify the shell editor when DOM classes are unavailable"
            )
            return
        }
        #expect(accessibility.performedAttributeMutations.isEmpty)
    }

    @Test
    @MainActor
    func floatingOpenCodeFallbackAttestationSurvivesPlaceholderRemoval() async throws {
        let content = "Verified V2 fallback context"
        let accessibility = FakeAccessibilityElementClient()
        accessibility.bundleIdentifier = "ai.opencode.desktop"
        accessibility.role = kAXTextAreaRole as String
        accessibility.descriptionText = "Prompt"
        accessibility.domClasses = nil
        accessibility.value = ""
        accessibility.secondaryRole = kAXStaticTextRole as String
        accessibility.secondaryValue =
            "Ask anything, / for commands, @ for context..."
        accessibility.tertiaryRole = kAXButtonRole as String
        accessibility.tertiaryDescriptionText = "Add images and files"
        accessibility.elementChildren[accessibility.nestedContainerElement] = [
            accessibility.element,
            accessibility.secondaryElement,
            accessibility.tertiaryElement,
        ]
        let projectDirectory = FileManager.default.currentDirectoryPath
        let canonicalProjectDirectory = URL(
            fileURLWithPath: projectDirectory,
            isDirectory: true
        ).standardizedFileURL.resolvingSymlinksInPath().path
        let windowState = FocusedTextPasteService
            .OpenCodeWindowStateAttestation(
                filePath: "/test/opencode.window.00000000-0000-0000-0000-000000000000.dat",
                device: 1,
                inode: 2,
                size: 243,
                modifiedSeconds: 3,
                modifiedNanoseconds: 4,
                activeDraftID: "11111111-1111-1111-1111-111111111111",
                projectDirectory: canonicalProjectDirectory
            )
        accessibility.exposeOpenCodeWindow(
            children: [accessibility.nestedContainerElement],
            projectDirectory: projectDirectory,
            newSessionIsCurrent: true
        )
        accessibility.settableAttributes = [
            kAXFocusedAttribute as String,
            kAXSelectedTextRangeAttribute as String,
            kAXValueAttribute as String,
        ]
        accessibility.successfulValueSetCallback = { element, value in
            guard CFEqual(element, accessibility.element), value == content
            else {
                return
            }
            // PromptInputV2 removes its placeholder as soon as AXValue becomes
            // nonempty. The normal-mode left control row remains visible.
            accessibility.elementChildren[
                accessibility.nestedContainerElement
            ] = [
                accessibility.element,
                accessibility.tertiaryElement,
            ]
        }
        var spacePosted = false
        var deletePosted = false
        let service = FocusedTextPasteService(
            accessibility: accessibility,
            pasteboard: FakeTextPasteboard(),
            postCommandV: { _ in false },
            postSpace: { _ in
                spacePosted = true
                accessibility.value = content + " "
                return true
            },
            postDeleteBackward: { _ in
                deletePosted = true
                accessibility.value = content
                return true
            },
            validateOpenCodeApplication: { _ in true },
            openCodeFocusSettleMilliseconds: 0,
            allowsLegacyOpenCodeEmptyComposerFallback: true,
            allowsOpenCodeURLRouting: false,
            attestOpenCodeWindowState: { requestedDirectory in
                #expect(requestedDirectory == canonicalProjectDirectory)
                return windowState
            }
        )

        let outcome = try await service.deliver(
            content,
            to: service.captureTarget(),
            openCodeProjectDirectory: projectDirectory
        )

        #expect(outcome == .insertedIntoVerifiedEmptyComposerWithInputSync)
        #expect(accessibility.value == content)
        #expect(spacePosted)
        #expect(deletePosted)
    }

    @Test
    @MainActor
    func floatingOpenCodeFallbackAttestationRejectsShellTransition() async throws {
        let content = "Must remain out of shell"
        let accessibility = FakeAccessibilityElementClient()
        accessibility.bundleIdentifier = "ai.opencode.desktop"
        accessibility.role = kAXTextAreaRole as String
        accessibility.descriptionText = "Prompt"
        accessibility.domClasses = nil
        accessibility.value = ""
        accessibility.secondaryRole = kAXStaticTextRole as String
        accessibility.secondaryValue =
            "Ask anything, / for commands, @ for context..."
        accessibility.tertiaryRole = kAXButtonRole as String
        accessibility.tertiaryDescriptionText = "Add images and files"
        accessibility.elementChildren[accessibility.nestedContainerElement] = [
            accessibility.element,
            accessibility.secondaryElement,
            accessibility.tertiaryElement,
        ]
        let projectDirectory = FileManager.default.currentDirectoryPath
        let canonicalProjectDirectory = URL(
            fileURLWithPath: projectDirectory,
            isDirectory: true
        ).standardizedFileURL.resolvingSymlinksInPath().path
        let windowState = FocusedTextPasteService
            .OpenCodeWindowStateAttestation(
                filePath: "/test/opencode.window.00000000-0000-0000-0000-000000000000.dat",
                device: 1,
                inode: 2,
                size: 243,
                modifiedSeconds: 3,
                modifiedNanoseconds: 4,
                activeDraftID: "11111111-1111-1111-1111-111111111111",
                projectDirectory: canonicalProjectDirectory
            )
        accessibility.exposeOpenCodeWindow(
            children: [accessibility.nestedContainerElement],
            projectDirectory: projectDirectory,
            newSessionIsCurrent: true
        )
        accessibility.settableAttributes = [
            kAXFocusedAttribute as String,
            kAXSelectedTextRangeAttribute as String,
            kAXValueAttribute as String,
        ]
        accessibility.successfulValueSetCallback = { element, value in
            guard CFEqual(element, accessibility.element), value == content
            else {
                return
            }
            // Shell mode hides/inerts the normal control row. With nonempty
            // content there is no placeholder, so the attestation must stop.
            accessibility.elementChildren[
                accessibility.nestedContainerElement
            ] = [accessibility.element]
        }
        var spacePosted = false
        var deletePosted = false
        let service = FocusedTextPasteService(
            accessibility: accessibility,
            pasteboard: FakeTextPasteboard(),
            postCommandV: { _ in false },
            postSpace: { _ in
                spacePosted = true
                return true
            },
            postDeleteBackward: { _ in
                deletePosted = true
                return true
            },
            validateOpenCodeApplication: { _ in true },
            openCodeFocusSettleMilliseconds: 0,
            allowsLegacyOpenCodeEmptyComposerFallback: true,
            allowsOpenCodeURLRouting: false,
            attestOpenCodeWindowState: { requestedDirectory in
                #expect(requestedDirectory == canonicalProjectDirectory)
                return windowState
            }
        )

        let outcome = try await service.deliver(
            content,
            to: service.captureTarget(),
            openCodeProjectDirectory: projectDirectory
        )

        #expect(
            outcome == .accessibilityInsertionUnverified(
                "macOS acknowledged the context insertion, but the editor "
                    + "did not expose the exact inserted value for verification."
            )
        )
        #expect(accessibility.value == content)
        #expect(!spacePosted)
        #expect(!deletePosted)
    }

    @Test
    @MainActor
    func floatingOpenCodeDirectTargetRejectsSamePIDWindowSwitch() async throws {
        let accessibility = FakeAccessibilityElementClient()
        accessibility.bundleIdentifier = "ai.opencode.desktop"
        accessibility.role = kAXTextAreaRole as String
        accessibility.descriptionText = "Ask anything..."
        accessibility.value = ""
        accessibility.settableAttributes = [
            kAXFocusedAttribute as String,
            kAXSelectedTextRangeAttribute as String,
            kAXValueAttribute as String,
        ]
        let projectDirectory = FileManager.default.temporaryDirectory.path
        accessibility.exposeOpenCodeWindow(
            children: [accessibility.element],
            projectDirectory: projectDirectory,
            newSessionIsCurrent: true
        )
        var synthesizedEvents: [String] = []
        let service = FocusedTextPasteService(
            accessibility: accessibility,
            pasteboard: FakeTextPasteboard(),
            postCommandV: { _ in
                synthesizedEvents.append("command-v")
                return true
            },
            postSpace: { _ in
                synthesizedEvents.append("space")
                return true
            },
            postDeleteBackward: { _ in
                synthesizedEvents.append("delete")
                return true
            },
            validateOpenCodeApplication: { _ in true }
        )
        let capture = service.captureTarget()

        accessibility.exposeOpenCodeWindow(
            children: [accessibility.element],
            projectDirectory: projectDirectory,
            newSessionIsCurrent: true,
            inAlternateWindow: true
        )
        let outcome = try await service.deliver(
            "Never cross an OpenCode window boundary",
            to: capture,
            openCodeProjectDirectory: projectDirectory
        )

        #expect(
            outcome == .notPasted(
                "OpenCode's captured window and selected project could not "
                    + "be verified. The context was copied."
            )
        )
        #expect(accessibility.value == "")
        #expect(synthesizedEvents.isEmpty)
    }

    @Test
    @MainActor
    func floatingOpenCodeLandingPageRejectsUnpresentedStaleComposers() async throws {
        for presentation in [
            "missing",
            "hidden",
            "invisible",
            "zero",
            "offscreen",
            "stale-hit-test",
            "ownerless",
        ] {
            let accessibility = FakeAccessibilityElementClient()
            accessibility.bundleIdentifier = "ai.opencode.desktop"
            accessibility.role = kAXTextAreaRole as String
            accessibility.descriptionText = "Ask anything..."
            accessibility.value = ""
            let projectDirectory = FileManager.default.currentDirectoryPath
            accessibility.exposeOpenCodeWindow(
                children: [accessibility.element],
                projectDirectory: projectDirectory,
                newSessionIsCurrent: true
            )
            switch presentation {
            case "missing":
                accessibility.elementsWithoutFrames.insert(accessibility.element)
            case "hidden":
                accessibility.hiddenElements.insert(accessibility.element)
            case "invisible":
                accessibility.invisibleElements.insert(accessibility.element)
            case "zero":
                accessibility.elementFrames[accessibility.element] = .zero
            case "offscreen":
                accessibility.elementFrames[accessibility.element] = CGRect(
                    x: 1_500,
                    y: 1_100,
                    width: 500,
                    height: 120
                )
            case "stale-hit-test":
                // A detached Electron node can retain its last good frame and
                // parent attributes. It is neither hit-test visible nor the
                // exact system-focused editor, so it must remain ineligible.
                accessibility.setFocusedElement(
                    accessibility.nestedContainerElement
                )
                accessibility.hitTestInvisibleElements.insert(
                    accessibility.element
                )
            default:
                accessibility.elementsWithoutWindowOwners.insert(
                    accessibility.element
                )
            }
            accessibility.settableAttributes = [
                kAXFocusedAttribute as String,
                kAXSelectedTextRangeAttribute as String,
                kAXValueAttribute as String,
            ]
            var openedURLCount = 0
            let service = FocusedTextPasteService(
                accessibility: accessibility,
                pasteboard: FakeTextPasteboard(),
                postCommandV: { _ in false },
                postSpace: { _ in false },
                postDeleteBackward: { _ in false },
                openURL: { _, _ in
                    openedURLCount += 1
                    return false
                },
                validateOpenCodeApplication: { _ in true },
                openCodeRouteTimeoutMilliseconds: 20,
                openCodeRouteGraceMilliseconds: 0,
                openCodeFocusSettleMilliseconds: 0,
                openCodeRoutePollMilliseconds: 1
            )

            let capture = service.captureTarget()
            #expect(accessibility.performedAttributeMutations.isEmpty)
            let outcome = try await service.deliver(
                "Never write a landing-page ghost",
                to: capture,
                openCodeProjectDirectory: projectDirectory
            )

            #expect(
                outcome == .notPasted(
                    "macOS could not request a new OpenCode chat composer. "
                        + "The context was copied."
                ),
                Comment(rawValue: presentation)
            )
            #expect(openedURLCount == 1, Comment(rawValue: presentation))
            #expect(
                accessibility.performedAttributeMutations.isEmpty,
                Comment(rawValue: presentation)
            )
            #expect(accessibility.value == "", Comment(rawValue: presentation))
        }
    }

    @Test
    @MainActor
    func floatingOpenCodeMarkerRequiredRejectsAnEmptyComposerMadeVisibleByRoute() async throws {
        let content = "Context for the newly rendered composer"
        let accessibility = FakeAccessibilityElementClient()
        accessibility.bundleIdentifier = "ai.opencode.desktop"
        accessibility.role = kAXTextAreaRole as String
        accessibility.descriptionText = "Ask anything..."
        accessibility.value = ""
        let projectDirectory = FileManager.default.currentDirectoryPath
        accessibility.exposeOpenCodeWindow(
            children: [accessibility.element],
            projectDirectory: projectDirectory,
            newSessionIsCurrent: true
        )
        accessibility.elementsWithoutFrames.insert(accessibility.element)
        accessibility.settableAttributes = [
            kAXFocusedAttribute as String,
            kAXSelectedTextRangeAttribute as String,
            kAXValueAttribute as String,
        ]
        var openedURLCount = 0
        var mutationsBeforeRoute = -1
        let service = FocusedTextPasteService(
            accessibility: accessibility,
            pasteboard: FakeTextPasteboard(),
            postCommandV: { _ in false },
            postSpace: { _ in
                accessibility.value = content + " "
                return true
            },
            postDeleteBackward: { _ in
                accessibility.value = content
                return true
            },
            openURL: { _, _ in
                openedURLCount += 1
                mutationsBeforeRoute = accessibility
                    .performedAttributeMutations.count
                accessibility.elementsWithoutFrames.remove(
                    accessibility.element
                )
                return true
            },
            validateOpenCodeApplication: { _ in true },
            openCodeRouteTimeoutMilliseconds: 100,
            openCodeRouteGraceMilliseconds: 0,
            openCodeFocusSettleMilliseconds: 0,
            openCodeRoutePollMilliseconds: 1,
            allowsLegacyOpenCodeEmptyComposerFallback: false
        )

        let capture = service.captureTarget()
        #expect(accessibility.performedAttributeMutations.isEmpty)
        let outcome = try await service.deliver(
            content,
            to: capture,
            openCodeProjectDirectory: projectDirectory
        )

        #expect(
            outcome == .notPasted(
                "OpenCode did not expose the requested active project and "
                    + "exactly one verified empty chat composer in the captured "
                    + "window; try the floating action again. The context was copied."
            )
        )
        #expect(openedURLCount == 1)
        #expect(mutationsBeforeRoute == 0)
        #expect(accessibility.value == "")
        #expect(accessibility.performedAttributeMutations.isEmpty)
    }

    @Test
    @MainActor
    func floatingOpenCodeVisibleComposerThatDisappearsIsNeverMutated() async throws {
        let accessibility = FakeAccessibilityElementClient()
        accessibility.bundleIdentifier = "ai.opencode.desktop"
        accessibility.role = kAXTextAreaRole as String
        accessibility.descriptionText = "Ask anything..."
        accessibility.value = ""
        let projectDirectory = FileManager.default.currentDirectoryPath
        accessibility.exposeOpenCodeWindow(
            children: [accessibility.element],
            projectDirectory: projectDirectory,
            newSessionIsCurrent: true
        )
        accessibility.settableAttributes = [
            kAXFocusedAttribute as String,
            kAXSelectedTextRangeAttribute as String,
            kAXValueAttribute as String,
        ]
        var synthesizedEvents: [String] = []
        let service = FocusedTextPasteService(
            accessibility: accessibility,
            pasteboard: FakeTextPasteboard(),
            postCommandV: { _ in
                synthesizedEvents.append("command-v")
                return true
            },
            postSpace: { _ in
                synthesizedEvents.append("space")
                return true
            },
            postDeleteBackward: { _ in
                synthesizedEvents.append("delete")
                return true
            },
            validateOpenCodeApplication: { _ in true }
        )
        let capture = service.captureTarget()
        accessibility.hiddenElements.insert(accessibility.element)

        let outcome = try await service.deliver(
            "Do not mutate a vanished composer",
            to: capture,
            openCodeProjectDirectory: projectDirectory
        )

        #expect(
            outcome == .notPasted(
                "OpenCode's captured window and selected project could not "
                    + "be verified. The context was copied."
            )
        )
        #expect(accessibility.performedAttributeMutations.isEmpty)
        #expect(synthesizedEvents.isEmpty)
        #expect(accessibility.value == "")
    }

    @Test
    @MainActor
    func floatingOpenCodeLandingPageRoutesAndLoadsWithoutCommandVOrSubmit() async throws {
        let accessibility = FakeAccessibilityElementClient()
        accessibility.bundleIdentifier = "ai.opencode.desktop"
        accessibility.role = kAXGroupRole as String
        accessibility.settableAttributes = [
            kAXFocusedAttribute as String,
            kAXSelectedTextRangeAttribute as String,
            kAXValueAttribute as String,
        ]
        let pasteboard = FakeTextPasteboard()
        let projectDirectory = FileManager.default.currentDirectoryPath
        let canonicalProjectDirectory = URL(
            fileURLWithPath: projectDirectory,
            isDirectory: true
        ).standardizedFileURL.resolvingSymlinksInPath().path
        var openedURLs: [URL] = []
        var synthesizedEvents: [String] = []
        var trustedApplicationChecks = 0
        let service = FocusedTextPasteService(
            accessibility: accessibility,
            pasteboard: pasteboard,
            postCommandV: { _ in
                synthesizedEvents.append("command-v")
                return true
            },
            postSpace: { _ in
                synthesizedEvents.append("space")
                return accessibility.typeSpaceInFocusedElement()
            },
            postDeleteBackward: { _ in
                synthesizedEvents.append("delete")
                return accessibility.deleteSelectionInFocusedElement()
            },
            openURL: { url, bundlePath in
                #expect(bundlePath == "/Applications/OpenCode.app")
                openedURLs.append(url)
                let components = URLComponents(
                    url: url,
                    resolvingAgainstBaseURL: false
                )
                let queryItems = components?.queryItems ?? []
                #expect(components?.scheme == "opencode")
                #expect(components?.host == "new-session")
                #expect(components?.path == "")
                #expect(queryItems.count == 2)
                #expect(queryItems.map(\.name) == ["directory", "prompt"])
                #expect(
                    queryItems.first(where: { $0.name == "directory" })?.value
                        == canonicalProjectDirectory
                )
                let marker = queryItems.first(where: {
                    $0.name == "prompt"
                })?.value
                #expect(marker?.hasPrefix("ds-") == true)
                #expect(marker?.count == 35)
                #expect(!url.absoluteString.contains("Landing-page%20Workspace"))
                accessibility.secondaryRole = kAXTextAreaRole as String
                // Production OpenCode 1.18 PromptInputV2 exposes the localized
                // label "Prompt" and this class shape, not the legacy
                // "Ask anything..." identity.
                accessibility.secondaryDescriptionText = "Prompt"
                accessibility.secondaryDOMClasses = [
                    "relative",
                    "z-10",
                    "block",
                    "min-h-[60px]",
                    "max-h-[180px]",
                    "w-full",
                    "overflow-y-auto",
                    "whitespace-pre-wrap",
                    "bg-transparent",
                    "px-4",
                    "pt-4",
                    "pb-2",
                    "text-[13px]",
                    "font-[440]",
                    "leading-5",
                    "text-v2-text-text-base",
                    "focus:outline-none",
                ]
                accessibility.secondaryValue = marker
                // OpenCode 1.18 creates a /new-session draft and exposes its
                // visible prompt before the sidebar offers legacy project
                // evidence. The per-route nonce is the exact binding.
                accessibility.focusedWindowChildren = [
                    accessibility.secondaryElement,
                ]
                accessibility.setFocusedElement(
                    accessibility.secondaryElement
                )
                return true
            },
            validateOpenCodeApplication: {
                trustedApplicationChecks += 1
                return $0 == "/Applications/OpenCode.app"
            },
            openCodeRouteTimeoutMilliseconds: 50,
            openCodeRouteGraceMilliseconds: 0,
            openCodeFocusSettleMilliseconds: 0,
            openCodeRoutePollMilliseconds: 1,
            allowsLegacyOpenCodeEmptyComposerFallback: false
        )

        let outcome = try await service.deliver(
            "Landing-page Workspace Context",
            to: service.captureTarget(),
            openCodeProjectDirectory: projectDirectory
        )

        #expect(outcome == .markerReplacedWithVerifiedInputSync)
        #expect(openedURLs.count == 1)
        #expect(trustedApplicationChecks >= 4)
        #expect(accessibility.secondaryValue == "Landing-page Workspace Context")
        #expect(synthesizedEvents == ["space", "delete"])
        #expect(
            pasteboard.string(forType: .string)
                == "Landing-page Workspace Context"
        )
    }

    @Test
    @MainActor
    func floatingOpenCodeCompactNewSessionPastesWithoutDispatchingAURL() async throws {
        let accessibility = FakeAccessibilityElementClient()
        accessibility.bundleIdentifier = "ai.opencode.desktop"
        accessibility.secondaryRole = kAXTextAreaRole as String
        accessibility.secondaryDescriptionText = "Prompt"
        accessibility.secondaryDOMClasses = [
            "min-h-[60px]",
            "max-h-[180px]",
            "w-full",
            "overflow-y-auto",
            "whitespace-pre-wrap",
            "text-v2-text-text-base",
            "focus:outline-none",
        ]
        accessibility.secondaryValue = ""
        accessibility.settableAttributes = [
            kAXFocusedAttribute as String,
            kAXSelectedTextRangeAttribute as String,
            kAXValueAttribute as String,
        ]
        accessibility.setFocusedElement(accessibility.secondaryElement)
        let projectDirectory = FileManager.default.currentDirectoryPath
        let canonicalProjectDirectory = URL(
            fileURLWithPath: projectDirectory,
            isDirectory: true
        ).standardizedFileURL.resolvingSymlinksInPath().path
        let windowState = FocusedTextPasteService
            .OpenCodeWindowStateAttestation(
                filePath: "/test/opencode.window.00000000-0000-0000-0000-000000000000.dat",
                device: 1,
                inode: 2,
                size: 243,
                modifiedSeconds: 3,
                modifiedNanoseconds: 4,
                activeDraftID: "11111111-1111-1111-1111-111111111111",
                projectDirectory: canonicalProjectDirectory
            )
        var stateAttestationReads = 0
        accessibility.exposeOpenCodeCompactNewSessionWindow(
            composer: accessibility.secondaryElement,
            projectDirectory: projectDirectory
        )
        let pasteboard = FakeTextPasteboard()
        var openedURLs: [URL] = []
        var synthesizedEvents: [String] = []
        let service = FocusedTextPasteService(
            accessibility: accessibility,
            pasteboard: pasteboard,
            postCommandV: { _ in
                synthesizedEvents.append("command-v")
                return true
            },
            postSpace: { _ in
                synthesizedEvents.append("space")
                return accessibility.typeSpaceInFocusedElement()
            },
            postDeleteBackward: { _ in
                synthesizedEvents.append("delete")
                return accessibility.deleteSelectionInFocusedElement()
            },
            openURL: { url, _ in
                openedURLs.append(url)
                return true
            },
            validateOpenCodeApplication: { _ in true },
            openCodeFocusSettleMilliseconds: 0,
            allowsLegacyOpenCodeEmptyComposerFallback: true,
            allowsOpenCodeURLRouting: false,
            attestOpenCodeWindowState: { requestedDirectory in
                stateAttestationReads += 1
                #expect(requestedDirectory == canonicalProjectDirectory)
                return windowState
            }
        )

        // The overlay can capture the window before its async workspace lookup
        // returns. Exact project attestation is therefore supplied at delivery,
        // while the original app/window identity remains bound.
        let capture = service.captureTarget()
        let outcome = try await service.deliver(
            "Exact compact landing context",
            to: capture,
            openCodeProjectDirectory: projectDirectory
        )

        #expect(outcome == .insertedIntoVerifiedEmptyComposerWithInputSync)
        #expect(accessibility.secondaryValue == "Exact compact landing context")
        #expect(openedURLs.isEmpty)
        #expect(synthesizedEvents == ["space", "delete"])
        // Focused-composer mode deliberately makes no project or navigation
        // claim, so it must not consult the legacy window-state attestation.
        #expect(stateAttestationReads == 0)
    }

    @Test
    @MainActor
    func floatingOpenCodeAllowsAuxiliaryWindowsAndFocusesExactComposer() async throws {
        let accessibility = FakeAccessibilityElementClient()
        accessibility.bundleIdentifier = "ai.opencode.desktop"
        accessibility.secondaryRole = kAXTextAreaRole as String
        accessibility.secondaryDescriptionText = "Prompt"
        accessibility.secondaryDOMClasses = [
            "min-h-[60px]",
            "max-h-[180px]",
            "w-full",
            "overflow-y-auto",
            "whitespace-pre-wrap",
            "text-v2-text-text-base",
            "focus:outline-none",
        ]
        accessibility.secondaryValue = ""
        accessibility.settableAttributes = [
            kAXFocusedAttribute as String,
            kAXSelectedTextRangeAttribute as String,
            kAXValueAttribute as String,
        ]
        let projectDirectory = FileManager.default.currentDirectoryPath
        let canonicalProjectDirectory = URL(
            fileURLWithPath: projectDirectory,
            isDirectory: true
        ).standardizedFileURL.resolvingSymlinksInPath().path
        let windowState = FocusedTextPasteService
            .OpenCodeWindowStateAttestation(
                filePath: "/test/opencode.window.00000000-0000-0000-0000-000000000000.dat",
                device: 1,
                inode: 2,
                size: 243,
                modifiedSeconds: 3,
                modifiedNanoseconds: 4,
                activeDraftID: "11111111-1111-1111-1111-111111111111",
                projectDirectory: canonicalProjectDirectory
            )
        accessibility.exposeOpenCodeCompactNewSessionWindow(
            composer: accessibility.secondaryElement,
            projectDirectory: projectDirectory
        )
        accessibility.exposeAuxiliaryWindowAlongsideFocusedWindow()
        // The user clicked DaemonState's non-activating floating control while
        // OpenCode's landing view, rather than its empty composer, owned AX
        // focus. The exact composer may be focused only after all draft/window
        // attestations have succeeded.
        accessibility.setFocusedElement(
            accessibility.compactNewSessionTitleElement
        )
        let pasteboard = FakeTextPasteboard()
        var openedURLs: [URL] = []
        var synthesizedEvents: [String] = []
        let service = FocusedTextPasteService(
            accessibility: accessibility,
            pasteboard: pasteboard,
            postCommandV: { _ in
                synthesizedEvents.append("command-v")
                return true
            },
            postSpace: { _ in
                synthesizedEvents.append("space")
                return accessibility.typeSpaceInFocusedElement()
            },
            postDeleteBackward: { _ in
                synthesizedEvents.append("delete")
                return accessibility.deleteSelectionInFocusedElement()
            },
            openURL: { url, _ in
                openedURLs.append(url)
                return true
            },
            validateOpenCodeApplication: { _ in true },
            openCodeFocusSettleMilliseconds: 0,
            allowsLegacyOpenCodeEmptyComposerFallback: true,
            allowsOpenCodeURLRouting: false,
            attestOpenCodeWindowState: { requestedDirectory in
                #expect(requestedDirectory == canonicalProjectDirectory)
                return windowState
            }
        )

        let outcome = try await service.deliver(
            "Focus-safe compact landing context",
            to: service.captureTarget(),
            openCodeProjectDirectory: projectDirectory
        )

        #expect(outcome == .insertedIntoVerifiedEmptyComposerWithInputSync)
        #expect(accessibility.secondaryValue == "Focus-safe compact landing context")
        #expect(accessibility.focusedElementMatches(accessibility.secondaryElement))
        #expect(openedURLs.isEmpty)
        #expect(synthesizedEvents == ["space", "delete"])
        #expect(
            accessibility.performedAttributeMutations.contains { mutation in
                mutation.attribute == kAXFocusedAttribute as String
                    && CFEqual(mutation.element, accessibility.secondaryElement)
            }
        )
    }

    @Test
    @MainActor
    func floatingOpenCodeRejectsWrongAndMissingExpectedWindowMembership() async throws {
        let projectDirectory = FileManager.default.currentDirectoryPath

        for hasWrongWindow in [true, false] {
            let accessibility = FakeAccessibilityElementClient()
            accessibility.bundleIdentifier = "ai.opencode.desktop"
            accessibility.role = kAXGroupRole as String
            if hasWrongWindow {
                accessibility.exposeOnlyWrongApplicationWindow()
            } else {
                accessibility.exposeNoApplicationWindows()
            }
            let pasteboard = FakeTextPasteboard()
            var openedURLs: [URL] = []
            var stateAttestationReads = 0
            let service = FocusedTextPasteService(
                accessibility: accessibility,
                pasteboard: pasteboard,
                postCommandV: { _ in false },
                openURL: { url, _ in
                    openedURLs.append(url)
                    return true
                },
                validateOpenCodeApplication: { _ in true },
                openCodeFocusSettleMilliseconds: 0,
                allowsLegacyOpenCodeEmptyComposerFallback: true,
                allowsOpenCodeURLRouting: false,
                attestOpenCodeWindowState: { _ in
                    stateAttestationReads += 1
                    return nil
                }
            )

            let outcome = try await service.deliver(
                "Window-membership rejection",
                to: service.captureTarget(),
                openCodeProjectDirectory: projectDirectory
            )

            guard case .notPasted = outcome else {
                Issue.record("Wrong or missing expected window must reject")
                continue
            }
            #expect(openedURLs.isEmpty)
            #expect(stateAttestationReads == 0)
            #expect(accessibility.performedActions.isEmpty)
            #expect(accessibility.performedAttributeMutations.isEmpty)
        }
    }

    @Test
    @MainActor
    func floatingOpenCodeWithoutAnAttestedComposerNeverDispatchesAURL() async throws {
        let accessibility = FakeAccessibilityElementClient()
        accessibility.bundleIdentifier = "ai.opencode.desktop"
        accessibility.role = kAXGroupRole as String
        let projectDirectory = FileManager.default.currentDirectoryPath
        var openedURLs: [URL] = []
        let service = FocusedTextPasteService(
            accessibility: accessibility,
            pasteboard: FakeTextPasteboard(),
            postCommandV: { _ in false },
            openURL: { url, _ in
                openedURLs.append(url)
                return true
            },
            validateOpenCodeApplication: { _ in true },
            openCodeRouteTimeoutMilliseconds: 10,
            openCodeRouteGraceMilliseconds: 0,
            openCodeFocusSettleMilliseconds: 0,
            openCodeRoutePollMilliseconds: 1,
            allowsLegacyOpenCodeEmptyComposerFallback: true,
            allowsOpenCodeURLRouting: false
        )

        let outcome = try await service.deliver(
            "Copy without navigation",
            to: service.captureTarget(
                attestingOpenCodeProjectDirectory: projectDirectory
            ),
            openCodeProjectDirectory: projectDirectory
        )

        guard case let .notPasted(message) = outcome else {
            Issue.record("Missing attestation must remain copy-only")
            return
        }
        #expect(
            message == "Open exactly one empty normal OpenCode chat composer, "
                + "then try again. The context was copied."
        )
        #expect(openedURLs.isEmpty)
        #expect(accessibility.performedActions.isEmpty)
        #expect(accessibility.performedAttributeMutations.isEmpty)
    }

    @Test
    @MainActor
    func floatingOpenCodeRouteCannotResumeAfterTheUserSwitchesToChrome() async throws {
        let accessibility = FakeAccessibilityElementClient()
        accessibility.bundleIdentifier = "ai.opencode.desktop"
        accessibility.role = kAXGroupRole as String
        let projectDirectory = FileManager.default.currentDirectoryPath
        var openedURLs: [URL] = []
        var synthesizedEvents: [String] = []
        let service = FocusedTextPasteService(
            accessibility: accessibility,
            pasteboard: FakeTextPasteboard(),
            postCommandV: { _ in
                synthesizedEvents.append("command-v")
                return true
            },
            postSpace: { _ in
                synthesizedEvents.append("space")
                return true
            },
            postDeleteBackward: { _ in
                synthesizedEvents.append("delete")
                return true
            },
            openURL: { url, _ in
                openedURLs.append(url)
                // The first observation after dispatch is Chrome. A later
                // rebound to OpenCode must never re-arm this invocation.
                accessibility.frontmostPIDSequence = [
                    99_999,
                    accessibility.processIdentifier,
                ]
                return true
            },
            validateOpenCodeApplication: { _ in true },
            openCodeRouteTimeoutMilliseconds: 30,
            openCodeRouteGraceMilliseconds: 0,
            openCodeFocusSettleMilliseconds: 0,
            openCodeRoutePollMilliseconds: 1,
            allowsLegacyOpenCodeEmptyComposerFallback: false,
            allowsOpenCodeURLRouting: true
        )

        let outcome = try await service.deliver(
            "Never resume after Chrome",
            to: service.captureTarget(),
            openCodeProjectDirectory: projectDirectory
        )

        guard case let .notPasted(message) = outcome else {
            Issue.record("The first focus change must permanently cancel routing")
            return
        }
        #expect(message.contains("will not reactivate"))
        #expect(openedURLs.count == 1)
        #expect(synthesizedEvents.isEmpty)
        #expect(accessibility.performedActions.isEmpty)
        #expect(accessibility.performedAttributeMutations.isEmpty)
    }

    @Test
    @MainActor
    func floatingOpenCodeNeverReclaimsFocusForANonceComposer() async throws {
        let accessibility = FakeAccessibilityElementClient()
        accessibility.bundleIdentifier = "ai.opencode.desktop"
        accessibility.role = kAXGroupRole as String
        let projectDirectory = FileManager.default.currentDirectoryPath
        var synthesizedEvents: [String] = []
        let service = FocusedTextPasteService(
            accessibility: accessibility,
            pasteboard: FakeTextPasteboard(),
            postCommandV: { _ in
                synthesizedEvents.append("command-v")
                return true
            },
            postSpace: { _ in
                synthesizedEvents.append("space")
                return true
            },
            postDeleteBackward: { _ in
                synthesizedEvents.append("delete")
                return true
            },
            openURL: { url, _ in
                let marker = URLComponents(
                    url: url,
                    resolvingAgainstBaseURL: false
                )?.queryItems?.first(where: { $0.name == "prompt" })?.value
                accessibility.secondaryRole = kAXTextAreaRole as String
                accessibility.secondaryDescriptionText = "Prompt"
                accessibility.secondaryDOMClasses = [
                    "min-h-[60px]",
                    "max-h-[180px]",
                    "w-full",
                    "overflow-y-auto",
                    "whitespace-pre-wrap",
                    "text-v2-text-text-base",
                    "focus:outline-none",
                ]
                accessibility.secondaryValue = marker
                accessibility.focusedWindowChildren = [
                    accessibility.secondaryElement,
                ]
                // The user kept focus on another control. DaemonState must not
                // set AXFocused on the new editor to make the test pass.
                return true
            },
            validateOpenCodeApplication: { _ in true },
            openCodeRouteTimeoutMilliseconds: 30,
            openCodeRouteGraceMilliseconds: 0,
            openCodeFocusSettleMilliseconds: 0,
            openCodeRoutePollMilliseconds: 1,
            allowsLegacyOpenCodeEmptyComposerFallback: false
        )

        let outcome = try await service.deliver(
            "Never reclaim focus",
            to: service.captureTarget(),
            openCodeProjectDirectory: projectDirectory
        )

        guard case .notPasted = outcome else {
            Issue.record("An unfocused nonce composer must remain copy-only")
            return
        }
        #expect(accessibility.performedAttributeMutations.isEmpty)
        #expect(accessibility.secondaryValue?.hasPrefix("ds-") == true)
        #expect(synthesizedEvents.isEmpty)
    }

    @Test
    @MainActor
    func floatingOpenCodeLinkModeRejectsSecondUnparentedCurrentLink() async throws {
        let accessibility = FakeAccessibilityElementClient()
        accessibility.bundleIdentifier = "ai.opencode.desktop"
        accessibility.role = kAXGroupRole as String
        accessibility.settableAttributes = [
            kAXFocusedAttribute as String,
            kAXSelectedTextRangeAttribute as String,
            kAXValueAttribute as String,
        ]
        let projectDirectory = FileManager.default.temporaryDirectory.path
        let pasteboard = FakeTextPasteboard()
        var synthesizedEvents: [String] = []
        let service = FocusedTextPasteService(
            accessibility: accessibility,
            pasteboard: pasteboard,
            postCommandV: { _ in
                synthesizedEvents.append("command-v")
                return true
            },
            postSpace: { _ in
                synthesizedEvents.append("space")
                accessibility.secondaryValue = "Reject ambiguous current links "
                return true
            },
            postDeleteBackward: { _ in
                synthesizedEvents.append("delete")
                accessibility.secondaryValue = "Reject ambiguous current links"
                return true
            },
            openURL: { _, _ in
                accessibility.secondaryRole = kAXTextAreaRole as String
                accessibility.secondaryDescriptionText = "Ask anything..."
                accessibility.secondaryValue = "\n"
                accessibility.exposeOpenCodeWindow(
                    children: [accessibility.secondaryElement],
                    projectDirectory: projectDirectory,
                    newSessionIsCurrent: true,
                    includeOrphanCurrentLink: true
                )
                return true
            },
            validateOpenCodeApplication: { _ in true },
            openCodeRouteTimeoutMilliseconds: 5,
            openCodeRouteGraceMilliseconds: 0,
            openCodeFocusSettleMilliseconds: 0,
            openCodeRoutePollMilliseconds: 1
        )

        let outcome = try await service.deliver(
            "Reject ambiguous current links",
            to: service.captureTarget(),
            openCodeProjectDirectory: projectDirectory
        )

        #expect(
            outcome == .notPasted(
                "OpenCode did not expose the requested active project and "
                    + "exactly one verified empty chat composer in the captured "
                    + "window; try the floating action again. "
                    + "The context was copied."
            )
        )
        #expect(accessibility.secondaryValue == "\n")
        #expect(synthesizedEvents.isEmpty)
        #expect(accessibility.performedActions.isEmpty)
        #expect(
            accessibility.elementAttribute(
                kAXParentAttribute as CFString,
                from: accessibility.orphanCurrentSessionLinkElement
            ) == nil
        )
        #expect(
            pasteboard.string(forType: .string)
                == "Reject ambiguous current links"
        )
    }

    @Test
    @MainActor
    func floatingOpenCodeLandingPageRoutesThroughLocalProjectRegion() async throws {
        let requestedContent = realisticRetainedOpenCodeContext(
            utf16Length: 25_730,
            heading: "# Local-project context"
        )
        let chromiumSentinelValue = String(requestedContent.dropLast())
            + " \n"
        let accessibility = FakeAccessibilityElementClient()
        accessibility.bundleIdentifier = "ai.opencode.desktop"
        accessibility.role = kAXGroupRole as String
        accessibility.settableAttributes = [
            kAXFocusedAttribute as String,
            kAXSelectedTextRangeAttribute as String,
            kAXValueAttribute as String,
        ]
        let pasteboard = FakeTextPasteboard()
        let projectDirectory = FileManager.default.currentDirectoryPath
        let canonicalProjectDirectory = URL(
            fileURLWithPath: projectDirectory,
            isDirectory: true
        ).standardizedFileURL.resolvingSymlinksInPath().path
        let home = FileManager.default.homeDirectoryForCurrentUser.path
        let projectDisplay = canonicalProjectDirectory.hasPrefix(home + "/")
            ? "~" + canonicalProjectDirectory.dropFirst(home.count)
            : canonicalProjectDirectory
        accessibility.secondaryRole = kAXTextAreaRole as String
        accessibility.secondaryDescriptionText = "Ask anything..."
        // This is the stale composer that the deep link leaves untouched in
        // OpenCode's single-local-workspace mode.
        accessibility.secondaryValue = "\n"
        accessibility.exposeOpenCodeLocalProjectWindow(
            children: [accessibility.secondaryElement],
            projectDirectory: canonicalProjectDirectory,
            projectDisplay: String(projectDisplay)
        )
        accessibility.performActionCallback = { action, element, result in
            #expect(action == kAXPressAction as String)
            #expect(CFEqual(element, accessibility.localNewSessionButtonElement))
            #expect(result == .success)
            accessibility.tertiaryRole = kAXTextAreaRole as String
            accessibility.tertiaryDescriptionText = "Ask anything..."
            accessibility.tertiaryValue = "\n"
            accessibility.exposeOpenCodeLocalProjectWindow(
                children: [accessibility.tertiaryElement],
                projectDirectory: canonicalProjectDirectory,
                projectDisplay: String(projectDisplay)
            )
        }
        var openedURLs: [URL] = []
        var synthesizedEvents: [String] = []
        let service = FocusedTextPasteService(
            accessibility: accessibility,
            pasteboard: pasteboard,
            postCommandV: { _ in
                synthesizedEvents.append("command-v")
                return true
            },
            postSpace: { _ in
                synthesizedEvents.append("space")
                accessibility.tertiaryValue = chromiumSentinelValue
                return true
            },
            postDeleteBackward: { _ in
                synthesizedEvents.append("delete")
                accessibility.tertiaryValue = requestedContent
                return true
            },
            openURL: { url, bundlePath in
                #expect(bundlePath == "/Applications/OpenCode.app")
                openedURLs.append(url)
                #expect(accessibility.secondaryValue == "\n")
                #expect(
                    accessibility.focusedWindowChildren.contains {
                        CFEqual($0, accessibility.secondaryElement)
                    }
                )
                return true
            },
            validateOpenCodeApplication: { _ in true },
            openCodeRouteTimeoutMilliseconds: 50,
            openCodeRouteGraceMilliseconds: 0,
            openCodeFocusSettleMilliseconds: 0,
            openCodeRoutePollMilliseconds: 1
        )

        let outcome = try await service.deliver(
            requestedContent,
            to: service.captureTarget(),
            openCodeProjectDirectory: projectDirectory
        )

        #expect(outcome == .insertedIntoVerifiedEmptyComposerWithInputSync)
        #expect(openedURLs.count == 1)
        #expect(accessibility.secondaryValue == "\n")
        #expect(accessibility.tertiaryValue == requestedContent)
        #expect(synthesizedEvents == ["space", "delete"])
        #expect(
            accessibility.performedActions.map { $0.action }
                == [kAXPressAction as String]
        )
        #expect(
            accessibility.performedActions.allSatisfy {
                CFEqual($0.element, accessibility.localNewSessionButtonElement)
            }
        )
        #expect(
            !accessibility.focusedWindowChildren.contains {
                CFEqual($0, accessibility.newSessionEvidenceElement)
            }
        )
        #expect(pasteboard.string(forType: .string) == requestedContent)
    }

    @Test
    @MainActor
    func floatingOpenCodePostPressUsesAFreshBoundedInspectionPhase() async throws {
        let accessibility = FakeAccessibilityElementClient()
        accessibility.bundleIdentifier = "ai.opencode.desktop"
        accessibility.role = kAXGroupRole as String
        accessibility.secondaryRole = kAXTextAreaRole as String
        accessibility.secondaryDescriptionText = "Ask anything..."
        accessibility.secondaryValue = "\n"
        accessibility.settableAttributes = [
            kAXFocusedAttribute as String,
            kAXSelectedTextAttribute as String,
            kAXSelectedTextRangeAttribute as String,
            kAXValueAttribute as String,
        ]
        let projectDirectory = FileManager.default.currentDirectoryPath
        accessibility.exposeOpenCodeLocalProjectWindow(
            children: [accessibility.secondaryElement],
            projectDirectory: projectDirectory
        )
        accessibility.performActionCallback = { _, _, result in
            #expect(result == .success)
            // Consume more than the navigation phase's entire budget. A
            // shared deadline would now emit the generic route timeout even
            // though the verified New-session action succeeded.
            Thread.sleep(forTimeInterval: 0.075)
            accessibility.tertiaryRole = kAXTextAreaRole as String
            accessibility.tertiaryDescriptionText = "Ask anything..."
            accessibility.tertiaryValue = "\n"
            accessibility.exposeOpenCodeLocalProjectWindow(
                children: [accessibility.tertiaryElement],
                projectDirectory: projectDirectory
            )
        }
        var synthesizedEvents: [String] = []
        let service = FocusedTextPasteService(
            accessibility: accessibility,
            pasteboard: FakeTextPasteboard(),
            postCommandV: { _ in
                synthesizedEvents.append("command-v")
                return true
            },
            postSpace: { _ in
                synthesizedEvents.append("space")
                accessibility.tertiaryValue = "Post-press context "
                return true
            },
            postDeleteBackward: { _ in
                synthesizedEvents.append("delete")
                accessibility.tertiaryValue = "Post-press context"
                return true
            },
            openURL: { _, _ in true },
            validateOpenCodeApplication: { _ in true },
            openCodeRouteTimeoutMilliseconds: 50,
            openCodeRouteGraceMilliseconds: 0,
            openCodeFocusSettleMilliseconds: 0,
            openCodeRoutePollMilliseconds: 1
        )

        let outcome = try await service.deliver(
            "Post-press context",
            to: service.captureTarget(),
            openCodeProjectDirectory: projectDirectory
        )

        #expect(outcome == .insertedIntoVerifiedEmptyComposerWithInputSync)
        #expect(accessibility.tertiaryValue == "Post-press context")
        #expect(synthesizedEvents == ["space", "delete"])
    }

    @Test
    @MainActor
    func floatingOpenCodeLocalModePreflightsRetainedRequestedContextBeforeRouting() async throws {
        // The second variant is exactly the 25,731 UTF-16-unit AXValue observed
        // in the deployed retry state: Chromium inserted one structural space
        // immediately before the requested content's final line feed.
        let requestedContent = realisticRetainedOpenCodeContext(
            utf16Length: 25_730,
            heading: "# Daemonstate workspace context"
        )
        let chromiumNormalizedContent = String(requestedContent.dropLast())
            + " \n"
        for retainedValue in [requestedContent, chromiumNormalizedContent] {
            let accessibility = FakeAccessibilityElementClient()
            accessibility.bundleIdentifier = "ai.opencode.desktop"
            accessibility.role = kAXGroupRole as String
            accessibility.secondaryRole = kAXTextAreaRole as String
            accessibility.secondaryDescriptionText =
                "Ask anything... \"How do environment variables work here?\""
            accessibility.secondaryValue = retainedValue
            accessibility.settableAttributes = [
                kAXFocusedAttribute as String,
                kAXSelectedTextAttribute as String,
                kAXSelectedTextRangeAttribute as String,
                kAXValueAttribute as String,
            ]
            let projectDirectory = FileManager.default.currentDirectoryPath
            let canonicalProjectDirectory = URL(
                fileURLWithPath: projectDirectory,
                isDirectory: true
            ).standardizedFileURL.resolvingSymlinksInPath().path
            let home = FileManager.default.homeDirectoryForCurrentUser.path
            let projectDisplay = canonicalProjectDirectory.hasPrefix(home + "/")
                ? "~" + canonicalProjectDirectory.dropFirst(home.count)
                : canonicalProjectDirectory
            accessibility.exposeOpenCodeLocalProjectWindow(
                children: [accessibility.secondaryElement],
                projectDirectory: canonicalProjectDirectory,
                projectDisplay: String(projectDisplay)
            )
            let retainedComposer = accessibility.secondaryElement
            let pasteboard = FakeTextPasteboard()
            var openedURLs: [URL] = []
            var synthesizedEvents: [String] = []
            accessibility.performActionCallback = { action, element, result in
                #expect(action == kAXPressAction as String)
                #expect(
                    CFEqual(
                        element,
                        accessibility.localNewSessionButtonElement
                    )
                )
                #expect(result == .success)
                #expect(accessibility.secondaryValue == retainedValue)
                #expect(
                    accessibility.focusedWindowChildren.contains {
                        CFEqual($0, retainedComposer)
                    }
                )
            }
            let service = FocusedTextPasteService(
                accessibility: accessibility,
                pasteboard: pasteboard,
                postCommandV: { _ in
                    synthesizedEvents.append("command-v")
                    return true
                },
                postSpace: { _ in
                    synthesizedEvents.append("space")
                    return true
                },
                postDeleteBackward: { _ in
                    synthesizedEvents.append("delete")
                    if retainedValue == chromiumNormalizedContent {
                        accessibility.secondaryValue = requestedContent
                    }
                    return true
                },
                openURL: { url, _ in
                    openedURLs.append(url)
                    return true
                },
                validateOpenCodeApplication: { _ in true },
                openCodeRouteTimeoutMilliseconds: 1_000,
                openCodeRouteGraceMilliseconds: 0,
                openCodeFocusSettleMilliseconds: 0,
                openCodeRoutePollMilliseconds: 1
            )

            let outcome = try await service.deliver(
                requestedContent,
                to: service.captureTarget(),
                openCodeProjectDirectory: projectDirectory
            )

            if retainedValue == requestedContent {
                #expect(outcome == .alreadyPresentInVerifiedOpenCodeComposer)
            } else {
                #expect(
                    outcome == .notPasted(
                        "OpenCode retained the requested context with a "
                            + "leftover one-space sync marker before its final "
                            + "line break. DaemonState did not modify the draft "
                            + "or request a new session. Review or clear the "
                            + "draft before trying again. The context was copied."
                    )
                )
            }
            #expect(openedURLs.isEmpty)
            #expect(accessibility.performedActions.isEmpty)
            #expect(accessibility.performedAttributeMutations.isEmpty)
            #expect(accessibility.insertedValues.isEmpty)
            #expect(synthesizedEvents.isEmpty)
            #expect(accessibility.secondaryValue == retainedValue)
            #expect(
                accessibility.focusedWindowChildren.contains {
                    CFEqual($0, retainedComposer)
                }
            )
            #expect(pasteboard.string(forType: .string) == requestedContent)
        }
    }

    @Test
    @MainActor
    func floatingOpenCodeRetainedComposerSettleBaselineSurvivesFasterPolling() async throws {
        let requestedContent = "Stable routed Daemonstate context\n"
        let scenarios = [
            (retainedValue: requestedContent, isEquivalent: true),
            (
                retainedValue: "Different stable unsent OpenCode draft",
                isEquivalent: false
            ),
        ]

        for scenario in scenarios {
            let accessibility = FakeAccessibilityElementClient()
            accessibility.bundleIdentifier = "ai.opencode.desktop"
            accessibility.role = kAXGroupRole as String
            accessibility.secondaryRole = kAXTextAreaRole as String
            accessibility.secondaryDescriptionText = "Ask anything..."
            accessibility.secondaryValue = scenario.retainedValue
            accessibility.settableAttributes = [
                kAXFocusedAttribute as String,
                kAXSelectedTextAttribute as String,
                kAXSelectedTextRangeAttribute as String,
                kAXValueAttribute as String,
            ]
            let projectDirectory = FileManager.default.currentDirectoryPath
            accessibility.exposeOpenCodeLocalProjectWindow(
                children: [accessibility.secondaryElement],
                projectDirectory: projectDirectory
            )
            let pasteboard = FakeTextPasteboard()
            var openedURLCount = 0
            let service = FocusedTextPasteService(
                accessibility: accessibility,
                pasteboard: pasteboard,
                postCommandV: { _ in false },
                postSpace: { _ in false },
                postDeleteBackward: { _ in false },
                openURL: { _, _ in
                    openedURLCount += 1
                    return true
                },
                validateOpenCodeApplication: { _ in true },
                openCodeRouteTimeoutMilliseconds: 100,
                openCodeRouteGraceMilliseconds: 0,
                openCodeFocusSettleMilliseconds: 20,
                openCodeRoutePollMilliseconds: 1
            )

            let clock = ContinuousClock()
            let startedAt = clock.now
            let outcome = try await service.deliver(
                requestedContent,
                to: service.captureTarget(),
                openCodeProjectDirectory: projectDirectory
            )
            let elapsed = startedAt.duration(to: clock.now)

            if scenario.isEquivalent {
                #expect(outcome == .alreadyPresentInVerifiedOpenCodeComposer)
            } else {
                guard case let .notPasted(message) = outcome else {
                    Issue.record("A stable different draft must remain copy-only")
                    continue
                }
                #expect(
                    message.localizedCaseInsensitiveContains(
                        "different nonempty draft"
                    )
                )
                #expect(!message.localizedCaseInsensitiveContains("did not expose"))
            }
            #expect(elapsed >= .milliseconds(20))
            // The route and post-New-session inspection are separate bounded
            // 100 ms phases. Leave scheduler headroom for the serialized
            // MainActor suite while still proving the settle baseline cannot
            // run indefinitely.
            #expect(elapsed < .milliseconds(250))
            if scenario.isEquivalent {
                #expect(openedURLCount == 0)
                #expect(accessibility.performedActions.isEmpty)
            } else {
                #expect(openedURLCount == 1)
                #expect(
                    accessibility.performedActions.map { $0.action }
                        == [kAXPressAction as String]
                )
            }
            #expect(accessibility.performedAttributeMutations.isEmpty)
            #expect(accessibility.insertedValues.isEmpty)
            #expect(accessibility.secondaryValue == scenario.retainedValue)
            #expect(pasteboard.string(forType: .string) == requestedContent)
        }
    }

    @Test
    @MainActor
    func floatingOpenCodeLocalModeReportsRetainedDifferentDraftWithoutOverwriting() async throws {
        let requestedContent = realisticRetainedOpenCodeContext(
            utf16Length: 25_730,
            heading: "# Fresh Daemonstate workspace context"
        )
        let retainedDraft = "Keep this unrelated unsent OpenCode draft"
        let accessibility = FakeAccessibilityElementClient()
        accessibility.bundleIdentifier = "ai.opencode.desktop"
        accessibility.role = kAXGroupRole as String
        accessibility.secondaryRole = kAXTextAreaRole as String
        accessibility.secondaryDescriptionText =
            "Ask anything... \"How do environment variables work here?\""
        accessibility.secondaryValue = retainedDraft
        accessibility.settableAttributes = [
            kAXFocusedAttribute as String,
            kAXSelectedTextAttribute as String,
            kAXSelectedTextRangeAttribute as String,
            kAXValueAttribute as String,
        ]
        let projectDirectory = FileManager.default.currentDirectoryPath
        let canonicalProjectDirectory = URL(
            fileURLWithPath: projectDirectory,
            isDirectory: true
        ).standardizedFileURL.resolvingSymlinksInPath().path
        let home = FileManager.default.homeDirectoryForCurrentUser.path
        let projectDisplay = canonicalProjectDirectory.hasPrefix(home + "/")
            ? "~" + canonicalProjectDirectory.dropFirst(home.count)
            : canonicalProjectDirectory
        accessibility.exposeOpenCodeLocalProjectWindow(
            children: [accessibility.secondaryElement],
            projectDirectory: canonicalProjectDirectory,
            projectDisplay: String(projectDisplay)
        )
        let retainedComposer = accessibility.secondaryElement
        let pasteboard = FakeTextPasteboard()
        var openedURLs: [URL] = []
        var synthesizedEvents: [String] = []
        accessibility.performActionCallback = { action, element, result in
            #expect(action == kAXPressAction as String)
            #expect(CFEqual(element, accessibility.localNewSessionButtonElement))
            #expect(result == .success)
            // OpenCode 1.15.4 keeps the same renderer route, AX node, and draft
            // after both the deep link and local New-session press.
            #expect(accessibility.secondaryValue == retainedDraft)
            #expect(
                accessibility.focusedWindowChildren.contains {
                    CFEqual($0, retainedComposer)
                }
            )
        }
        let service = FocusedTextPasteService(
            accessibility: accessibility,
            pasteboard: pasteboard,
            postCommandV: { _ in
                synthesizedEvents.append("command-v")
                return true
            },
            postSpace: { _ in
                synthesizedEvents.append("space")
                return true
            },
            postDeleteBackward: { _ in
                synthesizedEvents.append("delete")
                return true
            },
            openURL: { url, bundlePath in
                #expect(bundlePath == "/Applications/OpenCode.app")
                openedURLs.append(url)
                #expect(accessibility.secondaryValue == retainedDraft)
                #expect(
                    accessibility.focusedWindowChildren.contains {
                        CFEqual($0, retainedComposer)
                    }
                )
                return true
            },
            validateOpenCodeApplication: { _ in true },
            openCodeRouteTimeoutMilliseconds: 1_000,
            openCodeRouteGraceMilliseconds: 0,
            openCodeFocusSettleMilliseconds: 0,
            openCodeRoutePollMilliseconds: 1
        )

        let clock = ContinuousClock()
        let startedAt = clock.now
        let outcome = try await service.deliver(
            requestedContent,
            to: service.captureTarget(),
            openCodeProjectDirectory: projectDirectory
        )
        let elapsed = startedAt.duration(to: clock.now)

        guard case let .notPasted(message) = outcome else {
            Issue.record("Expected the retained different draft to stay copy-only")
            return
        }
        #expect(message.localizedCaseInsensitiveContains("did not overwrite"))
        #expect(!message.localizedCaseInsensitiveContains("did not expose"))
        #expect(message.localizedCaseInsensitiveContains("context was copied"))
        #expect(elapsed < .milliseconds(500))
        #expect(openedURLs.count == 1)
        #expect(
            accessibility.performedActions.map { $0.action }
                == [kAXPressAction as String]
        )
        #expect(
            accessibility.performedActions.allSatisfy {
                CFEqual($0.element, accessibility.localNewSessionButtonElement)
            }
        )
        #expect(accessibility.secondaryValue == retainedDraft)
        #expect(accessibility.insertedValues.isEmpty)
        #expect(synthesizedEvents.isEmpty)
        #expect(pasteboard.string(forType: .string) == requestedContent)
    }

    @Test
    @MainActor
    func floatingOpenCodeLocalModeDoesNotTreatNearMatchOrExtraNewlinesAsAlreadyPresent() async throws {
        let requestedContent = realisticRetainedOpenCodeContext(
            utf16Length: 25_730,
            heading: "# Requested Daemonstate workspace context"
        )
        let retainedNearMatches = [
            requestedContent + "\n",
            requestedContent + " ",
            String(requestedContent.dropLast()) + "\r\n",
            String(requestedContent.dropLast()) + "  \n",
        ]

        for retainedDraft in retainedNearMatches {
            let accessibility = FakeAccessibilityElementClient()
            accessibility.bundleIdentifier = "ai.opencode.desktop"
            accessibility.role = kAXGroupRole as String
            accessibility.secondaryRole = kAXTextAreaRole as String
            accessibility.secondaryDescriptionText =
                "Ask anything... \"How do environment variables work here?\""
            accessibility.secondaryValue = retainedDraft
            accessibility.settableAttributes = [
                kAXFocusedAttribute as String,
                kAXSelectedTextAttribute as String,
                kAXSelectedTextRangeAttribute as String,
                kAXValueAttribute as String,
            ]
            let projectDirectory = FileManager.default.currentDirectoryPath
            let canonicalProjectDirectory = URL(
                fileURLWithPath: projectDirectory,
                isDirectory: true
            ).standardizedFileURL.resolvingSymlinksInPath().path
            let home = FileManager.default.homeDirectoryForCurrentUser.path
            let projectDisplay = canonicalProjectDirectory.hasPrefix(home + "/")
                ? "~" + canonicalProjectDirectory.dropFirst(home.count)
                : canonicalProjectDirectory
            accessibility.exposeOpenCodeLocalProjectWindow(
                children: [accessibility.secondaryElement],
                projectDirectory: canonicalProjectDirectory,
                projectDisplay: String(projectDisplay)
            )
            let retainedComposer = accessibility.secondaryElement
            let pasteboard = FakeTextPasteboard()
            var openedURLCount = 0
            var synthesizedEvents: [String] = []
            accessibility.performActionCallback = { _, _, _ in
                #expect(accessibility.secondaryValue == retainedDraft)
                #expect(
                    accessibility.focusedWindowChildren.contains {
                        CFEqual($0, retainedComposer)
                    }
                )
            }
            let service = FocusedTextPasteService(
                accessibility: accessibility,
                pasteboard: pasteboard,
                postCommandV: { _ in
                    synthesizedEvents.append("command-v")
                    return true
                },
                postSpace: { _ in
                    synthesizedEvents.append("space")
                    return true
                },
                postDeleteBackward: { _ in
                    synthesizedEvents.append("delete")
                    return true
                },
                openURL: { _, _ in
                    openedURLCount += 1
                    #expect(accessibility.secondaryValue == retainedDraft)
                    return true
                },
                validateOpenCodeApplication: { _ in true },
                openCodeRouteTimeoutMilliseconds: 1_000,
                openCodeRouteGraceMilliseconds: 0,
                openCodeFocusSettleMilliseconds: 0,
                openCodeRoutePollMilliseconds: 1
            )

            let outcome = try await service.deliver(
                requestedContent,
                to: service.captureTarget(),
                openCodeProjectDirectory: projectDirectory
            )

            guard case let .notPasted(message) = outcome else {
                Issue.record("A near-match draft was incorrectly treated as already present")
                continue
            }
            #expect(
                message.localizedCaseInsensitiveContains("did not overwrite")
            )
            #expect(
                outcome != .alreadyPresentInVerifiedOpenCodeComposer
            )
            #expect(openedURLCount == 1)
            #expect(
                accessibility.performedActions.map { $0.action }
                    == [kAXPressAction as String]
            )
            #expect(accessibility.secondaryValue == retainedDraft)
            #expect(accessibility.insertedValues.isEmpty)
            #expect(synthesizedEvents.isEmpty)
            #expect(pasteboard.string(forType: .string) == requestedContent)
        }
    }

    @Test
    @MainActor
    func floatingOpenCodeEquivalentComposerPlusEmptyComposerIsNotIdempotent() async throws {
        let requestedContent = "Exact retained Daemonstate context\n"
        let accessibility = FakeAccessibilityElementClient()
        accessibility.bundleIdentifier = "ai.opencode.desktop"
        accessibility.role = kAXGroupRole as String
        accessibility.secondaryRole = kAXTextAreaRole as String
        accessibility.secondaryDescriptionText = "Ask anything..."
        accessibility.secondaryValue = requestedContent
        accessibility.tertiaryRole = kAXTextAreaRole as String
        accessibility.tertiaryDescriptionText = "Ask anything..."
        accessibility.tertiaryValue = "\n"
        accessibility.settableAttributes = [
            kAXFocusedAttribute as String,
            kAXSelectedTextAttribute as String,
            kAXSelectedTextRangeAttribute as String,
            kAXValueAttribute as String,
        ]
        let projectDirectory = FileManager.default.currentDirectoryPath
        accessibility.exposeOpenCodeLocalProjectWindow(
            children: [
                accessibility.secondaryElement,
                accessibility.tertiaryElement,
            ],
            projectDirectory: projectDirectory
        )
        let pasteboard = FakeTextPasteboard()
        var openedURLCount = 0
        var synthesizedEvents: [String] = []
        let service = FocusedTextPasteService(
            accessibility: accessibility,
            pasteboard: pasteboard,
            postCommandV: { _ in
                synthesizedEvents.append("command-v")
                return true
            },
            postSpace: { _ in
                synthesizedEvents.append("space")
                return true
            },
            postDeleteBackward: { _ in
                synthesizedEvents.append("delete")
                return true
            },
            openURL: { _, _ in
                openedURLCount += 1
                return true
            },
            validateOpenCodeApplication: { _ in true },
            openCodeRouteTimeoutMilliseconds: 25,
            openCodeRouteGraceMilliseconds: 0,
            openCodeFocusSettleMilliseconds: 0,
            openCodeRoutePollMilliseconds: 1
        )

        let outcome = try await service.deliver(
            requestedContent,
            to: service.captureTarget(),
            openCodeProjectDirectory: projectDirectory
        )

        #expect(outcome != .alreadyPresentInVerifiedOpenCodeComposer)
        guard case .notPasted = outcome else {
            Issue.record("Two normal composers must fail closed")
            return
        }
        #expect(openedURLCount == 1)
        #expect(
            accessibility.performedActions.map { $0.action }
                == [kAXPressAction as String]
        )
        #expect(accessibility.secondaryValue == requestedContent)
        #expect(accessibility.tertiaryValue == "\n")
        #expect(accessibility.performedAttributeMutations.isEmpty)
        #expect(accessibility.insertedValues.isEmpty)
        #expect(synthesizedEvents.isEmpty)
        #expect(pasteboard.string(forType: .string) == requestedContent)
    }

    @Test
    @MainActor
    func floatingOpenCodeEquivalentComposerPlusDifferentDraftIsNotIdempotent() async throws {
        let requestedContent = "Exact retained Daemonstate context\n"
        let differentDraft = "Unrelated user draft that must remain untouched"
        let accessibility = FakeAccessibilityElementClient()
        accessibility.bundleIdentifier = "ai.opencode.desktop"
        accessibility.role = kAXGroupRole as String
        accessibility.secondaryRole = kAXTextAreaRole as String
        accessibility.secondaryDescriptionText = "Ask anything..."
        accessibility.secondaryValue = requestedContent
        accessibility.tertiaryRole = kAXTextAreaRole as String
        accessibility.tertiaryDescriptionText = "Ask anything..."
        accessibility.tertiaryValue = differentDraft
        accessibility.settableAttributes = [
            kAXFocusedAttribute as String,
            kAXSelectedTextAttribute as String,
            kAXSelectedTextRangeAttribute as String,
            kAXValueAttribute as String,
        ]
        let projectDirectory = FileManager.default.currentDirectoryPath
        accessibility.exposeOpenCodeLocalProjectWindow(
            children: [
                accessibility.secondaryElement,
                accessibility.tertiaryElement,
            ],
            projectDirectory: projectDirectory
        )
        let pasteboard = FakeTextPasteboard()
        var openedURLCount = 0
        var synthesizedEvents: [String] = []
        let service = FocusedTextPasteService(
            accessibility: accessibility,
            pasteboard: pasteboard,
            postCommandV: { _ in
                synthesizedEvents.append("command-v")
                return true
            },
            postSpace: { _ in
                synthesizedEvents.append("space")
                return true
            },
            postDeleteBackward: { _ in
                synthesizedEvents.append("delete")
                return true
            },
            openURL: { _, _ in
                openedURLCount += 1
                return true
            },
            validateOpenCodeApplication: { _ in true },
            openCodeRouteTimeoutMilliseconds: 25,
            openCodeRouteGraceMilliseconds: 0,
            openCodeFocusSettleMilliseconds: 0,
            openCodeRoutePollMilliseconds: 1
        )

        let outcome = try await service.deliver(
            requestedContent,
            to: service.captureTarget(),
            openCodeProjectDirectory: projectDirectory
        )

        #expect(outcome != .alreadyPresentInVerifiedOpenCodeComposer)
        guard case .notPasted = outcome else {
            Issue.record("An exact draft plus a different draft must fail closed")
            return
        }
        #expect(openedURLCount == 1)
        #expect(
            accessibility.performedActions.map { $0.action }
                == [kAXPressAction as String]
        )
        #expect(accessibility.secondaryValue == requestedContent)
        #expect(accessibility.tertiaryValue == differentDraft)
        #expect(accessibility.performedAttributeMutations.isEmpty)
        #expect(accessibility.insertedValues.isEmpty)
        #expect(synthesizedEvents.isEmpty)
        #expect(pasteboard.string(forType: .string) == requestedContent)
    }

    @Test
    @MainActor
    func floatingOpenCodeWrongLocalProjectCannotFastPathEquivalentComposer() async throws {
        let requestedContent = "Requested-project retained context\n"
        let accessibility = FakeAccessibilityElementClient()
        accessibility.bundleIdentifier = "ai.opencode.desktop"
        accessibility.role = kAXGroupRole as String
        accessibility.secondaryRole = kAXTextAreaRole as String
        accessibility.secondaryDescriptionText = "Ask anything..."
        accessibility.secondaryValue = requestedContent
        accessibility.settableAttributes = [
            kAXFocusedAttribute as String,
            kAXSelectedTextAttribute as String,
            kAXSelectedTextRangeAttribute as String,
            kAXValueAttribute as String,
        ]
        let requestedProject = FileManager.default.currentDirectoryPath
        let wrongProject = URL(
            fileURLWithPath: requestedProject,
            isDirectory: true
        ).deletingLastPathComponent().path
        accessibility.exposeOpenCodeLocalProjectWindow(
            children: [accessibility.secondaryElement],
            projectDirectory: wrongProject
        )
        let pasteboard = FakeTextPasteboard()
        var openedURLCount = 0
        let service = FocusedTextPasteService(
            accessibility: accessibility,
            pasteboard: pasteboard,
            postCommandV: { _ in false },
            postSpace: { _ in false },
            postDeleteBackward: { _ in false },
            openURL: { _, _ in
                openedURLCount += 1
                // The fake deliberately leaves the wrong sidebar/project in
                // place, modeling a deep link that did not complete its route.
                return true
            },
            validateOpenCodeApplication: { _ in true },
            openCodeRouteTimeoutMilliseconds: 25,
            openCodeRouteGraceMilliseconds: 0,
            openCodeFocusSettleMilliseconds: 0,
            openCodeRoutePollMilliseconds: 1
        )

        let outcome = try await service.deliver(
            requestedContent,
            to: service.captureTarget(),
            openCodeProjectDirectory: requestedProject
        )

        #expect(outcome != .alreadyPresentInVerifiedOpenCodeComposer)
        guard case .notPasted = outcome else {
            Issue.record("Wrong-project evidence must remain copy-only")
            return
        }
        #expect(openedURLCount == 1)
        #expect(accessibility.performedActions.isEmpty)
        #expect(accessibility.secondaryValue == requestedContent)
        #expect(accessibility.performedAttributeMutations.isEmpty)
        #expect(accessibility.insertedValues.isEmpty)
        #expect(pasteboard.string(forType: .string) == requestedContent)
    }

    @Test
    @MainActor
    func floatingOpenCodeRequiresDistinctAXWindowFocusedRoot() {
        let projectDirectory = FileManager.default.currentDirectoryPath

        let validAccessibility = FakeAccessibilityElementClient()
        validAccessibility.bundleIdentifier = "ai.opencode.desktop"
        validAccessibility.role = kAXGroupRole as String
        validAccessibility.secondaryRole = kAXTextAreaRole as String
        validAccessibility.secondaryDescriptionText = "Ask anything..."
        validAccessibility.secondaryValue = "Retained context"
        validAccessibility.settableAttributes = [kAXValueAttribute as String]
        validAccessibility.exposeOpenCodeLocalProjectWindow(
            children: [validAccessibility.secondaryElement],
            projectDirectory: projectDirectory
        )
        let validService = FocusedTextPasteService(
            accessibility: validAccessibility,
            pasteboard: FakeTextPasteboard(),
            postCommandV: { _ in false }
        )
        guard case .openCodeNewComposer = validService.captureTarget() else {
            Issue.record("A distinct AXWindow focused root should remain routable")
            return
        }

        let applicationRootAccessibility = FakeAccessibilityElementClient()
        applicationRootAccessibility.bundleIdentifier = "ai.opencode.desktop"
        applicationRootAccessibility.role = kAXGroupRole as String
        applicationRootAccessibility.secondaryRole = kAXTextAreaRole as String
        applicationRootAccessibility.secondaryDescriptionText = "Ask anything..."
        applicationRootAccessibility.secondaryValue = "Retained context"
        applicationRootAccessibility.settableAttributes = [
            kAXValueAttribute as String,
        ]
        applicationRootAccessibility.exposeOpenCodeLocalProjectWindow(
            children: [applicationRootAccessibility.secondaryElement],
            projectDirectory: projectDirectory
        )
        applicationRootAccessibility.exposeApplicationElementAsFocusedWindow()
        let applicationRootService = FocusedTextPasteService(
            accessibility: applicationRootAccessibility,
            pasteboard: FakeTextPasteboard(),
            postCommandV: { _ in false }
        )
        guard case let .copyOnly(applicationRootMessage) =
            applicationRootService.captureTarget()
        else {
            Issue.record("AXApplication must not be accepted as AXFocusedWindow")
            return
        }
        #expect(applicationRootMessage.localizedCaseInsensitiveContains("window"))

        let groupRootAccessibility = FakeAccessibilityElementClient()
        groupRootAccessibility.bundleIdentifier = "ai.opencode.desktop"
        groupRootAccessibility.focusedWindowRole = kAXGroupRole as String
        groupRootAccessibility.role = kAXGroupRole as String
        groupRootAccessibility.secondaryRole = kAXTextAreaRole as String
        groupRootAccessibility.secondaryDescriptionText = "Ask anything..."
        groupRootAccessibility.secondaryValue = "Retained context"
        groupRootAccessibility.settableAttributes = [kAXValueAttribute as String]
        groupRootAccessibility.exposeOpenCodeLocalProjectWindow(
            children: [groupRootAccessibility.secondaryElement],
            projectDirectory: projectDirectory
        )
        let groupRootService = FocusedTextPasteService(
            accessibility: groupRootAccessibility,
            pasteboard: FakeTextPasteboard(),
            postCommandV: { _ in false }
        )
        guard case let .copyOnly(groupRootMessage) = groupRootService.captureTarget()
        else {
            Issue.record("A non-AXWindow focused root must fail closed")
            return
        }
        #expect(groupRootMessage.localizedCaseInsensitiveContains("window"))
    }

    @Test
    @MainActor
    func floatingOpenCodeEquivalentComposerChangingDuringReattestationIsNotIdempotent() async throws {
        let requestedContent = "Stable retained context candidate\n"
        let changedDraft = "Composer changed during final re-attestation"
        let accessibility = FakeAccessibilityElementClient()
        accessibility.bundleIdentifier = "ai.opencode.desktop"
        accessibility.role = kAXGroupRole as String
        accessibility.secondaryRole = kAXTextAreaRole as String
        accessibility.secondaryDescriptionText = "Ask anything..."
        accessibility.secondaryValue = requestedContent
        accessibility.settableAttributes = [
            kAXFocusedAttribute as String,
            kAXSelectedTextAttribute as String,
            kAXSelectedTextRangeAttribute as String,
            kAXValueAttribute as String,
        ]
        let projectDirectory = FileManager.default.currentDirectoryPath
        accessibility.exposeOpenCodeLocalProjectWindow(
            children: [accessibility.secondaryElement],
            projectDirectory: projectDirectory
        )
        let pasteboard = FakeTextPasteboard()
        var openedURLCount = 0
        var synthesizedEvents: [String] = []
        let service = FocusedTextPasteService(
            accessibility: accessibility,
            pasteboard: pasteboard,
            postCommandV: { _ in
                synthesizedEvents.append("command-v")
                return true
            },
            postSpace: { _ in
                synthesizedEvents.append("space")
                return true
            },
            postDeleteBackward: { _ in
                synthesizedEvents.append("delete")
                return true
            },
            openURL: { _, _ in
                openedURLCount += 1
                return true
            },
            validateOpenCodeApplication: { _ in true },
            openCodeRouteTimeoutMilliseconds: 50,
            openCodeRouteGraceMilliseconds: 0,
            openCodeFocusSettleMilliseconds: 0,
            openCodeRoutePollMilliseconds: 1
        )

        let capture = service.captureTarget()
        accessibility.resetSecondaryValueReadObservation()
        accessibility.secondaryValueReadCallback = { readCount, observed in
            if readCount == 1 {
                #expect(observed == requestedContent)
                accessibility.secondaryValue = changedDraft
            }
        }
        let outcome = try await service.deliver(
            requestedContent,
            to: capture,
            openCodeProjectDirectory: projectDirectory
        )

        #expect(outcome != .alreadyPresentInVerifiedOpenCodeComposer)
        guard case .notPasted = outcome else {
            Issue.record("A composer that changes during proof must fail closed")
            return
        }
        #expect(openedURLCount == 1)
        #expect(
            accessibility.performedActions.map { $0.action }
                == [kAXPressAction as String]
        )
        #expect(accessibility.secondaryValueReadCount >= 2)
        #expect(accessibility.secondaryValue == changedDraft)
        #expect(accessibility.performedAttributeMutations.isEmpty)
        #expect(accessibility.insertedValues.isEmpty)
        #expect(synthesizedEvents.isEmpty)
        #expect(pasteboard.string(forType: .string) == requestedContent)
    }

    @Test
    @MainActor
    func floatingOpenCodeLocalModeRejectsOtherWhitespaceAsNonempty() async throws {
        for composerValue in [" ", "\n\n", "\r\n"] {
            let accessibility = FakeAccessibilityElementClient()
            accessibility.bundleIdentifier = "ai.opencode.desktop"
            accessibility.role = kAXGroupRole as String
            accessibility.secondaryRole = kAXTextAreaRole as String
            accessibility.secondaryDescriptionText = "Ask anything..."
            accessibility.secondaryValue = composerValue
            accessibility.settableAttributes = [
                kAXFocusedAttribute as String,
                kAXSelectedTextRangeAttribute as String,
                kAXValueAttribute as String,
            ]
            let projectDirectory = FileManager.default.temporaryDirectory.path
            accessibility.exposeOpenCodeLocalProjectWindow(
                children: [accessibility.secondaryElement],
                projectDirectory: projectDirectory
            )
            let pasteboard = FakeTextPasteboard()
            var synthesizedEvents: [String] = []
            let service = FocusedTextPasteService(
                accessibility: accessibility,
                pasteboard: pasteboard,
                postCommandV: { _ in
                    synthesizedEvents.append("command-v")
                    return true
                },
                postSpace: { _ in
                    synthesizedEvents.append("space")
                    return true
                },
                postDeleteBackward: { _ in
                    synthesizedEvents.append("delete")
                    return true
                },
                openURL: { _, _ in true },
                validateOpenCodeApplication: { _ in true },
                openCodeRouteTimeoutMilliseconds: 1_000,
                openCodeRouteGraceMilliseconds: 0,
                openCodeFocusSettleMilliseconds: 0,
                openCodeRoutePollMilliseconds: 1
            )

            let outcome = try await service.deliver(
                "Never overwrite nonempty whitespace",
                to: service.captureTarget(),
                openCodeProjectDirectory: projectDirectory
            )

            #expect(
                outcome == .notPasted(
                    "OpenCode exposed a different nonempty draft instead of a "
                        + "fresh composer for the requested project, so DaemonState "
                        + "did not overwrite it. Send or clear that draft, then try "
                        + "the floating action again. "
                        + "The context was copied."
                )
            )
            #expect(accessibility.secondaryValue == composerValue)
            #expect(synthesizedEvents.isEmpty)
            #expect(
                accessibility.performedActions.map { $0.action }
                    == [kAXPressAction as String]
            )
            #expect(
                pasteboard.string(forType: .string)
                    == "Never overwrite nonempty whitespace"
            )
        }
    }

    @Test
    @MainActor
    func floatingOpenCodeLocalModePressFailureStaysCopyOnly() async throws {
        let accessibility = FakeAccessibilityElementClient()
        accessibility.bundleIdentifier = "ai.opencode.desktop"
        accessibility.role = kAXGroupRole as String
        accessibility.settableAttributes = [
            kAXFocusedAttribute as String,
            kAXSelectedTextRangeAttribute as String,
            kAXValueAttribute as String,
        ]
        let projectDirectory = FileManager.default.temporaryDirectory.path
        accessibility.secondaryRole = kAXTextAreaRole as String
        accessibility.secondaryDescriptionText = "Ask anything..."
        accessibility.secondaryValue = "\n"
        accessibility.exposeOpenCodeLocalProjectWindow(
            children: [accessibility.secondaryElement],
            projectDirectory: projectDirectory
        )
        accessibility.performActionResults = [.cannotComplete]
        let pasteboard = FakeTextPasteboard()
        var openedURLCount = 0
        var synthesizedEvents: [String] = []
        let service = FocusedTextPasteService(
            accessibility: accessibility,
            pasteboard: pasteboard,
            postCommandV: { _ in
                synthesizedEvents.append("command-v")
                return true
            },
            postSpace: { _ in
                synthesizedEvents.append("space")
                accessibility.secondaryValue = "Press failure must copy "
                return true
            },
            postDeleteBackward: { _ in
                synthesizedEvents.append("delete")
                accessibility.secondaryValue = "Press failure must copy"
                return true
            },
            openURL: { _, _ in
                openedURLCount += 1
                #expect(accessibility.secondaryValue == "\n")
                return true
            },
            validateOpenCodeApplication: { _ in true },
            openCodeRouteTimeoutMilliseconds: 5,
            openCodeRouteGraceMilliseconds: 0,
            openCodeFocusSettleMilliseconds: 0,
            openCodeRoutePollMilliseconds: 1
        )

        let outcome = try await service.deliver(
            "Press failure must copy",
            to: service.captureTarget(),
            openCodeProjectDirectory: projectDirectory
        )

        #expect(
            outcome == .notPasted(
                "OpenCode's verified New session control could not be "
                    + "activated. The context was copied."
            )
        )
        #expect(openedURLCount == 1)
        #expect(accessibility.secondaryValue == "\n")
        #expect(synthesizedEvents.isEmpty)
        #expect(
            accessibility.performedActions.map { $0.action }
                == [kAXPressAction as String]
        )
        #expect(
            pasteboard.string(forType: .string) == "Press failure must copy"
        )
    }

    @Test
    @MainActor
    func floatingOpenCodeLocalModeRejectsUnchangedStaleActiveSessionAfterPress() async throws {
        let accessibility = FakeAccessibilityElementClient()
        accessibility.bundleIdentifier = "ai.opencode.desktop"
        accessibility.role = kAXGroupRole as String
        accessibility.settableAttributes = [
            kAXFocusedAttribute as String,
            kAXSelectedTextRangeAttribute as String,
            kAXValueAttribute as String,
        ]
        let projectDirectory = FileManager.default.temporaryDirectory.path
        accessibility.secondaryRole = kAXTextAreaRole as String
        accessibility.secondaryDescriptionText = "Ask anything..."
        accessibility.secondaryValue = "\n"
        accessibility.exposeOpenCodeLocalProjectWindow(
            children: [accessibility.secondaryElement],
            projectDirectory: projectDirectory,
            activeSessionTitle: "Stale active session"
        )
        accessibility.performActionCallback = { action, element, result in
            #expect(action == kAXPressAction as String)
            #expect(CFEqual(element, accessibility.localNewSessionButtonElement))
            #expect(result == .success)
            // A successful AX action without any AX-tree transition is not
            // proof that OpenCode created a fresh session or composer.
        }
        let pasteboard = FakeTextPasteboard()
        var synthesizedEvents: [String] = []
        let service = FocusedTextPasteService(
            accessibility: accessibility,
            pasteboard: pasteboard,
            postCommandV: { _ in
                synthesizedEvents.append("command-v")
                return true
            },
            postSpace: { _ in
                synthesizedEvents.append("space")
                accessibility.secondaryValue = "Reject a stale active session "
                return true
            },
            postDeleteBackward: { _ in
                synthesizedEvents.append("delete")
                accessibility.secondaryValue = "Reject a stale active session"
                return true
            },
            openURL: { _, _ in
                #expect(accessibility.secondaryValue == "\n")
                return true
            },
            validateOpenCodeApplication: { _ in true },
            openCodeRouteTimeoutMilliseconds: 5,
            openCodeRouteGraceMilliseconds: 0,
            openCodeFocusSettleMilliseconds: 0,
            openCodeRoutePollMilliseconds: 1
        )

        let outcome = try await service.deliver(
            "Reject a stale active session",
            to: service.captureTarget(),
            openCodeProjectDirectory: projectDirectory
        )

        #expect(
            outcome == .notPasted(
                "OpenCode did not expose the requested active project and "
                    + "exactly one verified empty chat composer in the captured "
                    + "window; try the floating action again. "
                    + "The context was copied."
            )
        )
        #expect(accessibility.secondaryValue == "\n")
        #expect(synthesizedEvents.isEmpty)
        #expect(
            accessibility.performedActions.map { $0.action }
                == [kAXPressAction as String]
        )
        #expect(
            pasteboard.string(forType: .string)
                == "Reject a stale active session"
        )
    }

    @Test
    @MainActor
    func floatingOpenCodeRetryRecognizesExactContextInRequestedActiveSession() async throws {
        let requestedContent = "# Already delivered OpenCode context\n"
        let accessibility = FakeAccessibilityElementClient()
        accessibility.bundleIdentifier = "ai.opencode.desktop"
        accessibility.role = kAXGroupRole as String
        accessibility.secondaryRole = kAXTextAreaRole as String
        accessibility.secondaryDescriptionText = "Ask anything..."
        accessibility.secondaryValue = requestedContent
        accessibility.settableAttributes = [
            kAXFocusedAttribute as String,
            kAXSelectedTextAttribute as String,
            kAXSelectedTextRangeAttribute as String,
            kAXValueAttribute as String,
        ]
        let projectDirectory = FileManager.default.temporaryDirectory.path
        accessibility.exposeOpenCodeLocalProjectWindow(
            children: [accessibility.secondaryElement],
            projectDirectory: projectDirectory,
            activeSessionTitle: "Retained delivered context"
        )
        let pasteboard = FakeTextPasteboard()
        var openedURLCount = 0
        var synthesizedEvents: [String] = []
        let service = FocusedTextPasteService(
            accessibility: accessibility,
            pasteboard: pasteboard,
            postCommandV: { _ in
                synthesizedEvents.append("command-v")
                return true
            },
            postSpace: { _ in
                synthesizedEvents.append("space")
                return true
            },
            postDeleteBackward: { _ in
                synthesizedEvents.append("delete")
                return true
            },
            openURL: { _, _ in
                openedURLCount += 1
                return true
            },
            validateOpenCodeApplication: { _ in true },
            openCodeRouteTimeoutMilliseconds: 1_000,
            openCodeRouteGraceMilliseconds: 0,
            openCodeFocusSettleMilliseconds: 0,
            openCodeRoutePollMilliseconds: 1
        )

        let outcome = try await service.deliver(
            requestedContent,
            to: service.captureTarget(),
            openCodeProjectDirectory: projectDirectory
        )

        #expect(outcome == .alreadyPresentInVerifiedOpenCodeComposer)
        #expect(openedURLCount == 0)
        #expect(accessibility.performedActions.isEmpty)
        #expect(accessibility.performedAttributeMutations.isEmpty)
        #expect(accessibility.insertedValues.isEmpty)
        #expect(synthesizedEvents.isEmpty)
        #expect(accessibility.secondaryValue == requestedContent)
        #expect(pasteboard.string(forType: .string) == requestedContent)
    }

    @Test
    @MainActor
    func floatingOpenCodeRetryWarnsAboutResidualWithoutMutatingOrRouting() async throws {
        let requestedContent = "# Already delivered OpenCode context 😀\n"
        let residualValue = String(requestedContent.dropLast()) + " \n"
        let accessibility = FakeAccessibilityElementClient()
        accessibility.bundleIdentifier = "ai.opencode.desktop"
        accessibility.role = kAXGroupRole as String
        accessibility.secondaryRole = kAXTextAreaRole as String
        accessibility.secondaryDescriptionText = "Ask anything..."
        accessibility.secondaryValue = residualValue
        accessibility.settableAttributes = [
            kAXFocusedAttribute as String,
            kAXSelectedTextAttribute as String,
            kAXSelectedTextRangeAttribute as String,
            kAXValueAttribute as String,
        ]
        let projectDirectory = FileManager.default.temporaryDirectory.path
        accessibility.exposeOpenCodeLocalProjectWindow(
            children: [accessibility.secondaryElement],
            projectDirectory: projectDirectory,
            activeSessionTitle: "Retained residual sentinel"
        )
        let pasteboard = FakeTextPasteboard()
        var openedURLCount = 0
        var synthesizedEvents: [String] = []
        let service = FocusedTextPasteService(
            accessibility: accessibility,
            pasteboard: pasteboard,
            postCommandV: { _ in
                synthesizedEvents.append("command-v")
                return true
            },
            postSpace: { _ in
                synthesizedEvents.append("space")
                return true
            },
            postDeleteBackward: { _ in
                synthesizedEvents.append("delete")
                return true
            },
            openURL: { _, _ in
                openedURLCount += 1
                return true
            },
            validateOpenCodeApplication: { _ in true },
            openCodeRouteTimeoutMilliseconds: 1_000,
            openCodeRouteGraceMilliseconds: 0,
            openCodeFocusSettleMilliseconds: 0,
            openCodeRoutePollMilliseconds: 1
        )

        let outcome = try await service.deliver(
            requestedContent,
            to: service.captureTarget(),
            openCodeProjectDirectory: projectDirectory
        )

        #expect(
            outcome == .notPasted(
                "OpenCode retained the requested context with a leftover "
                    + "one-space sync marker before its final line break. "
                    + "DaemonState did not modify the draft or request a new "
                    + "session. Review or clear the draft before trying again. "
                    + "The context was copied."
            )
        )
        #expect(openedURLCount == 0)
        #expect(accessibility.performedActions.isEmpty)
        #expect(accessibility.performedAttributeMutations.isEmpty)
        #expect(accessibility.insertedValues.isEmpty)
        #expect(synthesizedEvents.isEmpty)
        #expect(accessibility.secondaryValue == residualValue)
        #expect(pasteboard.string(forType: .string) == requestedContent)
    }

    @Test
    @MainActor
    func floatingOpenCodeLocalModeRejectsPathShapedProjectNameAndSavedSessionTitle() async throws {
        let accessibility = FakeAccessibilityElementClient()
        accessibility.bundleIdentifier = "ai.opencode.desktop"
        accessibility.role = kAXGroupRole as String
        accessibility.settableAttributes = [
            kAXFocusedAttribute as String,
            kAXSelectedTextRangeAttribute as String,
            kAXValueAttribute as String,
        ]
        let requestedProject = URL(
            fileURLWithPath: FileManager.default.temporaryDirectory.path,
            isDirectory: true
        ).standardizedFileURL.resolvingSymlinksInPath().path
        let activeProject = FileManager.default.homeDirectoryForCurrentUser
            .standardizedFileURL.resolvingSymlinksInPath().path
        accessibility.secondaryRole = kAXTextAreaRole as String
        accessibility.secondaryDescriptionText = "Ask anything..."
        accessibility.secondaryValue = "\n"
        accessibility.exposeOpenCodeLocalProjectWindow(
            children: [accessibility.secondaryElement],
            projectDirectory: activeProject,
            projectName: requestedProject,
            activeSessionTitle: "Project B active session",
            savedSessionTitle: requestedProject
        )
        let pasteboard = FakeTextPasteboard()
        var synthesizedEvents: [String] = []
        let service = FocusedTextPasteService(
            accessibility: accessibility,
            pasteboard: pasteboard,
            postCommandV: { _ in
                synthesizedEvents.append("command-v")
                return true
            },
            postSpace: { _ in
                synthesizedEvents.append("space")
                return true
            },
            postDeleteBackward: { _ in
                synthesizedEvents.append("delete")
                return true
            },
            openURL: { _, _ in true },
            validateOpenCodeApplication: { _ in true },
            openCodeRouteTimeoutMilliseconds: 5,
            openCodeRouteGraceMilliseconds: 0,
            openCodeFocusSettleMilliseconds: 0,
            openCodeRoutePollMilliseconds: 1
        )

        let outcome = try await service.deliver(
            "Never activate project B for a path-shaped decoy",
            to: service.captureTarget(),
            openCodeProjectDirectory: requestedProject
        )

        #expect(
            outcome == .notPasted(
                "OpenCode did not expose the requested active project and "
                    + "exactly one verified empty chat composer in the captured "
                    + "window; try the floating action again. "
                    + "The context was copied."
            )
        )
        #expect(accessibility.localProjectEvidenceValue == activeProject)
        #expect(accessibility.localProjectNameValue == requestedProject)
        #expect(accessibility.savedSessionTitleValue == requestedProject)
        #expect(accessibility.performedActions.isEmpty)
        #expect(accessibility.secondaryValue == "\n")
        #expect(synthesizedEvents.isEmpty)
        #expect(
            pasteboard.string(forType: .string)
                == "Never activate project B for a path-shaped decoy"
        )
    }

    @Test
    @MainActor
    func floatingOpenCodeLocalModeRejectsUnparentedCurrentLinkAfterPress() async throws {
        let accessibility = FakeAccessibilityElementClient()
        accessibility.bundleIdentifier = "ai.opencode.desktop"
        accessibility.role = kAXGroupRole as String
        accessibility.settableAttributes = [
            kAXFocusedAttribute as String,
            kAXSelectedTextRangeAttribute as String,
            kAXValueAttribute as String,
        ]
        let projectDirectory = FileManager.default.temporaryDirectory.path
        accessibility.secondaryRole = kAXTextAreaRole as String
        accessibility.secondaryDescriptionText = "Ask anything..."
        accessibility.secondaryValue = "\n"
        accessibility.exposeOpenCodeLocalProjectWindow(
            children: [accessibility.secondaryElement],
            projectDirectory: projectDirectory,
            includeOrphanCurrentLink: true
        )
        accessibility.performActionCallback = { action, element, result in
            #expect(action == kAXPressAction as String)
            #expect(CFEqual(element, accessibility.localNewSessionButtonElement))
            #expect(result == .success)
            accessibility.tertiaryRole = kAXTextAreaRole as String
            accessibility.tertiaryDescriptionText = "Ask anything..."
            accessibility.tertiaryValue = "\n"
            accessibility.exposeOpenCodeLocalProjectWindow(
                children: [accessibility.tertiaryElement],
                projectDirectory: projectDirectory,
                includeOrphanCurrentLink: true
            )
        }
        let pasteboard = FakeTextPasteboard()
        var synthesizedEvents: [String] = []
        let service = FocusedTextPasteService(
            accessibility: accessibility,
            pasteboard: pasteboard,
            postCommandV: { _ in
                synthesizedEvents.append("command-v")
                return true
            },
            postSpace: { _ in
                synthesizedEvents.append("space")
                accessibility.tertiaryValue = "Reject unreadable link parent "
                return true
            },
            postDeleteBackward: { _ in
                synthesizedEvents.append("delete")
                accessibility.tertiaryValue = "Reject unreadable link parent"
                return true
            },
            openURL: { _, _ in true },
            validateOpenCodeApplication: { _ in true },
            openCodeRouteTimeoutMilliseconds: 50,
            openCodeRouteGraceMilliseconds: 0,
            openCodeFocusSettleMilliseconds: 0,
            openCodeRoutePollMilliseconds: 1
        )

        let outcome = try await service.deliver(
            "Reject unreadable link parent",
            to: service.captureTarget(),
            openCodeProjectDirectory: projectDirectory
        )

        #expect(
            outcome == .notPasted(
                "OpenCode did not expose the requested active project and "
                    + "exactly one verified empty chat composer in the captured "
                    + "window; try the floating action again. "
                    + "The context was copied."
            )
        )
        #expect(accessibility.secondaryValue == "\n")
        #expect(accessibility.tertiaryValue == "\n")
        #expect(synthesizedEvents.isEmpty)
        #expect(
            accessibility.performedActions.map { $0.action }
                == [kAXPressAction as String]
        )
        #expect(
            accessibility.elementAttribute(
                kAXParentAttribute as CFString,
                from: accessibility.orphanCurrentSessionLinkElement
            ) == nil
        )
        #expect(
            pasteboard.string(forType: .string)
                == "Reject unreadable link parent"
        )
    }

    @Test
    @MainActor
    func floatingOpenCodeRouteRejectsSamePIDFocusedWindowDrift() async throws {
        let accessibility = FakeAccessibilityElementClient()
        accessibility.bundleIdentifier = "ai.opencode.desktop"
        accessibility.role = kAXGroupRole as String
        accessibility.settableAttributes = [
            kAXFocusedAttribute as String,
            kAXSelectedTextRangeAttribute as String,
            kAXValueAttribute as String,
        ]
        let projectDirectory = FileManager.default.temporaryDirectory.path
        var commandVPosted = false
        let service = FocusedTextPasteService(
            accessibility: accessibility,
            pasteboard: FakeTextPasteboard(),
            postCommandV: { _ in
                commandVPosted = true
                return true
            },
            openURL: { _, _ in
                accessibility.secondaryRole = kAXTextAreaRole as String
                accessibility.secondaryDescriptionText = "Ask anything..."
                accessibility.secondaryValue = ""
                accessibility.exposeOpenCodeWindow(
                    children: [accessibility.secondaryElement],
                    projectDirectory: projectDirectory,
                    newSessionIsCurrent: true,
                    inAlternateWindow: true
                )
                return true
            },
            validateOpenCodeApplication: { _ in true },
            openCodeRouteTimeoutMilliseconds: 5,
            openCodeRouteGraceMilliseconds: 0,
            openCodeFocusSettleMilliseconds: 0,
            openCodeRoutePollMilliseconds: 1
        )

        let outcome = try await service.deliver(
            "Never follow a same-process window switch",
            to: service.captureTarget(),
            openCodeProjectDirectory: projectDirectory
        )

        #expect(
            outcome == .notPasted(
                "OpenCode lost focus, so DaemonState cancelled the handoff "
                    + "and will not reactivate it. "
                    + "The context was copied."
            )
        )
        #expect(!commandVPosted)
        #expect(accessibility.secondaryValue == "")
    }

    @Test
    @MainActor
    func floatingOpenCodeIgnoredRouteRejectsWrongWorkspaceComposer() async throws {
        let accessibility = FakeAccessibilityElementClient()
        accessibility.bundleIdentifier = "ai.opencode.desktop"
        accessibility.role = kAXGroupRole as String
        accessibility.settableAttributes = [
            kAXFocusedAttribute as String,
            kAXSelectedTextRangeAttribute as String,
            kAXValueAttribute as String,
        ]
        let requestedProject = FileManager.default.temporaryDirectory.path
        let wrongProject = FileManager.default.homeDirectoryForCurrentUser.path
        var commandVPosted = false
        let service = FocusedTextPasteService(
            accessibility: accessibility,
            pasteboard: FakeTextPasteboard(),
            postCommandV: { _ in
                commandVPosted = true
                return true
            },
            openURL: { _, _ in
                accessibility.secondaryRole = kAXTextAreaRole as String
                accessibility.secondaryDescriptionText = "Ask anything..."
                accessibility.secondaryValue = ""
                accessibility.exposeOpenCodeWindow(
                    children: [accessibility.secondaryElement],
                    projectDirectory: wrongProject,
                    newSessionIsCurrent: true
                )
                return true
            },
            validateOpenCodeApplication: { _ in true },
            openCodeRouteTimeoutMilliseconds: 5,
            openCodeRouteGraceMilliseconds: 0,
            openCodeFocusSettleMilliseconds: 0,
            openCodeRoutePollMilliseconds: 1
        )

        let outcome = try await service.deliver(
            "Never paste into the wrong workspace",
            to: service.captureTarget(),
            openCodeProjectDirectory: requestedProject
        )

        #expect(
            outcome == .notPasted(
                "OpenCode did not expose the requested active project and "
                    + "exactly one verified empty chat composer in the captured "
                    + "window; try the floating action again. "
                    + "The context was copied."
            )
        )
        #expect(!commandVPosted)
        #expect(accessibility.secondaryValue == "")
    }

    @Test
    @MainActor
    func floatingOpenCodeLocalModeRejectsWrongProject() async throws {
        let accessibility = FakeAccessibilityElementClient()
        accessibility.bundleIdentifier = "ai.opencode.desktop"
        accessibility.role = kAXGroupRole as String
        accessibility.settableAttributes = [
            kAXFocusedAttribute as String,
            kAXSelectedTextRangeAttribute as String,
            kAXValueAttribute as String,
        ]
        let requestedProject = FileManager.default.temporaryDirectory.path
        let wrongProject = FileManager.default.homeDirectoryForCurrentUser.path
        var synthesizedEvents: [String] = []
        let pasteboard = FakeTextPasteboard()
        let service = FocusedTextPasteService(
            accessibility: accessibility,
            pasteboard: pasteboard,
            postCommandV: { _ in
                synthesizedEvents.append("command-v")
                return true
            },
            postSpace: { _ in
                synthesizedEvents.append("space")
                return true
            },
            postDeleteBackward: { _ in
                synthesizedEvents.append("delete")
                return true
            },
            openURL: { _, _ in
                accessibility.secondaryRole = kAXTextAreaRole as String
                accessibility.secondaryDescriptionText = "Ask anything..."
                accessibility.secondaryValue = "\n"
                accessibility.exposeOpenCodeLocalProjectWindow(
                    children: [accessibility.secondaryElement],
                    projectDirectory: wrongProject
                )
                return true
            },
            validateOpenCodeApplication: { _ in true },
            openCodeRouteTimeoutMilliseconds: 5,
            openCodeRouteGraceMilliseconds: 0,
            openCodeFocusSettleMilliseconds: 0,
            openCodeRoutePollMilliseconds: 1
        )

        let outcome = try await service.deliver(
            "Never paste into the wrong local project",
            to: service.captureTarget(),
            openCodeProjectDirectory: requestedProject
        )

        #expect(
            outcome == .notPasted(
                "OpenCode did not expose the requested active project and "
                    + "exactly one verified empty chat composer in the captured "
                    + "window; try the floating action again. "
                    + "The context was copied."
            )
        )
        #expect(synthesizedEvents.isEmpty)
        #expect(accessibility.secondaryValue == "\n")
        #expect(
            pasteboard.string(forType: .string)
                == "Never paste into the wrong local project"
        )
    }

    @Test
    @MainActor
    func floatingOpenCodeRouteRejectsPathTextWithoutActiveProjectLink() async throws {
        let accessibility = FakeAccessibilityElementClient()
        accessibility.bundleIdentifier = "ai.opencode.desktop"
        accessibility.role = kAXGroupRole as String
        let requestedProject = FileManager.default.temporaryDirectory.path
        var commandVPosted = false
        let service = FocusedTextPasteService(
            accessibility: accessibility,
            pasteboard: FakeTextPasteboard(),
            postCommandV: { _ in
                commandVPosted = true
                return true
            },
            openURL: { _, _ in
                accessibility.secondaryRole = kAXTextAreaRole as String
                accessibility.secondaryDescriptionText = "Ask anything..."
                accessibility.secondaryValue = ""
                // Exact path text at the window root is not local-project
                // authority; it must be scoped by Projects and sessions.
                accessibility.exposeOpenCodeWindow(
                    children: [accessibility.secondaryElement],
                    projectDirectory: nil,
                    projectDisplay: requestedProject,
                    newSessionIsCurrent: true
                )
                return true
            },
            validateOpenCodeApplication: { _ in true },
            openCodeRouteTimeoutMilliseconds: 5,
            openCodeRouteGraceMilliseconds: 0,
            openCodeFocusSettleMilliseconds: 0,
            openCodeRoutePollMilliseconds: 1
        )

        let outcome = try await service.deliver(
            "Static path text is not project authority",
            to: service.captureTarget(),
            openCodeProjectDirectory: requestedProject
        )

        #expect(
            outcome == .notPasted(
                "OpenCode did not expose the requested active project and "
                    + "exactly one verified empty chat composer in the captured "
                    + "window; try the floating action again. "
                    + "The context was copied."
            )
        )
        #expect(!commandVPosted)
        #expect(accessibility.secondaryValue == "")
    }

    @Test
    @MainActor
    func floatingOpenCodeRouteFailureCopiesWithoutPasting() async throws {
        let accessibility = FakeAccessibilityElementClient()
        accessibility.bundleIdentifier = "ai.opencode.desktop"
        accessibility.role = kAXGroupRole as String
        let pasteboard = FakeTextPasteboard()
        var openedURLCount = 0
        var synthesizedEvents: [String] = []
        let service = FocusedTextPasteService(
            accessibility: accessibility,
            pasteboard: pasteboard,
            postCommandV: { _ in
                synthesizedEvents.append("command-v")
                return true
            },
            postSpace: { _ in
                synthesizedEvents.append("space")
                return true
            },
            postDeleteBackward: { _ in
                synthesizedEvents.append("delete")
                return true
            },
            openURL: { _, _ in
                openedURLCount += 1
                return false
            },
            validateOpenCodeApplication: { _ in true },
            openCodeRouteTimeoutMilliseconds: 5,
            openCodeRouteGraceMilliseconds: 0,
            openCodeFocusSettleMilliseconds: 0,
            openCodeRoutePollMilliseconds: 1
        )

        let outcome = try await service.deliver(
            "Copy after route failure",
            to: service.captureTarget(),
            openCodeProjectDirectory: FileManager.default.temporaryDirectory.path
        )

        #expect(
            outcome == .notPasted(
                "macOS could not request a new OpenCode chat composer. "
                    + "The context was copied."
            )
        )
        #expect(openedURLCount == 1)
        #expect(accessibility.insertedValues.isEmpty)
        #expect(synthesizedEvents.isEmpty)
        #expect(pasteboard.string(forType: .string) == "Copy after route failure")
    }

    @Test
    @MainActor
    func floatingOpenCodeRouteRejectsANonemptyComposer() async throws {
        let accessibility = FakeAccessibilityElementClient()
        accessibility.bundleIdentifier = "ai.opencode.desktop"
        accessibility.role = kAXGroupRole as String
        accessibility.settableAttributes = [
            kAXFocusedAttribute as String,
            kAXSelectedTextRangeAttribute as String,
            kAXValueAttribute as String,
        ]
        let pasteboard = FakeTextPasteboard()
        let projectDirectory = FileManager.default.temporaryDirectory.path
        var commandVPosted = false
        let service = FocusedTextPasteService(
            accessibility: accessibility,
            pasteboard: pasteboard,
            postCommandV: { _ in
                commandVPosted = true
                return true
            },
            openURL: { _, _ in
                accessibility.secondaryRole = kAXTextAreaRole as String
                accessibility.secondaryDescriptionText = "Ask anything..."
                accessibility.secondaryValue = "Keep this draft"
                accessibility.exposeOpenCodeWindow(
                    children: [
                        accessibility.element,
                        accessibility.secondaryElement,
                    ],
                    projectDirectory: projectDirectory,
                    newSessionIsCurrent: true
                )
                return true
            },
            validateOpenCodeApplication: { _ in true },
            openCodeRouteTimeoutMilliseconds: 1_000,
            openCodeRouteGraceMilliseconds: 0,
            openCodeFocusSettleMilliseconds: 0,
            openCodeRoutePollMilliseconds: 1
        )

        let outcome = try await service.deliver(
            "Do not overwrite a nonempty composer",
            to: service.captureTarget(),
            openCodeProjectDirectory: projectDirectory
        )

        #expect(
            outcome == .notPasted(
                "OpenCode exposed a different nonempty draft instead of a fresh "
                    + "composer for the requested project, so DaemonState did not "
                    + "overwrite it. Send or clear that draft, then try the "
                    + "floating action again. "
                    + "The context was copied."
            )
        )
        #expect(accessibility.secondaryValue == "Keep this draft")
        #expect(!commandVPosted)
        #expect(accessibility.insertedValues.isEmpty)
    }

    @Test
    @MainActor
    func floatingOpenCodeRouteRejectsMultipleEmptyComposers() async throws {
        let accessibility = FakeAccessibilityElementClient()
        accessibility.bundleIdentifier = "ai.opencode.desktop"
        accessibility.role = kAXGroupRole as String
        accessibility.settableAttributes = [
            kAXFocusedAttribute as String,
            kAXSelectedTextRangeAttribute as String,
            kAXValueAttribute as String,
        ]
        let pasteboard = FakeTextPasteboard()
        let projectDirectory = FileManager.default.temporaryDirectory.path
        var commandVPosted = false
        let service = FocusedTextPasteService(
            accessibility: accessibility,
            pasteboard: pasteboard,
            postCommandV: { _ in
                commandVPosted = true
                return true
            },
            openURL: { _, _ in
                accessibility.role = kAXTextAreaRole as String
                accessibility.descriptionText = "Ask anything..."
                accessibility.value = ""
                accessibility.secondaryRole = kAXTextAreaRole as String
                accessibility.secondaryDescriptionText = "Ask anything..."
                accessibility.secondaryValue = ""
                accessibility.exposeOpenCodeWindow(
                    children: [
                        accessibility.element,
                        accessibility.secondaryElement,
                    ],
                    projectDirectory: projectDirectory,
                    newSessionIsCurrent: true
                )
                return true
            },
            validateOpenCodeApplication: { _ in true },
            openCodeRouteTimeoutMilliseconds: 5,
            openCodeRouteGraceMilliseconds: 0,
            openCodeFocusSettleMilliseconds: 0,
            openCodeRoutePollMilliseconds: 1
        )

        let outcome = try await service.deliver(
            "Never guess between empty composers",
            to: service.captureTarget(),
            openCodeProjectDirectory: projectDirectory
        )

        #expect(
            outcome == .notPasted(
                "OpenCode did not expose the requested active project and "
                    + "exactly one verified empty chat composer in the captured "
                    + "window; try the floating action again. "
                    + "The context was copied."
            )
        )
        #expect(!commandVPosted)
        #expect(accessibility.insertedValues.isEmpty)
    }

    @Test
    @MainActor
    func floatingOpenCodeDepthCappedScanFailsClosedInsteadOfClaimingUniqueness() async throws {
        let accessibility = FakeAccessibilityElementClient()
        accessibility.bundleIdentifier = "ai.opencode.desktop"
        accessibility.role = kAXTextAreaRole as String
        accessibility.descriptionText = "Ask anything..."
        accessibility.value = ""
        accessibility.secondaryRole = kAXTextAreaRole as String
        accessibility.secondaryDescriptionText = "Ask anything..."
        accessibility.secondaryValue = ""

        let containers = (0..<33).map {
            AXUIElementCreateApplication(pid_t(50_000 + $0))
        }
        accessibility.focusedWindowChildren = [
            accessibility.element,
            containers[0],
        ]
        for index in 0..<32 {
            accessibility.elementChildren[containers[index]] = [
                containers[index + 1],
            ]
        }
        accessibility.elementChildren[containers[32]] = [
            accessibility.secondaryElement,
        ]

        var openedURLCount = 0
        var commandVPosted = false
        let service = FocusedTextPasteService(
            accessibility: accessibility,
            pasteboard: FakeTextPasteboard(),
            postCommandV: { _ in
                commandVPosted = true
                return true
            },
            openURL: { _, _ in
                openedURLCount += 1
                return false
            },
            validateOpenCodeApplication: { _ in true }
        )

        let outcome = try await service.deliver(
            "Never accept a partial uniqueness proof",
            to: service.captureTarget(),
            openCodeProjectDirectory: FileManager.default.temporaryDirectory.path
        )

        #expect(
            outcome == .notPasted(
                "macOS could not request a new OpenCode chat composer. "
                    + "The context was copied."
            )
        )
        #expect(openedURLCount == 1)
        #expect(!commandVPosted)
        #expect(accessibility.value == "")
        #expect(accessibility.secondaryValue == "")
    }

    @Test
    @MainActor
    func floatingOpenCodeTerminalRoutesToFreshComposerAndRemainsUnchanged() async throws {
        let accessibility = FakeAccessibilityElementClient()
        accessibility.bundleIdentifier = "ai.opencode.desktop"
        accessibility.role = kAXTextAreaRole as String
        accessibility.descriptionText = "Terminal input"
        accessibility.value = "pwd"
        accessibility.settableAttributes = [
            kAXFocusedAttribute as String,
            kAXSelectedTextRangeAttribute as String,
            kAXValueAttribute as String,
        ]
        let projectDirectory = FileManager.default.temporaryDirectory.path
        var synthesizedEvents: [String] = []
        let service = FocusedTextPasteService(
            accessibility: accessibility,
            pasteboard: FakeTextPasteboard(),
            postCommandV: { _ in
                synthesizedEvents.append("command-v")
                return true
            },
            postSpace: { _ in
                synthesizedEvents.append("space")
                accessibility.secondaryValue = "Fresh terminal-safe context "
                return true
            },
            postDeleteBackward: { _ in
                synthesizedEvents.append("delete")
                accessibility.secondaryValue = "Fresh terminal-safe context"
                return true
            },
            openURL: { _, _ in
                accessibility.secondaryRole = kAXTextAreaRole as String
                accessibility.secondaryDescriptionText = "Ask anything..."
                accessibility.secondaryValue = ""
                accessibility.exposeOpenCodeWindow(
                    children: [
                        accessibility.element,
                        accessibility.secondaryElement,
                    ],
                    projectDirectory: projectDirectory,
                    newSessionIsCurrent: true
                )
                return true
            },
            validateOpenCodeApplication: { _ in true },
            openCodeRouteTimeoutMilliseconds: 50,
            openCodeRouteGraceMilliseconds: 0,
            openCodeFocusSettleMilliseconds: 0,
            openCodeRoutePollMilliseconds: 1
        )

        let outcome = try await service.deliver(
            "Fresh terminal-safe context",
            to: service.captureTarget(),
            openCodeProjectDirectory: projectDirectory
        )

        #expect(outcome == .insertedIntoVerifiedEmptyComposerWithInputSync)
        #expect(accessibility.value == "pwd")
        #expect(accessibility.secondaryValue == "Fresh terminal-safe context")
        #expect(accessibility.focusedElementMatches(accessibility.secondaryElement))
        #expect(synthesizedEvents == ["space", "delete"])
    }

    @Test
    @MainActor
    func floatingOpenCodeNonemptyDraftRoutesWithoutOverwritingIt() async throws {
        let accessibility = FakeAccessibilityElementClient()
        accessibility.bundleIdentifier = "ai.opencode.desktop"
        accessibility.role = kAXTextAreaRole as String
        accessibility.descriptionText = "Ask anything..."
        accessibility.value = "Keep this draft"
        accessibility.settableAttributes = [
            kAXFocusedAttribute as String,
            kAXSelectedTextRangeAttribute as String,
            kAXValueAttribute as String,
        ]
        let projectDirectory = FileManager.default.temporaryDirectory.path
        var commandVPosted = false
        let service = FocusedTextPasteService(
            accessibility: accessibility,
            pasteboard: FakeTextPasteboard(),
            postCommandV: { _ in
                commandVPosted = true
                return true
            },
            postSpace: { _ in
                accessibility.secondaryValue = "Fresh draft-safe context "
                return true
            },
            postDeleteBackward: { _ in
                accessibility.secondaryValue = "Fresh draft-safe context"
                return true
            },
            openURL: { _, _ in
                accessibility.secondaryRole = kAXTextAreaRole as String
                accessibility.secondaryDescriptionText = "Ask anything..."
                accessibility.secondaryValue = ""
                accessibility.exposeOpenCodeWindow(
                    // The routed renderer detached the old draft. Its AXValue
                    // remains available to prove it was never overwritten, but
                    // only the new empty composer is still in the window tree.
                    children: [accessibility.secondaryElement],
                    projectDirectory: projectDirectory,
                    newSessionIsCurrent: true
                )
                return true
            },
            validateOpenCodeApplication: { _ in true },
            openCodeRouteTimeoutMilliseconds: 50,
            openCodeRouteGraceMilliseconds: 0,
            openCodeFocusSettleMilliseconds: 0,
            openCodeRoutePollMilliseconds: 1
        )

        let outcome = try await service.deliver(
            "Fresh draft-safe context",
            to: service.captureTarget(),
            openCodeProjectDirectory: projectDirectory
        )

        #expect(outcome == .insertedIntoVerifiedEmptyComposerWithInputSync)
        #expect(accessibility.value == "Keep this draft")
        #expect(accessibility.secondaryValue == "Fresh draft-safe context")
        #expect(!commandVPosted)
    }

    @Test
    @MainActor
    func floatingOpenCodePersistentOldDraftAndFreshComposerRemainAmbiguous() async throws {
        let accessibility = FakeAccessibilityElementClient()
        accessibility.bundleIdentifier = "ai.opencode.desktop"
        accessibility.role = kAXTextAreaRole as String
        accessibility.descriptionText = "Ask anything..."
        accessibility.value = "Keep this old draft"
        accessibility.settableAttributes = [
            kAXFocusedAttribute as String,
            kAXSelectedTextRangeAttribute as String,
            kAXValueAttribute as String,
        ]
        let projectDirectory = FileManager.default.temporaryDirectory.path
        var synthesizedEvents: [String] = []
        let service = FocusedTextPasteService(
            accessibility: accessibility,
            pasteboard: FakeTextPasteboard(),
            postCommandV: { _ in
                synthesizedEvents.append("command-v")
                return true
            },
            postSpace: { _ in
                synthesizedEvents.append("space")
                return true
            },
            postDeleteBackward: { _ in
                synthesizedEvents.append("delete")
                return true
            },
            openURL: { _, _ in
                accessibility.secondaryRole = kAXTextAreaRole as String
                accessibility.secondaryDescriptionText = "Ask anything..."
                accessibility.secondaryValue = ""
                // A renderer transition that leaves both normal composers
                // traversable is ambiguous even though one of them is fresh.
                accessibility.exposeOpenCodeWindow(
                    children: [
                        accessibility.element,
                        accessibility.secondaryElement,
                    ],
                    projectDirectory: projectDirectory,
                    newSessionIsCurrent: true
                )
                return true
            },
            validateOpenCodeApplication: { _ in true },
            openCodeRouteTimeoutMilliseconds: 10,
            openCodeRouteGraceMilliseconds: 0,
            openCodeFocusSettleMilliseconds: 0,
            openCodeRoutePollMilliseconds: 1
        )

        let outcome = try await service.deliver(
            "Never choose between two routed composers",
            to: service.captureTarget(),
            openCodeProjectDirectory: projectDirectory
        )

        guard case .notPasted = outcome else {
            Issue.record("A persistent old draft plus fresh composer must fail closed")
            return
        }
        #expect(outcome != .alreadyPresentInVerifiedOpenCodeComposer)
        #expect(accessibility.value == "Keep this old draft")
        #expect(accessibility.secondaryValue == "")
        #expect(accessibility.performedAttributeMutations.isEmpty)
        #expect(accessibility.insertedValues.isEmpty)
        #expect(synthesizedEvents.isEmpty)
    }

    @Test
    @MainActor
    func floatingOpenCodeAmbiguousEmptyComposersRouteToOneEmptyComposer() async throws {
        let accessibility = FakeAccessibilityElementClient()
        accessibility.bundleIdentifier = "ai.opencode.desktop"
        accessibility.role = kAXTextAreaRole as String
        accessibility.descriptionText = "Ask anything..."
        accessibility.value = ""
        accessibility.secondaryRole = kAXTextAreaRole as String
        accessibility.secondaryDescriptionText = "Ask anything..."
        accessibility.secondaryValue = ""
        accessibility.focusedWindowChildren = [
            accessibility.element,
            accessibility.secondaryElement,
        ]
        accessibility.settableAttributes = [
            kAXFocusedAttribute as String,
            kAXSelectedTextRangeAttribute as String,
            kAXValueAttribute as String,
        ]
        let projectDirectory = FileManager.default.temporaryDirectory.path
        var routeCount = 0
        var commandVPosted = false
        let service = FocusedTextPasteService(
            accessibility: accessibility,
            pasteboard: FakeTextPasteboard(),
            postCommandV: { _ in
                commandVPosted = true
                return true
            },
            postSpace: { _ in
                accessibility.tertiaryValue = "Fresh ambiguity-safe context "
                return true
            },
            postDeleteBackward: { _ in
                accessibility.tertiaryValue = "Fresh ambiguity-safe context"
                return true
            },
            openURL: { _, _ in
                routeCount += 1
                accessibility.tertiaryRole = kAXTextAreaRole as String
                accessibility.tertiaryDescriptionText = "Ask anything..."
                accessibility.tertiaryValue = ""
                // Model OpenCode replacing the old session view with the
                // routed new-session view and its one empty composer.
                accessibility.exposeOpenCodeWindow(
                    children: [accessibility.tertiaryElement],
                    projectDirectory: projectDirectory,
                    newSessionIsCurrent: true
                )
                return true
            },
            validateOpenCodeApplication: { _ in true },
            openCodeRouteTimeoutMilliseconds: 50,
            openCodeRouteGraceMilliseconds: 0,
            openCodeFocusSettleMilliseconds: 0,
            openCodeRoutePollMilliseconds: 1
        )

        let outcome = try await service.deliver(
            "Fresh ambiguity-safe context",
            to: service.captureTarget(),
            openCodeProjectDirectory: projectDirectory
        )

        #expect(outcome == .insertedIntoVerifiedEmptyComposerWithInputSync)
        #expect(routeCount == 1)
        #expect(accessibility.value == "")
        #expect(accessibility.secondaryValue == "")
        #expect(accessibility.tertiaryValue == "Fresh ambiguity-safe context")
        #expect(!commandVPosted)
    }

    @Test
    @MainActor
    func floatingOpenCodeRouteRejectsAStaleApplicationIdentity() async throws {
        let accessibility = FakeAccessibilityElementClient()
        accessibility.bundleIdentifier = "ai.opencode.desktop"
        accessibility.role = kAXGroupRole as String
        let pasteboard = FakeTextPasteboard()
        var commandVPosted = false
        let service = FocusedTextPasteService(
            accessibility: accessibility,
            pasteboard: pasteboard,
            postCommandV: { _ in
                commandVPosted = true
                return true
            },
            openURL: { _, _ in
                accessibility.frontmostPID = 99_999
                return true
            },
            validateOpenCodeApplication: { _ in true },
            openCodeRouteTimeoutMilliseconds: 5,
            openCodeRouteGraceMilliseconds: 0,
            openCodeFocusSettleMilliseconds: 0,
            openCodeRoutePollMilliseconds: 1
        )

        let outcome = try await service.deliver(
            "Do not route across an app race",
            to: service.captureTarget(),
            openCodeProjectDirectory: FileManager.default.temporaryDirectory.path
        )

        #expect(
            outcome == .notPasted(
                "OpenCode lost focus, so DaemonState cancelled the handoff "
                    + "and will not reactivate it. "
                    + "The context was copied."
            )
        )
        #expect(!commandVPosted)
        #expect(
            pasteboard.string(forType: .string)
                == "Do not route across an app race"
        )
    }

    @Test
    @MainActor
    func floatingOpenCodeRouteAbortsWhenClipboardChanges() async throws {
        let accessibility = FakeAccessibilityElementClient()
        accessibility.bundleIdentifier = "ai.opencode.desktop"
        accessibility.role = kAXGroupRole as String
        accessibility.settableAttributes = [
            kAXFocusedAttribute as String,
            kAXSelectedTextRangeAttribute as String,
            kAXValueAttribute as String,
        ]
        let pasteboard = FakeTextPasteboard()
        let projectDirectory = FileManager.default.temporaryDirectory.path
        var commandVPosted = false
        let service = FocusedTextPasteService(
            accessibility: accessibility,
            pasteboard: pasteboard,
            postCommandV: { _ in
                commandVPosted = true
                return true
            },
            openURL: { _, _ in
                accessibility.secondaryRole = kAXTextAreaRole as String
                accessibility.secondaryDescriptionText = "Ask anything..."
                accessibility.secondaryValue = ""
                accessibility.exposeOpenCodeWindow(
                    children: [
                        accessibility.element,
                        accessibility.secondaryElement,
                    ],
                    projectDirectory: projectDirectory,
                    newSessionIsCurrent: true
                )
                pasteboard.simulateExternalChange("User clipboard")
                return true
            },
            validateOpenCodeApplication: { _ in true },
            openCodeRouteTimeoutMilliseconds: 50,
            openCodeRouteGraceMilliseconds: 0,
            openCodeFocusSettleMilliseconds: 0,
            openCodeRoutePollMilliseconds: 1
        )

        do {
            _ = try await service.deliver(
                "Context must not overwrite a clipboard race",
                to: service.captureTarget(),
                openCodeProjectDirectory: projectDirectory
            )
            Issue.record("Expected the changed clipboard to abort delivery")
        } catch PasteDeliveryError.clipboardChanged {
            // Expected fail-closed result.
        } catch {
            Issue.record("Unexpected error: \(error)")
        }

        #expect(accessibility.secondaryValue == "")
        #expect(!commandVPosted)
        #expect(accessibility.insertedValues.isEmpty)
        #expect(pasteboard.string(forType: .string) == "User clipboard")
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
    func openCodeOneShotConfigurationSeparatesMarkerAndFocusedPolicies() {
        let projectDirectory = FileManager.default.currentDirectoryPath
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
                    "--target-marker",
                    "ds-0123456789abcdef0123456789abcdef",
                ]
            ) == nil
        )
        #expect(
            ComposerPasteConfiguration.parse(
                arguments: base + [
                    "--target-policy",
                    "opencode-chat-composer-v1",
                ]
            ) == nil
        )
        #expect(
            ComposerPasteConfiguration.parse(
                arguments: base + [
                    "--target-policy",
                    "opencode-chat-composer-v1",
                    "--target-marker",
                    "ds-0123456789abcdef0123456789abcdef",
                    "--expected-project-directory",
                    projectDirectory,
                ]
            )?.targetPolicy == .openCodeChatComposerV1
        )
        #expect(
            ComposerPasteConfiguration.parse(
                arguments: base + [
                    "--target-policy",
                    "opencode-chat-composer-v1",
                    "--target-marker",
                    "",
                    "--expected-project-directory",
                    projectDirectory,
                ]
            ) == nil
        )
        #expect(
            ComposerPasteConfiguration.parse(
                arguments: base + [
                    "--target-policy",
                    "opencode-focused-chat-composer-v1",
                ]
            )?.targetPolicy == .openCodeFocusedChatComposerV1
        )
        #expect(
            ComposerPasteConfiguration.parse(
                arguments: base + [
                    "--target-policy",
                    "opencode-focused-chat-composer-v1",
                    "--target-marker",
                    "ds-0123456789abcdef0123456789abcdef",
                ]
            ) == nil
        )
        #expect(
            ComposerPasteConfiguration.parse(
                arguments: base + [
                    "--target-policy",
                    "opencode-focused-chat-composer-v1",
                    "--expected-project-directory",
                    projectDirectory,
                ]
            ) == nil
        )
    }

    @Test
    @MainActor
    func focusedOpenCodePolicyUsesOneEmptyNormalComposerWithoutAURL() async throws {
        let content = "Focused OpenCode continuation context"
        let accessibility = FakeAccessibilityElementClient()
        accessibility.bundleIdentifier = "ai.opencode.desktop"
        accessibility.role = kAXGroupRole as String
        accessibility.descriptionText = "OpenCode landing content"
        accessibility.value = nil
        accessibility.secondaryRole = kAXTextAreaRole as String
        accessibility.secondaryDescriptionText = "Prompt"
        accessibility.secondaryDOMClasses = [
            "select-text",
            "w-full",
            "text-14-regular",
            "whitespace-pre-wrap",
        ]
        accessibility.secondaryValue = ""
        accessibility.focusedWindowChildren = [
            accessibility.nestedContainerElement,
        ]
        accessibility.nestedContainerChildren = [
            accessibility.element,
            accessibility.secondaryElement,
        ]
        accessibility.settableAttributes = [
            kAXFocusedAttribute as String,
            kAXSelectedTextRangeAttribute as String,
            kAXValueAttribute as String,
        ]
        accessibility.reflectSuccessfulInsertionInValue = true
        var openedURLCount = 0
        var synthesizedEvents: [String] = []
        let service = FocusedTextPasteService(
            accessibility: accessibility,
            pasteboard: FakeTextPasteboard(),
            postCommandV: { _ in
                synthesizedEvents.append("command-v")
                return true
            },
            postSpace: { _ in
                synthesizedEvents.append("space")
                return accessibility.typeSpaceInFocusedElement()
            },
            postDeleteBackward: { _ in
                synthesizedEvents.append("delete")
                return accessibility.deleteSelectionInFocusedElement()
            },
            openURL: { _, _ in
                openedURLCount += 1
                return true
            },
            validateOpenCodeApplication: { _ in true }
        )

        let capture = service.captureTarget(
            expectedBundleIdentifiers: ["ai.opencode.desktop"],
            allowNonEditableApplicationFallback: false,
            allowMissingFocusedElementFallback: false,
            requireExactInsertionReadback: true,
            requireFocusedEmptyOpenCodeComposer: true
        )
        let outcome = try await service.deliver(content, to: capture)

        #expect(outcome == .insertedIntoVerifiedEmptyComposerWithInputSync)
        #expect(accessibility.secondaryValue == content)
        #expect(accessibility.focusedElementMatches(accessibility.secondaryElement))
        #expect(accessibility.insertedValues.isEmpty)
        #expect(synthesizedEvents == ["space", "delete"])
        #expect(openedURLCount == 0)
    }

    @Test
    @MainActor
    func focusedOpenCodePolicyAcceptsFocusedV2StructuralEmptyBehindOverlay() async throws {
        let content = "Verified OpenCode context from either context action"
        let accessibility = FakeAccessibilityElementClient()
        accessibility.bundleIdentifier = "ai.opencode.desktop"
        accessibility.role = kAXGroupRole as String
        accessibility.descriptionText = "OpenCode landing content"
        accessibility.value = nil
        accessibility.secondaryRole = kAXTextAreaRole as String
        accessibility.secondaryDescriptionText = "Prompt"
        accessibility.secondaryDOMClasses = [
            "min-h-[60px]",
            "max-h-[180px]",
            "w-full",
            "overflow-y-auto",
            "whitespace-pre-wrap",
            "text-v2-text-text-base",
            "focus:outline-none",
        ]
        accessibility.secondaryValue = "\u{200B}"
        accessibility.focusedWindowChildren = [
            accessibility.nestedContainerElement,
        ]
        accessibility.nestedContainerChildren = [
            accessibility.element,
            accessibility.secondaryElement,
        ]
        accessibility.setFocusedElement(accessibility.secondaryElement)
        accessibility.hitTestInvisibleElements.insert(
            accessibility.secondaryElement
        )
        accessibility.settableAttributes = [
            kAXFocusedAttribute as String,
            kAXSelectedTextRangeAttribute as String,
            kAXValueAttribute as String,
        ]
        accessibility.reflectSuccessfulInsertionInValue = true
        var openedURLCount = 0
        var synthesizedEvents: [String] = []
        let service = FocusedTextPasteService(
            accessibility: accessibility,
            pasteboard: FakeTextPasteboard(),
            postCommandV: { _ in
                synthesizedEvents.append("command-v")
                return true
            },
            postSpace: { _ in
                synthesizedEvents.append("space")
                return accessibility.typeSpaceInFocusedElement()
            },
            postDeleteBackward: { _ in
                synthesizedEvents.append("delete")
                return accessibility.deleteSelectionInFocusedElement()
            },
            openURL: { _, _ in
                openedURLCount += 1
                return true
            },
            validateOpenCodeApplication: { _ in true }
        )

        let capture = service.captureTarget(
            expectedBundleIdentifiers: ["ai.opencode.desktop"],
            allowNonEditableApplicationFallback: false,
            allowMissingFocusedElementFallback: false,
            requireExactInsertionReadback: true,
            requireFocusedEmptyOpenCodeComposer: true
        )
        let outcome = try await service.deliver(content, to: capture)

        #expect(outcome == .insertedIntoVerifiedEmptyComposerWithInputSync)
        #expect(accessibility.secondaryValue == content)
        #expect(accessibility.focusedElementMatches(accessibility.secondaryElement))
        #expect(accessibility.insertedValues.isEmpty)
        #expect(synthesizedEvents == ["space", "delete"])
        #expect(openedURLCount == 0)
    }

    @Test
    @MainActor
    func focusedOpenCodePolicyDoesNotBypassHitTestForUnfocusedCandidate() async throws {
        let accessibility = FakeAccessibilityElementClient()
        accessibility.bundleIdentifier = "ai.opencode.desktop"
        accessibility.role = kAXGroupRole as String
        accessibility.descriptionText = "OpenCode landing content"
        accessibility.value = nil
        accessibility.secondaryRole = kAXTextAreaRole as String
        accessibility.secondaryDescriptionText = "Prompt"
        accessibility.secondaryDOMClasses = [
            "min-h-[60px]",
            "max-h-[180px]",
            "w-full",
            "overflow-y-auto",
            "whitespace-pre-wrap",
            "text-v2-text-text-base",
            "focus:outline-none",
        ]
        accessibility.secondaryValue = "\u{200B}\n"
        accessibility.focusedWindowChildren = [
            accessibility.nestedContainerElement,
        ]
        accessibility.nestedContainerChildren = [
            accessibility.element,
            accessibility.secondaryElement,
        ]
        accessibility.setFocusedElement(accessibility.element)
        accessibility.hitTestInvisibleElements.insert(
            accessibility.secondaryElement
        )
        accessibility.settableAttributes = [
            kAXFocusedAttribute as String,
            kAXSelectedTextRangeAttribute as String,
            kAXValueAttribute as String,
        ]
        var openedURLCount = 0
        var synthesizedEvents: [String] = []
        let service = FocusedTextPasteService(
            accessibility: accessibility,
            pasteboard: FakeTextPasteboard(),
            postCommandV: { _ in
                synthesizedEvents.append("command-v")
                return true
            },
            postSpace: { _ in
                synthesizedEvents.append("space")
                return true
            },
            postDeleteBackward: { _ in
                synthesizedEvents.append("delete")
                return true
            },
            openURL: { _, _ in
                openedURLCount += 1
                return true
            },
            validateOpenCodeApplication: { _ in true }
        )

        let capture = service.captureTarget(
            expectedBundleIdentifiers: ["ai.opencode.desktop"],
            allowNonEditableApplicationFallback: false,
            allowMissingFocusedElementFallback: false,
            requireExactInsertionReadback: true,
            requireFocusedEmptyOpenCodeComposer: true
        )
        let outcome = try await service.deliver(
            "Must not mutate an unfocused OpenCode editor",
            to: capture
        )

        #expect(
            outcome == .notPasted(
                "Open exactly one empty normal OpenCode chat composer, then "
                    + "try again. The context was copied."
            )
        )
        #expect(accessibility.secondaryValue == "\u{200B}\n")
        #expect(accessibility.performedAttributeMutations.isEmpty)
        #expect(synthesizedEvents.isEmpty)
        #expect(openedURLCount == 0)
    }

    @Test
    @MainActor
    func focusedOpenCodePolicyRejectsTerminalWithoutAURLOrMutation() async throws {
        let accessibility = FakeAccessibilityElementClient()
        accessibility.bundleIdentifier = "ai.opencode.desktop"
        accessibility.role = kAXTextAreaRole as String
        accessibility.descriptionText = "Terminal input"
        accessibility.value = ""
        accessibility.settableAttributes = [
            kAXFocusedAttribute as String,
            kAXSelectedTextRangeAttribute as String,
            kAXValueAttribute as String,
        ]
        var openedURLCount = 0
        var synthesizedEvents: [String] = []
        let service = FocusedTextPasteService(
            accessibility: accessibility,
            pasteboard: FakeTextPasteboard(),
            postCommandV: { _ in
                synthesizedEvents.append("command-v")
                return true
            },
            postSpace: { _ in
                synthesizedEvents.append("space")
                return true
            },
            postDeleteBackward: { _ in
                synthesizedEvents.append("delete")
                return true
            },
            openURL: { _, _ in
                openedURLCount += 1
                return true
            },
            validateOpenCodeApplication: { _ in true }
        )

        let capture = service.captureTarget(
            expectedBundleIdentifiers: ["ai.opencode.desktop"],
            allowNonEditableApplicationFallback: false,
            allowMissingFocusedElementFallback: false,
            requireExactInsertionReadback: true,
            requireFocusedEmptyOpenCodeComposer: true
        )
        let outcome = try await service.deliver(
            "Never paste continuation context into a terminal",
            to: capture
        )

        #expect(
            outcome == .notPasted(
                "Open exactly one empty normal OpenCode chat composer, then "
                    + "try again. The context was copied."
            )
        )
        #expect(accessibility.value == "")
        #expect(accessibility.performedAttributeMutations.isEmpty)
        #expect(synthesizedEvents.isEmpty)
        #expect(openedURLCount == 0)
    }

    @Test
    @MainActor
    func strictOpenCodeEmptyInitialValueCannotReportMarkerReplacement() async throws {
        let accessibility = FakeAccessibilityElementClient()
        accessibility.bundleIdentifier = "ai.opencode.desktop"
        accessibility.role = kAXTextAreaRole as String
        accessibility.descriptionText = "Ask anything..."
        accessibility.value = ""
        accessibility.settableAttributes = [
            kAXSelectedTextRangeAttribute as String,
            kAXValueAttribute as String,
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
            discoverEditableWithExactValue: ""
        )
        let outcome = try await service.deliver("Context", to: capture)

        #expect(outcome == .notPasted("The composer identity marker is invalid."))
        #expect(accessibility.value == "")
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
    func strictOpenCodeTargetRejectsExactMarkerInWrongProject() async throws {
        let marker = "ds-0123456789abcdef"
        let requestedProject = FileManager.default.temporaryDirectory.path
        let activeProject = FileManager.default.homeDirectoryForCurrentUser.path
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
        accessibility.exposeOpenCodeLocalProjectWindow(
            children: [accessibility.element],
            projectDirectory: activeProject
        )
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
            discoverEditableWithExactValue: marker,
            attestingOpenCodeProjectDirectory: requestedProject
        )
        let outcome = try await service.deliver(
            "Context for the requested project",
            to: capture
        )

        #expect(
            outcome == .notPasted(
                "The selected AI desktop app has not exposed its verified composer yet."
            )
        )
        #expect(accessibility.value == marker)
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
        let projectDirectory = FileManager.default.temporaryDirectory.path
        accessibility.exposeOpenCodeLocalProjectWindow(
            children: [accessibility.nestedContainerElement],
            projectDirectory: projectDirectory
        )
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
                return accessibility.typeSpaceInFocusedElement()
            },
            postDeleteBackward: { _ in
                deletePosted = true
                return accessibility.deleteSelectionInFocusedElement()
            }
        )

        let capture = service.captureTarget(
            expectedBundleIdentifiers: ["ai.opencode.desktop"],
            allowNonEditableApplicationFallback: false,
            allowMissingFocusedElementFallback: false,
            requireExactInsertionReadback: true,
            discoverEditableWithExactValue: marker,
            attestingOpenCodeProjectDirectory: projectDirectory
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
    func strictOpenCodeTrailingLineFeedDeletesChromiumsStructuralSentinel() async throws {
        let marker = "ds-0123456789abcdef"
        let content = "# Verified chat context 😀\n"
        let accessibility = FakeAccessibilityElementClient()
        accessibility.bundleIdentifier = "ai.opencode.desktop"
        accessibility.role = kAXTextAreaRole as String
        accessibility.descriptionText = "Ask anything..."
        accessibility.value = marker
        accessibility.serializesTypedSpaceBeforeTrailingLineFeed = true
        accessibility.settableAttributes = [
            kAXFocusedAttribute as String,
            kAXSelectedTextAttribute as String,
            kAXSelectedTextRangeAttribute as String,
            kAXValueAttribute as String,
        ]
        var synthesizedEvents: [String] = []
        let service = FocusedTextPasteService(
            accessibility: accessibility,
            pasteboard: FakeTextPasteboard(),
            postCommandV: { _ in
                synthesizedEvents.append("command-v")
                return true
            },
            postSpace: { _ in
                synthesizedEvents.append("space")
                return accessibility.typeSpaceInFocusedElement()
            },
            postDeleteBackward: { _ in
                synthesizedEvents.append("delete")
                return accessibility.deleteSelectionInFocusedElement()
            }
        )

        let capture = service.captureTarget(
            expectedBundleIdentifiers: ["ai.opencode.desktop"],
            allowNonEditableApplicationFallback: false,
            allowMissingFocusedElementFallback: false,
            requireExactInsertionReadback: true,
            discoverEditableWithExactValue: marker
        )
        let outcome = try await service.deliver(content, to: capture)

        #expect(outcome == .markerReplacedWithVerifiedInputSync)
        #expect(accessibility.value == content)
        #expect(synthesizedEvents == ["space", "delete"])
        #expect(accessibility.selectedText == nil)
    }

    @Test
    @MainActor
    func strictOpenCodeDoesNotDeleteIfUserSwitchesAppsDuringSentinelProof() async throws {
        let marker = "ds-0123456789abcdef"
        let content = "# Verified chat context 😀\n"
        let chromiumSentinelValue = String(content.dropLast()) + " \n"
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
        var synthesizedEvents: [String] = []
        let service = FocusedTextPasteService(
            accessibility: accessibility,
            pasteboard: FakeTextPasteboard(),
            postCommandV: { _ in
                synthesizedEvents.append("command-v")
                return true
            },
            postSpace: { _ in
                synthesizedEvents.append("space")
                accessibility.value = chromiumSentinelValue
                return true
            },
            postDeleteBackward: { _ in
                synthesizedEvents.append("delete")
                accessibility.value = content
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
        accessibility.selectedTextReadCallback = { selectedText in
            #expect(selectedText == " ")
            accessibility.frontmostPID = 99_999
            accessibility.bundleIdentifier = "com.google.Chrome"
        }
        let outcome = try await service.deliver(content, to: capture)

        #expect(
            outcome == .accessibilityInsertionUnverified(
                "macOS acknowledged the context insertion, but the editor "
                    + "did not expose the exact inserted value for verification."
            )
        )
        #expect(accessibility.value == chromiumSentinelValue)
        #expect(synthesizedEvents == ["space"])
        #expect(accessibility.selectedText == " ")
    }

    @Test
    @MainActor
    func strictOpenCodeDoesNotDeleteARemappedSentinelRange() async throws {
        let marker = "ds-0123456789abcdef"
        let content = "# Verified chat context 😀\n"
        let chromiumSentinelValue = String(content.dropLast()) + " \n"
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
        // Model Chromium accepting the selection request but reporting a
        // different interior range. No PID-scoped Delete may be dispatched.
        accessibility.reportedSelectedTextRanges = [
            CFRange(location: content.utf16.count, length: 0),
            CFRange(location: 0, length: 1),
        ]
        var synthesizedEvents: [String] = []
        let service = FocusedTextPasteService(
            accessibility: accessibility,
            pasteboard: FakeTextPasteboard(),
            postCommandV: { _ in
                synthesizedEvents.append("command-v")
                return true
            },
            postSpace: { _ in
                synthesizedEvents.append("space")
                accessibility.value = chromiumSentinelValue
                return true
            },
            postDeleteBackward: { _ in
                synthesizedEvents.append("delete")
                accessibility.value = content
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
        let outcome = try await service.deliver(content, to: capture)

        #expect(
            outcome == .accessibilityInsertionUnverified(
                "macOS acknowledged the context insertion, but the editor "
                    + "did not expose the exact inserted value for verification."
            )
        )
        #expect(accessibility.value == chromiumSentinelValue)
        #expect(synthesizedEvents == ["space"])
        #expect(accessibility.selectedText == " ")
    }

    @Test
    @MainActor
    func strictOpenCodeDoesNotTypeSpaceAtARemappedCursorRange() async throws {
        let marker = "ds-0123456789abcdef"
        let content = "# Preserve every context character 😀\n"
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
        // Model Chromium acknowledging the requested end cursor while
        // reporting a clamped interior cursor. No key event may be sent.
        accessibility.reportedSelectedTextRanges = [
            CFRange(location: 0, length: 0),
        ]
        var synthesizedEvents: [String] = []
        let service = FocusedTextPasteService(
            accessibility: accessibility,
            pasteboard: FakeTextPasteboard(),
            postCommandV: { _ in
                synthesizedEvents.append("command-v")
                return true
            },
            postSpace: { _ in
                synthesizedEvents.append("space")
                return true
            },
            postDeleteBackward: { _ in
                synthesizedEvents.append("delete")
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
        let outcome = try await service.deliver(content, to: capture)

        #expect(
            outcome == .accessibilityInsertionUnverified(
                "macOS acknowledged the context insertion, but the editor "
                    + "did not expose the exact inserted value for verification."
            )
        )
        #expect(accessibility.value == content)
        #expect(synthesizedEvents.isEmpty)
    }

    @Test
    @MainActor
    func floatingOpenCodeTrailingLineFeedDeletesChromiumsStructuralSentinel() async throws {
        let content = "# Routed workspace context 😀\n"
        let accessibility = FakeAccessibilityElementClient()
        accessibility.bundleIdentifier = "ai.opencode.desktop"
        accessibility.role = kAXTextAreaRole as String
        accessibility.descriptionText = "Ask anything..."
        accessibility.value = "\n"
        accessibility.serializesTypedSpaceBeforeTrailingLineFeed = true
        accessibility.settableAttributes = [
            kAXFocusedAttribute as String,
            kAXSelectedTextAttribute as String,
            kAXSelectedTextRangeAttribute as String,
            kAXValueAttribute as String,
        ]
        let projectDirectory = FileManager.default.temporaryDirectory.path
        accessibility.exposeOpenCodeWindow(
            children: [accessibility.element],
            projectDirectory: projectDirectory,
            newSessionIsCurrent: true
        )
        var openedURLCount = 0
        var synthesizedEvents: [String] = []
        let service = FocusedTextPasteService(
            accessibility: accessibility,
            pasteboard: FakeTextPasteboard(),
            postCommandV: { _ in
                synthesizedEvents.append("command-v")
                return true
            },
            postSpace: { _ in
                synthesizedEvents.append("space")
                return accessibility.typeSpaceInFocusedElement()
            },
            postDeleteBackward: { _ in
                synthesizedEvents.append("delete")
                return accessibility.deleteSelectionInFocusedElement()
            },
            openURL: { _, _ in
                openedURLCount += 1
                return true
            },
            validateOpenCodeApplication: { _ in true }
        )

        let outcome = try await service.deliver(
            content,
            to: service.captureTarget(),
            openCodeProjectDirectory: projectDirectory
        )

        #expect(outcome == .insertedIntoVerifiedEmptyComposerWithInputSync)
        #expect(accessibility.value == content)
        #expect(synthesizedEvents == ["space", "delete"])
        #expect(accessibility.selectedText == nil)
        #expect(openedURLCount == 0)
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

private func realisticRetainedOpenCodeContext(
    utf16Length: Int,
    heading: String
) -> String {
    let separator = "\n\n"
    let line = "- verified Daemonstate workspace evidence\n"
    let finalLineFeed = "\n"
    let fixedLength = heading.utf16.count
        + separator.utf16.count
        + finalLineFeed.utf16.count
    precondition(utf16Length >= fixedLength)
    let available = utf16Length - fixedLength
    let repetitions = available / line.utf16.count
    let base = heading + separator + String(repeating: line, count: repetitions)
    return base + String(
        repeating: "x",
        count: utf16Length - base.utf16.count - finalLineFeed.utf16.count
    ) + finalLineFeed
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

    func simulateExternalChange(_ string: String) {
        content = string
        changeCount += 1
    }
}

@MainActor
private final class FakeAccessibilityElementClient: AccessibilityElementClient {
    let element = AXUIElementCreateSystemWide()
    let secondaryElement = AXUIElementCreateApplication(42_425)
    let tertiaryElement = AXUIElementCreateApplication(42_428)
    let nestedContainerElement = AXUIElementCreateApplication(42_427)
    let projectEvidenceElement = AXUIElementCreateApplication(42_429)
    let newSessionEvidenceElement = AXUIElementCreateApplication(42_430)
    let projectsAndSessionsRegionElement = AXUIElementCreateApplication(42_432)
    let localProjectEvidenceElement = AXUIElementCreateApplication(42_433)
    let localNewSessionButtonElement = AXUIElementCreateApplication(42_434)
    let localWorkspaceContainerElement = AXUIElementCreateApplication(42_435)
    let localActiveSessionLinkElement = AXUIElementCreateApplication(42_436)
    let savedSessionContainerElement = AXUIElementCreateApplication(42_437)
    let savedSessionTitleElement = AXUIElementCreateApplication(42_438)
    let orphanCurrentSessionLinkElement = AXUIElementCreateApplication(42_439)
    let localProjectNameElement = AXUIElementCreateApplication(42_440)
    let localProjectOptionsElement = AXUIElementCreateApplication(42_441)
    let localNewSessionGroupElement = AXUIElementCreateApplication(42_442)
    let compactNewSessionTitleElement = AXUIElementCreateApplication(42_443)
    let compactProjectPathContainerElement = AXUIElementCreateApplication(42_444)
    let compactProjectDirectoryElement = AXUIElementCreateApplication(42_445)
    let compactProjectNameElement = AXUIElementCreateApplication(42_446)
    private let applicationAXElement = AXUIElementCreateApplication(42_424)
    private let focusedWindowElement = AXUIElementCreateApplication(42_426)
    private let alternateFocusedWindowElement = AXUIElementCreateApplication(42_431)
    private var applicationWindowsOverride: [AXUIElement]?
    let processIdentifier: pid_t = 42_424
    var trusted = true
    var frontmostPID: pid_t? = 42_424
    var frontmostPIDSequence: [pid_t?] = []
    var bundleIdentifier: String? = "com.openai.codex"
    var bundlePath: String?
    var hasFocusedElement = true
    var focusedElementMatchesCapture = true
    var focusedWindowRole: String? = kAXWindowRole as String
    var alternateFocusedWindowRole: String? = kAXWindowRole as String
    var role: String?
    var secondaryRole: String?
    var tertiaryRole: String?
    var descriptionText: String?
    var secondaryDescriptionText: String?
    var tertiaryDescriptionText: String?
    var domClasses: [String]?
    var secondaryDOMClasses: [String]?
    var tertiaryDOMClasses: [String]?
    var subrole: String?
    var enabled: Bool? = true
    var value: String?
    var secondaryValue: String?
    var tertiaryValue: String?
    var projectEvidenceValue: String?
    var newSessionIsCurrent = false
    var newSessionURLValue: String?
    var newSessionDOMClasses: [String] = []
    var localProjectEvidenceValue: String?
    var localProjectNameValue: String?
    var localActiveSessionTitle: String?
    var savedSessionTitleValue: String?
    var compactProjectDirectoryValue: String?
    var compactProjectNameValue: String?
    var selectedText: String?
    var selectedTextRange: CFRange?
    var reportedSelectedTextRange: CFRange?
    var reportedSelectedTextRanges: [CFRange?] = []
    var serializesTypedSpaceBeforeTrailingLineFeed = false
    var reflectSuccessfulInsertionInValue = false
    var settableAttributes: Set<String> = []
    var setResults: [AXError] = [.success]
    var performActionResults: [AXError] = [.success]
    var performActionCallback: ((String, AXUIElement, AXError) -> Void)?
    var successfulValueSetCallback: ((AXUIElement, String) -> Void)?
    var secondaryValueReadCallback: ((Int, String?) -> Void)?
    var selectedTextReadCallback: ((String?) -> Void)?
    var focusedWindowChildren: [AXUIElement] = []
    var nestedContainerChildren: [AXUIElement] = []
    var elementChildren: [AXUIElement: [AXUIElement]] = [:]
    var elementParents: [AXUIElement: AXUIElement] = [:]
    var explicitlyUnparentedElements = Set<AXUIElement>()
    var elementFrames: [AXUIElement: CGRect] = [:]
    var elementsWithoutFrames = Set<AXUIElement>()
    var hiddenElements = Set<AXUIElement>()
    var invisibleElements = Set<AXUIElement>()
    var elementWindowOwners: [AXUIElement: AXUIElement] = [:]
    var elementsWithoutWindowOwners = Set<AXUIElement>()
    var hitTestInvisibleElements = Set<AXUIElement>()
    private var focusedElementOverride: AXUIElement?
    private var focusedWindowOverride: AXUIElement?
    private(set) var insertedValues: [String] = []
    private(set) var performedActions: [
        (action: String, element: AXUIElement)
    ] = []
    private(set) var performedAttributeMutations: [
        (attribute: String, element: AXUIElement)
    ] = []
    private(set) var secondaryValueReadCount = 0

    func isTrusted(prompt: Bool) -> Bool {
        trusted
    }

    func frontmostApplication() -> FrontmostApplicationIdentity? {
        let observedPID = frontmostPIDSequence.isEmpty
            ? frontmostPID
            : frontmostPIDSequence.removeFirst()
        guard let observedPID else { return nil }
        let isConfiguredApplication = observedPID == processIdentifier
        return FrontmostApplicationIdentity(
            processIdentifier: observedPID,
            bundleIdentifier: isConfiguredApplication
                ? bundleIdentifier
                : "com.google.Chrome",
            bundlePath: isConfiguredApplication
                ? bundlePath ?? (
                bundleIdentifier == "ai.opencode.desktop"
                    ? "/Applications/OpenCode.app"
                    : "/Applications/Codex.app"
                )
                : "/Applications/Google Chrome.app"
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
        let name = attribute as String
        if name == kAXParentAttribute as String {
            if explicitlyUnparentedElements.contains(element) {
                return nil
            }
            if let parent = elementParents[element] {
                return parent
            }
            if let inferred = elementChildren.first(where: { _, children in
                children.contains(where: { CFEqual($0, element) })
            })?.key {
                return inferred
            }
            if nestedContainerChildren.contains(where: {
                CFEqual($0, element)
            }) {
                return nestedContainerElement
            }
            let activeWindow = focusedWindowOverride ?? focusedWindowElement
            let activeChildren = elementChildren[activeWindow]
                ?? focusedWindowChildren
            if (CFEqual(element, self.element) && activeChildren.isEmpty)
                || activeChildren.contains(where: {
                   CFEqual($0, element)
                }) {
                return activeWindow
            }
            return nil
        }
        if name == kAXWindowAttribute as String
            || name == "AXTopLevelUIElement"
        {
            if elementsWithoutWindowOwners.contains(element) {
                return nil
            }
            return elementWindowOwners[element]
                ?? (focusedWindowOverride ?? focusedWindowElement)
        }
        guard name == kAXFocusedWindowAttribute as String,
              CFEqual(element, applicationAXElement)
        else {
            return nil
        }
        return focusedWindowOverride ?? focusedWindowElement
    }

    func elementArrayAttribute(
        _ attribute: CFString,
        from element: AXUIElement,
        maximumCount: Int
    ) -> [AXUIElement]? {
        if attribute as String == kAXWindowsAttribute as String,
           CFEqual(element, applicationAXElement)
        {
            let windows = applicationWindowsOverride
                ?? [focusedWindowOverride ?? focusedWindowElement]
            guard windows.count <= maximumCount else { return nil }
            return windows
        }
        guard attribute as String == kAXChildrenAttribute as String else {
            return []
        }
        if let children = elementChildren[element] {
            guard children.count <= maximumCount else { return nil }
            return children
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
        let name = attribute as String
        if name == kAXRoleAttribute as String {
            if CFEqual(element, applicationAXElement) {
                return kAXApplicationRole as String
            }
            if CFEqual(element, focusedWindowElement) {
                return focusedWindowRole
            }
            if CFEqual(element, alternateFocusedWindowElement) {
                return alternateFocusedWindowRole
            }
        }
        if CFEqual(element, projectEvidenceElement) {
            if name == kAXRoleAttribute as String {
                return kAXStaticTextRole as String
            }
            return name == kAXValueAttribute as String
                ? projectEvidenceValue
                : nil
        }
        if CFEqual(element, newSessionEvidenceElement) {
            if name == kAXRoleAttribute as String {
                return "AXLink"
            }
            if name == kAXDescriptionAttribute as String {
                return "New session"
            }
            if name == "AXARIACurrent" {
                return newSessionIsCurrent ? "page" : nil
            }
            if name == kAXURLAttribute as String {
                return newSessionURLValue
            }
            return nil
        }
        if CFEqual(element, projectsAndSessionsRegionElement) {
            if name == kAXRoleAttribute as String {
                return kAXGroupRole as String
            }
            if name == kAXDescriptionAttribute as String {
                return "Projects and sessions"
            }
            return nil
        }
        if CFEqual(element, compactNewSessionTitleElement) {
            if name == kAXRoleAttribute as String {
                return kAXStaticTextRole as String
            }
            return name == kAXValueAttribute as String ? "New session" : nil
        }
        if CFEqual(element, compactProjectPathContainerElement) {
            return name == kAXRoleAttribute as String
                ? kAXGroupRole as String
                : nil
        }
        if CFEqual(element, compactProjectDirectoryElement) {
            if name == kAXRoleAttribute as String {
                return kAXStaticTextRole as String
            }
            return name == kAXValueAttribute as String
                ? compactProjectDirectoryValue
                : nil
        }
        if CFEqual(element, compactProjectNameElement) {
            if name == kAXRoleAttribute as String {
                return kAXStaticTextRole as String
            }
            return name == kAXValueAttribute as String
                ? compactProjectNameValue
                : nil
        }
        if CFEqual(element, localWorkspaceContainerElement) {
            return name == kAXRoleAttribute as String
                ? kAXGroupRole as String
                : nil
        }
        if CFEqual(element, localProjectNameElement) {
            if name == kAXRoleAttribute as String {
                return kAXStaticTextRole as String
            }
            return name == kAXValueAttribute as String
                ? localProjectNameValue
                : nil
        }
        if CFEqual(element, localProjectEvidenceElement) {
            if name == kAXRoleAttribute as String {
                return kAXStaticTextRole as String
            }
            return name == kAXValueAttribute as String
                ? localProjectEvidenceValue
                : nil
        }
        if CFEqual(element, localNewSessionButtonElement) {
            if name == kAXRoleAttribute as String {
                return kAXButtonRole as String
            }
            if name == kAXTitleAttribute as String {
                return "New session"
            }
            return nil
        }
        if CFEqual(element, localProjectOptionsElement) {
            if name == kAXRoleAttribute as String {
                return kAXPopUpButtonRole as String
            }
            if name == kAXTitleAttribute as String {
                return "More options"
            }
            return nil
        }
        if CFEqual(element, localNewSessionGroupElement) {
            return name == kAXRoleAttribute as String
                ? kAXGroupRole as String
                : nil
        }
        if CFEqual(element, localActiveSessionLinkElement) {
            if name == kAXRoleAttribute as String {
                return "AXLink"
            }
            if name == kAXTitleAttribute as String {
                return localActiveSessionTitle
            }
            if name == "AXARIACurrent" {
                return localActiveSessionTitle == nil ? nil : "page"
            }
            return nil
        }
        if CFEqual(element, savedSessionContainerElement) {
            return name == kAXRoleAttribute as String
                ? kAXGroupRole as String
                : nil
        }
        if CFEqual(element, savedSessionTitleElement) {
            if name == kAXRoleAttribute as String {
                return kAXStaticTextRole as String
            }
            return name == kAXValueAttribute as String
                ? savedSessionTitleValue
                : nil
        }
        if CFEqual(element, orphanCurrentSessionLinkElement) {
            if name == kAXRoleAttribute as String {
                return "AXLink"
            }
            if name == kAXTitleAttribute as String {
                return "Unparented stale session"
            }
            if name == "AXARIACurrent" {
                return "page"
            }
            return nil
        }
        let isSecondary = CFEqual(element, secondaryElement)
        let isTertiary = CFEqual(element, tertiaryElement)
        guard isSecondary || isTertiary || CFEqual(element, self.element)
        else {
            return nil
        }
        if name == kAXRoleAttribute as String {
            return isSecondary
                ? secondaryRole
                : (isTertiary ? tertiaryRole : role)
        }
        if name == kAXSubroleAttribute as String {
            return subrole
        }
        if name == kAXDescriptionAttribute as String {
            return isSecondary
                ? secondaryDescriptionText
                : (isTertiary ? tertiaryDescriptionText : descriptionText)
        }
        if name == kAXValueAttribute as String {
            if isSecondary {
                let result = secondaryValue
                secondaryValueReadCount += 1
                secondaryValueReadCallback?(secondaryValueReadCount, result)
                return result
            }
            return isTertiary ? tertiaryValue : value
        }
        if name == kAXSelectedTextAttribute as String {
            let result = selectedText
            selectedTextReadCallback?(result)
            return result
        }
        return nil
    }

    func stringArrayAttribute(
        _ attribute: CFString,
        from element: AXUIElement
    ) -> [String]? {
        guard attribute as String == "AXDOMClassList" else { return nil }
        if CFEqual(element, newSessionEvidenceElement) {
            return newSessionDOMClasses
        }
        if CFEqual(element, localProjectEvidenceElement)
            || CFEqual(element, localProjectNameElement)
            || CFEqual(element, savedSessionTitleElement)
        {
            return []
        }
        if CFEqual(element, secondaryElement) {
            return secondaryDOMClasses
        }
        if CFEqual(element, tertiaryElement) {
            return tertiaryDOMClasses
        }
        return CFEqual(element, self.element) ? domClasses : nil
    }

    func boolAttribute(
        _ attribute: CFString,
        from element: AXUIElement
    ) -> Bool? {
        if attribute as String == "AXHidden" {
            return hiddenElements.contains(element) ? true : nil
        }
        if attribute as String == "AXVisible" {
            return invisibleElements.contains(element) ? false : nil
        }
        guard CFEqual(element, self.element)
                || CFEqual(element, secondaryElement)
                || CFEqual(element, tertiaryElement)
        else {
            return nil
        }
        return attribute as String == kAXEnabledAttribute as String ? enabled : nil
    }

    func frame(of element: AXUIElement) -> CGRect? {
        guard !elementsWithoutFrames.contains(element) else { return nil }
        if let frame = elementFrames[element] {
            return frame
        }
        if CFEqual(element, focusedWindowElement)
            || CFEqual(element, alternateFocusedWindowElement)
        {
            return CGRect(x: 0, y: 0, width: 1_200, height: 900)
        }
        return CGRect(x: 160, y: 620, width: 880, height: 140)
    }

    func elementIsHitTestVisible(
        _ element: AXUIElement,
        at point: CGPoint,
        processIdentifier: pid_t
    ) -> Bool {
        !hitTestInvisibleElements.contains(element)
    }

    func rangeAttribute(
        _ attribute: CFString,
        from element: AXUIElement
    ) -> CFRange? {
        guard attribute as String == kAXSelectedTextRangeAttribute as String,
              CFEqual(element, self.element)
                || CFEqual(element, secondaryElement)
                || CFEqual(element, tertiaryElement)
        else {
            return nil
        }
        if !reportedSelectedTextRanges.isEmpty {
            return reportedSelectedTextRanges.removeFirst()
        }
        return reportedSelectedTextRange ?? selectedTextRange
    }

    func isAttributeSettable(
        _ attribute: CFString,
        on element: AXUIElement
    ) -> Bool {
        (
            CFEqual(element, self.element)
                || CFEqual(element, secondaryElement)
                || CFEqual(element, tertiaryElement)
        )
            && settableAttributes.contains(attribute as String)
    }

    func setAttribute(
        _ attribute: CFString,
        to value: CFTypeRef,
        on element: AXUIElement
    ) -> AXError {
        let name = attribute as String
        performedAttributeMutations.append((attribute: name, element: element))
        if name == kAXFocusedAttribute as String {
            focusedElementOverride = element
            return .success
        }
        if name == kAXSelectedTextRangeAttribute as String {
            let source = CFEqual(element, secondaryElement)
                ? secondaryValue
                : (CFEqual(element, tertiaryElement) ? tertiaryValue : self.value)
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
            selectedTextRange = range
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
                } else if CFEqual(element, tertiaryElement) {
                    tertiaryValue = string
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
            } else if CFEqual(element, tertiaryElement) {
                tertiaryValue = string
            } else {
                self.value = string
            }
            successfulValueSetCallback?(element, string)
        }
        return result
    }

    func performAction(
        _ action: CFString,
        on element: AXUIElement
    ) -> AXError {
        let actionName = action as String
        let result = performActionResults.isEmpty
            ? .success
            : performActionResults.removeFirst()
        performedActions.append((action: actionName, element: element))
        performActionCallback?(actionName, element, result)
        return result
    }

    func elementsAreEqual(_ lhs: AXUIElement, _ rhs: AXUIElement) -> Bool {
        focusedElementMatchesCapture && CFEqual(lhs, rhs)
    }

    func focusedElementMatches(_ expected: AXUIElement) -> Bool {
        guard let focused = focusedElement() else { return false }
        return CFEqual(focused, expected)
    }

    func setFocusedElement(_ element: AXUIElement?) {
        focusedElementOverride = element
    }

    func exposeAuxiliaryWindowAlongsideFocusedWindow() {
        applicationWindowsOverride = [
            alternateFocusedWindowElement,
            focusedWindowOverride ?? focusedWindowElement,
        ]
    }

    func exposeOnlyWrongApplicationWindow() {
        applicationWindowsOverride = [alternateFocusedWindowElement]
    }

    func exposeNoApplicationWindows() {
        applicationWindowsOverride = []
    }

    func typeSpaceInFocusedElement() -> Bool {
        guard let element = focusedElement(),
              var source = valueForEditableElement(element),
              let selectedTextRange,
              selectedTextRange.location >= 0,
              selectedTextRange.length >= 0,
              selectedTextRange.location + selectedTextRange.length
                <= source.utf16.count
        else {
            return false
        }
        var replacementRange = NSRange(
            location: selectedTextRange.location,
            length: selectedTextRange.length
        )
        if serializesTypedSpaceBeforeTrailingLineFeed,
           replacementRange.length == 0,
           replacementRange.location == source.utf16.count,
           source.hasSuffix("\n")
        {
            replacementRange.location -= 1
        }
        let mutable = NSMutableString(string: source)
        mutable.replaceCharacters(in: replacementRange, with: " ")
        source = mutable as String
        setValue(source, forEditableElement: element)
        self.selectedTextRange = CFRange(
            location: replacementRange.location + 1,
            length: 0
        )
        selectedText = nil
        return true
    }

    func deleteSelectionInFocusedElement() -> Bool {
        guard let element = focusedElement(),
              let source = valueForEditableElement(element),
              let selectedTextRange,
              selectedTextRange.location >= 0,
              selectedTextRange.length > 0,
              selectedTextRange.location + selectedTextRange.length
                <= source.utf16.count
        else {
            return false
        }
        let replacementRange = NSRange(
            location: selectedTextRange.location,
            length: selectedTextRange.length
        )
        let mutable = NSMutableString(string: source)
        mutable.replaceCharacters(in: replacementRange, with: "")
        setValue(mutable as String, forEditableElement: element)
        self.selectedTextRange = CFRange(
            location: replacementRange.location,
            length: 0
        )
        selectedText = nil
        return true
    }

    private func valueForEditableElement(_ element: AXUIElement) -> String? {
        if CFEqual(element, secondaryElement) { return secondaryValue }
        if CFEqual(element, tertiaryElement) { return tertiaryValue }
        return CFEqual(element, self.element) ? value : nil
    }

    private func setValue(
        _ value: String,
        forEditableElement element: AXUIElement
    ) {
        if CFEqual(element, secondaryElement) {
            secondaryValue = value
        } else if CFEqual(element, tertiaryElement) {
            tertiaryValue = value
        } else if CFEqual(element, self.element) {
            self.value = value
        }
    }

    func resetSecondaryValueReadObservation() {
        secondaryValueReadCount = 0
    }

    func exposeApplicationElementAsFocusedWindow() {
        elementChildren[applicationAXElement] = focusedWindowChildren
        for child in focusedWindowChildren {
            elementParents[child] = applicationAXElement
        }
        focusedWindowOverride = applicationAXElement
    }

    func exposeOpenCodeWindow(
        children: [AXUIElement],
        projectDirectory: String?,
        projectDisplay: String? = nil,
        newSessionIsCurrent: Bool,
        includeOrphanCurrentLink: Bool = false,
        inAlternateWindow: Bool = false
    ) {
        projectEvidenceValue = projectDisplay ?? projectDirectory
        self.newSessionIsCurrent = newSessionIsCurrent
        if let projectDirectory {
            let canonical = URL(
                fileURLWithPath: projectDirectory,
                isDirectory: true
            ).standardizedFileURL.resolvingSymlinksInPath().path
            let slug = Data(canonical.utf8).base64EncodedString()
                .replacingOccurrences(of: "+", with: "-")
                .replacingOccurrences(of: "/", with: "_")
                .replacingOccurrences(of: "=", with: "")
            newSessionURLValue = "https://opencode.invalid/\(slug)/session"
        } else {
            newSessionURLValue = nil
        }
        newSessionDOMClasses = [
            "flex",
            "items-center",
            "gap-2",
            "min-w-0",
            "w-full",
            "text-left",
            "focus:outline-none",
            "py-1",
            "active",
        ]
        var allChildren = children
        if projectEvidenceValue != nil {
            allChildren.append(projectEvidenceElement)
        }
        allChildren.append(newSessionEvidenceElement)
        if includeOrphanCurrentLink {
            allChildren.append(orphanCurrentSessionLinkElement)
        }
        if inAlternateWindow {
            elementChildren[alternateFocusedWindowElement] = allChildren
            for child in allChildren {
                elementParents[child] = alternateFocusedWindowElement
            }
            focusedWindowOverride = alternateFocusedWindowElement
        } else {
            focusedWindowChildren = allChildren
            for child in allChildren {
                elementParents[child] = focusedWindowElement
            }
            focusedWindowOverride = nil
        }
        if includeOrphanCurrentLink {
            elementParents.removeValue(
                forKey: orphanCurrentSessionLinkElement
            )
            explicitlyUnparentedElements.insert(
                orphanCurrentSessionLinkElement
            )
        }
    }

    func exposeOpenCodeLocalProjectWindow(
        children: [AXUIElement],
        projectDirectory: String,
        projectDisplay: String? = nil,
        projectName: String? = nil,
        activeSessionTitle: String? = nil,
        savedSessionTitle: String? = nil,
        includeOrphanCurrentLink: Bool = false,
        inAlternateWindow: Bool = false
    ) {
        localProjectEvidenceValue = projectDisplay ?? projectDirectory
        localProjectNameValue = projectName
            ?? URL(fileURLWithPath: projectDirectory).lastPathComponent
        localActiveSessionTitle = activeSessionTitle
            ?? (savedSessionTitle == nil ? nil : "Saved session")
        savedSessionTitleValue = savedSessionTitle
        newSessionIsCurrent = false
        newSessionURLValue = nil
        newSessionDOMClasses = []
        elementChildren[projectsAndSessionsRegionElement] = [
            localWorkspaceContainerElement,
        ]
        var localWorkspaceChildren = [
            localProjectNameElement,
            localProjectEvidenceElement,
            localProjectOptionsElement,
            localNewSessionGroupElement,
        ]
        elementChildren[localNewSessionGroupElement] = [
            localNewSessionButtonElement,
        ]
        if localActiveSessionTitle != nil {
            localWorkspaceChildren.append(localActiveSessionLinkElement)
            elementParents[localActiveSessionLinkElement] =
                localWorkspaceContainerElement
        }
        if savedSessionTitle != nil {
            elementChildren[localActiveSessionLinkElement] = [
                savedSessionContainerElement,
            ]
            elementChildren[savedSessionContainerElement] = [
                savedSessionTitleElement,
            ]
            elementParents[savedSessionContainerElement] =
                localActiveSessionLinkElement
            elementParents[savedSessionTitleElement] =
                savedSessionContainerElement
        } else {
            elementChildren[localActiveSessionLinkElement] = []
        }
        elementChildren[localWorkspaceContainerElement] =
            localWorkspaceChildren
        elementParents[localProjectNameElement] =
            localWorkspaceContainerElement
        elementParents[localProjectEvidenceElement] =
            localWorkspaceContainerElement
        elementParents[localProjectOptionsElement] =
            localWorkspaceContainerElement
        elementParents[localNewSessionGroupElement] =
            localWorkspaceContainerElement
        elementParents[localNewSessionButtonElement] =
            localNewSessionGroupElement
        elementParents[localWorkspaceContainerElement] =
            projectsAndSessionsRegionElement

        var allChildren = children + [projectsAndSessionsRegionElement]
        if includeOrphanCurrentLink {
            allChildren.append(orphanCurrentSessionLinkElement)
        }
        if inAlternateWindow {
            elementChildren[alternateFocusedWindowElement] = allChildren
            for child in allChildren {
                elementParents[child] = alternateFocusedWindowElement
            }
            focusedWindowOverride = alternateFocusedWindowElement
        } else {
            focusedWindowChildren = allChildren
            for child in allChildren {
                elementParents[child] = focusedWindowElement
            }
            focusedWindowOverride = nil
        }
        if includeOrphanCurrentLink {
            elementParents.removeValue(
                forKey: orphanCurrentSessionLinkElement
            )
            explicitlyUnparentedElements.insert(
                orphanCurrentSessionLinkElement
            )
        }
    }

    func exposeOpenCodeCompactNewSessionWindow(
        composer: AXUIElement,
        projectDirectory: String
    ) {
        let canonical = URL(
            fileURLWithPath: projectDirectory,
            isDirectory: true
        ).standardizedFileURL.resolvingSymlinksInPath()
        compactProjectDirectoryValue = canonical.deletingLastPathComponent().path
            + "/"
        compactProjectNameValue = canonical.lastPathComponent
        elementChildren[compactProjectPathContainerElement] = [
            compactProjectNameElement,
        ]
        elementParents[compactProjectNameElement] =
            compactProjectPathContainerElement
        focusedWindowChildren = [
            compactNewSessionTitleElement,
            compactProjectPathContainerElement,
            composer,
        ]
        elementParents[compactNewSessionTitleElement] = focusedWindowElement
        elementParents[compactProjectPathContainerElement] = focusedWindowElement
        elementParents[composer] = focusedWindowElement
        focusedWindowOverride = nil
    }
}
