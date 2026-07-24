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
  continuity: { data: { sessions: [] }, isLoading: false, isError: false, error: null },
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
  useLinkedAISessionRefresh: () => ({ data: null }),
  usePrepareContext: () => mocks.prepare,
}));

vi.mock("../api/hooks", () => ({
  useLatestCheckpoint: () => mocks.latest,
  useCheckpoints: () => mocks.history,
  useSessionLibrary: () => mocks.library,
  useSessionContinuity: () => mocks.continuity,
  useContinueSession: () => mocks.sessionContinue,
  useCaptureCheckpoint: () => mocks.capture,
  useCheckpointComparison: () => mocks.comparison,
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
  mocks.continuity.data = { sessions: [sessionLedgerFixture()] };
  mocks.continuity.isLoading = false;
  mocks.continuity.isError = false;
  mocks.continuity.error = null;
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
    expect(screen.getByText("Active task")).toBeInTheDocument();
    expect(screen.getByText("Implemented normalized session events")).toBeInTheDocument();
    expect(screen.getByText("Recovery point")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Progress" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Verification" })).toBeInTheDocument();
    expect(screen.getAllByRole("heading", { name: "Exact next action" })).toHaveLength(1);
    expect(screen.queryByText("Continuity")).not.toBeInTheDocument();
    expect(screen.getByText("Saved recovery points · 1")).toBeInTheDocument();
    expect(screen.getByText(/Each entry preserves an earlier handoff state/)).toBeInTheDocument();
    expect(screen.queryByText("Latest work")).not.toBeInTheDocument();
    expect(screen.getAllByText("Wire checkpoint verification into Runs")).toHaveLength(2);
    expect(screen.queryByText("not run")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "View in Memory" })).toHaveAttribute("href", "/app/memory");
    expect(screen.getByRole("link", { name: "Open project memory" })).toHaveAttribute("href", "/app/memory");
    expect(screen.getByRole("button", { name: "Prepare next session" })).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "Explain evidence" }).length).toBeGreaterThan(0);
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
    expect(screen.getByText(/created automatically before long sessions are condensed/)).toBeInTheDocument();
  });

  it("warns before opening a session and copies a deterministic resume bundle only after confirmation", async () => {
    render(<MemoryRouter><NowPage /></MemoryRouter>);

    fireEvent.click(screen.getByRole("button", { name: "Verify now" }));
    expect(mocks.verify.mutate).toHaveBeenCalledWith({
      workspaceId: "workspace-1",
      checkpointId: "checkpoint-1",
      executeCommands: true,
    });

    const resumeTrigger = screen.getByRole("button", { name: "Resume session" });
    resumeTrigger.focus();
    fireEvent.click(resumeTrigger);
    const continueDialog = screen.getByRole("dialog");
    expect(continueDialog).toHaveAccessibleName("Continue this work? Harden checkpoint capture");
    expect(screen.getByRole("heading", { name: "Continue this work? Harden checkpoint capture" })).toHaveFocus();
    expect(screen.getByText(/Nothing is sent, pasted, restored, or overwritten automatically/)).toBeInTheDocument();
    expect(screen.getAllByText(/saved before the session was condensed/i).length).toBeGreaterThan(0);
    expect(mocks.resume.mutateAsync).not.toHaveBeenCalled();

    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    await waitFor(() => expect(resumeTrigger).toHaveFocus());

    fireEvent.click(resumeTrigger);
    fireEvent.click(screen.getByRole("button", { name: "Open Codex and copy context" }));
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

    expect(screen.getByText("Saved recovery points · 2")).toBeInTheDocument();
    expect(screen.getByText("Recovery point 01")).toBeInTheDocument();
    expect(screen.getByText("Recovery point 02 · shown")).toBeInTheDocument();
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
    expect(screen.getByRole("heading", { name: "Previous recovery point" })).toBeInTheDocument();
    expect(screen.getByText("Goal")).toBeInTheDocument();
    expect(screen.getByText("Not the latest state — 10 events behind")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Resume session" }));
    expect(screen.getByText("This is an older saved version.")).toBeInTheDocument();
    expect(screen.getByText(/This session has newer activity after it/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Continue from older version" })).toBeInTheDocument();
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
    fireEvent.click(screen.getByRole("button", { name: "Capture latest session" }));

    expect(mocks.capture.mutate).toHaveBeenCalledWith({
      workspaceId: "workspace-1",
      provider: "codex",
      sessionId: "current-session",
    });
  });

  it("presents one source-backed continuity ledger per session", () => {
    render(<MemoryRouter><RunsPage /></MemoryRouter>);
    const heading = screen.getByRole("heading", { name: "Resume sessions" });
    expect(heading).toHaveClass("text-3xl", "font-black", "sm:text-4xl");
    expect(screen.getByText(/Every card is one agent session/)).toBeInTheDocument();
    expect(screen.getByText("One card. One session.")).toBeInTheDocument();
    const sessionHeading = screen.getByRole("heading", { name: "Harden checkpoint capture" });
    expect(sessionHeading).toBeInTheDocument();
    expect(document.querySelectorAll("[data-harness-deck-backdrop] [data-backdrop-harness]")).toHaveLength(3);
    const sessionCard = sessionHeading.closest("[data-session-ledger]");
    expect(sessionCard?.querySelector('[data-harness-logo="codex"]')).toBeInTheDocument();
    expect(sessionCard?.querySelector('[data-harness-artwork="codex"]')).toBeInTheDocument();
    expect(screen.getByText("Saved checks passed")).toBeInTheDocument();
    expect(screen.getByText(/Build one card per session/)).toBeInTheDocument();
    expect(screen.getAllByText("unmeasured").length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("button", { name: /Added/ }));
    expect(screen.getByText(/Showing the latest 2 of 7 captured items/)).toBeInTheDocument();
    expect(screen.getByText("Implemented normalized session events")).toBeInTheDocument();
    expect(screen.getByText("app/services/session_ledger.py")).toBeInTheDocument();
    const runChecks = screen.getByRole("button", { name: "Run saved checks for Harden checkpoint capture" });
    expect(runChecks).toHaveClass("h-11", "shrink-0", "whitespace-nowrap");
    fireEvent.click(runChecks);
    expect(mocks.verify.mutate).toHaveBeenCalledWith(
      {
        workspaceId: "workspace-1",
        checkpointId: "checkpoint-1",
        executeCommands: true,
      },
      expect.objectContaining({ onSuccess: expect.any(Function) }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Repair context and continue: Harden checkpoint capture" }));
    expect(screen.getByRole("dialog")).toHaveAccessibleName("Repair context and continue?");
    expect(screen.getByText(/Compaction loss cannot be measured yet/)).toBeInTheDocument();
    expect(screen.getByText(/Nothing is sent, pasted, restored, or overwritten automatically/)).toBeInTheDocument();
    expect(mocks.sessionContinue.mutateAsync).not.toHaveBeenCalled();
  });

  it.each([
    ["failed", "complete", "Checks failed"],
    ["stale", "complete", "Changed since check"],
    ["not_run", "incomplete", "Needs review"],
  ])("keeps %s session verification state explicit", (verificationStatus, captureStatus, expectedLabel) => {
    const checkpoint = checkpointFixture();
    checkpoint.verification.status = verificationStatus;
    checkpoint.capture_status = captureStatus;
    mocks.history.data = { checkpoints: [checkpoint] };

    render(<MemoryRouter><RunsPage /></MemoryRouter>);

    const expected = {
      "Checks failed": "Saved checks failed",
      "Changed since check": "Checks may be stale",
      "Needs review": "Saved context needs review",
    }[expectedLabel];
    expect(screen.getByText(expected)).toBeInTheDocument();
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
      ledgerItem("file-1", "app/services/session_ledger.py", "file", "observed", 3),
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
    counts: { base: 1, added: 7, changed: 1, missing: null, removed: 0 },
    truncated: { base: 0, added: 5, changed: 0, missing: 0, removed: 0 },
    compactions: [{ event_id: "compact-1", sequence_number: 5 }],
  };
}
