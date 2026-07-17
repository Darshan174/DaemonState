import { useState } from "react";
import { Link } from "react-router-dom";
import {
  ArrowRight,
  Bot,
  CheckCircle2,
  Clock3,
  GitBranch,
  ListTodo,
  Pencil,
  ShieldAlert,
  Sparkles,
  X,
} from "lucide-react";

import WorkspaceTopicGate from "../components/WorkspaceTopicGate";
import { useClearCurrentGoal, useContextDigest, useSetCurrentGoal } from "../context-map/api";
import { cleanDisplayText, formatTimeAgo } from "../context-map/digest";
import { useProductWorkspace } from "./useProductWorkspace";

export default function NowPage() {
  const workspace = useProductWorkspace();
  const digestQuery = useContextDigest(workspace.activeWorkspaceId);
  const setCurrentGoal = useSetCurrentGoal(workspace.activeWorkspaceId);
  const clearCurrentGoal = useClearCurrentGoal(workspace.activeWorkspaceId);
  const [choosingGoal, setChoosingGoal] = useState(false);
  const [customGoal, setCustomGoal] = useState("");

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
  const goal = digest.current_goal || null;
  const focusCard = goal?.component_id
    ? cards.find((card) => card.id === `component:${goal.component_id}`)
    : null;
  const currentGoal = cleanDisplayText(goal?.title);
  const focusDetail = distinctCardDetail(focusCard, "This goal was selected explicitly. Context Engine will not replace it with an inferred issue.");
  const attentionCards = cards
    .filter((card) => card.attention_required)
    .sort((left, right) => (right.attention_score || 0) - (left.attention_score || 0))
    .slice(0, 3);
  const backlogCards = cards
    .filter((card) => ["issue", "task"].includes(card.category))
    .filter((card) => card.focus_eligible)
    .filter((card) => !["resolved", "closed", "superseded", "stale"].includes(card.status))
    .filter((card) => card.id !== `component:${goal?.component_id}`)
    .sort((left, right) => (right.attention_score || 0) - (left.attention_score || 0));
  const suggestedCard = backlogCards[0] || null;
  const recommendedAction = cleanDisplayText(
    suggestedCard?.title
    || attentionCards[0]?.next_action,
  );
  const latestOutcome = digest.oversight?.latest_outcome;
  const repoPath = digest.scope?.project_paths?.[0];
  const sourceCount = Number(digest.scope?.included_source_count || 0);

  async function chooseCard(card) {
    await setCurrentGoal.mutateAsync({
      title: cleanDisplayText(card.title),
      component_id: card.id.replace(/^component:/, ""),
      source_kind: "suggested_card",
      source_id: card.source_snapshot?.source_document_id || undefined,
    });
    setChoosingGoal(false);
  }

  async function submitCustomGoal(event) {
    event.preventDefault();
    const title = cleanDisplayText(customGoal);
    if (title.length < 3) return;
    await setCurrentGoal.mutateAsync({ title, source_kind: "user_selected" });
    setCustomGoal("");
    setChoosingGoal(false);
  }

  async function clearGoal() {
    await clearCurrentGoal.mutateAsync();
    setChoosingGoal(true);
  }

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
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-2 text-[10px] font-black uppercase tracking-[0.16em] text-[#85857c]">
              <Sparkles className="h-3.5 w-3.5" /> Current goal
            </div>
            <div className="flex items-center gap-2">
              {goal?.source_kind === "active_agent_run" ? (
                <span className="text-[10px] font-black text-[#85857c]">Locked during run</span>
              ) : (
              <button type="button" onClick={() => setChoosingGoal((value) => !value)} className="inline-flex items-center gap-1.5 rounded-md border border-[#d8d8cf] px-2.5 py-1.5 text-[10px] font-black text-[#68685f] dark:border-[#33332e] dark:text-[#d8d8cf]">
                {choosingGoal ? <X className="h-3 w-3" /> : <Pencil className="h-3 w-3" />}
                {choosingGoal ? "Close" : currentGoal ? "Change" : "Choose goal"}
              </button>
              )}
              {goal?.can_clear ? (
                <button type="button" onClick={clearGoal} disabled={clearCurrentGoal.isPending} className="text-[10px] font-black text-[#85857c] underline underline-offset-4 disabled:opacity-50">Clear</button>
              ) : null}
            </div>
          </div>
          <h2 className="mt-5 max-w-3xl text-2xl font-black leading-tight text-[#171713] dark:text-white">
            {currentGoal || "No current goal selected."}
          </h2>
          <p className="mt-4 text-sm leading-6 text-[#68685f] dark:text-[#aaa9a0]">
            {currentGoal ? focusDetail : "Choose the work intentionally. Open issues remain backlog until you select one."}
          </p>
          {goal ? (
            <p className="mt-3 text-[10px] font-bold uppercase tracking-[0.12em] text-[#85857c]">
              {goalSourceLabel(goal)}{goal.selected_at ? ` · ${formatTimeAgo(goal.selected_at)}` : ""}
            </p>
          ) : null}
          {choosingGoal ? (
            <GoalChooser
              backlogCards={backlogCards}
              customGoal={customGoal}
              error={setCurrentGoal.error?.message}
              isPending={setCurrentGoal.isPending}
              onChooseCard={chooseCard}
              onCustomGoalChange={setCustomGoal}
              onSubmit={submitCustomGoal}
            />
          ) : null}
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
            <p className="mt-4 text-sm leading-6 text-[#68685f] dark:text-[#aaa9a0]">No blocker, conflict, stale evidence, or high-risk review is currently visible.</p>
          )}
        </article>

        <article className="rounded-2xl border border-[#171713] bg-[#171713] p-6 text-white dark:border-[#d9ff68] dark:bg-[#d9ff68] dark:text-[#171713]">
          <p className="text-[10px] font-black uppercase tracking-[0.16em] opacity-60">Suggested next · not selected</p>
          <p className="mt-4 text-lg font-black leading-7">{recommendedAction || "No actionable backlog item is strong enough to suggest yet."}</p>
          <p className="mt-3 text-xs leading-5 opacity-70">Suggestions are ranked from visible actionable cards. They never silently become the current goal.</p>
          {suggestedCard ? (
            <button type="button" onClick={() => chooseCard(suggestedCard)} disabled={setCurrentGoal.isPending} className="mt-6 inline-flex items-center gap-2 rounded-lg bg-white px-3.5 py-2.5 text-xs font-black text-[#171713] disabled:opacity-50 dark:bg-[#171713] dark:text-white">
              Make current <ArrowRight className="h-3.5 w-3.5" />
            </button>
          ) : null}
        </article>
      </section>

      <section className="rounded-2xl border border-[#d8d8cf] bg-[#fbfbf6] p-6 dark:border-[#292925] dark:bg-[#141411]">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2 text-[10px] font-black uppercase tracking-[0.16em] text-[#85857c]"><ListTodo className="h-3.5 w-3.5" /> Backlog</div>
          <span className="text-[10px] font-black text-[#85857c]">{backlogCards.length} available</span>
        </div>
        {backlogCards.length ? (
          <div className="mt-4 grid gap-2 md:grid-cols-2">
            {backlogCards.slice(0, 4).map((card) => (
              <button key={card.id} type="button" onClick={() => chooseCard(card)} className="rounded-lg border border-[#e1e1d9] p-3 text-left transition hover:border-[#aaa99f] dark:border-[#2d2d28] dark:hover:border-[#57574f]">
                <span className="block text-xs font-black text-[#171713] dark:text-white">{cleanDisplayText(card.title)}</span>
                <span className="mt-1 block text-[10px] font-semibold text-[#85857c]">Select as current goal</span>
              </button>
            ))}
          </div>
        ) : <p className="mt-4 text-sm text-[#68685f] dark:text-[#aaa9a0]">No actionable issues or tasks are currently captured.</p>}
      </section>
    </div>
  );
}

