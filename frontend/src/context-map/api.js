import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";

function digestPath(workspaceId) {
  const params = new URLSearchParams();
  if (workspaceId) params.set("workspace_id", workspaceId);
  const query = params.toString();
  return `/context/digest${query ? `?${query}` : ""}`;
}

export function useContextDigest(workspaceId) {
  return useQuery({
    queryKey: ["context-digest", workspaceId],
    queryFn: () => api.get(digestPath(workspaceId)),
    enabled: Boolean(workspaceId),
    retry: 1,
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
