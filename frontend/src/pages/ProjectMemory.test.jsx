import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ProjectMemory from "./ProjectMemory";


const SECTION_IDS = [
  "goal", "requirements", "decisions", "work", "blockers", "risks", "learnings",
  "deliveries", "unverified", "conflicts", "stale", "owners", "milestones",
  "resolved", "superseded", "dismissed", "revisions",
];

const decision = {
  id: "component:decision-1",
  section: "decisions",
  kind: "Decision",
  title: "Use source-backed records",
  summary: "Keep evidence attached to every decision.",
  status: "verified",
  verification: "verified",
  temporal: "current",
  origin: "component",
  component_id: "decision-1",
  source: {
    label: "Agent Session · codex:truth",
    source_type: "agent_session",
    document_id: "source-1",
    url: "https://example.test/session/1",
    revision_number: 2,
    freshness: "unknown",
  },
  evidence: {
    excerpt: "Decision: keep evidence attached.",
    evidence_span_id: "evidence-1",
    review_status: "verified",
    exact: true,
  },
  explanation: "Typed `decision` record with exact verified evidence.",
  allowed_actions: ["supersede", "dismiss"],
  occurred_at: "2026-07-22T10:00:00Z",
  occurrence_count: 1,
};

const unverifiedDecision = {
  ...decision,
  id: "component:decision-2",
  component_id: "decision-2",
  section: "unverified",
  title: "Review the context policy",
  status: "needs_review",
  verification: "needs_review",
  evidence: { ...decision.evidence, evidence_span_id: "evidence-2", review_status: "needs_review" },
  explanation: "Typed `decision` record awaiting human confirmation of its exact evidence.",
  allowed_actions: ["confirm", "supersede", "dismiss"],
};

function memoryData({ currentGoal = null, records = [decision, unverifiedDecision] } = {}) {
  const grouped = Object.fromEntries(SECTION_IDS.map((id) => [id, []]));
  for (const record of records) grouped[record.section].push(record);
  if (currentGoal) {
    grouped.goal.push({
      id: `goal:${currentGoal.id}`,
      section: "goal",
      kind: "Selected goal",
      title: currentGoal.title,
      summary: "Display-only workspace focus shown in Memory and Now.",
      status: "active",
      verification: "verified",
      temporal: "current",
      origin: "workspace_goal",
      source: { label: "User-selected workspace goal", source_type: "user_selected", freshness: "observed" },
      explanation: "Explicitly entered by a user and retained in workspace goal history.",
      allowed_actions: [],
      occurrence_count: 1,
    });
  }
  const sections = SECTION_IDS.map((id) => ({
    id,
    total: grouped[id].length,
    records: grouped[id],
    has_more: false,
  }));
  return {
    current_goal: currentGoal,
    totals: {
      active: grouped.goal.length + grouped.decisions.length,
      needs_review: grouped.unverified.length,
      people_and_dates: 0,
      history: 0,
      all: records.length + (currentGoal ? 1 : 0),
    },
    sections,
    scope: {},
  };
}

const mocks = vi.hoisted(() => ({
  workspace: {
    activeWorkspaceId: "workspace-1",
    activeWorkspace: { id: "workspace-1", name: "Context Engine" },
    workspacesQuery: { isLoading: false },
    workspaces: [{ id: "workspace-1", name: "Context Engine" }],
    selectedId: "workspace-1",
    setSelectedId: vi.fn(),
  },
  memory: { data: null, isLoading: false, isError: false, error: null },
  reviewMemory: { mutateAsync: vi.fn() },
  setGoal: { mutateAsync: vi.fn(), isPending: false },
  clearGoal: { mutateAsync: vi.fn(), isPending: false },
}));

vi.mock("./useProductWorkspace", () => ({
  useProductWorkspace: () => mocks.workspace,
}));

vi.mock("../context-map/api", () => ({
  useProjectMemory: () => mocks.memory,
  useReviewMemoryRecord: () => mocks.reviewMemory,
  useSetCurrentGoal: () => mocks.setGoal,
  useClearCurrentGoal: () => mocks.clearGoal,
}));

beforeEach(() => {
  mocks.reviewMemory.mutateAsync.mockReset().mockResolvedValue({ status: "verified" });
  mocks.setGoal.mutateAsync.mockReset().mockResolvedValue({ title: "New goal" });
  mocks.clearGoal.mutateAsync.mockReset().mockResolvedValue(null);
  mocks.memory.data = memoryData({
    currentGoal: {
      id: "goal-1",
      title: "Ship project memory",
      source_kind: "user_selected",
      can_clear: true,
    },
  });
  mocks.memory.isLoading = false;
  mocks.memory.isError = false;
});

