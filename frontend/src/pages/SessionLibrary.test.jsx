import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useSearchParams } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";

import SessionLibrary from "./SessionLibrary";
import {
  readExecuteSessionContexts,
  writeExecuteSessionContexts,
} from "./executeSessionSelection";


const mocks = vi.hoisted(() => ({
  extraSessions: [],
  getSource: vi.fn(),
  libraryLoading: false,
  openHarness: vi.fn(),
  select: vi.fn(),
  sync: vi.fn(),
}));

vi.mock("./useProductWorkspace", () => ({
  useProductWorkspace: () => ({
    activeWorkspaceId: "workspace-1",
    activeWorkspace: { id: "workspace-1", name: "DaemonState" },
    workspaces: [{ id: "workspace-1", name: "DaemonState" }],
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
    isLoading: mocks.libraryLoading,
    isError: false,
    data: mocks.libraryLoading ? undefined : {
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
        ...mocks.extraSessions,
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
  const storedValues = new Map();
  Object.defineProperty(globalThis, "localStorage", {
    configurable: true,
    value: {
      clear: () => storedValues.clear(),
      getItem: (key) => storedValues.get(key) ?? null,
      removeItem: (key) => storedValues.delete(key),
      setItem: (key, value) => storedValues.set(key, String(value)),
    },
  });
  mocks.extraSessions = [];
  mocks.libraryLoading = false;
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
    content: "[USER]\n<environment_context>DaemonState files</environment_context>\n\n[USER]\n# Files mentioned by the user:\n\n## Screenshot 2026-07-18 at 22.32.05.png: /var/folders/example/Screenshot 2026-07-18 at 22.32.05.png\n\n## My request for Codex:\nPlan Alpha billing for launch.\n<image name=[Image #1] path=\"/var/folders/example/Screenshot.png\">\n</image>\n\n[ASSISTANT]\nAlpha billing will use Stripe with metered plans.\n\n[USER]\nReview Beta pricing.\n\n[ASSISTANT]\nBeta pricing is ready.",
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
        <Route path="/app" element={<ContinueDestination />} />
        <Route path="/app/execute" element={<div>Execute destination</div>} />
        <Route path="/app/prepare" element={<PrepareDestination />} />
      </Routes>
    </MemoryRouter>,
  );
}

function ContinueDestination() {
  const [params] = useSearchParams();
  return (
    <div>
      Canonical Continue destination · {params.get("checkpoint")} · {params.get("objective")}
      {" · "}{params.get("source_provider")} · {params.get("source_session")}
      {" · "}{params.get("objective_source")}
    </div>
  );
}


function PrepareDestination() {
  const [params] = useSearchParams();
  return <div>Prepare destination · {params.get("checkpoint")} · {params.get("objective")}</div>;
}


it("uses the shared resume hero treatment without adding an archive eyebrow", () => {
  renderLibrary();

  const heading = screen.getByRole("heading", { name: "Session Library" });
  expect(heading).toHaveClass("text-3xl", "font-black", "tracking-[-0.035em]", "sm:text-4xl");
  expect(heading.closest("header")).toHaveClass(
    "daemonstate-resume-header",
    "min-h-56",
    "dark:bg-[#0c0c0a]",
  );
  expect(document.querySelectorAll(
    "[data-harness-deck-backdrop] [data-backdrop-harness]",
  )).toHaveLength(3);
  expect(screen.getByRole("button", { name: "Sync now" })).toHaveClass(
    "bg-[#d9ff68]/30",
    "backdrop-blur-xl",
    "dark:bg-[#d9ff68]/15",
  );
  expect(screen.queryByText("Live session archive")).not.toBeInTheDocument();
});


it("shows only numeric progress while the session library opens", () => {
  mocks.libraryLoading = true;

  renderLibrary();

  const status = screen.getByRole("status", {
    name: "Opening your session history…",
  });
  expect(status).toHaveTextContent(/^8%$/);
  expect(within(status).getByRole("progressbar", {
    name: "Loading progress",
  })).toHaveTextContent("8%");
  expect(screen.queryByText("Preparing the session archive")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("Session library harnesses")).not.toBeInTheDocument();
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

  const codex = screen.getByRole("button", { name: "Open Codex sessions" });
  const claude = screen.getByRole("button", { name: "Open Claude Code sessions" });
  const opencode = screen.getByRole("button", { name: "Open OpenCode sessions" });
  expect(screen.queryByText("Alpha launch")).not.toBeInTheDocument();
  expect(codex).toHaveAttribute("data-fan-position", "left");
  expect(claude).toHaveAttribute("data-fan-position", "center");
  expect(opencode).toHaveAttribute("data-fan-position", "right");
  expect(codex.parentElement).toHaveClass("daemonstate-harness-fan", "daemonstate-archive-fan");

  fireEvent.mouseEnter(codex);
  expect(codex).toHaveAttribute("data-hovered", "true");
  expect(claude.style.getPropertyValue("--daemonstate-card-x")).toBe("24px");

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
  expect(screen.queryByRole("button", { name: "Continue Alpha billing from Alpha launch" })).not.toBeInTheDocument();

  fireEvent.mouseEnter(alphaCard);
  expect(chooseAlphaTopic).toHaveAttribute("aria-expanded", "true");
  expect(screen.getByRole("button", { name: "Continue Alpha billing from Alpha launch" })).toBeInTheDocument();

  fireEvent.change(screen.getByRole("searchbox", { name: "Search Codex sessions" }), {
    target: { value: "Alpha" },
  });
  expect(screen.getByRole("heading", { name: "Alpha launch" })).toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "Beta onboarding" })).not.toBeInTheDocument();
});

it("syncs local history only when explicitly requested", () => {
  renderLibrary();

  expect(mocks.sync).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Sync now" }));
  expect(mocks.sync).toHaveBeenCalledTimes(1);
  expect(mocks.sync).toHaveBeenCalledWith({ workspaceId: "workspace-1" });
});

it.each([
  { provider: "codex", harness: "Codex", sessionId: "codex:one", title: "Alpha launch" },
  { provider: "claude", harness: "Claude Code", sessionId: "claude:artwork", title: "Claude architecture" },
  { provider: "opencode", harness: "OpenCode", sessionId: "opencode:artwork", title: "OpenCode refactor" },
])("uses large $harness artwork without a small corner logo on Library session cards", ({
  provider,
  harness,
  sessionId,
  title,
}) => {
  if (provider !== "codex") {
    mocks.extraSessions = [{
      id: sessionId,
      session_id: `${provider}-session`,
      source_document_id: `${provider}-document`,
      connector_type: provider,
      harness,
      title,
      topics: [`${harness} topic`],
      latest_topic: `${harness} topic`,
      preview: `${harness} session preview`,
      live: true,
      revision_number: 1,
      updated_at: "2026-07-18T07:00:00Z",
      compaction_checkpoints: [],
    }];
  }

  renderLibrary();
  fireEvent.click(screen.getByRole("button", { name: `Open ${harness} sessions` }));

  const sessionCard = document.querySelector(`[data-session-card="${sessionId}"]`);
  expect(sessionCard).not.toBeNull();
  expect(sessionCard.querySelector(`[data-harness-artwork="${provider}"]`)).toBeInTheDocument();
  expect(sessionCard.querySelector("[data-harness-logo]")).not.toBeInTheDocument();
});

it("keeps archive detection semantics separate from continuation readiness", () => {
  renderLibrary();

  const codex = screen.getByRole("button", { name: "Open Codex sessions" });
  const claude = screen.getByRole("button", { name: "Open Claude Code sessions" });
  expect(within(codex).getByText("Live")).toBeInTheDocument();
  expect(within(claude).getByText("Offline")).toBeInTheDocument();
  expect(claude).toBeEnabled();

  fireEvent.click(claude);
  expect(screen.getByRole("heading", { name: "Claude Code sessions" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "No sessions match this search" })).toBeInTheDocument();
});


it("selects a session topic and routes it to canonical Continue", async () => {
  renderLibrary();

  fireEvent.click(screen.getByRole("button", { name: "Open Codex sessions" }));
  const alphaCard = document.querySelector('[data-session-card="codex:one"]');
  fireEvent.mouseEnter(alphaCard);
  fireEvent.click(screen.getByRole("button", { name: "Continue Alpha billing from Alpha launch" }));

  await waitFor(() => {
    expect(mocks.select).toHaveBeenCalledWith({
      workspaceId: "workspace-1",
      sourceDocumentId: "doc-1",
      topic: "Alpha billing",
    });
  });
  const destination = await screen.findByText(/Canonical Continue destination/);
  expect(destination).toHaveTextContent("Alpha billing");
  expect(destination).toHaveTextContent("codex · session-one");
  expect(destination).toHaveTextContent("session");
});


it("uses the latest topic when the user continues only the session", async () => {
  renderLibrary();

  fireEvent.click(screen.getByRole("button", { name: "Open Codex sessions" }));
  fireEvent.click(screen.getByRole("button", { name: "Continue latest topic from Alpha launch" }));

  await waitFor(() => {
    expect(mocks.select).toHaveBeenCalledWith({
      workspaceId: "workspace-1",
      sourceDocumentId: "doc-1",
    });
  });
  const destination = await screen.findByText(/Canonical Continue destination/);
  expect(destination).toHaveTextContent("Beta pricing");
  expect(destination).toHaveTextContent("codex · session-one");
});


it("shows session checkboxes only after a harness is opened and enforces the two-session maximum", async () => {
  mocks.extraSessions = [{
    id: "codex:three",
    session_id: "session-three",
    source_document_id: "doc-3",
    connector_type: "codex",
    harness: "Codex",
    title: "Gamma reliability",
    topics: ["Gamma reliability"],
    latest_topic: "Gamma reliability",
    preview: "Review Gamma reliability",
    live: true,
    revision_number: 1,
    updated_at: "2026-07-18T07:00:00Z",
    compaction_checkpoints: [],
  }];
  renderLibrary("/app/library?mode=execute-context");

  expect(screen.queryAllByRole("checkbox")).toHaveLength(0);
  fireEvent.click(screen.getByRole("button", { name: "Open Codex sessions" }));

  const alpha = screen.getByRole("checkbox", {
    name: "Select Alpha launch for Execute",
  });
  const beta = screen.getByRole("checkbox", {
    name: "Select Beta onboarding for Execute",
  });
  const gamma = screen.getByRole("checkbox", {
    name: "Select Gamma reliability for Execute",
  });
  expect(alpha).toBeEnabled();
  expect(beta).toBeEnabled();
  expect(gamma).toBeEnabled();

  fireEvent.click(alpha);
  fireEvent.click(beta);
  expect(alpha).toBeChecked();
  expect(beta).toBeChecked();
  expect(gamma).toBeDisabled();
  expect(screen.getByText("2 of 2 selected")).toBeInTheDocument();

  fireEvent.click(alpha);
  expect(alpha).not.toBeChecked();
  expect(gamma).toBeEnabled();
  fireEvent.click(gamma);

  fireEvent.click(screen.getByRole("button", { name: "Use 2 sessions" }));
  expect(await screen.findByText("Execute destination")).toBeInTheDocument();
  expect(readExecuteSessionContexts("workspace-1").map((item) => item.sessionId)).toEqual([
    "session-two",
    "session-three",
  ]);
});


it("rehydrates a removed Execute card as an unselected Library session", () => {
  writeExecuteSessionContexts("workspace-1", [{
    source_document_id: "doc-2",
    connector_type: "codex",
    session_id: "session-two",
    title: "Beta onboarding",
  }]);
  renderLibrary("/app/library?mode=execute-context");
  fireEvent.click(screen.getByRole("button", { name: "Open Codex sessions" }));

  expect(screen.getByRole("checkbox", {
    name: "Select Alpha launch for Execute",
  })).not.toBeChecked();
  expect(screen.getByRole("checkbox", {
    name: "Select Beta onboarding for Execute",
  })).toBeChecked();
  expect(screen.getByText("1 of 2 selected")).toBeInTheDocument();
});


it("marks the current Execute session as unavailable for duplicate selection", () => {
  renderLibrary(
    "/app/library?mode=execute-context&current_provider=codex&current_session=session-one",
  );
  fireEvent.click(screen.getByRole("button", { name: "Open Codex sessions" }));

  const current = screen.getByRole("checkbox", {
    name: "Alpha launch is already the current session",
  });
  expect(current).toBeDisabled();
  expect(within(current.closest("article")).getByText(
    "Already shown as Current Session Context",
  )).toBeInTheDocument();
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

  expect(within(drawer).queryByRole("button", { name: "Open in Codex" })).not.toBeInTheDocument();
  expect(within(drawer).getByRole("button", { name: "Continue this topic" })).toBeInTheDocument();

  fireEvent.click(within(drawer).getByRole("button", { name: "Close evidence" }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});


it("prepares an automatic compaction checkpoint and routes it to canonical Continue", async () => {
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
  fireEvent.click(screen.getByRole("button", { name: "Open checkpoints for Alpha launch" }));

  const drawer = await screen.findByRole("dialog");
  expect(within(drawer).getByRole("heading", { name: "Compaction checkpoints" })).toBeInTheDocument();
  fireEvent.click(within(drawer).getByRole("button", { name: "Continue from checkpoint" }));

  await waitFor(() => {
    expect(mocks.openHarness).toHaveBeenCalledWith("/session-library/checkpoints/restore", {
      workspace_id: "workspace-1",
      source_document_id: "doc-1",
      checkpoint_id: "checkpoint-1",
    });
  });
  const destination = await screen.findByText(/Canonical Continue destination/);
  expect(destination).toHaveTextContent("checkpoint-1");
  expect(destination).toHaveTextContent("Review Beta pricing before launch");
  expect(screen.queryByRole("button", { name: "Copy restored context" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Use in agent handoff" })).not.toBeInTheDocument();
});


it("keeps original-harness launch out of the Library continuation journey", async () => {
  renderLibrary();

  fireEvent.click(screen.getByRole("button", { name: "Open Codex sessions" }));
  fireEvent.click(screen.getByRole("button", { name: "Inspect evidence for Alpha launch" }));

  const drawer = await screen.findByRole("dialog");
  expect(within(drawer).queryByRole("button", { name: /Open in Codex/ })).not.toBeInTheDocument();
  expect(within(drawer).getByText(/without reopening or modifying this source session/)).toBeInTheDocument();
  expect(mocks.openHarness).not.toHaveBeenCalledWith(
    "/session-library/open",
    expect.anything(),
  );
});
