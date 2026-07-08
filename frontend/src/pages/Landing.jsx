import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { LayoutGroup, motion } from "framer-motion";
import {
  AlertTriangle,
  ArrowRight,
  Bot,
  CheckCircle2,
  CircleDot,
  Database,
  FileText,
  PackageCheck,
  RefreshCw,
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

const TRUST_MARKERS = [
  { value: "Source ledger", label: "Raw evidence kept" },
  { value: "Graph facts", label: "Components + models" },
  { value: "Query trace", label: "Facts used visible" },
  { value: "Context packs", label: "Agent handoff surface" },
];

const PRODUCT_SURFACES = [
  {
    title: "Source-first ingestion",
    type: "Raw evidence",
    body: "Uploads, provider sync, and AI-session imports create SourceDocument rows before extraction.",
    href: "/app/sources",
    icon: Upload,
    tone: "bg-emerald-500/12 text-emerald-700 dark:text-emerald-300",
    chips: ["Local files", "AI sessions", "Provider sync"],
  },
  {
    title: "Knowledge graph",
    type: "Project memory",
    body: "Models, components, relationships, confidence, temporal state, and provenance are inspectable in the graph.",
    href: "/app/graph",
    icon: Database,
    tone: "bg-blue-500/12 text-blue-700 dark:text-blue-300",
    chips: ["Models", "Components", "Evidence"],
  },
  {
    title: "Grounded Ask",
    type: "Query surface",
    body: "Answers include retrieval strategy, ranked facts, relationship evidence, and source references.",
    href: "/app/query",
    icon: CheckCircle2,
    tone: "bg-teal-500/12 text-teal-700 dark:text-teal-300",
    chips: ["query.v1", "Facts used", "Confidence"],
  },
  {
    title: "Context packs",
    type: "Next-agent prep",
    body: "Graph selections and compiler paths package relevant context with citations for the next run.",
    href: "/app/graph",
    icon: PackageCheck,
    tone: "bg-violet-500/12 text-violet-700 dark:text-violet-300",
    chips: ["Markdown", "Manifest", "Neighbors"],
  },
  {
    title: "Connector guardrails",
    type: "Honest status",
    body: "Coming-soon providers stay disabled until the backend can create source documents and tests cover sync behavior.",
    href: "/app/connectors",
    icon: AlertTriangle,
    tone: "bg-amber-500/14 text-amber-800 dark:text-amber-300",
    chips: ["Available", "Disconnected", "Coming soon"],
  },
];

const SOURCES = [
  {
    name: "Local files",
    detail: "uploads",
    icon: <FileText className="h-4 w-4" />,
    color: "bg-slate-500/12 text-slate-700 dark:text-slate-300",
  },
  {
    name: "Codex",
    detail: "sessions",
    icon: <img src={openaiIcon} alt="" className="h-4 w-4 object-contain dark:invert" />,
    color: "bg-emerald-500/12 text-emerald-700 dark:text-emerald-300",
  },
  {
    name: "Claude",
    detail: "sessions",
    icon: <span className="flex h-5 w-5 items-center justify-center rounded-md bg-[#d97757] text-[10px] font-black text-white">C</span>,
    color: "bg-orange-500/12 text-orange-700 dark:text-orange-300",
  },
  {
    name: "OpenCode",
    detail: "sessions",
    icon: <OpenCodeMark />,
    color: "bg-neutral-500/12 text-neutral-700 dark:text-neutral-300",
  },
  {
    name: "GitHub",
    detail: "PRs, issues",
    icon: <GitHubMark className="h-5 w-5" />,
    color: "bg-slate-500/12 text-slate-800 dark:text-neutral-200",
  },
  {
    name: "Slack",
    detail: "threads",
    icon: <span className="flex h-5 w-5 items-center justify-center rounded-md bg-[#4A154B] text-[13px] font-black text-white">#</span>,
    color: "bg-fuchsia-500/12 text-fuchsia-800 dark:text-fuchsia-300",
  },
  {
    name: "Google Drive",
    detail: "docs",
    icon: <img src={gdriveIcon} alt="" className="h-5 w-5 object-contain" />,
    color: "bg-lime-500/12 text-lime-700 dark:text-lime-300",
  },
  {
    name: "Gmail",
    detail: "threads",
    icon: <img src={gmailIcon} alt="" className="h-5 w-5 object-contain" />,
    color: "bg-red-500/12 text-red-700 dark:text-red-300",
  },
];

const AGENT_STEPS = [
  {
    title: "Prepare the next run",
    body: "Build a context pack from graph facts, source citations, blockers, and recent project state.",
    icon: PackageCheck,
  },
  {
    title: "Ask with evidence",
    body: "Agents can query what changed, what is blocked, and why the graph believes it.",
    icon: Bot,
  },
  {
    title: "Record what happened",
    body: "MCP tools can store decisions, blockers, patch summaries, and verification as new source evidence.",
    icon: TerminalSquare,
  },
];

const FOOTER_LINKS = [
  { label: "Dashboard", to: "/app" },
  { label: "Graph", to: "/app/graph" },
  { label: "Ask", to: "/app/query" },
  { label: "Sources", to: "/app/sources" },
  { label: "Connectors", to: "/app/connectors" },
];

const fadeUp = {
  hidden: { opacity: 0, y: 14 },
  visible: { opacity: 1, y: 0 },
};

export default function Landing() {
  return (
    <div className="min-h-screen bg-[#f6f6f3] text-slate-950 transition-colors dark:bg-[#050505] dark:text-neutral-50">
      <main className="mx-auto flex min-h-screen w-full max-w-5xl flex-col px-4 py-6 md:px-6 md:py-8">
        <TopBar />

        <motion.section
          initial="hidden"
          animate="visible"
          variants={fadeUp}
          transition={{ duration: 0.45, ease: [0.22, 1, 0.36, 1] }}
          className="flex flex-col py-6 md:py-8"
        >
          <div className="mx-auto w-full max-w-3xl text-center">
            <Link to="/" className="mx-auto mb-4 inline-flex items-center gap-2 text-slate-500 transition hover:text-slate-950 dark:text-neutral-400 dark:hover:text-white">
              <CeIcon size={26} />
              <span className="text-lg font-bold text-slate-600 dark:text-neutral-300">Context Engine</span>
            </Link>

            <h1 className="text-3xl font-bold text-slate-950 dark:text-white sm:text-4xl md:text-5xl">
              Project memory graph for AI builders
            </h1>
            <p className="mx-auto mt-4 max-w-2xl text-base leading-7 text-slate-600 dark:text-neutral-400">
              Preserve coding sessions, source documents, PRs, issues, decisions, blockers, and provenance so the next agent starts from grounded project context.
            </p>

            <div className="mx-auto mt-6 flex justify-center">
              <Link
                to="/app"
                className="group relative inline-flex h-12 min-w-[190px] items-center justify-center gap-2 overflow-hidden rounded-lg bg-slate-950 px-6 text-sm font-black text-white shadow-[0_18px_42px_rgba(15,23,42,0.20)] transition hover:-translate-y-0.5 hover:bg-slate-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-500 focus-visible:ring-offset-2 dark:bg-white dark:text-black dark:shadow-[0_18px_42px_rgba(255,255,255,0.10)] dark:hover:bg-neutral-200 dark:focus-visible:ring-offset-black"
              >
                <span className="absolute inset-y-0 left-0 w-10 -translate-x-12 skew-x-[-14deg] bg-white/20 transition-transform duration-700 group-hover:translate-x-56 dark:bg-black/10" />
                <span className="relative z-10">Show dashboard</span>
                <ArrowRight className="relative z-10 h-4 w-4 transition-transform group-hover:translate-x-0.5" />
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

          <TrustRow />
          <ProductSurfaceRail />
          <SourceDirectory />
        </motion.section>

        <AgentNativeSection />
        <LandingFooter />
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

function TrustRow() {
  return (
    <motion.div
      variants={fadeUp}
      transition={{ duration: 0.45, delay: 0.08, ease: [0.22, 1, 0.36, 1] }}
      className="mx-auto mt-6 grid w-full max-w-2xl grid-cols-2 gap-px overflow-hidden rounded-lg border border-slate-200 bg-slate-200 dark:border-white/10 dark:bg-white/10 sm:grid-cols-4"
    >
      {TRUST_MARKERS.map((stat) => (
        <div key={stat.label} className="bg-white px-4 py-3 text-center dark:bg-white/[0.055]">
          <p className="text-sm font-black text-slate-950 dark:text-white">{stat.value}</p>
          <p className="mt-1 text-[10px] font-bold uppercase text-slate-400 dark:text-neutral-500">{stat.label}</p>
        </div>
      ))}
    </motion.div>
  );
}

function ProductSurfaceRail() {
  return (
    <section className="mt-7 w-full">
      <div className="mb-3 flex items-center justify-between px-1">
        <h2 className="text-sm font-semibold text-slate-500 dark:text-neutral-400">What exists today</h2>
        <Link to="/app/graph" className="inline-flex items-center gap-1 text-xs font-bold text-slate-500 transition hover:text-slate-950 dark:text-neutral-400 dark:hover:text-white">
          Open graph
          <ArrowRight className="h-3.5 w-3.5" />
        </Link>
      </div>

      <div className="flex gap-3 overflow-x-auto pb-3">
        {PRODUCT_SURFACES.map((item, index) => (
          <SurfaceCard key={item.title} item={item} index={index} />
        ))}
      </div>
    </section>
  );
}

function SurfaceCard({ item, index }) {
  const Icon = item.icon;

  return (
    <motion.div
      variants={fadeUp}
      initial="hidden"
      animate="visible"
      transition={{ duration: 0.4, delay: 0.12 + index * 0.04, ease: [0.22, 1, 0.36, 1] }}
      whileHover={{ y: -3 }}
      className="w-[248px] shrink-0"
    >
      <Link
        to={item.href}
        className="group flex h-full flex-col rounded-lg border border-slate-200 bg-white p-4 text-left shadow-sm transition hover:border-slate-300 hover:bg-slate-50 dark:border-white/10 dark:bg-white/[0.055] dark:hover:border-white/20 dark:hover:bg-white/[0.08]"
      >
        <div className="flex items-start justify-between gap-3">
          <span className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ${item.tone}`}>
            <Icon className="h-4 w-4" />
          </span>
          <span className="rounded-md bg-slate-100 px-2 py-1 text-[9px] font-black uppercase text-slate-500 dark:bg-white/10 dark:text-neutral-400">
            {item.type}
          </span>
        </div>
        <h3 className="mt-4 text-sm font-black text-slate-950 transition group-hover:text-slate-700 dark:text-white dark:group-hover:text-neutral-200">
          {item.title}
        </h3>
        <p className="mt-2 min-h-[60px] text-xs leading-5 text-slate-500 dark:text-neutral-400">
          {item.body}
        </p>
        <div className="mt-4 flex flex-wrap gap-1.5">
          {item.chips.map((chip) => (
            <span key={chip} className="rounded-md bg-slate-100 px-2 py-1 text-[10px] font-bold text-slate-500 dark:bg-white/10 dark:text-neutral-400">
              {chip}
            </span>
          ))}
        </div>
      </Link>
    </motion.div>
  );
}

function SourceDirectory() {
  const [activeIndex, setActiveIndex] = useState(0);

  useEffect(() => {
    const id = window.setInterval(() => {
      setActiveIndex((current) => (current + 1) % SOURCES.length);
    }, 1800);
    return () => window.clearInterval(id);
  }, []);

  return (
    <section className="mt-5 w-full">
      <div className="mb-3 flex items-center justify-between px-1">
        <h2 className="text-sm font-semibold text-slate-500 dark:text-neutral-400">Browse by source</h2>
        <Link to="/app/connectors" className="inline-flex items-center gap-1 text-xs font-bold text-slate-500 transition hover:text-slate-950 dark:text-neutral-400 dark:hover:text-white">
          Connect sources
          <ArrowRight className="h-3.5 w-3.5" />
        </Link>
      </div>
      <LayoutGroup>
        <div className="flex flex-wrap justify-center gap-2 rounded-lg border border-slate-200 bg-slate-100/80 p-1.5 shadow-inner shadow-black/[0.03] dark:border-white/10 dark:bg-white/[0.035] md:justify-start">
          {SOURCES.map((source, index) => {
            const active = activeIndex === index;
            return (
              <Link
                key={source.name}
                to="/app/connectors"
                onMouseEnter={() => setActiveIndex(index)}
                onFocus={() => setActiveIndex(index)}
                className="relative isolate inline-flex min-h-11 items-center gap-2 overflow-hidden rounded-md px-3 py-2 text-sm font-bold text-slate-700 transition dark:text-neutral-200"
              >
                {active ? (
                  <motion.span
                    data-testid="source-active-block"
                    layoutId="source-active-block"
                    className="absolute inset-0 -z-10 rounded-md bg-white shadow-sm ring-1 ring-slate-200 dark:bg-white/[0.08] dark:ring-white/[0.12]"
                    transition={{ type: "spring", stiffness: 260, damping: 28 }}
                  />
                ) : null}
                <span className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-md ${source.color}`}>
                  {source.icon}
                </span>
                <span>{source.name}</span>
                <span className="hidden text-xs font-medium text-slate-400 dark:text-neutral-500 sm:inline">{source.detail}</span>
              </Link>
            );
          })}
        </div>
      </LayoutGroup>
    </section>
  );
}

