import AppKit
import DaemonStateOverlayCore
import Darwin

// Mirrors INSTANCE_CONFLICT_EXIT_CODE in app/services/desktop_overlay.py.
private let instanceConflictExitCode: Int32 = 75

private enum PreferenceKey {
    static let workspaceID = "DaemonStateOverlay.workspaceID"
    static let originX = "DaemonStateOverlay.originX"
    static let originY = "DaemonStateOverlay.originY"
}

private enum OverlayDiagnosticsError: LocalizedError {
    case clipboardUnavailable

    var errorDescription: String? {
        "Recent error details could not be written to the clipboard."
    }
}

private struct LaunchConfiguration {
    let apiURL: URL
    let workspaceID: String?
    let controlToken: String

    static func current(
        arguments: [String] = ProcessInfo.processInfo.arguments,
        environment: [String: String] = ProcessInfo.processInfo.environment
    ) -> LaunchConfiguration {
        var apiValue = environment["DAEMONSTATE_API_URL"]
            ?? "http://127.0.0.1:8000/api"
        var workspaceID = environment["DAEMONSTATE_WORKSPACE_ID"]
        var controlToken = environment[
            "DAEMONSTATE_OVERLAY_CONTROL_TOKEN"
        ]

        var index = 1
        while index < arguments.count {
            switch arguments[index] {
            case "--api-url" where index + 1 < arguments.count:
                apiValue = arguments[index + 1]
                index += 2
            case "--workspace-id" where index + 1 < arguments.count:
                workspaceID = arguments[index + 1]
                index += 2
            case "--control-token" where index + 1 < arguments.count:
                controlToken = arguments[index + 1]
                index += 2
            default:
                index += 1
            }
        }

        let fallback = URL(string: "http://127.0.0.1:8000/api")!
        return LaunchConfiguration(
            apiURL: normalizedAPIURL(apiValue) ?? fallback,
            workspaceID: visibleString(workspaceID),
            controlToken: visibleString(controlToken)
                ?? UUID().uuidString.lowercased()
        )
    }

    private static func normalizedAPIURL(_ value: String) -> URL? {
        guard var components = URLComponents(
            string: value.trimmingCharacters(in: .whitespacesAndNewlines)
        ),
        components.scheme == "http" || components.scheme == "https",
        components.host != nil
        else {
            return nil
        }
        let path = components.path.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        if path.isEmpty {
            components.path = "/api"
        } else {
            components.path = "/\(path)"
        }
        components.query = nil
        components.fragment = nil
        return components.url
    }

    private static func visibleString(_ value: String?) -> String? {
        let normalized = value?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return normalized.isEmpty ? nil : normalized
    }
}

@MainActor
final class OverlayApplicationDelegate: NSObject, NSApplicationDelegate {
    private let preferences = UserDefaults.standard
    // OpenCode 1.18's V2 layout does not consume its new-session deep link.
    // Use the same focused-empty-editor boundary as Codex, while retaining
    // OpenCode's normal-chat-composer identity checks.
    private let pasteService = FocusedTextPasteService(
        allowsLegacyOpenCodeEmptyComposerFallback: true,
        allowsOpenCodeURLRouting: false
    )
    private let statusController = StatusPanelController()
    private let promptDropdownController = PromptDropdownController()
    private var panelController: OverlayPanelController?
    private var runtimeController: OverlayRuntimeController?
    private var api: DaemonStateAPI?
    private var configuration = LaunchConfiguration.current()
    private var scope: ContextScope = .defaultScope
    private var workspaces: [WorkspaceSummary] = []
    private var preferredWorkspaceID: String?
    private var busy = false
    private var pendingPasteTarget: FocusedTextPasteService.TargetCapture?
    private var visualResetWorkItem: DispatchWorkItem?
    private var promptSelection = PromptSelection()
    private var selectedSessions: [OverlaySelectedSession] = []
    private var errorHistory = OverlayErrorHistory()

