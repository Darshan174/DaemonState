import { useEffect, useRef, useState } from "react";
import { ExternalLink, FileText, GitBranch, Loader2, ShieldCheck, X } from "lucide-react";
import { api } from "../../api/client";
import {
  STATUS_META,
  TONE_CLASSES,
  cardRelationships,
  cleanDisplayText,
  confidenceLabel,
  sessionIdentity,
} from "../digest";

export default function ContextInspector({ card, cards = [], links = [], workspaceId, onClose }) {
  const panelRef = useRef(null);
  const [sourceDetail, setSourceDetail] = useState(null);
  const [sourceLoading, setSourceLoading] = useState(false);
  const [sourceError, setSourceError] = useState(null);
  const relationships = cardRelationships(card, cards, links);
  const sourceId = card?.provenance?.[0]?.source_document_id || card?.source_ids?.[0];

  useEffect(() => {
    setSourceDetail(null);
    setSourceError(null);
    if (!sourceId) {
      setSourceLoading(false);
      return undefined;
    }

    let active = true;
    setSourceLoading(true);
    const params = new URLSearchParams();
    if (workspaceId) params.set("workspace_id", workspaceId);
    api.get(`/sources/${sourceId}${params.size ? `?${params}` : ""}`)
      .then((detail) => {
        if (active) setSourceDetail(detail);
      })
      .catch((error) => {
        if (active) setSourceError(error?.message || "Source content is unavailable.");
      })
      .finally(() => {
        if (active) setSourceLoading(false);
      });
    return () => { active = false; };
  }, [sourceId, workspaceId]);

  useEffect(() => {
    if (card) panelRef.current?.querySelector('[aria-label="Close inspector"]')?.focus();
  }, [card?.id]);

  const handleDialogKeyDown = (event) => {
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
  };

  if (!card) {
    return (
      <aside className="hidden w-[360px] shrink-0 border-l border-slate-200 bg-white p-4 dark:border-neutral-800 dark:bg-[#07080a] lg:block">
        <div className="flex h-full items-center justify-center rounded-lg border border-dashed border-slate-200 text-center text-sm font-semibold text-slate-400 dark:border-neutral-800 dark:text-neutral-500">
          Select a card
        </div>
      </aside>
    );
  }

  const status = STATUS_META[card.status] || STATUS_META.active;
  const inspectorTitle = inspectorHeading(card);

  return (
    <aside ref={panelRef} role="dialog" aria-modal="true" aria-labelledby="context-inspector-title" onKeyDown={handleDialogKeyDown} className="flex min-h-0 w-full shrink-0 flex-col border-l border-slate-200 bg-white dark:border-neutral-800 dark:bg-[#07080a]">
      <div className="border-b border-slate-200 p-4 dark:border-neutral-800">
        <div className="mb-3 flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 id="context-inspector-title" className="line-clamp-2 text-base font-black text-slate-950 dark:text-white">
              {inspectorTitle}
            </h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-slate-400 transition hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-black dark:hover:text-white"
            aria-label="Close inspector"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="flex flex-wrap gap-1.5">
          <span className={`rounded-md border px-1.5 py-1 text-[10px] font-bold ${TONE_CLASSES[status.tone] || TONE_CLASSES.gray}`}>
            {status.label}
          </span>
          <span className="rounded-md border border-slate-200 bg-slate-50 px-1.5 py-1 text-[10px] font-bold text-slate-600 dark:border-neutral-800 dark:bg-black dark:text-neutral-300">
            {confidenceLabel(card.confidence)} confidence
          </span>
          {relationships.length ? (
            <span className="rounded-md border border-slate-200 bg-slate-50 px-1.5 py-1 text-[10px] font-bold text-slate-600 dark:border-neutral-800 dark:bg-black dark:text-neutral-300">
              {relationships.length} {relationships.length === 1 ? "connection" : "connections"}
            </span>
          ) : null}
        </div>
      </div>

      <div className="min-h-0 flex-1 space-y-6 overflow-y-auto p-4">
        <SummaryTab card={card} />
        <InspectorSection title="Evidence">
          <EvidenceTab card={card} sourceDetail={sourceDetail} loading={sourceLoading} error={sourceError} />
        </InspectorSection>
        {relationships.length ? (
          <InspectorSection title="Connections">
            <RelationshipsTab relationships={relationships} />
          </InspectorSection>
        ) : null}
      </div>
    </aside>
  );
}

