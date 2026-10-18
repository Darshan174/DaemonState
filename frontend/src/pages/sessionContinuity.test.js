import { describe, expect, it } from "vitest";

import {
  contextQualityActivationCopyReady,
  ledgerSections,
  sessionContextAdvisories,
  sessionContextArtifactShapeValid,
  sessionContextOperationState,
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
    expect(sessionContextReadinessLabel(handoff)).toBe("Background available");
    expect(sessionContextAdvisories(handoff)).toEqual([
      "Background is 214 tokens above its optimization target; copying remains available.",
    ]);
  });

  it("reports a real destination overflow without calling the prompt semantically invalid", () => {
    const handoff = readyHandoff({
      efficiency_target: { within_target: true, overflow_tokens: 0 },
      destination_limit: { status: "too_large", overflow_tokens: 91 },
    });

    expect(sessionContextSemanticCopyReady(handoff)).toBe(true);
    expect(sessionContextReadinessLabel(handoff)).toBe("Background available");
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
    expect(sessionContextReadinessLabel(handoff)).toBe("Background available");
    expect(sessionContextAdvisories(handoff)).toContain(
      "Repository snapshot unavailable: recorded session directory is not a Git repository.",
    );
  });

  it.each([
    ["direction_required", "Background available", "does not authorize"],
    ["intent_resolution_required", "Background available", "actionable objective"],
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
    handoff.quality_report.copy_ready = false;

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
  ])("keeps legacy validation closed for $name", ({ mutate }) => {
    const handoff = readyHandoff({
      efficiency_target: { within_target: true },
      destination_limit: { status: "unknown" },
    });
    handoff.schema_version = "session_handoff.v1";
    mutate(handoff);

    expect(sessionContextSemanticCopyReady(handoff)).toBe(false);
    expect(sessionContextReadinessLabel(handoff)).toMatch(
      /Background available · (Review required|Required evidence unavailable)/,
    );
  });

  it.each([
    {
      blocker: "semantic",
      dimensions: {
        semantic_readiness: { copy_ready: false },
        evidence_access: { status: "not_required", blocks_copy: false },
      },
      label: "Background available · Review required",
    },
    {
      blocker: "evidence",
      dimensions: {
        semantic_readiness: { copy_ready: true },
        evidence_access: { status: "unavailable", blocks_copy: true },
      },
      label: "Background available · Required evidence unavailable",
    },
  ])("still fails closed for a $blocker blocker", ({ dimensions, label }) => {
    const handoff = readyHandoff({
      efficiency_target: { within_target: true },
      destination_limit: { status: "unknown" },
    });
    Object.assign(handoff.quality_report, dimensions);
    Object.assign(handoff.readiness_dimensions, dimensions);
    handoff.quality_report.copy_ready = false;

    expect(sessionContextSemanticCopyReady(handoff)).toBe(false);
    expect(sessionContextReadinessLabel(handoff)).toBe(label);
  });

  it.each([
    {
      limitation: "missing objective",
      dimensions: { semantic_readiness: { copy_ready: false } },
      warning: "No current objective was recovered. Add your next instruction.",
      status: "background_with_limitations",
    },
    {
      limitation: "older capture",
      dimensions: {},
      warning: "This capture predates the latest repository changes.",
      status: "background_with_limitations",
    },
    {
      limitation: "missing source evidence",
      dimensions: { evidence_access: { status: "unavailable", blocks_copy: false } },
      warning: "Referenced image is unavailable.",
      status: "evidence_unavailable",
    },
    {
      limitation: "receiver pending",
      dimensions: { receiver_readiness: { status: "materialization_required" } },
      warning: "Referenced image must be attached separately.",
      status: "evidence_pending",
    },
    {
      limitation: "text-only evidence",
      dimensions: { receiver_readiness: { status: "degraded_text_only" } },
      warning: "Only the available text is included.",
      status: "degraded",
    },
  ])("copies canonical background with $limitation when the backend allows it", ({
    dimensions, warning, status,
  }) => {
    const handoff = readyHandoff({});
    handoff.quality_report.status = "ready_with_limitations";
    handoff.quality_report.warnings = [{ message: warning }];
    handoff.operation_capabilities.clipboard_copy.status = "ready_with_limitations";
    Object.assign(handoff.readiness_dimensions, dimensions);

    expect(sessionContextOperationState(handoff)).toMatchObject({
      status,
      clipboardCopyAllowed: true,
      previewAllowed: true,
      tone: "attention",
    });
    expect(sessionContextAdvisories(handoff)).toContain(warning);
    expect(sessionContextQualityMessage(handoff)).toContain("can be copied as background");
    expect(sessionContextQualityMessage(handoff)).toContain(warning);

    handoff.operation_capabilities.clipboard_copy.allowed = false;
    expect(sessionContextSemanticCopyReady(handoff)).toBe(false);
    handoff.operation_capabilities.clipboard_copy.allowed = true;
    handoff.quality_control.copy_allowed = false;
    expect(sessionContextSemanticCopyReady(handoff)).toBe(false);
  });

  it.each([
    ["review", { status: "review_required" }],
    ["rejected", { status: "rejected" }],
    ["quarantined", { status: "quarantined" }],
    ["inactive pointer", { active_candidate_id: "candidate-2" }],
    ["copy denial", { copy_allowed: false }],
    ["unknown schema", { schema_version: "context_quality_activation.v2" }],
    ["missing candidate identity", { candidate_id: "" }],
    ["missing active identity", { active_candidate_id: "" }],
    ["missing observation hash", { observation_sha256: "" }],
  ])("fails closed for a %s quality-control candidate", (_name, override) => {
    const handoff = readyHandoff({
      efficiency_target: { within_target: true },
      destination_limit: { status: "unknown" },
    });
    Object.assign(handoff.quality_control, override);

    expect(handoff.quality_report.copy_ready).toBe(true);
    expect(sessionContextSemanticCopyReady(handoff)).toBe(false);
    expect(sessionContextReadinessLabel(handoff)).toBe(
      "Background available · Review required",
    );
  });

  it("binds activation to the exact rendered artifact hash", () => {
    const handoff = readyHandoff({
      efficiency_target: { within_target: true },
      destination_limit: { status: "unknown" },
    });

    expect(contextQualityActivationCopyReady(
      handoff.quality_control,
      handoff.sha256,
    )).toBe(true);
    handoff.quality_control.artifact_sha256 = "different-artifact";
    expect(sessionContextSemanticCopyReady(handoff)).toBe(false);
  });

  it("keeps receiver-pending evidence previewable without exposing normal copy", () => {
    const handoff = readyHandoff({
      efficiency_target: { within_target: true },
      destination_limit: { status: "unknown" },
    });
    handoff.quality_report.status = "materialization_required";
    handoff.quality_report.copy_ready = false;
    handoff.readiness.status = "materialization_required";
    handoff.readiness_dimensions.evidence_access = {
      status: "materialization_required",
      blocks_copy: true,
      receiver_materialization_required_ids: ["attachment-1"],
    };
    handoff.readiness_dimensions.receiver_readiness = {
      status: "materialization_required",
      required_attachment_ids: ["attachment-1"],
    };
    handoff.operation_capabilities.clipboard_copy = {
      allowed: false,
      status: "materialization_required",
      blocking_issue_codes: [
        "required_evidence_receiver_materialization_required",
      ],
    };

    const operation = sessionContextOperationState(handoff);

    expect(sessionContextArtifactShapeValid(handoff)).toBe(true);
    expect(operation).toMatchObject({
      status: "evidence_pending",
      label: "Background available · Evidence pending",
      tone: "attention",
      previewAllowed: true,
      clipboardCopyAllowed: false,
    });
    expect(sessionContextSemanticCopyReady(handoff)).toBe(false);
    expect(sessionContextQualityMessage(handoff, "Selected Session Context")).toContain(
      "available for preview, but required evidence is not ready for the receiver",
    );
    expect(sessionContextReadinessLabel(handoff)).not.toMatch(/^Ready\b/);
  });

  it.each([
    ["ready_to_send", "Ready to send"],
    ["delivered", "Delivered"],
  ])("reports the receiver %s lifecycle independently from preview", (status, label) => {
    const handoff = readyHandoff({
      efficiency_target: { within_target: true },
      destination_limit: { status: "unknown" },
    });
    handoff.readiness_dimensions.receiver_readiness = {
      status,
      required_attachment_ids: ["attachment-1"],
    };

    expect(sessionContextOperationState(handoff)).toMatchObject({
      status,
      label,
      tone: "success",
      previewAllowed: true,
      clipboardCopyAllowed: true,
    });
  });

  it.each([
    ["operation capabilities", (handoff) => delete handoff.operation_capabilities, "unavailable"],
    ["quality activation", (handoff) => delete handoff.quality_control, "review_required"],
  ])("fails canonical operation permissions closed without %s", (_name, mutate, status) => {
    const handoff = readyHandoff({
      efficiency_target: { within_target: true },
      destination_limit: { status: "unknown" },
    });
    mutate(handoff);

    expect(sessionContextOperationState(handoff)).toMatchObject({
      status,
      previewAllowed: status !== "unavailable",
      clipboardCopyAllowed: false,
    });
  });

  it("accepts the legacy handoff contract only through the migration fallback", () => {
    const handoff = readyHandoff({
      efficiency_target: { within_target: true },
      destination_limit: { status: "unknown" },
    });
    handoff.schema_version = "session_handoff.v1";
    delete handoff.compatibility;
    delete handoff.operation_capabilities;
    delete handoff.quality_control;

    expect(sessionContextArtifactShapeValid(handoff)).toBe(true);
    expect(sessionContextOperationState(handoff)).toMatchObject({
      status: "background_available",
      previewAllowed: true,
      clipboardCopyAllowed: true,
    });
  });
});

