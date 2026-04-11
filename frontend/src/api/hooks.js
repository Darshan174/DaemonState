/**
 * React Query hooks for Context Engine API.
 *
 * Each hook tries the real backend first. If the fetch fails (backend
 * down, network error), it falls back to mock fixtures so the UI stays
 * usable during frontend-only development.
 */

import { useInfiniteQuery, useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";
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
  notion: {
    type: "notion",
    name: "Notion",
    description: "Wikis, docs, and linked databases",
    color: "#111111",
    availability: "available",
    provider: "dlt",
    providerLabel: "dlt",
    providerNote: "Powered by a dlt-backed connector path so we can reuse the substrate but keep our own storage and extraction pipeline.",
  },
  zoom: {
    type: "zoom",
    name: "Zoom",
    description: "Meeting transcripts and recording metadata",
    color: "#0B5CFF",
    availability: "available",
    provider: "official_api",
    providerLabel: "Official API",
    providerNote: "Transcript-first Zoom ingestion keeps the connector focused on high-signal meeting context instead of media processing.",
  },
  github: {
    type: "github",
    name: "GitHub",
    description: "Issues, pull requests, reviews, and engineering discussion",
    color: "#24292F",
    availability: "available",
    provider: "official_api",
    providerLabel: "Official API",
    providerNote: "GitHub stays close to the official API because PRs, review comments, and issue links carry the engineering rationale startups actually need.",
  },
  gdrive: {
    type: "gdrive",
    name: "Google Drive",
    description: "Docs, Sheets, Slides, and folder content",
    color: "#0F9D58",
    availability: "coming_soon",
    provider: "unstructured",
    providerLabel: "Unstructured",
    providerNote: "Planned to use Unstructured for Drive ingestion and document extraction.",
  },
  gong: {
    type: "gong",
    name: "Gong",
    description: "Calls, transcripts, and customer conversations",
    color: "#7C3AED",
    availability: "coming_soon",
    provider: "official_api",
    providerLabel: "Official API",
    providerNote: "Likely to stay on the Gong API directly because transcript semantics matter more than generic ETL.",
  },
};

/**
 * Resolve the workspace ID to use for API calls.
 *
 * Priority:
 * 1. localStorage selection (set by workspace switcher)
 * 2. First workspace from the backend
 *
 * Returns null if no workspaces exist.
 */
async function getWorkspaceId() {
  const workspaces = await api.get("/workspaces");
  if (workspaces.length === 0) return null;

  const stored = localStorage.getItem(LS_KEY);
  if (stored && workspaces.some((w) => w.id === stored)) return stored;

  return workspaces[0].id;
}

// ── Workspaces ────────────────────────────────────────────────

export function useWorkspaces() {
  return useQuery({
    queryKey: ["workspaces"],
    queryFn: () => api.get("/workspaces"),
    retry: 1,
  });
}

