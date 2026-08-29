const SESSION_BACKGROUND_SCHEMA = "session_background.v1";
const LEGACY_SESSION_HANDOFF_SCHEMA = "session_handoff.v1";
const RECEIVER_PENDING_STATUSES = new Set([
  "materialization_required",
  "pending",
  "receiver_pending",
  "not_ready",
  "not_delivered",
]);
const RECEIVER_READY_STATUSES = new Set([
  "available",
  "ready",
  "ready_to_send",
  "staged",
]);
const RECEIVER_DELIVERED_STATUSES = new Set([
  "acknowledged",
  "delivered",
  "receiver_acknowledged",
]);


export function sessionContextArtifactShapeValid(handoff) {
  const schema = cleanText(handoff?.schema_version);
  const supportedSchema = (
    schema === SESSION_BACKGROUND_SCHEMA
    || schema === LEGACY_SESSION_HANDOFF_SCHEMA
  );
  return Boolean(
    supportedSchema
    && handoff?.scope === "session"
    && typeof handoff.provider === "string"
    && handoff.provider.trim()
    && typeof handoff.session_id === "string"
    && handoff.session_id.trim()
    && typeof handoff.content === "string"
    && handoff.content.trim()
    && typeof handoff.sha256 === "string"
    && handoff.sha256.trim()
    && handoff.checkpoint_id
    && isRecord(handoff.boundary)
    && handoff.boundary.event_id
    && Number.isInteger(handoff.boundary.sequence_number)
    && isRecord(handoff.quality_report)
    && typeof handoff.quality_report.copy_ready === "boolean"
  );
}


