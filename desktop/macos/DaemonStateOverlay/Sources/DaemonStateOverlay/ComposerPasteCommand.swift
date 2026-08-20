import AppKit
import Foundation

private let composerPasteSchema = "daemonstate.composer_paste.v1"
private let maximumComposerContextBytes = 1_048_576

enum ComposerTargetPolicy: String {
    case openCodeChatComposerV1 = "opencode-chat-composer-v1"
    case openCodeFocusedChatComposerV1 =
        "opencode-focused-chat-composer-v1"
}

struct ComposerPasteConfiguration {
    let expectedBundleIdentifiers: Set<String>
    let expectedBundlePath: String
    let focusTimeoutMilliseconds: Int
    let focusSettleMilliseconds: Int
    let routeGraceMilliseconds: Int
    let targetPolicy: ComposerTargetPolicy?
    let targetMarker: String?
    let expectedProjectDirectory: String?

    static func parse(arguments: [String]) -> ComposerPasteConfiguration? {
        guard arguments.contains("--paste-stdin") else { return nil }

        var expectedBundleIdentifiers = Set<String>()
        var expectedBundlePath: String?
        var focusTimeoutMilliseconds = 6_000
        var focusSettleMilliseconds = 550
        var routeGraceMilliseconds = 1_250
        var targetPolicy: ComposerTargetPolicy?
        var targetPolicyWasSupplied = false
        var targetMarker: String?
        var targetMarkerWasSupplied = false
        var expectedProjectDirectory: String?
        var expectedProjectDirectoryWasSupplied = false
        var index = 1
        while index < arguments.count {
            switch arguments[index] {
            case "--paste-stdin":
                index += 1
            case "--expected-bundle-id" where index + 1 < arguments.count:
                let value = arguments[index + 1].trimmingCharacters(
                    in: .whitespacesAndNewlines
                )
                if isSafeBundleIdentifier(value) {
                    expectedBundleIdentifiers.insert(value)
                }
                index += 2
            case "--expected-bundle-path" where index + 1 < arguments.count:
                let value = URL(fileURLWithPath: arguments[index + 1])
                    .standardizedFileURL.resolvingSymlinksInPath().path
                if value.hasPrefix("/") {
                    expectedBundlePath = value
                }
                index += 2
            case "--focus-timeout-ms" where index + 1 < arguments.count:
                if let value = Int(arguments[index + 1]) {
                    focusTimeoutMilliseconds = min(max(value, 500), 15_000)
                }
                index += 2
            case "--focus-settle-ms" where index + 1 < arguments.count:
                if let value = Int(arguments[index + 1]) {
                    focusSettleMilliseconds = min(max(value, 100), 2_000)
                }
                index += 2
            case "--route-grace-ms" where index + 1 < arguments.count:
                if let value = Int(arguments[index + 1]) {
                    routeGraceMilliseconds = min(max(value, 500), 5_000)
                }
                index += 2
            case "--target-policy" where index + 1 < arguments.count:
                targetPolicyWasSupplied = true
                targetPolicy = ComposerTargetPolicy(
                    rawValue: arguments[index + 1]
                )
                index += 2
            case "--target-marker" where index + 1 < arguments.count:
                targetMarkerWasSupplied = true
                let value = arguments[index + 1]
                if isSafeTargetMarker(value) {
                    targetMarker = value
                }
                index += 2
            case "--expected-project-directory" where index + 1 < arguments.count:
                expectedProjectDirectoryWasSupplied = true
                let value = URL(fileURLWithPath: arguments[index + 1])
                    .standardizedFileURL.resolvingSymlinksInPath().path
                var isDirectory: ObjCBool = false
                if value.hasPrefix("/"),
                   FileManager.default.fileExists(
                       atPath: value,
                       isDirectory: &isDirectory
                   ), isDirectory.boolValue
                {
                    expectedProjectDirectory = value
                }
                index += 2
            default:
                // overlay.sh may append its normal control token. Ignore
                // unrelated pairs; the one-shot mode never opens overlay IPC.
                index += 1
            }
        }
        guard !expectedBundleIdentifiers.isEmpty,
              let expectedBundlePath,
              targetPolicyWasSupplied == (targetPolicy != nil),
              targetMarkerWasSupplied == (targetMarker != nil)
        else {
            return nil
        }
        switch targetPolicy {
        case .openCodeChatComposerV1:
            guard targetMarker != nil,
                  expectedProjectDirectoryWasSupplied,
                  expectedProjectDirectory != nil,
                  expectedBundleIdentifiers == ["ai.opencode.desktop"]
            else {
                return nil
            }
        case .openCodeFocusedChatComposerV1:
            guard !targetMarkerWasSupplied,
                  targetMarker == nil,
                  !expectedProjectDirectoryWasSupplied,
                  expectedProjectDirectory == nil,
                  expectedBundleIdentifiers == ["ai.opencode.desktop"]
            else {
                return nil
            }
        case nil:
            guard targetMarker == nil,
                  !expectedProjectDirectoryWasSupplied,
                  expectedProjectDirectory == nil,
                  !expectedBundleIdentifiers.contains("ai.opencode.desktop")
            else {
                return nil
            }
        }
        return ComposerPasteConfiguration(
            expectedBundleIdentifiers: expectedBundleIdentifiers,
            expectedBundlePath: expectedBundlePath,
            focusTimeoutMilliseconds: focusTimeoutMilliseconds,
            focusSettleMilliseconds: focusSettleMilliseconds,
            routeGraceMilliseconds: routeGraceMilliseconds,
            targetPolicy: targetPolicy,
            targetMarker: targetMarker,
            expectedProjectDirectory: expectedProjectDirectory
        )
    }

