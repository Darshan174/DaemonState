import CryptoKit
import Foundation
import Testing
@testable import DaemonStateOverlayCore

struct PromptSelectionTests {
    @Test
    func togglePreservesSelectionOrderAndBuildsPastePayload() {
        let first = prompt(id: "prompt-1", content: "First instruction")
        let second = prompt(id: "prompt-2", content: "Second instruction")
        var selection = PromptSelection()

        let selectedSecond = selection.toggle(second)
        let selectedFirst = selection.toggle(first)
        #expect(selectedSecond)
        #expect(selectedFirst)

        #expect(selection.ids == ["prompt-2", "prompt-1"])
        #expect(
            selection.combinedContent
                == "Second instruction\n\nFirst instruction"
        )
    }

    @Test
    func togglingASelectedPromptReturnsToNormalWhenLastItemIsRemoved() {
        let value = prompt(id: "prompt-1", content: "Reusable prompt")
        var selection = PromptSelection(prompts: [value])

        let remainsSelected = selection.toggle(value)
        #expect(!remainsSelected)
        #expect(!selection.isActive)
        #expect(selection.count == 0)
        #expect(selection.combinedContent.isEmpty)
    }

    @Test
    func refreshPrunesDeletedPromptsAndUpdatesStoredContent() {
        let first = prompt(id: "prompt-1", content: "Old content")
        let second = prompt(id: "prompt-2", content: "Removed content")
        var selection = PromptSelection(prompts: [first, second])

        selection.replaceAvailable(with: [
            prompt(id: "prompt-1", content: "Updated content"),
            prompt(id: "prompt-3", content: "Not selected"),
        ])

        #expect(selection.ids == ["prompt-1"])
        #expect(selection.combinedContent == "Updated content")
    }

    @Test
    func selectingFromAnotherWorkspaceClearsTheOldWorkspace() {
        var selection = PromptSelection(prompts: [
            prompt(id: "prompt-1", content: "First", workspaceID: "workspace-1"),
        ])

        selection.toggle(
            prompt(id: "prompt-2", content: "Second", workspaceID: "workspace-2")
        )

        #expect(selection.ids == ["prompt-2"])
        #expect(selection.prompts.first?.workspaceID == "workspace-2")
    }

    private func prompt(
        id: String,
        content: String,
        workspaceID: String = "workspace-1"
    ) -> PromptSnippet {
        PromptSnippet(
            id: id,
            workspaceID: workspaceID,
            content: content,
            contentSHA256: SHA256.hash(data: Data(content.utf8))
                .map { String(format: "%02x", $0) }
                .joined(),
            useCount: 0
        )
    }
}
