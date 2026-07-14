import { useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  Check,
  Clipboard,
  ExternalLink,
  FileText,
  GitBranch,
  Loader2,
  ShieldCheck,
  X,
} from "lucide-react";
import { api } from "../../api/client";
import {
  STATUS_META,
  TONE_CLASSES,
  cardRelationships,
  cleanDisplayText,
  confidenceLabel,
  sessionIdentity,
} from "../digest";

export default function ContextInspector({
  card,
  cards = [],
  links = [],
  workspaceId,
  onClose,
  canPrepareForAgent = false,
  onPrepareForAgent,
  preparing = false,
  prepareError = null,
  timeline = null,
  timelineLoading = false,
  timelineError = null,
  onRetryTimeline,
}) {
  const panelRef = useRef(null);
  const [sourceDetail, setSourceDetail] = useState(null);
  const [sourceLoading, setSourceLoading] = useState(false);
  const [sourceError, setSourceError] = useState(null);
  const [prepareStatus, setPrepareStatus] = useState("idle");
  const [preparedMarkdown, setPreparedMarkdown] = useState(null);
  const [preparedAffectedCode, setPreparedAffectedCode] = useState(null);
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
    setPrepareStatus("idle");
    setPreparedMarkdown(null);
    setPreparedAffectedCode(null);
  }, [card?.id]);

  const prepareForAgent = async () => {
    if (preparedMarkdown) {
      try {
        await copyText(preparedMarkdown);
        setPrepareStatus("copied");
      } catch {
        setPrepareStatus("ready");
      }
      return;
    }
    try {
      setPrepareStatus("preparing");
      const result = await onPrepareForAgent?.();
      const markdown = result?.markdown || "";
      setPreparedMarkdown(markdown);
      setPreparedAffectedCode(result?.manifest?.affected_code || null);
      try {
        await copyText(markdown);
        setPrepareStatus("copied");
      } catch {
        setPrepareStatus("ready");
      }
    } catch {
      setPrepareStatus("error");
    }
  };

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
  const affectedCode = preparedMarkdown !== null
    ? preparedAffectedCode
    : timeline?.affected_code || null;

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
        {canPrepareForAgent ? (
          <button
            type="button"
            onClick={prepareForAgent}
            disabled={preparing || prepareStatus === "preparing"}
            className="mt-3 inline-flex h-9 w-full items-center justify-center gap-2 rounded-md bg-slate-950 px-3 text-xs font-black text-white transition hover:bg-slate-800 disabled:opacity-60 dark:bg-[#d9ff68] dark:text-[#171713]"
          >
            {preparing || prepareStatus === "preparing" ? <Loader2 className="h-4 w-4 animate-spin" /> : prepareStatus === "copied" ? <Check className="h-4 w-4" /> : <Clipboard className="h-4 w-4" />}
            {preparing || prepareStatus === "preparing" ? "Preparing" : prepareStatus === "copied" ? "Agent pack copied" : prepareStatus === "ready" ? "Pack ready — retry copy" : "Prepare for agent"}
          </button>
        ) : null}
        {prepareStatus === "ready" ? (
          <p className="mt-2 text-xs font-semibold text-slate-500 dark:text-neutral-400">The pack is prepared, but clipboard access was unavailable. Select the action again to retry copying.</p>
        ) : null}
        {(prepareStatus === "error" || prepareError) ? (
          <p role="alert" className="mt-2 text-xs font-semibold text-red-600 dark:text-red-400">
            {prepareError?.message || "Could not prepare and copy this source-backed task."}
          </p>
        ) : null}
      </div>

      <div className="min-h-0 flex-1 space-y-6 overflow-y-auto p-4">
        <SummaryTab card={card} />
        {affectedCode?.files?.length ? <AffectedCode affectedCode={affectedCode} /> : null}
        {canPrepareForAgent ? (
          <InspectorSection title="Agent runs">
            <RunTimeline
              timeline={timeline}
              workspaceId={workspaceId}
              loading={timelineLoading}
              error={timelineError}
              onRetry={onRetryTimeline}
            />
          </InspectorSection>
        ) : null}
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