    func applicationDidFinishLaunching(_ notification: Notification) {
        configuration = LaunchConfiguration.current()
        api = DaemonStateAPI(baseURL: configuration.apiURL)
        preferredWorkspaceID = configuration.workspaceID
            ?? preferences.string(forKey: PreferenceKey.workspaceID)

        do {
            runtimeController = try OverlayRuntimeController(
                controlToken: configuration.controlToken
            )
        } catch OverlayRuntimeControlError.anotherInstanceIsRunning {
            Darwin.exit(instanceConflictExitCode)
        } catch {
            NSApplication.shared.terminate(nil)
            return
        }

        let panelController = OverlayPanelController(savedOrigin: savedOrigin())
        self.panelController = panelController
        let control = panelController.logoControl
        control.scope = scope
        control.onGestureBegan = { [weak self] in
            self?.capturePasteTarget()
        }
        control.onGestureCancelled = { [weak self] in
            self?.pendingPasteTarget = nil
        }
        control.onSingleClick = { [weak self] in
            self?.insertFromCurrentMode()
        }
        control.onTripleClick = { [weak self] in
            self?.toggleScope()
        }
        control.onContextMenu = { [weak self, weak control] location in
            guard let self, let control else { return }
            self.showContextMenu(at: location, in: control)
        }
        control.onMove = { [weak self, weak panelController] origin in
            let collapsedOrigin = panelController?.collapsedOrigin(
                forPanelOrigin: origin
            ) ?? origin
            self?.saveOrigin(collapsedOrigin)
        }
        panelController.onSelectSession = { [weak self] session in
            self?.capturePasteTarget()
            self?.pasteExplicitSession(session)
        }
        let promptButton = panelController.promptMenuButton
        promptButton.onPress = { [weak self, weak promptButton] in
            guard let self, let promptButton else { return }
            if self.promptDropdownController.isShown {
                self.pendingPasteTarget = nil
            } else {
                self.capturePasteTarget()
            }
            self.togglePromptDropdown(relativeTo: promptButton)
        }
        promptDropdownController.onRefresh = { [weak self] in
            guard let self else { return [] }
            return try await self.refreshPromptLibrary()
        }
        promptDropdownController.onSave = { [weak self] content in
            guard let self else {
                throw DaemonStateError.invalidPayload(
                    "the floating prompt control is unavailable"
                )
            }
            return try await self.savePrompt(content)
        }
        promptDropdownController.onToggle = { [weak self] prompt in
            self?.togglePrompt(prompt)
        }
        promptDropdownController.selectedPromptIDs = { [weak self] in
            self?.promptSelection.selectedIDs ?? []
        }
        promptDropdownController.onError = { [weak self] operation, error in
            self?.recordError(error, operation: operation)
        }
        applyPromptSelectionVisuals()
        panelController.show()
        runtimeController?.start { [weak self] visible, workspaceID, sessions in
            self?.applyRuntimeControl(
                visible: visible,
                workspaceID: workspaceID,
                selectedSessions: sessions
            )
        }
        guard publishRuntimeState() else {
            runtimeController?.stop()
            runtimeController = nil
            NSApplication.shared.terminate(nil)
            return
        }

        Task { [weak self] in
            await self?.refreshWorkspaces(showFailure: false)
        }
    }

    func applicationShouldTerminateAfterLastWindowClosed(
        _ sender: NSApplication
    ) -> Bool {
        false
    }

    func applicationWillTerminate(_ notification: Notification) {
        promptDropdownController.close()
        runtimeController?.stop()
    }

    private func insertFromCurrentMode() {
        if promptSelection.isActive {
            insertSelectedPrompts()
        } else {
            insertCurrentContext()
        }
    }

    private func insertCurrentContext() {
        insertContext(
            scope: scope,
            explicitSession: nil
        )
    }

