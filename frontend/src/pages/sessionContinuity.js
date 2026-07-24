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
    const checkpoint = versions.find(isUsableCheckpoint) || versions[0] || null;
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
      section.items.map((item) => `${item.kind || ""} ${item.text || ""}`),
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

export function ledgerSections(ledger) {
  return [
    {
      key: "base",
      symbol: "B",
      label: "Base",
      description: "Original request and requirements",
      items: ledger?.base || [],
      count: ledgerCount(ledger, "base"),
      hiddenCount: ledgerHiddenCount(ledger, "base"),
      status: "measured",
    },
    {
      key: "added",
      symbol: "+",
      label: "Added",
      description: "New instructions, decisions, files, and progress",
      items: ledger?.added || [],
      count: ledgerCount(ledger, "added"),
      hiddenCount: ledgerHiddenCount(ledger, "added"),
      status: "measured",
    },
    {
      key: "changed",
      symbol: "~",
      label: "Changed",
      description: "Explicit user amendments",
      items: ledger?.changed || [],
      count: ledgerCount(ledger, "changed"),
      hiddenCount: ledgerHiddenCount(ledger, "changed"),
      status: "measured",
    },
    {
      key: "missing",
      symbol: "!",
      label: "Missing",
      description: "Information compaction may have omitted",
      items: ledger?.missing?.items || [],
      count: null,
      status: ledger?.missing?.status || "unmeasured",
      statusLabel: ledger?.missing?.status === "not_applicable" ? "n/a" : (ledger?.missing?.status || "unmeasured"),
      reason: ledger?.missing?.reason,
    },
    {
      key: "removed",
      symbol: "−",
      label: "Removed",
      description: "Requirements explicitly cancelled by the user",
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
  return {
    key,
    id: session.id || key,
    sessionId: session.session_id,
    sourceDocumentId: session.source_document_id || ledger.source_document_id,
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
    canRepair: Boolean(session.source_document_id && ledger.schema_version),
    missingUnmeasured: ledger?.missing?.status === "unmeasured",
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
  const provider = String(value || "unknown").toLocaleLowerCase();
  return provider === "claude_code" ? "claude" : provider;
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
