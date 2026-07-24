import { useDeferredValue, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Link, useSearchParams } from "react-router-dom";
import {
  AlertTriangle,
  Archive,
  ArrowRight,
  BookOpenCheck,
  Calendar,
  CheckCheck,
  CheckCircle2,
  ChevronDown,
  ClipboardCheck,
  Clock3,
  Database,
  Filter,
  Fingerprint,
  FolderGit2,
  GitMerge,
  GraduationCap,
  HelpCircle,
  History,
  Link2,
  ListTodo,
  Rocket,
  Search,
  ShieldAlert,
  SlidersHorizontal,
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
  { id: "overview", label: "Overview", description: "Current project truth and the source-backed claims that can become reusable memory." },
  { id: "active", label: "Current", description: "Claims a person or trusted system has confirmed as current project truth." },
  { id: "review", label: "Review queue", description: "Assistant-derived claims that need a human judgment before agents may reuse them." },
  { id: "freshness", label: "Source health", description: "Provider snapshots that must be refreshed before they can describe the project now." },
  { id: "people", label: "People & dates", description: "Responsibility and important delivery boundaries." },
  { id: "history", label: "History", description: "Reported activity, resolved work, review decisions, and immutable source revisions." },
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

  { id: "unverified", view: "review_state", sources: ["needs_review"], area: "uncertainty", title: "Ready to decide", description: "Source-backed claims that can be added to current memory or ruled out.", capture: "Human-judgment claims with exact evidence", icon: HelpCircle },
  { id: "conflicts", view: "review", sources: ["conflicts"], area: "uncertainty", title: "Conflicts", description: "Claims or directions that disagree with each other.", capture: "Conflict statuses and contradiction links", icon: GitMerge },
  { id: "stale", view: "freshness", sources: ["stale_context"], area: "uncertainty", title: "Refresh needed", description: "Provider snapshots that may no longer describe the project.", capture: "Stale facts and provider snapshots", icon: Clock3 },

  { id: "owners", view: "people", sources: ["owners"], area: "ownership", title: "Owners", description: "People responsible for moving project records forward.", capture: "Assignment and ownership links", icon: UserRound },
  { id: "milestones", view: "people", sources: ["milestones"], area: "ownership", title: "Milestones", description: "Important deadlines and delivery boundaries.", capture: "Explicit milestone, deadline, and target-date evidence", icon: Calendar },

  { id: "resolved", view: "history", sources: ["resolved_blockers"], area: "history", title: "Resolved blockers", description: "Past obstacles and the evidence that cleared them.", capture: "Resolved blocker records", icon: CheckCheck },
  { id: "completed", view: "history", sources: ["completed"], area: "history", title: "Completed & reported activity", description: "Point-in-time outcomes, checks, and work preserved without treating assistant prose as durable truth.", capture: "Completed records and reported session activity", icon: CheckCircle2 },
  { id: "superseded", view: "history", sources: ["superseded"], area: "history", title: "Superseded memory", description: "Old context preserved without treating it as current truth.", capture: "Superseded project records", icon: Archive },
  { id: "dismissed", view: "history", sources: ["dismissed"], area: "history", title: "Dismissed memory", description: "Extracted records a person decided were not useful or correct.", capture: "Human-dismissed project records", icon: XCircle },
  { id: "revisions", view: "history", sources: ["version_history"], area: "history", title: "Source revisions", description: "Records backed by revised sources or marked as historical.", capture: "Source revision and temporal history", icon: History },
];

const SOURCE_FILTERS = [
  { id: "all", label: "All sources" },
  { id: "documents", label: "Docs & goals" },
  { id: "repository", label: "Repository" },
  { id: "sessions", label: "Agent sessions" },
  { id: "integrations", label: "Integrations" },
];

const VERIFICATION_FILTERS = [
  { id: "all", label: "All evidence" },
  { id: "verified", label: "Verified" },
  { id: "observed", label: "Observed" },
  { id: "reported", label: "Reported activity" },
  { id: "needs_review", label: "Needs review" },
  { id: "unavailable", label: "No exact evidence" },
];

const TEMPORAL_FILTERS = [
  { id: "all", label: "Any time" },
  { id: "current", label: "Current" },
  { id: "future", label: "Planned" },
  { id: "past", label: "Past" },
  { id: "unknown", label: "Unknown" },
];

const VIEW_SECTION_IDS = {
  overview: [
    "requirements", "decisions", "work", "blockers", "risks", "learnings",
    "deliveries", "unverified", "conflicts",
  ],
  active: [
    "requirements", "decisions", "work", "blockers", "risks", "learnings",
    "deliveries",
  ],
  review: ["unverified", "conflicts"],
  freshness: ["stale"],
  people: ["owners", "milestones"],
  history: ["resolved", "completed", "superseded", "dismissed", "revisions"],
};


