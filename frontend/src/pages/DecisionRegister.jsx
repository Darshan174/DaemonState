import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import MockBadge from "../components/MockBadge";
import StatusView from "../components/StatusView";
import { useDecisionHistory, useDecisionRegister } from "../api/hooks";

const FILTERS = [
  { key: "all", label: "All decisions" },
  { key: "current", label: "Current" },
  { key: "needs_review", label: "Needs review" },
  { key: "historical", label: "Historical" },
];

export default function DecisionRegister() {
  const [searchParams, setSearchParams] = useSearchParams();
  const filter = searchParams.get("state") ?? "all";
  const sourceId = searchParams.get("source_id");
  const query = useDecisionRegister();
  const items = query.data ?? [];

  const sourceFilteredItems = useMemo(
    () => items.filter((item) => {
      if (!sourceId) return true;
      return item.sourceDocumentId === sourceId || item.rationaleSources?.some(s => s.sourceDocumentId === sourceId);
    }),
    [sourceId, items],
  );

  const filteredItems = useMemo(
    () => sourceFilteredItems.filter((item) => filter === "all" || item.status === filter),
    [filter, sourceFilteredItems],
  );

  if (query.isLoading || query.isError) {
    return (
      <div className="max-w-6xl mx-auto">
        <StatusView query={query} empty="No decisions available yet." />
      </div>
    );
  }

  if (!items.length) {
    return (
      <div className="max-w-6xl mx-auto">
        <DecisionEmptyState />
      </div>
    );
  }

  const summary = {
    current: sourceFilteredItems.filter((item) => item.status === "current").length,
    needsReview: sourceFilteredItems.filter((item) => item.status === "needs_review").length,
    historical: sourceFilteredItems.filter((item) => item.status === "historical").length,
  };

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-3">
            <h2 className="text-lg font-semibold text-gray-800 dark:text-gray-300">Decisions</h2>
            {query.isMock && <MockBadge />}
          </div>
          <p className="text-xs text-gray-400 mt-1">
            Source-backed operating decisions, with their linked facts, review state, and historical changes.
          </p>
        </div>
        <div className="flex items-center gap-3 text-xs">
          <Link to={sourceId ? `/app/changes?source_id=${sourceId}` : "/app/changes"} className="font-medium text-brand-700 dark:text-brand-400 hover:text-brand-800 dark:text-brand-300">
            Open timeline
          </Link>
          <Link to="/app/review" className="font-medium text-brand-700 dark:text-brand-400 hover:text-brand-800 dark:text-brand-300">
            Open review queue
          </Link>
          <Link to={sourceId ? `/app/sources/${sourceId}` : "/app/sources"} className="font-medium text-brand-700 dark:text-brand-400 hover:text-brand-800 dark:text-brand-300">
            Inspect sources
          </Link>
        </div>
      </div>

      <div className="grid gap-4 sm:grid-cols-3">
        <SummaryCard label="Current decisions" value={summary.current} tone="emerald" />
        <SummaryCard label="Needs review" value={summary.needsReview} tone="amber" />
        <SummaryCard label="Historical changes" value={summary.historical} tone="slate" />
      </div>

      <div className="rounded-xl border border-gray-200 dark:border-gray-800/50 bg-white dark:bg-slate-800 p-4">
        <div className="flex flex-wrap items-center gap-2">
          {FILTERS.map((item) => {
            const active = filter === item.key;
            return (
              <button
                key={item.key}
                type="button"
                onClick={() => {
                  const next = new URLSearchParams(searchParams);
                  if (item.key === "all") next.delete("state");
                  else next.set("state", item.key);
                  setSearchParams(next);
                }}
                className={`rounded-full px-3 py-1.5 text-xs font-medium transition-colors ${
                  active
                    ? "bg-brand-600 text-white"
                    : "bg-gray-100 dark:bg-gray-900/40 text-gray-600 dark:text-gray-400 hover:bg-gray-200"
                }`}
              >
                {item.label}
              </button>
            );
          })}
        </div>
      </div>

      {filteredItems.length === 0 ? (
        <div className="rounded-xl border border-gray-200 dark:border-gray-800/50 bg-white dark:bg-slate-800 p-6 text-center">
          <p className="text-sm font-semibold text-gray-800 dark:text-gray-300">No decisions match this filter.</p>
          <p className="mt-2 text-xs text-gray-500">
            Change the state filter or sync more source documents to widen the register.
          </p>
        </div>
      ) : (
        <div className="space-y-4">
          {filteredItems.map((item) => (
            <DecisionCard key={item.id} item={item} />
          ))}
        </div>
      )}
    </div>
  );
}

