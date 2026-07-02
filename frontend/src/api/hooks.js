/**
 * React Query hooks for Context Engine API.
 *
 * Each hook tries the real backend first. If the fetch fails (backend
 * down, network error), it falls back to mock fixtures so the UI stays
 * usable during frontend-only development.
 */

import { useCallback } from "react";
import { useInfiniteQuery, useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";
import { resolveWorkspaceId } from "../context/WorkspaceContext";
import {
  dashboardStats,
  evalCasesByDomain as mockEvalCasesByDomain,
  evalSummary as mockEvalSummary,
  recentActivity,
  staleAlerts,
  connectors as mockConnectors,
  reviewQueue as mockReviewQueue,
  sourceDocuments as mockSourceDocuments,
  graphNodes as mockGraphNodes,
  graphEdges as mockGraphEdges,
  modelFixtures,
  queryExamples as mockQueryExamples,
} from "../fixtures/mockData";

// ── Helpers ────────────────────────────────────────────────────

/**
 * When true, hooks silently return mock fixtures on backend failure.
 * Default is false — network/backend errors surface as real errors.
 *
 * Enable with: VITE_USE_MOCKS=true in .env or environment.
 */
const MOCKS_ENABLED = import.meta.env.VITE_USE_MOCKS === "true";
const FOUNDER_WORKFLOW_API = Object.freeze({
  workspaces: "/workspaces",
  seedDemo: "/seed-demo",
  imports: "/imports",
  founderBrief: "/founder-brief",
  decisions: "/decisions",
  sourceDocuments: "/source-documents",
  query: "/query",
});
const OPERATOR_STATUS_ENDPOINTS = ["/operator/status", "/admin/status"];

/**
 * Wrap an API call so it falls back to mock data on network failure,
 * but only when VITE_USE_MOCKS=true. Otherwise errors propagate.
 *
 * `fallbackStatuses` is for endpoints that are intentionally stubbed out
 * in the backend for the current phase (for example 404/501 during Phase 1).
 */
function withFallback(apiFn, mockData, { fallbackStatuses = [] } = {}) {
  return async () => {
    try {
      return await apiFn();
    } catch (err) {
      if (err.status && !fallbackStatuses.includes(err.status)) {
        throw err; // real API error (4xx/5xx) — propagate
      }
      if (!MOCKS_ENABLED) throw err;
      if (err.status) {
        console.warn(`[api] endpoint unavailable (${err.status}), using mock data (VITE_USE_MOCKS=true)`);
        return mockData;
      }
      console.warn("[api] backend unreachable, using mock data (VITE_USE_MOCKS=true)");
      return mockData;
    }
  };
}

const LS_KEY = "ce:selectedWorkspaceId";
const CONNECTOR_CATALOG = {
  slack: {
    type: "slack",
    name: "Slack",
    description: "Channels, DMs, and thread history",
    color: "#4A154B",
    availability: "available",
    provider: "native",
    providerLabel: "Built in",
    providerNote: "Slack stays native because OAuth, thread expansion, and real-time events are product-critical.",
  },
  github: {
    type: "github",
    name: "GitHub",
    description: "Issues, pull requests, and code review discussions",
    color: "#24292e",
    availability: "available",
    provider: "native",
    providerLabel: "Personal Access Token",
    providerNote: "GitHub ingests issues, pull requests, labels, and review discussions. Each item becomes a structured component in the knowledge graph.",
  },
  discord: {
    type: "discord",
    name: "Discord",
    description: "Server channels, threads, and community context",
    color: "#5865F2",
    availability: "coming_soon",
    provider: "official_api",
    providerLabel: "Coming soon",
    providerNote: "Discord is shown in the catalog but is not available for direct ingest yet.",
  },
  ai_context: {
    type: "ai_context",
    name: "AI Context",
    description: "Codex, Claude Code, OpenCode, plans, diffs, and review notes",
    color: "#10a37f",
    availability: "available",
    provider: "native",
    providerLabel: "Session import",
    providerNote: "Import agent sessions and review notes as source documents with provenance.",
  },
  local: {
    type: "local",
    name: "Local Files",
    description: "Uploaded Markdown, text, JSON, CSV, and other local documents",
    color: "#64748B",
    availability: "available",
    provider: "native",
    providerLabel: "Upload",
    providerNote: "Local uploads are first-class source documents for the graph.",
  },
  zoom: {
    type: "zoom",
    name: "Zoom",
    description: "Meeting transcripts and recording metadata",
    color: "#0B5CFF",
    availability: "coming_soon",
    provider: "official_api",
    providerLabel: "Official API",
    providerNote: "Transcript-first Zoom ingestion keeps the connector focused on high-signal meeting context instead of media processing.",
  },
  gdrive: {
    type: "gdrive",
    name: "Google Drive",
    description: "Docs, Sheets, Slides, and folder content",
    color: "#ffffff",
    availability: "available",
    provider: "official_api",
    providerLabel: "Official API",
    providerNote: "Drive ingest docs, sheets, slides, and folder metadata into the source and graph pipeline.",
  },
  gmail: {
    type: "gmail",
    name: "Gmail",
    description: "Email threads, attachments, and sender context",
    color: "#ffffff",
    availability: "available",
    provider: "official_api",
    providerLabel: "Official API",
    providerNote: "Gmail ingests selected mailbox threads and attachments with source provenance.",
  },
  codex: {
    type: "codex",
    name: "Codex",
    description: "OpenAI Codex sessions — decisions, code plans, and AI reasoning",
    color: "#10a37f",
    availability: "available",
    provider: "native",
    providerLabel: "Session import",
  },
  claude: {
    type: "claude",
    name: "Claude",
    description: "Anthropic Claude conversations — architecture choices and research threads",
    color: "#D97757",
    availability: "available",
    provider: "native",
    providerLabel: "Session import",
  },
  opencode: {
    type: "opencode",
    name: "OpenCode",
    description: "OpenCode AI coding sessions — terminal context and implementation notes",
    color: "#000000",
    availability: "available",
    provider: "native",
    providerLabel: "Session import",
  },
  wispr_flow: {
    type: "wispr_flow",
    name: "Wispr Flow",
    description: "Voice notes, transcripts, and dictated project context",
    color: "#111827",
    availability: "coming_soon",
    provider: "official_api",
    providerLabel: "Coming soon",
    providerNote: "Wispr Flow is planned but not available for direct ingest yet.",
  },
};

const BROWSER_IMPORT_EXTENSIONS = new Set([
  "csv",
  "html",
  "htm",
  "json",
  "log",
  "md",
  "markdown",
  "txt",
  "xml",
  "yaml",
  "yml",
]);

/**
 * Resolve the workspace ID to use for API calls.
 *
 * Priority:
 * 1. localStorage selection (set by workspace switcher)
 * 2. The only workspace from the backend, when unambiguous
 *
 * Returns null if no workspaces exist, or when multiple workspaces exist but no
 * explicit browser selection has been made yet.
 */
async function getWorkspaceId() {
  let workspaces;
  try {
    workspaces = await api.get(FOUNDER_WORKFLOW_API.workspaces);
  } catch (err) {
    if (err.status === 404 || err.status === 501) return null;
    throw err;
  }
  if (workspaces.length === 0) return null;

  const stored = localStorage.getItem(LS_KEY);
  return resolveWorkspaceId(workspaces, stored);
}

function isBrowserFile(value) {
  return value && typeof value === "object" && typeof value.name === "string" && typeof value.text === "function";
}

function normalizeUploadInput(input) {
  if (Array.isArray(input)) return { files: input };
  if (isBrowserFile(input)) return { files: [input] };
  if (input && typeof input === "object") return input;
  return { files: [] };
}

function getFileExtension(fileName) {
  const parts = fileName.split(".");
  return parts.length > 1 ? parts.at(-1).toLowerCase() : "";
}

async function buildBrowserImportDocument(file) {
  const extension = getFileExtension(file.name);
  const relativePath = file.webkitRelativePath || file.name;
  const supportedByMime = file.type ? file.type.startsWith("text/") : false;

  if (!supportedByMime && !BROWSER_IMPORT_EXTENSIONS.has(extension)) {
    throw new Error(`Unsupported file type: ${file.name}. Use plain-text files like MD, TXT, JSON, CSV, or HTML.`);
  }

  const content = await file.text();
  if (!content.trim()) {
    throw new Error(`File is empty: ${file.name}`);
  }

  return {
    external_id: `browser-upload:${relativePath}`,
    content,
    created_at_source:
      typeof file.lastModified === "number" && file.lastModified > 0
        ? new Date(file.lastModified).toISOString()
        : undefined,
    metadata: {
      title: file.name,
      file_name: file.name,
      file_path: relativePath,
      file_extension: extension,
      mime_type: file.type || undefined,
      source_type: "browser_upload",
    },
  };
}

// ── Workspaces ────────────────────────────────────────────────

export function useWorkspaces() {
  return useQuery({
    queryKey: ["workspaces"],
    queryFn: async () => {
      try {
        return await api.get(FOUNDER_WORKFLOW_API.workspaces);
      } catch (err) {
        if (err.status === 404 || err.status === 501) return [];
        throw err;
      }
    },
    retry: 1,
  });
}

export function useCreateWorkspace() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body) => api.post(FOUNDER_WORKFLOW_API.workspaces, body),
    onSuccess: (newWorkspace) => {
      // Auto-select the newly created workspace
      if (newWorkspace?.id) {
        localStorage.setItem(LS_KEY, newWorkspace.id);
        qc.setQueryData(["workspaces"], (current = []) => {
          if (!Array.isArray(current)) return [newWorkspace];
          if (current.some((workspace) => workspace.id === newWorkspace.id)) {
            return current.map((workspace) =>
              workspace.id === newWorkspace.id ? newWorkspace : workspace,
            );
          }
          return [...current, newWorkspace];
        });
      }
      qc.invalidateQueries({ queryKey: ["workspaces"] });
    },
  });
}

// ── Dashboard ──────────────────────────────────────────────────

const MOCK_DASHBOARD = {
  stats: dashboardStats,
  activity: recentActivity,
  alerts: staleAlerts,
};

function buildActivityFromGraph(graph) {
  const components = Array.isArray(graph?.components) ? graph.components : [];
  if (components.length === 0) return [];

  return components.slice(0, 5).map((component, index) => ({
    id: component.id ?? index,
    text: `Component available: ${component.name ?? "Untitled component"}`,
    ts: component.model_name ? `Model: ${component.model_name}` : "Current graph",
    type: component.status === "needs_review" ? "alert" : "create",
  }));
}

function buildDashboardIo({ connectors = [], sourceCount = 0, componentCount = 0, relationshipCount = 0 } = {}) {
  const availableConnectors = connectors.filter((connector) => connector.availability === "available");
  const connectedConnectors = availableConnectors.filter((connector) => connector.status === "connected");
  const comingSoonCount = connectors.filter((connector) => connector.availability === "coming_soon").length;
  const activeFeeds = connectedConnectors.length > 0 ? connectedConnectors : availableConnectors.slice(0, 4);
  const feedFallback = sourceCount > 0
    ? [{ name: "Source documents", detail: `${sourceCount} raw source${sourceCount === 1 ? "" : "s"} preserved` }]
    : [{ name: "Local files", detail: "Upload or import a source to start the graph" }];

  return {
    feeds: (activeFeeds.length > 0 ? activeFeeds.map((connector) => ({
      name: connector.name,
      detail: connector.status === "connected"
        ? `${connector.itemsSynced || 0} item${connector.itemsSynced === 1 ? "" : "s"} synced`
        : connector.message || "Available connector",
    })) : feedFallback).slice(0, 4),
    feedFooter: comingSoonCount > 0
      ? `${comingSoonCount} planned connector${comingSoonCount === 1 ? "" : "s"} kept as coming soon`
      : "Connector status is sourced from the backend catalog",
    outputs: [
      { name: "MCP server", detail: "Agent tools read graph facts with source IDs and evidence" },
      { name: "Context packs", detail: "Selection or full-graph handoffs include 1-hop neighbors" },
      { name: "Query API", detail: `${componentCount} facts searchable with retrieval trace` },
      { name: "Graph UI", detail: `${relationshipCount} relationship${relationshipCount === 1 ? "" : "s"} inspectable` },
    ],
  };
}

