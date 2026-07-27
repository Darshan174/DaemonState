import { describe, expect, it } from "vitest";

import {
  ledgerSections,
  sessionContextQualityMessage,
} from "./sessionContinuity";

describe("session context ledger projection", () => {
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

  it("uses user-facing section names", () => {
    const sections = ledgerSections(ledger("one"));

    expect(sections.map((section) => section.label)).toEqual([
      "Original request",
      "Since then",
      "Updated requests",
      "Context gaps",
      "No longer applies",
    ]);
  });
});


describe("session context quality messaging", () => {
  it("names the selected session instead of mislabeling it as the current one", () => {
    expect(sessionContextQualityMessage({
      quality_report: {
        blocking_issues: [{
          message: "Attachment verification failed.",
        }],
      },
    }, "Architecture review Session Context")).toBe(
      "Architecture review Session Context is not copy-ready. Attachment verification failed.",
    );
  });
});

function ledger(id) {
  return {
    schema_version: "session_context.v1",
    provider: "codex",
    session_id: id,
    base: [{ id: "base", text: "Build one card per session", kind: "original_request" }],
    added: [
      { id: "progress", text: "Finished the resume redesign", kind: "progress" },
      { id: "file", text: "frontend/src/pages/SessionLibrary.jsx", kind: "file" },
    ],
    changed: [],
    missing: { status: "unmeasured", items: [], reason: "Provider context is opaque." },
    removed: [],
    compactions: [{ event_id: "compact" }],
  };
}
