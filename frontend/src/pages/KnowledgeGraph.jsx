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

  useEffect(() => {
    setSearch(searchParams.get("q") ?? "");
    setTypeFilter(searchParams.get("type") ?? "all");
    setViewMode(searchParams.get("view") === "local" ? "local" : "workspace");
  }, [searchParams]);

  const filteredNodes = graphNodes.filter((n) => {
    const matchesSearch =
      !search || n.label.toLowerCase().includes(search.toLowerCase());
    const matchesType = typeFilter === "all" || n.type === typeFilter;
    return matchesSearch && matchesType;
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
    <div className="max-w-6xl mx-auto space-y-6">
      <div>
        <div className="flex items-center gap-3">
          <h2 className="text-lg font-semibold text-gray-800">Graph Explorer</h2>
          {isMock && <MockBadge />}
        </div>
        {isMock && (
          <p className="text-xs text-gray-400 mt-1">
            Visual map of decisions, sources, and relationships. Showing demo data — live graph is coming in a future phase.
          </p>
        )}
      </div>

      <div className="rounded-xl border border-gray-200 bg-white p-4">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h3 className="text-sm font-semibold text-gray-700">How to use this graph</h3>
            <p className="text-xs text-gray-400 mt-1">
              Use the workspace graph to scan the whole knowledge space, then click into a node to switch into a local graph around that object. This works best for tracing a decision back to its sources and nearby blockers.
            </p>
          </div>
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
                  : "border border-gray-200 bg-white text-gray-600 hover:bg-gray-50"
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
                  : "border border-gray-200 bg-white text-gray-600 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-40"
              }`}
            >
              Local graph
            </button>
            <Link to="/app/models" className="font-medium text-brand-700 hover:text-brand-800">
              Models
            </Link>
            <Link to="/app/sources" className="font-medium text-brand-700 hover:text-brand-800">
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
          className="px-3 py-2 text-sm border border-gray-200 rounded-lg w-full sm:w-64 focus:outline-none focus:ring-2 focus:ring-brand-500/40"
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
                  : "bg-white text-gray-600 border-gray-200 hover:bg-gray-50"
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

        <div className="rounded-xl border border-gray-200 bg-white p-5">
          <div className="flex items-center justify-between gap-3">
            <div>
              <h3 className="text-sm font-semibold text-gray-800">Inspector</h3>
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
                className="text-xs font-medium text-brand-700 hover:text-brand-800"
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
                <span className="inline-flex rounded-full border border-gray-200 bg-gray-50 px-2.5 py-1 text-[11px] font-medium uppercase tracking-[0.08em] text-gray-500">
                  {selectedNode.type}
                </span>
                <h4 className="mt-3 text-base font-semibold text-gray-900">{selectedNode.label}</h4>
                <p className="mt-1 text-xs text-gray-500">
                  {viewMode === "local"
                    ? "Showing first-degree neighborhood around this node."
                    : "Selected from the workspace graph."}
                </p>
                <div className="mt-4 flex flex-col gap-2 border-t border-gray-100 pt-4">
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
                    to={selectedNode.type === "source"
                      ? `/app/review?source_id=${selectedNode.id}`
                      : `/app/review?search=${encodeURIComponent(selectedNode.label)}`}
                    className="block w-full rounded-lg border border-gray-200 bg-white px-4 py-2 text-center text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50"
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
                        className="rounded-full border border-gray-200 bg-gray-50 px-3 py-1.5 text-xs font-medium text-gray-700 transition-colors hover:border-brand-200 hover:bg-brand-50 hover:text-brand-800"
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
      <div className="bg-white rounded-xl border border-gray-200 p-5">
        <h3 className="text-sm font-semibold text-gray-700 mb-3">
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
