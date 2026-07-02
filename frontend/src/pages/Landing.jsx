import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  AlertTriangle,
  ArrowRight,
  Bot,
  CheckCircle2,
  CircleDot,
  FileText,
  GitBranch,
  GitPullRequest,
  PackageCheck,
  Plus,
  Search,
  ShieldCheck,
  TerminalSquare,
  Upload,
} from "lucide-react";
import CeIcon from "../components/CeIcon";
import ThemeToggle from "../components/ThemeToggle";
import gdriveIcon from "@assets/gdrive-icon.png";
import gmailIcon from "@assets/gmail-icon.png";
import openaiIcon from "@assets/openai-icon.png";
import opencodeIcon from "@assets/opencode-icon.png";

const GITHUB_URL = "https://github.com/Darshan174/Context-Engine";

const CONTEXT_ITEMS = [
  {
    title: "Auth refactor",
    type: "Agent session",
    source: "Codex",
    href: "/app/graph",
    icon: Bot,
    tone: "bg-emerald-500/12 text-emerald-700 dark:text-emerald-300",
    metric: "18 nodes",
    secondary: "6 decisions",
    status: "Fresh",
    statusClass: "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/12 dark:text-emerald-300",
  },
  {
    title: "PR #184",
    type: "Implementation",
    source: "GitHub",
    href: "/app/changes",
    icon: GitPullRequest,
    tone: "bg-blue-500/12 text-blue-700 dark:text-blue-300",
    metric: "12 files",
    secondary: "3 blockers",
    status: "Review",
    statusClass: "bg-blue-100 text-blue-700 dark:bg-blue-500/12 dark:text-blue-300",
  },
  {
    title: "Schema approval",
    type: "Blocker",
    source: "Slack",
    href: "/app/query",
    icon: AlertTriangle,
    tone: "bg-amber-500/14 text-amber-800 dark:text-amber-300",
    metric: "2 owners",
    secondary: "4 refs",
    status: "Blocked",
    statusClass: "bg-amber-100 text-amber-800 dark:bg-amber-500/12 dark:text-amber-300",
  },
  {
    title: "OAuth docs",
    type: "Drift",
    source: "Google Drive",
    href: "/app/sources",
    icon: FileText,
    tone: "bg-rose-500/12 text-rose-700 dark:text-rose-300",
    metric: "9 claims",
    secondary: "2 stale",
    status: "Update",
    statusClass: "bg-rose-100 text-rose-700 dark:bg-rose-500/12 dark:text-rose-300",
  },
  {
    title: "Next agent packet",
    type: "Handoff",
    source: "Graph",
    href: "/app/graph",
    icon: PackageCheck,
    tone: "bg-violet-500/12 text-violet-700 dark:text-violet-300",
    metric: "1 packet",
    secondary: "Ready",
    status: "Live",
    statusClass: "bg-violet-100 text-violet-700 dark:bg-violet-500/12 dark:text-violet-300",
  },
];

const SOURCES = [
  {
    name: "Codex",
    detail: "agent runs",
    icon: <img src={openaiIcon} alt="" className="h-5 w-5 object-contain dark:invert" />,
    color: "bg-emerald-500/12 text-emerald-700 dark:text-emerald-300",
  },
  {
    name: "Claude",
    detail: "sessions",
    icon: <span className="flex h-5 w-5 items-center justify-center rounded-md bg-[#d97757] text-[9px] font-black text-white">A</span>,
    color: "bg-orange-500/12 text-orange-700 dark:text-orange-300",
  },
  {
    name: "OpenCode",
    detail: "local work",
    icon: <img src={opencodeIcon} alt="" className="h-5 w-5 rounded object-contain" />,
    color: "bg-slate-500/12 text-slate-700 dark:text-slate-300",
  },
  {
    name: "GitHub",
    detail: "PRs, issues",
    icon: <GitBranch className="h-5 w-5" />,
    color: "bg-blue-500/12 text-blue-700 dark:text-blue-300",
  },
  {
    name: "Google Drive",
    detail: "docs",
    icon: <img src={gdriveIcon} alt="" className="h-5 w-5 object-contain" />,
    color: "bg-lime-500/12 text-lime-700 dark:text-lime-300",
  },
  {
    name: "Gmail",
    detail: "decisions",
    icon: <img src={gmailIcon} alt="" className="h-5 w-5 object-contain" />,
    color: "bg-red-500/12 text-red-700 dark:text-red-300",
  },
];

