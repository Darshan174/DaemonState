import Foundation

public struct WorkspaceSummary: Codable, Equatable, Identifiable, Sendable {
    public let id: String
    public let name: String
    public let slug: String
    public let kind: String
    public let status: String
    public let archivedAt: String?
    public let createdAt: String?
    public let lastActivityAt: String?
    public let repoPath: String?
    public let repoPaths: [String]
    public let sourceCount: Int?
    public let componentCount: Int?
    public let runCount: Int?
    public let connectorCount: Int?

    public init(
        id: String,
        name: String,
        slug: String = "",
        kind: String = "project",
        status: String = "active",
        archivedAt: String? = nil,
        createdAt: String? = nil,
        lastActivityAt: String? = nil,
        repoPath: String? = nil,
        repoPaths: [String] = [],
        sourceCount: Int? = nil,
        componentCount: Int? = nil,
        runCount: Int? = nil,
        connectorCount: Int? = nil
    ) {
        self.id = id
        self.name = name
        self.slug = slug
        self.kind = kind
        self.status = status
        self.archivedAt = archivedAt
        self.createdAt = createdAt
        self.lastActivityAt = lastActivityAt
        self.repoPath = repoPath
        self.repoPaths = repoPaths
        self.sourceCount = sourceCount
        self.componentCount = componentCount
        self.runCount = runCount
        self.connectorCount = connectorCount
    }

    private enum CodingKeys: String, CodingKey {
        case id
        case name
        case slug
        case kind
        case status
        case archivedAt = "archived_at"
        case createdAt = "created_at"
        case lastActivityAt = "last_activity_at"
        case repoPath = "repo_path"
        case repoPaths = "repo_paths"
        case sourceCount = "source_count"
        case componentCount = "component_count"
        case runCount = "run_count"
        case connectorCount = "connector_count"
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        id = try container.decode(String.self, forKey: .id)
        name = try container.decode(String.self, forKey: .name)
        slug = try container.decodeIfPresent(String.self, forKey: .slug) ?? ""
        kind = try container.decodeIfPresent(String.self, forKey: .kind) ?? "project"
        status = try container.decodeIfPresent(String.self, forKey: .status) ?? "active"
        archivedAt = try container.decodeIfPresent(String.self, forKey: .archivedAt)
        createdAt = try container.decodeIfPresent(String.self, forKey: .createdAt)
        lastActivityAt = try container.decodeIfPresent(String.self, forKey: .lastActivityAt)
        repoPath = try container.decodeIfPresent(String.self, forKey: .repoPath)
        repoPaths = try container.decodeIfPresent([String].self, forKey: .repoPaths) ?? []
        sourceCount = try container.decodeIfPresent(Int.self, forKey: .sourceCount)
        componentCount = try container.decodeIfPresent(Int.self, forKey: .componentCount)
        runCount = try container.decodeIfPresent(Int.self, forKey: .runCount)
        connectorCount = try container.decodeIfPresent(Int.self, forKey: .connectorCount)
    }
}

public enum WorkspaceResolver {
    /// Mirrors the web app's fail-closed selection rules.
    ///
    /// An existing explicit selection wins. Otherwise, only one real project
    /// may be selected automatically; demo and sandbox workspaces never become
    /// the implicit context source.
    public static func resolve(
        _ workspaces: [WorkspaceSummary],
        preferredID: String?
    ) throws -> WorkspaceSummary {
        guard !workspaces.isEmpty else {
            throw DaemonStateError.noWorkspaces
        }

        let preferred = preferredID?.trimmingCharacters(in: .whitespacesAndNewlines)
        if let preferred, !preferred.isEmpty,
           let selected = workspaces.first(where: { $0.id == preferred }) {
            return selected
        }

        let projects = workspaces.filter {
            let kind = $0.kind.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
            return kind != "demo" && kind != "sandbox"
        }
        if projects.count == 1, let project = projects.first {
            return project
        }
        if projects.isEmpty {
            throw DaemonStateError.noEligibleProjectWorkspace
        }
        throw DaemonStateError.workspaceSelectionRequired(preferredID: preferred)
    }
}
