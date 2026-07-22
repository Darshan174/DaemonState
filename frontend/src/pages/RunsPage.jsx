import { useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Clipboard,
  Clock3,
  FileCode2,
  History,
  PlayCircle,
  ShieldCheck,
  TestTube2,
  XCircle,
} from "lucide-react";

import WorkspaceTopicGate from "../components/WorkspaceTopicGate";
import ResumeCheckpointDialog from "../components/ResumeCheckpointDialog";
import ProductLoadingState from "../components/ProductLoadingState";
import { useCheckpoints, useResumeCheckpoint, useVerifyCheckpoint } from "../api/hooks";
import { cleanDisplayText, formatTimeAgo } from "../context-map/digest";
import { useProductWorkspace } from "./useProductWorkspace";

const SECTION_LABELS = {
  progress: "Progress",
  decisions: "Decisions",
  failed_attempts: "Failed attempts",
  relevant_files: "Relevant files",
  blockers: "Blockers",
  verification: "Verification evidence",
};

export default function RunsPage() {
  const workspace = useProductWorkspace();
  const checkpointsQuery = useCheckpoints(workspace.activeWorkspaceId);

  if (!workspace.workspacesQuery.isLoading && !workspace.activeWorkspaceId) {
    return <WorkspaceTopicGate workspaces={workspace.workspaces} selectedId={workspace.selectedId} onSelect={workspace.setSelectedId} />;
  }

  const checkpoints = checkpointsQuery.data?.checkpoints || [];
  return (
    <div className="relative mx-auto w-full max-w-6xl space-y-6">
      <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-xs font-black uppercase tracking-[0.18em] text-[#85857c]">{workspace.activeWorkspace?.name || "Project"}</p>
          <h1 className="mt-2 text-3xl font-black tracking-tight">Runs</h1>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-[#68685f] dark:text-[#aaa9a0]">Real session checkpoints, their evidence, verification state, and the exact action required to continue.</p>
        </div>
        {checkpoints.length ? (
          <div className="rounded-xl border border-[#d8d8cf] bg-[#fbfbf6] px-4 py-2 text-right dark:border-[#292925] dark:bg-[#141411]">
            <p className="text-lg font-black">{checkpoints.length}</p>
            <p className="text-[8px] font-black uppercase tracking-wide text-[#85857c]">checkpoints</p>
          </div>
        ) : null}
      </header>

      <CheckpointGuide />

      {checkpointsQuery.isLoading ? (
        <ProductLoadingState
          label="Loading checkpoint history…"
          detail="Captured boundaries are ordered without merging their claims."
          stages={["Opening the checkpoint index", "Reading captured boundaries", "Ordering verification history"]}
        />
      ) : null}
      {checkpointsQuery.isError ? <EmptyState title="Could not load checkpoint evidence" detail={checkpointsQuery.error?.message} error /> : null}
      {!checkpointsQuery.isLoading && !checkpointsQuery.isError ? (
        checkpoints.length ? (
          <CheckpointTimeline checkpoints={checkpoints} workspaceId={workspace.activeWorkspaceId} />
        ) : (
          <EmptyState
            title="No structured checkpoints yet"
            detail="Sync an agent session. Context Engine will capture compaction boundaries automatically, or you can save the latest session from Now."
          />
        )
      ) : null}
    </div>
  );
}

function CheckpointTimeline({ checkpoints, workspaceId }) {
  return (
    <ol aria-label="Checkpoint timeline" className="relative space-y-5 before:absolute before:bottom-6 before:left-[17px] before:top-6 before:w-px before:bg-gradient-to-b before:from-[#afca54] before:via-[#b8b8af] before:to-transparent dark:before:from-[#7d9535] dark:before:via-[#3a3a34]">
      {checkpoints.map((checkpoint, index) => (
        <li key={checkpoint.id} className="relative pl-12">
          <span className="absolute left-0 top-6 z-10 flex h-9 w-9 items-center justify-center border border-[#b9c77c] bg-[#f7f7f2] font-mono text-[9px] font-bold tabular-nums text-[#5e6c27] shadow-[0_0_0_6px_rgba(247,247,242,0.94)] dark:border-[#65762e] dark:bg-[#11110f] dark:text-[#d9ff68] dark:shadow-[0_0_0_6px_rgba(17,17,15,0.94)]">
            {String(index + 1).padStart(2, "0")}
          </span>
          <CheckpointCard checkpoint={checkpoint} workspaceId={workspaceId} />
        </li>
      ))}
    </ol>
  );
}

function CheckpointGuide() {
  const uses = [
    {
      icon: History,
      title: "Review the handoff state",
      detail: "See what the agent knew, decided, and planned immediately before compaction.",
    },
    {
      icon: FileCode2,
      title: "Compare boundaries",
      detail: "Follow the timestamps and event numbers to see how the goal and next action changed.",
    },
    {
      icon: TestTube2,
      title: "Verify against the repository",
      detail: "Check whether captured files, Git state, and test evidence still match the workspace.",
    },
    {
      icon: PlayCircle,
      title: "Resume from this point",
      detail: "Open the original agent session with a copied, evidence-linked resume bundle.",
    },
  ];

  return (
    <section aria-labelledby="checkpoint-guide-title" className="rounded-2xl border border-[#d8d8cf] bg-[#fbfbf6] p-5 dark:border-[#292925] dark:bg-[#141411] sm:p-6">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between sm:gap-5">
        <div>
          <p className="text-[9px] font-black uppercase tracking-[0.16em] text-[#85857c]">Checkpoint guide</p>
          <h2 id="checkpoint-guide-title" className="mt-2 text-lg font-black tracking-[-0.02em]">How to use checkpoints</h2>
          <p className="mt-1 max-w-2xl text-xs leading-5 text-[#68685f] dark:text-[#aaa9a0]">Each automatic checkpoint is a pre-compaction snapshot. It preserves the handoff state before context was compressed; it is not the current session state.</p>
        </div>
        <span className="w-fit shrink-0 rounded-full bg-sky-50 px-3 py-1.5 text-[9px] font-black text-sky-800 dark:bg-sky-950/40 dark:text-sky-200">Evidence-backed history</span>
      </div>

      <div className="mt-5 grid gap-2.5 sm:grid-cols-2 lg:grid-cols-4">
        {uses.map(({ icon: Icon, title, detail }, index) => (
          <article key={title} className="rounded-xl border border-[#e2e2da] bg-white/55 p-4 dark:border-[#30302b] dark:bg-white/[0.025]">
            <div className="flex items-center gap-2">
              <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-[#edf3d7] text-[#708327] dark:bg-[#d9ff68]/10 dark:text-[#d9ff68]"><Icon className="h-3.5 w-3.5" /></span>
              <span className="text-[9px] font-black uppercase tracking-[0.12em] text-[#85857c]">{index + 1}</span>
            </div>
            <h3 className="mt-3 text-xs font-black leading-5">{title}</h3>
            <p className="mt-1 text-[11px] leading-5 text-[#68685f] dark:text-[#aaa9a0]">{detail}</p>
          </article>
        ))}
      </div>

      <details className="mt-4 border-t border-[#e2e2da] pt-4 dark:border-[#30302b]">
        <summary className="cursor-pointer text-[10px] font-black text-[#5f5f57] underline decoration-[#b8b8af] underline-offset-4 dark:text-[#c7c7bd]">Learn what each action does</summary>
        <div className="mt-3 grid gap-3 text-[11px] leading-5 text-[#68685f] dark:text-[#aaa9a0] sm:grid-cols-2">
          <p><strong className="text-[#30302b] dark:text-white">Inspect structured evidence</strong> expands the captured goal, progress, decisions, failures, files, blockers, and checks.</p>
          <p><strong className="text-[#30302b] dark:text-white">Compare</strong> means reviewing checkpoints from the same session in boundary order; Context Engine does not merge their claims.</p>
          <p><strong className="text-[#30302b] dark:text-white">Verify</strong> rechecks the saved repository snapshot and permitted test commands against the workspace as it exists now.</p>
          <p><strong className="text-[#30302b] dark:text-white">Resume session</strong> warns about age, opens the linked desktop agent when supported, and copies the bundle. Nothing is sent automatically.</p>
        </div>
      </details>
    </section>
  );
}

function CheckpointCard({ checkpoint, workspaceId }) {
  const verifyCheckpoint = useVerifyCheckpoint();
  const resumeCheckpoint = useResumeCheckpoint();
  const [copyState, setCopyState] = useState("idle");
  const [resumeNotice, setResumeNotice] = useState("");
  const [confirmResume, setConfirmResume] = useState(false);
  const sections = checkpoint.sections || {};
  const verificationStatus = checkpoint.verification?.status || "not_run";
  const state = checkpointState(verificationStatus, checkpoint.capture_status);
  const StateIcon = state.icon;
  const goal = sections.goal?.[0]?.statement || "Goal was not captured.";
  const nextAction = sections.exact_next_action?.[0]?.statement || "Exact next action is missing.";

  const verify = () => verifyCheckpoint.mutate({
    workspaceId,
    checkpointId: checkpoint.id,
    executeCommands: true,
  });
  const copyResume = async () => {
    setConfirmResume(false);
    setCopyState("idle");
    setResumeNotice("");
    try {
      const bundle = await resumeCheckpoint.mutateAsync({ workspaceId, checkpointId: checkpoint.id, launchSession: true });
      await navigator.clipboard.writeText(bundle.content);
      if (bundle.launch?.launched === false) {
        setCopyState("copied_only");
        setResumeNotice(bundle.launch.message || "Resume copied; the desktop session could not be opened.");
      } else {
        setCopyState("copied");
      }
    } catch {
      setCopyState("error");
    }
  };

  return (
    <article className="rounded-2xl border border-[#d8d8cf] bg-[#fbfbf6] p-5 dark:border-[#292925] dark:bg-[#141411]">
      <div className="flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0 max-w-4xl">
          <div className={`flex flex-wrap items-center gap-2 text-[10px] font-black uppercase tracking-[0.13em] ${state.tone}`}>
            <StateIcon className="h-3.5 w-3.5" />{state.label}
            <span className="text-[#85857c]">· {checkpoint.trigger}</span>
            <span className="text-[#85857c]">· {checkpoint.currentness?.label || "Captured boundary"}</span>
          </div>
          <p className="mt-2 text-[10px] font-bold text-sky-700 dark:text-sky-300">{checkpoint.boundary?.snapshot_phase_label || (checkpoint.trigger === "compaction" ? "Pre-compaction snapshot" : "Session-tip snapshot")}</p>
          <p className="mt-1 max-w-3xl text-[10px] leading-5 text-[#68685f] dark:text-[#aaa9a0]">{checkpoint.boundary?.snapshot_phase_description || (checkpoint.trigger === "compaction" ? "Captures state immediately before compaction; later work is excluded." : "Captures state through the selected latest event.")}</p>
          <h2 className="mt-3 text-lg font-black leading-7">{cleanDisplayText(goal)}</h2>
          <div className="mt-4 border-l-2 border-[#bcd266] pl-4 dark:border-[#596d2b]">
            <p className="text-[8px] font-black uppercase tracking-[0.14em] text-[#85857c]">Exact next action</p>
            <p className="mt-1 text-sm font-semibold leading-6">{cleanDisplayText(nextAction)}</p>
          </div>
        </div>
        <div className="flex shrink-0 flex-wrap gap-2">
          <button type="button" onClick={verify} disabled={verifyCheckpoint.isPending} className="btn-secondary h-9 text-[10px] disabled:cursor-wait disabled:opacity-60">
            <ShieldCheck className="h-3.5 w-3.5" />{verifyCheckpoint.isPending ? "Verifying…" : "Verify"}
          </button>
          <button type="button" onClick={() => setConfirmResume(true)} disabled={resumeCheckpoint.isPending} className="btn-primary h-9 text-[10px] disabled:opacity-60">
            <Clipboard className="h-3.5 w-3.5" />{copyState === "copied" ? "Session opened" : copyState === "copied_only" ? "Resume copied" : "Resume session"}
          </button>
        </div>
      </div>

      <div className="mt-5 grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-6">
        <RunMetric icon={History} value={sections.progress?.length || 0} label="Progress" />
        <RunMetric icon={FileCode2} value={sections.relevant_files?.length || 0} label="Files" />
        <RunMetric icon={TestTube2} value={sections.verification?.length || 0} label="Checks" />
        <RunMetric icon={AlertTriangle} value={sections.failed_attempts?.length || 0} label="Failures" />
        <RunMetric icon={XCircle} value={sections.blockers?.length || 0} label="Blockers" />
        <RunMetric icon={Clock3} value={checkpoint.boundary?.occurred_at ? formatTimeAgo(checkpoint.boundary.occurred_at) : "—"} label="Boundary" />
      </div>

      <details className="mt-5 rounded-xl border border-[#e2e2da] bg-white/55 dark:border-[#292925] dark:bg-[#0f0f0c]">
        <summary className="cursor-pointer px-4 py-3 text-[10px] font-black uppercase tracking-[0.13em]">Inspect structured evidence</summary>
        <div className="space-y-5 border-t border-[#e2e2da] p-4 dark:border-[#292925]">
          {Object.entries(SECTION_LABELS).map(([category, label]) => (
            <CheckpointSection key={category} label={label} items={sections[category] || []} />
          ))}
          <div>
            <p className="text-[9px] font-black uppercase tracking-[0.13em] text-[#85857c]">Repository snapshot</p>
            <p className="mt-2 break-all font-mono text-[10px] leading-5 text-[#68685f] dark:text-[#aaa9a0]">
              {checkpoint.repo?.branch || "branch unavailable"} · {checkpoint.repo?.head_commit || "commit unavailable"}<br />
              fingerprint {checkpoint.repo?.worktree_fingerprint || "unavailable"}
            </p>
          </div>
        </div>
      </details>

      <p className="mt-3 break-all text-[9px] font-semibold leading-5 text-[#85857c]">
        {checkpoint.provider} · {checkpoint.session_id} · boundary event {checkpoint.boundary?.sequence_number || "unknown"} · checkpoint {checkpoint.id}<br />
        {checkpoint.currentness?.reason || "Immutable captured state; not live session truth."}
      </p>
      {(verifyCheckpoint.error || resumeCheckpoint.error || copyState === "error") ? (
        <p role="alert" className="mt-3 text-xs font-semibold text-red-600">{verifyCheckpoint.error?.message || resumeCheckpoint.error?.message || "Clipboard access is unavailable."}</p>
      ) : null}
      {resumeNotice ? <p role="status" className="mt-3 text-xs font-semibold text-amber-700 dark:text-amber-300">{resumeNotice}</p> : null}
      {confirmResume ? (
        <ResumeCheckpointDialog
          checkpoint={checkpoint}
          isPending={resumeCheckpoint.isPending}
          onCancel={() => setConfirmResume(false)}
          onConfirm={copyResume}
        />
      ) : null}
    </article>
  );
}

function CheckpointSection({ label, items }) {
  return (
    <section>
      <p className="text-[9px] font-black uppercase tracking-[0.13em] text-[#85857c]">{label} · {items.length}</p>
      {items.length ? (
        <div className="mt-2 space-y-2">
          {items.map((item) => (
            <div key={item.id} className="rounded-lg bg-[#f1f1e9] px-3 py-2.5 dark:bg-[#22221e]">
              <div className="flex items-start justify-between gap-3">
                <p className="min-w-0 text-xs font-semibold leading-5">{cleanDisplayText(item.statement)}</p>
                <span className="shrink-0 rounded-full bg-white/70 px-2 py-0.5 text-[8px] font-black uppercase text-[#77776e] dark:bg-black/20">{item.truth_state}</span>
              </div>
              <p className="mt-1 text-[8px] font-semibold text-[#85857c]">{item.evidence?.length || 0} evidence event{item.evidence?.length === 1 ? "" : "s"}</p>
            </div>
          ))}
        </div>
      ) : <p className="mt-2 text-xs text-[#85857c]">None captured.</p>}
    </section>
  );
}

function checkpointState(status, captureStatus) {
  if (status === "verified") return { label: "Verified", icon: CheckCircle2, tone: "text-emerald-700 dark:text-emerald-300" };
  if (status === "failed") return { label: "Verification failed", icon: XCircle, tone: "text-red-700 dark:text-red-300" };
  if (status === "stale") return { label: "Repository changed", icon: AlertTriangle, tone: "text-amber-700 dark:text-amber-300" };
  if (captureStatus === "incomplete") return { label: "Incomplete capture", icon: XCircle, tone: "text-red-700 dark:text-red-300" };
  return { label: status === "partial" ? "Partially verified" : "Not verified", icon: PlayCircle, tone: "text-amber-700 dark:text-amber-300" };
}

function RunMetric({ icon: Icon, value, label }) {
  return <div className="rounded-xl bg-[#efefe7] p-3 dark:bg-[#252521]"><div className="flex items-center gap-1.5"><Icon className="h-3 w-3 text-[#85857c]" /><span className="text-sm font-black">{value}</span></div><p className="mt-1 text-[8px] font-bold uppercase tracking-wide text-[#85857c]">{label}</p></div>;
}

function EmptyState({ title, detail, error = false }) {
  return <div className={`rounded-2xl border p-10 text-center ${error ? "border-red-200 bg-red-50 dark:border-red-900/60 dark:bg-red-950/25" : "border-dashed border-[#d8d8cf] bg-[#fbfbf6] dark:border-[#292925] dark:bg-[#141411]"}`}><h2 className="text-base font-black">{title}</h2>{detail ? <p className="mx-auto mt-2 max-w-xl text-xs leading-5 text-[#68685f] dark:text-[#aaa9a0]">{detail}</p> : null}</div>;
}
