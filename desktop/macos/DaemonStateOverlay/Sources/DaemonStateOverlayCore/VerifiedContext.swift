import Foundation

public struct VerifiedContext: Equatable, Sendable {
    public let content: String
    public let scope: ContextScope
    public let workspaceID: String
    public let schemaVersion: String
    public let sha256: String
    public let checkpointID: String?
    public let provider: String?
    public let sessionID: String?
    public let boundarySequence: Int?

    public init(
        content: String,
        scope: ContextScope,
        workspaceID: String,
        schemaVersion: String,
        sha256: String,
        checkpointID: String? = nil,
        provider: String? = nil,
        sessionID: String? = nil,
        boundarySequence: Int? = nil
    ) {
        self.content = content
        self.scope = scope
        self.workspaceID = workspaceID
        self.schemaVersion = schemaVersion
        self.sha256 = sha256
        self.checkpointID = checkpointID
        self.provider = provider
        self.sessionID = sessionID
        self.boundarySequence = boundarySequence
    }
}
