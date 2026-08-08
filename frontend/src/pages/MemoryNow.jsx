import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Link, useNavigate } from "react-router-dom";
import {
  AlertTriangle,
  ArrowRight,
  BookOpenCheck,
  Clipboard,
  FileCode2,
  FolderRoot,
  LockKeyhole,
  RefreshCw,
  ShieldCheck,
  Trash2,
  X,
} from "lucide-react";

import {
  useCaptureCheckpoint,
  useCheckpointHandoff,
  useLatestCheckpoint,
  useSessionLibrary,
} from "../api/hooks";
import HarnessDeckBackdrop from "../components/HarnessDeckBackdrop";
import { HarnessArtwork } from "../components/HarnessBrand";
import ProductLoadingState from "../components/ProductLoadingState";
import WorkspaceTopicGate from "../components/WorkspaceTopicGate";
import {
  useContextDigest,
  usePrepareContext,
  useProjectMemory,
} from "../context-map/api";
import { cleanDisplayText, formatTimeAgo } from "../context-map/digest";
import {
  copyReadySessionContextContent,
  requireMatchingContentSha256,
  sessionContextQualityMessage,
} from "./sessionContinuity";
import {
  MINIMUM_SESSION_CONTEXT_COMPACTIONS,
  sessionContextCompactionCount,
  sessionContextCompactionProgress,
} from "./sessionContextPolicy";
import {
  executeSessionIdentity,
  MAX_EXECUTE_SESSION_CONTEXTS,
  readExecuteSessionContexts,
  resolveExecuteSessionContexts,
  writeExecuteSessionContexts,
} from "./executeSessionSelection";
import { useProductWorkspace } from "./useProductWorkspace";

const SECTION_LINKS = {
  requirements: "/app/execute/inspector?view=active&category=requirements",
  decisions: "/app/execute/inspector?view=active&category=decisions",
  work: "/app/execute/inspector?view=active&category=work",
  blockers: "/app/execute/inspector?view=active&category=blockers",
  learnings: "/app/execute/inspector?view=active&category=learnings",
  deliveries: "/app/execute/inspector?view=active&category=deliveries",
  conflicts: "/app/execute/inspector?view=review",
  stale: "/app/execute/inspector?view=freshness",
  completed: "/app/execute/inspector?view=history&section=completed",
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
  "work_checkpoint.v8",
  "work_checkpoint.v9",
  "work_checkpoint.v10",
]);
const SUPPORTED_WORKSPACE_FOUNDATION_SCHEMAS = new Set([
  "workspace_foundation.v1",
  "workspace_foundation.v2",
]);
const CURRENT_CHECKPOINT_SCHEMA = "work_checkpoint.v10";
const SESSION_NETWORK_RETRY_DELAYS_MS = [120, 300];


