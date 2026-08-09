import { useLayoutEffect } from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useSearchParams } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";

import SessionLibrary from "./SessionLibrary";
import {
  readExecuteSessionContexts,
  writeExecuteSessionContexts,
} from "./executeSessionSelection";


const mocks = vi.hoisted(() => ({
  checkpointRestorable: true,
  compactionCounts: {},
  extraSessions: [],
  getSource: vi.fn(),
  libraryLoading: false,
  openHarness: vi.fn(),
  select: vi.fn(),
  sync: vi.fn(),
  workspaceId: "workspace-1",
}));

vi.mock("./useProductWorkspace", () => ({
  useProductWorkspace: () => ({
    activeWorkspaceId: mocks.workspaceId,
    activeWorkspace: { id: mocks.workspaceId, name: "DaemonState" },
    workspaces: [
      { id: "workspace-1", name: "DaemonState" },
      { id: "workspace-2", name: "Second workspace" },
    ],
    selectedId: mocks.workspaceId,
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
        { id: "codex:one", session_id: "session-one", source_document_id: "doc-1", connector_type: "codex", harness: "Codex", title: "Alpha launch", topics: ["Alpha billing", "Beta pricing"], latest_topic: "Beta pricing", preview: "Plan Alpha billing", live: true, revision_number: 2, updated_at: "2026-07-18T09:00:00Z", compaction_count: mocks.compactionCounts["doc-1"] ?? 2, compaction_checkpoints: [{ id: "checkpoint-1", label: "Before context compact", provider: "codex", occurred_at: "2026-07-18T08:30:00Z", turn_count: 3, objective_preview: "Review Beta pricing before launch", restorable: mocks.checkpointRestorable }] },
        { id: "codex:two", session_id: "session-two", source_document_id: "doc-2", connector_type: "codex", harness: "Codex", title: "Beta onboarding", topics: ["Beta onboarding"], latest_topic: "Beta onboarding", preview: "Review Beta onboarding", live: true, revision_number: 1, updated_at: "2026-07-18T08:00:00Z", compaction_count: mocks.compactionCounts["doc-2"] ?? 2, forked_from: { session_id: "session-one", title: "Alpha launch", source_document_id: "doc-1" } },
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
  mocks.checkpointRestorable = true;
  mocks.compactionCounts = {};
  mocks.libraryLoading = false;
  mocks.workspaceId = "workspace-1";
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
  return render(<LibraryTestApp initialEntry={initialEntry} />);
}

function LibraryTestApp({
  initialEntry = "/app/library",
  applyImmediately = false,
}) {
  useLayoutEffect(() => {
    if (!applyImmediately) return;
    const applyButton = Array.from(document.querySelectorAll("button")).find(
      (button) => button.textContent.trim() === "Use 1 session",
    );
    if (!applyButton) {
      throw new Error("The Execute session selection apply button was not rendered.");
    }
    applyButton.click();
  }, [applyImmediately]);

  return (
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
      {" · "}{params.get("objective_source")} · {params.get("session_flow")}
    </div>
  );
}


function PrepareDestination() {
  const [params] = useSearchParams();
  return (
    <div>
      Prepare destination · {params.get("checkpoint")} · {params.get("objective")}
      {" · "}{params.get("source_provider")} · {params.get("source_session")}
      {" · "}{params.get("objective_source")}
    </div>
  );
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
  expect(screen.queryByRole("button", { name: "Prepare Alpha billing from Alpha launch" })).not.toBeInTheDocument();

  fireEvent.mouseEnter(alphaCard);
  expect(chooseAlphaTopic).toHaveAttribute("aria-expanded", "true");
  expect(screen.getByRole("button", { name: "Prepare Alpha billing from Alpha launch" })).toBeInTheDocument();

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
      compaction_count: 2,
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


it("selects a historical session topic and routes it to Prepare", async () => {
  renderLibrary();

  fireEvent.click(screen.getByRole("button", { name: "Open Codex sessions" }));
  const alphaCard = document.querySelector('[data-session-card="codex:one"]');
  fireEvent.mouseEnter(alphaCard);
  fireEvent.click(screen.getByRole("button", { name: "Prepare Alpha billing from Alpha launch" }));

  await waitFor(() => {
    expect(mocks.select).toHaveBeenCalledWith({
      workspaceId: "workspace-1",
      sourceDocumentId: "doc-1",
      topic: "Alpha billing",
    });
  });
  const destination = await screen.findByText(/Prepare destination/);
  expect(destination).toHaveTextContent("Alpha billing");
  expect(destination).toHaveTextContent("codex · session-one");
  expect(destination).toHaveTextContent("session");
});


it("uses the latest topic when the user prepares only the session", async () => {
  renderLibrary();

  fireEvent.click(screen.getByRole("button", { name: "Open Codex sessions" }));
  fireEvent.click(screen.getByRole("button", { name: "Prepare latest topic from Alpha launch" }));

  await waitFor(() => {
    expect(mocks.select).toHaveBeenCalledWith({
      workspaceId: "workspace-1",
      sourceDocumentId: "doc-1",
    });
  });
  const destination = await screen.findByText(/Prepare destination/);
  expect(destination).toHaveTextContent("Beta pricing");
  expect(destination).toHaveTextContent("codex · session-one");
});


it("shows session checkboxes only after a harness is opened and enforces the three-session maximum", async () => {
  mocks.extraSessions = [
    {
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
      compaction_count: 2,
    },
    {
      id: "codex:four",
      session_id: "session-four",
      source_document_id: "doc-4",
      connector_type: "codex",
      harness: "Codex",
      title: "Delta observability",
      topics: ["Delta observability"],
      latest_topic: "Delta observability",
      preview: "Review Delta observability",
      live: true,
      revision_number: 1,
      updated_at: "2026-07-18T06:00:00Z",
      compaction_checkpoints: [],
      compaction_count: 2,
    },
  ];
  renderLibrary("/app/library?mode=execute-context");

  expect(screen.getByText(
    "Choose up to three Session Contexts to show in Execute.",
  )).toBeInTheDocument();
  expect(screen.queryAllByRole("checkbox")).toHaveLength(0);
  fireEvent.click(screen.getByRole("button", { name: "Open Codex sessions" }));

  const alpha = screen.getByRole("checkbox", {
    name: /^Select Alpha launch from Codex for Execute/,
  });
  const beta = screen.getByRole("checkbox", {
    name: /^Select Beta onboarding from Codex for Execute/,
  });
  const gamma = screen.getByRole("checkbox", {
    name: /^Select Gamma reliability from Codex for Execute/,
  });
  const delta = screen.getByRole("checkbox", {
    name: /^Select Delta observability from Codex for Execute/,
  });
  expect(alpha).toBeEnabled();
  expect(beta).toBeEnabled();
  expect(gamma).toBeEnabled();
  expect(delta).toBeEnabled();
  expect(alpha.closest("article")).toHaveAttribute("data-context-state", "available");
  expect(within(alpha.closest("article")).getByText("Available")).toBeVisible();
  expect(within(alpha.closest("article")).getByText(
    "Ready to add to Execute",
  )).toBeVisible();

  fireEvent.click(alpha);
  fireEvent.click(beta);
  fireEvent.click(gamma);
  expect(alpha).toBeChecked();
  expect(beta).toBeChecked();
  expect(gamma).toBeChecked();
  expect(delta).toBeDisabled();
  expect(alpha.closest("article")).toHaveAttribute("data-context-state", "selected");
  expect(delta.closest("article")).toHaveAttribute("data-context-state", "limit");
  expect(within(delta.closest("article")).getByText("Limit reached")).toBeVisible();
  expect(screen.getByText("3 of 3 selected")).toBeInTheDocument();
  expect(within(gamma.closest("article")).getByText(
    "Will appear in Execute",
  )).toBeInTheDocument();

  fireEvent.click(alpha);
  expect(alpha).not.toBeChecked();
  expect(delta).toBeEnabled();
  expect(delta.closest("article")).toHaveAttribute("data-context-state", "available");
  fireEvent.click(delta);

  fireEvent.click(screen.getByRole("button", { name: "Use 3 sessions" }));
  expect(await screen.findByText("Execute destination")).toBeInTheDocument();
  expect(readExecuteSessionContexts("workspace-1").map((item) => item.sessionId)).toEqual([
    "session-two",
    "session-three",
    "session-four",
  ]);
});


it("removes individual sessions through the selected-session checklist", async () => {
  mocks.extraSessions = [
    {
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
      compaction_count: 2,
    },
    {
      id: "codex:four",
      session_id: "session-four",
      source_document_id: "doc-4",
      connector_type: "codex",
      harness: "Codex",
      title: "Delta observability",
      topics: ["Delta observability"],
      latest_topic: "Delta observability",
      preview: "Review Delta observability",
      live: true,
      revision_number: 1,
      updated_at: "2026-07-18T06:00:00Z",
      compaction_count: 2,
    },
  ];
  renderLibrary("/app/library?mode=execute-context");
  fireEvent.click(screen.getByRole("button", { name: "Open Codex sessions" }));
  ["Alpha launch", "Beta onboarding", "Gamma reliability"].forEach((title) => {
    fireEvent.click(screen.getByRole("checkbox", {
      name: new RegExp(`^Select ${title} from Codex for Execute`),
    }));
  });

  const trigger = screen.getByRole("button", {
    name: "Review / remove 3 sessions",
  });
  expect(trigger).toHaveClass("col-span-2", "w-full", "bg-[#d92d20]");
  fireEvent.click(trigger);
  expect(trigger).toHaveAttribute("aria-expanded", "true");

  const manager = screen.getByRole("dialog", {
    name: "3 selected sessions",
  });
  const managerCheckboxes = within(manager).getAllByRole("checkbox");
  expect(managerCheckboxes).toHaveLength(3);
  managerCheckboxes.forEach((checkbox) => expect(checkbox).toBeChecked());
  expect(managerCheckboxes[0]).toHaveFocus();
  expect(within(manager).getByText("Alpha launch")).toBeVisible();
  expect(within(manager).getByText("Beta onboarding")).toBeVisible();
  expect(within(manager).getByText("Gamma reliability")).toBeVisible();

  const betaManagerCheckbox = within(manager).getByRole("checkbox", {
    name: "Selected session 2: keep Beta onboarding from Codex selected for Execute",
  });
  betaManagerCheckbox.focus();
  fireEvent.click(betaManagerCheckbox);

  expect(screen.getByText("2 of 3 selected")).toBeVisible();
  expect(screen.getByRole("checkbox", {
    name: /^Select Beta onboarding from Codex for Execute/,
  })).not.toBeChecked();
  expect(screen.getByRole("checkbox", {
    name: /^Select Delta observability from Codex for Execute/,
  })).toBeEnabled();
  expect(screen.getByRole("dialog", {
    name: "2 selected sessions",
  })).toBeVisible();
  expect(screen.getByRole("checkbox", {
    name: "Selected session 2: keep Gamma reliability from Codex selected for Execute",
  })).toHaveFocus();
  expect(readExecuteSessionContexts("workspace-1")).toEqual([]);

  fireEvent.click(screen.getByRole("button", { name: "Use 2 sessions" }));
  expect(await screen.findByText("Execute destination")).toBeVisible();
  expect(readExecuteSessionContexts("workspace-1").map((item) => item.sessionId)).toEqual([
    "session-one",
    "session-three",
  ]);
});


it("closes or clears the selected-session checklist without making Cancel destructive", () => {
  mocks.extraSessions = [{
    id: "opencode:three",
    session_id: "opencode-three",
    source_document_id: "opencode-doc-3",
    connector_type: "opencode",
    harness: "OpenCode",
    title: "Alpha launch",
    topics: ["OpenCode handoff"],
    latest_topic: "OpenCode handoff",
    preview: "Continue the OpenCode handoff",
    live: true,
    revision_number: 1,
    updated_at: "2026-07-18T07:00:00Z",
    compaction_count: 2,
  }];
  writeExecuteSessionContexts("workspace-1", [
    {
      source_document_id: "doc-1",
      connector_type: "codex",
      session_id: "session-one",
      title: "Alpha launch",
      compaction_count: 2,
    },
    {
      source_document_id: "opencode-doc-3",
      connector_type: "opencode",
      session_id: "opencode-three",
      title: "Alpha launch",
      compaction_count: 2,
    },
  ]);
  renderLibrary("/app/library?mode=execute-context");

  const trigger = screen.getByRole("button", {
    name: "Review / remove 2 sessions",
  });
  fireEvent.click(trigger);
  const manager = screen.getByRole("dialog", { name: "2 selected sessions" });
  expect(within(manager).getByRole("checkbox", {
    name: "Selected session 1: keep Alpha launch from Codex selected for Execute",
  })).toBeVisible();
  expect(within(manager).getByRole("checkbox", {
    name: "Selected session 2: keep Alpha launch from OpenCode selected for Execute",
  })).toBeVisible();

  fireEvent.pointerDown(document.body);
  expect(screen.queryByRole("dialog", { name: "2 selected sessions" })).not.toBeInTheDocument();
  expect(trigger).toHaveAttribute("aria-expanded", "false");
  expect(screen.getByText("2 of 3 selected")).toBeVisible();

  fireEvent.click(trigger);
  fireEvent.keyDown(document, { key: "Escape" });
  expect(screen.queryByRole("dialog", { name: "2 selected sessions" })).not.toBeInTheDocument();
  expect(trigger).toHaveFocus();
  expect(screen.getByText("2 of 3 selected")).toBeVisible();

  fireEvent.click(trigger);
  fireEvent.click(screen.getByRole("button", { name: "Unselect everything" }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(screen.getByText("0 of 3 selected")).toBeVisible();
  expect(screen.queryByRole("button", {
    name: /Review \/ remove/,
  })).not.toBeInTheDocument();
  expect(screen.getByRole("button", {
    name: "Clear selected sessions",
  })).toHaveFocus();
  expect(readExecuteSessionContexts("workspace-1").map((item) => item.sessionId)).toEqual([
    "session-one",
    "opencode-three",
  ]);
});


it("does not confuse a previously prepared session with Execute selection", () => {
  mocks.extraSessions = [{
    id: "codex:prepared-for-now",
    session_id: "prepared-for-now",
    source_document_id: "doc-prepared-for-now",
    connector_type: "codex",
    harness: "Codex",
    title: "Prepared elsewhere",
    topics: ["Previously prepared topic", "Current Execute topic"],
    selected_for_now: true,
    selected_topic: "Previously prepared topic",
    latest_topic: "Current Execute topic",
    preview: "A session already prepared outside Execute",
    live: true,
    revision_number: 1,
    updated_at: "2026-07-18T11:00:00Z",
    compaction_count: 2,
  }];
  renderLibrary("/app/library?mode=execute-context");
  fireEvent.click(screen.getByRole("button", { name: "Open Codex sessions" }));

  const checkbox = screen.getByRole("checkbox", {
    name: /^Select Prepared elsewhere from Codex for Execute/,
  });
  const card = checkbox.closest("article");
  expect(card).toHaveAttribute("data-context-state", "available");
  expect(within(card).getByText("Available")).toBeVisible();
  expect(within(card).queryByText(/^Selected$/)).not.toBeInTheDocument();
  expect(within(card).getByText("Latest · Current Execute topic")).toBeVisible();
  expect(within(card).queryByText(/Previously prepared topic/)).not.toBeInTheDocument();
});


it("does not let an under-compacted Library session enter Execute", () => {
  mocks.extraSessions = [{
    id: "codex:locked",
    session_id: "session-locked",
    source_document_id: "doc-locked",
    connector_type: "codex",
    harness: "Codex",
    title: "Fresh session",
    topics: ["Fresh task"],
    latest_topic: "Fresh task",
    preview: "No compaction yet",
    live: true,
    revision_number: 1,
    updated_at: "2026-07-18T10:00:00Z",
    compaction_checkpoints: [],
  }];
  renderLibrary("/app/library?mode=execute-context");
  fireEvent.click(screen.getByRole("button", { name: "Open Codex sessions" }));

  const checkbox = screen.getByRole("checkbox", {
    name: /^Select Fresh session from Codex for Execute/,
  });
  const card = checkbox.closest("article");
  expect(checkbox).toBeDisabled();
  expect(card).toHaveAttribute("data-context-state", "locked");
  expect(card).toHaveAttribute("data-context-eligibility", "locked");
  expect(card).toHaveClass("shadow-none");
  expect(within(card).getByText("Locked")).toBeVisible();
  expect(within(card).getByText("0/2 compactions")).toBeVisible();
  expect(within(card).getByText("2 compactions required")).toBeVisible();
  expect(document.getElementById(
    checkbox.getAttribute("aria-describedby"),
  )).toHaveTextContent("2 compactions required");
  fireEvent.click(checkbox);
  expect(checkbox).not.toBeChecked();
});


it("uses API compaction counts when OpenCode has no checkpoint descriptors", () => {
  mocks.extraSessions = [
    {
      id: "opencode:one-compaction",
      session_id: "opencode-one-compaction",
      source_document_id: "opencode-doc-one",
      connector_type: "opencode",
      harness: "OpenCode",
      title: "OpenCode one compaction",
      topics: ["Repair OpenCode compaction projection"],
      latest_topic: "Repair OpenCode compaction projection",
      preview: "One persisted boundary",
      live: true,
      revision_number: 1,
      updated_at: "2026-07-18T10:00:00Z",
      compaction_count: 1,
      compaction_checkpoints: [],
    },
    {
      id: "opencode:two-compactions",
      session_id: "opencode-two-compactions",
      source_document_id: "opencode-doc-two",
      connector_type: "opencode",
      harness: "OpenCode",
      title: "OpenCode two compactions",
      topics: ["Repair OpenCode compaction projection"],
      latest_topic: "Repair OpenCode compaction projection",
      preview: "Two persisted boundaries",
      live: true,
      revision_number: 1,
      updated_at: "2026-07-18T09:00:00Z",
      compaction_count: 2,
      compaction_checkpoints: [],
    },
  ];
  renderLibrary("/app/library?mode=execute-context");
  fireEvent.click(screen.getByRole("button", { name: "Open OpenCode sessions" }));

  const one = screen.getByRole("checkbox", {
    name: /^Select OpenCode one compaction from OpenCode for Execute/,
  });
  const two = screen.getByRole("checkbox", {
    name: /^Select OpenCode two compactions from OpenCode for Execute/,
  });
  expect(one).toBeDisabled();
  expect(one.closest("article")).toHaveAttribute("data-context-state", "locked");
  expect(within(one.closest("article")).getByText("1/2 compactions")).toBeVisible();
  expect(two).toBeEnabled();
  expect(two.closest("article")).toHaveAttribute("data-context-state", "available");
  expect(two.closest("article")).toHaveAttribute("data-context-eligibility", "available");
  expect(two.closest("article")).toHaveClass("ring-1", "border-[#9dbc47]");
  expect(within(two.closest("article")).getByText("Available")).toBeVisible();
  expect(within(two.closest("article")).getByText("2/2 compactions")).toBeVisible();

  fireEvent.click(two);
  expect(two).toBeChecked();
});


it("removes a stored selection when a same-revision ledger refresh drops below two", async () => {
  writeExecuteSessionContexts("workspace-1", [{
    source_document_id: "doc-2",
    connector_type: "codex",
    session_id: "session-two",
    title: "Beta onboarding",
    compaction_count: 2,
  }]);
  const view = renderLibrary("/app/library?mode=execute-context");
  fireEvent.click(screen.getByRole("button", { name: "Open Codex sessions" }));

  expect(screen.getByRole("checkbox", {
    name: /^Select Beta onboarding from Codex for Execute/,
  })).toBeChecked();

  mocks.compactionCounts = { "doc-2": 1 };
  view.rerender(
    <LibraryTestApp initialEntry="/app/library?mode=execute-context" />,
  );

  await waitFor(() => expect(screen.getByRole("checkbox", {
    name: /^Select Beta onboarding from Codex for Execute/,
  })).not.toBeChecked());
  const checkbox = screen.getByRole("checkbox", {
    name: /^Select Beta onboarding from Codex for Execute/,
  });
  expect(checkbox).toBeDisabled();
  expect(within(checkbox.closest("article")).getByText("1/2 compactions")).toBeVisible();
  expect(screen.getByText("0 of 3 selected")).toBeVisible();
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
    name: /^Select Alpha launch from Codex for Execute/,
  })).not.toBeChecked();
  expect(screen.getByRole("checkbox", {
    name: /^Select Beta onboarding from Codex for Execute/,
  })).toBeChecked();
  expect(screen.getByText("1 of 3 selected")).toBeInTheDocument();
});


it("blocks applying the previous workspace's session draft during a workspace switch", () => {
  writeExecuteSessionContexts("workspace-1", [{
    source_document_id: "doc-1",
    connector_type: "codex",
    session_id: "session-one",
    title: "Alpha launch",
  }]);
  writeExecuteSessionContexts("workspace-2", [{
    source_document_id: "doc-2",
    connector_type: "codex",
    session_id: "session-two",
    title: "Beta onboarding",
  }]);

  const view = renderLibrary("/app/library?mode=execute-context");
  fireEvent.click(screen.getByRole("button", { name: "Open Codex sessions" }));
  expect(screen.getByRole("checkbox", {
    name: /^Select Alpha launch from Codex for Execute/,
  })).toBeChecked();
  fireEvent.click(screen.getByRole("button", {
    name: "Review / remove 1 session",
  }));
  expect(screen.getByRole("dialog", {
    name: "1 selected session",
  })).toBeVisible();

  mocks.workspaceId = "workspace-2";
  mocks.libraryLoading = true;
  view.rerender(
    <LibraryTestApp
      initialEntry="/app/library?mode=execute-context"
      applyImmediately
    />,
  );

  expect(screen.queryByText("Execute destination")).not.toBeInTheDocument();
  expect(screen.queryByRole("dialog", {
    name: "1 selected session",
  })).not.toBeInTheDocument();
  expect(screen.getByRole("button", {
    name: "Use 1 session",
  })).toBeDisabled();
  expect(readExecuteSessionContexts("workspace-1").map((item) => item.sessionId)).toEqual([
    "session-one",
  ]);
  expect(readExecuteSessionContexts("workspace-2").map((item) => item.sessionId)).toEqual([
    "session-two",
  ]);
});


it("lets the latest Continue session be selected like any other Execute session", () => {
  renderLibrary(
    "/app/library?mode=execute-context&current_provider=codex&current_session=session-one",
  );
  fireEvent.click(screen.getByRole("button", { name: "Open Codex sessions" }));

  const latest = screen.getByRole("checkbox", {
    name: /^Select Alpha launch from Codex for Execute/,
  });
  expect(latest).toBeEnabled();

  fireEvent.click(latest);

  expect(latest).toBeChecked();
  expect(screen.getByText("1 of 3 selected")).toBeInTheDocument();
  expect(within(latest.closest("article")).getByText(
    "Will appear in Execute",
  )).toBeInTheDocument();
});


it("returns Continue-origin Execute selection to Continue with the explicit custom-session marker", async () => {
  renderLibrary("/app/library?mode=execute-context&return_to=continue");
  fireEvent.click(screen.getByRole("button", { name: "Open Codex sessions" }));
  fireEvent.click(screen.getByRole("checkbox", {
    name: /^Select Alpha launch from Codex for Execute/,
  }));

  fireEvent.click(screen.getByRole("button", { name: "Use 1 session" }));

  expect(await screen.findByText(/Canonical Continue destination/)).toHaveTextContent(
    "custom",
  );
  expect(readExecuteSessionContexts("workspace-1")).toEqual([
    expect.objectContaining({
      provider: "codex",
      sessionId: "session-one",
      title: "Alpha launch",
    }),
  ]);
});


it("returns an empty Continue-origin selection to normal Continue", async () => {
  writeExecuteSessionContexts("workspace-1", [{
    source_document_id: "doc-1",
    connector_type: "codex",
    session_id: "session-one",
    title: "Alpha launch",
    compaction_count: 2,
  }]);
  renderLibrary("/app/library?mode=execute-context&return_to=continue");
  fireEvent.click(screen.getByRole("button", { name: "Open Codex sessions" }));
  fireEvent.click(screen.getByRole("checkbox", {
    name: /^Select Alpha launch from Codex for Execute/,
  }));

  fireEvent.click(screen.getByRole("button", { name: "Clear selected sessions" }));

  expect(await screen.findByText(/Canonical Continue destination/)).not.toHaveTextContent(
    "custom",
  );
  expect(readExecuteSessionContexts("workspace-1")).toEqual([]);
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
  expect(within(drawer).getByRole("button", { name: "Prepare this topic" })).toBeInTheDocument();

  fireEvent.click(within(drawer).getByRole("button", { name: "Close evidence" }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});


it("prepares an automatic compaction checkpoint and routes it to Prepare", async () => {
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
  fireEvent.click(within(drawer).getByRole("button", { name: "Prepare from checkpoint" }));

  await waitFor(() => {
    expect(mocks.openHarness).toHaveBeenCalledWith("/session-library/checkpoints/restore", {
      workspace_id: "workspace-1",
      source_document_id: "doc-1",
      checkpoint_id: "checkpoint-1",
    });
  });
  const destination = await screen.findByText(/Prepare destination/);
  expect(destination).toHaveTextContent("checkpoint-1");
  expect(destination).toHaveTextContent("Review Beta pricing before launch");
  expect(screen.queryByRole("button", { name: "Copy restored context" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Use in agent handoff" })).not.toBeInTheDocument();
});


it.each([
  ["false", false],
  ["missing", undefined],
  ["malformed", "yes"],
])("does not prepare a checkpoint when restorable is %s", async (_label, restorable) => {
  mocks.checkpointRestorable = restorable;
  renderLibrary();

  fireEvent.click(screen.getByRole("button", { name: "Open Codex sessions" }));
  fireEvent.click(screen.getByRole("button", { name: "Open checkpoints for Alpha launch" }));

  const drawer = await screen.findByRole("dialog");
  const disabled = within(drawer).getByRole("button", { name: "No active task" });
  expect(disabled).toBeDisabled();
  fireEvent.click(disabled);
  expect(mocks.openHarness).not.toHaveBeenCalledWith(
    "/session-library/checkpoints/restore",
    expect.anything(),
  );
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