function AgentNativeSection() {
  return (
    <motion.section
      initial="hidden"
      whileInView="visible"
      viewport={{ once: true, margin: "-80px" }}
      variants={fadeUp}
      transition={{ duration: 0.45, ease: [0.22, 1, 0.36, 1] }}
      className="border-t border-slate-200 py-7 dark:border-white/10"
    >
      <div className="grid gap-4 md:grid-cols-[0.86fr_1.14fr] md:items-stretch">
        <div className="rounded-lg border border-slate-200 bg-white p-5 dark:border-white/10 dark:bg-white/[0.055]">
          <div className="flex items-center gap-2 text-[11px] font-bold uppercase text-slate-400 dark:text-neutral-500">
            <Bot className="h-4 w-4 text-violet-500" />
            For AI agents
          </div>
          <h2 className="mt-3 text-2xl font-bold text-slate-950 dark:text-white">
            Every run should start with the same source-backed project memory.
          </h2>
          <p className="mt-3 text-sm leading-6 text-slate-500 dark:text-neutral-400">
            Context Engine gives agents a grounded view of what changed, what is blocked, which decisions matter, and where the evidence came from.
          </p>
          <div className="mt-5 flex flex-wrap gap-2 text-[11px] font-bold uppercase text-slate-500 dark:text-neutral-500">
            <span className="inline-flex items-center gap-1.5 rounded-md bg-slate-100 px-2.5 py-1.5 dark:bg-white/10">
              <TerminalSquare className="h-3.5 w-3.5 text-blue-500" />
              MCP bridge
            </span>
            <span className="inline-flex items-center gap-1.5 rounded-md bg-slate-100 px-2.5 py-1.5 dark:bg-white/10">
              <ShieldCheck className="h-3.5 w-3.5 text-emerald-500" />
              Provenance kept
            </span>
            <span className="inline-flex items-center gap-1.5 rounded-md bg-slate-100 px-2.5 py-1.5 dark:bg-white/10">
              <PackageCheck className="h-3.5 w-3.5 text-violet-500" />
              Handoff packets
            </span>
          </div>
        </div>

        <div className="rounded-lg border border-slate-200 bg-white p-3 shadow-sm dark:border-white/10 dark:bg-white/[0.055]">
          <div className="grid gap-2 overflow-hidden">
            {AGENT_STEPS.map((step, index) => {
              const Icon = step.icon;
              return (
                <motion.div
                  key={step.title}
                  initial={{ opacity: 0, x: 12 }}
                  whileInView={{ opacity: 1, x: 0 }}
                  viewport={{ once: true, margin: "-80px" }}
                  transition={{ duration: 0.35, delay: index * 0.08, ease: [0.22, 1, 0.36, 1] }}
                  className="flex min-w-0 items-start gap-3 overflow-hidden rounded-md border border-slate-200 bg-slate-50 px-4 py-4 dark:border-white/10 dark:bg-black/25"
                >
                  <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-white text-slate-700 shadow-sm dark:bg-white/10 dark:text-neutral-200">
                    <Icon className="h-4 w-4" />
                  </span>
                  <span className="min-w-0">
                    <span className="block text-sm font-black text-slate-950 dark:text-white">{step.title}</span>
                    <span className="mt-1 block text-xs leading-5 text-slate-500 dark:text-neutral-400">{step.body}</span>
                  </span>
                </motion.div>
              );
            })}
          </div>
        </div>
      </div>
    </motion.section>
  );
}

