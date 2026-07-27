import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ProjectMemory from "./ProjectMemory";


const SECTION_IDS = [
  "goal", "requirements", "decisions", "work", "blockers", "risks", "learnings",
  "deliveries", "unverified", "conflicts", "stale", "owners", "milestones",
  "resolved", "completed", "superseded", "dismissed", "revisions",
];

const decision = {
  id: "component:decision-1",
  section: "decisions",
  kind: "Decision",
  title: "Use source-backed records",
  summary: "Keep evidence attached to every decision.",
  status: "active",
  verification: "verified",
  semantic_section: "decisions",
  temporal: "current",
  origin: "component",
  component_id: "decision-1",
  source_group: "sessions",
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
  relevance: "Explicitly matched the current workspace agenda.",
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
  relevance: "Backed by the same source as the current agenda.",
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
      summary: "Explicit workspace focus used to scope Current Memory.",
      status: "active",
      verification: "verified",
      temporal: "current",
      origin: "workspace_goal",
      source_group: "documents",
      source: { label: "User-selected workspace goal", source_type: "user_selected", freshness: "observed" },
      relevance: "This is the selected workspace agenda.",
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
  const kinds = records.reduce((counts, record) => ({
    ...counts,
    [record.kind]: (counts[record.kind] || 0) + 1,
  }), {});
  const kindsBySection = records.reduce((sections, record) => ({
    ...sections,
    [record.section]: {
      ...(sections[record.section] || {}),
      [record.kind]: ((sections[record.section] || {})[record.kind] || 0) + 1,
    },
  }), {});
  const reviewSemanticSections = records
    .filter((record) => ["unverified", "conflicts"].includes(record.section))
    .reduce((counts, record) => ({
      ...counts,
      [record.semantic_section]: (counts[record.semantic_section] || 0) + 1,
    }), {});
  const reviewableSemanticSections = records
    .filter((record) => (
      record.section === "unverified"
      && record.evidence?.exact
      && record.allowed_actions?.includes("confirm")
    ))
    .reduce((counts, record) => ({
      ...counts,
      [record.semantic_section]: (counts[record.semantic_section] || 0) + 1,
    }), {});
  const staleSemanticSections = records
    .filter((record) => record.section === "stale")
    .reduce((counts, record) => ({
      ...counts,
      [record.semantic_section]: (counts[record.semantic_section] || 0) + 1,
    }), {});
  const activeCount = ["requirements", "decisions", "work", "blockers", "risks", "learnings", "deliveries"]
    .reduce((total, id) => total + grouped[id].length, 0);
  const reviewCount = grouped.unverified.length + grouped.conflicts.length;
  const readyCount = records.filter((record) => (
    record.section === "unverified"
    && record.evidence?.exact
    && record.allowed_actions?.includes("confirm")
  )).length;
  return {
    current_goal: currentGoal,
    agenda: currentGoal ? {
      kind: "current_goal",
      id: currentGoal.id,
      title: currentGoal.title,
      match_mode: "text_match",
    } : null,
    totals: {
      active: activeCount,
      needs_review: reviewCount,
      ready_to_review: readyCount,
      conflicts: grouped.conflicts.length,
      needs_refresh: grouped.stale.length,
      people_and_dates: grouped.owners.length + grouped.milestones.length,
      history: grouped.resolved.length
        + grouped.completed.length
        + grouped.superseded.length
        + grouped.dismissed.length
        + grouped.revisions.length,
      reported_activity: records.filter((record) => record.status === "reported").length,
      source_revisions: grouped.revisions.length,
      attention: reviewCount + grouped.stale.length,
      all: records.length + (currentGoal ? 1 : 0),
    },
    filters: {
      requested_scope: "agenda",
      effective_scope: currentGoal ? "agenda_match" : "workspace",
      source_group: "all",
      verification: "all",
      temporal: "all",
      kind: null,
    },
    facets: {
      kinds,
      kinds_by_section: kindsBySection,
      review_semantic_sections: reviewSemanticSections,
      reviewable_semantic_sections: reviewableSemanticSections,
      stale_semantic_sections: staleSemanticSections,
    },
    matches: records.length + (currentGoal ? 1 : 0),
    sections,
    scope: {
      effective_mode: currentGoal ? "agenda_match" : "workspace",
      excluded_unknown_session_components: 0,
      excluded_irrelevant_session_components: 0,
      excluded_unconfirmable_agent_components: 0,
      collapsed_duplicate_current_claims: 0,
      excluded_untrusted_relationships: 0,
    },
  };
}

