import { useMemo } from "react";
import { Link } from "react-router-dom";
import MockBadge from "../components/MockBadge";
import StatusView from "../components/StatusView";
import {
  useEvalSummary,
  useFounderBrief,
  useSourceDocuments,
} from "../api/hooks";

export default function FounderBrief() {
  const briefQuery = useFounderBrief();
  const evalQuery = useEvalSummary();
  const engineeringQuery = useSourceDocuments({
    connector: "github",
    processed: "all",
    search: "",
  });

  const queries = [briefQuery, evalQuery];
  const loading = queries.some((query) => query.isLoading);
  const errorQuery = queries.find((query) => query.isError);
  const founderBrief = briefQuery.data;
  const evalSummary = evalQuery.data ?? null;

  const brief = useMemo(
    () =>
      buildFounderBrief({
        founderBrief,
        evalSummary,
        engineeringItems: engineeringQuery.data ?? [],
      }),
    [engineeringQuery.data, evalSummary, founderBrief],
  );

  if (loading || errorQuery) {
    return (
      <div className="max-w-6xl mx-auto">
        <StatusView
          query={
            errorQuery ?? {
              isLoading: loading,
              isError: false,
              refetch: () => Promise.all(queries.map((query) => query.refetch?.())),
            }
          }
          empty="No founder brief is available yet."
        />
      </div>
    );
  }

  if (!brief.hasData) {
    return (
      <div className="max-w-6xl mx-auto">
        <FounderBriefEmptyState />
      </div>
    );
  }

  const usesMockData = queries.some((query) => query.isMock) || engineeringQuery.isMock;

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-3">
            <h2 className="text-lg font-semibold text-gray-800">Brief</h2>
            {usesMockData && <MockBadge />}
          </div>
          <p className="text-xs text-gray-400 mt-1">
            A live roll-up of current decisions, review pressure, connector risk, and accuracy pressure.
          </p>
        </div>
        <div className="flex items-center gap-3 text-xs">
          <Link to="/app/changes" className="font-medium text-brand-700 hover:text-brand-800">
            Open timeline
          </Link>
          <Link to="/app/decisions" className="font-medium text-brand-700 hover:text-brand-800">
            Open decision register
          </Link>
        </div>
      </div>

      <div className="rounded-xl border border-gray-200 bg-white p-5">
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-sm font-semibold text-gray-800">Current picture</p>
            <p className="mt-1 text-sm text-gray-600">
              {brief.headline}
            </p>
          </div>
          <p className="text-xs text-gray-400">Updated {formatDateTime(brief.generatedAt)}</p>
        </div>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard label="Changed facts" value={brief.changedFactCount} />
        <MetricCard label="New blockers" value={brief.newBlockerCount} tone="amber" />
        <MetricCard label="Open conflicts" value={brief.openConflictCount} tone="amber" />
        <MetricCard label="At-risk domains" value={brief.atRiskDomainCount} tone="slate" />
      </div>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.1fr)_minmax(0,0.9fr)]">
        <section className="space-y-6">
          <Panel
            title="What changed"
            subtitle="Recent source-backed fact changes worth scanning first."
            action={<LinkText to="/app/decisions">View full register</LinkText>}
          >
            {brief.changedFacts.length > 0 ? (
              <div className="space-y-3">
                {brief.changedFacts.map((item) => (
                  <FactBriefRow key={item.componentId ?? `${item.modelId}-${item.name}`} item={item} />
                ))}
              </div>
            ) : (
              <EmptyText text="No recent fact changes are available yet." />
            )}
          </Panel>

          <Panel
            title="Needs attention"
            subtitle="Open conflicts and high-risk facts that still need a human decision."
            action={<LinkText to="/app/review?status=needs_review">Open review queue</LinkText>}
          >
            {(brief.openConflicts.length > 0 || brief.staleHighRiskItems.length > 0) ? (
              <div className="space-y-3">
                {brief.openConflicts.map((item) => (
                  <ConflictBriefRow key={item.reviewItemId ?? item.id} item={item} />
                ))}
                {brief.staleHighRiskItems.map((item) => (
                  <RiskBriefRow key={item.componentId ?? item.name} item={item} />
                ))}
              </div>
            ) : (
              <EmptyText text="Nothing is waiting on review right now." />
            )}
          </Panel>
        </section>

        <section className="space-y-6">
          <Panel
            title="Pipeline risk"
            subtitle="Connector failures and blockers that could distort company context."
            action={<LinkText to="/app/connectors">Inspect connectors</LinkText>}
          >
            {(brief.recentConnectorFailures.length > 0 || brief.newBlockers.length > 0) ? (
              <div className="space-y-3">
                {brief.newBlockers.map((item) => (
                  <BlockerBriefRow key={item.componentId ?? item.name} item={item} />
                ))}
                {brief.recentConnectorFailures.map((item) => (
                  <ConnectorFailureRow key={item.jobId ?? item.connectorId} item={item} />
                ))}
              </div>
            ) : (
              <EmptyText text="No connector or blocker risk is visible right now." />
            )}
          </Panel>

          <Panel
            title="Engineering movement"
            subtitle="Recent GitHub signals tied to decisions, refs, and pending implementation risk."
            action={<LinkText to="/app/engineering">Open engineering</LinkText>}
          >
            {brief.engineeringSignals.length > 0 ? (
              <div className="space-y-3">
                {brief.engineeringSignals.map((item) => (
                  <EngineeringBriefRow key={item.id} item={item} />
                ))}
              </div>
            ) : (
              <EmptyText text="No recent GitHub movement is affecting the brief right now." />
            )}
          </Panel>

          <Panel
            title="Accuracy watch"
            subtitle="Domains and blockers still keeping trust claims below the line."
            action={<LinkText to="/app/accuracy">Open accuracy</LinkText>}
          >
            {(brief.atRiskDomains.length > 0 || brief.accuracyBlockers.length > 0) ? (
              <div className="space-y-3">
                {brief.atRiskDomains.map((domain) => (
                  <div key={domain.domain} className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-3">
                    <p className="text-sm font-medium text-amber-800 capitalize">{domain.domain}</p>
                    <p className="mt-1 text-xs text-amber-700">
                      {domain.passed}/{domain.total} passing • {Math.round((domain.passRate ?? 0) * 100)}%
                    </p>
                  </div>
                ))}
                {brief.accuracyBlockers.map((blocker) => (
                  <div key={blocker} className="rounded-lg border border-gray-200 bg-gray-50 px-3 py-3 text-sm text-gray-700">
                    {blocker}
                  </div>
                ))}
              </div>
            ) : (
              <EmptyText text="No accuracy blockers are recorded right now." />
            )}
          </Panel>
        </section>
      </div>
    </div>
  );
}