export default function ProjectMemory() {
  const [searchParams, setSearchParams] = useSearchParams();
  const workspace = useProductWorkspace();
  const reviewMemory = useReviewMemoryRecord(workspace.activeWorkspaceId);
  const setCurrentGoal = useSetCurrentGoal(workspace.activeWorkspaceId);
  const clearCurrentGoal = useClearCurrentGoal(workspace.activeWorkspaceId);
  const requestedView = searchParams.get("view");
  const view = MEMORY_VIEWS.some((item) => item.id === requestedView) ? requestedView : "overview";
  const requestedScope = searchParams.get("scope");
  const scopeMode = requestedScope === "workspace" ? "workspace" : "agenda";
  const semanticTypes = MEMORY_TYPES.filter(
    (type) => type.view === "active" && type.id !== "goal",
  );
  const requestedCategory = searchParams.get("category");
  const selectedCategory = (
    ["overview", "active", "review"].includes(view)
    && semanticTypes.some((type) => type.id === requestedCategory)
  ) ? requestedCategory : null;
  const requestedSection = searchParams.get("section");
  const selectedSection = MEMORY_TYPES.some((item) => item.id === requestedSection && item.view === view)
    ? requestedSection
    : null;
  const requestedSource = searchParams.get("source");
  const sourceGroup = SOURCE_FILTERS.some((item) => item.id === requestedSource) ? requestedSource : "all";
  const requestedVerification = searchParams.get("verification");
  const verification = VERIFICATION_FILTERS.some((item) => item.id === requestedVerification)
    ? requestedVerification
    : "all";
  const requestedTemporal = searchParams.get("temporal");
  const temporal = TEMPORAL_FILTERS.some((item) => item.id === requestedTemporal)
    ? requestedTemporal
    : "all";
  const kind = searchParams.get("kind") || "";
  const search = searchParams.get("q") || "";
  const deferredSearch = useDeferredValue(search);
  const [drawerType, setDrawerType] = useState(null);
  const [reviewingId, setReviewingId] = useState(null);
  const [reviewError, setReviewError] = useState(null);
  const [reviewNotice, setReviewNotice] = useState("");
  const [skippedReviewIds, setSkippedReviewIds] = useState([]);
  const [detailLimit, setDetailLimit] = useState(50);
  const requestSection = drawerType?.id || selectedSection;
  const requestSemanticSection = drawerType ? null : selectedCategory;
  const goalDrawerOpen = drawerType?.id === "goal";
  const memoryQuery = useProjectMemory(workspace.activeWorkspaceId, {
    query: deferredSearch,
    section: requestSection,
    semanticSection: requestSemanticSection,
    scope: scopeMode,
    sourceGroup: goalDrawerOpen ? "all" : sourceGroup,
    verification: goalDrawerOpen ? "all" : verification,
    temporal: goalDrawerOpen ? "all" : temporal,
    kind: goalDrawerOpen ? null : kind || null,
    limit: drawerType
      ? detailLimit
      : view === "review"
        ? detailLimit
        : (selectedSection || selectedCategory) ? 50 : 6,
  });
  const sectionsById = useMemo(() => Object.fromEntries(
    (memoryQuery.data?.sections || []).map((section) => [section.id, section]),
  ), [memoryQuery.data]);
  const visibleTypes = ["overview", "active", "review"].includes(view)
    ? semanticTypes
    : MEMORY_TYPES.filter((type) => type.view === view && type.id !== "goal");
  const displayedTypes = selectedCategory
    ? visibleTypes.filter((type) => type.id === selectedCategory)
    : view === "overview"
      ? [...visibleTypes].sort((left, right) => {
        const leftTotal = Number(sectionsById[left.id]?.total || 0)
          + Number(memoryQuery.data?.facets?.reviewable_semantic_sections?.[left.id] || 0);
        const rightTotal = Number(sectionsById[right.id]?.total || 0)
          + Number(memoryQuery.data?.facets?.reviewable_semantic_sections?.[right.id] || 0);
        return rightTotal - leftTotal;
      })
      : visibleTypes;
  const selectedView = MEMORY_VIEWS.find((item) => item.id === view) || MEMORY_VIEWS[0];
  const activeRecordCount = memoryQuery.data?.totals?.active || 0;
  const reviewRecordCount = memoryQuery.data?.totals?.needs_review || 0;
  const readyReviewCount = memoryQuery.data?.totals?.ready_to_review || 0;
  const conflictCount = memoryQuery.data?.totals?.conflicts || 0;
  const refreshRecordCount = memoryQuery.data?.totals?.needs_refresh || 0;
  const reportedActivityCount = memoryQuery.data?.totals?.reported_activity || 0;
  const peopleRecordCount = memoryQuery.data?.totals?.people_and_dates || 0;
  const historyRecordCount = memoryQuery.data?.totals?.history || 0;
  const currentGoal = memoryQuery.data?.current_goal || null;
  const agenda = memoryQuery.data?.agenda || null;
  const effectiveScope = memoryQuery.data?.filters?.effective_scope
    || memoryQuery.data?.scope?.effective_mode
    || "workspace";
  const goalType = MEMORY_TYPES.find((type) => type.id === "goal");
  const viewCounts = {
    overview: activeRecordCount + reviewRecordCount,
    active: activeRecordCount,
    review: reviewRecordCount,
    freshness: refreshRecordCount,
    people: peopleRecordCount,
    history: historyRecordCount,
  };
  const excludedSessionCount = Number(memoryQuery.data?.scope?.excluded_unknown_session_components || 0)
    + Number(memoryQuery.data?.scope?.excluded_irrelevant_session_components || 0);
  const excludedLowIntegrityCount = Number(memoryQuery.data?.scope?.excluded_unconfirmable_agent_components || 0)
    + Number(memoryQuery.data?.scope?.collapsed_duplicate_current_claims || 0)
    + Number(memoryQuery.data?.scope?.excluded_untrusted_relationships || 0);
  const collapsedRevisionCount = Number(
    memoryQuery.data?.scope?.collapsed_source_revision_components || 0,
  );
  const reviewSemanticCounts = memoryQuery.data?.facets?.review_semantic_sections || {};
  const reviewableSemanticCounts = memoryQuery.data?.facets?.reviewable_semantic_sections || {};
  const workspaceName = workspace.activeWorkspace?.name || "Current workspace";
  const selectedType = MEMORY_TYPES.find(
    (type) => type.id === (selectedCategory || selectedSection),
  ) || null;
  const typeForRecord = (record) => (
    semanticTypes.find((type) => type.id === record.semantic_section)
    || MEMORY_TYPES.find((type) => type.id === record.section)
    || MEMORY_TYPES.find((type) => type.id === "unverified")
  );
  const currentPreviewRecords = semanticTypes.flatMap((type) => (
    (sectionsById[type.id]?.records || []).map((record) => ({ record, type }))
  ));
  const reviewPreviewRecords = [
    ...(sectionsById.unverified?.records || []),
    ...(sectionsById.conflicts?.records || []),
  ].map((record) => ({ record, type: typeForRecord(record) }));
  const previewRecords = (
    view === "overview"
      ? [...reviewPreviewRecords, ...currentPreviewRecords]
      : view === "active"
        ? currentPreviewRecords
        : view === "review"
          ? reviewPreviewRecords
          : visibleTypes.flatMap((type) => (
            (sectionsById[type.id]?.records || []).map((record) => ({ record, type }))
          ))
  ).slice(0, selectedType ? 50 : 18);
  const kindSections = selectedSection
    ? [selectedSection]
    : VIEW_SECTION_IDS[view] || [];
  const facetKindCounts = kindSections.reduce((counts, sectionId) => {
    for (const [recordKind, count] of Object.entries(
      memoryQuery.data?.facets?.kinds_by_section?.[sectionId] || {},
    )) {
      counts[recordKind] = (counts[recordKind] || 0) + Number(count || 0);
    }
    return counts;
  }, {});
  const previewKindCounts = previewRecords.reduce((counts, { record }) => ({
    ...counts,
    [record.kind]: (counts[record.kind] || 0) + 1,
  }), {});
  const availableKinds = Object.entries(
    Object.keys(facetKindCounts).length ? facetKindCounts : previewKindCounts,
  )
    .sort(([left], [right]) => left.localeCompare(right));
  const viewMatchCount = selectedSection
    ? Number(memoryQuery.data?.matches || 0)
    : view === "overview"
      ? activeRecordCount + reviewRecordCount
      : view === "active"
        ? activeRecordCount
        : view === "review"
          ? reviewRecordCount
          : view === "freshness"
            ? refreshRecordCount
            : view === "people"
              ? peopleRecordCount
              : historyRecordCount;
  const reviewableRecords = (sectionsById.unverified?.records || []).filter(
    (record) => record.evidence?.exact && (record.allowed_actions || []).includes("confirm"),
  );
  const evidenceGapRecords = (sectionsById.unverified?.records || []).filter(
    (record) => !record.evidence?.exact || !(record.allowed_actions || []).includes("confirm"),
  );
  const currentReviewCandidate = reviewableRecords.find(
    (record) => !skippedReviewIds.includes(record.id),
  ) || null;
  const evidenceGapCount = Math.max(
    0,
    reviewRecordCount - readyReviewCount - conflictCount,
  );
  const reviewHasMore = Boolean(
    sectionsById.unverified?.has_more || sectionsById.conflicts?.has_more,
  );
  const activeFilterCount = [
    search.trim(),
    selectedSection,
    selectedCategory,
    sourceGroup !== "all",
    verification !== "all",
    temporal !== "all",
    kind,
  ].filter(Boolean).length;
  const advancedFilterCount = [
    sourceGroup !== "all",
    verification !== "all",
    temporal !== "all",
    kind,
  ].filter(Boolean).length;

  useEffect(() => {
    setSkippedReviewIds([]);
    setReviewNotice("");
  }, [selectedCategory, scopeMode, sourceGroup, verification, temporal, kind, deferredSearch]);

  const handleReview = async (item, action) => {
    if (!item.component_id) return;
    setReviewingId(item.component_id);
    setReviewError(null);
    try {
      const result = await reviewMemory.mutateAsync({
        componentId: item.component_id,
        action,
      });
      setSkippedReviewIds((current) => (
        current.includes(item.id) ? current : [...current, item.id]
      ));
      const affected = Number(result?.affected_components || item.occurrence_count || 1);
      setReviewNotice(action === "confirm"
        ? `Added to Current ${typeForRecord(item)?.title || "memory"}. ${affected > 1 ? `${affected} matching occurrences were updated.` : "Future agent briefs may now reuse it."}`
        : action === "supersede"
          ? "Marked not current and preserved in History."
          : action === "dismiss"
            ? "Kept out of project memory and preserved in History."
            : "Memory updated.");
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
    setDrawerType(type);
  };

  const selectView = (nextView) => {
    const next = new URLSearchParams(searchParams);
    if (nextView === "overview") next.delete("view");
    else next.set("view", nextView);
    next.delete("section");
    next.delete("category");
    next.delete("kind");
    setDetailLimit(50);
    setDrawerType(null);
    setSearchParams(next, { replace: true });
  };

  const updateFilter = (key, value, defaultValue = "") => {
    const next = new URLSearchParams(searchParams);
    if (!value || value === defaultValue) next.delete(key);
    else next.set(key, value);
    if (key === "section" || key === "category") next.delete("kind");
    setDetailLimit(50);
    setDrawerType(null);
    setSearchParams(next, { replace: true });
  };

  const filterByType = (type) => {
    if (["overview", "active", "review"].includes(view)) {
      updateFilter("category", selectedCategory === type.id ? "" : type.id);
      return;
    }
    updateFilter("section", selectedSection === type.id ? "" : type.id);
  };

  const openCategory = (nextView, type) => {
    const next = new URLSearchParams(searchParams);
    if (nextView === "overview") next.delete("view");
    else next.set("view", nextView);
    next.set("category", type.id);
    next.delete("section");
    next.delete("kind");
    setDetailLimit(50);
    setDrawerType(null);
    setSearchParams(next, { replace: true });
  };

  const clearFilters = () => {
    const next = new URLSearchParams(searchParams);
    ["q", "section", "category", "source", "verification", "temporal", "kind"].forEach((key) => next.delete(key));
    setDetailLimit(50);
    setDrawerType(null);
    setSearchParams(next, { replace: true });
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
    <div className="relative mx-auto w-full max-w-7xl space-y-6 pb-16">
      <header className="flex flex-col gap-5 border-b border-line pb-7 lg:flex-row lg:items-end lg:justify-between">
        <div className="max-w-3xl">
          <div className="mb-3 flex flex-wrap items-center gap-2 text-xs font-semibold text-ink-muted">
            <span className="inline-flex items-center gap-2 rounded-full border border-line bg-surface-raised px-3 py-1.5">
              <FolderGit2 className="h-3.5 w-3.5" aria-hidden="true" />
              {workspaceName}
            </span>
            <span aria-hidden="true" className="text-ink-subtle">/</span>
            <span>Memory</span>
          </div>
          <h1 className="text-3xl font-black tracking-[-0.035em] text-ink sm:text-4xl">Project memory</h1>
          <p className="mt-3 max-w-2xl text-sm leading-6 text-ink-muted sm:text-[15px]">
            Trusted project knowledge, narrowed to the work that matters now and always traceable to its source.
          </p>
        </div>
        <div className="grid grid-cols-3 overflow-hidden rounded-surface border border-line bg-surface shadow-elevation-1">
          <MemoryStat label="Current" value={activeRecordCount} />
          <MemoryStat label="To decide" value={readyReviewCount} attention={readyReviewCount > 0} />
          <MemoryStat label="Refresh" value={refreshRecordCount} />
        </div>
      </header>

      <section aria-labelledby="workspace-agenda-heading" className="app-surface">
        <div className="grid lg:grid-cols-[minmax(0,1fr)_auto]">
          <div className="p-5 sm:p-6 lg:p-7">
            <div className="flex flex-wrap items-center gap-2">
              <span className="inline-flex items-center gap-2 rounded-full bg-accent px-3 py-1.5 text-xs font-semibold text-accent-ink">
                <Target className="h-3.5 w-3.5" aria-hidden="true" />
                Workspace agenda
              </span>
              <span className="text-xs font-medium text-ink-subtle">
                {agenda?.kind === "selected_session" ? "Selected in Library" : currentGoal ? "Explicit focus" : "No focus selected"}
              </span>
            </div>
            <h2 id="workspace-agenda-heading" className="mt-4 max-w-3xl text-xl font-semibold leading-7 tracking-[-0.03em] text-ink sm:text-2xl">
              {agenda?.title || `All trusted knowledge in ${workspaceName}`}
            </h2>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-ink-muted">
              {scopeExplanation({ scopeMode, effectiveScope, agenda, workspaceName })}
            </p>
            <div className="mt-4 flex flex-wrap items-center gap-3">
              <button
                type="button"
                aria-label="Open Current goal"
                onClick={() => openMemoryType(goalType)}
                className="btn-secondary min-h-11 px-4 text-xs"
              >
                {currentGoal ? "Edit agenda" : "Set agenda"}
                <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
              </button>
              {effectiveScope === "agenda_match" ? (
                <span className="inline-flex items-center gap-2 text-xs text-attention">
                  <HelpCircle className="h-3.5 w-3.5" aria-hidden="true" />
                  Text-matched scope; every record shows why it matched.
                </span>
              ) : null}
            </div>
          </div>
          <div className="border-t border-line bg-surface-raised p-4 lg:flex lg:min-w-[260px] lg:flex-col lg:justify-center lg:border-l lg:border-t-0">
            <p className="mb-2 text-xs font-semibold text-ink-muted">Memory scope</p>
            <div className="grid grid-cols-2 gap-2 lg:grid-cols-1" role="group" aria-label="Memory scope">
              <ScopeButton
                active={scopeMode === "agenda"}
                label="Current agenda"
                detail={agenda ? "Focused records" : "Falls back safely"}
                onClick={() => updateFilter("scope", "agenda", "agenda")}
              />
              <ScopeButton
                active={scopeMode === "workspace"}
                label={`All ${workspaceName}`}
                detail="Entire workspace"
                onClick={() => updateFilter("scope", "workspace", "agenda")}
              />
            </div>
          </div>
        </div>
      </section>

      {memoryQuery.isError ? (
        <div role="alert" className="rounded-control border border-attention/40 bg-attention/10 px-4 py-3 text-sm font-medium text-ink">
          Project memory could not be loaded. No cached or inferred records are being shown.
        </div>
      ) : null}

      {view === "overview" ? (
        <MemoryReadinessPanel
          currentCount={activeRecordCount}
          readyCount={readyReviewCount}
          conflictCount={conflictCount}
          refreshCount={refreshRecordCount}
          evidenceGapCount={evidenceGapCount}
          reportedCount={reportedActivityCount}
          hasGoal={Boolean(currentGoal)}
          loading={memoryQuery.isLoading}
          onReview={() => selectView("review")}
          onSetGoal={() => openMemoryType(goalType)}
        />
      ) : null}

      <section aria-labelledby="memory-filter-heading" className="app-surface p-4 sm:p-5">
        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
            <div>
              <div className="flex items-center gap-2">
                <SlidersHorizontal className="h-4 w-4 text-ink-muted" aria-hidden="true" />
                <h2 id="memory-filter-heading" className="text-sm font-semibold text-ink">Find memory</h2>
                {activeFilterCount ? (
                  <span className="rounded-full bg-accent px-2 py-0.5 text-[11px] font-semibold text-accent-ink">{activeFilterCount}</span>
                ) : null}
              </div>
              <p className="mt-1 text-xs leading-5 text-ink-muted">Search first; open advanced filters only when you need them.</p>
            </div>
            <label className="relative block w-full lg:max-w-sm">
              <span className="sr-only">Search memory</span>
              <Search className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-subtle" aria-hidden="true" />
              <input
                type="search"
                value={search}
                onChange={(event) => updateFilter("q", event.target.value)}
                placeholder={`Search ${workspaceName} memory`}
                className="h-11 w-full rounded-control border border-line bg-surface-raised pl-10 pr-4 text-sm font-medium text-ink outline-none placeholder:text-ink-subtle focus:border-line-strong"
              />
            </label>
          </div>

          <nav aria-label="Memory views" className="no-scrollbar flex min-w-0 gap-2 overflow-x-auto pb-1">
            {MEMORY_VIEWS.map((memoryView) => (
              <button
                type="button"
                key={memoryView.id}
                aria-label={memoryView.label}
                aria-pressed={view === memoryView.id}
                onClick={() => selectView(memoryView.id)}
                className={`inline-flex min-h-10 shrink-0 items-center gap-2 rounded-control border px-3.5 text-xs font-semibold transition ${
                  view === memoryView.id
                    ? "border-ink bg-ink text-canvas"
                    : "border-line bg-surface text-ink-muted hover:border-line-strong hover:text-ink"
                }`}
              >
                {memoryView.label}
                <span className="tabular-nums opacity-70">{viewCounts[memoryView.id].toLocaleString()}</span>
              </button>
            ))}
          </nav>

          <details className="group border-t border-line pt-3" open={advancedFilterCount > 0 ? true : undefined}>
            <summary className="flex min-h-10 cursor-pointer list-none items-center justify-between rounded-control px-2 text-xs font-semibold text-ink-muted marker:hidden hover:bg-surface-muted hover:text-ink">
              <span className="inline-flex items-center gap-2">
                <Filter className="h-3.5 w-3.5" aria-hidden="true" />
                Advanced filters
                {advancedFilterCount ? <span className="rounded-full bg-accent px-2 py-0.5 text-[10px] text-accent-ink">{advancedFilterCount}</span> : null}
              </span>
              <ChevronDown className="h-3.5 w-3.5 transition-transform group-open:rotate-180" aria-hidden="true" />
            </summary>
            <div className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              <FilterSelect
                label="Source"
                value={sourceGroup}
                options={SOURCE_FILTERS}
                onChange={(value) => updateFilter("source", value, "all")}
              />
              <FilterSelect
                label="Evidence"
                value={verification}
                options={VERIFICATION_FILTERS}
                onChange={(value) => updateFilter("verification", value, "all")}
              />
              <FilterSelect
                label="Time"
                value={temporal}
                options={TEMPORAL_FILTERS}
                onChange={(value) => updateFilter("temporal", value, "all")}
              />
              <FilterSelect
                label="Subtype"
                value={kind}
                options={[
                  { id: "", label: "All subtypes" },
                  ...availableKinds.map(([value, count]) => ({ id: value, label: `${value} (${count})` })),
                ]}
                onChange={(value) => updateFilter("kind", value)}
                disabled={!availableKinds.length}
              />
            </div>
          </details>

          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line pt-3">
            <p role="status" aria-live="polite" className="text-xs font-medium text-ink-muted">
              {memoryQuery.isLoading ? "Reading source-backed memory…" : `${viewMatchCount.toLocaleString()} matching ${viewMatchCount === 1 ? "record" : "records"} in ${selectedType ? selectedType.title : selectedView.label}`}
            </p>
            {activeFilterCount ? (
              <button type="button" onClick={clearFilters} className="inline-flex min-h-10 items-center gap-2 rounded-control px-3 text-xs font-semibold text-ink-muted hover:bg-surface-muted hover:text-ink">
                <Filter className="h-3.5 w-3.5" aria-hidden="true" />
                Clear filters
              </button>
            ) : null}
          </div>
        </div>
      </section>

      <section aria-labelledby="memory-categories-heading">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p className="text-xs font-semibold text-ink-subtle">{selectedView.label}</p>
            <h2 id="memory-categories-heading" className="mt-1 text-xl font-semibold tracking-[-0.03em] text-ink">
              {view === "overview" ? "Working memory by type" : view === "review" ? "Review by project meaning" : "Choose a memory type"}
            </h2>
            <p className="mt-1 max-w-2xl text-sm leading-6 text-ink-muted">{selectedView.description}</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {view === "freshness" && refreshRecordCount > 0 ? (
              <Link to="/app/connectors" className="btn-secondary min-h-10 px-3 text-xs">
                Open Integrations to refresh
                <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
              </Link>
            ) : null}
            {selectedSection || selectedCategory ? (
              <button
                type="button"
                onClick={() => updateFilter(selectedCategory ? "category" : "section", "")}
                className="min-h-10 self-start rounded-control px-3 text-xs font-semibold text-ink-muted hover:bg-surface-muted hover:text-ink"
              >
                Show all types
              </button>
            ) : null}
          </div>
        </div>
        <div className="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {displayedTypes.map((type, index) => view === "overview" ? (
            <MemoryCategoryCard
              key={type.id}
              type={type}
              currentCount={Number(sectionsById[type.id]?.total || 0)}
              candidateCount={Number(reviewableSemanticCounts[type.id] || 0)}
              loading={memoryQuery.isLoading}
              index={index}
              onViewCurrent={() => openCategory("active", type)}
              onReview={() => openCategory("review", type)}
            />
          ) : (
            <MemoryTypeCard
              key={type.id}
              type={type}
              count={view === "review"
                ? Number(reviewSemanticCounts[type.id] || 0)
                : Number(sectionsById[type.id]?.total || 0)}
              items={view === "review"
                ? reviewPreviewRecords
                  .filter(({ record }) => record.semantic_section === type.id)
                  .map(({ record }) => record)
                : sectionsById[type.id]?.records || []}
              loading={memoryQuery.isLoading}
              selected={(selectedCategory || selectedSection) === type.id}
              reviewCount={view === "active"
                ? Number(reviewableSemanticCounts[type.id] || 0)
                : 0}
              countLabel={view === "review" ? "to decide" : "records"}
              emptyLabel={view === "active" ? "No confirmed records in this scope" : undefined}
              index={index}
              onSelect={() => filterByType(type)}
            />
          ))}
        </div>
      </section>

      {view === "review" ? (
        <ReviewWorkspace
          candidate={currentReviewCandidate}
          remaining={readyReviewCount}
          shownRemaining={reviewableRecords.filter((record) => !skippedReviewIds.includes(record.id)).length}
          conflictCount={conflictCount}
          conflictRecords={sectionsById.conflicts?.records || []}
          evidenceGapCount={evidenceGapCount}
          evidenceGapRecords={evidenceGapRecords}
          selectedType={selectedType}
          reviewingId={reviewingId}
          error={reviewError}
          notice={reviewNotice}
          onReview={handleReview}
          onSkip={(item) => {
            setSkippedReviewIds((current) => (
              current.includes(item.id) ? current : [...current, item.id]
            ));
            setReviewNotice("Skipped for this visit. Nothing was changed.");
          }}
          onResetSkipped={() => {
            setSkippedReviewIds([]);
            setReviewNotice("");
          }}
          onOpenSourceHealth={() => selectView("freshness")}
          refreshCount={refreshRecordCount}
          hasMore={reviewHasMore}
          onLoadMore={() => setDetailLimit((value) => Math.min(500, value + 50))}
        />
      ) : (
      <section aria-labelledby="matching-memory-heading" className="app-surface">
        <header className="flex flex-col gap-2 border-b border-line px-5 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-6">
          <div>
            <p className="text-xs font-semibold text-ink-subtle">{selectedType ? selectedType.title : selectedView.label}</p>
            <h2 id="matching-memory-heading" className="mt-0.5 text-lg font-semibold tracking-[-0.025em] text-ink">
              {view === "overview" ? "What deserves attention next" : "Source-backed records"}
            </h2>
          </div>
          <span className="text-xs font-medium tabular-nums text-ink-muted">{previewRecords.length} shown</span>
        </header>
        {previewRecords.length ? (
          <div className="grid lg:grid-cols-2">
            {previewRecords.map(({ record, type }, index) => (
              <RecordPreview
                key={record.id}
                item={record}
                type={type}
                index={index}
                onOpen={() => {
                  if (view === "overview" && ["unverified", "conflicts"].includes(record.section)) {
                    openCategory("review", type);
                  } else if (view === "overview" && semanticTypes.some((item) => item.id === type.id)) {
                    openCategory("active", type);
                  } else {
                    openMemoryType(type);
                  }
                }}
              />
            ))}
          </div>
        ) : (
          <div className="px-6 py-14 text-center">
            <Database className="mx-auto h-6 w-6 text-ink-subtle" aria-hidden="true" />
            <p className="mt-3 text-sm font-semibold text-ink">
              {view === "active" && readyReviewCount > 0 ? "No confirmed memory yet" : "No matching source-backed records"}
            </p>
            <p className="mx-auto mt-2 max-w-lg text-xs leading-5 text-ink-muted">
              {view === "active" && readyReviewCount > 0
                ? `Current stays empty until you decide which of the ${readyReviewCount.toLocaleString()} source-backed candidates still describe the project.`
                : scopeMode === "agenda" && agenda
                ? "Nothing in this truth state is linked to the current agenda and the active filters."
                : "Try another memory type or clear one of the filters above."}
            </p>
            <div className="mt-4 flex flex-wrap justify-center gap-2">
              {view === "active" && readyReviewCount > 0 ? (
                <button type="button" onClick={() => selectView("review")} className="btn-secondary min-h-11 text-xs">
                  Review {readyReviewCount.toLocaleString()} {readyReviewCount === 1 ? "candidate" : "candidates"}
                </button>
              ) : null}
              {activeFilterCount ? <button type="button" onClick={clearFilters} className="btn-secondary min-h-11 text-xs">Clear filters</button> : null}
            </div>
          </div>
        )}
      </section>
      )}

      {!memoryQuery.isError && (excludedSessionCount > 0 || excludedLowIntegrityCount > 0 || collapsedRevisionCount > 0) ? (
        <details className="group rounded-control border border-line bg-surface-raised">
          <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between gap-3 px-4 py-2.5 text-xs font-semibold text-ink-muted marker:hidden hover:text-ink">
            <span className="inline-flex items-center gap-2">
              <Fingerprint className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
              Memory hygiene
            </span>
            <span className="inline-flex items-center gap-2 text-[11px] font-medium text-ink-subtle">
              {(
                excludedSessionCount
                + excludedLowIntegrityCount
                + collapsedRevisionCount
              ).toLocaleString()} records kept out of the working view
              <ChevronDown className="h-3.5 w-3.5 transition-transform group-open:rotate-180" aria-hidden="true" />
            </span>
          </summary>
          <div className="grid gap-2 border-t border-line px-4 py-3 text-xs leading-5 text-ink-muted sm:grid-cols-3">
            {excludedSessionCount > 0 ? <p><span className="font-semibold text-ink">{excludedSessionCount.toLocaleString()}</span> session records did not deterministically match this workspace.</p> : null}
            {excludedLowIntegrityCount > 0 ? <p><span className="font-semibold text-ink">{excludedLowIntegrityCount.toLocaleString()}</span> unconfirmable, duplicate, or untrusted records were hidden.</p> : null}
            {collapsedRevisionCount > 0 ? <p><span className="font-semibold text-ink">{collapsedRevisionCount.toLocaleString()}</span> mechanical projections were collapsed; immutable source revisions remain in History.</p> : null}
          </div>
        </details>
      ) : null}

      {drawerType ? createPortal(
        <MemoryDrawer
          type={drawerType}
          items={sectionsById[drawerType.id]?.records || []}
          total={sectionsById[drawerType.id]?.total || 0}
          hasMore={sectionsById[drawerType.id]?.has_more || false}
          loading={memoryQuery.isLoading}
          reviewingId={reviewingId}
          reviewError={reviewError}
          onReview={handleReview}
          goalSaving={setCurrentGoal.isPending || clearCurrentGoal.isPending}
          onSetGoal={handleSetGoal}
          onClearGoal={handleClearGoal}
          currentGoal={memoryQuery.data?.current_goal || null}
          hasSelectedSession={Boolean(
            memoryQuery.data?.scope?.selected_session_document_id,
          )}
          onLoadMore={() => setDetailLimit((value) => Math.min(500, value + 50))}
          onClose={() => setDrawerType(null)}
        />,
        document.body,
      ) : null}
    </div>
  );
}


