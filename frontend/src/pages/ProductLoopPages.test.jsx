import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import NowPage from "./NowPage";
import RunsPage from "./RunsPage";

const mocks = vi.hoisted(() => ({
  workspace: {
    activeWorkspaceId: "workspace-1",
    activeWorkspace: { id: "workspace-1", name: "Context Engine" },
    workspacesQuery: { isLoading: false },
    workspaces: [{ id: "workspace-1", name: "Context Engine" }],
    selectedId: "workspace-1",
    setSelectedId: vi.fn(),
  },
  digest: { data: null, isLoading: false, isError: false, error: null, refetch: vi.fn() },
  latest: { data: null, isLoading: false, isError: false, error: null },
  scopedLatest: null,
  history: { data: { checkpoints: [] }, isLoading: false, isError: false, error: null },
  library: { data: { sessions: [] }, isLoading: false },
  continuity: { data: { sessions: [] }, isLoading: false, isError: false, error: null },
  memory: { data: null, isLoading: false, isError: false, error: null },
  hookCalls: {
    latest: [],
    history: [],
    library: [],
    continuity: [],
    memory: [],
    refresh: [],
  },
  capture: { isPending: false, error: null, mutate: vi.fn() },
  prepare: { isPending: false, isError: false, error: null, mutateAsync: vi.fn() },
  comparison: {
    data: {
      status: "matched",
      current: {
        branch: "codex/checkpoints",
        head_commit: "abc123",
        changed_files: ["app/services/checkpoints.py"],
      },
    },
    isLoading: false,
    isError: false,
    error: null,
    refetch: vi.fn(),
  },
  verify: { isPending: false, error: null, mutate: vi.fn() },
  resume: { isPending: false, error: null, mutateAsync: vi.fn() },
  sessionContinue: { isPending: false, error: null, mutateAsync: vi.fn() },
}));

vi.mock("./useProductWorkspace", () => ({
  useProductWorkspace: () => mocks.workspace,
}));

vi.mock("../context-map/api", () => ({
  useContextDigest: () => mocks.digest,
  useLinkedAISessionRefresh: (_workspaceId, options = {}) => {
    mocks.hookCalls.refresh.push(options);
    return { data: null };
  },
  usePrepareContext: () => mocks.prepare,
  useProjectMemory: (_workspaceId, options = {}) => {
    mocks.hookCalls.memory.push(options);
    return mocks.memory;
  },
}));

vi.mock("../api/hooks", () => ({
  useLatestCheckpoint: (_workspaceId, options = {}) => {
    mocks.hookCalls.latest.push(options);
    return options.sessionId ? (mocks.scopedLatest || mocks.latest) : mocks.latest;
  },
  useCheckpoints: (_workspaceId, limit, options = {}) => {
    mocks.hookCalls.history.push({ limit, ...options });
    return mocks.history;
  },
  useSessionLibrary: (_workspaceId, options = {}) => {
    mocks.hookCalls.library.push(options);
    return mocks.library;
  },
  useSessionContinuity: (_workspaceId, options = {}) => {
    mocks.hookCalls.continuity.push(options);
    return mocks.continuity;
  },
  useContinueSession: () => mocks.sessionContinue,
  useCaptureCheckpoint: () => mocks.capture,
  useCheckpointComparison: () => mocks.comparison,
  useVerifyCheckpoint: () => mocks.verify,
  useResumeCheckpoint: () => mocks.resume,
}));

