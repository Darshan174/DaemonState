import { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  Check,
  CheckCircle2,
  ChevronRight,
  Clipboard,
  Code2,
  FileCheck2,
  GitBranch,
  Loader2,
  PackageCheck,
  Play,
  RefreshCw,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { useWorkspaces } from "../api/hooks";
import WorkspaceTopicGate from "../components/WorkspaceTopicGate";
import { resolveWorkspaceId, useWorkspaceSelection } from "../context/WorkspaceContext";
import { usePrepareContext } from "../context-map/api";

const DEFAULT_BUDGET = "8000";
const REPO_PATH_KEY = "ce:context-repo-path";

const LANE_LABELS = {
  instructions: "Governing instructions",
  code_and_tests: "Code and tests",
  decisions_and_invariants: "Decisions and invariants",
  blockers_and_questions: "Blockers and questions",
  prior_failures: "Prior attempts",
  verification: "Verification",
};

export default function PrepareContextPage() {
  const { selectedId, setSelectedId } = useWorkspaceSelection();
  const workspacesQuery = useWorkspaces();
  const workspaces = workspacesQuery.data || [];
  const workspaceId = resolveWorkspaceId(workspaces, selectedId);
  const activeWorkspace = workspaces.find((workspace) => workspace.id === workspaceId);
  const prepare = usePrepareContext();
  const [objective, setObjective] = useState("");
  const [repoPath, setRepoPath] = useState(readStoredRepoPath);
  const [targetModel, setTargetModel] = useState("");
  const [tokenBudget, setTokenBudget] = useState(DEFAULT_BUDGET);
  const [validationError, setValidationError] = useState("");
  const errorRef = useRef(null);

  const multipleWorkspacesNeedSelection = workspaces.length > 1 && !workspaceId;
  const errorMessage = validationError || formatPrepareError(prepare.error);

  useEffect(() => {
    if (errorMessage) errorRef.current?.focus();
  }, [errorMessage]);

  function submit(event) {
    event.preventDefault();
    const normalizedObjective = objective.trim();
    const normalizedRepoPath = repoPath.trim();
    const parsedBudget = Number(tokenBudget);
    if (!normalizedObjective) {
      setValidationError("Describe the objective for the next agent run.");
      return;
    }
    if (!normalizedRepoPath) {
      setValidationError("Enter the local repository path the compiler should inspect.");
      return;
    }
    if (!Number.isInteger(parsedBudget) || parsedBudget < 300) {
      setValidationError("Token budget must be a whole number of at least 300.");
      return;
    }

    setValidationError("");
    storeRepoPath(normalizedRepoPath);
    prepare.mutate({
      objective: normalizedObjective,
      workspace_id: workspaceId || null,
      repo_path: normalizedRepoPath,
      target_model: targetModel.trim() || null,
      token_budget: parsedBudget,
    });
  }

  if (multipleWorkspacesNeedSelection) {
    return (
      <div className="relative z-10 mx-auto max-w-5xl">
        <WorkspaceTopicGate
          workspaces={workspaces}
          selectedId={selectedId}
          onSelect={setSelectedId}
        />
      </div>
    );
  }

  return (
    <div className="app-page relative z-10 mx-auto max-w-6xl pb-14">
      <section className="overflow-hidden rounded-md border border-[#d9d9d0] bg-[#fbfbf6] dark:border-[#292925] dark:bg-[#141411]">
        <div className="grid gap-0 lg:grid-cols-[0.92fr_1.08fr]">
          <div className="relative overflow-hidden border-b border-[#292925] bg-[#171713] px-6 py-8 text-white lg:border-b-0 lg:border-r lg:px-8 lg:py-10 dark:bg-[#0d0d0b]">
            <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_18%_10%,rgba(217,255,104,0.16),transparent_34%),radial-gradient(circle_at_90%_85%,rgba(255,255,255,0.055),transparent_32%)]" />
            <div className="relative">
              <span className="inline-flex items-center gap-2 rounded-full border border-white/15 bg-white/[0.06] px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-[#d9ff68]">
                <Sparkles className="h-3.5 w-3.5" />
                Prepare next run
              </span>
              <h1 className="mt-5 text-3xl font-semibold leading-tight sm:text-4xl">
                Compile the evidence your next agent actually needs.
              </h1>
              <p className="mt-4 max-w-lg text-sm leading-7 text-slate-300">
                Context Engine binds the objective to repository state, current project evidence,
                explicit exclusions, and exact verification commands in one durable context lockfile.
              </p>

              <ol className="mt-8 space-y-4">
                {[
                  ["Capture", "Read the repository and current source-backed project truth."],
                  ["Compile", "Rank instructions, code, decisions, blockers, and prior attempts."],
                  ["Verify", "Review citations, exclusions, health reasons, and exact tests."],
                ].map(([title, detail], index) => (
                  <li key={title} className="flex gap-3">
                    <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-white/15 bg-white/[0.07] text-xs font-black text-[#d9ff68]">
                      {index + 1}
                    </span>
                    <span>
                      <span className="block text-sm font-bold text-white">{title}</span>
                      <span className="mt-0.5 block text-xs leading-5 text-slate-400">{detail}</span>
                    </span>
                  </li>
                ))}
              </ol>
            </div>
          </div>

          <form onSubmit={submit} className="px-6 py-8 sm:px-8 lg:px-10 lg:py-10" noValidate>
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <p className="eyebrow">Execution brief</p>
                <h2 className="mt-2 text-2xl font-semibold text-slate-950 dark:text-white">What should happen next?</h2>
              </div>
              <span className="rounded-md border border-[#d9d9d0] bg-[#f2f2eb] px-2.5 py-1.5 text-[11px] font-semibold text-[#68685f] dark:border-[#292925] dark:bg-[#1b1b18] dark:text-[#b3b3a9]">
                {activeWorkspace?.name || "Repository only"}
              </span>
            </div>

            <div className="mt-7 space-y-5">
              <Field label="Objective" hint={`${objective.length}/2000`}>
                <textarea
                  id="context-objective"
                  aria-label="Objective"
                  value={objective}
                  maxLength={2000}
                  onChange={(event) => setObjective(event.target.value)}
                  placeholder="Fix GitHub pagination without weakening source provenance."
                  className="min-h-28 w-full resize-y rounded-lg border border-slate-200 bg-white px-3.5 py-3 text-sm leading-6 text-slate-950 outline-none transition placeholder:text-slate-400 focus:border-brand-500 focus:ring-4 focus:ring-brand-500/10 dark:border-white/[0.1] dark:bg-white/[0.04] dark:text-white"
                />
              </Field>

              <Field label="Repository path" hint="Read-only inspection during compilation">
                <div className="relative">
                  <Code2 className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                  <input
                    id="context-repo-path"
                    aria-label="Repository path"
                    value={repoPath}
                    onChange={(event) => setRepoPath(event.target.value)}
                    placeholder="/absolute/path/to/repository"
                    className="h-11 w-full rounded-lg border border-slate-200 bg-white pl-10 pr-3.5 font-mono text-sm text-slate-950 outline-none transition placeholder:text-slate-400 focus:border-brand-500 focus:ring-4 focus:ring-brand-500/10 dark:border-white/[0.1] dark:bg-white/[0.04] dark:text-white"
                  />
                </div>
              </Field>

              <div className="grid gap-4 sm:grid-cols-2">
                <Field label="Target model" hint="Optional capability hint">
                  <input
                    id="context-target-model"
                    aria-label="Target model"
                    value={targetModel}
                    onChange={(event) => setTargetModel(event.target.value)}
                    placeholder="e.g. qwen2.5-coder-7b"
                    className="h-11 w-full rounded-lg border border-slate-200 bg-white px-3.5 text-sm text-slate-950 outline-none transition placeholder:text-slate-400 focus:border-brand-500 focus:ring-4 focus:ring-brand-500/10 dark:border-white/[0.1] dark:bg-white/[0.04] dark:text-white"
                  />
                </Field>
                <Field label="Token budget" hint="Minimum 300">
                  <input
                    id="context-token-budget"
                    aria-label="Token budget"
                    type="number"
                    min="300"
                    step="100"
                    value={tokenBudget}
                    onChange={(event) => setTokenBudget(event.target.value)}
                    className="h-11 w-full rounded-lg border border-slate-200 bg-white px-3.5 text-sm text-slate-950 outline-none transition focus:border-brand-500 focus:ring-4 focus:ring-brand-500/10 dark:border-white/[0.1] dark:bg-white/[0.04] dark:text-white"
                  />
                </Field>
              </div>
            </div>

            {errorMessage ? (
              <div
                ref={errorRef}
                role="alert"
                tabIndex={-1}
                className="mt-5 flex items-start gap-2.5 rounded-lg border border-red-200 bg-red-50 px-3.5 py-3 text-sm text-red-700 outline-none focus:ring-4 focus:ring-red-500/15 dark:border-red-900/60 dark:bg-red-950/30 dark:text-red-300"
              >
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                <span>{errorMessage}</span>
              </div>
            ) : null}

            <button
              type="submit"
              disabled={prepare.isPending}
              className="mt-6 inline-flex h-11 w-full items-center justify-center gap-2 rounded-md bg-[#171713] px-5 text-sm font-semibold text-white transition hover:bg-[#36362f] disabled:cursor-wait disabled:opacity-65 dark:bg-[#d9ff68] dark:text-[#171713] dark:hover:bg-[#e8ff9c]"
            >
              {prepare.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
              {prepare.isPending ? "Compiling source-backed context…" : prepare.data ? "Compile again" : "Compile context pack"}
            </button>
          </form>
        </div>
      </section>

      {prepare.data ? (
        <ContextPackResult key={prepare.data.context_pack_id} result={prepare.data} />
      ) : <EmptyResult />}
    </div>
  );
}

function Field({ label, hint, children }) {
  return (
    <label className="block">
      <span className="mb-2 flex items-center justify-between gap-3">
        <span className="text-xs font-bold text-slate-700 dark:text-neutral-200">{label}</span>
        {hint ? <span className="text-[11px] font-medium text-slate-400">{hint}</span> : null}
      </span>
      {children}
    </label>
  );
}

function EmptyResult() {
  return (
    <section className="mt-6 rounded-md border border-dashed border-[#bdbdb4] bg-[#fbfbf6]/65 px-6 py-10 text-center dark:border-[#3a3a34] dark:bg-[#141411]/65">
      <PackageCheck className="mx-auto h-9 w-9 text-[#a2a298] dark:text-[#57574f]" />
      <h2 className="mt-3 text-base font-semibold text-[#171713] dark:text-[#f4f4ec]">No context pack compiled yet</h2>
      <p className="mx-auto mt-1 max-w-xl text-sm leading-6 text-[#68685f] dark:text-[#aaa9a0]">
        The result will show selected evidence, citations, exclusions, definition of done, and verification commands before you hand it to an agent.
      </p>
    </section>
  );
}

function WorkspaceQueryState({ loading = false, error, onRetry }) {
  return (
    <section
      aria-busy={loading || undefined}
      className="app-page relative z-10 mx-auto max-w-3xl rounded-md border border-[#d9d9d0] bg-[#fbfbf6] px-6 py-12 text-center dark:border-[#292925] dark:bg-[#141411]"
    >
      {loading ? <Loader2 className="mx-auto h-7 w-7 animate-spin text-brand-500" /> : <AlertTriangle className="mx-auto h-7 w-7 text-red-500" />}
      <h1 className="mt-4 text-xl font-semibold text-slate-950 dark:text-white">
        {loading ? "Loading workspace evidence…" : "Workspace evidence is unavailable"}
      </h1>
      <p role={error ? "alert" : undefined} className="mx-auto mt-2 max-w-xl text-sm leading-6 text-slate-500 dark:text-neutral-400">
        {loading
          ? "Context preparation will unlock after workspace discovery completes."
          : `${formatPrepareError(error) || "The workspace list could not be loaded."} Repository-only compilation is disabled until this check succeeds.`}
      </p>
      {!loading ? (
        <button type="button" onClick={() => onRetry?.()} className="mt-5 inline-flex h-10 items-center gap-2 rounded-md bg-[#171713] px-4 text-sm font-semibold text-white dark:bg-[#d9ff68] dark:text-[#171713]">
          <RefreshCw className="h-4 w-4" /> Retry workspace discovery
        </button>
      ) : null}
    </section>
  );
}
function ContextPackResult({ result }) {
  const [copied, setCopied] = useState(false);
  const resultHeadingRef = useRef(null);
  const manifest = result.manifest || {};
  const selected = result.selected_context?.length
    ? result.selected_context
    : manifest.selected_context || [];
  const excluded = result.excluded_context?.length
    ? result.excluded_context
    : manifest.excluded_context || [];
  const health = manifest.context_health || {};
  const verification = manifest.verification || {};
  const tokenAccounting = manifest.token_accounting || manifest.rendering || {};
  const groups = useMemo(() => groupSelectedContext(selected), [selected]);

  useEffect(() => {
    resultHeadingRef.current?.focus();
  }, []);

  async function copyMarkdown() {
    await copyText(result.markdown || "");
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1600);
  }

  return (
    <section aria-live="polite" className="mt-6 space-y-5">
      <div className="rounded-md border border-emerald-200 bg-emerald-50/80 p-5 dark:border-emerald-900/50 dark:bg-emerald-950/20">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-start gap-3">
            <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-emerald-600 text-white shadow-sm">
              <CheckCircle2 className="h-5 w-5" />
            </span>
            <div>
              <p className="text-[11px] font-black uppercase tracking-[0.16em] text-emerald-700 dark:text-emerald-400">Context pack ready</p>
              <h2
                ref={resultHeadingRef}
                tabIndex={-1}
                className="mt-1 text-xl font-semibold text-slate-950 outline-none focus:ring-4 focus:ring-emerald-500/10 dark:text-white"
              >
                {manifest.objective || "Compiled execution context"}
              </h2>
              <p className="mt-1 font-mono text-[11px] text-slate-500 dark:text-neutral-400">{result.context_pack_id}</p>
            </div>
          </div>
          <button
            type="button"
            onClick={copyMarkdown}
            className="inline-flex h-10 items-center gap-2 rounded-md border border-emerald-300 bg-white px-4 text-xs font-semibold text-emerald-800 transition hover:bg-emerald-100 dark:border-emerald-800 dark:bg-black dark:text-emerald-300"
          >
            {copied ? <Check className="h-4 w-4" /> : <Clipboard className="h-4 w-4" />}
            {copied ? "Copied" : "Copy compiler markdown"}
          </button>
        </div>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Metric label="Context health" value={`${Math.round(Number(result.health_score ?? health.readiness_score ?? 0))}/100`} icon={ShieldCheck} />
        <Metric label="Selected items" value={selected.length} icon={FileCheck2} />
        <Metric label="Excluded items" value={excluded.length} icon={AlertTriangle} />
        <Metric label="Rendered tokens" value={tokenAccounting.rendered_tokens ?? tokenAccounting.estimated_tokens ?? "—"} icon={Sparkles} />
      </div>

      {health.reasons?.length ? (
        <Panel title="Health reasons" icon={ShieldCheck}>
          <ul className="space-y-2">
            {health.reasons.map((reason, index) => (
              <li key={`${reason.code || reason}-${index}`} className="flex gap-2 text-sm leading-6 text-slate-600 dark:text-neutral-300">
                <ChevronRight className="mt-1.5 h-3.5 w-3.5 shrink-0 text-amber-500" />
                {typeof reason === "string" ? reason : reason.message || reason.code}
              </li>
            ))}
          </ul>
        </Panel>
      ) : null}

      <div className="grid gap-5 lg:grid-cols-[1.25fr_0.75fr]">
        <div className="space-y-5">
          <Panel title="Selected context" icon={PackageCheck}>
            {groups.length ? (
              <div className="space-y-5">
                {groups.map(([lane, items]) => (
                  <div key={lane}>
                    <p className="mb-2 text-[11px] font-black uppercase tracking-[0.14em] text-slate-400">{LANE_LABELS[lane] || humanize(lane)}</p>
                    <div className="space-y-2">
                      {items.map((item) => <ContextItem key={item.id} item={item} />)}
                    </div>
                  </div>
                ))}
              </div>
            ) : <EmptyLine>No context items were selected.</EmptyLine>}
          </Panel>

          <Panel title="Compiler markdown" icon={Code2}>
            <pre className="max-h-[520px] overflow-auto whitespace-pre-wrap rounded-lg border border-slate-200 bg-slate-950 p-4 font-mono text-[12px] leading-6 text-slate-200 dark:border-white/[0.08]">{result.markdown}</pre>
          </Panel>
        </div>

        <div className="space-y-5">
          <Panel title="Definition of done" icon={CheckCircle2}>
            <SimpleList items={verification.acceptance_criteria} empty="No acceptance criteria were inferred." />
          </Panel>
          <Panel title="Verification commands" icon={Play}>
            {verification.commands?.length ? (
              <div className="space-y-2">
                {verification.commands.map((command, index) => (
                  <div key={command.id || index} className="rounded-lg border border-slate-200 bg-slate-50 p-3 dark:border-white/[0.08] dark:bg-white/[0.035]">
                    <code className="block overflow-x-auto whitespace-pre-wrap text-xs font-semibold text-slate-800 dark:text-neutral-200">{command.command || command}</code>
                    {command.purpose ? <p className="mt-2 text-[11px] leading-5 text-slate-500 dark:text-neutral-400">{command.purpose}</p> : null}
                  </div>
                ))}
              </div>
            ) : <EmptyLine>No verification command was inferred.</EmptyLine>}
          </Panel>
          <Panel title="Risks and uncertainties" icon={AlertTriangle}>
            <SimpleList items={[...(manifest.risks || []), ...(manifest.uncertainties || [])]} empty="No explicit risks were supplied." />
          </Panel>
          <Panel title="Excluded context" icon={RefreshCw}>
            {excluded.length ? (
              <div className="space-y-2">
                {excluded.map((item) => (
                  <div key={item.id} className="rounded-lg border border-slate-200 px-3 py-2.5 dark:border-white/[0.08]">
                    <p className="text-sm font-semibold text-slate-800 dark:text-neutral-200">{item.title}</p>
                    <p className="mt-1 text-[11px] font-bold uppercase tracking-wide text-amber-600 dark:text-amber-400">{humanize(item.reason)}</p>
                    {item.reason_detail ? <p className="mt-1 text-xs leading-5 text-slate-500 dark:text-neutral-400">{item.reason_detail}</p> : null}
                  </div>
                ))}
              </div>
            ) : <EmptyLine>No context was excluded.</EmptyLine>}
          </Panel>
        </div>
      </div>
    </section>
  );
}

