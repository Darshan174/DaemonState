import Foundation

struct OverlayErrorRecord: Equatable {
    let occurredAt: Date
    let operation: String
    let message: String
}

struct OverlayErrorHistory {
    private(set) var records: [OverlayErrorRecord] = []
    let capacity: Int

    init(capacity: Int = 20) {
        self.capacity = max(1, capacity)
    }

    var count: Int {
        records.count
    }

    var isEmpty: Bool {
        records.isEmpty
    }

    mutating func record(
        operation: String,
        error: Error,
        at occurredAt: Date = Date()
    ) {
        record(
            operation: operation,
            message: error.localizedDescription,
            at: occurredAt
        )
    }

    mutating func record(
        operation: String,
        message: String,
        at occurredAt: Date = Date()
    ) {
        let normalizedOperation = operation.trimmingCharacters(
            in: .whitespacesAndNewlines
        )
        let normalizedMessage = message.trimmingCharacters(
            in: .whitespacesAndNewlines
        )
        records.append(OverlayErrorRecord(
            occurredAt: occurredAt,
            operation: normalizedOperation.isEmpty ? "Unknown operation" : normalizedOperation,
            message: normalizedMessage.isEmpty ? "Unknown error" : normalizedMessage
        ))
        if records.count > capacity {
            records.removeFirst(records.count - capacity)
        }
    }

    func clipboardText() -> String {
        guard !records.isEmpty else { return "" }
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime]
        let entries = records.reversed().map { record in
            "[\(formatter.string(from: record.occurredAt))] \(record.operation)\n"
                + record.message
        }
        return (["DaemonState recent errors (newest first)"] + entries)
            .joined(separator: "\n\n")
    }

    static func conciseMessage(
        _ rawMessage: String,
        limit: Int = 180
    ) -> String {
        let message = rawMessage
            .split(whereSeparator: { $0.isWhitespace })
            .joined(separator: " ")
        guard message.count > limit, limit > 1 else { return message }

        if let requestRange = message.range(
            of: " Request ",
            options: .backwards
        ) {
            let requestSuffix = String(message[requestRange.lowerBound...])
            let prefixCount = limit - requestSuffix.count - 1
            if prefixCount > 12 {
                return "\(message.prefix(prefixCount))…\(requestSuffix)"
            }
        }
        return "\(message.prefix(limit - 1))…"
    }
}
