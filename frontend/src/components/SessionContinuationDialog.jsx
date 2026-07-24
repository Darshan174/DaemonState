import { useEffect, useRef } from "react";
import {
  AlertTriangle,
  Clipboard,
  ExternalLink,
  Layers3,
  ShieldCheck,
  X,
} from "lucide-react";
import { createPortal } from "react-dom";

import { ledgerSections } from "../pages/sessionContinuity";


export default function SessionContinuationDialog({
  card,
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
    if (!card) return undefined;
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
  }, [card]);

  if (!card) return null;

  const sections = ledgerSections(card.ledger);
  const repositoryChanged = repositoryComparison?.status === "changed";
  const totalMeasured = sections.reduce(
    (total, section) => total + (Number.isFinite(section.count) ? section.count : 0),
    0,
  );

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/65 px-4 py-4 backdrop-blur-[5px]"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !isPending) onCancel();
      }}
    >
      <section
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={`continue-session-${safeId(card.key)}`}
        aria-describedby={`continue-session-description-${safeId(card.key)}`}
        className="ce-continuation-dialog max-h-[calc(100dvh-2rem)] w-full max-w-2xl overflow-y-auto rounded-[1.75rem] border border-[#d5d5cc] bg-[#fbfbf6] shadow-[0_36px_120px_rgba(0,0,0,0.38)] dark:border-[#393934] dark:bg-[#0b0b09]"
      >
        <div className="relative overflow-hidden border-b border-[#deded5] px-5 py-5 dark:border-[#292925] sm:px-7 sm:py-6">
          <div
            aria-hidden="true"
            className="absolute -right-20 -top-24 h-56 w-56 rounded-full opacity-20 blur-3xl"
            style={{ backgroundColor: providerAccent(card.provider) }}
          />
          <div className="relative flex items-start justify-between gap-5">
            <div className="min-w-0">
              <p className="text-[10px] font-black uppercase tracking-[0.18em] text-[#77776e] dark:text-[#aaa9a0]">
                Recovered session context
              </p>
              <h2
                ref={headingRef}
                id={`continue-session-${safeId(card.key)}`}
                tabIndex={-1}
                className="mt-2 text-2xl font-black tracking-[-0.035em] outline-none sm:text-3xl"
              >
                Repair context and continue?
              </h2>
              <p className="mt-2 line-clamp-2 text-sm font-bold leading-6 text-[#68685f] dark:text-[#aaa9a0]">
                {card.title}
              </p>
            </div>
            <button
              type="button"
              onClick={onCancel}
              disabled={isPending}
              aria-label="Close session continuation dialog"
              className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full border border-[#d8d8cf] bg-white/70 text-[#77776e] transition hover:-rotate-6 hover:border-[#aaa99f] hover:text-[#171713] disabled:opacity-50 dark:border-[#34342f] dark:bg-black/30 dark:hover:text-white"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>

        <div className="space-y-4 p-5 sm:p-7">
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-5" aria-label="Recovered context summary">
            {sections.map((section) => (
              <div key={section.key} className="rounded-xl border border-[#deded5] bg-white/70 px-3 py-3 dark:border-[#2e2e29] dark:bg-black/20">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono text-sm font-black" aria-hidden="true">{section.symbol}</span>
                  <span className="font-mono text-xs font-black text-[#77776e] dark:text-[#aaa9a0]">
                    {section.count === null && section.status === "not_applicable" ? "N/A" : (section.count === null ? "—" : section.count)}
                  </span>
                </div>
                <p className="mt-2 text-[9px] font-black uppercase tracking-[0.13em]">{section.label}</p>
              </div>
            ))}
          </div>

          {repositoryComparisonLoading ? (
            <Notice icon={ShieldCheck} title="Checking the current repository">
              This comparison is read-only. No commands are being run.
            </Notice>
          ) : repositoryChanged ? (
            <Notice icon={AlertTriangle} title="The repository changed after this session context was captured" attention>
              Continuing copies recovered context; it does not restore or overwrite current files.
            </Notice>
          ) : repositoryComparison?.status === "matched" ? (
            <Notice icon={ShieldCheck} title="The repository matches the saved working state">
              The recovered context and current working tree are aligned.
            </Notice>
          ) : null}

          {card.missingUnmeasured ? (
            <Notice icon={AlertTriangle} title="Compaction loss cannot be measured yet" attention>
              The provider does not expose the active prompt created after compaction. Context Engine preserves the source history but will not pretend that “nothing is missing.”
            </Notice>
          ) : null}

          <div className="rounded-2xl border border-[#d8d8cf] bg-[#171713] p-5 text-white dark:border-[#383833] dark:bg-[#151512]">
            <div className="flex items-start gap-3">
              <Layers3 className="mt-0.5 h-5 w-5 shrink-0 text-[#d9ff68]" aria-hidden="true" />
              <div>
                <p className="text-sm font-black">What Context Engine will prepare</p>
                <p className="mt-1 text-xs leading-5 text-white/70">
                  One source-backed continuation containing {totalMeasured} captured context {totalMeasured === 1 ? "item" : "items"}, with every section labelled by its evidence status.
                </p>
              </div>
            </div>
            <div className="mt-4 grid gap-3 border-t border-white/15 pt-4 sm:grid-cols-2">
              <DialogStep icon={ExternalLink} title={`Open ${card.providerLabel}`}>
                Opens the original linked session when the desktop app is available.
              </DialogStep>
              <DialogStep icon={Clipboard} title="Copy repaired context">
                Copies the reconstructed ledger so you can review it before use.
              </DialogStep>
            </div>
          </div>

          <p id={`continue-session-description-${safeId(card.key)}`} className="text-[11px] font-semibold leading-5 text-[#68685f] dark:text-[#aaa9a0]">
            Nothing is sent, pasted, restored, or overwritten automatically.
          </p>

          <div className="flex flex-col-reverse gap-2 pt-1 sm:flex-row sm:justify-end">
            <button type="button" onClick={onCancel} disabled={isPending} className="btn-secondary min-h-11 text-xs disabled:opacity-50">
              Cancel
            </button>
            <button
              type="button"
              onClick={onConfirm}
              disabled={isPending || repositoryComparisonLoading}
              className="btn-primary min-h-11 text-xs disabled:cursor-wait disabled:opacity-60"
            >
              <Clipboard className="h-4 w-4" />
              {isPending ? "Preparing recovered context…" : `Open ${card.providerLabel} and copy context`}
            </button>
          </div>
        </div>
      </section>
    </div>,
    document.body,
  );
}

