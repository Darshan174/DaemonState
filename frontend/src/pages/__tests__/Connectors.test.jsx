import { render, screen, waitFor, within } from "@testing-library/react";
import { act } from "react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import Connectors from "../Connectors";

vi.mock("../../api/hooks", () => ({
  useConnectGitHub: vi.fn(),
  useConnectZoom: vi.fn(),
  useConnectNotion: vi.fn(),
  useConnectorSyncJobs: vi.fn(),
  useConnectorSyncStatus: vi.fn(),
  useConnectors: vi.fn(),
  useConnectorProcessingSummary: vi.fn(),
  useSyncConnector: vi.fn(),
  useDisconnectConnector: vi.fn(),
  useWorkspaces: vi.fn(),
}));

vi.mock("../../context/WorkspaceContext", () => ({
  useWorkspaceSelection: vi.fn(),
  resolveWorkspaceId: vi.fn(),
}));

import {
  useConnectGitHub,
  useConnectZoom,
  useConnectNotion,
  useConnectorSyncJobs,
  useConnectorSyncStatus,
  useConnectors,
  useConnectorProcessingSummary,
  useDisconnectConnector,
  useSyncConnector,
  useWorkspaces,
} from "../../api/hooks";
import { resolveWorkspaceId, useWorkspaceSelection } from "../../context/WorkspaceContext";

const syncMut = {
  mutate: vi.fn(),
  isPending: false,
  variables: undefined,
};

const disconnectMut = {
  mutate: vi.fn(),
  isPending: false,
  variables: undefined,
};

const connectNotionMut = {
  mutate: vi.fn(),
  isPending: false,
  variables: undefined,
};

const connectZoomMut = {
  mutate: vi.fn(),
  isPending: false,
  variables: undefined,
};

const connectGitHubMut = {
  mutate: vi.fn(),
  isPending: false,
  variables: undefined,
};

function mockConnectorsQuery(overrides = {}) {
  const value = {
    data: [],
    isMock: false,
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
    ...overrides,
  };
  useConnectors.mockReturnValue(value);
  return value;
}

function renderConnectors() {
  return render(
    <MemoryRouter>
      <Connectors />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  syncMut.mutate.mockReset();
  disconnectMut.mutate.mockReset();
  connectNotionMut.mutate.mockReset();
  connectZoomMut.mutate.mockReset();
  connectGitHubMut.mutate.mockReset();
  useConnectGitHub.mockReturnValue(connectGitHubMut);
  useConnectZoom.mockReturnValue(connectZoomMut);
  useConnectNotion.mockReturnValue(connectNotionMut);
  useConnectorSyncJobs.mockReturnValue({
    data: [],
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
  });
  useConnectorSyncStatus.mockReturnValue({
    data: null,
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
  });
  useSyncConnector.mockReturnValue(syncMut);
  useDisconnectConnector.mockReturnValue(disconnectMut);
  useConnectorProcessingSummary.mockReturnValue({
    data: {
      items: [
        {
          connectorType: "slack",
          status: "connected",
          totalDocuments: 42,
          processedDocuments: 30,
          unprocessedDocuments: 12,
          lastSyncAt: "Mar 29, 2026, 9:30 AM",
        },
      ],
    },
  });
  useWorkspaces.mockReturnValue({ data: [{ id: "ws_1", name: "Workspace" }] });
  useWorkspaceSelection.mockReturnValue({ selectedId: "ws_1" });
  resolveWorkspaceId.mockReturnValue("ws_1");
});

afterEach(() => {
  vi.useRealTimers();
});