const mocks = vi.hoisted(() => ({
  workspace: {
    activeWorkspaceId: "workspace-1",
    activeWorkspace: { id: "workspace-1", name: "DaemonState" },
    workspacesQuery: { isLoading: false },
    workspaces: [{ id: "workspace-1", name: "DaemonState" }],
    selectedId: "workspace-1",
    setSelectedId: vi.fn(),
  },
  memory: { data: null, isLoading: false, isError: false, error: null },
  memoryHook: vi.fn(),
  reviewMemory: { mutateAsync: vi.fn() },
  setGoal: { mutateAsync: vi.fn(), isPending: false },
  clearGoal: { mutateAsync: vi.fn(), isPending: false },
}));

vi.mock("./useProductWorkspace", () => ({
  useProductWorkspace: () => mocks.workspace,
}));

vi.mock("../context-map/api", () => ({
  useProjectMemory: (...args) => mocks.memoryHook(...args),
  useReviewMemoryRecord: () => mocks.reviewMemory,
  useSetCurrentGoal: () => mocks.setGoal,
  useClearCurrentGoal: () => mocks.clearGoal,
}));

function renderMemory(initialEntry = "/memory") {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <ProjectMemory />
    </MemoryRouter>,
  );
}

function latestMemoryOptions() {
  return mocks.memoryHook.mock.calls.at(-1)?.[1];
}

