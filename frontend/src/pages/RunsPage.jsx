import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  ChevronDown,
  FileCode2,
  FolderGit2,
  GitBranch,
  History,
  Layers3,
  Minus,
  Plus,
  Radio,
  Search,
  ShieldCheck,
  Sparkles,
} from "lucide-react";

import WorkspaceTopicGate from "../components/WorkspaceTopicGate";
import ProductLoadingState from "../components/ProductLoadingState";
import {
  HarnessArtwork,
  HarnessLogo,
  harnessMeta,
} from "../components/HarnessBrand";
import {
  useCheckpoints,
  useSessionContinuity,
  useSessionLibrary,
} from "../api/hooks";
import { cleanDisplayText, formatTimeAgo } from "../context-map/digest";
import { useProductWorkspace } from "./useProductWorkspace";
import {
  buildSessionContinuity,
  ledgerSections,
  sessionSearchText,
} from "./sessionContinuity";


const INITIAL_SESSION_COUNT = 8;
const CHECKPOINT_PAGE_LIMIT = 100;
const LEDGER_TONES = {
  base: {
    icon: Layers3,
    accent: "#171713",
    panel: "border-[#cfcfc5] bg-[#f5f5ee] dark:border-[#3c3c36] dark:bg-[#151512]",
  },
  added: {
    icon: Plus,
    accent: "#4f7b22",
    panel: "border-[#ccdda8] bg-[#f4f8e9] dark:border-[#40512a] dark:bg-[#17200e]",
  },
  changed: {
    icon: Sparkles,
    accent: "#9a6426",
    panel: "border-[#ead5b5] bg-[#fff8e9] dark:border-[#65451e] dark:bg-[#24180b]",
  },
  missing: {
    icon: AlertTriangle,
    accent: "#b34b43",
    panel: "border-[#e8c1bd] bg-[#fff5f3] dark:border-[#663531] dark:bg-[#25110f]",
  },
  removed: {
    icon: Minus,
    accent: "#6f687d",
    panel: "border-[#d8d2df] bg-[#f7f4fa] dark:border-[#494252] dark:bg-[#19161d]",
  },
};