    private static func isSafeBundleIdentifier(_ value: String) -> Bool {
        guard !value.isEmpty, value.count <= 255, value.contains(".") else {
            return false
        }
        return value.unicodeScalars.allSatisfy {
            CharacterSet.alphanumerics.contains($0)
                || $0 == "."
                || $0 == "-"
        }
    }

    private static func isSafeTargetMarker(_ value: String) -> Bool {
        guard (16...128).contains(value.count) else { return false }
        return value.unicodeScalars.allSatisfy {
            CharacterSet.alphanumerics.contains($0)
                || $0 == "-"
                || $0 == "_"
        }
    }
}

private struct ComposerPasteResult: Codable {
    let schemaVersion: String
    let code: String
    let message: String
    let action: String
    let expectedBundleIdentifiers: [String]
    let expectedBundlePath: String?
    let observedBundleIdentifier: String?
    let observedBundlePath: String?
    let openVerified: Bool
    let pasteRequested: Bool
    let pasteVerified: Bool
    let contextLoaded: Bool
    let pasteMethod: String?
    let executionStarted: Bool
    let targetPolicy: String?
    let targetKind: String?
    let targetIdentityVerified: Bool
    let markerReplaced: Bool

    private enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case code
        case message
        case action
        case expectedBundleIdentifiers = "expected_bundle_identifiers"
        case expectedBundlePath = "expected_bundle_path"
        case observedBundleIdentifier = "observed_bundle_identifier"
        case observedBundlePath = "observed_bundle_path"
        case openVerified = "open_verified"
        case pasteRequested = "paste_requested"
        case pasteVerified = "paste_verified"
        case contextLoaded = "context_loaded"
        case pasteMethod = "paste_method"
        case executionStarted = "execution_started"
        case targetPolicy = "target_policy"
        case targetKind = "target_kind"
        case targetIdentityVerified = "target_identity_verified"
        case markerReplaced = "marker_replaced"
    }
}

@MainActor
enum ComposerPasteCommand {
    static func isRequested(arguments: [String]) -> Bool {
        arguments.contains("--paste-stdin")
    }

