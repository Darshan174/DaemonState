import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  AlertTriangle,
  CheckCircle2,
  ExternalLink,
  GitBranch,
  Info,
  Loader2,
  Lock,
  Minus,
  MoreHorizontal,
  Plus,
  RefreshCw,
  RotateCcw,
  Search,
  Unlock,
  X,
} from "lucide-react";
import {
  buildEvidenceGraph,
  cardDisplayLine,
  issueLabel,
  observedRemoteState,
  pullRequestLabel,
  relevanceLabel,
  sessionIdentity,
  TONE_CLASSES,
} from "../digest";

const INITIAL_LINK_LIMIT = 4;

export default function DigestBoard({
  digest,
  workspaceName,
  generatedAt,
  onBuild,
  building = false,
  buildResult = null,
  buildError = null,
  onSelectCard,
}) {
  const projection = useMemo(() => buildEvidenceGraph(digest), [digest]);
  const nodeById = useMemo(
    () => new Map(projection.nodes.map((node) => [node.id, node])),
    [projection.nodes],
  );
  const [selectedId, setSelectedId] = useState(null);
  const [query, setQuery] = useState("");
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [actionsOpen, setActionsOpen] = useState(false);
  const [expandedLanes, setExpandedLanes] = useState(() => new Set());
  const [linksExpanded, setLinksExpanded] = useState(false);
  const [layoutMode, setLayoutMode] = useState("auto");
  const [locked, setLocked] = useState(true);
  const [zoom, setZoom] = useState(1);
  const [nodeOffsets, setNodeOffsets] = useState({});
  const [hiddenLanes, setHiddenLanes] = useState(() => new Set());

  useEffect(() => {
    setSelectedId(null);
    setQuery("");
    setDetailsOpen(false);
    setActionsOpen(false);
    setExpandedLanes(new Set());
    setLinksExpanded(false);
    setLayoutMode("auto");
    setLocked(true);
    setZoom(1);
    setNodeOffsets({});
    setHiddenLanes(new Set());
  }, [digest?.workspace_id]);

  const selectedNeighbors = useMemo(() => {
    if (!selectedId) return new Set();
    const ids = new Set([selectedId]);
    projection.edges.forEach((edge) => {
      if (edge.source_card_id === selectedId) ids.add(edge.target_card_id);
      if (edge.target_card_id === selectedId) ids.add(edge.source_card_id);
    });
    return ids;
  }, [projection.edges, selectedId]);

  const objectiveText = ["supplied", "set"].includes(digest?.objective?.status)
    ? digest.objective.text
    : null;
  const searchTerm = query.trim().toLowerCase();
  const visibleEdges = selectedId
    ? projection.edges.filter((edge) => edge.source_card_id === selectedId || edge.target_card_id === selectedId)
    : projection.edges;

  const selectNode = (node) => {
    const nextId = selectedId === node.id ? null : node.id;
    setSelectedId(nextId);
  };

  const clearSelection = () => {
    setSelectedId(null);
  };

  const toggleLayout = () => {
    setLayoutMode((current) => {
      const next = current === "auto" ? "manual" : "auto";
      setLocked(next === "auto");
      if (next === "auto") setNodeOffsets({});
      return next;
    });
  };

  const handleKeyDown = (event) => {
    if (event.key !== "Escape") return;
    if (selectedId) clearSelection();
    setDetailsOpen(false);
    setActionsOpen(false);
  };

  return (
    <section
      data-testid="session-knowledge-map"
      role="region"
      aria-label={`Evidence graph for ${workspaceName}`}
      tabIndex={0}
      onKeyDown={handleKeyDown}
      className="relative h-full min-h-[680px] overflow-y-auto bg-[#f4f4ed] text-[#171713] outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[#171713]/30 dark:bg-[#0f0f0c] dark:text-[#f4f4ec]"
    >
      <GraphCommandBar
        workspaceName={workspaceName}
        nodeCount={projection.nodes.length}
        edgeCount={projection.edges.length}
        objectiveText={objectiveText}
        query={query}
        onQueryChange={setQuery}
        onBuild={onBuild}
        building={building}
        actionsOpen={actionsOpen}
        onToggleActions={() => setActionsOpen((value) => !value)}
        onToggleDetails={() => {
          setDetailsOpen((value) => !value);
          setActionsOpen(false);
        }}
        layoutMode={layoutMode}
        onToggleLayout={toggleLayout}
      />

      {detailsOpen ? (
        <MapDetails
          digest={digest}
          generatedAt={generatedAt}
          sessionCount={projection.nodes.filter((node) => node.card?.category === "agent_session").length}
          onClose={() => setDetailsOpen(false)}
        />
      ) : null}

      <div className="mx-auto max-w-[1240px] px-3 pb-20 pt-4 sm:px-5">
        {projection.nodes.length ? (
          <EvidenceFlow
            lanes={projection.lanes}
            searchTerm={searchTerm}
            expandedLanes={expandedLanes}
            onExpandLane={(laneId) => setExpandedLanes((current) => new Set([...current, laneId]))}
            selectedId={selectedId}
            selectedNeighbors={selectedNeighbors}
            edges={projection.edges}
            nodeById={nodeById}
            onSelect={(card) => selectNode(nodeById.get(card.id))}
            zoom={zoom}
            layoutMode={layoutMode}
            locked={locked}
            nodeOffsets={nodeOffsets}
            onMoveNode={(cardId, offset) => setNodeOffsets((current) => ({ ...current, [cardId]: offset }))}
            hiddenLanes={hiddenLanes}
            onToggleLane={(laneId) => setHiddenLanes((current) => {
              const next = new Set(current);
              if (next.has(laneId)) next.delete(laneId);
              else next.add(laneId);
              return next;
            })}
            onFit={() => setZoom(1)}
          />
        ) : (
          <SparseGraphState onBuild={onBuild} building={building} />
        )}

        {projection.nodes.length ? (
          <RelationshipSummary
            edges={visibleEdges}
            nodeById={nodeById}
            expanded={linksExpanded || Boolean(selectedId)}
            onExpand={() => setLinksExpanded(true)}
            selected={Boolean(selectedId)}
            onClear={clearSelection}
          />
        ) : null}

        {projection.hiddenCardCount ? (
          <p className="mt-4 text-center text-[10px] font-semibold text-[#77776e] dark:text-[#999990]">
            {projection.hiddenCardCount} lower-priority record{projection.hiddenCardCount === 1 ? " is" : "s are"} outside this overview. Inspect Sources for the complete evidence inventory.
          </p>
        ) : null}
      </div>

      {projection.nodes.length ? (
        <FlowControls
          zoom={zoom}
          locked={locked}
          onZoomIn={() => setZoom((value) => Math.min(1.1, Number((value + 0.05).toFixed(2))))}
          onZoomOut={() => setZoom((value) => Math.max(0.85, Number((value - 0.05).toFixed(2))))}
          onFit={() => setZoom(1)}
          layoutMode={layoutMode}
          onToggleLock={() => {
            if (layoutMode === "manual") setLocked((value) => !value);
          }}
        />
      ) : null}

      {selectedId ? <QuickPeek card={nodeById.get(selectedId)?.card} onClose={clearSelection} onOpen={() => onSelectCard?.(nodeById.get(selectedId)?.card)} /> : null}

      {buildResult || buildError ? <BuildToast result={buildResult} error={buildError} /> : null}
    </section>
  );
}

