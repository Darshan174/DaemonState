import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ContextInspector from "./ContextInspector";
import { api } from "../../api/client";

vi.mock("../../api/client", () => ({
  api: { get: vi.fn() },
}));

const card = {
  id: "component:1",
  title: "Codex session · …08252",
  summary: "The user asked for a factual graph rebuild.",
  why_it_matters: "It defines the requested graph change.",
  next_action: "Inspect the source before relying on it.",
  status: "needs_review",
  confidence: 0.82,
  authority_weight: 0.6,
  attention_score: 80,
  category: "agent_session",
  classification: { reason: "Explicit session root from an imported AI-session source." },
  workspace_relevance: { status: "unknown", reasons: ["No repository match is available."] },
  session: {
    session_id: "019f4cfe-f6d7-7a80-b727-c3011aa08252",
    tool: "codex",
    model: "gpt-5",
    cwd: "/repo/context-engine",
    branch: "codex/graph-truth",
    message_count: 24,
  },
  source_ids: ["source-1"],
  provenance: [{
    source_document_id: "source-1",
    source_type: "Agent session",
    source_label: "Codex graph task",
    revision_number: 1,
    verification_status: "needs_review",
    excerpt: "User: make the graph factual and inspectable.",
  }],
};

describe("ContextInspector", () => {
  beforeEach(() => {
    api.get.mockReset();
  });

  it("shows session identity and loads the imported transcript", async () => {
    api.get.mockResolvedValue({ content: "[USER]\nMake the graph factual.\n\n[ASSISTANT]\nI will inspect every source." });
    render(
      <ContextInspector
        card={card}
        cards={[card]}
        workspaceId="00000000-0000-0000-0000-000000000001"
        onClose={() => {}}
      />,
    );

    expect(screen.getByText(card.session.session_id)).toBeInTheDocument();
    expect(screen.getByText("/repo/context-engine")).toBeInTheDocument();
    expect(screen.getByText("No repository match is available.")).toBeInTheDocument();

    await waitFor(() => expect(api.get).toHaveBeenCalledWith(
      "/sources/source-1?workspace_id=00000000-0000-0000-0000-000000000001",
    ));
    expect(await screen.findByText(/Make the graph factual/)).toBeInTheDocument();
  });

  it("behaves as a keyboard-closeable modal inspector", () => {
    api.get.mockImplementation(() => new Promise(() => {}));
    const onClose = vi.fn();
    render(
      <ContextInspector card={card} cards={[card]} workspaceId="workspace-1" onClose={onClose} />,
    );

    const dialog = screen.getByRole("dialog");
    expect(screen.getByRole("button", { name: "Close inspector" })).toHaveFocus();
    fireEvent.keyDown(dialog, { key: "Escape" });
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("removes punctuation residue and keeps generic planning copy out of the primary view", () => {
    api.get.mockImplementation(() => new Promise(() => {}));
    const malformedTask = {
      ...card,
      id: "task-1",
      category: "task",
      session: null,
      title: "Task: , provenance, review queue, evals, and temporal support",
      summary: ", provenance, review queue, evals, and temporal support",
      provenance: [{
        ...card.provenance[0],
        excerpt: ", provenance, review queue, evals, and temporal support",
      }],
    };

    render(<ContextInspector card={malformedTask} cards={[malformedTask]} onClose={() => {}} />);

    expect(screen.getByRole("heading", { name: "Provenance, review queue, evals, and temporal support" })).toBeInTheDocument();
    expect(screen.getByText("provenance, review queue, evals, and temporal support")).toBeInTheDocument();
    expect(screen.queryByText(malformedTask.summary)).not.toBeInTheDocument();
    expect(screen.queryByText("Why it matters")).not.toBeInTheDocument();
    expect(screen.queryByText("Suggested next action")).not.toBeInTheDocument();
    expect(screen.queryByText("Attention")).not.toBeInTheDocument();
    expect(screen.getByText("Imported source")).toBeInTheDocument();
  });

  it("shows a concise remote summary without empty provider rows", () => {
    api.get.mockImplementation(() => new Promise(() => {}));
    const issue = {
      ...card,
      id: "issue-1",
      category: "issue",
      session: null,
      title: "Task: Issue #1: Rewrite README",
      summary: "Issue #1: Rewrite README State: open Labels: none The README undersells the shipped product. Acceptance criteria: explain the current surface.",
      remote_item: {
        kind: "issue",
        repository: "acme/context-engine",
        number: 1,
        title: "Rewrite README",
        observed_status: "open",
      },
      freshness: { status: "unknown" },
      provenance: [{ ...card.provenance[0], excerpt: "Exact issue evidence." }],
    };

    render(<ContextInspector card={issue} cards={[issue]} onClose={() => {}} />);

    expect(screen.getByRole("heading", { name: "Issue #1 · Rewrite README" })).toBeInTheDocument();
    expect(screen.getByText("The README undersells the shipped product.")).toBeInTheDocument();
    expect(screen.queryByText(/State: open Labels:/)).not.toBeInTheDocument();
    expect(screen.queryByText("Provider updated")).not.toBeInTheDocument();
    expect(screen.queryByText("Last successful sync")).not.toBeInTheDocument();
  });
});
