import { describe, expect, it } from "vitest";

import { buildSessionKnowledgeMap, cardDisplayText, cleanDisplayText } from "./digest";

function card(overrides) {
  return {
    id: overrides.id || "card-1",
    title: overrides.title || "Decision: Keep FastAPI auth path",
    summary: overrides.summary || "Keep the FastAPI auth path for OAuth because it matches the existing backend contract and current tests.",
    type: overrides.type || "decision",
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
          status: "blocked",
          attention_score: 90,
        }),
        card({
          id: "bare-doc-path",
          title: "File: docs/runbook.md",
          summary: "docs/runbook.md",
          type: "file",
          attention_score: 80,
        }),
        card({
          id: "broken-doc",
          title: "File: docs/runbook.md",
          summary: "Runbook docs are stale and missing the OAuth callback setup steps.",
          type: "file",
          status: "needs_review",
          attention_score: 70,
        }),
      ],
    });

    expect(digest.decisions.map((item) => item.id)).toEqual(["valid-decision"]);
    expect(digest.blockers).toEqual([]);
    expect(digest.brokenDocs.map((item) => item.id)).toEqual(["broken-doc"]);
  });

  it("cleans punctuation-only prefixes and media residue", () => {
    expect(cleanDisplayText("./ Decision: ship the digest board")).toBe("ship the digest board");
    expect(cleanDisplayText(`Blocker: data:image/png;base64,${"B".repeat(200)} OAuth docs are missing`)).toBe(
      "OAuth docs are missing",
    );
  });
});
