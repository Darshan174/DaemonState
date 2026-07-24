import { useMemo, useState } from "react";
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  ChevronDown,
  Clipboard,
  Clock3,
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
  TestTube2,
  XCircle,
} from "lucide-react";

import WorkspaceTopicGate from "../components/WorkspaceTopicGate";
import SessionContinuationDialog from "../components/SessionContinuationDialog";
import ProductLoadingState from "../components/ProductLoadingState";
import {
  HarnessArtwork,
  HarnessLogo,
  harnessMeta,
} from "../components/HarnessBrand";
import {
  useCheckpointComparison,
  useCheckpoints,
  useContinueSession,
  useSessionContinuity,
  useSessionLibrary,
  useVerifyCheckpoint,
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
  const workspace = useProductWorkspace();
  const libraryQuery = useSessionLibrary(workspace.activeWorkspaceId);
  const continuityQuery = useSessionContinuity(workspace.activeWorkspaceId);
  const checkpointsQuery = useCheckpoints(
    workspace.activeWorkspaceId,
    CHECKPOINT_PAGE_LIMIT,
  );
  const continueSession = useContinueSession();
  const [search, setSearch] = useState("");
  const [providerFilter, setProviderFilter] = useState("all");
  const [visibleCount, setVisibleCount] = useState(INITIAL_SESSION_COUNT);
  const [selectedCard, setSelectedCard] = useState(null);
  const [continueState, setContinueState] = useState("idle");
  const [continueNotice, setContinueNotice] = useState("");
  const selectedComparison = useCheckpointComparison(
    workspace.activeWorkspaceId,
    selectedCard?.checkpoint?.id,
  );

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
  const recoveredItemCount = cards.reduce(
    (total, card) => total + ledgerSections(card.ledger).reduce(
      (sectionTotal, section) => sectionTotal + (Number.isFinite(section.count) ? section.count : 0),
      0,
    ),
    0,
  );
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

  const openContinue = (card) => {
    setContinueState("idle");
    setContinueNotice("");
    setSelectedCard(card);
  };
  const confirmContinue = async () => {
    if (!selectedCard) return;
    setContinueState("preparing");
    setContinueNotice("");
    try {
      const bundle = await continueSession.mutateAsync({
        workspaceId: workspace.activeWorkspaceId,
        sourceDocumentId: selectedCard.sourceDocumentId,
        launchSession: true,
      });
      await navigator.clipboard.writeText(bundle.content);
      const copiedOnly = bundle.launch?.launched === false;
      setContinueState(copiedOnly ? "copied_only" : "copied");
      setContinueNotice(
        copiedOnly
          ? bundle.launch?.message || "Recovered context copied. The linked desktop session could not be opened."
          : "Original session opened and recovered context copied.",
      );
      setSelectedCard(null);
    } catch {
      setContinueState("error");
    }
  };

  return (
    <div className="relative mx-auto w-full max-w-7xl space-y-7 pb-12 text-[#171713] dark:text-white">
      <header className="ce-resume-header group relative overflow-hidden rounded-[2rem] border border-[#d8d8cf] bg-[#f7f7f1] px-5 py-7 dark:border-[#292925] dark:bg-[#0c0c0a] sm:px-8 sm:py-9 lg:px-10">
        <div aria-hidden="true" className="absolute -right-20 -top-24 h-72 w-72 rounded-full bg-[#d9ff68]/25 blur-3xl dark:bg-[#d9ff68]/10" />
        <HarnessDeckBackdrop />
        <div className="relative grid gap-8 lg:grid-cols-[minmax(0,1fr)_22rem] lg:items-end">
          <div className="max-w-3xl">
            <div className="flex items-center gap-2 text-[10px] font-black uppercase tracking-[0.18em] text-[#77776e] dark:text-[#aaa9a0]">
              <span className="h-px w-8 bg-[#9dbc47]" aria-hidden="true" />
              Session continuity
            </div>
            <h1 className="mt-4 text-3xl font-black tracking-[-0.045em] sm:text-4xl lg:text-5xl">Resume sessions</h1>
            <p className="mt-4 max-w-2xl text-sm font-medium leading-6 text-[#68685f] dark:text-[#aaa9a0]">
              Every card is one agent session: what it started with, what accumulated, what explicitly changed, and what compaction still leaves unmeasured.
            </p>
          </div>
          {!loading && cards.length ? (
            <dl className="grid grid-cols-3 overflow-hidden rounded-2xl border border-[#d8d8cf] bg-white/70 backdrop-blur-sm dark:border-[#34342f] dark:bg-black/25">
              <HeaderMetric value={cards.length} label="Sessions" />
              <HeaderMetric value={totalCompactions} label="Compactions" />
              <HeaderMetric value={recoveredItemCount} label="Items" />
            </dl>
          ) : null}
        </div>
      </header>

      {loading ? (
        <ProductLoadingState
          label="Reconstructing session context…"
          detail="Reading source-backed events and arranging one continuity ledger per session."
          stages={["Finding agent sessions", "Rebuilding context ledgers", "Linking safe continuation actions"]}
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
                placeholder="Search requests, decisions, files, or progress"
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
                <p className="text-[10px] font-black uppercase tracking-[0.18em] text-[#77776e] dark:text-[#aaa9a0]">Context ledgers</p>
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
                      workspaceId={workspace.activeWorkspaceId}
                      onContinue={openContinue}
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
          detail="Sync Codex, Claude Code, or OpenCode from Library. A source-backed context ledger will appear here for every session."
        />
      ) : null}

      {continueNotice ? (
        <p role="status" className={`rounded-2xl border px-4 py-3 text-xs font-bold ${
          continueState === "copied_only"
            ? "border-amber-200 bg-amber-50 text-amber-900 dark:border-amber-900/70 dark:bg-amber-950/30 dark:text-amber-200"
            : "border-emerald-200 bg-emerald-50 text-emerald-900 dark:border-emerald-900/70 dark:bg-emerald-950/30 dark:text-emerald-200"
        }`}>
          {continueNotice}
        </p>
      ) : null}
      {continueState === "error" || continueSession.error ? (
        <p role="alert" className="rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-xs font-bold text-red-700 dark:border-red-900/70 dark:bg-red-950/30 dark:text-red-200">
          {continueSession.error?.message || "Could not open the session or copy its recovered context."}
        </p>
      ) : null}

      {selectedCard ? (
        <SessionContinuationDialog
          card={selectedCard}
          repositoryComparison={selectedComparison.data}
          repositoryComparisonLoading={selectedComparison.isLoading}
          isPending={continueSession.isPending || continueState === "preparing"}
          onCancel={() => setSelectedCard(null)}
          onConfirm={confirmContinue}
        />
      ) : null}
    </div>
  );
}

