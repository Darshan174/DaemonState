import Foundation

struct RefreshLinkedRequest: Encodable {
    let workspaceID: String

    private enum CodingKeys: String, CodingKey {
        case workspaceID = "workspace_id"
    }
}

struct RefreshLinkedEnvelope: Decodable {
    let workspaceID: String?
    let linkedSessions: Int?
    let refreshed: Int?
    let refreshedSessions: [RefreshedSessionEnvelope]?
    let errors: [RefreshFailureEnvelope]?
    let skippedReason: String?

    private enum CodingKeys: String, CodingKey {
        case workspaceID = "workspace_id"
        case linkedSessions = "linked_sessions"
        case refreshed
        case refreshedSessions = "refreshed_sessions"
        case errors
        case skippedReason = "skipped_reason"
    }
}

struct RefreshedSessionEnvelope: Decodable {
    let connectorType: String?
    let sessionID: String?

    private enum CodingKeys: String, CodingKey {
        case connectorType = "connector_type"
        case sessionID = "session_id"
    }
}

struct RefreshFailureEnvelope: Decodable {
    let connectorType: String?
    let sessionID: String?
    let message: String?

    private enum CodingKeys: String, CodingKey {
        case connectorType = "connector_type"
        case sessionID = "session_id"
        case message
    }
}

struct ContextDigestEnvelope: Decodable {
    let workspaceID: String?
    let activity: DigestActivityEnvelope?
    let currentGoal: DigestGoalEnvelope?

    private enum CodingKeys: String, CodingKey {
        case workspaceID = "workspace_id"
        case activity
        case currentGoal = "current_goal"
    }
}

struct DigestActivityEnvelope: Decodable {
    let schemaVersion: String?
    let primary: DigestPrimaryEnvelope?
    let recentSessions: [DigestPrimaryEnvelope]?

    private enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case primary
        case recentSessions = "recent_sessions"
    }
}

struct DigestGoalEnvelope: Decodable {
    let title: String?
}

struct DigestPrimaryEnvelope: Decodable {
    let kind: String?
    let state: String?
    let evidenceLevel: String?
    let selectedForNow: Bool?
    let provider: String?
    let tool: String?
    let sessionID: String?
    let refreshable: Bool?
    let request: String?
    let title: String?
    let sessionTitle: String?
    let projectMatch: RelevanceEnvelope?
    let workspaceRelevance: RelevanceEnvelope?

    private enum CodingKeys: String, CodingKey {
        case kind
        case state
        case evidenceLevel = "evidence_level"
        case selectedForNow = "selected_for_now"
        case provider
        case tool
        case sessionID = "session_id"
        case refreshable
        case request
        case title
        case sessionTitle = "session_title"
        case projectMatch = "project_match"
        case workspaceRelevance = "workspace_relevance"
    }
}

struct RelevanceEnvelope: Decodable {
    let status: String?
}

struct ActiveSessionIdentity: Equatable, Sendable {
    let provider: String
    let sessionID: String
}

struct LatestCheckpointEnvelope: Decodable {
    let id: String?
    let workspaceID: String?
    let provider: String?
    let sessionID: String?
    let schemaVersion: String?
    let captureStatus: String?
    let projection: CheckpointProjectionEnvelope?
    let boundary: CheckpointBoundaryEnvelope?
    let currentness: CheckpointCurrentnessEnvelope?
    let sections: CheckpointSectionsEnvelope?

    private enum CodingKeys: String, CodingKey {
        case id
        case workspaceID = "workspace_id"
        case provider
        case sessionID = "session_id"
        case schemaVersion = "schema_version"
        case captureStatus = "capture_status"
        case projection
        case boundary
        case currentness
        case sections
    }
}

struct CheckpointSectionsEnvelope: Decodable {
    let goal: [CheckpointItemEnvelope]?
    let exactNextAction: [CheckpointItemEnvelope]?

    private enum CodingKeys: String, CodingKey {
        case goal
        case exactNextAction = "exact_next_action"
    }
}

