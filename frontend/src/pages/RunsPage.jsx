import { useState } from "react";
import { AlertTriangle, CheckCircle2, Clock3, FileCode2, FlaskConical, PlayCircle, XCircle } from "lucide-react";

import WorkspaceTopicGate from "../components/WorkspaceTopicGate";
import { useRunOutcomes } from "../context-map/api";
import { cleanDisplayText, formatTimeAgo } from "../context-map/digest";
import { useProductWorkspace } from "./useProductWorkspace";

export default function RunsPage() {
  const workspace = useProductWorkspace();
  const outcomesQuery = useRunOutcomes(workspace.activeWorkspaceId);
  const [view, setView] = useState("recent");

  if (!workspace.workspacesQuery.isLoading && !workspace.activeWorkspaceId) {
    return <WorkspaceTopicGate workspaces={workspace.workspaces} selectedId={workspace.selectedId} onSelect={workspace.setSelectedId} />;
  }

  const report = outcomesQuery.data;
  const runs = report?.runs || [];
  const groups = report?.groups || [];

  return (
    <div className="relative mx-auto w-full max-w-6xl space-y-6">
      <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-xs font-black uppercase tracking-[0.18em] text-[#85857c]">{workspace.activeWorkspace?.name || "Project"}</p>
          <h1 className="mt-2 text-3xl font-black tracking-tight">Runs</h1>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-[#68685f] dark:text-[#aaa9a0]">Observed agent work, deterministic verification, and honest model-level evidence.</p>
        </div>
        <div className="inline-flex rounded-xl border border-[#d8d8cf] bg-[#fbfbf6] p-1 dark:border-[#292925] dark:bg-[#141411]">
          <ViewButton active={view === "recent"} onClick={() => setView("recent")} icon={PlayCircle}>Recent</ViewButton>
          <ViewButton active={view === "compare"} onClick={() => setView("compare")} icon={FlaskConical}>Compare</ViewButton>
        </div>
      </header>

      {outcomesQuery.isLoading ? <EmptyState title="Loading observed runs…" /> : null}
      {outcomesQuery.isError ? <EmptyState title="Could not load run evidence" detail={outcomesQuery.error?.message} error /> : null}

      {!outcomesQuery.isLoading && !outcomesQuery.isError && view === "recent" ? (
        runs.length ? (
          <div className="space-y-3">
            {runs.map((run) => <RunCard key={run.run_id} run={run} />)}
          </div>
        ) : (
          <EmptyState title="No local harness runs recorded yet" detail="Wrap your existing worker command to capture its model label, repository changes, checks, and terminal outcome.">
            <code className="mt-4 block overflow-x-auto rounded-lg bg-[#171713] px-3 py-2 text-left text-[10px] leading-5 text-[#e8e8e0] dark:bg-[#0b0b09]">ctxe harness run &quot;your task&quot; --repo . --workspace-id {workspace.activeWorkspaceId} --target-model your-model --verify -- your-worker --context {'{context_file}'}</code>
            <p className="mt-2 text-[10px] font-semibold text-[#85857c]">The harness runs only the explicit command after <code>--</code>. It does not choose or launch a provider for you.</p>
          </EmptyState>
        )
      ) : null}

      {!outcomesQuery.isLoading && !outcomesQuery.isError && view === "compare" ? (
        <div className="space-y-5">
          <section className={`rounded-2xl border p-5 ${groups.length >= 2 ? "border-amber-200 bg-amber-50 dark:border-amber-900/60 dark:bg-amber-950/25" : "border-[#d8d8cf] bg-[#fbfbf6] dark:border-[#292925] dark:bg-[#141411]"}`}>
            <div className="flex items-start gap-3">
              <AlertTriangle className={`mt-0.5 h-4 w-4 shrink-0 ${groups.length >= 2 ? "text-amber-600" : "text-[#85857c]"}`} />
              <div>
                <h2 className="text-sm font-black">{groups.length >= 2 ? "Multiple models observed; paired proof is still missing" : "A paired baseline is still missing"}</h2>
                <p className="mt-1.5 text-xs leading-5 text-[#68685f] dark:text-[#aaa9a0]">These are Context Engine-linked runs grouped by their recorded model. To claim model lift, run the same task from the same commit as old alone, old with Context Engine, and new alone.</p>
              </div>
            </div>
          </section>

          {groups.length ? (
            <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {groups.map((group) => <ModelGroup key={`${group.model}:${group.model_profile}`} group={group} />)}
            </section>
          ) : <EmptyState title="No model outcomes to compare" detail="The comparison will appear after locally observed harness runs have deterministic outcomes and verification evidence." />}

          {report?.measurement_note ? <p className="text-[10px] font-semibold leading-5 text-[#85857c]">{report.measurement_note}</p> : null}
        </div>
      ) : null}
    </div>
  );
}

function RunCard({ run }) {
  const state = run.verified_success
    ? { label: "Verified", icon: CheckCircle2, tone: "text-emerald-700 dark:text-emerald-300", chip: "bg-emerald-100 text-emerald-800 dark:bg-emerald-950/50 dark:text-emerald-200" }
    : run.failed_verification
      ? { label: "Checks failed", icon: XCircle, tone: "text-red-700 dark:text-red-300", chip: "bg-red-100 text-red-800 dark:bg-red-950/50 dark:text-red-200" }
      : { label: "Unverified", icon: AlertTriangle, tone: "text-amber-700 dark:text-amber-300", chip: "bg-amber-100 text-amber-800 dark:bg-amber-950/50 dark:text-amber-200" };
  const StateIcon = state.icon;
  return (
    <article className="rounded-2xl border border-[#d8d8cf] bg-[#fbfbf6] p-5 dark:border-[#292925] dark:bg-[#141411]">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <div className={`flex items-center gap-2 text-[10px] font-black uppercase tracking-[0.13em] ${state.tone}`}><StateIcon className="h-3.5 w-3.5" />{state.label}</div>
          <h2 className="mt-2 text-base font-black leading-6">{cleanDisplayText(run.objective) || "Recorded agent run"}</h2>
          <p className="mt-1 text-xs font-semibold text-[#68685f] dark:text-[#aaa9a0]">{run.model} · {profileLabel(run.model_profile)}{run.tool ? ` · ${run.tool}` : ""}</p>
        </div>
        <span className={`w-fit rounded-full px-2.5 py-1 text-[9px] font-black ${state.chip}`}>{state.label}</span>
      </div>
      <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
        <RunMetric icon={Clock3} value={durationLabel(run.duration_seconds)} label="Duration" />
        <RunMetric icon={FileCode2} value={run.changed_files.length} label="Files changed" />
        <RunMetric icon={CheckCircle2} value={`${run.verification.passed}/${run.verification.observed}`} label="Checks passed" />
        <RunMetric icon={PlayCircle} value={run.completed ? "Complete" : run.status} label="Outcome" />
      </div>
      {run.outcome_summary ? <p className="mt-4 text-xs font-semibold leading-5 text-[#4f4f48] dark:text-[#d8d8cf]">{cleanDisplayText(run.outcome_summary)}</p> : null}
      {run.changed_files.length ? <p className="mt-4 break-words font-mono text-[10px] leading-5 text-[#68685f] dark:text-[#aaa9a0]">{run.changed_files.slice(0, 5).join(" · ")}</p> : null}
      <p className="mt-3 text-[10px] font-semibold text-[#85857c]">{run.started_at ? `Started ${formatTimeAgo(run.started_at)}` : "Start time unavailable"}{run.unresolved_blocker ? " · unresolved blocker recorded" : ""}</p>
    </article>
  );
}

function ModelGroup({ group }) {
  const successRate = group.verified_success_rate === null ? null : Math.round(group.verified_success_rate * 100);
  return (
    <article className="rounded-2xl border border-[#d8d8cf] bg-[#fbfbf6] p-5 dark:border-[#292925] dark:bg-[#141411]">
      <p className="text-[10px] font-black uppercase tracking-[0.14em] text-[#85857c]">Recorded model</p>
      <h2 className="mt-2 break-words text-base font-black">{group.model}</h2>
      <p className="mt-1 text-[10px] font-semibold text-[#85857c]">{profileLabel(group.model_profile)}</p>
      <div className="mt-5 flex items-end justify-between gap-3">
        <div><p className="text-3xl font-black">{successRate === null ? "—" : `${successRate}%`}</p><p className="mt-1 text-[9px] font-black uppercase tracking-wide text-[#85857c]">Verified success</p></div>
        <p className="text-right text-xs font-bold text-[#68685f] dark:text-[#aaa9a0]">{group.verified_successful_runs}/{group.observed_runs} runs</p>
      </div>
      <div className="mt-4 h-2 overflow-hidden rounded-full bg-[#e6e6de] dark:bg-[#292925]"><div className="h-full rounded-full bg-emerald-500" style={{ width: `${successRate || 0}%` }} /></div>
      <div className="mt-4 flex flex-wrap gap-2 text-[9px] font-bold text-[#68685f] dark:text-[#aaa9a0]"><span>{group.failed_verification_runs} failed checks</span><span>·</span><span>{group.unresolved_blocker_runs} blocked</span></div>
    </article>
  );
}

function RunMetric({ icon: Icon, value, label }) {
  return <div className="rounded-xl bg-[#efefe7] p-3 dark:bg-[#252521]"><div className="flex items-center gap-1.5"><Icon className="h-3 w-3 text-[#85857c]" /><span className="text-sm font-black">{value}</span></div><p className="mt-1 text-[9px] font-bold uppercase tracking-wide text-[#85857c]">{label}</p></div>;
}

function ViewButton({ active, onClick, icon: Icon, children }) {
  return <button type="button" onClick={onClick} aria-pressed={active} className={`inline-flex h-8 items-center gap-1.5 rounded-lg px-3 text-[10px] font-black ${active ? "bg-[#171713] text-white dark:bg-[#d9ff68] dark:text-[#171713]" : "text-[#68685f] dark:text-[#aaa9a0]"}`}><Icon className="h-3.5 w-3.5" />{children}</button>;
}

function EmptyState({ title, detail, error = false, children = null }) {
  return <div className={`rounded-2xl border p-10 text-center ${error ? "border-red-200 bg-red-50 dark:border-red-900/60 dark:bg-red-950/25" : "border-dashed border-[#d8d8cf] bg-[#fbfbf6] dark:border-[#292925] dark:bg-[#141411]"}`}><h2 className="text-base font-black">{title}</h2>{detail ? <p className="mx-auto mt-2 max-w-xl text-xs leading-5 text-[#68685f] dark:text-[#aaa9a0]">{detail}</p> : null}{children ? <div className="mx-auto max-w-3xl">{children}</div> : null}</div>;
}

function durationLabel(seconds) {
  if (!Number.isFinite(Number(seconds))) return "—";
  const value = Number(seconds);
  if (value < 60) return `${Math.round(value)}s`;
  return `${Math.floor(value / 60)}m ${Math.round(value % 60)}s`;
}

function profileLabel(value) {
  return String(value || "unreported").replace("_coder_model", "").replaceAll("_", " ");
}