export function useDashboard() {
  return useQuery({
    queryKey: ["dashboard"],
    queryFn: withFallback(async () => {
      const wsId = await getWorkspaceId();
      if (!wsId) {
        const [stats, graph, connectorsPayload] = await Promise.all([
          api.get("/stats"),
          api.get("/graph"),
          api.get("/connectors"),
        ]);

        const sourceCount = stats?.sources ?? 0;
        const componentCount = stats?.components ?? graph?.components?.length ?? 0;
        const relationshipCount = stats?.relationships ?? graph?.relationships?.length ?? 0;
        const connectors = normalizeConnectors(connectorsPayload);
        return {
          stats: [
            { label: "Sources", value: sourceCount, icon: "database", delta: sourceCount > 0 ? `${sourceCount} source${sourceCount === 1 ? "" : "s"} ingested` : "No sources yet" },
            { label: "Models", value: stats?.models ?? graph?.models?.length ?? 0, icon: "cube", delta: "Current backend" },
            { label: "Components", value: componentCount, icon: "puzzle", delta: `${stats?.pending_review ?? 0} pending review` },
            { label: "Relationships", value: relationshipCount, icon: "link", delta: "Graph edges" },
          ],
          activity: buildActivityFromGraph(graph),
          alerts: staleAlerts,
          io: buildDashboardIo({ connectors, sourceCount, componentCount, relationshipCount }),
        };
      }

      const [stats, models, connectorsPayload, sources] = await Promise.all([
        api.get(`/stats?workspace_id=${wsId}`),
        api.get(`/models?workspace_id=${wsId}`),
        api.get(`/connectors?workspace_id=${wsId}`),
        api.get(`${FOUNDER_WORKFLOW_API.sourceDocuments}?workspace_id=${wsId}&limit=1`),
      ]);
      const connectors = normalizeConnectors(connectorsPayload);
      const totalComponents = stats?.components
        ?? models.reduce((n, m) => n + (m.component_count ?? 0), 0);
      const relationshipCount = stats?.relationships ?? 0;
      
      const sourceDocumentCount = stats?.sources ?? sources?.total ?? 0;
      const activeConnectorCount = connectors.filter(
        (connector) => connector.status === "connected" || connector.status === "error",
      ).length;
      const sourceDelta =
        activeConnectorCount > 0
          ? `${activeConnectorCount} connector${activeConnectorCount === 1 ? "" : "s"} active`
          : sourceDocumentCount > 0
            ? `${sourceDocumentCount} document${sourceDocumentCount === 1 ? "" : "s"} uploaded`
            : "No connectors active";

      return {
        stats: [
          { label: "Sources", value: sourceDocumentCount, icon: "database", delta: sourceDelta },
          { label: "Models", value: models.length, icon: "cube", delta: "—" },
          { label: "Components", value: totalComponents, icon: "puzzle", delta: "—" },
          { label: "Relationships", value: relationshipCount, icon: "link", delta: "—" },
        ],
        activity: recentActivity, // no backend endpoint yet
        alerts: staleAlerts, // no backend endpoint yet
        io: buildDashboardIo({
          connectors,
          sourceCount: sourceDocumentCount,
          componentCount: totalComponents,
          relationshipCount,
        }),
      };
    }, MOCK_DASHBOARD),
  });
}

// ── Operator status ────────────────────────────────────────────

export function useOperatorStatus() {
  return useQuery({
    queryKey: ["operator-status"],
    queryFn: async () => {
      let lastNotFound = null;

      for (const endpoint of OPERATOR_STATUS_ENDPOINTS) {
        try {
          const data = await api.get(endpoint);
          return { endpoint: `/api${endpoint}`, data };
        } catch (err) {
          if (err.status === 404) {
            lastNotFound = err;
            continue;
          }
          throw err;
        }
      }

      throw lastNotFound ?? new Error("No operator status endpoint is available.");
    },
    retry: 1,
    refetchInterval: 30000,
    refetchIntervalInBackground: false,
  });
}

// ── Models (list) ──────────────────────────────────────────────

export function useModels() {
  return useQuery({
    queryKey: ["models"],
    queryFn: withFallback(async () => {
      const wsId = await getWorkspaceId();
      if (!wsId) return [];
      return api.get(`/models?workspace_id=${wsId}`);
    }, []),
  });
}

// ── Model detail ───────────────────────────────────────────────

export function useModel(modelId) {
  return useQuery({
    queryKey: ["model", modelId],
    queryFn: withFallback(
      () => api.get(`/models/${modelId}`),
      modelFixtures[modelId] ?? {
        name: `Model: ${modelId}`,
        description: "No mock data available for this model ID.",
        lastUpdated: "—",
        components: [],
      },
    ),
    enabled: !!modelId,
  });
}

// ── Connectors ─────────────────────────────────────────────────

export function useConnectors() {
  const query = useQuery({
    queryKey: ["connectors"],
    queryFn: withFallback(
      async () => {
        const wsId = await getWorkspaceId();
        const connectorPath = wsId ? `/connectors?workspace_id=${wsId}` : "/connectors";
        const connectorPayload = await api.get(connectorPath);
        if (Array.isArray(connectorPayload)) {
          const setupStatus = await api.get("/connectors/setup-status").catch(() => []);
          return { connectors: connectorPayload, setupStatus };
        }
        if (Array.isArray(connectorPayload?.connectors)) {
          return {
            connectors: connectorPayload.connectors,
            setupStatus: Array.isArray(connectorPayload.setupStatus)
              ? connectorPayload.setupStatus
              : await api.get("/connectors/setup-status").catch(() => []),
          };
        }
        return connectorPayload;
      },
      mockConnectors,
      { fallbackStatuses: [404, 501] },
    ),
  });
  const refetch = useCallback(async () => {
    const result = await query.refetch();
    return {
      ...result,
      data: normalizeConnectors(result.data),
      isMock: result.data === mockConnectors,
    };
  }, [query.refetch]);
  return {
    ...query,
    data: normalizeConnectors(query.data),
    isMock: query.data === mockConnectors,
    refetch,
  };
}

export function useConnectorSyncStatus(connectorId, { enabled = true } = {}) {
  return useQuery({
    queryKey: ["connector-sync-status", connectorId],
    enabled: enabled && !!connectorId,
    retry: false,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "pending" || status === "running" ? 2000 : false;
    },
    queryFn: async () => {
      try {
        const data = await api.get(`/connectors/${connectorId}/sync-status`);
        return normalizeSyncJob(data);
      } catch (err) {
        if (err.status && ![404, 422, 500, 501, 502, 503].includes(err.status)) {
          throw err;
        }
        return null;
      }
    },
  });
}

export function useConnectorSyncJobs(connectorId, { enabled = true } = {}) {
  return useQuery({
    queryKey: ["connector-sync-jobs", connectorId],
    enabled: enabled && !!connectorId,
    retry: false,
    refetchInterval: (query) => {
      const jobs = query.state.data ?? [];
      const hasActive = jobs.some((job) => job.status === "pending" || job.status === "running");
      return hasActive ? 2000 : false;
    },
    queryFn: async () => {
      try {
        const data = await api.get(`/connectors/${connectorId}/sync-jobs`);
        return Array.isArray(data) ? data.map(normalizeSyncJob) : [];
      } catch (err) {
        if (err.status && ![404, 422, 500, 501, 502, 503].includes(err.status)) {
          throw err;
        }
        return [];
      }
    },
  });
}

// ── Source Documents ────────────────────────────────────────────

export function useSourceDocuments(filters = {}) {
  const { connector = "all", processed = "all", search = "" } = filters;
  const query = useInfiniteQuery({
    queryKey: ["source-documents", connector, processed, search],
    initialPageParam: null,
    queryFn: async ({ pageParam }) => {
      const wsId = await getWorkspaceId();
      if (!wsId) {
        return {
          items: [],
          total: 0,
          hasMore: false,
          nextCursor: null,
          isMock: false,
        };
      }

      const params = new URLSearchParams({ workspace_id: wsId });
      if (connector !== "all") params.set("connector_type", connector);
      if (processed !== "all") params.set("processed", String(processed === "processed"));
      if (pageParam) params.set("cursor", pageParam);
      params.set("limit", "25");

      try {
        const data = await api.get(`${FOUNDER_WORKFLOW_API.sourceDocuments}?${params.toString()}`);
        const items = applySourceSearchFilter(normalizeSourceDocuments(data.items ?? []), search);
        return {
          items,
          total: data.total ?? items.length,
          hasMore: Boolean(data.has_more),
          nextCursor: data.next_cursor ?? null,
          isMock: false,
        };
      } catch (err) {
        if (err.status && ![404, 501].includes(err.status)) {
          throw err;
        }
        if (!MOCKS_ENABLED) throw err;
        if (err.status) {
          console.warn(`[api] source-documents unavailable (${err.status}), using mock data (VITE_USE_MOCKS=true)`);
        } else {
          console.warn("[api] backend unreachable for source-documents, using mock data (VITE_USE_MOCKS=true)");
        }
        if (pageParam) {
          return {
            items: [],
            total: 0,
            hasMore: false,
            nextCursor: null,
            isMock: true,
          };
        }
        const items = filterMockSourceDocuments(mockSourceDocuments, { connector, processed, search });
        return {
          items,
          total: items.length,
          hasMore: false,
          nextCursor: null,
          isMock: true,
        };
      }
    },
    getNextPageParam: (lastPage) => (lastPage.hasMore ? lastPage.nextCursor : undefined),
  });

  const pages = query.data?.pages ?? [];
  const data = pages.flatMap((page) => page.items);
  const firstPage = pages[0];

  return {
    ...query,
    data,
    total: search.trim() ? data.length : (firstPage?.total ?? data.length),
    hasMore: query.hasNextPage ?? false,
    isMock: firstPage?.isMock ?? false,
  };
}

export function useSourceDocument(documentId) {
  return useQuery({
    queryKey: ["source-document", documentId],
    enabled: !!documentId,
    queryFn: async () => {
      const wsId = await getWorkspaceId();
      if (!wsId || !documentId) return null;

      try {
        const data = await api.get(
          `${FOUNDER_WORKFLOW_API.sourceDocuments}/${documentId}?workspace_id=${wsId}`,
        );
        return normalizeSourceDocuments([data])[0] ?? null;
      } catch (err) {
        if (err.status && ![404, 422, 500, 501, 502, 503].includes(err.status)) {
          throw err;
        }
        if (!MOCKS_ENABLED) throw err;
        const fallback = normalizeSourceDocuments(mockSourceDocuments).find((doc) => doc.id === documentId);
        return fallback ?? null;
      }
    },
  });
}

export function useSourceDocumentComponents(documentId) {
  return useQuery({
    queryKey: ["source-document-components", documentId],
    enabled: !!documentId,
    queryFn: async () => {
      const wsId = await getWorkspaceId();
      if (!wsId || !documentId) return [];

      try {
        const data = await api.get(
          `${FOUNDER_WORKFLOW_API.sourceDocuments}/${documentId}/components?workspace_id=${wsId}`,
        );
        return normalizeSourceComponentRefs(data);
      } catch (err) {
        if (err.status && ![404, 422, 500, 501, 502, 503].includes(err.status)) {
          throw err;
        }
        if (!MOCKS_ENABLED) throw err;
        return buildMockSourceComponentRefs(documentId);
      }
    },
  });
}

export function useComponentSources(componentId, { enabled = true } = {}) {
  return useQuery({
    queryKey: ["component-sources", componentId],
    enabled: enabled && !!componentId,
    queryFn: async () => {
      const wsId = await getWorkspaceId();
      if (!componentId || !wsId) return [];

      try {
        const data = await api.get(`/components/${componentId}/sources?workspace_id=${wsId}`);
        return normalizeComponentSourceRefs(data);
      } catch (err) {
        if (err.status && ![404, 422, 500, 501, 502, 503].includes(err.status)) {
          throw err;
        }
        if (!MOCKS_ENABLED) throw err;
        return buildMockComponentSources(componentId);
      }
    },
  });
}

export function useSourceDocumentReviewItems(documentId) {
  return useQuery({
    queryKey: ["source-document-review-items", documentId],
    enabled: !!documentId,
    queryFn: async () => {
      const wsId = await getWorkspaceId();
      if (!wsId || !documentId) return [];

      try {
        const params = new URLSearchParams({
          workspace_id: wsId,
          source_document_id: documentId,
        });
        const data = await api.get(`/review-items?${params.toString()}`);
        // data can be an array or { items: [], total: N }
        return normalizeReviewItems(data);
      } catch (err) {
        if (err.status && ![404, 422, 500, 501, 502, 503].includes(err.status)) {
          throw err;
        }
        if (!MOCKS_ENABLED) throw err;
        return buildMockSourceReviewItems(documentId);
      }
    },
  });
}

export function useConnectorProcessingSummary() {
  return useQuery({
    queryKey: ["connector-processing-summary"],
    queryFn: async () => {
      const wsId = await getWorkspaceId();
      if (!wsId) return { items: [], isMock: false };

      try {
        const data = await api.get(`/connectors/processing-summary?workspace_id=${wsId}`);
        return {
          items: normalizeProcessingSummary(data),
          isMock: false,
        };
      } catch (err) {
        if (err.status && ![404, 501].includes(err.status)) {
          throw err;
        }
        if (!MOCKS_ENABLED) throw err;
        return {
          items: buildMockProcessingSummary(mockSourceDocuments),
          isMock: true,
        };
      }
    },
  });
}

export function useReviewQueue(filters = {}) {
  const { status = "all", severity = "all", kind = "all", source_id = null, model_id = null, search = "" } = filters;
  const query = useInfiniteQuery({
    queryKey: ["review-queue", status, severity, kind, source_id, model_id, search],
    initialPageParam: 0,
    getNextPageParam: (lastPage, allPages) => {
      const currentCount = allPages.reduce((acc, page) => acc + page.items.length, 0);
      if (currentCount < lastPage.total) {
        return currentCount;
      }
      return undefined;
    },
    queryFn: async ({ pageParam = 0 }) => {
      const wsId = await getWorkspaceId();
      if (!wsId) return { items: [], total: 0, isMock: false };

      const params = new URLSearchParams({ workspace_id: wsId, limit: "20", offset: String(pageParam) });
      if (status !== "all") params.set("status", status);
      if (severity !== "all") params.set("severity", severity);
      if (kind !== "all") params.set("kind", kind);
      if (source_id) params.set("source_document_id", source_id);
      if (model_id) params.set("model_id", model_id);
      if (search) params.set("search", search);

      try {
        const data = await api.get(`/review-items?${params.toString()}`);
        return { 
          items: normalizeReviewItems(data), 
          total: data.total ?? data.items?.length ?? 0, 
          isMock: false 
        };
      } catch (err) {
        if (err.status && ![404, 501].includes(err.status)) {
          throw err;
        }
        if (!MOCKS_ENABLED) throw err;
        const mockItems = filterReviewItems(normalizeReviewItems(mockReviewQueue), { status, severity, kind });
        return {
          items: mockItems.slice(pageParam, pageParam + 20),
          total: mockItems.length,
          isMock: true,
        };
      }
    },
  });
  return {
    ...query,
    data: query.data?.pages.flatMap((page) => page.items) ?? [],
    total: query.data?.pages[0]?.total ?? 0,
    isMock: query.data?.pages[0]?.isMock ?? false,
  };
}
// ── Accuracy / eval summary ──────────────────────────────────

