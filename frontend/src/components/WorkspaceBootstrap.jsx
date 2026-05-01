import { useState } from "react";
import { useWorkspaces, useCreateWorkspace } from "../api/hooks";
import { useWorkspaceSelection } from "../context/WorkspaceContext";

/**
 * Full-screen gate shown when no workspace exists yet.
 * Renders children once at least one workspace is present.
 */
export default function WorkspaceBootstrap({ children }) {
  const { data: workspaces, isLoading, isError, error, refetch } = useWorkspaces();
  const create = useCreateWorkspace();
  const { setSelectedId } = useWorkspaceSelection();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");

  // While checking, show a minimal loader
  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-screen bg-gray-50 dark:bg-gray-900/30">
        <p className="text-sm text-gray-400">Connecting to backend...</p>
      </div>
    );
  }

  if (isError) {
    // Network error (no HTTP status) — backend unreachable, let mock fallbacks work
    if (!error?.status) return children;

    // Real server error (4xx/5xx) — surface it instead of silently proceeding
    return (
      <div className="flex items-center justify-center h-screen bg-gray-50 dark:bg-gray-900/30">
        <div className="w-full max-w-sm mx-4 text-center">
          <div className="w-10 h-10 rounded-full bg-red-100 dark:bg-red-900/40 flex items-center justify-center mx-auto mb-3">
            <span className="text-red-500 text-lg font-bold">!</span>
          </div>
          <p className="text-sm font-medium text-red-600 dark:text-red-400 mb-1">Failed to load workspaces</p>
          <p className="text-xs text-gray-400 mb-4">
            {error?.message || `Server returned ${error?.status}`}
          </p>
          <button
            onClick={() => refetch()}
            className="px-4 py-2 text-sm font-medium rounded-lg border border-gray-200 dark:border-gray-800/50 text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:bg-gray-900/30 transition-colors"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  // Workspace exists — render app normally
  if (workspaces && workspaces.length > 0) return children;

  // No workspace — show creation form
  const handleSubmit = (e) => {
    e.preventDefault();
    if (!name.trim()) return;
    create.mutate(
      { name: name.trim(), description: description.trim() || null },
      {
        onSuccess: (newWorkspace) => {
          if (newWorkspace?.id) setSelectedId(newWorkspace.id);
        },
      },
    );
  };

  return (
    <div className="relative flex h-screen items-center justify-center bg-slate-50 text-slate-900 transition-colors dark:bg-slate-950 dark:text-slate-100">
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_center,rgba(79,70,229,0.12)_0%,transparent_70%)] dark:bg-[radial-gradient(circle_at_center,rgba(79,70,229,0.15)_0%,transparent_70%)]" />
      <div className="w-full max-w-md mx-4 relative z-10">
        <div className="bg-white dark:bg-slate-800 rounded-[32px] border border-slate-200 dark:border-slate-800/50 shadow-2xl p-10">
          <div className="flex items-center gap-3 mb-8">
            <span className="w-10 h-10 rounded-2xl bg-brand-600 flex items-center justify-center text-white font-bold text-sm shadow-lg shadow-brand-500/30">
              CE
            </span>
            <span className="font-bold text-slate-900 dark:text-slate-200 text-xl tracking-tight">Context Engine</span>
          </div>

          <h2 className="text-2xl font-bold text-slate-900 dark:text-slate-200 mb-2">Create Workspace</h2>
          <p className="text-sm text-slate-500 dark:text-slate-400 mb-8 leading-relaxed">
            Every startup needs a grounded memory. Set up your first workspace to start ingesting context.
          </p>

          <form onSubmit={handleSubmit} className="space-y-6">
            <div>
              <label className="block text-xs font-bold uppercase tracking-widest text-slate-400 mb-2">Workspace Name</label>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. Acme Corp"
                required
                className="w-full px-4 py-3 bg-slate-50 dark:bg-slate-900/30 border border-slate-200 dark:border-slate-800/50 rounded-xl focus:outline-none focus:ring-2 focus:ring-brand-500/20 focus:border-brand-500 transition-all text-sm font-medium text-slate-900 dark:text-slate-100 placeholder:text-slate-400"
              />
            </div>

            {create.isError && (
              <div className="p-3 bg-red-50 dark:bg-red-900/30 border border-red-100 dark:border-red-800/30 rounded-xl flex items-start gap-2">
                <span className="text-red-500 text-sm font-bold mt-0.5">!</span>
                <p className="text-xs text-red-800 dark:text-red-300 font-medium">
                  {create.error?.message || "Failed to create workspace."}
                </p>
              </div>
            )}

            <button
              type="submit"
              disabled={create.isPending || !name.trim()}
              className="w-full py-4 text-sm font-bold rounded-xl bg-slate-900 text-white hover:bg-slate-800 disabled:opacity-50 transition-all shadow-lg flex items-center justify-center gap-2"
            >
              {create.isPending ? (
                <>
                  <div className="w-4 h-4 border-2 border-white/20 border-t-white rounded-full animate-spin" />
                  Initializing...
                </>
              ) : (
                <>
                  Create Workspace
                  <ArrowRight className="w-4 h-4" />
                </>
              )}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}

function ArrowRight({ className }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M14 5l7 7m0 0l-7 7m7-7H3" />
    </svg>
  );
}
