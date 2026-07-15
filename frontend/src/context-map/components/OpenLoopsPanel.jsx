import { useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  ExternalLink,
  FileText,
  Loader2,
  X,
} from "lucide-react";

import { api } from "../../api/client";

const CLOSED_STATES = new Set(["dismissed", "resolved", "superseded"]);

export default function OpenLoopsPanel({
  data,
  loading = false,
  error = null,
  workspaceId,
  onClose,
  onOpenFocus,
  onUpdate,
  updating = false,
  playbooks = [],
  playbooksLoading = false,
  onUpdatePlaybook,
  updatingPlaybook = false,
}) {
  const panelRef = useRef(null);
  const loops = loopItems(data);

  useEffect(() => {
    panelRef.current?.querySelector('[aria-label="Close open loops"]')?.focus();
  }, []);

  return (
    <aside
      ref={panelRef}
      role="dialog"
      aria-modal="true"
      aria-labelledby="open-loops-title"
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          event.preventDefault();
          onClose?.();
          return;
        }
        if (event.key !== "Tab") return;
        const focusable = [...(panelRef.current?.querySelectorAll(
          'button:not([disabled]), a[href], input:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ) || [])];
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
      }}
      className="flex min-h-0 w-full shrink-0 flex-col border-l border-slate-200 bg-white dark:border-neutral-800 dark:bg-[#07080a]"
    >
      <div className="flex items-start justify-between gap-3 border-b border-slate-200 p-4 dark:border-neutral-800">
        <div>
          <h2 id="open-loops-title" className="text-base font-black text-slate-950 dark:text-white">Open loops</h2>
          <p className="mt-1 text-xs font-semibold text-slate-500 dark:text-neutral-400">
            Unfinished or unsupported work that still needs a decision.
          </p>
        </div>
        <button type="button" onClick={onClose} aria-label="Close open loops" className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-slate-400 transition hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-black dark:hover:text-white">
          <X className="h-4 w-4" />
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        <PlaybookReviewList
          playbooks={playbooks}
          loading={playbooksLoading}
          onUpdate={onUpdatePlaybook}
          updating={updatingPlaybook}
        />
        {loading && !loops.length ? (
          <p className="flex items-center gap-2 text-xs font-semibold text-slate-500"><Loader2 className="h-3.5 w-3.5 animate-spin" />Loading open loops…</p>
        ) : error && !loops.length ? (
          <p role="alert" className="rounded-md border border-red-200 bg-red-50 p-3 text-xs font-semibold text-red-700 dark:border-red-900/60 dark:bg-red-950/30 dark:text-red-300">{error?.message || "Open loops are unavailable."}</p>
        ) : loops.length ? (
          <OpenLoopList
            loops={loops}
            workspaceId={workspaceId}
            onOpenFocus={onOpenFocus}
            onUpdate={onUpdate}
            updating={updating}
            showClosed
          />
        ) : (
          <div className="rounded-lg border border-dashed border-slate-200 p-5 text-center dark:border-neutral-800">
            <CheckCircle2 className="mx-auto h-5 w-5 text-emerald-600" />
            <p className="mt-2 text-xs font-black text-slate-800 dark:text-neutral-200">No open loops</p>
            <p className="mt-1 text-xs font-semibold text-slate-400">No supported unresolved finding is recorded for this project.</p>
          </div>
        )}
      </div>
    </aside>
  );
}

export function OpenLoopList({
  loops = [],
  workspaceId,
  onOpenFocus,
  onUpdate,
  updating = false,
  showClosed = false,
}) {
  const ordered = [...loops].sort(compareLoops);
  const active = ordered.filter((loop) => !CLOSED_STATES.has(loop.status));
  const closed = ordered.filter((loop) => CLOSED_STATES.has(loop.status));
  return (
    <div className="space-y-3">
      {active.map((loop) => (
        <OpenLoopCard
          key={loop.id}
          loop={loop}
          workspaceId={workspaceId}
          onOpenFocus={onOpenFocus}
          onUpdate={onUpdate}
          updating={updating}
        />
      ))}
      {showClosed && closed.length ? (
        <details className="rounded-lg border border-slate-200 bg-slate-50 dark:border-neutral-800 dark:bg-black">
          <summary className="cursor-pointer list-none p-3 text-xs font-black text-slate-600 [&::-webkit-details-marker]:hidden dark:text-neutral-300">
            Closed · {closed.length}
          </summary>
          <div className="space-y-2 border-t border-slate-200 p-3 dark:border-neutral-800">
            {closed.map((loop) => (
              <OpenLoopCard key={loop.id} loop={loop} workspaceId={workspaceId} onOpenFocus={onOpenFocus} />
            ))}
          </div>
        </details>
      ) : null}
    </div>
  );
}