export default function ExecutePage() {
  const workspace = useProductWorkspace();
  const digestQuery = useContextDigest(workspace.activeWorkspaceId, { poll: true });
  const memoryQuery = useProjectMemory(workspace.activeWorkspaceId, {
    limit: 6,
    poll: true,
    scope: "workspace",
  });
  const sessionLibraryQuery = useSessionLibrary(workspace.activeWorkspaceId);
  const [storedExecuteSessions, setStoredExecuteSessions] = useState(() => (
    readExecuteSessionContexts(workspace.activeWorkspaceId)
  ));
  const storedExecuteWorkspaceRef = useRef(workspace.activeWorkspaceId);
  const activeStoredExecuteSessions = (
    storedExecuteWorkspaceRef.current === workspace.activeWorkspaceId
      ? storedExecuteSessions
      : []
  );
  // Execute no longer owns an automatic current-session card. Workspace
  // Context compilation below is workspace/repository scoped; every visible
  // Session Context is explicitly selected by the user.
  const candidateActivity = digestQuery.data?.activity?.primary || null;
  const checkpointActivity = candidateActivity;
  const activityProvider = normalizeProvider(
    checkpointActivity?.provider || checkpointActivity?.tool,
  );
  const activitySessionId = visibleText(checkpointActivity?.session_id);
  const hasScopedSession = Boolean(activityProvider && activitySessionId);
  const selectedExecuteSessions = useMemo(() => {
    return resolveExecuteSessionContexts(
      activeStoredExecuteSessions,
      sessionLibraryQuery.data
        ? sessionLibraryQuery.data.sessions || []
        : undefined,
    ).slice(0, MAX_EXECUTE_SESSION_CONTEXTS);
  }, [
    activeStoredExecuteSessions,
    sessionLibraryQuery.data,
    workspace.activeWorkspaceId,
  ]);
  const removeExecuteSession = useCallback((session) => {
    const sourceDocumentId = rawText(
      session?.sourceDocumentId
      || session?.source_document_id,
    );
    const identity = executeSessionIdentity(session);
    if (!sourceDocumentId && !identity) return;

    setStoredExecuteSessions((current) => writeExecuteSessionContexts(
      workspace.activeWorkspaceId,
      current.filter((item) => {
        const itemSourceDocumentId = rawText(
          item?.sourceDocumentId
          || item?.source_document_id,
        );
        const matchesSource = Boolean(
          sourceDocumentId
          && itemSourceDocumentId === sourceDocumentId
        );
        const matchesIdentity = Boolean(
          identity
          && executeSessionIdentity(item) === identity
        );
        return !matchesSource && !matchesIdentity;
      }),
    ));
  }, [workspace.activeWorkspaceId]);
  const checkpointLookupEnabled = Boolean(digestQuery.data);
  const checkpointQuery = useLatestCheckpoint(workspace.activeWorkspaceId, {
    provider: hasScopedSession ? activityProvider : null,
    sessionId: hasScopedSession ? activitySessionId : null,
    enabled: checkpointLookupEnabled,
  });
  const prepareWorkspaceContext = usePrepareContext();
  const [previewOpen, setPreviewOpen] = useState(false);
  const [preparedContext, setPreparedContext] = useState(null);
  const [preparedContextAnchorKey, setPreparedContextAnchorKey] = useState(null);
  const [previewError, setPreviewError] = useState(null);
  const previewReturnFocusRef = useRef(null);
  const autoWorkspacePreviewKeyRef = useRef(null);
  const workspaceCompilePromiseRef = useRef(null);
  const closePreview = useCallback(() => setPreviewOpen(false), []);
  const [workspaceCopyState, setWorkspaceCopyState] = useState("idle");

  useEffect(() => {
    if (storedExecuteWorkspaceRef.current === workspace.activeWorkspaceId) {
      return;
    }
    storedExecuteWorkspaceRef.current = workspace.activeWorkspaceId;
    setStoredExecuteSessions(
      readExecuteSessionContexts(workspace.activeWorkspaceId),
    );
  }, [workspace.activeWorkspaceId]);

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
  const workspaceRepoPath = rawText(
    workspace.activeWorkspace?.repo_path
    || digestQuery.data?.scope?.project_paths?.[0],
  );
  const workspaceContextKey = JSON.stringify([
    workspace.activeWorkspaceId || "",
    normalizeComparableRepoPath(workspaceRepoPath),
  ]);
  const activeWorkspaceContextKeyRef = useRef(workspaceContextKey);
  activeWorkspaceContextKeyRef.current = workspaceContextKey;
  const currentPreparedContext = (
    preparedContextAnchorKey === workspaceContextKey
      ? preparedContext
      : null
  );

  useEffect(() => {
    setPreviewOpen(false);
    setPreparedContext(null);
    setPreparedContextAnchorKey(null);
    setPreviewError(null);
    setWorkspaceCopyState("idle");
  }, [workspaceContextKey]);

  const firstLoad = (
    workspace.workspacesQuery.isLoading
    || (digestQuery.isLoading && !digestQuery.data)
    || (memoryQuery.isLoading && !memoryQuery.data)
    || (checkpointLookupEnabled && checkpointQuery.isLoading && !checkpointQuery.data)
  );
  const workspaceSelectionLoading = workspace.workspacesQuery.isLoading;
  const partialData = digestQuery.isError || memoryQuery.isError || checkpointQuery.isError;
  const workspacePreviewPreparing = Boolean(
    prepareWorkspaceContext.isPending
    || (
      workspace.activeWorkspaceId
      && !currentPreparedContext
      && !previewError
    )
  );
  const workspacePreviewRetryable = workspaceContextErrorIsRetryable(previewError);

  const compileWorkspaceContext = useCallback(async ({ force = false } = {}) => {
    if (!workspace.activeWorkspaceId) {
      throw new Error("Workspace Context is unavailable because no workspace is selected.");
    }
    if (currentPreparedContext && !force) return currentPreparedContext;
    const requestAnchor = workspaceContextKey;
    if (
      !force
      && workspaceCompilePromiseRef.current?.key === requestAnchor
    ) {
      return workspaceCompilePromiseRef.current.promise;
    }

    const operation = (async () => {
      const response = await prepareWorkspaceContext.mutateAsync({
        workspace_id: workspace.activeWorkspaceId,
        ...(workspaceRepoPath ? { repo_path: workspaceRepoPath } : {}),
        mode: "project_snapshot",
        objective_origin: "project_snapshot",
      });
      if (activeWorkspaceContextKeyRef.current !== requestAnchor) {
        throw new Error("The selected workspace changed while Workspace Context was compiling.");
      }
      const result = validateWorkspaceContext(response, {
        workspaceId: workspace.activeWorkspaceId,
        repoPath: workspaceRepoPath,
      });
      await requireMatchingContentSha256(
        result.workspace_context.content,
        result.workspace_context.sha256,
        "Workspace Context",
      );
      if (activeWorkspaceContextKeyRef.current !== requestAnchor) {
        throw new Error("The selected workspace changed while Workspace Context was compiling.");
      }
      setPreparedContext(result);
      setPreparedContextAnchorKey(requestAnchor);
      return result;
    })();
    workspaceCompilePromiseRef.current = { key: requestAnchor, promise: operation };
    try {
      return await operation;
    } finally {
      if (workspaceCompilePromiseRef.current?.promise === operation) {
        workspaceCompilePromiseRef.current = null;
      }
    }
  }, [
    currentPreparedContext,
    prepareWorkspaceContext,
    workspace.activeWorkspaceId,
    workspaceContextKey,
    workspaceRepoPath,
  ]);

  const generatePreview = async (trigger = null) => {
    if (!workspace.activeWorkspaceId) return;
    previewReturnFocusRef.current = trigger || document.activeElement;
    setPreviewOpen(true);
    if (currentPreparedContext || prepareWorkspaceContext.isPending) return;
    setPreviewError(null);
    try {
      await compileWorkspaceContext();
    } catch (error) {
      setPreviewError(error?.message || "Could not generate Workspace Context.");
    }
  };

  const retryPreview = async () => {
    setPreparedContext(null);
    setPreparedContextAnchorKey(null);
    setPreviewError(null);
    try {
      await compileWorkspaceContext({ force: true });
    } catch (error) {
      setPreviewError(error?.message || "Could not generate Workspace Context.");
    }
  };

  const copyWorkspaceContext = async () => {
    setWorkspaceCopyState("copying");
    setPreviewError(null);
    try {
      // Clipboard content is an execution boundary. Recompile immediately so
      // an internally valid but repository-stale preview cannot be copied.
      const result = await compileWorkspaceContext({ force: true });
      await writeClipboard(await workspaceContextContent(result));
      setWorkspaceCopyState("copied");
      return true;
    } catch (error) {
      setWorkspaceCopyState("error");
      setPreviewError(error?.message || "Workspace Context could not be copied.");
      return false;
    }
  };

  useEffect(() => {
    if (
      workspaceSelectionLoading
      || !workspace.activeWorkspaceId
      || currentPreparedContext
      || prepareWorkspaceContext.isPending
    ) return undefined;

    const previewKey = workspaceContextKey;
    if (autoWorkspacePreviewKeyRef.current === previewKey) return undefined;
    autoWorkspacePreviewKeyRef.current = previewKey;

    let active = true;
    setPreviewError(null);
    compileWorkspaceContext().catch((error) => {
      if (active && activeWorkspaceContextKeyRef.current === workspaceContextKey) {
        setPreviewError(error?.message || "Could not generate Workspace Context.");
      }
    });
    return () => {
      active = false;
    };
  }, [
    compileWorkspaceContext,
    currentPreparedContext,
    prepareWorkspaceContext.isPending,
    workspace.activeWorkspaceId,
    workspaceContextKey,
    workspaceSelectionLoading,
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
      <div className="relative mx-auto min-h-full w-full max-w-none">
        <ExecuteWorkspaceFrame
          workspace={workspace.activeWorkspace}
          status="Preparing"
          busy
          selectedSessions={selectedExecuteSessions}
        >
          <div className="p-5 sm:p-7 lg:p-10">
            <ProductLoadingState
              label="Preparing the execution workspace…"
              detail="Reading the durable workspace foundation, repository state, and selected Session Contexts."
              stages={["Loading workspace context", "Reconciling project state", "Resolving selected sessions"]}
            />
          </div>
        </ExecuteWorkspaceFrame>
      </div>
    );
  }

  return (
    <div className="relative mx-auto min-h-full w-full max-w-none">
      <ExecuteWorkspaceFrame
        workspace={workspace.activeWorkspace}
        status={partialData ? "Partial context" : "Workspace ready"}
        attention={partialData}
        selectedSessions={selectedExecuteSessions}
      >
        {partialData ? (
          <div role="status" className="mx-5 mt-5 rounded-control border border-attention/30 bg-attention/10 px-4 py-3 text-xs font-medium leading-5 text-ink sm:mx-7 lg:mx-10">
            Some live context is temporarily unavailable. Execute is showing only the source-backed context that loaded successfully.
          </div>
        ) : null}

        <ContextProductsPanel
          preparedContext={currentPreparedContext}
          workspacePreparing={workspacePreviewPreparing}
          workspaceCopyState={workspaceCopyState}
          workspaceError={previewError}
          workspaceRetryable={workspacePreviewRetryable}
          workspaceDialogOpen={previewOpen}
          onPreviewWorkspace={generatePreview}
          onCopyWorkspace={copyWorkspaceContext}
          workspaceId={workspace.activeWorkspaceId}
          selectedSessions={selectedExecuteSessions}
          onRemoveSelectedSession={removeExecuteSession}
        />
      </ExecuteWorkspaceFrame>

      {previewOpen ? createPortal(
        <ContextPreviewDialog
          result={currentPreparedContext}
          loading={workspacePreviewPreparing}
          error={previewError}
          canRetry={workspacePreviewRetryable}
          onRetry={retryPreview}
          onCopy={copyWorkspaceContext}
          copyState={workspaceCopyState}
          onClose={closePreview}
          returnFocusRef={previewReturnFocusRef}
        />,
        document.body,
      ) : null}

    </div>
  );
}


