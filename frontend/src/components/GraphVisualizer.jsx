import { useEffect, useMemo, useRef, useState } from "react";
import { Maximize2, Minus, Plus, RotateCcw } from "lucide-react";

const CANVAS = { width: 980, height: 640 };
const MIN_ZOOM = 0.55;
const MAX_ZOOM = 2.2;

const TYPE_STYLES = {
  model: {
    fill: "#eef2ff",
    stroke: "#4f46e5",
    text: "#312e81",
    ring: "rgba(79,70,229,0.16)",
    label: "Models",
  },
  source: {
    fill: "#ecfdf5",
    stroke: "#059669",
    text: "#064e3b",
    ring: "rgba(5,150,105,0.14)",
    label: "Sources",
  },
  component: {
    fill: "#fff7ed",
    stroke: "#ea580c",
    text: "#7c2d12",
    ring: "rgba(234,88,12,0.14)",
    label: "Components",
  },
};

const RELATIONSHIP_STYLES = [
  {
    match: /contradict|block/i,
    stroke: "#dc2626",
    marker: "arrow-risk",
    chip: "#fee2e2",
    text: "#991b1b",
  },
  {
    match: /supersede/i,
    stroke: "#7c3aed",
    marker: "arrow-supersedes",
    chip: "#ede9fe",
    text: "#5b21b6",
  },
  {
    match: /depend/i,
    stroke: "#2563eb",
    marker: "arrow-depends",
    chip: "#dbeafe",
    text: "#1e3a8a",
  },
  {
    match: /enable|drive|produce|inform|feed/i,
    stroke: "#059669",
    marker: "arrow-positive",
    chip: "#d1fae5",
    text: "#065f46",
  },
];

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function isFinitePoint(node) {
  return Number.isFinite(node.x) && Number.isFinite(node.y);
}

function buildLayout(nodes, edges) {
  if (nodes.length === 0) return [];

  const hasUsablePositions = nodes.every(isFinitePoint);
  const positioned = hasUsablePositions
    ? nodes
    : radialLayout(nodes, edges);

  const padded = positioned.map((node) => ({
    ...node,
    x: clamp(Math.round(node.x), 70, CANVAS.width - 70),
    y: clamp(Math.round(node.y), 70, CANVAS.height - 70),
  }));

  return relaxCollisions(padded);
}

function radialLayout(nodes, edges) {
  const degree = new Map(nodes.map((node) => [node.id, 0]));
  for (const edge of edges) {
    degree.set(edge.source, (degree.get(edge.source) ?? 0) + 1);
    degree.set(edge.target, (degree.get(edge.target) ?? 0) + 1);
  }

  const models = nodes.filter((node) => node.type === "model");
  const others = nodes.filter((node) => node.type !== "model");
  const modelCount = Math.max(models.length, 1);
  const modelAnchors = new Map();

  models.forEach((node, index) => {
    modelAnchors.set(node.id, {
      x: Math.round(((index + 1) * CANVAS.width) / (modelCount + 1)),
      y: 130,
    });
  });

  const byModel = new Map();
  for (const node of others) {
    const key = node.modelId ?? "__unmodeled__";
    const group = byModel.get(key) ?? [];
    group.push(node);
    byModel.set(key, group);
  }

  const placed = [];
  for (const node of models) {
    placed.push({ ...node, ...modelAnchors.get(node.id) });
  }

  byModel.forEach((group, modelId) => {
    group.sort((a, b) => (degree.get(b.id) ?? 0) - (degree.get(a.id) ?? 0));
    const anchor = modelAnchors.get(modelId) ?? {
      x: Math.round(CANVAS.width / 2),
      y: 270,
    };
    const radius = clamp(92 + group.length * 8, 110, 210);

    group.forEach((node, index) => {
      const angle = -Math.PI / 2 + (Math.PI * 2 * index) / Math.max(group.length, 1);
      const yOffset = node.type === "source" ? 210 : 190;
      placed.push({
        ...node,
        x: anchor.x + Math.cos(angle) * radius,
        y: anchor.y + yOffset + Math.sin(angle) * radius * 0.68,
      });
    });
  });

  return placed;
}

