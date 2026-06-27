import { useEffect, useRef, useState, useCallback } from "react";
import { useSearchParams } from "react-router-dom";
import cytoscape from "cytoscape";
import {
  Zap, Network, AlertTriangle, MessageSquare, Package,
  Sparkles, Loader2, XCircle, Copy, Check, Search,
  ChevronRight, X as XIcon, Bot, Link2, Plus, Minus, Maximize2,
  GitPullRequest, MessageCircle, FileText, Layers3, ShieldCheck,
  SlidersHorizontal,
} from "lucide-react";
import { useTheme } from "../context/ThemeContext";
import { useWorkspaces } from "../api/hooks";
import { resolveWorkspaceId, useWorkspaceSelection } from "../context/WorkspaceContext";
import WorkspaceTopicGate from "../components/WorkspaceTopicGate";
import {
  BOARD_CARD_WIDTH,
  BOARD_CARD_HEIGHT,
  BOARD_CARD_TEXT_MAX_WIDTH,
  BOARD_READABLE_ZOOM,
  boardReadablePan,
  shouldUseReadableBoardViewport,
  BOARD_LENSES,
  boardGraphGroup,
  passesBoardLens,
  filterGapsLens,
  boardCardVisuals,
  resolveRelationshipEdgeStyle,
} from "../graph/boardMode";
import {
  buildExploreNeighborhood,
  filterExploreComponents,
} from "../graph/exploreMode";
import GraphInspector from "../components/GraphInspector";
import imgGmail from "@assets/gmail-icon.png";

function buildNodeConnections(cy, nodeId) {
  const connected = [];
  cy.edges(`[source = "${nodeId}"], [target = "${nodeId}"]`).forEach((e) => {
    const src = e.data("source");
    const tgt = e.data("target");
    const otherId = src === nodeId ? tgt : src;
    const otherNode = cy.getElementById(otherId);
    if (!otherNode.length) return;
    connected.push({
      nodeId: otherId,
      nodeLabel: otherNode.data("fullLabel") || otherNode.data("label"),
      label: e.data("displayLabel") || e.data("label"),
      edgeId: e.data("id"),
      origin: e.data("origin"),
      confidence: e.data("confidence"),
      direction: src === nodeId ? "out" : "in",
    });
  });
  return connected;
}

function svgDataUri(svg) {
  return `data:image/svg+xml;utf8,${encodeURIComponent(svg)}`;
}

const SLACK_LOGO_URI = svgDataUri(`
<svg viewBox="0 0 127 127" xmlns="http://www.w3.org/2000/svg">
  <path d="M27.2 80c0 7.3-5.9 13.2-13.2 13.2S.8 87.3.8 80s5.9-13.2 13.2-13.2h13.2V80zm6.6 0c0-7.3 5.9-13.2 13.2-13.2s13.2 5.9 13.2 13.2v33c0 7.3-5.9 13.2-13.2 13.2s-13.2-5.9-13.2-13.2V80z" fill="#E01E5A"/>
  <path d="M47 27c-7.3 0-13.2-5.9-13.2-13.2S39.7.6 47 .6s13.2 5.9 13.2 13.2V27H47zm0 6.7c7.3 0 13.2 5.9 13.2 13.2s-5.9 13.2-13.2 13.2H13.9C6.6 60.1.7 54.2.7 46.9s5.9-13.2 13.2-13.2H47z" fill="#36C5F0"/>
  <path d="M99.9 46.9c0-7.3 5.9-13.2 13.2-13.2s13.2 5.9 13.2 13.2-5.9 13.2-13.2 13.2H99.9V46.9zm-6.6 0c0 7.3-5.9 13.2-13.2 13.2s-13.2-5.9-13.2-13.2V13.8C66.9 6.5 72.8.6 80.1.6s13.2 5.9 13.2 13.2v33.1z" fill="#2EB67D"/>
  <path d="M80.1 99.8c7.3 0 13.2 5.9 13.2 13.2s-5.9 13.2-13.2 13.2-13.2-5.9-13.2-13.2V99.8h13.2zm0-6.6c-7.3 0-13.2-5.9-13.2-13.2s5.9-13.2 13.2-13.2h33.1c7.3 0 13.2 5.9 13.2 13.2s-5.9 13.2-13.2 13.2H80.1z" fill="#ECB22E"/>
</svg>`);

const GITHUB_LOGO_URI = svgDataUri(`
<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
  <rect width="24" height="24" rx="5" fill="#ffffff"/>
  <path fill="#24292f" d="M12 2.25c-5.385 0-9.75 4.365-9.75 9.75 0 4.305 2.79 7.96 6.655 9.255.487.09.665-.212.665-.47 0-.232-.008-.844-.013-1.655-2.71.59-3.283-1.305-3.483-1.98-.117-.298-.622-1.305-1.108-1.58-.37-.202-.905-.695-.013-.708.84-.013 1.445.615 1.645.87.96 1.612 2.505 1.16 3.12.877.09-.693.37-1.16.675-1.43-2.377-.27-4.875-1.185-4.875-5.28 0-1.162.416-2.112 1.095-2.857-.11-.27-.475-1.372.105-2.857 0 0 .892-.285 2.925 1.117.847-.24 1.755-.36 2.655-.36.9 0 1.808.12 2.655.36 2.032-1.402 2.925-1.117 2.925-1.117.58 1.485.215 2.587.105 2.857.68.745 1.095 1.695 1.095 2.857 0 4.11-2.505 5.01-4.89 5.278.385.33.727.975.727 1.965 0 1.418-.013 2.558-.013 2.91 0 .258.172.568.667.47A9.72 9.72 0 0021.75 12c0-5.385-4.365-9.75-9.75-9.75z"/>
</svg>`);

const AI_LOGO_URI = svgDataUri(`
<svg viewBox="0 0 48 48" xmlns="http://www.w3.org/2000/svg">
  <rect width="48" height="48" rx="12" fill="#7c3aed"/>
  <path d="M14 29.5V18.5L24 12.75L34 18.5V29.5L24 35.25L14 29.5Z" fill="none" stroke="white" stroke-width="3" stroke-linejoin="round"/>
  <path d="M24 13V35M14 19L34 30M34 19L14 30" stroke="white" stroke-width="2.5" stroke-linecap="round"/>
</svg>`);

function getAiSettingsSaved() {
  try { return JSON.parse(localStorage.getItem("ce_ai_settings") || "{}"); }
  catch { return {}; }
}

const SEV_DOT = { critical: "bg-red-500", high: "bg-amber-500", medium: "bg-yellow-400", low: "bg-slate-400" };
const SEV_PILL = {
  critical: "bg-red-100 dark:bg-red-900/40 text-red-700 dark:text-red-400",
  high:     "bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-400",
  medium:   "bg-yellow-100 dark:bg-yellow-900/40 text-yellow-700 dark:text-yellow-400",
  low:      "bg-slate-100 dark:bg-black text-slate-500",
};

// Status → card border + background tint
const CARD_STATUS = {
  active:       { bg: "rgba(34,197,94,0.10)",  border: "#22c55e" },
  healthy:      { bg: "rgba(34,197,94,0.10)",  border: "#22c55e" },
  completed:    { bg: "rgba(34,197,94,0.10)",  border: "#22c55e" },
  stale:        { bg: "rgba(245,158,11,0.10)", border: "#f59e0b" },
  needs_review: { bg: "rgba(245,158,11,0.10)", border: "#f59e0b" },
  draft:        { bg: "rgba(245,158,11,0.10)", border: "#f59e0b" },
  superseded:   { bg: "rgba(245,158,11,0.10)", border: "#f59e0b" },
  blocked:      { bg: "rgba(239,68,68,0.10)",  border: "#ef4444" },
  deprecated:   { bg: "rgba(239,68,68,0.10)",  border: "#ef4444" },
  rejected:     { bg: "rgba(239,68,68,0.10)",  border: "#ef4444" },
};
const CARD_STATUS_DEFAULT = { bg: "rgba(148,163,184,0.08)", border: "#94a3b8" };

// Status label + pill color for detail panel
const STATUS_META = {
  active:       { label: "Active",       pill: "bg-emerald-100 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-400" },
  healthy:      { label: "Healthy",      pill: "bg-emerald-100 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-400" },
  completed:    { label: "Completed",    pill: "bg-emerald-100 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-400" },
  stale:        { label: "Stale",        pill: "bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-400" },
  needs_review: { label: "Needs Review", pill: "bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-400" },
  draft:        { label: "Draft",        pill: "bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-400" },
  superseded:   { label: "Superseded",   pill: "bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-400" },
  blocked:      { label: "Blocked",      pill: "bg-red-100 dark:bg-red-900/40 text-red-700 dark:text-red-400" },
  deprecated:   { label: "Deprecated",   pill: "bg-red-100 dark:bg-red-900/40 text-red-700 dark:text-red-400" },
  rejected:     { label: "Rejected",     pill: "bg-red-100 dark:bg-red-900/40 text-red-700 dark:text-red-400" },
};

// Time → short badge text
const TEMPORAL_BADGE = { current: "Now", future: "Next", past: "Past", unknown: "" };

// Temporal detail for side panel
const TEMPORAL_META = {
  current: { label: "Now",  pill: "bg-sky-100 dark:bg-sky-900/40 text-sky-700 dark:text-sky-400" },
  future:  { label: "Next", pill: "bg-violet-100 dark:bg-violet-900/40 text-violet-700 dark:text-violet-400" },
  past:    { label: "Past", pill: "bg-slate-100 dark:bg-black text-slate-500" },
  unknown: { label: "Unknown", pill: "bg-slate-100 dark:bg-black text-slate-400" },
};

// Edge origin → visual style
const EDGE_ORIGIN_STYLE = {
  deterministic: { lineStyle: "solid", width: 2, opacity: 0.76, label: "Deterministic", color: "#3b82f6" },
  extracted:     { lineStyle: "solid", width: 1.6, opacity: 0.56, label: "Extracted", color: "#8b5cf6" },
  proposed:      { lineStyle: "dotted", width: 1.4, opacity: 0.40, label: "Proposed", color: "#94a3b8" },
  ai_proposed:   { lineStyle: "dashed", width: 1.5, opacity: 0.44, label: "AI Proposed", color: "#f59e0b" },
  human_verified:{ lineStyle: "solid", width: 2.4, opacity: 0.88, label: "Human Verified", color: "#059669" },
};

const BOARD_MAX_ZOOM = 1.12;
const LOD_MACRO_ZOOM = 0.58;
const LOD_CARD_ZOOM = BOARD_READABLE_ZOOM;
const LOD_NODE_CLASSES = "lod-macro lod-compact lod-card";
const LOD_EDGE_CLASSES = "lod-macro-edge lod-detail-edge";
const COMPONENT_CARD_WIDTH = 280;
const COMPONENT_CARD_HEIGHT = 112;
const COMPONENT_CARD_TEXT_MAX_WIDTH = COMPONENT_CARD_WIDTH - 36;
const CARD_OVERLAY_TITLE_PX = 11;
const CARD_OVERLAY_META_PX = 9.5;
const GROUP_HEADER_HEIGHT_PX = 30;
const GROUP_HUB_CHIP_HEIGHT_PX = 42;
const GROUP_HEADER_FLOAT_GAP_PX = 10;
const GROUP_HEADER_BAND_PX = 40;
const SOURCE_HUB_CARD_WIDTH = 164;
const SOURCE_HUB_CARD_HEIGHT = 116;
const SOURCE_HUB_TEXT_MAX_WIDTH = SOURCE_HUB_CARD_WIDTH - 34;

// Source type icon mapping
const SOURCE_TYPE_ICONS = {
  github_issue: "GH Issue",
  github_pr: "GH PR",
  github: "GitHub",
  ai_session: "AI Session",
  local: "Local",
  slack: "Slack",
  zoom: "Zoom",
  gmail: "Gmail",
  gdrive: "Drive",
};

const SOURCE_FAMILY_META = {
  github: { label: "GitHub", icon: GitPullRequest, color: "#24292e", bg: "bg-slate-100 dark:bg-black", text: "text-slate-700 dark:text-neutral-200" },
  agent: { label: "AI Session", icon: Bot, color: "#7c3aed", bg: "bg-violet-100 dark:bg-violet-900/30", text: "text-violet-700 dark:text-violet-300" },
  communication: { label: "Comms", icon: MessageCircle, color: "#0ea5e9", bg: "bg-sky-100 dark:bg-sky-900/30", text: "text-sky-700 dark:text-sky-300" },
  local: { label: "Local", icon: FileText, color: "#64748b", bg: "bg-slate-100 dark:bg-black", text: "text-slate-600 dark:text-neutral-300" },
  other: { label: "Source", icon: Layers3, color: "#14b8a6", bg: "bg-teal-100 dark:bg-teal-900/30", text: "text-teal-700 dark:text-teal-300" },
};

const SOURCE_VISUALS = {
  github: { icon: "GH", label: "GitHub", bg: "rgba(110,118,129,0.14)", border: "#6e7681", color: "#e6edf3", logo: GITHUB_LOGO_URI },
  gmail: { icon: "GM", label: "Gmail", bg: "rgba(14,165,233,0.18)", border: "#38bdf8", color: "#e0f2fe", logo: imgGmail },
  slack: { icon: "SL", label: "Slack", bg: "rgba(29,155,209,0.14)", border: "#1d9bd1", color: "#e8f6fc", logo: SLACK_LOGO_URI },
  agent: { icon: "AI", label: "AI Session", bg: "rgba(124,58,237,0.18)", border: "#8b5cf6", color: "#ede9fe", logo: AI_LOGO_URI },
  local: { icon: "DOC", label: "Document", bg: "rgba(148,163,184,0.16)", border: "#94a3b8", color: "#e2e8f0", logo: "" },
  other: { icon: "SRC", label: "Source", bg: "rgba(20,184,166,0.14)", border: "#14b8a6", color: "#ccfbf1", logo: "" },
};

const GRAPH_GROUP_META = {
  decisions: { label: "Decisions", color: "#d97706", short: "Decisions" },
  work: { label: "Active Work", color: "#3b82f6", short: "Work" },
  risks: { label: "Risks & Blockers", color: "#ef4444", short: "Risks" },
  github: { label: "GitHub", color: "#6e7681", short: "GitHub" },
  gmail: { label: "Gmail Inbox", color: "#38bdf8", short: "Gmail" },
  slack: { label: "Slack", color: "#1d9bd1", short: "Slack" },
  localDocs: { label: "Documents", color: "#94a3b8", short: "Docs" },
  agents: { label: "AI Sessions", color: "#8b5cf6", short: "AI" },
  sources: { label: "Sources", color: "#14b8a6", short: "Sources" },
  product: { label: "Product", color: "#22c55e", short: "Product" },
  repo: { label: "Repository", color: "#64748b", short: "Repo" },
  other: { label: "Other Context", color: "#94a3b8", short: "Other" },
};

const GROUP_HEADER_LOGOS = {
  github: GITHUB_LOGO_URI,
  slack: SLACK_LOGO_URI,
  gmail: imgGmail,
  agents: AI_LOGO_URI,
};

const REPO_TYPE_COLORS = {
  repo: "#0f172a",
  area: "#2563eb",
  folder: "#2563eb",
  file: "#64748b",
  technology: "#7c3aed",
};

function shortLabel(value, maxWords = 5) {
  const words = String(value || "Untitled").trim().split(/\s+/).filter(Boolean);
  if (words.length <= maxWords) return words.join(" ");
  return `${words.slice(0, maxWords).join(" ")}...`;
}

function compactCardText(value, maxChars = 80) {
  const clean = String(value || "").replace(/\s+/g, " ").trim();
  if (!clean) return "";
  if (clean.length <= maxChars) return clean;
  const clipped = clean.slice(0, Math.max(0, maxChars - 3)).trim();
  const boundary = clipped.search(/\s+\S*$/);
  const atWord = boundary > Math.floor(maxChars * 0.55) ? clipped.slice(0, boundary).trim() : clipped;
  return `${atWord.replace(/[,:;./\\-]+$/, "").trim()}...`;
}

function cleanDisplayFragment(value) {
  return String(value || "")
    .replace(/\s+/g, " ")
    .replace(/^\[[^\]]+\]\s*/i, "")
    .replace(/^`?\/?`?\s*(Task|Note|Status|Decision|Blocker)\s*:\s*/i, "$1: ")
    .replace(/^[,.;:)\]\s\/-]+/, "")
    .trim();
}

function isWeakFragment(value) {
  const text = cleanDisplayFragment(value);
  if (!text) return true;
  if (text.length < 12) return true;
  if (/^[a-z]\s*[,.;:)/]/i.test(text)) return true;
  if (/^[a-z]{1,2}\s*[/)]/.test(text)) return true;
  if (/^[,.;:)]/.test(String(value || "").trim())) return true;
  const opens = (text.match(/\(/g) || []).length;
  const closes = (text.match(/\)/g) || []).length;
  return closes > opens;
}

