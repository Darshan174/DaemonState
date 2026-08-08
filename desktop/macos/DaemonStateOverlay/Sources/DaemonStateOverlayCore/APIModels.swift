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
    let latest: DigestPrimaryEnvelope?
    let recentSessions: [DigestPrimaryEnvelope]?

    private enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case primary
        case latest
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

struct SessionContextEligibilityEnvelope: Decodable {
    let provider: String?
    let sessionID: String?
    let eligible: Bool?
    let compactionCount: Int?
    let minimumCompactions: Int?
    let message: String?

    private enum CodingKeys: String, CodingKey {
        case provider
        case sessionID = "session_id"
        case eligible
        case compactionCount = "compaction_count"
        case minimumCompactions = "minimum_compactions"
        case message
    }
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

struct PrepareWorkspaceContextRequest: Encodable {
    let workspaceID: String
    let repoPath: String?
    let mode = "project_snapshot"
    let objectiveOrigin = "project_snapshot"

    private enum CodingKeys: String, CodingKey {
        case workspaceID = "workspace_id"
        case repoPath = "repo_path"
        case mode
        case objectiveOrigin = "objective_origin"
    }
}

struct WorkspaceContextPackEnvelope: Decodable {
    let contextPackID: String?
    let schemaVersion: String?
    let markdown: String?
    let manifest: WorkspaceContextManifestEnvelope?

    private enum CodingKeys: String, CodingKey {
        case contextPackID = "context_pack_id"
        case schemaVersion = "schema_version"
        case markdown
        case manifest
    }
}

struct WorkspaceContextManifestEnvelope: Decodable {
    let schemaVersion: String?
    let contextPackID: String?
    let workspaceID: String?
    let objectiveKind: String?
    let focus: WorkspaceContextFocusEnvelope?
    let repoState: WorkspaceContextRepositoryEnvelope?
    let tokenAccounting: WorkspaceContextBudgetEnvelope?
    let rendering: WorkspaceContextRenderingEnvelope?
    let workspaceFoundation: WorkspaceFoundationEnvelope?

    private enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case contextPackID = "context_pack_id"
        case workspaceID = "workspace_id"
        case objectiveKind = "objective_kind"
        case focus
        case repoState = "repo_state"
        case tokenAccounting = "token_accounting"
        case rendering
        case workspaceFoundation = "workspace_foundation"
    }
}

struct WorkspaceContextFocusEnvelope: Decodable {
    let kind: String?
}

struct WorkspaceContextRepositoryEnvelope: Decodable {
    let repoPath: String?
    let stateFingerprint: String?
    let snapshotFingerprint: String?
    let workspaceFoundationSHA256: String?
    let workspaceFoundationArtifactSHA256: String?

    private enum CodingKeys: String, CodingKey {
        case repoPath = "repo_path"
        case stateFingerprint = "state_fingerprint"
        case snapshotFingerprint = "snapshot_fingerprint"
        case workspaceFoundationSHA256 = "workspace_foundation_sha256"
        case workspaceFoundationArtifactSHA256 = "workspace_foundation_artifact_sha256"
    }
}

private enum FoundationJSONValue: Decodable {
    case object([String: FoundationJSONValue])
    case array([FoundationJSONValue])
    case string(String)
    case integer(Int64)
    case number(Double)
    case boolean(Bool)
    case null

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() {
            self = .null
        } else if let value = try? container.decode(Bool.self) {
            self = .boolean(value)
        } else if let value = try? container.decode(Int64.self) {
            self = .integer(value)
        } else if let value = try? container.decode(Double.self) {
            self = .number(value)
        } else if let value = try? container.decode(String.self) {
            self = .string(value)
        } else if let value = try? container.decode([FoundationJSONValue].self) {
            self = .array(value)
        } else {
            self = .object(try container.decode([String: FoundationJSONValue].self))
        }
    }

    var foundationObject: Any {
        switch self {
        case let .object(value):
            return value.mapValues(\.foundationObject)
        case let .array(value):
            return value.map(\.foundationObject)
        case let .string(value):
            return value
        case let .integer(value):
            return value
        case let .number(value):
            return value
        case let .boolean(value):
            return value
        case .null:
            return NSNull()
        }
    }

    var objectValue: [String: FoundationJSONValue]? {
        guard case let .object(value) = self else { return nil }
        return value
    }

    var arrayValue: [FoundationJSONValue]? {
        guard case let .array(value) = self else { return nil }
        return value
    }

    var stringValue: String? {
        guard case let .string(value) = self else { return nil }
        return value
    }

    var boolValue: Bool? {
        guard case let .boolean(value) = self else { return nil }
        return value
    }
}

