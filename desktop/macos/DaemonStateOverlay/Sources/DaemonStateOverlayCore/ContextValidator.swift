import CryptoKit
import Foundation

enum ContextValidator {
    static let currentCheckpointSchema = "work_checkpoint.v10"
    static let checkpointSchemas = Set([
        "work_checkpoint.v5",
        "work_checkpoint.v6",
        "work_checkpoint.v7",
        "work_checkpoint.v8",
        "work_checkpoint.v9",
        "work_checkpoint.v10",
    ])
    static let checkpointSchemaExpectation =
        "work_checkpoint.v5, work_checkpoint.v6, work_checkpoint.v7, work_checkpoint.v8, work_checkpoint.v9, or work_checkpoint.v10"
    static let sessionSchema = "session_handoff.v1"
    static let continuationSchema = "continuation.v1"
    static let projectSchema = "continuation_staging_context.v1"
    static let activitySchema = "now_activity.v1"
    static let linkedRefreshLimit = 8

    static func activeSession(
        from digest: ContextDigestEnvelope,
        workspaceID: String
    ) throws -> ActiveSessionIdentity {
        if let returnedWorkspaceID = visible(digest.workspaceID),
           returnedWorkspaceID != workspaceID {
            throw DaemonStateError.identityMismatch(
                field: "digest workspace",
                expected: workspaceID,
                actual: returnedWorkspaceID
            )
        }
        guard digest.activity?.schemaVersion == activitySchema else {
            throw DaemonStateError.unsupportedSchema(
                expected: activitySchema,
                actual: digest.activity?.schemaVersion
            )
        }
        let latest = digest.activity?.latest
        let newestLinkedSession = digest.activity?.recentSessions?.first
        let active = (
            latest != nil
                ? newestLinkedSession ?? latest
                : digest.activity?.primary
        )
        guard let active else {
            throw DaemonStateError.activeSessionUnavailable(
                "the selected project has no active session"
            )
        }
        guard normalizedKey(active.kind) == "agent_session" else {
            throw DaemonStateError.activeSessionUnavailable(
                "the newest project activity is not a linked AI session"
            )
        }
        if normalizedKey(active.evidenceLevel) == "session_unassigned"
            || normalizedKey(active.state) == "unassigned" {
            throw DaemonStateError.activeSessionUnavailable(
                "the active AI session is not assigned to this project"
            )
        }

        let relevance = normalizedKey(
            active.projectMatch?.status ?? active.workspaceRelevance?.status
        )
        guard relevance == "relevant" else {
            throw DaemonStateError.activeSessionUnavailable(
                "the active AI session has not been confirmed as project-relevant"
            )
        }
        guard active.refreshable == true else {
            throw DaemonStateError.activeSessionUnavailable(
                "the active AI session is not linked to a refreshable local transcript"
            )
        }

        let provider = normalizeProvider(active.provider ?? active.tool)
        guard !provider.isEmpty else {
            throw DaemonStateError.activeSessionUnavailable(
                "the active AI session has no provider identity"
            )
        }
        guard let sessionID = visible(active.sessionID) else {
            throw DaemonStateError.activeSessionUnavailable(
                "the active AI session has no session identity"
            )
        }

        if let currentGoal = visible(digest.currentGoal?.title) {
            guard let sessionGoal = visible(
                active.request ?? active.title ?? active.sessionTitle
            ), taskTextCompatible(currentGoal, sessionGoal) else {
                throw DaemonStateError.activeSessionUnavailable(
                    "the active AI session does not match the workspace's current goal"
                )
            }
        }

        // A non-nil `latest` opts into the backend's newest-activity contract;
        // `recent_sessions[0]` is its newest assigned session and is the same
        // default used by Continue. Older servers expose only `primary`;
        // retain their ambiguity check unless Library selected it.
        if latest == nil, active.selectedForNow != true {
            let candidates = [active] + (digest.activity?.recentSessions ?? [])
            var identities = Set<String>()
            for candidate in candidates where candidateIsPlausible(
                candidate,
                currentGoal: visible(digest.currentGoal?.title)
            ) {
                let candidateProvider = normalizeProvider(
                    candidate.provider ?? candidate.tool
                )
                guard let candidateSessionID = visible(candidate.sessionID) else {
                    continue
                }
                identities.insert("\(candidateProvider)\u{0}\(candidateSessionID)")
            }
            guard identities.count == 1 else {
                throw DaemonStateError.activeSessionUnavailable(
                    "choose an active session in Library, then try again"
                )
            }
        }
        return ActiveSessionIdentity(provider: provider, sessionID: sessionID)
    }

