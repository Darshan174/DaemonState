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
    func workspaceContextUsesTaskFreeSnapshotEndpoint() async throws {
        defer { URLProtocolStub.reset() }
        let content = "# Workspace Context\n\nStable repository facts."
        let digest = sha256(content)
        let api = makeAPI { request in
            #expect(request.httpMethod == "POST")
            #expect(request.url?.path == "/api/context/prepare")
            let body = try jsonBody(request)
            #expect(body["workspace_id"] as? String == "workspace-1")
            #expect(body["repo_path"] as? String == "/workspace/daemonstate")
            #expect(body["mode"] as? String == "project_snapshot")
            #expect(body["objective_origin"] as? String == "project_snapshot")
            #expect(body["objective"] == nil)
            #expect(body["checkpoint_id"] == nil)
            return URLProtocolStub.response(
                for: request,
                json: workspaceContextJSON(content: content, sha256: digest)
            )
        }

        let result = try await api.fetchContext(
            scope: .project,
            workspaceID: "workspace-1",
            repoPath: "/workspace/daemonstate"
        )

        #expect(result.content == content)
        #expect(result.scope == .project)
        #expect(result.workspaceID == "workspace-1")
        #expect(result.schemaVersion == "workspace_context.v1")
        #expect(result.sha256 == digest)
        #expect(result.checkpointID == nil)
        #expect(result.provider == nil)
        #expect(result.sessionID == nil)
    }

    @Test
    func workspaceContextAcceptsWorkspaceFoundationV2() async throws {
        defer { URLProtocolStub.reset() }
        let content = "# Workspace Context\n\nVerified v2 repository facts."
        let api = makeAPI { request in
            URLProtocolStub.response(
                for: request,
                json: workspaceContextJSON(
                    content: content,
                    sha256: sha256(content),
                    foundationSchemaVersion: "workspace_foundation.v2"
                )
            )
        }

        let result = try await api.fetchContext(
            scope: .project,
            workspaceID: "workspace-1",
            repoPath: "/workspace/daemonstate"
        )

        #expect(result.content == content)
        #expect(result.scope == .project)
    }

    @Test
    func workspaceContextDoesNotUseContinuationCopyReadiness() async throws {
        defer { URLProtocolStub.reset() }
        let content = "# Workspace Context\n\nRepository-wide context."
        let api = makeAPI { request in
            URLProtocolStub.response(
                for: request,
                json: workspaceContextJSON(
                    content: content,
                    sha256: sha256(content),
                    extraTopLevel: """
                    ,"project_context": {
                      "copy_ready": false,
                      "quality_issues": [{"blocks_copy": true}]
                    }
                    """
                )
            )
        }

        let result = try await api.fetchContext(
            scope: .project,
            workspaceID: "workspace-1",
            repoPath: "/workspace/daemonstate"
        )

        #expect(result.content == content)
    }

    @Test
    func workspaceContextFailsClosedWhenControllerRejectsIt() async {
        defer { URLProtocolStub.reset() }
        let content = "# Workspace Context\n\nIncomplete repository context."
        let api = makeAPI { request in
            URLProtocolStub.response(
                for: request,
                json: workspaceContextJSON(
                    content: content,
                    sha256: sha256(content),
                    qualityControlAllowed: false
                )
            )
        }

        do {
            _ = try await api.fetchContext(
                scope: .project,
                workspaceID: "workspace-1",
                repoPath: "/workspace/daemonstate"
            )
            Issue.record("Expected the foundation quality gate to block copy")
        } catch let error as DaemonStateError {
            guard case let .contextNotCopyReady(scope: .project, reasons) = error else {
                Issue.record("Unexpected error: \(error)")
                return
            }
            #expect(reasons == [
                "Context quality control has not approved this artifact (rejected)."
            ])
        } catch {
            Issue.record("Unexpected error: \(error)")
        }
    }

    @Test
    func workspaceFoundationCanonicalHashesMatchTheBackendContract() throws {
        let json = """
        {
          "schema_version": "workspace_foundation.v1",
          "objective_independent": true,
          "compiled_at": "2026-08-05T12:00:00Z",
          "repository_state": {
            "snapshot_fingerprint": "\(String(repeating: "f", count: 64))",
            "captured_at": "2026-08-05T12:00:00Z"
          },
          "quality_report": {"copy_ready": true, "score": 68.92, "issues": []},
          "product_profile": {"name": "Café/工具"},
          "semantic_sha256": "fb53eb156b01af930671647371a5048ad902df5d6fa253e933d223ae4262fe06",
          "artifact_sha256": "108c8ef1067ce7319211ab03ecc3c2bee61917b255da256ed84fb9ebfb3266ee"
        }
        """
        let foundation = try JSONDecoder().decode(
            WorkspaceFoundationEnvelope.self,
            from: Data(json.utf8)
        )

        #expect(sha256(String(
            data: try foundation.canonicalSemanticData(),
            encoding: .utf8
        )!) == foundation.semanticSHA256)
        #expect(sha256(String(
            data: try foundation.canonicalArtifactData(),
            encoding: .utf8
        )!) == foundation.artifactSHA256)
    }

    @Test
    func workspaceFoundationRecognizesOnlySupportedSchemaVersions() throws {
        for schemaVersion in [
            "workspace_foundation.v1",
            "workspace_foundation.v2",
        ] {
            let foundation = try JSONDecoder().decode(
                WorkspaceFoundationEnvelope.self,
                from: Data("{\"schema_version\":\"\(schemaVersion)\"}".utf8)
            )
            #expect(foundation.hasSupportedSchemaVersion)
        }

        let unsupported = try JSONDecoder().decode(
            WorkspaceFoundationEnvelope.self,
            from: Data("{\"schema_version\":\"workspace_foundation.v3\"}".utf8)
        )
        #expect(!unsupported.hasSupportedSchemaVersion)
    }

    @Test
    func workspaceContextRejectsUnknownWorkspaceFoundationSchema() async {
        defer { URLProtocolStub.reset() }
        let content = "# Workspace Context\n\nRepository facts."
        let api = makeAPI { request in
            URLProtocolStub.response(
                for: request,
                json: workspaceContextJSON(
                    content: content,
                    sha256: sha256(content),
                    foundationSchemaVersion: "workspace_foundation.v3"
                )
            )
        }

        do {
            _ = try await api.fetchContext(
                scope: .project,
                workspaceID: "workspace-1",
                repoPath: "/workspace/daemonstate"
            )
            Issue.record("Expected an unknown foundation schema to fail")
        } catch let error as DaemonStateError {
            #expect(
                error == .invalidPayload(
                    "workspace foundation is missing or unsupported"
                )
            )
        } catch {
            Issue.record("Unexpected error: \(error)")
        }
    }

    @Test
    func workspaceContextRejectsMismatchedSHA256() async {
        defer { URLProtocolStub.reset() }
        let api = makeAPI { request in
            URLProtocolStub.response(
                for: request,
                json: workspaceContextJSON(
                    content: "# Workspace Context\n\ntampered",
                    sha256: String(repeating: "0", count: 64)
                )
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
    func workspaceContextRejectsTaskSpecificContinuationDocument() async {
        defer { URLProtocolStub.reset() }
        let content = """
        # Project / Workspace Context — NOT READY

        ## Session Context — task-specific child
        """
        let api = makeAPI { request in
            URLProtocolStub.response(
                for: request,
                json: workspaceContextJSON(
                    content: content,
                    sha256: sha256(content)
                )
            )
        }

        do {
            _ = try await api.fetchContext(
                scope: .project,
                workspaceID: "workspace-1",
                repoPath: "/workspace/daemonstate"
            )
            Issue.record("Expected the task-specific document to fail")
        } catch let error as DaemonStateError {
            #expect(
                error == .invalidPayload(
                    "Workspace Context has the wrong document boundary"
                )
            )
        } catch {
            Issue.record("Unexpected error: \(error)")
        }
    }

    @Test
    func workspaceContextRejectsMissingWorkspaceIdentity() async {
        defer { URLProtocolStub.reset() }
        let content = "# Workspace Context"
        let api = makeAPI { request in
            URLProtocolStub.response(
                for: request,
                json: workspaceContextJSON(
                    content: content,
                    sha256: sha256(content),
                    workspaceID: nil
                )
            )
        }

        do {
            _ = try await api.fetchContext(
                scope: .project,
                workspaceID: "workspace-1",
                repoPath: "/workspace/daemonstate"
            )
            Issue.record("Expected missing workspace identity to fail")
        } catch let error as DaemonStateError {
            guard case .identityMismatch(
                field: "workspace context workspace",
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
        var handoffBody: [String: Any]?
        let api = makeAPI { request in
            let path = request.url!.path
            paths.append(path)
            switch path {
            case "/api/session-library/latest":
                #expect(request.httpMethod == "POST")
                #expect(
                    try self.jsonBody(request)["workspace_id"] as? String
                        == "workspace-1"
                )
                return URLProtocolStub.response(
                    for: request,
                    json: self.latestLocalSessionJSON()
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
                handoffBody = try self.jsonBody(request)
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
                "/api/session-library/latest",
                "/api/checkpoints/latest",
                "/api/checkpoints/checkpoint-1/handoff",
            ]
        )
        #expect(handoffBody?["workspace_id"] as? String == "workspace-1")
        #expect(handoffBody?["handoff_origin"] as? String == "current_active")
        #expect(result.content == content)
        #expect(result.scope == .session)
        #expect(result.provider == "codex")
        #expect(result.sessionID == "session-1")
        #expect(result.checkpointID == "checkpoint-1")
        #expect(result.boundarySequence == 20)
    }

    @Test
    func explicitHistoricalSessionContextUsesExactIdentityWithoutRecapture() async throws {
        defer { URLProtocolStub.reset() }
        let content = "# Current Session Context\n\nContinue Claude session nine."
        var paths: [String] = []
        var handoffBody: [String: Any]?
        let api = makeAPI { request in
            let path = request.url!.path
            paths.append(path)
            switch path {
            case "/api/checkpoints/session-context-eligibility",
                 "/api/checkpoints/latest":
                let query = Dictionary(
                    uniqueKeysWithValues: URLComponents(
                        url: request.url!,
                        resolvingAgainstBaseURL: false
                    )!.queryItems!.map { ($0.name, $0.value ?? "") }
                )
                #expect(query["workspace_id"] == "workspace-1")
                #expect(query["provider"] == "claude")
                #expect(query["session_id"] == "claude-session-9")
                if path.hasSuffix("session-context-eligibility") {
                    return URLProtocolStub.response(
                        for: request,
                        json: self.eligibilityJSON(
                            provider: "claude",
                            sessionID: "claude-session-9"
                        )
                    )
                }
                return URLProtocolStub.response(
                    for: request,
                    json: self.checkpointJSON(
                        provider: "claude",
                        sessionID: "claude-session-9",
                        checkpointID: "claude-checkpoint-9",
                        currentnessState: "historical"
                    )
                )
            case "/api/checkpoints/claude-checkpoint-9/handoff":
                handoffBody = try self.jsonBody(request)
                return URLProtocolStub.response(
                    for: request,
                    json: self.handoffJSON(
                        content: content,
                        sha256: self.sha256(content),
                        provider: "claude",
                        sessionID: "claude-session-9",
                        checkpointID: "claude-checkpoint-9"
                    )
                )
            default:
                throw URLError(.badURL)
            }
        }

        let result = try await api.fetchSessionContext(
            workspaceID: " workspace-1 ",
            provider: "daemonstate:claude-code",
            sessionID: " claude-session-9 "
        )

        #expect(
            paths == [
                "/api/checkpoints/session-context-eligibility",
                "/api/checkpoints/latest",
                "/api/checkpoints/claude-checkpoint-9/handoff",
            ]
        )
        #expect(result.content == content)
        #expect(result.provider == "claude")
        #expect(result.sessionID == "claude-session-9")
        #expect(result.checkpointID == "claude-checkpoint-9")
        #expect(handoffBody?["workspace_id"] as? String == "workspace-1")
        #expect(handoffBody?["handoff_origin"] == nil)
    }

    @Test
    func explicitSessionContextCapturesTheExactSessionWhenLatestIsMissing() async throws {
        defer { URLProtocolStub.reset() }
        let content = "# Current Session Context"
        var paths: [String] = []
        var captureBody: [String: Any]?
        let api = makeAPI { request in
            let path = request.url!.path
            paths.append(path)
            switch path {
            case "/api/checkpoints/session-context-eligibility":
                return URLProtocolStub.response(
                    for: request,
                    json: self.eligibilityJSON(
                        provider: "opencode",
                        sessionID: "open-session-3"
                    )
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
                    json: self.checkpointJSON(
                        provider: "opencode",
                        sessionID: "open-session-3",
                        checkpointID: "open-checkpoint-3"
                    )
                )
            case "/api/checkpoints/open-checkpoint-3/handoff":
                return URLProtocolStub.response(
                    for: request,
                    json: self.handoffJSON(
                        content: content,
                        sha256: self.sha256(content),
                        provider: "opencode",
                        sessionID: "open-session-3",
                        checkpointID: "open-checkpoint-3"
                    )
                )
            default:
                throw URLError(.badURL)
            }
        }

        _ = try await api.fetchSessionContext(
            workspaceID: "workspace-1",
            provider: "opencode",
            sessionID: "open-session-3"
        )

        #expect(
            paths == [
                "/api/checkpoints/session-context-eligibility",
                "/api/checkpoints/latest",
                "/api/checkpoints/capture",
                "/api/checkpoints/open-checkpoint-3/handoff",
            ]
        )
        #expect(captureBody?["workspace_id"] as? String == "workspace-1")
        #expect(captureBody?["provider"] as? String == "opencode")
        #expect(captureBody?["session_id"] as? String == "open-session-3")
    }

    @Test
    func explicitSessionContextRejectsMismatchedCheckpointIdentity() async {
        defer { URLProtocolStub.reset() }
        var paths: [String] = []
        let api = makeAPI { request in
            let path = request.url!.path
            paths.append(path)
            switch path {
            case "/api/checkpoints/session-context-eligibility":
                return URLProtocolStub.response(
                    for: request,
                    json: self.eligibilityJSON(
                        provider: "claude",
                        sessionID: "claude-session-9"
                    )
                )
            case "/api/checkpoints/latest":
                return URLProtocolStub.response(
                    for: request,
                    json: self.checkpointJSON(
                        provider: "claude",
                        sessionID: "another-session",
                        checkpointID: "wrong-checkpoint"
                    )
                )
            default:
                throw URLError(.badURL)
            }
        }

        do {
            _ = try await api.fetchSessionContext(
                workspaceID: "workspace-1",
                provider: "claude",
                sessionID: "claude-session-9"
            )
            Issue.record("Expected the mismatched checkpoint to fail")
        } catch let error as DaemonStateError {
            #expect(
                error == .identityMismatch(
                    field: "checkpoint session",
                    expected: "claude-session-9",
                    actual: "another-session"
                )
            )
        } catch {
            Issue.record("Unexpected error: \(error)")
        }
        #expect(
            paths == [
                "/api/checkpoints/session-context-eligibility",
                "/api/checkpoints/latest",
            ]
        )
    }

    @Test
    func sessionContextRetriesTheWholeFlowAfterATransientServerError() async throws {
        defer { URLProtocolStub.reset() }
        let content = "# Current Session Context\n\nRetry the transient failure."
        var discoveryAttempts = 0
        var paths: [String] = []
        let api = makeAPI(sessionContextRetryDelays: [.zero]) { request in
            let path = request.url!.path
            paths.append(path)
            switch path {
            case "/api/session-library/latest":
                discoveryAttempts += 1
                if discoveryAttempts == 1 {
                    return URLProtocolStub.response(
                        for: request,
                        statusCode: 500,
                        json: """
                        {
                          "error": {
                            "code": "internal_error",
                            "message": "An internal error occurred.",
                            "request_id": "request-1"
                          }
                        }
                        """
                    )
                }
                return URLProtocolStub.response(
                    for: request,
                    json: self.latestLocalSessionJSON()
                )
            case "/api/checkpoints/latest":
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

        let result = try await api.fetchContext(
            scope: .session,
            workspaceID: "workspace-1"
        )

        #expect(result.content == content)
        #expect(discoveryAttempts == 2)
        #expect(
            paths.prefix(2)
                == [
                    "/api/session-library/latest",
                    "/api/session-library/latest",
                ]
        )
    }

    @Test
    func currentActiveHandoffMismatchRetriesDiscoveryCheckpointAndHandoff() async throws {
        defer { URLProtocolStub.reset() }
        let content = "# Current Session Context\n\nContinue after tip drift."
        var discoveryAttempts = 0
        var checkpointAttempts = 0
        var handoffAttempts = 0
        var paths: [String] = []
        let api = makeAPI(sessionContextRetryDelays: [.zero]) { request in
            let path = request.url!.path
            paths.append(path)
            switch path {
            case "/api/session-library/latest":
                discoveryAttempts += 1
                #expect(request.httpMethod == "POST")
                #expect(
                    try self.jsonBody(request)["workspace_id"] as? String
                        == "workspace-1"
                )
                return URLProtocolStub.response(
                    for: request,
                    json: self.latestLocalSessionJSON()
                )
            case "/api/checkpoints/latest":
                checkpointAttempts += 1
                return URLProtocolStub.response(
                    for: request,
                    json: self.checkpointJSON()
                )
            case "/api/checkpoints/checkpoint-1/handoff":
                handoffAttempts += 1
                #expect(
                    try self.jsonBody(request)["handoff_origin"] as? String
                        == "current_active"
                )
                if handoffAttempts == 1 {
                    return URLProtocolStub.response(
                        for: request,
                        statusCode: 409,
                        json: """
                        {
                          "detail": {
                            "code": "current_active_handoff_mismatch",
                            "message": "The current session tip changed."
                          }
                        }
                        """
                    )
                }
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

        let result = try await api.fetchContext(
            scope: .session,
            workspaceID: "workspace-1"
        )

        #expect(result.content == content)
        #expect(discoveryAttempts == 2)
        #expect(checkpointAttempts == 2)
        #expect(handoffAttempts == 2)
        #expect(
            paths == [
                "/api/session-library/latest",
                "/api/checkpoints/latest",
                "/api/checkpoints/checkpoint-1/handoff",
                "/api/session-library/latest",
                "/api/checkpoints/latest",
                "/api/checkpoints/checkpoint-1/handoff",
            ]
        )
    }

    @Test
    func repeatedCurrentActiveHandoffMismatchBecomesActionable() async {
        defer { URLProtocolStub.reset() }
        var handoffAttempts = 0
        let api = makeAPI(sessionContextRetryDelays: [.zero]) { request in
            switch request.url!.path {
            case "/api/session-library/latest":
                return URLProtocolStub.response(
                    for: request,
                    json: self.latestLocalSessionJSON()
                )
            case "/api/checkpoints/latest":
                return URLProtocolStub.response(
                    for: request,
                    json: self.checkpointJSON()
                )
            case "/api/checkpoints/checkpoint-1/handoff":
                handoffAttempts += 1
                return URLProtocolStub.response(
                    for: request,
                    statusCode: 409,
                    json: """
                    {
                      "detail": {
                        "code": "current_active_handoff_mismatch",
                        "message": "The current session tip changed."
                      }
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
            Issue.record("Expected repeated current-session drift to fail")
        } catch let error as DaemonStateError {
            #expect(
                error == .activeSessionUnavailable(
                    "the session changed while its context was being prepared. "
                        + "Wait for the current provider response to finish, then try again."
                )
            )
            #expect(
                error.localizedDescription
                    == "Current Session Context is unavailable: the session changed while its context was being prepared. Wait for the current provider response to finish, then try again."
            )
        } catch {
            Issue.record("Unexpected error: \(error)")
        }
        #expect(handoffAttempts == 2)
    }

    @Test
    func nestedInternalErrorsPreserveTheirRequestID() async {
        defer { URLProtocolStub.reset() }
        let api = makeAPI { request in
            URLProtocolStub.response(
                for: request,
                statusCode: 500,
                json: """
                {
                  "error": {
                    "code": "internal_error",
                    "message": "An internal error occurred.",
                    "request_id": "request-123"
                  }
                }
                """
            )
        }

        do {
            _ = try await api.workspaces()
            Issue.record("Expected the internal error response to fail")
        } catch let error as DaemonStateError {
            #expect(
                error == .httpError(
                    statusCode: 500,
                    code: "internal_error",
                    message: "An internal error occurred. Request request-123."
                )
            )
        } catch {
            Issue.record("Unexpected error: \(error)")
        }
    }

    @Test
    func detailErrorsPreserveTheResponseRequestID() async {
        defer { URLProtocolStub.reset() }
        let api = makeAPI { request in
            URLProtocolStub.response(
                for: request,
                statusCode: 500,
                headerFields: ["X-Request-ID": "request-from-header-456"],
                json: """
                {
                  "detail": {
                    "code": "context_prepare_failed",
                    "message": "The repository observation could not be compiled."
                  }
                }
                """
            )
        }

        do {
            _ = try await api.workspaces()
            Issue.record("Expected the context preparation response to fail")
        } catch let error as DaemonStateError {
            #expect(
                error == .httpError(
                    statusCode: 500,
                    code: "context_prepare_failed",
                    message: "The repository observation could not be compiled. "
                        + "Request request-from-header-456."
                )
            )
        } catch {
            Issue.record("Unexpected error: \(error)")
        }
    }

    @Test
    func validationErrorListsRemainActionable() async {
        defer { URLProtocolStub.reset() }
        let api = makeAPI { request in
            URLProtocolStub.response(
                for: request,
                statusCode: 422,
                headerFields: ["X-Request-ID": "validation-request-789"],
                json: """
                {
                  "detail": [
                    {
                      "loc": ["body", "objective"],
                      "msg": "String should have at least 1 character"
                    }
                  ]
                }
                """
            )
        }

        do {
            _ = try await api.workspaces()
            Issue.record("Expected request validation to fail")
        } catch let error as DaemonStateError {
            #expect(
                error == .httpError(
                    statusCode: 422,
                    code: "validation_error",
                    message: "body.objective: String should have at least 1 character "
                        + "Request validation-request-789."
                )
            )
        } catch {
            Issue.record("Unexpected error: \(error)")
        }
    }

    @Test
    func sessionContextCapturesTipWhenScopedCheckpointIsMissing() async throws {
        defer { URLProtocolStub.reset() }
        let content = "# Current Session Context"
        var captureBody: [String: Any]?
        let api = makeAPI { request in
            switch request.url!.path {
            case "/api/session-library/latest":
                return URLProtocolStub.response(
                    for: request,
                    json: self.latestLocalSessionJSON()
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
    func currentSessionCopiesBackgroundWithoutExecutionHintsOrCompactionPrecheck() async throws {
        defer { URLProtocolStub.reset() }
        let content = "# Current Session Context\n\nContinue the active session."
        var paths: [String] = []
        var handoffBody: [String: Any]?
        let api = makeAPI { request in
            let path = request.url!.path
            paths.append(path)
            switch path {
            case "/api/session-library/latest":
                #expect(request.httpMethod == "POST")
                #expect(
                    try self.jsonBody(request)["workspace_id"] as? String
                        == "workspace-1"
                )
                return URLProtocolStub.response(
                    for: request,
                    json: self.latestLocalSessionJSON()
                )
            case "/api/checkpoints/latest":
                return URLProtocolStub.response(
                    for: request,
                    json: self.checkpointJSON(hasExecutionHints: false)
                )
            case "/api/checkpoints/checkpoint-1/handoff":
                handoffBody = try self.jsonBody(request)
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

        let result = try await api.fetchContext(
            scope: .session,
            workspaceID: "workspace-1"
        )

        #expect(
            paths == [
                "/api/session-library/latest",
                "/api/checkpoints/latest",
                "/api/checkpoints/checkpoint-1/handoff",
            ]
        )
        #expect(result.content == content)
        #expect(handoffBody?["workspace_id"] as? String == "workspace-1")
        #expect(handoffBody?["handoff_origin"] as? String == "current_active")
    }

    @Test
    func explicitHistoricalSessionKeepsActionableCompactionGate() async {
        defer { URLProtocolStub.reset() }
        var paths: [String] = []
        let api = makeAPI { request in
            let path = request.url!.path
            paths.append(path)
            switch path {
            case "/api/checkpoints/session-context-eligibility":
                return URLProtocolStub.response(
                    for: request,
                    json: self.eligibilityJSON(
                        provider: "claude",
                        sessionID: "claude-session-9",
                        compactionCount: 1
                    )
                )
            default:
                throw URLError(.badURL)
            }
        }

        do {
            _ = try await api.fetchSessionContext(
                workspaceID: "workspace-1",
                provider: "claude",
                sessionID: "claude-session-9"
            )
            Issue.record("Expected the historical compaction gate to reject Session Context")
        } catch let error as DaemonStateError {
            #expect(
                error == .sessionContextCompactionsRequired(
                    compactionCount: 1,
                    minimumCompactions: 2
                )
            )
            #expect(
                error.localizedDescription
                    == "Session Context is not ready yet: 1 of 2 provider compactions detected. Continue the source session, then try again."
            )
        } catch {
            Issue.record("Unexpected error: \(error)")
        }
        #expect(paths == ["/api/checkpoints/session-context-eligibility"])
    }

    @Test
    func sessionContextFailsClosedWhenLatestLocalSessionIsUnavailable() async {
        defer { URLProtocolStub.reset() }
        let api = makeAPI { request in
            switch request.url!.path {
            case "/api/session-library/latest":
                return URLProtocolStub.response(
                    for: request,
                    json: """
                    {
                      "sync": {
                        "workspace_id": "workspace-1",
                        "mode": "latest"
                      },
                      "session": null
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
            Issue.record("Expected missing latest local session to be rejected")
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
        sessionContextRetryDelays: [Duration]? = nil,
        handler: @escaping URLProtocolStub.Handler
    ) -> DaemonStateAPI {
        URLProtocolStub.install(handler)
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [URLProtocolStub.self]
        let baseURL = URL(string: "https://context.test/api")!
        let session = URLSession(configuration: configuration)
        if let sessionContextRetryDelays {
            return DaemonStateAPI(
                baseURL: baseURL,
                session: session,
                sessionContextRetryDelays: sessionContextRetryDelays
            )
        }
        return DaemonStateAPI(baseURL: baseURL, session: session)
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

    private func latestLocalSessionJSON(
        provider: String = "codex",
        sessionID: String = "session-1"
    ) -> String {
        """
        {
          "sync": {
            "workspace_id": "workspace-1",
            "mode": "latest"
          },
          "session": {
            "connector_type": "\(provider)",
            "session_id": "\(sessionID)"
          }
        }
        """
    }

    private func checkpointJSON(
        workspaceID: String = "workspace-1",
        provider: String = "codex",
        sessionID: String = "session-1",
        checkpointID: String = "checkpoint-1",
        currentnessState: String = "captured",
        hasExecutionHints: Bool = true
    ) -> String {
        let sections = hasExecutionHints ? """
        {
          "goal": [{"statement": "Build the floating context overlay."}],
          "exact_next_action": [{"statement": "Compile and test the overlay."}]
        }
        """ : "{}"
        return """
        {
          "id": "\(checkpointID)",
          "workspace_id": "\(workspaceID)",
          "provider": "\(provider)",
          "session_id": "\(sessionID)",
          "schema_version": "work_checkpoint.v10",
          "capture_status": "\(hasExecutionHints ? "complete" : "incomplete")",
          "projection": {"valid": \(hasExecutionHints)},
          "currentness": {"state": "\(currentnessState)"},
          "boundary": {
            "event_id": "event-20",
            "sequence_number": 20,
            "session_tip_sequence": 20,
            "has_newer_events": false
          },
          "sections": \(sections)
        }
        """
    }

    private func eligibilityJSON(
        provider: String = "codex",
        sessionID: String = "session-1",
        compactionCount: Int = 2
    ) -> String {
        """
        {
          "workspace_id": "workspace-1",
          "provider": "\(provider)",
          "session_id": "\(sessionID)",
          "eligible": \(compactionCount >= 2 ? "true" : "false"),
          "compaction_count": \(compactionCount),
          "minimum_compactions": 2,
          "message": "2 compactions required (\(min(compactionCount, 2))/2)."
        }
        """
    }

    private func handoffJSON(
        content: String,
        sha256: String,
        provider: String = "codex",
        sessionID: String = "session-1",
        checkpointID: String = "checkpoint-1"
    ) -> String {
        """
        {
          "schema_version": "session_background.v1",
          "context_role": "background_only",
          "scope": "session",
          "provider": "\(provider)",
          "session_id": "\(sessionID)",
          "checkpoint_id": "\(checkpointID)",
          "boundary": {
            "event_id": "event-20",
            "sequence_number": 20,
            "session_tip_sequence": 20,
            "has_newer_events": false
          },
          "content": "\(escaped(content))",
          "sha256": "\(sha256)",
          "quality_control": \(qualityControlJSON(sha256: sha256)),
          "operation_capabilities": {
            "clipboard_copy": {"allowed": true},
            "automatic_execution": {"allowed": false}
          },
          "quality_report": {
            "copy_ready": true,
            "blocking_issues": []
          },
          "readiness_dimensions": {
            "semantic_readiness": {
              "copy_ready": true
            },
            "evidence_access": {
              "blocks_copy": false
            }
          }
        }
        """
    }

    private func workspaceContextJSON(
        content: String,
        sha256: String,
        workspaceID: String? = "workspace-1",
        repoPath: String = "/workspace/daemonstate",
        foundationSchemaVersion: String = "workspace_foundation.v1",
        foundationCopyReady: Bool = true,
        qualityControlAllowed: Bool = true,
        extraTopLevel: String = ""
    ) -> String {
        let workspaceValue = workspaceID.map {
            "\"\(escaped($0))\""
        } ?? "null"
        let qualityIssues: [[String: Any]] = foundationCopyReady ? [] : [[
            "id": "issue.product_missing",
            "blocking": true,
            "message": "No safe repository-stated product purpose was found.",
        ]]
        var foundation: [String: Any] = [
            "schema_version": foundationSchemaVersion,
            "objective_independent": true,
            "repository_state": [
                "snapshot_fingerprint": "repo-state-fingerprint",
            ],
            "quality_report": [
                "copy_ready": foundationCopyReady,
                "issues": qualityIssues,
            ],
        ]
        let semanticData = try! JSONSerialization.data(
            withJSONObject: foundation,
            options: [.sortedKeys, .withoutEscapingSlashes]
        )
        let semanticSHA256 = self.sha256(
            String(data: semanticData, encoding: .utf8)!
        )
        foundation["semantic_sha256"] = semanticSHA256
        let artifactData = try! JSONSerialization.data(
            withJSONObject: foundation,
            options: [.sortedKeys, .withoutEscapingSlashes]
        )
        let artifactSHA256 = self.sha256(
            String(data: artifactData, encoding: .utf8)!
        )
        foundation["artifact_sha256"] = artifactSHA256
        let foundationData = try! JSONSerialization.data(
            withJSONObject: foundation,
            options: [.sortedKeys, .withoutEscapingSlashes]
        )
        let foundationJSON = String(data: foundationData, encoding: .utf8)!
        return """
        {
          "context_pack_id": "context-pack-1",
          "schema_version": "context_pack.v2",
          "markdown": "\(escaped(content))",
          "quality_control": \(qualityControlJSON(sha256: sha256, allowed: qualityControlAllowed)),
          "selected_context": [],
          "excluded_context": [],
          "manifest": {
            "schema_version": "context_pack.v2",
            "context_pack_id": "context-pack-1",
            "workspace_id": \(workspaceValue),
            "objective_kind": "project_snapshot",
            "focus": {"kind": "project_snapshot"},
            "repo_state": {
              "repo_path": "\(escaped(repoPath))",
              "state_fingerprint": "repo-state-fingerprint",
              "workspace_foundation_sha256": "\(semanticSHA256)",
              "workspace_foundation_artifact_sha256": "\(artifactSHA256)"
            },
            "token_accounting": {"within_budget": true},
            "rendering": {
              "within_budget": true,
              "markdown_sha256": "\(sha256)"
            },
            "workspace_foundation": \(foundationJSON)
          }
          \(extraTopLevel)
        }
        """
    }

    private func qualityControlJSON(sha256: String, allowed: Bool = true) -> String {
        """
        {
          "schema_version": "context_quality_activation.v1",
          "status": "\(allowed ? "active" : "rejected")",
          "copy_allowed": \(allowed),
          "candidate_id": "candidate-1",
          "active_candidate_id": "candidate-1",
          "artifact_sha256": "\(sha256)"
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
