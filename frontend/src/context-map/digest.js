import {
  AlertTriangle,
  Bot,
  CheckCircle2,
  CircleDot,
  ClipboardList,
  FileText,
  GitPullRequest,
  HelpCircle,
  ShieldAlert,
} from "lucide-react";

export const STATUS_META = {
  active: { label: "Active", tone: "blue" },
  blocked: { label: "Blocked", tone: "red" },
  conflict: { label: "Conflict", tone: "red" },
  needs_review: { label: "Needs review", tone: "amber" },
  stale: { label: "Stale", tone: "amber" },
  verified: { label: "Verified", tone: "green" },
};

export const HEALTH_META = {
  empty: { label: "Empty", tone: "gray" },
  healthy: { label: "Healthy", tone: "green" },
  needs_review: { label: "Needs review", tone: "amber" },
  critical: { label: "Critical", tone: "red" },
};

export const TYPE_META = {
  agent_session: { label: "Agent session", icon: Bot },
  blocker: { label: "Blocker", icon: ShieldAlert },
  claim: { label: "Claim", icon: CircleDot },
  decision: { label: "Decision", icon: CheckCircle2 },
  evidence: { label: "Evidence", icon: FileText },
  file: { label: "File", icon: FileText },
  risk: { label: "Risk", icon: AlertTriangle },
  source: { label: "Source", icon: GitPullRequest },
  task: { label: "Task", icon: ClipboardList },
};

export const TONE_CLASSES = {
  amber: "border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-900/60 dark:bg-amber-950/35 dark:text-amber-200",
  blue: "border-sky-200 bg-sky-50 text-sky-800 dark:border-sky-900/60 dark:bg-sky-950/35 dark:text-sky-200",
  gray: "border-slate-200 bg-slate-50 text-slate-600 dark:border-neutral-800 dark:bg-neutral-950 dark:text-neutral-300",
  green: "border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-900/60 dark:bg-emerald-950/35 dark:text-emerald-200",
  red: "border-red-200 bg-red-50 text-red-800 dark:border-red-900/60 dark:bg-red-950/35 dark:text-red-200",
  violet: "border-violet-200 bg-violet-50 text-violet-800 dark:border-violet-900/60 dark:bg-violet-950/35 dark:text-violet-200",
};

const GRAPH_LANES = [
  { id: "sessions", label: "AI sessions", description: "Imported coding sessions in this workspace" },
  { id: "architecture", label: "System", description: "Deterministic areas discovered in the selected repository" },
  { id: "decisions", label: "Decisions", description: "Recorded choices and claims that guide the work" },
  { id: "prs", label: "Pull requests", description: "Observed pull requests from imported provider snapshots" },
  { id: "issues", label: "Issues & blockers", description: "Explicit issues, blockers, and risks" },
  { id: "documents", label: "Document gaps", description: "Explicit document findings; absence is not a verified pass" },
  { id: "next_tasks", label: "Next agent tasks", description: "Explicit tasks recorded for the next run" },
  { id: "other", label: "Other evidence", description: "Supporting records without a named overview category" },
];

export function cardIcon(card) {
  return TYPE_META[card?.type]?.icon || HelpCircle;
}

export function confidenceLabel(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return "n/a";
  return `${Math.round(numeric * 100)}%`;
}