function Metric({ label, value, icon: Icon }) {
  return (
    <div className="rounded-md border border-[#d9d9d0] bg-[#fbfbf6] p-4 dark:border-[#292925] dark:bg-[#141411]">
      <div className="flex items-center justify-between">
        <p className="text-[11px] font-bold uppercase tracking-wide text-slate-400">{label}</p>
        <Icon className="h-4 w-4 text-brand-500" />
      </div>
      <p className="mt-2 text-2xl font-semibold text-slate-950 dark:text-white">{value}</p>
    </div>
  );
}

function Panel({ title, icon: Icon, children }) {
  return (
    <section className="rounded-md border border-[#d9d9d0] bg-[#fbfbf6] p-5 dark:border-[#292925] dark:bg-[#141411]">
      <div className="mb-4 flex items-center gap-2">
        <Icon className="h-4 w-4 text-brand-500" />
        <h3 className="text-sm font-bold text-slate-950 dark:text-white">{title}</h3>
      </div>
      {children}
    </section>
  );
}

function ContextItem({ item }) {
  const citations = item.citations || (item.citation ? [item.citation] : []);
  return (
    <details className="group rounded-lg border border-slate-200 bg-slate-50/70 open:bg-white dark:border-white/[0.08] dark:bg-white/[0.025] dark:open:bg-white/[0.04]">
      <summary className="cursor-pointer list-none px-3.5 py-3">
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="text-sm font-semibold text-slate-900 dark:text-neutral-100">{item.title}</p>
            <p className="mt-1 line-clamp-2 text-xs leading-5 text-slate-500 dark:text-neutral-400">{item.summary}</p>
          </div>
          <span className="shrink-0 rounded bg-slate-200/70 px-2 py-1 text-[10px] font-black uppercase tracking-wide text-slate-500 dark:bg-white/[0.08] dark:text-neutral-400">{humanize(item.truth_state || item.status || item.item_type)}</span>
        </div>
      </summary>
      <div className="border-t border-slate-200 px-3.5 py-3 dark:border-white/[0.08]">
        <p className="text-[11px] font-bold uppercase tracking-wide text-slate-400">Why selected</p>
        <p className="mt-1 text-xs leading-5 text-slate-600 dark:text-neutral-300">{humanize(item.inclusion_reason) || "Goal relevant"}</p>
        {citations.map((citation, index) => (
          <div key={citation.citation_id || index} className="mt-3 rounded-md border border-indigo-100 bg-indigo-50/60 p-3 dark:border-indigo-900/40 dark:bg-indigo-950/20">
            <p className="text-[10px] font-black uppercase tracking-wide text-indigo-600 dark:text-indigo-300">
              {citation.citation_id || `Citation ${index + 1}`} · rev {citation.source_revision_number ?? "unknown"}
              {citation.start_char != null ? ` · chars ${citation.start_char}-${citation.end_char}` : ""}
            </p>
            <p className="mt-1.5 text-xs leading-5 text-slate-700 dark:text-neutral-300">{citation.quote || "Citation metadata only."}</p>
          </div>
        ))}
      </div>
    </details>
  );
}