function GraphCommandBar({ workspaceName, nodeCount, edgeCount, objectiveText, query, onQueryChange, onBuild, building, actionsOpen, onToggleActions, onToggleDetails, layoutMode, onToggleLayout }) {
  return (
    <header className="sticky inset-x-0 top-0 z-40 flex min-h-14 flex-wrap items-center gap-2 border-b border-[#d4d4ca] bg-[#fbfbf6]/95 px-3 py-2 backdrop-blur dark:border-[#30302b] dark:bg-[#171713]/95 sm:flex-nowrap sm:px-4">
      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-[8px] bg-[#171713] text-[#d9ff68] dark:bg-[#d9ff68] dark:text-[#171713]">
        <GitBranch className="h-4 w-4" />
      </span>
      <span className="min-w-0">
        <span className="block truncate text-[12px] font-extrabold">{workspaceName}</span>
        <span className="block text-[10px] font-medium text-[#77776e] dark:text-[#999990]">{nodeCount} records · {edgeCount} sourced links</span>
      </span>

      <button type="button" aria-label="Toggle graph layout mode" aria-pressed={layoutMode === "manual"} onClick={onToggleLayout} className="flex h-7 items-center gap-1.5 rounded-full border border-[#d8d8cf] bg-white px-2.5 text-[9px] font-bold text-[#68685f] dark:border-[#3a3a34] dark:bg-[#11110f] dark:text-[#c8c8be]">
        <span className={`h-1.5 w-1.5 rounded-full ${layoutMode === "auto" ? "bg-[#7764b7]" : "bg-[#c68a2d]"}`} />{layoutMode === "auto" ? "Auto layout" : "Manual view"}
      </button>

      <span className="mx-auto hidden min-w-0 max-w-[340px] flex-1 truncate text-center text-[10px] font-semibold text-[#68685f] dark:text-[#b8b8af] lg:block">
        {objectiveText || "Objective not supplied — showing workspace evidence"}
      </span>

      <label className="order-last flex h-8 w-full basis-full items-center gap-2 rounded-[8px] border border-[#deded5] bg-white px-2.5 text-[#77776e] focus-within:border-[#8c8c82] dark:border-[#33332e] dark:bg-[#11110f] sm:order-none sm:ml-auto sm:w-[190px] sm:basis-auto">
        <Search className="h-3.5 w-3.5 shrink-0" />
        <span className="sr-only">Search graph</span>
        <input value={query} onChange={(event) => onQueryChange(event.target.value)} placeholder="Find evidence" className="min-w-0 flex-1 bg-transparent text-[11px] font-semibold text-[#171713] outline-none placeholder:text-[#9a9a90] dark:text-[#f4f4ec]" />
        {query ? <button type="button" aria-label="Clear graph search" onClick={() => onQueryChange("")}><X className="h-3 w-3" /></button> : null}
      </label>

      <button type="button" aria-label="Update graph" onClick={() => onBuild?.("incremental")} disabled={!onBuild || building} className="inline-flex h-8 shrink-0 items-center gap-1.5 rounded-[8px] bg-[#171713] px-2.5 text-[11px] font-bold text-white transition hover:bg-[#34342e] disabled:opacity-50 dark:bg-[#d9ff68] dark:text-[#171713]">
        {building ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
        <span className="hidden md:inline">Update</span>
      </button>

      <div className="relative">
        <button type="button" aria-label="Open graph actions" aria-expanded={actionsOpen} onClick={onToggleActions} className="flex h-8 w-8 items-center justify-center rounded-[8px] border border-[#d8d8cf] bg-white text-[#5f5f57] dark:border-[#363631] dark:bg-[#11110f] dark:text-[#c8c8be]">
          <MoreHorizontal className="h-4 w-4" />
        </button>
        {actionsOpen ? (
          <div className="absolute right-0 top-10 w-64 overflow-hidden rounded-md border border-[#d4d4ca] bg-[#fbfbf6] p-1.5 shadow-[0_18px_50px_rgba(23,23,19,0.16)] dark:border-[#33332e] dark:bg-[#171713]">
            <ActionButton icon={RotateCcw} label="Rebuild from snapshots" detail="Re-extract current imported sources" onClick={() => onBuild?.("rebuild")} disabled={!onBuild || building} />
            <ActionButton icon={Info} label="Graph details" detail="Objective, scope, and freshness" onClick={onToggleDetails} />
            <div className="my-1 h-px bg-[#e6e6dd] dark:bg-[#2c2c27]" />
            <ActionLink to="/app/sources" icon={ExternalLink} label="Inspect sources" />
            <ActionLink to="/app/connectors" icon={RefreshCw} label="Refresh provider snapshots" />
            <p className="px-2.5 pb-1 pt-2 text-[9px] font-semibold leading-4 text-[#85857c]">Update and rebuild use imported snapshots only.</p>
          </div>
        ) : null}
      </div>
    </header>
  );
}

function EvidenceFlow({ lanes, searchTerm, expandedLanes, onExpandLane, selectedId, selectedNeighbors, edges, nodeById, onSelect, zoom, layoutMode, locked, nodeOffsets, onMoveNode, hiddenLanes, onToggleLane, onFit }) {
  const byId = Object.fromEntries(lanes.map((lane) => [lane.id, {
    ...lane,
    cards: lane.cards.filter((card) => !searchTerm || cardSearchText(card).includes(searchTerm)),
  }]));
  const downstream = [byId.prs, byId.issues, byId.documents, byId.next_tasks].filter((lane) => !hiddenLanes.has(lane.id));
  return (
    <div data-testid="evidence-flow-canvas" className="relative overflow-x-auto px-1 py-4 text-[#171713] dark:text-[#f4f4ec] sm:px-3 sm:py-6">
      <div className="pointer-events-none absolute inset-0 opacity-20 [background-image:radial-gradient(circle,#aaa9a0_1px,transparent_1px)] [background-size:24px_24px] [mask-image:linear-gradient(to_bottom,transparent,black_8%,black_92%,transparent)] dark:opacity-20 dark:[background-image:radial-gradient(circle,#77776e_1px,transparent_1px)]" />
      <FlowFilters lanes={lanes} hiddenLanes={hiddenLanes} onToggle={onToggleLane} />
      <div className="relative mx-auto min-w-[920px] max-w-[1080px] origin-top transition-transform" style={{ transform: `scale(${zoom})`, transformOrigin: "top center", marginBottom: `${(zoom - 1) * 520}px` }}>
        {!hiddenLanes.has("sessions") ? <FlowGroup lane={byId.sessions} variant="sessions" expanded={expandedLanes.has("sessions") || Boolean(searchTerm)} onExpand={() => onExpandLane("sessions")} selectedId={selectedId} selectedNeighbors={selectedNeighbors} edges={edges} onSelect={onSelect} layoutMode={layoutMode} locked={locked} nodeOffsets={nodeOffsets} onMoveNode={onMoveNode} /> : null}

        {!hiddenLanes.has("sessions") && !hiddenLanes.has("decisions") ? <div className="mx-auto my-3 h-7 w-px bg-gradient-to-b from-[#7764b7] to-[#4b9b67]" aria-hidden="true" /> : null}

        {!hiddenLanes.has("decisions") ? <FlowGroup lane={byId.decisions} variant="hub" expanded={expandedLanes.has("decisions") || Boolean(searchTerm)} onExpand={() => onExpandLane("decisions")} selectedId={selectedId} selectedNeighbors={selectedNeighbors} edges={edges} onSelect={onSelect} layoutMode={layoutMode} locked={locked} nodeOffsets={nodeOffsets} onMoveNode={onMoveNode} /> : null}

        <FactualLinkRail edges={edges} nodeById={nodeById} />

        <div className="grid grid-cols-4 gap-3">
          {downstream.map((lane) => <FlowGroup key={lane.id} lane={lane} variant="branch" expanded={expandedLanes.has(lane.id) || Boolean(searchTerm)} onExpand={() => onExpandLane(lane.id)} selectedId={selectedId} selectedNeighbors={selectedNeighbors} edges={edges} onSelect={onSelect} layoutMode={layoutMode} locked={locked} nodeOffsets={nodeOffsets} onMoveNode={onMoveNode} />)}
        </div>

        {byId.other?.cards.length ? <div className="mt-4"><FlowGroup lane={byId.other} variant="other" expanded={expandedLanes.has("other") || Boolean(searchTerm)} onExpand={() => onExpandLane("other")} selectedId={selectedId} selectedNeighbors={selectedNeighbors} edges={edges} onSelect={onSelect} layoutMode={layoutMode} locked={locked} nodeOffsets={nodeOffsets} onMoveNode={onMoveNode} /></div> : null}
      </div>
      <MiniMap lanes={lanes} onFit={onFit} />
    </div>
  );
}

function FlowFilters({ lanes, hiddenLanes, onToggle }) {
  return (
    <div aria-label="Graph quick filters" className="relative z-20 mb-4 flex max-w-[calc(100%-9rem)] flex-wrap gap-1.5">
      {lanes.filter((lane) => lane.id !== "other").map((lane) => {
        const active = !hiddenLanes.has(lane.id);
        return <button key={lane.id} type="button" aria-pressed={active} onClick={() => onToggle(lane.id)} className={`rounded-full px-2.5 py-1.5 text-[8px] font-bold transition ${active ? "bg-white text-[#34342e] shadow-[0_1px_4px_rgba(23,23,19,.1)] dark:bg-[#20201c] dark:text-[#d8d8cf]" : "bg-transparent text-[#999990] line-through"}`}>{lane.label} · {lane.totalCount ?? lane.cards.length}</button>;
      })}
    </div>
  );
}

function FlowGroup({ lane, variant, expanded, onExpand, selectedId, selectedNeighbors, edges, onSelect, layoutMode, locked, nodeOffsets, onMoveNode }) {
  if (!lane) return null;
  const limit = variant === "sessions" ? 3 : variant === "hub" ? 3 : 3;
  const visible = expanded ? lane.cards : lane.cards.slice(0, limit);
  const hiddenCount = Math.max(0, lane.cards.length - visible.length);
  const colors = flowColor(lane.id);
  const emptyDocuments = lane.id === "documents" && !lane.cards.length;
  return (
    <section className={variant === "sessions" || variant === "hub" ? "mx-auto w-[360px]" : "min-w-0"} aria-labelledby={`flow-${lane.id}`}>
      <header id={`flow-${lane.id}`} className={`flex items-center gap-2 rounded-[9px] px-3 py-2 text-[11px] font-bold ${colors.header}`}>
        <span className="h-2 w-2 rounded-full" style={{ backgroundColor: colors.dot }} />
        <span className="min-w-0 flex-1 truncate">{lane.label}</span>
        <span className="rounded-full bg-black/20 px-1.5 py-0.5 text-[9px]">{lane.totalCount ?? lane.cards.length}</span>
      </header>
      {visible.length ? (
        <div className={`mt-2 ${variant === "hub" ? "grid gap-1.5" : "space-y-1.5"}`}>
          {visible.map((card) => {
            const connectionCount = edges.filter((edge) => edge.source_card_id === card.id || edge.target_card_id === card.id).length;
            const dimmed = Boolean(selectedId) && !selectedNeighbors.has(card.id);
            return <FlowCard key={card.id} card={card} selected={selectedId === card.id} dimmed={dimmed} connectionCount={connectionCount} onClick={() => onSelect(card)} accent={colors.dot} movable={layoutMode === "manual" && !locked} offset={nodeOffsets[card.id]} onMove={onMoveNode} />;
          })}
        </div>
      ) : (
        <p className="mt-2 px-3 py-1.5 text-[9px] font-medium leading-4 text-[#85857c] dark:text-[#999990]">
          {emptyDocuments ? "Document checks are not available or verified for this workspace." : `No explicit ${lane.label.toLowerCase()} were returned.`}
        </p>
      )}
      {hiddenCount ? <button type="button" onClick={onExpand} className="mx-auto mt-2 block rounded-full bg-white px-2.5 py-1 text-[9px] font-bold text-[#68685f] shadow-sm dark:bg-[#20201c] dark:text-[#b8b8af]">+ {hiddenCount} more</button> : null}
    </section>
  );
}

function FlowCard({ card, selected, dimmed, connectionCount, onClick, accent, movable, offset, onMove }) {
  const dragRef = useRef(null);
  const suppressClickRef = useRef(false);
  const handlePointerDown = (event) => {
    if (!movable || event.button !== 0) return;
    event.currentTarget.setPointerCapture?.(event.pointerId);
    dragRef.current = { pointerId: event.pointerId, x: event.clientX, y: event.clientY, baseX: offset?.x || 0, baseY: offset?.y || 0, moved: false };
  };
  const handlePointerMove = (event) => {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    const dx = event.clientX - drag.x;
    const dy = event.clientY - drag.y;
    if (Math.abs(dx) + Math.abs(dy) > 4) drag.moved = true;
    onMove?.(card.id, { x: drag.baseX + dx, y: drag.baseY + dy });
  };
  const handlePointerEnd = (event) => {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    suppressClickRef.current = drag.moved;
    event.currentTarget.releasePointerCapture?.(event.pointerId);
    dragRef.current = null;
  };
  const handleClick = () => {
    if (suppressClickRef.current) {
      suppressClickRef.current = false;
      return;
    }
    onClick();
  };
  return (
    <button type="button" data-graph-node={card.id} data-card-category={card.category || "unknown"} data-movable={movable ? "true" : "false"} aria-pressed={selected} aria-label={`${nodeTitle(card)}${movable ? ". Drag to reposition" : ""}`} onClick={handleClick} onPointerDown={handlePointerDown} onPointerMove={handlePointerMove} onPointerUp={handlePointerEnd} onPointerCancel={handlePointerEnd} style={{ transform: `translate(${offset?.x || 0}px, ${offset?.y || 0}px)`, position: "relative", zIndex: offset?.x || offset?.y ? 10 : undefined, touchAction: movable ? "none" : undefined }} className={`block w-full rounded-[10px] bg-white px-3 py-2.5 text-left shadow-[0_2px_10px_rgba(23,23,19,.09)] transition focus:outline-none focus-visible:ring-2 focus-visible:ring-[#7764b7] dark:bg-[#1a1a17] dark:shadow-[0_3px_14px_rgba(0,0,0,.28)] dark:focus-visible:ring-[#d9ff68] ${movable ? "cursor-grab active:cursor-grabbing" : ""} ${selected ? "shadow-[0_5px_22px_rgba(119,100,183,.22)] ring-2 ring-[#7764b7]/50 dark:shadow-[0_5px_24px_rgba(217,255,104,.12)] dark:ring-[#d9ff68]/55" : "hover:-translate-y-px hover:shadow-[0_6px_20px_rgba(23,23,19,.14)]"} ${dimmed ? "opacity-20 saturate-0" : "opacity-100"}`}>
      <span className="flex items-start gap-2">
        <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full" style={{ backgroundColor: accent }} />
        <span className="min-w-0 flex-1">
          <span className="block text-[10px] font-bold leading-4 text-[#171713] dark:text-[#f4f4ec]">{nodeTitle(card)}</span>
          <span className="mt-0.5 block line-clamp-2 text-[9px] font-medium leading-4 text-[#74746c] dark:text-[#999990]">{nodeSummary(card)}</span>
        </span>
        {connectionCount ? <span className="shrink-0 text-[8px] font-bold text-[#77776e]">{connectionCount}↗</span> : null}
      </span>
    </button>
  );
}

function FactualLinkRail({ edges, nodeById }) {
  if (!edges.length) return <p className="mx-auto my-4 w-fit rounded-full bg-white/70 px-3 py-1 text-[8px] font-semibold text-[#77776e] dark:bg-[#20201c]">No explicit cross-record links returned</p>;
  return (
    <div className="mx-auto my-4 flex max-w-[760px] items-center justify-center gap-2 overflow-hidden text-[8px] font-semibold text-[#999990]" aria-label={`${edges.length} factual relationships`}>
      <span className="h-px flex-1 bg-[#c8c8be] dark:bg-[#3b3b35]" />
      <span title={edges.slice(0, 3).map((edge) => `${nodeTitle(nodeById.get(edge.source_card_id)?.card)} ${edge.label || edge.relationship_type} ${nodeTitle(nodeById.get(edge.target_card_id)?.card)}`).join("; ")} className="rounded-full bg-white px-2.5 py-1 text-[#6f6f67] shadow-sm dark:bg-[#20201c] dark:text-[#999990]">{edges.length} explicit link{edges.length === 1 ? "" : "s"}</span>
      <span className="h-px flex-1 bg-[#c8c8be] dark:bg-[#3b3b35]" />
    </div>
  );
}

function MiniMap({ lanes, onFit }) {
  const colors = { sessions: "#7764b7", decisions: "#4b9b67", prs: "#3972c4", issues: "#d95c4f", documents: "#c68a2d", next_tasks: "#c64b97", other: "#77776e" };
  return (
    <aside aria-label="Graph minimap and legend" className="absolute right-3 top-3 hidden w-32 rounded-[10px] bg-white/95 p-2.5 shadow-[0_4px_18px_rgba(23,23,19,.12)] dark:bg-[#1a1a17]/95 dark:shadow-[0_5px_22px_rgba(0,0,0,.3)] xl:block">
      <button type="button" aria-label="Fit graph from minimap" onClick={onFit} className="grid h-12 w-full grid-cols-4 items-center gap-1 rounded-[7px] bg-[#f2f2eb] p-2 transition hover:bg-[#e9e9e1] dark:bg-[#10100e] dark:hover:bg-[#242420]">
        {lanes.flatMap((lane) => lane.cards.slice(0, 3).map((card) => <span key={card.id} className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: colors[lane.id] }} />))}
      </button>
      <ul className="mt-2 space-y-1">
        {lanes.filter((lane) => lane.id !== "other").map((lane) => <li key={lane.id} className="flex items-center gap-1.5 text-[8px] font-semibold text-[#62625b] dark:text-[#b8b8af]"><span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: colors[lane.id] }} /><span className="min-w-0 flex-1 truncate">{lane.label}</span><span>{lane.totalCount ?? lane.cards.length}</span></li>)}
      </ul>
    </aside>
  );
}

