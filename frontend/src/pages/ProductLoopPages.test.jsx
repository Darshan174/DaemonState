import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { createHash } from "node:crypto";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import NowPage from "./NowPage";
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
  latestDiscovery: {
    data: {
      sync: { mode: "latest", discovered: 1 },
      session: {
        id: "codex:session-1",
        connector_type: "codex",
        session_id: "session-1",
        source_document_id: "source-1",
        title: "Harden checkpoint capture",
        preview: "Harden checkpoint capture",
        updated_at: "2026-07-21T10:00:00Z",
        cwd: "/workspace/daemonstate",
        revision_number: 1,
        live: true,
      },
    },
    isLoading: false,
    isFetching: false,
    isFetched: true,
    isFetchedAfterMount: true,
    isSuccess: true,
    isError: false,
    error: null,
    refetch: vi.fn(),
  },
  latest: { data: null, isLoading: false, isError: false, error: null },
  scopedLatest: null,
  history: { data: { checkpoints: [] }, isLoading: false, isError: false, error: null },
  library: { data: { sessions: [] }, isLoading: false },
  memory: { data: null, isLoading: false, isError: false, error: null },
  providers: {
    data: {
      providers: [
        {
          provider: "codex",
          name: "Codex",
          status: "ready",
          ready: true,
          context_staging_supported: false,
          desktop_handoff_supported: true,
          readiness_scope: "desktop_dispatch_with_account_evidence",
          account_access_state: "verified",
          account_access_verified: true,
          code: "desktop_account_access_verified",
          message: "Codex desktop and account access are verified.",
          action: "Continue in Codex Desktop.",
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
          status: "ready",
          ready: true,
          context_staging_supported: false,
          desktop_handoff_supported: true,
          readiness_scope: "desktop_dispatch_with_account_evidence",
          account_access_state: "verified",
          account_access_verified: true,
          code: "desktop_account_access_verified",
          message: "Claude desktop and account access are verified.",
          action: "Continue in Claude Desktop.",
        },
        {
          provider: "opencode",
          name: "OpenCode",
          status: "ready",
          ready: true,
          context_staging_supported: false,
          desktop_handoff_supported: true,
          readiness_scope: "desktop_dispatch_with_account_evidence",
          account_access_state: "verified",
          account_access_verified: true,
          code: "desktop_account_access_verified",
          message: "OpenCode desktop and provider/model access are verified.",
          action: "Continue in OpenCode Desktop.",
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
    digest: [],
    discovery: [],
    latest: [],
    history: [],
    library: [],
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
  selectSession: { isPending: false, error: null, mutateAsync: vi.fn() },
  overlayStatus: {
    data: { available: true, visible: false },
    isLoading: false,
    isError: false,
    error: null,
  },
  overlayVisibility: { isPending: false, error: null, mutate: vi.fn() },
  promptSnippets: {
    data: { prompts: [] },
    isLoading: false,
    isFetching: false,
    isError: false,
    error: null,
  },
  createPrompt: {
    isPending: false,
    error: null,
    mutateAsync: vi.fn(),
    reset: vi.fn(),
  },
  deletePrompt: {
    isPending: false,
    error: null,
    variables: null,
    mutateAsync: vi.fn(),
    reset: vi.fn(),
  },
}));

vi.mock("./useProductWorkspace", () => ({
  useProductWorkspace: () => mocks.workspace,
}));

vi.mock("../context-map/api", () => ({
  useContextDigest: (_workspaceId, options = {}) => {
    mocks.hookCalls.digest.push(options);
    return mocks.digest;
  },
  useLatestLocalAISessionDiscovery: (_workspaceId, options = {}) => {
    mocks.hookCalls.discovery.push(options);
    return mocks.latestDiscovery;
  },
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
  usePromptSnippets: () => mocks.promptSnippets,
  useCreatePromptSnippet: () => mocks.createPrompt,
  useDeletePromptSnippet: () => mocks.deletePrompt,
}));

beforeEach(() => {
  globalThis.sessionStorage?.clear();
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
  mocks.latestDiscovery.data = latestDiscoveryResult();
  mocks.latestDiscovery.isLoading = false;
  mocks.latestDiscovery.isFetching = false;
  mocks.latestDiscovery.isFetched = true;
  mocks.latestDiscovery.isFetchedAfterMount = true;
  mocks.latestDiscovery.isSuccess = true;
  mocks.latestDiscovery.isError = false;
  mocks.latestDiscovery.error = null;
  mocks.latestDiscovery.refetch.mockReset().mockResolvedValue({});
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
  mocks.promptSnippets.data = { prompts: [] };
  mocks.promptSnippets.isLoading = false;
  mocks.promptSnippets.isFetching = false;
  mocks.promptSnippets.isError = false;
  mocks.promptSnippets.error = null;
  mocks.createPrompt.isPending = false;
  mocks.createPrompt.error = null;
  mocks.createPrompt.mutateAsync.mockReset();
  mocks.createPrompt.reset.mockReset();
  mocks.deletePrompt.isPending = false;
  mocks.deletePrompt.error = null;
  mocks.deletePrompt.variables = null;
  mocks.deletePrompt.mutateAsync.mockReset();
  mocks.deletePrompt.reset.mockReset();
  mocks.providers.data = {
    active_run: null,
    latest_run: null,
    providers: [
      {
        provider: "codex",
        name: "Codex",
        status: "ready",
        ready: true,
        context_staging_supported: false,
        desktop_handoff_supported: true,
        readiness_scope: "desktop_dispatch_with_account_evidence",
        account_access_state: "verified",
        account_access_verified: true,
        code: "desktop_account_access_verified",
        message: "Codex desktop and account access are verified.",
        action: "Continue in Codex Desktop.",
        models: [
          {
            id: "gpt-5.6-sol",
            label: "GPT-5.6 Sol",
            default: true,
            reasoning_efforts: ["low", "medium", "high", "xhigh", "max", "ultra"],
            default_reasoning_effort: "medium",
          },
          {
            id: "gpt-5.6-terra",
            label: "GPT-5.6 Terra",
            default: false,
            reasoning_efforts: ["low", "medium", "high", "xhigh", "max", "ultra"],
            default_reasoning_effort: "medium",
          },
        ],
      },
      {
        provider: "claude",
        name: "Claude Code",
        status: "ready",
        ready: true,
        context_staging_supported: false,
        desktop_handoff_supported: true,
        readiness_scope: "desktop_dispatch_with_account_evidence",
        account_access_state: "verified",
        account_access_verified: true,
        code: "desktop_account_access_verified",
        message: "Claude desktop and account access are verified.",
        action: "Continue in Claude Desktop.",
      },
      {
        provider: "opencode",
        name: "OpenCode",
        status: "ready",
        ready: true,
        context_staging_supported: false,
        desktop_handoff_supported: true,
        readiness_scope: "desktop_dispatch_with_account_evidence",
        account_access_state: "verified",
        account_access_verified: true,
        code: "desktop_account_access_verified",
        message: "OpenCode desktop and provider/model access are verified.",
        action: "Continue in OpenCode Desktop.",
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
      status: "awaiting_user",
      provider: "claude",
      source_provider: "codex",
      provider_switched: true,
      mode: "desktop_composer_prefill",
      handoff_id: "handoff-1",
      context_delivery: "desktop_composer_prefill_and_clipboard",
      execution_started: false,
      visibility: {
        context_loaded: false,
        context_copied: true,
        prefill_requested: true,
        execution_started: false,
      },
      harness_session: {
        handoff_id: "handoff-1",
        provider: "claude",
        launched: false,
        open_requested: true,
        navigation_requested: true,
        navigation_verified: false,
        exact_session_supported: false,
        context_loaded: false,
        context_copied: true,
        prefill_requested: true,
        execution_started: false,
      },
    },
    run: {
      handoff_id: "handoff-1",
      provider: "claude",
      status: "awaiting_user",
      execution_started: false,
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
  it("keeps continuation cards inactive until two provider compactions exist", () => {
    mocks.latestDiscovery.data = latestDiscoveryResult({
      compaction_checkpoints: [
        { id: "provider-compaction-1", window_id: 1 },
      ],
    });
    mocks.history.data = { checkpoints: [checkpointFixture()] };

    render(<MemoryRouter><NowPage /></MemoryRouter>);

    const providerButtons = [
      screen.getByRole("button", { name: "Open desktop handoff in Codex" }),
      screen.getByRole("button", { name: "Open desktop handoff in Claude Code" }),
      screen.getByRole("button", { name: "Open desktop handoff in OpenCode" }),
    ];
    providerButtons.forEach((button) => {
      expect(button).toBeDisabled();
      expect(button).toHaveAttribute("data-context-ready", "false");
      expect(button).toHaveAttribute("data-compaction-count", "1");
    });
    expect(screen.getAllByText("1/2 compactions")).toHaveLength(3);
    expect(screen.getAllByText("Session Context locked")).toHaveLength(3);

    const codexCard = providerButtons[0].closest("article");
    fireEvent.mouseEnter(codexCard);
    expect(codexCard).toHaveStyle({
      zIndex: "40",
      "--daemonstate-card-y": "-18px",
      "--daemonstate-card-scale": "1.035",
    });

    fireEvent.click(providerButtons[0]);
    expect(mocks.continuation.mutateAsync).not.toHaveBeenCalled();
  });

  it("shows current work and a complete structured checkpoint on Now", () => {
    render(<MemoryRouter><NowPage /></MemoryRouter>);

    expect(screen.getByRole("definition", { name: "Harden checkpoint capture" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Continue with Session Context", level: 1 })).toBeInTheDocument();
    expect(screen.queryByText("DaemonState")).not.toBeInTheDocument();
    expect(screen.queryByText("Activity in view")).not.toBeInTheDocument();
    const statusRibbon = screen.getByLabelText("Observed work status");
    expect(within(statusRibbon).getByText(/^Source activity /)).toBeInTheDocument();
    expect(within(statusRibbon).getByText(/Provider session timestamp ·/)).toBeInTheDocument();
    expect(within(statusRibbon).queryByText("Latest available record")).not.toBeInTheDocument();
    expect(screen.queryByText("Active task")).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox", {
      name: "Immediate continuation lead",
    })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Continuation task contract")).not.toBeInTheDocument();
    const continuationChoices = screen.getByRole("navigation", {
      name: "Other task paths",
    });
    expect(continuationChoices).toHaveClass("mx-auto", "w-full", "max-w-4xl", "gap-4", "sm:grid-cols-2");
    expect(screen.getByRole("link", { name: "Prepare an older session" })).toHaveAttribute("href", "/app/library");
    expect(screen.getByRole("link", { name: "Choose explicit context in Execute" })).toHaveAttribute("href", "/app/execute");
    expect(screen.getByRole("heading", { name: "Context ready for selection" })).toBeInTheDocument();
    const carriedContext = screen.getByRole("region", { name: "Context ready for selection" });
    expect(within(carriedContext).getByTestId("context-package-card")).toHaveClass("w-full");
    expect(within(carriedContext).queryByText("Saved task state")).not.toBeInTheDocument();
    expect(within(carriedContext).queryByText("Reconciled at load")).not.toBeInTheDocument();
    expect(within(carriedContext).getByText("Continuation snapshot")).toBeInTheDocument();
    expect(within(carriedContext).getByRole("heading", {
      name: "Context prepared for review",
    })).toBeInTheDocument();
    expect(within(carriedContext).getByText("6 context records captured")).toBeInTheDocument();
    expect(within(carriedContext).queryByText("Boundary inventory")).not.toBeInTheDocument();
    expect(within(carriedContext).queryByText("Saved context awaiting selection")).not.toBeInTheDocument();
    const handoffCoverage = within(carriedContext).getByRole("region", {
      name: "Handoff coverage",
    });
    expect(within(handoffCoverage).getByText("Ready to continue")).toBeInTheDocument();
    expect(within(handoffCoverage).getByText(
      "Goal, current state, next action and 1 decision are available. "
      + "No blockers were captured. "
      + "The receiving agent should verify the repository before making changes.",
    )).toBeInTheDocument();
    expect(within(handoffCoverage).getByText("Carried forward")).toBeInTheDocument();
    expect(within(handoffCoverage).getByText("Supporting context")).toBeInTheDocument();
    expect(within(handoffCoverage).queryByText("Evidence")).not.toBeInTheDocument();
    expect(within(handoffCoverage).getByText("Missing")).toBeInTheDocument();
    expect(within(handoffCoverage).getByText("Goal captured")).toBeInTheDocument();
    expect(within(handoffCoverage).getByText("Current state captured")).toBeInTheDocument();
    expect(within(handoffCoverage).getByText("Next action captured")).toBeInTheDocument();
    expect(within(handoffCoverage).getByText("1 decision captured")).toBeInTheDocument();
    expect(within(handoffCoverage).getByText("1 relevant file")).toBeInTheDocument();
    expect(within(handoffCoverage).getByText("0 previous attempts")).toBeInTheDocument();
    expect(within(handoffCoverage).getByText("1 verification check")).toBeInTheDocument();
    expect(within(handoffCoverage).getByText("Blockers not captured")).toBeInTheDocument();
    expect(within(handoffCoverage).queryByText("—")).not.toBeInTheDocument();
    expect(within(carriedContext).queryByTestId("context-composition-pie")).not.toBeInTheDocument();
    expect(within(carriedContext).queryByLabelText("Pie chart categories")).not.toBeInTheDocument();
    expect(within(carriedContext).getByRole("button", { name: "View full evidence" })).toBeInTheDocument();
    expect(within(carriedContext).getByRole("button", { name: /Goal: 1 saved record/ })).toHaveAttribute("data-provenance", "human");
    expect(within(carriedContext).getByRole("button", { name: /State now: 1 saved record/ })).toBeInTheDocument();
    expect(within(carriedContext).getByRole("button", { name: /Start here: 1 saved record/ })).toBeInTheDocument();
    expect(within(carriedContext).getByText("Do not repeat")).toBeInTheDocument();
    expect(within(carriedContext).getByText("No failed approach or active blocker was captured.")).toBeInTheDocument();
    const fileCounter = within(carriedContext).getByRole("button", { name: /Relevant files: 1 saved record/ });
    expect(fileCounter).toHaveAttribute("data-provenance", "observed");
    expect(fileCounter).toHaveAttribute("data-context-color", "#75baa3");
    const verificationCounter = within(carriedContext).getByRole("button", { name: /Done when: 1 saved record/ });
    expect(verificationCounter).toHaveAttribute("data-context-color", "#b3a0d8");
    expect(within(carriedContext).queryByRole("button", { name: /Blockers: 0 saved records/ })).not.toBeInTheDocument();
    expect(within(carriedContext).queryByTestId("session-evidence-section")).not.toBeInTheDocument();
    expect(within(carriedContext).queryByRole("region", {
      name: "Compilation at load",
    })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Progress" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Done when: 1 saved record/ })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Exact next action" })).not.toBeInTheDocument();
    expect(screen.queryByText("Continuity")).not.toBeInTheDocument();
    expect(screen.getByText("Recovery points")).toBeInTheDocument();
    expect(screen.getByText(/Review only · the selected task does not change/)).toBeInTheDocument();
    expect(screen.queryByText("Latest work")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Start here: 1 saved record/ }));
    const nextActionDrawer = screen.getByRole("dialog", { name: "Start here" });
    expect(nextActionDrawer).toBeInTheDocument();
    expect(within(nextActionDrawer).getByText("Wire checkpoint verification into Runs")).toBeInTheDocument();
    expect(screen.getByText("Provider event · event-1")).toBeInTheDocument();
    expect(screen.getByText("View raw source")).toBeInTheDocument();
    expect(screen.getByText("View raw source").closest("summary")).toHaveClass("min-h-11");
    expect(screen.queryByText(/object Object/i)).not.toBeInTheDocument();
    expect(screen.queryByText("not run")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open project memory" })).toHaveAttribute("href", "/app/execute/inspector");
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
    const codexProvider = screen.getByRole("button", { name: "Open desktop handoff in Codex" });
    const claudeProvider = screen.getByRole("button", { name: "Open desktop handoff in Claude Code" });
    const openCodeProvider = screen.getByRole("button", { name: "Open desktop handoff in OpenCode" });
    expect(codexProvider).toBeEnabled();
    expect(claudeProvider).toBeEnabled();
    expect(openCodeProvider).toBeEnabled();
    expect(within(codexProvider).getByText("Account ready")).toBeInTheDocument();
    expect(within(claudeProvider).getByText("Account ready")).toBeInTheDocument();
    expect(within(openCodeProvider).getByText("Account ready")).toBeInTheDocument();
    expect(openCodeProvider).toHaveTextContent(
      "OpenCode desktop and provider/model access are verified.",
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
    expect(mocks.hookCalls.library).toEqual([]);
    expect(mocks.hookCalls.memory).toEqual([]);
    expect(mocks.hookCalls.providers.at(-1)).toMatchObject({
      workspaceId: "workspace-1",
      enabled: true,
    });
    expect(mocks.hookCalls.discovery.at(-1)).toEqual({});
    expect(mocks.hookCalls.digest.at(-1)).toMatchObject({
      poll: false,
      enabled: true,
    });
    expect(mocks.hookCalls.refresh).toEqual([]);
  });

  it("keeps Continue disabled until the newest local session is discovered", () => {
    mocks.latestDiscovery.data = undefined;
    mocks.latestDiscovery.isLoading = true;
    mocks.latestDiscovery.isFetching = true;
    mocks.latestDiscovery.isFetched = false;
    mocks.latestDiscovery.isFetchedAfterMount = false;
    mocks.latestDiscovery.isSuccess = false;
    mocks.providers.data = { providers: [] };
    mocks.providers.isLoading = true;

    render(<MemoryRouter><NowPage /></MemoryRouter>);

    expect(mocks.hookCalls.digest.at(-1)).toMatchObject({
      poll: false,
      enabled: false,
    });
    expect(screen.getByRole("button", {
      name: "Open desktop handoff in Codex",
    })).toBeDisabled();
    expect(screen.queryByText(
      "Finding the newest local session before enabling Continue.",
    )).not.toBeInTheDocument();
    expect(screen.queryByText("Task required:")).not.toBeInTheDocument();
    expect(mocks.hookCalls.providers.at(-1)).toMatchObject({
      workspaceId: "workspace-1",
      enabled: true,
    });
    expect(within(screen.getByRole("button", {
      name: "Open desktop handoff in Codex",
    })).getByText("Checking")).toBeInTheDocument();
    expect(screen.queryByText(/readiness was not reported/i)).not.toBeInTheDocument();
  });

  it("fails closed instead of continuing an older session when discovery fails", () => {
    mocks.latestDiscovery.data = undefined;
    mocks.latestDiscovery.isLoading = false;
    mocks.latestDiscovery.isFetching = false;
    mocks.latestDiscovery.isFetched = true;
    mocks.latestDiscovery.isFetchedAfterMount = true;
    mocks.latestDiscovery.isSuccess = false;
    mocks.latestDiscovery.isError = true;
    mocks.latestDiscovery.error = new Error("Local Codex history could not be read.");

    render(<MemoryRouter><NowPage /></MemoryRouter>);

    expect(screen.getByRole("button", {
      name: "Open desktop handoff in Codex",
    })).toBeDisabled();
    expect(screen.getByText(
      "Could not verify the newest local session",
    )).toBeInTheDocument();
    expect(screen.getByText(
      "Local Codex history could not be read.",
    )).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(mocks.latestDiscovery.refetch).toHaveBeenCalledTimes(1);
    expect(mocks.continuation.mutateAsync).not.toHaveBeenCalled();
  });

  it("shows explicit handoff coverage without a score or percentage", () => {
    const checkpoint = checkpointFixture();
    const relevantFile = checkpoint.sections.relevant_files[0];
    const previousAttempt = checkpoint.sections.progress[0];
    const verification = checkpoint.sections.verification[0];
    const decision = checkpoint.sections.decisions[0];
    checkpoint.sections.goal[0].statement = (
      "Update the license across the project so people may self-host it for "
      + "permitted uses, while preventing commercial redistribution or resale. "
      + "Align the documentation, package metadata, and deployment guidance."
    );
    checkpoint.sections.decisions = Array.from({ length: 3 }, (_, index) => ({
      ...decision,
      id: `decision-${index + 1}`,
      statement: `Licence decision ${index + 1}`,
    }));
    checkpoint.sections.blockers = [];
    checkpoint.sections.relevant_files = Array.from({ length: 29 }, (_, index) => ({
      ...relevantFile,
      id: `file-${index + 1}`,
      statement: `src/relevant-${index + 1}.js`,
    }));
    checkpoint.sections.failed_attempts = Array.from({ length: 12 }, (_, index) => ({
      ...previousAttempt,
      id: `attempt-${index + 1}`,
      statement: `Previous attempt ${index + 1}`,
    }));
    checkpoint.sections.verification = Array.from({ length: 12 }, (_, index) => ({
      ...verification,
      id: `verification-${index + 1}`,
      statement: `Verification check ${index + 1}`,
    }));
    mocks.latest.data = checkpoint;
    mocks.history.data = { checkpoints: [checkpoint] };

    render(<MemoryRouter><NowPage /></MemoryRouter>);

    const carriedContext = screen.getByRole("region", { name: "Context ready for selection" });
    expect(within(carriedContext).getByText("Continuation snapshot")).toBeInTheDocument();
    expect(within(carriedContext).getByRole("heading", {
      name: "Context prepared for review",
    })).toBeInTheDocument();
    expect(within(carriedContext).getByText("59 context records captured")).toBeInTheDocument();
    expect(within(carriedContext).getByText(
      "Update the project licence to allow self-hosting while preventing commercial redistribution.",
    )).toBeInTheDocument();
    const coverage = screen.getByRole("region", { name: "Handoff coverage" });
    expect(within(coverage).getByText("Ready to continue")).toBeInTheDocument();
    expect(within(coverage).getByText(
      "Goal, current state, next action and 3 decisions are available. "
      + "No blockers were captured. "
      + "The receiving agent should verify the repository before making changes.",
    )).toBeInTheDocument();
    expect(within(coverage).getByText("Goal captured")).toBeInTheDocument();
    expect(within(coverage).getByText("Current state captured")).toBeInTheDocument();
    expect(within(coverage).getByText("Next action captured")).toBeInTheDocument();
    expect(within(coverage).getByText("3 decisions captured")).toBeInTheDocument();
    expect(within(coverage).getByText("29 relevant files")).toBeInTheDocument();
    expect(within(coverage).getByText("12 previous attempts")).toBeInTheDocument();
    expect(within(coverage).getByText("12 verification checks")).toBeInTheDocument();
    expect(within(coverage).getByText("Supporting context")).toBeInTheDocument();
    const missing = within(coverage).getByRole("group", { name: "Missing" });
    expect(within(missing).getByText("Blockers not captured")).toBeInTheDocument();
    expect(within(missing).queryByText("—")).not.toBeInTheDocument();
    expect(within(missing).queryByText("Decisions not captured")).not.toBeInTheDocument();
    expect(coverage).not.toHaveTextContent("%");
    expect(coverage).not.toHaveTextContent(/score/i);
    expect(screen.queryByTestId("context-composition-pie")).not.toBeInTheDocument();

    const drillDownCases = [
      {
        button: /Decisions: 3 saved records/,
        dialog: "Decisions",
        item: "Licence decision 1",
      },
      {
        button: /Relevant files: 29 saved records/,
        dialog: "Relevant files",
        item: "src/relevant-1.js",
      },
      {
        button: /Do not repeat: 12 saved records/,
        dialog: "Do not repeat",
        item: "Previous attempt 1",
      },
      {
        button: /Done when: 12 saved records/,
        dialog: "Done when",
        item: "Verification check 1",
      },
    ];
    drillDownCases.forEach(({ button, dialog, item }) => {
      fireEvent.click(within(carriedContext).getByRole("button", { name: button }));
      const drawer = screen.getByRole("dialog", { name: dialog });
      expect(within(drawer).getByText(item)).toBeInTheDocument();
      fireEvent.click(within(drawer).getByRole("button", { name: "Close context details" }));
    });
  });

  it("labels import-time fallback as import time instead of source activity", () => {
    const imported = {
      ...baseDigest().activity.recent_sessions[0],
      evidence_level: "session_reported",
      recency_basis: "imported_at_fallback",
      source_activity_at: null,
    };
    mocks.digest.data.activity = {
      primary: imported,
      recent_sessions: [imported],
    };

    render(<MemoryRouter><NowPage /></MemoryRouter>);

    const statusRibbon = screen.getByLabelText("Observed work status");
    expect(within(statusRibbon).getByText(/^Imported (?:just now|\d|[A-Z])/)).toBeInTheDocument();
    expect(within(statusRibbon).getByText(/Import time; source activity time unavailable ·/)).toBeInTheDocument();
    expect(within(statusRibbon).queryByText(/^Source activity /)).not.toBeInTheDocument();
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

    const trigger = screen.getByRole("button", { name: /Start here: 1 saved record/ });
    fireEvent.click(trigger);
    const drawer = screen.getByRole("dialog", { name: "Start here" });
    expect(drawer).toHaveAttribute("aria-describedby", "context-detail-description");
    expect(screen.getByRole("button", { name: "Close context details" })).toHaveFocus();

    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Start here" })).not.toBeInTheDocument());
    expect(trigger).toHaveFocus();
  });

  it("counts stored decision records without inflating them through sentence parsing", () => {
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

    const decisionCounter = screen.getByRole("button", { name: /Decisions: 1 saved record/ });
    expect(decisionCounter).toHaveAttribute("data-context-color", "#8db7d1");
    fireEvent.click(decisionCounter);
    const drawer = screen.getByRole("dialog", { name: "Decisions" });
    expect(drawer.querySelectorAll("ol > li")).toHaveLength(1);
    expect(within(drawer).getByText(/The continuation brief should name its subject/)).toBeInTheDocument();
    expect(within(drawer).getByText(/Keep C:\\new\\tool unchanged/)).toBeInTheDocument();
    expect(within(drawer).getByText(/Keep foo\\nbar literal/)).toBeInTheDocument();
  });

  it("keeps Continue runnable from authoritative discovery while evidence loads", () => {
    mocks.digest.data = null;
    mocks.digest.isLoading = true;

    render(<MemoryRouter><NowPage /></MemoryRouter>);

    expect(screen.getByRole("heading", { name: "Continue with Session Context", level: 1 })).toBeInTheDocument();
    expect(screen.queryByText("Loading activity")).not.toBeInTheDocument();
    expect(screen.getByText("Loading evidence")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open desktop handoff in Codex" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Open desktop handoff in Claude Code" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Open desktop handoff in OpenCode" })).toBeEnabled();
    expect(screen.getByRole("region", { name: "Preparing desktop handoff" })).toBeInTheDocument();
    expect(screen.queryByText("No agent progress observed yet.")).not.toBeInTheDocument();
    expect(screen.queryByText("No verified result captured.")).not.toBeInTheDocument();
    expect(screen.queryByText("No blocker, conflict, stale evidence, or high-risk review is currently visible.")).not.toBeInTheDocument();
    expect(mocks.hookCalls.latest[0]).toMatchObject({
      provider: "codex",
      sessionId: "session-1",
      enabled: true,
    });
    expect(mocks.hookCalls.history.at(-1)).toMatchObject({ limit: 12, enabled: true });
    expect(mocks.hookCalls.library).toEqual([]);
    expect(mocks.hookCalls.memory).toEqual([]);
    expect(mocks.hookCalls.providers.at(-1)).toMatchObject({
      workspaceId: "workspace-1",
      enabled: true,
    });
    expect(mocks.hookCalls.refresh).toEqual([]);
  });

  it("reserves the continuation visual while saved context is loading", () => {
    mocks.latest.data = null;
    mocks.latest.isLoading = true;

    render(<MemoryRouter><NowPage /></MemoryRouter>);

    expect(screen.getByRole("region", { name: "Preparing desktop handoff" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Progress" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Verification" })).not.toBeInTheDocument();
  });

  it("does not fall back to stale indexed work when discovery finds no session", () => {
    mocks.digest.data = {
      ...baseDigest(),
      current_goal: null,
      activity: { primary: null },
    };
    mocks.latest.data = null;
    mocks.latestDiscovery.data = latestDiscoveryResult(null);

    render(<MemoryRouter><NowPage /></MemoryRouter>);

    expect(screen.getByRole("button", { name: "Open desktop handoff in Codex" })).toBeDisabled();
    expect(screen.getAllByText(
      /No current in-project root session was found/i,
    ).length).toBeGreaterThan(0);
    expect(screen.queryByRole("button", { name: "Save current context" })).not.toBeInTheDocument();
    expect(mocks.hookCalls.library).toEqual([]);
  });

  it("keeps the saved context preview available when the initial digest fails", () => {
    mocks.digest.data = null;
    mocks.digest.isLoading = false;
    mocks.digest.isError = true;
    mocks.digest.error = new Error("Digest timed out");

    render(<MemoryRouter><NowPage /></MemoryRouter>);

    expect(screen.getByRole("heading", { name: "Continue with Session Context", level: 1 })).toBeInTheDocument();
    expect(screen.queryByText("Activity unavailable")).not.toBeInTheDocument();
    expect(screen.getByText("Evidence unavailable")).toBeInTheDocument();
    expect(screen.getByText("Could not load current activity")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Context ready for selection" })).toBeInTheDocument();
    expect(screen.getAllByText("Current saved boundary").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "Open desktop handoff in Codex" })).toBeEnabled();
    expect(screen.getByText(/Live activity is unavailable/)).toBeInTheDocument();
  });

  it("keeps cached activity visible when a background digest refresh fails", () => {
    mocks.digest.isError = true;
    mocks.digest.error = new Error("Refresh timed out");

    render(<MemoryRouter><NowPage /></MemoryRouter>);

    expect(screen.getByRole("heading", { name: "Continue with Session Context", level: 1 })).toBeInTheDocument();
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

    render(<MemoryRouter><NowPage /></MemoryRouter>);

    expect(screen.queryByRole("button", { name: "Checking resume availability…" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Verify checkpoint" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Resume task" })).not.toBeInTheDocument();
    expect(screen.getByText(/Nothing is presented as carried until repository reconciliation/)).toBeInTheDocument();
  });

  it("keeps the legacy resume dialog removed while exposing the session handoff action", () => {
    render(<MemoryRouter><NowPage /></MemoryRouter>);

    expect(screen.queryByRole("button", { name: "Resume task" })).not.toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: "Review and resume" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", {
      name: "Copy current session context",
    })).toBeInTheDocument();
  });

  it("ignores URL task envelopes and keeps model controls on the latest session", async () => {
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
      name: "Harden checkpoint capture",
    })).toBeInTheDocument();
    expect(screen.queryByRole("definition", {
      name: "Remove screenshot IDs and temporary paths from the Now page.",
    })).not.toBeInTheDocument();
    expect(screen.queryByText(/Screenshot 2026-07-23/)).not.toBeInTheDocument();
    expect(screen.queryByText(/\/var\/folders/)).not.toBeInTheDocument();
    expect(screen.queryByText(/screencaptureui_/)).not.toBeInTheDocument();

    fireEvent.change(screen.getByRole("combobox", { name: "Codex model" }), {
      target: { value: "gpt-5.6-terra" },
    });
    fireEvent.change(screen.getByRole("combobox", {
      name: "Codex reasoning effort",
    }), {
      target: { value: "high" },
    });
    fireEvent.click(screen.getByRole("button", {
      name: "Open desktop handoff in Codex",
    }));
    await waitFor(() => expect(mocks.continuation.mutateAsync).toHaveBeenCalled());
    const request = mocks.continuation.mutateAsync.mock.calls.at(-1)[0];
    expect(request).toMatchObject({
      source_provider: "codex",
      source_session_id: "session-1",
      target_provider: "codex",
      provider_model: "gpt-5.6-terra",
      provider_effort: "high",
    });
    expect(request).not.toHaveProperty("objective");
  });

  it("falls back instead of displaying metadata-only activity", () => {
    const attachmentOnly = "Screenshot 2026-07-23 at 16.42.18.png: /var/folders/example/TemporaryItems/NSIRD_screencaptureui_abc/Screenshot 2026-07-23 at 16.42.18.png";
    mocks.digest.data.current_goal = null;
    mocks.digest.data.activity.primary.request = attachmentOnly;
    mocks.digest.data.activity.primary.title = attachmentOnly;

    render(<MemoryRouter><NowPage /></MemoryRouter>);

    expect(screen.getByRole("heading", { name: "Continue with Session Context", level: 1 })).toBeInTheDocument();
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

    fireEvent.click(screen.getByRole("button", { name: "Open desktop handoff in Codex" }));
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

  it("defaults Continue to the newest available session", async () => {
    const older = {
      ...mocks.digest.data.activity.recent_sessions[0],
      session_id: "older-session",
      source_document_id: "older-source",
      session_title: "Older task",
      title: "Older task",
      source_activity_at: "2026-07-21T09:00:00Z",
      updated_at: "2026-07-21T09:00:00Z",
    };
    const newest = {
      ...mocks.digest.data.activity.recent_sessions[0],
      session_id: "newest-session",
      source_document_id: "newest-source",
      session_title: "Newest task",
      title: "Newest task",
      source_activity_at: "2026-07-21T12:00:00Z",
      updated_at: "2026-07-21T12:00:00Z",
    };
    mocks.digest.data.activity.recent_sessions = [older, newest];
    mocks.latestDiscovery.data = latestDiscoveryResult({
      id: "codex:newest-session",
      session_id: "newest-session",
      source_document_id: "newest-source",
      title: "Newest task",
      preview: "Newest task",
      updated_at: "2026-07-21T12:00:00Z",
      revision_number: 2,
    });

    render(<MemoryRouter><NowPage /></MemoryRouter>);

    expect(screen.getByRole("definition", {
      name: "Newest task",
    })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", {
      name: "Open desktop handoff in Codex",
    }));

    await waitFor(() => expect(
      mocks.continuation.mutateAsync,
    ).toHaveBeenCalled());
    expect(mocks.continuation.mutateAsync.mock.calls.at(-1)[0]).toMatchObject({
      source_provider: "codex",
      source_session_id: "newest-session",
      target_provider: "codex",
    });
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
    mocks.latestDiscovery.data = latestDiscoveryResult({
      id: "codex:newest-root-session",
      session_id: "newest-root-session",
      source_document_id: "newest-root-source",
      title: "Fix harness continuation workflow",
      preview: "Continue AI Infra strategy",
      updated_at: "2026-07-25T09:59:00Z",
      revision_number: 2,
    });

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

    fireEvent.click(screen.getByRole("button", { name: "Open desktop handoff in Codex" }));
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
    mocks.latestDiscovery.data = latestDiscoveryResult({
      id: "codex:source-with-limited-display",
      session_id: "source-with-limited-display",
      source_document_id: "source-with-limited-display-document",
      title: "conversationId",
      preview: "You are an agent in a team of agents",
      revision_number: 2,
    });

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
    expect(screen.getByRole("button", { name: "Open desktop handoff in Codex" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Open desktop handoff in Codex" }));

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
    fireEvent.click(screen.getByRole("button", { name: "Open desktop handoff in Claude Code" }));

    await waitFor(() => expect(mocks.continuation.mutateAsync).toHaveBeenCalledWith({
      idempotency_key: expect.any(String),
      repo_path: "/workspace/daemonstate",
      source_provider: "codex",
      source_session_id: "session-1",
      target_provider: "claude",
      workspace_id: "workspace-1",
    }));
    const firstRequestKey = (
      mocks.continuation.mutateAsync.mock.calls[0][0].idempotency_key
    );
    expect(navigator.clipboard.writeText).not.toHaveBeenCalled();
    const status = await screen.findByRole("status");
    expect(status).toHaveTextContent("Continue in Claude Code");
    expect(status).toHaveTextContent(
      "Context copied. Review the draft, then send it in Claude Code.",
    );
    expect(status).not.toHaveTextContent("App rendering cannot be verified here");
    expect(status).not.toHaveTextContent("Look for Claude Code on your desktop");
    const requestAgain = screen.getByRole("button", {
      name: "Open desktop handoff in Claude Code",
    });
    expect(requestAgain).toBeEnabled();
    expect(requestAgain).toHaveTextContent("Request again");
    expect(status).not.toHaveTextContent("agent is working");
    expect(status).not.toHaveTextContent(/verification after/i);
    expect(await screen.findByRole("heading", { name: "Open requested" })).toBeInTheDocument();
    const carriedContext = screen.getByRole("region", { name: "Open requested" });
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
    expect(within(carriedContext).getByRole("button", { name: /Goal: 1 selected record/ })).toHaveAttribute("data-provenance", "human");
    expect(screen.getByRole("button", { name: /Decisions: 1 selected record/ })).toBeInTheDocument();
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

    fireEvent.click(requestAgain);
    await waitFor(() => expect(
      mocks.continuation.mutateAsync,
    ).toHaveBeenCalledTimes(2));
    expect(
      mocks.continuation.mutateAsync.mock.calls[1][0].idempotency_key,
    ).not.toBe(firstRequestKey);
  });

  it("warns when a visible desktop draft has an incomplete foundation", async () => {
    const staged = await mocks.continuation.mutateAsync();
    mocks.continuation.mutateAsync.mockReset().mockResolvedValue({
      ...staged,
      preparation: {
        ...staged.preparation,
        project_context: {
          copy_ready: false,
          quality_issues: [{
            code: "project_context_core_sections_empty",
            message: "Project Context core sections are incomplete.",
            blocks_current_execution: true,
            blocks_copy: true,
          }],
        },
      },
    });
    render(<MemoryRouter><NowPage /></MemoryRouter>);

    fireEvent.click(screen.getByRole("button", {
      name: "Open desktop handoff in Codex",
    }));

    const status = await screen.findByRole("status");
    expect(status).toHaveTextContent("Continue in Claude Code");
    expect(status).toHaveTextContent("Session Context needs repository review");
    expect(status).toHaveTextContent("Its inherited Workspace Context is incomplete.");
    expect(status).toHaveTextContent(
      "Review the repository in the opened desktop app before submitting.",
    );
    expect(status).toHaveTextContent("Automatic execution remains blocked.");
    expect(status).toHaveTextContent("Context copied.");
    expect(screen.queryByText("Project Context is not safe to stage")).not.toBeInTheDocument();
  });

  it("stages an exact source without exposing an editable continuation lead", async () => {
    render(<MemoryRouter><NowPage /></MemoryRouter>);

    expect(screen.queryByRole("textbox", {
      name: "Immediate continuation lead",
    })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", {
      name: "Open desktop handoff in Codex",
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

  it("updates the resolved task when latest discovery changes source", async () => {
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
    mocks.latestDiscovery.data = latestDiscoveryResult({
      id: "codex:new-source-task",
      session_id: "new-source-task",
      source_document_id: "new-source-document",
      title: "Finish the newly selected source task",
      preview: "Finish the newly selected source task",
      updated_at: "2026-07-21T11:00:00Z",
      revision_number: 2,
    });
    view.rerender(<MemoryRouter><NowPage /></MemoryRouter>);

    await waitFor(() => expect(screen.getByRole("definition", {
      name: "Finish the newly selected source task",
    })).toBeInTheDocument());
  });

  it("does not advance the workflow before the user submits the staged lead", async () => {
    render(<MemoryRouter><NowPage /></MemoryRouter>);

    fireEvent.click(screen.getByRole("button", { name: "Open desktop handoff in Codex" }));

    const status = await screen.findByRole("status");
    expect(status).toHaveTextContent("Context copied.");
    expect(status).not.toHaveTextContent("Workflow advanced after verification");
  });

  it.each([
    ["Codex", "codex"],
    ["Claude Code", "claude"],
    ["OpenCode", "opencode"],
  ])("loads the shared continuation into the selected %s provider", async (label, provider) => {
    render(<MemoryRouter><NowPage /></MemoryRouter>);

    fireEvent.click(screen.getByRole("button", { name: `Open desktop handoff in ${label}` }));

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

  it("does not let an explicit URL source replace the latest session", async () => {
    const rawObjective = "Fix the revoked Claude token without losing adapter context";

    render(
      <MemoryRouter initialEntries={[
        `/app?objective=${encodeURIComponent(rawObjective)}&repo_path=${encodeURIComponent("/workspace/explicit-session")}&source_provider=claude&source_session=explicit-session`,
      ]}>
        <NowPage />
      </MemoryRouter>,
    );

    expect(screen.queryByRole("definition", { name: rawObjective })).not.toBeInTheDocument();
    expect(screen.getByRole("definition", {
      name: "Harden checkpoint capture",
    })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Open desktop handoff in OpenCode" }));
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

  it("does not display a URL objective in place of the latest session goal", () => {
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

    expect(screen.queryByRole("definition", { name: longGoal })).not.toBeInTheDocument();
    const goalDefinition = screen.getByRole("definition", {
      name: "Harden checkpoint capture",
    });
    expect(goalDefinition.closest("dl")).toHaveClass("sr-only");
    expect(screen.queryByText("Read full goal")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Continuation task contract")).not.toBeInTheDocument();
  });

  it("ignores marker-looking URL objective literals on Continue", async () => {
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

    expect(screen.queryByRole("definition", {
      name: /Files mentioned by the user/,
    })).not.toBeInTheDocument();
    expect(screen.queryByText("Read full goal")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Open desktop handoff in OpenCode" }));
    await waitFor(() => expect(mocks.continuation.mutateAsync).toHaveBeenCalled());
    expect(mocks.continuation.mutateAsync.mock.calls.at(-1)[0]).toMatchObject({
      source_provider: "codex",
      source_session_id: "session-1",
      target_provider: "opencode",
    });
    expect(mocks.continuation.mutateAsync.mock.calls.at(-1)[0]).not.toHaveProperty(
      "objective",
    );
  });

  it("ignores a URL diagnostic and retains the latest source identity", async () => {
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

    expect(screen.queryByRole("definition", {
      name: /Concrete evidence from data\/context\.db/i,
    })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Open desktop handoff in OpenCode" }));
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

  it("ignores a source-backed URL override and continues the latest session", async () => {
    const sourceObjective = "Build one card per session.";

    render(
      <MemoryRouter initialEntries={[
        `/app?objective=${encodeURIComponent(sourceObjective)}&objective_source=session&repo_path=${encodeURIComponent("/workspace/source-session")}&source_provider=codex&source_session=source-session`,
      ]}>
        <NowPage />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Open desktop handoff in Claude Code" }));
    await waitFor(() => expect(mocks.continuation.mutateAsync).toHaveBeenCalledWith(
      expect.objectContaining({
        repo_path: "/workspace/daemonstate",
        source_provider: "codex",
        source_session_id: "session-1",
        target_provider: "claude",
      }),
    ));
    const request = mocks.continuation.mutateAsync.mock.calls.at(-1)[0];
    expect(request).not.toHaveProperty("objective");
  });

  it("shows missing Claude Desktop and keeps installed alternatives usable", () => {
    mocks.providers.data.providers = mocks.providers.data.providers.map((provider) => (
      provider.provider === "claude"
        ? {
            ...provider,
            status: "unavailable",
            ready: false,
            code: "desktop_app_missing",
            desktop_handoff_supported: false,
            message: "Claude Desktop is not installed.",
            action: "Install Claude Desktop, then check again.",
          }
        : provider
    ));

    render(<MemoryRouter><NowPage /></MemoryRouter>);

    const claude = screen.getByRole("button", { name: "Open desktop handoff in Claude Code" });
    expect(claude).toBeDisabled();
    expect(claude).toHaveAttribute("data-provider-ready", "false");
    expect(within(claude).getByText("Desktop missing")).toBeInTheDocument();
    expect(claude).toHaveTextContent("Claude Desktop is not installed.");
    expect(claude).toHaveTextContent("Next: Install Claude Desktop, then check again.");
    expect(screen.getByRole("button", { name: "Open desktop handoff in Codex" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Open desktop handoff in OpenCode" })).toBeEnabled();
    const retry = screen.getByRole("button", { name: "Retry desktop readiness" });
    fireEvent.click(retry);
    expect(mocks.providers.refetch).toHaveBeenCalledTimes(1);

    fireEvent.click(claude);
    expect(mocks.continuation.mutateAsync).not.toHaveBeenCalled();
  });

  it("opens OpenCode without a manual provider-access attestation", async () => {
    mocks.providers.data.providers = mocks.providers.data.providers.map((provider) => (
      provider.provider === "opencode"
        ? {
            ...provider,
            status: "ready",
            ready: true,
            code: "desktop_dispatch_ready",
            desktop_available: true,
            desktop_handoff_supported: true,
            account_access_state: "unverified",
            account_access_verified: false,
            capabilities: {
              desktop_dispatch_available: true,
              account_access_probe_supported: false,
            },
            message: (
              "OpenCode Desktop is ready to receive the draft. "
              + "OpenCode will verify account and model access when the user sends."
            ),
            action: "Open the prepared draft in OpenCode.",
          }
        : provider
    ));

    render(<MemoryRouter><NowPage /></MemoryRouter>);

    const openCode = screen.getByRole("button", {
      name: "Open desktop handoff in OpenCode",
    });
    expect(openCode).toBeEnabled();
    expect(openCode).toHaveAttribute("data-provider-ready", "true");
    expect(within(openCode).getByText("Ready")).toBeVisible();
    expect(openCode).toHaveTextContent(
      "OpenCode Desktop is ready to receive the draft.",
    );
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    fireEvent.click(openCode);
    await waitFor(() => expect(mocks.continuation.mutateAsync).toHaveBeenCalled());
    expect(mocks.continuation.mutateAsync.mock.calls.at(-1)[0]).toMatchObject({
      target_provider: "opencode",
    });
    expect(mocks.continuation.mutateAsync.mock.calls.at(-1)[0]).not.toHaveProperty(
      "desktop_access_confirmation",
    );
  });

  it("fails closed when a ready provider cannot open a desktop handoff", () => {
    mocks.providers.data.providers = mocks.providers.data.providers.map((provider) => (
      provider.provider === "codex"
        ? {
            ...provider,
            desktop_handoff_supported: false,
          }
        : provider
    ));

    render(<MemoryRouter><NowPage /></MemoryRouter>);

    const codex = screen.getByRole("button", { name: "Open desktop handoff in Codex" });
    expect(codex).toBeDisabled();
    expect(within(codex).getByText("No handoff")).toBeInTheDocument();
    expect(codex).toHaveTextContent(
      "Codex cannot open a visible desktop handoff on this machine.",
    );
    expect(codex).toHaveTextContent(
      "Next: Install or update the desktop app, then retry.",
    );
    fireEvent.click(codex);
    expect(mocks.continuation.mutateAsync).not.toHaveBeenCalled();
  });

  it("ignores legacy OpenCode CLI readiness even when it reports ready", () => {
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

    const openCode = screen.getByRole("button", { name: "Open desktop handoff in OpenCode" });
    expect(openCode).toBeDisabled();
    expect(openCode).toHaveAttribute("data-provider-ready", "false");
    expect(within(openCode).getByText("Unavailable")).toBeInTheDocument();
    expect(openCode).toHaveTextContent(
      "OpenCode reported provider-CLI state, which Continue ignores.",
    );
    expect(openCode).toHaveTextContent(
      "Next: Refresh desktop readiness before continuing.",
    );
    expect(screen.getByRole("button", { name: "Open desktop handoff in Codex" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Open desktop handoff in Claude Code" })).toBeEnabled();

    fireEvent.click(openCode);
    expect(mocks.continuation.mutateAsync).not.toHaveBeenCalled();
  });

  it.each([
    {
      status: "configuration_required",
      code: "provider_configuration_required",
      reportedReady: true,
    },
    {
      status: "unavailable",
      code: "provider_cli_not_found",
      reportedReady: true,
    },
  ])("rejects legacy $code as non-runnable desktop state", ({
    status,
    code,
    reportedReady,
  }) => {
    mocks.providers.data.providers = mocks.providers.data.providers.map((provider) => (
      provider.provider === "claude"
        ? {
            ...provider,
            status,
            ready: reportedReady,
            code,
            message: "Legacy provider CLI state.",
            action: "Configure the provider CLI.",
          }
        : provider
    ));

    render(<MemoryRouter><NowPage /></MemoryRouter>);

    const claude = screen.getByRole("button", { name: "Open desktop handoff in Claude Code" });
    expect(claude).toBeDisabled();
    expect(claude).toHaveAttribute("data-provider-ready", "false");
    expect(within(claude).getByText("Unavailable")).toBeInTheDocument();
    expect(claude).toHaveTextContent(
      "Claude Code reported provider-CLI state, which Continue ignores.",
    );
    expect(claude).toHaveTextContent(
      "Next: Refresh desktop readiness before continuing.",
    );
  });

  it("shows provider probes as checking instead of unavailable", () => {
    mocks.providers.data = { providers: [] };
    mocks.providers.isLoading = true;

    render(<MemoryRouter><NowPage /></MemoryRouter>);

    for (const label of ["Codex", "Claude Code", "OpenCode"]) {
      const provider = screen.getByRole("button", { name: `Open desktop handoff in ${label}` });
      expect(provider).toBeDisabled();
      expect(within(provider).getByText("Checking")).toBeInTheDocument();
    }
  });

  it("keeps the staging state visible when background session refresh changes the task key", () => {
    mocks.continuation.mutateAsync.mockImplementation(() => new Promise(() => {}));
    const view = render(<MemoryRouter><NowPage /></MemoryRouter>);

    fireEvent.click(screen.getByRole("button", { name: "Open desktop handoff in OpenCode" }));

    const status = screen.getByRole("status");
    expect(status).toHaveAttribute("aria-busy", "true");
    expect(status).toHaveTextContent("Requesting a desktop handoff in OpenCode");
    expect(status).toHaveTextContent("Requesting a visible desktop handoff");
    expect(status).toHaveTextContent(
      "Compiling context and requesting the selected desktop app. No provider CLI or task is being started",
    );
    expect(screen.getByRole("button", { name: "Open desktop handoff in OpenCode" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Open desktop handoff in OpenCode" })).toHaveAttribute("data-provider-pending", "true");
    expect(screen.getByRole("button", { name: "Open desktop handoff in OpenCode" })).toHaveClass("disabled:cursor-wait");
    expect(within(screen.getByRole("button", { name: "Open desktop handoff in OpenCode" })).getByText("Requesting")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open desktop handoff in Codex" })).toHaveAttribute("data-provider-pending", "false");

    mocks.digest.data.activity.recent_sessions[0] = {
      ...mocks.digest.data.activity.recent_sessions[0],
      session_title: "Background refresh imported a newer session title",
      title: "Background refresh imported a newer session title",
      session_id: "background-refresh-session",
      source_activity_at: "2026-07-25T16:04:00Z",
    };
    view.rerender(<MemoryRouter><NowPage /></MemoryRouter>);

    expect(screen.getByRole("status")).toHaveTextContent("Requesting a desktop handoff in OpenCode");
    expect(screen.getByRole("button", { name: "Open desktop handoff in OpenCode" })).toHaveAttribute("data-provider-pending", "true");
  });

  it("reuses an in-flight request key across remount and provider switch", async () => {
    mocks.continuation.mutateAsync.mockImplementation(() => new Promise(() => {}));
    const firstView = render(<MemoryRouter><NowPage /></MemoryRouter>);

    fireEvent.click(screen.getByRole("button", {
      name: "Open desktop handoff in Codex",
    }));
    await waitFor(() => expect(
      mocks.continuation.mutateAsync,
    ).toHaveBeenCalledTimes(1));
    const firstRequest = mocks.continuation.mutateAsync.mock.calls[0][0];

    firstView.unmount();
    const secondView = render(<MemoryRouter><NowPage /></MemoryRouter>);
    fireEvent.click(screen.getByRole("button", {
      name: "Open desktop handoff in OpenCode",
    }));
    await waitFor(() => expect(
      mocks.continuation.mutateAsync,
    ).toHaveBeenCalledTimes(2));
    const reloadedRequest = mocks.continuation.mutateAsync.mock.calls[1][0];

    expect(reloadedRequest.idempotency_key).toBe(
      firstRequest.idempotency_key,
    );
    expect(firstRequest.target_provider).toBe("codex");
    expect(reloadedRequest.target_provider).toBe("opencode");

    secondView.unmount();
    mocks.providers.data.staged_handoff = {
      schema_version: "continuation.stage.v1",
      status: "awaiting_user",
      delivery: {
        status: "awaiting_user",
        provider: "codex",
        handoff_id: "recovered-visible-handoff",
        context_delivery: "desktop_composer_prefill_and_clipboard",
        execution_started: false,
        harness_session: {
          handoff_id: "recovered-visible-handoff",
          open_requested: true,
          context_copied: true,
          context_loaded: false,
          execution_started: false,
        },
      },
      run: {
        handoff_id: "recovered-visible-handoff",
        provider: "codex",
        status: "awaiting_user",
        started_at: new Date(
          Date.now() - ((2 * 24 * 60 * 60 * 1000) + (60 * 1000)),
        ).toISOString(),
        execution_started: false,
      },
    };
    render(<MemoryRouter><NowPage /></MemoryRouter>);
    const restoredStatus = screen.getByRole("status");
    expect(restoredStatus).toHaveTextContent(
      "Previous Codex handoff · 2 days ago",
    );
    expect(restoredStatus).toHaveTextContent(
      "Nothing is running now. Request again if needed.",
    );
    expect(restoredStatus).not.toHaveTextContent("Continue in Codex");
    const requestAgain = screen.getByRole("button", {
      name: "Open desktop handoff in Codex",
    });
    expect(requestAgain).toHaveTextContent("Request again");

    fireEvent.click(requestAgain);
    await waitFor(() => expect(
      mocks.continuation.mutateAsync,
    ).toHaveBeenCalledTimes(3));
    expect(
      mocks.continuation.mutateAsync.mock.calls[2][0].idempotency_key,
    ).not.toBe(firstRequest.idempotency_key);
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

    const codex = screen.getByRole("button", { name: "Open desktop handoff in Codex" });
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

  it("does not treat a legacy hidden thread as a successful desktop handoff", () => {
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

    expect(screen.queryByText(/Previous Codex handoff/)).not.toBeInTheDocument();
    const codex = screen.getByRole("button", { name: "Open desktop handoff in Codex" });
    expect(codex).toBeEnabled();
    expect(codex).toHaveAttribute("data-desktop-open-requested", "false");
    expect(screen.queryByRole("button", { name: "Open Codex thread" })).not.toBeInTheDocument();
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

    const opencode = screen.getByRole("button", { name: "Open desktop handoff in OpenCode" });
    expect(opencode).toBeEnabled();
    expect(opencode).toHaveAttribute("aria-busy", "false");
    expect(screen.getByRole("alert")).toHaveTextContent("OpenCode continuation failed");
    expect(screen.getByRole("alert")).toHaveTextContent("OpenCode exited after repeated provider errors");
    expect(screen.getByRole("alert")).toHaveTextContent("No successful handoff is being claimed");
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

  it("does not let a recovery URL replace the latest Continue session", async () => {
    render(
      <MemoryRouter initialEntries={["/app?objective=Review%20Beta%20pricing&repo_path=%2Fworkspace%2Fselected-session&checkpoint=checkpoint-legacy&checkpoint_source=source-legacy"]}>
        <NowPage />
      </MemoryRouter>,
    );

    expect(screen.queryByRole("definition", {
      name: "Review Beta pricing",
    })).not.toBeInTheDocument();
    expect(screen.queryByText(
      "Recovery request · checkpoint-legacy",
    )).not.toBeInTheDocument();
    expect(screen.getByRole("definition", {
      name: "Harden checkpoint capture",
    })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Open desktop handoff in Codex" }));

    await waitFor(() => expect(mocks.continuation.mutateAsync).toHaveBeenCalledWith(
      expect.objectContaining({
      idempotency_key: expect.any(String),
      repo_path: "/workspace/daemonstate",
      source_provider: "codex",
      source_session_id: "session-1",
      target_provider: "codex",
      workspace_id: "workspace-1",
      }),
    ));
    const request = mocks.continuation.mutateAsync.mock.calls.at(-1)[0];
    expect(request).not.toHaveProperty("checkpoint_id");
    expect(request).not.toHaveProperty("checkpoint_source_id");
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

    fireEvent.click(screen.getByRole("button", { name: "Open desktop handoff in Codex" }));

    const blocker = await screen.findByRole("alert");
    expect(blocker).toHaveTextContent("Context staging was not confirmed");
    expect(blocker).toHaveTextContent(
      "desktop open request and clipboard copy were not both confirmed",
    );
    expect(screen.queryByText(/Continue in Codex/)).not.toBeInTheDocument();
    expect(blocker).not.toHaveTextContent("Audited the configuration");
    expect(blocker).toHaveTextContent("No successful handoff is being claimed");
  });

  it("shows the backend blocker instead of sending the user to inspect context", async () => {
    mocks.continuation.mutateAsync.mockRejectedValue(
      new Error("No installed target agent is available."),
    );
    render(<MemoryRouter><NowPage /></MemoryRouter>);

    fireEvent.click(screen.getByRole("button", { name: "Open desktop handoff in Codex" }));

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
    [409, false],
    [504, true],
  ])(
    "rotates a terminal %s desktop timeout key but retains an ambiguous one",
    async (status, shouldReuse) => {
      const error = Object.assign(
        new Error("The desktop open request timed out."),
        {
          status,
          detail: {
            code: "desktop_handoff_timeout",
            blocker: {
              code: "desktop_handoff_timeout",
              message: "The desktop open request timed out.",
              action: "Check the desktop app before trying again.",
            },
          },
        },
      );
      mocks.continuation.mutateAsync.mockRejectedValue(error);
      render(<MemoryRouter><NowPage /></MemoryRouter>);

      const button = screen.getByRole("button", {
        name: "Open desktop handoff in Codex",
      });
      fireEvent.click(button);
      await waitFor(() => expect(
        mocks.continuation.mutateAsync,
      ).toHaveBeenCalledTimes(1));
      const firstKey = (
        mocks.continuation.mutateAsync.mock.calls[0][0].idempotency_key
      );

      fireEvent.click(button);
      await waitFor(() => expect(
        mocks.continuation.mutateAsync,
      ).toHaveBeenCalledTimes(2));
      const secondKey = (
        mocks.continuation.mutateAsync.mock.calls[1][0].idempotency_key
      );
      if (shouldReuse) expect(secondKey).toBe(firstKey);
      else expect(secondKey).not.toBe(firstKey);
    },
  );

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

    fireEvent.click(screen.getByRole("button", { name: "Open desktop handoff in OpenCode" }));

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

    fireEvent.click(screen.getByRole("button", { name: "Open desktop handoff in OpenCode" }));

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

    fireEvent.click(screen.getByRole("button", { name: "Open desktop handoff in OpenCode" }));

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

    fireEvent.click(screen.getByRole("button", { name: "Open desktop handoff in Claude Code" }));

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

    fireEvent.click(screen.getByRole("button", { name: "Open desktop handoff in Claude Code" }));

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

    fireEvent.click(screen.getByRole("button", { name: "Open desktop handoff in Codex" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Continue in Claude Code");

    mocks.digest.data.activity.recent_sessions[0] = {
      ...mocks.digest.data.activity.recent_sessions[0],
      cwd: "/workspace/daemonstate-next",
    };
    mocks.latestDiscovery.data = latestDiscoveryResult({
      cwd: "/workspace/daemonstate-next",
      updated_at: "2026-07-21T10:01:00Z",
      revision_number: 2,
    });
    view.rerender(<MemoryRouter><NowPage /></MemoryRouter>);

    await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Open desktop handoff in Codex" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Continue in Claude Code");
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
    mocks.latestDiscovery.data = latestDiscoveryResult({
      id: "codex:new-continuation-target",
      session_id: "new-continuation-target",
      source_document_id: "new-continuation-source",
      title: "Verify the new continuation target",
      preview: "Verify the new continuation target",
      updated_at: "2026-07-22T10:00:00Z",
      revision_number: 3,
    });
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
    mocks.latestDiscovery.data = latestDiscoveryResult(null);

    render(<MemoryRouter><NowPage /></MemoryRouter>);

    expect(screen.getByRole("link", { name: "Choose work to continue" })).toHaveAttribute("href", "/app/library");
    expect(screen.getAllByText(
      /No current in-project root session was found/i,
    ).length).toBeGreaterThan(0);
    expect(mocks.hookCalls.library).toEqual([]);
  });

  it("does not enable a provider when only a repository can be resolved", () => {
    mocks.latest.data = null;
    mocks.history.data = { checkpoints: [] };
    mocks.library.data = { sessions: [] };
    mocks.digest.data.current_goal = null;
    mocks.digest.data.activity.primary = null;
    mocks.digest.data.activity.recent_sessions = [];
    mocks.latestDiscovery.data = latestDiscoveryResult(null);

    render(<MemoryRouter><NowPage /></MemoryRouter>);

    const codexProvider = screen.getByRole("button", { name: "Open desktop handoff in Codex" });
    expect(codexProvider).toBeDisabled();
    expect(codexProvider).toHaveAttribute("data-provider-ready", "true");
    expect(codexProvider).toHaveAttribute("data-task-ready", "false");
    expect(within(codexProvider).getByText("Account ready")).toBeVisible();
    expect(within(codexProvider).getByText("Task required:")).toBeVisible();
    expect(within(codexProvider).getByText(
      /No current in-project root session was found/i,
    )).toBeVisible();
    expect(within(codexProvider).getByText("Task required", { exact: true })).toBeVisible();
    expect(within(codexProvider).queryByText("Continue", { exact: true })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Choose work to continue" })).toHaveAttribute("href", "/app/library");
  });

  it("uses authoritative latest discovery when the digest still points to older work", async () => {
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
      session_title: "Stale digest task",
      title: "Stale digest task",
      session_id: "stale-digest-session",
      cwd: "/workspace/stale-digest-session",
    };
    mocks.latestDiscovery.data = latestDiscoveryResult({
      id: "codex:newest-root-session",
      session_id: "newest-root-session",
      source_document_id: "newest-root-source",
      title: "Continue the newest root session",
      preview: "Continue the newest root session",
      cwd: "/workspace/newest-root-session",
      updated_at: "2026-07-21T11:00:00Z",
      revision_number: 2,
    });

    render(<MemoryRouter><NowPage /></MemoryRouter>);
    expect(screen.getByRole("definition", {
      name: "Continue the newest root session",
    })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Open desktop handoff in Codex" }));

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
    expect(screen.getByText(/Nothing is presented as carried until repository reconciliation/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open desktop handoff in Codex" })).toBeInTheDocument();
    expect(mocks.verify.mutate).not.toHaveBeenCalled();
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
      name: "Continue with Session Context",
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
    mocks.latestDiscovery.data = latestDiscoveryResult({
      id: "codex:current-session",
      session_id: "current-session",
      source_document_id: "current-source",
      title: "Current observed task",
      preview: "Current session update.",
      updated_at: "2026-07-22T08:00:00Z",
      revision_number: 2,
    });

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
    mocks.latestDiscovery.data = latestDiscoveryResult({
      id: "codex:current-session",
      session_id: "current-session",
      source_document_id: "current-source",
      title: "Harden checkpoint capture",
      preview: "Implemented normalized session events.",
      revision_number: 2,
    });
    mocks.library.data.sessions = [{ connector_type: "opencode", session_id: "older-session" }];

    render(<MemoryRouter><NowPage /></MemoryRouter>);
    expect(screen.queryByRole("button", { name: "Save current context" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Open desktop handoff in Codex" }));

    await waitFor(() => expect(mocks.continuation.mutateAsync).toHaveBeenCalledWith(
      expect.objectContaining({
      idempotency_key: expect.any(String),
      repo_path: "/workspace/daemonstate",
      source_provider: "codex",
      source_session_id: "current-session",
      target_provider: "codex",
      workspace_id: "workspace-1",
      }),
    ));
    expect(mocks.capture.mutate).not.toHaveBeenCalled();
  });

});

function latestDiscoveryResult(session = {}) {
  let resolvedSession = null;
  if (session !== null) {
    resolvedSession = {
      id: "codex:session-1",
      connector_type: "codex",
      session_id: "session-1",
      source_document_id: "source-1",
      title: "Harden checkpoint capture",
      preview: "Harden checkpoint capture",
      updated_at: "2026-07-21T10:00:00Z",
      cwd: "/workspace/daemonstate",
      revision_number: 1,
      live: true,
      compaction_checkpoints: [
        { id: "provider-compaction-1", window_id: 1 },
        { id: "provider-compaction-2", window_id: 2 },
      ],
      ...session,
    };
    if (!Object.prototype.hasOwnProperty.call(session, "latest_topic")) {
      resolvedSession.latest_topic = resolvedSession.title;
    }
    if (!Object.prototype.hasOwnProperty.call(session, "root_task_title")) {
      resolvedSession.root_task_title = resolvedSession.title;
    }
  }
  return {
    sync: {
      mode: "latest",
      discovered: resolvedSession ? 1 : 0,
    },
    session: resolvedSession,
  };
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
