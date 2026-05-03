import { useEffect, useRef, useState, useCallback } from "react";
import cytoscape from "cytoscape";

const STATUS_COLORS = {
  active: "#22c55e",
  stale: "#f59e0b",
  deprecated: "#ef4444",
  superseded: "#6366f1",
};

const TEMPORAL_COLORS = {
  current: { bg: "#f59e0b", border: "#d97706", label: "Current" },
  past:    { bg: "#ef4444", border: "#dc2626", label: "Past" },
  future:  { bg: "#22c55e", border: "#16a34a", label: "Future" },
  unknown: { bg: "#94a3b8", border: "#64748b", label: "Unknown" },
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

// Strip common model-type prefixes that the containing box already communicates
function stripModelPrefix(name) {
  return String(name || "")
    .replace(/^(Action|Actions|Blocker|Blockers|Decision|Decisions|Risk|Risks|Outcome|Outcomes|Discussion|Fact|Task|Tasks|Feature|Features|Metric|Metrics|Meeting|Agent Session|AI step):\s*/i, "")
    .trim();
}

// ── CEO View presets ──────────────────────────────────────────────
const CEO_VIEWS = [
  { id: "all",        label: "All",            desc: "Full graph — every entity and relationship" },
  { id: "birdsEye",   label: "Bird's Eye",     desc: "Company → Product → Feature → Task → PR → Customer" },
  { id: "gaps",       label: "Gap Detector",   desc: "Highlights nodes with no connections — missing owners, orphaned tasks, unlinked decisions" },
  { id: "decisions",  label: "Decision Trail", desc: "Message → Meeting → Decision → PR → Feature" },
  { id: "aiSessions", label: "AI Sessions",    desc: "Agent sessions → decisions, files changed, bugs found, next steps" },
];

const CEO_VIEW_MODEL_PATTERNS = {
  birdsEye:   /^(company|product|feature|task|customer|user|pr|issue|repo|metric)/i,
  decisions:  /^(decision|meeting|message|email|document|slack|zoom|discussion)/i,
  aiSessions: /^(agent session|agent|claude|codex|opencode|chatgpt|ai session)/i,
};

// Derive a Cytoscape CSS class from a model name for entity-type shapes
function entityClass(modelName) {
  const k = (modelName || "").toLowerCase().trim();
  if (k.startsWith("decision"))                                                                   return "entity-decision";
  if (k.startsWith("risk"))                                                                       return "entity-risk";
  if (k.startsWith("task"))                                                                       return "entity-task";
  if (k.startsWith("metric"))                                                                     return "entity-metric";
  if (k.startsWith("company"))                                                                    return "entity-company";
  if (k === "agent session" || k === "claude" || k === "codex" || k === "opencode" || k.startsWith("agent")) return "entity-agent";
  if (k.startsWith("meeting"))                                                                    return "entity-meeting";
  if (k.startsWith("feature"))                                                                    return "entity-feature";
  if (k.startsWith("person") || k.startsWith("user") || k.startsWith("customer") || k.startsWith("team")) return "entity-person";
  return "";
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
    temporal: "",
  });
  const [building, setBuilding] = useState(false);
  const [buildResult, setBuildResult] = useState(null);
  const [agentStatus, setAgentStatus] = useState(null);
  const [showAiSettings, setShowAiSettings] = useState(false);
  const [aiSettings, setAiSettings] = useState(() => {
    try { return JSON.parse(localStorage.getItem("ce_ai_settings") || "{}"); }
    catch { return {}; }
  });
  const [tooltipNode, setTooltipNode] = useState(null);
  const [showAsk, setShowAsk] = useState(false);
  const [askQuery, setAskQuery] = useState("");
  const [askResult, setAskResult] = useState(null);
  const [askLoading, setAskLoading] = useState(false);
  const [askError, setAskError] = useState(null);
  const askInputRef = useRef(null);
  const [ceoView, setCeoView] = useState("all");

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

    const componentIds = new Set(components.map((c) => c.id));
    relationships = relationships.filter(
      (r) => componentIds.has(r.source_component_id) && componentIds.has(r.target_component_id)
    );

    return { models: allModels, components, relationships };
  }, [graphData, filters, viewMode, ceoView]);

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

    // Pre-compute visible models (those with at least one component) for use in layout
    const activeModelIds = new Set(components.map((c) => c.model_id));
    const visibleModels = models.filter((m) => activeModelIds.has(m.id));

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
      // Models become compound parent containers (empty models are already excluded via visibleModels)
      visibleModels.forEach((m) => {
        nodes.push({
          data: {
            id: `model:${m.id}`,
            label: m.name,
            fullLabel: m.name,
            type: "model",
            modelId: m.id,
            description: m.description || "",
            modelColor: modelColorMap[m.id] || "#6366f1",
          },
          classes: "model-node",
        });
      });

      // Components are children of their model compound node
      const modelNameById = new Map(models.map((m) => [m.id, m.name]));
      const connectedComponentIds = new Set();
      relationships.forEach((r) => {
        connectedComponentIds.add(r.source_component_id);
        connectedComponentIds.add(r.target_component_id);
      });

      components.forEach((c) => {
        const temporal = c.temporal || "unknown";
        const tc = TEMPORAL_COLORS[temporal] || TEMPORAL_COLORS.unknown;

        // GitHub-specific shape classes and label prefix
        const isGitHub = c.source_type === "github";
        const isPR = isGitHub && c.fact_type === "pull_request";
        const isIssue = isGitHub && c.fact_type === "issue";
        const mName = modelNameById.get(c.model_id) || "";
        const eClass = entityClass(mName);
        const isGap = ceoView === "gaps" && !connectedComponentIds.has(c.id);
        const classNames = [
          isPR ? "github-pr" : isIssue ? "github-issue" : "",
          eClass,
          isGap ? "gap-node" : "",
        ].filter(Boolean).join(" ");

        let labelPrefix = "";
        if (isPR) labelPrefix = "PR· ";
        else if (isIssue) labelPrefix = "# ";

        // Strip model-type prefix for display (box already communicates context)
        const cleanName = isGitHub ? c.name : stripModelPrefix(c.name);

        nodes.push({
          data: {
            id: c.id,
            parent: `model:${c.model_id}`,
            label: labelPrefix + shortLabel(cleanName, 4),
            fullLabel: (labelPrefix + c.name),
            type: "component",
            value: c.value,
            confidence: c.confidence,
            status: c.status,
            fact_type: c.fact_type,
            temporal,
            modelId: c.model_id,
            source_type: c.source_type,
            source_url: c.source_url,
            bgColor: tc.bg,
            borderColor: tc.border,
          },
          classes: classNames || undefined,
        });
      });

      // Relationship edges only — compound parent handles "contains" visually
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

    const isDark = document.documentElement.classList.contains("dark");
    const modelBg = isDark ? "rgba(255,255,255,0.11)" : "rgba(248,250,252,0.95)";
    const modelTextColor = isDark ? "#e2e8f0" : "#0f172a";
    const edgeLabelBg = isDark ? "#1e293b" : "#ffffff";

    const cy = cytoscape({
      container: containerRef.current,
      elements: { nodes, edges },
      style: [
        // ── Base node defaults ───────────────────────────────────
        {
          selector: "node",
          style: {
            label: "data(label)",
            "text-valign": "bottom",
            "text-halign": "center",
            "font-size": "7px",
            "font-weight": "600",
            color: "#475569",
            "background-color": "#cbd5e1",
            width: 26,
            height: 26,
            "border-width": 2,
            "border-color": "#94a3b8",
            "text-margin-y": 5,
            "text-wrap": "wrap",
            "text-max-width": 72,
          },
        },

        // ── MODEL — compound container node ──────────────────────
        {
          selector: ".model-node",
          style: {
            "background-color": modelBg,
            "background-opacity": 1,
            "border-color": "data(modelColor)",
            "border-width": 3,
            "border-opacity": 1,
            shape: "round-rectangle",
            padding: "38px",
            label: "data(label)",
            "text-valign": "top",
            "text-halign": "center",
            "text-margin-y": -16,
            "text-max-width": 160,
            "font-size": "12px",
            "font-weight": "800",
            "text-wrap": "wrap",
            color: modelTextColor,
            "text-background-color": modelBg,
            "text-background-opacity": 1,
            "text-background-padding": "4px",
            "text-background-shape": "round-rectangle",
            "text-border-opacity": 0,
          },
        },

        // ── COMPONENT — temporal-colored circles ─────────────────
        {
          selector: "node[type='component']",
          style: {
            "background-color": "data(bgColor)",
            "border-color": "data(borderColor)",
            "border-width": 2.5,
            width: 26,
            height: 26,
            shape: "ellipse",
            "font-size": "7.5px",
            "text-max-width": "88px",
            color: isDark ? "#e2e8f0" : "#1e293b",
          },
        },

        // ── GITHUB PR — diamond shape ─────────────────────────────
        {
          selector: ".github-pr",
          style: {
            shape: "diamond",
            width: 32,
            height: 32,
            "border-width": 3,
          },
        },

        // ── GITHUB ISSUE — rounded rectangle ─────────────────────
        {
          selector: ".github-issue",
          style: {
            shape: "round-rectangle",
            width: 36,
            height: 22,
            "border-width": 2.5,
          },
        },

        // ── ENTITY TYPE SHAPES ────────────────────────────────────
        { selector: ".entity-decision", style: { shape: "diamond",        width: 32, height: 32 } },
        { selector: ".entity-risk",     style: { shape: "triangle",       width: 32, height: 32 } },
        { selector: ".entity-task",     style: { shape: "tag",            width: 34, height: 22 } },
        { selector: ".entity-metric",   style: { shape: "barrel",         width: 28, height: 28 } },
        { selector: ".entity-company",  style: { shape: "hexagon",        width: 36, height: 36 } },
        { selector: ".entity-agent",    style: { shape: "star",           width: 36, height: 36 } },
        { selector: ".entity-meeting",  style: { shape: "pentagon",       width: 30, height: 30 } },
        { selector: ".entity-feature",  style: { shape: "round-rectangle", width: 38, height: 22 } },
        { selector: ".entity-person",   style: { shape: "ellipse",        width: 30, height: 30 } },

        // ── GAP NODE — isolated in Gap Detector view ──────────────
        {
          selector: ".gap-node",
          style: {
            opacity: 0.35,
            "border-style": "dashed",
            "border-width": 2.5,
            "border-color": "#ef4444",
          },
        },

        // ── Repo-view node types ──────────────────────────────────
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
          style: { width: 46, height: 34, "font-size": "8px", "font-weight": "800", "text-max-width": 92 },
        },
        {
          selector: "node[type='technology']",
          style: { width: 34, height: 28, "font-size": "8px", "text-max-width": 86 },
        },
        {
          selector: "node[type='file']",
          style: { width: 22, height: 22, "font-size": "7px", "text-max-width": 72 },
        },
        {
          selector: ".repo-node",
          style: {
            "background-color": "#1e293b",
            "border-color": "#475569",
            color: "#e2e8f0",
            width: 44,
            height: 44,
            shape: "round-rectangle",
            "font-size": "8px",
            "font-weight": "800",
          },
        },

        // ── RELATIONSHIP EDGES — visible, labeled arrows ──────────
        {
          selector: "edge[edgeType='relationship']",
          style: {
            width: 2,
            "line-color": "#818cf8",
            "target-arrow-color": "#818cf8",
            "target-arrow-shape": "triangle",
            "arrow-scale": 1,
            "curve-style": "bezier",
            label: "data(label)",
            "font-size": "8px",
            "font-weight": "600",
            color: "#6366f1",
            "text-rotation": "autorotate",
            "text-background-opacity": 1,
            "text-background-color": edgeLabelBg,
            "text-background-padding": "2px",
            "text-border-opacity": 0,
            "text-margin-y": -10,
            opacity: 0.9,
          },
        },

        // ── Repo-view edge defaults ───────────────────────────────
        {
          selector: "edge",
          style: {
            width: 1.5,
            "line-color": "#94a3b8",
            "target-arrow-color": "#94a3b8",
            "target-arrow-shape": "triangle",
            "arrow-scale": 0.8,
            "curve-style": "bezier",
            label: "data(label)",
            "font-size": "8px",
            color: "#64748b",
            "text-rotation": "autorotate",
            "text-margin-y": -10,
            opacity: 0.6,
          },
        },

        // ── Selection highlight ───────────────────────────────────
        {
          selector: "node[type='component']:selected, .github-pr:selected, .github-issue:selected",
          style: {
            "border-width": 3.5,
            "border-color": "#4f46e5",
            "background-color": "#4f46e5",
            color: "#ffffff",
          },
        },
        {
          selector: ".model-node:selected",
          style: {
            "border-width": 4,
            "border-color": "#4f46e5",
          },
        },
      ],
      layout: viewMode === "repo"
        ? { name: "preset", fit: true, padding: 110 }
        : (() => {
          // Preset layout: models in a grid, components in a circle inside each model
          const presetPositions = {};
          const cols = Math.max(2, Math.ceil(Math.sqrt(visibleModels.length)));
          const modelSpacing = 320;

          visibleModels.forEach((m, mi) => {
            const col = mi % cols;
            const row = Math.floor(mi / cols);
            const basex = (col - (cols - 1) / 2) * modelSpacing;
            const basey = row * modelSpacing;

            const mComps = components.filter((c) => c.model_id === m.id);
            const radius = mComps.length <= 1 ? 55 : Math.max(65, mComps.length * 20);
            mComps.forEach((c, ci) => {
              const angle = (ci / Math.max(1, mComps.length)) * 2 * Math.PI - Math.PI / 2;
              presetPositions[c.id] = {
                x: basex + radius * Math.cos(angle),
                y: basey + radius * Math.sin(angle),
              };
            });
            // If model is empty, give the compound node a fallback position
            if (mComps.length === 0) {
              presetPositions[`model:${m.id}`] = { x: basex, y: basey };
            }
          });

          return {
            name: "preset",
            positions: (node) => presetPositions[node.id()],
            fit: true,
            padding: 80,
          };
        })(),
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
          if (id !== lastHoveredId) {
            if (lastHoveredId) {
              const prev = cy.getElementById(lastHoveredId);
              const pf = prev.data("fullLabel");
              if (pf) prev.data("label", shortLabel(pf));
            }
            const fl = found.data("fullLabel");
            if (fl) found.data("label", fl);
            lastHoveredId = id;
          }
          setTooltipNode({ x: rx, y: ry, text: found.data("fullLabel") || found.data("label") });
        } else {
          if (lastHoveredId) {
            const prev = cy.getElementById(lastHoveredId);
            const pf = prev.data("fullLabel");
            if (pf) prev.data("label", shortLabel(pf));
            lastHoveredId = null;
          }
          setTooltipNode(null);
        }
      });
    }

    function onMouseLeave() {
      if (rafId) { cancelAnimationFrame(rafId); rafId = null; }
      if (lastHoveredId) {
        const prev = cy.getElementById(lastHoveredId);
        const pf = prev.data("fullLabel");
        if (pf) prev.data("label", shortLabel(pf));
        lastHoveredId = null;
      }
      setTooltipNode(null);
    }

    containerEl.addEventListener("mousemove", onMouseMove);
    containerEl.addEventListener("mouseleave", onMouseLeave);

    return () => {
      containerEl.removeEventListener("mousemove", onMouseMove);
      containerEl.removeEventListener("mouseleave", onMouseLeave);
      cy.destroy();
    };
  }, [graphData, filteredData, viewMode, ceoView]);

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
            <select
              value={filters.temporal}
              onChange={(e) => setFilters((f) => ({ ...f, temporal: e.target.value }))}
              className="text-xs px-3 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-300"
            >
              <option value="">All time</option>
              <option value="current">Current (needs now)</option>
              <option value="future">Future (will do)</option>
              <option value="past">Past (was done)</option>
              <option value="unknown">Unknown</option>
            </select>
          </div>
          )}
          <div className="ml-auto flex items-center gap-2">
            {agentStatus && (
              <span className={`text-[10px] font-bold uppercase tracking-wider px-2 py-1 rounded-full ${aiSettings.api_key || agentStatus.llm_enabled ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400" : "bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400"}`}>
                {aiSettings.api_key ? `AI: ${aiSettings.model || "gpt-4o"}` : agentStatus.llm_enabled ? `LLM: ${agentStatus.extraction_model}` : "Regex extraction"}
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
          <div className="flex items-center gap-2.5 mb-3 -mt-1 flex-wrap">
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
            {ceoView !== "all" && (
              <span className="text-[10px] text-slate-400 italic hidden sm:inline">{CEO_VIEWS.find((v) => v.id === ceoView)?.desc}</span>
            )}
          </div>
        )}

        {buildResult && !buildResult.error && (
          <div className="mb-3 flex items-start gap-3 px-4 py-3 rounded-xl bg-emerald-50 dark:bg-emerald-900/20 border border-emerald-200 dark:border-emerald-800 text-xs">
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
          <div className="mb-3 px-4 py-3 rounded-xl bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 text-xs text-red-700 dark:text-red-400 flex items-center justify-between">
            <span>Build failed: {buildResult.error}</span>
            <button onClick={() => setBuildResult(null)} className="font-bold ml-4">✕</button>
          </div>
        )}

        <div className="flex-1 relative rounded-2xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 min-h-0">
          <div ref={containerRef} className="absolute inset-0 rounded-2xl" />

          {/* Persistent legend — top-right corner of graph canvas */}
          <div className="pointer-events-none absolute top-3 right-3 z-10 bg-white/90 dark:bg-slate-800/90 backdrop-blur-sm rounded-xl border border-slate-200 dark:border-slate-700 px-3 py-2.5 shadow-sm space-y-2.5 max-w-[152px]">
            <div>
              <p className="text-[9px] font-bold uppercase tracking-widest text-slate-400 mb-1.5">Node color — time</p>
              <div className="flex flex-col gap-1">
                {[
                  { key: "future",  label: "Future"  },
                  { key: "current", label: "Current" },
                  { key: "past",    label: "Past"    },
                  { key: "unknown", label: "Unknown" },
                ].map(({ key, label }) => (
                  <div key={key} className="flex items-center gap-1.5">
                    <span
                      className="w-2.5 h-2.5 rounded-full shrink-0 border"
                      style={{ backgroundColor: TEMPORAL_COLORS[key].bg, borderColor: TEMPORAL_COLORS[key].border }}
                    />
                    <span className="text-[10px] text-slate-600 dark:text-slate-400">{label}</span>
                  </div>
                ))}
              </div>
            </div>
            <div>
              <p className="text-[9px] font-bold uppercase tracking-widest text-slate-400 mb-1.5">Node shape — type</p>
              <div className="flex flex-col gap-1">
                {[
                  { shape: "◆", label: "Decision" },
                  { shape: "▲", label: "Risk / Blocker" },
                  { shape: "⬟", label: "Task" },
                  { shape: "★", label: "AI Session" },
                  { shape: "⬡", label: "Company" },
                  { shape: "⬠", label: "Meeting" },
                  { shape: "▬", label: "Feature / Issue" },
                  { shape: "●", label: "Person / User" },
                ].map(({ shape, label }) => (
                  <div key={label} className="flex items-center gap-1.5">
                    <span className="text-[11px] text-slate-500 dark:text-slate-400 w-3 text-center shrink-0">{shape}</span>
                    <span className="text-[10px] text-slate-600 dark:text-slate-400">{label}</span>
                  </div>
                ))}
              </div>
            </div>
            <div>
              <p className="text-[9px] font-bold uppercase tracking-widest text-slate-400 mb-1.5">Box border — domain</p>
              <div className="flex items-center gap-1.5">
                <span className="w-5 h-3.5 rounded shrink-0 border-2 border-indigo-500 bg-transparent" />
                <span className="text-[10px] text-slate-600 dark:text-slate-400">Each color = one domain</span>
              </div>
            </div>
          </div>

          {tooltipNode && (
            <div
              className="pointer-events-none absolute z-10 bg-slate-900 text-white text-xs px-2.5 py-1.5 rounded-lg shadow-lg max-w-[220px] leading-snug break-words"
              style={{ left: tooltipNode.x + 14, top: tooltipNode.y - 8, transform: "translateY(-100%)" }}
            >
              {tooltipNode.text}
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
                      <div>
                        <div className="flex items-center gap-2 mb-1">
                          <span className="text-[10px] font-bold uppercase tracking-widest text-slate-400">Answer</span>
                          {askResult.confidence != null && (
                            <span className="text-[10px] font-bold px-1.5 py-0.5 rounded-full bg-brand-100 dark:bg-brand-900/30 text-brand-700 dark:text-brand-300">
                              {Math.round(askResult.confidence * 100)}%
                            </span>
                          )}
                        </div>
                        <p className="text-sm text-slate-800 dark:text-slate-200 leading-relaxed">{askResult.answer}</p>
                      </div>
                      {askResult.components?.length > 0 && (
                        <div>
                          <p className="text-[10px] font-bold uppercase tracking-widest text-slate-400 mb-1.5">Cited facts ({askResult.components.length})</p>
                          <div className="flex flex-col gap-1.5">
                            {askResult.components.slice(0, 5).map((c, i) => (
                              <div key={c.id || i} className="flex items-start gap-2 p-2 rounded-lg bg-slate-50 dark:bg-slate-900/60">
                                <span className="w-4 h-4 rounded bg-brand-100 dark:bg-brand-900/40 flex items-center justify-center text-[9px] font-bold text-brand-700 dark:text-brand-300 shrink-0 mt-0.5">{i + 1}</span>
                                <div className="min-w-0">
                                  <p className="text-[11px] font-semibold text-slate-700 dark:text-slate-300">{stripModelPrefix(c.name)}</p>
                                  <p className="text-[10px] text-slate-500 dark:text-slate-400">{c.value}</p>
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

      {selectedNode && (
        <div className="w-72 shrink-0 bg-white dark:bg-slate-800 rounded-2xl border border-slate-200 dark:border-slate-700 p-5 overflow-y-auto">
          <button
            onClick={() => setSelectedNode(null)}
            className="float-right text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 text-xs font-bold"
          >
            close
          </button>
          <h3 className="text-sm font-bold text-slate-900 dark:text-white mb-2 pr-6">
            {selectedNode.fullLabel || selectedNode.label}
          </h3>
          <div className="flex flex-wrap gap-1.5 mb-3">
            <span className="inline-block text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full bg-brand-100 dark:bg-brand-900/30 text-brand-700 dark:text-brand-300">
              {selectedNode.fact_type || "fact"}
            </span>
            {selectedNode.temporal && selectedNode.temporal !== "unknown" && (() => {
              const tc = TEMPORAL_COLORS[selectedNode.temporal];
              return (
                <span
                  className="inline-block text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full text-white"
                  style={{ backgroundColor: tc?.bg }}
                >
                  {tc?.label || selectedNode.temporal}
                </span>
              );
            })()}
          </div>
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
            {selectedNode.temporal && (
              <div className="flex justify-between text-xs">
                <span className="text-slate-500">Timeline</span>
                <span className="font-bold text-slate-700 dark:text-slate-300 capitalize">{selectedNode.temporal}</span>
              </div>
            )}
            {selectedNode.source_type && (
              <div className="flex justify-between text-xs">
                <span className="text-slate-500">Source</span>
                <span className="font-bold text-slate-700 dark:text-slate-300 capitalize">{selectedNode.source_type.replace(/_/g, " ")}</span>
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
          <div className="mt-4 pt-4 border-t border-slate-100 dark:border-slate-700 space-y-3">
            <div>
              <p className="text-[10px] font-bold uppercase tracking-widest text-slate-400 mb-2">Temporal</p>
              <div className="flex flex-col gap-1.5">
                <div className="flex items-center gap-2 text-xs">
                  <span className="w-3 h-3 rounded-full shrink-0 border-2" style={{ backgroundColor: TEMPORAL_COLORS.future.bg, borderColor: TEMPORAL_COLORS.future.border }} />
                  <span className="text-slate-600 dark:text-slate-400">Future — planned / not yet built</span>
                </div>
                <div className="flex items-center gap-2 text-xs">
                  <span className="w-3 h-3 rounded-full shrink-0 border-2" style={{ backgroundColor: TEMPORAL_COLORS.current.bg, borderColor: TEMPORAL_COLORS.current.border }} />
                  <span className="text-slate-600 dark:text-slate-400">Current — active / in use</span>
                </div>
                <div className="flex items-center gap-2 text-xs">
                  <span className="w-3 h-3 rounded-full shrink-0 border-2" style={{ backgroundColor: TEMPORAL_COLORS.past.bg, borderColor: TEMPORAL_COLORS.past.border }} />
                  <span className="text-slate-600 dark:text-slate-400">Past — completed / outdated</span>
                </div>
              </div>
            </div>
            <div>
              <p className="text-[10px] font-bold uppercase tracking-widest text-slate-400 mb-2">Node types</p>
              <div className="flex flex-col gap-1.5">
                <div className="flex items-center gap-2 text-xs">
                  <span className="w-8 h-4 rounded shrink-0 border-2 border-indigo-500 bg-indigo-50/30 dark:bg-indigo-900/20" />
                  <span className="text-slate-600 dark:text-slate-400">Model (domain container)</span>
                </div>
                <div className="flex items-center gap-2 text-xs">
                  <span className="w-3 h-3 rounded-full shrink-0 bg-slate-400" />
                  <span className="text-slate-600 dark:text-slate-400">Component (atomic fact)</span>
                </div>
                <div className="flex items-center gap-2 text-xs">
                  <span className="w-4 h-4 shrink-0 rotate-45 bg-slate-400" style={{ borderRadius: "2px" }} />
                  <span className="text-slate-600 dark:text-slate-400">GitHub PR (diamond)</span>
                </div>
                <div className="flex items-center gap-2 text-xs">
                  <span className="w-4 h-2.5 rounded shrink-0 bg-slate-400" />
                  <span className="text-slate-600 dark:text-slate-400">GitHub Issue (pill)</span>
                </div>
              </div>
            </div>
            <div>
              <p className="text-[10px] font-bold uppercase tracking-widest text-slate-400 mb-2">Edges</p>
              <div className="flex flex-col gap-1.5">
                <div className="flex items-center gap-2 text-xs">
                  <span className="w-6 shrink-0 border-t-2 border-indigo-400" />
                  <span className="text-slate-600 dark:text-slate-400">Relationship (labeled)</span>
                </div>
              </div>
            </div>
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