function OpenLoopCard({ loop, workspaceId, onOpenFocus, onUpdate, updating = false }) {
  const [action, setAction] = useState(null);
  const [reason, setReason] = useState("");
  const [assignee, setAssignee] = useState("");
  const [error, setError] = useState(null);
  const active = !CLOSED_STATES.has(loop.status);
  const critical = loop.severity === "critical";
  const focusId = loop.focus_component_id || loop.component_id;
  const label = loop.title || loop.explanation || "Unresolved project finding";

  const submit = async (event) => {
    event.preventDefault();
    const cleanReason = reason.trim();
    if (!cleanReason) {
      setError("A reason is required so this decision remains auditable.");
      return;
    }
    const cleanAssignee = assignee.trim();
    if (action === "assign" && !cleanAssignee) {
      setError("An assignee is required.");
      return;
    }
    setError(null);
    try {
      await onUpdate?.({
        loopId: loop.id,
        action,
        reason: cleanReason,
        ...(action === "assign" ? { assignee: cleanAssignee } : {}),
      });
      setAction(null);
      setReason("");
      setAssignee("");
    } catch (updateError) {
      setError(updateError?.message || "Could not update this open loop.");
    }
  };

  return (
    <article data-open-loop-state={loop.status || "open"} className={`rounded-lg border p-3 ${!active ? "border-slate-200 bg-white dark:border-neutral-800 dark:bg-[#07080a]" : critical ? "border-red-200 bg-red-50 dark:border-red-900/60 dark:bg-red-950/25" : "border-amber-200 bg-amber-50 dark:border-amber-900/60 dark:bg-amber-950/25"}`}>
      <div className="flex items-start gap-2">
        <AlertTriangle className={`mt-0.5 h-4 w-4 shrink-0 ${critical && active ? "text-red-600" : "text-amber-600"}`} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <p className="text-xs font-black text-slate-950 dark:text-white">{label}</p>
            <span className="rounded-full bg-white/70 px-2 py-0.5 text-[9px] font-black uppercase text-slate-500 dark:bg-black/30 dark:text-neutral-300">{formatState(loop.status || "open")}</span>
          </div>
          {loop.explanation && loop.explanation !== label ? <p className="mt-1 text-xs leading-5 text-slate-700 dark:text-neutral-300">{loop.explanation}</p> : null}
          {loop.next_action ? <p className="mt-1 text-[10px] font-semibold text-slate-500 dark:text-neutral-400">{loop.next_action}</p> : null}
          {loop.last_seen_at ? <p className="mt-1 text-[9px] font-semibold text-slate-400">Last observed {formatDate(loop.last_seen_at)}</p> : null}
          {loop.assigned_to ? <p className="mt-1 text-[9px] font-black text-slate-500 dark:text-neutral-300">Assigned to {loop.assigned_to}</p> : null}
          {(loop.sources || []).map((source, index) => (
            <OpenLoopEvidence key={`${source.source_document_id || source.source_url || "source"}:${index}`} source={source} workspaceId={workspaceId} index={index} />
          ))}
          <div className="mt-2 flex flex-wrap items-center gap-3">
            {focusId && onOpenFocus ? <button type="button" onClick={() => onOpenFocus(focusId)} className="text-[10px] font-black text-slate-700 underline dark:text-neutral-200">Open task</button> : null}
            {active && onUpdate ? (
              <>
                <button type="button" onClick={() => { setAction("resolve"); setReason(""); setError(null); }} className="text-[10px] font-black text-emerald-800 underline dark:text-emerald-300">Resolve</button>
                <button type="button" onClick={() => { setAction("dismiss"); setReason(""); setError(null); }} className="text-[10px] font-black text-slate-600 underline dark:text-neutral-300">Dismiss</button>
                <button type="button" onClick={() => { setAction("assign"); setReason(""); setAssignee(loop.assigned_to || ""); setError(null); }} className="text-[10px] font-black text-slate-600 underline dark:text-neutral-300">Assign</button>
              </>
            ) : null}
          </div>
          {action ? (
            <form onSubmit={submit} className="mt-3 rounded-md border border-slate-200 bg-white/80 p-2 dark:border-neutral-800 dark:bg-black/30">
              <label htmlFor={`open-loop-reason-${loop.id}`} className="block text-[10px] font-black text-slate-700 dark:text-neutral-200">
                Reason for {action === "resolve" ? "resolving" : action === "dismiss" ? "dismissing" : "assigning"}
              </label>
              {action === "assign" ? (
                <input
                  aria-label="Assignee"
                  value={assignee}
                  onChange={(event) => setAssignee(event.target.value)}
                  placeholder="Name or handle"
                  autoFocus
                  className="mt-1.5 h-8 w-full rounded-md border border-slate-200 bg-white px-2 text-xs outline-none focus:border-slate-500 dark:border-neutral-700 dark:bg-neutral-950"
                />
              ) : null}
              <input
                id={`open-loop-reason-${loop.id}`}
                value={reason}
                onChange={(event) => setReason(event.target.value)}
                autoFocus={action !== "assign"}
                className="mt-1.5 h-8 w-full rounded-md border border-slate-200 bg-white px-2 text-xs outline-none focus:border-slate-500 dark:border-neutral-700 dark:bg-neutral-950"
              />
              {error ? <p role="alert" className="mt-1.5 text-[10px] font-semibold text-red-600 dark:text-red-300">{error}</p> : null}
              <div className="mt-2 flex gap-2">
                <button type="submit" disabled={updating} className="rounded-md bg-slate-950 px-2.5 py-1.5 text-[10px] font-black text-white disabled:opacity-50 dark:bg-[#d9ff68] dark:text-[#171713]">
                  {updating ? "Saving…" : action === "resolve" ? "Confirm resolve" : action === "dismiss" ? "Confirm dismiss" : "Confirm assign"}
                </button>
                <button type="button" onClick={() => { setAction(null); setError(null); }} className="px-2 py-1.5 text-[10px] font-black text-slate-500">Cancel</button>
              </div>
            </form>
          ) : null}
        </div>
      </div>
    </article>
  );
}

