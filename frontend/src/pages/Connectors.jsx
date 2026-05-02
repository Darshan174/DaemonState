import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  useConnectGitHub,
  useConnectZoom,
  useConnectNotion,
  useSaveSlackOAuthSettings,
  useConnectorSyncJobs,
  useConnectorSyncStatus,
  useConnectors,
  useConnectorProcessingSummary,
  useDisconnectConnector,
  useSyncConnector,
  useWorkspaces,
} from "../api/hooks";
import MockBadge from "../components/MockBadge";
import StatusView from "../components/StatusView";
import { resolveWorkspaceId, useWorkspaceSelection } from "../context/WorkspaceContext";

const STATUS_PILL = {
  connected: "bg-emerald-100 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-400",
  disconnected: "bg-gray-100 dark:bg-gray-900/40 text-gray-600 dark:text-gray-400",
  warning: "bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-400",
  error: "bg-red-100 dark:bg-red-900/40 text-red-700 dark:text-red-400",
  coming_soon: "bg-slate-100 dark:bg-slate-900/40 text-slate-600 dark:text-slate-400",
};

const STATUS_LABEL = {
  connected: "Connected",
  disconnected: "Not connected",
  warning: "Warning",
  error: "Error",
  coming_soon: "Coming soon",
};

const PROVIDER_PILL = {
  native: "bg-gray-100 dark:bg-gray-900/40 text-gray-700 dark:text-gray-400",
  dlt: "bg-sky-100 dark:bg-sky-900/40 text-sky-700 dark:text-sky-400",
  unstructured: "bg-orange-100 dark:bg-orange-900/40 text-orange-700 dark:text-orange-400",
  official_api: "bg-indigo-100 dark:bg-indigo-900/40 text-indigo-700 dark:text-indigo-400",
};

const OAUTH_POLL_INTERVAL_MS = 1500;

function formatDocumentCount(count) {
  const total = Number(count || 0);
  return `${total.toLocaleString()} source document${total === 1 ? "" : "s"}`;
}

