export async function copyReadySessionContextContent(handoff, expected = {}) {
  if (
    handoff?.schema_version !== "session_handoff.v1"
    || handoff.scope !== "session"
    || typeof handoff.provider !== "string"
    || !handoff.provider.trim()
    || typeof handoff.session_id !== "string"
    || !handoff.session_id.trim()
    || typeof handoff.content !== "string"
    || !handoff.content.trim()
    || typeof handoff.sha256 !== "string"
    || !handoff.sha256.trim()
    || !handoff.checkpoint_id
    || typeof handoff.boundary !== "object"
    || handoff.boundary === null
    || !handoff.boundary.event_id
    || !Number.isInteger(handoff.boundary.sequence_number)
    || typeof handoff.quality_report !== "object"
    || handoff.quality_report === null
    || typeof handoff.quality_report.copy_ready !== "boolean"
  ) {
    throw new Error(
      "The checkpoint service returned an incomplete Current Session Context.",
    );
  }
  if (!sessionContextSemanticCopyReady(handoff)) {
    throw new Error(sessionContextQualityMessage(handoff));
  }
  if (
    expected.provider
    && normalizeProvider(handoff.provider) !== normalizeProvider(expected.provider)
  ) {
    throw new Error("Current Session Context belongs to a different harness.");
  }
  if (
    expected.sessionId
    && cleanText(handoff.session_id) !== cleanText(expected.sessionId)
  ) {
    throw new Error("Current Session Context belongs to a different session.");
  }
  if (
    expected.checkpointId
    && cleanText(handoff.checkpoint_id) !== cleanText(expected.checkpointId)
  ) {
    throw new Error("Current Session Context belongs to a different checkpoint.");
  }
  if (
    Number.isInteger(expected.boundarySequence)
    && handoff.boundary.sequence_number !== expected.boundarySequence
  ) {
    throw new Error("Current Session Context belongs to a different session boundary.");
  }
  await requireMatchingContentSha256(
    handoff.content,
    handoff.sha256,
    "Current Session Context",
  );
  return handoff.content;
}

export function sessionContextSemanticCopyReady(handoff) {
  const report = handoff?.quality_report;
  const dimensions = sessionContextReadinessDimensions(handoff);
  const semantic = dimensions?.semantic_readiness;
  const evidence = dimensions?.evidence_access;
  return Boolean(
    report?.copy_ready === true
    && isRecord(semantic)
    && semantic.copy_ready === true
    && isRecord(evidence)
    && evidence.blocks_copy === false
  );
}

export function sessionContextReadinessLabel(handoff) {
  if (!handoff?.content) return "Unavailable";
  const dimensions = sessionContextReadinessDimensions(handoff);
  const evidence = isRecord(dimensions?.evidence_access)
    ? dimensions.evidence_access
    : {};
  const budget = isRecord(dimensions?.budget_fit)
    ? dimensions.budget_fit
    : isRecord(handoff?.token_accounting)
      ? handoff.token_accounting
      : {};
  if (!sessionContextSemanticCopyReady(handoff)) {
    return evidence.status === "selection_required"
      ? "Repository selection required"
      : evidence.status === "unavailable"
      ? "Required evidence unavailable"
      : "Needs clarification";
  }
  if (handoff?.readiness?.status === "direction_required") {
    return "Context ready · Direction required";
  }
  if (handoff?.readiness?.status === "intent_resolution_required") {
    return "Context ready · Intent required";
  }
  if (budget?.destination_limit?.status === "too_large") {
    return "Copy-ready · Over destination limit";
  }
  if (handoff?.readiness?.status === "discovery_required") {
    return "Discovery brief ready";
  }
  if (handoff?.render_variant === "compact_v2") return "Ready · Compacted";
  return "Ready";
}

export function sessionContextAdvisories(handoff) {
  const dimensions = sessionContextReadinessDimensions(handoff);
  const budget = isRecord(dimensions?.budget_fit)
    ? dimensions.budget_fit
    : isRecord(handoff?.token_accounting)
      ? handoff.token_accounting
      : {};
  const evidence = isRecord(dimensions?.evidence_access)
    ? dimensions.evidence_access
    : {};
  const messages = [];
  if (handoff?.readiness?.status === "direction_required") {
    messages.push(
      "The prior result was rejected or reported failing. This context is portable, but it does not authorize another action until the user gives current direction.",
    );
  } else if (handoff?.readiness?.status === "intent_resolution_required") {
    messages.push(
      "The recovered turn does not establish an actionable objective. Ask the user for current direction instead of treating the read-only fallback as a task.",
    );
  }
  if (budget?.efficiency_target?.within_target === false) {
    messages.push(
      `Generated context is ${Number(budget.efficiency_target.overflow_tokens || 0).toLocaleString()} tokens above its optimization target; copying remains available.`,
    );
  }
  if (budget?.destination_limit?.status === "too_large") {
    messages.push(
      `This context is ${Number(budget.destination_limit.overflow_tokens || 0).toLocaleString()} tokens above the selected destination limit; manual copying remains available.`,
    );
  }
  if (evidence?.status === "materialization_required") {
    messages.push(
      "Required evidence is identified, but the receiving chat still needs it attached or materialized before inspection.",
    );
  }
  const repositorySnapshot = isRecord(evidence?.repository_snapshot)
    ? evidence.repository_snapshot
    : {};
  if (
    repositorySnapshot.source_available === false
    && repositorySnapshot.selection_required !== true
    && cleanText(repositorySnapshot.message)
  ) {
    messages.push(cleanText(repositorySnapshot.message));
  }
  return messages;
}

