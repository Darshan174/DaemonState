import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Beaker, Check, ChevronDown, FolderGit2, Plus, Settings2 } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { useWorkspaces } from "../api/hooks";
import { resolveWorkspaceId, useWorkspaceSelection } from "../context/WorkspaceContext";

function repoLabel(workspace) {
  if (!workspace.repo_path) return workspace.kind === "demo" ? "Sample data" : "No repo connected";
  return workspace.repo_path.split(/[\\/]/).filter(Boolean).at(-1) || workspace.repo_path;
}

export default function WorkspaceSwitcher({ variant = "header" }) {
  const { data: workspaces = [], isLoading, isError } = useWorkspaces();
  const { selectedId, setSelectedId } = useWorkspaceSelection();
  const [open, setOpen] = useState(false);
  const rootRef = useRef(null);
  const qc = useQueryClient();
  const navigate = useNavigate();
  const resolved = resolveWorkspaceId(workspaces, selectedId);
  const selected = workspaces.find((workspace) => workspace.id === resolved) || null;
  const projects = workspaces.filter((workspace) => !["demo", "sandbox"].includes(workspace.kind));
  const samples = workspaces.filter((workspace) => ["demo", "sandbox"].includes(workspace.kind));

  useEffect(() => {
    if (resolved && resolved !== selectedId) setSelectedId(resolved);
  }, [resolved, selectedId, setSelectedId]);

  useEffect(() => {
    if (!open) return undefined;
    const closeOutside = (event) => {
      if (!rootRef.current?.contains(event.target)) setOpen(false);
    };
    const closeOnEscape = (event) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", closeOutside);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("mousedown", closeOutside);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [open]);

  function selectWorkspace(workspaceId) {
    setSelectedId(workspaceId);
    setOpen(false);
    qc.invalidateQueries();
    navigate("/app");
  }

  function go(path) {
    setOpen(false);
    navigate(path);
  }

  if (isLoading) {
    return <div className="h-11 w-full animate-pulse rounded-xl bg-[#e8e8e0] dark:bg-[#111111]" />;
  }

  return (
    <div ref={rootRef} className={`relative min-w-0 ${variant === "sidebar" ? "space-y-2" : "flex items-center gap-2"}`}>
      <label className={variant === "sidebar" ? "block px-2 text-[9px] font-bold uppercase tracking-[0.18em] text-[#8a8a80] dark:text-[#77776e]" : "sr-only"}>
        Current project
      </label>
      <button
        type="button"
        aria-label="Choose workspace"
        aria-expanded={open}
        aria-haspopup="menu"
        onClick={() => setOpen((value) => !value)}
        className={`${variant === "sidebar" ? "w-full" : "max-w-[190px] sm:max-w-[240px]"} flex h-11 min-w-0 items-center gap-2.5 rounded-xl border border-[#d9d9d0] bg-[#fbfbf6]/90 px-3 text-left shadow-[0_1px_2px_rgba(23,23,19,0.03)] transition-all duration-200 hover:border-[#bdbdb4] hover:bg-white focus:outline-none focus:ring-2 focus:ring-[#9ebf35]/35 dark:border-[#292929] dark:bg-[#0b0b0b]/95 dark:shadow-none dark:hover:border-[#3b3b3b] dark:hover:bg-[#121212]`}
      >
        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-[#edede5] text-[#68685f] dark:bg-[#151515] dark:text-[#b8b8ae]">
          {selected?.kind === "demo" || selected?.kind === "sandbox" ? (
            <Beaker className="h-3.5 w-3.5" />
          ) : (
            <FolderGit2 className="h-3.5 w-3.5" />
          )}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-xs font-bold text-[#383832] dark:text-[#e1e1d8]">
            {selected?.name || (workspaces.length ? "Choose project" : "Add project")}
          </span>
          {variant === "sidebar" && selected ? (
            <span className="mt-0.5 block truncate text-[9px] text-[#8a8a80] dark:text-[#77776e]">{repoLabel(selected)}</span>
          ) : null}
        </span>
        <ChevronDown className={`h-3.5 w-3.5 shrink-0 text-[#8a8a80] transition-transform duration-200 ${open ? "rotate-180" : ""}`} />
      </button>

      {open ? (
        <div
          role="menu"
          className={`page-enter absolute z-50 w-[min(320px,calc(100vw-2rem))] overflow-hidden rounded-2xl border border-[#d9d9d0] bg-[#fbfbf6]/95 shadow-[0_18px_50px_rgba(23,23,19,0.16)] backdrop-blur-xl dark:border-[#292929] dark:bg-[#080808]/95 dark:shadow-[0_20px_60px_rgba(0,0,0,0.72)] ${variant === "sidebar" ? "bottom-[calc(100%+8px)] left-0" : "right-0 top-[calc(100%+8px)]"}`}
        >
          {isError ? (
            <p className="px-3 py-4 text-xs font-semibold text-red-600 dark:text-red-400">Workspaces could not be loaded.</p>
          ) : (
            <div className="max-h-72 overflow-y-auto p-2">
              <WorkspaceGroup label="Projects" workspaces={projects} selectedId={resolved} onSelect={selectWorkspace} />
              <WorkspaceGroup label="Samples" workspaces={samples} selectedId={resolved} onSelect={selectWorkspace} sample />
              {!workspaces.length ? (
                <p className="px-2 py-4 text-xs leading-5 text-[#77776e]">No projects yet. Connect a local repository to start with real evidence.</p>
              ) : null}
            </div>
          )}
          <div className="grid grid-cols-2 gap-1 border-t border-[#d9d9d0] bg-[#f5f5ee]/75 p-2 dark:border-[#202020] dark:bg-[#030303]/80">
            <button type="button" role="menuitem" onClick={() => go("/app/workspaces?new=1")} className="flex items-center gap-2 rounded-lg px-2.5 py-2 text-xs font-bold text-[#4f4f48] transition hover:bg-white dark:text-[#d0d0c7] dark:hover:bg-[#111111]">
              <Plus className="h-3.5 w-3.5" /> Add project
            </button>
            <button type="button" role="menuitem" onClick={() => go("/app/workspaces")} className="flex items-center gap-2 rounded-lg px-2.5 py-2 text-xs font-bold text-[#4f4f48] transition hover:bg-white dark:text-[#d0d0c7] dark:hover:bg-[#111111]">
              <Settings2 className="h-3.5 w-3.5" /> Manage
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function WorkspaceGroup({ label, workspaces, selectedId, onSelect, sample = false }) {
  if (!workspaces.length) return null;
  return (
    <section className="mb-2 last:mb-0">
      <p className="px-2 pb-1 pt-1 text-[9px] font-bold uppercase tracking-[0.16em] text-[#8a8a80]">{label}</p>
      {workspaces.map((workspace) => (
        <button
          key={workspace.id}
          type="button"
          role="menuitemradio"
          aria-checked={workspace.id === selectedId}
          onClick={() => onSelect(workspace.id)}
          className={`group flex w-full items-center gap-2.5 rounded-xl px-2.5 py-2.5 text-left transition ${workspace.id === selectedId ? "bg-[#e8e8e0] dark:bg-[#141414]" : "hover:bg-[#efefe8] dark:hover:bg-[#111111]"}`}
        >
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-white/70 text-[#68685f] shadow-sm dark:bg-[#0d0d0d] dark:text-[#a2a298] dark:shadow-none">
            {sample ? <Beaker className="h-3.5 w-3.5" /> : <FolderGit2 className="h-3.5 w-3.5" />}
          </span>
          <span className="min-w-0 flex-1">
            <span className="block truncate text-xs font-bold text-[#383832] dark:text-[#e1e1d8]">{workspace.name}</span>
            <span className="block truncate text-[10px] text-[#8a8a80] dark:text-[#77776e]">{repoLabel(workspace)}</span>
          </span>
          {workspace.id === selectedId ? <Check className="h-3.5 w-3.5 shrink-0 text-[#6f8427] dark:text-[#d9ff68]" /> : sample ? <span className="rounded bg-[#e8e8e0] px-1.5 py-0.5 text-[8px] font-bold uppercase tracking-wide text-[#77776e] dark:bg-[#181818]">sample</span> : null}
        </button>
      ))}
    </section>
  );
}