function buildFounderBrief({ founderBrief, evalSummary, engineeringItems }) {
  const changedFacts = founderBrief?.changedFacts ?? [];
  const newBlockers = founderBrief?.newBlockers ?? [];
  const openConflicts = [...(founderBrief?.openConflicts ?? [])].sort(
    (a, b) => severityRank(b.severity) - severityRank(a.severity),
  );
  const staleHighRiskItems = founderBrief?.staleHighRiskItems ?? [];
  const recentConnectorFailures = founderBrief?.recentConnectorFailures ?? [];
  const engineeringSignals = buildEngineeringSignals(engineeringItems);
  const atRiskDomains =
    evalSummary?.domains?.filter(
      (domain) =>
        domain.passRate != null &&
        evalSummary.threshold != null &&
        domain.passRate < evalSummary.threshold,
    ) ?? [];
  const accuracyBlockers = evalSummary?.blockers ?? [];
  const latestTimestamps = [
    founderBrief?.generatedAt,
    ...changedFacts.map((item) => item.validFrom),
    ...openConflicts.map((item) => item.updatedAt),
    ...recentConnectorFailures.map((item) => item.failedAt),
    evalSummary?.latestRunAt,
  ].filter(Boolean);

  const hasData =
    changedFacts.length > 0 ||
    newBlockers.length > 0 ||
    openConflicts.length > 0 ||
    staleHighRiskItems.length > 0 ||
    recentConnectorFailures.length > 0 ||
    engineeringSignals.length > 0 ||
    Boolean(evalSummary);

  return {
    hasData,
    generatedAt: latestTimestamps.sort().at(-1) ?? null,
    headline: buildFounderHeadline({
      changedFacts,
      openConflicts,
      recentConnectorFailures,
      atRiskDomains,
    }),
    changedFactCount: changedFacts.length,
    newBlockerCount: newBlockers.length,
    openConflictCount: openConflicts.length,
    atRiskDomainCount: atRiskDomains.length,
    changedFacts: changedFacts.slice(0, 4),
    newBlockers: newBlockers.slice(0, 4),
    openConflicts: openConflicts.slice(0, 4),
    staleHighRiskItems: staleHighRiskItems.slice(0, 4),
    recentConnectorFailures: recentConnectorFailures.slice(0, 4),
    engineeringSignals,
    atRiskDomains,
    accuracyBlockers,
  };
}