function AffectedCode({ affectedCode }) {
  const files = affectedCode.files || [];
  const linkedTests = new Map();
  files.forEach((file) => {
    if (file.role === "related_test") linkedTests.set(file.path, file);
    (file.related_tests || []).forEach((test) => linkedTests.set(test.path, test));
  });
  const likelyFileCount = files.filter((file) => file.role !== "related_test").length;
  const snapshot = affectedCode.snapshot || {};
  const snapshotNote = snapshot.dirty
    ? snapshot.head_commit
      ? `Based on HEAD ${shortCommit(snapshot.head_commit)} with local changes`
      : "Based on the current local files"
    : snapshot.head_commit
      ? `Indexed at commit ${shortCommit(snapshot.head_commit)}`
      : "Based on the current local files";

  return (
    <details className="group rounded-lg border border-slate-200 bg-slate-50 dark:border-neutral-800 dark:bg-black">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 p-3 [&::-webkit-details-marker]:hidden">
        <span className="flex min-w-0 items-center gap-2 text-xs font-black text-slate-900 dark:text-white">
          <FileText className="h-3.5 w-3.5 shrink-0" />
          Affected code
        </span>
        <span className="text-right text-[10px] font-bold text-slate-500 dark:text-neutral-400">
          {likelyFileCount} likely {likelyFileCount === 1 ? "file" : "files"}
          {linkedTests.size ? ` · ${linkedTests.size} linked ${linkedTests.size === 1 ? "test" : "tests"}` : ""}
        </span>
      </summary>
      <div className="space-y-3 border-t border-slate-200 p-3 dark:border-neutral-800">
        <p className="flex items-center gap-1.5 text-[10px] font-semibold text-slate-500 dark:text-neutral-400">
          <GitBranch className="h-3 w-3 shrink-0" />
          {snapshotNote}
        </p>
        <div className="space-y-2">
          {files.map((file) => (
            <AffectedFile key={file.path} file={file} />
          ))}
        </div>
      </div>
    </details>
  );
}

function AffectedFile({ file }) {
  return (
    <article className="min-w-0 rounded-md border border-slate-200 bg-white p-2.5 dark:border-neutral-800 dark:bg-[#07080a]">
      <p className="text-[9px] font-black uppercase tracking-wide text-slate-400">
        {file.role === "related_test" ? "Related test" : "Likely implementation"}
      </p>
      <p className="mt-1 break-all font-mono text-[10px] font-bold text-slate-800 dark:text-neutral-200">{file.path}</p>
      {file.why ? <p className="mt-1.5 text-[10px] font-semibold leading-4 text-slate-500 dark:text-neutral-400">{file.why}</p> : null}
      {file.line_ranges?.length ? (
        <p className="mt-1.5 font-mono text-[9px] font-semibold text-slate-400">
          {file.line_ranges.slice(0, 2).map((range) => (
            `lines ${range.start_line}${range.end_line && range.end_line !== range.start_line ? `–${range.end_line}` : ""}`
          )).join(" · ")}
        </p>
      ) : null}
      {file.impact_paths?.length ? (
        <div className="mt-2 space-y-1 border-t border-slate-100 pt-2 dark:border-neutral-900">
          {file.impact_paths.slice(0, 2).map((impact) => (
            <p key={(impact.paths || []).join("→")} className="break-all text-[9px] font-semibold leading-4 text-slate-400">
              {(impact.paths || []).join(" → ")}{impact.why ? ` · ${impact.why}` : ""}
            </p>
          ))}
        </div>
      ) : null}
      {file.related_tests?.length ? (
        <div className="mt-2 border-t border-slate-100 pt-2 dark:border-neutral-900">
          {file.related_tests.map((test) => (
            <div key={test.path} className="mt-1 first:mt-0">
              <p className="break-all font-mono text-[10px] font-bold text-slate-700 dark:text-neutral-300">{test.path}</p>
              {test.why ? <p className="mt-0.5 text-[9px] font-semibold leading-4 text-slate-400">{test.why}</p> : null}
            </div>
          ))}
        </div>
      ) : null}
    </article>
  );
}

function shortCommit(value) {
  return String(value || "").slice(0, 7);
}

