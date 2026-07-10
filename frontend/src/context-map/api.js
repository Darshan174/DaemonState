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

export function useBuildContext(workspaceId) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: () => {
      const saved = getAiSettings();
      const body = { limit: 100, workspace_id: workspaceId };
      if (saved.api_key) body.api_key = saved.api_key;
      if (saved.model) body.model = saved.model;
      return api.post("/graph/build", body);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["context-digest", workspaceId] });
      queryClient.invalidateQueries({ queryKey: ["knowledge-graph"] });
      queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
}

export function usePrepareContext() {
  return useMutation({
    mutationFn: (payload) => api.post("/context/prepare", payload),
  });
}

function getAiSettings() {
  try {
    return JSON.parse(localStorage.getItem("ce_ai_settings") || "{}");
  } catch {
    return {};
  }
}