function MemoryStat({ value, label, attention = false }) {
  return (
    <div className="min-w-[76px] border-r border-line px-3 py-3 text-center last:border-r-0 sm:min-w-[92px]">
      <p className={`text-xl font-semibold tabular-nums tracking-[-0.035em] ${attention ? "text-attention" : "text-ink"}`}>{value}</p>
      <p className="mt-0.5 text-[11px] font-medium text-ink-muted">{label}</p>
    </div>
  );
}


function MemoryReadinessPanel({
  currentCount,
  readyCount,
  conflictCount,
  refreshCount,
  evidenceGapCount,
  reportedCount,
  hasGoal,
  loading,
  onReview,
  onSetGoal,
}) {
  const bootstrap = !loading && currentCount === 0 && readyCount > 0;
  const ready = (
    !loading
    && currentCount > 0
    && readyCount === 0
    && conflictCount === 0
  );
  return (
    <section aria-labelledby="memory-readiness-heading" className="overflow-hidden rounded-surface border border-line bg-ink text-canvas shadow-elevation-1">
      <div className="grid lg:grid-cols-[minmax(0,1fr)_auto]">
        <div className="p-5 sm:p-7">
          <div className="flex items-center gap-2 text-xs font-semibold text-accent">
            <BookOpenCheck className="h-4 w-4" aria-hidden="true" />
            Memory readiness
          </div>
          <h2 id="memory-readiness-heading" className="mt-3 max-w-2xl text-2xl font-semibold tracking-[-0.035em]">
            {loading
              ? "Checking what agents can safely reuse…"
              : bootstrap
                ? "Your memory isn’t empty — it needs your judgment"
                : currentCount === 0 && conflictCount > 0
                  ? "Current is empty while conflicts remain"
                  : currentCount === 0 && refreshCount > 0
                    ? "Current is empty until sources are refreshed"
                    : currentCount === 0 && evidenceGapCount > 0
                      ? "Current is empty because evidence is incomplete"
                : ready
                  ? "Current memory is ready to reuse"
                  : currentCount > 0
                    ? "Keep reusable project truth small and current"
                    : "No reusable memory yet"}
          </h2>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-canvas/70">
            {bootstrap
              ? `Context Engine found ${readyCount.toLocaleString()} source-backed ${readyCount === 1 ? "claim" : "claims"}, but none has been accepted as current project truth.`
              : currentCount === 0 && conflictCount > 0
                ? "Conflicting claims stay out of Current until you compare them and rule out the version that should not remain current."
                : currentCount === 0 && refreshCount > 0
                  ? "Provider snapshots stay out of Current until a successful source refresh proves which exact remote revision was observed."
                  : currentCount === 0 && evidenceGapCount > 0
                    ? "Some extracted records lack an exact source span. They cannot be verified or reused until extraction captures traceable evidence."
              : "Current memory is the source-backed set Context Engine may place in future agent briefs. The review queue contains suggestions, not facts."}
          </p>
          <p className="mt-2 max-w-3xl text-xs leading-5 text-canvas/55">
            Exact evidence proves where a claim came from. Adding it to Current means you attest that it is correct, relevant, and still describes the project now.
          </p>
          <div className="mt-5 flex flex-wrap gap-2">
            {readyCount > 0 ? (
              <button type="button" onClick={onReview} className="inline-flex min-h-11 items-center gap-2 rounded-control bg-accent px-4 text-xs font-semibold text-accent-ink">
                Review {readyCount.toLocaleString()} {readyCount === 1 ? "candidate" : "candidates"}
                <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
              </button>
            ) : null}
            <button type="button" onClick={onSetGoal} className="min-h-11 rounded-control border border-canvas/20 px-4 text-xs font-semibold text-canvas hover:bg-canvas/10">
              {hasGoal ? "Edit current goal" : "Set current goal"}
            </button>
          </div>
        </div>
        <div className="grid min-w-[280px] grid-cols-2 border-t border-canvas/10 bg-canvas/[0.04] lg:border-l lg:border-t-0">
          <ReadinessMetric label="Current facts" value={currentCount} />
          <ReadinessMetric label="To decide" value={readyCount} attention={readyCount > 0} />
          <ReadinessMetric label="Conflicts" value={conflictCount} />
          <ReadinessMetric label="Need refresh" value={refreshCount} />
        </div>
      </div>
      {reportedCount > 0 ? (
        <p className="border-t border-canvas/10 px-5 py-3 text-[11px] leading-5 text-canvas/55 sm:px-7">
          {reportedCount.toLocaleString()} assistant-reported checks and outcomes were kept as activity history—not turned into verification work.
        </p>
      ) : null}
      {evidenceGapCount > 0 ? (
        <p className="border-t border-canvas/10 px-5 py-3 text-[11px] leading-5 text-canvas/55 sm:px-7">
          {evidenceGapCount.toLocaleString()} {evidenceGapCount === 1 ? "record lacks" : "records lack"} exact evidence and can only be cleaned up—not promoted to Current.
        </p>
      ) : null}
    </section>
  );
}


