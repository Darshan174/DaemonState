import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";

function digestPath(workspaceId) {
  const params = new URLSearchParams();
  if (workspaceId) params.set("workspace_id", workspaceId);
  const query = params.toString();
  return `/context/digest${query ? `?${query}` : ""}`;
}

export function useContextDigest(workspaceId, { poll = false } = {}) {
  return useQuery({
    queryKey: ["context-digest", workspaceId],
    queryFn: () => api.get(digestPath(workspaceId)),
    enabled: Boolean(workspaceId),
    refetchInterval: poll ? 4000 : false,
    refetchIntervalInBackground: false,
    retry: 1,
  });
}

export function useLinkedAISessionRefresh(workspaceId, { enabled = true } = {}) {
  const queryClient = useQueryClient();
  return useQuery({
    queryKey: ["linked-ai-session-refresh", workspaceId],
    queryFn: async () => {
      const result = await api.post("/connectors/ai-session/refresh-linked", {
        workspace_id: workspaceId,
      });
      if (Number(result?.changed || 0) > 0 || Number(result?.metadata_updated || 0) > 0) {
        await queryClient.invalidateQueries({ queryKey: ["context-digest", workspaceId] });
      }
      if (Number(result?.checkpoints_created || 0) > 0) {
        await queryClient.invalidateQueries({ queryKey: ["checkpoints", workspaceId] });
      }
      return result;
    },
    enabled: Boolean(workspaceId) && enabled,
    refetchInterval: 5000,
    refetchIntervalInBackground: false,
    retry: false,
  });
}

export function useClearNowSession(workspaceId) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => api.delete(`/session-library/selection?workspace_id=${encodeURIComponent(workspaceId)}`),
    onSuccess: (result) => {
      if (result?.library) {
        queryClient.setQueryData(["session-library", workspaceId], result.library);
      }
      queryClient.invalidateQueries({ queryKey: ["session-library", workspaceId] });
      queryClient.invalidateQueries({ queryKey: ["context-digest", workspaceId] });
      queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
}

export function useSetCurrentGoal(workspaceId) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (goal) => api.put(`/workspaces/${workspaceId}/current-goal`, goal),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["context-digest", workspaceId] }),
  });
}

export function useClearCurrentGoal(workspaceId) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => api.delete(`/workspaces/${workspaceId}/current-goal`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["context-digest", workspaceId] }),
  });
}

function runTimelinePath(workspaceId, focusComponentId) {
  const params = new URLSearchParams({
    workspace_id: workspaceId,
    focus_component_id: focusComponentId,
  });
  return `/context/run-timeline?${params}`;
}

export function useRunTimeline(workspaceId, focusComponentId) {
  return useQuery({
    queryKey: ["context-run-timeline", workspaceId, focusComponentId],
    queryFn: () => api.get(runTimelinePath(workspaceId, focusComponentId)),
    enabled: Boolean(workspaceId && focusComponentId),
    retry: 1,
  });
}

function runOutcomesPath(workspaceId) {
  const params = new URLSearchParams();
  if (workspaceId) params.set("workspace_id", workspaceId);
  return `/context/run-outcomes?${params}`;
}

export function useRunOutcomes(workspaceId) {
  return useQuery({
    queryKey: ["context-run-outcomes", workspaceId],
    queryFn: () => api.get(runOutcomesPath(workspaceId)),
    enabled: Boolean(workspaceId),
    retry: 1,
  });
}

function openLoopsPath(workspaceId) {
  const params = new URLSearchParams();
  if (workspaceId) params.set("workspace_id", workspaceId);
  return `/context/open-loops?${params}`;
}

export function useOpenLoops(workspaceId, { enabled = true } = {}) {
  return useQuery({
    queryKey: ["context-open-loops", workspaceId],
    queryFn: () => api.get(openLoopsPath(workspaceId)),
    enabled: enabled && Boolean(workspaceId),
    retry: 1,
  });
}

export function useUpdateOpenLoop(workspaceId) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ loopId, action, reason, assignee = undefined }) => api.patch(
      `/context/open-loops/${loopId}`,
      {
        workspace_id: workspaceId,
        action,
        reason,
        ...(assignee ? { assignee } : {}),
      },
    ),
    onSuccess: () => Promise.all([
      queryClient.invalidateQueries({ queryKey: ["context-digest", workspaceId] }),
      queryClient.invalidateQueries({ queryKey: ["context-open-loops", workspaceId] }),
      queryClient.invalidateQueries({ queryKey: ["context-run-timeline", workspaceId] }),
    ]),
  });
}

function playbooksPath(workspaceId) {
  const params = new URLSearchParams();
  if (workspaceId) params.set("workspace_id", workspaceId);
  return `/context/playbooks?${params}`;
}

export function usePlaybooks(workspaceId, { enabled = true } = {}) {
  return useQuery({
    queryKey: ["context-playbooks", workspaceId],
    queryFn: () => api.get(playbooksPath(workspaceId)),
    enabled: enabled && Boolean(workspaceId),
    retry: 1,
  });
}

export function useUpdatePlaybook(workspaceId) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ playbookId, action, reason }) => api.patch(
      `/context/playbooks/${playbookId}`,
      { workspace_id: workspaceId, action, reason },
    ),
    onSuccess: () => Promise.all([
      queryClient.invalidateQueries({ queryKey: ["context-playbooks", workspaceId] }),
      queryClient.invalidateQueries({ queryKey: ["context-digest", workspaceId] }),
      queryClient.invalidateQueries({ queryKey: ["context-run-timeline", workspaceId] }),
    ]),
  });
}

export function useBuildContext(workspaceId) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ mode = "incremental" } = {}) => {
      const saved = getAiSettings();
      const body = { limit: 100, workspace_id: workspaceId, mode };
      if (saved.api_key) body.api_key = saved.api_key;
      if (saved.model) body.model = saved.model;
      return api.post("/graph/build", body);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["context-digest", workspaceId] });
      queryClient.invalidateQueries({ queryKey: ["knowledge-graph"] });
    },
  });
}

export function useIndexProject(workspaceId) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ repo_path }) => api.post("/repo/index", {
      workspace_id: workspaceId,
      repo_path,
    }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["context-digest", workspaceId] });
      queryClient.invalidateQueries({ queryKey: ["knowledge-graph"] });
      queryClient.invalidateQueries({ queryKey: ["workspaces"] });
    },
  });
}

export function usePrepareContext() {
  return useMutation({
    mutationFn: async (payload) => {
      const result = await api.post("/context/prepare", payload);
      validateContextPackResponse(result);
      return result;
    },
  });
}

export function validateContextPackResponse(result) {
  const manifest = result?.manifest;
  if (
    !result
    || result.schema_version !== "context_pack.v2"
    || manifest?.schema_version !== "context_pack.v2"
    || !result.context_pack_id
    || typeof result.markdown !== "string"
    || !Array.isArray(result.selected_context)
    || !Array.isArray(result.excluded_context)
    || !Array.isArray(manifest.selected_context)
    || !Array.isArray(manifest.excluded_context)
  ) {
    throw new Error("The compiler returned an invalid context_pack.v2 response.");
  }
  if (
    JSON.stringify(result.selected_context) !== JSON.stringify(manifest.selected_context)
    || JSON.stringify(result.excluded_context) !== JSON.stringify(manifest.excluded_context)
  ) {
    throw new Error("The compiler returned inconsistent context-pack audit data.");
  }
}

function getAiSettings() {
  try {
    return JSON.parse(localStorage.getItem("ce_ai_settings") || "{}");
  } catch {
    return {};
  }
}