    static func run(arguments: [String]) async -> Int32 {
        guard let configuration = ComposerPasteConfiguration.parse(
            arguments: arguments
        ) else {
            emit(
                result(
                    code: "desktop_paste_request_invalid",
                    message: "The native paste request is invalid.",
                    action: "Retry Continue from DaemonState.",
                    configuration: nil
                )
            )
            return 64
        }

        let input = readBoundedInput(
            from: FileHandle.standardInput,
            maximumBytes: maximumComposerContextBytes
        )
        guard input.count <= maximumComposerContextBytes else {
            emit(
                result(
                    code: "desktop_context_too_large",
                    message: "The continuation context exceeds the native 1 MiB paste limit.",
                    action: "Reduce the context selection, then retry Continue.",
                    configuration: configuration
                )
            )
            return 65
        }
        guard let content = String(data: input, encoding: .utf8),
              !content.isEmpty,
              !content.contains("\0")
        else {
            emit(
                result(
                    code: "desktop_prompt_empty",
                    message: "The native paste request contained no context.",
                    action: "Refresh the session context, then retry Continue.",
                    configuration: configuration
                )
            )
            return 65
        }

        let service = FocusedTextPasteService()
        if configuration.targetPolicy != nil,
           !service.openCodeApplicationSupportsVerifiedComposer(
               at: configuration.expectedBundlePath
           )
        {
            emit(
                result(
                    code: "desktop_app_version_unsupported",
                    message: (
                        "The installed OpenCode Desktop build has not been "
                            + "audited for safe focused-composer insertion."
                    ),
                    action: (
                        "Install OpenCode Desktop 1.18.18, then retry Continue."
                    ),
                    configuration: configuration
                )
            )
            return 69
        }
        let clock = ContinuousClock()
        let deadline = clock.now.advanced(
            by: .milliseconds(configuration.focusTimeoutMilliseconds)
        )
        var observedBundleIdentifier: String?
        var expectedProcessIdentifier: pid_t?
        var expectedAppStableSince: Date?
        var fallbackProcessIdentifier: pid_t?
        var fallbackStableSince: Date?
        let accessibility = SystemAccessibilityElementClient()

        while clock.now < deadline {
            let frontmost = NSWorkspace.shared.frontmostApplication
            observedBundleIdentifier = frontmost?.bundleIdentifier
            let expectedAppIsFrontmost = (
                observedBundleIdentifier.map(
                    configuration.expectedBundleIdentifiers.contains
                ) ?? false
            ) && frontmostApplicationMatchesPath(
                frontmost,
                expectedPath: configuration.expectedBundlePath
            )
            if expectedAppIsFrontmost,
               let processIdentifier = frontmost?.processIdentifier
            {
                if expectedProcessIdentifier != processIdentifier {
                    expectedProcessIdentifier = processIdentifier
                    expectedAppStableSince = Date()
                }
            } else {
                expectedProcessIdentifier = nil
                expectedAppStableSince = nil
            }
            if expectedAppIsFrontmost,
               accessibility.focusedElement() == nil,
               let processIdentifier = frontmost?.processIdentifier
            {
                if fallbackProcessIdentifier != processIdentifier {
                    fallbackProcessIdentifier = processIdentifier
                    fallbackStableSince = Date()
                }
            } else {
                // Any app/PID change or any AX-focused element invalidates the
                // app-level fallback. A new nil-focus stability window may be
                // established on a later poll.
                fallbackProcessIdentifier = nil
                fallbackStableSince = nil
            }

            if configuration.targetMarker != nil {
                guard let expectedAppStableSince,
                      Date().timeIntervalSince(expectedAppStableSince)
                        >= Double(configuration.routeGraceMilliseconds) / 1_000
                else {
                    try? await Task.sleep(nanoseconds: 100_000_000)
                    continue
                }
            }

            let capture = service.captureTarget(
                expectedBundleIdentifiers: configuration.expectedBundleIdentifiers,
                allowNonEditableApplicationFallback: false,
                allowMissingFocusedElementFallback: false,
                requireExactInsertionReadback: true,
                requireFocusedEmptyOpenCodeComposer: (
                    configuration.targetPolicy
                        == .openCodeFocusedChatComposerV1
                ),
                discoverEditableWithExactValue: configuration.targetMarker,
                attestingOpenCodeProjectDirectory: (
                    configuration.expectedProjectDirectory
                ),
                discoveryDeadline: deadline
            )
            switch capture {
            case .accessibilityUnavailable:
                service.requestAccessibilityPermission()
                emit(
                    result(
                        code: "desktop_accessibility_permission_required",
                        message: (
                            "DaemonState needs macOS Accessibility access to "
                            + "paste into the selected AI desktop app. The full "
                            + "context remains on the clipboard."
                        ),
                        action: (
                            "Allow DaemonStateOverlay in System Settings > "
                            + "Privacy & Security > Accessibility, then retry Continue."
                        ),
                        configuration: configuration,
                        observedBundleIdentifier: observedBundleIdentifier,
                        openVerified: expectedAppIsFrontmost
                    )
                )
                return 77
            case .editable:
                // Generic providers require a stable empty editor. OpenCode's
                // focused-composer policy additionally requires one unique,
                // visible normal chat composer and exact input-state readback.
                if let expectedAppStableSince,
                   Date().timeIntervalSince(expectedAppStableSince)
                    >= Double(configuration.routeGraceMilliseconds) / 1_000
                {
                    let expectedContentIsPresent = if let targetMarker = (
                        configuration.targetMarker
                    ) {
                        service.editableTargetHasExactContent(
                            capture,
                            expected: targetMarker
                        )
                    } else {
                        service.editableTargetContentState(capture) == .empty
                    }
                    if !expectedContentIsPresent {
                        try? await Task.sleep(nanoseconds: 100_000_000)
                        continue
                    }
                    try? await Task.sleep(
                        nanoseconds: UInt64(
                            configuration.focusSettleMilliseconds
                        ) * 1_000_000
                    )
                    let settledFrontmost = NSWorkspace.shared
                        .frontmostApplication
                    let settledCapture = service.captureTarget(
                        expectedBundleIdentifiers: (
                            configuration.expectedBundleIdentifiers
                        ),
                        allowNonEditableApplicationFallback: false,
                        allowMissingFocusedElementFallback: false,
                        requireExactInsertionReadback: true,
                        requireFocusedEmptyOpenCodeComposer: (
                            configuration.targetPolicy
                                == .openCodeFocusedChatComposerV1
                        ),
                        discoverEditableWithExactValue: (
                            configuration.targetMarker
                        ),
                        attestingOpenCodeProjectDirectory: (
                            configuration.expectedProjectDirectory
                        ),
                        discoveryDeadline: deadline
                    )
                    let settledExpectedContentIsPresent = if let targetMarker = (
                        configuration.targetMarker
                    ) {
                        service.editableTargetHasExactContent(
                            settledCapture,
                            expected: targetMarker
                        )
                    } else {
                        service.editableTargetContentState(settledCapture)
                            == .empty
                    }
                    if settledFrontmost?.processIdentifier
                            == expectedProcessIdentifier,
                       service.capturesSameEditableTarget(
                           capture,
                           settledCapture
                       ),
                       settledExpectedContentIsPresent
                    {
                        return await deliver(
                            content,
                            to: settledCapture,
                            with: service,
                            configuration: configuration
                        )
                    }
                    continue
                }
                try? await Task.sleep(nanoseconds: 100_000_000)
            case .application:
                try? await Task.sleep(nanoseconds: 100_000_000)
            case .openCodeNewComposer, .copyOnly, .unavailable:
                try? await Task.sleep(nanoseconds: 100_000_000)
            }
        }

        let frontmost = NSWorkspace.shared.frontmostApplication
        observedBundleIdentifier = frontmost?.bundleIdentifier
        let expectedAppIsFrontmost = (
            observedBundleIdentifier.map(
                configuration.expectedBundleIdentifiers.contains
            ) ?? false
        ) && frontmostApplicationMatchesPath(
            frontmost,
            expectedPath: configuration.expectedBundlePath
        )
        let minimumStableInterval = Double(
            configuration.focusSettleMilliseconds
        ) / 1_000
        if configuration.targetPolicy == nil,
           expectedAppIsFrontmost,
           accessibility.focusedElement() == nil,
           let processIdentifier = frontmost?.processIdentifier,
           fallbackProcessIdentifier == processIdentifier,
           let fallbackStableSince,
           Date().timeIntervalSince(fallbackStableSince) >= minimumStableInterval
        {
            let fallbackApplicationCapture = service.captureTarget(
                expectedBundleIdentifiers: configuration.expectedBundleIdentifiers,
                allowNonEditableApplicationFallback: false,
                allowMissingFocusedElementFallback: true,
                requireMissingFocusedElementForApplicationPaste: true
            )
            guard case .application = fallbackApplicationCapture else {
                return composerFocusFailure(
                    configuration: configuration,
                    observedBundleIdentifier: observedBundleIdentifier,
                    openVerified: true
                )
            }
            return await deliver(
                content,
                to: fallbackApplicationCapture,
                with: service,
                configuration: configuration
            )
        }
        return composerFocusFailure(
            configuration: configuration,
            observedBundleIdentifier: observedBundleIdentifier,
            openVerified: expectedAppIsFrontmost
        )
    }

