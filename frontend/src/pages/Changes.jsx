import { useMemo } from "react";
import { Link, useSearchParams } from "react-router-dom";
import MockBadge from "../components/MockBadge";
import StatusView from "../components/StatusView";
import { useTimeline } from "../api/hooks";

const FILTERS = [
  { key: "all", label: "All activity" },
  { key: "decision", label: "Decisions" },
  { key: "review", label: "Review" },
  { key: "source", label: "Sources" },
  { key: "connector", label: "Connectors" },
];

export default function Changes() {
  const [searchParams, setSearchParams] = useSearchParams();
  const type = searchParams.get("type") ?? "all";
  const timelineQuery = useTimeline();
  const changes = timelineQuery.data?.items ?? [];
  const summaryCounts = useMemo(
    () =>
      changes.reduce(
        (acc, item) => {
          acc.all += 1;
          if (item.type in acc) acc[item.type] += 1;
          return acc;
        },
        { all: 0, decision: 0, review: 0, source: 0, connector: 0 },
      ),
    [changes],
  );

  const filteredChanges = useMemo(
    () => changes.filter((item) => type === "all" || item.type === type),
    [changes, type],
  );

  if (timelineQuery.isLoading || timelineQuery.isError) {
    return (
      <div className="max-w-6xl mx-auto">
        <StatusView query={timelineQuery} empty="No changes available yet." />
      </div>
    );
  }

  if (!changes.length) {
    return (
      <div className="max-w-6xl mx-auto">
        <ChangesEmptyState />
      </div>
    );
  }

  const usesMockData = timelineQuery.isMock;
  const generatedAt = timelineQuery.data?.generatedAt ?? null;
  const totalEvents = timelineQuery.data?.totalEvents ?? changes.length;
  const showLoadMore = !timelineQuery.isMock && timelineQuery.hasMore;

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-3">
            <h2 className="text-lg font-semibold text-gray-800">Changes</h2>
            {usesMockData && <MockBadge />}
          </div>
          <p className="text-xs text-gray-400 mt-1">
            A single timeline for decision changes, review transitions, source ingests, and connector pressure.
          </p>
          <p className="mt-2 text-[11px] uppercase tracking-wide text-gray-400">
            {totalEvents} recent events
            {generatedAt ? ` · Updated ${formatDateTime(generatedAt)}` : ""}
          </p>
        </div>
        <div className="flex items-center gap-3 text-xs">
          <Link to="/app/brief" className="font-medium text-brand-700 hover:text-brand-800">
            Open founder brief
          </Link>
          <Link to="/app/decisions" className="font-medium text-brand-700 hover:text-brand-800">
            Open decision register
          </Link>
        </div>
      </div>

      <div className="rounded-xl border border-gray-200 bg-white p-4">
        <div className="flex flex-wrap items-center gap-2">
          {FILTERS.map((item) => {
            const active = type === item.key;
            return (
              <button
                key={item.key}
                type="button"
                onClick={() => {
                  const next = new URLSearchParams(searchParams);
                  if (item.key === "all") next.delete("type");
                  else next.set("type", item.key);
                  setSearchParams(next);
                }}
                className={`rounded-full px-3 py-1.5 text-xs font-medium transition-colors ${
                  active
                    ? "bg-brand-600 text-white"
                    : "bg-gray-100 text-gray-600 hover:bg-gray-200"
                }`}
              >
                {item.label}
                <span className={`ml-1 ${active ? "text-brand-100" : "text-gray-400"}`}>
                  {summaryCounts[item.key] ?? 0}
                </span>
              </button>
            );
          })}
        </div>
      </div>

      {filteredChanges.length === 0 ? (
        <div className="rounded-xl border border-gray-200 bg-white p-6 text-center">
          <p className="text-sm font-semibold text-gray-800">No changes match this filter.</p>
          <p className="mt-2 text-xs text-gray-500">
            Widen the filter to view more recent changes across the workspace.
          </p>
        </div>
      ) : (
        <div className="space-y-4">
          {filteredChanges.map((item) => (
            <ChangeCard key={item.id} item={item} />
          ))}
          {showLoadMore && (
            <div className="rounded-xl border border-gray-200 bg-white p-4">
              <button
                type="button"
                onClick={() => timelineQuery.fetchNextPage()}
                disabled={timelineQuery.isFetchingNextPage}
                className="w-full rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-100 disabled:opacity-60"
              >
                {timelineQuery.isFetchingNextPage ? "Loading more..." : "Load more changes"}
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function ChangeCard({ item }) {
  const tone = normalizeChangeTone(item);
  const destination = getChangeDestination(item);
  const graphDestination = getChangeGraphDestination(item);
  const metadata = buildChangeMetadata(item);

  return (
    <article className="rounded-xl border border-gray-200 bg-white p-5">
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-start gap-3">
          <TimelineDot tone={tone} />
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="text-sm font-semibold text-gray-800">{item.title}</h3>
              <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${badgeClass(tone)}`}>
                {formatLabel(item.type)}
              </span>
              {item.status && (
                <span className="rounded-full bg-gray-100 px-2 py-0.5 text-[10px] font-medium text-gray-600">
                  {formatLabel(item.status)}
                </span>
              )}
            </div>
            <p className="mt-2 text-sm text-gray-600">{item.summary}</p>
            {metadata.length > 0 && (
              <div className="mt-3 flex flex-wrap items-center gap-2 text-[11px] text-gray-500">
                {metadata.map((entry) => (
                  <span key={`${item.id}-${entry.label}`} className="rounded-full bg-gray-100 px-2 py-1">
                    <span className="font-medium text-gray-700">{entry.label}:</span> {entry.value}
                  </span>
                ))}
              </div>
            )}
          </div>
        </div>
        <div className="flex flex-col items-end gap-3 text-xs text-gray-400">
          <p>{formatDateTime(item.occurredAt)}</p>
          {destination ? (
            <div className="flex flex-col items-end gap-2 text-right">
              <Link to={destination.href} className="block font-medium text-brand-700 hover:text-brand-800">
                {destination.label}
              </Link>
              {graphDestination ? (
                <Link to={graphDestination.href} className="inline-flex rounded-lg bg-slate-900 px-3 py-1.5 font-medium text-white shadow-sm transition-colors hover:bg-slate-800">
                  {graphDestination.label}
                </Link>
              ) : null}
            </div>
          ) : graphDestination ? (
            <Link to={graphDestination.href} className="inline-flex rounded-lg bg-slate-900 px-3 py-1.5 font-medium text-white shadow-sm transition-colors hover:bg-slate-800">
              {graphDestination.label}
            </Link>
          ) : null}
        </div>
      </div>
    </article>
  );
}

function TimelineDot({ tone }) {
  const styles = {
    emerald: "bg-emerald-500",
    amber: "bg-amber-500",
    rose: "bg-rose-500",
    slate: "bg-gray-400",
  };

  return <span className={`mt-1 h-2.5 w-2.5 rounded-full ${styles[tone] ?? styles.slate}`} />;
}

function badgeClass(tone) {
  const styles = {
    emerald: "bg-emerald-100 text-emerald-700",
    amber: "bg-amber-100 text-amber-700",
    rose: "bg-rose-100 text-rose-700",
    slate: "bg-gray-100 text-gray-600",
  };
  return styles[tone] ?? styles.slate;
}

function normalizeChangeTone(item) {
  if (item.type === "connector") {
    const status = String(item.status ?? "").toLowerCase();
    if (status === "failed" || status === "error") return "rose";
    if (status === "warning" || status === "pending") return "amber";
    return "slate";
  }
  if (item.type === "source") {
    const status = String(item.status ?? "").toLowerCase();
    return status === "processed" ? "slate" : "amber";
  }
  return normalizeStatusTone(item.status);
}

function normalizeStatusTone(status) {
  const value = String(status ?? "").toLowerCase();
  if (value === "approved" || value === "current") return "emerald";
  if (value === "rejected" || value === "failed") return "rose";
  if (value === "needs_review" || value === "pending") return "amber";
  return "slate";
}

function getChangeDestination(item) {
  if (item.type === "review" && item.reviewItemId) {
    return { href: `/app/review/${item.reviewItemId}`, label: "Open review thread" };
  }
  if (item.type === "decision") {
    if (item.sourceDocumentId) {
      return { href: `/app/sources/${item.sourceDocumentId}`, label: "View source" };
    }
    return { href: "/app/decisions", label: "Open decision register" };
  }
  if (item.type === "source" && item.sourceDocumentId) {
    return { href: `/app/sources/${item.sourceDocumentId}`, label: "Inspect source" };
  }
  if (item.type === "connector") {
    return {
      href: item.connectorType ? `/app/connectors/${item.connectorType}/runs` : "/app/connectors",
      label: "Inspect runs",
    };
  }
  return null;
}

function getChangeGraphDestination(item) {
  const focus = item.modelName || item.sourceLabel || item.title;
  if (!focus) return null;
  const params = new URLSearchParams();
  params.set("view", "local");
  params.set("focus", focus);
  params.set("q", focus);
  return { href: `/app/graph?${params.toString()}`, label: "Explore graph" };
}

function buildChangeMetadata(item) {
  const entries = [];
  if (item.modelName) entries.push({ label: "Model", value: item.modelName });
  if (item.sourceLabel) entries.push({ label: "Source", value: item.sourceLabel });
  if (item.connectorType) entries.push({ label: "Connector", value: formatLabel(item.connectorType) });
  return entries;
}

function formatLabel(value) {
  if (!value) return "Unknown";
  return String(value).replace(/_/g, " ");
}

function formatDateTime(value) {
  if (!value) return "Unknown time";
  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}

function ChangesEmptyState() {
  return (
    <div className="rounded-xl border border-gray-200 bg-white p-6 text-center">
      <p className="text-sm font-semibold text-gray-800">No changes are visible yet.</p>
      <p className="mt-2 text-xs text-gray-500 max-w-2xl mx-auto">
        This timeline starts filling in once source documents, review transitions, and decisions begin flowing through the workspace.
      </p>
      <div className="mt-4 flex flex-wrap items-center justify-center gap-4 text-xs">
        <Link to="/app/connectors" className="font-medium text-brand-700 hover:text-brand-800">
          Connect sources
        </Link>
        <Link to="/app/review" className="font-medium text-brand-700 hover:text-brand-800">
          Open review
        </Link>
      </div>
    </div>
  );
}
