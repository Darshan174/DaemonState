import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  Activity,
  AlertTriangle,
  Archive,
  ArrowRight,
  Calendar,
  CheckCheck,
  CheckCircle2,
  ClipboardCheck,
  Clock3,
  FileDiff,
  Files,
  Fingerprint,
  GitBranch,
  GitMerge,
  GitPullRequest,
  GraduationCap,
  HelpCircle,
  History,
  Lightbulb,
  Link2,
  ListTodo,
  Rocket,
  Route,
  Search,
  Shield,
  ShieldAlert,
  Target,
  TestTube2,
  Trophy,
  UserRound,
  X,
  XCircle,
} from "lucide-react";

import { useLatestCheckpoint } from "../api/hooks";
import WorkspaceTopicGate from "../components/WorkspaceTopicGate";
import { useContextDigest } from "../context-map/api";
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

const MEMORY_TYPES = [
  { id: "goals", area: "direction", title: "Current goal", description: "The explicit outcome currently selected as the workspace focus.", capture: "Explicitly selected workspace goals only", icon: Target },
  { id: "requirements", area: "direction", title: "Requirements", description: "Must-have behavior and acceptance criteria.", capture: "Explicit requirements in sessions and source documents", icon: ClipboardCheck },
  { id: "decisions", area: "direction", title: "Decisions", description: "Chosen direction, rationale, and the choices it replaces.", capture: "Verified decision facts and checkpoints", icon: CheckCircle2 },
  { id: "assumptions", area: "direction", title: "Assumptions", description: "Beliefs the work depends on but has not fully proven.", capture: "Explicit assumption language in project evidence", icon: Lightbulb },
  { id: "constraints", area: "direction", title: "Constraints", description: "Non-negotiable limits that shape implementation.", capture: "Constraints and non-negotiable source statements", icon: Shield },

  { id: "tasks", area: "execution", title: "Tasks", description: "Concrete units of work that are ready to be acted on.", capture: "Extracted tasks and action items", icon: ListTodo },
  { id: "progress", area: "execution", title: "Progress", description: "What has moved forward since the previous boundary.", capture: "Structured checkpoint progress", icon: Activity },
  { id: "blockers", area: "execution", title: "Blockers", description: "Problems that prevent the current work from continuing.", capture: "Active blocker facts and checkpoint blockers", icon: ShieldAlert },
  { id: "dependencies", area: "execution", title: "Dependencies", description: "Work, systems, or decisions that another item relies on.", capture: "Evidence-backed dependency and blocking links", icon: GitBranch },
  { id: "next_actions", area: "execution", title: "Next actions", description: "The exact action that should happen immediately next.", capture: "Checkpoint continuation and recommended actions", icon: ArrowRight },

  { id: "risks", area: "uncertainty", title: "Risks", description: "Potential problems that may affect delivery or quality.", capture: "Risk facts extracted from current evidence", icon: AlertTriangle },
  { id: "open_questions", area: "uncertainty", title: "Open questions", description: "Unanswered questions that require evidence or a decision.", capture: "Explicit questions and unresolved concerns", icon: HelpCircle },
  { id: "conflicts", area: "uncertainty", title: "Conflicts", description: "Claims or directions that disagree with each other.", capture: "Conflict statuses and contradiction links", icon: GitMerge },
  { id: "stale_context", area: "uncertainty", title: "Stale context", description: "Information that may no longer describe the project.", capture: "Stale facts and stale provider snapshots", icon: Clock3 },

  { id: "failed_attempts", area: "learning", title: "Failed attempts", description: "Approaches that were tried and did not work.", capture: "Structured checkpoint failures", icon: XCircle },
  { id: "lessons", area: "learning", title: "Lessons", description: "Reusable insights learned while doing the work.", capture: "Explicit lessons, insights, and takeaways", icon: GraduationCap },
  { id: "alternatives", area: "learning", title: "Alternatives", description: "Other approaches considered before choosing a path.", capture: "Alternative and option language in project evidence", icon: Route },

  { id: "changes", area: "delivery", title: "Changes", description: "The implementation changes made to the project.", capture: "Changed-file facts and run outcomes", icon: FileDiff },
  { id: "files", area: "delivery", title: "Relevant files", description: "Files and code areas that matter to the current work.", capture: "Repository indexing and checkpoint file references", icon: Files },
  { id: "commits_prs", area: "delivery", title: "Commits & PRs", description: "Reviewable delivery units linked to the work.", capture: "GitHub pull requests and commit references", icon: GitPullRequest },
  { id: "releases", area: "delivery", title: "Releases", description: "Launches and deployments that move work to users.", capture: "Explicit release, launch, and deployment evidence", icon: Rocket },

  { id: "tests", area: "proof", title: "Tests & checks", description: "Commands and checks used to verify the work.", capture: "Checkpoint verification and test evidence", icon: TestTube2 },
  { id: "outcomes", area: "proof", title: "Outcomes", description: "The factual result produced by a run or delivery.", capture: "Completion and outcome statements", icon: Trophy },
  { id: "evidence", area: "proof", title: "Evidence", description: "The exact source material supporting every tracked claim.", capture: "Source provenance, excerpts, and revisions", icon: Fingerprint },

  { id: "owners", area: "ownership", title: "Owners", description: "People responsible for moving an item forward.", capture: "Assignment and ownership links", icon: UserRound },
  { id: "milestones", area: "ownership", title: "Milestones", description: "Important target dates, deadlines, and delivery boundaries.", capture: "Explicit milestone and deadline evidence", icon: Calendar },

  { id: "version_history", area: "history", title: "Version history", description: "How source-backed project memory changed over time.", capture: "Source revisions and checkpoint boundaries", icon: History },
  { id: "superseded", area: "history", title: "Superseded items", description: "Old directions preserved without treating them as current truth.", capture: "Superseded facts and decisions", icon: Archive },
  { id: "resolved_blockers", area: "history", title: "Resolved blockers", description: "Past obstacles and the evidence that cleared them.", capture: "Resolved blocker facts and resolution history", icon: CheckCheck },
];

