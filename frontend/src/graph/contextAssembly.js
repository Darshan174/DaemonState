/**
 * Evidence-backed Context Assembly domain adapter.
 *
 * The backend currently returns models, components, and relationships. This
 * adapter treats components as extracted evidence fragments first, then derives
 * claim/model/readiness structures for the graph UI without changing API shape.
 *
 * @typedef {{ value: number, level: "high" | "medium" | "low", label: string }} Confidence
 * @typedef {{ value: number, missing: string[], label: string }} Completeness
 * @typedef {{ id: string, type: string, url?: string, title: string, timestamp?: string, metadata?: object }} RawSource
 * @typedef {{ id: string, sourceId?: string, sourceType: string, summary: string, confidence: Confidence, stale: boolean, conflict: boolean, status?: string, raw: object }} Fragment
 * @typedef {{ id: string, modelId?: string, text: string, type: string, confidence: Confidence, evidenceIds: string[], status?: string, raw: object }} Claim
 * @typedef {{ id: string, name: string, type: string, status: string, confidence: Confidence, completeness: Completeness, fragments: Fragment[], claims: Claim[], conflicts: Conflict[], missingContext: string[], blockers: Fragment[], suggestedNextAction: string, raw: object }} AssemblyModel
 * @typedef {{ id: string, sourceId: string, targetId: string, label: string, confidence: Confidence, evidence?: string, status: string, origin: string, weak: boolean, verified: boolean, conflict: boolean, raw: object }} AssemblyRelationship
 * @typedef {{ id: string, severity: "high" | "medium" | "low", summary: string, evidenceIds: string[] }} Conflict
 * @typedef {{ rawSources: RawSource[], fragments: Fragment[], claims: Claim[], models: AssemblyModel[], relationships: AssemblyRelationship[], stats: object }} ContextAssembly
 */

export const MODEL_TYPE_META = {
  feature: { label: "Feature", color: "#4f6f8f" },
  bug: { label: "Bug", color: "#9a5f5f" },
  decision: { label: "Decision", color: "#75608f" },
  blocker: { label: "Blocker", color: "#9a7a45" },
  component: { label: "Component", color: "#5f7f6f" },
  release: { label: "Release", color: "#4f7f8a" },
  task: { label: "Task", color: "#64748b" },
  area: { label: "Area", color: "#5f7187" },
};

export const SOURCE_TEXTURE_META = {
  github: { label: "GitHub", pattern: "solid", tone: "#6b7280" },
  slack: { label: "Slack", pattern: "split", tone: "#64748b" },
  gmail: { label: "Gmail", pattern: "stripe", tone: "#64748b" },
  agent: { label: "AI session", pattern: "dot", tone: "#6d6f85" },
  local: { label: "Doc", pattern: "paper", tone: "#71717a" },
  other: { label: "Other", pattern: "plain", tone: "#737373" },
};

const MISSING_CONTEXT_BY_TYPE = {
  feature: ["acceptance criteria", "owner", "current implementation evidence"],
  bug: ["reproduction evidence", "root cause confirmation", "fix verification"],
  decision: ["decision owner", "tradeoff evidence", "reversal criteria"],
  blocker: ["unblock owner", "dependency evidence", "deadline impact"],
  component: ["interface contract", "runtime evidence", "ownership"],
  release: ["scope evidence", "risk signoff", "ship criteria"],
  task: ["owner", "done criteria", "linked decision"],
  area: ["boundary evidence", "source of truth", "active owner"],
};

export function normalizeConfidence(value) {
  const numeric = Number.isFinite(Number(value)) ? Math.max(0, Math.min(1, Number(value))) : 0.58;
  return {
    value: numeric,
    level: numeric >= 0.78 ? "high" : numeric >= 0.52 ? "medium" : "low",
    label: `${Math.round(numeric * 100)}%`,
  };
}