beforeEach(() => {
  mocks.reviewMemory.mutateAsync.mockReset().mockResolvedValue({ status: "verified" });
  mocks.setGoal.mutateAsync.mockReset().mockResolvedValue({ title: "New goal" });
  mocks.clearGoal.mutateAsync.mockReset().mockResolvedValue(null);
  mocks.memoryHook.mockReset().mockImplementation(() => mocks.memory);
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
  it("shows the workspace agenda, scoped categories, and exact source evidence", async () => {
    renderMemory();

    expect(screen.getByRole("heading", { name: "Project memory" })).toBeInTheDocument();
    expect(screen.getByText("DaemonState")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Ship project memory" })).toBeInTheDocument();
    expect(screen.getByText(/transparent relevance match/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Current agenda/ })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: /All DaemonState/ })).toHaveAttribute("aria-pressed", "false");

    expect(screen.getByRole("button", { name: "Overview" })).toHaveAttribute("aria-pressed", "true");
    const decisions = screen.getByRole("heading", { name: "Decisions" }).closest("article");
    expect(decisions).toHaveTextContent(/Current\s*1/);
    expect(decisions).toHaveTextContent(/Candidates\s*1/);
    fireEvent.click(within(decisions).getByRole("button", { name: "View current" }));
    await waitFor(() => expect(latestMemoryOptions()).toMatchObject({
      semanticSection: "decisions",
    }));

    expect(screen.getByText("Why this is shown")).toBeInTheDocument();
    expect(screen.getByText("Explicitly matched the current workspace agenda.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", {
      name: "Inspect evidence for Use source-backed records",
    }));

    const drawer = screen.getByRole("dialog", { name: "Decisions" });
    expect(within(drawer).getByText("Use source-backed records")).toBeInTheDocument();
    expect(within(drawer).getByText("Keep evidence attached to every decision")).toBeInTheDocument();
    expect(within(drawer).getByText(/Exact source span/)).toBeInTheDocument();
    expect(within(drawer).getAllByText("Verified evidence")).not.toHaveLength(0);
    expect(within(drawer).getByRole("link", { name: /Agent Session/ })).toHaveAttribute(
      "href",
      "https://example.test/session/1",
    );
  });

  it("defaults to a useful overview when current memory is empty", () => {
    mocks.memory.data = memoryData({ records: [unverifiedDecision] });

    renderMemory();

    expect(screen.getByRole("button", { name: "Overview" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("heading", {
      name: "Your memory isn’t empty — it needs your judgment",
    })).toBeInTheDocument();
    expect(screen.getByText(/none has been accepted as current project truth/i)).toBeInTheDocument();
    const decisions = screen.getByRole("heading", { name: "Decisions" }).closest("article");
    expect(decisions).toHaveTextContent(/Current\s*0/);
    expect(decisions).toHaveTextContent(/Candidates\s*1/);
    expect(within(decisions).getByRole("button", { name: "Review 1" })).toBeInTheDocument();
    const requirements = screen.getByRole("heading", {
      name: "Requirements & constraints",
    }).closest("article");
    expect(requirements).toHaveTextContent("No source-backed records yet");
    expect(requirements).not.toHaveTextContent(/Current\s*0/);
    expect(screen.queryByText("0 records")).not.toBeInTheDocument();
  });

  it("does not call current memory ready while conflicts remain", () => {
    mocks.memory.data = memoryData({
      records: [
        decision,
        {
          ...unverifiedDecision,
          id: "component:conflict-readiness",
          component_id: "conflict-readiness",
          section: "conflicts",
          status: "conflict",
          allowed_actions: ["supersede", "dismiss"],
        },
      ],
    });

    renderMemory();

    expect(screen.queryByRole("heading", {
      name: "Current memory is ready to reuse",
    })).not.toBeInTheDocument();
    expect(screen.getByRole("heading", {
      name: "Keep reusable project truth small and current",
    })).toBeInTheDocument();
    expect(screen.getByText("Conflicts").closest("div")).toHaveTextContent("1");
  });

  it("opens a semantic review queue from a category candidate action", async () => {
    mocks.memory.data = memoryData({ records: [unverifiedDecision] });
    renderMemory();

    const decisions = screen.getByRole("heading", { name: "Decisions" }).closest("article");
    fireEvent.click(within(decisions).getByRole("button", { name: "Review 1" }));

    await waitFor(() => expect(latestMemoryOptions()).toMatchObject({
      semanticSection: "decisions",
    }));
    expect(screen.getByRole("button", { name: "Review queue" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("heading", { name: "Review decisions" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add to current memory" })).toBeInTheDocument();
  });

  it("skips a candidate without changing project memory", () => {
    const second = {
      ...unverifiedDecision,
      id: "component:decision-3",
      component_id: "decision-3",
      title: "Review the second policy",
      evidence: {
        ...unverifiedDecision.evidence,
        evidence_span_id: "evidence-3",
      },
    };
    mocks.memory.data = memoryData({ records: [unverifiedDecision, second] });
    renderMemory("/memory?view=review");

    expect(screen.getByRole("heading", { name: "Review the context policy" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Skip for now" }));

    expect(mocks.reviewMemory.mutateAsync).not.toHaveBeenCalled();
    expect(screen.getByRole("heading", { name: "Review the second policy" })).toBeInTheDocument();
    expect(screen.getByText(/Nothing was changed/)).toBeInTheDocument();
  });

  it("shows claim-wide impact before adding a repeated candidate", () => {
    mocks.memory.data = memoryData({
      records: [{ ...unverifiedDecision, occurrence_count: 3 }],
    });
    renderMemory("/memory?view=review");

    expect(screen.getByText(/appears in 3 matching source occurrences/i)).toBeInTheDocument();
    expect(screen.getByText(/one decision updates the canonical claim/i)).toBeInTheDocument();
  });

  it("can load review records beyond the first page", async () => {
    const firstPage = Array.from({ length: 50 }, (_, index) => ({
      ...unverifiedDecision,
      id: `component:review-page-${index}`,
      component_id: `review-page-${index}`,
      title: `Review candidate ${index + 1}`,
      evidence: {
        ...unverifiedDecision.evidence,
        evidence_span_id: `review-evidence-${index}`,
      },
    }));
    const data = memoryData({ records: firstPage });
    const unverified = data.sections.find((section) => section.id === "unverified");
    unverified.total = 97;
    unverified.has_more = true;
    data.totals.needs_review = 97;
    data.totals.ready_to_review = 97;
    data.totals.attention = 97;
    data.totals.all = 97;
    data.matches = 97;
    mocks.memory.data = data;

    renderMemory("/memory?view=review");

    expect(latestMemoryOptions()).toMatchObject({ limit: 50 });
    fireEvent.click(screen.getByRole("button", { name: "Load more review records" }));
    await waitFor(() => expect(latestMemoryOptions()).toMatchObject({ limit: 100 }));
  });

  it("keeps stale provider snapshots out of the confirm workflow", () => {
    mocks.memory.data = memoryData({
      records: [{
        ...unverifiedDecision,
        id: "component:stale-1",
        component_id: "stale-1",
        section: "stale",
        status: "stale",
        verification: "needs_review",
        source: { ...unverifiedDecision.source, source_type: "github", freshness: "stale" },
        allowed_actions: ["supersede", "dismiss"],
      }],
    });
    renderMemory("/memory?view=freshness");

    expect(screen.getByRole("button", { name: "Source health" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText(/must be refreshed before they can describe the project now/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Open Integrations to refresh/i })).toHaveAttribute(
      "href",
      "/app/connectors",
    );
    expect(screen.queryByRole("button", { name: "Add to current memory" })).not.toBeInTheDocument();
  });

  it("separates conflicts from the ordinary confirmation queue", () => {
    mocks.memory.data = memoryData({
      records: [{
        ...unverifiedDecision,
        id: "component:conflict-1",
        component_id: "conflict-1",
        section: "conflicts",
        status: "conflict",
        verification: "needs_review",
        allowed_actions: ["supersede", "dismiss"],
      }],
    });
    renderMemory("/memory?view=review");

    expect(screen.getByText("Conflicts still need a decision")).toBeInTheDocument();
    expect(screen.getByText("Conflicts need comparison")).toBeInTheDocument();
    expect(screen.getByText("Conflict flagged")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add to current memory" })).not.toBeInTheDocument();
    expect(screen.queryByText("Agenda memory ready")).not.toBeInTheDocument();
  });

  it("keeps a conflict action visibly pending for the exact record", async () => {
    let finishReview;
    mocks.reviewMemory.mutateAsync.mockImplementation(() => new Promise((resolve) => {
      finishReview = resolve;
    }));
    mocks.memory.data = memoryData({
      records: [{
        ...unverifiedDecision,
        id: "component:conflict-pending",
        component_id: "conflict-pending",
        section: "conflicts",
        status: "conflict",
        verification: "needs_review",
        allowed_actions: ["supersede", "dismiss"],
      }],
    });
    renderMemory("/memory?view=review");

    fireEvent.click(screen.getByRole("button", { name: "Supersede" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm supersede" }));

    await waitFor(() => expect(screen.getByRole("button", { name: "Saving…" })).toBeDisabled());
    finishReview({ status: "superseded" });
    await waitFor(() => expect(mocks.reviewMemory.mutateAsync).toHaveBeenCalledWith({
      componentId: "conflict-pending",
      action: "supersede",
    }));
  });

  it("passes agenda, workspace, source, evidence, time, subtype, and search filters to Memory", async () => {
    renderMemory();

    fireEvent.click(screen.getByRole("button", { name: /All DaemonState/ }));
    await waitFor(() => expect(latestMemoryOptions()).toMatchObject({ scope: "workspace" }));
    expect(screen.getByRole("button", { name: /All DaemonState/ })).toHaveAttribute("aria-pressed", "true");

    fireEvent.change(screen.getByRole("searchbox", { name: "Search memory" }), {
      target: { value: "evidence" },
    });
    await waitFor(() => expect(latestMemoryOptions()).toMatchObject({ query: "evidence" }));

    fireEvent.change(screen.getByLabelText("Source"), { target: { value: "sessions" } });
    await waitFor(() => expect(latestMemoryOptions()).toMatchObject({ sourceGroup: "sessions" }));

    fireEvent.change(screen.getByLabelText("Evidence"), { target: { value: "needs_review" } });
    await waitFor(() => expect(latestMemoryOptions()).toMatchObject({ verification: "needs_review" }));

    fireEvent.change(screen.getByLabelText("Time"), { target: { value: "future" } });
    await waitFor(() => expect(latestMemoryOptions()).toMatchObject({ temporal: "future" }));

    fireEvent.change(screen.getByLabelText("Subtype"), { target: { value: "Decision" } });
    await waitFor(() => expect(latestMemoryOptions()).toMatchObject({
      query: "evidence",
      scope: "workspace",
      sourceGroup: "sessions",
      verification: "needs_review",
      temporal: "future",
      kind: "Decision",
    }));

    fireEvent.click(screen.getByRole("button", { name: "Clear filters" }));
    await waitFor(() => expect(latestMemoryOptions()).toMatchObject({
      query: "",
      scope: "workspace",
      sourceGroup: "all",
      verification: "all",
      temporal: "all",
      kind: null,
    }));
  });

  it("switches between current, review, source health, people, and history taxonomies", () => {
    renderMemory();

    fireEvent.click(screen.getByRole("button", { name: "Review queue" }));
    expect(screen.getByRole("button", { name: "Review queue" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Filter by Decisions" })).toHaveTextContent(/1\s*to decide/);
    expect(screen.getByRole("heading", { name: /Decide what future agents may reuse/i })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "People & dates" }));
    expect(screen.getByRole("button", { name: "Filter by Milestones" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "History" }));
    expect(screen.getByRole("button", { name: "Filter by Resolved blockers" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Filter by Completed & reported activity" })).toBeInTheDocument();
  });

  it("keeps match counts and subtype choices inside the selected view", () => {
    mocks.memory.data = memoryData({
      records: [
        decision,
        {
          ...decision,
          id: "component:owner-1",
          component_id: "owner-1",
          section: "owners",
          semantic_section: "owners",
          kind: "Owner",
          title: "Darshan owns memory quality",
        },
        {
          ...decision,
          id: "component:history-1",
          component_id: "history-1",
          section: "completed",
          semantic_section: "work",
          kind: "Task",
          title: "Complete the first memory audit",
          status: "completed",
          temporal: "past",
        },
      ],
    });

    renderMemory();

    fireEvent.click(screen.getByRole("button", { name: "Current" }));
    expect(screen.getByRole("status")).toHaveTextContent("1 matching record in Current");
    const subtype = screen.getByLabelText("Subtype");
    expect(within(subtype).getByRole("option", { name: "Decision (1)" })).toBeInTheDocument();
    expect(within(subtype).queryByRole("option", { name: /Owner/ })).not.toBeInTheDocument();
    expect(within(subtype).queryByRole("option", { name: /Task/ })).not.toBeInTheDocument();
  });

  it("uses complete API facets for subtype choices instead of the truncated preview", () => {
    mocks.memory.data = memoryData({ records: [decision] });
    mocks.memory.data.facets.kinds_by_section.decisions["Architecture decision"] = 4;

    renderMemory("/memory?view=active");

    expect(within(screen.getByLabelText("Subtype")).getByRole("option", {
      name: "Architecture decision (4)",
    })).toBeInTheDocument();
  });

  it("uses the selected physical section match count instead of the whole view total", () => {
    mocks.memory.data = memoryData({
      records: [
        {
          ...decision,
          id: "component:completed-count",
          component_id: "completed-count",
          section: "completed",
          semantic_section: "work",
          status: "resolved",
        },
        {
          ...decision,
          id: "component:revision-count",
          component_id: "revision-count",
          section: "revisions",
          semantic_section: "deliveries",
          status: "historical",
        },
      ],
    });
    mocks.memory.data.matches = 1;

    renderMemory("/memory?view=history&section=completed");

    expect(screen.getByRole("status")).toHaveTextContent(
      "1 matching record in Completed & reported activity",
    );
  });

  it("uses scope-neutral completion copy when agenda mode falls back to the workspace", () => {
    mocks.memory.data = memoryData({ records: [] });

    renderMemory("/memory?view=review");

    expect(screen.getByText("Review queue clear")).toBeInTheDocument();
    expect(screen.queryByText("Agenda memory ready")).not.toBeInTheDocument();
  });

  it("shows the source evidence that cleared a resolved blocker", () => {
    mocks.memory.data = memoryData({
      records: [{
        ...decision,
        id: "component:resolved-blocker-1",
        component_id: "resolved-blocker-1",
        section: "resolved",
        semantic_section: "blockers",
        kind: "Blocker",
        title: "Database credentials are missing",
        summary: "Database credentials are missing.",
        status: "resolved",
        temporal: "past",
        resolution: {
          summary: "Database credentials were configured.",
          source: {
            label: "Agent run · blocker resolution",
            source_type: "agent_run_observation",
            document_id: "resolution-source-1",
            freshness: "not_remote",
          },
          evidence: {
            excerpt: "Blocker resolution: Database credentials were configured.",
            review_status: "needs_review",
            exact: true,
          },
        },
      }],
    });

    renderMemory();
    fireEvent.click(screen.getByRole("button", { name: "History" }));
    fireEvent.click(screen.getByRole("button", {
      name: "Inspect evidence for Database credentials are missing",
    }));

    const drawer = screen.getByRole("dialog", { name: "Resolved blockers" });
    expect(within(drawer).getByText(
      "Evidence that cleared this blocker",
    )).toBeInTheDocument();
    expect(within(drawer).getAllByText(
      /Database credentials were configured/,
    )).not.toHaveLength(0);
    expect(within(drawer).getByText(
      /Blocker resolution: Database credentials were configured/,
    )).toBeInTheDocument();
    expect(within(drawer).getByText(
      "Agent run · blocker resolution",
    )).toBeInTheDocument();
  });

  it("confirms only records whose API contract allows exact-evidence review", async () => {
    renderMemory();

    fireEvent.click(screen.getByRole("button", { name: "Review queue" }));
    expect(screen.getByText(/excerpt proves where this claim came from/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Add to current memory" }));

    await waitFor(() => expect(mocks.reviewMemory.mutateAsync).toHaveBeenCalledWith({
      componentId: "decision-2",
      action: "confirm",
    }));
  });

  it("separates evidence gaps and never offers to verify them as current", () => {
    mocks.memory.data = memoryData({
      records: [{
        ...unverifiedDecision,
        id: "component:evidence-gap",
        component_id: "evidence-gap",
        title: "Decision with no traceable excerpt",
        verification: "unavailable",
        evidence: null,
        allowed_actions: ["supersede", "dismiss"],
      }],
    });

    renderMemory();

    expect(screen.getByRole("heading", {
      name: "Current is empty because evidence is incomplete",
    })).toBeInTheDocument();
    expect(screen.getByText(/can only be cleaned up—not promoted to Current/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Review queue" }));
    expect(screen.getByText("Some records lack exact evidence")).toBeInTheDocument();
    expect(screen.getByText("Evidence gaps cannot be verified here")).toBeInTheDocument();
    expect(screen.getAllByText("No exact evidence")).not.toHaveLength(0);
    expect(screen.getByText(/cannot prove what text produced the claim/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add to current memory" })).not.toBeInTheDocument();
    expect(screen.queryByText("Review queue clear")).not.toBeInTheDocument();
  });

  it("explains the impact before superseding a current memory record", async () => {
    renderMemory();

    fireEvent.click(screen.getByRole("button", { name: "Current" }));
    fireEvent.click(screen.getByRole("button", {
      name: "Inspect evidence for Use source-backed records",
    }));
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
    renderMemory();

    fireEvent.click(screen.getByRole("button", { name: "Current" }));
    fireEvent.click(screen.getByRole("button", {
      name: "Inspect evidence for Use source-backed records",
    }));
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
    ["freshness", "stale", "Refresh needed", "stale", "verified", "Stale — review required"],
    ["history", "superseded", "Superseded memory", "superseded", "verified", "Superseded"],
    ["history", "dismissed", "Dismissed memory", "dismissed", "verified", "Dismissed"],
    ["history", "resolved", "Resolved blockers", "resolved", "verified", "Resolved"],
    ["history", "revisions", "Source revisions", "historical", "observed", "Historical record"],
  ])(
    "prioritizes governing %s state over the evidence verification flag",
    async (view, section, typeTitle, status, verification, expectedLabel) => {
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
      renderMemory();

      fireEvent.click(screen.getByRole("button", { name: view === "freshness" ? "Source health" : "History" }));
      fireEvent.click(screen.getByRole("button", { name: `Filter by ${typeTitle}` }));
      await waitFor(() => expect(latestMemoryOptions()).toMatchObject({ section }));
      fireEvent.click(screen.getByRole("button", {
        name: "Inspect evidence for Use source-backed records",
      }));

      expect(within(screen.getByRole("dialog", { name: typeTitle })).getByText(expectedLabel)).toBeInTheDocument();
    },
  );

  it("traps focus in the memory drawer, closes on Escape, and returns focus", async () => {
    renderMemory();

    fireEvent.click(screen.getByRole("button", { name: "Current" }));
    const trigger = screen.getByRole("button", {
      name: "Inspect evidence for Use source-backed records",
    });
    trigger.focus();
    fireEvent.click(trigger);

    const close = screen.getByRole("button", { name: "Close memory details" });
    expect(close).toHaveFocus();
    fireEvent.keyDown(window, { key: "Tab", shiftKey: true });
    expect(screen.getByRole("button", { name: "Dismiss" })).toHaveFocus();

    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(trigger).toHaveFocus());
    expect(screen.queryByRole("dialog", { name: "Decisions" })).not.toBeInTheDocument();
  });

  it("sets an explicit agenda while explaining its effect on Current Memory", async () => {
    mocks.memory.data = memoryData();
    renderMemory();

    fireEvent.click(screen.getByRole("button", { name: "Open Current goal" }));
    expect(within(screen.getByRole("dialog", { name: "Current goal" })).getByText(
      /scopes Current Memory.*does not start work, edit files/i,
    )).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Set project focus"), {
      target: { value: "Make project memory trustworthy" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Set goal" }));

    await waitFor(() => expect(mocks.setGoal.mutateAsync).toHaveBeenCalledWith({
      title: "Make project memory trustworthy",
      source_kind: "user_selected",
    }));
  });

  it("explains the scope fallback before clearing the agenda", async () => {
    renderMemory();

    fireEvent.click(screen.getByRole("button", { name: "Open Current goal" }));
    fireEvent.click(screen.getByRole("button", { name: "Clear goal" }));

    expect(mocks.clearGoal.mutateAsync).not.toHaveBeenCalled();
    expect(screen.getByText(/returning Memory to the full workspace/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Clear current goal" }));

    await waitFor(() => expect(mocks.clearGoal.mutateAsync).toHaveBeenCalledTimes(1));
  });

  it("explains the selected Library session fallback before clearing a goal", () => {
    mocks.memory.data.scope.selected_session_document_id = "source-session-1";
    renderMemory();

    fireEvent.click(screen.getByRole("button", { name: "Open Current goal" }));
    fireEvent.click(screen.getByRole("button", { name: "Clear goal" }));

    expect(screen.getByText(
      /Current Memory will then follow the session selected in Library/i,
    )).toBeInTheDocument();
  });

  it("fails closed when the Memory API is unavailable", () => {
    mocks.memory.isError = true;
    mocks.memory.data = null;
    renderMemory();

    expect(screen.getByRole("alert")).toHaveTextContent(
      "No cached or inferred records are being shown",
    );
    expect(screen.getByRole("heading", { name: "Decisions" }).closest("article")).toHaveTextContent(
      "No source-backed records yet",
    );
    expect(screen.queryByText("Inspect evidence")).not.toBeInTheDocument();
  });
});
