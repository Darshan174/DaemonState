import AppKit
import Darwin
import Foundation

private let overlayStateSchema = "context_overlay_state.v1"
private let overlayControlSchema = "context_overlay_control.v1"
private let maximumOverlaySelectedSessions = 3

enum OverlayRuntimeControlError: Error, Equatable {
    case anotherInstanceIsRunning
    case runtimeDirectoryUnavailable
}

struct OverlaySelectedSession: Codable, Equatable, Hashable, Sendable {
    let provider: String
    let sessionID: String
    let title: String
    let ordinal: Int

    init(provider: String, sessionID: String, title: String, ordinal: Int) {
        self.provider = provider
        self.sessionID = sessionID
        self.title = title
        self.ordinal = ordinal
    }

    private enum CodingKeys: String, CodingKey {
        case provider
        case sessionID = "session_id"
        case title
        case ordinal
    }

    var identity: String {
        "\(provider)\u{0}\(sessionID)"
    }

    var providerDisplayName: String {
        switch provider {
        case "codex":
            return "Codex"
        case "claude":
            return "Claude Code"
        case "opencode":
            return "OpenCode"
        default:
            return "AI session"
        }
    }

    var ordinalLabel: String {
        String(ordinal)
    }
}

func normalizedOverlaySelectedSessions(
    _ values: [OverlaySelectedSession]
) -> [OverlaySelectedSession] {
    var seenIdentities = Set<String>()
    var seenOrdinals = Set<Int>()
    var result: [OverlaySelectedSession] = []

    for value in values.sorted(by: {
        if $0.ordinal != $1.ordinal { return $0.ordinal < $1.ordinal }
        return $0.identity < $1.identity
    }) {
        let provider = normalizedOverlayProvider(value.provider)
        let sessionID = value.sessionID.trimmingCharacters(
            in: .whitespacesAndNewlines
        )
        guard ["codex", "claude", "opencode"].contains(provider),
              !sessionID.isEmpty,
              (1...maximumOverlaySelectedSessions).contains(value.ordinal)
        else {
            continue
        }
        let identity = "\(provider)\u{0}\(sessionID)"
        guard seenIdentities.insert(identity).inserted,
              seenOrdinals.insert(value.ordinal).inserted
        else {
            continue
        }
        let title = value.title.trimmingCharacters(in: .whitespacesAndNewlines)
        result.append(
            OverlaySelectedSession(
                provider: provider,
                sessionID: sessionID,
                title: title.isEmpty ? "Selected session" : title,
                ordinal: value.ordinal
            )
        )
        if result.count == maximumOverlaySelectedSessions { break }
    }
    return result
}

private func normalizedOverlayProvider(_ value: String) -> String {
    var provider = value.trimmingCharacters(in: .whitespacesAndNewlines)
        .lowercased()
    if provider.hasPrefix("daemonstate:") {
        provider.removeFirst("daemonstate:".count)
    }
    switch provider {
    case "claude code", "claude_code", "claude-code":
        return "claude"
    case "open code", "open_code", "open-code":
        return "opencode"
    default:
        return provider
    }
}

struct OverlayRuntimeState: Codable, Equatable {
    let schemaVersion: String
    let processIdentifier: Int32
    let controlToken: String
    let visible: Bool
    let workspaceID: String?
    let selectedSessions: [OverlaySelectedSession]
    let updatedAt: String

    init(
        schemaVersion: String,
        processIdentifier: Int32,
        controlToken: String,
        visible: Bool,
        workspaceID: String?,
        selectedSessions: [OverlaySelectedSession] = [],
        updatedAt: String
    ) {
        self.schemaVersion = schemaVersion
        self.processIdentifier = processIdentifier
        self.controlToken = controlToken
        self.visible = visible
        self.workspaceID = workspaceID
        self.selectedSessions = normalizedOverlaySelectedSessions(
            selectedSessions
        )
        self.updatedAt = updatedAt
    }

    private enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case processIdentifier = "pid"
        case controlToken = "control_token"
        case visible
        case workspaceID = "workspace_id"
        case selectedSessions = "selected_sessions"
        case updatedAt = "updated_at"
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        schemaVersion = try container.decode(String.self, forKey: .schemaVersion)
        processIdentifier = try container.decode(
            Int32.self,
            forKey: .processIdentifier
        )
        controlToken = try container.decode(String.self, forKey: .controlToken)
        visible = try container.decode(Bool.self, forKey: .visible)
        workspaceID = try container.decodeIfPresent(String.self, forKey: .workspaceID)
        selectedSessions = normalizedOverlaySelectedSessions(
            try container.decodeIfPresent(
                [OverlaySelectedSession].self,
                forKey: .selectedSessions
            ) ?? []
        )
        updatedAt = try container.decode(String.self, forKey: .updatedAt)
    }
}

