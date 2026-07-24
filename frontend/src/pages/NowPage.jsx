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
  TestTube2,
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
import { useContextDigest, useLinkedAISessionRefresh } from "../context-map/api";
import { cleanDisplayText, formatTimeAgo, sessionIdentity } from "../context-map/digest";
import { useProductWorkspace } from "./useProductWorkspace";

export default function NowPage() {
  const workspace = useProductWorkspace();
  const digestQuery = useContextDigest(workspace.activeWorkspaceId, { poll: true });
  const checkpointQuery = useLatestCheckpoint(workspace.activeWorkspaceId);
  const checkpointHistoryQuery = useCheckpoints(workspace.activeWorkspaceId, 100);
  const libraryQuery = useSessionLibrary(workspace.activeWorkspaceId);
  const captureCheckpoint = useCaptureCheckpoint();
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

  return (
    <div className="app-page ce-now-page relative">
      <header className="ce-now-hero relative overflow-hidden rounded-[1.75rem] border border-black/10 bg-[#171713] p-5 text-white shadow-[0_24px_70px_rgba(23,23,19,0.16)] sm:p-7 lg:p-8 dark:border-[#292929]">
        <div className="ce-now-grid pointer-events-none absolute inset-0" aria-hidden="true" />
        <div className="ce-now-orbit pointer-events-none absolute -right-24 -top-40 h-80 w-80 rounded-full border border-[#d9ff68]/20" aria-hidden="true" />
        <div className="relative flex flex-col gap-7 lg:flex-row lg:items-end lg:justify-between">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-3">
              <p className="text-xs font-semibold text-[#c5c5bc]">{workspace.activeWorkspace?.name || "Project"}</p>
              <span className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/[0.055] px-2.5 py-1 text-[11px] font-semibold text-[#d0d0c8]">
                <span className="ce-now-status-dot h-1.5 w-1.5 rounded-full bg-[#d9ff68]" aria-hidden="true" />
                {activity ? "Observing activity" : "Ready for activity"}
              </span>
            </div>
            <h1 className="mt-5 text-5xl font-semibold leading-none tracking-[-0.055em] text-white sm:text-6xl">Now</h1>
            <p className="mt-4 max-w-2xl text-sm leading-6 text-[#b8b8af] sm:text-[15px]">
              The current work, its latest result, and the safest verified point to continue from.
            </p>
            {currentGoal ? (
              <div className="mt-6 max-w-3xl rounded-2xl border border-[#d9ff68]/20 bg-[#d9ff68]/[0.07] px-4 py-3">
                <p className="text-[11px] font-semibold text-[#d9ff68]">Selected goal</p>
                <p className="mt-1 truncate text-sm font-semibold text-white">{currentGoal}</p>
              </div>
            ) : null}
          </div>
          <div className="flex shrink-0 flex-wrap items-center gap-2">
            <Link to="/app/explain" className="inline-flex h-11 items-center justify-center rounded-xl border border-white/15 bg-white/[0.055] px-4 text-xs font-semibold text-white transition hover:-translate-y-0.5 hover:bg-white/10">
              Explain project
            </Link>
            {latestSession ? (
              <button type="button" onClick={saveCheckpoint} disabled={captureCheckpoint.isPending} className="inline-flex h-11 items-center justify-center gap-2 rounded-xl bg-[#d9ff68] px-4 text-xs font-semibold text-[#171713] transition hover:-translate-y-0.5 hover:bg-[#e4ff91] disabled:cursor-wait disabled:opacity-60">
                {captureCheckpoint.isPending ? "Saving checkpoint…" : "Save checkpoint"}
                <RefreshCw className={`h-3.5 w-3.5 ${captureCheckpoint.isPending ? "animate-spin" : ""}`} />
              </button>
            ) : (
              <Link to="/app/library" className="inline-flex h-11 items-center justify-center gap-2 rounded-xl bg-[#d9ff68] px-4 text-xs font-semibold text-[#171713] transition hover:-translate-y-0.5 hover:bg-[#e4ff91]">
                Choose work <ArrowRight className="h-3.5 w-3.5" />
              </Link>
            )}
          </div>
        </div>
      </header>

      {unassignedSessionCount > 0 ? <UnassignedSessions count={unassignedSessionCount} cardId={unassignedSessionCard?.id} /> : null}

      <section className="grid items-stretch gap-4 lg:grid-cols-[1.48fr_.82fr]">
        <ObservedWork activity={activity} />
        <ObservedResult activity={activity} />
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
    return <section className="app-surface p-5 text-sm text-[#68685f] dark:text-[#aaa9a0]">Loading structured checkpoint…</section>;
  }
  if (!checkpoint) {
    return (
      <section className="app-surface p-5 sm:p-6">
        <PanelLabel icon={ShieldCheck}>Continuity checkpoint</PanelLabel>
        <h2 className="mt-5 text-xl font-semibold">No structured checkpoint captured yet.</h2>
        <p className="mt-2 max-w-2xl text-sm leading-6 text-[#68685f] dark:text-[#aaa9a0]">
          Checkpoints are created automatically at context compaction boundaries. Save one now to capture the latest goal, progress, decisions, failures, files, blockers, checks, and exact next action.
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
  const goal = sections.goal?.[0]?.statement || "Goal was not captured.";
  const nextAction = sections.exact_next_action?.[0]?.statement || "Exact next action is missing.";
  const verification = checkpoint.verification;
  const status = verification?.status || "not_run";
  const currentness = checkpoint.currentness || {};
  const boundary = checkpoint.boundary || {};
  const snapshotPhaseLabel = boundary.snapshot_phase_label || (
    checkpoint.trigger === "compaction" ? "Pre-compaction snapshot" : "Session-tip snapshot"
  );
  const snapshotPhaseDescription = boundary.snapshot_phase_description || (
    checkpoint.trigger === "compaction"
      ? "Captures session state immediately before context compaction and excludes later events."
      : "Captures session state through the selected latest event."
  );
  const outdated = currentness.state === "superseded" || currentness.state === "historical";
  const eventsBehind = checkpointEventsBehind(checkpoint);
  const statusTone = checkpointStatusTone(status, checkpoint.capture_status);
  const evidenceCount = checkpoint.payload?.sections
    ? Object.values(checkpoint.payload.sections)
      .flat()
      .reduce((count, item) => count + (item.evidence_event_ids?.length || 0), 0)
    : 0;
  return (
    <>
    <section className="app-surface relative overflow-hidden p-5 sm:p-6">
      <SurfaceAccent />
      <div className="relative flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0 max-w-4xl">
          <div className="flex flex-wrap items-center gap-2">
            <PanelLabel icon={outdated ? History : ShieldCheck}>{outdated ? "Last recovery checkpoint" : "Continuity checkpoint"}</PanelLabel>
            <span className={`rounded-full px-2.5 py-1 text-[9px] font-bold uppercase tracking-wide ${statusTone}`}>{status.replaceAll("_", " ")}</span>
            <span className="rounded-full bg-[#efefe7] px-2.5 py-1 text-[9px] font-bold text-[#68685f] dark:bg-[#252521] dark:text-[#bdbdb4]">{checkpoint.trigger}</span>
            <span className="rounded-full bg-sky-50 px-2.5 py-1 text-[9px] font-bold text-sky-800 dark:bg-sky-950/40 dark:text-sky-200">{snapshotPhaseLabel}</span>
            <span className="rounded-full bg-amber-50 px-2.5 py-1 text-[9px] font-bold text-amber-800 dark:bg-amber-950/40 dark:text-amber-200">{currentness.label || "Captured boundary"}</span>
          </div>
          <p className="mt-3 max-w-3xl text-[10px] leading-5 text-[#77776e] dark:text-[#aaa9a0]">
            {boundary.occurred_at ? `Boundary ${formatBoundaryTime(boundary.occurred_at)}` : "Boundary time unavailable"}
            {boundary.sequence_number ? ` · event ${boundary.sequence_number}` : ""}
            {boundary.captured_at ? ` · saved ${formatBoundaryTime(boundary.captured_at)}` : ""}. {currentness.reason || "This is an immutable checkpoint, not live session truth."}
          </p>
          <p className="mt-2 max-w-3xl text-[11px] font-semibold leading-5 text-sky-800 dark:text-sky-200">{snapshotPhaseDescription}</p>
          {outdated ? (
            <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-amber-950 dark:border-amber-900/70 dark:bg-amber-950/25 dark:text-amber-100">
              <p className="text-xs font-bold">Not the latest session state{eventsBehind ? ` · ${eventsBehind} events behind` : ""}</p>
              <p className="mt-1 text-[11px] leading-5 opacity-80">This remains available as a recovery point. Save a new checkpoint before resuming if you need the current state.</p>
              {latestSession ? (
                <button type="button" onClick={onCapture} disabled={capturePending} className="mt-3 rounded-lg border border-amber-300 bg-white/70 px-3 py-2 text-[10px] font-bold transition hover:bg-white disabled:cursor-wait disabled:opacity-60 dark:border-amber-800 dark:bg-black/15 dark:hover:bg-black/25">
                  {capturePending ? "Saving latest checkpoint…" : "Save latest checkpoint"}
                </button>
              ) : null}
            </div>
          ) : null}
          <p className="mt-5 text-[9px] font-bold uppercase tracking-[0.15em] text-[#85857c]">Goal</p>
          <h2 className="mt-2 text-xl font-semibold leading-7 tracking-[-0.02em]">{cleanDisplayText(goal)}</h2>
          <div className="mt-5 rounded-xl border border-[#d9dfc6] bg-[#f2f6e6] p-4 dark:border-[#384125] dark:bg-[#d9ff68]/[0.055]">
            <p className="text-[9px] font-bold uppercase tracking-[0.15em] text-[#71802f] dark:text-[#d9ff68]">Exact next action</p>
            <p className="mt-1.5 text-sm font-semibold leading-6">{cleanDisplayText(nextAction)}</p>
          </div>
        </div>
        <div className="flex shrink-0 flex-wrap gap-2">
          <button type="button" onClick={verify} disabled={verifyCheckpoint.isPending} className="btn-secondary h-10 text-xs disabled:cursor-wait disabled:opacity-60">
            {verifyCheckpoint.isPending ? "Running checks…" : "Verify now"}
          </button>
          <button type="button" onClick={() => setConfirmResume(true)} disabled={resumeCheckpoint.isPending} className="btn-primary h-10 text-xs disabled:opacity-60">
            <Clipboard className="h-3.5 w-3.5" />{copyState === "copied" ? "Session opened" : copyState === "copied_only" ? "Resume copied" : "Resume session"}
          </button>
        </div>
      </div>
      {sessionCompactions?.length ? (
        <SessionCompactions checkpoints={sessionCompactions} displayedCheckpointId={checkpoint.id} />
      ) : null}
      <div className="relative mt-5 grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-7">
        <CheckpointMetric label="Progress" value={sections.progress?.length || 0} />
        <CheckpointMetric label="Decisions" value={sections.decisions?.length || 0} />
        <CheckpointMetric label="Failures" value={sections.failed_attempts?.length || 0} />
        <CheckpointMetric label="Files" value={sections.relevant_files?.length || 0} />
        <CheckpointMetric label="Blockers" value={sections.blockers?.length || 0} />
        <CheckpointMetric label="Checks" value={sections.verification?.length || 0} />
        <CheckpointMetric label="Evidence" value={evidenceCount} />
      </div>
      <p className="relative mt-4 break-all text-[9px] font-semibold text-[#85857c]">
        {checkpoint.provider} · {checkpoint.session_id} · {checkpoint.repo?.branch || "branch unavailable"}
      </p>
      {(verifyCheckpoint.error || resumeCheckpoint.error || copyState === "error") ? (
        <p role="alert" className="relative mt-3 text-xs font-semibold text-red-600">{verifyCheckpoint.error?.message || resumeCheckpoint.error?.message || "Clipboard access is unavailable."}</p>
      ) : null}
      {resumeNotice ? <p role="status" className="relative mt-3 text-xs font-semibold text-amber-700 dark:text-amber-300">{resumeNotice}</p> : null}
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
    <section className="relative mt-6 rounded-xl border border-[#e1e1d9] bg-white/40 p-4 dark:border-[#30302b] dark:bg-black/10">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-[10px] font-bold uppercase tracking-[0.14em] text-[#77776e]">Captured compactions for this session · {checkpoints.length}</p>
          <p className="mt-1 text-[11px] leading-5 text-[#68685f] dark:text-[#aaa9a0]">Every entry is the session state immediately before that compaction—not the work that happened after it.</p>
        </div>
        <Link to="/app/runs" className="text-[10px] font-bold underline underline-offset-4">Inspect all evidence</Link>
      </div>
      <div className="mt-4 space-y-2">
        {checkpoints.map((item, index) => {
          const itemBoundary = item.boundary || {};
          const itemGoal = item.sections?.goal?.[0]?.statement || "Goal was not captured.";
          const displayed = item.id === displayedCheckpointId;
          return (
            <div key={item.id} className={`rounded-lg border px-3 py-3 ${displayed ? "border-[#b9cc73] bg-[#f2f6e6] dark:border-[#516127] dark:bg-[#d9ff68]/[0.055]" : "border-[#e5e5dd] bg-white/50 dark:border-[#292925] dark:bg-white/[0.02]"}`}>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-[10px] font-bold">Compaction {index + 1}{displayed ? " · displayed checkpoint" : ""}</p>
                <span className="text-[9px] font-semibold text-[#85857c]">
                  {itemBoundary.occurred_at ? formatBoundaryTime(itemBoundary.occurred_at) : "Time unavailable"}
                  {itemBoundary.sequence_number ? ` · event ${itemBoundary.sequence_number}` : ""}
                </span>
              </div>
              <p className="mt-1.5 line-clamp-2 text-xs font-semibold leading-5">{cleanDisplayText(itemGoal)}</p>
              <p className="mt-1 text-[9px] font-bold text-sky-700 dark:text-sky-300">{itemBoundary.snapshot_phase_label || "Pre-compaction snapshot"}</p>
            </div>
          );
        })}
      </div>
    </section>
  );
}

function CheckpointMetric({ label, value }) {
  return <div className="rounded-xl bg-[#efefe7] p-3 text-center dark:bg-[#252521]"><p className="text-lg font-semibold">{value}</p><p className="mt-0.5 text-[8px] font-bold uppercase tracking-wide text-[#85857c]">{label}</p></div>;
}

function checkpointStatusTone(status, captureStatus) {
  if (status === "verified") return "bg-emerald-100 text-emerald-800 dark:bg-emerald-950/50 dark:text-emerald-200";
  if (status === "failed") return "bg-red-100 text-red-800 dark:bg-red-950/50 dark:text-red-200";
  if (status === "stale") return "bg-amber-100 text-amber-800 dark:bg-amber-950/50 dark:text-amber-200";
  if (captureStatus === "incomplete") return "bg-red-100 text-red-800 dark:bg-red-950/50 dark:text-red-200";
  return "bg-[#efefe7] text-[#68685f] dark:bg-[#252521] dark:text-[#bdbdb4]";
}

function ObservedWork({ activity }) {
  if (!activity) {
    return (
      <article className="app-surface relative overflow-hidden p-5 sm:p-6">
        <SurfaceAccent />
        <PanelLabel icon={PlayCircle}>Observed work</PanelLabel>
        <div className="mt-8 max-w-2xl">
          <h2 className="text-2xl font-semibold tracking-[-0.025em] text-[#171713] dark:text-white">No agent work observed yet.</h2>
          <p className="mt-3 text-sm leading-6 text-[#68685f] dark:text-[#aaa9a0]">
            Import a Codex, Claude Code, or OpenCode session to make the latest request and agent update visible here.
          </p>
          <Link to="/app/connectors" className="group mt-6 inline-flex items-center gap-1.5 text-xs font-bold text-[#171713] dark:text-[#d9ff68]">
            Connect agent sessions <ArrowRight className="h-3 w-3 transition-transform group-hover:translate-x-0.5" />
          </Link>
        </div>
      </article>
    );
  }

  const observedRun = activity.evidence_level === "observed_run";
  const checkpointBoundary = activity.evidence_level === "checkpoint_boundary";
  const unassigned = activity.evidence_level === "session_unassigned";
  const changedFiles = activity.changed_files || [];
  const verification = activity.verification || {};
  const detailUrl = activity.source_card_id
    ? explainCardUrl(activity.source_card_id)
    : "/app/runs";

  return (
    <article className="app-surface relative overflow-hidden p-5 sm:p-6">
      <SurfaceAccent />
      <div className="relative flex flex-wrap items-center justify-between gap-3">
        <PanelLabel icon={activity.live ? PlayCircle : History}>
          {activity.live
            ? "Active work"
            : checkpointBoundary
              ? "Work at checkpoint"
              : observedRun
                ? "Recorded work"
                : "Imported session snapshot"}
        </PanelLabel>
        <ActivityBadge activity={activity} />
      </div>

      <h2 className="relative mt-6 max-w-4xl text-2xl font-semibold leading-[1.2] tracking-[-0.025em] text-[#171713] dark:text-white sm:text-[28px]">
        {cleanDisplayText(activity.request || activity.title) || "Agent request was not captured."}
      </h2>

      {activity.latest_update ? (
        <div className="relative mt-6 border-l-2 border-[#c5d98a] pl-4 dark:border-[#4b5830]">
          <p className="text-[9px] font-bold uppercase tracking-[0.15em] text-[#85857c]">
            {checkpointBoundary
              ? "Last update before boundary"
              : observedRun
                ? "Latest recorded update"
                : "Session update at source time"}
          </p>
          <p className="mt-1.5 max-w-3xl text-sm leading-6 text-[#4f4f48] dark:text-[#d0d0c7]">
            {cleanDisplayText(activity.latest_update)}
          </p>
        </div>
      ) : null}

      {activity.rationale ? (
        <div className="relative mt-5 rounded-xl bg-[#f1f1e9] px-4 py-3 dark:bg-white/[0.035]">
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
        {observedRun && verification.observed ? <Metric icon={TestTube2} label={verificationLabel(verification)} /> : null}
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
          {activity.source_card_id ? "Open session evidence" : checkpointBoundary ? "Inspect checkpoint evidence" : "Inspect recorded run"}
          <ArrowRight className="h-3 w-3 transition-transform group-hover:translate-x-0.5" />
        </Link>
      </div>
    </article>
  );
}

function ObservedResult({ activity }) {
  const outcome = activity?.outcome || null;
  const verification = activity?.verification || {};
  const changedFiles = activity?.changed_files || [];

  return (
    <article className="app-surface p-5 sm:p-6">
      <PanelLabel icon={CheckCircle2}>{activity?.evidence_level === "checkpoint_boundary" ? "Result at checkpoint" : "Latest observed result"}</PanelLabel>
      {outcome ? (
        <>
          <p className="mt-7 text-lg font-semibold leading-7 tracking-[-0.012em] text-[#171713] dark:text-white">
            {cleanDisplayText(outcome.summary) || "A terminal outcome was recorded."}
          </p>
          <div className="mt-6 space-y-2.5 border-t border-[#e5e5dd] pt-4 dark:border-[#292925]">
            {changedFiles.length ? <EvidenceRow label="Changed" value={`${changedFiles.length} file${changedFiles.length === 1 ? "" : "s"}`} /> : null}
            {verification.observed ? <EvidenceRow label="Checks" value={verificationLabel(verification)} /> : null}
            <EvidenceRow label="Observed" value={formatTimeAgo(outcome.observed_at || activity?.updated_at)} />
          </div>
          <Link to="/app/runs" className="group mt-6 inline-flex items-center gap-1.5 text-xs font-bold text-[#171713] dark:text-[#d9ff68]">
            View run evidence <ArrowRight className="h-3 w-3 transition-transform group-hover:translate-x-0.5" />
          </Link>
        </>
      ) : (
        <>
          <p className="mt-7 text-lg font-semibold leading-7 text-[#171713] dark:text-white">No verified result captured.</p>
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
      <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-[#edf3d7] text-[#708327] dark:bg-[#d9ff68]/10 dark:text-[#d9ff68]"><Icon className="h-3.5 w-3.5" /></span>
      {children}
    </div>
  );
}

function SurfaceAccent() {
  return (
    <>
      <div className="pointer-events-none absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-[#accf3d] to-transparent opacity-80 dark:via-[#d9ff68]" />
      <div className="pointer-events-none absolute -right-20 -top-24 h-52 w-52 rounded-full bg-[#d9ff68]/10 blur-3xl dark:bg-[#d9ff68]/[0.055]" />
    </>
  );
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
    <span className={`rounded-full px-2.5 py-1 text-[9px] font-bold ${activity.live ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-400/10 dark:text-emerald-200" : "bg-[#efefe7] text-[#68685f] dark:bg-[#252521] dark:text-[#bdbdb4]"}`}>
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
  const task = cleanDisplayText(value);
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
  return runtimeMarkers.some((marker) => lowered.includes(marker)) ? "" : task;
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