const STATS = [
  { label: "Sources", value: "6" },
  { label: "Entities", value: "214" },
  { label: "Open gaps", value: "11" },
  { label: "Packets", value: "8" },
];

const ACTIONS = [
  {
    title: "Find stale decisions",
    body: "Compare old notes against current code, PRs, and issues.",
    href: "/app/query",
    icon: Search,
  },
  {
    title: "Build a handoff",
    body: "Package the exact context a human or agent needs next.",
    href: "/app/graph",
    icon: PackageCheck,
  },
  {
    title: "Import a session",
    body: "Add Codex, Claude, OpenCode, docs, and repository context.",
    href: "/app/connectors",
    icon: Upload,
  },
];

const AGENT_COMMANDS = [
  {
    prompt: "$ ctxe mcp",
    response: "context-engine tools ready for Codex, Claude, Cursor, and OpenCode",
  },
  {
    prompt: '$ ctxe query "what should the next agent know?"',
    response: "Auth is blocked on schema approval. Update OAuth docs after PR #184 lands.",
  },
  {
    prompt: "$ ctxe ingest ./agent-runs --sync",
    response: "18 facts indexed, 6 decisions linked, 3 blockers surfaced",
  },
];

export default function Landing() {
  const [query, setQuery] = useState("");
  const normalizedQuery = query.trim().toLowerCase();

  const filteredItems = useMemo(() => {
    if (!normalizedQuery) return CONTEXT_ITEMS;
    return CONTEXT_ITEMS.filter((item) =>
      [item.title, item.type, item.source, item.metric, item.secondary, item.status]
        .join(" ")
        .toLowerCase()
        .includes(normalizedQuery),
    );
  }, [normalizedQuery]);

  return (
    <div className="min-h-screen bg-[#f6f6f3] text-slate-950 transition-colors dark:bg-[#050505] dark:text-neutral-50">
      <main className="mx-auto flex min-h-screen w-full max-w-5xl flex-col px-4 py-6 md:px-6 md:py-8">
        <TopBar />

        <section className="flex flex-col py-6 md:py-8">
          <div className="mx-auto w-full max-w-3xl text-center">
            <Link to="/" className="mx-auto mb-4 inline-flex items-center gap-2 text-slate-500 transition hover:text-slate-950 dark:text-neutral-400 dark:hover:text-white">
              <CeIcon size={26} />
              <span className="text-lg font-bold text-slate-600 dark:text-neutral-300">Context Engine</span>
            </Link>

            <h1 className="text-4xl font-bold tracking-tight text-slate-950 dark:text-white md:text-5xl">
              The project memory graph for AI builders
            </h1>
            <p className="mx-auto mt-4 max-w-2xl text-base leading-7 text-slate-600 dark:text-neutral-400">
              Search sessions, PRs, docs, blockers, decisions, and handoffs from one clean project graph.
            </p>

            <div className="mx-auto mt-6 flex max-w-xl flex-col gap-2 sm:flex-row">
              <label className="relative min-w-0 flex-1">
                <span className="sr-only">Search project context</span>
                <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                <input
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  className="h-11 w-full rounded-md border border-slate-200 bg-white pl-10 pr-3 text-sm font-medium text-slate-950 shadow-sm outline-none transition placeholder:text-slate-400 focus:border-slate-400 focus:ring-4 focus:ring-slate-200/70 dark:border-white/10 dark:bg-white/[0.055] dark:text-white dark:placeholder:text-neutral-500 dark:focus:border-white/25 dark:focus:ring-white/10"
                  placeholder='"auth blockers in PRs"'
                />
              </label>
              <Link
                to="/app/connectors"
                className="inline-flex h-11 shrink-0 items-center justify-center gap-2 rounded-md bg-slate-950 px-5 text-sm font-bold text-white transition hover:bg-slate-800 dark:bg-white dark:text-black dark:hover:bg-neutral-200"
              >
                <Plus className="h-4 w-4" />
                Add context
              </Link>
            </div>

            <div className="mt-4 flex flex-wrap items-center justify-center gap-x-3 gap-y-1 text-sm font-medium text-slate-500 dark:text-neutral-500">
              <Link to="/app/graph" className="transition hover:text-slate-950 dark:hover:text-white">Graph</Link>
              <span className="text-slate-300 dark:text-neutral-700">.</span>
              <Link to="/app/sources" className="transition hover:text-slate-950 dark:hover:text-white">Sources</Link>
              <span className="text-slate-300 dark:text-neutral-700">.</span>
              <Link to="/app/changes" className="transition hover:text-slate-950 dark:hover:text-white">Changes</Link>
              <span className="text-slate-300 dark:text-neutral-700">.</span>
              <a href={GITHUB_URL} target="_blank" rel="noreferrer" className="transition hover:text-slate-950 dark:hover:text-white">
                GitHub
              </a>
            </div>
          </div>

          <StatsRow />
          <RecentContext items={filteredItems} hasQuery={normalizedQuery.length > 0} />
          <SourceDirectory />
        </section>

        <AgentNativeSection />
        <ActionDirectory />
      </main>
    </div>
  );
}