function PlaybookReviewList({ playbooks, loading, onUpdate, updating }) {
  const pending = (playbooks || []).filter((item) => item.status === "pending_review");
  if (loading && !pending.length) {
    return <p className="mb-3 flex items-center gap-2 text-xs font-semibold text-slate-500"><Loader2 className="h-3.5 w-3.5 animate-spin" />Checking reusable agent steps…</p>;
  }
  if (!pending.length) return null;
  return (
    <section aria-labelledby="playbook-review-title" className="mb-4 rounded-lg border border-emerald-200 bg-emerald-50/60 p-3 dark:border-emerald-900/60 dark:bg-emerald-950/20">
      <h3 id="playbook-review-title" className="text-xs font-black text-slate-950 dark:text-white">Reusable agent steps to review</h3>
      <p className="mt-1 text-[10px] font-semibold text-slate-500 dark:text-neutral-400">Only verified runs appear here. Approve a playbook before it can guide another agent.</p>
      <div className="mt-3 space-y-2">
        {pending.map((playbook) => (
          <PlaybookReviewCard key={playbook.id} playbook={playbook} onUpdate={onUpdate} updating={updating} />
        ))}
      </div>
    </section>
  );
}

function PlaybookReviewCard({ playbook, onUpdate, updating }) {
  const [action, setAction] = useState(null);
  const [reason, setReason] = useState("");
  const [error, setError] = useState(null);
  const steps = playbook.ordered_steps || playbook.steps || [];
  const submit = async (event) => {
    event.preventDefault();
    const cleanReason = reason.trim();
    if (!cleanReason) {
      setError("A reason is required so approval remains auditable.");
      return;
    }
    setError(null);
    try {
      await onUpdate?.({ playbookId: playbook.id, action, reason: cleanReason });
      setAction(null);
      setReason("");
    } catch (updateError) {
      setError(updateError?.message || "Could not update this playbook.");
    }
  };
  return (
    <article className="rounded-md border border-emerald-200 bg-white p-2.5 dark:border-emerald-900/60 dark:bg-black/30">
      <p className="text-xs font-black text-slate-900 dark:text-white">{playbook.title || playbook.objective_pattern || "Verified task procedure"}</p>
      <p className="mt-1 text-[9px] font-semibold text-slate-500">Verified from {Number(playbook.successful_run_count || playbook.verified_run_count || 1)} successful run</p>
      {steps.length ? <p className="mt-1 line-clamp-2 text-[10px] leading-4 text-slate-600 dark:text-neutral-300">{steps.slice(0, 2).map((step) => typeof step === "string" ? step : step.summary || step.action).filter(Boolean).join(" → ")}</p> : null}
      {onUpdate ? <div className="mt-2 flex gap-3"><button type="button" onClick={() => setAction("approve")} className="text-[10px] font-black text-emerald-800 underline dark:text-emerald-300">Approve</button><button type="button" onClick={() => setAction("disable")} className="text-[10px] font-black text-slate-600 underline dark:text-neutral-300">Disable</button></div> : null}
      {action ? (
        <form onSubmit={submit} className="mt-2">
          <label htmlFor={`playbook-reason-${playbook.id}`} className="block text-[10px] font-black">Reason for {action === "approve" ? "approving" : "disabling"}</label>
          <input id={`playbook-reason-${playbook.id}`} value={reason} onChange={(event) => setReason(event.target.value)} autoFocus className="mt-1.5 h-8 w-full rounded-md border border-slate-200 bg-white px-2 text-xs dark:border-neutral-700 dark:bg-neutral-950" />
          {error ? <p role="alert" className="mt-1 text-[10px] font-semibold text-red-600">{error}</p> : null}
          <div className="mt-2 flex gap-2"><button type="submit" disabled={updating} className="rounded bg-slate-950 px-2 py-1 text-[10px] font-black text-white disabled:opacity-50 dark:bg-[#d9ff68] dark:text-[#171713]">{updating ? "Saving…" : `Confirm ${action}`}</button><button type="button" onClick={() => setAction(null)} className="text-[10px] font-black text-slate-500">Cancel</button></div>
        </form>
      ) : null}
    </article>
  );
}

