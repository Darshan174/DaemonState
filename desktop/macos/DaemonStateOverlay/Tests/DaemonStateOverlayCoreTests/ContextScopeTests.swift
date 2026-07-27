import Testing
@testable import DaemonStateOverlayCore

@Suite
struct ContextScopeTests {
    @Test
    func defaultScopeIsSessionAndToggleIsReversible() {
        var scope = ContextScope()

        #expect(scope == .session)
        #expect(ContextScope.defaultScope == .session)
        #expect(scope.toggled == .project)

        scope.toggle()
        #expect(scope == .project)
        scope.toggle()
        #expect(scope == .session)
    }

    @Test
    func tripleClickCancelsThePendingInsertAndOnlyTogglesScope() {
        #expect(
            ContextGesture.disposition(forClickCount: 1) == .scheduleSingle
        )
        #expect(
            ContextGesture.disposition(forClickCount: 2)
                == .rescheduleSingle
        )
        #expect(
            ContextGesture.disposition(forClickCount: 3)
                == .cancelSingleAndToggle
        )
        #expect(ContextGesture.disposition(forClickCount: 4) == .ignore)
    }
}
