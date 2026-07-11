import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useNavigate, useLocation } from "react-router-dom";
import { useWorkspaces } from "../api/hooks";
import { useWorkspaceSelection, resolveWorkspaceId } from "../context/WorkspaceContext";

/**
 * Dropdown workspace switcher for the top bar.
 * Persists selection to localStorage and invalidates workspace-scoped queries on change.
 */
export default function WorkspaceSwitcher({ variant = "header" }) {
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
    qc.invalidateQueries({ queryKey: ["connectors"] });
    qc.invalidateQueries({ queryKey: ["timeline"] });
    qc.invalidateQueries({ queryKey: ["connector-processing-summary"] });
    qc.invalidateQueries({ queryKey: ["knowledge-graph"] });
    qc.invalidateQueries({ queryKey: ["graph-slice"] });
    // If on a model detail page, navigate away — that model belongs to the old workspace
    if (location.pathname.startsWith("/app/model/")) {
      navigate("/app/models");
    }
  };

  return (
    <div className={variant === "sidebar" ? "space-y-2" : "flex min-w-0 items-center gap-2"}>
      <label className={variant === "sidebar" ? "block px-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-[#8a8a80] dark:text-[#77776e]" : "hidden text-xs font-semibold text-slate-500 dark:text-neutral-500 xl:inline"}>
        Workspace
      </label>
      <select
        value={resolved || ""}
        onChange={handleChange}
        aria-label="Workspace"
        className={`${variant === "sidebar" ? "w-full" : "max-w-[150px] sm:max-w-[200px]"} truncate rounded-md border border-[#d9d9d0] bg-[#fbfbf6] px-3 py-2 text-xs font-semibold text-[#4f4f48] transition-colors focus:outline-none focus:ring-2 focus:ring-brand-500/40 dark:border-[#35352f] dark:bg-[#141411] dark:text-[#d0d0c7]`}
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
