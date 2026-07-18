import { useMemo } from "react";
import { AlertCircle, Beaker, FolderGit2, Settings2 } from "lucide-react";
import { Link } from "react-router-dom";
import ProjectWorkspaceForm from "./ProjectWorkspaceForm";

function workspaceSubtitle(workspace) {
  if (workspace.repo_path) return workspace.repo_path;
  if (workspace.kind === "demo") return "Sample data — not your project";
  if (workspace.kind === "sandbox") return "Unscoped sandbox";
  return "No repository connected";
}

export default function WorkspaceTopicGate({
  workspaces = [],
  selectedId = null,
  onSelect,
}) {
  const { projects, samples } = useMemo(() => ({
    projects: workspaces.filter((workspace) => !["demo", "sandbox"].includes(workspace.kind)),
    samples: workspaces.filter((workspace) => ["demo", "sandbox"].includes(workspace.kind)),
  }), [workspaces]);
  const unresolvedSelection = selectedId && !workspaces.some((workspace) => workspace.id === selectedId);

  return (
    <div className="flex min-h-[560px] items-center justify-center bg-slate-50 p-4 dark:bg-transparent sm:p-6">
      <div className="w-full max-w-4xl rounded-2xl border border-slate-200 bg-white p-5 shadow-sm dark:border-neutral-800 dark:bg-black sm:p-7">
        <div className="mb-6 flex items-start justify-between gap-4">
          <div>
            <p className="mb-2 text-[10px] font-bold uppercase tracking-[0.18em] text-slate-400">Project scope</p>
            <h1 className="text-2xl font-bold tracking-tight text-slate-950 dark:text-white">
              {projects.length ? "Choose a project" : "Connect your first real project"}
            </h1>
            <p className="mt-1.5 max-w-2xl text-sm leading-6 text-slate-500 dark:text-neutral-400">
              A workspace should map to one real project. That boundary keeps goals, sessions, evidence, and generated context from bleeding into each other.
            </p>
          </div>
          <Link
            to="/app/workspaces"
            className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-slate-200 px-3 py-2 text-xs font-bold text-slate-600 hover:bg-slate-50 dark:border-neutral-700 dark:text-neutral-300 dark:hover:bg-neutral-900"
          >
            <Settings2 className="h-3.5 w-3.5" /> Manage
          </Link>
        </div>

        {unresolvedSelection ? (
          <div className="mb-5 flex items-start gap-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2.5 text-amber-900 dark:border-amber-900/60 dark:bg-amber-950/40 dark:text-amber-200">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
            <p className="text-xs font-semibold leading-5">
              The saved workspace is archived or missing. Choose an active project to continue.
            </p>
          </div>
        ) : null}

        {projects.length ? (
          <section className="mb-6">
            <h2 className="mb-3 text-xs font-bold uppercase tracking-widest text-slate-400">Your projects</h2>
            <div className="grid gap-2 sm:grid-cols-2">
              {projects.map((workspace) => (
                <button
                  key={workspace.id}
                  type="button"
                  onClick={() => onSelect(workspace.id)}
                  className="flex min-h-16 items-center gap-3 rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-left transition hover:border-slate-400 hover:bg-slate-50 dark:border-neutral-800 dark:bg-black dark:hover:border-neutral-600 dark:hover:bg-neutral-950"
                >
                  <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-slate-100 text-slate-600 dark:bg-neutral-900 dark:text-neutral-300">
                    <FolderGit2 className="h-4 w-4" />
                  </div>
                  <div className="min-w-0">
                    <p className="truncate text-sm font-bold text-slate-900 dark:text-white">{workspace.name}</p>
                    <p className="mt-0.5 truncate text-xs font-medium text-slate-400">{workspaceSubtitle(workspace)}</p>
                  </div>
                </button>
              ))}
            </div>
          </section>
        ) : null}

        <ProjectWorkspaceForm onCreated={(workspace) => onSelect(workspace.id)} />

        {samples.length ? (
          <section className="mt-6 border-t border-slate-200 pt-5 dark:border-neutral-800">
            <div className="mb-3 flex items-center gap-2">
              <Beaker className="h-4 w-4 text-slate-400" />
              <div>
                <h2 className="text-xs font-bold uppercase tracking-widest text-slate-400">Samples</h2>
                <p className="mt-0.5 text-[11px] text-slate-400">Useful for a tour, never treated as your real project.</p>
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              {samples.map((workspace) => (
                <button
                  key={workspace.id}
                  type="button"
                  onClick={() => onSelect(workspace.id)}
                  className="rounded-lg border border-dashed border-slate-300 px-3 py-2 text-left hover:bg-slate-50 dark:border-neutral-700 dark:hover:bg-neutral-950"
                >
                  <span className="block text-xs font-bold text-slate-700 dark:text-neutral-300">{workspace.name}</span>
                  <span className="block text-[10px] font-semibold uppercase tracking-wide text-slate-400">Sample workspace</span>
                </button>
              ))}
            </div>
          </section>
        ) : null}
      </div>
    </div>
  );
}
