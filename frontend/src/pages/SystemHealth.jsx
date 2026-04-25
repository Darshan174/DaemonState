import { useMemo } from "react";
import { useOperatorStatus } from "../api/hooks";

const PRIMARY_FIELDS = new Set([
  "checks",
  "components",
  "data",
  "dependencies",
  "endpoint",
  "message",
  "services",
  "status",
  "summary",
  "timestamp",
  "updatedAt",
  "updated_at",
  "checkedAt",
  "checked_at",
]);

export default function SystemHealth() {
  const query = useOperatorStatus();
  const snapshot = useMemo(
    () => normalizeStatusPayload(query.data?.data),
    [query.data],
  );

  if (query.isLoading) {
    return (
      <div className="max-w-6xl mx-auto">
        <SystemHealthShell>
          <div role="status" aria-live="polite" className="flex min-h-[360px] flex-col items-center justify-center text-slate-400">
            <div className="h-8 w-8 animate-spin rounded-full border-4 border-brand-200 dark:border-brand-800/50 border-t-brand-600" />
            <p className="mt-3 text-sm font-medium">Loading system status...</p>
          </div>
        </SystemHealthShell>
      </div>
    );
  }

  if (query.isError) {
    return (
      <div className="max-w-6xl mx-auto">
        <SystemHealthShell>
          <div role="alert" className="rounded-xl border border-amber-200 dark:border-amber-800/50 bg-amber-50 dark:bg-amber-900/30 px-5 py-4">
            <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
              <div>
                <p className="text-sm font-semibold text-amber-900 dark:text-amber-200">
                  Status endpoint unavailable
                </p>
                <p className="mt-1 max-w-2xl text-sm text-amber-800 dark:text-amber-300">
                  The UI checked /api/operator/status and /api/admin/status, but no self-host
                  status payload is available yet. Once the backend route lands, this page will
                  render it without requiring more frontend wiring.
                </p>
                <p className="mt-2 text-xs font-medium text-amber-700 dark:text-amber-400">
                  {formatError(query.error)}
                </p>
              </div>
              <button
                type="button"
                onClick={() => query.refetch()}
                className="inline-flex items-center justify-center rounded-lg bg-amber-900 px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-amber-800"
              >
                Retry
              </button>
            </div>
          </div>
        </SystemHealthShell>
      </div>
    );
  }

  if (!snapshot.hasData) {
    return (
      <div className="max-w-6xl mx-auto">
        <SystemHealthShell endpoint={query.data?.endpoint}>
          <div className="rounded-xl border border-slate-200 dark:border-slate-800/50 bg-slate-50 dark:bg-slate-900/30 px-5 py-12 text-center">
            <p className="text-sm font-semibold text-slate-800 dark:text-slate-300">No status data returned.</p>
            <p className="mt-2 text-sm text-slate-500">
              The endpoint responded, but the payload was empty.
            </p>
          </div>
        </SystemHealthShell>
      </div>
    );
  }

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <SystemHealthHeader
        endpoint={query.data?.endpoint}
        status={snapshot.overallStatus}
        updatedAt={snapshot.updatedAt}
        onRefresh={() => query.refetch()}
        isRefreshing={query.isFetching}
      />

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <SummaryCard
          label="Overall"
          value={formatStatus(snapshot.overallStatus)}
          detail={snapshot.summary}
          tone={statusTone(snapshot.overallStatus)}
        />
        <SummaryCard
          label="Healthy checks"
          value={`${snapshot.healthyCount}/${snapshot.checks.length || 0}`}
          detail={snapshot.checks.length ? "Reported dependency checks" : "No checks reported"}
          tone={snapshot.unhealthyCount > 0 ? "warn" : "ok"}
        />
        <SummaryCard
          label="Warnings"
          value={snapshot.warningCount}
          detail="Degraded or unknown signals"
          tone={snapshot.warningCount > 0 ? "warn" : "neutral"}
        />
        <SummaryCard
          label="Failures"
          value={snapshot.failureCount}
          detail="Unavailable or failed signals"
          tone={snapshot.failureCount > 0 ? "bad" : "ok"}
        />
      </div>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_360px]">
        <section className="rounded-xl border border-slate-200 dark:border-slate-800/50 bg-white dark:bg-slate-800">
          <div className="border-b border-slate-100 dark:border-slate-800/30 px-5 py-4">
            <p className="text-sm font-semibold text-slate-800 dark:text-slate-300">Dependency checks</p>
            <p className="mt-1 text-xs text-slate-500">
              Backend-reported services, queues, storage, and runtime checks.
            </p>
          </div>
          {snapshot.checks.length ? (
            <div className="divide-y divide-slate-100">
              {snapshot.checks.map((check) => (
                <CheckRow key={check.key} check={check} />
              ))}
            </div>
          ) : (
            <div className="px-5 py-10 text-center text-sm text-slate-500">
              No dependency checks were included in the status payload.
            </div>
          )}
        </section>

        <aside className="space-y-4">
          <section className="rounded-xl border border-slate-200 dark:border-slate-800/50 bg-white dark:bg-slate-800 p-5">
            <p className="text-sm font-semibold text-slate-800 dark:text-slate-300">Runtime details</p>
            {snapshot.details.length ? (
              <dl className="mt-4 space-y-3">
                {snapshot.details.map((item) => (
                  <div key={item.key} className="flex items-start justify-between gap-4 text-sm">
                    <dt className="text-slate-500">{item.label}</dt>
                    <dd className="max-w-[190px] break-words text-right font-medium text-slate-800 dark:text-slate-300">
                      {item.value}
                    </dd>
                  </div>
                ))}
              </dl>
            ) : (
              <p className="mt-4 text-sm text-slate-500">No runtime metadata was reported.</p>
            )}
          </section>

          <section className="rounded-xl border border-slate-200 dark:border-slate-800/50 bg-slate-950 p-5 text-white">
            <p className="text-sm font-semibold">Self-host note</p>
            <p className="mt-2 text-sm leading-6 text-slate-300">
              This page is intentionally read-only. It gives operators one concise place to
              confirm API readiness and dependency health without exposing backend controls.
            </p>
          </section>
        </aside>
      </div>
    </div>
  );
}

