import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useNavigate, useSearchParams } from "react-router-dom";
import {
  ArrowLeft,
  ArrowRight,
  ArrowUpRight,
  Check,
  Copy,
  FileSearch,
  FolderGit2,
  GitFork,
  History,
  Loader2,
  Radio,
  RefreshCw,
  Search,
  Sparkles,
  X,
} from "lucide-react";

import { api } from "../api/client";
import { useSessionLibrary, useSyncSessionLibrary } from "../api/hooks";
import {
  HARNESS_META,
  HARNESS_ORDER,
  HarnessArtwork,
  HarnessLogo,
} from "../components/HarnessBrand";
import { HarnessArchiveCard } from "../components/HarnessCard";
import HarnessDeckBackdrop from "../components/HarnessDeckBackdrop";
import ProductLoadingState from "../components/ProductLoadingState";
import WorkspaceTopicGate from "../components/WorkspaceTopicGate";
import { formatTimeAgo } from "../context-map/digest";
import { useProductWorkspace } from "./useProductWorkspace";

const INITIAL_SESSION_COUNT = 24;


export default function SessionLibrary() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const workspace = useProductWorkspace();
  const libraryQuery = useSessionLibrary(workspace.activeWorkspaceId);
  const syncMutation = useSyncSessionLibrary();
  const sessionsRef = useRef(null);
  const [selectedHarness, setSelectedHarness] = useState(null);
  const [hoveredHarness, setHoveredHarness] = useState(null);
  const [search, setSearch] = useState("");
  const [visibleSessionCount, setVisibleSessionCount] = useState(INITIAL_SESSION_COUNT);
  const [evidenceSelection, setEvidenceSelection] = useState(null);
  const closeEvidence = useCallback(() => {
    setEvidenceSelection(null);
    navigate("/app/library", { replace: true });
  }, [navigate]);

  const library = libraryQuery.data;
  const sessions = library?.sessions || [];
  const harnesses = useMemo(() => {
    const byType = Object.fromEntries((library?.harnesses || []).map((item) => [item.connector_type, item]));
    return HARNESS_ORDER.map((connectorType) => {
      const item = byType[connectorType] || {
        connector_type: connectorType,
        adapter_state: "not_scanned",
        session_count: 0,
        message: "Waiting for the first local scan.",
      };
      const harnessSessions = sessions.filter((session) => session.connector_type === connectorType);
      return {
        ...item,
        ...HARNESS_META[connectorType],
        topic_count: new Set(harnessSessions.flatMap((session) => session.topics || [])).size,
      };
    });
  }, [library?.harnesses, sessions]);

  const selectedHarnessMeta = harnesses.find((item) => item.connector_type === selectedHarness) || null;
  const filteredSessions = useMemo(() => {
    if (!selectedHarness) return [];
    const query = search.trim().toLowerCase();
    return sessions.filter((item) => {
      if (item.connector_type !== selectedHarness) return false;
      if (!query) return true;
      return [item.title, item.model, item.cwd, item.preview, ...(item.topics || [])]
        .filter(Boolean)
        .join(" ")
        .toLowerCase()
        .includes(query);
    });
  }, [search, selectedHarness, sessions]);
  const visibleSessions = filteredSessions.slice(0, visibleSessionCount);

  useEffect(() => {
    const requestedSourceId = searchParams.get("source");
    if (!requestedSourceId || !sessions.length) return;
    const requestedSession = sessions.find((item) => item.source_document_id === requestedSourceId);
    if (!requestedSession) return;
    const requestedTopic = searchParams.get("topic");
    const topics = requestedSession.topics || [];
    const topic = topics.includes(requestedTopic)
      ? requestedTopic
      : requestedSession.selected_topic || requestedSession.latest_topic || topics.at(-1) || requestedSession.title;
    setSelectedHarness(requestedSession.connector_type);
    setEvidenceSelection((current) => (
      current?.session?.source_document_id === requestedSession.source_document_id && current.topic === topic
        ? current
        : { session: requestedSession, topic }
    ));
  }, [searchParams, sessions]);

  const selectForNow = (item, topic) => {
    if (!workspace.activeWorkspaceId) return;
    const objective = String(topic || item.latest_topic || item.title || "").trim();
    const params = new URLSearchParams();
    if (objective) {
      params.set("objective", objective);
      if (topic) params.set("objective_source", "session");
    }
    if (item.cwd) params.set("repo_path", item.cwd);
    if (item.connector_type && item.session_id) {
      params.set("source_provider", item.connector_type);
      params.set("source_session", item.session_id);
    }
    navigate({ pathname: "/app", search: params.toString() ? `?${params}` : "" });
  };

  useEffect(() => {
    setSearch("");
    setVisibleSessionCount(INITIAL_SESSION_COUNT);
    if (selectedHarness) {
      window.setTimeout(() => sessionsRef.current?.scrollIntoView?.({ behavior: "smooth", block: "start" }), 100);
    }
  }, [selectedHarness, workspace.activeWorkspaceId]);

  if (!workspace.workspacesQuery.isLoading && !workspace.activeWorkspaceId) {
    return (
      <WorkspaceTopicGate
        workspaces={workspace.workspaces}
        selectedId={workspace.selectedId}
        onSelect={workspace.setSelectedId}
      />
    );
  }

  return (
    <div className="relative mx-auto w-full max-w-7xl space-y-8 pb-14">
      <header className="daemonstate-resume-header group relative min-h-56 overflow-hidden rounded-[2rem] border border-[#d8d8cf] bg-[#f7f7f1] px-5 py-7 text-[#171713] dark:border-[#292925] dark:bg-[#0c0c0a] dark:text-white sm:px-8 sm:py-9 lg:px-10">
        <div aria-hidden="true" className="absolute -right-20 -top-24 h-72 w-72 rounded-full bg-[#d9ff68]/25 blur-3xl dark:bg-[#d9ff68]/10" />
        <HarnessDeckBackdrop />
        <div className="relative flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <h1 className="text-3xl font-black tracking-[-0.035em] sm:text-4xl">Session Library</h1>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-[#68685f] dark:text-[#aaa9a0]">
              Choose a session or topic, then finish the handoff from the canonical Continue screen.
            </p>
            {library ? (
              <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-2 text-[10px] font-black uppercase tracking-[0.13em] text-[#85857c]">
                <span>{library.stats?.sessions || 0} sessions</span>
                <span className="h-1 w-1 rounded-full bg-[#b8dc45]" />
                <span>{library.stats?.topics || 0} topics</span>
                <span className="h-1 w-1 rounded-full bg-[#b8dc45]" />
                <span>{library.stats?.harnesses || 0} harnesses detected</span>
              </div>
            ) : null}
          </div>
          <button
            type="button"
            onClick={() => syncMutation.mutate({ workspaceId: workspace.activeWorkspaceId })}
            disabled={!workspace.activeWorkspaceId || syncMutation.isPending}
            className="inline-flex h-11 items-center justify-center gap-2 self-start rounded-xl border border-[#9dbc47]/45 bg-[#d9ff68]/30 px-5 text-xs font-black text-[#37420f] shadow-[0_8px_24px_rgba(157,188,71,0.14),inset_0_1px_0_rgba(255,255,255,0.28)] backdrop-blur-xl transition hover:-translate-y-0.5 hover:border-[#9dbc47]/65 hover:bg-[#d9ff68]/40 disabled:cursor-not-allowed disabled:opacity-60 dark:border-[#d9ff68]/35 dark:bg-[#d9ff68]/15 dark:text-[#eaffaa] dark:shadow-[0_8px_28px_rgba(217,255,104,0.08),inset_0_1px_0_rgba(255,255,255,0.1)] dark:hover:border-[#d9ff68]/55 dark:hover:bg-[#d9ff68]/25 lg:self-auto"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${syncMutation.isPending ? "animate-spin" : ""}`} />
            {syncMutation.isPending ? "Syncing local history…" : "Sync now"}
          </button>
        </div>
      </header>

      {syncMutation.isError ? (
        <Notice tone="error">Sync failed: {syncMutation.error?.message}</Notice>
      ) : null}
      {syncMutation.data?.sync?.failed ? (
        <Notice tone="warning">
          {syncMutation.data.sync.failed} session{syncMutation.data.sync.failed === 1 ? "" : "s"} could not be read; the remaining history was synced.
        </Notice>
      ) : null}
      {libraryQuery.isLoading && !library ? (
        <EmptyState title="Opening your session history…" detail="Loading the saved session index for this project." loading />
      ) : null}
      {libraryQuery.isError ? (
        <EmptyState title="Could not load the session library" detail={libraryQuery.error?.message} error />
      ) : null}

      {library ? (
        <>
          <section aria-labelledby="harness-heading" className="relative">
            <div className="mb-5 flex items-end justify-between gap-4">
              <div>
                <p className="text-[10px] font-black uppercase tracking-[0.18em] text-[#85857c]">01 · Choose the source</p>
                <h2 id="harness-heading" className="mt-1 text-xl font-black tracking-tight">AI harnesses</h2>
              </div>
              <p className="hidden max-w-sm text-right text-[10px] font-semibold leading-4 text-[#85857c] sm:block">
                Hover to fan the deck. Select a card to open its session archive.
              </p>
            </div>

            <div
              className="daemonstate-harness-fan daemonstate-archive-fan relative -mx-4 flex snap-x snap-mandatory items-stretch justify-start gap-4 overflow-x-auto overscroll-x-contain pb-8 pt-5 sm:-mx-7 md:mx-auto md:max-w-4xl md:snap-none md:gap-0 md:overflow-visible md:px-0 md:py-0"
              aria-label="Session library harnesses"
              onMouseLeave={() => setHoveredHarness(null)}
            >
              {harnesses.map((item, index) => {
                const hoverIndex = harnesses.findIndex((candidate) => candidate.connector_type === hoveredHarness);
                const hovered = hoveredHarness === item.connector_type;
                const selected = selectedHarness === item.connector_type;
                const distanceFromHover = hoverIndex >= 0 ? index - hoverIndex : 0;
                const translateX = hoverIndex >= 0 && !hovered ? distanceFromHover * 24 : 0;
                const translateY = hovered || selected ? -18 : Math.abs(distanceFromHover) * 5;
                return (
                  <HarnessArchiveCard
                    key={item.connector_type}
                    item={item}
                    index={index}
                    hovered={hovered}
                    selected={selected}
                    translateX={translateX}
                    translateY={translateY}
                    onHover={() => setHoveredHarness(item.connector_type)}
                    onSelect={() => setSelectedHarness(item.connector_type)}
                  />
                );
              })}
            </div>
          </section>

          <section ref={sessionsRef} aria-labelledby="sessions-heading" className="scroll-mt-6">
            {selectedHarnessMeta ? (
              <>
                <div className="mb-5 flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
                  <div>
                    <button
                      type="button"
                      onClick={() => setSelectedHarness(null)}
                      className="mb-3 inline-flex items-center gap-1.5 text-[10px] font-black uppercase tracking-[0.14em] text-[#77776e] transition hover:text-[#171713] dark:hover:text-white"
                    >
                      <ArrowLeft className="h-3.5 w-3.5" /> All harnesses
                    </button>
                    <p className="text-[10px] font-black uppercase tracking-[0.18em] text-[#85857c]">02 · Browse the archive</p>
                    <div className="mt-1 flex items-center gap-2">
                      <h2 id="sessions-heading" className="text-xl font-black tracking-tight">{selectedHarnessMeta.name} sessions</h2>
                      <span aria-label={`${filteredSessions.length} sessions`} className="rounded-full bg-[#ecece4] px-2.5 py-1 text-[9px] font-black dark:bg-[#252521]">{filteredSessions.length}</span>
                    </div>
                    <p className="mt-1 text-xs leading-5 text-[#68685f] dark:text-[#aaa9a0]">
                      Continue the session’s newest topic, or open Topics to choose another. Evidence stays separate.
                    </p>
                  </div>
                  <label className="relative block">
                    <Search className="pointer-events-none absolute left-3 top-3 h-3.5 w-3.5 text-[#85857c]" />
                    <span className="sr-only">Search {selectedHarnessMeta.name} sessions</span>
                    <input
                      type="search"
                      value={search}
                      onChange={(event) => setSearch(event.target.value)}
                      placeholder={`Search ${selectedHarnessMeta.name}`}
                      className="h-10 w-full rounded-xl border border-[#d8d8cf] bg-[#fbfbf6] pl-9 pr-3 text-xs font-semibold outline-none transition focus:border-[#9fbd3f] focus:ring-2 focus:ring-[#d9ff68]/30 dark:border-[#292925] dark:bg-[#141411] sm:w-72"
                    />
                  </label>
                </div>

                {filteredSessions.length ? (
                  <div className="grid items-start gap-4 md:grid-cols-2 xl:grid-cols-3">
                    {visibleSessions.map((item) => (
                      <SessionCard
                        key={item.id}
                        item={item}
                        selected={item.selected_for_now}
                        selectedTopic={item.selected_topic}
                        selectingTopic={null}
                        onSelectSession={() => selectForNow(item)}
                        onSelectTopic={(topic) => selectForNow(item, topic)}
                        onOpen={(topic) => setEvidenceSelection({ session: item, topic })}
                      />
                    ))}
                    {visibleSessionCount < filteredSessions.length ? (
                      <button
                        type="button"
                        onClick={() => setVisibleSessionCount((count) => count + INITIAL_SESSION_COUNT)}
                        className="flex min-h-44 items-center justify-center rounded-2xl border border-dashed border-[#c9c9bf] bg-[#fbfbf6]/45 p-5 text-xs font-black transition hover:-translate-y-0.5 hover:border-[#b8dc45] hover:bg-[#fbfbf6] dark:border-[#34342f] dark:bg-[#141411]/45 dark:hover:border-[#718a2c]"
                      >
                        Show {Math.min(INITIAL_SESSION_COUNT, filteredSessions.length - visibleSessionCount)} more
                      </button>
                    ) : null}
                  </div>
                ) : (
                  <EmptyState title="No sessions match this search" detail="Try a different topic, repository, or model name." />
                )}
              </>
            ) : (
              <div className="rounded-3xl border border-dashed border-[#d2d2c8] bg-[#fbfbf6]/60 px-6 py-12 text-center dark:border-[#31312c] dark:bg-[#141411]/50">
                <Sparkles className="mx-auto h-5 w-5 text-[#9fbd3f]" />
                <p className="mt-3 text-sm font-black">Choose a harness to open its session archive</p>
                <p className="mx-auto mt-2 max-w-md text-xs leading-5 text-[#77776e] dark:text-[#aaa9a0]">
                  The library keeps providers separate at the top, then reveals the topic-level evidence inside each session.
                </p>
              </div>
            )}
          </section>
        </>
      ) : null}

      {evidenceSelection ? createPortal(
        <EvidenceDrawer
          selection={evidenceSelection}
          workspaceId={workspace.activeWorkspaceId}
          onSelectTopic={(topic) => setEvidenceSelection((current) => ({ ...current, topic }))}
          onUseTopic={(topic) => selectForNow(evidenceSelection.session, topic)}
          selecting={false}
          onClose={closeEvidence}
        />,
        document.body,
      ) : null}
    </div>
  );
}


function SessionCard({ item, selected, selectedTopic, selectingTopic, onSelectSession, onSelectTopic, onOpen }) {
  const [revealed, setRevealed] = useState(false);
  const folder = item.cwd ? item.cwd.split("/").filter(Boolean).at(-1) : null;
  const topics = item.topics || [];
  const latestTopic = item.latest_topic || topics.at(-1) || item.title;
  const meta = HARNESS_META[item.connector_type] || HARNESS_META.codex;

  return (
    <article
      data-session-card={item.id}
      data-selected={selected ? "true" : "false"}
      onMouseEnter={() => setRevealed(true)}
      onMouseLeave={() => setRevealed(false)}
      onFocusCapture={() => setRevealed(true)}
      onBlurCapture={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) setRevealed(false);
      }}
      className="group relative min-h-56 overflow-hidden rounded-2xl border border-[#d8d8cf] bg-[#fbfbf6] p-5 outline-none transition-all duration-300 hover:-translate-y-1 hover:shadow-[0_18px_40px_rgba(23,23,19,0.09)] focus-within:ring-2 focus-within:ring-[#b8dc45] dark:border-[#292925] dark:bg-[#141411]"
      style={{ borderColor: revealed ? meta.accent : undefined }}
    >
      <span className="absolute inset-x-0 top-0 h-0.5 origin-left scale-x-0 transition-transform duration-500 group-hover:scale-x-100 group-focus-visible:scale-x-100" style={{ backgroundColor: meta.accent }} />
      <span
        aria-hidden="true"
        className="pointer-events-none absolute -right-[9%] top-12 h-44 w-52 origin-center opacity-[0.055] transition-[transform,opacity] duration-700 ease-out group-hover:-translate-x-3 group-hover:scale-110 group-hover:opacity-[0.09] dark:opacity-[0.08] dark:group-hover:opacity-[0.12]"
      >
        <HarnessArtwork type={item.connector_type} />
      </span>

      <div className="relative">
        <div className="flex items-start justify-end gap-3">
          <div className="flex items-center gap-2 text-[9px] font-black uppercase tracking-[0.12em] text-[#85857c]">
            {selected ? <span className="rounded-full bg-[#d9ff68] px-2 py-1 text-[#37420f]">Selected</span> : null}
            {item.forked_from ? (
              <span
                aria-label={`Continued in a new task from ${item.forked_from.title}`}
                title={`Continued in a new task from ${item.forked_from.title}`}
                className="inline-flex items-center gap-1 rounded-full border border-[#d8d8cf] px-2 py-1 text-[#68685f] dark:border-[#3a3a34] dark:text-[#c7c7bd]"
              >
                <GitFork className="h-3 w-3" /> Fork
              </span>
            ) : null}
            {(item.compaction_checkpoints || []).length ? (
              <button
                type="button"
                aria-label={`Open ${item.compaction_checkpoints.length} context checkpoints for ${item.title}`}
                title="Open context captured automatically before harness compaction"
                onClick={(event) => {
                  event.stopPropagation();
                  onOpen(selectedTopic || latestTopic);
                }}
                className="inline-flex items-center gap-1 rounded-full border border-[#b8ca7b] bg-[#f2f7df] px-2 py-1 text-[#58691c] transition hover:border-[#8aa62a] hover:bg-[#eaf3cb] dark:border-[#53602f] dark:bg-[#d9ff68]/[0.07] dark:text-[#d9ff68]"
              >
                <History className="h-3 w-3" /> {item.compaction_checkpoints.length} checkpoints
              </button>
            ) : null}
            {item.live ? <Radio className="h-3 w-3 text-emerald-600" /> : null}
            {item.updated_at ? formatTimeAgo(item.updated_at) : "Unknown time"}
          </div>
        </div>

        <p className="mt-4 text-[8px] font-black uppercase tracking-[0.16em] text-[#85857c]">Session title</p>
        <h3 className="mt-1 line-clamp-2 text-base font-black leading-6 tracking-[-0.015em]">{item.title}</h3>
        {item.forked_from ? (
          <p className="mt-1.5 flex min-w-0 items-center gap-1.5 text-[9px] font-semibold text-[#77776e] dark:text-[#aaa9a0]">
            <GitFork className="h-3 w-3 shrink-0" aria-hidden="true" />
            <span className="truncate">Continued from · {item.forked_from.title}</span>
          </p>
        ) : null}
        {selectedTopic || latestTopic ? (
          <p className="mt-2 line-clamp-1 text-[9px] font-bold text-[#58691c] dark:text-[#d9ff68]">{selectedTopic ? "Selected" : "Latest"} · {selectedTopic || latestTopic}</p>
        ) : null}
        <div className="mt-3 flex items-center justify-between gap-3">
          <div className="flex min-w-0 items-center gap-2 text-[10px] font-semibold text-[#77776e] dark:text-[#aaa9a0]">
            {folder ? <><FolderGit2 className="h-3.5 w-3.5 shrink-0" /><span className="truncate">{folder}</span></> : <span>Local session</span>}
          </div>
          <div className="shrink-0 rounded-xl bg-[#efefe7] px-3 py-2 text-right dark:bg-[#252521]">
            <span className="block text-lg font-black leading-none">{topics.length}</span>
            <span className="mt-1 block text-[8px] font-black uppercase tracking-[0.13em] text-[#85857c]">topics</span>
          </div>
        </div>

        <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-[#e1e1d8] pt-3 dark:border-[#30302b]">
          <button
            type="button"
            aria-label={`Continue latest topic from ${item.title}`}
            onClick={onSelectSession}
            disabled={Boolean(selectingTopic)}
            className="inline-flex items-center gap-1.5 text-[9px] font-black uppercase tracking-[0.12em] text-[#58691c] transition hover:text-[#171713] disabled:cursor-wait disabled:opacity-60 dark:text-[#d9ff68] dark:hover:text-white"
          >
            {selectingTopic === "__latest__" ? "Selecting…" : "Continue latest"}
            <ArrowRight className="h-3 w-3" />
          </button>
          <div className="flex items-center gap-3">
            {(item.compaction_checkpoints || []).length ? (
              <button
                type="button"
                aria-label={`Open checkpoints for ${item.title}`}
                onClick={(event) => {
                  event.stopPropagation();
                  onOpen(selectedTopic || latestTopic);
                }}
                className="inline-flex items-center gap-1 text-[8px] font-bold uppercase tracking-[0.12em] text-[#58691c] transition hover:text-[#171713] dark:text-[#d9ff68] dark:hover:text-white"
              >
                Checkpoints <History className="h-3 w-3" />
              </button>
            ) : null}
            <button
              type="button"
              aria-label={`Choose a topic from ${item.title}`}
              aria-expanded={revealed}
              onClick={() => setRevealed(true)}
              className="text-[8px] font-bold uppercase tracking-[0.12em] text-[#85857c] transition hover:text-[#171713] dark:hover:text-white"
            >
              Topics
            </button>
            <button
              type="button"
              aria-label={`Inspect evidence for ${item.title}`}
              onClick={(event) => {
                event.stopPropagation();
                onOpen(selectedTopic || latestTopic);
              }}
              className="inline-flex items-center gap-1 text-[8px] font-bold uppercase tracking-[0.12em] text-[#85857c] transition hover:text-[#171713] dark:hover:text-white"
            >
              Evidence <ArrowUpRight className="h-3 w-3" />
            </button>
          </div>
        </div>

        <div
          aria-hidden={!revealed}
          className={`overflow-hidden transition-all duration-500 ease-out ${revealed ? "mt-4 max-h-52 opacity-100" : "max-h-0 opacity-0"}`}
        >
          <div className="border-t border-[#e1e1d8] pt-3 dark:border-[#30302b]">
            <p className="mb-2 text-[8px] font-black uppercase tracking-[0.16em] text-[#85857c]">Topics discussed</p>
            <div className="flex flex-wrap gap-1.5">
              {topics.length ? topics.map((topic) => (
                <button
                  type="button"
                  key={topic}
                  tabIndex={revealed ? 0 : -1}
                  aria-label={`Continue ${topic} from ${item.title}`}
                  onClick={(event) => {
                    event.stopPropagation();
                    onSelectTopic(topic);
                  }}
                  className="inline-flex items-center gap-1 rounded-lg border border-[#d8d8cf] bg-white/80 px-2.5 py-1.5 text-left text-[9px] font-bold leading-4 transition hover:border-transparent disabled:cursor-wait disabled:opacity-60 dark:border-[#3b3b35] dark:bg-black/20"
                  disabled={Boolean(selectingTopic)}
                  style={{ color: meta.accent }}
                >
                  {selectingTopic === topic ? "Selecting…" : topic}
                  <ArrowRight className="h-2.5 w-2.5 shrink-0" />
                </button>
              )) : <span className="text-[10px] font-semibold text-[#85857c]">No distinct topics extracted.</span>}
            </div>
            <p className="mt-3 inline-flex items-center gap-1 text-[9px] font-black uppercase tracking-[0.12em]" style={{ color: meta.accent }}>
              Choose a topic for Continue <ArrowRight className="h-3 w-3" />
            </p>
          </div>
        </div>
      </div>
    </article>
  );
}


function EvidenceDrawer({ selection, workspaceId, onSelectTopic, onUseTopic, selecting, onClose }) {
  const navigate = useNavigate();
  const { session, topic } = selection;
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [copied, setCopied] = useState(false);
  const [checkpointState, setCheckpointState] = useState({
    status: "idle",
    checkpointId: null,
    error: "",
  });
  const closeRef = useRef(null);
  const meta = HARNESS_META[session.connector_type] || HARNESS_META.codex;

  useEffect(() => {
    let active = true;
    setDetail(null);
    setError(null);
    setLoading(true);
    setCheckpointState({ status: "idle", checkpointId: null, error: "" });
    const params = new URLSearchParams();
    if (workspaceId) params.set("workspace_id", workspaceId);
    api.get(`/sources/${session.source_document_id}${params.size ? `?${params}` : ""}`)
      .then((result) => { if (active) setDetail(result); })
      .catch((reason) => { if (active) setError(reason?.message || "Evidence is unavailable."); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [session.source_document_id, workspaceId]);

  useEffect(() => {
    closeRef.current?.focus();
    const onKeyDown = (event) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  const excerpts = useMemo(() => evidenceExcerpts(detail?.content, topic), [detail?.content, topic]);
  const components = useMemo(() => relevantComponents(detail?.components, topic), [detail?.components, topic]);
  const checkpoints = session.compaction_checkpoints || [];

  const copySessionId = async () => {
    try {
      await navigator.clipboard.writeText(session.session_id);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  };

  const continueFromCheckpoint = async (checkpoint) => {
    setCheckpointState({
      status: "loading",
      checkpointId: checkpoint.id,
      error: "",
    });
    try {
      const data = await api.post("/session-library/checkpoints/restore", {
        workspace_id: workspaceId,
        source_document_id: session.source_document_id,
        checkpoint_id: checkpoint.id,
      });
      const exactCheckpoint = data?.checkpoint || checkpoint;
      const objective = String(
        data?.restore_context?.objective
        || checkpoint.objective_preview
        || topic
        || session.title
        || "",
      ).trim();
      const params = new URLSearchParams({
        checkpoint: exactCheckpoint.id,
        checkpoint_source: session.source_document_id,
      });
      if (objective) params.set("objective", objective);
      if (session.cwd) params.set("repo_path", session.cwd);
      navigate(`/app?${params.toString()}`);
    } catch (reason) {
      setCheckpointState({
        status: "error",
        checkpointId: checkpoint.id,
        error: reason?.message || "This checkpoint could not be prepared for Continue.",
      });
    }
  };

  return (
    <div className="fixed inset-0 z-[100] flex justify-end bg-black/45 backdrop-blur-[3px]" role="presentation" onMouseDown={onClose}>
      <aside
        role="dialog"
        aria-modal="true"
        aria-labelledby="evidence-title"
        onMouseDown={(event) => event.stopPropagation()}
        className="flex h-full w-full max-w-2xl flex-col border-l border-[#d8d8cf] bg-[#f7f7f2] shadow-[-30px_0_90px_rgba(0,0,0,0.22)] dark:border-[#2d2d28] dark:bg-[#0d0d0b]"
      >
        <header className="shrink-0 border-b border-[#deded5] p-5 dark:border-[#292925] sm:p-6">
          <div className="flex items-start justify-between gap-4">
            <div className="flex min-w-0 items-start gap-3">
              <HarnessLogo type={session.connector_type} size="medium" />
              <div className="min-w-0">
                <p className="text-[9px] font-black uppercase tracking-[0.17em]" style={{ color: meta.accent }}>{meta.name} evidence</p>
                <h2 id="evidence-title" className="mt-1 text-xl font-black leading-7 tracking-[-0.025em]">{session.title}</h2>
                <p className="mt-1 text-[10px] font-semibold text-[#85857c]">Immutable source revision {session.revision_number} · {session.live ? "Live-linked" : "Imported"}</p>
                {session.forked_from ? (
                  <p className="mt-1.5 flex items-center gap-1.5 text-[10px] font-semibold text-[#77776e] dark:text-[#aaa9a0]">
                    <GitFork className="h-3 w-3 shrink-0" aria-hidden="true" />
                    <span className="truncate">Continued in a new task from {session.forked_from.title}</span>
                  </p>
                ) : null}
              </div>
            </div>
            <button ref={closeRef} type="button" aria-label="Close evidence" onClick={onClose} className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-[#d8d8cf] transition hover:bg-white dark:border-[#383832] dark:hover:bg-[#1c1c18]">
              <X className="h-4 w-4" />
            </button>
          </div>

          <div className="mt-5">
            <p className="mb-2 text-[8px] font-black uppercase tracking-[0.16em] text-[#85857c]">Highlight topic</p>
            <div className="flex gap-2 overflow-x-auto pb-1">
              {(session.topics || []).map((item) => (
                <button
                  type="button"
                  key={item}
                  aria-pressed={item === topic}
                  onClick={() => onSelectTopic(item)}
                  className={`shrink-0 rounded-lg border px-3 py-2 text-[10px] font-bold transition ${item === topic ? "border-transparent text-white" : "border-[#d8d8cf] bg-[#fbfbf6] dark:border-[#383832] dark:bg-[#171713]"}`}
                  style={item === topic ? { backgroundColor: meta.accent } : undefined}
                >
                  {item}
                </button>
              ))}
            </div>
          </div>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto p-5 sm:p-6">
          {loading ? (
            <div className="flex min-h-64 items-center justify-center"><Loader2 className="h-6 w-6 animate-spin text-[#85857c]" /></div>
          ) : null}
          {error ? <Notice tone="error">{error}</Notice> : null}
          {!loading && !error ? (
            <div className="space-y-6">
              {checkpoints.length ? (
                <section aria-labelledby="checkpoint-heading" className="rounded-2xl border border-[#cfd9b0] bg-[#f3f8e7] p-4 dark:border-[#435026] dark:bg-[#18200d]">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="text-[9px] font-black uppercase tracking-[0.16em] text-[#668020]">03 · Continue from saved state</p>
                      <h3 id="checkpoint-heading" className="mt-1 text-base font-black">Compaction checkpoints</h3>
                      <p className="mt-1 max-w-lg text-[10px] font-semibold leading-5 text-[#66704d] dark:text-[#bdc7a5]">
                        Captured automatically before this harness compressed its context. Continue reconciles the selected checkpoint without changing the original session.
                      </p>
                    </div>
                    <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-[#d9ff68] px-2.5 py-1 text-[8px] font-black uppercase tracking-wide text-[#37420f]">
                      <History className="h-3 w-3" /> {checkpoints.length}
                    </span>
                  </div>

                  <div className="mt-4 space-y-2">
                    {checkpoints.map((checkpoint) => {
                      const loadingCheckpoint = (
                        checkpointState.status === "loading"
                        && checkpointState.checkpointId === checkpoint.id
                      );
                      return (
                        <article key={checkpoint.id} className="rounded-xl border border-[#d6dfbd] bg-white/75 p-3 dark:border-[#3e4925] dark:bg-black/15">
                          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                            <div className="min-w-0">
                              <p className="text-xs font-black">{checkpoint.label}</p>
                              <p className="mt-1 line-clamp-2 text-[10px] font-semibold leading-4 text-[#66704d] dark:text-[#bdc7a5]">{checkpoint.objective_preview}</p>
                              <p className="mt-1.5 text-[8px] font-black uppercase tracking-[0.12em] text-[#87936b]">
                                {checkpoint.turn_count} turns · {checkpoint.occurred_at ? formatTimeAgo(checkpoint.occurred_at) : "Time unavailable"}
                              </p>
                            </div>
                            <button
                              type="button"
                              onClick={() => continueFromCheckpoint(checkpoint)}
                              disabled={checkpointState.status === "loading"}
                              className="inline-flex h-9 shrink-0 items-center justify-center gap-2 rounded-lg bg-[#171713] px-3 text-[9px] font-black text-white disabled:cursor-wait disabled:opacity-60 dark:bg-[#d9ff68] dark:text-[#171713]"
                            >
                              {loadingCheckpoint ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <ArrowRight className="h-3.5 w-3.5" />}
                              {loadingCheckpoint ? "Preparing Continue…" : "Continue from checkpoint"}
                            </button>
                          </div>
                        </article>
                      );
                    })}
                  </div>

                  {checkpointState.status === "error" ? (
                    <p role="alert" className="mt-3 text-[10px] font-bold text-red-700 dark:text-red-300">
                      {checkpointState.error}
                    </p>
                  ) : null}
                </section>
              ) : null}

              <section>
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <p className="text-[9px] font-black uppercase tracking-[0.16em] text-[#85857c]">{checkpoints.length ? "04" : "03"} · Inspect the source</p>
                    <h3 className="mt-1 text-base font-black">Topic evidence</h3>
                  </div>
                  <span className="rounded-full px-2.5 py-1 text-[9px] font-black" style={{ color: meta.accent, backgroundColor: meta.accentSoft }}>{excerpts.length} excerpts</span>
                </div>
                <div className="mt-3 space-y-3">
                  {excerpts.length ? excerpts.map((excerpt, index) => (
                    <article key={`${excerpt.role}:${index}`} className="rounded-2xl border border-[#d8d8cf] bg-[#fbfbf6] p-4 dark:border-[#2e2e29] dark:bg-[#141411]">
                      <p className="mb-2 text-[8px] font-black uppercase tracking-[0.16em]" style={{ color: excerpt.role === "USER" ? meta.accent : "#85857c" }}>{roleLabel(excerpt.role)}</p>
                      <p className="max-w-full whitespace-pre-wrap break-words text-xs leading-6 text-[#4f4f48] [overflow-wrap:anywhere] dark:text-[#d5d5cc]"><HighlightedText text={excerpt.text} topic={topic} color={meta.accentSoft} /></p>
                    </article>
                  )) : (
                    <div className="rounded-2xl border border-dashed border-[#d8d8cf] p-6 text-center text-xs text-[#77776e] dark:border-[#30302b]">No transcript excerpt matched this topic exactly.</div>
                  )}
                </div>
              </section>

              {components.length ? (
                <section>
                  <p className="text-[9px] font-black uppercase tracking-[0.16em] text-[#85857c]">Extracted context</p>
                  <div className="mt-3 space-y-2">
                    {components.map((component) => (
                      <div key={component.id} className="rounded-xl border border-[#d8d8cf] bg-[#fbfbf6] p-3 dark:border-[#2e2e29] dark:bg-[#141411]">
                        <div className="flex items-center justify-between gap-3">
                          <p className="text-xs font-black"><HighlightedText text={component.name} topic={topic} color={meta.accentSoft} /></p>
                          <span className="rounded-full bg-[#ecece4] px-2 py-1 text-[8px] font-black uppercase tracking-wide text-[#77776e] dark:bg-[#252521]">{component.fact_type}</span>
                        </div>
                        {component.value && component.value !== component.name ? <p className="mt-1 text-[10px] leading-5 text-[#68685f] dark:text-[#aaa9a0]"><HighlightedText text={component.value} topic={topic} color={meta.accentSoft} /></p> : null}
                      </div>
                    ))}
                  </div>
                </section>
              ) : null}
            </div>
          ) : null}
        </div>

        <footer className="flex shrink-0 flex-col gap-3 border-t border-[#deded5] bg-[#fbfbf6] px-5 py-4 dark:border-[#292925] dark:bg-[#141411] sm:flex-row sm:items-center sm:justify-between sm:px-6">
          <div className="min-w-0">
            <p className="text-[8px] font-black uppercase tracking-[0.15em] text-[#85857c]">Source session</p>
            <p className="mt-1 truncate font-mono text-[9px] text-[#68685f] dark:text-[#aaa9a0]">{session.session_id}</p>
            <p className="mt-1 text-[9px] font-semibold text-[#85857c]">
              Continue starts from the selected topic without reopening or modifying this source session.
            </p>
          </div>
          <div className="grid w-full shrink-0 grid-cols-2 gap-2 sm:flex sm:w-auto">
            <button
              type="button"
              onClick={() => onUseTopic(topic)}
              disabled={selecting}
              className="col-span-2 inline-flex h-10 items-center justify-center gap-2 rounded-lg bg-[#d9ff68] px-3 text-[10px] font-black text-[#263008] shadow-sm transition hover:-translate-y-0.5 disabled:cursor-wait disabled:opacity-70 sm:col-span-1"
            >
              {selecting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <ArrowRight className="h-3.5 w-3.5" />}
              {selecting ? "Selecting topic…" : "Continue this topic"}
            </button>
            <button type="button" onClick={copySessionId} className="inline-flex h-10 items-center justify-center gap-2 rounded-lg border border-[#d8d8cf] px-3 text-[10px] font-black transition hover:bg-white dark:border-[#383832] dark:hover:bg-[#1d1d19]">
              {copied ? <Check className="h-3.5 w-3.5 text-emerald-600" /> : <Copy className="h-3.5 w-3.5" />}
              {copied ? "Copied" : "Copy ID"}
            </button>
          </div>
        </footer>
      </aside>
    </div>
  );
}


function HighlightedText({ text, topic, color }) {
  const value = String(text || "");
  const keywords = topicKeywords(topic);
  if (!keywords.length) return value;
  const pattern = new RegExp(`(${keywords.map(escapeRegExp).join("|")})`, "ig");
  return value.split(pattern).map((part, index) => {
    const matched = keywords.some((keyword) => keyword.toLowerCase() === part.toLowerCase());
    return matched ? <mark key={`${part}:${index}`} className="rounded px-0.5 text-inherit" style={{ backgroundColor: color }}>{part}</mark> : part;
  });
}


function evidenceExcerpts(content, topic) {
  if (!content) return [];
  const matches = [...String(content).matchAll(/\[([A-Z_ -]+)\]\n([\s\S]*?)(?=\n\n\[[A-Z_ -]+\]\n|$)/g)];
  const turns = matches.map((match, index) => ({
    role: match[1].trim(),
    text: cleanEvidenceTurn(match[2]).slice(0, 1800),
    index,
  })).filter((item) => item.text && !isEvidenceNoise(item.text));
  const keywords = topicKeywords(topic).map((value) => value.toLowerCase());
  const scored = turns.map((turn) => ({
    ...turn,
    score: keywords.reduce((score, keyword) => score + (turn.text.toLowerCase().includes(keyword) ? 1 : 0), 0),
  }));
  const matched = scored.filter((turn) => turn.score > 0);
  if (matched.length) return matched.sort((left, right) => left.index - right.index).slice(0, 8);
  return scored.slice(0, 5);
}


function cleanEvidenceTurn(value) {
  const withoutImages = String(value || "").replace(/<image\b[\s\S]*?<\/image>/gi, " ");
  const lines = withoutImages.split("\n").filter((rawLine) => {
    const plain = rawLine.replace(/^[#>*\-\d.)\s]+/, "").trim();
    const lowered = plain.toLowerCase();
    if (!plain) return true;
    if (["files mentioned by the user:", "my request for codex:"].includes(lowered)) return false;
    if (/^(?:screenshot\s+\d{4}-\d{2}-\d{2}\s+at\s+\d{1,2}(?:[.:]\d{2}){0,2}|codex-clipboard-[a-z0-9-]+)(?:\.png|\.jpe?g|\.webp)?(?::.*)?$/i.test(plain)) return false;
    if ((rawLine.includes("/var/folders/") || lowered.includes("/temporaryitems/")) && /\.(?:png|jpe?g|webp)(?:["'>:]|$)/i.test(rawLine)) return false;
    return !lowered.startsWith(("image name=", "path=", "[image #"));
  });
  return lines
    .join("\n")
    .replace(/\[([^\]]+)\]\((?:\/Users|\/var|\/private)\/[^)]+\)/g, "$1")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}


function relevantComponents(components, topic) {
  const items = (Array.isArray(components) ? components : []).filter((item) => !isEvidenceNoise(`${item.name || ""} ${item.value || ""}`));
  const keywords = topicKeywords(topic).map((value) => value.toLowerCase());
  const matched = items.filter((item) => {
    const text = `${item.name || ""} ${item.value || ""}`.toLowerCase();
    return keywords.some((keyword) => text.includes(keyword));
  });
  return (matched.length ? matched : items).slice(0, 6);
}


function topicKeywords(topic) {
  return Array.from(new Set(
    String(topic || "")
      .split(/[^a-zA-Z0-9_-]+/)
      .map((value) => value.trim())
      .filter((value) => value.length >= 4 && !["about", "from", "into", "that", "this", "with", "your"].includes(value.toLowerCase())),
  )).slice(0, 8);
}


function roleLabel(role) {
  if (["USER", "HUMAN", "YOU"].includes(role)) return "User request";
  if (["ASSISTANT", "CLAUDE", "CODEX", "OPENCODE", "AI"].includes(role)) return "Harness response";
  return role.replaceAll("_", " ");
}


function isEvidenceNoise(value) {
  const lowered = String(value || "").toLowerCase();
  return ["<environment_context>", "<skills_instructions>", "permissions instructions", "# agents.md instructions"].some((marker) => lowered.includes(marker));
}


function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}


function Notice({ children, tone }) {
  const warning = tone === "warning";
  return <div className={`rounded-xl border px-4 py-3 text-xs font-semibold ${warning ? "border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-900/60 dark:bg-amber-950/25 dark:text-amber-200" : "border-red-200 bg-red-50 text-red-800 dark:border-red-900/60 dark:bg-red-950/25 dark:text-red-200"}`}>{children}</div>;
}


function EmptyState({ title, detail, error = false, loading = false }) {
  if (loading) {
    return (
      <ProductLoadingState
        label={title}
        detail={detail}
        stages={["Scanning supported session stores", "Grouping project workstreams", "Preparing the session archive"]}
      />
    );
  }

  return (
    <div className={`rounded-3xl border p-12 text-center ${error ? "border-red-200 bg-red-50 dark:border-red-900/60 dark:bg-red-950/25" : "border-dashed border-[#d8d8cf] bg-[#fbfbf6] dark:border-[#292925] dark:bg-[#141411]"}`}>
      <FileSearch className="mx-auto h-5 w-5 text-[#85857c]" />
      <h2 className="mt-3 text-base font-black">{title}</h2>
      {detail ? <p className="mx-auto mt-2 max-w-xl text-xs leading-5 text-[#68685f] dark:text-[#aaa9a0]">{detail}</p> : null}
    </div>
  );
}