export function useEvalSummary() {
  const query = useQuery({
    queryKey: ["eval-summary"],
    queryFn: async () => {
      const wsId = await getWorkspaceId();
      if (!wsId) return { summary: null, isMock: false };

      try {
        const data = await api.get(`/evals/summary?workspace_id=${wsId}`);
        return { summary: normalizeEvalSummary(data), isMock: false };
      } catch (err) {
        if (err.status && ![400, 404, 422, 500, 501, 502, 503].includes(err.status)) {
          throw err;
        }
        if (!MOCKS_ENABLED) throw err;
        return { summary: normalizeEvalSummary(mockEvalSummary), isMock: true };
      }
    },
  });

  return {
    ...query,
    data: query.data?.summary ?? null,
    isMock: query.data?.isMock ?? false,
  };
}

export function useEvalCases(domain, { enabled = true } = {}) {
  const query = useQuery({
    queryKey: ["eval-cases", domain],
    enabled: enabled && !!domain,
    queryFn: async () => {
      const wsId = await getWorkspaceId();
      if (!wsId || !domain) return { payload: null, isMock: false };

      const params = new URLSearchParams({ workspace_id: wsId, domain });
      try {
        const data = await api.get(`/evals/cases?${params.toString()}`);
        return { payload: normalizeEvalCases(data), isMock: false };
      } catch (err) {
        if (err.status && ![400, 404, 422, 500, 501, 502, 503].includes(err.status)) {
          throw err;
        }
        if (!MOCKS_ENABLED) throw err;
        return {
          payload: normalizeEvalCases(mockEvalCasesByDomain[domain] ?? { selectedDomain: domain, cases: [] }),
          isMock: true,
        };
      }
    },
  });

  return {
    ...query,
    data: query.data?.payload ?? null,
    isMock: query.data?.isMock ?? false,
  };
}

export function useRunEvals() {
  const qc = useQueryClient();

  return useMutation({
    mutationFn: async ({ domains, caseIds, passThreshold } = {}) => {
      const wsId = await getWorkspaceId();
      if (!wsId) {
        throw new Error("No workspace available for eval run");
      }

      const payload = { workspace_id: wsId };
      if (Array.isArray(domains) && domains.length > 0) {
        payload.domains = domains;
      }
      if (Array.isArray(caseIds) && caseIds.length > 0) {
        payload.case_ids = caseIds;
      }
      if (passThreshold != null) {
        payload.pass_threshold = passThreshold;
      }

      const data = await api.post("/evals/run", payload);
      return normalizeEvalCases(data);
    },
    onSuccess: async (_data, variables) => {
      await Promise.all([
        qc.invalidateQueries({ queryKey: ["eval-summary"] }),
        qc.invalidateQueries({ queryKey: ["eval-cases"] }),
        qc.invalidateQueries({ queryKey: ["dashboard"] }),
      ]);

      if (Array.isArray(variables?.domains) && variables.domains.length === 1) {
        await qc.invalidateQueries({ queryKey: ["eval-cases", variables.domains[0]] });
      }
    },
  });
}

// ── Workflow views ───────────────────────────────────────────

export function useFounderBrief(lookbackDays = 7) {
  const query = useQuery({
    queryKey: ["founder-brief", lookbackDays],
    queryFn: async () => {
      const wsId = await getWorkspaceId();
      if (!wsId) return { brief: null, isMock: false };

      const params = new URLSearchParams({
        workspace_id: wsId,
        lookback_days: String(lookbackDays),
      });

      try {
        const data = await api.get(`${FOUNDER_WORKFLOW_API.founderBrief}?${params.toString()}`);
        return { brief: normalizeFounderBrief(data), isMock: false };
      } catch (err) {
        if (err.status && ![404, 500, 501, 502, 503].includes(err.status)) {
          throw err;
        }
        if (!MOCKS_ENABLED) throw err;
        return { brief: buildMockFounderBrief(), isMock: true };
      }
    },
  });

  return {
    ...query,
    data: query.data?.brief ?? null,
    isMock: query.data?.isMock ?? false,
  };
}

export function useTimeline(limit = 50) {
  const query = useInfiniteQuery({
    queryKey: ["timeline", limit],
    initialPageParam: null,
    queryFn: async ({ pageParam }) => {
      const wsId = await getWorkspaceId();
      if (!wsId) {
        const params = new URLSearchParams({ limit: String(limit) });
        if (pageParam) params.set("cursor", pageParam);
        const data = await api.get(`/timeline?${params.toString()}`);
        return { timeline: normalizeTimelinePayload(data), isMock: false };
      }

      const params = new URLSearchParams({
        workspace_id: wsId,
        limit: String(limit),
      });
      if (pageParam) params.set("cursor", pageParam);

      try {
        const data = await api.get(`/timeline?${params.toString()}`);
        return { timeline: normalizeTimelinePayload(data), isMock: false };
      } catch (err) {
        if (err.status && ![404, 422, 500, 501, 502, 503].includes(err.status)) {
          throw err;
        }
        if (!MOCKS_ENABLED) throw err;
        if (pageParam) {
          return {
            timeline: {
              workspaceId: wsId,
              generatedAt: null,
              totalEvents: 0,
              hasMore: false,
              nextCursor: null,
              items: [],
            },
            isMock: true,
          };
        }
        return { timeline: buildMockTimeline(limit), isMock: true };
      }
    },
    getNextPageParam: (lastPage) =>
      lastPage.timeline?.hasMore ? lastPage.timeline.nextCursor : undefined,
  });

  const pages = query.data?.pages ?? [];
  const firstPage = pages[0]?.timeline ?? {
    workspaceId: null,
    generatedAt: null,
    totalEvents: 0,
    hasMore: false,
    nextCursor: null,
    items: [],
  };
  const data = {
    workspaceId: firstPage.workspaceId,
    generatedAt: firstPage.generatedAt,
    totalEvents: firstPage.totalEvents ?? 0,
    hasMore: query.hasNextPage ?? false,
    nextCursor: pages.at(-1)?.timeline?.nextCursor ?? null,
    items: pages.flatMap((page) => page.timeline?.items ?? []),
  };

  return {
    ...query,
    data,
    hasMore: query.hasNextPage ?? false,
    isMock: firstPage.items.length > 0 ? (pages[0]?.isMock ?? false) : false,
  };
}

export function useDecisionRegister() {
  const query = useQuery({
    queryKey: ["decision-register"],
    queryFn: async () => {
      const wsId = await getWorkspaceId();
      if (!wsId) return { items: [], isMock: false };

      try {
        const params = new URLSearchParams({
          workspace_id: wsId,
          include_historical: "true",
          limit: "100",
        });
        const data = await api.get(`${FOUNDER_WORKFLOW_API.decisions}?${params.toString()}`);
        return { items: normalizeDecisionRegisterItems(data), isMock: false };
      } catch (err) {
        if (err.status && ![404, 500, 501, 502, 503].includes(err.status)) {
          throw err;
        }
        if (!MOCKS_ENABLED) throw err;
        const documents = normalizeSourceDocuments(mockSourceDocuments).filter(
          isDecisionLikeDocument,
        );
        return {
          items: buildDecisionRegisterItems(
            documents,
            Object.fromEntries(documents.map((doc) => [doc.id, buildMockSourceComponentRefs(doc.id)])),
          ),
          isMock: true,
        };
      }
    },
  });

  return {
    ...query,
    data: query.data?.items ?? [],
    isMock: query.data?.isMock ?? false,
  };
}

export function useDecisionHistory(componentId, { enabled = true } = {}) {
  return useQuery({
    queryKey: ["decision-history", componentId],
    enabled: enabled && !!componentId,
    queryFn: async () => {
      const wsId = await getWorkspaceId();
      if (!wsId || !componentId) return null;

      try {
        const data = await api.get(
          `${FOUNDER_WORKFLOW_API.decisions}/${componentId}/history?workspace_id=${wsId}`,
        );
        return normalizeDecisionHistoryPayload(data);
      } catch (err) {
        if (err.status && ![404, 500, 501, 502, 503].includes(err.status)) {
          throw err;
        }
        return null;
      }
    },
  });
}

export function useLaunchGuardContext() {
  const query = useQuery({
    queryKey: ["launch-guard-context"],
    queryFn: async () => {
      const wsId = await getWorkspaceId();
      if (!wsId) return { payload: emptyLaunchGuardContext(), isMock: false };

      try {
        const [models, reviewData, sourceData] = await Promise.all([
          api.get(`/models?workspace_id=${wsId}`),
          api.get(`/review-items?workspace_id=${wsId}`),
          api.get(`${FOUNDER_WORKFLOW_API.sourceDocuments}?workspace_id=${wsId}&processed=true&limit=100`),
        ]);

        const modelDetails = await Promise.all(
          (models ?? []).map((model) => api.get(`/models/${model.id}`)),
        );
        const components = modelDetails.flatMap((detail) =>
          normalizeLaunchGuardComponents(detail),
        );
        const documents = normalizeSourceDocuments(sourceData.items ?? []);
        const decisionDocuments = documents.filter(isDecisionLikeDocument);
        const componentEntries = await Promise.all(
          decisionDocuments.map(async (doc) => {
            try {
              const linked = await api.get(
                `${FOUNDER_WORKFLOW_API.sourceDocuments}/${doc.id}/components?workspace_id=${wsId}`,
              );
              return [doc.id, normalizeSourceComponentRefs(linked)];
            } catch (err) {
              if (err.status && ![404, 500, 501, 502, 503].includes(err.status)) {
                throw err;
              }
              return [doc.id, buildMockSourceComponentRefs(doc.id)];
            }
          }),
        );

        let evalSummary = null;
        try {
          const evalData = await api.get(`/evals/summary?workspace_id=${wsId}`);
          evalSummary = normalizeEvalSummary(evalData);
        } catch (err) {
          if (err.status && ![400, 404, 422, 500, 501, 502, 503].includes(err.status)) {
            throw err;
          }
        }

        return {
          payload: {
            components,
            reviewItems: normalizeReviewItems(reviewData),
            decisions: buildDecisionRegisterItems(
              decisionDocuments,
              Object.fromEntries(componentEntries),
            ),
            evalSummary,
          },
          isMock: false,
        };
      } catch (err) {
        if (err.status && ![400, 404, 422, 500, 501, 502, 503].includes(err.status)) {
          throw err;
        }
        if (!MOCKS_ENABLED) throw err;
        return {
          payload: buildMockLaunchGuardContext(),
          isMock: true,
        };
      }
    },
  });

  return {
    ...query,
    data: query.data?.payload ?? emptyLaunchGuardContext(),
    isMock: query.data?.isMock ?? false,
  };
}

export function useLaunchGuardCheck() {
  return useMutation({
    mutationFn: async (draft) => {
      const wsId = await getWorkspaceId();
      return api.post("/launch-guard/check", {
        workspace_id: wsId,
        draft,
      });
    },
  });
}

// ── Knowledge Graph ────────────────────────────────────────────

const MOCK_GRAPH = { nodes: mockGraphNodes, edges: mockGraphEdges };

function formatRelationshipLabel(value) {
  return String(value ?? "")
    .replaceAll("_", " ")
    .trim();
}

function positionGraphNodes(nodes) {
  const modelNodes = nodes.filter((node) => node.type === "model");
  const componentNodes = nodes.filter((node) => node.type !== "model");
  const positions = new Map();

  const width = 760;
  const topY = 110;
  const modelGap = width / Math.max(modelNodes.length + 1, 2);

  modelNodes.forEach((node, index) => {
    positions.set(node.id, {
      x: Math.round((index + 1) * modelGap),
      y: topY,
    });
  });

  const groupedByModel = new Map();
  componentNodes.forEach((node) => {
    const groupKey = node.modelId ?? "__ungrouped__";
    const group = groupedByModel.get(groupKey) ?? [];
    group.push(node);
    groupedByModel.set(groupKey, group);
  });

  groupedByModel.forEach((groupNodes, groupKey) => {
    const anchor =
      positions.get(groupKey) ??
      {
        x: Math.round(width / 2),
        y: 250,
      };
    const radius = groupNodes.length <= 1 ? 0 : Math.min(170, 70 + groupNodes.length * 10);

    groupNodes.forEach((node, index) => {
      if (groupNodes.length === 1) {
        positions.set(node.id, { x: anchor.x, y: anchor.y + 120 });
        return;
      }

      const angle = (-Math.PI / 2) + ((Math.PI * 2 * index) / groupNodes.length);
      positions.set(node.id, {
        x: Math.round(anchor.x + Math.cos(angle) * radius),
        y: Math.round(anchor.y + 150 + Math.sin(angle) * radius * 0.58),
      });
    });
  });

  return nodes.map((node) => ({
    ...node,
    ...(positions.get(node.id) ?? { x: Math.round(width / 2), y: 250 }),
  }));
}

