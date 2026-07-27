import { describe, expect, it } from "vitest";

import {
  buildSessionContinuity,
  ledgerSections,
  sessionSearchText,
} from "./sessionContinuity";

describe("session continuity projection", () => {
  it("creates exactly one card per agent session without cross-session collapse", () => {
    const cards = buildSessionContinuity({
      sessions: [
        session("one", "Same task"),
        session("two", "Same task"),
      ],
      ledgers: [
        ledger("one"),
        ledger("two"),
      ],
    });

    expect(cards).toHaveLength(2);
    expect(cards.map((card) => card.sessionId).sort()).toEqual(["one", "two"]);
  });

  it("does not recreate a card from a ledger absent from the scoped Library", () => {
    const cards = buildSessionContinuity({
      sessions: [session("one", "Selected project")],
      ledgers: [
        ledger("one"),
        ledger("outside-project"),
      ],
    });

    expect(cards).toHaveLength(1);
    expect(cards[0].sessionId).toBe("one");
  });

  it("keeps the newest boundary instead of falling back to an older task", () => {
    const cards = buildSessionContinuity({
      sessions: [session("one", "Resume redesign")],
      ledgers: [ledger("one")],
      checkpoints: [
        checkpoint("old", "one", 10, "complete"),
        checkpoint("new", "one", 20, "incomplete"),
      ],
    });

    expect(cards[0].checkpoint.id).toBe("new");
    expect(cards[0].checkpoint.capture_status).toBe("incomplete");
    expect(cards[0].versions.map((value) => value.id)).toEqual(["new", "old"]);
  });

  it("presents an unmeasured compaction gap as Unknown instead of a false zero", () => {
    const [missing] = ledgerSections(ledger("one"))
      .filter((section) => section.key === "missing");

    expect(missing.count).toBeNull();
    expect(missing.status).toBe("unmeasured");
    expect(missing.label).toBe("Context gaps");
    expect(missing.statusLabel).toBe("Unknown");
    expect(missing.items).toEqual([]);
  });

  it("plainly says when there was no compaction", () => {
    const source = ledger("one");
    source.missing.status = "not_applicable";
    const [gaps] = ledgerSections(source)
      .filter((section) => section.key === "missing");

    expect(gaps.statusLabel).toBe("No compaction");
  });

  it("uses user-facing section names and keeps raw file paths out of search", () => {
    const [card] = buildSessionContinuity({
      sessions: [session("one", "Resume redesign")],
      ledgers: [ledger("one")],
    });
    const sections = ledgerSections(card.ledger);

    expect(sessionSearchText(card)).toContain("one card per session");
    expect(sessionSearchText(card)).toContain("finished the resume redesign");
    expect(sessionSearchText(card)).not.toContain("runspage.jsx");
    expect(sections.map((section) => section.label)).toEqual([
      "Original request",
      "Since then",
      "Updated requests",
      "Context gaps",
      "No longer applies",
    ]);
  });
});

function session(id, title) {
  return {
    id: `codex:${id}`,
    connector_type: "codex",
    harness: "Codex",
    session_id: id,
    source_document_id: `document-${id}`,
    title,
    updated_at: `2026-07-21T10:0${id === "one" ? 1 : 2}:00Z`,
    live: true,
    compaction_checkpoints: [{ id: `compact-${id}` }],
  };
}

function ledger(id) {
  return {
    schema_version: "session_context.v1",
    provider: "codex",
    session_id: id,
    base: [{ id: "base", text: "Build one card per session", kind: "original_request" }],
    added: [
      { id: "progress", text: "Finished the resume redesign", kind: "progress" },
      { id: "file", text: "frontend/src/pages/RunsPage.jsx", kind: "file" },
    ],
    changed: [],
    missing: { status: "unmeasured", items: [], reason: "Provider context is opaque." },
    removed: [],
    compactions: [{ event_id: "compact" }],
  };
}

function checkpoint(id, sessionId, sequence, captureStatus) {
  return {
    id,
    provider: "codex",
    session_id: sessionId,
    capture_status: captureStatus,
    projection: { valid: true },
    created_at: `2026-07-21T10:${sequence}:00Z`,
    boundary: { sequence_number: sequence },
    sections: {
      goal: [{ statement: "Resume redesign" }],
      exact_next_action: [{ statement: captureStatus === "complete" ? "Run tests" : "" }],
    },
  };
}
