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
    fireEvent.click(screen.getByRole("button", { name: "Evidence" }));

    await waitFor(() => expect(api.get).toHaveBeenCalledWith(
      "/sources/source-1?workspace_id=00000000-0000-0000-0000-000000000001",
    ));
    expect(await screen.findByText(/Make the graph factual/)).toBeInTheDocument();
  });
});
