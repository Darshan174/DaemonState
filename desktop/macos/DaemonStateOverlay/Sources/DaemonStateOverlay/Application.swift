import AppKit
import DaemonStateOverlayCore

private enum PreferenceKey {
    static let workspaceID = "DaemonStateOverlay.workspaceID"
    static let originX = "DaemonStateOverlay.originX"
    static let originY = "DaemonStateOverlay.originY"
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
    private let pasteService = FocusedTextPasteService()
    private let statusController = StatusPanelController()
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
            NSApplication.shared.terminate(nil)
            return
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
            self?.insertCurrentContext()
        }
        control.onTripleClick = { [weak self] in
            self?.toggleScope()
        }
        control.onContextMenu = { [weak self, weak control] location in
            guard let self, let control else { return }
            self.showContextMenu(at: location, in: control)
        }
        control.onMove = { [weak self] origin in
            self?.saveOrigin(origin)
        }
        panelController.show()
        runtimeController?.start { [weak self] visible, workspaceID in
            self?.applyRuntimeControl(
                visible: visible,
                workspaceID: workspaceID
            )
        }
        publishRuntimeState()

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
        runtimeController?.stop()
    }

    private func insertCurrentContext() {
        guard !busy,
              let target = pendingPasteTarget,
              let api,
              let panel = panelController?.window
        else {
            return
        }

        pendingPasteTarget = nil
        busy = true
        let requestedScope = scope
        if case .accessibilityUnavailable = target {
            pasteService.requestAccessibilityPermission()
        }
        setVisualState(.loading)
        statusController.show(
            "Preparing \(displayName(for: requestedScope))…",
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
                let context = try await api.fetchContext(
                    scope: requestedScope,
                    workspaceID: workspace.id
                )
                let outcome = try await self.pasteService.deliver(
                    context.content,
                    to: target
                )
                switch outcome {
                case .pasted:
                    self.setVisualState(.success, resetAfter: 1.1)
                    self.statusController.show(
                        "\(self.displayName(for: requestedScope)) pasted",
                        tone: .success,
                        relativeTo: panel,
                        dismissAfter: 1.8
                    )
                case let .copiedOnly(message):
                    self.setVisualState(.success, resetAfter: 1.1)
                    self.statusController.show(
                        message,
                        relativeTo: panel,
                        dismissAfter: 3.2
                    )
                }
            } catch {
                self.setVisualState(.failure, resetAfter: 1.35)
                self.statusController.show(
                    self.conciseError(error),
                    tone: .failure,
                    relativeTo: panel,
                    dismissAfter: 4.5
                )
            }
        }
    }

    private func toggleScope() {
        pendingPasteTarget = nil
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
        setScope(scope.toggled)
    }

    private func setScope(_ nextScope: ContextScope) {
        scope = nextScope
        panelController?.logoControl.scope = scope
        panelController?.logoControl.visualState = .idle
        if let panel = panelController?.window {
            statusController.show(
                "\(displayName(for: scope)) selected",
                tone: scope == .project ? .success : .neutral,
                relativeTo: panel,
                dismissAfter: 1.7
            )
        }
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
        let menu = NSMenu(title: "DaemonState")

        let sessionItem = NSMenuItem(
            title: "Session Context",
            action: #selector(selectSessionContext),
            keyEquivalent: ""
        )
        sessionItem.target = self
        sessionItem.state = scope == .session ? .on : .off
        sessionItem.isEnabled = !busy
        menu.addItem(sessionItem)

        let projectItem = NSMenuItem(
            title: "Workspace Context",
            action: #selector(selectProjectContext),
            keyEquivalent: ""
        )
        projectItem.target = self
        projectItem.state = scope == .project ? .on : .off
        projectItem.isEnabled = !busy
        menu.addItem(projectItem)
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
        setScope(.session)
    }

    @objc private func selectProjectContext() {
        setScope(.project)
    }

    @objc private func selectWorkspaceFromMenu(_ sender: NSMenuItem) {
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
        Task { [weak self] in
            await self?.refreshWorkspaces(showFailure: true)
        }
    }

    @objc private func openDashboard() {
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
            guard showFailure, let panel = panelController?.window else { return }
            statusController.show(
                conciseError(error),
                tone: .failure,
                relativeTo: panel,
                dismissAfter: 3.5
            )
        }
    }

    private func selectWorkspace(_ workspaceID: String) {
        preferredWorkspaceID = workspaceID
        preferences.set(workspaceID, forKey: PreferenceKey.workspaceID)
        publishRuntimeState()
    }

    private func applyRuntimeControl(
        visible: Bool,
        workspaceID: String?
    ) {
        if let workspaceID {
            selectWorkspace(workspaceID)
        }
        if visible {
            panelController?.show()
        } else {
            panelController?.hide()
            statusController.hide()
            pendingPasteTarget = nil
        }
        publishRuntimeState()
    }

    private func publishRuntimeState() {
        runtimeController?.publish(
            visible: panelController?.window?.isVisible == true,
            workspaceID: preferredWorkspaceID
        )
    }

    private func capturePasteTarget() {
        guard !busy else {
            pendingPasteTarget = nil
            return
        }
        pendingPasteTarget = pasteService.captureTarget()
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

    private func displayName(for scope: ContextScope) -> String {
        scope == .session ? "Session Context" : "Workspace Context"
    }

    private func conciseError(_ error: Error) -> String {
        let message = error.localizedDescription
            .trimmingCharacters(in: .whitespacesAndNewlines)
        if message.count <= 150 {
            return message
        }
        return "\(message.prefix(147))…"
    }
}
