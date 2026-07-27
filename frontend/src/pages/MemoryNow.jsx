import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Link } from "react-router-dom";
import {
  AlertTriangle,
  ArrowRight,
  BookOpenCheck,
  Clipboard,
  FileCode2,
  RefreshCw,
  X,
} from "lucide-react";

import {
  useCaptureCheckpoint,
  useCheckpointHandoff,
  useLatestCheckpoint,
  usePrepareContinuation,
} from "../api/hooks";
import fountainPen from "../assets/fountain-pen-monochrome.png";
import HarnessDeckBackdrop from "../components/HarnessDeckBackdrop";
import ProductLoadingState from "../components/ProductLoadingState";
import WorkspaceTopicGate from "../components/WorkspaceTopicGate";
import { useContextDigest, useProjectMemory } from "../context-map/api";
import { cleanDisplayText, formatTimeAgo } from "../context-map/digest";
import {
  copyReadySessionContextContent,
  requireMatchingContentSha256,
  sessionContextQualityMessage,
} from "./sessionContinuity";
import { useProductWorkspace } from "./useProductWorkspace";

const SECTION_LINKS = {
  requirements: "/app/memory/inspector?view=active&category=requirements",
  decisions: "/app/memory/inspector?view=active&category=decisions",
  work: "/app/memory/inspector?view=active&category=work",
  blockers: "/app/memory/inspector?view=active&category=blockers",
  learnings: "/app/memory/inspector?view=active&category=learnings",
  deliveries: "/app/memory/inspector?view=active&category=deliveries",
  conflicts: "/app/memory/inspector?view=review",
  stale: "/app/memory/inspector?view=freshness",
  completed: "/app/memory/inspector?view=history&section=completed",
};

const INACTIVE_CHECKPOINT_STATES = new Set([
  "cancelled",
  "completed",
  "resolved",
  "superseded",
  "dismissed",
  "historical",
  "inactive",
  "rejected",
  "closed",
]);
const SUPPORTED_CHECKPOINT_SCHEMAS = new Set([
  "work_checkpoint.v5",
  "work_checkpoint.v6",
  "work_checkpoint.v7",
]);
const SESSION_NETWORK_RETRY_DELAYS_MS = [120, 300];
const CONTEXT_PRODUCT_CARD_CLASSNAME = "relative isolate flex min-w-0 flex-col overflow-hidden rounded-[2rem] border border-[#d8d8cf]/80 bg-[#f7f7f1]/70 p-5 shadow-[0_18px_48px_rgba(23,23,19,0.06)] backdrop-blur-xl dark:border-white/10 dark:bg-[#11110f]/70 dark:shadow-[0_22px_60px_rgba(0,0,0,0.28)] sm:p-7 lg:p-8";