    static func confirmRefresh(
        _ refresh: RefreshLinkedEnvelope,
        workspaceID: String,
        activeSession: ActiveSessionIdentity
    ) throws {
        guard visible(refresh.workspaceID) == workspaceID else {
            throw DaemonStateError.identityMismatch(
                field: "refresh workspace",
                expected: workspaceID,
                actual: refresh.workspaceID
            )
        }
        if let skipped = visible(refresh.skippedReason) {
            throw DaemonStateError.sessionRefreshUnconfirmed(
                "the service skipped linked-session refresh (\(skipped))"
            )
        }
        guard let linked = refresh.linkedSessions, linked > 0 else {
            throw DaemonStateError.sessionRefreshUnconfirmed(
                "no refreshable linked session was found"
            )
        }
        let failures = refresh.errors ?? []
        guard let refreshed = refresh.refreshed,
              refreshed + failures.count == linked else {
            throw DaemonStateError.sessionRefreshUnconfirmed(
                "the refresh response did not account for every linked session"
            )
        }
        if let failure = failures.first(where: {
            normalizeProvider($0.connectorType) == activeSession.provider
                && visible($0.sessionID) == activeSession.sessionID
        }) {
            throw DaemonStateError.sessionRefreshUnconfirmed(
                visible(failure.message) ?? "the active session refresh failed"
            )
        }

        if let refreshedSessions = refresh.refreshedSessions {
            let identities = refreshedSessions.compactMap { session -> String? in
                let provider = normalizeProvider(session.connectorType)
                guard !provider.isEmpty,
                      let sessionID = visible(session.sessionID) else {
                    return nil
                }
                return "\(provider)\u{0}\(sessionID)"
            }
            guard identities.count == refreshed,
                  Set(identities).count == identities.count else {
                throw DaemonStateError.sessionRefreshUnconfirmed(
                    "the refresh response returned incomplete or duplicate session identities"
                )
            }
            let activeIdentity = (
                "\(activeSession.provider)\u{0}\(activeSession.sessionID)"
            )
            guard identities.contains(activeIdentity) else {
                throw DaemonStateError.sessionRefreshUnconfirmed(
                    "the selected active session was not refreshed"
                )
            }
            return
        }

        // Backward compatibility for older local services that expose only
        // aggregate counts. Below the cap every linked candidate was attempted;
        // at the cap an omitted ninth session would make identity ambiguous.
        guard linked < linkedRefreshLimit else {
            throw DaemonStateError.sessionRefreshUnconfirmed(
                "the refresh response reached its \(linkedRefreshLimit)-session cap and cannot prove which session was refreshed"
            )
        }
    }

    static func validateCheckpointIdentity(
        _ checkpoint: LatestCheckpointEnvelope,
        workspaceID: String,
        activeSession: ActiveSessionIdentity
    ) throws {
        guard let checkpointID = visible(checkpoint.id) else {
            throw DaemonStateError.invalidPayload("checkpoint.id is missing")
        }
        guard visible(checkpoint.workspaceID) == workspaceID else {
            throw DaemonStateError.identityMismatch(
                field: "checkpoint workspace",
                expected: workspaceID,
                actual: checkpoint.workspaceID
            )
        }
        guard normalizeProvider(checkpoint.provider) == activeSession.provider else {
            throw DaemonStateError.identityMismatch(
                field: "checkpoint provider",
                expected: activeSession.provider,
                actual: checkpoint.provider
            )
        }
        guard visible(checkpoint.sessionID) == activeSession.sessionID else {
            throw DaemonStateError.identityMismatch(
                field: "checkpoint session",
                expected: activeSession.sessionID,
                actual: checkpoint.sessionID
            )
        }
        guard !checkpointID.isEmpty else {
            throw DaemonStateError.invalidPayload("checkpoint.id is empty")
        }
    }

    static func isCurrentSessionTip(_ checkpoint: LatestCheckpointEnvelope) -> Bool {
        guard checkpoint.schemaVersion == currentCheckpointSchema,
              normalizedKey(checkpoint.captureStatus) == "complete",
              checkpoint.projection?.valid == true,
              normalizedKey(checkpoint.currentness?.state) == "captured",
              visible(checkpoint.boundary?.eventID) != nil,
              checkpoint.boundary?.hasNewerEvents == false,
              let sequence = checkpoint.boundary?.sequenceNumber,
              let tipSequence = checkpoint.boundary?.sessionTipSequence,
              sequence == tipSequence,
              visible(checkpoint.sections?.goal?.first?.statement) != nil,
              visible(checkpoint.sections?.exactNextAction?.first?.statement) != nil else {
            return false
        }
        return true
    }

    static func requireCurrentSessionTip(_ checkpoint: LatestCheckpointEnvelope) throws {
        guard checkpoint.schemaVersion.map(checkpointSchemas.contains) == true else {
            throw DaemonStateError.unsupportedSchema(
                expected: checkpointSchemaExpectation,
                actual: checkpoint.schemaVersion
            )
        }
        guard isCurrentSessionTip(checkpoint) else {
            throw DaemonStateError.activeSessionUnavailable(
                "the service did not return a complete checkpoint at the current session tip"
            )
        }
    }

