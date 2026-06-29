import { useEffect, useMemo, useState } from "react";
import { Check, Clipboard, FileJson } from "lucide-react";
import {
  buildAgentPacket,
  estimateTokens,
  packetMarkdown,
  relatedCards,
} from "../digest";

export default function AgentPackBuilder({ card, cards = [], links = [] }) {
  const related = useMemo(() => relatedCards(card, cards, links), [card, cards, links]);
  const defaultIds = useMemo(() => {
    const ids = new Set(card ? [card.id] : []);
    related.slice(0, 5).forEach((item) => ids.add(item.id));
    return ids;
  }, [card, related]);
  const [includedIds, setIncludedIds] = useState(defaultIds);
  const [copied, setCopied] = useState(null);

  useEffect(() => {
    setIncludedIds(defaultIds);
  }, [defaultIds]);

  const candidates = useMemo(() => [card, ...related].filter(Boolean), [card, related]);
  const includedCards = candidates.filter((item) => includedIds.has(item.id));
  const excludedCards = candidates.filter((item) => !includedIds.has(item.id));
  const packet = useMemo(
    () => buildAgentPacket({ selectedCard: card, includedCards, excludedCards }),
    [card, includedCards, excludedCards],
  );
  const tokenEstimate = estimateTokens(includedCards);

  function toggle(id) {
    setIncludedIds((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function copy(kind) {
    const text = kind === "json"
      ? JSON.stringify(packet, null, 2)
      : packetMarkdown(packet);
    await navigator.clipboard.writeText(text);
    setCopied(kind);
    window.setTimeout(() => setCopied(null), 1200);
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="text-xs font-black text-slate-950 dark:text-white">Context Pack</p>
          <p className="mt-0.5 text-[11px] font-semibold text-slate-500 dark:text-neutral-400">
            {includedCards.length} included · {tokenEstimate} tokens est.
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <button
            type="button"
            onClick={() => copy("json")}
            className="inline-flex h-8 items-center gap-1.5 rounded-md border border-slate-200 px-2 text-[11px] font-bold text-slate-600 transition hover:bg-slate-50 dark:border-neutral-800 dark:text-neutral-300 dark:hover:bg-black"
          >
            {copied === "json" ? <Check className="h-3.5 w-3.5" /> : <FileJson className="h-3.5 w-3.5" />}
            JSON
          </button>
          <button
            type="button"
            onClick={() => copy("markdown")}
            className="inline-flex h-8 items-center gap-1.5 rounded-md border border-slate-200 px-2 text-[11px] font-bold text-slate-600 transition hover:bg-slate-50 dark:border-neutral-800 dark:text-neutral-300 dark:hover:bg-black"
          >
            {copied === "markdown" ? <Check className="h-3.5 w-3.5" /> : <Clipboard className="h-3.5 w-3.5" />}
            Markdown
          </button>
        </div>
      </div>

      <div>
        <p className="mb-2 text-[10px] font-bold uppercase text-slate-400">Included</p>
        <div className="space-y-2">
          {candidates.map((item) => (
            <label
              key={item.id}
              className="flex items-start gap-2 rounded-lg border border-slate-200 bg-white px-2.5 py-2 text-left dark:border-neutral-800 dark:bg-black"
            >
              <input
                type="checkbox"
                checked={includedIds.has(item.id)}
                onChange={() => toggle(item.id)}
                className="mt-0.5 rounded border-slate-300 text-slate-900 focus:ring-slate-900 dark:border-neutral-700"
              />
              <span className="min-w-0">
                <span className="block truncate text-xs font-bold text-slate-900 dark:text-white">
                  {item.title}
                </span>
                <span className="mt-0.5 block line-clamp-2 text-[11px] leading-4 text-slate-500 dark:text-neutral-400">
                  {whyIncluded(item)}
                </span>
              </span>
            </label>
          ))}
        </div>
      </div>

      <div>
        <p className="mb-2 text-[10px] font-bold uppercase text-slate-400">Missing</p>
        {packet.missing_context.length ? (
          <ul className="space-y-1.5">
            {packet.missing_context.map((item) => (
              <li key={item} className="rounded-md bg-amber-50 px-2 py-1.5 text-[11px] font-semibold leading-4 text-amber-800 dark:bg-amber-950/35 dark:text-amber-200">
                {item}
              </li>
            ))}
          </ul>
        ) : (
          <p className="rounded-md bg-emerald-50 px-2 py-1.5 text-[11px] font-semibold text-emerald-800 dark:bg-emerald-950/35 dark:text-emerald-200">
            No missing context flagged.
          </p>
        )}
      </div>
    </div>
  );
}

function whyIncluded(card) {
  if (card.status === "blocked") return "Included because it blocks future work.";
  if (card.status === "conflict") return "Included because conflicting context needs resolution.";
  if (card.type === "decision") return "Included because it constrains implementation choices.";
  if (card.type === "agent_session") return "Included as prior agent attempt context.";
  return card.why_it_matters || "Included as related source-backed context.";
}
