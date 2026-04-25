import { useEffect } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useEvalCases, useEvalSummary, useRunEvals } from "../api/hooks";
import MockBadge from "../components/MockBadge";
import StatusView from "../components/StatusView";

const DOMAIN_BENCHMARKS = {
  pricing: {
    label: "What is our current enterprise pricing?",
    windowDays: 30,
  },
  blocker: {
    label: "What is currently blocking the SSO rollout?",
    windowDays: 30,
  },
  roadmap: {
    label: "What is the current SSO launch timeline?",
    windowDays: 30,
  },
  decision: {
    label: "Why did we choose SAML over OIDC?",
    windowDays: null,
  },
  meeting: {
    label: "What did we decide in the latest product review meeting?",
    windowDays: 30,
  },
};

export default function Accuracy() {
  const [searchParams, setSearchParams] = useSearchParams();
  const query = useEvalSummary();
  const summary = query.data;
  const selectedDomain = searchParams.get("domain") ?? "";
  const casesQuery = useEvalCases(selectedDomain, { enabled: !!selectedDomain });
  const runMutation = useRunEvals();
  const selectedDomainSummary =
    (summary?.domains ?? []).find((domain) => domain.domain === selectedDomain) ?? null;

  useEffect(() => {
    if (!summary?.domains?.length || selectedDomain) return;
    const firstWeakDomain =
      summary.domains.find(
        (domain) =>
          domain.passRate != null &&
          summary.threshold != null &&
          domain.passRate < summary.threshold,
      )?.domain ?? summary.domains[0]?.domain;
    if (!firstWeakDomain) return;

    const next = new URLSearchParams(searchParams);
    next.set("domain", firstWeakDomain);
    setSearchParams(next, { replace: true });
  }, [searchParams, selectedDomain, setSearchParams, summary]);

  if (query.isLoading || query.isError) {
    return (
      <div className="max-w-6xl mx-auto">
        <StatusView query={query} empty="No eval summary available yet." />
      </div>
    );
  }

  if (!summary) {
    return (
      <div className="max-w-6xl mx-auto">
        <AccuracyEmptyState runMutation={runMutation} />
      </div>
    );
  }

  const isHealthy =
    summary.passRate != null &&
    summary.threshold != null &&
    summary.passRate >= summary.threshold;

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-3">
            <h2 className="text-lg font-semibold text-gray-800 dark:text-gray-300">Accuracy</h2>
            {query.isMock && <MockBadge />}
          </div>
          <p className="text-xs text-gray-400 mt-1">
            Evaluate how well the context engine retrieves, extracts, and answers across startup-critical domains.
          </p>
          {query.isMock && (
            <p className="text-xs text-amber-600 dark:text-amber-400 mt-2">
              Showing demo accuracy data until the eval summary endpoint is available.
            </p>
          )}
        </div>
        <Link
          to="/app/review"
          className="rounded-lg border border-gray-200 dark:border-gray-800/50 bg-white dark:bg-slate-800 px-3 py-2 text-xs font-medium text-gray-700 dark:text-gray-400 hover:bg-gray-50 dark:bg-gray-900/30"
        >
          Open review queue
        </Link>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        {selectedDomainSummary && (
          <button
            type="button"
            onClick={() =>
              runMutation.mutate({
                domains: [selectedDomainSummary.domain],
                passThreshold: summary.threshold ?? undefined,
              })
            }
            disabled={runMutation.isPending}
            className="rounded-lg bg-brand-600 px-3 py-2 text-xs font-medium text-white hover:bg-brand-700 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {runMutation.isPending ? "Running evals..." : `Run ${selectedDomainSummary.domain} evals`}
          </button>
        )}
        <button
          type="button"
          onClick={() =>
            runMutation.mutate({
              passThreshold: summary.threshold ?? undefined,
            })
          }
          disabled={runMutation.isPending}
          className="rounded-lg border border-gray-200 dark:border-gray-800/50 bg-white dark:bg-slate-800 px-3 py-2 text-xs font-medium text-gray-700 dark:text-gray-400 hover:bg-gray-50 dark:bg-gray-900/30 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {runMutation.isPending ? "Running evals..." : "Run all evals"}
        </button>
        <p className="text-xs text-gray-500">
          Uses the backend eval runner when local/admin access is allowed.
        </p>
      </div>

      {runMutation.isError && (
        <div className="rounded-xl border border-amber-200 dark:border-amber-800/50 bg-amber-50 dark:bg-amber-900/30 px-4 py-3 text-sm text-amber-800 dark:text-amber-300">
          {formatEvalRunError(runMutation.error)}
        </div>
      )}

      {runMutation.isSuccess && (
        <div className="rounded-xl border border-emerald-200 dark:border-emerald-800/50 bg-emerald-50 dark:bg-emerald-900/30 px-4 py-3 text-sm text-emerald-800 dark:text-emerald-300">
          Eval run completed. Summary and case views have been refreshed.
        </div>
      )}

      <div
        className={`rounded-xl border p-5 ${
          isHealthy
            ? "border-emerald-200 dark:border-emerald-800/50 bg-emerald-50 dark:bg-emerald-900/30"
            : "border-amber-200 dark:border-amber-800/50 bg-amber-50 dark:bg-amber-900/30"
        }`}
      >
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className={`text-sm font-medium ${isHealthy ? "text-emerald-800 dark:text-emerald-300" : "text-amber-800 dark:text-amber-300"}`}>
              {isHealthy ? "Accuracy is above the current threshold" : "Accuracy still needs hardening"}
            </p>
            <p className={`mt-1 text-xs ${isHealthy ? "text-emerald-700 dark:text-emerald-400" : "text-amber-700 dark:text-amber-400"}`}>
              Latest eval run {formatDateTime(summary.latestRunAt)}.
              {summary.threshold != null ? ` Current gate: ${formatPercent(summary.threshold)}.` : ""}
            </p>
          </div>
          <div className="text-right">
            <p className="text-[11px] uppercase tracking-wide text-gray-500">Pass rate</p>
            <p className="mt-1 text-3xl font-semibold text-gray-900 dark:text-gray-200">
              {formatPercent(summary.passRate)}
            </p>
          </div>
        </div>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard label="Passed cases" value={`${summary.passedCases ?? 0}/${summary.totalCases ?? 0}`} />
        <MetricCard label="Threshold" value={formatPercent(summary.threshold)} />
        <MetricCard label="Domains" value={String(summary.domains?.length ?? 0)} />
        <MetricCard label="Metrics tracked" value={String(summary.metrics?.length ?? 0)} />
      </div>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.2fr)_minmax(320px,0.8fr)]">
        <section className="bg-white dark:bg-slate-800 rounded-xl border border-gray-200 dark:border-gray-800/50 p-5">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-400">Domain breakdown</h3>
              <p className="text-xs text-gray-400 mt-1">
                High-value startup workflows should clear the threshold before you market strong trust claims.
              </p>
            </div>
          </div>
          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            {(summary.domains ?? []).map((domain) => (
              <div key={domain.domain} className="rounded-xl border border-gray-200 dark:border-gray-800/50 bg-gray-50 dark:bg-gray-900/30 px-4 py-4">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-sm font-semibold text-gray-800 dark:text-gray-300 capitalize">
                      {domain.domain}
                    </p>
                    <p className="mt-1 text-xs text-gray-500">
                      {domain.passed}/{domain.total} cases passing
                    </p>
                  </div>
                  <span
                    className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${
                      domain.passRate != null && summary.threshold != null && domain.passRate >= summary.threshold
                        ? "bg-emerald-100 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-400"
                        : "bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-400"
                    }`}
                  >
                    {formatPercent(domain.passRate)}
                  </span>
                </div>
                <div className="mt-4 flex items-center justify-between gap-3">
                  <p className="text-[11px] text-gray-500">
                    {domain.passRate != null &&
                    summary.threshold != null &&
                    domain.passRate < summary.threshold
                      ? "Below threshold. Run a benchmark query and inspect the trust path."
                      : "Healthy enough to spot-check with a benchmark query."}
                  </p>
                  <div className="flex items-center gap-3">
                    <button
                      type="button"
                      onClick={() => {
                        const next = new URLSearchParams(searchParams);
                        next.set("domain", domain.domain);
                        setSearchParams(next);
                      }}
                      className="shrink-0 text-xs font-medium text-gray-600 dark:text-gray-400 hover:text-gray-800 dark:text-gray-300"
                    >
                      Inspect cases
                    </button>
                    <Link
                      to={buildBenchmarkQueryLink(domain.domain)}
                      className="shrink-0 text-xs font-medium text-brand-700 dark:text-brand-400 hover:text-brand-800 dark:text-brand-300"
                    >
                      Try benchmark query
                    </Link>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </section>

        <section className="bg-white dark:bg-slate-800 rounded-xl border border-gray-200 dark:border-gray-800/50 p-5">
          <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-400">Current blockers</h3>
          <p className="text-xs text-gray-400 mt-1">
            The biggest remaining issues before you can credibly market source-backed accuracy.
          </p>
          {(summary.blockers ?? []).length > 0 ? (
            <ul className="mt-4 space-y-3">
              {summary.blockers.map((blocker) => (
                <li
                  key={blocker}
                  className="rounded-lg border border-amber-200 dark:border-amber-800/50 bg-amber-50 dark:bg-amber-900/30 px-3 py-3 text-sm text-amber-800 dark:text-amber-300"
                >
                  {blocker}
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-4 text-sm text-gray-500">No blockers recorded.</p>
          )}
        </section>
      </div>

      <section className="bg-white dark:bg-slate-800 rounded-xl border border-gray-200 dark:border-gray-800/50 p-5">
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-400">
                {selectedDomainSummary ? `${selectedDomainSummary.domain} cases` : "Eval cases"}
              </h3>
              {casesQuery.isMock && selectedDomain && <MockBadge />}
            </div>
            <p className="text-xs text-gray-400 mt-1">
              Case-level failures make it easier to debug whether retrieval, extraction, or final answers are breaking.
            </p>
          </div>
          {selectedDomainSummary && (
            <Link
              to={buildBenchmarkQueryLink(selectedDomainSummary.domain)}
              className="text-xs font-medium text-brand-700 dark:text-brand-400 hover:text-brand-800 dark:text-brand-300"
            >
              Run domain benchmark query
            </Link>
          )}
        </div>

        {!selectedDomain ? (
          <p className="mt-4 text-sm text-gray-500">Select a domain to inspect its eval cases.</p>
        ) : casesQuery.isLoading ? (
          <div className="mt-4">
            <StatusView query={casesQuery} empty="No eval cases available yet." />
          </div>
        ) : casesQuery.isError ? (
          <div className="mt-4">
            <StatusView query={casesQuery} empty="No eval cases available yet." />
          </div>
        ) : (casesQuery.data?.cases?.length ?? 0) > 0 ? (
          <div className="mt-4 space-y-3">
            {casesQuery.data.cases.map((item) => (
              <EvalCaseCard key={item.caseId ?? item.question} item={item} />
            ))}
          </div>
        ) : (
          <p className="mt-4 text-sm text-gray-500">No eval cases available for this domain yet.</p>
        )}
      </section>

      <section className="bg-white dark:bg-slate-800 rounded-xl border border-gray-200 dark:border-gray-800/50 p-5">
        <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-400">Metric summary</h3>
        <p className="text-xs text-gray-400 mt-1">
          Retrieval, citations, freshness, answer quality, and baseline lift are shown separately so regressions stay visible.
        </p>
        <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {(summary.metrics ?? []).map((metric) => (
            <EvalMetricCard
              key={metric.key}
              label={metric.label}
              value={metric.value}
              target={metric.target}
              direction={metric.direction}
            />
          ))}
        </div>
      </section>
    </div>
  );
}

function AccuracyEmptyState({ runMutation }) {
  return (
    <div className="rounded-xl border border-gray-200 dark:border-gray-800/50 bg-white dark:bg-slate-800 p-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold text-gray-800 dark:text-gray-300">Accuracy</h2>
          <p className="text-xs text-gray-400 mt-1">
            Accuracy data is not ready yet for this workspace.
          </p>
        </div>
        <Link
          to="/app/sources"
          className="rounded-lg border border-gray-200 dark:border-gray-800/50 bg-white dark:bg-slate-800 px-3 py-2 text-xs font-medium text-gray-700 dark:text-gray-400 hover:bg-gray-50 dark:bg-gray-900/30"
        >
          Open sources
        </Link>
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={() => runMutation.mutate({})}
          disabled={runMutation.isPending}
          className="rounded-lg bg-brand-600 px-3 py-2 text-xs font-medium text-white hover:bg-brand-700 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {runMutation.isPending ? "Running evals..." : "Run evals now"}
        </button>
        <p className="text-xs text-gray-500">
          This works when the backend eval runner is enabled for your local/admin environment.
        </p>
      </div>

      <div className="mt-5 grid gap-3 md:grid-cols-3">
        <QuickStartCard
          title="1. Sync real sources"
          description="Accuracy runs only become meaningful after Slack, Notion, Zoom, or other connectors have stored source documents."
        />
        <QuickStartCard
          title="2. Review extracted facts"
          description="Resolve low-confidence or conflicting facts first so the eval run reflects real trust policy, not a half-reviewed workspace."
        />
        <QuickStartCard
          title="3. Run the eval command"
          description="From the backend, run the eval regression command for the selected workspace so this dashboard has live results to display."
        />
      </div>

      <div className="mt-5 rounded-xl border border-gray-200 dark:border-gray-800/50 bg-gray-50 dark:bg-gray-900/30 px-4 py-4">
        <p className="text-xs font-medium text-gray-700 dark:text-gray-400">Typical self-host flow</p>
        <code className="mt-2 block rounded-lg bg-gray-900 px-3 py-3 text-xs text-gray-100 overflow-x-auto">
          python3 scripts/run_eval_regression.py --workspace-id &lt;workspace-id&gt;
        </code>
      </div>

      <div className="mt-4 flex flex-wrap gap-4 text-xs">
        <Link to="/app/review" className="font-medium text-brand-700 dark:text-brand-400 hover:text-brand-800 dark:text-brand-300">
          Open review queue
        </Link>
        <Link to="/app/query" className="font-medium text-brand-700 dark:text-brand-400 hover:text-brand-800 dark:text-brand-300">
          Open query
        </Link>
      </div>

      {runMutation.isError && (
        <div className="mt-5 rounded-xl border border-amber-200 dark:border-amber-800/50 bg-amber-50 dark:bg-amber-900/30 px-4 py-3 text-sm text-amber-800 dark:text-amber-300">
          {formatEvalRunError(runMutation.error)}
        </div>
      )}

      {runMutation.isSuccess && (
        <div className="mt-5 rounded-xl border border-emerald-200 dark:border-emerald-800/50 bg-emerald-50 dark:bg-emerald-900/30 px-4 py-3 text-sm text-emerald-800 dark:text-emerald-300">
          Eval run completed. Refreshing accuracy results.
        </div>
      )}
    </div>
  );
}

function QuickStartCard({ title, description }) {
  return (
    <div className="rounded-xl border border-gray-200 dark:border-gray-800/50 bg-gray-50 dark:bg-gray-900/30 px-4 py-4">
      <p className="text-sm font-semibold text-gray-800 dark:text-gray-300">{title}</p>
      <p className="mt-2 text-xs text-gray-600 dark:text-gray-400">{description}</p>
    </div>
  );
}

function EvalCaseCard({ item }) {
  return (
    <div className="rounded-xl border border-gray-200 dark:border-gray-800/50 bg-gray-50 dark:bg-gray-900/30 p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <span
              className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${
                item.passed ? "bg-emerald-100 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-400" : "bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-400"
              }`}
            >
              {item.passed ? "Passed" : "Needs work"}
            </span>
            {item.caseId && <span className="text-[11px] text-gray-400">{item.caseId}</span>}
          </div>
          <p className="mt-2 text-sm font-medium text-gray-800 dark:text-gray-300">{item.question}</p>
          {item.detail && <p className="mt-2 text-xs text-gray-500">{item.detail}</p>}
        </div>
        <span className="text-sm font-semibold text-gray-900 dark:text-gray-200">
          {formatPercent(item.finalAnswerCorrectness)}
        </span>
      </div>
      <div className="mt-4 grid gap-3 sm:grid-cols-3">
        <SmallMetric label="Retrieval" value={item.retrievalHitQuality} />
        <SmallMetric label="Extraction" value={item.extractedFactCorrectness} />
        <SmallMetric label="Answer" value={item.finalAnswerCorrectness} />
        <SmallMetric label="Citation" value={item.citationAccuracy} />
        <SmallMetric label="Staleness" value={item.staleContextDetection} />
        <SmallMetric label="Lift" value={item.contextAnswerLift} signed />
      </div>
      {item.predictedConfidence != null && (
        <p className="mt-3 text-[11px] text-gray-500">
          Predicted confidence {formatPercent(item.predictedConfidence)}
        </p>
      )}
    </div>
  );
}

