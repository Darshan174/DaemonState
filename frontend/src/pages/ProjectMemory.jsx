import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  AlertTriangle,
  Archive,
  ArrowRight,
  Calendar,
  CheckCheck,
  CheckCircle2,
  ClipboardCheck,
  Clock3,
  Fingerprint,
  GitMerge,
  GraduationCap,
  HelpCircle,
  History,
  Link2,
  ListTodo,
  Rocket,
  Search,
  ShieldAlert,
  Target,
  UserRound,
  X,
  XCircle,
} from "lucide-react";

import WorkspaceTopicGate from "../components/WorkspaceTopicGate";
import {
  useClearCurrentGoal,
  useProjectMemory,
  useReviewMemoryRecord,
  useSetCurrentGoal,
} from "../context-map/api";
import { cleanDisplayText, formatTimeAgo } from "../context-map/digest";
import { useProductWorkspace } from "./useProductWorkspace";


const AREA_META = {
  direction: { label: "Direction", accent: "#7357d9", soft: "rgba(115,87,217,0.13)" },
  execution: { label: "Execution", accent: "#3d7ff2", soft: "rgba(61,127,242,0.12)" },
  uncertainty: { label: "Uncertainty", accent: "#db7046", soft: "rgba(219,112,70,0.13)" },
  learning: { label: "Learning", accent: "#a27818", soft: "rgba(162,120,24,0.13)" },
  delivery: { label: "Delivery", accent: "#218c72", soft: "rgba(33,140,114,0.13)" },
  proof: { label: "Proof", accent: "#2f8061", soft: "rgba(47,128,97,0.13)" },
  ownership: { label: "Ownership", accent: "#a04e83", soft: "rgba(160,78,131,0.12)" },
  history: { label: "History", accent: "#667085", soft: "rgba(102,112,133,0.13)" },
};

const MEMORY_VIEWS = [
  { id: "active", label: "Current memory", description: "Human-verified and directly observed project records. Reported claims stay in review." },
  { id: "review", label: "Needs review", description: "Unverified, conflicting, or stale context that needs a human decision." },
  { id: "people", label: "People & dates", description: "Responsibility and important delivery boundaries." },
  { id: "history", label: "History", description: "Resolved, superseded, dismissed, and revised context." },
];

