import { useState } from "react";
import {
  Zap, Network, AlertTriangle, MessageSquare, Package,
  ArrowRight, Loader2, CheckCircle2, XCircle, Copy, Check,
  ChevronRight, Sparkles
} from "lucide-react";

function getAiSettings() {
  try { return JSON.parse(localStorage.getItem("ce_ai_settings") || "{}"); }
  catch { return {}; }
}

const SEV_STYLES = {
  critical: { pill: "bg-red-100 dark:bg-red-900/40 text-red-700 dark:text-red-400 ring-1 ring-red-200 dark:ring-red-800", dot: "bg-red-500" },
  high:     { pill: "bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-400 ring-1 ring-amber-200 dark:ring-amber-800", dot: "bg-amber-500" },
  medium:   { pill: "bg-yellow-100 dark:bg-yellow-900/40 text-yellow-700 dark:text-yellow-400", dot: "bg-yellow-500" },
  low:      { pill: "bg-slate-100 dark:bg-slate-700 text-slate-500 dark:text-slate-400", dot: "bg-slate-400" },
};

const CAT_LABEL = {
  missing_owner:          "Missing owner",
  unimplemented_decision: "No implementation",
  blocked:                "Blocked",
  repeated_failure:       "Repeated failure",
  unactioned_pain:        "Unactioned pain",
  orphaned:               "Isolated",
};

