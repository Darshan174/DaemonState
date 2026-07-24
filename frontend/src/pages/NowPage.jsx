import { useState } from "react";
import { Link } from "react-router-dom";
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
import SessionContinuationDialog from "../components/SessionContinuationDialog";
import ProductLoadingState from "../components/ProductLoadingState";
import {
  useCaptureCheckpoint,
  useCheckpointComparison,
  useCheckpoints,
  useContinueSession,
  useLatestCheckpoint,
  useSessionContinuity,
  useSessionLibrary,
  useVerifyCheckpoint,
} from "../api/hooks";
import {
  useContextDigest,
  useLinkedAISessionRefresh,
  usePrepareContext,
  useProjectMemory,
} from "../context-map/api";
import { cleanDisplayText, formatTimeAgo, sessionIdentity } from "../context-map/digest";
import { buildSessionContinuity } from "./sessionContinuity";
import { useProductWorkspace } from "./useProductWorkspace";

export default function NowPage() {
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
  const continuityQuery = useSessionContinuity(
    workspace.activeWorkspaceId,
    {
      enabled: checkpointSettled && Boolean(detailSessionReference),
      ...(detailSessionReference || {}),
    },
  );
  const memoryQuery = useProjectMemory(
    workspace.activeWorkspaceId,
    { limit: 1, poll: true, enabled: checkpointSettled },
  );
  const captureCheckpoint = useCaptureCheckpoint();
  const continueSession = useContinueSession();
  const prepareContext = usePrepareContext();
  const [prepareState, setPrepareState] = useState("idle");
  const [prepareError, setPrepareError] = useState("");
  const [selectedResumeCard, setSelectedResumeCard] = useState(null);
  const [resumeState, setResumeState] = useState("idle");
  const [resumeNotice, setResumeNotice] = useState("");
  const selectedComparison = useCheckpointComparison(
    workspace.activeWorkspaceId,
    selectedResumeCard?.checkpoint?.id,
  );
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
  const currentGoal = prepareTaskCandidate(digest.current_goal?.title);
  const activeTaskTitle = digestPending
    ? "Loading current activity…"
    : digestUnavailable
      ? "Current activity is unavailable"
      : currentGoal
        || prepareTaskCandidate(observedActivity?.request || observedActivity?.title)
        || prepareTaskCandidate(activity?.request || activity?.title)
        || prepareTaskCandidate(cleanRecoveryText(currentCheckpoint?.sections?.goal?.[0]?.statement))
        || "No active task selected";
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
  const continuitySessions = activitySession
    ? [activitySession]
    : libraryQuery.data?.sessions || [];
  const sessionContinuityCards = buildSessionContinuity({
    sessions: continuitySessions,
    ledgers: continuityQuery.data?.sessions || [],
    checkpoints: checkpointHistoryQuery.data?.checkpoints || [],
  });
  const resumeCard = sessionContinuityCards.find((card) => (
    card.provider === normalizeProvider(checkpoint?.provider)
    && card.sessionId === checkpoint?.session_id
  )) || null;
  const resumeSourcesLoading = Boolean(
    checkpoint
    && !resumeCard?.canResume
    && (
      !checkpointSettled
      || (detailSessionReference && !queryHasSettled(continuityQuery))
      || (detailSessionReference && !queryHasSettled(checkpointHistoryQuery))
      || (libraryFallbackNeeded && !queryHasSettled(libraryQuery))
      || libraryQuery.isLoading
      || continuityQuery.isLoading
      || checkpointHistoryQuery.isLoading
    )
  );
  const resumeSourcesError = (
    libraryQuery.error
    || continuityQuery.error
    || checkpointHistoryQuery.error
    || null
  );
  const resumeAvailability = resumeCard?.canResume
    ? "available"
    : resumeSourcesLoading
      ? "loading"
      : resumeSourcesError
        ? "unknown"
        : "unavailable";
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
  const saveCheckpoint = () => {
    if (!latestSession) return;
    captureCheckpoint.mutate({
      workspaceId: workspace.activeWorkspaceId,
      provider: latestSession.connector_type,
      sessionId: latestSession.session_id,
    });
  };
  const openResume = (card) => {
    if (!card?.canResume) return;
    setResumeState("idle");
    setResumeNotice("");
    setSelectedResumeCard(card);
  };
  const confirmResume = async () => {
    if (!selectedResumeCard) return;
    setResumeState("preparing");
    setResumeNotice("");
    try {
      const bundle = await continueSession.mutateAsync({
        workspaceId: workspace.activeWorkspaceId,
        sourceDocumentId: selectedResumeCard.sourceDocumentId,
        launchSession: true,
      });
      await navigator.clipboard.writeText(bundle.content);
      const copiedOnly = bundle.launch?.launched === false;
      setResumeState(copiedOnly ? "copied_only" : "copied");
      setResumeNotice(
        copiedOnly
          ? bundle.launch?.message || "Resume context copied. The original task could not be opened."
          : "Original task opened and resume context copied.",
      );
      setSelectedResumeCard(null);
    } catch (error) {
      setResumeState("error");
      setResumeNotice(error?.message || "Could not prepare resume context.");
    }
  };
  const prepareNextSession = async () => {
    if (!currentGoal) return;
    setPrepareState("preparing");
    setPrepareError("");
    try {
      const result = await prepareContext.mutateAsync({
        objective: currentGoal,
        workspace_id: workspace.activeWorkspaceId,
        mode: "task",
        objective_origin: "trusted_human",
      });
      if (!globalThis.navigator?.clipboard?.writeText) {
        throw new Error("Clipboard access is unavailable.");
      }
      await globalThis.navigator.clipboard.writeText(result.markdown);
      setPrepareState("copied");
    } catch (error) {
      setPrepareState("error");
      setPrepareError(error?.message || "Could not prepare the next session.");
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
  const prepareAction = digestUnavailable
    ? {
        kind: "unavailable",
        description: "Current activity could not be loaded. Other saved project context remains available below.",
      }
    : actionInputsPending
      ? {
          kind: "loading",
          description: "Reading the current task and its safest available continuation.",
        }
      : latestSession && currentGoal
        ? {
            kind: "compile",
            description: "Compile the trusted goal and copy a focused context pack for a new agent session.",
          }
        : !latestSession
          ? {
              kind: "choose",
              description: "Choose a linked coding session before preparing its continuation.",
            }
          : checkpoint
            ? {
                kind: "review",
                description: "Review the saved context before resuming this task.",
              }
            : {
                kind: "capture",
                description: "Capture the current session state before preparing its continuation.",
              };

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

          <div className="mt-8 grid gap-8 lg:grid-cols-[minmax(0,1fr)_18rem] lg:items-end">
            <div className="min-w-0">
              <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[#d9ff68]">Active task</p>
              <h1 className="mt-4 max-w-[18ch] text-[clamp(2.65rem,6.2vw,5.75rem)] font-semibold leading-[0.92] tracking-[-0.062em] text-white">
                {activeTaskTitle}
              </h1>
              <p className="mt-5 max-w-2xl text-sm leading-6 text-[#b8b8af] sm:text-[15px]">
                Progress, verification, and the safest available continuation—kept separate by evidence type.
              </p>
            </div>

            <div className="flex flex-col gap-3">
              <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-1">
                {prepareAction.kind === "loading" || prepareAction.kind === "unavailable" ? (
                  <button
                    type="button"
                    disabled
                    className="inline-flex min-h-12 w-full items-center justify-center gap-2 rounded-xl bg-[#d9ff68] px-5 py-3 text-sm font-semibold text-[#171713] opacity-65"
                  >
                    {prepareAction.kind === "loading" ? "Loading task…" : "Activity unavailable"}
                    {prepareAction.kind === "loading"
                      ? <RefreshCw className="h-4 w-4 animate-spin" aria-hidden="true" />
                      : <ShieldAlert className="h-4 w-4" aria-hidden="true" />}
                  </button>
                ) : prepareAction.kind === "compile" ? (
                  <button
                    type="button"
                    onClick={prepareNextSession}
                    disabled={prepareState === "preparing" || prepareContext.isPending}
                    className="inline-flex min-h-12 w-full items-center justify-center gap-2 rounded-xl bg-[#d9ff68] px-5 py-3 text-sm font-semibold text-[#171713] transition hover:-translate-y-0.5 hover:bg-[#e4ff91] focus:outline-none focus-visible:ring-2 focus-visible:ring-white focus-visible:ring-offset-2 focus-visible:ring-offset-[#171713] disabled:cursor-wait disabled:opacity-60"
                  >
                    {prepareState === "preparing" || prepareContext.isPending ? "Preparing context…" : "Prepare next session"}
                    {prepareState === "preparing" || prepareContext.isPending
                      ? <RefreshCw className="h-4 w-4 animate-spin" aria-hidden="true" />
                      : <ArrowRight className="h-4 w-4" aria-hidden="true" />}
                  </button>
                ) : prepareAction.kind === "choose" ? (
                  <Link to="/app/library" className="inline-flex min-h-12 w-full items-center justify-center gap-2 rounded-xl bg-[#d9ff68] px-5 py-3 text-sm font-semibold text-[#171713] transition hover:-translate-y-0.5 hover:bg-[#e4ff91] focus:outline-none focus-visible:ring-2 focus-visible:ring-white focus-visible:ring-offset-2 focus-visible:ring-offset-[#171713]">
                    Prepare next session <ArrowRight className="h-4 w-4" aria-hidden="true" />
                  </Link>
                ) : prepareAction.kind === "review" ? (
                  <a href="#continuity-checkpoint" className="inline-flex min-h-12 w-full items-center justify-center gap-2 rounded-xl bg-[#d9ff68] px-5 py-3 text-sm font-semibold text-[#171713] transition hover:-translate-y-0.5 hover:bg-[#e4ff91] focus:outline-none focus-visible:ring-2 focus-visible:ring-white focus-visible:ring-offset-2 focus-visible:ring-offset-[#171713]">
                    Prepare next session <ArrowRight className="h-4 w-4" aria-hidden="true" />
                  </a>
                ) : (
                  <button
                    type="button"
                    onClick={saveCheckpoint}
                    disabled={captureCheckpoint.isPending}
                    className="inline-flex min-h-12 w-full items-center justify-center gap-2 rounded-xl bg-[#d9ff68] px-5 py-3 text-sm font-semibold text-[#171713] transition hover:-translate-y-0.5 hover:bg-[#e4ff91] focus:outline-none focus-visible:ring-2 focus-visible:ring-white focus-visible:ring-offset-2 focus-visible:ring-offset-[#171713] disabled:cursor-wait disabled:opacity-60"
                  >
                    {captureCheckpoint.isPending ? "Capturing session…" : "Prepare next session"}
                    <ArrowRight className="h-4 w-4" aria-hidden="true" />
                  </button>
                )}
                <Link to="/app/explain" className="inline-flex min-h-11 w-full items-center justify-center rounded-xl border border-white/15 bg-white/[0.055] px-4 py-3 text-xs font-semibold text-white transition hover:-translate-y-0.5 hover:bg-white/10 focus:outline-none focus-visible:ring-2 focus-visible:ring-white">
                  Explain evidence
                </Link>
              </div>
              <p className="text-xs leading-5 text-[#97978f]">{prepareAction.description}</p>
              <div aria-live="polite" aria-atomic="true">
                {prepareState === "copied" ? (
                  <p role="status" className="text-xs font-semibold leading-5 text-[#d9ff68]">
                    Context pack copied. Paste it into the new agent session.
                  </p>
                ) : null}
                {prepareState === "error" || prepareError ? (
                  <p role="alert" className="text-xs font-semibold leading-5 text-red-300">
                    {prepareError || "Could not prepare the next session."}
                  </p>
                ) : null}
              </div>
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

      <section className="grid items-start gap-4 lg:grid-cols-2 xl:grid-cols-3" aria-label="Active task overview">
        <ObservedWork
          activity={activity}
          activeTaskTitle={activeTaskTitle}
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
        error={checkpointQuery.error || workspaceCheckpointQuery.error || captureCheckpoint.error}
        latestSession={latestSession}
        memory={checkpointSettled ? memoryQuery.data : null}
        memoryLoading={
          !checkpointSettled
          || (!queryHasSettled(memoryQuery) && !memoryQuery.error)
        }
        memoryError={checkpointSettled ? memoryQuery.error : null}
        sessionLoading={
          digestPending
          || (
            libraryFallbackNeeded
            && (
              !checkpointSettled
              || !queryHasSettled(libraryQuery)
            )
          )
        }
        resumeCard={resumeCard}
        resumeAvailability={resumeAvailability}
        workspaceId={workspace.activeWorkspaceId}
        onCapture={saveCheckpoint}
        onResume={openResume}
        capturePending={captureCheckpoint.isPending}
        resumePending={continueSession.isPending || resumeState === "preparing"}
      />

      {resumeNotice && ["copied", "copied_only"].includes(resumeState) ? (
        <p role="status" className={`rounded-2xl border px-4 py-3 text-xs font-semibold ${
          resumeState === "copied_only"
            ? "border-amber-200 bg-amber-50 text-amber-900 dark:border-amber-900/70 dark:bg-amber-950/30 dark:text-amber-200"
            : "border-emerald-200 bg-emerald-50 text-emerald-900 dark:border-emerald-900/70 dark:bg-emerald-950/30 dark:text-emerald-200"
        }`}>
          {resumeNotice}
        </p>
      ) : null}
      {(resumeState === "error" || continueSession.error) && !selectedResumeCard ? (
        <p role="alert" className="rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-xs font-semibold text-red-700 dark:border-red-900/70 dark:bg-red-950/30 dark:text-red-200">
          {resumeNotice || continueSession.error?.message || "Could not prepare resume context."}
        </p>
      ) : null}

      <AttentionPanel cards={attentionCards} loading={digestPending} error={digestUnavailable} />

      {checkpointSettled && !digestUnavailable && recentSessionCards.length
        ? <RecentSessions cards={recentSessionCards} />
        : null}

      {selectedResumeCard ? (
        <SessionContinuationDialog
          card={selectedResumeCard}
          repositoryComparison={selectedComparison.data}
          repositoryComparisonLoading={selectedComparison.isLoading}
          isPending={continueSession.isPending || resumeState === "preparing"}
          errorMessage={resumeState === "error" ? resumeNotice : ""}
          onCancel={() => setSelectedResumeCard(null)}
          onConfirm={confirmResume}
        />
      ) : null}
    </div>
  );
}

function CheckpointPanel({
  checkpoint,
  previousCheckpoint,
  sessionCompactions,
  isLoading,
  error,
  latestSession,
  memory,
  memoryLoading,
  memoryError,
  sessionLoading,
  resumeCard,
  resumeAvailability,
  workspaceId,
  onCapture,
  onResume,
  capturePending,
  resumePending,
}) {
  const verifyCheckpoint = useVerifyCheckpoint();

  const verify = () => {
    if (checkpoint) {
      verifyCheckpoint.mutate({ workspaceId, checkpointId: checkpoint.id, executeCommands: true });
    }
  };

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
            Save the current task before a long handoff or compaction to preserve its goal, evidence, and exact next action.
          </p>
        </header>

        <div className="grid lg:grid-cols-[minmax(0,1.15fr)_minmax(19rem,.85fr)]">
          <div className="px-6 py-6 sm:px-8 sm:py-8">
            {sessionLoading && !latestSession ? (
              <button type="button" disabled className="btn-primary min-h-11 text-xs opacity-60">
                <RefreshCw className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
                Loading linked task…
              </button>
            ) : latestSession ? (
              <button type="button" onClick={onCapture} disabled={capturePending} className="btn-primary min-h-11 text-xs disabled:opacity-60">
                {capturePending ? "Saving current context…" : "Save current context"}
              </button>
            ) : (
              <Link to="/app/library" className="btn-primary min-h-11 text-xs">Choose a linked task</Link>
            )}

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
                  Review resume history <ArrowRight className="h-3.5 w-3.5 transition-transform group-hover:translate-x-1" />
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
  const reviewNotice = superseded
    ? "Earlier snapshot · newer task activity exists"
    : historical
      ? "Older snapshot · review before continuing"
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
            <div className="mt-5 flex flex-col gap-3 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-amber-950 dark:border-amber-900/70 dark:bg-amber-950/30 dark:text-amber-100 sm:flex-row sm:items-center sm:justify-between">
              <p className="text-xs font-semibold leading-5">{reviewNotice}</p>
              {latestSession ? (
                <button type="button" onClick={onCapture} disabled={capturePending} className="min-h-11 shrink-0 rounded-xl border border-current px-4 text-xs font-semibold transition hover:bg-white/50 disabled:cursor-wait disabled:opacity-60 dark:hover:bg-black/20">
                  {capturePending ? "Saving current context…" : "Save current context"}
                </button>
              ) : null}
            </div>
          ) : null}
        </section>

        <aside className="flex flex-col border-t border-[#deded5] dark:border-[#292925] lg:border-l lg:border-t-0">
          <ProjectMemorySummary memory={memory} loading={memoryLoading} error={memoryError} />
          <div className="mt-auto border-t border-[#deded5] px-6 py-6 dark:border-[#292925] sm:px-8 lg:px-7">
            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-1 xl:grid-cols-2">
              <button type="button" onClick={verify} disabled={verifyCheckpoint.isPending} className="btn-secondary min-h-11 text-xs disabled:cursor-wait disabled:opacity-60">
                {verifyCheckpoint.isPending ? "Running checks…" : "Verify checkpoint"}
              </button>
              {resumeAvailability === "available" ? (
                <button type="button" onClick={() => onResume(resumeCard)} disabled={resumePending} className="btn-primary min-h-11 text-xs disabled:opacity-60">
                  <Clipboard className="h-3.5 w-3.5" />{resumePending ? "Preparing…" : "Resume task"}
                </button>
              ) : resumeAvailability === "loading" ? (
                <button type="button" disabled className="btn-primary min-h-11 text-xs opacity-60">
                  <RefreshCw className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
                  Checking resume availability…
                </button>
              ) : (
                <Link to="/app/runs" className="btn-primary min-h-11 text-xs">
                  Review resume history <ArrowRight className="h-3.5 w-3.5" />
                </Link>
              )}
            </div>
            {resumeAvailability === "unknown" ? (
              <p className="mt-3 text-xs leading-5 text-amber-700 dark:text-amber-200">
                Resume availability could not be confirmed. The saved context remains available in history.
              </p>
            ) : resumeAvailability === "unavailable" ? (
              <p className="mt-3 text-xs leading-5 text-[#77776e] dark:text-[#aaa9a0]">
                The original task is unavailable here; its saved context remains in history.
              </p>
            ) : null}
          </div>
        </aside>
      </div>

      {sessionCompactions?.length ? (
        <SessionCompactions checkpoints={sessionCompactions} displayedCheckpointId={checkpoint.id} />
      ) : null}
      {(verifyCheckpoint.error || error) ? (
        <p role="alert" className="border-t border-red-200 px-6 py-3 text-xs font-semibold text-red-600 sm:px-8">{verifyCheckpoint.error?.message || error.message}</p>
      ) : null}
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
    <dl className="relative grid border-t border-white/10 bg-black/10 sm:grid-cols-2" aria-label="Active task status">
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

function ObservedWork({ activity, activeTaskTitle, loading = false, error = false }) {
  if (loading || error) {
    return (
      <OverviewLoadCard
        icon={History}
        label="Active task"
        title="Progress"
        message={error ? "Current progress could not be loaded." : "Loading observed progress…"}
        error={error}
      />
    );
  }
  if (!activity) {
    return (
      <article className="app-surface relative overflow-hidden p-6 sm:p-7 xl:p-8">
        <PanelLabel icon={History}>Active task</PanelLabel>
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
  const activityTitle = prepareTaskCandidate(activity.request || activity.title);
  const latestUpdate = displayActivityText(activity.latest_update);
  const distinctActivityTitle = activityTitle
    && activityTitle.toLocaleLowerCase() !== activeTaskTitle.toLocaleLowerCase();
  const detailUrl = activity.source_card_id
    ? explainCardUrl(activity.source_card_id)
    : "/app/runs";

  return (
    <article className="app-surface relative overflow-hidden p-6 sm:p-7 xl:p-8">
      <div className="relative flex flex-wrap items-center justify-between gap-3">
        <PanelLabel icon={activity.live ? PlayCircle : History}>Active task</PanelLabel>
        <ActivityBadge activity={activity} />
      </div>

      <h2 className="relative mt-6 text-2xl font-semibold tracking-[-0.025em] text-[#171713] dark:text-white">Progress</h2>

      {distinctActivityTitle ? (
        <div className="mt-6 border-l-2 border-[#171713] pl-4 dark:border-white">
          <p className="text-[11px] font-semibold text-[#85857c]">Observed request</p>
          <h3 className="mt-1.5 text-base font-semibold leading-6 text-[#171713] dark:text-white">{activityTitle}</h3>
        </div>
      ) : null}

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
          <span className="text-[10px] text-[#85857c]">No visible blocker, conflict, or stale evidence.</span>
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
      ? "Save the current task context to preserve its exact next action."
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
                ? "This instruction is saved, but its boundary time could not be verified. Review it before continuing."
                : "This instruction was saved at the recovery boundary and remains separate from live activity."
          : latestSession
            ? "No exact next action has been saved for this task yet."
            : "No task continuation is available yet."}
      </p>
      <div className="mt-7 border-t border-[#e5e5dd] pt-5 dark:border-[#292925]">
        {checkpoint || latestSession ? (
          <a href="#continuity-checkpoint" className="group inline-flex min-h-11 items-center gap-1.5 text-xs font-semibold text-[#171713] dark:text-[#d9ff68]">
            {checkpoint ? "Review saved context" : "Save current context"}
            <ArrowRight className="h-3 w-3 transition-transform group-hover:translate-x-0.5" />
          </a>
        ) : (
          <Link to="/app/library" className="group inline-flex min-h-11 items-center gap-1.5 text-xs font-semibold text-[#171713] dark:text-[#d9ff68]">
            Choose work <ArrowRight className="h-3 w-3 transition-transform group-hover:translate-x-0.5" />
          </Link>
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
            {cards.length} visible
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
          No blocker, conflict, stale evidence, or high-risk review is currently visible.
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
      if (/^(?:screenshot\s+\d{4}-\d{2}-\d{2}\s+at\s+\d{1,2}(?:[.:]\d{2}){1,2}|codex-clipboard-[a-z0-9-]+)(?:\.(?:png|jpe?g|webp))?(?::.*)?$/i.test(plain)) return false;
      if (/(?:\/var\/folders\/|\/private\/var\/|\/temporaryitems\/|screencaptureui_)/i.test(rawLine) && /\.(?:png|jpe?g|webp)(?:["'>:]|$)/i.test(rawLine)) return false;
      return !/^(?:image\s+name\s*=|path\s*=|\[image\s+#)/i.test(plain);
    })
    .join("\n");
  const task = cleanDisplayText(raw);
  if (!task) return "";
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