const MEMORY_TYPES = [
  { id: "goal", view: "active", sources: ["goals"], area: "direction", title: "Current goal", description: "The explicit outcome currently selected as the project focus.", capture: "Only an explicitly selected workspace goal", icon: Target },
  { id: "requirements", view: "active", sources: ["requirements", "constraints"], area: "direction", title: "Requirements & constraints", description: "What must be true and what cannot change.", capture: "Requirements and non-negotiable constraints with source evidence", icon: ClipboardCheck },
  { id: "decisions", view: "active", sources: ["decisions", "assumptions", "alternatives"], area: "direction", title: "Decisions", description: "Chosen direction, rationale, assumptions, and alternatives.", capture: "Decision facts plus their assumptions and considered alternatives", icon: CheckCircle2 },
  { id: "work", view: "active", sources: ["tasks", "next_actions", "progress"], area: "execution", title: "Work", description: "Source-backed committed tasks and immediate actions.", capture: "Typed tasks with reviewable source evidence", icon: ListTodo },
  { id: "blockers", view: "active", sources: ["blockers", "dependencies"], area: "execution", title: "Blockers & dependencies", description: "What stops the work and what it relies on.", capture: "Active blockers and evidence-backed dependency links", icon: ShieldAlert },
  { id: "risks", view: "active", sources: ["risks", "open_questions"], area: "uncertainty", title: "Risks & questions", description: "Potential problems and unresolved questions.", capture: "Risk facts and explicit unanswered questions", icon: AlertTriangle },
  { id: "learnings", view: "active", sources: ["failed_attempts", "lessons"], area: "learning", title: "Learnings", description: "Failed attempts and reusable lessons worth carrying forward.", capture: "Observed failures and explicit lessons", icon: GraduationCap },
  { id: "deliveries", view: "active", sources: ["changes", "files", "commits_prs", "releases", "tests", "outcomes"], area: "delivery", title: "Deliveries & outcomes", description: "What changed, how it was verified, and what shipped.", capture: "Typed releases, tests, changes, verification, and factual outcomes", icon: Rocket },

  { id: "unverified", view: "review", sources: ["needs_review"], area: "uncertainty", title: "Unverified memory", description: "Extracted context that has not been confirmed by a person.", capture: "Needs-review records and evidence", icon: HelpCircle },
  { id: "conflicts", view: "review", sources: ["conflicts"], area: "uncertainty", title: "Conflicts", description: "Claims or directions that disagree with each other.", capture: "Conflict statuses and contradiction links", icon: GitMerge },
  { id: "stale", view: "review", sources: ["stale_context"], area: "uncertainty", title: "Stale context", description: "Information that may no longer describe the project.", capture: "Stale facts and provider snapshots", icon: Clock3 },

  { id: "owners", view: "people", sources: ["owners"], area: "ownership", title: "Owners", description: "People responsible for moving project records forward.", capture: "Assignment and ownership links", icon: UserRound },
  { id: "milestones", view: "people", sources: ["milestones"], area: "ownership", title: "Milestones", description: "Important deadlines and delivery boundaries.", capture: "Explicit milestone, deadline, and target-date evidence", icon: Calendar },

  { id: "resolved", view: "history", sources: ["resolved_blockers"], area: "history", title: "Resolved blockers", description: "Past obstacles and the evidence that cleared them.", capture: "Resolved blocker records", icon: CheckCheck },
  { id: "superseded", view: "history", sources: ["superseded"], area: "history", title: "Superseded memory", description: "Old context preserved without treating it as current truth.", capture: "Superseded project records", icon: Archive },
  { id: "dismissed", view: "history", sources: ["dismissed"], area: "history", title: "Dismissed memory", description: "Extracted records a person decided were not useful or correct.", capture: "Human-dismissed project records", icon: XCircle },
  { id: "revisions", view: "history", sources: ["version_history"], area: "history", title: "Source revisions", description: "Records backed by revised sources or marked as historical.", capture: "Source revision and temporal history", icon: History },
];


