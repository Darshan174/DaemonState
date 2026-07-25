import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  ArrowRight,
  Bot,
  CheckCircle2,
  Clipboard,
  Clock3,
  FileCode2,
  GitBranch,
  History,
  Layers3,
  PlayCircle,
  RefreshCw,
  ShieldAlert,
  ShieldCheck,
} from "lucide-react";

import WorkspaceTopicGate from "../components/WorkspaceTopicGate";
import ProductLoadingState from "../components/ProductLoadingState";
import { HarnessContinuationCard } from "../components/HarnessCard";
import { HARNESS_ORDER, harnessMeta } from "../components/HarnessBrand";
import {
  useCheckpoints,
  useContinuationProviders,
  useLatestCheckpoint,
  useRunContinuation,
  useSessionLibrary,
} from "../api/hooks";
import {
  useContextDigest,
  useLinkedAISessionRefresh,
  useProjectMemory,
} from "../context-map/api";
import { cleanDisplayText, formatTimeAgo, sessionIdentity } from "../context-map/digest";
import { useProductWorkspace } from "./useProductWorkspace";

export default function NowPage() {
  const [searchParams] = useSearchParams();
  const workspace = useProductWorkspace();
  const digestQuery = useContextDigest(workspace.activeWorkspaceId, { poll: true });
  const digestActivity = digestQuery.data?.activity?.primary || null;
  const activeCheckpointSession = activitySessionReference(digestActivity);
  const digestSettled = Boolean(digestQuery.data) || digestQuery.isError;
  const hasActiveCheckpointSession = Boolean(activeCheckpointSession);
  const checkpointQuery = useLatestCheckpoint(
    workspace.activeWorkspaceId,
    {
      ...(activeCheckpointSession || {}),
      enabled: digestSettled && hasActiveCheckpointSession,
    },
  );
  const scopedCheckpointSettled = hasActiveCheckpointSession
    && queryHasSettled(checkpointQuery);
  const workspaceCheckpointQuery = useLatestCheckpoint(
    workspace.activeWorkspaceId,
    {
      enabled: digestSettled && (
        !hasActiveCheckpointSession
        || scopedCheckpointSettled
      ),
    },
  );
  const primaryCheckpointQuery = hasActiveCheckpointSession
    ? checkpointQuery
    : workspaceCheckpointQuery;
  const checkpointSettled = digestSettled && queryHasSettled(primaryCheckpointQuery);
  const activitySession = activitySessionDescriptor(digestActivity);
  const libraryFallbackNeeded = !activitySession;
  const libraryQuery = useSessionLibrary(
    workspace.activeWorkspaceId,
    { enabled: checkpointSettled && libraryFallbackNeeded },
  );
  const latestSession = activitySession || libraryQuery.data?.sessions?.[0] || null;
  const detailSessionReference = activeCheckpointSession
    || checkpointSessionReference(primaryCheckpointQuery.data)
    || sessionDescriptorReference(latestSession);
  const checkpointHistoryQuery = useCheckpoints(
    workspace.activeWorkspaceId,
    12,
    {
      enabled: checkpointSettled && Boolean(detailSessionReference),
      ...(detailSessionReference || {}),
    },
  );
  const memoryQuery = useProjectMemory(
    workspace.activeWorkspaceId,
    { limit: 1, poll: true, enabled: checkpointSettled },
  );
  const continuationProvidersQuery = useContinuationProviders(
    workspace.activeWorkspaceId,
  );
  const runContinuation = useRunContinuation();
  const [continuationState, setContinuationState] = useState("idle");
  const [continuationResult, setContinuationResult] = useState(null);
  const [continuationError, setContinuationError] = useState(null);
  const [pendingProvider, setPendingProvider] = useState(null);
  const continuationRequestKey = JSON.stringify([
    workspace.activeWorkspaceId || "",
    searchParams.get("objective") || "",
    searchParams.get("checkpoint") || "",
    searchParams.get("checkpoint_source") || "",
    digestQuery.data?.current_goal?.title || "",
    digestActivity?.request || digestActivity?.title || "",
    digestQuery.data?.scope?.project_paths?.[0]
      || digestActivity?.cwd
      || latestSession?.cwd
      || primaryCheckpointQuery.data?.activity?.cwd
      || workspace.activeWorkspace?.repo_path
      || "",
    primaryCheckpointQuery.data?.sections?.goal?.[0]?.statement || "",
  ]);
  useEffect(() => {
    setContinuationState("idle");
    setContinuationResult(null);
    setContinuationError(null);
    setPendingProvider(null);
  }, [continuationRequestKey]);
  useLinkedAISessionRefresh(
    workspace.activeWorkspaceId,
    { enabled: checkpointSettled, initialDelayMs: 5_000 },
  );

  if (!workspace.workspacesQuery.isLoading && !workspace.activeWorkspaceId) {
    return (
      <WorkspaceTopicGate
        workspaces={workspace.workspaces}
        selectedId={workspace.selectedId}
        onSelect={workspace.setSelectedId}
      />
    );
  }
  if (workspace.workspacesQuery.isLoading) {
    return (
      <ProductLoadingState
        label="Opening the workspace…"
        detail="The Now view will appear as soon as the workspace is selected."
        stages={["Selecting the workspace", "Opening Now"]}
      />
    );
  }

  const digest = digestQuery.data || {};
  const digestPending = digestQuery.isLoading && !digestQuery.data;
  const digestUnavailable = digestQuery.isError && !digestQuery.data;
  const digestError = digestQuery.isError ? digestQuery.error : null;
  const cards = digest.cards || [];
  const workspaceCheckpoint = workspaceCheckpointQuery.data || null;
  // Now is current observed activity. A checkpoint is a separate immutable
  // recovery boundary and must never replace newer session state.
  const observedActivity = digest.activity?.primary || fallbackActivity(digest);
  const checkpointIsCurrent = workspaceCheckpoint?.currentness?.state === "captured";
  const activity = observedActivity || (checkpointIsCurrent ? workspaceCheckpoint?.activity : null);
  const checkpoint = activeCheckpointSession
    ? checkpointQuery.data || null
    : checkpointMatchesActivity(workspaceCheckpoint, activity)
      ? workspaceCheckpoint
      : null;
  const currentCheckpoint = checkpoint?.currentness?.state === "captured" ? checkpoint : null;
  const previousCheckpoint = (
    workspaceCheckpoint
    && workspaceCheckpoint.id !== checkpoint?.id
    && !checkpointMatchesActivity(workspaceCheckpoint, activity)
  ) ? workspaceCheckpoint : null;
  const requestedObjective = prepareTaskCandidate(searchParams.get("objective"));
  const requestedCheckpointId = String(searchParams.get("checkpoint") || "").trim();
  const currentGoal = prepareTaskCandidate(digest.current_goal?.title);
  const attentionCards = cards
    .filter((card) => card.attention_required)
    .filter((card) => card.workspace_relevance?.status !== "not_relevant")
    .sort((left, right) => (right.attention_score || 0) - (left.attention_score || 0))
    .slice(0, 4);
  const recentSessionCards = cards
    .filter((card) => card.category === "agent_session")
    .filter((card) => card.workspace_relevance?.status === "relevant")
    .sort((left, right) => activityTimestamp(right) - activityTimestamp(left))
    .slice(0, 4);
  const unassignedSessionCards = cards.filter(
    (card) => card.category === "agent_session" && card.workspace_relevance?.status === "unknown",
  );
  const unassignedSessionCard = unassignedSessionCards[0];
  const unassignedSessionCount = unassignedSessionCards.length;
  const sessionCompactions = (checkpointHistoryQuery.data?.checkpoints || [])
    .filter((item) => (
      checkpoint
      && item.provider === checkpoint.provider
      && item.session_id === checkpoint.session_id
      && item.boundary?.snapshot_phase === "pre_compaction"
    ))
    .sort((left, right) => (
      Number(left.boundary?.sequence_number || 0)
      - Number(right.boundary?.sequence_number || 0)
    ));
  const continuationObjective = requestedObjective
    || currentGoal
    || prepareTaskCandidate(observedActivity?.request)
    || prepareTaskCandidate(observedActivity?.session_title)
    || prepareTaskCandidate(observedActivity?.title)
    || prepareTaskCandidate(latestSession?.title)
    || prepareTaskCandidate(cleanRecoveryText(currentCheckpoint?.sections?.goal?.[0]?.statement));
  const continuationRepoPath = digest.scope?.project_paths?.[0]
    || activity?.cwd
    || latestSession?.cwd
    || workspace.activeWorkspace?.repo_path
    || null;
  const continuationBranch = activity?.branch
    || currentCheckpoint?.repo?.branch
    || currentCheckpoint?.repository?.branch
    || null;
  const runTaskContinuation = async (targetProvider) => {
    if (!workspace.activeWorkspaceId || (!continuationObjective && !continuationRepoPath)) return;
    setContinuationState("running");
    setContinuationResult(null);
    setContinuationError(null);
    setPendingProvider(targetProvider);
    try {
      const result = await runContinuation.mutateAsync({
        workspace_id: workspace.activeWorkspaceId,
        idempotency_key: continuationIdempotencyKey(),
        target_provider: targetProvider,
        ...(continuationObjective ? { objective: continuationObjective } : {}),
        ...(continuationRepoPath ? { repo_path: continuationRepoPath } : {}),
        ...(requestedCheckpointId ? { checkpoint_id: requestedCheckpointId } : {}),
        ...(requestedCheckpointId && searchParams.get("checkpoint_source")
          ? { checkpoint_source_id: searchParams.get("checkpoint_source") }
          : {}),
      });
      setContinuationResult(result);
      const blocker = continuationBlocker(result);
      setContinuationError(blocker);
      setContinuationState(blocker ? "blocked" : "completed");
    } catch (error) {
      setContinuationState("blocked");
      setContinuationError(continuationErrorFromRequest(error, targetProvider));
    } finally {
      setPendingProvider(null);
    }
  };
  const actionInputsPending = digestPending
    || (!latestSession && libraryFallbackNeeded && (
      !checkpointSettled
      || libraryQuery.isLoading
      || !queryHasSettled(libraryQuery)
    ))
    || (
      !currentGoal
      && Boolean(latestSession)
      && (activeCheckpointSession ? checkpointQuery.isLoading : workspaceCheckpointQuery.isLoading)
    );
  const continueAction = digestUnavailable
    ? {
        kind: "unavailable",
        description: "Current activity could not be loaded. Saved project evidence remains available below.",
      }
    : actionInputsPending
      ? {
          kind: "loading",
          description: "Resolving the current task, repository, and safest continuation.",
        }
      : continuationObjective || continuationRepoPath
        ? {
            kind: "continue",
            description: "Resolve the task, reconcile the repository, run a fresh agent, and verify the observed outcome automatically.",
          }
        : {
            kind: "choose",
            description: "Choose linked work before continuing.",
          };
  const continuationProviders = resolvedContinuationProviders(continuationProvidersQuery);
  const continuationRunnable = continueAction.kind === "continue";

  return (
    <div className="app-page ce-now-page relative">
      <header className="ce-now-hero relative overflow-hidden rounded-[1.75rem] border border-black/10 bg-[#171713] text-white shadow-[0_24px_70px_rgba(23,23,19,0.16)] dark:border-[#292929]">
        <div className="ce-now-grid pointer-events-none absolute inset-0" aria-hidden="true" />
        <div className="ce-now-orbit pointer-events-none absolute -right-24 -top-32 h-80 w-80 rounded-full border border-white/10" aria-hidden="true" />
        <div className="relative px-5 pb-6 pt-5 sm:px-7 sm:pb-7 sm:pt-6 lg:px-9 lg:pb-8 lg:pt-7">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/10 pb-4">
            <p className="text-xs font-semibold text-[#c5c5bc]">{workspace.activeWorkspace?.name || "Project"}</p>
            <span className="inline-flex items-center rounded-full border border-white/12 bg-white/[0.05] px-3 py-1 text-[11px] font-semibold text-[#d0d0c8]">
              {digestPending
                ? "Loading activity"
                : digestUnavailable
                  ? "Activity unavailable"
                  : activity
                    ? "Activity in view"
                    : "Waiting for activity"}
            </span>
          </div>

          <div className="mt-7">
            <div className="max-w-3xl">
              <p className="text-[10px] font-black uppercase tracking-[0.2em] text-[#d9ff68]">
                Choose the next harness
              </p>
              <h1 className="mt-3 text-[clamp(2rem,4.2vw,3.5rem)] font-semibold leading-[0.96] tracking-[-0.055em] text-white">
                Continue with full context
              </h1>
              <p className="mt-4 max-w-2xl text-sm leading-6 text-[#b8b8af] sm:text-[15px]">
                The selected agent starts fresh with the same reconciled decisions, learnings, memory, blockers, and repository state.
              </p>
            </div>

            <dl
              className="mt-5 grid max-w-4xl gap-px overflow-hidden rounded-xl border border-white/10 bg-white/10 sm:grid-cols-[minmax(0,1.7fr)_minmax(0,1fr)_minmax(0,1fr)]"
              aria-label="Continuation task contract"
            >
              <ContinuationContractItem
                label="Execution goal"
                value={compactContinuationGoal(continuationObjective)}
              />
              <ContinuationContractItem
                label="Repository"
                value={continuationRepositoryLabel(continuationRepoPath)}
              />
              <ContinuationContractItem
                label="Branch"
                value={preserveContinuationText(continuationBranch) || "Resolved at launch"}
              />
            </dl>

            <div className="mt-7 grid gap-3 md:grid-cols-3" aria-label="Continuation harnesses">
              {continuationProviders.map((provider) => (
                <HarnessContinuationCard
                  key={provider.provider}
                  provider={provider}
                  pending={pendingProvider === provider.provider}
                  workflowPending={continuationState === "running" || runContinuation.isPending}
                  taskReady={continuationRunnable}
                  onContinue={runTaskContinuation}
                />
              ))}
            </div>

            <div className="mt-4 flex flex-col justify-between gap-3 sm:flex-row sm:items-center">
              <div className="flex flex-wrap items-center gap-2">
                <span className="rounded-full border border-[#d9ff68]/30 bg-[#d9ff68]/10 px-2.5 py-1 text-[10px] font-semibold text-[#d9ff68]">
                  Automatic reconciliation
                </span>
                {requestedCheckpointId ? (
                  <span className="rounded-full border border-white/15 bg-white/[0.04] px-2.5 py-1 text-[10px] font-semibold text-[#c5c5bc]">
                    Recovery request · {requestedCheckpointId}
                  </span>
                ) : null}
              </div>
              {continueAction.kind === "choose" ? (
                <Link to="/app/library" className="group inline-flex min-h-11 items-center gap-1.5 text-xs font-semibold text-[#d9ff68]">
                  Choose work to continue
                  <ArrowRight className="h-3.5 w-3.5 transition-transform group-hover:translate-x-0.5" aria-hidden="true" />
                </Link>
              ) : null}
            </div>
            <p className="mt-3 text-xs leading-5 text-[#97978f]">{continueAction.description}</p>
            <div className="mt-3 max-w-3xl">
              <ContinuationWorkflowStatus
                state={continuationState}
                result={continuationResult}
                blocker={continuationError}
              />
            </div>
          </div>
        </div>

        <TaskStatusRibbon
          activity={activity}
          checkpoint={currentCheckpoint}
          loading={digestPending}
          error={digestUnavailable}
        />
      </header>

      {digestError ? (
        <div className={`flex flex-col justify-between gap-3 rounded-2xl border px-4 py-3.5 sm:flex-row sm:items-center ${
          digestQuery.data
            ? "border-amber-200 bg-amber-50 text-amber-950 dark:border-amber-900/60 dark:bg-amber-950/25 dark:text-amber-100"
            : "border-red-200 bg-red-50 text-red-800 dark:border-red-900/60 dark:bg-red-950/25 dark:text-red-100"
        }`}>
          <div>
            <p className="text-xs font-semibold">
              {digestQuery.data ? "Activity refresh failed" : "Could not load current activity"}
            </p>
            <p className="mt-1 text-[11px] leading-5 opacity-75">
              {digestQuery.data
                ? "Showing the last loaded activity while saved context continues to load."
                : digestError.message || "Saved context and memory remain available below."}
            </p>
          </div>
          {digestQuery.refetch ? (
            <button type="button" onClick={() => digestQuery.refetch()} className="min-h-11 shrink-0 rounded-xl border border-current px-4 text-xs font-semibold">
              Try again
            </button>
          ) : null}
        </div>
      ) : null}

      {unassignedSessionCount > 0 ? <UnassignedSessions count={unassignedSessionCount} cardId={unassignedSessionCard?.id} /> : null}

      <section className="grid items-start gap-4 lg:grid-cols-2 xl:grid-cols-3" aria-label="Observed work overview">
        <ObservedWork
          activity={activity}
          loading={digestPending}
          error={digestUnavailable}
        />
        <ObservedResult
          activity={activity}
          checkpoint={checkpoint}
          attentionCount={attentionCards.length}
          loading={digestPending}
          error={digestUnavailable}
        />
        <ContinuationSummary
          checkpoint={checkpoint}
          latestSession={latestSession}
          loading={digestPending || (
            !digestUnavailable
            && (
              !checkpointSettled
              || (
                !latestSession
                && libraryFallbackNeeded
                && !queryHasSettled(libraryQuery)
              )
            )
          )}
          error={digestUnavailable}
        />
      </section>

      <CheckpointPanel
        checkpoint={checkpoint}
        previousCheckpoint={previousCheckpoint}
        sessionCompactions={sessionCompactions}
        isLoading={
          digestPending
          || !checkpointSettled
        }
        error={checkpointQuery.error || workspaceCheckpointQuery.error}
        memory={checkpointSettled ? memoryQuery.data : null}
        memoryLoading={
          !checkpointSettled
          || (!queryHasSettled(memoryQuery) && !memoryQuery.error)
        }
        memoryError={checkpointSettled ? memoryQuery.error : null}
      />

      <AttentionPanel cards={attentionCards} loading={digestPending} error={digestUnavailable} />

      {checkpointSettled && !digestUnavailable && recentSessionCards.length
        ? <RecentSessions cards={recentSessionCards} />
        : null}
    </div>
  );
}

