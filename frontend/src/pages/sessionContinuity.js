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
  if (handoff.quality_report.copy_ready !== true) {
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