function ReadinessMetric({ label, value, attention = false }) {
  return (
    <div className="border-b border-r border-canvas/10 p-4 last:border-b-0">
      <p className={`text-2xl font-semibold tabular-nums ${attention ? "text-accent" : "text-canvas"}`}>{value}</p>
      <p className="mt-1 text-[11px] font-medium text-canvas/55">{label}</p>
    </div>
  );
}


function MemoryCategoryCard({
  type,
  currentCount,
  candidateCount,
  loading,
  index,
  onViewCurrent,
  onReview,
}) {
  const meta = AREA_META[type.area];
  const Icon = type.icon;
  const empty = !loading && currentCount === 0 && candidateCount === 0;
  return (
    <article
      className="memory-card-enter relative overflow-hidden rounded-surface border border-line bg-surface p-4 shadow-elevation-1"
      style={{ animationDelay: `${Math.min(index, 12) * 20}ms` }}
    >
      <span aria-hidden="true" className="absolute inset-x-0 top-0 h-1" style={{ backgroundColor: meta.accent }} />
      <div className="flex items-center gap-3 pt-1">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-control bg-surface-muted" style={{ color: meta.accent }}>
          <Icon className="h-4 w-4" aria-hidden="true" />
        </span>
        <h3 className="text-sm font-semibold tracking-[-0.015em] text-ink">{type.title}</h3>
      </div>
      <p className="mt-3 min-h-10 text-xs leading-5 text-ink-muted">{type.description}</p>
      {empty ? (
        <div className="mt-4 flex min-h-[58px] items-center rounded-control border border-dashed border-line bg-surface-raised px-3 text-xs font-medium text-ink-subtle">
          No source-backed records yet
        </div>
      ) : (
        <dl className="mt-4 grid grid-cols-2 overflow-hidden rounded-control border border-line">
          <div className="border-r border-line bg-surface-raised px-3 py-2.5">
            <dt className="text-[10px] font-medium text-ink-subtle">Current</dt>
            <dd className="mt-0.5 text-lg font-semibold tabular-nums text-ink">{loading ? "—" : currentCount}</dd>
          </div>
          <div className={candidateCount > 0 ? "bg-attention/10 px-3 py-2.5" : "bg-surface-raised px-3 py-2.5"}>
            <dt className={`text-[10px] font-medium ${candidateCount > 0 ? "text-attention" : "text-ink-subtle"}`}>Candidates</dt>
            <dd className={`mt-0.5 text-lg font-semibold tabular-nums ${candidateCount > 0 ? "text-attention" : "text-ink"}`}>{loading ? "—" : candidateCount}</dd>
          </div>
        </dl>
      )}
      <div className="mt-3 flex min-h-10 items-center justify-between gap-2">
        {currentCount > 0 ? (
          <button type="button" onClick={onViewCurrent} className="min-h-10 rounded-control px-2 text-[11px] font-semibold text-ink-muted hover:bg-surface-muted hover:text-ink">
            View current
          </button>
        ) : <span className="text-[11px] text-ink-subtle">{candidateCount ? "Nothing confirmed yet" : "Captured when evidence appears"}</span>}
        {candidateCount > 0 ? (
          <button type="button" onClick={onReview} className="inline-flex min-h-10 items-center gap-1.5 rounded-control bg-ink px-3 text-[11px] font-semibold text-canvas">
            Review {candidateCount}
            <ArrowRight className="h-3 w-3" aria-hidden="true" />
          </button>
        ) : null}
      </div>
    </article>
  );
}