function SystemHealthShell({ children, endpoint = "/api/operator/status" }) {
  return (
    <div className="space-y-6">
      <SystemHealthHeader endpoint={endpoint} status="unknown" />
      {children}
    </div>
  );
}

function SystemHealthHeader({ endpoint, status, updatedAt, onRefresh, isRefreshing = false }) {
  return (
    <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
      <div>
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="text-2xl font-bold tracking-tight text-slate-900 dark:text-slate-200">System Health</h2>
          <StatusPill status={status} />
        </div>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-500">
          Self-host runtime status for the API, dependencies, workers, and storage services.
        </p>
        <p className="mt-2 text-xs font-medium text-slate-400">
          Endpoint: <span className="font-mono text-slate-600 dark:text-slate-400">{endpoint ?? "/api/operator/status"}</span>
          {updatedAt ? ` · Updated ${formatDateTime(updatedAt)}` : ""}
        </p>
      </div>
      {onRefresh && (
        <button
          type="button"
          onClick={onRefresh}
          disabled={isRefreshing}
          className="inline-flex items-center justify-center rounded-lg border border-slate-200 dark:border-slate-800/50 bg-white dark:bg-slate-800 px-4 py-2 text-sm font-semibold text-slate-700 dark:text-slate-400 shadow-sm transition-colors hover:bg-slate-50 dark:bg-slate-900/30 disabled:opacity-60"
        >
          {isRefreshing ? "Refreshing..." : "Refresh"}
        </button>
      )}
    </div>
  );
}