function flowColor(id) {
  const meta = {
    sessions: { dot: "#8d71d6", header: "bg-violet-100/80 text-violet-950 dark:bg-violet-950/35 dark:text-violet-100" },
    decisions: { dot: "#58ad70", header: "bg-emerald-100/80 text-emerald-950 dark:bg-emerald-950/35 dark:text-emerald-100" },
    prs: { dot: "#4f86d6", header: "bg-blue-100/80 text-blue-950 dark:bg-blue-950/35 dark:text-blue-100" },
    issues: { dot: "#e15d52", header: "bg-red-100/80 text-red-950 dark:bg-red-950/35 dark:text-red-100" },
    documents: { dot: "#d29a35", header: "bg-amber-100/80 text-amber-950 dark:bg-amber-950/35 dark:text-amber-100" },
    next_tasks: { dot: "#d65aa2", header: "bg-pink-100/80 text-pink-950 dark:bg-pink-950/35 dark:text-pink-100" },
    other: { dot: "#8c8c82", header: "bg-neutral-200/70 text-neutral-800 dark:bg-neutral-900 dark:text-neutral-200" },
  };
  return meta[id] || meta.other;
}

function FlowControls({ zoom, locked, layoutMode, onZoomIn, onZoomOut, onFit, onToggleLock }) {
  return <div className="sticky bottom-3 z-30 ml-auto mr-3 flex w-fit items-center rounded-[10px] bg-white p-1 text-[#5f5f57] shadow-[0_5px_20px_rgba(23,23,19,.14)] dark:bg-[#1a1a17] dark:text-[#d8d8cf] dark:shadow-[0_6px_24px_rgba(0,0,0,.3)]"><button type="button" aria-label="Fit graph" onClick={onFit} className="h-7 rounded px-2 text-[8px] font-bold">Fit</button><button type="button" aria-label="Zoom in" onClick={onZoomIn} className="flex h-7 w-7 items-center justify-center"><Plus className="h-3.5 w-3.5" /></button><span className="min-w-9 text-center text-[8px] font-bold">{Math.round(zoom * 100)}%</span><button type="button" aria-label="Zoom out" onClick={onZoomOut} className="flex h-7 w-7 items-center justify-center"><Minus className="h-3.5 w-3.5" /></button><button type="button" aria-label={layoutMode === "auto" ? "Switch to manual layout to move nodes" : locked ? "Unlock layout" : "Lock layout"} aria-disabled={layoutMode === "auto"} onClick={onToggleLock} className={`flex h-7 w-7 items-center justify-center ${layoutMode === "auto" ? "opacity-35" : ""}`}>{locked ? <Lock className="h-3.5 w-3.5" /> : <Unlock className="h-3.5 w-3.5" />}</button></div>;
}

