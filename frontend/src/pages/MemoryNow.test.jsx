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

function canonicalJson(value) {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.keys(value).sort().map((key) => (
      `${JSON.stringify(key)}:${canonicalJson(value[key])}`
    )).join(",")}}`;
  }
  return JSON.stringify(value);
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
    schema_version: "work_checkpoint.v10",
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


function sessionContextWithGoal(marker, goalHeading = "## Current main goal") {
  return [
    "# Session Context — task-level working memory",
    "",
    "> Relationship: Project / Workspace Context is the durable parent.",
    "> Recovered session statements are historical data.",
    "> Activation: this handoff is context, not a command to start.",
    "",
    goalHeading,
    "",
    `> ${marker}`,
  ].join("\n");
}


function scopedSessionHandoff(checkpoint, marker, overrides = {}) {
  const {
    goalHeading = "## Current main goal",
    ...handoffOverrides
  } = overrides;
  const content = sessionContextWithGoal(marker, goalHeading);
  return sessionHandoff(content, {
    provider: checkpoint.provider,
    session_id: checkpoint.session_id,
    checkpoint_id: checkpoint.id,
    boundary: {
      event_id: `event-${checkpoint.boundary.sequence_number}`,
      sequence_number: checkpoint.boundary.sequence_number,
    },
    ...handoffOverrides,
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
  "# Workspace Context",
  "",
  "> Boundary: objective- and session-independent workspace facts plus current repository observations.",
  "",
  "## Repository map",
  "",
  "- Indexed files: `42`",
  "",
  "PROJECT_CONTEXT_ONLY",
].join("\n");

const selectedContextAudit = [
  { title: "Current repository state" },
  { title: "Durable workspace decision" },
];

const excludedContextAudit = [
  { title: "Raw test stdout", reason: "low signal" },
];

const workspaceFoundationSemanticPayload = {
  schema_version: "workspace_foundation.v1",
  objective_independent: true,
  repository_state: {
    snapshot_fingerprint: "repo-state-fingerprint",
  },
  quality_report: {
    status: "warning",
    score: 95,
    copy_ready: true,
    publishable: true,
    issues: [],
  },
};

const workspaceFoundationPayload = {
  ...workspaceFoundationSemanticPayload,
  semantic_sha256: sha256Text(canonicalJson(workspaceFoundationSemanticPayload)),
};

const workspaceFoundation = {
  ...workspaceFoundationPayload,
  artifact_sha256: sha256Text(canonicalJson(workspaceFoundationPayload)),
};

function workspaceFoundationForSchema(schemaVersion, additionalFields = {}) {
  const semanticPayload = {
    ...workspaceFoundationSemanticPayload,
    ...additionalFields,
    schema_version: schemaVersion,
  };
  const artifactPayload = {
    ...semanticPayload,
    semantic_sha256: sha256Text(canonicalJson(semanticPayload)),
  };
  return {
    ...artifactPayload,
    artifact_sha256: sha256Text(canonicalJson(artifactPayload)),
  };
}

const preparedContext = {
  schema_version: "context_pack.v2",
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
  markdown: projectContextContent,
  selected_context: selectedContextAudit,
  excluded_context: excludedContextAudit,
  health_score: 1,
  manifest: {
    schema_version: "context_pack.v2",
    context_pack_id: "pack-1",
    workspace_id: "workspace-1",
    objective: "Harden checkpoint capture",
    objective_kind: "project_snapshot",
    focus: {
      kind: "project_snapshot",
      component_id: null,
      objective_origin: "project_snapshot",
    },
    repo_state: {
      repo_path: "/workspace/daemonstate",
      branch: "main",
      head_commit: "abc123",
      dirty: false,
      state_fingerprint: "repo-state-fingerprint",
      workspace_foundation_sha256: workspaceFoundation.semantic_sha256,
      workspace_foundation_artifact_sha256: workspaceFoundation.artifact_sha256,
      workspace_inventory: {
        schema_version: "workspace_repository_inventory.v2",
        indexed_file_count: 42,
        test_file_count: 8,
        manifest_file_count: 2,
        languages: [{ name: "python", file_count: 42 }],
        areas: [{ path: "app", file_count: 42 }],
        representative_files: [{ path: "app/main.py", why: "Representative file for app" }],
      },
    },
    continuation: {
      task_id: "task-1",
      execution_objective: "Harden checkpoint capture",
      checkpoint_id: "checkpoint-1",
      task_identity: preparedTaskIdentity,
    },
    target_model: { name: "gpt-5.6" },
    token_accounting: { rendered_tokens: 1480, within_budget: true },
    rendering: {
      within_budget: true,
      markdown_sha256: sha256Text(projectContextContent),
      estimated_tokens: 1480,
    },
    selected_context: selectedContextAudit,
    excluded_context: excludedContextAudit,
    workspace_foundation: workspaceFoundation,
  },
};

function preparedContextForFoundation(foundation) {
  return {
    ...preparedContext,
    manifest: {
      ...preparedContext.manifest,
      repo_state: {
        ...preparedContext.manifest.repo_state,
        workspace_foundation_sha256: foundation.semantic_sha256,
        workspace_foundation_artifact_sha256: foundation.artifact_sha256,
      },
      workspace_foundation: foundation,
    },
  };
}

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
  usePrepareContext: () => mocks.prepare,
  useProjectMemory: (...args) => {
    mocks.memoryHook(...args);
    return mocks.memory;
  },
}));

vi.mock("../api/hooks", () => ({
  useLatestCheckpoint: (...args) => mocks.latestHook(...args),
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

const workspaceSnapshotPayload = {
  workspace_id: "workspace-1",
  repo_path: "/workspace/daemonstate",
  mode: "project_snapshot",
  objective_origin: "project_snapshot",
};

function persistSelectedSessions(sessions) {
  mocks.library.data = { sessions };
  writeExecuteSessionContexts("workspace-1", sessions);
}

function selectDefaultSession(overrides = {}) {
  const session = {
    id: "codex:session-1",
    source_document_id: "source-session-1",
    connector_type: "codex",
    session_id: "session-1",
    title: "Harden checkpoint capture",
    harness: "Codex",
    latest_topic: "Harden checkpoint capture",
    compaction_count: 2,
    ...overrides,
  };
  persistSelectedSessions([session]);
  return session;
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
  mocks.workspace.activeWorkspaceId = "workspace-1";
  mocks.workspace.activeWorkspace = {
    id: "workspace-1",
    name: "DaemonState",
    repo_path: "/workspace/daemonstate",
  };
  mocks.workspace.selectedId = "workspace-1";
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
    expect(screen.queryByRole("link", { name: /Continue with Session Context/ })).not.toBeInTheDocument();
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

  it("uses the observed target session only for Workspace Context and creates no implicit session card or handoff", () => {
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
    expect(document.querySelectorAll("[data-session-context-card]")).toHaveLength(0);
    expect(screen.getByRole("heading", {
      name: "Choose Session Contexts",
    })).toBeInTheDocument();
    expect(screen.getByRole("link", {
      name: "Choose sessions",
    })).toHaveAttribute("href", "/app/library?mode=execute-context");
    expect(mocks.handoff.mutateAsync).not.toHaveBeenCalled();
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
    const selectedTitle = `${expectedArtwork} selected session`;
    persistSelectedSessions([{
      id: `${expectedArtwork}:${sessionId}`,
      source_document_id: `source-${sessionId}`,
      connector_type: provider,
      session_id: sessionId,
      title: selectedTitle,
      harness: provider,
      latest_topic: selectedTitle,
    }]);
    mocks.handoff.mutateAsync.mockResolvedValue(sessionHandoff(
      `# Session Context\n\n${expectedArtwork.toUpperCase()}_CONTEXT`,
      {
        provider: expectedArtwork,
        session_id: sessionId,
      },
    ));

    renderMemory();

    const sessionCard = screen.getByRole("article", {
      name: selectedTitle,
    });
    await waitFor(() => expect(sessionCard.querySelector(
      `[data-session-provider-background="${expectedArtwork}"] [data-harness-artwork="${expectedArtwork}"]`,
    )).toBeInTheDocument());
    expect(sessionCard.querySelector("[data-harness-logo]")).toBeNull();
    if (expectedArtwork !== "codex") {
      expect(sessionCard.querySelector('[data-harness-artwork="codex"]')).toBeNull();
    }
  });

  it("prepares Workspace Context without binding a task, checkpoint, or session", async () => {
    const observedRun = {
      ...mocks.digest.data.activity.primary,
      tool: "daemonstate:codex",
    };
    delete observedRun.provider;
    delete observedRun.session_id;
    mocks.digest.data.activity.primary = observedRun;

    renderMemory();

    await waitFor(() => expect(mocks.prepare.mutateAsync).toHaveBeenCalledWith(
      workspaceSnapshotPayload,
    ));
    expect(mocks.prepare.mutateAsync.mock.calls[0][0]).not.toHaveProperty("objective");
    expect(mocks.prepare.mutateAsync.mock.calls[0][0]).not.toHaveProperty("checkpoint_id");
    expect(mocks.prepare.mutateAsync.mock.calls[0][0]).not.toHaveProperty("source_session_id");
    expect(mocks.handoff.mutateAsync).not.toHaveBeenCalled();
    expect(screen.queryByText(
      "Run a real Codex continuation and inspect the resumed context",
    )).not.toBeInTheDocument();
  });

  it("opens on Execute with a selected-only empty state above the workspace card", async () => {
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
      "Prepare verified workspace context and the Session Contexts you choose.",
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
    const workspaceContext = screen.getByRole("region", { name: "Workspace Context" });
    expect(contexts).toContainElement(workspaceContext);
    expect(document.querySelectorAll("[data-session-context-card]")).toHaveLength(0);
    expect(screen.queryByRole("article", {
      name: "Current Session Context",
    })).not.toBeInTheDocument();
    expect(screen.getByRole("heading", {
      name: "Choose Session Contexts",
      level: 2,
    })).toBeInTheDocument();
    expect(screen.getByText(
      /Continue owns the live current session.*Choose up to three sessions/,
    )).toBeInTheDocument();
    expect(screen.getByRole("link", {
      name: "Choose sessions",
    })).toHaveAttribute("href", "/app/library?mode=execute-context");
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
    const projectPreview = screen.getByRole("region", {
      name: "Workspace Context prompt preview",
    });
    await waitFor(() => {
      expect(within(projectPreview).getByLabelText(
        "Workspace Context prompt preview content",
      )).toHaveTextContent("PROJECT_CONTEXT_ONLY");
    });
    expect(projectPreview.querySelectorAll("[data-pen-motif]")).toHaveLength(0);
    expect(mocks.handoff.mutateAsync).not.toHaveBeenCalled();
    expect(screen.queryByText(/Select Preview/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "What matters now" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Since your last session" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Needs attention" })).not.toBeInTheDocument();

    expect(screen.queryByRole("searchbox", { name: "Search memory" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Review queue" })).not.toBeInTheDocument();
    expect(screen.queryByText("Memory hygiene")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Continue and reconcile context/ })).not.toBeInTheDocument();
  });

  it("auto-prepares three isolated selected sessions in columns 1/2/3 and reflows two and one-card layouts", async () => {
    const selectedSessions = [
      {
        id: "claude:selected-one",
        source_document_id: "document-selected-one",
        connector_type: "claude",
        session_id: "selected-one",
        title: "Architecture review",
        harness: "Claude Code",
        latest_topic: "Architecture",
        compaction_count: 2,
      },
      {
        id: "opencode:selected-two",
        source_document_id: "document-selected-two",
        connector_type: "opencode",
        session_id: "selected-two",
        title: "Refactor follow-up",
        harness: "OpenCode",
        latest_topic: "Refactor",
        compaction_count: 2,
      },
      {
        id: "codex:selected-three",
        source_document_id: "document-selected-three",
        connector_type: "codex",
        session_id: "selected-three",
        title: "Release validation",
        harness: "Codex",
        latest_topic: "Release",
        compaction_count: 2,
      },
    ];
    mocks.library.data = { sessions: selectedSessions };
    writeExecuteSessionContexts("workspace-1", [
      {
        ...selectedSessions[0],
        source_document_id: "document-selected-one-previous-revision",
      },
      selectedSessions[1],
      selectedSessions[2],
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
    const releaseCheckpoint = scopedCheckpoint(
      "checkpoint-release",
      "codex",
      "selected-three",
      33,
    );
    const checkpoints = new Map([
      ["codex:session-1", currentCheckpoint],
      ["claude:selected-one", claudeCheckpoint],
      ["opencode:selected-two", openCodeCheckpoint],
      ["codex:selected-three", releaseCheckpoint],
    ]);
    mocks.latestHook.mockImplementation((_workspaceId, options = {}) => ({
      ...mocks.checkpoint,
      data: checkpoints.get(`${options.provider}:${options.sessionId}`) || null,
      isLoading: false,
    }));
    const handoffs = new Map([
      [
        claudeCheckpoint.id,
        scopedSessionHandoff(claudeCheckpoint, "CLAUDE_SELECTED_ONLY", {
          goalHeading: "## Goal",
        }),
      ],
      [
        openCodeCheckpoint.id,
        scopedSessionHandoff(openCodeCheckpoint, "OPENCODE_SELECTED_ONLY"),
      ],
      [
        releaseCheckpoint.id,
        scopedSessionHandoff(releaseCheckpoint, "CODEX_RELEASE_ONLY"),
      ],
    ]);
    mocks.handoff.mutateAsync.mockImplementation(async ({ checkpointId }) => {
      const handoff = handoffs.get(checkpointId);
      if (!handoff) throw new Error(`Unexpected checkpoint ${checkpointId}`);
      return handoff;
    });

    renderMemory();

    const left = screen.getByRole("article", {
      name: "Architecture review",
    });
    const middle = screen.getByRole("article", {
      name: "Refactor follow-up",
    });
    const right = screen.getByRole("article", {
      name: "Release validation",
    });
    expect(left).toHaveAttribute("data-session-context-slot", "selected-1");
    expect(left).toHaveClass("xl:col-start-1", "xl:row-start-1");
    expect(middle).toHaveAttribute("data-session-context-slot", "selected-2");
    expect(middle).toHaveClass("xl:col-start-2", "xl:row-start-1");
    expect(right).toHaveAttribute("data-session-context-slot", "selected-3");
    expect(right).toHaveClass("xl:col-start-3", "xl:row-start-1");
    expect(document.querySelectorAll("[data-session-context-card]")).toHaveLength(3);

    const toggle = screen.getByRole("button", {
      name: "Edit selected session contexts, 3 of 3 selected",
    });
    expect(toggle).toHaveAttribute("aria-pressed", "true");
    expect(within(left).getByText("Selected Session Context")).toBeInTheDocument();
    expect(within(middle).getByText("Selected Session Context")).toBeInTheDocument();
    expect(within(right).getByText("Selected Session Context")).toBeInTheDocument();
    expect(within(left).getByText(
      "Claude · Architecture review",
    )).toBeInTheDocument();
    expect(within(middle).getByText(
      "OpenCode · Refactor follow-up",
    )).toBeInTheDocument();
    expect(within(right).getByText(
      "Codex · Release validation",
    )).toBeInTheDocument();

    await waitFor(() => {
      const claudePreview = within(left).getByLabelText(
        "Architecture review Session Context prompt preview content",
      );
      const openCodePreview = within(middle).getByLabelText(
        "Refactor follow-up Session Context prompt preview content",
      );
      const releasePreview = within(right).getByLabelText(
        "Release validation Session Context prompt preview content",
      );
      expect(claudePreview).toHaveTextContent("CLAUDE_SELECTED_ONLY");
      expect(claudePreview).not.toHaveTextContent("OPENCODE_SELECTED_ONLY");
      expect(claudePreview).not.toHaveTextContent(
        "Relationship: Project / Workspace Context",
      );
      expect(openCodePreview).toHaveTextContent("OPENCODE_SELECTED_ONLY");
      expect(openCodePreview).not.toHaveTextContent("CLAUDE_SELECTED_ONLY");
      expect(releasePreview).toHaveTextContent("CODEX_RELEASE_ONLY");
      expect(releasePreview).not.toHaveTextContent("OPENCODE_SELECTED_ONLY");
    });
    expect(within(left).getByRole("button", {
      name: "Preview Architecture review Session Context",
    })).toHaveTextContent("Open full preview");
    expect(within(middle).getByRole("button", {
      name: "Preview Refactor follow-up Session Context",
    })).toHaveTextContent("Open full preview");
    expect(within(right).getByRole("button", {
      name: "Preview Release validation Session Context",
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
    expect(mocks.handoff.mutateAsync).toHaveBeenCalledWith({
      workspaceId: "workspace-1",
      checkpointId: "checkpoint-release",
    });

    fireEvent.click(within(left).getByRole("button", {
      name: "Remove Architecture review from Execute",
    }));

    expect(screen.queryByRole("article", {
      name: "Architecture review",
    })).not.toBeInTheDocument();
    const firstOfTwo = screen.getByRole("article", {
      name: "Refactor follow-up",
    });
    const secondOfTwo = screen.getByRole("article", {
      name: "Release validation",
    });
    expect(firstOfTwo).toHaveAttribute("data-session-context-slot", "selected-1");
    expect(firstOfTwo).toHaveClass("xl:col-start-1");
    expect(secondOfTwo).toHaveAttribute("data-session-context-slot", "selected-2");
    expect(secondOfTwo).toHaveClass("xl:col-start-3");
    expect(screen.getByRole("button", {
      name: "Edit selected session contexts, 2 of 3 selected",
    })).toHaveAttribute("aria-pressed", "true");
    expect(document.querySelectorAll("[data-session-context-card]")).toHaveLength(2);

    fireEvent.click(within(firstOfTwo).getByRole("button", {
      name: "Remove Refactor follow-up from Execute",
    }));

    const onlyCard = screen.getByRole("article", {
      name: "Release validation",
    });
    expect(onlyCard).toHaveAttribute("data-session-context-slot", "selected-1");
    expect(onlyCard).toHaveClass("xl:col-start-2");
    expect(document.querySelectorAll("[data-session-context-card]")).toHaveLength(1);
    expect(screen.getByRole("button", {
      name: "Edit selected session contexts, 1 of 3 selected",
    })).toHaveAttribute("aria-pressed", "true");
    expect(readExecuteSessionContexts("workspace-1")).toEqual([
      expect.objectContaining({
        sourceDocumentId: "document-selected-three",
        sessionId: "selected-three",
      }),
    ]);
  });

  it("keeps a Library-selected session locked until two compactions exist", async () => {
    selectDefaultSession({
      compaction_count: 0,
      compaction_checkpoints: [],
    });

    renderMemory();

    const card = screen.getByRole("article", {
      name: "Harden checkpoint capture",
    });
    expect(within(card).getByText("0/2 compactions")).toBeVisible();
    expect(within(card).getByText("2 compactions required.")).toBeVisible();
    expect(within(card).getByRole("button", {
      name: "Preview Harden checkpoint capture Session Context",
    })).toBeDisabled();
    expect(within(card).getByRole("button", {
      name: "Copy Harden checkpoint capture Session Context",
    })).toBeDisabled();

    await waitFor(() => {
      expect(mocks.latestHook).toHaveBeenCalledWith(
        "workspace-1",
        expect.objectContaining({ enabled: false }),
      );
    });
    expect(mocks.capture.mutateAsync).not.toHaveBeenCalled();
    expect(mocks.handoff.mutateAsync).not.toHaveBeenCalled();
    expect(navigator.clipboard.writeText).not.toHaveBeenCalled();
  });

  it("does not prepare a previous workspace's selected sessions after switching workspaces", async () => {
    const selectedSession = {
      id: "claude:selected-one",
      source_document_id: "document-selected-one",
      connector_type: "claude",
      session_id: "selected-one",
      title: "Architecture review",
      harness: "Claude Code",
      latest_topic: "Architecture",
      compaction_count: 2,
    };
    mocks.library.data = { sessions: [selectedSession] };
    writeExecuteSessionContexts("workspace-1", [selectedSession]);

    const oldCurrent = checkpointData();
    const oldSelected = scopedCheckpoint(
      "checkpoint-claude-old-workspace",
      "claude",
      "selected-one",
      31,
    );
    mocks.latestHook.mockImplementation((_workspaceId, options = {}) => ({
      ...mocks.checkpoint,
      data: options.provider === "claude" ? oldSelected : oldCurrent,
      isLoading: false,
      isFetching: false,
    }));
    mocks.handoff.mutateAsync.mockImplementation(async ({ checkpointId }) => {
      if (checkpointId === oldCurrent.id) {
        return scopedSessionHandoff(oldCurrent, "OLD_CURRENT_ONLY");
      }
      if (checkpointId === oldSelected.id) {
        return scopedSessionHandoff(oldSelected, "OLD_SELECTED_ONLY");
      }
      throw new Error(`Unexpected checkpoint ${checkpointId}`);
    });

    const view = renderMemory();
    const oldCard = screen.getByRole("article", {
      name: "Architecture review",
    });
    await waitFor(() => {
      expect(within(oldCard).getByLabelText(
        "Architecture review Session Context prompt preview content",
      )).toHaveTextContent("OLD_SELECTED_ONLY");
    });

    const newCurrent = {
      ...scopedCheckpoint(
        "checkpoint-new-workspace",
        "codex",
        "session-new-workspace",
        41,
      ),
      workspace_id: "workspace-2",
    };
    mocks.workspace.activeWorkspaceId = "workspace-2";
    mocks.workspace.activeWorkspace = {
      id: "workspace-2",
      name: "Other workspace",
      repo_path: "/workspace/other",
    };
    mocks.workspace.selectedId = "workspace-2";
    mocks.digest.data = {
      ...digestData(),
      activity: {
        ...digestData().activity,
        primary: {
          ...digestData().activity.primary,
          provider: "codex",
          session_id: "session-new-workspace",
        },
      },
    };
    mocks.library.data = { sessions: [] };
    mocks.latestHook.mockImplementation(() => ({
      ...mocks.checkpoint,
      data: newCurrent,
      isLoading: false,
      isFetching: false,
    }));
    mocks.handoff.mutateAsync.mockImplementation(async ({ checkpointId }) => {
      throw new Error(`Unexpected checkpoint ${checkpointId}`);
    });

    view.rerender(
      <MemoryRouter initialEntries={["/app/execute"]}>
        <MemoryNow />
      </MemoryRouter>,
    );

    expect(screen.queryByRole("article", {
      name: "Architecture review",
    })).not.toBeInTheDocument();
    expect(document.querySelectorAll("[data-session-context-card]")).toHaveLength(0);
    expect(screen.getByRole("heading", {
      name: "Choose Session Contexts",
    })).toBeInTheDocument();
    expect(mocks.handoff.mutateAsync).not.toHaveBeenCalledWith({
      workspaceId: "workspace-2",
      checkpointId: oldSelected.id,
    });
    expect(mocks.handoff.mutateAsync).not.toHaveBeenCalledWith({
      workspaceId: "workspace-2",
      checkpointId: newCurrent.id,
    });
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
      compaction_count: 2,
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

  it("automatically recompiles a legacy selected-session checkpoint with the current schema", async () => {
    const selectedSession = {
      id: "claude:selected-one",
      source_document_id: "document-selected-one",
      connector_type: "claude",
      session_id: "selected-one",
      title: "Architecture review",
      harness: "Claude Code",
      latest_topic: "Architecture",
      compaction_count: 2,
    };
    mocks.library.data = { sessions: [selectedSession] };
    writeExecuteSessionContexts("workspace-1", [selectedSession]);

    const currentCheckpoint = checkpointData();
    const legacyCheckpoint = {
      ...scopedCheckpoint(
        "checkpoint-claude-v8",
        "claude",
        "selected-one",
        31,
      ),
      schema_version: "work_checkpoint.v8",
    };
    const recompiledCheckpoint = scopedCheckpoint(
      "checkpoint-claude-v10",
      "claude",
      "selected-one",
      31,
    );
    mocks.latestHook.mockImplementation((_workspaceId, options = {}) => ({
      ...mocks.checkpoint,
      data: options.provider === "claude"
        ? legacyCheckpoint
        : currentCheckpoint,
      isLoading: false,
    }));
    mocks.capture.mutateAsync.mockResolvedValue(recompiledCheckpoint);
    mocks.handoff.mutateAsync.mockImplementation(async ({ checkpointId }) => {
      if (checkpointId === currentCheckpoint.id) {
        return scopedSessionHandoff(currentCheckpoint, "MIDDLE_CODEX_ONLY");
      }
      if (checkpointId === recompiledCheckpoint.id) {
        return scopedSessionHandoff(
          recompiledCheckpoint,
          "RECOMPILED_CLAUDE_ONLY",
        );
      }
      throw new Error(`Unexpected checkpoint ${checkpointId}`);
    });

    renderMemory();

    const claudeCard = screen.getByRole("article", {
      name: "Architecture review",
    });
    await waitFor(() => {
      expect(within(claudeCard).getByLabelText(
        "Architecture review Session Context prompt preview content",
      )).toHaveTextContent("RECOMPILED_CLAUDE_ONLY");
    });
    expect(mocks.capture.mutateAsync).toHaveBeenCalledWith({
      workspaceId: "workspace-1",
      provider: "claude",
      sessionId: "selected-one",
      updateGenericLatest: false,
    });
    expect(mocks.handoff.mutateAsync).not.toHaveBeenCalledWith({
      workspaceId: "workspace-1",
      checkpointId: legacyCheckpoint.id,
    });
    expect(mocks.handoff.mutateAsync).toHaveBeenCalledWith({
      workspaceId: "workspace-1",
      checkpointId: recompiledCheckpoint.id,
    });
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
      compaction_count: 2,
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
    await waitFor(() => {
      expect(within(selectedCard).getByLabelText(
        "Architecture review Session Context prompt preview content",
      )).toHaveTextContent("CLAUDE_NEWER_ONLY");
    });
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
      compaction_count: 2,
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
    selectDefaultSession();
    renderMemory();

    const workspaceContext = screen.getByRole("region", { name: "Workspace Context" });
    const sessionCard = screen.getByRole("article", {
      name: "Harden checkpoint capture",
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
      name: "Harden checkpoint capture Session Context prompt preview",
    }).querySelector("[data-pen-motif]")).toBeNull();
    expect(within(workspaceContext).getByRole("region", {
      name: "Workspace Context prompt preview",
    }).querySelector("[data-pen-motif]")).toBeNull();

    expect(within(sessionCard).queryByText(
      /Inherits the verified workspace foundation.*adds only this session's current task state/i,
    )).not.toBeInTheDocument();
    expect(within(sessionCard).queryByText(/Current tip · Updated/)).not.toBeInTheDocument();
    await waitFor(() => expect(within(sessionCard).getByRole("button", {
      name: "Preview Harden checkpoint capture Session Context",
    })).toHaveTextContent("Open full preview"));
    const sessionCopy = within(sessionCard).getByRole("button", {
      name: "Copy Harden checkpoint capture Session Context",
    });
    expect(sessionCopy).toBeEnabled();
    expect(sessionCopy).toHaveClass("btn-primary");

    expect(within(workspaceContext).queryByText("Parent context")).not.toBeInTheDocument();
    expect(within(workspaceContext).queryByText("Workspace-wide · source-backed")).not.toBeInTheDocument();
    expect(within(workspaceContext).queryByText(
      /durable Workspace Context foundation every continuation inherits.*active session is contained below/i,
    )).not.toBeInTheDocument();
    expect(within(workspaceContext).queryByText(/^Workspace scope$/)).not.toBeInTheDocument();
    expect(within(workspaceContext).queryByText(/^Repository$/)).not.toBeInTheDocument();
    expect(within(workspaceContext).queryByText(/^Compiled size$/)).not.toBeInTheDocument();
    expect(workspaceContext.querySelector("dl")).toBeNull();
    await waitFor(() => expect(within(workspaceContext).getByRole("button", {
      name: "Preview Workspace Context",
    })).toHaveTextContent("Open full preview"));
    const projectCopy = within(workspaceContext).getByRole("button", {
      name: "Copy Workspace Context",
    });
    expect(projectCopy).toBeEnabled();
    expect(projectCopy).toHaveClass("btn-primary");
    expect(screen.queryByText("Advanced context details")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Inspect context sources" })).not.toBeInTheDocument();
  });

  it("freshly revalidates the prepared session prompt before copying it", async () => {
    selectDefaultSession();
    renderMemory();

    const sessionCard = screen.getByRole("article", {
      name: "Harden checkpoint capture",
    });
    const preview = within(sessionCard).getByRole("button", {
      name: "Preview Harden checkpoint capture Session Context",
    });
    fireEvent.click(preview);

    await waitFor(() => expect(mocks.handoff.mutateAsync).toHaveBeenCalledWith({
      workspaceId: "workspace-1",
      checkpointId: "checkpoint-1",
    }));
    expect(mocks.capture.mutateAsync).not.toHaveBeenCalled();
    const dialog = await screen.findByRole("dialog", {
      name: "Harden checkpoint capture Session Context Preview",
    });
    expect(within(dialog).getByText(/SESSION_CONTEXT_ONLY/)).toBeInTheDocument();
    expect(screen.getByRole("region", {
      name: "Harden checkpoint capture Session Context prompt preview",
    })).toHaveTextContent("SESSION_CONTEXT_ONLY");
    expect(mocks.handoff.mutateAsync).toHaveBeenCalledTimes(1);
    mocks.handoff.mutateAsync.mockResolvedValue(sessionHandoff(
      "# Session Context\n\nFRESHLY_REVALIDATED",
    ));

    fireEvent.click(within(dialog).getByRole("button", {
      name: "Copy Harden checkpoint capture Session Context",
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
    selectDefaultSession();
    renderMemory();

    const sessionCard = screen.getByRole("article", {
      name: "Harden checkpoint capture",
    });
    await waitFor(() => expect(within(sessionCard).getByRole("button", {
      name: "Preview Harden checkpoint capture Session Context",
    })).toHaveTextContent("Open full preview"));
    expect(mocks.handoff.mutateAsync).toHaveBeenCalledTimes(1);
    mocks.handoff.mutateAsync
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValueOnce(sessionHandoff(
        "# Session Context\n\nRECOVERED_AFTER_RETRY",
      ));

    fireEvent.click(within(sessionCard).getByRole("button", {
      name: "Copy Harden checkpoint capture Session Context",
    }));

    await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
      "# Session Context\n\nRECOVERED_AFTER_RETRY",
    ));
    expect(mocks.handoff.mutateAsync).toHaveBeenCalledTimes(3);
    expect(screen.queryByText("Failed to fetch")).not.toBeInTheDocument();
  });

  it("keeps a persistent session-copy network failure safe and actionable", async () => {
    selectDefaultSession();
    renderMemory();

    const sessionCard = screen.getByRole("article", {
      name: "Harden checkpoint capture",
    });
    await waitFor(() => expect(within(sessionCard).getByRole("button", {
      name: "Preview Harden checkpoint capture Session Context",
    })).toHaveTextContent("Open full preview"));
    expect(mocks.handoff.mutateAsync).toHaveBeenCalledTimes(1);
    mocks.handoff.mutateAsync.mockRejectedValue(new TypeError("Failed to fetch"));

    fireEvent.click(within(sessionCard).getByRole("button", {
      name: "Copy Harden checkpoint capture Session Context",
    }));

    const retryCopy = await within(sessionCard).findByRole("button", {
      name: "Try copy again",
    });
    expect(retryCopy).toHaveClass("btn-primary");
    expect(within(sessionCard).getByText(
      /Could not reach DaemonState to verify the selected session/,
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
    selectDefaultSession();
    renderMemory();

    const sessionCard = screen.getByRole("article", {
      name: "Harden checkpoint capture",
    });
    fireEvent.click(within(sessionCard).getByRole("button", {
      name: "Preview Harden checkpoint capture Session Context",
    }));

    const dialog = await screen.findByRole("dialog", {
      name: "Harden checkpoint capture Session Context Preview",
    });
    expect(within(dialog).getByRole("status")).toHaveTextContent(
      "Reported completion conflicts with remaining work.",
    );
    expect(within(dialog).getByRole("button", {
      name: "Copy Harden checkpoint capture Session Context",
    })).toBeDisabled();
    expect(within(sessionCard).getByRole("button", {
      name: "Copy Harden checkpoint capture Session Context",
    })).toBeDisabled();
    expect(within(sessionCard).getByText("Not copy-ready")).toBeInTheDocument();
    expect(within(sessionCard).getByText(
      /Harden checkpoint capture Session Context is not copy-ready.*completion conflicts/,
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
    selectDefaultSession();
    renderMemory();

    const sessionCard = screen.getByRole("article", {
      name: "Harden checkpoint capture",
    });
    await waitFor(() => expect(mocks.capture.mutateAsync).toHaveBeenCalledWith({
      workspaceId: "workspace-1",
      provider: "codex",
      sessionId: "session-1",
      updateGenericLatest: false,
    }));
    await waitFor(() => expect(within(sessionCard).getByRole("button", {
      name: "Preview Harden checkpoint capture Session Context",
    })).toHaveTextContent("Open full preview"));

    fireEvent.click(within(sessionCard).getByRole("button", {
      name: "Copy Harden checkpoint capture Session Context",
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
    selectDefaultSession();
    renderMemory();

    const sessionCard = screen.getByRole("article", {
      name: "Harden checkpoint capture",
    });
    fireEvent.click(within(sessionCard).getByRole("button", {
      name: "Preview Harden checkpoint capture Session Context",
    }));

    await waitFor(() => expect(mocks.capture.mutateAsync).toHaveBeenCalledWith({
      workspaceId: "workspace-1",
      provider: "codex",
      sessionId: "session-1",
      updateGenericLatest: false,
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
      name: "Harden checkpoint capture Session Context Preview",
    });
    expect(within(dialog).getByText(/REFRESHED_LOSSLESS_GOAL/)).toBeInTheDocument();
  });

  it("explains an irrecoverable missing lossless goal without offering a retry loop", async () => {
    mocks.handoff.mutateAsync.mockRejectedValue(new Error(
      "The checkpoint does not contain a lossless session goal and its original goal event is unavailable.",
    ));
    selectDefaultSession();
    renderMemory();

    const sessionCard = screen.getByRole("article", {
      name: "Harden checkpoint capture",
    });
    fireEvent.click(within(sessionCard).getByRole("button", {
      name: "Preview Harden checkpoint capture Session Context",
    }));

    const dialog = await screen.findByRole("dialog", {
      name: "Harden checkpoint capture Session Context Preview",
    });
    expect(within(dialog).getByRole("alert")).toHaveTextContent(
      "no longer retains its original user request",
    );
    expect(within(dialog).queryByRole("button", {
      name: "Refresh selected session tip",
    })).not.toBeInTheDocument();
    expect(mocks.capture.mutateAsync).toHaveBeenCalledTimes(1);
    expect(mocks.handoff.mutateAsync).toHaveBeenCalledTimes(1);
  });

  it("forces a fresh session-tip capture when retrying a transient handoff failure", async () => {
    mocks.handoff.mutateAsync.mockRejectedValueOnce(new Error(
      "The checkpoint service is temporarily unavailable.",
    ));
    selectDefaultSession();
    renderMemory();

    const sessionCard = screen.getByRole("article", {
      name: "Harden checkpoint capture",
    });
    fireEvent.click(within(sessionCard).getByRole("button", {
      name: "Preview Harden checkpoint capture Session Context",
    }));

    const dialog = await screen.findByRole("dialog", {
      name: "Harden checkpoint capture Session Context Preview",
    });
    fireEvent.click(within(dialog).getByRole("button", {
      name: "Refresh selected session tip",
    }));

    await waitFor(() => expect(mocks.capture.mutateAsync).toHaveBeenCalledWith({
      workspaceId: "workspace-1",
      provider: "codex",
      sessionId: "session-1",
      updateGenericLatest: false,
    }));
    await waitFor(() => expect(within(dialog).getByText(
      /SESSION_CONTEXT_ONLY/,
    )).toBeInTheDocument());
  });

  it("copies the complete Workspace Context snapshot directly from its card", async () => {
    renderMemory();

    const workspaceContext = screen.getByRole("region", { name: "Workspace Context" });
    fireEvent.click(within(workspaceContext).getByRole("button", {
      name: "Copy Workspace Context",
    }));

    await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
      preparedContext.markdown,
    ));
    expect(navigator.clipboard.writeText).not.toHaveBeenCalledWith(preparedContext.execution_prompt);
  });

  it("uses the same canonical foundation hashes as the backend contract", async () => {
    const backendFoundation = {
      schema_version: "workspace_foundation.v1",
      objective_independent: true,
      compiled_at: "2026-08-05T12:00:00Z",
      repository_state: {
        snapshot_fingerprint: "f".repeat(64),
        captured_at: "2026-08-05T12:00:00Z",
      },
      quality_report: { copy_ready: true, score: 95.0, issues: [] },
      product_profile: { name: "Café/工具" },
      semantic_sha256: "dfe6d4365fc4e5c2818f0289835dc37f13f6746ed263c03d5706e4438c3b60cf",
      artifact_sha256: "972306bb79e175f08302dc3641408fbd852d111077298cbe67465e7d1848a15b",
    };
    mocks.prepare.mutateAsync.mockResolvedValue({
      ...preparedContext,
      manifest: {
        ...preparedContext.manifest,
        repo_state: {
          ...preparedContext.manifest.repo_state,
          state_fingerprint: "f".repeat(64),
          workspace_foundation_sha256: backendFoundation.semantic_sha256,
          workspace_foundation_artifact_sha256: backendFoundation.artifact_sha256,
        },
        workspace_foundation: backendFoundation,
      },
    });
    renderMemory();

    const workspaceContext = screen.getByRole("region", { name: "Workspace Context" });
    fireEvent.click(within(workspaceContext).getByRole("button", {
      name: "Copy Workspace Context",
    }));

    await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
      preparedContext.markdown,
    ));
  });

  it("accepts a hash-valid workspace_foundation.v2 artifact", async () => {
    const v2Foundation = workspaceFoundationForSchema("workspace_foundation.v2", {
      verification_runs: [{
        command: "npm test",
        snapshot: "repo-state-fingerprint",
        exit_code: 0,
        result: "passed",
        failures: [],
      }],
    });
    mocks.prepare.mutateAsync.mockResolvedValue(
      preparedContextForFoundation(v2Foundation),
    );
    renderMemory();

    const workspaceContext = screen.getByRole("region", { name: "Workspace Context" });
    fireEvent.click(within(workspaceContext).getByRole("button", {
      name: "Copy Workspace Context",
    }));

    await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
      preparedContext.markdown,
    ));
  });

  it("rejects an unknown Workspace Foundation schema even when its hashes are valid", async () => {
    const unsupportedFoundation = workspaceFoundationForSchema("workspace_foundation.v3");
    mocks.prepare.mutateAsync.mockResolvedValue(
      preparedContextForFoundation(unsupportedFoundation),
    );
    renderMemory();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "compiler returned an incomplete Workspace Context",
    );
    expect(screen.getByRole("button", {
      name: "Copy Workspace Context",
    })).toBeDisabled();
    expect(navigator.clipboard.writeText).not.toHaveBeenCalled();
  });

  it("recompiles immediately before copy so a valid cached preview cannot go stale", async () => {
    const freshMarkdown = projectContextContent.replace(
      "PROJECT_CONTEXT_ONLY",
      "FRESH_REPOSITORY_SNAPSHOT",
    );
    const freshContext = {
      ...preparedContext,
      context_pack_id: "pack-2",
      markdown: freshMarkdown,
      manifest: {
        ...preparedContext.manifest,
        context_pack_id: "pack-2",
        rendering: {
          ...preparedContext.manifest.rendering,
          markdown_sha256: sha256Text(freshMarkdown),
        },
      },
    };
    mocks.prepare.mutateAsync
      .mockResolvedValueOnce(preparedContext)
      .mockResolvedValueOnce(freshContext);
    renderMemory();

    await waitFor(() => expect(mocks.prepare.mutateAsync).toHaveBeenCalledTimes(1));
    const workspaceContext = screen.getByRole("region", { name: "Workspace Context" });
    fireEvent.click(within(workspaceContext).getByRole("button", {
      name: "Copy Workspace Context",
    }));

    await waitFor(() => expect(mocks.prepare.mutateAsync).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
      freshMarkdown,
    ));
    expect(navigator.clipboard.writeText).not.toHaveBeenCalledWith(projectContextContent);
  });

  it("rejects Workspace Context whose content no longer matches its hash", async () => {
    mocks.prepare.mutateAsync.mockResolvedValue({
      ...preparedContext,
      markdown: `${preparedContext.markdown}\nTAMPERED`,
    });
    renderMemory();

    const workspaceContext = screen.getByRole("region", { name: "Workspace Context" });
    fireEvent.click(within(workspaceContext).getByRole("button", {
      name: "Copy Workspace Context",
    }));

    expect(await screen.findByText(
      /Workspace Context failed its content integrity check/,
    )).toBeInTheDocument();
    expect(navigator.clipboard.writeText).not.toHaveBeenCalled();
  });

  it("rejects a continuation staging document presented as Workspace Context", async () => {
    const continuationStagingContent = [
      "# Project / Workspace Context — NOT READY",
      "",
      "## Session Context — task-specific child",
      "",
      "### Authoritative current lead",
      "",
      "### Definition of done",
    ].join("\n");
    mocks.prepare.mutateAsync.mockResolvedValue({
      ...preparedContext,
      markdown: continuationStagingContent,
      manifest: {
        ...preparedContext.manifest,
        rendering: {
          ...preparedContext.manifest.rendering,
          markdown_sha256: sha256Text(continuationStagingContent),
        },
      },
    });
    renderMemory();

    const workspaceContext = screen.getByRole("region", { name: "Workspace Context" });
    fireEvent.click(within(workspaceContext).getByRole("button", {
      name: "Copy Workspace Context",
    }));

    expect(await screen.findByText(
      /compiler returned an incomplete Workspace Context/,
    )).toBeInTheDocument();
    expect(navigator.clipboard.writeText).not.toHaveBeenCalled();
  });

  it("does not apply task handoff quality gates to Workspace Context", async () => {
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
      name: "Copy Workspace Context",
    }));

    await waitFor(() => expect(mocks.prepare.mutateAsync).toHaveBeenCalled());
    await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
      preparedContext.markdown,
    ));
    expect(within(workspaceContext).queryByText("Not copy-ready")).not.toBeInTheDocument();
  });

  it("fails closed when the Workspace Foundation quality gate blocks copy", async () => {
    const blockedFoundationPayload = {
      ...workspaceFoundationPayload,
      quality_report: {
        status: "fail",
        score: 45,
        copy_ready: false,
        publishable: false,
        issues: [{
          id: "issue.product_missing",
          blocking: true,
          message: "No safe repository-stated product purpose was found.",
        }],
      },
    };
    const blockedFoundation = {
      ...blockedFoundationPayload,
      artifact_sha256: sha256Text(canonicalJson(blockedFoundationPayload)),
    };
    mocks.prepare.mutateAsync.mockResolvedValue({
      ...preparedContext,
      manifest: {
        ...preparedContext.manifest,
        repo_state: {
          ...preparedContext.manifest.repo_state,
          workspace_foundation_artifact_sha256: blockedFoundation.artifact_sha256,
        },
        workspace_foundation: blockedFoundation,
      },
    });
    renderMemory();

    const workspaceContext = screen.getByRole("region", { name: "Workspace Context" });
    fireEvent.click(within(workspaceContext).getByRole("button", {
      name: "Copy Workspace Context",
    }));

    expect(await screen.findByText(
      /Workspace Context is not copy-ready.*No safe repository-stated product purpose/i,
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

  it("keeps an unassigned latest session out of Workspace Context while still compiling the workspace", async () => {
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
    expect(document.querySelectorAll("[data-session-context-card]")).toHaveLength(0);
    expect(screen.getByRole("button", {
      name: "Preview Workspace Context",
    })).toBeEnabled();
    await waitFor(() => expect(mocks.prepare.mutateAsync).toHaveBeenCalledWith(
      workspaceSnapshotPayload,
    ));
    expect(mocks.handoff.mutateAsync).not.toHaveBeenCalled();
  });

  it("does not admit an unassigned session checkpoint through workspace fallback", async () => {
    mocks.digest.data.activity.primary = {
      ...mocks.digest.data.activity.primary,
      evidence_level: "session_unassigned",
      project_match: { status: "unknown" },
    };

    renderMemory();

    await waitFor(() => expect(mocks.prepare.mutateAsync).toHaveBeenCalledWith(
      workspaceSnapshotPayload,
    ));
    const payload = mocks.prepare.mutateAsync.mock.calls[0][0];
    expect(payload).not.toHaveProperty("objective");
    expect(payload).not.toHaveProperty("checkpoint_id");
    expect(payload).not.toHaveProperty("source_session_id");
    expect(document.querySelectorAll("[data-session-context-card]")).toHaveLength(0);
    expect(mocks.handoff.mutateAsync).not.toHaveBeenCalled();
    expect(screen.queryByText(
      "Run a real Codex continuation and inspect the resumed context",
    )).not.toBeInTheDocument();
  });

  it("auto-prepares Workspace Context from an imported latest session without creating a Session Context card", async () => {
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

    await waitFor(() => expect(mocks.prepare.mutateAsync).toHaveBeenCalledWith(
      workspaceSnapshotPayload,
    ));
    expect(await screen.findByLabelText(
      "Workspace Context prompt preview content",
    )).toHaveTextContent("PROJECT_CONTEXT_ONLY");
    expect(document.querySelectorAll("[data-session-context-card]")).toHaveLength(0);
    expect(mocks.handoff.mutateAsync).not.toHaveBeenCalled();
  });

  it("does not let a scoped session replace task-independent Workspace Context", async () => {
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
    expect(document.querySelectorAll("[data-session-context-card]")).toHaveLength(0);
    expect(mocks.handoff.mutateAsync).not.toHaveBeenCalled();

    await waitFor(() => expect(mocks.prepare.mutateAsync).toHaveBeenCalledWith(
      workspaceSnapshotPayload,
    ));
    expect(mocks.prepare.mutateAsync.mock.calls[0][0]).not.toHaveProperty("objective");
    expect(mocks.prepare.mutateAsync.mock.calls[0][0]).not.toHaveProperty("source_session_id");
    expect(await screen.findByLabelText(
      "Workspace Context prompt preview content",
    )).toHaveTextContent("PROJECT_CONTEXT_ONLY");
  });

  it("does not pin a source session when preparing Workspace Context", async () => {
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

    await waitFor(() => expect(mocks.prepare.mutateAsync).toHaveBeenCalledWith(
      workspaceSnapshotPayload,
    ));
    expect(mocks.prepare.mutateAsync.mock.calls[0][0]).not.toHaveProperty("source_provider");
    expect(await screen.findByLabelText(
      "Workspace Context prompt preview content",
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

  it("keeps failed task verification out of task-independent Workspace Context preparation", async () => {
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

    await waitFor(() => expect(mocks.prepare.mutateAsync).toHaveBeenCalledWith(
      workspaceSnapshotPayload,
    ));
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

  it("previews and copies the Workspace Context while keeping audit data advanced", async () => {
    renderMemory();

    await waitFor(() => expect(mocks.prepare.mutateAsync).toHaveBeenCalledWith(
      workspaceSnapshotPayload,
    ));
    expect(mocks.prepare.mutateAsync).toHaveBeenCalledTimes(1);
    const previewTrigger = screen.getByRole("button", { name: "Preview Workspace Context" });
    await waitFor(() => {
      expect(screen.getByRole("region", {
        name: "Workspace Context prompt preview",
      })).toHaveTextContent("PROJECT_CONTEXT_ONLY");
      expect(previewTrigger).toHaveTextContent("Open full preview");
    });
    fireEvent.click(previewTrigger);

    const dialog = await screen.findByRole("dialog", { name: "Workspace Context Preview" });
    expect(within(dialog).getByText("Whole workspace")).toBeInTheDocument();
    expect(within(dialog).getByText("workspace_context.v1")).toBeInTheDocument();
    expect(within(dialog).getByLabelText(
      "Workspace Context prompt content",
    )).toHaveTextContent("PROJECT_CONTEXT_ONLY");
    expect(screen.getByRole("region", {
      name: "Workspace Context prompt preview",
    })).toHaveTextContent("PROJECT_CONTEXT_ONLY");

    const advanced = within(dialog).getByText("Advanced audit details").closest("details");
    expect(advanced).not.toHaveAttribute("open");
    fireEvent.click(within(dialog).getByText("Advanced audit details"));
    expect(advanced).toHaveAttribute("open");
    expect(within(dialog).getByLabelText("Advanced audit markdown")).toHaveTextContent(
      "PROJECT_CONTEXT_ONLY",
    );
    expect(within(dialog).getByText("Raw test stdout")).toBeInTheDocument();
    expect(within(dialog).getByText("low signal")).toBeInTheDocument();

    const close = within(dialog).getByRole("button", { name: "Close Workspace Context Preview" });
    expect(close).toHaveFocus();
    fireEvent.keyDown(window, { key: "Tab", shiftKey: true });
    const auditMarkdown = within(dialog).getByLabelText("Advanced audit markdown");
    expect(auditMarkdown).toHaveFocus();
    const copy = within(dialog).getByRole("button", { name: "Copy Workspace Context" });
    fireEvent.click(copy);
    await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
      preparedContext.markdown,
    ));
    expect(navigator.clipboard.writeText).not.toHaveBeenCalledWith(preparedContext.execution_prompt);
    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog", {
      name: "Workspace Context Preview",
    })).not.toBeInTheDocument());
    await waitFor(() => expect(previewTrigger).toHaveFocus());
  });

  it("keeps checkpoint requests and attachments out of Workspace Context preparation", async () => {
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

    await waitFor(() => expect(mocks.prepare.mutateAsync).toHaveBeenCalledWith(
      workspaceSnapshotPayload,
    ));
    expect(mocks.prepare.mutateAsync.mock.calls[0][0]).not.toHaveProperty("objective");
    expect(mocks.prepare.mutateAsync.mock.calls[0][0]).not.toHaveProperty("checkpoint_id");
    fireEvent.click(screen.getByRole("button", { name: "Preview Workspace Context" }));
    expect(await screen.findByRole("dialog", {
      name: "Workspace Context Preview",
    })).toBeInTheDocument();
  });

  it("does not burden Workspace Context with continuation attachment review", async () => {
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

    await waitFor(() => expect(mocks.prepare.mutateAsync).toHaveBeenCalledWith(
      workspaceSnapshotPayload,
    ));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByRole("button", {
      name: "Preview Workspace Context",
    })).toBeEnabled();
  });

  it("does not bind Workspace Context to the authoritative task objective", async () => {
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

    await waitFor(() => expect(mocks.prepare.mutateAsync).toHaveBeenCalledWith(
      workspaceSnapshotPayload,
    ));
    expect(mocks.prepare.mutateAsync.mock.calls[0][0]).not.toHaveProperty("objective");
    fireEvent.click(screen.getByRole("button", { name: "Preview Workspace Context" }));
    expect(await screen.findByRole("dialog", { name: "Workspace Context Preview" })).toBeInTheDocument();
  });

  it("does not send task labels while compiling Workspace Context", async () => {
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
      workspaceSnapshotPayload,
    ));
    expect(mocks.prepare.mutateAsync.mock.calls[0][0]).not.toHaveProperty("objective");
    fireEvent.click(screen.getByRole("button", {
      name: "Preview Workspace Context",
    }));
    expect(await screen.findByRole("dialog", {
      name: "Workspace Context Preview",
    })).toBeInTheDocument();
    expect(screen.queryByText(/belongs to a different task/i)).not.toBeInTheDocument();
  });

  it("ignores continuation task identity when the workspace snapshot identity is valid", async () => {
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
      name: "Preview Workspace Context",
    })[0]);

    expect(await screen.findByRole("dialog", {
      name: "Workspace Context Preview",
    })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("ignores cross-task continuation fields in a valid workspace snapshot", async () => {
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

    fireEvent.click(screen.getByRole("button", { name: "Preview Workspace Context" }));
    expect(await screen.findByRole("dialog", {
      name: "Workspace Context Preview",
    })).toBeInTheDocument();
    expect(screen.queryByText(/belongs to a different task/i)).not.toBeInTheDocument();
  });

  it("keeps session prerequisites out of Workspace Context", async () => {
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

    const preview = screen.getByRole("button", { name: "Preview Workspace Context" });
    await waitFor(() => expect(preview).toHaveTextContent("Open full preview"));
    fireEvent.click(preview);

    const dialog = await screen.findByRole("dialog", { name: "Workspace Context Preview" });
    expect(within(dialog).queryByText(/unfinished prerequisite/i)).not.toBeInTheDocument();
    expect(within(dialog).getByLabelText("Workspace Context prompt content")).toHaveTextContent(
      "PROJECT_CONTEXT_ONLY",
    );
  });

  it("does not turn task readiness into a Workspace Context review gate", async () => {
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

    const preview = screen.getByRole("button", { name: "Preview Workspace Context" });
    await waitFor(() => expect(preview).toHaveTextContent("Open full preview"));
    fireEvent.click(preview);

    const dialog = await screen.findByRole("dialog", { name: "Workspace Context Preview" });
    expect(within(dialog).queryByText(/Compiler readiness/)).not.toBeInTheDocument();
    expect(within(dialog).getByRole("button", {
      name: "Copy Workspace Context",
    })).toBeEnabled();
    expect(screen.queryByText("Continuation blocked")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Review compiled context" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Continue with Session Context/ })).not.toBeInTheDocument();
  });

  it("reports repository indexing without using continuation freshness as a gate", async () => {
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

    fireEvent.click(screen.getAllByRole("button", { name: "Preview Workspace Context" })[0]);

    const dialog = await screen.findByRole("dialog", { name: "Workspace Context Preview" });
    expect(await within(dialog).findByText("Indexed")).toBeInTheDocument();
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
  ])("ignores continuation %s anchors when the workspace snapshot is valid", async (_kind, result, _message) => {
    mocks.prepare.mutateAsync.mockResolvedValue(result);
    renderMemory();

    fireEvent.click(screen.getAllByRole("button", { name: "Preview Workspace Context" })[0]);

    expect(await screen.findByRole("dialog", {
      name: "Workspace Context Preview",
    })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("rejects a Workspace Context artifact from another repository", async () => {
    mocks.prepare.mutateAsync.mockResolvedValue({
      ...preparedContext,
      manifest: {
        ...preparedContext.manifest,
        repo_state: {
          ...preparedContext.manifest.repo_state,
          repo_path: "/workspace/different-project",
        },
      },
    });
    renderMemory();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "compiled context belongs to a different repository",
    );
    expect(screen.getByRole("button", {
      name: "Copy Workspace Context",
    })).toBeDisabled();
  });

  it("ignores source-session identity when preparing Workspace Context", async () => {
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

    await waitFor(() => expect(mocks.prepare.mutateAsync).toHaveBeenCalledWith(
      workspaceSnapshotPayload,
    ));
    expect(screen.queryByText(/belongs to a different source session/i)).not.toBeInTheDocument();
    expect(screen.getByRole("button", {
      name: "Copy Workspace Context",
    })).toBeEnabled();
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

  it("keeps Workspace Context available when no task can be detected", async () => {
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

    expect(document.querySelectorAll("[data-session-context-card]")).toHaveLength(0);
    expect(screen.getByRole("heading", {
      name: "Choose Session Contexts",
    })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("region", {
      name: "Workspace Context prompt preview",
    })).toHaveTextContent("PROJECT_CONTEXT_ONLY"));
    expect(screen.getByRole("button", {
      name: "Preview Workspace Context",
    })).toBeEnabled();
    expect(screen.getByRole("button", {
      name: "Copy Workspace Context",
    })).toBeEnabled();
    expect(mocks.prepare.mutateAsync).toHaveBeenCalledWith(workspaceSnapshotPayload);
    expect(mocks.handoff.mutateAsync).not.toHaveBeenCalled();
  });

  it("falls back to repository Workspace Context when live activity and memory are unavailable", async () => {
    mocks.digest.data = null;
    mocks.digest.isError = true;
    mocks.memory.data = null;
    mocks.memory.isError = true;

    renderMemory();

    expect(screen.getByRole("status")).toHaveTextContent(
      "Some live context is temporarily unavailable",
    );
    await waitFor(() => expect(mocks.prepare.mutateAsync).toHaveBeenCalledWith(
      workspaceSnapshotPayload,
    ));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByRole("button", {
      name: "Copy Workspace Context",
    })).toBeEnabled();
    expect(screen.queryByText("Ready to continue")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Inspect context sources" })).not.toBeInTheDocument();
  });
});