export function sourceKindFromType(sourceType = "", factType = "") {
  const text = `${sourceType} ${factType}`.toLowerCase();
  if (/github|pr|issue|commit|repo/.test(text)) return "github";
  if (/slack|channel|thread/.test(text)) return "slack";
  if (/gmail|email/.test(text)) return "gmail";
  if (/ai|agent|codex|claude|chatgpt|cursor|session/.test(text)) return "agent";
  if (/local|doc|file|markdown|readme/.test(text)) return "local";
  return "other";
}

export function inferModelType(modelName = "", fragments = []) {
  const text = `${modelName} ${fragments.map((f) => `${f.raw?.fact_type || ""} ${f.summary}`).join(" ")}`.toLowerCase();
  if (/bug|fix|defect|regression|oauth|error|failure/.test(text)) return "bug";
  if (/blocker|blocked|risk|hardening|incident/.test(text)) return "blocker";
  if (/decision|decide|chosen|tradeoff/.test(text)) return "decision";
  if (/release|ship|launch|version/.test(text)) return "release";
  if (/component|service|api|frontend|backend|connector|engine/.test(text)) return "component";
  if (/task|todo|action|issue|pr/.test(text)) return "task";
  if (/feature|journey|flow|capability/.test(text)) return "feature";
  return "area";
}

export function fragmentConfidence(component = {}) {
  let value = component.confidence;
  if (value == null && component.authority_weight != null) value = component.authority_weight;
  if (value == null) {
    const status = String(component.status || "").toLowerCase();
    value = status === "needs_review" || status === "proposed" ? 0.46 : 0.62;
  }
  return normalizeConfidence(value);
}

export function isConflictFragment(component = {}) {
  const text = `${component.fact_type || ""} ${component.status || ""} ${component.value || ""} ${component.name || ""}`.toLowerCase();
  return /conflict|contradict|mismatch|disagree|regression/.test(text);
}

export function buildCompleteness({ fragments = [], claims = [], relationships = [], type = "area" }) {
  const evidenceScore = Math.min(0.42, fragments.length * 0.07);
  const claimScore = Math.min(0.28, claims.length * 0.09);
  const relationScore = Math.min(0.18, relationships.length * 0.04);
  const confidenceAvg = fragments.length
    ? fragments.reduce((sum, f) => sum + f.confidence.value, 0) / fragments.length
    : 0.35;
  const confidenceScore = confidenceAvg * 0.12;
  const value = Math.max(0.08, Math.min(1, evidenceScore + claimScore + relationScore + confidenceScore));
  const missing = (MISSING_CONTEXT_BY_TYPE[type] || MISSING_CONTEXT_BY_TYPE.area)
    .slice(0, value > 0.78 ? 1 : value > 0.55 ? 2 : 3);
  return {
    value,
    missing,
    label: `${Math.round(value * 100)}%`,
  };
}

export function relationshipConfidence(relationship = {}) {
  return normalizeConfidence(relationship.confidence ?? (relationship.origin === "deterministic" ? 0.86 : 0.54));
}

export function buildContextHealth({
  sources = 0,
  fragments = 0,
  claims = 0,
  models = 0,
  weakRelationships = 0,
  conflicts = 0,
  missingModels = 0,
  blockedModels = 0,
  averageConfidence = 0,
} = {}) {
  if (!fragments && !models) {
    return {
      status: "empty",
      label: "No context",
      tone: "slate",
      summary: "Add sources to create evidence-backed claims.",
    };
  }

  if (conflicts > 0 || blockedModels > 0) {
    return {
      status: "critical",
      label: "Conflicts",
      tone: "red",
      summary: `${conflicts} conflict${conflicts === 1 ? "" : "s"} · ${blockedModels} blocked model${blockedModels === 1 ? "" : "s"}`,
    };
  }

  if (missingModels > 0 || weakRelationships > 0 || averageConfidence < 58) {
    return {
      status: "review",
      label: "Needs review",
      tone: "amber",
      summary: `${missingModels} gap${missingModels === 1 ? "" : "s"} · ${weakRelationships} weak edge${weakRelationships === 1 ? "" : "s"}`,
    };
  }

  return {
    status: "healthy",
    label: "Grounded",
    tone: "emerald",
    summary: `${sources} source${sources === 1 ? "" : "s"} · ${claims} claim${claims === 1 ? "" : "s"} · ${averageConfidence}% avg confidence`,
  };
}

