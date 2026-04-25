import { useState } from "react";
import { useComponentSources } from "../api/hooks";
import SourceDocumentLinks from "./SourceDocumentLinks";
import TrustStatePanel from "./TrustStatePanel";

/**
 * Renders a single component card with optional inline edit and delete.
 *
 * Accepts both mock data shape (freshness, sources[]) and backend
 * ComponentRead shape (last_verified_at, authority_source, no sources).
 *
 * Pass `onUpdate` and `onDelete` to enable edit/delete actions.
 */
export default function ComponentCard({
  id,
  name,
  value,
  confidence,
  freshness,
  last_verified_at,
  sources,
  sourceDocuments,
  authority_source,
  authority_weight,
  reviewStatus,
  reviewSummary,
  temporalState,
  reviewItemId,
  decisionHistory,
  onUpdate,
  onDelete,
  updatePending,
  deletePending,
  mutationError,
}) {
  const [mode, setMode] = useState("view"); // "view" | "edit" | "confirmDelete"
  const [editName, setEditName] = useState(name);
  const [editValue, setEditValue] = useState(value);
  const [editConfidence, setEditConfidence] = useState(String(confidence));
  const [editAuthority, setEditAuthority] = useState(authority_source ?? "");

  const confidencePct = Math.round(confidence * 100);
  const barColor =
    confidencePct >= 90 ? "bg-emerald-500" : confidencePct >= 75 ? "bg-amber-400" : "bg-red-400";
  const provenanceQuery = useComponentSources(id, {
    enabled: !!id && (!sourceDocuments || sourceDocuments.length === 0),
  });

  const displayFreshness = freshness ?? formatVerifiedAt(last_verified_at);
  const displaySources = sources ?? (authority_source ? [authority_source] : []);
  const displaySourceDocuments =
    sourceDocuments?.length > 0 ? sourceDocuments : provenanceQuery.data ?? [];

  const canMutate = !!onUpdate; // if callbacks provided, this is a real backend component

  const handleSaveEdit = () => {
    if (!onUpdate || !editName.trim() || !editValue.trim()) return;
    onUpdate(
      {
        componentId: id,
        name: editName.trim(),
        value: editValue.trim(),
        confidence: parseFloat(editConfidence) || confidence,
        authority_source: editAuthority.trim() || null,
      },
      { onSuccess: () => setMode("view") },
    );
  };

  const handleDelete = () => {
    if (!onDelete) return;
    onDelete(id, { onSuccess: () => {} });
  };

  // ── Edit mode ──
  if (mode === "edit") {
    return (
      <div className="bg-white dark:bg-slate-800 border-2 border-brand-300 rounded-xl p-5 space-y-3">
        <div>
          <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">Name</label>
          <input
            type="text"
            value={editName}
            onChange={(e) => setEditName(e.target.value)}
            className="w-full px-2.5 py-1.5 text-sm border border-gray-200 dark:border-gray-800/50 rounded-lg focus:outline-none focus:ring-2 focus:ring-brand-500/40"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">Value</label>
          <input
            type="text"
            value={editValue}
            onChange={(e) => setEditValue(e.target.value)}
            className="w-full px-2.5 py-1.5 text-sm border border-gray-200 dark:border-gray-800/50 rounded-lg focus:outline-none focus:ring-2 focus:ring-brand-500/40"
          />
        </div>
        <div className="grid grid-cols-2 gap-2">
          <div>
            <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">Confidence</label>
            <input
              type="number"
              step="0.01"
              min="0"
              max="1"
              value={editConfidence}
              onChange={(e) => setEditConfidence(e.target.value)}
              className="w-full px-2.5 py-1.5 text-sm border border-gray-200 dark:border-gray-800/50 rounded-lg focus:outline-none focus:ring-2 focus:ring-brand-500/40"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">Source</label>
            <input
              type="text"
              value={editAuthority}
              onChange={(e) => setEditAuthority(e.target.value)}
              className="w-full px-2.5 py-1.5 text-sm border border-gray-200 dark:border-gray-800/50 rounded-lg focus:outline-none focus:ring-2 focus:ring-brand-500/40"
            />
          </div>
        </div>
        {mutationError && (
          <p className="text-xs text-red-600 dark:text-red-400">{mutationError}</p>
        )}
        <div className="flex gap-2 pt-1">
          <button
            onClick={handleSaveEdit}
            disabled={updatePending || !editName.trim() || !editValue.trim()}
            className="px-3 py-1.5 text-xs font-medium rounded-lg bg-brand-600 text-white hover:bg-brand-700 disabled:opacity-50 transition-colors"
          >
            {updatePending ? "Saving..." : "Save"}
          </button>
          <button
            onClick={() => setMode("view")}
            className="px-3 py-1.5 text-xs font-medium rounded-lg border border-gray-200 dark:border-gray-800/50 text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:bg-gray-900/30 transition-colors"
          >
            Cancel
          </button>
        </div>
      </div>
    );
  }

  // ── Confirm delete mode ──
  if (mode === "confirmDelete") {
    return (
      <div className="bg-red-50 dark:bg-red-900/30 border-2 border-red-200 dark:border-red-800/50 rounded-xl p-5 space-y-3">
        <p className="text-sm font-medium text-red-800 dark:text-red-300">
          Delete "{name}"?
        </p>
        <p className="text-xs text-red-600 dark:text-red-400">This action cannot be undone.</p>
        {mutationError && (
          <p className="text-xs text-red-600 dark:text-red-400">{mutationError}</p>
        )}
        <div className="flex gap-2">
          <button
            onClick={handleDelete}
            disabled={deletePending}
            className="px-3 py-1.5 text-xs font-medium rounded-lg bg-red-600 text-white hover:bg-red-700 disabled:opacity-50 transition-colors"
          >
            {deletePending ? "Deleting..." : "Yes, delete"}
          </button>
          <button
            onClick={() => setMode("view")}
            className="px-3 py-1.5 text-xs font-medium rounded-lg border border-gray-200 dark:border-gray-800/50 text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:bg-gray-900/30 transition-colors"
          >
            Cancel
          </button>
        </div>
      </div>
    );
  }

  // ── View mode (default) ──
  return (
    <div className="bg-white dark:bg-slate-800 border border-gray-200 dark:border-gray-800/50 rounded-xl p-5 hover:shadow-md transition-shadow group">
      <div className="flex items-start justify-between mb-3">
        <h3 className="text-sm font-semibold text-gray-800 dark:text-gray-300">{name}</h3>
        <span className="text-lg font-bold text-gray-900 dark:text-gray-200">{value}</span>
      </div>

      {/* Confidence bar */}
      <div className="mb-3">
        <div className="flex items-center justify-between text-xs text-gray-500 mb-1">
          <span>Confidence</span>
          <span>{confidencePct}%</span>
        </div>
        <div className="h-1.5 bg-gray-100 dark:bg-gray-900/40 rounded-full overflow-hidden">
          <div className={`h-full rounded-full ${barColor}`} style={{ width: `${confidencePct}%` }} />
        </div>
      </div>

      {/* Freshness */}
      {displayFreshness && (
        <p className="text-xs text-gray-400 mb-3">Updated {displayFreshness}</p>
      )}

      <TrustStatePanel
        reviewStatus={reviewStatus}
        reviewSummary={reviewSummary}
        temporalState={temporalState}
        reviewItemId={reviewItemId}
        compact
        className="mb-3"
      />

      {/* Source chips */}
      {displaySources.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mb-3">
          {displaySources.map((s) => (
            <span
              key={s}
              className="inline-block px-2 py-0.5 text-[11px] rounded-full bg-gray-100 dark:bg-gray-900/40 text-gray-600 dark:text-gray-400"
            >
              {s}
            </span>
          ))}
        </div>
      )}

      {typeof authority_weight === "number" && (
        <p className="text-[11px] text-gray-500 mb-3">
          Authority weight {Math.round(authority_weight * 100)}%
        </p>
      )}

      {displaySourceDocuments.length > 0 && (
        <div className="mb-3">
          <SourceDocumentLinks items={displaySourceDocuments} label="Evidence" compact showMeta />
        </div>
      )}

      {decisionHistory?.length > 0 && (
        <div className="mb-3 rounded-lg border border-gray-100 dark:border-gray-800/30 bg-gray-50 dark:bg-gray-900/30 px-3 py-3">
          <p className="text-[11px] font-medium uppercase tracking-wide text-gray-500">
            Review history
          </p>
          <div className="mt-2 space-y-2">
            {decisionHistory.map((decision) => (
              <div key={decision.id ?? `${decision.createdAt}-${decision.newStatus}`} className="text-xs text-gray-600 dark:text-gray-400">
                <p className="font-medium text-gray-700 dark:text-gray-400">{formatDecisionTransition(decision)}</p>
                <p className="mt-0.5 text-[11px] text-gray-500">
                  {formatDecisionActor(decision.actorType)}
                  {decision.createdAt ? ` · ${formatDate(decision.createdAt)}` : ""}
                </p>
                {decision.note && (
                  <p className="mt-1 text-[11px] text-gray-500">{decision.note}</p>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Action buttons — only for backend components */}
      {canMutate && (
        <div className="flex gap-2 pt-1 sm:opacity-0 sm:group-hover:opacity-100 transition-opacity">
          <button
            onClick={() => {
              setEditName(name);
              setEditValue(value);
              setEditConfidence(String(confidence));
              setEditAuthority(authority_source ?? "");
              setMode("edit");
            }}
            aria-label={`Edit ${name}`}
            className="px-2.5 py-1 text-[11px] font-medium rounded-lg border border-gray-200 dark:border-gray-800/50 text-gray-500 hover:bg-gray-50 dark:bg-gray-900/30 transition-colors"
          >
            Edit
          </button>
          <button
            onClick={() => setMode("confirmDelete")}
            aria-label={`Delete ${name}`}
            className="px-2.5 py-1 text-[11px] font-medium rounded-lg border border-red-200 dark:border-red-800/50 text-red-500 hover:bg-red-50 dark:bg-red-900/30 transition-colors"
          >
            Delete
          </button>
        </div>
      )}
    </div>
  );
}

function formatVerifiedAt(isoString) {
  if (!isoString) return null;
  const diff = Date.now() - new Date(isoString).getTime();
  const mins = Math.floor(diff / 60_000);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

function formatDate(value) {
  if (!value) return "—";
  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}

function formatDecisionTransition(decision) {
  const previous = decision?.previousStatus ?? decision?.previous_status;
  const next = decision?.newStatus ?? decision?.new_status;
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
