import Foundation
import Testing
@testable import DaemonStateOverlay

@Suite(.serialized)
struct OverlayRuntimeControlTests {
    @Test
    @MainActor
    func publishesStateAndAppliesOnlyTokenBoundCommands() throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let controller = try OverlayRuntimeController(
            controlToken: "control-token-1",
            runtimeDirectory: directory
        )
        defer { controller.stop() }

        var receivedVisible: Bool?
        var receivedWorkspaceID: String?
        var receivedSessions: [OverlaySelectedSession]?
        controller.start { visible, workspaceID, selectedSessions in
            receivedVisible = visible
            receivedWorkspaceID = workspaceID
            receivedSessions = selectedSessions
        }
        let workspaceID = "6e7a71eb-df4f-4899-9aab-ee487f5a0649"
        let sessions = selectedSessionFixtures()
        controller.publish(
            visible: true,
            workspaceID: workspaceID,
            selectedSessions: sessions
        )

        let stateData = try Data(contentsOf: directory.appendingPathComponent(
            OverlayRuntimeController.stateFileName
        ))
        let state = try JSONDecoder().decode(
            OverlayRuntimeState.self,
            from: stateData
        )
        #expect(state.schemaVersion == "context_overlay_state.v1")
        #expect(state.processIdentifier == ProcessInfo.processInfo.processIdentifier)
        #expect(state.controlToken == "control-token-1")
        #expect(state.visible)
        #expect(state.workspaceID == workspaceID)
        #expect(state.selectedSessions == sessions)
        let stateObject = try #require(
            JSONSerialization.jsonObject(with: stateData) as? [String: Any]
        )
        #expect(stateObject["selected_sessions"] != nil)

        try writeCommand(
            OverlayRuntimeCommand(
                schemaVersion: "context_overlay_control.v1",
                targetToken: "another-process",
                visible: false,
                workspaceID: workspaceID,
                selectedSessions: sessions
            ),
            to: directory
        )
        controller.processPendingControl()
        #expect(receivedVisible == nil)
        #expect(receivedSessions == nil)

        try writeCommand(
            OverlayRuntimeCommand(
                schemaVersion: "context_overlay_control.v1",
                targetToken: "control-token-1",
                visible: false,
                workspaceID: workspaceID,
                selectedSessions: sessions
            ),
            to: directory
        )
        controller.processPendingControl()
        #expect(receivedVisible == false)
        #expect(receivedWorkspaceID == workspaceID)
        #expect(receivedSessions == sessions)
    }

    @Test
    @MainActor
    func instanceLockPreventsDuplicateFloatingControls() throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let first = try OverlayRuntimeController(
            controlToken: "first",
            runtimeDirectory: directory
        )
        defer { first.stop() }

        do {
            _ = try OverlayRuntimeController(
                controlToken: "second",
                runtimeDirectory: directory
            )
            Issue.record("Expected the second overlay instance to be rejected")
        } catch let error as OverlayRuntimeControlError {
            #expect(error == .anotherInstanceIsRunning)
        }
    }

    @Test
    @MainActor
    func republishesStateWhenTheStateFileDisappears() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let controller = try OverlayRuntimeController(
            controlToken: "control-token-heartbeat",
            runtimeDirectory: directory,
            stateRepairInterval: .milliseconds(20)
        )
        defer { controller.stop() }

        controller.start { _, _, _ in }
        let workspaceID = "6e7a71eb-df4f-4899-9aab-ee487f5a0649"
        let sessions = selectedSessionFixtures()
        #expect(controller.publish(
            visible: true,
            workspaceID: workspaceID,
            selectedSessions: sessions
        ))

        let stateURL = directory.appendingPathComponent(
            OverlayRuntimeController.stateFileName
        )
        try FileManager.default.removeItem(at: stateURL)
        #expect(!FileManager.default.fileExists(atPath: stateURL.path))

        try await Task<Never, Never>.sleep(nanoseconds: 100_000_000)

        let stateData = try Data(contentsOf: stateURL)
        let state = try JSONDecoder().decode(
            OverlayRuntimeState.self,
            from: stateData
        )
        #expect(state.controlToken == "control-token-heartbeat")
        #expect(state.visible)
        #expect(state.workspaceID == workspaceID)
        #expect(state.selectedSessions == sessions)
    }

    @Test
    func legacyStateWithoutSelectedSessionsDecodesAsEmpty() throws {
        let data = Data(
            """
            {
              "schema_version":"context_overlay_state.v1",
              "pid":123,
              "control_token":"token",
              "visible":true,
              "workspace_id":null,
              "updated_at":"2026-08-08T00:00:00Z"
            }
            """.utf8
        )

        let state = try JSONDecoder().decode(OverlayRuntimeState.self, from: data)

        #expect(state.selectedSessions.isEmpty)
    }

    @Test
    @MainActor
    func commandDistinguishesOmittedSelectionsFromExplicitClear() throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let controller = try OverlayRuntimeController(
            controlToken: "selection-token",
            runtimeDirectory: directory,
            stateRepairInterval: nil
        )
        defer { controller.stop() }
        var received: [[OverlaySelectedSession]?] = []
        controller.start { _, _, selectedSessions in
            received.append(selectedSessions)
        }

        try writeCommandJSON(
            """
            {
              "schema_version":"context_overlay_control.v1",
              "target_token":"selection-token",
              "visible":true,
              "workspace_id":null
            }
            """,
            to: directory
        )
        controller.processPendingControl()
        #expect(received.count == 1)
        #expect(received[0] == nil)

        try writeCommandJSON(
            """
            {
              "schema_version":"context_overlay_control.v1",
              "target_token":"selection-token",
              "visible":true,
              "workspace_id":null,
              "selected_sessions":[]
            }
            """,
            to: directory
        )
        controller.processPendingControl()
        #expect(received.count == 2)
        #expect(received[1]?.isEmpty == true)
    }

    @Test
    func selectedSessionsAreNormalizedOrderedAndBounded() {
        let values = [
            OverlaySelectedSession(
                provider: " Open Code ",
                sessionID: " open-3 ",
                title: " Open three ",
                ordinal: 3
            ),
            OverlaySelectedSession(
                provider: "CODEX",
                sessionID: " codex-1 ",
                title: "Codex one",
                ordinal: 1
            ),
            OverlaySelectedSession(
                provider: "daemonstate:claude-code",
                sessionID: "claude-2",
                title: " ",
                ordinal: 2
            ),
            OverlaySelectedSession(
                provider: "unsupported",
                sessionID: "ignored",
                title: "Ignored",
                ordinal: 2
            ),
            OverlaySelectedSession(
                provider: "codex",
                sessionID: "four",
                title: "Ignored",
                ordinal: 4
            ),
        ]

        let normalized = normalizedOverlaySelectedSessions(values)

        #expect(normalized.map(\.provider) == ["codex", "claude", "opencode"])
        #expect(normalized.map(\.sessionID) == ["codex-1", "claude-2", "open-3"])
        #expect(normalized.map(\.ordinalLabel) == ["1", "2", "3"])
        #expect(normalized[1].title == "Selected session")
    }

    @Test
    func runtimeDirectoryOverrideMustBeAbsolute() {
        let fallback = OverlayRuntimeController.defaultRuntimeDirectory(
            environment: [
                "DAEMONSTATE_OVERLAY_RUNTIME_DIR": "relative/runtime",
            ]
        )
        #expect(fallback == FileManager.default.temporaryDirectory)

        let configured = OverlayRuntimeController.defaultRuntimeDirectory(
            environment: [
                "DAEMONSTATE_OVERLAY_RUNTIME_DIR": "/tmp/context-overlay-tests",
            ]
        )
        #expect(configured.path == "/tmp/context-overlay-tests")
    }

    private func temporaryDirectory() -> URL {
        FileManager.default.temporaryDirectory.appendingPathComponent(
            "context-overlay-tests-\(UUID().uuidString)",
            isDirectory: true
        )
    }

    private func writeCommand(
        _ command: OverlayRuntimeCommand,
        to directory: URL
    ) throws {
        let data = try JSONEncoder().encode(command)
        try data.write(
            to: directory.appendingPathComponent(
                OverlayRuntimeController.controlFileName
            ),
            options: .atomic
        )
    }

    private func writeCommandJSON(_ json: String, to directory: URL) throws {
        try Data(json.utf8).write(
            to: directory.appendingPathComponent(
                OverlayRuntimeController.controlFileName
            ),
            options: .atomic
        )
    }

    private func selectedSessionFixtures() -> [OverlaySelectedSession] {
        [
            OverlaySelectedSession(
                provider: "codex",
                sessionID: "codex-session-1",
                title: "Implement the control",
                ordinal: 1
            ),
            OverlaySelectedSession(
                provider: "claude",
                sessionID: "claude-session-2",
                title: "Review the architecture",
                ordinal: 2
            ),
            OverlaySelectedSession(
                provider: "opencode",
                sessionID: "opencode-session-3",
                title: "Test the overlay",
                ordinal: 3
            ),
        ]
    }
}
