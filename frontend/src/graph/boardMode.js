/** Board view defaults — model-first shard clusters, quiet canvas, lens presets. */

export const BOARD_CARD_WIDTH = 88;
export const BOARD_CARD_HEIGHT = 58;
export const BOARD_CARD_TEXT_MAX_WIDTH = BOARD_CARD_WIDTH - 18;
export const BOARD_READABLE_ZOOM = 0.62;
export const BOARD_READABLE_PAN_PADDING = { x: 24, y: 72 };
export const BOARD_MODEL_GROUP_PREFIX = "model:";
export const BOARD_UNMODELED_GROUP = `${BOARD_MODEL_GROUP_PREFIX}unmodeled`;

export const BOARD_LENSES = [
  { id: "all", label: "All Models", desc: "Every model cluster in this workspace" },
  { id: "work", label: "Work", desc: "Tasks, issues, PRs, and active delivery items" },
  { id: "decisions", label: "Decisions", desc: "Decision facts and their neighborhood" },
  { id: "gaps", label: "Gaps", desc: "Isolated components with no relationships" },
];

const BOARD_ACCENT = "#3b82f6";
const BOARD_NEUTRAL_BORDER = "#475569";
const BOARD_MODEL_COLORS = [
  "#7c3aed",
  "#db2777",
  "#2563eb",
  "#0891b2",
  "#059669",
  "#d97706",
  "#dc2626",
  "#4f46e5",
];

const BOARD_SHARD_POLYGONS = [
  [-0.92, -0.68, 0.42, -0.96, 0.96, -0.16, 0.62, 0.84, -0.78, 0.92],
  [-0.58, -0.98, 0.94, -0.66, 0.78, 0.72, -0.50, 0.98, -0.98, 0.08],
  [-0.86, -0.82, 0.72, -0.78, 0.94, 0.56, -0.18, 0.94, -0.96, 0.30],
  [-0.32, -0.98, 0.92, -0.38, 0.66, 0.88, -0.86, 0.72, -0.98, -0.22],
  [-0.96, -0.36, -0.30, -0.96, 0.88, -0.60, 0.96, 0.52, -0.42, 0.98],
  [-0.84, -0.90, 0.24, -0.96, 0.98, -0.32, 0.48, 0.90, -0.98, 0.64],
  [-0.64, -0.94, 0.68, -0.92, 0.98, 0.24, 0.04, 0.98, -0.92, 0.48],
  [-0.96, -0.14, -0.52, -0.94, 0.76, -0.86, 0.96, 0.44, -0.18, 0.96],
];

