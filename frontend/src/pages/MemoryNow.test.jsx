import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { createHash } from "node:crypto";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import MemoryNow from "./MemoryNow";
import {
  readExecuteSessionContexts,
  writeExecuteSessionContexts,
} from "./executeSessionSelection";

function sha256Text(value) {
  return createHash("sha256").update(value, "utf8").digest("hex");
}

const SECTION_IDS = [
  "goal",
  "requirements",
  "decisions",
  "work",
  "blockers",
  "risks",
  "learnings",
  "deliveries",
  "unverified",
  "conflicts",
  "stale",
  "owners",
  "milestones",
  "resolved",
  "completed",
  "superseded",
  "dismissed",
  "revisions",
];

function record(section, title, overrides = {}) {
  return {
    id: `${section}:${title}`,
    section,
    semantic_section: section,
    kind: section === "deliveries" ? "Verification" : "Project memory",
    title,
    summary: title,
    status: "active",
    verification: "verified",
    temporal: "current",
    source_group: "sessions",
    occurred_at: "2026-07-21T10:00:00Z",
    ...overrides,
  };
}

function memoryData(records = []) {
  const grouped = Object.fromEntries(SECTION_IDS.map((id) => [id, []]));
  for (const item of records) grouped[item.section].push(item);
  return {
    generated_at: "2026-07-21T10:05:00Z",
    current_goal: { id: "goal-1", title: "Harden checkpoint capture" },
    agenda: {
      id: "goal-1",
      kind: "current_goal",
      title: "Harden checkpoint capture",
    },
    totals: {
      active: records.filter((item) => item.status === "active").length,
      conflicts: grouped.conflicts.length,
      needs_refresh: grouped.stale.length,
      needs_review: grouped.unverified.length + grouped.conflicts.length,
    },
    sections: SECTION_IDS.map((id) => ({
      id,
      total: grouped[id].length,
      records: grouped[id],
      has_more: false,
    })),
  };
}

function digestData() {
  return {
    generated_at: "2026-07-21T10:05:00Z",
    current_goal: { id: "goal-1", title: "Harden checkpoint capture" },
    scope: { project_paths: ["/workspace/daemonstate"] },
    activity: {
      primary: {
        id: "run:run-1",
        kind: "agent_run",
        state: "completed",
        evidence_level: "observed_run",
        request: "Harden checkpoint capture",
        latest_update: "Implemented normalized session events.",
        tool: "codex",
        provider: "codex",
        session_id: "session-1",
        branch: "codex/checkpoints",
        cwd: "/workspace/daemonstate",
        updated_at: "2026-07-21T10:00:00Z",
        changed_files: ["app/services/checkpoints.py"],
        verification: { observed: 1, passed: 1, failed: 0 },
        outcome: {
          summary: "Focused tests passed.",
          observed_at: "2026-07-21T10:00:00Z",
        },
      },
      recent_sessions: [{
        id: "session:source-1",
        kind: "agent_session",
        state: "snapshot",
        evidence_level: "session_reported",
        provider: "codex",
        session_id: "session-1",
        title: "Harden checkpoint capture",
        latest_update: "Implemented normalized session events.",
        updated_at: "2026-07-21T10:00:00Z",
      }],
    },
    cards: [],
    open_loops: { open_count: 0, items: [] },
  };
}

function checkpointData() {
  const item = (id, statement, truthState = "reported", payload = {}) => ({
    id,
    statement,
    state: "active",
    truth_state: truthState,
    payload,
  });
  return {
    id: "checkpoint-1",
    schema_version: "work_checkpoint.v6",
    workspace_id: "workspace-1",
    provider: "codex",
    session_id: "session-1",
    capture_status: "complete",
    continuation_status: "ready",
    projection: { valid: true, state: "safe" },
    currentness: { state: "captured" },
    boundary: {
      occurred_at: "2026-07-21T09:58:00Z",
      sequence_number: 20,
      session_tip_sequence: 20,
      has_newer_events: false,
    },
    repo: {
      branch: "codex/checkpoints",
      worktree_fingerprint: "checkpoint-worktree",
    },
    activity: {
      latest_update: "Implemented normalized session events.",
      changed_files: ["app/services/checkpoints.py"],
    },
    sections: {
      goal: [item("goal", "Harden checkpoint capture", "user_stated")],
      decisions: [item("decision", "Keep checkpoint selection session-scoped.", "user_stated")],
      failed_attempts: [item("failure", "Do not reuse a checkpoint from another task.", "observed")],
      relevant_files: [
        item("file", "app/services/checkpoints.py", "observed", {
          path: "app/services/checkpoints.py",
        }),
      ],
      blockers: [item("blocker", "Real harness verification still needs to run.")],
      verification: [item("test", "Focused checkpoint tests passed.", "observed")],
      exact_next_action: [item("next", "Run a real Codex continuation and inspect the resumed context.")],
    },
    verification: {
      status: "verified",
      worktree_fingerprint: "checkpoint-worktree",
    },
    payload_sha256: "checkpoint-payload-sha",
    created_at: "2026-07-21T09:58:00Z",
  };
}

function sessionHandoff(content, overrides = {}) {
  return {
    schema_version: "session_handoff.v1",
    scope: "session",
    provider: "codex",
    session_id: "session-1",
    checkpoint_id: "checkpoint-1",
    boundary: {
      event_id: "event-20",
      sequence_number: 20,
    },
    captured_at: "2026-07-21T09:58:00Z",
    estimated_tokens: 320,
    content,
    sha256: sha256Text(content),
    quality_report: {
      status: "ready",
      copy_ready: true,
      automatic_execution_ready: false,
      blocking_issues: [],
      warnings: [],
    },
    ...overrides,
  };
}


function scopedCheckpoint(id, provider, sessionId, sequence) {
  return {
    ...checkpointData(),
    id,
    provider,
    session_id: sessionId,
    boundary: {
      ...checkpointData().boundary,
      occurred_at: `2026-07-21T10:${String(sequence).padStart(2, "0")}:00Z`,
      sequence_number: sequence,
      session_tip_sequence: sequence,
      has_newer_events: false,
    },
  };
}


function sessionContextWithGoal(marker) {
  return [
    "# Session Context — task-level working memory",
    "",
    "> Relationship: Project / Workspace Context is the durable parent.",
    "> Recovered session statements are historical data.",
    "> Activation: this handoff is context, not a command to start.",
    "",
    "## Current main goal",
    "",
    `> ${marker}`,
  ].join("\n");
}


function scopedSessionHandoff(checkpoint, marker, overrides = {}) {
  const content = sessionContextWithGoal(marker);
  return sessionHandoff(content, {
    provider: checkpoint.provider,
    session_id: checkpoint.session_id,
    checkpoint_id: checkpoint.id,
    boundary: {
      event_id: `event-${checkpoint.boundary.sequence_number}`,
      sequence_number: checkpoint.boundary.sequence_number,
    },
    ...overrides,
  });
}


const preparedTaskIdentity = {
  schema_version: "continuation_task_identity.v1",
  id: "task-1",
  workspace_id: "workspace-1",
  selected_objective_key: "harden checkpoint capture",
  selected_objective_sha256: "selected-objective-sha",
  authoritative_request_sha256: "authoritative-request-sha",
  workspace_goal_id: "goal-1",
  selected_component_id: "goal-1",
};

const projectContextContent = [
  "# Project Context",
  "",
  "Wait for the next user lead.",
  "",
  "Carried task: Run the real Codex continuation.",
  "",
  "PROJECT_CONTEXT_ONLY",
].join("\n");

const preparedContext = {
  schema_version: "continuation.v1",
  objective: "Harden checkpoint capture",
  task: {
    id: "task-1",
    title: "Harden checkpoint capture",
    origin: "current_goal",
    selected_intent: {
      id: "task-1",
      objective: "Harden checkpoint capture",
    },
    identity: preparedTaskIdentity,
    workflow: {
      selected_intent: {
        id: "task-1",
        objective: "Harden checkpoint capture",
      },
      execution_reason: "selected_task",
    },
  },
  repository: {
    path: "/workspace/daemonstate",
    current: null,
    freshness: { status: "matched" },
  },
  checkpoint: {
    id: "checkpoint-1",
    continuation_status: "ready",
  },
  readiness: {
    status: "ready",
    score: 100,
    blocking_issues: [],
    affected_tasks: [],
  },
  quality_report: {
    status: "ready",
    launchable: true,
    issues: [],
    blocking_issues: [],
  },
  attention: [],
  context_pack_id: "pack-1",
  project_context: {
    schema_version: "continuation_staging_context.v1",
    scope: "project",
    content: projectContextContent,
    sha256: sha256Text(projectContextContent),
    copy_ready: true,
    quality_issues: [],
  },
  execution_prompt: "EXECUTION_PROMPT_MUST_NOT_BE_COPIED",
  execution_contract: {
    schema_version: "continuation_execution.v1",
    context_pack_id: "pack-1",
    task_identity: preparedTaskIdentity,
    task: {
      request_verbatim: "Harden checkpoint capture",
    },
    project_context: [],
  },
  markdown: "# Audit ContextPack\n\nAUDIT_MARKDOWN_MUST_NOT_BE_COPIED",
  manifest: {
    schema_version: "context_pack.v2",
    context_pack_id: "pack-1",
    objective: "Harden checkpoint capture",
    continuation: {
      task_id: "task-1",
      execution_objective: "Harden checkpoint capture",
      checkpoint_id: "checkpoint-1",
      task_identity: preparedTaskIdentity,
    },
    target_model: { name: "gpt-5.6" },
    token_accounting: { rendered_tokens: 1480, within_budget: true },
    rendering: { within_budget: true },
    selected_context: [
      { title: "Current goal" },
      { title: "Exact next action" },
    ],
    excluded_context: [
      { title: "Raw test stdout", reason: "low signal" },
    ],
  },
};

const mocks = vi.hoisted(() => ({
  workspace: {
    activeWorkspaceId: "workspace-1",
    activeWorkspace: {
      id: "workspace-1",
      name: "DaemonState",
      repo_path: "/workspace/daemonstate",
    },
    workspacesQuery: { isLoading: false },
    workspaces: [],
    selectedId: "workspace-1",
    setSelectedId: vi.fn(),
  },
  digest: { data: null, isLoading: false, isError: false, error: null },
  memory: { data: null, isLoading: false, isError: false, error: null },
  memoryHook: vi.fn(),
  library: { data: { sessions: [] }, isLoading: false, isError: false, error: null },
  checkpoint: { data: null, isLoading: false, isError: false, error: null },
  latestHook: vi.fn(),
  prepare: { mutateAsync: vi.fn(), isPending: false },
  capture: { mutateAsync: vi.fn(), isPending: false },
  handoff: { mutateAsync: vi.fn(), isPending: false },
}));

vi.mock("./useProductWorkspace", () => ({
  useProductWorkspace: () => mocks.workspace,
}));

vi.mock("../context-map/api", () => ({
  useContextDigest: () => mocks.digest,
  useProjectMemory: (...args) => {
    mocks.memoryHook(...args);
    return mocks.memory;
  },
}));

