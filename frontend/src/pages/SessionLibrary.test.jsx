import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useSearchParams } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";

import SessionLibrary from "./SessionLibrary";


const mocks = vi.hoisted(() => ({
  getSource: vi.fn(),
  openHarness: vi.fn(),
  select: vi.fn(),
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
      stats: { sessions: 2, topics: 2, harnesses: 1, live_sessions: 2, checkpoints: 1 },
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
        { id: "codex:one", session_id: "session-one", source_document_id: "doc-1", connector_type: "codex", harness: "Codex", title: "Alpha launch", topics: ["Alpha billing", "Beta pricing"], latest_topic: "Beta pricing", preview: "Plan Alpha billing", live: true, revision_number: 2, updated_at: "2026-07-18T09:00:00Z", compaction_checkpoints: [{ id: "checkpoint-1", label: "Before context compact", provider: "codex", occurred_at: "2026-07-18T08:30:00Z", turn_count: 3, objective_preview: "Review Beta pricing before launch", restorable: true }] },
        { id: "codex:two", session_id: "session-two", source_document_id: "doc-2", connector_type: "codex", harness: "Codex", title: "Beta onboarding", topics: ["Beta onboarding"], latest_topic: "Beta onboarding", preview: "Review Beta onboarding", live: true, revision_number: 1, updated_at: "2026-07-18T08:00:00Z", forked_from: { session_id: "session-one", title: "Alpha launch", source_document_id: "doc-1" } },
      ],
    },
  }),
  useSyncSessionLibrary: () => ({
    mutate: mocks.sync,
    isPending: false,
    isError: false,
    data: null,
  }),
  useSelectSessionFromLibrary: () => ({
    mutateAsync: mocks.select,
    isPending: false,
    isError: false,
    error: null,
  }),
}));


beforeEach(() => {
  mocks.sync.mockReset();
  mocks.getSource.mockReset();
  mocks.openHarness.mockReset();
  mocks.select.mockReset().mockResolvedValue({});
  mocks.openHarness.mockResolvedValue({
    launched: true,
    harness: "Codex",
    message: "Opened this session in the Codex desktop app. Topic highlighting stays here.",
  });
  mocks.getSource.mockResolvedValue({
    content: "[USER]\n<environment_context>Context Engine files</environment_context>\n\n[USER]\n# Files mentioned by the user:\n\n## Screenshot 2026-07-18 at 22.32.05.png: /var/folders/example/Screenshot 2026-07-18 at 22.32.05.png\n\n## My request for Codex:\nPlan Alpha billing for launch.\n<image name=[Image #1] path=\"/var/folders/example/Screenshot.png\">\n</image>\n\n[ASSISTANT]\nAlpha billing will use Stripe with metered plans.\n\n[USER]\nReview Beta pricing.\n\n[ASSISTANT]\nBeta pricing is ready.",
    components: [
      { id: "component-1", name: "Alpha billing decision", value: "Use Stripe with metered plans", fact_type: "decision" },
    ],
  });
});


function renderLibrary(initialEntry = "/app/library") {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route path="/app/library" element={<SessionLibrary />} />
        <Route path="/app" element={<div>Now destination</div>} />
        <Route path="/app/prepare" element={<PrepareDestination />} />
      </Routes>
    </MemoryRouter>,
  );
}


function PrepareDestination() {
  const [params] = useSearchParams();
  return <div>Prepare destination · {params.get("checkpoint")} · {params.get("objective")}</div>;
}


it("uses the shared page-title scale without the archive eyebrow", () => {
  renderLibrary();

  const heading = screen.getByRole("heading", { name: "Session Library" });
  expect(heading).toHaveClass("text-3xl", "font-black", "tracking-[-0.035em]", "sm:text-4xl");
  expect(screen.queryByText("Live session archive")).not.toBeInTheDocument();
});


it("opens a linked session topic directly in the library evidence drawer", async () => {
  renderLibrary("/app/library?source=doc-1&topic=Alpha+billing");

  const drawer = await screen.findByRole("dialog");
  expect(screen.getByRole("heading", { name: "Codex sessions" })).toBeInTheDocument();
  expect(within(drawer).getByRole("heading", { name: "Alpha launch" })).toBeInTheDocument();
  expect(within(drawer).getByRole("button", { name: "Alpha billing" })).toHaveAttribute("aria-pressed", "true");
  await waitFor(() => {
    expect(mocks.getSource).toHaveBeenCalledWith("/sources/doc-1?workspace_id=workspace-1");
  });
});


it("organizes sessions behind animated harness cards", async () => {
  renderLibrary();

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
  expect(screen.getByLabelText("Continued in a new task from Alpha launch")).toBeInTheDocument();
  expect(screen.getByText("Continued from · Alpha launch")).toBeInTheDocument();

  const alphaCard = document.querySelector('[data-session-card="codex:one"]');
  const chooseAlphaTopic = within(alphaCard).getByRole("button", { name: "Choose a topic from Alpha launch" });
  expect(chooseAlphaTopic).toHaveAttribute("aria-expanded", "false");
  expect(within(alphaCard).getByText("2")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Use Alpha billing from Alpha launch on Now" })).not.toBeInTheDocument();

  fireEvent.mouseEnter(alphaCard);
  expect(chooseAlphaTopic).toHaveAttribute("aria-expanded", "true");
  expect(screen.getByRole("button", { name: "Use Alpha billing from Alpha launch on Now" })).toBeInTheDocument();

  fireEvent.change(screen.getByRole("searchbox", { name: "Search Codex sessions" }), {
    target: { value: "Alpha" },
  });
  expect(screen.getByRole("heading", { name: "Alpha launch" })).toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "Beta onboarding" })).not.toBeInTheDocument();
});