function CitationBlock({ citation, index = 0 }) {
  return (
    <div className="mt-3 rounded-md border border-brand-200 bg-brand-50/80 p-3 dark:border-[#4d5326] dark:bg-[#242418]">
      <p className="text-[10px] font-black uppercase tracking-wide text-brand-700 dark:text-brand-300">
        {citation.citation_id || `Citation ${index + 1}`} · rev {citation.source_revision_number ?? "unknown"}
        {citation.start_char != null ? ` · chars ${citation.start_char}-${citation.end_char}` : ""}
      </p>
      <p className="mt-1.5 text-xs leading-5 text-slate-700 dark:text-neutral-300">{citation.quote || "Citation metadata only."}</p>
    </div>
  );
}
function SimpleList({ items = [], empty }) {
  if (!items.length) return <EmptyLine>{empty}</EmptyLine>;
  return (
    <ul className="space-y-2">
      {items.map((item, index) => (
        <li key={item.id || index} className="flex gap-2 text-sm leading-6 text-slate-600 dark:text-neutral-300">
          <ChevronRight className="mt-1.5 h-3.5 w-3.5 shrink-0 text-brand-500" />
          <span>{typeof item === "string" ? item : item.text || item.title || item.message || JSON.stringify(item)}</span>
        </li>
      ))}
    </ul>
  );
}