vi.mock("../api/hooks", () => ({
  useLatestCheckpoint: (...args) => mocks.latestHook(...args),
  usePrepareContinuation: () => mocks.prepare,
  useCaptureCheckpoint: () => mocks.capture,
  useCheckpointHandoff: () => mocks.handoff,
  useSessionLibrary: () => mocks.library,
}));

function renderMemory() {
  return render(
    <MemoryRouter initialEntries={["/app/execute"]}>
      <MemoryNow />
    </MemoryRouter>,
  );
}

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
  mocks.digest.data = digestData();
  mocks.digest.isLoading = false;
  mocks.digest.isError = false;
  mocks.memory.data = memoryData([
    record("decisions", "Use source-backed continuation state."),
    record("work", "Finish the continuation workflow."),
    record("deliveries", "Frontend continuation tests passed."),
    record("learnings", "Avoid increasing unrelated frontend timeouts."),
  ]);
  mocks.memory.isLoading = false;
  mocks.memory.isError = false;
  mocks.memoryHook.mockReset();
  mocks.library.data = { sessions: [] };
  mocks.library.isLoading = false;
  mocks.library.isError = false;
  mocks.checkpoint.data = checkpointData();
  mocks.checkpoint.isLoading = false;
  mocks.checkpoint.isError = false;
  mocks.latestHook.mockReset().mockImplementation(() => mocks.checkpoint);
  mocks.prepare.mutateAsync.mockReset().mockResolvedValue(preparedContext);
  mocks.prepare.isPending = false;
  mocks.capture.mutateAsync.mockReset().mockResolvedValue(checkpointData());
  mocks.capture.isPending = false;
  mocks.handoff.mutateAsync.mockReset().mockResolvedValue(
    sessionHandoff("# Session Context\n\nSESSION_CONTEXT_ONLY"),
  );
  mocks.handoff.isPending = false;
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: {
      writeText: vi.fn().mockResolvedValue(undefined),
    },
  });
});