function sentenceCase(value) {
  const text = cleanDisplayFragment(value);
  if (!text) return "";
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function toolLabel(value) {
  const raw = String(value || "").replace(/_/g, " ").trim();
  if (!raw) return "AI";
  if (/codex/i.test(raw)) return "Codex";
  if (/claude/i.test(raw)) return "Claude";
  if (/opencode|open code/i.test(raw)) return "OpenCode";
  return raw.replace(/\b\w/g, (m) => m.toUpperCase());
}

function factKindLabel(component = {}, fallback = "Context") {
  const raw = String(component.fact_type || component.model_name || fallback).replace(/_/g, " ").trim();
  if (/session root/i.test(raw)) return "Session";
  return raw ? raw.replace(/\b\w/g, (m) => m.toUpperCase()) : fallback;
}

function stripSlackNoise(text, channel = "") {
  let clean = String(text || "").replace(/^Slack(?: message)?:\s*/i, "").trim();
  if (channel) {
    const ch = String(channel).replace(/^#/, "");
    clean = clean.replace(new RegExp(`^#?${ch.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\s*:?\\s*`, "i"), "");
  }
  return clean.replace(/\s+/g, " ").trim();
}

function formatCardLabel(lines, maxLines = 2) {
  return lines
    .map((line) => compactCardText(line))
    .filter(Boolean)
    .slice(0, maxLines)
    .join("\n");
}

function layoutGridColumns(itemCount, maxCols = 3) {
  if (itemCount <= 1) return 1;
  if (itemCount <= 4) return 2;
  if (itemCount <= 10) return 3;
  return maxCols;
}

function appendSourceHubChip(container, {
  logo,
  count,
  accent,
  isDark,
  textColor,
  mutedColor,
  headerBg,
}) {
  const chip = document.createElement("div");
  Object.assign(chip.style, {
    display: "inline-flex",
    alignItems: "center",
    gap: "8px",
    padding: "6px 12px",
    borderRadius: "12px",
    background: headerBg,
    border: `1.5px solid ${accent}`,
    boxShadow: isDark ? "0 2px 10px rgba(0,0,0,0.28)" : "0 2px 8px rgba(15,23,42,0.08)",
  });

  if (logo) {
    const img = document.createElement("img");
    img.src = logo;
    img.alt = "";
    Object.assign(img.style, {
      width: "28px",
      height: "28px",
      borderRadius: "6px",
      objectFit: "contain",
      background: "#fff",
      padding: "2px",
      flexShrink: "0",
    });
    chip.appendChild(img);
  }

  const countEl = document.createElement("span");
  countEl.textContent = String(count);
  Object.assign(countEl.style, {
    color: textColor,
    fontSize: `${CARD_OVERLAY_TITLE_PX + 2}px`,
    fontWeight: "800",
    lineHeight: "1",
  });
  chip.appendChild(countEl);

  const unit = document.createElement("span");
  unit.textContent = "items";
  Object.assign(unit.style, {
    color: mutedColor,
    fontSize: `${CARD_OVERLAY_META_PX}px`,
    fontWeight: "600",
    lineHeight: "1",
  });
  chip.appendChild(unit);
  container.appendChild(chip);
  return chip;
}

function componentAttentionBadge(component = {}) {
  const status = String(component.status || "").toLowerCase();
  const parts = [];
  if (status === "needs_review") parts.push("Needs review");
  else if (status === "stale") parts.push("Stale");
  else if (status === "blocked") parts.push("Blocked");
  if (component.confidence != null && component.confidence < 0.6) {
    parts.push(`Low confidence ${Math.round(component.confidence * 100)}%`);
  } else if (component.temporal === "future") {
    parts.push("Next");
  } else if (component.temporal === "past") {
    parts.push("Past");
  }
  return parts.join(" · ");
}

// Strip common model-type prefixes that the containing box already communicates
function stripModelPrefix(name) {
  return String(name || "")
    .replace(/^(Action|Actions|Blocker|Blockers|Decision|Decisions|Risk|Risks|Outcome|Outcomes|Discussion|Fact|Task|Tasks|Feature|Features|Metric|Metrics|Meeting|Agent Session|AI step):\s*/i, "")
    .trim();
}

function sourceFamily(component = {}) {
  const raw = [
    component.source_type,
    component.fact_type,
    component.model_name,
    component.source_metadata_summary?.tool,
    component.source_metadata_summary?.item_type,
  ].filter(Boolean).join(" ").toLowerCase();

  if (/(github|pull_request|github_pr|github_issue|\bpr\b|issue|changed_file|commit)/.test(raw)) return "github";
  if (/(agent_session|ai_context|codex|claude|opencode|open_code|kimi|glm|ai_step|ai_task|ai_decision)/.test(raw)) return "agent";
  if (/(slack|discord|gmail|email|zoom|meeting|message)/.test(raw)) return "communication";
  if (/(local|browser_upload|paste|document|gdrive|notion|source)/.test(raw)) return "local";
  return "other";
}

function sourceKind(component = {}) {
  const rawSource = String(component.source_type || "").toLowerCase();
  const itemType = String(component.source_metadata_summary?.item_type || "").toLowerCase();
  const model = String(component.model_name || "").toLowerCase();
  const fact = String(component.fact_type || "").toLowerCase();

  if (rawSource.includes("gmail") || model.includes("email") || model.includes("gmail")) return "gmail";
  if (rawSource.includes("slack") || model.includes("message")) return "slack";
  if (rawSource.includes("github") || itemType.includes("pull") || itemType.includes("issue") || /pull_request|issue|pr/.test(fact)) return "github";
  if (rawSource.includes("agent") || rawSource.includes("ai_context") || /agent|ai_/.test(fact)) return "agent";
  if (rawSource.includes("local") || rawSource.includes("gdrive") || rawSource.includes("document")) return "local";
  return sourceFamily(component) === "agent" ? "agent" : sourceFamily(component) === "github" ? "github" : "other";
}

function sourceVisual(component = {}) {
  return SOURCE_VISUALS[sourceKind(component)] || SOURCE_VISUALS.other;
}

function sourceMetaEntries(meta = {}, max = 8) {
  const hiddenKeys = new Set(["permalink"]);
  return Object.entries(meta || {})
    .filter(([key, value]) => !hiddenKeys.has(key) && value !== null && value !== undefined && value !== "")
    .slice(0, max);
}

function formatMetaKey(key = "") {
  return String(key).replace(/_/g, " ");
}

function slackContextRows(node = {}) {
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

function slackPermalink(node = {}) {
  return node.source_metadata_summary?.permalink || node.source_url || "";
}

function isDeterministicMentionEdge(edge = {}) {
  const rel = String(edge.label || edge.displayLabel || "").toLowerCase();
  return edge.origin === "deterministic" && rel.includes("mentions");
}

function connectorCardParts(component = {}, cleanName = "") {
  const kind = sourceKind(component);
  const meta = component.source_metadata_summary || {};
  const valueSnippet = compactCardText(component.excerpt || meta.snippet || component.value, 88);

  if (kind === "gmail") {
    const title = meta.subject || cleanName.replace(/^Email:\s*/i, "");
    return {
      title: title || "Email",
      context: meta.from ? meta.from : "",
      snippet: valueSnippet,
    };
  }

  if (kind === "slack") {
    const channel = meta.channel_name ? `#${String(meta.channel_name).replace(/^#/, "")}` : "";
    const author = meta.author_name || meta.user_name || meta.author || "";
    const parsed = stripSlackNoise(cleanName, channel);
    const messageLead = compactCardText(
      stripSlackNoise(component.display_title, channel)
      || parsed.split(":").slice(1).join(":").trim()
      || parsed,
      52,
    );
    const snippetSource = stripSlackNoise(component.excerpt || meta.snippet || component.value, channel);
    const snippet = snippetSource
      && snippetSource.toLowerCase() !== messageLead.toLowerCase()
      && !messageLead.toLowerCase().includes(snippetSource.slice(0, 28).toLowerCase())
      ? compactCardText(snippetSource, 64)
      : "";
    const contextParts = [];
    if (channel && messageLead && !messageLead.toLowerCase().includes(channel.toLowerCase())) {
      contextParts.push(channel);
    }
    if (author) contextParts.push(author);
    return {
      title: messageLead || channel || "Slack message",
      context: contextParts.join(" · "),
      snippet,
    };
  }

  if (kind === "github") {
    const number = meta.number;
    const itemType = String(meta.item_type || "").toLowerCase();
    const isPr = itemType.includes("pull") || /\bpr\b/i.test(cleanName);
    const rawTitle = meta.title
      || cleanName.replace(/^(?:GH\s+)?(?:Issue|PR)\s*#?\d+\s*:?\s*/i, "")
      || stripModelPrefix(cleanName);
    const prefix = number ? (isPr ? `PR #${number}` : `Issue #${number}`) : (isPr ? "PR" : "Issue");
    const title = rawTitle ? `${prefix}: ${compactCardText(rawTitle, 42)}` : prefix;
    const repo = meta.repo || meta.repository || "";
    const repoShort = repo ? String(repo).split("/").slice(-2).join("/") : "";
    const state = meta.state || meta.merged_state || "";
    const stateLabel = state ? String(state).replace(/_/g, " ") : "";
    const context = [repoShort, stateLabel].filter(Boolean).join(" · ");
    const snippetRaw = compactCardText(component.excerpt || meta.snippet || component.value, 64);
    const snippet = snippetRaw
      && !title.toLowerCase().includes(snippetRaw.toLowerCase())
      && snippetRaw.toLowerCase() !== stateLabel.toLowerCase()
      && snippetRaw.toLowerCase() !== repoShort.toLowerCase()
      ? snippetRaw
      : "";
    return { title, context, snippet };
  }

  if (kind === "agent") {
    const tool = toolLabel(meta.tool || meta.agent || "");
    const session = meta.session_id ? `…${String(meta.session_id).slice(-6)}` : "";
    const rawTitle = stripModelPrefix(component.display_title || cleanName);
    const readableTitle = isWeakFragment(rawTitle)
      ? `${factKindLabel(component)} from ${tool} session`
      : sentenceCase(rawTitle);
    const readableSnippet = isWeakFragment(valueSnippet) || valueSnippet === readableTitle ? "" : valueSnippet;
    return {
      title: compactCardText(readableTitle, 76) || `${tool} session`,
      context: [tool, session].filter(Boolean).join(" · "),
      snippet: readableSnippet,
    };
  }

  if (kind === "local") {
    const path = meta.path || meta.filename || "";
    const fileName = path ? String(path).split("/").pop() : "";
    const rawTitle = stripModelPrefix(component.display_title || cleanName);
    return {
      title: compactCardText(isWeakFragment(rawTitle) ? `Document fact from ${fileName || "local source"}` : sentenceCase(rawTitle), 76) || fileName || "Document",
      context: fileName && !cleanName.includes(fileName) ? fileName : "",
      snippet: valueSnippet,
    };
  }

  return null;
}

function buildComponentCardContent(component = {}, cleanName = "", modelName = "", { boardMode = false } = {}) {
  const connector = connectorCardParts(component, cleanName);
  let title;
  let context = "";
  let detail = "";

  if (connector) {
    ({ title, context = "", snippet: detail = "" } = connector);
  } else {
    const rawTitle = stripModelPrefix(component.display_title || cleanName);
    title = compactCardText(
      isWeakFragment(rawTitle) ? `${factKindLabel(component)} from ${sourceFamilyLabel(component)}` : sentenceCase(rawTitle),
      76,
    ) || shortLabel(cleanName, 6);
    const domain = usefulDomainLabel(component, modelName);
    if (domain && !String(title).toLowerCase().includes(domain.toLowerCase())) {
      context = domain;
    }
    detail = compactCardText(component.excerpt || component.value, 88);
  }

  if (detail && (detail === title || String(title).includes(detail.slice(0, 32)))) {
    detail = "";
  }

  const cardLines = boardMode
    ? [title, context, detail].map((line) => compactCardText(line, 98)).filter(Boolean).slice(0, 3)
    : [title, context, detail, componentAttentionBadge(component)]
        .map((line) => compactCardText(line, 98))
        .filter(Boolean)
        .slice(0, 3);
  const cardLabel = cardLines.join("\n");
  const compactLabel = compactCardText(title, 54) || shortLabel(cleanName, 5);

  return { displayName: title, compactLabel, cardLabel, cardTitle: title, cardContext: context, cardDetail: detail };
}

function usefulDomainLabel(component = {}, modelName = "") {
  const fact = String(component.fact_type || "").replace(/_/g, " ").trim();
  if (!fact || /^(fact|email|message|document)$/i.test(fact)) {
    return domainLabel(modelName);
  }
  return fact;
}

function graphGroup(component = {}, modelName = "") {
  const family = sourceFamily(component);
  const kind = sourceKind(component);
  const fact = String(component.fact_type || "").toLowerCase();
  const model = String(modelName || component.model_name || "").toLowerCase();
  const status = String(component.status || "").toLowerCase();

  if (family === "github") return "github";
  if (family === "agent") return "agents";
  if (/(blocker|risk|review_finding|pr_review_finding)/.test(fact) || /(risk|blocker)/.test(model) || status === "blocked") return "risks";
  if (/decision/.test(fact) || /decision/.test(model)) return "decisions";
  if (/(task|action_item|open_question|issue)/.test(fact) || /(task|issue)/.test(model)) return "work";
  if (/(feature|product|metric|customer|user)/.test(fact) || /(feature|product|metric|customer|user)/.test(model)) return "product";
  if (/(repo|file|changed_file|commit)/.test(fact) || /(repo|engineering)/.test(model)) return "repo";
  if (kind === "gmail") return "gmail";
  if (kind === "slack") return "slack";
  if (kind === "local") return "localDocs";
  if (family === "local" || family === "communication") return "sources";
  return "other";
}

function resolveGraphGroup(component, modelName, layoutMode) {
  if (layoutMode === "board") return boardGraphGroup(component, sourceKind, sourceFamily);
  return graphGroup(component, modelName);
}

function sourceFamilyLabel(component = {}) {
  return SOURCE_FAMILY_META[sourceFamily(component)]?.label || "Source";
}

function componentVisuals(component = {}, isGap = false) {
  if (isGap) {
    return {
      bg: "#fff1f2",
      border: "#ef4444",
      stripe: "#ef4444",
    };
  }

  const kind = sourceKind(component);
  const family = sourceFamily(component);
  const status = String(component.status || "").toLowerCase();
  const byKind = {
    github: { bg: "#f8fafc", border: "#6e7681", stripe: "#8b949e" },
    slack: { bg: "#f0f9ff", border: "#1d9bd1", stripe: "#36c5f0" },
    gmail: { bg: "#f0f9ff", border: "#38bdf8", stripe: "#7dd3fc" },
    agent: { bg: "#f5f3ff", border: "#8b5cf6", stripe: "#a78bfa" },
    local: { bg: "#f8fafc", border: "#94a3b8", stripe: "#cbd5e1" },
  };
  const byFamily = {
    github: { bg: "#f8fafc", border: "#6e7681", stripe: "#8b949e" },
    agent: { bg: "#f5f3ff", border: "#8b5cf6", stripe: "#a78bfa" },
    communication: { bg: "#f0f9ff", border: "#1d9bd1", stripe: "#36c5f0" },
    local: { bg: "#f8fafc", border: "#94a3b8", stripe: "#cbd5e1" },
    other: { bg: "#f8fafc", border: "#94a3b8", stripe: "#cbd5e1" },
  };
  const palette = byKind[kind] || byFamily[family] || byFamily.other;

  if (status === "needs_review" || status === "proposed" || status === "draft") {
    return { ...palette, border: "#f59e0b" };
  }
  if (status === "blocked" || status === "stale" || status === "deprecated") {
    return { ...palette, border: "#ef4444" };
  }
  return palette;
}

function fitGraphViewport(cy, viewMode, graphLayout = "board", { preferReadableBoard = false } = {}) {
  if (!cy) return;
  const padding = viewMode === "repo" ? 72 : 24;
  cy.resize();
  const ext = cy.elements().boundingBox();
  if (!ext.w || !ext.h) {
    cy.fit(undefined, padding);
    applyGraphLod(cy);
    return;
  }
  const fitZoom = Math.min(
    (cy.width() - padding * 2) / ext.w,
    (cy.height() - padding * 2) / ext.h,
  );
  cy.minZoom(Math.max(0.05, fitZoom * 0.78));
  cy.fit(undefined, padding);
  if (preferReadableBoard && shouldUseReadableBoardViewport({ viewMode, graphLayout, fitZoom })) {
    const targetZoom = Math.min(BOARD_READABLE_ZOOM, cy.maxZoom ? cy.maxZoom() : BOARD_READABLE_ZOOM);
    cy.zoom(targetZoom);
    cy.pan(boardReadablePan(ext, targetZoom));
  }
  applyGraphLod(cy);
}

function graphLod(zoom) {
  if (zoom <= LOD_MACRO_ZOOM) return "lod-macro";
  if (zoom < LOD_CARD_ZOOM) return "lod-compact";
  return "lod-card";
}

function applyGraphLod(cy) {
  const lod = graphLod(cy.zoom());
  cy.batch(() => {
    cy.nodes(".explore-node").removeClass(LOD_NODE_CLASSES);
    cy.nodes("[type='component']:not(.explore-node), .source-hub, .model-node").removeClass(LOD_NODE_CLASSES).addClass(lod);
    cy.edges("[edgeType='relationship']")
      .removeClass(LOD_EDGE_CLASSES)
      .addClass(lod === "lod-macro" ? "lod-macro-edge" : "lod-detail-edge");
  });
  return lod;
}

function buildGraphStats(data) {
  const components = data?.components || [];
  const relationships = data?.relationships || [];
  const connected = new Set();
  relationships.forEach((r) => {
    connected.add(r.source_component_id);
    connected.add(r.target_component_id);
  });
  return {
    components: components.length,
    relationships: relationships.length,
    blockers: components.filter((c) => /blocker|risk|review_finding/.test(String(c.fact_type || "").toLowerCase()) || c.status === "blocked").length,
    github: components.filter((c) => sourceFamily(c) === "github").length,
    agents: components.filter((c) => sourceFamily(c) === "agent").length,
    proposedEdges: relationships.filter((r) => ["proposed", "ai_proposed"].includes(r.origin || "proposed")).length,
    isolated: components.filter((c) => !connected.has(c.id)).length,
  };
}

function buildGraphOverview(cy) {
  try {
    if (!cy || (typeof cy.destroyed === "function" && cy.destroyed())) return null;
    const visibleNodes = cy.nodes().filter((node) => node.visible());
    if (!visibleNodes.length) {
      return { nodes: [], edges: [], viewport: null, bounds: null };
    }

    const zoom = cy.zoom() || 1;
    const pan = cy.pan();
    const viewport = {
      x: -pan.x / zoom,
      y: -pan.y / zoom,
      w: cy.width() / zoom,
      h: cy.height() / zoom,
    };
    const rawBounds = visibleNodes.boundingBox({
      includeLabels: false,
      includeNodes: true,
    });
    const x1 = Math.min(rawBounds.x1, viewport.x);
    const y1 = Math.min(rawBounds.y1, viewport.y);
    const x2 = Math.max(rawBounds.x2, viewport.x + viewport.w);
    const y2 = Math.max(rawBounds.y2, viewport.y + viewport.h);

    const nodes = [];
    visibleNodes.forEach((node) => {
      const box = node.boundingBox({ includeLabels: false, includeNodes: true });
      if (![box.x1, box.y1, box.w, box.h].every(Number.isFinite)) return;
      const type = node.data("type") || "";
      nodes.push({
        id: node.id(),
        type,
        x: box.x1,
        y: box.y1,
        w: Math.max(1, box.w),
        h: Math.max(1, box.h),
        fill: node.data("bgColor") || (type === "model" ? "transparent" : "#94a3b8"),
        stroke: node.data("borderColor") || node.data("modelColor") || "#64748b",
      });
    });

    const edges = [];
    cy.edges().forEach((edge) => {
      const source = edge.source();
      const target = edge.target();
      if (!edge.visible() || !source.visible() || !target.visible()) return;
      const sourcePos = source.position();
      const targetPos = target.position();
      if (![sourcePos.x, sourcePos.y, targetPos.x, targetPos.y].every(Number.isFinite)) return;
      edges.push({
        id: edge.id(),
        x1: sourcePos.x,
        y1: sourcePos.y,
        x2: targetPos.x,
        y2: targetPos.y,
        color: edge.data("edgeColor") || "#94a3b8",
      });
    });

    return {
      bounds: {
        x: x1,
        y: y1,
        w: Math.max(1, x2 - x1),
        h: Math.max(1, y2 - y1),
      },
      viewport,
      nodes,
      edges: edges.slice(0, 260),
    };
  } catch (_) {
    return null;
  }
}

function componentMatchesSearch(component, query) {
  if (!query) return true;
  const haystack = [
    component.name,
    component.value,
    component.fact_type,
    component.source_type,
    component.provenance,
    component.excerpt,
    JSON.stringify(component.source_metadata_summary),
  ].filter(Boolean).join(" ").toLowerCase();
  return haystack.includes(query);
}

// Map model name to a short domain label for the type chip
function domainLabel(modelName) {
  const k = (modelName || "").toLowerCase().trim();
  if (k.startsWith("decision"))  return "Decision";
  if (k.startsWith("risk"))      return "Risk";
  if (k.startsWith("task"))      return "Task";
  if (k.startsWith("feature"))   return "Feature";
  if (k.startsWith("metric"))    return "Metric";
  if (k.startsWith("company"))   return "Company";
  if (k.startsWith("product"))   return "Product";
  if (k.startsWith("customer") || k.startsWith("user")) return "Customer";
  if (k === "agent session" || k === "claude" || k === "codex" || k.startsWith("agent")) return "AI";
  if (k.startsWith("meeting"))   return "Meeting";
  if (k.startsWith("person") || k.startsWith("team")) return "Person";
  if (k.startsWith("engineering") || k.startsWith("repo")) return "Eng";
  if (k.startsWith("ops"))       return "Ops";
  return modelName ? modelName.split(" ")[0] : "Fact";
}

export default function GraphView() {
  const containerRef = useRef(null);
  const logoLayerRef = useRef(null);
  const cyRef = useRef(null);
  const searchInputRef = useRef(null);
  const [searchParams, setSearchParams] = useSearchParams();
  const graphLayout = searchParams.get("graph") === "explore" ? "explore" : "board";
  const setGraphLayout = useCallback((layout) => {
    const next = new URLSearchParams(searchParams);
    if (layout === "board") next.delete("graph");
    else next.set("graph", layout);
    setSearchParams(next, { replace: true });
  }, [searchParams, setSearchParams]);
  const { theme } = useTheme();
  const { selectedId, setSelectedId } = useWorkspaceSelection();
  const { data: workspaces = [], isLoading: workspacesLoading } = useWorkspaces();
  const activeWorkspaceId = resolveWorkspaceId(workspaces, selectedId);
  const activeWorkspace = activeWorkspaceId
    ? workspaces.find((w) => w.id === activeWorkspaceId) || null
    : null;
  const workspaceQueryString = activeWorkspaceId
    ? `?${new URLSearchParams({ workspace_id: activeWorkspaceId }).toString()}`
    : "";
  const [viewMode, setViewMode] = useState("knowledge");
  const [graphData, setGraphData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [selectedNode, setSelectedNode] = useState(null);
  const [selectedEdge, setSelectedEdge] = useState(null);
  const [edgeReviewLoading, setEdgeReviewLoading] = useState(false);
  const [edgeReviewError, setEdgeReviewError] = useState(null);
  const [filters, setFilters] = useState({
    model: "",
    source_type: "",
    status: "",
    temporal: "",
    confidence_threshold: 0,
    relationship_origin: "",
    search: "",
  });
  const [building, setBuilding] = useState(false);
  const [buildResult, setBuildResult] = useState(null);
  const [agentStatus, setAgentStatus] = useState(null);
  const [showAiSettings, setShowAiSettings] = useState(false);
  const [aiSettings, setAiSettings] = useState(() => {
    try { return JSON.parse(localStorage.getItem("ce_ai_settings") || "{}"); }
    catch { return {}; }
  });
  const [showAsk, setShowAsk] = useState(false);
  const [askQuery, setAskQuery] = useState("");
  const [askResult, setAskResult] = useState(null);
  const [askLoading, setAskLoading] = useState(false);
  const [askError, setAskError] = useState(null);
  const askInputRef = useRef(null);
  const [boardLens, setBoardLens] = useState("all");
  const [exploreDepth, setExploreDepth] = useState(1);
  const [showTrustEdges, setShowTrustEdges] = useState(false);
  const [graphOverview, setGraphOverview] = useState(null);
  const [showRefine, setShowRefine] = useState(false);

  // Agents sidebar
  const [showAgents, setShowAgents] = useState(false);
  const [gapReport, setGapReport]     = useState(null);
  const [gapLoading, setGapLoading]   = useState(false);
  const [gapError, setGapError]       = useState(null);
  const [packResult, setPackResult]   = useState(null);
  const [packLoading, setPackLoading] = useState(false);
  const [packError, setPackError]     = useState(null);
  const [packCopied, setPackCopied]   = useState(false);
  const [relReport, setRelReport]     = useState(null);
  const [relLoading, setRelLoading]   = useState(false);
  const [relError, setRelError]       = useState(null);

  // Side panels
  const [showSidePanel, setShowSidePanel] = useState(false);
  const [sidePanelTab, setSidePanelTab] = useState("coverage");
  const [workLens, setWorkLens] = useState(null);
  const [workLensLoading, setWorkLensLoading] = useState(false);

  async function callAgent(endpoint, setLoading, setResult, setError, extraBody = {}) {
    setLoading(true); setResult(null); setError(null);
    const s = getAiSettingsSaved();
    try {
      const body = {
        api_key: s.api_key || null,
        model: s.model || null,
        ...extraBody,
      };
      if (activeWorkspaceId) body.workspace_id = activeWorkspaceId;
      const res = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setResult(await res.json());
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  }

  async function copyPack() {
    if (!packResult) return;
    await navigator.clipboard.writeText(packResult.content);
    setPackCopied(true);
    setTimeout(() => setPackCopied(false), 2000);
  }

  const fitGraph = useCallback(() => {
    const cy = cyRef.current;
    if (!cy) return;
    fitGraphViewport(cy, viewMode, graphLayout, { preferReadableBoard: false });
  }, [viewMode, graphLayout]);

  const changeGraphZoom = useCallback((delta) => {
    const cy = cyRef.current;
    if (!cy) return;
    const nextZoom = Math.max(cy.minZoom(), Math.min(cy.maxZoom(), cy.zoom() + delta));
    cy.zoom({ level: nextZoom, renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 } });
  }, []);

  const centerGraphOnOverviewPoint = useCallback((point) => {
    const cy = cyRef.current;
    if (!cy || !point) return;
    const zoom = cy.zoom();
    cy.animate({
      pan: {
        x: cy.width() / 2 - point.x * zoom,
        y: cy.height() / 2 - point.y * zoom,
      },
    }, { duration: 120 });
  }, []);

  const focusGraphNode = useCallback((nodeId, edgeId) => {
    const cy = cyRef.current;
    if (!cy || !nodeId) return;
    const ele = cy.getElementById(nodeId);
    if (!ele.length || ele.data("type") !== "component") return;

    cy.elements().removeClass("search-match");
    cy.elements().unselect();
    ele.addClass("search-match");
    ele.select();
    cy.animate(
      { center: { eles: ele }, zoom: Math.max(Math.min(cy.zoom() * 1.1, 2), 1) },
      { duration: 200 },
    );

    setSelectedNode({ ...ele.data(), connected: buildNodeConnections(cy, nodeId) });
    setSelectedEdge(null);
    setEdgeReviewError(null);

    if (edgeId) {
      const edgeEle = cy.getElementById(edgeId);
      if (edgeEle.length) edgeEle.select();
    }
  }, []);

  useEffect(() => {
    async function fetchGraph() {
      if (viewMode === "knowledge" && workspacesLoading) return;
      if (viewMode === "knowledge" && !activeWorkspaceId) {
        setGraphData({ models: [], components: [], relationships: [] });
        setSelectedNode(null);
        setSelectedEdge(null);
        setLoading(false);
        return;
      }
      try {
        setLoading(true);
        setError(null);
        setSelectedNode(null);
        setSelectedEdge(null);
        const res = await fetch(
          viewMode === "repo" ? "/api/repo/graph" : `/api/graph${workspaceQueryString}`,
        );
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        setGraphData(data);
      } catch (err) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    }
    fetchGraph();
  }, [activeWorkspaceId, viewMode, workspaceQueryString, workspacesLoading]);

  useEffect(() => {
    fetch("/api/graph/agent-status")
      .then((r) => r.json())
      .then(setAgentStatus)
      .catch(() => {});
  }, []);

  useEffect(() => {
    async function fetchWorkLens() {
      if (workspacesLoading) return;
      if (!activeWorkspaceId) {
        setWorkLens(null);
        setWorkLensLoading(false);
        return;
      }
      setWorkLensLoading(true);
      try {
        const res = await fetch(`/api/work-lens${workspaceQueryString}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        setWorkLens(await res.json());
      } catch (e) {
        setWorkLens(null);
      } finally {
        setWorkLensLoading(false);
      }
    }
    fetchWorkLens();
    const interval = setInterval(fetchWorkLens, 30000);
    return () => clearInterval(interval);
  }, [activeWorkspaceId, workspaceQueryString, workspacesLoading]);

  async function handleBuildGraph() {
    if (!activeWorkspaceId) {
      setBuildResult({ error: "Select a workspace before building the graph." });
      return;
    }
    setBuilding(true);
    setBuildResult(null);
    const saved = (() => { try { return JSON.parse(localStorage.getItem("ce_ai_settings") || "{}"); } catch { return {}; } })();
    try {
      const body = { limit: 100, workspace_id: activeWorkspaceId };
      if (saved.api_key) body.api_key = saved.api_key;
      if (saved.model) body.model = saved.model;
      const res = await fetch("/api/graph/build", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setBuildResult(data);
      const graphRes = await fetch(`/api/graph${workspaceQueryString}`);
      if (graphRes.ok) setGraphData(await graphRes.json());
      fetch("/api/graph/agent-status").then((r) => r.json()).then(setAgentStatus).catch(() => {});
    } catch (e) {
      setBuildResult({ error: e.message });
    } finally {
      setBuilding(false);
    }
  }

  useEffect(() => {
    if (!buildResult || buildResult.error) return undefined;
    const timeoutId = setTimeout(() => setBuildResult(null), 5000);
    return () => clearTimeout(timeoutId);
  }, [buildResult]);

  async function handleAsk(e) {
    e?.preventDefault();
    const q = askQuery.trim();
    if (!q) return;
    if (!activeWorkspaceId) {
      setAskError("Select a workspace before asking the graph.");
      return;
    }
    setAskLoading(true);
    setAskError(null);
    setAskResult(null);
    const saved = (() => { try { return JSON.parse(localStorage.getItem("ce_ai_settings") || "{}"); } catch { return {}; } })();
    try {
      const body = {
        question: q,
        workspace_id: activeWorkspaceId,
        top_k: 8,
        min_confidence: filters.confidence_threshold || 0,
        hybrid: true,
      };
      if (saved.api_key) body.api_key = saved.api_key;
      if (saved.model)   body.model   = saved.model;
      const res = await fetch("/api/query", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setAskResult(await res.json());
    } catch (err) {
      setAskError(err.message);
    } finally {
      setAskLoading(false);
    }
  }

  async function reviewSelectedEdge(action) {
    if (!selectedEdge?.id) return;
    setEdgeReviewLoading(true);
    setEdgeReviewError(null);
    try {
      const res = await fetch(`/api/relationships/${selectedEdge.id}/review`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const updated = await res.json();
      if (action === "reject") {
        setGraphData((current) => current ? {
          ...current,
          relationships: (current.relationships || []).filter((r) => r.id !== selectedEdge.id),
        } : current);
        setSelectedEdge(null);
      } else {
        setGraphData((current) => current ? {
          ...current,
          relationships: (current.relationships || []).map((r) => (
            r.id === updated.id ? { ...r, ...updated } : r
          )),
        } : current);
        setSelectedEdge((edge) => edge ? { ...edge, ...updated } : edge);
      }
    } catch (err) {
      setEdgeReviewError(err.message);
    } finally {
      setEdgeReviewLoading(false);
    }
  }

  const centerOnSearchMatch = useCallback(() => {
    const cy = cyRef.current;
    const query = filters.search?.trim().toLowerCase();
    if (!cy || !query) return;
    const match = cy.nodes("[type='component']").filter((node) => {
      const data = node.data();
      return componentMatchesSearch(data, query);
    }).first();
    if (!match || match.empty()) return;
    cy.animate({
      center: { eles: match },
      zoom: Math.max(cy.zoom(), LOD_CARD_ZOOM),
    }, { duration: 220 });
    match.addClass("search-match");
    setTimeout(() => match.removeClass("search-match"), 1800);
  }, [filters.search]);

  useEffect(() => {
    const onKeyDown = (event) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        searchInputRef.current?.focus();
        searchInputRef.current?.select();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  const filteredData = useCallback(() => {
    if (!graphData) return { models: [], components: [], relationships: [] };
    if (viewMode === "repo") return graphData;

    const allModels = graphData.models || [];
    const modelNameById = new Map(allModels.map((m) => [m.id, m.name]));
    let components = graphData.components || [];
    let relationships = graphData.relationships || [];

    if (graphLayout === "board" && boardLens !== "all" && boardLens !== "gaps") {
      components = components.filter((c) => passesBoardLens(c, modelNameById.get(c.model_id), boardLens));
    }

    if (filters.model) {
      components = components.filter((c) => c.model_id === filters.model);
    }
    if (filters.source_type) {
      components = components.filter((c) => c.source_type === filters.source_type);
    }
    if (filters.status) {
      components = components.filter((c) => c.status === filters.status);
    }
    if (filters.temporal) {
      components = components.filter((c) => (c.temporal || "unknown") === filters.temporal);
    }
    if (filters.confidence_threshold > 0) {
      components = components.filter((c) => (c.confidence ?? 0) >= filters.confidence_threshold);
    }

    const componentIds = new Set(components.map((c) => c.id));
    relationships = relationships.filter(
      (r) => componentIds.has(r.source_component_id) && componentIds.has(r.target_component_id)
    );

    if (graphLayout === "board" && boardLens === "gaps") {
      components = filterGapsLens(components, relationships);
      const gapIds = new Set(components.map((c) => c.id));
      relationships = relationships.filter(
        (r) => gapIds.has(r.source_component_id) && gapIds.has(r.target_component_id)
      );
    }

    if (filters.relationship_origin) {
      relationships = relationships.filter((r) => (r.origin || "proposed") === filters.relationship_origin);
    }

    if (filters.search && filters.search.trim() && graphLayout !== "explore") {
      const q = filters.search.trim().toLowerCase();
      components = components.filter((c) => componentMatchesSearch(c, q));
      const searchedComponentIds = new Set(components.map((c) => c.id));
      relationships = relationships.filter(
        (r) => searchedComponentIds.has(r.source_component_id) && searchedComponentIds.has(r.target_component_id)
      );
    }

    return { models: allModels, components, relationships };
  }, [graphData, filters, viewMode, boardLens, graphLayout]);

  useEffect(() => {
    if (!containerRef.current || !graphData) return;

    const viewData = filteredData();
    const { models = [], relationships = [] } = viewData;
    const isExplore = graphLayout === "explore" && viewMode === "knowledge";
    const components = isExplore
      ? filterExploreComponents(viewData.components || [], relationships)
      : (viewData.components || []);
    const isBoard = graphLayout === "board" && viewMode === "knowledge";
    const searchQuery = filters.search?.trim().toLowerCase() || "";

    const nodes = [];
    const edges = [];

    const modelNameById = new Map(models.map((m) => [m.id, m.name]));
    const visibleGroups = new Map();
    const groupSourceSummaries = new Map();
    const groupForComponent = (component) => resolveGraphGroup(
      component,
      modelNameById.get(component.model_id),
      isBoard ? "board" : "legacy",
    );
    if (!isExplore) {
      components.forEach((component) => {
        const groupKey = groupForComponent(component);
        if (!visibleGroups.has(groupKey)) {
          visibleGroups.set(groupKey, GRAPH_GROUP_META[groupKey] || GRAPH_GROUP_META.other);
        }
        const kind = sourceKind(component);
        const visual = sourceVisual(component);
        if (!groupSourceSummaries.has(groupKey)) groupSourceSummaries.set(groupKey, new Map());
        const summary = groupSourceSummaries.get(groupKey);
        const current = summary.get(kind) || { ...visual, kind, count: 0 };
        current.count += 1;
        summary.set(kind, current);
      });
    }

    if (viewMode === "repo") {
      (viewData.nodes || []).forEach((node) => {
        nodes.push({
          data: {
            id: node.id,
            label: node.label,
            fullLabel: node.label,
            type: node.type,
            value: node.detail || node.path || node.technology || "",
            status: node.technology || node.type,
            fact_type: node.type,
            bgColor: REPO_TYPE_COLORS[node.type] || "#64748b",
            borderColor: node.type === "technology" ? "#a78bfa" : "#cbd5e1",
          },
          position:
            Number.isFinite(node.x) && Number.isFinite(node.y)
              ? { x: node.x, y: node.y }
              : undefined,
          classes: node.type === "repo" ? "repo-node" : "",
        });
      });

      (viewData.edges || []).forEach((edge) => {
        edges.push({
          data: {
            id: edge.id,
            source: edge.source,
            target: edge.target,
            label: edge.label,
            edgeType: edge.label === "contains" ? "repoContains" : edge.label === "uses" ? "repoUses" : "repoFile",
          },
        });
      });
    } else {
      if (!isExplore) {
        // Strategy groups become compound parent containers. They are backed by source,
        // model, fact type, or relationship metadata; no synthetic facts are invented.
        visibleGroups.forEach((meta, groupKey) => {
          const itemCount = components.filter(
            (c) => groupForComponent(c) === groupKey,
          ).length;
          const hubSummary = groupSourceSummaries.get(groupKey);
          const primaryHub = hubSummary
            ? Array.from(hubSummary.values()).sort((a, b) => b.count - a.count)[0]
            : null;
          nodes.push({
            data: {
              id: `group:${groupKey}`,
              label: meta.label,
              shortLabel: meta.short || meta.label,
              fullLabel: meta.label,
              type: "model",
              modelId: groupKey,
              groupKey,
              description: "",
              modelColor: primaryHub?.border || meta.color || "#6366f1",
              itemCount,
              hubLogo: primaryHub?.logo || GROUP_HEADER_LOGOS[groupKey] || "",
              hubCount: primaryHub?.count || itemCount,
              hubAccent: primaryHub?.border || meta.color || "#6366f1",
              minWidth: 360,
              minHeight: 220,
            },
            classes: "model-node",
          });
        });
      }

      // Source hub identity is rendered as the group header chip — no separate hub nodes.

      // Components are children of their strategy group compound node
      const connectedComponentIds = new Set();
      relationships.forEach((r) => {
        connectedComponentIds.add(r.source_component_id);
        connectedComponentIds.add(r.target_component_id);
      });

      const componentGroupMap = new Map();
      let firstSearchMatchId = null;

      components.forEach((c) => {
        const temporal = c.temporal || "unknown";
        const isGap = boardLens === "gaps";
        const visuals = isBoard ? boardCardVisuals(c, isGap, sourceKind) : componentVisuals(c, isGap);
        const source = sourceVisual(c);

        const mName = modelNameById.get(c.model_id) || "";
        const groupKey = isExplore ? sourceKind(c) : groupForComponent(c);
        componentGroupMap.set(c.id, groupKey);
        const cleanName = stripModelPrefix(c.name);
        const { displayName, compactLabel, cardLabel, cardTitle, cardContext, cardDetail } = buildComponentCardContent(c, cleanName, mName, { boardMode: isBoard });
        const relationshipCount = c.relationship_count ?? 0;
        const groupHubs = groupSourceSummaries.get(groupKey);
        const componentKind = sourceKind(c);
        const hasGroupSourceHub = Boolean(groupHubs?.has(componentKind));
        const matchesSearch = componentMatchesSearch(c, searchQuery);
        if (searchQuery && matchesSearch && !firstSearchMatchId) firstSearchMatchId = c.id;
        const searchDimClass = searchQuery && !matchesSearch ? "search-dim" : "";
        const searchMatchClass = c.id === firstSearchMatchId ? "search-match" : "";

        nodes.push({
          data: {
            id: c.id,
            ...(isExplore ? {} : { parent: `group:${groupKey}` }),
            label: displayName,
            compactLabel,
            cardLabel,
            cardTitle,
            cardContext,
            cardDetail,
            fullLabel: displayName || c.display_title || c.name,
            type: "component",
            value: c.value,
            confidence: c.confidence,
            authority_weight: c.authority_weight,
            status: c.status,
            fact_type: c.fact_type,
            temporal,
            modelId: c.model_id,
            model: c.model_name,
            source_type: c.source_type,
            source_url: c.source_url,
            source_document_id: c.source_document_id,
            source_external_id: c.source_external_id,
            source_metadata_summary: c.source_metadata_summary,
            source_family: sourceFamily(c),
            source_kind: componentKind,
            relationship_count: c.relationship_count,
            provenance: c.provenance,
            excerpt: c.excerpt,
            bgColor: visuals.bg,
            borderColor: visuals.border,
            stripeColor: visuals.stripe,
            badgeColor: source.border,
            logo: isExplore ? source.logo : hasGroupSourceHub ? "" : source.logo,
            sourceLabel: source.label,
          },
          classes: [
            isExplore ? "explore-node" : "",
            isGap ? "gap-node" : "",
            relationshipCount === 0 ? "isolated-node" : "linked-node",
            searchDimClass,
            searchMatchClass,
          ].filter(Boolean).join(" "),
        });
      });

      // Relationship edges only — compound parent handles "contains" visually
      relationships.forEach((r) => {
        const hideLowConfidence = filters.confidence_threshold > 0 && (r.confidence ?? 0) < filters.confidence_threshold;
        if (hideLowConfidence) return;

        const sourceGroup = componentGroupMap.get(r.source_component_id);
        const targetGroup = componentGroupMap.get(r.target_component_id);
        const sameGroup = Boolean(sourceGroup && targetGroup && sourceGroup === targetGroup);
        const edgeStyle = resolveRelationshipEdgeStyle({
          relationship: r,
          sameGroup,
          showTrustEdges,
          isDark: theme === "dark" || document.documentElement.classList.contains("dark"),
        });

        edges.push({
          data: {
            id: r.id,
            source: r.source_component_id,
            target: r.target_component_id,
            label: (r.relationship_type || "related_to").replaceAll("_", " "),
            displayLabel: r.display_label || (r.relationship_type || "related_to").replaceAll("_", " "),
            shortLabel: (r.relationship_type || "related_to").replaceAll("_", " "),
            edgeType: "relationship",
            origin: edgeStyle.origin,
            confidence: r.confidence,
            evidence: r.evidence,
            status: r.status,
            lineStyle: edgeStyle.lineStyle,
            edgeWidth: edgeStyle.width,
            edgeOpacity: edgeStyle.opacity,
            edgeColor: edgeStyle.color,
            sourceName: r.source_component_name,
            targetName: r.target_component_name,
          },
          classes: [
            isExplore ? "explore-edge" : "",
            sameGroup && !isExplore ? "route-taxi" : "route-bezier",
          ].filter(Boolean).join(" "),
        });
      });
    }

    const isDark = theme === "dark" || document.documentElement.classList.contains("dark");
    const modelBg = isDark ? "#101827" : "#f8fafc";
    const modelBgOpacity = isDark ? 1 : 0.95;
    const modelTextColor = isDark ? "#f8fafc" : "#0f172a";
    const componentTextColor = "#0f172a";
    const labelOutlineColor = isDark ? "#000000" : "#ffffff";
    const edgeLabelBg = isDark ? "#1e293b" : "#ffffff";
    const repoFileBg = isDark ? "#263244" : "#f1f5f9";
    const repoFileBorder = isDark ? "#64748b" : "#cbd5e1";
    const repoTextColor = isDark ? "#e5edf8" : "#1e293b";
    const repoLabelOutline = isDark ? "#000000" : "#ffffff";
    const cardWidth = isBoard ? BOARD_CARD_WIDTH : COMPONENT_CARD_WIDTH;
    const cardHeight = isBoard ? BOARD_CARD_HEIGHT : COMPONENT_CARD_HEIGHT;
    const cardTextMaxWidth = isBoard ? BOARD_CARD_TEXT_MAX_WIDTH : COMPONENT_CARD_TEXT_MAX_WIDTH;
    const sourceHubWidth = SOURCE_HUB_CARD_WIDTH;
    const sourceHubHeight = SOURCE_HUB_CARD_HEIGHT;
    const sourceHubTextMaxWidth = SOURCE_HUB_TEXT_MAX_WIDTH;

    const cy = cytoscape({
      container: containerRef.current,
      elements: { nodes, edges },
      style: [
        // ── Base node defaults ───────────────────────────────────
        {
          selector: "node",
          style: {
            label: "data(label)",
            "text-valign": "center",
            "text-halign": "center",
            "font-size": "11px",
            "font-weight": "bold",
            color: componentTextColor,
            "background-color": CARD_STATUS_DEFAULT.bg,
            width: cardWidth,
            height: cardHeight,
            shape: "round-rectangle",
            "corner-radius": "10px",
            "border-width": 2,
            "border-color": CARD_STATUS_DEFAULT.border,
            "text-wrap": "wrap",
            "text-max-width": `${cardTextMaxWidth}px`,
            "text-outline-color": labelOutlineColor,
            "text-outline-width": 1,
          },
        },

        // ── MODEL — compound domain lane ─────────────────────────
        {
          selector: ":parent",
          style: {
            "background-color": modelBg,
            "background-opacity": modelBgOpacity,
            "border-color": isDark ? "#334155" : "#cbd5e1",
            "border-width": 1.5,
            "border-opacity": isDark ? 0.8 : 0.7,
            "compound-sizing-wrt-labels": "include",
          },
        },
        {
          selector: ".model-node",
          style: {
            "background-color": isDark ? "#000000" : "#f8fafc",
            "background-opacity": modelBgOpacity,
            "border-color": "data(modelColor)",
            "border-width": 2,
            "border-opacity": 0.7,
            shape: "round-rectangle",
            "corner-radius": "16px",
            padding: "40px 32px 28px 32px",
            label: "",
            "text-opacity": 0,
            "min-width": "data(minWidth)",
            "min-height": "data(minHeight)",
            "bounds-expansion": 16,
            width: 10,
            height: 10,
          },
        },
        {
          selector: ".model-node.lod-macro",
          style: {
            "background-opacity": isDark ? 0.16 : 0.08,
            "border-opacity": isDark ? 0.5 : 0.35,
            "border-width": 1,
            label: "data(shortLabel)",
            "text-opacity": 1,
            "font-size": "13px",
            "font-weight": "bold",
            color: modelTextColor,
            "text-valign": "top",
            "text-halign": "center",
            "text-margin-y": -8,
            "compound-sizing-wrt-labels": "exclude",
            "min-width": 0,
            "min-height": 0,
            "bounds-expansion": 4,
            padding: "26px",
          },
        },
        {
          selector: ".model-node.lod-compact",
          style: {
            "background-opacity": isDark ? 0.6 : 0.35,
            "border-opacity": 0.55,
            label: "",
            "text-opacity": 0,
            "compound-sizing-wrt-labels": "exclude",
            "min-width": 0,
            "min-height": 0,
            "bounds-expansion": 6,
            padding: "40px 32px 28px 32px",
          },
        },
        {
          selector: ".model-node.lod-card",
          style: {
            padding: "44px 32px 28px 32px",
          },
        },

        // ── COMPONENT — uniform card nodes ───────────────────────
        {
          selector: "node[type='component']",
          style: {
            "background-color": "data(bgColor)",
            "background-opacity": 1,
            "border-color": "data(borderColor)",
            "border-width": 3,
            width: cardWidth,
            height: cardHeight,
            shape: "round-rectangle",
            "corner-radius": "10px",
            "z-index": 20,
            "z-compound-depth": "top",
            label: "data(label)",
            "text-valign": "center",
            "text-halign": "center",
            "text-margin-x": 0,
            "text-margin-y": 0,
            "font-size": "11px",
            "font-weight": "bold",
            "text-wrap": "wrap",
            "text-max-width": `${cardTextMaxWidth}px`,
            "text-justification": "left",
            color: componentTextColor,
            "text-outline-color": labelOutlineColor,
            "text-outline-width": 0,
            "transition-property": "width height background-color border-width opacity font-size",
            "transition-duration": "180ms",
          },
        },
        {
          selector: "node.explore-node[type='component']",
          style: {
            width: 62,
            height: 62,
            shape: "ellipse",
            "corner-radius": "0px",
            "background-color": "data(bgColor)",
            "background-opacity": 0.98,
            "background-image": "data(logo)",
            "background-fit": "contain",
            "background-clip": "node",
            "background-width": "64%",
            "background-height": "64%",
            "background-position-x": "50%",
            "background-position-y": "50%",
            "border-color": "data(borderColor)",
            "border-width": 2,
            label: "data(compactLabel)",
            "text-opacity": 1,
            "text-valign": "bottom",
            "text-halign": "center",
            "text-margin-y": 7,
            "text-wrap": "wrap",
            "text-max-width": "112px",
            "text-justification": "center",
            "font-size": "9px",
            "font-weight": "700",
            color: componentTextColor,
            "text-outline-color": labelOutlineColor,
            "text-outline-width": 1.5,
            "z-index": 4,
          },
        },
        {
          selector: "node[type='component'].lod-macro",
          style: {
            width: 18,
            height: 18,
            shape: "ellipse",
            label: "",
            "background-color": "data(stripeColor)",
            "background-opacity": 1,
            "border-width": 2,
            "border-color": "data(borderColor)",
          },
        },
        {
          selector: "node[type='component'].lod-compact",
          style: {
            width: 170,
            height: 44,
            shape: "round-rectangle",
            "corner-radius": "8px",
            label: "data(compactLabel)",
            "font-size": "9.5px",
            "font-weight": "bold",
            "text-max-width": "150px",
            "text-wrap": "wrap",
            "text-justification": "left",
            "text-valign": "center",
            "text-margin-x": 4,
            "background-color": "data(bgColor)",
            "background-opacity": 0.96,
            "border-width": 2,
          },
        },
        {
          selector: "node[type='component'].lod-card",
          style: {
            width: cardWidth,
            height: cardHeight,
            shape: "round-rectangle",
            "corner-radius": "10px",
            "background-opacity": 1,
            label: "",
            "text-opacity": 0,
          },
        },
        {
          selector: ".source-hub",
          style: {
            "background-color": "data(bgColor)",
            "background-opacity": 1,
            "border-color": "data(borderColor)",
            "border-width": 2,
            width: sourceHubWidth,
            height: sourceHubHeight,
            shape: "round-rectangle",
            "corner-radius": "12px",
            label: "data(label)",
            "text-valign": "center",
            "text-halign": "center",
            "text-margin-y": 24,
            "font-size": "10px",
            "font-weight": "bold",
            "text-wrap": "wrap",
            "text-max-width": `${sourceHubTextMaxWidth}px`,
            "text-justification": "center",
            color: componentTextColor,
            "text-outline-color": labelOutlineColor,
            "text-outline-width": 1,
            "transition-property": "width height background-color border-width opacity font-size",
            "transition-duration": "180ms",
          },
        },
        {
          selector: ".source-hub.lod-macro",
          style: {
            width: 22,
            height: 22,
            shape: "ellipse",
            label: "",
            "background-color": "data(borderColor)",
            "background-opacity": 1,
            "border-width": 1,
          },
        },
        {
          selector: ".source-hub.lod-compact",
          style: {
            width: 112,
            height: 34,
            label: "data(compactLabel)",
            "font-size": "8.5px",
            "text-max-width": "96px",
            "text-valign": "center",
            "text-margin-y": 0,
          },
        },
        {
          selector: ".source-hub.lod-card",
          style: {
            width: sourceHubWidth,
            height: sourceHubHeight,
            label: "",
            "text-opacity": 0,
          },
        },
        {
          selector: ".linked-node",
          style: {
            "border-style": "solid",
          },
        },
        {
          selector: ".isolated-node",
          style: {
            "border-style": "dashed",
            "border-opacity": 0.8,
          },
        },

        {
          selector: "node.search-dim",
          style: {
            opacity: 0.12,
          },
        },
        {
          selector: "node.search-match",
          style: {
            "border-width": 2.5,
            "border-color": "#6366f1",
          },
        },

        // ── GAP NODE — isolated in Gap Detector view ──────────────
        {
          selector: ".gap-node",
          style: {
            opacity: 0.4,
            "border-style": "dashed",
            "border-width": 2,
            "border-color": "#ef4444",
          },
        },

        // ── Repo-view node types ──────────────────────────────────
        {
          selector: "node[type='area'], node[type='folder'], node[type='file'], node[type='technology']",
          style: {
            "background-color": "data(bgColor)",
            "border-color": "data(borderColor)",
            color: repoTextColor,
            "text-outline-color": repoLabelOutline,
            "text-outline-width": 1.8,
            width: 24,
            height: 24,
            shape: "round-rectangle",
          },
        },
        {
          selector: "node[type='area']",
          style: {
            width: 84,
            height: 36,
            "font-size": "9px",
            "font-weight": "bold",
            "text-max-width": 94,
            "background-color": isDark ? "#2563eb" : "#3b82f6",
            "border-color": isDark ? "#93c5fd" : "#1d4ed8",
            "border-width": 1.5,
          },
        },
        {
          selector: "node[type='technology']",
          style: {
            width: 64,
            height: 30,
            "font-size": "8px",
            "font-weight": "bold",
            "text-max-width": 70,
            "background-color": isDark ? "#6d28d9" : "#8b5cf6",
            "border-color": isDark ? "#c4b5fd" : "#6d28d9",
            "border-width": 1.2,
          },
        },
        {
          selector: "node[type='file']",
          style: {
            width: 76,
            height: 24,
            "font-size": "7px",
            "font-weight": "bold",
            "text-max-width": 80,
            "background-color": repoFileBg,
            "border-color": repoFileBorder,
            "border-width": 1,
          },
        },
        {
          selector: ".repo-node",
          style: {
            "background-color": isDark ? "#1e293b" : "#334155",
            "border-color": isDark ? "#525252" : "#0f172a",
            color: "#f8fafc",
            width: 78,
            height: 36,
            shape: "round-rectangle",
            "font-size": "8.5px",
            "font-weight": "bold",
            "text-max-width": 82,
          },
        },

        // ── EDGES — subtle by default, labels hidden ─────────────
        {
          selector: "edge",
          style: {
            width: 2.2,
            "line-color": isDark ? "#64748b" : "#64748b",
            "target-arrow-color": isDark ? "#64748b" : "#64748b",
            "target-arrow-shape": "triangle",
            "arrow-scale": 1.1,
            "curve-style": "bezier",
            label: "",
            opacity: 0.72,
          },
        },

        // ── RELATIONSHIP EDGES — routed outside cards; labels on demand ──
        {
          selector: "edge[edgeType='relationship']",
          style: {
            width: "data(edgeWidth)",
            "line-color": "data(edgeColor)",
            "target-arrow-color": "data(edgeColor)",
            "target-arrow-shape": "triangle",
            "arrow-scale": 1.55,
            "edge-distances": "intersection",
            "source-endpoint": "outside-to-node",
            "target-endpoint": "outside-to-node",
            "source-distance-from-node": 8,
            "target-distance-from-node": 12,
            "z-index": 8,
            "z-compound-depth": "top",
            label: "",
            opacity: "data(edgeOpacity)",
            "font-size": "8.5px",
            "font-weight": "bold",
            color: isDark ? "#dbeafe" : "#1e3a8a",
            "text-rotation": "0deg",
            "text-background-opacity": 1,
            "text-background-color": edgeLabelBg,
            "text-background-padding": "3px",
            "text-border-opacity": 0,
            "text-margin-y": -10,
            "transition-property": "width opacity line-color target-arrow-color z-index",
            "transition-duration": "180ms",
          },
        },
        {
          selector: "edge[edgeType='relationship'].route-taxi",
          style: {
            "curve-style": "taxi",
            "taxi-direction": "auto",
            "taxi-turn": 28,
            "taxi-turn-min-distance": 12,
          },
        },
        {
          selector: "edge[edgeType='relationship'].route-bezier",
          style: {
            "curve-style": "unbundled-bezier",
            "control-point-distances": 56,
            "control-point-weights": 0.42,
          },
        },
        {
          selector: "edge.explore-edge[edgeType='relationship']",
          style: {
            "curve-style": "bezier",
            "control-point-distances": 0,
            "control-point-weights": 0.5,
            width: 1.2,
            opacity: "data(edgeOpacity)",
            "target-arrow-shape": "triangle",
            "arrow-scale": 1,
          },
        },
        {
          selector: "edge[edgeType='relationship'].lod-macro-edge",
          style: {
            label: "",
            width: 1.5,
            opacity: 0.5,
            "arrow-scale": 0.85,
          },
        },
        {
          selector: "edge[edgeType='relationship'].lod-detail-edge",
          style: {
            label: "",
            width: "data(edgeWidth)",
            opacity: "data(edgeOpacity)",
          },
        },

        // ── AI PROPOSED EDGES — dashed ────────────────────────────
        {
          selector: "edge[edgeType='relationship'][lineStyle='dashed']",
          style: {
            "line-style": "dashed",
            "line-dash-pattern": [6, 4],
          },
        },
        {
          selector: "edge[edgeType='relationship'][lineStyle='dotted']",
          style: {
            "line-style": "dotted",
          },
        },

        // ── HUMAN VERIFIED EDGES — green tint ─────────────────────
        {
          selector: "edge[edgeType='relationship'][origin='human_verified']",
          style: {
            "line-color": isDark ? "#059669" : "#34d399",
            "target-arrow-color": isDark ? "#059669" : "#34d399",
          },
        },

        // ── Repo-view edges — calm structural map ─────────────────
        {
          selector: "edge[edgeType='repoContains']",
          style: {
            width: 1,
            "line-color": isDark ? "#1e293b" : "#cbd5e1",
            "target-arrow-shape": "none",
            "curve-style": "straight",
            opacity: 0.35,
          },
        },
        {
          selector: "edge[edgeType='repoFile']",
          style: {
            width: 1.1,
            "line-color": isDark ? "#334155" : "#94a3b8",
            "target-arrow-color": isDark ? "#334155" : "#94a3b8",
            "target-arrow-shape": "triangle",
            "arrow-scale": 0.45,
            "curve-style": "straight",
            opacity: 0.55,
          },
        },
        {
          selector: "edge[edgeType='repoUses']",
          style: {
            width: 1.2,
            "line-color": isDark ? "#7c3aed" : "#8b5cf6",
            "target-arrow-color": isDark ? "#7c3aed" : "#8b5cf6",
            "target-arrow-shape": "triangle",
            "arrow-scale": 0.48,
            "curve-style": "straight",
            opacity: 0.48,
          },
        },

        // ── Selection highlight ───────────────────────────────────
        {
          selector: "node[type='component']:selected",
          style: {
            "border-width": 2.5,
            "border-color": "#4f46e5",
            "background-color": isDark ? "rgba(79,70,229,0.18)" : "rgba(99,102,241,0.12)",
            color: isDark ? "#c7d2fe" : "#3730a3",
          },
        },
        {
          selector: ".model-node:selected",
          style: {
            "border-width": 2.5,
            "border-color": "#4f46e5",
          },
        },
        {
          selector: "edge:selected",
          style: {
            opacity: 1,
            width: 4,
            "z-index": 30,
            "line-color": isDark ? "#818cf8" : "#6366f1",
            "target-arrow-color": isDark ? "#818cf8" : "#6366f1",
          },
        },
      ],
      layout: viewMode === "repo"
        ? { name: "preset", fit: true, padding: 110 }
        : isExplore
          ? {
            name: "cose",
            animate: true,
            animationDuration: 1900,
            fit: true,
            padding: 96,
            randomize: true,
            nodeRepulsion: 8200,
            idealEdgeLength: 170,
            edgeElasticity: 110,
            nestingFactor: 1.1,
            gravity: 0.28,
            numIter: 2200,
            initialTemp: 180,
            coolingFactor: 0.95,
            minTemp: 1.0,
          }
        : (() => {
          const presetPositions = {};
          const groups = Array.from(visibleGroups.entries())
            .map(([groupKey, meta]) => ({
              groupKey,
              meta,
              items: components.filter((c) => groupForComponent(c) === groupKey),
              hubs: Array.from(groupSourceSummaries.get(groupKey)?.values() || []),
            }))
            .sort((a, b) => b.items.length - a.items.length);

          const colCount = isBoard
            ? Math.min(2, Math.max(1, groups.length))
            : Math.min(4, Math.max(1, groups.length));
          const columnStride = isBoard ? 980 : 1080;
          const laneGapY = isBoard ? 68 : 96;
          const headerFloatClearance = GROUP_HUB_CHIP_HEIGHT_PX + GROUP_HEADER_FLOAT_GAP_PX + 8;
          const cardW = cardWidth;
          const cardH = cardHeight;
          const gapX = isBoard ? 28 : 26;
          const gapY = isBoard ? 18 : 20;
          const groupPadX = isBoard ? 32 : 40;
          const groupPadTop = GROUP_HEADER_BAND_PX;
          const groupPadBottom = isBoard ? 32 : 32;
          const colHeights = Array.from({ length: colCount }, () => 0);

          groups.forEach(({ groupKey, items }) => {
            const col = colHeights.indexOf(Math.min(...colHeights));
            const itemCount = Math.max(1, items.length);
            const gridCols = layoutGridColumns(itemCount, isBoard ? 4 : 3);
            const rows = Math.ceil(itemCount / gridCols);
            const groupWidth = groupPadX * 2 + gridCols * cardW + Math.max(0, gridCols - 1) * gapX;
            const laneWidth = isBoard ? groupWidth + 40 : Math.min(groupWidth + 48, columnStride - 40);
            const baseX = col * columnStride - ((colCount - 1) * columnStride) / 2;
            const baseY = colHeights[col];
            const startX = baseX - groupWidth / 2 + groupPadX + cardW / 2;
            const startY = baseY + headerFloatClearance + groupPadTop;
            const groupHeight = headerFloatClearance + groupPadTop + rows * cardH + Math.max(0, rows - 1) * gapY + groupPadBottom;

            items.forEach((c, index) => {
              const row = Math.floor(index / gridCols);
              const itemCol = index % gridCols;
              presetPositions[c.id] = {
                x: startX + itemCol * (cardW + gapX),
                y: startY + row * (cardH + gapY),
              };
            });
            if (items.length === 0) {
              presetPositions[`group:${groupKey}`] = { x: baseX, y: baseY + groupHeight / 2 };
            }
            const groupNode = nodes.find((node) => node.data.id === `group:${groupKey}`);
            if (groupNode) {
              groupNode.data.minWidth = Math.max(laneWidth, 300);
              groupNode.data.minHeight = Math.max(groupHeight, 180);
            }
            colHeights[col] += groupHeight + laneGapY;
          });

          return {
            name: "preset",
            positions: (node) => presetPositions[node.id()],
            fit: true,
            padding: 36,
          };
        })(),
      wheelSensitivity: 0.18,
    });

    cy.maxZoom(isBoard ? BOARD_MAX_ZOOM : 2.8);
    fitGraphViewport(cy, viewMode, graphLayout);
    applyGraphLod(cy);
    const freezeExploreLayoutId = isExplore
      ? setTimeout(() => {
        if (typeof cy.destroyed === "function" && cy.destroyed()) return;
        cy.nodes(".explore-node").lock();
      }, 2100)
      : null;

    const graphIsDestroyed = () => typeof cy.destroyed === "function" && cy.destroyed();
    let overviewRafId = null;
    const updateGraphOverview = () => {
      if (graphIsDestroyed()) return;
      setGraphOverview(buildGraphOverview(cy));
    };
    const scheduleGraphOverviewUpdate = () => {
      if (overviewRafId) return;
      overviewRafId = requestAnimationFrame(() => {
        overviewRafId = null;
        updateGraphOverview();
      });
    };
    const handleGraphZoom = () => {
      applyGraphLod(cy);
      scheduleGraphOverviewUpdate();
    };
    const handleGraphMove = () => {
      scheduleGraphOverviewUpdate();
    };
    scheduleGraphOverviewUpdate();

    const resizeObserver = new ResizeObserver(() => {
      cy.resize();
      fitGraphViewport(cy, viewMode, graphLayout);
      scheduleGraphOverviewUpdate();
    });
    resizeObserver.observe(containerRef.current);

    let logoRafId = null;
    const logoTimeoutIds = [];
    const updateNodeOverlays = () => {
      const layer = logoLayerRef.current;
      if (!layer || !containerRef.current || graphIsDestroyed()) {
        return;
      }
      const zoom = cy.zoom();
      const showDetailOverlays = viewMode === "repo" || zoom >= LOD_CARD_ZOOM;
      const showGroupChrome = viewMode !== "repo" && zoom >= LOD_MACRO_ZOOM;
      if (!showDetailOverlays && !showGroupChrome) {
        layer.replaceChildren();
        return;
      }

      const fragment = document.createDocumentFragment();
      const textColor = isDark ? "#f8fafc" : "#0f172a";
      const mutedColor = isDark ? "#94a3b8" : "#64748b";
      const headerBg = isDark ? "rgba(15,23,42,0.94)" : "rgba(255,255,255,0.96)";

      if (showGroupChrome) {
        cy.nodes(".model-node").forEach((node) => {
          if (node.hasClass("lod-macro")) return;
          try {
            const bounds = node.renderedBoundingBox({
              includeEdges: false,
              includeLabels: false,
              includeNodes: true,
            });
            const groupKey = node.data("groupKey") || node.data("modelId");
            const meta = GRAPH_GROUP_META[groupKey] || GRAPH_GROUP_META.other;
            const hubLogo = node.data("hubLogo");
            const hubCount = node.data("hubCount") || node.data("itemCount") || 0;
            const hubAccent = node.data("hubAccent") || meta.color;

            const header = document.createElement("div");
            header.className = "pointer-events-none absolute";
            header.dataset.graphGroupHeader = node.id();
            const chipTop = bounds.y1 - GROUP_HUB_CHIP_HEIGHT_PX - GROUP_HEADER_FLOAT_GAP_PX;
            Object.assign(header.style, {
              left: `${bounds.x1 + 14}px`,
              top: `${chipTop}px`,
              zIndex: "24",
            });

            if (hubLogo) {
              appendSourceHubChip(header, {
                logo: hubLogo,
                count: hubCount,
                accent: hubAccent,
                isDark,
                textColor,
                mutedColor,
                headerBg,
              });
            } else {
              const fallback = document.createElement("div");
              Object.assign(fallback.style, {
                display: "inline-flex",
                alignItems: "center",
                gap: "8px",
                height: `${GROUP_HEADER_HEIGHT_PX}px`,
                padding: "0 10px",
                borderRadius: "999px",
                background: headerBg,
                border: `1.5px solid ${meta.color}`,
              });
              const dot = document.createElement("span");
              Object.assign(dot.style, {
                width: "10px",
                height: "10px",
                borderRadius: "999px",
                background: meta.color,
              });
              fallback.appendChild(dot);
              const title = document.createElement("span");
              title.textContent = meta.short || meta.label;
              Object.assign(title.style, {
                color: textColor,
                fontSize: `${CARD_OVERLAY_TITLE_PX}px`,
                fontWeight: "700",
              });
              fallback.appendChild(title);
              const badge = document.createElement("span");
              badge.textContent = String(hubCount);
              Object.assign(badge.style, {
                color: mutedColor,
                fontSize: "10px",
                fontWeight: "700",
                padding: "2px 7px",
                borderRadius: "999px",
                background: isDark ? "rgba(148,163,184,0.18)" : "rgba(148,163,184,0.14)",
              });
              fallback.appendChild(badge);
              header.appendChild(fallback);
            }
            fragment.appendChild(header);
          } catch (_) {}
        });
      }

      if (!showDetailOverlays) {
        layer.replaceChildren(fragment);
        return;
      }

      cy.nodes("[type='component']").forEach((node) => {
        try {
          if (!node.hasClass("lod-card")) return;

          const bounds = node.renderedBoundingBox({
            includeEdges: false,
            includeLabels: false,
            includeNodes: true,
          });

          const shell = document.createElement("div");
          shell.className = "pointer-events-none absolute overflow-hidden";
          shell.dataset.graphCard = node.id();
          Object.assign(shell.style, {
            left: `${bounds.x1}px`,
            top: `${bounds.y1}px`,
            width: `${bounds.w}px`,
            height: `${bounds.h}px`,
            borderRadius: "10px",
          });

          const title = node.data("cardTitle") || node.data("label") || "";
          const compactCard = bounds.h < 88;
          const tinyCard = bounds.h < 56;
          const detailLines = [
            node.data("cardContext"),
            node.data("cardDetail"),
          ].filter(Boolean);
          const cardTitleColor = "#0f172a";
          const cardMutedColor = "#475569";
          const textWrap = document.createElement("div");
          Object.assign(textWrap.style, {
            position: "absolute",
            left: compactCard ? "10px" : "14px",
            right: compactCard ? "10px" : "14px",
            top: compactCard ? "8px" : "12px",
            bottom: compactCard ? "8px" : "12px",
            overflow: "hidden",
            display: "flex",
            flexDirection: "column",
            justifyContent: "center",
            gap: compactCard ? "3px" : "5px",
          });

          const titleEl = document.createElement("div");
          titleEl.textContent = title;
          Object.assign(titleEl.style, {
            color: cardTitleColor,
            fontSize: `${compactCard ? CARD_OVERLAY_TITLE_PX : CARD_OVERLAY_TITLE_PX + 1}px`,
            fontWeight: "800",
            lineHeight: compactCard ? "1.12" : "1.22",
            overflow: "hidden",
            display: "-webkit-box",
            WebkitLineClamp: tinyCard ? "1" : "2",
            WebkitBoxOrient: "vertical",
            whiteSpace: "normal",
          });
          textWrap.appendChild(titleEl);

          detailLines.slice(0, compactCard ? 1 : 2).forEach((line, index) => {
            if (tinyCard) return;
            const lineEl = document.createElement("div");
            lineEl.textContent = line;
            Object.assign(lineEl.style, {
              color: cardMutedColor,
              fontSize: `${compactCard ? CARD_OVERLAY_META_PX - 0.5 : CARD_OVERLAY_META_PX}px`,
              fontWeight: index === 0 ? "650" : "500",
              lineHeight: "1.22",
              overflow: "hidden",
              display: "-webkit-box",
              WebkitLineClamp: "1",
              WebkitBoxOrient: "vertical",
              whiteSpace: "normal",
            });
            textWrap.appendChild(lineEl);
          });
          shell.appendChild(textWrap);
          fragment.appendChild(shell);
        } catch (_) {}
      });
      layer.replaceChildren(fragment);
    };
    const scheduleLogoOverlayUpdate = () => {
      if (logoRafId) return;
      logoRafId = requestAnimationFrame(() => {
        logoRafId = null;
        updateNodeOverlays();
      });
    };
    updateNodeOverlays();
    logoTimeoutIds.push(setTimeout(updateNodeOverlays, 50));
    logoTimeoutIds.push(setTimeout(updateNodeOverlays, 250));
    cy.on("render zoom pan position", scheduleLogoOverlayUpdate);
    cy.on("zoom", handleGraphZoom);
    cy.on("pan position", handleGraphMove);

    cy.on("tap", "node", (evt) => {
      const data = evt.target.data();
      if (data.type === "component") {
        setSelectedNode({ ...data, connected: buildNodeConnections(cy, data.id) });
        setSelectedEdge(null);
        setEdgeReviewError(null);
        setShowRefine(false);
        setShowSidePanel(false);
        setShowAgents(false);
      } else {
        setSelectedNode(null);
      }
    });

    cy.on("tap", "edge[edgeType='relationship']", (evt) => {
      const data = evt.target.data();
      setSelectedEdge({
        id: data.id,
        label: data.label,
        displayLabel: data.displayLabel,
        origin: data.origin,
        confidence: data.confidence,
        evidence: data.evidence,
        status: data.status,
        source: data.source,
        target: data.target,
        sourceName: data.sourceName,
        targetName: data.targetName,
      });
      setSelectedNode(null);
      setEdgeReviewError(null);
      setShowRefine(false);
      setShowSidePanel(false);
      setShowAgents(false);
    });

    cy.on("tap", (evt) => {
      if (evt.target === cy) {
        setSelectedNode(null);
        setSelectedEdge(null);
        setShowRefine(false);
      }
    });

    // Edge labels — reveal on hover/select only so the overview stays readable
    cy.on("mouseover", "edge[edgeType='relationship']", (evt) => {
      evt.target.style({
        label: evt.target.data("displayLabel") || evt.target.data("label"),
        opacity: 1,
        "z-index": 24,
        "text-rotation": "0deg",
      });
    });
    cy.on("mouseout", "edge[edgeType='relationship']", (evt) => {
      if (!evt.target.selected()) {
        evt.target.style({
          label: "",
          opacity: evt.target.data("edgeOpacity") ?? 0.6,
          "z-index": 8,
        });
      }
    });
    cy.on("select", "edge[edgeType='relationship']", (evt) => {
      evt.target.style({
        label: evt.target.data("displayLabel") || evt.target.data("label"),
        opacity: 1,
        "z-index": 24,
        "text-rotation": "0deg",
      });
    });
    cy.on("unselect", "edge[edgeType='relationship']", (evt) => {
      evt.target.style({
        label: "",
        opacity: evt.target.data("edgeOpacity") ?? 0.6,
        "z-index": 8,
      });
    });

    // Hover effect on card nodes — subtle lift + surface connected edges
    cy.on("mouseover", "node[type='component']", (evt) => {
      evt.target.style({ "border-width": 4, opacity: 1 });
      evt.target.connectedEdges("[edgeType='relationship']").style({ "z-index": 20, opacity: 1 });
    });
    cy.on("mouseout", "node[type='component']", (evt) => {
      if (!evt.target.selected()) {
        evt.target.style({ "border-width": 3, opacity: 1 });
      }
      evt.target.connectedEdges("[edgeType='relationship']").forEach((edge) => {
        if (!edge.selected()) {
          edge.style({ "z-index": 8, opacity: edge.data("edgeOpacity") ?? 0.6 });
        }
      });
    });

    cyRef.current = cy;

    const containerEl = containerRef.current;
    let lastHoveredId = null;
    let rafId = null;

    function onMouseMove(e) {
      if (rafId) return;
      rafId = requestAnimationFrame(() => {
        rafId = null;
        const rect = containerEl.getBoundingClientRect();
        const rx = e.clientX - rect.left;
        const ry = e.clientY - rect.top;
        let found = null;
        cy.nodes().forEach((node) => {
          try {
            const bb = node.renderedBoundingBox({ includeLabels: true, includeEdges: false, includeNodes: true });
            if (rx >= bb.x1 && rx <= bb.x2 && ry >= bb.y1 && ry <= bb.y2) found = node;
          } catch (_) {}
        });
        if (found) {
          const id = found.id();
          lastHoveredId = id;
        } else {
          lastHoveredId = null;
        }
      });
    }

    function onMouseLeave() {
      if (rafId) { cancelAnimationFrame(rafId); rafId = null; }
      lastHoveredId = null;
    }

    containerEl.addEventListener("mousemove", onMouseMove);
    containerEl.addEventListener("mouseleave", onMouseLeave);

    return () => {
      containerEl.removeEventListener("mousemove", onMouseMove);
      containerEl.removeEventListener("mouseleave", onMouseLeave);
      cy.off("render zoom pan position", scheduleLogoOverlayUpdate);
      cy.off("zoom", handleGraphZoom);
      cy.off("pan position", handleGraphMove);
      logoTimeoutIds.forEach((timeoutId) => clearTimeout(timeoutId));
      if (logoRafId) cancelAnimationFrame(logoRafId);
      if (overviewRafId) cancelAnimationFrame(overviewRafId);
      if (freezeExploreLayoutId) clearTimeout(freezeExploreLayoutId);
      logoLayerRef.current?.replaceChildren();
      resizeObserver.disconnect();
      cy.destroy();
      setGraphOverview(null);
    };
  }, [graphData, filteredData, viewMode, boardLens, graphLayout, showTrustEdges, filters.search, theme]);

  const models = graphData?.models || [];
  const allComponents = graphData?.components || [];
  const sourceTypes = [...new Set(allComponents.map((c) => c.source_type).filter(Boolean))];
  const statuses = [...new Set(allComponents.map((c) => c.status).filter(Boolean))];
  const currentViewData = filteredData();
  const graphStats = buildGraphStats(currentViewData);
  const visibleCanvasItemCount = graphLayout === "explore" && viewMode === "knowledge"
    ? filterExploreComponents(currentViewData.components || [], currentViewData.relationships || []).length
    : (currentViewData.components || currentViewData.nodes || []).length;
  const exploreNeighborhood = graphLayout === "explore" && selectedNode
    ? buildExploreNeighborhood(
      selectedNode.id,
      currentViewData.components || [],
      currentViewData.relationships || [],
      exploreDepth,
    )
    : [];
  const activeBoardLens = BOARD_LENSES.find((v) => v.id === boardLens);
  const clearGraphFilters = () => setFilters({
    model: "",
    source_type: "",
    status: "",
    temporal: "",
    confidence_threshold: 0,
    relationship_origin: "",
    search: "",
  });
  const activeFilterCount = [
    filters.model,
    filters.source_type,
    filters.status,
    filters.temporal,
    filters.relationship_origin,
    filters.search,
    filters.confidence_threshold > 0 ? "confidence" : "",
  ].filter(Boolean).length;

  if (viewMode === "knowledge" && !workspacesLoading && !activeWorkspaceId) {
    return (
      <WorkspaceTopicGate
        workspaces={workspaces}
        selectedId={selectedId}
        onSelect={setSelectedId}
      />
    );
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-center">
          <div className="h-8 w-8 animate-spin rounded-full border-4 border-brand-200 border-t-brand-600 mx-auto mb-3" />
          <p className="text-sm font-bold text-slate-800 dark:text-neutral-200">Loading graph...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-center p-6 bg-white dark:bg-black rounded-2xl border border-slate-200 dark:border-neutral-800">
          <p className="text-sm font-bold text-red-600 dark:text-red-400 mb-2">Failed to load graph</p>
          <p className="text-xs text-slate-500">{error}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="relative flex h-full min-h-0 overflow-hidden">
      <div className="relative flex min-w-0 flex-1 flex-col">
        <div className="pointer-events-none absolute left-3 right-3 top-3 z-30 flex flex-col gap-2 lg:flex-row lg:items-start lg:justify-between">
          <div className="pointer-events-auto w-fit max-w-[calc(100vw-1.5rem)] self-start rounded-xl border border-slate-200 bg-white/92 p-2 shadow-sm backdrop-blur-sm dark:border-neutral-800 dark:bg-black">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-sm font-black text-slate-900 dark:text-white">Knowledge Graph</h2>
              <div className="flex rounded-lg border border-slate-200 bg-slate-50 p-0.5 dark:border-neutral-800 dark:bg-black">
                {[
                  ["knowledge", "Knowledge"],
                  ["repo", "Repository"],
                ].map(([mode, label]) => (
                  <button
                    key={mode}
                    type="button"
                    onClick={() => setViewMode(mode)}
                    className={`rounded-md px-2.5 py-1 text-[11px] font-bold transition-colors ${
                      viewMode === mode
                        ? "bg-slate-900 text-white dark:bg-white dark:text-slate-900"
                        : "text-slate-500 hover:text-slate-900 dark:text-neutral-400 dark:hover:text-white"
                    }`}
                  >
                    {label}
                  </button>
                ))}
              </div>
              {viewMode === "knowledge" && (
                <div className="flex rounded-lg border border-slate-200 bg-slate-50 p-0.5 dark:border-neutral-800 dark:bg-black">
                  {[
                    ["board", "Board"],
                    ["explore", "Explore"],
                  ].map(([layout, label]) => (
                    <button
                      key={layout}
                      type="button"
                      onClick={() => setGraphLayout(layout)}
                      className={`rounded-md px-2.5 py-1 text-[11px] font-bold transition-colors ${
                        graphLayout === layout
                          ? "bg-brand-600 text-white"
                          : "text-slate-500 hover:text-slate-900 dark:text-neutral-400 dark:hover:text-white"
                      }`}
                    >
                      {label}
                    </button>
                  ))}
                </div>
              )}
            </div>
            {viewMode === "knowledge" && activeWorkspace && (
              <div className="mt-2 flex w-fit max-w-full items-center gap-1.5 rounded-lg bg-brand-50 px-2 py-1 text-[10px] font-bold text-brand-700 dark:bg-brand-900/30 dark:text-brand-300">
                <ShieldCheck className="h-3.5 w-3.5 shrink-0" />
                <span className="shrink-0">Workspace focused</span>
                <span className="truncate text-brand-900 dark:text-brand-100">{activeWorkspace.name}</span>
              </div>
            )}
            {viewMode === "knowledge" && graphLayout === "board" && (
              <div className="mt-2 flex flex-wrap items-center gap-1.5">
                <span className="shrink-0 text-[10px] font-bold uppercase text-slate-400">Lens</span>
                {BOARD_LENSES.map(({ id, label, desc }) => (
                  <button
                    key={id}
                    type="button"
                    title={desc}
                    onClick={() => setBoardLens(id)}
                    className={`rounded-full px-2.5 py-1 text-[10px] font-bold transition-colors ${
                      boardLens === id
                        ? id === "gaps"
                          ? "bg-red-500 text-white"
                          : "bg-slate-900 text-white dark:bg-white dark:text-slate-900"
                        : "bg-slate-100 text-slate-500 hover:bg-slate-200 dark:bg-black dark:text-neutral-400 dark:hover:bg-black"
                    }`}
                  >
                    {label}
                  </button>
                ))}
              </div>
            )}
            {viewMode === "knowledge" && (
              <div className="mt-2 flex items-center gap-1.5 rounded-lg bg-slate-100 px-2 py-1 text-[10px] font-bold text-slate-500 dark:bg-black dark:text-neutral-400">
                <Network className="h-3.5 w-3.5 text-brand-500" />
                <span className="text-slate-900 dark:text-white">{graphStats.components}</span>
                <span>nodes</span>
                <span className="text-slate-300 dark:text-slate-600">/</span>
                <span className="text-slate-900 dark:text-white">{graphStats.relationships}</span>
                <span>edges</span>
                {graphStats.isolated > 0 && (
                  <>
                    <span className="text-slate-300 dark:text-slate-600">/</span>
                    <span className="text-red-500">{graphStats.isolated}</span>
                    <span>isolated</span>
                  </>
                )}
              </div>
            )}
          </div>

          <div className="pointer-events-auto flex flex-wrap items-center justify-end gap-2">
            {viewMode === "knowledge" && (
              <div className="relative">
                <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-400" />
                <input
                  ref={searchInputRef}
                  type="text"
                  value={filters.search}
                  onChange={(e) => setFilters((f) => ({ ...f, search: e.target.value }))}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") centerOnSearchMatch();
                  }}
                  placeholder="Search graph (⌘K)…"
                  className="h-9 w-40 rounded-xl border border-slate-200 bg-white/92 pl-8 pr-7 text-xs font-semibold text-slate-700 shadow-sm outline-none backdrop-blur-sm transition placeholder:text-slate-400 focus:border-brand-400 dark:border-neutral-800 dark:bg-black dark:text-neutral-200 sm:w-52 xl:w-60"
                />
                {filters.search && (
                  <button
                    type="button"
                    onClick={() => setFilters((f) => ({ ...f, search: "" }))}
                    className="absolute right-2 top-1/2 flex h-5 w-5 -translate-y-1/2 items-center justify-center rounded-md text-slate-400 hover:bg-slate-100 hover:text-slate-600 dark:hover:bg-black dark:hover:text-slate-300"
                  >
                    <XIcon className="h-3 w-3" />
                  </button>
                )}
              </div>
            )}
            {viewMode === "knowledge" && (
              <button
                type="button"
                onClick={() => {
                  setShowRefine((v) => !v);
                  setShowSidePanel(false);
                  setShowAgents(false);
                  setSelectedNode(null);
                  setSelectedEdge(null);
                }}
                className={`flex h-9 items-center gap-1.5 rounded-xl border px-2.5 text-xs font-bold shadow-sm backdrop-blur-sm transition-colors ${
                  showRefine
                    ? "border-sky-400 bg-sky-50/95 text-sky-700 dark:border-sky-600 dark:bg-sky-900/60 dark:text-sky-300"
                    : "border-slate-200 bg-white/92 text-slate-600 hover:bg-slate-50 dark:border-neutral-800 dark:bg-black dark:text-neutral-300 dark:hover:bg-black"
                }`}
              >
                <SlidersHorizontal className="h-3.5 w-3.5" />
                <span className="hidden sm:inline">Refine</span>
                {activeFilterCount > 0 && (
                  <span className="rounded-full bg-sky-600 px-1.5 py-0.5 text-[9px] leading-none text-white">{activeFilterCount}</span>
                )}
              </button>
            )}
            <button
              type="button"
              onClick={() => setShowAiSettings(true)}
              title="Configure AI extraction"
              className={`flex h-9 items-center gap-1.5 rounded-xl border px-2.5 text-xs font-bold shadow-sm backdrop-blur-sm transition-colors ${aiSettings.api_key ? "border-brand-400 bg-brand-50/95 text-brand-700 dark:border-brand-600 dark:bg-brand-900/60 dark:text-brand-300" : "border-slate-200 bg-white/92 text-slate-500 hover:bg-slate-50 dark:border-neutral-800 dark:bg-black dark:text-neutral-300 dark:hover:bg-black"}`}
            >
              <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="3"/>
                <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>
              </svg>
              <span className="hidden xl:inline">{aiSettings.api_key ? "AI ready" : "AI"}</span>
            </button>
            <button
              type="button"
              onClick={() => {
                setShowAsk((v) => !v);
                setShowRefine(false);
                setShowSidePanel(false);
                setShowAgents(false);
                setAskResult(null);
                setAskError(null);
                setTimeout(() => askInputRef.current?.focus(), 80);
              }}
              className={`flex h-9 items-center gap-1.5 rounded-xl border px-2.5 text-xs font-bold shadow-sm backdrop-blur-sm transition-colors ${
                showAsk
                  ? "border-brand-500 bg-brand-50/95 text-brand-700 dark:border-brand-500 dark:bg-brand-900/60 dark:text-brand-300"
                  : "border-slate-200 bg-white/92 text-slate-600 hover:bg-slate-50 dark:border-neutral-800 dark:bg-black dark:text-neutral-300 dark:hover:bg-black"
              }`}
            >
              <Search className="h-3.5 w-3.5" />
              <span className="hidden sm:inline">Ask AI</span>
            </button>
            <button
              type="button"
              onClick={() => {
                setShowAgents((v) => !v);
                setShowRefine(false);
                setShowSidePanel(false);
                setSelectedEdge(null);
              }}
              className={`flex h-9 items-center gap-1.5 rounded-xl border px-2.5 text-xs font-bold shadow-sm backdrop-blur-sm transition-colors ${
                showAgents
                  ? "border-violet-500 bg-violet-50/95 text-violet-700 dark:border-violet-500 dark:bg-violet-900/60 dark:text-violet-300"
                  : "border-slate-200 bg-white/92 text-slate-600 hover:bg-slate-50 dark:border-neutral-800 dark:bg-black dark:text-neutral-300 dark:hover:bg-black"
              }`}
            >
              <Bot className="h-3.5 w-3.5" />
              <span className="hidden sm:inline">Agents</span>
            </button>
            <button
              type="button"
              title="Source coverage and work lens"
              onClick={() => {
                setShowSidePanel((v) => !v);
                setShowRefine(false);
                setShowAgents(false);
                setSelectedNode(null);
                setSelectedEdge(null);
              }}
              className={`flex h-9 items-center gap-1.5 rounded-xl border px-2.5 text-xs font-bold shadow-sm backdrop-blur-sm transition-colors ${
                showSidePanel
                  ? "border-brand-500 bg-brand-50/95 text-brand-700 dark:border-brand-500 dark:bg-brand-900/60 dark:text-brand-300"
                  : "border-slate-200 bg-white/92 text-slate-600 hover:bg-slate-50 dark:border-neutral-800 dark:bg-black dark:text-neutral-300 dark:hover:bg-black"
              }`}
            >
              <Layers3 className="h-3.5 w-3.5" />
              <span className="hidden sm:inline">Panels</span>
            </button>
          </div>
        </div>

        {viewMode === "knowledge" && showRefine && (
          <div className="absolute right-3 top-28 z-40 w-[min(25rem,calc(100%-1.5rem))] rounded-xl border border-slate-200 bg-white/95 p-3 shadow-xl backdrop-blur-sm dark:border-neutral-800 dark:bg-black lg:top-16">
            <div className="mb-3 flex items-center justify-between gap-3">
              <div className="min-w-0">
                <p className="text-xs font-black text-slate-900 dark:text-white">Refine</p>
                <p className="text-[10px] font-semibold text-slate-400">{graphStats.components} nodes · {graphStats.relationships} edges</p>
              </div>
              <button
                type="button"
                onClick={clearGraphFilters}
                className="rounded-lg border border-slate-200 px-2.5 py-1 text-[11px] font-bold text-slate-500 hover:bg-slate-50 hover:text-slate-700 dark:border-neutral-800 dark:text-neutral-300 dark:hover:bg-black"
              >
                Clear
              </button>
            </div>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              <select value={filters.model} onChange={(e) => setFilters((f) => ({ ...f, model: e.target.value }))} className="rounded-lg border border-slate-200 bg-white px-2.5 py-2 text-xs font-semibold text-slate-700 dark:border-neutral-800 dark:bg-black dark:text-neutral-300">
                <option value="">All models</option>
                {models.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
              </select>
              <select value={filters.source_type} onChange={(e) => setFilters((f) => ({ ...f, source_type: e.target.value }))} className="rounded-lg border border-slate-200 bg-white px-2.5 py-2 text-xs font-semibold text-slate-700 dark:border-neutral-800 dark:bg-black dark:text-neutral-300">
                <option value="">All sources</option>
                {sourceTypes.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
              <select value={filters.status} onChange={(e) => setFilters((f) => ({ ...f, status: e.target.value }))} className="rounded-lg border border-slate-200 bg-white px-2.5 py-2 text-xs font-semibold text-slate-700 dark:border-neutral-800 dark:bg-black dark:text-neutral-300">
                <option value="">All statuses</option>
                {statuses.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
              <select value={filters.temporal} onChange={(e) => setFilters((f) => ({ ...f, temporal: e.target.value }))} className="rounded-lg border border-slate-200 bg-white px-2.5 py-2 text-xs font-semibold text-slate-700 dark:border-neutral-800 dark:bg-black dark:text-neutral-300">
                <option value="">All time</option>
                <option value="current">Current</option>
                <option value="future">Future</option>
                <option value="past">Past</option>
                <option value="unknown">Unknown</option>
              </select>
              <select value={filters.confidence_threshold} onChange={(e) => setFilters((f) => ({ ...f, confidence_threshold: Number(e.target.value) }))} className="rounded-lg border border-slate-200 bg-white px-2.5 py-2 text-xs font-semibold text-slate-700 dark:border-neutral-800 dark:bg-black dark:text-neutral-300">
                <option value={0}>All confidence</option>
                <option value={0.5}>50% and up</option>
                <option value={0.7}>70% and up</option>
                <option value={0.85}>85% and up</option>
              </select>
              <select value={filters.relationship_origin} onChange={(e) => setFilters((f) => ({ ...f, relationship_origin: e.target.value }))} className="rounded-lg border border-slate-200 bg-white px-2.5 py-2 text-xs font-semibold text-slate-700 dark:border-neutral-800 dark:bg-black dark:text-neutral-300">
                <option value="">All edges</option>
                <option value="deterministic">Deterministic</option>
                <option value="extracted">Extracted</option>
                <option value="ai_proposed">AI proposed</option>
                <option value="human_verified">Human verified</option>
                <option value="proposed">Proposed</option>
              </select>
            </div>
            <label className="mt-3 flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-2 text-xs font-semibold text-slate-600 dark:border-neutral-800 dark:bg-black dark:text-neutral-300">
              <input
                type="checkbox"
                checked={showTrustEdges}
                onChange={(e) => setShowTrustEdges(e.target.checked)}
                className="rounded border-slate-300 text-brand-600 focus:ring-brand-500"
              />
              Show edge trust styling
            </label>
          </div>
        )}

        <div className="hidden">
          <h2 className="text-lg font-bold text-slate-900 dark:text-white">Knowledge Graph</h2>
          <div className="flex rounded-lg border border-slate-200 dark:border-neutral-800 bg-white dark:bg-black p-1">
            {[
              ["knowledge", "Knowledge"],
              ["repo", "Repository"],
            ].map(([mode, label]) => (
              <button
                key={mode}
                type="button"
                onClick={() => setViewMode(mode)}
                className={`rounded-md px-3 py-1.5 text-xs font-bold transition-colors ${
                  viewMode === mode
                    ? "bg-slate-900 text-white dark:bg-white dark:text-slate-900"
                    : "text-slate-500 hover:text-slate-900 dark:text-neutral-400 dark:hover:text-white"
                }`}
              >
                {label}
              </button>
            ))}
          </div>
          {viewMode === "knowledge" && (
            <div className="hidden md:flex items-center gap-2 rounded-lg border border-slate-200 dark:border-neutral-800 bg-white dark:bg-black px-2.5 py-1.5 text-[11px] font-bold text-slate-500 dark:text-neutral-400">
              <Network className="h-3.5 w-3.5 text-brand-500" />
              <span className="text-slate-900 dark:text-white">{graphStats.components}</span>
              <span>nodes</span>
              <span className="h-3 w-px bg-slate-200 dark:bg-black" />
              <span className="text-slate-900 dark:text-white">{graphStats.relationships}</span>
              <span>edges</span>
              {graphStats.isolated > 0 && (
                <>
                  <span className="h-3 w-px bg-slate-200 dark:bg-black" />
                  <span className="text-red-500">{graphStats.isolated}</span>
                  <span>isolated</span>
                </>
              )}
            </div>
          )}
          {viewMode === "knowledge" && showRefine && (
          <div className="flex gap-1.5 flex-wrap min-w-0">
            <select
              value={filters.model}
              onChange={(e) => setFilters((f) => ({ ...f, model: e.target.value }))}
              className="text-xs px-2.5 py-1.5 rounded-lg border border-slate-200 dark:border-neutral-800 bg-white dark:bg-black text-slate-700 dark:text-neutral-300 max-w-[9.5rem]"
            >
              <option value="">All models</option>
              {models.map((m) => (
                <option key={m.id} value={m.id}>{m.name}</option>
              ))}
            </select>
            <select
              value={filters.source_type}
              onChange={(e) => setFilters((f) => ({ ...f, source_type: e.target.value }))}
              className="text-xs px-2.5 py-1.5 rounded-lg border border-slate-200 dark:border-neutral-800 bg-white dark:bg-black text-slate-700 dark:text-neutral-300 max-w-[9.5rem]"
            >
              <option value="">All sources</option>
              {sourceTypes.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
            <select
              value={filters.status}
              onChange={(e) => setFilters((f) => ({ ...f, status: e.target.value }))}
              className="text-xs px-2.5 py-1.5 rounded-lg border border-slate-200 dark:border-neutral-800 bg-white dark:bg-black text-slate-700 dark:text-neutral-300 max-w-[9.5rem]"
            >
              <option value="">All statuses</option>
              {statuses.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
            <select
              value={filters.temporal}
              onChange={(e) => setFilters((f) => ({ ...f, temporal: e.target.value }))}
              className="text-xs px-2.5 py-1.5 rounded-lg border border-slate-200 dark:border-neutral-800 bg-white dark:bg-black text-slate-700 dark:text-neutral-300 max-w-[9.5rem]"
            >
              <option value="">All time</option>
              <option value="current">Current (needs now)</option>
              <option value="future">Future (will do)</option>
              <option value="past">Past (was done)</option>
              <option value="unknown">Unknown</option>
            </select>
            <select
              value={filters.confidence_threshold}
              onChange={(e) => setFilters((f) => ({ ...f, confidence_threshold: Number(e.target.value) }))}
              className="text-xs px-2.5 py-1.5 rounded-lg border border-slate-200 dark:border-neutral-800 bg-white dark:bg-black text-slate-700 dark:text-neutral-300 max-w-[9.5rem]"
            >
              <option value={0}>All confidence</option>
              <option value={0.5}>≥ 50%</option>
              <option value={0.7}>≥ 70%</option>
              <option value={0.85}>≥ 85%</option>
            </select>
            <select
              value={filters.relationship_origin}
              onChange={(e) => setFilters((f) => ({ ...f, relationship_origin: e.target.value }))}
              className="text-xs px-2.5 py-1.5 rounded-lg border border-slate-200 dark:border-neutral-800 bg-white dark:bg-black text-slate-700 dark:text-neutral-300 max-w-[9.5rem]"
            >
              <option value="">All edges</option>
              <option value="deterministic">Deterministic</option>
              <option value="extracted">Extracted</option>
              <option value="ai_proposed">AI Proposed</option>
              <option value="human_verified">Human Verified</option>
              <option value="proposed">Proposed</option>
            </select>
            <div className="relative">
              <svg className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
                <circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/>
              </svg>
              <input
                type="text"
                value={filters.search}
                onChange={(e) => setFilters((f) => ({ ...f, search: e.target.value }))}
                placeholder="Search graph…"
                className="text-xs pl-8 pr-2.5 py-1.5 rounded-lg border border-slate-200 dark:border-neutral-800 bg-white dark:bg-black text-slate-700 dark:text-neutral-300 w-40 focus:outline-none focus:ring-1 focus:ring-brand-400"
              />
              {filters.search && (
                <button
                  onClick={() => setFilters((f) => ({ ...f, search: "" }))}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
                >
                  <XIcon className="w-3 h-3" />
                </button>
              )}
            </div>
          </div>
          )}
          <div className="ml-auto flex items-center gap-2">
            {viewMode === "knowledge" && (
              <button
                type="button"
                onClick={() => setShowRefine((v) => !v)}
                className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border text-xs font-bold transition-colors ${
                  showRefine
                    ? "border-sky-400 bg-sky-50 text-sky-700 dark:border-sky-600 dark:bg-sky-900/20 dark:text-sky-300"
                    : "border-slate-200 dark:border-neutral-800 bg-white dark:bg-black text-slate-600 dark:text-neutral-300 hover:bg-slate-50 dark:hover:bg-black"
                }`}
              >
                <SlidersHorizontal className="w-3.5 h-3.5" />
                Filters
              </button>
            )}
            {agentStatus && (
              <span className={`text-[10px] font-bold uppercase tracking-wider px-2 py-1 rounded-full ${aiSettings.api_key || agentStatus.llm_enabled ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400" : "bg-slate-100 text-slate-500 dark:bg-black dark:text-neutral-400"}`}>
                {aiSettings.api_key && aiSettings.model ? `AI: ${aiSettings.model}` : agentStatus.llm_enabled ? `LLM: ${agentStatus.extraction_model}` : "Regex extraction"}
              </span>
            )}
            <button
              type="button"
              onClick={() => setShowAiSettings(true)}
              title="Configure AI extraction"
              className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border text-xs font-bold transition-colors ${aiSettings.api_key ? "border-brand-400 bg-brand-50 text-brand-700 dark:border-brand-600 dark:bg-brand-900/20 dark:text-brand-400" : "border-slate-200 dark:border-neutral-800 bg-white dark:bg-black text-slate-500 dark:text-neutral-400 hover:bg-slate-50 dark:hover:bg-black"}`}
            >
              <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="3"/>
                <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>
              </svg>
              {aiSettings.api_key ? "AI ready" : "Configure AI"}
            </button>
            <button
              type="button"
              onClick={() => {
                setShowAsk((v) => !v);
                setAskResult(null);
                setAskError(null);
                setTimeout(() => askInputRef.current?.focus(), 80);
              }}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-xs font-bold transition-colors ${
                showAsk
                  ? "border-brand-500 bg-brand-50 text-brand-700 dark:border-brand-500 dark:bg-brand-900/20 dark:text-brand-400"
                  : "border-slate-200 dark:border-neutral-800 bg-white dark:bg-black text-slate-600 dark:text-neutral-300 hover:bg-slate-50 dark:hover:bg-black"
              }`}
            >
              <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round">
                <circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/><path d="M11 8v6M8 11h6"/>
              </svg>
              Ask AI
            </button>
            <button
              type="button"
              onClick={() => { setShowAgents((v) => !v); setSelectedNode(null); }}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-xs font-bold transition-colors ${
                showAgents
                  ? "border-violet-500 bg-violet-50 text-violet-700 dark:border-violet-500 dark:bg-violet-900/20 dark:text-violet-400"
                  : "border-slate-200 dark:border-neutral-800 bg-white dark:bg-black text-slate-600 dark:text-neutral-300 hover:bg-slate-50 dark:hover:bg-black"
              }`}
            >
              <Bot className="w-3.5 h-3.5" />
              Agents
            </button>
            <button
              type="button"
              onClick={handleBuildGraph}
              disabled={building}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-brand-600 hover:bg-brand-700 disabled:opacity-60 disabled:cursor-not-allowed text-white text-xs font-bold transition-colors"
            >
              {building ? (
                <>
                  <span className="w-3 h-3 rounded-full border-2 border-white/30 border-t-white animate-spin" />
                  Building…
                </>
              ) : (
                <>
                  <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M12 2L2 7l10 5 10-5-10-5z"/>
                    <path d="M2 17l10 5 10-5"/>
                    <path d="M2 12l10 5 10-5"/>
                  </svg>
                  Build Graph
                </>
              )}
            </button>
          </div>
        </div>

        {/* ── CEO Views ─────────────────────────────────────────── */}
        {viewMode === "knowledge" && (
          <div className="hidden">
            <span className="text-[10px] font-bold uppercase tracking-widest text-slate-400 shrink-0">CEO View</span>
            <div className="flex gap-1.5 flex-wrap">
              {BOARD_LENSES.map(({ id, label, desc }) => (
                <button
                  key={id}
                  type="button"
                  title={desc}
                  onClick={() => setBoardLens(id)}
                  className={`px-2.5 py-1 rounded-full text-[11px] font-bold transition-all ${
                    boardLens === id
                      ? id === "gaps"       ? "bg-red-500 text-white shadow-sm"
                      : id === "aiSessions" ? "bg-violet-600 text-white shadow-sm"
                      : id === "github"     ? "bg-slate-600 text-white shadow-sm"
                      : "bg-slate-900 dark:bg-white text-white dark:text-slate-900 shadow-sm"
                      : "bg-slate-100 dark:bg-black text-slate-500 dark:text-neutral-400 hover:bg-slate-200 dark:hover:bg-black"
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
            {activeBoardLens && boardLens !== "all" && (
              <span className="text-[10px] text-slate-400 italic hidden lg:inline">{activeBoardLens.desc}</span>
            )}
          </div>
        )}

        {viewMode === "knowledge" && showRefine && (
          <div className="hidden">
            <GraphStat label="Nodes" value={graphStats.components} />
            <GraphStat label="Edges" value={graphStats.relationships} />
            <GraphStat label="Risks" value={graphStats.blockers} tone={graphStats.blockers ? "red" : "slate"} />
            <GraphStat label="GitHub" value={graphStats.github} icon={GitPullRequest} />
            <GraphStat label="AI Sessions" value={graphStats.agents} icon={Bot} />
            <GraphStat label="Proposed" value={graphStats.proposedEdges} tone={graphStats.proposedEdges ? "amber" : "slate"} />
            <GraphStat label="Isolated" value={graphStats.isolated} tone={graphStats.isolated ? "red" : "slate"} />
          </div>
        )}

        {buildResult && !buildResult.error && (
          <div className="absolute left-1/2 top-24 z-40 flex w-[min(42rem,calc(100%-1.5rem))] -translate-x-1/2 items-start gap-3 rounded-xl border border-emerald-200 bg-emerald-50/95 px-4 py-3 text-xs shadow-xl backdrop-blur-sm dark:border-emerald-800 dark:bg-emerald-900/80">
            <svg className="w-4 h-4 text-emerald-600 dark:text-emerald-400 shrink-0 mt-0.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="20 6 9 17 4 12"/>
            </svg>
            <div className="flex-1 min-w-0">
              <p className="font-bold text-emerald-800 dark:text-emerald-300 mb-1">Graph built successfully</p>
              <div className="flex flex-wrap gap-x-4 gap-y-0.5 text-emerald-700 dark:text-emerald-400">
                <span>{buildResult.docs_processed} docs processed</span>
                <span>{buildResult.components_created} components created</span>
                <span>{buildResult.relationships_inferred} relationships inferred</span>
              </div>
              {buildResult.errors?.length > 0 && (
                <p className="mt-1 text-amber-600 dark:text-amber-400">{buildResult.errors.length} doc(s) had errors</p>
              )}
            </div>
            <button onClick={() => setBuildResult(null)} className="text-emerald-500 hover:text-emerald-700 dark:hover:text-emerald-300 font-bold ml-auto shrink-0">✕</button>
          </div>
        )}
        {buildResult?.error && (
          <div className="absolute left-1/2 top-24 z-40 flex w-[min(42rem,calc(100%-1.5rem))] -translate-x-1/2 items-center justify-between rounded-xl border border-red-200 bg-red-50/95 px-4 py-3 text-xs text-red-700 shadow-xl backdrop-blur-sm dark:border-red-800 dark:bg-red-900/80 dark:text-red-400">
            <span>Build failed: {buildResult.error}</span>
            <button onClick={() => setBuildResult(null)} className="font-bold ml-4">✕</button>
          </div>
        )}

        <div
          className="flex-1 relative min-h-0 overflow-hidden"
          style={{
            backgroundColor: theme === "dark" ? "#000" : "#fff",
            backgroundImage: theme === "dark"
              ? "radial-gradient(circle at 1px 1px, rgba(255,255,255,0.075) 1px, transparent 0)"
              : "radial-gradient(circle at 1px 1px, rgba(15,23,42,0.11) 1px, transparent 0)",
            backgroundSize: "22px 22px",
          }}
        >
          <div ref={containerRef} className="absolute inset-0" />
          <div ref={logoLayerRef} className="pointer-events-none absolute inset-0 z-10" />

          {graphLayout === "explore" && viewMode === "knowledge" && (
            <div className="absolute bottom-16 right-4 top-24 z-30 flex w-[min(20rem,calc(100%-2rem))] flex-col overflow-hidden rounded-xl border border-slate-200 bg-white/95 shadow-xl backdrop-blur-sm dark:border-neutral-800 dark:bg-black">
              <div className="border-b border-slate-100 px-3 py-3 dark:border-neutral-800">
                <div className="flex items-center justify-between gap-2">
                  <div className="min-w-0">
                    <p className="text-xs font-black text-slate-900 dark:text-white">Local graph</p>
                    <p className="mt-0.5 text-[10px] font-semibold text-slate-400">
                      Orphans hidden · {currentViewData.relationships?.length || 0} visible edges
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => {
                      const nodeId = selectedNode?.id;
                      setGraphLayout("board");
                      if (nodeId) setTimeout(() => focusGraphNode(nodeId), 260);
                    }}
                    className="rounded-lg border border-slate-200 px-2.5 py-1 text-[10px] font-bold text-slate-500 hover:bg-slate-50 hover:text-slate-800 dark:border-neutral-800 dark:text-neutral-300 dark:hover:bg-black"
                  >
                    Open in Board
                  </button>
                </div>
                <div className="mt-3 grid grid-cols-2 gap-1 rounded-lg bg-slate-100 p-0.5 dark:bg-black">
                  {[1, 2].map((depth) => (
                    <button
                      key={depth}
                      type="button"
                      onClick={() => setExploreDepth(depth)}
                      className={`rounded-md px-2 py-1 text-[10px] font-bold transition ${
                        exploreDepth === depth
                          ? "bg-white text-slate-900 shadow-sm dark:bg-black dark:text-white"
                          : "text-slate-500 hover:text-slate-800 dark:text-neutral-400 dark:hover:text-white"
                      }`}
                    >
                      {depth}-hop
                    </button>
                  ))}
                </div>
              </div>
              <div className="min-h-0 flex-1 overflow-y-auto p-3">
                {!selectedNode ? (
                  <div className="rounded-lg border border-dashed border-slate-200 p-4 text-center dark:border-neutral-800">
                    <Network className="mx-auto mb-2 h-6 w-6 text-slate-300 dark:text-slate-600" />
                    <p className="text-xs font-semibold text-slate-600 dark:text-neutral-300">Select a node to inspect its neighborhood.</p>
                  </div>
                ) : exploreNeighborhood.length === 0 ? (
                  <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs text-slate-500 dark:border-neutral-800 dark:bg-black dark:text-neutral-400">
                    No visible neighbors for {selectedNode.label}.
                  </div>
                ) : (
                  <div className="space-y-2">
                    <p className="truncate text-[11px] font-bold uppercase tracking-wide text-slate-400">
                      {selectedNode.label}
                    </p>
                    {exploreNeighborhood.map((neighbor) => (
                      <button
                        key={`${neighbor.id}-${neighbor.depth}`}
                        type="button"
                        onClick={() => focusGraphNode(neighbor.id)}
                        className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-left transition hover:border-brand-300 hover:bg-brand-50 dark:border-neutral-800 dark:bg-black dark:hover:border-brand-700 dark:hover:bg-brand-900/20"
                      >
                        <div className="flex items-center justify-between gap-2">
                          <span className="truncate text-xs font-bold text-slate-800 dark:text-neutral-100">{neighbor.display_title || neighbor.name}</span>
                          <span className="shrink-0 rounded-full bg-slate-100 px-1.5 py-0.5 text-[9px] font-bold text-slate-500 dark:bg-black dark:text-neutral-300">
                            {neighbor.depth} hop
                          </span>
                        </div>
                        <p className="mt-1 text-[10px] font-semibold text-brand-600 dark:text-brand-400">{neighbor.relationship_label}</p>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}

          <div className="absolute bottom-4 left-4 z-20 flex flex-col items-center gap-1 rounded-xl border border-slate-200 bg-white/92 p-1 shadow-sm backdrop-blur-sm dark:border-neutral-800 dark:bg-black">
            <button type="button" title="Zoom in" onClick={() => changeGraphZoom(0.12)} className="flex h-8 w-8 items-center justify-center rounded-lg text-slate-500 hover:bg-slate-100 hover:text-slate-800 dark:text-neutral-300 dark:hover:bg-black dark:hover:text-white">
              <Plus className="h-3.5 w-3.5" />
            </button>
            <button type="button" title="Zoom out" onClick={() => changeGraphZoom(-0.12)} className="flex h-8 w-8 items-center justify-center rounded-lg text-slate-500 hover:bg-slate-100 hover:text-slate-800 dark:text-neutral-300 dark:hover:bg-black dark:hover:text-white">
              <Minus className="h-3.5 w-3.5" />
            </button>
            <button type="button" title="Fit whole graph" onClick={fitGraph} className="flex h-8 w-8 items-center justify-center rounded-lg text-slate-500 hover:bg-slate-100 hover:text-slate-800 dark:text-neutral-300 dark:hover:bg-black dark:hover:text-white">
              <Maximize2 className="h-3.5 w-3.5" />
            </button>
          </div>

          <GraphMinimap overview={graphOverview} onCenter={centerGraphOnOverviewPoint} theme={theme} />

          <div className="absolute bottom-4 right-4 z-20 flex items-center gap-2">
            <button
              type="button"
              onClick={handleBuildGraph}
              disabled={building}
              className="flex h-10 items-center gap-1.5 rounded-xl bg-brand-600 px-3.5 text-xs font-bold text-white shadow-lg shadow-brand-600/20 transition-colors hover:bg-brand-700 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {building ? (
                <>
                  <span className="h-3.5 w-3.5 rounded-full border-2 border-white/30 border-t-white animate-spin" />
                  Building...
                </>
              ) : (
                <>
                  <Layers3 className="h-4 w-4" />
                  Build Graph
                </>
              )}
            </button>
          </div>

          {/* Side-panel toggle — top right of canvas */}
          <div className="hidden">
            <button
              type="button"
              title="Source coverage & work lens"
              onClick={() => setShowSidePanel((v) => !v)}
              className={`flex h-7 items-center gap-1 px-2 rounded-lg text-[11px] font-bold transition-colors ${
                showSidePanel
                  ? "bg-brand-100 text-brand-700 dark:bg-brand-900/30 dark:text-brand-400"
                  : "text-slate-500 hover:bg-slate-100 hover:text-slate-800 dark:text-neutral-300 dark:hover:bg-black dark:hover:text-white"
              }`}
            >
              <Layers3 className="h-3.5 w-3.5" />
              Panels
            </button>
          </div>

          {/* Persistent legend — top-right corner of graph canvas */}
          <div className="hidden">
            <div>
              <p className="text-[9px] font-bold uppercase tracking-widest text-slate-400 mb-1.5">Border — status</p>
              <div className="flex flex-col gap-1">
                {[
                  { color: "#22c55e", label: "Healthy / Active" },
                  { color: "#f59e0b", label: "Needs Review" },
                  { color: "#ef4444", label: "Blocked / Stale" },
                  { color: "#94a3b8", label: "Unknown" },
                ].map(({ color, label }) => (
                  <div key={label} className="flex items-center gap-1.5">
                    <span
                      className="w-8 h-3.5 rounded shrink-0 border"
                      style={{ borderColor: color, backgroundColor: `${color}18` }}
                    />
                    <span className="text-[10px] text-slate-600 dark:text-neutral-400">{label}</span>
                  </div>
                ))}
              </div>
            </div>
            <div>
              <p className="text-[9px] font-bold uppercase tracking-widest text-slate-400 mb-1.5">Chip — time horizon</p>
              <div className="flex flex-col gap-1">
                {[
                  { badge: "Now",  desc: "Current / Active" },
                  { badge: "Next", desc: "Planned / Future" },
                  { badge: "Past", desc: "Completed / Old" },
                ].map(({ badge, desc }) => (
                  <div key={badge} className="flex items-center gap-1.5">
                    <span className="text-[9px] font-bold bg-slate-100 dark:bg-black text-slate-500 dark:text-neutral-400 px-1.5 py-0.5 rounded shrink-0">{badge}</span>
                    <span className="text-[10px] text-slate-600 dark:text-neutral-400">{desc}</span>
                  </div>
                ))}
              </div>
            </div>
            <div>
              <p className="text-[9px] font-bold uppercase tracking-widest text-slate-400 mb-1.5">Box — domain</p>
              <div className="flex items-center gap-1.5">
                <span className="w-8 h-4 rounded-md shrink-0 border-2 border-indigo-400 bg-transparent" />
                <span className="text-[10px] text-slate-600 dark:text-neutral-400">Each = one domain</span>
              </div>
            </div>
            <div className="border-t border-slate-100 dark:border-neutral-800 pt-2">
              <p className="text-[9px] font-bold uppercase tracking-widest text-slate-400 mb-1.5">Edge — origin</p>
              <div className="flex flex-col gap-1">
                {[
                  { style: "solid", color: "#3b82f6", label: "Deterministic" },
                  { style: "solid", color: "#8b5cf6", label: "Extracted" },
                  { style: "dashed", color: "#f59e0b", label: "AI Proposed" },
                  { style: "solid", color: "#059669", label: "Human Verified" },
                  { style: "dotted", color: "#94a3b8", label: "Proposed" },
                ].map(({ style, color, label }) => (
                  <div key={label} className="flex items-center gap-1.5">
                    <span
                      className="w-8 h-0.5 rounded shrink-0"
                      style={
                        style === "dashed"
                          ? { borderTop: `2px dashed ${color}`, height: 0, backgroundColor: "transparent" }
                          : style === "dotted"
                          ? { borderTop: `2px dotted ${color}`, height: 0, backgroundColor: "transparent" }
                          : { backgroundColor: color, height: 2 }
                      }
                    />
                    <span className="text-[10px] text-slate-600 dark:text-neutral-400">{label}</span>
                  </div>
                ))}
              </div>
            </div>
            <div className="border-t border-slate-100 dark:border-neutral-800 pt-2">
              <p className="text-[9px] text-slate-400 italic">Click edges to see evidence</p>
            </div>
          </div>


          {/* ── Empty state when filters hide everything ─────────── */}
          {visibleCanvasItemCount === 0 && !loading && (
            <div className="absolute inset-0 z-10 flex items-center justify-center">
              <div className="text-center p-6 bg-white/95 dark:bg-black rounded-2xl border border-slate-200 dark:border-neutral-800 shadow-lg backdrop-blur-sm max-w-xs">
                <Search className="w-8 h-8 text-slate-300 dark:text-slate-600 mx-auto mb-2" />
                <p className="text-sm font-bold text-slate-800 dark:text-neutral-200 mb-1">No visible items</p>
                <p className="text-xs text-slate-500 dark:text-neutral-400 mb-3">
                  {filters.search
                    ? `No results for "${filters.search}"`
                    : graphLayout === "explore"
                    ? "Explore hides isolated facts. Use Board or add relationships to inspect orphans."
                    : "Current filters hide every node."}
                </p>
                <button
                  onClick={clearGraphFilters}
                  className="px-3 py-1.5 rounded-lg bg-brand-600 hover:bg-brand-700 text-white text-xs font-bold transition-colors"
                >
                  Clear all filters
                </button>
              </div>
            </div>
          )}

          {/* ── Ask AI slide-up panel ─────────────────────────────── */}
          {showAsk && (
            <div className="absolute bottom-0 left-0 right-0 z-20 bg-white/95 dark:bg-black backdrop-blur-sm border-t border-slate-200 dark:border-neutral-800 rounded-b-2xl shadow-xl">
              <form onSubmit={handleAsk} className="flex items-center gap-2 px-4 py-3 border-b border-slate-100 dark:border-neutral-800/60">
                <svg className="w-4 h-4 text-slate-400 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
                  <circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/>
                </svg>
                <input
                  ref={askInputRef}
                  type="text"
                  value={askQuery}
                  onChange={(e) => setAskQuery(e.target.value)}
                  placeholder="Ask within this workspace... e.g. What are the current blockers?"
                  className="flex-1 bg-transparent text-sm text-slate-900 dark:text-neutral-100 placeholder:text-slate-400 focus:outline-none"
                />
                <button
                  type="submit"
                  disabled={askLoading || !askQuery.trim()}
                  className="px-3 py-1.5 bg-brand-600 hover:bg-brand-700 disabled:opacity-50 text-white text-xs font-bold rounded-lg transition-colors flex items-center gap-1.5 shrink-0"
                >
                  {askLoading ? <span className="w-3 h-3 rounded-full border-2 border-white/30 border-t-white animate-spin" /> : null}
                  {askLoading ? "Searching…" : "Ask"}
                </button>
                <button type="button" onClick={() => { setShowAsk(false); setAskResult(null); setAskError(null); }} className="text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 text-sm font-bold ml-1">✕</button>
              </form>

              {(askResult || askError) && (
                <div className="px-4 py-3 max-h-60 overflow-y-auto">
                  {askError && (
                    <p className="text-xs text-red-600 dark:text-red-400">{askError}</p>
                  )}
                  {askResult && (
                    <div className="space-y-3">
                      {askResult.answer && (
                        <div>
                          <span className="text-[10px] font-bold uppercase tracking-widest text-slate-400">Answer</span>
                          <p className="text-sm text-slate-800 dark:text-neutral-200 leading-relaxed mt-1">{askResult.answer}</p>
                        </div>
                      )}
                      {!askResult.answer && (
                        <p className="text-xs text-slate-400 italic">Configure AI to get synthesized answers — showing matching facts below.</p>
                      )}
                      {askResult.trace?.facts_used?.length > 0 && (
                        <div>
                          <p className="text-[10px] font-bold uppercase tracking-widest text-slate-400 mb-1.5">
                            Facts used ({askResult.trace.facts_used.length})
                          </p>
                          <div className="flex flex-col gap-1.5">
                            {askResult.trace.facts_used.slice(0, 5).map((c) => (
                              <div key={c.component_id} className="flex items-start gap-2 p-2 rounded-lg bg-slate-50 dark:bg-black">
                                <span className="w-4 h-4 rounded bg-brand-100 dark:bg-brand-900/40 flex items-center justify-center text-[9px] font-bold text-brand-700 dark:text-brand-300 shrink-0 mt-0.5">{c.rank}</span>
                                <div className="min-w-0">
                                  <p className="text-[11px] font-semibold text-slate-700 dark:text-neutral-300">{c.value || stripModelPrefix(c.name)}</p>
                                  <span className="text-[10px] text-slate-400">
                                    {c.model_name} · score {Number(c.score).toFixed(2)} · {Math.round(c.confidence * 100)}%
                                  </span>
                                </div>
                              </div>
                            ))}
                          </div>
                          {askResult.trace.relationships_used?.length > 0 && (
                            <div className="mt-2 rounded-lg border border-slate-100 bg-slate-50 px-2 py-1.5 text-[10px] text-slate-500 dark:border-neutral-800 dark:bg-black dark:text-neutral-400">
                              Expanded through {askResult.trace.relationships_used.length} relationship{askResult.trace.relationships_used.length === 1 ? "" : "s"}.
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {(selectedNode || selectedEdge) && !showAgents && (
        <GraphInspector
          node={selectedNode}
          edge={selectedEdge}
          onClose={() => {
            setSelectedNode(null);
            setSelectedEdge(null);
            setEdgeReviewError(null);
          }}
          onFocusNode={focusGraphNode}
          onReviewEdge={reviewSelectedEdge}
          edgeReviewLoading={edgeReviewLoading}
          edgeReviewError={edgeReviewError}
        />
      )}

      {showSidePanel && (
        <div className="absolute bottom-3 right-3 top-20 z-40 flex w-[min(20rem,calc(100%-1.5rem))] flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-xl dark:border-neutral-800 dark:bg-black">
          <div className="flex items-center border-b border-slate-100 dark:border-neutral-800">
            {[
              { id: "coverage", label: "Coverage" },
              { id: "work", label: "Work Lens" },
            ].map((tab) => (
              <button
                key={tab.id}
                onClick={() => setSidePanelTab(tab.id)}
                className={`flex-1 px-3 py-2 text-[11px] font-bold transition-colors ${
                  sidePanelTab === tab.id
                    ? "bg-slate-50 dark:bg-black text-slate-900 dark:text-white"
                    : "text-slate-400 hover:text-slate-600 dark:hover:text-slate-300"
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>
          <div className="flex-1 overflow-y-auto p-3">
            {sidePanelTab === "coverage" && (
              <SourceCoveragePanel components={allComponents} />
            )}
            {sidePanelTab === "work" && (
              <WorkLensPanel data={workLens} loading={workLensLoading} />
            )}
          </div>
        </div>
      )}

      {showAgents && (
        <AgentsSidebarPanel
          onClose={() => setShowAgents(false)}
          gapReport={gapReport} gapLoading={gapLoading} gapError={gapError}
          onRunGaps={() => callAgent("/api/agents/gaps", setGapLoading, setGapReport, setGapError)}
          relReport={relReport} relLoading={relLoading} relError={relError}
          onRunRel={() => callAgent("/api/agents/relationships", setRelLoading, setRelReport, setRelError)}
          packResult={packResult} packLoading={packLoading} packError={packError} packCopied={packCopied}
          selectedNode={selectedNode}
          onRunPack={() => callAgent(
            "/api/agents/context-pack",
            setPackLoading,
            setPackResult,
            setPackError,
            selectedNode?.id ? { component_ids: [selectedNode.id] } : {},
          )}
          onCopyPack={copyPack}
        />
      )}

      {showAiSettings && (
        <div className="fixed inset-0 bg-black/40 backdrop-blur-sm z-50 flex items-center justify-center" onClick={() => setShowAiSettings(false)}>

          <div className="bg-white dark:bg-black rounded-2xl border border-slate-200 dark:border-neutral-800 p-6 w-[22rem] shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-5">
              <div>
                <h3 className="text-sm font-bold text-slate-900 dark:text-white">AI Extraction Settings</h3>
                <p className="text-[10px] text-slate-400 dark:text-slate-500 mt-0.5">Bring your own API key to power intelligent graph building</p>
              </div>
              <button onClick={() => setShowAiSettings(false)} className="text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 text-sm font-bold ml-3">✕</button>
            </div>

            <div className="space-y-4">
              <div>
                <label className="block text-xs font-semibold text-slate-600 dark:text-neutral-400 mb-1.5">Provider</label>
                <select
                  value={aiSettings.provider || ""}
                  onChange={(e) => {
                    const p = e.target.value;
                    const newS = { ...aiSettings, provider: p, model: "" };
                    setAiSettings(newS);
                    localStorage.setItem("ce_ai_settings", JSON.stringify(newS));
                  }}
                  className="w-full text-xs px-3 py-2 rounded-lg border border-slate-200 dark:border-neutral-700 bg-slate-50 dark:bg-black text-slate-700 dark:text-neutral-300"
                >
                  <option value="">— select provider —</option>
                  <option value="google">Google (Gemini)</option>
                  <option value="anthropic">Anthropic (Claude)</option>
                  <option value="openai">OpenAI (GPT)</option>
                  <option value="custom">OpenAI-compatible API</option>
                </select>
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-600 dark:text-neutral-400 mb-1.5">API Key</label>
                <input
                  type="password"
                  value={aiSettings.api_key || ""}
                  onChange={(e) => {
                    const newS = { ...aiSettings, api_key: e.target.value };
                    setAiSettings(newS);
                    localStorage.setItem("ce_ai_settings", JSON.stringify(newS));
                  }}
                  placeholder={
                    aiSettings.provider === "anthropic" ? "sk-ant-..." :
                    aiSettings.provider === "google" ? "AIza..." :
                    "sk-..."
                  }
                  className="w-full text-xs px-3 py-2 rounded-lg border border-slate-200 dark:border-neutral-700 bg-slate-50 dark:bg-black text-slate-700 dark:text-neutral-300 font-mono"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-600 dark:text-neutral-400 mb-1.5">Model</label>
                {aiSettings.provider === "custom" ? (
                  <input
                    type="text"
                    value={aiSettings.model || ""}
                    onChange={(e) => {
                      const newS = { ...aiSettings, model: e.target.value };
                      setAiSettings(newS);
                      localStorage.setItem("ce_ai_settings", JSON.stringify(newS));
                    }}
                    placeholder="e.g. mistral-large, llama-3-70b"
                    className="w-full text-xs px-3 py-2 rounded-lg border border-slate-200 dark:border-neutral-700 bg-slate-50 dark:bg-black text-slate-700 dark:text-neutral-300 font-mono"
                  />
                ) : (
                  <select
                    value={aiSettings.model || ""}
                    onChange={(e) => {
                      const newS = { ...aiSettings, model: e.target.value };
                      setAiSettings(newS);
                      localStorage.setItem("ce_ai_settings", JSON.stringify(newS));
                    }}
                    className="w-full text-xs px-3 py-2 rounded-lg border border-slate-200 dark:border-neutral-700 bg-slate-50 dark:bg-black text-slate-700 dark:text-neutral-300 font-mono"
                  >
                    <option value="">— select model —</option>
                    {aiSettings.provider === "google" ? (
                      <>
                        <option value="gemini/gemini-2.5-flash">gemini-2.5-flash (recommended)</option>
                        <option value="gemini/gemini-2.5-flash-lite">gemini-2.5-flash-lite (fastest)</option>
                      </>
                    ) : aiSettings.provider === "anthropic" ? (
                      <>
                        <option value="claude-3-5-sonnet-20241022">claude-3-5-sonnet-20241022</option>
                        <option value="claude-3-5-haiku-20241022">claude-3-5-haiku-20241022</option>
                        <option value="claude-3-opus-20240229">claude-3-opus-20240229</option>
                      </>
                    ) : aiSettings.provider === "openai" ? (
                      <>
                        <option value="gpt-4o">gpt-4o</option>
                        <option value="gpt-4o-mini">gpt-4o-mini</option>
                      </>
                    ) : (
                      <option value="" disabled>Select a provider first</option>
                    )}
                  </select>
                )}
              </div>

              <div className="rounded-lg bg-slate-50 dark:bg-black border border-slate-200 dark:border-neutral-800 px-3 py-2.5 space-y-1.5">
                <p className="text-[10px] font-semibold text-slate-500 dark:text-neutral-400">How it works</p>
                <p className="text-[10px] text-slate-500 dark:text-neutral-400 leading-relaxed">
                  When you click <strong className="text-slate-600 dark:text-neutral-300">Build Graph</strong>, your synced source documents are sent to the AI. It reads each document and extracts:
                </p>
                <ul className="text-[10px] text-slate-500 dark:text-neutral-400 leading-relaxed list-disc pl-3 space-y-0.5">
                  <li><strong className="text-slate-600 dark:text-neutral-300">Domain models</strong> — business areas like Pricing, Features, Decisions</li>
                  <li><strong className="text-slate-600 dark:text-neutral-300">Atomic facts</strong> — each tagged as current, past, or future</li>
                  <li><strong className="text-slate-600 dark:text-neutral-300">Relationships</strong> — logical links between facts across models</li>
                </ul>
                <p className="text-[10px] text-slate-500 dark:text-neutral-400 leading-relaxed mt-1">
                  Without a key, the built-in regex fallback is used instead. Your key never leaves this browser.
                </p>
              </div>

              <div className="flex gap-2 pt-1">
                <button
                  onClick={() => setShowAiSettings(false)}
                  className="flex-1 px-4 py-2 rounded-lg bg-brand-600 hover:bg-brand-700 text-white text-xs font-bold transition-colors"
                >
                  {aiSettings.api_key ? "Save & Close" : "Close"}
                </button>
                {aiSettings.api_key && (
                  <button
                    onClick={() => {
                      const newS = {};
                      setAiSettings(newS);
                      localStorage.removeItem("ce_ai_settings");
                    }}
                    className="px-3 py-2 rounded-lg border border-slate-200 dark:border-neutral-700 text-slate-500 dark:text-neutral-400 text-xs font-bold hover:bg-slate-50 dark:hover:bg-black transition-colors"
                  >
                    Clear
                  </button>
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function GraphMinimap({ overview, onCenter, theme }) {
  const svgRef = useRef(null);
  if (!overview?.bounds || !overview.nodes?.length) return null;

  const width = 184;
  const height = 118;
  const padding = 10;
  const usableWidth = width - padding * 2;
  const usableHeight = height - padding * 2;
  const scale = Math.min(usableWidth / overview.bounds.w, usableHeight / overview.bounds.h);
  const offsetX = padding + (usableWidth - overview.bounds.w * scale) / 2 - overview.bounds.x * scale;
  const offsetY = padding + (usableHeight - overview.bounds.h * scale) / 2 - overview.bounds.y * scale;
  const x = (value) => value * scale + offsetX;
  const y = (value) => value * scale + offsetY;
  const graphNodes = overview.nodes.filter((node) => node.type !== "model");
  const groupNodes = overview.nodes.filter((node) => node.type === "model");
  const viewport = overview.viewport
    ? {
      x: x(overview.viewport.x),
      y: y(overview.viewport.y),
      w: overview.viewport.w * scale,
      h: overview.viewport.h * scale,
    }
    : null;

  function handlePointerDown(event) {
    if (!svgRef.current || !onCenter) return;
    const rect = svgRef.current.getBoundingClientRect();
    const sx = ((event.clientX - rect.left) / rect.width) * width;
    const sy = ((event.clientY - rect.top) / rect.height) * height;
    onCenter({
      x: (sx - offsetX) / scale,
      y: (sy - offsetY) / scale,
    });
  }

  const isDark = theme === "dark";

  return (
    <div className="absolute bottom-20 right-4 z-20 rounded-xl border border-slate-200 bg-white/90 p-1.5 shadow-sm backdrop-blur-sm dark:border-neutral-800 dark:bg-black">
      <svg
        ref={svgRef}
        width={width}
        height={height}
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label="Graph minimap"
        onPointerDown={handlePointerDown}
        className="block cursor-crosshair rounded-lg"
      >
        <rect
          x="0"
          y="0"
          width={width}
          height={height}
          rx="8"
          fill={isDark ? "rgba(2,6,23,0.96)" : "rgba(248,250,252,0.96)"}
        />
        <pattern id="graph-minimap-grid" width="12" height="12" patternUnits="userSpaceOnUse">
          <circle cx="1" cy="1" r="0.8" fill={isDark ? "rgba(148,163,184,0.28)" : "rgba(100,116,139,0.28)"} />
        </pattern>
        <rect x="0" y="0" width={width} height={height} rx="8" fill="url(#graph-minimap-grid)" />
        {groupNodes.map((node) => (
          <rect
            key={node.id}
            x={x(node.x)}
            y={y(node.y)}
            width={Math.max(8, node.w * scale)}
            height={Math.max(8, node.h * scale)}
            rx="4"
            fill="transparent"
            stroke={node.stroke}
            strokeWidth="1"
            opacity="0.28"
          />
        ))}
        {overview.edges.map((edge) => (
          <line
            key={edge.id}
            x1={x(edge.x1)}
            y1={y(edge.y1)}
            x2={x(edge.x2)}
            y2={y(edge.y2)}
            stroke={edge.color}
            strokeWidth="1"
            opacity="0.28"
          />
        ))}
        {graphNodes.map((node) => (
          <rect
            key={node.id}
            x={x(node.x)}
            y={y(node.y)}
            width={Math.max(node.type === "sourceHub" ? 7 : 4, node.w * scale)}
            height={Math.max(node.type === "sourceHub" ? 5 : 3, node.h * scale)}
            rx={node.type === "sourceHub" ? "2" : "1.5"}
            fill={node.fill}
            stroke={node.stroke}
            strokeWidth="1"
            opacity="0.82"
          />
        ))}
        {viewport && (
          <rect
            x={viewport.x}
            y={viewport.y}
            width={Math.max(12, viewport.w)}
            height={Math.max(10, viewport.h)}
            rx="3"
            fill="transparent"
            stroke={isDark ? "#f8fafc" : "#0f172a"}
            strokeWidth="1.5"
            opacity="0.9"
          />
        )}
      </svg>
    </div>
  );
}

function GraphStat({ label, value, icon: Icon, tone = "slate" }) {
  const tones = {
    slate: "border-slate-200 bg-white text-slate-700 dark:border-neutral-800 dark:bg-black dark:text-neutral-200",
    red: "border-red-200 bg-red-50 text-red-700 dark:border-red-900/50 dark:bg-red-950/30 dark:text-red-300",
    amber: "border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900/50 dark:bg-amber-950/30 dark:text-amber-300",
  };
  const iconClass = tone === "red" ? "text-red-500" : tone === "amber" ? "text-amber-500" : "text-slate-400";
  return (
    <div className={`flex min-h-11 items-center justify-between gap-2 rounded-lg border px-2.5 py-1.5 ${tones[tone] || tones.slate}`}>
      <div className="min-w-0">
        <p className="text-[9px] font-bold uppercase tracking-widest opacity-60">{label}</p>
        <p className="text-base font-black leading-tight">{value}</p>
      </div>
      {Icon ? <Icon className={`h-4 w-4 shrink-0 ${iconClass}`} /> : <ShieldCheck className={`h-4 w-4 shrink-0 ${iconClass}`} />}
    </div>
  );
}

/* ── Agents Sidebar Panel ─────────────────────────────────────────── */

function AgentsSidebarPanel({
  onClose,
  gapReport, gapLoading, gapError, onRunGaps,
  relReport, relLoading, relError, onRunRel,
  packResult, packLoading, packError, packCopied, selectedNode, onRunPack, onCopyPack,
}) {
  return (
    <div className="absolute bottom-3 right-3 top-20 z-40 flex w-[min(22rem,calc(100%-1.5rem))] flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-xl dark:border-neutral-800 dark:bg-black">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-100 dark:border-neutral-800 shrink-0">
        <div className="flex items-center gap-2">
          <div className="w-6 h-6 rounded-lg bg-violet-500 flex items-center justify-center">
            <Bot className="w-3.5 h-3.5 text-white" />
          </div>
          <span className="text-sm font-bold text-slate-900 dark:text-white">AI Agents</span>
        </div>
        <button
          onClick={onClose}
          className="w-6 h-6 flex items-center justify-center rounded-md text-slate-400 hover:text-slate-600 hover:bg-slate-100 dark:hover:bg-black transition-colors"
        >
          <XIcon className="w-3.5 h-3.5" />
        </button>
      </div>

      {/* Scrollable agent list */}
      <div className="flex-1 overflow-y-auto p-3 space-y-3">

        {/* 01 Ingestion */}
        <AgentRow
          icon={<Zap className="w-3.5 h-3.5" />}
          iconColor="bg-blue-500"
          num="01"
          title="Ingestion"
          desc="Slack · GitHub · Gmail → clean entities"
          action={
            <a href="/app/graph" className="text-[10px] font-bold text-slate-500 dark:text-neutral-400 hover:text-slate-700 dark:hover:text-slate-200 border border-slate-200 dark:border-neutral-700 px-2 py-1 rounded-lg transition-colors whitespace-nowrap">
              Build Graph →
            </a>
          }
        />

        {/* 02 Relationship */}
        <AgentRow
          icon={<Network className="w-3.5 h-3.5" />}
          iconColor="bg-violet-500"
          num="02"
          title="Relationships"
          desc="Finds hidden links across all sources"
          action={
            <SidebarRunBtn loading={relLoading} onClick={onRunRel} color="violet">
              Run
            </SidebarRunBtn>
          }
        >
          {relError && <SidebarError>{relError}</SidebarError>}
          {relReport && (
            <div className="mt-2 space-y-1.5">
              <p className="text-[10px] text-slate-400">{relReport.message}</p>
              {relReport.suggested?.slice(0, 3).map((r, i) => (
                <div key={i} className="flex items-start gap-1.5 p-2 rounded-lg bg-slate-50 dark:bg-black border border-slate-100 dark:border-neutral-800/50">
                  <span className={`text-[9px] font-bold px-1 rounded shrink-0 mt-0.5 ${r.confidence >= 0.7 ? "bg-emerald-100 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-400" : "bg-slate-100 dark:bg-black text-slate-500"}`}>
                    {Math.round(r.confidence * 100)}%
                  </span>
                  <p className="text-[10px] text-slate-600 dark:text-neutral-400 leading-snug">
                    <span className="font-semibold text-slate-700 dark:text-neutral-300">{r.source_name}</span>
                    <span className="text-slate-400 mx-1">→</span>
                    {r.target_name}
                  </p>
                </div>
              ))}
              {relReport.suggested?.length === 0 && relReport.duplicates?.length === 0 && (
                <p className="text-[10px] text-slate-400 italic text-center py-2">No hidden relationships found.</p>
              )}
            </div>
          )}
        </AgentRow>

        {/* 03 Gap Detector — hero */}
        <div className="rounded-xl border-2 border-red-200 dark:border-red-900/60 overflow-hidden">
          <div className="px-3 py-2.5 bg-gradient-to-br from-red-50 to-orange-50/50 dark:from-red-950/40 dark:to-transparent border-b border-red-100 dark:border-red-900/40">
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2 min-w-0">
                <div className="w-5 h-5 rounded-md bg-red-500 flex items-center justify-center shrink-0">
                  <AlertTriangle className="w-3 h-3 text-white" />
                </div>
                <div className="min-w-0">
                  <div className="flex items-center gap-1.5">
                    <span className="text-[9px] font-bold text-red-500 dark:text-red-400 uppercase tracking-wide">03 · Killer Feature</span>
                  </div>
                  <p className="text-xs font-bold text-slate-900 dark:text-white leading-none mt-0.5">Gap Detector</p>
                </div>
              </div>
              <SidebarRunBtn loading={gapLoading} onClick={onRunGaps} color="red">
                Run
              </SidebarRunBtn>
            </div>
            <p className="text-[10px] text-slate-500 dark:text-neutral-400 mt-1.5 leading-relaxed">
              Scans the full graph — finds missing owners, blocked items, isolated nodes.
            </p>
          </div>
          {(gapError || gapReport) && (
            <div className="p-3 space-y-2">
              {gapError && <SidebarError>{gapError}</SidebarError>}
              {gapReport && <GapSidebarResult report={gapReport} />}
            </div>
          )}
        </div>

        {/* 04 Ask */}
        <AgentRow
          icon={<MessageSquare className="w-3.5 h-3.5" />}
          iconColor="bg-brand-500"
          num="04"
          title="Ask AI"
          desc="Questions over the full graph with citations"
          action={
            <a href="/app/query" className="text-[10px] font-bold text-slate-500 dark:text-neutral-400 hover:text-slate-700 dark:hover:text-slate-200 border border-slate-200 dark:border-neutral-700 px-2 py-1 rounded-lg transition-colors whitespace-nowrap">
              Open →
            </a>
          }
        />

        {/* 05 Context Pack */}
        <AgentRow
          icon={<Package className="w-3.5 h-3.5" />}
          iconColor="bg-emerald-500"
          num="05"
          title="Context Pack"
          desc={selectedNode?.label ? "Selection + 1-hop neighbors" : "Generates a handoff prompt for AI agents"}
          action={
            <SidebarRunBtn loading={packLoading} onClick={onRunPack} color="emerald">
              {selectedNode?.id ? "Generate selected" : "Generate"}
            </SidebarRunBtn>
          }
        >
          {selectedNode?.label && (
            <div className="mt-2 rounded-lg border border-emerald-100 bg-emerald-50 px-2 py-1.5 text-[10px] text-emerald-700 dark:border-emerald-900/50 dark:bg-emerald-900/20 dark:text-emerald-300">
              Seed: {selectedNode.label}
            </div>
          )}
          {packError && <SidebarError>{packError}</SidebarError>}
          {packResult && (
            <div className="mt-2">
              <div className="flex items-center justify-between mb-1.5">
                <p className="text-[10px] text-slate-400">{packResult.entity_count} entities</p>
                <button
                  onClick={onCopyPack}
                  className={`flex items-center gap-1 text-[10px] font-bold px-2 py-0.5 rounded-md transition-all ${packCopied ? "bg-emerald-100 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-400" : "bg-slate-100 dark:bg-black text-slate-500 hover:bg-slate-200 dark:hover:bg-slate-600"}`}
                >
                  {packCopied ? <Check className="w-2.5 h-2.5" /> : <Copy className="w-2.5 h-2.5" />}
                  {packCopied ? "Copied!" : "Copy"}
                </button>
              </div>
              <pre className="text-[10px] text-slate-600 dark:text-neutral-300 bg-slate-50 dark:bg-black border border-slate-200 dark:border-neutral-800 rounded-lg p-2.5 overflow-x-auto whitespace-pre-wrap leading-relaxed font-mono max-h-40 overflow-y-auto">
                {packResult.content}
              </pre>
            </div>
          )}
        </AgentRow>

      </div>
    </div>
  );
}

function AgentRow({ icon, iconColor, num, title, desc, action, children }) {
  return (
    <div className="rounded-xl border border-slate-200 dark:border-neutral-800 bg-white dark:bg-black p-3">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <div className={`w-5 h-5 rounded-md ${iconColor} flex items-center justify-center text-white shrink-0`}>
            {icon}
          </div>
          <div className="min-w-0">
            <div className="flex items-center gap-1.5">
              <span className="text-[9px] font-bold text-slate-400 uppercase tracking-wide">{num}</span>
              <span className="text-xs font-bold text-slate-800 dark:text-neutral-200">{title}</span>
            </div>
            <p className="text-[10px] text-slate-500 dark:text-neutral-400 leading-none mt-0.5 truncate">{desc}</p>
          </div>
        </div>
        <div className="shrink-0">{action}</div>
      </div>
      {children}
    </div>
  );
}

function SidebarRunBtn({ loading, onClick, color, children }) {
  const colors = {
    red:     "bg-red-500 hover:bg-red-600",
    violet:  "bg-violet-500 hover:bg-violet-600",
    emerald: "bg-emerald-500 hover:bg-emerald-600",
  };
  return (
    <button
      onClick={onClick}
      disabled={loading}
      className={`flex items-center gap-1 px-2.5 py-1 rounded-lg text-[10px] font-bold text-white transition-colors disabled:opacity-60 shrink-0 ${colors[color] || "bg-brand-600 hover:bg-brand-500"}`}
    >
      {loading ? <Loader2 className="w-2.5 h-2.5 animate-spin" /> : <Sparkles className="w-2.5 h-2.5" />}
      {loading ? "…" : children}
    </button>
  );
}

function SidebarError({ children }) {
  return (
    <div className="mt-2 flex items-start gap-1.5 p-2 rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-100 dark:border-red-800/40">
      <XCircle className="w-3 h-3 text-red-500 shrink-0 mt-0.5" />
      <p className="text-[10px] text-red-700 dark:text-red-400">{children}</p>
    </div>
  );
}

function GapSidebarResult({ report }) {
  const critical = report.gaps.filter(g => g.severity === "critical").length;
  const high     = report.gaps.filter(g => g.severity === "high").length;

  return (
    <div className="space-y-2">
      {/* Mini stats */}
      <div className="grid grid-cols-3 gap-1.5">
        {[
          { label: "Entities", value: report.stats.total_entities },
          { label: "Gaps",     value: report.gaps.length, alert: critical + high > 0 },
          { label: "Isolated", value: report.stats.isolated, alert: report.stats.isolated > 0 },
        ].map(s => (
          <div key={s.label} className="rounded-lg bg-slate-50 dark:bg-black border border-slate-100 dark:border-neutral-800/50 p-2 text-center">
            <p className={`text-base font-bold ${s.alert ? "text-red-600 dark:text-red-400" : "text-slate-900 dark:text-white"}`}>{s.value}</p>
            <p className="text-[9px] text-slate-400 uppercase tracking-wide">{s.label}</p>
          </div>
        ))}
      </div>

      {/* Summary */}
      {report.summary && (
        <div className="p-2.5 rounded-lg bg-amber-50 dark:bg-amber-900/10 border border-amber-100 dark:border-amber-800/30">
          <p className="text-[10px] text-amber-800 dark:text-amber-300 leading-relaxed">{report.summary}</p>
        </div>
      )}

      {/* Top gaps */}
      {report.gaps.slice(0, 4).map((g, i) => (
        <div key={i} className="flex items-start gap-1.5 p-2 rounded-lg bg-slate-50 dark:bg-black border border-slate-100 dark:border-neutral-800/50">
          <div className={`w-1.5 h-1.5 rounded-full shrink-0 mt-1.5 ${SEV_DOT[g.severity] || SEV_DOT.low}`} />
          <div className="min-w-0">
            <div className="flex items-center gap-1 flex-wrap">
              <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded-full ${SEV_PILL[g.severity] || SEV_PILL.low}`}>{g.severity}</span>
            </div>
            <p className="text-[10px] font-semibold text-slate-700 dark:text-neutral-300 mt-0.5 leading-snug">{g.title}</p>
            {g.recommendation && (
              <p className="text-[10px] text-brand-600 dark:text-brand-400 mt-0.5 flex items-center gap-0.5">
                <ChevronRight className="w-2.5 h-2.5 shrink-0" />{g.recommendation}
              </p>
            )}
          </div>
        </div>
      ))}
      {report.gaps.length > 4 && (
        <p className="text-[10px] text-slate-400 text-center">+{report.gaps.length - 4} more gaps</p>
      )}
    </div>
  );
}

/* ── Source Coverage Panel ────────────────────────────────────────── */

function SourceCoveragePanel({ components }) {
  const byFamily = {};
  components.forEach((c) => {
    const family = sourceFamily(c);
    if (!byFamily[family]) byFamily[family] = { count: 0, types: new Set() };
    byFamily[family].count++;
    byFamily[family].types.add(c.source_type || "unknown");
  });

  const families = [
    { key: "github", label: "GitHub", icon: GitPullRequest, color: "text-slate-700 dark:text-neutral-300", bg: "bg-slate-100 dark:bg-black" },
    { key: "agent", label: "AI Sessions", icon: Bot, color: "text-violet-700 dark:text-violet-300", bg: "bg-violet-100 dark:bg-violet-900/30" },
    { key: "communication", label: "Comms", icon: MessageCircle, color: "text-sky-700 dark:text-sky-300", bg: "bg-sky-100 dark:bg-sky-900/30" },
    { key: "local", label: "Local", icon: FileText, color: "text-slate-600 dark:text-neutral-300", bg: "bg-slate-100 dark:bg-black" },
    { key: "other", label: "Other", icon: Layers3, color: "text-teal-700 dark:text-teal-300", bg: "bg-teal-100 dark:bg-teal-900/30" },
  ];

  return (
    <div className="space-y-3">
      <p className="text-[10px] font-bold uppercase tracking-widest text-slate-400">By source family</p>
      <div className="space-y-1.5">
        {families.map(({ key, label, icon: Icon, color, bg }) => {
          const data = byFamily[key];
          return (
            <div key={key} className="flex items-center justify-between gap-2 p-2 rounded-lg bg-slate-50 dark:bg-black border border-slate-100 dark:border-neutral-800/50">
              <div className="flex items-center gap-2">
                <div className={`w-6 h-6 rounded-md ${bg} flex items-center justify-center`}>
                  <Icon className={`w-3.5 h-3.5 ${color}`} />
                </div>
                <span className="text-xs font-bold text-slate-700 dark:text-neutral-300">{label}</span>
              </div>
              <span className="text-xs font-bold text-slate-500">{data ? data.count : 0}</span>
            </div>
          );
        })}
      </div>
      {components.length > 0 && (
        <>
          <p className="text-[10px] font-bold uppercase tracking-widest text-slate-400 mt-3">By source type</p>
          <div className="space-y-1">
            {Object.entries(
              components.reduce((acc, c) => {
                const st = c.source_type || "unknown";
                acc[st] = (acc[st] || 0) + 1;
                return acc;
              }, {})
            )
              .sort((a, b) => b[1] - a[1])
              .slice(0, 8)
              .map(([type, count]) => (
                <div key={type} className="flex items-center justify-between text-xs">
                  <span className="text-slate-600 dark:text-neutral-400 capitalize">{type.replace(/_/g, " ")}</span>
                  <span className="font-bold text-slate-700 dark:text-neutral-300">{count}</span>
                </div>
              ))}
          </div>
        </>
      )}
    </div>
  );
}

/* ── Work Lens Panel ──────────────────────────────────────────────── */

function WorkLensPanel({ data, loading }) {
  if (loading) {
    return (
      <div className="flex items-center justify-center py-8">
        <Loader2 className="w-4 h-4 animate-spin text-slate-400" />
      </div>
    );
  }
  if (!data) {
    return <p className="text-xs text-slate-400 text-center py-4">Work lens unavailable.</p>;
  }

  const sections = [
    { key: "blockers", label: "Blockers", color: "red", icon: AlertTriangle },
    { key: "open_decisions", label: "Open Decisions", color: "amber", icon: ShieldCheck },
    { key: "active_tasks", label: "Active Tasks", color: "blue", icon: Zap },
    { key: "unresolved_questions", label: "Unresolved Questions", color: "sky", icon: MessageSquare },
    { key: "proposed_items", label: "Proposed", color: "violet", icon: Sparkles },
    { key: "stale_items", label: "Stale", color: "slate", icon: XCircle },
  ];

  return (
    <div className="space-y-3">
      {sections.map(({ key, label, color, icon: Icon }) => {
        const items = data[key] || [];
        const colorMap = {
          red: "bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400",
          amber: "bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400",
          blue: "bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400",
          sky: "bg-sky-100 dark:bg-sky-900/30 text-sky-700 dark:text-sky-400",
          violet: "bg-violet-100 dark:bg-violet-900/30 text-violet-700 dark:text-violet-400",
          slate: "bg-slate-100 dark:bg-black text-slate-600 dark:text-neutral-300",
        };
        return (
          <div key={key}>
            <div className="flex items-center justify-between mb-1.5">
              <div className="flex items-center gap-1.5">
                <Icon className="w-3 h-3 text-slate-400" />
                <span className="text-[10px] font-bold uppercase tracking-wider text-slate-500">{label}</span>
              </div>
              <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded-full ${colorMap[color]}`}>{items.length}</span>
            </div>
            {items.length > 0 ? (
              <div className="space-y-1">
                {items.slice(0, 4).map((item) => (
                  <div key={item.id} className="p-2 rounded-lg bg-slate-50 dark:bg-black border border-slate-100 dark:border-neutral-800/50">
                    <p className="text-[11px] font-semibold text-slate-700 dark:text-neutral-300 truncate">{item.name || item.display_title}</p>
                    <div className="flex items-center gap-1.5 mt-0.5">
                      {item.model_name && <span className="text-[9px] text-slate-400">{item.model_name}</span>}
                      {item.confidence != null && (
                        <span className={`text-[9px] font-bold ${item.confidence < 0.5 ? "text-red-500" : "text-slate-400"}`}>
                          {Math.round(item.confidence * 100)}%
                        </span>
                      )}
                    </div>
                  </div>
                ))}
                {items.length > 4 && (
                  <p className="text-[10px] text-slate-400 text-center">+{items.length - 4} more</p>
                )}
              </div>
            ) : (
              <p className="text-[10px] text-slate-400 italic">None</p>
            )}
          </div>
        );
      })}
    </div>
  );
}
