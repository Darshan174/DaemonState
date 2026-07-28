import Testing
@testable import DaemonStateOverlayCore

@Suite
struct WorkspaceResolverTests {
    private let alpha = WorkspaceSummary(
        id: "alpha",
        name: "Alpha",
        kind: "project"
    )
    private let beta = WorkspaceSummary(
        id: "beta",
        name: "Beta",
        kind: "project"
    )

    @Test
    func explicitAvailableWorkspaceWins() throws {
        let selected = try WorkspaceResolver.resolve(
            [alpha, beta],
            preferredID: "beta"
        )

        #expect(selected == beta)
    }

    @Test
    func onlyRealProjectIsSelectedInsteadOfSampleWorkspace() throws {
        let demo = WorkspaceSummary(
            id: "demo",
            name: "Sample",
            kind: "demo"
        )

        let selected = try WorkspaceResolver.resolve(
            [demo, alpha],
            preferredID: nil
        )

        #expect(selected == alpha)
    }

    @Test
    func multipleProjectsRequireExplicitSelection() {
        do {
            _ = try WorkspaceResolver.resolve([alpha, beta], preferredID: nil)
            Issue.record("Expected explicit workspace selection to be required")
        } catch {
            #expect(
                error as? DaemonStateError
                    == .workspaceSelectionRequired(preferredID: nil)
            )
        }
    }

    @Test
    func demoIsNeverAnImplicitSelection() {
        let demo = WorkspaceSummary(
            id: "demo",
            name: "Sample",
            kind: "demo"
        )

        do {
            _ = try WorkspaceResolver.resolve([demo], preferredID: nil)
            Issue.record("Expected the sample workspace to be rejected")
        } catch {
            #expect(
                error as? DaemonStateError == .noEligibleProjectWorkspace
            )
        }
    }
}
