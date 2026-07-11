import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import DigestBoard from "./DigestBoard";

function digestCard(overrides) {
  return {
    id: overrides.id,
    title: overrides.title,
    summary: overrides.summary,
    type: overrides.type,
    status: overrides.status || "active",
    attention_score: overrides.attention_score ?? 50,
    provenance: overrides.provenance || [],
    ...overrides,
  };
}

const digest = {
  workspace_id: "workspace-1",
  generated_at: "2026-07-02T12:00:00Z",
  objective: { status: "not_supplied", text: null },
  scope: { included_source_count: 3, pending_source_count: 0 },
  build: { last_built_at: "2026-07-02T12:00:00Z" },
  health: { status: "healthy" },
  cards: [
    digestCard({
      id: "session-1",
      type: "agent_session",
      category: "agent_session",
      title: "Agent session: restore graph board",
      summary: "Codex restored the graph board layout and connector overlay.",
      attention_score: 90,
      session: {
        session_id: "019f4cfe-f6d7-7a80-b727-c3011aa08252",
        title: "Restore the graph board",
        tool: "codex",
        branch: "codex/graph-truth",
        cwd: "/repo/context-engine",
        message_count: 24,
        started_at: "2026-07-02T11:00:00Z",
      },
      workspace_relevance: { status: "relevant", reasons: ["Imported into this workspace"] },
    }),
    digestCard({
      id: "decision-1",
      type: "decision",
      category: "decision",
      title: "Decision: keep the digest board",
      summary: "Keep the digest board as the default graph route.",
      attention_score: 80,
    }),
    digestCard({
      id: "pr-1",
      type: "source",
      category: "pull_request",
      title: "PR #12",
      summary: "PR 12 fixes graph review regressions.",
      attention_score: 70,
      provenance: [{ source_url: "https://github.com/example/context-engine/pull/12" }],
      remote_item: { repository: "example/context-engine", number: 12, observed_status: "closed" },
    }),
  ],
  links: [
    {
      id: "link-1",
      source_card_id: "decision-1",
      target_card_id: "pr-1",
      relationship_id: "relationship-1",
      relationship_type: "enables",
      label: "enables",
      status: "active",
      confidence: 0.92,
    },
  ],
};

function renderBoard(props = {}) {
  return render(
    <MemoryRouter>
      <DigestBoard digest={digest} workspaceName="Test workspace" generatedAt={digest.generated_at} {...props} />
    </MemoryRouter>,
  );
}