function buildFounderHeadline({ changedFacts, openConflicts, recentConnectorFailures, atRiskDomains }) {
  const parts = [];
  if (changedFacts.length > 0) {
    parts.push(`${changedFacts.length} fact change${changedFacts.length === 1 ? "" : "s"} tracked`);
  }
  if (openConflicts.length > 0) {
    parts.push(`${openConflicts.length} open conflict${openConflicts.length === 1 ? "" : "s"} need review`);
  }
  if (recentConnectorFailures.length > 0) {
    parts.push(`${recentConnectorFailures.length} connector failure${recentConnectorFailures.length === 1 ? "" : "s"} visible`);
  }
  if (atRiskDomains.length > 0) {
    parts.push(`${atRiskDomains.length} eval domain${atRiskDomains.length === 1 ? "" : "s"} below threshold`);
  }
  if (!parts.length) return "The system is quiet right now. No major decision, trust, or connector pressure is visible.";
  return `${parts.join(" • ")}.`;
}

function buildEngineeringSignals(items) {
  if (!Array.isArray(items)) return [];
  return [...items]
    .filter((item) => item?.connectorType === "github")
    .sort(
      (a, b) =>
        new Date(b.createdAtSource ?? b.ingestedAt ?? 0) -
        new Date(a.createdAtSource ?? a.ingestedAt ?? 0),
    )
    .slice(0, 4)
    .map((item) => ({
      id: item.id,
      title: item.documentTitle || item.location || item.externalId || "Untitled GitHub item",
      repository: item.repository || "Unknown repository",
      itemType: formatGitHubItemType(item.githubItemType),
      processed: Boolean(item.processed),
      refs:
        (item.pullRequestReferences?.length ?? 0) + (item.commitReferences?.length ?? 0),
      author: item.author ?? null,
      createdAt: item.createdAtSource ?? item.ingestedAt ?? null,
    }));
}

function Panel({ title, subtitle, action, children }) {
  return (
    <section className="rounded-xl border border-gray-200 bg-white p-5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h3 className="text-sm font-semibold text-gray-700">{title}</h3>
          <p className="mt-1 text-xs text-gray-400">{subtitle}</p>
        </div>
        {action}
      </div>
      <div className="mt-4">{children}</div>
    </section>
  );
}

