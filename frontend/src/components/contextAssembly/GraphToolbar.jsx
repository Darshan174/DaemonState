import { AlertTriangle, ArrowRight, CircleDashed, FileText, GitBranch, Search, ShieldCheck, SlidersHorizontal } from "lucide-react";

export default function GraphToolbar({
  workspaceName,
  stats,
  search,
  onSearchChange,
  onSearchEnter,
  mode,
  onModeChange,
  onToggleRefine,
  activeFilterCount = 0,
}) {
  const modes = [
    ["overview", "Overview"],
    ["assembly", "Assembly"],
    ["explore", "Explore"],
  ];
  const health = stats?.health || {
    label: "No context",
    tone: "slate",
    summary: "Add sources to create evidence-backed claims.",
  };

  return (
    <div className="pointer-events-auto w-fit max-w-[calc(100vw-1.5rem)] rounded-lg border border-slate-200/80 bg-white/92 p-2 shadow-[0_16px_45px_rgba(15,23,42,0.08)] backdrop-blur-xl dark:border-white/[0.09] dark:bg-neutral-950/92">
      <div className="flex flex-wrap items-center gap-2">
        <div className="min-w-0">
          <h2 className="text-sm font-black text-slate-900 dark:text-white">Context Assembly</h2>
          <p className="text-[10px] font-semibold text-slate-400">Evidence to claims to models</p>
        </div>
        <div className="flex rounded-lg border border-slate-200/80 bg-slate-100/80 p-0.5 dark:border-white/[0.08] dark:bg-white/[0.04]">
          {modes.map(([value, label]) => (
            <button
              key={value}
              type="button"
              onClick={() => onModeChange?.(value)}
              className={`rounded-md px-2.5 py-1 text-[11px] font-bold transition-colors ${
                mode === value
                  ? "bg-slate-900 text-white dark:bg-white dark:text-slate-900"
                  : "text-slate-500 hover:text-slate-900 dark:text-neutral-400 dark:hover:text-white"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-1.5 rounded-lg border border-slate-200/70 bg-slate-50/80 px-2 py-1.5 text-[10px] font-bold text-slate-500 dark:border-white/[0.07] dark:bg-white/[0.03] dark:text-neutral-400">
        {[
          ["Sources", stats?.sources || 0],
          ["Evidence", stats?.fragments || 0],
          ["Claims", stats?.claims || 0],
          ["Models", stats?.models || 0],
        ].map(([label, value], index) => (
          <div key={label} className="flex items-center gap-1.5">
            {index > 0 ? <ArrowRight className="h-3 w-3 text-slate-300 dark:text-neutral-600" /> : null}
            <span className="text-slate-900 dark:text-white">{value}</span>
            <span>{label}</span>
          </div>
        ))}
      </div>

      {workspaceName ? (
        <div className="mt-2 flex w-fit max-w-full items-center gap-1.5 rounded-lg border border-slate-300/60 bg-slate-50 px-2 py-1 text-[10px] font-bold text-slate-600 dark:border-white/[0.08] dark:bg-white/[0.035] dark:text-neutral-300">
          <ShieldCheck className="h-3.5 w-3.5 shrink-0" />
          <span className="shrink-0">Workspace</span>
          <span className="truncate text-slate-900 dark:text-white">{workspaceName}</span>
        </div>
      ) : null}

      <div className="mt-2 flex items-center gap-2 rounded-lg border border-slate-200/70 bg-white/80 px-2 py-1.5 text-[10px] font-bold dark:border-white/[0.07] dark:bg-white/[0.025]">
        <HealthIcon tone={health.tone} />
        <div className="min-w-0">
          <p className="text-[9px] uppercase tracking-wide text-slate-400">Context health</p>
          <p className="truncate text-xs text-slate-900 dark:text-white">{health.label}</p>
        </div>
        <p className="max-w-[16rem] truncate text-slate-500 dark:text-neutral-400">{health.summary}</p>
      </div>

      <div className="mt-2 grid grid-cols-2 gap-1.5 text-[10px] font-bold text-slate-500 sm:grid-cols-4">
        <Metric icon={ShieldCheck} label="models" value={stats?.models || 0} />
        <Metric icon={CircleDashed} label="gaps" value={stats?.missingModels || 0} tone={stats?.missingModels ? "amber" : "slate"} />
        <Metric icon={GitBranch} label="weak" value={stats?.weakRelationships || 0} tone={stats?.weakRelationships ? "amber" : "slate"} />
        <Metric icon={AlertTriangle} label="conflicts" value={stats?.conflicts || 0} tone={stats?.conflicts ? "red" : "slate"} />
      </div>

      <div className="mt-2 flex items-center gap-2">
        <div className="relative min-w-0 flex-1">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-400" />
          <input
            type="text"
            value={search}
            onChange={(event) => onSearchChange?.(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") onSearchEnter?.();
            }}
            placeholder="Search evidence, claims, models..."
            className="h-8 w-full rounded-lg border border-slate-200/80 bg-white/90 pl-8 pr-2 text-xs font-semibold text-slate-700 outline-none transition placeholder:text-slate-400 focus:border-slate-400 dark:border-white/[0.09] dark:bg-white/[0.045] dark:text-neutral-200"
          />
        </div>
        <button
          type="button"
          onClick={onToggleRefine}
          className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-slate-200/80 px-2.5 text-xs font-bold text-slate-600 hover:bg-slate-50 dark:border-white/[0.09] dark:text-neutral-300 dark:hover:bg-white/[0.055]"
        >
          <SlidersHorizontal className="h-3.5 w-3.5" />
          Refine
          {activeFilterCount ? <span className="rounded-full bg-slate-900 px-1.5 py-0.5 text-[9px] text-white dark:bg-white dark:text-black">{activeFilterCount}</span> : null}
        </button>
      </div>
    </div>
  );
}

function HealthIcon({ tone = "slate" }) {
  const toneClass = {
    red: "bg-red-100 text-red-600 dark:bg-red-950/40 dark:text-red-300",
    amber: "bg-amber-100 text-amber-600 dark:bg-amber-950/40 dark:text-amber-300",
    emerald: "bg-emerald-100 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300",
    slate: "bg-slate-100 text-slate-500 dark:bg-white/[0.06] dark:text-neutral-300",
  }[tone] || "bg-slate-100 text-slate-500 dark:bg-white/[0.06] dark:text-neutral-300";
  const Icon = tone === "red" ? AlertTriangle : tone === "amber" ? CircleDashed : tone === "emerald" ? ShieldCheck : FileText;

  return (
    <span className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-lg ${toneClass}`}>
      <Icon className="h-3.5 w-3.5" />
    </span>
  );
}

function Metric({ icon: Icon, label, value, tone = "slate" }) {
  const toneClass = tone === "red" ? "text-red-500" : tone === "amber" ? "text-amber-500" : "text-slate-500";
  return (
    <div className="flex items-center gap-1.5 rounded-md border border-slate-200/70 bg-slate-50/80 px-2 py-1 dark:border-white/[0.07] dark:bg-white/[0.03]">
      <Icon className={`h-3 w-3 ${toneClass}`} />
      <span className="text-slate-900 dark:text-white">{value}</span>
      <span>{label}</span>
    </div>
  );
}