function relaxCollisions(nodes) {
  const next = nodes.map((node) => ({ ...node }));
  for (let pass = 0; pass < 14; pass += 1) {
    for (let i = 0; i < next.length; i += 1) {
      for (let j = i + 1; j < next.length; j += 1) {
        const a = next[i];
        const b = next[j];
        const minDistance = nodeRadius(a) + nodeRadius(b) + 22;
        const dx = b.x - a.x;
        const dy = b.y - a.y;
        const distance = Math.max(Math.sqrt(dx * dx + dy * dy), 0.001);
        if (distance >= minDistance) continue;

        const push = (minDistance - distance) / 2;
        const ux = dx / distance;
        const uy = dy / distance;
        a.x = clamp(a.x - ux * push, 70, CANVAS.width - 70);
        a.y = clamp(a.y - uy * push, 70, CANVAS.height - 70);
        b.x = clamp(b.x + ux * push, 70, CANVAS.width - 70);
        b.y = clamp(b.y + uy * push, 70, CANVAS.height - 70);
      }
    }
  }
  return next.map((node) => ({
    ...node,
    x: Math.round(node.x),
    y: Math.round(node.y),
  }));
}

function nodeRadius(node) {
  if (node.type === "model") return 26;
  const confidence = Number.isFinite(node.confidence) ? node.confidence : 0.75;
  const sourceBoost = Math.min(Number(node.sourceCount ?? 0), 5) * 1.5;
  return Math.round(17 + confidence * 5 + sourceBoost);
}

function edgeStyle(edge) {
  if (edge.sentiment === "negative") {
    return RELATIONSHIP_STYLES[0];
  }
  if (edge.sentiment === "positive") {
    return RELATIONSHIP_STYLES[3];
  }
  const label = edge.label ?? "";
  return (
    RELATIONSHIP_STYLES.find((style) => style.match.test(label)) ?? {
      stroke: "#64748b",
      marker: "arrow-neutral",
      chip: "#f1f5f9",
      text: "#334155",
    }
  );
}

function edgePath(src, tgt) {
  const dx = tgt.x - src.x;
  const dy = tgt.y - src.y;
  const distance = Math.max(Math.sqrt(dx * dx + dy * dy), 1);
  const sourcePad = nodeRadius(src) + 5;
  const targetPad = nodeRadius(tgt) + 9;
  const start = {
    x: src.x + (dx / distance) * sourcePad,
    y: src.y + (dy / distance) * sourcePad,
  };
  const end = {
    x: tgt.x - (dx / distance) * targetPad,
    y: tgt.y - (dy / distance) * targetPad,
  };
  const mx = (start.x + end.x) / 2;
  const my = (start.y + end.y) / 2;
  const curve = clamp(Math.abs(dx) * 0.12, 22, 56) * (src.y <= tgt.y ? -1 : 1);
  return `M ${start.x} ${start.y} Q ${mx} ${my + curve} ${end.x} ${end.y}`;
}

function edgeMidpoint(src, tgt) {
  return {
    x: Math.round((src.x + tgt.x) / 2),
    y: Math.round((src.y + tgt.y) / 2),
  };
}

function truncateLabel(label, max = 30) {
  const text = String(label ?? "");
  if (text.length <= max) return text;
  return `${text.slice(0, max - 3)}...`;
}

function buildNeighborSet(nodeId, edges) {
  const neighbors = new Set([nodeId]);
  for (const edge of edges) {
    if (edge.source === nodeId) neighbors.add(edge.target);
    if (edge.target === nodeId) neighbors.add(edge.source);
  }
  return neighbors;
}

function graphSignature(nodes) {
  return nodes.map((node) => `${node.id}:${node.x ?? ""}:${node.y ?? ""}`).join("|");
}