function normalizeGraphResponse(graph) {
  const modelNodeMap = new Map();
  const componentNodeMap = new Map();
  const edgeMap = new Map();

  graph?.nodes?.forEach((node) => {
    if (node.model_id && !modelNodeMap.has(node.model_id)) {
      modelNodeMap.set(node.model_id, {
        id: node.model_id,
        label: node.model_name ?? "Model",
        type: "model",
        modelId: node.model_id,
      });
    }

    componentNodeMap.set(node.id, {
      id: node.id,
      label: node.name,
      type: "component",
      modelId: node.model_id,
      reviewStatus: node.review_status,
      reviewItemId: node.review_item_id,
      temporalState: node.temporal_state,
      isStale: Boolean(node.is_stale),
      authorityWeight: node.authority_weight,
      sourceCount: node.source_count,
      confidence: node.confidence,
    });

    if (node.model_id) {
      edgeMap.set(`model:${node.model_id}:${node.id}`, {
        id: `model:${node.model_id}:${node.id}`,
        source: node.model_id,
        target: node.id,
        label: "contains",
      });
    }
  });

  graph?.edges?.forEach((edge) => {
    edgeMap.set(edge.id, {
      id: edge.id,
      source: edge.source_component_id ?? edge.source_id,
      target: edge.target_component_id ?? edge.target_id,
      label: formatRelationshipLabel(edge.relationship_type),
      sentiment: edge.sentiment,
      confidence: edge.confidence,
      temporalState: edge.temporal_state,
    });
  });

  return {
    nodes: positionGraphNodes([
      ...modelNodeMap.values(),
      ...componentNodeMap.values(),
    ]),
    edges: [...edgeMap.values()],
    includeHistorical: graph?.include_historical ?? false,
    hiddenNodeCount: graph?.hidden_node_count ?? 0,
    rootComponentId: graph?.root_component_id ?? graph?.root_id ?? null,
  };
}

export function useKnowledgeGraph({ viewMode = "workspace", selectedNodeId = null } = {}) {
  const workspaceQuery = useQuery({
    queryKey: ["knowledge-graph"],
    queryFn: withFallback(async () => {
      const wsId = await getWorkspaceId();
      if (!wsId) return { nodes: [], edges: [] };

      return normalizeGraphResponse(
        await api.get(`/graph?workspace_id=${wsId}`),
      );
    }, MOCK_GRAPH, { fallbackStatuses: [404, 501] }),
  });

  const selectedWorkspaceNode =
    workspaceQuery.data?.nodes?.find((node) => node.id === selectedNodeId) ?? null;

  const localQuery = useQuery({
    queryKey: [
      "knowledge-graph",
      "local",
      selectedWorkspaceNode?.type ?? null,
      selectedWorkspaceNode?.id ?? null,
    ],
    enabled:
      viewMode === "local" &&
      !!selectedWorkspaceNode &&
      (selectedWorkspaceNode.type === "model" || selectedWorkspaceNode.type === "component"),
    queryFn: withFallback(async () => {
      if (!selectedWorkspaceNode) {
        return { nodes: [], edges: [] };
      }

      if (selectedWorkspaceNode.type === "model") {
        return normalizeGraphResponse(
          await api.get(`/graph/models/${selectedWorkspaceNode.id}`),
        );
      }

      return normalizeGraphResponse(
        await api.get(`/graph/components/${selectedWorkspaceNode.id}?depth=1`),
      );
    }, MOCK_GRAPH, { fallbackStatuses: [404, 501] }),
  });

  const usingLocalGraph =
    viewMode === "local" &&
    !!selectedWorkspaceNode &&
    (selectedWorkspaceNode.type === "model" || selectedWorkspaceNode.type === "component");

  const data =
    usingLocalGraph && localQuery.data
      ? localQuery.data
      : workspaceQuery.data;
  const isMock =
    usingLocalGraph && localQuery.data
      ? localQuery.data === MOCK_GRAPH
      : workspaceQuery.data === MOCK_GRAPH;
  const isLoading =
    workspaceQuery.isLoading || (usingLocalGraph && localQuery.isLoading && !localQuery.data);
  const isError =
    workspaceQuery.isError || (usingLocalGraph && localQuery.isError && !localQuery.data);
  const error =
    usingLocalGraph && localQuery.isError
      ? localQuery.error
      : workspaceQuery.error;
  const refetch = usingLocalGraph ? localQuery.refetch : workspaceQuery.refetch;

  return {
    data,
    isMock,
    isLoading,
    isError,
    error,
    refetch,
  };
}

// ── Context Query ─────────────────────────────────────────────

const MOCK_QUERY_RESPONSE = mockQueryExamples;

/**
 * Submit a natural-language question to the Context API.
 *
 * Stable founder workflow contract: POST /api/query with explicit workspace_id.
 * Falls back to mock data only on network failure when VITE_USE_MOCKS=true.
 */
export function useContextQuery() {
  return useMutation({
    mutationFn: async (input) => {
      const request =
        typeof input === "string"
          ? { question: input, maxAgeDays: null, asOf: null }
          : {
              question: input?.question ?? "",
              maxAgeDays: input?.maxAgeDays ?? null,
              asOf: input?.asOf ?? null,
            };
      try {
        const wsId = await getWorkspaceId();
        return await api.post(FOUNDER_WORKFLOW_API.query, {
          question: request.question,
          workspace_id: wsId,
          ...(request.maxAgeDays != null ? { max_age_days: request.maxAgeDays } : {}),
          ...(request.asOf ? { as_of: request.asOf } : {}),
        });
      } catch (err) {
        // Only fall back to mock on network errors (backend unreachable)
        // and only when VITE_USE_MOCKS=true.
        if (err.status) throw err;
        if (!MOCKS_ENABLED) throw err;

        // Simulate latency then return a mock answer that best matches the question
        await new Promise((r) => setTimeout(r, 800));
        const q = request.question.toLowerCase();
        const match = MOCK_QUERY_RESPONSE.find((m) =>
          m.question.toLowerCase().split(" ").some((w) => w.length > 3 && q.includes(w)),
        );
        return {
          ...(match ?? MOCK_QUERY_RESPONSE[0]),
          question: request.question,
          answeredAt: "just now",
          ...(request.asOf ? { asOf: request.asOf } : {}),
          _isMock: true,
        };
      }
    },
  });
}

// ── Relationships (per model) ──────────────────────────────────

export function useModelRelationships(modelId) {
  return useQuery({
    queryKey: ["model-relationships", modelId],
    queryFn: withFallback(
      () => api.get(`/models/${modelId}/relationships`),
      [],
    ),
    enabled: !!modelId,
  });
}

// ── Mutations ──────────────────────────────────────────────────

export function useCreateModel() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body) => {
      const wsId = await getWorkspaceId();
      return api.post("/models", { workspace_id: wsId, ...body });
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["models"] }),
  });
}

export function useCreateComponent(modelId) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body) => api.post(`/models/${modelId}/components`, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["model", modelId] }),
  });
}

export function useUpdateComponent() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ componentId, ...body }) => api.patch(`/components/${componentId}`, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["model"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
}

export function useDeleteComponent() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (componentId) => api.delete(`/components/${componentId}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["model"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
}

export function useCreateRelationship() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body) => api.post("/relationships", body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["model-relationships"] }),
  });
}

export function useSyncConnector() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (connectorId) => api.post(`/connectors/${connectorId}/sync`, {}),
    onSuccess: (_data, connectorId) => {
      qc.invalidateQueries({ queryKey: ["connectors"] });
      qc.invalidateQueries({ queryKey: ["connector-sync-status", connectorId] });
      qc.invalidateQueries({ queryKey: ["connector-sync-jobs", connectorId] });
      qc.invalidateQueries({ queryKey: ["connector-processing-summary"] });
    },
  });
}

export function useDisconnectConnector() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (connectorId) => api.delete(`/connectors/${connectorId}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["connectors"] });
      qc.invalidateQueries({ queryKey: ["connector-processing-summary"] });
      qc.invalidateQueries({ queryKey: ["connector-sync-status"] });
      qc.invalidateQueries({ queryKey: ["connector-sync-jobs"] });
    },
  });
}

export function useApproveReviewItem() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (reviewItemId) => {
      const wsId = await getWorkspaceId();
      return api.post(`/review-items/${reviewItemId}/approve?workspace_id=${wsId}`, {});
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["review-queue"] });
      qc.invalidateQueries({ queryKey: ["source-document-review-items"] });
      qc.invalidateQueries({ queryKey: ["source-document-components"] });
      qc.invalidateQueries({ queryKey: ["model"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
}

export function useRejectReviewItem() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (reviewItemId) => {
      const wsId = await getWorkspaceId();
      return api.post(`/review-items/${reviewItemId}/reject?workspace_id=${wsId}`, {});
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["review-queue"] });
      qc.invalidateQueries({ queryKey: ["source-document-review-items"] });
      qc.invalidateQueries({ queryKey: ["source-document-components"] });
      qc.invalidateQueries({ queryKey: ["model"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
}

export function useSupersedeReviewItem() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (reviewItemId) => {
      const wsId = await getWorkspaceId();
      return api.post(`/review-items/${reviewItemId}/supersede?workspace_id=${wsId}`, {});
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["review-queue"] });
      qc.invalidateQueries({ queryKey: ["source-document-review-items"] });
      qc.invalidateQueries({ queryKey: ["source-document-components"] });
      qc.invalidateQueries({ queryKey: ["model"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
}

export function useReprocessSourceDocument() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (documentId) => {
      const wsId = await getWorkspaceId();
      const job = await api.post(
        `${FOUNDER_WORKFLOW_API.sourceDocuments}/${documentId}/reprocess?workspace_id=${wsId}`,
        {},
      );
      return normalizeSyncJob(job);
    },
    onSuccess: (job, documentId) => {
      qc.invalidateQueries({ queryKey: ["source-documents"] });
      qc.invalidateQueries({ queryKey: ["source-document", documentId] });
      qc.invalidateQueries({ queryKey: ["source-document-components", documentId] });
      qc.invalidateQueries({ queryKey: ["source-document-review-items", documentId] });
      qc.invalidateQueries({ queryKey: ["connector-processing-summary"] });
      qc.invalidateQueries({ queryKey: ["connectors"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      if (job?.connectorId) {
        qc.invalidateQueries({ queryKey: ["connector-sync-status", job.connectorId] });
        qc.invalidateQueries({ queryKey: ["connector-sync-jobs", job.connectorId] });
      }
    },
  });
}

export function useDeleteSourceDocument() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (documentId) => {
      const wsId = await getWorkspaceId();
      await api.delete(
        `${FOUNDER_WORKFLOW_API.sourceDocuments}/${documentId}?workspace_id=${wsId}`,
      );
      return { documentId };
    },
    onSuccess: (_result, documentId) => {
      qc.invalidateQueries({ queryKey: ["source-documents"] });
      qc.invalidateQueries({ queryKey: ["source-document", documentId] });
      qc.invalidateQueries({ queryKey: ["source-document-components", documentId] });
      qc.invalidateQueries({ queryKey: ["source-document-review-items", documentId] });
      qc.invalidateQueries({ queryKey: ["connector-processing-summary"] });
      qc.invalidateQueries({ queryKey: ["review-queue"] });
      qc.invalidateQueries({ queryKey: ["founder-brief"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
}

export function useRestoreSourceDocument() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (documentId) => {
      const wsId = await getWorkspaceId();
      const data = await api.post(
        `${FOUNDER_WORKFLOW_API.sourceDocuments}/${documentId}/restore?workspace_id=${wsId}`,
        {},
      );
      return normalizeSourceDocuments([data])[0] ?? null;
    },
    onSuccess: (document, documentId) => {
      qc.invalidateQueries({ queryKey: ["source-documents"] });
      qc.invalidateQueries({ queryKey: ["source-document", documentId] });
      qc.invalidateQueries({ queryKey: ["source-document-components", documentId] });
      qc.invalidateQueries({ queryKey: ["source-document-review-items", documentId] });
      qc.invalidateQueries({ queryKey: ["connector-processing-summary"] });
      qc.invalidateQueries({ queryKey: ["review-queue"] });
      qc.invalidateQueries({ queryKey: ["founder-brief"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      if (document?.connectorId) {
        qc.invalidateQueries({ queryKey: ["connector-sync-status", document.connectorId] });
        qc.invalidateQueries({ queryKey: ["connector-sync-jobs", document.connectorId] });
      }
    },
  });
}

export function useConnectGitHub() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ token, repositories }) => {
      const wsId = await getWorkspaceId();
      return api.post("/connectors/github/connect", {
        workspace_id: wsId,
        token,
        repositories,
      });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["connectors"] });
      qc.invalidateQueries({ queryKey: ["connector-processing-summary"] });
      qc.invalidateQueries({ queryKey: ["source-documents"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
}

export function useIngestAISession() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ connectorType, sessionId, content }) => {
      const wsId = await getWorkspaceId();
      return api.post("/connectors/ai-session/ingest", {
        workspace_id: wsId,
        connector_type: connectorType,
        session_id: sessionId,
        content,
      });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["connectors"] });
      qc.invalidateQueries({ queryKey: ["connector-processing-summary"] });
      qc.invalidateQueries({ queryKey: ["source-documents"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
}

export function useImportAISessionById() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ connectorType, sessionId }) => {
      const wsId = await getWorkspaceId();
      return api.post("/connectors/ai-session/import-by-id", {
        workspace_id: wsId,
        connector_type: connectorType,
        session_id: sessionId,
      });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["connectors"] });
      qc.invalidateQueries({ queryKey: ["connector-processing-summary"] });
      qc.invalidateQueries({ queryKey: ["source-documents"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
}

export function useSaveSlackOAuthSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ clientId, clientSecret, redirectUri }) => api.post("/connectors/slack/oauth-settings", {
      client_id: clientId,
      client_secret: clientSecret,
      redirect_uri: redirectUri,
    }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["connectors"] });
      qc.invalidateQueries({ queryKey: ["connector-processing-summary"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
}

export function useSeedDemoData() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (input) => {
      const payload = input && typeof input === "object" ? input : {};
      const hasExplicitWorkspace =
        Object.prototype.hasOwnProperty.call(payload, "workspaceId") ||
        Object.prototype.hasOwnProperty.call(payload, "workspace_id");
      const workspaceId = hasExplicitWorkspace
        ? (payload.workspaceId ?? payload.workspace_id ?? null)
        : null;
      return api.post(
        FOUNDER_WORKFLOW_API.seedDemo,
        workspaceId ? { workspace_id: workspaceId } : {},
      );
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["workspaces"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      qc.invalidateQueries({ queryKey: ["connectors"] });
      qc.invalidateQueries({ queryKey: ["connector-processing-summary"] });
      qc.invalidateQueries({ queryKey: ["source-documents"] });
    },
  });
}

export function useUploadSourceFile() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (input) => {
      const payload = normalizeUploadInput(input);
      const files = Array.isArray(payload.files) ? payload.files : [];
      if (files.length === 0) {
        throw new Error("Select at least one file to import.");
      }

      const workspaceId = payload.workspaceId ?? payload.workspace_id ?? await getWorkspaceId();
      if (!workspaceId) {
        throw new Error("Workspace not found.");
      }

      const documents = await Promise.all(files.map((file) => buildBrowserImportDocument(file)));
      const externalIds = new Set();
      for (const document of documents) {
        if (externalIds.has(document.external_id)) {
          throw new Error("Selected files must have unique names or paths.");
        }
        externalIds.add(document.external_id);
      }

      return api.post(FOUNDER_WORKFLOW_API.imports, {
        workspace_id: workspaceId,
        documents,
      });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["connectors"] });
      qc.invalidateQueries({ queryKey: ["source-documents"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      qc.invalidateQueries({ queryKey: ["connector-processing-summary"] });
    },
  });
}