function ReviewWorkspace({
  candidate,
  remaining,
  shownRemaining,
  conflictCount,
  conflictRecords,
  evidenceGapCount,
  evidenceGapRecords,
  selectedType,
  reviewingId,
  error,
  notice,
  onReview,
  onSkip,
  onResetSkipped,
  onOpenSourceHealth,
  refreshCount,
  hasMore,
  onLoadMore,
}) {
  const source = candidate?.source || null;
  const evidence = candidate?.evidence || null;
  const destination = selectedType?.title
    || MEMORY_TYPES.find((type) => type.id === candidate?.semantic_section)?.title
    || "Current memory";
  const candidateReviewing = reviewingId === candidate?.component_id;
  return (
    <section aria-labelledby="review-workspace-heading" className="app-surface overflow-hidden">
      <header className="border-b border-line px-5 py-4 sm:px-6">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="text-xs font-semibold text-ink-subtle">Guided review</p>
            <h2 id="review-workspace-heading" className="mt-0.5 text-xl font-semibold tracking-[-0.03em] text-ink">
              {selectedType ? `Review ${selectedType.title.toLowerCase()}` : "Decide what future agents may reuse"}
            </h2>
          </div>
          <span className="rounded-full bg-attention/10 px-3 py-1.5 text-xs font-semibold tabular-nums text-attention">
            {remaining.toLocaleString()} {remaining === 1 ? "claim" : "claims"} to decide
            {conflictCount > 0 ? ` · ${conflictCount.toLocaleString()} ${conflictCount === 1 ? "conflict" : "conflicts"}` : ""}
            {evidenceGapCount > 0 ? ` · ${evidenceGapCount.toLocaleString()} evidence ${evidenceGapCount === 1 ? "gap" : "gaps"}` : ""}
          </span>
        </div>
        <p className="mt-2 max-w-3xl text-xs leading-5 text-ink-muted">
          Exact-evidence claims are decided one at a time. Evidence gaps are listed separately and cannot be added to Current; reported checks stay in History and provider snapshots stay in Source health.
        </p>
      </header>
      {notice ? <p role="status" aria-live="polite" className="border-b border-line bg-accent/15 px-5 py-3 text-xs font-semibold text-ink sm:px-6">{notice}</p> : null}
      {error ? <p role="alert" className="border-b border-red-300 bg-red-50 px-5 py-3 text-xs font-semibold text-red-800 dark:border-red-950 dark:bg-red-950/20 dark:text-red-200">{error}</p> : null}
      {candidate ? (
        <article className="grid lg:grid-cols-[minmax(0,1fr)_320px]">
          <div className="p-5 sm:p-7">
            <div className="flex flex-wrap items-center gap-2 text-[11px] font-semibold text-ink-muted">
              <span className="rounded-full bg-surface-muted px-2.5 py-1">{candidate.kind}</span>
              {source?.label ? <span>{source.label}</span> : null}
              {source?.revision_number ? <span>Revision {source.revision_number}</span> : null}
              {candidate.last_observed_at ? <span>{formatTimeAgo(candidate.last_observed_at)}</span> : null}
            </div>
            <h3 className="mt-4 text-xl font-semibold leading-8 tracking-[-0.025em] text-ink">{cleanDisplayText(candidate.title)}</h3>
            {evidence?.excerpt ? (
              <div className="mt-5">
                <p className="text-[11px] font-semibold text-ink-muted">Exact source evidence</p>
                <blockquote className="mt-2 rounded-control border border-line bg-surface-raised p-4 text-sm leading-6 text-ink">
                  “{cleanDisplayText(evidence.excerpt)}”
                </blockquote>
              </div>
            ) : null}
            {candidate.occurrence_count > 1 ? (
              <p className="mt-3 text-xs leading-5 text-ink-muted">
                This claim appears in {candidate.occurrence_count} matching source occurrences. One decision updates the canonical claim across those occurrences.
              </p>
            ) : null}
          </div>
          <aside className="border-t border-line bg-surface-raised p-5 lg:border-l lg:border-t-0">
            <p className="text-xs font-semibold text-ink">What your decision means</p>
            <p className="mt-2 text-xs leading-5 text-ink-muted">
              The excerpt proves where this claim came from—not that it is true. Add it only if it is correct, relevant, and still current.
            </p>
            <div className="mt-4 rounded-control border border-line bg-surface p-3">
              <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-ink-subtle">Impact</p>
              <p className="mt-1 text-xs leading-5 text-ink">
                Adds this to <strong>{destination}</strong> in Current and makes it eligible for future agent briefs.
              </p>
            </div>
            <div className="mt-5 grid gap-2">
              <button type="button" disabled={candidateReviewing} onClick={() => onReview(candidate, "confirm")} className="min-h-11 rounded-control bg-ink px-4 text-xs font-semibold text-canvas disabled:opacity-40">
                {candidateReviewing ? "Saving…" : "Add to current memory"}
              </button>
              {(candidate.allowed_actions || []).includes("supersede") ? (
                <button type="button" disabled={candidateReviewing} onClick={() => onReview(candidate, "supersede")} className="min-h-10 rounded-control border border-line px-3 text-xs font-semibold text-ink disabled:opacity-40">
                  Not current
                </button>
              ) : null}
              {(candidate.allowed_actions || []).includes("dismiss") ? (
                <button type="button" disabled={candidateReviewing} onClick={() => onReview(candidate, "dismiss")} className="min-h-10 rounded-control px-3 text-xs font-semibold text-ink-muted hover:bg-surface-muted disabled:opacity-40">
                  Not project memory
                </button>
              ) : null}
              <button type="button" disabled={candidateReviewing} onClick={() => onSkip(candidate)} className="min-h-10 rounded-control px-3 text-xs font-semibold text-ink-subtle hover:bg-surface-muted disabled:opacity-40">
                Skip for now
              </button>
            </div>
          </aside>
        </article>
      ) : shownRemaining === 0 && remaining > 0 ? (
        <div className="px-6 py-14 text-center">
          <Clock3 className="mx-auto h-6 w-6 text-ink-subtle" aria-hidden="true" />
          <p className="mt-3 text-sm font-semibold text-ink">Every visible candidate was skipped</p>
          <p className="mx-auto mt-2 max-w-lg text-xs leading-5 text-ink-muted">Nothing changed. Revisit the skipped candidates whenever you are ready.</p>
          <button type="button" onClick={onResetSkipped} className="btn-secondary mt-4 min-h-11 text-xs">Review skipped candidates</button>
        </div>
      ) : conflictCount > 0 ? (
        <div className="px-6 py-10 text-center">
          <GitMerge className="mx-auto h-7 w-7 text-attention" aria-hidden="true" />
          <p className="mt-3 text-base font-semibold text-ink">Conflicts still need a decision</p>
          <p className="mx-auto mt-2 max-w-xl text-xs leading-5 text-ink-muted">
            There are no ordinary claims ready to add. Compare the conflicting records below and rule out the version that should not remain current.
          </p>
        </div>
      ) : evidenceGapCount > 0 ? (
        <div className="px-6 py-10 text-center">
          <HelpCircle className="mx-auto h-7 w-7 text-attention" aria-hidden="true" />
          <p className="mt-3 text-base font-semibold text-ink">Some records lack exact evidence</p>
          <p className="mx-auto mt-2 max-w-xl text-xs leading-5 text-ink-muted">
            They cannot become Current. Inspect the records below and dismiss or supersede them, or improve the source extraction first.
          </p>
        </div>
      ) : (
        <div className="px-6 py-14 text-center">
          <CheckCheck className="mx-auto h-7 w-7 text-emerald-700 dark:text-emerald-300" aria-hidden="true" />
          <p className="mt-3 text-base font-semibold text-ink">Review queue clear</p>
          <p className="mx-auto mt-2 max-w-xl text-xs leading-5 text-ink-muted">
            Every reviewable claim in this scope is now current, dismissed, superseded, or outside the active filters.
          </p>
        </div>
      )}
      {conflictRecords.length > 0 ? (
        <div className="border-t border-line px-5 py-5 sm:px-6">
          <h3 className="text-sm font-semibold text-ink">Conflicts need comparison</h3>
          <p className="mt-1 text-xs leading-5 text-ink-muted">A matching quote cannot resolve a disagreement. Compare the competing claims and rule out the one that should not remain current.</p>
          <div className="mt-4 overflow-hidden rounded-control border border-line">
            {conflictRecords.map((item) => (
              <MemoryRecord
                key={item.id}
                item={item}
                reviewing={reviewingId === item.component_id}
                onReview={onReview}
              />
            ))}
          </div>
        </div>
      ) : null}
      {evidenceGapRecords.length > 0 ? (
        <div className="border-t border-line px-5 py-5 sm:px-6">
          <h3 className="text-sm font-semibold text-ink">Evidence gaps cannot be verified here</h3>
          <p className="mt-1 text-xs leading-5 text-ink-muted">
            Without an exact source span, Context Engine cannot prove what text produced the claim and will never offer “Add to current memory.”
          </p>
          <div className="mt-4 overflow-hidden rounded-control border border-line">
            {evidenceGapRecords.map((item) => (
              <MemoryRecord
                key={item.id}
                item={item}
                reviewing={reviewingId === item.component_id}
                onReview={onReview}
              />
            ))}
          </div>
        </div>
      ) : null}
      {hasMore ? (
        <div className="border-t border-line px-5 py-3 text-right sm:px-6">
          <button type="button" onClick={onLoadMore} className="btn-secondary min-h-10 text-xs">
            Load more review records
          </button>
        </div>
      ) : null}
      {(refreshCount > 0 || conflictCount > 0) ? (
        <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-line px-5 py-3 text-xs text-ink-muted sm:px-6">
          <span>{conflictCount ? `${conflictCount} conflicts require comparison. ` : ""}{refreshCount ? `${refreshCount} provider snapshots need a source refresh.` : ""}</span>
          {refreshCount > 0 ? <button type="button" onClick={onOpenSourceHealth} className="font-semibold text-ink underline-offset-4 hover:underline">Open source health</button> : null}
        </footer>
      ) : null}
    </section>
  );
}


