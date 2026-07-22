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
  digest: { data: null, isLoading: false, isError: false, error: null },
  latest: { data: null, isLoading: false, isError: false, error: null },
  history: { data: { checkpoints: [] }, isLoading: false, isError: false, error: null },
  library: { data: { sessions: [] }, isLoading: false },
  capture: { isPending: false, error: null, mutate: vi.fn() },
  verify: { isPending: false, error: null, mutate: vi.fn() },
  resume: { isPending: false, error: null, mutateAsync: vi.fn() },
}));

vi.mock("./useProductWorkspace", () => ({
  useProductWorkspace: () => mocks.workspace,
}));

vi.mock("../context-map/api", () => ({
  useContextDigest: () => mocks.digest,
  useLinkedAISessionRefresh: () => ({ data: null }),
}));

vi.mock("../api/hooks", () => ({
  useLatestCheckpoint: () => mocks.latest,
  useCheckpoints: () => mocks.history,
  useSessionLibrary: () => mocks.library,
  useCaptureCheckpoint: () => mocks.capture,
  useVerifyCheckpoint: () => mocks.verify,
  useResumeCheckpoint: () => mocks.resume,
}));

beforeEach(() => {
  mocks.digest.data = baseDigest();
  mocks.digest.isLoading = false;
  mocks.digest.isError = false;
  mocks.latest.data = checkpointFixture();
  mocks.latest.isLoading = false;
  mocks.latest.error = null;
  mocks.history.data = { checkpoints: [checkpointFixture()] };
  mocks.history.isLoading = false;
  mocks.history.isError = false;
  mocks.library.data = {
    sessions: [{ connector_type: "codex", session_id: "session-1" }],
  };
  mocks.capture.isPending = false;
  mocks.capture.error = null;
  mocks.capture.mutate.mockReset();
  mocks.verify.isPending = false;
  mocks.verify.error = null;
  mocks.verify.mutate.mockReset();
  mocks.resume.isPending = false;
  mocks.resume.error = null;
  mocks.resume.mutateAsync.mockReset().mockResolvedValue({ content: "# Resume bundle" });
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: { writeText: vi.fn().mockResolvedValue(undefined) },
  });
});

