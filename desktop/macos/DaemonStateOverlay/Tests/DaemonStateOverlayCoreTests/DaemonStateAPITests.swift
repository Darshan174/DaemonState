#if canImport(FoundationNetworking)
import FoundationNetworking
#endif
import CryptoKit
import Foundation
import Testing
@testable import DaemonStateOverlayCore

@Suite(.serialized)
struct DaemonStateAPITests {
    @Test
    func workspacesUsesAPIPrefixOnceAndDecodesSummaries() async throws {
        defer { URLProtocolStub.reset() }
        let api = makeAPI { request in
            #expect(request.httpMethod == "GET")
            #expect(request.url?.path == "/api/workspaces")
            return URLProtocolStub.response(
                for: request,
                json: """
                [
                  {
                    "id": "workspace-1",
                    "name": "DaemonState",
                    "slug": "daemonstate",
                    "kind": "project",
                    "status": "active",
                    "repo_path": "/workspace/daemonstate",
                    "repo_paths": ["/workspace/daemonstate"]
                  }
                ]
                """
            )
        }

        let workspaces = try await api.workspaces()

        #expect(workspaces.count == 1)
        #expect(workspaces.first?.id == "workspace-1")
        #expect(workspaces.first?.repoPath == "/workspace/daemonstate")
    }

    @Test
    func projectContextReturnsOnlyVerifiedCopyReadyProduct() async throws {
        defer { URLProtocolStub.reset() }
        let content = "# Project Context\n\nWait for the next user lead."
        let digest = sha256(content)
        let api = makeAPI { request in
            #expect(request.httpMethod == "POST")
            #expect(request.url?.path == "/api/continuations/prepare")
            let body = try jsonBody(request)
            #expect(body["workspace_id"] as? String == "workspace-1")
            return URLProtocolStub.response(
                for: request,
                json: """
                {
                  "schema_version": "continuation.v1",
                  "task": {
                    "identity": {"workspace_id": "workspace-1"}
                  },
                  "checkpoint": {"id": "checkpoint-1"},
                  "source_session": {
                    "provider": "codex",
                    "session_id": "session-1"
                  },
                  "project_context": {
                    "schema_version": "continuation_staging_context.v1",
                    "scope": "project",
                    "content": "\(escaped(content))",
                    "sha256": "\(digest)",
                    "copy_ready": true,
                    "quality_issues": []
                  }
                }
                """
            )
        }

        let result = try await api.fetchContext(
            scope: .project,
            workspaceID: "workspace-1"
        )

        #expect(result.content == content)
        #expect(result.scope == .project)
        #expect(result.workspaceID == "workspace-1")
        #expect(result.schemaVersion == "continuation_staging_context.v1")
        #expect(result.sha256 == digest)
        #expect(result.checkpointID == "checkpoint-1")
        #expect(result.provider == "codex")
        #expect(result.sessionID == "session-1")
    }

