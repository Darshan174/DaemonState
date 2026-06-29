import { useMemo, useState } from "react";
import {
  AlertTriangle,
  Bot,
  Check,
  CircleDot,
  Copy,
  ExternalLink,
  FileWarning,
  GitPullRequest,
  Lightbulb,
  Sparkles,
} from "lucide-react";
import {
  buildSessionKnowledgeMap,
  issueLabel,
  preciseLine,
  primarySourceUrl,
  pullRequestLabel,
} from "../digest";

const emptyAiSession = {
  id: "empty-ai-session",
  title: "AI session",
  summary: "No session imported yet",
  synthetic: true,
};

export default function DigestBoard({ digest, workspaceName, onSelectCard }) {
  const [copiedPrompt, setCopiedPrompt] = useState(false);
  const map = useMemo(
    () => buildSessionKnowledgeMap(digest, workspaceName),
    [digest, workspaceName],
  );
  const aiSessions = map.aiSessions.length ? map.aiSessions : [emptyAiSession];

  const copyPrompt = async () => {
    const copied = await copyText(map.nextAgentPrompt);
    if (copied) {
      setCopiedPrompt(true);
      window.setTimeout(() => setCopiedPrompt(false), 1600);
    }
  };

  return (
    <section
      data-testid="session-knowledge-map"
      className="relative min-h-[980px] overflow-hidden rounded-lg border border-slate-200 bg-[#f4f4f1] shadow-sm dark:border-neutral-800 dark:bg-[#10110f] lg:min-h-[780px]"
    >
      <div
        aria-hidden="true"
        className="absolute inset-0 opacity-80"
        style={{
          backgroundImage:
            "linear-gradient(to right, rgba(15, 23, 42, 0.08) 1px, transparent 1px), linear-gradient(to bottom, rgba(15, 23, 42, 0.08) 1px, transparent 1px)",
          backgroundSize: "64px 64px",
        }}
      />
      <SessionLines sessionCount={aiSessions.length} />

      <div className="relative z-10 flex flex-col gap-4 p-4 lg:absolute lg:inset-0 lg:block lg:p-0">
        <div className="lg:absolute lg:left-[2%] lg:top-[12%] lg:w-[19%]">
          <div className="space-y-3">
            {aiSessions.slice(0, 4).map((card, index) => (
              <MapNode
                key={card.id}
                icon={Bot}
                iconClassName="text-violet-600"
                title={index === 0 ? "AI session" : `AI session ${index + 1}`}
                primary={preciseLine(card.title, 6)}
                secondary={preciseLine(card.summary, 8)}
                onClick={card.synthetic ? undefined : () => onSelectCard?.(card)}
              />
            ))}
          </div>
        </div>

        <PanelNode
          className="lg:absolute lg:left-[28%] lg:top-[7%] lg:w-[29%]"
          icon={Lightbulb}
          iconClassName="text-orange-600"
          title="Decisions"
          emptyText="No decisions captured yet"
          items={map.decisions}
          renderItem={(card) => preciseLine(card.summary || card.title, 12)}
          onItemClick={onSelectCard}
        />

        <PanelNode
          className="lg:absolute lg:left-[53%] lg:top-[32%] lg:w-[22%]"
          icon={GitPullRequest}
          iconClassName="text-blue-600"
          title="PR"
          emptyText="No PRs linked yet"
          featured
          items={map.prs}
          renderItem={(card) => (
            <LinkedItem
              label={pullRequestLabel(card)}
              url={primarySourceUrl(card)}
              detail={preciseLine(card.summary || card.title, 9)}
            />
          )}
          onItemClick={onSelectCard}
        />

        <PanelNode
          className="lg:absolute lg:right-[3%] lg:top-[12%] lg:w-[22%]"
          icon={AlertTriangle}
          iconClassName="text-red-600"
          title="Blockers"
          emptyText="No blockers"
          items={map.blockers}
          renderItem={(card) => preciseLine(card.summary || card.title, 10)}
          onItemClick={onSelectCard}
        />

        <PanelNode
          className="lg:absolute lg:left-[23%] lg:bottom-[7%] lg:w-[21%]"
          icon={CircleDot}
          iconClassName="text-slate-600"
          title="Issues"
          emptyText="No issues linked yet"
          items={map.issues}
          renderItem={(card) => (
            <LinkedItem
              label={issueLabel(card)}
              url={primarySourceUrl(card)}
              detail={preciseLine(card.summary || card.title, 9)}
            />
          )}
          onItemClick={onSelectCard}
        />

        <PanelNode
          className="lg:absolute lg:left-[51%] lg:bottom-[5%] lg:w-[21%]"
          icon={FileWarning}
          iconClassName="text-red-600"
          title="Broken docs"
          emptyText="No broken docs flagged"
          items={map.brokenDocs}
          renderItem={(card) => preciseLine(card.summary || card.title, 10)}
          onItemClick={onSelectCard}
        />

        <NextAgentTask
          prompt={map.nextAgentPrompt}
          copied={copiedPrompt}
          onCopy={copyPrompt}
        />
      </div>
    </section>
  );
}

