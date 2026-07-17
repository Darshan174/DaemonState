import { useWorkspaces } from "../api/hooks";
import { resolveWorkspaceId, useWorkspaceSelection } from "../context/WorkspaceContext";

export function useProductWorkspace() {
  const selection = useWorkspaceSelection();
  const workspacesQuery = useWorkspaces();
  const workspaces = workspacesQuery.data || [];
  const activeWorkspaceId = resolveWorkspaceId(workspaces, selection.selectedId);
  const activeWorkspace = workspaces.find((workspace) => workspace.id === activeWorkspaceId) || null;
  return {
    ...selection,
    workspacesQuery,
    workspaces,
    activeWorkspaceId,
    activeWorkspace,
  };
}