    private func insertContext(
        scope requestedScope: ContextScope,
        explicitSession requestedExplicitSession: OverlaySelectedSession?
    ) {
        guard !busy,
              let target = pendingPasteTarget,
              let api,
              let panel = panelController?.window
        else {
            return
        }

        pendingPasteTarget = nil
        busy = true
        let requestedDisplayName = displayName(
            for: requestedScope,
            explicitSession: requestedExplicitSession
        )
        if case .accessibilityUnavailable = target {
            pasteService.requestAccessibilityPermission()
        }
        setVisualState(.loading)
        statusController.show(
            "Preparing \(requestedDisplayName)…",
            relativeTo: panel,
            dismissAfter: nil
        )

        Task { [weak self] in
            guard let self else { return }
            defer { self.busy = false }
            do {
                let workspace = try await api.resolveWorkspace(
                    preferredID: self.preferredWorkspaceID
                )
                self.selectWorkspace(workspace.id)
                let context: VerifiedContext
                if let requestedExplicitSession {
                    context = try await api.fetchSessionContext(
                        workspaceID: workspace.id,
                        provider: requestedExplicitSession.provider,
                        sessionID: requestedExplicitSession.sessionID
                    )
                } else {
                    context = try await api.fetchContext(
                        scope: requestedScope,
                        workspaceID: workspace.id,
                        repoPath: workspace.repoPath ?? workspace.repoPaths.first
                    )
                }
                let outcome = try await self.pasteService.deliver(
                    context.content,
                    to: target,
                    openCodeProjectDirectory: (
                        workspace.repoPath ?? workspace.repoPaths.first
                    )
                )
                switch outcome {
                case .alreadyPresentInVerifiedOpenCodeComposer:
                    self.setVisualState(.success, resetAfter: 1.1)
                    self.statusController.show(
                        "\(requestedDisplayName) is already present",
                        tone: .success,
                        relativeTo: panel,
                        dismissAfter: 2.4
                    )
                case .insertedWithAccessibility,
                     .insertedIntoVerifiedEmptyComposerWithInputSync,
                     .markerReplacedWithVerifiedInputSync,
                     .commandVDispatched:
                    self.setVisualState(.success, resetAfter: 1.1)
                    self.statusController.show(
                        "\(requestedDisplayName) pasted",
                        tone: .success,
                        relativeTo: panel,
                        dismissAfter: 1.8
                    )
                case let .accessibilityInsertionUnverified(message),
                     let .notPasted(message):
                    self.setVisualState(.failure, resetAfter: 1.35)
                    self.statusController.show(
                        message,
                        tone: .failure,
                        relativeTo: panel,
                        dismissAfter: 3.2
                    )
                }
            } catch {
                self.setVisualState(.failure, resetAfter: 1.35)
                self.presentError(
                    error,
                    operation: "Paste \(requestedDisplayName)",
                    relativeTo: panel,
                    dismissAfter: 4.5
                )
            }
        }
    }