function SessionLines({ sessionCount }) {
  const sessionYs = sessionCount > 1 ? [20, 28, 36, 44].slice(0, Math.min(sessionCount, 4)) : [25];

  return (
    <svg
      aria-hidden="true"
      className="pointer-events-none absolute inset-0 z-0 hidden h-full w-full lg:block"
      preserveAspectRatio="none"
      viewBox="0 0 100 100"
    >
      <defs>
        <filter id="sessionLineGlow" x="-20%" y="-20%" width="140%" height="140%">
          <feGaussianBlur stdDeviation="0.55" result="blur" />
          <feMerge>
            <feMergeNode in="blur" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>
      {sessionYs.map((y) => (
        <line
          key={y}
          x1="21"
          y1={y}
          x2="27"
          y2="20"
          stroke="rgba(118, 105, 255, 0.42)"
          strokeWidth="0.16"
          filter="url(#sessionLineGlow)"
        />
      ))}
      <polyline
        points="57,18 64,28 64,32"
        fill="none"
        stroke="rgba(118, 105, 255, 0.34)"
        strokeWidth="0.14"
      />
      <line x1="75" y1="37" x2="78" y2="28" stroke="rgba(118, 105, 255, 0.36)" strokeWidth="0.14" />
      <line x1="64" y1="46" x2="63" y2="80" stroke="rgba(118, 105, 255, 0.36)" strokeWidth="0.14" />
      <line x1="44" y1="86" x2="51" y2="84" stroke="rgba(118, 105, 255, 0.36)" strokeWidth="0.14" />
      <line x1="72" y1="86" x2="78" y2="84" stroke="rgba(118, 105, 255, 0.36)" strokeWidth="0.14" />
      <line x1="87" y1="28" x2="89" y2="80" stroke="rgba(118, 105, 255, 0.34)" strokeWidth="0.14" />
    </svg>
  );
}

function MapNode({ icon: Icon, iconClassName, title, primary, secondary, onClick }) {
  const Component = onClick ? "button" : "div";

  return (
    <Component
      type={onClick ? "button" : undefined}
      onClick={onClick}
      className="flex min-h-[106px] w-full items-center gap-4 rounded-md border border-slate-300 bg-white px-6 py-4 text-left shadow-[0_18px_40px_rgba(15,23,42,0.12)] transition hover:border-slate-400 dark:border-neutral-700 dark:bg-neutral-950"
    >
      <Icon className={`h-7 w-7 shrink-0 ${iconClassName}`} />
      <div className="min-w-0">
        <p className="text-lg font-black leading-6 text-slate-950 dark:text-white">{title}</p>
        <p className="mt-1 truncate font-mono text-sm text-slate-900 dark:text-neutral-200">{primary}</p>
        {secondary ? (
          <p className="mt-1 line-clamp-1 text-xs font-semibold text-slate-500 dark:text-neutral-400">
            {secondary}
          </p>
        ) : null}
      </div>
    </Component>
  );
}