export default function AgentsView() {
  const [gapReport, setGapReport]     = useState(null);
  const [gapLoading, setGapLoading]   = useState(false);
  const [gapError, setGapError]       = useState(null);

  const [contextPack, setContextPack] = useState(null);
  const [packLoading, setPackLoading] = useState(false);
  const [packError, setPackError]     = useState(null);
  const [copied, setCopied]           = useState(false);

  const [relReport, setRelReport]     = useState(null);
  const [relLoading, setRelLoading]   = useState(false);
  const [relError, setRelError]       = useState(null);

  async function callAgent(endpoint, setLoading, setResult, setError) {
    setLoading(true); setResult(null); setError(null);
    const s = getAiSettings();
    try {
      const res = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ api_key: s.api_key || null, model: s.model || null }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setResult(await res.json());
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  }

  async function copyPack() {
    if (!contextPack) return;
    await navigator.clipboard.writeText(contextPack.content);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <div className="max-w-3xl mx-auto space-y-5 pb-12">
      {/* Page header */}
      <div className="mb-2">
        <h1 className="text-xl font-bold text-slate-900 dark:text-white">AI Agents</h1>
        <p className="text-sm text-slate-500 dark:text-slate-400 mt-0.5">
          Five agents that read, connect, reason, detect gaps, and generate action plans from your startup knowledge graph.
        </p>
      </div>

      {/* 1 — Ingestion Agent */}
      <AgentCard
        icon={<Zap className="w-4 h-4" />}
        iconColor="bg-blue-500"
        number="01"
        title="Ingestion Agent"
        tagline="Reads Slack, GitHub, Gmail, Zoom, AI sessions → clean entities"
        examples={["Slack thread → Decision + Task + Risk + Owner", "GitHub PR → Feature + Files + Issue solved", "Agent session → Failed attempts + Next steps"]}
        action={<a href="/app/graph" className="inline-flex items-center gap-1.5 text-sm font-semibold text-slate-600 dark:text-slate-300 hover:text-slate-900 dark:hover:text-white border border-slate-200 dark:border-slate-600 px-4 py-2 rounded-xl hover:bg-slate-50 dark:hover:bg-slate-700 transition-all">Build Graph <ArrowRight className="w-3.5 h-3.5" /></a>}
      />

      {/* 2 — Relationship Agent */}
      <AgentCard
        icon={<Network className="w-4 h-4" />}
        iconColor="bg-violet-500"
        number="02"
        title="Relationship Agent"
        tagline="Finds hidden links between things across all your sources"
        examples={["Gmail complaint → GitHub issue", "Slack decision → caused this PR", "Agent session → solved this bug"]}
        action={
          <RunButton loading={relLoading} onClick={() => callAgent("/api/agents/relationships", setRelLoading, setRelReport, setRelError)} color="violet">
            Find Hidden Links
          </RunButton>
        }
      >
        {relError && <ErrorBanner>{relError}</ErrorBanner>}
        {relReport && <RelationshipResult report={relReport} />}
      </AgentCard>

      {/* 3 — Gap Detector (HERO) */}
      <div className="rounded-2xl border-2 border-red-200 dark:border-red-900/60 bg-white dark:bg-slate-800 shadow-sm overflow-hidden">
        <div className="px-6 py-5 bg-gradient-to-br from-red-50 via-orange-50 to-white dark:from-red-950/40 dark:via-orange-950/20 dark:to-transparent border-b border-red-100 dark:border-red-900/40">
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className="flex items-center gap-2.5 mb-2">
                <div className="w-7 h-7 rounded-xl bg-red-500 flex items-center justify-center shadow-sm shadow-red-500/30">
                  <AlertTriangle className="w-3.5 h-3.5 text-white" />
                </div>
                <span className="text-xs font-bold text-red-500 dark:text-red-400 uppercase tracking-wider">03 · Killer Feature</span>
              </div>
              <h2 className="text-lg font-bold text-slate-900 dark:text-white">Agentic Gap Detector</h2>
              <p className="text-sm text-slate-500 dark:text-slate-400 mt-1 leading-relaxed">
                Scans your entire startup graph — finds what's missing, blocked, duplicated, risky, or ready to ship.
              </p>
              <div className="flex flex-wrap gap-1.5 mt-3">
                {["Features with no owner", "Decisions without implementation", "High-priority issues with no PR", "Repeated AI failures"].map(ex => (
                  <span key={ex} className="text-[10px] font-medium px-2.5 py-1 rounded-full bg-red-100 dark:bg-red-900/40 text-red-700 dark:text-red-400">{ex}</span>
                ))}
              </div>
            </div>
            <RunButton loading={gapLoading} onClick={() => callAgent("/api/agents/gaps", setGapLoading, setGapReport, setGapError)} color="red">
              Run Detector
            </RunButton>
          </div>
        </div>

        {(gapError || gapReport) && (
          <div className="px-6 py-5 space-y-5">
            {gapError && <ErrorBanner>{gapError}</ErrorBanner>}
            {gapReport && <GapResult report={gapReport} />}
          </div>
        )}
      </div>

      {/* 4 — Ask / Strategy Agent */}
      <AgentCard
        icon={<MessageSquare className="w-4 h-4" />}
        iconColor="bg-brand-500"
        number="04"
        title="Ask / Strategy Agent"
        tagline="Ask questions over the full graph, get synthesized answers with citations"
        examples={["What is blocking launch?", "Which customer problems are unresolved?", "What should we build next?", "What did AI agents already try?"]}
        action={<a href="/app/query" className="inline-flex items-center gap-1.5 text-sm font-semibold text-slate-600 dark:text-slate-300 hover:text-slate-900 dark:hover:text-white border border-slate-200 dark:border-slate-600 px-4 py-2 rounded-xl hover:bg-slate-50 dark:hover:bg-slate-700 transition-all">Open Ask AI <ArrowRight className="w-3.5 h-3.5" /></a>}
      />

      {/* 5 — Context Pack Agent */}
      <AgentCard
        icon={<Package className="w-4 h-4" />}
        iconColor="bg-emerald-500"
        number="05"
        title="Context Pack Agent"
        tagline="Generates a perfect handoff prompt for humans or coding agents"
        examples={["Project goal + current state", "Open decisions + blockers", "Past AI attempts + next 5 tasks", "Ready to paste into Replit Agent / Codex / Claude"]}
        action={
          <RunButton loading={packLoading} onClick={() => callAgent("/api/agents/context-pack", setPackLoading, setContextPack, setPackError)} color="emerald">
            Generate Pack
          </RunButton>
        }
      >
        {packError && <ErrorBanner>{packError}</ErrorBanner>}
        {contextPack && <ContextPackResult pack={contextPack} copied={copied} onCopy={copyPack} />}
      </AgentCard>
    </div>
  );
}

/* ── Sub-components ───────────────────────────────────── */

function AgentCard({ icon, iconColor, number, title, tagline, examples, action, children }) {
  return (
    <div className="rounded-2xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 shadow-sm overflow-hidden">
      <div className="px-6 py-5">
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-start gap-3 flex-1 min-w-0">
            <div className={`w-7 h-7 rounded-xl ${iconColor} flex items-center justify-center text-white shadow-sm shrink-0 mt-0.5`}>
              {icon}
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 mb-1">
                <span className="text-[10px] font-bold text-slate-400 uppercase tracking-widest">{number}</span>
                <h2 className="text-base font-bold text-slate-900 dark:text-white">{title}</h2>
              </div>
              <p className="text-sm text-slate-500 dark:text-slate-400">{tagline}</p>
              <div className="flex flex-wrap gap-1.5 mt-2.5">
                {examples.map(ex => (
                  <span key={ex} className="text-[10px] font-medium px-2.5 py-0.5 rounded-full bg-slate-100 dark:bg-slate-700 text-slate-500 dark:text-slate-400">{ex}</span>
                ))}
              </div>
            </div>
          </div>
          <div className="shrink-0">{action}</div>
        </div>
        {children && <div className="mt-4">{children}</div>}
      </div>
    </div>
  );
}

