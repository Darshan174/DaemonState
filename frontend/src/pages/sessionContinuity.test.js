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

  it("joins the newest usable saved version to its session", () => {
    const cards = buildSessionContinuity({
      sessions: [session("one", "Resume redesign")],
      ledgers: [ledger("one")],
      checkpoints: [
        checkpoint("old", "one", 10, "complete"),
        checkpoint("new", "one", 20, "incomplete"),
      ],
    });

    expect(cards[0].checkpoint.id).toBe("old");
    expect(cards[0].versions.map((value) => value.id)).toEqual(["new", "old"]);
  });

  it("keeps Missing explicitly unmeasured instead of presenting a false zero", () => {
    const [missing] = ledgerSections(ledger("one"))
      .filter((section) => section.key === "missing");

    expect(missing.count).toBeNull();
    expect(missing.status).toBe("unmeasured");
    expect(missing.items).toEqual([]);
  });

  it("searches across the session title and ledger details", () => {
    const [card] = buildSessionContinuity({
      sessions: [session("one", "Resume redesign")],
      ledgers: [ledger("one")],
    });

    expect(sessionSearchText(card)).toContain("one card per session");
    expect(sessionSearchText(card)).toContain("runspage.jsx");
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
    added: [{ id: "file", text: "frontend/src/pages/RunsPage.jsx", kind: "file" }],
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
