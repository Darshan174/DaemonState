import { useEffect, useRef, useState, useCallback } from "react";
import cytoscape from "cytoscape";

const STATUS_COLORS = {
  active: "#22c55e",
  stale: "#f59e0b",
  deprecated: "#ef4444",
  superseded: "#6366f1",
};

const MODEL_COLORS = [
  "#6366f1", "#8b5cf6", "#ec4899", "#f43f5e", "#f97316",
  "#eab308", "#22c55e", "#14b8a6", "#06b6d4", "#3b82f6",
];

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

export default function GraphView() {
  const containerRef = useRef(null);
  const cyRef = useRef(null);
  const [viewMode, setViewMode] = useState("knowledge");
  const [graphData, setGraphData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [selectedNode, setSelectedNode] = useState(null);
  const [filters, setFilters] = useState({
    model: "",
    source_type: "",
    status: "",
  });

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

  const filteredData = useCallback(() => {
    if (!graphData) return { models: [], components: [], relationships: [] };
    if (viewMode === "repo") return graphData;

    let components = graphData.components || [];
    let relationships = graphData.relationships || [];

    if (filters.model) {
      components = components.filter((c) => c.model_id === filters.model);
    }
    if (filters.source_type) {
      components = components.filter((c) => c.source_type === filters.source_type);
    }
    if (filters.status) {
      components = components.filter((c) => c.status === filters.status);
    }

    const componentIds = new Set(components.map((c) => c.id));
    relationships = relationships.filter(
      (r) => componentIds.has(r.source_component_id) && componentIds.has(r.target_component_id)
    );

    return { models: graphData.models || [], components, relationships };
  }, [graphData, filters, viewMode]);

  useEffect(() => {
    if (!containerRef.current || !graphData) return;

    const viewData = filteredData();
    const { models = [], components = [], relationships = [] } = viewData;

    const modelColorMap = {};
    models.forEach((m, i) => {
      modelColorMap[m.id] = MODEL_COLORS[i % MODEL_COLORS.length];
    });

    const nodes = [];
    const edges = [];

    if (viewMode === "repo") {
      (viewData.nodes || []).forEach((node) => {
        nodes.push({
          data: {
            id: node.id,
            label: shortLabel(node.label),
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
            edgeType: edge.label === "contains" ? "contains" : "relationship",
          },
        });
      });
    } else {
      models.forEach((m) => {
        nodes.push({
          data: {
            id: `model:${m.id}`,
            label: shortLabel(m.name),
            fullLabel: m.name,
            type: "model",
            modelId: m.id,
            description: m.description || "",
          },
          classes: "model-node",
        });
      });

      components.forEach((c) => {
        const color = STATUS_COLORS[c.status] || "#64748b";
        nodes.push({
          data: {
            id: c.id,
            label: shortLabel(c.name),
            fullLabel: c.name,
            type: "component",
            value: c.value,
            confidence: c.confidence,
            status: c.status,
            fact_type: c.fact_type,
            modelId: c.model_id,
            source_type: c.source_type,
            bgColor: modelColorMap[c.model_id] || "#94a3b8",
            borderColor: color,
          },
        });
      });

      components.forEach((c) => {
        edges.push({
          data: {
            id: `contains:${c.model_id}:${c.id}`,
            source: `model:${c.model_id}`,
            target: c.id,
            label: "contains",
            edgeType: "contains",
          },
        });
      });

      relationships.forEach((r) => {
        edges.push({
          data: {
            id: r.id,
            source: r.source_component_id,
            target: r.target_component_id,
            label: (r.relationship_type || "related_to").replaceAll("_", " "),
            edgeType: "relationship",
          },
        });
      });
    }

    const cy = cytoscape({
      container: containerRef.current,
      elements: { nodes, edges },
      style: [
        {
          selector: "node",
          style: {
            label: "data(label)",
            "text-valign": "bottom",
            "text-halign": "center",
            "font-size": "7px",
            "font-weight": "600",
            color: "#334155",
            "background-color": "#cbd5e1",
            width: 28,
            height: 28,
            "border-width": 2,
            "border-color": "#94a3b8",
            "text-margin-y": 6,
            "text-wrap": "wrap",
            "text-max-width": 64,
            "text-overflow-wrap": "anywhere",
          },
        },
        {
          selector: ".model-node, .repo-node",
          style: {
            "background-color": "#1e293b",
            "border-color": "#475569",
            color: "#1e293b",
            width: 44,
            height: 44,
            "font-size": "8px",
            "font-weight": "800",
            shape: "round-rectangle",
            "text-margin-y": 8,
          },
        },
        {
          selector: "node[type='component']",
          style: {
            "background-color": "data(bgColor)",
            "border-color": "data(borderColor)",
            width: 24,
            height: 24,
          },
        },
        {
          selector: "node[type='area'], node[type='folder'], node[type='file'], node[type='technology']",
          style: {
            "background-color": "data(bgColor)",
            "border-color": "data(borderColor)",
            width: 24,
            height: 24,
            shape: "round-rectangle",
          },
        },
        {
          selector: "node[type='area']",
          style: {
            width: 46,
            height: 34,
            "font-size": "8px",
            "font-weight": "800",
            "text-max-width": 92,
          },
        },
        {
          selector: "node[type='technology']",
          style: {
            width: 34,
            height: 28,
            "font-size": "8px",
            "text-max-width": 86,
          },
        },
        {
          selector: "node[type='file']",
          style: {
            width: 22,
            height: 22,
            "font-size": "7px",
            "text-max-width": 72,
          },
        },
        {
          selector: "edge",
          style: {
            width: 1.5,
            "line-color": "#cbd5e1",
            "target-arrow-color": "#cbd5e1",
            "target-arrow-shape": "triangle",
            "arrow-scale": 0.8,
            "curve-style": "bezier",
            label: "data(label)",
            "font-size": "8px",
            color: "#94a3b8",
            "text-rotation": "autorotate",
            "text-margin-y": -12,
            opacity: 0.6,
          },
        },
        {
          selector: "edge[edgeType='contains']",
          style: {
            "line-style": "dashed",
            "line-color": "#94a3b8",
            "target-arrow-color": "#94a3b8",
            opacity: 0.3,
            label: "",
          },
        },
        {
          selector: ":selected",
          style: {
            "border-width": 3,
            "border-color": "#4f46e5",
            "background-color": "#4f46e5",
            color: "#fff",
          },
        },
      ],
      layout: {
        name: viewMode === "repo" ? "preset" : "cose",
        idealEdgeLength: viewMode === "repo" ? 95 : 150,
        nodeOverlap: 30,
        refresh: 20,
        randomize: false,
        componentSpacing: viewMode === "repo" ? 70 : 110,
        nodeRepulsion: viewMode === "repo" ? 9000 : 12000,
        edgeElasticity: 100,
        nestingFactor: 1.2,
        gravity: 0.2,
        fit: true,
        padding: viewMode === "repo" ? 110 : 60,
        animate: false,
      },
      wheelSensitivity: 0.3,
    });

    cy.on("tap", "node", (evt) => {
      const data = evt.target.data();
      if (data.type !== "model") {
        const connectedEdges = cy.edges(`[source = "${data.id}"], [target = "${data.id}"]`);
        const connected = [];
        connectedEdges.forEach((e) => {
          const src = e.data("source");
          const tgt = e.data("target");
          const otherId = src === data.id ? tgt : src;
          const otherNode = cy.getElementById(otherId);
          if (otherNode.length) {
            connected.push({ id: otherId, label: otherNode.data("fullLabel") || otherNode.data("label"), edgeLabel: e.data("label") });
          }
        });
        setSelectedNode({ ...data, connected });
      } else {
        setSelectedNode(null);
      }
    });

    cy.on("tap", (evt) => {
      if (evt.target === cy) setSelectedNode(null);
    });

    cy.on("mouseover", "node", (evt) => {
      const node = evt.target;
      const fullLabel = node.data("fullLabel");
      if (fullLabel) node.data("label", fullLabel);
    });

    cy.on("mouseout", "node", (evt) => {
      const node = evt.target;
      const fullLabel = node.data("fullLabel");
      if (fullLabel) node.data("label", shortLabel(fullLabel));
    });

    cyRef.current = cy;

    return () => {
      cy.destroy();
    };
  }, [graphData, filteredData, viewMode]);

  const models = graphData?.models || [];
  const allComponents = graphData?.components || [];
  const sourceTypes = [...new Set(allComponents.map((c) => c.source_type).filter(Boolean))];
  const statuses = [...new Set(allComponents.map((c) => c.status).filter(Boolean))];

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
    <div className="flex h-full gap-4">
      <div className="flex-1 flex flex-col min-w-0">
        <div className="flex items-center gap-3 mb-4 flex-wrap">
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
          <div className="flex gap-2 flex-wrap">
            <select
              value={filters.model}
              onChange={(e) => setFilters((f) => ({ ...f, model: e.target.value }))}
              className="text-xs px-3 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-300"
            >
              <option value="">All models</option>
              {models.map((m) => (
                <option key={m.id} value={m.id}>{m.name}</option>
              ))}
            </select>
            <select
              value={filters.source_type}
              onChange={(e) => setFilters((f) => ({ ...f, source_type: e.target.value }))}
              className="text-xs px-3 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-300"
            >
              <option value="">All sources</option>
              {sourceTypes.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
            <select
              value={filters.status}
              onChange={(e) => setFilters((f) => ({ ...f, status: e.target.value }))}
              className="text-xs px-3 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-300"
            >
              <option value="">All statuses</option>
              {statuses.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          </div>
          )}
        </div>
        <div
          ref={containerRef}
          className="flex-1 rounded-2xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 min-h-0"
        />
      </div>

      {selectedNode && (
        <div className="w-72 shrink-0 bg-white dark:bg-slate-800 rounded-2xl border border-slate-200 dark:border-slate-700 p-5 overflow-y-auto">
          <button
            onClick={() => setSelectedNode(null)}
            className="float-right text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 text-xs font-bold"
          >
            close
          </button>
          <h3 className="text-sm font-bold text-slate-900 dark:text-white mb-1 pr-6">
            {selectedNode.label}
          </h3>
          <span className="inline-block text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full bg-brand-100 dark:bg-brand-900/30 text-brand-700 dark:text-brand-300 mb-3">
            {selectedNode.fact_type || "fact"}
          </span>
          <p className="text-xs text-slate-600 dark:text-slate-400 leading-relaxed mb-4">
            {selectedNode.value}
          </p>
          <div className="space-y-2 mb-4">
            <div className="flex justify-between text-xs">
              <span className="text-slate-500">Confidence</span>
              <span className="font-bold text-slate-700 dark:text-slate-300">
                {selectedNode.confidence != null ? `${Math.round(selectedNode.confidence * 100)}%` : "—"}
              </span>
            </div>
            <div className="flex justify-between text-xs">
              <span className="text-slate-500">Status</span>
              <span className="font-bold text-slate-700 dark:text-slate-300">{selectedNode.status}</span>
            </div>
          </div>
          {selectedNode.connected?.length > 0 && (
            <div>
              <p className="text-[10px] font-bold uppercase tracking-widest text-slate-400 mb-2">
                Connected ({selectedNode.connected.length})
              </p>
              <div className="space-y-1.5">
                {selectedNode.connected.map((c) => (
                  <div
                    key={c.id}
                    className="flex items-center gap-2 text-xs p-2 rounded-lg bg-slate-50 dark:bg-slate-900/50"
                  >
                    <span className="w-1.5 h-1.5 rounded-full bg-brand-500 shrink-0" />
                    <span className="text-slate-700 dark:text-slate-300 truncate">{c.label}</span>
                    <span className="text-slate-400 text-[10px] ml-auto shrink-0">{c.edgeLabel}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