describe("ExecutePage", () => {
  it("loads the durable parent from the full workspace scope", () => {
    renderMemory();

    expect(mocks.memoryHook).toHaveBeenCalledWith("workspace-1", {
      limit: 6,
      poll: true,
      scope: "workspace",
    });
  });

  it("waits for the scoped checkpoint before making readiness claims", () => {
    mocks.checkpoint.data = undefined;
    mocks.checkpoint.isLoading = true;

    renderMemory();

    expect(screen.getByRole("status", {
      name: "Preparing the execution workspace…",
    })).toBeInTheDocument();
    expect(screen.queryByText("Ready to continue")).not.toBeInTheDocument();
    expect(screen.queryByText("No confirmed blocker.")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Continue with project context/ })).not.toBeInTheDocument();
  });

  it("uses an unscoped checkpoint lookup for production observed runs without a session id", () => {
    const observedRun = { ...mocks.digest.data.activity.primary };
    delete observedRun.provider;
    delete observedRun.session_id;
    mocks.digest.data.activity.primary = observedRun;
    mocks.checkpoint.data = null;

    renderMemory();

    const [workspaceId, options] = mocks.latestHook.mock.calls.at(-1);
    expect(workspaceId).toBe("workspace-1");
    expect(options.enabled).toBe(true);
    expect(options.provider).toBeFalsy();
    expect(options.sessionId).toBeFalsy();
  });

  it("uses the observed target session tip for a production continuation run", () => {
    mocks.digest.data.activity.primary = {
      ...mocks.digest.data.activity.primary,
      tool: "daemonstate:codex",
      provider: "codex",
      session_id: "target-session",
    };
    mocks.checkpoint.data = {
      ...checkpointData(),
      session_id: "target-session",
    };

    renderMemory();

    const latestOptions = mocks.latestHook.mock.calls.at(-1)[1];
    expect(latestOptions).toEqual({
      provider: "codex",
      sessionId: "target-session",
      enabled: true,
    });
    const sessionCard = screen.getByRole("article", {
      name: "Current Session Context",
    });
    expect(sessionCard.querySelector(
      '[data-session-provider-background="codex"] [data-harness-artwork="codex"]',
    )).toBeInTheDocument();
    expect(sessionCard.querySelector("[data-harness-logo]")).toBeNull();
    expect(screen.queryByText("Codex · target-session")).not.toBeInTheDocument();
  });

  it.each([
    ["codex", "codex"],
    ["claude_code", "claude"],
    ["open-code", "opencode"],
  ])("uses %s artwork as the session background instead of a logo tile", async (
    provider,
    expectedArtwork,
  ) => {
    const sessionId = `${expectedArtwork}-session`;
    const providerCheckpoint = {
      ...checkpointData(),
      provider: expectedArtwork,
      session_id: sessionId,
    };
    mocks.digest.data.activity.primary = {
      ...mocks.digest.data.activity.primary,
      tool: provider,
      provider,
      session_id: sessionId,
    };
    mocks.checkpoint.data = providerCheckpoint;
    mocks.capture.mutateAsync.mockResolvedValue(providerCheckpoint);
    mocks.handoff.mutateAsync.mockResolvedValue(sessionHandoff(
      `# Session Context\n\n${expectedArtwork.toUpperCase()}_CONTEXT`,
      {
        provider: expectedArtwork,
        session_id: sessionId,
      },
    ));

    renderMemory();

    const sessionCard = screen.getByRole("article", {
      name: "Current Session Context",
    });
    await waitFor(() => expect(sessionCard.querySelector(
      `[data-session-provider-background="${expectedArtwork}"] [data-harness-artwork="${expectedArtwork}"]`,
    )).toBeInTheDocument());
    expect(sessionCard.querySelector("[data-harness-logo]")).toBeNull();
    if (expectedArtwork !== "codex") {
      expect(sessionCard.querySelector('[data-harness-artwork="codex"]')).toBeNull();
    }
  });

  it("does not send an unbound same-task workspace checkpoint to the compiler", async () => {
    const observedRun = {
      ...mocks.digest.data.activity.primary,
      tool: "daemonstate:codex",
    };
    delete observedRun.provider;
    delete observedRun.session_id;
    mocks.digest.data.activity.primary = observedRun;

    renderMemory();

    await waitFor(() => expect(mocks.prepare.mutateAsync).toHaveBeenCalledWith({
      workspace_id: "workspace-1",
      repo_path: "/workspace/daemonstate",
      objective: "Harden checkpoint capture",
    }));
    expect(mocks.prepare.mutateAsync.mock.calls[0][0]).not.toHaveProperty("checkpoint_id");
    expect(mocks.prepare.mutateAsync.mock.calls[0][0]).not.toHaveProperty("source_session_id");
    expect(mocks.handoff.mutateAsync).not.toHaveBeenCalled();
    expect(screen.queryByText(
      "Run a real Codex continuation and inspect the resumed context",
    )).not.toBeInTheDocument();
  });

  it("opens on Execute with a centered session card above the workspace card", async () => {
    renderMemory();

    const executeTitle = screen.getByRole("heading", { name: "Execute", level: 1 });
    const executeHeader = executeTitle.closest("header");
    expect(executeHeader).toHaveClass(
      "daemonstate-resume-header",
      "min-h-56",
      "rounded-[2rem]",
      "border-[#d8d8cf]",
      "bg-[#f7f7f1]",
      "dark:border-[#292925]",
      "dark:bg-[#0c0c0a]",
    );
    expect(executeTitle).toHaveClass("font-black", "tracking-[-0.055em]");
    const sessionContextToggle = within(executeHeader).getByRole("button", {
      name: "Select session contexts",
    });
    expect(sessionContextToggle).toHaveAttribute("aria-pressed", "false");
    expect(sessionContextToggle).toHaveClass(
      "border-white/50",
      "bg-white/35",
      "backdrop-blur-xl",
      "backdrop-saturate-150",
      "dark:border-white/15",
      "dark:bg-black/30",
    );
    expect(sessionContextToggle.parentElement).toBe(executeTitle.parentElement?.parentElement);
    expect(within(executeHeader).getByText(
      "Prepare verified workspace context, with the active session carried inside it.",
    )).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Context hierarchy" })).not.toBeInTheDocument();
    expect(screen.queryByText("Workspace foundation")).not.toBeInTheDocument();
    expect(screen.queryByText("Context products")).not.toBeInTheDocument();
    expect(screen.queryByText("1 blocker affecting continuation")).not.toBeInTheDocument();
    expect(screen.queryByText("Ready to continue")).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", {
      name: "Harden checkpoint capture",
      level: 2,
    })).not.toBeInTheDocument();
    expect(document.querySelectorAll(
      "[data-harness-deck-backdrop] [data-backdrop-harness]",
    )).toHaveLength(3);
    expect(screen.queryByRole("navigation", { name: "Memory views" })).not.toBeInTheDocument();

    const contexts = screen.getByRole("region", { name: "Execution contexts" });
    const sessionCard = screen.getByRole("article", { name: "Current Session Context" });
    const workspaceContext = screen.getByRole("region", { name: "Workspace Context" });
    expect(contexts).toContainElement(sessionCard);
    expect(contexts).toContainElement(workspaceContext);
    expect(workspaceContext).not.toContainElement(sessionCard);
    expect(sessionCard.parentElement).toHaveClass("grid", "xl:grid-cols-3");
    expect(sessionCard).toHaveClass(
      "xl:col-start-2",
      "border-[#d8d8cf]",
      "bg-[#fbfbf6]",
      "dark:border-[#292925]",
      "dark:bg-[#141411]",
    );
    expect(sessionCard.compareDocumentPosition(workspaceContext)
      & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(within(sessionCard).getByRole("heading", {
      name: "Current Session Context",
      level: 2,
    })).toHaveClass("font-black", "tracking-[-0.055em]");
    expect(sessionCard.querySelector(
      '[data-session-provider-background="codex"] [data-harness-artwork="codex"]',
    )).toBeInTheDocument();
    expect(sessionCard.querySelector("[data-harness-logo]")).toBeNull();
    expect(within(workspaceContext).getByRole("heading", {
      name: "Workspace Context",
      level: 2,
    })).toHaveClass("font-black", "tracking-[-0.055em]");
    expect(workspaceContext).toHaveClass(
      "border-[#d8d8cf]",
      "bg-[#fbfbf6]",
      "dark:border-[#292925]",
      "dark:bg-[#141411]",
    );
    const sessionPreview = screen.getByRole("region", {
      name: "Current Session Context prompt preview",
    });
    const projectPreview = screen.getByRole("region", {
      name: "Project Context prompt preview",
    });
    await waitFor(() => {
      expect(within(sessionPreview).getByLabelText(
        "Current Session Context prompt preview content",
      )).toHaveTextContent("SESSION_CONTEXT_ONLY");
      expect(within(projectPreview).getByLabelText(
        "Project Context prompt preview content",
      )).toHaveTextContent("PROJECT_CONTEXT_ONLY");
    });
    expect(sessionPreview.querySelectorAll("[data-pen-motif]")).toHaveLength(0);
    expect(projectPreview.querySelectorAll("[data-pen-motif]")).toHaveLength(0);
    expect(screen.queryByText(/Select Preview/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "What matters now" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Since your last session" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Needs attention" })).not.toBeInTheDocument();

    expect(screen.queryByRole("searchbox", { name: "Search memory" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Review queue" })).not.toBeInTheDocument();
    expect(screen.queryByText("Memory hygiene")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Continue and reconcile context/ })).not.toBeInTheDocument();
  });

  it("auto-prepares isolated selected sessions beside the current one and can persistently remove one", async () => {
    const selectedSessions = [
      {
        id: "claude:selected-one",
        source_document_id: "document-selected-one",
        connector_type: "claude",
        session_id: "selected-one",
        title: "Architecture review",
        harness: "Claude Code",
        latest_topic: "Architecture",
      },
      {
        id: "opencode:selected-two",
        source_document_id: "document-selected-two",
        connector_type: "opencode",
        session_id: "selected-two",
        title: "Refactor follow-up",
        harness: "OpenCode",
        latest_topic: "Refactor",
      },
    ];
    mocks.library.data = { sessions: selectedSessions };
    writeExecuteSessionContexts("workspace-1", [
      {
        ...selectedSessions[0],
        source_document_id: "document-selected-one-previous-revision",
      },
      selectedSessions[1],
    ]);
    const currentCheckpoint = checkpointData();
    const claudeCheckpoint = scopedCheckpoint(
      "checkpoint-claude",
      "claude",
      "selected-one",
      31,
    );
    const openCodeCheckpoint = scopedCheckpoint(
      "checkpoint-opencode",
      "opencode",
      "selected-two",
      32,
    );
    const checkpoints = new Map([
      ["codex:session-1", currentCheckpoint],
      ["claude:selected-one", claudeCheckpoint],
      ["opencode:selected-two", openCodeCheckpoint],
    ]);
    mocks.latestHook.mockImplementation((_workspaceId, options = {}) => ({
      ...mocks.checkpoint,
      data: checkpoints.get(`${options.provider}:${options.sessionId}`) || null,
      isLoading: false,
    }));
    const handoffs = new Map([
      [
        currentCheckpoint.id,
        scopedSessionHandoff(currentCheckpoint, "MIDDLE_CODEX_ONLY"),
      ],
      [
        claudeCheckpoint.id,
        scopedSessionHandoff(claudeCheckpoint, "CLAUDE_SELECTED_ONLY"),
      ],
      [
        openCodeCheckpoint.id,
        scopedSessionHandoff(openCodeCheckpoint, "OPENCODE_SELECTED_ONLY"),
      ],
    ]);
    mocks.handoff.mutateAsync.mockImplementation(async ({ checkpointId }) => {
      const handoff = handoffs.get(checkpointId);
      if (!handoff) throw new Error(`Unexpected checkpoint ${checkpointId}`);
      return handoff;
    });

    renderMemory();

    const current = screen.getByRole("article", {
      name: "Current Session Context",
    });
    const left = screen.getByRole("article", {
      name: "Architecture review",
    });
    const right = screen.getByRole("article", {
      name: "Refactor follow-up",
    });
    expect(current).toHaveAttribute("data-session-context-slot", "current");
    expect(current).toHaveClass("xl:col-start-2", "xl:row-start-1");
    expect(within(current).queryByRole("button", {
      name: "Remove Current Session Context from Execute",
    })).not.toBeInTheDocument();
    expect(left).toHaveAttribute("data-session-context-slot", "selected-1");
    expect(left).toHaveClass("xl:col-start-1", "xl:row-start-1");
    expect(right).toHaveAttribute("data-session-context-slot", "selected-2");
    expect(right).toHaveClass("xl:col-start-3", "xl:row-start-1");
    expect(document.querySelectorAll("[data-session-context-card]")).toHaveLength(3);

    const toggle = screen.getByRole("button", {
      name: "Edit selected session contexts, 2 of 2 selected",
    });
    expect(toggle).toHaveAttribute("aria-pressed", "true");
    expect(within(left).getByText("Selected Session Context")).toBeInTheDocument();
    expect(within(right).getByText("Selected Session Context")).toBeInTheDocument();
    expect(within(left).getByText(
      "Claude · Architecture review",
    )).toBeInTheDocument();
    expect(within(right).getByText(
      "OpenCode · Refactor follow-up",
    )).toBeInTheDocument();

    await waitFor(() => {
      const currentPreview = within(current).getByLabelText(
        "Current Session Context prompt preview content",
      );
      const claudePreview = within(left).getByLabelText(
        "Architecture review Session Context prompt preview content",
      );
      const openCodePreview = within(right).getByLabelText(
        "Refactor follow-up Session Context prompt preview content",
      );
      expect(currentPreview).toHaveTextContent("MIDDLE_CODEX_ONLY");
      expect(currentPreview).not.toHaveTextContent("CLAUDE_SELECTED_ONLY");
      expect(claudePreview).toHaveTextContent("CLAUDE_SELECTED_ONLY");
      expect(claudePreview).not.toHaveTextContent("MIDDLE_CODEX_ONLY");
      expect(claudePreview).not.toHaveTextContent(
        "Relationship: Project / Workspace Context",
      );
      expect(openCodePreview).toHaveTextContent("OPENCODE_SELECTED_ONLY");
      expect(openCodePreview).not.toHaveTextContent("CLAUDE_SELECTED_ONLY");
    });
    expect(within(left).getByRole("button", {
      name: "Preview Architecture review Session Context",
    })).toHaveTextContent("Open full preview");
    expect(within(right).getByRole("button", {
      name: "Preview Refactor follow-up Session Context",
    })).toHaveTextContent("Open full preview");
    expect(mocks.capture.mutateAsync).not.toHaveBeenCalled();
    expect(mocks.handoff.mutateAsync).toHaveBeenCalledWith({
      workspaceId: "workspace-1",
      checkpointId: "checkpoint-claude",
    });
    expect(mocks.handoff.mutateAsync).toHaveBeenCalledWith({
      workspaceId: "workspace-1",
      checkpointId: "checkpoint-opencode",
    });

    fireEvent.click(within(left).getByRole("button", {
      name: "Remove Architecture review from Execute",
    }));

    expect(screen.queryByRole("article", {
      name: "Architecture review",
    })).not.toBeInTheDocument();
    expect(screen.getByRole("article", {
      name: "Refactor follow-up",
    })).toHaveAttribute("data-session-context-slot", "selected-1");
    expect(screen.getByRole("button", {
      name: "Edit selected session contexts, 1 of 2 selected",
    })).toHaveAttribute("aria-pressed", "true");
    expect(document.querySelectorAll("[data-session-context-card]")).toHaveLength(2);
    expect(readExecuteSessionContexts("workspace-1")).toEqual([
      expect.objectContaining({
        sourceDocumentId: "document-selected-two",
        sessionId: "selected-two",
      }),
    ]);
  });

  it("captures the exact selected Claude tip without reusing the middle Codex handoff", async () => {
    const selectedSession = {
      id: "claude:selected-one",
      source_document_id: "document-selected-one",
      connector_type: "claude",
      session_id: "selected-one",
      title: "Architecture review",
      harness: "Claude Code",
      latest_topic: "Architecture",
    };
    mocks.library.data = { sessions: [selectedSession] };
    writeExecuteSessionContexts("workspace-1", [selectedSession]);

    const currentCheckpoint = checkpointData();
    const claudeCheckpoint = scopedCheckpoint(
      "checkpoint-claude",
      "claude",
      "selected-one",
      31,
    );
    mocks.latestHook.mockImplementation((_workspaceId, options = {}) => ({
      ...mocks.checkpoint,
      data: options.provider === "codex"
        && options.sessionId === "session-1"
        ? currentCheckpoint
        : null,
      isLoading: false,
    }));
    mocks.capture.mutateAsync.mockImplementation(async (args) => {
      if (
        args.provider === "claude"
        && args.sessionId === "selected-one"
      ) {
        return claudeCheckpoint;
      }
      throw new Error(`Unexpected capture ${args.provider}:${args.sessionId}`);
    });
    mocks.handoff.mutateAsync.mockImplementation(async ({ checkpointId }) => {
      if (checkpointId === currentCheckpoint.id) {
        return scopedSessionHandoff(currentCheckpoint, "MIDDLE_CODEX_ONLY");
      }
      if (checkpointId === claudeCheckpoint.id) {
        return scopedSessionHandoff(claudeCheckpoint, "CLAUDE_SELECTED_ONLY");
      }
      throw new Error(`Unexpected checkpoint ${checkpointId}`);
    });

    renderMemory();

    const claudeCard = screen.getByRole("article", {
      name: "Architecture review",
    });
    await waitFor(() => {
      const preview = within(claudeCard).getByLabelText(
        "Architecture review Session Context prompt preview content",
      );
      expect(preview).toHaveTextContent("CLAUDE_SELECTED_ONLY");
      expect(preview).not.toHaveTextContent("MIDDLE_CODEX_ONLY");
    });
    expect(mocks.capture.mutateAsync).toHaveBeenCalledTimes(1);
    expect(mocks.capture.mutateAsync).toHaveBeenCalledWith({
      workspaceId: "workspace-1",
      provider: "claude",
      sessionId: "selected-one",
      updateGenericLatest: false,
    });
    expect(mocks.handoff.mutateAsync).toHaveBeenCalledWith({
      workspaceId: "workspace-1",
      checkpointId: "checkpoint-claude",
    });
    expect(within(claudeCard).getByRole("button", {
      name: "Preview Architecture review Session Context",
    })).toHaveTextContent("Open full preview");
  });

  it("copies a newly observed selected-session checkpoint instead of its auto-prepared cache", async () => {
    const selectedSession = {
      id: "claude:selected-one",
      source_document_id: "document-selected-one",
      connector_type: "claude",
      session_id: "selected-one",
      title: "Architecture review",
      harness: "Claude Code",
      latest_topic: "Architecture",
    };
    mocks.library.data = { sessions: [selectedSession] };
    writeExecuteSessionContexts("workspace-1", [selectedSession]);

    const currentCheckpoint = checkpointData();
    const originalCheckpoint = scopedCheckpoint(
      "checkpoint-claude-original",
      "claude",
      "selected-one",
      31,
    );
    const newerCheckpoint = scopedCheckpoint(
      "checkpoint-claude-newer",
      "claude",
      "selected-one",
      32,
    );
    let selectedLatest = originalCheckpoint;
    mocks.latestHook.mockImplementation((_workspaceId, options = {}) => ({
      ...mocks.checkpoint,
      data: options.provider === "claude"
        ? selectedLatest
        : currentCheckpoint,
      isLoading: false,
    }));
    const currentHandoff = scopedSessionHandoff(
      currentCheckpoint,
      "MIDDLE_CODEX_ONLY",
    );
    const originalHandoff = scopedSessionHandoff(
      originalCheckpoint,
      "CLAUDE_ORIGINAL_ONLY",
    );
    const newerHandoff = scopedSessionHandoff(
      newerCheckpoint,
      "CLAUDE_NEWER_ONLY",
    );
    const handoffs = new Map([
      [currentCheckpoint.id, currentHandoff],
      [originalCheckpoint.id, originalHandoff],
      [newerCheckpoint.id, newerHandoff],
    ]);
    mocks.handoff.mutateAsync.mockImplementation(async ({ checkpointId }) => {
      const handoff = handoffs.get(checkpointId);
      if (!handoff) throw new Error(`Unexpected checkpoint ${checkpointId}`);
      return handoff;
    });

    const view = renderMemory();
    const selectedCard = screen.getByRole("article", {
      name: "Architecture review",
    });
    await waitFor(() => {
      expect(within(selectedCard).getByLabelText(
        "Architecture review Session Context prompt preview content",
      )).toHaveTextContent("CLAUDE_ORIGINAL_ONLY");
    });

    selectedLatest = newerCheckpoint;
    view.rerender(
      <MemoryRouter initialEntries={["/app/execute"]}>
        <MemoryNow />
      </MemoryRouter>,
    );
    fireEvent.click(within(selectedCard).getByRole("button", {
      name: "Copy Architecture review Session Context",
    }));

    await waitFor(() => {
      expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
        newerHandoff.content,
      );
    });
    expect(navigator.clipboard.writeText).not.toHaveBeenCalledWith(
      originalHandoff.content,
    );
    expect(mocks.handoff.mutateAsync).toHaveBeenCalledWith({
      workspaceId: "workspace-1",
      checkpointId: "checkpoint-claude-newer",
    });
  });

  it("names the selected session in its full-preview quality warning", async () => {
    const selectedSession = {
      id: "claude:selected-one",
      source_document_id: "document-selected-one",
      connector_type: "claude",
      session_id: "selected-one",
      title: "Architecture review",
      harness: "Claude Code",
      latest_topic: "Architecture",
    };
    mocks.library.data = { sessions: [selectedSession] };
    writeExecuteSessionContexts("workspace-1", [selectedSession]);

    const currentCheckpoint = checkpointData();
    const claudeCheckpoint = scopedCheckpoint(
      "checkpoint-claude",
      "claude",
      "selected-one",
      31,
    );
    mocks.latestHook.mockImplementation((_workspaceId, options = {}) => ({
      ...mocks.checkpoint,
      data: options.provider === "claude"
        ? claudeCheckpoint
        : currentCheckpoint,
      isLoading: false,
    }));
    mocks.handoff.mutateAsync.mockImplementation(async ({ checkpointId }) => {
      if (checkpointId === currentCheckpoint.id) {
        return scopedSessionHandoff(currentCheckpoint, "MIDDLE_CODEX_ONLY");
      }
      if (checkpointId === claudeCheckpoint.id) {
        return scopedSessionHandoff(
          claudeCheckpoint,
          "CLAUDE_SELECTED_ONLY",
          {
            quality_report: {
              status: "blocked",
              copy_ready: false,
              automatic_execution_ready: false,
              blocking_issues: [{
                code: "required_attachments_resolved",
                severity: "blocking",
                message: "The selected visual attachment is not hash-verified.",
              }],
              warnings: [],
            },
          },
        );
      }
      throw new Error(`Unexpected checkpoint ${checkpointId}`);
    });

    renderMemory();
    const selectedCard = screen.getByRole("article", {
      name: "Architecture review",
    });
    await waitFor(() => expect(within(selectedCard).getByRole("button", {
      name: "Preview Architecture review Session Context",
    })).toHaveTextContent("Open full preview"));

    fireEvent.click(within(selectedCard).getByRole("button", {
      name: "Preview Architecture review Session Context",
    }));

    const dialog = await screen.findByRole("dialog", {
      name: "Architecture review Session Context Preview",
    });
    expect(within(dialog).getByRole("status")).toHaveTextContent(
      "Architecture review Session Context is not copy-ready.",
    );
    expect(within(dialog).getByRole("status")).not.toHaveTextContent(
      "Current Session Context is not copy-ready.",
    );
  });

  it("removes explanatory chrome while preserving separate context artifacts", async () => {
    renderMemory();

    const workspaceContext = screen.getByRole("region", { name: "Workspace Context" });
    const sessionCard = screen.getByRole("article", {
      name: "Current Session Context",
    });

    expect(workspaceContext).not.toContainElement(sessionCard);
    expect(within(sessionCard).queryByText("Contained context")).not.toBeInTheDocument();
    expect(within(sessionCard).queryByText("Session-specific")).not.toBeInTheDocument();
    expect(within(sessionCard).queryByText("Context relationship")).not.toBeInTheDocument();
    expect(within(sessionCard).queryByText(/Uses Workspace Context/)).not.toBeInTheDocument();
    expect(within(sessionCard).queryByText(/^Source$/)).not.toBeInTheDocument();
    expect(within(sessionCard).queryByText(/^Freshness$/)).not.toBeInTheDocument();
    expect(within(sessionCard).queryByText(/^Size$/)).not.toBeInTheDocument();
    expect(sessionCard.querySelector("dl")).toBeNull();
    expect(within(sessionCard).getByRole("region", {
      name: "Current Session Context prompt preview",
    }).querySelector("[data-pen-motif]")).toBeNull();
    expect(within(workspaceContext).getByRole("region", {
      name: "Project Context prompt preview",
    }).querySelector("[data-pen-motif]")).toBeNull();

    expect(within(sessionCard).queryByText(
      /Inherits the verified workspace foundation.*adds only this session's current task state/i,
    )).not.toBeInTheDocument();
    expect(within(sessionCard).queryByText(/Current tip · Updated/)).not.toBeInTheDocument();
    await waitFor(() => expect(within(sessionCard).getByRole("button", {
      name: "Preview Current Session Context",
    })).toHaveTextContent("Open full preview"));
    const sessionCopy = within(sessionCard).getByRole("button", {
      name: "Copy Current Session Context",
    });
    expect(sessionCopy).toBeEnabled();
    expect(sessionCopy).toHaveClass("btn-primary");

    expect(within(workspaceContext).queryByText("Parent context")).not.toBeInTheDocument();
    expect(within(workspaceContext).queryByText("Workspace-wide · source-backed")).not.toBeInTheDocument();
    expect(within(workspaceContext).queryByText(
      /durable Project Context foundation every continuation inherits.*active session is contained below/i,
    )).not.toBeInTheDocument();
    expect(within(workspaceContext).queryByText(/^Workspace scope$/)).not.toBeInTheDocument();
    expect(within(workspaceContext).queryByText(/^Repository$/)).not.toBeInTheDocument();
    expect(within(workspaceContext).queryByText(/^Compiled size$/)).not.toBeInTheDocument();
    expect(workspaceContext.querySelector("dl")).toBeNull();
    await waitFor(() => expect(within(workspaceContext).getByRole("button", {
      name: "Preview Project Context",
    })).toHaveTextContent("Open full preview"));
    const projectCopy = within(workspaceContext).getByRole("button", {
      name: "Copy Project Context",
    });
    expect(projectCopy).toBeEnabled();
    expect(projectCopy).toHaveClass("btn-primary");
    expect(screen.queryByText("Advanced context details")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Inspect context sources" })).not.toBeInTheDocument();
  });

  it("freshly revalidates the prepared session prompt before copying it", async () => {
    renderMemory();

    const sessionCard = screen.getByRole("article", {
      name: "Current Session Context",
    });
    const preview = within(sessionCard).getByRole("button", {
      name: "Preview Current Session Context",
    });
    fireEvent.click(preview);

    await waitFor(() => expect(mocks.handoff.mutateAsync).toHaveBeenCalledWith({
      workspaceId: "workspace-1",
      checkpointId: "checkpoint-1",
    }));
    expect(mocks.capture.mutateAsync).not.toHaveBeenCalled();
    const dialog = await screen.findByRole("dialog", {
      name: "Current Session Context Preview",
    });
    expect(within(dialog).getByText(/SESSION_CONTEXT_ONLY/)).toBeInTheDocument();
    expect(screen.getByRole("region", {
      name: "Current Session Context prompt preview",
    })).toHaveTextContent("SESSION_CONTEXT_ONLY");
    expect(mocks.handoff.mutateAsync).toHaveBeenCalledTimes(1);
    mocks.handoff.mutateAsync.mockResolvedValue(sessionHandoff(
      "# Session Context\n\nFRESHLY_REVALIDATED",
    ));

    fireEvent.click(within(dialog).getByRole("button", {
      name: "Copy Current Session Context",
    }));
    await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
      "# Session Context\n\nFRESHLY_REVALIDATED",
    ));
    expect(mocks.handoff.mutateAsync).toHaveBeenCalledTimes(2);
    expect(navigator.clipboard.writeText).not.toHaveBeenCalledWith(
      "# Session Context\n\nSESSION_CONTEXT_ONLY",
    );
    expect(navigator.clipboard.writeText).not.toHaveBeenCalledWith(preparedContext.markdown);
  });

  it("retries a transient session-copy fetch failure before copying", async () => {
    renderMemory();

    const sessionCard = screen.getByRole("article", {
      name: "Current Session Context",
    });
    await waitFor(() => expect(within(sessionCard).getByRole("button", {
      name: "Preview Current Session Context",
    })).toHaveTextContent("Open full preview"));
    expect(mocks.handoff.mutateAsync).toHaveBeenCalledTimes(1);
    mocks.handoff.mutateAsync
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValueOnce(sessionHandoff(
        "# Session Context\n\nRECOVERED_AFTER_RETRY",
      ));

    fireEvent.click(within(sessionCard).getByRole("button", {
      name: "Copy Current Session Context",
    }));

    await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
      "# Session Context\n\nRECOVERED_AFTER_RETRY",
    ));
    expect(mocks.handoff.mutateAsync).toHaveBeenCalledTimes(3);
    expect(screen.queryByText("Failed to fetch")).not.toBeInTheDocument();
  });

  it("keeps a persistent session-copy network failure safe and actionable", async () => {
    renderMemory();

    const sessionCard = screen.getByRole("article", {
      name: "Current Session Context",
    });
    await waitFor(() => expect(within(sessionCard).getByRole("button", {
      name: "Preview Current Session Context",
    })).toHaveTextContent("Open full preview"));
    expect(mocks.handoff.mutateAsync).toHaveBeenCalledTimes(1);
    mocks.handoff.mutateAsync.mockRejectedValue(new TypeError("Failed to fetch"));

    fireEvent.click(within(sessionCard).getByRole("button", {
      name: "Copy Current Session Context",
    }));

    const retryCopy = await within(sessionCard).findByRole("button", {
      name: "Try copy again",
    });
    expect(retryCopy).toHaveClass("btn-primary");
    expect(within(sessionCard).getByText(
      /Could not reach DaemonState to verify the current session/,
    )).toBeInTheDocument();
    expect(mocks.handoff.mutateAsync).toHaveBeenCalledTimes(4);
    expect(navigator.clipboard.writeText).not.toHaveBeenCalled();
    expect(screen.queryByText("Failed to fetch")).not.toBeInTheDocument();
  });

  it("previews but never copies Session Context that fails its quality gate", async () => {
    mocks.handoff.mutateAsync.mockResolvedValue(sessionHandoff(
      "# Session Context\n\nCONTRADICTORY_HANDOFF",
      {
        quality_report: {
          status: "needs_reconciliation",
          copy_ready: false,
          automatic_execution_ready: false,
          blocking_issues: [{
            code: "completion_remaining_conflict",
            severity: "blocking",
            message: "Reported completion conflicts with remaining work.",
          }],
          warnings: [],
        },
      },
    ));
    renderMemory();

    const sessionCard = screen.getByRole("article", {
      name: "Current Session Context",
    });
    fireEvent.click(within(sessionCard).getByRole("button", {
      name: "Preview Current Session Context",
    }));

    const dialog = await screen.findByRole("dialog", {
      name: "Current Session Context Preview",
    });
    expect(within(dialog).getByRole("status")).toHaveTextContent(
      "Reported completion conflicts with remaining work.",
    );
    expect(within(dialog).getByRole("button", {
      name: "Copy Current Session Context",
    })).toBeDisabled();
    expect(within(sessionCard).getByRole("button", {
      name: "Copy Current Session Context",
    })).toBeDisabled();
    expect(within(sessionCard).getByText("Not copy-ready")).toBeInTheDocument();
    expect(within(sessionCard).getByText(
      /Current Session Context is not copy-ready.*completion conflicts/,
    )).toBeInTheDocument();
    expect(navigator.clipboard.writeText).not.toHaveBeenCalled();
  });

  it("captures a new session tip before copying when the saved checkpoint is stale", async () => {
    mocks.checkpoint.data = {
      ...checkpointData(),
      currentness: { state: "superseded" },
      boundary: {
        ...checkpointData().boundary,
        has_newer_events: true,
        session_tip_sequence: 21,
      },
    };
    mocks.capture.mutateAsync.mockResolvedValue({
      ...checkpointData(),
      id: "checkpoint-current-tip",
    });
    mocks.handoff.mutateAsync.mockResolvedValue(sessionHandoff(
      "# Session Context\n\nCURRENT_TIP_ONLY",
      {
        checkpoint_id: "checkpoint-current-tip",
      },
    ));
    renderMemory();

    const sessionCard = screen.getByRole("article", {
      name: "Current Session Context",
    });
    fireEvent.click(within(sessionCard).getByRole("button", {
      name: "Copy Current Session Context",
    }));

    await waitFor(() => expect(mocks.capture.mutateAsync).toHaveBeenCalledWith({
      workspaceId: "workspace-1",
      provider: "codex",
      sessionId: "session-1",
    }));
    expect(mocks.handoff.mutateAsync).toHaveBeenCalledWith({
      workspaceId: "workspace-1",
      checkpointId: "checkpoint-current-tip",
    });
    await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
      "# Session Context\n\nCURRENT_TIP_ONLY",
    ));
  });

  it("recaptures and retries handoff once when a newer tip can restore the lossless goal", async () => {
    mocks.capture.mutateAsync.mockResolvedValue({
      ...checkpointData(),
      id: "checkpoint-refreshed-tip",
    });
    mocks.handoff.mutateAsync
      .mockRejectedValueOnce(new Error(
        "The checkpoint does not contain a lossless session goal and its original goal event is unavailable.",
      ))
      .mockResolvedValueOnce(sessionHandoff(
        "# Session Context\n\nREFRESHED_LOSSLESS_GOAL",
        {
          checkpoint_id: "checkpoint-refreshed-tip",
        },
      ));
    renderMemory();

    const sessionCard = screen.getByRole("article", {
      name: "Current Session Context",
    });
    fireEvent.click(within(sessionCard).getByRole("button", {
      name: "Preview Current Session Context",
    }));

    await waitFor(() => expect(mocks.capture.mutateAsync).toHaveBeenCalledWith({
      workspaceId: "workspace-1",
      provider: "codex",
      sessionId: "session-1",
    }));
    expect(mocks.handoff.mutateAsync.mock.calls).toEqual([
      [{
        workspaceId: "workspace-1",
        checkpointId: "checkpoint-1",
      }],
      [{
        workspaceId: "workspace-1",
        checkpointId: "checkpoint-refreshed-tip",
      }],
    ]);
    const dialog = await screen.findByRole("dialog", {
      name: "Current Session Context Preview",
    });
    expect(within(dialog).getByText(/REFRESHED_LOSSLESS_GOAL/)).toBeInTheDocument();
  });

  it("explains an irrecoverable missing lossless goal without offering a retry loop", async () => {
    mocks.handoff.mutateAsync.mockRejectedValue(new Error(
      "The checkpoint does not contain a lossless session goal and its original goal event is unavailable.",
    ));
    renderMemory();

    const sessionCard = screen.getByRole("article", {
      name: "Current Session Context",
    });
    fireEvent.click(within(sessionCard).getByRole("button", {
      name: "Preview Current Session Context",
    }));

    const dialog = await screen.findByRole("dialog", {
      name: "Current Session Context Preview",
    });
    expect(within(dialog).getByRole("alert")).toHaveTextContent(
      "no longer retains its original user request",
    );
    expect(within(dialog).queryByRole("button", {
      name: "Refresh current session tip",
    })).not.toBeInTheDocument();
    expect(mocks.capture.mutateAsync).toHaveBeenCalledTimes(1);
    expect(mocks.handoff.mutateAsync).toHaveBeenCalledTimes(1);
  });

  it("forces a fresh session-tip capture when retrying a transient handoff failure", async () => {
    mocks.handoff.mutateAsync.mockRejectedValueOnce(new Error(
      "The checkpoint service is temporarily unavailable.",
    ));
    renderMemory();

    const sessionCard = screen.getByRole("article", {
      name: "Current Session Context",
    });
    fireEvent.click(within(sessionCard).getByRole("button", {
      name: "Preview Current Session Context",
    }));

    const dialog = await screen.findByRole("dialog", {
      name: "Current Session Context Preview",
    });
    fireEvent.click(within(dialog).getByRole("button", {
      name: "Refresh current session tip",
    }));

    await waitFor(() => expect(mocks.capture.mutateAsync).toHaveBeenCalledWith({
      workspaceId: "workspace-1",
      provider: "codex",
      sessionId: "session-1",
    }));
    await waitFor(() => expect(within(dialog).getByText(
      /SESSION_CONTEXT_ONLY/,
    )).toBeInTheDocument());
  });

  it("copies Project Context directly from its card, never audit or execution text", async () => {
    renderMemory();

    const workspaceContext = screen.getByRole("region", { name: "Workspace Context" });
    fireEvent.click(within(workspaceContext).getByRole("button", {
      name: "Copy Project Context",
    }));

    await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
      preparedContext.project_context.content,
    ));
    expect(navigator.clipboard.writeText).not.toHaveBeenCalledWith(preparedContext.markdown);
    expect(navigator.clipboard.writeText).not.toHaveBeenCalledWith(preparedContext.execution_prompt);
  });

  it("rejects Project Context whose content no longer matches its hash", async () => {
    mocks.prepare.mutateAsync.mockResolvedValue({
      ...preparedContext,
      project_context: {
        ...preparedContext.project_context,
        content: `${preparedContext.project_context.content}\nTAMPERED`,
      },
    });
    renderMemory();

    const workspaceContext = screen.getByRole("region", { name: "Workspace Context" });
    fireEvent.click(within(workspaceContext).getByRole("button", {
      name: "Copy Project Context",
    }));

    expect(await screen.findByText(
      /Project Context failed its content integrity check/,
    )).toBeInTheDocument();
    expect(navigator.clipboard.writeText).not.toHaveBeenCalled();
  });

  it("never copies Project Context that fails its worker-handoff quality gate", async () => {
    mocks.prepare.mutateAsync.mockResolvedValue({
      ...preparedContext,
      readiness: {
        ...preparedContext.readiness,
        status: "blocked",
        blocking_issues: [{
          code: "project_context_copy_definition_of_done_missing",
          message: "Project Context omits the definition of done.",
        }],
      },
      quality_report: {
        status: "blocked",
        launchable: false,
        issues: [{
          code: "project_context_copy_definition_of_done_missing",
          severity: "blocking",
          message: "Project Context omits the definition of done.",
        }],
        blocking_issues: [{
          code: "project_context_copy_definition_of_done_missing",
          severity: "blocking",
          message: "Project Context omits the definition of done.",
        }],
      },
      project_context: {
        ...preparedContext.project_context,
        copy_ready: false,
        quality_issues: [{
          code: "project_context_copy_definition_of_done_missing",
          severity: "blocking",
          message: "Project Context omits the definition of done.",
          blocks_current_execution: true,
          blocks_copy: true,
        }],
      },
    });
    renderMemory();

    const workspaceContext = screen.getByRole("region", { name: "Workspace Context" });
    fireEvent.click(within(workspaceContext).getByRole("button", {
      name: "Copy Project Context",
    }));

    await waitFor(() => expect(mocks.prepare.mutateAsync).toHaveBeenCalled());
    expect(await screen.findByText(
      /Project Context is not copy-ready.*omits the definition of done/,
    )).toBeInTheDocument();
    expect(navigator.clipboard.writeText).not.toHaveBeenCalled();
  });

  it("keeps attention records out of the simplified context-product page", () => {
    mocks.digest.data.cards = [{
      id: "routine-review-card",
      category: "agent_session",
      status: "needs_review",
      title: "Review an ordinary session summary.",
      attention_required: true,
      workspace_relevance: { status: "relevant" },
    }];
    mocks.memory.data = memoryData([
      record("unverified", "Approve an ordinary extracted claim.", {
        status: "needs_review",
        verification: "needs_review",
      }),
      ...Array.from({ length: 4 }, (_, index) => record(
        "conflicts",
        `Conflicting decision ${index + 1}`,
        { status: "conflict", verification: "needs_review" },
      )),
      record("stale", "GitHub source is stale.", {
        status: "stale",
        verification: "observed",
      }),
    ]);

    renderMemory();

    expect(screen.queryByRole("heading", { name: "Needs attention" })).not.toBeInTheDocument();
    expect(screen.queryByText("Approve an ordinary extracted claim.")).not.toBeInTheDocument();
    expect(screen.queryByText("Review an ordinary session summary.")).not.toBeInTheDocument();
    expect(screen.queryByText("Conflicting decision 1")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Inspector" })).not.toBeInTheDocument();
  });

  it("does not mix a different session into the explicit project task", async () => {
    mocks.digest.data.activity.primary = {
      ...mocks.digest.data.activity.primary,
      request: "Ship the billing settings page",
      latest_update: "Changed an unrelated billing form.",
      cwd: "/workspace/other-project",
      branch: "codex/billing",
      changed_files: ["billing/Form.jsx"],
    };

    renderMemory();

    await waitFor(() => expect(mocks.prepare.mutateAsync).toHaveBeenCalledWith({
      workspace_id: "workspace-1",
      repo_path: "/workspace/daemonstate",
      objective: "Harden checkpoint capture",
    }));
    const payload = mocks.prepare.mutateAsync.mock.calls[0][0];
    expect(payload).not.toHaveProperty("checkpoint_id");
    expect(payload).not.toHaveProperty("source_provider");
    expect(payload).not.toHaveProperty("source_session_id");
    expect(screen.getByRole("button", {
      name: "Preview Current Session Context",
    })).toBeDisabled();
    expect(screen.getByRole("region", {
      name: "Current Session Context prompt preview",
    })).toHaveTextContent("Choose a session in Library");
    expect(screen.queryByText("Changed an unrelated billing form")).not.toBeInTheDocument();
    expect(screen.queryByText("billing/Form.jsx")).not.toBeInTheDocument();
    expect(screen.queryByText("codex/billing")).not.toBeInTheDocument();
  });

  it("excludes mismatched task memory and unrelated open loops from the brief", () => {
    mocks.digest.data.current_goal = {
      ...mocks.digest.data.current_goal,
      component_id: "component-checkpoint",
    };
    mocks.digest.data.open_loops = {
      open_count: 1,
      items: [{
        id: "loop-billing",
        status: "open",
        severity: "critical",
        title: "Billing deployment is blocked",
        next_action: "Repair the billing schema",
        focus_component_id: "component-billing",
      }],
    };
    mocks.memory.data = memoryData([
      record("decisions", "Use the billing-only schema."),
      record("requirements", "Billing exports must remain CSV."),
      record("work", "Finish the billing settings page."),
      record("blockers", "Billing migration is blocked."),
    ]);
    mocks.memory.data.current_goal = {
      id: "goal-billing",
      title: "Ship the billing settings page",
    };
    mocks.memory.data.agenda = {
      id: "goal-billing",
      kind: "current_goal",
      title: "Ship the billing settings page",
    };

    renderMemory();

    expect(screen.queryByText("Use the billing-only schema")).not.toBeInTheDocument();
    expect(screen.queryByText("Billing exports must remain CSV")).not.toBeInTheDocument();
    expect(screen.queryByText("Finish the billing settings page")).not.toBeInTheDocument();
    expect(screen.queryByText("Billing migration is blocked")).not.toBeInTheDocument();
    expect(screen.queryByText("Billing deployment is blocked")).not.toBeInTheDocument();
    expect(screen.queryByText("Repair the billing schema")).not.toBeInTheDocument();
  });

  it("excludes an unassigned session from project truth", () => {
    mocks.digest.data = {
      ...digestData(),
      current_goal: null,
      activity: {
        primary: {
          ...digestData().activity.primary,
          evidence_level: "session_unassigned",
          project_match: { status: "unknown" },
        },
        recent_sessions: [],
      },
    };
    mocks.memory.data = {
      ...memoryData([]),
      current_goal: null,
      agenda: null,
    };
    mocks.checkpoint.data = null;

    renderMemory();

    expect(screen.queryByText("Implemented normalized session events")).not.toBeInTheDocument();
    expect(screen.getByRole("button", {
      name: "Preview Current Session Context",
    })).toBeDisabled();
    expect(screen.getByRole("button", {
      name: "Preview Project Context",
    })).toBeDisabled();
    expect(mocks.prepare.mutateAsync).not.toHaveBeenCalled();
    expect(mocks.handoff.mutateAsync).not.toHaveBeenCalled();
  });

  it("does not admit an unassigned session checkpoint through workspace fallback", async () => {
    mocks.digest.data.activity.primary = {
      ...mocks.digest.data.activity.primary,
      evidence_level: "session_unassigned",
      project_match: { status: "unknown" },
    };

    renderMemory();

    await waitFor(() => expect(mocks.prepare.mutateAsync).toHaveBeenCalledWith({
      workspace_id: "workspace-1",
      repo_path: "/workspace/daemonstate",
      objective: "Harden checkpoint capture",
    }));
    const payload = mocks.prepare.mutateAsync.mock.calls[0][0];
    expect(payload).not.toHaveProperty("checkpoint_id");
    expect(payload).not.toHaveProperty("source_session_id");
    expect(screen.getByRole("button", {
      name: "Preview Current Session Context",
    })).toBeDisabled();
    expect(screen.queryByText(
      "Run a real Codex continuation and inspect the resumed context",
    )).not.toBeInTheDocument();
  });

  it("auto-prepares an assigned imported session without a project checkpoint", async () => {
    mocks.digest.data = {
      ...digestData(),
      current_goal: null,
      activity: {
        primary: {
          ...digestData().activity.primary,
          evidence_level: "session_reported",
          project_match: { status: "relevant" },
        },
        recent_sessions: [],
      },
    };
    mocks.memory.data = {
      ...memoryData([]),
      current_goal: null,
      agenda: null,
    };
    mocks.checkpoint.data = null;
    mocks.prepare.mutateAsync.mockResolvedValue({
      ...preparedContext,
      source_session: {
        provider: "codex",
        session_id: "session-1",
      },
      checkpoint: null,
      manifest: {
        ...preparedContext.manifest,
        continuation: {
          ...preparedContext.manifest.continuation,
          checkpoint_id: null,
        },
      },
    });

    renderMemory();

    await waitFor(() => expect(mocks.prepare.mutateAsync).toHaveBeenCalledWith({
      workspace_id: "workspace-1",
      repo_path: "/workspace/daemonstate",
      source_provider: "codex",
      source_session_id: "session-1",
    }));
    expect(await screen.findByLabelText(
      "Project Context prompt preview content",
    )).toHaveTextContent("PROJECT_CONTEXT_ONLY");
    expect(await screen.findByLabelText(
      "Current Session Context prompt preview content",
    )).toHaveTextContent("SESSION_CONTEXT_ONLY");
  });

  it("recovers Project Context from a scoped session without promoting its generated title", async () => {
    const recoveredObjective = "Recover the source-backed task from this session.";
    const recoveredProjectContent = "# Project Context\n\nRECOVERED_FROM_SCOPED_SESSION";
    const recoveredIdentity = {
      ...preparedTaskIdentity,
      selected_objective_key: "recover the source backed task from this session",
      selected_objective_sha256: "recovered-objective-sha",
      authoritative_request_sha256: "recovered-request-sha",
      workspace_goal_id: null,
      selected_component_id: null,
    };
    mocks.digest.data = {
      ...digestData(),
      current_goal: null,
      activity: {
        primary: {
          ...digestData().activity.primary,
          request: null,
          title: "Generated session summary, not a user-authored task",
          session_title: "Generated session title",
          evidence_level: "session_reported",
          project_match: { status: "relevant" },
        },
        recent_sessions: [],
      },
    };
    mocks.memory.data = {
      ...memoryData([]),
      current_goal: null,
      agenda: null,
    };
    mocks.checkpoint.data = null;
    mocks.prepare.mutateAsync.mockResolvedValue({
      ...preparedContext,
      objective: recoveredObjective,
      source_session: {
        provider: "codex",
        session_id: "session-1",
      },
      checkpoint: null,
      project_context: {
        ...preparedContext.project_context,
        content: recoveredProjectContent,
        sha256: sha256Text(recoveredProjectContent),
      },
      task: {
        ...preparedContext.task,
        title: recoveredObjective,
        identity: recoveredIdentity,
        selected_intent: {
          ...preparedContext.task.selected_intent,
          objective: recoveredObjective,
        },
        workflow: {
          ...preparedContext.task.workflow,
          selected_intent: {
            ...preparedContext.task.workflow.selected_intent,
            objective: recoveredObjective,
          },
        },
      },
      execution_contract: {
        ...preparedContext.execution_contract,
        task_identity: recoveredIdentity,
        task: {
          request_verbatim: recoveredObjective,
        },
      },
      manifest: {
        ...preparedContext.manifest,
        objective: recoveredObjective,
        continuation: {
          ...preparedContext.manifest.continuation,
          execution_objective: recoveredObjective,
          checkpoint_id: null,
          task_identity: recoveredIdentity,
        },
      },
    });

    renderMemory();

    expect(screen.queryByText(
      "Generated session summary, not a user-authored task",
    )).not.toBeInTheDocument();
    expect(screen.getByRole("button", {
      name: "Preview Current Session Context",
    })).toBeEnabled();

    await waitFor(() => expect(mocks.prepare.mutateAsync).toHaveBeenCalledWith({
      workspace_id: "workspace-1",
      repo_path: "/workspace/daemonstate",
      source_provider: "codex",
      source_session_id: "session-1",
    }));
    expect(mocks.prepare.mutateAsync.mock.calls[0][0]).not.toHaveProperty("objective");
    expect(await screen.findByLabelText(
      "Project Context prompt preview content",
    )).toHaveTextContent("RECOVERED_FROM_SCOPED_SESSION");
  });

  it("pins a compatible source session when an authoritative goal has no checkpoint", async () => {
    mocks.checkpoint.data = null;
    mocks.prepare.mutateAsync.mockResolvedValue({
      ...preparedContext,
      source_session: {
        provider: "codex",
        session_id: "session-1",
      },
      checkpoint: null,
      manifest: {
        ...preparedContext.manifest,
        continuation: {
          ...preparedContext.manifest.continuation,
          checkpoint_id: null,
        },
      },
    });

    renderMemory();

    await waitFor(() => expect(mocks.prepare.mutateAsync).toHaveBeenCalledWith({
      workspace_id: "workspace-1",
      repo_path: "/workspace/daemonstate",
      source_provider: "codex",
      source_session_id: "session-1",
    }));
    expect(await screen.findByLabelText(
      "Project Context prompt preview content",
    )).toHaveTextContent("PROJECT_CONTEXT_ONLY");
    expect(screen.queryByRole("link", { name: /Continue/ })).not.toBeInTheDocument();
  });

  it("does not claim unknown verification outcomes passed in the simplified page", () => {
    mocks.digest.data.activity.primary.verification = {
      observed: 3,
      passed: 0,
      failed: 0,
    };

    renderMemory();

    expect(screen.queryByText("3 observed verification checks · 3 outcomes unknown")).not.toBeInTheDocument();
    expect(screen.queryByText("3 observed verification checks passed")).not.toBeInTheDocument();
  });

  it("keeps failed verification out of the removed status hero while compiling the scoped task", async () => {
    mocks.digest.data.activity.primary.verification = {
      observed: 1,
      passed: 0,
      failed: 1,
    };
    mocks.checkpoint.data = {
      ...checkpointData(),
      sections: {
        ...checkpointData().sections,
        blockers: [],
      },
    };

    renderMemory();

    await waitFor(() => expect(mocks.prepare.mutateAsync).toHaveBeenCalledWith({
      workspace_id: "workspace-1",
      repo_path: "/workspace/daemonstate",
      checkpoint_id: "checkpoint-1",
    }));
    expect(screen.queryByText("Verification failed")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Continue/ })).not.toBeInTheDocument();
  });

  it.each([
    ["active", "Work is still in progress.", "running"],
    ["failed", "The continuation run failed.", "failed"],
  ])("does not present the removed Last completed panel for a %s-state outcome", (state, summary, status) => {
    mocks.digest.data.activity.primary = {
      ...mocks.digest.data.activity.primary,
      state,
      latest_update: summary,
      outcome: {
        summary,
        status,
        observed_at: "2026-07-21T10:00:00Z",
      },
    };

    renderMemory();

    expect(screen.queryByText("Last completed")).not.toBeInTheDocument();
    expect(screen.queryByText(summary)).not.toBeInTheDocument();
    expect(screen.queryByText("Run in progress")).not.toBeInTheDocument();
    expect(screen.queryByText("Latest run needs review")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Continue/ })).not.toBeInTheDocument();
  });

  it("filters inactive and weak checkpoint claims and flags stale verification", () => {
    mocks.memory.data = memoryData([]);
    mocks.checkpoint.data = {
      ...checkpointData(),
      verification: { status: "stale" },
      sections: {
        ...checkpointData().sections,
        blockers: [{
          ...checkpointData().sections.blockers[0],
          state: "resolved",
        }],
        decisions: [
          {
            ...checkpointData().sections.decisions[0],
            statement: "A superseded checkpoint decision.",
            state: "superseded",
          },
          {
            ...checkpointData().sections.decisions[0],
            statement: "An agent-reported checkpoint decision.",
            truth_state: "reported",
          },
          {
            ...checkpointData().sections.decisions[0],
            statement: "A human-confirmed checkpoint decision.",
            truth_state: "user_stated",
          },
        ],
      },
    };

    renderMemory();

    expect(screen.queryByText("No confirmed blocker.")).not.toBeInTheDocument();
    expect(screen.queryByText("A human-confirmed checkpoint decision")).not.toBeInTheDocument();
    expect(screen.queryByText("A superseded checkpoint decision")).not.toBeInTheDocument();
    expect(screen.queryByText("An agent-reported checkpoint decision")).not.toBeInTheDocument();
    expect(screen.queryByText("Focused checkpoint tests passed")).not.toBeInTheDocument();
    expect(screen.queryByText("Ready to continue")).not.toBeInTheDocument();
  });

  it("previews and copies only the Project Context while keeping audit data advanced", async () => {
    renderMemory();

    await waitFor(() => expect(mocks.prepare.mutateAsync).toHaveBeenCalledWith({
      workspace_id: "workspace-1",
      repo_path: "/workspace/daemonstate",
      checkpoint_id: "checkpoint-1",
    }));
    expect(mocks.prepare.mutateAsync).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("region", {
      name: "Project Context prompt preview",
    })).toHaveTextContent("PROJECT_CONTEXT_ONLY");
    const previewTrigger = screen.getByRole("button", { name: "Preview Project Context" });
    expect(previewTrigger).toHaveTextContent("Open full preview");
    fireEvent.click(previewTrigger);

    const dialog = await screen.findByRole("dialog", { name: "Project Context Preview" });
    expect(within(dialog).getByText("Verified parent projection")).toBeInTheDocument();
    expect(within(dialog).getByText("continuation_staging_context.v1")).toBeInTheDocument();
    expect(within(dialog).getByText(/Run the real Codex continuation/)).toBeInTheDocument();
    expect(within(dialog).getByText(/PROJECT_CONTEXT_ONLY/)).toBeInTheDocument();
    expect(screen.getByRole("region", {
      name: "Project Context prompt preview",
    })).toHaveTextContent("PROJECT_CONTEXT_ONLY");

    const advanced = within(dialog).getByText("Advanced audit details").closest("details");
    expect(advanced).not.toHaveAttribute("open");
    fireEvent.click(within(dialog).getByText("Advanced audit details"));
    expect(advanced).toHaveAttribute("open");
    expect(within(dialog).getByText(/AUDIT_MARKDOWN_MUST_NOT_BE_COPIED/)).toBeInTheDocument();
    expect(within(dialog).getByText("Raw test stdout")).toBeInTheDocument();
    expect(within(dialog).getByText("low signal")).toBeInTheDocument();

    const close = within(dialog).getByRole("button", { name: "Close Project Context Preview" });
    expect(close).toHaveFocus();
    fireEvent.keyDown(window, { key: "Tab", shiftKey: true });
    const auditMarkdown = within(dialog).getByLabelText("Advanced audit markdown");
    expect(auditMarkdown).toHaveFocus();
    const copy = within(dialog).getByRole("button", { name: "Copy Project Context" });
    fireEvent.click(copy);
    await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
      preparedContext.project_context.content,
    ));
    expect(navigator.clipboard.writeText).not.toHaveBeenCalledWith(preparedContext.markdown);
    expect(navigator.clipboard.writeText).not.toHaveBeenCalledWith(preparedContext.execution_prompt);
    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog", {
      name: "Project Context Preview",
    })).not.toBeInTheDocument());
    await waitFor(() => expect(previewTrigger).toHaveFocus());
  });

  it("recovers the lossless checkpoint request without resending its display goal or dropping images", async () => {
    const displayGoal = "Continue the saved visual-context task. ".padEnd(174, "x");
    const fullRequest = (
      `${displayGoal}\n`
      + "Preserve the complete user-authored task and all three attached visual references. "
    ).padEnd(687, "y");
    const artifacts = [1, 2, 3].map((index) => ({
      id: `A${index}`,
      kind: "screenshot",
      path: `/tmp/reference-${index}.png`,
      sha256: String(index).repeat(64),
      mime_type: "image/png",
      required: true,
      available: true,
      requirement_ids: [`R${index + 1}`],
    }));
    const losslessIdentity = {
      ...preparedTaskIdentity,
      selected_objective_key: "continue the saved visual context task",
      selected_objective_sha256: "display-goal-sha",
      authoritative_request_sha256: "lossless-request-sha",
    };
    mocks.digest.data.current_goal.title = displayGoal;
    mocks.digest.data.activity.primary.request = displayGoal;
    mocks.memory.data.current_goal.title = displayGoal;
    mocks.memory.data.agenda.title = displayGoal;
    mocks.checkpoint.data.sections.goal[0].statement = displayGoal;
    mocks.prepare.mutateAsync.mockResolvedValue({
      ...preparedContext,
      objective: fullRequest,
      task: {
        ...preparedContext.task,
        title: fullRequest,
        identity: losslessIdentity,
        selected_intent: {
          ...preparedContext.task.selected_intent,
          objective: fullRequest,
        },
        workflow: {
          ...preparedContext.task.workflow,
          selected_intent: {
            ...preparedContext.task.workflow.selected_intent,
            objective: fullRequest,
          },
        },
      },
      execution_contract: {
        ...preparedContext.execution_contract,
        task_identity: losslessIdentity,
        task: { request_verbatim: fullRequest },
        artifacts,
      },
      manifest: {
        ...preparedContext.manifest,
        objective: fullRequest,
        continuation: {
          ...preparedContext.manifest.continuation,
          execution_objective: fullRequest,
          task_identity: losslessIdentity,
          artifacts,
        },
      },
    });

    renderMemory();

    await waitFor(() => expect(mocks.prepare.mutateAsync).toHaveBeenCalledWith({
      workspace_id: "workspace-1",
      repo_path: "/workspace/daemonstate",
      checkpoint_id: "checkpoint-1",
    }));
    expect(mocks.prepare.mutateAsync.mock.calls[0][0]).not.toHaveProperty("objective");
    fireEvent.click(screen.getByRole("button", { name: "Preview Project Context" }));
    expect(await screen.findByRole("dialog", {
      name: "Project Context Preview",
    })).toBeInTheDocument();
  });

  it("fails closed when compilation drops a source-bound attachment", async () => {
    const artifact = {
      id: "A1",
      kind: "screenshot",
      path: "/tmp/reference.png",
      sha256: "a".repeat(64),
      required: true,
      available: true,
      requirement_ids: ["R2"],
    };
    mocks.prepare.mutateAsync.mockResolvedValue({
      ...preparedContext,
      execution_contract: {
        ...preparedContext.execution_contract,
        artifacts: [],
      },
      manifest: {
        ...preparedContext.manifest,
        continuation: {
          ...preparedContext.manifest.continuation,
          artifacts: [artifact],
        },
      },
    });

    renderMemory();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "compiler dropped a referenced attachment",
    );
    expect(screen.getByRole("button", {
      name: "Preview Project Context",
    })).toBeDisabled();
  });

  it("preserves the authoritative objective verbatim when preparing context", async () => {
    const exactObjective = "Fix `api/v1` timeout: preserve exact input.";
    mocks.digest.data.current_goal.title = exactObjective;
    mocks.digest.data.activity.primary.request = exactObjective;
    delete mocks.digest.data.activity.primary.session_id;
    mocks.memory.data.current_goal.title = exactObjective;
    mocks.memory.data.agenda.title = exactObjective;
    mocks.checkpoint.data = null;
    const exactIdentity = {
      ...preparedTaskIdentity,
      selected_objective_key: "fix api v1 timeout preserve exact input",
      selected_objective_sha256: "exact-objective-sha",
      authoritative_request_sha256: "exact-request-sha",
    };
    mocks.prepare.mutateAsync.mockResolvedValue({
      ...preparedContext,
      objective: exactObjective,
      checkpoint: null,
      task: {
        ...preparedContext.task,
        title: exactObjective,
        identity: exactIdentity,
        selected_intent: {
          ...preparedContext.task.selected_intent,
          objective: exactObjective,
        },
        workflow: {
          ...preparedContext.task.workflow,
          selected_intent: {
            ...preparedContext.task.workflow.selected_intent,
            objective: exactObjective,
          },
        },
      },
      execution_contract: {
        ...preparedContext.execution_contract,
        task_identity: exactIdentity,
        task: {
          request_verbatim: exactObjective,
        },
      },
      manifest: {
        ...preparedContext.manifest,
        objective: exactObjective,
        continuation: {
          ...preparedContext.manifest.continuation,
          execution_objective: exactObjective,
          checkpoint_id: null,
          task_identity: exactIdentity,
        },
      },
    });
    renderMemory();

    await waitFor(() => expect(mocks.prepare.mutateAsync).toHaveBeenCalledWith({
      workspace_id: "workspace-1",
      repo_path: "/workspace/daemonstate",
      objective: exactObjective,
    }));
    fireEvent.click(screen.getByRole("button", { name: "Preview Project Context" }));
    expect(await screen.findByRole("dialog", { name: "Project Context Preview" })).toBeInTheDocument();
  });

  it("does not sanitize Context labels while validating the canonical task identity", async () => {
    const exactObjective = (
      "DaemonState should send three things together: "
      + "Context:** What happened, decisions, files, failures, current state."
    );
    const exactIdentity = {
      ...preparedTaskIdentity,
      selected_objective_key: (
        "daemonstate should send three things together "
        + "context what happened decisions files failures current state"
      ),
      selected_objective_sha256: "context-label-objective-sha",
      authoritative_request_sha256: "context-label-request-sha",
    };
    mocks.digest.data.current_goal.title = exactObjective;
    mocks.digest.data.activity.primary.request = exactObjective;
    delete mocks.digest.data.activity.primary.session_id;
    mocks.memory.data.current_goal.title = exactObjective;
    mocks.memory.data.agenda.title = exactObjective;
    mocks.checkpoint.data = null;
    mocks.prepare.mutateAsync.mockResolvedValue({
      ...preparedContext,
      objective: exactObjective,
      checkpoint: null,
      task: {
        ...preparedContext.task,
        title: exactObjective,
        identity: exactIdentity,
        selected_intent: {
          ...preparedContext.task.selected_intent,
          objective: exactObjective,
        },
        workflow: {
          ...preparedContext.task.workflow,
          selected_intent: {
            ...preparedContext.task.workflow.selected_intent,
            objective: exactObjective,
          },
        },
      },
      execution_contract: {
        ...preparedContext.execution_contract,
        task_identity: exactIdentity,
        task: {
          request_verbatim: exactObjective,
        },
      },
      manifest: {
        ...preparedContext.manifest,
        objective: exactObjective,
        continuation: {
          ...preparedContext.manifest.continuation,
          execution_objective: exactObjective,
          checkpoint_id: null,
          task_identity: exactIdentity,
        },
      },
    });
    renderMemory();

    await waitFor(() => expect(mocks.prepare.mutateAsync).toHaveBeenCalledWith(
      expect.objectContaining({ objective: exactObjective }),
    ));
    fireEvent.click(screen.getByRole("button", {
      name: "Preview Project Context",
    }));
    expect(await screen.findByRole("dialog", {
      name: "Project Context Preview",
    })).toBeInTheDocument();
    expect(screen.queryByText(/belongs to a different task/i)).not.toBeInTheDocument();
  });

  it("rejects a compiler response whose execution contract carries a split task identity", async () => {
    mocks.prepare.mutateAsync.mockResolvedValue({
      ...preparedContext,
      execution_contract: {
        ...preparedContext.execution_contract,
        task_identity: {
          ...preparedTaskIdentity,
          id: "different-contract-task",
        },
      },
    });
    renderMemory();

    fireEvent.click(screen.getAllByRole("button", {
      name: "Preview Project Context",
    })[0]);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "compiler returned an incomplete continuation context",
    );
  });

  it("rejects an incomplete or cross-task compiler response", async () => {
    mocks.checkpoint.data = null;
    delete mocks.digest.data.activity.primary.session_id;
    const unrelatedIdentity = {
      ...preparedTaskIdentity,
      selected_objective_key: "ship an unrelated task",
      selected_objective_sha256: "unrelated-objective-sha",
      authoritative_request_sha256: "unrelated-request-sha",
    };
    mocks.prepare.mutateAsync.mockResolvedValue({
      ...preparedContext,
      objective: "Ship an unrelated task",
      checkpoint: null,
      task: {
        ...preparedContext.task,
        title: "Ship an unrelated task",
        identity: unrelatedIdentity,
        selected_intent: {
          ...preparedContext.task.selected_intent,
          objective: "Ship an unrelated task",
        },
        workflow: {
          ...preparedContext.task.workflow,
          selected_intent: {
            ...preparedContext.task.workflow.selected_intent,
            objective: "Ship an unrelated task",
          },
        },
      },
      execution_contract: {
        ...preparedContext.execution_contract,
        task_identity: unrelatedIdentity,
        task: {
          request_verbatim: "Ship an unrelated task",
        },
      },
      manifest: {
        ...preparedContext.manifest,
        objective: "Ship an unrelated task",
        continuation: {
          ...preparedContext.manifest.continuation,
          execution_objective: "Ship an unrelated task",
          checkpoint_id: null,
          task_identity: unrelatedIdentity,
        },
      },
    });
    renderMemory();

    expect(await screen.findByText(
      "The compiled context belongs to a different task.",
    )).toBeInTheDocument();
    expect(screen.queryByText(/Run the real Codex continuation/)).not.toBeInTheDocument();
  });

  it("accepts and discloses an unfinished prerequisite that switches source and checkpoint", async () => {
    mocks.prepare.mutateAsync.mockResolvedValue({
      ...preparedContext,
      objective: "Repair the checkpoint database migration",
      task: {
        ...preparedContext.task,
        title: "Repair the checkpoint database migration",
        execution_task: {
          id: "task-prerequisite",
          title: "Repair the checkpoint database migration",
          objective: "Repair the checkpoint database migration",
        },
        workflow: {
          ...preparedContext.task.workflow,
          execution_reason: "unfinished_prerequisite",
          execution_task: {
            id: "task-prerequisite",
            title: "Repair the checkpoint database migration",
            objective: "Repair the checkpoint database migration",
          },
        },
      },
      source_session: {
        provider: "opencode",
        session_id: "prerequisite-session",
      },
      checkpoint: {
        ...preparedContext.checkpoint,
        id: "checkpoint-prerequisite",
      },
      manifest: {
        ...preparedContext.manifest,
        objective: "Repair the checkpoint database migration",
        continuation: {
          ...preparedContext.manifest.continuation,
          execution_objective: "Repair the checkpoint database migration",
          checkpoint_id: "checkpoint-prerequisite",
        },
      },
    });
    renderMemory();

    fireEvent.click(screen.getAllByRole("button", { name: "Preview Project Context" })[0]);

    const dialog = await screen.findByRole("dialog", { name: "Project Context Preview" });
    expect(within(dialog).getByText(/starts with the unfinished prerequisite/)).toHaveTextContent(
      "Repair the checkpoint database migration",
    );
    expect(within(dialog).getByText(/starts with the unfinished prerequisite/)).toHaveTextContent(
      "Harden checkpoint capture",
    );
    expect(within(dialog).getByText(/starts with the unfinished prerequisite/)).toHaveTextContent(
      "different checkpoint or source session",
    );
  });

  it("discloses blocked compiler readiness in the full preview without the removed hero", async () => {
    mocks.prepare.mutateAsync.mockResolvedValue({
      ...preparedContext,
      readiness: {
        ...preparedContext.readiness,
        status: "blocked",
        blocking_issues: [{
          code: "repository_changed",
          message: "Repository state changed.",
          blocks_current_execution: true,
        }],
      },
    });
    renderMemory();

    fireEvent.click(screen.getAllByRole("button", { name: "Preview Project Context" })[0]);

    const dialog = await screen.findByRole("dialog", { name: "Project Context Preview" });
    expect(within(dialog).getByText(/Compiler readiness: Blocked/)).toBeInTheDocument();
    expect(screen.queryByText("Continuation blocked")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Review compiled context" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Continue with project context/ })).not.toBeInTheDocument();
  });

  it("shows changed repository freshness in the preview without the removed readiness hero", async () => {
    mocks.prepare.mutateAsync.mockResolvedValue({
      ...preparedContext,
      repository: {
        ...preparedContext.repository,
        freshness: {
          status: "changed",
          reason: "The worktree fingerprint changed after checkpoint capture.",
        },
      },
    });
    renderMemory();

    fireEvent.click(screen.getAllByRole("button", { name: "Preview Project Context" })[0]);

    const dialog = await screen.findByRole("dialog", { name: "Project Context Preview" });
    expect(within(dialog).getByText("Changed")).toBeInTheDocument();
    expect(screen.queryByText("Continuation blocked")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Review compiled context" })).not.toBeInTheDocument();
    expect(screen.queryByText("Ready to continue")).not.toBeInTheDocument();
  });

  it.each([
    [
      "repository",
      {
        ...preparedContext,
        repository: {
          ...preparedContext.repository,
          path: "/workspace/different-project",
        },
      },
      "compiled context belongs to a different repository",
    ],
    [
      "checkpoint",
      {
        ...preparedContext,
        checkpoint: {
          ...preparedContext.checkpoint,
          id: "checkpoint-other",
        },
        manifest: {
          ...preparedContext.manifest,
          continuation: {
            ...preparedContext.manifest.continuation,
            checkpoint_id: "checkpoint-other",
          },
        },
      },
      "compiled context belongs to a different checkpoint",
    ],
  ])("rejects a same-task response anchored to another %s", async (_kind, result, message) => {
    mocks.prepare.mutateAsync.mockResolvedValue(result);
    renderMemory();

    fireEvent.click(screen.getAllByRole("button", { name: "Preview Project Context" })[0]);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(message);
  });

  it("rejects a same-task response from another source session", async () => {
    mocks.digest.data = {
      ...digestData(),
      current_goal: null,
      activity: {
        primary: {
          ...digestData().activity.primary,
          evidence_level: "session_reported",
          project_match: { status: "relevant" },
        },
        recent_sessions: [],
      },
    };
    mocks.memory.data = {
      ...memoryData([]),
      current_goal: null,
      agenda: null,
    };
    mocks.checkpoint.data = null;
    mocks.prepare.mutateAsync.mockResolvedValue({
      ...preparedContext,
      source_session: {
        provider: "codex",
        session_id: "another-session",
      },
    });
    renderMemory();

    await waitFor(() => expect(mocks.prepare.mutateAsync).toHaveBeenCalledWith({
      workspace_id: "workspace-1",
      repo_path: "/workspace/daemonstate",
      source_provider: "codex",
      source_session_id: "session-1",
    }));
    expect(await screen.findByText(
      "The compiled context belongs to a different source session.",
    )).toBeInTheDocument();
  });

  it("labels partial live data without restoring removed summary claims", () => {
    mocks.memory.data = memoryData([]);
    mocks.memory.isError = true;
    mocks.checkpoint.data = null;
    mocks.digest.data.activity.primary.verification = {
      observed: 0,
      passed: 0,
      failed: 0,
    };
    mocks.digest.data.activity.primary.outcome = null;
    mocks.digest.data.activity.primary.changed_files = [];

    renderMemory();

    expect(screen.getByRole("status")).toHaveTextContent(
      "Some live context is temporarily unavailable",
    );
    expect(screen.queryByRole("heading", { name: "What matters now" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Needs attention" })).not.toBeInTheDocument();
    expect(screen.queryByText("No confirmed blocker.")).not.toBeInTheDocument();
    expect(screen.queryByText("No conflict affecting continuation")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Continue and reconcile context/ })).not.toBeInTheDocument();
  });

  it("labels a failed scoped checkpoint lookup without restoring attention UI", () => {
    mocks.checkpoint.data = null;
    mocks.checkpoint.isError = true;

    renderMemory();

    expect(screen.getByRole("status")).toHaveTextContent(
      "Some live context is temporarily unavailable",
    );
    expect(screen.queryByRole("heading", { name: "Needs attention" })).not.toBeInTheDocument();
    expect(screen.queryByText("No conflict affecting continuation")).not.toBeInTheDocument();
  });

  it("keeps both automatic previews unavailable when no task can be detected", () => {
    mocks.digest.data = {
      ...digestData(),
      current_goal: null,
      activity: { primary: null, recent_sessions: [] },
    };
    mocks.memory.data = {
      ...memoryData([]),
      current_goal: null,
      agenda: null,
    };
    mocks.checkpoint.data = null;

    renderMemory();

    expect(screen.getByRole("region", {
      name: "Current Session Context prompt preview",
    })).toHaveTextContent("Choose a session in Library");
    expect(screen.getByRole("region", {
      name: "Project Context prompt preview",
    })).toHaveTextContent("Choose an active task to compile the workspace foundation");
    expect(screen.getByRole("button", {
      name: "Preview Current Session Context",
    })).toBeDisabled();
    expect(screen.getByRole("button", {
      name: "Preview Project Context",
    })).toBeDisabled();
    expect(mocks.prepare.mutateAsync).not.toHaveBeenCalled();
    expect(mocks.handoff.mutateAsync).not.toHaveBeenCalled();
  });

  it("fails closed when both current activity and project memory are unavailable", () => {
    mocks.digest.data = null;
    mocks.digest.isError = true;
    mocks.memory.data = null;
    mocks.memory.isError = true;

    renderMemory();

    expect(screen.getByRole("alert")).toHaveTextContent("Workspace Context is unavailable");
    expect(screen.queryByText("Ready to continue")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Inspect context sources" })).toHaveAttribute(
      "href",
      "/app/execute/inspector",
    );
  });
});