    private static func deliver(
        _ content: String,
        to capture: FocusedTextPasteService.TargetCapture,
        with service: FocusedTextPasteService,
        configuration: ComposerPasteConfiguration
    ) async -> Int32 {
        let frontmostApplication = NSWorkspace.shared.frontmostApplication
        let observedBundleIdentifier = frontmostApplication?.bundleIdentifier
        let openVerified = (
            observedBundleIdentifier.map(
                configuration.expectedBundleIdentifiers.contains
            ) ?? false
        ) && frontmostApplicationMatchesPath(
            frontmostApplication,
            expectedPath: configuration.expectedBundlePath
        )
        guard openVerified else {
            emit(
                result(
                    code: "desktop_composer_focus_unverified",
                    message: "The selected AI desktop app lost focus before paste. The full context remains on the clipboard.",
                    action: "Return to the selected app, then retry Continue.",
                    configuration: configuration,
                    observedBundleIdentifier: observedBundleIdentifier
                )
            )
            return 78
        }

        do {
            let outcome = try await service.deliver(content, to: capture)
            switch outcome {
            case .alreadyPresentInVerifiedOpenCodeComposer:
                // This outcome belongs only to the interactive floating
                // workflow. One-shot Continue must still prove that its exact
                // provider marker was replaced during this invocation.
                emit(
                    result(
                        code: "desktop_context_insertion_unverified",
                        message: "The native helper reported content already present in an OpenCode draft. No marker replacement was proven.",
                        action: "Inspect the OpenCode draft before retrying Continue.",
                        configuration: configuration,
                        observedBundleIdentifier: observedBundleIdentifier,
                        openVerified: true
                    )
                )
                return 79
            case .insertedIntoVerifiedEmptyComposerWithInputSync:
                guard configuration.targetPolicy
                        == .openCodeFocusedChatComposerV1
                else {
                    emit(
                        result(
                            code: "desktop_context_insertion_unverified",
                            message: "The native helper reported an unexpected empty-composer insertion.",
                            action: "Inspect the OpenCode draft before retrying Continue.",
                            configuration: configuration,
                            observedBundleIdentifier: observedBundleIdentifier,
                            openVerified: true
                        )
                    )
                    return 79
                }
                emit(
                    result(
                        code: "desktop_context_inserted",
                        message: "The complete context was inserted into the verified focused OpenCode chat composer and its input state was synchronized. Exact readback succeeded and nothing was submitted.",
                        action: "Review the draft, then submit it when ready.",
                        configuration: configuration,
                        observedBundleIdentifier: observedBundleIdentifier,
                        openVerified: true,
                        pasteRequested: true,
                        pasteVerified: true,
                        pasteMethod: "accessibility_verified_input_sync",
                        targetIdentityVerified: true,
                        markerReplaced: false
                    )
                )
                return 0
            case .markerReplacedWithVerifiedInputSync:
                guard configuration.targetPolicy == .openCodeChatComposerV1 else {
                    emit(
                        result(
                            code: "desktop_context_insertion_unverified",
                            message: "The native helper reported an unexpected marker replacement. No second paste was attempted.",
                            action: "Inspect the selected app's draft before retrying Continue.",
                            configuration: configuration,
                            observedBundleIdentifier: observedBundleIdentifier,
                            openVerified: true
                        )
                    )
                    return 79
                }
                emit(
                    result(
                        code: "desktop_context_inserted",
                        message: "The complete context replaced the verified OpenCode chat-composer marker and its input state was synchronized. Exact readback succeeded and nothing was submitted.",
                        action: "Review the draft, then submit it when ready.",
                        configuration: configuration,
                        observedBundleIdentifier: observedBundleIdentifier,
                        openVerified: true,
                        pasteRequested: true,
                        pasteVerified: true,
                        pasteMethod: "accessibility_verified_input_sync",
                        targetIdentityVerified: true,
                        markerReplaced: true
                    )
                )
                return 0
            case .insertedWithAccessibility:
                guard configuration.targetPolicy == nil else {
                    emit(
                        result(
                            code: "desktop_context_insertion_unverified",
                            message: "OpenCode's composer marker was not proven replaced. No second paste was attempted.",
                            action: "Inspect the OpenCode draft before retrying Continue.",
                            configuration: configuration,
                            observedBundleIdentifier: observedBundleIdentifier,
                            openVerified: true
                        )
                    )
                    return 79
                }
                emit(
                    result(
                        code: "desktop_context_inserted",
                        message: "The complete context was inserted into the selected provider app's focused empty editor. Nothing was submitted.",
                        action: "Review the draft, then submit it when ready.",
                        configuration: configuration,
                        observedBundleIdentifier: observedBundleIdentifier,
                        openVerified: true,
                        pasteRequested: true,
                        pasteVerified: true,
                        pasteMethod: "accessibility_insert"
                    )
                )
                return 0
            case .commandVDispatched:
                if configuration.targetPolicy != nil {
                    emit(
                        result(
                            code: "desktop_composer_focus_unverified",
                            message: "OpenCode's chat composer identity could not be verified for a safe replacement. The full context remains on the clipboard.",
                            action: "Open a normal OpenCode chat composer, then retry Continue.",
                            configuration: configuration,
                            observedBundleIdentifier: observedBundleIdentifier,
                            openVerified: true
                        )
                    )
                    return 79
                }
                emit(
                    result(
                        code: "desktop_paste_command_dispatched",
                        message: "A paste command was sent after the selected provider app remained focused, but its editor contents could not be read back. Nothing was submitted.",
                        action: "Verify the complete draft before submitting it.",
                        configuration: configuration,
                        observedBundleIdentifier: observedBundleIdentifier,
                        openVerified: true,
                        pasteRequested: true,
                        pasteVerified: false,
                        pasteMethod: "command_v"
                    )
                )
                return 0
            case let .accessibilityInsertionUnverified(message):
                emit(
                    result(
                        code: "desktop_context_insertion_unverified",
                        message: "\(message) No second paste was attempted.",
                        action: "Inspect the selected app's draft before retrying Continue.",
                        configuration: configuration,
                        observedBundleIdentifier: observedBundleIdentifier,
                        openVerified: true
                    )
                )
                return 79
            case let .notPasted(message):
                emit(
                    result(
                        code: "desktop_paste_not_requested",
                        message: "\(message) The full context remains on the clipboard.",
                        action: "Focus the selected app's composer, then retry Continue.",
                        configuration: configuration,
                        observedBundleIdentifier: observedBundleIdentifier,
                        openVerified: true
                    )
                )
                return 79
            }
        } catch {
            emit(
                result(
                    code: "desktop_paste_failed",
                    message: "\(error.localizedDescription) The full context remains on the clipboard.",
                    action: "Focus the selected app's composer, then retry Continue.",
                    configuration: configuration,
                    observedBundleIdentifier: observedBundleIdentifier,
                    openVerified: true
                )
            )
            return 79
        }
    }