function SessionLedgerCard({ card, index, workspaceId, onContinue }) {
  const [expanded, setExpanded] = useState(false);
  const [activeSection, setActiveSection] = useState("added");
  const [verificationNotice, setVerificationNotice] = useState("");
  const verifyCheckpoint = useVerifyCheckpoint();
  const sections = ledgerSections(card.ledger);
  const active = sections.find((section) => section.key === activeSection) || sections[0];
  const meta = harnessMeta(card.provider);
  const cardNumber = String(index + 1).padStart(2, "0");
  const titleId = `session-ledger-${safeId(card.key)}`;
  const panelId = `${titleId}-panel`;
  const baseText = card.ledger?.base?.[0]?.text;
  const checkpointStateValue = checkpointState(
    card.checkpoint?.verification?.status,
    card.checkpoint?.capture_status,
  );
  const CheckpointIcon = checkpointStateValue.icon;

  const selectSection = (key) => {
    setActiveSection(key);
    setExpanded(true);
  };
  const runSavedChecks = () => {
    if (!card.checkpoint) return;
    setVerificationNotice("");
    verifyCheckpoint.mutate(
      {
        workspaceId,
        checkpointId: card.checkpoint.id,
        executeCommands: true,
      },
      {
        onSuccess: (result) => {
          const resultState = checkpointState(
            result?.verification?.status,
            result?.capture_status,
          );
          setVerificationNotice(`Check finished: ${resultState.label}.`);
        },
      },
    );
  };

  return (
    <article
      aria-labelledby={titleId}
      data-session-ledger={card.id}
      className="ce-session-ledger group relative"
      style={{
        "--session-accent": meta.accent,
        "--session-soft": meta.soft,
        "--session-glow": meta.glow,
        "--session-delay": `${Math.min(index, 8) * 55}ms`,
      }}
    >
      <div className="ce-session-ledger__paper relative overflow-hidden rounded-[1.75rem] border border-[#d4d4ca] bg-[#fbfbf6] shadow-[0_18px_48px_rgba(23,23,19,0.08)] dark:border-[#34342f] dark:bg-[#11110e] dark:shadow-[0_24px_70px_rgba(0,0,0,0.42)]">
        <span aria-hidden="true" className="ce-session-ledger__accent absolute inset-x-0 top-0 h-1 origin-left" />
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
              <p className="font-mono text-xl font-black leading-none" style={{ color: meta.accent }}>{cardNumber}</p>
              <div className="mt-2 flex items-center justify-end gap-1.5 text-[9px] font-black uppercase tracking-[0.12em] text-[#77776e] dark:text-[#aaa9a0]">
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

          <div className="mt-5 overflow-hidden rounded-2xl bg-[#171713] text-white dark:bg-[#e9e9df] dark:text-[#171713]">
            <div className="grid grid-cols-[auto_minmax(0,1fr)]">
              <div className="flex w-12 items-center justify-center border-r border-white/15 bg-white/[0.04] font-mono text-lg font-black text-[#d9ff68] dark:border-black/10 dark:bg-black/[0.035] dark:text-[#57711a]">
                B
              </div>
              <div className="flex min-h-[7.5rem] min-w-0 flex-col justify-center px-4 py-4">
                <p className="text-[8px] font-black uppercase tracking-[0.17em] text-white/55 dark:text-black/50">Base · original request</p>
                <p className="mt-2 line-clamp-3 text-sm font-bold leading-6">
                  {baseText ? cleanDisplayText(baseText) : "The original request was not available in normalized session evidence."}
                </p>
              </div>
            </div>
          </div>
        </div>

        <LedgerRail
          sections={sections}
          activeSection={activeSection}
          expanded={expanded}
          onSelect={selectSection}
        />

        <div className={`ce-ledger-reveal ${expanded ? "is-open" : ""}`} aria-hidden={!expanded}>
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

        <div className="ce-session-ledger__footer relative border-t border-[#deded5] dark:border-[#292925]">
          <div className="ce-session-ledger__footer-meta flex min-h-[4.5rem] min-w-0 flex-wrap items-center gap-x-4 gap-y-2 px-5 py-3 sm:px-6">
            <button
              type="button"
              aria-expanded={expanded}
              aria-controls={panelId}
              onClick={() => setExpanded((value) => !value)}
              className="inline-flex min-h-10 items-center gap-2 text-xs font-black transition hover:text-[#64801d]"
            >
              <ChevronDown className={`h-4 w-4 transition-transform duration-500 ${expanded ? "rotate-180" : ""}`} aria-hidden="true" />
              {expanded ? "Close context ledger" : "Review context ledger"}
            </button>
            <span className="hidden h-4 w-px bg-[#d8d8cf] dark:bg-[#34342f] sm:block" aria-hidden="true" />
            <span className="inline-flex items-center gap-1.5 text-[10px] font-bold text-[#68685f] dark:text-[#aaa9a0]">
              <CheckpointIcon className="h-3.5 w-3.5" aria-hidden="true" />
              {card.checkpoint ? checkpointStateValue.label : "No saved checks"}
            </span>
            {card.branch ? (
              <span className="inline-flex min-w-0 items-center gap-1.5 text-[10px] font-bold text-[#68685f] dark:text-[#aaa9a0]">
                <GitBranch className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                <span className="max-w-40 truncate">{card.branch}</span>
              </span>
            ) : null}
          </div>

          <div className="ce-session-ledger__actions flex min-h-[4.5rem] flex-wrap items-center justify-end gap-2 border-t border-[#deded5] bg-[#f5f5ef] px-4 py-3 dark:border-[#292925] dark:bg-[#0c0c09]">
            {card.checkpoint ? (
              <button
                type="button"
                onClick={runSavedChecks}
                disabled={verifyCheckpoint.isPending}
                aria-label={`Run saved checks for ${card.title}`}
                className="btn-secondary h-11 shrink-0 whitespace-nowrap px-3 text-[10px] disabled:cursor-wait disabled:opacity-50"
              >
                <TestTube2 className="h-3.5 w-3.5" aria-hidden="true" />
                {verifyCheckpoint.isPending ? "Running…" : "Run checks"}
              </button>
            ) : null}
            <button
              type="button"
              onClick={() => onContinue(card)}
              disabled={!card.canRepair}
              aria-label={`Repair context and continue: ${card.title}`}
              className="btn-primary h-11 min-w-40 shrink-0 whitespace-nowrap px-4 text-[10px] disabled:cursor-not-allowed disabled:opacity-50"
            >
              <Clipboard className="h-3.5 w-3.5" aria-hidden="true" />
              {card.canRepair ? "Repair & continue" : "Context unavailable"}
              <ArrowRight className="h-3.5 w-3.5 transition-transform group-hover:translate-x-0.5" aria-hidden="true" />
            </button>
          </div>
        </div>

        {verificationNotice || verifyCheckpoint.error ? (
          <p
            role={verifyCheckpoint.error ? "alert" : "status"}
            className={`border-t px-5 py-3 text-[10px] font-bold sm:px-6 ${
              verifyCheckpoint.error
                ? "border-red-200 bg-red-50 text-red-700 dark:border-red-900/70 dark:bg-red-950/30 dark:text-red-200"
                : "border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-900/70 dark:bg-emerald-950/30 dark:text-emerald-200"
            }`}
          >
            {verifyCheckpoint.error?.message || verificationNotice}
          </p>
        ) : null}
      </div>
    </article>
  );
}

