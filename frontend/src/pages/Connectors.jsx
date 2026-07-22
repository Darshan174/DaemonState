import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import imgGmail from "@assets/gmail-icon.png";
import imgGDrive from "@assets/gdrive-icon.png";
import imgOpenAI from "@assets/openai-icon.png";
import imgOpenCode from "@assets/opencode-icon.png";
import {
  useConnectGitHub,
  useImportAISessionById,
  useIngestAISession,
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
  coming_soon: "bg-slate-100 dark:bg-black text-slate-600 dark:text-neutral-400",
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
  const saveSlackOAuthMut = useSaveSlackOAuthSettings();
  const connectGitHubMut = useConnectGitHub();
  const syncMut = useSyncConnector();
  const disconnectMut = useDisconnectConnector();
  const [actionError, setActionError] = useState(null);
  const [actionNotice, setActionNotice] = useState(null);
  const [oauthFlow, setOauthFlow] = useState(null);
  const [genericOAuthPending, setGenericOAuthPending] = useState(() => new Set());
  const refetchRef = useRef(query.refetch);
  useEffect(() => { refetchRef.current = query.refetch; }, [query.refetch]);
  const [slackConnectIntent, setSlackConnectIntent] = useState(null);
  const [slackSetupOpen, setSlackSetupOpen] = useState(false);
  const [slackClientId, setSlackClientId] = useState("");
  const [slackClientSecret, setSlackClientSecret] = useState("");
  const [slackRedirectUri, setSlackRedirectUri] = useState(
    () => `${window.location.origin}/api/connectors/slack/callback`,
  );
  const [githubFormOpen, setGitHubFormOpen] = useState(false);
  const [githubToken, setGitHubToken] = useState("");
  const [githubRepositories, setGitHubRepositories] = useState("");
  const [aiSessionFormOpenFor, setAISessionFormOpenFor] = useState(null);
  const [aiSessionImportMode, setAISessionImportMode] = useState("local");
  const [aiSessionId, setAISessionId] = useState("");
  const [aiSessionContent, setAISessionContent] = useState("");
  const [connectorFilter, setConnectorFilter] = useState("all");
  const ingestAISessionMut = useIngestAISession();
  const importAISessionByIdMut = useImportAISessionById();

  const workspaceId = useMemo(
    () => resolveWorkspaceId(workspaces.data, selectedId),
    [workspaces.data, selectedId],
  );

  const list = data ?? [];
  const connectorCounts = useMemo(() => ({
    connected: list.filter((item) => item.status === "connected" || item.status === "error").length,
    available: list.filter((item) => item.availability === "available" && item.status === "disconnected" && !["codex", "claude", "opencode"].includes(item.type)).length,
    sessions: list.filter((item) => ["codex", "claude", "opencode"].includes(item.type)).length,
    comingSoon: list.filter((item) => item.availability === "coming_soon").length,
  }), [list]);
  const visibleConnectors = useMemo(() => {
    const matches = list.filter((item) => {
      if (connectorFilter === "connected") return item.status === "connected" || item.status === "error";
      if (connectorFilter === "available") return item.availability === "available" && item.status === "disconnected" && !["codex", "claude", "opencode"].includes(item.type);
      if (connectorFilter === "sessions") return ["codex", "claude", "opencode"].includes(item.type);
      if (connectorFilter === "coming-soon") return item.availability === "coming_soon";
      return true;
    });
    const rank = (item) => {
      if (item.status === "connected" || item.status === "error") return 0;
      if (["codex", "claude", "opencode"].includes(item.type)) return 2;
      if (item.availability === "coming_soon") return 3;
      return 1;
    };
    return [...matches].sort((a, b) => rank(a) - rank(b));
  }, [connectorFilter, list]);
  const slackConnector = list.find((item) => item.type === "slack") ?? null;
  useEffect(() => {
    if (slackConnector?.redirectUri) {
      setSlackRedirectUri(slackConnector.redirectUri);
    }
  }, [slackConnector?.redirectUri]);

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
      const result = await refetchRef.current();
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

      // Close popup and finish as soon as backend reports connected,
      // regardless of whether this was an initial connect or reconnect.
      if (!popupClosed && nextSlack?.status === "connected") {
        oauthFlow.popup.close?.();
        finishOAuthFlow(nextSlack, oauthFlow.startedStatus);
        return;
      }

      if (popupClosed) {
        finishOAuthFlow(nextSlack, oauthFlow.startedStatus);
      }
    };

    const onMsg = (e) => {
      if (e.data === "oauth-complete") {
        void tick();
      }
    };
    window.addEventListener("message", onMsg);

    const timer = window.setInterval(() => {
      void tick();
    }, OAUTH_POLL_INTERVAL_MS);

    // Safety net: auto-clear oauthFlow after 5 minutes
    const safetyTimeout = window.setTimeout(() => {
      if (!cancelled) {
        setOauthFlow(null);
        setActionError("Slack OAuth timed out. If the popup is still open, close it and try again.");
      }
    }, 300000);

    return () => {
      cancelled = true;
      window.clearInterval(timer);
      window.clearTimeout(safetyTimeout);
      window.removeEventListener("message", onMsg);
    };
  }, [isMock, oauthFlow]);

  const startGenericOAuth = (installHref, connectorType) => {
    setActionError(null);
    setActionNotice(null);
    const popup = window.open(installHref, `ce-${connectorType}-oauth`, "popup=yes,width=640,height=820");
    if (!popup) {
      window.location.assign(installHref);
      return;
    }
    popup.focus?.();
    setGenericOAuthPending((prev) => new Set([...prev, connectorType]));
    const finish = async () => {
      setGenericOAuthPending((prev) => {
        const next = new Set(prev);
        next.delete(connectorType);
        return next;
      });
      await query.refetch();
    };
    const timer = window.setInterval(async () => {
      if (popup.closed) {
        window.clearInterval(timer);
        await finish();
      }
    }, OAUTH_POLL_INTERVAL_MS);
    const onMsg = async (e) => {
      if (e.data === "oauth-complete") {
        window.removeEventListener("message", onMsg);
        window.clearInterval(timer);
        popup.close?.();
        await finish();
      }
    };
    window.addEventListener("message", onMsg);
    setActionNotice(`${connectorType.replace(/_/g, " ")} OAuth opened in a new window. Finish there to connect.`);
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
        <StatusView
          query={{ data, ...query }}
          empty="No connectors configured."
          loading="Loading connectors…"
          loadingStages={["Opening the connector catalog", "Checking connection health", "Preparing available integrations"]}
        />
      </div>
    );
  }

  return (
    <div className="app-page relative z-10">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="eyebrow">Data plane</p>
          <div className="flex items-center gap-3">
            <h2 className="mt-2 text-3xl font-black tracking-tight text-slate-950 dark:text-white">Connectors</h2>
            {isMock && <MockBadge />}
          </div>
          <p className="mt-2 max-w-2xl text-sm leading-relaxed text-slate-500 dark:text-neutral-400">
            Bring project evidence into the workspace. Availability and connection state come directly from the backend catalog.
          </p>
        </div>
      </div>

      <div className="panel overflow-hidden">
        <div className="grid grid-cols-2 sm:grid-cols-4">
          <ConnectorStat label="Connected" value={connectorCounts.connected} />
          <ConnectorStat label="Ready to connect" value={connectorCounts.available} bordered />
          <ConnectorStat label="Agent imports" value={connectorCounts.sessions} bordered />
          <ConnectorStat label="Coming soon" value={connectorCounts.comingSoon} bordered />
        </div>
        <div className="flex gap-2 overflow-x-auto border-t border-[#e1e1d8] px-3 py-3 no-scrollbar dark:border-[#292925]" aria-label="Filter connectors">
          {[
            ["all", "All", list.length],
            ["connected", "Connected", connectorCounts.connected],
            ["available", "Available", connectorCounts.available],
            ["sessions", "Agent sessions", connectorCounts.sessions],
            ["coming-soon", "Coming soon", connectorCounts.comingSoon],
          ].map(([value, label, count]) => (
            <button
              key={value}
              type="button"
              onClick={() => setConnectorFilter(value)}
              aria-pressed={connectorFilter === value}
              className={`whitespace-nowrap rounded-md px-3 py-1.5 text-xs font-semibold transition-colors ${connectorFilter === value ? "bg-[#171713] text-white dark:bg-[#d9ff68] dark:text-[#171713]" : "text-[#68685f] hover:bg-[#f2f2eb] dark:text-[#a2a298] dark:hover:bg-[#1f1f1b]"}`}
            >
              {label} <span className="ml-1 tabular-nums opacity-65">{count}</span>
            </button>
          ))}
        </div>
      </div>

      {actionError && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-4 dark:border-red-800/50 dark:bg-red-900/30">
          <p className="text-sm text-red-700 dark:text-red-400">{actionError}</p>
        </div>
      )}
      {actionNotice && (
        <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-4 dark:border-emerald-800/50 dark:bg-emerald-900/30">
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
          redirectUri={slackConnector?.redirectUri ?? slackRedirectUri}
          onCancel={() => setSlackConnectIntent(null)}
          onContinue={() => startSlackOAuth(slackConnectIntent.installHref, slackConnectIntent.currentStatus)}
        />
      )}

      {list.length === 0 ? (
        <StatusView query={{ data: list, isLoading: false, isError: false }} empty="No connectors configured." />
      ) : visibleConnectors.length === 0 ? (
        <div className="panel px-6 py-14 text-center">
          <p className="text-sm font-semibold text-[#4f4f48] dark:text-[#d0d0c7]">No connectors in this state.</p>
          <button type="button" onClick={() => setConnectorFilter("all")} className="mt-2 text-xs font-semibold text-brand-700 dark:text-brand-400">Show all connectors</button>
        </div>
      ) : (
        <div className="grid items-start gap-4 xl:grid-cols-2">
          {visibleConnectors.map((connector) => (
            <ConnectorCard
              key={connector.type}
              connector={connector}
              isDemo={isMock}
              oauthPending={connector.type === "slack" ? !!oauthFlow : genericOAuthPending.has(connector.type)}
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
              githubFormOpen={connector.type === "github" ? githubFormOpen : false}
              githubToken={githubToken}
              githubRepositories={githubRepositories}
              onChangeGitHubToken={setGitHubToken}
              onChangeGitHubRepositories={setGitHubRepositories}
              onToggleGitHubForm={() => setGitHubFormOpen((current) => !current)}
              connectGitHubMut={connectGitHubMut}
              aiSessionFormOpen={["codex", "claude", "opencode"].includes(connector.type) ? aiSessionFormOpenFor === connector.type : false}
              aiSessionId={aiSessionId}
              aiSessionContent={aiSessionContent}
              aiSessionImportMode={aiSessionImportMode}
              onChangeAISessionImportMode={setAISessionImportMode}
              onChangeAISessionId={setAISessionId}
              onChangeAISessionContent={setAISessionContent}
              onToggleAISessionForm={() => {
                setAISessionFormOpenFor((f) => f === connector.type ? null : connector.type);
                setAISessionImportMode("local");
                setAISessionId("");
                setAISessionContent("");
              }}
              ingestAISessionMut={ingestAISessionMut}
              importAISessionByIdMut={importAISessionByIdMut}
              syncMut={syncMut}
              disconnectMut={disconnectMut}
              onActionError={setActionError}
              onActionNotice={setActionNotice}
              onSyncJobSettled={handleSyncJobSettled}
              onRefreshConnectors={query.refetch}
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
    <div className="panel-subtle px-4 py-4">
      <p className="text-sm font-semibold text-gray-800 dark:text-gray-300">{title}</p>
      <p className="mt-2 text-xs text-gray-600 dark:text-gray-400">{description}</p>
      <Link to={to} className="mt-4 inline-flex text-xs font-medium text-brand-700 dark:text-brand-400 hover:text-brand-800 dark:text-brand-300">
        {action}
      </Link>
    </div>
  );
}

function ConnectorStat({ label, value, bordered = false }) {
  return (
    <div className={`${bordered ? "border-l border-[#e1e1d8] dark:border-[#292925]" : ""} px-4 py-3.5`}>
      <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-[#8a8a80] dark:text-[#77776e]">{label}</p>
      <p className="mt-1 text-xl font-semibold tabular-nums text-[#171713] dark:text-[#f4f4ec]">{value}</p>
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
  githubFormOpen,
  githubToken,
  githubRepositories,
  onChangeGitHubToken,
  onChangeGitHubRepositories,
  onToggleGitHubForm,
  connectGitHubMut,
  aiSessionFormOpen,
  aiSessionId,
  aiSessionContent,
  aiSessionImportMode,
  onChangeAISessionImportMode,
  onChangeAISessionId,
  onChangeAISessionContent,
  onToggleAISessionForm,
  ingestAISessionMut,
  importAISessionByIdMut,
  syncMut,
  disconnectMut,
  onActionError,
  onActionNotice,
  onSyncJobSettled,
  onRefreshConnectors,
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
    provider,
    providerLabel,
    providerNote,
    isConfigured = true,
    managedConnectAvailable = false,
    managedInstallUrl = null,
    redirectUri = null,
  } = connector;

  const isSlack = type === "slack";
  const isGitHub = type === "github";
  const isGDrive = type === "gdrive";
  const isGmail = type === "gmail";
  const isGoogleOAuth = isGDrive || isGmail;
  const isAISession = type === "codex" || type === "claude" || type === "opencode";
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
  const hasOperationalConnection = status === "connected" || status === "error";
  const hasPersistedConnectionRecord = !!connectorId && status !== "coming_soon";
  const canSync = !isDemo && !oauthPending && !!connectorId && hasOperationalConnection;
  const canDisconnect = !isDemo && !oauthPending && hasPersistedConnectionRecord;
  const installHref = workspaceId
    ? isSlack
      ? managedConnectAvailable && managedInstallUrl
        ? `${managedInstallUrl}?workspace_id=${workspaceId}`
        : isConfigured
          ? `/api/connectors/slack/install?workspace_id=${workspaceId}`
          : null
      : isGoogleOAuth && !isConfigured
        ? null
        : `/api/connectors/${type}/install?workspace_id=${workspaceId}`
    : null;
  const slackConnectMode = managedConnectAvailable ? "managed" : "self_hosted";
  const processedDocuments = processing?.processedDocuments ?? totalProcessedCount;
  const pendingDocuments = processing?.unprocessedDocuments ?? Math.max(Number(itemsSynced || 0) - processedDocuments, 0);
  const syncStatusQuery = useConnectorSyncStatus(connectorId, {
    enabled: !isDemo && !!connectorId && hasOperationalConnection,
  });
  const syncJobsQuery = useConnectorSyncJobs(connectorId, {
    enabled: !isDemo && !!connectorId && hasOperationalConnection,
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
          onRefreshConnectors?.();
          onActionNotice("Slack OAuth settings saved. You can connect Slack now.");
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

  const handleSlackConnectAction = () => {
    if (installHref) {
      onStartOAuth(installHref, status, slackConnectMode);
      return;
    }
    if (!workspaceId) {
      onActionNotice("Select a workspace before connecting Slack.");
      return;
    }
    if (!isConfigured) {
      onActionNotice("Slack OAuth is not configured for this server. Use advanced self-hosted setup to add your Slack app credentials.");
      return;
    }
    onActionError("Slack install URL is unavailable. Refresh connector status and try again.");
  };

  const handleAISessionIngest = (event) => {
    event.preventDefault();
    onActionError(null);
    onActionNotice(null);
    const sessionId = aiSessionId.trim();
    const onSuccess = (data) => {
      onChangeAISessionContent("");
      onChangeAISessionId("");
      onToggleAISessionForm();
      const docs = data?.ingest?.documents_persisted ?? 0;
      const updated = data?.ingest?.documents_updated ?? 0;
      const comps = data?.extract?.components_created ?? 0;
      const modeSuffix = data?.resolved_from ? " from local history" : "";
      onActionNotice(
        docs > 0
          ? `${name} session ingested${modeSuffix}. ${comps > 0 ? `${comps} graph component${comps === 1 ? "" : "s"} extracted.` : "Run a sync to extract graph facts."}`
          : updated > 0
            ? `${name} session updated${modeSuffix}. ${comps > 0 ? `${comps} graph component${comps === 1 ? "" : "s"} extracted.` : ""}`
            : `${name} session processed.`,
      );
    };

    if (aiSessionImportMode === "local") {
      importAISessionByIdMut.mutate(
        { connectorType: type, sessionId },
        {
          onError: (err) => onActionError(formatActionError(err) || `Failed to import ${name} session from local history.`),
          onSuccess,
        },
      );
      return;
    }

    ingestAISessionMut.mutate(
      { connectorType: type, sessionId: sessionId || `session-${Date.now()}`, content: aiSessionContent },
      {
        onError: (err) => onActionError(formatActionError(err) || `Failed to ingest ${name} session.`),
        onSuccess,
      },
    );
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
    <div className={`panel rounded-xl [border-radius:0.5rem] flex flex-col gap-4 p-5 transition-colors hover:border-[#8a8a80] dark:hover:border-[#57574f] ${availability === "coming_soon" ? "opacity-70" : ""}`}>
      <div className="flex items-center gap-3">
        <ConnectorIconBadge type={type} color={color} name={name} />
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
          className={`rounded-md px-2.5 py-0.5 text-[11px] font-bold ${STATUS_PILL[status]}`}
        >
          {STATUS_LABEL[status]}
        </span>
      </div>

      {(hasOperationalConnection || Number(itemsSynced || 0) > 0) ? <div className="panel-subtle p-3">
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
        {syncQueuedAt && (
          <div className="mt-2 inline-flex items-center gap-2 rounded-full bg-blue-50 dark:bg-blue-900/30 px-2.5 py-1 text-[11px] text-blue-700 dark:text-blue-400">
            <span className="inline-block h-1.5 w-1.5 rounded-full bg-blue-500" />
            Sync queued {syncQueuedAt}
          </div>
        )}
        {latestSyncJob && (
          <div className="mt-3 rounded-lg border border-slate-200/80 bg-white/[0.84] px-3 py-3 dark:border-white/[0.08] dark:bg-white/[0.035]">
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
            <p className="mt-2 text-[11px] text-gray-500">{formatLatestSyncJobTime(latestSyncJob)}</p>
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
          <div className="mt-3 rounded-lg border border-slate-200/80 bg-white/[0.84] px-3 py-3 dark:border-white/[0.08] dark:bg-white/[0.035]">
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
        {isGitHub && status !== "disconnected" && <GitHubCapabilityPanel repositories={connector.repositories ?? null} />}
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
        {redirectUri && status === "disconnected" && (isGoogleOAuth || githubFormOpen) && (
          <div className="mt-2 rounded-md bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800/50 px-2.5 py-2">
            <p className="text-[10px] font-medium text-blue-700 dark:text-blue-400 mb-0.5">
              Register this redirect URI in {isGoogleOAuth ? "Google Cloud Console" : `your ${name} app`}:
            </p>
            <div className="flex items-center gap-1.5">
              <code className="flex-1 text-[10px] text-blue-800 dark:text-blue-300 break-all font-mono">{redirectUri}</code>
              <button
                type="button"
                onClick={() => navigator.clipboard.writeText(redirectUri)}
                className="shrink-0 text-[10px] px-1.5 py-0.5 rounded bg-blue-100 dark:bg-blue-800/40 text-blue-700 dark:text-blue-300 hover:bg-blue-200 dark:hover:bg-blue-700/40"
              >
                Copy
              </button>
            </div>
          </div>
        )}
        {status === "error" && (
          <p className="text-[11px] text-red-600 dark:text-red-400 mt-2">
            Reconnect to refresh credentials, then run another sync.
          </p>
        )}
        {status === "connected" && itemsSynced > 0 && (
          <div className="mt-2 flex items-center gap-2">
            <p className="text-[11px] text-emerald-700 dark:text-emerald-400">
              {Number(itemsSynced).toLocaleString()} document{Number(itemsSynced) === 1 ? "" : "s"} stored
            </p>
            <span className="text-gray-300 dark:text-gray-600">·</span>
            <Link to="/app/sources" className="text-[11px] font-medium text-brand-600 dark:text-brand-400 hover:underline">
              View sources
            </Link>
          </div>
        )}
        {status === "connected" && itemsSynced === 0 && processedDocuments === 0 && !syncQueuedAt && (
          <p className="text-[11px] text-gray-400 dark:text-gray-500 mt-2">
            Ready — run a sync to start pulling data.
          </p>
        )}
      </div> : (
        <div className="border-y border-[#e1e1d8] py-3 text-xs leading-relaxed text-[#77776e] dark:border-[#292925] dark:text-[#929289]">
          {availability === "coming_soon"
            ? "Listed for product visibility; setup and sync are not available yet."
            : isAISession
              ? "Import a local agent session by ID or paste exported session content."
              : "Connect this provider to begin preserving raw source documents."}
        </div>
      )}

      {isGitHub && githubFormOpen && (
        <form onSubmit={handleGitHubConnect} className="panel-subtle space-y-3 p-3">
          {/* Setup guide */}
          <div className="rounded-lg border border-sky-200 dark:border-sky-500/20 bg-sky-50 dark:bg-sky-500/10 px-3 py-2.5 space-y-1.5">
            <p className="text-[11px] font-bold uppercase tracking-wide text-sky-800 dark:text-sky-200">
              How to get a GitHub token
            </p>
            <ol className="text-xs text-sky-900 dark:text-sky-100 space-y-1 list-decimal list-inside leading-relaxed">
              <li>
                Go to{" "}
                <a
                  href="https://github.com/settings/tokens/new"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="font-semibold underline decoration-sky-400 hover:text-sky-700 dark:hover:text-sky-300"
                >
                  github.com/settings/tokens/new
                </a>
              </li>
              <li>Under <strong>Note</strong>, enter a name like <em>Context Engine</em></li>
              <li>
                Select scope{" "}
                <span className="rounded bg-sky-100 dark:bg-sky-900/50 px-1.5 py-0.5 font-mono font-bold">repo</span>
                {" "}for private repos, or{" "}
                <span className="rounded bg-sky-100 dark:bg-sky-900/50 px-1.5 py-0.5 font-mono font-bold">public_repo</span>
                {" "}for public repos only
              </li>
              <li>Click <strong>Generate token</strong> and copy it below</li>
            </ol>
            <p className="text-[11px] text-sky-700 dark:text-sky-300 mt-1">
              Fine-grained tokens work too — grant <strong>Issues</strong> and <strong>Pull requests</strong> read access on the target repos.
            </p>
          </div>

          <div>
            <label htmlFor="github-token" className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
              Personal Access Token
            </label>
            <input
              id="github-token"
              type="password"
              value={githubToken}
              onChange={(event) => onChangeGitHubToken(event.target.value)}
              placeholder="ghp_xxxxxxxxxxxxxxxxxxxx"
              className="w-full rounded-lg border border-gray-200 dark:border-gray-800/50 bg-white dark:bg-black px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500/40 font-mono"
            />
          </div>
          <div>
            <label htmlFor="github-repositories" className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
              Repositories to sync
            </label>
            <textarea
              id="github-repositories"
              value={githubRepositories}
              onChange={(event) => onChangeGitHubRepositories(event.target.value)}
              placeholder={"your-org/repo-name\nyour-org/another-repo"}
              rows={3}
              className="w-full rounded-lg border border-gray-200 dark:border-gray-800/50 bg-white dark:bg-black px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500/40 font-mono"
            />
            <p className="mt-1 text-[11px] text-gray-500 dark:text-gray-400">
              One <code className="bg-gray-100 dark:bg-gray-800 px-1 rounded">owner/repo</code> per line. Example: <code className="bg-gray-100 dark:bg-gray-800 px-1 rounded">acme/backend</code>
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
              {connectGitHubMut.isPending ? "Saving…" : "Save & connect"}
            </button>
            <button
              type="button"
              onClick={onToggleGitHubForm}
              className="px-3 py-1.5 text-xs font-medium rounded-lg border border-gray-200 dark:border-gray-800/50 text-gray-700 dark:text-gray-400 hover:bg-white dark:bg-black"
            >
              Cancel
            </button>
          </div>
        </form>
      )}

      {isAISession && aiSessionFormOpen && (
        <form onSubmit={handleAISessionIngest} className="panel-subtle space-y-3 p-3">
          <div>
            <p className="text-xs font-semibold text-gray-700 dark:text-gray-300 mb-2">
              Import a {name} session
            </p>
            <div className="inline-flex rounded-lg border border-gray-200 dark:border-gray-800/50 bg-white dark:bg-black p-0.5 mb-3">
              {[
                ["local", "Local history"],
                ["paste", "Paste content"],
              ].map(([mode, label]) => (
                <button
                  key={mode}
                  type="button"
                  onClick={() => onChangeAISessionImportMode(mode)}
                  className={`px-3 py-1.5 text-[11px] font-medium rounded-md ${
                    aiSessionImportMode === mode
                      ? "bg-gray-900 text-white dark:bg-white dark:text-black"
                      : "text-gray-500 dark:text-gray-400 hover:text-gray-800 dark:hover:text-gray-200"
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
            <label htmlFor={`${type}-session-id`} className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
              Session ID {aiSessionImportMode === "paste" && <span className="text-gray-400">(optional — used for deduplication)</span>}
            </label>
            <input
              id={`${type}-session-id`}
              type="text"
              value={aiSessionId}
              onChange={(e) => onChangeAISessionId(e.target.value)}
              placeholder={aiSessionImportMode === "local" ? (type === "opencode" ? "ses_..." : "019eff6d-f344-...") : `my-${type}-session-1`}
              className="w-full rounded-lg border border-gray-200 dark:border-gray-800/50 bg-white dark:bg-black px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500/40"
            />
            {aiSessionImportMode === "local" && (
              <p className="mt-1 text-[11px] text-gray-400">
                Reads from local {name} history on this machine. No website scraping.
              </p>
            )}
          </div>
          {aiSessionImportMode === "paste" && (
            <div>
              <label htmlFor={`${type}-session-content`} className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
                Session content
              </label>
              <textarea
                id={`${type}-session-content`}
                value={aiSessionContent}
                onChange={(e) => onChangeAISessionContent(e.target.value)}
                placeholder={"Paste your conversation export here. JSON (messages array), markdown (Human:/Assistant: format), or plain text are all supported."}
                rows={6}
                className="w-full rounded-lg border border-gray-200 dark:border-gray-800/50 bg-white dark:bg-black px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500/40 font-mono text-xs"
              />
              <p className="mt-1 text-[11px] text-gray-400">
                Supports OpenAI JSON export, Claude markdown, or raw conversation text.
              </p>
            </div>
          )}
          <div className="flex gap-2">
            <button
              type="submit"
              disabled={
                ingestAISessionMut.isPending ||
                importAISessionByIdMut.isPending ||
                (aiSessionImportMode === "local" ? !aiSessionId.trim() : !aiSessionContent.trim())
              }
              className="px-3 py-1.5 text-xs font-medium rounded-lg bg-brand-600 text-white hover:bg-brand-700 disabled:bg-gray-300 disabled:cursor-not-allowed"
            >
              {ingestAISessionMut.isPending || importAISessionByIdMut.isPending ? "Importing..." : "Import session"}
            </button>
            <button
              type="button"
              onClick={onToggleAISessionForm}
              className="px-3 py-1.5 text-xs font-medium rounded-lg border border-gray-200 dark:border-gray-800/50 text-gray-700 dark:text-gray-400 hover:bg-white dark:bg-black"
            >
              Cancel
            </button>
          </div>
        </form>
      )}

      <div className="flex flex-wrap gap-2 mt-auto">
        {availability === "coming_soon" || status === "coming_soon" ? (
          <button
            type="button"
            disabled
            className="px-3 py-1.5 text-xs font-medium rounded-lg border border-gray-200 dark:border-gray-800/50 text-gray-400 cursor-not-allowed"
          >
            Coming soon
          </button>
        ) : type === "local" && status === "disconnected" ? (
          <Link
            to="/app/sources"
            className="px-3 py-1.5 text-xs font-medium rounded-lg bg-brand-600 text-white hover:bg-brand-700 transition-colors"
          >
            Upload files
          </Link>
        ) : type === "ai_context" && status === "disconnected" ? (
          <span className="inline-flex items-center rounded-lg bg-slate-100 dark:bg-black px-3 py-1.5 text-xs font-medium text-slate-600 dark:text-neutral-400 border border-slate-200 dark:border-neutral-800/50">
            Use Codex, Claude, or OpenCode import
          </span>
        ) : isSlack && canConnect ? (
          <button
            type="button"
            onClick={handleSlackConnectAction}
            className="inline-flex items-center gap-2 rounded-full bg-white border border-gray-200 px-4 py-2 text-sm font-medium text-gray-900 hover:bg-gray-50 shadow-sm transition-colors dark:bg-black dark:border-gray-700 dark:text-white dark:hover:bg-black"
          >
            <SlackLogoIcon className="w-5 h-5" />
            Connect to Slack
          </button>
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
        ) : isSlack && canReconnect ? (
          <button
            type="button"
            onClick={handleSlackConnectAction}
            className="px-3 py-1.5 text-xs font-medium rounded-lg border border-gray-200 dark:border-gray-800/50 text-gray-700 dark:text-gray-400 hover:bg-gray-50 dark:bg-gray-900/30 transition-colors"
          >
            Reconnect Slack
          </button>
        ) : isGoogleOAuth && canConnect && installHref ? (
          <button
            type="button"
            disabled={isDemo || !workspaceId}
            onClick={handleGoogleOAuth}
            className="inline-flex items-center gap-2 rounded-full bg-white border border-gray-200 px-4 py-2 text-sm font-medium text-gray-900 hover:bg-gray-50 shadow-sm transition-colors dark:bg-black dark:border-gray-700 dark:text-white dark:hover:bg-black"
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
        ) : isAISession ? (
          <button
            type="button"
            disabled={isDemo || !workspaceId}
            onClick={onToggleAISessionForm}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-brand-600 text-white hover:bg-brand-700 disabled:bg-gray-300 disabled:cursor-not-allowed"
          >
            <svg className="w-3.5 h-3.5" viewBox="0 0 16 16" fill="currentColor">
              <path d="M8 1a.5.5 0 0 1 .5.5v6h6a.5.5 0 0 1 0 1h-6v6a.5.5 0 0 1-1 0v-6h-6a.5.5 0 0 1 0-1h6v-6A.5.5 0 0 1 8 1z"/>
            </svg>
            Import session
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
                ? "Connecting..."
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

        {hasOperationalConnection && (
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
        )}

        {hasPersistedConnectionRecord && (
          <button
            type="button"
            disabled={!canDisconnect || disconnectMut.isPending}
            onClick={handleDisconnect}
            className="px-3 py-1.5 text-xs font-medium rounded-lg border border-red-200 dark:border-red-800/50 text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/30 disabled:text-gray-400 disabled:border-gray-200 dark:disabled:border-gray-800/50 disabled:cursor-not-allowed transition-colors"
          >
            {disconnectMut.isPending && disconnectMut.variables === connectorId
              ? "Disconnecting..."
              : "Disconnect"}
          </button>
        )}
      </div>
    </div>
  );
}

function formatCompletedSyncNotice(connectorName, metadata) {
  if (!metadata || typeof metadata !== "object") {
    return `${connectorName} sync completed.`;
  }

  const counts = getSyncDocumentCounts(metadata);
  const syncMode = metadata.sync_mode ? ` (${metadata.sync_mode})` : "";
  const skippedSummary = formatSkippedSummary(counts);
  const noNewWork = counts.noNewDocuments
    ? " No new documents since last sync; all fetched items were already imported or skipped."
    : "";

  return `${connectorName} sync completed: fetched ${counts.fetched}, stored ${counts.persisted} new, processed ${counts.processed} new${skippedSummary}${syncMode}.${noNewWork}`;
}

function summarizeSyncJob(metadata) {
  if (!metadata || typeof metadata !== "object") {
    return "Sync completed.";
  }
  const counts = getSyncDocumentCounts(metadata);
  const skippedSummary = formatSkippedSummary(counts);
  const suffix = counts.noNewDocuments
    ? ". No new documents since last sync."
    : "";
  return `Fetched ${counts.fetched}, stored ${counts.persisted} new, processed ${counts.processed} new${skippedSummary}${suffix}`;
}

function getSyncDocumentCounts(metadata) {
  const fetched = toSyncCount(metadata.documents_fetched);
  const persisted = toSyncCount(metadata.documents_persisted);
  const processed = toSyncCount(metadata.documents_processed);
  const fallbackSkipped = Math.max(fetched - persisted, 0);
  const skipped = toSyncCount(metadata.documents_skipped, fallbackSkipped);
  const errors = Array.isArray(metadata.errors)
    ? metadata.errors.length
    : toSyncCount(metadata.errors_count);

  return {
    fetched,
    persisted,
    processed,
    skipped,
    duplicatesSkipped: toSyncCount(metadata.duplicates_skipped),
    emptySkipped: toSyncCount(metadata.empty_skipped),
    filteredSkipped: toSyncCount(metadata.filtered_skipped),
    noNewDocuments: fetched > 0 && persisted === 0 && processed === 0 && errors === 0,
  };
}

function formatSkippedSummary(counts) {
  if (counts.skipped <= 0) return "";

  const parts = [];
  if (counts.duplicatesSkipped > 0) {
    parts.push(`${counts.duplicatesSkipped} already imported`);
  }
  if (counts.emptySkipped > 0) {
    parts.push(`${counts.emptySkipped} empty`);
  }
  if (counts.filteredSkipped > 0) {
    parts.push(`${counts.filteredSkipped} filtered`);
  }
  const detail = parts.length ? ` (${parts.join(", ")})` : "";
  return `, skipped ${counts.skipped}${detail}`;
}

function toSyncCount(value, fallback = 0) {
  const number = Number(value ?? fallback);
  return Number.isFinite(number) ? Math.max(number, 0) : fallback;
}

function formatDateTime(value) {
  if (!value) return "—";
  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}

function formatLatestSyncJobTime(job) {
  if (!job) return "No sync job yet.";
  if (job.status === "completed" && job.completedAt) return `Completed ${formatDateTime(job.completedAt)}`;
  if (job.status === "failed" && job.completedAt) return `Failed ${formatDateTime(job.completedAt)}`;
  if (job.startedAt) return `Started ${formatDateTime(job.startedAt)}`;
  if (job.createdAt) return `Queued ${formatDateTime(job.createdAt)}`;
  return "Sync job pending.";
}

function formatActionError(error) {
  if (!error) return null;
  if (Array.isArray(error.detail)) {
    return error.detail.map((item) => item.msg).join(". ");
  }
  return error.message || null;
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
              className="rounded-full bg-white dark:bg-black px-2 py-0.5 text-[10px] font-medium text-gray-700 dark:text-gray-400 border border-gray-200 dark:border-gray-800/50"
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
  if (!isConfigured && !managedConnectAvailable) {
    return (
      <p className="text-[11px] text-gray-500 mt-2">
        Use advanced setup to provide your own Slack app credentials.
      </p>
    );
  }
  return null;
}

function SlackConnectModal({ mode, redirectUri, onCancel, onContinue }) {
  const isManaged = mode === "managed";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 px-4">
      <div className="w-full max-w-lg rounded-2xl border border-gray-200 dark:border-gray-800/60 bg-white dark:bg-black p-6 shadow-2xl">
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
            <p className="font-semibold text-gray-900 dark:text-gray-100">Read-only access</p>
            <p className="mt-1.5 leading-relaxed text-sm">
              Context Engine only reads channel history. No messages are posted or modified. Revoke access anytime from your Slack workspace settings.
            </p>
            <div className="mt-3 flex flex-wrap gap-1.5">
              {["channels:history", "channels:join", "channels:read", "groups:history", "groups:read", "users:read", "team:read"].map((scope) => (
                <span key={scope} className="inline-flex items-center rounded-md bg-gray-100 dark:bg-gray-800 px-2 py-1 text-[11px] font-medium text-gray-600 dark:text-gray-400">
                  {scope}
                </span>
              ))}
            </div>
          </div>
          <div className="border-t border-gray-200 dark:border-gray-800/60" />
          {!isManaged && redirectUri && (
            <>
              <div>
                <p className="font-semibold text-gray-900 dark:text-gray-100">Slack redirect URL must match exactly</p>
                <p className="mt-1.5 leading-relaxed text-sm">
                  In Slack app settings, open OAuth & Permissions and add this Redirect URL before continuing:
                </p>
                <code className="mt-2 block rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-[11px] font-mono text-gray-800 break-all dark:border-gray-800 dark:bg-black dark:text-gray-200">
                  {redirectUri}
                </code>
              </div>
              <div className="border-t border-gray-200 dark:border-gray-800/60" />
            </>
          )}
          <div>
            <p className="font-semibold text-gray-900 dark:text-gray-100">You're in control</p>
            <p className="mt-1.5 leading-relaxed text-sm">
              Disconnect the workspace from Context Engine at any time from this page.
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
            className="mt-1 w-full rounded-lg border border-amber-200 bg-white px-3 py-2 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-amber-500/40 dark:border-amber-800/50 dark:bg-black dark:text-gray-100"
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
            className="mt-1 w-full rounded-lg border border-amber-200 bg-white px-3 py-2 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-amber-500/40 dark:border-amber-800/50 dark:bg-black dark:text-gray-100"
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
            className="mt-1 w-full rounded-lg border border-amber-200 bg-white px-3 py-2 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-amber-500/40 dark:border-amber-800/50 dark:bg-black dark:text-gray-100"
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
          className="px-3 py-1.5 text-xs font-medium rounded-lg border border-amber-200 bg-white text-amber-900 hover:bg-amber-100 dark:border-amber-800/50 dark:bg-black dark:text-amber-200"
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
    const subtext = connector.syncQueuedAt
      ? `Sync queued`
      : connector.itemsSynced > 0
        ? `${Number(connector.itemsSynced).toLocaleString()} document${Number(connector.itemsSynced) === 1 ? "" : "s"} stored`
        : `Last sync ${connector.lastSync} — run a sync to pull messages`;
    return (
      <div className="rounded-xl border border-emerald-200 dark:border-emerald-800/50 bg-emerald-50 dark:bg-emerald-900/30 px-4 py-3 flex items-center justify-between gap-4">
        <div className="flex items-center gap-3 min-w-0">
          <span className="inline-block h-2 w-2 shrink-0 rounded-full bg-emerald-500" />
          <div className="min-w-0">
            <span className="text-sm font-medium text-emerald-800 dark:text-emerald-300">
              {connector.teamName ? connector.teamName : "Slack"} connected
            </span>
            <span className="ml-2 text-xs text-emerald-600 dark:text-emerald-400">{subtext}</span>
          </div>
        </div>
        {!isDemo && !oauthPending && reconnectHref && (
          <a
            href={reconnectHref}
            onClick={(event) => {
              event.preventDefault();
              onStartOAuth(reconnectHref, connector.status, slackConnectMode);
            }}
            className="shrink-0 px-3 py-1.5 text-xs font-medium rounded-lg border border-emerald-300 dark:border-emerald-700 text-emerald-700 dark:text-emerald-300 hover:bg-white/70 transition-colors"
          >
            Refresh OAuth
          </a>
        )}
      </div>
    );
  }

  if (connector.status === "error") {
    return (
      <div className="rounded-xl border border-red-200 dark:border-red-800/50 bg-red-50 dark:bg-red-900/30 px-4 py-3 flex items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <span className="inline-block h-2 w-2 shrink-0 rounded-full bg-red-500" />
          <span className="text-sm font-medium text-red-800 dark:text-red-300">Slack needs attention — reconnect to refresh credentials</span>
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
    return (
      <div className="rounded-xl border border-amber-200 dark:border-amber-800/50 bg-amber-50 dark:bg-amber-900/30 px-4 py-3 flex items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <span className="inline-block h-2 w-2 shrink-0 rounded-full bg-amber-400" />
          <span className="text-sm font-medium text-amber-800 dark:text-amber-300">Slack not connected</span>
        </div>
        {!isDemo && !oauthPending && reconnectHref && (
          <button
            type="button"
            onClick={() => onStartOAuth(reconnectHref, connector.status, slackConnectMode)}
            className="shrink-0 inline-flex items-center gap-2 rounded-full bg-white border border-gray-200 px-4 py-2 text-sm font-medium text-gray-900 hover:bg-gray-50 shadow-sm transition-colors dark:bg-black dark:border-gray-700 dark:text-white dark:hover:bg-black"
          >
            <SlackLogoIcon className="w-4 h-4" />
            Connect to Slack
          </button>
        )}
      </div>
    );
  }

  return null;
}

function ConnectorIconBadge({ type, color, name }) {
  const icons = {
    slack: <SlackLogoIcon className="w-5 h-5" />,
    zoom: <ZoomIcon className="w-5 h-5" />,
    gdrive: <img src={imgGDrive} alt="Google Drive" className="w-8 h-8 object-contain" />,
    gmail: <img src={imgGmail} alt="Gmail" className="w-6 h-6 object-contain" />,
    github: <GitHubIcon className="w-5 h-5 text-white" />,
    codex: <img src={imgOpenAI} alt="OpenAI" className="w-7 h-7 object-contain" />,
    claude: <AnthropicIcon className="w-5 h-5 text-white" />,
    opencode: <img src={imgOpenCode} alt="OpenCode" className="w-8 h-8 object-contain" />,
  };
  const icon = icons[type];
  return (
    <span
      className="w-10 h-10 rounded-lg flex items-center justify-center shrink-0 overflow-hidden"
      style={{ backgroundColor: color, boxShadow: color === "#ffffff" ? "inset 0 0 0 1px #e5e7eb" : undefined }}
    >
      {icon ?? <span className="text-white text-sm font-bold">{name[0]}</span>}
    </span>
  );
}

function ZoomIcon({ className }) {
  return (
    <svg className={className} viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect width="32" height="32" rx="6" fill="#2D8CFF"/>
      <path d="M5 11.5C5 10.67 5.67 10 6.5 10H18.5C20.43 10 22 11.57 22 13.5V18.5C22 20.43 20.43 22 18.5 22H6.5C5.67 22 5 21.33 5 20.5V11.5Z" fill="white"/>
      <path d="M23 14L27 11.5V20.5L23 18V14Z" fill="white"/>
    </svg>
  );
}

function GoogleDriveIcon({ className }) {
  return (
    <svg className={className} viewBox="0 0 87.3 78" xmlns="http://www.w3.org/2000/svg">
      <path d="M6.6 66.85l3.85 6.65c.8 1.4 1.95 2.5 3.3 3.3L28 53H0c0 1.55.4 3.1 1.2 4.5z" fill="#0066DA"/>
      <path d="M43.65 25L29.35 0c-1.35.8-2.5 1.9-3.3 3.3L1.2 48.5A9 9 0 000 53h28z" fill="#00AC47"/>
      <path d="M73.55 76.8c1.35-.8 2.5-1.9 3.3-3.3l1.6-2.75L86.1 57.5A9 9 0 0087.3 53H59.3l5.95 11.45z" fill="#EA4335"/>
      <path d="M43.65 25L57.95 0H13.35c-1.35.8-2.5 1.9-3.3 3.3L13.35 8.5 28 25z" fill="#00832D"/>
      <path d="M59.3 53H87.3l-1.2-4.5-25-43.2c-.8-1.4-1.95-2.5-3.3-3.3L43.65 25l15.65 28z" fill="#2684FC"/>
      <path d="M28 53L13.75 76.8c1.35.8 2.9 1.2 4.5 1.2h50.8c1.6 0 3.15-.45 4.5-1.2L59.3 53z" fill="#FFBA00"/>
    </svg>
  );
}

function GmailIcon({ className }) {
  return (
    <svg className={className} viewBox="0 0 48 48" xmlns="http://www.w3.org/2000/svg">
      <path d="M4.5 39.5h7V24L2 17v19a2.5 2.5 0 002.5 2.5z" fill="#4285F4"/>
      <path d="M36.5 39.5h7A2.5 2.5 0 0046 37V17l-9.5 7v15.5z" fill="#34A853"/>
      <path d="M36.5 11.5v12.5L46 17v-3a2.5 2.5 0 00-4-2l-5.5 3.5-12 7.5-12-7.5L7 10a2.5 2.5 0 00-5 2v3l9.5 7V11.5L24 19.5l12.5-8z" fill="#EA4335"/>
      <path d="M11.5 24v15.5h13V25.5L11.5 24z" fill="#FBBC05"/>
      <path d="M36.5 24L24 25.5v14h12.5V24z" fill="#34A853"/>
      <path d="M2 17l9.5 7L24 19.5 36.5 24l9.5-7-12-7.5L24 11.5l-9.5 5.5L7 10 2 17z" fill="#EA4335"/>
    </svg>
  );
}

function GitHubIcon({ className }) {
  return (
    <svg className={className} viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" fill="currentColor">
      <path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0024 12c0-6.63-5.37-12-12-12z"/>
    </svg>
  );
}

function OpenAIIcon({ className }) {
  return (
    <svg className={className} viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" fill="currentColor">
      <path d="M22.282 9.821a5.985 5.985 0 0 0-.516-4.91 6.046 6.046 0 0 0-6.51-2.9A6.065 6.065 0 0 0 4.981 4.18a5.985 5.985 0 0 0-3.998 2.9 6.046 6.046 0 0 0 .743 7.097 5.98 5.98 0 0 0 .51 4.911 6.051 6.051 0 0 0 6.515 2.9A5.985 5.985 0 0 0 13.26 24a6.056 6.056 0 0 0 5.772-4.206 5.99 5.99 0 0 0 3.997-2.9 6.056 6.056 0 0 0-.747-7.073zM13.26 22.43a4.476 4.476 0 0 1-2.876-1.04l.141-.081 4.779-2.758a.795.795 0 0 0 .392-.681v-6.737l2.02 1.168a.071.071 0 0 1 .038.052v5.583a4.504 4.504 0 0 1-4.494 4.494zM3.6 18.304a4.47 4.47 0 0 1-.535-3.014l.142.085 4.783 2.759a.771.771 0 0 0 .78 0l5.843-3.369v2.332a.08.08 0 0 1-.032.067L9.8 19.9a4.494 4.494 0 0 1-6.2-1.596zM2.34 7.896a4.485 4.485 0 0 1 2.366-1.973V11.6a.766.766 0 0 0 .388.676l5.815 3.355-2.02 1.168a.076.076 0 0 1-.071 0l-4.83-2.786A4.504 4.504 0 0 1 2.34 7.872zm16.597 3.855l-5.843-3.369 2.02-1.168a.076.076 0 0 1 .071 0l4.83 2.791a4.494 4.494 0 0 1-.676 8.105v-5.678a.79.79 0 0 0-.402-.681zm2.01-3.023l-.141-.085-4.774-2.782a.776.776 0 0 0-.785 0L9.409 9.23V6.897a.066.066 0 0 1 .028-.061l4.83-2.787a4.5 4.5 0 0 1 6.68 4.66zm-12.64 4.135l-2.02-1.164a.08.08 0 0 1-.038-.057V6.075a4.5 4.5 0 0 1 7.375-3.453l-.142.08-4.778 2.758a.795.795 0 0 0-.392.681zm1.097-2.365l2.602-1.5 2.607 1.5v2.993l-2.607 1.5-2.602-1.5z"/>
    </svg>
  );
}

function AnthropicIcon({ className }) {
  return (
    <svg className={className} viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" fill="currentColor">
      <path d="M13.827 3.52h3.603L24 20h-3.603l-6.57-16.48zm-7.258 0h3.767L16.906 20h-3.674l-1.343-3.461H5.017L3.674 20H0L6.57 3.52zm2.285 5.357l-2.07 5.675h4.14l-2.07-5.675z"/>
    </svg>
  );
}

function OpenCodeIcon({ className }) {
  return (
    <svg className={className} viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
      <rect x="2" y="3" width="20" height="15" rx="2"/>
      <path d="M7 9l-2 3 2 3"/>
      <path d="M17 9l2 3-2 3"/>
      <path d="M12 9l-1.5 6"/>
      <line x1="2" y1="21" x2="22" y2="21"/>
    </svg>
  );
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