const FILTERS = [
  { id: "all", label: "All" },
  ...Object.entries(AREA_META).map(([id, value]) => ({ id, label: value.label })),
];


export default function ProjectMemory() {
  const workspace = useProductWorkspace();
  const digestQuery = useContextDigest(workspace.activeWorkspaceId);
  const checkpointQuery = useLatestCheckpoint(workspace.activeWorkspaceId);
  const [area, setArea] = useState("all");
  const [search, setSearch] = useState("");
  const [selectedType, setSelectedType] = useState(null);

  const itemsByType = useMemo(
    () => buildItemsByType(digestQuery.data || {}, checkpointQuery.data),
    [digestQuery.data, checkpointQuery.data],
  );
  const visibleTypes = useMemo(() => {
    const query = search.trim().toLowerCase();
    return MEMORY_TYPES.filter((type) => {
      if (area !== "all" && type.area !== area) return false;
      if (!query) return true;
      return `${type.title} ${type.description} ${AREA_META[type.area].label}`.toLowerCase().includes(query);
    });
  }, [area, search]);
  const visibleGroups = useMemo(() => Object.entries(AREA_META)
    .map(([id, meta]) => ({
      id,
      ...meta,
      types: visibleTypes.filter((type) => type.area === id),
    }))
    .filter((group) => group.types.length), [visibleTypes]);
  const observedTypeCount = MEMORY_TYPES.filter((type) => (itemsByType[type.id] || []).length > 0).length;
  const observedRecordCount = MEMORY_TYPES.reduce((total, type) => total + (itemsByType[type.id] || []).length, 0);

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
              The durable facts, choices, work, and evidence behind this project.
            </p>
          </div>
          <dl className="grid w-full grid-cols-3 divide-x divide-[#d8d8cf] border-y border-[#d8d8cf] py-3 dark:divide-[#30302c] dark:border-[#30302c] sm:w-auto sm:min-w-[420px]">
            <MemoryStat value={MEMORY_TYPES.length} label="Types" />
            <MemoryStat value={observedTypeCount} label="Active types" />
            <MemoryStat value={observedRecordCount} label="Records" />
          </dl>
        </div>
      </header>

      <div className="mt-5 flex flex-col gap-4 border-b border-[#d8d8cf] dark:border-[#252522] lg:flex-row lg:items-center lg:justify-between">
        <nav aria-label="Memory type filters" className="no-scrollbar flex min-w-0 gap-6 overflow-x-auto">
          {FILTERS.map((filter) => (
            <button
              type="button"
              key={filter.id}
              aria-pressed={area === filter.id}
              onClick={() => setArea(filter.id)}
              className={`relative shrink-0 pb-3 text-[11px] font-semibold transition-colors duration-200 ${
                area === filter.id
                  ? "text-[#171713] dark:text-white"
                  : "text-[#85857c] hover:text-[#363630] dark:hover:text-[#d8d8cf]"
              }`}
            >
              {filter.label}
              {area === filter.id ? <span className="absolute inset-x-0 -bottom-px h-0.5 bg-[#171713] dark:bg-[#d9ff68]" /> : null}
            </button>
          ))}
        </nav>
        <div className="relative mb-3 w-full shrink-0 lg:w-64">
          <Search className="pointer-events-none absolute left-0 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[#85857c]" />
          <input
            type="search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            aria-label="Search memory types"
            placeholder="Search memory"
            className="h-9 w-full border-0 border-b border-[#cfcfc5] bg-transparent pl-6 pr-1 text-xs font-medium text-[#171713] outline-none transition-colors placeholder:text-[#9b9b92] focus:border-[#171713] focus:ring-0 dark:border-[#393934] dark:text-white dark:focus:border-[#d9ff68]"
          />
        </div>
      </div>

      {digestQuery.isError ? (
        <div role="alert" className="mt-6 border-y border-amber-300 py-3 text-xs font-medium text-amber-900 dark:border-amber-900/70 dark:text-amber-200">
          Live project records could not be loaded. The memory catalogue is still available.
        </div>
      ) : null}

      <section aria-label="Project memory types" className="mt-9">
        {visibleGroups.length ? (
          <div className="space-y-12">
            {visibleGroups.map((group, groupIndex) => (
              <section key={group.id} aria-labelledby={`memory-group-${group.id}`}>
                <div className="mb-4 flex items-center gap-4">
                  <div>
                    <p className="text-[10px] font-medium tabular-nums text-[#9a9a91]">{String(groupIndex + 1).padStart(2, "0")}</p>
                    <h2 id={`memory-group-${group.id}`} className="mt-0.5 text-base font-semibold tracking-[-0.02em]">{group.label}</h2>
                  </div>
                  <span className="h-px flex-1 bg-[#dfdfd7] dark:bg-[#252522]" />
                  <span className="text-[10px] font-medium text-[#8a8a80]">{group.types.length} {group.types.length === 1 ? "type" : "types"}</span>
                </div>
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                  {group.types.map((type, index) => (
                    <MemoryTypeCard
                      key={type.id}
                      type={type}
                    index={index}
                      loading={digestQuery.isLoading || checkpointQuery.isLoading}
                      items={itemsByType[type.id] || []}
                      onOpen={() => setSelectedType(type)}
                    />
                  ))}
                </div>
              </section>
            ))}
          </div>
        ) : (
          <div className="border-y border-[#d8d8cf] py-16 text-center dark:border-[#30302b]">
            <p className="text-sm font-semibold">No matching memory type</p>
            <button type="button" onClick={() => { setSearch(""); setArea("all"); }} className="mt-3 text-xs font-semibold text-[#686d35] dark:text-[#d9ff68]">Clear filters</button>
          </div>
        )}
      </section>

      {selectedType ? createPortal(
        <MemoryDrawer
          type={selectedType}
          items={itemsByType[selectedType.id] || []}
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


function MemoryTypeCard({ type, items, index, loading, onOpen }) {
  const meta = AREA_META[type.area];
  const count = items.length;
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


function MemoryGlyph({ type, accent, soft, index }) {
  const Icon = type.icon;
  const layout = index % 4;
  return (
    <span aria-hidden="true" className="relative my-2.5 block min-h-0 flex-1 overflow-hidden rounded-[12px] border border-[#e1e1d9] bg-[#f4f4ee] dark:border-[#252521] dark:bg-[#151512] sm:my-3.5">
      {layout === 0 ? (
        <>
          <span className="absolute left-[18%] right-[18%] top-1/2 h-px bg-[#d4d4cc] dark:bg-[#33332e]" />
          <span className="absolute left-[17%] top-1/2 h-2 w-2 -translate-y-1/2 rounded-full border-2 border-current bg-[#f4f4ee] transition-transform duration-300 group-hover:scale-125 dark:bg-[#151512]" style={{ color: accent }} />
          <span className="absolute right-[17%] top-1/2 h-2 w-2 -translate-y-1/2 rounded-full border-2 border-current bg-[#f4f4ee] transition-transform duration-300 group-hover:scale-125 dark:bg-[#151512]" style={{ color: accent }} />
        </>
      ) : null}
      {layout === 1 ? (
        <>
          <span className="absolute left-[22%] top-[24%] h-[52%] w-px bg-[#d4d4cc] dark:bg-[#33332e]" />
          <span className="absolute right-[22%] top-[24%] h-[52%] w-px bg-[#d4d4cc] dark:bg-[#33332e]" />
          <span className="absolute left-[20.5%] top-[20%] h-2 w-2 rounded-full" style={{ backgroundColor: accent }} />
          <span className="absolute right-[20.5%] bottom-[20%] h-2 w-2 rounded-full" style={{ backgroundColor: accent }} />
        </>
      ) : null}
      {layout === 2 ? (
        <>
          <span className="absolute left-[16%] right-[16%] top-[31%] h-px -rotate-6 bg-[#d4d4cc] dark:bg-[#33332e]" />
          <span className="absolute bottom-[31%] left-[16%] right-[16%] h-px rotate-6 bg-[#d4d4cc] dark:bg-[#33332e]" />
          <span className="absolute left-[16%] top-[26%] h-1.5 w-1.5 rounded-full" style={{ backgroundColor: accent }} />
          <span className="absolute bottom-[26%] left-[16%] h-1.5 w-1.5 rounded-full" style={{ backgroundColor: accent }} />
        </>
      ) : null}
      {layout === 3 ? (
        <>
          <span className="absolute inset-[21%] rounded-full border border-dashed border-[#c9c9c0] transition-transform duration-500 group-hover:rotate-45 dark:border-[#3b3b35]" />
          <span className="absolute right-[20%] top-1/2 h-2 w-2 -translate-y-1/2 rounded-full" style={{ backgroundColor: accent }} />
        </>
      ) : null}
      <span className="absolute left-1/2 top-1/2 flex h-11 w-11 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-[11px] border shadow-[0_3px_10px_rgba(23,23,19,0.06)] transition-transform duration-300 group-hover:scale-105" style={{ borderColor: accent, color: accent, backgroundColor: soft }}>
        <Icon className="h-5 w-5" strokeWidth={1.8} />
      </span>
    </span>
  );
}


function MemoryDrawer({ type, items, onClose }) {
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
            <h3 className="text-xs font-semibold text-[#4f4f48] dark:text-[#d0d0c8]">Observed records</h3>
            <span className="font-mono text-[10px] tabular-nums text-[#8a8a80]">{String(items.length).padStart(2, "0")}</span>
          </div>
          {items.length ? (
            <div className="overflow-hidden rounded-[12px] border border-[#d8d8cf] bg-[#fbfbf6] dark:border-[#292925] dark:bg-[#11110f]">
              {items.map((item) => <MemoryRecord key={item.id} item={item} accent={meta.accent} />)}
            </div>
          ) : (
            <div className="border-y border-[#d1d1c7] px-6 py-12 text-center dark:border-[#30302b]">
              <Icon className="mx-auto h-6 w-6 opacity-50" strokeWidth={1.7} style={{ color: meta.accent }} />
              <p className="mt-4 text-sm font-semibold">Nothing observed yet</p>
              <p className="mx-auto mt-2 max-w-sm text-[11px] leading-5 text-[#68685f] dark:text-[#aaa9a0]">{type.id === "goals" ? "No current project goal is explicitly selected. Session tasks and checkpoint instructions are kept out of this tracker." : "When this information appears in a connected source, Context Engine can place it here with its evidence attached."}</p>
            </div>
          )}
        </div>
      </aside>
    </div>
  );
}


function MemoryRecord({ item, accent }) {
  return (
    <article className="group border-b border-[#e1e1d9] p-4 last:border-b-0 dark:border-[#292925]">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h4 className="text-[13px] font-semibold leading-5">{cleanDisplayText(item.title)}</h4>
          {item.summary && cleanDisplayText(item.summary) !== cleanDisplayText(item.title) ? <p className="mt-1.5 text-[11px] leading-5 text-[#68685f] dark:text-[#aaa9a0]">{cleanDisplayText(item.summary)}</p> : null}
        </div>
        <span className="flex shrink-0 items-center gap-1.5 text-[9px] font-medium text-[#68685f] dark:text-[#aaa9a0]"><span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: accent }} />{String(item.status || "observed").replaceAll("_", " ")}</span>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-[9px] font-medium text-[#8a8a80]">
        {item.source ? <span className="inline-flex items-center gap-1"><Link2 className="h-3 w-3" />{item.source}</span> : null}
        {item.updatedAt ? <span>{formatTimeAgo(item.updatedAt)}</span> : null}
      </div>
    </article>
  );
}


function buildItemsByType(digest, checkpoint) {
  const cards = (digest.cards || [])
    .filter((card) => card.workspace_relevance?.status !== "not_relevant")
    .map(cardRecord);
  const links = digest.links || [];
  const cardsById = new Map(cards.map((card) => [card.cardId, card]));
  const checkpointItems = (category) => (checkpoint?.sections?.[category] || []).map((item) => ({
    id: `checkpoint:${category}:${item.id || item.item_key}`,
    title: item.statement,
    summary: item.statement,
    status: item.truth_state || item.state || "observed",
    source: "Latest checkpoint",
    updatedAt: checkpoint?.created_at,
  }));
  const matching = (pattern) => cards.filter((card) => pattern.test(card.searchText));
  const category = (value) => cards.filter((card) => card.category === value);
  const linkRecords = (types) => links
    .filter((link) => types.includes(link.relationship_type))
    .map((link) => {
      const source = cardsById.get(link.source_card_id);
      const target = cardsById.get(link.target_card_id);
      return {
        id: link.id,
        title: [source?.title, readableRelationship(link.relationship_type), target?.title].filter(Boolean).join(" "),
        summary: link.evidence,
        status: link.status || "observed",
        source: "Relationship evidence",
      };
    });

  const currentGoal = digest.current_goal?.title ? [{
    id: `goal:${digest.current_goal.component_id || digest.current_goal.title}`,
    title: digest.current_goal.title,
    summary: digest.current_goal.summary || "Current workspace focus",
    status: "active",
    source: "Current goal",
    updatedAt: digest.current_goal.updated_at,
  }] : [];
  const recommendedActions = (digest.recommended_actions || []).map((action) => ({
    id: `action:${action.id}`,
    title: action.title,
    summary: action.summary,
    status: "recommended",
    source: "Project digest",
  }));
  const evidence = uniqueItems(cards.map((card) => ({
    id: `evidence:${card.sourceDocumentId || card.id}`,
    title: card.source || "Project source",
    summary: card.excerpt || card.summary,
    status: card.verificationStatus || "observed",
    source: card.sourceType || "Source evidence",
    updatedAt: card.updatedAt,
  })));

  return {
    goals: uniqueItems(currentGoal),
    requirements: uniqueItems(matching(/\brequirement\b|acceptance criteria|must[- ]have/i)),
    decisions: uniqueItems([...category("decision"), ...checkpointItems("decisions")]),
    assumptions: uniqueItems(matching(/\bassum(?:e|ed|ption|ptions)\b/i)),
    constraints: uniqueItems(matching(/\bconstraint\b|non[- ]negotiable|must not|cannot change/i)),
    tasks: uniqueItems([
      ...category("task"),
      ...category("issue"),
      ...checkpointItems("goal").map((item) => ({ ...item, source: "Latest checkpoint task" })),
    ]),
    progress: uniqueItems(checkpointItems("progress")),
    blockers: uniqueItems([...category("blocker").filter((item) => item.status !== "resolved"), ...checkpointItems("blockers")]),
    dependencies: uniqueItems(linkRecords(["depends_on", "blocked_by", "blocks"])),
    next_actions: uniqueItems([...checkpointItems("exact_next_action"), ...recommendedActions]),
    risks: uniqueItems(cards.filter((card) => card.type === "risk" || /(?:^|\b)risk\s*:/i.test(card.searchText))),
    open_questions: uniqueItems(matching(/open question|unanswered|\bquestion\s*:|\?$/i)),
    conflicts: uniqueItems([...cards.filter((card) => card.status === "conflict"), ...linkRecords(["conflicts_with", "contradicts"])]),
    stale_context: uniqueItems(cards.filter((card) => card.status === "stale" || card.freshness === "stale")),
    failed_attempts: uniqueItems(checkpointItems("failed_attempts")),
    lessons: uniqueItems(matching(/\blesson\b|\blearn(?:ed|ing)\b|\binsight\b|\btakeaway\b/i)),
    alternatives: uniqueItems(matching(/\balternative\b|\boption\b|instead of|other approach/i)),
    changes: uniqueItems(matching(/changed file|\bimplemented\b|\bupdated\b|\bmodified\b|\bpatch\b/i)),
    files: uniqueItems([...category("code_area"), ...cards.filter((card) => card.type === "file"), ...checkpointItems("relevant_files")]),
    commits_prs: uniqueItems([...category("pull_request"), ...matching(/\bcommit\b|pull request|\bpr\s*#?\d+/i)]),
    releases: uniqueItems(matching(/\brelease\b|\bdeploy(?:ed|ment)?\b|\blaunch(?:ed)?\b/i)),
    tests: uniqueItems([...checkpointItems("verification"), ...matching(/\btest(?:ed|s|ing)?\b|\bverification\b|\bcheck(?:ed|s)?\b/i)]),
    outcomes: uniqueItems(matching(/\boutcome\b|\bresult\b|\bcompleted\b|\bshipped\b/i)),
    evidence,
    owners: uniqueItems([...linkRecords(["owned_by", "assigned_to"]), ...matching(/\bowner\b|assigned to|responsible for/i)]),
    milestones: uniqueItems(matching(/\bmilestone\b|\bdeadline\b|\bdue date\b|target date/i)),
    version_history: uniqueItems(cards.filter((card) => Number(card.revisionNumber || 1) > 1 || card.temporal === "past")),
    superseded: uniqueItems(cards.filter((card) => card.status === "superseded")),
    resolved_blockers: uniqueItems(category("blocker").filter((card) => card.status === "resolved")),
  };
}


function cardRecord(card) {
  const provenance = card.provenance?.[0] || {};
  const source = card.source_snapshot || {};
  const title = card.title || card.summary || "Observed project item";
  const summary = card.summary || card.why_it_matters || title;
  return {
    ...card,
    id: card.id,
    cardId: card.id,
    title,
    summary,
    source: provenance.source_label || source.external_id || "Project source",
    sourceType: provenance.source_type || source.source_type,
    sourceDocumentId: source.source_document_id || provenance.source_document_id,
    excerpt: provenance.excerpt || card.evidence?.excerpt,
    verificationStatus: card.evidence?.verification_status,
    revisionNumber: source.revision_number,
    freshness: source.freshness,
    updatedAt: card.updated_at || source.provider_updated_at || source.ingested_at,
    searchText: `${title} ${summary} ${card.type || ""} ${card.category || ""}`,
  };
}


function uniqueItems(items) {
  const seen = new Set();
  return items.filter((item) => {
    const key = item.id || `${item.title}:${item.source}`;
    if (!item.title || seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}


function readableRelationship(value) {
  return String(value || "relates to").replaceAll("_", " ");
}