function RunTimeline({ timeline, workspaceId, loading, error, onRetry }) {
  if (loading) {
    return <p className="flex items-center gap-2 text-xs font-semibold text-slate-500"><Loader2 className="h-3.5 w-3.5 animate-spin" />Loading observed runs…</p>;
  }
  if (error) {
    return (
      <div role="alert" className="rounded-md border border-red-200 bg-red-50 p-3 dark:border-red-900/60 dark:bg-red-950/30">
        <p className="text-xs font-semibold text-red-700 dark:text-red-300">{error?.message || "Run history is unavailable."}</p>
        <button type="button" onClick={onRetry} className="mt-2 text-xs font-black text-red-800 underline dark:text-red-200">Retry</button>
      </div>
    );
  }
  if (!timeline?.runs?.length) {
    return <p className="rounded-md border border-dashed border-slate-200 p-3 text-xs font-semibold text-slate-400 dark:border-neutral-800">No observed agent run yet.</p>;
  }
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-3">
        <span className={`rounded-full px-2 py-1 text-[10px] font-black ${timelineStateTone(timeline.state)}`}>
          {formatStatus(timeline.state || "unknown")}
        </span>
        {timeline.latest_outcome?.summary ? <p className="line-clamp-1 text-[10px] font-semibold text-slate-500">{timeline.latest_outcome.summary}</p> : null}
      </div>
      {(timeline.findings || []).map((finding) => (
        <FindingCard key={finding.id} finding={finding} workspaceId={workspaceId} />
      ))}
      {timeline.runs.map((run) => (
        <article key={run.run_id} className="rounded-lg border border-slate-200 bg-slate-50 p-3 dark:border-neutral-800 dark:bg-black">
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-xs font-black text-slate-900 dark:text-white">{run.tool || "Agent"} · {formatStatus(run.status || "unknown")}</p>
              <p className="mt-1 text-[10px] font-semibold text-slate-400">{formatDate(run.started_at) || "Start time unknown"}</p>
            </div>
            <span className={`rounded-full px-2 py-1 text-[9px] font-black ${timelineStateTone(run.state)}`}>{formatStatus(run.state || "unknown")}</span>
          </div>
          {run.base_commit || run.head_commit ? <p className="mt-2 break-all font-mono text-[10px] text-slate-500">{run.base_commit || "Unknown"} → {run.head_commit || "Unknown"}</p> : null}
          {run.events?.length ? (
            <ol className="mt-3 space-y-2 border-l border-slate-200 pl-3 dark:border-neutral-800">
              {run.events.map((event) => (
                <li key={event.event_key || event.run_observation_id}>
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-[10px] font-black uppercase text-slate-500">{formatStatus(event.event_type)}</p>
                    <span className="text-[9px] font-semibold text-slate-400">{formatDate(event.observed_at)}</span>
                  </div>
                  <p className="mt-1 text-xs leading-5 text-slate-600 dark:text-neutral-300">{event.summary || "No summary recorded."}</p>
                  {event.command ? <p className="mt-1 break-words rounded bg-white px-2 py-1 font-mono text-[10px] text-slate-600 dark:bg-neutral-950 dark:text-neutral-300">{event.command}{Number.isInteger(event.exit_code) ? ` · exit ${event.exit_code}` : ""}</p> : null}
                  {event.verification_results?.map((result, index) => (
                    <p key={`${result.requirement_id || result.command || "check"}:${index}`} className="mt-1 break-words rounded bg-white px-2 py-1 font-mono text-[10px] text-slate-600 dark:bg-neutral-950 dark:text-neutral-300">
                      {result.command || result.requirement_id || "Recorded check"} · {formatStatus(result.status || "unknown")}{Number.isInteger(result.exit_code) ? ` · exit ${result.exit_code}` : ""}
                    </p>
                  ))}
                  <SourceEvidenceButton
                    sourceDocumentId={event.source_document_id}
                    sourceUrl={event.source_url}
                    workspaceId={workspaceId}
                  />
                </li>
              ))}
            </ol>
          ) : <p className="mt-3 text-xs font-semibold text-slate-400">No durable timeline events yet.</p>}
        </article>
      ))}
    </div>
  );
}

