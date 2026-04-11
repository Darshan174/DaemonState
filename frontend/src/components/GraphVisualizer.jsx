import { useMemo } from "react";

const TYPE_COLORS = {
  model: { fill: "#e0e7ff", stroke: "#4f46e5", text: "#312e81" },
  source: { fill: "#dcfce7", stroke: "#16a34a", text: "#166534" },
  component: { fill: "#fef3c7", stroke: "#d97706", text: "#92400e" },
};

function buildNeighborSet(nodeId, edges) {
  const neighbors = new Set([nodeId]);
  for (const edge of edges) {
    if (edge.source === nodeId) neighbors.add(edge.target);
    if (edge.target === nodeId) neighbors.add(edge.source);
  }
  return neighbors;
}

function edgePath(src, tgt) {
  const mx = (src.x + tgt.x) / 2;
  const my = (src.y + tgt.y) / 2;
  const curve = Math.abs(src.x - tgt.x) > 120 ? -28 : -18;
  return `M ${src.x} ${src.y} Q ${mx} ${my + curve} ${tgt.x} ${tgt.y}`;
}

export default function GraphVisualizer({
  nodes,
  edges,
  selectedNodeId = null,
  hoveredNodeId = null,
  onNodeSelect,
  onNodeHover,
}) {
  const nodesById = useMemo(
    () => new Map(nodes.map((node) => [node.id, node])),
    [nodes],
  );

  const focusNodeId = hoveredNodeId || selectedNodeId;
  const focusSet = useMemo(
    () => (focusNodeId ? buildNeighborSet(focusNodeId, edges) : null),
    [focusNodeId, edges],
  );

  const visibleEdges = edges
    .map((edge) => ({
      ...edge,
      sourceNode: nodesById.get(edge.source),
      targetNode: nodesById.get(edge.target),
    }))
    .filter((edge) => edge.sourceNode && edge.targetNode);

  return (
    <div className="relative w-full h-full min-h-[420px] overflow-hidden rounded-[28px] border border-slate-200 bg-[radial-gradient(circle_at_top,_rgba(79,70,229,0.08),_transparent_38%),linear-gradient(180deg,_#ffffff,_#f8fafc)] shadow-[0_24px_60px_rgba(15,23,42,0.08)]">
      <svg
        className="absolute inset-0 h-full w-full"
        viewBox="0 0 800 500"
        role="img"
        aria-label="Interactive knowledge graph"
      >
        <defs>
          <filter id="graph-node-glow" x="-50%" y="-50%" width="200%" height="200%">
            <feDropShadow dx="0" dy="10" stdDeviation="8" floodColor="#0f172a" floodOpacity="0.14" />
          </filter>
        </defs>

        <rect x="0" y="0" width="800" height="500" fill="transparent" onClick={() => onNodeSelect?.(null)} />

        {visibleEdges.map((edge) => {
          const isFocused =
            !focusSet ||
            (focusSet.has(edge.source) && focusSet.has(edge.target));
          const mx = (edge.sourceNode.x + edge.targetNode.x) / 2;
          const my = (edge.sourceNode.y + edge.targetNode.y) / 2;

          return (
            <g
              key={`${edge.source}-${edge.target}-${edge.label}`}
              opacity={isFocused ? 1 : 0.15}
              className="transition-opacity duration-300 ease-in-out"
            >
              <path
                d={edgePath(edge.sourceNode, edge.targetNode)}
                fill="none"
                stroke={isFocused ? "#94a3b8" : "#cbd5e1"}
                strokeWidth={isFocused ? 2 : 1.5}
                strokeDasharray={isFocused ? "none" : "6 6"}
                className="transition-all duration-300 ease-in-out"
              />
              <text
                x={mx}
                y={my - 8}
                textAnchor="middle"
                className="text-[10.5px] font-medium tracking-wide transition-all duration-300"
                fill={isFocused ? "#475569" : "#94a3b8"}
                stroke="white"
                strokeWidth="4"
                paintOrder="stroke"
                strokeLinejoin="round"
              >
                {edge.label}
              </text>
            </g>
          );
        })}

        {nodes.map((node) => {
          const palette = TYPE_COLORS[node.type] || TYPE_COLORS.component;
          const isFocused = !focusSet || focusSet.has(node.id);
          const isSelected = selectedNodeId === node.id;
          const radius = isSelected ? 24 : 18;

          return (
            <g
              key={node.id}
              opacity={isFocused ? 1 : 0.2}
              className="cursor-pointer transition-opacity duration-300 ease-in-out"
              onClick={(event) => {
                event.stopPropagation();
                onNodeSelect?.(node.id);
              }}
              onMouseEnter={() => onNodeHover?.(node.id)}
              onMouseLeave={() => onNodeHover?.(null)}
            >
              {isSelected && (
                <circle
                  cx={node.x}
                  cy={node.y}
                  r={radius + 12}
                  fill="rgba(79,70,229,0.12)"
                  className="transition-all duration-300 ease-out origin-center"
                  style={{ transformOrigin: `${node.x}px ${node.y}px` }}
                />
              )}
              <circle
                cx={node.x}
                cy={node.y}
                r={radius}
                fill={palette.fill}
                stroke={isSelected ? "#4f46e5" : palette.stroke}
                strokeWidth={isSelected ? 3.5 : 2}
                filter="url(#graph-node-glow)"
                className="transition-all duration-300 ease-out origin-center"
                style={{ transformOrigin: `${node.x}px ${node.y}px` }}
              />
              <text
                x={node.x}
                y={node.y - (radius + 14)}
                textAnchor="middle"
                fill={palette.text}
                className="text-[12px] font-bold tracking-tight transition-all duration-300"
                stroke="white"
                strokeWidth="4.5"
                paintOrder="stroke"
                strokeLinejoin="round"
              >
                {node.label}
              </text>
            </g>
          );
        })}
      </svg>

      <div className="absolute bottom-3 left-3 flex flex-wrap gap-4 rounded-full border border-white/70 bg-white/80 px-4 py-2 text-[11px] text-slate-500 backdrop-blur">
        {Object.entries(TYPE_COLORS).map(([type, palette]) => (
          <span key={type} className="flex items-center gap-1.5">
            <span
              className="h-2.5 w-2.5 rounded-full"
              style={{ backgroundColor: palette.stroke }}
            />
            {type}
          </span>
        ))}
      </div>

      <div className="absolute right-3 top-3 rounded-full border border-white/70 bg-white/80 px-3 py-1.5 text-[11px] text-slate-500 backdrop-blur">
        Click a node to open its local graph
      </div>
    </div>
  );
}
