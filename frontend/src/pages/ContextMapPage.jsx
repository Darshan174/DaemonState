import { useEffect, useState } from "react";
import {
  AlertTriangle,
  Loader2,
} from "lucide-react";
import { useWorkspaces } from "../api/hooks";
import { resolveWorkspaceId, useWorkspaceSelection } from "../context/WorkspaceContext";
import WorkspaceTopicGate from "../components/WorkspaceTopicGate";
import { useBuildContext, useContextDigest } from "../context-map/api";
import DigestBoard from "../context-map/components/DigestBoard";
import ContextInspector from "../context-map/components/ContextInspector";

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
  const [selectedCard, setSelectedCard] = useState(null);

  const digest = digestQuery.data;

  useEffect(() => {
    setSelectedCard(null);
  }, [activeWorkspaceId]);

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
      <div className="flex h-full items-center justify-center bg-[#f7f7f2] p-6 dark:bg-[#0d0d0b]">
        <div className="w-full max-w-md rounded-md border border-red-200 bg-[#fbfbf6] p-5 text-center dark:border-red-900/60 dark:bg-[#141411]">
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
    <div className="flex h-full min-h-0 flex-col bg-[#f7f7f2] text-[#171713] dark:bg-[#0d0d0b] dark:text-[#f4f4ec]">
      <div className="min-h-0 flex-1">
        <main className="h-full min-h-0 overflow-hidden">
          {digest ? (
            <div className="relative flex h-full min-h-0">
              <div className="min-w-0 flex-1">
                <DigestBoard
                  digest={digest}
                  workspaceName={activeWorkspace?.name || "selected workspace"}
                  generatedAt={digest?.generated_at}
                  onBuild={(mode) => buildContext.mutate({ mode })}
                  building={buildContext.isPending}
                  buildResult={buildContext.data}
                  buildError={buildContext.isError ? buildContext.error : null}
                  onSelectCard={setSelectedCard}
                />
              </div>
              {selectedCard ? (
                <div className="absolute inset-y-0 right-0 z-50 flex w-full max-w-[430px] overflow-hidden rounded-r-lg shadow-[-24px_0_60px_rgba(15,23,42,0.16)]">
                  <ContextInspector
                    card={selectedCard}
                    cards={digest.cards}
                    links={digest.links}
                    workspaceId={activeWorkspaceId}
                    onClose={() => setSelectedCard(null)}
                  />
                </div>
              ) : null}
            </div>
          ) : null}
        </main>
      </div>
    </div>
  );
}

function PageLoading({ label }) {
  return (
    <div className="flex h-full items-center justify-center bg-[#f7f7f2] dark:bg-[#0d0d0b]">
      <div className="text-center">
        <Loader2 className="mx-auto mb-3 h-8 w-8 animate-spin text-slate-500 dark:text-neutral-300" />
        <p className="text-sm font-bold text-slate-700 dark:text-neutral-300">{label}</p>
      </div>
    </div>
  );
}
