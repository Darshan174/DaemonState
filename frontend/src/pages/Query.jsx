import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useComponentSources, useContextQuery } from "../api/hooks";
import MockBadge from "../components/MockBadge";
import SourceDocumentLinks from "../components/SourceDocumentLinks";
import TrustStatePanel from "../components/TrustStatePanel";

const FRESHNESS_STYLE = {
  current: "bg-emerald-50 text-emerald-700 border-emerald-200",
  possibly_stale: "bg-amber-50 text-amber-700 border-amber-200",
  stale: "bg-red-50 text-red-700 border-red-200",
};

const FRESHNESS_LABEL = {
  current: "Current",
  possibly_stale: "Possibly stale",
  stale: "Stale",
};

const WINDOW_OPTIONS = [
  { value: "all", label: "All time" },
  { value: "7", label: "Last 7 days" },
  { value: "30", label: "Last 30 days" },
];

export default function Query() {
  const [searchParams] = useSearchParams();
  const [input, setInput] = useState("");
  const [windowDays, setWindowDays] = useState("all");
  const [asOfDate, setAsOfDate] = useState("");
  const [lastRequestMeta, setLastRequestMeta] = useState({
    question: "",
    maxAgeDays: null,
    asOf: null,
  });
  const mutation = useContextQuery();
  const result = mutation.data;
  const components = result?.components ?? [];
  const currentComponents = components.filter((component) => !isHistoricalComponent(component));
  const historicalComponents = components.filter(isHistoricalComponent);
  const isMock = result?._isMock ?? false;
  const isNoMatch =
    result &&
    result.confidence === 0 &&
    components.length === 0 &&
    (!result.sources || result.sources.length === 0);

  useEffect(() => {
    const nextQuestion = searchParams.get("question") ?? "";
    const nextWindow = searchParams.get("window");
    const nextAsOf = searchParams.get("as_of") ?? searchParams.get("asOf") ?? "";

    setInput(nextQuestion);
    setWindowDays(nextWindow && WINDOW_OPTIONS.some((option) => option.value === nextWindow) ? nextWindow : "all");
    setAsOfDate(normalizeAsOfSearchParam(nextAsOf));
  }, [searchParams]);

  const handleSubmit = (e) => {
    e.preventDefault();
    const q = input.trim();
    if (!q) return;
    const payload = buildQueryPayload(q, windowDays, asOfDate);
    setLastRequestMeta({
      question: q,
      maxAgeDays: payload.maxAgeDays ?? null,
      asOf: payload.asOf ?? null,
    });
    mutation.mutate(payload.maxAgeDays != null || payload.asOf ? payload : payload.question);
  };

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      <div className="flex items-center gap-3">
        <h2 className="text-lg font-semibold text-gray-800">Ask the workspace</h2>
        {isMock && result && <MockBadge />}
        {!isMock && result && (
          <span className="px-2 py-0.5 text-[11px] rounded-full border border-emerald-200 bg-emerald-50 text-emerald-700">
            Live backend
          </span>
        )}
      </div>
      <p className="text-xs text-gray-400">
        Query your workspace context. Live backend answers are preferred; demo answers only appear when the backend is unreachable.
      </p>

      <div className="rounded-xl border border-gray-200 bg-white p-4">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h3 className="text-sm font-semibold text-gray-700">Self-host query flow</h3>
            <p className="text-xs text-gray-400 mt-1">
              Query works best after raw sources are synced, extracted facts are reviewed, and benchmark cases clear the current accuracy gate.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-3 text-xs">
            <Link to="/app/sources" className="font-medium text-brand-700 hover:text-brand-800">
              Inspect sources
            </Link>
            <Link to="/app/review" className="font-medium text-brand-700 hover:text-brand-800">
              Review trust
            </Link>
            <Link to="/app/accuracy" className="font-medium text-brand-700 hover:text-brand-800">
              Benchmark accuracy
            </Link>
          </div>
        </div>
      </div>

      {/* ── Input ───────────────────────────────── */}
      <form onSubmit={handleSubmit} className="space-y-3">
        <div className="flex gap-3">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask a question about your company data..."
            aria-label="Query input"
            className="flex-1 px-4 py-2.5 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-brand-500/40"
          />
          <button
            type="submit"
            disabled={mutation.isPending || !input.trim()}
            className="px-5 py-2.5 text-sm font-medium rounded-lg bg-brand-600 text-white hover:bg-brand-700 disabled:opacity-50 transition-colors shrink-0"
          >
            {mutation.isPending ? "Thinking..." : "Ask"}
          </button>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <label className="flex items-center gap-2 text-xs text-gray-500">
            <span>Context window</span>
            <select
              value={windowDays}
              onChange={(e) => setWindowDays(e.target.value)}
              aria-label="Context window"
              className="rounded-lg border border-gray-200 bg-white px-2.5 py-1.5 text-xs text-gray-700 focus:outline-none focus:ring-2 focus:ring-brand-500/40"
            >
              {WINDOW_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label className="flex items-center gap-2 text-xs text-gray-500">
            <span>As of</span>
            <input
              type="date"
              value={asOfDate}
              onChange={(e) => setAsOfDate(e.target.value)}
              aria-label="As of date"
              className="rounded-lg border border-gray-200 bg-white px-2.5 py-1.5 text-xs text-gray-700 focus:outline-none focus:ring-2 focus:ring-brand-500/40"
            />
          </label>
          {asOfDate && (
            <button
              type="button"
              onClick={() => setAsOfDate("")}
              className="text-[11px] font-medium text-gray-500 underline underline-offset-2 hover:text-gray-700"
            >
              Clear historical mode
            </button>
          )}
          <p className="text-[11px] text-gray-400">
            Use a recent window for fresher truth, or set an as-of date to inspect historical context.
          </p>
        </div>
      </form>

      {/* ── Loading ─────────────────────────────── */}
      {mutation.isPending && (
        <div role="status" aria-live="polite" className="flex items-center gap-3 py-8 justify-center text-gray-400">
          <svg className="animate-spin h-5 w-5 text-brand-600" viewBox="0 0 24 24" fill="none">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>
          <span className="text-sm">Querying knowledge graph...</span>
        </div>
      )}

      {/* ── Error ───────────────────────────────── */}
      {mutation.isError && (
        <div role="alert" className="bg-red-50 border border-red-200 rounded-xl p-4 text-center">
          <p className="text-sm text-red-600">
            {mutation.error?.message || "Failed to get an answer."}
          </p>
          <button
            onClick={() => {
              const payload = buildQueryPayload(input.trim(), windowDays, asOfDate);
              setLastRequestMeta({
                question: input.trim(),
                maxAgeDays: payload.maxAgeDays ?? null,
                asOf: payload.asOf ?? null,
              });
              mutation.mutate(payload.maxAgeDays != null || payload.asOf ? payload : payload.question);
            }}
            disabled={!input.trim()}
            className="mt-3 px-3 py-1.5 text-xs font-medium rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50 transition-colors"
          >
            Retry
          </button>
        </div>
      )}

      {/* ── No-match ─────────────────────────────── */}
      {result && !mutation.isPending && isNoMatch && (
        <div className="space-y-4">
          <div className="bg-gray-100 rounded-xl px-5 py-3">
            <p className="text-sm text-gray-600 font-medium">{result.question}</p>
          </div>
          <div className="bg-amber-50 border border-amber-200 rounded-xl p-5 text-center space-y-2">
            <p className="text-sm font-medium text-amber-700">No grounded answer found</p>
            <p className="text-xs text-amber-600">
              {result.answer || "The knowledge graph does not contain enough structured context to answer this question."}
            </p>
            {lastRequestMeta.maxAgeDays != null && (
              <p className="text-xs text-amber-700">
                Try widening the context window if this answer may depend on older company context.
              </p>
            )}
            {lastRequestMeta.asOf && (
              <p className="text-xs text-amber-700">
                Try a more recent as-of date or clear historical mode if this answer depends on the current state of the company.
              </p>
            )}
            {!isMock && (
              <p className="text-xs text-amber-700">
                If you recently connected Slack, run a sync from{" "}
                <Link to="/app/connectors" className="underline underline-offset-2">
                  Connectors
                </Link>{" "}
                and try again.
              </p>
            )}
            <p className="text-xs text-amber-700">
              Then inspect{" "}
              <Link to="/app/sources" className="underline underline-offset-2">
                Sources
              </Link>{" "}
              and{" "}
              <Link to="/app/review" className="underline underline-offset-2">
                Review
              </Link>{" "}
              to see whether the problem is missing raw context or unresolved trust state.
            </p>
          </div>
        </div>
      )}

      {/* ── Answer ──────────────────────────────── */}
      {result && !mutation.isPending && !isNoMatch && (
        <div className="space-y-4">
          {/* Question echo */}
          <div className="bg-gray-100 rounded-xl px-5 py-3">
            <p className="text-sm text-gray-600 font-medium">{result.question}</p>
          </div>

          {/* Answer body */}
          <div className="bg-white border border-gray-200 rounded-xl p-5 space-y-4">
            {!isMock && (
              <div className="flex flex-wrap items-center gap-2 text-[11px] text-gray-500">
                <span className="px-2 py-0.5 rounded-full bg-gray-100 text-gray-600">
                  Live workspace context
                </span>
                {lastRequestMeta.maxAgeDays != null && (
                  <span className="px-2 py-0.5 rounded-full bg-blue-50 text-blue-700 border border-blue-200">
                    Window: {formatWindowLabel(lastRequestMeta.maxAgeDays)}
                  </span>
                )}
                {lastRequestMeta.asOf && (
                  <span className="px-2 py-0.5 rounded-full bg-amber-50 text-amber-700 border border-amber-200">
                    As of: {formatAsOfLabel(lastRequestMeta.asOf)}
                  </span>
                )}
                <span>
                  Grounded in {components.length} component{components.length === 1 ? "" : "s"}
                  {" "}from {result.sources?.length ?? 0} source{result.sources?.length === 1 ? "" : "s"}.
                </span>
              </div>
            )}
            <TrustStatePanel
              reviewStatus={result.reviewStatus ?? result.review_status}
              reviewSummary={result.reviewSummary ?? result.review_summary}
              temporalState={result.temporalState ?? result.temporal_state}
              reviewItemId={result.reviewItemId ?? result.review_item_id}
              className="mt-1"
            />
            {result.answer ? (
              <div className="text-sm text-gray-800 leading-relaxed space-y-2">
                {result.answer.split("\n").filter(Boolean).map((line, i) => (
                  <p key={i}>{line}</p>
                ))}
              </div>
            ) : (
              <p className="text-sm text-gray-400 italic">No answer could be determined for this query.</p>
            )}

            {/* Confidence */}
            {result.confidence != null && (
              <div className="flex items-center gap-3">
                <span className="text-xs text-gray-400">Confidence</span>
                <div className="flex-1 h-1.5 bg-gray-100 rounded-full overflow-hidden max-w-[200px]">
                  <div
                    className={`h-full rounded-full ${
                      result.confidence >= 0.9
                        ? "bg-emerald-500"
                        : result.confidence >= 0.75
                          ? "bg-amber-400"
                          : "bg-red-400"
                    }`}
                    style={{ width: `${Math.round(result.confidence * 100)}%` }}
                  />
                </div>
                <span className="text-xs text-gray-500">{Math.round(result.confidence * 100)}%</span>
              </div>
            )}

            {/* Freshness + timestamp */}
            <div className="flex items-center gap-2">
              {result.freshness && (
                <span
                  className={`px-2 py-0.5 text-[11px] rounded-full border ${
                    FRESHNESS_STYLE[result.freshness] || "bg-blue-50 text-blue-700 border-blue-200"
                  }`}
                >
                  {FRESHNESS_LABEL[result.freshness] || result.freshness}
                </span>
              )}
              {result.answeredAt && (
                <p className="text-[11px] text-gray-300">{result.answeredAt}</p>
              )}
            </div>
          </div>

          {/* Cited components */}
          {components.length > 0 && (
            <div className="bg-white border border-gray-200 rounded-xl p-5">
              {currentComponents.length > 0 && (
                <>
                  <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">
                    Cited Components
                  </h3>
                  <div className="divide-y divide-gray-100">
                    {currentComponents.map((c) => (
                      <ComponentEvidenceRow key={c.id} component={c} />
                    ))}
                  </div>
                </>
              )}

              {historicalComponents.length > 0 && (
                <div className={currentComponents.length > 0 ? "mt-5 pt-5 border-t border-gray-100" : ""}>
                  <div className="mb-3">
                    <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
                      Historical Context
                    </h3>
                    <p className="mt-1 text-xs text-gray-400">
                      Older or superseded facts are separated here so they do not read like current truth.
                    </p>
                  </div>
                  <div className="divide-y divide-gray-100">
                    {historicalComponents.map((c) => (
                      <ComponentEvidenceRow key={c.id} component={c} />
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {(result.sourceDocuments ?? result.source_documents)?.length > 0 && (
            <div className="bg-white border border-gray-200 rounded-xl p-5">
              <SourceDocumentLinks
                items={result.sourceDocuments ?? result.source_documents}
                label="Supporting documents"
                showMeta={true}
              />
            </div>
          )}

          {/* Sources */}
          {result.sources?.length > 0 && (
            <div className="bg-white border border-gray-200 rounded-xl p-5">
              <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">
                Sources
              </h3>
              <div className="flex flex-wrap gap-2">
                {result.sources.map((s, i) => (
                  <SourceChip key={typeof s === "string" ? s : i} source={s} />
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* ── Empty / hint ────────────────────────── */}
      {!result && !mutation.isPending && !mutation.isError && (
        <div className="rounded-[32px] border border-gray-200 bg-white p-12 text-center shadow-sm mt-8">
          <div className="mx-auto w-16 h-16 bg-brand-50 text-brand-600 rounded-full flex items-center justify-center mb-6">
            <svg className="w-8 h-8" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
            </svg>
          </div>
          <h2 className="text-xl font-bold text-gray-900">Ask a question to query your knowledge graph.</h2>
          <p className="mt-3 text-sm text-gray-500 max-w-lg mx-auto leading-relaxed">
            For a self-hosted install, the fastest path is sync real sources first, review conflicts, then use query to pressure-test the current trust graph.
          </p>
          <div className="flex flex-wrap justify-center gap-3 pt-6">
            {["What is our current MRR?", "How healthy are our customers?"].map((q) => (
              <button
                key={q}
                onClick={() => {
                  setInput(q);
                  const payload = buildQueryPayload(q, windowDays, asOfDate);
                  setLastRequestMeta({
                    question: q,
                    maxAgeDays: payload.maxAgeDays ?? null,
                    asOf: payload.asOf ?? null,
                  });
                  mutation.mutate(payload.maxAgeDays != null || payload.asOf ? payload : payload.question);
                }}
                className="px-4 py-2 text-sm font-medium rounded-xl border border-gray-200 text-gray-600 hover:bg-brand-50 hover:text-brand-700 hover:border-brand-200 transition-colors shadow-sm"
              >
                {q}
              </button>
            ))}
          </div>
          <div className="flex flex-wrap justify-center gap-4 text-xs mt-8">
            <Link to="/app" className="font-medium text-brand-700 hover:text-brand-800">
              Add context
            </Link>
            <Link to="/app/review" className="font-medium text-brand-700 hover:text-brand-800">
              Review trust issues
            </Link>
            <Link to="/app/accuracy" className="font-medium text-brand-700 hover:text-brand-800">
              Benchmark accuracy
            </Link>
          </div>
        </div>
      )}
    </div>
  );
}

function ComponentEvidenceRow({ component: c }) {
  const provenanceQuery = useComponentSources(c.id, {
    enabled: !!c.id && !((c.sourceDocuments ?? c.source_documents)?.length > 0),
  });
  const sourceDocuments =
    (c.sourceDocuments ?? c.source_documents)?.length > 0
      ? (c.sourceDocuments ?? c.source_documents)
      : provenanceQuery.data ?? [];

  return (
    <div className="py-2.5">
      <div className="flex items-center justify-between">
        <div>
          <span className="text-sm font-medium text-gray-700">{c.name}</span>
          {c.model && (
            <span className="ml-2 text-xs text-gray-400">{c.model}</span>
          )}
        </div>
        <span className="text-sm font-semibold text-gray-900">{c.value}</span>
      </div>
      {(c.confidence != null || c.authority_source || c.last_verified_at) && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 mt-1.5 text-[11px] text-gray-400">
          {c.confidence != null && (
            <span>{Math.round(c.confidence * 100)}% confidence</span>
          )}
          {c.authority_source && (
            <span>via {c.authority_source}</span>
          )}
          {c.last_verified_at && (
            <span>verified {formatDate(c.last_verified_at)}</span>
          )}
        </div>
      )}
      <TrustStatePanel
        reviewStatus={c.reviewStatus ?? c.review_status}
        reviewSummary={c.reviewSummary ?? c.review_summary}
        temporalState={c.temporalState ?? c.temporal_state}
        reviewItemId={c.reviewItemId ?? c.review_item_id}
        compact
        className="mt-2"
      />
      {sourceDocuments.length > 0 && (
        <div className="mt-3">
          <SourceDocumentLinks
            items={sourceDocuments}
            label="Evidence"
            compact
            showMeta
          />
        </div>
      )}
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

function SourceChip({ source }) {
  if (!source) return null;
  if (typeof source !== "object") {
    return (
      <span className="px-2.5 py-1 text-xs rounded-full bg-gray-100 text-gray-600">
        {String(source)}
      </span>
    );
  }
  const label = source.type || source.url || "Source";
  const meta = [source.author, source.date].filter(Boolean).join(" · ");
  return (
    <span
      className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs rounded-full bg-gray-100 text-gray-600"
      title={meta || undefined}
    >
      {source.url ? (
        <a href={source.url} target="_blank" rel="noopener noreferrer" className="underline">
          {label}
        </a>
      ) : (
        label
      )}
      {meta && <span className="text-gray-400">{meta}</span>}
    </span>
  );
}

function formatDate(iso) {
  if (!iso) return null;
  try {
    return new Date(iso).toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
      year: "numeric",
    });
  } catch {
    return iso;
  }
}

function SearchIcon() {
  return (
    <svg className="w-10 h-10 mx-auto text-gray-300" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
    </svg>
  );
}

function buildQueryPayload(question, windowDays, asOfDate = "") {
  const trimmed = question.trim();
  const days = windowDays === "all" ? null : Number(windowDays);
  const asOf =
    typeof asOfDate === "string" && asOfDate.trim()
      ? new Date(`${asOfDate}T00:00:00Z`).toISOString()
      : null;
  return {
    question: trimmed,
    maxAgeDays: Number.isFinite(days) ? days : null,
    ...(asOf ? { asOf } : {}),
  };
}

function formatWindowLabel(days) {
  if (days == null) return "All time";
  return `last ${days} day${days === 1 ? "" : "s"}`;
}

function formatAsOfLabel(value) {
  if (!value) return "—";
  try {
    return new Date(value).toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
      year: "numeric",
    });
  } catch {
    return value;
  }
}

function normalizeAsOfSearchParam(value) {
  if (!value) return "";
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return value;
  try {
    return new Date(value).toISOString().slice(0, 10);
  } catch {
    return "";
  }
}
