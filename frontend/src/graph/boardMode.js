/** Board view defaults — source-first clusters, quiet canvas, lens presets. */

export const BOARD_CARD_WIDTH = 188;
export const BOARD_CARD_HEIGHT = 64;
export const BOARD_CARD_TEXT_MAX_WIDTH = BOARD_CARD_WIDTH - 36;
export const BOARD_READABLE_ZOOM = 0.52;
export const BOARD_READABLE_PAN_PADDING = { x: 24, y: 72 };

export const BOARD_LENSES = [
  { id: "all", label: "All Sources", desc: "Every source cluster in this workspace" },
  { id: "work", label: "Work", desc: "Tasks, issues, PRs, and active delivery items" },
  { id: "decisions", label: "Decisions", desc: "Decision facts and their neighborhood" },
  { id: "gaps", label: "Gaps", desc: "Isolated components with no relationships" },
];

const BOARD_ACCENT = "#3b82f6";
const BOARD_NEUTRAL_BORDER = "#475569";

export function boardGraphGroup(component, sourceKindFn, sourceFamilyFn) {
  const kind = sourceKindFn(component);
  if (kind === "github") return "github";
  if (kind === "slack") return "slack";
  if (kind === "gmail") return "gmail";
  if (kind === "agent") return "agents";
  if (kind === "local") return "localDocs";
  const family = sourceFamilyFn(component);
  if (family === "communication") return "slack";
  return "other";
}

export function passesBoardLens(component, modelName, lensId) {
  const fact = String(component.fact_type || "").toLowerCase();
  const model = String(modelName || component.model_name || "").toLowerCase();
  const status = String(component.status || "").toLowerCase();

  if (lensId === "all" || lensId === "gaps") return true;
  if (lensId === "work") {
    return (
      /(task|action_item|open_question|github_issue|github_pr|pr_review_finding|changed_file|commit)/.test(fact)
      || /(task|issue|work|pr|repo|github)/.test(model)
      || status === "blocked"
    );
  }
  if (lensId === "decisions") {
    return /decision/.test(fact) || /decision/.test(model);
  }
  return true;
}

export function filterGapsLens(components, relationships) {
  const connected = new Set();
  relationships.forEach((r) => {
    connected.add(r.source_component_id);
    connected.add(r.target_component_id);
  });
  return components.filter((c) => !connected.has(c.id));
}

export function shouldUseReadableBoardViewport({
  viewMode,
  graphLayout,
  fitZoom,
  readableZoom = BOARD_READABLE_ZOOM,
}) {
  return viewMode === "knowledge" && graphLayout === "board" && Number.isFinite(fitZoom) && fitZoom < readableZoom;
}

export function boardReadablePan(bounds, zoom, padding = BOARD_READABLE_PAN_PADDING) {
  return {
    x: padding.x - (bounds?.x1 || 0) * zoom,
    y: padding.y - (bounds?.y1 || 0) * zoom,
  };
}

export function boardCardVisuals(component, isGap, sourceKindFn) {
  if (isGap) {
    return {
      bg: "#fff1f2",
      border: "#ef4444",
      stripe: "#ef4444",
    };
  }
  const kind = sourceKindFn(component);
  const byKind = {
    github: { bg: "#f8fafc", border: BOARD_NEUTRAL_BORDER, stripe: "#6e7681" },
    slack: { bg: "#f0f9ff", border: BOARD_NEUTRAL_BORDER, stripe: "#1d9bd1" },
    gmail: { bg: "#f0f9ff", border: BOARD_NEUTRAL_BORDER, stripe: "#38bdf8" },
    agent: { bg: "#f5f3ff", border: BOARD_NEUTRAL_BORDER, stripe: "#8b5cf6" },
    local: { bg: "#f8fafc", border: BOARD_NEUTRAL_BORDER, stripe: "#94a3b8" },
  };
  return byKind[kind] || { bg: "#f8fafc", border: BOARD_NEUTRAL_BORDER, stripe: BOARD_ACCENT };
}

export function resolveRelationshipEdgeStyle({
  relationship,
  sameGroup,
  showTrustEdges,
  isDark,
}) {
  const origin = relationship.origin || "proposed";
  const originStyles = {
    deterministic: { lineStyle: "solid", width: 3.8, opacity: 0.96, color: "#2563eb" },
    extracted: { lineStyle: "solid", width: 3.4, opacity: 0.9, color: "#7c3aed" },
    proposed: { lineStyle: "dotted", width: 2.8, opacity: 0.78, color: "#475569" },
    ai_proposed: { lineStyle: "dashed", width: 3.1, opacity: 0.86, color: "#d97706" },
    human_verified: { lineStyle: "solid", width: 4, opacity: 0.98, color: "#059669" },
  };

  if (showTrustEdges) {
    const style = originStyles[origin] || originStyles.extracted;
    return { origin, ...style };
  }

  const accent = isDark ? "#60a5fa" : BOARD_ACCENT;
  return {
    origin,
    lineStyle: "solid",
    width: sameGroup ? 3.2 : 4,
    opacity: sameGroup ? 0.9 : 0.96,
    color: accent,
  };
}

export function buildBoardCardLines(title, context, detail) {
  const lines = [title, context || detail].map((line) => String(line || "").trim()).filter(Boolean);
  return lines.slice(0, 2);
}