it("selects a session topic for Now and returns to the Now tab", async () => {
  renderLibrary();

  fireEvent.click(screen.getByRole("button", { name: "Open Codex sessions" }));
  const alphaCard = document.querySelector('[data-session-card="codex:one"]');
  fireEvent.mouseEnter(alphaCard);
  fireEvent.click(screen.getByRole("button", { name: "Use Alpha billing from Alpha launch on Now" }));

  await waitFor(() => {
    expect(mocks.select).toHaveBeenCalledWith({
      workspaceId: "workspace-1",
      sourceDocumentId: "doc-1",
      topic: "Alpha billing",
    });
  });
  expect(await screen.findByText("Now destination")).toBeInTheDocument();
});


it("uses the latest topic when the user selects only the session", async () => {
  renderLibrary();

  fireEvent.click(screen.getByRole("button", { name: "Open Codex sessions" }));
  fireEvent.click(screen.getByRole("button", { name: "Use latest topic from Alpha launch on Now" }));

  await waitFor(() => {
    expect(mocks.select).toHaveBeenCalledWith({
      workspaceId: "workspace-1",
      sourceDocumentId: "doc-1",
    });
  });
  expect(await screen.findByText("Now destination")).toBeInTheDocument();
});


it("opens the selected topic in a source evidence drawer and highlights matches", async () => {
  renderLibrary();

  fireEvent.click(screen.getByRole("button", { name: "Open Codex sessions" }));
  fireEvent.click(screen.getByRole("button", { name: "Inspect evidence for Alpha launch" }));

  await waitFor(() => {
    expect(mocks.getSource).toHaveBeenCalledWith("/sources/doc-1?workspace_id=workspace-1");
  });

  const drawer = screen.getByRole("dialog");
  expect(within(drawer).getByRole("heading", { name: "Alpha launch" })).toBeInTheDocument();
  expect(within(drawer).getByRole("button", { name: "Beta pricing" })).toHaveAttribute("aria-pressed", "true");
  expect(within(drawer).getByRole("heading", { name: "Topic evidence" })).toBeInTheDocument();
  expect(within(drawer).getByText("Extracted context")).toBeInTheDocument();
  expect(drawer).not.toHaveTextContent("environment_context");
  expect(drawer).not.toHaveTextContent("Files mentioned by the user");
  expect(drawer).not.toHaveTextContent("/var/folders/example");

  await waitFor(() => {
    expect(drawer.querySelectorAll("mark").length).toBeGreaterThan(0);
  });

  fireEvent.click(within(drawer).getByRole("button", { name: "Open in Codex" }));
  await waitFor(() => {
    expect(mocks.openHarness).toHaveBeenCalledWith("/session-library/open", {
      workspace_id: "workspace-1",
      source_document_id: "doc-1",
      topic: "Beta pricing",
    });
  });
  expect(within(drawer).getByRole("button", { name: "Opened Codex" })).toBeInTheDocument();

  fireEvent.click(within(drawer).getByRole("button", { name: "Close evidence" }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});


it("restores an automatic compaction checkpoint and carries it into agent handoff", async () => {
  mocks.openHarness.mockImplementation((path) => {
    if (path === "/session-library/checkpoints/restore") {
      return Promise.resolve({
        checkpoint: { id: "checkpoint-1", label: "Before context compact" },
        restore_context: {
          objective: "Review Beta pricing before launch",
          agent_reported_state: "Billing implementation is complete; verification remains.",
          earlier_requirements: ["Plan Alpha billing"],
          markdown: "# Restored context checkpoint\n\nReview Beta pricing before launch",
        },
      });
    }
    return Promise.resolve({ launched: true, harness: "Codex", message: "Opened Codex" });
  });
  renderLibrary();

  fireEvent.click(screen.getByRole("button", { name: "Open Codex sessions" }));
  expect(screen.getByRole("button", { name: "Open 1 context checkpoints for Alpha launch" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Restore context from Alpha launch" }));

  const drawer = await screen.findByRole("dialog");
  expect(within(drawer).getByRole("heading", { name: "Compaction checkpoints" })).toBeInTheDocument();
  fireEvent.click(within(drawer).getByRole("button", { name: "Restore context" }));

  await waitFor(() => {
    expect(mocks.openHarness).toHaveBeenCalledWith("/session-library/checkpoints/restore", {
      workspace_id: "workspace-1",
      source_document_id: "doc-1",
      checkpoint_id: "checkpoint-1",
    });
  });
  expect(await within(drawer).findAllByText("Review Beta pricing before launch")).toHaveLength(2);
  expect(within(drawer).getByText(/Reported state · not verified truth/i)).toBeInTheDocument();

  fireEvent.click(within(drawer).getByRole("button", { name: "Use in agent handoff" }));
  expect(await screen.findByText(/Prepare destination · checkpoint-1 · Review Beta pricing before launch/)).toBeInTheDocument();
});


it("shows a clear missing-app state without falling back to a terminal", async () => {
  mocks.openHarness.mockRejectedValueOnce({
    message: "Codex desktop app is missing. Install the Codex desktop app to open sessions here.",
    detail: { code: "desktop_app_missing" },
  });
  renderLibrary();

  fireEvent.click(screen.getByRole("button", { name: "Open Codex sessions" }));
  fireEvent.click(screen.getByRole("button", { name: "Inspect evidence for Alpha launch" }));

  const drawer = await screen.findByRole("dialog");
  fireEvent.click(within(drawer).getByRole("button", { name: "Open in Codex" }));

  expect(await within(drawer).findByText(/Codex desktop app is missing/)).toBeInTheDocument();
  expect(within(drawer).getByRole("button", { name: "Codex app missing" })).toBeDisabled();
});
