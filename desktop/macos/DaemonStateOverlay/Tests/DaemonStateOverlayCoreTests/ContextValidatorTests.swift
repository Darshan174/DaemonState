import CryptoKit
import Foundation
import Testing
@testable import DaemonStateOverlayCore

@Suite
struct ContextValidatorTests {
    @Test
    func multiplePlausibleSessionsFailClosedWithoutExplicitSelection() throws {
        let digest = try decode(
            ContextDigestEnvelope.self,
            """
            {
              "workspace_id": "workspace-1",
              "activity": {
                "schema_version": "now_activity.v1",
                "primary": {
                  "kind": "agent_session",
                  "state": "snapshot",
                  "evidence_level": "session_reported",
                  "selected_for_now": false,
                  "provider": "codex",
                  "session_id": "session-1",
                  "refreshable": true,
                  "request": "Build the floating context overlay.",
                  "project_match": {"status": "relevant"}
                },
                "recent_sessions": [
                  {
                    "kind": "agent_session",
                    "state": "snapshot",
                    "evidence_level": "session_reported",
                    "selected_for_now": false,
                    "provider": "claude",
                    "session_id": "session-2",
                    "refreshable": true,
                    "request": "Build the floating context overlay.",
                    "project_match": {"status": "relevant"}
                  }
                ]
              },
              "current_goal": {
                "title": "Build the floating context overlay."
              }
            }
            """
        )

        do {
            _ = try ContextValidator.activeSession(
                from: digest,
                workspaceID: "workspace-1"
            )
            Issue.record("Expected ambiguous active-session identity to fail")
        } catch let error as DaemonStateError {
            #expect(
                error == .activeSessionUnavailable(
                    "choose an active session in Library, then try again"
                )
            )
        }
    }

    @Test
    func matchingLinkedRefreshFailureIsRejected() throws {
        let refresh = try decode(
            RefreshLinkedEnvelope.self,
            """
            {
              "workspace_id": "workspace-1",
              "linked_sessions": 2,
              "refreshed": 1,
              "errors": [
                {
                  "connector_type": "codex",
                  "session_id": "session-1",
                  "message": "Transcript file disappeared."
                }
              ]
            }
            """
        )

        do {
            try ContextValidator.confirmRefresh(
                refresh,
                workspaceID: "workspace-1",
                activeSession: ActiveSessionIdentity(
                    provider: "codex",
                    sessionID: "session-1"
                )
            )
            Issue.record("Expected the active-session refresh failure to block")
        } catch let error as DaemonStateError {
            #expect(
                error == .sessionRefreshUnconfirmed(
                    "Transcript file disappeared."
                )
            )
        }
    }

    @Test
    func cappedRefreshAcceptsAnExactActiveSessionIdentity() throws {
        let refresh = try decode(
            RefreshLinkedEnvelope.self,
            """
            {
              "workspace_id": "workspace-1",
              "linked_sessions": 8,
              "refreshed": 8,
              "refreshed_sessions": [
                {"connector_type": "claude", "session_id": "session-2"},
                {"connector_type": "codex", "session_id": "session-1"},
                {"connector_type": "codex", "session_id": "session-3"},
                {"connector_type": "codex", "session_id": "session-4"},
                {"connector_type": "codex", "session_id": "session-5"},
                {"connector_type": "codex", "session_id": "session-6"},
                {"connector_type": "codex", "session_id": "session-7"},
                {"connector_type": "codex", "session_id": "session-8"}
              ],
              "errors": []
            }
            """
        )

        try ContextValidator.confirmRefresh(
            refresh,
            workspaceID: "workspace-1",
            activeSession: activeSession
        )
    }

    @Test
    func sessionCopyReadyGateRejectsBlockingIssue() throws {
        let handoff = try sessionHandoff(
            content: "Verified session context",
            sha256: sha256("Verified session context"),
            copyReady: false
        )

        do {
            _ = try ContextValidator.verifiedSessionContext(
                handoff,
                workspaceID: "workspace-1",
                activeSession: activeSession,
                checkpoint: try checkpoint()
            )
            Issue.record("Expected the session copy gate to block")
        } catch let error as DaemonStateError {
            #expect(
                error == .contextNotCopyReady(
                    scope: .session,
                    reasons: ["The session boundary is superseded."]
                )
            )
        }
    }

    @Test
    func sessionSHA256MismatchIsRejected() throws {
        let handoff = try sessionHandoff(
            content: "Tampered session context",
            sha256: String(repeating: "0", count: 64),
            copyReady: true
        )

        do {
            _ = try ContextValidator.verifiedSessionContext(
                handoff,
                workspaceID: "workspace-1",
                activeSession: activeSession,
                checkpoint: try checkpoint()
            )
            Issue.record("Expected session integrity validation to fail")
        } catch let error as DaemonStateError {
            guard case .integrityMismatch(scope: .session, _, _) = error else {
                Issue.record("Unexpected error: \(error)")
                return
            }
        }
    }

    @Test
    func sessionBoundaryEventMismatchIsRejected() throws {
        let handoff = try sessionHandoff(
            content: "Verified session context",
            sha256: sha256("Verified session context"),
            copyReady: true,
            boundaryEventID: "event-21"
        )

        do {
            _ = try ContextValidator.verifiedSessionContext(
                handoff,
                workspaceID: "workspace-1",
                activeSession: activeSession,
                checkpoint: try checkpoint()
            )
            Issue.record("Expected the boundary event mismatch to fail")
        } catch let error as DaemonStateError {
            guard case .identityMismatch(
                field: "handoff boundary event",
                expected: "event-20",
                actual: "event-21"
            ) = error else {
                Issue.record("Unexpected error: \(error)")
                return
            }
        }
    }

    @Test
    func sessionHandoffWithNewerEventsIsRejectedEvenIfCopyReady() throws {
        let handoff = try sessionHandoff(
            content: "Stale session context",
            sha256: sha256("Stale session context"),
            copyReady: true,
            sessionTipSequence: 21,
            hasNewerEvents: true
        )

        do {
            _ = try ContextValidator.verifiedSessionContext(
                handoff,
                workspaceID: "workspace-1",
                activeSession: activeSession,
                checkpoint: try checkpoint()
            )
            Issue.record("Expected a superseded handoff to fail")
        } catch let error as DaemonStateError {
            guard case .activeSessionUnavailable = error else {
                Issue.record("Unexpected error: \(error)")
                return
            }
        }
    }

    @Test
    func sessionCheckpointWithoutBoundaryEventFailsClosed() throws {
        let handoff = try sessionHandoff(
            content: "Verified session context",
            sha256: sha256("Verified session context"),
            copyReady: true
        )
        let malformedCheckpoint = try checkpoint(boundaryEventID: nil)
        #expect(!ContextValidator.isCurrentSessionTip(malformedCheckpoint))

        do {
            _ = try ContextValidator.verifiedSessionContext(
                handoff,
                workspaceID: "workspace-1",
                activeSession: activeSession,
                checkpoint: malformedCheckpoint
            )
            Issue.record("Expected a missing checkpoint boundary event to fail")
        } catch let error as DaemonStateError {
            #expect(
                error == .invalidPayload(
                    "checkpoint.boundary.event_id is missing"
                )
            )
        }
    }

    @Test
    func supportedCheckpointSchemasPreserveCurrentTipValidation() throws {
        for schemaVersion in [
            "work_checkpoint.v5",
            "work_checkpoint.v6",
            "work_checkpoint.v7",
            "work_checkpoint.v8",
        ] {
            let candidate = try checkpoint(schemaVersion: schemaVersion)
            #expect(ContextValidator.isCurrentSessionTip(candidate))
            try ContextValidator.requireCurrentSessionTip(candidate)
        }
    }

    @Test
    func unsupportedCheckpointSchemaStillFailsClosed() throws {
        let candidate = try checkpoint(schemaVersion: "work_checkpoint.v9")
        #expect(!ContextValidator.isCurrentSessionTip(candidate))

        do {
            try ContextValidator.requireCurrentSessionTip(candidate)
            Issue.record("Expected an unsupported checkpoint schema to fail")
        } catch let error as DaemonStateError {
            #expect(
                error == .unsupportedSchema(
                    expected: (
                        "work_checkpoint.v5, work_checkpoint.v6, "
                        + "work_checkpoint.v7, or work_checkpoint.v8"
                    ),
                    actual: "work_checkpoint.v9"
                )
            )
        }
    }

    private var activeSession: ActiveSessionIdentity {
        ActiveSessionIdentity(provider: "codex", sessionID: "session-1")
    }

    private func checkpoint(
        schemaVersion: String = "work_checkpoint.v8",
        boundaryEventID: String? = "event-20"
    ) throws -> LatestCheckpointEnvelope {
        let eventIdentity = boundaryEventID.map {
            #""event_id": "\#($0)","#
        } ?? ""
        return try decode(
            LatestCheckpointEnvelope.self,
            """
            {
              "id": "checkpoint-1",
              "workspace_id": "workspace-1",
              "provider": "codex",
              "session_id": "session-1",
              "schema_version": "\(schemaVersion)",
              "capture_status": "complete",
              "projection": {"valid": true},
              "currentness": {"state": "captured"},
              "boundary": {
                \(eventIdentity)
                "sequence_number": 20,
                "session_tip_sequence": 20,
                "has_newer_events": false
              },
              "sections": {
                "goal": [{"statement": "Build the floating context overlay."}],
                "exact_next_action": [{"statement": "Compile the package."}]
              }
            }
            """
        )
    }

    private func sessionHandoff(
        content: String,
        sha256: String,
        copyReady: Bool,
        boundaryEventID: String = "event-20",
        sessionTipSequence: Int = 20,
        hasNewerEvents: Bool = false
    ) throws -> SessionHandoffEnvelope {
        try decode(
            SessionHandoffEnvelope.self,
            """
            {
              "schema_version": "session_handoff.v1",
              "scope": "session",
              "provider": "codex",
              "session_id": "session-1",
              "checkpoint_id": "checkpoint-1",
              "boundary": {
                "event_id": "\(boundaryEventID)",
                "sequence_number": 20,
                "session_tip_sequence": \(sessionTipSequence),
                "has_newer_events": \(hasNewerEvents)
              },
              "content": "\(content)",
              "sha256": "\(sha256)",
              "quality_report": {
                "copy_ready": \(copyReady),
                "blocking_issues": [
                  {
                    "severity": "blocking",
                    "message": "The session boundary is superseded."
                  }
                ]
              }
            }
            """
        )
    }

    private func decode<Value: Decodable>(
        _ type: Value.Type,
        _ json: String
    ) throws -> Value {
        try JSONDecoder().decode(type, from: Data(json.utf8))
    }

    private func sha256(_ value: String) -> String {
        SHA256.hash(data: Data(value.utf8))
            .map { String(format: "%02x", $0) }
            .joined()
    }
}