export default function ProjectMemory() {
  const workspace = useProductWorkspace();
  const reviewMemory = useReviewMemoryRecord(workspace.activeWorkspaceId);
  const setCurrentGoal = useSetCurrentGoal(workspace.activeWorkspaceId);
  const clearCurrentGoal = useClearCurrentGoal(workspace.activeWorkspaceId);
  const [view, setView] = useState("active");
  const [search, setSearch] = useState("");
  const [selectedType, setSelectedType] = useState(null);
  const [reviewingId, setReviewingId] = useState(null);
  const [reviewError, setReviewError] = useState(null);
  const [detailLimit, setDetailLimit] = useState(50);
  const memoryQuery = useProjectMemory(workspace.activeWorkspaceId, {
    query: search,
    section: selectedType?.id || null,
    limit: selectedType ? detailLimit : 3,
  });
  const sectionsById = useMemo(() => Object.fromEntries(
    (memoryQuery.data?.sections || []).map((section) => [section.id, section]),
  ), [memoryQuery.data]);
  const visibleTypes = useMemo(() => {
    const query = search.trim().toLowerCase();
    return MEMORY_TYPES.filter((type) => {
      if (type.view !== view) return false;
      if (!query) return true;
      return Number(sectionsById[type.id]?.total || 0) > 0;
    });
  }, [view, search, sectionsById]);
  const selectedView = MEMORY_VIEWS.find((item) => item.id === view) || MEMORY_VIEWS[0];
  const activeRecordCount = memoryQuery.data?.totals?.active || 0;
  const reviewRecordCount = memoryQuery.data?.totals?.needs_review || 0;
  const historyRecordCount = memoryQuery.data?.totals?.history || 0;
  const excludedSessionCount = Number(memoryQuery.data?.scope?.excluded_unknown_session_components || 0)
    + Number(memoryQuery.data?.scope?.excluded_irrelevant_session_components || 0);
  const excludedLowIntegrityCount = Number(memoryQuery.data?.scope?.excluded_unconfirmable_agent_components || 0)
    + Number(memoryQuery.data?.scope?.collapsed_duplicate_current_claims || 0);

  const handleReview = async (item, action) => {
    if (!item.component_id) return;
    setReviewingId(item.component_id);
    setReviewError(null);
    try {
      await reviewMemory.mutateAsync({ componentId: item.component_id, action });
    } catch (error) {
      setReviewError(error?.message || "Could not update this memory record.");
    } finally {
      setReviewingId(null);
    }
  };

  const handleSetGoal = async (title) => {
    setReviewError(null);
    try {
      await setCurrentGoal.mutateAsync({ title, source_kind: "user_selected" });
    } catch (error) {
      setReviewError(error?.message || "Could not set the current goal.");
      throw error;
    }
  };

  const handleClearGoal = async () => {
    setReviewError(null);
    try {
      await clearCurrentGoal.mutateAsync();
    } catch (error) {
      setReviewError(error?.message || "Could not clear the current goal.");
    }
  };

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
    <div className="relative mx-auto w-full max-w-7xl pb-16">
      <header className="border-b border-[#d8d8cf] pb-7 dark:border-[#252522]">
        <div className="flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <p className="text-[11px] font-semibold text-[#77776e] dark:text-[#929289]">{workspace.activeWorkspace?.name || "Project"}</p>
            <h1 className="mt-2 text-4xl font-semibold tracking-[-0.05em] text-[#171713] dark:text-white sm:text-5xl">Project memory</h1>
            <p className="mt-3 max-w-xl text-sm leading-6 text-[#68685f] dark:text-[#aaa9a0]">
              Source-backed project records with their verification state and history.
            </p>
          </div>
          <dl className="grid w-full grid-cols-3 divide-x divide-[#d8d8cf] border-y border-[#d8d8cf] py-3 dark:divide-[#30302c] dark:border-[#30302c] sm:w-auto sm:min-w-[420px]">
            <MemoryStat value={activeRecordCount} label="Current" />
            <MemoryStat value={reviewRecordCount} label="Needs review" />
            <MemoryStat value={historyRecordCount} label="History" />
          </dl>
        </div>
      </header>

      <div className="mt-5 flex flex-col gap-4 border-b border-[#d8d8cf] dark:border-[#252522] lg:flex-row lg:items-center lg:justify-between">
        <nav aria-label="Memory views" className="no-scrollbar flex min-w-0 gap-6 overflow-x-auto">
          {MEMORY_VIEWS.map((memoryView) => (
            <button
              type="button"
              key={memoryView.id}
              aria-pressed={view === memoryView.id}
              onClick={() => { setView(memoryView.id); setSelectedType(null); }}
              className={`relative shrink-0 pb-3 text-[11px] font-semibold transition-colors duration-200 ${
                view === memoryView.id
                  ? "text-[#171713] dark:text-white"
                  : "text-[#85857c] hover:text-[#363630] dark:hover:text-[#d8d8cf]"
              }`}
            >
              {memoryView.label}
              {view === memoryView.id ? <span className="absolute inset-x-0 -bottom-px h-0.5 bg-[#171713] dark:bg-[#d9ff68]" /> : null}
            </button>
          ))}
        </nav>
        <div className="relative mb-3 w-full shrink-0 lg:w-64">
          <Search className="pointer-events-none absolute left-0 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[#85857c]" />
          <input
            type="search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            aria-label="Search memory records"
            placeholder="Search records and evidence"
            className="h-9 w-full border-0 border-b border-[#cfcfc5] bg-transparent pl-6 pr-1 text-xs font-medium text-[#171713] outline-none transition-colors placeholder:text-[#9b9b92] focus:border-[#171713] focus:ring-0 dark:border-[#393934] dark:text-white dark:focus:border-[#d9ff68]"
          />
        </div>
      </div>

      {memoryQuery.isError ? (
        <div role="alert" className="mt-6 border-y border-amber-300 py-3 text-xs font-medium text-amber-900 dark:border-amber-900/70 dark:text-amber-200">
          Project memory could not be loaded. No cached or inferred records are being shown.
        </div>
      ) : null}

      {!memoryQuery.isError && excludedSessionCount > 0 ? (
        <p className="mt-4 text-[10px] leading-4 text-[#77776e] dark:text-[#999990]">
          {excludedSessionCount.toLocaleString()} session-derived {excludedSessionCount === 1 ? "record is" : "records are"} outside this project scope or cannot be tied to it, so {excludedSessionCount === 1 ? "it is" : "they are"} excluded from these counts.
        </p>
      ) : null}
      {!memoryQuery.isError && excludedLowIntegrityCount > 0 ? (
        <p className="mt-1 text-[10px] leading-4 text-[#77776e] dark:text-[#999990]">
          {excludedLowIntegrityCount.toLocaleString()} unconfirmable or duplicate current {excludedLowIntegrityCount === 1 ? "record is" : "records are"} also hidden rather than presented as memory.
        </p>
      ) : null}

      <section aria-label="Project memory types" className="mt-9">
        {visibleTypes.length ? (
          <div>
            <div className="mb-5 flex items-end justify-between gap-6 border-b border-[#dfdfd7] pb-4 dark:border-[#252522]">
              <div>
                <h2 className="text-lg font-semibold tracking-[-0.025em]">{selectedView.label}</h2>
                <p className="mt-1 max-w-2xl text-xs leading-5 text-[#74746b] dark:text-[#aaa9a0]">{selectedView.description}</p>
              </div>
              <span className="shrink-0 text-[10px] font-medium text-[#8a8a80]">{visibleTypes.length} {visibleTypes.length === 1 ? "area" : "areas"}</span>
            </div>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
              {visibleTypes.map((type, index) => (
                <MemoryTypeCard
                  key={type.id}
                  type={type}
                  index={index}
                  loading={memoryQuery.isLoading}
                  count={sectionsById[type.id]?.total || 0}
                  items={sectionsById[type.id]?.records || []}
                  onOpen={() => {
                    setReviewError(null);
                    setDetailLimit(50);
                    setSelectedType(type);
                  }}
                />
              ))}
            </div>
          </div>
        ) : (
          <div className="border-y border-[#d8d8cf] py-16 text-center dark:border-[#30302b]">
            <p className="text-sm font-semibold">No matching memory type</p>
            <button type="button" onClick={() => setSearch("")} className="mt-3 text-xs font-semibold text-[#686d35] dark:text-[#d9ff68]">Clear search</button>
          </div>
        )}
      </section>

      {selectedType ? createPortal(
        <MemoryDrawer
          type={selectedType}
          items={sectionsById[selectedType.id]?.records || []}
          total={sectionsById[selectedType.id]?.total || 0}
          hasMore={sectionsById[selectedType.id]?.has_more || false}
          loading={memoryQuery.isLoading}
          reviewingId={reviewingId}
          reviewError={reviewError}
          onReview={handleReview}
          goalSaving={setCurrentGoal.isPending || clearCurrentGoal.isPending}
          onSetGoal={handleSetGoal}
          onClearGoal={handleClearGoal}
          currentGoal={memoryQuery.data?.current_goal || null}
          onLoadMore={() => setDetailLimit((value) => Math.min(500, value + 50))}
          onClose={() => setSelectedType(null)}
        />,
        document.body,
      ) : null}
    </div>
  );
}