    private func insertSelectedPrompts(
        clearSelectionAfterPaste: Bool = false
    ) {
        guard !busy,
              let target = pendingPasteTarget,
              let api,
              let panel = panelController?.window,
              let workspaceID = promptSelection.prompts.first?.workspaceID,
              !promptSelection.combinedContent.isEmpty
        else {
            return
        }

        let selection = promptSelection
        pendingPasteTarget = nil
        busy = true
        if case .accessibilityUnavailable = target {
            pasteService.requestAccessibilityPermission()
        }
        setVisualState(.loading)
        let noun = selection.count == 1 ? "prompt" : "prompts"
        statusController.show(
            "Pasting \(selection.count) selected \(noun)…",
            relativeTo: panel,
            dismissAfter: nil
        )

        Task { [weak self] in
            guard let self else { return }
            defer {
                self.busy = false
                if clearSelectionAfterPaste {
                    self.promptSelection.clear()
                    self.applyPromptSelectionVisuals()
                }
            }
            do {
                let projectDirectory = self.workspaces.first {
                    $0.id == workspaceID
                }.flatMap { workspace in
                    workspace.repoPath ?? workspace.repoPaths.first
                }
                let outcome = try await self.pasteService.deliver(
                    selection.combinedContent,
                    to: target,
                    openCodeProjectDirectory: projectDirectory
                )
                do {
                    try await api.recordPromptUsage(
                        workspaceID: workspaceID,
                        promptIDs: selection.ids
                    )
                } catch {
                    self.recordError(error, operation: "Record Prompt Usage")
                }
                self.setVisualState(.success, resetAfter: 1.1)
                switch outcome {
                case .alreadyPresentInVerifiedOpenCodeComposer:
                    self.statusController.show(
                        selection.count == 1
                            ? "Selected prompt is already present"
                            : "Selected prompts are already present",
                        tone: .success,
                        relativeTo: panel,
                        dismissAfter: 2.4
                    )
                case .insertedWithAccessibility,
                     .insertedIntoVerifiedEmptyComposerWithInputSync,
                     .markerReplacedWithVerifiedInputSync,
                     .commandVDispatched:
                    self.statusController.show(
                        selection.count == 1
                            ? "Selected prompt pasted"
                            : "\(selection.count) selected prompts pasted",
                        tone: .success,
                        relativeTo: panel,
                        dismissAfter: 1.8
                    )
                case let .accessibilityInsertionUnverified(message),
                     let .notPasted(message):
                    self.setVisualState(.failure, resetAfter: 1.35)
                    self.statusController.show(
                        message,
                        tone: .failure,
                        relativeTo: panel,
                        dismissAfter: 3.2
                    )
                }
            } catch {
                self.setVisualState(.failure, resetAfter: 1.35)
                self.presentError(
                    error,
                    operation: "Paste Selected Prompts",
                    relativeTo: panel,
                    dismissAfter: 4.5
                )
            }
        }
    }

    private func togglePromptDropdown(relativeTo button: NSView) {
        guard !busy else {
            if let panel = panelController?.window {
                statusController.show(
                    "Finish the current paste before changing prompts.",
                    relativeTo: panel,
                    dismissAfter: 2.2
                )
            }
            return
        }
        promptDropdownController.toggle(relativeTo: button)
    }

    private func refreshPromptLibrary() async throws -> [PromptSnippet] {
        guard let api else {
            throw DaemonStateError.network("the local service is unavailable")
        }
        let workspace = try await api.resolveWorkspace(
            preferredID: preferredWorkspaceID
        )
        selectWorkspace(workspace.id)
        let prompts = try await api.promptSnippets(workspaceID: workspace.id)
        promptSelection.replaceAvailable(with: prompts)
        applyPromptSelectionVisuals()
        return prompts
    }

    private func savePrompt(_ content: String) async throws -> PromptSnippet {
        guard let api else {
            throw DaemonStateError.network("the local service is unavailable")
        }
        let workspace = try await api.resolveWorkspace(
            preferredID: preferredWorkspaceID
        )
        selectWorkspace(workspace.id)
        return try await api.createPromptSnippet(
            workspaceID: workspace.id,
            content: content
        )
    }

    private func togglePrompt(_ prompt: PromptSnippet) {
        guard !busy else { return }
        if preferredWorkspaceID != prompt.workspaceID {
            selectWorkspace(prompt.workspaceID)
        }
        promptSelection.clear()
        _ = promptSelection.toggle(prompt)
        applyPromptSelectionVisuals()
        insertSelectedPrompts(clearSelectionAfterPaste: true)
    }

    private func applyPromptSelectionVisuals() {
        panelController?.logoControl.selectedPromptCount = promptSelection.count
        panelController?.promptMenuButton.selectedPromptCount = promptSelection.count
        promptDropdownController.selectionDidChange()
    }

    private func toggleScope() {
        guard !busy else {
            if let panel = panelController?.window {
                statusController.show(
                    "Finish the current insert before switching context.",
                    tone: .neutral,
                    relativeTo: panel,
                    dismissAfter: 2.2
                )
            }
            return
        }
        capturePasteTarget()
        let nextScope = scope.toggled
        prepareForDirectContextAction(scope: nextScope)
        insertContext(scope: nextScope, explicitSession: nil)
    }