function LedgerRail({ sections, activeSection, expanded, onSelect }) {
  return (
    <div className="overflow-x-auto border-t border-[#deded5] bg-white/50 dark:border-[#292925] dark:bg-black/10">
      <div className="grid min-w-[28rem] grid-cols-5 sm:min-w-0" aria-label="Session context ledger">
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
              className={`ce-ledger-tab relative min-h-[5.4rem] border-r border-[#e2e2da] px-3 py-3 text-left transition-colors last:border-r-0 dark:border-[#292925] ${active ? "is-active" : ""}`}
              style={{ "--ledger-accent": tone.accent }}
            >
              <span className="flex items-center justify-between gap-2">
                <span className="flex h-7 w-7 items-center justify-center rounded-lg border border-current/15 bg-white/60 dark:bg-black/15" style={{ color: tone.accent }}>
                  <Icon className="h-3.5 w-3.5" aria-hidden="true" />
                </span>
                <span className="font-mono text-sm font-black text-[#77776e] dark:text-[#aaa9a0]">
                  {section.count === null ? "—" : String(section.count).padStart(2, "0")}
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
  return (
    <section id={id} className={`border-t p-5 dark:border-[#292925] sm:p-6 ${tone.panel}`} aria-labelledby={`${id}-heading`}>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex items-start gap-3">
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-current/15 bg-white/70 dark:bg-black/15" style={{ color: tone.accent }}>
            <Icon className="h-4 w-4" aria-hidden="true" />
          </span>
          <div>
            <p className="text-[9px] font-black uppercase tracking-[0.16em]" style={{ color: tone.accent }}>
              {section.symbol} · {section.label}
            </p>
            <h4 id={`${id}-heading`} className="mt-1 text-base font-black">{section.description}</h4>
          </div>
        </div>
        <span className="rounded-full border border-current/15 bg-white/60 px-2.5 py-1 font-mono text-[9px] font-black uppercase tracking-[0.12em] dark:bg-black/15" style={{ color: tone.accent }}>
          {section.count === null ? section.statusLabel : `${section.count} captured`}
        </span>
      </div>

      {section.key === "missing" ? (
        <div className="mt-5 rounded-xl border border-[#e3b7b3] bg-white/70 p-4 dark:border-[#5a302c] dark:bg-black/15">
          <p className="text-xs font-black">
            {section.status === "not_applicable" ? "No compaction to compare" : "Not a fake zero"}
          </p>
          <p className="mt-1 text-xs leading-5 text-[#6f4f4b] dark:text-[#d9aaa5]">
            {section.reason || "The provider does not expose the post-compaction active prompt, so missing information cannot be measured truthfully."}
          </p>
        </div>
      ) : section.items.length ? (
        <>
          {section.hiddenCount ? (
            <p className="mt-5 rounded-xl border border-dashed border-current/20 bg-white/45 px-3.5 py-3 text-[10px] font-bold dark:bg-black/10">
              Showing the latest {section.items.length} of {section.count} captured items. Earlier evidence remains in the source session history.
            </p>
          ) : null}
          <ol className="mt-3 space-y-2.5">
            {section.items.map((item, itemIndex) => (
              <li
                key={item.id || `${section.key}-${itemIndex}`}
                className="ce-ledger-row rounded-xl border border-black/10 bg-white/75 p-3.5 dark:border-white/10 dark:bg-black/15"
                style={{ "--row-delay": `${Math.min(itemIndex, 8) * 42}ms` }}
              >
                <div className="flex items-start gap-3">
                  <span className="mt-0.5 flex h-6 min-w-6 items-center justify-center rounded-md bg-black/[0.055] px-1 font-mono text-[9px] font-black dark:bg-white/[0.08]">
                    {String(itemIndex + 1).padStart(2, "0")}
                  </span>
                  <div className="min-w-0">
                    <p className={`text-xs leading-5 ${
                      item.kind === "file" || item.kind === "check"
                        ? "break-all font-mono font-semibold"
                        : "font-semibold"
                    }`}>
                      {ledgerItemText(item)}
                    </p>
                    <div className="mt-2 flex flex-wrap gap-2 text-[8px] font-black uppercase tracking-[0.1em] text-[#77776e] dark:text-[#aaa9a0]">
                      <span>{itemKindLabel(item.kind)}</span>
                      <span>·</span>
                      <span>{truthLabel(item.truth_state)}</span>
                      {Number.isFinite(item.sequence_number) ? (
                        <>
                          <span>·</span>
                          <span>Event {item.sequence_number}</span>
                        </>
                      ) : null}
                    </div>
                  </div>
                </div>
              </li>
            ))}
          </ol>
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
          Source-backed session events
        </p>
      </div>
    </section>
  );
}

function HarnessDeckBackdrop() {
  const cards = [
    { type: "codex", number: "01", left: "3.5rem", top: "4.5rem", rotation: "-10deg", delay: "0ms" },
    { type: "claude", number: "02", left: "12.5rem", top: "1.25rem", rotation: "-1deg", delay: "750ms" },
    { type: "opencode", number: "03", left: "21.5rem", top: "4rem", rotation: "9deg", delay: "1500ms" },
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
      {cards.map(({ type, number, left, top, rotation, delay }) => {
        const meta = harnessMeta(type);
        return (
          <span
            key={type}
            data-backdrop-harness={type}
            className="ce-resume-deck-card absolute block h-64 w-44 overflow-hidden rounded-[1.65rem] border border-black/30 bg-[#efefe9] text-[#171713] opacity-[0.13] shadow-2xl grayscale dark:border-white/35 dark:bg-[#d6d6cf] dark:opacity-[0.16]"
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
            <span className="absolute inset-x-0 top-0 flex items-start justify-between px-4 pt-4">
              <span className="font-mono text-lg font-black">{number}</span>
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

function checkpointState(status = "not_run", captureStatus) {
  if (status === "verified") return { label: "Saved checks passed", icon: CheckCircle2 };
  if (status === "failed") return { label: "Saved checks failed", icon: XCircle };
  if (status === "stale") return { label: "Checks may be stale", icon: AlertTriangle };
  if (captureStatus === "incomplete") return { label: "Saved context needs review", icon: XCircle };
  return { label: status === "partial" ? "Partly checked" : "Checks not rerun", icon: Clock3 };
}

function itemKindLabel(kind) {
  return {
    original_request: "Original request",
    instruction: "Instruction",
    amendment: "User amendment",
    cancellation: "User cancellation",
    decision: "Reported decision",
    progress: "Reported progress",
    file: "Referenced file",
    check: "Observed check",
  }[kind] || "Context item";
}

function truthLabel(value) {
  return {
    user_stated: "User stated",
    observed: "Observed",
    reported: "Agent reported",
  }[value] || "Source linked";
}

function ledgerItemText(item) {
  if (item?.kind === "file" || item?.kind === "check") {
    return String(item.text || "").trim();
  }
  return cleanDisplayText(item?.text);
}

function emptySectionCopy(key) {
  return {
    base: "The original request was not available in normalized session evidence.",
    added: "No later instructions, decisions, files, or progress were captured.",
    changed: "No explicit user amendment was captured.",
    removed: "No explicit cancellation of an earlier requirement was captured.",
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
