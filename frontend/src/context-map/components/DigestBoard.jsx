import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  AlertTriangle,
  Check,
  CheckCircle2,
  Clipboard,
  FolderGit2,
  Loader2,
  Maximize2,
  MoreHorizontal,
  RefreshCw,
  RotateCcw,
  Search,
} from "lucide-react";
import {
  buildEvidenceGraph,
  cardDisplayLine,
  cardIcon,
  preciseLine,
  sessionIdentity,
  TONE_CLASSES,
} from "../digest";
import {
  MAP_HEIGHT,
  MAP_LANE_LIMITS,
  MAP_NODE_SIZE,
  MAP_WIDTH,
  MAP_ZONES,
  positionNodes,
} from "../layout";

export default function DigestBoard({
  digest,
  workspaceName,
  generatedAt,
  onBuild,
  building = false,
  buildResult = null,
  buildError = null,
  selectedCardId = null,
  onSelectCard,
  onClearSelection,
  onIndexProject,
  indexingProject = false,
  indexResult = null,
  indexError = null,
  onPrepareHandoff,
  onOpenLoops,
}) {
  const [query, setQuery] = useState("");
  const [changingProject, setChangingProject] = useState(false);
  const prioritizedCardIds = useMemo(() => {
    const term = query.trim().toLowerCase();
    if (!term) return new Set();
    return new Set(
      (digest?.cards || [])
        .filter((card) => cardSearchText(card).includes(term))
        .map((card) => card.id),
    );
  }, [digest?.cards, query]);
  const projection = useMemo(
    () => buildEvidenceGraph(digest, {
      limitPerLane: 2,
      laneLimits: MAP_LANE_LIMITS,
      prioritizedCardIds,
    }),
    [digest, prioritizedCardIds],
  );
  const hasProjectBoundary = Boolean(
    digest?.scope?.project_paths?.length
    || digest?.scope?.project_repositories?.length,
  );
  const nodes = useMemo(() => positionNodes(projection), [projection]);
  const nodeById = useMemo(
    () => new Map(nodes.map((node) => [node.id, node])),
    [nodes],
  );
  const initialView = defaultMapView(nodes);
  const [actionsOpen, setActionsOpen] = useState(false);
  const [zoom, setZoom] = useState(initialView.zoom);
  const [pan, setPan] = useState(initialView.pan);
  const [panning, setPanning] = useState(false);
  const [handoffStatus, setHandoffStatus] = useState("idle");
  const panRef = useRef(null);
  const focusedCard = useMemo(() => {
    const componentId = digest?.oversight?.current_focus?.component_id;
    if (!componentId) return null;
    return (digest?.cards || []).find((card) => card.id === `component:${componentId}`) || null;
  }, [digest?.cards, digest?.oversight?.current_focus?.component_id]);

  useEffect(() => {
    setQuery("");
    setActionsOpen(false);
    const view = defaultMapView(nodes);
    setZoom(view.zoom);
    setPan(view.pan);
    setHandoffStatus("idle");
  }, [digest?.workspace_id, digest?.generated_at]);

  useEffect(() => {
    if (indexResult) setChangingProject(false);
  }, [indexResult]);

  const selectedNeighbors = useMemo(() => {
    if (!selectedCardId) return new Set();
    const ids = new Set([selectedCardId]);
    projection.edges.forEach((edge) => {
      if (edge.source_card_id === selectedCardId) ids.add(edge.target_card_id);
      if (edge.target_card_id === selectedCardId) ids.add(edge.source_card_id);
    });
    return ids;
  }, [projection.edges, selectedCardId]);

  const searchTerm = query.trim().toLowerCase();
  const matchesSearch = (card) => !searchTerm || cardSearchText(card).includes(searchTerm);

  const fitMap = () => {
    const view = defaultMapView(nodes);
    setZoom(view.zoom);
    setPan(view.pan);
  };

  const copyHandoff = async () => {
    try {
      setHandoffStatus("preparing");
      const handoff = await onPrepareHandoff();
      await writeClipboard(handoff);
      setHandoffStatus("copied");
    } catch {
      setHandoffStatus("error");
    }
  };

  const handleKeyDown = (event) => {
    if (event.key === "Escape") {
      setActionsOpen(false);
      onClearSelection?.();
    }
    if (event.key === "0") fitMap();
    if (event.key === "+" || event.key === "=") setZoom((value) => clampZoom(value + 0.1));
    if (event.key === "-") setZoom((value) => clampZoom(value - 0.1));
  };

  const beginPan = (event) => {
    if (event.button !== 0 || event.target.closest("button, input")) return;
    event.currentTarget.setPointerCapture?.(event.pointerId);
    panRef.current = {
      pointerId: event.pointerId,
      x: event.clientX,
      y: event.clientY,
      baseX: pan.x,
      baseY: pan.y,
    };
    setPanning(true);
    onClearSelection?.();
  };

  const movePan = (event) => {
    const drag = panRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    setPan({
      x: drag.baseX + event.clientX - drag.x,
      y: drag.baseY + event.clientY - drag.y,
    });
  };

  const endPan = (event) => {
    const drag = panRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    event.currentTarget.releasePointerCapture?.(event.pointerId);
    panRef.current = null;
    setPanning(false);
  };

  const handleWheel = (event) => {
    if (event.target.closest("button, input")) return;
    event.preventDefault();
    setZoom((value) => clampZoom(value + (event.deltaY < 0 ? 0.1 : -0.1)));
  };

  return (
    <section
      data-testid="session-knowledge-map"
      role="region"
      aria-label={`Project map for ${workspaceName}`}
      tabIndex={0}
      onKeyDown={handleKeyDown}
      className="relative flex h-full min-h-0 flex-col overflow-hidden bg-[#f4f4ed] text-[#171713] outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[#171713]/30 dark:bg-[#0f0f0c] dark:text-[#f4f4ec]"
    >
      {hasProjectBoundary ? <ProjectBar
        workspaceName={workspaceName}
        objectiveText={digest?.objective?.status === "supplied" ? digest.objective.text : null}
        oversight={digest?.oversight}
        generatedAt={generatedAt}
        nodeCount={nodes.length}
        edgeCount={projection.edges.length}
        query={query}
        onQueryChange={setQuery}
        onFit={fitMap}
        onBuild={onBuild}
        building={building}
        actionsOpen={actionsOpen}
        onToggleActions={() => setActionsOpen((value) => !value)}
        canCopyHandoff={hasProjectBoundary && nodes.length > 0 && Boolean(onPrepareHandoff)}
        handoffStatus={handoffStatus}
        onCopyHandoff={copyHandoff}
        onOpenFocus={focusedCard ? () => onSelectCard?.(focusedCard) : null}
        openLoopCount={Number(digest?.open_loops?.open_count || 0)}
        pendingPlaybookCount={Number(digest?.playbooks?.pending_review_count || 0)}
        onOpenLoops={onOpenLoops}
        monitoring={digest?.monitoring || null}
        onChangeProject={() => {
          setActionsOpen(false);
          setChangingProject(true);
        }}
      /> : null}

      <div className="relative min-h-0 flex-1 overflow-hidden">
        {!hasProjectBoundary || changingProject ? (
          <ProjectEmptyState
            onIndexProject={onIndexProject}
            indexing={indexingProject}
            result={indexResult}
            error={indexError}
            onCancel={hasProjectBoundary ? () => setChangingProject(false) : null}
          />
        ) : nodes.length ? (
          <div
            data-testid="evidence-flow-canvas"
            data-panning={panning ? "true" : "false"}
            aria-label="Interactive project map. Drag the background to pan and use the wheel or trackpad to zoom."
            className={`relative h-full min-h-0 touch-none overflow-hidden ${panning ? "cursor-grabbing" : "cursor-grab"}`}
            onPointerDown={beginPan}
            onPointerMove={movePan}
            onPointerUp={endPan}
            onPointerCancel={endPan}
            onWheel={handleWheel}
          >
            <div className="pointer-events-none absolute inset-0 opacity-[0.16] [background-image:radial-gradient(circle,#aaa9a0_1px,transparent_1px)] [background-size:28px_28px] dark:[background-image:radial-gradient(circle,#66665e_1px,transparent_1px)]" />
            <div
              data-testid="fitted-evidence-graph"
              className="absolute left-1/2 top-1/2 h-[620px] w-[1000px] origin-center"
              style={{ transform: `translate3d(calc(-50% + ${pan.x}px), calc(-50% + ${pan.y}px), 0) scale(${zoom})` }}
            >
              <ZoneBackdrops projection={projection} />
              <SemanticContainers
                edges={projection.edges}
                nodeById={nodeById}
                selectedCardId={selectedCardId}
                matchesSearch={matchesSearch}
              />
              <EvidenceEdges
                edges={projection.edges}
                nodeById={nodeById}
                selectedCardId={selectedCardId}
                matchesSearch={matchesSearch}
              />
              {nodes.map((node) => (
                <MapNode
                  key={node.id}
                  node={node}
                  selected={node.id === selectedCardId}
                  related={!selectedCardId || selectedNeighbors.has(node.id)}
                  searchMatch={matchesSearch(node.card)}
                  onSelect={() => onSelectCard?.(node.card)}
                />
              ))}
            </div>

            <div className="absolute bottom-3 left-3 z-30 flex items-center rounded-lg border border-[#d8d8cf] bg-[#fbfbf6]/95 p-1 shadow-sm backdrop-blur dark:border-[#33332e] dark:bg-[#171713]/95">
              <button type="button" onClick={() => setZoom((value) => clampZoom(value - 0.1))} aria-label="Zoom out" className="flex h-7 w-7 items-center justify-center text-sm font-bold">−</button>
              <span className="min-w-10 text-center text-[9px] font-bold text-[#77776e]">{Math.round(zoom * 100)}%</span>
              <button type="button" onClick={() => setZoom((value) => clampZoom(value + 0.1))} aria-label="Zoom in" className="flex h-7 w-7 items-center justify-center text-sm font-bold">+</button>
            </div>

            {projection.hiddenCardCount ? (
              <p title="Use Find to bring a quieter matching record into view." className="absolute bottom-3 right-3 rounded-full bg-[#fbfbf6]/95 px-3 py-1.5 text-[9px] font-semibold text-[#68685f] shadow-sm dark:bg-[#171713]/95 dark:text-[#aaa9a0]">
                +{projection.hiddenCardCount} quieter
              </p>
            ) : null}
          </div>
        ) : <ProjectReadyState />}
      </div>

      {buildResult || buildError ? <BuildToast result={buildResult} error={buildError} /> : null}
      {handoffStatus === "error" ? (
        <div role="alert" className="fixed bottom-4 left-1/2 z-50 -translate-x-1/2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-[10px] font-bold text-red-800 shadow-lg dark:border-red-900/60 dark:bg-red-950/40 dark:text-red-200">
          Could not create or copy the source-backed handoff.
        </div>
      ) : null}
    </section>
  );
}