function LandingFooter() {
  return (
    <footer className="border-t border-slate-200 py-7 dark:border-white/10">
      <div className="grid gap-6 md:grid-cols-[1.1fr_0.9fr] md:items-start">
        <div>
          <Link to="/" className="inline-flex items-center gap-2">
            <CeIcon size={26} />
            <span className="text-base font-black text-slate-950 dark:text-white">Context Engine</span>
          </Link>
          <p className="mt-3 max-w-xl text-sm leading-6 text-slate-500 dark:text-neutral-400">
            Open-source project memory for solo founders and small teams using coding agents heavily. The product is a source ledger, graph, query layer, and handoff surface, not a generic enterprise search tool.
          </p>
          <div className="mt-4 flex flex-wrap gap-2 text-[11px] font-bold uppercase text-slate-500 dark:text-neutral-500">
            <span className="inline-flex items-center gap-1.5 rounded-md bg-white px-2.5 py-1.5 ring-1 ring-slate-200 dark:bg-white/[0.055] dark:ring-white/10">
              <ShieldCheck className="h-3.5 w-3.5 text-emerald-500" />
              Source-backed
            </span>
            <span className="inline-flex items-center gap-1.5 rounded-md bg-white px-2.5 py-1.5 ring-1 ring-slate-200 dark:bg-white/[0.055] dark:ring-white/10">
              <AlertTriangle className="h-3.5 w-3.5 text-amber-500" />
              Unsupported stays unsupported
            </span>
            <span className="inline-flex items-center gap-1.5 rounded-md bg-white px-2.5 py-1.5 ring-1 ring-slate-200 dark:bg-white/[0.055] dark:ring-white/10">
              <RefreshCw className="h-3.5 w-3.5 text-blue-500" />
              Built from evidence
            </span>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3 text-sm">
          <div>
            <h3 className="text-xs font-black uppercase text-slate-400 dark:text-neutral-500">App</h3>
            <div className="mt-3 grid gap-2">
              {FOOTER_LINKS.map((link) => (
                <Link key={link.to} to={link.to} className="font-bold text-slate-600 transition hover:text-slate-950 dark:text-neutral-300 dark:hover:text-white">
                  {link.label}
                </Link>
              ))}
            </div>
          </div>
          <div>
            <h3 className="text-xs font-black uppercase text-slate-400 dark:text-neutral-500">Project</h3>
            <div className="mt-3 grid gap-2">
              <a href={GITHUB_URL} target="_blank" rel="noreferrer" className="font-bold text-slate-600 transition hover:text-slate-950 dark:text-neutral-300 dark:hover:text-white">
                GitHub repo
              </a>
              <a href={`${GITHUB_URL}/blob/main/docs/connectors.md`} target="_blank" rel="noreferrer" className="font-bold text-slate-600 transition hover:text-slate-950 dark:text-neutral-300 dark:hover:text-white">
                Connector status
              </a>
              <a href={`${GITHUB_URL}/blob/main/docs/ai-context.md`} target="_blank" rel="noreferrer" className="font-bold text-slate-600 transition hover:text-slate-950 dark:text-neutral-300 dark:hover:text-white">
                AI context
              </a>
            </div>
          </div>
        </div>
      </div>
    </footer>
  );
}