    private func pasteExplicitSession(_ session: OverlaySelectedSession) {
        guard !busy,
              selectedSessions.contains(where: { $0.identity == session.identity })
        else {
            return
        }
        prepareForDirectContextAction(scope: .session)
        panelController?.collapse()
        insertContext(scope: .session, explicitSession: session)
    }

    private func setScope(_ nextScope: ContextScope) {
        scope = nextScope
        panelController?.logoControl.scope = scope
        panelController?.logoControl.visualState = .idle
    }

    private func prepareForDirectContextAction(scope nextScope: ContextScope) {
        if promptSelection.isActive {
            promptSelection.clear()
            applyPromptSelectionVisuals()
        }
        setScope(nextScope)
    }

    private func setVisualState(
        _ state: LogoControl.VisualState,
        resetAfter: TimeInterval? = nil
    ) {
        visualResetWorkItem?.cancel()
        panelController?.logoControl.visualState = state
        guard let resetAfter else { return }
        let workItem = DispatchWorkItem { [weak self] in
            self?.panelController?.logoControl.visualState = .idle
        }
        visualResetWorkItem = workItem
        DispatchQueue.main.asyncAfter(
            deadline: .now() + resetAfter,
            execute: workItem
        )
    }

    private func showContextMenu(at location: NSPoint, in control: NSView) {
        capturePasteTarget()
        let menu = NSMenu(title: "DaemonState")

        let sessionItem = NSMenuItem(
            title: "Paste Session Context",
            action: #selector(selectSessionContext),
            keyEquivalent: ""
        )
        sessionItem.target = self
        sessionItem.state = scope == .session ? .on : .off
        sessionItem.isEnabled = !busy
        menu.addItem(sessionItem)

        let projectItem = NSMenuItem(
            title: "Paste Workspace Context",
            action: #selector(selectProjectContext),
            keyEquivalent: ""
        )
        projectItem.target = self
        projectItem.state = scope == .project ? .on : .off
        projectItem.isEnabled = !busy
        menu.addItem(projectItem)

        if !selectedSessions.isEmpty {
            let selectedItem = NSMenuItem(
                title: "Paste Selected Session",
                action: nil,
                keyEquivalent: ""
            )
            let selectedMenu = NSMenu(title: "Selected Sessions")
            for session in selectedSessions {
                let item = NSMenuItem(
                    title: "\(session.ordinalLabel) · \(session.providerDisplayName) · \(session.title)",
                    action: #selector(selectExplicitSessionFromMenu(_:)),
                    keyEquivalent: "\(session.ordinal)"
                )
                item.target = self
                item.representedObject = session.identity
                item.keyEquivalentModifierMask = [.command, .option]
                item.isEnabled = !busy
                selectedMenu.addItem(item)
            }
            selectedItem.submenu = selectedMenu
            menu.addItem(selectedItem)
        }
        menu.addItem(.separator())

        let workspaceItem = NSMenuItem(title: "Workspace", action: nil, keyEquivalent: "")
        let workspaceMenu = NSMenu(title: "Workspace")
        if workspaces.isEmpty {
            let unavailable = NSMenuItem(
                title: "Loading workspaces…",
                action: nil,
                keyEquivalent: ""
            )
            unavailable.isEnabled = false
            workspaceMenu.addItem(unavailable)
        } else {
            for workspace in workspaces {
                let item = NSMenuItem(
                    title: workspace.name,
                    action: #selector(selectWorkspaceFromMenu(_:)),
                    keyEquivalent: ""
                )
                item.target = self
                item.representedObject = workspace.id
                item.state = workspace.id == preferredWorkspaceID ? .on : .off
                item.isEnabled = !busy
                workspaceMenu.addItem(item)
            }
        }
        workspaceItem.submenu = workspaceMenu
        menu.addItem(workspaceItem)

        let refreshItem = NSMenuItem(
            title: "Refresh Workspaces",
            action: #selector(refreshWorkspacesFromMenu),
            keyEquivalent: ""
        )
        refreshItem.target = self
        menu.addItem(refreshItem)

        let errorCountSuffix = errorHistory.isEmpty
            ? ""
            : " (\(errorHistory.count))"
        let copyErrorsItem = NSMenuItem(
            title: "Copy Recent Error Details\(errorCountSuffix)",
            action: #selector(copyRecentErrorDetails),
            keyEquivalent: ""
        )
        copyErrorsItem.target = self
        copyErrorsItem.isEnabled = !errorHistory.isEmpty
        menu.addItem(copyErrorsItem)
        menu.addItem(.separator())

        let openItem = NSMenuItem(
            title: "Open DaemonState",
            action: #selector(openDashboard),
            keyEquivalent: ""
        )
        openItem.target = self
        menu.addItem(openItem)
        menu.addItem(.separator())

        let quitItem = NSMenuItem(
            title: "Quit DaemonState Control",
            action: #selector(quit),
            keyEquivalent: "q"
        )
        quitItem.target = self
        menu.addItem(quitItem)

        menu.popUp(positioning: nil, at: location, in: control)
    }

