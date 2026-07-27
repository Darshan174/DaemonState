import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { createHash } from "node:crypto";
import {
  MemoryRouter,
  Route,
  Routes,
  useSearchParams,
} from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import NowPage from "./NowPage";
import RunsPage from "./RunsPage";
import { copyReadySessionContextContent } from "./sessionContinuity";

function sha256Text(value) {
  return createHash("sha256").update(value, "utf8").digest("hex");
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
          context_staging_supported: true,
          code: "provider_ready",
          message: "Codex CLI is installed and signed in.",
          action: "Load context in Codex.",
          models: [
            {
              id: "gpt-5.6-sol",
              label: "GPT-5.6 Sol",
              default: true,
              reasoning_efforts: ["low", "medium", "high"],
              default_reasoning_effort: "medium",
            },
            {
              id: "gpt-5.6-terra",
              label: "GPT-5.6 Terra",
              default: false,
              reasoning_efforts: ["low", "medium", "high"],
              default_reasoning_effort: "medium",
            },
          ],
        },
        {
          provider: "claude",
          name: "Claude Code",
          status: "configured",
          ready: true,
          context_staging_supported: true,
          code: "provider_configured",
          message: "Claude Code CLI has authentication configured. Live Claude Code plan or API access is not verified until a run starts.",
          action: "Load context in Claude Code.",
        },
        {
          provider: "opencode",
          name: "OpenCode",
          status: "configured",
          ready: true,
          context_staging_supported: true,
          code: "provider_configured",
          message: "OpenCode CLI is configured to try `opencode/big-pickle`. Live model access, service availability, and balance are not verified until a run starts.",
          action: "Load context in OpenCode.",
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
  checkpointHandoff: { isPending: false, error: null, mutateAsync: vi.fn() },
  sessionContinue: { isPending: false, error: null, mutateAsync: vi.fn() },
  selectSession: { isPending: false, error: null, mutateAsync: vi.fn() },
  overlayStatus: {
    data: { available: true, visible: false },
    isLoading: false,
    isError: false,
    error: null,
  },
  overlayVisibility: { isPending: false, error: null, mutate: vi.fn() },
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
  useStageContinuation: () => mocks.continuation,
  useOpenContinuationHarness: () => mocks.openContinuation,
  useContinuationProviders: (workspaceId, options = {}) => {
    mocks.hookCalls.providers.push({ workspaceId, ...options });
    return mocks.providers;
  },
  useCaptureCheckpoint: () => mocks.capture,
  useCheckpointComparison: () => mocks.comparison,
  useVerifyCheckpoint: () => mocks.verify,
  useResumeCheckpoint: () => mocks.resume,
  useCheckpointHandoff: () => mocks.checkpointHandoff,
  useDesktopOverlayStatus: () => mocks.overlayStatus,
  useSetDesktopOverlayVisibility: () => mocks.overlayVisibility,
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
        context_staging_supported: true,
        code: "provider_ready",
        message: "Codex CLI is installed and signed in.",
        action: "Load context in Codex.",
        models: [{
          id: "gpt-5.6-sol",
          label: "GPT-5.6 Sol",
          default: true,
          reasoning_efforts: ["low", "medium", "high", "xhigh", "max", "ultra"],
          default_reasoning_effort: "medium",
        }],
      },
      {
        provider: "claude",
        name: "Claude Code",
        status: "configured",
        ready: true,
        context_staging_supported: true,
        code: "provider_configured",
        message: "Claude Code CLI has authentication configured. Live Claude Code plan or API access is not verified until a run starts.",
        action: "Load context in Claude Code.",
      },
      {
        provider: "opencode",
        name: "OpenCode",
        status: "configured",
        ready: true,
        context_staging_supported: true,
        code: "provider_configured",
        message: "OpenCode CLI is configured to try `opencode/big-pickle`. Live model access, service availability, and balance are not verified until a run starts.",
        action: "Load context in OpenCode.",
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
    schema_version: "continuation.stage.v1",
    status: "awaiting_user",
    preparation: {
      schema_version: "continuation.v1",
      objective: "Harden checkpoint capture",
      health_score: 0.96,
      readiness: {
        status: "ready",
        blocking_issues: [],
      },
      repository: {
        freshness: {
          status: "changed",
          reason: "The repository changed after the saved boundary.",
          checked_at: "2026-07-21T10:01:00Z",
        },
      },
      execution_contract: {
        schema_version: "continuation_execution.v1",
        task_mode: "change",
        task: {
          request_verbatim: "Harden checkpoint capture.\nPreserve the full request and verify the visible continuation flow.",
        },
        source_spans: [{
          id: "S3",
          kind: "constraint",
          text: "Prioritize quality over speed.",
        }],
        authority: {
          filesystem_mode: "workspace_write",
          command_mode: "execute",
          allow_product_edits: true,
          preserve_preexisting_changes: true,
        },
        requirements: [
          {
            id: "R1",
            text: "Preserve the authoritative request without truncation.",
            priority: "must",
            verification_ids: ["V1"],
          },
          {
            id: "R2",
            text: "Verify the visible continuation flow.",
            priority: "must",
            verification_ids: ["V2"],
          },
          {
            id: "R3",
            text: "Prioritize quality over speed.",
            priority: "context",
            source_span_ids: ["S3"],
            verification_ids: [],
          },
        ],
        definition_of_done: ["R1", "R2"],
        artifacts: [{
          id: "A1",
          kind: "screenshot",
          path: "attachments/reference.png",
          required: true,
          requirement_ids: ["R2"],
        }],
        verification: [
          {
            id: "V1",
            verifier_type: "unit_test",
            command_argv: ["npm", "test", "--", "--run"],
            requirement_ids: ["R1"],
          },
          {
            id: "V2",
            verifier_type: "browser_assertion",
            requirement_ids: ["R2"],
            rubric: "The continuation flow is visible.",
          },
        ],
      },
      manifest: {
        created_at: "2026-07-21T10:01:00Z",
        selected_context: [
          {
            id: "objective",
            title: "Harden checkpoint capture",
            summary: "The exact task selected for continuation.",
            lane: "instructions",
            truth_state: "user_stated",
            token_cost: 120,
          },
          {
            id: "decision",
            title: "Keep checkpoint items evidence-linked",
            summary: "A source-backed implementation decision.",
            lane: "decisions_and_invariants",
            truth_state: "reported",
            token_cost: 80,
          },
          {
            id: "file",
            title: "frontend/src/pages/NowPage.jsx",
            summary: "Repository file selected for the task.",
            lane: "code_and_tests",
            trust_zone: "trusted_repo",
            provenance_verified: true,
            token_cost: 240,
          },
        ],
        excluded_context: [{
          id: "stale",
          title: "Superseded layout note",
          reason: "stale",
          reason_detail: "A newer source revision replaced this note.",
          truth_state: "stale",
        }],
        token_accounting: {
          rendered_tokens: 18_420,
          budget: 24_000,
          remaining_tokens: 5_580,
          within_budget: true,
          estimation_method: "chars_div_4.v1",
        },
        repo_state: {
          relevant_files: [
            { path: "frontend/src/pages/NowPage.jsx" },
            { path: "frontend/src/api/hooks.js" },
          ],
        },
        verification: {
          commands: [{ id: "V1" }, { id: "V2" }],
        },
      },
    },
    delivery: {
      status: "staged",
      provider: "claude",
      source_provider: "codex",
      provider_switched: true,
      mode: "fresh",
      run_id: "run-1",
      context_delivery: "developer_instructions",
      harness_session: {
        provider: "claude",
        session_id: "staged-claude-thread",
        launched: true,
        navigation_requested: true,
        navigation_verified: false,
        exact_session_supported: true,
      },
    },
    run: {
      run_id: "run-1",
      provider: "claude",
      status: "awaiting_user",
      changed_files: [],
      verification_results: [],
    },
    outcome: {
      status: "awaiting_user",
      verified: false,
      changed_files: [],
      checks: {
        status: "not_run",
        total: 0,
        passed: 0,
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
  mocks.checkpointHandoff.isPending = false;
  mocks.checkpointHandoff.error = null;
  mocks.checkpointHandoff.mutateAsync.mockReset().mockResolvedValue(
    sessionHandoff("# Session-only pre-compaction handoff"),
  );
  mocks.sessionContinue.isPending = false;
  mocks.sessionContinue.error = null;
  mocks.sessionContinue.mutateAsync.mockReset().mockResolvedValue({
    content: "# Continue with recovered session context",
    launch: { launched: true },
  });
  mocks.selectSession.isPending = false;
  mocks.selectSession.error = null;
  mocks.selectSession.mutateAsync.mockReset().mockResolvedValue({});
  mocks.overlayStatus.data = { available: true, visible: false };
  mocks.overlayStatus.isLoading = false;
  mocks.overlayStatus.isError = false;
  mocks.overlayStatus.error = null;
  mocks.overlayVisibility.isPending = false;
  mocks.overlayVisibility.error = null;
  mocks.overlayVisibility.mutate.mockReset();
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: { writeText: vi.fn().mockResolvedValue(undefined) },
  });
});

