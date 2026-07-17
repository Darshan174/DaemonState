import { useEffect, useMemo, useState } from "react";
import { Check, Clipboard, FileText, Loader2, PackageCheck, ShieldCheck, XCircle } from "lucide-react";
import { useSearchParams } from "react-router-dom";

import WorkspaceTopicGate from "../components/WorkspaceTopicGate";
import { useContextDigest, usePrepareContext } from "../context-map/api";
import { cleanDisplayText } from "../context-map/digest";
import { useProductWorkspace } from "./useProductWorkspace";

export default function PreparePage() {
  const workspace = useProductWorkspace();
  const digestQuery = useContextDigest(workspace.activeWorkspaceId);
  const prepareContext = usePrepareContext();
  const [searchParams] = useSearchParams();
  const [objective, setObjective] = useState(searchParams.get("objective") || "");
  const [targetModel, setTargetModel] = useState("");
  const [tokenBudget, setTokenBudget] = useState("4000");
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (objective || !digestQuery.data) return;
    const focus = digestQuery.data.oversight?.current_focus?.title;
    const task = (digestQuery.data.cards || []).find((card) => card.category === "task");
    setObjective(cleanDisplayText(focus || task?.title || ""));
  }, [digestQuery.data, objective]);

  if (!workspace.workspacesQuery.isLoading && !workspace.activeWorkspaceId) {
    return <WorkspaceTopicGate workspaces={workspace.workspaces} selectedId={workspace.selectedId} onSelect={workspace.setSelectedId} />;
  }

  const result = prepareContext.data;
  const rendering = result?.manifest?.rendering || {};
  const profile = result?.manifest?.target_model?.profile;
  const resultModel = result?.manifest?.target_model?.name;
  const readiness = Math.round(result?.health_score ?? 0);
  const health = result?.manifest?.context_health || {};
  const readinessStatus = contextReadiness(readiness);
  const selectedTokens = result?.manifest?.token_accounting?.selected_item_tokens;
  const selectedItems = result?.selected_context || [];
  const excludedItems = result?.excluded_context || [];
  const exclusionSummary = useMemo(() => countBy(excludedItems, "reason"), [excludedItems]);

  const submit = async (event) => {
    event.preventDefault();
    setCopied(false);
    await prepareContext.mutateAsync({
      objective: objective.trim(),
      objective_origin: "trusted_human",
      workspace_id: workspace.activeWorkspaceId,
      repo_path: digestQuery.data?.scope?.project_paths?.[0] || undefined,
      target_model: targetModel.trim() || undefined,
      token_budget: Number(tokenBudget),
      mode: "task",
    });
  };

  const copyBrief = async () => {
    await navigator.clipboard.writeText(result.markdown);
    setCopied(true);
  };

  return (
    <div className="relative mx-auto w-full max-w-6xl space-y-6">
      <header>
        <p className="text-xs font-black uppercase tracking-[0.18em] text-[#85857c]">{workspace.activeWorkspace?.name || "Project"}</p>
        <h1 className="mt-2 text-3xl font-black tracking-tight">Prepare</h1>
        <p className="mt-2 max-w-2xl text-sm leading-6 text-[#68685f] dark:text-[#aaa9a0]">Compile the smallest complete, source-backed brief for one concrete agent task.</p>
      </header>

      <div className="grid items-start gap-5 lg:grid-cols-[.85fr_1.15fr]">
        <form onSubmit={submit} className="space-y-5 rounded-2xl border border-[#d8d8cf] bg-[#fbfbf6] p-6 dark:border-[#292925] dark:bg-[#141411]">
          <label className="block">
            <span className="text-xs font-black">Task</span>
            <textarea aria-label="Task" required value={objective} onChange={(event) => setObjective(event.target.value)} rows={5} placeholder="Fix the authentication redirect loop and add focused tests" className="mt-2 w-full resize-none rounded-xl border border-[#d8d8cf] bg-white px-3.5 py-3 text-sm font-semibold leading-6 outline-none focus:border-[#77776e] dark:border-[#33332e] dark:bg-[#0f0f0c]" />
          </label>
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="block">
              <span className="text-xs font-black">Target model label <span className="font-semibold text-[#85857c]">(optional)</span></span>
              <input aria-label="Target model" value={targetModel} onChange={(event) => setTargetModel(event.target.value)} placeholder="e.g. qwen2.5-coder-7b" className="mt-2 h-10 w-full rounded-lg border border-[#d8d8cf] bg-white px-3 text-xs font-semibold outline-none focus:border-[#77776e] dark:border-[#33332e] dark:bg-[#0f0f0c]" />
              <span className="mt-1.5 block text-[9px] font-semibold leading-4 text-[#85857c]">Capabilities are inferred conservatively from this label; provider probing is not connected yet.</span>
            </label>
            <label className="block">
              <span className="text-xs font-black">Context budget</span>
              <input aria-label="Context budget" type="number" min="300" step="100" required value={tokenBudget} onChange={(event) => setTokenBudget(event.target.value)} className="mt-2 h-10 w-full rounded-lg border border-[#d8d8cf] bg-white px-3 text-xs font-semibold outline-none focus:border-[#77776e] dark:border-[#33332e] dark:bg-[#0f0f0c]" />
            </label>
          </div>
          <div className="rounded-xl bg-[#efefe7] p-3 text-[11px] font-semibold leading-5 text-[#68685f] dark:bg-[#252521] dark:text-[#aaa9a0]">
            Context Engine will rank current project evidence, keep provenance, and exclude stale, unsafe, or lower-value context when necessary.
          </div>
          {prepareContext.isError ? <p role="alert" className="text-xs font-bold leading-5 text-red-600">{prepareContext.error?.message || "The context pack could not be prepared."}</p> : null}
          <button type="submit" disabled={prepareContext.isPending || !objective.trim()} className="inline-flex h-11 w-full items-center justify-center gap-2 rounded-xl bg-[#171713] px-4 text-xs font-black text-white disabled:opacity-50 dark:bg-[#d9ff68] dark:text-[#171713]">
            {prepareContext.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <PackageCheck className="h-4 w-4" />}
            {prepareContext.isPending ? "Compiling evidence…" : "Compile context"}
          </button>
        </form>

        <section aria-label="Compiled context result" className="min-h-[420px] rounded-2xl border border-[#d8d8cf] bg-[#fbfbf6] p-6 dark:border-[#292925] dark:bg-[#141411]">
          {!result ? (
            <div className="flex min-h-[370px] flex-col items-center justify-center text-center">
              <FileText className="h-9 w-9 text-[#aaa9a0]" />
              <h2 className="mt-4 text-base font-black">No context pack prepared yet</h2>
              <p className="mt-2 max-w-sm text-xs leading-5 text-[#68685f] dark:text-[#aaa9a0]">Describe one task. You will see exactly what was selected, excluded, and delivered in the brief.</p>
            </div>
          ) : (
            <div className="space-y-5">
              <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
                <div>
                  <div className={`flex items-center gap-2 ${readinessStatus.tone}`}><ShieldCheck className="h-4 w-4" /><span className="text-[10px] font-black uppercase tracking-[0.14em]">{readinessStatus.label}</span></div>
                  <h2 className="mt-2 text-lg font-black">{resultModel || "Default model"}</h2>
                  <p className="mt-1 text-xs font-semibold text-[#68685f] dark:text-[#aaa9a0]">{profileDescription(profile, resultModel)} · {rendering.estimated_tokens ?? selectedTokens ?? "Unknown"} estimated tokens</p>
                </div>
                <button type="button" onClick={copyBrief} className="inline-flex h-9 items-center gap-2 rounded-lg bg-[#171713] px-3 text-[10px] font-black text-white dark:bg-[#d9ff68] dark:text-[#171713]">
                  {copied ? <Check className="h-3.5 w-3.5" /> : <Clipboard className="h-3.5 w-3.5" />}{copied ? "Copied" : "Copy agent brief"}
                </button>
              </div>

              <div className="grid grid-cols-3 gap-2">
                <ResultMetric value={selectedItems.length} label="Selected" />
                <ResultMetric value={excludedItems.length} label="Excluded" />
                <ResultMetric value={`${readiness}%`} label="Readiness" />
              </div>

              {readiness < 70 ? (
                <div role="status" className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-[10px] font-semibold leading-5 text-amber-900 dark:border-amber-900/60 dark:bg-amber-950/30 dark:text-amber-100">
                  <strong>Do not hand this pack off blindly.</strong> {healthSummary(health)}
                </div>
              ) : null}

              <div>
                <h3 className="text-[10px] font-black uppercase tracking-[0.14em] text-[#85857c]">Included because it matters</h3>
                <div className="mt-2 space-y-2">
                  {selectedItems.slice(0, 6).map((item) => (
                    <article key={item.id} className="rounded-lg border border-[#e2e2da] bg-white p-3 dark:border-[#292925] dark:bg-[#0f0f0c]">
                      <p className="text-xs font-black">{cleanDisplayText(item.title) || item.item_type}</p>
                      <p className="mt-1 text-[10px] font-semibold leading-4 text-[#68685f] dark:text-[#aaa9a0]">{humanReason(item.inclusion_reason)} · {item.token_cost || 0} tokens</p>
                    </article>
                  ))}
                </div>
              </div>

              {excludedItems.length ? (
                <details className="rounded-lg border border-[#e2e2da] bg-[#f6f6ef] p-3 dark:border-[#292925] dark:bg-[#1b1b18]">
                  <summary className="cursor-pointer text-[10px] font-black uppercase tracking-[0.12em]">Why {excludedItems.length} items were left out</summary>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {Object.entries(exclusionSummary).map(([reason, count]) => <span key={reason} className="inline-flex items-center gap-1.5 rounded-full bg-white px-2.5 py-1 text-[9px] font-bold dark:bg-[#0f0f0c]"><XCircle className="h-3 w-3 text-[#85857c]" />{humanReason(reason)} {count}</span>)}
                  </div>
                </details>
              ) : null}

              <details className="rounded-lg border border-[#e2e2da] dark:border-[#292925]">
                <summary className="cursor-pointer p-3 text-[10px] font-black uppercase tracking-[0.12em]">Preview compiled brief</summary>
                <pre className="max-h-72 overflow-auto whitespace-pre-wrap border-t border-[#e2e2da] bg-[#0f0f0c] p-4 text-[10px] leading-5 text-[#e8e8e0] dark:border-[#292925]">{result.markdown}</pre>
              </details>
              <p className="text-[10px] font-semibold text-[#85857c]">Nothing was sent to an agent automatically.</p>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

function ResultMetric({ value, label }) {
  return <div className="rounded-xl bg-[#efefe7] p-3 text-center dark:bg-[#252521]"><p className="text-lg font-black">{value}</p><p className="mt-0.5 text-[9px] font-bold uppercase tracking-wide text-[#85857c]">{label}</p></div>;
}

function countBy(items, key) {
  return items.reduce((counts, item) => ({ ...counts, [item[key] || "not_selected"]: (counts[item[key] || "not_selected"] || 0) + 1 }), {});
}

function profileLabel(profile) {
  return ({ small_coder_model: "Concise small-model profile", general_coder_model: "Structured general-model profile", frontier_coder_model: "Frontier-model profile" })[profile] || "Adaptive model profile";
}

function profileDescription(profile, model) {
  return model && model !== "default"
    ? `${profileLabel(profile)} inferred from label`
    : `Conservative default (${profileLabel(profile).toLowerCase()})`;
}

function contextReadiness(score) {
  if (score >= 70) return { label: "Brief compiled", tone: "text-emerald-700 dark:text-emerald-300" };
  if (score >= 40) return { label: "Brief compiled — review recommended", tone: "text-amber-700 dark:text-amber-300" };
  return { label: "Brief compiled — evidence weak", tone: "text-red-700 dark:text-red-300" };
}

function healthSummary(health) {
  const reasons = (health.reasons || []).slice(0, 3).map((reason) => humanReason(reason).replaceAll(":", ": "));
  if (reasons.length) return `Readiness is reduced by ${reasons.join(", ").toLowerCase()}.`;
  return "Readiness is below the safe handoff threshold; inspect selected evidence and exclusions first.";
}

function humanReason(value) {
  return String(value || "relevant evidence").replaceAll("_", " ").replace(/^./, (letter) => letter.toUpperCase());
}
