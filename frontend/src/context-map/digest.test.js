import { describe, expect, it } from "vitest";

import { buildEvidenceGraph, buildSessionKnowledgeMap, cardDisplayText, cleanDisplayText, sessionTopic } from "./digest";

function card(overrides) {
  return {
    id: overrides.id || "card-1",
    title: overrides.title || "Decision: Keep FastAPI auth path",
    summary: overrides.summary || "Keep the FastAPI auth path for OAuth because it matches the existing backend contract and current tests.",
    type: overrides.type || "decision",
    category: overrides.category || "decision",
    status: overrides.status || "active",
    attention_score: overrides.attention_score ?? 50,
    provenance: overrides.provenance || [],
    ...overrides,
  };
}

describe("context digest adapter", () => {
  it("returns full readable text for expanded digest cards", () => {
    const item = card({
      summary: "Decision: keep the FastAPI auth path for OAuth because it matches the existing backend contract and current test coverage.",
    });

    expect(cardDisplayText(item, "decision")).toBe(
      "keep the FastAPI auth path for OAuth because it matches the existing backend contract and current test coverage",
    );
  });

  it("filters tool instructions, media payloads, and bare doc paths from digest groups", () => {
    const digest = buildSessionKnowledgeMap({
      cards: [
        card({ id: "valid-decision" }),
        card({
          id: "instruction-noise",
          title: "Decision: base_instructions",
          summary: "developer instructions require request escalation and prefix_rule handling.",
          type: "decision",
          attention_score: 100,
        }),
        card({
          id: "media-noise",
          title: "Blocker: screenshot",
          summary: `data:image/png;base64,${"A".repeat(220)}`,
          type: "blocker",
          category: "blocker",
          status: "blocked",
          attention_score: 90,
        }),
        card({
          id: "bare-doc-path",
          title: "File: docs/runbook.md",
          summary: "docs/runbook.md",
          type: "file",
          category: "supporting_evidence",
          attention_score: 80,
        }),
        card({
          id: "broken-doc",
          title: "File: docs/runbook.md",
          summary: "Runbook docs are stale and missing the OAuth callback setup steps.",
          type: "file",
          category: "document_finding",
          status: "needs_review",
          attention_score: 70,
        }),
      ],
    });

    expect(digest.decisions.map((item) => item.id)).toEqual(["valid-decision"]);
    expect(digest.blockers).toEqual([]);
    expect(digest.brokenDocs.map((item) => item.id)).toEqual(["broken-doc"]);
  });

  it("uses backend categories instead of PR, issue, and blocker keywords", () => {
    const digest = buildSessionKnowledgeMap({
      cards: [
        card({
          id: "lookalike",
          category: "supporting_evidence",
          type: "task",
          title: "PR #12 blocked by broken docs",
          summary: "Issue #12 mentions a blocker and stale README text.",
          provenance: [{ source_url: "https://github.com/acme/repo/pull/12" }],
        }),
        card({
          id: "typed-pr",
          category: "pull_request",
          type: "task",
          title: "Graph truth repair",
          summary: "Repairs graph truth metadata and rendering.",
          remote_item: { repository: "acme/repo", number: 67, observed_status: "open" },
        }),
      ],
    });

    expect(digest.prs.map((item) => item.id)).toEqual(["typed-pr"]);
    expect(digest.issues).toEqual([]);
    expect(digest.blockers).toEqual([]);
    expect(digest.brokenDocs).toEqual([]);
  });

  it("renders one session root per imported source", () => {
    const source = { source_document_id: "source-1", source_label: "Codex session" };
    const digest = buildSessionKnowledgeMap({
      cards: [
        card({ id: "root", category: "agent_session", type: "agent_session", provenance: [source], session: { session_id: "abc", tool: "codex" } }),
        card({ id: "duplicate-root", category: "agent_session", type: "agent_session", provenance: [source], session: { session_id: "abc", tool: "codex" } }),
        card({ id: "file", category: "supporting_evidence", type: "file", provenance: [source], title: "File: app.py", summary: "Referenced app.py in the session." }),
      ],
    });

    expect(digest.aiSessions.map((item) => item.id)).toEqual(["root"]);
  });

  it("derives a useful topic for every session while ignoring injected setup text", () => {
    const item = card({
      category: "agent_session",
      type: "agent_session",
      session: { session_id: "019ed6a2-ce45-7b40-8454-23ec87df0edf", tool: "codex", title: "Codex session · 23ec87df0edf" },
      summary: [
        "[USER]",
        "## request_user_input availability",
        "Use the request_user_input tool only when listed.",
        "[USER]",
        "/goal make this project a oss sucess, a highly used tool for vibe coders.",
      ].join("\n"),
    });

    expect(sessionTopic(item)).toBe("Make this project an OSS success");
  });

  it("cleans punctuation-only prefixes and media residue", () => {
    expect(cleanDisplayText("./ Decision: ship the digest board")).toBe("ship the digest board");
    expect(cleanDisplayText(`Blocker: data:image/png;base64,${"B".repeat(200)} OAuth docs are missing`)).toBe(
      "OAuth docs are missing",
    );
  });

  it("projects typed records into stable graph lanes and preserves only visible links", () => {
    const source = card({ id: "source", category: "agent_session", type: "agent_session" });
    const decision = card({ id: "decision", category: "decision", type: "decision" });
    const delivery = card({ id: "delivery", category: "pull_request", type: "source" });
    const blocker = card({ id: "blocker", category: "blocker", type: "blocker" });
    const projection = buildEvidenceGraph({
      cards: [source, decision, delivery, blocker],
      links: [
        { id: "visible", source_card_id: "decision", target_card_id: "delivery", relationship_type: "enables" },
        { id: "missing-target", source_card_id: "delivery", target_card_id: "missing", relationship_type: "blocks" },
      ],
    });

    expect(Object.fromEntries(projection.nodes.map((node) => [node.id, node.laneId]))).toEqual({
      decision: "decisions",
      delivery: "prs",
      source: "sessions",
      blocker: "issues",
    });
    expect(projection.edges.map((edge) => edge.id)).toEqual(["visible"]);
  });

  it("applies the visual node budget per lane so one category cannot crowd out another", () => {
    const cards = [
      ...Array.from({ length: 6 }, (_, index) => card({ id: `decision-${index}`, attention_score: 100 - index })),
      card({ id: "session", category: "agent_session", type: "agent_session" }),
      card({ id: "blocker", category: "blocker", type: "blocker" }),
    ];
    const projection = buildEvidenceGraph({
      cards,
      links: [{ id: "link", source_card_id: "decision-0", target_card_id: "blocker", relationship_type: "blocked_by" }],
    }, { limitPerLane: 2 });

    expect(projection.nodes.map((node) => node.id).sort()).toEqual(["blocker", "decision-0", "decision-1", "session"]);
    expect(projection.hiddenCardCount).toBe(4);
    expect(projection.edges).toHaveLength(1);
  });

  it("never promotes supporting evidence into named lanes from its legacy type", () => {
    const projection = buildEvidenceGraph({
      cards: [
        card({ id: "supporting-decision", category: "supporting_evidence", type: "decision" }),
        card({ id: "supporting-task", category: "supporting_evidence", type: "task" }),
        card({ id: "supporting-file", category: "supporting_evidence", type: "file" }),
      ],
    });

    expect(projection.nodes.map((node) => [node.id, node.laneId])).toEqual([
      ["supporting-decision", "other"],
      ["supporting-task", "other"],
      ["supporting-file", "other"],
    ]);
  });
});
