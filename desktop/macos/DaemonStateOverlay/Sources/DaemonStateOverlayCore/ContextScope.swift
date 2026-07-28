import Foundation

/// The two copy-safe context products exposed by DaemonState.
public enum ContextScope: String, Codable, CaseIterable, Sendable {
    case session
    case project

    /// A new overlay always starts in the narrower, current-session scope.
    public static let defaultScope: ContextScope = .session

    public init() {
        self = .session
    }

    public var toggled: ContextScope {
        switch self {
        case .session:
            return .project
        case .project:
            return .session
        }
    }

    public mutating func toggle() {
        self = toggled
    }

    public var displayName: String {
        switch self {
        case .session:
            return "Session Context"
        case .project:
            return "Project Context"
        }
    }
}