function TopBar() {
  return (
    <header className="flex items-center justify-between">
      <Link to="/app" className="inline-flex items-center gap-2 text-xs font-bold text-slate-500 transition hover:text-slate-950 dark:text-neutral-400 dark:hover:text-white">
        <CircleDot className="h-3.5 w-3.5 text-emerald-500" />
        Open workspace
      </Link>
      <div className="flex items-center gap-2">
        <a
          href={GITHUB_URL}
          target="_blank"
          rel="noreferrer"
          className="hidden h-9 items-center gap-2 rounded-md border border-slate-200 bg-white px-3 text-xs font-bold text-slate-600 transition hover:border-slate-300 hover:text-slate-950 dark:border-white/10 dark:bg-white/[0.055] dark:text-neutral-300 dark:hover:border-white/20 dark:hover:text-white sm:inline-flex"
        >
          <GitHubMark className="h-4 w-4" />
          GitHub
        </a>
        <ThemeToggle />
      </div>
    </header>
  );
}

function StatsRow() {
  return (
    <div className="mx-auto mt-6 grid w-full max-w-2xl grid-cols-2 gap-px overflow-hidden rounded-lg border border-slate-200 bg-slate-200 dark:border-white/10 dark:bg-white/10 sm:grid-cols-4">
      {STATS.map((stat) => (
        <div key={stat.label} className="bg-white px-4 py-3 text-center dark:bg-white/[0.055]">
          <p className="font-mono text-lg font-bold text-slate-950 dark:text-white">{stat.value}</p>
          <p className="mt-1 text-[10px] font-bold uppercase tracking-wider text-slate-400 dark:text-neutral-500">{stat.label}</p>
        </div>
      ))}
    </div>
  );
}

function RecentContext({ items, hasQuery }) {
  return (
    <section className="mt-7 w-full">
      <div className="mb-3 flex items-center justify-between px-1">
        <h2 className="text-sm font-semibold text-slate-500 dark:text-neutral-400">
          {hasQuery ? "Matching context" : "Recently indexed"}
        </h2>
        <Link to="/app/graph" className="inline-flex items-center gap-1 text-xs font-bold text-slate-500 transition hover:text-slate-950 dark:text-neutral-400 dark:hover:text-white">
          View graph
          <ArrowRight className="h-3.5 w-3.5" />
        </Link>
      </div>

      {items.length > 0 ? (
        <div className="-mx-4 flex gap-3 overflow-x-auto px-4 pb-3 md:mx-0 md:px-0">
          {items.map((item) => (
            <ContextCard key={item.title} item={item} />
          ))}
        </div>
      ) : (
        <div className="rounded-lg border border-dashed border-slate-300 bg-white/70 px-5 py-8 text-center text-sm font-medium text-slate-500 dark:border-white/15 dark:bg-white/[0.035] dark:text-neutral-400">
          No matching context in the demo set.
        </div>
      )}
    </section>
  );
}

