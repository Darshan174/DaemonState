import { AlertTriangle, Clipboard, ExternalLink, X } from "lucide-react";
import { createPortal } from "react-dom";

export default function ResumeCheckpointDialog({ checkpoint, isPending, onCancel, onConfirm }) {
  if (!checkpoint) return null;

  const boundary = checkpoint.boundary || {};
  const currentness = checkpoint.currentness || {};
  const eventsBehind = checkpointEventsBehind(checkpoint);
  const outdated = currentness.state === "superseded" || currentness.state === "historical";
  const provider = providerLabel(checkpoint.provider);
  const snapshotPhaseLabel = boundary.snapshot_phase_label || (
    checkpoint.trigger === "compaction" ? "Pre-compaction snapshot" : "Session-tip snapshot"
  );
  const snapshotPhaseDescription = boundary.snapshot_phase_description || (
    checkpoint.trigger === "compaction"
      ? "This contains the session state immediately before compaction and excludes later work."
      : "This contains session state through the selected latest event."
  );
  const launchDescription = checkpoint.provider === "codex"
    ? `Open the original ${provider} task when the desktop app is available.`
    : checkpoint.provider === "opencode"
      ? `Open the linked ${provider} project when the desktop app is available. Exact session reopening is not supported.`
      : `Open ${provider} when the desktop app is available. Exact session reopening is not supported.`;

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 px-4" role="presentation">
      <section
        role="dialog"
        aria-modal="true"
        aria-labelledby={`resume-checkpoint-${checkpoint.id}`}
        className="w-full max-w-lg rounded-2xl border border-[#d8d8cf] bg-[#fbfbf6] p-5 shadow-2xl dark:border-[#35352f] dark:bg-[#141411] sm:p-6"
      >
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-[9px] font-bold uppercase tracking-[0.16em] text-[#85857c]">Before you continue</p>
            <h2 id={`resume-checkpoint-${checkpoint.id}`} className="mt-2 text-xl font-semibold tracking-[-0.02em]">
              Resume from this checkpoint?
            </h2>
          </div>
          <button type="button" onClick={onCancel} disabled={isPending} aria-label="Close resume warning" className="rounded-lg p-1.5 text-[#77776e] transition hover:bg-[#efefe7] hover:text-[#171713] disabled:opacity-50 dark:hover:bg-[#252521] dark:hover:text-white">
            <X className="h-4 w-4" />
          </button>
        </div>

        {outdated ? (
          <div className="mt-5 flex gap-3 rounded-xl border border-amber-200 bg-amber-50 p-4 text-amber-950 dark:border-amber-900/70 dark:bg-amber-950/30 dark:text-amber-100">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            <div>
              <p className="text-xs font-bold">This checkpoint is not the latest session state.</p>
              <p className="mt-1 text-[11px] leading-5 opacity-80">
                {eventsBehind > 0
                  ? `${eventsBehind} newer event${eventsBehind === 1 ? " exists" : "s exist"} after this boundary.`
                  : currentness.reason || "Newer or more current work may exist."}
                {boundary.occurred_at ? ` It resumes the state captured at ${formatBoundaryTime(boundary.occurred_at)}.` : ""}
              </p>
            </div>
          </div>
        ) : null}

        <div className="mt-4 rounded-xl border border-sky-200 bg-sky-50 p-4 text-sky-950 dark:border-sky-900/70 dark:bg-sky-950/25 dark:text-sky-100">
          <p className="text-xs font-bold">{snapshotPhaseLabel}</p>
          <p className="mt-1 text-[11px] leading-5 opacity-80">{snapshotPhaseDescription}</p>
        </div>

        <div className="mt-5 space-y-3 rounded-xl border border-[#e2e2da] bg-white/60 p-4 dark:border-[#30302b] dark:bg-black/15">
          <ResumeStep icon={ExternalLink} title={`Open ${provider}`}>
            {launchDescription}
          </ResumeStep>
          <ResumeStep icon={Clipboard} title="Copy the resume bundle">
            After the launch attempt returns, the bundle generated from this checkpoint’s goal, evidence, and exact next action is copied to your clipboard.
          </ResumeStep>
        </div>

        <p className="mt-4 text-[11px] font-semibold leading-5 text-[#68685f] dark:text-[#aaa9a0]">
          Nothing is sent or pasted automatically. Review the copied bundle before using it in the opened session.
        </p>

        <div className="mt-6 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <button type="button" onClick={onCancel} disabled={isPending} className="btn-secondary h-10 text-xs disabled:opacity-50">Cancel</button>
          <button type="button" onClick={onConfirm} disabled={isPending} className="btn-primary h-10 text-xs disabled:cursor-wait disabled:opacity-60">
            {isPending ? "Preparing resume…" : outdated ? "Resume from old checkpoint" : `Open ${provider} and copy bundle`}
          </button>
        </div>
      </section>
    </div>,
    document.body,
  );
}

function ResumeStep({ icon: Icon, title, children }) {
  return (
    <div className="flex gap-3">
      <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-[#edf3d7] text-[#708327] dark:bg-[#d9ff68]/10 dark:text-[#d9ff68]"><Icon className="h-3.5 w-3.5" /></span>
      <div>
        <p className="text-xs font-bold">{title}</p>
        <p className="mt-0.5 text-[11px] leading-5 text-[#68685f] dark:text-[#aaa9a0]">{children}</p>
      </div>
    </div>
  );
}

function checkpointEventsBehind(checkpoint) {
  const boundary = Number(checkpoint?.boundary?.sequence_number);
  const tip = Number(checkpoint?.boundary?.session_tip_sequence);
  if (!Number.isFinite(boundary) || !Number.isFinite(tip) || tip <= boundary) return 0;
  return tip - boundary;
}

function providerLabel(value) {
  return {
    codex: "Codex",
    claude: "Claude Desktop",
    claude_code: "Claude Desktop",
    opencode: "OpenCode",
  }[String(value || "").toLowerCase()] || "the desktop agent";
}

function formatBoundaryTime(value) {
  const parsed = value ? new Date(value) : null;
  if (!parsed || Number.isNaN(parsed.getTime())) return "the captured boundary";
  return parsed.toLocaleString([], {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}