export function buildContextAssembly(graphData = {}) {
  const components = graphData.components || [];
  const apiModels = graphData.models || [];
  const apiRelationships = graphData.relationships || [];
  const modelNameById = new Map(apiModels.map((m) => [m.id, m.name]));
  const sourceByKey = new Map();

  const fragments = components.map((component) => {
    const sourceType = component.source_type || "unknown";
    const sourceKind = sourceKindFromType(sourceType, component.fact_type);
    const sourceId = component.source_document_id || component.source_external_id || `${sourceType}:${component.id}`;
    if (!sourceByKey.has(sourceId)) {
      sourceByKey.set(sourceId, {
        id: sourceId,
        type: sourceKind,
        url: component.source_url,
        title: component.source_metadata_summary?.title || component.source_external_id || sourceType,
        timestamp: component.ingested_at || component.source_metadata_summary?.created_at,
        metadata: component.source_metadata_summary,
      });
    }
    return {
      id: component.id,
      sourceId,
      sourceType: sourceKind,
      summary: component.display_title || component.name || component.value || "Untitled evidence",
      confidence: fragmentConfidence(component),
      stale: ["stale", "deprecated", "superseded"].includes(String(component.status || "").toLowerCase()) || component.temporal === "past",
      conflict: isConflictFragment(component),
      status: component.status || "active",
      raw: component,
    };
  });

  const fragmentById = new Map(fragments.map((f) => [f.id, f]));
  const relationships = apiRelationships.map((relationship) => {
    const confidence = relationshipConfidence(relationship);
    const origin = relationship.origin || "proposed";
    const label = relationship.display_label || relationship.relationship_type || "related_to";
    const conflict = /conflict|contradict|blocks|blocked/.test(`${label} ${relationship.status || ""}`.toLowerCase());
    return {
      id: relationship.id,
      sourceId: relationship.source_component_id,
      targetId: relationship.target_component_id,
      label: label.replaceAll("_", " "),
      confidence,
      evidence: relationship.evidence,
      status: relationship.status || "active",
      origin,
      weak: confidence.value < 0.62 || ["proposed", "ai_proposed"].includes(origin),
      verified: origin === "human_verified" || relationship.status === "accepted",
      conflict,
      raw: relationship,
    };
  });

  const relationshipByComponent = new Map();
  relationships.forEach((relationship) => {
    [relationship.sourceId, relationship.targetId].forEach((id) => {
      if (!relationshipByComponent.has(id)) relationshipByComponent.set(id, []);
      relationshipByComponent.get(id).push(relationship);
    });
  });

  const claims = components.map((component) => {
    const confidence = fragmentConfidence(component);
    const factType = String(component.fact_type || "claim").replaceAll("_", " ");
    return {
      id: `claim:${component.id}`,
      modelId: component.model_id,
      text: component.display_title || component.name || component.value || "Interpreted claim",
      type: factType,
      confidence,
      evidenceIds: [component.id],
      status: component.status || "active",
      raw: component,
    };
  });

  const fragmentsByModel = new Map();
  const claimsByModel = new Map();
  fragments.forEach((fragment) => {
    const modelId = fragment.raw.model_id || "unmodeled";
    if (!fragmentsByModel.has(modelId)) fragmentsByModel.set(modelId, []);
    fragmentsByModel.get(modelId).push(fragment);
  });
  claims.forEach((claim) => {
    const modelId = claim.modelId || "unmodeled";
    if (!claimsByModel.has(modelId)) claimsByModel.set(modelId, []);
    claimsByModel.get(modelId).push(claim);
  });

  const modelIds = new Set([...apiModels.map((m) => m.id), ...fragmentsByModel.keys()]);
  const models = Array.from(modelIds).map((modelId) => {
    const modelFragments = fragmentsByModel.get(modelId) || [];
    const modelClaims = claimsByModel.get(modelId) || [];
    const modelRelationships = modelFragments.flatMap((f) => relationshipByComponent.get(f.id) || []);
    const name = modelNameById.get(modelId) || "Unmodeled context";
    const type = inferModelType(name, modelFragments);
    const confidenceValue = modelFragments.length
      ? modelFragments.reduce((sum, f) => sum + f.confidence.value, 0) / modelFragments.length
      : 0.45;
    const conflicts = modelFragments.filter((f) => f.conflict).map((f) => ({
      id: `conflict:${f.id}`,
      severity: f.confidence.value > 0.7 ? "high" : "medium",
      summary: f.summary,
      evidenceIds: [f.id],
    }));
    const completeness = buildCompleteness({
      fragments: modelFragments,
      claims: modelClaims,
      relationships: modelRelationships,
      type,
    });
    const blockers = modelFragments.filter((f) => /blocker|risk|blocked/.test(`${f.raw.fact_type || ""} ${f.status}`.toLowerCase()));
    const missingContext = completeness.missing;
    const suggestedNextAction = conflicts.length
      ? "Resolve conflicting evidence before relying on this model."
      : blockers.length
        ? "Review blocker evidence and assign an unblock owner."
        : completeness.value < 0.62
          ? `Add ${missingContext[0] || "supporting evidence"} to raise completeness.`
          : "Verify strongest inferred relationships.";
    return {
      id: modelId,
      name,
      type,
      status: blockers.length ? "blocked" : conflicts.length ? "conflict" : completeness.value < 0.62 ? "needs_review" : "active",
      confidence: normalizeConfidence(confidenceValue),
      completeness,
      fragments: modelFragments,
      claims: modelClaims,
      conflicts,
      missingContext,
      blockers,
      suggestedNextAction,
      raw: apiModels.find((m) => m.id === modelId) || { id: modelId, name },
    };
  });

  const weakRelationships = relationships.filter((r) => r.weak);
  const conflictRelationships = relationships.filter((r) => r.conflict);
  const missingModels = models.filter((m) => m.completeness.value < 0.62);
  const blockedModels = models.filter((m) => m.blockers.length > 0 || m.status === "blocked");
  const averageConfidence = fragments.length
    ? Math.round((fragments.reduce((sum, f) => sum + f.confidence.value, 0) / fragments.length) * 100)
    : 0;
  const stats = {
    sources: sourceByKey.size,
    fragments: fragments.length,
    claims: claims.length,
    models: models.length,
    weakRelationships: weakRelationships.length,
    conflicts: conflictRelationships.length + models.reduce((sum, m) => sum + m.conflicts.length, 0),
    missingModels: missingModels.length,
    blockedModels: blockedModels.length,
    verifiedRelationships: relationships.filter((r) => r.verified).length,
    averageConfidence,
  };

  return {
    rawSources: Array.from(sourceByKey.values()),
    fragments,
    claims,
    models,
    relationships,
    stats: {
      ...stats,
      health: buildContextHealth(stats),
    },
  };
}

export function findAssemblyModelForNode(assembly, node) {
  if (!assembly || !node) return null;
  if (node.type === "model") {
    const rawId = String(node.modelId || node.id || "").replace(/^model:/, "");
    return assembly.models.find((model) => model.id === rawId || `model:${model.id}` === node.id) || null;
  }
  const modelId = node.modelId || node.model_id;
  return assembly.models.find((model) => model.id === modelId) || null;
}

export function findAssemblyFragment(assembly, id) {
  return assembly?.fragments?.find((fragment) => fragment.id === id) || null;
}

export function findAssemblyClaim(assembly, id) {
  return assembly?.claims?.find((claim) => claim.id === id || claim.evidenceIds.includes(id)) || null;
}

export function findAssemblyRelationship(assembly, id) {
  return assembly?.relationships?.find((relationship) => relationship.id === id) || null;
}