function ExecuteWorkspaceFrame({
  workspace,
  status,
  busy = false,
  attention = false,
  selectedSessions = [],
  children,
}) {
  const navigate = useNavigate();
  const workspaceName = visibleText(workspace?.name) || "Selected workspace";
  const selectedCount = Math.min(
    selectedSessions.length,
    MAX_EXECUTE_SESSION_CONTEXTS,
  );
  const openSessionPicker = () => {
    navigate("/app/library?mode=execute-context");
  };

  return (
    <div className="relative mx-auto w-full max-w-7xl space-y-8 pb-14">
      <header
        aria-labelledby="execute-title"
        className="daemonstate-resume-header group relative min-h-56 overflow-hidden rounded-[2rem] border border-[#d8d8cf] bg-[#f7f7f1] px-5 py-7 text-[#171713] dark:border-[#292925] dark:bg-[#0c0c0a] dark:text-white sm:px-8 sm:py-9 lg:px-10"
      >
        <div aria-hidden="true" className="absolute -right-20 -top-24 h-72 w-72 rounded-full bg-[#d9ff68]/25 blur-3xl dark:bg-[#d9ff68]/10" />
        <HarnessDeckBackdrop />
        <div className="relative flex items-start justify-between gap-4">
          <div className="min-w-0">
            <h1 id="execute-title" className="text-3xl font-black tracking-[-0.055em] sm:text-4xl">
              Execute
            </h1>
            <p className="mt-2 max-w-3xl text-sm font-medium leading-6 text-[#68685f] dark:text-[#aaa9a0]">
              Prepare verified workspace context and the Session Contexts you choose.
            </p>
          </div>

          <button
            type="button"
            aria-pressed={selectedCount > 0}
            aria-label={
              selectedCount
                ? `Edit selected session contexts, ${selectedCount} of ${MAX_EXECUTE_SESSION_CONTEXTS} selected`
                : "Select session contexts"
            }
            onClick={openSessionPicker}
            className="group inline-flex min-h-11 shrink-0 items-center gap-3 rounded-xl border border-white/50 bg-white/35 px-3.5 text-left text-[#3f3f38] shadow-[0_10px_28px_rgba(23,23,19,0.10)] backdrop-blur-xl backdrop-saturate-150 transition hover:-translate-y-0.5 hover:border-[#b7d957]/70 hover:bg-white/45 dark:border-white/15 dark:bg-black/30 dark:text-[#ecece4] dark:shadow-[0_10px_30px_rgba(0,0,0,0.22)] dark:hover:border-[#d9ff68]/45 dark:hover:bg-black/38"
          >
            <span className="hidden sm:block">
              <span className="block text-[10px] font-black uppercase tracking-[0.12em]">
                Session contexts
              </span>
              <span className="mt-0.5 block text-[9px] font-semibold text-[#85857c] dark:text-[#929289]">
                {selectedCount} of {MAX_EXECUTE_SESSION_CONTEXTS} selected
              </span>
            </span>
            <span
              aria-hidden="true"
              className={`relative h-6 w-11 rounded-full border transition ${
                selectedCount
                  ? "border-[#95b52f] bg-[#d9ff68]"
                  : "border-[#c9c9bf] bg-[#e8e8e0] dark:border-[#44443e] dark:bg-[#292925]"
              }`}
            >
              <span
                className={`absolute top-0.5 h-[18px] w-[18px] rounded-full bg-[#171713] shadow-sm transition-transform ${
                  selectedCount ? "translate-x-[1.15rem]" : "translate-x-0.5"
                }`}
              />
            </span>
          </button>
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-2">
          <span className="inline-flex min-h-8 items-center gap-2 rounded-full border border-[#d8d8cf] bg-white/60 px-3 text-xs font-semibold text-[#77776e] dark:border-[#292925] dark:bg-white/[0.04] dark:text-[#aaa9a0]">
            <FolderRoot className="h-4 w-4" aria-hidden="true" />
            {workspaceName}
          </span>
          <span
            className={`inline-flex min-h-8 items-center gap-2 rounded-full border px-3 text-xs font-semibold ${
              attention
                ? "border-[#d0a946]/40 bg-[#d0a946]/10 text-[#5f4a12] dark:text-[#e4c875]"
                : "border-[#d8d8cf] bg-white/60 text-[#68685f] dark:border-[#292925] dark:bg-white/[0.04] dark:text-[#aaa9a0]"
            }`}
          >
            {busy
              ? <RefreshCw className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
              : attention
                ? <AlertTriangle className="h-3.5 w-3.5 text-attention" aria-hidden="true" />
                : <ShieldCheck className="h-3.5 w-3.5" aria-hidden="true" />}
            {status}
          </span>
        </div>
      </header>
      {children}
    </div>
  );
}


function ContextProductsPanel({
  preparedContext,
  workspacePreparing,
  workspaceCopyState,
  workspaceError,
  workspaceRetryable,
  workspaceDialogOpen,
  onPreviewWorkspace,
  onCopyWorkspace,
  workspaceId,
  selectedSessions = [],
  onRemoveSelectedSession,
}) {
  const workspaceContent = preparedContext?.workspace_context?.content || "";
  const workspaceAvailable = Boolean(workspaceId);
  const terminalWorkspaceError = Boolean(
    !preparedContext && workspaceError && !workspaceRetryable,
  );

  return (
    <section aria-label="Execution contexts" className="space-y-8">
      <div
        data-session-context-slots
        className="grid grid-cols-1 items-start gap-5 xl:grid-cols-3"
      >
        {selectedSessions.map((session, index) => (
          <SelectedSessionContextCard
            key={executeSessionIdentity(session)}
            workspaceId={workspaceId}
            session={session}
            slot={index + 1}
            total={selectedSessions.length}
            onRemove={onRemoveSelectedSession}
          />
        ))}
        {!selectedSessions.length ? (
          <div className="rounded-2xl border border-dashed border-[#c9c9bf] bg-[#fbfbf6]/55 px-6 py-10 text-center text-[#68685f] dark:border-[#34342f] dark:bg-[#141411]/55 dark:text-[#aaa9a0] xl:col-span-3">
            <h2 className="text-xl font-black tracking-[-0.035em] text-[#171713] dark:text-white">
              Choose Session Contexts
            </h2>
            <p className="mx-auto mt-2 max-w-lg text-xs leading-5">
              Continue owns the live current session. Choose up to three sessions
              from Library to compare or copy here.
            </p>
            <Link
              to="/app/library?mode=execute-context"
              className="btn-secondary mt-5 min-h-11 px-4 text-xs"
            >
              Choose sessions
              <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
            </Link>
          </div>
        ) : null}
      </div>

      <section
        aria-labelledby="workspace-context-heading"
        className="overflow-hidden rounded-2xl border border-[#d8d8cf] bg-[#fbfbf6] p-5 text-[#171713] shadow-[0_18px_40px_rgba(23,23,19,0.07)] dark:border-[#292925] dark:bg-[#141411] dark:text-white sm:p-7"
      >
        <header className="flex flex-col gap-5 lg:flex-row lg:items-center lg:justify-between">
          <h2 id="workspace-context-heading" className="text-3xl font-black tracking-[-0.055em] sm:text-4xl">
            Workspace Context
          </h2>

          <div className="grid w-full gap-3 sm:grid-cols-2 lg:w-auto lg:min-w-[22rem]">
            <button
              type="button"
              aria-label="Preview Workspace Context"
              onClick={(event) => onPreviewWorkspace(event.currentTarget)}
              disabled={!workspaceAvailable || terminalWorkspaceError}
              className="btn-secondary min-h-11 px-4 text-xs"
            >
              {workspacePreparing
                ? <RefreshCw className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
                : <BookOpenCheck className="h-3.5 w-3.5" aria-hidden="true" />}
              {!workspaceAvailable
                ? "Unavailable"
                : workspaceContent
                  ? "Open full preview"
                  : workspaceError
                    ? workspaceRetryable
                      ? "Retry preview"
                      : "Unavailable"
                    : "Preparing…"}
            </button>
            <ContextCopyButton
              contextName="Workspace Context"
              copyState={workspaceCopyState}
              onClick={onCopyWorkspace}
              disabled={!workspaceAvailable || terminalWorkspaceError}
            />
          </div>
        </header>

        <PromptPreview
          label="Workspace Context prompt preview"
          content={workspaceContent}
          loading={workspacePreparing || (
            workspaceAvailable
            && !preparedContext
            && !workspaceError
          )}
          available={workspaceAvailable}
          error={workspaceError}
          unavailableMessage="Select a workspace to compile its repository and durable context."
          className="mt-5 min-h-[360px]"
        />
        {workspaceError ? (
          <p
            role={workspaceDialogOpen ? undefined : "alert"}
            className="mt-3 text-xs leading-5 text-attention"
          >
            {workspaceError}
          </p>
        ) : null}
      </section>
    </section>
  );
}


