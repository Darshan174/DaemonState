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
  direction: { label: "Direction", accent: "#68721f", soft: "rgba(104,114,31,0.10)" },
  execution: { label: "Execution", accent: "#416781", soft: "rgba(65,103,129,0.09)" },
  uncertainty: { label: "Uncertainty", accent: "#9a5e38", soft: "rgba(154,94,56,0.09)" },
  learning: { label: "Learning", accent: "#786337", soft: "rgba(120,99,55,0.09)" },
  delivery: { label: "Delivery", accent: "#3f6d5e", soft: "rgba(63,109,94,0.09)" },
  proof: { label: "Proof", accent: "#3f6d5e", soft: "rgba(63,109,94,0.09)" },
  ownership: { label: "Ownership", accent: "#6d5c7d", soft: "rgba(109,92,125,0.09)" },
  history: { label: "History", accent: "#6b6b65", soft: "rgba(107,107,101,0.09)" },
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
  const peopleRecordCount = memoryQuery.data?.totals?.people_and_dates || 0;
  const historyRecordCount = memoryQuery.data?.totals?.history || 0;
  const currentGoal = memoryQuery.data?.current_goal || null;
  const goalType = MEMORY_TYPES.find((type) => type.id === "goal");
  const displayedTypes = visibleTypes.filter(
    (type) => !(view === "active" && type.id === "goal" && !search.trim()),
  );
  const viewCounts = {
    active: activeRecordCount,
    review: reviewRecordCount,
    people: peopleRecordCount,
    history: historyRecordCount,
  };
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

  const openMemoryType = (type) => {
    setReviewError(null);
    setDetailLimit(50);
    setSelectedType(type);
  };

  const selectView = (nextView) => {
    setView(nextView);
    setSelectedType(null);
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
      <header className="border-b border-[#d8d8cf] pb-8 dark:border-[#252522] sm:pb-10">
        <div className="grid gap-8 lg:grid-cols-[minmax(0,1.4fr)_minmax(300px,0.6fr)] lg:items-end">
          <div className="max-w-3xl">
            <h1 className="text-3xl font-black tracking-[-0.035em] text-[#171713] dark:text-white sm:text-4xl">Project memory</h1>
            <p className="mt-4 max-w-2xl text-sm leading-6 text-[#5f5f57] dark:text-[#b7b7ae] sm:text-[15px] sm:leading-7">
              The project’s trusted knowledge base—what is current, where it came from, and what still needs a human decision.
            </p>
          </div>
          <div className="border-l-2 border-[#a7b74d] pl-4 dark:border-[#d9ff68] sm:pl-5">
            <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-[#77776e] dark:text-[#929289]">Trust rule</p>
            <p className="mt-2 text-sm font-medium leading-6 text-[#30302b] dark:text-[#deded6]">
              Reported claims do not become current memory until their evidence is verified.
            </p>
          </div>
        </div>
      </header>

      <section aria-labelledby="memory-priorities-heading" className="grid border-b border-[#d8d8cf] dark:border-[#252522] lg:grid-cols-[minmax(0,1.6fr)_minmax(320px,0.8fr)]">
        <div className="border-b border-[#d8d8cf] py-7 dark:border-[#252522] lg:border-b-0 lg:border-r lg:pr-8 dark:lg:border-[#252522] sm:py-8">
          <div className="flex items-center justify-between gap-4">
            <p id="memory-priorities-heading" className="text-[10px] font-semibold uppercase tracking-[0.14em] text-[#77776e] dark:text-[#929289]">Current project goal</p>
            <span className="inline-flex items-center gap-1.5 text-[10px] font-medium text-[#68721f] dark:text-[#d9ff68]">
              <span className="h-1.5 w-1.5 rounded-full bg-current" />
              {currentGoal?.source_kind === "active_agent_run" ? "Controlled by active run" : currentGoal ? "Explicitly selected" : "Not selected"}
            </span>
          </div>
          <h2 className="mt-5 max-w-3xl text-2xl font-semibold leading-tight tracking-[-0.04em] text-[#171713] dark:text-white sm:text-3xl">
            {currentGoal?.title || "No current goal selected"}
          </h2>
          <p className="mt-3 max-w-2xl text-xs leading-5 text-[#68685f] dark:text-[#aaa9a0]">
            {currentGoal
              ? "Shown as the workspace focus in Memory and Now, and used only when you explicitly prepare context."
              : "Set a display-only workspace focus for Memory, Now, and context you explicitly prepare."}
          </p>
          <button
            type="button"
            aria-label="Open Current goal"
            onClick={() => openMemoryType(goalType)}
            className="mt-5 inline-flex items-center gap-2 text-xs font-semibold text-[#31312c] outline-none underline-offset-4 hover:underline focus-visible:rounded-sm focus-visible:ring-2 focus-visible:ring-[#68721f] focus-visible:ring-offset-4 dark:text-[#e0e0d8] dark:focus-visible:ring-[#d9ff68] dark:focus-visible:ring-offset-[#090908]"
          >
            {currentGoal ? "Review project goal" : "Set project goal"}
            <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
          </button>
        </div>

        <div className="py-7 lg:pl-8 sm:py-8">
          <h2 className="text-[10px] font-semibold uppercase tracking-[0.14em] text-[#77776e] dark:text-[#929289]">Memory health</h2>
          <dl className="mt-5 divide-y divide-[#deded6] border-y border-[#deded6] dark:divide-[#30302c] dark:border-[#30302c]">
            <MemoryHealthStat
              value={activeRecordCount}
              label="Trusted current memory"
              description="Verified or directly observed"
              tone="trusted"
            />
            <MemoryHealthStat
              value={reviewRecordCount}
              label="Needs human review"
              description={reviewRecordCount ? "Waiting for a decision" : "Nothing waiting"}
              tone={reviewRecordCount ? "review" : "neutral"}
            />
          </dl>
          {reviewRecordCount ? (
            <button
              type="button"
              onClick={() => selectView("review")}
              className="mt-4 inline-flex items-center gap-2 text-xs font-semibold text-[#8a4d2d] outline-none underline-offset-4 hover:underline focus-visible:rounded-sm focus-visible:ring-2 focus-visible:ring-[#9a5e38] focus-visible:ring-offset-4 dark:text-[#e4ab85] dark:focus-visible:ring-offset-[#090908]"
            >
              Review {reviewRecordCount.toLocaleString()} {reviewRecordCount === 1 ? "item" : "items"}
              <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
            </button>
          ) : null}
        </div>
      </section>

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

      <section aria-labelledby="memory-browser-heading" className="mt-10">
        <div className="grid gap-5 border-b border-[#d8d8cf] pb-5 dark:border-[#252522] lg:grid-cols-[minmax(0,1fr)_minmax(260px,0.38fr)] lg:items-end">
          <div className="min-w-0">
            <h2 id="memory-browser-heading" className="text-lg font-semibold tracking-[-0.03em]">Browse project knowledge</h2>
            <nav aria-label="Memory views" className="no-scrollbar mt-4 flex min-w-0 gap-2 overflow-x-auto pb-1">
              {MEMORY_VIEWS.map((memoryView) => (
                <button
                  type="button"
                  key={memoryView.id}
                  aria-label={memoryView.label}
                  aria-pressed={view === memoryView.id}
                  onClick={() => selectView(memoryView.id)}
                  className={`inline-flex min-h-9 shrink-0 items-center gap-2 rounded-full border px-3.5 text-[10px] font-semibold outline-none transition-colors focus-visible:ring-2 focus-visible:ring-[#68721f] focus-visible:ring-offset-2 dark:focus-visible:ring-[#d9ff68] dark:focus-visible:ring-offset-[#090908] ${
                    view === memoryView.id
                      ? "border-[#24241f] bg-[#24241f] text-white dark:border-[#d9ff68] dark:bg-[#d9ff68] dark:text-[#11110f]"
                      : "border-[#d4d4cb] text-[#68685f] hover:border-[#99998f] hover:text-[#24241f] dark:border-[#34342f] dark:text-[#aaa9a0] dark:hover:border-[#62625b] dark:hover:text-white"
                  }`}
                >
                  {memoryView.label}
                  <span className={`tabular-nums ${view === memoryView.id ? "opacity-70" : "text-[#929289]"}`}>{viewCounts[memoryView.id].toLocaleString()}</span>
                </button>
              ))}
            </nav>
          </div>
          <div>
            <label htmlFor="memory-search" className="text-[10px] font-semibold uppercase tracking-[0.12em] text-[#77776e] dark:text-[#929289]">Search this workspace</label>
            <div className="relative mt-2">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[#85857c]" aria-hidden="true" />
              <input
                id="memory-search"
                type="search"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Records, evidence, sources…"
                className="h-10 w-full rounded-lg border border-[#d4d4cb] bg-[#fbfbf6] pl-9 pr-3 text-xs font-medium text-[#171713] outline-none transition-colors placeholder:text-[#9b9b92] focus:border-[#68721f] focus:ring-2 focus:ring-[#68721f]/20 dark:border-[#34342f] dark:bg-[#11110f] dark:text-white dark:focus:border-[#d9ff68] dark:focus:ring-[#d9ff68]/15"
              />
            </div>
          </div>
        </div>

        {displayedTypes.length ? (
          <div>
            <div className="flex items-end justify-between gap-6 py-6">
              <div>
                <h3 className="text-base font-semibold tracking-[-0.025em]">{selectedView.label}</h3>
                <p className="mt-1 max-w-2xl text-xs leading-5 text-[#74746b] dark:text-[#aaa9a0]">{selectedView.description}</p>
              </div>
              <span className="shrink-0 text-[10px] font-medium text-[#8a8a80]">{displayedTypes.length} {displayedTypes.length === 1 ? "area" : "areas"}</span>
            </div>
            <div className="border-t border-[#cfcfc5] dark:border-[#353530]">
              {displayedTypes.map((type, index) => (
                <MemoryTypeRow
                  key={type.id}
                  type={type}
                  index={index}
                  loading={memoryQuery.isLoading}
                  count={sectionsById[type.id]?.total || 0}
                  items={sectionsById[type.id]?.records || []}
                  onOpen={() => openMemoryType(type)}
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


function MemoryHealthStat({ value, label, description, tone }) {
  const toneClass = tone === "trusted"
    ? "text-[#68721f] dark:text-[#d9ff68]"
    : tone === "review"
      ? "text-[#9a5e38] dark:text-[#e4ab85]"
      : "text-[#77776e] dark:text-[#aaa9a0]";
  return (
    <div className="grid grid-cols-[1fr_auto] items-center gap-4 py-3">
      <dt className="text-xs font-semibold text-[#34342f] dark:text-[#d8d8cf]">
        <span className="block">{label}</span>
        <span className="mt-0.5 block text-[10px] font-normal text-[#85857c]">{description}</span>
      </dt>
      <dd className={`text-2xl font-semibold tabular-nums tracking-[-0.04em] ${toneClass}`}>{value}</dd>
    </div>
  );
}


function MemoryTypeRow({ type, count, items, index, loading, onOpen }) {
  const meta = AREA_META[type.area];
  const previews = items.slice(0, 2);
  const Icon = type.icon;
  return (
    <button
      type="button"
      onClick={onOpen}
      aria-label={`Open ${type.title}`}
      className="memory-card-enter group relative grid w-full gap-4 border-b border-[#d8d8cf] py-5 text-left outline-none transition-colors hover:bg-[#efefe8]/65 focus-visible:z-10 focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[var(--memory-accent)] dark:border-[#30302c] dark:hover:bg-white/[0.025] sm:grid-cols-[minmax(0,0.8fr)_auto] sm:px-3 lg:grid-cols-[minmax(240px,0.75fr)_minmax(260px,1.25fr)_auto] lg:items-center lg:gap-8"
      style={{
        "--memory-accent": meta.accent,
        animationDelay: `${Math.min(index, 12) * 20}ms`,
      }}
    >
      <span className="flex min-w-0 items-start gap-3.5 pr-20 sm:pr-0">
        <span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-[#d8d8cf] bg-[#f5f5ef] dark:border-[#34342f] dark:bg-[#11110f]" style={{ color: meta.accent }}>
          <Icon className="h-4 w-4" strokeWidth={1.8} aria-hidden="true" />
        </span>
        <span className="min-w-0">
          <span className="block text-[9px] font-semibold uppercase tracking-[0.13em]" style={{ color: meta.accent }}>{meta.label}</span>
          <span className="mt-1 block text-[15px] font-semibold leading-5 tracking-[-0.02em] text-[#171713] dark:text-white">{type.title}</span>
          <span className={`mt-1.5 flex items-center gap-1.5 text-[9px] font-medium ${count ? "text-[#5f5f57] dark:text-[#bdbdb4]" : "text-[#929289]"}`}>
            <Fingerprint className="h-3 w-3" aria-hidden="true" />
            {loading ? "Reading memory" : count ? "Contains source-backed records" : "No evidence captured"}
          </span>
        </span>
      </span>

      <span className="min-w-0 sm:col-span-2 lg:col-span-1">
        <span className="block text-[11px] leading-5 text-[#68685f] dark:text-[#aaa9a0]">{type.description}</span>
        {previews.length ? (
          <span className="mt-2 flex min-w-0 flex-col gap-1 text-[10px] text-[#4f4f48] dark:text-[#c8c8bf]">
            {previews.map((item, previewIndex) => (
              <span key={`${item.id || item.title}-${previewIndex}`} className="flex min-w-0 items-center gap-2">
                <span className="h-px w-3 shrink-0" style={{ backgroundColor: meta.accent }} />
                <span className="line-clamp-1">{cleanDisplayText(item.title)}</span>
              </span>
            ))}
          </span>
        ) : (
          <span className="mt-2 block text-[9px] text-[#929289]">No observed records in this area</span>
        )}
      </span>

      <span className="absolute right-0 top-5 flex items-center gap-3 sm:static sm:row-start-1 sm:justify-self-end lg:row-auto">
        <span className="text-right">
          <span className="block text-xl font-semibold tabular-nums leading-none tracking-[-0.04em] text-[#252520] dark:text-[#f1f1ea]">{loading ? "—" : count}</span>
          <span className="mt-1 block text-[8px] font-semibold uppercase tracking-[0.1em] text-[#999990]">{count === 1 ? "record" : "records"}</span>
        </span>
        <span className="flex h-8 w-8 items-center justify-center rounded-full border border-[#d7d7ce] text-[#77776e] transition-[transform,border-color,color] duration-200 group-hover:translate-x-0.5 group-hover:border-[var(--memory-accent)] group-hover:text-[var(--memory-accent)] dark:border-[#34342f]">
          <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
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
  const drawerRef = useRef(null);
  const onCloseRef = useRef(onClose);
  const meta = AREA_META[type.area];
  const Icon = type.icon;

  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    const returnFocusTo = document.activeElement;
    const appRoot = document.getElementById("root");
    const previousOverflow = document.body.style.overflow;
    appRoot?.setAttribute("inert", "");
    document.body.style.overflow = "hidden";
    closeRef.current?.focus();

    const onKeyDown = (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onCloseRef.current();
        return;
      }
      if (event.key !== "Tab") return;
      const focusable = Array.from(drawerRef.current?.querySelectorAll(
        'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])',
      ) || []).filter((element) => !element.hasAttribute("hidden"));
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      appRoot?.removeAttribute("inert");
      document.body.style.overflow = previousOverflow;
      window.requestAnimationFrame(() => returnFocusTo?.focus?.());
    };
  }, []);

  return (
    <div className="fixed inset-0 z-[100] flex justify-end bg-[#171713]/35 dark:bg-black/70" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <aside ref={drawerRef} role="dialog" aria-modal="true" aria-labelledby="memory-drawer-title" aria-describedby="memory-drawer-description" className="memory-drawer-enter relative flex h-[100dvh] w-full max-w-lg flex-col overscroll-contain border-l border-[#d8d8cf] bg-[#f7f7f2] shadow-[-20px_0_60px_rgba(23,23,19,0.16)] dark:border-[#292925] dark:bg-[#090908]">
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
          <p id="memory-drawer-description" className="mt-5 max-w-md text-sm leading-6 text-[#4f4f48] dark:text-[#c8c8bf]">{type.description}</p>
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
              {items.map((item) => <MemoryRecord key={item.id} item={item} reviewing={reviewingId === item.component_id} onReview={onReview} />)}
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
  const [confirmingClear, setConfirmingClear] = useState(false);

  useEffect(() => {
    setTitle(currentTitle);
    setConfirmingClear(false);
  }, [currentTitle]);

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
        {onClear ? <button type="button" disabled={saving} onClick={() => setConfirmingClear(true)} className="text-[10px] font-semibold text-[#7a5750] underline-offset-4 hover:underline disabled:opacity-40 dark:text-[#d6a69b]">Clear goal</button> : <span />}
        <button type="submit" disabled={locked || saving || title.trim().length < 3 || title.trim() === currentTitle} className="rounded-md bg-[#171713] px-3 py-2 text-[10px] font-semibold text-white transition-opacity disabled:opacity-35 dark:bg-[#d9ff68] dark:text-[#11110f]">{saving ? "Saving…" : currentTitle ? "Update goal" : "Set goal"}</button>
      </div>
      {confirmingClear ? (
        <div role="group" aria-label="Confirm clear current goal" className="mt-4 border-l-2 border-[#9a5e38] bg-[#9a5e38]/[0.06] px-3 py-3">
          <p className="text-[10px] font-semibold text-[#633c25] dark:text-[#e4ab85]">Clear the current project goal?</p>
          <p className="mt-1 text-[10px] leading-4 text-[#68685f] dark:text-[#aaa9a0]">This removes the focus from Memory and Now. It does not delete its history or change project files.</p>
          <div className="mt-3 flex items-center gap-3 text-[10px] font-semibold">
            <button type="button" disabled={saving} onClick={() => setConfirmingClear(false)} className="underline-offset-4 hover:underline disabled:opacity-40">Keep goal</button>
            <button type="button" disabled={saving} onClick={onClear} className="rounded-md bg-[#7a4030] px-2.5 py-1.5 text-white disabled:opacity-40 dark:bg-[#d38d74] dark:text-[#171713]">{saving ? "Clearing…" : "Clear current goal"}</button>
          </div>
        </div>
      ) : null}
    </form>
  );
}


function getTruthPresentation(item) {
  const status = String(item?.status || "").toLowerCase();
  const verification = String(item?.verification || "observed").toLowerCase();
  if (status.includes("conflict") || status.includes("contested")) {
    return { label: "Conflict flagged", Icon: GitMerge, className: "border-amber-300 text-amber-800 dark:border-amber-900 dark:text-amber-200" };
  }
  if (status.includes("stale") || status.includes("deprecated")) {
    return { label: "Stale — review required", Icon: Clock3, className: "border-amber-300 text-amber-800 dark:border-amber-900 dark:text-amber-200" };
  }
  if (status.includes("superseded")) {
    return { label: "Superseded", Icon: Archive, className: "border-[#c9c9c0] text-[#5f5f57] dark:border-[#393934] dark:text-[#bdbdb4]" };
  }
  if (status.includes("dismissed") || status.includes("rejected")) {
    return { label: "Dismissed", Icon: XCircle, className: "border-[#c9c9c0] text-[#5f5f57] dark:border-[#393934] dark:text-[#bdbdb4]" };
  }
  if (status.includes("resolved")) {
    return { label: "Resolved", Icon: CheckCheck, className: "border-[#c9c9c0] text-[#5f5f57] dark:border-[#393934] dark:text-[#bdbdb4]" };
  }
  if (status.includes("historical")) {
    return { label: "Historical record", Icon: History, className: "border-[#c9c9c0] text-[#5f5f57] dark:border-[#393934] dark:text-[#bdbdb4]" };
  }
  if (
    status.includes("needs_review")
    || status.includes("unverified")
    || status.includes("reported")
    || verification.includes("needs_review")
    || verification.includes("unverified")
    || verification.includes("reported")
  ) {
    return { label: "Needs human review", Icon: HelpCircle, className: "border-amber-300 text-amber-800 dark:border-amber-900 dark:text-amber-200" };
  }
  if (verification.includes("verified") || verification.includes("confirmed")) {
    return { label: "Verified evidence", Icon: CheckCircle2, className: "border-emerald-300 text-emerald-800 dark:border-emerald-900 dark:text-emerald-200" };
  }
  if (verification.includes("observed") || status.includes("observed")) {
    return { label: "Directly observed", Icon: Fingerprint, className: "border-[#c9c9c0] text-[#5f5f57] dark:border-[#393934] dark:text-[#bdbdb4]" };
  }
  return {
    label: status === "active" ? "Current record" : (status || verification).replaceAll("_", " "),
    Icon: Fingerprint,
    className: "border-[#c9c9c0] text-[#5f5f57] dark:border-[#393934] dark:text-[#bdbdb4]",
  };
}


function MemoryRecord({ item, reviewing, onReview }) {
  const actions = new Set(item.allowed_actions || []);
  const evidence = item.evidence || null;
  const source = item.source || null;
  const [confirmAction, setConfirmAction] = useState(null);
  const truth = getTruthPresentation(item);
  const TruthIcon = truth.Icon;
  const confirmCopy = confirmAction === "supersede"
    ? "This moves the record out of current memory while preserving it in History."
    : "This marks the extracted record as not useful or correct and preserves that decision in History.";

  useEffect(() => setConfirmAction(null), [item.id]);

  const submitConfirmedReview = async () => {
    if (!confirmAction) return;
    await onReview(item, confirmAction);
    setConfirmAction(null);
  };

  return (
    <article className="group border-b border-[#e1e1d9] p-4 last:border-b-0 dark:border-[#292925]">
      <div className="flex flex-col items-start gap-3 sm:flex-row sm:justify-between">
        <div className="min-w-0">
          {item.kind ? <p className="mb-1 text-[9px] font-semibold uppercase tracking-[0.1em] text-[#8a8a80]">{item.kind}</p> : null}
          <h4 className="text-[13px] font-semibold leading-5">{cleanDisplayText(item.title)}</h4>
          {item.summary && cleanDisplayText(item.summary) !== cleanDisplayText(item.title) ? <p className="mt-1.5 text-[11px] leading-5 text-[#68685f] dark:text-[#aaa9a0]">{cleanDisplayText(item.summary)}</p> : null}
        </div>
        <span className={`inline-flex shrink-0 items-center gap-1.5 rounded-full border px-2 py-1 text-[9px] font-semibold ${truth.className}`}>
          <TruthIcon className="h-3 w-3" aria-hidden="true" />
          {truth.label}
        </span>
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
            {evidence.exact ? "Exact source span" : "Captured evidence"} · {getTruthPresentation({ verification: evidence.review_status || item.verification }).label}
          </span>
        </blockquote>
      ) : null}
      {item.last_review ? (
        <p className="mt-2 text-[9px] text-[#8a8a80]">Last review: {item.last_review.action.replaceAll("_", " ")} by {item.last_review.reviewed_by}{item.last_review.reason ? ` — ${item.last_review.reason}` : ""}</p>
      ) : null}
      {item.component_id && actions.size ? (
        <div className="mt-3 border-t border-[#e5e5dd] pt-3 text-[10px] font-semibold dark:border-[#292925]">
          <div className="flex flex-wrap gap-x-3 gap-y-2">
            {actions.has("reopen") ? <button type="button" disabled={reviewing} onClick={() => onReview(item, "reopen")} className="text-[#4f4f48] underline-offset-4 hover:underline disabled:opacity-40 dark:text-[#d0d0c8]">Reopen</button> : null}
            {actions.has("confirm") ? <button type="button" disabled={reviewing} onClick={() => onReview(item, "confirm")} className="text-emerald-700 underline-offset-4 hover:underline disabled:opacity-40 dark:text-emerald-300">Confirm exact evidence</button> : null}
            {actions.has("resolve") ? <button type="button" disabled={reviewing} onClick={() => onReview(item, "resolve")} className="text-[#4f4f48] underline-offset-4 hover:underline disabled:opacity-40 dark:text-[#d0d0c8]">Resolve</button> : null}
            {actions.has("supersede") ? <button type="button" disabled={reviewing} onClick={() => setConfirmAction("supersede")} className="text-[#4f4f48] underline-offset-4 hover:underline disabled:opacity-40 dark:text-[#d0d0c8]">Supersede</button> : null}
            {actions.has("dismiss") ? <button type="button" disabled={reviewing} onClick={() => setConfirmAction("dismiss")} className="text-[#7a5750] underline-offset-4 hover:underline disabled:opacity-40 dark:text-[#d6a69b]">Dismiss</button> : null}
            {reviewing ? <span role="status" aria-live="polite" className="text-[#8a8a80]">Saving…</span> : null}
          </div>
          {confirmAction ? (
            <div role="group" aria-label={`Confirm ${confirmAction}`} className="mt-3 border-l-2 border-[#9a5e38] bg-[#9a5e38]/[0.06] px-3 py-2.5">
              <p className="font-normal leading-4 text-[#68685f] dark:text-[#aaa9a0]">{confirmCopy}</p>
              <div className="mt-2 flex items-center gap-3">
                <button type="button" disabled={reviewing} onClick={() => setConfirmAction(null)} className="underline-offset-4 hover:underline disabled:opacity-40">Cancel</button>
                <button type="button" disabled={reviewing} onClick={submitConfirmedReview} className="rounded-md bg-[#7a4030] px-2.5 py-1.5 text-white disabled:opacity-40 dark:bg-[#d38d74] dark:text-[#171713]">
                  {reviewing ? "Saving…" : `Confirm ${confirmAction}`}
                </button>
              </div>
            </div>
          ) : null}
        </div>
      ) : null}
    </article>
  );
}
