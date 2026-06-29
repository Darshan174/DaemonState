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
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Unknown";
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

export function cardsById(cards = []) {
  return new Map(cards.map((card) => [card.id, card]));
}

export function relatedCards(card, cards = [], links = []) {
  if (!card) return [];
  const byId = cardsById(cards);
  const relatedIds = new Set();
  links.forEach((link) => {
    if (link.source_card_id === card.id) relatedIds.add(link.target_card_id);
    if (link.target_card_id === card.id) relatedIds.add(link.source_card_id);
  });
  return Array.from(relatedIds).map((id) => byId.get(id)).filter(Boolean);
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

export function estimateTokens(cards = []) {
  const words = cards.reduce((total, card) => {
    const text = [card.title, card.summary, card.why_it_matters, card.next_action]
      .filter(Boolean)
      .join(" ");
    return total + text.split(/\s+/).filter(Boolean).length;
  }, 0);
  return Math.max(120, Math.round(words * 1.35));
}

export function buildAgentPacket({ selectedCard, includedCards, excludedCards = [] }) {
  const cards = includedCards.filter(Boolean);
  return {
    schema: "context_packet.v1",
    goal: selectedCard?.title || "Selected context handoff",
    current_state: cards.filter((card) => card.temporal === "current").map(packetItem),
    decisions: cards.filter((card) => card.type === "decision").map(packetItem),
    blockers: cards.filter((card) => card.type === "blocker" || card.status === "blocked").map(packetItem),
    tasks: cards.filter((card) => card.type === "task").map(packetItem),
    files: cards.filter((card) => card.type === "file").map(packetItem),
    prior_agent_attempts: cards.filter((card) => card.type === "agent_session").map(packetItem),
    missing_context: missingContext(cards),
    source_citations: cards.flatMap((card) =>
      (card.provenance || []).map((source) => ({
        card_id: card.id,
        source_type: source.source_type,
        source_label: source.source_label,
        source_url: source.source_url || null,
      })),
    ),
    excluded: excludedCards.map((card) => ({ id: card.id, title: card.title })),
  };
}

export function packetMarkdown(packet) {
  const lines = [
    `# ${packet.goal}`,
    "",
    "## Current State",
    ...markdownItems(packet.current_state),
    "",
    "## Decisions",
    ...markdownItems(packet.decisions),
    "",
    "## Blockers",
    ...markdownItems(packet.blockers),
    "",
    "## Tasks",
    ...markdownItems(packet.tasks),
    "",
    "## Files",
    ...markdownItems(packet.files),
    "",
    "## Prior Agent Attempts",
    ...markdownItems(packet.prior_agent_attempts),
    "",
    "## Missing Context",
    ...(packet.missing_context.length ? packet.missing_context.map((item) => `- ${item}`) : ["- None flagged"]),
    "",
    "## Source Citations",
    ...(packet.source_citations.length
      ? packet.source_citations.map((source) => `- ${source.source_label} (${source.source_type})${source.source_url ? `: ${source.source_url}` : ""}`)
      : ["- None"]),
  ];
  return lines.join("\n");
}

function packetItem(card) {
  return {
    id: card.id,
    title: card.title,
    summary: card.summary,
    status: card.status,
    confidence: card.confidence,
    why_included: card.why_it_matters,
    next_action: card.next_action,
  };
}

function markdownItems(items) {
  return items.length
    ? items.map((item) => `- **${item.title}**: ${item.summary}`)
    : ["- None"];
}

function missingContext(cards) {
  const missing = [];
  if (cards.some((card) => card.status === "needs_review" || card.confidence < 0.7)) {
    missing.push("Verify low-confidence or proposed context before execution.");
  }
  if (cards.some((card) => card.status === "conflict")) {
    missing.push("Resolve conflicting evidence before handing off to an agent.");
  }
  if (cards.some((card) => card.status === "blocked")) {
    missing.push("Confirm owner, reproduction steps, or acceptance criteria for blockers.");
  }
  return missing;
}