function normalizeConnectors(data) {
  const rawConnectors = Array.isArray(data) ? data : data?.connectors;
  const setupStatus = Array.isArray(data?.setupStatus) ? data.setupStatus : [];
  if (!Array.isArray(rawConnectors)) return [];

  const setupByType = new Map(
    setupStatus
      .filter((item) => item?.connector_type)
      .map((item) => [item.connector_type, item]),
  );

  const isMockShape = rawConnectors.length > 0 && rawConnectors.every((item) => item && "lastSync" in item);
  if (isMockShape) {
    return rawConnectors.map((item) => {
      const type = item.type ?? item.id;
      const catalogItem = CONNECTOR_CATALOG[type] ?? {};
      return {
        ...catalogItem,
        ...item,
        type,
        connectorId: null,
        availability: catalogItem.availability ?? "coming_soon",
        isInstalled: item.status === "connected" || item.status === "warning" || item.status === "error",
        status:
          catalogItem.availability === "available"
            ? item.status
            : "coming_soon",
        provider: item.provider ?? catalogItem.provider,
        providerLabel: item.providerLabel ?? catalogItem.providerLabel,
        providerNote: item.providerNote ?? catalogItem.providerNote,
        setupStatus: item.setupStatus ?? null,
        isConfigured: item.isConfigured ?? item.setupStatus?.configured ?? true,
        managedConnectAvailable: item.managedConnectAvailable ?? item.setupStatus?.managed_available ?? false,
        managedInstallUrl: item.managedInstallUrl ?? item.setupStatus?.managed_install_url ?? null,
        missingConfig: item.missingConfig ?? item.setupStatus?.missing ?? [],
      };
    });
  }

  const recordsByType = new Map(
    rawConnectors
      .filter((item) => item?.connector_type)
      .map((item) => [item.connector_type, item]),
  );

  return Object.values(CONNECTOR_CATALOG).map((catalogItem) => {
    const record = recordsByType.get(catalogItem.type);
    const setup = setupByType.get(catalogItem.type) ?? record?.setup_status ?? null;
    const isConfigured = setup?.configured ?? record?.is_configured ?? true;
    const managedConnectAvailable = Boolean(setup?.managed_available);
    const availability = record?.availability ?? catalogItem.availability;
    const normalizedStatus = availability === "coming_soon"
      ? "coming_soon"
      : record?.status ?? setup?.status ?? "disconnected";
    if (!record) {
      return {
        ...catalogItem,
        id: catalogItem.type,
        connectorId: null,
        status:
          availability === "available" ? "disconnected" : "coming_soon",
        availability,
        isInstalled: false,
        lastSync: "Never",
        itemsSynced: 0,
        setupStatus: setup,
        isConfigured,
        managedConnectAvailable,
        managedInstallUrl: setup?.managed_install_url ?? null,
        missingConfig: Array.isArray(setup?.missing) ? setup.missing : [],
        redirectUri: setup?.redirect_uri ?? null,
        message:
          catalogItem.type === "slack" && !isConfigured && !managedConnectAvailable
            ? setup?.message ?? "Slack OAuth is not configured yet."
            : availability === "available"
            ? "Not connected yet."
            : "Planned after the Slack reference connector ships.",
      };
    }

    return {
      ...catalogItem,
      id: record.id ?? record.connector_id ?? catalogItem.type,
      connectorId: record.connector_id ?? null,
      status: normalizedStatus,
      isInstalled: normalizedStatus === "connected" || normalizedStatus === "warning" || normalizedStatus === "error",
      availability,
      lastSync: formatConnectorDate(record.last_sync_at),
      itemsSynced: extractConnectorCount(record.config),
      message: record.message ?? record.config?.message ?? null,
      teamName: record.config?.team_name ?? null,
      teamId: record.config?.team_id ?? null,
      scope: record.config?.scope ?? null,
      syncQueuedAt: formatConnectorDate(record.config?.sync_queued_at, { fallback: null }),
      syncMode: record.config?.sync_mode ?? null,
      syncModeNote: record.config?.sync_mode_note ?? null,
      processedCount: Number(record.config?.processed_count ?? 0),
      totalProcessedCount: Number(record.config?.total_processed_count ?? 0),
      authMode: record.config?.auth_mode ?? null,
      accountId: record.config?.account_id ?? null,
      repositories: Array.isArray(record.config?.repositories) ? record.config.repositories : [],
      ingestionMode: record.config?.ingestion_mode ?? null,
      sourceFocus: record.config?.source_focus ?? null,
      lastWebhookEvent: record.config?.last_zoom_webhook_event ?? null,
      lastWebhookReceivedAt: formatConnectorDate(record.config?.last_zoom_webhook_received_at, {
        fallback: null,
      }),
      provider: record.provider ?? catalogItem.provider,
      providerLabel: record.provider_label ?? record.providerLabel ?? catalogItem.providerLabel,
      providerNote: record.provider_note ?? catalogItem.providerNote,
      setupStatus: setup,
      isConfigured,
      managedConnectAvailable,
      managedInstallUrl: setup?.managed_install_url ?? null,
      missingConfig: Array.isArray(setup?.missing) ? setup.missing : [],
      redirectUri: setup?.redirect_uri ?? null,
    };
  });
}

function normalizeSyncJob(data) {
  if (!data) return null;

  return {
    jobId: data.jobId ?? data.job_id ?? data.id ?? null,
    jobType: data.jobType ?? data.job_type ?? "sync",
    connectorId: data.connectorId ?? data.connector_id ?? null,
    status: data.status ?? "pending",
    startedAt: data.startedAt ?? data.started_at ?? null,
    completedAt: data.completedAt ?? data.completed_at ?? null,
    errorType: data.errorType ?? data.error_type ?? null,
    errorMessage: data.errorMessage ?? data.error_message ?? null,
    createdAt: data.createdAt ?? data.created_at ?? null,
    resultMetadata: data.resultMetadata ?? data.result_metadata ?? {},
  };
}

function normalizeSourceDocuments(data) {
  if (!Array.isArray(data)) return [];

  return data.map((item) => {
    const connectorType = item.connectorType ?? item.connector_type ?? "unknown";
    const metadata = item.metadata ?? item.metadata_json ?? {};
    return {
      id: item.id,
      connectorId: item.connectorId ?? item.connector_id ?? null,
      connectorType,
      externalId: item.externalId ?? item.external_id,
      author: item.author ?? "Unknown",
      content: item.content ?? "",
      preview: item.content ?? "",
      sourceUrl: item.sourceUrl ?? item.source_url ?? null,
      createdAtSource: item.createdAtSource ?? item.created_at_source ?? null,
      ingestedAt: item.ingestedAt ?? item.ingested_at ?? null,
      processedAt: item.processedAt ?? item.processed_at ?? null,
      deletedAt: item.deletedAt ?? item.deleted_at ?? null,
      deleted: Boolean(item.deletedAt ?? item.deleted_at),
      processed: Boolean(item.processedAt ?? item.processed_at),
      location:
        metadata.location ??
        metadata.channel_name ??
        metadata.meeting_topic ??
        metadata.team_name ??
        metadata.page_title ??
        metadata.page_id ??
        item.location ??
        null,
      meetingTopic: metadata.meeting_topic ?? item.meetingTopic ?? item.meeting_topic ?? null,
      host: metadata.host ?? item.host ?? null,
      participants: Array.isArray(metadata.participants)
        ? metadata.participants
        : Array.isArray(item.participants)
          ? item.participants
          : [],
      recordingDate: metadata.recording_date ?? item.recordingDate ?? item.recording_date ?? null,
      transcriptTimestamp:
        metadata.transcript_timestamp ??
        item.transcriptTimestamp ??
        item.transcript_timestamp ??
        null,
      sourceType: metadata.source_type ?? item.sourceType ?? item.source_type ?? null,
      repository: metadata.repo_full_name ?? item.repository ?? item.repo_full_name ?? null,
      documentTitle: metadata.title ?? item.documentTitle ?? item.title ?? null,
      githubItemType: metadata.item_type ?? item.githubItemType ?? item.item_type ?? null,
      parentExternalId:
        metadata.parent_external_id ?? item.parentExternalId ?? item.parent_external_id ?? null,
      pullRequestReferences:
        metadata.pull_request_references ??
        item.pullRequestReferences ??
        item.pull_request_references ??
        [],
      commitReferences:
        metadata.commit_references ??
        item.commitReferences ??
        item.commit_references ??
        [],
      metadata,
    };
  });
}

function filterMockSourceDocuments(data, filters) {
  const items = normalizeSourceDocuments(data);
  const connector = filters.connector ?? "all";
  const processed = filters.processed ?? "all";
  const search = (filters.search ?? "").trim().toLowerCase();

  return items.filter((item) => {
    const matchesConnector = connector === "all" || item.connectorType === connector;
    const matchesProcessed =
      processed === "all" ||
      (processed === "processed" && item.processed) ||
      (processed === "unprocessed" && !item.processed);
    const haystack = [
      item.author,
      item.content,
      item.location,
      item.externalId,
      item.connectorType,
    ]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();
    const matchesSearch = !search || haystack.includes(search);
    return matchesConnector && matchesProcessed && matchesSearch;
  });
}

function normalizeProcessingSummary(data) {
  const items = Array.isArray(data) ? data : Array.isArray(data?.items) ? data.items : [];
  return items.map((item) => ({
    connectorId: item.connectorId ?? item.connector_id ?? null,
    connectorType: item.connectorType ?? item.connector_type,
    status: item.status,
    totalDocuments: Number(item.totalDocuments ?? item.total_documents ?? 0),
    processedDocuments: Number(item.processedDocuments ?? item.processed_documents ?? 0),
    unprocessedDocuments: Number(item.unprocessedDocuments ?? item.unprocessed_documents ?? 0),
    lastSyncAt: formatConnectorDate(item.lastSyncAt ?? item.last_sync_at),
  }));
}

function buildMockProcessingSummary(data) {
  const docs = normalizeSourceDocuments(data);
  const groups = new Map();
  for (const doc of docs) {
    const current = groups.get(doc.connectorType) ?? {
      connectorId: doc.connectorType,
      connectorType: doc.connectorType,
      status: "connected",
      totalDocuments: 0,
      processedDocuments: 0,
      unprocessedDocuments: 0,
      lastSyncAt: formatConnectorDate(doc.ingestedAt),
    };
    current.totalDocuments += 1;
    if (doc.processed) current.processedDocuments += 1;
    else current.unprocessedDocuments += 1;
    groups.set(doc.connectorType, current);
  }
  return Array.from(groups.values());
}

function normalizeReviewItems(data) {
  const items = Array.isArray(data) ? data : (data?.items && Array.isArray(data.items) ? data.items : []);
  if (items.length === 0) return [];
  return items.map((item) => ({
    id: item.id,
    status: item.status ?? "needs_review",
    severity: item.severity ?? "medium",
    kind: item.kind ?? "review_item",
    title: item.title ?? "Untitled review item",
    summary: item.summary ?? item.detail ?? "",
    confidence: typeof item.confidence === "number" ? item.confidence : null,
    freshness: item.freshness ?? formatConnectorDate(item.last_seen_at, { fallback: "—" }),
    model: item.model ?? item.model_name ?? null,
    modelId: item.modelId ?? item.model_id ?? null,
    sources: item.sources ?? [],
    sourceDocuments: item.sourceDocuments ?? item.source_documents ?? [],
    rationale: item.rationale ?? item.detail ?? "",
    suggestedAction: item.suggestedAction ?? item.suggested_action ?? null,
    lastSeenAt: item.lastSeenAt ?? item.last_seen_at ?? null,
    decisionHistory: normalizeReviewDecisionHistory(
      item.decisionHistory ?? item.decision_history ?? [],
    ),
  }));
}

