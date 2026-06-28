import { useMemo, useState } from "react";
import { AlertCircle, ArrowRight, FolderKanban, Loader2, Plus } from "lucide-react";
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
    <div className="flex h-full min-h-[520px] items-center justify-center bg-slate-50 p-4 dark:bg-transparent sm:p-6">
      <div className="w-full max-w-3xl rounded-xl border border-slate-200 bg-white p-5 shadow-sm dark:border-neutral-800 dark:bg-black sm:p-6">
        <div className="mb-6 flex items-start gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-slate-100 text-slate-700 dark:bg-black dark:text-neutral-200">
            <FolderKanban className="h-5 w-5" />
          </div>
          <div className="min-w-0">
            <h1 className="text-xl font-bold tracking-tight text-slate-950 dark:text-white">
              Create or choose a workspace
            </h1>
            <p className="mt-1 max-w-2xl text-sm leading-6 text-slate-500 dark:text-neutral-400">
              Use one workspace for each project so sources, decisions, and relationships stay together.
            </p>
          </div>
        </div>

        {unresolvedSelection && (
          <div className="mb-5 flex items-start gap-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2.5 text-amber-900 dark:border-amber-900/60 dark:bg-amber-950/40 dark:text-amber-200">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
            <p className="text-xs font-semibold leading-5">
              The saved workspace could not be found. Choose a workspace below to continue.
            </p>
          </div>
        )}

        {hasRealWorkspaces && (
          <section className="mb-6">
            <h2 className="mb-3 text-xs font-bold uppercase tracking-widest text-slate-400">
              Existing workspaces
            </h2>
            <div className="grid gap-2 sm:grid-cols-2">
              {realWorkspaces.map((workspace) => (
                <button
                  key={workspace.id}
                  type="button"
                  onClick={() => onSelect(workspace.id)}
                  className="flex min-h-16 items-center gap-3 rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-left transition hover:border-slate-300 hover:bg-slate-50 dark:border-neutral-800 dark:bg-black dark:hover:border-slate-600 dark:hover:bg-black"
                >
                  <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-slate-100 text-slate-500 dark:bg-black dark:text-neutral-300">
                    <FolderKanban className="h-4 w-4" />
                  </div>
                  <div className="min-w-0">
                    <p className="truncate text-sm font-bold text-slate-900 dark:text-white">
                      {workspace.name}
                    </p>
                    <p className="mt-0.5 truncate text-xs font-medium text-slate-400">
                      {workspace.slug || "workspace"}
                    </p>
                  </div>
                </button>
              ))}
            </div>
          </section>
        )}

        <form onSubmit={handleCreate} className="rounded-lg border border-slate-200 bg-slate-50 p-4 dark:border-neutral-800 dark:bg-black">
          <div className="mb-3 flex items-center gap-2">
            <div className="flex h-7 w-7 items-center justify-center rounded-md bg-white text-slate-600 ring-1 ring-slate-200 dark:bg-black dark:text-neutral-300 dark:ring-slate-700">
              <Plus className="h-4 w-4" />
            </div>
            <div>
              <h3 className="text-sm font-bold text-slate-900 dark:text-white">
                New workspace
              </h3>
              <p className="text-xs font-medium text-slate-500 dark:text-neutral-400">
                Name it after the product, repo, customer, or initiative.
              </p>
            </div>
          </div>

          <label className="mb-1.5 block text-xs font-bold text-slate-500 dark:text-neutral-400">
            Workspace name
          </label>
          <div className="flex flex-col gap-2 sm:flex-row">
            <input
              type="text"
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="Context Engine"
              className="min-w-0 flex-1 rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-sm font-semibold text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-slate-400 focus:ring-4 focus:ring-slate-200/70 dark:border-neutral-800 dark:bg-black dark:text-white dark:focus:border-slate-500 dark:focus:ring-neutral-800"
            />
            <button
              type="submit"
              disabled={!nameValue || createWorkspace.isPending}
              className="inline-flex items-center justify-center gap-2 rounded-lg bg-slate-900 px-4 py-2.5 text-sm font-bold text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-white dark:text-slate-950 dark:hover:bg-slate-200"
            >
              {createWorkspace.isPending ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Creating
                </>
              ) : (
                <>
                  Create
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
      </div>
    </div>
  );
}