function RunButton({ loading, onClick, color, children }) {
  const colors = {
    red:     "bg-red-500 hover:bg-red-600 shadow-red-500/20",
    violet:  "bg-violet-500 hover:bg-violet-600 shadow-violet-500/20",
    emerald: "bg-emerald-500 hover:bg-emerald-600 shadow-emerald-500/20",
  };
  return (
    <button
      onClick={onClick}
      disabled={loading}
      className={`inline-flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-bold text-white transition-all shadow-sm disabled:opacity-60 ${colors[color] || "bg-brand-600 hover:bg-brand-500 shadow-brand-500/20"}`}
    >
      {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />}
      {loading ? "Running…" : children}
    </button>
  );
}

function ErrorBanner({ children }) {
  return (
    <div className="flex items-start gap-2.5 p-3.5 rounded-xl bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800/40">
      <XCircle className="w-4 h-4 text-red-500 shrink-0 mt-0.5" />
      <p className="text-sm text-red-700 dark:text-red-400">{children}</p>
    </div>
  );
}

function GapResult({ report }) {
  const criticalCount = report.gaps.filter(g => g.severity === "critical").length;
  const highCount = report.gaps.filter(g => g.severity === "high").length;

  return (
    <div className="space-y-5">
      {/* Stat row */}
      <div className="grid grid-cols-4 gap-3">
        {[
          { label: "Entities", value: report.stats.total_entities, color: "text-slate-900 dark:text-white" },
          { label: "Relationships", value: report.stats.total_relationships, color: "text-slate-900 dark:text-white" },
          { label: "Gaps", value: report.gaps.length, color: criticalCount + highCount > 0 ? "text-red-600 dark:text-red-400" : "text-slate-900 dark:text-white" },
          { label: "Isolated", value: report.stats.isolated, color: report.stats.isolated > 0 ? "text-amber-600 dark:text-amber-400" : "text-slate-900 dark:text-white" },
        ].map(s => (
          <div key={s.label} className="rounded-xl bg-slate-50 dark:bg-slate-900/60 border border-slate-100 dark:border-slate-700/50 p-3 text-center">
            <p className={`text-xl font-bold ${s.color}`}>{s.value}</p>
            <p className="text-[10px] text-slate-400 uppercase tracking-wide mt-0.5">{s.label}</p>
          </div>
        ))}
      </div>

      {/* CEO summary */}
      {report.summary && (
        <div className="flex items-start gap-3 p-4 rounded-xl bg-amber-50 dark:bg-amber-900/10 border border-amber-100 dark:border-amber-800/30">
          <Sparkles className="w-4 h-4 text-amber-600 dark:text-amber-400 shrink-0 mt-0.5" />
          <div>
            <p className="text-[10px] font-bold uppercase tracking-widest text-amber-600 dark:text-amber-400 mb-1">CEO Summary</p>
            <p className="text-sm text-amber-900 dark:text-amber-300 leading-relaxed">{report.summary}</p>
          </div>
        </div>
      )}

      {/* Ready / Blocked */}
      {(report.ready_to_ship.length > 0 || report.blocked.length > 0) && (
        <div className="grid sm:grid-cols-2 gap-3">
          {report.ready_to_ship.length > 0 && (
            <div className="rounded-xl bg-emerald-50 dark:bg-emerald-900/10 border border-emerald-100 dark:border-emerald-800/30 p-4">
              <p className="text-[10px] font-bold uppercase tracking-widest text-emerald-600 dark:text-emerald-400 mb-2">Ready to Ship</p>
              <ul className="space-y-1.5">
                {report.ready_to_ship.map((n, i) => (
                  <li key={i} className="flex items-start gap-2 text-xs text-emerald-800 dark:text-emerald-300">
                    <CheckCircle2 className="w-3.5 h-3.5 shrink-0 mt-0.5" />{n}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {report.blocked.length > 0 && (
            <div className="rounded-xl bg-red-50 dark:bg-red-900/10 border border-red-100 dark:border-red-800/30 p-4">
              <p className="text-[10px] font-bold uppercase tracking-widest text-red-600 dark:text-red-400 mb-2">Blocked</p>
              <ul className="space-y-1.5">
                {report.blocked.map((n, i) => (
                  <li key={i} className="flex items-start gap-2 text-xs text-red-800 dark:text-red-300">
                    <XCircle className="w-3.5 h-3.5 shrink-0 mt-0.5" />{n}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {/* Gaps list */}
      {report.gaps.length > 0 && (
        <div>
          <p className="text-[10px] font-bold uppercase tracking-widest text-slate-400 mb-2">Gap Details</p>
          <div className="space-y-2">
            {report.gaps.map((g, i) => {
              const sev = SEV_STYLES[g.severity] || SEV_STYLES.low;
              return (
                <div key={i} className="flex items-start gap-3 p-3.5 rounded-xl bg-slate-50 dark:bg-slate-900/60 border border-slate-100 dark:border-slate-700/50">
                  <div className={`w-2 h-2 rounded-full shrink-0 mt-1.5 ${sev.dot}`} />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap mb-0.5">
                      <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${sev.pill}`}>{g.severity}</span>
                      <span className="text-[10px] text-slate-400">{CAT_LABEL[g.category] || g.category}</span>
                    </div>
                    <p className="text-sm font-semibold text-slate-800 dark:text-slate-200">{g.title}</p>
                    <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5 leading-relaxed">{g.detail}</p>
                    {g.recommendation && (
                      <p className="text-xs font-medium text-brand-600 dark:text-brand-400 mt-1.5 flex items-center gap-1">
                        <ChevronRight className="w-3 h-3 shrink-0" />{g.recommendation}
                      </p>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

function RelationshipResult({ report }) {
  return (
    <div className="space-y-4">
      <p className="text-xs text-slate-500 dark:text-slate-400 italic">{report.message}</p>

      {report.suggested.length > 0 && (
        <div>
          <p className="text-[10px] font-bold uppercase tracking-widest text-slate-400 mb-2">Suggested Relationships</p>
          <div className="space-y-2">
            {report.suggested.map((r, i) => (
              <div key={i} className="flex items-start gap-3 p-3 rounded-xl bg-slate-50 dark:bg-slate-900/60 border border-slate-100 dark:border-slate-700/50">
                <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded-lg shrink-0 mt-0.5 ${r.confidence >= 0.8 ? "bg-emerald-100 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-400" : r.confidence >= 0.6 ? "bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-400" : "bg-slate-100 dark:bg-slate-700 text-slate-500"}`}>
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

      {report.duplicates.length > 0 && (
        <div>
          <p className="text-[10px] font-bold uppercase tracking-widest text-slate-400 mb-2">Potential Duplicates</p>
          <div className="space-y-1.5">
            {report.duplicates.map((d, i) => (
              <div key={i} className="p-3 rounded-xl bg-amber-50 dark:bg-amber-900/10 border border-amber-100 dark:border-amber-800/30">
                <p className="text-xs font-semibold text-amber-800 dark:text-amber-400">{d.entity_a} ↔ {d.entity_b}</p>
                <p className="text-[11px] text-amber-700 dark:text-amber-500 mt-0.5">{d.reason}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {report.suggested.length === 0 && report.duplicates.length === 0 && (
        <p className="text-xs text-slate-400 italic text-center py-4">No hidden relationships found in current graph.</p>
      )}
    </div>
  );
}

function ContextPackResult({ pack, copied, onCopy }) {
  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <p className="text-[10px] font-bold uppercase tracking-widest text-slate-400">
          {pack.entity_count} entities · {pack.generated_at}
        </p>
        <button
          onClick={onCopy}
          className={`flex items-center gap-1.5 text-[11px] font-bold px-3 py-1.5 rounded-lg transition-all ${
            copied
              ? "bg-emerald-100 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-400"
              : "bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-600"
          }`}
        >
          {copied ? <Check className="w-3.5 h-3.5" /> : <Copy className="w-3.5 h-3.5" />}
          {copied ? "Copied!" : "Copy"}
        </button>
      </div>
      <pre className="text-[11px] text-slate-600 dark:text-slate-300 bg-slate-50 dark:bg-slate-900/60 border border-slate-200 dark:border-slate-700 rounded-xl p-4 overflow-x-auto whitespace-pre-wrap leading-relaxed font-mono max-h-72 overflow-y-auto">
        {pack.content}
      </pre>
    </div>
  );
}
