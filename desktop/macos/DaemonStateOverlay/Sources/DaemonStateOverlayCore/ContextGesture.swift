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
///
/// AppKit keeps incrementing `clickCount` when the user clicks again
/// immediately after a triple click. Treat each group of three as a new
/// gesture sequence so that click four behaves like a single click instead of
/// becoming a dead click.
public enum ContextGesture {
    public static func disposition(
        forClickCount clickCount: Int
    ) -> ContextClickDisposition {
        guard clickCount > 0 else {
            return .ignore
        }
        switch (clickCount - 1) % 3 {
        case 0:
            return .scheduleSingle
        case 1:
            return .rescheduleSingle
        case 2:
            return .cancelSingleAndToggle
        default:
            return .ignore
        }
    }
}