beforeEach(() => {
  Object.values(mocks.hookCalls).forEach((calls) => calls.splice(0));
  mocks.digest.data = baseDigest();
  mocks.digest.isLoading = false;
  mocks.digest.isError = false;
  mocks.digest.error = null;
  mocks.digest.refetch.mockReset();
  mocks.workspace.workspacesQuery.isLoading = false;
  mocks.latest.data = checkpointFixture();
  mocks.latest.isLoading = false;
  mocks.latest.error = null;
  mocks.scopedLatest = null;
  mocks.history.data = { checkpoints: [checkpointFixture()] };
  mocks.history.isLoading = false;
  mocks.history.isError = false;
  mocks.library.data = {
    sessions: [{
      id: "codex:session-1",
      connector_type: "codex",
      harness: "Codex",
      session_id: "session-1",
      source_document_id: "source-1",
      title: "Harden checkpoint capture",
      preview: "Harden checkpoint capture",
      updated_at: "2026-07-21T10:00:00Z",
      cwd: "/workspace/context-engine",
      live: true,
      compaction_checkpoints: [{ id: "compaction-1" }],
    }],
  };
  mocks.library.isLoading = false;
  mocks.library.isError = false;
  mocks.library.error = null;
  mocks.continuity.data = { sessions: [sessionLedgerFixture()] };
  mocks.continuity.isLoading = false;
  mocks.continuity.isError = false;
  mocks.continuity.error = null;
  mocks.memory.data = {
    current_goal: { id: "goal-1", title: "Harden checkpoint capture" },
    totals: {
      active: 12,
      needs_review: 2,
      people_and_dates: 1,
      history: 4,
      all: 19,
    },
  };
  mocks.memory.isLoading = false;
  mocks.memory.isError = false;
  mocks.memory.error = null;
  mocks.capture.isPending = false;
  mocks.capture.error = null;
  mocks.capture.mutate.mockReset();
  mocks.prepare.isPending = false;
  mocks.prepare.isError = false;
  mocks.prepare.error = null;
  mocks.prepare.mutateAsync.mockReset().mockResolvedValue({
    markdown: "# Prepared context",
  });
  mocks.comparison.data = {
    status: "matched",
    current: {
      branch: "codex/checkpoints",
      head_commit: "abc123",
      changed_files: ["app/services/checkpoints.py"],
    },
  };
  mocks.comparison.isLoading = false;
  mocks.comparison.isError = false;
  mocks.comparison.error = null;
  mocks.comparison.refetch.mockReset();
  mocks.verify.isPending = false;
  mocks.verify.error = null;
  mocks.verify.mutate.mockReset();
  mocks.resume.isPending = false;
  mocks.resume.error = null;
  mocks.resume.mutateAsync.mockReset().mockResolvedValue({ content: "# Resume bundle" });
  mocks.sessionContinue.isPending = false;
  mocks.sessionContinue.error = null;
  mocks.sessionContinue.mutateAsync.mockReset().mockResolvedValue({
    content: "# Continue with recovered session context",
    launch: { launched: true },
  });
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: { writeText: vi.fn().mockResolvedValue(undefined) },
  });
});