struct OverlayRuntimeCommand: Codable, Equatable {
    let schemaVersion: String
    let targetToken: String
    let visible: Bool
    let workspaceID: String?
    let selectedSessions: [OverlaySelectedSession]?

    init(
        schemaVersion: String,
        targetToken: String,
        visible: Bool,
        workspaceID: String?,
        selectedSessions: [OverlaySelectedSession]? = nil
    ) {
        self.schemaVersion = schemaVersion
        self.targetToken = targetToken
        self.visible = visible
        self.workspaceID = workspaceID
        self.selectedSessions = selectedSessions.map(
            normalizedOverlaySelectedSessions
        )
    }

    private enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case targetToken = "target_token"
        case visible
        case workspaceID = "workspace_id"
        case selectedSessions = "selected_sessions"
    }
}

@MainActor
final class OverlayRuntimeController {
    typealias CommandHandler = (
        _ visible: Bool,
        _ workspaceID: String?,
        _ selectedSessions: [OverlaySelectedSession]?
    ) -> Void

    nonisolated static let stateFileName = "daemonstate-overlay-state.json"
    nonisolated static let controlFileName = "daemonstate-overlay-control.json"
    nonisolated static let lockFileName = "daemonstate-overlay.lock"
    private static var acquiredLockPaths = Set<String>()

    private let controlToken: String
    private let runtimeDirectory: URL
    private let stateURL: URL
    private let controlURL: URL
    private let lockURL: URL
    private let stateRepairInterval: DispatchTimeInterval?
    private var lockFileDescriptor: Int32 = -1
    private var signalSource: DispatchSourceSignal?
    private var stateRepairTimer: DispatchSourceTimer?
    private var commandHandler: CommandHandler?
    private var lastPublishedVisible: Bool?
    private var lastPublishedWorkspaceID: String?
    private var lastPublishedSelectedSessions: [OverlaySelectedSession] = []

    init(
        controlToken: String,
        runtimeDirectory: URL? = nil,
        stateRepairInterval: DispatchTimeInterval? = .seconds(1)
    ) throws {
        self.controlToken = controlToken
        self.stateRepairInterval = stateRepairInterval
        let resolvedRuntimeDirectory = runtimeDirectory
            ?? Self.defaultRuntimeDirectory()
        self.runtimeDirectory = resolvedRuntimeDirectory
        stateURL = resolvedRuntimeDirectory.appendingPathComponent(
            Self.stateFileName
        )
        controlURL = resolvedRuntimeDirectory.appendingPathComponent(
            Self.controlFileName
        )
        lockURL = resolvedRuntimeDirectory.appendingPathComponent(
            Self.lockFileName
        )

        do {
            try FileManager.default.createDirectory(
                at: resolvedRuntimeDirectory,
                withIntermediateDirectories: true,
                attributes: [.posixPermissions: 0o700]
            )
        } catch {
            throw OverlayRuntimeControlError.runtimeDirectoryUnavailable
        }
        try acquireInstanceLock()
    }

    func start(commandHandler: @escaping CommandHandler) {
        self.commandHandler = commandHandler
        Darwin.signal(SIGUSR1, SIG_IGN)
        let source = DispatchSource.makeSignalSource(
            signal: SIGUSR1,
            queue: .main
        )
        source.setEventHandler { [weak self] in
            self?.processPendingControl()
        }
        signalSource = source
        source.resume()

        if let stateRepairInterval {
            let timer = DispatchSource.makeTimerSource(queue: .main)
            timer.schedule(
                deadline: .now() + stateRepairInterval,
                repeating: stateRepairInterval,
                leeway: .milliseconds(10)
            )
            timer.setEventHandler { [weak self] in
                _ = self?.ensureLatestStateIsPublished()
            }
            stateRepairTimer = timer
            timer.resume()
        }
    }

    @discardableResult
    func publish(
        visible: Bool,
        workspaceID: String?,
        selectedSessions: [OverlaySelectedSession] = []
    ) -> Bool {
        lastPublishedVisible = visible
        lastPublishedWorkspaceID = normalizedWorkspaceID(workspaceID)
        lastPublishedSelectedSessions = normalizedOverlaySelectedSessions(
            selectedSessions
        )
        return writeLatestState()
    }

