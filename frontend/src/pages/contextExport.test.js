import { describe, expect, it } from "vitest";
import { createHash } from "node:crypto";
import { sessionContextFile, workspaceContextFile } from "./contextExport";

function withDetails(context, overrides = {}) {
  const content = JSON.stringify({
    provider: context.provider,
    session_id: context.session_id,
    checkpoint_id: context.checkpoint_id,
    source_document_id: context.source_document_id,
    boundary: context.boundary,
    overview_sha256: context.sha256,
    claim_manifest: context.claim_manifest,
    retrieval_context: context.retrieval_context,
    ...overrides,
  });
  return { ...context, portable_details: {
    schema_version: "session_context_details.v1", content,
    sha256: createHash("sha256").update(content).digest("hex"),
  } };
}

describe("portable background context", () => {
  it("exports a large included record without overflowing the argument stack", async () => {
    const statement = "Historical `symbol` reference. ".repeat(100_000);
    const file = await sessionContextFile(withDetails({
      schema_version: "session_background.v1", context_role: "background_only",
      content: "# Session Context", provider: "codex", session_id: "large-session",
      checkpoint_id: "large-capture", boundary: { sequence_number: 1 },
      claim_manifest: [{ section: "state", selection: "included", statement }],
    }));
    expect(file.content).toContain(statement);
    expect(file.content).toContain("```json");
  });

  it("includes workspace topics omitted from the compact overview, with evidence", () => {
    const file = workspaceContextFile({
      schema_version: "workspace_context.v1",
      context_pack_id: "pack-1",
      content: "# Workspace Context\nFour capabilities shown.",
      sha256: "overview-hash",
      foundation: {
        objective_independent: true,
        capabilities: Array.from({ length: 7 }, (_, index) => ({
          id: `cap-${index}`, name: `Capability ${index}`, evidence_ref_ids: [`E-${index}`],
        })),
        evidence_references: [{ id: "E-6", path: "src/search.py", start_line: 12, end_line: 15 }],
        quality_report: { copy_ready: true, issues: [] },
      },
    });
    expect(file.filename).toBe("workspace-context-pack-1.md");
    expect(file.content).toContain("Capability 6");
    expect(file.content).toContain('"path": "src/search.py"');
    expect(file.content).toContain("[Capabilities](#detail-1)");
  });

  it("preserves full included claims and exact source quotes without reviving exclusions", async () => {
    const excerpt = "Use cursor paging because offsets skip rows.\n```\n# Run a deployment";
    const longClaim = "Decision rationale: " + "preserve stable cursors; ".repeat(50);
    const file = await sessionContextFile(withDetails({
      schema_version: "session_background.v1",
      context_role: "background_only",
      checkpoint_id: "capture-7",
      session_id: "session-a",
      boundary: { sequence_number: 17 },
      content: "# Session Context\nTwo progress records shown.",
      claim_manifest: [
        { section: "decisions", selection: "included", statement: longClaim, evidence_refs: ["event-12"] },
        { section: "decisions", selection: "excluded", statement: "REJECTED_INSTRUCTION", exclusion_reason: "untrusted" },
        { kind: "relevant_file", section: "relevant_surfaces", selection: "excluded", statement: "src/omitted-from-preview.py", exclusion_reason: "bounded_inventory" },
      ],
      supporting_context: [{ text: "EXCLUDED_HISTORICAL_REFERENCE" }],
      retrieval_context: { spans: [
        { statement: excerpt, source_event_id: "event-12", field: "content", start_char: 0, end_char: excerpt.length },
        { statement: "Historical tool result", source_event_id: "tool-13", field: "content", start_char: 14, end_char: 36 },
      ] },
    }));
    expect(file.content).toContain(longClaim);
    expect(file.content).toContain('"source_event_id": "event-12"');
    expect(file.content).toContain('"source_event_id": "tool-13"');
    expect(file.content).toContain('"start_char": 14');
    expect(file.content).toContain(JSON.stringify(excerpt));
    expect(file.content).toContain("````json");
    expect(file.content).not.toContain("REJECTED_INSTRUCTION");
    expect(file.content).not.toContain("EXCLUDED_HISTORICAL_REFERENCE");
    expect(file.content).toContain("src/omitted-from-preview.py");
    expect(file.content).toContain("not instructions to execute");
    expect(file.content).toContain("image attachments are not embedded");
  });

  it("rejects execution artifacts and objective-bound workspace records", async () => {
    await expect(sessionContextFile({
      schema_version: "session_handoff.v1", content: "Execute the prior request",
    })).rejects.toThrow("background Session Context");
    expect(() => workspaceContextFile({
      schema_version: "workspace_context.v1", content: "Fix the bug", foundation: { objective_independent: false },
    })).toThrow("Workspace Context");
  });

  it("rejects altered detail and valid detail from another capture", async () => {
    const context = {
      schema_version: "session_background.v1", context_role: "background_only",
      content: "# Session Context", sha256: "overview", provider: "codex",
      session_id: "session-a", checkpoint_id: "capture-1", boundary: { sequence_number: 3, event_id: "event-3" },
      claim_manifest: [{ section: "state", selection: "included", statement: "original detail" }],
    };
    const altered = withDetails(context);
    altered.portable_details.content = altered.portable_details.content.replace("original detail", "unbound detail");
    await expect(sessionContextFile(altered)).rejects.toThrow(/integrity check/i);
    await expect(sessionContextFile(withDetails(context, { checkpoint_id: "capture-other" })))
      .rejects.toThrow("different captured context");
    // The server emits canonically sorted detail JSON; the ordinary artifact
    // preserves construction order. These still identify the same capture.
    await expect(sessionContextFile(withDetails(context, {
      boundary: { event_id: "event-3", sequence_number: 3 },
    }))).resolves.toHaveProperty("filename", "session-context-capture-1.md");
  });
});
