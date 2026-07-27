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
        controller.start { visible, workspaceID in
            receivedVisible = visible
            receivedWorkspaceID = workspaceID
        }
        let workspaceID = "6e7a71eb-df4f-4899-9aab-ee487f5a0649"
        controller.publish(visible: true, workspaceID: workspaceID)

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

        try writeCommand(
            OverlayRuntimeCommand(
                schemaVersion: "context_overlay_control.v1",
                targetToken: "another-process",
                visible: false,
                workspaceID: workspaceID
            ),
            to: directory
        )
        controller.processPendingControl()
        #expect(receivedVisible == nil)

        try writeCommand(
            OverlayRuntimeCommand(
                schemaVersion: "context_overlay_control.v1",
                targetToken: "control-token-1",
                visible: false,
                workspaceID: workspaceID
            ),
            to: directory
        )
        controller.processPendingControl()
        #expect(receivedVisible == false)
        #expect(receivedWorkspaceID == workspaceID)
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
}
