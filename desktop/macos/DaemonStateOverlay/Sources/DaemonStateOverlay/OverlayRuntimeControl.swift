import AppKit
import Darwin
import Foundation

private let overlayStateSchema = "context_overlay_state.v1"
private let overlayControlSchema = "context_overlay_control.v1"

enum OverlayRuntimeControlError: Error, Equatable {
    case anotherInstanceIsRunning
    case runtimeDirectoryUnavailable
}

struct OverlayRuntimeState: Codable, Equatable {
    let schemaVersion: String
    let processIdentifier: Int32
    let controlToken: String
    let visible: Bool
    let workspaceID: String?
    let updatedAt: String

    private enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case processIdentifier = "pid"
        case controlToken = "control_token"
        case visible
        case workspaceID = "workspace_id"
        case updatedAt = "updated_at"
    }
}

struct OverlayRuntimeCommand: Codable, Equatable {
    let schemaVersion: String
    let targetToken: String
    let visible: Bool
    let workspaceID: String?

    private enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case targetToken = "target_token"
        case visible
        case workspaceID = "workspace_id"
    }
}

@MainActor
final class OverlayRuntimeController {
    typealias CommandHandler = (_ visible: Bool, _ workspaceID: String?) -> Void

    nonisolated static let stateFileName = "daemonstate-overlay-state.json"
    nonisolated static let controlFileName = "daemonstate-overlay-control.json"
    nonisolated static let lockFileName = "daemonstate-overlay.lock"
    private static var acquiredLockPaths = Set<String>()

    private let controlToken: String
    private let runtimeDirectory: URL
    private let stateURL: URL
    private let controlURL: URL
    private let lockURL: URL
    private var lockFileDescriptor: Int32 = -1
    private var signalSource: DispatchSourceSignal?
    private var commandHandler: CommandHandler?

    init(
        controlToken: String,
        runtimeDirectory: URL? = nil
    ) throws {
        self.controlToken = controlToken
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
    }

    func publish(visible: Bool, workspaceID: String?) {
        let state = OverlayRuntimeState(
            schemaVersion: overlayStateSchema,
            processIdentifier: ProcessInfo.processInfo.processIdentifier,
            controlToken: controlToken,
            visible: visible,
            workspaceID: normalizedWorkspaceID(workspaceID),
            updatedAt: ISO8601DateFormatter().string(from: Date())
        )
        try? writeJSON(state, to: stateURL)
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
            normalizedWorkspaceID(command.workspaceID)
        )
    }

    func stop() {
        signalSource?.cancel()
        signalSource = nil
        commandHandler = nil
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
