import { AlertTriangle, CircleDashed, LockKeyhole, ShieldCheck } from "lucide-react";
import { MODEL_TYPE_META } from "../../graph/contextAssembly";
import FragmentBlock from "./FragmentBlock";

export default function AssembledModel({ model, selectedFragmentId, onSelectFragment }) {
  if (!model) return null;
  const meta = MODEL_TYPE_META[model.type] || MODEL_TYPE_META.area;
  const missingCount = model.missingContext?.length || 0;

  return (
    <div className="rounded-lg border border-slate-200/80 bg-white/92 p-3 dark:border-white/[0.09] dark:bg-neutral-950/92">
      <div className="mb-3 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-[10px] font-bold uppercase tracking-wide text-slate-400">Assembled model</p>
          <h3 className="mt-0.5 truncate text-sm font-black text-slate-950 dark:text-white">{model.name}</h3>
          <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[10px] font-bold">
            <span className="rounded-full px-2 py-0.5 text-white" style={{ backgroundColor: meta.color }}>{meta.label}</span>
            <span className="rounded-full bg-slate-100 px-2 py-0.5 text-slate-600 dark:bg-white/[0.06] dark:text-neutral-300">
              {model.completeness.label} complete
            </span>
            <span className="rounded-full bg-slate-100 px-2 py-0.5 text-slate-600 dark:bg-white/[0.06] dark:text-neutral-300">
              {model.confidence.label} confidence
            </span>
          </div>
        </div>
        {model.status === "blocked" ? <AlertTriangle className="h-4 w-4 shrink-0 text-amber-600" /> : model.status === "active" ? <ShieldCheck className="h-4 w-4 shrink-0 text-emerald-600" /> : <CircleDashed className="h-4 w-4 shrink-0 text-slate-400" />}
      </div>

      <div className="mb-3 h-1.5 overflow-hidden rounded-full bg-slate-100 dark:bg-white/[0.06]">
        <div className="h-full rounded-full" style={{ width: model.completeness.label, backgroundColor: meta.color }} />
      </div>

      <div className="grid grid-cols-2 gap-1.5">
        {model.fragments.slice(0, 10).map((fragment) => (
          <button
            key={fragment.id}
            type="button"
            onClick={() => onSelectFragment?.(fragment.id)}
            className="min-w-0 text-left"
          >
            <FragmentBlock fragment={fragment} compact selected={fragment.id === selectedFragmentId} />
          </button>
        ))}
        {model.missingContext?.slice(0, 3).map((missing) => (
          <div key={missing} className="flex min-h-8 items-center gap-1.5 rounded-md border border-dashed border-slate-300/80 bg-slate-50/60 px-2 text-[10px] font-semibold text-slate-400 dark:border-white/[0.12] dark:bg-white/[0.025]">
            <CircleDashed className="h-3 w-3 shrink-0" />
            <span className="truncate">{missing}</span>
          </div>
        ))}
      </div>

      <div className="mt-3 flex items-center justify-between text-[10px] font-semibold text-slate-500 dark:text-neutral-400">
        <span>{model.claims.length} claims</span>
        <span>{model.fragments.length} fragments</span>
        <span className={missingCount ? "text-amber-600 dark:text-amber-400" : ""}>{missingCount} gaps</span>
        <span className={model.conflicts.length ? "text-red-600 dark:text-red-400" : ""}>{model.conflicts.length} conflicts</span>
        {model.confidence.level === "high" ? <LockKeyhole className="h-3 w-3 text-emerald-600" /> : null}
      </div>
    </div>
  );
}
