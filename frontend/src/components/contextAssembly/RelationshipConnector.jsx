import { Check, GitBranch, HelpCircle, XCircle } from "lucide-react";

export default function RelationshipConnector({ relationship, onAccept, onReject, loading = false }) {
  if (!relationship) return null;
  const tone = relationship.conflict
    ? "border-red-200 bg-red-50 text-red-800 dark:border-red-900/60 dark:bg-red-950/30 dark:text-red-300"
    : relationship.verified
      ? "border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-900/60 dark:bg-emerald-950/30 dark:text-emerald-300"
      : relationship.weak
        ? "border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-900/60 dark:bg-amber-950/30 dark:text-amber-300"
        : "border-slate-200 bg-slate-50 text-slate-700 dark:border-white/[0.08] dark:bg-white/[0.035] dark:text-neutral-200";

  return (
    <div className={`rounded-lg border px-3 py-2 ${tone}`}>
      <div className="flex items-start gap-2">
        <GitBranch className="mt-0.5 h-3.5 w-3.5 shrink-0" />
        <div className="min-w-0 flex-1">
          <div className="flex items-center justify-between gap-2">
            <p className="truncate text-xs font-bold">{relationship.label}</p>
            <span className="shrink-0 text-[10px] font-bold">{relationship.confidence?.label}</span>
          </div>
          {relationship.evidence ? (
            <p className="mt-1 line-clamp-2 text-[11px] leading-snug opacity-80">{relationship.evidence}</p>
          ) : (
            <p className="mt-1 flex items-center gap-1 text-[11px] opacity-70">
              <HelpCircle className="h-3 w-3" />
              No explicit evidence text attached.
            </p>
          )}
          {relationship.weak && !relationship.verified ? (
            <div className="mt-2 flex gap-1.5">
              <button
                type="button"
                disabled={loading}
                onClick={() => onAccept?.(relationship.id)}
                className="inline-flex items-center gap-1 rounded-md bg-white/80 px-2 py-1 text-[10px] font-bold text-slate-700 hover:bg-white disabled:opacity-50 dark:bg-black/30 dark:text-neutral-200"
              >
                <Check className="h-3 w-3" />
                Accept
              </button>
              <button
                type="button"
                disabled={loading}
                onClick={() => onReject?.(relationship.id)}
                className="inline-flex items-center gap-1 rounded-md bg-white/80 px-2 py-1 text-[10px] font-bold text-slate-700 hover:bg-white disabled:opacity-50 dark:bg-black/30 dark:text-neutral-200"
              >
                <XCircle className="h-3 w-3" />
                Reject
              </button>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}