function normalizeReviewDecisionHistory(data) {
  if (!Array.isArray(data)) return [];
  return data.map((item) => ({
    id: item.id,
    previousStatus: item.previousStatus ?? item.previous_status ?? null,
    newStatus: item.newStatus ?? item.new_status ?? null,
    actorType: item.actorType ?? item.actor_type ?? null,
    note: item.note ?? null,
    createdAt: item.createdAt ?? item.created_at ?? null,
  }));
}

function normalizeEvalSummary(data) {
  if (!data || typeof data !== "object") return null;

  const source = data.summary ?? data;
  const domains = Array.isArray(source.domains)
    ? source.domains
    : Array.isArray(source.domain_summaries)
      ? source.domain_summaries
      : [];

  return {
    passRate: toNumber(
      source.passRate ??
        source.pass_rate ??
        source.overall_pass_rate ??
        source.passRateOverall,
    ),
    passedCases: toNumber(
      source.passedCases ?? source.passed_cases ?? source.passed_count ?? source.total_passed ?? 0,
    ),
    totalCases: toNumber(
      source.totalCases ?? source.total_cases ?? source.total ?? source.case_count ?? 0,
    ),
    threshold: toNumber(source.threshold ?? source.pass_threshold ?? null),
    latestRunAt:
      source.latestRunAt ??
      source.latest_run_at ??
      source.latest_run_timestamp ??
      source.generated_at ??
      null,
    domains: domains.map((item) => ({
      domain: item.domain ?? item.name ?? "unknown",
      passRate: toNumber(item.passRate ?? item.pass_rate ?? 0),
      passed: toNumber(item.passed ?? item.passed_cases ?? item.case_count ?? 0),
      total: toNumber(item.total ?? item.total_cases ?? item.case_count ?? 0),
      avgCitation: toNumber(item.avgCitation ?? item.avg_citation ?? null),
      avgStaleness: toNumber(item.avgStaleness ?? item.avg_staleness ?? null),
      avgContextLift: toNumber(item.avgContextLift ?? item.avg_context_lift ?? null),
    })),
    metrics: normalizeEvalMetrics(
      source.metrics ??
        source.metric_summary ??
        buildEvalMetricSummary(source),
    ),
    blockers: normalizeEvalBlockers(source.blockers ?? []),
  };
}

function normalizeEvalMetrics(data) {
  if (Array.isArray(data)) {
    return data.map((item, index) => ({
      key: item.key ?? item.metric ?? `metric_${index + 1}`,
      label: item.label ?? item.metric ?? `Metric ${index + 1}`,
      value: toNumber(item.value ?? 0),
      target: toNumber(item.target ?? null),
      direction: item.direction === "down" ? "down" : "up",
    }));
  }

  if (!data || typeof data !== "object") return [];

  return Object.entries(data).map(([key, value]) => ({
    key,
    label: key.replaceAll("_", " "),
    value: toNumber(value ?? 0),
    target: null,
    direction: key.includes("error") ? "down" : "up",
  }));
}

function buildEvalMetricSummary(source) {
  const metrics = [];

  if (source.average_retrieval_hit_quality != null) {
    metrics.push({
      key: "average_retrieval_hit_quality",
      label: "Retrieval hit quality",
      value: source.average_retrieval_hit_quality,
      direction: "up",
    });
  }
  if (source.average_extracted_fact_correctness != null) {
    metrics.push({
      key: "average_extracted_fact_correctness",
      label: "Extracted fact correctness",
      value: source.average_extracted_fact_correctness,
      direction: "up",
    });
  }
  if (source.average_final_answer_correctness != null) {
    metrics.push({
      key: "average_final_answer_correctness",
      label: "Final answer correctness",
      value: source.average_final_answer_correctness,
      direction: "up",
    });
  }
  if (source.average_citation_accuracy != null) {
    metrics.push({
      key: "average_citation_accuracy",
      label: "Citation accuracy",
      value: source.average_citation_accuracy,
      direction: "up",
    });
  }
  if (source.average_stale_context_detection != null) {
    metrics.push({
      key: "average_stale_context_detection",
      label: "Stale context detection",
      value: source.average_stale_context_detection,
      direction: "up",
    });
  }
  if (source.average_naive_answer_correctness != null) {
    metrics.push({
      key: "average_naive_answer_correctness",
      label: "Naive RAG answer correctness",
      value: source.average_naive_answer_correctness,
      direction: "up",
    });
  }
  if (source.average_context_answer_lift != null) {
    metrics.push({
      key: "average_context_answer_lift",
      label: "Context answer lift",
      value: source.average_context_answer_lift,
      direction: "up",
    });
  }
  if (source.confidence_calibration_error != null) {
    metrics.push({
      key: "confidence_calibration_error",
      label: "Confidence calibration error",
      value: source.confidence_calibration_error,
      direction: "down",
    });
  }

  return metrics;
}

function normalizeEvalCases(data) {
  if (!data || typeof data !== "object") return null;

  const source = data;
  return {
    selectedDomain: source.selectedDomain ?? source.selected_domain ?? null,
    cases: normalizeEvalCaseItems(source.cases ?? []),
  };
}

function normalizeEvalCaseItems(data) {
  if (!Array.isArray(data)) return [];
  return data.map((item) => ({
    caseId: item.caseId ?? item.case_id ?? null,
    domain: item.domain ?? "unknown",
    question: item.question ?? "Untitled eval case",
    predictedConfidence: toNumber(item.predictedConfidence ?? item.predicted_confidence ?? null),
    retrievalHitQuality: toNumber(item.retrievalHitQuality ?? item.retrieval_hit_quality ?? null),
    extractedFactCorrectness: toNumber(
      item.extractedFactCorrectness ?? item.extracted_fact_correctness ?? null,
    ),
    finalAnswerCorrectness: toNumber(
      item.finalAnswerCorrectness ?? item.final_answer_correctness ?? null,
    ),
    citationAccuracy: toNumber(item.citationAccuracy ?? item.citation_accuracy ?? null),
    staleContextDetection: toNumber(
      item.staleContextDetection ?? item.stale_context_detection ?? null,
    ),
    naiveAnswerCorrectness: toNumber(
      item.naiveAnswerCorrectness ?? item.naive_answer_correctness ?? null,
    ),
    contextAnswerLift: toNumber(item.contextAnswerLift ?? item.context_answer_lift ?? null),
    passed: Boolean(item.passed),
    detail: item.detail ?? "",
  }));
}

function normalizeEvalBlockers(data) {
  if (!Array.isArray(data)) return [];
  return data.map((item) =>
    typeof item === "string"
      ? item
      : item?.detail ?? item?.question ?? item?.case_id ?? "Unknown blocker",
  );
}

