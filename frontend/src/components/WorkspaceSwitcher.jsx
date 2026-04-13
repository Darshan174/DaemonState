import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useNavigate, useLocation } from "react-router-dom";
import { useWorkspaces } from "../api/hooks";
import { useWorkspaceSelection, resolveWorkspaceId } from "../context/WorkspaceContext";

/**
 * Dropdown workspace switcher for the top bar.
 * Persists selection to localStorage and invalidates workspace-scoped queries on change.
 */
export default function WorkspaceSwitcher() {
  const { data: workspaces, isLoading, isError } = useWorkspaces();
  const { selectedId, setSelectedId } = useWorkspaceSelection();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const location = useLocation();

  // Reconcile: if stored selection is stale (deleted workspace), auto-correct.
  // With multiple workspaces we intentionally require an explicit selection.
  const resolved = resolveWorkspaceId(workspaces, selectedId);
  useEffect(() => {
    if (resolved && resolved !== selectedId) {
      setSelectedId(resolved);
    }
  }, [resolved, selectedId, setSelectedId]);

  if (isLoading || isError || !workspaces || workspaces.length === 0) return null;

  const handleChange = (e) => {
    const newId = e.target.value;
    setSelectedId(newId);
    // Invalidate all workspace-scoped queries so they refetch with the new workspace
    qc.invalidateQueries({ queryKey: ["dashboard"] });
    qc.invalidateQueries({ queryKey: ["models"] });
    qc.invalidateQueries({ queryKey: ["model"] });
    qc.invalidateQueries({ queryKey: ["model-relationships"] });
    // If on a model detail page, navigate away — that model belongs to the old workspace
    if (location.pathname.startsWith("/app/model/")) {
      navigate("/app/models");
    }
  };

  return (
    <div className="flex items-center gap-2">
      <label className="text-xs text-gray-400 hidden sm:inline">Workspace:</label>
      <select
        value={resolved || ""}
        onChange={handleChange}
        className="text-xs bg-gray-50 border border-gray-200 rounded-lg px-2 py-1.5 text-gray-700 focus:outline-none focus:ring-2 focus:ring-brand-500/40 max-w-[180px] truncate"
      >
        {!resolved && workspaces.length > 1 ? (
          <option value="" disabled>
            Select workspace
          </option>
        ) : null}
        {workspaces.map((w) => (
          <option key={w.id} value={w.id}>
            {w.name}
          </option>
        ))}
      </select>
    </div>
  );
}