export function useCreateWorkspace() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body) => api.post("/workspaces", body),
    onSuccess: (newWorkspace) => {
      // Auto-select the newly created workspace
      if (newWorkspace?.id) {
        localStorage.setItem(LS_KEY, newWorkspace.id);
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

export function useDashboard() {
  return useQuery({
    queryKey: ["dashboard"],
    queryFn: withFallback(async () => {
      const wsId = await getWorkspaceId();
      if (!wsId) throw new Error("no workspace");

      const [models, connectors, sources] = await Promise.all([
        api.get(`/models?workspace_id=${wsId}`),
        api.get(`/connectors?workspace_id=${wsId}`),
        api.get(`/connectors/source-documents?workspace_id=${wsId}&limit=1`),
      ]);

      // Fetch each model's detail to get actual component counts
      const details = await Promise.all(
        models.map((m) => api.get(`/models/${m.id}`)),
      );
      const relationshipsPerModel = await Promise.all(
        models.map((m) => api.get(`/models/${m.id}/relationships`)),
      );
      const totalComponents = details.reduce(
        (n, d) => n + (d.components?.length ?? 0),
        0,
      );
      const relationshipCount = new Set(
        relationshipsPerModel.flatMap((rels) => (rels ?? []).map((rel) => rel.id)),
      ).size;
      
      const sourceDocumentCount = sources?.total ?? 0;
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
      };
    }, MOCK_DASHBOARD),
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
        if (!wsId) return [];
        return api.get(`/connectors?workspace_id=${wsId}`);
      },
      mockConnectors,
      { fallbackStatuses: [404, 501] },
    ),
  });
  const refetch = async () => {
    const result = await query.refetch();
    return {
      ...result,
      data: normalizeConnectors(result.data),
      isMock: result.data === mockConnectors,
    };
  };
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
        const data = await api.get(`/source-documents?${params.toString()}`);
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
        const data = await api.get(`/source-documents/${documentId}?workspace_id=${wsId}`);
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
        const data = await api.get(`/source-documents/${documentId}/components?workspace_id=${wsId}`);
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
  const { status = "all", severity = "all", kind = "all" } = filters;
  const query = useQuery({
    queryKey: ["review-queue", status, severity, kind],
    queryFn: async () => {
      const wsId = await getWorkspaceId();
      if (!wsId) return { items: [], isMock: false };

      const params = new URLSearchParams({ workspace_id: wsId });
      if (status !== "all") params.set("status", status);
      if (severity !== "all") params.set("severity", severity);
      if (kind !== "all") params.set("kind", kind);

      try {
        const data = await api.get(`/review-items?${params.toString()}`);
        return { items: normalizeReviewItems(data), isMock: false };
      } catch (err) {
        if (err.status && ![404, 501].includes(err.status)) {
          throw err;
        }
        if (!MOCKS_ENABLED) throw err;
        return {
          items: filterReviewItems(normalizeReviewItems(mockReviewQueue), { status, severity, kind }),
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
        const data = await api.get(`/founder-brief?${params.toString()}`);
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
        return {
          timeline: {
            workspaceId: null,
            generatedAt: null,
            totalEvents: 0,
            hasMore: false,
            nextCursor: null,
            items: [],
          },
          isMock: false,
        };
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
        const data = await api.get(`/decisions?${params.toString()}`);
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
          `/decisions/${componentId}/history?workspace_id=${wsId}`,
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
          api.get(`/source-documents?workspace_id=${wsId}&processed=true&limit=100`),
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
                `/source-documents/${doc.id}/components?workspace_id=${wsId}`,
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
      temporalState: node.temporal_state,
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
 * Fully mock-backed for now — the backend query endpoint does not exist yet.
 * When the backend is ready, replace the mock with:
 *   api.post("/query", { question, workspace_id })
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
        return await api.post("/query", {
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
    onSuccess: () => qc.invalidateQueries({ queryKey: ["connectors"] }),
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
      const job = await api.post(`/source-documents/${documentId}/reprocess?workspace_id=${wsId}`, {});
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

export function useConnectNotion() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ token }) => {
      const wsId = await getWorkspaceId();
      return api.post("/connectors/notion/connect", { workspace_id: wsId, token });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["connectors"] });
      qc.invalidateQueries({ queryKey: ["connector-processing-summary"] });
      qc.invalidateQueries({ queryKey: ["source-documents"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
}

export function useConnectZoom() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ token }) => {
      const wsId = await getWorkspaceId();
      return api.post("/connectors/zoom/connect", { workspace_id: wsId, token });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["connectors"] });
      qc.invalidateQueries({ queryKey: ["connector-processing-summary"] });
      qc.invalidateQueries({ queryKey: ["source-documents"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
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

export function useSeedDemoData() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      // This endpoint triggers a backend task to seed the current workspace with demo data
      return api.post("/seed-demo", {});
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["workspaces"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      qc.invalidateQueries({ queryKey: ["connectors"] });
      qc.invalidateQueries({ queryKey: ["source-documents"] });
    },
  });
}

export function useUploadSourceFile() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (file) => {
      const wsId = await getWorkspaceId();
      const formData = new FormData();
      formData.append("file", file);
      formData.append("workspace_id", wsId);

      // We use a separate fetch call here because the standard api client 
      // is configured for JSON and not multipart/form-data
      const response = await fetch(`/api/source-documents/upload`, {
        method: "POST",
        body: formData,
      });

      if (!response.ok) {
        let detail;
        try {
          const body = await response.json();
          detail = body.detail ?? body;
        } catch {
          detail = response.statusText;
        }
        throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
      }

      return response.json();
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["source-documents"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      qc.invalidateQueries({ queryKey: ["connector-processing-summary"] });
    },
  });
}

function normalizeConnectors(data) {
  if (!Array.isArray(data)) return [];

  const isMockShape = data.every((item) => item && "lastSync" in item);
  if (isMockShape) {
    return data.map((item) => {
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
      };
    });
  }

  const recordsByType = new Map(
    data
      .filter((item) => item?.connector_type)
      .map((item) => [item.connector_type, item]),
  );

  return Object.values(CONNECTOR_CATALOG).map((catalogItem) => {
    const record = recordsByType.get(catalogItem.type);
    if (!record) {
      return {
        ...catalogItem,
        id: catalogItem.type,
        connectorId: null,
        status:
          catalogItem.availability === "available" ? "disconnected" : "coming_soon",
        isInstalled: false,
        lastSync: "Never",
        itemsSynced: 0,
        message:
          catalogItem.availability === "available"
            ? "Not connected yet."
            : "Planned after the Slack reference connector ships.",
      };
    }

    return {
      ...catalogItem,
      id: record.id,
      connectorId: record.id,
      status: record.status,
      isInstalled: record.status !== "disconnected",
      lastSync: formatConnectorDate(record.last_sync_at),
      itemsSynced: extractConnectorCount(record.config),
      message: record.config?.message ?? null,
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
      providerLabel: record.provider_label ?? catalogItem.providerLabel,
      providerNote: record.provider_note ?? catalogItem.providerNote,
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
      connectorType,
      externalId: item.externalId ?? item.external_id,
      author: item.author ?? "Unknown",
      content: item.content ?? "",
      preview: item.content ?? "",
      sourceUrl: item.sourceUrl ?? item.source_url ?? null,
      createdAtSource: item.createdAtSource ?? item.created_at_source ?? null,
      ingestedAt: item.ingestedAt ?? item.ingested_at ?? null,
      processedAt: item.processedAt ?? item.processed_at ?? null,
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
  if (!Array.isArray(data)) return [];
  return data.map((item) => ({
    connectorId: item.connector_id,
    connectorType: item.connector_type,
    status: item.status,
    totalDocuments: Number(item.total_documents ?? 0),
    processedDocuments: Number(item.processed_documents ?? 0),
    unprocessedDocuments: Number(item.unprocessed_documents ?? 0),
    lastSyncAt: formatConnectorDate(item.last_sync_at),
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
  if (!Array.isArray(data)) return [];
  return data.map((item) => ({
    id: item.id,
    status: item.status ?? "needs_review",
    severity: item.severity ?? "medium",
    kind: item.kind ?? "review_item",
    title: item.title ?? "Untitled review item",
    summary: item.summary ?? "",
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

  const items = Array.isArray(data.items)
    ? data.items.map((item, index) => normalizeTimelineItem(item, index))
    : [];

  return {
    workspaceId: data.workspaceId ?? data.workspace_id ?? null,
    generatedAt: data.generatedAt ?? data.generated_at ?? null,
    totalEvents: toNumber(data.totalEvents ?? data.total_events ?? items.length),
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
