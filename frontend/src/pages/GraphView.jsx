import { useEffect, useRef, useState, useCallback } from "react";
import cytoscape from "cytoscape";
import {
  Zap, Network, AlertTriangle, MessageSquare, Package,
  Sparkles, Loader2, XCircle, Copy, Check, Search,
  ChevronRight, X as XIcon, Bot, Link2, Plus, Minus, Maximize2,
  GitPullRequest, MessageCircle, FileText, Layers3, ShieldCheck,
  SlidersHorizontal,
} from "lucide-react";
import { useTheme } from "../context/ThemeContext";
import imgGmail from "@assets/gmail-icon.png";

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
<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" fill="#181717">
  <path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0024 12c0-6.63-5.37-12-12-12z"/>
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
  low:      "bg-slate-100 dark:bg-slate-700 text-slate-500",
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
  past:    { label: "Past", pill: "bg-slate-100 dark:bg-slate-700 text-slate-500" },
  unknown: { label: "Unknown", pill: "bg-slate-100 dark:bg-slate-700 text-slate-400" },
};

// Edge origin → visual style
const EDGE_ORIGIN_STYLE = {
  deterministic: { lineStyle: "solid", width: 2, opacity: 0.76, label: "Deterministic", color: "#3b82f6" },
  extracted:     { lineStyle: "solid", width: 1.6, opacity: 0.56, label: "Extracted", color: "#8b5cf6" },
  proposed:      { lineStyle: "dotted", width: 1.4, opacity: 0.40, label: "Proposed", color: "#94a3b8" },
  ai_proposed:   { lineStyle: "dashed", width: 1.5, opacity: 0.44, label: "AI Proposed", color: "#f59e0b" },
  human_verified:{ lineStyle: "solid", width: 2.4, opacity: 0.88, label: "Human Verified", color: "#059669" },
};

const LOD_MACRO_ZOOM = 0.5;
const LOD_CARD_ZOOM = 0.85;
const LOD_NODE_CLASSES = "lod-macro lod-compact lod-card";
const LOD_EDGE_CLASSES = "lod-macro-edge lod-detail-edge";

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
  github: { label: "GitHub", icon: GitPullRequest, color: "#24292e", bg: "bg-slate-100 dark:bg-slate-700", text: "text-slate-700 dark:text-slate-200" },
  agent: { label: "AI Session", icon: Bot, color: "#7c3aed", bg: "bg-violet-100 dark:bg-violet-900/30", text: "text-violet-700 dark:text-violet-300" },
  communication: { label: "Comms", icon: MessageCircle, color: "#0ea5e9", bg: "bg-sky-100 dark:bg-sky-900/30", text: "text-sky-700 dark:text-sky-300" },
  local: { label: "Local", icon: FileText, color: "#64748b", bg: "bg-slate-100 dark:bg-slate-700", text: "text-slate-600 dark:text-slate-300" },
  other: { label: "Source", icon: Layers3, color: "#14b8a6", bg: "bg-teal-100 dark:bg-teal-900/30", text: "text-teal-700 dark:text-teal-300" },
};

const SOURCE_VISUALS = {
  github: { icon: "GH", label: "GitHub", bg: "rgba(100,116,139,0.18)", border: "#64748b", color: "#e2e8f0", logo: GITHUB_LOGO_URI },
  gmail: { icon: "GM", label: "Gmail", bg: "rgba(14,165,233,0.18)", border: "#38bdf8", color: "#e0f2fe", logo: imgGmail },
  slack: { icon: "SL", label: "Slack", bg: "rgba(20,184,166,0.18)", border: "#2dd4bf", color: "#ccfbf1", logo: SLACK_LOGO_URI },
  agent: { icon: "AI", label: "AI Session", bg: "rgba(124,58,237,0.18)", border: "#8b5cf6", color: "#ede9fe", logo: AI_LOGO_URI },
  local: { icon: "DOC", label: "Document", bg: "rgba(148,163,184,0.16)", border: "#94a3b8", color: "#e2e8f0", logo: "" },
  other: { icon: "SRC", label: "Source", bg: "rgba(20,184,166,0.14)", border: "#14b8a6", color: "#ccfbf1", logo: "" },
};

