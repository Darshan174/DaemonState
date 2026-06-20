/** Board view defaults — source-first clusters, quiet canvas, lens presets. */

export const BOARD_CARD_WIDTH = 220;
export const BOARD_CARD_HEIGHT = 80;
export const BOARD_CARD_TEXT_MAX_WIDTH = BOARD_CARD_WIDTH - 36;
export const BOARD_READABLE_ZOOM = 0.82;
export const BOARD_READABLE_PAN_PADDING = { x: 28, y: 86 };

export const BOARD_LENSES = [
  { id: "all", label: "All Sources", desc: "Every source cluster in this workspace" },
  { id: "work", label: "Work", desc: "Tasks, issues, PRs, and active delivery items" },
  { id: "decisions", label: "Decisions", desc: "Decision facts and their neighborhood" },
  { id: "gaps", label: "Gaps", desc: "Isolated components with no relationships" },
];

const BOARD_ACCENT = "#3b82f6";
const BOARD_NEUTRAL_BORDER = "#64748b";

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
      bg: "rgba(239,68,68,0.08)",
      border: BOARD_NEUTRAL_BORDER,
      stripe: "#ef4444",
    };
  }
  const kind = sourceKindFn(component);
  const byKind = {
    github: { bg: "rgba(59,130,246,0.08)", border: BOARD_NEUTRAL_BORDER, stripe: "#6e7681" },
    slack: { bg: "rgba(59,130,246,0.08)", border: BOARD_NEUTRAL_BORDER, stripe: "#1d9bd1" },
    gmail: { bg: "rgba(59,130,246,0.08)", border: BOARD_NEUTRAL_BORDER, stripe: "#38bdf8" },
    agent: { bg: "rgba(59,130,246,0.08)", border: BOARD_NEUTRAL_BORDER, stripe: "#8b5cf6" },
    local: { bg: "rgba(59,130,246,0.08)", border: BOARD_NEUTRAL_BORDER, stripe: "#94a3b8" },
  };
  return byKind[kind] || { bg: "rgba(59,130,246,0.06)", border: BOARD_NEUTRAL_BORDER, stripe: BOARD_ACCENT };
}

export function resolveRelationshipEdgeStyle({
  relationship,
  sameGroup,
  showTrustEdges,
  isDark,
}) {
  const origin = relationship.origin || "proposed";
  const originStyles = {
    deterministic: { lineStyle: "solid", width: 2, opacity: 0.76, color: "#3b82f6" },
    extracted: { lineStyle: "solid", width: 1.6, opacity: 0.56, color: "#8b5cf6" },
    proposed: { lineStyle: "dotted", width: 1.4, opacity: 0.4, color: "#94a3b8" },
    ai_proposed: { lineStyle: "dashed", width: 1.5, opacity: 0.44, color: "#f59e0b" },
    human_verified: { lineStyle: "solid", width: 2.4, opacity: 0.88, color: "#059669" },
  };

  if (showTrustEdges) {
    const style = originStyles[origin] || originStyles.extracted;
    return { origin, ...style };
  }

  const accent = isDark ? "#60a5fa" : BOARD_ACCENT;
  return {
    origin,
    lineStyle: "solid",
    width: sameGroup ? 1 : 1.5,
    opacity: sameGroup ? 0.45 : 0.65,
    color: accent,
  };
}

export function buildBoardCardLines(title, context, detail) {
  const lines = [title, context || detail].map((line) => String(line || "").trim()).filter(Boolean);
  return lines.slice(0, 2);
}
