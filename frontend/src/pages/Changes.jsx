import { useMemo } from "react";
import { Link, useSearchParams } from "react-router-dom";
import MockBadge from "../components/MockBadge";
import StatusView from "../components/StatusView";
import { useTimeline } from "../api/hooks";
import { GitBranch, Plug, FileText, CheckSquare, Clock } from "lucide-react";

const FILTERS = [
  { key: "all", label: "All" },
  { key: "decision", label: "Decisions" },
  { key: "review", label: "Review" },
  { key: "source", label: "Sources" },
  { key: "connector", label: "Connectors" },
];

export default function Changes() {
  const [searchParams, setSearchParams] = useSearchParams();
  const type = searchParams.get("type") ?? "all";
  const sourceId = searchParams.get("source_id");
  const timelineQuery = useTimeline();
  const changes = timelineQuery.data?.items ?? [];

  const sourceFiltered = useMemo(
    () => sourceId ? changes.filter(i => i.sourceDocumentId === sourceId) : changes,
    [changes, sourceId]
  );

  const filtered = useMemo(
    () => sourceFiltered.filter((item) => type === "all" || item.type === type),
    [sourceFiltered, type]
  );

  const counts = useMemo(() =>
    sourceFiltered.reduce(
      (acc, item) => { acc.all += 1; if (item.type in acc) acc[item.type] += 1; return acc; },
      { all: 0, decision: 0, review: 0, source: 0, connector: 0 }
    ), [sourceFiltered]);

  if (timelineQuery.isLoading || timelineQuery.isError) {
    return <div className="max-w-3xl mx-auto"><StatusView query={timelineQuery} empty="No changes available yet." /></div>;
  }
  if (!changes.length) {
    return <div className="max-w-3xl mx-auto"><ChangesEmptyState /></div>;
  }

  const usesMockData = timelineQuery.isMock;
  const generatedAt = timelineQuery.data?.generatedAt ?? null;
  const totalEvents = sourceId ? sourceFiltered.length : (timelineQuery.data?.totalEvents ?? changes.length);

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2.5">
            <h1 className="text-xl font-bold text-slate-900 dark:text-white">Changes</h1>
            {usesMockData && <MockBadge />}
          </div>
          <p className="text-sm text-slate-500 dark:text-slate-400 mt-0.5">
            {totalEvents} event{totalEvents !== 1 ? "s" : ""}
            {generatedAt ? ` · Updated ${formatDate(generatedAt)}` : ""}
          </p>
        </div>
      </div>

      {/* Filter bar */}
      <div className="flex items-center gap-1.5 p-1.5 bg-slate-100 dark:bg-slate-800 rounded-xl w-fit">
        {FILTERS.map((f) => {
          const active = type === f.key;
          return (
            <button
              key={f.key}
              onClick={() => {
                const next = new URLSearchParams(searchParams);
                if (f.key === "all") next.delete("type"); else next.set("type", f.key);
                setSearchParams(next);
              }}
              className={`flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                active
                  ? "bg-white dark:bg-slate-700 text-slate-900 dark:text-white shadow-sm"
                  : "text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-300"
              }`}
            >
              {f.label}
              <span className={`text-[10px] font-bold tabular-nums ${active ? "text-brand-500" : "text-slate-400"}`}>
                {counts[f.key] ?? 0}
              </span>
            </button>
          );
        })}
      </div>

      {/* Timeline */}
      {filtered.length === 0 ? (
        <div className="rounded-xl bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 p-8 text-center">
          <p className="text-sm font-semibold text-slate-600 dark:text-slate-300">No changes match this filter.</p>
        </div>
      ) : (
        <div className="relative">
          {/* Vertical line */}
          <div className="absolute left-[19px] top-3 bottom-3 w-px bg-slate-200 dark:bg-slate-700" />
          <div className="space-y-3">
            {filtered.map((item) => <ChangeCard key={item.id} item={item} />)}
          </div>
          {!timelineQuery.isMock && timelineQuery.hasMore && (
            <button
              onClick={() => timelineQuery.fetchNextPage()}
              disabled={timelineQuery.isFetchingNextPage}
              className="mt-4 w-full py-2.5 rounded-xl border border-slate-200 dark:border-slate-700 text-xs font-semibold text-slate-500 hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors disabled:opacity-50"
            >
              {timelineQuery.isFetchingNextPage ? "Loading…" : "Load more"}
            </button>
          )}
        </div>
      )}
    </div>
  );
}