describe("DigestBoard", () => {
  it("draws only factual digest relationships instead of decorative guides", () => {
    const { container } = renderBoard();

    const edges = container.querySelectorAll("[data-evidence-edge]");
    expect(edges).toHaveLength(1);
    expect(edges[0]).toHaveAttribute("data-relationship-type", "enables");
    expect(container.querySelectorAll("[data-component-line]")).toHaveLength(0);
    expect(screen.getByText(/1 sourced link/)).toBeInTheDocument();
  });

  it("keeps build explanations and metadata out of the default canvas", () => {
    renderBoard();

    expect(screen.queryByText(/uses imported snapshots only/i)).not.toBeInTheDocument();
    expect(screen.queryByText("Graph details")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Update graph" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open graph actions" })).toBeInTheDocument();
  });

  it("reveals exact scope and timestamp only when graph details are requested", () => {
    renderBoard();

    fireEvent.click(screen.getByRole("button", { name: "Open graph actions" }));
    expect(screen.getByText(/use imported snapshots only/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Graph details" }));

    expect(screen.getByRole("heading", { name: "Graph details" })).toBeInTheDocument();
    expect(screen.getByText("Imported sources")).toBeInTheDocument();
    expect(screen.getByText(/Jul 2, 2026/)).toBeInTheDocument();
  });

  it("keeps the objective compact in the toolbar instead of rendering a hero strip", () => {
    renderBoard();

    expect(screen.getByText("Objective not supplied — showing workspace evidence")).toBeInTheDocument();
    expect(screen.queryByText("Test workspace has no supplied objective")).not.toBeInTheDocument();
    expect(screen.queryByText("The map does not infer intent from source history.")).not.toBeInTheDocument();
  });

  it("uses an open canvas and borderless graph cards", () => {
    const { container } = renderBoard();

    expect(screen.getByTestId("session-knowledge-map")).not.toHaveClass("border");
    expect(screen.getByTestId("evidence-flow-canvas")).not.toHaveClass("border");
    container.querySelectorAll("[data-graph-node]").forEach((node) => {
      expect(node).not.toHaveClass("border");
    });
  });

  it("shows identifiable session context on an individual evidence node", () => {
    renderBoard();

    expect(screen.getByText("Restore the graph board")).toBeInTheDocument();
    expect(screen.getByText(/codex\/graph-truth/)).toBeInTheDocument();
    expect(screen.queryByText("AI session 2")).not.toBeInTheDocument();
    expect(screen.getByText(/Workspace relevant/)).toBeInTheDocument();
  });

  it("keeps document health unknown when no explicit document finding was returned", () => {
    renderBoard();

    expect(screen.getAllByText("Broken docs").length).toBeGreaterThan(0);
    expect(screen.getByText(/Document checks are not available or verified/i)).toBeInTheDocument();
  });

  it("focuses a selected record in quick peek and opens full details only on request", () => {
    const onSelectCard = vi.fn();
    const { container } = renderBoard({ onSelectCard });

    fireEvent.click(container.querySelector('[data-graph-node="decision-1"]'));

    expect(onSelectCard).not.toHaveBeenCalled();
    expect(screen.getByText("enables")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Clear focus" })).toBeInTheDocument();
    expect(container.querySelector('[data-graph-node="session-1"]')).toHaveClass("opacity-20");
    expect(screen.getByRole("complementary", { name: "Selected record quick peek" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Open full details" }));
    expect(onSelectCard).toHaveBeenCalledWith(expect.objectContaining({ id: "decision-1" }));
  });

  it("supports real manual node movement and restores auto layout", () => {
    const { container } = renderBoard();
    const session = container.querySelector('[data-graph-node="session-1"]');

    expect(session).toHaveAttribute("data-movable", "false");
    fireEvent.click(screen.getByRole("button", { name: "Toggle graph layout mode" }));
    expect(session).toHaveAttribute("data-movable", "true");

    fireEvent.pointerDown(session, { pointerId: 1, button: 0, clientX: 10, clientY: 10 });
    fireEvent.pointerMove(session, { pointerId: 1, clientX: 50, clientY: 35 });
    fireEvent.pointerUp(session, { pointerId: 1, clientX: 50, clientY: 35 });
    expect(session).toHaveStyle({ transform: "translate(40px, 25px)" });

    fireEvent.click(screen.getByRole("button", { name: "Lock layout" }));
    expect(session).toHaveAttribute("data-movable", "false");
    fireEvent.click(screen.getByRole("button", { name: "Toggle graph layout mode" }));
    expect(session).toHaveStyle({ transform: "translate(0px, 0px)" });
  });

  it("filters graph groups without changing the underlying category counts", () => {
    renderBoard();

    fireEvent.click(screen.getByRole("button", { name: "AI sessions · 1" }));
    expect(screen.queryByText("Restore the graph board")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "AI sessions · 1" })).toHaveAttribute("aria-pressed", "false");
  });

  it("separates incremental graph updates from explicit rebuilds", () => {
    const onBuild = vi.fn();
    renderBoard({ onBuild });

    fireEvent.click(screen.getByRole("button", { name: "Update graph" }));
    fireEvent.click(screen.getByRole("button", { name: "Open graph actions" }));
    fireEvent.click(screen.getByRole("button", { name: "Rebuild from snapshots" }));

    expect(onBuild).toHaveBeenNthCalledWith(1, "incremental");
    expect(onBuild).toHaveBeenNthCalledWith(2, "rebuild");
  });
});
