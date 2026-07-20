import { useState } from "react";
import { Link } from "react-router-dom";
import {
  ArrowRight,
  ArrowUpRight,
  Bot,
  CheckCircle2,
  Clock3,
  FileCode2,
  GitBranch,
  GitFork,
  History,
  ListFilter,
  Loader2,
  PlayCircle,
  Radio,
  RotateCcw,
  ShieldAlert,
  TestTube2,
} from "lucide-react";

import WorkspaceTopicGate from "../components/WorkspaceTopicGate";
import { api } from "../api/client";
import { useClearNowSession, useContextDigest, useLinkedAISessionRefresh } from "../context-map/api";
import { cleanDisplayText, formatTimeAgo } from "../context-map/digest";
import { useProductWorkspace } from "./useProductWorkspace";

export default function NowPage() {
  const workspace = useProductWorkspace();
  const digestQuery = useContextDigest(workspace.activeWorkspaceId, { poll: true });
  const sampleWorkspace = workspace.activeWorkspace?.kind === "demo";
  useLinkedAISessionRefresh(workspace.activeWorkspaceId, { enabled: !sampleWorkspace });
  const clearNowSession = useClearNowSession(workspace.activeWorkspaceId);

  if (!workspace.workspacesQuery.isLoading && !workspace.activeWorkspaceId) {
    return (
      <WorkspaceTopicGate
        workspaces={workspace.workspaces}
        selectedId={workspace.selectedId}
        onSelect={workspace.setSelectedId}
      />
    );
  }
  if (workspace.workspacesQuery.isLoading || digestQuery.isLoading) {
    return <PageState title="Loading observed project activity…" />;
  }
  if (digestQuery.isError) {
    return <PageState title="Could not load project activity" detail={digestQuery.error?.message} error />;
  }

  const digest = digestQuery.data || {};
  const cards = digest.cards || [];
  const currentGoal = cleanDisplayText(digest.current_goal?.title);
  const activity = digest.activity?.primary || fallbackActivity(digest);
  const visibleTopic = activityTitle(activity);
  const recordedAttentionCards = cards
    .filter((card) => card.attention_required)
    .filter((card) => card.workspace_relevance?.status !== "not_relevant")
  const sessionAttentionCards = (activity?.attention_items || [])
    .filter((item) => (
      item.source_document_id === activity?.source_document_id
      && (
        item.temporal_status !== "previous"
        || activity?.selected_for_now === true
      )
    ))
    .map((item) => ({
      ...item,
      href: sessionLibraryUrl({
        ...activity,
        source_document_id: item.source_document_id,
        selected_topic: item.title,
      }),
    }));
  const attentionCards = [...sessionAttentionCards, ...recordedAttentionCards]
    .sort((left, right) => (
      attentionTemporalRank(left) - attentionTemporalRank(right)
      || (right.attention_score || 0) - (left.attention_score || 0)
    ))
    .slice(0, 4);
  const recentSessions = (digest.activity?.recent_sessions || [])
    .filter((session) => session.source_document_id !== activity?.source_document_id)
    .sort((left, right) => activityTimestamp(right) - activityTimestamp(left))
    .slice(0, 4);
  const prepareObjective = currentGoal || visibleTopic;
  const prepareUrl = `/app/prepare${prepareObjective ? `?objective=${encodeURIComponent(prepareObjective)}` : ""}`;

  return (
    <div className="app-page relative">
      <header className="flex flex-col gap-5 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="eyebrow">{sampleWorkspace ? "Sample workspace" : workspace.activeWorkspace?.name || "Project"}</p>
          <h1 className="mt-2 text-3xl font-black tracking-tight text-[#171713] dark:text-white">Now</h1>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-[#68685f] dark:text-[#aaa9a0] sm:text-[15px]">
            {sampleWorkspace
              ? "Explore the product with sample evidence. Your real project activity stays separate."
              : "What changed, what needs attention, and where to continue."}
          </p>
          {currentGoal ? (
            <p className="mt-2 max-w-2xl truncate text-[10px] font-semibold text-[#85857c]">
              Pinned for Prepare · {currentGoal}
            </p>
          ) : null}
        </div>
        {sampleWorkspace ? (
          <div className="flex flex-wrap items-center gap-2">
            <Link to="/app/workspaces" className="btn-secondary h-11 text-xs">Choose project</Link>
            <Link to={prepareUrl} className="btn-primary h-11 text-xs">Explore Prepare <ArrowRight className="h-3.5 w-3.5" /></Link>
          </div>
        ) : activity?.kind === "agent_session" && activity?.refreshable ? (
          <div className="flex flex-col items-end gap-1.5">
            <div className="flex flex-wrap items-center justify-end gap-2">
              <Link to={prepareUrl} className="btn-secondary h-11 text-xs">Prepare handoff</Link>
              <ContinueInHarness
                activity={activity}
                workspaceId={workspace.activeWorkspaceId}
              />
            </div>
          </div>
        ) : (
          <div className="flex flex-wrap items-center gap-2">
            <Link to="/app/explain" className="btn-secondary h-11 text-xs">Project overview</Link>
            <Link to={prepareUrl} className="btn-primary h-11 text-xs">
              {prepareObjective ? "Prepare this work" : "Prepare work"} <ArrowRight className="h-3.5 w-3.5" />
            </Link>
          </div>
        )}
      </header>

      <section className="grid items-stretch gap-4 lg:grid-cols-[1.48fr_.82fr]">
        <ObservedWork activity={activity} clearSelection={clearNowSession} />
        <ObservedResult activity={activity} />
      </section>

      <AttentionPanel cards={attentionCards} activity={activity} />

      {recentSessions.length ? <RecentSessions sessions={recentSessions} /> : null}
    </div>
  );
}

function ContinueInHarness({ activity, workspaceId }) {
  const [launchState, setLaunchState] = useState({ status: "idle", message: "" });
  const harness = agentLabel({ ...activity, model: null });

  const openSession = async () => {
    setLaunchState({ status: "loading", message: "" });
    try {
      const result = await api.post("/session-library/open", {
        workspace_id: workspaceId,
        source_document_id: activity.source_document_id,
        topic: activity.selected_topic || activity.latest_topic || activity.title,
      });
      setLaunchState({ status: "success", message: result?.message || `${harness} opened.` });
    } catch (reason) {
      setLaunchState({
        status: reason?.detail?.code === "desktop_app_missing" ? "missing" : "error",
        message: reason?.message || `Could not open ${harness}.`,
      });
    }
  };

  return (
    <div className="flex flex-col items-end gap-1.5">
      <button
        type="button"
        onClick={openSession}
        disabled={launchState.status === "loading"}
        className="btn-primary h-11 text-xs disabled:cursor-wait disabled:opacity-65"
      >
        {launchState.status === "loading" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <PlayCircle className="h-3.5 w-3.5" />}
        {launchState.status === "loading" ? "Opening…" : `Continue in ${harness}`}
      </button>
      {launchState.status !== "idle" && launchState.status !== "loading" ? (
        <p className={`max-w-xs text-right text-[10px] font-semibold ${launchState.status === "success" ? "text-emerald-700 dark:text-emerald-300" : "text-red-700 dark:text-red-300"}`}>
          {launchState.message}
        </p>
      ) : null}
    </div>
  );
}

function ObservedWork({ activity, clearSelection }) {
  if (!activity) {
    return (
      <article className="app-surface relative overflow-hidden p-5 sm:p-6">
        <SurfaceAccent />
        <PanelLabel icon={PlayCircle}>Observed work</PanelLabel>
        <div className="mt-8 max-w-2xl">
          <h2 className="text-2xl font-semibold tracking-[-0.025em] text-[#171713] dark:text-white">No agent work observed yet.</h2>
          <p className="mt-3 text-sm leading-6 text-[#68685f] dark:text-[#aaa9a0]">
            Choose the session that matters from Library, or record an agent run. Now will not guess from unrelated session history.
          </p>
          <Link to="/app/library" className="group mt-6 inline-flex items-center gap-1.5 text-xs font-bold text-[#171713] dark:text-[#d9ff68]">
            Choose from Session Library <ArrowRight className="h-3 w-3 transition-transform group-hover:translate-x-0.5" />
          </Link>
        </div>
      </article>
    );
  }

  const observedRun = activity.evidence_level === "observed_run";
  const unassigned = activity.evidence_level === "session_unassigned";
  const projectMatched = activity.project_match?.status === "relevant";
  const importedSession = activity.kind === "agent_session";
  const selectedSession = importedSession && activity.selected_for_now;
  const historicalSelection = selectedSession && isHistoricalActivity(activity);
  const changedFiles = activity.changed_files || [];
  const verification = activity.verification || {};
  const latestUpdate = cleanDisplayText(activity.latest_update);
  const latestUpdatePreview = previewText(latestUpdate, 170);
  const reportedResult = cleanDisplayText(activity.result_summary?.text);
  const showLatestUpdate = latestUpdate && latestUpdate.toLowerCase() !== reportedResult?.toLowerCase();
  const detailUrl = importedSession
    ? sessionLibraryUrl(activity)
    : activity.source_card_id ? explainCardUrl(activity.source_card_id) : "/app/runs";

  return (
    <article className={`app-surface relative overflow-hidden p-5 sm:p-6 ${historicalSelection ? "border-indigo-200/80 bg-indigo-50/30 dark:border-indigo-900/60 dark:bg-indigo-950/10" : ""}`}>
      <SurfaceAccent historical={historicalSelection} />
      <div className="relative flex flex-wrap items-center justify-between gap-3">
        <PanelLabel icon={activity.live ? PlayCircle : History}>
          {selectedSession ? "Selected topic" : importedSession ? "Latest topic" : activity.live ? "Active work" : "Latest work"}
        </PanelLabel>
        <div className="flex items-center gap-2">
          {importedSession ? (
            <Link
              to={detailUrl}
              className="inline-flex items-center gap-1.5 rounded-lg border border-[#d8d8cf] bg-white/55 px-2.5 py-1.5 text-[9px] font-bold text-[#5f5f57] transition hover:border-[#a9c54a] hover:bg-white hover:text-[#171713] dark:border-[#34342f] dark:bg-white/[0.025] dark:text-[#bdbdb4] dark:hover:border-[#718a2c] dark:hover:text-[#d9ff68]"
            >
              <ListFilter className="h-3 w-3" /> Choose topic
            </Link>
          ) : null}
          <ActivityBadge activity={activity} historical={historicalSelection} />
        </div>
      </div>

      <h2 className="relative mt-6 max-w-4xl text-2xl font-semibold leading-[1.2] tracking-[-0.025em] text-[#171713] dark:text-white sm:text-[28px]">
        {activityTitle(activity) || "Agent request was not captured."}
      </h2>
      {importedSession ? (
        <Link
          to={detailUrl}
          aria-label={`From session: ${cleanDisplayText(activity.session_title) || "Imported session"}`}
          className="relative mt-3 inline-flex max-w-full items-center gap-1.5 text-[10px] font-bold text-[#77776e] transition hover:text-[#171713] dark:text-[#aaa9a0] dark:hover:text-[#d9ff68]"
        >
          <span>From session</span>
          <span aria-hidden="true">·</span>
          <span className="truncate text-[#4f4f48] dark:text-[#d0d0c7]">{cleanDisplayText(activity.session_title) || "Imported session"}</span>
          <ArrowUpRight className="h-3 w-3 shrink-0" />
        </Link>
      ) : null}

      {selectedSession ? (
        <div className={`relative mt-5 flex flex-col gap-3 rounded-xl border px-4 py-3 sm:flex-row sm:items-center sm:justify-between ${historicalSelection ? "border-indigo-200 bg-indigo-50/80 dark:border-indigo-900/70 dark:bg-indigo-950/30" : "border-[#d8e4ad] bg-[#f4f8e5] dark:border-[#465226] dark:bg-[#d9ff68]/[0.055]"}`}>
          <div className="flex min-w-0 items-start gap-3">
            <span className={`mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg ${historicalSelection ? "bg-indigo-100 text-indigo-700 dark:bg-indigo-400/10 dark:text-indigo-200" : "bg-[#e4efbc] text-[#64771e] dark:bg-[#d9ff68]/10 dark:text-[#d9ff68]"}`}>
              {historicalSelection ? <History className="h-3.5 w-3.5" /> : <Radio className="h-3.5 w-3.5" />}
            </span>
            <div className="min-w-0">
              <p className={`text-[10px] font-black uppercase tracking-[0.12em] ${historicalSelection ? "text-indigo-800 dark:text-indigo-200" : "text-[#64771e] dark:text-[#d9ff68]"}`}>
                {historicalSelection ? "Historical selection" : "Pinned selection"}
              </p>
              <p className="mt-1 text-xs leading-5 text-[#5f5f57] dark:text-[#bdbdb4]">
                {historicalSelection
                  ? `Updated ${formatTimeAgo(activity.updated_at)}. This remains pinned for reference and is not live activity.`
                  : "This topic is pinned for reference. Return to latest activity whenever you are done reviewing it."}
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={() => clearSelection.mutate()}
            disabled={clearSelection.isPending}
            className={`inline-flex h-9 shrink-0 items-center justify-center gap-1.5 rounded-lg border px-3 text-[10px] font-black transition disabled:cursor-wait disabled:opacity-60 ${historicalSelection ? "border-indigo-300 bg-white text-indigo-800 hover:border-indigo-500 dark:border-indigo-800 dark:bg-indigo-950/40 dark:text-indigo-100" : "border-[#bdce7e] bg-white/75 text-[#4e5c1b] hover:border-[#8aa62a] dark:border-[#59682d] dark:bg-black/10 dark:text-[#d9ff68]"}`}
          >
            <RotateCcw className={`h-3 w-3 ${clearSelection.isPending ? "animate-spin" : ""}`} />
            {clearSelection.isPending ? "Returning…" : "Return to latest activity"}
          </button>
          {clearSelection.isError ? (
            <p className="text-[10px] font-semibold text-red-700 dark:text-red-300">Could not clear this selection. Try again.</p>
          ) : null}
        </div>
      ) : null}

      {showLatestUpdate ? (
        <div className="relative mt-6 border-l-2 border-[#c5d98a] pl-4 dark:border-[#4b5830]">
          <p className="text-[9px] font-bold uppercase tracking-[0.15em] text-[#85857c]">
            {observedRun ? "Latest recorded update" : "Latest update"}
          </p>
          <p
            title={latestUpdate}
            className="mt-1.5 line-clamp-3 max-w-3xl break-words text-sm leading-6 text-[#4f4f48] [overflow-wrap:anywhere] dark:text-[#d0d0c7]"
          >
            {latestUpdatePreview}
          </p>
        </div>
      ) : null}

      {observedRun && activity.rationale && cleanDisplayText(activity.rationale) !== latestUpdate ? (
        <div className="relative mt-5 rounded-xl bg-[#f1f1e9] px-4 py-3 dark:bg-white/[0.035]">
          <p className="text-[9px] font-bold uppercase tracking-[0.14em] text-[#85857c]">Why this approach</p>
          <p className="mt-1.5 line-clamp-2 text-xs leading-5 text-[#5f5f57] dark:text-[#bdbdb4]">{cleanDisplayText(activity.rationale)}</p>
        </div>
      ) : null}

      <div className="relative mt-6 flex flex-wrap gap-2">
        <Metric icon={Bot} label={agentLabel(activity)} />
        {activity.branch ? <Metric icon={GitBranch} label={activity.branch} /> : null}
        {observedRun && changedFiles.length ? <Metric icon={FileCode2} label={`${changedFiles.length} file${changedFiles.length === 1 ? "" : "s"} changed`} /> : null}
        {observedRun && verification.observed ? <Metric icon={TestTube2} label={verificationLabel(verification)} /> : null}
        <Metric icon={Clock3} label={activity.updated_at ? `Updated ${formatTimeAgo(activity.updated_at)}` : "Update time unavailable"} />
      </div>

      <div className="relative mt-5 flex flex-col gap-3 border-t border-[#e5e5dd] pt-4 dark:border-[#292925] sm:flex-row sm:items-center sm:justify-between">
        <p className="text-[10px] font-medium leading-5 text-[#85857c]">
          {observedRun
            ? "Repository-backed activity and checks."
            : unassigned
              ? "Harness transcript · project match pending."
              : projectMatched
                ? "Harness transcript · automatically matched to this project · repository not verified."
                : "Harness transcript · agent-reported until repository evidence confirms it."}
        </p>
        <Link to={detailUrl} className="group inline-flex shrink-0 items-center gap-1.5 text-xs font-bold text-[#171713] dark:text-[#d9ff68]">
          {importedSession ? "Review session evidence" : "Open run evidence"}
          <ArrowRight className="h-3 w-3 transition-transform group-hover:translate-x-0.5" />
        </Link>
      </div>
    </article>
  );
}

function ObservedResult({ activity }) {
  const outcome = activity?.outcome || null;
  const reportedSummary = activity?.result_summary || null;
  const verification = activity?.verification || {};
  const changedFiles = activity?.changed_files || [];
  const importedSession = activity?.kind === "agent_session";
  const detailUrl = importedSession
    ? sessionLibraryUrl(activity)
    : activity?.source_card_id ? explainCardUrl(activity.source_card_id) : "/app/runs";

  return (
    <article className="app-surface p-5 sm:p-6">
      <PanelLabel icon={CheckCircle2}>{importedSession ? "Latest session result" : "Latest result"}</PanelLabel>
      {outcome ? (
        <>
          <ResultProvenance label="Observed outcome" verified />
          <p className="mt-4 text-lg font-semibold leading-7 tracking-[-0.012em] text-[#171713] dark:text-white">
            {cleanDisplayText(outcome.summary) || "A terminal outcome was recorded."}
          </p>
          <div className="mt-6 space-y-2.5 border-t border-[#e5e5dd] pt-4 dark:border-[#292925]">
            {changedFiles.length ? <EvidenceRow label="Changed" value={`${changedFiles.length} file${changedFiles.length === 1 ? "" : "s"}`} /> : null}
            {verification.observed ? <EvidenceRow label="Checks" value={verificationLabel(verification)} /> : null}
            <EvidenceRow label="Observed" value={formatTimeAgo(outcome.observed_at || activity?.updated_at)} />
          </div>
          <Link to="/app/runs" className="group mt-6 inline-flex items-center gap-1.5 text-xs font-bold text-[#171713] dark:text-[#d9ff68]">
            View run evidence <ArrowRight className="h-3 w-3 transition-transform group-hover:translate-x-0.5" />
          </Link>
        </>
      ) : reportedSummary?.text ? (
        <>
          <ResultProvenance label={reportedSummary.kind === "completion" ? "Agent-reported result" : "Agent-reported update"} />
          <p
            title={cleanDisplayText(reportedSummary.text)}
            className="mt-4 line-clamp-6 break-words text-lg font-semibold leading-7 tracking-[-0.012em] text-[#171713] [overflow-wrap:anywhere] dark:text-white"
          >
            {cleanDisplayText(reportedSummary.text)}
          </p>
          <div className="mt-6 space-y-2.5 border-t border-[#e5e5dd] pt-4 dark:border-[#292925]">
            {changedFiles.length ? <EvidenceRow label="Changed" value={`${changedFiles.length} file${changedFiles.length === 1 ? "" : "s"}`} /> : null}
            {verification.observed ? <EvidenceRow label="Checks" value={verificationLabel(verification)} /> : null}
            <EvidenceRow label="Verification" value={changedFiles.length || verification.observed ? "Partially observed" : "Session-only"} />
            <EvidenceRow label="Reported" value={formatTimeAgo(reportedSummary.reported_at || activity?.updated_at)} />
          </div>
          <p className="mt-5 text-[10px] leading-5 text-[#85857c]">From the harness session · not repository-verified.</p>
          <Link to={detailUrl} className="group mt-4 inline-flex items-center gap-1.5 text-xs font-bold text-[#171713] dark:text-[#d9ff68]">
            {importedSession ? "Review result evidence" : "View run evidence"} <ArrowRight className="h-3 w-3 transition-transform group-hover:translate-x-0.5" />
          </Link>
        </>
      ) : (
        <>
          <p className="mt-7 text-lg font-semibold leading-7 text-[#171713] dark:text-white">Work is still in progress.</p>
          <p className="mt-2 text-sm leading-6 text-[#68685f] dark:text-[#aaa9a0]">
            {activity?.evidence_level?.startsWith("session_")
              ? "No meaningful agent summary or independently verified outcome has been captured yet."
              : "A summary will appear after the run reports progress or records an outcome."}
          </p>
          {verification.observed ? (
            <div className="mt-5 border-t border-[#e5e5dd] pt-4 dark:border-[#292925]">
              <EvidenceRow label="Checks so far" value={verificationLabel(verification)} />
            </div>
          ) : null}
        </>
      )}
    </article>
  );
}

function ResultProvenance({ label, verified = false }) {
  return (
    <span className={`mt-6 inline-flex rounded-full px-2.5 py-1 text-[9px] font-bold uppercase tracking-[0.11em] ${verified ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-400/10 dark:text-emerald-200" : "bg-[#efefe7] text-[#68685f] dark:bg-[#252521] dark:text-[#bdbdb4]"}`}>
      {label}
    </span>
  );
}

function AttentionPanel({ cards, activity }) {
  const currentCount = cards.filter((card) => card.temporal_status !== "previous").length;
  const previousCount = cards.length - currentCount;
  return (
    <section className="app-surface p-5 sm:p-6">
      <div className="flex items-center justify-between gap-3">
        <PanelLabel icon={ShieldAlert}>Needs attention</PanelLabel>
        <span className={`rounded-full px-2.5 py-1 text-[9px] font-bold ${currentCount ? "bg-amber-100/80 text-amber-800 dark:bg-amber-950/50 dark:text-amber-200" : "bg-slate-100 text-slate-600 dark:bg-slate-800/60 dark:text-slate-300"}`}>
          {currentCount ? `${currentCount} current` : activity?.kind === "agent_session" ? "No session issues" : "No current items"}{previousCount ? ` · ${previousCount} previous` : ""}
        </span>
      </div>
      {cards.length ? (
        <div className="mt-4 grid gap-2.5 md:grid-cols-2">
          {cards.map((card) => {
            const previous = card.temporal_status === "previous";
            return (
            <Link
              key={card.id}
              to={card.href || explainCardUrl(card.id)}
              className={`group flex min-h-[116px] flex-col rounded-xl border p-4 transition-all duration-200 hover:-translate-y-0.5 hover:shadow-[0_7px_20px_rgba(23,23,19,0.05)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[#95b52f]/45 dark:hover:shadow-none ${previous ? "border-slate-200 bg-slate-50/55 hover:border-slate-300 hover:bg-slate-50 dark:border-slate-800 dark:bg-slate-900/20 dark:hover:border-slate-700 dark:hover:bg-slate-900/35" : "border-amber-200/80 bg-amber-50/35 hover:border-amber-300 hover:bg-amber-50/60 dark:border-amber-900/50 dark:bg-amber-950/10 dark:hover:border-amber-800 dark:hover:bg-amber-950/20"}`}
            >
              <div className="flex items-start justify-between gap-3">
                <p className="text-sm font-semibold leading-5 text-[#171713] dark:text-white">{cleanDisplayText(card.title)}</p>
                <span className={`shrink-0 rounded-full px-2 py-1 text-[8px] font-bold uppercase tracking-[0.1em] ${previous ? "bg-slate-200/70 text-slate-600 dark:bg-slate-700/50 dark:text-slate-300" : "bg-amber-100 text-amber-800 dark:bg-amber-400/10 dark:text-amber-200"}`}>
                  {previous ? `Previous ${attentionLabel(card).toLowerCase()}` : attentionLabel(card)}
                </span>
              </div>
              <p className="mt-2 line-clamp-2 break-words text-xs leading-5 text-[#68685f] [overflow-wrap:anywhere] dark:text-[#aaa9a0]">
                {distinctCardDetail(card, "Open the evidence record for the latest observed detail.")}
              </p>
              <span className="mt-auto flex items-center gap-1.5 pt-3 text-[10px] font-bold text-[#77776e] transition-colors group-hover:text-[#171713] dark:group-hover:text-[#d9ff68]">
                {card.kind === "user_correction" ? "Review session evidence" : "Explain evidence"} <ArrowRight className="h-3 w-3 transition-transform group-hover:translate-x-0.5" />
              </span>
            </Link>
            );
          })}
        </div>
      ) : (
        <p className="mt-4 text-sm leading-6 text-[#68685f] dark:text-[#aaa9a0]">
          {activity?.kind === "agent_session"
            ? "No issues were detected in this session. Repository checks have not confirmed the project state."
            : "No blocker, conflict, stale evidence, or high-risk review is currently visible."}
        </p>
      )}
    </section>
  );
}

function RecentSessions({ sessions }) {
  return (
    <section className="app-surface p-5 sm:p-6">
      <div className="flex items-center justify-between gap-3">
        <PanelLabel icon={History}>Recent coding sessions</PanelLabel>
        <Link to="/app/library" className="text-[10px] font-bold text-[#77776e] underline-offset-4 hover:underline dark:text-[#aaa9a0]">View session library</Link>
      </div>
      <div className="mt-4 divide-y divide-[#e5e5dd] dark:divide-[#292925]">
        {sessions.map((session) => {
          return (
            <Link key={session.id} to={sessionLibraryUrl(session)} className="group flex items-center gap-3 py-3.5 first:pt-1 last:pb-1">
              <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-[#efefe7] text-[#68685f] dark:bg-[#252521] dark:text-[#c7c7bd]"><Bot className="h-4 w-4" /></span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-semibold text-[#171713] dark:text-white">{activityTitle(session) || "Imported coding session"}</span>
                <span className="mt-1 flex min-w-0 items-center gap-1.5 truncate text-[10px] font-medium text-[#85857c]">
                  {session.forked_from ? <GitFork className="h-3 w-3 shrink-0" aria-label="Continued in a new task" /> : null}
                  <span className="truncate">{session.forked_from ? `Continued from ${cleanDisplayText(session.forked_from.title)} · ` : ""}{agentLabel({ ...session, model: null })} · {session.updated_at ? formatTimeAgo(session.updated_at) : "Time unavailable"}</span>
                </span>
              </span>
              <ArrowRight className="h-3.5 w-3.5 shrink-0 text-[#aaa99f] transition-transform group-hover:translate-x-0.5 group-hover:text-[#171713] dark:group-hover:text-[#d9ff68]" />
            </Link>
          );
        })}
      </div>
    </section>
  );
}

function PanelLabel({ icon: Icon, children }) {
  return (
    <div className="flex items-center gap-2 text-[10px] font-bold uppercase tracking-[0.16em] text-[#77776e] dark:text-[#929289]">
      <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-[#edf3d7] text-[#708327] dark:bg-[#d9ff68]/10 dark:text-[#d9ff68]"><Icon className="h-3.5 w-3.5" /></span>
      {children}
    </div>
  );
}

function SurfaceAccent({ historical = false }) {
  return (
    <>
      <div className={`pointer-events-none absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent to-transparent opacity-80 ${historical ? "via-indigo-400 dark:via-indigo-500" : "via-[#accf3d] dark:via-[#d9ff68]"}`} />
      <div className={`pointer-events-none absolute -right-20 -top-24 h-52 w-52 rounded-full blur-3xl ${historical ? "bg-indigo-300/15 dark:bg-indigo-500/[0.06]" : "bg-[#d9ff68]/10 dark:bg-[#d9ff68]/[0.055]"}`} />
    </>
  );
}

function ActivityBadge({ activity, historical = false }) {
  const label = activity.live
    ? "Live session"
    : historical
      ? "Historical selection"
    : activity.selected_for_now
      ? "Selected for Now"
      : activity.evidence_level === "observed_run"
        ? "Observed run"
        : activity.evidence_level === "session_unassigned"
          ? "Project match pending"
          : activity.project_match?.status === "relevant"
            ? "Project matched"
          : activity.refreshable ? "Auto-updating" : "Imported session";
  return (
    <span className={`rounded-full px-2.5 py-1 text-[9px] font-bold ${activity.live ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-400/10 dark:text-emerald-200" : historical ? "bg-indigo-100 text-indigo-800 dark:bg-indigo-400/10 dark:text-indigo-200" : "bg-[#efefe7] text-[#68685f] dark:bg-[#252521] dark:text-[#bdbdb4]"}`}>
      {label}
    </span>
  );
}

function EvidenceRow({ label, value }) {
  return (
    <div className="flex items-center justify-between gap-4 text-xs">
      <span className="font-medium text-[#85857c]">{label}</span>
      <span className="text-right font-bold text-[#383832] dark:text-[#e0e0d8]">{value}</span>
    </div>
  );
}

function Metric({ icon: Icon, label }) {
  return <span className="status-chip"><Icon className="h-3 w-3" />{label}</span>;
}

function agentLabel(activity) {
  const rawTool = cleanDisplayText(activity.tool || "Agent").toLowerCase();
  const tool = {
    codex: "Codex",
    claude: "Claude Code",
    claude_code: "Claude Code",
    opencode: "OpenCode",
    agent: "Agent",
  }[rawTool] || cleanDisplayText(activity.tool || "Agent");
  const model = cleanDisplayText(activity.model);
  return model ? `${tool} · ${model}` : tool;
}

function activityTitle(activity) {
  if (!activity) return "";
  const importedSession = activity.kind === "agent_session";
  if (importedSession && activity.selected_for_now) {
    return cleanDisplayText(activity.selected_topic || activity.title);
  }
  if (importedSession) {
    return cleanDisplayText(
      activity.latest_topic || activity.title || activity.session_title || activity.request,
    );
  }
  return cleanDisplayText(activity.request || activity.title);
}

function verificationLabel(verification = {}) {
  const observed = Number(verification.observed || 0);
  const passed = Number(verification.passed || 0);
  const failed = Number(verification.failed || 0);
  if (failed) return `${passed} passed · ${failed} failed`;
  return `${passed}/${observed} passed`;
}

function attentionLabel(card) {
  if (card.kind === "user_correction") return "User correction";
  if (card.status === "conflict") return "Conflict";
  if (card.status === "stale") return "Stale";
  if (card.category === "blocker" || card.status === "blocked") return "Blocker";
  if (card.type === "risk" || card.category === "risk") return "Risk";
  return "Review";
}

function attentionTemporalRank(card) {
  return card?.temporal_status === "previous" ? 1 : 0;
}

function isHistoricalActivity(activity) {
  if (!activity || activity.live || !activity.updated_at) return false;
  const updatedAt = new Date(activity.updated_at).getTime();
  if (!Number.isFinite(updatedAt)) return false;
  return Date.now() - updatedAt > 2 * 60 * 60 * 1000;
}

function explainCardUrl(cardId) {
  return `/app/explain?card=${encodeURIComponent(cardId)}`;
}

function sessionLibraryUrl(activity) {
  const sourceDocumentId = activity?.source_document_id
    || (String(activity?.id || "").startsWith("session:") ? String(activity.id).slice("session:".length) : "");
  if (!sourceDocumentId) return "/app/library";
  const params = new URLSearchParams({ source: sourceDocumentId });
  const topic = cleanDisplayText(activity?.selected_topic || activity?.latest_topic || activity?.title);
  if (topic) params.set("topic", topic);
  return `/app/library?${params.toString()}`;
}

function activityTimestamp(card) {
  const value = card?.updated_at || card?.source_snapshot?.ingested_at;
  const parsed = value ? new Date(value).getTime() : 0;
  return Number.isFinite(parsed) ? parsed : 0;
}

function previewText(value, maxChars = 170) {
  const text = cleanDisplayText(value);
  if (!text || text.length <= maxChars) return text;
  const clipped = text.slice(0, maxChars - 3).replace(/\s+\S*$/, "");
  const safe = clipped && clipped.length > maxChars * 0.6
    ? clipped
    : text.slice(0, maxChars - 3);
  return `${safe.trim().replace(/[,:;\-]+$/, "")}...`;
}

function fallbackActivity(digest) {
  const outcome = digest?.oversight?.latest_outcome;
  const goal = cleanDisplayText(digest?.current_goal?.title);
  if (!outcome || !goal) return null;
  return {
    kind: "agent_run",
    state: "completed",
    evidence_level: "observed_run",
    title: goal,
    request: goal,
    latest_update: cleanDisplayText(outcome.summary),
    updated_at: outcome.observed_at,
    changed_files: [],
    verification: { observed: 0, passed: 0, failed: 0 },
    outcome,
  };
}

function distinctCardDetail(card, fallback) {
  if (!card) return fallback;
  const title = cleanDisplayText(card.title);
  for (const candidate of [card.summary, card.next_action, card.why_it_matters]) {
    let detail = cleanDisplayText(candidate);
    if (!detail) continue;
    if (title && detail.toLowerCase().startsWith(title.toLowerCase())) {
      detail = detail.slice(title.length).trim();
    }
    detail = detail
      .replace(/^State:\s*\S+\s*/i, "")
      .replace(/^Labels:\s*none\s*/i, "")
      .trim();
    if (detail && detail.toLowerCase() !== title.toLowerCase()) return detail;
  }
  return fallback;
}

function PageState({ title, detail, error = false }) {
  return (
    <div className={`mx-auto max-w-xl rounded-2xl border p-8 text-center shadow-[0_12px_36px_rgba(23,23,19,0.04)] dark:shadow-none ${error ? "border-red-200 bg-red-50 dark:border-red-900/60 dark:bg-red-950/30" : "border-[#d8d8cf] bg-[#fbfbf6] dark:border-[#292925] dark:bg-[#141411]"}`}>
      <h1 className="text-lg font-semibold">{title}</h1>
      {detail ? <p className="mt-2 text-sm text-[#68685f] dark:text-[#aaa9a0]">{detail}</p> : null}
    </div>
  );
}