function Notice({ icon: Icon, title, children, attention = false }) {
  return (
    <div className={`flex gap-3 rounded-2xl border p-4 ${
      attention
        ? "border-amber-200 bg-amber-50 text-amber-950 dark:border-amber-900/70 dark:bg-amber-950/30 dark:text-amber-100"
        : "border-[#d8d8cf] bg-white/70 dark:border-[#30302b] dark:bg-black/20"
    }`}>
      <Icon className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
      <div>
        <p className="text-xs font-black">{title}</p>
        <p className="mt-1 text-[11px] leading-5 opacity-80">{children}</p>
      </div>
    </div>
  );
}

function DialogStep({ icon: Icon, title, children }) {
  return (
    <div className="flex gap-2.5">
      <Icon className="mt-0.5 h-4 w-4 shrink-0 text-[#d9ff68]" aria-hidden="true" />
      <div>
        <p className="text-xs font-black">{title}</p>
        <p className="mt-1 text-[11px] leading-5 text-white/65">{children}</p>
      </div>
    </div>
  );
}

function providerAccent(provider) {
  return {
    codex: "#10a37f",
    claude: "#d97757",
    opencode: "#b9dc4a",
  }[provider] || "#d9ff68";
}

function safeId(value) {
  let hash = 0;
  for (const character of String(value || "")) {
    hash = ((hash << 5) - hash + character.charCodeAt(0)) | 0;
  }
  return Math.abs(hash).toString(36);
}
