import ContextCard from "./ContextCard";
import { cardsById } from "../digest";

export default function DigestBoard({ digest, selectedCardId, onSelectCard }) {
  const byId = cardsById(digest?.cards || []);
  const clusters = digest?.clusters || [];

  return (
    <div className="grid min-h-0 gap-4 xl:grid-cols-4">
      {clusters.map((cluster) => {
        const cards = (cluster.card_ids || []).map((id) => byId.get(id)).filter(Boolean);
        return (
          <section key={cluster.id} className="min-w-0">
            <div className="mb-3 flex items-end justify-between gap-3 border-b border-slate-200 pb-2 dark:border-neutral-800">
              <div className="min-w-0">
                <h2 className="truncate text-sm font-black text-slate-950 dark:text-white">
                  {cluster.title}
                </h2>
                <p className="mt-0.5 line-clamp-2 text-[11px] leading-4 text-slate-500 dark:text-neutral-400">
                  {cluster.description}
                </p>
              </div>
              <span className="shrink-0 rounded-md bg-slate-100 px-1.5 py-1 text-[10px] font-bold text-slate-500 dark:bg-black dark:text-neutral-300">
                {cards.length}
              </span>
            </div>
            <div className="space-y-3">
              {cards.length ? (
                cards.map((card) => (
                  <ContextCard
                    key={card.id}
                    card={card}
                    selected={card.id === selectedCardId}
                    onSelect={onSelectCard}
                  />
                ))
              ) : (
                <div className="rounded-lg border border-dashed border-slate-200 px-3 py-8 text-center text-xs font-semibold text-slate-400 dark:border-neutral-800 dark:text-neutral-500">
                  No cards
                </div>
              )}
            </div>
          </section>
        );
      })}
    </div>
  );
}