const GRAPH_GROUP_META = {
  decisions: { label: "Decisions", color: "#f59e0b" },
  work: { label: "Active Work", color: "#2563eb" },
  risks: { label: "Risks & Blockers", color: "#ef4444" },
  github: { label: "GitHub Delivery", color: "#334155" },
  gmail: { label: "Gmail Inbox", color: "#38bdf8" },
  slack: { label: "Slack Messages", color: "#2dd4bf" },
  localDocs: { label: "Documents", color: "#94a3b8" },
  agents: { label: "AI Sessions", color: "#7c3aed" },
  sources: { label: "Sources", color: "#14b8a6" },
  product: { label: "Product", color: "#22c55e" },
  repo: { label: "Repository", color: "#64748b" },
  other: { label: "Other Context", color: "#94a3b8" },
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

function sourceFamilyLabel(component = {}) {
  return SOURCE_FAMILY_META[sourceFamily(component)]?.label || "Source";
}

function componentVisuals(component = {}, isGap = false) {
  if (isGap) {
    return {
      bg: "rgba(239,68,68,0.10)",
      border: "#ef4444",
      stripe: "#ef4444",
    };
  }

  const family = sourceFamily(component);
  const status = String(component.status || "").toLowerCase();
  const palette = {
    github: { bg: "rgba(100,116,139,0.14)", border: "#64748b", stripe: "#94a3b8" },
    agent: { bg: "rgba(124,58,237,0.14)", border: "#8b5cf6", stripe: "#a78bfa" },
    communication: { bg: "rgba(14,165,233,0.14)", border: "#38bdf8", stripe: "#38bdf8" },
    local: { bg: "rgba(20,184,166,0.13)", border: "#2dd4bf", stripe: "#2dd4bf" },
    other: { bg: "rgba(148,163,184,0.12)", border: "#94a3b8", stripe: "#94a3b8" },
  }[family] || { bg: "rgba(148,163,184,0.12)", border: "#94a3b8", stripe: "#94a3b8" };

  if (status === "needs_review" || status === "proposed" || status === "draft") {
    return { ...palette, border: "#f59e0b" };
  }
  if (status === "blocked" || status === "stale" || status === "deprecated") {
    return { ...palette, border: "#ef4444" };
  }
  return palette;
}

function readableViewport(cy, viewMode) {
  const padding = viewMode === "repo" ? 72 : 36;
  cy.fit(undefined, padding);
}

function graphLod(zoom) {
  if (zoom <= LOD_MACRO_ZOOM) return "lod-macro";
  if (zoom < LOD_CARD_ZOOM) return "lod-compact";
  return "lod-card";
}

function applyGraphLod(cy) {
  const lod = graphLod(cy.zoom());
  cy.batch(() => {
    cy.nodes("[type='component'], .source-hub, .model-node").removeClass(LOD_NODE_CLASSES).addClass(lod);
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

// ── CEO View presets ──────────────────────────────────────────────
const CEO_VIEWS = [
  { id: "all",        label: "All",            desc: "Full graph — every entity and relationship" },
  { id: "birdsEye",   label: "Bird's Eye",     desc: "Company → Product → Feature → Task → PR → Customer" },
  { id: "gaps",       label: "Gap Detector",   desc: "Highlights nodes with no connections — missing owners, orphaned tasks, unlinked decisions" },
  { id: "decisions",  label: "Decision Trail", desc: "Message → Meeting → Decision → PR → Feature" },
  { id: "aiSessions", label: "AI Sessions",    desc: "Agent sessions → decisions, files changed, bugs found, next steps" },
  { id: "workLens",   label: "Work Lens",      desc: "Blockers, open decisions, active tasks, unresolved questions" },
  { id: "github",     label: "GitHub Delivery", desc: "Issue → PR → files → decisions/tasks" },
  { id: "repo",       label: "Repository",      desc: "Repos, files, changed modules" },
];

const CEO_VIEW_MODEL_PATTERNS = {
  birdsEye:   /^(company|product|feature|task|customer|user|pr|issue|repo|metric)/i,
  decisions:  /^(decision|meeting|message|email|document|slack|zoom|discussion)/i,
  aiSessions: /^(agent session|agent|claude|codex|opencode|chatgpt|ai session)/i,
  workLens:   /^(risk|task|decision|agent session|issue|pr|repo)/i,
  github:     /^(issue|pr|repo|github)/i,
  repo:       /^(repo|github)/i,
};

const CEO_VIEW_FACT_TYPE_PATTERNS = {
  workLens:   /^(blocker|task|decision|risk|open_question|issue|pr|pr_review_finding|github_issue|github_pr|changed_file|session_root|ai_task|ai_decision|ai_blocker)$/,
  github:     /^(github_issue|github_pr|pr_review_finding|issue|pr|changed_file|commit_reference)$/,
};

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
  const { theme } = useTheme();
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
  const [ceoView, setCeoView] = useState("workLens");
  const [graphZoom, setGraphZoom] = useState(100);
  const [showFilters, setShowFilters] = useState(false);

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

  async function callAgent(endpoint, setLoading, setResult, setError) {
    setLoading(true); setResult(null); setError(null);
    const s = getAiSettingsSaved();
    try {
      const res = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ api_key: s.api_key || null, model: s.model || null }),
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
    cy.resize();
    cy.fit(undefined, 36);
    setGraphZoom(Math.round(cy.zoom() * 100));
  }, []);

  const changeGraphZoom = useCallback((delta) => {
    const cy = cyRef.current;
    if (!cy) return;
    const nextZoom = Math.max(cy.minZoom(), Math.min(cy.maxZoom(), cy.zoom() + delta));
    cy.zoom({ level: nextZoom, renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 } });
    setGraphZoom(Math.round(cy.zoom() * 100));
  }, []);

  useEffect(() => {
    async function fetchGraph() {
      try {
        setLoading(true);
        setError(null);
        setSelectedNode(null);
        const res = await fetch(viewMode === "repo" ? "/api/repo/graph" : "/api/graph");
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
  }, [viewMode]);

  useEffect(() => {
    fetch("/api/graph/agent-status")
      .then((r) => r.json())
      .then(setAgentStatus)
      .catch(() => {});
  }, []);

  useEffect(() => {
    async function fetchWorkLens() {
      setWorkLensLoading(true);
      try {
        const res = await fetch("/api/work-lens");
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
  }, []);

  async function handleBuildGraph() {
    setBuilding(true);
    setBuildResult(null);
    const saved = (() => { try { return JSON.parse(localStorage.getItem("ce_ai_settings") || "{}"); } catch { return {}; } })();
    try {
      const body = { limit: 100 };
      if (saved.api_key) body.api_key = saved.api_key;
      if (saved.model) body.model = saved.model;
      const res = await fetch("/api/graph/build", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const data = await res.json();
      setBuildResult(data);
      const graphRes = await fetch("/api/graph");
      if (graphRes.ok) setGraphData(await graphRes.json());
      fetch("/api/graph/agent-status").then((r) => r.json()).then(setAgentStatus).catch(() => {});
    } catch (e) {
      setBuildResult({ error: e.message });
    } finally {
      setBuilding(false);
    }
  }

  async function handleAsk(e) {
    e?.preventDefault();
    const q = askQuery.trim();
    if (!q) return;
    setAskLoading(true);
    setAskError(null);
    setAskResult(null);
    const saved = (() => { try { return JSON.parse(localStorage.getItem("ce_ai_settings") || "{}"); } catch { return {}; } })();
    try {
      const body = { question: q };
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

  const filteredData = useCallback(() => {
    if (!graphData) return { models: [], components: [], relationships: [] };
    if (viewMode === "repo") return graphData;

    const allModels = graphData.models || [];
    let components = graphData.components || [];
    let relationships = graphData.relationships || [];

    // CEO view: filter to relevant model types (except "gaps" shows everything)
    const ceoPattern = CEO_VIEW_MODEL_PATTERNS[ceoView];
    if (ceoPattern) {
      const modelNameById = new Map(allModels.map((m) => [m.id, m.name]));
      components = components.filter((c) => ceoPattern.test(modelNameById.get(c.model_id) || ""));
    }
    const factPattern = CEO_VIEW_FACT_TYPE_PATTERNS[ceoView];
    if (factPattern) {
      components = components.filter((c) => factPattern.test(String(c.fact_type || "").toLowerCase()));
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

    if (filters.relationship_origin) {
      relationships = relationships.filter((r) => (r.origin || "proposed") === filters.relationship_origin);
    }

    if (filters.search && filters.search.trim()) {
      const q = filters.search.trim().toLowerCase();
      components = components.filter((c) => {
        const haystack = [
          c.name,
          c.value,
          c.fact_type,
          c.source_type,
          c.provenance,
          c.excerpt,
          JSON.stringify(c.source_metadata_summary),
        ].filter(Boolean).join(" ").toLowerCase();
        return haystack.includes(q);
      });
      const searchedComponentIds = new Set(components.map((c) => c.id));
      relationships = relationships.filter(
        (r) => searchedComponentIds.has(r.source_component_id) && searchedComponentIds.has(r.target_component_id)
      );
    }

    return { models: allModels, components, relationships };
  }, [graphData, filters, viewMode, ceoView]);

  useEffect(() => {
    if (!containerRef.current || !graphData) return;

    const viewData = filteredData();
    const { models = [], components = [], relationships = [] } = viewData;

    const nodes = [];
    const edges = [];

    const modelNameById = new Map(models.map((m) => [m.id, m.name]));
    const visibleGroups = new Map();
    const groupSourceSummaries = new Map();
    components.forEach((component) => {
      const groupKey = graphGroup(component, modelNameById.get(component.model_id));
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
      // Strategy groups become compound parent containers. They are backed by source,
      // model, fact type, or relationship metadata; no synthetic facts are invented.
      visibleGroups.forEach((meta, groupKey) => {
        nodes.push({
          data: {
            id: `group:${groupKey}`,
            label: meta.label,
            fullLabel: meta.label,
            type: "model",
            modelId: groupKey,
            description: "",
            modelColor: meta.color || "#6366f1",
          },
          classes: "model-node",
        });
      });

      groupSourceSummaries.forEach((summary, groupKey) => {
        Array.from(summary.values()).forEach((item) => {
          nodes.push({
            data: {
              id: `source:${groupKey}:${item.kind}`,
              parent: `group:${groupKey}`,
            label: `${item.label}\n${item.count} components`,
            compactLabel: `${item.label} (${item.count})`,
            cardLabel: `${item.label}\n${item.count} components`,
            fullLabel: `${item.label} source summary`,
            type: "sourceHub",
              sourceKind: item.kind,
              bgColor: item.bg,
              borderColor: item.border,
              textColor: item.color,
              logo: item.logo,
              count: item.count,
            },
            classes: "source-hub",
          });
        });
      });

      // Components are children of their strategy group compound node
      const connectedComponentIds = new Set();
      relationships.forEach((r) => {
        connectedComponentIds.add(r.source_component_id);
        connectedComponentIds.add(r.target_component_id);
      });

      components.forEach((c) => {
        const temporal = c.temporal || "unknown";
        const isGap = ceoView === "gaps" && !connectedComponentIds.has(c.id);
        const visuals = componentVisuals(c, isGap);
        const source = sourceVisual(c);

        const mName = modelNameById.get(c.model_id) || "";
        const groupKey = graphGroup(c, mName);
        const cleanName = stripModelPrefix(c.name);

        // Three-line card label: source badge, entity, then model/link metadata.
        const domain = (c.fact_type || domainLabel(mName) || "Fact").replace(/_/g, " ");
        const timeBadge = TEMPORAL_BADGE[temporal] || "";
        const confidenceBadge = c.confidence != null ? `${Math.round(c.confidence * 100)}%` : "";
        const relationshipCount = c.relationship_count ?? 0;
        const linkBadge = relationshipCount > 0 ? `${relationshipCount} linked` : "isolated";
        const chipLine = [source.label, domain].filter(Boolean).join("  /  ");
        const evidenceLine = [linkBadge, timeBadge, confidenceBadge].filter(Boolean).join("  /  ");
        const displayName = shortLabel(cleanName, 7);

        nodes.push({
          data: {
            id: c.id,
            parent: `group:${groupKey}`,
            label: `${source.icon}  ${displayName}\n${chipLine}\n${evidenceLine}`,
            compactLabel: displayName,
            cardLabel: `${source.icon}  ${displayName}\n${chipLine}\n${evidenceLine}`,
            fullLabel: c.name,
            type: "component",
            value: c.value,
            confidence: c.confidence,
            status: c.status,
            fact_type: c.fact_type,
            temporal,
            modelId: c.model_id,
            source_type: c.source_type,
            source_url: c.source_url,
            source_external_id: c.source_external_id,
            source_metadata_summary: c.source_metadata_summary,
            source_family: sourceFamily(c),
            source_kind: sourceKind(c),
            relationship_count: c.relationship_count,
            provenance: c.provenance,
            excerpt: c.excerpt,
            bgColor: visuals.bg,
            borderColor: visuals.border,
            stripeColor: visuals.stripe,
            badgeColor: source.border,
            logo: source.logo,
          },
          classes: [isGap ? "gap-node" : "", relationshipCount === 0 ? "isolated-node" : "linked-node"].filter(Boolean).join(" "),
        });
      });

      // Relationship edges only — compound parent handles "contains" visually
      relationships.forEach((r) => {
        const origin = r.origin || "proposed";
        const style = EDGE_ORIGIN_STYLE[origin] || EDGE_ORIGIN_STYLE.extracted;
        const hideLowConfidence = filters.confidence_threshold > 0 && (r.confidence ?? 0) < filters.confidence_threshold;
        if (hideLowConfidence) return;

        edges.push({
          data: {
            id: r.id,
            source: r.source_component_id,
            target: r.target_component_id,
            label: (r.relationship_type || "related_to").replaceAll("_", " "),
            displayLabel: r.display_label || (r.relationship_type || "related_to").replaceAll("_", " "),
            shortLabel: (r.relationship_type || "related_to").replaceAll("_", " "),
            edgeType: "relationship",
            origin,
            confidence: r.confidence,
            evidence: r.evidence,
            status: r.status,
            lineStyle: style.lineStyle,
            edgeWidth: style.width,
            edgeOpacity: style.opacity,
            edgeColor: style.color,
            sourceName: r.source_component_name,
            targetName: r.target_component_name,
          },
        });
      });
    }

    const isDark = theme === "dark" || document.documentElement.classList.contains("dark");
    const modelBg = isDark ? "#101827" : "#f8fafc";
    const modelBgOpacity = isDark ? 1 : 0.95;
    const modelLabelBg = isDark ? "#0f172a" : "#ffffff";
    const modelTextColor = isDark ? "#f8fafc" : "#0f172a";
    const componentTextColor = isDark ? "#f8fafc" : "#1e293b";
    const labelOutlineColor = isDark ? "#0f172a" : "#ffffff";
    const edgeLabelBg = isDark ? "#1e293b" : "#ffffff";
    const repoFileBg = isDark ? "#263244" : "#f1f5f9";
    const repoFileBorder = isDark ? "#64748b" : "#cbd5e1";
    const repoTextColor = isDark ? "#e5edf8" : "#1e293b";
    const repoLabelOutline = isDark ? "#0f172a" : "#ffffff";
    const cardWidth = 270;
    const cardHeight = 106;

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
            "text-max-width": "238px",
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
          },
        },
        {
          selector: ".model-node",
          style: {
            "background-color": isDark ? "#0c1526" : "#f8fafc",
            "background-opacity": modelBgOpacity,
            "border-color": "data(modelColor)",
            "border-width": 2,
            "border-opacity": 0.7,
            shape: "round-rectangle",
            "corner-radius": "16px",
            padding: "58px",
            label: "data(label)",
            "text-valign": "top",
            "text-halign": "left",
            "text-margin-y": -28,
            "text-margin-x": 12,
            "text-max-width": 320,
            "font-size": "13px",
            "font-weight": "bold",
            "text-wrap": "wrap",
            color: modelTextColor,
            "text-outline-color": labelOutlineColor,
            "text-outline-width": 0,
            "text-background-color": modelLabelBg,
            "text-background-opacity": 1,
            "text-background-padding": "5px",
            "text-background-shape": "round-rectangle",
            "text-border-opacity": 0,
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
            "font-size": "34px",
            "text-outline-width": 3,
            "text-background-opacity": 0,
            "text-margin-y": -42,
            padding: "36px",
          },
        },
        {
          selector: ".model-node.lod-compact",
          style: {
            "background-opacity": isDark ? 0.6 : 0.35,
            "border-opacity": 0.55,
            "font-size": "22px",
            "text-outline-width": 2,
            "text-margin-y": -34,
            padding: "44px",
          },
        },

        // ── COMPONENT — uniform card nodes ───────────────────────
        {
          selector: "node[type='component']",
          style: {
            "background-color": "data(bgColor)",
            "background-opacity": 0.95,
            "border-color": "data(borderColor)",
            "border-width": 2,
            width: cardWidth,
            height: cardHeight,
            shape: "round-rectangle",
            "corner-radius": "10px",
            label: "data(label)",
            "text-valign": "center",
            "text-halign": "center",
            "text-margin-x": 12,
            "font-size": "10.5px",
            "font-weight": "bold",
            "text-wrap": "wrap",
            "text-max-width": "238px",
            color: componentTextColor,
            "text-outline-color": labelOutlineColor,
            "text-outline-width": 1,
            "transition-property": "width height background-color border-width opacity font-size",
            "transition-duration": "180ms",
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
            width: 150,
            height: 42,
            shape: "round-rectangle",
            "corner-radius": "9px",
            label: "data(compactLabel)",
            "font-size": "9px",
            "font-weight": "bold",
            "text-max-width": "132px",
            "text-wrap": "wrap",
            "background-color": "data(bgColor)",
            "background-opacity": 0.98,
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
            label: "data(cardLabel)",
            "font-size": "10.5px",
            "text-max-width": "238px",
          },
        },
        {
          selector: ".source-hub",
          style: {
            "background-color": "data(bgColor)",
            "background-opacity": 1,
            "border-color": "data(borderColor)",
            "border-width": 2,
            width: 144,
            height: 104,
            shape: "round-rectangle",
            "corner-radius": "12px",
            label: "data(label)",
            "text-valign": "bottom",
            "text-halign": "center",
            "text-margin-y": -10,
            "font-size": "10px",
            "font-weight": "bold",
            "text-wrap": "wrap",
            "text-max-width": "104px",
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
            width: 144,
            height: 104,
            label: "data(cardLabel)",
            "font-size": "10px",
            "text-max-width": "104px",
            "text-valign": "bottom",
            "text-margin-y": -10,
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
            "border-color": isDark ? "#64748b" : "#0f172a",
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
            width: 1.5,
            "line-color": isDark ? "#334155" : "#cbd5e1",
            "target-arrow-color": isDark ? "#334155" : "#cbd5e1",
            "target-arrow-shape": "triangle",
            "arrow-scale": 0.8,
            "curve-style": "bezier",
            label: "",
            opacity: 0.5,
          },
        },

        // ── RELATIONSHIP EDGES — indigo tint ──────────────────────
        {
          selector: "edge[edgeType='relationship']",
          style: {
            width: "data(edgeWidth)",
            "line-color": "data(edgeColor)",
            "target-arrow-color": "data(edgeColor)",
            "target-arrow-shape": "triangle",
            "arrow-scale": 1.1,
            "curve-style": "bezier",
            label: "data(shortLabel)",
            opacity: "data(edgeOpacity)",
            "font-size": "9px",
            "font-weight": "bold",
            color: isDark ? "#c7d2fe" : "#3730a3",
            "text-rotation": "autorotate",
            "text-background-opacity": 1,
            "text-background-color": edgeLabelBg,
            "text-background-padding": "4px",
            "text-border-opacity": 0,
            "text-margin-y": -8,
            "transition-property": "width opacity line-color target-arrow-color",
            "transition-duration": "180ms",
          },
        },
        {
          selector: "edge[edgeType='relationship'].lod-macro-edge",
          style: {
            label: "",
            width: 1,
            opacity: 0.34,
            "arrow-scale": 0.72,
          },
        },
        {
          selector: "edge[edgeType='relationship'].lod-detail-edge",
          style: {
            label: "data(shortLabel)",
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
            width: 2.5,
            "line-color": isDark ? "#818cf8" : "#6366f1",
            "target-arrow-color": isDark ? "#818cf8" : "#6366f1",
          },
        },
      ],
      layout: viewMode === "repo"
        ? { name: "preset", fit: true, padding: 110 }
        : (() => {
          const presetPositions = {};
          const groups = Array.from(visibleGroups.entries())
            .map(([groupKey, meta]) => ({
              groupKey,
              meta,
              items: components.filter((c) => graphGroup(c, modelNameById.get(c.model_id)) === groupKey),
              hubs: Array.from(groupSourceSummaries.get(groupKey)?.values() || []),
            }))
            .sort((a, b) => b.items.length - a.items.length);

          const colCount = Math.min(3, Math.max(1, groups.length));
          const colWidth = 1220;
          const cardW = 306;
          const cardH = 128;
          const gapX = 36;
          const gapY = 34;
          const groupPadX = 132;
          const sourceHubW = 152;
          const sourceHubGap = 22;
          const groupPadTop = 190;
          const groupGapY = 120;
          const colHeights = Array.from({ length: colCount }, () => 0);

          groups.forEach(({ groupKey, items, hubs }) => {
            const col = colHeights.indexOf(Math.min(...colHeights));
            const itemCount = Math.max(1, items.length);
            const gridCols = itemCount >= 40 ? 4 : itemCount >= 20 ? 3 : itemCount >= 8 ? 2 : 1;
            const rows = Math.ceil(itemCount / gridCols);
            const groupWidth = groupPadX * 2 + gridCols * cardW + (gridCols - 1) * gapX;
            const groupHeight = groupPadTop + rows * cardH + Math.max(0, rows - 1) * gapY + 80;
            const baseX = col * colWidth - ((colCount - 1) * colWidth) / 2;
            const baseY = colHeights[col];
            const startX = baseX - groupWidth / 2 + groupPadX + cardW / 2;
            const startY = baseY + groupPadTop;
            const hubTotalWidth = hubs.length * sourceHubW + Math.max(0, hubs.length - 1) * sourceHubGap;
            const hubStartX = baseX - hubTotalWidth / 2 + sourceHubW / 2;

            hubs.forEach((hub, index) => {
              presetPositions[`source:${groupKey}:${hub.kind}`] = {
                x: hubStartX + index * (sourceHubW + sourceHubGap),
                y: baseY + 88,
              };
            });

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
            colHeights[col] += groupHeight + groupGapY;
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

    cy.minZoom(viewMode === "repo" ? 0.35 : 0.28);
    cy.maxZoom(2.8);
    readableViewport(cy, viewMode);
    applyGraphLod(cy);
    setGraphZoom(Math.round(cy.zoom() * 100));
    cy.on("zoom", () => {
      applyGraphLod(cy);
      setGraphZoom(Math.round(cy.zoom() * 100));
    });

    const resizeObserver = new ResizeObserver(() => {
      cy.resize();
      readableViewport(cy, viewMode);
      setGraphZoom(Math.round(cy.zoom() * 100));
    });
    resizeObserver.observe(containerRef.current);

    let logoRafId = null;
    const logoTimeoutIds = [];
    const graphIsDestroyed = () => typeof cy.destroyed === "function" && cy.destroyed();
    const updateLogoOverlays = () => {
      const layer = logoLayerRef.current;
      if (!layer || !containerRef.current || graphIsDestroyed()) {
        return;
      }
      if (viewMode !== "repo" && cy.zoom() < LOD_CARD_ZOOM) {
        layer.replaceChildren();
        return;
      }
      const fragment = document.createDocumentFragment();
      cy.nodes().forEach((node) => {
        try {
          const logo = node.data("logo");
          const type = node.data("type");
          if (!logo || !["component", "sourceHub"].includes(type)) return;

          const bounds = node.renderedBoundingBox({
            includeEdges: false,
            includeLabels: false,
            includeNodes: true,
          });
          const isSourceHub = type === "sourceHub";
          const size = isSourceHub ? 34 : 24;
          const left = isSourceHub
            ? bounds.x1 + bounds.w / 2
            : bounds.x1 + bounds.w * (26 / cardWidth);
          const top = isSourceHub
            ? bounds.y1 + bounds.h * ((104 / 2 - 18) / 104)
            : bounds.y1 + bounds.h * (24 / cardHeight);
          const img = document.createElement("img");
          img.src = logo;
          img.alt = "";
          img.title = node.data("fullLabel") || node.data("label") || "";
          img.dataset.graphLogo = node.id();
          img.className = isSourceHub
            ? "absolute rounded-md bg-white/95 p-1 object-contain shadow-sm dark:bg-slate-950/90"
            : "absolute rounded bg-white/95 p-0.5 object-contain shadow-sm dark:bg-slate-950/90";
          Object.assign(img.style, {
            width: `${size}px`,
            height: `${size}px`,
            left: `${left}px`,
            top: `${top}px`,
            transform: "translate(-50%, -50%)",
          });
          fragment.appendChild(img);
        } catch (_) {}
      });
      layer.replaceChildren(fragment);
    };
    const scheduleLogoOverlayUpdate = () => {
      if (logoRafId) return;
      logoRafId = requestAnimationFrame(() => {
        logoRafId = null;
        updateLogoOverlays();
      });
    };
    updateLogoOverlays();
    logoTimeoutIds.push(setTimeout(updateLogoOverlays, 50));
    logoTimeoutIds.push(setTimeout(updateLogoOverlays, 250));
    cy.on("render zoom pan position", scheduleLogoOverlayUpdate);

    cy.on("tap", "node", (evt) => {
      const data = evt.target.data();
      if (data.type === "component") {
        const connectedEdges = cy.edges(`[source = "${data.id}"], [target = "${data.id}"]`);
        const connected = [];
        connectedEdges.forEach((e) => {
          const src = e.data("source");
          const tgt = e.data("target");
          const otherId = src === data.id ? tgt : src;
          const otherNode = cy.getElementById(otherId);
          if (otherNode.length) {
            connected.push({
              id: otherId,
              label: otherNode.data("fullLabel") || otherNode.data("label"),
              edgeLabel: e.data("label"),
              relationshipType: e.data("label"),
              origin: e.data("origin"),
              confidence: e.data("confidence"),
              direction: src === data.id ? "out" : "in",
            });
          }
        });
        setSelectedNode({ ...data, connected });
        setSelectedEdge(null);
        setEdgeReviewError(null);
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
      setShowSidePanel(false);
      setShowAgents(false);
    });

    cy.on("tap", (evt) => {
      if (evt.target === cy) {
        setSelectedNode(null);
        setSelectedEdge(null);
      }
    });

    // Edge labels — reveal on hover, hide when mouse leaves
    cy.on("mouseover", "edge[edgeType='relationship']", (evt) => {
      evt.target.style({ label: evt.target.data("label"), opacity: 1 });
    });
    cy.on("mouseout", "edge[edgeType='relationship']", (evt) => {
      if (!evt.target.selected()) {
        evt.target.style({ label: evt.target.data("shortLabel"), opacity: evt.target.data("edgeOpacity") ?? 0.6 });
      }
    });
    cy.on("select", "edge[edgeType='relationship']", (evt) => {
      evt.target.style({ label: evt.target.data("label"), opacity: 1 });
    });
    cy.on("unselect", "edge[edgeType='relationship']", (evt) => {
      evt.target.style({ label: evt.target.data("shortLabel"), opacity: evt.target.data("edgeOpacity") ?? 0.6 });
    });

    // Hover effect on card nodes — subtle lift
    cy.on("mouseover", "node[type='component']", (evt) => {
      evt.target.style({ "border-width": 2.5, opacity: 1 });
    });
    cy.on("mouseout", "node[type='component']", (evt) => {
      if (!evt.target.selected()) {
        evt.target.style({ "border-width": 2, opacity: 1 });
      }
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
      logoTimeoutIds.forEach((timeoutId) => clearTimeout(timeoutId));
      if (logoRafId) cancelAnimationFrame(logoRafId);
      logoLayerRef.current?.replaceChildren();
      resizeObserver.disconnect();
      cy.destroy();
    };
  }, [graphData, filteredData, viewMode, ceoView, theme]);

  const models = graphData?.models || [];
  const allComponents = graphData?.components || [];
  const sourceTypes = [...new Set(allComponents.map((c) => c.source_type).filter(Boolean))];
  const statuses = [...new Set(allComponents.map((c) => c.status).filter(Boolean))];
  const currentViewData = filteredData();
  const graphStats = buildGraphStats(currentViewData);
  const activeCeoView = CEO_VIEWS.find((v) => v.id === ceoView);
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
  const extractionLabel = aiSettings.api_key && aiSettings.model
    ? `AI: ${aiSettings.model}`
    : agentStatus?.llm_enabled
      ? `LLM: ${agentStatus.extraction_model}`
      : "Regex extraction";

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-center">
          <div className="h-8 w-8 animate-spin rounded-full border-4 border-brand-200 border-t-brand-600 mx-auto mb-3" />
          <p className="text-sm font-bold text-slate-800 dark:text-slate-200">Loading graph...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-center p-6 bg-white dark:bg-slate-800 rounded-2xl border border-slate-200 dark:border-slate-700">
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
          <div className="pointer-events-auto max-w-full rounded-xl border border-slate-200 bg-white/92 p-2 shadow-sm backdrop-blur-sm dark:border-slate-700 dark:bg-slate-800/92 lg:max-w-[34rem]">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-sm font-black text-slate-900 dark:text-white">Knowledge Graph</h2>
              <div className="flex rounded-lg border border-slate-200 bg-slate-50 p-0.5 dark:border-slate-700 dark:bg-slate-900/70">
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
                        : "text-slate-500 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white"
                    }`}
                  >
                    {label}
                  </button>
                ))}
              </div>
              {viewMode === "knowledge" && (
                <div className="flex items-center gap-1.5 rounded-lg bg-slate-100 px-2 py-1 text-[10px] font-bold text-slate-500 dark:bg-slate-900/70 dark:text-slate-400">
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
            {viewMode === "knowledge" && (
              <div className="mt-2 flex min-w-0 items-center gap-2">
                <span className="shrink-0 text-[10px] font-bold uppercase text-slate-400">View</span>
                <select
                  value={ceoView}
                  onChange={(e) => setCeoView(e.target.value)}
                  className="min-w-0 flex-1 rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-xs font-bold text-slate-700 outline-none transition focus:border-brand-400 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200"
                >
                  {CEO_VIEWS.map(({ id, label }) => (
                    <option key={id} value={id}>{label}</option>
                  ))}
                </select>
                {activeCeoView && ceoView !== "all" && (
                  <span className="hidden truncate text-[10px] text-slate-400 xl:block">{activeCeoView.desc}</span>
                )}
              </div>
            )}
          </div>

          <div className="pointer-events-auto flex flex-wrap items-center justify-end gap-2">
            {viewMode === "knowledge" && (
              <div className="relative">
                <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-400" />
                <input
                  type="text"
                  value={filters.search}
                  onChange={(e) => setFilters((f) => ({ ...f, search: e.target.value }))}
                  placeholder="Search graph..."
                  className="h-9 w-40 rounded-xl border border-slate-200 bg-white/92 pl-8 pr-7 text-xs font-semibold text-slate-700 shadow-sm outline-none backdrop-blur-sm transition placeholder:text-slate-400 focus:border-brand-400 dark:border-slate-700 dark:bg-slate-800/92 dark:text-slate-200 sm:w-52 xl:w-60"
                />
                {filters.search && (
                  <button
                    type="button"
                    onClick={() => setFilters((f) => ({ ...f, search: "" }))}
                    className="absolute right-2 top-1/2 flex h-5 w-5 -translate-y-1/2 items-center justify-center rounded-md text-slate-400 hover:bg-slate-100 hover:text-slate-600 dark:hover:bg-slate-700 dark:hover:text-slate-300"
                  >
                    <XIcon className="h-3 w-3" />
                  </button>
                )}
              </div>
            )}
            {viewMode === "knowledge" && (
              <button
                type="button"
                onClick={() => setShowFilters((v) => !v)}
                className={`flex h-9 items-center gap-1.5 rounded-xl border px-2.5 text-xs font-bold shadow-sm backdrop-blur-sm transition-colors ${
                  showFilters
                    ? "border-sky-400 bg-sky-50/95 text-sky-700 dark:border-sky-600 dark:bg-sky-900/60 dark:text-sky-300"
                    : "border-slate-200 bg-white/92 text-slate-600 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-800/92 dark:text-slate-300 dark:hover:bg-slate-700"
                }`}
              >
                <SlidersHorizontal className="h-3.5 w-3.5" />
                <span className="hidden sm:inline">Filters</span>
                {activeFilterCount > 0 && (
                  <span className="rounded-full bg-sky-600 px-1.5 py-0.5 text-[9px] leading-none text-white">{activeFilterCount}</span>
                )}
              </button>
            )}
            <button
              type="button"
              onClick={() => setShowAiSettings(true)}
              title="Configure AI extraction"
              className={`flex h-9 items-center gap-1.5 rounded-xl border px-2.5 text-xs font-bold shadow-sm backdrop-blur-sm transition-colors ${aiSettings.api_key ? "border-brand-400 bg-brand-50/95 text-brand-700 dark:border-brand-600 dark:bg-brand-900/60 dark:text-brand-300" : "border-slate-200 bg-white/92 text-slate-500 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-800/92 dark:text-slate-300 dark:hover:bg-slate-700"}`}
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
                setAskResult(null);
                setAskError(null);
                setTimeout(() => askInputRef.current?.focus(), 80);
              }}
              className={`flex h-9 items-center gap-1.5 rounded-xl border px-2.5 text-xs font-bold shadow-sm backdrop-blur-sm transition-colors ${
                showAsk
                  ? "border-brand-500 bg-brand-50/95 text-brand-700 dark:border-brand-500 dark:bg-brand-900/60 dark:text-brand-300"
                  : "border-slate-200 bg-white/92 text-slate-600 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-800/92 dark:text-slate-300 dark:hover:bg-slate-700"
              }`}
            >
              <Search className="h-3.5 w-3.5" />
              <span className="hidden sm:inline">Ask AI</span>
            </button>
            <button
              type="button"
              onClick={() => {
                setShowAgents((v) => !v);
                setShowSidePanel(false);
                setSelectedNode(null);
                setSelectedEdge(null);
              }}
              className={`flex h-9 items-center gap-1.5 rounded-xl border px-2.5 text-xs font-bold shadow-sm backdrop-blur-sm transition-colors ${
                showAgents
                  ? "border-violet-500 bg-violet-50/95 text-violet-700 dark:border-violet-500 dark:bg-violet-900/60 dark:text-violet-300"
                  : "border-slate-200 bg-white/92 text-slate-600 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-800/92 dark:text-slate-300 dark:hover:bg-slate-700"
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
                setShowAgents(false);
                setSelectedNode(null);
                setSelectedEdge(null);
              }}
              className={`flex h-9 items-center gap-1.5 rounded-xl border px-2.5 text-xs font-bold shadow-sm backdrop-blur-sm transition-colors ${
                showSidePanel
                  ? "border-brand-500 bg-brand-50/95 text-brand-700 dark:border-brand-500 dark:bg-brand-900/60 dark:text-brand-300"
                  : "border-slate-200 bg-white/92 text-slate-600 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-800/92 dark:text-slate-300 dark:hover:bg-slate-700"
              }`}
            >
              <Layers3 className="h-3.5 w-3.5" />
              <span className="hidden sm:inline">Panels</span>
            </button>
          </div>
        </div>

        {viewMode === "knowledge" && showFilters && (
          <div className="absolute right-3 top-28 z-40 w-[min(25rem,calc(100%-1.5rem))] rounded-xl border border-slate-200 bg-white/95 p-3 shadow-xl backdrop-blur-sm dark:border-slate-700 dark:bg-slate-800/95 lg:top-16">
            <div className="mb-3 flex items-center justify-between gap-3">
              <div className="min-w-0">
                <p className="text-xs font-black text-slate-900 dark:text-white">Filters</p>
                <p className="text-[10px] font-semibold text-slate-400">{graphStats.components} nodes, {graphStats.relationships} edges, {graphStats.isolated} isolated</p>
              </div>
              <button
                type="button"
                onClick={clearGraphFilters}
                className="rounded-lg border border-slate-200 px-2.5 py-1 text-[11px] font-bold text-slate-500 hover:bg-slate-50 hover:text-slate-700 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-700"
              >
                Clear
              </button>
            </div>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              <select value={filters.model} onChange={(e) => setFilters((f) => ({ ...f, model: e.target.value }))} className="rounded-lg border border-slate-200 bg-white px-2.5 py-2 text-xs font-semibold text-slate-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
                <option value="">All models</option>
                {models.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
              </select>
              <select value={filters.source_type} onChange={(e) => setFilters((f) => ({ ...f, source_type: e.target.value }))} className="rounded-lg border border-slate-200 bg-white px-2.5 py-2 text-xs font-semibold text-slate-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
                <option value="">All sources</option>
                {sourceTypes.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
              <select value={filters.status} onChange={(e) => setFilters((f) => ({ ...f, status: e.target.value }))} className="rounded-lg border border-slate-200 bg-white px-2.5 py-2 text-xs font-semibold text-slate-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
                <option value="">All statuses</option>
                {statuses.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
              <select value={filters.temporal} onChange={(e) => setFilters((f) => ({ ...f, temporal: e.target.value }))} className="rounded-lg border border-slate-200 bg-white px-2.5 py-2 text-xs font-semibold text-slate-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
                <option value="">All time</option>
                <option value="current">Current</option>
                <option value="future">Future</option>
                <option value="past">Past</option>
                <option value="unknown">Unknown</option>
              </select>
              <select value={filters.confidence_threshold} onChange={(e) => setFilters((f) => ({ ...f, confidence_threshold: Number(e.target.value) }))} className="rounded-lg border border-slate-200 bg-white px-2.5 py-2 text-xs font-semibold text-slate-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
                <option value={0}>All confidence</option>
                <option value={0.5}>50% and up</option>
                <option value={0.7}>70% and up</option>
                <option value={0.85}>85% and up</option>
              </select>
              <select value={filters.relationship_origin} onChange={(e) => setFilters((f) => ({ ...f, relationship_origin: e.target.value }))} className="rounded-lg border border-slate-200 bg-white px-2.5 py-2 text-xs font-semibold text-slate-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
                <option value="">All edges</option>
                <option value="deterministic">Deterministic</option>
                <option value="extracted">Extracted</option>
                <option value="ai_proposed">AI proposed</option>
                <option value="human_verified">Human verified</option>
                <option value="proposed">Proposed</option>
              </select>
            </div>
          </div>
        )}

        <div className="hidden">
          <h2 className="text-lg font-bold text-slate-900 dark:text-white">Knowledge Graph</h2>
          <div className="flex rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 p-1">
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
                    : "text-slate-500 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white"
                }`}
              >
                {label}
              </button>
            ))}
          </div>
          {viewMode === "knowledge" && (
            <div className="hidden md:flex items-center gap-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 px-2.5 py-1.5 text-[11px] font-bold text-slate-500 dark:text-slate-400">
              <Network className="h-3.5 w-3.5 text-brand-500" />
              <span className="text-slate-900 dark:text-white">{graphStats.components}</span>
              <span>nodes</span>
              <span className="h-3 w-px bg-slate-200 dark:bg-slate-700" />
              <span className="text-slate-900 dark:text-white">{graphStats.relationships}</span>
              <span>edges</span>
              {graphStats.isolated > 0 && (
                <>
                  <span className="h-3 w-px bg-slate-200 dark:bg-slate-700" />
                  <span className="text-red-500">{graphStats.isolated}</span>
                  <span>isolated</span>
                </>
              )}
            </div>
          )}
          {viewMode === "knowledge" && showFilters && (
          <div className="flex gap-1.5 flex-wrap min-w-0">
            <select
              value={filters.model}
              onChange={(e) => setFilters((f) => ({ ...f, model: e.target.value }))}
              className="text-xs px-2.5 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-300 max-w-[9.5rem]"
            >
              <option value="">All models</option>
              {models.map((m) => (
                <option key={m.id} value={m.id}>{m.name}</option>
              ))}
            </select>
            <select
              value={filters.source_type}
              onChange={(e) => setFilters((f) => ({ ...f, source_type: e.target.value }))}
              className="text-xs px-2.5 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-300 max-w-[9.5rem]"
            >
              <option value="">All sources</option>
              {sourceTypes.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
            <select
              value={filters.status}
              onChange={(e) => setFilters((f) => ({ ...f, status: e.target.value }))}
              className="text-xs px-2.5 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-300 max-w-[9.5rem]"
            >
              <option value="">All statuses</option>
              {statuses.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
            <select
              value={filters.temporal}
              onChange={(e) => setFilters((f) => ({ ...f, temporal: e.target.value }))}
              className="text-xs px-2.5 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-300 max-w-[9.5rem]"
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
              className="text-xs px-2.5 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-300 max-w-[9.5rem]"
            >
              <option value={0}>All confidence</option>
              <option value={0.5}>≥ 50%</option>
              <option value={0.7}>≥ 70%</option>
              <option value={0.85}>≥ 85%</option>
            </select>
            <select
              value={filters.relationship_origin}
              onChange={(e) => setFilters((f) => ({ ...f, relationship_origin: e.target.value }))}
              className="text-xs px-2.5 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-300 max-w-[9.5rem]"
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
                className="text-xs pl-8 pr-2.5 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-300 w-40 focus:outline-none focus:ring-1 focus:ring-brand-400"
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
                onClick={() => setShowFilters((v) => !v)}
                className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border text-xs font-bold transition-colors ${
                  showFilters
                    ? "border-sky-400 bg-sky-50 text-sky-700 dark:border-sky-600 dark:bg-sky-900/20 dark:text-sky-300"
                    : "border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-600 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-700"
                }`}
              >
                <SlidersHorizontal className="w-3.5 h-3.5" />
                Filters
              </button>
            )}
            {agentStatus && (
              <span className={`text-[10px] font-bold uppercase tracking-wider px-2 py-1 rounded-full ${aiSettings.api_key || agentStatus.llm_enabled ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400" : "bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400"}`}>
                {aiSettings.api_key && aiSettings.model ? `AI: ${aiSettings.model}` : agentStatus.llm_enabled ? `LLM: ${agentStatus.extraction_model}` : "Regex extraction"}
              </span>
            )}
            <button
              type="button"
              onClick={() => setShowAiSettings(true)}
              title="Configure AI extraction"
              className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border text-xs font-bold transition-colors ${aiSettings.api_key ? "border-brand-400 bg-brand-50 text-brand-700 dark:border-brand-600 dark:bg-brand-900/20 dark:text-brand-400" : "border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-500 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-700"}`}
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
                  : "border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-600 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-700"
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
                  : "border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-600 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-700"
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
              {CEO_VIEWS.map(({ id, label, desc }) => (
                <button
                  key={id}
                  type="button"
                  title={desc}
                  onClick={() => setCeoView(id)}
                  className={`px-2.5 py-1 rounded-full text-[11px] font-bold transition-all ${
                    ceoView === id
                      ? id === "gaps"       ? "bg-red-500 text-white shadow-sm"
                      : id === "decisions"  ? "bg-amber-500 text-white shadow-sm"
                      : id === "aiSessions" ? "bg-violet-600 text-white shadow-sm"
                      : id === "birdsEye"   ? "bg-sky-600 text-white shadow-sm"
                      : "bg-slate-900 dark:bg-white text-white dark:text-slate-900 shadow-sm"
                      : "bg-slate-100 dark:bg-slate-800 text-slate-500 dark:text-slate-400 hover:bg-slate-200 dark:hover:bg-slate-700"
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
            {activeCeoView && ceoView !== "all" && (
              <span className="text-[10px] text-slate-400 italic hidden lg:inline">{activeCeoView.desc}</span>
            )}
          </div>
        )}

        {viewMode === "knowledge" && showFilters && (
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
                <span className="text-emerald-600 dark:text-emerald-500">{buildResult.llm_extraction ? "LLM extraction" : "Regex extraction"}</span>
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

        <div className="flex-1 relative rounded-2xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 min-h-0 overflow-hidden">
          <div ref={containerRef} className="absolute inset-0 rounded-2xl" />
          <div ref={logoLayerRef} className="pointer-events-none absolute inset-0 z-10" />

          <div className="absolute bottom-3 left-3 z-20 flex items-center gap-1 rounded-xl border border-slate-200 bg-white/92 p-1 shadow-sm backdrop-blur-sm dark:border-slate-700 dark:bg-slate-800/92">
            <button type="button" title="Zoom out" onClick={() => changeGraphZoom(-0.12)} className="flex h-7 w-7 items-center justify-center rounded-lg text-slate-500 hover:bg-slate-100 hover:text-slate-800 dark:text-slate-300 dark:hover:bg-slate-700 dark:hover:text-white">
              <Minus className="h-3.5 w-3.5" />
            </button>
            <span className="min-w-[2.75rem] text-center text-[11px] font-bold text-slate-600 dark:text-slate-300">{graphZoom}%</span>
            <button type="button" title="Zoom in" onClick={() => changeGraphZoom(0.12)} className="flex h-7 w-7 items-center justify-center rounded-lg text-slate-500 hover:bg-slate-100 hover:text-slate-800 dark:text-slate-300 dark:hover:bg-slate-700 dark:hover:text-white">
              <Plus className="h-3.5 w-3.5" />
            </button>
            <button type="button" title="Fit graph" onClick={fitGraph} className="flex h-7 w-7 items-center justify-center rounded-lg text-slate-500 hover:bg-slate-100 hover:text-slate-800 dark:text-slate-300 dark:hover:bg-slate-700 dark:hover:text-white">
              <Maximize2 className="h-3.5 w-3.5" />
            </button>
          </div>

          <div className="absolute bottom-3 right-3 z-20 flex items-center gap-2">
            {agentStatus && (
              <span className={`hidden rounded-xl border px-2.5 py-1.5 text-[10px] font-bold uppercase shadow-sm backdrop-blur-sm sm:inline-flex ${aiSettings.api_key || agentStatus.llm_enabled ? "border-emerald-200 bg-emerald-50/95 text-emerald-700 dark:border-emerald-900/50 dark:bg-emerald-950/70 dark:text-emerald-300" : "border-slate-200 bg-white/92 text-slate-500 dark:border-slate-700 dark:bg-slate-800/92 dark:text-slate-400"}`}>
                {extractionLabel}
              </span>
            )}
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
                  : "text-slate-500 hover:bg-slate-100 hover:text-slate-800 dark:text-slate-300 dark:hover:bg-slate-700 dark:hover:text-white"
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
                    <span className="text-[10px] text-slate-600 dark:text-slate-400">{label}</span>
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
                    <span className="text-[9px] font-bold bg-slate-100 dark:bg-slate-700 text-slate-500 dark:text-slate-400 px-1.5 py-0.5 rounded shrink-0">{badge}</span>
                    <span className="text-[10px] text-slate-600 dark:text-slate-400">{desc}</span>
                  </div>
                ))}
              </div>
            </div>
            <div>
              <p className="text-[9px] font-bold uppercase tracking-widest text-slate-400 mb-1.5">Box — domain</p>
              <div className="flex items-center gap-1.5">
                <span className="w-8 h-4 rounded-md shrink-0 border-2 border-indigo-400 bg-transparent" />
                <span className="text-[10px] text-slate-600 dark:text-slate-400">Each = one domain</span>
              </div>
            </div>
            <div className="border-t border-slate-100 dark:border-slate-700 pt-2">
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
                    <span className="text-[10px] text-slate-600 dark:text-slate-400">{label}</span>
                  </div>
                ))}
              </div>
            </div>
            <div className="border-t border-slate-100 dark:border-slate-700 pt-2">
              <p className="text-[9px] text-slate-400 italic">Click edges to see evidence</p>
            </div>
          </div>


          {/* ── Empty state when filters hide everything ─────────── */}
          {((currentViewData.components || currentViewData.nodes || []).length === 0) && !loading && (
            <div className="absolute inset-0 z-10 flex items-center justify-center">
              <div className="text-center p-6 bg-white/95 dark:bg-slate-800/95 rounded-2xl border border-slate-200 dark:border-slate-700 shadow-lg backdrop-blur-sm max-w-xs">
                <Search className="w-8 h-8 text-slate-300 dark:text-slate-600 mx-auto mb-2" />
                <p className="text-sm font-bold text-slate-800 dark:text-slate-200 mb-1">No visible items</p>
                <p className="text-xs text-slate-500 dark:text-slate-400 mb-3">
                  {filters.search
                    ? `No results for "${filters.search}"`
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
            <div className="absolute bottom-0 left-0 right-0 z-20 bg-white/95 dark:bg-slate-800/95 backdrop-blur-sm border-t border-slate-200 dark:border-slate-700 rounded-b-2xl shadow-xl">
              <form onSubmit={handleAsk} className="flex items-center gap-2 px-4 py-3 border-b border-slate-100 dark:border-slate-700/60">
                <svg className="w-4 h-4 text-slate-400 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
                  <circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/>
                </svg>
                <input
                  ref={askInputRef}
                  type="text"
                  value={askQuery}
                  onChange={(e) => setAskQuery(e.target.value)}
                  placeholder="Ask about this graph… e.g. What are the current blockers?"
                  className="flex-1 bg-transparent text-sm text-slate-900 dark:text-slate-100 placeholder:text-slate-400 focus:outline-none"
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
                          <p className="text-sm text-slate-800 dark:text-slate-200 leading-relaxed mt-1">{askResult.answer}</p>
                        </div>
                      )}
                      {!askResult.answer && (
                        <p className="text-xs text-slate-400 italic">Configure AI to get synthesized answers — showing matching facts below.</p>
                      )}
                      {askResult.components?.length > 0 && (
                        <div>
                          <p className="text-[10px] font-bold uppercase tracking-widest text-slate-400 mb-1.5">Cited facts ({askResult.components.length})</p>
                          <div className="flex flex-col gap-1.5">
                            {askResult.components.slice(0, 5).map((c, i) => (
                              <div key={c.id || i} className="flex items-start gap-2 p-2 rounded-lg bg-slate-50 dark:bg-slate-900/60">
                                <span className="w-4 h-4 rounded bg-brand-100 dark:bg-brand-900/40 flex items-center justify-center text-[9px] font-bold text-brand-700 dark:text-brand-300 shrink-0 mt-0.5">{i + 1}</span>
                                <div className="min-w-0">
                                  <p className="text-[11px] font-semibold text-slate-700 dark:text-slate-300">{c.value || stripModelPrefix(c.name)}</p>
                                  <span className="text-[10px] text-slate-400">{c.model_name}</span>
                                </div>
                              </div>
                            ))}
                          </div>
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

      {showSidePanel && (
        <div className="absolute bottom-3 right-3 top-20 z-40 flex w-[min(20rem,calc(100%-1.5rem))] flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-xl dark:border-slate-700 dark:bg-slate-800">
          <div className="flex items-center border-b border-slate-100 dark:border-slate-700">
            {[
              { id: "coverage", label: "Coverage" },
              { id: "work", label: "Work Lens" },
            ].map((tab) => (
              <button
                key={tab.id}
                onClick={() => setSidePanelTab(tab.id)}
                className={`flex-1 px-3 py-2 text-[11px] font-bold transition-colors ${
                  sidePanelTab === tab.id
                    ? "bg-slate-50 dark:bg-slate-700 text-slate-900 dark:text-white"
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
          onRunPack={() => callAgent("/api/agents/context-pack", setPackLoading, setPackResult, setPackError)}
          onCopyPack={copyPack}
        />
      )}

      {selectedNode && !showAgents && (
        <div className="absolute bottom-3 right-3 top-20 z-40 w-[min(22rem,calc(100%-1.5rem))] overflow-y-auto rounded-2xl border border-slate-200 bg-white p-5 shadow-xl dark:border-slate-700 dark:bg-slate-800">
          <button
            onClick={() => setSelectedNode(null)}
            className="float-right text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 text-xs font-bold"
          >
            close
          </button>

          {/* Status indicator bar */}
          {(() => {
            const sc = CARD_STATUS[selectedNode.status];
            return sc ? (
              <div
                className="w-full h-1 rounded-full mb-3"
                style={{ backgroundColor: sc.border }}
              />
            ) : <div className="w-full h-1 rounded-full mb-3 bg-slate-200 dark:bg-slate-700" />;
          })()}

          <h3 className="text-sm font-bold text-slate-900 dark:text-white mb-2.5 pr-6 leading-snug">
            {selectedNode.fullLabel || selectedNode.label.split("\n")[0]}
          </h3>

          {/* Warnings */}
          {(() => {
            const warnings = [];
            if (selectedNode.status === "stale") warnings.push({ text: "Stale — may need review", color: "amber" });
            if (selectedNode.status === "proposed") warnings.push({ text: "Proposed — not yet accepted", color: "amber" });
            if (selectedNode.status === "blocked") warnings.push({ text: "Blocked — needs attention", color: "red" });
            if (selectedNode.status === "deprecated") warnings.push({ text: "Deprecated — do not rely on", color: "red" });
            if (selectedNode.confidence != null && selectedNode.confidence < 0.5) warnings.push({ text: `Low confidence (${Math.round(selectedNode.confidence * 100)}%)`, color: "red" });
            if (!selectedNode.excerpt && !selectedNode.provenance) warnings.push({ text: "Missing evidence / provenance", color: "amber" });
            if (!selectedNode.connected || selectedNode.connected.length === 0) warnings.push({ text: "Isolated — no relationships", color: "amber" });
            if (warnings.length === 0) return null;
            return (
              <div className="mb-3 space-y-1">
                {warnings.map((w, i) => (
                  <div key={i} className={`flex items-center gap-1.5 text-[10px] font-bold px-2 py-1 rounded-lg ${
                    w.color === "red"
                      ? "bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-400"
                      : "bg-amber-50 dark:bg-amber-900/20 text-amber-700 dark:text-amber-400"
                  }`}>
                    <AlertTriangle className="w-3 h-3 shrink-0" />
                    {w.text}
                  </div>
                ))}
              </div>
            );
          })()}

          {/* Chips row */}
          <div className="flex flex-wrap gap-1.5 mb-3">
            {selectedNode.fact_type && (
              <span className="inline-block text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full bg-brand-100 dark:bg-brand-900/30 text-brand-700 dark:text-brand-300">
                {selectedNode.fact_type.replace(/_/g, " ")}
              </span>
            )}
            {selectedNode.status && (() => {
              const sm = STATUS_META[selectedNode.status];
              return sm ? (
                <span className={`inline-block text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full ${sm.pill}`}>
                  {sm.label}
                </span>
              ) : (
                <span className="inline-block text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full bg-slate-100 dark:bg-slate-700 text-slate-500">
                  {selectedNode.status}
                </span>
              );
            })()}
            {selectedNode.temporal && selectedNode.temporal !== "unknown" && (() => {
              const tm = TEMPORAL_META[selectedNode.temporal];
              return tm ? (
                <span className={`inline-block text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full ${tm.pill}`}>
                  {tm.label}
                </span>
              ) : null;
            })()}
            {selectedNode.source_type && (
              (() => {
                const familyMeta = SOURCE_FAMILY_META[selectedNode.source_family] || SOURCE_FAMILY_META.other;
                return (
                  <span className={`inline-block text-[10px] font-bold px-2 py-0.5 rounded-full ${familyMeta.bg} ${familyMeta.text}`}>
                    {SOURCE_TYPE_ICONS[selectedNode.source_type] || selectedNode.source_type.replace(/_/g, " ")}
                  </span>
                );
              })()
            )}
          </div>

          {selectedNode.value && (
            <p className="text-xs text-slate-600 dark:text-slate-400 leading-relaxed mb-4">
              {selectedNode.value}
            </p>
          )}

          <div className="space-y-2 mb-4">
            {selectedNode.confidence != null && (
              <div className="flex justify-between text-xs">
                <span className="text-slate-500">Confidence</span>
                <span className={`font-bold ${selectedNode.confidence < 0.5 ? "text-red-600 dark:text-red-400" : "text-slate-700 dark:text-slate-300"}`}>
                  {Math.round(selectedNode.confidence * 100)}%
                </span>
              </div>
            )}
            {selectedNode.authority_weight != null && (
              <div className="flex justify-between text-xs">
                <span className="text-slate-500">Authority</span>
                <span className="font-bold text-slate-700 dark:text-slate-300">
                  {Math.round(selectedNode.authority_weight * 100)}%
                </span>
              </div>
            )}
            {selectedNode.source_type && (
              <div className="flex justify-between text-xs">
                <span className="text-slate-500">Source</span>
                <span className="font-bold text-slate-700 dark:text-slate-300 capitalize">{selectedNode.source_type.replace(/_/g, " ")}</span>
              </div>
            )}
            {selectedNode.relationship_count != null && (
              <div className="flex justify-between text-xs">
                <span className="text-slate-500">Relationships</span>
                <span className="font-bold text-slate-700 dark:text-slate-300">{selectedNode.relationship_count}</span>
              </div>
            )}
            {selectedNode.source_external_id && (
              <div className="flex justify-between text-xs">
                <span className="text-slate-500">Source ID</span>
                <span className="font-mono text-slate-600 dark:text-slate-400 text-[10px] truncate max-w-[180px]" title={selectedNode.source_external_id}>{selectedNode.source_external_id}</span>
              </div>
            )}
            {selectedNode.source_metadata_summary && Object.keys(selectedNode.source_metadata_summary).length > 0 && (
              <div className="text-xs mt-1 border-t border-slate-100 dark:border-slate-700 pt-2">
                <span className="text-[10px] font-bold uppercase tracking-widest text-slate-400">Source context</span>
                <div className="mt-1 space-y-0.5">
                  {Object.entries(selectedNode.source_metadata_summary).slice(0, 5).map(([k, v]) => (
                    <div key={k} className="flex justify-between">
                      <span className="text-slate-500">{k}</span>
                      <span className="text-slate-600 dark:text-slate-400 font-mono text-[10px]">{String(v)}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
            {selectedNode.source_url && (
              <div className="flex justify-between items-start text-xs gap-2">
                <span className="text-slate-500 shrink-0">URL</span>
                <a
                  href={selectedNode.source_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="font-medium text-brand-600 dark:text-brand-400 truncate hover:underline text-right"
                  title={selectedNode.source_url}
                >
                  {selectedNode.source_url.replace(/^https?:\/\//, "").slice(0, 36)}{selectedNode.source_url.length > 46 ? "…" : ""}
                </a>
              </div>
            )}
            {selectedNode.excerpt && (
              <div className="text-xs mt-1">
                <span className="text-slate-500">Excerpt</span>
                <p className="text-slate-600 dark:text-slate-400 italic mt-0.5 line-clamp-3">{selectedNode.excerpt}</p>
              </div>
            )}
            {selectedNode.provenance && (
              <div className="text-xs">
                <span className="text-slate-500">Provenance</span>
                <p className="text-slate-500 dark:text-slate-500 mt-0.5 font-mono text-[10px] break-all line-clamp-2">{selectedNode.provenance}</p>
              </div>
            )}
          </div>

          {selectedNode.connected?.length > 0 && (
            <div>
              <p className="text-[10px] font-bold uppercase tracking-widest text-slate-400 mb-2">
                Connections ({selectedNode.connected.length})
              </p>
              {(() => {
                const grouped = {};
                selectedNode.connected.forEach((c) => {
                  const type = c.relationshipType || "related";
                  if (!grouped[type]) grouped[type] = [];
                  grouped[type].push(c);
                });
                return Object.entries(grouped).map(([type, items]) => (
                  <div key={type} className="mb-2">
                    <p className="text-[9px] font-bold uppercase tracking-wider text-slate-500 mb-1">{type}</p>
                    <div className="space-y-1">
                      {items.map((c) => (
                        <div
                          key={c.id}
                          className="flex items-center gap-2 text-xs p-2 rounded-lg bg-slate-50 dark:bg-slate-900/50 border border-slate-100 dark:border-slate-700/50"
                        >
                          <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${
                            c.origin === "human_verified" ? "bg-emerald-400" :
                            c.origin === "deterministic" ? "bg-blue-400" :
                            c.origin === "ai_proposed" ? "bg-amber-400" :
                            "bg-indigo-400"
                          }`} />
                          <span className="text-slate-700 dark:text-slate-300 truncate flex-1">{c.label}</span>
                          <span className="text-[9px] font-semibold text-slate-400 ml-auto shrink-0">
                            {c.direction === "out" ? "→" : "←"}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                ));
              })()}
            </div>
          )}
        </div>
      )}

      {selectedEdge && !showAgents && (
        <div className="absolute bottom-3 right-3 top-20 z-40 w-[min(22rem,calc(100%-1.5rem))] overflow-y-auto rounded-2xl border border-slate-200 bg-white p-5 shadow-xl dark:border-slate-700 dark:bg-slate-800">
          <button
            onClick={() => setSelectedEdge(null)}
            className="float-right text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 text-xs font-bold"
          >
            close
          </button>

          <div className="w-full h-1 rounded-full mb-3" style={{ backgroundColor: EDGE_ORIGIN_STYLE[selectedEdge.origin]?.color || "#94a3b8" }} />

          <div className="flex items-center gap-2 mb-3">
            <Link2 className="w-4 h-4 text-indigo-500" />
            <h3 className="text-sm font-bold text-slate-900 dark:text-white">
              {selectedEdge.displayLabel || selectedEdge.label}
            </h3>
          </div>

          <div className="flex flex-wrap gap-1.5 mb-3">
            {(() => {
              const originLabel = EDGE_ORIGIN_STYLE[selectedEdge.origin]?.label || selectedEdge.origin;
              const isUncertain = selectedEdge.origin === "ai_proposed" || selectedEdge.origin === "proposed";
              return (
                <span className={`inline-block text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full ${
                  selectedEdge.origin === "human_verified" ? "bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-300" :
                  selectedEdge.origin === "deterministic" ? "bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300" :
                  selectedEdge.origin === "ai_proposed" ? "bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-300" :
                  selectedEdge.origin === "extracted" ? "bg-violet-100 dark:bg-violet-900/30 text-violet-700 dark:text-violet-300" :
                  "bg-slate-100 dark:bg-slate-700 text-slate-500"
                }`}>
                  {isUncertain && "◌ "}{originLabel}
                </span>
              );
            })()}
            {selectedEdge.status && (
              <span className="inline-block text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full bg-slate-100 dark:bg-slate-700 text-slate-500">
                {selectedEdge.status}
              </span>
            )}
          </div>

          <div className="space-y-2 mb-4">
            <div className="flex justify-between text-xs">
              <span className="text-slate-500">Confidence</span>
              <span className="font-bold text-slate-700 dark:text-slate-300">
                {selectedEdge.confidence != null ? `${Math.round(selectedEdge.confidence * 100)}%` : "—"}
              </span>
            </div>
            <div className="flex justify-between text-xs">
              <span className="text-slate-500">Style</span>
              <span className="font-bold text-slate-700 dark:text-slate-300">
                {selectedEdge.origin === "ai_proposed" ? "Dashed (AI proposed)" : selectedEdge.origin === "proposed" ? "Dotted (proposed)" : selectedEdge.origin === "deterministic" ? "Solid (deterministic)" : selectedEdge.origin === "extracted" ? "Solid (extracted)" : selectedEdge.origin === "human_verified" ? "Solid (verified)" : "Solid"}
              </span>
            </div>
          </div>

          {selectedEdge.evidence && (
            <div className="mb-4">
              <div className="flex items-center gap-2 mb-1.5">
                <p className="text-[10px] font-bold uppercase tracking-widest text-slate-400">Evidence</p>
                {selectedEdge.evidence.endsWith("(template evidence)") && (
                  <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400">
                    Template — weak
                  </span>
                )}
              </div>
              <div className={`text-xs text-slate-600 dark:text-slate-400 leading-relaxed p-2.5 rounded-lg border ${
                selectedEdge.evidence.endsWith("(template evidence)")
                  ? "bg-amber-50 dark:bg-amber-900/10 border-amber-100 dark:border-amber-800/30"
                  : "bg-slate-50 dark:bg-slate-900/50 border-slate-100 dark:border-slate-700/50"
              }`}>
                {selectedEdge.evidence}
              </div>
            </div>
          )}

          {!selectedEdge.evidence && (
            <div className="mb-4">
              <p className="text-[10px] font-bold uppercase tracking-widest text-slate-400 mb-1.5">Evidence</p>
              <div className="flex items-center gap-1.5 text-xs text-red-600 dark:text-red-400 p-2.5 rounded-lg bg-red-50 dark:bg-red-900/10 border border-red-100 dark:border-red-800/30">
                <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
                No evidence recorded for this relationship.
              </div>
            </div>
          )}

          {/* Source / target names if available */}
          {selectedEdge.sourceName && selectedEdge.targetName && (
            <div className="space-y-1.5 mb-4 text-xs border-t border-slate-100 dark:border-slate-700 pt-2">
              <div className="flex justify-between">
                <span className="text-slate-500">From</span>
                <span className="font-bold text-slate-700 dark:text-slate-300 truncate max-w-[140px]" title={selectedEdge.sourceName}>{selectedEdge.sourceName}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-500">To</span>
                <span className="font-bold text-slate-700 dark:text-slate-300 truncate max-w-[140px]" title={selectedEdge.targetName}>{selectedEdge.targetName}</span>
              </div>
            </div>
          )}

          {(selectedEdge.origin === "ai_proposed" || selectedEdge.origin === "proposed" || selectedEdge.status === "proposed") && (
            <div className="mb-4 rounded-xl border border-amber-200 bg-amber-50 p-2.5 dark:border-amber-900/40 dark:bg-amber-950/20">
              <p className="mb-2 text-[10px] font-bold uppercase tracking-widest text-amber-700 dark:text-amber-300">Review proposed edge</p>
              <div className="grid grid-cols-2 gap-2">
                <button
                  type="button"
                  disabled={edgeReviewLoading}
                  onClick={() => reviewSelectedEdge("accept")}
                  className="inline-flex items-center justify-center gap-1.5 rounded-lg bg-emerald-600 px-2.5 py-1.5 text-[11px] font-bold text-white hover:bg-emerald-700 disabled:opacity-50"
                >
                  {edgeReviewLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
                  Accept
                </button>
                <button
                  type="button"
                  disabled={edgeReviewLoading}
                  onClick={() => reviewSelectedEdge("reject")}
                  className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-red-200 bg-white px-2.5 py-1.5 text-[11px] font-bold text-red-700 hover:bg-red-50 disabled:opacity-50 dark:border-red-900/50 dark:bg-slate-900 dark:text-red-300 dark:hover:bg-red-950/30"
                >
                  {edgeReviewLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <XCircle className="h-3.5 w-3.5" />}
                  Reject
                </button>
              </div>
              {edgeReviewError && (
                <p className="mt-2 text-[10px] font-semibold text-red-600 dark:text-red-400">{edgeReviewError}</p>
              )}
            </div>
          )}

          <div className="text-[10px] text-slate-400 border-t border-slate-100 dark:border-slate-700 pt-2">
            <p>Edge ID: <span className="font-mono text-slate-500 dark:text-slate-400">{selectedEdge.id.slice(0, 8)}…</span></p>
          </div>
        </div>
      )}

      {showAiSettings && (
        <div className="fixed inset-0 bg-black/40 backdrop-blur-sm z-50 flex items-center justify-center" onClick={() => setShowAiSettings(false)}>

          <div className="bg-white dark:bg-slate-800 rounded-2xl border border-slate-200 dark:border-slate-700 p-6 w-[22rem] shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-5">
              <div>
                <h3 className="text-sm font-bold text-slate-900 dark:text-white">AI Extraction Settings</h3>
                <p className="text-[10px] text-slate-400 dark:text-slate-500 mt-0.5">Bring your own API key to power intelligent graph building</p>
              </div>
              <button onClick={() => setShowAiSettings(false)} className="text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 text-sm font-bold ml-3">✕</button>
            </div>

            <div className="space-y-4">
              <div>
                <label className="block text-xs font-semibold text-slate-600 dark:text-slate-400 mb-1.5">Provider</label>
                <select
                  value={aiSettings.provider || ""}
                  onChange={(e) => {
                    const p = e.target.value;
                    const newS = { ...aiSettings, provider: p, model: "" };
                    setAiSettings(newS);
                    localStorage.setItem("ce_ai_settings", JSON.stringify(newS));
                  }}
                  className="w-full text-xs px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-600 bg-slate-50 dark:bg-slate-900 text-slate-700 dark:text-slate-300"
                >
                  <option value="">— select provider —</option>
                  <option value="google">Google (Gemini)</option>
                  <option value="anthropic">Anthropic (Claude)</option>
                  <option value="openai">OpenAI (GPT)</option>
                  <option value="custom">OpenAI-compatible API</option>
                </select>
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-600 dark:text-slate-400 mb-1.5">API Key</label>
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
                  className="w-full text-xs px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-600 bg-slate-50 dark:bg-slate-900 text-slate-700 dark:text-slate-300 font-mono"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-600 dark:text-slate-400 mb-1.5">Model</label>
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
                    className="w-full text-xs px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-600 bg-slate-50 dark:bg-slate-900 text-slate-700 dark:text-slate-300 font-mono"
                  />
                ) : (
                  <select
                    value={aiSettings.model || ""}
                    onChange={(e) => {
                      const newS = { ...aiSettings, model: e.target.value };
                      setAiSettings(newS);
                      localStorage.setItem("ce_ai_settings", JSON.stringify(newS));
                    }}
                    className="w-full text-xs px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-600 bg-slate-50 dark:bg-slate-900 text-slate-700 dark:text-slate-300 font-mono"
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

              <div className="rounded-lg bg-slate-50 dark:bg-slate-900/50 border border-slate-200 dark:border-slate-700 px-3 py-2.5 space-y-1.5">
                <p className="text-[10px] font-semibold text-slate-500 dark:text-slate-400">How it works</p>
                <p className="text-[10px] text-slate-500 dark:text-slate-400 leading-relaxed">
                  When you click <strong className="text-slate-600 dark:text-slate-300">Build Graph</strong>, your synced source documents are sent to the AI. It reads each document and extracts:
                </p>
                <ul className="text-[10px] text-slate-500 dark:text-slate-400 leading-relaxed list-disc pl-3 space-y-0.5">
                  <li><strong className="text-slate-600 dark:text-slate-300">Domain models</strong> — business areas like Pricing, Features, Decisions</li>
                  <li><strong className="text-slate-600 dark:text-slate-300">Atomic facts</strong> — each tagged as current, past, or future</li>
                  <li><strong className="text-slate-600 dark:text-slate-300">Relationships</strong> — logical links between facts across models</li>
                </ul>
                <p className="text-[10px] text-slate-500 dark:text-slate-400 leading-relaxed mt-1">
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
                    className="px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-600 text-slate-500 dark:text-slate-400 text-xs font-bold hover:bg-slate-50 dark:hover:bg-slate-700 transition-colors"
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

function GraphStat({ label, value, icon: Icon, tone = "slate" }) {
  const tones = {
    slate: "border-slate-200 bg-white text-slate-700 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200",
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
  packResult, packLoading, packError, packCopied, onRunPack, onCopyPack,
}) {
  return (
    <div className="absolute bottom-3 right-3 top-20 z-40 flex w-[min(22rem,calc(100%-1.5rem))] flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-xl dark:border-slate-700 dark:bg-slate-800">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-100 dark:border-slate-700 shrink-0">
        <div className="flex items-center gap-2">
          <div className="w-6 h-6 rounded-lg bg-violet-500 flex items-center justify-center">
            <Bot className="w-3.5 h-3.5 text-white" />
          </div>
          <span className="text-sm font-bold text-slate-900 dark:text-white">AI Agents</span>
        </div>
        <button
          onClick={onClose}
          className="w-6 h-6 flex items-center justify-center rounded-md text-slate-400 hover:text-slate-600 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
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
            <a href="/app/graph" className="text-[10px] font-bold text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 border border-slate-200 dark:border-slate-600 px-2 py-1 rounded-lg transition-colors whitespace-nowrap">
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
                <div key={i} className="flex items-start gap-1.5 p-2 rounded-lg bg-slate-50 dark:bg-slate-900/60 border border-slate-100 dark:border-slate-700/50">
                  <span className={`text-[9px] font-bold px-1 rounded shrink-0 mt-0.5 ${r.confidence >= 0.7 ? "bg-emerald-100 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-400" : "bg-slate-100 dark:bg-slate-700 text-slate-500"}`}>
                    {Math.round(r.confidence * 100)}%
                  </span>
                  <p className="text-[10px] text-slate-600 dark:text-slate-400 leading-snug">
                    <span className="font-semibold text-slate-700 dark:text-slate-300">{r.source_name}</span>
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
            <p className="text-[10px] text-slate-500 dark:text-slate-400 mt-1.5 leading-relaxed">
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
            <a href="/app/query" className="text-[10px] font-bold text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 border border-slate-200 dark:border-slate-600 px-2 py-1 rounded-lg transition-colors whitespace-nowrap">
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
          desc="Generates a handoff prompt for AI agents"
          action={
            <SidebarRunBtn loading={packLoading} onClick={onRunPack} color="emerald">
              Generate
            </SidebarRunBtn>
          }
        >
          {packError && <SidebarError>{packError}</SidebarError>}
          {packResult && (
            <div className="mt-2">
              <div className="flex items-center justify-between mb-1.5">
                <p className="text-[10px] text-slate-400">{packResult.entity_count} entities</p>
                <button
                  onClick={onCopyPack}
                  className={`flex items-center gap-1 text-[10px] font-bold px-2 py-0.5 rounded-md transition-all ${packCopied ? "bg-emerald-100 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-400" : "bg-slate-100 dark:bg-slate-700 text-slate-500 hover:bg-slate-200 dark:hover:bg-slate-600"}`}
                >
                  {packCopied ? <Check className="w-2.5 h-2.5" /> : <Copy className="w-2.5 h-2.5" />}
                  {packCopied ? "Copied!" : "Copy"}
                </button>
              </div>
              <pre className="text-[10px] text-slate-600 dark:text-slate-300 bg-slate-50 dark:bg-slate-900/60 border border-slate-200 dark:border-slate-700 rounded-lg p-2.5 overflow-x-auto whitespace-pre-wrap leading-relaxed font-mono max-h-40 overflow-y-auto">
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
    <div className="rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800/50 p-3">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <div className={`w-5 h-5 rounded-md ${iconColor} flex items-center justify-center text-white shrink-0`}>
            {icon}
          </div>
          <div className="min-w-0">
            <div className="flex items-center gap-1.5">
              <span className="text-[9px] font-bold text-slate-400 uppercase tracking-wide">{num}</span>
              <span className="text-xs font-bold text-slate-800 dark:text-slate-200">{title}</span>
            </div>
            <p className="text-[10px] text-slate-500 dark:text-slate-400 leading-none mt-0.5 truncate">{desc}</p>
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
          <div key={s.label} className="rounded-lg bg-slate-50 dark:bg-slate-900/60 border border-slate-100 dark:border-slate-700/50 p-2 text-center">
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
        <div key={i} className="flex items-start gap-1.5 p-2 rounded-lg bg-slate-50 dark:bg-slate-900/60 border border-slate-100 dark:border-slate-700/50">
          <div className={`w-1.5 h-1.5 rounded-full shrink-0 mt-1.5 ${SEV_DOT[g.severity] || SEV_DOT.low}`} />
          <div className="min-w-0">
            <div className="flex items-center gap-1 flex-wrap">
              <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded-full ${SEV_PILL[g.severity] || SEV_PILL.low}`}>{g.severity}</span>
            </div>
            <p className="text-[10px] font-semibold text-slate-700 dark:text-slate-300 mt-0.5 leading-snug">{g.title}</p>
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
    { key: "github", label: "GitHub", icon: GitPullRequest, color: "text-slate-700 dark:text-slate-300", bg: "bg-slate-100 dark:bg-slate-700" },
    { key: "agent", label: "AI Sessions", icon: Bot, color: "text-violet-700 dark:text-violet-300", bg: "bg-violet-100 dark:bg-violet-900/30" },
    { key: "communication", label: "Comms", icon: MessageCircle, color: "text-sky-700 dark:text-sky-300", bg: "bg-sky-100 dark:bg-sky-900/30" },
    { key: "local", label: "Local", icon: FileText, color: "text-slate-600 dark:text-slate-300", bg: "bg-slate-100 dark:bg-slate-700" },
    { key: "other", label: "Other", icon: Layers3, color: "text-teal-700 dark:text-teal-300", bg: "bg-teal-100 dark:bg-teal-900/30" },
  ];

  return (
    <div className="space-y-3">
      <p className="text-[10px] font-bold uppercase tracking-widest text-slate-400">By source family</p>
      <div className="space-y-1.5">
        {families.map(({ key, label, icon: Icon, color, bg }) => {
          const data = byFamily[key];
          return (
            <div key={key} className="flex items-center justify-between gap-2 p-2 rounded-lg bg-slate-50 dark:bg-slate-900/50 border border-slate-100 dark:border-slate-700/50">
              <div className="flex items-center gap-2">
                <div className={`w-6 h-6 rounded-md ${bg} flex items-center justify-center`}>
                  <Icon className={`w-3.5 h-3.5 ${color}`} />
                </div>
                <span className="text-xs font-bold text-slate-700 dark:text-slate-300">{label}</span>
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
                  <span className="text-slate-600 dark:text-slate-400 capitalize">{type.replace(/_/g, " ")}</span>
                  <span className="font-bold text-slate-700 dark:text-slate-300">{count}</span>
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
          slate: "bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-300",
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
                  <div key={item.id} className="p-2 rounded-lg bg-slate-50 dark:bg-slate-900/50 border border-slate-100 dark:border-slate-700/50">
                    <p className="text-[11px] font-semibold text-slate-700 dark:text-slate-300 truncate">{item.name || item.display_title}</p>
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