    private func writeLatestState() -> Bool {
        guard let visible = lastPublishedVisible else { return false }
        let state = OverlayRuntimeState(
            schemaVersion: overlayStateSchema,
            processIdentifier: ProcessInfo.processInfo.processIdentifier,
            controlToken: controlToken,
            visible: visible,
            workspaceID: lastPublishedWorkspaceID,
            selectedSessions: lastPublishedSelectedSessions,
            updatedAt: ISO8601DateFormatter().string(from: Date())
        )
        do {
            try writeJSON(state, to: stateURL)
            return true
        } catch {
            return false
        }
    }

    private func ensureLatestStateIsPublished() -> Bool {
        guard let visible = lastPublishedVisible,
              let data = try? Data(contentsOf: stateURL),
              let object = try? JSONSerialization.jsonObject(with: data)
                  as? [String: Any],
              object["selected_sessions"] is [Any],
              let state = try? JSONDecoder().decode(
                  OverlayRuntimeState.self,
                  from: data
              ),
              state.schemaVersion == overlayStateSchema,
              state.processIdentifier == ProcessInfo.processInfo.processIdentifier,
              state.controlToken == controlToken,
              state.visible == visible,
              state.workspaceID == lastPublishedWorkspaceID,
              state.selectedSessions == lastPublishedSelectedSessions
        else {
            return writeLatestState()
        }
        return true
    }

    func processPendingControl() {
        guard let data = try? Data(contentsOf: controlURL),
              let command = try? JSONDecoder().decode(
                  OverlayRuntimeCommand.self,
                  from: data
              ),
              command.schemaVersion == overlayControlSchema,
              command.targetToken == controlToken
        else {
            return
        }
        commandHandler?(
            command.visible,
            normalizedWorkspaceID(command.workspaceID),
            command.selectedSessions.map(normalizedOverlaySelectedSessions)
        )
    }

    func stop() {
        stateRepairTimer?.cancel()
        stateRepairTimer = nil
        signalSource?.cancel()
        signalSource = nil
        commandHandler = nil
        lastPublishedVisible = nil
        lastPublishedWorkspaceID = nil
        lastPublishedSelectedSessions = []
        removeOwnedRuntimeFiles()
        if lockFileDescriptor >= 0 {
            _ = Darwin.lockf(lockFileDescriptor, F_ULOCK, 0)
            Darwin.close(lockFileDescriptor)
            lockFileDescriptor = -1
        }
        Self.acquiredLockPaths.remove(lockURL.path)
    }

    nonisolated static func defaultRuntimeDirectory(
        environment: [String: String] = ProcessInfo.processInfo.environment
    ) -> URL {
        let configured = environment["DAEMONSTATE_OVERLAY_RUNTIME_DIR"]?
            .trimmingCharacters(in: .whitespacesAndNewlines)
        if let configured,
           configured.hasPrefix("/") {
            return URL(fileURLWithPath: configured, isDirectory: true)
        }
        return FileManager.default.temporaryDirectory
    }

    private func acquireInstanceLock() throws {
        guard !Self.acquiredLockPaths.contains(lockURL.path) else {
            throw OverlayRuntimeControlError.anotherInstanceIsRunning
        }
        let descriptor = lockURL.path.withCString { path in
            Darwin.open(path, O_CREAT | O_RDWR, S_IRUSR | S_IWUSR)
        }
        guard descriptor >= 0 else {
            throw OverlayRuntimeControlError.runtimeDirectoryUnavailable
        }
        guard Darwin.lockf(descriptor, F_TLOCK, 0) == 0 else {
            Darwin.close(descriptor)
            throw OverlayRuntimeControlError.anotherInstanceIsRunning
        }
        lockFileDescriptor = descriptor
        Self.acquiredLockPaths.insert(lockURL.path)
    }

    private func removeOwnedRuntimeFiles() {
        guard let data = try? Data(contentsOf: stateURL),
              let state = try? JSONDecoder().decode(
                  OverlayRuntimeState.self,
                  from: data
              ),
              state.controlToken == controlToken
        else {
            return
        }
        try? FileManager.default.removeItem(at: stateURL)
        if let data = try? Data(contentsOf: controlURL),
           let command = try? JSONDecoder().decode(
               OverlayRuntimeCommand.self,
               from: data
           ),
           command.targetToken == controlToken {
            try? FileManager.default.removeItem(at: controlURL)
        }
    }

    private func writeJSON<Value: Encodable>(
        _ value: Value,
        to url: URL
    ) throws {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        let data = try encoder.encode(value)
        try data.write(to: url, options: .atomic)
        try FileManager.default.setAttributes(
            [.posixPermissions: 0o600],
            ofItemAtPath: url.path
        )
    }

    private func normalizedWorkspaceID(_ value: String?) -> String? {
        let normalized = value?
            .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        guard !normalized.isEmpty,
              UUID(uuidString: normalized) != nil else {
            return nil
        }
        return normalized
    }
}
