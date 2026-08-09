import Foundation
import Testing
@testable import DaemonStateOverlay

struct OverlayErrorHistoryTests {
    @Test
    func retainsBoundedFullErrorsAndFormatsNewestFirst() {
        var history = OverlayErrorHistory(capacity: 2)
        history.record(
            operation: "Old operation",
            message: "old error",
            at: Date(timeIntervalSince1970: 0)
        )
        history.record(
            operation: "Workspace Context",
            message: "full validation detail\nsecond line",
            at: Date(timeIntervalSince1970: 1)
        )
        history.record(
            operation: "Session Context",
            message: "latest error",
            at: Date(timeIntervalSince1970: 2)
        )

        #expect(history.count == 2)
        #expect(history.records.map(\.operation) == [
            "Workspace Context",
            "Session Context",
        ])
        let details = history.clipboardText()
        #expect(details.contains("DaemonState recent errors (newest first)"))
        #expect(details.contains("full validation detail\nsecond line"))
        #expect(!details.contains("old error"))
        #expect(
            details.range(of: "Session Context")!.lowerBound
                < details.range(of: "Workspace Context")!.lowerBound
        )
    }

    @Test
    func conciseMessagesKeepTheRequestIDVisible() {
        let message = String(repeating: "repository validation failed ", count: 12)
            + "Request request-correlation-123."

        let concise = OverlayErrorHistory.conciseMessage(message, limit: 100)

        #expect(concise.count <= 100)
        #expect(concise.contains("…"))
        #expect(concise.hasSuffix("Request request-correlation-123."))
    }
}
