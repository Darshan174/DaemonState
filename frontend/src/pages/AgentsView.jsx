import { useState } from "react";

function getAiSettings() {
  try { return JSON.parse(localStorage.getItem("ce_ai_settings") || "{}"); }
  catch { return {}; }
}

const SEVERITY_COLOR = {
  critical: "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400",
  high:     "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400",
  medium:   "bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400",
  low:      "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400",
};

const CATEGORY_LABEL = {
  missing_owner:           "Missing Owner",
  unimplemented_decision:  "No Implementation",
  blocked:                 "Blocked",
  repeated_failure:        "Repeated Failure",
  unactioned_pain:         "Unactioned Pain",
  orphaned:                "Isolated",
};

export default function AgentsView() {
  const [gapReport, setGapReport]         = useState(null);
  const [gapLoading, setGapLoading]       = useState(false);
  const [gapError, setGapError]           = useState(null);

  const [contextPack, setContextPack]     = useState(null);
  const [packLoading, setPackLoading]     = useState(false);
  const [packError, setPackError]         = useState(null);
  const [copied, setCopied]               = useState(false);

  const [relReport, setRelReport]         = useState(null);
  const [relLoading, setRelLoading]       = useState(false);
  const [relError, setRelError]           = useState(null);

  async function callAgent(endpoint, setLoading, setResult, setError) {
    setLoading(true);
    setResult(null);
    setError(null);
    const s = getAiSettings();
    try {
      const res = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ api_key: s.api_key || null, model: s.model || null }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setResult(await res.json());
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  function runGaps()    { callAgent("/api/agents/gaps", setGapLoading, setGapReport, setGapError); }
  function runPack()    { callAgent("/api/agents/context-pack", setPackLoading, setContextPack, setPackError); }
  function runRels()    { callAgent("/api/agents/relationships", setRelLoading, setRelReport, setRelError); }

  async function copyPack() {
    if (!contextPack) return;
    await navigator.clipboard.writeText(contextPack.content);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <div className="max-w-4xl mx-auto space-y-6 pb-12">

      {/* Header */}
      <div className="mb-2">
        <h1 className="text-xl font-bold text-slate-900 dark:text-white">AI Agents</h1>
        <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">
          Five agents that read, connect, reason, detect gaps, and generate action plans from your startup knowledge graph.
        </p>
      </div>

      {/* ── 1. Ingestion Agent (status card only) ──────────────────────── */}
      <AgentCard
        number="1"
        title="Ingestion Agent"
        tagline="Reads Slack, GitHub, Gmail, Zoom, AI sessions → clean entities"
        examples={["Slack thread → Decision + Task + Risk + Owner", "GitHub PR → Feature + Files + Issue solved", "Agent session → Failed attempts + Next steps"]}
        color="blue"
        actionLabel="Run via Build Graph"
        onAction={() => window.location.href = "/app/graph"}
        actionVariant="secondary"
      />

      {/* ── 2. Relationship Agent ───────────────────────────────────────── */}
      <AgentCard
        number="2"
        title="Relationship Agent"
        tagline="Finds hidden links between things across sources"
        examples={["Gmail complaint → GitHub issue", "Slack decision → caused this PR", "Agent session → solved this bug"]}
        color="violet"
        actionLabel={relLoading ? "Scanning…" : "Find Hidden Links"}
        onAction={runRels}
        loading={relLoading}
      >
        {relError && <p className="text-xs text-red-500 mt-2">{relError}</p>}
        {relReport && (
          <div className="mt-4 space-y-3">
            <p className="text-xs text-slate-500 dark:text-slate-400 italic">{relReport.message}</p>

            {relReport.suggested.length > 0 && (
              <div>
                <p className="text-[10px] font-bold uppercase tracking-widest text-slate-400 mb-2">Suggested Relationships</p>
                <div className="space-y-2">
                  {relReport.suggested.map((r, i) => (
                    <div key={i} className="flex items-start gap-3 p-2.5 rounded-lg bg-slate-50 dark:bg-slate-900/60 border border-slate-100 dark:border-slate-700/50">
                      <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded shrink-0 ${r.confidence >= 0.8 ? "bg-emerald-100 text-emerald-700" : r.confidence >= 0.6 ? "bg-amber-100 text-amber-700" : "bg-slate-100 text-slate-600"}`}>
                        {Math.round(r.confidence * 100)}%
                      </span>
                      <div className="min-w-0">
                        <p className="text-xs font-semibold text-slate-700 dark:text-slate-300">
                          {r.source_name} <span className="text-slate-400 font-normal">→ {r.relationship_type} →</span> {r.target_name}
                        </p>
                        <p className="text-[11px] text-slate-500 dark:text-slate-400 mt-0.5">{r.reasoning}</p>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {relReport.duplicates.length > 0 && (
              <div>
                <p className="text-[10px] font-bold uppercase tracking-widest text-slate-400 mb-2">Potential Duplicates</p>
                <div className="space-y-1.5">
                  {relReport.duplicates.map((d, i) => (
                    <div key={i} className="p-2.5 rounded-lg bg-amber-50 dark:bg-amber-900/10 border border-amber-100 dark:border-amber-800/30">
                      <p className="text-xs font-semibold text-amber-800 dark:text-amber-400">{d.entity_a} ↔ {d.entity_b}</p>
                      <p className="text-[11px] text-amber-700 dark:text-amber-500 mt-0.5">{d.reason}</p>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {relReport.suggested.length === 0 && relReport.duplicates.length === 0 && (
              <p className="text-xs text-slate-400 italic">No hidden relationships found.</p>
            )}
          </div>
        )}
      </AgentCard>

      {/* ── 3. Gap Detector (HERO) ──────────────────────────────────────── */}
      <div className="rounded-2xl border-2 border-red-200 dark:border-red-900/50 bg-white dark:bg-slate-800 shadow-sm overflow-hidden">
        <div className="px-6 pt-5 pb-4 bg-gradient-to-r from-red-50 to-orange-50 dark:from-red-900/20 dark:to-orange-900/10 border-b border-red-100 dark:border-red-900/30">
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className="flex items-center gap-2 mb-1">
                <span className="w-6 h-6 rounded-full bg-red-500 text-white text-[11px] font-bold flex items-center justify-center shrink-0">3</span>
                <span className="text-[10px] font-bold uppercase tracking-widest text-red-500 dark:text-red-400">Killer Feature</span>
              </div>
              <h2 className="text-base font-bold text-slate-900 dark:text-white">Agentic Gap Detector</h2>
              <p className="text-sm text-slate-600 dark:text-slate-400 mt-0.5">
                Scans your entire startup graph — finds what's missing, blocked, duplicated, risky, or ready to ship.
              </p>
              <div className="flex flex-wrap gap-1.5 mt-2">
                {["Features with no owner", "Decisions with no implementation", "High-priority issues with no PR", "Repeated AI failures"].map(ex => (
                  <span key={ex} className="text-[10px] px-2 py-0.5 rounded-full bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400">{ex}</span>
                ))}
              </div>
            </div>
            <button
              onClick={runGaps}
              disabled={gapLoading}
              className="shrink-0 px-4 py-2 rounded-xl bg-red-500 hover:bg-red-600 disabled:opacity-60 text-white text-sm font-bold transition-colors shadow-sm"
            >
              {gapLoading ? "Scanning…" : "Run Gap Detector"}
            </button>
          </div>
        </div>

        {(gapError || gapReport) && (
          <div className="px-6 py-4 space-y-4">
            {gapError && <p className="text-xs text-red-500">{gapError}</p>}

            {gapReport && (
              <>
                {/* Stats row */}
                <div className="grid grid-cols-4 gap-3">
                  {[
                    { label: "Entities", value: gapReport.stats.total_entities },
                    { label: "Relationships", value: gapReport.stats.total_relationships },
                    { label: "Gaps found", value: gapReport.gaps.length },
                    { label: "Isolated", value: gapReport.stats.isolated },
                  ].map(s => (
                    <div key={s.label} className="rounded-lg bg-slate-50 dark:bg-slate-900/50 p-3 text-center">
                      <p className="text-lg font-bold text-slate-900 dark:text-white">{s.value}</p>
                      <p className="text-[10px] text-slate-400 uppercase tracking-wide">{s.label}</p>
                    </div>
                  ))}
                </div>

                {/* Summary */}
                {gapReport.summary && (
                  <div className="rounded-lg bg-amber-50 dark:bg-amber-900/10 border border-amber-100 dark:border-amber-800/30 px-4 py-3">
                    <p className="text-xs font-semibold text-amber-800 dark:text-amber-400 mb-1">CEO Summary</p>
                    <p className="text-sm text-amber-900 dark:text-amber-300 leading-relaxed">{gapReport.summary}</p>
                  </div>
                )}

                {/* Ready to ship + Blocked */}
                <div className="grid grid-cols-2 gap-3">
                  {gapReport.ready_to_ship.length > 0 && (
                    <div className="rounded-lg bg-emerald-50 dark:bg-emerald-900/10 border border-emerald-100 dark:border-emerald-800/30 px-4 py-3">
                      <p className="text-[10px] font-bold uppercase tracking-widest text-emerald-600 dark:text-emerald-400 mb-2">Ready to Ship</p>
                      <ul className="space-y-1">
                        {gapReport.ready_to_ship.map((name, i) => (
                          <li key={i} className="text-xs text-emerald-800 dark:text-emerald-300 flex items-start gap-1.5">
                            <span className="mt-0.5 shrink-0">✓</span>{name}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {gapReport.blocked.length > 0 && (
                    <div className="rounded-lg bg-red-50 dark:bg-red-900/10 border border-red-100 dark:border-red-800/30 px-4 py-3">
                      <p className="text-[10px] font-bold uppercase tracking-widest text-red-600 dark:text-red-400 mb-2">Blocked</p>
                      <ul className="space-y-1">
                        {gapReport.blocked.map((name, i) => (
                          <li key={i} className="text-xs text-red-800 dark:text-red-300 flex items-start gap-1.5">
                            <span className="mt-0.5 shrink-0">✗</span>{name}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>

                {/* Gap items */}
                {gapReport.gaps.length > 0 && (
                  <div>
                    <p className="text-[10px] font-bold uppercase tracking-widest text-slate-400 mb-2">Gap Details</p>
                    <div className="space-y-2">
                      {gapReport.gaps.map((g, i) => (
                        <div key={i} className="flex items-start gap-3 p-3 rounded-lg bg-slate-50 dark:bg-slate-900/60 border border-slate-100 dark:border-slate-700/50">
                          <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded shrink-0 mt-0.5 ${SEVERITY_COLOR[g.severity] || SEVERITY_COLOR.low}`}>
                            {g.severity}
                          </span>
                          <div className="min-w-0 flex-1">
                            <div className="flex items-center gap-2 flex-wrap">
                              <p className="text-xs font-semibold text-slate-800 dark:text-slate-200">{g.title}</p>
                              <span className="text-[10px] text-slate-400">
                                {CATEGORY_LABEL[g.category] || g.category}
                              </span>
                            </div>
                            <p className="text-[11px] text-slate-500 dark:text-slate-400 mt-0.5">{g.detail}</p>
                            {g.recommendation && (
                              <p className="text-[11px] text-brand-600 dark:text-brand-400 mt-1 font-medium">→ {g.recommendation}</p>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
        )}
      </div>

      {/* ── 4. Ask / Strategy Agent (link to Ask AI) ───────────────────── */}
      <AgentCard
        number="4"
        title="Ask / Strategy Agent"
        tagline="Ask questions over the entire graph, get synthesized answers"
        examples={["What is blocking launch?", "Which customer problems are unresolved?", "What should we build next?", "What did AI agents already try?"]}
        color="brand"
        actionLabel="Open Ask AI"
        onAction={() => window.location.href = "/app/query"}
        actionVariant="secondary"
      />

      {/* ── 5. Context Pack Agent ───────────────────────────────────────── */}
      <AgentCard
        number="5"
        title="Context Pack Agent"
        tagline="Generates a perfect handoff prompt for humans or coding agents"
        examples={["Project goal + current state", "Open decisions + blockers", "Past AI attempts + next 5 tasks", "Ready to paste into Replit Agent / Codex / Claude"]}
        color="emerald"
        actionLabel={packLoading ? "Generating…" : "Generate Context Pack"}
        onAction={runPack}
        loading={packLoading}
      >
        {packError && <p className="text-xs text-red-500 mt-2">{packError}</p>}
        {contextPack && (
          <div className="mt-4">
            <div className="flex items-center justify-between mb-2">
              <p className="text-[10px] font-bold uppercase tracking-widest text-slate-400">
                Context Pack — {contextPack.entity_count} entities — {contextPack.generated_at}
              </p>
              <button
                onClick={copyPack}
                className="text-[11px] font-bold px-3 py-1 rounded-lg bg-emerald-100 hover:bg-emerald-200 dark:bg-emerald-900/30 dark:hover:bg-emerald-900/50 text-emerald-700 dark:text-emerald-400 transition-colors"
              >
                {copied ? "Copied!" : "Copy"}
              </button>
            </div>
            <pre className="text-[11px] text-slate-600 dark:text-slate-300 bg-slate-50 dark:bg-slate-900/60 border border-slate-200 dark:border-slate-700 rounded-xl p-4 overflow-x-auto whitespace-pre-wrap leading-relaxed font-mono max-h-80 overflow-y-auto">
              {contextPack.content}
            </pre>
          </div>
        )}
      </AgentCard>

    </div>
  );
}


function AgentCard({ number, title, tagline, examples, color, actionLabel, onAction, actionVariant = "primary", loading, children }) {
  const colors = {
    blue:    { badge: "bg-blue-500",    btn: "bg-blue-500 hover:bg-blue-600",    pill: "bg-blue-50 dark:bg-blue-900/20 text-blue-700 dark:text-blue-400", border: "border-blue-100 dark:border-blue-900/30" },
    violet:  { badge: "bg-violet-500",  btn: "bg-violet-500 hover:bg-violet-600", pill: "bg-violet-50 dark:bg-violet-900/20 text-violet-700 dark:text-violet-400", border: "border-violet-100 dark:border-violet-900/30" },
    brand:   { badge: "bg-brand-500",   btn: "bg-brand-600 hover:bg-brand-700",  pill: "bg-brand-50 dark:bg-brand-900/20 text-brand-700 dark:text-brand-400", border: "border-brand-100 dark:border-brand-900/30" },
    emerald: { badge: "bg-emerald-500", btn: "bg-emerald-600 hover:bg-emerald-700", pill: "bg-emerald-50 dark:bg-emerald-900/20 text-emerald-700 dark:text-emerald-400", border: "border-emerald-100 dark:border-emerald-900/30" },
  };
  const c = colors[color] || colors.brand;

  return (
    <div className="rounded-2xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 shadow-sm overflow-hidden">
      <div className="px-6 py-5">
        <div className="flex items-start justify-between gap-4">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-1.5">
              <span className={`w-6 h-6 rounded-full ${c.badge} text-white text-[11px] font-bold flex items-center justify-center shrink-0`}>{number}</span>
              <h2 className="text-base font-bold text-slate-900 dark:text-white">{title}</h2>
            </div>
            <p className="text-sm text-slate-500 dark:text-slate-400">{tagline}</p>
            <div className="flex flex-wrap gap-1.5 mt-2">
              {examples.map(ex => (
                <span key={ex} className={`text-[10px] px-2 py-0.5 rounded-full ${c.pill}`}>{ex}</span>
              ))}
            </div>
          </div>
          <button
            onClick={onAction}
            disabled={loading}
            className={`shrink-0 px-4 py-2 rounded-xl text-sm font-bold transition-colors disabled:opacity-60 shadow-sm ${
              actionVariant === "secondary"
                ? "border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-700"
                : `${c.btn} text-white`
            }`}
          >
            {actionLabel}
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}