function OpenLoopEvidence({ source, workspaceId, index }) {
  const [open, setOpen] = useState(false);
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  if (source.source_url) {
    return <a href={source.source_url} target="_blank" rel="noreferrer" className="mt-2 inline-flex items-center gap-1 text-[10px] font-black text-slate-600 underline dark:text-neutral-300"><ExternalLink className="h-3 w-3" />View evidence {index + 1}</a>;
  }
  if (!source.source_document_id) return source.excerpt ? <p className="mt-2 text-[9px] font-semibold text-slate-500">{source.excerpt}</p> : null;

  const toggle = async () => {
    if (open) {
      setOpen(false);
      return;
    }
    setOpen(true);
    if (detail || loading) return;
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (workspaceId) params.set("workspace_id", workspaceId);
      setDetail(await api.get(`/sources/${source.source_document_id}${params.size ? `?${params}` : ""}`));
    } catch (sourceError) {
      setError(sourceError?.message || "Evidence is unavailable.");
    } finally {
      setLoading(false);
    }
  };
  return (
    <div className="mt-2">
      {source.excerpt ? <p className="text-[9px] font-semibold text-slate-500 dark:text-neutral-400">{source.excerpt}</p> : null}
      <button type="button" onClick={toggle} className="mt-1 inline-flex items-center gap-1 text-[10px] font-black text-slate-600 underline dark:text-neutral-300"><FileText className="h-3 w-3" />{open ? "Hide evidence" : `View evidence ${index + 1}`}</button>
      {open ? <div className="mt-2 rounded border border-slate-200 bg-white p-2 dark:border-neutral-800 dark:bg-neutral-950">{loading ? <p className="text-[10px] font-semibold text-slate-400">Loading evidence…</p> : error ? <p className="text-[10px] font-semibold text-red-600">{error}</p> : <pre className="max-h-40 overflow-auto whitespace-pre-wrap break-words font-mono text-[10px] leading-4 text-slate-600 dark:text-neutral-300">{detail?.content || "No source content available."}</pre>}</div> : null}
    </div>
  );
}

function loopItems(data) {
  if (Array.isArray(data)) return data;
  return Array.isArray(data?.items) ? data.items : [];
}

function compareLoops(left, right) {
  const severity = { critical: 0, warning: 1, info: 2 };
  const severityDiff = (severity[left.severity] ?? 3) - (severity[right.severity] ?? 3);
  if (severityDiff) return severityDiff;
  return String(right.last_seen_at || "").localeCompare(String(left.last_seen_at || ""));
}

function formatState(value) {
  return String(value || "").replaceAll("_", " ");
}

function formatDate(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString();
}