export default function RunsPage() {
  const navigate = useNavigate();
  const workspace = useProductWorkspace();
  const libraryQuery = useSessionLibrary(workspace.activeWorkspaceId);
  const continuityQuery = useSessionContinuity(workspace.activeWorkspaceId);
  const checkpointsQuery = useCheckpoints(
    workspace.activeWorkspaceId,
    CHECKPOINT_PAGE_LIMIT,
  );
  const [search, setSearch] = useState("");
  const [providerFilter, setProviderFilter] = useState("all");
  const [visibleCount, setVisibleCount] = useState(INITIAL_SESSION_COUNT);

  const cards = useMemo(() => buildSessionContinuity({
    sessions: libraryQuery.data?.sessions || [],
    ledgers: continuityQuery.data?.sessions || [],
    checkpoints: checkpointsQuery.data?.checkpoints || [],
  }), [
    checkpointsQuery.data?.checkpoints,
    continuityQuery.data?.sessions,
    libraryQuery.data?.sessions,
  ]);
  const normalizedSearch = search.trim().toLocaleLowerCase();
  const matchingCards = cards.filter((card) => (
    (providerFilter === "all" || card.provider === providerFilter)
    && (!normalizedSearch || sessionSearchText(card).includes(normalizedSearch))
  ));
  const visibleCards = matchingCards.slice(0, visibleCount);
  const totalCompactions = cards.reduce((total, card) => total + card.compactionCount, 0);
  const loading = libraryQuery.isLoading || continuityQuery.isLoading;
  const error = libraryQuery.isError ? libraryQuery.error : continuityQuery.isError ? continuityQuery.error : null;

  if (!workspace.workspacesQuery.isLoading && !workspace.activeWorkspaceId) {
    return (
      <WorkspaceTopicGate
        workspaces={workspace.workspaces}
        selectedId={workspace.selectedId}
        onSelect={workspace.setSelectedId}
      />
    );
  }

  const continueFromCard = (card) => {
    if (!workspace.activeWorkspaceId || !card?.sourceDocumentId) return;
    const params = new URLSearchParams();
    const objective = cleanDisplayText(card.ledger?.base?.[0]?.text);
    if (objective) {
      params.set("objective", objective);
      params.set("objective_source", "session");
    }
    if (card.cwd) params.set("repo_path", card.cwd);
    if (card.provider && card.sessionId) {
      params.set("source_provider", card.provider);
      params.set("source_session", card.sessionId);
    }
    navigate({ pathname: "/app", search: params.toString() ? `?${params}` : "" });
  };

  return (
    <div className="relative mx-auto w-full max-w-7xl space-y-7 pb-12 text-[#171713] dark:text-white">
      <header className="daemonstate-resume-header group relative overflow-hidden rounded-[2rem] border border-[#d8d8cf] bg-[#f7f7f1] px-5 py-7 dark:border-[#292925] dark:bg-[#0c0c0a] sm:px-8 sm:py-9 lg:px-10">
        <div aria-hidden="true" className="absolute -right-20 -top-24 h-72 w-72 rounded-full bg-[#d9ff68]/25 blur-3xl dark:bg-[#d9ff68]/10" />
        <HarnessDeckBackdrop />
        <div className="relative grid gap-8 lg:grid-cols-[minmax(0,1fr)_22rem] lg:items-end">
          <div className="max-w-3xl">
            <div className="flex items-center gap-2 text-[10px] font-black uppercase tracking-[0.18em] text-[#77776e] dark:text-[#aaa9a0]">
              <span className="h-px w-8 bg-[#9dbc47]" aria-hidden="true" />
              Task history
            </div>
            <h1 className="mt-4 text-3xl font-black tracking-[-0.045em] sm:text-4xl lg:text-5xl">History</h1>
            <p className="mt-4 max-w-2xl text-sm font-medium leading-6 text-[#68685f] dark:text-[#aaa9a0]">
              Review what you asked for, what happened since, and any context gaps before choosing a task for Continue.
            </p>
          </div>
          {!loading && cards.length ? (
            <dl className="grid grid-cols-2 overflow-hidden rounded-2xl border border-[#d8d8cf] bg-white/70 backdrop-blur-sm dark:border-[#34342f] dark:bg-black/25">
              <HeaderMetric value={cards.length} label="Sessions" />
              <HeaderMetric value={totalCompactions} label="Compactions" />
            </dl>
          ) : null}
        </div>
      </header>

      {loading ? (
        <ProductLoadingState
          label="Reconstructing session context…"
          detail="Reading source-backed history and preparing one history card per session."
          stages={["Finding agent sessions", "Rebuilding session history", "Linking Continue actions"]}
        />
      ) : null}
      {error ? <EmptyState title="Could not reconstruct session context" detail={error.message} error /> : null}

      {!loading && !error && cards.length ? (
        <>
          <section className="grid gap-4 rounded-2xl border border-[#deded5] bg-white p-4 dark:border-[#292925] dark:bg-[#11110f] lg:grid-cols-[minmax(0,1fr)_auto] lg:items-center lg:p-5" aria-label="Filter session continuity">
            <label className="relative block">
              <span className="sr-only">Search session continuity</span>
              <Search className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-[#77776e]" aria-hidden="true" />
              <input
                type="search"
                value={search}
                onChange={(event) => {
                  setSearch(event.target.value);
                  setVisibleCount(INITIAL_SESSION_COUNT);
                }}
                placeholder="Search requests, decisions, or progress"
                className="h-11 w-full rounded-xl border border-[#d5d5cc] bg-[#fbfbf6] pl-10 pr-4 text-sm font-semibold outline-none transition placeholder:font-normal placeholder:text-[#85857c] focus:border-[#7f983d] focus:ring-2 focus:ring-[#c9ec70]/35 dark:border-[#363630] dark:bg-black dark:focus:border-[#d8ff73]"
              />
            </label>
            <div className="flex flex-wrap gap-2" aria-label="Filter by agent provider">
              {["all", "codex", "claude", "opencode"].map((provider) => {
                const count = provider === "all"
                  ? cards.length
                  : cards.filter((card) => card.provider === provider).length;
                if (provider !== "all" && count === 0) return null;
                const selected = providerFilter === provider;
                return (
                  <button
                    key={provider}
                    type="button"
                    aria-pressed={selected}
                    onClick={() => {
                      setProviderFilter(provider);
                      setVisibleCount(INITIAL_SESSION_COUNT);
                    }}
                    className={`rounded-full border px-3 py-2 text-[10px] font-black uppercase tracking-[0.12em] transition ${
                      selected
                        ? "border-[#171713] bg-[#171713] text-white dark:border-[#d9ff68] dark:bg-[#d9ff68] dark:text-[#171713]"
                        : "border-[#d8d8cf] bg-[#fbfbf6] text-[#68685f] hover:-translate-y-0.5 hover:border-[#aaa99f] hover:text-[#171713] dark:border-[#34342f] dark:bg-[#0c0c0a] dark:text-[#aaa9a0] dark:hover:text-white"
                    }`}
                  >
                    {provider === "all" ? "All sessions" : harnessMeta(provider).label || provider}
                    <span className="ml-1.5 opacity-65">{count}</span>
                  </button>
                );
              })}
            </div>
          </section>

          <section aria-labelledby="session-ledger-heading">
            <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
              <div>
                <p className="text-[10px] font-black uppercase tracking-[0.18em] text-[#77776e] dark:text-[#aaa9a0]">Task history</p>
                <h2 id="session-ledger-heading" className="mt-1 text-xl font-black tracking-[-0.025em]">One card. One session.</h2>
              </div>
              <p role="status" className="text-xs font-semibold text-[#68685f] dark:text-[#aaa9a0]">
                {matchingCards.length} {matchingCards.length === 1 ? "session" : "sessions"}
              </p>
            </div>

            {visibleCards.length ? (
              <ol className="grid items-start gap-6 xl:grid-cols-2">
                {visibleCards.map((card, index) => (
                  <li key={card.key} className="min-w-0">
                    <SessionLedgerCard
                      card={card}
                      index={index}
                      onContinue={continueFromCard}
                    />
                  </li>
                ))}
              </ol>
            ) : (
              <EmptyState title="No sessions match" detail="Try a different request, file, provider, or progress term." />
            )}

            {matchingCards.length > visibleCards.length ? (
              <button
                type="button"
                className="btn-secondary mx-auto mt-6 min-h-11 text-xs"
                onClick={() => setVisibleCount((count) => count + INITIAL_SESSION_COUNT)}
              >
                Show {Math.min(INITIAL_SESSION_COUNT, matchingCards.length - visibleCards.length)} more sessions
              </button>
            ) : null}
          </section>
        </>
      ) : null}

      {!loading && !error && !cards.length ? (
        <EmptyState
          title="No agent sessions yet"
          detail="Sync Codex, Claude Code, or OpenCode from Library. A source-backed history card will appear here for every session."
        />
      ) : null}

    </div>
  );
}

function SessionLedgerCard({
  card,
  index,
  onContinue,
}) {
  const [expanded, setExpanded] = useState(false);
  const [activeSection, setActiveSection] = useState("added");
  const sections = ledgerSections(card.ledger);
  const active = sections.find((section) => section.key === activeSection) || sections[0];
  const meta = harnessMeta(card.provider);
  const titleId = `session-ledger-${safeId(card.key)}`;
  const panelId = `${titleId}-panel`;
  const baseText = card.ledger?.base?.[0]?.text;
  const readiness = continuationReadiness(card);
  const ReadinessIcon = readiness.icon;

  const selectSection = (key) => {
    setActiveSection(key);
    setExpanded(true);
  };

  return (
    <article
      aria-labelledby={titleId}
      data-session-ledger={card.id}
      className="daemonstate-session-ledger group relative"
      style={{
        "--session-accent": meta.accent,
        "--session-soft": meta.soft,
        "--session-glow": meta.glow,
        "--session-delay": `${Math.min(index, 8) * 55}ms`,
      }}
    >
      <div className="daemonstate-session-ledger__paper relative overflow-hidden rounded-[1.75rem] border border-[#d4d4ca] bg-[#fbfbf6] shadow-[0_18px_48px_rgba(23,23,19,0.08)] dark:border-[#34342f] dark:bg-[#11110e] dark:shadow-[0_24px_70px_rgba(0,0,0,0.42)]">
        <span aria-hidden="true" className="daemonstate-session-ledger__accent absolute inset-x-0 top-0 h-1 origin-left" />
        <span aria-hidden="true" className="absolute -right-[9%] top-12 h-44 w-52 origin-center opacity-[0.055] transition-[transform,opacity] duration-700 ease-out group-hover:-translate-x-3 group-hover:scale-110 group-hover:opacity-[0.09] dark:opacity-[0.08] dark:group-hover:opacity-[0.12]">
          <HarnessArtwork type={card.provider} />
        </span>

        <div className="relative p-5 sm:p-6">
          <div className="flex items-start justify-between gap-4">
            <div className="flex items-center gap-3">
              <HarnessLogo type={card.provider} size="medium" decorative />
              <div>
                <p className="text-[9px] font-black uppercase tracking-[0.17em]" style={{ color: meta.accent }}>{meta.company}</p>
                <p className="mt-0.5 text-xs font-black">{meta.label}</p>
              </div>
            </div>
            <div className="text-right">
              <div className="flex items-center justify-end gap-1.5 text-[9px] font-black uppercase tracking-[0.12em] text-[#77776e] dark:text-[#aaa9a0]">
                {card.live ? <Radio className="h-3 w-3 text-emerald-600" aria-hidden="true" /> : null}
                {card.live ? "Live-linked" : "Imported"}
              </div>
            </div>
          </div>

          <div className="mt-6 min-h-[5.5rem]">
            <p className="text-[9px] font-black uppercase tracking-[0.16em] text-[#85857c]">Session</p>
            <h3 id={titleId} className="mt-2 line-clamp-2 text-[1.55rem] font-black leading-8 tracking-[-0.035em] sm:text-[1.7rem]">
              {card.title}
            </h3>
            <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-[10px] font-semibold text-[#68685f] dark:text-[#aaa9a0]">
              <span>{card.updatedAt ? `Updated ${formatTimeAgo(card.updatedAt)}` : "Update time unavailable"}</span>
              <span>{card.compactionCount} context {card.compactionCount === 1 ? "compaction" : "compactions"}</span>
              {card.cwd ? (
                <span className="inline-flex min-w-0 items-center gap-1">
                  <FolderGit2 className="h-3 w-3 shrink-0" aria-hidden="true" />
                  <span className="max-w-44 truncate">{folderName(card.cwd)}</span>
                </span>
              ) : null}
            </div>
          </div>

          <div className="mt-5 overflow-hidden rounded-2xl bg-[#171713] px-5 py-5 text-white dark:bg-[#e9e9df] dark:text-[#171713]">
            <div className="flex min-h-[5.5rem] min-w-0 flex-col justify-center">
              <p className="text-[8px] font-black uppercase tracking-[0.17em] text-white/55 dark:text-black/50">Original request</p>
              <p className="mt-2 line-clamp-3 text-sm font-bold leading-6">
                {baseText ? cleanDisplayText(baseText) : "The original request is not available in this session history."}
              </p>
            </div>
          </div>
        </div>

        <LedgerRail
          sections={sections}
          activeSection={activeSection}
          expanded={expanded}
          onSelect={selectSection}
        />

        <div className={`daemonstate-ledger-reveal ${expanded ? "is-open" : ""}`} aria-hidden={!expanded}>
          <div>
            {expanded ? (
              <ContextLedgerPanel
                id={panelId}
                section={active}
                card={card}
              />
            ) : null}
          </div>
        </div>

        <div className="daemonstate-session-ledger__footer relative border-t border-[#deded5] dark:border-[#292925]">
          <div className="daemonstate-session-ledger__footer-meta flex min-h-[4.5rem] min-w-0 flex-wrap items-center gap-x-4 gap-y-2 px-5 py-3 sm:px-6">
            <button
              type="button"
              aria-expanded={expanded}
              aria-controls={panelId}
              onClick={() => setExpanded((value) => !value)}
              className="inline-flex min-h-10 items-center gap-2 text-xs font-black transition hover:text-[#64801d]"
            >
              <ChevronDown className={`h-4 w-4 transition-transform duration-500 ${expanded ? "rotate-180" : ""}`} aria-hidden="true" />
              {expanded ? "Close session history" : "Review session history"}
            </button>
            <span className="hidden h-4 w-px bg-[#d8d8cf] dark:bg-[#34342f] sm:block" aria-hidden="true" />
            <span className="inline-flex items-center gap-1.5 text-[10px] font-bold text-[#68685f] dark:text-[#aaa9a0]">
              <ReadinessIcon className="h-3.5 w-3.5" aria-hidden="true" />
              {readiness.label}
            </span>
            {card.branch ? (
              <span className="inline-flex min-w-0 items-center gap-1.5 text-[10px] font-bold text-[#68685f] dark:text-[#aaa9a0]">
                <GitBranch className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                <span className="max-w-40 truncate">{card.branch}</span>
              </span>
            ) : null}
          </div>

          <div className="daemonstate-session-ledger__actions flex min-h-[4.5rem] flex-wrap items-center justify-end gap-2 border-t border-[#deded5] bg-[#f5f5ef] px-4 py-3 dark:border-[#292925] dark:bg-[#0c0c09]">
            <button
              type="button"
              onClick={() => onContinue(card)}
              disabled={!card.sourceDocumentId}
              aria-label={`Continue task: ${card.title}`}
              className="btn-primary h-11 min-w-40 shrink-0 whitespace-nowrap px-4 text-[10px] disabled:cursor-not-allowed disabled:opacity-50"
            >
              {card.sourceDocumentId ? "Continue this task" : "Continue unavailable"}
              <ArrowRight className="h-3.5 w-3.5 transition-transform group-hover:translate-x-0.5" aria-hidden="true" />
            </button>
          </div>
        </div>
      </div>
    </article>
  );
}

function LedgerRail({ sections, activeSection, expanded, onSelect }) {
  return (
    <div className="overflow-x-auto border-t border-[#deded5] bg-white/50 dark:border-[#292925] dark:bg-black/10">
      <div className="grid min-w-[28rem] grid-cols-5 sm:min-w-0" aria-label="Session task history">
        {sections.map((section) => {
          const tone = LEDGER_TONES[section.key];
          const Icon = tone.icon;
          const active = expanded && activeSection === section.key;
          return (
            <button
              key={section.key}
              type="button"
              aria-pressed={active}
              onClick={() => onSelect(section.key)}
              className={`daemonstate-ledger-tab relative min-h-[5.4rem] border-r border-[#e2e2da] px-3 py-3 text-left transition-colors last:border-r-0 dark:border-[#292925] ${active ? "is-active" : ""}`}
              style={{ "--ledger-accent": tone.accent }}
            >
              <span className="flex items-center justify-between gap-2">
                <span className="flex h-7 w-7 items-center justify-center rounded-lg border border-current/15 bg-white/60 dark:bg-black/15" style={{ color: tone.accent }}>
                  <Icon className="h-3.5 w-3.5" aria-hidden="true" />
                </span>
                <span className="font-mono text-sm font-black text-[#77776e] dark:text-[#aaa9a0]">
                  {section.count === null ? "—" : section.count}
                </span>
              </span>
              <span className="mt-2 block text-[9px] font-black uppercase tracking-[0.13em]">{section.label}</span>
              {section.key === "missing" ? (
                <span className="mt-1 block text-[8px] font-bold uppercase tracking-[0.1em] text-[#b34b43] dark:text-[#f08b83]">
                  {section.statusLabel}
                </span>
              ) : null}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function ContextLedgerPanel({ id, section, card }) {
  const tone = LEDGER_TONES[section.key];
  const Icon = tone.icon;
  const displayItems = userFacingItems(section.items);
  const technicalItemsHidden = displayItems.length !== section.items.length;
  return (
    <section id={id} className={`border-t p-5 dark:border-[#292925] sm:p-6 ${tone.panel}`} aria-labelledby={`${id}-heading`}>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex items-start gap-3">
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-current/15 bg-white/70 dark:bg-black/15" style={{ color: tone.accent }}>
            <Icon className="h-4 w-4" aria-hidden="true" />
          </span>
          <div>
            <p className="text-[9px] font-black uppercase tracking-[0.16em]" style={{ color: tone.accent }}>
              {section.label}
            </p>
            <h4 id={`${id}-heading`} className="mt-1 text-base font-black">{section.description}</h4>
          </div>
        </div>
        <span className="rounded-full border border-current/15 bg-white/60 px-2.5 py-1 font-mono text-[9px] font-black uppercase tracking-[0.12em] dark:bg-black/15" style={{ color: tone.accent }}>
          {sectionCountLabel(section)}
        </span>
      </div>

      {section.key === "missing" ? (
        <div className="mt-5 rounded-xl border border-[#e3b7b3] bg-white/70 p-4 dark:border-[#5a302c] dark:bg-black/15">
          <p className="text-xs font-black">
            {section.status === "not_applicable" ? "No compaction occurred" : "What was lost is unknown"}
          </p>
          <p className="mt-1 text-xs leading-5 text-[#6f4f4b] dark:text-[#d9aaa5]">
            {section.status === "not_applicable"
              ? "This session was not compacted, so there is no compaction gap to review."
              : "This session was compacted, but its history cannot show exactly what the agent stopped carrying forward."}
          </p>
        </div>
      ) : displayItems.length ? (
        <>
          {section.hiddenCount || technicalItemsHidden ? (
            <p className="mt-5 rounded-xl border border-dashed border-current/20 bg-white/45 px-3.5 py-3 text-[10px] font-bold dark:bg-black/10">
              {section.key === "added"
                ? section.hiddenCount
                  ? `Showing the latest ${displayItems.length} of ${section.count} session updates, grouped as follow-up requests, decisions, and progress. Older updates remain in the source session; technical file references stay out of this view.`
                  : "Showing follow-up requests, decisions, and progress. Technical file references stay out of this view."
                : `Showing the latest ${displayItems.length} of ${section.count} captured updates. Earlier history remains available in the source session.`}
            </p>
          ) : null}
          {section.key === "added"
            ? <SinceThenGroups items={displayItems} />
            : <LedgerItemList items={displayItems} sectionKey={section.key} />}
        </>
      ) : (
        <div className="mt-5 rounded-xl border border-dashed border-black/15 bg-white/45 p-4 text-xs font-semibold text-[#68685f] dark:border-white/15 dark:bg-black/10 dark:text-[#aaa9a0]">
          {emptySectionCopy(section.key)}
        </div>
      )}

      <div className="mt-5 grid gap-3 border-t border-black/10 pt-4 text-[10px] font-semibold text-[#68685f] dark:border-white/10 dark:text-[#aaa9a0] sm:grid-cols-2">
        <p className="inline-flex items-center gap-2">
          <History className="h-3.5 w-3.5" aria-hidden="true" />
          {card.compactionCount} context {card.compactionCount === 1 ? "boundary" : "boundaries"}
        </p>
        <p className="inline-flex items-center gap-2 sm:justify-end">
          <ShieldCheck className="h-3.5 w-3.5" aria-hidden="true" />
          Source-backed session history
        </p>
      </div>
    </section>
  );
}

function SinceThenGroups({ items }) {
  const groups = [
    {
      key: "requests",
      label: "Follow-up requests",
      items: items.filter((item) => item.kind === "instruction"),
    },
    {
      key: "decisions",
      label: "Decisions",
      items: items.filter((item) => item.kind === "decision"),
    },
    {
      key: "progress",
      label: "Progress",
      items: items.filter((item) => item.kind === "progress"),
    },
    {
      key: "other",
      label: "Other updates",
      items: items.filter((item) => !["instruction", "decision", "progress"].includes(item.kind)),
    },
  ].filter((group) => group.items.length);

  return (
    <div className="mt-5 space-y-5">
      {groups.map((group) => (
        <section key={group.key} aria-label={group.label}>
          <div className="mb-2 flex items-center justify-between gap-3">
            <h5 className="text-[10px] font-black uppercase tracking-[0.14em]">{group.label}</h5>
            <span className="text-[9px] font-bold text-[#68685f] dark:text-[#aaa9a0]">{group.items.length}</span>
          </div>
          <LedgerItemList items={group.items} sectionKey={`added-${group.key}`} compact />
        </section>
      ))}
    </div>
  );
}

function LedgerItemList({ items, sectionKey, compact = false }) {
  return (
    <ul className={compact ? "space-y-2.5" : "mt-3 space-y-2.5"}>
      {items.map((item, itemIndex) => (
        <li
          key={item.id || `${sectionKey}-${itemIndex}`}
          className="daemonstate-ledger-row rounded-xl border border-black/10 bg-white/75 p-3.5 dark:border-white/10 dark:bg-black/15"
          style={{ "--row-delay": `${Math.min(itemIndex, 8) * 42}ms` }}
        >
          <p className="text-xs font-semibold leading-5">
            {ledgerItemText(item)}
          </p>
          <div className="mt-2 flex flex-wrap gap-2 text-[8px] font-black uppercase tracking-[0.1em] text-[#77776e] dark:text-[#aaa9a0]">
            <span>{itemKindLabel(item.kind)}</span>
            <span>·</span>
            <span>{truthLabel(item.truth_state)}</span>
          </div>
        </li>
      ))}
    </ul>
  );
}

function HarnessDeckBackdrop() {
  const cards = [
    { type: "codex", left: "3.5rem", top: "4.5rem", rotation: "-10deg", delay: "0ms" },
    { type: "claude", left: "12.5rem", top: "1.25rem", rotation: "-1deg", delay: "750ms" },
    { type: "opencode", left: "21.5rem", top: "4rem", rotation: "9deg", delay: "1500ms" },
  ];
  return (
    <div
      aria-hidden="true"
      data-harness-deck-backdrop
      className="pointer-events-none absolute -right-8 -top-10 hidden h-[23rem] w-[37rem] select-none overflow-hidden sm:block"
      style={{
        maskImage: "linear-gradient(to right, transparent 0%, black 25%, black 100%)",
        WebkitMaskImage: "linear-gradient(to right, transparent 0%, black 25%, black 100%)",
      }}
    >
      {cards.map(({ type, left, top, rotation, delay }) => {
        const meta = harnessMeta(type);
        return (
          <span
            key={type}
            data-backdrop-harness={type}
            className="daemonstate-resume-deck-card absolute block h-64 w-44 overflow-hidden rounded-[1.65rem] border border-black/30 bg-[#efefe9] text-[#171713] opacity-[0.13] shadow-2xl grayscale dark:border-white/35 dark:bg-[#d6d6cf] dark:opacity-[0.16]"
            style={{
              left,
              top,
              "--deck-rotation": rotation,
              "--deck-delay": delay,
            }}
          >
            <span className="absolute inset-x-0 top-0 h-1 bg-[#171713]" />
            <span className="absolute -right-[24%] top-[14%] h-[48%] w-[94%] opacity-45">
              <HarnessArtwork type={type} monochrome />
            </span>
            <span className="absolute inset-x-0 top-0 flex items-start justify-end px-4 pt-4">
              <span className="text-[7px] font-black uppercase tracking-[0.15em]">{meta.company}</span>
            </span>
            <span className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-[#efefe9] via-[#efefe9]/95 to-transparent px-4 pb-5 pt-16">
              <span className="block text-xl font-black tracking-[-0.04em]">{meta.name}</span>
              <span className="mt-2 block h-px w-full bg-black/35" />
              <span className="mt-3 grid grid-cols-2 gap-3">
                <span className="h-5 rounded-sm bg-black/15" />
                <span className="h-5 rounded-sm bg-black/10" />
              </span>
            </span>
          </span>
        );
      })}
    </div>
  );
}

function HeaderMetric({ value, label }) {
  return (
    <div className="border-r border-[#d8d8cf] px-3 py-4 text-center last:border-r-0 dark:border-[#34342f]">
      <dd className="text-xl font-black tracking-[-0.04em] sm:text-2xl">{value}</dd>
      <dt className="mt-1 text-[8px] font-black uppercase tracking-[0.14em] text-[#77776e] dark:text-[#aaa9a0]">{label}</dt>
    </div>
  );
}

function continuationReadiness(card) {
  if (!card.sourceDocumentId) {
    return { label: "Continue unavailable", icon: AlertTriangle };
  }
  if (card.hasUnknownContextGaps) {
    return { label: "Ready for Continue — review context gaps", icon: AlertTriangle };
  }
  return { label: "Ready for Continue", icon: CheckCircle2 };
}

function sectionCountLabel(section) {
  if (section.count === null) return section.statusLabel;
  const noun = section.key === "added" ? "update" : "request";
  return `${section.count} ${noun}${section.count === 1 ? "" : "s"}`;
}

function userFacingItems(items = []) {
  return items.filter((item) => item.kind !== "file" && item.kind !== "check");
}

function itemKindLabel(kind) {
  return {
    original_request: "Original request",
    instruction: "Follow-up request",
    amendment: "Updated request",
    cancellation: "No longer applies",
    decision: "Decision",
    progress: "Progress",
  }[kind] || "Session update";
}

function truthLabel(value) {
  return {
    user_stated: "From you",
    observed: "Observed",
    reported: "Agent reported",
  }[value] || "From session history";
}

function ledgerItemText(item) {
  return cleanDisplayText(item?.text);
}

function emptySectionCopy(key) {
  return {
    base: "The original request is not available in this session history.",
    added: "No follow-up requests, decisions, or progress were captured.",
    changed: "You did not explicitly update an earlier request.",
    removed: "You did not explicitly cancel an earlier request.",
  }[key] || "Nothing captured in this section.";
}

function folderName(value) {
  return String(value || "").split("/").filter(Boolean).at(-1) || value;
}

function safeId(value) {
  let hash = 0;
  for (const character of String(value || "")) {
    hash = ((hash << 5) - hash + character.charCodeAt(0)) | 0;
  }
  return Math.abs(hash).toString(36);
}

function EmptyState({ title, detail, error = false }) {
  return (
    <div className={`rounded-[1.75rem] border p-10 text-center ${
      error
        ? "border-red-200 bg-red-50 dark:border-red-900/60 dark:bg-red-950/25"
        : "border-[#d8d8cf] bg-white dark:border-[#292925] dark:bg-[#11110f]"
    }`}>
      <FileCode2 className="mx-auto h-5 w-5 text-[#8aa62a]" aria-hidden="true" />
      <h2 className="mt-3 text-base font-black">{title}</h2>
      {detail ? <p className="mx-auto mt-2 max-w-xl text-xs leading-5 text-[#68685f] dark:text-[#aaa9a0]">{detail}</p> : null}
    </div>
  );
}