function hashString(seed = "") {
  const text = String(seed || "shard");
  let hash = 2166136261;
  for (let i = 0; i < text.length; i += 1) {
    hash ^= text.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function rotatePoints(points, angleDeg) {
  const rad = (angleDeg * Math.PI) / 180;
  const cos = Math.cos(rad);
  const sin = Math.sin(rad);
  const rotated = [];
  let maxAbs = 0;
  for (let i = 0; i < points.length; i += 2) {
    const x = points[i];
    const y = points[i + 1];
    const rx = x * cos - y * sin;
    const ry = x * sin + y * cos;
    rotated.push(rx, ry);
    maxAbs = Math.max(maxAbs, Math.abs(rx), Math.abs(ry));
  }
  const scale = maxAbs > 0.96 ? 0.96 / maxAbs : 1;
  return rotated.map((point) => clamp(point * scale, -0.98, 0.98));
}

function pointsToString(points) {
  return points.map((point) => Number(point.toFixed(3))).join(" ");
}

function pointsToCssPolygon(points) {
  const css = [];
  for (let i = 0; i < points.length; i += 2) {
    css.push(`${((points[i] + 1) * 50).toFixed(1)}% ${((points[i + 1] + 1) * 50).toFixed(1)}%`);
  }
  return `polygon(${css.join(", ")})`;
}

function pointsToSvgPolygon(points) {
  const svg = [];
  for (let i = 0; i < points.length; i += 2) {
    svg.push(`${((points[i] + 1) * 50).toFixed(1)},${((points[i + 1] + 1) * 50).toFixed(1)}`);
  }
  return svg.join(" ");
}

export function boardModelGroupKey(modelId) {
  return modelId ? `${BOARD_MODEL_GROUP_PREFIX}${modelId}` : BOARD_UNMODELED_GROUP;
}

export function boardModelColor(seed = "") {
  const hash = hashString(seed || "model");
  return BOARD_MODEL_COLORS[hash % BOARD_MODEL_COLORS.length];
}

export function boardShardGeometry(seed = "", index = 0, {
  angle = 0,
  scale = 1,
} = {}) {
  const hash = hashString(`${seed}:${index}`);
  const base = BOARD_SHARD_POLYGONS[hash % BOARD_SHARD_POLYGONS.length];
  const widthJitter = [-10, -4, 0, 7, 13, 18][hash % 6];
  const heightJitter = [-8, -3, 2, 7, 11][Math.floor(hash / 7) % 5];
  const rotation = angle + [-10, -5, 0, 6, 11][Math.floor(hash / 13) % 5];
  const rotatedPoints = rotatePoints(base, rotation);

  return {
    width: Math.round(clamp((BOARD_CARD_WIDTH + widthJitter) * scale, 46, 122)),
    height: Math.round(clamp((BOARD_CARD_HEIGHT + heightJitter) * scale, 34, 86)),
    rotation: Number(rotation.toFixed(2)),
    polygonPoints: pointsToString(rotatedPoints),
    clipPath: pointsToCssPolygon(base),
    svgPoints: pointsToSvgPolygon(base),
  };
}

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
  const status = String(component.status || "").toLowerCase();
  const byKind = {
    github: { bg: "#f5f3ff", border: BOARD_NEUTRAL_BORDER, stripe: "#7c3aed" },
    slack: { bg: "#fdf2f8", border: BOARD_NEUTRAL_BORDER, stripe: "#db2777" },
    gmail: { bg: "#eef2ff", border: BOARD_NEUTRAL_BORDER, stripe: "#6366f1" },
    agent: { bg: "#f3e8ff", border: BOARD_NEUTRAL_BORDER, stripe: "#9333ea" },
    local: { bg: "#faf5ff", border: BOARD_NEUTRAL_BORDER, stripe: "#a855f7" },
  };
  const palette = byKind[kind] || { bg: "#f5f3ff", border: BOARD_NEUTRAL_BORDER, stripe: "#8b5cf6" };
  if (status === "blocked" || status === "stale" || status === "deprecated") {
    return { ...palette, border: "#ef4444" };
  }
  if (status === "needs_review" || status === "proposed" || status === "draft") {
    return { ...palette, border: "#d97706" };
  }
  return palette;
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

export function buildBoardShardClusterLayout(itemCount, {
  cardWidth = BOARD_CARD_WIDTH,
  cardHeight = BOARD_CARD_HEIGHT,
} = {}) {
  if (itemCount <= 0) {
    return { positions: [], width: 300, height: 180 };
  }

  const positions = [];
  const outerCount = itemCount <= 14
    ? itemCount
    : Math.min(itemCount, Math.max(12, Math.ceil(itemCount * 0.58)));
  const middleCount = itemCount <= outerCount
    ? 0
    : Math.min(itemCount - outerCount, Math.max(4, Math.ceil(itemCount * 0.28)));
  const innerCount = Math.max(0, itemCount - outerCount - middleCount);
  const ringCounts = [outerCount, middleCount, innerCount].filter((count) => count > 0);
  const outerRadiusX = clamp(126 + itemCount * 5.4 + cardWidth * 0.2, 150, 330);
  const outerRadiusY = clamp(100 + itemCount * 4.4 + cardHeight * 0.28, 124, 280);
  let slot = 0;

  ringCounts.forEach((count, ring) => {
    const radiusScale = ring === 0 ? 1 : ring === 1 ? 0.62 : 0.34;
    const sizeScale = ring === 0 ? 1 : ring === 1 ? 0.72 : 0.58;
    const startAngle = -88 + ring * 19;
    const radiusX = outerRadiusX * radiusScale;
    const radiusY = outerRadiusY * radiusScale;

    for (let index = 0; index < count; index += 1) {
      const localHash = hashString(`${itemCount}:${ring}:${index}`);
      const jitter = ((localHash % 1000) / 1000 - 0.5) * (ring === 0 ? 9 : 15);
      const radialJitter = (((localHash >>> 10) % 1000) / 1000 - 0.5) * (ring === 0 ? 18 : 12);
      const angle = startAngle + (360 * index) / count + jitter;
      const rad = (angle * Math.PI) / 180;
      const tangent = angle + 90 + (((localHash >>> 20) % 1000) / 1000 - 0.5) * 14;

      positions.push({
        x: Math.cos(rad) * (radiusX + radialJitter),
        y: Math.sin(rad) * (radiusY + radialJitter * 0.7),
        angle,
        rotation: tangent,
        ring,
        slot,
        scale: sizeScale,
      });
      slot += 1;
    }
  });

  const minX = positions.reduce((value, pos) => Math.min(value, pos.x - (cardWidth * pos.scale) / 2), Infinity);
  const maxX = positions.reduce((value, pos) => Math.max(value, pos.x + (cardWidth * pos.scale) / 2), -Infinity);
  const minY = positions.reduce((value, pos) => Math.min(value, pos.y - (cardHeight * pos.scale) / 2), Infinity);
  const maxY = positions.reduce((value, pos) => Math.max(value, pos.y + (cardHeight * pos.scale) / 2), -Infinity);

  return {
    positions,
    width: Math.max(360, maxX - minX + cardWidth + 120),
    height: Math.max(280, maxY - minY + cardHeight + 120),
  };
}

export const buildBoardTetrisClusterLayout = buildBoardShardClusterLayout;