describe("checkpoint product loop", () => {
  it("shows current work and a complete structured checkpoint on Now", () => {
    render(<MemoryRouter><NowPage /></MemoryRouter>);

    expect(screen.getAllByRole("heading", { name: "Harden checkpoint capture" })).toHaveLength(2);
    expect(screen.getByText("Implemented normalized session events")).toBeInTheDocument();
    expect(screen.getByText("Continuity checkpoint")).toBeInTheDocument();
    expect(screen.getByText("Recorded work")).toBeInTheDocument();
    expect(screen.getByText("Captured compactions for this session · 1")).toBeInTheDocument();
    expect(screen.getByText(/Every entry is the session state immediately before that compaction/)).toBeInTheDocument();
    expect(screen.queryByText("Latest work")).not.toBeInTheDocument();
    expect(screen.getByText("Wire checkpoint verification into Runs")).toBeInTheDocument();
    expect(screen.getByText("verified")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Save checkpoint/ })).toBeInTheDocument();
    expect(screen.queryByText(/Prepare this work/)).not.toBeInTheDocument();
  });

  it("captures the latest real session instead of compiling a Prepare brief", () => {
    mocks.latest.data = null;
    render(<MemoryRouter><NowPage /></MemoryRouter>);

    fireEvent.click(screen.getByRole("button", { name: "Capture latest session" }));
    expect(mocks.capture.mutate).toHaveBeenCalledWith({
      workspaceId: "workspace-1",
      provider: "codex",
      sessionId: "session-1",
    });
    expect(screen.getByText(/created automatically at context compaction boundaries/)).toBeInTheDocument();
  });

  it("warns before opening a session and copies a deterministic resume bundle only after confirmation", async () => {
    render(<MemoryRouter><NowPage /></MemoryRouter>);

    fireEvent.click(screen.getByRole("button", { name: "Verify now" }));
    expect(mocks.verify.mutate).toHaveBeenCalledWith({
      workspaceId: "workspace-1",
      checkpointId: "checkpoint-1",
      executeCommands: true,
    });

    fireEvent.click(screen.getByRole("button", { name: "Resume session" }));
    expect(screen.getByRole("dialog", { name: "Resume from this checkpoint?" })).toBeInTheDocument();
    expect(screen.getByText(/Nothing is sent or pasted automatically/)).toBeInTheDocument();
    expect(screen.getAllByText("Pre-compaction snapshot").length).toBeGreaterThan(0);
    expect(mocks.resume.mutateAsync).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Open Codex and copy bundle" }));
    await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledWith("# Resume bundle"));
    expect(mocks.resume.mutateAsync).toHaveBeenCalledWith({
      workspaceId: "workspace-1",
      checkpointId: "checkpoint-1",
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

    expect(screen.getByText("Captured compactions for this session · 2")).toBeInTheDocument();
    expect(screen.getByText("Compaction 1")).toBeInTheDocument();
    expect(screen.getByText("Compaction 2 · displayed checkpoint")).toBeInTheDocument();
    expect(screen.getByText("Earlier compacted goal")).toBeInTheDocument();
  });

  it("shows current observed work before a superseded recovery checkpoint", () => {
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
    expect(screen.getByRole("heading", { name: "Old checkpoint task" })).toBeInTheDocument();
    expect(screen.getByText("Last recovery checkpoint")).toBeInTheDocument();
    expect(screen.getByText("Not the latest session state · 10 events behind")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Resume session" }));
    expect(screen.getByText("This checkpoint is not the latest session state.")).toBeInTheDocument();
    expect(screen.getByText(/10 newer events exist after this boundary/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Resume from old checkpoint" })).toBeInTheDocument();
  });

  it("saves the session selected as the latest observed work", () => {
    mocks.digest.data.activity.primary = {
      ...mocks.digest.data.activity.primary,
      provider: "codex",
      session_id: "current-session",
      state: "snapshot",
      evidence_level: "session_reported",
    };
    mocks.library.data.sessions = [{ connector_type: "opencode", session_id: "older-session" }];

    render(<MemoryRouter><NowPage /></MemoryRouter>);
    fireEvent.click(screen.getByRole("button", { name: /Save checkpoint/ }));

    expect(mocks.capture.mutate).toHaveBeenCalledWith({
      workspaceId: "workspace-1",
      provider: "codex",
      sessionId: "current-session",
    });
  });

  it("uses Runs as an inspectable checkpoint and evidence timeline", () => {
    render(<MemoryRouter><RunsPage /></MemoryRouter>);

    expect(screen.getByRole("heading", { name: "How to use checkpoints" })).toBeInTheDocument();
    expect(screen.getByText("Review the handoff state")).toBeInTheDocument();
    expect(screen.getByText("Compare boundaries")).toBeInTheDocument();
    expect(screen.getByText("Verify against the repository")).toBeInTheDocument();
    expect(screen.getByText("Resume from this point")).toBeInTheDocument();
    expect(screen.getByText(/It preserves the handoff state before context was compressed/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Harden checkpoint capture" })).toBeInTheDocument();
    expect(screen.getByText("Verified")).toBeInTheDocument();
    expect(screen.getByText("Wire checkpoint verification into Runs")).toBeInTheDocument();
    fireEvent.click(screen.getAllByText("Inspect structured evidence").find((node) => node.tagName === "SUMMARY"));
    expect(screen.getByText("Implemented normalized session events")).toBeInTheDocument();
    expect(screen.getByText("app/services/checkpoints.py")).toBeInTheDocument();
    expect(screen.getAllByText(/evidence event/).length).toBeGreaterThan(0);
    expect(screen.queryByRole("button", { name: /Compare/ })).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("Learn what each action does"));
    expect(screen.getByText(/Context Engine does not merge their claims/)).toBeInTheDocument();
    expect(screen.getByText(/Nothing is sent automatically/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Resume session" }));
    expect(screen.getByRole("dialog", { name: "Resume from this checkpoint?" })).toBeInTheDocument();
    expect(mocks.resume.mutateAsync).not.toHaveBeenCalled();
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