function SummaryTab({ card }) {
  const summary = displaySummary(card);
  const title = cleanDisplayText(card.title);
  const showSummary = Boolean(summary && summary.toLowerCase() !== title.toLowerCase());
  if (!showSummary && !card.session && !card.remote_item) return null;
  return (
    <div className="space-y-4">
      {showSummary ? (
        <InspectorBlock label="Summary">
          <p>{summary}</p>
        </InspectorBlock>
      ) : null}
      {card.session ? <SessionFacts session={card.session} relevance={card.workspace_relevance} /> : null}
      {card.remote_item ? <RemoteFacts remote={card.remote_item} freshness={card.freshness || card.source_snapshot} /> : null}
    </div>
  );
}

function EvidenceTab({ card, sourceDetail, loading, error }) {
  const provenance = card.provenance || [];
  return (
    <div className="space-y-3">
      {provenance.map((source, index) => {
        const excerpt = cleanDisplayText(source.excerpt);
        return (
          <div
            key={`${source.source_label}:${index}`}
            className="rounded-lg border border-slate-200 bg-white p-3 dark:border-neutral-800 dark:bg-black"
          >
            <div className="mb-2 flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="text-[10px] font-bold uppercase text-slate-400">{source.source_type}</p>
                <p className="mt-0.5 truncate text-xs font-bold text-slate-900 dark:text-white">
                  {source.source_label}
                </p>
                <p className="mt-1 text-[10px] font-semibold text-slate-400">
                  Revision {source.revision_number || card.source_snapshot?.revision_number || "unknown"} · {formatStatus(source.verification_status || card.evidence?.verification_status || "verification unknown")}
                </p>
              </div>
              {source.source_url ? (
                <a
                  href={source.source_url}
                  target="_blank"
                  rel="noreferrer"
                  className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md border border-slate-200 text-slate-500 transition hover:bg-slate-50 hover:text-slate-900 dark:border-neutral-800 dark:text-neutral-300 dark:hover:bg-neutral-900 dark:hover:text-white"
                  aria-label="Open source"
                >
                  <ExternalLink className="h-3.5 w-3.5" />
                </a>
              ) : null}
            </div>
            {excerpt ? (
              <p className="rounded-md bg-slate-50 px-2 py-2 text-xs leading-5 text-slate-600 dark:bg-neutral-950 dark:text-neutral-300">
                {excerpt}
              </p>
            ) : (
              <p className="text-xs font-semibold text-slate-400">No excerpt available.</p>
            )}
          </div>
        );
      })}
      <details className="group rounded-lg border border-slate-200 bg-slate-50 dark:border-neutral-800 dark:bg-black">
        <summary className="flex cursor-pointer list-none items-center gap-2 p-3 text-[10px] font-bold uppercase text-slate-500 marker:hidden dark:text-neutral-400">
          <FileText className="h-3.5 w-3.5" />
          Imported source
        </summary>
        <div className="border-t border-slate-200 p-3 dark:border-neutral-800">
          {loading ? (
            <p className="flex items-center gap-2 text-xs font-semibold text-slate-500"><Loader2 className="h-3.5 w-3.5 animate-spin" />Loading source…</p>
          ) : error ? (
            <p className="text-xs font-semibold text-red-600 dark:text-red-400">{error}</p>
          ) : sourceDetail?.content ? (
            <pre className="max-h-80 overflow-auto whitespace-pre-wrap break-words rounded-md bg-white p-3 font-mono text-[11px] leading-5 text-slate-700 dark:bg-neutral-950 dark:text-neutral-300">{sourceDetail.content}</pre>
          ) : (
            <p className="text-xs font-semibold text-slate-400">No source content is available for this card.</p>
          )}
        </div>
      </details>
    </div>
  );
}

function SessionFacts({ session, relevance }) {
  const facts = [
    ["Session ID", session.session_id],
    ["Tool", session.tool],
    ["Model", session.model],
    ["Started", formatDate(session.started_at)],
    ["Ended", formatDate(session.ended_at)],
    ["Messages", session.message_count],
    ["Branch", session.branch],
    ["Repository / cwd", session.repository || session.cwd],
    ["Workspace relevance", relevance?.status || "unknown"],
  ].filter(([, value]) => value !== null && value !== undefined && value !== "");
  return (
    <div className="space-y-3">
      <FactGrid label="Imported session" facts={facts} />
      {relevance?.reasons?.length ? (
        <InspectorBlock label="Project relevance">
          <ul className="space-y-1">
            {relevance.reasons.map((reason) => <li key={reason}>{reason}</li>)}
          </ul>
        </InspectorBlock>
      ) : null}
    </div>
  );
}

