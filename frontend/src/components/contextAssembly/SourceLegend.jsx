import { CircleDashed, LockKeyhole, Unlink } from "lucide-react";
import { MODEL_TYPE_META, SOURCE_TEXTURE_META } from "../../graph/contextAssembly";

export default function SourceLegend() {
  return (
    <div className="pointer-events-auto w-64 rounded-lg border border-slate-200/80 bg-white/90 p-3 text-xs shadow-sm backdrop-blur-xl dark:border-white/[0.09] dark:bg-neutral-950/90">
      <p className="mb-2 text-[10px] font-black uppercase tracking-wide text-slate-400">Assembly legend</p>
      <div className="space-y-3">
        <section>
          <p className="mb-1.5 text-[10px] font-bold uppercase text-slate-400">Model hue</p>
          <div className="grid grid-cols-2 gap-1">
            {Object.entries(MODEL_TYPE_META).slice(0, 6).map(([type, meta]) => (
              <div key={type} className="flex items-center gap-1.5">
                <span className="h-3 w-3 rounded-sm" style={{ backgroundColor: meta.color }} />
                <span className="truncate text-[10px] font-semibold text-slate-600 dark:text-neutral-300">{meta.label}</span>
              </div>
            ))}
          </div>
        </section>
        <section>
          <p className="mb-1.5 text-[10px] font-bold uppercase text-slate-400">Source texture</p>
          <div className="grid grid-cols-2 gap-1">
            {Object.entries(SOURCE_TEXTURE_META).slice(0, 5).map(([type, meta]) => (
              <div key={type} className="flex items-center gap-1.5">
                <span
                  className="h-3 w-5 rounded-sm border border-slate-300"
                  style={{
                    backgroundColor: "#f8fafc",
                    backgroundImage:
                      meta.pattern === "stripe"
                        ? "repeating-linear-gradient(135deg, #64748b 0 1px, transparent 1px 5px)"
                        : meta.pattern === "dot"
                          ? "radial-gradient(#64748b 1px, transparent 1px)"
                          : meta.pattern === "split"
                            ? "linear-gradient(90deg, #64748b 0 40%, transparent 40%)"
                            : "none",
                    backgroundSize: meta.pattern === "dot" ? "6px 6px" : undefined,
                  }}
                />
                <span className="truncate text-[10px] font-semibold text-slate-600 dark:text-neutral-300">{meta.label}</span>
              </div>
            ))}
          </div>
        </section>
        <section className="space-y-1 text-[10px] font-semibold text-slate-500 dark:text-neutral-400">
          <p className="flex items-center gap-1.5"><CircleDashed className="h-3 w-3" /> Empty slot = missing evidence</p>
          <p className="flex items-center gap-1.5"><LockKeyhole className="h-3 w-3" /> Solid join = verified</p>
          <p className="flex items-center gap-1.5"><Unlink className="h-3 w-3" /> Loose join = inferred or weak</p>
        </section>
      </div>
    </div>
  );
}
