import { useEffect, useRef, useState } from "react";
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
  X,
} from "lucide-react";

import WorkspaceTopicGate from "../components/WorkspaceTopicGate";
import ProductLoadingState from "../components/ProductLoadingState";
import FloatingContextToggle from "../components/FloatingContextToggle";
import { HarnessContinuationCard } from "../components/HarnessCard";
import { HARNESS_ORDER, harnessMeta } from "../components/HarnessBrand";
import {
  useCheckpointHandoff,
  useCheckpoints,
  useContinuationProviders,
  useLatestCheckpoint,
  useOpenContinuationHarness,
  useStageContinuation,
  useSessionLibrary,
} from "../api/hooks";
import {
  useContextDigest,
  useLinkedAISessionRefresh,
} from "../context-map/api";
import {
  cleanDisplayText,
  formatTimeAgo,
  parseApiTimestamp,
  sessionIdentity,
} from "../context-map/digest";
import { copyReadySessionContextContent } from "./sessionContinuity";
import { useProductWorkspace } from "./useProductWorkspace";

export default function NowPage() {
  const [searchParams] = useSearchParams();
  const workspace = useProductWorkspace();
  const digestQuery = useContextDigest(workspace.activeWorkspaceId, { poll: true });
  const digestActivity = digestQuery.data?.activity?.primary || null;
  const requestedSourceReference = explicitSessionReference(
    searchParams.get("source_provider"),
    searchParams.get("source_session"),
  );
  const continuationDigestActivity = selectContinuationSessionActivity(
    digestQuery.data?.activity?.recent_sessions,
    digestActivity,
    requestedSourceReference,
  );
  const activeCheckpointSession = requestedSourceReference
    || activitySessionReference(continuationDigestActivity);
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
  const activitySession = activitySessionDescriptor(continuationDigestActivity);
  const libraryFallbackNeeded = !activitySession;
  const libraryQuery = useSessionLibrary(
    workspace.activeWorkspaceId,
    { enabled: checkpointSettled && libraryFallbackNeeded },
  );
  const latestSession = activitySession || selectLibrarySession(
    libraryQuery.data?.sessions,
    requestedSourceReference,
  );
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
  const continuationProvidersQuery = useContinuationProviders(
    workspace.activeWorkspaceId,
    { enabled: checkpointSettled },
  );
  const stageContinuation = useStageContinuation();
  const checkpointHandoff = useCheckpointHandoff();
  const [continuationState, setContinuationState] = useState("idle");
  const [continuationResult, setContinuationResult] = useState(null);
  const [continuationError, setContinuationError] = useState(null);
  const [pendingProvider, setPendingProvider] = useState(null);
  const [hoveredContinuationProvider, setHoveredContinuationProvider] = useState(null);
  const [sessionHandoffState, setSessionHandoffState] = useState({
    checkpointId: null,
    status: "idle",
    message: null,
  });
  const continuationRequestKey = JSON.stringify([
    workspace.activeWorkspaceId || "",
    searchParams.get("objective") || "",
    searchParams.get("objective_source") || "",
    searchParams.get("repo_path") || "",
    searchParams.get("checkpoint") || "",
    searchParams.get("checkpoint_source") || "",
    searchParams.get("source_provider") || "",
    searchParams.get("source_session") || "",
    digestQuery.data?.current_goal?.title || "",
    continuationDigestActivity?.session_title
      || continuationDigestActivity?.title
      || "",
    continuationDigestActivity?.provider
      || continuationDigestActivity?.tool
      || "",
    continuationDigestActivity?.session_id || "",
    digestQuery.data?.scope?.project_paths?.[0]
      || digestActivity?.cwd
      || latestSession?.cwd
      || primaryCheckpointQuery.data?.activity?.cwd
      || workspace.activeWorkspace?.repo_path
      || "",
    primaryCheckpointQuery.data?.sections?.goal?.[0]?.statement || "",
  ]);
  const continuationRequestKeyRef = useRef(continuationRequestKey);
  useEffect(() => {
    if (continuationRequestKeyRef.current === continuationRequestKey) return;
    continuationRequestKeyRef.current = continuationRequestKey;
    if (continuationState === "staging" || stageContinuation.isPending) return;
    setContinuationState("idle");
    setContinuationResult(null);
    setContinuationError(null);
    setPendingProvider(null);
  }, [continuationRequestKey, continuationState, stageContinuation.isPending]);
  useLinkedAISessionRefresh(
    workspace.activeWorkspaceId,
    { enabled: checkpointSettled, initialDelayMs: 30_000 },
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
  const observedActivity = continuationDigestActivity
    || (!requestedSourceReference
      ? digest.activity?.primary || fallbackActivity(digest)
      : null);
  const checkpointIsCurrent = workspaceCheckpoint?.currentness?.state === "captured";
  const activity = observedActivity || (checkpointIsCurrent ? workspaceCheckpoint?.activity : null);
  const checkpoint = activeCheckpointSession
    ? checkpointMatchesSessionReference(checkpointQuery.data, activeCheckpointSession)
      ? checkpointQuery.data
      : null
    : checkpointMatchesActivity(workspaceCheckpoint, activity)
      ? workspaceCheckpoint
      : null;
  const currentCheckpoint = checkpoint?.currentness?.state === "captured" ? checkpoint : null;
  const previousCheckpoint = (
    workspaceCheckpoint
    && workspaceCheckpoint.id !== checkpoint?.id
    && !checkpointMatchesActivity(workspaceCheckpoint, activity)
  ) ? workspaceCheckpoint : null;
  const requestedObjective = prepareTaskCandidate(
    searchParams.get("objective"),
    { authoritative: true },
  );
  const requestedObjectiveIsSourceBacked = (
    searchParams.get("objective_source") === "session"
  );
  const requestedRepoPath = String(searchParams.get("repo_path") || "").trim();
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
  const sessionCheckpoints = (checkpointHistoryQuery.data?.checkpoints || [])
    .filter((item) => (
      checkpoint
      && item.provider === checkpoint.provider
      && item.session_id === checkpoint.session_id
    ))
    .sort((left, right) => (
      Number(left.boundary?.sequence_number || 0)
      - Number(right.boundary?.sequence_number || 0)
    ));
  const sessionCompactions = sessionCheckpoints.filter(
    (item) => item.boundary?.snapshot_phase === "pre_compaction",
  );
  const latestSessionContextCandidate = [...sessionCheckpoints]
    .filter((item) => (
      ["pre_compaction", "session_tip"].includes(
        item.boundary?.snapshot_phase,
      )
    ))
    .sort(compareSessionHandoffBoundariesNewestFirst)[0] || null;
  const latestSessionContextCheckpoint = isUsableSessionHandoffCheckpoint(
    latestSessionContextCandidate,
  )
    ? latestSessionContextCandidate
    : null;
  const selectedSessionObjective = rootSessionTaskCandidate(continuationDigestActivity)
    || rootSessionTaskCandidate(latestSession);
  const checkpointObjective = prepareTaskCandidate(
    cleanRecoveryText(currentCheckpoint?.sections?.goal?.[0]?.statement),
  );
  const inferredSource = activitySessionReference(continuationDigestActivity)
    || sessionDescriptorReference(latestSession);
  // Continue must stage the exact session whose task is shown on this screen.
  // The backend can refresh that session before resolving its task, but it must
  // never replace it with a newer, unrelated provider session during staging.
  const continuationSource = !requestedCheckpointId
    ? (
        requestedSourceReference
        || (
          (!requestedObjective || requestedObjectiveIsSourceBacked)
            ? inferredSource
            : null
        )
      )
    : null;
  const continuationObjective = requestedObjective
    || selectedSessionObjective
    || (!continuationSource && (
      !requestedCheckpointId || currentCheckpoint?.id === requestedCheckpointId
    )
      ? checkpointObjective
      : "");
  const continuationLead = continuationObjective;
  const continuationLeadCandidate = prepareTaskCandidate(
    continuationLead,
    { authoritative: true },
  );
  const continuationLeadAvailable = Boolean(continuationLeadCandidate);
  const continuationRepoPath = requestedRepoPath
    || continuationDigestActivity?.cwd
    || latestSession?.cwd
    || currentCheckpoint?.activity?.cwd
    || workspace.activeWorkspace?.repo_path
    || digest.scope?.project_paths?.[0]
    || null;
  // Likewise, an automatically discovered checkpoint is context for the
  // screen, not a request to resume that immutable boundary.
  const continuationCheckpointId = requestedCheckpointId;
  const continuationLeadSourceBound = Boolean(
    continuationSource || continuationCheckpointId,
  );
  const continuationLeadResolvable = Boolean(
    continuationLeadAvailable || continuationLeadSourceBound,
  );
  const continuationAnchorAvailable = Boolean(
    continuationLeadAvailable
    || requestedObjective
    || continuationSource
    || continuationCheckpointId
    || inferredSource
    || continuationObjective
  );
  const continuationDisplayObjective = continuationLead
    || (continuationSource
      ? "Task will be resolved from the selected session"
      : continuationCheckpointId
        ? "Task will be resolved from the saved recovery point"
        : "");
  const stageTaskContinuation = async (targetProvider, providerConfig = {}) => {
    if (!workspace.activeWorkspaceId || !continuationAnchorAvailable) return;
    if (!continuationLeadResolvable) {
      setContinuationState("blocked");
      setContinuationError({
        title: "Choose work to continue",
        message: (
          "Choose a saved session or select work in Execute before loading "
          + "Project Context into a harness."
        ),
        affectedTasks: [],
        action: "Choose a session or task, then select a harness.",
      });
      return;
    }
    const exactLead = !continuationLeadSourceBound
      ? continuationLeadCandidate
      : null;
    setContinuationState("staging");
    setContinuationResult(null);
    setContinuationError(null);
    setPendingProvider(targetProvider);
    try {
      const result = await stageContinuation.mutateAsync({
        workspace_id: workspace.activeWorkspaceId,
        idempotency_key: continuationIdempotencyKey(),
        target_provider: targetProvider,
        ...(providerConfig.provider_model
          ? { provider_model: providerConfig.provider_model }
          : {}),
        ...(providerConfig.provider_effort
          ? { provider_effort: providerConfig.provider_effort }
          : {}),
        ...(exactLead ? { objective: exactLead } : {}),
        ...(continuationRepoPath ? { repo_path: continuationRepoPath } : {}),
        ...(continuationCheckpointId ? { checkpoint_id: continuationCheckpointId } : {}),
        ...(requestedCheckpointId && searchParams.get("checkpoint_source")
          ? { checkpoint_source_id: searchParams.get("checkpoint_source") }
          : {}),
        ...(continuationSource
          ? {
              source_provider: continuationSource.provider,
              source_session_id: continuationSource.sessionId,
            }
          : {}),
      });
      setContinuationResult(result);
      const blocker = continuationBlocker(result) || (
        continuationStagingConfirmed(result)
          ? null
          : {
              title: "Context staging was not confirmed",
              message: (
                "The selected harness did not return a durable awaiting-user "
                + "thread, so DaemonState will not claim that context was loaded."
              ),
              affectedTasks: continuationObjective ? [continuationObjective] : [],
              action: "Retry after context staging is available.",
            }
      );
      setContinuationError(blocker);
      setContinuationState(blocker ? "blocked" : "awaiting_user");
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
  const continueAction = actionInputsPending
      ? {
          kind: "loading",
          description: "Resolving the current task, repository, and safest continuation.",
        }
      : continuationAnchorAvailable && continuationLeadResolvable
        ? {
            kind: "continue",
            description: digestUnavailable
              ? "Live activity is unavailable. Continue will compile the workspace-wide Project Context foundation before loading the resolved task into the selected harness."
              : continuationLeadAvailable
                ? "Compile workspace-wide Project Context, reconcile the repository, then load it with the resolved task handoff into the selected harness."
                : "Resolve the lossless user lead from the selected source, then compile the objective-independent Project Context foundation and load both.",
          }
        : continuationAnchorAvailable
          ? {
              kind: "lead_required",
              description: "Choose a saved session or task before selecting a harness.",
            }
        : digestUnavailable
          ? {
              kind: "unavailable",
              description: "Current activity could not be loaded and no saved task could be resolved. Choose work before continuing.",
            }
        : {
            kind: "choose",
            description: "Choose linked work before continuing.",
          };
  const continuationProviders = resolvedContinuationProviders(continuationProvidersQuery);
  const continuationRunnable = continueAction.kind === "continue";
  const providerRetryVisible = continuationProviders.some((provider) => !provider.ready);
  const activeContinuationRun = continuationProvidersQuery.data?.active_run || null;
  const latestContinuationRun = continuationProvidersQuery.data?.latest_run || null;
  const stagedContinuationHandoff = continuationProvidersQuery.data?.staged_handoff || null;
  const latestRunMatchesCurrentTask = persistedRunMatchesContinuation(
    latestContinuationRun,
    {
      objective: continuationLead,
      source: continuationSource,
      checkpointId: requestedCheckpointId,
    },
  );
  const stagedHandoffVisible = Boolean(
    continuationState === "idle"
    && stagedContinuationHandoff
    && continuationStagingConfirmed(stagedContinuationHandoff)
    && stagedHandoffMatchesContinuation(stagedContinuationHandoff, {
      objective: continuationLead,
      source: continuationSource,
      checkpointId: requestedCheckpointId,
    })
  );
  const recoveredContinuationVisible = Boolean(
    latestContinuationRun
    && continuationState === "idle"
    && !stagedHandoffVisible
    && latestRunMatchesCurrentTask,
  );
  const recoveredContinuationResult = recoveredContinuationVisible
    ? continuationResultFromPersistedRun(latestContinuationRun)
    : null;
  const recoveredContinuationState = recoveredContinuationVisible
    ? continuationStateFromPersistedRun(latestContinuationRun)
    : null;
  const continuationWorkflowPending = (
    continuationState === "staging"
    || continuationState === "awaiting_user"
    || stageContinuation.isPending
    || stagedHandoffVisible
    || activeContinuationRun?.status === "running"
  );
  const displayedContinuationState = (
    stagedHandoffVisible
      ? "awaiting_user"
      : recoveredContinuationState || (
        continuationState === "idle" && activeContinuationRun?.status === "running"
          ? "legacy_running"
          : continuationState
      )
  );
  const displayedContinuationResult = (
    stagedHandoffVisible ? stagedContinuationHandoff : recoveredContinuationResult
  )
    || continuationResult;
  const loadedContinuationProvider = displayedContinuationState === "awaiting_user"
    ? normalizeProvider(
        displayedContinuationResult?.delivery?.provider
          || displayedContinuationResult?.run?.provider,
      )
    : "";
  const displayedContinuationError = recoveredContinuationResult
    ? continuationBlockerFromPersistedRun(latestContinuationRun)
    : continuationError;
  const carriedContextManifest = displayedContinuationResult?.preparation?.manifest
    || displayedContinuationResult?.context_manifest
    || (stagedHandoffVisible ? stagedContinuationHandoff?.context_manifest : null)
    || (stagedHandoffVisible
      ? stagedContinuationHandoff?.preparation?.manifest
      : null)
    || (recoveredContinuationVisible ? latestContinuationRun?.context_manifest : null)
    || (recoveredContinuationVisible
      ? contextPackageSummaryToManifest(latestContinuationRun?.context_package)
      : null)
    || null;
  const copyCurrentSessionContext = async () => {
    if (!workspace.activeWorkspaceId || !latestSessionContextCheckpoint) return;
    setSessionHandoffState({
      checkpointId: latestSessionContextCheckpoint.id,
      status: "copying",
      message: null,
    });
    try {
      const handoff = await checkpointHandoff.mutateAsync({
        workspaceId: workspace.activeWorkspaceId,
        checkpointId: latestSessionContextCheckpoint.id,
      });
      await writeClipboard(await copyReadySessionContextContent(handoff, {
        provider: latestSessionContextCheckpoint.provider,
        sessionId: latestSessionContextCheckpoint.session_id,
        checkpointId: latestSessionContextCheckpoint.id,
        boundarySequence: (
          latestSessionContextCheckpoint.boundary?.sequence_number
        ),
      }));
      setSessionHandoffState({
        checkpointId: latestSessionContextCheckpoint.id,
        status: "copied",
        message: null,
      });
    } catch (error) {
      setSessionHandoffState({
        checkpointId: latestSessionContextCheckpoint.id,
        status: "error",
        message: error?.message || "Session context could not be copied.",
      });
    }
  };

  return (
    <div className="app-page daemonstate-now-page relative">
      <header className="daemonstate-now-hero relative overflow-hidden rounded-[1.75rem] border border-black/10 bg-[#171713] text-white shadow-[0_24px_70px_rgba(23,23,19,0.16)] dark:border-[#292929]">
        <div className="daemonstate-now-grid pointer-events-none absolute inset-0" aria-hidden="true" />
        <div className="daemonstate-now-orbit pointer-events-none absolute -right-24 -top-32 h-80 w-80 rounded-full border border-white/10" aria-hidden="true" />
        <div className="relative px-4 pb-5 pt-4 sm:px-6 sm:pb-6 sm:pt-5 lg:px-8">
          <div className="flex justify-end">
            <FloatingContextToggle workspaceId={workspace.activeWorkspaceId} />
          </div>

          <div className="mt-3 sm:mt-4">
            <div className="max-w-3xl">
              <p className="text-xs font-black uppercase tracking-[0.18em] text-[#d9ff68]">
                Choose the next harness
              </p>
              <h1 className="mt-2 text-[clamp(2rem,4.2vw,3.25rem)] font-semibold leading-[0.96] tracking-[-0.055em] text-white">
                Continue with project context
              </h1>
              <p className="mt-3 hidden max-w-2xl text-sm leading-6 text-[#b8b8af] lg:block lg:text-[15px]">
                Choose where to continue, then load the resolved Project Context into the harness you want.
              </p>
            </div>

            <dl
              className="sr-only"
              aria-label="Selected continuation task"
            >
              <dt>Selected task</dt>
              <dd aria-label={continuationGoalDisplayText(continuationDisplayObjective)}>
                {continuationGoalDisplayText(continuationDisplayObjective)}
              </dd>
            </dl>

            <nav
              className="mx-auto mt-6 grid w-full max-w-4xl auto-rows-fr gap-4 sm:grid-cols-2"
              aria-label="Choose another continuation"
            >
              <Link
                to="/app/library"
                aria-label="Continue from an older session"
                className="group flex h-full min-h-20 items-center gap-3 rounded-2xl border border-white/[0.12] bg-white/[0.045] px-4 py-3.5 text-left backdrop-blur-md transition hover:-translate-y-0.5 hover:border-[#d9ff68]/45 hover:bg-white/[0.075] focus:outline-none focus-visible:ring-2 focus-visible:ring-[#d9ff68]/70 motion-reduce:hover:translate-y-0"
              >
                <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl border border-white/10 bg-black/15 text-[#d9ff68]">
                  <History className="h-4 w-4" aria-hidden="true" />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block text-sm font-semibold text-white">Continue from an older session</span>
                  <span className="mt-1 block text-[11px] leading-4 text-white/50">Browse saved sessions in Library.</span>
                </span>
                <ArrowRight className="h-4 w-4 shrink-0 text-white/35 transition-transform group-hover:translate-x-0.5 group-hover:text-[#d9ff68]" aria-hidden="true" />
              </Link>
              <Link
                to="/app/execute"
                aria-label="Continue to a different session or harness"
                className="group flex h-full min-h-20 items-center gap-3 rounded-2xl border border-white/[0.12] bg-white/[0.045] px-4 py-3.5 text-left backdrop-blur-md transition hover:-translate-y-0.5 hover:border-[#d9ff68]/45 hover:bg-white/[0.075] focus:outline-none focus-visible:ring-2 focus-visible:ring-[#d9ff68]/70 motion-reduce:hover:translate-y-0"
              >
                <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl border border-white/10 bg-black/15 text-[#d9ff68]">
                  <Layers3 className="h-4 w-4" aria-hidden="true" />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block text-sm font-semibold text-white">Continue to a different session or harness</span>
                  <span className="mt-1 block text-[11px] leading-4 text-white/50">Assemble the workspace envelope in Execute.</span>
                </span>
                <ArrowRight className="h-4 w-4 shrink-0 text-white/35 transition-transform group-hover:translate-x-0.5 group-hover:text-[#d9ff68]" aria-hidden="true" />
              </Link>
            </nav>

            <div
              className="daemonstate-harness-fan relative -mx-4 mt-4 flex snap-x snap-mandatory items-stretch justify-start gap-4 overflow-x-auto overscroll-x-contain pb-5 pt-2 sm:-mx-6 md:mx-auto md:max-w-4xl md:snap-none md:gap-0 md:overflow-visible md:px-0 md:py-0"
              aria-label="Continuation harnesses"
              onMouseLeave={() => setHoveredContinuationProvider(null)}
            >
              {continuationProviders.map((provider, index) => {
                const hoverIndex = continuationProviders.findIndex(
                  (candidate) => (
                    candidate.provider === hoveredContinuationProvider
                  ),
                );
                const hovered = hoveredContinuationProvider === provider.provider;
                const pending = pendingProvider === provider.provider;
                const distanceFromHover = hoverIndex >= 0 ? index - hoverIndex : 0;
                const translateX = hoverIndex >= 0 && !hovered
                  ? distanceFromHover * 24
                  : 0;
                const translateY = hovered || pending
                  ? -18
                  : Math.abs(distanceFromHover) * 5;
                return (
                  <HarnessContinuationCard
                    key={provider.provider}
                    provider={provider}
                    index={index}
                    hovered={hovered}
                    translateX={translateX}
                    translateY={translateY}
                    pending={pending}
                    contextLoaded={loadedContinuationProvider === provider.provider}
                    workflowPending={continuationWorkflowPending}
                    taskReady={continuationRunnable}
                    taskRequirement={continueAction.description}
                    onHover={() => setHoveredContinuationProvider(provider.provider)}
                    onContinue={stageTaskContinuation}
                  />
                );
              })}
            </div>

            <div className="mt-4 flex flex-col justify-between gap-3 sm:flex-row sm:items-center">
              <div className="flex flex-wrap items-center gap-2">
                <span className="rounded-full border border-[#d9ff68]/30 bg-[#d9ff68]/10 px-2.5 py-1 text-xs font-semibold text-[#d9ff68]">
                  Automatic reconciliation
                </span>
                {requestedCheckpointId ? (
                  <span className="rounded-full border border-white/15 bg-white/[0.04] px-2.5 py-1 text-xs font-semibold text-[#c5c5bc]">
                    Recovery request · {requestedCheckpointId}
                  </span>
                ) : null}
                {providerRetryVisible ? (
                  <button
                    type="button"
                    onClick={() => (
                      continuationProvidersQuery.refreshReadiness
                      || continuationProvidersQuery.refetch
                    )?.()}
                    disabled={continuationProvidersQuery.isFetching}
                    className="inline-flex min-h-11 items-center gap-1.5 rounded-full border border-white/15 bg-white/[0.04] px-3 text-xs font-semibold text-[#d0d0c8] transition-colors hover:border-white/30 hover:text-white disabled:cursor-wait disabled:opacity-60"
                  >
                    <RefreshCw
                      className={`h-3.5 w-3.5 ${continuationProvidersQuery.isFetching ? "animate-spin motion-reduce:animate-none" : ""}`}
                      aria-hidden="true"
                    />
                    {continuationProvidersQuery.isFetching
                      ? "Checking readiness…"
                      : "Retry provider readiness"}
                  </button>
                ) : null}
              </div>
              {continueAction.kind === "choose" || continueAction.kind === "unavailable" ? (
                <Link to="/app/library" className="group inline-flex min-h-11 items-center gap-1.5 text-xs font-semibold text-[#d9ff68]">
                  Choose work to continue
                  <ArrowRight className="h-3.5 w-3.5 transition-transform motion-reduce:transition-none group-hover:translate-x-0.5" aria-hidden="true" />
                </Link>
              ) : null}
            </div>
            <p className="mt-3 text-xs leading-5 text-[#97978f]">{continueAction.description}</p>
            <div className="mt-3 max-w-3xl">
              <ContinuationWorkflowStatus
                state={displayedContinuationState}
                result={displayedContinuationResult}
                blocker={displayedContinuationError}
                activeRun={activeContinuationRun}
                workspaceId={workspace.activeWorkspaceId}
                targetProvider={pendingProvider}
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
            <p className="mt-1 text-xs leading-5 opacity-75">
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

      <CarriedContextPanel
        checkpoint={checkpoint}
        previousCheckpoint={previousCheckpoint}
        sessionCompactions={sessionCompactions}
        manifest={carriedContextManifest}
        result={displayedContinuationResult}
        latestSession={latestSession}
        objective={continuationDisplayObjective}
        sessionHandoffCheckpoint={latestSessionContextCheckpoint}
        sessionHandoffState={sessionHandoffState}
        sessionHandoffPending={checkpointHandoff.isPending}
        onCopySessionContext={copyCurrentSessionContext}
        isLoading={
          digestPending
          || !checkpointSettled
        }
        error={checkpointQuery.error || workspaceCheckpointQuery.error}
      />
    </div>
  );
}

const CONTEXT_GROUP_META = {
  goal: {
    label: "Goal",
    shortLabel: "Goal",
    color: "#d9ff68",
    soft: "rgba(217,255,104,0.14)",
  },
  current_state: {
    label: "Current state",
    shortLabel: "Current",
    color: "#b8b8af",
    soft: "rgba(184,184,175,0.13)",
  },
  next_action: {
    label: "Next action",
    shortLabel: "Next",
    color: "#d9ff68",
    soft: "rgba(217,255,104,0.14)",
  },
  instructions: {
    label: "Task frame",
    shortLabel: "Task",
    color: "#d9ff68",
    soft: "rgba(217,255,104,0.14)",
  },
  decisions_and_invariants: {
    label: "Decisions",
    shortLabel: "Decisions",
    color: "#8db7d1",
    soft: "rgba(141,183,209,0.14)",
  },
  code_and_tests: {
    label: "Relevant code",
    shortLabel: "Code",
    color: "#75baa3",
    soft: "rgba(117,186,163,0.14)",
  },
  blockers_and_questions: {
    label: "Blockers",
    shortLabel: "Blockers",
    color: "#e2a86d",
    soft: "rgba(226,168,109,0.14)",
  },
  prior_failures: {
    label: "Prior attempts",
    shortLabel: "Attempts",
    color: "#d98a84",
    soft: "rgba(217,138,132,0.14)",
  },
  verification: {
    label: "Verification plan",
    shortLabel: "Checks",
    color: "#b3a0d8",
    soft: "rgba(179,160,216,0.14)",
  },
  supporting_context: {
    label: "Supporting context",
    shortLabel: "Supporting",
    color: "#b8b8af",
    soft: "rgba(184,184,175,0.13)",
  },
  package_frame: {
    label: "Package framing",
    shortLabel: "Framing",
    color: "#73736b",
    soft: "rgba(115,115,107,0.16)",
  },
};

const CHECKPOINT_GROUPS = [
  ["goal", "Task goal", "instructions", "Task"],
  ["progress", "Current state", "supporting_context", "Current"],
  ["decisions", "Decisions", "decisions_and_invariants", "Decisions"],
  ["relevant_files", "Relevant files", "code_and_tests", "Files"],
  ["blockers", "Blockers", "blockers_and_questions", "Blockers"],
  ["failed_attempts", "Prior attempts", "prior_failures", "Attempts"],
  ["verification", "Verification", "verification", "Checks"],
  ["exact_next_action", "Next action", "instructions", "Next"],
];

function CarriedContextPanel({
  checkpoint,
  previousCheckpoint,
  sessionCompactions,
  manifest,
  result,
  latestSession,
  objective,
  sessionHandoffCheckpoint,
  sessionHandoffState,
  sessionHandoffPending,
  onCopySessionContext,
  isLoading,
  error,
}) {
  const [drawer, setDrawer] = useState(null);
  const drawerRef = useRef(null);
  const closeButtonRef = useRef(null);
  const returnFocusRef = useRef(null);
  const snapshotScrollerRef = useRef(null);
  const displayedSessionHandoffState = (
    sessionHandoffState?.checkpointId === sessionHandoffCheckpoint?.id
      ? sessionHandoffState
      : { status: "idle", message: null }
  );

  useEffect(() => {
    if (!drawer) return undefined;
    const previousOverflow = document.body.style.overflow;
    const appScroll = document.querySelector("[data-app-scroll-container]");
    const previousAppOverflow = appScroll?.style.overflow;
    document.body.style.overflow = "hidden";
    if (appScroll) appScroll.style.overflow = "hidden";
    closeButtonRef.current?.focus();
    const handleKeyDown = (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setDrawer(null);
        return;
      }
      if (event.key !== "Tab" || !drawerRef.current) return;
      const focusable = Array.from(drawerRef.current.querySelectorAll(
        "button:not([disabled]), a[href], [tabindex]:not([tabindex='-1'])",
      ));
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      if (appScroll) appScroll.style.overflow = previousAppOverflow || "";
      document.removeEventListener("keydown", handleKeyDown);
      returnFocusRef.current?.focus?.();
    };
  }, [drawer]);

  useEffect(() => {
    const scroller = snapshotScrollerRef.current;
    const activeSnapshot = scroller?.querySelector('[aria-current="step"]');
    if (!scroller || !activeSnapshot) return;
    const inlineEndPadding = 24;
    const activeInlineEnd = activeSnapshot.offsetLeft + activeSnapshot.offsetWidth + inlineEndPadding;
    const visibleInlineEnd = scroller.scrollLeft + scroller.clientWidth;
    if (activeInlineEnd > visibleInlineEnd) {
      scroller.scrollLeft = Math.max(0, activeInlineEnd - scroller.clientWidth);
    }
  }, [checkpoint?.id, sessionCompactions?.length]);

  const openDrawer = (nextDrawer, trigger) => {
    returnFocusRef.current = trigger || document.activeElement;
    setDrawer(nextDrawer);
  };

  if (isLoading) {
    return <CarriedContextLoading />;
  }

  const compiled = Boolean(
    manifest
    && Array.isArray(manifest.selected_context)
    && manifest.token_accounting,
  );
  const summaryOnly = manifest?.summary_only === true;
  const staged = (
    String(result?.status || "").trim().toLocaleLowerCase() === "awaiting_user"
    || ["staged", "loaded", "awaiting_user"].includes(
      String(result?.delivery?.status || "").trim().toLocaleLowerCase(),
    )
  );
  const delivered = summaryOnly || result?.delivery?.status === "delivered";
  const groups = compiled
    ? manifestContextGroups(manifest)
    : checkpointContextGroups(checkpoint);
  const selectedItems = compiled ? manifest.selected_context : groups.flatMap((group) => group.items);
  const packageBrief = contextPackageBrief({
    groups,
    checkpoint,
    objective,
    compiled,
  });
  const briefGroupIds = new Set(packageBrief.map((item) => item.group?.id).filter(Boolean));
  const counterGroups = groups.filter((group) => !briefGroupIds.has(group.id));
  const populatedGroups = groups.filter((group) => group.items.length);
  const excludedItems = compiled && Array.isArray(manifest.excluded_context)
    ? manifest.excluded_context
    : [];
  const tokenAccounting = manifest?.token_accounting || {};
  const renderedTokens = Number(tokenAccounting.rendered_tokens || 0);
  const tokenBudget = Number(tokenAccounting.budget || manifest?.target_model?.context_budget_tokens || 0);
  const boundary = checkpoint?.boundary || {};
  const currentness = checkpoint?.currentness?.state || "unknown";
  const sourceProvider = continuationProviderLabel(
    manifest?.continuation?.source_provider
      || manifest?.continuation?.provider
      || result?.preparation?.source_session?.provider
      || checkpoint?.provider
      || latestSession?.connector_type,
    "Linked session",
  );
  const deliveryProvider = continuationProviderLabel(
    result?.delivery?.provider || result?.run?.provider,
    "Target harness",
  );
  const contract = continuationContractView({ result });
  const snapshotItems = uniqueContextSnapshots(checkpoint, sessionCompactions);
  const visibleSnapshotItems = snapshotItems.slice(-4);
  const hiddenSnapshotCount = Math.max(0, snapshotItems.length - visibleSnapshotItems.length);
  const previewCount = selectedItems.length;
  const statusTone = currentness === "captured"
    ? "border-[#cad9a1] bg-[#f0f5df] text-[#617324] dark:border-[#d9ff68]/20 dark:bg-[#d9ff68]/10 dark:text-[#d9ff68]"
    : "border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-900/60 dark:bg-amber-950/30 dark:text-amber-200";

  return (
    <section
      id="continuity-checkpoint"
      className="app-surface relative scroll-mt-24 overflow-hidden"
      aria-labelledby="carried-context-heading"
    >
      <div className="pointer-events-none absolute right-0 top-0 h-52 w-52 rounded-full bg-[#d9ff68]/[0.08] blur-3xl dark:bg-[#d9ff68]/[0.04]" aria-hidden="true" />
      <header className="relative flex flex-col gap-5 border-b border-[#deded5] px-5 py-6 dark:border-[#292925] sm:px-7 sm:py-7 lg:flex-row lg:items-start lg:justify-between lg:px-8">
        <div className="max-w-3xl">
          <PanelLabel icon={Layers3}>
            {compiled
              ? staged
                ? "Staged continuation"
                : delivered
                  ? "Compiled handoff"
                  : "Prepared handoff"
              : "Context handoff preview"}
          </PanelLabel>
          <h2 id="carried-context-heading" className="mt-3 text-[clamp(1.65rem,3vw,2.35rem)] font-semibold leading-none tracking-[-0.045em] text-[#171713] dark:text-white">
            {compiled
              ? staged
                ? "Context loaded"
                : delivered
                  ? "What carried over"
                  : "Prepared context package"
              : "Context ready for selection"}
          </h2>
          <p className="mt-3 max-w-2xl text-sm leading-6 text-[#68685f] dark:text-[#aaa9a0]">
            {compiled
              ? staged
                ? `The exact context, direction, and execution loop loaded into ${deliveryProvider}. No turn has been submitted.`
                : delivered && summaryOnly
                ? `The recorded package summary delivered to ${deliveryProvider}, with exact selection, exclusion, repository, and verification counts.`
                : delivered
                  ? `The exact context package delivered to ${deliveryProvider}, including what was selected, excluded, and verified.`
                  : "The exact context package prepared for this run. Delivery did not complete, so this is not presented as carried over."
              : checkpoint
                ? "A source-backed inventory of the saved task boundary. Nothing is presented as carried until repository reconciliation finishes. Continue uses the workspace-wide Project Context parent; Copy Session Context uses only this session’s latest captured immutable checkpoint."
                : "The linked task is ready. Continue will inspect the repository, compile the final package, and load it before you start the first turn."}
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2 lg:justify-end">
          {compiled && renderedTokens && tokenBudget ? (
            <span className="rounded-full border border-[#d7d7cf] bg-white/70 px-3 py-1.5 text-xs font-semibold tabular-nums text-[#52524b] dark:border-white/10 dark:bg-white/[0.04] dark:text-[#d0d0c8]">
              {renderedTokens.toLocaleString()} / {tokenBudget.toLocaleString()} estimated tokens
            </span>
          ) : checkpoint ? (
            <span className={`rounded-full border px-3 py-1.5 text-xs font-semibold ${statusTone}`}>
              {checkpointCurrentnessLabel(currentness)}
            </span>
          ) : null}
          {error ? (
            <span className="rounded-full border border-amber-200 bg-amber-50 px-3 py-1.5 text-xs font-semibold text-amber-800 dark:border-amber-900/60 dark:bg-amber-950/30 dark:text-amber-200">
              Refresh unavailable
            </span>
          ) : null}
          <div className="flex flex-col items-end gap-1">
            <button
              type="button"
              onClick={onCopySessionContext}
              disabled={!sessionHandoffCheckpoint || sessionHandoffPending}
              aria-label={sessionHandoffCheckpoint
                ? "Copy current session context"
                : "Current session context unavailable"}
              title={sessionHandoffCheckpoint
                ? "Copy only this session’s latest captured immutable context. No harness is launched or submitted."
                : "No usable captured context is available for the current session."}
              className="btn-secondary min-h-11 text-xs disabled:cursor-not-allowed disabled:opacity-50"
            >
              <Clipboard className="h-3.5 w-3.5" aria-hidden="true" />
              {displayedSessionHandoffState.status === "copied"
                ? "Session context copied"
                : displayedSessionHandoffState.status === "copying"
                  ? "Copying session context…"
                  : sessionHandoffCheckpoint
                    ? "Copy session context"
                    : "Session context unavailable"}
            </button>
            {displayedSessionHandoffState.status === "error" ? (
              <span role="alert" className="max-w-64 text-right text-[10px] font-semibold text-red-700 dark:text-red-300">
                {displayedSessionHandoffState.message}
              </span>
            ) : null}
          </div>
        </div>
      </header>

      <div className="relative px-5 py-6 sm:px-7 sm:py-8 lg:px-8">
        <div className="w-full">
          <div
            className="relative w-full overflow-hidden rounded-[1.35rem] border border-black/10 bg-[#171713] p-4 text-white shadow-[0_20px_55px_rgba(23,23,19,0.16)] dark:border-white/10 sm:p-5 lg:p-6"
            data-testid="context-package-card"
          >
            <div className="pointer-events-none absolute inset-0 daemonstate-now-grid opacity-40" aria-hidden="true" />
            <div className="relative">
              <div className="flex flex-wrap items-end justify-between gap-3">
                <div>
                  <p className="text-xs font-black uppercase tracking-[0.14em] text-[#d9ff68]">
                    {compiled
                      ? staged
                        ? "Loaded package"
                        : delivered
                          ? "Delivered package"
                          : "Prepared package"
                      : "Boundary inventory"}
                  </p>
                  <h3 className="mt-1.5 text-lg font-semibold tracking-[-0.025em]">
                    {compiled ? "Compiled context package" : "Saved context awaiting selection"}
                  </h3>
                  <p className="mt-2 text-xs leading-5 text-[#a9a9a1]">
                    {compiled
                      ? `${selectedItems.length + excludedItems.length} considered · ${selectedItems.length} selected · ${excludedItems.length} excluded`
                      : `${previewCount} boundary entries · selected and excluded counts are recorded at launch`}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={(event) => openDrawer({
                    title: compiled ? "Compiled package details" : "Saved boundary details",
                    subtitle: compiled
                      ? summaryOnly
                        ? "A lane-by-lane summary recovered from the recorded package."
                        : staged
                          ? "Every selected item loaded into the prepared harness thread."
                          : "Every selected item in the delivered context package."
                      : "Every item captured at the saved task boundary.",
                    items: selectedItems,
                    mode: compiled ? "selected" : "checkpoint",
                  }, event.currentTarget)}
                  className="inline-flex min-h-11 items-center gap-1.5 rounded-full border border-white/15 bg-white/[0.04] px-3 text-xs font-semibold text-[#d8d8cf] transition-colors hover:border-white/30 hover:bg-white/[0.08] hover:text-white focus:outline-none focus-visible:ring-2 focus-visible:ring-[#d9ff68]/60"
                >
                  Review context <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
                </button>
              </div>

              <div className="mt-4 space-y-2" aria-label="Continuation brief">
                {packageBrief.map((item) => (
                  <ContextBriefRow
                    key={item.id}
                    item={item}
                    compiled={compiled}
                    onOpen={item.group?.items?.length ? (event) => openDrawer({
                      title: item.label,
                      subtitle: compiled
                        ? `${item.group.items.length} selected item${item.group.items.length === 1 ? "" : "s"} supporting this brief.`
                        : `${item.group.items.length} source-backed item${item.group.items.length === 1 ? "" : "s"} captured at the saved boundary.`,
                      items: item.group.items,
                      mode: compiled ? "selected" : "checkpoint",
                    }, event.currentTarget) : null}
                  />
                ))}
              </div>

              {populatedGroups.length ? (
                <ContextCompositionPie groups={populatedGroups} compiled={compiled} />
              ) : null}

              {counterGroups.length ? (
                <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3" aria-label="Supporting context counters">
                  {counterGroups.map((group) => {
                  const provenance = contextGroupProvenance(group.items);
                  const visual = contextCategoryVisual(group);
                  return (
                    <button
                      key={group.id}
                      type="button"
                      onClick={(event) => openDrawer({
                        title: group.label,
                        subtitle: compiled
                          ? `${group.items.length} selected item${group.items.length === 1 ? "" : "s"} in this compiler lane.`
                          : `${group.items.length} item${group.items.length === 1 ? "" : "s"} captured at the saved boundary.`,
                        items: group.items,
                        mode: compiled ? "selected" : "checkpoint",
                      }, event.currentTarget)}
                      className={`group flex min-h-16 items-center justify-between gap-3 rounded-xl border px-3 py-2.5 text-left transition motion-reduce:transition-none motion-reduce:hover:translate-y-0 hover:-translate-y-0.5 hover:brightness-110 focus:outline-none focus-visible:ring-2 focus-visible:ring-[#d9ff68]/70 ${
                        group.items.length ? "" : "opacity-55 hover:opacity-85"
                      }`}
                      style={{
                        backgroundColor: visual.background,
                        borderColor: visual.border,
                      }}
                      data-context-color={visual.color}
                      data-provenance={group.items.length ? provenance.kind || "mixed" : "excluded"}
                      aria-label={`${group.label}: ${group.items.length} ${compiled ? "selected" : "saved"} record${group.items.length === 1 ? "" : "s"}. ${provenance.label}. Inspect details.`}
                    >
                      <span className="min-w-0">
                        <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ backgroundColor: visual.color }} aria-hidden="true" />
                        <span className="mt-1.5 block text-xs font-semibold leading-4 text-white">
                          {group.shortLabel || group.label}
                        </span>
                        <span className="mt-1 block text-[10px] font-semibold leading-4 text-white/60">
                          {provenance.label}
                        </span>
                      </span>
                      <span className="shrink-0 text-xl font-semibold tabular-nums tracking-[-0.03em] text-white">
                        {group.items.length}
                      </span>
                    </button>
                  );
                })}
                </div>
              ) : null}

              <ContextCountSemantics compiled={compiled} />
            </div>
          </div>
        </div>

        {snapshotItems.length ? (
          <div className="mt-5 border-t border-[#deded5] pt-5 dark:border-[#292925]">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <p className="text-xs font-semibold text-[#383832] dark:text-[#deded6]">Recovery points</p>
                <span className="rounded-full bg-[#ecece4] px-2 py-0.5 text-[10px] font-bold tabular-nums text-[#68685f] dark:bg-white/[0.06] dark:text-[#aaa9a0]">
                  {snapshotItems.length}
                </span>
              </div>
              <p className="text-xs leading-5 text-[#77776e] dark:text-[#aaa9a0]">
                Review only · the selected task does not change
              </p>
            </div>
            <div
              ref={snapshotScrollerRef}
              className="no-scrollbar -mx-1 mt-3 overflow-x-auto pb-1 pl-1 pr-6 [scroll-padding-inline-end:1.5rem]"
            >
              <ol className="flex min-w-max items-center pr-1" aria-label="Saved boundary history">
                {hiddenSnapshotCount ? (
                  <li className="flex items-center">
                    <button
                      type="button"
                      onClick={(event) => openDrawer({
                        title: "Earlier saved boundaries",
                        subtitle: `${hiddenSnapshotCount} earlier immutable ${hiddenSnapshotCount === 1 ? "boundary is" : "boundaries are"} not selected for this continuation.`,
                        items: snapshotItems.slice(0, hiddenSnapshotCount).flatMap(checkpointSnapshotItems),
                        mode: "checkpoint",
                      }, event.currentTarget)}
                      className="inline-flex min-h-11 items-center rounded-full px-2 text-xs font-semibold text-[#77776e] underline decoration-[#b8b8af] underline-offset-4 hover:text-[#171713] focus:outline-none focus-visible:ring-2 focus-visible:ring-[#95b52f]/50 dark:text-[#aaa9a0] dark:hover:text-white"
                    >
                      +{hiddenSnapshotCount} earlier
                    </button>
                    <span className="mx-1 h-px w-6 bg-[#d1d1c8] dark:bg-[#3a3a34]" aria-hidden="true" />
                  </li>
                ) : null}
                {visibleSnapshotItems.map((snapshot, index) => {
                const active = snapshot.id === checkpoint?.id;
                const time = snapshot.boundary?.occurred_at || snapshot.boundary?.captured_at;
                return (
                  <li key={snapshot.id || `${time}-${index}`} className="flex items-center">
                    {index ? <span className="mx-1 h-px w-6 bg-[#d1d1c8] dark:bg-[#3a3a34]" aria-hidden="true" /> : null}
                    <button
                      type="button"
                      onClick={(event) => openDrawer({
                        title: active ? "Current saved boundary" : "Earlier saved boundary",
                        subtitle: time ? formatBoundaryTime(time) : "Boundary time unavailable",
                        items: checkpointSnapshotItems(snapshot),
                        mode: "checkpoint",
                      }, event.currentTarget)}
                      className={`group inline-flex min-h-11 items-center gap-2 rounded-full px-2 text-xs font-semibold transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-[#95b52f]/50 ${
                        active
                          ? "text-[#171713] dark:text-white"
                          : "text-[#77776e] hover:text-[#171713] dark:text-[#aaa9a0] dark:hover:text-white"
                      }`}
                      aria-current={active ? "step" : undefined}
                      aria-label={`${active ? "Current recovery point" : "Recovery point"} · ${time ? formatBoundaryTime(time) : `Snapshot ${index + 1}`}`}
                    >
                      <span className={`grid h-4 w-4 place-items-center rounded-full border ${
                        active
                          ? "border-[#171713] bg-[#171713] dark:border-[#d9ff68] dark:bg-[#d9ff68]"
                          : "border-[#b8b8af] bg-[#fbfbf6] group-hover:border-[#68685f] dark:border-[#55554e] dark:bg-[#11110f]"
                      }`} aria-hidden="true">
                        <span className={`h-1.5 w-1.5 rounded-full ${active ? "bg-[#d9ff68] dark:bg-[#171713]" : "bg-[#b8b8af]"}`} />
                      </span>
                      <span>
                        {time ? formatSnapshotTime(time) : `Snapshot ${index + 1}`}
                        {active ? <span className="ml-1 text-[10px] font-black uppercase tracking-[0.08em] text-[#617324] dark:text-[#d9ff68]">Current</span> : null}
                      </span>
                    </button>
                  </li>
                );
                })}
              </ol>
            </div>
          </div>
        ) : previousCheckpoint ? (
          <button
            type="button"
            onClick={(event) => openDrawer({
              title: "Earlier saved context",
              subtitle: "This belongs to another task and is not selected for the current continuation.",
              items: checkpointSnapshotItems(previousCheckpoint),
              mode: "checkpoint",
            }, event.currentTarget)}
            className="mt-5 inline-flex min-h-11 items-center gap-2 text-xs font-semibold text-[#68685f] underline decoration-[#aaa99f] underline-offset-4 hover:text-[#171713] focus:outline-none focus-visible:ring-2 focus-visible:ring-[#95b52f]/50 dark:text-[#aaa9a0] dark:hover:text-white"
          >
            Inspect an earlier task snapshot <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
          </button>
        ) : null}

        {contract ? <ContinuationContractPanel contract={contract} /> : null}
      </div>

      {drawer ? (
        <div className="fixed inset-0 z-50 flex justify-end" role="presentation">
          <button
            type="button"
            className="absolute inset-0 cursor-default bg-black/45 backdrop-blur-[2px]"
            onClick={() => setDrawer(null)}
            aria-label="Dismiss context details"
          />
          <aside
            ref={drawerRef}
            role="dialog"
            aria-modal="true"
            aria-labelledby="context-detail-heading"
            aria-describedby="context-detail-description"
            className="relative z-10 flex h-full w-full max-w-xl flex-col border-l border-black/10 bg-[#fbfbf6] shadow-[-28px_0_70px_rgba(0,0,0,0.2)] dark:border-white/10 dark:bg-[#11110f]"
          >
            <header className="flex items-start justify-between gap-4 border-b border-[#deded5] px-5 py-5 dark:border-[#292925] sm:px-7">
              <div>
                <PanelLabel icon={Layers3}>Context details</PanelLabel>
                <h3 id="context-detail-heading" className="mt-2 text-xl font-semibold tracking-[-0.03em] text-[#171713] dark:text-white">{drawer.title}</h3>
                <p id="context-detail-description" className="mt-2 text-xs leading-5 text-[#68685f] dark:text-[#aaa9a0]">{drawer.subtitle}</p>
              </div>
              <button
                ref={closeButtonRef}
                type="button"
                onClick={() => setDrawer(null)}
                className="grid h-11 w-11 shrink-0 place-items-center rounded-full border border-[#d7d7cf] text-[#68685f] transition hover:border-[#aaa99f] hover:text-[#171713] focus:outline-none focus-visible:ring-2 focus-visible:ring-[#95b52f]/50 dark:border-white/10 dark:text-[#aaa9a0] dark:hover:border-white/25 dark:hover:text-white"
                aria-label="Close context details"
              >
                <X className="h-4 w-4" aria-hidden="true" />
              </button>
            </header>
            <div className="flex-1 overflow-y-auto px-5 py-5 sm:px-7">
              {drawer.items.length ? (
                <ol className="space-y-3">
                  {drawer.items.map((item, index) => (
                    <ContextDrawerItem
                      key={item.id || item.item_key || `${drawer.title}-${index}`}
                      item={item}
                      mode={drawer.mode}
                      index={index}
                      sourceContext={{
                        provider: sourceProvider,
                        occurredAt: boundary.occurred_at || boundary.captured_at || manifest?.created_at,
                      }}
                    />
                  ))}
                </ol>
              ) : (
                <div className="rounded-2xl border border-dashed border-[#cecec5] px-5 py-8 text-center dark:border-[#363631]">
                  <p className="text-sm font-semibold text-[#383832] dark:text-[#deded6]">Nothing captured here</p>
                  <p className="mt-1 text-xs leading-5 text-[#77776e] dark:text-[#aaa9a0]">The empty category is explicit; no placeholder context will be sent.</p>
                </div>
              )}
            </div>
            <footer className="border-t border-[#deded5] px-5 py-4 dark:border-[#292925] sm:px-7">
              <Link to={drawer.mode === "excluded" ? "/app/execute/inspector?view=review" : "/app/execute/inspector"} className="group inline-flex min-h-11 items-center gap-2 text-xs font-semibold text-[#171713] dark:text-[#d9ff68]">
                Open project memory <ArrowRight className="h-3.5 w-3.5 transition-transform group-hover:translate-x-0.5" aria-hidden="true" />
              </Link>
            </footer>
          </aside>
        </div>
      ) : null}
    </section>
  );
}

function ContinuationContractPanel({ contract }) {
  const summary = [
    contract.mode || "Compiled",
    `${contract.requirements.length} ${contract.requirements.length === 1 ? "requirement" : "requirements"}`,
    `${contract.verification.length} planned ${contract.verification.length === 1 ? "check" : "checks"}`,
  ].join(" · ");
  return (
    <details className="group mt-5 overflow-hidden rounded-2xl border border-[#d7d7cf] bg-white/65 open:bg-white dark:border-[#30302b] dark:bg-white/[0.025] dark:open:bg-white/[0.04]">
      <summary className="flex min-h-14 cursor-pointer list-none items-center justify-between gap-4 px-4 py-3 focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[#95b52f]/60 [&::-webkit-details-marker]:hidden sm:px-5">
        <span className="min-w-0">
          <span className="block text-sm font-semibold text-[#171713] dark:text-white">
            Run plan &amp; safeguards
          </span>
          <span className="mt-1 block text-xs leading-5 text-[#68685f] dark:text-[#aaa9a0]">
            Compiled after Continue · {summary}
          </span>
        </span>
        <ArrowRight
          className="h-4 w-4 shrink-0 text-[#77776e] transition-transform duration-200 motion-reduce:transition-none group-open:rotate-90 dark:text-[#aaa9a0]"
          aria-hidden="true"
        />
      </summary>

      <div className="border-t border-[#deded5] px-4 py-5 dark:border-[#30302b] sm:px-5 sm:py-6">
        <section aria-labelledby="authoritative-request-heading">
          <p className="text-xs font-black uppercase tracking-[0.14em] text-[#77776e] dark:text-[#aaa9a0]">
            Authoritative request
          </p>
          <h3 id="authoritative-request-heading" className="sr-only">Authoritative request</h3>
          {contract.request ? (
            <p className="mt-3 whitespace-pre-wrap rounded-xl border border-[#deded5] bg-[#f7f7f2] p-4 text-sm leading-6 text-[#292922] [overflow-wrap:anywhere] dark:border-[#30302b] dark:bg-[#11110f] dark:text-[#deded6]">
              {contract.request}
            </p>
          ) : (
            <ContractUnknown>
              No authoritative request was returned for this view. Continue will not present a synthesized replacement as fact.
            </ContractUnknown>
          )}
        </section>

        <dl className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4" aria-label="Continuation contract readiness">
          <ContractMetric
            label="Task mode"
            value={contract.mode || "Not declared"}
            detail={contract.mode
              ? "Execution authority reported by the compiler"
              : "The current response did not include task mode"}
          />
          <ContractMetric
            label="Context health"
            value={contract.qualityLabel}
            detail={contract.qualityDetail}
          />
          <ContractMetric
            label="Context readiness"
            value={contract.readinessLabel}
            detail={contract.readinessDetail}
          />
          <ContractMetric
            label="Planned verification"
            value={contract.coverageLabel}
            detail={contract.coverageDetail}
          />
        </dl>

        <div className="mt-5 grid gap-4 lg:grid-cols-2">
          <ContractList
            heading="Mandatory requirements"
            items={contract.requirements}
            empty="No atomic requirement list was reported. The UI does not infer one from historical agent text."
          />
          {contract.guidance.length ? (
            <ContractList
              heading="User guidance"
              items={contract.guidance}
              empty=""
            />
          ) : null}
          <ContractList
            heading="Authority"
            items={contract.authority}
            empty="No execution authority was reported."
          />
          <ContractList
            heading="Artifacts"
            items={contract.artifacts}
            empty="No durable artifacts or attachments were reported."
          />
          <ContractList
            heading="Verification"
            items={contract.verification}
            empty="No task-specific verification plan was reported."
          />
        </div>
      </div>
    </details>
  );
}

function ContractMetric({ label, value, detail }) {
  return (
    <div className="rounded-xl border border-[#deded5] bg-[#f7f7f2] p-4 dark:border-[#30302b] dark:bg-[#11110f]">
      <dt className="text-xs font-black uppercase tracking-[0.12em] text-[#77776e] dark:text-[#aaa9a0]">{label}</dt>
      <dd className="mt-2 text-sm font-semibold text-[#171713] dark:text-white">{value}</dd>
      <dd className="mt-1 text-xs leading-5 text-[#77776e] dark:text-[#aaa9a0]">{detail}</dd>
    </div>
  );
}

function ContractList({ heading, items, empty }) {
  return (
    <section className="rounded-xl border border-[#deded5] p-4 dark:border-[#30302b]" aria-label={heading}>
      <h3 className="text-sm font-semibold text-[#171713] dark:text-white">{heading}</h3>
      {items.length ? (
        <ol className="mt-3 space-y-2">
          {items.map((item, index) => (
            <li
              key={item.id || `${heading}-${index}`}
              className="flex gap-2.5 text-xs leading-5 text-[#52524b] dark:text-[#c6c6bd]"
            >
              <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-[#95b52f]" aria-hidden="true" />
              <span className="[overflow-wrap:anywhere]">
                {item.id ? <strong className="mr-1 text-[#292922] dark:text-white">{item.id}</strong> : null}
                {item.text}
                {item.meta ? <span className="mt-0.5 block text-[#85857c]">{item.meta}</span> : null}
              </span>
            </li>
          ))}
        </ol>
      ) : (
        <ContractUnknown>{empty}</ContractUnknown>
      )}
    </section>
  );
}

function ContractUnknown({ children }) {
  return (
    <p className="mt-3 rounded-xl border border-dashed border-[#cecec5] px-3 py-3 text-xs leading-5 text-[#77776e] dark:border-[#3a3a34] dark:text-[#aaa9a0]">
      {children}
    </p>
  );
}

function CarriedContextLoading() {
  return (
    <section className="app-surface overflow-hidden" aria-busy="true" aria-label="Loading continuation context">
      <header className="border-b border-[#deded5] px-5 py-6 dark:border-[#292925] sm:px-7 lg:px-8">
        <PanelLabel icon={Layers3}>Continuation preview</PanelLabel>
        <div className="mt-3 h-8 w-60 animate-pulse rounded-lg bg-[#e7e7df] motion-reduce:animate-none dark:bg-white/[0.07]" aria-hidden="true" />
        <div className="mt-3 h-4 w-full max-w-xl animate-pulse rounded-full bg-[#ecece5] motion-reduce:animate-none dark:bg-white/[0.05]" aria-hidden="true" />
      </header>
      <div className="px-5 py-6 sm:px-7 sm:py-8 lg:px-8">
        <div className="h-72 w-full animate-pulse rounded-[1.35rem] bg-[#20201c] motion-reduce:animate-none dark:bg-[#1a1a17]" />
      </div>
    </section>
  );
}

function ContextBriefRow({ item, compiled, onOpen }) {
  const count = item.group?.items?.length || 0;
  const visual = contextCategoryVisual(item.group);
  const content = (
    <>
      <span className="flex items-center justify-between gap-3">
        <span className="flex items-center gap-2">
          <span className="h-2 w-2 shrink-0 rounded-full" style={{ backgroundColor: visual.color }} aria-hidden="true" />
          <span className="text-[10px] font-black uppercase tracking-[0.13em] text-white/55">{item.label}</span>
        </span>
        <span className="text-[9px] font-semibold text-white/55">{item.provenance.label}</span>
      </span>
      <span className="mt-1.5 block text-xs font-semibold leading-5 text-white">
        {item.text}
      </span>
    </>
  );
  const className = "block w-full rounded-xl border px-3.5 py-3 text-left transition focus:outline-none focus-visible:ring-2 focus-visible:ring-[#d9ff68]/70";
  const style = {
    backgroundColor: visual.background,
    borderColor: visual.border,
  };
  if (!onOpen) {
    return (
      <div
        className={`${className} opacity-75`}
        style={style}
        data-context-color={visual.color}
        data-provenance={item.provenance.kind || "mixed"}
      >
        {content}
      </div>
    );
  }
  return (
    <button
      type="button"
      onClick={onOpen}
      className={`${className} hover:-translate-y-0.5 hover:brightness-110 motion-reduce:hover:translate-y-0`}
      style={style}
      data-context-color={visual.color}
      data-provenance={item.provenance.kind || "mixed"}
      aria-label={`${item.label}: ${count} ${compiled ? "selected" : "saved"} record${count === 1 ? "" : "s"}. ${item.provenance.label}. Inspect details.`}
    >
      {content}
    </button>
  );
}

function ContextCompositionPie({ groups, compiled }) {
  const total = groups.reduce((sum, group) => sum + group.items.length, 0);
  const recordLabel = compiled ? "selected" : "saved";
  const slices = [];
  let cursor = 0;

  groups.forEach((group) => {
    const count = group.items.length;
    const start = cursor / total;
    cursor += count;
    const end = cursor / total;
    const provenance = contextGroupProvenance(group.items);
    const visual = contextCategoryVisual(group);
    slices.push({
      ...group,
      count,
      start,
      end,
      provenance,
      visual,
      color: group.meta?.color || visual.color,
    });
  });

  const chartLabel = (
    `Context composition pie chart: ${total} ${recordLabel} `
    + `record${total === 1 ? "" : "s"} across ${groups.length} section${groups.length === 1 ? "" : "s"}`
  );

  return (
    <figure className="relative mt-4 grid overflow-hidden rounded-[1.35rem] border border-white/[0.1] bg-white/[0.018] p-4 shadow-[inset_0_1px_0_rgba(255,255,255,0.055)] backdrop-blur-xl sm:grid-cols-[9.5rem_minmax(0,1fr)] sm:items-center sm:gap-6 sm:p-5">
      <div className="pointer-events-none absolute -left-16 top-1/2 h-36 w-36 -translate-y-1/2 rounded-full bg-[#d9ff68]/[0.055] blur-3xl" aria-hidden="true" />

      <div className="relative mx-auto h-36 w-36 shrink-0 sm:mx-0">
        <svg
          viewBox="0 0 160 160"
          className="relative h-full w-full overflow-visible [filter:drop-shadow(0_12px_22px_rgba(0,0,0,0.2))]"
          role="img"
          aria-label={chartLabel}
          data-testid="context-composition-pie"
        >
          <defs>
            <radialGradient id="context-pie-sheen" cx="30%" cy="24%" r="76%">
              <stop offset="0%" stopColor="white" stopOpacity="0.22" />
              <stop offset="42%" stopColor="white" stopOpacity="0.04" />
              <stop offset="100%" stopColor="white" stopOpacity="0" />
            </radialGradient>
          </defs>
          <circle cx="80" cy="80" r="63" fill="rgba(255,255,255,0.035)" />
          {slices.length === 1 ? (
            <circle
              cx="80"
              cy="80"
              r="62"
              fill={slices[0].color}
              fillOpacity="0.92"
              stroke="rgba(255,255,255,0.24)"
              strokeWidth="1.25"
              data-context-pie-slice={slices[0].id}
              data-context-color={slices[0].color}
            >
              <title>{`${slices[0].label}: ${slices[0].count} ${recordLabel} record. ${slices[0].provenance.label}.`}</title>
            </circle>
          ) : (
            slices.map((slice) => (
              <path
                key={slice.id}
                d={contextPieSlicePath(slice.start, slice.end)}
                fill={slice.color}
                fillOpacity="0.92"
                stroke="rgba(255,255,255,0.24)"
                strokeWidth="1.25"
                strokeLinejoin="round"
                className="origin-center transition-[opacity,filter] duration-300 hover:opacity-100 hover:[filter:brightness(1.12)] motion-reduce:transition-none"
                data-context-pie-slice={slice.id}
                data-context-color={slice.color}
              >
                <title>{`${slice.label}: ${slice.count} ${recordLabel} record${slice.count === 1 ? "" : "s"} (${Math.round((slice.count / total) * 100)}%). ${slice.provenance.label}.`}</title>
              </path>
            ))
          )}
          <circle cx="80" cy="80" r="62" fill="url(#context-pie-sheen)" pointerEvents="none" aria-hidden="true" />
          <circle cx="80" cy="80" r="62" fill="none" stroke="rgba(255,255,255,0.2)" strokeWidth="1" aria-hidden="true" />
        </svg>
      </div>

      <figcaption className="relative mt-3 min-w-0 flex-1 text-center sm:mt-0 sm:text-left">
        <span className="block text-[10px] font-black uppercase tracking-[0.16em] text-[#d9ff68]">
          Context composition
        </span>
        <span className="mt-1.5 flex items-baseline justify-center gap-2 sm:justify-start">
          <strong className="text-3xl font-semibold leading-none tracking-[-0.055em] text-white">{total}</strong>
          <span className="text-xs font-semibold text-white/65">
            {recordLabel} record{total === 1 ? "" : "s"} · {groups.length} section{groups.length === 1 ? "" : "s"}
          </span>
        </span>
        <span className="mt-1.5 block text-[10px] leading-4 text-white/45">
          Slice size is the stored record count. Color identifies the checkpoint section.
        </span>
        <ul className="mt-3 flex flex-wrap justify-center gap-1.5 sm:justify-start" aria-label="Pie chart categories">
          {slices.map((slice) => (
            <li
              key={slice.id}
              className="inline-flex items-center gap-1.5 rounded-full border border-white/[0.1] bg-black/10 px-2.5 py-1 text-[10px] font-semibold text-white/70 backdrop-blur-md"
              data-context-color={slice.color}
            >
              <span
                className="h-1.5 w-1.5 shrink-0 rounded-full"
                style={{ backgroundColor: slice.color }}
                aria-hidden="true"
              />
              <span>{slice.shortLabel || slice.label}</span>
              <span className="tabular-nums text-white">{slice.count}</span>
            </li>
          ))}
        </ul>
      </figcaption>
    </figure>
  );
}

function contextPieSlicePath(startRatio, endRatio) {
  const center = 80;
  const radius = 62;
  const sliceRatio = endRatio - startRatio;
  const gapRatio = Math.min(0.0024, sliceRatio * 0.08);
  const start = contextPiePoint(startRatio + (gapRatio / 2), center, radius);
  const end = contextPiePoint(endRatio - (gapRatio / 2), center, radius);
  const largeArc = sliceRatio - gapRatio > 0.5 ? 1 : 0;
  return [
    `M ${center} ${center}`,
    `L ${start.x} ${start.y}`,
    `A ${radius} ${radius} 0 ${largeArc} 1 ${end.x} ${end.y}`,
    "Z",
  ].join(" ");
}

function contextPiePoint(ratio, center, radius) {
  const angle = (ratio * Math.PI * 2) - (Math.PI / 2);
  return {
    x: Number((center + (radius * Math.cos(angle))).toFixed(3)),
    y: Number((center + (radius * Math.sin(angle))).toFixed(3)),
  };
}

function ContextCountSemantics({ compiled }) {
  return (
    <p
      className="mt-4 border-t border-white/10 pt-3 text-[10px] font-semibold leading-5 text-white/55"
      aria-label="Context count semantics"
    >
      Colors identify sections. Counts are {compiled
        ? "records selected by the compiler, not all available context"
        : "records stored in this bounded checkpoint, not totals across the whole session"}; evidence status appears on each card.
    </p>
  );
}

function ContextDrawerItem({ item, mode, index, sourceContext }) {
  const title = normalizeContextNarrativeText(item.title || item.statement || item.summary)
    || `Context item ${index + 1}`;
  const summary = normalizeContextNarrativeText(
    mode === "excluded"
      ? item.reason_detail || item.reason
      : item.summary || item.statement,
  );
  const state = mode === "excluded"
    ? {
        label: "Excluded / superseded",
        kind: "excluded",
        tone: "bg-[#e8e8e0] text-[#52524b] dark:bg-white/10 dark:text-[#d0d0c8]",
      }
    : contextItemProvenance(item);
  const tokenCost = Number(item.token_cost || 0);
  const sourceView = contextItemSourceView(item, sourceContext);
  return (
    <li className="rounded-2xl border border-[#deded5] bg-white/55 p-4 dark:border-[#30302b] dark:bg-white/[0.025]">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <p className="max-w-[42ch] whitespace-pre-wrap text-sm font-semibold leading-5 text-[#171713] [overflow-wrap:anywhere] dark:text-white">{title}</p>
        <span className={`rounded-full px-2.5 py-1 text-xs font-bold ${state.tone}`}>{state.label}</span>
      </div>
      {summary && summary !== title ? (
        <p className="mt-2 whitespace-pre-wrap text-xs leading-5 text-[#68685f] [overflow-wrap:anywhere] dark:text-[#aaa9a0]">{summary}</p>
      ) : null}
      <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs font-medium text-[#77776e] dark:text-[#aaa9a0]">
        {item.item_type ? <span>{humanizeContextValue(item.item_type)}</span> : null}
        {item.lane ? <span>{humanizeContextValue(item.lane)}</span> : null}
        {tokenCost ? <span>{formatCompactNumber(tokenCost)} estimated tokens</span> : null}
      </div>
      <div className="mt-3 border-t border-[#e5e5dd] pt-3 text-xs leading-5 text-[#77776e] dark:border-[#30302b] dark:text-[#aaa9a0]">
        <p className="[overflow-wrap:anywhere]">
          <span className="font-semibold text-[#52524b] dark:text-[#d0d0c8]">Source: </span>
          {sourceView.label}
        </p>
        {sourceView.raw ? (
          <details className="group/raw mt-1.5">
            <summary className="inline-flex min-h-11 cursor-pointer list-none items-center gap-1 py-1 font-semibold text-[#68685f] underline decoration-[#b8b8af] underline-offset-4 focus:outline-none focus-visible:ring-2 focus-visible:ring-[#95b52f]/50 dark:text-[#aaa9a0] [&::-webkit-details-marker]:hidden">
              View raw source
              <ArrowRight className="h-3 w-3 transition-transform group-open/raw:rotate-90" aria-hidden="true" />
            </summary>
            <code className="mt-1.5 block rounded-lg bg-[#f0f0e9] px-2.5 py-2 font-mono text-[10px] leading-4 text-[#68685f] [overflow-wrap:anywhere] dark:bg-black/20 dark:text-[#aaa9a0]">
              {sourceView.raw}
            </code>
          </details>
        ) : null}
      </div>
    </li>
  );
}

function normalizeContextNarrativeText(value) {
  const raw = String(value || "");
  if (!raw.trim()) return "";
  const hadTrailingChunkMarker = /---+\s*(?:(?:\\r\\n|\\[nr]|[\r\n])+\s*)+\d{1,3}\s*$/.test(raw);
  const decoded = raw.replace(/\\r\\n|\\n|\\r/g, (token, offset, source) => {
    if (offset > 0 && source[offset - 1] === "\\") return token;
    const before = source.slice(0, offset);
    const after = source.slice(offset + token.length);
    const beforeToken = before.match(/(?:^|\s)(\S*)$/)?.[1] || "";
    if (/^[A-Za-z]:[^ \t]*$/.test(beforeToken)) return token;
    if (/\/[^/\r\n]*$/.test(before) && /^[^/\r\n]*\//.test(after)) return token;

    const prior = before.trimEnd();
    const next = after.trimStart();
    const adjacentBreak = /(?:\\r\\n|\\n|\\r)$/.test(prior)
      || /^(?:\\r\\n|\\n|\\r)/.test(next);
    const markdownBoundary = /^(?:---+(?:\s|$)|#{1,6}\s|>\s?|[-*+]\s+|\d+[.)]\s+)/.test(next);
    const proseBoundary = /[.!?:;”"'')\]}]$/.test(prior)
      && /^[“"'([{]*[A-Z0-9]/.test(next);
    return adjacentBreak || markdownBoundary || proseBoundary ? "\n" : token;
  });
  const lines = decoded.replace(/\r\n?/g, "\n").split("\n");
  const formatted = [];
  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (/^---+$/.test(line)) continue;
    if (!line) {
      if (formatted.length && formatted.at(-1) !== "") formatted.push("");
      continue;
    }
    const listMatch = line.match(/^(?:[-*+]|\d+[.)])\s+(.+)$/);
    const cleaned = cleanDisplayText(listMatch ? listMatch[1] : line);
    if (cleaned) formatted.push(listMatch ? `• ${cleaned}` : cleaned);
  }
  while (formatted.at(-1) === "") formatted.pop();
  if (hadTrailingChunkMarker && /^\d{1,3}$/.test(formatted.at(-1) || "")) {
    formatted.pop();
    while (formatted.at(-1) === "") formatted.pop();
  }
  return formatted.join("\n").trim();
}

function contextItemSourceView(item = {}, fallback = {}) {
  if (item.summary_only === true) {
    return {
      label: "Recorded package summary · item-level source not loaded",
      raw: "",
    };
  }
  const evidence = firstRecord(
    Array.isArray(item.evidence) ? item.evidence[0] : item.evidence,
    Array.isArray(item.citations) ? item.citations[0] : item.citations,
    item.citation,
  );
  const source = evidence && typeof evidence === "object" ? evidence : {};
  const locator = source.locator;
  const provider = firstText(fallback?.provider, "Linked session");
  const occurredAt = firstText(fallback?.occurredAt);
  const fallbackLabel = occurredAt
    ? `${provider} saved boundary · ${formatSnapshotTime(occurredAt)}`
    : `${provider} saved boundary`;
  if (typeof locator === "string" && locator.trim()) {
    const rawLocator = cleanDisplayText(locator);
    if (looksLikeRepositoryPath(rawLocator)) {
      return { label: `Repository · ${rawLocator}`, raw: "" };
    }
    return { label: fallbackLabel, raw: rawLocator };
  }
  if (locator && typeof locator === "object" && !Array.isArray(locator)) {
    const providerEventId = cleanDisplayText(locator.provider_event_id);
    if (providerEventId) {
      return {
        label: fallbackLabel,
        raw: `Provider event · ${providerEventId}`,
      };
    }
    const path = cleanDisplayText(locator.path || locator.file);
    const line = Number(locator.line || locator.start_line || 0);
    if (path) {
      return {
        label: `Repository · ${line > 0 ? `${path}:${line}` : path}`,
        raw: "",
      };
    }
    const cursor = cleanDisplayText(locator.source_cursor || locator.cursor);
    if (cursor) return { label: fallbackLabel, raw: `Source cursor · ${cursor}` };
    const sequence = Number(locator.sequence_number);
    if (Number.isFinite(sequence)) {
      return { label: fallbackLabel, raw: `Event sequence · ${sequence}` };
    }
  }
  const rawIdentity = cleanDisplayText(
    item.source_locator
      || item.source_url
      || item.path
      || source.url
      || source.path
      || source.event_key
      || source.session_event_id
      || source.source_document_id
      || item.source_document_id,
  );
  if (looksLikeRepositoryPath(rawIdentity)) {
    return { label: `Repository · ${rawIdentity}`, raw: "" };
  }
  return {
    label: fallbackLabel,
    raw: rawIdentity,
  };
}

function looksLikeRepositoryPath(value) {
  return /^(?:\/|(?:app|frontend|tests|scripts|docs|src|migrations|alembic)\/)/.test(String(value || ""));
}

function contextPackageSummaryToManifest(summary) {
  if (!summary || summary.state !== "delivered") return null;
  const selected = Object.entries(summary.selected_by_lane || {}).flatMap(([lane, rawCount]) => {
    const count = Math.max(0, Number(rawCount || 0));
    const meta = CONTEXT_GROUP_META[lane] || CONTEXT_GROUP_META.supporting_context;
    return Array.from({ length: count }, (_, index) => ({
      id: `summary:${lane}:${index}`,
      title: `${meta.label} item`,
      summary: "Item-level evidence is not loaded in this recovered summary.",
      item_type: "recorded_context",
      lane,
      truth_state: "unknown",
      summary_only: true,
    }));
  });
  const excluded = Object.entries(summary.excluded_by_reason || {}).flatMap(([reason, rawCount]) => {
    const count = Math.max(0, Number(rawCount || 0));
    return Array.from({ length: count }, (_, index) => ({
      id: `summary:excluded:${reason}:${index}`,
      title: humanizeContextValue(reason),
      reason,
      reason_detail: "Excluded by the compiler. Item-level evidence is not loaded in this recovered summary.",
      truth_state: "unknown",
      summary_only: true,
    }));
  });
  const tokenEstimate = summary.token_estimate || {};
  const relevantFileCount = Math.max(0, Number(summary.relevant_files_count || 0));
  const verificationCount = Math.max(0, Number(summary.verification_commands_count || 0));
  return {
    schema_version: summary.schema_version,
    summary_only: true,
    created_at: summary.created_at,
    input_fingerprint: summary.input_fingerprint,
    selected_context: selected,
    excluded_context: excluded,
    token_accounting: {
      rendered_tokens: Number(tokenEstimate.rendered || 0),
      budget: Number(tokenEstimate.budget || 0),
      remaining_tokens: Number(tokenEstimate.remaining || 0),
      within_budget: tokenEstimate.within_budget === true,
      estimation_method: tokenEstimate.method,
    },
    repo_state: {
      relevant_files: Array.from({ length: relevantFileCount }, (_, index) => ({
        path: `Recorded relevant file ${index + 1}`,
      })),
    },
    verification: {
      commands: Array.from({ length: verificationCount }, (_, index) => ({
        id: `recorded-check-${index + 1}`,
      })),
    },
  };
}

function continuationContractView({
  result,
}) {
  const preparation = result?.preparation || {};
  const executionContract = preparation.execution_contract;
  if (
    !executionContract
    || typeof executionContract !== "object"
    || Array.isArray(executionContract)
    || executionContract.schema_version !== "continuation_execution.v1"
  ) {
    return null;
  }
  const task = firstRecord(executionContract.task);
  const request = firstMultilineText(
    task?.request_verbatim,
    executionContract?.request_verbatim,
  );
  const mode = firstText(
    executionContract?.task_mode,
    executionContract?.mode,
    task?.mode,
  );

  const requirementSource = firstArray(executionContract?.requirements);
  const sourceSpanKinds = new Map(
    firstArray(executionContract?.source_spans)
      .map((span) => [
        firstText(span?.id),
        firstText(span?.kind).toLowerCase(),
      ])
      .filter(([id]) => id),
  );
  const mandatoryRequirementSource = requirementSource.filter((item) => (
    firstText(item?.priority).toLowerCase() !== "context"
  ));
  const guidanceRequirementSource = requirementSource.filter((item) => (
    firstText(item?.priority).toLowerCase() === "context"
    && firstPopulatedArray(item?.source_span_ids).some(
      (spanId) => sourceSpanKinds.get(firstText(spanId)) === "constraint",
    )
  ));
  const requirements = normalizeContractRequirements(mandatoryRequirementSource);
  const guidance = normalizeContractRequirements(guidanceRequirementSource);
  const authority = normalizeContractAuthority(executionContract?.authority);
  const artifactSource = firstArray(executionContract?.artifacts);
  const artifacts = normalizeContractArtifacts(artifactSource);
  const verificationSource = firstArray(executionContract?.verification);
  const verification = normalizeContractVerification(verificationSource);

  const score = firstFiniteNumber(
    preparation.health_score,
    preparation.quality_report?.score,
    preparation.quality?.score,
    result?.health_score,
  );
  const qualityStatus = firstText(
    preparation.quality_report?.status,
    preparation.quality?.status,
    preparation.quality_gate?.status,
    result?.quality_report?.status,
  );
  const qualityLabel = score === null
    ? (qualityStatus ? humanizeContextValue(qualityStatus) : "Not reported")
    : `${score <= 1 ? Math.round(score * 100) : Math.round(score)} / 100`;
  const qualityDetail = score === null && !qualityStatus
    ? "The response did not include a quality-gate result"
    : qualityStatus
      ? `Quality gate: ${humanizeContextValue(qualityStatus)}`
      : "Compiler health score";

  const readiness = firstRecord(
    preparation.readiness,
    result?.readiness,
    executionContract?.readiness,
  );
  const readinessValue = firstText(
    typeof preparation.readiness === "string" ? preparation.readiness : "",
    readiness?.status,
    readiness?.state,
    typeof result?.readiness === "string" ? result.readiness : "",
  );
  const blockingIssues = firstArray(
    readiness?.blocking_issues,
    preparation.quality_report?.blocking_issues,
  );
  const readinessLabel = readinessValue
    ? humanizeContextValue(readinessValue)
    : "Not reported";
  const readinessDetail = readinessValue
    ? blockingIssues.length
      ? `${blockingIssues.length} blocking ${blockingIssues.length === 1 ? "issue" : "issues"} reported`
      : "No blocking issue was included in the response"
    : "The response did not include a launch-readiness state";

  const requirementsWithMapping = mandatoryRequirementSource.filter((item) => (
    item
    && typeof item === "object"
    && firstPopulatedArray(
      item.verification_ids,
      item.verifier_ids,
      item.verification,
    ).length > 0
  )).length;
  const requirementMappingReported = mandatoryRequirementSource.some((item) => (
    item
    && typeof item === "object"
    && (
      Array.isArray(item.verification_ids)
      || Array.isArray(item.verifier_ids)
      || Array.isArray(item.verification)
    )
  ));
  const coverageLabel = requirements.length && requirementMappingReported
    ? `${requirementsWithMapping}/${requirements.length} mapped`
    : "Not reported";
  const coverageDetail = requirements.length
    ? requirementMappingReported
      ? `${verification.length} task-specific ${verification.length === 1 ? "verifier" : "verifiers"} reported`
      : `${verification.length} ${verification.length === 1 ? "check was" : "checks were"} reported without requirement mapping`
    : verification.length
      ? `${verification.length} ${verification.length === 1 ? "check was" : "checks were"} reported; atomic requirements were not`
      : "No requirement-to-proof lineage was returned";

  return {
    request,
    mode: mode ? humanizeContextValue(mode) : "",
    requirements,
    guidance,
    authority,
    artifacts,
    verification,
    qualityLabel,
    qualityDetail,
    readinessLabel,
    readinessDetail,
    coverageLabel,
    coverageDetail,
  };
}

function normalizeContractRequirements(items) {
  return items.map((item, index) => {
    if (typeof item === "string") {
      return { id: "", text: firstMultilineText(item), meta: "" };
    }
    const id = firstText(item?.id, item?.requirement_id);
    const text = firstMultilineText(item?.text, item?.statement, item?.title)
      || `Requirement ${index + 1}`;
    const priority = firstText(item?.priority);
    const verificationIds = firstPopulatedArray(
      item?.verification_ids,
      item?.verifier_ids,
      item?.verification,
    ).map((value) => (
      typeof value === "string" ? value : firstText(value?.id)
    )).filter(Boolean);
    return {
      id,
      text,
      meta: [
        priority ? humanizeContextValue(priority) : "",
        verificationIds.length
          ? `Proof: ${verificationIds.join(", ")}`
          : "",
      ].filter(Boolean).join(" · "),
    };
  }).filter((item) => item.text);
}

function normalizeContractAuthority(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return [];
  return [
    {
      id: "Filesystem",
      text: firstText(value.filesystem_mode)
        ? humanizeContextValue(value.filesystem_mode)
        : "",
      meta: "",
    },
    {
      id: "Commands",
      text: firstText(value.command_mode)
        ? humanizeContextValue(value.command_mode)
        : "",
      meta: "",
    },
    {
      id: "Product edits",
      text: typeof value.allow_product_edits === "boolean"
        ? value.allow_product_edits ? "Allowed" : "Not allowed"
        : "",
      meta: "",
    },
    {
      id: "Existing changes",
      text: typeof value.preserve_preexisting_changes === "boolean"
        ? value.preserve_preexisting_changes ? "Must preserve" : "No preservation rule"
        : "",
      meta: "",
    },
  ].filter((item) => item.text);
}

function normalizeContractArtifacts(items) {
  return items.map((item, index) => {
    if (typeof item === "string") return { id: "", text: item, meta: "" };
    const id = firstText(item?.id);
    const text = firstText(
      item?.path,
      item?.name,
      item?.title,
      item?.uri,
    ) || `Artifact ${index + 1}`;
    const kind = firstText(item?.kind, item?.mime_type, item?.type);
    const requirementIds = firstPopulatedArray(
      item?.requirement_ids,
      item?.requirements,
    ).map((value) => (
      typeof value === "string" ? value : firstText(value?.id)
    )).filter(Boolean);
    return {
      id,
      text,
      meta: [
        kind ? humanizeContextValue(kind) : "",
        item?.required === false ? "Optional" : item?.required === true ? "Required" : "",
        requirementIds.length ? `Supports ${requirementIds.join(", ")}` : "",
      ].filter(Boolean).join(" · "),
    };
  }).filter((item) => item.text);
}

function normalizeContractVerification(items) {
  return items.map((item, index) => {
    if (typeof item === "string") return { id: "", text: item, meta: "" };
    const id = firstText(item?.id, item?.verification_id);
    const argv = firstPopulatedArray(item?.command_argv, item?.argv);
    const text = argv.length
      ? argv.join(" ")
      : firstText(
          item?.command,
          item?.title,
          item?.label,
          item?.rubric,
          item?.description,
        ) || (id ? `Verifier ${id}` : `Verification ${index + 1}`);
    const type = firstText(item?.verifier_type, item?.type);
    const requirementIds = firstPopulatedArray(
      item?.requirement_ids,
      item?.requirements,
    ).map((value) => (
      typeof value === "string" ? value : firstText(value?.id)
    )).filter(Boolean);
    return {
      id,
      text,
      meta: [
        type ? humanizeContextValue(type) : "",
        requirementIds.length ? `Covers ${requirementIds.join(", ")}` : "",
      ].filter(Boolean).join(" · "),
    };
  }).filter((item) => item.text);
}

function firstRecord(...values) {
  return values.find((value) => (
    value
    && typeof value === "object"
    && !Array.isArray(value)
  )) || null;
}

function firstPopulatedArray(...values) {
  return values.find((value) => Array.isArray(value) && value.length) || [];
}

function firstArray(...values) {
  return values.find((value) => Array.isArray(value)) || [];
}

function firstText(...values) {
  for (const value of values) {
    const text = String(value ?? "").trim();
    if (text) return text;
  }
  return "";
}

function firstMultilineText(...values) {
  for (const value of values) {
    const text = String(value ?? "").replace(/\r\n?/g, "\n").trim();
    if (text) return text;
  }
  return "";
}

function firstFiniteNumber(...values) {
  for (const value of values) {
    if (value === "" || value === null || value === undefined) continue;
    const numeric = Number(value);
    if (Number.isFinite(numeric)) return numeric;
  }
  return null;
}

function manifestContextGroups(manifest) {
  const selected = Array.isArray(manifest?.selected_context) ? manifest.selected_context : [];
  const byLane = new Map();
  selected.forEach((item) => {
    const id = contextPresentationGroupId(item);
    const current = byLane.get(id) || [];
    current.push(item);
    byLane.set(id, current);
  });
  const groups = Array.from(byLane.entries()).map(([id, items]) => ({
    id,
    label: CONTEXT_GROUP_META[id].label,
    shortLabel: CONTEXT_GROUP_META[id].shortLabel,
    meta: CONTEXT_GROUP_META[id],
    items,
    weight: contextGroupWeight(items),
  }));
  return groups.sort((left, right) => right.weight - left.weight);
}

function checkpointContextGroups(checkpoint) {
  const sections = checkpoint?.sections || {};
  return CHECKPOINT_GROUPS.map(([section, label, groupId, shortLabel]) => {
    const sourceItems = Array.isArray(sections[section]) ? sections[section] : [];
    const items = sourceItems.map((item) => (
      section === "goal"
        ? { ...item, trust_zone: item.trust_zone || "trusted_human" }
        : item
    ));
    return {
      id: section,
      label,
      shortLabel,
      meta: CONTEXT_GROUP_META[groupId],
      items,
      weight: contextGroupWeight(items),
    };
  });
}

function contextPackageBrief({
  groups = [],
  checkpoint,
  objective,
  compiled = false,
} = {}) {
  const findGroup = (...ids) => groups.find((group) => ids.includes(group.id));
  const goalGroup = findGroup("goal");
  const currentGroup = findGroup("current_state", "progress");
  const nextGroup = findGroup("next_action", "exact_next_action");
  const objectiveText = contextBriefText(objective);
  const savedGoalText = contextBriefItemText(goalGroup?.items?.[0]);
  const checkpointGoalText = contextBriefItemText(checkpoint?.sections?.goal?.[0]);
  const goalText = [
    { text: objectiveText, boost: compiled ? 0 : 4 },
    { text: savedGoalText, boost: compiled ? 8 : 0 },
    { text: checkpointGoalText, boost: 0 },
  ].sort((left, right) => (
    contextGoalBriefScore(right.text) + right.boost
      - contextGoalBriefScore(left.text) - left.boost
  ))[0]?.text
    || "No task goal was captured at this boundary.";
  const goalUsesSelectedObjective = Boolean(objectiveText && goalText === objectiveText);
  const briefGoalGroup = goalUsesSelectedObjective
    ? {
        ...(goalGroup || {
          id: "goal",
          label: "Goal",
          shortLabel: "Goal",
          meta: CONTEXT_GROUP_META.goal,
        }),
        items: [{
          id: "selected-task-goal",
          statement: objectiveText,
          item_type: "authoritative_request",
          truth_state: "user_stated",
          trust_zone: "trusted_human",
        }],
      }
    : goalGroup;
  const currentText = contextBriefItemText(contextCurrentStateItem(currentGroup?.items))
    || checkpointCurrentStateBrief(checkpoint);
  const capturedNextText = contextBriefItemText(nextGroup?.items?.[0])
    || contextBriefItemText(checkpoint?.sections?.exact_next_action?.[0]);
  let nextText = usefulNextActionBrief(capturedNextText)
    ? capturedNextText
    : "No explicit next action captured.";
  if (
    nextText.toLowerCase().startsWith("continue the current request:")
    && contextBriefComparableText(nextText) === contextBriefComparableText(`Continue the current request: ${goalText}`)
  ) {
    nextText = "No explicit next action captured.";
  }
  const hasExplicitNextAction = nextText !== "No explicit next action captured.";
  const humanFallback = {
    label: "User-authoritative",
    kind: "human",
  };
  const reportedFallback = {
    label: "Agent-reported",
    kind: "reported",
  };
  return [
    {
      id: "brief-goal",
      label: "Goal",
      text: goalText,
      group: briefGoalGroup,
      provenance: briefGoalGroup?.items?.length ? contextGroupProvenance(briefGoalGroup.items) : humanFallback,
    },
    {
      id: "brief-current",
      label: "Current state",
      text: currentText,
      group: currentGroup,
      provenance: currentGroup?.items?.length
        ? contextGroupProvenance(currentGroup.items)
        : checkpoint?.activity?.changed_files?.length || checkpoint?.activity?.verification?.observed
          ? { label: "Repository-verified", kind: "observed" }
          : reportedFallback,
    },
    {
      id: "brief-next",
      label: "Next action",
      text: nextText,
      group: nextGroup,
      provenance: hasExplicitNextAction && nextGroup?.items?.length
        ? contextGroupProvenance(nextGroup.items)
        : { label: "Not captured", kind: "summary" },
    },
  ].map((item) => ({
    ...item,
    text: truncateContextBrief(item.text, compiled ? 190 : 170),
  }));
}

function checkpointCurrentStateBrief(checkpoint) {
  const latestUpdate = contextBriefText(checkpoint?.activity?.latest_update);
  if (latestUpdate) return latestUpdate;
  const changedFiles = firstPopulatedArray(
    checkpoint?.activity?.agent_changed_files,
    checkpoint?.activity?.changed_files,
  );
  const observed = Number(checkpoint?.activity?.verification?.observed || 0);
  const passed = Number(checkpoint?.activity?.verification?.passed || 0);
  if (changedFiles.length || observed) {
    const parts = [];
    if (changedFiles.length) {
      parts.push(`${changedFiles.length} changed ${changedFiles.length === 1 ? "file is" : "files are"} recorded`);
    }
    if (observed) parts.push(`${passed}/${observed} checks passed`);
    return `${parts.join(" · ")} at this saved boundary.`;
  }
  return "No current-state update was captured at this boundary.";
}

function contextCurrentStateItem(items = []) {
  return [...items]
    .map((item, index) => ({
      item,
      score: contextCurrentStateScore(contextBriefItemText(item), index),
    }))
    .sort((left, right) => right.score - left.score)[0]?.item;
}

function contextCurrentStateScore(value, index = 0) {
  const text = String(value || "");
  if (!text) return -1_000;
  const positiveSignals = text.match(/\b(?:added|built|completed|fixed|green|implemented|updated|verified|wired)\b/gi)?.length || 0;
  const verificationSignal = /\b(?:checks?|suite|tests?|validation)\b.{0,50}\bpassed\b/i.test(text) ? 1 : 0;
  const issueSignals = text.match(/\b(?:bug|can be|can still|does not|failed run|fail-open|failure mode|falsely|incorrect|never|old task|p[0-3]|report\b|renders as|should|still|substitute|without checking|without ever)\b/gi)?.length || 0;
  const pathSignals = text.match(/\/[A-Za-z0-9_.@+-]+\/|[A-Za-z0-9_.@+-]+\.(?:py|tsx?|jsx?):\d+/g)?.length || 0;
  const readableLength = text.length >= 35 && text.length <= 190 ? 24 : 0;
  return ((positiveSignals + verificationSignal) * 55)
    - (issueSignals * 70)
    - (pathSignals * 12)
    + readableLength
    + (index * 0.25);
}

function contextBriefItemText(item) {
  if (!item) return "";
  return contextBriefText(item.statement || item.summary || item.title);
}

function contextBriefText(value) {
  const withoutInternalLinks = String(value || "")
    .replace(/\[([^\]]+)\]\(chatgpt-conversation:\/\/[^)]+\)/gi, "$1")
    .replace(/chatgpt-conversation:(?:\/\/)?[^\s)]*/gi, "");
  return normalizeContextNarrativeText(withoutInternalLinks)
    .replace(/\s+/g, " ")
    .trim();
}

function truncateContextBrief(value, limit = 180) {
  const text = String(value || "").trim();
  if (text.length <= limit) return text;
  const clipped = text.slice(0, limit + 1);
  const boundary = clipped.lastIndexOf(" ");
  return `${clipped.slice(0, boundary > limit * 0.72 ? boundary : limit).trimEnd()}…`;
}

function contextBriefComparableText(value) {
  return String(value || "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

function usefulNextActionBrief(value) {
  const comparable = contextBriefComparableText(value);
  if (comparable.length < 12) return false;
  if (/\b(?:output truncated|truncated output|unknown task)\b/.test(comparable)) return false;
  return ![
    "blocker",
    "blockers",
    "current state",
    "exact next action",
    "next",
    "next action",
    "next step",
    "progress",
    "verification",
  ].includes(comparable);
}

function contextGoalBriefScore(value) {
  const text = String(value || "").trim();
  if (!text) return -1_000;
  if (/\b(?:output truncated|truncated output|current observed task|untitled task|unknown task)\b/i.test(text)) {
    return -1_000 + text.length;
  }
  const trailingFragmentPenalty = /\b(?:a|an|and|for|from|of|or|the|to|with)$/i.test(text) ? 80 : 0;
  return Math.min(text.length, 240) - trailingFragmentPenalty;
}

function checkpointSnapshotItems(snapshot) {
  return CHECKPOINT_GROUPS.flatMap(([section, label]) => (
    (snapshot?.sections?.[section] || []).map((item) => ({
      ...item,
      item_type: item.item_type || label,
    }))
  ));
}

function uniqueContextSnapshots(checkpoint, sessionCompactions = []) {
  const seen = new Set();
  return [checkpoint, ...sessionCompactions]
    .filter(Boolean)
    .filter((item) => {
      const key = item.id || `${item.provider}:${item.session_id}:${item.boundary?.occurred_at || ""}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    })
    .sort((left, right) => {
      const leftTime = new Date(
        left.boundary?.occurred_at
          || left.boundary?.captured_at
          || left.created_at
          || 0,
      ).getTime();
      const rightTime = new Date(
        right.boundary?.occurred_at
          || right.boundary?.captured_at
          || right.created_at
          || 0,
      ).getTime();
      if (
        Number.isFinite(leftTime)
        && Number.isFinite(rightTime)
        && leftTime !== rightTime
      ) {
        return leftTime - rightTime;
      }
      const leftSequence = Number(left.boundary?.sequence_number);
      const rightSequence = Number(right.boundary?.sequence_number);
      if (
        Number.isFinite(leftSequence)
        && Number.isFinite(rightSequence)
        && leftSequence !== rightSequence
      ) {
        return leftSequence - rightSequence;
      }
      return (Number.isFinite(leftTime) ? leftTime : 0)
        - (Number.isFinite(rightTime) ? rightTime : 0);
    });
}

function contextGroupWeight(items = []) {
  const tokenWeight = items.reduce((sum, item) => sum + Number(item?.token_cost || 0), 0);
  return tokenWeight > 0 ? tokenWeight : items.length;
}

function contextPresentationGroupId(item = {}) {
  const raw = [
    item.display_section,
    item.presentation_section,
    item.item_type,
    item.id,
  ].filter(Boolean).join(" ").toLowerCase();
  if (/\b(goal|objective|original[_\s-]?request|authoritative[_\s-]?request)\b/.test(raw)) {
    return "goal";
  }
  if (/\b(next[_\s-]?action|next[_\s-]?step|handoff)\b/.test(raw)) {
    return "next_action";
  }
  if (/\b(progress|current[_\s-]?state|status|working[_\s-]?state)\b/.test(raw)) {
    return "current_state";
  }
  return CONTEXT_GROUP_META[item.lane] ? item.lane : "supporting_context";
}

function contextCategoryVisual(group = {}) {
  const meta = group.meta || CONTEXT_GROUP_META.supporting_context;
  return {
    color: meta.color,
    border: `${meta.color}66`,
    background: meta.soft,
  };
}

function contextGroupProvenance(items) {
  if (!items.length) return { label: "None captured" };
  const states = items.map(contextItemProvenance);
  const labels = new Set(states.map((item) => item.label));
  if (labels.size === 1) return states[0];
  if (states.some((item) => item.kind === "review")) return { label: "Mixed · review present", kind: "review" };
  return { label: "Mixed provenance", kind: "mixed" };
}

function contextItemProvenance(item = {}) {
  if (item.summary_only === true) {
    return {
      label: "Recorded summary",
      kind: "summary",
      tone: "bg-[#e8e8e0] text-[#52524b] dark:bg-white/10 dark:text-[#d0d0c8]",
    };
  }
  const truth = String(item.truth_state || "").trim().toLowerCase();
  const trust = String(item.trust_zone || "").trim().toLowerCase();
  if (
    ["trusted_human", "user_task", "human"].includes(trust)
    || ["user_stated", "human_confirmed", "human_verified", "confirmed"].includes(truth)
  ) {
    return {
      label: "User-authoritative",
      kind: "human",
      tone: "bg-[#e8e8e0] text-[#383832] dark:bg-white/10 dark:text-white",
    };
  }
  if (
    item.provenance_verified === true
    || trust === "trusted_repo"
    || ["observed", "verified"].includes(truth)
  ) {
    return {
      label: trust === "trusted_repo" ? "Repository-backed" : "Observed evidence",
      kind: "observed",
      tone: "bg-[#eaf2cf] text-[#617324] dark:bg-[#d9ff68]/10 dark:text-[#d9ff68]",
    };
  }
  if (
    ["needs_review", "stale", "conflicted", "unknown"].includes(truth)
    || ["untrusted", "quarantined"].includes(trust)
  ) {
    return {
      label: "Needs review",
      kind: "review",
      tone: "bg-amber-100 text-amber-800 dark:bg-amber-950/50 dark:text-amber-200",
    };
  }
  return {
    label: "Agent-reported",
    kind: "reported",
    tone: "bg-amber-100 text-amber-800 dark:bg-amber-950/50 dark:text-amber-200",
  };
}

function checkpointCurrentnessLabel(value) {
  return {
    captured: "Current saved boundary",
    superseded: "Earlier saved boundary",
    historical: "Older saved boundary",
    unknown: "Boundary time unknown",
  }[value] || "Saved boundary";
}

function humanizeContextValue(value) {
  return String(value || "")
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function formatCompactNumber(value) {
  const numeric = Number(value || 0);
  if (numeric >= 1_000_000) {
    return `${(numeric / 1_000_000).toFixed(numeric >= 100_000_000 ? 0 : 1).replace(/\.0$/, "")}m`;
  }
  if (numeric >= 1_000) {
    return `${(numeric / 1_000).toFixed(numeric >= 100_000 ? 0 : 1).replace(/\.0$/, "")}k`;
  }
  return numeric.toLocaleString();
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
                <Link to="/app/library" className="group relative mt-5 inline-flex min-h-11 items-center gap-2 text-xs font-semibold">
                  Browse saved sessions <ArrowRight className="h-3.5 w-3.5 transition-transform group-hover:translate-x-1" />
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
    <section id="continuity-checkpoint" className="app-surface daemonstate-recovery-checkpoint relative scroll-mt-24">
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
              Continue reconciles this snapshot and loads the resulting continuation into the target harness without submitting a turn.
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

      <Link to="/app/execute/inspector" className="group mt-5 inline-flex min-h-11 items-center gap-2 text-xs font-semibold text-[#171713] dark:text-[#d9ff68]">
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
          <Link to="/app/library" className="inline-flex min-h-11 items-center text-xs font-semibold underline decoration-[#aaa99f] underline-offset-4">Open Library</Link>
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
  const freshness = activityFreshnessStatus({
    activity,
    checkpoint,
    loading,
    error,
  });

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
        value={freshness.value}
        detail={freshness.detail}
        tone="text-white"
      />
    </dl>
  );
}

function activityFreshnessStatus({
  activity,
  checkpoint,
  loading = false,
  error = false,
}) {
  if (loading) {
    return {
      value: "Checking freshness",
      detail: "Reading the activity timestamp",
    };
  }
  if (error) {
    return {
      value: "Time unavailable",
      detail: "Current activity could not be loaded",
    };
  }

  const activityTimestamp = activity?.updated_at;
  const checkpointTimestamp = checkpoint?.boundary?.captured_at;
  const timestamp = activityTimestamp || checkpointTimestamp;
  if (!timestamp || !parseApiTimestamp(timestamp)) {
    return {
      value: "Time unavailable",
      detail: "No valid source timestamp was recorded",
    };
  }

  const age = formatTimeAgo(timestamp);
  const exact = formatExactActivityTime(timestamp);
  if (!activityTimestamp) {
    return {
      value: `Captured ${age}`,
      detail: `Checkpoint capture time · ${exact}`,
    };
  }
  if (activity.evidence_level === "observed_run") {
    return {
      value: `Observed ${age}`,
      detail: `${activity.live ? "Latest recorded live-run event" : "Last persisted run event"} · ${exact}`,
    };
  }
  if (activity.evidence_level === "checkpoint_boundary") {
    return {
      value: `Captured ${age}`,
      detail: `Saved checkpoint boundary · ${exact}`,
    };
  }
  if (activity.recency_basis === "imported_at_fallback") {
    return {
      value: `Imported ${age}`,
      detail: `Import time; source activity time unavailable · ${exact}`,
    };
  }
  return {
    value: `Source activity ${age}`,
    detail: `Provider session timestamp · ${exact}`,
  };
}

function formatExactActivityTime(value) {
  const parsed = parseApiTimestamp(value);
  if (!parsed) return "time unavailable";
  return parsed.toLocaleString([], {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZoneName: "short",
  });
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
    : "/app/library";

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

function persistedRunMatchesContinuation(latestRun, {
  objective,
  source,
  checkpointId,
} = {}) {
  const identity = latestRun?.context_package?.continuation_identity;
  if (!identity || typeof identity !== "object") return false;
  const currentObjective = canonicalContinuationIdentityText(objective);
  const persistedObjective = canonicalContinuationIdentityText(
    identity.selected_objective,
  );
  if (!currentObjective || persistedObjective !== currentObjective) return false;
  if (checkpointId && String(identity.checkpoint_id || "") !== String(checkpointId)) {
    return false;
  }
  if (source?.provider || source?.sessionId) {
    if (
      normalizeProvider(identity.source_provider) !== normalizeProvider(source.provider)
      || String(identity.source_session_id || "") !== String(source.sessionId || "")
    ) {
      return false;
    }
  }
  return true;
}

function stagedHandoffMatchesContinuation(handoff, {
  objective,
  source,
  checkpointId,
} = {}) {
  const identity = handoff?.context_package?.continuation_identity
    || handoff?.context_manifest?.continuation
    || handoff?.preparation?.manifest?.continuation
    || null;
  if (!identity || typeof identity !== "object") return true;

  const stagedObjective = canonicalContinuationIdentityText(
    identity.selected_objective
      || identity.execution_objective
      || handoff?.preparation?.objective
      || handoff?.run?.objective,
  );
  const currentObjective = canonicalContinuationIdentityText(objective);
  if (stagedObjective && currentObjective && stagedObjective !== currentObjective) {
    return false;
  }
  if (
    checkpointId
    && identity.checkpoint_id
    && String(identity.checkpoint_id) !== String(checkpointId)
  ) {
    return false;
  }
  if (source?.provider && identity.source_provider) {
    if (
      normalizeProvider(identity.source_provider) !== normalizeProvider(source.provider)
      || (
        identity.source_session_id
        && String(identity.source_session_id) !== String(source.sessionId || "")
      )
    ) {
      return false;
    }
  }
  return true;
}

function canonicalContinuationIdentityText(value) {
  return String(value || "").trim().replace(/\s+/g, " ").toLocaleLowerCase();
}

function continuationResultFromPersistedRun(latestRun) {
  const verification = latestRun?.verification || {};
  const observed = numericCount(verification.observed);
  const passed = numericCount(verification.passed);
  const failed = numericCount(
    verification.failed,
    Math.max(0, observed - passed),
  );
  const provider = normalizeProvider(
    latestRun?.provider || latestRun?.tool,
  );
  const objective = preserveContinuationText(latestRun?.objective);
  return {
    status: latestRun?.status,
    delivery: {
      status: "recorded",
      provider,
      mode: "fresh",
      recovered: true,
      harness_session: latestRun?.harness_session || null,
    },
    run: {
      id: latestRun?.run_id,
      run_id: latestRun?.run_id,
      provider,
      status: latestRun?.status,
      changed_files: latestRun?.changed_files || [],
      verification_results: [],
      harness_session: latestRun?.harness_session || null,
    },
    outcome: {
      status: latestRun?.status,
      verified: latestRun?.verified_success === true,
      summary: latestRun?.outcome_summary,
      changed_files: latestRun?.changed_files || [],
      affected_tasks: objective ? [objective] : [],
      checks: {
        total: observed,
        passed,
        failed,
        status: failed ? "failed" : observed ? "passed" : "",
        items: [],
      },
    },
  };
}

function continuationStateFromPersistedRun(latestRun) {
  if (latestRun?.verified_success === true) return "completed";
  const status = String(latestRun?.status || "").trim().toLocaleLowerCase();
  if (["complete", "completed", "passed", "success", "succeeded"].includes(status)) {
    return "completed";
  }
  return "blocked";
}

function continuationBlockerFromPersistedRun(latestRun) {
  if (continuationStateFromPersistedRun(latestRun) !== "blocked") return null;
  const provider = continuationProviderLabel(
    latestRun?.provider || latestRun?.tool,
  );
  const objective = preserveContinuationText(latestRun?.objective);
  const verification = latestRun?.verification || {};
  const failedChecks = numericCount(verification.failed);
  const failureCode = preserveContinuationText(latestRun?.failure_code)
    .toLocaleLowerCase();
  return {
    title: `${provider} continuation failed`,
    message: preserveContinuationText(latestRun?.outcome_summary)
      || (
        failedChecks
          ? `${failedChecks} verification ${failedChecks === 1 ? "check failed" : "checks failed"}.`
          : "The run ended without a verified handoff."
    ),
    affectedTasks: objective ? [objective] : [],
    action: failureCode === "provider_run_timed_out"
      ? (
          "Review the recorded changes, finish any incomplete work, and retry "
          + "only if work remains."
        )
      : "Review the recorded run, then retry when the provider is available.",
  };
}

const CONTINUATION_STARTING_PHASE = "Resolving the task and preparing its harness context";

function resolvedContinuationProviders(query) {
  const supplied = Array.isArray(query.data?.providers) ? query.data.providers : [];
  const byProvider = new Map(
    supplied.map((item) => [normalizeProvider(item.provider), item]),
  );
  return HARNESS_ORDER.map((provider) => {
    const meta = harnessMeta(provider);
    const suppliedProvider = byProvider.get(provider);
    if (suppliedProvider) {
      const reportedReady = suppliedProvider.ready === true;
      const reportedStatus = normalizedProviderReadinessStatus(
        suppliedProvider,
        reportedReady,
      );
      const reportedCode = String(suppliedProvider.code || "").trim().toLowerCase();
      const providerReady = (
        reportedReady
        && (reportedStatus === "ready" || reportedStatus === "configured")
        && reportedCode !== "provider_cli_not_found"
      );
      const stagingSupported = suppliedProvider.context_staging_supported === true;
      const stagingUnavailable = providerReady && !stagingSupported;
      const status = stagingUnavailable ? "staging_unsupported" : reportedStatus;
      const code = stagingUnavailable
        ? "provider_context_staging_unsupported"
        : reportedCode;
      const ready = providerReady && stagingSupported;
      return {
        ...suppliedProvider,
        provider,
        name: suppliedProvider.name || meta.name,
        status,
        ready,
        context_staging_supported: stagingSupported,
        message: stagingUnavailable
          ? `${meta.name} cannot load continuation context without submitting a turn.`
          : preserveContinuationText(suppliedProvider.message),
        action: stagingUnavailable
          ? "Choose a harness that supports context staging."
          : preserveContinuationText(suppliedProvider.action),
      };
    }
    if (query.isLoading) {
      return {
        provider,
        name: meta.name,
        status: "checking",
        ready: false,
        code: "provider_readiness_loading",
        message: "Checking local installation, authentication, and context staging.",
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
          || "Context-staging readiness could not be loaded.",
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

function normalizedProviderReadinessStatus(provider, reportedReady) {
  const status = String(provider.status || "").trim().toLowerCase();
  if (status) return status;

  const code = String(provider.code || "").trim().toLowerCase();
  if (code === "provider_cli_not_found") return "provider_cli_not_found";
  if (code === "provider_configured") return "configured";
  if (code === "provider_ready") return "ready";
  if (code.includes("authentication")) return "authentication_required";
  if (code.includes("access")) return "access_required";
  if (code.includes("configuration") || code.includes("setup")) {
    return "configuration_required";
  }
  return reportedReady ? "ready" : "unavailable";
}

function ContinuationWorkflowStatus({
  state,
  result,
  blocker,
  activeRun = null,
  workspaceId = null,
  targetProvider = null,
}) {
  if (state === "idle") return null;

  const recordedRunId = result?.delivery?.run_id
    || result?.run?.run_id
    || result?.run?.id
    || activeRun?.run_id;
  const harnessSession = result?.delivery?.harness_session
    || result?.run?.harness_session
    || activeRun?.harness_session
    || null;

  if (state === "staging") {
    const provider = continuationProviderLabel(targetProvider, "the selected harness");
    return (
      <div
        role="status"
        aria-busy="true"
        className="rounded-xl border border-[#d9ff68]/25 bg-[#d9ff68]/[0.08] px-3 py-3 text-xs text-[#e7ffad]"
      >
        <p className="font-semibold">Loading continuation context into {provider}</p>
        <div className="mt-2 flex items-center gap-2 rounded-lg bg-black/15 px-2.5 py-2 text-xs leading-5 text-[#d8e6b5]">
          <RefreshCw className="h-3.5 w-3.5 shrink-0 animate-spin opacity-70 motion-reduce:animate-none" aria-hidden="true" />
          {CONTINUATION_STARTING_PHASE}
        </div>
        <p className="mt-2 text-xs leading-5 text-[#aab28f]">
          Compiling context, direction, and the execution loop. No task has been submitted.
        </p>
      </div>
    );
  }

  if (state === "awaiting_user") {
    const provider = continuationProviderLabel(
      result?.delivery?.provider
        || result?.target_provider
        || result?.run?.provider
        || harnessSession?.provider,
      "the selected harness",
    );
    return (
      <div
        role="status"
        className="rounded-xl border border-[#d9ff68]/25 bg-[#d9ff68]/[0.08] px-3 py-3 text-xs text-[#e7ffad]"
      >
        <p className="font-semibold">Context loaded in {provider}</p>
        <p className="mt-1 text-xs leading-5 text-[#c8d6a7]">
          Context, direction, and the execution loop are loaded together. Nothing has been submitted.
        </p>
        <div className="mt-2 rounded-lg bg-black/15 px-2.5 py-2 text-xs font-semibold leading-5 text-[#d8e6b5]">
          Confirm or narrow the compiled lead in {provider}, then press Enter.
        </div>
        <HarnessSessionAction
          workspaceId={workspaceId}
          runId={recordedRunId}
          session={harnessSession}
          awaitingUser
        />
      </div>
    );
  }

  if (state === "legacy_running") {
    const activeProvider = continuationProviderLabel(activeRun?.provider, "");
    const activeStartedAt = activeRun?.started_at
      ? formatTimeAgo(activeRun.started_at)
      : "";
    return (
      <div
        role="status"
        aria-busy="true"
        className="rounded-xl border border-[#d9ff68]/25 bg-[#d9ff68]/[0.08] px-3 py-3 text-xs text-[#e7ffad]"
      >
        <p className="font-semibold">
          {activeProvider
            ? `Previous ${activeProvider} continuation is still active`
            : "A previous automatic continuation is still active"}
        </p>
        {activeRun ? (
          <p className="mt-1 text-xs leading-5 text-[#c8d6a7]">
            This recorded run is still active on this machine
            {activeStartedAt ? ` · started ${activeStartedAt}` : ""}.
            Context staging will remain unavailable until it ends.
          </p>
        ) : null}
        <HarnessSessionAction
          workspaceId={workspaceId}
          runId={recordedRunId}
          session={harnessSession}
        />
      </div>
    );
  }

  if (state === "blocked") {
    const detail = blocker || {
      title: "Continuation blocked",
      message: "The target harness could not receive the continuation context.",
      affectedTasks: [],
      action: "",
    };
    const failedChecks = continuationChecks(result).items.filter(
      (item) => !continuationCheckPassed(item),
    );
    return (
      <div role="alert" className="rounded-xl border border-red-300/25 bg-red-300/[0.08] px-3 py-3 text-xs text-red-100">
        <p className="font-semibold">{detail.title}</p>
        <p className="mt-1 leading-5 opacity-85">
          {detail.message}
        </p>
        {detail.affectedTasks?.length ? (
          <div className="mt-2 border-t border-red-100/10 pt-2">
            <p className="text-xs font-semibold uppercase tracking-[0.14em] opacity-70">
              Affected tasks
            </p>
            <ul className="mt-1.5 grid gap-1 text-xs leading-5">
              {detail.affectedTasks.map((task) => (
                <li key={task} className="flex gap-2">
                  <span aria-hidden="true">•</span>
                  <span>{task}</span>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
        {failedChecks.length ? (
          <div className="mt-2 border-t border-red-100/10 pt-2">
            <p className="text-xs font-semibold uppercase tracking-[0.14em] opacity-70">
              Failed checks
            </p>
            <ul className="mt-1.5 grid gap-2 text-xs leading-5">
              {failedChecks.map((check, index) => (
                <li
                  key={check.requirement_id || check.command || index}
                  className="rounded-lg bg-black/15 px-2.5 py-2"
                >
                  <code className="break-all text-xs text-red-50">
                    {preserveContinuationText(check.command) || "Unnamed verification check"}
                  </code>
                  {continuationCheckDetail(check) ? (
                    <p className="mt-1 break-words text-xs leading-5 opacity-75">
                      {continuationCheckDetail(check)}
                    </p>
                  ) : null}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
        {detail.action ? (
          <p className="mt-2 rounded-lg bg-red-100/[0.06] px-2.5 py-2 text-xs font-semibold leading-5">
            Next: {detail.action}
          </p>
        ) : null}
        <HarnessSessionAction
          workspaceId={workspaceId}
          runId={recordedRunId}
          session={harnessSession}
          tone="danger"
        />
        {recordedRunId && !harnessSession ? (
          <p className="mt-2 text-xs leading-5 opacity-70">
            Recorded run {String(recordedRunId).slice(0, 8)} has no linked harness session.
          </p>
        ) : null}
        <p className="mt-1 text-xs leading-5 opacity-70">
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
          <p className="mt-1 text-xs leading-5 opacity-80">
            {fresh ? "Fresh " : ""}{provider} agent
            {delivery.provider_switched && sourceProvider
              ? ` · switched from ${sourceProvider}`
              : ""}
          </p>
        </div>
        <span className={`rounded-full border px-2.5 py-1 text-xs font-semibold ${
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

      <HarnessSessionAction
        workspaceId={workspaceId}
        runId={recordedRunId}
        session={harnessSession}
      />

      <dl className="mt-3 grid gap-2 border-t border-white/10 pt-3">
        <div>
          <dt className="text-xs font-semibold uppercase tracking-[0.14em] opacity-60">
            Repository changes
          </dt>
          <dd className="mt-1 leading-5">
            {changedFiles.length
              ? `${changedFiles.length} changed ${changedFiles.length === 1 ? "file" : "files"} · ${summarizeChangedFiles(changedFiles)}`
              : "No repository file changes observed."}
          </dd>
        </div>
        <div>
          <dt className="text-xs font-semibold uppercase tracking-[0.14em] opacity-60">
            Checks
          </dt>
          <dd className="mt-1 leading-5">{continuationChecksLabel(checks)}</dd>
        </div>
        {agentOutput ? (
          <div>
            <dt className="text-xs font-semibold uppercase tracking-[0.14em] opacity-60">
              Agent outcome
            </dt>
            <dd className="mt-1 leading-5">“{agentOutput}”</dd>
          </div>
        ) : null}
      </dl>

      {!verified ? (
        <p className="mt-2 border-t border-amber-200/15 pt-2 text-xs leading-5 text-amber-100/80">
          The run finished, but successful task continuation is not proven.
        </p>
      ) : null}
    </div>
  );
}

function HarnessSessionAction({
  workspaceId,
  runId,
  session,
  tone = "default",
  awaitingUser = false,
}) {
  const openHarness = useOpenContinuationHarness();
  const [feedback, setFeedback] = useState("");
  if (
    !workspaceId
    || !runId
    || !session?.session_id
    || session?.exact_session_supported !== true
  ) {
    return null;
  }

  const provider = continuationProviderLabel(session.provider);
  const danger = tone === "danger";
  const openSession = async () => {
    setFeedback("");
    try {
      await openHarness.mutateAsync({
        workspaceId,
        runId,
      });
      setFeedback(`Asked ${provider} to open this exact thread.`);
    } catch (error) {
      setFeedback(
        preserveContinuationText(
          error?.detail?.message || error?.message,
        ) || `Could not open the ${provider} run.`,
      );
    }
  };

  return (
    <div className={`mt-2 rounded-lg px-2.5 py-2 ${
      danger ? "bg-red-100/[0.06]" : "bg-black/15"
    }`}>
      <p className="text-xs leading-5 opacity-80">
        {awaitingUser
          ? session.navigation_verified
            ? `Your prepared ${provider} thread is open.`
            : session.navigation_requested
              ? `${provider} was asked to open your prepared thread.`
              : `Your prepared context has an exact ${provider} thread.`
          : session.navigation_verified
            ? `This exact ${provider} thread is open.`
            : session.navigation_requested
              ? `${provider} was asked to open this exact thread.`
              : `This recorded continuation has an exact ${provider} thread.`}
        {" "}Thread {String(session.session_id).slice(0, 8)}.
      </p>
      <button
        type="button"
        onClick={openSession}
        disabled={openHarness.isPending}
        className="mt-1.5 inline-flex min-h-11 items-center gap-1.5 text-xs font-semibold underline decoration-current/35 underline-offset-4 disabled:cursor-wait disabled:opacity-60"
      >
        {openHarness.isPending ? `Opening ${provider}…` : `Open ${provider} thread`}
        <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
      </button>
      {feedback ? (
        <p className="mt-1 text-xs leading-5 opacity-75">{feedback}</p>
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
      <p className="text-xs font-semibold uppercase tracking-[0.14em] opacity-60">
        {advanced ? "Workflow advanced after verification" : "Execution plan"}
      </p>
      <dl className="mt-2 grid gap-2 sm:grid-cols-2">
        {buckets.map(([label, tasks]) => (
          <div key={label} className="rounded-lg bg-white/[0.045] px-2.5 py-2">
            <dt className="text-xs font-black uppercase tracking-[0.13em] opacity-60">
              {label}
            </dt>
            <dd className="mt-1 text-xs font-semibold leading-5">
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

function continuationStagingConfirmed(result) {
  const delivery = result?.delivery;
  const session = delivery?.harness_session;
  return (
    String(result?.status || "").trim().toLocaleLowerCase() === "awaiting_user"
    && ["staged", "loaded", "awaiting_user"].includes(
      String(delivery?.status || "").trim().toLocaleLowerCase(),
    )
    && Boolean(String(delivery?.context_delivery || "").trim())
    && Boolean(String(session?.session_id || "").trim())
    && Boolean(
      String(
        delivery?.run_id
          || result?.run?.run_id
          || result?.run?.id
          || "",
      ).trim(),
    )
  );
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
      targetProvider: (
        result?.delivery?.provider
        || result?.target_provider
        || result?.run?.provider
      ),
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
    ) || "The target harness did not receive the continuation context.";
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
    fallbackMessage: error?.message || "The continuation context could not be loaded.",
    targetProvider,
  });
}

function normalizeContinuationBlocker(blocker, {
  fallbackTitle = "Continuation blocked",
  fallbackMessage = "The continuation workflow could not continue.",
  targetProvider = "",
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
  // Error codes are machine identifiers. Display sanitization strips
  // underscores and would collapse `provider_run_failed` before classification.
  const code = preserveContinuationText(source.code);
  const provider = source.provider
    || source.target_provider
    || source.detail?.provider
    || source.detail?.target_provider
    || targetProvider;
  const title = preserveContinuationText(
    source.title
    || source.label
    || continuationBlockerTitleFromCode(code, provider),
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

function continuationGoalDisplayText(value) {
  const text = String(value || "").trim();
  return text || "No task selected";
}

function continuationBlockerTitleFromCode(code, targetProvider = "") {
  const normalized = String(code || "").toLocaleLowerCase();
  if (
    normalized.includes("billing")
    || normalized.includes("credits")
    || normalized.includes("subscription")
  ) {
    return "Provider access or billing required";
  }
  if (normalized.includes("service_unavailable")) {
    return "Provider service unavailable";
  }
  if (normalized.includes("auth") || normalized.includes("oauth")) {
    return "Agent authentication failed";
  }
  if (normalized.includes("update") || normalized.includes("cli")) {
    return "Agent update required";
  }
  if (normalized.includes("fresh")) return "Repository freshness check failed";
  if (
    normalized.includes("verification")
    || normalized.includes("continuation_checks_failed")
  ) {
    return "Verification failed";
  }
  if (normalized.includes("goal")) return "Task goal is missing";
  if ([
    "provider_run_failed",
    "provider_run_timed_out",
    "provider_invocation_invalid",
  ].some((failureCode) => normalized.includes(failureCode))) {
    return `${continuationProviderLabel(targetProvider)} continuation failed`;
  }
  if ([
    "provider_unavailable",
    "provider_not_found",
    "provider_not_ready",
    "provider_readiness",
    "provider_missing",
    "agent_unavailable",
    "agent_not_found",
    "target_agent_unavailable",
  ].some((unavailableCode) => normalized.includes(unavailableCode))) {
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
    const runItems = Array.isArray(result?.run?.verification_results)
      ? result.run.verification_results
      : [];
    const items = (Array.isArray(supplied.items) ? supplied.items : []).map(
      (item) => {
        const matchingRunItem = runItems.find((candidate) => (
          (
            item?.requirement_id
            && candidate?.requirement_id === item.requirement_id
          )
          || (
            item?.command
            && candidate?.command === item.command
          )
        ));
        return matchingRunItem ? { ...matchingRunItem, ...item } : item;
      },
    );
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

function continuationCheckDetail(item) {
  const result = item?.result && typeof item.result === "object"
    ? item.result
    : {};
  const value = preserveContinuationText(
    result.stderr
    || result.stdout
    || item?.message
    || item?.details,
  );
  if (!value) {
    const exitCode = item?.exit_code ?? result.exit_code;
    return Number.isInteger(Number(exitCode))
      ? `Exited with code ${Number(exitCode)}.`
      : "";
  }
  const compact = value.replace(/\s+/g, " ").trim();
  const limit = 280;
  return compact.length > limit
    ? `${compact.slice(0, limit - 1).trimEnd()}…`
    : compact;
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

function explicitSessionReference(provider, sessionId) {
  const normalizedProvider = normalizeProvider(provider);
  const normalizedSessionId = String(sessionId || "").trim();
  if (!normalizedProvider || !normalizedSessionId) return null;
  return {
    provider: normalizedProvider,
    sessionId: normalizedSessionId,
  };
}

function selectContinuationSessionActivity(recentSessions, primary, requestedSource) {
  const recent = Array.isArray(recentSessions) ? recentSessions : [];
  const candidates = [...recent, primary]
    .filter(Boolean)
    .filter((activity) => activitySessionReference(activity));
  if (requestedSource) {
    return candidates.find((activity) => (
      sameSessionReference(activitySessionReference(activity), requestedSource)
    )) || null;
  }
  return [...recent]
    .filter((activity) => activitySessionReference(activity))
    .sort((left, right) => sessionActivityTimestamp(right) - sessionActivityTimestamp(left))[0]
    || (activitySessionReference(primary) ? primary : null);
}

function selectLibrarySession(sessions, requestedSource) {
  const candidates = (Array.isArray(sessions) ? sessions : [])
    .filter((session) => sessionDescriptorReference(session));
  if (requestedSource) {
    return candidates.find((session) => (
      sameSessionReference(sessionDescriptorReference(session), requestedSource)
    )) || null;
  }
  return [...candidates]
    .sort((left, right) => sessionActivityTimestamp(right) - sessionActivityTimestamp(left))[0]
    || null;
}

function sameSessionReference(left, right) {
  return Boolean(
    left
    && right
    && left.provider === right.provider
    && left.sessionId === right.sessionId
  );
}

function sessionActivityTimestamp(session) {
  const value = session?.source_activity_at
    || session?.updated_at
    || session?.ended_at
    || session?.started_at
    || session?.imported_at;
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
  const rootTaskTitle = rootSessionTaskCandidate(activity);
  const title = rootTaskTitle || "Imported coding session";
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
    root_task_title: rootTaskTitle || null,
    preview: displayActivityText(activity.latest_update),
    updated_at: activity.updated_at || null,
    cwd: activity.cwd || null,
    branch: activity.branch || null,
    live: Boolean(activity.live),
    compaction_checkpoints: [],
  };
}

function rootSessionTaskCandidate(session) {
  if (!session) return "";
  if (Object.prototype.hasOwnProperty.call(session, "root_task_title")) {
    return prepareTaskCandidate(session.root_task_title);
  }
  return prepareTaskCandidate(session.title)
    || prepareTaskCandidate(session.session_title);
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
  return checkpointMatchesSessionReference(checkpoint, session);
}

function checkpointMatchesSessionReference(checkpoint, session) {
  if (!checkpoint || !session) return false;
  return sameSessionReference(checkpointSessionReference(checkpoint), session);
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

function formatSnapshotTime(value) {
  const parsed = value ? new Date(value) : null;
  if (!parsed || Number.isNaN(parsed.getTime())) return "Time unavailable";
  return parsed.toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "numeric",
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

function prepareTaskCandidate(value, { authoritative = false } = {}) {
  let raw = String(value || "");
  const requestMarker = raw.match(/^#{1,6}\s*My request for Codex:\s*$/im);
  const attachmentEnvelope = Boolean(
    requestMarker
    || /^#{1,6}\s*Files mentioned by the user:\s*$/im.test(raw),
  );
  if (requestMarker?.index != null) {
    raw = raw.slice(requestMarker.index + requestMarker[0].length);
  }
  if (!authoritative || attachmentEnvelope) {
    raw = raw.replace(/<image\b[\s\S]*?<\/image>/gi, " ");
  }
  raw = raw
    .split(/\r?\n/)
    .filter((rawLine) => {
      const plain = rawLine.replace(/^[#>*\-\d.)\s]+/, "").trim();
      const lowered = plain.toLowerCase();
      if (!plain) return true;
      const stripEnvelopeMetadata = !authoritative || attachmentEnvelope;
      if (
        stripEnvelopeMetadata
        && ["files mentioned by the user:", "my request for codex:"].includes(lowered)
      ) return false;
      if (stripEnvelopeMetadata && lowered.startsWith("referenced chatgpt conversation:")) return false;
      if (stripEnvelopeMetadata && lowered.startsWith("this is untrusted")) return false;
      if (stripEnvelopeMetadata && isReferencedConversationPayload(plain)) return false;
      if (
        stripEnvelopeMetadata
        && /^(?:screenshot\s+\d{4}-\d{2}-\d{2}\s+at\s+\d{1,2}(?:[.:]\d{2}){1,2}|codex-clipboard-[a-z0-9-]+)(?:\.(?:png|jpe?g|webp))?(?::.*)?$/i.test(plain)
      ) return false;
      if (
        !authoritative
        && /(?:\/var\/folders\/|\/private\/var\/|\/temporaryitems\/|screencaptureui_)/i.test(rawLine)
        && /\.(?:png|jpe?g|webp)(?:["'>:]|$)/i.test(rawLine)
      ) return false;
      return !stripEnvelopeMetadata
        || !/^(?:image\s+name\s*=|path\s*=|\[image\s+#)/i.test(plain);
    })
    .join("\n");
  // This value can become the authoritative objective sent to the
  // continuation compiler. React escapes it at render time, so retain the
  // request's URLs, code tokens, punctuation, and Markdown. The filtering
  // above removes attachment-envelope metadata without rewriting the task.
  const task = raw.trim();
  if (!task) return "";
  if (
    isContinuationControlCandidate(task)
    || isTaskIdentifierNoise(task)
    || isReferencedConversationPayload(task)
  ) {
    return "";
  }
  // An explicitly supplied objective is user authority. Marker-looking
  // literals may be the very behavior under repair, so substring deny-lists
  // must never erase it after structural envelope extraction.
  if (authoritative) return task;
  const lowered = task.toLowerCase();
  const runtimeMarkers = [
    "collaboration tools cannot be called from inside",
    "you are an agent in a team of agents",
    "message type: new_task",
    "message type: message",
    "message type: final_answer",
    "<environment_context>",
    "<permissions instructions>",
    "<app-context>",
    "available tools are explicitly described",
    "target channel: commentary",
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
  return String(value || "")
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

function isUsableSessionHandoffCheckpoint(checkpoint) {
  return Boolean(
    checkpoint
    && ["pre_compaction", "session_tip"].includes(
      checkpoint.boundary?.snapshot_phase,
    )
    && checkpoint.capture_status === "complete"
    && checkpoint.projection?.valid !== false
    && checkpoint.sections?.goal?.[0]?.statement
    && checkpoint.sections?.exact_next_action?.[0]?.statement
  );
}

function compareSessionHandoffBoundariesNewestFirst(left, right) {
  const leftSequence = sessionHandoffSequence(left);
  const rightSequence = sessionHandoffSequence(right);
  if (leftSequence !== null || rightSequence !== null) {
    if (leftSequence === null) return 1;
    if (rightSequence === null) return -1;
    if (leftSequence !== rightSequence) return rightSequence - leftSequence;
  }
  const timeDelta = sessionHandoffTimestamp(right) - sessionHandoffTimestamp(left);
  if (timeDelta) return timeDelta;
  return String(right?.id || "").localeCompare(String(left?.id || ""));
}

function sessionHandoffSequence(checkpoint) {
  const raw = checkpoint?.boundary?.sequence_number;
  if (raw === null || raw === undefined || raw === "") return null;
  const value = Number(raw);
  return Number.isFinite(value) ? value : null;
}

function sessionHandoffTimestamp(checkpoint) {
  const value = checkpoint?.boundary?.occurred_at || checkpoint?.created_at;
  const parsed = value ? Date.parse(value) : Number.NaN;
  return Number.isFinite(parsed) ? parsed : 0;
}

async function writeClipboard(value) {
  if (globalThis.navigator?.clipboard?.writeText) {
    await globalThis.navigator.clipboard.writeText(value);
    return;
  }
  const textarea = document.createElement("textarea");
  textarea.value = value;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "fixed";
  textarea.style.opacity = "0";
  document.body.appendChild(textarea);
  textarea.select();
  const copied = document.execCommand?.("copy");
  textarea.remove();
  if (!copied) throw new Error("Clipboard unavailable");
}

function PageState({ title, detail, error = false }) {
  return (
    <div className={`mx-auto max-w-xl rounded-2xl border p-8 text-center shadow-[0_12px_36px_rgba(23,23,19,0.04)] dark:shadow-none ${error ? "border-red-200 bg-red-50 dark:border-red-900/60 dark:bg-red-950/30" : "border-[#d8d8cf] bg-[#fbfbf6] dark:border-[#292925] dark:bg-[#141411]"}`}>
      <h1 className="text-lg font-semibold">{title}</h1>
      {detail ? <p className="mt-2 text-sm text-[#68685f] dark:text-[#aaa9a0]">{detail}</p> : null}
    </div>
  );
}