    static func verifiedSessionContext(
        _ handoff: SessionHandoffEnvelope,
        workspaceID: String,
        activeSession: ActiveSessionIdentity,
        checkpoint: LatestCheckpointEnvelope
    ) throws -> VerifiedContext {
        guard handoff.schemaVersion == sessionSchema else {
            throw DaemonStateError.unsupportedSchema(
                expected: sessionSchema,
                actual: handoff.schemaVersion
            )
        }
        guard handoff.scope == ContextScope.session.rawValue else {
            throw DaemonStateError.scopeMismatch(
                expected: .session,
                actual: handoff.scope
            )
        }
        guard normalizeProvider(handoff.provider) == activeSession.provider else {
            throw DaemonStateError.identityMismatch(
                field: "handoff provider",
                expected: activeSession.provider,
                actual: handoff.provider
            )
        }
        guard visible(handoff.sessionID) == activeSession.sessionID else {
            throw DaemonStateError.identityMismatch(
                field: "handoff session",
                expected: activeSession.sessionID,
                actual: handoff.sessionID
            )
        }
        let checkpointID = visible(checkpoint.id)!
        guard visible(handoff.checkpointID) == checkpointID else {
            throw DaemonStateError.identityMismatch(
                field: "handoff checkpoint",
                expected: checkpointID,
                actual: handoff.checkpointID
            )
        }
        guard let expectedSequence = checkpoint.boundary?.sequenceNumber,
              handoff.boundary?.sequenceNumber == expectedSequence else {
            throw DaemonStateError.identityMismatch(
                field: "handoff boundary",
                expected: checkpoint.boundary?.sequenceNumber.map(String.init) ?? "missing",
                actual: handoff.boundary?.sequenceNumber.map(String.init)
            )
        }
        guard let checkpointEventID = visible(checkpoint.boundary?.eventID) else {
            throw DaemonStateError.invalidPayload(
                "checkpoint.boundary.event_id is missing"
            )
        }
        guard visible(handoff.boundary?.eventID) == checkpointEventID else {
            throw DaemonStateError.identityMismatch(
                field: "handoff boundary event",
                expected: checkpointEventID,
                actual: handoff.boundary?.eventID
            )
        }
        guard handoff.boundary?.sessionTipSequence == expectedSequence,
              handoff.boundary?.hasNewerEvents == false else {
            throw DaemonStateError.activeSessionUnavailable(
                "the handoff is not bound to the current session tip"
            )
        }
        guard let copyReady = handoff.qualityReport?.copyReady else {
            throw DaemonStateError.invalidPayload(
                "handoff.quality_report.copy_ready is missing"
            )
        }
        guard copyReady else {
            let issues = handoff.qualityReport?.blockingIssues
                ?? handoff.qualityReport?.issues?.filter {
                    normalizedKey($0.severity) == "blocking"
                }
                ?? []
            throw DaemonStateError.contextNotCopyReady(
                scope: .session,
                reasons: issueMessages(issues)
            )
        }
        let verified = try verifyContent(
            handoff.content,
            expectedSHA256: handoff.sha256,
            scope: .session
        )
        return VerifiedContext(
            content: verified.content,
            scope: .session,
            workspaceID: workspaceID,
            schemaVersion: sessionSchema,
            sha256: verified.sha256,
            checkpointID: checkpointID,
            provider: activeSession.provider,
            sessionID: activeSession.sessionID,
            boundarySequence: expectedSequence
        )
    }

    static func verifiedProjectContext(
        _ continuation: ContinuationEnvelope,
        workspaceID: String
    ) throws -> VerifiedContext {
        guard continuation.schemaVersion == continuationSchema else {
            throw DaemonStateError.unsupportedSchema(
                expected: continuationSchema,
                actual: continuation.schemaVersion
            )
        }
        guard let identityWorkspaceID = visible(
            continuation.task?.identity?.workspaceID
        ) else {
            throw DaemonStateError.identityMismatch(
                field: "continuation workspace",
                expected: workspaceID,
                actual: nil
            )
        }
        guard identityWorkspaceID == workspaceID else {
            throw DaemonStateError.identityMismatch(
                field: "continuation workspace",
                expected: workspaceID,
                actual: identityWorkspaceID
            )
        }
        guard let project = continuation.projectContext else {
            throw DaemonStateError.invalidPayload("project_context is missing")
        }
        guard project.schemaVersion == projectSchema else {
            throw DaemonStateError.unsupportedSchema(
                expected: projectSchema,
                actual: project.schemaVersion
            )
        }
        guard project.scope == ContextScope.project.rawValue else {
            throw DaemonStateError.scopeMismatch(
                expected: .project,
                actual: project.scope
            )
        }
        guard let copyReady = project.copyReady else {
            throw DaemonStateError.invalidPayload("project_context.copy_ready is missing")
        }
        guard copyReady else {
            let blocking = (project.qualityIssues ?? []).filter {
                $0.blocksCopy != false
            }
            throw DaemonStateError.contextNotCopyReady(
                scope: .project,
                reasons: issueMessages(blocking)
            )
        }
        let verified = try verifyContent(
            project.content,
            expectedSHA256: project.sha256,
            scope: .project
        )
        return VerifiedContext(
            content: verified.content,
            scope: .project,
            workspaceID: workspaceID,
            schemaVersion: projectSchema,
            sha256: verified.sha256,
            checkpointID: visible(continuation.checkpoint?.id),
            provider: normalizeProvider(continuation.sourceSession?.provider).nilIfEmpty,
            sessionID: visible(continuation.sourceSession?.sessionID)
        )
    }