function MemoryStat({ value, label }) {
  return (
    <div className="px-4 text-center sm:px-6">
      <dd className="text-xl font-semibold tabular-nums tracking-[-0.03em]">{value}</dd>
      <dt className="mt-0.5 text-[9px] font-medium uppercase tracking-[0.12em] text-[#85857c]">{label}</dt>
    </div>
  );
}


function MemoryTypeCard({ type, count, items, index, loading, onOpen }) {
  const meta = AREA_META[type.area];
  const previews = items.slice(0, 2);
  const Icon = type.icon;
  return (
    <button
      type="button"
      onClick={onOpen}
      aria-label={`Open ${type.title}`}
      className="memory-card-enter group relative min-h-[270px] w-full overflow-hidden rounded-[20px] border border-[#d7d7ce] bg-[#fbfbf6] p-5 text-left outline-none transition-[transform,border-color,box-shadow] duration-300 ease-out hover:-translate-y-1.5 hover:border-[var(--memory-accent)] hover:shadow-[0_18px_44px_rgba(23,23,19,0.1)] focus-visible:border-[var(--memory-accent)] focus-visible:ring-2 focus-visible:ring-[var(--memory-accent)] focus-visible:ring-offset-2 dark:border-[#2c2c28] dark:bg-[#0f0f0d] dark:focus-visible:ring-offset-[#090908] dark:hover:shadow-[0_20px_48px_rgba(0,0,0,0.46)]"
      style={{
        "--memory-accent": meta.accent,
        animationDelay: `${Math.min(index, 12) * 30}ms`,
      }}
    >
      <span aria-hidden="true" className="pointer-events-none absolute -right-12 -top-16 h-48 w-48 rounded-full opacity-70 blur-3xl transition-transform duration-700 group-hover:scale-125" style={{ backgroundColor: meta.soft }} />
      <span aria-hidden="true" className="absolute inset-y-5 left-0 w-[3px] origin-top scale-y-50 rounded-r-full opacity-70 transition-transform duration-500 group-hover:scale-y-100" style={{ backgroundColor: meta.accent }} />

      <span className="relative flex h-full flex-col">
        <span className="flex items-start justify-between gap-4">
          <span className="flex min-w-0 items-center gap-3">
            <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-[13px] border shadow-[0_6px_18px_rgba(23,23,19,0.06)] transition-transform duration-300 group-hover:-rotate-3 group-hover:scale-105 dark:shadow-none" style={{ borderColor: meta.accent, color: meta.accent, backgroundColor: meta.soft }}>
              <Icon className="h-5 w-5" strokeWidth={1.8} />
            </span>
            <span className="min-w-0">
              <span className="block text-[9px] font-semibold uppercase tracking-[0.13em] text-[#8a8a80]">{meta.label}</span>
              <span className={`mt-1 flex items-center gap-1.5 text-[10px] font-medium ${count ? "text-[#57574f] dark:text-[#bdbdb4]" : "text-[#9a9a91] dark:text-[#707069]"}`}>
                <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: count ? meta.accent : "currentColor" }} />
                {loading ? "Reading memory" : count ? "In memory" : "Awaiting evidence"}
              </span>
            </span>
          </span>
          <span className="text-right">
            <span className="block text-[26px] font-semibold tabular-nums leading-none tracking-[-0.06em] text-[#252520] dark:text-[#f1f1ea]">{loading ? "—" : count}</span>
            <span className="mt-1 block text-[8px] font-semibold uppercase tracking-[0.12em] text-[#999990]">{count === 1 ? "record" : "records"}</span>
          </span>
        </span>

        <span className="mt-5 block">
          <span className="block text-[18px] font-semibold leading-tight tracking-[-0.035em] text-[#171713] dark:text-white">{type.title}</span>
          <span className="mt-1.5 line-clamp-2 text-[11px] font-normal leading-[1.55] text-[#68685f] dark:text-[#aaa9a0]">{type.description}</span>
        </span>

        <span className={`mt-5 block rounded-[13px] border px-3 py-2.5 ${previews.length ? "border-[#dfdfd7] bg-white/55 dark:border-[#292925] dark:bg-white/[0.025]" : "border-dashed border-[#d8d8cf] bg-[#f5f5ef]/65 dark:border-[#30302b] dark:bg-white/[0.015]"}`}>
          {previews.length ? (
            <span className="block space-y-2">
              {previews.map((item, previewIndex) => (
                <span key={`${item.id || item.title}-${previewIndex}`} className="flex items-center gap-2">
                  <span className="h-1.5 w-1.5 shrink-0 rounded-full" style={{ backgroundColor: meta.accent }} />
                  <span className="line-clamp-1 text-[10px] font-medium text-[#56564f] dark:text-[#c8c8bf]">{cleanDisplayText(item.title)}</span>
                </span>
              ))}
            </span>
          ) : (
            <span className="flex items-center justify-between gap-3 text-[10px] text-[#8f8f86] dark:text-[#777770]">
              <span>No observed records yet</span>
              <span className="font-mono text-[8px] tabular-nums">{String(index + 1).padStart(2, "0")}</span>
            </span>
          )}
        </span>

        <span className="mt-auto flex items-center justify-between border-t border-[#dfdfd7] pt-3 text-[10px] font-semibold dark:border-[#292925]">
          <span className="text-[#56564f] transition-colors group-hover:text-[#171713] dark:text-[#aaa9a0] dark:group-hover:text-white">Open memory</span>
          <span className="flex h-7 w-7 items-center justify-center rounded-full border border-[#d7d7ce] text-[#77776e] transition-[transform,border-color,color,background-color] duration-300 group-hover:translate-x-0.5 group-hover:border-[var(--memory-accent)] group-hover:text-[var(--memory-accent)] dark:border-[#34342f]">
            <ArrowRight className="h-3.5 w-3.5" />
          </span>
        </span>
      </span>
    </button>
  );
}


