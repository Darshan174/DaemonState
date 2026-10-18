import CryptoKit
import Foundation
import Testing
@testable import DaemonStateOverlayCore

struct BackgroundContextContractTests {
    private let session = ActiveSessionIdentity(provider: "codex", sessionID: "session-1")
    private let background = "# Session Context\n\nThe user explored two alternatives.\n\nAttachment unavailable. Awaiting user instruction."

    @Test
    func currentBackgroundBoundaryDoesNotRequireAnObjectiveOrNextAction() throws {
        let checkpoint = try checkpoint()
        #expect(ContextValidator.isCurrentSessionBackgroundTip(checkpoint))
        try ContextValidator.requireCurrentSessionBackgroundTip(checkpoint)
        // Execution-oriented consumers keep their existing stricter contract.
        #expect(!ContextValidator.isCurrentSessionTip(checkpoint))
    }

    @Test
    func backgroundAcceptsHonestLimitationsWithoutReceiverOrExecutionReadiness() throws {
        let result = try validateSession(sessionPayload())
        #expect(result.content == background)
        #expect(result.schemaVersion == "session_background.v1")
        #expect(result.checkpointID == "checkpoint-1")
    }

    @Test
    func backgroundUsesCanonicalCopyAndControllerGatesWithoutLegacySemanticReadiness() throws {
        var payload = sessionPayload()
        payload["readiness_dimensions"] = ["semantic_readiness": ["copy_ready": false]]
        let result = try validateSession(payload)
        #expect(result.content == background)
    }

    @Test
    func historicalBackgroundRetainsItsBoundCaptureWhenNewerEventsExist() throws {
        var payload = sessionPayload()
        payload["boundary"] = [
            "event_id": "event-20",
            "sequence_number": 20,
            "session_tip_sequence": 21,
            "has_newer_events": true,
        ]
        let result = try validateSession(payload)
        #expect(result.boundarySequence == 20)
    }

    @Test
    func backgroundStillRejectsBrokenScopeIdentityRoleAndContent() throws {
        let mutations: [(String, Any)] = [
            ("scope", "project"),
            ("provider", "claude"),
            ("session_id", "another-session"),
            ("checkpoint_id", "another-checkpoint"),
            ("context_role", "automatic_handoff"),
            ("sha256", String(repeating: "0", count: 64)),
        ]
        for (key, value) in mutations {
            var payload = sessionPayload()
            payload[key] = value
            #expect(throws: DaemonStateError.self) { try validateSession(payload) }
        }
    }

    @Test
    func backgroundRequiresExplicitClipboardPermissionDespiteOtherReadyFlags() throws {
        var payload = sessionPayload()
        payload["operation_capabilities"] = ["clipboard_copy": ["allowed": false]]
        #expect(throws: DaemonStateError.self) { try validateSession(payload) }
    }

    @Test
    func backgroundRejectsMissingRejectedOrUnboundControllerApproval() throws {
        var payload = sessionPayload()
        payload.removeValue(forKey: "quality_control")
        #expect(throws: DaemonStateError.self) { try validateSession(payload) }
        let mutations: [(String, Any)] = [
            ("status", "rejected"),
            ("copy_allowed", false),
            ("active_candidate_id", "another-candidate"),
            ("artifact_sha256", String(repeating: "0", count: 64)),
            ("schema_version", "context_quality_activation.v99"),
        ]
        for (key, value) in mutations {
            payload = sessionPayload()
            var control = qualityControl(content: background)
            control[key] = value
            payload["quality_control"] = control
            #expect(throws: DaemonStateError.self) { try validateSession(payload) }
        }
    }

    @Test
    func workspaceAcceptsControllerApprovedLimitationsAndCanonicalSnapshotBinding() throws {
        let result = try validateWorkspace(workspacePayload())
        #expect(result.scope == .project)
        #expect(result.content.contains("No current verification was observed."))
    }

    @Test
    func workspaceRejectsControllerRejectionDespiteLegacyCopyReady() throws {
        var payload = workspacePayload(foundationCopyReady: true)
        let content = payload["markdown"] as! String
        var control = qualityControl(content: content)
        control["status"] = "rejected"
        control["copy_allowed"] = false
        payload["quality_control"] = control
        #expect(throws: DaemonStateError.self) { try validateWorkspace(payload) }
    }

    @Test
    func workspaceRequiresControllerBoundToDeliveredContent() throws {
        var payload = workspacePayload()
        payload.removeValue(forKey: "quality_control")
        #expect(throws: DaemonStateError.self) { try validateWorkspace(payload) }
        payload["quality_control"] = qualityControl(content: "Another artifact")
        #expect(throws: DaemonStateError.self) { try validateWorkspace(payload) }
    }