    private static func result(
        code: String,
        message: String,
        action: String,
        configuration: ComposerPasteConfiguration?,
        observedBundleIdentifier: String? = nil,
        openVerified: Bool = false,
        pasteRequested: Bool = false,
        pasteVerified: Bool = false,
        pasteMethod: String? = nil,
        targetIdentityVerified: Bool = false,
        markerReplaced: Bool = false
    ) -> ComposerPasteResult {
        let strictTargetVerified = switch configuration?.targetPolicy {
        case nil:
            true
        case .openCodeChatComposerV1:
            targetIdentityVerified && markerReplaced
        case .openCodeFocusedChatComposerV1:
            targetIdentityVerified && !markerReplaced
        }
        return ComposerPasteResult(
            schemaVersion: composerPasteSchema,
            code: code,
            message: message,
            action: action,
            expectedBundleIdentifiers: Array(
                configuration?.expectedBundleIdentifiers ?? []
            ).sorted(),
            expectedBundlePath: configuration?.expectedBundlePath,
            observedBundleIdentifier: observedBundleIdentifier,
            observedBundlePath: canonicalBundlePath(
                of: NSWorkspace.shared.frontmostApplication
            ),
            openVerified: openVerified,
            pasteRequested: pasteRequested,
            pasteVerified: pasteVerified,
            contextLoaded: pasteVerified && strictTargetVerified,
            pasteMethod: pasteMethod,
            executionStarted: false,
            targetPolicy: configuration?.targetPolicy?.rawValue,
            targetKind: targetIdentityVerified ? "chat_composer" : nil,
            targetIdentityVerified: targetIdentityVerified,
            markerReplaced: markerReplaced
        )
    }