export default function Connectors() {
  const { data, isMock, ...query } = useConnectors();
  const summaryQuery = useConnectorProcessingSummary();
  const workspaces = useWorkspaces();
  const { selectedId } = useWorkspaceSelection();
  const connectNotionMut = useConnectNotion();
  const saveSlackOAuthMut = useSaveSlackOAuthSettings();
  const connectZoomMut = useConnectZoom();
  const connectGitHubMut = useConnectGitHub();
  const syncMut = useSyncConnector();
  const disconnectMut = useDisconnectConnector();
  const [actionError, setActionError] = useState(null);
  const [actionNotice, setActionNotice] = useState(null);
  const [oauthFlow, setOauthFlow] = useState(null);
  const [slackConnectIntent, setSlackConnectIntent] = useState(null);
  const [slackSetupOpen, setSlackSetupOpen] = useState(false);
  const [slackClientId, setSlackClientId] = useState("");
  const [slackClientSecret, setSlackClientSecret] = useState("");
  const [slackRedirectUri, setSlackRedirectUri] = useState(
    "http://localhost:8000/api/connectors/slack/callback",
  );
  const [notionFormOpen, setNotionFormOpen] = useState(false);
  const [notionToken, setNotionToken] = useState("");
  const [zoomFormOpen, setZoomFormOpen] = useState(false);
  const [zoomToken, setZoomToken] = useState("");
  const [githubFormOpen, setGitHubFormOpen] = useState(false);
  const [githubToken, setGitHubToken] = useState("");
  const [githubRepositories, setGitHubRepositories] = useState("");

  const workspaceId = useMemo(
    () => resolveWorkspaceId(workspaces.data, selectedId),
    [workspaces.data, selectedId],
  );

  const list = data ?? [];
  const slackConnector = list.find((item) => item.type === "slack") ?? null;
  const processingByType = useMemo(
    () =>
      new Map(
        (summaryQuery.data?.items ?? []).map((item) => [item.connectorType, item]),
      ),
    [summaryQuery.data?.items],
  );

  const handleSyncJobSettled = async (connectorName, job) => {
    await Promise.allSettled([query.refetch(), summaryQuery.refetch?.()]);

    if (job?.status === "failed") {
      setActionNotice(null);
      setActionError(
        job.errorMessage || `${connectorName} sync failed before the worker finished successfully.`,
      );
      return;
    }

    if (job?.status === "completed") {
      setActionError(null);
      setActionNotice(formatCompletedSyncNotice(connectorName, job.resultMetadata));
    }
  };

  useEffect(() => {
    if (!oauthFlow || isMock) return undefined;

    let cancelled = false;

    const finishOAuthFlow = (slack, startedStatus) => {
      setOauthFlow(null);

      if (slack?.status === "connected") {
        const teamSuffix = slack.teamName ? ` to ${slack.teamName}` : "";
        setActionError(null);
        setActionNotice(
          startedStatus === "disconnected"
            ? `Slack connected${teamSuffix}.`
            : `Slack OAuth finished${teamSuffix}. Connector state refreshed.`,
        );
        return;
      }

      if (slack?.status === "error") {
        setActionNotice(null);
        setActionError(
          "Slack OAuth finished, but the connector is still in an error state. Refresh OAuth or check the backend logs.",
        );
        return;
      }

      setActionNotice(null);
      setActionError("Slack OAuth window closed before the connector status updated.");
    };

    const tick = async () => {
      const result = await query.refetch();
      if (cancelled) return;

      if (result.isError) {
        if (oauthFlow.popup?.closed) {
          setOauthFlow(null);
          setActionNotice(null);
          setActionError("Failed to refresh connector state after Slack OAuth.");
        }
        return;
      }

      const nextList = result.data ?? [];
      const nextSlack = nextList.find((item) => item.type === "slack") ?? null;
      const popupClosed = oauthFlow.popup?.closed ?? true;

      if (!popupClosed && nextSlack?.status === "connected" && oauthFlow.startedStatus === "disconnected") {
        oauthFlow.popup.close?.();
        finishOAuthFlow(nextSlack, oauthFlow.startedStatus);
        return;
      }

      if (popupClosed) {
        finishOAuthFlow(nextSlack, oauthFlow.startedStatus);
      }
    };

    const timer = window.setInterval(() => {
      void tick();
    }, OAUTH_POLL_INTERVAL_MS);

    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [isMock, oauthFlow, query.refetch]);

  const startGenericOAuth = (installHref, connectorType) => {
    setActionError(null);
    setActionNotice(null);
    const popup = window.open(installHref, `ce-${connectorType}-oauth`, "popup=yes,width=640,height=820");
    if (!popup) {
      window.location.assign(installHref);
      return;
    }
    popup.focus?.();
    const timer = window.setInterval(async () => {
      if (popup.closed) {
        window.clearInterval(timer);
        await query.refetch();
      }
    }, OAUTH_POLL_INTERVAL_MS);
    setActionNotice(`${connectorType.replace("_", " ")} OAuth opened in a new window. Finish there to connect.`);
  };

  const openSlackConnectModal = (installHref, currentStatus, mode = "self_hosted") => {
    setActionError(null);
    setActionNotice(null);
    setSlackConnectIntent({ installHref, currentStatus, mode });
  };

  const startSlackOAuth = (installHref, currentStatus) => {
    setActionError(null);
    setActionNotice(null);
    setSlackConnectIntent(null);

    const popup = window.open(
      installHref,
      "ce-slack-oauth",
      "popup=yes,width=640,height=820",
    );

    if (!popup) {
      window.location.assign(installHref);
      return;
    }

    popup.focus?.();
    setOauthFlow({
      popup,
      startedStatus: currentStatus,
    });
    setActionNotice(
      currentStatus === "disconnected"
        ? "Slack OAuth opened in a new window. Finish there to connect the workspace."
        : "Slack reconnect opened in a new window. Finish there to refresh credentials.",
    );
  };

  if (query.isLoading || query.isError) {
    return (
      <div className="max-w-5xl mx-auto">
        <StatusView query={{ data, ...query }} empty="No connectors configured." />
      </div>
    );
  }

  return (
    <div className="max-w-5xl mx-auto space-y-7">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-3">
            <h2 className="text-3xl font-bold tracking-tight text-slate-950 dark:text-white">Workspace Connectors</h2>
            {isMock && <MockBadge />}
          </div>
          <p className="mt-2 max-w-4xl text-sm leading-6 text-slate-500 dark:text-slate-400">
            Slack, Zoom, Google Drive, and Gmail are the target source surfaces. Each connector lands raw source documents first, then the extractor turns those documents into graph components with provenance.
          </p>
          {isMock && (
            <p className="text-xs text-amber-600 dark:text-amber-400 mt-2">
              Connector cards are in demo mode right now. OAuth and sync actions unlock once the backend
              endpoints are live.
            </p>
          )}
        </div>
      </div>

      <div className="rounded-xl border border-gray-200 dark:border-gray-800/50 bg-white dark:bg-slate-800 p-4">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-400">Self-host quick path</h3>
            <p className="text-xs text-gray-400 mt-1">
              For a fresh install, the shortest path is connect a source, run the first sync, then inspect Sources before trusting Query answers.
            </p>
          </div>
          <Link to="/app/sources" className="text-xs font-medium text-brand-700 dark:text-brand-400 hover:text-brand-800 dark:text-brand-300">
            Open sources
          </Link>
        </div>
        <div className="mt-4 grid gap-3 md:grid-cols-3">
          <QuickPathStep
            title="1. Connect a source"
            description="Start with Slack, Zoom, Drive, Gmail, or Wispr Flow so the workspace has real context to ingest."
            to="/app/connectors"
            action="Connectors"
          />
          <QuickPathStep
            title="2. Run the first sync"
            description="Queue a sync from the connector card and wait for raw documents to land in the source store."
            to="/app/connectors"
            action="Run sync"
          />
          <QuickPathStep
            title="3. Validate trust"
            description="Use Sources, Review, and Accuracy to verify what the system extracted before relying on it."
            to="/app/review"
            action="Open review"
          />
        </div>
      </div>

      {actionError && (
        <div className="rounded-xl border border-red-200 dark:border-red-800/50 bg-red-50 dark:bg-red-900/30 p-4">
          <p className="text-sm text-red-700 dark:text-red-400">{actionError}</p>
        </div>
      )}
      {actionNotice && (
        <div className="rounded-xl border border-emerald-200 dark:border-emerald-800/50 bg-emerald-50 dark:bg-emerald-900/30 p-4">
          <p className="text-sm text-emerald-700 dark:text-emerald-400">{actionNotice}</p>
        </div>
      )}
      {slackConnector && (
        <SlackSummaryBanner
          connector={slackConnector}
          isDemo={isMock}
          oauthPending={!!oauthFlow}
          workspaceId={workspaceId}
          onStartOAuth={openSlackConnectModal}
        />
      )}
      {slackConnectIntent && (
        <SlackConnectModal
          mode={slackConnectIntent.mode}
          onCancel={() => setSlackConnectIntent(null)}
          onContinue={() => startSlackOAuth(slackConnectIntent.installHref, slackConnectIntent.currentStatus)}
        />
      )}

      {list.length === 0 ? (
        <StatusView query={{ data: list, isLoading: false, isError: false }} empty="No connectors configured." />
      ) : (
        <div className="grid sm:grid-cols-2 gap-5">
          {list.map((connector) => (
            <ConnectorCard
              key={connector.type}
              connector={connector}
              isDemo={isMock}
              oauthPending={!!oauthFlow}
              workspaceId={workspaceId}
              processing={processingByType.get(connector.type) ?? null}
              slackSetupOpen={connector.type === "slack" ? slackSetupOpen : false}
              slackClientId={slackClientId}
              slackClientSecret={slackClientSecret}
              slackRedirectUri={slackRedirectUri}
              onChangeSlackClientId={setSlackClientId}
              onChangeSlackClientSecret={setSlackClientSecret}
              onChangeSlackRedirectUri={setSlackRedirectUri}
              onToggleSlackSetup={() => setSlackSetupOpen((current) => !current)}
              saveSlackOAuthMut={saveSlackOAuthMut}
              notionFormOpen={connector.type === "notion" ? notionFormOpen : false}
              notionToken={notionToken}
              onChangeNotionToken={setNotionToken}
              onToggleNotionForm={() => setNotionFormOpen((current) => !current)}
              connectNotionMut={connectNotionMut}
              zoomFormOpen={connector.type === "zoom" ? zoomFormOpen : false}
              zoomToken={zoomToken}
              onChangeZoomToken={setZoomToken}
              onToggleZoomForm={() => setZoomFormOpen((current) => !current)}
              connectZoomMut={connectZoomMut}
              githubFormOpen={connector.type === "github" ? githubFormOpen : false}
              githubToken={githubToken}
              githubRepositories={githubRepositories}
              onChangeGitHubToken={setGitHubToken}
              onChangeGitHubRepositories={setGitHubRepositories}
              onToggleGitHubForm={() => setGitHubFormOpen((current) => !current)}
              connectGitHubMut={connectGitHubMut}
              syncMut={syncMut}
              disconnectMut={disconnectMut}
              onActionError={setActionError}
              onActionNotice={setActionNotice}
              onSyncJobSettled={handleSyncJobSettled}
              onStartOAuth={openSlackConnectModal}
              onStartGenericOAuth={startGenericOAuth}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function QuickPathStep({ title, description, to, action }) {
  return (
    <div className="rounded-xl border border-gray-200 dark:border-gray-800/50 bg-gray-50 dark:bg-gray-900/30 px-4 py-4">
      <p className="text-sm font-semibold text-gray-800 dark:text-gray-300">{title}</p>
      <p className="mt-2 text-xs text-gray-600 dark:text-gray-400">{description}</p>
      <Link to={to} className="mt-4 inline-flex text-xs font-medium text-brand-700 dark:text-brand-400 hover:text-brand-800 dark:text-brand-300">
        {action}
      </Link>
    </div>
  );
}

function ConnectorCard({
  connector,
  isDemo,
  oauthPending,
  workspaceId,
  processing,
  slackSetupOpen,
  slackClientId,
  slackClientSecret,
  slackRedirectUri,
  onChangeSlackClientId,
  onChangeSlackClientSecret,
  onChangeSlackRedirectUri,
  onToggleSlackSetup,
  saveSlackOAuthMut,
  notionFormOpen,
  notionToken,
  onChangeNotionToken,
  onToggleNotionForm,
  connectNotionMut,
  zoomFormOpen,
  zoomToken,
  onChangeZoomToken,
  onToggleZoomForm,
  connectZoomMut,
  githubFormOpen,
  githubToken,
  githubRepositories,
  onChangeGitHubToken,
  onChangeGitHubRepositories,
  onToggleGitHubForm,
  connectGitHubMut,
  syncMut,
  disconnectMut,
  onActionError,
  onActionNotice,
  onSyncJobSettled,
  onStartOAuth,
  onStartGenericOAuth,
}) {
  const {
    connectorId,
    type,
    name,
    description,
    status,
    lastSync,
    itemsSynced,
    color,
    availability,
    message,
    teamName,
    scope,
    syncQueuedAt,
    syncMode,
    syncModeNote,
    processedCount,
    totalProcessedCount,
    authMode,
    accountId,
    ingestionMode,
    sourceFocus,
    lastWebhookEvent,
    lastWebhookReceivedAt,
    provider,
    providerLabel,
    providerNote,
    isConfigured = true,
    managedConnectAvailable = false,
    managedInstallUrl = null,
  } = connector;

  const isSlack = type === "slack";
  const isNotion = type === "notion";
  const isZoom = type === "zoom";
  const isGitHub = type === "github";
  const isGDrive = type === "gdrive";
  const isGmail = type === "gmail";
  const isGoogleOAuth = isGDrive || isGmail;
  const slackSelfHostedSetupAvailable = isSlack && isConfigured === false;
  const canConnect =
    !isDemo &&
    !oauthPending &&
    availability === "available" &&
    status === "disconnected" &&
    !!workspaceId;
  const canReconnect =
    !isDemo &&
    !oauthPending &&
    availability === "available" &&
    !!workspaceId &&
    (status === "connected" || status === "error");
  const canSync = !isDemo && !oauthPending && !!connectorId && (status === "connected" || status === "error");
  const canDisconnect = !isDemo && !oauthPending && !!connectorId && (status === "connected" || status === "error");
  const installHref = workspaceId
    ? isSlack
      ? managedConnectAvailable && managedInstallUrl
        ? `${managedInstallUrl}?workspace_id=${workspaceId}`
        : isConfigured
          ? `/api/connectors/slack/install?workspace_id=${workspaceId}`
          : null
      : `/api/connectors/${type}/install?workspace_id=${workspaceId}`
    : null;
  const slackConnectMode = managedConnectAvailable ? "managed" : "self_hosted";
  const zoomOauthHref = isZoom ? installHref : null;
  const processedDocuments = processing?.processedDocuments ?? totalProcessedCount;
  const pendingDocuments = processing?.unprocessedDocuments ?? Math.max(Number(itemsSynced || 0) - processedDocuments, 0);
  const syncStatusQuery = useConnectorSyncStatus(connectorId, {
    enabled: !isDemo && !!connectorId,
  });
  const syncJobsQuery = useConnectorSyncJobs(connectorId, {
    enabled: !isDemo && !!connectorId,
  });
  const latestSyncJob = syncStatusQuery.data;
  const recentSyncJobs = syncJobsQuery.data ?? [];
  const activeSyncStatus =
    latestSyncJob?.status === "pending" || latestSyncJob?.status === "running"
      ? latestSyncJob.status
      : null;
  const previousJobRef = useRef({ jobId: null, status: null });

  const handleSync = () => {
    onActionError(null);
    onActionNotice(null);
    syncMut.mutate(connectorId, {
      onError: (err) => onActionError(err?.message || `Failed to sync ${name}.`),
      onSuccess: (result) =>
        onActionNotice(
          result?.message ||
            (result?.job_id || result?.jobId
              ? `${name} sync queued. Worker status will update below.`
              : `${name} sync started.`),
        ),
    });
  };

  const handleDisconnect = () => {
    onActionError(null);
    onActionNotice(null);
    disconnectMut.mutate(connectorId, {
      onError: (err) => onActionError(err?.message || `Failed to disconnect ${name}.`),
      onSuccess: () => onActionNotice(`${name} disconnected.`),
    });
  };

  const handleSlackOAuthSettingsSave = (event) => {
    event.preventDefault();
    onActionError(null);
    onActionNotice(null);
    saveSlackOAuthMut.mutate(
      {
        clientId: slackClientId,
        clientSecret: slackClientSecret,
        redirectUri: slackRedirectUri,
      },
      {
        onError: (err) => onActionError(formatActionError(err) || "Failed to save Slack OAuth settings."),
        onSuccess: () => {
          onChangeSlackClientSecret("");
          onToggleSlackSetup();
          onActionNotice("Slack OAuth settings saved. You can connect Slack now.");
        },
      },
    );
  };

  const handleNotionConnect = (event) => {
    event.preventDefault();
    onActionError(null);
    onActionNotice(null);
    connectNotionMut.mutate(
      { token: notionToken },
      {
        onError: (err) => onActionError(formatActionError(err) || "Failed to connect Notion."),
        onSuccess: () => {
          onChangeNotionToken("");
          onToggleNotionForm();
          onActionNotice(
            status === "disconnected"
              ? "Notion connected. Run a sync to start storing workspace pages."
              : "Notion token updated. Run another sync to refresh workspace pages.",
          );
        },
      },
    );
  };

  const handleZoomConnect = (event) => {
    event.preventDefault();
    onActionError(null);
    onActionNotice(null);
    connectZoomMut.mutate(
      { token: zoomToken },
      {
        onError: (err) => onActionError(formatActionError(err) || "Failed to connect Zoom."),
        onSuccess: () => {
          onChangeZoomToken("");
          onToggleZoomForm();
          onActionNotice(
            status === "disconnected"
              ? "Zoom manual token saved. Run a sync to start storing meeting transcripts."
              : "Zoom manual token updated. Run another sync to refresh meeting transcripts.",
          );
        },
      },
    );
  };

  const handleGitHubConnect = (event) => {
    event.preventDefault();
    onActionError(null);
    onActionNotice(null);
    const repositories = githubRepositories
      .split(/[\n,]/)
      .map((item) => item.trim())
      .filter(Boolean);
    connectGitHubMut.mutate(
      { token: githubToken, repositories },
      {
        onError: (err) => onActionError(formatActionError(err) || "Failed to connect GitHub."),
        onSuccess: () => {
          onChangeGitHubToken("");
          onChangeGitHubRepositories("");
          onToggleGitHubForm();
          onActionNotice(
            status === "disconnected"
              ? "GitHub token saved. Run a sync to ingest issues, pull requests, and reviews."
              : "GitHub token updated. Run another sync to refresh engineering context.",
          );
        },
      },
    );
  };

  const handleGoogleOAuth = () => {
    if (!installHref) return;
    onStartGenericOAuth(installHref, type);
  };

  useEffect(() => {
    const previous = previousJobRef.current;
    const nextJobId = latestSyncJob?.jobId ?? null;
    const nextStatus = latestSyncJob?.status ?? null;
    const previousWasActive =
      previous.status === "pending" || previous.status === "running";

    if (
      previous.jobId &&
      previous.jobId === nextJobId &&
      previousWasActive &&
      (nextStatus === "completed" || nextStatus === "failed")
    ) {
      onSyncJobSettled(name, latestSyncJob);
    }

    previousJobRef.current = { jobId: nextJobId, status: nextStatus };
  }, [latestSyncJob, name, onSyncJobSettled]);

  return (
    <div className="bg-white dark:bg-slate-800 rounded-xl border border-gray-200 dark:border-gray-800/50 p-5 flex flex-col gap-4 hover:shadow-sm transition-shadow">
      <div className="flex items-center gap-3">
        <span
          className="w-10 h-10 rounded-lg flex items-center justify-center text-white text-sm font-bold shrink-0"
          style={{ backgroundColor: color }}
        >
          {name[0]}
        </span>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-semibold text-gray-800 dark:text-gray-300">{name}</h3>
            {providerLabel && (
              <span
                className={`px-2 py-0.5 rounded-full text-[10px] font-medium ${PROVIDER_PILL[provider] ?? PROVIDER_PILL.native}`}
              >
                {providerLabel}
              </span>
            )}
          </div>
          <p className="text-xs text-gray-500">{description}</p>
        </div>
        <span
          className={`px-2.5 py-0.5 rounded-full text-[11px] font-medium ${STATUS_PILL[status]}`}
        >
          {STATUS_LABEL[status]}
        </span>
      </div>

      <div className="rounded-lg bg-gray-50 dark:bg-gray-900/30 border border-gray-100 dark:border-gray-800/30 p-3">
        <div className="grid grid-cols-2 text-xs text-gray-500 gap-y-1">
          <span>Last sync</span>
          <span className="text-right text-gray-700 dark:text-gray-400">{lastSync}</span>
          <span>Items synced</span>
          <span className="text-right text-gray-700 dark:text-gray-400">{Number(itemsSynced || 0).toLocaleString()}</span>
          <span>Processed</span>
          <span className="text-right text-gray-700 dark:text-gray-400">{Number(processedDocuments || 0).toLocaleString()}</span>
          <span>Pending</span>
          <span className="text-right text-gray-700 dark:text-gray-400">{Number(pendingDocuments || 0).toLocaleString()}</span>
          {teamName && (
            <>
              <span>Workspace</span>
              <span className="text-right text-gray-700 dark:text-gray-400">{teamName}</span>
            </>
          )}
        </div>
        {syncMode && (
          <p className="text-[11px] text-gray-400 mt-2 capitalize">
            Last sync mode: {syncMode}
          </p>
        )}
        {syncModeNote && (
          <p className="text-[11px] text-gray-400 mt-2">
            {syncModeNote}
          </p>
        )}
        {syncQueuedAt && (
          <div className="mt-2 inline-flex items-center gap-2 rounded-full bg-blue-50 dark:bg-blue-900/30 px-2.5 py-1 text-[11px] text-blue-700 dark:text-blue-400">
            <span className="inline-block h-1.5 w-1.5 rounded-full bg-blue-500" />
            Sync queued {syncQueuedAt}
          </div>
        )}
        {latestSyncJob && (
          <div className="mt-3 rounded-lg border border-gray-200 dark:border-gray-800/50 bg-white dark:bg-slate-800 px-3 py-3">
            <div className="flex items-center justify-between gap-3">
              <p className="text-[11px] uppercase tracking-wide text-gray-400">Latest job</p>
              <span
                className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${
                  latestSyncJob.status === "completed"
                    ? "bg-emerald-100 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-400"
                    : latestSyncJob.status === "failed"
                      ? "bg-red-100 dark:bg-red-900/40 text-red-700 dark:text-red-400"
                      : "bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-400"
                }`}
              >
                {latestSyncJob.status}
              </span>
            </div>
            <p className="mt-2 text-[11px] text-gray-500">
              Created {formatDateTime(latestSyncJob.createdAt)}
              {latestSyncJob.startedAt ? ` · Started ${formatDateTime(latestSyncJob.startedAt)}` : ""}
              {latestSyncJob.completedAt ? ` · Finished ${formatDateTime(latestSyncJob.completedAt)}` : ""}
            </p>
            {latestSyncJob.status === "completed" && (
              <p className="mt-2 text-[11px] text-emerald-700 dark:text-emerald-400">
                {formatCompletedSyncNotice(name, latestSyncJob.resultMetadata)}
              </p>
            )}
            {latestSyncJob.status === "failed" && (
              <p className="mt-2 text-[11px] text-red-600 dark:text-red-400">
                {latestSyncJob.errorType ? `${latestSyncJob.errorType}: ` : ""}
                {latestSyncJob.errorMessage || "Sync failed."}
              </p>
            )}
            {activeSyncStatus && (
              <p className="mt-2 text-[11px] text-blue-700 dark:text-blue-400">
                Worker is {activeSyncStatus === "running" ? "running" : "queued"} for this connector.
              </p>
            )}
          </div>
        )}
        {recentSyncJobs.length > 1 && (
          <div className="mt-3 rounded-lg border border-gray-200 dark:border-gray-800/50 bg-white dark:bg-slate-800 px-3 py-3">
            <div className="flex items-center justify-between gap-3">
              <p className="text-[11px] uppercase tracking-wide text-gray-400">Recent runs</p>
              {connectorId && (
                <Link
                  to={`/app/connectors/${type}/runs`}
                  className="text-[11px] font-medium text-brand-700 dark:text-brand-400 hover:text-brand-800 dark:text-brand-300"
                >
                  View all runs
                </Link>
              )}
            </div>
            <div className="mt-2 space-y-2">
              {recentSyncJobs.slice(0, 4).map((job) => (
                <div key={job.jobId ?? `${job.status}-${job.createdAt}`} className="flex items-start justify-between gap-3 text-[11px]">
                  <div className="min-w-0">
                    <p className="text-gray-700 dark:text-gray-400">
                      {job.status === "completed"
                        ? summarizeSyncJob(job.resultMetadata)
                        : job.status === "failed"
                          ? job.errorMessage || "Sync failed."
                          : `Job ${job.status}`}
                    </p>
                    <p className="mt-0.5 text-gray-400">
                      {job.createdAt ? formatDateTime(job.createdAt) : "Unknown start time"}
                    </p>
                  </div>
                  <span
                    className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-medium ${
                      job.status === "completed"
                        ? "bg-emerald-100 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-400"
                        : job.status === "failed"
                          ? "bg-red-100 dark:bg-red-900/40 text-red-700 dark:text-red-400"
                          : "bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-400"
                    }`}
                  >
                    {job.status}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
        {message && !isSlack && (
          <p className="text-[11px] text-gray-500 mt-2">{message}</p>
        )}
        {providerNote && (
          <p className="text-[11px] text-gray-400 mt-2">
            Connector path: {providerNote}
          </p>
        )}
        {isZoom && (
          <ZoomCapabilityPanel
            status={status}
            authMode={authMode}
            accountId={accountId}
            ingestionMode={ingestionMode}
            sourceFocus={sourceFocus}
            lastWebhookEvent={lastWebhookEvent}
            lastWebhookReceivedAt={lastWebhookReceivedAt}
            oauthHref={zoomOauthHref}
            isDemo={isDemo}
            oauthPending={oauthPending}
          />
        )}
        {isGitHub && <GitHubCapabilityPanel repositories={connector.repositories ?? null} />}
        {scope && (
          <p className="text-[11px] text-gray-400 mt-2">
            Slack scopes: {scope}
          </p>
        )}
        {isSlack && status === "disconnected" && availability === "available" && (
          <SlackSetupHint isConfigured={isConfigured} managedConnectAvailable={managedConnectAvailable} />
        )}
        {isSlack && slackSetupOpen && (
          <SlackOAuthSettingsForm
            clientId={slackClientId}
            clientSecret={slackClientSecret}
            redirectUri={slackRedirectUri}
            isSaving={saveSlackOAuthMut.isPending}
            onChangeClientId={onChangeSlackClientId}
            onChangeClientSecret={onChangeSlackClientSecret}
            onChangeRedirectUri={onChangeSlackRedirectUri}
            onSubmit={handleSlackOAuthSettingsSave}
            onCancel={onToggleSlackSetup}
          />
        )}
        {isNotion && status === "disconnected" && availability === "available" && (
          <p className="text-[11px] text-gray-500 mt-2">
            Add a Notion integration token, then sync pages into stored source documents for extraction and query.
          </p>
        )}
        {isZoom && status === "disconnected" && availability === "available" && (
          <p className="text-[11px] text-gray-500 mt-2">
            Choose OAuth for webhook-driven transcript sync, or save a manual token if polling-only ingestion is enough for now.
          </p>
        )}
        {isGitHub && status === "disconnected" && availability === "available" && (
          <p className="text-[11px] text-gray-500 mt-2">
            Save a GitHub token plus one or more repositories to ingest issues, pull requests, reviews, and comment threads.
          </p>
        )}
        {isGDrive && status === "disconnected" && availability === "available" && (
          <p className="text-[11px] text-gray-500 mt-2">
            Connect with your Google account to start syncing Docs, Sheets, and Slides as structured source documents.
          </p>
        )}
        {isGmail && status === "disconnected" && availability === "available" && (
          <p className="text-[11px] text-gray-500 mt-2">
            Connect with your Google account to ingest email threads and extract facts from important conversations.
          </p>
        )}
        {isSlack && status === "error" && (
          <p className="text-[11px] text-red-600 dark:text-red-400 mt-2">
            Slack needs attention. Reconnect the workspace or retry sync after checking OAuth and connector health.
          </p>
        )}
        {isNotion && status === "error" && (
          <p className="text-[11px] text-red-600 dark:text-red-400 mt-2">
            Notion needs attention. Update the integration token, then run another sync.
          </p>
        )}
        {isZoom && status === "error" && (
          <p className="text-[11px] text-red-600 dark:text-red-400 mt-2">
            Zoom needs attention. Reconnect OAuth or update the manual token, then run another sync.
          </p>
        )}
        {isGitHub && status === "error" && (
          <p className="text-[11px] text-red-600 dark:text-red-400 mt-2">
            GitHub needs attention. Update the token or repository list, then run another sync.
          </p>
        )}
        {status === "connected" && teamName && (
          <p className="text-[11px] text-emerald-700 dark:text-emerald-400 mt-2">
            Connected and ready for ingestion.
          </p>
        )}
        {status === "connected" && itemsSynced > 0 && (
          <div className="mt-2">
            <p className="text-[11px] text-emerald-700 dark:text-emerald-400">
              {formatDocumentCount(itemsSynced)} available for extraction and query.
            </p>
            <Link to="/app/sources" className="inline-flex mt-1 text-[11px] font-medium text-emerald-700 dark:text-emerald-400 underline">
              Inspect stored documents
            </Link>
          </div>
        )}
        {status === "connected" && itemsSynced === 0 && !syncQueuedAt && (
          <p className="text-[11px] text-gray-500 mt-2">
            OAuth is complete. Run a sync to start storing Slack history in the database.
          </p>
        )}
        {isNotion && status === "connected" && itemsSynced === 0 && !syncQueuedAt && (
          <p className="text-[11px] text-gray-500 mt-2">
            Notion is connected. Run a sync to store workspace pages and surface them in Sources and Query.
          </p>
        )}
        {isZoom && status === "connected" && itemsSynced === 0 && !syncQueuedAt && (
          <p className="text-[11px] text-gray-500 mt-2">
            {authMode === "oauth"
              ? "Zoom OAuth is connected. Webhook-driven sync is ready for supported recording events, or you can run a sync now."
              : "Zoom is connected in manual polling mode. Run a sync to store meeting transcripts and surface them in Sources and Query."}
          </p>
        )}
        {isGitHub && status === "connected" && itemsSynced === 0 && !syncQueuedAt && (
          <p className="text-[11px] text-gray-500 mt-2">
            GitHub is connected. Run a sync to store issues, pull requests, review threads, and linked engineering discussion.
          </p>
        )}
        {status === "coming_soon" && (
          <p className="text-[11px] text-gray-500 mt-2">
            Backend support for this connector is intentionally deferred until the Slack path is stable.
          </p>
        )}
      </div>

      {isNotion && notionFormOpen && (
        <form onSubmit={handleNotionConnect} className="rounded-lg border border-gray-200 dark:border-gray-800/50 bg-gray-50 dark:bg-gray-900/30 p-3 space-y-3">
          <div>
            <label htmlFor="notion-token" className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
              Notion integration token
            </label>
            <input
              id="notion-token"
              type="password"
              value={notionToken}
              onChange={(event) => onChangeNotionToken(event.target.value)}
              placeholder="secret_xxx"
              className="w-full rounded-lg border border-gray-200 dark:border-gray-800/50 bg-white dark:bg-slate-800 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500/40"
            />
          </div>
          <div className="flex gap-2">
            <button
              type="submit"
              disabled={connectNotionMut.isPending || !notionToken.trim()}
              className="px-3 py-1.5 text-xs font-medium rounded-lg bg-brand-600 text-white hover:bg-brand-700 disabled:bg-gray-300 disabled:cursor-not-allowed"
            >
              {connectNotionMut.isPending
                ? "Saving..."
                : status === "connected" || status === "error"
                  ? "Save Notion token"
                  : "Save Notion token"}
            </button>
            <button
              type="button"
              onClick={onToggleNotionForm}
              className="px-3 py-1.5 text-xs font-medium rounded-lg border border-gray-200 dark:border-gray-800/50 text-gray-700 dark:text-gray-400 hover:bg-white dark:bg-slate-800"
            >
              Cancel
            </button>
          </div>
        </form>
      )}

      {isZoom && zoomFormOpen && (
        <form onSubmit={handleZoomConnect} className="rounded-lg border border-gray-200 dark:border-gray-800/50 bg-gray-50 dark:bg-gray-900/30 p-3 space-y-3">
          <div>
            <label htmlFor="zoom-token" className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
              Zoom access token
            </label>
            <input
              id="zoom-token"
              type="password"
              value={zoomToken}
              onChange={(event) => onChangeZoomToken(event.target.value)}
              placeholder="zoom_access_token"
              className="w-full rounded-lg border border-gray-200 dark:border-gray-800/50 bg-white dark:bg-slate-800 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500/40"
            />
          </div>
          <div className="flex gap-2">
            <button
              type="submit"
              disabled={connectZoomMut.isPending || !zoomToken.trim()}
              className="px-3 py-1.5 text-xs font-medium rounded-lg bg-brand-600 text-white hover:bg-brand-700 disabled:bg-gray-300 disabled:cursor-not-allowed"
            >
              {connectZoomMut.isPending ? "Saving..." : "Save Zoom token"}
            </button>
            <button
              type="button"
              onClick={onToggleZoomForm}
              className="px-3 py-1.5 text-xs font-medium rounded-lg border border-gray-200 dark:border-gray-800/50 text-gray-700 dark:text-gray-400 hover:bg-white dark:bg-slate-800"
            >
              Cancel
            </button>
          </div>
        </form>
      )}

      {isGitHub && githubFormOpen && (
        <form onSubmit={handleGitHubConnect} className="rounded-lg border border-gray-200 dark:border-gray-800/50 bg-gray-50 dark:bg-gray-900/30 p-3 space-y-3">
          <div>
            <label htmlFor="github-token" className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
              GitHub access token
            </label>
            <input
              id="github-token"
              type="password"
              value={githubToken}
              onChange={(event) => onChangeGitHubToken(event.target.value)}
              placeholder="ghp_xxx"
              className="w-full rounded-lg border border-gray-200 dark:border-gray-800/50 bg-white dark:bg-slate-800 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500/40"
            />
          </div>
          <div>
            <label htmlFor="github-repositories" className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
              Repositories
            </label>
            <textarea
              id="github-repositories"
              value={githubRepositories}
              onChange={(event) => onChangeGitHubRepositories(event.target.value)}
              placeholder={"acme/context-engine\nacme/platform"}
              rows={3}
              className="w-full rounded-lg border border-gray-200 dark:border-gray-800/50 bg-white dark:bg-slate-800 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500/40"
            />
            <p className="mt-1 text-[11px] text-gray-500">
              One `owner/repo` per line or comma separated.
            </p>
          </div>
          <div className="flex gap-2">
            <button
              type="submit"
              disabled={
                connectGitHubMut.isPending ||
                !githubToken.trim() ||
                !githubRepositories.trim()
              }
              className="px-3 py-1.5 text-xs font-medium rounded-lg bg-brand-600 text-white hover:bg-brand-700 disabled:bg-gray-300 disabled:cursor-not-allowed"
            >
              {connectGitHubMut.isPending ? "Saving..." : "Save GitHub token"}
            </button>
            <button
              type="button"
              onClick={onToggleGitHubForm}
              className="px-3 py-1.5 text-xs font-medium rounded-lg border border-gray-200 dark:border-gray-800/50 text-gray-700 dark:text-gray-400 hover:bg-white dark:bg-slate-800"
            >
              Cancel
            </button>
          </div>
        </form>
      )}

      <div className="flex flex-wrap gap-2 mt-auto">
        {status === "coming_soon" ? (
          <button
            type="button"
            disabled
            className="px-3 py-1.5 text-xs font-medium rounded-lg border border-gray-200 dark:border-gray-800/50 text-gray-400 cursor-not-allowed"
          >
            Coming soon
          </button>
        ) : isSlack && canConnect && installHref ? (
          <button
            type="button"
            onClick={() => onStartOAuth(installHref, status, slackConnectMode)}
            className="inline-flex items-center gap-2 rounded-full bg-white border border-gray-200 px-4 py-2 text-sm font-medium text-gray-900 hover:bg-gray-50 shadow-sm transition-colors dark:bg-slate-800 dark:border-gray-700 dark:text-white dark:hover:bg-slate-700"
          >
            <SlackLogoIcon className="w-5 h-5" />
            Connect to Slack
          </button>
        ) : isSlack && canConnect && !installHref ? (
          <span className="inline-flex items-center rounded-lg bg-amber-50 dark:bg-amber-900/30 px-3 py-1.5 text-xs font-medium text-amber-700 dark:text-amber-400 border border-amber-200 dark:border-amber-800/50">
            Slack OAuth not configured
          </span>
        ) : isSlack && canReconnect && installHref ? (
          <a
            href={installHref}
            onClick={(event) => {
              event.preventDefault();
              onStartOAuth(installHref, status, slackConnectMode);
            }}
            className="px-3 py-1.5 text-xs font-medium rounded-lg border border-gray-200 dark:border-gray-800/50 text-gray-700 dark:text-gray-400 hover:bg-gray-50 dark:bg-gray-900/30 transition-colors"
          >
            Reconnect Slack
          </a>
        ) : isSlack && canReconnect && !installHref ? (
          <span className="inline-flex items-center rounded-lg bg-amber-50 dark:bg-amber-900/30 px-3 py-1.5 text-xs font-medium text-amber-700 dark:text-amber-400 border border-amber-200 dark:border-amber-800/50">
            Slack OAuth not configured
          </span>
        ) : isGoogleOAuth && canConnect && installHref ? (
          <button
            type="button"
            disabled={isDemo || !workspaceId}
            onClick={handleGoogleOAuth}
            className="inline-flex items-center gap-2 rounded-full bg-white border border-gray-200 px-4 py-2 text-sm font-medium text-gray-900 hover:bg-gray-50 shadow-sm transition-colors dark:bg-slate-800 dark:border-gray-700 dark:text-white dark:hover:bg-slate-700"
          >
            <GoogleIcon className="w-4 h-4" />
            Connect with Google
          </button>
        ) : isGoogleOAuth && canConnect && !installHref ? (
          <span className="inline-flex items-center rounded-lg bg-amber-50 dark:bg-amber-900/30 px-3 py-1.5 text-xs font-medium text-amber-700 dark:text-amber-400 border border-amber-200 dark:border-amber-800/50">
            Google OAuth not configured
          </span>
        ) : isGoogleOAuth && canReconnect && installHref ? (
          <button
            type="button"
            onClick={handleGoogleOAuth}
            className="px-3 py-1.5 text-xs font-medium rounded-lg border border-gray-200 dark:border-gray-800/50 text-gray-700 dark:text-gray-400 hover:bg-gray-50 dark:bg-gray-900/30 transition-colors"
          >
            Reconnect Google
          </button>
        ) : isGoogleOAuth && canReconnect && !installHref ? (
          <span className="inline-flex items-center rounded-lg bg-amber-50 dark:bg-amber-900/30 px-3 py-1.5 text-xs font-medium text-amber-700 dark:text-amber-400 border border-amber-200 dark:border-amber-800/50">
            Google OAuth not configured
          </span>
        ) : isNotion && status === "disconnected" ? (
          <button
            type="button"
            disabled={isDemo || !workspaceId}
            onClick={onToggleNotionForm}
            className="px-3 py-1.5 text-xs font-medium rounded-lg bg-brand-600 text-white hover:bg-brand-700 disabled:bg-gray-300 disabled:cursor-not-allowed"
          >
            Connect Notion
          </button>
        ) : isNotion && (status === "connected" || status === "error") ? (
          <button
            type="button"
            disabled={isDemo}
            onClick={onToggleNotionForm}
            className="px-3 py-1.5 text-xs font-medium rounded-lg border border-gray-200 dark:border-gray-800/50 text-gray-700 dark:text-gray-400 hover:bg-gray-50 dark:bg-gray-900/30 disabled:text-gray-400 disabled:cursor-not-allowed"
          >
            Update Notion token
          </button>
        ) : isZoom && status === "disconnected" ? (
          <button
            type="button"
            disabled={isDemo || !workspaceId}
            onClick={onToggleZoomForm}
            className="px-3 py-1.5 text-xs font-medium rounded-lg bg-brand-600 text-white hover:bg-brand-700 disabled:bg-gray-300 disabled:cursor-not-allowed"
          >
            Use manual token
          </button>
        ) : isZoom && (status === "connected" || status === "error") ? (
          <button
            type="button"
            disabled={isDemo}
            onClick={onToggleZoomForm}
            className="px-3 py-1.5 text-xs font-medium rounded-lg border border-gray-200 dark:border-gray-800/50 text-gray-700 dark:text-gray-400 hover:bg-gray-50 dark:bg-gray-900/30 disabled:text-gray-400 disabled:cursor-not-allowed"
          >
            Update Zoom token
          </button>
        ) : isGitHub && status === "disconnected" ? (
          <button
            type="button"
            disabled={isDemo || !workspaceId}
            onClick={onToggleGitHubForm}
            className="px-3 py-1.5 text-xs font-medium rounded-lg bg-brand-600 text-white hover:bg-brand-700 disabled:bg-gray-300 disabled:cursor-not-allowed"
          >
            Connect GitHub
          </button>
        ) : isGitHub && (status === "connected" || status === "error") ? (
          <button
            type="button"
            disabled={isDemo}
            onClick={onToggleGitHubForm}
            className="px-3 py-1.5 text-xs font-medium rounded-lg border border-gray-200 dark:border-gray-800/50 text-gray-700 dark:text-gray-400 hover:bg-gray-50 dark:bg-gray-900/30 disabled:text-gray-400 disabled:cursor-not-allowed"
          >
            Update GitHub token
          </button>
        ) : (
          <button
            type="button"
            disabled
            className="px-3 py-1.5 text-xs font-medium rounded-lg border border-gray-200 dark:border-gray-800/50 text-gray-400 cursor-not-allowed"
          >
          {isDemo
              ? "Demo mode"
              : oauthPending
                ? "Waiting for Slack..."
                : workspaceId
                  ? "Already connected"
                  : "Select workspace"}
          </button>
        )}

        {isSlack && slackSelfHostedSetupAvailable && status === "disconnected" && !isDemo && (
          <button
            type="button"
            onClick={onToggleSlackSetup}
            className="px-3 py-1.5 text-xs font-medium rounded-lg border border-gray-200 dark:border-gray-800/50 text-gray-700 dark:text-gray-400 hover:bg-gray-50 dark:bg-gray-900/30 transition-colors"
          >
            Advanced self-hosted setup
          </button>
        )}

        <button
          type="button"
          disabled={!canSync || syncMut.isPending || !!activeSyncStatus}
          onClick={handleSync}
          className="px-3 py-1.5 text-xs font-medium rounded-lg border border-gray-200 dark:border-gray-800/50 text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:bg-gray-900/30 disabled:text-gray-400 disabled:cursor-not-allowed transition-colors"
        >
          {activeSyncStatus === "running"
            ? "Running..."
            : activeSyncStatus === "pending"
              ? "Queued..."
              : syncMut.isPending && syncMut.variables === connectorId
                ? "Starting..."
                : "Sync now"}
        </button>

        <button
          type="button"
          disabled={!canDisconnect || disconnectMut.isPending}
          onClick={handleDisconnect}
          className="px-3 py-1.5 text-xs font-medium rounded-lg border border-red-200 dark:border-red-800/50 text-red-600 dark:text-red-400 hover:bg-red-50 dark:bg-red-900/30 disabled:text-gray-400 disabled:border-gray-200 dark:border-gray-800/50 disabled:cursor-not-allowed transition-colors"
        >
          {disconnectMut.isPending && disconnectMut.variables === connectorId
            ? "Disconnecting..."
            : "Disconnect"}
        </button>
      </div>
    </div>
  );
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

function summarizeSyncJob(metadata) {
  if (!metadata || typeof metadata !== "object") {
    return "Sync completed.";
  }
  const fetched = Number(metadata.documents_fetched ?? 0);
  const persisted = Number(metadata.documents_persisted ?? 0);
  const processed = Number(metadata.documents_processed ?? 0);
  return `Fetched ${fetched}, stored ${persisted}, processed ${processed}`;
}

function formatDateTime(value) {
  if (!value) return "—";
  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}

function formatActionError(error) {
  if (!error) return null;
  if (Array.isArray(error.detail)) {
    return error.detail.map((item) => item.msg).join(". ");
  }
  return error.message || null;
}

function ZoomCapabilityPanel({
  status,
  authMode,
  accountId,
  ingestionMode,
  sourceFocus,
  lastWebhookEvent,
  lastWebhookReceivedAt,
  oauthHref,
  isDemo,
  oauthPending,
}) {
  const mode = authMode === "oauth" ? "oauth" : authMode === "manual_token" ? "manual_token" : "unknown";
  const badgeClass =
    mode === "oauth"
      ? "bg-emerald-100 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-400"
      : mode === "manual_token"
        ? "bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-400"
        : "bg-gray-100 dark:bg-gray-900/40 text-gray-600 dark:text-gray-400";

  const modeLabel =
    mode === "oauth"
      ? "OAuth auto-sync"
      : mode === "manual_token"
        ? "Manual polling"
        : "Choose auth mode";

  const modeSummary =
    mode === "oauth"
      ? "Webhook-triggered sync is enabled for supported transcript and recording completion events."
      : mode === "manual_token"
        ? "This connector stays polling-only. Use Sync now to pull transcripts, or upgrade to OAuth for webhook-driven sync."
        : "Zoom supports OAuth for webhook-triggered auto-sync or a manual token for polling-only transcript sync.";

  const ctaLabel =
    status === "connected" || status === "error"
      ? mode === "oauth"
        ? "Refresh Zoom OAuth"
        : "Upgrade to Zoom OAuth"
      : "Connect Zoom OAuth";

  return (
    <div className="mt-3 rounded-lg border border-sky-200 bg-sky-50 px-3 py-3 dark:border-sky-500/20 dark:bg-sky-500/10">
      <div className="flex items-center justify-between gap-3">
        <p className="text-[11px] font-bold uppercase tracking-wide text-sky-800 dark:text-sky-200">Zoom sync mode</p>
        <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${badgeClass}`}>
          {modeLabel}
        </span>
      </div>
      <p className="mt-2 text-sm leading-5 text-sky-900 dark:text-sky-100">{modeSummary}</p>
      {(ingestionMode || sourceFocus) && (
        <p className="mt-2 text-xs text-sky-800 dark:text-sky-200/80">
          {ingestionMode === "transcripts_only" ? "Transcript-only ingestion" : ingestionMode || "Ingestion configured"}
          {sourceFocus ? ` · ${sourceFocus.replaceAll("_", " ")}` : ""}
        </p>
      )}
      {accountId && (
        <p className="mt-1 text-xs text-sky-800 dark:text-sky-200/80">
          Account: {accountId}
        </p>
      )}
      {(lastWebhookEvent || lastWebhookReceivedAt) && (
        <p className="mt-1 text-xs text-sky-800 dark:text-sky-200/80">
          Last webhook:
          {lastWebhookEvent ? ` ${lastWebhookEvent}` : " event received"}
          {lastWebhookReceivedAt ? ` · ${lastWebhookReceivedAt}` : ""}
        </p>
      )}
      {!isDemo && !oauthPending && oauthHref && (
        <a
          href={oauthHref}
          className="mt-3 inline-flex rounded-lg border border-sky-300 bg-white/80 px-3 py-1.5 text-xs font-bold text-sky-800 transition-colors hover:bg-white hover:text-sky-950 dark:border-sky-400/30 dark:bg-sky-950/40 dark:text-sky-100 dark:hover:bg-sky-900/60"
        >
          {ctaLabel}
        </a>
      )}
    </div>
  );
}

function GitHubCapabilityPanel({ repositories }) {
  const repoList = Array.isArray(repositories) ? repositories : [];
  return (
    <div className="mt-3 rounded-lg border border-gray-100 dark:border-gray-800/30 bg-gray-50 dark:bg-gray-900/30 px-3 py-3">
      <p className="text-[11px] uppercase tracking-wide text-gray-500">GitHub scope</p>
      <p className="mt-2 text-[11px] text-gray-700 dark:text-gray-400">
        Polling-first engineering context from issues, pull requests, reviews, and comments.
      </p>
      {repoList.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {repoList.map((repo) => (
            <span
              key={repo}
              className="rounded-full bg-white dark:bg-slate-800 px-2 py-0.5 text-[10px] font-medium text-gray-700 dark:text-gray-400 border border-gray-200 dark:border-gray-800/50"
            >
              {repo}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function SlackSetupHint({ isConfigured, managedConnectAvailable }) {
  if (isConfigured || managedConnectAvailable) {
    return (
      <p className="text-[11px] text-gray-500 mt-2">
        Connect Slack to start ingesting messages, threads, and source-backed pricing or roadmap facts.
      </p>
    );
  }

  return (
    <p className="text-[11px] text-gray-500 mt-2">
      Connect Slack through the managed app flow. Self-hosted Slack app credentials are available under advanced setup.
    </p>
  );
}

function SlackConnectModal({ mode, onCancel, onContinue }) {
  const isManaged = mode === "managed";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 px-4">
      <div className="w-full max-w-lg rounded-2xl border border-gray-200 dark:border-gray-800/60 bg-white dark:bg-slate-900 p-6 shadow-2xl">
        <div className="flex justify-end">
          <button
            type="button"
            onClick={onCancel}
            className="rounded-lg p-1 text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 transition-colors"
            aria-label="Close Slack connection dialog"
          >
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
        <div className="flex items-center justify-center gap-4">
          <div className="flex h-14 w-14 items-center justify-center rounded-xl bg-gradient-to-br from-brand-400 to-brand-600 text-white text-xl font-bold shadow-lg">
            CE
          </div>
          <div className="flex gap-1">
            <span className="inline-block h-2 w-2 rounded-full bg-gray-300 dark:bg-gray-600" />
            <span className="inline-block h-2 w-2 rounded-full bg-gray-300 dark:bg-gray-600" />
            <span className="inline-block h-2 w-2 rounded-full bg-gray-300 dark:bg-gray-600" />
          </div>
          <div className="flex h-14 w-14 items-center justify-center rounded-xl bg-white border border-gray-200 shadow-sm">
            <SlackLogoIcon className="w-8 h-8" />
          </div>
        </div>
        <div className="mt-6 text-center">
          <h3 className="text-2xl font-semibold text-gray-900 dark:text-gray-100">
            Connect Context Engine to Slack
          </h3>
          <p className="mt-2 text-sm text-gray-500">
            {isManaged ? "Managed install" : "Self-hosted Slack app"}
          </p>
        </div>

        <div className="mt-6 rounded-xl border border-gray-200 dark:border-gray-800/60 p-5 text-sm text-gray-700 dark:text-gray-300 space-y-4">
          <div>
            <p className="font-semibold text-gray-900 dark:text-gray-100">Permissions always respected</p>
            <p className="mt-1.5 leading-relaxed">
              Context Engine is strictly limited to the scopes you explicitly approve during install. You can revoke access anytime from your Slack workspace settings.
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              {["channels:history", "channels:read", "groups:history", "groups:read", "users:read", "team:read"].map((scope) => (
                <span key={scope} className="inline-flex items-center rounded-md bg-gray-100 dark:bg-gray-800 px-2 py-1 text-[11px] font-medium text-gray-600 dark:text-gray-400">
                  {scope}
                </span>
              ))}
            </div>
          </div>
          <div className="border-t border-gray-200 dark:border-gray-800/60" />
          <div>
            <p className="font-semibold text-gray-900 dark:text-gray-100">You're in control</p>
            <p className="mt-1.5 leading-relaxed">
              You can disconnect the workspace from Context Engine at any time. No messages are sent or posted to Slack.
            </p>
          </div>
          <div className="border-t border-gray-200 dark:border-gray-800/60" />
          <div>
            <p className="font-semibold text-gray-900 dark:text-gray-100">Connectors may introduce risk</p>
            <p className="mt-1.5 leading-relaxed">
              Connect only workspaces whose documents and messages should be available to this Context Engine instance.
            </p>
          </div>
        </div>

        <button
          type="button"
          onClick={onContinue}
          className="mt-6 w-full rounded-full bg-gray-900 px-5 py-3 text-sm font-semibold text-white hover:bg-gray-800 dark:bg-white dark:text-gray-900 dark:hover:bg-gray-100 transition-colors inline-flex items-center justify-center gap-2"
        >
          Continue to Slack
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M7 17L17 7M17 7H7M17 7v10" />
          </svg>
        </button>
      </div>
    </div>
  );
}

function SlackOAuthSettingsForm({
  clientId,
  clientSecret,
  redirectUri,
  isSaving,
  onChangeClientId,
  onChangeClientSecret,
  onChangeRedirectUri,
  onSubmit,
  onCancel,
}) {
  const canSave = clientId.trim() && clientSecret.trim() && redirectUri.trim();

  return (
    <form
      onSubmit={onSubmit}
      className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-3 text-xs text-amber-900 dark:border-amber-800/50 dark:bg-amber-900/30 dark:text-amber-200"
    >
      <div className="grid gap-3">
        <div>
          <label htmlFor="slack-client-id" className="block font-medium">
            Slack client ID
          </label>
          <input
            id="slack-client-id"
            value={clientId}
            onChange={(event) => onChangeClientId(event.target.value)}
            placeholder="123456789.123456789"
            className="mt-1 w-full rounded-lg border border-amber-200 bg-white px-3 py-2 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-amber-500/40 dark:border-amber-800/50 dark:bg-slate-900 dark:text-gray-100"
          />
        </div>
        <div>
          <label htmlFor="slack-client-secret" className="block font-medium">
            Slack client secret
          </label>
          <input
            id="slack-client-secret"
            type="password"
            value={clientSecret}
            onChange={(event) => onChangeClientSecret(event.target.value)}
            placeholder="Slack app client secret"
            className="mt-1 w-full rounded-lg border border-amber-200 bg-white px-3 py-2 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-amber-500/40 dark:border-amber-800/50 dark:bg-slate-900 dark:text-gray-100"
          />
        </div>
        <div>
          <label htmlFor="slack-redirect-uri" className="block font-medium">
            Redirect URL
          </label>
          <input
            id="slack-redirect-uri"
            value={redirectUri}
            onChange={(event) => onChangeRedirectUri(event.target.value)}
            className="mt-1 w-full rounded-lg border border-amber-200 bg-white px-3 py-2 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-amber-500/40 dark:border-amber-800/50 dark:bg-slate-900 dark:text-gray-100"
          />
        </div>
      </div>
      <p className="mt-3 text-[11px]">
        Use the manifest in docs/slack.md, paste these values once, then the normal Slack connect button becomes available.
      </p>
      <div className="mt-3 flex flex-wrap gap-2">
        <button
          type="submit"
          disabled={isSaving || !canSave}
          className="px-3 py-1.5 text-xs font-medium rounded-lg bg-amber-600 text-white hover:bg-amber-700 disabled:bg-gray-300 disabled:cursor-not-allowed"
        >
          {isSaving ? "Saving..." : "Save Slack settings"}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="px-3 py-1.5 text-xs font-medium rounded-lg border border-amber-200 bg-white text-amber-900 hover:bg-amber-100 dark:border-amber-800/50 dark:bg-slate-900 dark:text-amber-200"
        >
          Cancel
        </button>
      </div>
    </form>
  );
}

function SlackSummaryBanner({ connector, isDemo, oauthPending, workspaceId, onStartOAuth }) {
  const isConfigured = connector.isConfigured ?? true;
  const managedConnectAvailable = connector.managedConnectAvailable ?? false;
  const managedInstallUrl = connector.managedInstallUrl ?? null;
  const reconnectHref = workspaceId
    ? managedConnectAvailable && managedInstallUrl
      ? `${managedInstallUrl}?workspace_id=${workspaceId}`
      : isConfigured
        ? `/api/connectors/slack/install?workspace_id=${workspaceId}`
        : null
    : null;
  const slackConnectMode = managedConnectAvailable ? "managed" : "self_hosted";

  if (connector.status === "connected") {
    return (
      <div className="rounded-xl border border-emerald-200 dark:border-emerald-800/50 bg-emerald-50 dark:bg-emerald-900/30 p-4 flex items-start justify-between gap-4">
        <div>
          <p className="text-sm font-medium text-emerald-800 dark:text-emerald-300">
            Slack is connected{connector.teamName ? ` to ${connector.teamName}` : ""}.
          </p>
          <p className="text-xs text-emerald-700 dark:text-emerald-400 mt-1">
            {connector.syncQueuedAt
              ? `A sync is queued for ${connector.syncQueuedAt}.`
              : connector.itemsSynced > 0
                ? `${formatDocumentCount(connector.itemsSynced)} available for extraction and query.`
                : `Last completed sync: ${connector.lastSync}. Run a sync to store Slack history.`}
          </p>
          {connector.itemsSynced > 0 && (
            <Link to="/app/sources" className="inline-flex mt-3 text-xs font-medium text-emerald-800 dark:text-emerald-300 underline">
              Inspect stored documents
            </Link>
          )}
        </div>
        {!isDemo && !oauthPending && reconnectHref && (
          <a
            href={reconnectHref}
            onClick={(event) => {
              event.preventDefault();
              onStartOAuth(reconnectHref, connector.status, slackConnectMode);
            }}
            className="shrink-0 px-3 py-1.5 text-xs font-medium rounded-lg border border-emerald-200 dark:border-emerald-800/50 text-emerald-800 dark:text-emerald-300 hover:bg-white/70 transition-colors"
          >
            Refresh OAuth
          </a>
        )}
      </div>
    );
  }

  if (connector.status === "error") {
    return (
      <div className="rounded-xl border border-red-200 dark:border-red-800/50 bg-red-50 dark:bg-red-900/30 p-4 flex items-start justify-between gap-4">
        <div>
          <p className="text-sm font-medium text-red-800 dark:text-red-300">Slack needs attention.</p>
          <p className="text-xs text-red-700 dark:text-red-400 mt-1">
            Reconnect the workspace to refresh credentials, then run another sync.
          </p>
        </div>
        {!isDemo && !oauthPending && reconnectHref && (
          <a
            href={reconnectHref}
            onClick={(event) => {
              event.preventDefault();
              onStartOAuth(reconnectHref, connector.status, slackConnectMode);
            }}
            className="shrink-0 px-3 py-1.5 text-xs font-medium rounded-lg bg-red-600 text-white hover:bg-red-700 transition-colors"
          >
            Refresh OAuth
          </a>
        )}
      </div>
    );
  }

  if (connector.status === "disconnected") {
    const isConfiguredBanner = connector.isConfigured ?? true;
    return (
      <div className="rounded-xl border border-amber-200 dark:border-amber-800/50 bg-amber-50 dark:bg-amber-900/30 p-4 flex items-start justify-between gap-4">
        <div>
          <p className="text-sm font-medium text-amber-800 dark:text-amber-300">Slack is not connected yet.</p>
          <p className="text-xs text-amber-700 dark:text-amber-400 mt-1">
            {isConfiguredBanner
              ? "Connect Slack to ingest channel history, threads, and source-backed team context."
              : "A Slack app is required before connecting. Use Advanced self-hosted setup below to add your credentials, or ask your operator to set environment variables."}
          </p>
        </div>
        {!isDemo && !oauthPending && reconnectHref && (
          <button
            type="button"
            onClick={() => onStartOAuth(reconnectHref, connector.status, slackConnectMode)}
            className="shrink-0 inline-flex items-center gap-2 rounded-full bg-white border border-gray-200 px-4 py-2 text-sm font-medium text-gray-900 hover:bg-gray-50 shadow-sm transition-colors dark:bg-slate-800 dark:border-gray-700 dark:text-white dark:hover:bg-slate-700"
          >
            <SlackLogoIcon className="w-5 h-5" />
            Connect to Slack
          </button>
        )}
      </div>
    );
  }

  return null;
}

function SlackLogoIcon({ className }) {
  return (
    <svg className={className} viewBox="0 0 127 127" xmlns="http://www.w3.org/2000/svg">
      <path d="M27.2 80c0 7.3-5.9 13.2-13.2 13.2S.8 87.3.8 80s5.9-13.2 13.2-13.2h13.2V80zm6.6 0c0-7.3 5.9-13.2 13.2-13.2s13.2 5.9 13.2 13.2v33c0 7.3-5.9 13.2-13.2 13.2s-13.2-5.9-13.2-13.2V80z" fill="#E01E5A"/>
      <path d="M47 27c-7.3 0-13.2-5.9-13.2-13.2S39.7.6 47 .6s13.2 5.9 13.2 13.2V27H47zm0 6.7c7.3 0 13.2 5.9 13.2 13.2s-5.9 13.2-13.2 13.2H13.9C6.6 60.1.7 54.2.7 46.9s5.9-13.2 13.2-13.2H47z" fill="#36C5F0"/>
      <path d="M99.9 46.9c0-7.3 5.9-13.2 13.2-13.2s13.2 5.9 13.2 13.2-5.9 13.2-13.2 13.2H99.9V46.9zm-6.6 0c0 7.3-5.9 13.2-13.2 13.2s-13.2-5.9-13.2-13.2V13.8C66.9 6.5 72.8.6 80.1.6s13.2 5.9 13.2 13.2v33.1z" fill="#2EB67D"/>
      <path d="M80.1 99.8c7.3 0 13.2 5.9 13.2 13.2s-5.9 13.2-13.2 13.2-13.2-5.9-13.2-13.2V99.8h13.2zm0-6.6c-7.3 0-13.2-5.9-13.2-13.2s5.9-13.2 13.2-13.2h33.1c7.3 0 13.2 5.9 13.2 13.2s-5.9 13.2-13.2 13.2H80.1z" fill="#ECB22E"/>
    </svg>
  );
}

function GoogleIcon({ className }) {
  return (
    <svg className={className} viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
      <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" fill="#4285F4"/>
      <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853"/>
      <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" fill="#FBBC05"/>
      <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335"/>
    </svg>
  );
}