export function formatTimeAgo(value) {
  if (!value) return "Unknown";
  const date = parseApiTimestamp(value);
  if (!date) return "Unknown";
  const seconds = Math.max(0, Math.floor((Date.now() - date.getTime()) / 1000));
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} hr ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days} day${days === 1 ? "" : "s"} ago`;
  return date.toLocaleDateString();
}

export function parseApiTimestamp(value) {
  if (value instanceof Date) {
    return Number.isNaN(value.getTime()) ? null : value;
  }
  const raw = String(value || "").trim();
  if (!raw) return null;
  // The database stores naive UTC. Older API responses omitted the UTC marker,
  // which made browsers reinterpret fresh events as local time.
  const normalized = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?$/.test(raw)
    ? `${raw}Z`
    : raw;
  const parsed = new Date(normalized);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

export function cardsById(cards = []) {
  return new Map(cards.map((card) => [card.id, card]));
}

export function buildSessionKnowledgeMap(digest, workspaceName = "selected workspace") {
  const cards = [...(digest?.cards || [])]
    .filter(hasUsefulCard)
    .sort((a, b) => (b.attention_score || 0) - (a.attention_score || 0));

  const groups = {
    aiSessions: uniqueBySource(cards.filter((card) => ["agent_session", "session"].includes(card.category))),
    decisions: cards.filter((card) => card.category === "decision").filter(hasUsefulDisplayText),
    prs: cards.filter((card) => card.category === "pull_request"),
    blockers: cards.filter((card) => card.category === "blocker").filter(hasUsefulDisplayText),
    brokenDocs: cards.filter((card) => card.category === "document_finding").filter(hasUsefulDisplayText),
    issues: cards.filter((card) => card.category === "issue"),
  };

  return {
    ...groups,
    nextAgentPrompt: buildNextAgentPrompt({ groups, workspaceName, health: digest?.health }),
  };
}

export function preciseLine(value, maxWords = 9) {
  const cleaned = cleanDisplayText(value).replace(/https?:\/\/\S+/g, "").trim();
  if (!cleaned) return "Not captured yet";

  const firstThought = cleaned.split(/[.!?\n]/).find(Boolean)?.trim() || cleaned;
  const words = firstThought.split(/\s+/).filter(Boolean);
  if (words.length <= maxWords) return firstThought;
  return `${words.slice(0, maxWords).join(" ")}...`;
}

export function cardDisplayLine(card, intent = "summary", maxWords = 9) {
  const candidates = displayCandidates(card, intent);
  const selected = candidates.map(cleanDisplayText).find((candidate) => isUsefulText(candidate)) || card?.title || card?.summary;
  return preciseLine(selected, maxWords);
}

export function cardDisplayText(card, intent = "summary") {
  const candidates = displayCandidates(card, intent);
  const selected = candidates.map(cleanDisplayText).find((candidate) => isUsefulText(candidate)) || "";
  return selected || "Not captured yet";
}

export function primarySourceUrl(card) {
  return (card?.provenance || []).find((source) => source.source_url)?.source_url || null;
}

export function pullRequestLabel(card) {
  const number = card?.remote_item?.number;
  const repository = card?.remote_item?.repository || card?.remote_item?.repo_full_name;
  if (number && repository) return `${repository} · PR #${number}`;
  return number ? `PR #${number}` : "Unidentified pull request";
}

export function issueLabel(card) {
  const number = card?.remote_item?.number;
  const repository = card?.remote_item?.repository || card?.remote_item?.repo_full_name;
  if (number && repository) return `${repository} · Issue #${number}`;
  return number ? `Issue #${number}` : "Unidentified issue";
}

export function observedRemoteState(card) {
  const state = card?.remote_item?.observed_status
    || card?.remote_item?.provider_state
    || card?.freshness?.observed_status
    || card?.source_snapshot?.provider_state
    || "unknown";
  if (state === "merged") return "Merged in imported snapshot";
  if (state === "closed") return "Closed in imported snapshot";
  if (state === "draft") return "Draft in imported snapshot";
  if (state === "open") return "Open in imported snapshot";
  return "Provider state unknown";
}

export function sessionIdentity(card) {
  const session = card?.session || {};
  const tool = toolName(session.tool);
  const id = session.session_id ? String(session.session_id) : "unknown ID";
  const shortId = id.length > 14 ? `…${id.slice(-12)}` : id;
  const topic = sessionTopic(card);
  return {
    title: topic || `${tool} session`,
    tool,
    shortId,
    source: `${tool} · ${shortId}`,
    context: [session.branch, session.repository || session.cwd].filter(Boolean).join(" · ") || "Repository context unknown",
    detail: [
      Number.isFinite(Number(session.message_count)) ? `${Number(session.message_count)} messages` : null,
      session.started_at ? formatTimeAgo(session.started_at) : null,
    ].filter(Boolean).join(" · ") || "Session timing unknown",
  };
}