struct CheckpointItemEnvelope: Decodable {
    let statement: String?
}

struct CheckpointProjectionEnvelope: Decodable {
    let valid: Bool?
}

struct CheckpointCurrentnessEnvelope: Decodable {
    let state: String?
}

struct CheckpointBoundaryEnvelope: Decodable {
    let eventID: String?
    let sequenceNumber: Int?
    let sessionTipSequence: Int?
    let hasNewerEvents: Bool?

    private enum CodingKeys: String, CodingKey {
        case eventID = "event_id"
        case sequenceNumber = "sequence_number"
        case sessionTipSequence = "session_tip_sequence"
        case hasNewerEvents = "has_newer_events"
    }
}

struct CaptureCheckpointRequest: Encodable {
    let workspaceID: String
    let provider: String
    let sessionID: String

    private enum CodingKeys: String, CodingKey {
        case workspaceID = "workspace_id"
        case provider
        case sessionID = "session_id"
    }
}

struct CheckpointHandoffRequest: Encodable {
    let workspaceID: String

    private enum CodingKeys: String, CodingKey {
        case workspaceID = "workspace_id"
    }
}

struct SessionHandoffEnvelope: Decodable {
    let schemaVersion: String?
    let scope: String?
    let provider: String?
    let sessionID: String?
    let checkpointID: String?
    let boundary: CheckpointBoundaryEnvelope?
    let content: String?
    let sha256: String?
    let qualityReport: SessionQualityEnvelope?

    private enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case scope
        case provider
        case sessionID = "session_id"
        case checkpointID = "checkpoint_id"
        case boundary
        case content
        case sha256
        case qualityReport = "quality_report"
    }
}

struct SessionQualityEnvelope: Decodable {
    let copyReady: Bool?
    let blockingIssues: [QualityIssueEnvelope]?
    let issues: [QualityIssueEnvelope]?

    private enum CodingKeys: String, CodingKey {
        case copyReady = "copy_ready"
        case blockingIssues = "blocking_issues"
        case issues
    }
}

struct QualityIssueEnvelope: Decodable {
    let code: String?
    let severity: String?
    let message: String?
    let blocksCopy: Bool?

    private enum CodingKeys: String, CodingKey {
        case code
        case severity
        case message
        case blocksCopy = "blocks_copy"
    }
}

struct PrepareContinuationRequest: Encodable {
    let workspaceID: String
    let syncSessions = false
    let executeCommands = false

    private enum CodingKeys: String, CodingKey {
        case workspaceID = "workspace_id"
        case syncSessions = "sync_sessions"
        case executeCommands = "execute_commands"
    }
}

struct ContinuationEnvelope: Decodable {
    let schemaVersion: String?
    let projectContext: ProjectContextEnvelope?
    let checkpoint: ContinuationCheckpointEnvelope?
    let sourceSession: ContinuationSourceSessionEnvelope?
    let task: ContinuationTaskEnvelope?

    private enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case projectContext = "project_context"
        case checkpoint
        case sourceSession = "source_session"
        case task
    }
}

struct ProjectContextEnvelope: Decodable {
    let schemaVersion: String?
    let scope: String?
    let content: String?
    let sha256: String?
    let copyReady: Bool?
    let qualityIssues: [QualityIssueEnvelope]?

    private enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case scope
        case content
        case sha256
        case copyReady = "copy_ready"
        case qualityIssues = "quality_issues"
    }
}

struct ContinuationCheckpointEnvelope: Decodable {
    let id: String?
}

struct ContinuationSourceSessionEnvelope: Decodable {
    let provider: String?
    let sessionID: String?

    private enum CodingKeys: String, CodingKey {
        case provider
        case sessionID = "session_id"
    }
}

struct ContinuationTaskEnvelope: Decodable {
    let identity: ContinuationTaskIdentityEnvelope?
}

struct ContinuationTaskIdentityEnvelope: Decodable {
    let workspaceID: String?

    private enum CodingKeys: String, CodingKey {
        case workspaceID = "workspace_id"
    }
}