function readyHandoff(budgetFit) {
  const artifactSha256 = "b".repeat(64);
  const dimensions = {
    semantic_readiness: { copy_ready: true },
    evidence_access: { status: "not_required", blocks_copy: false },
    budget_fit: budgetFit,
  };
  return {
    schema_version: "session_background.v1",
    compatibility: { legacy_schema_version: "session_handoff.v1" },
    scope: "session",
    provider: "codex",
    session_id: "session-1",
    checkpoint_id: "checkpoint-1",
    boundary: { event_id: "event-1", sequence_number: 1 },
    content: "# Continuation Brief v2",
    sha256: artifactSha256,
    quality_control: {
      schema_version: "context_quality_activation.v1",
      status: "active",
      copy_allowed: true,
      candidate_id: "candidate-1",
      active_candidate_id: "candidate-1",
      observation_sha256: "a".repeat(64),
      artifact_sha256: artifactSha256,
      semantic_sha256: "c".repeat(64),
      evaluation_id: "evaluation-1",
      pointer_generation: 1,
      decision: "promote",
      policy_version: "context_quality_policy.v1",
    },
    render_variant: "compact_v2",
    readiness: { status: "execution_ready" },
    readiness_dimensions: dimensions,
    operation_capabilities: {
      preview: { allowed: true, status: "ready" },
      clipboard_copy: { allowed: true, status: "ready" },
      automatic_execution: { allowed: false, status: "not_applicable" },
    },
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