export async function copyReadySessionContextContent(handoff, expected = {}) {
  if (
    !sessionContextArtifactShapeValid(handoff)
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
  return sessionContextOperationState(handoff).clipboardCopyAllowed;
}


function sessionContextPolicyCopyReady(handoff) {
  const report = handoff?.quality_report;
  const dimensions = sessionContextReadinessDimensions(handoff);
  const semantic = dimensions?.semantic_readiness;
  const evidence = dimensions?.evidence_access;
  const legacyWithoutActivation = Boolean(
    handoff?.schema_version === LEGACY_SESSION_HANDOFF_SCHEMA
    && !isRecord(handoff?.quality_control),
  );
  return Boolean(
    report?.copy_ready === true
    && isRecord(semantic)
    && semantic.copy_ready === true
    && isRecord(evidence)
    && evidence.blocks_copy === false
    && (
      legacyWithoutActivation
      || contextQualityActivationCopyReady(
        handoff?.quality_control,
        handoff?.sha256,
      )
    )
  );
}


export function sessionContextOperationState(handoff) {
  if (!sessionContextArtifactShapeValid(handoff)) {
    return {
      status: "unavailable",
      label: "Unavailable",
      tone: "attention",
      previewAllowed: false,
      clipboardCopyAllowed: false,
    };
  }

  const canonical = handoff.schema_version === SESSION_BACKGROUND_SCHEMA;
  const dimensions = sessionContextReadinessDimensions(handoff) || {};
  const evidence = isRecord(handoff.evidence_access)
    ? handoff.evidence_access
    : isRecord(dimensions.evidence_access)
      ? dimensions.evidence_access
      : {};
  const receiver = isRecord(handoff.receiver_readiness)
    ? handoff.receiver_readiness
    : isRecord(dimensions.receiver_readiness)
      ? dimensions.receiver_readiness
      : {};
  const sourceCompleteness = isRecord(handoff.source_completeness)
    ? handoff.source_completeness
    : isRecord(dimensions.source_completeness)
      ? dimensions.source_completeness
      : {};
  const capabilities = isRecord(handoff.operation_capabilities)
    ? handoff.operation_capabilities
    : {};
  const previewCapability = capabilityState(capabilities.preview);
  const clipboardCapability = capabilityState(capabilities.clipboard_copy);
  const evidenceStatus = cleanText(evidence.status).toLowerCase();
  const qualityStatus = cleanText(handoff.quality_report?.status).toLowerCase();
  const receiverStatus = cleanText(
    receiver.status
    || receiver.delivery_status
    || evidence.receiver_status
    || handoff?.delivery?.receipt?.status
    || handoff?.delivery?.status,
  ).toLowerCase();
  const receiverRequiredIds = Array.isArray(receiver.required_attachment_ids)
    ? receiver.required_attachment_ids.map(cleanText).filter(Boolean)
    : [];
  const pendingIds = [
    ...(Array.isArray(receiver.materialization_required_ids)
      ? receiver.materialization_required_ids
      : []),
    ...(Array.isArray(evidence.receiver_materialization_required_ids)
      ? evidence.receiver_materialization_required_ids
      : []),
  ].map(cleanText).filter(Boolean);
  const requiredDependencies = sessionContextRequiredDependencies(handoff);
  const hasRequiredEvidence = Boolean(
    requiredDependencies.length
    || receiverRequiredIds.length
    || pendingIds.length,
  );
  const previewAllowed = canonical
    ? previewCapability.configured && previewCapability.allowed
    : true;
  const degraded = [
    clipboardCapability.status,
    receiverStatus,
    cleanText(handoff?.delivery?.degradation_status).toLowerCase(),
  ].some((status) => status.includes("degraded"));
  const receiverPending = Boolean(
    pendingIds.length
    || evidenceStatus === "materialization_required"
    || qualityStatus === "materialization_required"
    || RECEIVER_PENDING_STATUSES.has(receiverStatus)
    || RECEIVER_PENDING_STATUSES.has(clipboardCapability.status)
  );
  const sourceUnavailable = Boolean(
    evidenceStatus === "unavailable"
    || ["incomplete", "missing", "unavailable"].includes(
      cleanText(sourceCompleteness.status).toLowerCase(),
    )
  );
  const policyCopyReady = sessionContextPolicyCopyReady(handoff);
  const clipboardCopyAllowed = Boolean(
    policyCopyReady
    && !receiverPending
    && !degraded
    && (
      canonical
        ? clipboardCapability.configured && clipboardCapability.allowed
        : true
    )
  );

  if (!previewAllowed) {
    return {
      status: "unavailable",
      label: "Unavailable",
      tone: "attention",
      previewAllowed: false,
      clipboardCopyAllowed: false,
    };
  }
  if (receiverPending) {
    return {
      status: "evidence_pending",
      label: "Background available · Evidence pending",
      tone: "attention",
      previewAllowed: true,
      clipboardCopyAllowed: false,
    };
  }
  if (sourceUnavailable) {
    return {
      status: "evidence_unavailable",
      label: "Background available · Required evidence unavailable",
      tone: "attention",
      previewAllowed: true,
      clipboardCopyAllowed: false,
    };
  }
  if (degraded) {
    return {
      status: "degraded",
      label: "Background available · Degraded text only",
      tone: "attention",
      previewAllowed: true,
      clipboardCopyAllowed: false,
    };
  }
  if (RECEIVER_DELIVERED_STATUSES.has(receiverStatus)) {
    return {
      status: "delivered",
      label: "Delivered",
      tone: "success",
      previewAllowed: true,
      clipboardCopyAllowed,
    };
  }
  if (
    receiverStatus === "ready_to_send"
    || (
      hasRequiredEvidence
      && RECEIVER_READY_STATUSES.has(receiverStatus)
    )
  ) {
    return {
      status: "ready_to_send",
      label: "Ready to send",
      tone: "success",
      previewAllowed: true,
      clipboardCopyAllowed,
    };
  }
  if (!policyCopyReady) {
    return {
      status: "review_required",
      label: "Background available · Review required",
      tone: "attention",
      previewAllowed: true,
      clipboardCopyAllowed: false,
    };
  }
  return {
    status: "background_available",
    label: "Background available",
    tone: "neutral",
    previewAllowed: true,
    clipboardCopyAllowed,
  };
}

export function contextQualityActivationCopyReady(
  qualityControl,
  expectedArtifactSha256,
) {
  if (!isRecord(qualityControl)) return false;
  const candidateId = cleanText(qualityControl.candidate_id);
  const activeCandidateId = cleanText(qualityControl.active_candidate_id);
  const observationSha256 = cleanText(qualityControl.observation_sha256);
  const artifactSha256 = cleanText(qualityControl.artifact_sha256).toLowerCase();
  const expectedArtifact = cleanText(expectedArtifactSha256).toLowerCase();
  return Boolean(
    qualityControl.schema_version === "context_quality_activation.v1"
    && qualityControl.status === "active"
    && qualityControl.copy_allowed === true
    && candidateId
    && activeCandidateId
    && candidateId === activeCandidateId
    && observationSha256
    && artifactSha256
    && expectedArtifact
    && artifactSha256 === expectedArtifact
  );
}

export function sessionContextReadinessLabel(handoff) {
  const dimensions = sessionContextReadinessDimensions(handoff);
  const evidence = isRecord(dimensions?.evidence_access)
    ? dimensions.evidence_access
    : {};
  if (evidence.status === "selection_required") {
    return "Repository selection required";
  }
  return sessionContextOperationState(handoff).label;
}

export function sessionContextAdvisories(handoff) {
  const operation = sessionContextOperationState(handoff);
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
      `Background is ${Number(budget.efficiency_target.overflow_tokens || 0).toLocaleString()} tokens above its optimization target${operation.clipboardCopyAllowed ? "; copying remains available" : ""}.`,
    );
  }
  if (budget?.destination_limit?.status === "too_large") {
    messages.push(
      `This background is ${Number(budget.destination_limit.overflow_tokens || 0).toLocaleString()} tokens above the selected destination limit${operation.clipboardCopyAllowed ? "; manual copying remains available" : ""}.`,
    );
  }
  if (operation.status === "evidence_pending") {
    messages.push(
      "The background can be previewed, but required evidence must be attached or materialized before it is sent to a receiver.",
    );
  } else if (operation.status === "ready_to_send") {
    messages.push(
      operation.clipboardCopyAllowed
        ? "The background and its required evidence are staged for target delivery. Clipboard copy remains a separate action."
        : "The background and its required evidence are staged for target delivery; use the verified send flow instead of text-only copy.",
    );
  } else if (operation.status === "delivered") {
    messages.push("The receiver acknowledged this background delivery.");
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
  const operation = sessionContextOperationState(handoff);
  if (operation.status === "evidence_pending") {
    return `${contextName} is available for preview, but required evidence is not ready for the receiver. Use a verified attachment delivery flow before continuing.`;
  }
  if (operation.status === "ready_to_send") {
    return `${contextName} is ready to send with its required evidence. Text-only copy is disabled.`;
  }
  if (operation.status === "delivered") {
    return `${contextName} was acknowledged by the receiver.`;
  }
  if (operation.status === "degraded") {
    return `${contextName} is available only as degraded text. Normal copy remains disabled.`;
  }
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


function sessionContextRequiredDependencies(handoff) {
  const dependencies = Array.isArray(handoff?.artifact_dependencies)
    ? handoff.artifact_dependencies
    : Array.isArray(handoff?.attachment_dependencies)
      ? handoff.attachment_dependencies
      : [];
  return dependencies.filter((dependency) => (
    dependency?.required === true
    || cleanText(dependency?.necessity).toLowerCase() === "required"
  ));
}


function capabilityState(value) {
  if (typeof value === "boolean") {
    return { configured: true, allowed: value, status: value ? "ready" : "blocked" };
  }
  if (!isRecord(value)) {
    return { configured: false, allowed: false, status: "unknown" };
  }
  return {
    configured: true,
    allowed: value.allowed === true,
    status: cleanText(value.status).toLowerCase() || "unknown",
  };
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
