import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import ComponentCard from "../components/ComponentCard";
import RelationshipsPanel from "../components/RelationshipsPanel";
import StatusView from "../components/StatusView";
import {
  useModel,
  useCreateComponent,
  useUpdateComponent,
  useDeleteComponent,
} from "../api/hooks";

export default function ModelDetail() {
  const { modelId } = useParams();
  const query = useModel(modelId);
  const updateMut = useUpdateComponent();
  const deleteMut = useDeleteComponent();
  const [showForm, setShowForm] = useState(false);

  if (query.isLoading || query.isError) {
    return (
      <div className="max-w-5xl mx-auto">
        <StatusView query={query} empty="This model has no components yet." />
      </div>
    );
  }

  const model = query.data ?? { name: "Unknown", description: "", components: [] };
  const components = model.components ?? [];
  const activeComponents = components.filter((component) => !isHistoricalComponent(component));
  const historicalComponents = components.filter(isHistoricalComponent);
  // If the data came from mock fixtures it won't have a UUID id — detect that to disable mutations
  const isBackendData = !!model.workspace_id;

  return (
    <div className="max-w-5xl mx-auto space-y-8">
      {/* ── Header ──────────────────────────────── */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold text-gray-800 dark:text-gray-300">{model.name}</h2>
          <p className="text-sm text-gray-500 mt-1">{model.description}</p>
          <div className="flex gap-4 mt-3 text-xs text-gray-400">
            <span>
              Last updated:{" "}
              {model.lastUpdated ??
                (model.updated_at
                  ? new Date(model.updated_at).toLocaleDateString()
                  : "—")}
            </span>
            <span>{components.length} components</span>
          </div>
        </div>
        {isBackendData && !showForm && (
          <button
            onClick={() => setShowForm(true)}
            aria-label="Add component to model"
            className="px-4 py-2 text-sm font-medium rounded-lg bg-brand-600 text-white hover:bg-brand-700 transition-colors shrink-0"
          >
            + Add Component
          </button>
        )}
      </div>

      <div className="rounded-xl border border-gray-200 dark:border-gray-800/50 bg-white dark:bg-slate-800 p-4">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-400">Trust path for this model</h3>
            <p className="text-xs text-gray-400 mt-1">
              Use this page to inspect current facts, historical versions, evidence links, and review history before treating a model as operational truth.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-3 text-xs">
            <Link to="/app/sources" className="font-medium text-brand-700 dark:text-brand-400 hover:text-brand-800 dark:text-brand-300">
              Sources
            </Link>
            <Link to="/app/review" className="font-medium text-brand-700 dark:text-brand-400 hover:text-brand-800 dark:text-brand-300">
              Review
            </Link>
            <Link to="/app/graph" className="font-medium text-brand-700 dark:text-brand-400 hover:text-brand-800 dark:text-brand-300">
              Graph
            </Link>
          </div>
        </div>
      </div>

      {/* ── Add component form ──────────────────── */}
      {isBackendData && showForm && (
        <AddComponentForm modelId={modelId} onClose={() => setShowForm(false)} />
      )}

      {/* ── Component grid ──────────────────────── */}
      {components.length === 0 ? (
        <div className="rounded-xl border border-gray-200 dark:border-gray-800/50 bg-white dark:bg-slate-800 p-6 text-center">
          <p className="text-sm font-semibold text-gray-800 dark:text-gray-300">No components yet.</p>
          <p className="mt-2 text-xs text-gray-500 max-w-2xl mx-auto">
            Components are the facts inside this model. In a self-hosted setup, they usually appear after source documents are synced and extracted, or you can add them manually to shape the graph first.
          </p>
          <div className="mt-4 flex flex-wrap items-center justify-center gap-4 text-xs">
            {isBackendData && (
              <button type="button" onClick={() => setShowForm(true)} className="font-medium text-brand-700 dark:text-brand-400 hover:text-brand-800 dark:text-brand-300">
                Add a component
              </button>
            )}
            <Link to="/app/sources" className="font-medium text-brand-700 dark:text-brand-400 hover:text-brand-800 dark:text-brand-300">
              Inspect sources
            </Link>
          </div>
        </div>
      ) : (
        <div className="space-y-8">
          {activeComponents.length > 0 && (
            <div className="space-y-4">
              {historicalComponents.length > 0 && (
                <div>
                  <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
                    Current components
                  </h3>
                  <p className="mt-1 text-xs text-gray-400">
                    Active facts stay in the main model view. Superseded facts are separated below.
                  </p>
                </div>
              )}
              <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-5">
                {activeComponents.map((c) => (
                  <ComponentCard
                    key={c.id}
                    id={c.id}
                    name={c.name}
                    value={c.value}
                    confidence={c.confidence}
                    freshness={c.freshness}
                    last_verified_at={c.last_verified_at}
                    sources={c.sources}
                    sourceDocuments={c.sourceDocuments ?? c.source_documents}
                    authority_source={c.authority_source}
                    authority_weight={c.authorityWeight ?? c.authority_weight}
                    reviewStatus={c.reviewStatus ?? c.review_status}
                    reviewSummary={c.reviewSummary ?? c.review_summary}
                    temporalState={c.temporalState ?? c.temporal_state}
                    reviewItemId={c.reviewItemId ?? c.review_item_id}
                    decisionHistory={c.decisionHistory ?? c.decision_history}
                    onUpdate={isBackendData ? (body, opts) => updateMut.mutate(body, opts) : undefined}
                    onDelete={isBackendData ? (compId, opts) => deleteMut.mutate(compId, opts) : undefined}
                    updatePending={updateMut.isPending}
                    deletePending={deleteMut.isPending}
                    mutationError={
                      (updateMut.isError ? updateMut.error?.message : null) ||
                      (deleteMut.isError ? deleteMut.error?.message : null) ||
                      null
                    }
                  />
                ))}
              </div>
            </div>
          )}

          {historicalComponents.length > 0 && (
            <div className="space-y-4">
              <div>
                <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
                  Historical context
                </h3>
                <p className="mt-1 text-xs text-gray-400">
                  Older or superseded facts stay visible for time-travel context, but they are separated from current truth.
                </p>
              </div>
              <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-5">
                {historicalComponents.map((c) => (
                  <ComponentCard
                    key={c.id}
                    id={c.id}
                    name={c.name}
                    value={c.value}
                    confidence={c.confidence}
                    freshness={c.freshness}
                    last_verified_at={c.last_verified_at}
                    sources={c.sources}
                    sourceDocuments={c.sourceDocuments ?? c.source_documents}
                    authority_source={c.authority_source}
                    authority_weight={c.authorityWeight ?? c.authority_weight}
                    reviewStatus={c.reviewStatus ?? c.review_status}
                    reviewSummary={c.reviewSummary ?? c.review_summary}
                    temporalState={c.temporalState ?? c.temporal_state}
                    reviewItemId={c.reviewItemId ?? c.review_item_id}
                    decisionHistory={c.decisionHistory ?? c.decision_history}
                    onUpdate={isBackendData ? (body, opts) => updateMut.mutate(body, opts) : undefined}
                    onDelete={isBackendData ? (compId, opts) => deleteMut.mutate(compId, opts) : undefined}
                    updatePending={updateMut.isPending}
                    deletePending={deleteMut.isPending}
                    mutationError={
                      (updateMut.isError ? updateMut.error?.message : null) ||
                      (deleteMut.isError ? deleteMut.error?.message : null) ||
                      null
                    }
                  />
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* ── Relationships ───────────────────────── */}
      <RelationshipsPanel modelId={modelId} components={components} isBackendData={isBackendData} />
    </div>
  );
}

function isHistoricalComponent(component) {
  const temporalState = normalizeValue(component?.temporalState ?? component?.temporal_state);
  const reviewStatus = normalizeValue(component?.reviewStatus ?? component?.review_status);
  return temporalState === "historical" || temporalState === "superseded" || reviewStatus === "superseded";
}

function normalizeValue(value) {
  return typeof value === "string" && value.trim() ? value.trim().toLowerCase() : null;
}

function AddComponentForm({ modelId, onClose }) {
  const create = useCreateComponent(modelId);
  const [name, setName] = useState("");
  const [value, setValue] = useState("");
  const [confidence, setConfidence] = useState("0.9");
  const [authoritySource, setAuthoritySource] = useState("");

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!name.trim() || !value.trim()) return;
    create.mutate(
      {
        name: name.trim(),
        value: value.trim(),
        confidence: parseFloat(confidence) || 0.9,
        authority_source: authoritySource.trim() || null,
      },
      { onSuccess: () => onClose() },
    );
  };

  return (
    <div className="bg-white dark:bg-slate-800 rounded-xl border border-gray-200 dark:border-gray-800/50 p-5">
      <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-400 mb-4">Add component</h3>
      <form onSubmit={handleSubmit} className="grid sm:grid-cols-2 gap-3">
        <div>
          <label htmlFor="comp-name" className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">Name</label>
          <input
            id="comp-name"
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Monthly Recurring Revenue"
            required
            autoFocus
            className="w-full px-3 py-2 text-sm border border-gray-200 dark:border-gray-800/50 rounded-lg focus:outline-none focus:ring-2 focus:ring-brand-500/40"
          />
        </div>
        <div>
          <label htmlFor="comp-value" className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">Value</label>
          <input
            id="comp-value"
            type="text"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder="e.g. $2.4M"
            required
            className="w-full px-3 py-2 text-sm border border-gray-200 dark:border-gray-800/50 rounded-lg focus:outline-none focus:ring-2 focus:ring-brand-500/40"
          />
        </div>
        <div>
          <label htmlFor="comp-confidence" className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">Confidence (0–1)</label>
          <input
            id="comp-confidence"
            type="number"
            step="0.01"
            min="0"
            max="1"
            value={confidence}
            onChange={(e) => setConfidence(e.target.value)}
            className="w-full px-3 py-2 text-sm border border-gray-200 dark:border-gray-800/50 rounded-lg focus:outline-none focus:ring-2 focus:ring-brand-500/40"
          />
        </div>
        <div>
          <label htmlFor="comp-authority" className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">Authority source</label>
          <input
            id="comp-authority"
            type="text"
            value={authoritySource}
            onChange={(e) => setAuthoritySource(e.target.value)}
            placeholder="e.g. Stripe export"
            className="w-full px-3 py-2 text-sm border border-gray-200 dark:border-gray-800/50 rounded-lg focus:outline-none focus:ring-2 focus:ring-brand-500/40"
          />
        </div>
        {create.isError && (
          <p className="sm:col-span-2 text-xs text-red-600 dark:text-red-400">
            {create.error?.message || "Failed to add component."}
          </p>
        )}
        <div className="sm:col-span-2 flex gap-2 pt-1">
          <button
            type="submit"
            disabled={create.isPending || !name.trim() || !value.trim()}
            className="px-4 py-2 text-sm font-medium rounded-lg bg-brand-600 text-white hover:bg-brand-700 disabled:opacity-50 transition-colors"
          >
            {create.isPending ? "Adding..." : "Add Component"}
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
