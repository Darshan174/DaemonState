import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { MAP_NODE_SIZE, positionNodes } from "../layout";
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
  scope: {
    included_source_count: 5,
    pending_source_count: 0,
    project_paths: ["/workspace/context-engine"],
    project_repositories: [],
  },
  build: { last_built_at: "2026-07-02T12:00:00Z" },
  health: { status: "healthy" },
  cards: [
    digestCard({
      id: "session-relevant",
      type: "agent_session",
      category: "agent_session",
      title: "Agent session: restore graph board",
      summary: "Codex restored the graph board layout.",
      attention_score: 90,
      session: { session_id: "session-relevant", title: "Restore the graph board", tool: "codex" },
      workspace_relevance: { status: "relevant", reasons: ["Repository matched."] },
    }),
    digestCard({
      id: "session-unknown",
      type: "agent_session",
      category: "agent_session",
      title: "Agent session: inspect migrations",
      summary: "Repository metadata was unavailable.",
      session: { session_id: "session-unknown", title: "Inspect migrations", tool: "claude_code" },
      workspace_relevance: { status: "unknown", reasons: ["No comparable metadata."] },
    }),
    digestCard({
      id: "session-irrelevant",
      type: "agent_session",
      category: "agent_session",
      title: "Agent session: edit another product",
      summary: "This session belongs to another repository.",
      session: { session_id: "session-irrelevant", title: "Edit another product", tool: "codex" },
      workspace_relevance: { status: "not_relevant", reasons: ["Repository differed."] },
    }),
    digestCard({
      id: "decision-1",
      type: "decision",
      category: "decision",
      title: "Decision: keep evidence visible",
      summary: "Keep source evidence inspectable.",
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
  const onPrepareHandoff = props.onPrepareHandoff || vi.fn().mockResolvedValue(
    "# Context Engine safe compiled handoff\n\nNo raw imported instructions.\n",
  );
  return render(
    <MemoryRouter>
      <DigestBoard digest={digest} workspaceName="Test workspace" generatedAt={digest.generated_at} onPrepareHandoff={onPrepareHandoff} {...props} />
    </MemoryRouter>,
  );
}

describe("DigestBoard", () => {
  it("draws each factual digest relationship between real endpoints", () => {
    const { container } = renderBoard();

    const edges = container.querySelectorAll("line[data-evidence-edge]");
    expect(edges).toHaveLength(1);
    expect(edges[0]).toHaveAttribute("data-relationship-type", "enables");
    expect(screen.getByText(/1 sourced link/)).toBeInTheDocument();
    expect(container.querySelectorAll("[data-component-line]")).toHaveLength(0);
  });

  it("renders contained architecture as a parent envelope instead of another generic arrow", () => {
    const repository = digestCard({
      id: "code-repository",
      type: "code_area",
      category: "code_area",
      title: "Repository: context-engine",
      summary: "The indexed repository boundary.",
      attention_score: 100,
    });
    const api = digestCard({
      id: "code-api",
      type: "code_area",
      category: "code_area",
      title: "API layer",
      summary: "FastAPI routes and services.",
      attention_score: 90,
    });
    const partOf = {
      id: "link-contained",
      source_card_id: "code-api",
      target_card_id: "code-repository",
      relationship_type: "part_of",
      label: "part of",
    };
    const { container } = renderBoard({ digest: { ...digest, cards: [repository, api], links: [partOf] } });

    const envelope = container.querySelector("[data-semantic-container]");
    expect(envelope).toHaveAttribute("data-parent-node", "code-repository");
    expect(envelope).toHaveAttribute("data-child-node", "code-api");
    expect(container.querySelector('line[data-relationship-type="part_of"]')).not.toBeInTheDocument();
  });

  it("uses distinct visual grammar for contradictions and supersession", () => {
    const { container } = renderBoard({
      digest: {
        ...digest,
        links: [
          { ...digest.links[0], id: "conflict", relationship_type: "contradicts" },
          { ...digest.links[0], id: "replacement", relationship_type: "supersedes" },
        ],
      },
    });

    expect(container.querySelector('[data-relationship-visual="contradiction"] line')).toHaveAttribute("stroke-dasharray", "7 4");
    expect(container.querySelector('[data-relationship-visual="supersession"] line')).toHaveAttribute("stroke-dasharray", "9 4");
  });

  it("keeps the default project map free of the old control-heavy UI", () => {
    renderBoard();

    expect(screen.getByRole("button", { name: "Refresh project map" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Copy project brief" })).toBeInTheDocument();
    expect(screen.getByLabelText("Search project map")).toBeInTheDocument();
    expect(screen.queryByRole("complementary", { name: "Graph minimap" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /layout/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("complementary", { name: "Selected record quick peek" })).not.toBeInTheDocument();
    expect(screen.queryByText("Broken docs")).not.toBeInTheDocument();
  });

  it("explains empty product lanes without implying checks passed", () => {
    renderBoard();

    expect(screen.getByText("Refresh this project to map its structure.")).toBeInTheDocument();
    expect(screen.getByText("No explicit verified next task.")).toBeInTheDocument();
    expect(screen.getByText("No verified document gaps.")).toBeInTheDocument();
    expect(screen.getByText("Docs")).toBeInTheDocument();
    expect(screen.queryByText("Checks")).not.toBeInTheDocument();
  });

  it("shows an observed objective without restoring the execution form", () => {
    renderBoard({
      digest: {
        ...digest,
        objective: { status: "supplied", text: "Preserve source-backed project handoffs." },
      },
    });

    expect(screen.getByTitle("Preserve source-backed project handoffs.")).toHaveTextContent("Preserve source-backed project handoffs.");
    expect(screen.queryByRole("textbox", { name: /objective/i })).not.toBeInTheDocument();
  });

  it("expresses session relevance visually without relevance prose on the canvas", () => {
    const { container } = renderBoard();
    const relevant = container.querySelector('[data-graph-node="session-relevant"]');
    const unknown = container.querySelector('[data-graph-node="session-unknown"]');
    const irrelevant = container.querySelector('[data-graph-node="session-irrelevant"]');

    expect(relevant).toHaveAttribute("data-relevance-status", "relevant");
    expect(relevant).toHaveStyle({ opacity: "1" });
    expect(unknown).toHaveAttribute("data-relevance-status", "unknown");
    expect(unknown).toHaveStyle({ opacity: "0.48", borderStyle: "dotted" });
    expect(irrelevant).toHaveAttribute("data-relevance-status", "not_relevant");
    expect(irrelevant).toHaveStyle({ opacity: "0.16", borderStyle: "dashed" });
    expect(screen.queryByText("Workspace relevant")).not.toBeInTheDocument();
    expect(screen.queryByText("Different repository")).not.toBeInTheDocument();
    expect(screen.queryByText("Relevance unverified")).not.toBeInTheDocument();
  });

  it("keeps every visible card collision-free inside dense lanes", () => {
    const lanes = [
      ["sessions", 6],
      ["architecture", 8],
      ["decisions", 4],
      ["next_tasks", 2],
      ["prs", 4],
      ["issues", 4],
      ["documents", 2],
      ["other", 2],
    ].map(([id, count]) => ({
      id,
      cards: Array.from({ length: count }, (_, index) => ({ id: `${id}-${index}` })),
    }));
    const nodes = positionNodes({ lanes });

    for (let leftIndex = 0; leftIndex < nodes.length; leftIndex += 1) {
      for (let rightIndex = leftIndex + 1; rightIndex < nodes.length; rightIndex += 1) {
        const left = nodes[leftIndex];
        const right = nodes[rightIndex];
        const separated = Math.abs(left.x - right.x) >= MAP_NODE_SIZE.width
          || Math.abs(left.y - right.y) >= MAP_NODE_SIZE.height;
        expect(separated, `${left.id} overlaps ${right.id}`).toBe(true);
      }
    }
  });

  it("keeps search active while promoting a quieter matching record", () => {
    const tasks = Array.from({ length: 3 }, (_, index) => digestCard({
      id: `task-${index}`,
      type: "task",
      category: "task",
      title: index === 2 ? "Task: quiet target" : `Task: visible ${index}`,
      summary: index === 2 ? "quiet target" : `visible ${index}`,
      attention_score: 100 - index,
    }));
    const { container } = renderBoard({ digest: { ...digest, cards: [...digest.cards, ...tasks] } });
    const search = screen.getByLabelText("Search project map");

    fireEvent.change(search, { target: { value: "quiet target" } });

    expect(search).toHaveValue("quiet target");
    expect(container.querySelector('[data-graph-node="task-2"]')).toBeInTheDocument();
  });

  it("uses the evidence claim instead of repeating the project name on supporting nodes", () => {
    const supporting = digestCard({
      id: "supporting-1",
      type: "evidence",
      category: "supporting_evidence",
      title: "Slack: context-engine",
      summary: "Channel: #context-engine-channel Context Engine connects to sources like Slack and GitHub.",
      provenance: [{ excerpt: "Context Engine connects to sources like Slack and GitHub." }],
    });
    const { container } = renderBoard({ digest: { ...digest, cards: [supporting] } });

    expect(container.querySelector('[data-graph-node="supporting-1"]')).toHaveTextContent(
      "Connects to sources like Slack and GitHub",
    );
  });

  it("opens the full inspector immediately and labels only selected factual edges", () => {
    const onSelectCard = vi.fn();
    const { container, rerender } = renderBoard({ onSelectCard });

    fireEvent.click(container.querySelector('[data-graph-node="decision-1"]'));
    expect(onSelectCard).toHaveBeenCalledWith(expect.objectContaining({ id: "decision-1" }));

    rerender(
      <MemoryRouter>
        <DigestBoard digest={digest} workspaceName="Test workspace" selectedCardId="decision-1" onSelectCard={onSelectCard} />
      </MemoryRouter>,
    );
    expect(screen.getByText("enables")).toBeInTheDocument();
    expect(container.querySelector('[data-graph-node="session-relevant"]')).toHaveStyle({ opacity: "0.13" });
  });

  it("pans, zooms, and resets the project map", () => {
    renderBoard();
    const canvas = screen.getByTestId("evidence-flow-canvas");
    const graph = screen.getByTestId("fitted-evidence-graph");

    fireEvent.pointerDown(canvas, { pointerId: 7, button: 0, clientX: 100, clientY: 100 });
    fireEvent.pointerMove(canvas, { pointerId: 7, clientX: 145, clientY: 125 });
    fireEvent.pointerUp(canvas, { pointerId: 7, clientX: 145, clientY: 125 });
    expect(graph.style.transform).toContain("calc(-50% + 45px)");

    fireEvent.wheel(canvas, { deltaY: -100 });
    expect(graph.style.transform).toContain("scale(1.1)");
    fireEvent.click(screen.getByRole("button", { name: "Open project map actions" }));
    fireEvent.click(screen.getByRole("button", { name: "Fit project map" }));
    expect(graph.style.transform).toContain("calc(-50% + 0px)");
    expect(graph.style.transform).toContain("scale(1)");
  });

  it("separates map refresh from an explicit rebuild", () => {
    const onBuild = vi.fn();
    renderBoard({ onBuild });

    fireEvent.click(screen.getByRole("button", { name: "Refresh project map" }));
    fireEvent.click(screen.getByRole("button", { name: "Open project map actions" }));
    fireEvent.click(screen.getByRole("button", { name: "Rebuild projection" }));

    expect(onBuild).toHaveBeenNthCalledWith(1, "incremental");
    expect(onBuild).toHaveBeenNthCalledWith(2, "rebuild");
    expect(screen.getByText(/Provider sync stays separate/i)).toBeInTheDocument();
  });

  it("compiles and copies a hardened context pack as the map's primary outcome", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    const onPrepareHandoff = vi.fn().mockResolvedValue(
      "# Context Engine safe compiled handoff\n\nPrompt-risk evidence excluded.\n",
    );
    Object.defineProperty(globalThis.navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });
    renderBoard({ onPrepareHandoff });

    fireEvent.click(screen.getByRole("button", { name: "Copy project brief" }));
    await waitFor(() => expect(onPrepareHandoff).toHaveBeenCalledOnce());
    await waitFor(() => expect(writeText).toHaveBeenCalledOnce());
    const copied = writeText.mock.calls[0][0];
    expect(copied).toContain("Context Engine safe compiled handoff");
    expect(copied).toContain("Prompt-risk evidence excluded");
    expect(screen.getByRole("button", { name: "Copied" })).toBeInTheDocument();
  });

  it("shows focused oversight and only non-zero attention counts", () => {
    const onSelectCard = vi.fn();
    const focusId = "00000000-0000-0000-0000-000000000010";
    const focusedCard = digestCard({
      id: `component:${focusId}`,
      type: "task",
      category: "task",
      title: "Make runtime writes retry-safe",
      summary: "Add stable runtime event identity.",
    });
    renderBoard({
      digest: {
        ...digest,
        cards: [...digest.cards, focusedCard],
        oversight: {
          current_focus: { component_id: focusId, title: "Make runtime writes retry-safe" },
          latest_outcome: null,
          attention: { blocked: 1, unverified: 2, stale: 0 },
        },
      },
      onSelectCard,
    });

    expect(screen.getByTitle("Make runtime writes retry-safe")).toHaveTextContent("Focus · Make runtime writes retry-safe");
    expect(screen.getByLabelText("Focused task attention")).toHaveTextContent("Blocked 1");
    expect(screen.getByLabelText("Focused task attention")).toHaveTextContent("Unverified 2");
    expect(screen.getByLabelText("Focused task attention")).not.toHaveTextContent("Stale");
    expect(screen.getByRole("button", { name: "Attention 3" })).toBeInTheDocument();
    fireEvent.click(screen.getByTitle("Make runtime writes retry-safe"));
    expect(onSelectCard).toHaveBeenCalledWith(focusedCard);
    expect(screen.queryByText(/ready score/i)).not.toBeInTheDocument();
  });

  it("opens the compact project-wide open-loop rail trigger without adding map nodes", () => {
    const onOpenLoops = vi.fn();
    const { container } = renderBoard({
      digest: {
        ...digest,
        open_loops: {
          open_count: 3,
          items: [{ id: "loop-1", title: "Verification is missing", status: "open" }],
        },
      },
      onOpenLoops,
    });

    fireEvent.click(screen.getByRole("button", { name: "Open unresolved work, 3 items" }));
    expect(onOpenLoops).toHaveBeenCalledOnce();
    expect(container.querySelector('[data-graph-node="loop-1"]')).not.toBeInTheDocument();
  });

  it("surfaces pending playbook review through the same compact attention trigger", () => {
    const onOpenLoops = vi.fn();
    renderBoard({
      digest: {
        ...digest,
        open_loops: { open_count: 0, items: [] },
        playbooks: { pending_review_count: 2 },
      },
      onOpenLoops,
    });

    fireEvent.click(screen.getByRole("button", { name: "Review verified agent steps, 2 pending" }));
    expect(onOpenLoops).toHaveBeenCalledOnce();
  });

  it("shows honest monitoring freshness but no watcher or retrieval controls", () => {
    const lastSeen = new Date(Date.now() - 12 * 60 * 1000).toISOString();
    renderBoard({
      digest: {
        ...digest,
        monitoring: { status: "stale", last_seen_at: lastSeen },
      },
    });

    expect(screen.getByRole("status", { name: /Local activity may be stale · watcher last seen 12m ago/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /watcher|retrieval|indexed|combined/i })).not.toBeInTheDocument();
  });

  it("opens a local project from the honest empty state", () => {
    const onIndexProject = vi.fn();
    renderBoard({
      digest: {
        ...digest,
        scope: { ...digest.scope, project_paths: [], project_repositories: [] },
        cards: [],
        links: [],
      },
      onIndexProject,
    });

    fireEvent.change(screen.getByLabelText("Local project path"), { target: { value: "relative/repo" } });
    fireEvent.click(screen.getByRole("button", { name: "Open" }));
    expect(screen.getByRole("alert")).toHaveTextContent("absolute local project path");
    expect(onIndexProject).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText("Local project path"), { target: { value: "/workspace/context-engine" } });
    fireEvent.click(screen.getByRole("button", { name: "Open" }));
    expect(onIndexProject).toHaveBeenCalledWith("/workspace/context-engine");
    expect(screen.queryByText(/token budget/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/objective/i)).not.toBeInTheDocument();
  });

  it("requires a project boundary even when imported sessions already exist", () => {
    renderBoard({
      digest: {
        ...digest,
        scope: { ...digest.scope, project_paths: [], project_repositories: [] },
      },
    });

    expect(screen.getByRole("heading", { name: "Open your project" })).toBeInTheDocument();
    expect(screen.queryByTestId("evidence-flow-canvas")).not.toBeInTheDocument();
  });

  it("sends an indexed project without evidence to Sources", () => {
    renderBoard({ digest: { ...digest, cards: [], links: [] } });

    expect(screen.getByRole("heading", { name: "Your project is ready" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Add evidence" })).toHaveAttribute("href", "/app/sources");
  });
});