function QuickPeek({ card, onClose, onOpen }) {
  if (!card) return null;
  return (
    <aside aria-label="Selected record quick peek" className="sticky bottom-3 z-40 mx-auto mb-3 w-[min(760px,calc(100%-1.5rem))] rounded-[12px] border border-[#c8c8be] bg-white p-4 text-[#171713] shadow-[0_18px_55px_rgba(23,23,19,.18)] dark:border-[#3a3a34] dark:bg-[#171713] dark:text-[#f4f4ec] dark:shadow-[0_18px_55px_rgba(0,0,0,.35)]">
      <div className="flex items-start gap-3"><span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-[7px] bg-[#efefe8] text-[#7764b7] dark:bg-[#292925] dark:text-[#d9ff68]"><Info className="h-3.5 w-3.5" /></span><span className="min-w-0 flex-1"><span className="block text-[9px] font-bold uppercase tracking-[.14em] text-[#7a7a72] dark:text-[#999990]">{nodeTypeLabel(card)} · quick peek</span><strong className="mt-1 block text-[12px] leading-5">{nodeTitle(card)}</strong><span className="mt-1 block text-[10px] leading-4 text-[#68685f] dark:text-[#b8b8af]">{nodeSummary(card)}</span></span><button type="button" onClick={onOpen} className="shrink-0 rounded-[7px] border border-[#d2d2c8] px-2.5 py-1.5 text-[9px] font-bold dark:border-[#3a3a34]">Open full details</button><button type="button" aria-label="Close quick peek" onClick={onClose}><X className="h-4 w-4 text-[#999990]" /></button></div>
    </aside>
  );
}

function RelationshipSummary({ edges, nodeById, expanded, onExpand, selected, onClear }) {
  const visible = expanded ? edges : edges.slice(0, INITIAL_LINK_LIMIT);
  return (
    <section className="mt-6 rounded-[12px] bg-white/65 p-4 dark:bg-[#171713]/65">
      <div className="flex items-center gap-2">
        <GitBranch className="h-3.5 w-3.5 text-[#77776e]" />
        <h2 className="text-[11px] font-extrabold">{selected ? "Links for selected record" : "Sourced relationships"}</h2>
        <span className="text-[9px] font-semibold text-[#85857c]">{edges.length}</span>
        {selected ? <button type="button" onClick={onClear} className="ml-auto text-[9px] font-bold text-[#68685f] underline underline-offset-2 dark:text-[#d9ff68]">Clear focus</button> : null}
      </div>
      {visible.length ? (
        <div className="mt-3 space-y-1.5">
          {visible.map((edge) => {
            const source = nodeById.get(edge.source_card_id)?.card;
            const target = nodeById.get(edge.target_card_id)?.card;
            return (
              <div key={edge.id} data-evidence-edge data-relationship-type={edge.relationship_type} className="grid items-center gap-1.5 rounded-[8px] bg-[#f0f0e8] px-3 py-2 text-[9px] font-semibold text-[#68685f] dark:bg-[#23231f] dark:text-[#b8b8af] sm:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)]">
                <span className="truncate">{source ? nodeTitle(source) : "Unavailable source"}</span>
                <span className="w-fit rounded-full border border-[#d2d2c8] bg-[#fbfbf6] px-2 py-0.5 font-bold text-[#45453f] dark:border-[#3a3a34] dark:bg-[#171713] dark:text-[#d9ff68]">{edge.label || edge.relationship_type}</span>
                <span className="truncate sm:text-right">{target ? nodeTitle(target) : "Unavailable target"}</span>
              </div>
            );
          })}
        </div>
      ) : <p className="mt-2 text-[10px] font-medium text-[#85857c]">No explicit links were returned for this {selected ? "record" : "workspace"}. Records remain readable without inferred edges.</p>}
      {!expanded && edges.length > INITIAL_LINK_LIMIT ? <button type="button" onClick={onExpand} className="mt-2 text-[9px] font-bold text-[#68685f] underline underline-offset-2">Show {edges.length - INITIAL_LINK_LIMIT} more links</button> : null}
    </section>
  );
}

function ActionButton({ icon: Icon, label, detail, onClick, disabled }) {
  return <button type="button" aria-label={label} onClick={onClick} disabled={disabled} className="flex w-full items-start gap-2.5 rounded-[8px] px-2.5 py-2 text-left transition hover:bg-[#efefe7] disabled:opacity-45 dark:hover:bg-[#252521]"><Icon className="mt-0.5 h-3.5 w-3.5 shrink-0" /><span><span className="block text-[11px] font-bold">{label}</span><span className="mt-0.5 block text-[9px] text-[#85857c]">{detail}</span></span></button>;
}

function ActionLink({ to, icon: Icon, label }) {
  return <Link to={to} className="flex items-center gap-2.5 rounded-[8px] px-2.5 py-2 text-[11px] font-bold transition hover:bg-[#efefe7] dark:hover:bg-[#252521]"><Icon className="h-3.5 w-3.5" />{label}</Link>;
}

function MapDetails({ digest, generatedAt, sessionCount, onClose }) {
  const scope = digest?.scope;
  const builtLabel = formatDigestTimestamp(digest?.build?.last_built_at || digest?.build?.last_processed_at || generatedAt);
  return (
    <aside className="fixed right-3 top-[72px] z-50 w-[min(340px,calc(100%-1.5rem))] rounded-md border border-[#d4d4ca] bg-[#fbfbf6] p-4 shadow-[0_18px_50px_rgba(23,23,19,0.16)] dark:border-[#33332e] dark:bg-[#171713]">
      <div className="flex items-center justify-between"><h2 className="text-[12px] font-extrabold">Graph details</h2><button type="button" aria-label="Close graph details" onClick={onClose}><X className="h-4 w-4 text-[#77776e]" /></button></div>
      <dl className="mt-3 grid grid-cols-2 gap-2">
        <DetailStat label="Imported sources" value={scope?.included_source_count ?? scope?.included_sources ?? scope?.source_count ?? 0} />
        <DetailStat label="Pending" value={scope?.pending_source_count ?? scope?.pending_sources ?? 0} />
        <DetailStat label="AI sessions" value={sessionCount} />
        <DetailStat label="Last processing" value={builtLabel || "Not recorded"} wide />
      </dl>
      <p className="mt-3 rounded-[8px] bg-[#f0f0e8] px-3 py-2 text-[10px] font-medium leading-4 text-[#68685f] dark:bg-[#23231f] dark:text-[#b8b8af]">Only relationships returned by the evidence-backed digest appear here. Provider state remains an imported snapshot until sources are refreshed.</p>
    </aside>
  );
}

function DetailStat({ label, value, wide }) {
  return <div className={`${wide ? "col-span-2" : ""} rounded-[8px] border border-[#e0e0d7] px-3 py-2 dark:border-[#30302b]`}><dt className="text-[9px] font-semibold text-[#85857c]">{label}</dt><dd className="mt-0.5 truncate text-[11px] font-extrabold">{value}</dd></div>;
}

function SparseGraphState({ onBuild, building }) {
  return (
    <div className="mx-auto mt-16 w-[min(400px,100%)] rounded-[14px] border border-dashed border-[#bdbdb3] bg-[#fbfbf6] p-6 text-center dark:border-[#41413b] dark:bg-[#171713]">
      <GitBranch className="mx-auto h-5 w-5 text-[#85857c]" />
      <h2 className="mt-3 text-[14px] font-extrabold">The overview is ready for evidence</h2>
      <p className="mt-1 text-[11px] font-medium leading-5 text-[#77776e]">Import sources, then process their current snapshots into inspectable records.</p>
      <button type="button" onClick={() => onBuild?.("incremental")} disabled={!onBuild || building} className="mt-4 inline-flex h-8 items-center gap-2 rounded-[8px] bg-[#171713] px-3 text-[10px] font-bold text-white dark:bg-[#d9ff68] dark:text-[#171713]">{building ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}Process imported sources</button>
    </div>
  );
}

function BuildToast({ result, error }) {
  const warnings = result?.warnings?.length || result?.errors?.length || result?.documents?.failed || 0;
  return <div role={error ? "alert" : "status"} className={`fixed bottom-4 left-1/2 z-50 flex max-w-[min(440px,calc(100%-2rem))] -translate-x-1/2 items-start gap-2 rounded-[9px] border px-3 py-2 text-[10px] font-bold shadow-lg ${error ? TONE_CLASSES.red : warnings ? TONE_CLASSES.amber : TONE_CLASSES.green}`}>{error || warnings ? <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" /> : <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0" />}{error?.message || buildSummary(result)}</div>;
}

function nodeTitle(card) {
  if (["agent_session", "session"].includes(card?.category)) return sessionIdentity(card).title;
  if (card?.category === "pull_request") return pullRequestLabel(card);
  if (card?.category === "issue") return issueLabel(card);
  return cardDisplayLine(card, card?.category || "summary", 16);
}

function nodeSummary(card) {
  if (["agent_session", "session"].includes(card?.category)) {
    const identity = sessionIdentity(card);
    return [identity.source, identity.context, identity.detail, relevanceLabel(card)].filter(Boolean).join(" · ");
  }
  if (["pull_request", "issue"].includes(card?.category)) return observedRemoteState(card);
  return cardDisplayLine(card, "summary", 24);
}

function nodeTypeLabel(card) {
  const labels = { agent_session: "AI session", blocker: "Blocker", decision: "Decision", document_finding: "Document warning", issue: "Issue snapshot", pull_request: "Pull request snapshot", supporting_evidence: "Supporting evidence" };
  return labels[card?.category] || String(card?.type || "Evidence").replaceAll("_", " ");
}

function cardSearchText(card) {
  return [card?.title, card?.summary, card?.why_it_matters, card?.next_action, card?.type, card?.category, card?.status, card?.session?.session_id, card?.session?.branch, card?.remote_item?.repository]
    .filter(Boolean).join(" ").toLowerCase();
}

function buildSummary(result) {
  if (!result) return "Graph processing finished.";
  const processed = result.documents?.processed ?? result.docs_processed ?? 0;
  const reprocessed = result.documents?.reprocessed ?? result.docs_reprocessed ?? 0;
  const created = result.components?.created ?? result.components_created ?? 0;
  const superseded = result.components?.superseded ?? result.components_superseded ?? 0;
  const failed = result.documents?.failed ?? result.errors?.length ?? 0;
  if (processed === 0 && reprocessed === 0 && failed === 0) return "No imported source needed processing. Provider snapshots were unchanged.";
  return `${result.mode === "rebuild" ? "Rebuild" : "Update"}: ${processed} processed, ${reprocessed} reprocessed, ${created} created, ${superseded} superseded${failed ? `, ${failed} failed` : ""}.`;
}

function formatDigestTimestamp(value) {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return date.toLocaleString(undefined, { year: "numeric", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}
