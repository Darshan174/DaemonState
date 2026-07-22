import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ProjectMemory from "./ProjectMemory";

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
  checkpoint: { data: null, isLoading: false },
}));

vi.mock("./useProductWorkspace", () => ({
  useProductWorkspace: () => mocks.workspace,
}));

vi.mock("../context-map/api", () => ({
  useContextDigest: () => mocks.digest,
}));

vi.mock("../api/hooks", () => ({
  useLatestCheckpoint: () => mocks.checkpoint,
}));

beforeEach(() => {
  mocks.digest.data = {
    current_goal: { component_id: "goal-1", title: "Ship project memory" },
    recommended_actions: [],
    links: [],
    cards: [
      {
        id: "decision-1",
        title: "Use source-backed records",
        summary: "Keep evidence attached to every decision.",
        type: "decision",
        category: "decision",
        status: "active",
        temporal: "current",
        workspace_relevance: { status: "relevant" },
        evidence: { verification_status: "verified", excerpt: "Decision: keep evidence attached." },
        source_snapshot: { source_document_id: "source-1", source_type: "agent_session", revision_number: 2, freshness: "observed" },
        provenance: [{ source_label: "Codex session", source_type: "Agent Session" }],
      },
    ],
  };
  mocks.checkpoint.data = {
    created_at: "2026-07-22T10:00:00Z",
    sections: {
      goal: [], progress: [], decisions: [], failed_attempts: [], relevant_files: [], blockers: [], verification: [], exact_next_action: [],
    },
  };
});

describe("ProjectMemory", () => {
  it("shows the structured memory catalogue as inspectable cards", () => {
    render(<MemoryRouter><ProjectMemory /></MemoryRouter>);

    expect(screen.getByRole("heading", { name: "Project memory" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open Current goal" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open Decisions" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open Resolved blockers" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Open Decisions" }));
    const drawer = screen.getByRole("dialog", { name: "Decisions" });
    expect(within(drawer).getByText("Use source-backed records")).toBeInTheDocument();
    expect(within(drawer).getByText("Codex session")).toBeInTheDocument();
  });

  it("filters cards by area and search", () => {
    render(<MemoryRouter><ProjectMemory /></MemoryRouter>);

    fireEvent.click(screen.getByRole("button", { name: "Learning" }));
    expect(screen.getByRole("button", { name: "Open Lessons" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Open Current goal" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "All" }));
    fireEvent.change(screen.getByRole("searchbox", { name: "Search memory types" }), { target: { value: "milestone" } });
    expect(screen.getByRole("button", { name: "Open Milestones" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Open Decisions" })).not.toBeInTheDocument();
  });

  it("does not present a checkpoint task as the project goal", () => {
    mocks.digest.data = { ...mocks.digest.data, current_goal: null };
    mocks.checkpoint.data = {
      ...mocks.checkpoint.data,
      sections: {
        ...mocks.checkpoint.data.sections,
        goal: [{ id: "run-goal", statement: "Fix the checkpoint implementation", truth_state: "reported" }],
      },
    };
    render(<MemoryRouter><ProjectMemory /></MemoryRouter>);

    fireEvent.click(screen.getByRole("button", { name: "Open Current goal" }));
    expect(screen.getByText("No current project goal is explicitly selected. Session tasks and checkpoint instructions are kept out of this tracker.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Close memory details" }));

    fireEvent.click(screen.getByRole("button", { name: "Open Tasks" }));
    const drawer = screen.getByRole("dialog", { name: "Tasks" });
    expect(within(drawer).getByText("Fix the checkpoint implementation")).toBeInTheDocument();
    expect(within(drawer).getByText("Latest checkpoint task")).toBeInTheDocument();
  });
});