function OpenCodeMark() {
  return (
    <span className="flex h-6 w-6 items-center justify-center rounded-md bg-slate-950 ring-1 ring-black/10 dark:bg-white dark:ring-white/20">
      <img src={opencodeIcon} alt="" className="h-4 w-4 object-contain" />
    </span>
  );
}

function GitHubMark({ className = "" }) {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true" className={className}>
      <path d="M12 .7C5.6.7.5 5.9.5 12.3c0 5.1 3.3 9.5 7.9 11 .6.1.8-.3.8-.6v-2.2c-3.2.7-3.9-1.4-3.9-1.4-.5-1.4-1.3-1.8-1.3-1.8-1.1-.7.1-.7.1-.7 1.2.1 1.8 1.2 1.8 1.2 1.1 1.8 2.8 1.3 3.5 1 .1-.8.4-1.3.8-1.6-2.6-.3-5.3-1.3-5.3-5.7 0-1.3.4-2.3 1.2-3.1-.1-.3-.5-1.5.1-3.1 0 0 1-.3 3.2 1.2a11 11 0 0 1 5.8 0c2.2-1.5 3.2-1.2 3.2-1.2.6 1.6.2 2.8.1 3.1.8.8 1.2 1.8 1.2 3.1 0 4.4-2.7 5.4-5.3 5.7.4.4.8 1.1.8 2.2v3.3c0 .3.2.7.8.6a11.6 11.6 0 0 0 7.9-11C23.5 5.9 18.4.7 12 .7Z" />
    </svg>
  );
}
