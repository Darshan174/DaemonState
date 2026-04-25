import { useState } from "react";
import { useModelRelationships, useCreateRelationship } from "../api/hooks";

const RELATIONSHIP_TYPES = [
  { value: "depends_on", label: "Depends on" },
  { value: "blocked_by", label: "Blocked by" },
  { value: "enables", label: "Enables" },
  { value: "contradicts", label: "Contradicts" },
  { value: "supersedes", label: "Supersedes" },
  { value: "related_to", label: "Related to" },
];

const SENTIMENTS = [
  { value: "positive", label: "Positive", color: "text-emerald-600 dark:text-emerald-400" },
  { value: "negative", label: "Negative", color: "text-red-600 dark:text-red-400" },
  { value: "neutral", label: "Neutral", color: "text-gray-500" },
];

const SENTIMENT_BADGE = {
  positive: "bg-emerald-50 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400 border-emerald-200 dark:border-emerald-800/50",
  negative: "bg-red-50 dark:bg-red-900/30 text-red-700 dark:text-red-400 border-red-200 dark:border-red-800/50",
  neutral: "bg-gray-50 dark:bg-gray-900/30 text-gray-600 dark:text-gray-400 border-gray-200 dark:border-gray-800/50",
};

const TYPE_LABEL = Object.fromEntries(RELATIONSHIP_TYPES.map((t) => [t.value, t.label]));

/**
 * Relationships section for a model detail page.
 *
 * Shows existing relationships and a form to create new ones.
 * Components from the current model are available as source/target options.
 */
