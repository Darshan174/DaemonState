import { createContext, useContext, useState, useCallback, useEffect } from "react";

const LS_KEY = "ce:selectedWorkspaceId";

const WorkspaceContext = createContext(null);

export function WorkspaceProvider({ children }) {
  const [selectedId, setSelectedIdRaw] = useState(
    () => localStorage.getItem(LS_KEY) || null,
  );

  const setSelectedId = useCallback((id) => {
    setSelectedIdRaw(id);
    if (id) {
      localStorage.setItem(LS_KEY, id);
    } else {
      localStorage.removeItem(LS_KEY);
    }
  }, []);

  return (
    <WorkspaceContext.Provider value={{ selectedId, setSelectedId }}>
      {children}
    </WorkspaceContext.Provider>
  );
}

/**
 * Returns { selectedId, setSelectedId }.
 *
 * selectedId is the workspace UUID string persisted in localStorage.
 * setSelectedId updates both React state and localStorage.
 */
export function useWorkspaceSelection() {
  const ctx = useContext(WorkspaceContext);
  if (!ctx) throw new Error("useWorkspaceSelection must be inside WorkspaceProvider");
  return ctx;
}

/**
 * Given a workspaces array, resolve which ID should be active:
 * - If selectedId exists in the list, use it.
 * - Otherwise auto-select only when there is exactly one real project.
 * - Never silently enter a demo or sandbox workspace.
 * - When multiple workspaces exist and no persisted selection is present,
 *   require an explicit user choice instead of silently picking one.
 * Returns null if no workspaces.
 */
export function resolveWorkspaceId(workspaces, selectedId) {
  if (!workspaces || workspaces.length === 0) return null;
  if (selectedId && workspaces.some((w) => w.id === selectedId)) return selectedId;
  const projects = workspaces.filter((workspace) =>
    !["demo", "sandbox"].includes(workspace.kind),
  );
  if (projects.length === 1) return projects[0].id;
  return null;
}
