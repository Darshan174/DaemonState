import { useState, useRef, useEffect } from "react";
import { Sparkles, Search, ChevronRight, FileText, Loader2 } from "lucide-react";

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
  const inputRef = useRef(null);

  useEffect(() => { inputRef.current?.focus(); }, []);

  async function handleSubmit(e) {
    e?.preventDefault();
    const q = question.trim();
    if (!q) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const res = await fetch("/api/query", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: q }),
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
    setQuestion(s);
    setTimeout(() => inputRef.current?.form?.requestSubmit(), 0);
  }

  const hasResult = result || loading || error;

  return (
    <div className="max-w-2xl mx-auto flex flex-col gap-8">
      {/* Header */}
      <div className={hasResult ? "hidden" : ""}>
        <div className="flex items-center gap-2 mb-3">
          <div className="w-8 h-8 rounded-xl bg-brand-600 flex items-center justify-center shadow-sm shadow-brand-600/30">
            <Sparkles className="w-4 h-4 text-white" />
          </div>
          <h1 className="text-xl font-bold text-slate-900 dark:text-white">Ask Context Engine</h1>
        </div>
        <p className="text-sm text-slate-500 dark:text-slate-400 leading-relaxed">
          Ask anything grounded in your knowledge graph. Every answer cites the exact source it came from.
        </p>
      </div>

      {/* Search form */}
      <form onSubmit={handleSubmit}>
        <div className={`relative flex items-center bg-white dark:bg-slate-800 border rounded-2xl transition-all shadow-sm ${
          hasResult
            ? "border-slate-200 dark:border-slate-700"
            : "border-slate-200 dark:border-slate-700 shadow-[0_4px_24px_rgba(0,0,0,0.06)] dark:shadow-[0_4px_24px_rgba(0,0,0,0.3)]"
        }`}>
          <Search className="absolute left-4 w-4 h-4 text-slate-400 shrink-0" />
          <input
            ref={inputRef}
            type="text"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="Ask about your startup knowledge…"
            className="flex-1 pl-11 pr-4 py-3.5 bg-transparent text-sm font-medium text-slate-900 dark:text-slate-100 placeholder:text-slate-400 focus:outline-none rounded-2xl"
          />
          <button
            type="submit"
            disabled={loading || !question.trim()}
            className="mr-2 shrink-0 flex items-center gap-2 px-4 py-2 bg-brand-600 hover:bg-brand-500 disabled:opacity-40 text-white text-sm font-bold rounded-xl transition-all"
          >
            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />}
            Ask
          </button>
        </div>
      </form>

      {/* Suggestions (only when no result) */}
      {!hasResult && (
        <div className="space-y-3">
          <p className="text-[11px] font-bold uppercase tracking-widest text-slate-400">Try asking</p>
          <div className="grid sm:grid-cols-2 gap-2">
            {SUGGESTIONS.map((s) => (
              <button
                key={s}
                onClick={() => { setQuestion(s); setTimeout(() => handleSubmit(), 0); }}
                className="group flex items-center gap-3 p-3.5 rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 hover:border-brand-300 dark:hover:border-brand-600 hover:bg-brand-50 dark:hover:bg-brand-900/20 text-left transition-all"
              >
                <span className="shrink-0 w-6 h-6 rounded-lg bg-brand-50 dark:bg-brand-900/40 flex items-center justify-center">
                  <ChevronRight className="w-3 h-3 text-brand-500" />
                </span>
                <span className="text-sm text-slate-700 dark:text-slate-300 group-hover:text-brand-700 dark:group-hover:text-brand-300 transition-colors leading-snug">{s}</span>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="p-4 rounded-xl bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800/40">
          <p className="text-sm font-medium text-red-700 dark:text-red-300">{error}</p>
        </div>
      )}

      {/* Loading shimmer */}
      {loading && (
        <div className="space-y-3 animate-pulse">
          <div className="h-4 bg-slate-100 dark:bg-slate-700 rounded-lg w-3/4" />
          <div className="h-4 bg-slate-100 dark:bg-slate-700 rounded-lg w-full" />
          <div className="h-4 bg-slate-100 dark:bg-slate-700 rounded-lg w-5/6" />
        </div>
      )}

      {/* Result */}
      {result && !loading && (
        <div className="space-y-4">
          {/* Question echo */}
          <div className="flex items-start gap-3">
            <div className="w-7 h-7 rounded-full bg-slate-200 dark:bg-slate-700 flex items-center justify-center shrink-0 mt-0.5">
              <span className="text-[10px] font-black text-slate-500">Q</span>
            </div>
            <p className="text-sm font-semibold text-slate-700 dark:text-slate-300 pt-1">{question}</p>
          </div>

          {/* Answer */}
          {result.answer && (
            <div className="ml-10 rounded-2xl bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 p-5 shadow-sm">
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
              <p className="text-sm text-slate-800 dark:text-slate-200 leading-relaxed whitespace-pre-wrap">{result.answer}</p>
            </div>
          )}

          {/* Cited components */}
          {result.components?.length > 0 && (
            <div className="ml-10 rounded-2xl bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 p-5 shadow-sm">
              <p className="text-[11px] font-bold uppercase tracking-widest text-slate-400 mb-3">
                {result.components.length} cited facts
              </p>
              <div className="space-y-2">
                {result.components.map((c, i) => (
                  <div key={c.id || i} className="flex items-start gap-3 p-3 rounded-xl bg-slate-50 dark:bg-slate-900/60 border border-slate-100 dark:border-slate-700/50">
                    <span className="w-5 h-5 rounded-md bg-brand-100 dark:bg-brand-900/40 flex items-center justify-center text-[10px] font-bold text-brand-700 dark:text-brand-300 shrink-0 mt-0.5">
                      {i + 1}
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="text-xs font-bold text-slate-800 dark:text-slate-200 leading-snug">{c.value || c.name}</p>
                      {c.value && c.name && c.value !== c.name && (
                        <p className="text-[11px] text-slate-400 mt-0.5">{c.name}</p>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Sources */}
          {result.sources?.length > 0 && (
            <div className="ml-10 rounded-2xl bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 p-5 shadow-sm">
              <p className="text-[11px] font-bold uppercase tracking-widest text-slate-400 mb-3">Sources</p>
              <div className="space-y-1.5">
                {result.sources.map((s, i) => (
                  <div key={i} className="flex items-center gap-2.5 text-xs text-slate-600 dark:text-slate-400">
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
        <div className="pt-4 border-t border-slate-100 dark:border-slate-800">
          <p className="text-[11px] font-bold uppercase tracking-widest text-slate-400 mb-2">Recent questions</p>
          <div className="space-y-0.5">
            {history.map((h, i) => (
              <button
                key={i}
                onClick={() => { setQuestion(h.question); setResult(h); }}
                className="block w-full text-left text-xs text-slate-500 dark:text-slate-400 hover:text-slate-800 dark:hover:text-slate-200 py-2 px-3 rounded-lg hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors truncate"
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