describe("session context clipboard integrity", () => {
  it("rejects tampered content and mismatched session identity", async () => {
    const content = "# Session Context\n\nTrusted content.";
    const handoff = sessionHandoff(content);

    await expect(copyReadySessionContextContent(
      { ...handoff, content: `${content}\nTAMPERED` },
      { provider: "codex", sessionId: "session-1", boundarySequence: 42 },
    )).rejects.toThrow(/integrity check/);
    await expect(copyReadySessionContextContent(
      handoff,
      { provider: "codex", sessionId: "different-session", boundarySequence: 42 },
    )).rejects.toThrow(/different session/);
  });
});

describe("checkpoint product loop", () => {
  it("shows current work and a complete structured checkpoint on Now", () => {
    render(<MemoryRouter><NowPage /></MemoryRouter>);

    expect(screen.getByRole("definition", { name: "Harden checkpoint capture" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Continue with project context", level: 1 })).toBeInTheDocument();
    expect(screen.queryByText("Active task")).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox", {
      name: "Immediate continuation lead",
    })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Continuation task contract")).not.toBeInTheDocument();
    const continuationChoices = screen.getByRole("navigation", {
      name: "Choose another continuation",
    });
    expect(continuationChoices).toHaveClass("mx-auto", "w-full", "max-w-4xl", "gap-4", "sm:grid-cols-2");
    expect(screen.getByRole("link", { name: "Continue from an older session" })).toHaveAttribute("href", "/app/library");
    expect(screen.getByRole("link", { name: "Continue to a different session or harness" })).toHaveAttribute("href", "/app/memory");
    expect(screen.getByRole("heading", { name: "Context ready for selection" })).toBeInTheDocument();
    const carriedContext = screen.getByRole("region", { name: "Context ready for selection" });
    expect(within(carriedContext).getByTestId("context-package-card")).toHaveClass("w-full");
    expect(within(carriedContext).queryByText("Saved task state")).not.toBeInTheDocument();
    expect(within(carriedContext).queryByText("Reconciled at load")).not.toBeInTheDocument();
    const provenanceLegend = within(carriedContext).getByLabelText("Context provenance legend");
    expect(within(provenanceLegend).getByText("Repository-verified")).toBeInTheDocument();
    expect(within(provenanceLegend).getByText("User-authoritative")).toBeInTheDocument();
    expect(within(provenanceLegend).getByText("Agent-reported")).toBeInTheDocument();
    expect(within(provenanceLegend).getByText("Excluded / superseded")).toBeInTheDocument();
    const compositionPie = within(carriedContext).getByRole("img", {
      name: "Context composition pie chart: 6 boundary items across 6 categories",
    });
    expect(compositionPie).toHaveAttribute("data-testid", "context-composition-pie");
    expect(compositionPie.querySelectorAll("[data-context-pie-slice]")).toHaveLength(6);
    expect(within(within(carriedContext).getByLabelText("Pie chart categories")).getAllByRole("listitem")[0]).toHaveTextContent("Task1");
    expect(within(carriedContext).getByRole("button", { name: /Goal: 1 captured item/ })).toHaveAttribute("data-provenance", "human");
    expect(within(carriedContext).getByRole("button", { name: /Relevant files: 1 captured item/ })).toHaveAttribute("data-provenance", "observed");
    expect(within(carriedContext).getByRole("button", { name: /Blockers: 0 captured items/ })).toHaveAttribute("data-provenance", "excluded");
    expect(within(carriedContext).queryByTestId("session-evidence-section")).not.toBeInTheDocument();
    expect(within(carriedContext).queryByRole("region", {
      name: "Compilation at load",
    })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Progress" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Verification: 1 captured item/ })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Exact next action" })).not.toBeInTheDocument();
    expect(screen.queryByText("Continuity")).not.toBeInTheDocument();
    expect(screen.getByText("Recovery points")).toBeInTheDocument();
    expect(screen.getByText(/Review only · the selected task does not change/)).toBeInTheDocument();
    expect(screen.queryByText("Latest work")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Next action: 1 captured item/ }));
    const nextActionDrawer = screen.getByRole("dialog", { name: "Next action" });
    expect(nextActionDrawer).toBeInTheDocument();
    expect(within(nextActionDrawer).getByText("Wire checkpoint verification into Runs")).toBeInTheDocument();
    expect(screen.getByText("Provider event · event-1")).toBeInTheDocument();
    expect(screen.getByText("View raw source")).toBeInTheDocument();
    expect(screen.getByText("View raw source").closest("summary")).toHaveClass("min-h-11");
    expect(screen.queryByText(/object Object/i)).not.toBeInTheDocument();
    expect(screen.queryByText("not run")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open project memory" })).toHaveAttribute("href", "/app/memory");
    fireEvent.click(screen.getByRole("button", { name: "Close context details" }));
    expect(screen.queryByText(/01 \//)).not.toBeInTheDocument();
    expect(screen.queryByText(/02 \//)).not.toBeInTheDocument();
    expect(screen.queryByText(/03 \//)).not.toBeInTheDocument();
    expect(screen.queryByText(/04 \//)).not.toBeInTheDocument();
    expect(screen.getByLabelText("Continuation harnesses")).toHaveClass(
      "daemonstate-harness-fan",
      "snap-mandatory",
      "overflow-x-auto",
      "md:snap-none",
      "md:overflow-visible",
      "md:max-w-4xl",
      "md:gap-0",
    );
    expect(screen.getByLabelText("Continuation harnesses")).not.toHaveClass(
      "daemonstate-provider-deck",
      "xl:snap-none",
      "xl:overflow-visible",
    );
    const codexProvider = screen.getByRole("button", { name: "Load context in Codex" });
    const claudeProvider = screen.getByRole("button", { name: "Load context in Claude Code" });
    const openCodeProvider = screen.getByRole("button", { name: "Load context in OpenCode" });
    expect(codexProvider).toBeEnabled();
    expect(claudeProvider).toBeEnabled();
    expect(openCodeProvider).toBeEnabled();
    expect(within(codexProvider).getByText("CLI ready")).toBeInTheDocument();
    expect(within(claudeProvider).getByText("Configured")).toBeInTheDocument();
    expect(within(openCodeProvider).getByText("Configured")).toBeInTheDocument();
    expect(openCodeProvider).toHaveTextContent(
      "Live model access, service availability, and balance are not verified until a run starts.",
    );
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
    expect(mocks.hookCalls.memory).toEqual([]);
    expect(mocks.hookCalls.providers.at(-1)).toMatchObject({
      workspaceId: "workspace-1",
      enabled: true,
    });
    expect(mocks.hookCalls.refresh.at(-1)).toEqual({
      enabled: true,
      initialDelayMs: 30_000,
    });
  });

  it("hides the run plan until the compiler returns an exact execution contract", () => {
    render(<MemoryRouter><NowPage /></MemoryRouter>);

    expect(screen.queryByText("Run plan & safeguards")).not.toBeInTheDocument();
    expect(screen.queryByText("Execution contract")).not.toBeInTheDocument();
    expect(screen.queryByText("Not declared")).not.toBeInTheDocument();
    expect(screen.queryByText("Not reported")).not.toBeInTheDocument();
  });

  it("does not invent a next action when the saved boundary has no executable instruction", () => {
    const checkpoint = checkpointFixture();
    checkpoint.sections.exact_next_action = [{
      ...checkpoint.sections.exact_next_action[0],
      statement: "Blockers",
    }];
    mocks.latest.data = checkpoint;
    mocks.history.data = { checkpoints: [checkpoint] };

    render(<MemoryRouter><NowPage /></MemoryRouter>);

    const carriedContext = screen.getByRole("region", { name: "Context ready for selection" });
    expect(within(carriedContext).getByText("No explicit next action captured.")).toBeInTheDocument();
    expect(within(carriedContext).queryByText(/Continue the selected (?:goal|task)/i)).not.toBeInTheDocument();
  });

  it("returns keyboard focus to the context segment after closing its drawer", async () => {
    render(<MemoryRouter><NowPage /></MemoryRouter>);

    const trigger = screen.getByRole("button", { name: /Next action: 1 captured item/ });
    fireEvent.click(trigger);
    const drawer = screen.getByRole("dialog", { name: "Next action" });
    expect(drawer).toHaveAttribute("aria-describedby", "context-detail-description");
    expect(screen.getByRole("button", { name: "Close context details" })).toHaveFocus();

    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Next action" })).not.toBeInTheDocument());
    expect(trigger).toHaveFocus();
  });

  it("turns transported context breaks into readable drawer paragraphs without corrupting literals", () => {
    const checkpoint = checkpointFixture();
    checkpoint.sections.decisions = [{
      ...checkpoint.sections.decisions[0],
      statement: (
        "“What matters now”\\n\\nThis should stay concise. Only the first should remain. The continuation brief should name its subject."
        + "\\n- Current branch\\n- Changed files"
        + "\\n\\nKeep C:\\new\\tool unchanged. Match /\\\\n/ literally. Keep foo\\nbar literal."
        + "\\r\\n\\r\\nReady to continue.\\n\\n---\\n\\n4"
      ),
    }];
    mocks.latest.data = checkpoint;
    mocks.history.data = { checkpoints: [checkpoint] };

    render(<MemoryRouter><NowPage /></MemoryRouter>);

    fireEvent.click(screen.getByRole("button", { name: /Decisions: 3 captured items/ }));
    const drawer = screen.getByRole("dialog", { name: "Decisions" });
    expect(within(drawer).queryByText("This should stay concise")).not.toBeInTheDocument();
    expect(within(drawer).queryByText("Only the first should remain")).not.toBeInTheDocument();
    expect(within(drawer).getByText("The continuation brief should name its subject")).toBeInTheDocument();
    expect(within(drawer).getByText("Keep C:\\new\\tool unchanged")).toBeInTheDocument();
    expect(within(drawer).getByText("Keep foo\\nbar literal")).toBeInTheDocument();
    expect(within(drawer).queryByText(/What matters now/)).not.toBeInTheDocument();
    expect(within(drawer).queryByText(/Current branch/)).not.toBeInTheDocument();
    expect(within(drawer).queryByText(/---/)).not.toBeInTheDocument();
    expect(within(drawer).queryByText("4")).not.toBeInTheDocument();
  });

  it("renders the Now shell while current activity is still loading", () => {
    mocks.digest.data = null;
    mocks.digest.isLoading = true;

    render(<MemoryRouter><NowPage /></MemoryRouter>);

    expect(screen.getByRole("heading", { name: "Continue with project context", level: 1 })).toBeInTheDocument();
    expect(screen.getByText("Loading activity")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Load context in Codex" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Load context in Claude Code" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Load context in OpenCode" })).toBeDisabled();
    expect(screen.getByRole("region", { name: "Loading continuation context" })).toBeInTheDocument();
    expect(screen.queryByText("No agent progress observed yet.")).not.toBeInTheDocument();
    expect(screen.queryByText("No verified result captured.")).not.toBeInTheDocument();
    expect(screen.queryByText("No blocker, conflict, stale evidence, or high-risk review is currently visible.")).not.toBeInTheDocument();
    expect(mocks.hookCalls.latest.every((options) => options.enabled === false)).toBe(true);
    expect(mocks.hookCalls.history.at(-1)).toMatchObject({ limit: 12, enabled: false });
    expect(mocks.hookCalls.library.at(-1)).toMatchObject({ enabled: false });
    expect(mocks.hookCalls.continuity).toEqual([]);
    expect(mocks.hookCalls.memory).toEqual([]);
    expect(mocks.hookCalls.providers.at(-1)).toMatchObject({
      workspaceId: "workspace-1",
      enabled: false,
    });
    expect(mocks.hookCalls.refresh.at(-1)).toEqual({
      enabled: false,
      initialDelayMs: 30_000,
    });
  });

  it("reserves the continuation visual while saved context is loading", () => {
    mocks.latest.data = null;
    mocks.latest.isLoading = true;

    render(<MemoryRouter><NowPage /></MemoryRouter>);

    expect(screen.getByRole("region", { name: "Loading continuation context" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Progress" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Verification" })).not.toBeInTheDocument();
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

    expect(screen.getByRole("button", { name: "Load context in Codex" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Loading linked task…" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Save current context" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Choose work" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Choose a linked task" })).not.toBeInTheDocument();
  });

  it("keeps the saved context preview available when the initial digest fails", () => {
    mocks.digest.data = null;
    mocks.digest.isLoading = false;
    mocks.digest.isError = true;
    mocks.digest.error = new Error("Digest timed out");

    render(<MemoryRouter><NowPage /></MemoryRouter>);

    expect(screen.getByRole("heading", { name: "Continue with project context", level: 1 })).toBeInTheDocument();
    expect(screen.getByText("Activity unavailable")).toBeInTheDocument();
    expect(screen.getByText("Could not load current activity")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Context ready for selection" })).toBeInTheDocument();
    expect(screen.getAllByText("Current saved boundary").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "Load context in Codex" })).toBeEnabled();
    expect(screen.getByText(/Live activity is unavailable/)).toBeInTheDocument();
  });

  it("keeps cached activity visible when a background digest refresh fails", () => {
    mocks.digest.isError = true;
    mocks.digest.error = new Error("Refresh timed out");

    render(<MemoryRouter><NowPage /></MemoryRouter>);

    expect(screen.getByRole("heading", { name: "Continue with project context", level: 1 })).toBeInTheDocument();
    expect(screen.getByText("Activity refresh failed")).toBeInTheDocument();
    expect(screen.getByText(/Showing the last loaded activity/)).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Current activity is unavailable" })).not.toBeInTheDocument();
  });

  it("does not depend on the memory summary for continuation composition", () => {
    mocks.memory.data = null;
    mocks.memory.isError = true;
    mocks.memory.error = new Error("Memory service unavailable");

    render(<MemoryRouter><NowPage /></MemoryRouter>);

    expect(screen.getByRole("heading", { name: "Context ready for selection" })).toBeInTheDocument();
    expect(screen.queryByText("Trusted current")).not.toBeInTheDocument();
    expect(mocks.hookCalls.memory).toEqual([]);
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

    expect(screen.getByRole("heading", { name: "Context ready for selection" })).toBeInTheDocument();
    expect(screen.getAllByText("Older saved boundary").length).toBeGreaterThan(0);
    expect(screen.queryByText(/newer task activity exists/)).not.toBeInTheDocument();
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

    expect(screen.getByRole("heading", { name: "Context ready for selection" })).toBeInTheDocument();
    expect(screen.getAllByText("Boundary time unknown").length).toBeGreaterThan(0);
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
    expect(screen.getByText(/Nothing is presented as carried until launch-time selection/)).toBeInTheDocument();
  });

  it("keeps the legacy resume dialog removed while exposing the session handoff action", () => {
    render(<MemoryRouter><NowPage /></MemoryRouter>);

    expect(screen.queryByRole("button", { name: "Resume task" })).not.toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: "Review and resume" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", {
      name: "Copy current session context",
    })).toBeInTheDocument();
  });

  it("executes only the explicit task contract from a screenshot attachment envelope", async () => {
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
      name: "Remove screenshot IDs and temporary paths from the Now page.",
    })).toBeInTheDocument();
    expect(screen.queryByText(/Screenshot 2026-07-23/)).not.toBeInTheDocument();
    expect(screen.queryByText(/\/var\/folders/)).not.toBeInTheDocument();
    expect(screen.queryByText(/screencaptureui_/)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Load context in Codex" }));
    await waitFor(() => expect(mocks.continuation.mutateAsync).toHaveBeenCalled());
    const request = mocks.continuation.mutateAsync.mock.calls.at(-1)[0];
    expect(request).toMatchObject({
      objective: "Remove screenshot IDs and temporary paths from the Now page.",
      target_provider: "codex",
    });
    expect(request).not.toHaveProperty("source_provider");
    expect(request).not.toHaveProperty("source_session_id");
  });

  it("falls back instead of displaying metadata-only activity", () => {
    const attachmentOnly = "Screenshot 2026-07-23 at 16.42.18.png: /var/folders/example/TemporaryItems/NSIRD_screencaptureui_abc/Screenshot 2026-07-23 at 16.42.18.png";
    mocks.digest.data.current_goal = null;
    mocks.digest.data.activity.primary.request = attachmentOnly;
    mocks.digest.data.activity.primary.title = attachmentOnly;

    render(<MemoryRouter><NowPage /></MemoryRouter>);

    expect(screen.getByRole("heading", { name: "Continue with project context", level: 1 })).toBeInTheDocument();
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

    fireEvent.click(screen.getByRole("button", { name: "Load context in Codex" }));
    await waitFor(() => expect(mocks.continuation.mutateAsync).toHaveBeenCalled());
    const request = mocks.continuation.mutateAsync.mock.calls.at(-1)[0];
    expect(request).toMatchObject({
      source_provider: "codex",
      source_session_id: "session-1",
      target_provider: "codex",
    });
    expect(request).not.toHaveProperty("objective");
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

    fireEvent.click(screen.getByRole("button", { name: "Load context in Codex" }));
    await waitFor(() => expect(mocks.continuation.mutateAsync).toHaveBeenCalled());
    const request = mocks.continuation.mutateAsync.mock.calls.at(-1)[0];
    expect(request).toMatchObject({
      source_provider: "codex",
      source_session_id: "newest-root-session",
    });
    expect(request).not.toHaveProperty("objective");
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
    expect(screen.getByRole("button", { name: "Load context in Codex" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Load context in Codex" }));

    await waitFor(() => expect(mocks.continuation.mutateAsync).toHaveBeenCalled());
    const request = mocks.continuation.mutateAsync.mock.calls.at(-1)[0];
    expect(request).toMatchObject({
      source_provider: "codex",
      source_session_id: "source-with-limited-display",
      target_provider: "codex",
    });
    expect(request).not.toHaveProperty("objective");
  });

  it("loads the complete continuation into the selected harness and waits for the user", async () => {
    render(<MemoryRouter><NowPage /></MemoryRouter>);

    expect(screen.queryByRole("link", { name: "Inspect evidence" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /browser fallback/i })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Load context in Claude Code" }));

    await waitFor(() => expect(mocks.continuation.mutateAsync).toHaveBeenCalledWith({
      idempotency_key: expect.any(String),
      repo_path: "/workspace/daemonstate",
      source_provider: "codex",
      source_session_id: "session-1",
      target_provider: "claude",
      workspace_id: "workspace-1",
    }));
    expect(navigator.clipboard.writeText).not.toHaveBeenCalled();
    const status = await screen.findByRole("status");
    expect(status).toHaveTextContent("Context loaded in Claude Code");
    expect(status).toHaveTextContent("Context, direction, and the execution loop are loaded together");
    expect(status).toHaveTextContent("Nothing has been submitted");
    expect(status).toHaveTextContent("Confirm or narrow the compiled lead in Claude Code, then press Enter");
    expect(status).not.toHaveTextContent("agent is working");
    expect(status).not.toHaveTextContent(/verification after/i);
    expect(await screen.findByRole("heading", { name: "Context loaded" })).toBeInTheDocument();
    const carriedContext = screen.getByRole("region", { name: "Context loaded" });
    expect(screen.getByText("18,420 / 24,000 estimated tokens")).toBeInTheDocument();
    expect(within(carriedContext).getByRole("heading", { name: "Compiled context package" })).toBeInTheDocument();
    expect(within(carriedContext).getByText("4 considered · 3 selected · 1 excluded")).toBeInTheDocument();
    expect(within(carriedContext).getByTestId("context-package-card")).toHaveClass("w-full");
    expect(within(carriedContext).queryByText("Ready in Claude Code")).not.toBeInTheDocument();
    expect(within(carriedContext).queryByText("Waiting for task confirmation")).not.toBeInTheDocument();
    expect(within(carriedContext).queryByText("Saved task state")).not.toBeInTheDocument();
    expect(within(carriedContext).queryByText("Reconciled at load")).not.toBeInTheDocument();
    expect(within(carriedContext).queryByRole("region", {
      name: "Reconciliation recorded",
    })).not.toBeInTheDocument();
    expect(within(carriedContext).getByRole("button", { name: /Goal: 1 selected item/ })).toHaveAttribute("data-provenance", "human");
    expect(screen.getByRole("button", { name: /Decisions: 1 selected item/ })).toBeInTheDocument();
    const executionContract = screen.getByText("Run plan & safeguards").closest("details");
    fireEvent.click(executionContract.querySelector("summary"));
    expect(within(executionContract).getByText(/Preserve the full request and verify the visible continuation flow/)).toBeInTheDocument();
    expect(within(executionContract).getByText("Change")).toBeInTheDocument();
    expect(within(executionContract).getByText("Workspace Write")).toBeInTheDocument();
    expect(within(executionContract).getByText("Must preserve")).toBeInTheDocument();
    expect(within(executionContract).getByText("96 / 100")).toBeInTheDocument();
    expect(within(executionContract).getByText("Ready")).toBeInTheDocument();
    expect(within(executionContract).getByText("2/2 mapped")).toBeInTheDocument();
    expect(within(executionContract).getAllByText("Preserve the authoritative request without truncation.").length).toBeGreaterThan(0);
    const mandatoryRequirements = within(executionContract).getByRole("region", {
      name: "Mandatory requirements",
    });
    const userGuidance = within(executionContract).getByRole("region", {
      name: "User guidance",
    });
    expect(within(mandatoryRequirements).queryByText("Prioritize quality over speed.")).not.toBeInTheDocument();
    expect(within(userGuidance).getByText("Prioritize quality over speed.")).toBeInTheDocument();
    expect(within(executionContract).getByText("attachments/reference.png")).toBeInTheDocument();
    expect(within(executionContract).getByText("npm test -- --run")).toBeInTheDocument();
    expect(mocks.capture.mutate).not.toHaveBeenCalled();
  });

  it("stages an exact source without exposing an editable continuation lead", async () => {
    render(<MemoryRouter><NowPage /></MemoryRouter>);

    expect(screen.queryByRole("textbox", {
      name: "Immediate continuation lead",
    })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", {
      name: "Load context in Codex",
    }));

    await waitFor(() => expect(
      mocks.continuation.mutateAsync,
    ).toHaveBeenCalledWith(expect.objectContaining({
      source_provider: "codex",
      source_session_id: "session-1",
      target_provider: "codex",
    })));
    const request = mocks.continuation.mutateAsync.mock.calls.at(-1)[0];
    expect(request).not.toHaveProperty("objective");
    expect(request).not.toHaveProperty("objective_is_user_edited");
  });

  it("updates the resolved task when the selected source changes", async () => {
    const view = render(<MemoryRouter><NowPage /></MemoryRouter>);
    expect(screen.getByRole("definition", {
      name: "Harden checkpoint capture",
    })).toBeInTheDocument();

    mocks.digest.data.activity.recent_sessions[0] = {
      ...mocks.digest.data.activity.recent_sessions[0],
      session_id: "new-source-task",
      session_title: "Finish the newly selected source task",
      title: "Finish the newly selected source task",
    };
    view.rerender(<MemoryRouter><NowPage /></MemoryRouter>);

    await waitFor(() => expect(screen.getByRole("definition", {
      name: "Finish the newly selected source task",
    })).toBeInTheDocument());
  });

  it("does not advance the workflow before the user submits the staged lead", async () => {
    render(<MemoryRouter><NowPage /></MemoryRouter>);

    fireEvent.click(screen.getByRole("button", { name: "Load context in Codex" }));

    const status = await screen.findByRole("status");
    expect(status).toHaveTextContent("Nothing has been submitted");
    expect(status).not.toHaveTextContent("Workflow advanced after verification");
  });

  it.each([
    ["Codex", "codex"],
    ["Claude Code", "claude"],
    ["OpenCode", "opencode"],
  ])("loads the shared continuation into the selected %s provider", async (label, provider) => {
    render(<MemoryRouter><NowPage /></MemoryRouter>);

    fireEvent.click(screen.getByRole("button", { name: `Load context in ${label}` }));

    await waitFor(() => expect(mocks.continuation.mutateAsync).toHaveBeenCalledWith(
      expect.objectContaining({
        target_provider: provider,
        workspace_id: "workspace-1",
      }),
    ));
    const request = mocks.continuation.mutateAsync.mock.calls.at(-1)[0];
    expect(request).toMatchObject({
      source_provider: "codex",
      source_session_id: "session-1",
    });
    expect(request).not.toHaveProperty("objective");
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
    fireEvent.click(screen.getByRole("button", { name: "Load context in OpenCode" }));
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

  it("keeps the lossless execution goal accessible without a visible contract box", () => {
    const longGoal = (
      "Task: preserve `foo(bar)` and [the exact URL](https://example.com/a?b=1&c=2). "
      + "Keep every provider inspectable at intermediate widths, and prove the final behavior "
      + "with focused interaction tests — including terminal punctuation!"
    );

    render(
      <MemoryRouter initialEntries={[
        `/app?objective=${encodeURIComponent(longGoal)}`,
      ]}>
        <NowPage />
      </MemoryRouter>,
    );

    const goalDefinition = screen.getByRole("definition", { name: longGoal });
    expect(goalDefinition).toHaveTextContent(longGoal);
    expect(goalDefinition.closest("dl")).toHaveClass("sr-only");
    expect(screen.queryByText("Read full goal")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Continuation task contract")).not.toBeInTheDocument();
  });

  it("preserves marker-looking literals without restoring the visible contract", async () => {
    const objective = (
      "Fix A.\n"
      + "Fix B.\n"
      + "Files mentioned by the user: preserve /var/folders/demo.png.\n"
      + "Keep sandbox_permissions unchanged."
    );
    expect(objective.length).toBeLessThan(120);

    render(
      <MemoryRouter initialEntries={[
        `/app?objective=${encodeURIComponent(objective)}`,
      ]}>
        <NowPage />
      </MemoryRouter>,
    );

    const goalDefinition = screen.getByRole("definition", {
      name: /Files mentioned by the user/,
    });
    expect(goalDefinition).toHaveAttribute("aria-label", objective);
    expect(screen.queryByText("Read full goal")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Load context in OpenCode" }));
    await waitFor(() => expect(mocks.continuation.mutateAsync).toHaveBeenCalled());
    expect(mocks.continuation.mutateAsync.mock.calls.at(-1)[0]).toMatchObject({
      objective,
      target_provider: "opencode",
    });
  });

  it("preserves a human-authored failed-run diagnostic on an exact source", async () => {
    const diagnosticObjective = (
      "Concrete evidence from data/context.db: latest failed run "
      + "c526bac6447b4ece9ced31e594e43ebf command was "
      + "/Users/darshann/.npm-global/bin/codex exec --json. Exit 1."
    );

    render(
      <MemoryRouter initialEntries={[
        `/app?objective=${encodeURIComponent(diagnosticObjective)}&objective_source=session&repo_path=${encodeURIComponent("/workspace/daemonstate")}&source_provider=codex&source_session=session-1`,
      ]}>
        <NowPage />
      </MemoryRouter>,
    );

    expect(screen.getByRole("definition", {
      name: /Concrete evidence from data\/context\.db/i,
    })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Load context in OpenCode" }));
    await waitFor(() => expect(mocks.continuation.mutateAsync).toHaveBeenCalled());
    const request = mocks.continuation.mutateAsync.mock.calls.at(-1)[0];
    expect(request).toMatchObject({
      repo_path: "/workspace/daemonstate",
      source_provider: "codex",
      source_session_id: "session-1",
      target_provider: "opencode",
    });
    expect(request).not.toHaveProperty("objective");
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

    fireEvent.click(screen.getByRole("button", { name: "Load context in Claude Code" }));
    await waitFor(() => expect(mocks.continuation.mutateAsync).toHaveBeenCalledWith(
      expect.objectContaining({
        repo_path: "/workspace/source-session",
        source_provider: "codex",
        source_session_id: "source-session",
        target_provider: "claude",
      }),
    ));
    const request = mocks.continuation.mutateAsync.mock.calls.at(-1)[0];
    expect(request).not.toHaveProperty("objective");
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

    const claude = screen.getByRole("button", { name: "Load context in Claude Code" });
    expect(claude).toBeDisabled();
    expect(claude).toHaveAttribute("data-provider-ready", "false");
    expect(within(claude).getByText("Sign in")).toBeInTheDocument();
    expect(claude).toHaveTextContent("Claude Code CLI is installed, but it is not signed in.");
    expect(claude).toHaveTextContent("Next: Run `claude auth login` and try again.");
    expect(screen.getByRole("button", { name: "Load context in Codex" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Load context in OpenCode" })).toBeEnabled();
    const retry = screen.getByRole("button", { name: "Retry provider readiness" });
    fireEvent.click(retry);
    expect(mocks.providers.refetch).toHaveBeenCalledTimes(1);

    fireEvent.click(claude);
    expect(mocks.continuation.mutateAsync).not.toHaveBeenCalled();
  });

  it("fails closed when a ready provider cannot stage context without submitting", () => {
    mocks.providers.data.providers = mocks.providers.data.providers.map((provider) => (
      provider.provider === "codex"
        ? {
            ...provider,
            context_staging_supported: false,
          }
        : provider
    ));

    render(<MemoryRouter><NowPage /></MemoryRouter>);

    const codex = screen.getByRole("button", { name: "Load context in Codex" });
    expect(codex).toBeDisabled();
    expect(within(codex).getByText("No staging")).toBeInTheDocument();
    expect(codex).toHaveTextContent(
      "Codex cannot load continuation context without submitting a turn.",
    );
    expect(codex).toHaveTextContent(
      "Next: Choose a harness that supports context staging.",
    );
    fireEvent.click(codex);
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

    const openCode = screen.getByRole("button", { name: "Load context in OpenCode" });
    expect(openCode).toBeDisabled();
    expect(openCode).toHaveAttribute("data-provider-ready", "false");
    expect(within(openCode).getByText("Access needed")).toBeInTheDocument();
    expect(openCode).toHaveTextContent(
      "OpenCode CLI is installed, but `opencode/big-pickle` is not available to this account.",
    );
    expect(openCode).toHaveTextContent(
      "Next: Choose a model with active access, then check again.",
    );
    expect(screen.getByRole("button", { name: "Load context in Codex" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Load context in Claude Code" })).toBeEnabled();

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

    const claude = screen.getByRole("button", { name: "Load context in Claude Code" });
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
      const provider = screen.getByRole("button", { name: `Load context in ${label}` });
      expect(provider).toBeDisabled();
      expect(within(provider).getByText("Checking")).toBeInTheDocument();
    }
  });

  it("keeps the staging state visible when background session refresh changes the task key", () => {
    mocks.continuation.mutateAsync.mockImplementation(() => new Promise(() => {}));
    const view = render(<MemoryRouter><NowPage /></MemoryRouter>);

    fireEvent.click(screen.getByRole("button", { name: "Load context in OpenCode" }));

    const status = screen.getByRole("status");
    expect(status).toHaveAttribute("aria-busy", "true");
    expect(status).toHaveTextContent("Loading continuation context into OpenCode");
    expect(status).toHaveTextContent("Resolving the task and preparing its harness context");
    expect(status).toHaveTextContent(
      "Compiling context, direction, and the execution loop. No task has been submitted",
    );
    expect(screen.getByRole("button", { name: "Load context in OpenCode" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Load context in OpenCode" })).toHaveAttribute("data-provider-pending", "true");
    expect(screen.getByRole("button", { name: "Load context in OpenCode" })).toHaveClass("disabled:cursor-wait");
    expect(within(screen.getByRole("button", { name: "Load context in OpenCode" })).getByText("Loading")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Load context in Codex" })).toHaveAttribute("data-provider-pending", "false");

    mocks.digest.data.activity.recent_sessions[0] = {
      ...mocks.digest.data.activity.recent_sessions[0],
      session_title: "Background refresh imported a newer session title",
      title: "Background refresh imported a newer session title",
      session_id: "background-refresh-session",
      source_activity_at: "2026-07-25T16:04:00Z",
    };
    view.rerender(<MemoryRouter><NowPage /></MemoryRouter>);

    expect(screen.getByRole("status")).toHaveTextContent("Loading continuation context into OpenCode");
    expect(screen.getByRole("button", { name: "Load context in OpenCode" })).toHaveAttribute("data-provider-pending", "true");
  });

  it("keeps a legacy active run from creating a duplicate staged thread", async () => {
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

    const codex = screen.getByRole("button", { name: "Load context in Codex" });
    expect(codex).toBeDisabled();
    expect(codex).toHaveAttribute("aria-busy", "false");
    expect(codex).toHaveAttribute("data-provider-pending", "false");
    expect(codex).toHaveClass("disabled:cursor-wait");
    expect(screen.getByRole("status")).toHaveTextContent("Previous Codex continuation is still active");
    expect(screen.getByRole("status")).toHaveTextContent("Context staging will remain unavailable until it ends");
    expect(screen.getByRole("status")).toHaveTextContent(
      "Codex was asked to open this exact thread",
    );

    fireEvent.click(codex);
    expect(mocks.continuation.mutateAsync).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Open Codex thread" }));
    await waitFor(() => expect(mocks.openContinuation.mutateAsync).toHaveBeenCalledWith({
      workspaceId: "workspace-1",
      runId: "active-codex-run",
    }));
  });

  it("restores a staged handoff after reload without creating another thread", async () => {
    mocks.providers.data.staged_handoff = {
      schema_version: "continuation.stage.v1",
      status: "awaiting_user",
      delivery: {
        status: "staged",
        provider: "codex",
        run_id: "staged-codex-run",
        context_delivery: "developer_instructions",
        harness_session: {
          provider: "codex",
          session_id: "019f9a4d-f586-79d3-b305-4844518003bd",
          launched: true,
          navigation_requested: true,
          navigation_verified: false,
          exact_session_supported: true,
        },
      },
      run: {
        run_id: "staged-codex-run",
        provider: "codex",
        status: "awaiting_user",
      },
    };

    render(<MemoryRouter><NowPage /></MemoryRouter>);

    const status = screen.getByRole("status");
    expect(status).toHaveTextContent("Context loaded in Codex");
    expect(status).toHaveTextContent("Nothing has been submitted");
    expect(status).toHaveTextContent("Confirm or narrow the compiled lead in Codex, then press Enter");
    const codex = screen.getByRole("button", { name: "Load context in Codex" });
    expect(codex).toBeDisabled();
    expect(codex).toHaveAttribute("data-context-loaded", "true");
    fireEvent.click(codex);
    expect(mocks.continuation.mutateAsync).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Open Codex thread" }));
    await waitFor(() => expect(mocks.openContinuation.mutateAsync).toHaveBeenCalledWith({
      workspaceId: "workspace-1",
      runId: "staged-codex-run",
    }));
  });

  it("restores a terminal continuation after reload and leaves retry enabled", () => {
    mocks.providers.data.latest_run = {
      run_id: "failed-opencode-run",
      provider: "opencode",
      tool: "daemonstate:opencode",
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
      context_package: {
        schema_version: "context_package_summary.v1",
        context_pack_id: "pack-1",
        state: "delivered",
        created_at: "2026-07-25T16:03:30Z",
        selected_count: 3,
        excluded_count: 1,
        selected_by_lane: {
          instructions: 1,
          code_and_tests: 2,
        },
        excluded_by_reason: { stale: 1 },
        provenance: { verified: 2, unverified: 0, unknown: 1 },
        token_estimate: {
          rendered: 1_800,
          budget: 24_000,
          remaining: 22_200,
          within_budget: true,
          method: "chars_div_4.v1",
        },
        relevant_files_count: 2,
        verification_commands_count: 1,
        input_fingerprint: "fingerprint-1",
        continuation_identity: {
          task_id: "task-1",
          selected_objective: "Harden checkpoint capture",
          checkpoint_id: null,
          source_provider: "codex",
          source_session_id: "session-1",
        },
      },
    };

    render(<MemoryRouter><NowPage /></MemoryRouter>);

    const opencode = screen.getByRole("button", { name: "Load context in OpenCode" });
    expect(opencode).toBeEnabled();
    expect(opencode).toHaveAttribute("aria-busy", "false");
    expect(screen.getByRole("alert")).toHaveTextContent("OpenCode continuation failed");
    expect(screen.getByRole("alert")).toHaveTextContent("OpenCode exited after repeated provider errors");
    expect(screen.getByRole("alert")).toHaveTextContent("No successful handoff is being claimed");
    expect(screen.queryByText("Open run history")).not.toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Recorded run failed-o has no linked harness session",
    );
    expect(screen.getByRole("heading", { name: "What carried over" })).toBeInTheDocument();
    expect(screen.getByText("1,800 / 24,000 estimated tokens")).toBeInTheDocument();
    expect(screen.getByText(/recorded package summary delivered to OpenCode/)).toBeInTheDocument();
    expect(screen.queryByText("Run plan & safeguards")).not.toBeInTheDocument();
  });

  it("does not attach another task's persisted package to the selected continuation", () => {
    mocks.providers.data.latest_run = {
      run_id: "other-task-run",
      provider: "claude",
      status: "completed",
      completed: true,
      verified_success: true,
      context_package: {
        state: "delivered",
        selected_by_lane: { instructions: 4 },
        token_estimate: { rendered: 9_000, budget: 24_000 },
        continuation_identity: {
          task_id: "task-other",
          selected_objective: "Ship an unrelated billing change",
          checkpoint_id: null,
          source_provider: "claude",
          source_session_id: "session-other",
        },
      },
    };

    render(<MemoryRouter><NowPage /></MemoryRouter>);

    expect(screen.getByRole("heading", { name: "Context ready for selection" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "What carried over" })).not.toBeInTheDocument();
    expect(screen.queryByText("9,000 / 24,000 estimated tokens")).not.toBeInTheDocument();
  });

  it("opens the exact Codex thread for a persisted local timeout", async () => {
    mocks.providers.data.latest_run = {
      run_id: "timed-out-codex-run",
      provider: "codex",
      tool: "daemonstate:codex",
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
      context_package: {
        state: "delivered",
        continuation_identity: {
          task_id: "task-1",
          selected_objective: "Harden checkpoint capture",
          checkpoint_id: null,
          source_provider: "codex",
          source_session_id: "session-1",
        },
      },
    };

    render(<MemoryRouter><NowPage /></MemoryRouter>);

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent(
      "Review the recorded changes, finish any incomplete work, and retry only if work remains.",
    );
    expect(alert).not.toHaveTextContent("provider is available");
    expect(alert).toHaveTextContent(
      "Codex was asked to open this exact thread",
    );
    fireEvent.click(screen.getByRole("button", { name: "Open Codex thread" }));
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
    fireEvent.click(screen.getByRole("button", { name: "Load context in Codex" }));

    await waitFor(() => expect(mocks.continuation.mutateAsync).toHaveBeenCalledWith({
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

  it("fails closed instead of treating a terminal run response as staged context", async () => {
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

    fireEvent.click(screen.getByRole("button", { name: "Load context in Codex" }));

    const blocker = await screen.findByRole("alert");
    expect(blocker).toHaveTextContent("Context staging was not confirmed");
    expect(blocker).toHaveTextContent("will not claim that context was loaded");
    expect(screen.queryByText("Context loaded in Codex")).not.toBeInTheDocument();
    expect(blocker).not.toHaveTextContent("Audited the configuration");
    expect(blocker).toHaveTextContent("No successful handoff is being claimed");
  });

  it("shows the backend blocker instead of sending the user to inspect context", async () => {
    mocks.continuation.mutateAsync.mockRejectedValue(
      new Error("No installed target agent is available."),
    );
    render(<MemoryRouter><NowPage /></MemoryRouter>);

    fireEvent.click(screen.getByRole("button", { name: "Load context in Codex" }));

    const blocker = await screen.findByRole("alert");
    expect(blocker).toHaveTextContent("Codex continuation blocked");
    expect(blocker).toHaveTextContent("No installed target agent is available");
    expect(blocker).toHaveTextContent("No successful handoff is being claimed");
    expect(screen.queryByRole("link", { name: "Inspect evidence" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", {
      name: "Copy current session context",
    })).toBeInTheDocument();
    expect(navigator.clipboard.writeText).not.toHaveBeenCalled();
  });

  it.each([
    ["provider_run_failed", "OpenCode exited with code 1."],
    ["provider_run_timed_out", "OpenCode exceeded the run timeout."],
    ["provider_invocation_invalid", "DaemonState constructed an invalid OpenCode invocation."],
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

    fireEvent.click(screen.getByRole("button", { name: "Load context in OpenCode" }));

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

    fireEvent.click(screen.getByRole("button", { name: "Load context in OpenCode" }));

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

    fireEvent.click(screen.getByRole("button", { name: "Load context in OpenCode" }));

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

    fireEvent.click(screen.getByRole("button", { name: "Load context in Claude Code" }));

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
          cwd: "/workspace/daemonstate",
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

    fireEvent.click(screen.getByRole("button", { name: "Load context in Claude Code" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("1 verification check failed");
    expect(alert).toHaveTextContent("Failed checks");
    expect(alert).toHaveTextContent("python3 -m pytest -q tests/test_auth.py");
    expect(alert).toHaveTextContent(
      "FAILED tests/test_auth.py::test_callback - assertion failed",
    );
  });

  it("clears a staged continuation when its repository or objective changes", async () => {
    const view = render(<MemoryRouter><NowPage /></MemoryRouter>);

    fireEvent.click(screen.getByRole("button", { name: "Load context in Codex" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Context loaded in Claude Code");

    mocks.digest.data.activity.recent_sessions[0] = {
      ...mocks.digest.data.activity.recent_sessions[0],
      cwd: "/workspace/daemonstate-next",
    };
    view.rerender(<MemoryRouter><NowPage /></MemoryRouter>);

    await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Load context in Codex" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Context loaded in Claude Code");
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
    expect(screen.getAllByText("Choose linked work before continuing.").length).toBeGreaterThan(0);
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

    const codexProvider = screen.getByRole("button", { name: "Load context in Codex" });
    expect(codexProvider).toBeDisabled();
    expect(codexProvider).toHaveAttribute("data-provider-ready", "true");
    expect(codexProvider).toHaveAttribute("data-task-ready", "false");
    expect(within(codexProvider).getByText("CLI ready")).toBeVisible();
    expect(within(codexProvider).getByText("Task required:")).toBeVisible();
    expect(within(codexProvider).getByText("Choose linked work before continuing.")).toBeVisible();
    expect(within(codexProvider).getByText("Task required", { exact: true })).toBeVisible();
    expect(within(codexProvider).queryByText("Continue", { exact: true })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Choose work to continue" })).toHaveAttribute("href", "/app/library");
  });

  it("pins the newest inferred session so backend sync cannot replace the displayed task", async () => {
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
    fireEvent.click(screen.getByRole("button", { name: "Load context in Codex" }));

    await waitFor(() => expect(mocks.continuation.mutateAsync).toHaveBeenCalled());
    const request = mocks.continuation.mutateAsync.mock.calls.at(-1)[0];
    expect(request).toMatchObject({
      repo_path: "/workspace/newest-root-session",
      source_provider: "codex",
      source_session_id: "newest-root-session",
    });
    expect(request).not.toHaveProperty("objective");
    expect(request).not.toHaveProperty("checkpoint_id");
  });

  it("captures context automatically instead of exposing a manual save action", () => {
    mocks.latest.data = null;
    render(<MemoryRouter><NowPage /></MemoryRouter>);

    expect(screen.queryByRole("button", { name: "Save current context" })).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Context ready for selection" })).toBeInTheDocument();
    expect(screen.getByText(/Continue will inspect the repository, compile the final package, and load it/)).toBeInTheDocument();
    expect(mocks.capture.mutate).not.toHaveBeenCalled();
  });

  it("keeps checkpoint history read-only and delegates execution to Continue", () => {
    render(<MemoryRouter><NowPage /></MemoryRouter>);

    expect(screen.queryByRole("button", { name: "Verify checkpoint" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Resume task" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Save current context" })).not.toBeInTheDocument();
    expect(screen.getByText(/Nothing is presented as carried until launch-time selection/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Load context in Codex" })).toBeInTheDocument();
    expect(mocks.verify.mutate).not.toHaveBeenCalled();
    expect(mocks.sessionContinue.mutateAsync).not.toHaveBeenCalled();
    expect(navigator.clipboard.writeText).not.toHaveBeenCalled();
  });

  it("copies the current session's latest captured immutable checkpoint", async () => {
    const newerTimestamp = checkpointFixture();
    newerTimestamp.id = "now-newer-timestamp";
    newerTimestamp.boundary.sequence_number = 20;
    newerTimestamp.boundary.occurred_at = "2026-07-21T11:00:00Z";
    const highestBoundary = checkpointFixture();
    highestBoundary.id = "now-highest-boundary";
    highestBoundary.trigger = "manual";
    highestBoundary.boundary.sequence_number = 80;
    highestBoundary.boundary.occurred_at = "2026-07-21T08:00:00Z";
    const newerSessionTip = checkpointFixture();
    newerSessionTip.id = "now-session-tip";
    newerSessionTip.trigger = "session_tip";
    newerSessionTip.boundary.snapshot_phase = "session_tip";
    newerSessionTip.boundary.sequence_number = 90;
    mocks.history.data = {
      checkpoints: [newerSessionTip, newerTimestamp, highestBoundary],
    };
    const content = "# Session Context\n\nLatest captured session state.";
    mocks.checkpointHandoff.mutateAsync.mockResolvedValue(
      sessionHandoff(content, {
        checkpoint_id: "now-session-tip",
        boundary: { event_id: "event-90", sequence_number: 90 },
      }),
    );

    render(<MemoryRouter><NowPage /></MemoryRouter>);

    expect(screen.getByRole("heading", {
      name: "Continue with project context",
    })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", {
      name: "Copy current session context",
    }));

    await waitFor(() => expect(
      mocks.checkpointHandoff.mutateAsync,
    ).toHaveBeenCalledWith({
      workspaceId: "workspace-1",
      checkpointId: "now-session-tip",
    }));
    await waitFor(() => expect(
      navigator.clipboard.writeText,
    ).toHaveBeenCalledWith(content));
    expect(await screen.findByText("Session context copied")).toBeInTheDocument();
    expect(mocks.continuation.mutateAsync).not.toHaveBeenCalled();
  });

  it("shows every captured compaction for the displayed session in boundary order", () => {
    const latest = checkpointFixture();
    const earlier = checkpointFixture();
    earlier.id = "checkpoint-0";
    earlier.boundary.sequence_number = 99;
    earlier.boundary.occurred_at = "2026-07-21T09:15:00Z";
    earlier.sections.goal[0].statement = "Earlier compacted goal";
    mocks.latest.data = latest;
    mocks.history.data = { checkpoints: [latest, earlier] };

    render(<MemoryRouter><NowPage /></MemoryRouter>);

    const recoveryPoints = screen.getByText("Recovery points");
    expect(within(recoveryPoints.parentElement).getByText("2")).toBeInTheDocument();
    const recoveryButtons = screen.getAllByRole("button", { name: /Jul 21, 2026/ });
    expect(recoveryButtons).toHaveLength(2);
    expect(recoveryButtons[0]).not.toHaveAttribute("aria-current");
    expect(recoveryButtons[1]).toHaveAttribute("aria-current", "step");
    expect(screen.queryByText(/Recovery point 0/)).not.toBeInTheDocument();
    fireEvent.click(recoveryButtons[0]);
    expect(screen.getByRole("dialog", { name: "Earlier saved boundary" })).toBeInTheDocument();
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
    expect(screen.getByRole("heading", { name: "Context ready for selection" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Inspect an earlier task snapshot" }));
    expect(screen.getByRole("dialog", { name: "Earlier saved context" })).toBeInTheDocument();
    expect(screen.getByText("Old checkpoint task")).toBeInTheDocument();
    expect(screen.getByText(/belongs to another task and is not selected/)).toBeInTheDocument();
    expect(screen.queryByText("Not the latest state — 10 events behind")).not.toBeInTheDocument();
    expect(screen.queryByText("Resume session")).not.toBeInTheDocument();
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
    fireEvent.click(screen.getByRole("button", { name: "Load context in Codex" }));

    await waitFor(() => expect(mocks.continuation.mutateAsync).toHaveBeenCalledWith({
      idempotency_key: expect.any(String),
      provider_effort: "medium",
      provider_model: "gpt-5.6-sol",
      repo_path: "/workspace/daemonstate",
      source_provider: "codex",
      source_session_id: "current-session",
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
    expect(heading.closest("header")).toHaveClass("daemonstate-resume-header", "min-h-56");
    expect(mocks.hookCalls.continuity.at(-1)).toMatchObject({ limit: 50 });
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
    expect(mocks.checkpointHandoff.mutateAsync).not.toHaveBeenCalled();
    expect(navigator.clipboard.writeText).not.toHaveBeenCalled();
  });

  it("copies the latest usable immutable session checkpoint", async () => {
    const newerTimestamp = checkpointFixture();
    newerTimestamp.id = "newer-timestamp";
    newerTimestamp.boundary.sequence_number = 20;
    newerTimestamp.boundary.occurred_at = "2026-07-21T11:00:00Z";
    const highestBoundary = checkpointFixture();
    highestBoundary.id = "highest-pre-compaction-boundary";
    highestBoundary.trigger = "manual";
    highestBoundary.boundary.sequence_number = 80;
    highestBoundary.boundary.occurred_at = "2026-07-21T08:00:00Z";
    const sessionTip = checkpointFixture();
    sessionTip.id = "session-tip-newest";
    sessionTip.trigger = "session_tip";
    sessionTip.boundary.snapshot_phase = "session_tip";
    sessionTip.boundary.sequence_number = 90;
    sessionTip.boundary.occurred_at = "2026-07-21T12:00:00Z";
    mocks.history.data = {
      checkpoints: [newerTimestamp, sessionTip, highestBoundary],
    };
    const content = "# Exact session handoff\n\nOnly the pre-compaction session state.";
    mocks.checkpointHandoff.mutateAsync.mockResolvedValue(
      sessionHandoff(content, {
        checkpoint_id: "session-tip-newest",
        boundary: { event_id: "event-90", sequence_number: 90 },
      }),
    );

    render(<MemoryRouter><RunsPage /></MemoryRouter>);

    expect(screen.getByText(/Continue builds task-relevant Project Context/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", {
      name: "Copy session context: Harden checkpoint capture",
    }));

    await waitFor(() => expect(mocks.checkpointHandoff.mutateAsync).toHaveBeenCalledWith({
      workspaceId: "workspace-1",
      checkpointId: "session-tip-newest",
    }));
    await waitFor(() => expect(
      navigator.clipboard.writeText,
    ).toHaveBeenCalledWith(content));
    expect(await screen.findByText("Session context copied")).toBeInTheDocument();
    expect(mocks.continuation.mutateAsync).not.toHaveBeenCalled();
    expect(mocks.sessionContinue.mutateAsync).not.toHaveBeenCalled();
  });

  it("uses timestamp then checkpoint ID as deterministic fallbacks when boundary sequence is missing", async () => {
    const older = checkpointFixture();
    older.id = "fallback-older";
    delete older.boundary.sequence_number;
    older.boundary.occurred_at = "2026-07-21T08:00:00Z";
    const tiedA = checkpointFixture();
    tiedA.id = "fallback-a";
    delete tiedA.boundary.sequence_number;
    tiedA.boundary.occurred_at = "2026-07-21T11:00:00Z";
    const tiedZ = checkpointFixture();
    tiedZ.id = "fallback-z";
    delete tiedZ.boundary.sequence_number;
    tiedZ.boundary.occurred_at = "2026-07-21T11:00:00Z";
    mocks.history.data = { checkpoints: [tiedA, older, tiedZ] };

    render(<MemoryRouter><RunsPage /></MemoryRouter>);
    fireEvent.click(screen.getByRole("button", {
      name: "Copy session context: Harden checkpoint capture",
    }));

    await waitFor(() => expect(mocks.checkpointHandoff.mutateAsync).toHaveBeenCalledWith({
      workspaceId: "workspace-1",
      checkpointId: "fallback-z",
    }));
  });

  it("disables session-context copy when no usable captured context exists", () => {
    mocks.history.data = { checkpoints: [] };

    render(<MemoryRouter><RunsPage /></MemoryRouter>);

    const unavailable = screen.getByRole("button", {
      name: "Session context unavailable: Harden checkpoint capture",
    });
    expect(unavailable).toBeDisabled();
    expect(unavailable).toHaveTextContent("Session context unavailable");
    expect(mocks.checkpointHandoff.mutateAsync).not.toHaveBeenCalled();
    expect(navigator.clipboard.writeText).not.toHaveBeenCalled();
  });

  it("fails closed instead of copying an older task when the newest boundary is unusable", () => {
    const olderUsable = checkpointFixture();
    olderUsable.id = "older-unrelated-task";
    olderUsable.boundary.sequence_number = 80;
    const newestUnusable = checkpointFixture();
    newestUnusable.id = "newest-needs-recovery";
    newestUnusable.trigger = "session_tip";
    newestUnusable.boundary.snapshot_phase = "session_tip";
    newestUnusable.boundary.sequence_number = 90;
    newestUnusable.capture_status = "incomplete";
    newestUnusable.projection = {
      valid: false,
      state: "missing_substantive_goal",
    };
    newestUnusable.sections.goal = [];
    newestUnusable.sections.exact_next_action = [];
    mocks.history.data = {
      checkpoints: [olderUsable, newestUnusable],
    };

    render(<MemoryRouter><RunsPage /></MemoryRouter>);

    expect(screen.getByRole("button", {
      name: "Session context unavailable: Harden checkpoint capture",
    })).toBeDisabled();
    expect(mocks.checkpointHandoff.mutateAsync).not.toHaveBeenCalled();
    expect(navigator.clipboard.writeText).not.toHaveBeenCalled();
  });

  it("does not claim session context was copied when clipboard writing fails", async () => {
    navigator.clipboard.writeText.mockRejectedValue(new Error("Clipboard permission denied"));

    render(<MemoryRouter><RunsPage /></MemoryRouter>);

    fireEvent.click(screen.getByRole("button", {
      name: "Copy session context: Harden checkpoint capture",
    }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Clipboard permission denied");
    expect(mocks.checkpointHandoff.mutateAsync).toHaveBeenCalledWith({
      workspaceId: "workspace-1",
      checkpointId: "checkpoint-1",
    });
    expect(screen.queryByText("Session context copied")).not.toBeInTheDocument();
    expect(screen.getByRole("button", {
      name: "Copy session context: Harden checkpoint capture",
    })).toHaveTextContent("Copy session context");
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
        cwd: "/workspace/daemonstate",
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

function sessionHandoff(content, overrides = {}) {
  return {
    schema_version: "session_handoff.v1",
    scope: "session",
    provider: "codex",
    session_id: "session-1",
    checkpoint_id: "checkpoint-1",
    boundary: {
      event_id: "event-42",
      sequence_number: 42,
    },
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
