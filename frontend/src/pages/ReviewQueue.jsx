import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import MockBadge from "../components/MockBadge";
import SourceDocumentLinks from "../components/SourceDocumentLinks";
import StatusView from "../components/StatusView";
import {
  useApproveReviewItem,
  useRejectReviewItem,
  useReviewQueue,
  useSupersedeReviewItem,
} from "../api/hooks";

const STATUS_OPTIONS = [
  { value: "all", label: "All statuses" },
  { value: "needs_review", label: "Needs review" },
  { value: "approved", label: "Approved" },
  { value: "superseded", label: "Superseded" },
];

const SEVERITY_OPTIONS = [
  { value: "all", label: "All severity" },
  { value: "high", label: "High" },
  { value: "medium", label: "Medium" },
  { value: "low", label: "Low" },
];

const KIND_OPTIONS = [
  { value: "all", label: "All types" },
  { value: "conflict", label: "Conflict" },
  { value: "low_confidence", label: "Low confidence" },
  { value: "fact_update", label: "Fact update" },
  { value: "superseded_fact", label: "Superseded fact" },
];

const STATUS_PILL = {
  needs_review: "bg-amber-100 text-amber-700",
  approved: "bg-emerald-100 text-emerald-700",
  superseded: "bg-slate-100 text-slate-600",
  rejected: "bg-red-100 text-red-700",
};

const SEVERITY_PILL = {
  high: "bg-red-100 text-red-700",
  medium: "bg-amber-100 text-amber-700",
  low: "bg-emerald-100 text-emerald-700",
};