function MemoryDrawer({
  type,
  items,
  total,
  hasMore,
  loading,
  reviewingId,
  reviewError,
  onReview,
  goalSaving,
  onSetGoal,
  onClearGoal,
  currentGoal,
  onLoadMore,
  onClose,
}) {
  const closeRef = useRef(null);
  const meta = AREA_META[type.area];
  const Icon = type.icon;

  useEffect(() => {
    closeRef.current?.focus();
    const onKeyDown = (event) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-[100] flex justify-end bg-[#171713]/35 dark:bg-black/70" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <aside role="dialog" aria-modal="true" aria-labelledby="memory-drawer-title" className="memory-drawer-enter relative flex h-full w-full max-w-lg flex-col border-l border-[#d8d8cf] bg-[#f7f7f2] shadow-[-20px_0_60px_rgba(23,23,19,0.16)] dark:border-[#292925] dark:bg-[#090908]">
        <span aria-hidden="true" className="absolute inset-y-0 left-0 w-[3px]" style={{ backgroundColor: meta.accent }} />
        <header className="border-b border-[#d8d8cf] px-5 py-5 dark:border-[#292925] sm:px-7 sm:py-6">
          <div className="flex items-start justify-between gap-4">
            <div className="flex min-w-0 items-start gap-3.5">
              <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-[11px] border dark:bg-white/[0.03]" style={{ borderColor: meta.accent, backgroundColor: meta.soft }}>
                <Icon className="h-5 w-5" strokeWidth={1.8} style={{ color: meta.accent }} />
              </span>
              <div>
                <p className="text-[10px] font-medium" style={{ color: meta.accent }}>{meta.label}</p>
                <h2 id="memory-drawer-title" className="mt-0.5 text-2xl font-semibold tracking-[-0.04em]">{type.title}</h2>
              </div>
            </div>
            <button ref={closeRef} type="button" onClick={onClose} aria-label="Close memory details" className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-[#d4d4cb] text-[#68685f] transition-colors hover:border-[#a9a99f] hover:text-[#171713] dark:border-[#34342f] dark:text-[#aaa9a0] dark:hover:text-white"><X className="h-4 w-4" /></button>
          </div>
          <p className="mt-5 max-w-md text-sm leading-6 text-[#4f4f48] dark:text-[#c8c8bf]">{type.description}</p>
          <div className="mt-4 flex items-center gap-2 border-t border-[#dfdfd7] pt-3 text-[10px] text-[#77776e] dark:border-[#292925] dark:text-[#aaa9a0]">
            <Fingerprint className="h-3.5 w-3.5 shrink-0" />
            <span>{type.capture}</span>
          </div>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5 sm:px-7 sm:py-6">
          <div className="mb-4 flex items-center justify-between gap-3">
            <h3 className="text-xs font-semibold text-[#4f4f48] dark:text-[#d0d0c8]">Memory records</h3>
            <span className="font-mono text-[10px] tabular-nums text-[#8a8a80]">{loading ? "…" : `${items.length} / ${total}`}</span>
          </div>
          {reviewError ? <p role="alert" className="mb-4 border-y border-red-300 py-2 text-[11px] font-medium text-red-700 dark:border-red-900 dark:text-red-300">{reviewError}</p> : null}
          {type.id === "goal" ? (
            <GoalEditor
              currentGoal={currentGoal}
              saving={goalSaving}
              onSave={onSetGoal}
              onClear={currentGoal?.can_clear ? onClearGoal : null}
            />
          ) : null}
          {items.length ? (
            <div className="overflow-hidden rounded-[12px] border border-[#d8d8cf] bg-[#fbfbf6] dark:border-[#292925] dark:bg-[#11110f]">
              {items.map((item) => <MemoryRecord key={item.id} item={item} accent={meta.accent} reviewing={reviewingId === item.component_id} onReview={onReview} />)}
            </div>
          ) : (
            <div className="border-y border-[#d1d1c7] px-6 py-12 text-center dark:border-[#30302b]">
              <Icon className="mx-auto h-6 w-6 opacity-50" strokeWidth={1.7} style={{ color: meta.accent }} />
              <p className="mt-4 text-sm font-semibold">Nothing observed yet</p>
              <p className="mx-auto mt-2 max-w-sm text-[11px] leading-5 text-[#68685f] dark:text-[#aaa9a0]">{type.id === "goal" ? "No current project goal is explicitly selected. Session tasks and checkpoint instructions are kept out of this tracker." : "When this information appears in a connected source, Context Engine can place it here with its evidence attached."}</p>
            </div>
          )}
          {hasMore ? (
            <button type="button" disabled={loading} onClick={onLoadMore} className="mt-4 w-full rounded-lg border border-[#d4d4cb] px-3 py-2.5 text-[10px] font-semibold transition-colors hover:border-[#99998f] disabled:opacity-40 dark:border-[#34342f]">
              {loading ? "Loading…" : `Load more (${total - items.length} remaining)`}
            </button>
          ) : null}
        </div>
      </aside>
    </div>
  );
}


function GoalEditor({ currentGoal, saving, onSave, onClear }) {
  const currentTitle = currentGoal?.title || "";
  const locked = currentGoal?.source_kind === "active_agent_run";
  const [title, setTitle] = useState(currentTitle);

  useEffect(() => setTitle(currentTitle), [currentTitle]);

  const submit = async (event) => {
    event.preventDefault();
    const normalized = title.trim();
    if (locked || normalized.length < 3 || normalized === currentTitle) return;
    await onSave(normalized);
  };

  return (
    <form onSubmit={submit} className="mb-4 border-y border-[#d8d8cf] py-4 dark:border-[#292925]">
      <label htmlFor="memory-current-goal" className="text-[10px] font-semibold uppercase tracking-[0.1em] text-[#77776e]">Set project focus</label>
      <textarea
        id="memory-current-goal"
        value={title}
        onChange={(event) => setTitle(event.target.value)}
        disabled={locked}
        rows={3}
        placeholder="Describe the outcome the project is trying to reach"
        className="mt-2 w-full resize-none rounded-[10px] border border-[#d4d4cb] bg-[#fbfbf6] px-3 py-2.5 text-[12px] leading-5 outline-none transition-colors placeholder:text-[#9b9b92] focus:border-[#77776e] dark:border-[#34342f] dark:bg-[#11110f]"
      />
      <p className="mt-2 text-[10px] leading-4 text-[#77776e] dark:text-[#aaa9a0]">
        {locked
          ? "An active agent run currently controls this objective. Finish or stop that run before changing it here."
          : "This is a display-only workspace focus shown in Memory and Now. It does not start work, edit files, or change an agent brief by itself."}
      </p>
      <div className="mt-2.5 flex items-center justify-between gap-3">
        {onClear ? <button type="button" disabled={saving} onClick={onClear} className="text-[10px] font-semibold text-[#7a5750] underline-offset-4 hover:underline disabled:opacity-40 dark:text-[#d6a69b]">Clear goal</button> : <span />}
        <button type="submit" disabled={locked || saving || title.trim().length < 3 || title.trim() === currentTitle} className="rounded-md bg-[#171713] px-3 py-2 text-[10px] font-semibold text-white transition-opacity disabled:opacity-35 dark:bg-[#d9ff68] dark:text-[#11110f]">{saving ? "Saving…" : currentTitle ? "Update goal" : "Set goal"}</button>
      </div>
    </form>
  );
}


function MemoryRecord({ item, accent, reviewing, onReview }) {
  const actions = new Set(item.allowed_actions || []);
  const evidence = item.evidence || null;
  const source = item.source || null;
  return (
    <article className="group border-b border-[#e1e1d9] p-4 last:border-b-0 dark:border-[#292925]">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          {item.kind ? <p className="mb-1 text-[9px] font-semibold uppercase tracking-[0.1em] text-[#8a8a80]">{item.kind}</p> : null}
          <h4 className="text-[13px] font-semibold leading-5">{cleanDisplayText(item.title)}</h4>
          {item.summary && cleanDisplayText(item.summary) !== cleanDisplayText(item.title) ? <p className="mt-1.5 text-[11px] leading-5 text-[#68685f] dark:text-[#aaa9a0]">{cleanDisplayText(item.summary)}</p> : null}
        </div>
        <span className="flex shrink-0 items-center gap-1.5 text-[9px] font-medium text-[#68685f] dark:text-[#aaa9a0]"><span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: accent }} />{String(item.verification || item.status || "observed").replaceAll("_", " ")}</span>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-[9px] font-medium text-[#8a8a80]">
        {source?.url ? (
          <a href={source.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 underline-offset-4 hover:underline"><Link2 className="h-3 w-3" />{source.label}</a>
        ) : source?.label ? <span className="inline-flex items-center gap-1"><Link2 className="h-3 w-3" />{source.label}</span> : null}
        {source?.revision_number ? <span>Revision {source.revision_number}</span> : null}
        {item.last_observed_at || item.occurred_at ? <span>{formatTimeAgo(item.last_observed_at || item.occurred_at)}</span> : null}
        {item.occurrence_count > 1 ? <span>Observed {item.occurrence_count} times</span> : null}
      </div>
      <p className="mt-2 text-[10px] leading-4 text-[#77776e] dark:text-[#999990]">{item.explanation}</p>
      {evidence?.excerpt ? (
        <blockquote className="mt-3 border-l-2 border-[#cfcfc5] pl-3 text-[10px] leading-4 text-[#5f5f57] dark:border-[#3a3a34] dark:text-[#b7b7ae]">
          “{cleanDisplayText(evidence.excerpt)}”
          <span className="mt-1 block text-[9px] text-[#8a8a80]">
            {evidence.exact ? "Exact source span" : "Captured evidence"} · {String(evidence.review_status || item.verification).replaceAll("_", " ")}
          </span>
        </blockquote>
      ) : null}
      {item.last_review ? (
        <p className="mt-2 text-[9px] text-[#8a8a80]">Last review: {item.last_review.action.replaceAll("_", " ")} by {item.last_review.reviewed_by}{item.last_review.reason ? ` — ${item.last_review.reason}` : ""}</p>
      ) : null}
      {item.component_id && actions.size ? (
        <div className="mt-3 flex flex-wrap gap-x-3 gap-y-2 border-t border-[#e5e5dd] pt-3 text-[10px] font-semibold dark:border-[#292925]">
          {actions.has("reopen") ? <button type="button" disabled={reviewing} onClick={() => onReview(item, "reopen")} className="text-[#4f4f48] underline-offset-4 hover:underline disabled:opacity-40 dark:text-[#d0d0c8]">Reopen</button> : null}
          {actions.has("confirm") ? <button type="button" disabled={reviewing} onClick={() => onReview(item, "confirm")} className="text-emerald-700 underline-offset-4 hover:underline disabled:opacity-40 dark:text-emerald-300">Confirm exact evidence</button> : null}
          {actions.has("resolve") ? <button type="button" disabled={reviewing} onClick={() => onReview(item, "resolve")} className="text-[#4f4f48] underline-offset-4 hover:underline disabled:opacity-40 dark:text-[#d0d0c8]">Resolve</button> : null}
          {actions.has("supersede") ? <button type="button" disabled={reviewing} onClick={() => onReview(item, "supersede")} className="text-[#4f4f48] underline-offset-4 hover:underline disabled:opacity-40 dark:text-[#d0d0c8]">Supersede</button> : null}
          {actions.has("dismiss") ? <button type="button" disabled={reviewing} onClick={() => onReview(item, "dismiss")} className="text-[#7a5750] underline-offset-4 hover:underline disabled:opacity-40 dark:text-[#d6a69b]">Dismiss</button> : null}
          {reviewing ? <span className="text-[#8a8a80]">Saving…</span> : null}
        </div>
      ) : null}
    </article>
  );
}
