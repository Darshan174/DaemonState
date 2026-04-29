import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import GraphVisualizer from "../components/GraphVisualizer";
import RelationshipEdge from "../components/RelationshipEdge";
import StatusView from "../components/StatusView";
import MockBadge from "../components/MockBadge";
import { useKnowledgeGraph } from "../api/hooks";
import { graphNodes as mockNodes, graphEdges as mockEdges } from "../fixtures/mockData";

const NODE_TYPES = ["all", "model", "source", "component"];

export default function KnowledgeGraph() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [search, setSearch] = useState("");
  const [typeFilter, setTypeFilter] = useState("all");
  const [viewMode, setViewMode] = useState("workspace");
  const [signalMode, setSignalMode] = useState("all");
  const [selectedNodeId, setSelectedNodeId] = useState(null);
  const [hoveredNodeId, setHoveredNodeId] = useState(null);
  const { data, isMock, ...query } = useKnowledgeGraph({
    viewMode,
    selectedNodeId,
  });

  const status = <StatusView query={{ data, ...query }} empty="No graph data yet." />;
  const graphNodes =
    query.isLoading || query.isError ? [] : data?.nodes ?? mockNodes;
  const graphEdges =
    query.isLoading || query.isError ? [] : data?.edges ?? mockEdges;
  const nodesById = useMemo(
    () => new Map(graphNodes.map((node) => [node.id, node])),
    [graphNodes],
  );
  const nodeDegree = useMemo(() => {
    const degree = new Map(graphNodes.map((node) => [node.id, 0]));
    for (const edge of graphEdges) {
      degree.set(edge.source, (degree.get(edge.source) ?? 0) + 1);
      degree.set(edge.target, (degree.get(edge.target) ?? 0) + 1);
    }
    return degree;
  }, [graphEdges, graphNodes]);
  const graphStats = useMemo(() => buildGraphStats(graphNodes, graphEdges), [graphEdges, graphNodes]);

  const signalNodeIds = useMemo(() => {
    if (signalMode !== "signal") return null;
    const ranked = [...graphNodes]
      .filter(
        (node) =>
          node.type === "model" ||
          node.reviewStatus === "needs_review" ||
          node.isStale ||
          node.temporalState === "historical" ||
          Number(node.sourceCount ?? 0) >= 2 ||
          Number(nodeDegree.get(node.id) ?? 0) >= 2,
      )
      .sort((a, b) => (nodeDegree.get(b.id) ?? 0) - (nodeDegree.get(a.id) ?? 0))
      .slice(0, 80)
      .map((node) => node.id);
    if (selectedNodeId) ranked.push(selectedNodeId);
    const signalIds = new Set(ranked);
    for (const edge of graphEdges) {
      if (signalIds.has(edge.source)) signalIds.add(edge.target);
      if (signalIds.has(edge.target)) signalIds.add(edge.source);
    }
    return signalIds;
  }, [graphEdges, graphNodes, nodeDegree, selectedNodeId, signalMode]);

  useEffect(() => {
    setSearch(searchParams.get("q") ?? "");
    setTypeFilter(searchParams.get("type") ?? "all");
    setViewMode(searchParams.get("view") === "local" ? "local" : "workspace");
    setSignalMode(searchParams.get("signal") === "1" ? "signal" : "all");
  }, [searchParams]);

  const filteredNodes = graphNodes.filter((n) => {
    const matchesSearch =
      !search || n.label.toLowerCase().includes(search.toLowerCase());
    const matchesType = typeFilter === "all" || n.type === typeFilter;
    const matchesSignal = !signalNodeIds || signalNodeIds.has(n.id);
    return matchesSearch && matchesType && matchesSignal;
  });

  const filteredNodeIds = new Set(filteredNodes.map((n) => n.id));

  const baseEdges = graphEdges.filter(
    (e) => filteredNodeIds.has(e.source) && filteredNodeIds.has(e.target),
  );

  useEffect(() => {
    if (!selectedNodeId && filteredNodes[0]?.id) {
      setSelectedNodeId(filteredNodes[0].id);
      return;
    }
    if (selectedNodeId && !filteredNodeIds.has(selectedNodeId)) {
      setSelectedNodeId(filteredNodes[0]?.id ?? null);
    }
  }, [filteredNodes, filteredNodeIds, selectedNodeId]);

  useEffect(() => {
    const focus = searchParams.get("focus");
    if (!focus) return;
    const normalized = focus.trim().toLowerCase();
    const exactMatch =
      filteredNodes.find((node) => node.label.trim().toLowerCase() === normalized) ??
      filteredNodes.find((node) => node.label.toLowerCase().includes(normalized));
    if (exactMatch && exactMatch.id !== selectedNodeId) {
      setSelectedNodeId(exactMatch.id);
    }
  }, [filteredNodes, searchParams, selectedNodeId]);

  const localNodeIds = useMemo(() => {
    if (viewMode !== "local" || !selectedNodeId) {
      return null;
    }
    const neighbors = new Set([selectedNodeId]);
    for (const edge of baseEdges) {
      if (edge.source === selectedNodeId) neighbors.add(edge.target);
      if (edge.target === selectedNodeId) neighbors.add(edge.source);
    }
    return neighbors;
  }, [baseEdges, selectedNodeId, viewMode]);

  const visibleNodes = useMemo(() => {
    if (!localNodeIds) return filteredNodes;
    return filteredNodes.filter((node) => localNodeIds.has(node.id));
  }, [filteredNodes, localNodeIds]);

  const visibleNodeIds = new Set(visibleNodes.map((node) => node.id));
  const filteredEdges = baseEdges.filter(
    (edge) => visibleNodeIds.has(edge.source) && visibleNodeIds.has(edge.target),
  );

  const selectedNode = selectedNodeId ? nodesById.get(selectedNodeId) : null;
  const selectedEdges = selectedNode
    ? filteredEdges.filter(
        (edge) => edge.source === selectedNode.id || edge.target === selectedNode.id,
      )
    : [];
  const relatedNodes = selectedEdges
    .map((edge) => nodesById.get(edge.source === selectedNode?.id ? edge.target : edge.source))
    .filter(Boolean);

  function updateGraphParams(nextParams) {
    const next = new URLSearchParams(searchParams);
    Object.entries(nextParams).forEach(([key, value]) => {
      if (value == null || value === "" || value === "all") {
        next.delete(key);
      } else {
        next.set(key, value);
      }
    });
    setSearchParams(next, { replace: true });
  }

  if (query.isLoading || query.isError) {
    return <div className="max-w-6xl mx-auto">{status}</div>;
  }

  return (
    <div className="max-w-6xl mx-auto space-y-7">
      <div>
        <div className="flex items-center gap-3">
          <h2 className="text-3xl font-bold tracking-tight text-slate-950 dark:text-white">Knowledge Graph</h2>
          {isMock && <MockBadge />}
        </div>
        {isMock && (
          <p className="mt-2 text-sm leading-6 text-slate-500 dark:text-slate-400">
            Showing demo data until live workspace graph data is available.
          </p>
        )}
      </div>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <GraphStat label="Models" value={graphStats.models} />
        <GraphStat label="Components" value={graphStats.components} />
        <GraphStat label="Sources" value={graphStats.sources} />
        <GraphStat label="Relationships" value={graphStats.relationships} />
      </div>

      <div className="rounded-xl border border-gray-200 dark:border-gray-800/50 bg-white dark:bg-slate-800 p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <button
              type="button"
              onClick={() => {
                setViewMode("workspace");
                updateGraphParams({ view: "workspace" });
              }}
              className={`rounded-full px-3 py-1.5 font-medium transition-colors ${
                viewMode === "workspace"
                  ? "bg-brand-600 text-white"
                  : "border border-gray-200 dark:border-gray-800/50 bg-white dark:bg-slate-800 text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:bg-gray-900/30"
              }`}
            >
              Workspace graph
            </button>
            <button
              type="button"
              onClick={() => {
                if (!selectedNodeId) return;
                setViewMode("local");
                updateGraphParams({
                  view: "local",
                  focus: nodesById.get(selectedNodeId)?.label ?? null,
                });
              }}
              disabled={!selectedNodeId}
              className={`rounded-full px-3 py-1.5 font-medium transition-colors ${
                viewMode === "local"
                  ? "bg-slate-900 text-white"
                  : "border border-gray-200 dark:border-gray-800/50 bg-white dark:bg-slate-800 text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:bg-gray-900/30 disabled:cursor-not-allowed disabled:opacity-40"
              }`}
            >
              Local graph
            </button>
            <button
              type="button"
              onClick={() => {
                const nextMode = signalMode === "signal" ? "all" : "signal";
                setSignalMode(nextMode);
                updateGraphParams({ signal: nextMode === "signal" ? "1" : null });
              }}
              className={`rounded-full px-3 py-1.5 font-medium transition-colors ${
                signalMode === "signal"
                  ? "bg-amber-600 text-white"
                  : "border border-gray-200 dark:border-gray-800/50 bg-white dark:bg-slate-800 text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:bg-gray-900/30"
              }`}
            >
              High-signal
            </button>
          </div>
          <div className="flex flex-wrap items-center gap-3 text-xs">
            <span className="rounded-full border border-amber-200 bg-amber-50 px-2.5 py-1 font-medium text-amber-700 dark:border-amber-800/50 dark:bg-amber-900/30 dark:text-amber-300">
              {graphStats.reviewItems} review
            </span>
            <span className="rounded-full border border-violet-200 bg-violet-50 px-2.5 py-1 font-medium text-violet-700 dark:border-violet-800/50 dark:bg-violet-900/30 dark:text-violet-300">
              {graphStats.historical} historical
            </span>
            <Link to="/app/models" className="font-medium text-brand-700 dark:text-brand-400 hover:text-brand-800 dark:text-brand-300">
              Models
            </Link>
            <Link to="/app/sources" className="font-medium text-brand-700 dark:text-brand-400 hover:text-brand-800 dark:text-brand-300">
              Sources
            </Link>
          </div>
        </div>
      </div>

      {/* ── Controls ────────────────────────────── */}
      <div className="flex flex-wrap items-center gap-3">
        <input
          type="text"
          placeholder="Search nodes..."
          value={search}
          onChange={(e) => {
            const nextValue = e.target.value;
            setSearch(nextValue);
            updateGraphParams({ q: nextValue });
          }}
          aria-label="Search graph nodes"
          className="px-3 py-2 text-sm border border-gray-200 dark:border-gray-800/50 rounded-lg w-full sm:w-64 focus:outline-none focus:ring-2 focus:ring-brand-500/40"
        />
        <div className="flex gap-1">
          {NODE_TYPES.map((t) => (
            <button
              key={t}
              onClick={() => {
                setTypeFilter(t);
                updateGraphParams({ type: t });
              }}
              className={`px-3 py-1.5 text-xs rounded-lg border transition-colors ${
                typeFilter === t
                  ? "bg-brand-600 text-white border-brand-600"
                  : "bg-white dark:bg-slate-800 text-gray-600 dark:text-gray-400 border-gray-200 dark:border-gray-800/50 hover:bg-gray-50 dark:bg-gray-900/30"
              }`}
            >
              {t === "all" ? "All types" : t}
            </button>
          ))}
        </div>
        <span className="ml-auto text-xs text-gray-400">
          {visibleNodes.length}/{graphNodes.length} nodes &middot; {filteredEdges.length}/{graphEdges.length} edges
        </span>
      </div>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="h-[460px]">
          <GraphVisualizer
            nodes={visibleNodes}
            edges={filteredEdges}
            selectedNodeId={selectedNodeId}
            hoveredNodeId={hoveredNodeId}
            onNodeSelect={(nodeId) => {
              setSelectedNodeId(nodeId);
              if (nodeId) {
                setViewMode("local");
                updateGraphParams({
                  focus: nodesById.get(nodeId)?.label ?? null,
                  view: "local",
                });
              } else {
                updateGraphParams({
                  focus: null,
                  view: "workspace",
                });
              }
            }}
            onNodeHover={setHoveredNodeId}
          />
        </div>

        <div className="rounded-xl border border-gray-200 dark:border-gray-800/50 bg-white dark:bg-slate-800 p-5">
          <div className="flex items-center justify-between gap-3">
            <div>
              <h3 className="text-sm font-semibold text-gray-800 dark:text-gray-300">Inspector</h3>
              <p className="mt-1 text-xs text-gray-400">
                Click a node to inspect its nearby graph.
              </p>
            </div>
            {selectedNode && (
              <button
                type="button"
                onClick={() => {
                  setViewMode("workspace");
                  updateGraphParams({ view: "workspace" });
                }}
                className="text-xs font-medium text-brand-700 dark:text-brand-400 hover:text-brand-800 dark:text-brand-300"
              >
                Back to workspace
              </button>
            )}
          </div>

          {!selectedNode ? (
            <p className="mt-6 text-sm text-gray-500">
              No node selected yet. Pick a decision, source, or component to see its local graph.
            </p>
          ) : (
            <div className="mt-5 space-y-5">
              <div>
                <span className="inline-flex rounded-full border border-gray-200 dark:border-gray-800/50 bg-gray-50 dark:bg-gray-900/30 px-2.5 py-1 text-[11px] font-medium uppercase tracking-[0.08em] text-gray-500">
                  {selectedNode.type}
                </span>
                <h4 className="mt-3 text-base font-semibold text-gray-900 dark:text-gray-200">{selectedNode.label}</h4>
                <p className="mt-1 text-xs text-gray-500">
                  {viewMode === "local"
                    ? "Showing first-degree neighborhood around this node."
                    : "Selected from the workspace graph."}
                </p>
                <div className="mt-4 flex flex-col gap-2 border-t border-gray-100 dark:border-gray-800/30 pt-4">
                  {selectedNode.type === "source" && (
                    <Link
                      to={`/app/sources/${selectedNode.id}`}
                      className="block w-full rounded-lg bg-brand-600 px-4 py-2 text-center text-sm font-semibold text-white shadow-sm transition-colors hover:bg-brand-500"
                    >
                      Inspect source details
                    </Link>
                  )}
                  {selectedNode.type === "model" && (
                    <Link
                      to={`/app/model/${selectedNode.id}`}
                      className="block w-full rounded-lg bg-brand-600 px-4 py-2 text-center text-sm font-semibold text-white shadow-sm transition-colors hover:bg-brand-500"
                    >
                      Inspect model facts
                    </Link>
                  )}
                  <Link
                    to={selectedNode.reviewItemId 
                      ? `/app/review/${selectedNode.reviewItemId}` 
                      : selectedNode.type === "source"
                        ? `/app/review?source_id=${selectedNode.id}`
                        : `/app/review?search=${encodeURIComponent(selectedNode.label)}`}
                    className="block w-full rounded-lg border border-gray-200 dark:border-gray-800/50 bg-white dark:bg-slate-800 px-4 py-2 text-center text-sm font-medium text-gray-700 dark:text-gray-400 transition-colors hover:bg-gray-50 dark:bg-gray-900/30"
                  >
                    Review trust state
                  </Link>
                </div>
              </div>

              <div>
                <h5 className="text-xs font-semibold uppercase tracking-[0.08em] text-gray-500">
                  Linked nodes
                </h5>
                {relatedNodes.length === 0 ? (
                  <p className="mt-2 text-sm text-gray-500">No linked nodes in the current graph filters.</p>
                ) : (
                  <div className="mt-2 flex flex-wrap gap-2">
                    {relatedNodes.map((node) => (
                      <button
                        key={node.id}
                        type="button"
                        onClick={() => {
                          setSelectedNodeId(node.id);
                          setViewMode("local");
                          updateGraphParams({
                            focus: node.label,
                            view: "local",
                          });
                        }}
                        className="rounded-full border border-gray-200 dark:border-gray-800/50 bg-gray-50 dark:bg-gray-900/30 px-3 py-1.5 text-xs font-medium text-gray-700 dark:text-gray-400 transition-colors hover:border-brand-200 dark:border-brand-800/50 hover:bg-brand-50 dark:bg-brand-900/30 hover:text-brand-800 dark:text-brand-300"
                      >
                        {node.label}
                      </button>
                    ))}
                  </div>
                )}
              </div>

              <div>
                <h5 className="text-xs font-semibold uppercase tracking-[0.08em] text-gray-500">
                  Connected edges
                </h5>
                {selectedEdges.length === 0 ? (
                  <p className="mt-2 text-sm text-gray-500">No visible edges from this node.</p>
                ) : (
                  <div className="mt-2 space-y-2">
                    {selectedEdges.map((edge) => {
                      const src = nodesById.get(edge.source);
                      const tgt = nodesById.get(edge.target);
                      return (
                        <RelationshipEdge
                          key={`${edge.source}-${edge.target}-${edge.label}`}
                          sourceLabel={src?.label}
                          targetLabel={tgt?.label}
                          label={edge.label}
                        />
                      );
                    })}
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* ── Edge list ───────────────────────────── */}
      <div className="bg-white dark:bg-slate-800 rounded-xl border border-gray-200 dark:border-gray-800/50 p-5">
        <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-400 mb-3">
          {selectedNode ? "Visible relationships" : "Relationships"}
        </h3>
        {filteredEdges.length === 0 ? (
          <div className="space-y-2">
            <p className="text-sm text-gray-400">No relationships match your filters.</p>
            <p className="text-xs text-gray-500">
              If the graph still looks empty after syncing sources, inspect Models and Review to confirm components and relationships have actually been extracted.
            </p>
          </div>
        ) : (
          <div className="divide-y divide-gray-100">
            {filteredEdges.map((e) => {
              const src = graphNodes.find((n) => n.id === e.source);
              const tgt = graphNodes.find((n) => n.id === e.target);
              return (
                <RelationshipEdge
                  key={`${e.source}-${e.target}`}
                  sourceLabel={src?.label}
                  targetLabel={tgt?.label}
                  label={e.label}
                />
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

function buildGraphStats(nodes, edges) {
  return {
    models: nodes.filter((node) => node.type === "model").length,
    components: nodes.filter((node) => node.type === "component").length,
    sources: nodes.filter((node) => node.type === "source").length,
    relationships: edges.length,
    reviewItems: nodes.filter((node) => node.reviewStatus === "needs_review").length,
    historical: nodes.filter((node) => node.temporalState === "historical" || node.isStale).length,
  };
}

function GraphStat({ label, value }) {
  return (
    <div className="rounded-xl border border-gray-200 bg-white px-4 py-3 dark:border-gray-800/50 dark:bg-slate-800">
      <p className="text-[11px] font-semibold uppercase tracking-wide text-gray-400">{label}</p>
      <p className="mt-1 text-2xl font-semibold text-gray-900 dark:text-gray-100">{value}</p>
    </div>
  );
}