function RemoteFacts({ remote, freshness }) {
  const facts = [
    ["Repository", remote.repository || remote.repo_full_name],
    ["Number", remote.number],
    ["Observed state", remote.observed_status || remote.provider_state || freshness?.observed_status || freshness?.provider_state],
    ["Provider updated", formatDate(remote.provider_updated_at || freshness?.provider_updated_at)],
    ["Last successful sync", formatDate(freshness?.last_successful_sync_at)],
    ["Freshness", freshness?.status || freshness?.freshness || "unknown"],
  ].filter(([, value]) => value !== null && value !== undefined && value !== "");
  return <FactGrid label="Provider snapshot" facts={facts} />;
}

function FactGrid({ label, facts }) {
  return (
    <section>
      <p className="mb-2 text-[10px] font-bold uppercase text-slate-400">{label}</p>
      <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-md border border-slate-200 bg-slate-200 dark:border-neutral-800 dark:bg-neutral-800">
        {facts.map(([name, value]) => (
          <div key={name} className="bg-white p-2 dark:bg-black">
            <dt className="text-[9px] font-bold uppercase text-slate-400">{name}</dt>
            <dd className="mt-1 break-words text-xs font-semibold text-slate-700 dark:text-neutral-300">{value ?? "Unknown"}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

function formatDate(value) {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString();
}

function RelationshipsTab({ relationships }) {
  if (!relationships.length) {
    return (
      <div className="rounded-lg border border-dashed border-slate-200 p-5 text-center text-xs font-semibold text-slate-400 dark:border-neutral-800 dark:text-neutral-500">
        No visible relationships.
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {relationships.map((relationship) => (
        <div
          key={relationship.id}
          className="rounded-lg border border-slate-200 bg-white p-3 dark:border-neutral-800 dark:bg-black"
        >
          <div className="flex items-center gap-2">
            <GitBranch className="h-3.5 w-3.5 shrink-0 text-slate-400" />
            <p className="min-w-0 truncate text-xs font-bold text-slate-900 dark:text-white">
              {relationship.label}
            </p>
          </div>
          <p className="mt-2 line-clamp-2 text-xs leading-5 text-slate-500 dark:text-neutral-400">
            {relationship.direction === "out" ? "To" : "From"}: {cleanDisplayText(relationship.otherCard?.title) || "Hidden card"}
          </p>
          <div className="mt-2 flex items-center gap-2 text-[10px] font-bold text-slate-400">
            <ShieldCheck className="h-3 w-3" />
            {confidenceLabel(relationship.confidence)} confidence
          </div>
        </div>
      ))}
    </div>
  );
}

function InspectorBlock({ label, children }) {
  return (
    <section>
      <p className="mb-1 text-[10px] font-bold uppercase text-slate-400">{label}</p>
      <div className="text-sm leading-6 text-slate-700 dark:text-neutral-300">
        {children}
      </div>
    </section>
  );
}

function InspectorSection({ title, children }) {
  return (
    <section className="border-t border-slate-200 pt-5 dark:border-neutral-800">
      <h3 className="mb-3 text-[10px] font-black uppercase tracking-[0.16em] text-slate-400">{title}</h3>
      {children}
    </section>
  );
}

function sentenceCase(value) {
  return value ? `${value.charAt(0).toUpperCase()}${value.slice(1)}` : "";
}

function inspectorHeading(card) {
  if (card?.session) return sessionIdentity(card).title;
  if (card?.remote_item) {
    const kind = card.remote_item.kind === "pull_request" ? "PR" : "Issue";
    const identity = card.remote_item.number ? `${kind} #${card.remote_item.number}` : kind;
    const title = cleanDisplayText(card.remote_item.title);
    return title ? `${identity} · ${title}` : identity;
  }
  return sentenceCase(cleanDisplayText(card?.title)) || "Untitled record";
}

function displaySummary(card) {
  let summary = cleanDisplayText(card?.summary);
  const remoteTitle = cleanDisplayText(card?.remote_item?.title);
  if (remoteTitle) {
    const titleIndex = summary.toLowerCase().indexOf(remoteTitle.toLowerCase());
    if (titleIndex >= 0) summary = summary.slice(titleIndex + remoteTitle.length);
    summary = summary
      .replace(/^\s*State\s*:\s*\S+\s*/i, "")
      .replace(/^\s*Labels\s*:\s*none\s*/i, "")
      .trim();
    const firstSentence = summary.split(/(?<=[.!?])\s+/).find(Boolean);
    if (firstSentence) summary = firstSentence;
  }
  return summary;
}

function formatStatus(value) {
  return String(value || "").replaceAll("_", " ");
}
