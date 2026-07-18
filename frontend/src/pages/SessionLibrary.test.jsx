import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import SessionLibrary from "./SessionLibrary";


const mocks = vi.hoisted(() => ({
  getSource: vi.fn(),
  openHarness: vi.fn(),
  sync: vi.fn(),
}));

vi.mock("./useProductWorkspace", () => ({
  useProductWorkspace: () => ({
    activeWorkspaceId: "workspace-1",
    activeWorkspace: { id: "workspace-1", name: "Context Engine" },
    workspaces: [{ id: "workspace-1", name: "Context Engine" }],
    selectedId: "workspace-1",
    setSelectedId: vi.fn(),
    workspacesQuery: { isLoading: false },
  }),
}));

vi.mock("../api/client", () => ({
  api: { get: mocks.getSource, post: mocks.openHarness },
}));

vi.mock("../api/hooks", () => ({
  useSessionLibrary: () => ({
    isLoading: false,
    isError: false,
    data: {
      stats: { sessions: 2, topics: 2, harnesses: 1, live_sessions: 2 },
      harnesses: [
        { connector_type: "codex", name: "Codex", adapter_state: "ready", message: "Detected", session_count: 2 },
        { connector_type: "claude", name: "Claude Code", adapter_state: "unavailable", message: "Not installed", session_count: 0 },
        { connector_type: "opencode", name: "OpenCode", adapter_state: "unavailable", message: "Not installed", session_count: 0 },
      ],
      topics: [
        { id: "topic-1", name: "Alpha billing", session_count: 2, harnesses: ["codex"], last_discussed_at: "2026-07-18T09:00:00Z" },
        { id: "topic-2", name: "Beta onboarding", session_count: 1, harnesses: ["codex"], last_discussed_at: "2026-07-18T08:00:00Z" },
      ],
      sessions: [
        { id: "codex:one", session_id: "session-one", source_document_id: "doc-1", connector_type: "codex", harness: "Codex", title: "Alpha launch", topics: ["Alpha billing"], preview: "Plan Alpha billing", live: true, revision_number: 2, updated_at: "2026-07-18T09:00:00Z" },
        { id: "codex:two", session_id: "session-two", source_document_id: "doc-2", connector_type: "codex", harness: "Codex", title: "Beta onboarding", topics: ["Beta onboarding"], preview: "Review Beta onboarding", live: true, revision_number: 1, updated_at: "2026-07-18T08:00:00Z" },
      ],
    },
  }),
  useSyncSessionLibrary: () => ({
    mutate: mocks.sync,
    isPending: false,
    isError: false,
    data: null,
  }),
}));


beforeEach(() => {
  mocks.sync.mockReset();
  mocks.getSource.mockReset();
  mocks.openHarness.mockReset();
  mocks.openHarness.mockResolvedValue({
    launched: true,
    harness: "Codex",
    message: "Opened this session in the Codex desktop app. Topic highlighting stays here.",
  });
  mocks.getSource.mockResolvedValue({
    content: "[USER]\n<environment_context>Context Engine files</environment_context>\n\n[USER]\nPlan Alpha billing for launch.\n\n[ASSISTANT]\nAlpha billing will use Stripe with metered plans.",
    components: [
      { id: "component-1", name: "Alpha billing decision", value: "Use Stripe with metered plans", fact_type: "decision" },
    ],
  });
});


it("organizes sessions behind animated harness cards", async () => {
  render(<SessionLibrary />);

  await waitFor(() => {
    expect(mocks.sync).toHaveBeenCalledWith({ workspaceId: "workspace-1" });
  });

  const codex = screen.getByRole("button", { name: "Open Codex sessions" });
  const claude = screen.getByRole("button", { name: "Open Claude Code sessions" });
  expect(screen.queryByText("Alpha launch")).not.toBeInTheDocument();

  fireEvent.mouseEnter(codex);
  expect(codex).toHaveAttribute("data-hovered", "true");
  expect(claude.style.transform).toContain("24px");

  fireEvent.click(codex);
  expect(screen.getByRole("heading", { name: "Codex sessions" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Alpha launch" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Beta onboarding" })).toBeInTheDocument();

  const alphaCard = screen.getByRole("button", { name: "Open evidence for Alpha launch" });
  expect(alphaCard).toHaveAttribute("aria-expanded", "false");
  expect(within(alphaCard).getByText("1")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Alpha billing" })).not.toBeInTheDocument();

  fireEvent.mouseEnter(alphaCard);
  expect(alphaCard).toHaveAttribute("aria-expanded", "true");
  expect(screen.getByRole("button", { name: "Alpha billing" })).toBeInTheDocument();

  fireEvent.change(screen.getByRole("searchbox", { name: "Search Codex sessions" }), {
    target: { value: "Alpha" },
  });
  expect(screen.getByRole("heading", { name: "Alpha launch" })).toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "Beta onboarding" })).not.toBeInTheDocument();
});


it("opens the selected topic in a source evidence drawer and highlights matches", async () => {
  render(<SessionLibrary />);

  fireEvent.click(screen.getByRole("button", { name: "Open Codex sessions" }));
  const alphaCard = screen.getByRole("button", { name: "Open evidence for Alpha launch" });
  fireEvent.mouseEnter(alphaCard);
  fireEvent.click(screen.getByRole("button", { name: "Alpha billing" }));

  await waitFor(() => {
    expect(mocks.getSource).toHaveBeenCalledWith("/sources/doc-1?workspace_id=workspace-1");
  });

  const drawer = screen.getByRole("dialog");
  expect(within(drawer).getByRole("heading", { name: "Alpha launch" })).toBeInTheDocument();
  expect(within(drawer).getByRole("button", { name: "Alpha billing" })).toHaveAttribute("aria-pressed", "true");
  expect(within(drawer).getByRole("heading", { name: "Topic evidence" })).toBeInTheDocument();
  expect(within(drawer).getByText("Extracted context")).toBeInTheDocument();
  expect(drawer).not.toHaveTextContent("environment_context");

  await waitFor(() => {
    expect(drawer.querySelectorAll("mark").length).toBeGreaterThan(0);
  });

  fireEvent.click(within(drawer).getByRole("button", { name: "Open in Codex" }));
  await waitFor(() => {
    expect(mocks.openHarness).toHaveBeenCalledWith("/session-library/open", {
      workspace_id: "workspace-1",
      source_document_id: "doc-1",
      topic: "Alpha billing",
    });
  });
  expect(within(drawer).getByRole("button", { name: "Opened Codex" })).toBeInTheDocument();

  fireEvent.click(within(drawer).getByRole("button", { name: "Close evidence" }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});


it("shows a clear missing-app state without falling back to a terminal", async () => {
  mocks.openHarness.mockRejectedValueOnce({
    message: "Codex desktop app is missing. Install the Codex desktop app to open sessions here.",
    detail: { code: "desktop_app_missing" },
  });
  render(<SessionLibrary />);

  fireEvent.click(screen.getByRole("button", { name: "Open Codex sessions" }));
  const alphaCard = screen.getByRole("button", { name: "Open evidence for Alpha launch" });
  fireEvent.mouseEnter(alphaCard);
  fireEvent.click(screen.getByRole("button", { name: "Alpha billing" }));

  const drawer = await screen.findByRole("dialog");
  fireEvent.click(within(drawer).getByRole("button", { name: "Open in Codex" }));

  expect(await within(drawer).findByText(/Codex desktop app is missing/)).toBeInTheDocument();
  expect(within(drawer).getByRole("button", { name: "Codex app missing" })).toBeDisabled();
});
