import { useState } from "react";
import { ExternalLink, GitBranch, ShieldCheck, X } from "lucide-react";
import AgentPackBuilder from "./AgentPackBuilder";
import {
  STATUS_META,
  TONE_CLASSES,
  cardRelationships,
  confidenceLabel,
} from "../digest";

const TABS = ["Summary", "Evidence", "Relationships", "Agent Pack"];

export default function ContextInspector({ card, cards = [], links = [], onClose }) {
  const [tab, setTab] = useState("Summary");
  const relationships = cardRelationships(card, cards, links);

  if (!card) {
    return (
      <aside className="hidden w-[360px] shrink-0 border-l border-slate-200 bg-white p-4 dark:border-neutral-800 dark:bg-[#07080a] lg:block">
        <div className="flex h-full items-center justify-center rounded-lg border border-dashed border-slate-200 text-center text-sm font-semibold text-slate-400 dark:border-neutral-800 dark:text-neutral-500">
          Select a card
        </div>
      </aside>
    );
  }

  const status = STATUS_META[card.status] || STATUS_META.active;

  return (
    <aside className="flex min-h-0 w-full shrink-0 flex-col border-t border-slate-200 bg-white dark:border-neutral-800 dark:bg-[#07080a] lg:w-[390px] lg:border-l lg:border-t-0">
      <div className="border-b border-slate-200 p-4 dark:border-neutral-800">
        <div className="mb-3 flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="text-[11px] font-bold uppercase text-slate-400">Inspector</p>
            <h2 className="mt-1 line-clamp-2 text-base font-black text-slate-950 dark:text-white">
              {card.title}
            </h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-slate-400 transition hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-black dark:hover:text-white lg:hidden"
            aria-label="Close inspector"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="flex flex-wrap gap-1.5">
          <span className={`rounded-md border px-1.5 py-1 text-[10px] font-bold ${TONE_CLASSES[status.tone] || TONE_CLASSES.gray}`}>
            {status.label}
          </span>
          <span className="rounded-md border border-slate-200 bg-slate-50 px-1.5 py-1 text-[10px] font-bold text-slate-600 dark:border-neutral-800 dark:bg-black dark:text-neutral-300">
            {confidenceLabel(card.confidence)} confidence
          </span>
          <span className="rounded-md border border-slate-200 bg-slate-50 px-1.5 py-1 text-[10px] font-bold text-slate-600 dark:border-neutral-800 dark:bg-black dark:text-neutral-300">
            {relationships.length} relationships
          </span>
        </div>
      </div>

      <div className="border-b border-slate-200 px-3 py-2 dark:border-neutral-800">
        <div className="grid grid-cols-4 gap-1 rounded-lg bg-slate-100 p-1 dark:bg-black">
          {TABS.map((item) => (
            <button
              key={item}
              type="button"
              onClick={() => setTab(item)}
              className={`rounded-md px-2 py-1.5 text-[10px] font-bold transition ${
                tab === item
                  ? "bg-white text-slate-950 shadow-sm dark:bg-neutral-900 dark:text-white"
                  : "text-slate-500 hover:text-slate-900 dark:text-neutral-400 dark:hover:text-white"
              }`}
            >
              {item}
            </button>
          ))}
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        {tab === "Summary" && <SummaryTab card={card} />}
        {tab === "Evidence" && <EvidenceTab card={card} />}
        {tab === "Relationships" && <RelationshipsTab relationships={relationships} />}
        {tab === "Agent Pack" && <AgentPackBuilder card={card} cards={cards} links={links} />}
      </div>
    </aside>
  );
}

function SummaryTab({ card }) {
  return (
    <div className="space-y-4">
      <InspectorBlock label="Summary">
        <p>{card.summary}</p>
      </InspectorBlock>
      <InspectorBlock label="Why it matters">
        <p>{card.why_it_matters}</p>
      </InspectorBlock>
      <InspectorBlock label="Suggested next action">
        <p>{card.next_action}</p>
      </InspectorBlock>
      <div className="grid grid-cols-2 gap-2">
        <Metric label="Attention" value={card.attention_score} />
        <Metric label="Authority" value={confidenceLabel(card.authority_weight)} />
      </div>
    </div>
  );
}

function EvidenceTab({ card }) {
  const provenance = card.provenance || [];
  return (
    <div className="space-y-3">
      {provenance.map((source, index) => (
        <div
          key={`${source.source_label}:${index}`}
          className="rounded-lg border border-slate-200 bg-white p-3 dark:border-neutral-800 dark:bg-black"
        >
          <div className="mb-2 flex items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="text-[10px] font-bold uppercase text-slate-400">{source.source_type}</p>
              <p className="mt-0.5 truncate text-xs font-bold text-slate-900 dark:text-white">
                {source.source_label}
              </p>
            </div>
            {source.source_url ? (
              <a
                href={source.source_url}
                target="_blank"
                rel="noreferrer"
                className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md border border-slate-200 text-slate-500 transition hover:bg-slate-50 hover:text-slate-900 dark:border-neutral-800 dark:text-neutral-300 dark:hover:bg-neutral-900 dark:hover:text-white"
                aria-label="Open source"
              >
                <ExternalLink className="h-3.5 w-3.5" />
              </a>
            ) : null}
          </div>
          {source.excerpt ? (
            <p className="rounded-md bg-slate-50 px-2 py-2 text-xs leading-5 text-slate-600 dark:bg-neutral-950 dark:text-neutral-300">
              {source.excerpt}
            </p>
          ) : (
            <p className="text-xs font-semibold text-slate-400">No excerpt available.</p>
          )}
        </div>
      ))}
    </div>
  );
}

function RelationshipsTab({ relationships }) {
  if (!relationships.length) {
    return (
      <div className="rounded-lg border border-dashed border-slate-200 p-5 text-center text-xs font-semibold text-slate-400 dark:border-neutral-800 dark:text-neutral-500">
        No visible relationships.
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {relationships.map((relationship) => (
        <div
          key={relationship.id}
          className="rounded-lg border border-slate-200 bg-white p-3 dark:border-neutral-800 dark:bg-black"
        >
          <div className="flex items-center gap-2">
            <GitBranch className="h-3.5 w-3.5 shrink-0 text-slate-400" />
            <p className="min-w-0 truncate text-xs font-bold text-slate-900 dark:text-white">
              {relationship.label}
            </p>
          </div>
          <p className="mt-2 line-clamp-2 text-xs leading-5 text-slate-500 dark:text-neutral-400">
            {relationship.direction === "out" ? "To" : "From"}: {relationship.otherCard?.title || "Hidden card"}
          </p>
          <div className="mt-2 flex items-center gap-2 text-[10px] font-bold text-slate-400">
            <ShieldCheck className="h-3 w-3" />
            {confidenceLabel(relationship.confidence)} confidence
          </div>
        </div>
      ))}
    </div>
  );
}

function InspectorBlock({ label, children }) {
  return (
    <section>
      <p className="mb-1 text-[10px] font-bold uppercase text-slate-400">{label}</p>
      <div className="text-sm leading-6 text-slate-700 dark:text-neutral-300">
        {children}
      </div>
    </section>
  );
}

function Metric({ label, value }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 dark:border-neutral-800 dark:bg-black">
      <p className="text-[10px] font-bold uppercase text-slate-400">{label}</p>
      <p className="mt-1 text-sm font-black text-slate-950 dark:text-white">{value}</p>
    </div>
  );
}