export default function ReviewQueue() {
  const navigate = useNavigate();
  const { itemId } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const [status, setStatus] = useState(searchParams.get("status") ?? "all");
  const [severity, setSeverity] = useState(searchParams.get("severity") ?? "all");
  const [kind, setKind] = useState(searchParams.get("kind") ?? "all");
  const searchQuery = searchParams.get("search") ?? "";
  const sourceId = searchParams.get("source_id");
  const modelId = searchParams.get("model_id");
  const query = useReviewQueue({ status, severity, kind, source_id: sourceId, model_id: modelId });

  const items = useMemo(() => {
    const data = query.data ?? [];
    return data.filter((item) => {
      const matchSearch = !searchQuery || 
        item.title?.toLowerCase().includes(searchQuery.toLowerCase()) || 
        item.summary?.toLowerCase().includes(searchQuery.toLowerCase()) ||
        item.model?.toLowerCase().includes(searchQuery.toLowerCase());

      return matchSearch;
    });
  }, [query.data, searchQuery]);

  const isMock = query.isMock ?? false;  const approveMut = useApproveReviewItem();
  const rejectMut = useRejectReviewItem();
  const supersedeMut = useSupersedeReviewItem();
  const [selectedId, setSelectedId] = useState(null);
  const [actionMessage, setActionMessage] = useState("");
  const [actionError, setActionError] = useState("");

  useEffect(() => {
    setStatus(searchParams.get("status") ?? "all");
    setSeverity(searchParams.get("severity") ?? "all");
    setKind(searchParams.get("kind") ?? "all");
  }, [searchParams]);

  useEffect(() => {
    const next = new URLSearchParams(searchParams);
    if (status !== "all") next.set("status", status); else next.delete("status");
    if (severity !== "all") next.set("severity", severity); else next.delete("severity");
    if (kind !== "all") next.set("kind", kind); else next.delete("kind");
    if (next.toString() !== searchParams.toString()) {
      setSearchParams(next, { replace: true });
    }
  }, [kind, searchParams, setSearchParams, severity, status]);

  useEffect(() => {
    if (items.length === 0) {
      setSelectedId(null);
      return;
    }
    const matchingItem = itemId ? items.find((item) => item.id === itemId) : null;
    if (matchingItem) {
      setSelectedId(matchingItem.id);
      return;
    }
    if (!selectedId || !items.some((item) => item.id === selectedId)) {
      setSelectedId(items[0].id);
      if (itemId && items[0]?.id) {
        navigate({ pathname: `/app/review/${items[0].id}`, search: searchParams.toString() ? `?${searchParams.toString()}` : "" }, { replace: true });
      }
    }
  }, [items, itemId, navigate, searchParams, selectedId]);

  const selectedItem = useMemo(
    () => items.find((item) => item.id === selectedId) ?? null,
    [items, selectedId],
  );

  useEffect(() => {
    setActionMessage("");
    setActionError("");
  }, [selectedId]);

  if (query.isLoading || query.isError) {
    return (
      <div className="max-w-6xl mx-auto">
        <StatusView query={query} empty="No review items yet." />
      </div>
    );
  }

  const filtersActive = status !== "all" || severity !== "all" || kind !== "all" || searchQuery !== "" || sourceId != null || modelId != null;

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-3">
            <h2 className="text-lg font-semibold text-gray-800">Review Queue</h2>
            {isMock && <MockBadge />}
          </div>
          <p className="text-xs text-gray-400 mt-1">
            Human-in-the-loop review for low-confidence facts, conflicts, and superseded company context.
          </p>
          {isMock ? (
            <p className="text-xs text-amber-600 mt-2">
              Review actions are staged in demo mode until the backend review workflow is live.
            </p>
          ) : (
            <p className="text-xs text-emerald-700 mt-2">
              Review actions are live. Approvals and rejections update trust state immediately.
            </p>
          )}
        </div>
        <div className="rounded-xl border border-gray-200 bg-white px-4 py-3 text-right">
          <p className="text-[11px] uppercase tracking-wide text-gray-400">Queue</p>
          <p className="text-sm font-medium text-gray-700">
            {query.total ?? items.length} matching item{(query.total ?? items.length) === 1 ? "" : "s"}
          </p>
        </div>
      </div>

      <div className="rounded-xl border border-gray-200 bg-white px-4 py-4">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h3 className="text-sm font-semibold text-gray-700">Self-host review loop</h3>
            <p className="text-xs text-gray-400 mt-1">
              This queue should stay focused on high-impact conflicts and low-confidence facts, not every extraction event.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-3 text-xs">
            <Link to="/app/sources" className="font-medium text-brand-700 hover:text-brand-800">
              Inspect sources
            </Link>
            <Link to="/app/query" className="font-medium text-brand-700 hover:text-brand-800">
              Pressure-test query
            </Link>
          </div>
        </div>
      </div>

      <div className="grid gap-3 md:grid-cols-[220px_220px_220px_minmax(0,1fr)]">
        <label className="block">
          <span className="block text-xs font-medium text-gray-600 mb-1">Status</span>
          <select
            value={status}
            onChange={(event) => setStatus(event.target.value)}
            aria-label="Filter review queue by status"
            className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-brand-500/40"
          >
            {STATUS_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>

        <label className="block">
          <span className="block text-xs font-medium text-gray-600 mb-1">Severity</span>
          <select
            value={severity}
            onChange={(event) => setSeverity(event.target.value)}
            aria-label="Filter review queue by severity"
            className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-brand-500/40"
          >
            {SEVERITY_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>

        <label className="block">
          <span className="block text-xs font-medium text-gray-600 mb-1">Type</span>
          <select
            value={kind}
            onChange={(event) => setKind(event.target.value)}
            aria-label="Filter review queue by type"
            className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-brand-500/40"
          >
            {KIND_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>

        <div className="rounded-xl border border-gray-200 bg-white px-4 py-3">
          <p className="text-xs uppercase tracking-wide text-gray-400">Policy</p>
          <p className="mt-1 text-sm text-gray-700">
            Only high-impact, conflicting, or ambiguous facts should require human review.
          </p>
        </div>
      </div>

      {items.length === 0 ? (
        <ReviewEmptyState filtersActive={filtersActive} />
      ) : (
        <div className="grid gap-6 lg:grid-cols-[minmax(0,1.05fr)_minmax(320px,0.95fr)]">
          <section
            aria-label="Review items"
            className="bg-white rounded-xl border border-gray-200 overflow-hidden"
          >
            <div className="px-4 py-3 border-b border-gray-100">
              <p className="text-sm font-semibold text-gray-700">Items requiring trust decisions</p>
              <p className="text-xs text-gray-400 mt-1">
                Review conflicts, low-confidence facts, and superseded knowledge before it becomes active truth.
              </p>
            </div>
            <div className="divide-y divide-gray-100">
              {items.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => {
                    setSelectedId(item.id);
                    navigate({
                      pathname: `/app/review/${item.id}`,
                      search: searchParams.toString() ? `?${searchParams.toString()}` : "",
                    });
                  }}
                  aria-pressed={selectedId === item.id}
                  className={`w-full text-left px-4 py-4 transition-colors ${
                    selectedId === item.id ? "bg-brand-50" : "hover:bg-gray-50"
                  }`}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium ${STATUS_PILL[item.status] ?? STATUS_PILL.needs_review}`}>
                          {item.status.replaceAll("_", " ")}
                        </span>
                        <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium ${SEVERITY_PILL[item.severity] ?? SEVERITY_PILL.medium}`}>
                          {item.severity}
                        </span>
                        <span className="text-[11px] text-gray-400 capitalize">{item.kind.replaceAll("_", " ")}</span>
                      </div>
                      <p className="mt-2 text-sm font-medium text-gray-800">{item.title}</p>
                      <p className="mt-1 text-xs text-gray-500 line-clamp-2">{item.summary}</p>
                    </div>
                    <div className="text-right shrink-0">
                      <p className="text-[11px] text-gray-400">{item.freshness}</p>
                      {item.confidence != null && (
                        <p className="text-[11px] text-gray-500 mt-1">
                          {Math.round(item.confidence * 100)}% confidence
                        </p>
                      )}
                    </div>
                  </div>
                </button>
              ))}
              {query.hasNextPage && (
                <div className="p-4 border-t border-gray-100 flex justify-center">
                  <button
                    onClick={() => query.fetchNextPage()}
                    disabled={query.isFetchingNextPage}
                    className="px-4 py-2 text-xs font-bold rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50 transition-colors shadow-sm disabled:opacity-50"
                  >
                    {query.isFetchingNextPage ? "Loading..." : "Load more items"}
                  </button>
                </div>
              )}
            </div>
          </section>

          <section
            aria-label="Review detail"
            className="bg-white rounded-xl border border-gray-200 p-5 space-y-4"
          >
            {selectedItem ? (
              <>
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <h3 className="text-sm font-semibold text-gray-700">{selectedItem.title}</h3>
                    <p className="text-xs text-gray-400 mt-1">
                      {selectedItem.model && (
                        <>
                          {selectedItem.modelId ? (
                            <Link
                              to={`/app/model/${selectedItem.modelId}`}
                              className="text-brand-600 hover:text-brand-700"
                            >
                              {selectedItem.model}
                            </Link>
                          ) : (
                            selectedItem.model
                          )}
                          {" · "}
                        </>
                      )}
                      {selectedItem.kind.replaceAll("_", " ")}
                    </p>
                  </div>
                  <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium ${STATUS_PILL[selectedItem.status] ?? STATUS_PILL.needs_review}`}>
                    {selectedItem.status.replaceAll("_", " ")}
                  </span>
                </div>

                <div className="rounded-xl border border-gray-100 bg-gray-50 p-4 space-y-3">
                  <div>
                    <p className="text-[11px] uppercase tracking-wide text-gray-400">Summary</p>
                    <p className="mt-1 text-sm text-gray-700">{selectedItem.summary}</p>
                  </div>
                  <div>
                    <p className="text-[11px] uppercase tracking-wide text-gray-400">Why this needs review</p>
                    <p className="mt-1 text-sm text-gray-700">{selectedItem.rationale}</p>
                  </div>
                  {selectedItem.suggestedAction && (
                    <div>
                      <p className="text-[11px] uppercase tracking-wide text-gray-400">Suggested action</p>
                      <p className="mt-1 text-sm text-gray-700">{selectedItem.suggestedAction}</p>
                    </div>
                  )}
                </div>

                {(selectedItem.sources.length > 0 || selectedItem.sourceDocuments.length > 0) && (
                  <div className="space-y-3">
                    {selectedItem.sourceDocuments.length > 0 && (
                      <SourceDocumentLinks
                        items={selectedItem.sourceDocuments}
                        label="Supporting documents"
                        compact
                      />
                    )}
                    {selectedItem.sources.length > 0 && (
                      <div>
                        <p className="text-[11px] uppercase tracking-wide text-gray-400">Evidence labels</p>
                        <div className="mt-2 flex flex-wrap gap-2">
                          {selectedItem.sources.map((source) => (
                            <span
                              key={source}
                              className="px-2 py-1 rounded-full bg-slate-100 text-slate-700 text-xs"
                            >
                              {source}
                            </span>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                )}

                {selectedItem.lastSeenAt && (
                  <p className="text-[11px] text-gray-400">
                    Last seen {formatDateTime(selectedItem.lastSeenAt)}
                  </p>
                )}

                {selectedItem.decisionHistory?.length > 0 && (
                  <div className="space-y-3">
                    <div>
                      <p className="text-[11px] uppercase tracking-wide text-gray-400">Decision history</p>
                      <p className="mt-1 text-xs text-gray-500">
                        Audit trail for review actions and automated state transitions.
                      </p>
                    </div>
                    <div className="space-y-2">
                      {selectedItem.decisionHistory.map((decision) => (
                        <div
                          key={decision.id ?? `${decision.createdAt}-${decision.newStatus}`}
                          className="rounded-lg border border-gray-200 bg-gray-50 px-3 py-3"
                        >
                          <div className="flex items-start justify-between gap-3">
                            <div className="min-w-0">
                              <p className="text-sm font-medium text-gray-700">
                                {formatDecisionTransition(decision)}
                              </p>
                              <p className="mt-1 text-[11px] text-gray-500">
                                {formatDecisionActor(decision.actorType)}
                                {decision.createdAt ? ` · ${formatDateTime(decision.createdAt)}` : ""}
                              </p>
                            </div>
                            {decision.newStatus && (
                              <span className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-medium ${STATUS_PILL[decision.newStatus] ?? STATUS_PILL.needs_review}`}>
                                {decision.newStatus.replaceAll("_", " ")}
                              </span>
                            )}
                          </div>
                          {decision.note && (
                            <p className="mt-2 text-xs text-gray-600">{decision.note}</p>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {actionMessage && (
                  <p role="status" className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-700">
                    {actionMessage}
                  </p>
                )}
                {actionError && (
                  <p role="alert" className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
                    {actionError}
                  </p>
                )}

                <div className="grid gap-3 sm:grid-cols-3">
                  <button
                    type="button"
                    disabled={
                      isMock ||
                      selectedItem.status !== "needs_review" ||
                      (approveMut.isPending && approveMut.variables === selectedItem.id)
                    }
                    onClick={() => {
                      setActionMessage("");
                      setActionError("");
                      approveMut.mutate(selectedItem.id, {
                        onSuccess: (item) => {
                          setActionMessage(
                            `${item.title} marked ${item.status.replaceAll("_", " ")}.`,
                          );
                        },
                        onError: (err) => {
                          setActionError(err?.message || "Failed to approve review item.");
                        },
                      });
                    }}
                    className="px-4 py-2 rounded-lg bg-emerald-100 text-emerald-700 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {approveMut.isPending && approveMut.variables === selectedItem.id ? "Approving..." : "Approve"}
                  </button>
                  <button
                    type="button"
                    disabled={
                      isMock ||
                      selectedItem.status === "superseded" ||
                      selectedItem.status === "rejected" ||
                      (supersedeMut.isPending && supersedeMut.variables === selectedItem.id)
                    }
                    onClick={() => {
                      setActionMessage("");
                      setActionError("");
                      supersedeMut.mutate(selectedItem.id, {
                        onSuccess: (item) => {
                          setActionMessage(
                            `${item.title} marked ${item.status.replaceAll("_", " ")}.`,
                          );
                        },
                        onError: (err) => {
                          setActionError(err?.message || "Failed to supersede review item.");
                        },
                      });
                    }}
                    className="px-4 py-2 rounded-lg bg-slate-100 text-slate-700 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {supersedeMut.isPending && supersedeMut.variables === selectedItem.id ? "Superseding..." : "Supersede"}
                  </button>
                  <button
                    type="button"
                    disabled={
                      isMock ||
                      selectedItem.status !== "needs_review" ||
                      (rejectMut.isPending && rejectMut.variables === selectedItem.id)
                    }
                    onClick={() => {
                      setActionMessage("");
                      setActionError("");
                      rejectMut.mutate(selectedItem.id, {
                        onSuccess: (item) => {
                          setActionMessage(
                            `${item.title} marked ${item.status.replaceAll("_", " ")}.`,
                          );
                        },
                        onError: (err) => {
                          setActionError(err?.message || "Failed to reject review item.");
                        },
                      });
                    }}
                    className="px-4 py-2 rounded-lg bg-red-100 text-red-700 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {rejectMut.isPending && rejectMut.variables === selectedItem.id ? "Rejecting..." : "Reject"}
                  </button>
                </div>

                {isMock && (
                  <p className="text-xs text-gray-400">
                    Review actions will become live once the backend review workflow lands.
                  </p>
                )}
              </>
            ) : (
              <div className="flex flex-col items-center justify-center py-16 text-gray-400">
                <p className="text-sm">Select a review item to inspect it.</p>
              </div>
            )}
          </section>
        </div>
      )}
    </div>
  );
}