    private static func frontmostApplicationMatchesPath(
        _ application: NSRunningApplication?,
        expectedPath: String
    ) -> Bool {
        canonicalBundlePath(of: application) == expectedPath
    }

    private static func canonicalBundlePath(
        of application: NSRunningApplication?
    ) -> String? {
        application?.bundleURL?
            .standardizedFileURL.resolvingSymlinksInPath().path
    }

    private static func composerFocusFailure(
        configuration: ComposerPasteConfiguration,
        observedBundleIdentifier: String?,
        openVerified: Bool
    ) -> Int32 {
        emit(
            result(
                code: "desktop_composer_focus_unverified",
                message: (
                    openVerified
                        ? "The selected AI desktop app opened, but DaemonState could not verify a safe composer target. The full context remains on the clipboard."
                        : "DaemonState could not verify that the selected AI desktop app became frontmost. The full context remains on the clipboard."
                ),
                action: "Open the selected app's new-session composer, then retry Continue.",
                configuration: configuration,
                observedBundleIdentifier: observedBundleIdentifier,
                openVerified: openVerified
            )
        )
        return 78
    }

    private static func emit(_ value: ComposerPasteResult) {
        guard let data = try? JSONEncoder().encode(value) else { return }
        FileHandle.standardOutput.write(data)
        FileHandle.standardOutput.write(Data([0x0A]))
    }

    static func readBoundedInput(
        from handle: FileHandle,
        maximumBytes: Int
    ) -> Data {
        var input = Data()
        while input.count <= maximumBytes {
            let remaining = maximumBytes + 1 - input.count
            let chunk = handle.readData(
                ofLength: min(65_536, remaining)
            )
            if chunk.isEmpty { break }
            input.append(chunk)
        }
        return input
    }
}
