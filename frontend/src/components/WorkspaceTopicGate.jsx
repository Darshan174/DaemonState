import { useMemo, useState } from "react";
import { AlertCircle, ArrowRight, CheckCircle2, Loader2, Network, Plus } from "lucide-react";
import { useCreateWorkspace } from "../api/hooks";

function isDefaultWorkspace(workspace) {
  return (
    workspace?.slug === "default" ||
    String(workspace?.name || "").trim().toLowerCase() === "default"
  );
}

export default function WorkspaceTopicGate({
  workspaces = [],
  selectedId = null,
  onSelect,
}) {
  const createWorkspace = useCreateWorkspace();
  const [name, setName] = useState("");
  const [createError, setCreateError] = useState(null);

  const { realWorkspaces, defaultWorkspace } = useMemo(() => {
    const real = [];
    let fallbackDefault = null;
    workspaces.forEach((workspace) => {
      if (isDefaultWorkspace(workspace)) {
        fallbackDefault = fallbackDefault || workspace;
      } else {
        real.push(workspace);
      }
    });
    return { realWorkspaces: real, defaultWorkspace: fallbackDefault };
  }, [workspaces]);

  const unresolvedSelection = selectedId && !workspaces.some((workspace) => workspace.id === selectedId);
  const hasRealWorkspaces = realWorkspaces.length > 0;
  const nameValue = name.trim();

  async function handleCreate(event) {
    event.preventDefault();
    if (!nameValue || createWorkspace.isPending) return;

    setCreateError(null);
    try {
      const workspace = await createWorkspace.mutateAsync({ name: nameValue });
      if (workspace?.id) {
        onSelect(workspace.id);
      }
    } catch (error) {
      setCreateError(error?.message || "Failed to create workspace.");
    }
  }

  return (
    <div className="flex h-full min-h-[520px] items-center justify-center p-4 sm:p-6">
      <div className="relative w-full max-w-5xl overflow-hidden rounded-[2rem] border border-slate-200 bg-white shadow-2xl shadow-slate-200/70 dark:border-slate-800 dark:bg-slate-950 dark:shadow-black/30">
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_left,rgba(79,70,229,0.14),transparent_38%),radial-gradient(circle_at_bottom_right,rgba(14,165,233,0.12),transparent_32%)]" />
        <div className="relative grid gap-0 lg:grid-cols-[0.92fr_1.08fr]">
          <section className="border-b border-slate-200 bg-slate-950 p-7 text-white dark:border-slate-800 lg:border-b-0 lg:border-r">
            <div className="mb-8 inline-flex h-12 w-12 items-center justify-center rounded-2xl bg-white/10 ring-1 ring-white/15">
              <Network className="h-6 w-6 text-brand-200" />
            </div>
            <p className="mb-3 text-xs font-black uppercase tracking-[0.24em] text-brand-200">
              Graph Workspace
            </p>
            <h1 className="text-3xl font-black tracking-tight sm:text-4xl">
              Choose the topic this graph should understand.
            </h1>
            <p className="mt-5 text-sm leading-6 text-slate-300">
              This workspace defines the project/topic whose Gmail, GitHub, Slack,
              AI sessions, docs, and local files will be focused in the graph.
            </p>
            <div className="mt-8 space-y-3 text-sm text-slate-300">
              <div className="flex gap-3">
                <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-300" />
                <span>Keep project facts, decisions, and relationships scoped together.</span>
              </div>
              <div className="flex gap-3">
                <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-300" />
                <span>Name it after the actual product or initiative, for example "Context Engine".</span>
              </div>
            </div>
          </section>

          <section className="p-6 sm:p-8">
            {unresolvedSelection && (
              <div className="mb-5 flex items-start gap-3 rounded-2xl border border-amber-200 bg-amber-50 p-4 text-amber-900 dark:border-amber-900/60 dark:bg-amber-950/40 dark:text-amber-200">
                <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                <p className="text-xs font-semibold leading-5">
                  The saved workspace could not be found. Pick a graph topic below to continue.
                </p>
              </div>
            )}

            <div className="mb-6">
              <h2 className="text-xl font-black text-slate-900 dark:text-white">
                {hasRealWorkspaces ? "Select a workspace" : "Create your first graph topic"}
              </h2>
              <p className="mt-2 text-sm leading-6 text-slate-500 dark:text-slate-400">
                {hasRealWorkspaces
                  ? "Choose the existing topic to load, or create a new one for another project."
                  : "The backend may create a Default workspace automatically. For a useful graph, start with the real topic you are working on."}
              </p>
            </div>

            {hasRealWorkspaces && (
              <div className="mb-7 grid gap-3 sm:grid-cols-2">
                {realWorkspaces.map((workspace) => (
                  <button
                    key={workspace.id}
                    type="button"
                    onClick={() => onSelect(workspace.id)}
                    className="group rounded-2xl border border-slate-200 bg-white p-4 text-left shadow-sm transition hover:-translate-y-0.5 hover:border-brand-300 hover:shadow-md dark:border-slate-800 dark:bg-slate-900/70 dark:hover:border-brand-700"
                  >
                    <div className="mb-3 flex h-10 w-10 items-center justify-center rounded-xl bg-brand-50 text-brand-600 transition group-hover:bg-brand-600 group-hover:text-white dark:bg-brand-900/30 dark:text-brand-300">
                      <Network className="h-4 w-4" />
                    </div>
                    <p className="truncate text-sm font-black text-slate-900 dark:text-white">
                      {workspace.name}
                    </p>
                    <p className="mt-1 truncate text-xs font-semibold text-slate-400">
                      {workspace.slug || "workspace topic"}
                    </p>
                  </button>
                ))}
              </div>
            )}

            <form onSubmit={handleCreate} className="rounded-3xl border border-slate-200 bg-slate-50 p-5 dark:border-slate-800 dark:bg-slate-900/60">
              <div className="mb-4 flex items-center gap-2">
                <div className="flex h-8 w-8 items-center justify-center rounded-xl bg-slate-900 text-white dark:bg-white dark:text-slate-950">
                  <Plus className="h-4 w-4" />
                </div>
                <div>
                  <h3 className="text-sm font-black text-slate-900 dark:text-white">
                    Create a new topic
                  </h3>
                  <p className="text-xs font-semibold text-slate-500 dark:text-slate-400">
                    Use a clear project name so future source sync can attach to it.
                  </p>
                </div>
              </div>

              <label className="mb-2 block text-xs font-black uppercase tracking-widest text-slate-400">
                Workspace/topic name
              </label>
              <div className="flex flex-col gap-3 sm:flex-row">
                <input
                  type="text"
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  placeholder="Context Engine"
                  className="min-w-0 flex-1 rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm font-semibold text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-brand-400 focus:ring-4 focus:ring-brand-500/10 dark:border-slate-700 dark:bg-slate-950 dark:text-white"
                />
                <button
                  type="submit"
                  disabled={!nameValue || createWorkspace.isPending}
                  className="inline-flex items-center justify-center gap-2 rounded-2xl bg-slate-900 px-5 py-3 text-sm font-black text-white shadow-sm transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-white dark:text-slate-950 dark:hover:bg-slate-200"
                >
                  {createWorkspace.isPending ? (
                    <>
                      <Loader2 className="h-4 w-4 animate-spin" />
                      Creating
                    </>
                  ) : (
                    <>
                      Create and load
                      <ArrowRight className="h-4 w-4" />
                    </>
                  )}
                </button>
              </div>

              {(createError || createWorkspace.isError) && (
                <p className="mt-3 text-xs font-semibold text-red-600 dark:text-red-400">
                  {createError || createWorkspace.error?.message || "Failed to create workspace."}
                </p>
              )}
            </form>

            {defaultWorkspace && (
              <button
                type="button"
                onClick={() => onSelect(defaultWorkspace.id)}
                className="mt-4 text-xs font-bold text-slate-400 underline-offset-4 hover:text-slate-600 hover:underline dark:hover:text-slate-300"
              >
                Use Default for now
              </button>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}