function FindingCard({ finding, workspaceId }) {
  const [copied, setCopied] = useState(false);
  const sources = finding.sources || [];
  const critical = finding.severity === "critical";
  const sourceRefs = sources
    .map((source) => source?.source_url || source?.source_document_id)
    .filter(Boolean)
    .join(", ") || "unknown";
  const challenge = `${finding.title}. ${finding.explanation} ${finding.next_action} Show the supporting result or correct the completion claim. Sources: ${sourceRefs}.`;
  const copyChallenge = async () => {
    await copyText(challenge);
    setCopied(true);
  };
  return (
    <div data-severity={finding.severity || "warning"} className={`rounded-lg border p-3 ${critical ? "border-red-200 bg-red-50 dark:border-red-900/60 dark:bg-red-950/25" : "border-amber-200 bg-amber-50 dark:border-amber-900/60 dark:bg-amber-950/25"}`}>
      <div className="flex items-start gap-2">
        <AlertTriangle className={`mt-0.5 h-4 w-4 shrink-0 ${critical ? "text-red-600" : "text-amber-600"}`} />
        <div className="min-w-0 flex-1">
          <p className={`text-xs font-black ${critical ? "text-red-950 dark:text-red-100" : "text-amber-950 dark:text-amber-100"}`}>{finding.title}</p>
          <p className={`mt-1 text-xs leading-5 ${critical ? "text-red-900/80 dark:text-red-200/80" : "text-amber-900/80 dark:text-amber-200/80"}`}>{finding.explanation}</p>
          <p className={`mt-1 text-[10px] font-semibold ${critical ? "text-red-800 dark:text-red-300" : "text-amber-800 dark:text-amber-300"}`}>{finding.next_action}</p>
          <button type="button" onClick={copyChallenge} className={`mt-2 inline-flex items-center gap-1 text-[10px] font-black underline ${critical ? "text-red-900 dark:text-red-100" : "text-amber-900 dark:text-amber-100"}`}>
            {copied ? <Check className="h-3 w-3" /> : <Clipboard className="h-3 w-3" />}{copied ? "Challenge copied" : "Challenge agent"}
          </button>
          {sources.map((source, index) => (
            <div key={`${source?.source_document_id || source?.source_url || "source"}:${index}`} className="mt-2">
              {source?.excerpt ? <p className="text-[9px] font-semibold text-slate-500 dark:text-neutral-400">{source.excerpt}</p> : null}
              <SourceEvidenceButton
                sourceDocumentId={source?.source_document_id}
                sourceUrl={source?.source_url}
                workspaceId={workspaceId}
                label={`View evidence ${index + 1}`}
              />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function SourceEvidenceButton({ sourceDocumentId, sourceUrl, workspaceId, label = "View source" }) {
  const [open, setOpen] = useState(false);
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  if (sourceUrl) {
    return <a href={sourceUrl} target="_blank" rel="noreferrer" className="mt-2 inline-flex items-center gap-1 text-[10px] font-black text-slate-600 underline dark:text-neutral-300"><ExternalLink className="h-3 w-3" />{label === "View source" ? "Open source" : label}</a>;
  }
  if (!sourceDocumentId) return null;

  const toggleSource = async () => {
    if (open) {
      setOpen(false);
      return;
    }
    setOpen(true);
    if (detail || loading) return;
    setLoading(true);
    setError(null);
    const params = new URLSearchParams();
    if (workspaceId) params.set("workspace_id", workspaceId);
    try {
      setDetail(await api.get(`/sources/${sourceDocumentId}${params.size ? `?${params}` : ""}`));
    } catch (sourceError) {
      setError(sourceError?.message || "Source content is unavailable.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <button type="button" onClick={toggleSource} className="mt-2 inline-flex items-center gap-1 text-[10px] font-black text-slate-600 underline dark:text-neutral-300">
        <FileText className="h-3 w-3" />{open ? `Hide ${label.toLowerCase().replace(/^view /, "")}` : label}
      </button>
      {open ? (
        <div className="mt-2 rounded border border-slate-200 bg-white p-2 dark:border-neutral-800 dark:bg-neutral-950">
          {loading ? <p className="text-[10px] font-semibold text-slate-400">Loading source…</p> : error ? <p className="text-[10px] font-semibold text-red-600">{error}</p> : <pre className="max-h-40 overflow-auto whitespace-pre-wrap break-words font-mono text-[10px] leading-4 text-slate-600 dark:text-neutral-300">{detail?.content || "No source content available."}</pre>}
        </div>
      ) : null}
    </div>
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

function timelineStateTone(state) {
  if (["verified"].includes(state)) return "bg-emerald-100 text-emerald-800 dark:bg-emerald-950/50 dark:text-emerald-200";
  if (["blocked", "verification_failed", "conflicting_evidence"].includes(state)) return "bg-red-100 text-red-800 dark:bg-red-950/50 dark:text-red-200";
  if (["verification_missing", "completed_unverified", "stale_source"].includes(state)) return "bg-amber-100 text-amber-800 dark:bg-amber-950/50 dark:text-amber-200";
  return "bg-slate-100 text-slate-600 dark:bg-neutral-900 dark:text-neutral-300";
}

async function copyText(value) {
  if (!value) throw new Error("Nothing to copy");
  if (!globalThis.navigator?.clipboard?.writeText) throw new Error("Clipboard is unavailable");
  let timeoutId;
  try {
    await Promise.race([
      globalThis.navigator.clipboard.writeText(value),
      new Promise((_, reject) => {
        timeoutId = globalThis.setTimeout(
          () => reject(new Error("Clipboard timed out")),
          2000,
        );
      }),
    ]);
  } finally {
    globalThis.clearTimeout(timeoutId);
  }
}