export function sessionTopic(card) {
  const session = card?.session || {};
  const candidates = [
    session.topic,
    session.title,
    card?.summary,
    card?.title,
    ...(card?.provenance || []).map((source) => source.excerpt),
  ];
  for (const candidate of candidates) {
    const topic = cleanSessionTopic(candidate, session);
    if (topic) return topic;
  }
  return null;
}

function cleanSessionTopic(value, session) {
  if (!value) return null;
  const id = String(session?.session_id || "");
  const shortId = id.slice(-12).toLowerCase();
  let text = String(value);
  const userBlocks = text
    .split(/^\[USER\]\s*/m)
    .slice(1)
    .map((block) => block.split(/^\[[A-Z_]+\]\s*/m)[0]);
  if (userBlocks.length) {
    text = userBlocks.find((block) => !isSessionBootstrapNoise(block)) || "";
  }
  if (!text || isSessionBootstrapNoise(text)) return null;
  text = text
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/<[^>]+>/g, " ")
    .replace(/https?:\/\/\S+/g, " ")
    .replace(/(?:\/[\w. -]+){2,}/g, " ")
    .replace(/\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b/gi, " ")
    .split(/\n/)
    .map((line) => line.replace(/^[#>*\-\d.)\s]+/, "").trim())
    .filter((line) => line && !/^files mentioned|^image #/i.test(line))
    .join(" ")
    .split(/[.!?,;]/, 1)[0]
    .trim();
  const generic = /^(?:ai|codex|claude(?: code)?|opencode)?\s*session(?:\s*[·:#-]\s*[\w-]+)?$/i;
  if (!text || generic.test(text) || (shortId && text.toLowerCase().includes(shortId))) return null;
  const prefixes = /^(?:agent session:\s*|session:\s*|\/goal\s+|now\s+|please\s+|can you\s+|could you\s+|would you\s+|i (?:now )?want you to\s+|i need you to\s+|help me(?: to)?\s+|go ahead and\s+|work on\s+)/i;
  let previous;
  while (text && text !== previous) {
    previous = text;
    text = text.replace(prefixes, "").trim();
  }
  text = text.replace(/\ba\s+oss\b/i, "an OSS").replace(/\boss\s+sucess\b/i, "OSS success");
  const words = text.split(/\s+/).filter(Boolean).slice(0, 7);
  const shortened = words.join(" ").slice(0, 56).trim();
  return shortened ? shortened[0].toUpperCase() + shortened.slice(1) : null;
}

function isSessionBootstrapNoise(value) {
  const text = String(value || "").toLowerCase();
  return [
    "request_user_input availability",
    "<apps_instructions>",
    "<collaboration_mode>",
    "<environment_context>",
    "<permissions instructions>",
    "<plugins_instructions>",
    "<skills_instructions>",
    "available skills",
    "filesystem sandboxing",
    "you are codex",
  ].some((marker) => text.includes(marker));
}

export function relevanceLabel(card) {
  const status = card?.workspace_relevance?.status || "unknown";
  if (status === "relevant") return "Workspace relevant";
  if (status === "not_relevant") return "Different repository";
  return "Relevance unverified";
}

export function cardRelationships(card, cards = [], links = []) {
  if (!card) return [];
  const byId = cardsById(cards);
  return links
    .filter((link) => link.source_card_id === card.id || link.target_card_id === card.id)
    .map((link) => ({
      ...link,
      otherCard: byId.get(link.source_card_id === card.id ? link.target_card_id : link.source_card_id),
      direction: link.source_card_id === card.id ? "out" : "in",
    }));
}

export function buildEvidenceGraph(
  digest,
  { limitPerLane = 6, laneLimits = {}, prioritizedCardIds = new Set() } = {},
) {
  const candidateCards = [...(digest?.cards || [])]
    .filter((card) => card?.id && hasUsefulCard(card));
  const candidateIds = new Set(candidateCards.map((card) => card.id));
  const factualLinks = (digest?.links || []).filter((link) => (
    candidateIds.has(link?.source_card_id)
    && candidateIds.has(link?.target_card_id)
    && link?.source_card_id !== link?.target_card_id
  ));
  const linkedIds = new Set(factualLinks.flatMap((link) => [link.source_card_id, link.target_card_id]));
  const namedSourceRoots = new Set(candidateCards
    .filter((card) => ["agent_session", "pull_request", "issue"].includes(card.category))
    .map(cardSourceIdentity)
    .filter(Boolean));
  const bestSupportingCardBySource = new Map();
  candidateCards.forEach((card) => {
    if (card.category !== "supporting_evidence" || linkedIds.has(card.id)) return;
    const sourceIdentity = cardSourceIdentity(card);
    if (!sourceIdentity || namedSourceRoots.has(sourceIdentity)) return;
    const current = bestSupportingCardBySource.get(sourceIdentity);
    if (!current || supportingVisualScore(card) > supportingVisualScore(current)) {
      bestSupportingCardBySource.set(sourceIdentity, card);
    }
  });
  const allCards = candidateCards.filter((card) => {
    if (card.category !== "supporting_evidence") return true;
    if (isGenericSourceHub(card)) return false;
    if (linkedIds.has(card.id)) return true;
    if (supportingRemoteMatch(card)) return false;
    const sourceIdentity = cardSourceIdentity(card);
    if (!sourceIdentity) return true;
    if (namedSourceRoots.has(sourceIdentity)) return false;
    return bestSupportingCardBySource.get(sourceIdentity)?.id === card.id;
  });
  const lanes = GRAPH_LANES.map((lane) => ({ ...lane, cards: [] }));

  allCards.forEach((card) => {
    const laneId = graphLaneForCard(card);
    lanes.find((lane) => lane.id === laneId).cards.push(card);
  });
  lanes.forEach((lane) => {
    lane.totalCount = lane.cards.length;
    lane.cards = lane.cards
      .sort((a, b) => compareMapCards(a, b, prioritizedCardIds))
      .slice(0, laneLimits[lane.id] ?? limitPerLane);
  });
  const cards = lanes.flatMap((lane) => lane.cards);
  const visibleIds = new Set(cards.map((card) => card.id));

  const nodes = lanes.flatMap((lane) => lane.cards.map((card, index) => ({
    id: card.id,
    card,
    laneId: lane.id,
    laneLabel: lane.label,
    position: {
      x: 0,
      y: index,
    },
  })));

  return {
    nodes,
    edges: factualLinks.filter((link) => visibleIds.has(link.source_card_id) && visibleIds.has(link.target_card_id)),
    lanes,
    hiddenCardCount: Math.max(0, allCards.length - cards.length),
  };
}

function compareMapCards(a, b, prioritizedCardIds) {
  const prioritized = Number(prioritizedCardIds.has(b.id)) - Number(prioritizedCardIds.has(a.id));
  if (prioritized) return prioritized;
  if (a.category === "agent_session" && b.category === "agent_session") {
    const relevance = { relevant: 3, unknown: 2, not_relevant: 1 };
    const relevanceOrder = (relevance[b.workspace_relevance?.status] || 0) - (relevance[a.workspace_relevance?.status] || 0);
    if (relevanceOrder) return relevanceOrder;
  }
  if (a.category === "code_area" && b.category === "code_area") {
    const rootOrder = Number(/Repository:/i.test(b.title || "")) - Number(/Repository:/i.test(a.title || ""));
    if (rootOrder) return rootOrder;
  }
  return (b.attention_score || 0) - (a.attention_score || 0)
    || String(a.title || "").localeCompare(String(b.title || ""));
}

export function graphLaneForCard(card) {
  const category = card?.category;
  if (["agent_session", "session"].includes(category)) return "sessions";
  if (category === "code_area") return "architecture";
  if (category === "decision") return "decisions";
  if (category === "pull_request") return "prs";
  if (["issue", "blocker"].includes(category)) return "issues";
  if (category === "document_finding") return "documents";
  if (category === "task") return "next_tasks";
  return "other";
}

function singleLine(value) {
  return String(value ?? "").replace(/\s+/g, " ").trim();
}

function cardSourceIdentity(card) {
  return card?.source_snapshot?.source_document_id
    || card?.provenance?.[0]?.source_document_id
    || card?.source_ids?.[0]
    || null;
}

function supportingVisualScore(card) {
  const title = singleLine(card?.title).toLowerCase();
  const summary = singleLine(card?.summary).toLowerCase();
  let score = Math.min(240, summary.length) + Math.min(120, title.length);
  if (/\bhub for messages\b|^slack channel\b/.test(`${title} ${summary}`)) score -= 500;
  if (/^slack:|^message:/.test(title)) score += 160;
  return score;
}

function isGenericSourceHub(card) {
  const title = singleLine(card?.title);
  const summary = singleLine(card?.summary);
  const channelHeading = /^(?:slack\s+)?channel\s*[:#]/i;
  return channelHeading.test(title)
    && (
      !summary
      || /\bhub for messages\b/i.test(summary)
      || channelHeading.test(summary)
      || cleanDisplayText(title).toLowerCase() === cleanDisplayText(summary).toLowerCase()
    );
}

function supportingRemoteMatch(card) {
  return [card?.title, card?.summary]
    .map(singleLine)
    .map((value) => value.match(/(?:^|\b)(PR|Issue)\s*#?(\d+)/i))
    .find(Boolean);
}

function uniqueBySource(cards) {
  const seen = new Set();
  return cards.filter((card) => {
    const key = card?.session?.session_id || card?.provenance?.[0]?.source_document_id || card?.source_ids?.[0] || card.id;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function toolName(value) {
  const normalized = String(value || "").toLowerCase();
  if (normalized === "claude_code" || normalized === "claude") return "Claude Code";
  if (normalized === "opencode") return "OpenCode";
  if (normalized === "codex") return "Codex";
  return value ? String(value) : "AI";
}

function searchableText(card) {
  return [
    card?.title,
    card?.summary,
    card?.why_it_matters,
    card?.next_action,
    card?.status,
    card?.type,
    ...(card?.badges || []).map((badge) => badge.label),
    ...(card?.provenance || []).flatMap((source) => [
      source.source_type,
      source.source_label,
      source.source_url,
      source.excerpt,
    ]),
  ]
    .filter(Boolean)
    .join(" ");
}

function displayCandidates(card, intent) {
  const sourceLabels = (card?.provenance || []).map((source) => source.source_label);
  const excerpts = (card?.provenance || []).map((source) => source.excerpt);
  const base = [card?.summary, card?.next_action, card?.title, ...sourceLabels, ...excerpts];

  if (intent === "blocker") {
    return [
      textWithKeywords(base, /\b(blocked|blocker|blocking|failed|failing|error|conflict|broken|schema|ci|test|approval)\b/i),
      card?.summary,
      card?.title,
      card?.next_action,
      ...sourceLabels,
    ].filter(Boolean);
  }

  if (intent === "decision") {
    return [card?.summary, card?.title, card?.next_action, ...excerpts, ...sourceLabels].filter(Boolean);
  }

  if (intent === "docs") {
    return [
      textWithKeywords(base, /\b(docs?|documentation|readme|runbook|guide|devrel|stale|broken)\b/i),
      card?.summary,
      card?.title,
      card?.next_action,
      ...excerpts,
      ...sourceLabels,
    ].filter(Boolean);
  }

  return base.filter(Boolean);
}

function textWithKeywords(values, pattern) {
  return values.find((value) => pattern.test(String(value || "")));
}

function hasUsefulCard(card) {
  return !isInstructionNoise(card) && hasUsefulDisplayText(card);
}

function hasUsefulDisplayText(card) {
  return ["summary", "decision", "blocker", "docs"].some((intent) =>
    displayCandidates(card, intent).map(cleanDisplayText).some((candidate) => isUsefulText(candidate)),
  );
}

function isUsefulText(value) {
  const text = cleanDisplayText(value);
  if (!text || text.length < 8) return false;
  if (/^[a-z],\s/i.test(text)) return false;
  if (/^[a-z]\s/i.test(text)) return false;
  if (/[A-Za-z0-9+/]{140,}={0,2}/.test(text)) return false;
  if (/data:image\/|base64|internal_chat_message_metadata|function_call_output|session_meta/i.test(text)) return false;
  if (text.split(/\s+/).length < 2) return false;
  const letters = (text.match(/[a-z]/gi) || []).length;
  if (letters < 8) return false;
  const punctuation = (text.match(/[/.\\{}[\]<>_=+:;|]/g) || []).length;
  if (text.length > 0 && punctuation / text.length > 0.34 && text.split(/\s+/).length <= 5) return false;
  return !noisePattern().test(text);
}

function isInstructionNoise(card) {
  const text = searchableText(card);
  return noisePattern().test(text) || /data:image\/|base64|[A-Za-z0-9+/]{180,}={0,2}/i.test(text);
}

function noisePattern() {
  return /\b(ask the user directly|concise plain-text question|readers don.t mistake|vitest does not accept|file references|sandbox|permissions instructions|developer instructions|base_instructions|must browse|request escalation|prefix_rule|do not revert unrelated|working with the user|knowledge cutoff|final answer instructions|turn_aborted|tool_call|function_call|function_call_output|internal_chat_message_metadata|local_images|session_meta)\b/i;
}

export function cleanDisplayText(value) {
  return String(value || "")
    .replace(/\s+From:\s+[^<\n]*<[^>]+>[\s\S]*$/i, " ")
    .replace(/\s+Reply to this email[\s\S]*$/i, " ")
    .replace(/data:image\/[a-z0-9.+-]+;base64,\S+/gi, " ")
    .replace(/[A-Za-z0-9+/]{140,}={0,2}/g, " ")
    .replace(/https?:\/\/\S+/g, " ")
    .replace(/[*_`#>\[\](){}"]/g, " ")
    .replace(/\b(decision|blocker|risk|task|issue|summary|context)\s*:\s*/gi, "")
    .replace(/\s*[\u2013\u2014]\s*/g, " — ")
    .replace(/\s+-\s+/g, " — ")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/^[,./\\\s:;!?…\-\u2013\u2014]+/, "")
    .replace(/[,./\\\s:;!?…\-\u2013\u2014]+$/, "");
}

function buildNextAgentPrompt({ groups, workspaceName, health }) {
  const lines = [
    `Continue work on Context Engine for ${workspaceName}.`,
    "",
    "Goal: use the session knowledge map as the source of truth for the next focused change.",
    "",
    "Current context:",
    ...promptItems("AI sessions", groups.aiSessions, (card) => `${cardDisplayLine(card, "title", 7)} - ${cardDisplayLine(card, "summary", 14)}`),
    ...promptItems("Decisions", groups.decisions, (card) => cardDisplayLine(card, "decision", 14)),
    ...promptItems("PRs", groups.prs, (card) => `${pullRequestLabel(card)} - ${primarySourceUrl(card) || "link missing"} - ${cardDisplayLine(card, "summary", 12)}`),
    ...promptItems("Blockers", groups.blockers, (card) => cardDisplayLine(card, "blocker", 12)),
    ...promptItems("Broken docs", groups.brokenDocs, (card) => cardDisplayLine(card, "docs", 12)),
    ...promptItems("Issues", groups.issues, (card) => `${issueLabel(card)} - ${primarySourceUrl(card) || "link missing"} - ${cardDisplayLine(card, "summary", 12)}`),
    "",
    "Instructions:",
    "1. Start by checking git status and the active branch. Do not revert unrelated local changes.",
    "2. Read the files touched by the current task before editing.",
    "3. Resolve blockers first, then update PRs/issues/docs with exact links and short summaries.",
    "4. Keep user-facing summaries short and plain. No academic jargon.",
    "5. Run the narrow relevant tests plus the frontend build before committing.",
    "6. Commit only the files you intentionally changed and push the branch.",
    "",
    `Health: ${health?.summary || "No health summary captured yet."}`,
  ];

  return lines.join("\n");
}

function promptItems(label, cards, render) {
  if (!cards.length) return [`- ${label}: none captured yet.`];
  return [
    `- ${label}:`,
    ...cards.slice(0, 5).map((card) => `  - ${render(card)}`),
  ];
}