struct WorkspaceFoundationEnvelope: Decodable {
    private static let supportedSchemaVersions: Set<String> = [
        "workspace_foundation.v1",
        "workspace_foundation.v2",
    ]

    private let raw: FoundationJSONValue

    init(from decoder: Decoder) throws {
        raw = try FoundationJSONValue(from: decoder)
    }

    var schemaVersion: String? { value("schema_version")?.stringValue }
    var hasSupportedSchemaVersion: Bool {
        schemaVersion.map(Self.supportedSchemaVersions.contains) == true
    }
    var objectiveIndependent: Bool? { value("objective_independent")?.boolValue }
    var semanticSHA256: String? { value("semantic_sha256")?.stringValue }
    var artifactSHA256: String? { value("artifact_sha256")?.stringValue }
    var copyReady: Bool? {
        value("quality_report")?.objectValue?["copy_ready"]?.boolValue
    }
    var repositorySnapshotFingerprint: String? {
        value("repository_state")?.objectValue?["snapshot_fingerprint"]?.stringValue
    }
    var blockingMessages: [String] {
        let issues = value("quality_report")?.objectValue?["issues"]?.arrayValue ?? []
        return issues.compactMap { issue in
            guard let object = issue.objectValue,
                  object["blocking"]?.boolValue == true else { return nil }
            return object["message"]?.stringValue
        }
    }

    func canonicalArtifactData() throws -> Data {
        guard var object = raw.objectValue else {
            throw DaemonStateError.invalidPayload(
                "workspace foundation artifact is not a JSON object"
            )
        }
        object.removeValue(forKey: "artifact_sha256")
        return try JSONSerialization.data(
            withJSONObject: object.mapValues(\.foundationObject),
            options: [.sortedKeys, .withoutEscapingSlashes]
        )
    }

    func canonicalSemanticData() throws -> Data {
        guard var object = raw.objectValue else {
            throw DaemonStateError.invalidPayload(
                "workspace foundation artifact is not a JSON object"
            )
        }
        object.removeValue(forKey: "artifact_sha256")
        object.removeValue(forKey: "semantic_sha256")
        object.removeValue(forKey: "compiled_at")
        if case var .object(repository)? = object["repository_state"] {
            repository.removeValue(forKey: "captured_at")
            object["repository_state"] = .object(repository)
        }
        return try JSONSerialization.data(
            withJSONObject: object.mapValues(\.foundationObject),
            options: [.sortedKeys, .withoutEscapingSlashes]
        )
    }

    private func value(_ key: String) -> FoundationJSONValue? {
        raw.objectValue?[key]
    }
}

struct WorkspaceContextBudgetEnvelope: Decodable {
    let withinBudget: Bool?

    private enum CodingKeys: String, CodingKey {
        case withinBudget = "within_budget"
    }
}

struct WorkspaceContextRenderingEnvelope: Decodable {
    let withinBudget: Bool?
    let markdownSHA256: String?

    private enum CodingKeys: String, CodingKey {
        case withinBudget = "within_budget"
        case markdownSHA256 = "markdown_sha256"
    }
}

struct PromptSnippetListEnvelope: Decodable {
    let schemaVersion: String?
    let workspaceID: String?
    let prompts: [PromptSnippetEnvelope]?

    private enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case workspaceID = "workspace_id"
        case prompts
    }
}

struct PromptSnippetEnvelope: Decodable {
    let id: String?
    let workspaceID: String?
    let content: String?
    let contentSHA256: String?
    let useCount: Int?

    private enum CodingKeys: String, CodingKey {
        case id
        case workspaceID = "workspace_id"
        case content
        case contentSHA256 = "content_sha256"
        case useCount = "use_count"
    }
}

struct PromptSnippetCreateRequest: Encodable {
    let content: String
}

struct PromptSnippetUsageRequest: Encodable {
    let promptIDs: [String]

    private enum CodingKeys: String, CodingKey {
        case promptIDs = "prompt_ids"
    }
}

struct PromptSnippetUsageEnvelope: Decodable {
    let schemaVersion: String?
    let workspaceID: String?
    let updated: Int?

    private enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case workspaceID = "workspace_id"
        case updated
    }
}
