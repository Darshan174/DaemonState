import { useState, useRef, useEffect } from "react";
import {
  ChevronRight,
  ExternalLink,
  FileText,
  Loader2,
  Search,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
} from "lucide-react";
import { useWorkspaces } from "../api/hooks";
import { resolveWorkspaceId, useWorkspaceSelection } from "../context/WorkspaceContext";

const SUGGESTIONS = [
  "What is blocking our launch?",
  "Which customer problems are still unresolved?",
  "What did our AI agents already try?",
  "Which features have the strongest customer signal?",
];

export default function QueryView() {
  const [question, setQuestion] = useState("");
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [history, setHistory] = useState([]);
  const [topK, setTopK] = useState(8);
  const [minConfidence, setMinConfidence] = useState(0);
  const [hybrid, setHybrid] = useState(true);
  const inputRef = useRef(null);
  const { selectedId } = useWorkspaceSelection();
  const { data: workspaces = [] } = useWorkspaces();
  const activeWorkspaceId = resolveWorkspaceId(workspaces, selectedId);
  const activeWorkspace = activeWorkspaceId
    ? workspaces.find((w) => w.id === activeWorkspaceId) || null
    : null;

  useEffect(() => { inputRef.current?.focus(); }, []);

  async function handleSubmit(e, overrideQuestion) {
    e?.preventDefault();
    const q = (overrideQuestion || question).trim();
    if (!q) return;
    if (overrideQuestion) setQuestion(overrideQuestion);
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const body = {
        question: q,
        top_k: topK,
        min_confidence: minConfidence,
        hybrid,
      };
      if (activeWorkspaceId) body.workspace_id = activeWorkspaceId;
      const res = await fetch("/api/query", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setResult(data);
      setHistory((prev) => [{ question: q, ...data }, ...prev].slice(0, 10));
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  function askSuggestion(s) {
    handleSubmit(null, s);
  }

  const hasResult = result || loading || error;

  return (
    <div className="relative z-10 mx-auto flex max-w-3xl flex-col gap-6">
      <div className={hasResult ? "hidden" : ""}>
        <div className="mb-4 flex items-center gap-2">
          <div className="flex h-9 w-9 items-center justify-center rounded-md bg-[#171713] dark:bg-[#d9ff68]">
            <Sparkles className="w-4 h-4 text-white" />
          </div>
          <div>
            <p className="eyebrow">Grounded query</p>
            <h1 className="text-2xl font-semibold text-slate-950 dark:text-white">Ask Context Engine</h1>
          </div>
        </div>
        <p className="max-w-xl text-sm leading-relaxed text-slate-500 dark:text-neutral-400">
          Ask anything grounded in your knowledge graph. Every answer cites the exact source it came from.
        </p>
      </div>

      <form onSubmit={handleSubmit}>
        <div className={`relative flex items-center rounded-lg border transition-all ${
          hasResult
            ? "border-[#d9d9d0] bg-[#fbfbf6] dark:border-[#292925] dark:bg-[#141411]"
            : "border-[#bdbdb4] bg-[#fbfbf6] shadow-[0_16px_42px_rgba(23,23,19,0.06)] dark:border-[#3a3a34] dark:bg-[#141411] dark:shadow-none"
        }`}>
          <Search className="absolute left-4 h-4 w-4 shrink-0 text-slate-400" />
          <input
            ref={inputRef}
            type="text"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="Ask about your startup knowledge…"
            className="flex-1 rounded-lg bg-transparent py-3.5 pl-11 pr-3 text-sm font-medium text-slate-900 placeholder:text-slate-400 focus:outline-none dark:text-neutral-100"
          />
          <button
            type="submit"
            disabled={loading || !question.trim()}
            className="mr-1.5 flex shrink-0 items-center gap-2 rounded-md bg-brand-600 px-3.5 py-2 text-sm font-bold text-white transition-all hover:bg-brand-500 disabled:opacity-40"
          >
            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />}
            Ask
          </button>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          {activeWorkspace ? (
            <span className="inline-flex items-center gap-1.5 rounded-lg border border-brand-500/20 bg-brand-500/10 px-2.5 py-1 text-[11px] font-bold text-brand-700 dark:text-brand-300">
              <ShieldCheck className="h-3.5 w-3.5" />
              {activeWorkspace.name}
            </span>
          ) : null}
          <span className="pill-control inline-flex items-center gap-1.5 px-2.5 py-1 text-[11px] font-bold">
            <SlidersHorizontal className="h-3.5 w-3.5" />
            Retrieval
          </span>
          <select
            value={topK}
            onChange={(e) => setTopK(Number(e.target.value))}
            className="pill-control px-2 py-1 text-[11px] font-semibold"
          >
            <option value={4}>Top 4</option>
            <option value={8}>Top 8</option>
            <option value={12}>Top 12</option>
            <option value={20}>Top 20</option>
          </select>
          <select
            value={minConfidence}
            onChange={(e) => setMinConfidence(Number(e.target.value))}
            className="pill-control px-2 py-1 text-[11px] font-semibold"
          >
            <option value={0}>Any confidence</option>
            <option value={0.5}>50%+</option>
            <option value={0.7}>70%+</option>
            <option value={0.85}>85%+</option>
          </select>
          <label className="pill-control inline-flex items-center gap-1.5 px-2.5 py-1 text-[11px] font-semibold">
            <input
              type="checkbox"
              checked={hybrid}
              onChange={(e) => setHybrid(e.target.checked)}
              className="rounded border-slate-300 text-brand-600 focus:ring-brand-500"
            />
            Hybrid
          </label>
        </div>
      </form>

      {/* Suggestions (only when no result) */}
      {!hasResult && (
        <div className="space-y-3">
          <p className="text-[11px] font-bold uppercase tracking-widest text-slate-400">Try asking</p>
          <div className="grid gap-2 sm:grid-cols-2">
            {SUGGESTIONS.map((s) => (
              <button
                key={s}
                onClick={() => askSuggestion(s)}
                className="group panel-subtle flex items-center gap-3 p-3.5 text-left transition-all hover:border-brand-400/50 hover:bg-brand-500/10"
              >
                <span className="shrink-0 w-6 h-6 rounded-lg bg-brand-50 dark:bg-brand-900/40 flex items-center justify-center">
                  <ChevronRight className="w-3 h-3 text-brand-500" />
                </span>
                <span className="text-sm leading-snug text-slate-700 transition-colors group-hover:text-brand-700 dark:text-neutral-300 dark:group-hover:text-brand-300">{s}</span>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-4 dark:border-red-800/40 dark:bg-red-900/20">
          <p className="text-sm font-medium text-red-700 dark:text-red-300">{error}</p>
        </div>
      )}

      {/* Loading shimmer */}
      {loading && (
        <div className="space-y-3 animate-pulse">
          <div className="h-4 bg-slate-100 dark:bg-black rounded-lg w-3/4" />
          <div className="h-4 bg-slate-100 dark:bg-black rounded-lg w-full" />
          <div className="h-4 bg-slate-100 dark:bg-black rounded-lg w-5/6" />
        </div>
      )}

      {/* Result */}
      {result && !loading && (
        <div className="space-y-4">
          {/* Question echo */}
          <div className="flex items-start gap-3">
            <div className="w-7 h-7 rounded-full bg-slate-200 dark:bg-black flex items-center justify-center shrink-0 mt-0.5">
              <span className="text-[10px] font-black text-slate-500">Q</span>
            </div>
            <p className="text-sm font-semibold text-slate-700 dark:text-neutral-300 pt-1">{question}</p>
          </div>

          {/* Answer */}
          {result.answer && (
          <div className="panel ml-10 p-5">
              <div className="flex items-center gap-2 mb-3">
                <div className="w-5 h-5 rounded-md bg-brand-600 flex items-center justify-center shrink-0">
                  <Sparkles className="w-3 h-3 text-white" />
                </div>
                <span className="text-[11px] font-bold uppercase tracking-widest text-slate-400">Answer</span>
                {result.confidence != null && (
                  <span className="ml-auto text-[10px] font-bold px-2 py-0.5 rounded-full bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400">
                    {Math.round(result.confidence * 100)}% confidence
                  </span>
                )}
              </div>
              <p className="text-sm text-slate-800 dark:text-neutral-200 leading-relaxed whitespace-pre-wrap">{result.answer}</p>
            </div>
          )}

          {/* Facts used */}
          {result.trace?.facts_used?.length > 0 && (
            <div className="panel ml-10 p-5">
              <p className="text-[11px] font-bold uppercase tracking-widest text-slate-400 mb-3">
                Facts used ({result.trace.facts_used.length})
              </p>
              <div className="space-y-2">
                {result.trace.facts_used.map((c) => (
                  <div key={c.component_id} className="panel-subtle flex items-start gap-3 p-3">
                    <span className="w-5 h-5 rounded-md bg-brand-100 dark:bg-brand-900/40 flex items-center justify-center text-[10px] font-bold text-brand-700 dark:text-brand-300 shrink-0 mt-0.5">
                      {c.rank}
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="text-xs font-bold text-slate-800 dark:text-neutral-200 leading-snug">{c.value || c.name}</p>
                      <p className="mt-0.5 text-[11px] text-slate-400">
                        {c.model_name} / score {Number(c.score).toFixed(2)} / {Math.round(c.confidence * 100)}% confidence
                      </p>
                      {c.source_url ? (
                        <a
                          href={c.source_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="mt-1 inline-flex items-center gap-1 text-[11px] font-semibold text-brand-600 hover:text-brand-700 dark:text-brand-400"
                        >
                          Source <ExternalLink className="h-3 w-3" />
                        </a>
                      ) : null}
                    </div>
                  </div>
                ))}
              </div>
              {result.trace.relationships_used?.length > 0 && (
                <div className="mt-4 border-t border-slate-100 pt-3 dark:border-neutral-800">
                  <p className="mb-2 text-[11px] font-bold uppercase tracking-widest text-slate-400">
                    Relationship expansion ({result.trace.relationships_used.length})
                  </p>
                  <div className="space-y-1.5">
                    {result.trace.relationships_used.slice(0, 5).map((rel) => (
                      <div key={rel.id} className="panel-subtle px-3 py-2 text-[11px] text-slate-600 dark:text-neutral-300">
                        <span className="font-bold">{rel.relationship_type.replaceAll("_", " ")}</span>
                        {rel.evidence ? <span className="block text-slate-400">{rel.evidence}</span> : null}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {result.trace?.facts_used?.length === 0 && result.components?.length > 0 && (
            <div className="panel ml-10 p-5">
              <p className="text-[11px] font-bold uppercase tracking-widest text-slate-400 mb-3">
                Cited facts ({result.components.length})
              </p>
              <div className="space-y-2">
                {result.components.map((c, i) => (
                  <div key={c.id || i} className="panel-subtle flex items-start gap-3 p-3">
                    <span className="w-5 h-5 rounded-md bg-brand-100 dark:bg-brand-900/40 flex items-center justify-center text-[10px] font-bold text-brand-700 dark:text-brand-300 shrink-0 mt-0.5">
                      {i + 1}
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="text-xs font-bold text-slate-800 dark:text-neutral-200 leading-snug">{c.value || c.name}</p>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Sources */}
          {result.sources?.length > 0 && (
            <div className="panel ml-10 p-5">
              <p className="text-[11px] font-bold uppercase tracking-widest text-slate-400 mb-3">Sources</p>
              <div className="space-y-1.5">
                {result.sources.map((s, i) => (
                  <div key={i} className="flex items-center gap-2.5 text-xs text-slate-600 dark:text-neutral-400">
                    <FileText className="w-3.5 h-3.5 text-slate-400 shrink-0" />
                    <span className="truncate">{s.url || s.author || s.type || s.external_id || JSON.stringify(s)}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* History */}
      {history.length > 0 && !loading && (
      <div className="border-t border-slate-200/80 pt-4 dark:border-white/[0.08]">
          <p className="text-[11px] font-bold uppercase tracking-widest text-slate-400 mb-2">Recent questions</p>
          <div className="space-y-0.5">
            {history.map((h, i) => (
              <button
                key={i}
                onClick={() => { setQuestion(h.question); setResult(h); }}
                className="block w-full truncate rounded-lg px-3 py-2 text-left text-xs text-slate-500 transition-colors hover:bg-slate-100/80 hover:text-slate-800 dark:text-neutral-400 dark:hover:bg-white/[0.045] dark:hover:text-slate-200"
              >
                {h.question}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
