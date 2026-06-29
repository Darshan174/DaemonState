import { Suspense, lazy, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Clock3,
  Database,
  GitBranch,
  Loader2,
  RefreshCw,
} from "lucide-react";
import { useWorkspaces } from "../api/hooks";
import { resolveWorkspaceId, useWorkspaceSelection } from "../context/WorkspaceContext";
import WorkspaceTopicGate from "../components/WorkspaceTopicGate";
import { useBuildContext, useContextDigest } from "../context-map/api";
import DigestBoard from "../context-map/components/DigestBoard";
import ContextInspector from "../context-map/components/ContextInspector";
import { HEALTH_META, TONE_CLASSES, cardsById, formatTimeAgo } from "../context-map/digest";

const LegacyGraphView = lazy(() => import("./GraphView"));

export default function ContextMapPage() {
  const [searchParams] = useSearchParams();
  const showLegacyGraph = searchParams.get("legacy") === "1" || searchParams.get("graph") === "explore";

  if (showLegacyGraph) {
    return (
      <Suspense fallback={<PageLoading label="Loading graph..." />}>
        <LegacyGraphView />
      </Suspense>
    );
  }

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
  const [selectedCardId, setSelectedCardId] = useState(null);

  const digest = digestQuery.data;
  const byId = useMemo(() => cardsById(digest?.cards || []), [digest]);
  const selectedCard = selectedCardId ? byId.get(selectedCardId) : null;

  useEffect(() => {
    if (!digest?.cards?.length) {
      setSelectedCardId(null);
      return;
    }
    if (!selectedCardId || !byId.has(selectedCardId)) {
      setSelectedCardId(digest.cards[0].id);
    }
  }, [digest, selectedCardId, byId]);

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

  const health = digest?.health || {};
  const healthMeta = HEALTH_META[health.status] || HEALTH_META.empty;

  return (
    <div className="flex h-full min-h-0 flex-col bg-[#f5f6f8] text-slate-950 dark:bg-[#050507] dark:text-white">
      <header className="shrink-0 border-b border-slate-200 bg-white px-4 py-3 dark:border-neutral-800 dark:bg-[#07080a] md:px-6">
        <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-lg font-black tracking-tight text-slate-950 dark:text-white">
                Context Digest
              </h1>
              <span className={`rounded-md border px-2 py-1 text-[11px] font-bold ${TONE_CLASSES[healthMeta.tone] || TONE_CLASSES.gray}`}>
                {healthMeta.label}
              </span>
            </div>
            <p className="mt-1 text-xs font-semibold text-slate-500 dark:text-neutral-400">
              Workspace: {activeWorkspace?.name || "Selected workspace"} · Last built: {formatTimeAgo(digest?.generated_at)}
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <Link
              to="/app/sources"
              className="inline-flex h-9 items-center gap-1.5 rounded-md border border-slate-200 bg-white px-3 text-xs font-bold text-slate-600 transition hover:bg-slate-50 dark:border-neutral-800 dark:bg-black dark:text-neutral-300 dark:hover:bg-neutral-900"
            >
              <Database className="h-3.5 w-3.5" />
              Sources
            </Link>
            <Link
              to="/app/graph?graph=explore"
              className="inline-flex h-9 items-center gap-1.5 rounded-md border border-slate-200 bg-white px-3 text-xs font-bold text-slate-600 transition hover:bg-slate-50 dark:border-neutral-800 dark:bg-black dark:text-neutral-300 dark:hover:bg-neutral-900"
            >
              <GitBranch className="h-3.5 w-3.5" />
              Explore Graph
            </Link>
            <button
              type="button"
              onClick={() => buildContext.mutate()}
              disabled={!activeWorkspaceId || buildContext.isPending}
              className="inline-flex h-9 items-center gap-1.5 rounded-md bg-slate-900 px-3 text-xs font-bold text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60 dark:bg-white dark:text-slate-950 dark:hover:bg-slate-200"
            >
              {buildContext.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
              Build Context
            </button>
          </div>
        </div>

        {buildContext.data ? (
          <div className="mt-3 flex flex-wrap items-center gap-3 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs font-bold text-emerald-800 dark:border-emerald-900/60 dark:bg-emerald-950/35 dark:text-emerald-200">
            <CheckCircle2 className="h-4 w-4" />
            {buildContext.data.docs_processed} docs processed · {buildContext.data.components_created} components created · {buildContext.data.relationships_inferred} relationships inferred
          </div>
        ) : null}
        {buildContext.isError ? (
          <div className="mt-3 flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs font-bold text-red-800 dark:border-red-900/60 dark:bg-red-950/35 dark:text-red-200">
            <AlertTriangle className="h-4 w-4" />
            {buildContext.error?.message || "Build failed"}
          </div>
        ) : null}
      </header>

      <div className="grid shrink-0 grid-cols-2 border-b border-slate-200 bg-white dark:border-neutral-800 dark:bg-[#07080a] md:grid-cols-4">
        <HealthTile label="Health" value={healthMeta.label} detail={health.summary} icon={CheckCircle2} tone={healthMeta.tone} />
        <HealthTile label="Blockers" value={health.blocker_count ?? 0} detail={`${health.conflict_count ?? 0} conflicts`} icon={AlertTriangle} tone={(health.blocker_count || health.conflict_count) ? "red" : "gray"} />
        <HealthTile label="Unverified" value={health.unverified_count ?? 0} detail={`${health.stale_count ?? 0} stale`} icon={Clock3} tone={health.unverified_count ? "amber" : "gray"} />
        <HealthTile label="Agent-ready" value={`${health.agent_ready_score ?? 0}%`} detail={`${digest?.cards?.length || 0} cards ranked`} icon={ArrowRight} tone={(health.agent_ready_score ?? 0) >= 75 ? "green" : "blue"} />
      </div>

      <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
        <main className="min-h-0 flex-1 overflow-y-auto px-4 py-4 md:px-6">
          {digest?.cards?.length ? (
            <DigestBoard
              digest={digest}
              selectedCardId={selectedCardId}
              onSelectCard={(card) => setSelectedCardId(card.id)}
            />
          ) : (
            <EmptyDigest onBuild={() => buildContext.mutate()} building={buildContext.isPending} />
          )}
        </main>
        <ContextInspector
          card={selectedCard}
          cards={digest?.cards || []}
          links={digest?.links || []}
          onClose={() => setSelectedCardId(null)}
        />
      </div>
    </div>
  );
}

function HealthTile({ label, value, detail, icon: Icon, tone = "gray" }) {
  return (
    <div className="min-h-24 border-r border-slate-200 px-4 py-3 last:border-r-0 dark:border-neutral-800 md:px-5">
      <div className="mb-2 flex items-center justify-between gap-3">
        <p className="text-[11px] font-bold uppercase text-slate-400">{label}</p>
        <span className={`flex h-7 w-7 items-center justify-center rounded-md border ${TONE_CLASSES[tone] || TONE_CLASSES.gray}`}>
          <Icon className="h-3.5 w-3.5" />
        </span>
      </div>
      <p className="text-2xl font-black text-slate-950 dark:text-white">{value}</p>
      <p className="mt-1 line-clamp-1 text-[11px] font-semibold text-slate-500 dark:text-neutral-400">
        {detail}
      </p>
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