function ReviewEmptyState({ filtersActive }) {
  return (
    <div className="rounded-xl border border-gray-200 bg-white p-6 text-center">
      <p className="text-sm font-semibold text-gray-800">
        {filtersActive ? "No review items match the current filters." : "No review items yet."}
      </p>
      <p className="mt-2 text-xs text-gray-500 max-w-2xl mx-auto">
        {filtersActive
          ? "Widen the current filters or inspect the underlying source documents to understand whether the queue is currently quiet for the right reasons."
          : "That usually means either the workspace has not been synced yet, or the current ingestion pass did not produce conflicts or low-confidence facts that need operator review."}
      </p>
      <div className="mt-4 flex flex-wrap items-center justify-center gap-4 text-xs">
        <Link to="/app/sources" className="font-medium text-brand-700 hover:text-brand-800">
          Open sources
        </Link>
        <Link to="/app/connectors" className="font-medium text-brand-700 hover:text-brand-800">
          Open connectors
        </Link>
      </div>
    </div>
  );
}

function formatDateTime(value) {
  if (!value) return "—";
  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}

function formatDecisionTransition(decision) {
  const previous = decision.previousStatus;
  const next = decision.newStatus;
  if (previous && next) {
    return `${previous.replaceAll("_", " ")} -> ${next.replaceAll("_", " ")}`;
  }
  if (next) {
    return `Marked ${next.replaceAll("_", " ")}`;
  }
  return "State updated";
}

function formatDecisionActor(actorType) {
  if (!actorType) return "Unknown actor";
  if (actorType === "system") return "System";
  if (actorType === "human") return "Human reviewer";
  return actorType.replaceAll("_", " ");
}

function SummaryCard({ label, value, tone }) {
  const style = {
    amber: "bg-amber-50 border-amber-200 text-amber-700",
    red: "bg-red-50 border-red-200 text-red-700",
    emerald: "bg-emerald-50 border-emerald-200 text-emerald-700",
  }[tone];

  return (
    <div className={`rounded-xl border px-4 py-4 ${style}`}>
      <p className="text-[11px] uppercase tracking-wide opacity-80">{label}</p>
      <p className="mt-2 text-2xl font-semibold">{value}</p>
    </div>
  );
}