export default function RelationshipsPanel({ modelId, components, isBackendData }) {
  const query = useModelRelationships(modelId);
  const [showForm, setShowForm] = useState(false);

  const relationships = query.data ?? [];
  const componentMap = new Map((components ?? []).map((c) => [c.id, c.name]));

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-800 dark:text-gray-300">
          Relationships
          {relationships.length > 0 && (
            <span className="ml-2 text-xs font-normal text-gray-400">
              ({relationships.length})
            </span>
          )}
        </h3>
        {isBackendData && !showForm && (
          <button
            onClick={() => setShowForm(true)}
            className="px-3 py-1.5 text-xs font-medium rounded-lg bg-brand-600 text-white hover:bg-brand-700 transition-colors"
          >
            + Add Relationship
          </button>
        )}
      </div>

      {/* Create form */}
      {showForm && (
        <CreateRelationshipForm
          components={components}
          onClose={() => setShowForm(false)}
        />
      )}

      {/* List */}
      {query.isLoading ? (
        <p className="text-xs text-gray-400 py-4 text-center">Loading relationships...</p>
      ) : query.isError ? (
        <div className="text-center py-4">
          <p className="text-xs text-red-500">Failed to load relationships.</p>
          <button
            onClick={() => query.refetch()}
            className="mt-2 text-xs text-gray-500 underline"
          >
            Retry
          </button>
        </div>
      ) : relationships.length === 0 ? (
        <div className="bg-white dark:bg-slate-800 rounded-xl border border-gray-200 dark:border-gray-800/50 p-6 text-center">
          <p className="text-sm text-gray-400">No relationships yet.</p>
          <p className="text-xs text-gray-300 mt-1">
            Relationships connect components to show how they influence each other.
          </p>
        </div>
      ) : (
        <div className="bg-white dark:bg-slate-800 rounded-xl border border-gray-200 dark:border-gray-800/50 divide-y divide-gray-100">
          {relationships.map((r) => (
            <RelationshipRow
              key={r.id}
              rel={r}
              componentMap={componentMap}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function RelationshipRow({ rel, componentMap }) {
  const srcName = rel.source_component_name
    || componentMap.get(rel.source_component_id)
    || shortId(rel.source_component_id);
  const tgtName = rel.target_component_name
    || componentMap.get(rel.target_component_id)
    || shortId(rel.target_component_id);
  const confidencePct = Math.round(rel.confidence * 100);
  const sentimentCls = SENTIMENT_BADGE[rel.sentiment] || SENTIMENT_BADGE.neutral;

  return (
    <div className="px-4 py-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
      {/* Source → Type → Target */}
      <span className="font-medium text-gray-700 dark:text-gray-400 truncate max-w-[160px]" title={srcName}>
        {srcName}
      </span>
      <span className="flex items-center gap-1 text-xs text-gray-400 shrink-0">
        <span className="w-6 h-px bg-gray-300 inline-block" />
        <span className="italic whitespace-nowrap">
          {TYPE_LABEL[rel.relationship_type] || rel.relationship_type}
        </span>
        <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
        </svg>
      </span>
      <span className="font-medium text-gray-700 dark:text-gray-400 truncate max-w-[160px]" title={tgtName}>
        {tgtName}
      </span>

      {/* Badges */}
      <div className="ml-auto flex items-center gap-2">
        <span className={`px-2 py-0.5 text-[11px] rounded-full border ${sentimentCls}`}>
          {rel.sentiment}
        </span>
        <span className="text-[11px] text-gray-400">
          {confidencePct}% conf
        </span>
      </div>

      {/* Description */}
      {rel.description && (
        <p className="w-full text-xs text-gray-400 mt-0.5 pl-0">{rel.description}</p>
      )}
    </div>
  );
}

function CreateRelationshipForm({ components, onClose }) {
  const create = useCreateRelationship();
  const [sourceId, setSourceId] = useState("");
  const [targetId, setTargetId] = useState("");
  const [relType, setRelType] = useState("related_to");
  const [sentiment, setSentiment] = useState("neutral");
  const [confidence, setConfidence] = useState("0.8");
  const [description, setDescription] = useState("");

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!sourceId || !targetId || sourceId === targetId) return;
    create.mutate(
      {
        source_component_id: sourceId,
        target_component_id: targetId,
        relationship_type: relType,
        sentiment,
        confidence: parseFloat(confidence) || 0.8,
        description: description.trim() || null,
      },
      { onSuccess: () => onClose() },
    );
  };

  return (
    <div className="bg-white dark:bg-slate-800 rounded-xl border border-gray-200 dark:border-gray-800/50 p-5">
      <h4 className="text-sm font-semibold text-gray-700 dark:text-gray-400 mb-4">Add relationship</h4>
      <form onSubmit={handleSubmit} className="grid sm:grid-cols-2 gap-3">
        {/* Source */}
        <div>
          <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">Source component</label>
          <select
            value={sourceId}
            onChange={(e) => setSourceId(e.target.value)}
            required
            className="w-full px-2.5 py-2 text-sm border border-gray-200 dark:border-gray-800/50 rounded-lg focus:outline-none focus:ring-2 focus:ring-brand-500/40 bg-white dark:bg-slate-800"
          >
            <option value="">Select...</option>
            {components.map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
        </div>

        {/* Target */}
        <div>
          <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">Target component</label>
          <select
            value={targetId}
            onChange={(e) => setTargetId(e.target.value)}
            required
            className="w-full px-2.5 py-2 text-sm border border-gray-200 dark:border-gray-800/50 rounded-lg focus:outline-none focus:ring-2 focus:ring-brand-500/40 bg-white dark:bg-slate-800"
          >
            <option value="">Select...</option>
            {components.filter((c) => c.id !== sourceId).map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
        </div>

        {/* Type */}
        <div>
          <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">Type</label>
          <select
            value={relType}
            onChange={(e) => setRelType(e.target.value)}
            className="w-full px-2.5 py-2 text-sm border border-gray-200 dark:border-gray-800/50 rounded-lg focus:outline-none focus:ring-2 focus:ring-brand-500/40 bg-white dark:bg-slate-800"
          >
            {RELATIONSHIP_TYPES.map((t) => (
              <option key={t.value} value={t.value}>{t.label}</option>
            ))}
          </select>
        </div>

        {/* Sentiment */}
        <div>
          <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">Sentiment</label>
          <select
            value={sentiment}
            onChange={(e) => setSentiment(e.target.value)}
            className="w-full px-2.5 py-2 text-sm border border-gray-200 dark:border-gray-800/50 rounded-lg focus:outline-none focus:ring-2 focus:ring-brand-500/40 bg-white dark:bg-slate-800"
          >
            {SENTIMENTS.map((s) => (
              <option key={s.value} value={s.value}>{s.label}</option>
            ))}
          </select>
        </div>

        {/* Confidence */}
        <div>
          <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">Confidence (0–1)</label>
          <input
            type="number"
            step="0.01"
            min="0"
            max="1"
            value={confidence}
            onChange={(e) => setConfidence(e.target.value)}
            className="w-full px-2.5 py-2 text-sm border border-gray-200 dark:border-gray-800/50 rounded-lg focus:outline-none focus:ring-2 focus:ring-brand-500/40"
          />
        </div>

        {/* Description */}
        <div>
          <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">Description</label>
          <input
            type="text"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Optional note"
            className="w-full px-2.5 py-2 text-sm border border-gray-200 dark:border-gray-800/50 rounded-lg focus:outline-none focus:ring-2 focus:ring-brand-500/40"
          />
        </div>

        {/* Validation */}
        {sourceId && targetId && sourceId === targetId && (
          <p className="sm:col-span-2 text-xs text-amber-600 dark:text-amber-400">
            Source and target must be different components.
          </p>
        )}

        {create.isError && (
          <p className="sm:col-span-2 text-xs text-red-600 dark:text-red-400">
            {create.error?.message || "Failed to create relationship."}
          </p>
        )}

        <div className="sm:col-span-2 flex gap-2 pt-1">
          <button
            type="submit"
            disabled={create.isPending || !sourceId || !targetId || sourceId === targetId}
            className="px-4 py-2 text-sm font-medium rounded-lg bg-brand-600 text-white hover:bg-brand-700 disabled:opacity-50 transition-colors"
          >
            {create.isPending ? "Creating..." : "Create Relationship"}
          </button>
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 text-sm font-medium rounded-lg border border-gray-200 dark:border-gray-800/50 text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:bg-gray-900/30 transition-colors"
          >
            Cancel
          </button>
        </div>
      </form>
    </div>
  );
}

function shortId(uuid) {
  if (!uuid) return "?";
  return String(uuid).slice(0, 8) + "...";
}