    @objc private func selectSessionContext() {
        prepareForDirectContextAction(scope: .session)
        insertContext(scope: .session, explicitSession: nil)
    }

    @objc private func selectProjectContext() {
        prepareForDirectContextAction(scope: .project)
        insertContext(scope: .project, explicitSession: nil)
    }

    @objc private func selectExplicitSessionFromMenu(_ sender: NSMenuItem) {
        guard let identity = sender.representedObject as? String,
              let session = selectedSessions.first(where: {
                  $0.identity == identity
              }) else { return }
        pasteExplicitSession(session)
    }

    @objc private func selectWorkspaceFromMenu(_ sender: NSMenuItem) {
        pendingPasteTarget = nil
        guard let workspaceID = sender.representedObject as? String else { return }
        selectWorkspace(workspaceID)
        if let workspace = workspaces.first(where: { $0.id == workspaceID }),
           let panel = panelController?.window
        {
            statusController.show(
                workspace.name,
                relativeTo: panel,
                dismissAfter: 1.8
            )
        }
    }

    @objc private func refreshWorkspacesFromMenu() {
        pendingPasteTarget = nil
        Task { [weak self] in
            await self?.refreshWorkspaces(showFailure: true)
        }
    }

    @objc private func copyRecentErrorDetails() {
        pendingPasteTarget = nil
        let details = errorHistory.clipboardText()
        guard !details.isEmpty else { return }

        let pasteboard = NSPasteboard.general
        pasteboard.clearContents()
        guard pasteboard.setString(details, forType: .string) else {
            let error = OverlayDiagnosticsError.clipboardUnavailable
            recordError(error, operation: "Copy Recent Error Details")
            if let panel = panelController?.window {
                statusController.show(
                    conciseError(error),
                    tone: .failure,
                    relativeTo: panel,
                    dismissAfter: 3.5
                )
            }
            return
        }
        if let panel = panelController?.window {
            let noun = errorHistory.count == 1 ? "error" : "errors"
            statusController.show(
                "Copied \(errorHistory.count) recent \(noun) with full details",
                tone: .success,
                relativeTo: panel,
                dismissAfter: 2.2
            )
        }
    }

    @objc private func openDashboard() {
        pendingPasteTarget = nil
        guard var components = URLComponents(
            url: configuration.apiURL,
            resolvingAgainstBaseURL: false
        ) else {
            return
        }
        var path = components.path
        if path.hasSuffix("/api") {
            path.removeLast(4)
        }
        components.path = "\(path)/app/execute"
            .replacingOccurrences(of: "//", with: "/")
        components.query = nil
        components.fragment = nil
        if let url = components.url {
            NSWorkspace.shared.open(url)
        }
    }

