import { describe, expect, it } from "vitest";
import {
  buildContextHealth,
  buildContextAssembly,
  inferModelType,
  normalizeConfidence,
  sourceKindFromType,
} from "./contextAssembly";

describe("context assembly domain adapter", () => {
  it("normalizes confidence into product-facing levels", () => {
    expect(normalizeConfidence(0.82)).toMatchObject({ level: "high", label: "82%" });
    expect(normalizeConfidence(0.41)).toMatchObject({ level: "low", label: "41%" });
  });

  it("detects source kinds from source and fact types", () => {
    expect(sourceKindFromType("github_pr", "changed_file")).toBe("github");
    expect(sourceKindFromType("ai_session", "decision")).toBe("agent");
    expect(sourceKindFromType("slack_message", "blocker")).toBe("slack");
  });

  it("infers model types from model names and evidence", () => {
    expect(inferModelType("OAuth redirect fix", [])).toBe("bug");
    expect(inferModelType("Release readiness", [])).toBe("release");
    expect(inferModelType("Decision log", [])).toBe("decision");
  });

  it("summarizes context health from gaps and conflicts", () => {
    expect(buildContextHealth({ fragments: 0, models: 0 })).toMatchObject({
      status: "empty",
      label: "No context",
    });
    expect(buildContextHealth({ fragments: 4, models: 2, conflicts: 1 })).toMatchObject({
      status: "critical",
      tone: "red",
    });
    expect(buildContextHealth({ fragments: 8, models: 2, missingModels: 1, weakRelationships: 3, averageConfidence: 63 })).toMatchObject({
      status: "review",
      label: "Needs review",
    });
    expect(buildContextHealth({ sources: 2, fragments: 8, claims: 8, models: 2, averageConfidence: 81 })).toMatchObject({
      status: "healthy",
      tone: "emerald",
    });
  });

  it("builds evidence-backed models from graph API data", () => {
    const assembly = buildContextAssembly({
      models: [{ id: "m1", name: "GitHub OAuth Fix" }],
      components: [
        {
          id: "c1",
          model_id: "m1",
          name: "OAuth redirect issue found",
          fact_type: "bug",
          source_type: "ai_session",
          source_document_id: "doc1",
          confidence: 0.82,
          status: "active",
        },
        {
          id: "c2",
          model_id: "m1",
          name: "Slack report conflicts with PR",
          fact_type: "conflict",
          source_type: "slack",
          source_document_id: "doc2",
          confidence: 0.66,
          status: "needs_review",
        },
      ],
      relationships: [
        {
          id: "r1",
          source_component_id: "c1",
          target_component_id: "c2",
          relationship_type: "caused_by",
          confidence: 0.57,
          origin: "ai_proposed",
          evidence: "Codex session and Slack thread mention redirect mismatch.",
        },
      ],
    });

    expect(assembly.rawSources).toHaveLength(2);
    expect(assembly.fragments).toHaveLength(2);
    expect(assembly.claims).toHaveLength(2);
    expect(assembly.models).toHaveLength(1);
    expect(assembly.models[0]).toMatchObject({
      id: "m1",
      name: "GitHub OAuth Fix",
      type: "bug",
      status: "conflict",
    });
    expect(assembly.models[0].conflicts).toHaveLength(1);
    expect(assembly.relationships[0]).toMatchObject({ weak: true, label: "caused by" });
    expect(assembly.stats).toMatchObject({
      sources: 2,
      fragments: 2,
      claims: 2,
      models: 1,
      weakRelationships: 1,
      health: expect.objectContaining({ status: "critical" }),
    });
  });
});
