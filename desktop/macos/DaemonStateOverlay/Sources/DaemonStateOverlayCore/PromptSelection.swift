import Foundation

public struct PromptSnippet: Equatable, Identifiable, Sendable {
    public let id: String
    public let workspaceID: String
    public let content: String
    public let contentSHA256: String
    public let useCount: Int

    public init(
        id: String,
        workspaceID: String,
        content: String,
        contentSHA256: String,
        useCount: Int
    ) {
        self.id = id
        self.workspaceID = workspaceID
        self.content = content
        self.contentSHA256 = contentSHA256
        self.useCount = useCount
    }
}

public struct PromptSelection: Equatable, Sendable {
    public private(set) var prompts: [PromptSnippet]

    public init(prompts: [PromptSnippet] = []) {
        self.prompts = []
        for prompt in prompts {
            guard !self.prompts.contains(where: { $0.id == prompt.id }) else {
                continue
            }
            self.prompts.append(prompt)
        }
    }

    public var isActive: Bool { !prompts.isEmpty }
    public var count: Int { prompts.count }
    public var ids: [String] { prompts.map(\.id) }
    public var selectedIDs: Set<String> { Set(ids) }
    public var combinedContent: String {
        prompts.map(\.content).joined(separator: "\n\n")
    }

    public func contains(_ promptID: String) -> Bool {
        prompts.contains { $0.id == promptID }
    }

    @discardableResult
    public mutating func toggle(_ prompt: PromptSnippet) -> Bool {
        if let index = prompts.firstIndex(where: { $0.id == prompt.id }) {
            prompts.remove(at: index)
            return false
        }
        if let workspaceID = prompts.first?.workspaceID,
           workspaceID != prompt.workspaceID
        {
            prompts.removeAll()
        }
        prompts.append(prompt)
        return true
    }

    public mutating func replaceAvailable(with available: [PromptSnippet]) {
        let byID = Dictionary(
            uniqueKeysWithValues: available.map { ($0.id, $0) }
        )
        prompts = prompts.compactMap { byID[$0.id] }
    }

    public mutating func clear() {
        prompts.removeAll()
    }
}
