import { ArrowRight, ExternalLink } from "lucide-react";
import {
  TONE_CLASSES,
  cardIcon,
  confidenceLabel,
  formatTimeAgo,
} from "../digest";

export default function ContextCard({ card, selected = false, onSelect }) {
  const Icon = cardIcon(card);
  const source = card.provenance?.[0];

  return (
    <button
      type="button"
      onClick={() => onSelect?.(card)}
      className={`group flex min-h-[230px] w-full flex-col rounded-lg border bg-white p-3 text-left shadow-sm transition hover:-translate-y-0.5 hover:border-slate-300 hover:shadow-md dark:bg-[#07080a] dark:hover:border-neutral-600 ${
        selected
          ? "border-slate-900 ring-2 ring-slate-900/10 dark:border-white dark:ring-white/15"
          : "border-slate-200 dark:border-neutral-800"
      }`}
    >
      <div className="mb-3 flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2">
          <span className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-md border ${TONE_CLASSES[card.badges?.[0]?.tone || "gray"]}`}>
            <Icon className="h-4 w-4" />
          </span>
          <div className="min-w-0">
            <p className="truncate text-[11px] font-bold uppercase text-slate-400">
              {card.type.replace("_", " ")}
            </p>
            <p className="line-clamp-2 text-sm font-bold leading-5 text-slate-950 dark:text-white">
              {card.title}
            </p>
          </div>
        </div>
        <span className="shrink-0 rounded-md border border-slate-200 px-1.5 py-1 text-[10px] font-bold text-slate-500 dark:border-neutral-800 dark:text-neutral-300">
          {card.attention_score}
        </span>
      </div>

      <div className="mb-3 flex flex-wrap gap-1.5">
        {(card.badges || []).slice(0, 4).map((badge) => (
          <span
            key={`${card.id}:${badge.label}`}
            className={`rounded-md border px-1.5 py-1 text-[10px] font-bold ${TONE_CLASSES[badge.tone] || TONE_CLASSES.gray}`}
          >
            {badge.label}
          </span>
        ))}
      </div>

      <p className="line-clamp-3 text-xs leading-5 text-slate-600 dark:text-neutral-300">
        {card.summary}
      </p>

      <div className="mt-3 border-t border-slate-100 pt-3 dark:border-neutral-900">
        <p className="text-[10px] font-bold uppercase text-slate-400">Why it matters</p>
        <p className="mt-1 line-clamp-2 text-xs leading-5 text-slate-600 dark:text-neutral-300">
          {card.why_it_matters}
        </p>
      </div>

      <div className="mt-auto pt-3">
        <div className="flex items-center justify-between gap-3 text-[11px] font-semibold text-slate-500 dark:text-neutral-400">
          <span>{confidenceLabel(card.confidence)} confidence</span>
          <span>{formatTimeAgo(card.updated_at || card.created_at)}</span>
        </div>
        <div className="mt-2 flex items-center justify-between gap-3 rounded-md bg-slate-50 px-2 py-1.5 text-[11px] font-semibold text-slate-600 dark:bg-black dark:text-neutral-300">
          <span className="min-w-0 truncate">
            {source?.source_label || "Source evidence"}
          </span>
          {source?.source_url ? (
            <ExternalLink className="h-3.5 w-3.5 shrink-0 text-slate-400" />
          ) : (
            <ArrowRight className="h-3.5 w-3.5 shrink-0 text-slate-400 transition group-hover:translate-x-0.5" />
          )}
        </div>
      </div>
    </button>
  );
}
