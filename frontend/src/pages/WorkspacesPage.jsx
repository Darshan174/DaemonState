import { useEffect, useMemo, useRef, useState } from "react";
import { Archive, Beaker, Check, FolderGit2, Pencil, RotateCcw, Trash2, X } from "lucide-react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useAllWorkspaces, useDeleteWorkspace, useUpdateWorkspace } from "../api/hooks";
import ProjectWorkspaceForm from "../components/ProjectWorkspaceForm";
import { useWorkspaceSelection } from "../context/WorkspaceContext";

function formatActivity(value) {
  if (!value) return "No activity yet";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Activity recorded";
  return `Active ${date.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })}`;
}

export default function WorkspacesPage() {
  const { data: workspaces = [], isLoading, isError, error } = useAllWorkspaces();
  const updateWorkspace = useUpdateWorkspace();
  const deleteWorkspace = useDeleteWorkspace();
  const { selectedId, setSelectedId } = useWorkspaceSelection();
  const [searchParams] = useSearchParams();
  const [actionError, setActionError] = useState(null);
  const addRef = useRef(null);
  const navigate = useNavigate();
  const groups = useMemo(() => ({
    projects: workspaces.filter((workspace) => workspace.status === "active" && !["demo", "sandbox"].includes(workspace.kind)),
    samples: workspaces.filter((workspace) => workspace.status === "active" && ["demo", "sandbox"].includes(workspace.kind)),
    archived: workspaces.filter((workspace) => workspace.status === "archived"),
  }), [workspaces]);

  useEffect(() => {
    if (searchParams.get("new") === "1") addRef.current?.scrollIntoView({ block: "start" });
  }, [searchParams]);

  async function update(id, body) {
    setActionError(null);
    try {
      const changed = await updateWorkspace.mutateAsync({ id, ...body });
      if (body.status === "archived" && selectedId === id) setSelectedId(null);
      return changed;
    } catch (mutationError) {
      setActionError(mutationError?.message || "The workspace could not be updated.");
      return null;
    }
  }

  async function remove(workspace) {
    setActionError(null);
    try {
      await deleteWorkspace.mutateAsync({ id: workspace.id, confirmName: workspace.name });
      if (selectedId === workspace.id) setSelectedId(null);
      return true;
    } catch (mutationError) {
      setActionError(mutationError?.message || "The workspace could not be deleted.");
      return false;
    }
  }

  return (
    <div className="relative mx-auto max-w-6xl">
      <div className="mb-7 flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
        <div>
          <p className="mb-2 text-[10px] font-bold uppercase tracking-[0.18em] text-slate-400">Project boundaries</p>
          <h1 className="text-2xl font-bold tracking-tight text-slate-950 dark:text-white">Workspaces</h1>
          <p className="mt-1.5 max-w-2xl text-sm leading-6 text-slate-500 dark:text-neutral-400">
            Keep one workspace per real project. Samples are isolated, archived projects disappear from daily work, and permanent deletion requires explicit confirmation.
          </p>
        </div>
        <button type="button" onClick={() => addRef.current?.scrollIntoView({ behavior: "smooth", block: "start" })} className="rounded-lg bg-slate-950 px-4 py-2.5 text-sm font-bold text-white hover:bg-slate-800 dark:bg-[#d9ff68] dark:text-[#171713]">
          Add project
        </button>
      </div>

      {actionError ? <p role="alert" className="mb-5 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs font-semibold text-red-700 dark:border-red-900/60 dark:bg-red-950/30 dark:text-red-300">{actionError}</p> : null}
      {isError ? <p role="alert" className="mb-5 text-sm font-semibold text-red-600">{error?.message || "Workspaces could not be loaded."}</p> : null}
      {isLoading ? <div className="h-40 animate-pulse rounded-xl bg-slate-100 dark:bg-neutral-900" /> : null}

      {!isLoading ? (
        <div className="space-y-8">
          <WorkspaceSection title="Projects" description="Real repositories and their project evidence." empty="No real projects connected yet." workspaces={groups.projects} selectedId={selectedId} onUpdate={update} />
          {groups.samples.length ? <WorkspaceSection title="Samples" description="Tour data, kept visibly separate from real work." workspaces={groups.samples} selectedId={selectedId} onUpdate={update} sample /> : null}
          {groups.archived.length ? <WorkspaceSection title="Archived" description="Hidden from the product loop. Restore or permanently delete." workspaces={groups.archived} selectedId={selectedId} onUpdate={update} onDelete={remove} archived /> : null}
        </div>
      ) : null}

      <section ref={addRef} className="mt-10 scroll-mt-8 border-t border-slate-200 pt-8 dark:border-neutral-800">
        <div className="mb-4">
          <h2 className="text-lg font-bold text-slate-950 dark:text-white">Add a real project</h2>
          <p className="mt-1 text-sm text-slate-500 dark:text-neutral-400">The repository is indexed before the workspace is kept, so a bad path does not leave junk behind.</p>
        </div>
        <ProjectWorkspaceForm
          compact
          onCreated={(workspace) => {
            setSelectedId(workspace.id);
            navigate("/app");
          }}
        />
      </section>
    </div>
  );
}

