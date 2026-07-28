import Foundation

public enum DaemonStateError: Error, Equatable, Sendable {
    case invalidBaseURL
    case network(String)
    case invalidHTTPResponse
    case httpError(statusCode: Int, code: String?, message: String)
    case decodingFailed(String)
    case invalidPayload(String)
    case noWorkspaces
    case noEligibleProjectWorkspace
    case workspaceSelectionRequired(preferredID: String?)
    case unsupportedSchema(expected: String, actual: String?)
    case scopeMismatch(expected: ContextScope, actual: String?)
    case contextNotCopyReady(scope: ContextScope, reasons: [String])
    case invalidSHA256(scope: ContextScope)
    case integrityMismatch(scope: ContextScope, expected: String, actual: String)
    case identityMismatch(field: String, expected: String, actual: String?)
    case activeSessionUnavailable(String)
    case sessionRefreshUnconfirmed(String)
}

extension DaemonStateError: LocalizedError {
    public var errorDescription: String? {
        switch self {
        case .invalidBaseURL:
            return "The DaemonState server URL is invalid."
        case let .network(message):
            return "DaemonState could not be reached: \(message)"
        case .invalidHTTPResponse:
            return "DaemonState returned a response without a valid HTTP status."
        case let .httpError(statusCode, code, message):
            let codeSuffix = code.map { " (\($0))" } ?? ""
            return "DaemonState returned HTTP \(statusCode)\(codeSuffix): \(message)"
        case let .decodingFailed(message):
            return "DaemonState returned unreadable JSON: \(message)"
        case let .invalidPayload(message):
            return "DaemonState returned an incomplete response: \(message)"
        case .noWorkspaces:
            return "No active DaemonState workspace is available."
        case .noEligibleProjectWorkspace:
            return "Only demo or sandbox workspaces are available. Select a real project first."
        case let .workspaceSelectionRequired(preferredID):
            if let preferredID, !preferredID.isEmpty {
                return "The saved workspace “\(preferredID)” is unavailable and multiple projects remain. Select a workspace."
            }
            return "Multiple projects are available. Select a workspace before inserting context."
        case let .unsupportedSchema(expected, actual):
            return "DaemonState returned schema “\(actual ?? "missing")”; expected “\(expected)”."
        case let .scopeMismatch(expected, actual):
            return "DaemonState returned \(actual ?? "missing") scope while \(expected.displayName) was requested."
        case let .contextNotCopyReady(scope, reasons):
            let detail = reasons.prefix(2).joined(separator: " ")
            return detail.isEmpty
                ? "\(scope.displayName) did not pass its copy-safety gate."
                : "\(scope.displayName) is not copy-ready. \(detail)"
        case let .invalidSHA256(scope):
            return "\(scope.displayName) did not include a valid SHA-256 digest."
        case let .integrityMismatch(scope, _, _):
            return "\(scope.displayName) failed its content integrity check."
        case let .identityMismatch(field, expected, actual):
            return "Context identity mismatch for \(field): expected “\(expected)”, received “\(actual ?? "missing")”."
        case let .activeSessionUnavailable(message):
            return "Current Session Context is unavailable: \(message)"
        case let .sessionRefreshUnconfirmed(message):
            return "The active session could not be refreshed safely: \(message)"
        }
    }
}