describe("Connectors", () => {
  it("shows loading state", () => {
    mockConnectorsQuery({
      data: undefined,
      isLoading: true,
    });

    renderConnectors();
    expect(screen.getByText("Loading...")).toBeInTheDocument();
  });

  it("shows empty state when connector list is empty", () => {
    mockConnectorsQuery({
      data: [],
    });

    renderConnectors();
    expect(screen.getByText("No connectors configured.")).toBeInTheDocument();
    expect(screen.getByText("Self-host quick path")).toBeInTheDocument();
    expect(screen.getByText("1. Connect a source")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open sources" })).toHaveAttribute("href", "/app/sources");
  });

  it("renders demo note and disables actions when mock-backed", () => {
    mockConnectorsQuery({
      data: [
        {
          type: "slack",
          connectorId: null,
          name: "Slack",
          description: "Channels",
          status: "connected",
          lastSync: "3 min ago",
          itemsSynced: 14820,
          color: "#4A154B",
          availability: "available",
        },
        {
          type: "notion",
          connectorId: null,
          name: "Notion",
          description: "Docs",
          status: "disconnected",
          lastSync: "Never",
          itemsSynced: 0,
          color: "#111111",
          availability: "available",
        },
      ],
      isMock: true,
    });

    renderConnectors();

    expect(screen.getByText(/Demo data/)).toBeInTheDocument();
    expect(screen.getByText(/OAuth and sync actions unlock once the backend endpoints are live/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Demo mode" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Connect Notion" })).toBeDisabled();
  });

  it("renders Slack connect link for a real disconnected connector", () => {
    mockConnectorsQuery({
      data: [
        {
          type: "slack",
          connectorId: null,
          name: "Slack",
          description: "Channels",
          status: "disconnected",
          lastSync: "Never",
          itemsSynced: 0,
          color: "#4A154B",
          availability: "available",
        },
      ],
    });

    renderConnectors();

    const link = screen.getByRole("link", { name: "Start Slack OAuth" });
    expect(link).toHaveAttribute("href", "/api/connectors/slack/install?workspace_id=ws_1");
    expect(screen.getByText("Not connected")).toBeInTheDocument();
    expect(screen.getByText("Slack is not connected yet.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Connect Slack" })).toHaveAttribute(
      "href",
      "/api/connectors/slack/install?workspace_id=ws_1",
    );
  });

  it("shows Slack setup guidance instead of OAuth links when configuration is missing", () => {
    mockConnectorsQuery({
      data: [
        {
          type: "slack",
          connectorId: null,
          name: "Slack",
          description: "Channels",
          status: "disconnected",
          lastSync: "Never",
          itemsSynced: 0,
          color: "#4A154B",
          availability: "available",
          isConfigured: false,
          missingConfig: ["SLACK_CLIENT_ID", "SLACK_CLIENT_SECRET", "SLACK_REDIRECT_URI"],
        },
      ],
    });

    renderConnectors();

    expect(screen.getByText("Slack OAuth is not configured yet.")).toBeInTheDocument();
    expect(screen.getAllByText(/SLACK_CLIENT_ID, SLACK_CLIENT_SECRET, SLACK_REDIRECT_URI/).length).toBeGreaterThan(0);
    expect(screen.getAllByText("docs/slack.md").length).toBeGreaterThan(0);
    expect(screen.queryByRole("link", { name: "Start Slack OAuth" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Connect Slack" })).not.toBeInTheDocument();
  });

  it("shows coming-soon connector as disabled", () => {
    mockConnectorsQuery({
      data: [
        {
          type: "gong",
          connectorId: null,
          name: "Gong",
          description: "Calls",
          status: "coming_soon",
          lastSync: "Never",
          itemsSynced: 0,
          color: "#7C3AED",
          availability: "coming_soon",
        },
      ],
    });

    renderConnectors();

    expect(screen.getByRole("button", { name: "Coming soon" })).toBeDisabled();
    expect(screen.getByText(/deferred until the Slack path is stable/)).toBeInTheDocument();
  });

  it("queues sync for a connected connector", async () => {
    mockConnectorsQuery({
      data: [
        {
          type: "slack",
          connectorId: "conn_1",
          name: "Slack",
          description: "Channels",
          status: "connected",
          lastSync: "just now",
          itemsSynced: 12,
          color: "#4A154B",
          availability: "available",
        },
      ],
    });

    renderConnectors();

    await userEvent.click(screen.getByRole("button", { name: "Sync now" }));
    expect(syncMut.mutate).toHaveBeenCalledWith("conn_1", expect.any(Object));
  });

  it("disconnects a connected connector", async () => {
    mockConnectorsQuery({
      data: [
        {
          type: "slack",
          connectorId: "conn_1",
          name: "Slack",
          description: "Channels",
          status: "connected",
          lastSync: "just now",
          itemsSynced: 12,
          color: "#4A154B",
          availability: "available",
        },
      ],
    });

    renderConnectors();

    await userEvent.click(screen.getByRole("button", { name: "Disconnect" }));
    expect(disconnectMut.mutate).toHaveBeenCalledWith("conn_1", expect.any(Object));
  });

  it("renders backend connector metadata from config", () => {
    mockConnectorsQuery({
      data: [
        {
          type: "slack",
          connectorId: "conn_1",
          name: "Slack",
          description: "Channels",
          status: "connected",
          lastSync: "Mar 29, 2026, 9:30 AM",
          itemsSynced: 42,
          color: "#4A154B",
          availability: "available",
          teamName: "Acme Workspace",
          scope: "channels:history,channels:read",
          syncQueuedAt: "Mar 29, 2026, 9:35 AM",
          message: "Sync queued (placeholder)",
          provider: "native",
          providerLabel: "Built in",
          providerNote:
            "Slack stays native because OAuth, thread expansion, and real-time events are product-critical.",
        },
      ],
    });

    renderConnectors();

    expect(screen.getByText("Acme Workspace")).toBeInTheDocument();
    expect(screen.getByText("Built in")).toBeInTheDocument();
    expect(screen.getByText(/Sync queued Mar 29, 2026, 9:35 AM/)).toBeInTheDocument();
    expect(screen.getByText(/Slack scopes: channels:history,channels:read/)).toBeInTheDocument();
    expect(screen.getByText(/Connector path: Slack stays native/)).toBeInTheDocument();
    expect(screen.getByText("Slack is connected to Acme Workspace.")).toBeInTheDocument();
    expect(screen.getByText("42 source documents available for extraction and query.")).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "Inspect stored documents" })[0]).toHaveAttribute(
      "href",
      "/app/sources",
    );
    expect(screen.getByRole("link", { name: "Refresh OAuth" })).toHaveAttribute(
      "href",
      "/api/connectors/slack/install?workspace_id=ws_1",
    );
  });

  it("connects GitHub with a token and repository list", async () => {
    mockConnectorsQuery({
      data: [
        {
          type: "github",
          connectorId: null,
          name: "GitHub",
          description: "Issues and pull requests",
          status: "disconnected",
          lastSync: "Never",
          itemsSynced: 0,
          color: "#24292F",
          availability: "available",
          provider: "official_api",
          providerLabel: "Official API",
        },
      ],
    });

    renderConnectors();

    await userEvent.click(screen.getByRole("button", { name: "Connect GitHub" }));
    await userEvent.type(screen.getByLabelText("GitHub access token"), "ghp_test_token");
    await userEvent.type(
      screen.getByLabelText("Repositories"),
      "acme/context-engine{enter}acme/platform",
    );
    await userEvent.click(screen.getByRole("button", { name: "Save GitHub token" }));

    expect(connectGitHubMut.mutate).toHaveBeenCalledWith(
      {
        token: "ghp_test_token",
        repositories: ["acme/context-engine", "acme/platform"],
      },
      expect.any(Object),
    );
  });

  it("shows success notice after sync callback succeeds", async () => {
    syncMut.mutate.mockImplementation((_id, opts) =>
      opts.onSuccess({ message: "Synced 12 documents" }),
    );
    mockConnectorsQuery({
      data: [
        {
          type: "slack",
          connectorId: "conn_1",
          name: "Slack",
          description: "Channels",
          status: "connected",
          lastSync: "just now",
          itemsSynced: 12,
          color: "#4A154B",
          availability: "available",
        },
      ],
    });

    renderConnectors();

    await userEvent.click(screen.getByRole("button", { name: "Sync now" }));
    expect(screen.getByText("Synced 12 documents")).toBeInTheDocument();
  });

  it("shows queued sync status and disables sync while a job is active", () => {
    useConnectorSyncStatus.mockReturnValue({
      data: {
        jobId: "job_1",
        status: "running",
        createdAt: "2026-03-31T08:00:00Z",
        startedAt: "2026-03-31T08:01:00Z",
        completedAt: null,
        errorType: null,
        errorMessage: null,
        resultMetadata: {},
      },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });
    mockConnectorsQuery({
      data: [
        {
          type: "slack",
          connectorId: "conn_1",
          name: "Slack",
          description: "Channels",
          status: "connected",
          lastSync: "just now",
          itemsSynced: 12,
          color: "#4A154B",
          availability: "available",
        },
      ],
    });

    renderConnectors();

    expect(screen.getByText("Latest job")).toBeInTheDocument();
    expect(screen.getByText("running")).toBeInTheDocument();
    expect(screen.getByText(/Worker is running for this connector/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Running..." })).toBeDisabled();
  });

  it("renders completed sync job metadata", () => {
    useConnectorSyncStatus.mockReturnValue({
      data: {
        jobId: "job_2",
        status: "completed",
        createdAt: "2026-03-31T08:00:00Z",
        startedAt: "2026-03-31T08:01:00Z",
        completedAt: "2026-03-31T08:02:00Z",
        errorType: null,
        errorMessage: null,
        resultMetadata: {
          documents_fetched: 18,
          documents_persisted: 10,
          documents_processed: 7,
          sync_mode: "incremental",
        },
      },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });
    mockConnectorsQuery({
      data: [
        {
          type: "notion",
          connectorId: "conn_notion",
          name: "Notion",
          description: "Docs",
          status: "connected",
          lastSync: "Mar 31, 2026, 8:02 AM",
          itemsSynced: 18,
          color: "#111111",
          availability: "available",
          provider: "dlt",
          providerLabel: "dlt",
        },
      ],
    });

    renderConnectors();

    expect(
      screen.getByText("Notion sync completed: fetched 18, stored 10, processed 7 (incremental)."),
    ).toBeInTheDocument();
  });

  it("renders recent sync history when multiple jobs exist", () => {
    useConnectorSyncJobs.mockReturnValue({
      data: [
        {
          jobId: "job_3",
          status: "completed",
          createdAt: "2026-03-31T09:00:00Z",
          resultMetadata: {
            documents_fetched: 18,
            documents_persisted: 10,
            documents_processed: 7,
          },
        },
        {
          jobId: "job_2",
          status: "failed",
          createdAt: "2026-03-31T08:00:00Z",
          errorMessage: "Slack API returned HTTP 429",
          resultMetadata: {},
        },
      ],
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });
    mockConnectorsQuery({
      data: [
        {
          type: "slack",
          connectorId: "conn_1",
          name: "Slack",
          description: "Channels",
          status: "connected",
          lastSync: "Mar 31, 2026, 9:05 AM",
          itemsSynced: 18,
          color: "#4A154B",
          availability: "available",
        },
      ],
    });

    renderConnectors();

    expect(screen.getByText("Recent runs")).toBeInTheDocument();
    expect(screen.getByText("Fetched 18, stored 10, processed 7")).toBeInTheDocument();
    expect(screen.getByText("Slack API returned HTTP 429")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "View all runs" })).toHaveAttribute(
      "href",
      "/app/connectors/slack/runs",
    );
  });

  it("shows reconnect guidance for error state", () => {
    mockConnectorsQuery({
      data: [
        {
          type: "slack",
          connectorId: "conn_1",
          name: "Slack",
          description: "Channels",
          status: "error",
          lastSync: "Never",
          itemsSynced: 12,
          color: "#4A154B",
          availability: "available",
        },
      ],
    });

    renderConnectors();

    expect(screen.getByText("Slack needs attention.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Refresh OAuth" })).toHaveAttribute(
      "href",
      "/api/connectors/slack/install?workspace_id=ws_1",
    );
    expect(screen.getByRole("link", { name: "Reconnect Slack" })).toHaveAttribute(
      "href",
      "/api/connectors/slack/install?workspace_id=ws_1",
    );
  });

  it("shows planned OSS providers for coming-soon connectors", () => {
    mockConnectorsQuery({
      data: [
        {
          type: "gdrive",
          connectorId: null,
          name: "Google Drive",
          description: "Files",
          status: "coming_soon",
          lastSync: "Never",
          itemsSynced: 0,
          color: "#0F9D58",
          availability: "coming_soon",
          provider: "unstructured",
          providerLabel: "Unstructured",
          providerNote:
            "Planned to use Unstructured for Drive ingestion and document extraction.",
        },
      ],
    });

    renderConnectors();

    expect(screen.getByText("Unstructured")).toBeInTheDocument();
    expect(screen.getByText(/Unstructured for Drive ingestion/)).toBeInTheDocument();
  });

  it("opens a Notion token form for a disconnected connector and submits it", async () => {
    connectNotionMut.mutate.mockImplementation((_body, opts) => opts.onSuccess?.());
    mockConnectorsQuery({
      data: [
        {
          type: "notion",
          connectorId: null,
          name: "Notion",
          description: "Docs",
          status: "disconnected",
          lastSync: "Never",
          itemsSynced: 0,
          color: "#111111",
          availability: "available",
          provider: "dlt",
          providerLabel: "dlt",
        },
      ],
    });

    renderConnectors();

    await userEvent.click(screen.getByRole("button", { name: "Connect Notion" }));
    await userEvent.type(screen.getByLabelText("Notion integration token"), "secret_test_token");
    await userEvent.click(screen.getByRole("button", { name: "Save Notion token" }));

    await waitFor(() => {
      expect(connectNotionMut.mutate).toHaveBeenCalledWith(
        { token: "secret_test_token" },
        expect.any(Object),
      );
    });
    expect(screen.getByText("Notion connected. Run a sync to start storing workspace pages.")).toBeInTheDocument();
  });

  it("opens a Zoom token form for a disconnected connector and submits it", async () => {
    connectZoomMut.mutate.mockImplementation((_body, opts) => opts.onSuccess?.());
    mockConnectorsQuery({
      data: [
        {
          type: "zoom",
          connectorId: null,
          name: "Zoom",
          description: "Meeting transcripts",
          status: "disconnected",
          lastSync: "Never",
          itemsSynced: 0,
          color: "#0B5CFF",
          availability: "available",
          provider: "official_api",
          providerLabel: "Official API",
        },
      ],
    });

    renderConnectors();

    expect(screen.getByText("Choose auth mode")).toBeInTheDocument();
    expect(screen.getByText(/Zoom supports OAuth for webhook-triggered auto-sync/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Connect Zoom OAuth" })).toHaveAttribute(
      "href",
      "/api/connectors/zoom/install?workspace_id=ws_1",
    );

    await userEvent.click(screen.getByRole("button", { name: "Use manual token" }));
    await userEvent.type(screen.getByLabelText("Zoom access token"), "zoom_test_token");
    await userEvent.click(screen.getByRole("button", { name: "Save Zoom token" }));

    await waitFor(() => {
      expect(connectZoomMut.mutate).toHaveBeenCalledWith(
        { token: "zoom_test_token" },
        expect.any(Object),
      );
    });
    expect(screen.getByText("Zoom manual token saved. Run a sync to start storing meeting transcripts.")).toBeInTheDocument();
  });

  it("shows polling-only guidance for Zoom manual-token connectors", () => {
    mockConnectorsQuery({
      data: [
        {
          type: "zoom",
          connectorId: "conn_zoom",
          name: "Zoom",
          description: "Meeting transcripts",
          status: "connected",
          lastSync: "Mar 31, 2026, 8:15 AM",
          itemsSynced: 4,
          color: "#0B5CFF",
          availability: "available",
          provider: "official_api",
          providerLabel: "Official API",
          authMode: "manual_token",
          ingestionMode: "transcripts_only",
          sourceFocus: "meeting_transcripts",
        },
      ],
    });

    renderConnectors();

    expect(screen.getByText("Manual polling")).toBeInTheDocument();
    expect(screen.getByText(/This connector stays polling-only/i)).toBeInTheDocument();
    expect(screen.getByText("Transcript-only ingestion · meeting transcripts")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Upgrade to Zoom OAuth" })).toHaveAttribute(
      "href",
      "/api/connectors/zoom/install?workspace_id=ws_1",
    );
  });

  it("shows webhook-backed guidance for Zoom OAuth connectors", () => {
    mockConnectorsQuery({
      data: [
        {
          type: "zoom",
          connectorId: "conn_zoom",
          name: "Zoom",
          description: "Meeting transcripts",
          status: "connected",
          lastSync: "Apr 1, 2026, 10:00 AM",
          itemsSynced: 14,
          color: "#0B5CFF",
          availability: "available",
          provider: "official_api",
          providerLabel: "Official API",
          authMode: "oauth",
          accountId: "acct_123",
          lastWebhookEvent: "recording.transcript_completed",
          lastWebhookReceivedAt: "Apr 1, 2026, 10:05 AM",
          syncModeNote: "Webhook auto-sync handles transcript completion events.",
        },
      ],
    });

    renderConnectors();

    expect(screen.getByText("OAuth auto-sync")).toBeInTheDocument();
    expect(screen.getByText(/Webhook-triggered sync is enabled/i)).toBeInTheDocument();
    expect(screen.getByText("Account: acct_123")).toBeInTheDocument();
    expect(screen.getByText(/Last webhook: recording\.transcript_completed · Apr 1, 2026, 10:05 AM/i)).toBeInTheDocument();
    expect(screen.getByText("Webhook auto-sync handles transcript completion events.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Refresh Zoom OAuth" })).toHaveAttribute(
      "href",
      "/api/connectors/zoom/install?workspace_id=ws_1",
    );
  });

  it("renders connector processing counts from the summary endpoint", () => {
    useConnectorProcessingSummary.mockReturnValue({
      data: {
        items: [
          {
            connectorType: "notion",
            status: "connected",
            totalDocuments: 18,
            processedDocuments: 12,
            unprocessedDocuments: 6,
            lastSyncAt: "Mar 30, 2026, 10:00 AM",
          },
        ],
      },
    });
    mockConnectorsQuery({
      data: [
        {
          type: "notion",
          connectorId: "conn_notion",
          name: "Notion",
          description: "Docs",
          status: "connected",
          lastSync: "Mar 30, 2026, 10:00 AM",
          itemsSynced: 18,
          color: "#111111",
          availability: "available",
          provider: "dlt",
          providerLabel: "dlt",
          syncMode: "incremental",
        },
      ],
    });

    renderConnectors();

    const card = screen.getByText("Notion").closest("div.rounded-xl");
    expect(within(card).getByText("12")).toBeInTheDocument();
    expect(within(card).getByText("6")).toBeInTheDocument();
    expect(within(card).getByText(/Last sync mode: incremental/)).toBeInTheDocument();
  });

  it("opens Slack OAuth in a popup and shows pending guidance", async () => {
    const popup = { closed: false, close: vi.fn(), focus: vi.fn() };
    vi.spyOn(window, "open").mockReturnValue(popup);
    mockConnectorsQuery({
      data: [
        {
          type: "slack",
          connectorId: null,
          name: "Slack",
          description: "Channels",
          status: "disconnected",
          lastSync: "Never",
          itemsSynced: 0,
          color: "#4A154B",
          availability: "available",
        },
      ],
    });

    renderConnectors();

    await userEvent.click(screen.getByRole("link", { name: "Connect Slack" }));

    expect(window.open).toHaveBeenCalledWith(
      "/api/connectors/slack/install?workspace_id=ws_1",
      "ce-slack-oauth",
      expect.stringContaining("width=640"),
    );
    expect(screen.getByText(/Slack OAuth opened in a new window/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Waiting for Slack..." })).toBeDisabled();
  });

  it("refreshes connector state after popup closes and shows success notice", async () => {
    const user = userEvent.setup();
    const popup = { closed: false, close: vi.fn(), focus: vi.fn() };
    vi.spyOn(window, "open").mockReturnValue(popup);
    let pollCallback;
    vi.spyOn(window, "setInterval").mockImplementation((fn) => {
      pollCallback = fn;
      return 1;
    });
    vi.spyOn(window, "clearInterval").mockImplementation(() => {});
    const refetch = vi.fn().mockResolvedValue({
      isError: false,
      data: [
        {
          type: "slack",
          connectorId: "conn_1",
          name: "Slack",
          description: "Channels",
          status: "connected",
          lastSync: "just now",
          itemsSynced: 12,
          color: "#4A154B",
          availability: "available",
          teamName: "Acme Workspace",
        },
      ],
    });
    mockConnectorsQuery({
      data: [
        {
          type: "slack",
          connectorId: null,
          name: "Slack",
          description: "Channels",
          status: "disconnected",
          lastSync: "Never",
          itemsSynced: 0,
          color: "#4A154B",
          availability: "available",
        },
      ],
      refetch,
    });

    renderConnectors();

    await user.click(screen.getByRole("link", { name: "Connect Slack" }));
    popup.closed = true;

    await act(async () => {
      pollCallback();
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(refetch).toHaveBeenCalled();
    expect(screen.getByText("Slack connected to Acme Workspace.")).toBeInTheDocument();
  });
});