function ProjectBar({ workspaceName, objectiveText, oversight, generatedAt, nodeCount, edgeCount, query, onQueryChange, onFit, onBuild, building, actionsOpen, onToggleActions, canCopyHandoff, handoffStatus, onCopyHandoff, onChangeProject, onOpenFocus, openLoopCount, pendingPlaybookCount, onOpenLoops, monitoring }) {
  const observed = formatDigestTimestamp(generatedAt);
  const monitoringMeta = projectMonitoringMeta(monitoring);
  const focus = oversight?.current_focus;
  const latestOutcome = oversight?.latest_outcome;
  const attention = [
    ["Blocked", oversight?.attention?.blocked, "text-red-700 dark:text-red-300"],
    ["Unverified", oversight?.attention?.unverified, "text-amber-700 dark:text-amber-300"],
    ["Stale", oversight?.attention?.stale, "text-slate-600 dark:text-slate-300"],
  ].filter(([, count]) => Number(count) > 0);
  return (
    <header className="relative z-40 flex min-h-16 shrink-0 items-center gap-3 border-b border-[#d8d8cf] bg-[#fbfbf6]/95 px-4 py-2.5 backdrop-blur dark:border-[#292925] dark:bg-[#141411]/95 sm:px-5">
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span
            className={`h-2 w-2 rounded-full ${monitoringMeta?.tone || "bg-[#58ad70]"}`}
            aria-hidden={monitoringMeta ? undefined : "true"}
            aria-label={monitoringMeta?.label}
            role={monitoringMeta ? "status" : undefined}
            title={monitoringMeta?.label}
          />
          <p className="truncate text-[10px] font-semibold text-[#77776e] dark:text-[#aaa9a0]">{workspaceName}</p>
          {monitoringMeta ? <span aria-hidden="true" className={`hidden truncate text-[9px] font-semibold md:inline ${monitoringMeta.textTone}`}>{monitoringMeta.label}</span> : null}
        </div>
        <div className="mt-0.5 flex items-baseline gap-2">
          <h1 className="text-sm font-extrabold">Explain</h1>
          <span className="hidden text-[9px] font-medium text-[#929289] sm:inline">{nodeCount} records · {edgeCount} sourced link{edgeCount === 1 ? "" : "s"}{observed ? ` · ${observed}` : ""}</span>
        </div>
        {focus ? (
          <button type="button" onClick={onOpenFocus} disabled={!onOpenFocus} className="mt-0.5 block max-w-xl truncate text-left text-[9px] font-semibold text-[#68685f] underline-offset-2 enabled:hover:underline disabled:cursor-default dark:text-[#b8b8af]" title={focus.title}>
            <span className="text-[#929289]">Focus ·</span> {focus.title}
            <span className="text-[#929289]"> · {latestOutcome?.summary || "No observed outcome yet"}</span>
          </button>
        ) : objectiveText ? (
          <p className="mt-0.5 max-w-xl truncate text-[9px] font-semibold text-[#68685f] dark:text-[#b8b8af]" title={objectiveText}><span className="text-[#929289]">Now ·</span> {objectiveText}</p>
        ) : null}
      </div>

      {openLoopCount > 0 || pendingPlaybookCount > 0 ? (
        <button data-project-attention type="button" onClick={onOpenLoops} disabled={!onOpenLoops} aria-label={openLoopCount > 0 ? `Open unresolved work, ${openLoopCount} items` : `Review verified agent steps, ${pendingPlaybookCount} pending`} className="shrink-0 rounded-full bg-amber-100 px-2 py-1 text-[9px] font-black text-amber-800 transition enabled:hover:ring-1 enabled:hover:ring-amber-400 disabled:cursor-default dark:bg-amber-950/50 dark:text-amber-200">
          {openLoopCount > 0 ? `Unresolved ${openLoopCount}` : `Review steps ${pendingPlaybookCount}`}
        </button>
      ) : null}

      {attention.length ? (
        <div aria-label="Focused task attention" className="flex items-center gap-1">
          <button type="button" onClick={onOpenFocus} disabled={!onOpenFocus} className="rounded-full bg-[#efefe7] px-2 py-1 text-[9px] font-black text-amber-700 enabled:hover:ring-1 enabled:hover:ring-amber-400 disabled:cursor-default dark:bg-[#252521] dark:text-amber-300 lg:hidden">
            Attention {attention.reduce((total, [, count]) => total + Number(count), 0)}
          </button>
          <div className="hidden items-center gap-1 lg:flex">
            {attention.map(([label, count, tone]) => (
              <button type="button" onClick={onOpenFocus} disabled={!onOpenFocus} key={label} className={`rounded-full bg-[#efefe7] px-2 py-1 text-[9px] font-black enabled:hover:ring-1 enabled:hover:ring-[#aaa9a0] disabled:cursor-default dark:bg-[#252521] ${tone}`}>
                {label} {count}
              </button>
            ))}
          </div>
        </div>
      ) : null}

      <label className="hidden h-8 w-40 items-center gap-2 rounded-lg border border-[#d8d8cf] bg-white px-2.5 focus-within:border-[#77776e] dark:border-[#33332e] dark:bg-[#0f0f0c] sm:flex lg:w-52">
        <Search className="h-3.5 w-3.5 shrink-0 text-[#929289]" />
        <span className="sr-only">Search project map</span>
        <input value={query} onChange={(event) => onQueryChange(event.target.value)} placeholder="Find" className="min-w-0 flex-1 bg-transparent text-[11px] font-semibold outline-none placeholder:text-[#aaa9a0]" />
      </label>
      <button type="button" onClick={() => onBuild?.("incremental")} disabled={!onBuild || building} aria-label="Refresh project map" title="Refresh map" className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-[#171713] text-white transition hover:bg-[#34342e] disabled:opacity-50 dark:bg-[#d9ff68] dark:text-[#171713]">
        {building ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
      </button>
      {canCopyHandoff ? (
        <button type="button" onClick={onCopyHandoff} disabled={handoffStatus === "preparing"} className="inline-flex h-8 shrink-0 items-center justify-center gap-1.5 rounded-lg border border-[#d8d8cf] bg-white px-2.5 text-[10px] font-bold text-[#4f4f48] transition hover:border-[#aaa9a0] hover:text-[#171713] disabled:opacity-60 dark:border-[#33332e] dark:bg-[#1b1b18] dark:text-[#d8d8cf] dark:hover:text-white">
          {handoffStatus === "preparing" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : handoffStatus === "copied" ? <Check className="h-3.5 w-3.5" /> : <Clipboard className="h-3.5 w-3.5" />}
          {handoffStatus === "preparing" ? "Preparing" : handoffStatus === "copied" ? "Copied" : "Copy project brief"}
        </button>
      ) : null}
      <div className="relative">
        <button type="button" onClick={onToggleActions} aria-label="Open project map actions" aria-expanded={actionsOpen} className="flex h-8 w-8 items-center justify-center rounded-lg border border-[#d8d8cf] bg-white text-[#68685f] dark:border-[#33332e] dark:bg-[#1b1b18] dark:text-[#aaa9a0]">
          <MoreHorizontal className="h-4 w-4" />
        </button>
        {actionsOpen ? (
          <div className="absolute right-0 top-10 z-50 w-64 rounded-lg border border-[#d8d8cf] bg-[#fbfbf6] p-2 shadow-xl dark:border-[#33332e] dark:bg-[#171713]">
            <button type="button" aria-label="Fit project map" onClick={onFit} className="flex w-full items-start gap-2.5 rounded-md px-2.5 py-2 text-left transition hover:bg-[#efefe7] dark:hover:bg-[#252521]">
              <Maximize2 className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              <span>
                <span className="block text-[11px] font-bold">Fit project map</span>
                <span className="mt-0.5 block text-[9px] leading-4 text-[#85857c]">Reset pan and zoom to the full project.</span>
              </span>
            </button>
            <button type="button" aria-label="Rebuild projection" onClick={() => onBuild?.("rebuild")} disabled={!onBuild || building} className="flex w-full items-start gap-2.5 rounded-md px-2.5 py-2 text-left transition hover:bg-[#efefe7] disabled:opacity-50 dark:hover:bg-[#252521]">
              <RotateCcw className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              <span>
                <span className="block text-[11px] font-bold">Rebuild projection</span>
                <span className="mt-0.5 block text-[9px] leading-4 text-[#85857c]">Re-read imported snapshots. Provider sync stays separate.</span>
              </span>
            </button>
            <button type="button" aria-label="Change local project" onClick={onChangeProject} className="flex w-full items-start gap-2.5 rounded-md px-2.5 py-2 text-left transition hover:bg-[#efefe7] dark:hover:bg-[#252521]">
              <FolderGit2 className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              <span>
                <span className="block text-[11px] font-bold">Change local project</span>
                <span className="mt-0.5 block text-[9px] leading-4 text-[#85857c]">Replace this workspace's active repository boundary.</span>
              </span>
            </button>
          </div>
        ) : null}
      </div>
    </header>
  );
}

function projectMonitoringMeta(monitoring) {
  if (!monitoring) return null;
  const status = String(monitoring.status || "unknown").toLowerCase();
  const observedAt = monitoring.last_seen_at || monitoring.observed_at || monitoring.updated_at;
  const age = relativeAge(observedAt);
  if (["watching", "healthy", "active", "current"].includes(status)) {
    return {
      label: `Monitoring local activity${age ? ` · updated ${age}` : ""}`,
      tone: "bg-[#58ad70]",
      textTone: "text-[#68766a] dark:text-[#9db7a2]",
    };
  }
  if (["observed", "captured", "indexed"].includes(status)) {
    return {
      label: `Local activity captured${age ? ` · latest change ${age}` : ""}`,
      tone: "bg-sky-500",
      textTone: "text-sky-700 dark:text-sky-300",
    };
  }
  if (["stale", "delayed", "unhealthy"].includes(status)) {
    return {
      label: `Local activity may be stale${age ? ` · watcher last seen ${age}` : ""}`,
      tone: "bg-amber-500",
      textTone: "text-amber-700 dark:text-amber-300",
    };
  }
  return {
    label: "Local activity monitoring is off",
    tone: "bg-slate-400",
    textTone: "text-slate-500 dark:text-neutral-400",
  };
}

function relativeAge(value) {
  if (!value) return null;
  const timestamp = new Date(value).getTime();
  if (!Number.isFinite(timestamp)) return null;
  const seconds = Math.max(0, Math.round((Date.now() - timestamp) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

function ZoneBackdrops({ projection }) {
  return Object.entries(MAP_ZONES).map(([zoneId, zone]) => {
    const lane = projection.lanes.find((item) => item.id === zoneId);
    const hasCards = Boolean(lane?.cards.length);
    if (zoneId === "other" && !hasCards) return null;
    return (
      <div
        key={zone.label}
        aria-label={`${zone.label}: ${hasCards ? `${lane.cards.length} visible records` : "no evidence"}`}
        data-zone-empty={hasCards ? "false" : "true"}
        className={`pointer-events-none absolute rounded-2xl border ${hasCards ? "border-[#d8d8cf]/65 bg-[#fbfbf6]/20 dark:border-[#33332e]/70 dark:bg-[#171713]/15" : "border-dashed border-[#d8d8cf]/45 dark:border-[#33332e]/45"}`}
        style={{
          left: `${(zone.x / MAP_WIDTH) * 100}%`,
          top: `${(zone.y / MAP_HEIGHT) * 100}%`,
          width: `${(zone.width / MAP_WIDTH) * 100}%`,
          height: `${(zone.height / MAP_HEIGHT) * 100}%`,
        }}
      >
        <span className={`absolute left-3 top-2 text-[9px] font-black uppercase tracking-[0.16em] ${hasCards ? "text-[#929289] dark:text-[#77776e]" : "text-[#c2c2b9] dark:text-[#44443e]"}`}>
          {zone.label}
        </span>
        {!hasCards && zone.emptyLabel ? (
          <span className="absolute inset-x-3 top-1/2 -translate-y-1/2 text-center text-[10px] font-semibold leading-4 text-[#a8a89f] dark:text-[#5f5f58]">
            {zone.emptyLabel}
          </span>
        ) : null}
      </div>
    );
  });
}

function SemanticContainers({ edges, nodeById, selectedCardId, matchesSearch }) {
  const containers = containmentGroups(edges, nodeById);
  if (!containers.length) return null;
  return (
    <svg className="pointer-events-none absolute inset-0 h-full w-full overflow-visible" viewBox={`0 0 ${MAP_WIDTH} ${MAP_HEIGHT}`} preserveAspectRatio="none" aria-label={`${containers.length} containment group${containers.length === 1 ? "" : "s"}`}>
      {containers.map(({ parent, children, edges: groupEdges, x, y, width, height }) => {
        const childIds = children.map((child) => child.id);
        const selected = selectedCardId && (parent.id === selectedCardId || childIds.includes(selectedCardId));
        const subdued = (selectedCardId && !selected) || !matchesSearch(parent.card) || children.every((child) => !matchesSearch(child.card));
        return (
          <g
            key={`container:${parent.id}`}
            data-semantic-container
            data-relationship-type="contains"
            data-relationship-count={groupEdges.length}
            data-parent-node={parent.id}
            data-child-node={children[0]?.id}
            data-child-nodes={childIds.join(" ")}
            opacity={subdued ? 0.08 : selected ? 0.9 : 0.52}
          >
            <rect x={x} y={y} width={width} height={height} rx="18" className="fill-sky-100/25 stroke-sky-500 dark:fill-sky-950/15 dark:stroke-sky-400" strokeWidth={selected ? 2.2 : 1.4} strokeDasharray="5 3" vectorEffect="non-scaling-stroke" />
            <text x={x + 12} y={y + 15} className="fill-sky-700 text-[8px] font-black uppercase tracking-[0.1em] dark:fill-sky-300">
              {compactLabel(nodeTitle(parent.card), 46)} · contains {children.length}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

function EvidenceEdges({ edges, nodeById, selectedCardId, matchesSearch }) {
  return (
    <svg className="pointer-events-none absolute inset-0 h-full w-full overflow-visible" viewBox={`0 0 ${MAP_WIDTH} ${MAP_HEIGHT}`} preserveAspectRatio="none" aria-label={`${edges.length} sourced relationships`}>
      <defs>
        <marker id="project-map-arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="5" markerHeight="5" orient="auto-start-reverse">
          <path d="M 0 0 L 8 4 L 0 8 z" fill="currentColor" />
        </marker>
      </defs>
      {edges.map((edge) => {
        const source = nodeById.get(edge.source_card_id);
        const target = nodeById.get(edge.target_card_id);
        if (!source || !target) return null;
        if (containmentRelation(edge, nodeById)) return null;
        const selected = selectedCardId && (edge.source_card_id === selectedCardId || edge.target_card_id === selectedCardId);
        const subdued = selectedCardId && !selected;
        const searchSubdued = !matchesSearch(source.card) || !matchesSearch(target.card);
        const visual = relationshipVisual(edge.relationship_type);
        const opacity = subdued || searchSubdued ? 0.08 : selected ? 0.92 : visual.opacity;
        const midX = (source.x + target.x) / 2;
        const midY = (source.y + target.y) / 2;
        return (
          <g key={edge.id} className={visual.tone} data-relationship-visual={visual.kind}>
            <line
              data-evidence-edge
              data-relationship-type={edge.relationship_type}
              x1={source.x}
              y1={source.y}
              x2={target.x}
              y2={target.y}
              stroke="currentColor"
              strokeWidth={selected ? Math.max(2.2, visual.width) : visual.width}
              strokeDasharray={visual.dash || undefined}
              opacity={opacity}
              markerEnd="url(#project-map-arrow)"
              vectorEffect="non-scaling-stroke"
            />
            {selected ? (
              <g transform={`translate(${midX} ${midY})`}>
                <rect x="-42" y="-10" width="84" height="20" rx="10" className="fill-[#fbfbf6] stroke-[#d8d8cf] dark:fill-[#171713] dark:stroke-[#3a3a34]" />
                <text textAnchor="middle" dominantBaseline="middle" className="fill-[#4f4f48] text-[9px] font-bold dark:fill-[#d8d8cf]">{edge.label || edge.relationship_type}</text>
              </g>
            ) : null}
          </g>
        );
      })}
    </svg>
  );
}

function containmentRelation(edge, nodeById) {
  const type = String(edge.relationship_type || "").toLowerCase();
  if (!["contains", "part_of", "contained_by"].includes(type)) return null;
  const source = nodeById.get(edge.source_card_id);
  const target = nodeById.get(edge.target_card_id);
  if (!source || !target) return null;
  const parent = type === "contains" ? source : target;
  const child = type === "contains" ? target : source;
  if (parent.laneId !== child.laneId) return null;
  return { edge, parent, child };
}

function containmentGroups(edges, nodeById) {
  const byParent = new Map();
  edges.forEach((edge) => {
    const relation = containmentRelation(edge, nodeById);
    if (!relation) return;
    const group = byParent.get(relation.parent.id) || { parent: relation.parent, children: new Map(), edges: [] };
    group.children.set(relation.child.id, relation.child);
    group.edges.push(edge);
    byParent.set(relation.parent.id, group);
  });
  return [...byParent.values()].map((group) => {
    const children = [...group.children.values()];
    const nodes = [group.parent, ...children];
    const horizontalPadding = 13;
    const topPadding = 25;
    const bottomPadding = 13;
    const minX = Math.min(...nodes.map((node) => node.x)) - MAP_NODE_SIZE.width / 2;
    const maxX = Math.max(...nodes.map((node) => node.x)) + MAP_NODE_SIZE.width / 2;
    const minY = Math.min(...nodes.map((node) => node.y)) - MAP_NODE_SIZE.height / 2;
    const maxY = Math.max(...nodes.map((node) => node.y)) + MAP_NODE_SIZE.height / 2;
    return {
      parent: group.parent,
      children,
      edges: group.edges,
      x: minX - horizontalPadding,
      y: minY - topPadding,
      width: maxX - minX + horizontalPadding * 2,
      height: maxY - minY + topPadding + bottomPadding,
    };
  });
}

function compactLabel(value, maxLength) {
  const text = String(value || "Parent");
  return text.length > maxLength ? `${text.slice(0, maxLength - 1).trim()}…` : text;
}

function relationshipVisual(type) {
  const value = String(type || "related_to").toLowerCase();
  if (["blocks", "blocked_by"].includes(value)) return { kind: "blocking", tone: "text-red-500", width: 2, opacity: 0.62, dash: null };
  if (["contradicts", "conflicts_with"].includes(value)) return { kind: "contradiction", tone: "text-red-500", width: 1.8, opacity: 0.58, dash: "7 4" };
  if (["supersedes", "superseded_by"].includes(value)) return { kind: "supersession", tone: "text-violet-500", width: 1.7, opacity: 0.52, dash: "9 4" };
  if (["depends_on", "enables", "confirms"].includes(value)) return { kind: "dependency", tone: "text-sky-600 dark:text-sky-400", width: 1.55, opacity: 0.46, dash: null };
  if (["created_from", "generated_by_agent", "implemented_in", "touches_file"].includes(value)) return { kind: "provenance", tone: "text-[#77776e] dark:text-[#8f8f86]", width: 1.2, opacity: 0.3, dash: "2 4" };
  return { kind: "association", tone: "text-[#77776e] dark:text-[#8f8f86]", width: 1.25, opacity: 0.28, dash: null };
}

function MapNode({ node, selected, related, searchMatch, onSelect }) {
  const { card } = node;
  const Icon = cardIcon(card);
  const relevance = sessionRelevance(card);
  const baseVisual = relevanceVisual(relevance);
  const focusOpacity = related && searchMatch ? baseVisual.opacity : Math.min(baseVisual.opacity, 0.13);
  const renderedOpacity = selected ? Math.max(focusOpacity, relevance === "not_relevant" ? 0.44 : 0.72) : focusOpacity;
  const colors = stateColors(observedCardState(card));
  const kind = nodeKind(card);
  const relevanceLabel = {
    relevant: "current project",
    unknown: "project match uncertain",
    not_relevant: "different project",
  }[relevance];
  const label = `${nodeTitle(card)}. ${kind}.${isSession(card) ? ` Project relevance: ${relevanceLabel}.` : ""}`;

  return (
    <button
      type="button"
      data-graph-node={card.id}
      data-card-category={card.category || "unknown"}
      data-card-state={card.status || "unknown"}
      data-relevance-status={isSession(card) ? relevance : "relevant"}
      aria-pressed={selected}
      aria-label={label}
      onClick={(event) => {
        event.stopPropagation();
        onSelect();
      }}
      className={`absolute z-10 flex min-h-[58px] w-[112px] -translate-x-1/2 -translate-y-1/2 items-center gap-2 px-2.5 py-2 text-left shadow-[0_5px_18px_rgba(23,23,19,.12)] transition-[opacity,filter,box-shadow,transform] duration-200 hover:z-20 hover:scale-[1.02] focus:z-20 focus:!opacity-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-[#171713] dark:shadow-[0_7px_22px_rgba(0,0,0,.3)] dark:focus-visible:ring-[#d9ff68] sm:w-[124px] ${nodeShape(card)} ${colors.surface} ${selected ? colors.selected : ""}`}
      style={{
        left: `${(node.x / MAP_WIDTH) * 100}%`,
        top: `${(node.y / MAP_HEIGHT) * 100}%`,
        opacity: renderedOpacity,
        filter: `saturate(${baseVisual.saturation}) ${relevance === "not_relevant" ? "grayscale(1)" : ""}`,
        borderStyle: baseVisual.borderStyle,
      }}
    >
      <span className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-md ${colors.icon}`} aria-hidden="true">
        <Icon className="h-3.5 w-3.5" />
      </span>
      <span className="line-clamp-2 text-sm font-extrabold leading-4 sm:text-[11px]">{nodeTitle(card)}</span>
    </button>
  );
}

function ProjectEmptyState({ onIndexProject, indexing, result, error, onCancel }) {
  const [repoPath, setRepoPath] = useState("");
  const [validationError, setValidationError] = useState("");

  const submit = (event) => {
    event.preventDefault();
    const value = repoPath.trim();
    if (!value || !value.startsWith("/")) {
      setValidationError("Enter an absolute local project path.");
      return;
    }
    setValidationError("");
    onIndexProject?.(value);
  };

  const errorMessage = validationError || error?.message || "";
  return (
    <div className="flex h-full min-h-[420px] items-center justify-center px-5 py-10">
      <div className="w-full max-w-lg text-center">
        <span className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl bg-[#171713] text-[#d9ff68] dark:bg-[#d9ff68] dark:text-[#171713]">
          <FolderGit2 className="h-5 w-5" />
        </span>
        <h2 className="mt-5 text-2xl font-semibold">Open your project</h2>
        <p className="mx-auto mt-2 max-w-sm text-sm leading-6 text-[#77776e] dark:text-[#aaa9a0]">
          Add the repository once. Context Engine will use it as the boundary for sessions and project evidence.
        </p>

        <form onSubmit={submit} className="mx-auto mt-6 flex max-w-md gap-2" noValidate>
          <label className="sr-only" htmlFor="project-repo-path">Local project path</label>
          <input
            id="project-repo-path"
            value={repoPath}
            onChange={(event) => setRepoPath(event.target.value)}
            placeholder="/absolute/path/to/project"
            className="h-11 min-w-0 flex-1 rounded-lg border border-[#d8d8cf] bg-[#fbfbf6] px-3.5 font-mono text-xs outline-none transition focus:border-[#77776e] focus:ring-4 focus:ring-[#77776e]/10 dark:border-[#33332e] dark:bg-[#171713]"
          />
          <button type="submit" disabled={indexing || !onIndexProject} className="inline-flex h-11 items-center justify-center gap-2 rounded-lg bg-[#171713] px-4 text-xs font-bold text-white transition hover:bg-[#34342e] disabled:opacity-50 dark:bg-[#d9ff68] dark:text-[#171713]">
            {indexing ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
            Open
          </button>
        </form>

        {errorMessage ? <p role="alert" className="mt-3 text-xs font-semibold text-red-600 dark:text-red-400">{errorMessage}</p> : null}
        {result ? (
          <div role="status" className="mx-auto mt-4 flex max-w-md items-start gap-2 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2.5 text-left text-xs text-emerald-800 dark:border-emerald-900/60 dark:bg-emerald-950/30 dark:text-emerald-200">
            <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />
            <span><strong>Project opened.</strong> {result.files_indexed ?? 0} files indexed from the current repository state.</span>
          </div>
        ) : null}
        <div className="mt-5 flex items-center justify-center gap-3 text-[10px] font-semibold text-[#77776e] dark:text-[#aaa9a0]">
          <Link to="/app/connectors" className="underline decoration-[#aaa9a0] underline-offset-4 hover:text-[#171713] dark:hover:text-white">Choose a GitHub repository</Link>
          {onCancel ? <button type="button" onClick={onCancel} className="underline decoration-[#aaa9a0] underline-offset-4 hover:text-[#171713] dark:hover:text-white">Cancel</button> : null}
        </div>
      </div>
    </div>
  );
}

function ProjectReadyState() {
  return (
    <div className="flex h-full min-h-[420px] items-center justify-center px-5 py-10">
      <div className="w-full max-w-md text-center">
        <span className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl border border-[#d8d8cf] bg-[#fbfbf6] text-[#68685f] dark:border-[#33332e] dark:bg-[#171713] dark:text-[#aaa9a0]">
          <FolderGit2 className="h-5 w-5" />
        </span>
        <h2 className="mt-5 text-xl font-semibold">Your project is ready</h2>
        <p className="mx-auto mt-2 max-w-sm text-sm leading-6 text-[#77776e] dark:text-[#aaa9a0]">
          Add an AI coding session or source. The map will appear when there is project evidence to show.
        </p>
        <Link to="/app/sources" className="mt-6 inline-flex h-10 items-center justify-center rounded-lg bg-[#171713] px-4 text-xs font-bold text-white transition hover:bg-[#34342e] dark:bg-[#d9ff68] dark:text-[#171713]">
          Add evidence
        </Link>
      </div>
    </div>
  );
}

function BuildToast({ result, error }) {
  const warnings = result?.warnings?.length || result?.errors?.length || result?.documents?.failed || 0;
  return (
    <div role={error ? "alert" : "status"} className={`fixed bottom-4 left-1/2 z-50 flex max-w-[min(440px,calc(100%-2rem))] -translate-x-1/2 items-start gap-2 rounded-lg border px-3 py-2 text-[10px] font-bold shadow-lg ${error ? TONE_CLASSES.red : warnings ? TONE_CLASSES.amber : TONE_CLASSES.green}`}>
      {error || warnings ? <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" /> : <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0" />}
      {error?.message || buildSummary(result)}
    </div>
  );
}

function isSession(card) {
  return ["agent_session", "session"].includes(card?.category);
}

function sessionRelevance(card) {
  if (!isSession(card)) return "relevant";
  const status = card?.workspace_relevance?.status;
  return ["relevant", "unknown", "not_relevant"].includes(status) ? status : "unknown";
}

function relevanceVisual(status) {
  if (status === "not_relevant") return { opacity: 0.16, saturation: 0, borderStyle: "dashed" };
  if (status === "unknown") return { opacity: 0.48, saturation: 0.55, borderStyle: "dotted" };
  return { opacity: 1, saturation: 1, borderStyle: "solid" };
}

function nodeTitle(card) {
  if (isSession(card)) return sessionIdentity(card).title;
  if (card?.category === "pull_request") return remoteNodeTitle(card, "PR");
  if (card?.category === "issue") return remoteNodeTitle(card, "Issue");
  if (card?.category === "supporting_evidence") return supportingNodeTitle(card);
  return sentenceCase(cardDisplayLine(card, card?.category || "summary", 7));
}

function supportingNodeTitle(card) {
  const candidates = [
    card?.summary,
    ...(card?.provenance || []).map((source) => source.excerpt),
    card?.title,
  ];
  const selected = candidates.find((value) => (
    value
    && !/\bhub for messages\b|^(?:slack\s+)?channel\s*[:#]|^source type\s*:/i.test(String(value).trim())
  ));
  const evidenceText = String(selected || card?.summary || card?.title || "")
    .replace(/^#?\s*Context Engine\s*(?:[-\u2013\u2014:]\s*)?/i, "");
  return sentenceCase(preciseLine(evidenceText, 7));
}

function remoteNodeTitle(card, prefix) {
  const number = card?.remote_item?.number;
  const title = String(card?.remote_item?.title || "").trim();
  const identity = number ? `${prefix} #${number}` : prefix;
  return title ? `${identity} · ${title}` : identity;
}

function sentenceCase(value) {
  return value ? `${value.charAt(0).toUpperCase()}${value.slice(1)}` : "";
}

function nodeKind(card) {
  const labels = {
    agent_session: "AI session",
    blocker: "Blocker",
    decision: "Decision",
    document_finding: "Document finding",
    code_area: "Repository area",
    issue: "Issue snapshot",
    pull_request: "Pull request snapshot",
    supporting_evidence: "Supporting evidence",
    task: "Next task",
  };
  return labels[card?.category] || String(card?.type || "Evidence").replaceAll("_", " ");
}

function nodeShape(card) {
  if (isSession(card)) return "rounded-2xl border-2";
  if (["blocker", "issue"].includes(card?.category)) return "rounded-md border-2";
  if (card?.category === "decision") return "rounded-xl border";
  return "rounded-lg border";
}

function stateColors(status) {
  const map = {
    verified: {
      surface: "border-emerald-300 bg-emerald-50 text-emerald-950 dark:border-emerald-700 dark:bg-emerald-950/70 dark:text-emerald-50",
      icon: "bg-emerald-200/70 text-emerald-800 dark:bg-emerald-800/60 dark:text-emerald-100",
      selected: "ring-2 ring-emerald-500/45",
    },
    blocked: {
      surface: "border-red-400 bg-red-50 text-red-950 dark:border-red-600 dark:bg-red-950/70 dark:text-red-50",
      icon: "bg-red-200/80 text-red-800 dark:bg-red-800/60 dark:text-red-100",
      selected: "ring-2 ring-red-500/50",
    },
    conflict: {
      surface: "border-red-400 bg-red-50 text-red-950 dark:border-red-600 dark:bg-red-950/70 dark:text-red-50",
      icon: "bg-red-200/80 text-red-800 dark:bg-red-800/60 dark:text-red-100",
      selected: "ring-2 ring-red-500/50",
    },
    stale: {
      surface: "border-[#b8b8af] bg-[#e9e9e1] text-[#55554e] dark:border-[#55554e] dark:bg-[#242420] dark:text-[#c8c8be]",
      icon: "bg-[#d8d8cf] text-[#68685f] dark:bg-[#33332e] dark:text-[#aaa9a0]",
      selected: "ring-2 ring-[#77776e]/45",
    },
    needs_review: {
      surface: "border-[#b8b8af] bg-[#fbfbf6] text-[#34342e] dark:border-[#4a4a43] dark:bg-[#1b1b18] dark:text-[#e8e8e0]",
      icon: "bg-[#e8e8e0] text-[#68685f] dark:bg-[#292925] dark:text-[#aaa9a0]",
      selected: "ring-2 ring-[#77776e]/45 dark:ring-[#d9ff68]/40",
    },
    open: {
      surface: "border-sky-300 bg-sky-50 text-sky-950 dark:border-sky-800 dark:bg-sky-950/65 dark:text-sky-50",
      icon: "bg-sky-200/75 text-sky-800 dark:bg-sky-800/60 dark:text-sky-100",
      selected: "ring-2 ring-sky-500/45",
    },
    closed: {
      surface: "border-[#b8b8af] bg-[#f1f1e9] text-[#55554e] dark:border-[#4a4a43] dark:bg-[#242420] dark:text-[#d8d8cf]",
      icon: "bg-[#d8d8cf] text-[#68685f] dark:bg-[#33332e] dark:text-[#b8b8af]",
      selected: "ring-2 ring-[#77776e]/45",
    },
    draft: {
      surface: "border-violet-300 bg-violet-50 text-violet-950 dark:border-violet-800 dark:bg-violet-950/65 dark:text-violet-50",
      icon: "bg-violet-200/75 text-violet-800 dark:bg-violet-800/60 dark:text-violet-100",
      selected: "ring-2 ring-violet-500/45",
    },
  };
  return map[status] || {
    surface: "border-violet-300 bg-white text-[#171713] dark:border-violet-800 dark:bg-[#1b1b18] dark:text-[#f4f4ec]",
    icon: "bg-violet-100 text-violet-700 dark:bg-violet-950 dark:text-violet-200",
    selected: "ring-2 ring-violet-500/45 dark:ring-[#d9ff68]/45",
  };
}

function observedCardState(card) {
  const remoteState = card?.remote_item?.observed_status || card?.remote_item?.provider_state;
  if (["open", "closed", "draft"].includes(remoteState)) return remoteState;
  if (remoteState === "merged") return "verified";
  return card?.status;
}

function cardSearchText(card) {
  return [card?.title, card?.summary, card?.why_it_matters, card?.type, card?.category, card?.status, card?.session?.session_id, card?.session?.branch, card?.remote_item?.repository]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
}

function clampZoom(value) {
  return Math.max(0.45, Math.min(1.8, Number(value.toFixed(2))));
}

function defaultMapView(nodes) {
  if ((globalThis.innerWidth || 1024) >= 640) {
    return { zoom: 1, pan: { x: 0, y: 0 } };
  }
  const relevantNodes = nodes.filter((node) => sessionRelevance(node.card) !== "not_relevant");
  const focusNodes = relevantNodes.length ? relevantNodes : nodes;
  const centerX = focusNodes.length
    ? focusNodes.reduce((sum, node) => sum + node.x, 0) / focusNodes.length
    : MAP_WIDTH / 2;
  const centerY = focusNodes.length
    ? focusNodes.reduce((sum, node) => sum + node.y, 0) / focusNodes.length
    : MAP_HEIGHT / 2;
  const zoom = 0.72;
  return {
    zoom,
    pan: {
      x: Math.round((MAP_WIDTH / 2 - centerX) * zoom),
      y: Math.round((MAP_HEIGHT / 2 - centerY) * zoom),
    },
  };
}

function buildSummary(result) {
  if (!result) return "Project map refreshed.";
  const processed = result.documents?.processed ?? result.docs_processed ?? 0;
  const reprocessed = result.documents?.reprocessed ?? result.docs_reprocessed ?? 0;
  const created = result.components?.created ?? result.components_created ?? 0;
  const failed = result.documents?.failed ?? result.errors?.length ?? 0;
  if (processed === 0 && reprocessed === 0 && failed === 0) return "Imported evidence was already up to date.";
  return `${processed + reprocessed} source snapshot${processed + reprocessed === 1 ? "" : "s"} read · ${created} record${created === 1 ? "" : "s"} added${failed ? ` · ${failed} failed` : ""}.`;
}

function formatDigestTimestamp(value) {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return date.toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

async function writeClipboard(value) {
  if (globalThis.navigator?.clipboard?.writeText) {
    await globalThis.navigator.clipboard.writeText(value);
    return;
  }
  const textarea = document.createElement("textarea");
  textarea.value = value;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "fixed";
  textarea.style.opacity = "0";
  document.body.appendChild(textarea);
  textarea.select();
  const copied = document.execCommand?.("copy");
  textarea.remove();
  if (!copied) throw new Error("Clipboard unavailable");
}