    @Test
    func workspaceStillRequiresFoundationCoreIntegrityReadiness() throws {
        #expect(throws: DaemonStateError.self) {
            try validateWorkspace(workspacePayload(foundationCopyReady: false))
        }
    }

    private func validateSession(_ payload: [String: Any]) throws -> VerifiedContext {
        try ContextValidator.verifiedSessionContext(
            decode(SessionHandoffEnvelope.self, payload),
            workspaceID: "workspace-1",
            activeSession: session,
            checkpoint: checkpoint()
        )
    }

    private func validateWorkspace(_ payload: [String: Any]) throws -> VerifiedContext {
        try ContextValidator.verifiedWorkspaceContext(
            decode(WorkspaceContextPackEnvelope.self, payload),
            workspaceID: "workspace-1",
            repoPath: "/workspace/project"
        )
    }

    private func checkpoint() throws -> LatestCheckpointEnvelope {
        try decode(LatestCheckpointEnvelope.self, [
            "id": "checkpoint-1",
            "workspace_id": "workspace-1",
            "provider": "codex",
            "session_id": "session-1",
            "schema_version": "work_checkpoint.v10",
            "capture_status": "incomplete",
            "projection": ["valid": false, "state": "missing_scoped_next_action"],
            "currentness": ["state": "historical"],
            "boundary": [
                "event_id": "event-20", "sequence_number": 20,
                "session_tip_sequence": 20, "has_newer_events": false,
            ],
            "sections": ["goal": [], "exact_next_action": []],
        ])
    }

    private func sessionPayload() -> [String: Any] {
        [
            "schema_version": "session_background.v1",
            "context_role": "background_only",
            "scope": "session",
            "provider": "codex",
            "session_id": "session-1",
            "checkpoint_id": "checkpoint-1",
            "boundary": [
                "event_id": "event-20", "sequence_number": 20,
                "session_tip_sequence": 20, "has_newer_events": false,
            ],
            "content": background,
            "sha256": sha256(background),
            "quality_control": qualityControl(content: background),
            "quality_report": [
                "status": "ready_with_limitations", "copy_ready": true,
                "automatic_execution_ready": false, "blocking_issues": [],
                "warnings": ["USER_OBJECTIVE_MISSING", "REQUIRED_DEPENDENCY_MISSING"],
            ],
            "readiness_dimensions": [
                "semantic_readiness": ["copy_ready": true],
                "evidence_access": ["blocks_copy": true, "receiver_ready": false],
            ],
            "operation_capabilities": [
                "clipboard_copy": ["allowed": true],
                "automatic_execution": ["allowed": false],
            ],
        ]
    }

    private func workspacePayload(foundationCopyReady: Bool = true) -> [String: Any] {
        let content = "# Workspace Context\n\nNo current verification was observed."
        var foundation: [String: Any] = [
            "schema_version": "workspace_foundation.v2",
            "objective_independent": true,
            "repository_state": ["snapshot_fingerprint": "snapshot-fingerprint"],
            "quality_report": [
                "copy_ready": foundationCopyReady,
                "issues": [["id": "coverage-limited", "blocking": false, "message": "Partial coverage"]],
            ],
        ]
        foundation["semantic_sha256"] = sha256(canonicalJSON(foundation))
        foundation["artifact_sha256"] = sha256(canonicalJSON(foundation))
        return [
            "schema_version": "context_pack.v2", "context_pack_id": "pack-1",
            "markdown": content, "quality_control": qualityControl(content: content),
            "manifest": [
                "schema_version": "context_pack.v2", "context_pack_id": "pack-1",
                "workspace_id": "workspace-1", "objective_kind": "project_snapshot",
                "focus": ["kind": "project_snapshot"],
                "repo_state": [
                    "repo_path": "/workspace/project",
                    "state_fingerprint": "different-state-fingerprint",
                    "snapshot_fingerprint": "snapshot-fingerprint",
                    "workspace_foundation_sha256": foundation["semantic_sha256"]!,
                    "workspace_foundation_artifact_sha256": foundation["artifact_sha256"]!,
                ],
                "token_accounting": ["within_budget": true],
                "rendering": ["within_budget": true, "markdown_sha256": sha256(content)],
                "workspace_foundation": foundation,
            ],
        ]
    }

    private func qualityControl(content: String) -> [String: Any] {
        [
            "schema_version": "context_quality_activation.v1", "status": "active",
            "copy_allowed": true, "candidate_id": "candidate-1",
            "active_candidate_id": "candidate-1", "artifact_sha256": sha256(content),
        ]
    }

    private func decode<T: Decodable>(_ type: T.Type, _ value: [String: Any]) throws -> T {
        try JSONDecoder().decode(type, from: Data(canonicalJSON(value).utf8))
    }

    private func canonicalJSON(_ value: [String: Any]) -> String {
        String(data: try! JSONSerialization.data(
            withJSONObject: value, options: [.sortedKeys, .withoutEscapingSlashes]
        ), encoding: .utf8)!
    }

    private func sha256(_ value: String) -> String {
        SHA256.hash(data: Data(value.utf8)).map { String(format: "%02x", $0) }.joined()
    }
}