export default function MemoryNow() {
  const workspace = useProductWorkspace();
  const digestQuery = useContextDigest(workspace.activeWorkspaceId, { poll: true });
  const memoryQuery = useProjectMemory(workspace.activeWorkspaceId, {
    limit: 6,
    poll: true,
  });
  const candidateActivity = digestQuery.data?.activity?.primary || null;
  const checkpointGoalAnchor = rawText(
    digestQuery.data?.current_goal?.title
    || memoryQuery.data?.current_goal?.title,
  );
  const candidateActivityGoal = rawText(
    candidateActivity?.request
    || candidateActivity?.title
    || candidateActivity?.session_title,
  );
  const checkpointActivity = (
    activityIsProjectAssigned(candidateActivity)
    && (
      !checkpointGoalAnchor
      || taskTextCompatible(checkpointGoalAnchor, candidateActivityGoal)
    )
  ) ? candidateActivity : null;
  const activityProvider = normalizeProvider(
    checkpointActivity?.provider || checkpointActivity?.tool,
  );
  const activitySessionId = visibleText(checkpointActivity?.session_id);
  const hasScopedSession = Boolean(activityProvider && activitySessionId);
  const checkpointLookupEnabled = Boolean(digestQuery.data);
  const checkpointQuery = useLatestCheckpoint(workspace.activeWorkspaceId, {
    provider: hasScopedSession ? activityProvider : null,
    sessionId: hasScopedSession ? activitySessionId : null,
    enabled: checkpointLookupEnabled,
  });
  const captureCheckpoint = useCaptureCheckpoint();
  const checkpointHandoff = useCheckpointHandoff();
  const prepareContinuation = usePrepareContinuation();
  const [previewOpen, setPreviewOpen] = useState(false);
  const [preparedContext, setPreparedContext] = useState(null);
  const [preparedContextAnchorKey, setPreparedContextAnchorKey] = useState(null);
  const [previewError, setPreviewError] = useState(null);
  const previewReturnFocusRef = useRef(null);
  const autoProjectPreviewKeyRef = useRef(null);
  const projectCompilePromiseRef = useRef(null);
  const closePreview = useCallback(() => setPreviewOpen(false), []);
  const [sessionPreviewOpen, setSessionPreviewOpen] = useState(false);
  const [sessionContext, setSessionContext] = useState(null);
  const [sessionContextSourceKey, setSessionContextSourceKey] = useState(null);
  const [sessionContextError, setSessionContextError] = useState(null);
  const [sessionContextRetryable, setSessionContextRetryable] = useState(true);
  const [sessionCopyState, setSessionCopyState] = useState("idle");
  const [projectCopyState, setProjectCopyState] = useState("idle");
  const sessionPreviewReturnFocusRef = useRef(null);
  const autoSessionPreviewKeyRef = useRef(null);
  const sessionLoadPromiseRef = useRef(null);
  const closeSessionPreview = useCallback(() => setSessionPreviewOpen(false), []);

  const projection = useMemo(() => projectMemoryNow({
    digest: digestQuery.data,
    memory: memoryQuery.data,
    checkpoint: checkpointQuery.data,
    workspace: workspace.activeWorkspace,
  }), [
    checkpointQuery.data,
    digestQuery.data,
    memoryQuery.data,
    workspace.activeWorkspace,
  ]);
  const activeAnchorRef = useRef(projection.anchorKey);
  activeAnchorRef.current = projection.anchorKey;
  const activeSessionSourceKey = JSON.stringify([
    workspace.activeWorkspaceId || "",
    activityProvider || "",
    activitySessionId || "",
  ]);
  const activeSessionSourceKeyRef = useRef(activeSessionSourceKey);
  activeSessionSourceKeyRef.current = activeSessionSourceKey;
  const currentPreparedContext = (
    preparedContextAnchorKey === projection.anchorKey
      ? preparedContext
      : null
  );
  const currentSessionContext = (
    sessionContextSourceKey === activeSessionSourceKey
      ? sessionContext
      : null
  );

  useEffect(() => {
    setPreviewOpen(false);
    setPreparedContext(null);
    setPreparedContextAnchorKey(null);
    setPreviewError(null);
    setProjectCopyState("idle");
  }, [workspace.activeWorkspaceId, projection.anchorKey]);

  useEffect(() => {
    setSessionPreviewOpen(false);
    setSessionContext(null);
    setSessionContextSourceKey(null);
    setSessionContextError(null);
    setSessionContextRetryable(true);
    setSessionCopyState("idle");
  }, [workspace.activeWorkspaceId, activeSessionSourceKey]);

  const firstLoad = (
    workspace.workspacesQuery.isLoading
    || (digestQuery.isLoading && !digestQuery.data)
    || (memoryQuery.isLoading && !memoryQuery.data)
    || (checkpointLookupEnabled && checkpointQuery.isLoading && !checkpointQuery.data)
  );
  const dataUnavailable = (
    digestQuery.isError
    && !digestQuery.data
    && memoryQuery.isError
    && !memoryQuery.data
  );
  const partialData = digestQuery.isError || memoryQuery.isError || checkpointQuery.isError;
  const projectPreviewPreparing = Boolean(
    prepareContinuation.isPending
    || (
      projection.previewAvailable
      && !currentPreparedContext
      && !previewError
    )
  );
  const sessionPreviewPreparing = Boolean(
    captureCheckpoint.isPending
    || checkpointHandoff.isPending
    || (
      hasScopedSession
      && !currentSessionContext
      && !sessionContextError
    )
  );
  const projectPreviewRetryable = projectContextErrorIsRetryable(previewError);

  const compileProjectContext = useCallback(async ({ force = false } = {}) => {
    if (!projection.previewAvailable || !workspace.activeWorkspaceId) {
      throw new Error("Project Context is unavailable until an active task is selected.");
    }
    if (currentPreparedContext && !force) return currentPreparedContext;
    const requestAnchor = projection.anchorKey;
    if (
      !force
      && projectCompilePromiseRef.current?.key === requestAnchor
    ) {
      return projectCompilePromiseRef.current.promise;
    }

    const operation = (async () => {
      const response = await prepareContinuation.mutateAsync(projection.preparePayload);
      if (activeAnchorRef.current !== requestAnchor) {
        throw new Error("The active task changed while Project Context was compiling.");
      }
      const result = validatePreparedContext(
        response,
        projection.previewIdentity,
      );
      setPreparedContext(result);
      setPreparedContextAnchorKey(requestAnchor);
      return result;
    })();
    projectCompilePromiseRef.current = { key: requestAnchor, promise: operation };
    try {
      return await operation;
    } finally {
      if (projectCompilePromiseRef.current?.promise === operation) {
        projectCompilePromiseRef.current = null;
      }
    }
  }, [
    currentPreparedContext,
    prepareContinuation,
    projection.anchorKey,
    projection.preparePayload,
    projection.previewAvailable,
    projection.previewIdentity,
    workspace.activeWorkspaceId,
  ]);

  const generatePreview = async (trigger = null) => {
    if (!projection.previewAvailable || !workspace.activeWorkspaceId) return;
    previewReturnFocusRef.current = trigger || document.activeElement;
    setPreviewOpen(true);
    if (currentPreparedContext || prepareContinuation.isPending) return;
    setPreviewError(null);
    try {
      await compileProjectContext();
    } catch (error) {
      setPreviewError(error?.message || "Could not generate Project Context.");
    }
  };

  const retryPreview = async () => {
    setPreparedContext(null);
    setPreparedContextAnchorKey(null);
    setPreviewError(null);
    try {
      await compileProjectContext({ force: true });
    } catch (error) {
      setPreviewError(error?.message || "Could not generate Project Context.");
    }
  };

  const copyProjectContext = async () => {
    setProjectCopyState("copying");
    setPreviewError(null);
    try {
      const result = await compileProjectContext();
      await writeClipboard(await projectContextContent(result));
      setProjectCopyState("copied");
      return true;
    } catch (error) {
      setProjectCopyState("error");
      setPreviewError(error?.message || "Project Context could not be copied.");
      return false;
    }
  };

  const loadSessionContext = useCallback(async ({
    forceCapture = false,
    retryTransientNetworkFailure = false,
  } = {}) => {
    if (!workspace.activeWorkspaceId || !hasScopedSession) {
      throw new Error("Current Session Context requires a linked active session.");
    }
    const requestSourceKey = activeSessionSourceKey;
    if (
      !forceCapture
      && sessionLoadPromiseRef.current?.key === requestSourceKey
    ) {
      try {
        return await sessionLoadPromiseRef.current.promise;
      } catch (error) {
        if (
          !retryTransientNetworkFailure
          || !isTransientNetworkFailure(error)
        ) {
          throw error;
        }
      }
    }

    const operation = (async () => {
      const captureCurrentTip = () => retryTransientNetworkRequest(
        () => captureCheckpoint.mutateAsync({
          workspaceId: workspace.activeWorkspaceId,
          provider: activityProvider,
          sessionId: activitySessionId,
        }),
        retryTransientNetworkFailure,
      );
      let checkpoint = forceCapture ? await captureCurrentTip() : checkpointQuery.data;
      if (
        !forceCapture
        && !sessionCheckpointIsCurrent(
          checkpoint,
          activityProvider,
          activitySessionId,
        )
      ) {
        checkpoint = await captureCurrentTip();
      }
      if (!checkpoint?.id) {
        throw new Error("The current session checkpoint could not be captured.");
      }

      const requestHandoff = (checkpointId) => retryTransientNetworkRequest(
        () => checkpointHandoff.mutateAsync({
          workspaceId: workspace.activeWorkspaceId,
          checkpointId,
        }),
        retryTransientNetworkFailure,
      );
      let handoffResponse;
      try {
        handoffResponse = await requestHandoff(checkpoint.id);
      } catch (error) {
        if (!forceCapture && sessionGoalIsUnavailable(error)) {
          const refreshedCheckpoint = await captureCurrentTip();
          if (
            refreshedCheckpoint?.id
            && rawText(refreshedCheckpoint.id) !== rawText(checkpoint.id)
          ) {
            checkpoint = refreshedCheckpoint;
            handoffResponse = await requestHandoff(checkpoint.id);
          } else {
            throw unavailableSessionGoalError();
          }
        } else {
          throw error;
        }
      }
      if (activeSessionSourceKeyRef.current !== requestSourceKey) {
        throw new Error("The active session changed while Session Context was preparing.");
      }
      const handoff = validateSessionContext(
        handoffResponse,
        {
          provider: activityProvider,
          sessionId: activitySessionId,
          checkpointId: checkpoint.id,
          boundarySequence: checkpoint.boundary?.sequence_number,
        },
      );
      setSessionContext(handoff);
      setSessionContextSourceKey(requestSourceKey);
      return { handoff, checkpoint };
    })();
    sessionLoadPromiseRef.current = { key: requestSourceKey, promise: operation };
    try {
      return await operation;
    } finally {
      if (sessionLoadPromiseRef.current?.promise === operation) {
        sessionLoadPromiseRef.current = null;
      }
    }
  }, [
    activeSessionSourceKey,
    activityProvider,
    activitySessionId,
    captureCheckpoint,
    checkpointHandoff,
    checkpointQuery.data,
    hasScopedSession,
    workspace.activeWorkspaceId,
  ]);

  const recordSessionContextFailure = useCallback((error, fallback) => {
    const failure = sessionContextFailure(error, fallback);
    setSessionContextError(failure.message);
    setSessionContextRetryable(failure.retryable);
  }, []);

  const previewSessionContext = async (trigger = null) => {
    if (!hasScopedSession) return;
    sessionPreviewReturnFocusRef.current = trigger || document.activeElement;
    setSessionPreviewOpen(true);
    if (
      currentSessionContext
      || captureCheckpoint.isPending
      || checkpointHandoff.isPending
    ) return;
    setSessionContextError(null);
    setSessionContextRetryable(true);
    try {
      await loadSessionContext();
    } catch (error) {
      recordSessionContextFailure(
        error,
        "Current Session Context could not be prepared.",
      );
    }
  };

  const retrySessionContext = async () => {
    setSessionContext(null);
    setSessionContextSourceKey(null);
    setSessionContextError(null);
    setSessionContextRetryable(true);
    try {
      await loadSessionContext({ forceCapture: true });
    } catch (error) {
      recordSessionContextFailure(
        error,
        "Current Session Context could not be prepared.",
      );
    }
  };

  const copySessionContext = async () => {
    setSessionCopyState("copying");
    setSessionContextError(null);
    setSessionContextRetryable(true);
    try {
      const { handoff, checkpoint } = await loadSessionContext({
        retryTransientNetworkFailure: true,
      });
      await writeClipboard(await copyReadySessionContextContent(handoff, {
        provider: activityProvider,
        sessionId: activitySessionId,
        checkpointId: checkpoint.id,
        boundarySequence: checkpoint.boundary?.sequence_number,
      }));
      setSessionContextError(null);
      setSessionContextRetryable(true);
      setSessionCopyState("copied");
    } catch (error) {
      setSessionCopyState("error");
      recordSessionContextFailure(
        error,
        "Current Session Context could not be copied.",
      );
    }
  };

  useEffect(() => {
    if (
      firstLoad
      || dataUnavailable
      || !workspace.activeWorkspaceId
      || !projection.previewAvailable
      || currentPreparedContext
      || prepareContinuation.isPending
      || (
        hasScopedSession
        && !currentSessionContext
        && !sessionContextError
      )
    ) return undefined;

    const previewKey = JSON.stringify([
      workspace.activeWorkspaceId,
      projection.anchorKey,
    ]);
    if (autoProjectPreviewKeyRef.current === previewKey) return undefined;
    autoProjectPreviewKeyRef.current = previewKey;

    let active = true;
    setPreviewError(null);
    compileProjectContext().catch((error) => {
      if (active && activeAnchorRef.current === projection.anchorKey) {
        setPreviewError(error?.message || "Could not generate Project Context.");
      }
    });
    return () => {
      active = false;
    };
  }, [
    compileProjectContext,
    currentPreparedContext,
    dataUnavailable,
    firstLoad,
    hasScopedSession,
    prepareContinuation.isPending,
    projection.anchorKey,
    projection.previewAvailable,
    currentSessionContext,
    sessionContextError,
    workspace.activeWorkspaceId,
  ]);

  useEffect(() => {
    if (
      firstLoad
      || dataUnavailable
      || !workspace.activeWorkspaceId
      || !hasScopedSession
      || currentSessionContext
      || captureCheckpoint.isPending
      || checkpointHandoff.isPending
    ) return undefined;

    const previewKey = activeSessionSourceKey;
    if (autoSessionPreviewKeyRef.current === previewKey) return undefined;
    autoSessionPreviewKeyRef.current = previewKey;

    let active = true;
    setSessionContextError(null);
    setSessionContextRetryable(true);
    loadSessionContext().catch((error) => {
      if (active && activeSessionSourceKeyRef.current === previewKey) {
        recordSessionContextFailure(
          error,
          "Current Session Context could not be prepared.",
        );
      }
    });
    return () => {
      active = false;
    };
  }, [
    activeSessionSourceKey,
    captureCheckpoint.isPending,
    checkpointHandoff.isPending,
    currentSessionContext,
    dataUnavailable,
    firstLoad,
    hasScopedSession,
    loadSessionContext,
    recordSessionContextFailure,
    workspace.activeWorkspaceId,
  ]);

  if (!workspace.workspacesQuery.isLoading && !workspace.activeWorkspaceId) {
    return (
      <WorkspaceTopicGate
        workspaces={workspace.workspaces}
        selectedId={workspace.selectedId}
        onSelect={workspace.setSelectedId}
      />
    );
  }

  if (firstLoad) {
    return (
      <div className="relative mx-auto w-full max-w-none space-y-6 pb-16">
        <MemoryIdentityCard />
        <div className="app-surface">
          <ProductLoadingState
            label="Preparing context products…"
            detail="Reading the active session, current task, repository state, and durable project knowledge."
            stages={["Detecting the active session", "Reconciling project state", "Preparing prompt previews"]}
          />
        </div>
      </div>
    );
  }

  if (dataUnavailable) {
    return (
      <div className="relative mx-auto w-full max-w-7xl space-y-6 pb-16">
        <MemoryIdentityCard />
        <div role="alert" className="app-surface px-6 py-14 text-center">
          <AlertTriangle className="mx-auto h-7 w-7 text-attention" aria-hidden="true" />
          <h2 className="mt-4 text-xl font-semibold tracking-[-0.025em] text-ink">
            The continuation brief is unavailable
          </h2>
          <p className="mx-auto mt-2 max-w-lg text-sm leading-6 text-ink-muted">
            Current activity and project knowledge could not be loaded, so Memory is not inventing a task state.
          </p>
          <Link to="/app/memory/inspector" className="btn-secondary mt-5 min-h-11 text-xs">
            Open Inspector
            <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="relative mx-auto w-full max-w-none space-y-6 pb-16">
      <MemoryIdentityCard />

      {partialData ? (
        <div role="status" className="rounded-control border border-attention/30 bg-attention/10 px-4 py-3 text-xs font-medium leading-5 text-ink">
          Some live context is temporarily unavailable. The previews below show only the source-backed context that loaded successfully.
        </div>
      ) : null}

      <ContextProductsPanel
        projection={projection}
        preparedContext={currentPreparedContext}
        projectPreparing={projectPreviewPreparing}
        projectCopyState={projectCopyState}
        projectError={previewError}
        projectRetryable={projectPreviewRetryable}
        projectDialogOpen={previewOpen}
        onPreviewProject={generatePreview}
        onCopyProject={copyProjectContext}
        sessionAvailable={hasScopedSession}
        sessionProvider={activityProvider}
        sessionId={activitySessionId}
        sessionCheckpoint={checkpointQuery.data}
        sessionContext={currentSessionContext}
        sessionPreparing={sessionPreviewPreparing}
        sessionCopyState={sessionCopyState}
        sessionError={sessionContextError}
        onPreviewSession={previewSessionContext}
        onCopySession={copySessionContext}
      />

      {previewOpen ? createPortal(
        <ContextPreviewDialog
          result={currentPreparedContext}
          loading={projectPreviewPreparing}
          error={previewError}
          canRetry={projectPreviewRetryable}
          onRetry={retryPreview}
          onCopy={copyProjectContext}
          copyState={projectCopyState}
          onClose={closePreview}
          returnFocusRef={previewReturnFocusRef}
        />,
        document.body,
      ) : null}

      {sessionPreviewOpen ? createPortal(
        <SessionContextPreviewDialog
          result={currentSessionContext}
          loading={sessionPreviewPreparing}
          error={sessionContextError}
          canRetry={sessionContextRetryable}
          copyState={sessionCopyState}
          onCopy={copySessionContext}
          onRetry={retrySessionContext}
          onClose={closeSessionPreview}
          returnFocusRef={sessionPreviewReturnFocusRef}
        />,
        document.body,
      ) : null}
    </div>
  );
}


function MemoryIdentityCard() {
  return (
    <header className="daemonstate-resume-header group relative min-h-56 overflow-hidden rounded-[2rem] border border-[#d8d8cf] bg-[#f7f7f1] px-5 py-7 text-[#171713] dark:border-[#292925] dark:bg-[#0c0c0a] dark:text-white sm:px-8 sm:py-9 lg:px-10">
      <div aria-hidden="true" className="absolute -right-20 -top-24 h-72 w-72 rounded-full bg-[#d9ff68]/25 blur-3xl dark:bg-[#d9ff68]/10" />
      <HarnessDeckBackdrop />
      <div className="relative grid gap-8 lg:grid-cols-[minmax(0,1fr)_22rem] lg:items-end">
        <div className="max-w-3xl">
          <h1 id="memory-title" className="text-4xl font-black tracking-[-0.05em] sm:text-5xl">
            Memory
          </h1>
          <h2 id="context-products-heading" className="mt-4 max-w-2xl text-xl font-semibold tracking-[-0.035em] text-[#4f4f48] dark:text-[#d8d8cf] sm:text-2xl">
            Choose the context your next agent needs
          </h2>
        </div>
        <span aria-hidden="true" className="hidden lg:block" />
      </div>
    </header>
  );
}


function ContextProductsPanel({
  projection,
  preparedContext,
  projectPreparing,
  projectCopyState,
  projectError,
  projectRetryable,
  projectDialogOpen,
  onPreviewProject,
  onCopyProject,
  sessionAvailable,
  sessionProvider,
  sessionId,
  sessionCheckpoint,
  sessionContext,
  sessionPreparing,
  sessionCopyState,
  sessionError,
  onPreviewSession,
  onCopySession,
}) {
  const projectContent = preparedContext?.project_context?.content || "";
  const projectCopyReady = (
    !preparedContext
    || preparedContext?.project_context?.copy_ready === true
  );
  const sessionCopyReady = (
    !sessionContext
    || sessionContext?.quality_report?.copy_ready === true
  );
  const sessionFreshness = sessionContext
    ? "Prepared from the current session tip"
    : sessionCheckpointIsCurrent(sessionCheckpoint, sessionProvider, sessionId)
      ? `Current tip · Updated ${formatTimeAgo(
        sessionCheckpoint?.boundary?.occurred_at || sessionCheckpoint?.created_at,
      )}`
      : sessionAvailable
        ? "Preparing from the current session tip"
        : "No linked active session";
  const repositoryFreshness = humanizeStatus(
    preparedContext?.repository?.freshness?.status,
  );

  return (
    <aside
      aria-labelledby="context-products-heading"
      className="flex min-h-[calc(100dvh-18rem)] flex-col gap-4"
    >
      <div className="grid flex-1 items-stretch gap-4 xl:grid-cols-2">
        <article
          aria-labelledby="current-session-context-heading"
          className={CONTEXT_PRODUCT_CARD_CLASSNAME}
        >
          <ContextCardPenBackdrop motif="session" />
          <div className="relative z-10 flex min-h-full flex-1 flex-col">
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-[0.13em] text-ink-subtle">Same harness</p>
                <h3 id="current-session-context-heading" className="mt-1 text-xl font-semibold tracking-[-0.03em] text-ink sm:text-2xl">
                  Current Session Context
                </h3>
              </div>
              <span className="rounded-full border border-line bg-white/50 px-3 py-1.5 text-[9px] font-semibold uppercase tracking-[0.1em] text-ink-muted backdrop-blur-md dark:bg-black/20">
                Session only
              </span>
            </div>
            <p className="mt-3 max-w-xl text-sm leading-6 text-ink-muted">
              Start a new chat in the same harness or refresh a long-running session after compaction.
            </p>
            <dl className="mt-6 grid gap-3 rounded-xl border border-line bg-white/45 p-4 text-[10px] backdrop-blur-md dark:bg-black/15 sm:grid-cols-3 sm:gap-4">
              <ContextDetail
                label="Source"
                value={sessionAvailable
                  ? `${humanizeStatus(sessionProvider)} · ${sessionId}`
                  : "No linked active session"}
              />
              <ContextDetail label="Freshness" value={sessionFreshness} />
              <ContextDetail
                label="Size"
                value={sessionContext?.estimated_tokens
                  ? `${Number(sessionContext.estimated_tokens).toLocaleString()} tokens`
                  : sessionContext?.content
                    ? `≈${approximateTokens(sessionContext.content).toLocaleString()} tokens`
                    : sessionAvailable
                      ? "Preparing…"
                      : "Unavailable"}
              />
            </dl>

            <PromptPreview
              label="Current Session Context prompt preview"
              content={sessionContext?.content}
              loading={sessionPreparing || (sessionAvailable && !sessionContext && !sessionError)}
              available={sessionAvailable}
              error={sessionError}
              unavailableMessage="Link an active session to preview its continuation prompt."
            />

            <div className="mt-auto grid grid-cols-2 gap-3 pt-5">
              <button
                type="button"
                aria-label="Preview Current Session Context"
                onClick={(event) => onPreviewSession(event.currentTarget)}
                disabled={!sessionAvailable}
                className="btn-secondary min-h-11 px-4 text-xs"
              >
                {sessionPreparing
                  ? <RefreshCw className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
                  : <BookOpenCheck className="h-3.5 w-3.5" aria-hidden="true" />}
                {sessionContext
                  ? "Open full preview"
                  : sessionError
                    ? "Retry preview"
                    : "Preparing…"}
              </button>
              <ContextCopyButton
                contextName="Current Session Context"
                copyState={sessionCopyState}
                onClick={onCopySession}
                disabled={!sessionAvailable || !sessionCopyReady}
              />
            </div>
            {sessionError ? (
              <p className="mt-3 text-[10px] leading-4 text-attention">
                {sessionError}
              </p>
            ) : sessionContext && !sessionCopyReady ? (
              <p className="mt-3 text-[10px] leading-4 text-attention">
                {sessionContextQualityMessage(sessionContext)}
              </p>
            ) : null}
          </div>
        </article>

        <article
          aria-labelledby="project-context-heading"
          className={CONTEXT_PRODUCT_CARD_CLASSNAME}
        >
          <ContextCardPenBackdrop motif="project" />
          <div className="relative z-10 flex min-h-full flex-1 flex-col">
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-[0.13em] text-ink-subtle">Switch harnesses</p>
                <h3 id="project-context-heading" className="mt-1 text-xl font-semibold tracking-[-0.03em] text-ink sm:text-2xl">
                  Project Context
                </h3>
              </div>
              <span className="rounded-full border border-line bg-white/50 px-3 py-1.5 text-[9px] font-semibold uppercase tracking-[0.1em] text-ink-muted backdrop-blur-md dark:bg-black/20">
                Task relevant
              </span>
            </div>
            <p className="mt-3 max-w-xl text-sm leading-6 text-ink-muted">
              Switch harnesses with the relevant session, repository state, project decisions, blockers, and learnings.
            </p>
            <dl className="mt-6 grid gap-3 rounded-xl border border-line bg-white/45 p-4 text-[10px] backdrop-blur-md dark:bg-black/15 sm:grid-cols-3 sm:gap-4">
              <ContextDetail
                label="Scope"
                value={preparedContext
                  ? `${preparedContext.execution_contract?.project_context?.length || 0} task-relevant project facts`
                  : `${projection.included.length} expected memory lanes`}
              />
              <ContextDetail
                label="Freshness"
                value={preparedContext
                  ? `Repository ${repositoryFreshness.toLowerCase()}`
                  : projection.previewAvailable
                    ? "Compiling against the live project"
                    : "Unavailable"}
              />
              <ContextDetail
                label="Size"
                value={projectContent
                  ? `≈${approximateTokens(projectContent).toLocaleString()} tokens`
                  : projection.previewAvailable
                    ? "Preparing…"
                    : "Unavailable"}
              />
            </dl>

            <PromptPreview
              label="Project Context prompt preview"
              content={projectContent}
              loading={projectPreparing || (
                projection.previewAvailable
                && !preparedContext
                && !projectError
              )}
              available={projection.previewAvailable}
              error={projectError}
              unavailableMessage="Choose an active task to preview its project prompt."
            />

            <div className="mt-auto grid grid-cols-2 gap-3 pt-5">
              <button
                type="button"
                aria-label="Preview Project Context"
                onClick={(event) => onPreviewProject(event.currentTarget)}
                disabled={
                  !projection.previewAvailable
                  || (!preparedContext && !projectRetryable)
                }
                className="btn-secondary min-h-11 px-4 text-xs"
              >
                {projectPreparing
                  ? <RefreshCw className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
                  : <BookOpenCheck className="h-3.5 w-3.5" aria-hidden="true" />}
                {projectContent
                  ? "Open full preview"
                  : projectError
                    ? projectRetryable
                      ? "Retry preview"
                      : "Unavailable"
                    : "Preparing…"}
              </button>
              <ContextCopyButton
                contextName="Project Context"
                copyState={projectCopyState}
                onClick={onCopyProject}
                disabled={
                  !projection.previewAvailable
                  || !projectCopyReady
                  || (!preparedContext && !projectRetryable)
                }
              />
            </div>
            {projectError ? (
              <p
                role={projectDialogOpen ? undefined : "alert"}
                className="mt-3 text-[10px] leading-4 text-attention"
              >
                {projectError}
              </p>
            ) : null}
          </div>
        </article>
      </div>

      <div className="rounded-2xl border border-[#d8d8cf]/80 bg-[#f7f7f1]/60 px-5 py-4 backdrop-blur-xl dark:border-white/10 dark:bg-[#11110f]/60 sm:px-7">
        <details className="text-xs text-ink-muted">
          <summary className="cursor-pointer font-semibold text-ink">Advanced context details</summary>
          <div className="mt-3 space-y-3">
            <p>
              Audit provenance, selection records, hashes, and exclusions stay available for inspection but are never copied as either context product.
            </p>
            <ul className="space-y-1.5">
              {projection.excluded.map((item) => <li key={item}>• {item}</li>)}
            </ul>
          </div>
        </details>
      </div>
    </aside>
  );
}


function ContextDetail({ label, value }) {
  return (
    <div className="min-w-0 border-t border-line pt-3 first:border-t-0 first:pt-0 sm:border-l sm:border-t-0 sm:pl-4 sm:pt-0 sm:first:border-l-0 sm:first:pl-0">
      <dt className="font-semibold uppercase tracking-[0.09em] text-ink-subtle">{label}</dt>
      <dd className="mt-1 break-words font-medium leading-4 text-ink-muted">{value}</dd>
    </div>
  );
}


function PromptPreview({
  label,
  content,
  loading,
  available,
  error,
  unavailableMessage,
}) {
  return (
    <section
      aria-label={label}
      className="relative isolate mt-6 flex min-h-[320px] flex-1 flex-col overflow-hidden rounded-2xl border border-[#2b2b26] bg-[#171713] text-[#f4f4ec] shadow-[inset_0_1px_0_rgba(255,255,255,0.04)]"
    >
      <header className="relative z-10 flex items-center justify-between gap-3 border-b border-white/10 px-4 py-3">
        <div className="flex items-center gap-2">
          <FileCode2 className="h-3.5 w-3.5 text-[#d9ff68]" aria-hidden="true" />
          <span className="font-mono text-[9px] font-semibold uppercase tracking-[0.14em] text-white/60">
            Prompt preview
          </span>
        </div>
        <span className="inline-flex items-center gap-1.5 text-[9px] font-semibold uppercase tracking-[0.1em] text-white/40">
          <span className={`h-1.5 w-1.5 rounded-full ${
            content ? "bg-[#d9ff68]" : loading ? "animate-pulse bg-white/60" : "bg-white/25"
          }`} />
          {content ? "Prepared" : loading ? "Preparing" : "Unavailable"}
        </span>
      </header>
      {content ? (
        <pre
          tabIndex={0}
          aria-label={`${label} content`}
          className="relative z-10 max-h-[460px] flex-1 overflow-auto whitespace-pre-wrap break-words p-4 font-mono text-[11px] leading-5 text-white/78 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-[-3px] focus-visible:outline-[#d9ff68] sm:p-5"
        >
          {content}
        </pre>
      ) : (
        <div className="relative z-10 flex flex-1 items-center justify-center p-6 text-center">
          <div className="max-w-sm">
            {loading ? (
              <RefreshCw className="mx-auto h-5 w-5 animate-spin text-[#d9ff68]" aria-hidden="true" />
            ) : (
              <BookOpenCheck className="mx-auto h-5 w-5 text-white/30" aria-hidden="true" />
            )}
            <p className="mt-3 text-xs font-medium leading-5 text-white/55">
              {loading
                ? "Preparing the exact prompt…"
                : error
                  ? "The prompt could not be prepared automatically. Retry the preview."
                  : available
                    ? "The exact prompt is temporarily unavailable."
                    : unavailableMessage}
            </p>
          </div>
        </div>
      )}
    </section>
  );
}


function ContextCardPenBackdrop({ motif }) {
  return (
    <div aria-hidden="true" className="pointer-events-none absolute inset-0 z-0 overflow-hidden">
      <img
        src={fountainPen}
        alt=""
        data-pen-motif={motif}
        className="absolute -right-20 -top-16 w-[22rem] max-w-none rotate-[12deg] select-none opacity-[0.055] dark:invert dark:opacity-[0.09] sm:-right-16 sm:w-[24rem] lg:w-[26rem]"
      />
    </div>
  );
}


function copyActionLabel(state, contextName) {
  if (state === "copying") return "Copying…";
  if (state === "copied") return "Copied";
  if (state === "error") return "Try copy again";
  return `Copy ${contextName}`;
}


function ContextCopyButton({
  contextName,
  copyState,
  onClick,
  disabled,
}) {
  return (
    <button
      type="button"
      aria-label={copyActionLabel(copyState, contextName)}
      onClick={onClick}
      disabled={disabled || copyState === "copying"}
      className="btn-primary min-h-11 px-4 text-xs"
    >
      <Clipboard className="h-3.5 w-3.5" aria-hidden="true" />
      {copyActionLabel(copyState, "").trim()}
    </button>
  );
}


function ContextPreviewDialog({
  result,
  loading,
  error,
  canRetry,
  onRetry,
  onCopy,
  copyState,
  onClose,
  returnFocusRef,
}) {
  const closeRef = useRef(null);
  const dialogRef = useRef(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    closeRef.current?.focus();
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKeyDown = (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key !== "Tab" || !dialogRef.current) return;
      const focusable = Array.from(dialogRef.current.querySelectorAll(
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
    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = previousOverflow;
      window.setTimeout(() => returnFocusRef.current?.focus(), 0);
    };
  }, [onClose, returnFocusRef]);

  const manifest = result?.manifest || {};
  const selected = manifest.selected_context || [];
  const excluded = manifest.excluded_context || [];
  const projectContent = result?.project_context?.content || "";
  const projectCopyReady = result?.project_context?.copy_ready === true;
  const projectTokens = projectContent ? approximateTokens(projectContent) : null;
  const selectedObjective = visibleText(
    result?.task?.selected_intent?.objective
    || result?.task?.workflow?.selected_intent?.objective,
  );
  const executionObjective = visibleText(result?.objective);
  const executingPrerequisite = (
    result?.task?.workflow?.execution_reason === "unfinished_prerequisite"
    || (
      selectedObjective
      && executionObjective
      && !taskTextCompatible(selectedObjective, executionObjective)
    )
  );
  const prerequisiteAnchorSwitched = Boolean(
    result?._memory_preview?.prerequisite_anchor_switched,
  );

  const copyContext = async () => {
    if (!projectContent || typeof onCopy !== "function") return;
    const succeeded = await onCopy();
    if (succeeded) {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    } else {
      setCopied(false);
    }
  };

  return (
    <div className="fixed inset-0 z-[100] flex items-end justify-center bg-black/55 p-0 backdrop-blur-sm sm:items-center sm:p-6">
      <section
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="context-preview-title"
        className="memory-drawer-enter flex max-h-[94vh] w-full max-w-5xl flex-col overflow-hidden rounded-t-[24px] border border-line bg-canvas shadow-[0_30px_100px_rgba(0,0,0,0.35)] sm:rounded-[24px]"
      >
        <header className="flex items-start justify-between gap-4 border-b border-line bg-surface-raised px-5 py-5 sm:px-6">
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-[0.13em] text-ink-subtle">Cross-harness handoff</p>
            <h2 id="context-preview-title" className="mt-1 text-xl font-semibold tracking-[-0.03em] text-ink">
              Project Context Preview
            </h2>
            <p className="mt-1 text-xs leading-5 text-ink-muted">
              Task-relevant project knowledge compiled for the current lead. If the task changes materially, compile a fresh Project Context.
            </p>
          </div>
          <button
            ref={closeRef}
            type="button"
            onClick={onClose}
            aria-label="Close Project Context Preview"
            className="icon-button shrink-0"
          >
            <X className="h-4 w-4" aria-hidden="true" />
          </button>
        </header>

        {loading ? (
          <ProductLoadingState
            compact
            label="Compiling Project Context…"
            detail="Reconciling the active task, current repository, and relevant project knowledge."
            stages={["Resolving the task", "Checking repository state", "Rendering Project Context"]}
            className="m-5 sm:m-6"
          />
        ) : error ? (
          <div role="alert" className="px-6 py-14 text-center">
            <AlertTriangle className="mx-auto h-7 w-7 text-attention" aria-hidden="true" />
            <h3 className="mt-4 text-base font-semibold text-ink">Project Context could not be generated</h3>
            <p className="mx-auto mt-2 max-w-lg text-sm leading-6 text-ink-muted">{error}</p>
            {canRetry ? (
              <button type="button" onClick={onRetry} className="btn-secondary mt-5 min-h-11 text-xs">
                <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
                Try again
              </button>
            ) : null}
          </div>
        ) : result ? (
          <>
            <div className="grid grid-cols-2 gap-px border-b border-line bg-line sm:grid-cols-4">
              <PreviewMetric label="Scope" value="Task-relevant project" />
              <PreviewMetric
                label="Estimated size"
                value={Number.isFinite(projectTokens) ? `≈${projectTokens.toLocaleString()} tokens` : "Not reported"}
              />
              <PreviewMetric
                label="Repository"
                value={humanizeStatus(result.repository?.freshness?.status)}
              />
              <PreviewMetric label="Format" value={result.project_context?.schema_version || "Unknown"} />
            </div>
            {result.readiness?.status !== "ready" ? (
              <div role="status" className="border-b border-attention/30 bg-attention/10 px-5 py-3 text-xs font-medium leading-5 text-ink sm:px-6">
                Compiler readiness: {humanizeStatus(result.readiness?.status)}. Review the reported attention before continuing.
              </div>
            ) : null}
            {!projectCopyReady ? (
              <div role="status" className="border-b border-attention/30 bg-attention/10 px-5 py-3 text-xs font-medium leading-5 text-ink sm:px-6">
                {projectContextQualityMessage(result)}
              </div>
            ) : null}
            {executingPrerequisite ? (
              <div role="status" className="border-b border-sky-300/40 bg-sky-50 px-5 py-3 text-xs font-medium leading-5 text-sky-950 dark:border-sky-900 dark:bg-sky-950/30 dark:text-sky-100 sm:px-6">
                This pack starts with the unfinished prerequisite “{executionObjective}” before returning to “{selectedObjective}”.
                {prerequisiteAnchorSwitched
                  ? " The compiler selected a different checkpoint or source session for that prerequisite; inspect the execution anchor before continuing."
                  : ""}
              </div>
            ) : null}
            <div className="min-h-0 flex-1 overflow-y-auto p-5 sm:p-6">
              <div>
                <div className="flex items-center justify-between gap-3">
                  <p className="text-xs font-semibold text-ink">Project Context</p>
                  <button
                    type="button"
                    onClick={copyContext}
                    disabled={!projectCopyReady || copyState === "copying"}
                    className="inline-flex min-h-9 items-center gap-2 rounded-lg px-3 text-[10px] font-semibold text-ink-muted hover:bg-surface-muted hover:text-ink"
                  >
                    <Clipboard className="h-3.5 w-3.5" aria-hidden="true" />
                    {copied
                      ? "Copied"
                      : copyState === "copying"
                        ? "Refreshing…"
                        : "Copy Project Context"}
                  </button>
                </div>
                <pre
                  tabIndex={0}
                  aria-label="Project Context prompt content"
                  className="mt-3 max-h-[48vh] overflow-auto whitespace-pre-wrap rounded-xl border border-line bg-[#171713] p-4 font-mono text-[11px] leading-5 text-[#f4f4ec]"
                >
                  {projectContent}
                </pre>
              </div>
              <details className="mt-5 rounded-xl border border-line bg-surface-raised p-4">
                <summary className="cursor-pointer text-xs font-semibold text-ink">
                  Advanced audit details
                </summary>
                <div className="mt-4 grid gap-5 lg:grid-cols-[minmax(0,1fr)_280px]">
                  <div>
                    <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-ink-subtle">
                      Audit ContextPack
                    </p>
                    <pre
                      tabIndex={0}
                      aria-label="Advanced audit markdown"
                      className="mt-3 max-h-72 overflow-auto whitespace-pre-wrap rounded-xl border border-line bg-surface p-4 font-mono text-[10px] leading-5 text-ink-muted"
                    >
                      {result.markdown}
                    </pre>
                  </div>
                  <aside>
                    <AuditList title="Included" items={selected} empty="No selected items were reported." />
                    <div className="mt-5 border-t border-line pt-4">
                      <AuditList
                        title="Excluded"
                        items={excluded}
                        empty="No excluded items were reported."
                        showReason
                      />
                    </div>
                  </aside>
                </div>
              </details>
            </div>
          </>
        ) : null}
      </section>
    </div>
  );
}


function SessionContextPreviewDialog({
  result,
  loading,
  error,
  canRetry,
  copyState,
  onCopy,
  onRetry,
  onClose,
  returnFocusRef,
}) {
  const closeRef = useRef(null);
  const dialogRef = useRef(null);
  const copyReady = result?.quality_report?.copy_ready === true;

  useEffect(() => {
    closeRef.current?.focus();
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKeyDown = (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key !== "Tab" || !dialogRef.current) return;
      const focusable = Array.from(dialogRef.current.querySelectorAll(
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
    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = previousOverflow;
      window.setTimeout(() => returnFocusRef.current?.focus(), 0);
    };
  }, [onClose, returnFocusRef]);

  return (
    <div className="fixed inset-0 z-[100] flex items-end justify-center bg-black/55 p-0 backdrop-blur-sm sm:items-center sm:p-6">
      <section
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="session-context-preview-title"
        className="memory-drawer-enter flex max-h-[94vh] w-full max-w-4xl flex-col overflow-hidden rounded-t-[24px] border border-line bg-canvas shadow-[0_30px_100px_rgba(0,0,0,0.35)] sm:rounded-[24px]"
      >
        <header className="flex items-start justify-between gap-4 border-b border-line bg-surface-raised px-5 py-5 sm:px-6">
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-[0.13em] text-ink-subtle">Same-session handoff</p>
            <h2 id="session-context-preview-title" className="mt-1 text-xl font-semibold tracking-[-0.03em] text-ink">
              Current Session Context Preview
            </h2>
            <p className="mt-1 text-xs leading-5 text-ink-muted">
              A compact handoff from one session boundary for a new chat in the same harness.
            </p>
          </div>
          <button
            ref={closeRef}
            type="button"
            onClick={onClose}
            aria-label="Close Current Session Context Preview"
            className="icon-button shrink-0"
          >
            <X className="h-4 w-4" aria-hidden="true" />
          </button>
        </header>

        {loading ? (
          <ProductLoadingState
            compact
            label="Preparing Current Session Context…"
            detail="Capturing the current session tip and rendering its compact handoff."
            stages={["Capturing the session tip", "Restoring structured progress", "Rendering Session Context"]}
            className="m-5 sm:m-6"
          />
        ) : error ? (
          <div role="alert" className="px-6 py-14 text-center">
            <AlertTriangle className="mx-auto h-7 w-7 text-attention" aria-hidden="true" />
            <h3 className="mt-4 text-base font-semibold text-ink">Current Session Context could not be prepared</h3>
            <p className="mx-auto mt-2 max-w-lg text-sm leading-6 text-ink-muted">{error}</p>
            {canRetry ? (
              <button type="button" onClick={onRetry} className="btn-secondary mt-5 min-h-11 text-xs">
                <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
                Refresh current session tip
              </button>
            ) : null}
          </div>
        ) : result ? (
          <>
            <div className="grid grid-cols-2 gap-px border-b border-line bg-line sm:grid-cols-4">
              <PreviewMetric label="Harness" value={humanizeStatus(result.provider)} />
              <PreviewMetric label="Session" value={result.session_id || "Unknown"} />
              <PreviewMetric
                label="Captured"
                value={result.captured_at ? formatTimeAgo(result.captured_at) : "Current tip"}
              />
              <PreviewMetric
                label="Estimated size"
                value={`${Number(
                  result.estimated_tokens || approximateTokens(result.content),
                ).toLocaleString()} tokens`}
              />
            </div>
            {!copyReady ? (
              <div role="status" className="border-b border-attention/30 bg-attention/10 px-5 py-3 text-xs font-medium leading-5 text-ink sm:px-6">
                {sessionContextQualityMessage(result)}
              </div>
            ) : null}
            <div className="min-h-0 flex-1 overflow-y-auto p-5 sm:p-6">
              <div className="flex items-center justify-between gap-3">
                <p className="text-xs font-semibold text-ink">Current Session Context</p>
                <button
                  type="button"
                  onClick={onCopy}
                  disabled={!copyReady || copyState === "copying"}
                  className="inline-flex min-h-9 items-center gap-2 rounded-lg px-3 text-[10px] font-semibold text-ink-muted hover:bg-surface-muted hover:text-ink"
                >
                  <Clipboard className="h-3.5 w-3.5" aria-hidden="true" />
                  {copyActionLabel(copyState, "Current Session Context")}
                </button>
              </div>
              <pre
                tabIndex={0}
                aria-label="Current Session Context prompt content"
                className="mt-3 max-h-[56vh] overflow-auto whitespace-pre-wrap rounded-xl border border-line bg-[#171713] p-4 font-mono text-[11px] leading-5 text-[#f4f4ec]"
              >
                {result.content}
              </pre>
            </div>
          </>
        ) : null}
      </section>
    </div>
  );
}


function PreviewMetric({ label, value }) {
  return (
    <div className="bg-surface px-4 py-3">
      <p className="text-[9px] font-semibold uppercase tracking-[0.11em] text-ink-subtle">{label}</p>
      <p className="mt-1 truncate text-xs font-semibold text-ink">{value}</p>
    </div>
  );
}


function AuditList({ title, items, empty, showReason = false }) {
  return (
    <div>
      <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-ink-subtle">{title}</p>
      {items.length ? (
        <ul className="mt-3 space-y-2">
          {items.slice(0, 12).map((item, index) => (
            <li key={`${auditItemLabel(item)}-${index}`} className="text-[11px] leading-5 text-ink-muted">
              {auditItemLabel(item)}
              {showReason && auditItemReason(item) ? (
                <span className="mt-0.5 block text-[10px] text-ink-subtle">
                  {auditItemReason(item)}
                </span>
              ) : null}
            </li>
          ))}
        </ul>
      ) : <p className="mt-3 text-[11px] leading-5 text-ink-muted">{empty}</p>}
      {items.length > 12 ? <p className="mt-2 text-[10px] text-ink-subtle">+{items.length - 12} more</p> : null}
    </div>
  );
}


function projectMemoryNow({
  digest,
  memory,
  checkpoint,
  workspace,
}) {
  const candidateActivity = digest?.activity?.primary || null;
  const currentGoalRaw = rawText(digest?.current_goal?.title || memory?.current_goal?.title);
  const currentGoal = visibleText(currentGoalRaw);
  const activityGoalRaw = rawText(
    candidateActivity?.request
    || candidateActivity?.title
    || candidateActivity?.session_title,
  );
  const activityRequestRaw = rawText(candidateActivity?.request);
  const activityGoal = visibleText(activityGoalRaw);
  const activityAssigned = activityIsProjectAssigned(candidateActivity);
  const activityTaskCompatible = (
    activityAssigned
    && (!currentGoal || taskTextCompatible(currentGoalRaw, activityGoalRaw))
  );
  const activity = activityTaskCompatible ? candidateActivity : null;
  const activityAssignmentIssue = Boolean(candidateActivity && !activityAssigned);
  const activityTaskMismatch = Boolean(
    candidateActivity
    && activityAssigned
    && currentGoal
    && !activityTaskCompatible
  );
  const activeRepoPath = rawText(
    activity?.cwd
    || workspace?.repo_path
    || digest?.scope?.project_paths?.[0],
  );

  const checkpointGoalItems = activeCheckpointItems(checkpoint?.sections?.goal);
  const checkpointGoalCandidateRaw = rawCheckpointStatement(checkpointGoalItems[0]);
  const checkpointGoalCandidate = visibleText(checkpointGoalCandidateRaw);
  const taskAnchorGoalRaw = currentGoalRaw || (activity ? activityRequestRaw : "");
  const checkpointCanSeedTask = Boolean(
    !taskAnchorGoalRaw
  );
  const checkpointGoalCompatible = Boolean(
    checkpointGoalCandidate
    && (
      checkpointCanSeedTask
      || (
        taskAnchorGoalRaw
        && taskTextCompatible(taskAnchorGoalRaw, checkpointGoalCandidateRaw)
      )
    )
  );
  const checkpointSourceCompatible = checkpointMatchesActivity(checkpoint, activity);
  const checkpointTaskRepoCompatible = Boolean(
    !candidateActivity
    && checkpointGoalCompatible
    && repositoryPathsMatch(checkpoint?.repo?.root, activeRepoPath)
  );
  const checkpointTaskCompatible = Boolean(
    checkpointGoalCompatible
    && (
      checkpointSourceCompatible
      || checkpointTaskRepoCompatible
    )
  );
  const checkpointStructurallyCurrent = Boolean(
    checkpointTaskCompatible
    && SUPPORTED_CHECKPOINT_SCHEMAS.has(checkpoint?.schema_version)
    && checkpoint?.currentness?.state === "captured"
    && checkpoint?.capture_status === "complete"
    && checkpoint?.projection?.valid === true
    && checkpoint?.boundary?.has_newer_events === false
    && Number.isInteger(checkpoint?.boundary?.sequence_number)
    && checkpoint.boundary.sequence_number === checkpoint.boundary.session_tip_sequence
    && checkpointGoalItems.length === 1
    && activeCheckpointItems(checkpoint?.sections?.exact_next_action).length === 1
  );
  const currentCheckpoint = checkpointStructurallyCurrent ? checkpoint : null;
  const checkpointGoalRaw = currentCheckpoint ? checkpointGoalCandidateRaw : "";
  const checkpointGoal = visibleText(checkpointGoalRaw);
  const checkpointStatus = String(currentCheckpoint?.continuation_status || "").toLowerCase();
  const checkpointStatusNeedsReview = Boolean(
    currentCheckpoint
    && checkpointStatus !== "ready"
  );
  const checkpointUnavailableForBrief = Boolean(
    checkpoint
    && checkpointGoalCompatible
    && !checkpointStructurallyCurrent
  );

  const scopedActivityGoalRaw = activity ? activityRequestRaw : "";
  const scopedActivityGoal = visibleText(scopedActivityGoalRaw);
  const activityDisplayGoal = activity ? activityGoal : "";
  const goal = (
    currentGoal
    || checkpointGoal
    || scopedActivityGoal
    || activityDisplayGoal
    || "No active task detected"
  );
  const objective = currentGoal
    ? currentGoalRaw
    : checkpointGoal
      ? checkpointGoalRaw
      : scopedActivityGoal
        ? scopedActivityGoalRaw
        : "";
  const goalOrigin = currentGoal
    ? "current_goal"
    : checkpointGoal
      ? "checkpoint"
      : scopedActivityGoal
        ? "session"
        : "missing";

  const sections = memorySectionMap(memory);
  const memoryGoal = rawText(memory?.current_goal?.title || memory?.agenda?.title);
  const taskMemoryScoped = Boolean(
    currentGoal
    && memoryGoal
    && taskTextCompatible(currentGoalRaw, memoryGoal)
  );
  const checkpointSections = Object.fromEntries(
    Object.entries(currentCheckpoint?.sections || {}).map(([key, items]) => [
      key,
      activeCheckpointItems(items),
    ]),
  );
  const checkpointProgress = [...(checkpointSections.progress || [])]
    .filter(checkpointItemIsGrounded)
    .map(checkpointStatement)
    .filter(Boolean);
  const latestUpdate = visibleText(
    activity?.latest_update
    || checkpointProgress.at(-1),
  );
  const workRecords = taskMemoryScoped ? sections.work || [] : [];
  const deliveryRecords = taskMemoryScoped ? sections.deliveries || [] : [];
  const completedRecords = taskMemoryScoped ? sections.completed || [] : [];
  const currentState = uniqueText([
    latestUpdate,
    ...deliveryRecords.slice(0, 1).map(memoryRecordStatement),
    ...workRecords.slice(0, 1).map(memoryRecordStatement),
  ]).slice(0, 2);
  const outcomeSummary = successfulCompletionSummary(activity);
  const lastCompleted = uniqueText([
    outcomeSummary,
    ...completedRecords.slice(0, 2).map(memoryRecordStatement),
  ]).slice(0, 2);

  const checkpointNextAction = checkpointStatement(
    checkpointSections.exact_next_action?.[0],
  );
  const activeLoopIdentity = {
    focusComponentId: rawText(
      digest?.current_goal?.component_id
      || memory?.current_goal?.component_id
      || memory?.agenda?.component_id,
    ),
    contextPackId: rawText(
      activity?.context_pack_id
      || currentCheckpoint?.context_pack_id
      || currentCheckpoint?.payload?.context_pack_id,
    ),
    runId: rawText(activity?.run_id || String(activity?.id || "").replace(/^run:/, "")),
  };
  const openLoops = Array.isArray(digest?.open_loops?.items)
    ? digest.open_loops.items
      .filter((item) => item?.status === "open")
      .filter((item) => openLoopMatchesTask(item, activeLoopIdentity))
    : [];
  const loopNextAction = visibleText(
    openLoops.find((item) => item?.next_action)?.next_action,
  );
  const memoryNextAction = memoryRecordStatement(
    workRecords.find((record) => (
      /next action|next step|follow[- ]?up/i.test(`${record.kind || ""} ${record.title || ""}`)
    )) || workRecords[0],
  );
  const nextAction = uniqueText([
    checkpointNextAction,
    loopNextAction,
    memoryNextAction,
  ]).slice(0, 2);

  const blockers = uniqueText([
    ...(checkpointSections.blockers || []).map(checkpointStatement),
    ...(taskMemoryScoped ? sections.blockers || [] : []).map(memoryRecordStatement),
    ...openLoops
      .filter((item) => ["high", "critical"].includes(String(item.severity || "").toLowerCase()))
      .map((item) => visibleText(item.summary || item.title)),
  ]).slice(0, 4);

  const activityVerification = observedVerification(activity);
  const activityVerificationFailed = Number(activity?.verification?.failed || 0) > 0;
  const checkpointVerificationStatus = String(currentCheckpoint?.verification?.status || "").toLowerCase();
  const checkpointVerificationItems = checkpointSections.verification || [];
  const checkpointVerificationBoundToSnapshot = Boolean(
    checkpointVerificationStatus === "verified"
    && currentCheckpoint?.verification?.worktree_fingerprint
    && currentCheckpoint?.repo?.worktree_fingerprint
    && currentCheckpoint.verification.worktree_fingerprint
      === currentCheckpoint.repo.worktree_fingerprint
  );
  const checkpointVerification = checkpointVerificationBoundToSnapshot
    ? checkpointVerificationItems
      .filter((item) => ["observed", "verified"].includes(String(item?.truth_state || "").toLowerCase()))
      .map((item) => `At the saved checkpoint: ${checkpointStatement(item)}`)
    : [];
  const memoryVerification = [...deliveryRecords, ...completedRecords]
    .filter((record) => (
      ["verified", "observed"].includes(record.verification)
      && /verification|test|check/i.test(`${record.kind || ""} ${record.title || ""}`)
    ))
    .map(memoryRecordStatement);
  const verification = uniqueText([
    activityVerification,
    ...checkpointVerification,
    ...memoryVerification,
  ]).slice(0, 4);

  const fileRecords = [...deliveryRecords, ...workRecords]
    .filter((record) => /file|change|patch|commit/i.test(String(record.kind || "")))
    .flatMap((record) => extractFilePaths(`${record.title || ""} ${record.summary || ""}`));
  const files = uniquePaths([
    ...(activity?.changed_files || []),
    ...(checkpointSections.relevant_files || [])
      .filter(checkpointItemIsGrounded)
      .map((item) => (
        rawText(item?.payload?.path) || checkpointStatement(item)
      )),
    ...fileRecords,
  ]).slice(0, 6);

  const decisions = uniqueText([
    ...(checkpointSections.decisions || [])
      .filter(checkpointDecisionIsDurable)
      .map(checkpointStatement),
    ...(taskMemoryScoped ? sections.decisions || [] : []).map(memoryRecordStatement),
    ...(taskMemoryScoped ? sections.requirements || [] : []).slice(0, 1).map(memoryRecordStatement),
  ]).slice(0, 4);
  const failedAttempts = uniqueText([
    ...(checkpointSections.failed_attempts || [])
      .filter(checkpointItemIsGrounded)
      .map(checkpointStatement),
    ...(taskMemoryScoped ? sections.learnings || [] : []).map(memoryRecordStatement),
  ]).slice(0, 4);

  const projectionAttention = [];
  if (activityAssignmentIssue) {
    projectionAttention.push({
      id: "activity-needs-assignment",
      label: "Task scope",
      title: "Recent session needs project assignment",
      summary: "The newest session is excluded from this brief until its workspace relevance is confirmed.",
      href: "/app",
    });
  } else if (activityTaskMismatch) {
    projectionAttention.push({
      id: "activity-task-mismatch",
      label: "Task mismatch",
      title: "Recent activity belongs to a different task",
      summary: `Project focus is “${currentGoal}”; the newest session reports “${activityGoal}”. Its state and files were excluded.`,
      href: "/app/runs",
    });
  }
  if (activityOutcomeNeedsAttention(activity)) {
    projectionAttention.push({
      id: `activity-outcome:${activity?.id || "latest"}`,
      label: humanizeStatus(activity?.state || activity?.outcome?.status || "Run"),
      title: "Latest run did not complete successfully",
      summary: visibleText(activity?.outcome?.summary || activity?.latest_update),
      href: "/app/runs",
    });
  }
  if (activityVerificationFailed) {
    projectionAttention.push({
      id: `activity-verification:${activity?.id || "latest"}`,
      label: "Verification",
      title: "Latest observed verification failed",
      summary: activityVerification,
      href: "/app/runs",
    });
  }
  if (checkpointUnavailableForBrief) {
    projectionAttention.push({
      id: `checkpoint-not-current:${checkpoint?.id || "unknown"}`,
      label: "Checkpoint",
      title: "Saved checkpoint is not current and complete",
      summary: checkpointSafetySummary(checkpoint),
      href: "/app/runs",
    });
  }
  if (checkpointStatusNeedsReview) {
    projectionAttention.push({
      id: `checkpoint-status:${currentCheckpoint.id}`,
      label: checkpointStatus === "blocked" ? "Blocked" : "Review required",
      title: checkpointStatus === "blocked"
        ? "Checkpoint reports a blocked continuation"
        : "Checkpoint requires review before continuation",
      summary: "The checkpoint can inform the brief, but it is not treated as launch-ready.",
      href: "/app/runs",
    });
  }
  if (checkpointVerificationItems.length && !checkpointVerificationBoundToSnapshot) {
    projectionAttention.push({
      id: `checkpoint-verification:${currentCheckpoint?.id || checkpoint?.id || "unknown"}`,
      label: "Verification",
      title: "Checkpoint verification is not current",
      summary: checkpointVerificationStatus === "verified"
        ? "The verification fingerprint does not match the repository snapshot saved with this checkpoint."
        : checkpointVerificationStatus
        ? `Verification status is ${humanizeStatus(checkpointVerificationStatus)}.`
        : "No verified checkpoint result is attached to this repository state.",
      href: "/app/runs",
    });
  }

  const timeline = sessionTimeline(digest, currentGoal || checkpointGoal || scopedActivityGoal);
  const attention = attentionItems(
    digest,
    taskMemoryScoped ? sections : {},
    projectionAttention,
  );
  const attentionTotal = Math.max(
    attention.length,
    taskMemoryScoped
      ? (
          Number(memory?.totals?.conflicts || 0)
          + Number(memory?.totals?.needs_refresh || 0)
        )
      : 0,
  );

  const provider = normalizeProvider(activity?.provider || activity?.tool);
  const sessionId = visibleText(activity?.session_id);
  const repoPath = activeRepoPath;
  const preparePayload = { workspace_id: workspace?.id };
  if (repoPath) preparePayload.repo_path = repoPath;
  if (currentCheckpoint?.id) preparePayload.checkpoint_id = currentCheckpoint.id;
  if (!currentCheckpoint?.id && provider && sessionId) {
    preparePayload.source_provider = provider;
    preparePayload.source_session_id = sessionId;
  }
  const prepareIsSourceBound = Boolean(
    preparePayload.checkpoint_id
    || (
      preparePayload.source_provider
      && preparePayload.source_session_id
    )
  );
  if (goalOrigin !== "missing" && !prepareIsSourceBound) {
    preparePayload.objective = objective;
  }

  const continuable = goalOrigin !== "missing";

  const included = [
    goalOrigin !== "missing" ? "Current goal" : null,
    nextAction.length ? "Exact next action" : null,
    decisions.length ? `${decisions.length} active ${decisions.length === 1 ? "decision" : "decisions"}` : null,
    blockers.length ? `${blockers.length} known ${blockers.length === 1 ? "blocker" : "blockers"}` : null,
    files.length ? `${files.length} relevant ${files.length === 1 ? "file" : "files"}` : null,
    verification.length ? "Latest observed verification" : null,
    failedAttempts.length ? "Known failed approaches" : null,
  ].filter(Boolean);

  return {
    goal,
    objective,
    continuable,
    currentState,
    currentStateSource: latestUpdate ? "/app/runs" : SECTION_LINKS.work,
    lastCompleted,
    lastCompletedSource: outcomeSummary ? "/app/runs" : SECTION_LINKS.completed,
    nextAction,
    nextActionSource: checkpointNextAction ? "/app/runs" : SECTION_LINKS.work,
    blockers,
    verification,
    verificationSource: activityVerification || checkpointVerification.length ? "/app/runs" : SECTION_LINKS.deliveries,
    files,
    filesSource: activity?.changed_files?.length || checkpointSections.relevant_files?.length
      ? "/app/runs"
      : SECTION_LINKS.deliveries,
    decisions,
    failedAttempts,
    failedAttemptsSource: checkpointSections.failed_attempts?.length ? "/app/runs" : SECTION_LINKS.learnings,
    timeline,
    attentionItems: attention.slice(0, 3),
    attentionTotal,
    included,
    excluded: [
      "Raw test stdout and tool logs",
      "Superseded decisions and completed task noise",
      "Unrelated workspace and session activity",
    ],
    preparePayload,
    previewIdentity: {
      workspaceId: workspace?.id || null,
      objective: preparePayload.objective || null,
      repoPath: preparePayload.repo_path || null,
      checkpointId: preparePayload.checkpoint_id || null,
      sourceProvider: preparePayload.source_provider || null,
      sourceSessionId: preparePayload.source_session_id || null,
    },
    previewAvailable: Boolean(
      workspace?.id
      && (
        continuable
        || (
          preparePayload.source_provider
          && preparePayload.source_session_id
        )
      )
    ),
    anchorKey: JSON.stringify([
      workspace?.id || "",
      objective,
      provider || "",
      sessionId || "",
      repoPath || "",
      currentCheckpoint?.id || "",
      currentCheckpoint?.payload_sha256 || "",
      currentCheckpoint?.currentness?.state || "",
      currentCheckpoint?.boundary?.sequence_number || "",
      currentCheckpoint?.continuation_status || "",
      currentCheckpoint?.verification?.status || "",
      currentCheckpoint?.verification?.worktree_fingerprint || "",
      activity?.updated_at || activity?.source_activity_at || activity?.ended_at || "",
      activity?.event_count || "",
      activity?.run_id || activity?.id || "",
      activity?.context_pack_id || "",
      currentState,
      lastCompleted,
      nextAction,
      blockers,
      verification,
      files,
      decisions,
      failedAttempts,
      attention.slice(0, 3).map((item) => [item.id, item.label, item.title, item.summary]),
    ]),
  };
}


function memorySectionMap(memory) {
  return Object.fromEntries(
    (memory?.sections || []).map((section) => [section.id, section.records || []]),
  );
}


function memoryRecordStatement(record) {
  if (!record) return "";
  const title = visibleText(record.title);
  const summary = visibleText(record.summary);
  if (!title) return summary;
  if (!summary || summary === title || summary.toLowerCase().includes(title.toLowerCase())) return title;
  return `${title}: ${summary}`;
}


function checkpointStatement(item) {
  return visibleText(item?.statement || item?.text || item?.summary);
}


function rawCheckpointStatement(item) {
  return rawText(item?.statement || item?.text || item?.summary);
}


function observedVerification(activity) {
  if (activity?.evidence_level !== "observed_run") return "";
  const observed = Number(activity?.verification?.observed || 0);
  const passed = Number(activity?.verification?.passed || 0);
  const failed = Number(activity?.verification?.failed || 0);
  const known = Math.max(0, passed) + Math.max(0, failed);
  const total = Math.max(0, observed, known);
  const unknown = Math.max(0, total - known);
  if (!total) return "";
  if (passed > 0 && !failed && !unknown) {
    return `${passed} observed verification ${passed === 1 ? "check" : "checks"} passed`;
  }
  if (!passed && !failed && unknown) {
    return `${total} observed verification ${total === 1 ? "check" : "checks"} · ${unknown} ${unknown === 1 ? "outcome" : "outcomes"} unknown`;
  }
  return [
    passed > 0 ? `${passed} passed` : null,
    failed > 0 ? `${failed} failed` : null,
    unknown > 0 ? `${unknown} ${unknown === 1 ? "outcome" : "outcomes"} unknown` : null,
  ].filter(Boolean).join(" · ");
}


function sessionTimeline(digest, taskGoal = "") {
  const primary = digest?.activity?.primary;
  const recent = digest?.activity?.recent_sessions || [];
  const candidates = [primary, ...recent]
    .filter(activityIsProjectAssigned)
    .filter((item) => {
      if (!taskGoal) return true;
      const itemGoal = visibleText(item?.request || item?.title || item?.session_title);
      return taskTextCompatible(taskGoal, itemGoal);
    });
  const seen = new Set();
  const result = [];
  for (const item of candidates) {
    const id = [
      normalizeProvider(item.provider || item.tool),
      visibleText(item.session_id || item.source_document_id || item.id),
    ].join(":");
    if (seen.has(id)) continue;
    seen.add(id);
    const summary = visibleText(
      item.outcome?.summary
      || item.result_summary?.summary
      || item.latest_update,
    );
    result.push({
      id: id || `activity-${result.length}`,
      title: visibleText(item.request || item.title || item.session_title) || "Agent session",
      summary,
      updatedAt: item.updated_at || item.source_activity_at || item.ended_at,
      fileCount: Array.isArray(item.changed_files) ? item.changed_files.length : 0,
      verification: observedVerification(item),
      branch: visibleText(item.branch),
      provenance: item.evidence_level === "observed_run" ? "Observed run" : "Session summary",
    });
  }
  return result
    .sort((left, right) => timestampValue(right.updatedAt) - timestampValue(left.updatedAt))
    .slice(0, 4);
}


function attentionItems(digest, sections, projectedItems = []) {
  const items = [...projectedItems];
  for (const record of sections.conflicts || []) {
    items.push({
      id: record.id,
      label: "Conflict",
      title: visibleText(record.title) || "Conflicting project memory",
      summary: visibleText(record.summary),
      href: SECTION_LINKS.conflicts,
    });
  }
  for (const record of sections.stale || []) {
    items.push({
      id: record.id,
      label: "Stale source",
      title: visibleText(record.title) || "Source needs refresh",
      summary: visibleText(record.summary),
      href: SECTION_LINKS.stale,
    });
  }
  for (const card of digestAttentionCards(digest)) {
    items.push({
      id: card.id,
      label: visibleText(card.category || card.status) || "Review",
      title: visibleText(card.title) || "Context needs review",
      summary: visibleText(card.summary || card.content),
      href: card.id ? `/app/explain?card=${encodeURIComponent(card.id)}` : "/app/explain",
    });
  }
  const seen = new Set();
  return items.filter((item) => {
    const key = `${item.label}:${item.title}`.toLowerCase();
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}


function digestAttentionCards(digest) {
  return (digest?.cards || [])
    .filter((card) => card?.attention_required)
    .filter((card) => card?.workspace_relevance?.status !== "not_relevant")
    .filter((card) => {
      const category = String(card.category || card.type || "").toLowerCase();
      const status = String(card.status || "").toLowerCase();
      const severity = String(card.severity || card.risk_level || "").toLowerCase();
      return (
        ["conflict", "stale", "blocked"].includes(status)
        || ["blocker", "risk", "conflict"].includes(category)
        || ["high", "critical"].includes(severity)
      );
    });
}


function activityIsProjectAssigned(activity) {
  if (!activity) return false;
  if (
    activity.evidence_level === "session_unassigned"
    || String(activity.state || "").trim().toLowerCase() === "unassigned"
  ) {
    return false;
  }
  const matchStatus = String(
    activity.project_match?.status
    || activity.workspace_relevance?.status
    || "",
  )
    .trim()
    .toLowerCase()
    .replaceAll("-", "_");
  return !matchStatus || matchStatus === "relevant";
}


function taskTextCompatible(left, right) {
  const normalizedLeft = normalizeTaskText(left);
  const normalizedRight = normalizeTaskText(right);
  if (!normalizedLeft || !normalizedRight) return false;
  if (normalizedLeft === normalizedRight) return true;
  const shorter = normalizedLeft.length <= normalizedRight.length
    ? normalizedLeft
    : normalizedRight;
  const longer = shorter === normalizedLeft ? normalizedRight : normalizedLeft;
  return shorter.length >= 12 && longer.includes(shorter);
}


function normalizeTaskText(value) {
  return rawText(value)
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}


function checkpointMatchesActivity(checkpoint, activity) {
  if (!checkpoint || !activity) return false;
  const checkpointProvider = normalizeProvider(checkpoint.provider);
  const activityProvider = normalizeProvider(activity.provider || activity.tool);
  const checkpointSession = visibleText(checkpoint.session_id);
  const activitySession = visibleText(activity.session_id);
  if (
    !checkpointProvider
    || !activityProvider
    || checkpointProvider !== activityProvider
  ) {
    return false;
  }
  if (checkpointSession && activitySession) {
    return checkpointSession === activitySession;
  }
  const checkpointSource = rawText(checkpoint.source_document_id);
  const activitySource = rawText(activity.source_document_id);
  return Boolean(checkpointSource && activitySource && checkpointSource === activitySource);
}


function repositoryPathsMatch(left, right) {
  const normalizedLeft = normalizeComparableRepoPath(left);
  const normalizedRight = normalizeComparableRepoPath(right);
  return Boolean(normalizedLeft && normalizedRight && normalizedLeft === normalizedRight);
}


function openLoopMatchesTask(item, identity) {
  if (!item) return false;
  const associations = [
    [rawText(item.focus_component_id), rawText(identity.focusComponentId)],
    [rawText(item.context_pack_id), rawText(identity.contextPackId)],
    [rawText(item.run_id), rawText(identity.runId)],
  ];
  return associations.some(([itemValue, taskValue]) => (
    itemValue && taskValue && itemValue === taskValue
  ));
}


function successfulCompletionSummary(activity) {
  if (!activity) return "";
  const state = String(activity.state || "").trim().toLowerCase();
  const outcomeStatus = String(activity.outcome?.status || "").trim().toLowerCase();
  const failureStates = new Set([
    "aborted",
    "blocked",
    "cancelled",
    "error",
    "failed",
    "rejected",
    "timed_out",
    "timeout",
  ]);
  if (failureStates.has(state) || failureStates.has(outcomeStatus)) return "";

  const completionStates = new Set([
    "completed",
    "passed",
    "success",
    "succeeded",
    "verified",
  ]);
  const outcomeSummary = visibleText(activity.outcome?.summary);
  if (
    outcomeSummary
    && completionStates.has(state)
    && (!outcomeStatus || completionStates.has(outcomeStatus))
  ) {
    return outcomeSummary;
  }

  if (String(activity.result_summary?.kind || "").toLowerCase() === "completion") {
    return visibleText(
      activity.result_summary?.summary
      || activity.result_summary?.text,
    );
  }
  return "";
}


function activityOutcomeNeedsAttention(activity) {
  const state = String(activity?.state || "").trim().toLowerCase();
  const outcomeStatus = String(activity?.outcome?.status || "").trim().toLowerCase();
  const failureStates = [
    "aborted",
    "blocked",
    "cancelled",
    "error",
    "failed",
    "rejected",
    "timed_out",
    "timeout",
  ];
  return failureStates.includes(state) || failureStates.includes(outcomeStatus);
}


function activeCheckpointItems(items) {
  if (!Array.isArray(items)) return [];
  return items.filter((item) => (
    !INACTIVE_CHECKPOINT_STATES.has(String(item?.state || "active").toLowerCase())
  ));
}


function checkpointDecisionIsDurable(item) {
  return ["user_stated", "verified"].includes(
    String(item?.truth_state || "").toLowerCase(),
  );
}


function checkpointItemIsGrounded(item) {
  return ["user_stated", "observed", "verified"].includes(
    String(item?.truth_state || "").toLowerCase(),
  );
}


function checkpointSafetySummary(checkpoint) {
  const reasons = [];
  if (!SUPPORTED_CHECKPOINT_SCHEMAS.has(checkpoint?.schema_version)) reasons.push("its schema is not the current durable format");
  if (checkpoint?.currentness?.state !== "captured") reasons.push("it is no longer the captured session tip");
  if (checkpoint?.capture_status !== "complete") reasons.push("its capture is incomplete");
  if (checkpoint?.projection?.valid !== true) reasons.push("its safe projection is invalid");
  if (
    checkpoint?.boundary?.has_newer_events !== false
    || !Number.isInteger(checkpoint?.boundary?.sequence_number)
    || checkpoint?.boundary?.sequence_number !== checkpoint?.boundary?.session_tip_sequence
  ) {
    reasons.push("its boundary is not the latest observed session event");
  }
  return reasons.length
    ? `Excluded because ${reasons.join(", ")}.`
    : "The checkpoint did not match the selected task and session.";
}


function extractFilePaths(value) {
  const text = rawText(value);
  if (!text) return [];
  return text.match(/(?:[\w.-]+\/)+[\w.@-]+(?:\.[A-Za-z0-9_-]+)?/g) || [];
}


function uniqueText(values) {
  const seen = new Set();
  const result = [];
  for (const value of values) {
    const normalized = visibleText(value);
    if (!normalized) continue;
    const key = normalized.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    result.push(normalized);
  }
  return result;
}


function uniquePaths(values) {
  const seen = new Set();
  const result = [];
  for (const value of values) {
    const normalized = rawText(value);
    if (!normalized) continue;
    const key = normalized.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    result.push(normalized);
  }
  return result;
}


function visibleText(value) {
  if (value === null || value === undefined) return "";
  return cleanDisplayText(String(value)).trim();
}


function rawText(value) {
  if (value === null || value === undefined) return "";
  return String(value).trim();
}


function normalizeProvider(value) {
  const normalized = visibleText(value)
    .toLowerCase()
    .replace(/^daemonstate:/, "");
  if (normalized === "claude_code" || normalized === "claude-code") return "claude";
  if (normalized === "open_code" || normalized === "open-code") return "opencode";
  return normalized;
}


function timestampValue(value) {
  const parsed = value ? new Date(value).getTime() : 0;
  return Number.isFinite(parsed) ? parsed : 0;
}


function auditItemLabel(item) {
  return visibleText(
    item?.title
    || item?.statement
    || item?.summary
    || item?.lane
    || item?.type
    || item?.reason,
  ) || "Context item";
}


function auditItemReason(item) {
  const reason = visibleText(item?.reason);
  return reason && reason !== auditItemLabel(item) ? reason : "";
}


function humanizeStatus(value) {
  const text = visibleText(value).replaceAll("_", " ");
  return text ? `${text.charAt(0).toUpperCase()}${text.slice(1)}` : "Unknown";
}


function projectContextErrorIsRetryable(error) {
  if (!error) return true;
  const message = String(error).toLowerCase();
  return ![
    "compiler dropped a referenced attachment",
    "compiled context belongs to a different",
    "compiler returned an incomplete continuation context",
    "failed its content integrity check",
    "compiler returned an incomplete project context",
  ].some((terminalMessage) => message.includes(terminalMessage));
}


async function projectContextContent(result) {
  const projectContext = result?.project_context;
  if (
    projectContext?.schema_version !== "continuation_staging_context.v1"
    || projectContext.scope !== "project"
    || typeof projectContext.content !== "string"
    || !projectContext.content.trim()
    || typeof projectContext.sha256 !== "string"
    || !projectContext.sha256.trim()
  ) {
    throw new Error("The compiler returned an incomplete Project Context.");
  }
  if (projectContext.copy_ready !== true) {
    throw new Error(projectContextQualityMessage(result));
  }
  await requireMatchingContentSha256(
    projectContext.content,
    projectContext.sha256,
    "Project Context",
  );
  return projectContext.content;
}


function projectContextQualityMessage(result) {
  const issues = Array.isArray(result?.project_context?.quality_issues)
    ? result.project_context.quality_issues.filter(
      (issue) => issue?.blocks_copy !== false,
    )
    : [];
  const detail = issues
    .map((issue) => visibleText(issue?.message))
    .filter(Boolean)
    .slice(0, 2)
    .join(" ");
  return detail
    ? `Project Context is not copy-ready. ${detail}`
    : "Project Context is not copy-ready because its quality gate did not pass.";
}


function validateSessionContext(result, expected = {}) {
  if (
    result?.schema_version !== "session_handoff.v1"
    || result.scope !== "session"
    || typeof result.content !== "string"
    || !result.content.trim()
    || typeof result.sha256 !== "string"
    || !result.sha256.trim()
    || !result.checkpoint_id
    || typeof result.quality_report !== "object"
    || result.quality_report === null
    || typeof result.quality_report.copy_ready !== "boolean"
  ) {
    throw new Error("The checkpoint service returned an incomplete Current Session Context.");
  }
  if (
    expected.provider
    && normalizeProvider(result.provider) !== normalizeProvider(expected.provider)
  ) {
    throw new Error("The Current Session Context belongs to a different harness.");
  }
  if (
    expected.sessionId
    && rawText(result.session_id) !== rawText(expected.sessionId)
  ) {
    throw new Error("The Current Session Context belongs to a different session.");
  }
  if (
    expected.checkpointId
    && rawText(result.checkpoint_id) !== rawText(expected.checkpointId)
  ) {
    throw new Error("The Current Session Context belongs to a different checkpoint.");
  }
  if (
    Number.isInteger(expected.boundarySequence)
    && result.boundary?.sequence_number !== expected.boundarySequence
  ) {
    throw new Error("The Current Session Context belongs to a different session boundary.");
  }
  return result;
}


function sessionGoalIsUnavailable(error) {
  const code = rawText(
    error?.code
    || error?.detail?.code
    || error?.detail?.detail?.code,
  ).toLowerCase();
  const message = rawText(
    error?.message
    || error?.detail?.message
    || error?.detail?.detail?.message,
  ).toLowerCase();
  return (
    code === "session_goal_unavailable"
    || code === "checkpoint_goal_unavailable"
    || (
      message.includes("lossless")
      && message.includes("goal")
    )
    || message.includes("original goal event is unavailable")
  );
}


function unavailableSessionGoalError() {
  const error = new Error(
    "This session no longer retains its original user request, so a trustworthy Current Session Context cannot be produced. Choose another session or checkpoint in History.",
  );
  error.code = "session_goal_unavailable";
  error.retryable = false;
  return error;
}


function sessionContextFailure(error, fallback) {
  if (sessionGoalIsUnavailable(error)) {
    return {
      message: unavailableSessionGoalError().message,
      retryable: false,
    };
  }
  if (isTransientNetworkFailure(error)) {
    return {
      message: "Could not reach DaemonState to verify the current session. Keep the local service running, then try copy again.",
      retryable: true,
    };
  }
  return {
    message: error?.message || fallback,
    retryable: error?.retryable !== false,
  };
}


function isTransientNetworkFailure(error) {
  if (error?.status) return false;
  const message = rawText(error?.message || error).toLowerCase();
  return (
    error instanceof TypeError
    || message.includes("failed to fetch")
    || message.includes("network error")
    || message.includes("networkerror")
    || message.includes("load failed")
  );
}


async function retryTransientNetworkRequest(request, retryEnabled) {
  let attempt = 0;
  while (true) {
    try {
      return await request();
    } catch (error) {
      const retryDelay = SESSION_NETWORK_RETRY_DELAYS_MS[attempt];
      if (
        !retryEnabled
        || retryDelay === undefined
        || !isTransientNetworkFailure(error)
      ) {
        throw error;
      }
      await new Promise((resolve) => globalThis.setTimeout(resolve, retryDelay));
      attempt += 1;
    }
  }
}


function sessionCheckpointIsCurrent(checkpoint, provider, sessionId) {
  if (
    !checkpoint
    || !SUPPORTED_CHECKPOINT_SCHEMAS.has(checkpoint.schema_version)
    || !checkpoint.id
    || normalizeProvider(checkpoint.provider) !== normalizeProvider(provider)
    || rawText(checkpoint.session_id) !== rawText(sessionId)
    || checkpoint.capture_status !== "complete"
    || checkpoint.currentness?.state !== "captured"
    || checkpoint.boundary?.has_newer_events !== false
    || !Number.isInteger(checkpoint.boundary?.sequence_number)
    || checkpoint.boundary.sequence_number !== checkpoint.boundary.session_tip_sequence
  ) {
    return false;
  }
  return true;
}


function approximateTokens(content) {
  return Math.max(1, Math.ceil(String(content || "").length / 4));
}


async function writeClipboard(content) {
  if (!content) {
    throw new Error("There is no context to copy.");
  }
  if (!globalThis.navigator?.clipboard?.writeText) {
    throw new Error("Clipboard access is unavailable in this browser.");
  }
  await globalThis.navigator.clipboard.writeText(content);
}


function validatePreparedContext(result, expectedIdentity = {}) {
  // Identity checks must use lossless task data. cleanDisplayText is only for
  // presentation and intentionally removes labels such as "Context:", which
  // can be substantive text in an authoritative user request.
  const selectedGoal = rawText(
    result?.task?.selected_intent?.objective
    || result?.task?.workflow?.selected_intent?.objective
    || result?.task?.title
    || result?.objective,
  );
  const contractRequest = rawText(
    result?.execution_contract?.task?.request_verbatim,
  );
  const taskIdentity = result?.task?.identity;
  const contractTaskIdentity = result?.execution_contract?.task_identity;
  const readinessStatus = String(result?.readiness?.status || "").toLowerCase();
  const manifest = result?.manifest;
  const manifestTaskIdentity = manifest?.continuation?.task_identity;
  const executingPrerequisite = (
    result?.task?.workflow?.execution_reason === "unfinished_prerequisite"
  );
  if (
    !result
    || result.schema_version !== "continuation.v1"
    || !result.context_pack_id
    || !result.markdown
    || result?.project_context?.schema_version !== "continuation_staging_context.v1"
    || result.project_context.scope !== "project"
    || typeof result.project_context.content !== "string"
    || !result.project_context.content.trim()
    || typeof result.project_context.sha256 !== "string"
    || !result.project_context.sha256.trim()
    || typeof result.project_context.copy_ready !== "boolean"
    || !Array.isArray(result.project_context.quality_issues)
    || !result.task
    || typeof result.task !== "object"
    || !selectedGoal
    || !result.task.workflow
    || typeof result.task.workflow !== "object"
    || !result.repository
    || typeof result.repository !== "object"
    || Array.isArray(result.repository)
    || !result.repository.freshness
    || typeof result.repository.freshness !== "object"
    || !["matched", "changed", "unavailable", "not_applicable"].includes(
      String(result.repository.freshness.status || "").toLowerCase(),
    )
    || !result.readiness
    || typeof result.readiness !== "object"
    || !["ready", "review_required", "blocked"].includes(readinessStatus)
    || !Array.isArray(result.attention)
    || typeof result.quality_report !== "object"
    || result.quality_report === null
    || typeof result.quality_report.launchable !== "boolean"
    || manifest?.schema_version !== "context_pack.v2"
    || manifest.context_pack_id !== result.context_pack_id
    || rawText(manifest.objective) !== rawText(result.objective)
    || manifest.continuation?.task_id !== result.task.id
    || rawText(manifest.continuation?.execution_objective) !== rawText(result.objective)
    || manifest.token_accounting?.within_budget !== true
    || manifest.rendering?.within_budget !== true
    || !Array.isArray(manifest.selected_context)
    || !Array.isArray(manifest.excluded_context)
    || !taskIdentityCopiesAreValid(
      taskIdentity,
      manifestTaskIdentity,
      contractTaskIdentity,
    )
    || (
      taskIdentity
      && (
        taskIdentity.schema_version !== "continuation_task_identity.v1"
        || rawText(taskIdentity.id) !== rawText(result.task.id)
      )
    )
  ) {
    throw new Error("The compiler returned an incomplete continuation context.");
  }
  const referencedImagePaths = imagePathsFromRequest(contractRequest);
  const manifestArtifactPaths = (
    manifest?.continuation?.artifacts || []
  )
    .flatMap((artifact) => [
      rawText(artifact?.path),
      rawText(artifact?.source_path),
    ])
    .filter(Boolean);
  const expectedArtifactPaths = [
    ...new Set([...referencedImagePaths, ...manifestArtifactPaths]),
  ];
  if (expectedArtifactPaths.length) {
    const compiledArtifactPaths = new Set(
      (result?.execution_contract?.artifacts || [])
        .flatMap((artifact) => [
          rawText(artifact?.path),
          rawText(artifact?.source_path),
        ])
        .filter(Boolean),
    );
    const missingImages = expectedArtifactPaths.filter(
      (path) => !compiledArtifactPaths.has(path),
    );
    if (missingImages.length) {
      throw new Error(
        "The compiler dropped a referenced attachment; Project Context was not prepared.",
      );
    }
  }
  if (
    expectedIdentity.workspaceId
    && taskIdentity
    && rawText(taskIdentity.workspace_id) !== rawText(expectedIdentity.workspaceId)
  ) {
    throw new Error("The compiled context belongs to a different workspace.");
  }
  if (expectedIdentity.objective) {
    const expectedTaskKey = normalizeTaskText(expectedIdentity.objective);
    const selectedTaskKey = rawText(taskIdentity?.selected_objective_key);
    const taskMatches = selectedTaskKey
      ? selectedTaskKey === expectedTaskKey
      : contractRequest
        ? normalizeTaskText(contractRequest) === expectedTaskKey
        : taskTextCompatible(expectedIdentity.objective, selectedGoal);
    if (!taskMatches) {
      throw new Error("The compiled context belongs to a different task.");
    }
  }
  if (
    expectedIdentity.repoPath
    && normalizeComparableRepoPath(result.repository.path)
      !== normalizeComparableRepoPath(expectedIdentity.repoPath)
  ) {
    throw new Error("The compiled context belongs to a different repository.");
  }
  const checkpointIdentityMismatch = Boolean(
    expectedIdentity.checkpointId
    && (
      rawText(result.checkpoint?.id) !== rawText(expectedIdentity.checkpointId)
      || rawText(manifest.continuation?.checkpoint_id)
        !== rawText(expectedIdentity.checkpointId)
    )
  );
  if (checkpointIdentityMismatch && !executingPrerequisite) {
    throw new Error("The compiled context belongs to a different checkpoint.");
  }
  const sourceIdentityMismatch = Boolean(
    expectedIdentity.sourceProvider
    && (
      normalizeProvider(result.source_session?.provider)
        !== normalizeProvider(expectedIdentity.sourceProvider)
      || rawText(result.source_session?.session_id)
        !== rawText(expectedIdentity.sourceSessionId)
    )
  );
  if (sourceIdentityMismatch && !executingPrerequisite) {
    throw new Error("The compiled context belongs to a different source session.");
  }
  if (executingPrerequisite && (checkpointIdentityMismatch || sourceIdentityMismatch)) {
    return {
      ...result,
      _memory_preview: {
        prerequisite_anchor_switched: true,
      },
    };
  }
  return result;
}


function imagePathsFromRequest(value) {
  const paths = [];
  const seen = new Set();
  const pattern = /<image\b[^>]*\bpath\s*=\s*(?:"([^"]+)"|'([^']+)'|([^\s>]+))[^>]*>/gi;
  for (const match of String(value || "").matchAll(pattern)) {
    const path = rawText(match[1] || match[2] || match[3]);
    if (!path || seen.has(path)) continue;
    seen.add(path);
    paths.push(path);
  }
  return paths;
}


function taskIdentityCopiesAreValid(
  taskIdentity,
  manifestTaskIdentity,
  contractTaskIdentity,
) {
  const identities = [
    taskIdentity,
    manifestTaskIdentity,
    contractTaskIdentity,
  ];
  const present = identities.filter(Boolean);
  if (!present.length) return true;
  if (
    present.length !== identities.length
    || present.some((identity) => typeof identity !== "object")
  ) return false;
  const fields = [
    "schema_version",
    "id",
    "workspace_id",
    "selected_objective_key",
    "selected_objective_sha256",
    "authoritative_request_sha256",
    "workspace_goal_id",
    "selected_component_id",
  ];
  return fields.every((field) => {
    const expected = rawText(taskIdentity[field]);
    return identities.every((identity) => rawText(identity[field]) === expected);
  });
}


function normalizeComparableRepoPath(value) {
  const path = rawText(value);
  if (!path) return "";
  const withoutTrailingSlash = path.replace(/\/+$/, "");
  return withoutTrailingSlash || "/";
}