function WorkspaceSection({ title, description, empty, workspaces = [], selectedId, onUpdate, onDelete, sample = false, archived = false }) {
  return (
    <section>
      <div className="mb-3 flex items-end justify-between gap-4">
        <div>
          <h2 className="text-sm font-bold text-slate-950 dark:text-white">{title} <span className="ml-1 text-xs text-slate-400">{workspaces.length}</span></h2>
          <p className="mt-0.5 text-xs text-slate-400">{description}</p>
        </div>
      </div>
      {workspaces.length ? (
        <div className="grid gap-3 lg:grid-cols-2">
          {workspaces.map((workspace) => (
            <WorkspaceCard key={workspace.id} workspace={workspace} selected={workspace.id === selectedId} onUpdate={onUpdate} onDelete={onDelete} sample={sample} archived={archived} />
          ))}
        </div>
      ) : (
        <div className="rounded-xl border border-dashed border-slate-300 px-4 py-6 text-sm text-slate-400 dark:border-neutral-700">{empty}</div>
      )}
    </section>
  );
}

function WorkspaceCard({ workspace, selected, onUpdate, onDelete, sample, archived }) {
  const [renaming, setRenaming] = useState(false);
  const [name, setName] = useState(workspace.name);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [confirmation, setConfirmation] = useState("");

  async function saveName() {
    const normalized = name.trim();
    if (!normalized || normalized === workspace.name) {
      setName(workspace.name);
      setRenaming(false);
      return;
    }
    const changed = await onUpdate(workspace.id, { name: normalized });
    if (changed) setRenaming(false);
  }

  return (
    <article className={`rounded-xl border bg-white p-4 dark:bg-black ${selected ? "border-slate-500 ring-2 ring-slate-200 dark:border-[#d9ff68] dark:ring-[#d9ff68]/10" : "border-slate-200 dark:border-neutral-800"}`}>
      <div className="flex items-start gap-3">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-slate-100 text-slate-600 dark:bg-neutral-900 dark:text-neutral-300">
          {sample ? <Beaker className="h-4 w-4" /> : <FolderGit2 className="h-4 w-4" />}
        </div>
        <div className="min-w-0 flex-1">
          {renaming ? (
            <div className="flex gap-1.5">
              <input aria-label={`Rename ${workspace.name}`} value={name} onChange={(event) => setName(event.target.value)} className="min-w-0 flex-1 rounded-md border border-slate-300 px-2 py-1 text-sm font-bold outline-none focus:ring-2 focus:ring-slate-200 dark:border-neutral-700 dark:bg-neutral-950" />
              <button type="button" aria-label="Save name" onClick={saveName} className="rounded-md p-1.5 hover:bg-slate-100 dark:hover:bg-neutral-900"><Check className="h-4 w-4" /></button>
              <button type="button" aria-label="Cancel rename" onClick={() => { setName(workspace.name); setRenaming(false); }} className="rounded-md p-1.5 hover:bg-slate-100 dark:hover:bg-neutral-900"><X className="h-4 w-4" /></button>
            </div>
          ) : (
            <div className="flex min-w-0 items-center gap-2">
              <h3 className="truncate text-sm font-bold text-slate-950 dark:text-white">{workspace.name}</h3>
              {selected ? <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[9px] font-bold uppercase tracking-wide text-slate-500 dark:bg-neutral-900 dark:text-[#d9ff68]">Current</span> : null}
              {sample ? <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[9px] font-bold uppercase tracking-wide text-amber-700 dark:bg-amber-950/30 dark:text-amber-300">Sample</span> : null}
            </div>
          )}
          <p className="mt-1 truncate font-mono text-[11px] text-slate-400">{workspace.repo_path || (sample ? "Sample evidence" : "No repository connected")}</p>
        </div>
      </div>

      <div className="mt-4 grid grid-cols-4 gap-2 border-y border-slate-100 py-3 dark:border-neutral-900">
        <Metric value={workspace.source_count} label="Sources" />
        <Metric value={workspace.component_count} label="Facts" />
        <Metric value={workspace.run_count} label="Runs" />
        <Metric value={workspace.connector_count} label="Inputs" />
      </div>
      <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
        <span className="text-[11px] font-medium text-slate-400">{formatActivity(workspace.last_activity_at)}</span>
        <div className="flex gap-1">
          {!archived ? (
            <>
              <button type="button" onClick={() => setRenaming(true)} className="inline-flex items-center gap-1.5 rounded-md px-2 py-1.5 text-[11px] font-bold text-slate-500 hover:bg-slate-100 dark:hover:bg-neutral-900"><Pencil className="h-3 w-3" /> Rename</button>
              <button type="button" onClick={() => onUpdate(workspace.id, { status: "archived" })} className="inline-flex items-center gap-1.5 rounded-md px-2 py-1.5 text-[11px] font-bold text-slate-500 hover:bg-slate-100 dark:hover:bg-neutral-900"><Archive className="h-3 w-3" /> Archive</button>
            </>
          ) : (
            <>
              <button type="button" onClick={() => onUpdate(workspace.id, { status: "active" })} className="inline-flex items-center gap-1.5 rounded-md px-2 py-1.5 text-[11px] font-bold text-slate-600 hover:bg-slate-100 dark:text-neutral-300 dark:hover:bg-neutral-900"><RotateCcw className="h-3 w-3" /> Restore</button>
              <button type="button" onClick={() => setConfirmingDelete(true)} className="inline-flex items-center gap-1.5 rounded-md px-2 py-1.5 text-[11px] font-bold text-red-600 hover:bg-red-50 dark:text-red-400 dark:hover:bg-red-950/30"><Trash2 className="h-3 w-3" /> Delete</button>
            </>
          )}
        </div>
      </div>

      {confirmingDelete ? (
        <div className="mt-4 rounded-lg border border-red-200 bg-red-50 p-3 dark:border-red-900/60 dark:bg-red-950/20">
          <p className="text-xs font-bold text-red-800 dark:text-red-300">Delete {workspace.name} permanently?</p>
          <p className="mt-1 text-[11px] leading-5 text-red-700 dark:text-red-400">This removes {workspace.source_count || 0} sources, {workspace.component_count || 0} facts, and {workspace.run_count || 0} runs. Type the exact workspace name.</p>
          <input aria-label={`Type ${workspace.name} to confirm deletion`} value={confirmation} onChange={(event) => setConfirmation(event.target.value)} className="mt-2 w-full rounded-md border border-red-200 bg-white px-2 py-1.5 text-xs font-semibold outline-none focus:ring-2 focus:ring-red-200 dark:border-red-900 dark:bg-black" />
          <div className="mt-2 flex justify-end gap-2">
            <button type="button" onClick={() => { setConfirmingDelete(false); setConfirmation(""); }} className="rounded-md px-2 py-1.5 text-xs font-bold text-slate-500">Cancel</button>
            <button type="button" disabled={confirmation !== workspace.name} onClick={async () => { if (await onDelete(workspace)) setConfirmingDelete(false); }} className="rounded-md bg-red-600 px-2.5 py-1.5 text-xs font-bold text-white disabled:cursor-not-allowed disabled:opacity-40">Delete permanently</button>
          </div>
        </div>
      ) : null}
    </article>
  );
}

function Metric({ value = 0, label }) {
  return <div><p className="text-sm font-bold text-slate-800 dark:text-neutral-200">{value || 0}</p><p className="text-[9px] font-bold uppercase tracking-wide text-slate-400">{label}</p></div>;
}