function ScopeButton({ active, label, detail, onClick }) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={`min-h-12 rounded-control border px-3 py-2 text-left transition ${
        active
          ? "border-ink bg-ink text-canvas"
          : "border-line bg-surface text-ink hover:border-line-strong"
      }`}
    >
      <span className="block text-xs font-semibold">{label}</span>
      <span className={`mt-0.5 block text-[11px] ${active ? "text-canvas/65" : "text-ink-muted"}`}>{detail}</span>
    </button>
  );
}


function FilterSelect({ label, value, options, onChange, disabled = false }) {
  return (
    <label className="block">
      <span className="text-[11px] font-semibold text-ink-muted">{label}</span>
      <select
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
        className="mt-1.5 h-11 w-full rounded-control border border-line bg-surface-raised px-3 text-sm font-medium text-ink outline-none transition hover:border-line-strong disabled:cursor-not-allowed disabled:opacity-50"
      >
        {options.map((option) => <option key={option.id || "__all__"} value={option.id}>{option.label}</option>)}
      </select>
    </label>
  );
}


function MemoryTypeCard({
  type,
  count,
  items,
  index,
  loading,
  selected,
  reviewCount = 0,
  countLabel = "records",
  emptyLabel = "No records in this scope",
  onSelect,
}) {
  const meta = AREA_META[type.area];
  const Icon = type.icon;
  const kinds = [...new Set(items.map((item) => item.kind).filter(Boolean))].slice(0, 3);
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-label={`Filter by ${type.title}`}
      aria-pressed={selected}
      className={`memory-card-enter group relative min-h-48 overflow-hidden rounded-surface border p-4 text-left shadow-elevation-1 transition hover:-translate-y-0.5 hover:shadow-elevation-2 ${
        selected ? "border-ink bg-ink text-canvas" : "border-line bg-surface text-ink"
      }`}
      style={{
        "--memory-accent": meta.accent,
        animationDelay: `${Math.min(index, 12) * 20}ms`,
      }}
    >
      <span aria-hidden="true" className="absolute inset-x-0 top-0 h-1" style={{ backgroundColor: selected ? "var(--ce-color-accent)" : meta.accent }} />
      <span className="flex items-start justify-between gap-4">
        <span className={`flex h-10 w-10 items-center justify-center rounded-control border ${selected ? "border-canvas/20 bg-canvas/10" : "border-line bg-surface-raised"}`} style={{ color: selected ? "var(--ce-color-accent)" : meta.accent }}>
          <Icon className="h-[18px] w-[18px]" strokeWidth={1.8} aria-hidden="true" />
        </span>
        <span className="text-right">
          <span className="block text-2xl font-semibold tabular-nums tracking-[-0.04em]">{loading ? "—" : count}</span>
          <span className={`block text-[11px] font-medium ${selected ? "text-canvas/60" : "text-ink-subtle"}`}>
            {countLabel === "records" ? (count === 1 ? "record" : "records") : countLabel}
          </span>
        </span>
      </span>
      <span className="mt-5 block text-base font-semibold tracking-[-0.02em]">{type.title}</span>
      <span className={`mt-1.5 block text-xs leading-5 ${selected ? "text-canvas/70" : "text-ink-muted"}`}>{type.description}</span>
      {reviewCount > 0 ? (
        <span className={`mt-3 inline-flex rounded-full px-2 py-1 text-[10px] font-semibold ${
          selected ? "bg-attention/20 text-canvas" : "bg-attention/10 text-attention"
        }`}>
          {reviewCount.toLocaleString()} awaiting review
        </span>
      ) : null}
      <span className="mt-4 flex min-h-6 flex-wrap gap-1.5">
        {kinds.length ? (
          kinds.map((itemKind) => (
            <span key={itemKind} className={`rounded-full px-2 py-1 text-[10px] font-medium ${selected ? "bg-canvas/10 text-canvas/75" : "bg-surface-muted text-ink-muted"}`}>{itemKind}</span>
          ))
        ) : (
          <span className={`text-[11px] ${selected ? "text-canvas/55" : "text-ink-subtle"}`}>{count ? "Apply filters to inspect records" : emptyLabel}</span>
        )}
      </span>
    </button>
  );
}


