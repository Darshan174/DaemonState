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
  PlayCircle,
  RefreshCw,
  ShieldAlert,
  ShieldCheck,
} from "lucide-react";

import WorkspaceTopicGate from "../components/WorkspaceTopicGate";
import ResumeCheckpointDialog from "../components/ResumeCheckpointDialog";
import ProductLoadingState from "../components/ProductLoadingState";
import {
  useCaptureCheckpoint,
  useCheckpoints,
  useLatestCheckpoint,
  useResumeCheckpoint,
  useSessionLibrary,
  useVerifyCheckpoint,
} from "../api/hooks";
import {
  useContextDigest,
  useLinkedAISessionRefresh,
  usePrepareContext,
} from "../context-map/api";
import { cleanDisplayText, formatTimeAgo, sessionIdentity } from "../context-map/digest";
import { useProductWorkspace } from "./useProductWorkspace";

export default function NowPage() {
  const workspace = useProductWorkspace();
  const digestQuery = useContextDigest(workspace.activeWorkspaceId, { poll: true });
  const checkpointQuery = useLatestCheckpoint(workspace.activeWorkspaceId);
  const checkpointHistoryQuery = useCheckpoints(workspace.activeWorkspaceId, 100);
  const libraryQuery = useSessionLibrary(workspace.activeWorkspaceId);
  const captureCheckpoint = useCaptureCheckpoint();
  const prepareContext = usePrepareContext();
  const [prepareState, setPrepareState] = useState("idle");
  const [prepareError, setPrepareError] = useState("");
  useLinkedAISessionRefresh(workspace.activeWorkspaceId);

  if (!workspace.workspacesQuery.isLoading && !workspace.activeWorkspaceId) {
    return (
      <WorkspaceTopicGate
        workspaces={workspace.workspaces}
        selectedId={workspace.selectedId}
        onSelect={workspace.setSelectedId}
      />
    );
  }
  if (workspace.workspacesQuery.isLoading || digestQuery.isLoading) {
    return (
      <ProductLoadingState
        label="Loading observed project activity…"
        detail="Current work remains separate from immutable checkpoint history."
        stages={["Selecting the workspace", "Reading observed activity", "Resolving the latest checkpoint"]}
      />
    );
  }
  if (digestQuery.isError) {
    return <PageState title="Could not load project activity" detail={digestQuery.error?.message} error />;
  }

  const digest = digestQuery.data || {};
  const cards = digest.cards || [];
  const checkpoint = checkpointQuery.data || null;
  // Now is current observed activity. A checkpoint is a separate immutable
  // recovery boundary and must never replace newer session state.
  const observedActivity = digest.activity?.primary || fallbackActivity(digest);
  const checkpointIsCurrent = !["superseded", "historical"].includes(
    checkpoint?.currentness?.state,
  );
  const activity = observedActivity || (checkpointIsCurrent ? checkpoint?.activity : null);
  const currentGoal = prepareTaskCandidate(digest.current_goal?.title);
  const activeTaskTitle = currentGoal
    || prepareTaskCandidate(observedActivity?.request || observedActivity?.title)
    || prepareTaskCandidate(activity?.request || activity?.title)
    || prepareTaskCandidate(cleanRecoveryText(checkpoint?.sections?.goal?.[0]?.statement))
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
  const activitySession = (
    activity?.session_id
    && activity?.state !== "unassigned"
    && (activity?.provider || activity?.tool)
  ) ? {
      connector_type: activity.provider || activity.tool,
      session_id: activity.session_id,
    } : null;
  const latestSession = activitySession || libraryQuery.data?.sessions?.[0] || null;
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
  const prepareAction = latestSession && currentGoal
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
            description: "Review the saved continuation before opening the earlier session state.",
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
              {activity ? "Activity in view" : "Waiting for activity"}
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
                {prepareAction.kind === "compile" ? (
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

        <TaskStatusRibbon activity={activity} checkpoint={checkpoint} />
      </header>

      {unassignedSessionCount > 0 ? <UnassignedSessions count={unassignedSessionCount} cardId={unassignedSessionCard?.id} /> : null}

      <section className="grid items-stretch gap-4 lg:grid-cols-3" aria-label="Active task overview">
        <ObservedWork activity={activity} activeTaskTitle={activeTaskTitle} />
        <ObservedResult activity={activity} checkpoint={checkpoint} attentionCount={attentionCards.length} />
        <ContinuationSummary checkpoint={checkpoint} latestSession={latestSession} />
      </section>

      <CheckpointPanel
        checkpoint={checkpoint}
        sessionCompactions={sessionCompactions}
        isLoading={checkpointQuery.isLoading}
        error={checkpointQuery.error || captureCheckpoint.error}
        latestSession={latestSession}
        workspaceId={workspace.activeWorkspaceId}
        onCapture={saveCheckpoint}
        capturePending={captureCheckpoint.isPending}
      />

      <AttentionPanel cards={attentionCards} />

      {recentSessionCards.length ? <RecentSessions cards={recentSessionCards} /> : null}

    </div>
  );
}

function CheckpointPanel({ checkpoint, sessionCompactions, isLoading, error, latestSession, workspaceId, onCapture, capturePending }) {
  const verifyCheckpoint = useVerifyCheckpoint();
  const resumeCheckpoint = useResumeCheckpoint();
  const [copyState, setCopyState] = useState("idle");
  const [resumeNotice, setResumeNotice] = useState("");
  const [confirmResume, setConfirmResume] = useState(false);

  const verify = () => {
    if (checkpoint) {
      verifyCheckpoint.mutate({ workspaceId, checkpointId: checkpoint.id, executeCommands: true });
    }
  };
  const resume = async () => {
    if (!checkpoint) return;
    setConfirmResume(false);
    setCopyState("idle");
    setResumeNotice("");
    try {
      const bundle = await resumeCheckpoint.mutateAsync({ workspaceId, checkpointId: checkpoint.id, launchSession: true });
      await navigator.clipboard.writeText(bundle.content);
      if (bundle.launch?.launched === false) {
        setCopyState("copied_only");
        setResumeNotice(bundle.launch.message || "The resume bundle was copied, but the desktop session could not be opened.");
      } else {
        setCopyState("copied");
      }
    } catch {
      setCopyState("error");
    }
  };

  if (isLoading) {
    return <section id="continuity-checkpoint" className="app-surface scroll-mt-24 p-5 text-sm text-[#68685f] dark:text-[#aaa9a0]">Loading structured checkpoint…</section>;
  }
  if (!checkpoint) {
    return (
      <section id="continuity-checkpoint" className="app-surface scroll-mt-24 p-5 sm:p-6">
        <PanelLabel icon={ShieldCheck}>Continuity checkpoint</PanelLabel>
        <h2 className="mt-5 text-xl font-semibold">No structured checkpoint captured yet.</h2>
        <p className="mt-2 max-w-2xl text-sm leading-6 text-[#68685f] dark:text-[#aaa9a0]">
          Recovery points are created automatically before long sessions are condensed. Save one now to preserve the latest goal, progress, decisions, failures, files, blockers, checks, and exact next action.
        </p>
        {latestSession ? (
          <button type="button" onClick={onCapture} disabled={capturePending} className="btn-primary mt-5 h-10 text-xs disabled:opacity-60">
            {capturePending ? "Capturing…" : "Capture latest session"}
          </button>
        ) : <Link to="/app/library" className="mt-5 inline-flex text-xs font-bold underline">Import an agent session</Link>}
        {error ? <p role="alert" className="mt-3 text-xs font-semibold text-red-600">{error.message}</p> : null}
      </section>
    );
  }

  const sections = checkpoint.sections || {};
  const goal = cleanRecoveryText(sections.goal?.[0]?.statement || "Goal was not captured.");
  const nextAction = sections.exact_next_action?.[0]?.statement || "Exact next action is missing.";
  const currentness = checkpoint.currentness || {};
  const boundary = checkpoint.boundary || {};
  const recoveryTitle = checkpoint.trigger === "compaction"
    ? "Saved before the session was condensed"
    : "Saved from the latest session state";
  const recoveryDescription = checkpoint.trigger === "compaction"
    ? "This recovery point preserves what the agent knew and planned at that moment. Later activity stays separate, so you always know exactly what will be resumed."
    : "This recovery point preserves the goal, decisions, evidence, and next action available when it was saved.";
  const outdated = currentness.state === "superseded" || currentness.state === "historical";
  const eventsBehind = checkpointEventsBehind(checkpoint);
  const evidenceCount = checkpoint.payload?.sections
    ? Object.values(checkpoint.payload.sections)
      .flat()
      .reduce((count, item) => count + (item.evidence_event_ids?.length || 0), 0)
    : 0;
  return (
    <>
    <section id="continuity-checkpoint" className="ce-recovery-editorial relative scroll-mt-24 overflow-hidden border-y border-[#171713] bg-white dark:border-white dark:bg-black">
      <div className="grid border-b border-[#171713] dark:border-white lg:grid-cols-[minmax(0,1.55fr)_minmax(19rem,.65fr)]">
        <header className="relative overflow-hidden px-5 py-8 sm:px-8 sm:py-10 lg:min-h-[15rem] lg:px-10 lg:py-10">
          <div className="pointer-events-none absolute -right-8 -top-16 select-none text-[14rem] font-semibold leading-none tracking-[-0.1em] text-[#171713]/[0.025] dark:text-white/[0.035]" aria-hidden="true">
            04
          </div>
          <div className="relative flex items-center justify-between gap-4">
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-[#68685f] dark:text-[#aaa9a0]">04 / Recovery</p>
            <span className="text-xs font-semibold text-[#68685f] dark:text-[#aaa9a0]">{outdated ? "Earlier state" : "Latest state"}</span>
          </div>
          <h2 className="relative mt-10 max-w-[16ch] text-[clamp(2.4rem,3.8vw,3.5rem)] font-semibold leading-[0.96] tracking-[-0.055em] text-[#171713] dark:text-white sm:mt-12">
            {outdated ? "Previous recovery point" : "Recovery point"}
          </h2>
        </header>

        <aside className="flex flex-col justify-between border-t border-[#171713] px-5 py-7 dark:border-white sm:px-8 lg:border-l lg:border-t-0 lg:px-7 lg:py-8">
          <div>
            <p className="text-[10px] font-bold uppercase tracking-[0.19em] text-[#77776e] dark:text-[#929289]">What this means</p>
            <h3 className="mt-5 text-2xl font-semibold leading-[1.08] tracking-[-0.04em] text-[#171713] dark:text-white">{recoveryTitle}</h3>
            <p className="mt-4 text-sm leading-6 text-[#68685f] dark:text-[#aaa9a0]">{recoveryDescription}</p>
            <Link to="/app/memory" className="group mt-6 inline-flex items-center gap-2 border-b border-[#171713] pb-1 text-sm font-semibold text-[#171713] dark:border-white dark:text-white">
              View in Memory <ArrowRight className="h-3.5 w-3.5 transition-transform group-hover:translate-x-1" />
            </Link>
          </div>
          <div className="mt-10 grid grid-cols-2 gap-2 lg:grid-cols-1">
            <button type="button" onClick={verify} disabled={verifyCheckpoint.isPending} className="btn-secondary h-11 text-xs disabled:cursor-wait disabled:opacity-60">
              {verifyCheckpoint.isPending ? "Running checks…" : "Verify now"}
            </button>
            <button type="button" onClick={() => setConfirmResume(true)} disabled={resumeCheckpoint.isPending} className="btn-primary h-11 text-xs disabled:opacity-60">
              <Clipboard className="h-3.5 w-3.5" />{copyState === "copied" ? "Session opened" : copyState === "copied_only" ? "Resume copied" : "Resume session"}
            </button>
          </div>
        </aside>
      </div>

      <div className="grid border-b border-[#171713] dark:border-white lg:grid-cols-[minmax(0,1.55fr)_minmax(19rem,.65fr)]">
        <section className="px-5 py-9 sm:px-8 sm:py-10 lg:px-10 lg:py-11" aria-labelledby={`checkpoint-goal-${checkpoint.id}`}>
          <p className="text-lg font-semibold tracking-[-0.02em] text-[#4f4f48] dark:text-[#c7c7bd]">Goal</p>
          <h3 id={`checkpoint-goal-${checkpoint.id}`} className="mt-4 max-w-[32ch] text-[clamp(1.8rem,2.4vw,2.4rem)] font-semibold leading-[1.1] tracking-[-0.035em] text-[#171713] dark:text-white">
            {prepareTaskCandidate(goal) || "Goal was not captured"}
          </h3>

          <div className="mt-10 grid border-t border-[#171713] pt-5 dark:border-white sm:grid-cols-[3.5rem_1fr] sm:gap-5">
            <span className="hidden text-sm font-semibold text-[#85857c] sm:block" aria-hidden="true">01</span>
            <div>
              <p className="text-xs font-bold uppercase tracking-[0.16em] text-[#77776e] dark:text-[#929289]">Exact next action</p>
              <p className="mt-3 max-w-3xl text-lg font-semibold leading-7 tracking-[-0.015em] text-[#171713] dark:text-white sm:text-xl">
                {prepareTaskCandidate(nextAction) || "Exact next action was not captured"}
              </p>
            </div>
          </div>
        </section>

        <aside className="border-t border-[#171713] dark:border-white lg:border-l lg:border-t-0">
          <div className="px-5 py-7 sm:px-8 lg:px-7 lg:py-9">
            <p className="text-[10px] font-bold uppercase tracking-[0.19em] text-[#77776e] dark:text-[#929289]">Recovery position</p>
            <dl className="mt-5">
              <BoundaryDetail label="Session point" value={boundary.occurred_at ? formatBoundaryTime(boundary.occurred_at) : "Time unavailable"} />
              <BoundaryDetail label="Position" value={boundary.sequence_number ? `Event ${boundary.sequence_number}` : "Event unavailable"} />
              <BoundaryDetail label="Saved" value={boundary.captured_at ? formatBoundaryTime(boundary.captured_at) : "Time unavailable"} />
            </dl>
          </div>
          {outdated ? (
            <div className="border-t border-[#171713] bg-[#fff7dc] px-5 py-7 text-[#3f210f] dark:border-white dark:bg-[#21170b] dark:text-[#ffe8b4] sm:px-8 lg:px-7">
              <p className="text-base font-semibold leading-6">Not the latest state{eventsBehind ? ` — ${eventsBehind} events behind` : ""}</p>
              <p className="mt-2 text-xs leading-5 opacity-80">Keep this for recovery, or save the current session before resuming.</p>
              {latestSession ? (
                <button type="button" onClick={onCapture} disabled={capturePending} className="mt-5 inline-flex h-10 items-center justify-center border border-current px-4 text-xs font-bold transition hover:bg-white/60 disabled:cursor-wait disabled:opacity-60 dark:hover:bg-black/20">
                  {capturePending ? "Saving latest checkpoint…" : "Save latest checkpoint"}
                </button>
              ) : null}
            </div>
          ) : null}
        </aside>
      </div>

      {sessionCompactions?.length ? (
        <SessionCompactions checkpoints={sessionCompactions} displayedCheckpointId={checkpoint.id} />
      ) : null}
      <div className="relative grid grid-cols-2 border-b border-[#171713] dark:border-white sm:grid-cols-4 lg:grid-cols-7">
        <CheckpointMetric label="Progress" value={sections.progress?.length || 0} />
        <CheckpointMetric label="Decisions" value={sections.decisions?.length || 0} />
        <CheckpointMetric label="Failures" value={sections.failed_attempts?.length || 0} />
        <CheckpointMetric label="Files" value={sections.relevant_files?.length || 0} />
        <CheckpointMetric label="Blockers" value={sections.blockers?.length || 0} />
        <CheckpointMetric label="Checks" value={sections.verification?.length || 0} />
        <CheckpointMetric label="Evidence" value={evidenceCount} />
      </div>
      <div className="relative flex flex-col gap-3 px-5 py-6 sm:flex-row sm:items-center sm:justify-between sm:px-8 lg:px-10">
        <p className="max-w-xl text-xs leading-5 text-[#77776e] dark:text-[#929289]">Goals, decisions, files, and supporting evidence continue in project memory.</p>
        <Link to="/app/memory" className="group inline-flex shrink-0 items-center gap-2 text-sm font-semibold text-[#171713] dark:text-white">
          Open project memory <ArrowRight className="h-3.5 w-3.5 transition-transform group-hover:translate-x-1" />
        </Link>
      </div>
      {(verifyCheckpoint.error || resumeCheckpoint.error || copyState === "error") ? (
        <p role="alert" className="relative border-t border-red-300 px-5 py-3 text-xs font-semibold text-red-600 sm:px-8 lg:px-10">{verifyCheckpoint.error?.message || resumeCheckpoint.error?.message || "Clipboard access is unavailable."}</p>
      ) : null}
      {resumeNotice ? <p role="status" className="relative border-t border-amber-300 px-5 py-3 text-xs font-semibold text-amber-700 dark:text-amber-300 sm:px-8 lg:px-10">{resumeNotice}</p> : null}
    </section>
    {confirmResume ? (
      <ResumeCheckpointDialog
        checkpoint={checkpoint}
        isPending={resumeCheckpoint.isPending}
        onCancel={() => setConfirmResume(false)}
        onConfirm={resume}
      />
    ) : null}
    </>
  );
}

function SessionCompactions({ checkpoints, displayedCheckpointId }) {
  return (
    <section className="relative border-b border-[#171713] dark:border-white">
      <div className="flex flex-wrap items-start justify-between gap-3 px-5 py-6 sm:px-8 lg:px-10">
        <div>
          <p className="text-xs font-bold uppercase tracking-[0.16em] text-[#77776e]">Saved recovery points · {checkpoints.length}</p>
          <p className="mt-2 text-xs leading-5 text-[#68685f] dark:text-[#aaa9a0]">Each entry preserves an earlier handoff state. Newer work remains separate.</p>
        </div>
        <Link to="/app/runs" className="text-xs font-bold underline underline-offset-4">View history</Link>
      </div>
      <div className="grid border-t border-[#171713] dark:border-white md:grid-cols-2">
        {checkpoints.map((item, index) => {
          const itemBoundary = item.boundary || {};
          const itemGoal = prepareTaskCandidate(cleanRecoveryText(item.sections?.goal?.[0]?.statement))
            || "Goal was not captured";
          const displayed = item.id === displayedCheckpointId;
          return (
            <div key={item.id} className={`border-b border-[#171713] px-5 py-5 dark:border-white md:odd:border-r ${displayed ? "bg-[#171713] text-white dark:bg-white dark:text-black" : "bg-white dark:bg-black"}`}>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-[10px] font-bold uppercase tracking-[0.14em]">Recovery point {String(index + 1).padStart(2, "0")}{displayed ? " · shown" : ""}</p>
                <span className={`text-[10px] font-semibold ${displayed ? "opacity-70" : "text-[#85857c]"}`}>
                  {itemBoundary.occurred_at ? formatBoundaryTime(itemBoundary.occurred_at) : "Time unavailable"}
                </span>
              </div>
              <p className="mt-3 line-clamp-2 text-sm font-semibold leading-5">{itemGoal}</p>
            </div>
          );
        })}
      </div>
    </section>
  );
}

function CheckpointMetric({ label, value }) {
  return <div className="border-r border-t border-[#171713] px-4 py-5 text-left first:border-l-0 dark:border-white sm:py-6 lg:border-t-0"><p className="text-2xl font-semibold tracking-[-0.04em]">{value}</p><p className="mt-1 text-[9px] font-bold uppercase tracking-[0.14em] text-[#85857c]">{label}</p></div>;
}

function TaskStatusRibbon({ activity, checkpoint }) {
  const evidence = activityEvidenceStatus(activity);
  const updatedAt = activity?.updated_at || checkpoint?.boundary?.captured_at;

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
        value={updatedAt ? `Updated ${formatTimeAgo(updatedAt)}` : "Time unavailable"}
        detail={activity?.live ? "Live session activity" : "Latest available record"}
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

function ObservedWork({ activity, activeTaskTitle }) {
  if (!activity) {
    return (
      <article className="app-surface relative overflow-hidden p-5 sm:p-6">
        <PanelLabel icon={History}>01 / Active task</PanelLabel>
        <h2 className="mt-5 text-2xl font-semibold tracking-[-0.025em] text-[#171713] dark:text-white">Progress</h2>
        <p className="mt-5 text-base font-semibold leading-7 text-[#171713] dark:text-white">No agent progress observed yet.</p>
        <p className="mt-2 text-sm leading-6 text-[#68685f] dark:text-[#aaa9a0]">
          Import a Codex, Claude Code, or OpenCode session to make its latest update visible here.
        </p>
        <Link to="/app/connectors" className="group mt-6 inline-flex items-center gap-1.5 text-xs font-bold text-[#171713] dark:text-[#d9ff68]">
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
  const distinctActivityTitle = activityTitle
    && activityTitle.toLocaleLowerCase() !== activeTaskTitle.toLocaleLowerCase();
  const detailUrl = activity.source_card_id
    ? explainCardUrl(activity.source_card_id)
    : "/app/runs";

  return (
    <article className="app-surface relative overflow-hidden p-5 sm:p-6">
      <div className="relative flex flex-wrap items-center justify-between gap-3">
        <PanelLabel icon={activity.live ? PlayCircle : History}>01 / Active task</PanelLabel>
        <ActivityBadge activity={activity} />
      </div>

      <h2 className="relative mt-5 text-2xl font-semibold tracking-[-0.025em] text-[#171713] dark:text-white">Progress</h2>

      {distinctActivityTitle ? (
        <div className="mt-5 border-l-2 border-[#171713] pl-3 dark:border-white">
          <p className="text-[9px] font-bold uppercase tracking-[0.15em] text-[#85857c]">Observed request</p>
          <h3 className="mt-1.5 text-base font-semibold leading-6 text-[#171713] dark:text-white">{activityTitle}</h3>
        </div>
      ) : null}

      {activity.latest_update ? (
        <p className="relative mt-5 text-base font-semibold leading-7 tracking-[-0.012em] text-[#171713] dark:text-white">
          {cleanDisplayText(activity.latest_update)}
        </p>
      ) : null}

      {activity.rationale ? (
        <div className="relative mt-4 rounded-xl bg-[#f1f1e9] px-4 py-3 dark:bg-white/[0.035]">
          <p className="text-[9px] font-bold uppercase tracking-[0.14em] text-[#85857c]">
            {observedRun ? "Recorded reason" : "Stated reason"}
          </p>
          <p className="mt-1.5 text-xs leading-5 text-[#5f5f57] dark:text-[#bdbdb4]">{cleanDisplayText(activity.rationale)}</p>
        </div>
      ) : null}

      <div className="relative mt-6 flex flex-wrap gap-2">
        <Metric icon={Bot} label={agentLabel(activity)} />
        {activity.branch ? <Metric icon={GitBranch} label={activity.branch} /> : null}
        {observedRun && changedFiles.length ? <Metric icon={FileCode2} label={`${changedFiles.length} file${changedFiles.length === 1 ? "" : "s"} changed`} /> : null}
        <Metric icon={Clock3} label={activity.updated_at ? `Updated ${formatTimeAgo(activity.updated_at)}` : "Update time unavailable"} />
      </div>

      <div className="relative mt-5 flex flex-col gap-3 border-t border-[#e5e5dd] pt-4 dark:border-[#292925] sm:flex-row sm:items-center sm:justify-between">
        <p className="text-[10px] font-medium leading-5 text-[#85857c]">
          {observedRun
            ? "Changes and checks come from recorded run evidence."
            : checkpointBoundary
              ? "This work is scoped to the same provider, session, and event boundary as the checkpoint above."
            : unassigned
              ? "This transcript is visible for review, but is not yet counted as project truth."
              : "This update comes from an imported transcript; repository changes were not observed."}
        </p>
        <Link to={detailUrl} className="group inline-flex shrink-0 items-center gap-1.5 text-xs font-bold text-[#171713] dark:text-[#d9ff68]">
          {activity.source_card_id ? "Explain session evidence" : checkpointBoundary ? "Inspect checkpoint evidence" : "Inspect run evidence"}
          <ArrowRight className="h-3 w-3 transition-transform group-hover:translate-x-0.5" />
        </Link>
      </div>
    </article>
  );
}

function ObservedResult({ activity, checkpoint, attentionCount }) {
  const outcome = activity?.outcome || null;
  const verification = activity?.verification || {};
  const changedFiles = activity?.changed_files || [];
  const trust = activityEvidenceStatus(activity);
  const checkpointVerified = checkpoint?.verification?.status === "verified";

  return (
    <article className="app-surface p-5 sm:p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <PanelLabel icon={CheckCircle2}>02 / Trust</PanelLabel>
        <span className={`rounded-full bg-[#f1f1ec] px-2.5 py-1 text-[9px] font-bold dark:bg-white/[0.06] ${trust.panelTone}`}>
          {trust.value}
        </span>
      </div>
      <h2 className="mt-5 text-2xl font-semibold tracking-[-0.025em] text-[#171713] dark:text-white">Verification</h2>
      {outcome ? (
        <>
          <p className="mt-5 text-base font-semibold leading-7 tracking-[-0.012em] text-[#171713] dark:text-white">
            {cleanDisplayText(outcome.summary) || "A terminal outcome was recorded."}
          </p>
          <div className="mt-5 space-y-2.5 border-t border-[#e5e5dd] pt-4 dark:border-[#292925]">
            {changedFiles.length ? <EvidenceRow label="Changed" value={`${changedFiles.length} file${changedFiles.length === 1 ? "" : "s"}`} /> : null}
            {verification.observed ? <EvidenceRow label="Checks" value={verificationLabel(verification)} /> : null}
            <EvidenceRow label="Observed" value={formatTimeAgo(outcome.observed_at || activity?.updated_at)} />
          </div>
        </>
      ) : (
        <>
          <p className="mt-5 text-base font-semibold leading-7 text-[#171713] dark:text-white">
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
            <div className="mt-5 border-t border-[#e5e5dd] pt-4 dark:border-[#292925]">
              <EvidenceRow label="Checks so far" value={verificationLabel(verification)} />
            </div>
          ) : null}
        </>
      )}
      {checkpointVerified ? (
        <p className="mt-5 border-t border-[#e5e5dd] pt-4 text-[11px] leading-5 text-[#68685f] dark:border-[#292925] dark:text-[#aaa9a0]">
          The saved recovery point is verified separately. That does not verify newer activity.
        </p>
      ) : null}
      <div className="mt-5 flex flex-col gap-2 border-t border-[#e5e5dd] pt-4 dark:border-[#292925]">
        <Link to="/app/explain" className="group inline-flex items-center gap-1.5 text-xs font-bold text-[#171713] dark:text-[#d9ff68]">
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

function ContinuationSummary({ checkpoint, latestSession }) {
  const currentness = checkpoint?.currentness?.state;
  const outdated = currentness === "superseded" || currentness === "historical";
  const savedNextAction = prepareTaskCandidate(checkpoint?.sections?.exact_next_action?.[0]?.statement);
  const nextAction = savedNextAction
    || (latestSession
      ? "Capture the current session to preserve its exact next action."
      : "Choose or import an agent session before continuing.");

  return (
    <article className="app-surface flex flex-col p-5 sm:p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <PanelLabel icon={Clipboard}>03 / Continue</PanelLabel>
        {checkpoint ? (
          <span className={`rounded-full px-2.5 py-1 text-[9px] font-bold ${outdated ? "bg-amber-100 text-amber-800 dark:bg-amber-950/50 dark:text-amber-200" : "bg-[#edf3d7] text-[#617324] dark:bg-[#d9ff68]/10 dark:text-[#d9ff68]"}`}>
            {outdated ? "Earlier state" : "Saved state"}
          </span>
        ) : null}
      </div>
      <h2 className="mt-5 text-2xl font-semibold tracking-[-0.025em] text-[#171713] dark:text-white">Exact next action</h2>
      <p className="mt-5 text-base font-semibold leading-7 tracking-[-0.012em] text-[#171713] dark:text-white">
        {nextAction}
      </p>
      <p className="mt-3 text-[11px] leading-5 text-[#68685f] dark:text-[#aaa9a0]">
        {checkpoint
          ? outdated
            ? "This instruction belongs to an earlier recovery point; newer activity is not merged into it."
            : "This instruction was saved at the recovery boundary and remains separate from newer work."
          : latestSession
            ? "No exact next action has been preserved in a structured recovery point yet."
            : "No session continuation is available yet."}
      </p>
      <div className="mt-auto pt-6">
        {checkpoint || latestSession ? (
          <a href="#continuity-checkpoint" className="group inline-flex items-center gap-1.5 text-xs font-bold text-[#171713] dark:text-[#d9ff68]">
            {checkpoint ? "Review recovery point" : "Capture recovery point"}
            <ArrowRight className="h-3 w-3 transition-transform group-hover:translate-x-0.5" />
          </a>
        ) : (
          <Link to="/app/library" className="group inline-flex items-center gap-1.5 text-xs font-bold text-[#171713] dark:text-[#d9ff68]">
            Choose work <ArrowRight className="h-3 w-3 transition-transform group-hover:translate-x-0.5" />
          </Link>
        )}
      </div>
    </article>
  );
}

function AttentionPanel({ cards }) {
  return (
    <section className="app-surface p-5 sm:p-6">
      <div className="flex items-center justify-between gap-3">
        <PanelLabel icon={ShieldAlert}>Needs attention</PanelLabel>
        <span className="rounded-full bg-amber-100/80 px-2.5 py-1 text-[9px] font-bold text-amber-800 dark:bg-amber-950/50 dark:text-amber-200">
          {cards.length} visible
        </span>
      </div>
      {cards.length ? (
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

function BoundaryDetail({ label, value }) {
  return (
    <div>
      <dt className="text-[9px] font-semibold text-[#85857c]">{label}</dt>
      <dd className="mt-1 text-xs font-semibold text-[#383832] dark:text-[#deded6]">{value}</dd>
    </div>
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

function checkpointEventsBehind(checkpoint) {
  const boundary = Number(checkpoint?.boundary?.sequence_number);
  const tip = Number(checkpoint?.boundary?.session_tip_sequence);
  if (!Number.isFinite(boundary) || !Number.isFinite(tip) || tip <= boundary) return 0;
  return tip - boundary;
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