function SummaryCard({ label, value, detail, tone }) {
  const styles = {
    ok: "border-emerald-200 dark:border-emerald-800/50 bg-emerald-50 dark:bg-emerald-900/30 text-emerald-800 dark:text-emerald-300",
    warn: "border-amber-200 dark:border-amber-800/50 bg-amber-50 dark:bg-amber-900/30 text-amber-800 dark:text-amber-300",
    bad: "border-red-200 dark:border-red-800/50 bg-red-50 dark:bg-red-900/30 text-red-800 dark:text-red-300",
    neutral: "border-slate-200 dark:border-slate-800/50 bg-white dark:bg-slate-800 text-slate-800 dark:text-slate-300",
    unknown: "border-slate-200 dark:border-slate-800/50 bg-slate-50 dark:bg-slate-900/30 text-slate-700 dark:text-slate-400",
  };

  return (
    <section className={`rounded-xl border p-5 ${styles[tone] ?? styles.unknown}`}>
      <p className="text-xs font-bold uppercase tracking-widest opacity-70">{label}</p>
      <p className="mt-3 text-2xl font-bold">{value}</p>
      <p className="mt-1 text-xs opacity-75">{detail}</p>
    </section>
  );
}

function CheckRow({ check }) {
  return (
    <div className="flex flex-col gap-3 px-5 py-4 sm:flex-row sm:items-start sm:justify-between">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <p className="text-sm font-semibold text-slate-800 dark:text-slate-300">{check.label}</p>
          <StatusPill status={check.status} />
        </div>
        {check.message && (
          <p className="mt-1 text-sm leading-6 text-slate-500">{check.message}</p>
        )}
      </div>
      {check.value && (
        <p className="max-w-full break-words rounded-lg bg-slate-50 dark:bg-slate-900/30 px-3 py-1.5 font-mono text-xs text-slate-600 dark:text-slate-400 sm:max-w-[280px]">
          {check.value}
        </p>
      )}
    </div>
  );
}

function StatusPill({ status }) {
  const tone = statusTone(status);
  const classes = {
    ok: "bg-emerald-100 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-400 ring-emerald-200",
    warn: "bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-400 ring-amber-200",
    bad: "bg-red-100 dark:bg-red-900/40 text-red-700 dark:text-red-400 ring-red-200",
    neutral: "bg-slate-100 dark:bg-slate-900/40 text-slate-700 dark:text-slate-400 ring-slate-200",
    unknown: "bg-slate-100 dark:bg-slate-900/40 text-slate-600 dark:text-slate-400 ring-slate-200",
  };

  return (
    <span className={`inline-flex rounded-full px-2.5 py-1 text-xs font-semibold ring-1 ${classes[tone]}`}>
      {formatStatus(status)}
    </span>
  );
}

function normalizeStatusPayload(payload) {
  const source = payload && typeof payload === "object" ? payload : {};
  const checks = collectChecks(source);
  const overallStatus = source.status ?? source.state ?? deriveOverallStatus(checks);
  const details = [
    ...Object.entries(source)
      .filter(([key, value]) => !PRIMARY_FIELDS.has(key) && isScalar(value))
      .map(([key, value]) => ({
        key,
        label: humanize(key),
        value: formatScalar(key, value),
      })),
    ...modelConfigDetails(source.models),
  ];
  const hasData = Object.keys(source).length > 0 || checks.length > 0;
  const healthyCount = checks.filter((item) => statusTone(item.status) === "ok").length;
  const failureCount = checks.filter((item) => statusTone(item.status) === "bad").length;
  const warningCount = checks.filter((item) => statusTone(item.status) === "warn" || statusTone(item.status) === "unknown").length;

  return {
    checks,
    details,
    failureCount,
    hasData,
    healthyCount,
    overallStatus,
    summary: source.summary ?? source.message ?? "Latest status endpoint response",
    unhealthyCount: checks.length - healthyCount,
    updatedAt: source.updated_at ?? source.updatedAt ?? source.timestamp ?? source.checked_at ?? source.checkedAt,
    warningCount,
  };
}