function SummaryCard({ label, value, tone }) {
  const tones = {
    emerald: "border-emerald-200 dark:border-emerald-800/50 bg-emerald-50 dark:bg-emerald-900/30 text-emerald-800 dark:text-emerald-300",
    amber: "border-amber-200 dark:border-amber-800/50 bg-amber-50 dark:bg-amber-900/30 text-amber-800 dark:text-amber-300",
    slate: "border-gray-200 dark:border-gray-800/50 bg-white dark:bg-slate-800 text-gray-800 dark:text-gray-300",
  };

  return (
    <div className={`rounded-xl border p-4 ${tones[tone] ?? tones.slate}`}>
      <p className="text-[11px] uppercase tracking-wide opacity-70">{label}</p>
      <p className="mt-2 text-3xl font-semibold">{value}</p>
    </div>
  );
}

function DecisionCard({ item }) {
  const [showHistory, setShowHistory] = useState(false);
  const primaryReviewItemId = item.reviewItemIds?.[0] ?? null;
  const latestDecisionEvent = item.decisionHistory?.[0] ?? null;
  const workflowLinks = buildDecisionWorkflowLinks(item.rationaleSources ?? []);
  const historyQuery = useDecisionHistory(item.id, {
    enabled: showHistory && item.historyAvailable,
  });
  const historyEntries = historyQuery.data?.entries ?? [];

  return (
    <article className="rounded-xl border border-gray-200 dark:border-gray-800/50 bg-white dark:bg-slate-800 p-5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-sm font-semibold text-gray-800 dark:text-gray-300">{item.title}</h3>
            <StatusBadge status={item.status} />
            {item.connectorType && (
              <span className="rounded-full bg-gray-100 dark:bg-gray-900/40 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-gray-600 dark:text-gray-400">
                {item.connectorType}
              </span>
            )}
          </div>
          <p className="mt-2 text-sm text-gray-600 dark:text-gray-400">{item.summary}</p>
        </div>
        <div className="flex flex-col items-end gap-3 text-xs text-gray-400">
          <div className="text-right">
            <p>{formatDateTime(item.createdAt)}</p>
            {typeof item.averageConfidence === "number" && (
              <p className="mt-1">Confidence {Math.round(item.averageConfidence * 100)}%</p>
            )}
          </div>
          <Link
            to={buildDecisionGraphHref(item)}
            className="inline-flex rounded-lg bg-slate-900 px-3 py-1.5 font-medium text-white shadow-sm transition-colors hover:bg-slate-800"
          >
            Explore graph
          </Link>
        </div>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,1.15fr)_minmax(240px,0.85fr)]">
        <div className="space-y-3">
          <MetadataRow label="Source" value={`${item.sourceLabel}${item.author ? ` · ${item.author}` : ""}`} />
          {item.relatedBlocker && <MetadataRow label="Open risk" value={item.relatedBlocker} tone="amber" />}
          {item.modelNames?.length > 0 && (
            <div>
              <p className="text-[11px] uppercase tracking-wide text-gray-500">Affected models</p>
              <div className="mt-2 flex flex-wrap gap-2">
                {item.modelNames.map((modelName) => (
                  <span
                    key={modelName}
                    className="rounded-full bg-gray-100 dark:bg-gray-900/40 px-2 py-1 text-[11px] font-medium text-gray-700 dark:text-gray-400"
                  >
                    {modelName}
                  </span>
                ))}
              </div>
            </div>
          )}
          {item.affectedComponents?.length > 0 && (
            <div>
              <p className="text-[11px] uppercase tracking-wide text-gray-500">Linked facts</p>
              <div className="mt-2 flex flex-wrap gap-2">
                {item.affectedComponents.slice(0, 4).map((component) => (
                  <Link
                    key={component.id}
                    to={component.modelId ? `/app/model/${component.modelId}` : "/app/models"}
                    className="rounded-full border border-gray-200 dark:border-gray-800/50 bg-white dark:bg-slate-800 px-2 py-1 text-[11px] font-medium text-gray-700 dark:text-gray-400 hover:border-brand-200 dark:border-brand-800/50 hover:text-brand-700 dark:text-brand-400"
                  >
                    {component.name}
                  </Link>
                ))}
              </div>
            </div>
          )}
        </div>

        <div className="rounded-xl border border-gray-200 dark:border-gray-800/50 bg-gray-50 dark:bg-gray-900/30 p-4">
          <p className="text-[11px] uppercase tracking-wide text-gray-500">Trust path</p>
          {latestDecisionEvent ? (
            <p className="mt-2 text-sm text-gray-700 dark:text-gray-400">
              Last change:{" "}
              <span className="font-medium">{formatStatus(latestDecisionEvent.newStatus)}</span>
              {latestDecisionEvent.note ? ` — ${latestDecisionEvent.note}` : ""}
            </p>
          ) : (
            <p className="mt-2 text-sm text-gray-600 dark:text-gray-400">
              No explicit review transitions recorded for this decision yet.
            </p>
          )}
          {item.rationaleSources?.length > 0 && (
            <div className="mt-3">
              <p className="text-[11px] uppercase tracking-wide text-gray-500">Rationale sources</p>
              <div className="mt-2 space-y-2">
                {item.rationaleSources.slice(0, 2).map((source, index) => (
                  <div
                    key={source.id ?? source.sourceDocumentId ?? `${source.label ?? "source"}-${index}`}
                    className="text-xs text-gray-600 dark:text-gray-400"
                  >
                    <p className="font-medium text-gray-700 dark:text-gray-400">{source.label}</p>
                    <p className="mt-0.5 text-[11px] text-gray-500">
                      {[source.author, source.connectorType].filter(Boolean).join(" · ")}
                    </p>
                    {source.extractedValue && (
                      <p className="mt-1 text-[11px] text-gray-500">{source.extractedValue}</p>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
          {workflowLinks.length > 0 && (
            <div className="mt-3">
              <p className="text-[11px] uppercase tracking-wide text-gray-500">Related workflows</p>
              <div className="mt-2 flex flex-wrap gap-2">
                {workflowLinks.map((link) => (
                  <Link
                    key={`${link.label}-${link.to}`}
                    to={link.to}
                    className="rounded-full border border-gray-200 dark:border-gray-800/50 bg-white dark:bg-slate-800 px-2 py-1 text-[11px] font-medium text-gray-700 dark:text-gray-400 hover:border-brand-200 dark:border-brand-800/50 hover:text-brand-700 dark:text-brand-400"
                  >
                    {link.label}
                  </Link>
                ))}
              </div>
            </div>
          )}
          <div className="mt-4 flex flex-wrap items-center gap-3 text-xs">
            {item.sourceDocumentId ? (
              <Link
                to={`/app/sources/${item.sourceDocumentId}`}
                className="font-medium text-brand-700 dark:text-brand-400 hover:text-brand-800 dark:text-brand-300"
              >
                View source
              </Link>
            ) : (
              <Link
                to="/app/sources"
                className="font-medium text-brand-700 dark:text-brand-400 hover:text-brand-800 dark:text-brand-300"
              >
                Inspect sources
              </Link>
            )}
            {primaryReviewItemId && (
              <Link
                to={`/app/review/${primaryReviewItemId}`}
                className="font-medium text-brand-700 dark:text-brand-400 hover:text-brand-800 dark:text-brand-300"
              >
                Open review thread
              </Link>
            )}
            {item.historyAvailable && (
              <button
                type="button"
                onClick={() => setShowHistory((value) => !value)}
                className="font-medium text-brand-700 dark:text-brand-400 hover:text-brand-800 dark:text-brand-300"
              >
                {showHistory ? "Hide history" : "Inspect history"}
              </button>
            )}
          </div>
        </div>
      </div>

      {showHistory && (
        <div className="mt-4 rounded-xl border border-gray-200 dark:border-gray-800/50 bg-gray-50 dark:bg-gray-900/30 p-4">
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-[11px] uppercase tracking-wide text-gray-500">Decision timeline</p>
              <p className="mt-1 text-sm text-gray-600 dark:text-gray-400">
                Current and historical versions of this decision.
              </p>
            </div>
          </div>
          {historyQuery.isLoading ? (
            <p className="mt-3 text-sm text-gray-500">Loading history...</p>
          ) : historyEntries.length > 0 ? (
            <div className="mt-4 space-y-3">
              {historyEntries.map((entry) => (
                <div key={entry.id} className="rounded-lg border border-gray-200 dark:border-gray-800/50 bg-white dark:bg-slate-800 px-4 py-3">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="flex flex-wrap items-center gap-2">
                        <p className="text-sm font-medium text-gray-800 dark:text-gray-300">{entry.title}</p>
                        <StatusBadge status={entry.status} />
                      </div>
                      <p className="mt-1 text-sm text-gray-600 dark:text-gray-400">{entry.summary}</p>
                      <p className="mt-2 text-[11px] text-gray-500">
                        {[entry.sourceLabel, entry.author].filter(Boolean).join(" · ")}
                      </p>
                    </div>
                    <div className="text-right text-[11px] text-gray-400">
                      <p>{formatDateTime(entry.createdAt)}</p>
                      {typeof entry.averageConfidence === "number" && (
                        <p className="mt-1">
                          Confidence {Math.round(entry.averageConfidence * 100)}%
                        </p>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="mt-3 text-sm text-gray-500">
              No additional historical versions were returned for this decision.
            </p>
          )}
        </div>
      )}
    </article>
  );
}

function MetadataRow({ label, value, tone = "default" }) {
  const colorClass = tone === "amber" ? "text-amber-700 dark:text-amber-400" : "text-gray-700 dark:text-gray-400";
  return (
    <div>
      <p className="text-[11px] uppercase tracking-wide text-gray-500">{label}</p>
      <p className={`mt-1 text-sm ${colorClass}`}>{value}</p>
    </div>
  );
}

function StatusBadge({ status }) {
  const styles = {
    current: "bg-emerald-100 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-400",
    needs_review: "bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-400",
    historical: "bg-gray-100 dark:bg-gray-900/40 text-gray-600 dark:text-gray-400",
  };

  return (
    <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${styles[status] ?? styles.current}`}>
      {formatStatus(status)}
    </span>
  );
}

function formatStatus(value) {
  if (!value) return "Unknown";
  return value.replace(/_/g, " ");
}

function buildDecisionWorkflowLinks(rationaleSources) {
  if (!Array.isArray(rationaleSources)) return [];

  const links = [];
  const seen = new Set();

  rationaleSources.forEach((source) => {
    if (!source?.sourceDocumentId) return;
    let label = null;
    let to = null;

    if (source.connectorType === "github") {
      label = "Open engineering trail";
      to = `/app/engineering/${source.sourceDocumentId}`;
    } else if (source.connectorType === "zoom") {
      label = "Open meeting context";
      to = `/app/meetings/${source.sourceDocumentId}`;
    }

    if (!label || !to) return;
    const key = `${label}:${to}`;
    if (seen.has(key)) return;
    seen.add(key);
    links.push({ label, to });
  });

  return links;
}

function buildDecisionGraphHref(item) {
  const focus =
    item.affectedComponents?.[0]?.name ||
    item.modelNames?.[0] ||
    item.sourceLabel ||
    item.title;
  const params = new URLSearchParams();
  params.set("view", "local");
  params.set("focus", focus);
  params.set("q", focus);
  return `/app/graph?${params.toString()}`;
}

function formatDateTime(value) {
  if (!value) return "Unknown time";
  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}

function DecisionEmptyState() {
  return (
    <div className="rounded-[32px] border border-gray-200 dark:border-gray-800/50 bg-white dark:bg-slate-800 p-12 text-center shadow-sm">
      <div className="mx-auto w-16 h-16 bg-brand-50 dark:bg-brand-900/30 text-brand-600 dark:text-brand-400 rounded-full flex items-center justify-center mb-6">
        <svg className="w-8 h-8" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
        </svg>
      </div>
      <h2 className="text-xl font-bold text-gray-900 dark:text-gray-200">No decisions have been registered yet.</h2>
      <p className="mt-3 text-sm text-gray-500 max-w-lg mx-auto leading-relaxed">
        The register populates automatically from synced source documents that contain decisions, action items, or major technical choices.
      </p>
      <div className="mt-8 flex flex-wrap items-center justify-center gap-4">
        <Link to="/app" className="px-6 py-2.5 bg-brand-600 text-white text-sm font-bold rounded-xl hover:bg-brand-500 transition-colors shadow-lg shadow-brand-500/20">
          Add context
        </Link>
        <Link to="/app/sources" className="px-6 py-2.5 bg-gray-100 dark:bg-gray-900/40 text-gray-700 dark:text-gray-400 text-sm font-bold rounded-xl hover:bg-gray-200 transition-colors">
          Inspect sources
        </Link>
      </div>
    </div>
  );
}