function RecordPreview({ item, type, index, onOpen }) {
  const truth = getTruthPresentation(item);
  const TruthIcon = truth.Icon;
  const Icon = type.icon;
  const meta = AREA_META[type.area];
  const source = item.source || {};
  return (
    <article
      className="memory-card-enter group relative border-b border-line p-5 last:border-b-0 lg:min-h-64 lg:border-r lg:[&:nth-child(even)]:border-r-0"
      style={{ animationDelay: `${Math.min(index, 12) * 20}ms` }}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2.5">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-control bg-surface-muted" style={{ color: meta.accent }}>
            <Icon className="h-4 w-4" aria-hidden="true" />
          </span>
          <div className="min-w-0">
            <p className="text-[11px] font-semibold text-ink-subtle">{type.title}</p>
            <p className="truncate text-xs font-medium text-ink-muted">{item.kind}</p>
          </div>
        </div>
        <span className={`inline-flex shrink-0 items-center gap-1.5 rounded-full border px-2 py-1 text-[10px] font-semibold ${truth.className}`}>
          <TruthIcon className="h-3 w-3" aria-hidden="true" />
          {truth.label}
        </span>
      </div>
      <h3 className="mt-4 text-[15px] font-semibold leading-6 tracking-[-0.015em] text-ink">{cleanDisplayText(item.title)}</h3>
      {item.summary && cleanDisplayText(item.summary) !== cleanDisplayText(item.title) ? (
        <p className="mt-1.5 line-clamp-2 text-xs leading-5 text-ink-muted">{cleanDisplayText(item.summary)}</p>
      ) : null}
      <div className="mt-4 rounded-control bg-surface-raised px-3 py-2.5">
        <p className="text-[11px] font-semibold text-ink">Why this is shown</p>
        <p className="mt-1 text-[11px] leading-4 text-ink-muted">{item.relevance || item.explanation}</p>
      </div>
      <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
        <span className="inline-flex min-w-0 items-center gap-1.5 text-[11px] text-ink-muted">
          <Link2 className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
          <span className="truncate">{source.label || "Workspace record"}</span>
        </span>
        <button
          type="button"
          aria-label={`Inspect evidence for ${cleanDisplayText(item.title)}`}
          onClick={onOpen}
          className="inline-flex min-h-10 items-center gap-1.5 rounded-control px-3 text-xs font-semibold text-ink hover:bg-surface-muted"
        >
          Inspect evidence
          <ArrowRight className="h-3.5 w-3.5 transition-transform group-hover:translate-x-0.5" aria-hidden="true" />
        </button>
      </div>
    </article>
  );
}


