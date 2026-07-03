import {
  AlertTriangle,
  Database,
  Loader2,
  RefreshCw,
} from "lucide-react";
import { useWorkspaces } from "../api/hooks";
import { resolveWorkspaceId, useWorkspaceSelection } from "../context/WorkspaceContext";
import WorkspaceTopicGate from "../components/WorkspaceTopicGate";
import { useBuildContext, useContextDigest } from "../context-map/api";
import DigestBoard from "../context-map/components/DigestBoard";

export default function ContextMapPage() {
  return <ContextDigestSurface />;
}

function ContextDigestSurface() {
  const { selectedId, setSelectedId } = useWorkspaceSelection();
  const workspacesQuery = useWorkspaces();
  const workspaces = workspacesQuery.data || [];
  const activeWorkspaceId = resolveWorkspaceId(workspaces, selectedId);
  const activeWorkspace = workspaces.find((workspace) => workspace.id === activeWorkspaceId);
  const digestQuery = useContextDigest(activeWorkspaceId);
  const buildContext = useBuildContext(activeWorkspaceId);

  const digest = digestQuery.data;

  if (!workspacesQuery.isLoading && !activeWorkspaceId) {
    return (
      <WorkspaceTopicGate
        workspaces={workspaces}
        selectedId={selectedId}
        onSelect={setSelectedId}
      />
    );
  }

  if (workspacesQuery.isLoading || digestQuery.isLoading) {
    return <PageLoading label="Loading context digest..." />;
  }

  if (digestQuery.isError) {
    return (
      <div className="flex h-full items-center justify-center bg-slate-50 p-6 dark:bg-[#050507]">
        <div className="w-full max-w-md rounded-lg border border-red-200 bg-white p-5 text-center dark:border-red-900/60 dark:bg-black">
          <AlertTriangle className="mx-auto mb-3 h-8 w-8 text-red-500" />
          <h1 className="text-base font-black text-slate-950 dark:text-white">Failed to load digest</h1>
          <p className="mt-2 text-sm leading-6 text-slate-500 dark:text-neutral-400">
            {digestQuery.error?.message || "The context digest endpoint is unavailable."}
          </p>
          <button
            type="button"
            onClick={() => digestQuery.refetch()}
            className="mt-4 inline-flex h-9 items-center justify-center rounded-md bg-slate-900 px-4 text-xs font-bold text-white transition hover:bg-slate-800 dark:bg-white dark:text-slate-950 dark:hover:bg-slate-200"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col bg-[#f5f6f8] text-slate-950 dark:bg-[#050507] dark:text-white">
      <div className="min-h-0 flex-1">
        <main className="h-full min-h-0 overflow-hidden px-4 py-4 md:px-6">
          {digest?.cards?.length ? (
            <DigestBoard
              digest={digest}
              workspaceName={activeWorkspace?.name || "selected workspace"}
              generatedAt={digest?.generated_at}
              onBuild={() => buildContext.mutate()}
              building={buildContext.isPending}
              buildResult={buildContext.data}
              buildError={buildContext.isError ? buildContext.error : null}
            />
          ) : (
            <EmptyDigest onBuild={() => buildContext.mutate()} building={buildContext.isPending} />
          )}
        </main>
      </div>
    </div>
  );
}

function EmptyDigest({ onBuild, building }) {
  return (
    <div className="flex min-h-[460px] items-center justify-center">
      <div className="max-w-md rounded-lg border border-dashed border-slate-300 bg-white px-5 py-8 text-center dark:border-neutral-800 dark:bg-black">
        <Database className="mx-auto mb-3 h-8 w-8 text-slate-300 dark:text-neutral-600" />
        <h2 className="text-base font-black text-slate-950 dark:text-white">No digest cards yet</h2>
        <p className="mt-2 text-sm leading-6 text-slate-500 dark:text-neutral-400">
          Import sources or build context for this workspace to create ranked cards.
        </p>
        <button
          type="button"
          onClick={onBuild}
          disabled={building}
          className="mt-4 inline-flex h-9 items-center justify-center gap-1.5 rounded-md bg-slate-900 px-4 text-xs font-bold text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60 dark:bg-white dark:text-slate-950 dark:hover:bg-slate-200"
        >
          {building ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
          Build Context
        </button>
      </div>
    </div>
  );
}

function PageLoading({ label }) {
  return (
    <div className="flex h-full items-center justify-center bg-slate-50 dark:bg-[#050507]">
      <div className="text-center">
        <Loader2 className="mx-auto mb-3 h-8 w-8 animate-spin text-slate-500 dark:text-neutral-300" />
        <p className="text-sm font-bold text-slate-700 dark:text-neutral-300">{label}</p>
      </div>
    </div>
  );
}