function EmptyLine({ children }) {
  return <p className="text-sm leading-6 text-slate-400 dark:text-neutral-500">{children}</p>;
}

function groupSelectedContext(items) {
  const groups = new Map();
  items.forEach((item) => {
    const lane = item.lane || fallbackLane(item.item_type);
    groups.set(lane, [...(groups.get(lane) || []), item]);
  });
  return Array.from(groups.entries());
}

function fallbackLane(itemType) {
  if (["file", "repo_state"].includes(itemType)) return "code_and_tests";
  if (["blocker", "risk", "question"].includes(itemType)) return "blockers_and_questions";
  if (itemType === "verification") return "verification";
  if (["decision", "constraint"].includes(itemType)) return "decisions_and_invariants";
  return "instructions";
}

function humanize(value) {
  return String(value || "").replaceAll("_", " ");
}

export function formatPrepareError(error) {
  if (!error) return "";
  const detail = error.detail;
  if (Array.isArray(detail)) {
    return detail.map((item) => item.msg || item.message).filter(Boolean).join(" ") || "The request is invalid.";
  }
  if (detail && typeof detail === "object") {
    return detail.message || detail.code || "The context compiler rejected the request.";
  }
  if (typeof detail === "string") return detail;
  if (error.status >= 500 || error instanceof TypeError) {
    return "The context compiler is unavailable. Your form values are preserved; retry when the service is ready.";
  }
  return error.message || "The context pack could not be compiled.";
}

function readStoredRepoPath() {
  try {
    return localStorage.getItem(REPO_PATH_KEY) || "";
  } catch {
    return "";
  }
}

function storeRepoPath(repoPath) {
  try {
    localStorage.setItem(REPO_PATH_KEY, repoPath);
  } catch {
    // Compilation does not depend on browser storage being available.
  }
}

async function copyText(value) {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(value);
      return;
    } catch {
      // Fall through when browser permissions block the async clipboard API.
    }
  }
  const textArea = document.createElement("textarea");
  textArea.value = value;
  textArea.setAttribute("readonly", "");
  textArea.style.position = "fixed";
  textArea.style.left = "-9999px";
  document.body.appendChild(textArea);
  textArea.select();
  document.execCommand("copy");
  document.body.removeChild(textArea);
}
