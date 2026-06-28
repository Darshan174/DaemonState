import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import Connectors from "./Connectors";

const mocks = vi.hoisted(() => ({
  refetchConnectors: vi.fn(),
  refetchSummary: vi.fn(),
  connectGitHubMutate: vi.fn(),
  saveSlackOAuthMutate: vi.fn(),
  syncMutate: vi.fn(),
  disconnectMutate: vi.fn(),
  ingestAISessionMutate: vi.fn(),
  importAISessionByIdMutate: vi.fn(),
}));

function mutation(mutate) {
  return { mutate, isPending: false };
}

const connectorFixtures = [
  {
    type: "slack",
    name: "Slack",
    description: "Channels, DMs, and thread history",
    status: "disconnected",
    availability: "available",
    lastSync: "Never",
    itemsSynced: 0,
    color: "#4A154B",
    provider: "native",
    providerLabel: "Built in",
    isConfigured: true,
  },
  {
    type: "github",
    name: "GitHub",
    description: "Issues, pull requests, and code review discussions",
    status: "disconnected",
    availability: "available",
    lastSync: "Never",
    itemsSynced: 0,
    color: "#24292e",
    provider: "native",
    providerLabel: "Personal Access Token",
  },
  {
    type: "gdrive",
    name: "Google Drive",
    description: "Docs, Sheets, Slides, and folder content",
    status: "disconnected",
    availability: "available",
    lastSync: "Never",
    itemsSynced: 0,
    color: "#ffffff",
    provider: "official_api",
    providerLabel: "Official API",
    isConfigured: true,
  },
  {
    type: "zoom",
    name: "Zoom",
    description: "Meeting transcripts and recording metadata",
    status: "coming_soon",
    availability: "coming_soon",
    lastSync: "Never",
    itemsSynced: 0,
    color: "#0B5CFF",
    provider: "official_api",
    providerLabel: "Coming soon",
  },
  {
    type: "codex",
    name: "Codex",
    description: "AI coding sessions",
    status: "disconnected",
    availability: "available",
    lastSync: "Never",
    itemsSynced: 0,
    color: "#10a37f",
    provider: "native",
    providerLabel: "Session import",
  },
];

vi.mock("../api/hooks", () => ({
  useConnectors: () => ({
    data: connectorFixtures,
    isMock: false,
    isLoading: false,
    isError: false,
    refetch: mocks.refetchConnectors,
  }),
  useConnectorProcessingSummary: () => ({
    data: { items: [] },
    refetch: mocks.refetchSummary,
  }),
  useWorkspaces: () => ({ data: [{ id: "workspace-1", name: "Workspace" }] }),
  useConnectorSyncJobs: () => ({ data: [] }),
  useConnectorSyncStatus: () => ({ data: null }),
  useConnectGitHub: () => mutation(mocks.connectGitHubMutate),
  useSaveSlackOAuthSettings: () => mutation(mocks.saveSlackOAuthMutate),
  useSyncConnector: () => mutation(mocks.syncMutate),
  useDisconnectConnector: () => mutation(mocks.disconnectMutate),
  useIngestAISession: () => mutation(mocks.ingestAISessionMutate),
  useImportAISessionById: () => mutation(mocks.importAISessionByIdMutate),
}));

vi.mock("../context/WorkspaceContext", () => ({
  resolveWorkspaceId: (_workspaces, selectedId) => selectedId,
  useWorkspaceSelection: () => ({ selectedId: "workspace-1" }),
}));

function renderConnectors() {
  return render(
    <MemoryRouter>
      <Connectors />
    </MemoryRouter>,
  );
}

describe("Connectors", () => {
  beforeEach(() => {
    Object.values(mocks).forEach((fn) => fn.mockReset());
  });

  it("keeps coming-soon providers disabled without manual setup actions", () => {
    renderConnectors();

    const zoomCard = screen.getByText("Zoom").closest(".rounded-xl");
    expect(zoomCard).toBeTruthy();
    expect(within(zoomCard).getAllByText("Coming soon").length).toBeGreaterThan(0);
    expect(within(zoomCard).getByRole("button", { name: "Coming soon" })).toBeDisabled();

    expect(screen.queryByText("Connect Notion")).not.toBeInTheDocument();
    expect(screen.queryByText("Update Notion token")).not.toBeInTheDocument();
    expect(screen.queryByText("Use manual token")).not.toBeInTheDocument();
    expect(screen.queryByText("Update Zoom token")).not.toBeInTheDocument();
    expect(screen.queryByText("Zoom sync mode")).not.toBeInTheDocument();
  });

  it("shows only backend-backed launch connector actions", () => {
    renderConnectors();

    expect(screen.getAllByRole("button", { name: /connect to slack/i }).length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: /connect github/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /connect with google/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /import session/i })).toBeInTheDocument();
    expect(screen.queryByText("Notion")).not.toBeInTheDocument();
  });

  it("imports AI sessions from local history by session ID", () => {
    renderConnectors();

    fireEvent.click(screen.getByRole("button", { name: /import session/i }));
    fireEvent.change(screen.getByLabelText(/session id/i), {
      target: { value: "019eff6d-f344-7a52-b0c9-3ce47f8adc21" },
    });
    const importButtons = screen.getAllByRole("button", { name: /import session/i });
    fireEvent.click(importButtons[0]);

    expect(mocks.importAISessionByIdMutate).toHaveBeenCalledWith(
      {
        connectorType: "codex",
        sessionId: "019eff6d-f344-7a52-b0c9-3ce47f8adc21",
      },
      expect.any(Object),
    );
    expect(mocks.ingestAISessionMutate).not.toHaveBeenCalled();
  });
});