function scopeExplanation({ scopeMode, effectiveScope, agenda, workspaceName }) {
  if (scopeMode === "workspace") {
    return `Showing every trusted record assigned to ${workspaceName}.`;
  }
  if (!agenda || effectiveScope === "workspace") {
    return `No current agenda is selected, so Memory is safely showing the full ${workspaceName} workspace.`;
  }
  if (agenda.match_mode === "selected_source") {
    return "Showing memory from the task session selected in Library. Unverified session claims remain in the Review queue.";
  }
  if (agenda.match_mode === "linked_component") {
    return "Showing the selected goal, records linked to it, and records backed by the same source.";
  }
  return "Showing records with explicit text matches to the selected goal. This is a transparent relevance match, not an inferred fact.";
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
  hasSelectedSession,
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
              hasSelectedSession={hasSelectedSession}
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


function GoalEditor({
  currentGoal,
  saving,
  onSave,
  onClear,
  hasSelectedSession,
}) {
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
          : "This scopes Current Memory and is also shown in Now. It does not start work, edit files, or change an agent brief by itself."}
      </p>
      <div className="mt-2.5 flex items-center justify-between gap-3">
        {onClear ? <button type="button" disabled={saving} onClick={() => setConfirmingClear(true)} className="text-[10px] font-semibold text-[#7a5750] underline-offset-4 hover:underline disabled:opacity-40 dark:text-[#d6a69b]">Clear goal</button> : <span />}
        <button type="submit" disabled={locked || saving || title.trim().length < 3 || title.trim() === currentTitle} className="rounded-md bg-[#171713] px-3 py-2 text-[10px] font-semibold text-white transition-opacity disabled:opacity-35 dark:bg-[#d9ff68] dark:text-[#11110f]">{saving ? "Saving…" : currentTitle ? "Update goal" : "Set goal"}</button>
      </div>
      {confirmingClear ? (
        <div role="group" aria-label="Confirm clear current goal" className="mt-4 border-l-2 border-[#9a5e38] bg-[#9a5e38]/[0.06] px-3 py-3">
          <p className="text-[10px] font-semibold text-[#633c25] dark:text-[#e4ab85]">Clear the current project goal?</p>
          <p className="mt-1 text-[10px] leading-4 text-[#68685f] dark:text-[#aaa9a0]">
            {hasSelectedSession
              ? "This removes the goal from Memory and Now. Current Memory will then follow the session selected in Library. It does not delete history or change project files."
              : "This removes the focus from Memory and Now, returning Memory to the full workspace. It does not delete history or change project files."}
          </p>
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
  if (status.includes("deprecated")) {
    return { label: "Deprecated", Icon: Archive, className: "border-[#c9c9c0] text-[#5f5f57] dark:border-[#393934] dark:text-[#bdbdb4]" };
  }
  if (status.includes("stale")) {
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
  if (status.includes("reported") || verification.includes("reported")) {
    return { label: "Reported activity", Icon: History, className: "border-[#c9c9c0] text-[#5f5f57] dark:border-[#393934] dark:text-[#bdbdb4]" };
  }
  if (verification.includes("unavailable")) {
    return { label: "No exact evidence", Icon: HelpCircle, className: "border-amber-300 text-amber-800 dark:border-amber-900 dark:text-amber-200" };
  }
  if (
    status.includes("proposed")
    ||
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
  const resolution = item.resolution || null;
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
      {resolution ? (
        <div className="mt-3 rounded-control border border-emerald-200 bg-emerald-50/60 px-3 py-3 text-[10px] dark:border-emerald-950 dark:bg-emerald-950/20">
          <p className="font-semibold text-emerald-900 dark:text-emerald-200">
            Evidence that cleared this blocker
          </p>
          <p className="mt-1 leading-4 text-emerald-950/75 dark:text-emerald-100/75">
            {cleanDisplayText(resolution.summary)}
          </p>
          {resolution.source?.url ? (
            <a
              href={resolution.source.url}
              target="_blank"
              rel="noreferrer"
              className="mt-2 inline-flex items-center gap-1 font-semibold text-emerald-800 underline-offset-4 hover:underline dark:text-emerald-300"
            >
              <Link2 className="h-3 w-3" aria-hidden="true" />
              {resolution.source.label}
            </a>
          ) : resolution.source?.label ? (
            <p className="mt-2 inline-flex items-center gap-1 font-semibold text-emerald-800 dark:text-emerald-300">
              <Link2 className="h-3 w-3" aria-hidden="true" />
              {resolution.source.label}
            </p>
          ) : null}
          {resolution.evidence?.excerpt ? (
            <blockquote className="mt-2 border-l-2 border-emerald-300 pl-2 leading-4 text-emerald-950/70 dark:border-emerald-800 dark:text-emerald-100/70">
              “{cleanDisplayText(resolution.evidence.excerpt)}”
              <span className="mt-1 block text-[9px]">
                {resolution.evidence.exact ? "Exact resolution source span" : "Captured resolution evidence"}
              </span>
            </blockquote>
          ) : null}
        </div>
      ) : null}
      {item.last_review ? (
        <p className="mt-2 text-[9px] text-[#8a8a80]">Last review: {item.last_review.action.replaceAll("_", " ")} by {item.last_review.reviewed_by}{item.last_review.reason ? ` — ${item.last_review.reason}` : ""}</p>
      ) : null}
      {item.component_id && actions.size ? (
        <div className="mt-3 border-t border-[#e5e5dd] pt-3 text-[10px] font-semibold dark:border-[#292925]">
          {actions.has("confirm") ? (
            <p className="mb-3 font-normal leading-4 text-[#68685f] dark:text-[#aaa9a0]">
              Exact evidence proves the source, not the truth. Add this only if the claim is correct and current.
            </p>
          ) : null}
          <div className="flex flex-wrap gap-x-3 gap-y-2">
            {actions.has("reopen") ? <button type="button" disabled={reviewing} onClick={() => onReview(item, "reopen")} className="text-[#4f4f48] underline-offset-4 hover:underline disabled:opacity-40 dark:text-[#d0d0c8]">Reopen</button> : null}
            {actions.has("confirm") ? <button type="button" disabled={reviewing} onClick={() => onReview(item, "confirm")} className="text-emerald-700 underline-offset-4 hover:underline disabled:opacity-40 dark:text-emerald-300">Add to current memory</button> : null}
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