function ContextCard({ item }) {
  const Icon = item.icon;

  return (
    <Link
      to={item.href}
      className="group flex w-[220px] shrink-0 flex-col rounded-lg border border-slate-200 bg-white p-3 text-left shadow-sm transition hover:border-slate-300 hover:bg-slate-50 dark:border-white/10 dark:bg-white/[0.055] dark:hover:border-white/20 dark:hover:bg-white/[0.08]"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-center gap-3">
          <span className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ${item.tone}`}>
            <Icon className="h-4 w-4" />
          </span>
          <div className="min-w-0">
            <h3 className="truncate text-sm font-bold text-slate-950 transition group-hover:text-slate-700 dark:text-white dark:group-hover:text-neutral-200">
              {item.title}
            </h3>
            <p className="truncate text-[11px] font-medium text-slate-500 dark:text-neutral-500">{item.type}</p>
          </div>
        </div>
        <span className={`rounded-md px-2 py-1 text-[9px] font-black uppercase tracking-wide ${item.statusClass}`}>
          {item.status}
        </span>
      </div>

      <div className="mt-4 grid grid-cols-3 gap-2">
        <Metric label="Source" value={item.source} />
        <Metric label="Scope" value={item.metric} />
        <Metric label="Signal" value={item.secondary} />
      </div>
    </Link>
  );
}

function Metric({ label, value }) {
  return (
    <div className="min-w-0">
      <p className="truncate text-[9px] font-black uppercase tracking-wider text-slate-400 dark:text-neutral-600">{label}</p>
      <p className="mt-1 truncate font-mono text-xs font-bold text-slate-900 dark:text-neutral-100">{value}</p>
    </div>
  );
}

function SourceDirectory() {
  return (
    <section className="mt-5 w-full">
      <div className="mb-3 flex items-center justify-between px-1">
        <h2 className="text-sm font-semibold text-slate-500 dark:text-neutral-400">Browse by source</h2>
        <Link to="/app/connectors" className="inline-flex items-center gap-1 text-xs font-bold text-slate-500 transition hover:text-slate-950 dark:text-neutral-400 dark:hover:text-white">
          Connect more
          <ArrowRight className="h-3.5 w-3.5" />
        </Link>
      </div>
      <div className="flex flex-wrap justify-center gap-2 md:justify-start">
        {SOURCES.map((source) => (
          <Link
            key={source.name}
            to="/app/connectors"
            className="inline-flex items-center gap-2 rounded-md border border-slate-200 bg-white px-3 py-2 text-sm font-bold text-slate-700 transition hover:border-slate-300 hover:bg-slate-50 dark:border-white/10 dark:bg-white/[0.055] dark:text-neutral-200 dark:hover:border-white/20 dark:hover:bg-white/[0.08]"
          >
            <span className={`flex h-7 w-7 items-center justify-center rounded-md ${source.color}`}>
              {source.icon}
            </span>
            <span>{source.name}</span>
            <span className="hidden text-xs font-medium text-slate-400 dark:text-neutral-500 sm:inline">{source.detail}</span>
          </Link>
        ))}
      </div>
    </section>
  );
}

function AgentNativeSection() {
  return (
    <section className="border-t border-slate-200 py-7 dark:border-white/10">
      <div className="grid gap-4 md:grid-cols-[0.8fr_1.2fr] md:items-stretch">
        <div className="rounded-lg border border-slate-200 bg-white p-5 dark:border-white/10 dark:bg-white/[0.055]">
          <div className="flex items-center gap-2 text-[11px] font-bold uppercase tracking-wider text-slate-400 dark:text-neutral-500">
            <Bot className="h-4 w-4 text-violet-500" />
            For AI agents
          </div>
          <h2 className="mt-3 text-2xl font-bold tracking-tight text-slate-950 dark:text-white">
            Give every coding agent the same project memory.
          </h2>
          <p className="mt-3 text-sm leading-6 text-slate-500 dark:text-neutral-400">
            Run Context Engine as an MCP server or CLI-backed memory layer so agents can ask what changed,
            what is blocked, and what context belongs in the next session.
          </p>
          <div className="mt-5 flex flex-wrap gap-2 text-[11px] font-bold uppercase tracking-wider text-slate-500 dark:text-neutral-500">
            <span className="inline-flex items-center gap-1.5 rounded-md bg-slate-100 px-2.5 py-1.5 dark:bg-white/10">
              <TerminalSquare className="h-3.5 w-3.5 text-blue-500" />
              MCP server
            </span>
            <span className="inline-flex items-center gap-1.5 rounded-md bg-slate-100 px-2.5 py-1.5 dark:bg-white/10">
              <Search className="h-3.5 w-3.5 text-emerald-500" />
              Source-backed answers
            </span>
            <span className="inline-flex items-center gap-1.5 rounded-md bg-slate-100 px-2.5 py-1.5 dark:bg-white/10">
              <PackageCheck className="h-3.5 w-3.5 text-violet-500" />
              Handoff packets
            </span>
          </div>
        </div>

        <div className="overflow-hidden rounded-lg border border-slate-200 bg-slate-950 text-slate-100 shadow-sm dark:border-white/10">
          <div className="flex items-center justify-between border-b border-white/10 px-4 py-3">
            <div className="flex items-center gap-1.5">
              <span className="h-2.5 w-2.5 rounded-full bg-red-400" />
              <span className="h-2.5 w-2.5 rounded-full bg-amber-400" />
              <span className="h-2.5 w-2.5 rounded-full bg-emerald-400" />
            </div>
            <span className="font-mono text-[10px] text-slate-500">agent-context.sh</span>
          </div>
          <div className="space-y-4 px-4 py-4 font-mono text-xs leading-6">
            {AGENT_COMMANDS.map((item) => (
              <div key={item.prompt}>
                <p className="text-emerald-300">{item.prompt}</p>
                <p className="mt-1 text-slate-400">{item.response}</p>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

function ActionDirectory() {
  return (
    <section className="border-t border-slate-200 py-7 dark:border-white/10">
      <div className="mb-4 flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-[11px] font-bold uppercase tracking-wider text-slate-400 dark:text-neutral-500">Useful next actions</p>
          <h2 className="mt-1 text-2xl font-bold tracking-tight text-slate-950 dark:text-white">Move from memory to work.</h2>
        </div>
        <div className="flex flex-wrap gap-3 text-[11px] font-bold uppercase tracking-wider text-slate-500 dark:text-neutral-500">
          <span className="inline-flex items-center gap-1.5"><ShieldCheck className="h-3.5 w-3.5 text-emerald-500" /> Local-first</span>
          <span className="inline-flex items-center gap-1.5"><TerminalSquare className="h-3.5 w-3.5 text-blue-500" /> BYO key</span>
          <span className="inline-flex items-center gap-1.5"><CheckCircle2 className="h-3.5 w-3.5 text-violet-500" /> Open source</span>
        </div>
      </div>

      <div className="grid gap-3 md:grid-cols-3">
        {ACTIONS.map((action) => (
          <Link
            key={action.title}
            to={action.href}
            className="group rounded-lg border border-slate-200 bg-white p-4 transition hover:border-slate-300 hover:bg-slate-50 dark:border-white/10 dark:bg-white/[0.055] dark:hover:border-white/20 dark:hover:bg-white/[0.08]"
          >
            <div className="flex items-center justify-between gap-3">
              <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-slate-100 text-slate-700 dark:bg-white/10 dark:text-neutral-200">
                <action.icon className="h-4 w-4" />
              </span>
              <ArrowRight className="h-4 w-4 text-slate-300 transition group-hover:translate-x-0.5 group-hover:text-slate-600 dark:text-neutral-700 dark:group-hover:text-neutral-300" />
            </div>
            <h3 className="mt-5 text-base font-bold text-slate-950 dark:text-white">{action.title}</h3>
            <p className="mt-2 text-sm leading-6 text-slate-500 dark:text-neutral-400">{action.body}</p>
          </Link>
        ))}
      </div>
    </section>
  );
}

function GitHubMark({ className = "" }) {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true" className={className}>
      <path d="M12 .7C5.6.7.5 5.9.5 12.3c0 5.1 3.3 9.5 7.9 11 .6.1.8-.3.8-.6v-2.2c-3.2.7-3.9-1.4-3.9-1.4-.5-1.4-1.3-1.8-1.3-1.8-1.1-.7.1-.7.1-.7 1.2.1 1.8 1.2 1.8 1.2 1.1 1.8 2.8 1.3 3.5 1 .1-.8.4-1.3.8-1.6-2.6-.3-5.3-1.3-5.3-5.7 0-1.3.4-2.3 1.2-3.1-.1-.3-.5-1.5.1-3.1 0 0 1-.3 3.2 1.2a11 11 0 0 1 5.8 0c2.2-1.5 3.2-1.2 3.2-1.2.6 1.6.2 2.8.1 3.1.8.8 1.2 1.8 1.2 3.1 0 4.4-2.7 5.4-5.3 5.7.4.4.8 1.1.8 2.2v3.3c0 .3.2.7.8.6a11.6 11.6 0 0 0 7.9-11C23.5 5.9 18.4.7 12 .7Z" />
    </svg>
  );
}
