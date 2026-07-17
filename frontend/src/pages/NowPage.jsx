import { Link } from "react-router-dom";
import {
  ArrowRight,
  Bot,
  CheckCircle2,
  Clock3,
  GitBranch,
  ShieldAlert,
  Sparkles,
} from "lucide-react";

import WorkspaceTopicGate from "../components/WorkspaceTopicGate";
import { useContextDigest } from "../context-map/api";
import { cleanDisplayText, formatTimeAgo } from "../context-map/digest";
import { useProductWorkspace } from "./useProductWorkspace";

export default function NowPage() {
  const workspace = useProductWorkspace();
  const digestQuery = useContextDigest(workspace.activeWorkspaceId);

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
    return <PageState title="Loading the current project state…" />;
  }
  if (digestQuery.isError) {
    return <PageState title="Could not load the project state" detail={digestQuery.error?.message} error />;
  }

  const digest = digestQuery.data || {};
  const cards = digest.cards || [];
  const focus = digest.oversight?.current_focus;
  const focusCard = focus?.component_id
    ? cards.find((card) => card.id === `component:${focus.component_id}`)
    : null;
  const nextTask = cards.find((card) => card.category === "task");
  const currentGoal = cleanDisplayText(
    focus?.title
    || (digest.objective?.status === "supplied" ? digest.objective.text : null)
    || nextTask?.title,
  );
  const focusDetail = distinctCardDetail(focusCard, "Prepare a task to give the next agent a focused, source-backed objective.");
  const attentionCards = cards
    .filter((card) => ["blocker", "risk", "issue", "document_finding"].includes(card.category))
    .filter((card) => !["resolved", "closed", "superseded"].includes(card.status))
    .sort((left, right) => (right.attention_score || 0) - (left.attention_score || 0))
    .slice(0, 3);
  const recommendedAction = cleanDisplayText(
    focusCard?.next_action
    || attentionCards[0]?.next_action
    || nextTask?.summary
    || nextTask?.title,
  );
  const latestOutcome = digest.oversight?.latest_outcome;
  const repoPath = digest.scope?.project_paths?.[0];
  const sourceCount = Number(digest.scope?.included_source_count || 0);

  return (
    <div className="relative mx-auto w-full max-w-6xl space-y-6">
      <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-xs font-black uppercase tracking-[0.18em] text-[#85857c]">{workspace.activeWorkspace?.name || "Project"}</p>
          <h1 className="mt-2 text-3xl font-black tracking-tight text-[#171713] dark:text-white">Now</h1>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-[#68685f] dark:text-[#aaa9a0]">
            Current project truth, recent agent evidence, and the next useful action.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Link to="/app/explain" className="inline-flex h-10 items-center gap-2 rounded-lg border border-[#d8d8cf] bg-white px-4 text-xs font-black text-[#4f4f48] dark:border-[#33332e] dark:bg-[#171713] dark:text-[#d8d8cf]">
            Explain project
          </Link>
          <Link to={`/app/prepare${currentGoal ? `?objective=${encodeURIComponent(currentGoal)}` : ""}`} className="inline-flex h-10 items-center gap-2 rounded-lg bg-[#171713] px-4 text-xs font-black text-white dark:bg-[#d9ff68] dark:text-[#171713]">
            Prepare task <ArrowRight className="h-3.5 w-3.5" />
          </Link>
        </div>
      </header>

      <section className="grid gap-4 lg:grid-cols-[1.55fr_.95fr]">
        <article className="rounded-2xl border border-[#d8d8cf] bg-[#fbfbf6] p-6 shadow-sm dark:border-[#292925] dark:bg-[#141411]">
          <div className="flex items-center gap-2 text-[10px] font-black uppercase tracking-[0.16em] text-[#85857c]">
            <Sparkles className="h-3.5 w-3.5" /> Current goal
          </div>
          <h2 className="mt-5 max-w-3xl text-2xl font-black leading-tight text-[#171713] dark:text-white">
            {currentGoal || "No explicit current goal has been captured."}
          </h2>
          <p className="mt-4 text-sm leading-6 text-[#68685f] dark:text-[#aaa9a0]">
            {focusDetail}
          </p>
          <div className="mt-6 flex flex-wrap gap-2 text-[10px] font-bold text-[#68685f] dark:text-[#aaa9a0]">
            <Metric icon={GitBranch} label={repoPath ? repoPath.split("/").filter(Boolean).pop() : "Repository not indexed"} />
            <Metric icon={Bot} label={`${sourceCount} captured source${sourceCount === 1 ? "" : "s"}`} />
            <Metric icon={Clock3} label={digest.generated_at ? `Updated ${formatTimeAgo(digest.generated_at)}` : "Update time unavailable"} />
          </div>
        </article>

        <article className="rounded-2xl border border-[#d8d8cf] bg-[#fbfbf6] p-6 shadow-sm dark:border-[#292925] dark:bg-[#141411]">
          <div className="flex items-center gap-2 text-[10px] font-black uppercase tracking-[0.16em] text-[#85857c]">
            <CheckCircle2 className="h-3.5 w-3.5" /> Latest observed result
          </div>
          {latestOutcome ? (
            <>
              <p className="mt-5 text-base font-black leading-6 text-[#171713] dark:text-white">{cleanDisplayText(latestOutcome.summary)}</p>
              <p className="mt-3 text-xs font-semibold text-[#85857c]">Observed {formatTimeAgo(latestOutcome.observed_at)}</p>
              <Link to="/app/runs" className="mt-6 inline-flex items-center gap-1.5 text-xs font-black text-[#171713] underline underline-offset-4 dark:text-[#d9ff68]">
                Inspect recorded runs <ArrowRight className="h-3 w-3" />
              </Link>
            </>
          ) : (
            <p className="mt-5 text-sm leading-6 text-[#68685f] dark:text-[#aaa9a0]">No agent outcome has been recorded for the current focus yet.</p>
          )}
        </article>
      </section>

      <section className="grid gap-4 lg:grid-cols-[1.2fr_.8fr]">
        <article className="rounded-2xl border border-[#d8d8cf] bg-[#fbfbf6] p-6 dark:border-[#292925] dark:bg-[#141411]">
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-2 text-[10px] font-black uppercase tracking-[0.16em] text-[#85857c]">
              <ShieldAlert className="h-3.5 w-3.5" /> Needs attention
            </div>
            <span className="rounded-full bg-amber-100 px-2 py-1 text-[9px] font-black text-amber-800 dark:bg-amber-950/50 dark:text-amber-200">{attentionCards.length} visible</span>
          </div>
          {attentionCards.length ? (
            <div className="mt-4 divide-y divide-[#e6e6de] dark:divide-[#292925]">
              {attentionCards.map((card) => (
                <div key={card.id} className="py-4 first:pt-0 last:pb-0">
                  <p className="text-sm font-black text-[#171713] dark:text-white">{cleanDisplayText(card.title)}</p>
                  <p className="mt-1.5 line-clamp-2 text-xs leading-5 text-[#68685f] dark:text-[#aaa9a0]">{distinctCardDetail(card, "Open the evidence record for the latest observed detail.")}</p>
                </div>
              ))}
            </div>
          ) : (
            <p className="mt-4 text-sm leading-6 text-[#68685f] dark:text-[#aaa9a0]">No active blocker, risk, issue, or document finding is visible in the current digest.</p>
          )}
        </article>

        <article className="rounded-2xl border border-[#171713] bg-[#171713] p-6 text-white dark:border-[#d9ff68] dark:bg-[#d9ff68] dark:text-[#171713]">
          <p className="text-[10px] font-black uppercase tracking-[0.16em] opacity-60">Recommended next action</p>
          <p className="mt-4 text-lg font-black leading-7">{recommendedAction || "Choose one concrete task and compile the context the agent actually needs."}</p>
          <Link to={`/app/prepare${recommendedAction ? `?objective=${encodeURIComponent(recommendedAction)}` : ""}`} className="mt-6 inline-flex items-center gap-2 rounded-lg bg-white px-3.5 py-2.5 text-xs font-black text-[#171713] dark:bg-[#171713] dark:text-white">
            Prepare this work <ArrowRight className="h-3.5 w-3.5" />
          </Link>
        </article>
      </section>
    </div>
  );
}

function Metric({ icon: Icon, label }) {
  return <span className="inline-flex items-center gap-1.5 rounded-full bg-[#efefe7] px-2.5 py-1.5 dark:bg-[#252521]"><Icon className="h-3 w-3" />{label}</span>;
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
    <div className={`mx-auto max-w-xl rounded-2xl border p-8 text-center ${error ? "border-red-200 bg-red-50 dark:border-red-900/60 dark:bg-red-950/30" : "border-[#d8d8cf] bg-[#fbfbf6] dark:border-[#292925] dark:bg-[#141411]"}`}>
      <h1 className="text-lg font-black">{title}</h1>
      {detail ? <p className="mt-2 text-sm text-[#68685f] dark:text-[#aaa9a0]">{detail}</p> : null}
    </div>
  );
}