function toNumber(value) {
  if (value == null || value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function normalizeSourceComponentRefs(data) {
  if (!Array.isArray(data)) return [];
  return data.map((item) => ({
    id: item.id,
    name: item.name ?? "Unnamed component",
    value: item.value ?? "",
    confidence: typeof item.confidence === "number" ? item.confidence : null,
    modelId: item.modelId ?? item.model_id ?? null,
    modelName: item.modelName ?? item.model_name ?? item.model ?? "Unknown model",
    authorityWeight: toNumber(item.authorityWeight ?? item.authority_weight ?? null),
    reviewStatus: item.reviewStatus ?? item.review_status ?? null,
    reviewItemId: item.reviewItemId ?? item.review_item_id ?? null,
    reviewSummary: item.reviewSummary ?? item.review_summary ?? null,
    decisionHistory: normalizeReviewDecisionHistory(
      item.decisionHistory ?? item.decision_history ?? [],
    ),
    temporalState: item.temporalState ?? item.temporal_state ?? null,
    validFrom: item.validFrom ?? item.valid_from ?? null,
    validTo: item.validTo ?? item.valid_to ?? null,
    supersededBy: item.supersededBy ?? item.superseded_by ?? null,
    sourceDocuments: normalizeComponentSourceRefs(item.sourceDocuments ?? item.source_documents ?? []),
  }));
}

function normalizeDecisionRegisterItems(data) {
  if (!Array.isArray(data)) return [];

  return data
    .map((item) => {
      const rationaleSources = normalizeDecisionRationaleSources(
        item.rationaleSources ?? item.rationale_sources ?? [],
      );
      const primarySource = rationaleSources[0] ?? null;
      return {
        id: item.id,
        title: extractDecisionTitleFromFact(item.name, item.value),
        summary:
          rationaleSources[0]?.extractedValue ??
          rationaleSources[0]?.extractionContext ??
          item.value ??
          "No source summary available yet.",
        status: normalizeDecisionStatus(item),
        sourceDocumentId: primarySource?.sourceDocumentId ?? null,
        sourceUrl: primarySource?.sourceUrl ?? null,
        connectorType: primarySource?.connectorType ?? null,
        sourceLabel: primarySource?.label ?? item.model_name ?? item.modelName ?? "Decision source",
        author: primarySource?.author ?? null,
        createdAt: item.validFrom ?? item.valid_from ?? null,
        updatedAt: item.validFrom ?? item.valid_from ?? null,
        meetingTopic: null,
        relatedBlocker: item.reviewSummary ?? item.review_summary ?? null,
        modelNames: [item.modelName ?? item.model_name ?? "Unknown model"].filter(Boolean),
        reviewItemIds: [item.reviewItemId ?? item.review_item_id].filter(Boolean),
        averageConfidence: toNumber(item.confidence),
        affectedComponents: [
          normalizeSourceComponentRefs([
            {
              ...item,
              model_id: item.modelId ?? item.model_id,
              model_name: item.modelName ?? item.model_name,
              authority_weight: item.authorityWeight ?? item.authority_weight,
              review_status: item.reviewStatus ?? item.review_status,
              review_item_id: item.reviewItemId ?? item.review_item_id,
              review_summary: item.reviewSummary ?? item.review_summary,
              temporal_state: item.temporalState ?? item.temporal_state,
              valid_from: item.validFrom ?? item.valid_from,
              valid_to: item.validTo ?? item.valid_to,
              superseded_by: item.supersededBy ?? item.superseded_by,
              decision_history: item.decisionHistory ?? item.decision_history,
              source_documents: rationaleSources,
            },
          ])[0],
        ].filter(Boolean),
        decisionHistory: normalizeReviewDecisionHistory(
          item.decisionHistory ?? item.decision_history ?? [],
        ),
        rationaleSources,
        historyAvailable: true,
      };
    })
    .sort((a, b) => new Date(b.createdAt ?? 0) - new Date(a.createdAt ?? 0));
}

function normalizeDecisionHistoryPayload(data) {
  if (!data || typeof data !== "object") return null;
  return {
    workspaceId: data.workspaceId ?? data.workspace_id ?? null,
    decisionName: data.decisionName ?? data.decision_name ?? "Decision history",
    currentDecisionId: data.currentDecisionId ?? data.current_decision_id ?? null,
    entries: normalizeDecisionRegisterItems(data.entries ?? []),
  };
}

function normalizeDecisionRationaleSources(data) {
  if (!Array.isArray(data)) return [];
  return data.map((item, index) => ({
    id: item.sourceDocumentId ?? item.source_document_id ?? `decision-source-${index + 1}`,
    sourceDocumentId: item.sourceDocumentId ?? item.source_document_id ?? null,
    label: item.label ?? `Source ${index + 1}`,
    connectorType: item.connectorType ?? item.connector_type ?? null,
    sourceUrl: item.sourceUrl ?? item.source_url ?? null,
    author: item.author ?? null,
    createdAtSource: item.createdAtSource ?? item.created_at_source ?? null,
    extractionContext: item.extractionContext ?? item.extraction_context ?? null,
    extractedValue: item.extractedValue ?? item.extracted_value ?? null,
    extractorName: item.extractorName ?? item.extractor_name ?? null,
    extractorKind: item.extractorKind ?? item.extractor_kind ?? null,
    extractorSchemaVersion:
      item.extractorSchemaVersion ?? item.extractor_schema_version ?? null,
  }));
}

function normalizeDecisionStatus(item) {
  const explicit = normalizeValue(
    item.reviewStatus ?? item.review_status ?? item.temporalState ?? item.temporal_state,
  );
  if (explicit === "needs_review") return "needs_review";
  if (explicit === "historical" || explicit === "superseded") return "historical";
  if ((item.validTo ?? item.valid_to) != null) return "historical";
  return "current";
}

function extractDecisionTitleFromFact(name, value) {
  const cleanedName = String(name ?? "").replace(/^decision:\s*/i, "").trim();
  const cleanedValue = trimSentence(value ?? "");
  if (cleanedValue) return cleanedValue;
  return cleanedName || "Untitled decision";
}

function normalizeFounderBrief(data) {
  if (!data || typeof data !== "object") return null;

  return {
    workspaceId: data.workspaceId ?? data.workspace_id ?? null,
    generatedAt: data.generatedAt ?? data.generated_at ?? null,
    lookbackDays: toNumber(data.lookbackDays ?? data.lookback_days ?? null),
    changedFacts: normalizeFounderBriefFacts(data.changedFacts ?? data.changed_facts ?? []),
    newBlockers: normalizeFounderBriefFacts(data.newBlockers ?? data.new_blockers ?? []),
    openConflicts: normalizeFounderBriefConflicts(data.openConflicts ?? data.open_conflicts ?? []),
    staleHighRiskItems: normalizeFounderBriefRisks(
      data.staleHighRiskItems ?? data.stale_high_risk_items ?? [],
    ),
    recentConnectorFailures: normalizeFounderBriefFailures(
      data.recentConnectorFailures ?? data.recent_connector_failures ?? [],
    ),
  };
}

function normalizeFounderBriefFacts(data) {
  if (!Array.isArray(data)) return [];
  return data.map((item) => ({
    componentId: item.componentId ?? item.component_id ?? null,
    modelId: item.modelId ?? item.model_id ?? null,
    modelName: item.modelName ?? item.model_name ?? "Unknown model",
    name: item.name ?? "Unnamed fact",
    value: item.value ?? "",
    confidence: toNumber(item.confidence ?? null),
    authorityWeight: toNumber(item.authorityWeight ?? item.authority_weight ?? null),
    validFrom: item.validFrom ?? item.valid_from ?? null,
    reviewStatus: item.reviewStatus ?? item.review_status ?? null,
    reviewItemId: item.reviewItemId ?? item.review_item_id ?? null,
    sourceLabels: item.sourceLabels ?? item.source_labels ?? [],
  }));
}

function normalizeFounderBriefConflicts(data) {
  if (!Array.isArray(data)) return [];
  return data.map((item) => ({
    id: item.reviewItemId ?? item.review_item_id ?? item.id ?? null,
    reviewItemId: item.reviewItemId ?? item.review_item_id ?? item.id ?? null,
    componentId: item.componentId ?? item.component_id ?? null,
    componentName: item.componentName ?? item.component_name ?? "Unknown fact",
    status: item.status ?? "needs_review",
    severity: item.severity ?? "medium",
    kind: item.kind ?? "conflict",
    title: item.title ?? "Untitled conflict",
    summary: item.summary ?? "",
    suggestedAction: item.suggestedAction ?? item.suggested_action ?? null,
    createdAt: item.createdAt ?? item.created_at ?? null,
    updatedAt: item.updatedAt ?? item.updated_at ?? null,
  }));
}

function normalizeFounderBriefRisks(data) {
  if (!Array.isArray(data)) return [];
  return data.map((item) => ({
    componentId: item.componentId ?? item.component_id ?? null,
    name: item.name ?? "Unnamed fact",
    value: item.value ?? "",
    reason: item.reason ?? "",
    confidence: toNumber(item.confidence ?? null),
    reviewStatus: item.reviewStatus ?? item.review_status ?? null,
    sourceLabels: item.sourceLabels ?? item.source_labels ?? [],
  }));
}

function normalizeFounderBriefFailures(data) {
  if (!Array.isArray(data)) return [];
  return data.map((item) => ({
    jobId: item.jobId ?? item.job_id ?? null,
    connectorId: item.connectorId ?? item.connector_id ?? null,
    connectorType: item.connectorType ?? item.connector_type ?? "unknown",
    jobType: item.jobType ?? item.job_type ?? "sync",
    failedAt: item.failedAt ?? item.failed_at ?? null,
    errorType: item.errorType ?? item.error_type ?? null,
    errorMessage: item.errorMessage ?? item.error_message ?? null,
  }));
}

function normalizeTimelinePayload(data) {
  if (!data || typeof data !== "object") {
    return {
      workspaceId: null,
      generatedAt: null,
      totalEvents: 0,
      hasMore: false,
      nextCursor: null,
      items: [],
    };
  }

  const rawItems = Array.isArray(data.items)
    ? data.items
    : Array.isArray(data.events)
      ? data.events
      : [];

  const items = rawItems.length > 0
    ? rawItems.map((item, index) => normalizeTimelineItem(item, index))
    : [];

  return {
    workspaceId: data.workspaceId ?? data.workspace_id ?? null,
    generatedAt: data.generatedAt ?? data.generated_at ?? null,
    totalEvents: toNumber(data.totalEvents ?? data.total_events ?? data.events?.length ?? items.length),
    hasMore: Boolean(data.hasMore ?? data.has_more ?? false),
    nextCursor: data.nextCursor ?? data.next_cursor ?? null,
    items,
  };
}

function normalizeTimelineItem(item, index) {
  const type = normalizeTimelineType(item.eventType ?? item.event_type ?? item.type ?? null);
  const occurredAt = item.occurredAt ?? item.occurred_at ?? item.timestamp ?? null;
  const reviewItemId = item.reviewItemId ?? item.review_item_id ?? null;
  const sourceDocumentId = item.sourceDocumentId ?? item.source_document_id ?? null;
  const connectorType = item.connectorType ?? item.connector_type ?? null;
  const componentId = item.componentId ?? item.component_id ?? null;

  return {
    id:
      item.id ??
      `${type}-${reviewItemId ?? sourceDocumentId ?? componentId ?? connectorType ?? index}-${occurredAt ?? "event"}`,
    type,
    occurredAt,
    title: item.title ?? "Untitled event",
    summary: item.summary ?? "",
    status: item.status ?? null,
    componentId,
    reviewItemId,
    sourceDocumentId,
    connectorId: item.connectorId ?? item.connector_id ?? null,
    connectorType,
    sourceLabel: item.sourceLabel ?? item.source_label ?? null,
    modelName: item.modelName ?? item.model_name ?? null,
  };
}

function normalizeTimelineType(value) {
  const normalized = String(value ?? "").toLowerCase();
  if (normalized === "decision_change" || normalized === "decision") return "decision";
  if (normalized === "review_transition" || normalized === "review") return "review";
  if (normalized === "source_ingest" || normalized === "source") return "source";
  if (normalized === "connector_failure" || normalized === "connector") return "connector";
  return "other";
}

function buildMockFounderBrief() {
  const context = buildMockLaunchGuardContext();
  const connectors = normalizeConnectors(mockConnectors);
  const processingItems = buildMockProcessingSummary(mockSourceDocuments);
  const processingMap = new Map(
    processingItems.map((item) => [item.connectorType ?? item.type, item]),
  );

  return {
    workspaceId: "mock-workspace",
    generatedAt: new Date().toISOString(),
    lookbackDays: 7,
    changedFacts: context.components.slice(0, 4).map((item) => ({
      componentId: item.id,
      modelId: item.modelId,
      modelName: item.modelName,
      name: item.name,
      value: item.value,
      confidence: item.confidence,
      authorityWeight: item.authorityWeight,
      validFrom: item.validFrom,
      reviewStatus: item.reviewStatus,
      reviewItemId: item.reviewItemId,
      sourceLabels: (item.sourceDocuments ?? []).map((doc) => doc.label),
    })),
    newBlockers: context.components
      .filter((item) => String(item.name).toLowerCase().startsWith("blocker"))
      .slice(0, 4)
      .map((item) => ({
        componentId: item.id,
        modelId: item.modelId,
        modelName: item.modelName,
        name: item.name,
        value: item.value,
        confidence: item.confidence,
        authorityWeight: item.authorityWeight,
        validFrom: item.validFrom,
        reviewStatus: item.reviewStatus,
        reviewItemId: item.reviewItemId,
        sourceLabels: (item.sourceDocuments ?? []).map((doc) => doc.label),
      })),
    openConflicts: normalizeReviewItems(mockReviewQueue)
      .filter((item) => item.kind === "conflict" || item.status === "needs_review")
      .slice(0, 5)
      .map((item) => ({
        id: item.id,
        reviewItemId: item.id,
        componentId: null,
        componentName: item.model ?? "Unknown fact",
        status: item.status,
        severity: item.severity,
        kind: item.kind,
        title: item.title,
        summary: item.summary,
        suggestedAction: item.suggestedAction,
        createdAt: item.lastSeenAt,
        updatedAt: item.lastSeenAt,
      })),
    staleHighRiskItems: context.components
      .filter(
        (item) =>
          item.reviewStatus === "needs_review" ||
          item.temporalState === "historical" ||
          item.temporalState === "superseded",
      )
      .slice(0, 5)
      .map((item) => ({
        componentId: item.id,
        name: item.name,
        value: item.value,
        reason: item.reviewSummary ?? "Current fact still needs review.",
        confidence: item.confidence,
        reviewStatus: item.reviewStatus,
        sourceLabels: (item.sourceDocuments ?? []).map((doc) => doc.label),
      })),
    recentConnectorFailures: connectors
      .filter((item) => item.status === "error")
      .slice(0, 5)
      .map((item) => ({
        jobId: item.connectorId ?? item.type,
        connectorId: item.connectorId ?? item.type,
        connectorType: item.type,
        jobType: "sync",
        failedAt: new Date().toISOString(),
        errorType: "ConnectorError",
        errorMessage:
          item.message ??
          `${item.name} still has pipeline issues${processingMap.get(item.type)?.unprocessedDocuments ? " and pending documents." : "."}`,
      })),
  };
}

function buildMockTimeline(limit = 50) {
  const documents = normalizeSourceDocuments(mockSourceDocuments);
  const decisionDocuments = documents.filter(isDecisionLikeDocument);
  const componentsByDocument = Object.fromEntries(
    decisionDocuments.map((doc) => [doc.id, buildMockSourceComponentRefs(doc.id)]),
  );
  const decisions = buildDecisionRegisterItems(decisionDocuments, componentsByDocument);
  const reviewItems = normalizeReviewItems(mockReviewQueue);
  const connectors = normalizeConnectors(mockConnectors);
  const processingItems = buildMockProcessingSummary(mockSourceDocuments);
  const processingMap = new Map(
    processingItems.map((item) => [item.connectorType ?? item.type, item]),
  );

  const reviewEvents = reviewItems.flatMap((item) => {
    const history = item.decisionHistory ?? [];
    if (history.length === 0) {
      return [
        {
          id: `review-${item.id}`,
          type: "review",
          occurredAt: item.lastSeenAt ?? null,
          title: item.title,
          summary: item.summary,
          status: item.status,
          reviewItemId: item.id,
          modelName: item.model ?? null,
        },
      ];
    }
    return history.map((event) => ({
      id: `review-${item.id}-${event.id ?? event.createdAt ?? event.newStatus}`,
      type: "review",
      occurredAt: event.createdAt ?? item.lastSeenAt ?? null,
      title: item.title,
      summary: `${formatTimelineTransition(event.previousStatus, event.newStatus)}${event.note ? ` — ${event.note}` : ""}`,
      status: event.newStatus ?? item.status,
      reviewItemId: item.id,
      componentId: item.componentId ?? null,
      modelName: item.model ?? null,
    }));
  });

  const decisionEvents = decisions.map((item) => ({
    id: `decision-${item.id}`,
    type: "decision",
    occurredAt: item.createdAt ?? item.updatedAt ?? null,
    title: item.title,
    summary: item.summary,
    status: item.status,
    componentId: item.id,
    sourceDocumentId: item.sourceDocumentId ?? null,
    sourceLabel: item.sources?.[0]?.label ?? null,
    modelName: item.modelName ?? null,
  }));

  const sourceEvents = documents.slice(0, 12).map((item) => ({
    id: `source-${item.id}`,
    type: "source",
    occurredAt: item.ingestedAt ?? item.createdAtSource ?? null,
    title: formatMockTimelineSourceTitle(item),
    summary: item.processed
      ? "Stored and processed into structured context."
      : "Stored in the source layer and still waiting on extraction.",
    status: item.processed ? "processed" : "pending",
    sourceDocumentId: item.id,
    connectorId: item.connectorId ?? null,
    connectorType: item.connectorType ?? null,
    sourceLabel: item.label ?? null,
  }));

  const connectorEvents = connectors
    .map((connector) => {
      const processing = processingMap.get(connector.type) ?? null;
      const hasRisk =
        connector.status === "error" ||
        connector.status === "warning" ||
        connector.status === "disconnected" ||
        (processing?.unprocessedDocuments ?? 0) > 0;
      if (!hasRisk) return null;
      return {
        id: `connector-${connector.connectorId ?? connector.type}`,
        type: "connector",
        occurredAt: connector.lastWebhookReceivedAt ?? connector.syncQueuedAt ?? null,
        title: `${connector.name} connector`,
        summary:
          connector.status === "error"
            ? "Connector health needs attention before new context can be trusted."
            : (processing?.unprocessedDocuments ?? 0) > 0
              ? `${processing.unprocessedDocuments} documents still waiting on extraction.`
              : connector.syncMessage ?? "Connector needs attention.",
        status: connector.status,
        connectorId: connector.connectorId ?? null,
        connectorType: connector.type ?? null,
      };
    })
    .filter(Boolean);

  const items = [...reviewEvents, ...decisionEvents, ...sourceEvents, ...connectorEvents]
    .sort((a, b) => new Date(b.occurredAt ?? 0) - new Date(a.occurredAt ?? 0))
    .slice(0, limit);

  return {
    workspaceId: "mock-workspace",
    generatedAt: new Date().toISOString(),
    totalEvents: items.length,
    hasMore: false,
    nextCursor: null,
    items,
  };
}

function formatTimelineTransition(previousStatus, nextStatus) {
  if (!previousStatus && nextStatus) return `Moved to ${formatTimelineLabel(nextStatus)}`;
  if (previousStatus && nextStatus) {
    return `${formatTimelineLabel(previousStatus)} -> ${formatTimelineLabel(nextStatus)}`;
  }
  return "Review state updated";
}

function formatTimelineLabel(value) {
  if (!value) return "Unknown";
  return String(value).replace(/_/g, " ");
}

function formatMockTimelineSourceTitle(item) {
  if (item.meetingTopic) return `${item.meetingTopic} transcript ingested`;
  if (item.repository && item.documentTitle) return `${item.repository}: ${item.documentTitle}`;
  if (item.location) return `${item.location} source ingested`;
  return `${String(item.connectorType ?? "source").toUpperCase()} source ingested`;
}

function normalizeLaunchGuardComponents(detail) {
  const modelId = detail?.id ?? null;
  const modelName = detail?.name ?? "Unknown model";
  const components = Array.isArray(detail?.components) ? detail.components : [];

  return components.map((item) => ({
    id: item.id,
    name: item.name ?? "Unnamed component",
    value: item.value ?? "",
    confidence: typeof item.confidence === "number" ? item.confidence : null,
    modelId,
    modelName,
    reviewStatus: item.reviewStatus ?? item.review_status ?? null,
    reviewSummary: item.reviewSummary ?? item.review_summary ?? null,
    reviewItemId: item.reviewItemId ?? item.review_item_id ?? null,
    temporalState: item.temporalState ?? item.temporal_state ?? null,
    validFrom: item.validFrom ?? item.valid_from ?? null,
    validTo: item.validTo ?? item.valid_to ?? null,
    authorityWeight: toNumber(item.authorityWeight ?? item.authority_weight ?? null),
    decisionHistory: normalizeReviewDecisionHistory(
      item.decisionHistory ?? item.decision_history ?? [],
    ),
    sourceDocuments: normalizeComponentSourceRefs(
      item.sourceDocuments ?? item.source_documents ?? [],
    ),
  }));
}

function normalizeComponentSourceRefs(data) {
  if (!Array.isArray(data)) return [];
  return data.map((item, index) => ({
    id: item.id ?? `${item.external_id ?? "source"}-${index}`,
    label:
      item.label ??
      item.location ??
      item.author ??
      item.externalId ??
      item.external_id ??
      `Source ${index + 1}`,
    connectorType: item.connectorType ?? item.connector_type ?? null,
    author: item.author ?? null,
    sourceUrl: item.sourceUrl ?? item.source_url ?? null,
    createdAtSource: item.createdAtSource ?? item.created_at_source ?? null,
    ingestedAt: item.ingestedAt ?? item.ingested_at ?? null,
    processedAt: item.processedAt ?? item.processed_at ?? null,
    extractionContext: item.extractionContext ?? item.extraction_context ?? null,
    extractorName: item.extractorName ?? item.extractor_name ?? null,
    extractorKind: item.extractorKind ?? item.extractor_kind ?? null,
    extractorSchemaVersion:
      item.extractorSchemaVersion ?? item.extractor_schema_version ?? null,
  }));
}

function filterReviewItems(items, filters) {
  const { status = "all", severity = "all", kind = "all" } = filters;
  return items.filter((item) => {
    const matchesStatus = status === "all" || item.status === status;
    const matchesSeverity = severity === "all" || item.severity === severity;
    const matchesKind = kind === "all" || item.kind === kind;
    return matchesStatus && matchesSeverity && matchesKind;
  });
}

function buildMockSourceComponentRefs(documentId) {
  return Object.entries(modelFixtures).flatMap(([modelId, model]) =>
    (model.components ?? [])
      .filter((component) =>
        (component.sourceDocuments ?? component.source_documents ?? []).some((doc) => doc?.id === documentId),
      )
      .map((component) => ({
        id: component.id,
        name: component.name,
        value: component.value,
        confidence: typeof component.confidence === "number" ? component.confidence : null,
        modelId,
        modelName: model.name,
        authorityWeight: toNumber(component.authorityWeight ?? component.authority_weight ?? null),
        reviewStatus: component.reviewStatus ?? component.review_status ?? null,
        reviewItemId: component.reviewItemId ?? component.review_item_id ?? null,
        reviewSummary: component.reviewSummary ?? component.review_summary ?? null,
        decisionHistory: normalizeReviewDecisionHistory(
          component.decisionHistory ?? component.decision_history ?? [],
        ),
        temporalState: component.temporalState ?? component.temporal_state ?? null,
        validFrom: component.validFrom ?? component.valid_from ?? null,
        validTo: component.validTo ?? component.valid_to ?? null,
        supersededBy: component.supersededBy ?? component.superseded_by ?? null,
        sourceDocuments: normalizeComponentSourceRefs(
          component.sourceDocuments ?? component.source_documents ?? [],
        ),
      })),
  );
}

function buildDecisionRegisterItems(documents, componentsByDocument) {
  return documents
    .map((doc) => {
      const linkedComponents = (componentsByDocument[doc.id] ?? []).filter(Boolean);
      const status = deriveDecisionStatus(linkedComponents);
      const reviewItemIds = uniqueValues(
        linkedComponents.map((component) => component.reviewItemId).filter(Boolean),
      );
      const modelNames = uniqueValues(
        linkedComponents.map((component) => component.modelName).filter(Boolean),
      );
      const blocker = extractBlockerReference(doc, linkedComponents);
      const latestValidFrom = linkedComponents
        .map((component) => component.validFrom)
        .filter(Boolean)
        .sort()
        .at(-1);
      const latestDecisionHistory = linkedComponents
        .flatMap((component) => component.decisionHistory ?? [])
        .sort((a, b) => new Date(b.createdAt ?? 0) - new Date(a.createdAt ?? 0));
      const averageConfidence =
        linkedComponents.length > 0
          ? linkedComponents.reduce(
              (sum, component) => sum + (component.confidence ?? 0),
              0,
            ) / linkedComponents.length
          : null;

      return {
        id: doc.id,
        title: extractDecisionTitle(doc),
        summary: extractDecisionSummary(doc),
        status,
        sourceDocumentId: doc.id,
        sourceUrl: doc.sourceUrl ?? null,
        connectorType: doc.connectorType,
        sourceLabel: doc.location ?? doc.meetingTopic ?? doc.externalId ?? "Source document",
        author: doc.author ?? "Unknown",
        createdAt: doc.createdAtSource ?? doc.ingestedAt ?? null,
        updatedAt: latestValidFrom ?? doc.ingestedAt ?? null,
        meetingTopic: doc.meetingTopic ?? null,
        relatedBlocker: blocker,
        modelNames,
        reviewItemIds,
        averageConfidence,
        affectedComponents: linkedComponents,
        decisionHistory: latestDecisionHistory,
      };
    })
    .sort((a, b) => new Date(b.createdAt ?? 0) - new Date(a.createdAt ?? 0));
}

function isDecisionLikeDocument(doc) {
  const haystack = [doc.content, doc.location, doc.meetingTopic]
    .filter(Boolean)
    .join("\n")
    .toLowerCase();

  return [
    "decision:",
    "key decisions",
    "decided to",
    "we decided",
    "approved",
    "adopt ",
    "adopted",
    "selected",
    "choose ",
    "chose ",
    "launch the",
  ].some((token) => haystack.includes(token));
}

function deriveDecisionStatus(components) {
  if (!components.length) return "current";

  const reviewStates = components
    .map((component) => normalizeValue(component.reviewStatus))
    .filter(Boolean);
  const temporalStates = components
    .map((component) => normalizeValue(component.temporalState))
    .filter(Boolean);

  if (reviewStates.includes("needs_review")) return "needs_review";
  if (
    (temporalStates.length > 0 &&
      temporalStates.every((state) => state === "historical" || state === "superseded")) ||
    (reviewStates.length > 0 && reviewStates.every((state) => state === "superseded"))
  ) {
    return "historical";
  }
  return "current";
}

function extractDecisionTitle(doc) {
  const content = doc.content ?? "";
  const explicitDecision = content.match(/decision:\s*([^\n]+)/i)?.[1];
  if (explicitDecision) return trimSentence(explicitDecision);

  const keyDecisionLine = content
    .split("\n")
    .map((line) => line.trim())
    .find((line) => /^[-*]\s+/.test(line));
  if (keyDecisionLine) return trimSentence(keyDecisionLine.replace(/^[-*]\s+/, ""));

  const naturalDecision = content.match(/\b(?:we decided|decided to|choose|chose|approved)\b[^.\n]*/i)?.[0];
  if (naturalDecision) return trimSentence(naturalDecision);

  return doc.meetingTopic ?? doc.location ?? "Untitled decision";
}

function extractDecisionSummary(doc) {
  const content = (doc.content ?? "").replace(/\s+/g, " ").trim();
  if (!content) return "No source summary available yet.";
  return content.length > 180 ? `${content.slice(0, 177)}...` : content;
}

function extractBlockerReference(doc, components) {
  const explicitBlocker = (doc.content ?? "").match(/blocker:\s*([^\n]+)/i)?.[1];
  if (explicitBlocker) return trimSentence(explicitBlocker);

  const componentBlocker = components.find((component) =>
    [component.name, component.value].filter(Boolean).join(" ").toLowerCase().includes("blocker"),
  );
  if (!componentBlocker) return null;
  return trimSentence(componentBlocker.value || componentBlocker.name);
}

function trimSentence(value) {
  return value.replace(/\s+/g, " ").trim().replace(/[.]+$/, "");
}

function uniqueValues(values) {
  return Array.from(new Set(values));
}

function normalizeValue(value) {
  return typeof value === "string" && value.trim() ? value.trim().toLowerCase() : null;
}

function buildMockComponentSources(componentId) {
  for (const model of Object.values(modelFixtures)) {
    const component = (model.components ?? []).find((item) => item.id === componentId);
    if (component) {
      return normalizeComponentSourceRefs(component.sourceDocuments ?? component.source_documents ?? []);
    }
  }
  return [];
}

function buildMockSourceReviewItems(documentId) {
  return normalizeReviewItems(mockReviewQueue).filter((item) =>
    (item.sourceDocuments ?? []).some((doc) => doc?.id === documentId),
  );
}

function buildMockLaunchGuardContext() {
  const details = Object.entries(modelFixtures).map(([modelId, model]) => ({
    id: modelId,
    name: model.name,
    components: model.components ?? [],
  }));
  const documents = normalizeSourceDocuments(mockSourceDocuments);
  const decisionDocuments = documents.filter(isDecisionLikeDocument);
  return {
    components: details.flatMap((detail) => normalizeLaunchGuardComponents(detail)),
    reviewItems: normalizeReviewItems(mockReviewQueue),
    decisions: buildDecisionRegisterItems(
      decisionDocuments,
      Object.fromEntries(decisionDocuments.map((doc) => [doc.id, buildMockSourceComponentRefs(doc.id)])),
    ),
    evalSummary: normalizeEvalSummary(mockEvalSummary),
  };
}

function emptyLaunchGuardContext() {
  return {
    components: [],
    reviewItems: [],
    decisions: [],
    evalSummary: null,
  };
}

function applySourceSearchFilter(items, search) {
  const q = search.trim().toLowerCase();
  if (!q) return items;
  return items.filter((item) => {
    const haystack = [
      item.author,
      item.content,
      item.location,
      item.externalId,
      item.connectorType,
    ]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();
    return haystack.includes(q);
  });
}

function formatConnectorDate(value, { fallback = "Never" } = {}) {
  if (!value) return fallback;
  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}

function extractConnectorCount(config) {
  if (!config || typeof config !== "object") return 0;
  return (
    config.document_count ??
    config.items_synced ??
    config.item_count ??
    0
  );
}

// ── Graph Slice ──────────────────────────────────────────────────────────────

export function useGraphSlice(filters = {}) {
  return useQuery({
    queryKey: ["graph-slice", filters],
    queryFn: async () => {
      const body = {};
      if (filters.modelIds?.length) body.model_ids = filters.modelIds;
      if (filters.sourceTypes?.length) body.source_types = filters.sourceTypes;
      if (filters.statuses?.length) body.statuses = filters.statuses;
      if (filters.factTypes?.length) body.fact_types = filters.factTypes;
      if (filters.confidenceMin != null) body.confidence_min = filters.confidenceMin;
      if (filters.temporal) body.temporal = filters.temporal;
      if (filters.includeStale) body.include_stale = true;
      if (filters.includeProposedEdges !== undefined) body.include_proposed_edges = filters.includeProposedEdges;
      if (filters.maxHops != null) body.max_hops = filters.maxHops;
      return api.post("/graph/slice", body);
    },
    enabled: Object.keys(filters).length > 0,
  });
}

// ── Component Detail ─────────────────────────────────────────────────────────

export function useComponentDetail(componentId) {
  return useQuery({
    queryKey: ["component-detail", componentId],
    queryFn: () => api.get(`/components/${componentId}`),
    enabled: !!componentId,
  });
}

// ── Relationship Detail ──────────────────────────────────────────────────────

export function useRelationshipDetail(relationshipId) {
  return useQuery({
    queryKey: ["relationship-detail", relationshipId],
    queryFn: () => api.get(`/relationships/${relationshipId}`),
    enabled: !!relationshipId,
  });
}

// ── Source Diff ──────────────────────────────────────────────────────────────

export function useSourceDiff(sourceId) {
  return useQuery({
    queryKey: ["source-diff", sourceId],
    queryFn: () => api.get(`/source-documents/${sourceId}/diff`),
    enabled: !!sourceId,
  });
}

// ── Work Lens ────────────────────────────────────────────────────────────────

export function useWorkLens(workspaceId = null) {
  return useQuery({
    queryKey: ["work-lens", workspaceId],
    queryFn: async () => {
      const params = workspaceId ? `?workspace_id=${workspaceId}` : "";
      return api.get(`/work-lens${params}`);
    },
  });
}