function SelectedSessionContextCard({
  workspaceId,
  session,
  slot,
  total,
  onRemove,
}) {
  const provider = normalizeProvider(session?.provider);
  const sessionId = rawText(session?.sessionId);
  const title = visibleText(session?.title) || "Selected session";
  const compactionCount = sessionContextCompactionCount(session);
  const contextEligible = (
    compactionCount >= MINIMUM_SESSION_CONTEXT_COMPACTIONS
  );
  const compactionProgress = sessionContextCompactionProgress(compactionCount);
  const compactionRequirement = contextEligible
    ? ""
    : `${MINIMUM_SESSION_CONTEXT_COMPACTIONS} compactions required.`;
  const contextName = `${title} Session Context`;
  const headingId = `selected-session-context-${slot}`;
  const checkpointQuery = useLatestCheckpoint(workspaceId, {
    provider,
    sessionId,
    enabled: Boolean(workspaceId && provider && sessionId && contextEligible),
  });
  const captureCheckpoint = useCaptureCheckpoint();
  const checkpointHandoff = useCheckpointHandoff();
  const [context, setContext] = useState(null);
  const [contextCheckpoint, setContextCheckpoint] = useState(null);
  const [error, setError] = useState(null);
  const [retryable, setRetryable] = useState(true);
  const [copyState, setCopyState] = useState("idle");
  const [previewOpen, setPreviewOpen] = useState(false);
  const previewReturnFocusRef = useRef(null);
  const loadPromiseRef = useRef(null);
  const identity = executeSessionIdentity(session);
  const identityKey = JSON.stringify([workspaceId || "", identity]);
  const requestKey = JSON.stringify([
    identityKey,
    compactionCount,
    checkpointQuery.data?.id || "",
    checkpointQuery.data?.schema_version || "",
    checkpointQuery.data?.boundary?.sequence_number ?? null,
    checkpointQuery.data?.boundary?.session_tip_sequence ?? null,
    checkpointQuery.data?.boundary?.has_newer_events ?? null,
  ]);
  const activeIdentityKeyRef = useRef(identityKey);
  const autoPreviewKeyRef = useRef(null);
  activeIdentityKeyRef.current = identityKey;
  const closePreview = useCallback(() => setPreviewOpen(false), []);

  useEffect(() => {
    setContext(null);
    setContextCheckpoint(null);
    setError(null);
    setRetryable(true);
    setCopyState("idle");
    setPreviewOpen(false);
    loadPromiseRef.current = null;
    autoPreviewKeyRef.current = null;
  }, [requestKey]);

  const recordFailure = useCallback((reason, fallback) => {
    const failure = sessionContextFailure(reason, fallback);
    setError(failure.message);
    setRetryable(failure.retryable);
  }, []);

  const loadContext = useCallback(async ({
    forceCapture = false,
    retryTransientNetworkFailure = false,
  } = {}) => {
    if (!workspaceId || !provider || !sessionId) {
      throw new Error("This selected session no longer has a valid Library identity.");
    }
    if (!contextEligible) {
      throw sessionContextCompactionsRequiredError(compactionCount);
    }
    if (loadPromiseRef.current?.key === requestKey) {
      try {
        return await loadPromiseRef.current.promise;
      } catch (reason) {
        if (
          !forceCapture
          && (
            !retryTransientNetworkFailure
            || !isTransientNetworkFailure(reason)
          )
        ) {
          throw reason;
        }
      }
    }

    const operation = (async () => {
      const captureSelectedTip = () => retryTransientNetworkRequest(
        () => captureCheckpoint.mutateAsync({
          workspaceId,
          provider,
          sessionId,
          updateGenericLatest: false,
        }),
        retryTransientNetworkFailure,
      );
      let checkpoint = (
        forceCapture || checkpointQuery.isFetching
          ? await captureSelectedTip()
          : checkpointQuery.data
      );
      if (
        !forceCapture
        && !sessionCheckpointIsCurrent(checkpoint, provider, sessionId)
      ) {
        checkpoint = await captureSelectedTip();
      }
      if (!checkpoint?.id) {
        throw new Error("The selected session checkpoint could not be captured.");
      }

      const requestHandoff = (checkpointId) => retryTransientNetworkRequest(
        () => checkpointHandoff.mutateAsync({
          workspaceId,
          checkpointId,
        }),
        retryTransientNetworkFailure,
      );
      let handoffResponse;
      try {
        handoffResponse = await requestHandoff(checkpoint.id);
      } catch (reason) {
        if (!forceCapture && sessionGoalIsUnavailable(reason)) {
          const refreshed = await captureSelectedTip();
          if (
            refreshed?.id
            && rawText(refreshed.id) !== rawText(checkpoint.id)
          ) {
            checkpoint = refreshed;
            handoffResponse = await requestHandoff(checkpoint.id);
          } else {
            throw unavailableSessionGoalError();
          }
        } else {
          throw reason;
        }
      }
      const handoff = validateSessionContext(handoffResponse, {
        provider,
        sessionId,
        checkpointId: checkpoint.id,
        boundarySequence: checkpoint.boundary?.sequence_number,
      });
      if (activeIdentityKeyRef.current !== identityKey) {
        throw new Error(
          "The selected session changed while its Session Context was preparing.",
        );
      }
      setContext(handoff);
      setContextCheckpoint(checkpoint);
      setError(null);
      setRetryable(true);
      return { handoff, checkpoint };
    })();
    loadPromiseRef.current = { key: requestKey, promise: operation };
    try {
      return await operation;
    } finally {
      if (loadPromiseRef.current?.promise === operation) {
        loadPromiseRef.current = null;
      }
    }
  }, [
    captureCheckpoint,
    checkpointHandoff,
    checkpointQuery.data,
    checkpointQuery.isFetching,
    identityKey,
    compactionCount,
    contextEligible,
    provider,
    requestKey,
    sessionId,
    workspaceId,
  ]);

  useEffect(() => {
    if (
      !workspaceId
      || !provider
      || !sessionId
      || !contextEligible
      || (checkpointQuery.isLoading && !checkpointQuery.data)
      || checkpointQuery.isFetching
      || context
      || error
      || captureCheckpoint.isPending
      || checkpointHandoff.isPending
    ) return;
    if (autoPreviewKeyRef.current === requestKey) return;
    autoPreviewKeyRef.current = requestKey;

    setError(null);
    setRetryable(true);
    loadContext().catch((reason) => {
      if (activeIdentityKeyRef.current === identityKey) {
        recordFailure(
          reason,
          `${title} Session Context could not be prepared.`,
        );
      }
    });
  }, [
    captureCheckpoint.isPending,
    checkpointHandoff.isPending,
    checkpointQuery.data,
    checkpointQuery.isFetching,
    checkpointQuery.isLoading,
    context,
    contextEligible,
    error,
    identityKey,
    loadContext,
    provider,
    recordFailure,
    requestKey,
    sessionId,
    title,
    workspaceId,
  ]);

  const previewContext = async (trigger) => {
    previewReturnFocusRef.current = trigger || document.activeElement;
    setPreviewOpen(true);
    if (
      context
      || captureCheckpoint.isPending
      || checkpointHandoff.isPending
      || (checkpointQuery.isLoading && !checkpointQuery.data)
    ) {
      return;
    }
    setError(null);
    setRetryable(true);
    try {
      await loadContext();
    } catch (reason) {
      recordFailure(
        reason,
        `${title} Session Context could not be prepared.`,
      );
    }
  };

  const retryContext = async () => {
    setContext(null);
    setContextCheckpoint(null);
    setError(null);
    setRetryable(true);
    try {
      await loadContext({ forceCapture: true });
    } catch (reason) {
      recordFailure(
        reason,
        `${title} Session Context could not be prepared.`,
      );
    }
  };

  const copyContext = async () => {
    setCopyState("copying");
    setError(null);
    setRetryable(true);
    try {
      const result = await loadContext({
        retryTransientNetworkFailure: true,
      });
      const handoff = result?.handoff || result;
      const checkpoint = result?.checkpoint || contextCheckpoint || checkpointQuery.data;
      await writeClipboard(await copyReadySessionContextContent(handoff, {
        provider,
        sessionId,
        checkpointId: checkpoint?.id,
        boundarySequence: checkpoint?.boundary?.sequence_number,
      }));
      setCopyState("copied");
      return true;
    } catch (reason) {
      setCopyState("error");
      recordFailure(
        reason,
        `${title} Session Context could not be copied.`,
      );
      return false;
    }
  };

  const preparing = Boolean(
    contextEligible
    && (
      captureCheckpoint.isPending
      || checkpointHandoff.isPending
      || (
        workspaceId
        && provider
        && sessionId
        && !context
        && !error
      )
    )
  );
  const copyReady = contextEligible && (
    !context || context?.quality_report?.copy_ready === true
  );
  const columnClass = total === 1
    ? "xl:col-start-2"
    : total === 2
      ? (slot === 1 ? "xl:col-start-1" : "xl:col-start-3")
      : [
          "xl:col-start-1",
          "xl:col-start-2",
          "xl:col-start-3",
        ][slot - 1] || "xl:col-start-1";

  return (
    <>
      <article
        aria-labelledby={headingId}
        data-session-context-card
        data-session-context-slot={`selected-${slot}`}
        className={`relative isolate flex min-w-0 flex-col overflow-hidden rounded-2xl border border-[#d8d8cf] bg-[#fbfbf6] p-5 text-[#171713] shadow-[0_18px_40px_rgba(23,23,19,0.07)] dark:border-[#292925] dark:bg-[#141411] dark:text-white ${columnClass} xl:row-start-1`}
      >
        <button
          type="button"
          aria-label={`Remove ${title} from Execute`}
          title={`Remove ${title} from Execute`}
          onClick={() => onRemove?.(session)}
          className="absolute right-3 top-3 z-30 inline-flex h-8 w-8 items-center justify-center rounded-lg border border-[#d8d8cf] bg-[#fbfbf6]/90 text-[#77776e] shadow-sm backdrop-blur-sm transition hover:border-red-300 hover:bg-red-50 hover:text-red-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-red-400/60 dark:border-[#383832] dark:bg-[#141411]/90 dark:text-[#aaa9a0] dark:hover:border-red-800 dark:hover:bg-red-950/40 dark:hover:text-red-300"
        >
          <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
        </button>

        {!contextEligible ? (
          <span
            title={`${compactionCount} of ${MINIMUM_SESSION_CONTEXT_COMPACTIONS} provider compactions detected`}
            className="absolute right-12 top-3 z-30 inline-flex min-h-8 items-center gap-1.5 rounded-lg bg-[#d9ff68] px-2.5 py-1 text-[10px] font-black uppercase tracking-[0.08em] text-[#171713] shadow-[0_5px_16px_rgba(217,255,104,0.22)]"
          >
            <LockKeyhole className="h-3 w-3" aria-hidden="true" />
            {compactionProgress}
          </span>
        ) : null}

        <span
          aria-hidden="true"
          data-session-provider-background={provider}
          className="pointer-events-none absolute -right-[20%] top-[16%] z-10 h-[76%] w-[92%] opacity-[0.055] dark:opacity-[0.09]"
        >
          <HarnessArtwork type={provider} color="#a2a298" />
        </span>

        <header className={`relative z-20 pr-9 ${contextEligible ? "" : "pt-10"}`}>
          <p className="text-[9px] font-black uppercase tracking-[0.14em] text-[#77776e] dark:text-[#aaa9a0]">
            Selected Session Context
          </p>
          <h2 id={headingId} className="mt-1 line-clamp-2 text-xl font-black leading-tight tracking-[-0.04em]">
            {title}
          </h2>
          <p className="mt-2 line-clamp-1 text-[10px] font-semibold text-[#77776e] dark:text-[#aaa9a0]">
            {sessionProviderLabel(provider)}
            {session?.topic ? ` · ${session.topic}` : ""}
          </p>
        </header>

        <PromptPreview
          label={`${title} Session Context prompt preview`}
          content={sessionContextCardPreviewContent(context?.content)}
          loading={preparing}
          available={Boolean(context)}
          error={error}
          unavailableMessage={compactionRequirement
            || "Open the preview to prepare this selected session’s exact context."}
          compact
          allowAncestorWatermark
          identityLabel={`${sessionProviderLabel(provider)} · ${title}`}
          copyReady={context?.quality_report?.copy_ready}
          className="mt-5 min-h-[210px]"
        />

        <div className="relative z-20 mt-auto grid gap-3 pt-4 sm:grid-cols-2">
          <button
            type="button"
            aria-label={`Preview ${contextName}`}
            onClick={(event) => previewContext(event.currentTarget)}
            disabled={!contextEligible}
            className="btn-secondary min-h-11 px-4 text-xs"
          >
            {preparing
              ? <RefreshCw className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
              : <BookOpenCheck className="h-3.5 w-3.5" aria-hidden="true" />}
            {!contextEligible
              ? "Locked"
              : preparing
              ? "Preparing…"
              : context
              ? "Open full preview"
              : error
                ? retryable ? "Retry preview" : "Unavailable"
                : "Prepare preview"}
          </button>
          <ContextCopyButton
            contextName={contextName}
            copyState={copyState}
            onClick={copyContext}
            disabled={
              !contextEligible
              || preparing
              || !copyReady
              || (!context && error && !retryable)
            }
          />
        </div>

        {error ? (
          <p className="relative z-20 mt-3 text-xs leading-5 text-attention">
            {error}
          </p>
        ) : context && !copyReady ? (
          <p className="relative z-20 mt-3 text-xs leading-5 text-attention">
            {sessionContextQualityMessage(context, contextName)}
          </p>
        ) : null}
      </article>

      {previewOpen ? createPortal(
        <SessionContextPreviewDialog
          result={context}
          loading={preparing}
          error={error}
          canRetry={retryable}
          copyState={copyState}
          onCopy={copyContext}
          onRetry={retryContext}
          onClose={closePreview}
          returnFocusRef={previewReturnFocusRef}
          contextName={contextName}
          previewTitle={`${title} Session Context Preview`}
          eyebrow={`Selected task child · ${sessionProviderLabel(provider)}`}
        />,
        document.body,
      ) : null}
    </>
  );
}