    @objc private func quit() {
        NSApplication.shared.terminate(nil)
    }

    private func refreshWorkspaces(showFailure: Bool) async {
        guard let api else { return }
        do {
            let loaded = try await api.workspaces()
            workspaces = loaded
            if let selected = try? WorkspaceResolver.resolve(
                loaded,
                preferredID: preferredWorkspaceID
            ) {
                selectWorkspace(selected.id)
            }
        } catch {
            recordError(error, operation: "Refresh Workspaces")
            guard showFailure, let panel = panelController?.window else { return }
            statusController.show(
                conciseError(error),
                tone: .failure,
                relativeTo: panel,
                dismissAfter: 3.5
            )
        }
    }

    private func selectWorkspace(
        _ workspaceID: String,
        publishState: Bool = true
    ) {
        if let current = preferredWorkspaceID, current != workspaceID {
            if promptSelection.isActive {
                promptSelection.clear()
                applyPromptSelectionVisuals()
            }
            applySelectedSessions([])
        }
        preferredWorkspaceID = workspaceID
        preferences.set(workspaceID, forKey: PreferenceKey.workspaceID)
        if publishState {
            publishRuntimeState()
        }
    }

    private func applyRuntimeControl(
        visible: Bool,
        workspaceID: String?,
        selectedSessions incomingSessions: [OverlaySelectedSession]?
    ) {
        if let workspaceID {
            selectWorkspace(workspaceID, publishState: false)
        }
        if let incomingSessions {
            applySelectedSessions(incomingSessions)
        }
        if visible {
            panelController?.show()
        } else {
            promptDropdownController.close()
            panelController?.hide()
            statusController.hide()
            pendingPasteTarget = nil
        }
        publishRuntimeState()
    }

    @discardableResult
    private func publishRuntimeState() -> Bool {
        runtimeController?.publish(
            visible: panelController?.window?.isVisible == true,
            workspaceID: preferredWorkspaceID,
            selectedSessions: selectedSessions
        ) ?? false
    }

    private func applySelectedSessions(_ sessions: [OverlaySelectedSession]) {
        let normalized = normalizedOverlaySelectedSessions(sessions)
        selectedSessions = normalized
        panelController?.setSelectedSessions(normalized)
    }

    private func capturePasteTarget() {
        guard !busy else {
            pendingPasteTarget = nil
            return
        }
        pendingPasteTarget = pasteService.captureTarget(
            requireFocusedEmptyOpenCodeComposer: true
        )
    }

    private func saveOrigin(_ origin: NSPoint) {
        preferences.set(origin.x, forKey: PreferenceKey.originX)
        preferences.set(origin.y, forKey: PreferenceKey.originY)
    }

    private func savedOrigin() -> NSPoint? {
        guard preferences.object(forKey: PreferenceKey.originX) != nil,
              preferences.object(forKey: PreferenceKey.originY) != nil
        else {
            return nil
        }
        return NSPoint(
            x: preferences.double(forKey: PreferenceKey.originX),
            y: preferences.double(forKey: PreferenceKey.originY)
        )
    }

    private func displayName(
        for scope: ContextScope,
        explicitSession: OverlaySelectedSession? = nil
    ) -> String {
        if scope == .session, let explicitSession {
            return "Session \(explicitSession.ordinalLabel) Context"
        }
        return scope == .session ? "Session Context" : "Workspace Context"
    }

    private func recordError(_ error: Error, operation: String) {
        errorHistory.record(operation: operation, error: error)
    }

    private func presentError(
        _ error: Error,
        operation: String,
        relativeTo panel: NSWindow,
        dismissAfter: TimeInterval
    ) {
        recordError(error, operation: operation)
        statusController.show(
            conciseError(error),
            tone: .failure,
            relativeTo: panel,
            dismissAfter: dismissAfter
        )
    }

    private func conciseError(_ error: Error) -> String {
        OverlayErrorHistory.conciseMessage(error.localizedDescription)
    }
}
