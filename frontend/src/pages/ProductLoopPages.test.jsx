import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import NowPage from "./NowPage";
import PreparePage from "./PreparePage";
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
  digest: { data: null, isLoading: false, isError: false },
  prepare: { data: null, isPending: false, isError: false, mutateAsync: vi.fn() },
  outcomes: { data: null, isLoading: false, isError: false },
  setGoal: { isPending: false, error: null, mutateAsync: vi.fn() },
  clearGoal: { isPending: false, error: null, mutateAsync: vi.fn() },
  clearNowSession: { isPending: false, isError: false, mutate: vi.fn() },
  apiPost: vi.fn(),
}));

vi.mock("./useProductWorkspace", () => ({
  useProductWorkspace: () => mocks.workspace,
}));

vi.mock("../context-map/api", () => ({
  useContextDigest: () => mocks.digest,
  useLinkedAISessionRefresh: () => ({ data: null }),
  useClearNowSession: () => mocks.clearNowSession,
  useSetCurrentGoal: () => mocks.setGoal,
  useClearCurrentGoal: () => mocks.clearGoal,
  usePrepareContext: () => mocks.prepare,
  useRunOutcomes: () => mocks.outcomes,
}));

vi.mock("../api/client", () => ({
  api: { post: mocks.apiPost },
}));

beforeEach(() => {
  mocks.workspace.activeWorkspace = { id: "workspace-1", name: "Context Engine", kind: "project" };
  mocks.digest.data = null;
  mocks.digest.isLoading = false;
  mocks.digest.isError = false;
  mocks.prepare.data = null;
  mocks.prepare.isPending = false;
  mocks.prepare.isError = false;
  mocks.prepare.mutateAsync.mockReset().mockResolvedValue({});
  mocks.outcomes.data = null;
  mocks.outcomes.isLoading = false;
  mocks.outcomes.isError = false;
  mocks.setGoal.isPending = false;
  mocks.setGoal.error = null;
  mocks.setGoal.mutateAsync.mockReset().mockResolvedValue({});
  mocks.clearGoal.isPending = false;
  mocks.clearGoal.error = null;
  mocks.clearGoal.mutateAsync.mockReset().mockResolvedValue(null);
  mocks.clearNowSession.isPending = false;
  mocks.clearNowSession.isError = false;
  mocks.clearNowSession.mutate.mockReset();
  mocks.apiPost.mockReset().mockResolvedValue({ message: "Opened in Codex." });
});

