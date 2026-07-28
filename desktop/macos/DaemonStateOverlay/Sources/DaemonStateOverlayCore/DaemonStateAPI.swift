#if canImport(FoundationNetworking)
import FoundationNetworking
#endif
import Foundation

public final class DaemonStateAPI: @unchecked Sendable {
    public let baseURL: URL
    private let session: URLSession

    public init(baseURL: URL, session: URLSession = .shared) {
        self.baseURL = baseURL
        self.session = session
    }

    public func workspaces() async throws -> [WorkspaceSummary] {
        let values: [WorkspaceSummary] = try await send(
            method: "GET",
            path: ["workspaces"]
        )
        var seen = Set<String>()
        for workspace in values {
            let id = workspace.id.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !id.isEmpty else {
                throw DaemonStateError.invalidPayload("workspace.id is empty")
            }
            guard !workspace.name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
                throw DaemonStateError.invalidPayload(
                    "workspace \(id) has no visible name"
                )
            }
            guard seen.insert(id).inserted else {
                throw DaemonStateError.invalidPayload(
                    "workspace \(id) appears more than once"
                )
            }
        }
        return values
    }

    public func resolveWorkspace(preferredID: String?) async throws -> WorkspaceSummary {
        try WorkspaceResolver.resolve(
            try await workspaces(),
            preferredID: preferredID
        )
    }

    public func fetchContext(
        scope: ContextScope,
        workspaceID: String
    ) async throws -> VerifiedContext {
        let workspaceID = workspaceID.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !workspaceID.isEmpty else {
            throw DaemonStateError.invalidPayload("workspace_id is empty")
        }
        switch scope {
        case .session:
            return try await fetchSessionContext(workspaceID: workspaceID)
        case .project:
            return try await fetchProjectContext(workspaceID: workspaceID)
        }
    }

    private func fetchSessionContext(workspaceID: String) async throws -> VerifiedContext {
        let refresh: RefreshLinkedEnvelope = try await send(
            method: "POST",
            path: ["connectors", "ai-session", "refresh-linked"],
            body: RefreshLinkedRequest(workspaceID: workspaceID)
        )
        let digest: ContextDigestEnvelope = try await send(
            method: "GET",
            path: ["context", "digest"],
            queryItems: [URLQueryItem(name: "workspace_id", value: workspaceID)]
        )
        let activeSession = try ContextValidator.activeSession(
            from: digest,
            workspaceID: workspaceID
        )
        try ContextValidator.confirmRefresh(
            refresh,
            workspaceID: workspaceID,
            activeSession: activeSession
        )

        var checkpoint: LatestCheckpointEnvelope?
        do {
            checkpoint = try await scopedLatestCheckpoint(
                workspaceID: workspaceID,
                activeSession: activeSession
            )
        } catch let error as DaemonStateError {
            if case .httpError(statusCode: 404, code: _, message: _) = error {
                checkpoint = nil
            } else {
                throw error
            }
        }

        if let checkpoint {
            try ContextValidator.validateCheckpointIdentity(
                checkpoint,
                workspaceID: workspaceID,
                activeSession: activeSession
            )
        }
        if checkpoint.map(ContextValidator.isCurrentSessionTip) != true {
            checkpoint = try await captureCheckpoint(
                workspaceID: workspaceID,
                activeSession: activeSession
            )
            try ContextValidator.validateCheckpointIdentity(
                checkpoint!,
                workspaceID: workspaceID,
                activeSession: activeSession
            )
        }
        guard let checkpoint else {
            throw DaemonStateError.activeSessionUnavailable(
                "the current session checkpoint could not be captured"
            )
        }
        try ContextValidator.requireCurrentSessionTip(checkpoint)

        let checkpointID = checkpoint.id!
        let handoff: SessionHandoffEnvelope = try await send(
            method: "POST",
            path: ["checkpoints", checkpointID, "handoff"],
            body: CheckpointHandoffRequest(workspaceID: workspaceID)
        )
        return try ContextValidator.verifiedSessionContext(
            handoff,
            workspaceID: workspaceID,
            activeSession: activeSession,
            checkpoint: checkpoint
        )
    }

    private func scopedLatestCheckpoint(
        workspaceID: String,
        activeSession: ActiveSessionIdentity
    ) async throws -> LatestCheckpointEnvelope {
        try await send(
            method: "GET",
            path: ["checkpoints", "latest"],
            queryItems: [
                URLQueryItem(name: "workspace_id", value: workspaceID),
                URLQueryItem(name: "provider", value: activeSession.provider),
                URLQueryItem(name: "session_id", value: activeSession.sessionID),
            ]
        )
    }

    private func captureCheckpoint(
        workspaceID: String,
        activeSession: ActiveSessionIdentity
    ) async throws -> LatestCheckpointEnvelope {
        try await send(
            method: "POST",
            path: ["checkpoints", "capture"],
            body: CaptureCheckpointRequest(
                workspaceID: workspaceID,
                provider: activeSession.provider,
                sessionID: activeSession.sessionID
            )
        )
    }

    private func fetchProjectContext(workspaceID: String) async throws -> VerifiedContext {
        let response: ContinuationEnvelope = try await send(
            method: "POST",
            path: ["continuations", "prepare"],
            body: PrepareContinuationRequest(workspaceID: workspaceID)
        )
        return try ContextValidator.verifiedProjectContext(
            response,
            workspaceID: workspaceID
        )
    }

    private func send<Response: Decodable>(
        method: String,
        path: [String],
        queryItems: [URLQueryItem] = []
    ) async throws -> Response {
        try await send(
            method: method,
            path: path,
            queryItems: queryItems,
            bodyData: nil
        )
    }

    private func send<Response: Decodable, Body: Encodable>(
        method: String,
        path: [String],
        queryItems: [URLQueryItem] = [],
        body: Body
    ) async throws -> Response {
        let data: Data
        do {
            data = try JSONEncoder().encode(body)
        } catch {
            throw DaemonStateError.invalidPayload(
                "the request could not be encoded: \(error.localizedDescription)"
            )
        }
        return try await send(
            method: method,
            path: path,
            queryItems: queryItems,
            bodyData: data
        )
    }

    private func send<Response: Decodable>(
        method: String,
        path: [String],
        queryItems: [URLQueryItem],
        bodyData: Data?
    ) async throws -> Response {
        let url = try endpointURL(path: path, queryItems: queryItems)
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        if let bodyData {
            request.httpBody = bodyData
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }

        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await session.data(for: request)
        } catch {
            throw DaemonStateError.network(error.localizedDescription)
        }
        guard let http = response as? HTTPURLResponse else {
            throw DaemonStateError.invalidHTTPResponse
        }
        guard (200..<300).contains(http.statusCode) else {
            let serviceError = Self.serviceError(from: data)
            throw DaemonStateError.httpError(
                statusCode: http.statusCode,
                code: serviceError.code,
                message: serviceError.message
            )
        }
        do {
            return try JSONDecoder().decode(Response.self, from: data)
        } catch {
            throw DaemonStateError.decodingFailed(error.localizedDescription)
        }
    }

    private func endpointURL(
        path: [String],
        queryItems: [URLQueryItem]
    ) throws -> URL {
        guard let scheme = baseURL.scheme?.lowercased(),
              ["http", "https"].contains(scheme),
              baseURL.host != nil else {
            throw DaemonStateError.invalidBaseURL
        }
        var url = baseURL
        let baseComponents = url.pathComponents.filter { $0 != "/" }
        if baseComponents.last?.lowercased() != "api" {
            url.appendPathComponent("api")
        }
        for component in path {
            url.appendPathComponent(component)
        }
        guard var components = URLComponents(url: url, resolvingAgainstBaseURL: false) else {
            throw DaemonStateError.invalidBaseURL
        }
        if !queryItems.isEmpty {
            components.queryItems = queryItems
        }
        guard let result = components.url else {
            throw DaemonStateError.invalidBaseURL
        }
        return result
    }

    private static func serviceError(from data: Data) -> (code: String?, message: String) {
        guard !data.isEmpty,
              let object = try? JSONSerialization.jsonObject(with: data),
              let payload = object as? [String: Any] else {
            return (nil, "The service returned an unspecified error.")
        }
        if let detail = payload["detail"] as? String, !detail.isEmpty {
            return (payload["code"] as? String, detail)
        }
        if let detail = payload["detail"] as? [String: Any] {
            let code = detail["code"] as? String
            let message = detail["message"] as? String
                ?? detail["detail"] as? String
                ?? "The service rejected the request."
            return (code, message)
        }
        return (
            payload["code"] as? String,
            payload["message"] as? String ?? "The service rejected the request."
        )
    }
}