function ChangeCard({ item }) {
  const tone = normalizeTone(item);
  const destination = getDestination(item);
  const graphDest = getGraphDestination(item);
  const meta = buildMeta(item);
  const Icon = getIcon(item.type);

  const dotColors = {
    emerald: "bg-emerald-500 ring-emerald-100 dark:ring-emerald-900/40",
    amber:   "bg-amber-500 ring-amber-100 dark:ring-amber-900/40",
    rose:    "bg-rose-500 ring-rose-100 dark:ring-rose-900/40",
    slate:   "bg-slate-400 ring-slate-100 dark:ring-slate-800",
  };

  return (
    <div className="flex items-start gap-4 relative">
      {/* Dot */}
      <div className={`mt-3.5 w-5 h-5 rounded-full shrink-0 z-10 ring-4 flex items-center justify-center ${dotColors[tone] || dotColors.slate}`}>
        <Icon className="w-2.5 h-2.5 text-white" />
      </div>
      {/* Card */}
      <div className="flex-1 bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-4 shadow-sm min-w-0">
        <div className="flex items-start justify-between gap-3">
          <div className="flex-1 min-w-0">
            <div className="flex flex-wrap items-center gap-2 mb-1.5">
              <h3 className="text-sm font-semibold text-slate-800 dark:text-slate-200">{item.title}</h3>
              <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${badgeClass(tone)}`}>
                {fmtLabel(item.type)}
              </span>
              {item.status && (
                <span className="rounded-full bg-slate-100 dark:bg-slate-700 px-2 py-0.5 text-[10px] font-medium text-slate-500 dark:text-slate-400">
                  {fmtLabel(item.status)}
                </span>
              )}
            </div>
            {item.summary && <p className="text-xs text-slate-500 dark:text-slate-400 leading-relaxed">{item.summary}</p>}
            {meta.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {meta.map((e) => (
                  <span key={`${item.id}-${e.label}`} className="rounded-lg bg-slate-50 dark:bg-slate-900/60 border border-slate-100 dark:border-slate-700/50 px-2 py-0.5 text-[10px] text-slate-500 dark:text-slate-400">
                    <span className="font-semibold text-slate-600 dark:text-slate-300">{e.label}:</span> {e.value}
                  </span>
                ))}
              </div>
            )}
          </div>
          <div className="flex flex-col items-end gap-2 shrink-0">
            <p className="text-[11px] text-slate-400 whitespace-nowrap">{formatDate(item.occurredAt)}</p>
            {destination && (
              <Link to={destination.href} className="text-[11px] font-semibold text-brand-600 dark:text-brand-400 hover:text-brand-500 whitespace-nowrap">
                {destination.label} →
              </Link>
            )}
            {graphDest && (
              <Link to={graphDest.href} className="text-[10px] font-bold px-2.5 py-1 rounded-lg bg-slate-900 dark:bg-slate-700 text-white hover:bg-slate-800 transition-colors whitespace-nowrap">
                {graphDest.label}
              </Link>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function getIcon(type) {
  return { decision: CheckSquare, source: FileText, connector: Plug, review: GitBranch }[type] || Clock;
}

function normalizeTone(item) {
  if (item.type === "connector") {
    const s = String(item.status ?? "").toLowerCase();
    if (s === "failed" || s === "error") return "rose";
    if (s === "warning" || s === "pending") return "amber";
    return "slate";
  }
  if (item.type === "source") return String(item.status ?? "").toLowerCase() === "processed" ? "slate" : "amber";
  const v = String(item.status ?? "").toLowerCase();
  if (v === "approved" || v === "current") return "emerald";
  if (v === "rejected" || v === "failed") return "rose";
  if (v === "needs_review" || v === "pending") return "amber";
  return "slate";
}

function badgeClass(tone) {
  return {
    emerald: "bg-emerald-100 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-400",
    amber:   "bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-400",
    rose:    "bg-rose-100 dark:bg-rose-900/40 text-rose-700 dark:text-rose-400",
    slate:   "bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400",
  }[tone] || "bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400";
}

function getDestination(item) {
  if (item.type === "connector") {
    return {
      href: item.connectorType ? `/app/connectors/${item.connectorType}/runs` : "/app/connectors",
      label: "Inspect runs",
    };
  }
  // Source documents and decisions both trace back to the source manager.
  // Deep links to per-document/review/decision routes don't exist yet, so we
  // link to the surfaces that do rather than bouncing through the catch-all.
  if ((item.type === "source" || item.type === "decision") && item.sourceDocumentId) {
    return { href: "/app/sources", label: "View in sources" };
  }
  return null;
}

function getGraphDestination(item) {
  const focus = item.modelName || item.sourceLabel || item.title;
  if (!focus) return null;
  const p = new URLSearchParams({ view: "local", focus, q: focus });
  return { href: `/app/graph?${p.toString()}`, label: "Explore graph" };
}

function buildMeta(item) {
  const e = [];
  if (item.modelName) e.push({ label: "Model", value: item.modelName });
  if (item.sourceLabel) e.push({ label: "Source", value: item.sourceLabel });
  if (item.connectorType) e.push({ label: "Connector", value: fmtLabel(item.connectorType) });
  return e;
}

function fmtLabel(v) { return v ? String(v).replace(/_/g, " ") : "Unknown"; }
function formatDate(v) {
  if (!v) return "Unknown";
  try { return new Date(v).toLocaleString(); } catch { return v; }
}

function ChangesEmptyState() {
  return (
    <div className="rounded-2xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 p-12 text-center shadow-sm">
      <div className="w-14 h-14 rounded-2xl bg-brand-50 dark:bg-brand-900/30 flex items-center justify-center mx-auto mb-5">
        <Clock className="w-7 h-7 text-brand-500" />
      </div>
      <h2 className="text-lg font-bold text-slate-900 dark:text-white">No changes yet</h2>
      <p className="mt-2 text-sm text-slate-500 max-w-sm mx-auto leading-relaxed">
        This timeline fills in once source documents, review transitions, and decisions start flowing through your workspace.
      </p>
      <div className="mt-8 flex items-center justify-center gap-3">
        <Link to="/app" className="px-5 py-2.5 bg-brand-600 text-white text-sm font-bold rounded-xl hover:bg-brand-500 transition-colors shadow-sm shadow-brand-600/20">
          Add context
        </Link>
        <Link to="/app/sources" className="px-5 py-2.5 bg-slate-100 dark:bg-slate-700 text-slate-700 dark:text-slate-300 text-sm font-bold rounded-xl hover:bg-slate-200 dark:hover:bg-slate-600 transition-colors">
          Upload sources
        </Link>
      </div>
    </div>
  );
}