function GoalChooser({ backlogCards, customGoal, error, isPending, onChooseCard, onCustomGoalChange, onSubmit }) {
  return (
    <div className="mt-5 rounded-xl border border-[#deded5] bg-white p-4 dark:border-[#30302b] dark:bg-[#10100e]">
      <form onSubmit={onSubmit}>
        <label htmlFor="current-goal-title" className="text-[10px] font-black uppercase tracking-[0.12em] text-[#85857c]">Describe current work</label>
        <div className="mt-2 flex flex-col gap-2 sm:flex-row">
          <input id="current-goal-title" value={customGoal} onChange={(event) => onCustomGoalChange(event.target.value)} placeholder="e.g. Fix workspace onboarding" className="min-w-0 flex-1 rounded-lg border border-[#d8d8cf] bg-[#fbfbf6] px-3 py-2.5 text-sm font-semibold outline-none focus:ring-2 focus:ring-brand-500/30 dark:border-[#33332e] dark:bg-[#171713]" />
          <button type="submit" disabled={isPending || cleanDisplayText(customGoal).length < 3} className="rounded-lg bg-[#171713] px-4 py-2.5 text-xs font-black text-white disabled:opacity-40 dark:bg-[#d9ff68] dark:text-[#171713]">Set current</button>
        </div>
      </form>
      {backlogCards.length ? (
        <div className="mt-4 border-t border-[#e5e5dd] pt-4 dark:border-[#292925]">
          <p className="text-[10px] font-black uppercase tracking-[0.12em] text-[#85857c]">Or choose from backlog</p>
          <div className="mt-2 space-y-1.5">
            {backlogCards.slice(0, 4).map((card) => (
              <button key={card.id} type="button" onClick={() => onChooseCard(card)} disabled={isPending} className="block w-full rounded-md px-2.5 py-2 text-left text-xs font-bold text-[#4f4f48] hover:bg-[#f0f0e8] disabled:opacity-50 dark:text-[#d8d8cf] dark:hover:bg-[#23231f]">{cleanDisplayText(card.title)}</button>
            ))}
          </div>
        </div>
      ) : null}
      {error ? <p className="mt-3 text-xs font-bold text-red-600 dark:text-red-400">{error}</p> : null}
    </div>
  );
}

function goalSourceLabel(goal) {
  if (goal.source_kind === "active_agent_run") return `Active ${goal.selected_by || "agent"} run`;
  if (goal.source_kind === "suggested_card") return "Selected from project backlog";
  return goal.selected_by && goal.selected_by !== "local" ? `Selected by ${goal.selected_by}` : "Selected by you";
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