function sessionContextCardPreviewContent(content) {
  const fullContent = rawText(content);
  if (!fullContent) return "";

  const goalMatch = /(^|\n)## (?:Goal|Current main goal)(?=\r?\n|$)/m.exec(fullContent);
  const goalOffset = goalMatch
    ? goalMatch.index + (goalMatch[1] ? goalMatch[1].length : 0)
    : -1;
  if (goalOffset <= 0) return fullContent;

  return [
    "# Session Context — task-level working memory",
    "",
    fullContent.slice(goalOffset),
  ].join("\n");
}


function PromptPreview({
  label,
  content,
  loading,
  available,
  error,
  unavailableMessage,
  compact = false,
  allowAncestorWatermark = false,
  identityLabel = "",
  copyReady,
  className = "",
}) {
  const blocked = Boolean(content && copyReady === false);
  return (
    <section
      aria-label={label}
      aria-busy={loading || undefined}
      className={`relative flex flex-1 flex-col overflow-hidden rounded-2xl border border-[#2b2b26] bg-[#171713] text-[#f4f4ec] shadow-[inset_0_1px_0_rgba(255,255,255,0.04)] ${
        allowAncestorWatermark ? "" : "isolate"
      } ${className}`}
    >
      <header className="relative z-20 flex items-center justify-between gap-3 border-b border-white/10 px-4 py-3">
        <div className="flex items-center gap-2">
          <FileCode2 className="h-3.5 w-3.5 text-[#d9ff68]" aria-hidden="true" />
          <span className="font-mono text-xs font-semibold uppercase tracking-[0.12em] text-white/70">
            Prompt preview
          </span>
        </div>
        <span className={`inline-flex items-center gap-1.5 text-xs font-semibold ${
          blocked ? "text-amber-300" : "text-white/60"
        }`}>
          <span className={`h-1.5 w-1.5 rounded-full ${
            blocked
              ? "bg-amber-400"
              : content
                ? "bg-[#d9ff68]"
                : loading
                  ? "animate-pulse bg-white/60"
                  : "bg-white/25"
          }`} />
          {blocked
            ? "Not copy-ready"
            : content
              ? "Prepared"
              : loading
                ? "Preparing"
                : "Unavailable"}
        </span>
      </header>
      {identityLabel ? (
        <div className="relative z-20 border-b border-white/10 bg-white/[0.025] px-4 py-2 font-mono text-[10px] font-semibold uppercase tracking-[0.1em] text-white/50 sm:px-5">
          {identityLabel}
        </div>
      ) : null}
      {content ? (
        <pre
          tabIndex={0}
          aria-label={`${label} content`}
          className={`relative z-20 flex-1 overflow-auto whitespace-pre-wrap break-words p-4 font-mono text-xs leading-5 text-white/80 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-[-3px] focus-visible:outline-[#d9ff68] sm:p-5 ${
            compact ? "max-h-[320px]" : "max-h-[620px]"
          }`}
        >
          {content}
        </pre>
      ) : (
        <div className="relative z-20 flex flex-1 items-center justify-center p-6 text-center">
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
  const artifactLabel = contextName === "Workspace Context" ? "workspace" : "session";
  const visibleLabel = copyState === "copying"
    ? "Copying…"
    : copyState === "copied"
      ? "Copied"
      : copyState === "error"
        ? "Try copy again"
        : `Copy ${artifactLabel}`;

  return (
    <button
      type="button"
      aria-label={copyActionLabel(copyState, contextName)}
      onClick={onClick}
      disabled={disabled || copyState === "copying"}
      className="btn-primary min-h-11 px-4 text-xs"
    >
      <Clipboard className="h-3.5 w-3.5" aria-hidden="true" />
      {visibleLabel}
      <span className="sr-only" aria-live="polite">
        {copyState === "copied"
          ? `${contextName} copied`
          : copyState === "error"
            ? `${contextName} could not be copied`
            : ""}
      </span>
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
  const workspaceContext = result?.workspace_context || {};
  const workspaceContent = workspaceContext.content || "";
  const workspaceCopyReady = workspaceContext.quality_report?.copy_ready === true;
  const workspaceTokens = Number.isFinite(workspaceContext.estimated_tokens)
    ? workspaceContext.estimated_tokens
    : workspaceContent
      ? approximateTokens(workspaceContent)
      : null;
  const repository = manifest.repo_state || {};

  const copyContext = async () => {
    if (!workspaceContent || typeof onCopy !== "function") return;
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
            <p className="text-[10px] font-semibold uppercase tracking-[0.13em] text-ink-subtle">Workspace foundation · cross-harness</p>
            <h2 id="context-preview-title" className="mt-1 text-xl font-semibold tracking-[-0.03em] text-ink">
              Workspace Context Preview
            </h2>
            <p className="mt-1 text-xs leading-5 text-ink-muted">
              The task- and session-independent workspace snapshot, compiled automatically from the current repository and durable workspace evidence.
            </p>
          </div>
          <button
            ref={closeRef}
            type="button"
            onClick={onClose}
            aria-label="Close Workspace Context Preview"
            className="icon-button shrink-0"
          >
            <X className="h-4 w-4" aria-hidden="true" />
          </button>
        </header>

        {loading ? (
          <ProductLoadingState
            compact
            label="Compiling Workspace Context…"
            detail="Reading the selected workspace, current repository, and durable workspace evidence."
            stages={["Resolving the workspace", "Indexing repository state", "Rendering Workspace Context"]}
            className="m-5 sm:m-6"
          />
        ) : error ? (
          <div role="alert" className="px-6 py-14 text-center">
            <AlertTriangle className="mx-auto h-7 w-7 text-attention" aria-hidden="true" />
            <h3 className="mt-4 text-base font-semibold text-ink">Workspace Context could not be generated</h3>
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
              <PreviewMetric label="Scope" value="Whole workspace" />
              <PreviewMetric
                label="Estimated size"
                value={Number.isFinite(workspaceTokens) ? `≈${workspaceTokens.toLocaleString()} tokens` : "Not reported"}
              />
              <PreviewMetric
                label="Repository"
                value={repository.repo_path ? "Indexed" : "Workspace evidence only"}
              />
              <PreviewMetric label="Format" value={workspaceContext.schema_version || "Unknown"} />
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto p-5 sm:p-6">
              {!workspaceCopyReady ? (
                <div role="alert" className="mb-5 rounded-xl border border-attention/35 bg-attention/10 p-4 text-xs leading-5 text-ink">
                  This foundation is incomplete. Review the blocking gaps below and recompile after adding the missing evidence; copying is disabled.
                </div>
              ) : null}
              <div>
                <div className="flex items-center justify-between gap-3">
                  <p className="text-xs font-semibold text-ink">Workspace Context</p>
                  <button
                    type="button"
                    onClick={copyContext}
                    disabled={!workspaceContent || !workspaceCopyReady || copyState === "copying"}
                    className="inline-flex min-h-9 items-center gap-2 rounded-lg px-3 text-[10px] font-semibold text-ink-muted hover:bg-surface-muted hover:text-ink"
                  >
                    <Clipboard className="h-3.5 w-3.5" aria-hidden="true" />
                    {copied
                      ? "Copied"
                      : copyState === "copying"
                        ? "Refreshing…"
                        : "Copy Workspace Context"}
                  </button>
                </div>
                <pre
                  tabIndex={0}
                  aria-label="Workspace Context prompt content"
                  className="mt-3 max-h-[48vh] overflow-auto whitespace-pre-wrap rounded-xl border border-line bg-[#171713] p-4 font-mono text-[11px] leading-5 text-[#f4f4ec]"
                >
                  {workspaceContent}
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
  contextName = "Session Context",
  previewTitle = "Session Context Preview",
  eyebrow = "Task child · same harness",
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
            <p className="text-[10px] font-semibold uppercase tracking-[0.13em] text-ink-subtle">{eyebrow}</p>
            <h2 id="session-context-preview-title" className="mt-1 text-xl font-semibold tracking-[-0.03em] text-ink">
              {previewTitle}
            </h2>
            <p className="mt-1 text-xs leading-5 text-ink-muted">
              The latest individual session's child working memory. Its Workspace Context parent is a separate artifact; failed attempts and transient blockers stay here.
            </p>
          </div>
          <button
            ref={closeRef}
            type="button"
            onClick={onClose}
            aria-label={`Close ${previewTitle}`}
            className="icon-button shrink-0"
          >
            <X className="h-4 w-4" aria-hidden="true" />
          </button>
        </header>

        {loading ? (
          <ProductLoadingState
            compact
            label={`Preparing ${contextName}…`}
            detail="Capturing the latest task child while preserving its separate Workspace Context boundary."
            stages={["Capturing the session tip", "Restoring structured progress", "Rendering Session Context"]}
            className="m-5 sm:m-6"
          />
        ) : error ? (
          <div role="alert" className="px-6 py-14 text-center">
            <AlertTriangle className="mx-auto h-7 w-7 text-attention" aria-hidden="true" />
            <h3 className="mt-4 text-base font-semibold text-ink">{contextName} could not be prepared</h3>
            <p className="mx-auto mt-2 max-w-lg text-sm leading-6 text-ink-muted">{error}</p>
            {canRetry ? (
              <button type="button" onClick={onRetry} className="btn-secondary mt-5 min-h-11 text-xs">
                <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
                Refresh selected session tip
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
                {sessionContextQualityMessage(result, contextName)}
              </div>
            ) : null}
            <div className="min-h-0 flex-1 overflow-y-auto p-5 sm:p-6">
              <div className="flex items-center justify-between gap-3">
                <p className="text-xs font-semibold text-ink">{contextName}</p>
                <button
                  type="button"
                  onClick={onCopy}
                  disabled={!copyReady || copyState === "copying"}
                  className="inline-flex min-h-9 items-center gap-2 rounded-lg px-3 text-[10px] font-semibold text-ink-muted hover:bg-surface-muted hover:text-ink"
                >
                  <Clipboard className="h-3.5 w-3.5" aria-hidden="true" />
                  {copyActionLabel(copyState, contextName)}
                </button>
              </div>
              <pre
                tabIndex={0}
                aria-label={`${contextName} prompt content`}
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
      href: "/app/library",
    });
  }
  if (activityOutcomeNeedsAttention(activity)) {
    projectionAttention.push({
      id: `activity-outcome:${activity?.id || "latest"}`,
      label: humanizeStatus(activity?.state || activity?.outcome?.status || "Run"),
      title: "Latest run did not complete successfully",
      summary: visibleText(activity?.outcome?.summary || activity?.latest_update),
      href: "/app/library",
    });
  }
  if (activityVerificationFailed) {
    projectionAttention.push({
      id: `activity-verification:${activity?.id || "latest"}`,
      label: "Verification",
      title: "Latest observed verification failed",
      summary: activityVerification,
      href: "/app/library",
    });
  }
  if (checkpointUnavailableForBrief) {
    projectionAttention.push({
      id: `checkpoint-not-current:${checkpoint?.id || "unknown"}`,
      label: "Checkpoint",
      title: "Saved checkpoint is not current and complete",
      summary: checkpointSafetySummary(checkpoint),
      href: "/app/library",
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
      href: "/app/library",
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
      href: "/app/library",
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
    currentStateSource: latestUpdate ? "/app/library" : SECTION_LINKS.work,
    lastCompleted,
    lastCompletedSource: outcomeSummary ? "/app/library" : SECTION_LINKS.completed,
    nextAction,
    nextActionSource: checkpointNextAction ? "/app/library" : SECTION_LINKS.work,
    blockers,
    verification,
    verificationSource: activityVerification || checkpointVerification.length ? "/app/library" : SECTION_LINKS.deliveries,
    files,
    filesSource: activity?.changed_files?.length || checkpointSections.relevant_files?.length
      ? "/app/library"
      : SECTION_LINKS.deliveries,
    decisions,
    failedAttempts,
    failedAttemptsSource: checkpointSections.failed_attempts?.length ? "/app/library" : SECTION_LINKS.learnings,
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
  if (["claude code", "claude_code", "claude-code"].includes(normalized)) return "claude";
  if (["open code", "open_code", "open-code"].includes(normalized)) return "opencode";
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


function sessionProviderLabel(value) {
  const provider = normalizeProvider(value);
  if (provider === "codex") return "Codex";
  if (provider === "claude") return "Claude";
  if (provider === "opencode") return "OpenCode";
  return humanizeStatus(provider);
}


function workspaceContextErrorIsRetryable(error) {
  if (!error) return true;
  const message = String(error).toLowerCase();
  return ![
    "compiled context belongs to a different workspace",
    "compiled context belongs to a different repository",
  ].some((terminalMessage) => message.includes(terminalMessage));
}


async function workspaceContextContent(result) {
  const workspaceContext = result?.workspace_context;
  const foundation = workspaceContext?.foundation;
  if (
    workspaceContext?.schema_version !== "workspace_context.v1"
    || typeof workspaceContext.content !== "string"
    || !workspaceContext.content.trim()
    || typeof workspaceContext.sha256 !== "string"
    || !workspaceContext.sha256.trim()
  ) {
    throw new Error("The compiler returned an incomplete Workspace Context.");
  }
  if (foundation?.quality_report?.copy_ready !== true) {
    const detail = Array.isArray(foundation?.quality_report?.issues)
      ? foundation.quality_report.issues
        .filter((issue) => issue?.blocking === true)
        .map((issue) => visibleText(issue?.message))
        .filter(Boolean)
        .slice(0, 2)
        .join(" ")
      : "";
    throw new Error(
      detail
        ? `Workspace Context is not copy-ready. ${detail}`
        : "Workspace Context is not copy-ready because its foundation quality gate did not pass.",
    );
  }
  await requireMatchingContentSha256(
    canonicalWorkspaceFoundationSemanticJson(foundation),
    foundation.semantic_sha256,
    "Workspace foundation semantic state",
  );
  await requireMatchingContentSha256(
    canonicalWorkspaceFoundationJson(foundation),
    foundation.artifact_sha256,
    "Workspace foundation",
  );
  await requireMatchingContentSha256(
    workspaceContext.content,
    workspaceContext.sha256,
    "Workspace Context",
  );
  return workspaceContext.content;
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
    throw new Error("The checkpoint service returned an incomplete Session Context.");
  }
  if (
    expected.provider
    && normalizeProvider(result.provider) !== normalizeProvider(expected.provider)
  ) {
    throw new Error("The Session Context belongs to a different harness.");
  }
  if (
    expected.sessionId
    && rawText(result.session_id) !== rawText(expected.sessionId)
  ) {
    throw new Error("The Session Context belongs to a different session.");
  }
  if (
    expected.checkpointId
    && rawText(result.checkpoint_id) !== rawText(expected.checkpointId)
  ) {
    throw new Error("The Session Context belongs to a different checkpoint.");
  }
  if (
    Number.isInteger(expected.boundarySequence)
    && result.boundary?.sequence_number !== expected.boundarySequence
  ) {
    throw new Error("The Session Context belongs to a different session boundary.");
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
    "This session no longer retains its original user request, so a trustworthy Session Context cannot be produced. Choose another session or checkpoint in Library.",
  );
  error.code = "session_goal_unavailable";
  error.retryable = false;
  return error;
}


function sessionContextFailure(error, fallback) {
  if (sessionContextCompactionsAreRequired(error)) {
    return {
      message: error?.message || `${MINIMUM_SESSION_CONTEXT_COMPACTIONS} compactions required.`,
      retryable: false,
    };
  }
  if (sessionGoalIsUnavailable(error)) {
    return {
      message: unavailableSessionGoalError().message,
      retryable: false,
    };
  }
  if (isTransientNetworkFailure(error)) {
    return {
      message: "Could not reach DaemonState to verify the selected session. Keep the local service running, then try copy again.",
      retryable: true,
    };
  }
  return {
    message: error?.message || fallback,
    retryable: error?.retryable !== false,
  };
}


function sessionContextCompactionsAreRequired(error) {
  return rawText(
    error?.code
    || error?.detail?.code
    || error?.detail?.detail?.code,
  ).toLowerCase() === "session_context_compactions_required";
}


function sessionContextCompactionsRequiredError(compactionCount) {
  const error = new Error(
    `${MINIMUM_SESSION_CONTEXT_COMPACTIONS} compactions required (${Math.min(
      Math.max(Number(compactionCount) || 0, 0),
      MINIMUM_SESSION_CONTEXT_COMPACTIONS,
    )}/${MINIMUM_SESSION_CONTEXT_COMPACTIONS}).`,
  );
  error.code = "session_context_compactions_required";
  error.retryable = false;
  return error;
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
    || checkpoint.schema_version !== CURRENT_CHECKPOINT_SCHEMA
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


function validateWorkspaceContext(result, expectedIdentity = {}) {
  const manifest = result?.manifest;
  const foundation = manifest?.workspace_foundation;
  const repositoryFingerprint = rawText(
    manifest?.repo_state?.state_fingerprint
      || manifest?.repo_state?.snapshot_fingerprint,
  );
  if (
    !result
    || result.schema_version !== "context_pack.v2"
    || !result.context_pack_id
    || typeof result.markdown !== "string"
    || !result.markdown.trim()
    || !(
      result.markdown === "# Workspace Context"
      || result.markdown.startsWith("# Workspace Context\n")
    )
    || !Array.isArray(result.selected_context)
    || !Array.isArray(result.excluded_context)
    || manifest?.schema_version !== "context_pack.v2"
    || manifest.context_pack_id !== result.context_pack_id
    || manifest.objective_kind !== "project_snapshot"
    || manifest.focus?.kind !== "project_snapshot"
    || !manifest.repo_state
    || typeof manifest.repo_state !== "object"
    || Array.isArray(manifest.repo_state)
    || manifest.token_accounting?.within_budget !== true
    || manifest.rendering?.within_budget !== true
    || typeof manifest.rendering?.markdown_sha256 !== "string"
    || !manifest.rendering.markdown_sha256.trim()
    || !Array.isArray(manifest.selected_context)
    || !Array.isArray(manifest.excluded_context)
    || !SUPPORTED_WORKSPACE_FOUNDATION_SCHEMAS.has(foundation?.schema_version)
    || foundation.objective_independent !== true
    || typeof foundation.semantic_sha256 !== "string"
    || !foundation.semantic_sha256.trim()
    || typeof foundation.artifact_sha256 !== "string"
    || !foundation.artifact_sha256.trim()
    || typeof foundation.quality_report !== "object"
    || foundation.quality_report === null
    || typeof foundation.quality_report.copy_ready !== "boolean"
    || !repositoryFingerprint
    || rawText(foundation.repository_state?.snapshot_fingerprint) !== repositoryFingerprint
    || rawText(manifest.repo_state.workspace_foundation_sha256)
      !== rawText(foundation.semantic_sha256)
    || rawText(manifest.repo_state.workspace_foundation_artifact_sha256)
      !== rawText(foundation.artifact_sha256)
    || JSON.stringify(result.selected_context) !== JSON.stringify(manifest.selected_context)
    || JSON.stringify(result.excluded_context) !== JSON.stringify(manifest.excluded_context)
  ) {
    throw new Error("The compiler returned an incomplete Workspace Context.");
  }
  if (
    expectedIdentity.workspaceId
    && rawText(manifest.workspace_id) !== rawText(expectedIdentity.workspaceId)
  ) {
    throw new Error("The compiled context belongs to a different workspace.");
  }
  if (
    expectedIdentity.repoPath
    && normalizeComparableRepoPath(manifest.repo_state.repo_path)
      !== normalizeComparableRepoPath(expectedIdentity.repoPath)
  ) {
    throw new Error("The compiled context belongs to a different repository.");
  }
  return {
    ...result,
    workspace_context: {
      schema_version: "workspace_context.v1",
      workspace_id: rawText(manifest.workspace_id),
      context_pack_id: result.context_pack_id,
      content: result.markdown,
      sha256: manifest.rendering.markdown_sha256,
      estimated_tokens: Number(manifest.rendering.estimated_tokens),
      repository: manifest.repo_state,
      quality_report: foundation.quality_report,
      foundation,
    },
  };
}


function canonicalWorkspaceFoundationJson(foundation) {
  if (!foundation || typeof foundation !== "object" || Array.isArray(foundation)) {
    throw new Error("The compiler returned an incomplete Workspace foundation.");
  }
  const payload = { ...foundation };
  delete payload.artifact_sha256;
  return JSON.stringify(sortCanonicalJsonValue(payload));
}


function canonicalWorkspaceFoundationSemanticJson(foundation) {
  if (!foundation || typeof foundation !== "object" || Array.isArray(foundation)) {
    throw new Error("The compiler returned an incomplete Workspace foundation.");
  }
  const payload = {
    ...foundation,
    repository_state: { ...(foundation.repository_state || {}) },
  };
  delete payload.artifact_sha256;
  delete payload.semantic_sha256;
  delete payload.compiled_at;
  delete payload.repository_state.captured_at;
  return JSON.stringify(sortCanonicalJsonValue(payload));
}


function sortCanonicalJsonValue(value) {
  if (Array.isArray(value)) {
    return value.map((item) => sortCanonicalJsonValue(item));
  }
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.keys(value)
        .sort()
        .map((key) => [key, sortCanonicalJsonValue(value[key])]),
    );
  }
  return value;
}


function normalizeComparableRepoPath(value) {
  const path = rawText(value);
  if (!path) return "";
  const withoutTrailingSlash = path.replace(/\/+$/, "");
  return withoutTrailingSlash || "/";
}