function CheckpointPanel({
  checkpoint,
  previousCheckpoint,
  sessionCompactions,
  isLoading,
  error,
  memory,
  memoryLoading,
  memoryError,
}) {
  if (isLoading) {
    return (
      <section id="continuity-checkpoint" className="app-surface scroll-mt-24">
        <header className="border-b border-[#e1e1d9] px-6 py-6 dark:border-[#292925] sm:px-8 sm:py-7">
          <PanelLabel icon={ShieldCheck}>Saved context</PanelLabel>
          <h2 className="mt-3 text-2xl font-semibold tracking-[-0.035em] text-[#171713] dark:text-white">
            Loading saved context…
          </h2>
        </header>
        <div className="grid lg:grid-cols-[minmax(0,1.15fr)_minmax(19rem,.85fr)]">
          <div className="px-6 py-6 sm:px-8 sm:py-8" role="status" aria-busy="true">
            <p className="text-sm leading-6 text-[#68685f] dark:text-[#aaa9a0]">
              Checking this task’s latest saved recovery point.
            </p>
            <div className="mt-5 space-y-3" aria-hidden="true">
              <span className="block h-3 w-4/5 animate-pulse rounded-full bg-[#e8e8e0] dark:bg-white/[0.07]" />
              <span className="block h-3 w-3/5 animate-pulse rounded-full bg-[#e8e8e0] dark:bg-white/[0.07]" />
            </div>
          </div>
          <div className="border-t border-[#deded5] dark:border-[#292925] lg:border-l lg:border-t-0">
            <ProjectMemorySummary memory={memory} loading={memoryLoading} error={memoryError} />
          </div>
        </div>
      </section>
    );
  }
  if (!checkpoint) {
    const earlierBoundary = previousCheckpoint?.boundary || {};
    const earlierGoal = prepareTaskCandidate(cleanRecoveryText(
      previousCheckpoint?.sections?.goal?.[0]?.statement,
    ));
    return (
      <section id="continuity-checkpoint" className="app-surface scroll-mt-24">
        <header className="border-b border-[#e1e1d9] px-6 py-6 dark:border-[#292925] sm:px-8 sm:py-7">
          <PanelLabel icon={ShieldCheck}>Saved context</PanelLabel>
          <h2 className="mt-3 text-2xl font-semibold tracking-[-0.035em] text-[#171713] dark:text-white">
            No saved context for this task
          </h2>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-[#68685f] dark:text-[#aaa9a0]">
            Context is captured automatically during session sync and continuation.
          </p>
        </header>

        <div className="grid lg:grid-cols-[minmax(0,1.15fr)_minmax(19rem,.85fr)]">
          <div className="px-6 py-6 sm:px-8 sm:py-8">
            <p className="max-w-2xl text-sm leading-6 text-[#68685f] dark:text-[#aaa9a0]">
              Continue will resolve the latest linked session and create the recovery boundary it needs. No manual save is required.
            </p>

            {previousCheckpoint ? (
              <article className="relative mt-7 overflow-hidden rounded-2xl bg-[#171713] p-5 text-white dark:bg-[#e8e8df] dark:text-[#171713]">
                <div className="absolute -right-10 -top-14 h-36 w-36 rounded-full border border-white/10 dark:border-black/10" aria-hidden="true" />
                <div className="relative flex flex-wrap items-center justify-between gap-3">
                  <p className="text-xs font-semibold text-white/65 dark:text-black/55">Earlier saved context · another task</p>
                  {earlierBoundary.occurred_at ? (
                    <time dateTime={earlierBoundary.occurred_at} className="text-xs font-semibold text-white/65 dark:text-black/55">
                      {formatBoundaryTime(earlierBoundary.occurred_at)}
                    </time>
                  ) : null}
                </div>
                <p className="relative mt-4 max-w-2xl text-lg font-semibold leading-7 tracking-[-0.02em]">
                  {earlierGoal || "Goal was not captured"}
                </p>
                <p className="relative mt-3 text-xs leading-5 text-white/60 dark:text-black/55">
                  It is kept in history and is not being used as the current task’s next action.
                </p>
                <Link to="/app/runs" className="group relative mt-5 inline-flex min-h-11 items-center gap-2 text-xs font-semibold">
                  View recovery history <ArrowRight className="h-3.5 w-3.5 transition-transform group-hover:translate-x-1" />
                </Link>
              </article>
            ) : null}
          </div>

          <div className="border-t border-[#deded5] dark:border-[#292925] lg:border-l lg:border-t-0">
            <ProjectMemorySummary memory={memory} loading={memoryLoading} error={memoryError} />
          </div>
        </div>
        {error ? <p role="alert" className="border-t border-red-200 px-6 py-3 text-xs font-semibold text-red-600 sm:px-8">{error.message}</p> : null}
      </section>
    );
  }

  const sections = checkpoint.sections || {};
  const goal = cleanRecoveryText(sections.goal?.[0]?.statement || "Goal was not captured.");
  const nextAction = sections.exact_next_action?.[0]?.statement || "Exact next action is missing.";
  const currentness = checkpoint.currentness || {};
  const boundary = checkpoint.boundary || {};
  const recoveryTitle = checkpoint.trigger === "compaction"
    ? "Saved before context was condensed"
    : "Saved from the task’s working context";
  const superseded = currentness.state === "superseded";
  const historical = currentness.state === "historical";
  const unknownBoundary = !currentness.state || currentness.state === "unknown";
  const needsReview = currentness.state !== "captured";
  const recoveryTimestamp = boundary.occurred_at || boundary.captured_at;
  const recoveryHeading = superseded
    ? "Earlier recovery point"
    : historical
      ? "Older recovery point"
      : unknownBoundary
        ? "Saved recovery point"
        : "Latest recovery point";
  const recoveryDetail = superseded
    ? `${recoveryTitle}. Newer task activity remains separate.`
    : historical
      ? `${recoveryTitle}. It is older than 24 hours; age alone does not imply newer activity.`
      : unknownBoundary
        ? `${recoveryTitle}. Its boundary time could not be verified.`
        : `${recoveryTitle}. It remains separate from live activity.`;
  const snapshotLabel = superseded
    ? "Earlier snapshot"
    : historical
      ? "Older snapshot"
      : unknownBoundary
        ? "Boundary time unknown"
        : "Recent snapshot";
  const boundaryNotice = superseded
    ? "Earlier snapshot · newer task activity exists"
    : historical
      ? "Older snapshot · reconciled automatically on Continue"
      : "Saved snapshot · boundary time unavailable";
  return (
    <section id="continuity-checkpoint" className="app-surface ce-recovery-checkpoint relative scroll-mt-24">
      <header className="flex flex-col gap-4 border-b border-[#deded5] px-6 py-6 dark:border-[#292925] sm:flex-row sm:items-start sm:justify-between sm:px-8 sm:py-7">
        <div className="min-w-0">
          <PanelLabel icon={History}>Saved context</PanelLabel>
          <h2 className="mt-3 text-2xl font-semibold tracking-[-0.04em] text-[#171713] dark:text-white sm:text-[1.75rem]">
            {recoveryHeading}
          </h2>
          <p className="mt-2 text-sm leading-6 text-[#68685f] dark:text-[#aaa9a0]">{recoveryDetail}</p>
        </div>
        <div className="flex shrink-0 flex-col items-start gap-2 sm:items-end">
          <span className={`rounded-full px-3 py-1.5 text-xs font-semibold ${
            needsReview
              ? "bg-amber-100 text-amber-900 dark:bg-amber-950/50 dark:text-amber-200"
              : "bg-[#edf3d7] text-[#617324] dark:bg-[#d9ff68]/10 dark:text-[#d9ff68]"
          }`}>
            {snapshotLabel}
          </span>
          {recoveryTimestamp ? (
            <time dateTime={recoveryTimestamp} className="text-xs font-semibold text-[#77776e] dark:text-[#aaa9a0]">
              {formatBoundaryTime(recoveryTimestamp)}
            </time>
          ) : null}
        </div>
      </header>

      <div className="grid lg:grid-cols-[minmax(0,1.2fr)_minmax(20rem,.8fr)]">
        <section className="px-6 py-7 sm:px-8 sm:py-8" aria-labelledby={`checkpoint-goal-${checkpoint.id}`}>
          <p className="text-xs font-semibold text-[#77776e] dark:text-[#aaa9a0]">Goal at this point</p>
          <h3 id={`checkpoint-goal-${checkpoint.id}`} className="mt-3 max-w-[58ch] text-xl font-semibold leading-8 tracking-[-0.025em] text-[#171713] [overflow-wrap:anywhere] dark:text-white sm:text-[1.45rem]">
            {prepareTaskCandidate(goal) || "Goal was not captured"}
          </h3>

          <div className="mt-7 rounded-2xl border border-[#deded5] bg-[#f6f6f0] p-5 dark:border-[#30302b] dark:bg-[#11110f] sm:p-6">
            <p className="text-xs font-semibold text-[#77776e] dark:text-[#aaa9a0]">Exact next action</p>
            <p className="mt-3 max-w-[65ch] text-base font-semibold leading-7 tracking-[-0.012em] text-[#171713] [overflow-wrap:anywhere] dark:text-white sm:text-lg">
              {prepareTaskCandidate(nextAction) || "Exact next action was not captured"}
            </p>
          </div>

          {needsReview ? (
            <div className="mt-5 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-amber-950 dark:border-amber-900/70 dark:bg-amber-950/30 dark:text-amber-100">
              <p className="text-xs font-semibold leading-5">{boundaryNotice}</p>
            </div>
          ) : null}
        </section>

        <aside className="flex flex-col border-t border-[#deded5] dark:border-[#292925] lg:border-l lg:border-t-0">
          <ProjectMemorySummary memory={memory} loading={memoryLoading} error={memoryError} />
          <div className="mt-auto border-t border-[#deded5] px-6 py-6 dark:border-[#292925] sm:px-8 lg:px-7">
            <p className="text-xs leading-5 text-[#77776e] dark:text-[#aaa9a0]">
              Continue reconciles this snapshot against current repository state and runs the target agent automatically.
            </p>
          </div>
        </aside>
      </div>

      {sessionCompactions?.length ? (
        <SessionCompactions checkpoints={sessionCompactions} displayedCheckpointId={checkpoint.id} />
      ) : null}
      {error ? <p role="alert" className="border-t border-red-200 px-6 py-3 text-xs font-semibold text-red-600 sm:px-8">{error.message}</p> : null}
    </section>
  );
}

function ProjectMemorySummary({ memory, loading, error }) {
  const totals = memory?.totals || {};
  const currentGoal = prepareTaskCandidate(memory?.current_goal?.title);
  const unavailable = Boolean(error && !memory);
  const stats = [
    { label: "Trusted current", value: Number(totals.active || 0) },
    { label: "Needs review", value: Number(totals.needs_review || 0) },
    { label: "History", value: Number(totals.history || 0) },
  ];

  return (
    <section className="px-6 py-6 sm:px-8 sm:py-7 lg:px-7" aria-labelledby="now-project-memory-heading">
      <PanelLabel icon={Layers3}>Current project memory</PanelLabel>
      <h3 id="now-project-memory-heading" className="mt-3 text-lg font-semibold tracking-[-0.025em] text-[#171713] dark:text-white">
        What the project remembers now
      </h3>
      <p className="mt-2 text-xs leading-5 text-[#77776e] dark:text-[#aaa9a0]">
        This is current project truth, kept separate from the saved snapshot.
      </p>

      {loading && !memory ? (
        <p className="mt-5 text-xs font-semibold text-[#77776e] dark:text-[#aaa9a0]">Loading memory summary…</p>
      ) : unavailable ? (
        <div className="mt-5 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-amber-950 dark:border-amber-900/70 dark:bg-amber-950/30 dark:text-amber-100">
          <p className="text-xs font-semibold">Memory summary unavailable</p>
          <p className="mt-1 text-[11px] leading-5 opacity-75">Current memory could not be loaded, so no totals are shown.</p>
        </div>
      ) : (
        <>
          <dl className="mt-5 grid grid-cols-3 overflow-hidden rounded-xl border border-[#deded5] bg-[#f6f6f0] dark:border-[#30302b] dark:bg-[#11110f]">
            {stats.map((stat) => (
              <div key={stat.label} className="flex flex-col border-r border-[#deded5] px-3 py-3 last:border-r-0 dark:border-[#30302b]">
                <dt className="order-2 mt-1 text-[11px] font-medium leading-4 text-[#77776e] dark:text-[#aaa9a0]">{stat.label}</dt>
                <dd className="order-1 text-lg font-semibold tracking-[-0.03em] text-[#171713] dark:text-white">{stat.value}</dd>
              </div>
            ))}
          </dl>
          {error ? (
            <p className="mt-3 text-[11px] font-medium leading-5 text-amber-700 dark:text-amber-200">
              These are the last loaded totals; the latest refresh failed.
            </p>
          ) : null}
          {currentGoal ? (
            <div className="mt-4 border-l-2 border-[#9dbc47] pl-3">
              <p className="text-[11px] font-semibold text-[#77776e] dark:text-[#aaa9a0]">Current focus</p>
              <p className="mt-1 line-clamp-2 text-xs font-semibold leading-5 text-[#383832] dark:text-[#deded6]" title={currentGoal}>{currentGoal}</p>
            </div>
          ) : null}
        </>
      )}

      <Link to="/app/memory" className="group mt-5 inline-flex min-h-11 items-center gap-2 text-xs font-semibold text-[#171713] dark:text-[#d9ff68]">
        Open project memory <ArrowRight className="h-3.5 w-3.5 transition-transform group-hover:translate-x-1" />
      </Link>
    </section>
  );
}

function SessionCompactions({ checkpoints, displayedCheckpointId }) {
  return (
    <section className="relative border-t border-[#deded5] dark:border-[#292925]">
      <div className="flex flex-wrap items-start justify-between gap-3 px-6 py-6 sm:px-8">
        <div>
          <PanelLabel icon={History}>Recovery history</PanelLabel>
          <p className="mt-2 text-xs leading-5 text-[#68685f] dark:text-[#aaa9a0]">Each dated card preserves an earlier handoff state. Newer work remains separate.</p>
        </div>
        <div className="flex items-center gap-3">
          <span className="rounded-full bg-[#f0f0e9] px-3 py-1.5 text-xs font-semibold text-[#68685f] dark:bg-white/[0.06] dark:text-[#aaa9a0]">
            {checkpoints.length} saved
          </span>
          <Link to="/app/runs" className="inline-flex min-h-11 items-center text-xs font-semibold underline decoration-[#aaa99f] underline-offset-4">View all</Link>
        </div>
      </div>
      <ol className="grid gap-3 border-t border-[#deded5] px-6 py-6 dark:border-[#292925] sm:px-8 md:grid-cols-2">
        {checkpoints.map((item, index) => {
          const itemBoundary = item.boundary || {};
          const itemGoal = prepareTaskCandidate(cleanRecoveryText(item.sections?.goal?.[0]?.statement))
            || "Goal was not captured";
          const displayed = item.id === displayedCheckpointId;
          return (
            <li key={item.id} className={index % 2 ? "md:pt-4" : ""}>
              <article
                aria-current={displayed ? "true" : undefined}
                className={`relative h-full overflow-hidden rounded-2xl border p-5 shadow-[0_12px_32px_rgba(23,23,19,0.05)] ${
                  displayed
                    ? "border-[#171713] bg-[#171713] text-white dark:border-white dark:bg-white dark:text-black"
                    : "border-[#deded5] bg-[#f8f8f3] text-[#171713] dark:border-[#30302b] dark:bg-[#11110f] dark:text-white"
                }`}
              >
                <span className={`absolute inset-x-0 top-0 h-1 ${displayed ? "bg-[#d9ff68] dark:bg-[#68721f]" : "bg-[#cfd7ad] dark:bg-[#637132]"}`} aria-hidden="true" />
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <time dateTime={itemBoundary.occurred_at || undefined} className={`text-xs font-semibold ${displayed ? "opacity-70" : "text-[#77776e] dark:text-[#aaa9a0]"}`}>
                  {itemBoundary.occurred_at ? formatBoundaryTime(itemBoundary.occurred_at) : "Time unavailable"}
                  </time>
                  <span className={`rounded-full px-2.5 py-1 text-[11px] font-semibold ${displayed ? "bg-white/10 dark:bg-black/10" : "bg-white dark:bg-black/20"}`}>
                    {displayed ? "In view" : "Earlier"}
                  </span>
                </div>
                <p className="mt-4 line-clamp-3 text-sm font-semibold leading-6" title={itemGoal}>{itemGoal}</p>
              </article>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

function TaskStatusRibbon({ activity, checkpoint, loading = false, error = false }) {
  const evidence = loading
    ? {
        value: "Loading evidence",
        detail: "Reading current activity",
        tone: "text-[#d9ff68]",
      }
    : error
      ? {
          value: "Evidence unavailable",
          detail: "Current activity could not be loaded",
          tone: "text-red-200",
        }
      : activityEvidenceStatus(activity);
  const updatedAt = activity?.updated_at || checkpoint?.boundary?.captured_at;
  const freshnessValue = loading
    ? "Checking freshness"
    : error
      ? "Time unavailable"
      : updatedAt
        ? `Updated ${formatTimeAgo(updatedAt)}`
        : "Time unavailable";
  const freshnessDetail = loading
    ? "Loading the latest available record"
    : error
      ? "Retry current activity"
      : activity?.live
        ? "Live session activity"
        : "Latest available record";

  return (
    <dl className="relative grid border-t border-white/10 bg-black/10 sm:grid-cols-2" aria-label="Observed work status">
      <StatusRibbonItem
        label="Evidence"
        value={evidence.value}
        detail={evidence.detail}
        tone={evidence.tone}
      />
      <StatusRibbonItem
        label="Freshness"
        value={freshnessValue}
        detail={freshnessDetail}
        tone="text-white"
      />
    </dl>
  );
}

function StatusRibbonItem({ label, value, detail, tone }) {
  return (
    <div className="border-b border-white/10 px-5 py-4 last:border-b-0 sm:border-b-0 sm:border-r sm:px-7 sm:last:border-r-0 lg:px-9">
      <dt className="text-[9px] font-bold uppercase tracking-[0.17em] text-[#85857c]">{label}</dt>
      <dd className={`mt-1.5 text-sm font-semibold ${tone}`}>{value}</dd>
      <dd className="mt-1 text-[10px] leading-4 text-[#929289]">{detail}</dd>
    </div>
  );
}

function ContinuationContractItem({ label, value }) {
  return (
    <div className="min-w-0 bg-[#171713]/95 px-3.5 py-3">
      <dt className="text-[8px] font-black uppercase tracking-[0.16em] text-[#85857c]">
        {label}
      </dt>
      <dd className="mt-1.5 truncate text-[11px] font-semibold text-[#e7e7df]" title={value}>
        {value}
      </dd>
    </div>
  );
}

function OverviewLoadCard({ icon, label, title, message, error = false }) {
  const Icon = icon;
  return (
    <article className="app-surface relative overflow-hidden p-6 sm:p-7 xl:p-8" aria-busy={error ? undefined : "true"}>
      <PanelLabel icon={Icon}>{label}</PanelLabel>
      <h2 className="mt-6 text-2xl font-semibold tracking-[-0.025em] text-[#171713] dark:text-white">{title}</h2>
      <p className={`mt-6 text-sm font-semibold leading-6 ${
        error ? "text-red-700 dark:text-red-200" : "text-[#68685f] dark:text-[#aaa9a0]"
      }`}>
        {message}
      </p>
      {!error ? (
        <div className="mt-6 space-y-3" aria-hidden="true">
          <span className="block h-3 w-full animate-pulse rounded-full bg-[#e8e8e0] dark:bg-white/[0.07]" />
          <span className="block h-3 w-5/6 animate-pulse rounded-full bg-[#e8e8e0] dark:bg-white/[0.07]" />
          <span className="block h-3 w-2/3 animate-pulse rounded-full bg-[#e8e8e0] dark:bg-white/[0.07]" />
        </div>
      ) : null}
    </article>
  );
}

function ObservedWork({ activity, loading = false, error = false }) {
  if (loading || error) {
    return (
      <OverviewLoadCard
        icon={History}
        label="Observed work"
        title="Progress"
        message={error ? "Current progress could not be loaded." : "Loading observed progress…"}
        error={error}
      />
    );
  }
  if (!activity) {
    return (
      <article className="app-surface relative overflow-hidden p-6 sm:p-7 xl:p-8">
        <PanelLabel icon={History}>Observed work</PanelLabel>
        <h2 className="mt-6 text-2xl font-semibold tracking-[-0.025em] text-[#171713] dark:text-white">Progress</h2>
        <p className="mt-6 text-base font-semibold leading-7 text-[#171713] dark:text-white">No agent progress observed yet.</p>
        <p className="mt-2 text-sm leading-6 text-[#68685f] dark:text-[#aaa9a0]">
          Import a Codex, Claude Code, or OpenCode session to make its latest update visible here.
        </p>
        <Link to="/app/connectors" className="group mt-7 inline-flex min-h-11 items-center gap-1.5 text-xs font-semibold text-[#171713] dark:text-[#d9ff68]">
          Connect agent sessions <ArrowRight className="h-3 w-3 transition-transform group-hover:translate-x-0.5" />
        </Link>
      </article>
    );
  }

  const observedRun = activity.evidence_level === "observed_run";
  const checkpointBoundary = activity.evidence_level === "checkpoint_boundary";
  const unassigned = activity.evidence_level === "session_unassigned";
  const changedFiles = activity.changed_files || [];
  const latestUpdate = displayActivityText(activity.latest_update);
  const detailUrl = activity.source_card_id
    ? explainCardUrl(activity.source_card_id)
    : "/app/runs";

  return (
    <article className="app-surface relative overflow-hidden p-6 sm:p-7 xl:p-8">
      <div className="relative flex flex-wrap items-center justify-between gap-3">
        <PanelLabel icon={activity.live ? PlayCircle : History}>Observed work</PanelLabel>
        <ActivityBadge activity={activity} />
      </div>

      <h2 className="relative mt-6 text-2xl font-semibold tracking-[-0.025em] text-[#171713] dark:text-white">Progress</h2>

      {latestUpdate ? (
        <p className="relative mt-6 text-base font-semibold leading-7 tracking-[-0.012em] text-[#171713] [overflow-wrap:anywhere] dark:text-white">
          {latestUpdate}
        </p>
      ) : null}

      {activity.rationale ? (
        <div className="relative mt-5 rounded-2xl bg-[#f1f1e9] px-4 py-4 dark:bg-white/[0.035]">
          <p className="text-[11px] font-semibold text-[#85857c]">
            {observedRun ? "Recorded reason" : "Stated reason"}
          </p>
          <p className="mt-2 text-sm leading-6 text-[#5f5f57] [overflow-wrap:anywhere] dark:text-[#bdbdb4]">{cleanDisplayText(activity.rationale)}</p>
        </div>
      ) : null}

      <div className="relative mt-7 flex flex-wrap gap-2">
        <Metric icon={Bot} label={agentLabel(activity)} />
        {activity.branch ? <Metric icon={GitBranch} label={activity.branch} /> : null}
        {observedRun && changedFiles.length ? <Metric icon={FileCode2} label={`${changedFiles.length} file${changedFiles.length === 1 ? "" : "s"} changed`} /> : null}
        <Metric icon={Clock3} label={activity.updated_at ? `Updated ${formatTimeAgo(activity.updated_at)}` : "Update time unavailable"} />
      </div>

      <div className="relative mt-7 flex flex-col gap-4 border-t border-[#e5e5dd] pt-5 dark:border-[#292925]">
        <p className="text-xs font-medium leading-5 text-[#85857c]">
          {observedRun
            ? "Changes and checks come from recorded run evidence."
            : checkpointBoundary
              ? "This work is scoped to the same provider, session, and event boundary as the checkpoint above."
            : unassigned
              ? "This transcript is visible for review, but is not yet counted as project truth."
              : "This update comes from an imported transcript; repository changes were not observed."}
        </p>
        <Link to={detailUrl} className="group inline-flex min-h-11 w-fit items-center gap-1.5 text-xs font-semibold text-[#171713] dark:text-[#d9ff68]">
          {activity.source_card_id ? "Explain session evidence" : checkpointBoundary ? "Inspect checkpoint evidence" : "Inspect run evidence"}
          <ArrowRight className="h-3 w-3 transition-transform group-hover:translate-x-0.5" />
        </Link>
      </div>
    </article>
  );
}

function ObservedResult({
  activity,
  checkpoint,
  attentionCount,
  loading = false,
  error = false,
}) {
  if (loading || error) {
    return (
      <OverviewLoadCard
        icon={CheckCircle2}
        label="Evidence status"
        title="Verification"
        message={error ? "Current verification could not be loaded." : "Loading verification evidence…"}
        error={error}
      />
    );
  }
  const outcome = activity?.outcome || null;
  const verification = activity?.verification || {};
  const changedFiles = activity?.changed_files || [];
  const trust = activityEvidenceStatus(activity);
  const checkpointVerified = checkpoint?.verification?.status === "verified";

  return (
    <article className="app-surface p-6 sm:p-7 xl:p-8">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <PanelLabel icon={CheckCircle2}>Evidence status</PanelLabel>
        <span className={`rounded-full bg-[#f1f1ec] px-3 py-1.5 text-[11px] font-semibold dark:bg-white/[0.06] ${trust.panelTone}`}>
          {trust.value}
        </span>
      </div>
      <h2 className="mt-6 text-2xl font-semibold tracking-[-0.025em] text-[#171713] dark:text-white">Verification</h2>
      {outcome ? (
        <>
          <p className="mt-6 text-base font-semibold leading-7 tracking-[-0.012em] text-[#171713] [overflow-wrap:anywhere] dark:text-white">
            {cleanDisplayText(outcome.summary) || "A terminal outcome was recorded."}
          </p>
          <div className="mt-6 space-y-3 border-t border-[#e5e5dd] pt-5 dark:border-[#292925]">
            {changedFiles.length ? <EvidenceRow label="Changed" value={`${changedFiles.length} file${changedFiles.length === 1 ? "" : "s"}`} /> : null}
            {verification.observed ? <EvidenceRow label="Checks" value={verificationLabel(verification)} /> : null}
            <EvidenceRow label="Observed" value={formatTimeAgo(outcome.observed_at || activity?.updated_at)} />
          </div>
        </>
      ) : (
        <>
          <p className="mt-6 text-base font-semibold leading-7 text-[#171713] dark:text-white">
            {activity?.evidence_level?.startsWith("session_")
              ? "Agent-reported progress is not repository-verified."
              : "No verified result captured."}
          </p>
          <p className="mt-2 text-sm leading-6 text-[#68685f] dark:text-[#aaa9a0]">
            {activity?.evidence_level?.startsWith("session_")
              ? "The session contains an agent update, but no linked repository result or check evidence."
              : "A result will appear after an observed run records its outcome and checks."}
          </p>
          {verification.observed ? (
            <div className="mt-6 border-t border-[#e5e5dd] pt-5 dark:border-[#292925]">
              <EvidenceRow label="Checks so far" value={verificationLabel(verification)} />
            </div>
          ) : null}
        </>
      )}
      {checkpointVerified ? (
        <p className="mt-6 border-t border-[#e5e5dd] pt-5 text-xs leading-5 text-[#68685f] dark:border-[#292925] dark:text-[#aaa9a0]">
          The saved recovery point is verified separately. That does not verify newer activity.
        </p>
      ) : null}
      <div className="mt-7 flex flex-col gap-2 border-t border-[#e5e5dd] pt-5 dark:border-[#292925]">
        <Link to="/app/explain" className="group inline-flex min-h-11 w-fit items-center gap-1.5 text-xs font-semibold text-[#171713] dark:text-[#d9ff68]">
          Explain evidence <ArrowRight className="h-3 w-3 transition-transform group-hover:translate-x-0.5" />
        </Link>
        {attentionCount ? (
          <span className="text-[10px] font-semibold text-amber-700 dark:text-amber-300">
            {attentionCount} item{attentionCount === 1 ? "" : "s"} need attention
          </span>
        ) : (
          <span className="text-[10px] text-[#85857c]">
            No additional evidence alert. Provider readiness and run blockers appear above.
          </span>
        )}
      </div>
    </article>
  );
}

function ContinuationSummary({
  checkpoint,
  latestSession,
  loading = false,
  error = false,
}) {
  if (loading || error) {
    return (
      <OverviewLoadCard
        icon={Clipboard}
        label="Continuation"
        title="Exact next action"
        message={error ? "Current continuation could not be loaded." : "Loading the safest available continuation…"}
        error={error}
      />
    );
  }
  const currentness = checkpoint?.currentness?.state;
  const superseded = currentness === "superseded";
  const historical = currentness === "historical";
  const unknownBoundary = Boolean(checkpoint && (!currentness || currentness === "unknown"));
  const needsReview = Boolean(checkpoint && currentness !== "captured");
  const savedNextAction = prepareTaskCandidate(checkpoint?.sections?.exact_next_action?.[0]?.statement);
  const nextAction = savedNextAction
    || (latestSession
      ? "Continue will resolve the latest exact next action from the linked session."
      : "Choose or import an agent task before continuing.");

  return (
    <article className="app-surface p-6 sm:p-7 xl:p-8">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <PanelLabel icon={Clipboard}>Continuation</PanelLabel>
        {checkpoint ? (
          <span className={`rounded-full px-3 py-1.5 text-[11px] font-semibold ${needsReview ? "bg-amber-100 text-amber-800 dark:bg-amber-950/50 dark:text-amber-200" : "bg-[#edf3d7] text-[#617324] dark:bg-[#d9ff68]/10 dark:text-[#d9ff68]"}`}>
            {superseded
              ? "Earlier saved state"
              : historical
                ? "Older saved state"
                : unknownBoundary
                  ? "Saved state · time unknown"
                  : "Saved state"}
          </span>
        ) : null}
      </div>
      <h2 className="mt-6 text-2xl font-semibold tracking-[-0.025em] text-[#171713] dark:text-white">Exact next action</h2>
      <p className="mt-6 text-base font-semibold leading-7 tracking-[-0.012em] text-[#171713] [overflow-wrap:anywhere] dark:text-white">
        {nextAction}
      </p>
      <p className="mt-4 text-xs leading-5 text-[#68685f] dark:text-[#aaa9a0]">
        {checkpoint
          ? superseded
            ? "This instruction belongs to an earlier recovery point; newer task activity is not merged into it."
            : historical
              ? "This instruction was saved more than 24 hours ago. Its age does not prove that newer task activity exists."
              : unknownBoundary
                ? "This instruction is saved, but its boundary time is unknown. Continue reconciles it automatically."
                : "This instruction was saved at the recovery boundary and remains separate from live activity."
          : latestSession
            ? "No manual checkpoint is needed; continuation resolves and captures current state automatically."
            : "No task continuation is available yet."}
      </p>
      <div className="mt-7 border-t border-[#e5e5dd] pt-5 dark:border-[#292925]">
        {checkpoint ? (
          <a href="#continuity-checkpoint" className="group inline-flex min-h-11 items-center gap-1.5 text-xs font-semibold text-[#171713] dark:text-[#d9ff68]">
            View saved context
            <ArrowRight className="h-3 w-3 transition-transform group-hover:translate-x-0.5" />
          </a>
        ) : !latestSession ? (
          <Link to="/app/library" className="group inline-flex min-h-11 items-center gap-1.5 text-xs font-semibold text-[#171713] dark:text-[#d9ff68]">
            Choose work <ArrowRight className="h-3 w-3 transition-transform group-hover:translate-x-0.5" />
          </Link>
        ) : (
          <p className="text-xs font-semibold text-[#77776e] dark:text-[#aaa9a0]">Captured automatically on Continue</p>
        )}
      </div>
    </article>
  );
}

function AttentionPanel({ cards, loading = false, error = false }) {
  return (
    <section className="app-surface p-5 sm:p-6" aria-busy={loading ? "true" : undefined}>
      <div className="flex items-center justify-between gap-3">
        <PanelLabel icon={ShieldAlert}>Needs attention</PanelLabel>
        {!loading && !error ? (
          <span className="rounded-full bg-amber-100/80 px-2.5 py-1 text-[9px] font-bold text-amber-800 dark:bg-amber-950/50 dark:text-amber-200">
            {cards.length} evidence alert{cards.length === 1 ? "" : "s"}
          </span>
        ) : null}
      </div>
      {loading ? (
        <div className="mt-4 space-y-3" role="status">
          <p className="text-sm leading-6 text-[#68685f] dark:text-[#aaa9a0]">Loading attention signals…</p>
          <span className="block h-3 w-3/4 animate-pulse rounded-full bg-[#e8e8e0] dark:bg-white/[0.07]" aria-hidden="true" />
        </div>
      ) : error ? (
        <p className="mt-4 text-sm leading-6 text-red-700 dark:text-red-200">
          Attention signals are unavailable until current activity loads.
        </p>
      ) : cards.length ? (
        <div className="mt-4 grid gap-2.5 md:grid-cols-2">
          {cards.map((card) => (
            <Link
              key={card.id}
              to={explainCardUrl(card.id)}
              className="group flex min-h-[116px] flex-col rounded-xl border border-[#e1e1d9] bg-white/35 p-4 transition-all duration-200 hover:-translate-y-0.5 hover:border-[#b9b9af] hover:bg-white hover:shadow-[0_7px_20px_rgba(23,23,19,0.05)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[#95b52f]/45 dark:border-[#2d2d28] dark:bg-white/[0.015] dark:hover:border-[#57574f] dark:hover:bg-white/[0.035] dark:hover:shadow-none"
            >
              <div className="flex items-start justify-between gap-3">
                <p className="text-sm font-semibold leading-5 text-[#171713] dark:text-white">{cleanDisplayText(card.title)}</p>
                <span className="shrink-0 rounded-full bg-amber-50 px-2 py-1 text-[8px] font-bold uppercase tracking-[0.1em] text-amber-700 dark:bg-amber-400/10 dark:text-amber-200">
                  {attentionLabel(card)}
                </span>
              </div>
              <p className="mt-2 line-clamp-2 text-xs leading-5 text-[#68685f] dark:text-[#aaa9a0]">
                {distinctCardDetail(card, "Open the evidence record for the latest observed detail.")}
              </p>
              <span className="mt-auto flex items-center gap-1.5 pt-3 text-[10px] font-bold text-[#77776e] transition-colors group-hover:text-[#171713] dark:group-hover:text-[#d9ff68]">
                Explain evidence <ArrowRight className="h-3 w-3 transition-transform group-hover:translate-x-0.5" />
              </span>
            </Link>
          ))}
        </div>
      ) : (
        <p className="mt-4 text-sm leading-6 text-[#68685f] dark:text-[#aaa9a0]">
          No additional task-evidence alert is visible. Provider readiness and
          continuation blockers are reported in the harness cards above.
        </p>
      )}
    </section>
  );
}

function RecentSessions({ cards }) {
  return (
    <section className="app-surface p-5 sm:p-6">
      <div className="flex items-center justify-between gap-3">
        <PanelLabel icon={History}>Recent coding sessions</PanelLabel>
        <Link to="/app/explain" className="text-[10px] font-bold text-[#77776e] underline-offset-4 hover:underline dark:text-[#aaa9a0]">See all evidence</Link>
      </div>
      <div className="mt-4 divide-y divide-[#e5e5dd] dark:divide-[#292925]">
        {cards.map((card) => {
          const identity = sessionIdentity(card);
          return (
            <Link key={card.id} to={explainCardUrl(card.id)} className="group flex items-center gap-3 py-3.5 first:pt-1 last:pb-1">
              <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-[#efefe7] text-[#68685f] dark:bg-[#252521] dark:text-[#c7c7bd]"><Bot className="h-4 w-4" /></span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-semibold text-[#171713] dark:text-white">{identity.title}</span>
                <span className="mt-1 block truncate text-[10px] font-medium text-[#85857c]">{identity.source} · {card.updated_at ? formatTimeAgo(card.updated_at) : identity.detail}</span>
              </span>
              <ArrowRight className="h-3.5 w-3.5 shrink-0 text-[#aaa99f] transition-transform group-hover:translate-x-0.5 group-hover:text-[#171713] dark:group-hover:text-[#d9ff68]" />
            </Link>
          );
        })}
      </div>
    </section>
  );
}

function UnassignedSessions({ count, cardId }) {
  return (
    <div className="flex flex-col justify-between gap-3 rounded-2xl border border-amber-200/80 bg-amber-50/80 px-4 py-3.5 text-amber-950 shadow-[0_1px_2px_rgba(120,53,15,0.04)] dark:border-amber-900/60 dark:bg-amber-950/25 dark:text-amber-100 sm:flex-row sm:items-center">
      <div className="flex items-start gap-3">
        <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-amber-100 dark:bg-amber-900/50"><ShieldAlert className="h-3.5 w-3.5" /></span>
        <div>
          <p className="text-xs font-bold">{count} AI session{count === 1 ? " is" : "s are"} waiting for project assignment</p>
          <p className="mt-0.5 text-[11px] leading-5 opacity-75">It stays out of project health and compiled truth until its repository relevance is confirmed.</p>
        </div>
      </div>
      <Link to={cardId ? explainCardUrl(cardId) : "/app/explain"} className="shrink-0 rounded-lg px-2 py-1 text-xs font-bold underline decoration-amber-400 underline-offset-4 transition hover:bg-amber-100/70 dark:hover:bg-amber-900/30">Review session</Link>
    </div>
  );
}

function PanelLabel({ icon: Icon, children }) {
  return (
    <div className="flex items-center gap-2 text-[10px] font-bold uppercase tracking-[0.16em] text-[#77776e] dark:text-[#929289]">
      <Icon className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
      {children}
    </div>
  );
}

function activityEvidenceStatus(activity) {
  if (!activity) {
    return {
      value: "No evidence",
      detail: "Nothing observed or reported",
      tone: "text-[#c5c5bc]",
      panelTone: "text-[#68685f] dark:text-[#bdbdb4]",
    };
  }
  if (activity.evidence_level === "observed_run") {
    return {
      value: "Observed run",
      detail: "Repository and run evidence",
      tone: "text-[#d9ff68]",
      panelTone: "text-[#617324] dark:text-[#d9ff68]",
    };
  }
  if (activity.evidence_level === "checkpoint_boundary") {
    return {
      value: "Saved boundary",
      detail: "Immutable recovery evidence",
      tone: "text-sky-200",
      panelTone: "text-sky-700 dark:text-sky-200",
    };
  }
  if (activity.evidence_level === "session_unassigned") {
    return {
      value: "Needs assignment",
      detail: "Excluded from project truth",
      tone: "text-amber-200",
      panelTone: "text-amber-700 dark:text-amber-200",
    };
  }
  return {
    value: "Agent-reported",
    detail: "Imported session claim",
    tone: "text-sky-200",
    panelTone: "text-sky-700 dark:text-sky-200",
  };
}

function ActivityBadge({ activity }) {
  const label = activity.live
    ? "Live"
    : activity.evidence_level === "observed_run"
      ? "Observed run"
      : activity.evidence_level === "session_unassigned"
        ? "Needs assignment"
        : activity.refreshable ? "Auto-updating" : "Imported session";
  return (
    <span className="rounded-full border border-[#deded8] bg-[#f5f5f2] px-2.5 py-1 text-[9px] font-bold text-[#68685f] dark:border-[#292929] dark:bg-[#111111] dark:text-[#bdbdb4]">
      {label}
    </span>
  );
}

function EvidenceRow({ label, value }) {
  return (
    <div className="flex items-center justify-between gap-4 text-xs">
      <span className="font-medium text-[#85857c]">{label}</span>
      <span className="text-right font-bold text-[#383832] dark:text-[#e0e0d8]">{value}</span>
    </div>
  );
}

function Metric({ icon: Icon, label }) {
  return <span className="status-chip"><Icon className="h-3 w-3" />{label}</span>;
}

function agentLabel(activity) {
  const rawTool = cleanDisplayText(activity.tool || "Agent").toLowerCase();
  const tool = {
    codex: "Codex",
    claude: "Claude Code",
    claude_code: "Claude Code",
    opencode: "OpenCode",
    agent: "Agent",
  }[rawTool] || cleanDisplayText(activity.tool || "Agent");
  const model = cleanDisplayText(activity.model);
  return model ? `${tool} · ${model}` : tool;
}

function verificationLabel(verification = {}) {
  const observed = Number(verification.observed || 0);
  const passed = Number(verification.passed || 0);
  const failed = Number(verification.failed || 0);
  if (failed) return `${passed} passed · ${failed} failed`;
  return `${passed}/${observed} passed`;
}

const CONTINUATION_PHASES = [
  "Resolving the real task",
  "Reconciling repository state",
  "Running a fresh target agent",
  "Verifying the observed outcome",
];

function resolvedContinuationProviders(query) {
  const supplied = Array.isArray(query.data?.providers) ? query.data.providers : [];
  const byProvider = new Map(
    supplied.map((item) => [normalizeProvider(item.provider), item]),
  );
  return HARNESS_ORDER.map((provider) => {
    const meta = harnessMeta(provider);
    const suppliedProvider = byProvider.get(provider);
    if (suppliedProvider) {
      return {
        ...suppliedProvider,
        provider,
        name: suppliedProvider.name || meta.name,
        status: suppliedProvider.status || (suppliedProvider.ready ? "ready" : "unavailable"),
        ready: suppliedProvider.ready === true,
        message: preserveContinuationText(suppliedProvider.message),
        action: preserveContinuationText(suppliedProvider.action),
      };
    }
    if (query.isLoading) {
      return {
        provider,
        name: meta.name,
        status: "checking",
        ready: false,
        code: "provider_readiness_loading",
        message: "Checking local installation and authentication.",
        action: "",
      };
    }
    if (query.isError) {
      return {
        provider,
        name: meta.name,
        status: "unavailable",
        ready: false,
        code: "provider_readiness_unavailable",
        message: preserveContinuationText(query.error?.message)
          || "Execution readiness could not be loaded.",
        action: "Retry provider readiness before continuing.",
      };
    }
    return {
      provider,
      name: meta.name,
      status: "unavailable",
      ready: false,
      code: "provider_readiness_missing",
      message: `${meta.name} execution readiness was not reported.`,
      action: "Refresh provider readiness before continuing.",
    };
  });
}

function ContinuationWorkflowStatus({ state, result, blocker }) {
  if (state === "idle") return null;

  if (state === "running") {
    return (
      <div
        role="status"
        aria-busy="true"
        className="rounded-xl border border-[#d9ff68]/25 bg-[#d9ff68]/[0.08] px-3 py-3 text-xs text-[#e7ffad]"
      >
        <p className="font-semibold">Automatic continuation in progress</p>
        <ol className="mt-2 grid gap-1.5" aria-label="Continuation workflow phases">
          {CONTINUATION_PHASES.map((phase) => (
            <li key={phase} className="flex items-center gap-2 text-[11px] leading-5 text-[#d8e6b5]">
              <RefreshCw className="h-3 w-3 shrink-0 animate-spin opacity-70" aria-hidden="true" />
              {phase}
            </li>
          ))}
        </ol>
        <p className="mt-2 text-[10px] leading-4 text-[#aab28f]">
          The result appears after the agent exits and verification finishes.
        </p>
      </div>
    );
  }

  if (state === "blocked") {
    const detail = blocker || {
      title: "Continuation blocked",
      message: "The target agent could not complete the continuation workflow.",
      affectedTasks: [],
      action: "",
    };
    return (
      <div role="alert" className="rounded-xl border border-red-300/25 bg-red-300/[0.08] px-3 py-3 text-xs text-red-100">
        <p className="font-semibold">{detail.title}</p>
        <p className="mt-1 leading-5 opacity-85">
          {detail.message}
        </p>
        {detail.affectedTasks?.length ? (
          <div className="mt-2 border-t border-red-100/10 pt-2">
            <p className="text-[9px] font-semibold uppercase tracking-[0.14em] opacity-65">
              Affected tasks
            </p>
            <ul className="mt-1.5 grid gap-1 text-[11px] leading-5">
              {detail.affectedTasks.map((task) => (
                <li key={task} className="flex gap-2">
                  <span aria-hidden="true">•</span>
                  <span>{task}</span>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
        {detail.action ? (
          <p className="mt-2 rounded-lg bg-red-100/[0.06] px-2.5 py-2 text-[11px] font-semibold leading-5">
            Next: {detail.action}
          </p>
        ) : null}
        <p className="mt-1 text-[10px] leading-4 opacity-65">
          No successful handoff is being claimed.
        </p>
      </div>
    );
  }

  const delivery = result?.delivery || {};
  const outcome = result?.outcome || {};
  const run = result?.run || {};
  const provider = continuationProviderLabel(
    delivery.provider || result?.target_provider || run.provider,
  );
  const sourceProvider = continuationProviderLabel(
    delivery.source_provider || result?.source_provider,
    "",
  );
  const changedFiles = continuationChangedFiles(result);
  const checks = continuationChecks(result);
  const agentOutput = continuationAgentOutput(result);
  const verified = outcome.verified === true;
  const fresh = String(delivery.mode || "").toLocaleLowerCase() === "fresh";
  const taskTransition = outcome.task_transition || {};
  const workflow = taskTransition.workflow_after
    || result?.preparation?.task?.workflow
    || result?.task?.workflow
    || null;

  return (
    <div role="status" className="rounded-xl border border-[#d9ff68]/25 bg-[#d9ff68]/[0.08] px-3 py-3 text-xs text-[#e7ffad]">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="font-semibold">
            {verified ? "Observed run passed verification" : "Agent run completed"}
          </p>
          <p className="mt-1 text-[11px] leading-5 opacity-80">
            {fresh ? "Fresh " : ""}{provider} agent
            {delivery.provider_switched && sourceProvider
              ? ` · switched from ${sourceProvider}`
              : ""}
          </p>
        </div>
        <span className={`rounded-full border px-2 py-1 text-[9px] font-semibold ${
          verified
            ? "border-[#d9ff68]/30 bg-[#d9ff68]/10 text-[#d9ff68]"
            : "border-amber-300/30 bg-amber-300/10 text-amber-200"
        }`}>
          {verified ? "Verified outcome" : "Verification incomplete"}
        </span>
      </div>

      <ContinuationTaskQueue
        workflow={workflow}
        advanced={taskTransition.status === "completed"}
      />

      <dl className="mt-3 grid gap-2 border-t border-white/10 pt-3">
        <div>
          <dt className="text-[9px] font-semibold uppercase tracking-[0.14em] opacity-55">
            Repository changes
          </dt>
          <dd className="mt-1 leading-5">
            {changedFiles.length
              ? `${changedFiles.length} changed ${changedFiles.length === 1 ? "file" : "files"} · ${summarizeChangedFiles(changedFiles)}`
              : "No repository file changes observed."}
          </dd>
        </div>
        <div>
          <dt className="text-[9px] font-semibold uppercase tracking-[0.14em] opacity-55">
            Checks
          </dt>
          <dd className="mt-1 leading-5">{continuationChecksLabel(checks)}</dd>
        </div>
        {agentOutput ? (
          <div>
            <dt className="text-[9px] font-semibold uppercase tracking-[0.14em] opacity-55">
              Agent outcome
            </dt>
            <dd className="mt-1 leading-5">“{agentOutput}”</dd>
          </div>
        ) : null}
      </dl>

      {!verified ? (
        <p className="mt-2 border-t border-amber-200/15 pt-2 text-[10px] leading-4 text-amber-100/75">
          The run finished, but successful task continuation is not proven.
        </p>
      ) : null}
    </div>
  );
}

function ContinuationTaskQueue({ workflow, advanced = false }) {
  if (!workflow || typeof workflow !== "object") return null;
  const buckets = [
    ["Now", workflow.now],
    ["Blocked", workflow.blocked],
    ["Next", workflow.next],
    ["Paused", workflow.paused],
  ]
    .map(([label, tasks]) => [
      label,
      normalizeWorkflowTaskTitles(tasks),
    ])
    .filter(([, tasks]) => tasks.length);
  if (!buckets.length) return null;

  return (
    <div className="mt-3 border-t border-white/10 pt-3">
      <p className="text-[9px] font-semibold uppercase tracking-[0.14em] opacity-55">
        {advanced ? "Workflow advanced after verification" : "Execution plan"}
      </p>
      <dl className="mt-2 grid gap-2 sm:grid-cols-2">
        {buckets.map(([label, tasks]) => (
          <div key={label} className="rounded-lg bg-white/[0.045] px-2.5 py-2">
            <dt className="text-[8px] font-black uppercase tracking-[0.13em] opacity-55">
              {label}
            </dt>
            <dd className="mt-1 text-[10px] font-semibold leading-4">
              {tasks.slice(0, 3).join(" · ")}
              {tasks.length > 3 ? ` · +${tasks.length - 3}` : ""}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

function normalizeWorkflowTaskTitles(value) {
  if (!Array.isArray(value)) return [];
  return [...new Set(value.map((task) => (
    preserveContinuationText(
      typeof task === "string"
        ? task
        : task?.title || task?.objective || task?.name,
    )
  )).filter(Boolean))];
}

function continuationBlocker(result) {
  const candidates = [
    result?.blocker,
    result?.outcome?.blocker,
    result?.delivery?.blocker,
  ];
  const explicit = candidates.find(Boolean);
  if (explicit) {
    return normalizeContinuationBlocker(explicit, {
      fallbackTitle: "Continuation blocked",
      fallbackMessage: "The continuation workflow reported a blocker.",
    });
  }

  const checks = continuationChecks(result);
  if (checks.failed > 0) {
    return {
      title: "Verification failed",
      message: `${checks.failed} verification ${checks.failed === 1 ? "check failed" : "checks failed"}.`,
      affectedTasks: [],
      action: "Review the failed checks before starting another continuation.",
    };
  }

  const statuses = [
    result?.status,
    result?.delivery?.status,
    result?.run?.status,
    result?.outcome?.status,
  ]
    .map((value) => String(value || "").trim().toLocaleLowerCase())
    .filter(Boolean);
  if (statuses.some((status) => (
    ["blocked", "failed", "error", "not_delivered", "unavailable"].includes(status)
  ))) {
    const message = cleanDisplayText(
      result?.outcome?.message
      || result?.delivery?.message
      || result?.message,
    ) || "The target agent did not complete the continuation workflow.";
    return {
      title: continuationFailureTitle(result),
      message,
      affectedTasks: continuationAffectedTasks(result),
      action: cleanDisplayText(
        result?.outcome?.action
        || result?.delivery?.action
        || result?.action,
      ),
    };
  }
  return null;
}

function continuationErrorFromRequest(error, targetProvider) {
  const detail = error?.detail;
  const candidate = detail?.blocker || detail || error;
  return normalizeContinuationBlocker(candidate, {
    fallbackTitle: `${continuationProviderLabel(targetProvider)} continuation blocked`,
    fallbackMessage: error?.message || "The continuation workflow could not start.",
  });
}

function normalizeContinuationBlocker(blocker, {
  fallbackTitle = "Continuation blocked",
  fallbackMessage = "The continuation workflow could not continue.",
} = {}) {
  if (typeof blocker === "string") {
    return {
      title: fallbackTitle,
      message: preserveContinuationText(blocker) || fallbackMessage,
      affectedTasks: [],
      action: "",
    };
  }
  const source = blocker && typeof blocker === "object" ? blocker : {};
  const code = cleanDisplayText(source.code);
  const title = preserveContinuationText(
    source.title
    || source.label
    || continuationBlockerTitleFromCode(code),
  ) || fallbackTitle;
  const message = preserveContinuationText(
    source.message
    || source.reason
    || source.detail?.message
    || source.error,
  ) || fallbackMessage;
  const affectedTasks = normalizeAffectedTasks(
    source.affected_tasks
    || source.affectedTasks
    || source.detail?.affected_tasks,
  );
  const action = preserveContinuationText(
    source.action
    || source.next_action
    || source.recovery_action
    || source.detail?.action,
  );
  return { title, message, affectedTasks, action, code };
}

function preserveContinuationText(value) {
  return String(value || "").replace(/\s+/g, " ").trim();
}

function compactContinuationGoal(value) {
  const text = preserveContinuationText(cleanDisplayText(value));
  if (!text) return "Resolved from the latest linked work";
  const sentence = text.split(/(?<=[.!?])\s+/)[0] || text;
  const limit = 140;
  return sentence.length > limit
    ? `${sentence.slice(0, limit - 1).trimEnd()}…`
    : sentence;
}

function continuationRepositoryLabel(value) {
  const normalized = String(value || "").replace(/\\/g, "/").replace(/\/+$/, "");
  return normalized.split("/").filter(Boolean).at(-1) || "Resolved at launch";
}

function continuationBlockerTitleFromCode(code) {
  const normalized = String(code || "").toLocaleLowerCase();
  if (normalized.includes("auth") || normalized.includes("oauth")) {
    return "Agent authentication failed";
  }
  if (normalized.includes("update") || normalized.includes("cli")) {
    return "Agent update required";
  }
  if (normalized.includes("fresh")) return "Repository freshness check failed";
  if (normalized.includes("verification")) return "Verification failed";
  if (normalized.includes("goal")) return "Task goal is missing";
  if (normalized.includes("provider") || normalized.includes("agent")) {
    return "Target agent unavailable";
  }
  return "";
}

function continuationFailureTitle(result) {
  const provider = continuationProviderLabel(
    result?.delivery?.provider || result?.target_provider || result?.run?.provider,
    "",
  );
  return provider ? `${provider} continuation failed` : "Continuation failed";
}

function continuationAffectedTasks(result) {
  return normalizeAffectedTasks(
    result?.affected_tasks
    || result?.outcome?.affected_tasks
    || result?.delivery?.affected_tasks,
  );
}

function normalizeAffectedTasks(value) {
  if (!Array.isArray(value)) return [];
  return [...new Set(value.map((item) => (
    cleanDisplayText(
      typeof item === "string"
        ? item
        : item?.title || item?.name || item?.task || item?.id,
    )
  )).filter(Boolean))];
}

function continuationChangedFiles(result) {
  const candidates = [
    result?.outcome?.changed_files,
    result?.run?.changed_files,
    result?.changed_files,
  ];
  const files = candidates.find(Array.isArray) || [];
  return [...new Set(files.map((item) => cleanDisplayText(item)).filter(Boolean))];
}

function continuationAgentOutput(result) {
  const value = cleanDisplayText(
    result?.outcome?.summary
    || result?.outcome?.output
    || result?.run?.command?.stdout,
  );
  if (!value) return "";
  const limit = 320;
  return value.length > limit ? `${value.slice(0, limit - 1).trimEnd()}…` : value;
}

function continuationChecks(result) {
  const supplied = result?.outcome?.checks;
  if (supplied && typeof supplied === "object") {
    const items = Array.isArray(supplied.items) ? supplied.items : [];
    const total = numericCount(supplied.total, items.length);
    const passed = numericCount(
      supplied.passed,
      items.filter((item) => continuationCheckPassed(item)).length,
    );
    const failed = numericCount(supplied.failed, Math.max(0, total - passed));
    return { total, passed, failed, status: supplied.status || "", items };
  }

  const items = Array.isArray(result?.run?.verification_results)
    ? result.run.verification_results
    : [];
  const passed = items.filter((item) => continuationCheckPassed(item)).length;
  return {
    total: items.length,
    passed,
    failed: Math.max(0, items.length - passed),
    status: items.length ? (passed === items.length ? "passed" : "failed") : "",
    items,
  };
}

function continuationCheckPassed(item) {
  const status = String(item?.status || "").toLocaleLowerCase();
  if (status) return ["passed", "success", "completed"].includes(status);
  return Number(item?.result?.exit_code) === 0;
}

function continuationChecksLabel(checks) {
  if (!checks.total) return "No verification checks ran.";
  if (checks.failed) {
    return `${checks.passed}/${checks.total} passed · ${checks.failed} failed.`;
  }
  return `${checks.passed}/${checks.total} passed.`;
}

function summarizeChangedFiles(files) {
  const visible = files.slice(0, 3).join(", ");
  return files.length > 3 ? `${visible}, +${files.length - 3} more` : visible;
}

function numericCount(value, fallback = 0) {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : fallback;
}

function continuationIdempotencyKey() {
  if (globalThis.crypto?.randomUUID) {
    return `continue-${globalThis.crypto.randomUUID()}`;
  }
  return `continue-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}

function continuationProviderLabel(value, fallback = "Target") {
  const provider = String(value || "").trim().toLocaleLowerCase();
  return {
    codex: "Codex",
    claude: "Claude Code",
    claude_code: "Claude Code",
    opencode: "OpenCode",
  }[provider] || cleanDisplayText(value) || fallback;
}

function attentionLabel(card) {
  if (card.status === "conflict") return "Conflict";
  if (card.status === "stale") return "Stale";
  if (card.category === "blocker" || card.status === "blocked") return "Blocker";
  if (card.type === "risk" || card.category === "risk") return "Risk";
  return "Review";
}

function explainCardUrl(cardId) {
  return `/app/explain?card=${encodeURIComponent(cardId)}`;
}

function activityTimestamp(card) {
  const value = card?.updated_at || card?.source_snapshot?.ingested_at;
  const parsed = value ? new Date(value).getTime() : 0;
  return Number.isFinite(parsed) ? parsed : 0;
}

function activitySessionReference(activity) {
  if (
    !activity?.session_id
    || activity.state === "unassigned"
    || !(activity.provider || activity.tool)
  ) {
    return null;
  }
  return {
    provider: normalizeProvider(activity.provider || activity.tool),
    sessionId: String(activity.session_id),
  };
}

function activitySessionDescriptor(activity) {
  const session = activitySessionReference(activity);
  if (!session) return null;
  const title = prepareTaskCandidate(
    activity.selected_topic
    || activity.request
    || activity.title
    || activity.session_title,
  ) || "Imported coding session";
  return {
    id: activity.source_document_id || `${session.provider}:${session.sessionId}`,
    connector_type: session.provider,
    harness: {
      codex: "Codex",
      claude: "Claude Code",
      opencode: "OpenCode",
    }[session.provider] || "Agent",
    session_id: session.sessionId,
    source_document_id: activity.source_document_id || null,
    title,
    preview: displayActivityText(activity.latest_update),
    updated_at: activity.updated_at || null,
    cwd: activity.cwd || null,
    branch: activity.branch || null,
    live: Boolean(activity.live),
    compaction_checkpoints: [],
  };
}

function checkpointSessionReference(checkpoint) {
  if (!checkpoint?.provider || !checkpoint?.session_id) return null;
  return {
    provider: normalizeProvider(checkpoint.provider),
    sessionId: String(checkpoint.session_id),
  };
}

function sessionDescriptorReference(session) {
  if (!session?.session_id || !(session.connector_type || session.provider)) return null;
  return {
    provider: normalizeProvider(session.connector_type || session.provider),
    sessionId: String(session.session_id),
  };
}

function queryHasSettled(query) {
  return Boolean(
    query?.isFetched
    || query?.isSuccess
    || query?.isError
    || (!query?.isLoading && query?.data !== undefined),
  );
}

function checkpointMatchesActivity(checkpoint, activity) {
  const session = activitySessionReference(activity);
  if (!checkpoint || !session) return false;
  return (
    normalizeProvider(checkpoint.provider) === session.provider
    && String(checkpoint.session_id || "") === session.sessionId
  );
}

function normalizeProvider(value) {
  const provider = String(value || "").trim().toLocaleLowerCase();
  return provider === "claude_code" ? "claude" : provider;
}

function displayActivityText(value) {
  const raw = String(value || "").trim();
  const cleaned = cleanDisplayText(raw);
  if (!cleaned) return "";
  if (!/(?:\.{3}|…)\s*$/.test(raw)) return cleaned;
  const completeWords = cleaned.replace(/\s+\S+$/, "").trim() || cleaned;
  return `${completeWords}…`;
}

function formatBoundaryTime(value) {
  const parsed = value ? new Date(value) : null;
  if (!parsed || Number.isNaN(parsed.getTime())) return "time unavailable";
  return parsed.toLocaleString([], {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function fallbackActivity(digest) {
  const outcome = digest?.oversight?.latest_outcome;
  const goal = cleanDisplayText(digest?.current_goal?.title);
  if (!outcome || !goal) return null;
  return {
    kind: "agent_run",
    state: "completed",
    evidence_level: "observed_run",
    title: goal,
    request: goal,
    latest_update: cleanDisplayText(outcome.summary),
    updated_at: outcome.observed_at,
    changed_files: [],
    verification: { observed: 0, passed: 0, failed: 0 },
    outcome,
  };
}

function prepareTaskCandidate(value) {
  let raw = String(value || "");
  const requestMarker = raw.match(/^#{1,6}\s*My request for Codex:\s*$/im);
  if (requestMarker?.index != null) {
    raw = raw.slice(requestMarker.index + requestMarker[0].length);
  }
  raw = raw
    .replace(/<image\b[\s\S]*?<\/image>/gi, " ")
    .split(/\r?\n/)
    .filter((rawLine) => {
      const plain = rawLine.replace(/^[#>*\-\d.)\s]+/, "").trim();
      const lowered = plain.toLowerCase();
      if (!plain) return true;
      if (["files mentioned by the user:", "my request for codex:"].includes(lowered)) return false;
      if (lowered.startsWith("referenced chatgpt conversation:")) return false;
      if (lowered.startsWith("this is untrusted")) return false;
      if (isReferencedConversationPayload(plain)) return false;
      if (/^(?:screenshot\s+\d{4}-\d{2}-\d{2}\s+at\s+\d{1,2}(?:[.:]\d{2}){1,2}|codex-clipboard-[a-z0-9-]+)(?:\.(?:png|jpe?g|webp))?(?::.*)?$/i.test(plain)) return false;
      if (/(?:\/var\/folders\/|\/private\/var\/|\/temporaryitems\/|screencaptureui_)/i.test(rawLine) && /\.(?:png|jpe?g|webp)(?:["'>:]|$)/i.test(rawLine)) return false;
      return !/^(?:image\s+name\s*=|path\s*=|\[image\s+#)/i.test(plain);
    })
    .join("\n");
  const task = cleanDisplayText(raw);
  if (!task) return "";
  if (
    isContinuationControlCandidate(task)
    || isTaskIdentifierNoise(task)
    || isReferencedConversationPayload(task)
  ) {
    return "";
  }
  const lowered = task.toLowerCase();
  const runtimeMarkers = [
    "collaboration tools cannot be called from inside functions.exec",
    "request_user_input availability",
    "permissions instructions",
    "developer instructions",
    "sandbox_permissions",
    "internal_chat_message_metadata",
  ];
  const attachmentMarkers = [
    "/var/folders/",
    "/private/var/",
    "/temporaryitems/",
    "screencaptureui_",
    "files mentioned by the user",
    "image name=",
  ];
  const screenshotArtifact = (
    /\bscreenshot\s+\d{4}-\d{2}-\d{2}\s+at\s+\d{1,2}(?:[.:]\d{2}){1,2}/i.test(task)
    && /\.(?:png|jpe?g|webp)\b/i.test(task)
  );
  return runtimeMarkers.some((marker) => lowered.includes(marker))
    || attachmentMarkers.some((marker) => lowered.includes(marker))
    || screenshotArtifact
    ? ""
    : task;
}

function isContinuationControlCandidate(value) {
  const raw = String(value || "").trim();
  const normalized = raw
    .toLowerCase()
    .replace(/[^a-z0-9']+/g, " ")
    .trim();
  const exactControls = new Set([
    "carry on",
    "continue",
    "continue please",
    "go ahead",
    "go ahead now",
    "go on",
    "keep going",
    "next",
    "now continue",
    "okay continue",
    "please continue",
    "proceed",
    "resume",
    "yes continue",
  ]);
  return exactControls.has(normalized)
    || /^(?:please )?(?:continue|resume)(?: the task)? from (?:the )?(?:latest|last|current) state$/.test(normalized)
    || /^(?:continue|resume)\s*:\s*[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(raw);
}

function isTaskIdentifierNoise(value) {
  const raw = String(value || "").trim();
  if (!raw) return false;
  const candidate = raw.replace(/^[\s{}[\]()"':;,`]+|[\s{}[\]()"':;,`]+$/g, "");
  if (!candidate || /\s/.test(candidate)) return false;
  const normalized = candidate.toLowerCase().replace(/[^a-z0-9_]+/g, "");
  const metadataKeys = new Set([
    "clientthreadid",
    "conversationid",
    "hostid",
    "projectid",
    "sessionid",
    "sourcedocumentid",
    "sourcethreadid",
    "threadid",
    "turnid",
    "workspaceid",
  ]);
  return metadataKeys.has(normalized)
    || /^[a-z][A-Za-z0-9]*(?:Id|ID|Uuid|UUID|Url|URL)$/.test(candidate)
    || /^[a-z][a-z0-9_]*(?:_id|_uuid|_url)$/.test(candidate);
}

function isReferencedConversationPayload(value) {
  const raw = String(value || "").trim();
  if (!raw.startsWith("{") && !raw.startsWith("[")) return false;
  return /["']conversationId["']\s*:/i.test(raw)
    && /["']conversation["']\s*:/i.test(raw);
}

function cleanRecoveryText(value) {
  return cleanDisplayText(value)
    .replace(/^continue:\s*(?:[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})?\s*/i, "")
    .trim();
}

function distinctCardDetail(card, fallback) {
  if (!card) return fallback;
  const title = cleanDisplayText(card.title);
  for (const candidate of [card.summary, card.next_action, card.why_it_matters]) {
    let detail = cleanDisplayText(candidate);
    if (!detail) continue;
    if (title && detail.toLowerCase().startsWith(title.toLowerCase())) {
      detail = detail.slice(title.length).trim();
    }
    detail = detail
      .replace(/^State:\s*\S+\s*/i, "")
      .replace(/^Labels:\s*none\s*/i, "")
      .trim();
    if (detail && detail.toLowerCase() !== title.toLowerCase()) return detail;
  }
  return fallback;
}

function PageState({ title, detail, error = false }) {
  return (
    <div className={`mx-auto max-w-xl rounded-2xl border p-8 text-center shadow-[0_12px_36px_rgba(23,23,19,0.04)] dark:shadow-none ${error ? "border-red-200 bg-red-50 dark:border-red-900/60 dark:bg-red-950/30" : "border-[#d8d8cf] bg-[#fbfbf6] dark:border-[#292925] dark:bg-[#141411]"}`}>
      <h1 className="text-lg font-semibold">{title}</h1>
      {detail ? <p className="mt-2 text-sm text-[#68685f] dark:text-[#aaa9a0]">{detail}</p> : null}
    </div>
  );
}
