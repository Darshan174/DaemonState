import { useEffect, useRef } from "react";
import { AlertTriangle, Clipboard, ExternalLink, X } from "lucide-react";
import { createPortal } from "react-dom";
import { cleanDisplayText } from "../context-map/digest";

export default function ResumeCheckpointDialog({
  checkpoint,
  repositoryComparison,
  repositoryComparisonLoading = false,
  isPending,
  onCancel,
  onConfirm,
}) {
  const dialogRef = useRef(null);
  const headingRef = useRef(null);
  const onCancelRef = useRef(onCancel);
  const pendingRef = useRef(isPending);

  onCancelRef.current = onCancel;
  pendingRef.current = isPending;

  useEffect(() => {
    if (!checkpoint) return undefined;
    const returnFocusTo = document.activeElement;
    const appRoot = document.getElementById("root");
    const rootWasInert = appRoot?.hasAttribute("inert");
    const previousOverflow = document.body.style.overflow;

    appRoot?.setAttribute("inert", "");
    document.body.style.overflow = "hidden";
    headingRef.current?.focus();

    const onKeyDown = (event) => {
      if (event.key === "Escape" && !pendingRef.current) {
        event.preventDefault();
        onCancelRef.current();
        return;
      }
      if (event.key !== "Tab") return;
      const focusable = Array.from(dialogRef.current?.querySelectorAll(
        'a[href], button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])',
      ) || []).filter((element) => !element.hasAttribute("hidden"));
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
      if (!rootWasInert) appRoot?.removeAttribute("inert");
      document.body.style.overflow = previousOverflow;
      window.requestAnimationFrame(() => returnFocusTo?.focus?.());
    };
  }, [checkpoint]);

  if (!checkpoint) return null;

  const boundary = checkpoint.boundary || {};
  const currentness = checkpoint.currentness || {};
  const taskTitle = cleanDisplayText(checkpoint.sections?.goal?.[0]?.statement || "saved work");
  const eventsBehind = checkpointEventsBehind(checkpoint);
  const outdated = currentness.state === "superseded" || currentness.state === "historical";
  const repositoryChanged = repositoryComparison?.status === "changed";
  const provider = providerLabel(checkpoint.provider);
  const recoveryTitle = checkpoint.trigger === "compaction"
    ? "Saved before the session was condensed"
    : "Saved from the latest session state";
  const recoveryDescription = checkpoint.trigger === "compaction"
    ? "This saved version contains the goal, evidence, and next action available at that moment. Work added later is not included."
    : "This saved version contains the goal, evidence, and next action available when it was saved.";
  const launchDescription = checkpoint.provider === "codex"
    ? `Open the original ${provider} task when the desktop app is available.`
    : checkpoint.provider === "opencode"
      ? `Open the linked ${provider} project when the desktop app is available. Exact session reopening is not supported.`
      : `Open ${provider} when the desktop app is available. Exact session reopening is not supported.`;

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 px-4"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !isPending) onCancel();
      }}
    >
      <section
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={`resume-checkpoint-${checkpoint.id}`}
        aria-describedby={`resume-checkpoint-description-${checkpoint.id}`}
        className="max-h-[calc(100dvh-2rem)] w-full max-w-lg overflow-y-auto rounded-2xl border border-[#deded8] bg-white p-5 shadow-2xl dark:border-[#353535] dark:bg-black sm:p-6"
      >
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-[11px] font-bold uppercase tracking-[0.14em] text-[#68685f] dark:text-[#aaa9a0]">Before you continue</p>
            <h2
              ref={headingRef}
              id={`resume-checkpoint-${checkpoint.id}`}
              tabIndex={-1}
              className="mt-2 text-xl font-semibold tracking-[-0.02em] outline-none"
            >
              Continue this work?{" "}
              <span className="mt-1 line-clamp-2 text-base font-semibold leading-6 text-[#68685f] dark:text-[#aaa9a0]">{taskTitle}</span>
            </h2>
          </div>
          <button type="button" onClick={onCancel} disabled={isPending} aria-label="Close continue dialog" className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl text-[#77776e] transition hover:bg-[#efefe7] hover:text-[#171713] disabled:opacity-50 dark:hover:bg-[#252521] dark:hover:text-white">
            <X className="h-4 w-4" />
          </button>
        </div>

        {outdated ? (
          <div className="mt-5 flex gap-3 rounded-xl border border-amber-200 bg-amber-50 p-4 text-amber-950 dark:border-amber-900/70 dark:bg-amber-950/30 dark:text-amber-100">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            <div>
              <p className="text-xs font-bold">This is an older saved version.</p>
              <p className="mt-1 text-[11px] leading-5 opacity-80">
                {eventsBehind > 0
                  ? "This session has newer activity after it."
                  : currentness.reason || "Newer or more current work may exist."}
                {boundary.occurred_at ? ` It uses the state saved at ${formatBoundaryTime(boundary.occurred_at)}.` : ""}
              </p>
            </div>
          </div>
        ) : null}

        {repositoryComparisonLoading ? (
          <div className="mt-4 rounded-xl border border-[#deded5] bg-[#f7f7f3] p-4 dark:border-[#30302b] dark:bg-[#11110f]">
            <p className="text-xs font-bold">Checking the current repository…</p>
            <p className="mt-1 text-[11px] leading-5 text-[#68685f] dark:text-[#aaa9a0]">This comparison is read-only. No commands are being run.</p>
          </div>
        ) : repositoryChanged ? (
          <div className="mt-4 flex gap-3 rounded-xl border border-amber-200 bg-amber-50 p-4 text-amber-950 dark:border-amber-900/70 dark:bg-amber-950/30 dark:text-amber-100">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            <div>
              <p className="text-xs font-bold">The repository has changed since this version was saved.</p>
              <p className="mt-1 text-[11px] leading-5 opacity-80">
                Continuing will copy the saved context; it will not restore or overwrite your current files.
              </p>
            </div>
          </div>
        ) : null}

        <div className="mt-4 rounded-xl border border-[#e1e1dc] bg-[#f7f7f4] p-4 dark:border-[#292929] dark:bg-[#0c0c0c]">
          <p className="text-xs font-bold">Context from: {recoveryTitle.toLocaleLowerCase()}</p>
          <p className="mt-1 text-[11px] leading-5 text-[#68685f] dark:text-[#aaa9a0]">{recoveryDescription}</p>
        </div>

        <div className="mt-5 space-y-3 rounded-xl border border-[#e2e2da] bg-white/60 p-4 dark:border-[#30302b] dark:bg-black/15">
          <ResumeStep icon={ExternalLink} title={`Open ${provider}`}>
            {launchDescription}
          </ResumeStep>
          <ResumeStep icon={Clipboard} title="Copy the continuation context">
            The goal, saved evidence, and next action from this version are copied to your clipboard after the launch attempt.
          </ResumeStep>
        </div>

        <p id={`resume-checkpoint-description-${checkpoint.id}`} className="mt-4 text-[11px] font-semibold leading-5 text-[#68685f] dark:text-[#aaa9a0]">
          Nothing is sent, pasted, restored, or overwritten automatically. Review the copied context before using it.
        </p>

        <div className="mt-6 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <button type="button" onClick={onCancel} disabled={isPending} className="btn-secondary h-11 text-xs disabled:opacity-50">Cancel</button>
          <button type="button" onClick={onConfirm} disabled={isPending || repositoryComparisonLoading} className="btn-primary h-11 text-xs disabled:cursor-wait disabled:opacity-60">
            {isPending ? "Preparing context…" : outdated ? "Continue from older version" : `Open ${provider} and copy context`}
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
      <Icon className="mt-0.5 h-4 w-4 shrink-0 text-[#77776e] dark:text-[#aaa9a0]" aria-hidden="true" />
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