function modelConfigDetails(models) {
  if (!models || typeof models !== "object") return [];

  const rows = [
    ["providerApiConfigured", "Provider API configured", models.providerApiConfigured],
    ["defaultProviderModelsEnabled", "Default provider models", models.defaultProviderModelsEnabled],
    ["litellmApiBaseConfigured", "LiteLLM API base", models.litellmApiBaseConfigured],
    ["litellmTimeoutSeconds", "LiteLLM timeout", models.litellmTimeoutSeconds],
    ["embedding.provider", "Embedding provider", models.embedding?.provider],
    ["embedding.model", "Embedding model", models.embedding?.model],
    ["embedding.dimensions", "Embedding dimensions", models.embedding?.dimensions],
    ["extraction.provider", "Extraction provider", models.extraction?.provider],
    ["extraction.model", "Extraction model", models.extraction?.model],
  ];

  return rows
    .filter(([, , value]) => isScalar(value))
    .map(([key, label, value]) => ({
      key,
      label,
      value: formatScalar(key, value),
    }));
}

function collectChecks(source) {
  const groups = [
    source.checks,
    source.services,
    source.dependencies,
    source.components,
    source.data?.checks,
  ];

  return groups.flatMap((group) => normalizeCheckGroup(group));
}

function normalizeCheckGroup(group) {
  if (!group) return [];

  if (Array.isArray(group)) {
    return group.map((item, index) => normalizeCheck(`check_${index + 1}`, item));
  }

  if (typeof group === "object") {
    return Object.entries(group).map(([key, value]) => normalizeCheck(key, value));
  }

  return [];
}

function normalizeCheck(key, value) {
  if (value && typeof value === "object") {
    return {
      key,
      label: value.name ?? value.label ?? humanize(key),
      message: value.message ?? value.detail ?? value.details ?? value.error ?? null,
      status: value.status ?? value.state ?? value.ok ?? value.healthy ?? "unknown",
      value: formatCheckValue(value),
    };
  }

  return {
    key,
    label: humanize(key),
    message: null,
    status: value,
    value: typeof value === "boolean" ? null : String(value ?? ""),
  };
}

function formatCheckValue(value) {
  const metadata = Object.entries(value)
    .filter(([key, item]) => !["name", "label", "message", "detail", "details", "error", "status", "state", "ok", "healthy"].includes(key) && isScalar(item))
    .map(([key, item]) => `${humanize(key)}: ${formatScalar(key, item)}`);

  return metadata.join(" · ");
}

function deriveOverallStatus(checks) {
  if (!checks.length) return "unknown";
  if (checks.some((item) => statusTone(item.status) === "bad")) return "error";
  if (checks.some((item) => statusTone(item.status) === "warn" || statusTone(item.status) === "unknown")) return "degraded";
  return "ready";
}

function statusTone(status) {
  const value = String(status ?? "unknown").toLowerCase();
  if (["ok", "ready", "healthy", "up", "pass", "passed", "true", "connected"].includes(value)) return "ok";
  if (["warn", "warning", "degraded", "pending", "starting", "unknown", "null"].includes(value)) return "warn";
  if (["error", "failed", "fail", "down", "unhealthy", "false", "disconnected"].includes(value)) return "bad";
  return "unknown";
}

function formatStatus(status) {
  if (typeof status === "boolean") return status ? "Healthy" : "Failed";
  return humanize(String(status ?? "unknown"));
}

function humanize(value) {
  return String(value)
    .replace(/[_-]+/g, " ")
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/^./, (char) => char.toUpperCase());
}

function isScalar(value) {
  return value == null || ["string", "number", "boolean"].includes(typeof value);
}

function formatScalar(key, value) {
  if (value == null) return "—";
  if (/(_at|At|timestamp|time)$/.test(key) && typeof value === "string") {
    return formatDateTime(value);
  }
  if (/uptime/.test(key) && typeof value === "number") return formatDuration(value);
  return String(value);
}

function formatDateTime(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString();
}

function formatDuration(seconds) {
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  if (hours > 0) return `${hours}h ${minutes}m`;
  return `${minutes}m`;
}

function formatError(error) {
  if (error?.status === 404) return "Backend returned 404 for both known status paths.";
  return error?.message ?? "Unable to load operator status.";
}