    @Test
    func projectContextRejectsCopyBlockedResponseWithReason() async {
        defer { URLProtocolStub.reset() }
        let content = "# Project Context"
        let api = makeAPI { request in
            URLProtocolStub.response(
                for: request,
                json: """
                {
                  "schema_version": "continuation.v1",
                  "task": {
                    "identity": {"workspace_id": "workspace-1"}
                  },
                  "project_context": {
                    "schema_version": "continuation_staging_context.v1",
                    "scope": "project",
                    "content": "\(escaped(content))",
                    "sha256": "\(sha256(content))",
                    "copy_ready": false,
                    "quality_issues": [
                      {
                        "code": "required_artifact_unresolved",
                        "message": "A required artifact is unavailable.",
                        "blocks_copy": true
                      }
                    ]
                  }
                }
                """
            )
        }

        do {
            _ = try await api.fetchContext(
                scope: .project,
                workspaceID: "workspace-1"
            )
            Issue.record("Expected the copy gate to reject the response")
        } catch let error as DaemonStateError {
            #expect(
                error == .contextNotCopyReady(
                    scope: .project,
                    reasons: ["A required artifact is unavailable."]
                )
            )
        } catch {
            Issue.record("Unexpected error: \(error)")
        }
    }

    @Test
    func projectContextRejectsMismatchedSHA256() async {
        defer { URLProtocolStub.reset() }
        let api = makeAPI { request in
            URLProtocolStub.response(
                for: request,
                json: """
                {
                  "schema_version": "continuation.v1",
                  "task": {
                    "identity": {"workspace_id": "workspace-1"}
                  },
                  "project_context": {
                    "schema_version": "continuation_staging_context.v1",
                    "scope": "project",
                    "content": "tampered",
                    "sha256": "\(String(repeating: "0", count: 64))",
                    "copy_ready": true,
                    "quality_issues": []
                  }
                }
                """
            )
        }

        do {
            _ = try await api.fetchContext(
                scope: .project,
                workspaceID: "workspace-1"
            )
            Issue.record("Expected integrity validation to fail")
        } catch let error as DaemonStateError {
            guard case .integrityMismatch(scope: .project, _, _) = error else {
                Issue.record("Unexpected error: \(error)")
                return
            }
        } catch {
            Issue.record("Unexpected error: \(error)")
        }
    }

    @Test
    func projectContextRejectsMissingWorkspaceIdentity() async {
        defer { URLProtocolStub.reset() }
        let content = "# Project Context"
        let api = makeAPI { request in
            URLProtocolStub.response(
                for: request,
                json: """
                {
                  "schema_version": "continuation.v1",
                  "project_context": {
                    "schema_version": "continuation_staging_context.v1",
                    "scope": "project",
                    "content": "\(escaped(content))",
                    "sha256": "\(sha256(content))",
                    "copy_ready": true,
                    "quality_issues": []
                  }
                }
                """
            )
        }

        do {
            _ = try await api.fetchContext(
                scope: .project,
                workspaceID: "workspace-1"
            )
            Issue.record("Expected missing workspace identity to fail")
        } catch let error as DaemonStateError {
            guard case .identityMismatch(
                field: "continuation workspace",
                expected: "workspace-1",
                actual: nil
            ) = error else {
                Issue.record("Unexpected error: \(error)")
                return
            }
        } catch {
            Issue.record("Unexpected error: \(error)")
        }
    }

    @Test
    func sessionContextRefreshesAndUsesExactScopedCurrentCheckpoint() async throws {
        defer { URLProtocolStub.reset() }
        let content = "# Current Session Context\n\nContinue the exact active task."
        let contentSHA = sha256(content)
        var paths: [String] = []
        let api = makeAPI { request in
            let path = request.url!.path
            paths.append(path)
            switch path {
            case "/api/connectors/ai-session/refresh-linked":
                return URLProtocolStub.response(
                    for: request,
                    json: """
                    {
                      "workspace_id": "workspace-1",
                      "linked_sessions": 1,
                      "refreshed": 1,
                      "errors": []
                    }
                    """
                )
            case "/api/context/digest":
                #expect(
                    URLComponents(
                        url: request.url!,
                        resolvingAgainstBaseURL: false
                    )?.queryItems?.first(where: {
                        $0.name == "workspace_id"
                    })?.value == "workspace-1"
                )
                return URLProtocolStub.response(
                    for: request,
                    json: self.digestJSON()
                )
            case "/api/checkpoints/session-context-eligibility":
                return URLProtocolStub.response(
                    for: request,
                    json: self.eligibilityJSON()
                )
            case "/api/checkpoints/latest":
                let query = Dictionary(
                    uniqueKeysWithValues: URLComponents(
                        url: request.url!,
                        resolvingAgainstBaseURL: false
                    )!.queryItems!.map { ($0.name, $0.value ?? "") }
                )
                #expect(query["workspace_id"] == "workspace-1")
                #expect(query["provider"] == "codex")
                #expect(query["session_id"] == "session-1")
                return URLProtocolStub.response(
                    for: request,
                    json: self.checkpointJSON()
                )
            case "/api/checkpoints/checkpoint-1/handoff":
                #expect(request.httpMethod == "POST")
                return URLProtocolStub.response(
                    for: request,
                    json: self.handoffJSON(content: content, sha256: contentSHA)
                )
            default:
                throw URLError(.badURL)
            }
        }

        let result = try await api.fetchContext(
            scope: .session,
            workspaceID: "workspace-1"
        )

        #expect(
            paths == [
                "/api/connectors/ai-session/refresh-linked",
                "/api/context/digest",
                "/api/checkpoints/session-context-eligibility",
                "/api/checkpoints/latest",
                "/api/checkpoints/checkpoint-1/handoff",
            ]
        )
        #expect(result.content == content)
        #expect(result.scope == .session)
        #expect(result.provider == "codex")
        #expect(result.sessionID == "session-1")
        #expect(result.checkpointID == "checkpoint-1")
        #expect(result.boundarySequence == 20)
    }

    @Test
    func sessionContextCapturesTipWhenScopedCheckpointIsMissing() async throws {
        defer { URLProtocolStub.reset() }
        let content = "# Current Session Context"
        var captureBody: [String: Any]?
        let api = makeAPI { request in
            switch request.url!.path {
            case "/api/connectors/ai-session/refresh-linked":
                return URLProtocolStub.response(
                    for: request,
                    json: """
                    {
                      "workspace_id": "workspace-1",
                      "linked_sessions": 1,
                      "refreshed": 1,
                      "errors": []
                    }
                    """
                )
            case "/api/context/digest":
                return URLProtocolStub.response(
                    for: request,
                    json: self.digestJSON()
                )
            case "/api/checkpoints/session-context-eligibility":
                return URLProtocolStub.response(
                    for: request,
                    json: self.eligibilityJSON()
                )
            case "/api/checkpoints/latest":
                return URLProtocolStub.response(
                    for: request,
                    statusCode: 404,
                    json: #"{"detail":"Checkpoint not found"}"#
                )
            case "/api/checkpoints/capture":
                captureBody = try self.jsonBody(request)
                return URLProtocolStub.response(
                    for: request,
                    json: self.checkpointJSON()
                )
            case "/api/checkpoints/checkpoint-1/handoff":
                return URLProtocolStub.response(
                    for: request,
                    json: self.handoffJSON(
                        content: content,
                        sha256: self.sha256(content)
                    )
                )
            default:
                throw URLError(.badURL)
            }
        }

        _ = try await api.fetchContext(
            scope: .session,
            workspaceID: "workspace-1"
        )

        #expect(captureBody?["workspace_id"] as? String == "workspace-1")
        #expect(captureBody?["provider"] as? String == "codex")
        #expect(captureBody?["session_id"] as? String == "session-1")
        #expect(captureBody?["boundary_event_id"] == nil)
    }

    @Test
    func sessionContextStopsBeforeCheckpointCaptureWhenCompactionsAreMissing() async {
        defer { URLProtocolStub.reset() }
        var paths: [String] = []
        let api = makeAPI { request in
            let path = request.url!.path
            paths.append(path)
            switch path {
            case "/api/connectors/ai-session/refresh-linked":
                return URLProtocolStub.response(
                    for: request,
                    json: """
                    {
                      "workspace_id": "workspace-1",
                      "linked_sessions": 1,
                      "refreshed": 1,
                      "errors": []
                    }
                    """
                )
            case "/api/context/digest":
                return URLProtocolStub.response(
                    for: request,
                    json: self.digestJSON()
                )
            case "/api/checkpoints/session-context-eligibility":
                return URLProtocolStub.response(
                    for: request,
                    json: self.eligibilityJSON(compactionCount: 0)
                )
            default:
                throw URLError(.badURL)
            }
        }

        do {
            _ = try await api.fetchContext(
                scope: .session,
                workspaceID: "workspace-1"
            )
            Issue.record("Expected the compaction gate to reject Session Context")
        } catch let error as DaemonStateError {
            #expect(
                error == .activeSessionUnavailable(
                    "2 compactions required (0/2)."
                )
            )
        } catch {
            Issue.record("Unexpected error: \(error)")
        }
        #expect(
            paths == [
                "/api/connectors/ai-session/refresh-linked",
                "/api/context/digest",
                "/api/checkpoints/session-context-eligibility",
            ]
        )
    }

    @Test
    func sessionContextFailsClosedForUnassignedPrimarySession() async {
        defer { URLProtocolStub.reset() }
        let api = makeAPI { request in
            switch request.url!.path {
            case "/api/connectors/ai-session/refresh-linked":
                return URLProtocolStub.response(
                    for: request,
                    json: """
                    {
                      "workspace_id": "workspace-1",
                      "linked_sessions": 1,
                      "refreshed": 1,
                      "errors": []
                    }
                    """
                )
            case "/api/context/digest":
                return URLProtocolStub.response(
                    for: request,
                    json: """
                    {
                      "workspace_id": "workspace-1",
                      "activity": {
                        "schema_version": "now_activity.v1",
                        "primary": {
                          "kind": "agent_session",
                          "state": "unassigned",
                          "evidence_level": "session_unassigned",
                          "provider": "codex",
                          "session_id": "other-session",
                          "refreshable": true,
                          "project_match": {"status": "unknown"}
                        },
                        "recent_sessions": []
                      },
                      "current_goal": null
                    }
                    """
                )
            default:
                throw URLError(.badURL)
            }
        }

        do {
            _ = try await api.fetchContext(
                scope: .session,
                workspaceID: "workspace-1"
            )
            Issue.record("Expected unassigned activity to be rejected")
        } catch let error as DaemonStateError {
            guard case .activeSessionUnavailable = error else {
                Issue.record("Unexpected error: \(error)")
                return
            }
        } catch {
            Issue.record("Unexpected error: \(error)")
        }
    }

    @Test
    func promptLibraryValidatesWorkspaceContentAndIntegrity() async throws {
        defer { URLProtocolStub.reset() }
        let first = "Summarize the current diff."
        let second = "List only concrete regressions."
        let api = makeAPI { request in
            #expect(request.httpMethod == "GET")
            #expect(
                request.url?.path
                    == "/api/workspaces/workspace-1/prompt-snippets"
            )
            return URLProtocolStub.response(
                for: request,
                json: """
                {
                  "schema_version": "prompt_snippet_list.v1",
                  "workspace_id": "workspace-1",
                  "prompts": [
                    {
                      "id": "prompt-1",
                      "workspace_id": "workspace-1",
                      "content": "\(first)",
                      "content_sha256": "\(self.sha256(first))",
                      "use_count": 2
                    },
                    {
                      "id": "prompt-2",
                      "workspace_id": "workspace-1",
                      "content": "\(second)",
                      "content_sha256": "\(self.sha256(second))",
                      "use_count": 0
                    }
                  ]
                }
                """
            )
        }

        let prompts = try await api.promptSnippets(workspaceID: "workspace-1")

        #expect(prompts.map(\.id) == ["prompt-1", "prompt-2"])
        #expect(prompts.map(\.content) == [first, second])
        #expect(prompts.first?.useCount == 2)
    }

    @Test
    func promptLibraryRejectsTamperedContent() async {
        defer { URLProtocolStub.reset() }
        let api = makeAPI { request in
            URLProtocolStub.response(
                for: request,
                json: """
                {
                  "schema_version": "prompt_snippet_list.v1",
                  "workspace_id": "workspace-1",
                  "prompts": [{
                    "id": "prompt-1",
                    "workspace_id": "workspace-1",
                    "content": "tampered",
                    "content_sha256": "\(String(repeating: "0", count: 64))",
                    "use_count": 0
                  }]
                }
                """
            )
        }

        do {
            _ = try await api.promptSnippets(workspaceID: "workspace-1")
            Issue.record("Expected prompt integrity verification to fail")
        } catch let error as DaemonStateError {
            guard case .invalidPayload(let message) = error else {
                Issue.record("Unexpected error: \(error)")
                return
            }
            #expect(message.contains("integrity"))
        } catch {
            Issue.record("Unexpected error: \(error)")
        }
    }

    @Test
    func createPromptTrimsContentAndValidatesTheResponse() async throws {
        defer { URLProtocolStub.reset() }
        let content = "Write a concise release note."
        let api = makeAPI { request in
            #expect(request.httpMethod == "POST")
            #expect(
                request.url?.path
                    == "/api/workspaces/workspace-1/prompt-snippets"
            )
            let body = try self.jsonBody(request)
            #expect(body["content"] as? String == content)
            return URLProtocolStub.response(
                for: request,
                statusCode: 201,
                json: """
                {
                  "id": "prompt-1",
                  "workspace_id": "workspace-1",
                  "content": "\(content)",
                  "content_sha256": "\(self.sha256(content))",
                  "use_count": 0
                }
                """
            )
        }

        let prompt = try await api.createPromptSnippet(
            workspaceID: "workspace-1",
            content: "  \(content)\n"
        )

        #expect(prompt.content == content)
    }

    @Test
    func promptUsageDeduplicatesIDsAndUsesTheWorkspaceRoute() async throws {
        defer { URLProtocolStub.reset() }
        let api = makeAPI { request in
            #expect(request.httpMethod == "POST")
            #expect(
                request.url?.path
                    == "/api/workspaces/workspace-1/prompt-snippets/usage"
            )
            let body = try self.jsonBody(request)
            #expect(body["prompt_ids"] as? [String] == ["prompt-1", "prompt-2"])
            return URLProtocolStub.response(
                for: request,
                json: """
                {
                  "schema_version": "prompt_snippet_usage.v1",
                  "workspace_id": "workspace-1",
                  "updated": 2
                }
                """
            )
        }

        try await api.recordPromptUsage(
            workspaceID: "workspace-1",
            promptIDs: ["prompt-1", "prompt-1", "prompt-2"]
        )
    }

    private func makeAPI(
        handler: @escaping URLProtocolStub.Handler
    ) -> DaemonStateAPI {
        URLProtocolStub.install(handler)
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [URLProtocolStub.self]
        return DaemonStateAPI(
            baseURL: URL(string: "https://context.test/api")!,
            session: URLSession(configuration: configuration)
        )
    }

    private func jsonBody(_ request: URLRequest) throws -> [String: Any] {
        let body: Data
        if let requestBody = request.httpBody {
            body = requestBody
        } else if let stream = request.httpBodyStream {
            stream.open()
            defer { stream.close() }
            var streamedBody = Data()
            var buffer = [UInt8](repeating: 0, count: 1_024)
            while true {
                let count = stream.read(&buffer, maxLength: buffer.count)
                if count > 0 {
                    streamedBody.append(buffer, count: count)
                } else if count == 0 {
                    break
                } else {
                    throw stream.streamError ?? FixtureError.invalidRequestBody
                }
            }
            body = streamedBody
        } else {
            throw FixtureError.missingRequestBody
        }
        guard let object = try JSONSerialization.jsonObject(with: body)
            as? [String: Any] else {
            throw FixtureError.invalidRequestBody
        }
        return object
    }

    private func digestJSON() -> String {
        """
        {
          "workspace_id": "workspace-1",
          "activity": {
            "schema_version": "now_activity.v1",
            "primary": {
              "kind": "agent_session",
              "state": "snapshot",
              "evidence_level": "session_reported",
              "selected_for_now": true,
              "provider": "codex",
              "session_id": "historical-session",
              "refreshable": true,
              "request": "Finish the historical task.",
              "project_match": {"status": "relevant"}
            },
            "latest": {
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
                "provider": "codex",
                "session_id": "session-1",
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
    }

    private func checkpointJSON() -> String {
        """
        {
          "id": "checkpoint-1",
          "workspace_id": "workspace-1",
          "provider": "codex",
          "session_id": "session-1",
          "schema_version": "work_checkpoint.v10",
          "capture_status": "complete",
          "projection": {"valid": true},
          "currentness": {"state": "captured"},
          "boundary": {
            "event_id": "event-20",
            "sequence_number": 20,
            "session_tip_sequence": 20,
            "has_newer_events": false
          },
          "sections": {
            "goal": [{"statement": "Build the floating context overlay."}],
            "exact_next_action": [{"statement": "Compile and test the overlay."}]
          }
        }
        """
    }

    private func eligibilityJSON(compactionCount: Int = 2) -> String {
        """
        {
          "workspace_id": "workspace-1",
          "provider": "codex",
          "session_id": "session-1",
          "eligible": \(compactionCount >= 2 ? "true" : "false"),
          "compaction_count": \(compactionCount),
          "minimum_compactions": 2,
          "message": "2 compactions required (\(min(compactionCount, 2))/2)."
        }
        """
    }

    private func handoffJSON(content: String, sha256: String) -> String {
        """
        {
          "schema_version": "session_handoff.v1",
          "scope": "session",
          "provider": "codex",
          "session_id": "session-1",
          "checkpoint_id": "checkpoint-1",
          "boundary": {
            "event_id": "event-20",
            "sequence_number": 20,
            "session_tip_sequence": 20,
            "has_newer_events": false
          },
          "content": "\(escaped(content))",
          "sha256": "\(sha256)",
          "quality_report": {
            "copy_ready": true,
            "blocking_issues": []
          }
        }
        """
    }

    private func sha256(_ value: String) -> String {
        SHA256.hash(data: Data(value.utf8))
            .map { String(format: "%02x", $0) }
            .joined()
    }

    private func escaped(_ value: String) -> String {
        let data = try! JSONEncoder().encode(value)
        let encoded = String(data: data, encoding: .utf8)!
        return String(encoded.dropFirst().dropLast())
    }
}

private enum FixtureError: Error {
    case missingRequestBody
    case invalidRequestBody
}
