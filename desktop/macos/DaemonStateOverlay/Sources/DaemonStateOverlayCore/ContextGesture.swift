import Foundation

public enum ContextClickDisposition: Equatable, Sendable {
    case scheduleSingle
    case rescheduleSingle
    case cancelSingleAndToggle
    case ignore
}

/// Classifies AppKit click counts without performing context work.
///
/// The first click is deferred through the multi-click interval. A second
/// click restarts that interval, while a third cancels it and changes scope.
/// A triple click therefore cannot insert context before it toggles, including
/// when each click uses most of the user's configured multi-click interval.
public enum ContextGesture {
    public static func disposition(
        forClickCount clickCount: Int
    ) -> ContextClickDisposition {
        switch clickCount {
        case 1:
            return .scheduleSingle
        case 2:
            return .rescheduleSingle
        case 3:
            return .cancelSingleAndToggle
        default:
            return .ignore
        }
    }
}
