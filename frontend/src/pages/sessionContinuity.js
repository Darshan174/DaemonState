const FALLBACK_TITLE = "Untitled agent session";

export function buildSessionContinuity({
  sessions = [],
  ledgers = [],
  checkpoints = [],
} = {}) {
  const ledgersBySession = new Map(
    ledgers.map((ledger) => [sessionKey(ledger.provider, ledger.session_id), ledger]),
  );
  const checkpointsBySession = new Map();
  for (const checkpoint of checkpoints) {
    const key = sessionKey(checkpoint.provider, checkpoint.session_id);
    const values = checkpointsBySession.get(key) || [];
    values.push(checkpoint);
    checkpointsBySession.set(key, values);
  }
  for (const values of checkpointsBySession.values()) {
    values.sort(compareNewestFirst);
  }

  const cards = sessions.map((session) => {
    const key = sessionKey(session.connector_type, session.session_id);
    const ledger = ledgersBySession.get(key) || emptyLedger(session);
    const versions = checkpointsBySession.get(key) || [];
    // Never fall back from an unusable newest boundary to an older task. The
    // backend recovers source-backed historical goals for list projections;
    // if that recovery still fails, the safe UI state is unavailable.
    const checkpoint = versions[0] || null;
    return prepareSessionCard(session, ledger, versions, checkpoint);
  });

  cards.sort((left, right) => {
    const delta = timestamp(right.updatedAt) - timestamp(left.updatedAt);
    if (delta) return delta;
    return right.key.localeCompare(left.key);
  });
  return cards;
}

export function sessionSearchText(card) {
  return [
    card.title,
    card.provider,
    card.sessionId,
    card.cwd,
    card.branch,
    ...ledgerSections(card.ledger).flatMap((section) =>
      section.items
        .filter((item) => item.kind !== "file" && item.kind !== "check")
        .map((item) => `${item.kind || ""} ${item.text || ""}`),
    ),
  ].join(" ").toLocaleLowerCase();
}

export function isUsableCheckpoint(checkpoint) {
  return Boolean(
    checkpoint
    && checkpoint.capture_status === "complete"
    && checkpoint.projection?.valid !== false
    && checkpoint.sections?.goal?.[0]?.statement
    && checkpoint.sections?.exact_next_action?.[0]?.statement
  );
}

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

export function sessionContextQualityMessage(handoff) {
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
    ? `Current Session Context is not copy-ready. ${detail}`
    : "Current Session Context is not copy-ready because its quality gate did not pass.";
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

function prepareSessionCard(session, ledger, versions, checkpoint) {
  const provider = normalizeProvider(session.connector_type || ledger.provider);
  const key = sessionKey(provider, session.session_id);
  const sourceDocumentId = session.source_document_id || ledger.source_document_id || null;
  return {
    key,
    id: session.id || key,
    sessionId: session.session_id,
    sourceDocumentId,
    provider,
    providerLabel: session.harness || providerLabel(provider),
    title: cleanText(session.title) || cleanText(ledger.base?.[0]?.text) || FALLBACK_TITLE,
    preview: cleanText(session.preview),
    cwd: session.cwd || null,
    branch: session.branch || checkpoint?.repo?.branch || null,
    live: Boolean(session.live),
    updatedAt: session.updated_at || ledger.updated_at || checkpointTime(checkpoint),
    compactionCount: Math.max(
      ledger.compactions?.length || 0,
      session.compaction_checkpoints?.length || 0,
      versions.filter((item) => item.trigger === "compaction").length,
    ),
    ledger,
    versions,
    checkpoint,
    canResume: Boolean(sourceDocumentId && ledger.schema_version),
    hasUnknownContextGaps: ledger?.missing?.status === "unmeasured",
  };
}

function emptyLedger(session) {
  return {
    schema_version: null,
    provider: normalizeProvider(session.connector_type),
    session_id: session.session_id,
    source_document_id: session.source_document_id,
    base: [],
    added: [],
    changed: [],
    missing: {
      status: "unmeasured",
      items: [],
      reason: "Normalized session events are not available for comparison.",
    },
    removed: [],
    compactions: session.compaction_checkpoints || [],
  };
}

function sessionKey(provider, sessionId) {
  return `${normalizeProvider(provider)}\u0000${String(sessionId || "unknown")}`;
}

function normalizeProvider(value) {
  const provider = cleanText(value).toLocaleLowerCase().replace(/[\s_-]+/g, "");
  return provider === "claudecode" ? "claude" : provider || "unknown";
}

function providerLabel(value) {
  return {
    codex: "Codex",
    claude: "Claude Code",
    opencode: "OpenCode",
  }[normalizeProvider(value)] || "Agent";
}

function compareNewestFirst(left, right) {
  const delta = timestamp(checkpointTime(right)) - timestamp(checkpointTime(left));
  if (delta) return delta;
  return String(right?.id || "").localeCompare(String(left?.id || ""));
}

function checkpointTime(checkpoint) {
  return checkpoint?.boundary?.occurred_at || checkpoint?.created_at || null;
}

function timestamp(value) {
  const parsed = value ? Date.parse(value) : Number.NaN;
  return Number.isFinite(parsed) ? parsed : 0;
}

function cleanText(value) {
  return String(value || "").replace(/\s+/g, " ").trim();
}