function sessionContextReadinessDimensions(handoff) {
  if (Object.prototype.hasOwnProperty.call(handoff || {}, "readiness_dimensions")) {
    return isRecord(handoff.readiness_dimensions)
      ? handoff.readiness_dimensions
      : null;
  }
  return isRecord(handoff?.quality_report)
    ? handoff.quality_report
    : null;
}

function isRecord(value) {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}

export async function requireMatchingContentSha256(content, expected, label) {
  const subtle = globalThis.crypto?.subtle;
  if (!subtle || typeof globalThis.TextEncoder !== "function") {
    throw new Error(`${label} integrity could not be verified in this browser.`);
  }
  const digest = await subtle.digest(
    "SHA-256",
    new TextEncoder().encode(String(content)),
  );
  const actual = Array.from(new Uint8Array(digest), (value) => (
    value.toString(16).padStart(2, "0")
  )).join("");
  if (actual !== String(expected || "").trim().toLowerCase()) {
    throw new Error(`${label} failed its content integrity check.`);
  }
}

export function sessionContextQualityMessage(
  handoff,
  contextName = "Current Session Context",
) {
  const report = handoff?.quality_report;
  const issues = Array.isArray(report?.blocking_issues)
    ? report.blocking_issues
    : Array.isArray(report?.issues)
      ? report.issues.filter((issue) => issue?.severity === "blocking")
      : [];
  const detail = issues
    .map((issue) => cleanText(issue?.message))
    .filter(Boolean)
    .slice(0, 2)
    .join(" ");
  return detail
    ? `${contextName} is not copy-ready. ${detail}`
    : `${contextName} is not copy-ready because its quality gate did not pass.`;
}

export function ledgerSections(ledger) {
  return [
    {
      key: "base",
      label: "Original request",
      description: "What you asked for when this task started",
      items: ledger?.base || [],
      count: ledgerCount(ledger, "base"),
      hiddenCount: ledgerHiddenCount(ledger, "base"),
      status: "measured",
    },
    {
      key: "added",
      label: "Since then",
      description: "Follow-up requests, decisions, and progress since the task started",
      items: ledger?.added || [],
      count: ledgerCount(ledger, "added"),
      hiddenCount: ledgerHiddenCount(ledger, "added"),
      status: "measured",
    },
    {
      key: "changed",
      label: "Updated requests",
      description: "Requests you explicitly changed",
      items: ledger?.changed || [],
      count: ledgerCount(ledger, "changed"),
      hiddenCount: ledgerHiddenCount(ledger, "changed"),
      status: "measured",
    },
    {
      key: "missing",
      label: "Context gaps",
      description: "What may no longer be carried forward after compaction",
      items: ledger?.missing?.items || [],
      count: null,
      status: ledger?.missing?.status || "unmeasured",
      statusLabel: ledger?.missing?.status === "not_applicable" ? "No compaction" : "Unknown",
      reason: ledger?.missing?.reason,
    },
    {
      key: "removed",
      label: "No longer applies",
      description: "Earlier requests you explicitly cancelled",
      items: ledger?.removed || [],
      count: ledgerCount(ledger, "removed"),
      hiddenCount: ledgerHiddenCount(ledger, "removed"),
      status: "measured",
    },
  ];
}

function ledgerCount(ledger, key) {
  const captured = Number(ledger?.counts?.[key]);
  return Number.isFinite(captured) ? captured : (ledger?.[key]?.length || 0);
}

function ledgerHiddenCount(ledger, key) {
  const explicit = Number(ledger?.truncated?.[key]);
  if (Number.isFinite(explicit)) return Math.max(0, explicit);
  return Math.max(0, ledgerCount(ledger, key) - (ledger?.[key]?.length || 0));
}

function normalizeProvider(value) {
  const provider = cleanText(value).toLocaleLowerCase().replace(/[\s_-]+/g, "");
  return provider === "claudecode" ? "claude" : provider || "unknown";
}

function cleanText(value) {
  return String(value || "").replace(/\s+/g, " ").trim();
}