describe("ProjectMemory", () => {
  it("shows typed memory sections and exact evidence", () => {
    render(<MemoryRouter><ProjectMemory /></MemoryRouter>);

    const heading = screen.getByRole("heading", { name: "Project memory" });
    expect(heading).toHaveClass("text-3xl", "font-black", "tracking-[-0.035em]", "sm:text-4xl");
    expect(screen.queryByText("Context Engine")).not.toBeInTheDocument();
    expect(screen.getByText(/project’s trusted knowledge base/i)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Ship project memory" })).toBeInTheDocument();
    expect(screen.getByText("Trusted current memory")).toBeInTheDocument();
    expect(screen.getByText("Needs human review")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open Current goal" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open Decisions" })).toHaveTextContent(/1\s*record/);

    fireEvent.click(screen.getByRole("button", { name: "Open Decisions" }));
    const drawer = screen.getByRole("dialog", { name: "Decisions" });
    expect(within(drawer).getByText("Use source-backed records")).toBeInTheDocument();
    expect(within(drawer).getByText("Keep evidence attached to every decision")).toBeInTheDocument();
    expect(within(drawer).getByText(/Exact source span/)).toBeInTheDocument();
    expect(within(drawer).getByText("Verified evidence")).toBeInTheDocument();
    expect(within(drawer).getByRole("link", { name: /Agent Session/ })).toHaveAttribute(
      "href",
      "https://example.test/session/1",
    );
  });

  it("switches between active, review, people, and history views", () => {
    render(<MemoryRouter><ProjectMemory /></MemoryRouter>);

    fireEvent.click(screen.getByRole("button", { name: "Needs review" }));
    expect(screen.getByRole("button", { name: "Needs review" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Open Unverified memory" })).toHaveTextContent(/1\s*record/);
    expect(screen.queryByRole("button", { name: "Open Decisions" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "People & dates" }));
    expect(screen.getByRole("button", { name: "Open Milestones" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "History" }));
    expect(screen.getByRole("button", { name: "Open Resolved blockers" })).toBeInTheDocument();
  });

  it("makes the review queue an explicit priority and exposes a labeled workspace search", () => {
    render(<MemoryRouter><ProjectMemory /></MemoryRouter>);

    expect(screen.getByRole("searchbox", { name: "Search this workspace" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Review 1 item" }));

    expect(screen.getByRole("button", { name: "Needs review" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("heading", { name: "Needs review" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open Unverified memory" })).toBeInTheDocument();
  });

  it("confirms only records whose API contract allows exact-evidence review", async () => {
    render(<MemoryRouter><ProjectMemory /></MemoryRouter>);

    fireEvent.click(screen.getByRole("button", { name: "Needs review" }));
    fireEvent.click(screen.getByRole("button", { name: "Open Unverified memory" }));
    const drawer = screen.getByRole("dialog", { name: "Unverified memory" });
    fireEvent.click(within(drawer).getByRole("button", { name: "Confirm exact evidence" }));

    await waitFor(() => expect(mocks.reviewMemory.mutateAsync).toHaveBeenCalledWith({
      componentId: "decision-2",
      action: "confirm",
    }));
  });

  it("explains the impact before superseding a current memory record", async () => {
    render(<MemoryRouter><ProjectMemory /></MemoryRouter>);

    fireEvent.click(screen.getByRole("button", { name: "Open Decisions" }));
    const drawer = screen.getByRole("dialog", { name: "Decisions" });
    fireEvent.click(within(drawer).getByRole("button", { name: "Supersede" }));

    expect(mocks.reviewMemory.mutateAsync).not.toHaveBeenCalled();
    expect(within(drawer).getByText(/moves the record out of current memory/i)).toBeInTheDocument();
    fireEvent.click(within(drawer).getByRole("button", { name: "Confirm supersede" }));

    await waitFor(() => expect(mocks.reviewMemory.mutateAsync).toHaveBeenCalledWith({
      componentId: "decision-1",
      action: "supersede",
    }));
  });

  it("requires explicit confirmation before dismissing an extracted record", async () => {
    render(<MemoryRouter><ProjectMemory /></MemoryRouter>);

    fireEvent.click(screen.getByRole("button", { name: "Open Decisions" }));
    const drawer = screen.getByRole("dialog", { name: "Decisions" });
    fireEvent.click(within(drawer).getByRole("button", { name: "Dismiss" }));

    expect(mocks.reviewMemory.mutateAsync).not.toHaveBeenCalled();
    expect(within(drawer).getByText(/not useful or correct/i)).toBeInTheDocument();
    fireEvent.click(within(drawer).getByRole("button", { name: "Confirm dismiss" }));

    await waitFor(() => expect(mocks.reviewMemory.mutateAsync).toHaveBeenCalledWith({
      componentId: "decision-1",
      action: "dismiss",
    }));
  });

  it.each([
    ["review", "stale", "Stale context", "stale", "verified", "Stale — review required"],
    ["review", "conflicts", "Conflicts", "conflict", "observed", "Conflict flagged"],
    ["history", "superseded", "Superseded memory", "superseded", "verified", "Superseded"],
    ["history", "dismissed", "Dismissed memory", "dismissed", "verified", "Dismissed"],
    ["history", "resolved", "Resolved blockers", "resolved", "verified", "Resolved"],
    ["history", "revisions", "Source revisions", "historical", "observed", "Historical record"],
  ])(
    "prioritizes governing %s state over the evidence verification flag",
    (view, section, typeTitle, status, verification, expectedLabel) => {
      mocks.memory.data = memoryData({
        records: [{
          ...decision,
          id: `component:${section}`,
          component_id: section,
          section,
          status,
          verification,
        }],
      });
      render(<MemoryRouter><ProjectMemory /></MemoryRouter>);

      fireEvent.click(screen.getByRole("button", { name: view === "review" ? "Needs review" : "History" }));
      fireEvent.click(screen.getByRole("button", { name: `Open ${typeTitle}` }));

      expect(within(screen.getByRole("dialog", { name: typeTitle })).getByText(expectedLabel)).toBeInTheDocument();
    },
  );

  it("focuses the memory drawer and returns focus to its trigger when closed", async () => {
    render(<MemoryRouter><ProjectMemory /></MemoryRouter>);

    const trigger = screen.getByRole("button", { name: "Open Decisions" });
    trigger.focus();
    fireEvent.click(trigger);

    expect(screen.getByRole("button", { name: "Close memory details" })).toHaveFocus();
    fireEvent.keyDown(window, { key: "Escape" });

    await waitFor(() => expect(trigger).toHaveFocus());
    expect(screen.queryByRole("dialog", { name: "Decisions" })).not.toBeInTheDocument();
  });

  it("sets and clears an explicit current goal while explaining its real effect", async () => {
    mocks.memory.data = memoryData();
    render(<MemoryRouter><ProjectMemory /></MemoryRouter>);

    fireEvent.click(screen.getByRole("button", { name: "Open Current goal" }));
    expect(within(screen.getByRole("dialog", { name: "Current goal" })).getByText(/does not start work, edit files/i)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Set project focus"), {
      target: { value: "Make project memory trustworthy" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Set goal" }));

    await waitFor(() => expect(mocks.setGoal.mutateAsync).toHaveBeenCalledWith({
      title: "Make project memory trustworthy",
      source_kind: "user_selected",
    }));

    mocks.memory.data = memoryData({
      currentGoal: { id: "goal-1", title: "Ship memory", source_kind: "user_selected", can_clear: true },
    });
  });

  it("explains where the goal is removed before clearing it", async () => {
    render(<MemoryRouter><ProjectMemory /></MemoryRouter>);

    fireEvent.click(screen.getByRole("button", { name: "Open Current goal" }));
    fireEvent.click(screen.getByRole("button", { name: "Clear goal" }));

    expect(mocks.clearGoal.mutateAsync).not.toHaveBeenCalled();
    expect(screen.getByText(/removes the focus from Memory and Now/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Clear current goal" }));

    await waitFor(() => expect(mocks.clearGoal.mutateAsync).toHaveBeenCalledTimes(1));
  });

  it("fails closed when the Memory API is unavailable", () => {
    mocks.memory.isError = true;
    mocks.memory.data = null;
    render(<MemoryRouter><ProjectMemory /></MemoryRouter>);

    expect(screen.getByRole("alert")).toHaveTextContent(
      "No cached or inferred records are being shown",
    );
    expect(screen.getByRole("button", { name: "Open Decisions" })).toHaveTextContent(/0\s*records/);
  });
});