describe("product loop pages", () => {
  it("turns observed run evidence into a concise current-work surface", () => {
    mocks.digest.data = {
      generated_at: "2026-07-17T10:00:00Z",
      scope: { included_source_count: 7, project_paths: ["/workspace/context-engine"] },
      current_goal: {
        component_id: "task-1",
        title: "Harden the model adapter",
        source_kind: "user_selected",
        selected_by: "local",
        selected_at: "2026-07-17T09:00:00Z",
        can_clear: true,
      },
      oversight: {
        current_focus: { component_id: "task-1", title: "Harden the model adapter" },
        latest_outcome: { summary: "Compiler tests passed.", observed_at: "2026-07-17T09:30:00Z" },
      },
      activity: {
        primary: {
          id: "run:run-1",
          kind: "agent_run",
          state: "completed",
          evidence_level: "observed_run",
          request: "Harden the model adapter",
          latest_update: "Added capability-aware rendering and focused coverage.",
          rationale: "The adapter needs conservative defaults because provider probing is not connected.",
          tool: "codex",
          model: "gpt-5",
          branch: "codex/model-adapter",
          updated_at: "2026-07-17T09:30:00Z",
          changed_files: ["app/model_adapter.py", "tests/test_model_adapter.py"],
          verification: { observed: 2, passed: 2, failed: 0 },
          outcome: { summary: "Compiler tests passed.", observed_at: "2026-07-17T09:30:00Z" },
        },
      },
      cards: [
        { id: "component:task-1", category: "task", title: "Harden the model adapter", summary: "Implement capability-aware rendering.", next_action: "Add provider capability probing.", focus_eligible: true, attention_required: false },
        { id: "risk-1", category: "risk", type: "risk", status: "active", title: "Model identity is self-reported", summary: "Provider identity is not independently verified.", attention_score: 95, attention_required: true, workspace_relevance: { status: "relevant" } },
        { id: "component:issue-2", category: "issue", status: "needs_review", title: "Issue #2: Add hybrid retrieval", summary: "Backlog work.", attention_score: 60, focus_eligible: true, attention_required: false },
      ],
    };

    render(<MemoryRouter><NowPage /></MemoryRouter>);

    expect(screen.getByRole("heading", { name: "Harden the model adapter" })).toBeInTheDocument();
    expect(screen.getByText("Added capability-aware rendering and focused coverage")).toBeInTheDocument();
    expect(screen.getByText("2 files changed")).toBeInTheDocument();
    expect(screen.getAllByText("2/2 passed")).toHaveLength(2);
    expect(screen.getByText("Compiler tests passed")).toBeInTheDocument();
    expect(screen.getByText(/Model identity is self\s*-\s*reported/)).toBeInTheDocument();
    expect(screen.getByText("1 current")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Model identity is self-reported/ })).toHaveAttribute("href", "/app/explain?card=risk-1");
    expect(screen.queryByText(/Issue 2: Add hybrid retrieval/)).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Prepare this work" })).toHaveAttribute("href", "/app/prepare?objective=Harden%20the%20model%20adapter");
    expect(screen.getByRole("link", { name: "Project overview" })).toHaveAttribute("href", "/app/explain");
  });

  it("does not present backlog as current work without observed activity", () => {
    mocks.digest.data = {
      generated_at: "2026-07-17T10:00:00Z",
      scope: { included_source_count: 2, project_paths: ["/workspace/context-engine"] },
      current_goal: null,
      oversight: {},
      activity: { state: "empty", primary: null, recent_sessions: [] },
      cards: [{
        id: "component:issue-2",
        category: "issue",
        status: "needs_review",
        title: "Issue #2: Add hybrid retrieval",
        summary: "Backlog work.",
        attention_score: 60,
        focus_eligible: true,
        attention_required: false,
        source_snapshot: { source_document_id: "source-2" },
      }],
    };

    render(<MemoryRouter><NowPage /></MemoryRouter>);

    expect(screen.getByRole("heading", { name: "No agent work observed yet." })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Choose from Session Library" })).toHaveAttribute("href", "/app/library");
    expect(screen.getByText("No current items")).toBeInTheDocument();
    expect(screen.queryByText(/Issue 2: Add hybrid retrieval/)).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Prepare work/ })).toHaveAttribute("href", "/app/prepare");
    expect(mocks.setGoal.mutateAsync).not.toHaveBeenCalled();
  });

  it("defaults Now to the latest topic and offers direct desktop continuation", async () => {
    mocks.digest.data = {
      generated_at: "2026-07-17T10:00:00Z",
      scope: { included_source_count: 1, project_paths: ["/workspace/context-engine"] },
      current_goal: null,
      oversight: {},
      activity: {
        primary: {
          id: "session:source-1",
          kind: "agent_session",
          state: "active",
          live: true,
          evidence_level: "session_reported",
          selected_for_now: false,
          refreshable: true,
          project_match: { status: "relevant", automatic: true },
          latest_topic: "Add regression coverage for the OAuth callback",
          session_title: "Authentication redirect investigation",
          title: "Add regression coverage for the OAuth callback",
          latest_update: "The callback regression now has coverage.",
          rationale: "The callback regression now has coverage.",
          result_summary: {
            text: "Implemented OAuth callback regression coverage.",
            kind: "completion",
            provenance: "agent_reported",
            reported_at: "2026-07-17T09:30:00Z",
          },
          updated_at: "2026-07-17T09:30:00Z",
          changed_files: [],
          verification: { observed: 0, passed: 0, failed: 0 },
          outcome: null,
          source_card_id: "component:session-1",
          source_document_id: "source-1",
          tool: "codex",
          attention_items: [{
            id: "session-attention:source-1:0",
            kind: "user_correction",
            title: "The redirect is still broken in the app",
            summary: "The user reported that the previous result did not match the visible app.",
            attention_score: 90,
            temporal_status: "previous",
            source_document_id: "source-1",
          }],
        },
        recent_sessions: [{
          id: "session:source-2",
          kind: "agent_session",
          latest_topic: "Tighten session title cleanup",
          session_title: "Session library polish",
          source_document_id: "source-2",
          tool: "claude_code",
          forked_from: { session_id: "parent-session", title: "Session library foundation" },
          updated_at: "2026-07-17T08:30:00Z",
        }],
      },
      cards: [{
        id: "component:session-1",
        category: "agent_session",
        title: "Authentication redirect investigation",
        workspace_relevance: { status: "unknown" },
        source_snapshot: { source_document_id: "source-1" },
      }],
    };

    render(<MemoryRouter><NowPage /></MemoryRouter>);

    expect(screen.getByRole("heading", { name: "Add regression coverage for the OAuth callback" })).toBeInTheDocument();
    expect(screen.getByText("Latest topic")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "From session: Authentication redirect investigation" })).toHaveAttribute("href", "/app/library?source=source-1&topic=Add+regression+coverage+for+the+OAuth+callback");
    expect(screen.getByRole("link", { name: "Choose topic" })).toHaveAttribute("href", "/app/library?source=source-1&topic=Add+regression+coverage+for+the+OAuth+callback");
    expect(screen.getByText("Live session")).toBeInTheDocument();
    expect(screen.getByText(/automatically matched to this project/i)).toBeInTheDocument();
    expect(screen.queryByText(/AI sessions are available to choose from/i)).not.toBeInTheDocument();
    expect(screen.getByText("Agent-reported result")).toBeInTheDocument();
    expect(screen.getByText("Implemented OAuth callback regression coverage")).toBeInTheDocument();
    expect(screen.queryByText("Stated reason")).not.toBeInTheDocument();
    expect(screen.getByText("The callback regression now has coverage")).toHaveClass("line-clamp-3");
    expect(screen.getByText("Session-only")).toBeInTheDocument();
    expect(screen.getByText("No session issues")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "View session library" })).toHaveAttribute("href", "/app/library");
    expect(screen.getByRole("link", { name: /Tighten session title cleanup/ })).toHaveAttribute("href", "/app/library?source=source-2&topic=Tighten+session+title+cleanup");
    expect(screen.getByLabelText("Continued in a new task")).toBeInTheDocument();
    expect(screen.getByText(/Continued from Session library foundation/)).toBeInTheDocument();
    expect(screen.queryByText("Previous user correction")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /The redirect is still broken in the app/ })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Continue in Codex" }));
    await waitFor(() => expect(mocks.apiPost).toHaveBeenCalledWith("/session-library/open", {
      workspace_id: "workspace-1",
      source_document_id: "source-1",
      topic: "Add regression coverage for the OAuth callback",
    }));
  });

  it("shows previous corrections only when that exact session is selected", () => {
    mocks.digest.data = {
      generated_at: "2026-07-17T10:00:00Z",
      scope: { included_source_count: 2, project_paths: ["/workspace/context-engine"] },
      current_goal: null,
      oversight: {},
      activity: {
        primary: {
          id: "session:source-selected",
          kind: "agent_session",
          state: "recent",
          evidence_level: "session_reported",
          selected_for_now: true,
          selected_topic: "Review the banner fix",
          session_title: "Banner correction session",
          source_document_id: "source-selected",
          updated_at: "2026-07-17T09:30:00Z",
          changed_files: [],
          verification: { observed: 0, passed: 0, failed: 0 },
          attention_items: [{
            id: "session-attention:source-selected:0",
            kind: "user_correction",
            title: "The banner is still displayed",
            summary: "The banner remained visible after the claimed removal.",
            attention_score: 90,
            temporal_status: "previous",
            source_document_id: "source-selected",
          }, {
            id: "session-attention:source-other:0",
            kind: "user_correction",
            title: "A correction from another session",
            summary: "This must not leak into the selected session.",
            attention_score: 95,
            temporal_status: "previous",
            source_document_id: "source-other",
          }],
        },
      },
      cards: [],
    };

    render(<MemoryRouter><NowPage /></MemoryRouter>);

    expect(screen.getByText("No session issues · 1 previous")).toBeInTheDocument();
    expect(screen.getByText("The banner is still displayed")).toBeInTheDocument();
    expect(screen.queryByText("A correction from another session")).not.toBeInTheDocument();
  });

  it("marks an old selected session as historical and lets the user return to latest activity", () => {
    mocks.digest.data = {
      generated_at: "2026-07-17T10:00:00Z",
      scope: { included_source_count: 2, project_paths: ["/workspace/context-engine"] },
      current_goal: null,
      oversight: {},
      activity: {
        primary: {
          id: "session:source-1",
          kind: "agent_session",
          state: "recent",
          evidence_level: "session_reported",
          selected_for_now: true,
          selected_topic: "Fix the authentication redirect loop",
          session_title: "Authentication redirect investigation",
          request: "Fix the authentication redirect loop",
          latest_update: "Updated the callback handler and added tests.",
          result_summary: {
            text: "Updated the callback handler and added tests.",
            kind: "completion",
            provenance: "agent_reported",
            reported_at: "2026-07-17T09:30:00Z",
          },
          tool: "claude_code",
          updated_at: "2026-07-17T09:30:00Z",
          changed_files: [],
          verification: { observed: 0, passed: 0, failed: 0 },
          outcome: null,
          source_card_id: "component:session-1",
          source_document_id: "source-1",
        },
      },
      cards: [],
    };

    render(<MemoryRouter><NowPage /></MemoryRouter>);

    expect(screen.getByRole("heading", { name: "Fix the authentication redirect loop" })).toBeInTheDocument();
    expect(screen.getByText("Selected topic")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "From session: Authentication redirect investigation" })).toHaveAttribute("href", "/app/library?source=source-1&topic=Fix+the+authentication+redirect+loop");
    expect(screen.getByRole("link", { name: "Choose topic" })).toHaveAttribute("href", "/app/library?source=source-1&topic=Fix+the+authentication+redirect+loop");
    expect(screen.getAllByText("Historical selection")).toHaveLength(2);
    expect(screen.getByText(/This remains pinned for reference and is not live activity/i)).toBeInTheDocument();
    expect(screen.getByText(/agent-reported until repository evidence confirms it/i)).toBeInTheDocument();
    expect(screen.getByText("Agent-reported result")).toBeInTheDocument();
    expect(screen.getByText("Updated the callback handler and added tests")).toBeInTheDocument();
    expect(screen.getByText("Session-only")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Review session evidence/ })).toHaveAttribute("href", "/app/library?source=source-1&topic=Fix+the+authentication+redirect+loop");
    expect(screen.getByRole("link", { name: /Review result evidence/ })).toHaveAttribute("href", "/app/library?source=source-1&topic=Fix+the+authentication+redirect+loop");
    fireEvent.click(screen.getByRole("button", { name: "Return to latest activity" }));
    expect(mocks.clearNowSession.mutate).toHaveBeenCalledTimes(1);
  });

  it("labels a sample workspace clearly and routes the user toward a real project", () => {
    mocks.workspace.activeWorkspace = { id: "workspace-1", name: "Context Engine Demo", kind: "demo" };
    mocks.digest.data = {
      scope: { project_paths: [] },
      activity: { state: "empty", primary: null, recent_sessions: [] },
      cards: [],
      current_goal: null,
      oversight: {},
    };

    render(<MemoryRouter><NowPage /></MemoryRouter>);

    expect(screen.getByText("Sample workspace")).toBeInTheDocument();
    expect(screen.getByText(/Your real project activity stays separate/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Choose project" })).toHaveAttribute("href", "/app/workspaces");
  });

  it("shows compiler selection, exclusions, model profile, and the exact brief", async () => {
    mocks.digest.data = { scope: { project_paths: ["/workspace/context-engine"] }, cards: [] };
    mocks.prepare.data = {
      markdown: "# Agent brief\n\nUse source-backed evidence.",
      health_score: 92,
      manifest: {
        target_model: { name: "older-coder", profile: "small_coder_model" },
        rendering: { estimated_tokens: 740 },
        token_accounting: { selected_item_tokens: 700 },
      },
      selected_context: [{ id: "selected-1", title: "Authentication decision", item_type: "decision", inclusion_reason: "direct_objective_match", token_cost: 180 }],
      excluded_context: [{ id: "excluded-1", reason: "lower_ranked" }],
    };
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(globalThis.navigator, "clipboard", { configurable: true, value: { writeText } });

    render(<MemoryRouter initialEntries={["/app/prepare?objective=Fix%20the%20redirect"]}><PreparePage /></MemoryRouter>);

    expect(screen.getByLabelText("Task")).toHaveValue("Fix the redirect");
    expect(screen.getByText("older-coder")).toBeInTheDocument();
    expect(screen.getByText("Concise small-model profile inferred from label · 740 estimated tokens")).toBeInTheDocument();
    expect(screen.getByText("Authentication decision")).toBeInTheDocument();
    expect(screen.getByText(/Why 1 items were left out/)).toBeInTheDocument();
    expect(screen.getByText("Brief compiled")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Copy agent brief" }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith("# Agent brief\n\nUse source-backed evidence."));

    fireEvent.click(screen.getByRole("button", { name: "Compile context" }));
    await waitFor(() => expect(mocks.prepare.mutateAsync).toHaveBeenCalledWith(expect.objectContaining({
      objective: "Fix the redirect",
      target_model: undefined,
      token_budget: 4000,
      mode: "task",
    })));
  });

  it("keeps an explicit compaction checkpoint attached to the agent handoff", async () => {
    mocks.digest.data = { scope: { project_paths: ["/workspace/context-engine"] }, cards: [] };
    mocks.prepare.data = {
      markdown: "# Agent brief\n\n## Restored Session Checkpoint",
      health_score: 88,
      manifest: {
        target_model: { name: "default", profile: "general_coder_model" },
        rendering: { estimated_tokens: 900 },
        token_accounting: { selected_item_tokens: 850 },
      },
      selected_context: [{
        id: "session_checkpoint:source-1:checkpoint-1",
        title: "Restored pre-compaction context",
        item_type: "session_checkpoint",
        inclusion_reason: "explicit_pre_compaction_restore",
        token_cost: 250,
      }],
      excluded_context: [],
    };

    render(
      <MemoryRouter initialEntries={[
        "/app/prepare?objective=Finish%20the%20handoff&checkpoint_source=source-1&checkpoint=checkpoint-1",
      ]}>
        <PreparePage />
      </MemoryRouter>,
    );

    expect(screen.getByText("Compaction checkpoint attached")).toBeInTheDocument();
    expect(screen.getByText(/Pre-compaction context included/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Compile context" }));
    await waitFor(() => expect(mocks.prepare.mutateAsync).toHaveBeenCalledWith(expect.objectContaining({
      objective: "Finish the handoff",
      checkpoint_source_document_id: "source-1",
      checkpoint_id: "checkpoint-1",
    })));

    fireEvent.click(screen.getByRole("button", { name: "Remove restored checkpoint" }));
    expect(screen.queryByText("Compaction checkpoint attached")).not.toBeInTheDocument();
  });

  it("keeps observed runs separate from an honest, non-causal comparison", () => {
    mocks.outcomes.data = {
      measurement_note: "Model names are recorded labels, not independently verified provider identities.",
      runs: [{
        run_id: "run-1",
        model: "older-coder",
        model_profile: "small_coder_model",
        objective: "Fix the redirect",
        tool: "codex",
        status: "complete",
        completed: true,
        verified_success: true,
        failed_verification: false,
        unresolved_blocker: false,
        duration_seconds: 83,
        started_at: "2026-07-17T10:00:00Z",
        changed_files: ["frontend/src/App.jsx"],
        verification: { observed: 2, passed: 2, failed: 0 },
      }],
      groups: [{
        model: "older-coder",
        model_profile: "small_coder_model",
        observed_runs: 1,
        verified_successful_runs: 1,
        verified_success_rate: 1,
        failed_verification_runs: 0,
        unresolved_blocker_runs: 0,
      }],
    };

    render(<MemoryRouter><RunsPage /></MemoryRouter>);

    expect(screen.getByRole("heading", { name: "Fix the redirect" })).toBeInTheDocument();
    expect(screen.getByText("2/2")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Compare/ }));
    expect(screen.getByRole("heading", { name: "A paired baseline is still missing" })).toBeInTheDocument();
    expect(screen.getByText("100%")).toBeInTheDocument();
    expect(screen.getByText(/not independently verified provider identities/)).toBeInTheDocument();
  });
});
