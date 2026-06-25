export const INSPECTOR_EDGE_ORIGIN = {
  deterministic: { label: "Deterministic", color: "#3b82f6" },
  extracted: { label: "Extracted", color: "#8b5cf6" },
  proposed: { label: "Proposed", color: "#94a3b8" },
  ai_proposed: { label: "AI Proposed", color: "#f59e0b" },
  human_verified: { label: "Human Verified", color: "#059669" },
};

export const INSPECTOR_STATUS = {
  active: { label: "Active", pill: "bg-emerald-100 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-400" },
  needs_review: { label: "Needs Review", pill: "bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-400" },
  blocked: { label: "Blocked", pill: "bg-red-100 dark:bg-red-900/40 text-red-700 dark:text-red-400" },
  stale: { label: "Stale", pill: "bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-400" },
  proposed: { label: "Proposed", pill: "bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-400" },
};

export const INSPECTOR_TEMPORAL = {
  current: { label: "Now", pill: "bg-sky-100 dark:bg-sky-900/40 text-sky-700 dark:text-sky-400" },
  future: { label: "Next", pill: "bg-violet-100 dark:bg-violet-900/40 text-violet-700 dark:text-violet-400" },
  past: { label: "Past", pill: "bg-slate-100 dark:bg-slate-700 text-slate-500" },
};

export function githubSourceUrl(node = {}) {
  if (node.source_url) return node.source_url;
  const meta = node.source_metadata_summary || {};
  if (meta.html_url || meta.url) return meta.html_url || meta.url;
  const repo = meta.repo || meta.repository;
  const number = meta.number;
  if (!repo || !number) return null;
  const itemType = String(meta.item_type || node.fact_type || "").toLowerCase();
  const segment = itemType.includes("pull") || /\bpr\b/.test(itemType) ? "pull" : "issues";
  return `https://github.com/${String(repo).replace(/^https?:\/\/github\.com\//, "")}/${segment}/${number}`;
}

export function sourceDocumentPath(sourceDocumentId) {
  if (!sourceDocumentId) return null;
  return `/app/sources?source_id=${encodeURIComponent(sourceDocumentId)}`;
}

export function isDeterministicMentionEdge(edge = {}) {
  const rel = String(edge.label || edge.displayLabel || "").toLowerCase();
  return edge.origin === "deterministic" && rel.includes("mentions");
}

export function slackPermalink(node = {}) {
  const meta = node.source_metadata_summary || {};
  return meta.permalink || node.source_url || "";
}

export function slackContextRows(node = {}) {
  const meta = node.source_metadata_summary || {};
  const channel = meta.channel_name ? `#${String(meta.channel_name).replace(/^#/, "")}` : "";
  return [
    ["Channel", channel],
    ["Author", meta.author_name || meta.user_name],
    ["Message ts", meta.ts],
    ["Thread ts", meta.thread_ts],
    ["Parent ts", meta.parent_ts],
    ["Reply count", meta.reply_count],
  ].filter(([, value]) => value !== null && value !== undefined && value !== "");
}

export function sourceMetaEntries(meta = {}, max = 8) {
  const hiddenKeys = new Set(["permalink"]);
  return Object.entries(meta || {})
    .filter(([key, value]) => !hiddenKeys.has(key) && value !== null && value !== undefined && value !== "")
    .slice(0, max);
}

export function formatMetaKey(key = "") {
  return String(key).replace(/_/g, " ");
}

export function nodeWarnings(node = {}) {
  const warnings = [];
  if (node.status === "stale") warnings.push({ text: "Stale — may need review", tone: "amber" });
  if (node.status === "proposed") warnings.push({ text: "Proposed — not yet accepted", tone: "amber" });
  if (node.status === "blocked") warnings.push({ text: "Blocked — needs attention", tone: "red" });
  if (node.status === "deprecated") warnings.push({ text: "Deprecated — do not rely on", tone: "red" });
  if (node.confidence != null && node.confidence < 0.5) {
    warnings.push({ text: `Low confidence (${Math.round(node.confidence * 100)}%)`, tone: "red" });
  }
  if (!node.excerpt && !node.provenance) warnings.push({ text: "Missing evidence / provenance", tone: "amber" });
  if (!node.connected?.length) warnings.push({ text: "Isolated — no relationships", tone: "amber" });
  return warnings;
}