function EngineeringBriefRow({ item }) {
  return (
    <div className="rounded-lg border border-gray-200 bg-gray-50 px-4 py-3">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-sm font-medium text-gray-800">{item.title}</p>
            <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-medium text-slate-700">
              {item.itemType}
            </span>
            <span
              className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${
                item.processed
                  ? "bg-emerald-100 text-emerald-700"
                  : "bg-amber-100 text-amber-700"
              }`}
            >
              {item.processed ? "Processed" : "Pending"}
            </span>
          </div>
          <p className="mt-1 text-xs text-gray-500">
            {[item.repository, item.author, `${item.refs} refs`].filter(Boolean).join(" · ")}
          </p>
        </div>
        <div className="text-right">
          <p className="text-[11px] text-gray-400">{formatDateTime(item.createdAt)}</p>
          <Link
            to={`/app/engineering/${item.id}`}
            className="mt-2 inline-block text-xs font-medium text-brand-700 hover:text-brand-800"
          >
            Open engineering trail
          </Link>
        </div>
      </div>
    </div>
  );
}

function MetricCard({ label, value, tone = "default" }) {
  const tones = {
    default: "border-gray-200 bg-white text-gray-800",
    amber: "border-amber-200 bg-amber-50 text-amber-800",
    rose: "border-rose-200 bg-rose-50 text-rose-800",
    slate: "border-gray-200 bg-gray-50 text-gray-800",
  };

  return (
    <div className={`rounded-xl border p-4 ${tones[tone] ?? tones.default}`}>
      <p className="text-[11px] uppercase tracking-wide opacity-70">{label}</p>
      <p className="mt-2 text-3xl font-semibold">{value}</p>
    </div>
  );
}

function LinkText({ to, children }) {
  return (
    <Link to={to} className="text-xs font-medium text-brand-700 hover:text-brand-800">
      {children}
    </Link>
  );
}

function FactBriefRow({ item }) {
  return (
    <div className="rounded-lg border border-gray-200 bg-gray-50 px-4 py-3">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-sm font-medium text-gray-800">{item.name}</p>
            {item.reviewStatus && <BriefBadge status={item.reviewStatus} />}
          </div>
          <p className="mt-1 text-sm text-gray-600">{item.value}</p>
          <p className="mt-2 text-xs text-gray-500">
            {[item.modelName, ...(item.sourceLabels ?? [])].filter(Boolean).join(" · ")}
          </p>
          {typeof item.authorityWeight === "number" && (
            <p className="mt-2 text-[11px] text-gray-500">
              Authority {Math.round(item.authorityWeight * 100)}%
            </p>
          )}
        </div>
        <div className="text-right text-xs text-gray-400">
          <p>{formatDateTime(item.validFrom)}</p>
          <LinkText to={item.modelId ? `/app/model/${item.modelId}` : "/app/models"}>Fact</LinkText>
        </div>
      </div>
    </div>
  );
}

function ConflictBriefRow({ item }) {
  return (
    <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-sm font-medium text-amber-800">{item.title}</p>
            <span className="rounded-full bg-white/70 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-amber-700">
              {item.severity}
            </span>
          </div>
          <p className="mt-1 text-sm text-amber-700">{item.summary}</p>
        </div>
        <LinkText to={`/app/review/${item.reviewItemId ?? item.id}`}>Open</LinkText>
      </div>
    </div>
  );
}

function RiskBriefRow({ item }) {
  return (
    <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-sm font-medium text-amber-800">{item.name}</p>
            {item.reviewStatus && (
              <span className="rounded-full bg-white/70 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-amber-700">
                {item.reviewStatus}
              </span>
            )}
          </div>
          <p className="mt-1 text-sm text-amber-700">{item.reason}</p>
        </div>
        <LinkText to="/app/review?status=needs_review">Inspect</LinkText>
      </div>
    </div>
  );
}

function BlockerBriefRow({ item }) {
  return (
    <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-sm font-medium text-amber-800">{item.name}</p>
            {item.reviewStatus && (
              <span className="rounded-full bg-white/70 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-amber-700">
                {item.reviewStatus}
              </span>
            )}
          </div>
          <p className="mt-1 text-sm text-amber-700">{item.value}</p>
        </div>
        <LinkText to={item.modelId ? `/app/model/${item.modelId}` : "/app/models"}>Inspect</LinkText>
      </div>
    </div>
  );
}

function ConnectorFailureRow({ item }) {
  return (
    <div className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-sm font-medium text-rose-800">{item.connectorType}</p>
            <span className="rounded-full bg-white/70 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-rose-700">
              {item.jobType}
            </span>
          </div>
          <p className="mt-1 text-sm text-rose-700">{item.errorMessage || "Connector health needs attention."}</p>
          <p className="mt-2 text-[11px] text-rose-700/80">
            {item.errorType || "Failure"} · {formatDateTime(item.failedAt)}
          </p>
        </div>
        <LinkText to={item.connectorType ? `/app/connectors/${item.connectorType}/runs` : "/app/connectors"}>
          Inspect
        </LinkText>
      </div>
    </div>
  );
}

function BriefBadge({ status }) {
  const styles = {
    current: "bg-emerald-100 text-emerald-700",
    needs_review: "bg-amber-100 text-amber-700",
    historical: "bg-gray-100 text-gray-600",
  };
  return (
    <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${styles[status] ?? styles.current}`}>
      {status.replace(/_/g, " ")}
    </span>
  );
}

function EmptyText({ text }) {
  return <p className="text-sm text-gray-500">{text}</p>;
}

function formatGitHubItemType(value) {
  if (!value) return "github item";
  return value.replace(/_/g, " ");
}

function FounderBriefEmptyState() {
  return (
    <div className="rounded-[32px] border border-gray-200 bg-white p-12 text-center shadow-sm">
      <div className="mx-auto w-16 h-16 bg-brand-50 text-brand-600 rounded-full flex items-center justify-center mb-6">
        <svg className="w-8 h-8" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M8 6h10M8 10h10M8 14h6M5 4h14a2 2 0 012 2v12a2 2 0 01-2 2H5a2 2 0 01-2-2V6a2 2 0 012-2z" />
        </svg>
      </div>
      <h2 className="text-xl font-bold text-gray-900">No founder brief is available yet.</h2>
      <p className="mt-3 text-sm text-gray-500 max-w-lg mx-auto leading-relaxed">
        Sync sources and let the trust pipeline extract decisions, review items, and eval state first.
        Your startup's "current truth" will be summarized here once data is processed.
      </p>
      <div className="mt-8 flex flex-wrap items-center justify-center gap-4">
        <Link to="/app" className="px-6 py-2.5 bg-brand-600 text-white text-sm font-bold rounded-xl hover:bg-brand-500 transition-colors shadow-lg shadow-brand-500/20">
          Add context
        </Link>
        <Link to="/app/decisions" className="px-6 py-2.5 bg-gray-100 text-gray-700 text-sm font-bold rounded-xl hover:bg-gray-200 transition-colors">
          Open decision register
        </Link>
      </div>
    </div>
  );
}

function severityRank(value) {
  return { critical: 4, high: 3, medium: 2, low: 1 }[value] ?? 0;
}

function formatDateTime(value) {
  if (!value) return "Unknown time";
  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}
