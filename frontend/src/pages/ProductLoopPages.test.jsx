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
}));

vi.mock("./useProductWorkspace", () => ({
  useProductWorkspace: () => mocks.workspace,
}));

vi.mock("../context-map/api", () => ({
  useContextDigest: () => mocks.digest,
  usePrepareContext: () => mocks.prepare,
  useRunOutcomes: () => mocks.outcomes,
}));

beforeEach(() => {
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
});

describe("product loop pages", () => {
  it("turns the digest into a concise current-state and next-action surface", () => {
    mocks.digest.data = {
      generated_at: "2026-07-17T10:00:00Z",
      scope: { included_source_count: 7, project_paths: ["/workspace/context-engine"] },
      oversight: {
        current_focus: { component_id: "task-1", title: "Harden the model adapter" },
        latest_outcome: { summary: "Compiler tests passed.", observed_at: "2026-07-17T09:30:00Z" },
      },
      cards: [
        { id: "component:task-1", category: "task", title: "Harden the model adapter", summary: "Implement capability-aware rendering.", next_action: "Add provider capability probing." },
        { id: "risk-1", category: "risk", status: "active", title: "Model identity is self-reported", summary: "Provider identity is not independently verified.", attention_score: 95 },
      ],
    };

    render(<MemoryRouter><NowPage /></MemoryRouter>);

    expect(screen.getByRole("heading", { name: "Harden the model adapter" })).toBeInTheDocument();
    expect(screen.getByText(/Model identity is self\s*-\s*reported/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Prepare task/ })).toHaveAttribute("href", "/app/prepare?objective=Harden%20the%20model%20adapter");
    expect(screen.getByRole("link", { name: "Explain project" })).toHaveAttribute("href", "/app/explain");
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