export default function GraphVisualizer({
  nodes,
  edges,
  selectedNodeId = null,
  hoveredNodeId = null,
  onNodeSelect,
  onNodeHover,
}) {
  const containerRef = useRef(null);
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [draggingNodeId, setDraggingNodeId] = useState(null);
  const [draggingCanvas, setDraggingCanvas] = useState(null);
  const [manualPositions, setManualPositions] = useState({});

  const layoutSignature = useMemo(() => graphSignature(nodes), [nodes]);

  const baseNodes = useMemo(
    () => buildLayout(nodes, edges),
    [nodes, edges],
  );

  useEffect(() => {
    setManualPositions({});
    setZoom(1);
    setPan({ x: 0, y: 0 });
  }, [layoutSignature]);

  const positionedNodes = useMemo(
    () =>
      baseNodes.map((node) => ({
        ...node,
        ...(manualPositions[node.id] ?? {}),
      })),
    [baseNodes, manualPositions],
  );

  const nodesById = useMemo(
    () => new Map(positionedNodes.map((node) => [node.id, node])),
    [positionedNodes],
  );

  const visibleEdges = useMemo(
    () =>
      edges
        .map((edge) => ({
          ...edge,
          sourceNode: nodesById.get(edge.source),
          targetNode: nodesById.get(edge.target),
        }))
        .filter((edge) => edge.sourceNode && edge.targetNode),
    [edges, nodesById],
  );

  const focusNodeId = hoveredNodeId || draggingNodeId || selectedNodeId;
  const focusSet = useMemo(
    () => (focusNodeId ? buildNeighborSet(focusNodeId, visibleEdges) : null),
    [focusNodeId, visibleEdges],
  );

  const visibleLabels = useMemo(() => {
    if (positionedNodes.length <= 36) {
      return new Set(positionedNodes.map((node) => node.id));
    }
    const important = [...positionedNodes]
      .sort(
        (a, b) =>
          Number(b.sourceCount ?? 0) - Number(a.sourceCount ?? 0) ||
          Number(b.confidence ?? 0) - Number(a.confidence ?? 0),
      )
      .slice(0, 28)
      .map((node) => node.id);
    return new Set([selectedNodeId, hoveredNodeId, ...important].filter(Boolean));
  }, [hoveredNodeId, positionedNodes, selectedNodeId]);

  const counts = useMemo(
    () =>
      positionedNodes.reduce(
        (acc, node) => {
          acc[node.type] = (acc[node.type] ?? 0) + 1;
          return acc;
        },
        { model: 0, source: 0, component: 0 },
      ),
    [positionedNodes],
  );

  function toGraphPoint(event) {
    const rect = containerRef.current?.getBoundingClientRect();
    if (!rect) return { x: 0, y: 0 };
    const viewX = ((event.clientX - rect.left) / rect.width) * CANVAS.width;
    const viewY = ((event.clientY - rect.top) / rect.height) * CANVAS.height;
    return {
      x: (viewX - pan.x) / zoom,
      y: (viewY - pan.y) / zoom,
    };
  }

  function updateZoom(nextZoom) {
    setZoom(clamp(nextZoom, MIN_ZOOM, MAX_ZOOM));
  }

  function resetView() {
    setZoom(1);
    setPan({ x: 0, y: 0 });
    setManualPositions({});
  }

  function handleWheel(event) {
    event.preventDefault();
    const delta = event.deltaY > 0 ? -0.08 : 0.08;
    updateZoom(zoom + delta);
  }

  function handlePointerMove(event) {
    if (draggingNodeId) {
      event.preventDefault();
      const point = toGraphPoint(event);
      setManualPositions((current) => ({
        ...current,
        [draggingNodeId]: {
          x: clamp(Math.round(point.x), 50, CANVAS.width - 50),
          y: clamp(Math.round(point.y), 50, CANVAS.height - 50),
        },
      }));
      return;
    }

    if (draggingCanvas) {
      event.preventDefault();
      const dx = ((event.clientX - draggingCanvas.clientX) / draggingCanvas.width) * CANVAS.width;
      const dy = ((event.clientY - draggingCanvas.clientY) / draggingCanvas.height) * CANVAS.height;
      setPan({
        x: draggingCanvas.originX + dx,
        y: draggingCanvas.originY + dy,
      });
    }
  }

  function handlePointerUp() {
    setDraggingNodeId(null);
    setDraggingCanvas(null);
  }

  if (positionedNodes.length === 0) {
    return (
      <div className="relative flex h-full min-h-[420px] items-center justify-center overflow-hidden rounded-xl border border-slate-200 bg-slate-50 text-sm text-slate-500 dark:border-slate-800/50 dark:bg-slate-900/40 dark:text-slate-400">
        No graph nodes match the current filters.
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      className="relative h-full min-h-[420px] w-full overflow-hidden rounded-xl border border-slate-200 bg-white shadow-[0_18px_48px_rgba(15,23,42,0.08)] dark:border-slate-800/50 dark:bg-slate-950"
      onWheel={handleWheel}
      onPointerMove={handlePointerMove}
      onPointerUp={handlePointerUp}
      onPointerCancel={handlePointerUp}
      onPointerLeave={handlePointerUp}
    >
      <svg
        className="absolute inset-0 h-full w-full touch-none"
        viewBox={`0 0 ${CANVAS.width} ${CANVAS.height}`}
        role="img"
        aria-label="Interactive knowledge graph"
      >
        <defs>
          <pattern id="graph-grid" width="36" height="36" patternUnits="userSpaceOnUse">
            <path d="M 36 0 L 0 0 0 36" fill="none" stroke="#e2e8f0" strokeWidth="0.7" />
          </pattern>
          <pattern id="graph-grid-dark" width="36" height="36" patternUnits="userSpaceOnUse">
            <path d="M 36 0 L 0 0 0 36" fill="none" stroke="#334155" strokeOpacity="0.32" strokeWidth="0.55" />
          </pattern>
          <filter id="node-shadow" x="-35%" y="-35%" width="170%" height="170%">
            <feDropShadow dx="0" dy="10" stdDeviation="8" floodColor="#0f172a" floodOpacity="0.14" />
          </filter>
          <ArrowMarker id="arrow-neutral" color="#64748b" />
          <ArrowMarker id="arrow-risk" color="#dc2626" />
          <ArrowMarker id="arrow-supersedes" color="#7c3aed" />
          <ArrowMarker id="arrow-depends" color="#2563eb" />
          <ArrowMarker id="arrow-positive" color="#059669" />
        </defs>

        <rect
          className="dark:hidden"
          x="0"
          y="0"
          width={CANVAS.width}
          height={CANVAS.height}
          fill="url(#graph-grid)"
          onPointerDown={(event) => {
            if (event.button !== 0) return;
            onNodeSelect?.(null);
            setDraggingCanvas({
              clientX: event.clientX,
              clientY: event.clientY,
              width: event.currentTarget.getBoundingClientRect().width,
              height: event.currentTarget.getBoundingClientRect().height,
              originX: pan.x,
              originY: pan.y,
            });
          }}
        />
        <rect
          className="hidden dark:block"
          x="0"
          y="0"
          width={CANVAS.width}
          height={CANVAS.height}
          fill="url(#graph-grid-dark)"
          onPointerDown={(event) => {
            if (event.button !== 0) return;
            onNodeSelect?.(null);
            setDraggingCanvas({
              clientX: event.clientX,
              clientY: event.clientY,
              width: event.currentTarget.getBoundingClientRect().width,
              height: event.currentTarget.getBoundingClientRect().height,
              originX: pan.x,
              originY: pan.y,
            });
          }}
        />

        <g transform={`translate(${pan.x} ${pan.y}) scale(${zoom})`}>
          {visibleEdges.map((edge) => {
            const isFocused =
              !focusSet ||
              (focusSet.has(edge.source) && focusSet.has(edge.target));
            const style = edgeStyle(edge);
            const mid = edgeMidpoint(edge.sourceNode, edge.targetNode);

            return (
              <g
                key={edge.id ?? `${edge.source}-${edge.target}-${edge.label}`}
                opacity={isFocused ? 1 : 0.12}
                className="transition-opacity duration-200 ease-out"
              >
                <path
                  d={edgePath(edge.sourceNode, edge.targetNode)}
                  fill="none"
                  stroke={style.stroke}
                  strokeWidth={isFocused ? 2.8 : 1.6}
                  strokeLinecap="round"
                  markerEnd={`url(#${style.marker})`}
                  className="transition-all duration-200"
                />
                {isFocused && (
                  <g transform={`translate(${mid.x} ${mid.y - 10})`}>
                    <rect
                      x={-measureLabel(edge.label) / 2}
                      y="-13"
                      width={measureLabel(edge.label)}
                      height="24"
                      rx="12"
                      fill={style.chip}
                      stroke="rgba(255,255,255,0.78)"
                    />
                    <text
                      textAnchor="middle"
                      dominantBaseline="middle"
                      fill={style.text}
                      className="text-[11px] font-semibold"
                    >
                      {truncateLabel(edge.label, 22)}
                    </text>
                  </g>
                )}
              </g>
            );
          })}

          {positionedNodes.map((node) => {
            const palette = TYPE_STYLES[node.type] || TYPE_STYLES.component;
            const isFocused = !focusSet || focusSet.has(node.id);
            const isSelected = selectedNodeId === node.id;
            const isHovered = hoveredNodeId === node.id || draggingNodeId === node.id;
            const radius = nodeRadius(node) + (isSelected ? 5 : 0);
            const showLabel = visibleLabels.has(node.id);

            return (
              <g
                key={node.id}
                role="button"
                aria-label={`${node.type ?? "node"}: ${node.label}`}
                tabIndex={0}
                opacity={isFocused ? 1 : 0.18}
                className="cursor-grab outline-none transition-opacity duration-200 active:cursor-grabbing"
                onClick={(event) => {
                  event.stopPropagation();
                  onNodeSelect?.(node.id);
                }}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    onNodeSelect?.(node.id);
                  }
                }}
                onPointerDown={(event) => {
                  event.stopPropagation();
                  event.currentTarget.setPointerCapture?.(event.pointerId);
                  setDraggingNodeId(node.id);
                  onNodeHover?.(node.id);
                  onNodeSelect?.(node.id);
                }}
                onMouseEnter={() => onNodeHover?.(node.id)}
                onMouseLeave={() => {
                  if (!draggingNodeId) onNodeHover?.(null);
                }}
              >
                {(isSelected || isHovered) && (
                  <circle cx={node.x} cy={node.y} r={radius + 17} fill={palette.ring} />
                )}
                <circle
                  cx={node.x}
                  cy={node.y}
                  r={radius}
                  fill={palette.fill}
                  stroke={isSelected ? "#111827" : palette.stroke}
                  strokeWidth={isSelected ? 3.4 : 2.2}
                  filter="url(#node-shadow)"
                />
                {(node.reviewStatus === "needs_review" || node.isStale) && (
                  <circle cx={node.x + radius - 3} cy={node.y - radius + 3} r="6" fill="#f59e0b" />
                )}
                {node.temporalState === "historical" && (
                  <path
                    d={`M ${node.x - radius + 8} ${node.y + radius - 8} L ${node.x + radius - 8} ${node.y - radius + 8}`}
                    stroke="#64748b"
                    strokeWidth="2"
                    strokeLinecap="round"
                  />
                )}
                <text
                  x={node.x}
                  y={node.y + 4}
                  textAnchor="middle"
                  fill={palette.text}
                  className="pointer-events-none text-[11px] font-black uppercase"
                >
                  {node.type === "model" ? "M" : node.type === "source" ? "S" : "C"}
                </text>
                {showLabel && (
                  <text
                    x={node.x}
                    y={node.y - (radius + 15)}
                    textAnchor="middle"
                    fill={palette.text}
                    className="pointer-events-none text-[12px] font-bold"
                    stroke="white"
                    strokeWidth="4.5"
                    paintOrder="stroke"
                    strokeLinejoin="round"
                  >
                    {truncateLabel(node.label)}
                  </text>
                )}
              </g>
            );
          })}
        </g>
      </svg>

      <div className="absolute left-3 top-3 flex flex-wrap gap-2">
        {Object.entries(TYPE_STYLES).map(([type, palette]) => (
          <span
            key={type}
            className="inline-flex items-center gap-1.5 rounded-full border border-white/80 bg-white/90 px-2.5 py-1 text-[11px] font-medium text-slate-600 shadow-sm backdrop-blur dark:border-slate-800/80 dark:bg-slate-900/85 dark:text-slate-300"
          >
            <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: palette.stroke }} />
            {palette.label} {counts[type] ?? 0}
          </span>
        ))}
      </div>

      <div className="absolute bottom-3 left-3 rounded-full border border-white/80 bg-white/90 px-3 py-1.5 text-[11px] font-medium text-slate-500 shadow-sm backdrop-blur dark:border-slate-800/80 dark:bg-slate-900/85 dark:text-slate-400">
        {positionedNodes.length} nodes &middot; {visibleEdges.length} relationships &middot; {Math.round(zoom * 100)}%
      </div>

      <div className="absolute right-3 top-3 flex overflow-hidden rounded-full border border-white/80 bg-white/90 shadow-sm backdrop-blur dark:border-slate-800/80 dark:bg-slate-900/85">
        <GraphControlButton label="Zoom out" onClick={() => updateZoom(zoom - 0.15)}>
          <Minus className="h-3.5 w-3.5" />
        </GraphControlButton>
        <GraphControlButton label="Zoom in" onClick={() => updateZoom(zoom + 0.15)}>
          <Plus className="h-3.5 w-3.5" />
        </GraphControlButton>
        <GraphControlButton label="Fit view" onClick={() => setPan({ x: 0, y: 0 })}>
          <Maximize2 className="h-3.5 w-3.5" />
        </GraphControlButton>
        <GraphControlButton label="Reset graph" onClick={resetView}>
          <RotateCcw className="h-3.5 w-3.5" />
        </GraphControlButton>
      </div>
    </div>
  );
}

function GraphControlButton({ label, onClick, children }) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={onClick}
      className="border-r border-slate-200 p-2 text-slate-500 transition-colors last:border-r-0 hover:bg-slate-100 hover:text-slate-900 dark:border-slate-800 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-100"
    >
      {children}
    </button>
  );
}

function ArrowMarker({ id, color }) {
  return (
    <marker
      id={id}
      viewBox="0 0 10 10"
      refX="8"
      refY="5"
      markerWidth="5"
      markerHeight="5"
      orient="auto-start-reverse"
    >
      <path d="M 0 0 L 10 5 L 0 10 z" fill={color} />
    </marker>
  );
}

function measureLabel(label) {
  return clamp(String(label ?? "").length * 7.5 + 24, 64, 170);
}
