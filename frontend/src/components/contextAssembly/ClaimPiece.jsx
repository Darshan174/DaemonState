import { CheckCircle2, CircleDashed, AlertTriangle } from "lucide-react";

export default function ClaimPiece({ claim, compact = false }) {
  if (!claim) return null;
  const low = claim.confidence?.level === "low";
  const Icon = claim.status === "accepted" || claim.status === "verified" ? CheckCircle2 : low ? CircleDashed : CheckCircle2;

  return (
    <div className="rounded-md border border-slate-300/80 bg-slate-50/90 px-2.5 py-2 dark:border-white/[0.09] dark:bg-white/[0.035]">
      <div className="flex items-start gap-2">
        <Icon className={`mt-0.5 h-3.5 w-3.5 shrink-0 ${low ? "text-slate-400" : "text-slate-600 dark:text-neutral-300"}`} />
        <div className="min-w-0 flex-1">
          <p className={`${compact ? "text-[11px]" : "text-xs"} font-semibold leading-snug text-slate-800 dark:text-neutral-100`}>
            {claim.text}
          </p>
          {!compact ? (
            <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[10px] font-medium text-slate-500 dark:text-neutral-400">
              <span>{claim.type}</span>
              <span>{claim.confidence?.label || "n/a"}</span>
              <span>{claim.evidenceIds?.length || 0} evidence</span>
              {low ? (
                <span className="inline-flex items-center gap-1 text-amber-600 dark:text-amber-400">
                  <AlertTriangle className="h-3 w-3" />
                  weak
                </span>
              ) : null}
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}