    static func normalizeProvider(_ value: String?) -> String {
        var normalized = normalizedKey(value)
        if normalized.hasPrefix("daemonstate:") {
            normalized.removeFirst("daemonstate:".count)
        }
        switch normalized {
        case "claude_code", "claude-code":
            return "claude"
        case "open_code", "open-code":
            return "opencode"
        default:
            return normalized
        }
    }

    private static func candidateIsPlausible(
        _ candidate: DigestPrimaryEnvelope,
        currentGoal: String?
    ) -> Bool {
        guard normalizedKey(candidate.kind) == "agent_session",
              normalizedKey(candidate.state) != "unassigned",
              normalizedKey(candidate.evidenceLevel) != "session_unassigned",
              normalizedKey(
                  candidate.projectMatch?.status
                      ?? candidate.workspaceRelevance?.status
              ) == "relevant",
              !normalizeProvider(candidate.provider ?? candidate.tool).isEmpty,
              visible(candidate.sessionID) != nil else {
            return false
        }
        guard let currentGoal else {
            return true
        }
        guard let sessionGoal = visible(
            candidate.request ?? candidate.title ?? candidate.sessionTitle
        ) else {
            return false
        }
        return taskTextCompatible(currentGoal, sessionGoal)
    }

    private static func verifyContent(
        _ content: String?,
        expectedSHA256: String?,
        scope: ContextScope
    ) throws -> (content: String, sha256: String) {
        guard let content, !content.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            throw DaemonStateError.invalidPayload("\(scope.rawValue) content is empty")
        }
        guard let expected = visible(expectedSHA256)?.lowercased(),
              expected.count == 64,
              expected.unicodeScalars.allSatisfy({
                  CharacterSet(charactersIn: "0123456789abcdef").contains($0)
              }) else {
            throw DaemonStateError.invalidSHA256(scope: scope)
        }
        let digest = SHA256.hash(data: Data(content.utf8))
        let actual = digest.map { String(format: "%02x", $0) }.joined()
        guard actual == expected else {
            throw DaemonStateError.integrityMismatch(
                scope: scope,
                expected: expected,
                actual: actual
            )
        }
        return (content, expected)
    }

    private static func issueMessages(_ issues: [QualityIssueEnvelope]) -> [String] {
        issues.compactMap { visible($0.message) }
    }

    private static func taskTextCompatible(_ left: String, _ right: String) -> Bool {
        let normalizedLeft = normalizeTaskText(left)
        let normalizedRight = normalizeTaskText(right)
        guard !normalizedLeft.isEmpty, !normalizedRight.isEmpty else {
            return false
        }
        if normalizedLeft == normalizedRight {
            return true
        }
        let shorter: String
        let longer: String
        if normalizedLeft.count <= normalizedRight.count {
            shorter = normalizedLeft
            longer = normalizedRight
        } else {
            shorter = normalizedRight
            longer = normalizedLeft
        }
        return shorter.count >= 12 && longer.contains(shorter)
    }

    private static func normalizeTaskText(_ value: String) -> String {
        let folded = value.folding(
            options: [.caseInsensitive, .diacriticInsensitive],
            locale: Locale(identifier: "en_US_POSIX")
        )
        let tokens = folded.components(
            separatedBy: CharacterSet.alphanumerics.inverted
        ).filter { !$0.isEmpty }
        return tokens.joined(separator: " ")
    }

    private static func normalizedKey(_ value: String?) -> String {
        value?
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased()
            .replacingOccurrences(of: "-", with: "_")
            ?? ""
    }

    private static func visible(_ value: String?) -> String? {
        guard let normalized = value?.trimmingCharacters(in: .whitespacesAndNewlines),
              !normalized.isEmpty else {
            return nil
        }
        return normalized
    }
}

private extension String {
    var nilIfEmpty: String? {
        isEmpty ? nil : self
    }
}
