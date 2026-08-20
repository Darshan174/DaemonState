import { describe, expect, it } from "vitest";

import {
  ledgerSections,
  sessionContextAdvisories,
  sessionContextQualityMessage,
  sessionContextReadinessLabel,
  sessionContextSemanticCopyReady,
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

  it("keeps generated-overhead advisories separate from semantic copy safety", () => {
    const handoff = readyHandoff({
      efficiency_target: {
        within_target: false,
        overflow_tokens: 214,
      },
      destination_limit: { status: "unknown" },
    });

    expect(sessionContextSemanticCopyReady(handoff)).toBe(true);
    expect(sessionContextReadinessLabel(handoff)).toBe("Ready · Compacted");
    expect(sessionContextAdvisories(handoff)).toEqual([
      "Generated context is 214 tokens above its optimization target; copying remains available.",
    ]);
  });

  it("reports a real destination overflow without calling the prompt semantically invalid", () => {
    const handoff = readyHandoff({
      efficiency_target: { within_target: true, overflow_tokens: 0 },
      destination_limit: { status: "too_large", overflow_tokens: 91 },
    });

    expect(sessionContextSemanticCopyReady(handoff)).toBe(true);
    expect(sessionContextReadinessLabel(handoff)).toBe(
      "Copy-ready · Over destination limit",
    );
    expect(sessionContextAdvisories(handoff)[0]).toContain(
      "91 tokens above the selected destination limit; manual copying remains available",
    );
  });

  it("keeps a no-Git workspace copyable and explains the missing snapshot", () => {
    const handoff = readyHandoff({
      efficiency_target: { within_target: true, overflow_tokens: 0 },
      destination_limit: { status: "unknown" },
    });
    handoff.readiness.status = "discovery_required";
    const evidence = {
      status: "not_required",
      blocks_copy: false,
      repository_snapshot: {
        source_available: false,
        selection_required: false,
        message: (
          "Repository snapshot unavailable: recorded session directory is not a Git repository."
        ),
      },
    };
    handoff.readiness_dimensions.evidence_access = evidence;
    handoff.quality_report.evidence_access = evidence;

    expect(sessionContextSemanticCopyReady(handoff)).toBe(true);
    expect(sessionContextReadinessLabel(handoff)).toBe("Discovery brief ready");
    expect(sessionContextAdvisories(handoff)).toContain(
      "Repository snapshot unavailable: recorded session directory is not a Git repository.",
    );
  });

  it.each([
    ["direction_required", "Context ready · Direction required", "does not authorize"],
    ["intent_resolution_required", "Context ready · Intent required", "actionable objective"],
  ])(
    "keeps %s context copyable while exposing the stop state",
    (status, label, advisoryText) => {
      const handoff = readyHandoff({
        efficiency_target: { within_target: true, overflow_tokens: 0 },
        destination_limit: { status: "too_large", overflow_tokens: 91 },
      });
      handoff.readiness.status = status;

      expect(sessionContextSemanticCopyReady(handoff)).toBe(true);
      expect(sessionContextReadinessLabel(handoff)).toBe(label);
      expect(sessionContextAdvisories(handoff)[0]).toContain(advisoryText);
    },
  );

  it("labels an unresolved multi-repository choice explicitly", () => {
    const handoff = readyHandoff({
      efficiency_target: { within_target: true },
      destination_limit: { status: "unknown" },
    });
    const evidence = {
      status: "selection_required",
      blocks_copy: true,
      repository_snapshot: { selection_required: true },
    };
    handoff.readiness_dimensions.evidence_access = evidence;
    handoff.quality_report.evidence_access = evidence;

    expect(sessionContextSemanticCopyReady(handoff)).toBe(false);
    expect(sessionContextReadinessLabel(handoff)).toBe(
      "Repository selection required",
    );
  });

  it.each([
    {
      name: "missing readiness dimensions",
      mutate: (handoff) => {
        delete handoff.readiness_dimensions;
        delete handoff.quality_report.semantic_readiness;
        delete handoff.quality_report.evidence_access;
      },
    },
    {
      name: "malformed canonical dimensions",
      mutate: (handoff) => {
        handoff.readiness_dimensions = "ready";
      },
    },
    {
      name: "partial unavailable evidence verdict",
      mutate: (handoff) => {
        handoff.readiness_dimensions.evidence_access = { status: "unavailable" };
      },
    },
  ])("fails closed for $name", ({ mutate }) => {
    const handoff = readyHandoff({
      efficiency_target: { within_target: true },
      destination_limit: { status: "unknown" },
    });
    mutate(handoff);

    expect(sessionContextSemanticCopyReady(handoff)).toBe(false);
    expect(sessionContextReadinessLabel(handoff)).toMatch(
      /Needs clarification|Required evidence unavailable/,
    );
  });

  it.each([
    {
      blocker: "semantic",
      dimensions: {
        semantic_readiness: { copy_ready: false },
        evidence_access: { status: "not_required", blocks_copy: false },
      },
      label: "Needs clarification",
    },
    {
      blocker: "evidence",
      dimensions: {
        semantic_readiness: { copy_ready: true },
        evidence_access: { status: "unavailable", blocks_copy: true },
      },
      label: "Required evidence unavailable",
    },
  ])("still fails closed for a $blocker blocker", ({ dimensions, label }) => {
    const handoff = readyHandoff({
      efficiency_target: { within_target: true },
      destination_limit: { status: "unknown" },
    });
    Object.assign(handoff.quality_report, dimensions);
    Object.assign(handoff.readiness_dimensions, dimensions);

    expect(sessionContextSemanticCopyReady(handoff)).toBe(false);
    expect(sessionContextReadinessLabel(handoff)).toBe(label);
  });
});

function readyHandoff(budgetFit) {
  const dimensions = {
    semantic_readiness: { copy_ready: true },
    evidence_access: { status: "not_required", blocks_copy: false },
    budget_fit: budgetFit,
  };
  return {
    content: "# Continuation Brief v2",
    render_variant: "compact_v2",
    readiness: { status: "execution_ready" },
    readiness_dimensions: dimensions,
    token_accounting: {
      ...budgetFit,
      blocks_automatic_delivery: budgetFit?.destination_limit?.status === "too_large",
    },
    advisories: [],
    delivery: { mode: "direct_copy", ready_for_target: true },
    quality_report: {
      copy_ready: true,
      ...dimensions,
    },
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
      { id: "file", text: "frontend/src/pages/SessionLibrary.jsx", kind: "file" },
    ],
    changed: [],
    missing: { status: "unmeasured", items: [], reason: "Provider context is opaque." },
    removed: [],
    compactions: [{ event_id: "compact" }],
  };
}