function MetricCard({ label, value }) {
  return (
    <div className="rounded-xl border border-gray-200 dark:border-gray-800/50 bg-white dark:bg-slate-800 px-4 py-4">
      <p className="text-[11px] uppercase tracking-wide text-gray-400">{label}</p>
      <p className="mt-2 text-2xl font-semibold text-gray-900 dark:text-gray-200">{value}</p>
    </div>
  );
}

function SmallMetric({ label, value, signed = false }) {
  return (
    <div className="rounded-lg border border-gray-200 dark:border-gray-800/50 bg-white dark:bg-slate-800 px-3 py-3">
      <p className="text-[11px] uppercase tracking-wide text-gray-400">{label}</p>
      <p className="mt-1 text-lg font-semibold text-gray-900 dark:text-gray-200">
        {signed ? formatSignedScore(value) : formatPercent(value)}
      </p>
    </div>
  );
}

function EvalMetricCard({ label, value, target, direction }) {
  const isHealthy =
    target == null || value == null
      ? true
      : direction === "down"
        ? value <= target
        : value >= target;

  return (
    <div className="rounded-xl border border-gray-200 dark:border-gray-800/50 bg-gray-50 dark:bg-gray-900/30 px-4 py-4">
      <div className="flex items-start justify-between gap-3">
        <p className="text-sm font-medium text-gray-800 dark:text-gray-300">{label}</p>
        <span
          className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${
            isHealthy ? "bg-emerald-100 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-400" : "bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-400"
          }`}
        >
          {direction === "down" ? "Lower is better" : "Higher is better"}
        </span>
      </div>
      <p className="mt-3 text-2xl font-semibold text-gray-900 dark:text-gray-200">{formatPercent(value)}</p>
      {target != null && (
        <p className="mt-1 text-xs text-gray-500">
          Target {formatPercent(target)}
        </p>
      )}
    </div>
  );
}

function formatPercent(value) {
  if (value == null) return "—";
  return `${Math.round(value * 100)}%`;
}

function formatSignedScore(value) {
  if (value == null) return "—";
  const rounded = Math.round(value * 100);
  return `${rounded >= 0 ? "+" : ""}${rounded} pts`;
}

function formatDateTime(value) {
  if (!value) return "—";
  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}

function formatEvalRunError(error) {
  const detail =
    error?.detail ??
    error?.message ??
    "Unable to run evals right now.";

  if (Array.isArray(detail)) {
    return detail.map((item) => item?.msg ?? String(item)).join(", ");
  }
  if (typeof detail === "object" && detail !== null) {
    return detail.detail ?? JSON.stringify(detail);
  }
  return String(detail);
}

function buildBenchmarkQueryLink(domain) {
  const benchmark = DOMAIN_BENCHMARKS[domain] ?? {
    label: `What is the current state of ${domain}?`,
    windowDays: 30,
  };
  const params = new URLSearchParams({ question: benchmark.label });
  if (benchmark.windowDays != null) {
    params.set("window", String(benchmark.windowDays));
  }
  return `/app/query?${params.toString()}`;
}