function PanelNode({
  className = "",
  icon: Icon,
  iconClassName,
  title,
  emptyText,
  items,
  renderItem,
  onItemClick,
  featured = false,
}) {
  return (
    <section
      className={`rounded-md border bg-white px-5 py-4 shadow-[0_18px_40px_rgba(15,23,42,0.12)] dark:bg-neutral-950 ${
        featured
          ? "border-blue-500 ring-4 ring-blue-500/10 dark:border-blue-400"
          : "border-slate-300 dark:border-neutral-700"
      } ${className}`}
    >
      <div className="mb-3 flex items-center gap-3">
        <Icon className={`h-7 w-7 shrink-0 ${iconClassName}`} />
        <h2 className="text-lg font-black leading-6 text-slate-950 dark:text-white">{title}</h2>
      </div>
      <div className="space-y-2">
        {items.length ? (
          items.map((card) => (
            <div
              key={card.id}
              role="button"
              tabIndex={0}
              onClick={() => onItemClick?.(card)}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  onItemClick?.(card);
                }
              }}
              className="block w-full rounded-md border border-transparent px-2 py-1.5 text-left transition hover:border-slate-200 hover:bg-slate-50 dark:hover:border-neutral-800 dark:hover:bg-neutral-900"
            >
              {renderItem(card)}
            </div>
          ))
        ) : (
          <p className="rounded-md border border-dashed border-slate-200 px-3 py-3 text-sm font-semibold text-slate-400 dark:border-neutral-800 dark:text-neutral-500">
            {emptyText}
          </p>
        )}
      </div>
    </section>
  );
}

function LinkedItem({ label, url, detail }) {
  return (
    <span className="block min-w-0">
      <span className="flex min-w-0 items-center gap-2">
        {url ? (
          <a
            href={url}
            target="_blank"
            rel="noreferrer"
            onClick={(event) => event.stopPropagation()}
            className="min-w-0 truncate text-base font-black text-blue-700 underline-offset-2 hover:underline dark:text-blue-300"
          >
            {label}
          </a>
        ) : (
          <span className="min-w-0 truncate text-base font-black text-slate-950 dark:text-white">
            {label}
          </span>
        )}
        {url ? <ExternalLink className="h-3.5 w-3.5 shrink-0 text-blue-500" /> : null}
      </span>
      <span className="mt-1 block truncate font-mono text-sm text-slate-900 dark:text-neutral-200">
        {detail}
      </span>
    </span>
  );
}

function NextAgentTask({ prompt, copied, onCopy }) {
  return (
    <button
      data-testid="next-agent-task"
      type="button"
      onClick={onCopy}
      className="group z-20 flex min-h-[106px] w-full flex-col rounded-md border border-slate-300 bg-white px-5 py-4 text-left shadow-[0_18px_40px_rgba(15,23,42,0.12)] transition-all duration-200 hover:border-emerald-500 focus:border-emerald-500 focus:outline-none dark:border-neutral-700 dark:bg-neutral-950 lg:absolute lg:bottom-[7%] lg:right-[2%] lg:w-[22%] lg:hover:w-[36%] lg:focus:w-[36%]"
    >
      <span className="flex items-center gap-3">
        <Sparkles className="h-7 w-7 shrink-0 text-emerald-600" />
        <span className="min-w-0">
          <span className="block text-lg font-black leading-6 text-slate-950 dark:text-white">
            Next agent task
          </span>
          <span className="mt-1 flex items-center gap-2 text-sm font-semibold text-slate-500 dark:text-neutral-400">
            {copied ? <Check className="h-4 w-4 text-emerald-600" /> : <Copy className="h-4 w-4" />}
            {copied ? "Copied" : "Click to copy"}
          </span>
        </span>
      </span>
      <span className="mt-3 block max-h-0 overflow-hidden opacity-0 transition-all duration-200 group-hover:max-h-[520px] group-hover:opacity-100 group-focus:max-h-[520px] group-focus:opacity-100">
        <span className="mb-2 block text-xs font-bold uppercase text-slate-400">
          Handoff prompt
        </span>
        <span className="block max-h-[440px] overflow-y-auto whitespace-pre-wrap rounded-md border border-slate-200 bg-slate-50 p-3 font-mono text-[11px] leading-5 text-slate-700 dark:border-neutral-800 dark:bg-black dark:text-neutral-300">
          {prompt}
        </span>
      </span>
    </button>
  );
}

async function copyText(value) {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(value);
      return true;
    } catch {
      // Fall back for browser contexts that block async clipboard writes.
    }
  }

  const textArea = document.createElement("textarea");
  textArea.value = value;
  textArea.setAttribute("readonly", "");
  textArea.style.position = "fixed";
  textArea.style.left = "-9999px";
  textArea.style.top = "0";
  document.body.appendChild(textArea);
  textArea.focus();
  textArea.select();
  textArea.setSelectionRange(0, value.length);

  try {
    const didCopy = document.execCommand("copy");
    return didCopy || textArea.selectionStart === 0;
  } finally {
    document.body.removeChild(textArea);
  }
}
