import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import {
  MemoryRouter,
  Route,
  Routes,
  useSearchParams,
} from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import NowPage from "./NowPage";
import RunsPage from "./RunsPage";

const mocks = vi.hoisted(() => ({
  workspace: {
    activeWorkspaceId: "workspace-1",
    activeWorkspace: {
      id: "workspace-1",
      name: "DaemonState",
      repo_path: "/workspace/daemonstate",
    },
    workspacesQuery: { isLoading: false },
    workspaces: [{
      id: "workspace-1",
      name: "DaemonState",
      repo_path: "/workspace/daemonstate",
    }],
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
  providers: {
    data: {
      providers: [
        {
          provider: "codex",
          name: "Codex",
          status: "ready",
          ready: true,
          code: "provider_ready",
          message: "Codex CLI is installed and signed in.",
          action: "Run task in Codex.",
        },
        {
          provider: "claude",
          name: "Claude Code",
          status: "configured",
          ready: true,
          code: "provider_configured",
          message: "Claude Code CLI has authentication configured. Live Claude Code plan or API access is not verified until a run starts.",
          action: "Run task in Claude Code.",
        },
        {
          provider: "opencode",
          name: "OpenCode",
          status: "configured",
          ready: true,
          code: "provider_configured",
          message: "OpenCode CLI is configured to try `opencode/big-pickle`. Live model access, service availability, and balance are not verified until a run starts.",
          action: "Run task in OpenCode.",
        },
      ],
    },
    isLoading: false,
    isError: false,
    error: null,
    isFetching: false,
    refetch: vi.fn(),
  },
  hookCalls: {
    latest: [],
    history: [],
    library: [],
    continuity: [],
    memory: [],
    providers: [],
    refresh: [],
  },
  capture: { isPending: false, error: null, mutate: vi.fn() },
  prepare: { isPending: false, isError: false, error: null, mutateAsync: vi.fn() },
  continuation: { isPending: false, error: null, mutateAsync: vi.fn() },
  openContinuation: { isPending: false, error: null, mutateAsync: vi.fn() },
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
  selectSession: { isPending: false, error: null, mutateAsync: vi.fn() },
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
  useSelectSessionFromLibrary: () => mocks.selectSession,
  useRunContinuation: () => mocks.continuation,
  useOpenContinuationHarness: () => mocks.openContinuation,
  useContinuationProviders: (workspaceId, options = {}) => {
    mocks.hookCalls.providers.push({ workspaceId, ...options });
    return mocks.providers;
  },
  useCaptureCheckpoint: () => mocks.capture,
  useCheckpointComparison: () => mocks.comparison,
  useVerifyCheckpoint: () => mocks.verify,
  useResumeCheckpoint: () => mocks.resume,
}));

beforeEach(() => {
  Object.values(mocks.hookCalls).forEach((calls) => calls.splice(0));
  mocks.workspace.activeWorkspace = {
    id: "workspace-1",
    name: "DaemonState",
    repo_path: "/workspace/daemonstate",
  };
  mocks.workspace.workspaces = [mocks.workspace.activeWorkspace];
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
      cwd: "/workspace/daemonstate",
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
  mocks.providers.data = {
    active_run: null,
    latest_run: null,
    providers: [
      {
        provider: "codex",
        name: "Codex",
        status: "ready",
        ready: true,
        code: "provider_ready",
        message: "Codex CLI is installed and signed in.",
        action: "Run task in Codex.",
      },
      {
        provider: "claude",
        name: "Claude Code",
        status: "configured",
        ready: true,
        code: "provider_configured",
        message: "Claude Code CLI has authentication configured. Live Claude Code plan or API access is not verified until a run starts.",
        action: "Run task in Claude Code.",
      },
      {
        provider: "opencode",
        name: "OpenCode",
        status: "configured",
        ready: true,
        code: "provider_configured",
        message: "OpenCode CLI is configured to try `opencode/big-pickle`. Live model access, service availability, and balance are not verified until a run starts.",
        action: "Run task in OpenCode.",
      },
    ],
  };
  mocks.providers.isLoading = false;
  mocks.providers.isError = false;
  mocks.providers.error = null;
  mocks.providers.isFetching = false;
  mocks.providers.refetch.mockReset().mockResolvedValue({});
  mocks.capture.isPending = false;
  mocks.capture.error = null;
  mocks.capture.mutate.mockReset();
  mocks.prepare.isPending = false;
  mocks.prepare.isError = false;
  mocks.prepare.error = null;
  mocks.prepare.mutateAsync.mockReset().mockResolvedValue({
    markdown: "# Prepared context",
  });
  mocks.continuation.isPending = false;
  mocks.continuation.error = null;
  mocks.continuation.mutateAsync.mockReset().mockResolvedValue({
    schema_version: "continuation.run.v1",
    status: "verified",
    preparation: {
      schema_version: "continuation.v1",
      objective: "Harden checkpoint capture",
    },
    delivery: {
      status: "delivered",
      provider: "claude",
      source_provider: "codex",
      provider_switched: true,
      mode: "fresh",
      run_id: "run-1",
    },
    run: {
      run_id: "run-1",
      status: "completed",
      changed_files: ["frontend/src/pages/NowPage.jsx", "frontend/src/api/hooks.js"],
      verification_results: [],
    },
    outcome: {
      status: "verified",
      verified: true,
      changed_files: ["frontend/src/pages/NowPage.jsx", "frontend/src/api/hooks.js"],
      checks: {
        status: "passed",
        total: 2,
        passed: 2,
        failed: 0,
        items: [],
      },
    },
  });
  mocks.openContinuation.isPending = false;
  mocks.openContinuation.error = null;
  mocks.openContinuation.mutateAsync.mockReset().mockResolvedValue({
    launch: { launched: true },
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
  mocks.selectSession.isPending = false;
  mocks.selectSession.error = null;
  mocks.selectSession.mutateAsync.mockReset().mockResolvedValue({});
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: { writeText: vi.fn().mockResolvedValue(undefined) },
  });
});

describe("checkpoint product loop", () => {
  it("shows current work and a complete structured checkpoint on Now", () => {
    render(<MemoryRouter><NowPage /></MemoryRouter>);

    expect(screen.getAllByRole("heading", { name: "Harden checkpoint capture" })).toHaveLength(1);
    expect(screen.getByRole("heading", { name: "Continue with full context", level: 1 })).toBeInTheDocument();
    expect(screen.queryByText("Active task")).not.toBeInTheDocument();
    expect(screen.getAllByText("Observed work").length).toBeGreaterThan(0);
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
    const codexProvider = screen.getByRole("button", { name: "Run task in Codex" });
    const claudeProvider = screen.getByRole("button", { name: "Run task in Claude Code" });
    const openCodeProvider = screen.getByRole("button", { name: "Run task in OpenCode" });
    expect(codexProvider).toBeEnabled();
    expect(claudeProvider).toBeEnabled();
    expect(openCodeProvider).toBeEnabled();
    expect(within(codexProvider).getByText("Ready")).toBeInTheDocument();
    expect(within(claudeProvider).getByText("Configured")).toBeInTheDocument();
    expect(within(openCodeProvider).getByText("Configured")).toBeInTheDocument();
    expect(openCodeProvider).toHaveTextContent(
      "Live model access, service availability, and balance are not verified until a run starts.",
    );
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
    expect(mocks.hookCalls.continuity).toEqual([]);
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

    expect(screen.getByRole("heading", { name: "Continue with full context", level: 1 })).toBeInTheDocument();
    expect(screen.getByText("Loading activity")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run task in Codex" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Run task in Claude Code" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Run task in OpenCode" })).toBeDisabled();
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
    expect(mocks.hookCalls.continuity).toEqual([]);
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

    expect(screen.getByRole("button", { name: "Run task in Codex" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Loading linked task…" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Save current context" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Choose work" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Choose a linked task" })).not.toBeInTheDocument();
  });

  it("keeps saved context and memory available when the initial digest fails", () => {
    mocks.digest.data = null;
    mocks.digest.isLoading = false;
    mocks.digest.isError = true;
    mocks.digest.error = new Error("Digest timed out");

    render(<MemoryRouter><NowPage /></MemoryRouter>);

    expect(screen.getByRole("heading", { name: "Continue with full context", level: 1 })).toBeInTheDocument();
    expect(screen.getByText("Activity unavailable")).toBeInTheDocument();
    expect(screen.getByText("Could not load current activity")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Latest recovery point" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "What the project remembers now" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run task in Codex" })).toBeEnabled();
    expect(screen.getByText(/Live activity is unavailable/)).toBeInTheDocument();
  });

  it("keeps cached activity visible when a background digest refresh fails", () => {
    mocks.digest.isError = true;
    mocks.digest.error = new Error("Refresh timed out");

    render(<MemoryRouter><NowPage /></MemoryRouter>);

    expect(screen.getByRole("heading", { name: "Continue with full context", level: 1 })).toBeInTheDocument();
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
    expect(screen.getAllByText(/boundary time could not be verified/)).toHaveLength(1);
    expect(screen.getByText(/boundary time is unknown.*reconciles it automatically/i)).toBeInTheDocument();
  });

  it("keeps saved checkpoints read-only while session sources load", () => {
    mocks.library.data = { sessions: [] };
    mocks.library.isLoading = true;
    mocks.continuity.data = { sessions: [] };
    mocks.continuity.isLoading = true;

    render(<MemoryRouter><NowPage /></MemoryRouter>);

    expect(screen.queryByRole("button", { name: "Checking resume availability…" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Verify checkpoint" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Resume task" })).not.toBeInTheDocument();
    expect(screen.getByText(/Continue reconciles this snapshot/)).toBeInTheDocument();
  });

  it("does not expose the clipboard resume dialog on Now", () => {
    render(<MemoryRouter><NowPage /></MemoryRouter>);

    expect(screen.queryByRole("button", { name: "Resume task" })).not.toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: "Review and resume" })).not.toBeInTheDocument();
    expect(screen.queryByText(/copy context/i)).not.toBeInTheDocument();
  });

  it("shows only the bounded task contract from a screenshot attachment envelope", () => {
    const attachmentEnvelope = `# Files mentioned by the user:

## Screenshot 2026-07-23 at 16.42.18.png: /var/folders/example/TemporaryItems/NSIRD_screencaptureui_abc/Screenshot 2026-07-23 at 16.42.18.png

## My request for Codex:
Remove screenshot IDs and temporary paths from the Now page.
<image name=[Image #1] path="/var/folders/example/TemporaryItems/NSIRD_screencaptureui_abc/Screenshot 2026-07-23 at 16.42.18.png">
</image>`;
    render(
      <MemoryRouter initialEntries={[
        `/app?objective=${encodeURIComponent(attachmentEnvelope)}`,
      ]}>
        <NowPage />
      </MemoryRouter>,
    );

    expect(screen.getByRole("definition", {
      name: "Remove screenshot IDs and temporary paths from the Now page",
    })).toBeInTheDocument();
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

    expect(screen.getByRole("heading", { name: "Continue with full context", level: 1 })).toBeInTheDocument();
    expect(screen.queryByText(/Screenshot 2026-07-23/)).not.toBeInTheDocument();
    expect(screen.queryByText(/\/var\/folders/)).not.toBeInTheDocument();
  });

  it("never treats conversationId as work and uses the root session title", async () => {
    mocks.digest.data.current_goal = { title: "conversationId" };
    mocks.digest.data.activity.recent_sessions[0] = {
      ...mocks.digest.data.activity.recent_sessions[0],
      request: "Continue from the latest state.",
      latest_topic: "conversationId",
      title: "conversationId",
      session_title: "Fix harness continuation workflow",
    };

    render(<MemoryRouter><NowPage /></MemoryRouter>);

    expect(screen.queryByRole("definition", { name: "conversationId" })).not.toBeInTheDocument();
    expect(screen.getByRole("definition", {
      name: "Fix harness continuation workflow",
    })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Run task in Codex" }));
    await waitFor(() => expect(mocks.continuation.mutateAsync).toHaveBeenCalled());
    const request = mocks.continuation.mutateAsync.mock.calls.at(-1)[0];
    expect(request).toMatchObject({
      target_provider: "codex",
    });
    expect(request).not.toHaveProperty("objective");
    expect(request).not.toHaveProperty("source_provider");
    expect(request).not.toHaveProperty("source_session_id");
    expect(request).not.toHaveProperty("checkpoint_id");
  });

  it("ignores a poisoned selected activity and continues the newest viable root session", async () => {
    mocks.digest.data.activity.primary = {
      ...mocks.digest.data.activity.primary,
      selected_topic: (
      "Note that collaboration tools cannot be called from inside functions"
      ),
      request: "Diagnostic imported request",
      latest_topic: "Diagnostic extracted topic",
      title: "Note that collaboration tools cannot be called from inside functions",
      session_title: "Note that collaboration tools cannot be called from inside functions",
      session_id: "poisoned-selected-session",
      updated_at: "2026-07-25T10:00:00Z",
    };
    mocks.digest.data.activity.recent_sessions = [{
      ...mocks.digest.data.activity.recent_sessions[0],
      session_id: "newest-root-session",
      session_title: "Continue AI Infra strategy",
      title: "Fix harness continuation workflow",
      request: "Diagnostic imported request",
      latest_topic: "Diagnostic extracted topic",
      source_activity_at: "2026-07-25T09:59:00Z",
    }];

    render(<MemoryRouter><NowPage /></MemoryRouter>);

    expect(screen.queryByRole("definition", {
      name: "Note that collaboration tools cannot be called from inside functions",
    })).not.toBeInTheDocument();
    expect(screen.getByRole("definition", {
      name: "Fix harness continuation workflow",
    })).toBeInTheDocument();
    expect(screen.queryByRole("definition", {
      name: "Diagnostic imported request",
    })).not.toBeInTheDocument();
    expect(screen.queryByRole("definition", {
      name: "Diagnostic extracted topic",
    })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Run task in Codex" }));
    await waitFor(() => expect(mocks.continuation.mutateAsync).toHaveBeenCalled());
    const request = mocks.continuation.mutateAsync.mock.calls.at(-1)[0];
    expect(request).not.toHaveProperty("objective");
    expect(request).not.toHaveProperty("source_provider");
    expect(request).not.toHaveProperty("source_session_id");
    expect(request).not.toHaveProperty("checkpoint_id");
  });

  it("keeps Continue enabled for an exact source even when its display title is rejected", async () => {
    mocks.digest.data.current_goal = { title: "conversationId" };
    mocks.digest.data.activity.recent_sessions = [{
      ...mocks.digest.data.activity.recent_sessions[0],
      session_id: "source-with-limited-display",
      session_title: "conversationId",
      title: "You are an agent in a team of agents",
    }];

    render(
      <MemoryRouter initialEntries={[
        "/app?source_provider=codex&source_session=source-with-limited-display",
      ]}>
        <NowPage />
      </MemoryRouter>,
    );

    expect(screen.getByRole("definition", {
      name: "Task will be resolved from the selected session",
    })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run task in Codex" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Run task in Codex" }));

    await waitFor(() => expect(mocks.continuation.mutateAsync).toHaveBeenCalled());
    const request = mocks.continuation.mutateAsync.mock.calls.at(-1)[0];
    expect(request).toMatchObject({
      source_provider: "codex",
      source_session_id: "source-with-limited-display",
      target_provider: "codex",
    });
    expect(request).not.toHaveProperty("objective");
  });

  it("runs the complete continuation workflow and reports the observed target outcome", async () => {
    render(<MemoryRouter><NowPage /></MemoryRouter>);

    expect(screen.queryByRole("link", { name: "Inspect evidence" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /browser fallback/i })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Run task in Claude Code" }));

    await waitFor(() => expect(mocks.continuation.mutateAsync).toHaveBeenCalledWith({
      idempotency_key: expect.any(String),
      repo_path: "/workspace/context-engine",
      target_provider: "claude",
      workspace_id: "workspace-1",
    }));
    expect(navigator.clipboard.writeText).not.toHaveBeenCalled();
    const status = await screen.findByRole("status");
    expect(status).toHaveTextContent("Observed run passed verification");
    expect(status).toHaveTextContent("Fresh Claude Code agent · switched from Codex");
    expect(status).toHaveTextContent("2 changed files");
    expect(status).toHaveTextContent("frontend/src/pages/NowPage.jsx");
    expect(status).toHaveTextContent("2/2 passed");
    expect(mocks.capture.mutate).not.toHaveBeenCalled();
  });

  it("advances the five-feature workflow only after the prerequisite is verified", async () => {
    mocks.continuation.mutateAsync.mockResolvedValue({
      schema_version: "continuation.run.v1",
      status: "verified",
      delivery: {
        status: "delivered",
        provider: "codex",
        source_provider: "codex",
        provider_switched: false,
        mode: "fresh",
      },
      run: {
        status: "completed",
        changed_files: ["app/services/task_workflow.py"],
        verification_results: [],
      },
      outcome: {
        status: "verified",
        verified: true,
        changed_files: ["app/services/task_workflow.py"],
        checks: {
          status: "passed",
          total: 1,
          passed: 1,
          failed: 0,
          items: [],
        },
        task_transition: {
          status: "completed",
          completed_task: "Feature 3 · verified context compiler",
          workflow_after: {
            now: [{ title: "Feature 4 · automatic cross-harness delivery" }],
            blocked: [],
            next: [{ title: "Feature 5 · external handoff evaluation" }],
            paused: [
              { title: "Feature 1 · graph map" },
              { title: "Feature 2 · memory inbox" },
            ],
          },
        },
      },
    });
    render(<MemoryRouter><NowPage /></MemoryRouter>);

    fireEvent.click(screen.getByRole("button", { name: "Run task in Codex" }));

    const status = await screen.findByRole("status");
    expect(status).toHaveTextContent("Workflow advanced after verification");
    expect(status).toHaveTextContent("Now");
    expect(status).toHaveTextContent("Feature 4 · automatic cross-harness delivery");
    expect(status).toHaveTextContent("Next");
    expect(status).toHaveTextContent("Feature 5 · external handoff evaluation");
    expect(status).toHaveTextContent("Paused");
    expect(status).toHaveTextContent("Feature 1 · graph map");
    expect(status).toHaveTextContent("Feature 2 · memory inbox");
  });

  it.each([
    ["Codex", "codex"],
    ["Claude Code", "claude"],
    ["OpenCode", "opencode"],
  ])("runs the shared continuation through the selected %s provider", async (label, provider) => {
    render(<MemoryRouter><NowPage /></MemoryRouter>);

    fireEvent.click(screen.getByRole("button", { name: `Run task in ${label}` }));

    await waitFor(() => expect(mocks.continuation.mutateAsync).toHaveBeenCalledWith(
      expect.objectContaining({
        target_provider: provider,
        workspace_id: "workspace-1",
      }),
    ));
    const request = mocks.continuation.mutateAsync.mock.calls.at(-1)[0];
    expect(request).not.toHaveProperty("objective");
    expect(request).not.toHaveProperty("source_provider");
    expect(request).not.toHaveProperty("source_session_id");
    expect(request).not.toHaveProperty("checkpoint_id");
  });

  it("uses an explicit URL title for display but lets the exact source resolve execution", async () => {
    const rawObjective = "Fix the revoked Claude token without losing adapter context";

    render(
      <MemoryRouter initialEntries={[
        `/app?objective=${encodeURIComponent(rawObjective)}&repo_path=${encodeURIComponent("/workspace/explicit-session")}&source_provider=claude&source_session=explicit-session`,
      ]}>
        <NowPage />
      </MemoryRouter>,
    );

    expect(screen.getByRole("definition", { name: rawObjective })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Run task in OpenCode" }));
    await waitFor(() => expect(mocks.continuation.mutateAsync).toHaveBeenCalled());
    const request = mocks.continuation.mutateAsync.mock.calls.at(-1)[0];
    expect(request).toMatchObject({
      repo_path: "/workspace/explicit-session",
      source_provider: "claude",
      source_session_id: "explicit-session",
      target_provider: "opencode",
    });
    expect(request).not.toHaveProperty("objective");
  });

  it("preserves a human-authored failed-run diagnostic on an exact source", async () => {
    const diagnosticObjective = (
      "Concrete evidence from data/context.db: latest failed run "
      + "c526bac6447b4ece9ced31e594e43ebf command was "
      + "/Users/darshann/.npm-global/bin/codex exec --json. Exit 1."
    );

    render(
      <MemoryRouter initialEntries={[
        `/app?objective=${encodeURIComponent(diagnosticObjective)}&objective_source=session&repo_path=${encodeURIComponent("/workspace/context-engine")}&source_provider=codex&source_session=session-1`,
      ]}>
        <NowPage />
      </MemoryRouter>,
    );

    expect(screen.getByRole("definition", {
      name: /Concrete evidence from data\/context\.db/i,
    })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Run task in OpenCode" }));
    await waitFor(() => expect(mocks.continuation.mutateAsync).toHaveBeenCalled());
    const request = mocks.continuation.mutateAsync.mock.calls.at(-1)[0];
    expect(request).toMatchObject({
      repo_path: "/workspace/context-engine",
      source_provider: "codex",
      source_session_id: "session-1",
      target_provider: "opencode",
    });
    expect(request.objective).toContain("Concrete evidence from data/context.db");
  });

  it("passes a source-backed session objective through exact source validation", async () => {
    const sourceObjective = "Build one card per session.";

    render(
      <MemoryRouter initialEntries={[
        `/app?objective=${encodeURIComponent(sourceObjective)}&objective_source=session&repo_path=${encodeURIComponent("/workspace/source-session")}&source_provider=codex&source_session=source-session`,
      ]}>
        <NowPage />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Run task in Claude Code" }));
    await waitFor(() => expect(mocks.continuation.mutateAsync).toHaveBeenCalledWith(
      expect.objectContaining({
        objective: "Build one card per session",
        repo_path: "/workspace/source-session",
        source_provider: "codex",
        source_session_id: "source-session",
        target_provider: "claude",
      }),
    ));
  });

  it("shows signed-out Claude as requiring sign-in and keeps ready alternatives usable", () => {
    mocks.providers.data.providers = mocks.providers.data.providers.map((provider) => (
      provider.provider === "claude"
        ? {
            ...provider,
            status: "authentication_required",
            ready: false,
            code: "provider_authentication_required",
            message: "Claude Code CLI is installed, but it is not signed in.",
            action: "Run `claude auth login` and try again.",
          }
        : provider
    ));

    render(<MemoryRouter><NowPage /></MemoryRouter>);

    const claude = screen.getByRole("button", { name: "Run task in Claude Code" });
    expect(claude).toBeDisabled();
    expect(claude).toHaveAttribute("data-provider-ready", "false");
    expect(within(claude).getByText("Sign in")).toBeInTheDocument();
    expect(claude).toHaveTextContent("Claude Code CLI is installed, but it is not signed in.");
    expect(claude).toHaveTextContent("Next: Run `claude auth login` and try again.");
    expect(screen.getByRole("button", { name: "Run task in Codex" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Run task in OpenCode" })).toBeEnabled();
    const retry = screen.getByRole("button", { name: "Retry provider readiness" });
    fireEvent.click(retry);
    expect(mocks.providers.refetch).toHaveBeenCalledTimes(1);

    fireEvent.click(claude);
    expect(mocks.continuation.mutateAsync).not.toHaveBeenCalled();
  });

  it("fails closed when OpenCode reports access_required with ready=true", () => {
    mocks.providers.data.providers = mocks.providers.data.providers.map((provider) => (
      provider.provider === "opencode"
        ? {
            ...provider,
            status: "access_required",
            ready: true,
            code: "provider_model_access_required",
            message: "OpenCode CLI is installed, but `opencode/big-pickle` is not available to this account.",
            action: "Choose a model with active access, then check again.",
          }
        : provider
    ));

    render(<MemoryRouter><NowPage /></MemoryRouter>);

    const openCode = screen.getByRole("button", { name: "Run task in OpenCode" });
    expect(openCode).toBeDisabled();
    expect(openCode).toHaveAttribute("data-provider-ready", "false");
    expect(within(openCode).getByText("Access needed")).toBeInTheDocument();
    expect(openCode).toHaveTextContent(
      "OpenCode CLI is installed, but `opencode/big-pickle` is not available to this account.",
    );
    expect(openCode).toHaveTextContent(
      "Next: Choose a model with active access, then check again.",
    );
    expect(screen.getByRole("button", { name: "Run task in Codex" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Run task in Claude Code" })).toBeEnabled();

    fireEvent.click(openCode);
    expect(mocks.continuation.mutateAsync).not.toHaveBeenCalled();
  });

  it.each([
    {
      status: "configuration_required",
      code: "provider_configuration_required",
      reportedReady: true,
      label: "Setup needed",
      message: "Claude Code launcher is present, but CLI setup is incomplete.",
      action: "Finish Claude Code CLI setup, then check again.",
    },
    {
      status: "unavailable",
      code: "provider_cli_not_found",
      reportedReady: true,
      label: "Not installed",
      message: "Claude Code CLI is not installed or is not on PATH.",
      action: "Install the Claude Code CLI and try again.",
    },
  ])("renders $label as a distinct non-runnable provider state", ({
    status,
    code,
    reportedReady,
    label,
    message,
    action,
  }) => {
    mocks.providers.data.providers = mocks.providers.data.providers.map((provider) => (
      provider.provider === "claude"
        ? {
            ...provider,
            status,
            ready: reportedReady,
            code,
            message,
            action,
          }
        : provider
    ));

    render(<MemoryRouter><NowPage /></MemoryRouter>);

    const claude = screen.getByRole("button", { name: "Run task in Claude Code" });
    expect(claude).toBeDisabled();
    expect(claude).toHaveAttribute("data-provider-ready", "false");
    expect(within(claude).getByText(label)).toBeInTheDocument();
    expect(claude).toHaveTextContent(message);
    expect(claude).toHaveTextContent(`Next: ${action}`);
  });

  it("shows provider probes as checking instead of unavailable", () => {
    mocks.providers.data = { providers: [] };
    mocks.providers.isLoading = true;

    render(<MemoryRouter><NowPage /></MemoryRouter>);

    for (const label of ["Codex", "Claude Code", "OpenCode"]) {
      const provider = screen.getByRole("button", { name: `Run task in ${label}` });
      expect(provider).toBeDisabled();
      expect(within(provider).getByText("Checking")).toBeInTheDocument();
    }
  });

  it("keeps the running state visible when background session refresh changes the task key", () => {
    mocks.continuation.mutateAsync.mockImplementation(() => new Promise(() => {}));
    const view = render(<MemoryRouter><NowPage /></MemoryRouter>);

    fireEvent.click(screen.getByRole("button", { name: "Run task in OpenCode" }));

    const status = screen.getByRole("status");
    expect(status).toHaveAttribute("aria-busy", "true");
    expect(status).toHaveTextContent("Resolving the task and starting its harness");
    expect(status).toHaveTextContent(
      "Context Engine captures changed files and runs verification after the agent exits",
    );
    expect(screen.getByRole("button", { name: "Run task in OpenCode" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Run task in OpenCode" })).toHaveAttribute("data-provider-pending", "true");
    expect(screen.getByRole("button", { name: "Run task in OpenCode" })).toHaveClass("disabled:cursor-wait");
    expect(within(screen.getByRole("button", { name: "Run task in OpenCode" })).getByText("Running")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run task in Codex" })).toHaveAttribute("data-provider-pending", "false");

    mocks.digest.data.activity.recent_sessions[0] = {
      ...mocks.digest.data.activity.recent_sessions[0],
      session_title: "Background refresh imported a newer session title",
      title: "Background refresh imported a newer session title",
      session_id: "background-refresh-session",
      source_activity_at: "2026-07-25T16:04:00Z",
    };
    view.rerender(<MemoryRouter><NowPage /></MemoryRouter>);

    expect(screen.getByRole("status")).toHaveTextContent("Automatic continuation in progress");
    expect(screen.getByRole("button", { name: "Run task in OpenCode" })).toHaveAttribute("data-provider-pending", "true");
  });

  it("restores a visible Codex harness run after reload and prevents a duplicate click", async () => {
    mocks.providers.data.active_run = {
      run_id: "active-codex-run",
      provider: "codex",
      model: "codex",
      objective: "Finish the continuation workflow",
      status: "running",
      phase: "agent_running",
      started_at: "2026-07-25T16:03:36Z",
      harness_session: {
        provider: "codex",
        session_id: "019f9a4d-f586-79d3-b305-4844518003bd",
        launched: true,
        navigation_requested: true,
        navigation_verified: false,
        mode: "desktop_app",
        navigation: "session",
        exact_session_supported: true,
      },
    };

    render(<MemoryRouter><NowPage /></MemoryRouter>);

    const codex = screen.getByRole("button", { name: "Run task in Codex" });
    expect(codex).toBeDisabled();
    expect(codex).toHaveAttribute("aria-busy", "true");
    expect(codex).toHaveAttribute("data-provider-pending", "true");
    expect(codex).toHaveClass("disabled:cursor-wait");
    expect(screen.getByRole("status")).toHaveTextContent("Codex continuation in progress");
    expect(screen.getByRole("status")).toHaveTextContent("Reloading will not start another copy");
    expect(screen.getByRole("status")).toHaveTextContent(
      "Codex was asked to show this exact thread automatically",
    );

    fireEvent.click(codex);
    expect(mocks.continuation.mutateAsync).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Open Codex run" }));
    await waitFor(() => expect(mocks.openContinuation.mutateAsync).toHaveBeenCalledWith({
      workspaceId: "workspace-1",
      runId: "active-codex-run",
    }));
  });

  it("restores a terminal continuation after reload and leaves retry enabled", () => {
    mocks.providers.data.latest_run = {
      run_id: "failed-opencode-run",
      provider: "opencode",
      tool: "context-engine:opencode",
      model: "opencode/big-pickle",
      objective: "Finish the continuation workflow",
      status: "failed",
      completed: false,
      verified_success: false,
      failed_verification: false,
      unresolved_blocker: true,
      outcome_summary: "OpenCode exited after repeated provider errors.",
      changed_files: [],
      verification: {
        observed: 0,
        passed: 0,
        failed: 0,
      },
    };

    render(<MemoryRouter><NowPage /></MemoryRouter>);

    const opencode = screen.getByRole("button", { name: "Run task in OpenCode" });
    expect(opencode).toBeEnabled();
    expect(opencode).toHaveAttribute("aria-busy", "false");
    expect(screen.getByRole("alert")).toHaveTextContent("OpenCode continuation failed");
    expect(screen.getByRole("alert")).toHaveTextContent("OpenCode exited after repeated provider errors");
    expect(screen.getByRole("alert")).toHaveTextContent("No successful handoff is being claimed");
    expect(screen.queryByText("Open run history")).not.toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Recorded run failed-o has no linked harness session",
    );
  });

  it("opens the exact Codex thread for a persisted local timeout", async () => {
    mocks.providers.data.latest_run = {
      run_id: "timed-out-codex-run",
      provider: "codex",
      tool: "context-engine:codex",
      model: "codex",
      objective: "Finish the continuation workflow",
      status: "failed",
      completed: false,
      verified_success: false,
      failure_code: "provider_run_timed_out",
      outcome_summary: "Codex did not finish before the continuation timeout.",
      changed_files: ["app/services/continuation_runtime.py"],
      harness_session: {
        provider: "codex",
        session_id: "019f9a4d-f586-79d3-b305-4844518003bd",
        launched: true,
        navigation_requested: true,
        navigation_verified: false,
        mode: "desktop_app",
        navigation: "session",
        exact_session_supported: true,
      },
      verification: {
        observed: 0,
        passed: 0,
        failed: 0,
      },
    };

    render(<MemoryRouter><NowPage /></MemoryRouter>);

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent(
      "Review the recorded changes, finish any incomplete work, and retry only if work remains.",
    );
    expect(alert).not.toHaveTextContent("provider is available");
    expect(alert).toHaveTextContent(
      "Codex was asked to show this exact thread automatically",
    );
    fireEvent.click(screen.getByRole("button", { name: "Open Codex run" }));
    await waitFor(() => expect(mocks.openContinuation.mutateAsync).toHaveBeenCalledWith({
      workspaceId: "workspace-1",
      runId: "timed-out-codex-run",
    }));
  });

  it("uses a preserved recovery objective without silently dropping its checkpoint intent", async () => {
    render(
      <MemoryRouter initialEntries={["/app?objective=Review%20Beta%20pricing&repo_path=%2Fworkspace%2Fselected-session&checkpoint=checkpoint-legacy&checkpoint_source=source-legacy"]}>
        <NowPage />
      </MemoryRouter>,
    );

    expect(screen.getByRole("definition", { name: "Review Beta pricing" })).toBeInTheDocument();
    expect(screen.getByText("Recovery request · checkpoint-legacy")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Run task in Codex" }));

    await waitFor(() => expect(mocks.continuation.mutateAsync).toHaveBeenCalledWith({
      objective: "Review Beta pricing",
      checkpoint_id: "checkpoint-legacy",
      checkpoint_source_id: "source-legacy",
      idempotency_key: expect.any(String),
      provider_effort: "medium",
      provider_model: "gpt-5.6-sol",
      repo_path: "/workspace/selected-session",
      target_provider: "codex",
      workspace_id: "workspace-1",
    }));
  });

  it("does not claim success when the run has no observed changes or checks", async () => {
    mocks.continuation.mutateAsync.mockResolvedValue({
      schema_version: "continuation.run.v1",
      status: "completed_unverified",
      delivery: {
        status: "delivered",
        provider: "codex",
        source_provider: "codex",
        provider_switched: false,
        mode: "fresh",
      },
      run: {
        status: "completed",
        changed_files: [],
        verification_results: [],
        command: { stdout: "Audited the configuration and confirmed no code change was required." },
      },
      outcome: {
        status: "completed_unverified",
        verified: false,
        changed_files: [],
        checks: { status: "not_run", total: 0, passed: 0, failed: 0, items: [] },
      },
    });
    render(<MemoryRouter><NowPage /></MemoryRouter>);

    fireEvent.click(screen.getByRole("button", { name: "Run task in Codex" }));

    const status = await screen.findByRole("status");
    expect(status).toHaveTextContent("Agent run completed");
    expect(status).toHaveTextContent("Fresh Codex agent");
    expect(status).toHaveTextContent("No repository file changes observed");
    expect(status).toHaveTextContent("No verification checks ran");
    expect(status).toHaveTextContent("Audited the configuration and confirmed no code change was required");
    expect(status).toHaveTextContent("successful task continuation is not proven");
    expect(status).not.toHaveTextContent(/successful handoff/i);
  });

  it("shows the backend blocker instead of sending the user to inspect context", async () => {
    mocks.continuation.mutateAsync.mockRejectedValue(
      new Error("No installed target agent is available."),
    );
    render(<MemoryRouter><NowPage /></MemoryRouter>);

    fireEvent.click(screen.getByRole("button", { name: "Run task in Codex" }));

    const blocker = await screen.findByRole("alert");
    expect(blocker).toHaveTextContent("Codex continuation blocked");
    expect(blocker).toHaveTextContent("No installed target agent is available");
    expect(blocker).toHaveTextContent("No successful handoff is being claimed");
    expect(screen.queryByRole("link", { name: "Inspect evidence" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /copy/i })).not.toBeInTheDocument();
  });

  it.each([
    ["provider_run_failed", "OpenCode exited with code 1."],
    ["provider_run_timed_out", "OpenCode exceeded the run timeout."],
    ["provider_invocation_invalid", "Context Engine constructed an invalid OpenCode invocation."],
  ])("reports %s as an OpenCode execution failure, not provider unavailability", async (code, message) => {
    const error = Object.assign(new Error(message), {
      detail: {
        blocker: {
          code,
          message,
          action: "Correct the execution failure, then retry.",
        },
      },
    });
    mocks.continuation.mutateAsync.mockRejectedValue(error);
    render(<MemoryRouter><NowPage /></MemoryRouter>);

    fireEvent.click(screen.getByRole("button", { name: "Run task in OpenCode" }));

    const blocker = await screen.findByRole("alert");
    expect(blocker).toHaveTextContent("OpenCode continuation failed");
    expect(blocker).toHaveTextContent(message);
    expect(blocker).not.toHaveTextContent("Target agent unavailable");
  });

  it.each([
    [
      "provider_billing_required",
      "OpenCode has insufficient balance.",
      "Provider access or billing required",
    ],
    [
      "provider_service_unavailable",
      "OpenCode's selected provider returned HTTP 500.",
      "Provider service unavailable",
    ],
  ])("reports %s with an exact provider blocker title", async (
    code,
    message,
    title,
  ) => {
    const error = Object.assign(new Error(message), {
      detail: {
        blocker: {
          code,
          message,
          action: "Choose another configured model or retry later.",
        },
      },
    });
    mocks.continuation.mutateAsync.mockRejectedValue(error);
    render(<MemoryRouter><NowPage /></MemoryRouter>);

    fireEvent.click(screen.getByRole("button", { name: "Run task in OpenCode" }));

    const blocker = await screen.findByRole("alert");
    expect(blocker).toHaveTextContent(title);
    expect(blocker).toHaveTextContent(message);
  });

  it("reports continuation_checks_failed as a verification failure", async () => {
    const error = Object.assign(new Error("The required checks did not pass."), {
      detail: {
        blocker: {
          code: "continuation_checks_failed",
          message: "The required checks did not pass.",
        },
      },
    });
    mocks.continuation.mutateAsync.mockRejectedValue(error);
    render(<MemoryRouter><NowPage /></MemoryRouter>);

    fireEvent.click(screen.getByRole("button", { name: "Run task in OpenCode" }));

    const blocker = await screen.findByRole("alert");
    expect(blocker).toHaveTextContent("Verification failed");
    expect(blocker).not.toHaveTextContent("Target agent unavailable");
  });

  it("names a structured blocker, its affected tasks, and the recovery action", async () => {
    mocks.continuation.mutateAsync.mockResolvedValue({
      schema_version: "continuation.run.v1",
      status: "blocked",
      blocker: {
        title: "Claude Code authentication failed",
        code: "oauth_revoked",
        message: "Claude authentication failed — its OAuth token has been revoked (401).",
        affected_tasks: [
          "Validate Claude adapter",
          "Cross-provider handoff test",
        ],
        action: "Reconnect Claude Code, then retry this continuation.",
      },
    });
    render(<MemoryRouter><NowPage /></MemoryRouter>);

    fireEvent.click(screen.getByRole("button", { name: "Run task in Claude Code" }));

    const blocker = await screen.findByRole("alert");
    expect(blocker).toHaveTextContent("Claude Code authentication failed");
    expect(blocker).toHaveTextContent("Claude authentication failed — its OAuth token has been revoked (401).");
    expect(blocker).toHaveTextContent("Affected tasks");
    expect(blocker).toHaveTextContent("Validate Claude adapter");
    expect(blocker).toHaveTextContent("Cross-provider handoff test");
    expect(blocker).toHaveTextContent("Next: Reconnect Claude Code, then retry this continuation.");
    expect(blocker).not.toHaveTextContent(/^Continuation blocked/);
  });

  it("treats failed verification as a real terminal blocker", async () => {
    mocks.continuation.mutateAsync.mockResolvedValue({
      schema_version: "continuation.run.v1",
      status: "failed",
      delivery: { status: "delivered", provider: "claude", mode: "fresh" },
      run: {
        status: "failed",
        changed_files: ["app/auth.py"],
        verification_results: [{
          requirement_id: "V2",
          command: "python3 -m pytest -q tests/test_auth.py",
          cwd: "/workspace/context-engine",
          result: {
            exit_code: 1,
            stdout: "FAILED tests/test_auth.py::test_callback - assertion failed",
            stderr: "",
          },
        }],
      },
      outcome: {
        status: "failed",
        verified: false,
        changed_files: ["app/auth.py"],
        checks: {
          status: "failed",
          total: 2,
          passed: 1,
          failed: 1,
          items: [{
            requirement_id: "V2",
            command: "python3 -m pytest -q tests/test_auth.py",
            status: "failed",
            exit_code: 1,
          }],
        },
      },
    });
    render(<MemoryRouter><NowPage /></MemoryRouter>);

    fireEvent.click(screen.getByRole("button", { name: "Run task in Claude Code" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("1 verification check failed");
    expect(alert).toHaveTextContent("Failed checks");
    expect(alert).toHaveTextContent("python3 -m pytest -q tests/test_auth.py");
    expect(alert).toHaveTextContent(
      "FAILED tests/test_auth.py::test_callback - assertion failed",
    );
  });

  it("clears a completed continuation when its repository or objective changes", async () => {
    const view = render(<MemoryRouter><NowPage /></MemoryRouter>);

    fireEvent.click(screen.getByRole("button", { name: "Run task in Codex" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Observed run passed verification");

    mocks.digest.data.activity.recent_sessions[0] = {
      ...mocks.digest.data.activity.recent_sessions[0],
      cwd: "/workspace/daemonstate-next",
    };
    view.rerender(<MemoryRouter><NowPage /></MemoryRouter>);

    await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Run task in Codex" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Observed run passed verification");
    await waitFor(() => expect(mocks.continuation.mutateAsync).toHaveBeenLastCalledWith(
      expect.objectContaining({ repo_path: "/workspace/daemonstate-next" }),
    ));

    mocks.digest.data.activity.recent_sessions[0] = {
      ...mocks.digest.data.activity.recent_sessions[0],
      session_title: "Verify the new continuation target",
      title: "Verify the new continuation target",
      session_id: "new-continuation-target",
      source_activity_at: "2026-07-22T10:00:00Z",
    };
    view.rerender(<MemoryRouter><NowPage /></MemoryRouter>);

    await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());
    expect(
      screen.getByRole("definition", { name: "Verify the new continuation target" }),
    ).toBeInTheDocument();
  });

  it("leads to session selection when no linked work can be continued", () => {
    mocks.workspace.activeWorkspace = { id: "workspace-1", name: "DaemonState" };
    mocks.workspace.workspaces = [mocks.workspace.activeWorkspace];
    mocks.latest.data = null;
    mocks.history.data = { checkpoints: [] };
    mocks.library.data = { sessions: [] };
    mocks.digest.data.current_goal = null;
    mocks.digest.data.activity.primary = null;
    mocks.digest.data.activity.recent_sessions = [];

    render(<MemoryRouter><NowPage /></MemoryRouter>);

    expect(screen.getByRole("link", { name: "Choose work to continue" })).toHaveAttribute("href", "/app/library");
    expect(screen.getByText("Choose linked work before continuing.")).toBeInTheDocument();
    expect(mocks.hookCalls.library.at(-1)).toMatchObject({ enabled: true });
  });

  it("does not enable a provider when only a repository can be resolved", () => {
    mocks.latest.data = null;
    mocks.history.data = { checkpoints: [] };
    mocks.library.data = { sessions: [] };
    mocks.digest.data.current_goal = null;
    mocks.digest.data.activity.primary = null;
    mocks.digest.data.activity.recent_sessions = [];

    render(<MemoryRouter><NowPage /></MemoryRouter>);

    expect(screen.getByRole("button", { name: "Run task in Codex" })).toBeDisabled();
    expect(screen.getByRole("link", { name: "Choose work to continue" })).toHaveAttribute("href", "/app/library");
  });

  it("displays the newest inferred session without pinning it before backend sync", async () => {
    mocks.digest.data.current_goal = { title: "Stale workspace goal" };
    mocks.digest.data.scope = { project_paths: ["/workspace/stale-scope"] };
    mocks.digest.data.activity.primary = {
      ...mocks.digest.data.activity.primary,
      request: "Stale selected activity",
      title: "Stale selected activity",
      cwd: "/workspace/stale-selected-activity",
    };
    mocks.digest.data.activity.recent_sessions[0] = {
      ...mocks.digest.data.activity.recent_sessions[0],
      session_title: "Continue the newest root session",
      title: "Continue the newest root session",
      session_id: "newest-root-session",
      cwd: "/workspace/newest-root-session",
    };

    render(<MemoryRouter><NowPage /></MemoryRouter>);
    expect(screen.getByRole("definition", {
      name: "Continue the newest root session",
    })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Run task in Codex" }));

    await waitFor(() => expect(mocks.continuation.mutateAsync).toHaveBeenCalled());
    const request = mocks.continuation.mutateAsync.mock.calls.at(-1)[0];
    expect(request).toMatchObject({
      repo_path: "/workspace/newest-root-session",
    });
    expect(request).not.toHaveProperty("objective");
    expect(request).not.toHaveProperty("source_provider");
    expect(request).not.toHaveProperty("source_session_id");
    expect(request).not.toHaveProperty("checkpoint_id");
  });

  it("captures context automatically instead of exposing a manual save action", () => {
    mocks.latest.data = null;
    render(<MemoryRouter><NowPage /></MemoryRouter>);

    expect(screen.queryByRole("button", { name: "Save current context" })).not.toBeInTheDocument();
    expect(screen.getByText(/Context is captured automatically during session sync and continuation/)).toBeInTheDocument();
    expect(screen.getByText(/No manual save is required/)).toBeInTheDocument();
    expect(mocks.capture.mutate).not.toHaveBeenCalled();
  });

  it("keeps checkpoint history read-only and delegates execution to Continue", () => {
    render(<MemoryRouter><NowPage /></MemoryRouter>);

    expect(screen.queryByRole("button", { name: "Verify checkpoint" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Resume task" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Save current context" })).not.toBeInTheDocument();
    expect(screen.getByText(/Continue reconciles this snapshot against current repository state/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run task in Codex" })).toBeInTheDocument();
    expect(mocks.verify.mutate).not.toHaveBeenCalled();
    expect(mocks.sessionContinue.mutateAsync).not.toHaveBeenCalled();
    expect(navigator.clipboard.writeText).not.toHaveBeenCalled();
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
    mocks.digest.data.activity.recent_sessions = [{
      ...mocks.digest.data.activity.recent_sessions[0],
      session_title: "Current observed task",
      title: "Current observed task",
      session_id: "current-session",
      source_activity_at: "2026-07-22T08:00:00Z",
      updated_at: "2026-07-22T08:00:00Z",
    }];

    render(<MemoryRouter><NowPage /></MemoryRouter>);

    expect(
      screen.getByRole("definition", { name: "Current observed task" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "No saved context for this task" })).toBeInTheDocument();
    expect(screen.getByText("Old checkpoint task")).toBeInTheDocument();
    expect(screen.getByText("Earlier saved context · another task")).toBeInTheDocument();
    expect(screen.getByText(/not being used as the current task’s next action/)).toBeInTheDocument();
    expect(screen.queryByText("Not the latest state — 10 events behind")).not.toBeInTheDocument();
    expect(screen.queryByText("Resume session")).not.toBeInTheDocument();
    expect(screen.queryByText("Wire checkpoint verification into Runs")).not.toBeInTheDocument();
    expect(screen.getByText("Continue will resolve the latest exact next action from the linked session.")).toBeInTheDocument();
  });

  it("uses the latest observed session without exposing checkpoint capture controls", async () => {
    mocks.latest.data = null;
    mocks.history.data = { checkpoints: [] };
    mocks.digest.data.activity.primary = {
      ...mocks.digest.data.activity.primary,
      provider: "codex",
      session_id: "current-session",
      state: "snapshot",
      evidence_level: "session_reported",
    };
    mocks.digest.data.activity.recent_sessions = [{
      ...mocks.digest.data.activity.recent_sessions[0],
      provider: "codex",
      session_id: "current-session",
      state: "snapshot",
      evidence_level: "session_reported",
    }];
    mocks.library.data.sessions = [{ connector_type: "opencode", session_id: "older-session" }];

    render(<MemoryRouter><NowPage /></MemoryRouter>);
    expect(screen.queryByRole("button", { name: "Save current context" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Run task in Codex" }));

    await waitFor(() => expect(mocks.continuation.mutateAsync).toHaveBeenCalledWith({
      idempotency_key: expect.any(String),
      provider_effort: "medium",
      provider_model: "gpt-5.6-sol",
      repo_path: "/workspace/context-engine",
      target_provider: "codex",
      workspace_id: "workspace-1",
    }));
    expect(mocks.capture.mutate).not.toHaveBeenCalled();
  });

  it("routes a source-backed History task into the canonical Continue screen", async () => {
    render(
      <MemoryRouter initialEntries={["/app/runs"]}>
        <Routes>
          <Route path="/app/runs" element={<RunsPage />} />
          <Route path="/app" element={<HistoryContinueDestination />} />
        </Routes>
      </MemoryRouter>,
    );
    const heading = screen.getByRole("heading", { name: "History" });
    expect(heading).toHaveClass("text-3xl", "font-black", "sm:text-4xl");
    expect(screen.getByText(/before choosing a task for Continue/)).toBeInTheDocument();
    expect(screen.getByText("One card. One session.")).toBeInTheDocument();
    expect(screen.queryByText("Items")).not.toBeInTheDocument();
    const sessionHeading = screen.getByRole("heading", { name: "Harden checkpoint capture" });
    expect(sessionHeading).toBeInTheDocument();
    expect(document.querySelectorAll("[data-harness-deck-backdrop] [data-backdrop-harness]")).toHaveLength(3);
    const sessionCard = sessionHeading.closest("[data-session-ledger]");
    expect(sessionCard?.querySelector('[data-harness-logo="codex"]')).toBeInTheDocument();
    expect(sessionCard?.querySelector('[data-harness-artwork="codex"]')).toBeInTheDocument();
    expect(sessionCard).toHaveTextContent("Ready for Continue — review context gaps");
    expect(sessionCard).not.toHaveTextContent(/Event \d+/);
    expect(sessionCard).not.toHaveTextContent("01");
    expect(screen.getByText(/Build one card per session/)).toBeInTheDocument();
    expect(screen.getByText("Unknown")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Since then/ }));
    expect(screen.getByText(/Showing the latest 1 of 7 session updates/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Progress" })).toBeInTheDocument();
    expect(screen.getByText("Implemented normalized session events")).toBeInTheDocument();
    expect(screen.queryByText("/Users/darshann/Desktop/daemonstate/tests/test_session_library.py")).not.toBeInTheDocument();
    expect(screen.queryByText("Run checks")).not.toBeInTheDocument();
    expect(screen.queryByText(/Repair/)).not.toBeInTheDocument();
    expect(mocks.verify.mutate).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Continue task: Harden checkpoint capture" }));
    expect(await screen.findByText("Canonical Continue destination")).toBeInTheDocument();
    expect(screen.getByText("codex · session-1")).toBeInTheDocument();
    expect(screen.getByText("Build one card per session · session")).toBeInTheDocument();
    expect(mocks.selectSession.mutateAsync).not.toHaveBeenCalled();
    expect(mocks.sessionContinue.mutateAsync).not.toHaveBeenCalled();
    expect(navigator.clipboard.writeText).not.toHaveBeenCalled();
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

    expect(screen.getByText("Ready for Continue — review context gaps")).toBeInTheDocument();
    expect(screen.queryByText(/Saved checks|Checks may be stale|Saved context needs review/)).not.toBeInTheDocument();
    expect(screen.queryByText("Run checks")).not.toBeInTheDocument();
  });
});

function HistoryContinueDestination() {
  const [params] = useSearchParams();
  return (
    <>
      <div>Canonical Continue destination</div>
      <div>{params.get("source_provider")} · {params.get("source_session")}</div>
      <div>{params.get("objective")} · {params.get("objective_source")}</div>
    </>
  );
}

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
      recent_sessions: [{
        kind: "agent_session",
        state: "snapshot",
        evidence_level: "session_reported",
        provider: "codex",
        tool: "codex",
        session_id: "session-1",
        source_document_id: "source-1",
        session_title: "Harden checkpoint capture",
        title: "Harden checkpoint capture",
        request: "Diagnostic imported request",
        latest_topic: "Diagnostic extracted topic",
        latest_update: "Implemented normalized session events.",
        branch: "codex/checkpoints",
        cwd: "/workspace/context-engine",
        source_activity_at: "2026-07-21T10:00:00Z",
        updated_at: "2026-07-21T10:00:00Z",
        changed_files: ["app/services/checkpoints.py"],
        verification: { observed: 1, passed: 1, failed: 0 },
        outcome: { summary: "Focused tests passed.", observed_at: "2026-07-21T10:00:00Z" },
      }],
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
        "/Users/darshann/Desktop/daemonstate/tests/test_session_library.py",
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
