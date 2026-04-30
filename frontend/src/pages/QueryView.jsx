import { useState, useRef, useEffect } from "react";

export default function QueryView() {
  const [question, setQuestion] = useState("");
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [history, setHistory] = useState([]);
  const inputRef = useRef(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  async function handleSubmit(e) {
    e.preventDefault();
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
      setHistory((prev) => [{ question: q, ...data }, ...prev].slice(0, 20));
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="max-w-3xl mx-auto">
      <h2 className="text-lg font-bold text-slate-900 dark:text-white mb-1">Ask Context Engine</h2>
      <p className="text-sm text-slate-500 dark:text-slate-400 mb-6">
        Ask a natural language question and get answers grounded in your knowledge graph.
      </p>

      <form onSubmit={handleSubmit} className="mb-8">
        <div className="flex gap-2">
          <input
            ref={inputRef}
            type="text"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="What is the Starter Plan pricing?"
            className="flex-1 px-4 py-3 bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-xl text-sm font-medium text-slate-900 dark:text-slate-100 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-brand-500/40 focus:border-brand-500 transition-all"
          />
          <button
            type="submit"
            disabled={loading || !question.trim()}
            className="px-6 py-3 bg-slate-900 dark:bg-white text-white dark:text-slate-900 text-sm font-bold rounded-xl hover:bg-slate-800 dark:hover:bg-slate-200 disabled:opacity-50 transition-all flex items-center gap-2"
          >
            {loading ? (
              <div className="w-4 h-4 border-2 border-white/20 border-t-white dark:border-slate-900/20 dark:border-t-slate-900 rounded-full animate-spin" />
            ) : (
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
              </svg>
            )}
            Ask
          </button>
        </div>
      </form>

      {error && (
        <div className="mb-6 p-4 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800/40 rounded-xl">
          <p className="text-sm font-medium text-red-700 dark:text-red-300">{error}</p>
        </div>
      )}

      {result && (
        <div className="space-y-6">
          <div className="bg-white dark:bg-slate-800 rounded-2xl border border-slate-200 dark:border-slate-700 p-6">
            <div className="flex items-center gap-3 mb-4">
              <span className="text-xs font-bold uppercase tracking-widest text-slate-400">Answer</span>
              {result.confidence != null && (
                <span className="text-xs font-bold px-2.5 py-0.5 rounded-full bg-brand-100 dark:bg-brand-900/30 text-brand-700 dark:text-brand-300">
                  {Math.round(result.confidence * 100)}% confidence
                </span>
              )}
            </div>
            <p className="text-sm text-slate-800 dark:text-slate-200 leading-relaxed whitespace-pre-wrap">
              {result.answer}
            </p>
          </div>

          {result.components?.length > 0 && (
            <div className="bg-white dark:bg-slate-800 rounded-2xl border border-slate-200 dark:border-slate-700 p-6">
              <p className="text-xs font-bold uppercase tracking-widest text-slate-400 mb-3">
                Cited Components ({result.components.length})
              </p>
              <div className="space-y-2">
                {result.components.map((c, i) => (
                  <div
                    key={c.id || i}
                    className="flex items-start gap-3 p-3 rounded-xl bg-slate-50 dark:bg-slate-900/50"
                  >
                    <span className="w-5 h-5 rounded-md bg-brand-100 dark:bg-brand-900/40 flex items-center justify-center text-[10px] font-bold text-brand-700 dark:text-brand-300 shrink-0 mt-0.5">
                      {i + 1}
                    </span>
                    <div className="min-w-0">
                      <p className="text-xs font-bold text-slate-700 dark:text-slate-300">{c.name}</p>
                      <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5 line-clamp-2">{c.value}</p>
                      {c.confidence != null && (
                        <span className="text-[10px] text-slate-400 mt-1 inline-block">
                          {Math.round(c.confidence * 100)}% conf
                        </span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {result.sources?.length > 0 && (
            <div className="bg-white dark:bg-slate-800 rounded-2xl border border-slate-200 dark:border-slate-700 p-6">
              <p className="text-xs font-bold uppercase tracking-widest text-slate-400 mb-3">
                Sources
              </p>
              <div className="space-y-1.5">
                {result.sources.map((s, i) => (
                  <div key={i} className="text-xs text-slate-600 dark:text-slate-400 flex items-center gap-2">
                    <span className="w-1 h-1 rounded-full bg-slate-400 shrink-0" />
                    {s.url || s.author || s.type || s.external_id || JSON.stringify(s)}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {!result && !loading && !error && (
        <div className="text-center py-16">
          <div className="w-12 h-12 rounded-2xl bg-slate-100 dark:bg-slate-800 flex items-center justify-center mx-auto mb-4">
            <svg className="w-6 h-6 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09zM18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.455 2.456L21.75 6l-1.036.259a3.375 3.375 0 00-2.455 2.456zM16.894 20.567L16.5 21.75l-.394-1.183a2.25 2.25 0 00-1.423-1.423L13.5 18.75l1.183-.394a2.25 2.25 0 001.423-1.423l.394-1.183.394 1.183a2.25 2.25 0 001.423 1.423l1.183.394-1.183.394a2.25 2.25 0 00-1.423 1.423z" />
            </svg>
          </div>
          <p className="text-sm font-medium text-slate-500 dark:text-slate-400">Ask a question to get started</p>
          <p className="text-xs text-slate-400 dark:text-slate-500 mt-1">Results include answers, cited components, and sources</p>
        </div>
      )}

      {history.length > 0 && !loading && (
        <div className="mt-10 pt-6 border-t border-slate-200 dark:border-slate-700">
          <p className="text-xs font-bold uppercase tracking-widest text-slate-400 mb-3">Recent Queries</p>
          <div className="space-y-1">
            {history.map((h, i) => (
              <button
                key={i}
                onClick={() => { setQuestion(h.question); setResult(h); }}
                className="block w-full text-left text-xs text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200 py-1.5 px-3 rounded-lg hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors truncate"
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