describe("checkpoint product loop", () => {
  it("shows current work and a complete structured checkpoint on Now", () => {
    render(<MemoryRouter><NowPage /></MemoryRouter>);

    expect(screen.getAllByRole("heading", { name: "Harden checkpoint capture" })).toHaveLength(2);
    expect(screen.getAllByText("Active task").length).toBeGreaterThan(0);
    expect(screen.getByText("Implemented normalized session events")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Latest recovery point" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Progress" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Verification" })).toBeInTheDocument();
    expect(screen.getAllByRole("heading", { name: "Exact next action" })).toHaveLength(1);
    expect(screen.queryByText("Continuity")).not.toBeInTheDocument();
    expect(screen.getByText("Recovery history")).toBeInTheDocument();
    expect(screen.getByText("1 saved")).toBeInTheDocument();
    expect(screen.getByText(/Each dated card preserves an earlier handoff state/)).toBeInTheDocument();
    expect(screen.queryByText("Latest work")).not.toBeInTheDocument();
    expect(screen.getAllByText("Wire checkpoint verification into Runs")).toHaveLength(2);
    expect(screen.queryByText("not run")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open project memory" })).toHaveAttribute("href", "/app/memory");
    expect(screen.getByRole("heading", { name: "What the project remembers now" })).toBeInTheDocument();
    expect(screen.getByText("Trusted current")).toBeInTheDocument();
    expect(screen.queryByText(/01 \//)).not.toBeInTheDocument();
    expect(screen.queryByText(/02 \//)).not.toBeInTheDocument();
    expect(screen.queryByText(/03 \//)).not.toBeInTheDocument();
    expect(screen.queryByText(/04 \//)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Prepare next session" })).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "Explain evidence" }).length).toBeGreaterThan(0);
    expect(mocks.hookCalls.latest[0]).toMatchObject({
      provider: "codex",
      sessionId: "session-1",
      enabled: true,
    });
    expect(mocks.hookCalls.history.at(-1)).toMatchObject({
      limit: 12,
      provider: "codex",
      sessionId: "session-1",
      enabled: true,
    });
    expect(mocks.hookCalls.continuity.at(-1)).toMatchObject({
      provider: "codex",
      sessionId: "session-1",
      enabled: true,
    });
    expect(mocks.hookCalls.library.at(-1)).toMatchObject({ enabled: false });
    expect(mocks.hookCalls.memory.at(-1)).toMatchObject({ enabled: true, limit: 1 });
    expect(mocks.hookCalls.refresh.at(-1)).toEqual({
      enabled: true,
      initialDelayMs: 5_000,
    });
  });

  it("renders the Now shell while current activity is still loading", () => {
    mocks.digest.data = null;
    mocks.digest.isLoading = true;

    render(<MemoryRouter><NowPage /></MemoryRouter>);

    expect(screen.getByRole("heading", { name: "Loading current activity…", level: 1 })).toBeInTheDocument();
    expect(screen.getByText("Loading activity")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Loading task…" })).toBeDisabled();
    expect(screen.getByText("Loading observed progress…")).toBeInTheDocument();
    expect(screen.getByText("Loading verification evidence…")).toBeInTheDocument();
    expect(screen.getByText("Loading attention signals…")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "What the project remembers now" })).toBeInTheDocument();
    expect(screen.queryByText("No agent progress observed yet.")).not.toBeInTheDocument();
    expect(screen.queryByText("No verified result captured.")).not.toBeInTheDocument();
    expect(screen.queryByText("No blocker, conflict, stale evidence, or high-risk review is currently visible.")).not.toBeInTheDocument();
    expect(mocks.hookCalls.latest.every((options) => options.enabled === false)).toBe(true);
    expect(mocks.hookCalls.history.at(-1)).toMatchObject({ limit: 12, enabled: false });
    expect(mocks.hookCalls.library.at(-1)).toMatchObject({ enabled: false });
    expect(mocks.hookCalls.continuity.at(-1)).toMatchObject({ enabled: false });
    expect(mocks.hookCalls.memory.at(-1)).toMatchObject({ enabled: false });
    expect(mocks.hookCalls.refresh.at(-1)).toEqual({
      enabled: false,
      initialDelayMs: 5_000,
    });
  });

  it("reserves project memory space while saved context is loading", () => {
    mocks.latest.data = null;
    mocks.latest.isLoading = true;

    render(<MemoryRouter><NowPage /></MemoryRouter>);

    expect(screen.getByRole("heading", { name: "Loading saved context…" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "What the project remembers now" })).toBeInTheDocument();
    expect(screen.getByText("Loading memory summary…")).toBeInTheDocument();
    expect(screen.queryByText("Trusted current")).not.toBeInTheDocument();
  });

  it("does not offer empty-state actions while linked sessions are loading", () => {
    mocks.digest.data = {
      ...baseDigest(),
      current_goal: null,
      activity: { primary: null },
    };
    mocks.latest.data = null;
    mocks.library.data = { sessions: [] };
    mocks.library.isLoading = true;

    render(<MemoryRouter><NowPage /></MemoryRouter>);

    expect(screen.getByRole("button", { name: "Loading task…" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Loading linked task…" })).toBeDisabled();
    expect(screen.queryByRole("link", { name: "Choose work" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Choose a linked task" })).not.toBeInTheDocument();
  });

  it("keeps saved context and memory available when the initial digest fails", () => {
    mocks.digest.data = null;
    mocks.digest.isLoading = false;
    mocks.digest.isError = true;
    mocks.digest.error = new Error("Digest timed out");

    render(<MemoryRouter><NowPage /></MemoryRouter>);

    expect(screen.getByRole("heading", { name: "Current activity is unavailable", level: 1 })).toBeInTheDocument();
    expect(screen.getByText("Could not load current activity")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Latest recovery point" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "What the project remembers now" })).toBeInTheDocument();
  });

  it("keeps cached activity visible when a background digest refresh fails", () => {
    mocks.digest.isError = true;
    mocks.digest.error = new Error("Refresh timed out");

    render(<MemoryRouter><NowPage /></MemoryRouter>);

    expect(screen.getByRole("heading", { name: "Harden checkpoint capture", level: 1 })).toBeInTheDocument();
    expect(screen.getByText("Activity refresh failed")).toBeInTheDocument();
    expect(screen.getByText(/Showing the last loaded activity/)).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Current activity is unavailable" })).not.toBeInTheDocument();
  });

  it("shows memory as unavailable instead of inventing zero totals", () => {
    mocks.memory.data = null;
    mocks.memory.isError = true;
    mocks.memory.error = new Error("Memory service unavailable");

    render(<MemoryRouter><NowPage /></MemoryRouter>);

    expect(screen.getByText("Memory summary unavailable")).toBeInTheDocument();
    expect(screen.getByText(/no totals are shown/)).toBeInTheDocument();
    expect(screen.queryByText("Trusted current")).not.toBeInTheDocument();
  });

  it("keeps age-only history distinct from a checkpoint with newer activity", () => {
    const historical = checkpointFixture();
    historical.currentness = {
      state: "historical",
      label: "Historical checkpoint",
      is_live: false,
      reason: "This is an older immutable session boundary, not live session state.",
    };
    mocks.latest.data = historical;
    mocks.history.data = { checkpoints: [historical] };

    render(<MemoryRouter><NowPage /></MemoryRouter>);

    expect(screen.getByRole("heading", { name: "Older recovery point" })).toBeInTheDocument();
    expect(screen.getByText("Older snapshot")).toBeInTheDocument();
    expect(screen.getByText(/age alone does not imply newer activity/)).toBeInTheDocument();
    expect(screen.queryByText("Earlier snapshot · newer task activity exists")).not.toBeInTheDocument();
    expect(screen.getAllByText("Wire checkpoint verification into Runs")).toHaveLength(2);
  });

  it("does not present an untrusted checkpoint boundary as current", () => {
    const unknown = checkpointFixture();
    unknown.boundary.occurred_at = null;
    unknown.currentness = {
      state: "unknown",
      label: "Checkpoint boundary",
      is_live: false,
      reason: "The source did not provide a trustworthy boundary time.",
    };
    mocks.latest.data = unknown;
    mocks.history.data = { checkpoints: [unknown] };

    render(<MemoryRouter><NowPage /></MemoryRouter>);

    expect(screen.getByRole("heading", { name: "Saved recovery point" })).toBeInTheDocument();
    expect(screen.getByText("Boundary time unknown")).toBeInTheDocument();
    expect(screen.getByText("Saved state · time unknown")).toBeInTheDocument();
    expect(screen.getAllByText(/boundary time could not be verified/)).toHaveLength(2);
  });

  it("does not call a still-loading resume source unavailable", () => {
    mocks.library.data = { sessions: [] };
    mocks.library.isLoading = true;
    mocks.continuity.data = { sessions: [] };
    mocks.continuity.isLoading = true;

    render(<MemoryRouter><NowPage /></MemoryRouter>);

    expect(screen.getByRole("button", { name: "Checking resume availability…" })).toBeDisabled();
    expect(screen.queryByText(/original task is unavailable here/)).not.toBeInTheDocument();
  });

  it("reports resume preparation failures inside the active dialog", async () => {
    mocks.sessionContinue.mutateAsync.mockRejectedValueOnce(new Error("The linked task is no longer available."));

    render(<MemoryRouter><NowPage /></MemoryRouter>);
    fireEvent.click(screen.getByRole("button", { name: "Resume task" }));
    fireEvent.click(screen.getByRole("button", { name: "Open Codex and copy context" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Could not prepare resume context");
    expect(alert).toHaveTextContent("The linked task is no longer available.");
    expect(alert.closest('[role="dialog"]')).not.toBeNull();
  });

  it("never promotes screenshot attachment metadata to the active task", () => {
    const attachmentEnvelope = `# Files mentioned by the user:

## Screenshot 2026-07-23 at 16.42.18.png: /var/folders/example/TemporaryItems/NSIRD_screencaptureui_abc/Screenshot 2026-07-23 at 16.42.18.png

## My request for Codex:
Remove screenshot IDs and temporary paths from the Now page.
<image name=[Image #1] path="/var/folders/example/TemporaryItems/NSIRD_screencaptureui_abc/Screenshot 2026-07-23 at 16.42.18.png">
</image>`;
    mocks.digest.data.current_goal = null;
    mocks.digest.data.activity.primary.request = attachmentEnvelope;
    mocks.digest.data.activity.primary.title = attachmentEnvelope;

    render(<MemoryRouter><NowPage /></MemoryRouter>);

    expect(screen.getByRole("heading", { name: "Remove screenshot IDs and temporary paths from the Now page", level: 1 })).toBeInTheDocument();
    expect(screen.queryByText(/Screenshot 2026-07-23/)).not.toBeInTheDocument();
    expect(screen.queryByText(/\/var\/folders/)).not.toBeInTheDocument();
    expect(screen.queryByText(/screencaptureui_/)).not.toBeInTheDocument();
  });

  it("falls back instead of displaying metadata-only activity", () => {
    const attachmentOnly = "Screenshot 2026-07-23 at 16.42.18.png: /var/folders/example/TemporaryItems/NSIRD_screencaptureui_abc/Screenshot 2026-07-23 at 16.42.18.png";
    mocks.digest.data.current_goal = null;
    mocks.digest.data.activity.primary.request = attachmentOnly;
    mocks.digest.data.activity.primary.title = attachmentOnly;

    render(<MemoryRouter><NowPage /></MemoryRouter>);

    expect(screen.getByRole("heading", { name: "Harden checkpoint capture", level: 1 })).toBeInTheDocument();
    expect(screen.queryByText(/Screenshot 2026-07-23/)).not.toBeInTheDocument();
    expect(screen.queryByText(/\/var\/folders/)).not.toBeInTheDocument();
  });

  it("prepares the trusted active goal and copies a focused context pack", async () => {
    render(<MemoryRouter><NowPage /></MemoryRouter>);

    fireEvent.click(screen.getByRole("button", { name: "Prepare next session" }));

    await waitFor(() => expect(mocks.prepare.mutateAsync).toHaveBeenCalledWith({
      objective: "Harden checkpoint capture",
      workspace_id: "workspace-1",
      mode: "task",
      objective_origin: "trusted_human",
    }));
    await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledWith("# Prepared context"));
    expect(screen.getByRole("status")).toHaveTextContent("Context pack copied");
    expect(mocks.capture.mutate).not.toHaveBeenCalled();
  });

  it("leads to session selection when no linked work can be continued", () => {
    mocks.latest.data = null;
    mocks.history.data = { checkpoints: [] };
    mocks.library.data = { sessions: [] };
    mocks.digest.data.activity.primary = {
      ...mocks.digest.data.activity.primary,
      provider: null,
      tool: null,
      session_id: null,
    };

    render(<MemoryRouter><NowPage /></MemoryRouter>);

    expect(screen.getByRole("link", { name: "Prepare next session" })).toHaveAttribute("href", "/app/library");
    expect(screen.getByText("Choose a linked coding session before preparing its continuation.")).toBeInTheDocument();
    expect(mocks.hookCalls.library.at(-1)).toMatchObject({ enabled: true });
  });

  it("captures the latest real session instead of compiling a Prepare brief", () => {
    mocks.latest.data = null;
    render(<MemoryRouter><NowPage /></MemoryRouter>);

    fireEvent.click(screen.getByRole("button", { name: "Save current context" }));
    expect(mocks.capture.mutate).toHaveBeenCalledWith({
      workspaceId: "workspace-1",
      provider: "codex",
      sessionId: "session-1",
    });
    expect(screen.getByText(/Save the current task before a long handoff or compaction/)).toBeInTheDocument();
  });

  it("reviews the reconstructed task and copies resume context only after confirmation", async () => {
    render(<MemoryRouter><NowPage /></MemoryRouter>);

    fireEvent.click(screen.getByRole("button", { name: "Verify checkpoint" }));
    expect(mocks.verify.mutate).toHaveBeenCalledWith({
      workspaceId: "workspace-1",
      checkpointId: "checkpoint-1",
      executeCommands: true,
    });

    const resumeTrigger = screen.getByRole("button", { name: "Resume task" });
    resumeTrigger.focus();
    fireEvent.click(resumeTrigger);
    const continueDialog = screen.getByRole("dialog");
    expect(continueDialog).toHaveAccessibleName("Review and resume");
    expect(screen.getByRole("heading", { name: "Review and resume" })).toHaveFocus();
    expect(screen.getByText(/Nothing is sent, pasted, restored, or overwritten automatically/)).toBeInTheDocument();
    expect(mocks.sessionContinue.mutateAsync).not.toHaveBeenCalled();

    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    await waitFor(() => expect(resumeTrigger).toHaveFocus());

    fireEvent.click(resumeTrigger);
    fireEvent.click(screen.getByRole("button", { name: "Open Codex and copy context" }));
    await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledWith("# Continue with recovered session context"));
    expect(mocks.sessionContinue.mutateAsync).toHaveBeenCalledWith({
      workspaceId: "workspace-1",
      sourceDocumentId: "source-1",
      launchSession: true,
    });
  });

  it("shows every captured compaction for the displayed session in boundary order", () => {
    const latest = checkpointFixture();
    const earlier = checkpointFixture();
    earlier.id = "checkpoint-0";
    earlier.boundary.sequence_number = 12;
    earlier.boundary.occurred_at = "2026-07-21T09:15:00Z";
    earlier.sections.goal[0].statement = "Earlier compacted goal";
    mocks.latest.data = latest;
    mocks.history.data = { checkpoints: [latest, earlier] };

    render(<MemoryRouter><NowPage /></MemoryRouter>);

    expect(screen.getByText("2 saved")).toBeInTheDocument();
    expect(screen.getByText("In view")).toBeInTheDocument();
    expect(screen.getByText("Earlier")).toBeInTheDocument();
    expect(screen.queryByText(/Recovery point 0/)).not.toBeInTheDocument();
    expect(screen.getByText("Earlier compacted goal")).toBeInTheDocument();
  });

  it("does not mix an unrelated older checkpoint into the active task", () => {
    const oldCheckpoint = checkpointFixture();
    oldCheckpoint.currentness = {
      state: "superseded",
      label: "Superseded checkpoint",
      is_live: false,
      reason: "This session has events after the captured boundary.",
    };
    oldCheckpoint.boundary.session_tip_sequence = 52;
    oldCheckpoint.sections.goal[0].statement = "Old checkpoint task";
    oldCheckpoint.activity.request = "Old checkpoint task";
    oldCheckpoint.activity.title = "Old checkpoint task";
    mocks.latest.data = oldCheckpoint;
    mocks.scopedLatest = {
      data: null,
      isLoading: false,
      isError: false,
      error: null,
    };
    mocks.digest.data.activity.primary = {
      ...mocks.digest.data.activity.primary,
      request: "Current observed task",
      title: "Current observed task",
      latest_update: "Current session update.",
      provider: "codex",
      session_id: "current-session",
      state: "snapshot",
      evidence_level: "session_reported",
      updated_at: "2026-07-22T08:00:00Z",
    };

    render(<MemoryRouter><NowPage /></MemoryRouter>);

    expect(screen.getByRole("heading", { name: "Current observed task" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "No saved context for this task" })).toBeInTheDocument();
    expect(screen.getByText("Old checkpoint task")).toBeInTheDocument();
    expect(screen.getByText("Earlier saved context · another task")).toBeInTheDocument();
    expect(screen.getByText(/not being used as the current task’s next action/)).toBeInTheDocument();
    expect(screen.queryByText("Not the latest state — 10 events behind")).not.toBeInTheDocument();
    expect(screen.queryByText("Resume session")).not.toBeInTheDocument();
    expect(screen.queryByText("Wire checkpoint verification into Runs")).not.toBeInTheDocument();
    expect(screen.getByText("Save the current task context to preserve its exact next action.")).toBeInTheDocument();
  });

  it("saves the session selected as the latest observed work", () => {
    mocks.latest.data = null;
    mocks.history.data = { checkpoints: [] };
    mocks.digest.data.activity.primary = {
      ...mocks.digest.data.activity.primary,
      provider: "codex",
      session_id: "current-session",
      state: "snapshot",
      evidence_level: "session_reported",
    };
    mocks.library.data.sessions = [{ connector_type: "opencode", session_id: "older-session" }];

    render(<MemoryRouter><NowPage /></MemoryRouter>);
    fireEvent.click(screen.getByRole("button", { name: "Save current context" }));

    expect(mocks.capture.mutate).toHaveBeenCalledWith({
      workspaceId: "workspace-1",
      provider: "codex",
      sessionId: "current-session",
    });
  });

  it("presents one source-backed, user-facing resume history per session", () => {
    render(<MemoryRouter><RunsPage /></MemoryRouter>);
    const heading = screen.getByRole("heading", { name: "Resume sessions" });
    expect(heading).toHaveClass("text-3xl", "font-black", "sm:text-4xl");
    expect(screen.getByText(/Review what you asked for/)).toBeInTheDocument();
    expect(screen.getByText("One card. One session.")).toBeInTheDocument();
    expect(screen.queryByText("Items")).not.toBeInTheDocument();
    const sessionHeading = screen.getByRole("heading", { name: "Harden checkpoint capture" });
    expect(sessionHeading).toBeInTheDocument();
    expect(document.querySelectorAll("[data-harness-deck-backdrop] [data-backdrop-harness]")).toHaveLength(3);
    const sessionCard = sessionHeading.closest("[data-session-ledger]");
    expect(sessionCard?.querySelector('[data-harness-logo="codex"]')).toBeInTheDocument();
    expect(sessionCard?.querySelector('[data-harness-artwork="codex"]')).toBeInTheDocument();
    expect(sessionCard).toHaveTextContent("Ready to resume — review context gaps");
    expect(sessionCard).not.toHaveTextContent(/Event \d+/);
    expect(sessionCard).not.toHaveTextContent("01");
    expect(screen.getByText(/Build one card per session/)).toBeInTheDocument();
    expect(screen.getByText("Unknown")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Since then/ }));
    expect(screen.getByText(/Showing the latest 1 of 7 session updates/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Progress" })).toBeInTheDocument();
    expect(screen.getByText("Implemented normalized session events")).toBeInTheDocument();
    expect(screen.queryByText("/Users/darshann/Desktop/context-engine/tests/test_session_library.py")).not.toBeInTheDocument();
    expect(screen.queryByText("Run checks")).not.toBeInTheDocument();
    expect(screen.queryByText(/Repair/)).not.toBeInTheDocument();
    expect(mocks.verify.mutate).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Resume task: Harden checkpoint capture" }));
    expect(screen.getByRole("dialog")).toHaveAccessibleName("Review and resume");
    expect(screen.getByText(/Some context gaps are unknown/)).toBeInTheDocument();
    expect(screen.getByText(/Nothing is sent, pasted, restored, or overwritten automatically/)).toBeInTheDocument();
    expect(mocks.sessionContinue.mutateAsync).not.toHaveBeenCalled();
  });

  it.each([
    ["failed", "complete"],
    ["stale", "complete"],
    ["not_run", "incomplete"],
  ])("keeps checkpoint status %s out of the resume card", (verificationStatus, captureStatus) => {
    const checkpoint = checkpointFixture();
    checkpoint.verification.status = verificationStatus;
    checkpoint.capture_status = captureStatus;
    mocks.history.data = { checkpoints: [checkpoint] };

    render(<MemoryRouter><RunsPage /></MemoryRouter>);

    expect(screen.getByText("Ready to resume — review context gaps")).toBeInTheDocument();
    expect(screen.queryByText(/Saved checks|Checks may be stale|Saved context needs review/)).not.toBeInTheDocument();
    expect(screen.queryByText("Run checks")).not.toBeInTheDocument();
  });
});

function baseDigest() {
  return {
    current_goal: { title: "Harden checkpoint capture" },
    activity: {
      primary: {
        evidence_level: "observed_run",
        request: "Harden checkpoint capture",
        latest_update: "Implemented normalized session events.",
        tool: "codex",
        model: "gpt-5",
        branch: "codex/checkpoints",
        updated_at: "2026-07-21T10:00:00Z",
        changed_files: ["app/services/checkpoints.py"],
      verification: { observed: 1, passed: 1, failed: 0 },
      outcome: { summary: "Focused tests passed.", observed_at: "2026-07-21T10:00:00Z" },
      provider: "codex",
      session_id: "session-1",
      state: "snapshot",
      },
    },
    cards: [],
  };
}

function checkpointFixture() {
  const evidence = [{ id: "evidence-1", locator: { provider_event_id: "event-1" } }];
  const item = (id, statement, truthState = "reported", payload = {}) => ({
    id,
    statement,
    truth_state: truthState,
    payload,
    evidence,
  });
  return {
    id: "checkpoint-1",
    provider: "codex",
    session_id: "session-1",
    trigger: "compaction",
    capture_status: "complete",
    continuation_status: "ready",
    created_at: "2026-07-21T10:00:00Z",
    boundary: {
      occurred_at: "2026-07-21T09:58:00Z",
      captured_at: "2026-07-21T10:00:00Z",
      sequence_number: 42,
      session_tip_sequence: 42,
      snapshot_phase: "pre_compaction",
      snapshot_phase_label: "Pre-compaction snapshot",
      snapshot_phase_description: "Captures session state immediately before context compaction and excludes all events after the boundary.",
    },
    currentness: {
      state: "captured",
      label: "Recent checkpoint boundary",
      is_live: false,
      reason: "This is immutable state at the captured boundary, not a live goal.",
    },
    repo: {
      branch: "codex/checkpoints",
      head_commit: "abc123",
      worktree_fingerprint: "fingerprint-1",
    },
    verification: { status: "verified", results: { checks: [] } },
    sections: {
      goal: [item("goal-1", "Harden checkpoint capture")],
      progress: [item("progress-1", "Implemented normalized session events.")],
      decisions: [item("decision-1", "Keep every checkpoint item evidence-linked.")],
      failed_attempts: [],
      relevant_files: [item("file-1", "app/services/checkpoints.py", "observed", { path: "app/services/checkpoints.py" })],
      blockers: [],
      verification: [item("test-1", "pytest -q passed.", "observed", { passed: true })],
      exact_next_action: [item("next-1", "Wire checkpoint verification into Runs.")],
    },
    payload: {
      sections: {
        goal: [{ evidence_event_ids: ["event-1"] }],
        progress: [{ evidence_event_ids: ["event-2"] }],
      },
    },
    activity: {
      kind: "checkpoint_boundary",
      evidence_level: "checkpoint_boundary",
      request: "Harden checkpoint capture",
      title: "Harden checkpoint capture",
      latest_update: "Implemented normalized session events.",
      tool: "codex",
      provider: "codex",
      session_id: "session-1",
      branch: "codex/checkpoints",
      updated_at: "2026-07-21T09:58:00Z",
      changed_files: ["app/services/checkpoints.py"],
      verification: { observed: 1, passed: 1, failed: 0 },
      outcome: null,
    },
  };
}

function sessionLedgerFixture() {
  const ledgerItem = (id, text, kind, truthState = "reported", sequenceNumber = 1) => ({
    id,
    text,
    kind,
    truth_state: truthState,
    sequence_number: sequenceNumber,
  });
  return {
    schema_version: "session_context.v1",
    provider: "codex",
    session_id: "session-1",
    source_document_id: "source-1",
    updated_at: "2026-07-21T10:00:00Z",
    base: [
      ledgerItem("base-1", "Build one card per session.", "original_request", "user_stated", 1),
    ],
    added: [
      ledgerItem("progress-1", "Implemented normalized session events", "progress", "reported", 2),
    ],
    files: [
      ledgerItem(
        "file-1",
        "/Users/darshann/Desktop/context-engine/tests/test_session_library.py",
        "file",
        "observed",
        3,
      ),
    ],
    changed: [
      ledgerItem("change-1", "Instead, use one card per session.", "amendment", "user_stated", 4),
    ],
    missing: {
      status: "unmeasured",
      items: [],
      reason: "The provider does not expose post-compaction active context.",
    },
    removed: [],
    counts: { base: 1, added: 7, files: 1, changed: 1, missing: null, removed: 0 },
    truncated: { base: 0, added: 6, files: 0, changed: 0, missing: 0, removed: 0 },
    compactions: [{ event_id: "compact-1", sequence_number: 5 }],
  };
}
