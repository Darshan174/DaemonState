import { Link, useParams } from "react-router-dom";
import {
  useConnectors,
  useConnectorSyncJobs,
  useConnectorSyncStatus,
} from "../api/hooks";
import MockBadge from "../components/MockBadge";
import StatusView from "../components/StatusView";

const STATUS_PILL = {
  completed: "bg-emerald-100 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-400",
  failed: "bg-red-100 dark:bg-red-900/40 text-red-700 dark:text-red-400",
  pending: "bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-400",
  running: "bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-400",
};

export default function ConnectorRuns() {
  const { connectorType } = useParams();
  const connectorsQuery = useConnectors();
  const connectors = connectorsQuery.data ?? [];
  const connector = connectors.find((item) => item.type === connectorType) ?? null;
  const jobsQuery = useConnectorSyncJobs(connector?.connectorId, {
    enabled: !connectorsQuery.isMock && !!connector?.connectorId,
  });
  const latestJobQuery = useConnectorSyncStatus(connector?.connectorId, {
    enabled: !connectorsQuery.isMock && !!connector?.connectorId,
  });

  if (connectorsQuery.isLoading || connectorsQuery.isError) {
    return (
      <div className="max-w-5xl mx-auto">
        <StatusView query={connectorsQuery} empty="Connector runs are not available." />
      </div>
    );
  }

  if (!connector) {
    return (
      <div className="max-w-5xl mx-auto">
        <StatusView query={{ isLoading: false, isError: false, data: [] }} empty="Connector not found." />
      </div>
    );
  }

  const isMock = connectorsQuery.isMock || !connector.connectorId;
  const jobs = jobsQuery.data ?? [];
  const latestJob = latestJobQuery.data ?? null;

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-3">
            <h2 className="text-lg font-semibold text-gray-800 dark:text-gray-300">{connector.name} Run History</h2>
            {isMock && <MockBadge />}
          </div>
          <p className="text-xs text-gray-400 mt-1">
            Inspect background sync and reprocess jobs for this connector.
          </p>
          {isMock && (
            <p className="text-xs text-amber-600 dark:text-amber-400 mt-2">
              Job history is only available when the backend sync-job endpoints are live for this connector.
            </p>
          )}
        </div>
        <Link
          to="/app/connectors"
          className="rounded-lg border border-gray-200 dark:border-gray-800/50 bg-white dark:bg-slate-800 px-3 py-2 text-xs font-medium text-gray-700 dark:text-gray-400 hover:bg-gray-50 dark:bg-gray-900/30"
        >
          Back to connectors
        </Link>
      </div>

      <div className="rounded-xl border border-gray-200 dark:border-gray-800/50 bg-white dark:bg-slate-800 p-4">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-400">How this page gets populated</h3>
            <p className="text-xs text-gray-400 mt-1">
              Run history appears after a connector sync or document reprocess is queued. Use this page to verify worker outcomes before trusting downstream extraction and query state.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-3 text-xs">
            <Link to="/app/connectors" className="font-medium text-brand-700 dark:text-brand-400 hover:text-brand-800 dark:text-brand-300">
              Queue syncs
            </Link>
            <Link to="/app/sources" className="font-medium text-brand-700 dark:text-brand-400 hover:text-brand-800 dark:text-brand-300">
              Inspect sources
            </Link>
          </div>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-[minmax(0,1.1fr)_minmax(280px,0.9fr)]">
        <section className="rounded-xl border border-gray-200 dark:border-gray-800/50 bg-white dark:bg-slate-800 p-5 space-y-4">
          <div>
            <p className="text-xs uppercase tracking-wide text-gray-400">Connector</p>
            <p className="mt-1 text-sm font-semibold text-gray-800 dark:text-gray-300">{connector.name}</p>
            <p className="mt-1 text-xs text-gray-500">{connector.description}</p>
          </div>

          <div className="grid grid-cols-2 gap-y-2 text-xs">
            <span className="text-gray-400">Status</span>
            <span className="text-right text-gray-700 dark:text-gray-400">{connector.status}</span>
            <span className="text-gray-400">Last sync</span>
            <span className="text-right text-gray-700 dark:text-gray-400">{connector.lastSync}</span>
            <span className="text-gray-400">Stored docs</span>
            <span className="text-right text-gray-700 dark:text-gray-400">
              {Number(connector.itemsSynced || 0).toLocaleString()}
            </span>
            {connector.processedCount != null && (
              <>
                <span className="text-gray-400">Processed docs</span>
                <span className="text-right text-gray-700 dark:text-gray-400">
                  {Number(connector.processedCount || 0).toLocaleString()}
                </span>
              </>
            )}
          </div>
        </section>

        <section className="rounded-xl border border-gray-200 dark:border-gray-800/50 bg-white dark:bg-slate-800 p-5 space-y-3">
          <div className="flex items-center justify-between gap-3">
            <p className="text-xs uppercase tracking-wide text-gray-400">Latest job</p>
            {latestJob ? <StatusBadge status={latestJob.status} /> : null}
          </div>
          {latestJob ? (
            <div className="space-y-2 text-xs text-gray-600 dark:text-gray-400">
              <p>
                <span className="text-gray-400">Type:</span>{" "}
                <span className="text-gray-700 dark:text-gray-400 capitalize">{latestJob.jobType ?? "sync"}</span>
              </p>
              <p>
                <span className="text-gray-400">Created:</span> {formatDateTime(latestJob.createdAt)}
              </p>
              {latestJob.startedAt && (
                <p>
                  <span className="text-gray-400">Started:</span> {formatDateTime(latestJob.startedAt)}
                </p>
              )}
              {latestJob.completedAt && (
                <p>
                  <span className="text-gray-400">Finished:</span> {formatDateTime(latestJob.completedAt)}
                </p>
              )}
              {latestJob.status === "completed" && (
                <p className="rounded-lg bg-emerald-50 dark:bg-emerald-900/30 px-3 py-2 text-emerald-700 dark:text-emerald-400">
                  {formatCompletedSyncNotice(connector.name, latestJob.resultMetadata)}
                </p>
              )}
              {latestJob.status === "failed" && (
                <p className="rounded-lg bg-red-50 dark:bg-red-900/30 px-3 py-2 text-red-700 dark:text-red-400">
                  {latestJob.errorType ? `${latestJob.errorType}: ` : ""}
                  {latestJob.errorMessage || "Job failed."}
                </p>
              )}
              {(latestJob.status === "pending" || latestJob.status === "running") && (
                <p className="rounded-lg bg-blue-50 dark:bg-blue-900/30 px-3 py-2 text-blue-700 dark:text-blue-400">
                  Worker is {latestJob.status === "running" ? "running" : "queued"} for this job.
                </p>
              )}
            </div>
          ) : (
            <p className="text-xs text-gray-500">No run has been recorded for this connector yet.</p>
          )}
        </section>
      </div>

      <section className="rounded-xl border border-gray-200 dark:border-gray-800/50 bg-white dark:bg-slate-800 overflow-hidden">
        <div className="border-b border-gray-100 dark:border-gray-800/30 px-5 py-4">
          <p className="text-sm font-semibold text-gray-700 dark:text-gray-400">Recent runs</p>
          <p className="mt-1 text-xs text-gray-400">
            Completed, failed, queued, and reprocess jobs are listed here in reverse chronological order.
          </p>
        </div>
        {isMock ? (
          <div className="px-5 py-8 text-sm text-gray-500">
            Live run history is unavailable in demo mode.
          </div>
        ) : jobs.length === 0 ? (
          <div className="px-5 py-8 text-sm text-gray-500 space-y-2">
            <p>No sync or reprocess jobs have been recorded for this connector yet.</p>
            <p className="text-xs text-gray-400">
              Queue the first connector sync, then come back here to inspect timestamps, worker outcomes, and document counts.
            </p>
          </div>
        ) : (
          <div className="divide-y divide-gray-100">
            {jobs.map((job) => (
              <div key={job.jobId ?? `${job.status}-${job.createdAt}`} className="px-5 py-4">
                <div className="flex items-start justify-between gap-4">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <StatusBadge status={job.status} />
                      <span className="rounded-full bg-gray-100 dark:bg-gray-900/40 px-2 py-0.5 text-[10px] font-medium text-gray-600 dark:text-gray-400 capitalize">
                        {job.jobType ?? "sync"}
                      </span>
                    </div>
                    <p className="mt-2 text-sm text-gray-800 dark:text-gray-300">
                      {job.status === "completed"
                        ? summarizeSyncJob(job.resultMetadata)
                        : job.status === "failed"
                          ? job.errorMessage || "Sync failed."
                          : `Job ${job.status}`}
                    </p>
                    <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-gray-400">
                      <span>Created {formatDateTime(job.createdAt)}</span>
                      {job.startedAt && <span>Started {formatDateTime(job.startedAt)}</span>}
                      {job.completedAt && <span>Finished {formatDateTime(job.completedAt)}</span>}
                    </div>
                  </div>
                  <span className="text-[11px] text-gray-400">{job.jobId}</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

function StatusBadge({ status }) {
  return (
    <span
      className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${
        STATUS_PILL[status] ?? "bg-slate-100 dark:bg-slate-900/40 text-slate-600 dark:text-slate-400"
      }`}
    >
      {status}
    </span>
  );
}

function summarizeSyncJob(metadata) {
  if (!metadata || typeof metadata !== "object") {
    return "Sync completed.";
  }
  const fetched = Number(metadata.documents_fetched ?? 0);
  const persisted = Number(metadata.documents_persisted ?? 0);
  const processed = Number(metadata.documents_processed ?? 0);
  return `Fetched ${fetched}, stored ${persisted}, processed ${processed}`;
}

function formatCompletedSyncNotice(connectorName, metadata) {
  if (!metadata || typeof metadata !== "object") {
    return `${connectorName} sync completed.`;
  }

  const fetched = Number(metadata.documents_fetched ?? 0);
  const persisted = Number(metadata.documents_persisted ?? 0);
  const processed = Number(metadata.documents_processed ?? 0);
  const syncMode = metadata.sync_mode ? ` (${metadata.sync_mode})` : "";

  return `${connectorName} sync completed: fetched ${fetched}, stored ${persisted}, processed ${processed}${syncMode}.`;
}

function formatDateTime(value) {
  if (!value) return "—";
  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}
