import { useRef, useState } from "react";
import { motion } from "framer-motion";
import { Link } from "react-router-dom";
import {
  AlertTriangle,
  ArrowRight,
  Bot,
  CircleDot,
  FileText,
  GitBranch,
  GitPullRequest,
  Layers3,
  Lightbulb,
  MessageSquare,
  PackageCheck,
  Search,
  ShieldCheck,
  Sparkles,
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

const GRAPH_NODES = [
  { id: "claude", label: "Claude session", meta: "Auth architecture", x: 13, y: 23, icon: Bot, tone: "violet" },
  { id: "decision", label: "Decision", meta: "Use session tokens", x: 38, y: 18, icon: Lightbulb, tone: "amber" },
  { id: "pr", label: "PR #184", meta: "Auth migration", x: 62, y: 35, icon: GitPullRequest, tone: "blue" },
  { id: "blocker", label: "Blocker", meta: "Schema approval", x: 84, y: 22, icon: AlertTriangle, tone: "red" },
  { id: "docs", label: "Broken docs", meta: "Old OAuth flow", x: 61, y: 73, icon: FileText, tone: "red" },
  { id: "issue", label: "Issue #72", meta: "Stale callback", x: 33, y: 72, icon: CircleDot, tone: "slate" },
  { id: "next", label: "Next agent task", meta: "Fix schema + docs", x: 86, y: 72, icon: Sparkles, tone: "green" },
];

const GRAPH_EDGES = [
  ["claude", "decision"],
  ["decision", "pr"],
  ["pr", "blocker"],
  ["pr", "docs"],
  ["issue", "docs"],
  ["blocker", "next"],
  ["docs", "next"],
];

const GRAPH_CARDS = [
  {
    number: "01",
    title: "Capture the work",
    body: "Import Codex, Claude Code, and OpenCode sessions alongside GitHub PRs, issues, chats, and docs.",
    icon: Upload,
  },
  {
    number: "02",
    title: "Map the relationships",
    body: "See how decisions, blockers, files, PRs, ideas, and agent runs connect across the project.",
    icon: GitBranch,
  },
  {
    number: "03",
    title: "Act from the graph",
    body: "Spot gaps, create next steps, and generate a clean handoff for yourself or the next agent.",
    icon: PackageCheck,
  },
];

const TEMPLATES = [
  {
    title: "Generate next-agent packet",
    body: "Package the relevant goal, decisions, blockers, files, and next tasks.",
    icon: PackageCheck,
  },
  {
    title: "Find project gaps",
    body: "Surface disconnected work, missing implementation, and unresolved blockers.",
    icon: Search,
  },
  {
    title: "Show stale decisions",
    body: "Find decisions that no longer match the code, issue, PR, or documentation.",
    icon: AlertTriangle,
  },
];

const container = {
  hidden: { opacity: 0 },
  visible: { opacity: 1, transition: { staggerChildren: 0.1 } },
};

const item = {
  hidden: { opacity: 0, y: 18 },
  visible: { opacity: 1, y: 0, transition: { duration: 0.5, ease: "easeOut" } },
};

export default function Landing() {
  return (
    <div className="min-h-screen overflow-x-hidden bg-[#f4f4f2] text-[#111113] dark:bg-[#050505] dark:text-white">
      <Header />

      <main>
        <section className="relative border-b border-black/10 dark:border-white/10">
          <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(to_right,rgba(17,17,19,0.055)_1px,transparent_1px),linear-gradient(to_bottom,rgba(17,17,19,0.055)_1px,transparent_1px)] bg-[size:48px_48px] [mask-image:linear-gradient(to_bottom,black,transparent_92%)] dark:bg-[linear-gradient(to_right,rgba(255,255,255,0.05)_1px,transparent_1px),linear-gradient(to_bottom,rgba(255,255,255,0.05)_1px,transparent_1px)]" />

          <div className="relative mx-auto grid min-h-[calc(100vh-65px)] max-w-[1500px] lg:grid-cols-[0.72fr_1.28fr]">
            <motion.div
              initial="hidden"
              animate="visible"
              variants={container}
              className="flex flex-col justify-between border-black/10 px-6 py-14 md:px-10 md:py-20 lg:border-r lg:px-14"
            >
              <div>
                <motion.div variants={item} className="mb-9 flex items-center gap-2">
                  <span className="h-2 w-2 rounded-full bg-[#6d5dfc] shadow-[0_0_18px_rgba(109,93,252,0.7)]" />
                  <span className="text-[11px] font-bold uppercase tracking-[0.18em] text-black/48 dark:text-white/48">
                    Open-source project graph for AI builders
                  </span>
                </motion.div>

                <motion.h1
                  variants={item}
                  className="max-w-[680px] text-[3.6rem] font-medium leading-[0.94] tracking-[-0.065em] md:text-[5.1rem] lg:text-[4.55rem] 2xl:text-[5.5rem]"
                >
                  See your AI-built project as a{" "}
                  <span className="text-[#6d5dfc]">living graph.</span>
                </motion.h1>

                <motion.p
                  variants={item}
                  className="mt-7 max-w-xl text-lg font-normal leading-relaxed text-black/58 dark:text-white/55"
                >
                  Context Engine turns scattered agent runs, PRs, issues, chats, and decisions into
                  a visual map of what happened, what is blocked, and what should happen next.
                </motion.p>

                <motion.p variants={item} className="mt-4 max-w-xl text-sm leading-relaxed text-black/42 dark:text-white/42">
                  Explore the graph. Connect ideas. Spot gaps. Start the next human or agent with the
                  full project state.
                </motion.p>

                <motion.div variants={item} className="mt-9 flex flex-wrap gap-3">
                  <Link
                    to="/app/graph"
                    className="group inline-flex items-center gap-3 bg-[#111113] px-6 py-3.5 text-sm font-bold text-white transition hover:bg-[#6d5dfc] dark:bg-white dark:text-black dark:hover:bg-[#a99fff]"
                  >
                    Explore demo graph
                    <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-1" />
                  </Link>
                  <Link
                    to="/app/connectors"
                    className="inline-flex items-center gap-3 border border-black/25 px-6 py-3.5 text-sm font-bold transition hover:border-black dark:border-white/25 dark:hover:border-white"
                  >
                    Import your project
                    <Upload className="h-4 w-4" />
                  </Link>
                </motion.div>
              </div>

              <motion.div variants={item} className="mt-14 flex flex-wrap items-center gap-x-7 gap-y-3 border-t border-black/10 pt-5 dark:border-white/10">
                <Proof icon={GitHubMark} text="Open source" />
                <Proof icon={ShieldCheck} text="Your data stays yours" />
                <Proof icon={TerminalSquare} text="Bring your own API key" />
              </motion.div>
            </motion.div>

            <motion.div
              initial={{ opacity: 0, scale: 0.97 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={{ duration: 0.7, delay: 0.16 }}
              className="flex min-h-[650px] items-center justify-center px-4 py-8 md:px-8 lg:px-10"
            >
              <LiveProjectGraph />
            </motion.div>
          </div>
        </section>

        <SourceStrip />

        <section id="why-graph" className="border-b border-black/10 dark:border-white/10">
          <div className="mx-auto grid max-w-[1500px] lg:grid-cols-[0.72fr_1.28fr]">
            <div className="border-black/10 p-8 md:p-14 lg:border-r">
              <p className="text-[11px] font-bold uppercase tracking-[0.18em] text-[#6d5dfc]">Why graph?</p>
              <h2 className="mt-6 text-4xl font-medium leading-[1.02] tracking-[-0.05em] md:text-6xl">
                Every change affects something else.
              </h2>
              <p className="mt-7 max-w-md text-lg leading-relaxed text-black/54 dark:text-white/50">
                Every agent run creates context. Every PR changes the plan. Every decision affects
                future work. Context Engine connects them into one project graph you can explore,
                edit, and hand off.
              </p>
            </div>

            <div className="relative min-h-[500px] overflow-hidden p-7 md:p-12">
              <div className="absolute inset-0 bg-[linear-gradient(to_right,rgba(17,17,19,0.055)_1px,transparent_1px),linear-gradient(to_bottom,rgba(17,17,19,0.055)_1px,transparent_1px)] bg-[size:42px_42px] dark:bg-[linear-gradient(to_right,rgba(255,255,255,0.05)_1px,transparent_1px),linear-gradient(to_bottom,rgba(255,255,255,0.05)_1px,transparent_1px)]" />
              <GraphStory />
            </div>
          </div>
        </section>

        <section id="product" className="border-b border-black/10 dark:border-white/10">
          <div className="mx-auto max-w-[1500px]">
            <div className="grid border-b border-black/10 dark:border-white/10 lg:grid-cols-[0.72fr_1.28fr]">
              <div className="border-black/10 p-8 md:p-14 lg:border-r">
                <p className="text-[11px] font-bold uppercase tracking-[0.18em] text-[#6d5dfc]">The product</p>
                <h2 className="mt-6 text-4xl font-medium leading-[1.02] tracking-[-0.05em] md:text-6xl">
                  One graph for every moving part of your project.
                </h2>
              </div>
              <div className="flex items-end p-8 md:p-14">
                <p className="max-w-2xl text-xl leading-relaxed text-black/54 dark:text-white/50">
                  Built for solo founders, indie hackers, and AI coding-agent power users moving
                  across Cursor, Claude Code, Codex, OpenCode, and GitHub.
                </p>
              </div>
            </div>

            <motion.div
              initial="hidden"
              whileInView="visible"
              viewport={{ once: true, margin: "-80px" }}
              variants={container}
              className="grid md:grid-cols-3"
            >
              {GRAPH_CARDS.map((card) => (
                <motion.article
                  key={card.number}
                  variants={item}
                  className="group min-h-[390px] border-b border-black/10 p-8 transition-colors hover:bg-white/60 dark:border-white/10 dark:hover:bg-white/[0.025] md:border-b-0 md:border-r md:last:border-r-0 md:p-10"
                >
                  <div className="flex items-center justify-between">
                    <span className="font-mono text-xs text-black/35 dark:text-white/35">{card.number}</span>
                    <card.icon className="h-5 w-5 text-black/35 transition-colors group-hover:text-[#6d5dfc] dark:text-white/35" />
                  </div>
                  <h3 className="mt-24 text-3xl font-medium tracking-[-0.035em]">{card.title}</h3>
                  <p className="mt-5 text-base leading-relaxed text-black/52 dark:text-white/48">{card.body}</p>
                </motion.article>
              ))}
            </motion.div>
          </div>
        </section>

        <section className="border-b border-black/10 dark:border-white/10">
          <div className="mx-auto grid max-w-[1500px] lg:grid-cols-2">
            <div className="border-b border-black/10 p-8 dark:border-white/10 md:p-14 lg:border-b-0 lg:border-r">
              <p className="text-[11px] font-bold uppercase tracking-[0.18em] text-[#6d5dfc]">Killer use case</p>
              <h2 className="mt-6 max-w-xl text-4xl font-medium leading-[1.02] tracking-[-0.05em] md:text-6xl">
                Upload a coding session. Get a project graph.
              </h2>
              <p className="mt-7 max-w-xl text-lg leading-relaxed text-black/54 dark:text-white/50">
                Paste a Claude, Codex, or OpenCode session. Context Engine preserves the raw source,
                extracts decisions, tasks, blockers, and file references, then places them in the
                project graph.
              </p>
              <Link to="/app/connectors" className="mt-9 inline-flex items-center gap-3 bg-[#6d5dfc] px-6 py-3.5 text-sm font-bold text-white transition hover:bg-[#5848ef]">
                Import a session
                <ArrowRight className="h-4 w-4" />
              </Link>
            </div>
            <SessionToGraph />
          </div>
        </section>

        <section className="border-b border-black/10 dark:border-white/10">
          <div className="mx-auto max-w-[1500px] px-6 py-24 md:px-10 md:py-28">
            <div className="flex flex-col gap-5 md:flex-row md:items-end md:justify-between">
              <div>
                <p className="text-[11px] font-bold uppercase tracking-[0.18em] text-[#6d5dfc]">Graph actions</p>
                <h2 className="mt-5 text-4xl font-medium tracking-[-0.045em] md:text-6xl">Start from a useful question.</h2>
              </div>
              <p className="max-w-md text-black/50 dark:text-white/46">Use the graph to move the project forward—not just inspect it.</p>
            </div>
            <div className="mt-12 grid gap-px overflow-hidden border border-black/10 bg-black/10 dark:border-white/10 dark:bg-white/10 md:grid-cols-3">
              {TEMPLATES.map((template) => (
                <div key={template.title} className="group bg-[#f4f4f2] p-8 transition hover:bg-white dark:bg-[#050505] dark:hover:bg-[#0c0c0c] md:p-10">
                  <template.icon className="h-5 w-5 text-[#6d5dfc]" />
                  <h3 className="mt-14 text-2xl font-medium tracking-[-0.03em]">{template.title}</h3>
                  <p className="mt-4 leading-relaxed text-black/50 dark:text-white/46">{template.body}</p>
                  <span className="mt-8 inline-flex items-center gap-2 text-xs font-bold text-[#6d5dfc]">
                    Run from graph <ArrowRight className="h-3.5 w-3.5 transition-transform group-hover:translate-x-1" />
                  </span>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section className="px-5 py-20 md:px-10 md:py-28">
          <div className="relative mx-auto max-w-[1380px] overflow-hidden bg-[#111113] px-7 py-16 text-white dark:bg-white dark:text-black md:px-14 md:py-20">
            <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(to_right,rgba(255,255,255,0.08)_1px,transparent_1px),linear-gradient(to_bottom,rgba(255,255,255,0.08)_1px,transparent_1px)] bg-[size:44px_44px] dark:bg-[linear-gradient(to_right,rgba(0,0,0,0.07)_1px,transparent_1px),linear-gradient(to_bottom,rgba(0,0,0,0.07)_1px,transparent_1px)]" />
            <div className="relative flex flex-col gap-10 lg:flex-row lg:items-end lg:justify-between">
              <div>
                <p className="text-[11px] font-bold uppercase tracking-[0.18em] text-white/45 dark:text-black/45">
                  Your agents move fast. Your project memory should keep up.
                </p>
                <h2 className="mt-5 max-w-4xl text-4xl font-medium leading-[0.98] tracking-[-0.05em] md:text-7xl">
                  Map the project before the next change lands.
                </h2>
              </div>
              <div className="flex shrink-0 flex-wrap gap-3">
                <Link to="/app/graph" className="group inline-flex items-center gap-3 bg-white px-6 py-3.5 text-sm font-bold text-black transition hover:bg-[#a99fff] dark:bg-black dark:text-white">
                  Explore graph
                  <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-1" />
                </Link>
                <a href={GITHUB_URL} target="_blank" rel="noreferrer" className="inline-flex items-center gap-3 border border-white/30 px-6 py-3.5 text-sm font-bold dark:border-black/30">
                  <GitHubMark className="h-4 w-4" />
                  Star on GitHub
                </a>
              </div>
            </div>
          </div>
        </section>
      </main>

      <Footer />
    </div>
  );
}

function Header() {
  return (
    <header className="sticky top-0 z-50 border-b border-black/10 bg-[#f4f4f2]/90 backdrop-blur-xl dark:border-white/10 dark:bg-[#050505]/90">
      <div className="mx-auto flex h-16 max-w-[1500px] items-center justify-between px-5 md:px-10">
        <Link to="/" className="flex items-center gap-3">
          <CeIcon size={32} />
          <div>
            <p className="text-sm font-bold leading-none">Context Engine</p>
            <p className="mt-1 text-[9px] font-bold uppercase tracking-[0.15em] text-black/42 dark:text-white/42">
              Project graph for AI builders
            </p>
          </div>
        </Link>

        <nav className="hidden items-center gap-7 text-xs font-bold text-black/50 dark:text-white/50 md:flex">
          <a href="#why-graph" className="transition hover:text-black dark:hover:text-white">Why graph</a>
          <a href="#product" className="transition hover:text-black dark:hover:text-white">Product</a>
          <Link to="/app/connectors" className="transition hover:text-black dark:hover:text-white">Import</Link>
        </nav>

        <div className="flex items-center gap-3">
          <ThemeToggle />
          <a href={GITHUB_URL} target="_blank" rel="noreferrer" className="hidden items-center gap-2 text-xs font-bold sm:inline-flex">
            <GitHubMark className="h-4 w-4" />
            GitHub
          </a>
          <Link to="/app/graph" className="group inline-flex items-center gap-2 border border-black/25 px-4 py-2.5 text-xs font-bold transition hover:border-black dark:border-white/25 dark:hover:border-white">
            Open graph
            <ArrowRight className="h-3.5 w-3.5 transition-transform group-hover:translate-x-0.5" />
          </Link>
        </div>
      </div>
    </header>
  );
}

function LiveProjectGraph() {
  const graphRef = useRef(null);
  const draggingRef = useRef(null);
  const [nodes, setNodes] = useState(GRAPH_NODES);
  const [selected, setSelected] = useState("pr");

  const moveNode = (id, delta) => {
    const bounds = graphRef.current?.getBoundingClientRect();
    if (!bounds) return;
    setNodes((current) =>
      current.map((node) =>
        node.id === id
          ? {
              ...node,
              x: clamp(node.x + (delta.x / bounds.width) * 100, 7, 93),
              y: clamp(node.y + (delta.y / bounds.height) * 100, 10, 90),
            }
          : node,
      ),
    );
  };

  const startDrag = (id, event) => {
    event.preventDefault();
    setSelected(id);
    draggingRef.current = { id, x: event.clientX, y: event.clientY };
  };

  const continueDrag = (event) => {
    const current = draggingRef.current;
    if (!current) return;
    moveNode(current.id, {
      x: event.clientX - current.x,
      y: event.clientY - current.y,
    });
    draggingRef.current = { ...current, x: event.clientX, y: event.clientY };
  };

  const stopDrag = () => {
    draggingRef.current = null;
  };

  return (
    <div className="w-full max-w-[900px] overflow-hidden border border-black/15 bg-[#ecece9] shadow-[0_35px_100px_rgba(17,17,19,0.14)] dark:border-white/15 dark:bg-[#090909] dark:shadow-[0_40px_110px_rgba(0,0,0,0.6)]">
      <div className="flex items-center justify-between border-b border-black/10 px-5 py-4 dark:border-white/10">
        <div className="flex items-center gap-3">
          <div className="flex gap-1.5">
            <span className="h-2 w-2 rounded-full bg-red-400" />
            <span className="h-2 w-2 rounded-full bg-amber-400" />
            <span className="h-2 w-2 rounded-full bg-emerald-400" />
          </div>
          <span className="font-mono text-[10px] text-black/45 dark:text-white/45">acme / project graph</span>
        </div>
        <div className="flex items-center gap-4">
          <span className="hidden font-mono text-[9px] text-black/38 dark:text-white/38 sm:block">Drag any node</span>
          <span className="flex items-center gap-2 text-[9px] font-bold uppercase tracking-[0.14em] text-emerald-600 dark:text-emerald-400">
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-current" />
            Live
          </span>
        </div>
      </div>

      <div
        ref={graphRef}
        onPointerMove={continueDrag}
        onPointerUp={stopDrag}
        onPointerCancel={stopDrag}
        onPointerLeave={stopDrag}
        className="relative aspect-[1.45/1] min-h-[470px] overflow-hidden"
      >
        <div className="absolute inset-0 bg-[linear-gradient(to_right,rgba(17,17,19,0.07)_1px,transparent_1px),linear-gradient(to_bottom,rgba(17,17,19,0.07)_1px,transparent_1px)] bg-[size:34px_34px] dark:bg-[linear-gradient(to_right,rgba(255,255,255,0.06)_1px,transparent_1px),linear-gradient(to_bottom,rgba(255,255,255,0.06)_1px,transparent_1px)]" />
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_62%_48%,rgba(109,93,252,0.13),transparent_34%)]" />

        <svg className="pointer-events-none absolute inset-0 h-full w-full" viewBox="0 0 100 100" preserveAspectRatio="none">
          {GRAPH_EDGES.map(([fromId, toId], index) => {
            const from = nodes.find((node) => node.id === fromId);
            const to = nodes.find((node) => node.id === toId);
            if (!from || !to) return null;
            return (
              <g key={`${fromId}-${toId}`}>
                <line x1={from.x} y1={from.y} x2={to.x} y2={to.y} stroke="rgba(109,93,252,0.28)" strokeWidth="0.45" vectorEffect="non-scaling-stroke" />
                <motion.line
                  x1={from.x}
                  y1={from.y}
                  x2={to.x}
                  y2={to.y}
                  stroke="#8173ff"
                  strokeWidth="1.2"
                  strokeLinecap="round"
                  vectorEffect="non-scaling-stroke"
                  initial={{ pathLength: 0, opacity: 0 }}
                  animate={{ pathLength: 1, opacity: [0, 0.9, 0] }}
                  transition={{ duration: 2.8, repeat: Infinity, delay: index * 0.35, repeatDelay: 1 }}
                />
              </g>
            );
          })}
        </svg>

        {nodes.map((node, index) => (
          <GraphNode
            key={node.id}
            node={node}
            selected={selected === node.id}
            onStartDrag={(event) => startDrag(node.id, event)}
            delay={index * 0.05}
          />
        ))}

        <div className="absolute bottom-4 left-4 right-4 flex items-center justify-between border border-black/10 bg-[#f7f7f4]/90 px-4 py-3 backdrop-blur dark:border-white/10 dark:bg-[#111113]/90">
          <div className="flex min-w-0 items-center gap-3">
            <Layers3 className="h-4 w-4 shrink-0 text-[#6d5dfc]" />
            <p className="truncate text-[10px] font-bold">
              {nodes.find((node) => node.id === selected)?.label}{" "}
              <span className="font-normal text-black/42 dark:text-white/42">
                · {nodes.find((node) => node.id === selected)?.meta}
              </span>
            </p>
          </div>
          <span className="hidden font-mono text-[9px] text-black/35 dark:text-white/35 sm:block">7 nodes · 7 links</span>
        </div>
      </div>
    </div>
  );
}

function GraphNode({ node, selected, onStartDrag, delay }) {
  const Icon = node.icon;

  return (
    <motion.button
      type="button"
      onPointerDown={onStartDrag}
      initial={{ opacity: 0, scale: 0.8 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ duration: 0.35, delay }}
      className={`absolute z-10 cursor-grab select-none border px-3 py-2.5 text-left shadow-lg active:cursor-grabbing ${
        selected
          ? "border-[#6d5dfc] bg-white ring-4 ring-[#6d5dfc]/10 dark:bg-[#171719]"
          : "border-black/15 bg-[#f8f8f5] hover:border-[#6d5dfc]/60 dark:border-white/15 dark:bg-[#111113]"
      }`}
      style={{ left: `${node.x}%`, top: `${node.y}%`, x: "-50%", y: "-50%", touchAction: "none" }}
    >
      <div className="flex items-center gap-2.5">
        <span className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full ${nodeTone(node.tone)}`}>
          <Icon className="h-4 w-4" />
        </span>
        <span>
          <span className="block whitespace-nowrap text-[10px] font-bold">{node.label}</span>
          <span className="mt-0.5 block whitespace-nowrap font-mono text-[8px] text-black/38 dark:text-white/38">{node.meta}</span>
        </span>
      </div>
    </motion.button>
  );
}

function GraphStory() {
  const story = [
    { label: "Claude session", icon: Bot, tone: "violet" },
    { label: "Decision", icon: Lightbulb, tone: "amber" },
    { label: "PR #184", icon: GitPullRequest, tone: "blue" },
    { label: "Broken docs", icon: FileText, tone: "red" },
    { label: "Blocker", icon: AlertTriangle, tone: "red" },
    { label: "Next task", icon: Sparkles, tone: "green" },
  ];

  return (
    <div className="relative z-10 flex min-h-[400px] flex-col justify-center">
      <div className="grid gap-3 sm:grid-cols-3">
        {story.map((node, index) => (
          <div key={node.label} className="relative">
            <motion.div
              initial={{ opacity: 0, y: 16 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ duration: 0.4, delay: index * 0.1 }}
              className="flex min-h-28 items-center gap-3 border border-black/12 bg-[#f7f7f4]/90 p-4 dark:border-white/12 dark:bg-[#111113]/90"
            >
              <span className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full ${nodeTone(node.tone)}`}>
                <node.icon className="h-4 w-4" />
              </span>
              <span className="text-sm font-bold">{node.label}</span>
            </motion.div>
            {index < story.length - 1 ? (
              <ArrowRight className="absolute -right-2.5 top-1/2 z-20 hidden h-5 w-5 -translate-y-1/2 rounded-full bg-[#6d5dfc] p-1 text-white sm:block" />
            ) : null}
          </div>
        ))}
      </div>
      <p className="mt-7 text-center font-mono text-[10px] uppercase tracking-[0.15em] text-black/38 dark:text-white/38">
        Session → decision → implementation → drift → blocker → next action
      </p>
    </div>
  );
}

function SessionToGraph() {
  return (
    <div className="relative min-h-[560px] overflow-hidden p-8 md:p-14">
      <div className="absolute inset-0 bg-[linear-gradient(to_right,rgba(17,17,19,0.055)_1px,transparent_1px),linear-gradient(to_bottom,rgba(17,17,19,0.055)_1px,transparent_1px)] bg-[size:42px_42px] dark:bg-[linear-gradient(to_right,rgba(255,255,255,0.05)_1px,transparent_1px),linear-gradient(to_bottom,rgba(255,255,255,0.05)_1px,transparent_1px)]" />
      <div className="relative z-10 flex h-full flex-col justify-center">
        <div className="border border-black/12 bg-[#f7f7f4] p-5 dark:border-white/12 dark:bg-[#111113]">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <span className="flex h-9 w-9 items-center justify-center bg-[#d97757] text-xs font-black text-white">A</span>
              <div>
                <p className="text-sm font-bold">Claude session</p>
                <p className="font-mono text-[9px] text-black/38 dark:text-white/38">auth-refactor.md</p>
              </div>
            </div>
            <span className="text-[9px] font-bold uppercase tracking-[0.14em] text-emerald-600 dark:text-emerald-400">Parsed</span>
          </div>
          <div className="mt-5 space-y-2 font-mono text-[10px] leading-relaxed text-black/48 dark:text-white/48">
            <p>Decision: move auth to session tokens</p>
            <p>Blocker: migration schema is not approved</p>
            <p>Next: update docs after PR #184 lands</p>
          </div>
        </div>

        <div className="mx-auto flex h-16 w-px items-center justify-center bg-[#6d5dfc]/30">
          <motion.span
            className="h-2 w-2 rounded-full bg-[#6d5dfc]"
            animate={{ y: [-24, 24] }}
            transition={{ duration: 1.8, repeat: Infinity, ease: "easeInOut" }}
          />
        </div>

        <div className="grid grid-cols-3 gap-2">
          <ExtractedNode icon={Lightbulb} label="Decision" />
          <ExtractedNode icon={AlertTriangle} label="Blocker" />
          <ExtractedNode icon={GitPullRequest} label="PR link" />
        </div>
      </div>
    </div>
  );
}

function ExtractedNode({ icon: Icon, label }) {
  return (
    <div className="border border-black/12 bg-[#f7f7f4] p-4 text-center dark:border-white/12 dark:bg-[#111113]">
      <span className="mx-auto flex h-9 w-9 items-center justify-center rounded-full bg-[#6d5dfc]/12 text-[#6d5dfc]">
        <Icon className="h-4 w-4" />
      </span>
      <p className="mt-3 text-[10px] font-bold">{label}</p>
    </div>
  );
}

function Proof({ icon: Icon, text }) {
  return (
    <span className="flex items-center gap-2 text-[10px] font-bold uppercase tracking-[0.12em] text-black/48 dark:text-white/48">
      <Icon className="h-3.5 w-3.5 text-[#6d5dfc]" />
      {text}
    </span>
  );
}

function SourceStrip() {
  const sources = [
    { name: "Codex", icon: <img src={openaiIcon} alt="" className="h-5 w-5 object-contain dark:invert" />, accent: "from-emerald-400/25 to-cyan-400/10" },
    { name: "Claude", icon: <span className="flex h-5 w-5 items-center justify-center bg-[#d97757] text-[9px] font-black text-white">A</span>, accent: "from-orange-400/25 to-amber-400/10" },
    { name: "OpenCode", icon: <img src={opencodeIcon} alt="" className="h-5 w-5 rounded object-contain" />, accent: "from-slate-400/25 to-white/5" },
    { name: "GitHub", icon: <GitBranch className="h-5 w-5" />, accent: "from-violet-400/25 to-fuchsia-400/10" },
    { name: "Slack", icon: <MessageSquare className="h-5 w-5" />, accent: "from-sky-400/25 to-blue-400/10" },
    { name: "Google Drive", icon: <img src={gdriveIcon} alt="" className="h-5 w-5 object-contain" />, accent: "from-emerald-400/25 to-yellow-400/10" },
    { name: "Gmail", icon: <img src={gmailIcon} alt="" className="h-5 w-5 object-contain" />, accent: "from-red-400/25 to-orange-400/10" },
  ];

  return (
    <section className="overflow-hidden border-b border-black/10 bg-white/45 dark:border-white/10 dark:bg-white/[0.025]">
      <div className="mx-auto flex max-w-[1500px] flex-col md:flex-row">
        <div className="relative z-10 flex shrink-0 items-center gap-4 border-b border-black/10 bg-[#f4f4f2] px-6 py-5 dark:border-white/10 dark:bg-[#080808] md:w-72 md:border-b-0 md:border-r md:px-10">
          <span className="source-orbit relative flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-[#6d5dfc]/40">
            <span className="h-2 w-2 rounded-full bg-[#6d5dfc] shadow-[0_0_12px_#6d5dfc]" />
            <span className="absolute -top-1 left-1/2 h-1.5 w-1.5 -translate-x-1/2 rounded-full bg-cyan-400" />
            <span className="absolute bottom-0 left-0 h-1.5 w-1.5 rounded-full bg-violet-400" />
          </span>
          <p className="text-[10px] font-bold uppercase tracking-[0.16em] text-slate-600 dark:text-neutral-200">Graph sources</p>
        </div>
        <div className="relative min-w-0 flex-1 overflow-hidden py-3 [mask-image:linear-gradient(to_right,transparent,black_5%,black_95%,transparent)]">
          <div className="source-flow flex w-max items-center">
            {[0, 1].map((group) => (
              <div key={group} className="flex shrink-0 items-center gap-3 px-3" aria-hidden={group === 1}>
                {sources.map((source, index) => (
                  <Source key={`${group}-${source.name}`} name={source.name} accent={source.accent} delay={index * -0.55}>
                    {source.icon}
                  </Source>
                ))}
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

function Source({ name, children, accent, delay }) {
  return (
    <div className="group flex min-w-max items-center gap-3 border border-slate-300/80 bg-white/80 px-4 py-3 text-xs font-bold text-slate-800 shadow-sm dark:border-white/15 dark:bg-[#111113] dark:text-white">
      <span
        className={`source-icon-float flex h-8 w-8 items-center justify-center rounded-full bg-gradient-to-br ${accent} text-slate-800 ring-1 ring-black/5 dark:text-white dark:ring-white/10`}
        style={{ animationDelay: `${delay}s` }}
      >
        {children}
      </span>
      <span className="pr-1">{name}</span>
      <span className="h-1.5 w-1.5 rounded-full bg-[#6d5dfc] opacity-40 transition-opacity group-hover:opacity-100" />
    </div>
  );
}

function Footer() {
  return (
    <footer className="border-t border-black/10 dark:border-white/10">
      <div className="mx-auto flex max-w-[1500px] flex-col gap-6 px-6 py-10 md:flex-row md:items-center md:justify-between md:px-10">
        <div className="flex items-center gap-3">
          <CeIcon size={28} />
          <div>
            <p className="text-sm font-bold">Context Engine</p>
            <p className="text-[10px] text-black/42 dark:text-white/42">The open-source project graph for AI builders.</p>
          </div>
        </div>
        <div className="flex gap-6 text-xs font-bold text-black/45 dark:text-white/45">
          <Link to="/app/graph" className="transition hover:text-black dark:hover:text-white">Graph</Link>
          <Link to="/app/connectors" className="transition hover:text-black dark:hover:text-white">Import</Link>
          <a href={GITHUB_URL} target="_blank" rel="noreferrer" className="transition hover:text-black dark:hover:text-white">GitHub</a>
        </div>
      </div>
    </footer>
  );
}

function nodeTone(tone) {
  const tones = {
    violet: "bg-violet-500/12 text-violet-600 dark:text-violet-300",
    amber: "bg-amber-500/14 text-amber-700 dark:text-amber-300",
    blue: "bg-blue-500/12 text-blue-600 dark:text-blue-300",
    red: "bg-red-500/12 text-red-600 dark:text-red-300",
    green: "bg-emerald-500/12 text-emerald-600 dark:text-emerald-300",
    slate: "bg-slate-500/12 text-slate-600 dark:text-slate-300",
  };
  return tones[tone] || tones.slate;
}

function clamp(value, min, max) {
  return Math.min(Math.max(value, min), max);
}

function GitHubMark({ className = "" }) {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true" className={className}>
      <path d="M12 .7C5.6.7.5 5.9.5 12.3c0 5.1 3.3 9.5 7.9 11 .6.1.8-.3.8-.6v-2.2c-3.2.7-3.9-1.4-3.9-1.4-.5-1.4-1.3-1.8-1.3-1.8-1.1-.7.1-.7.1-.7 1.2.1 1.8 1.2 1.8 1.2 1.1 1.8 2.8 1.3 3.5 1 .1-.8.4-1.3.8-1.6-2.6-.3-5.3-1.3-5.3-5.7 0-1.3.4-2.3 1.2-3.1-.1-.3-.5-1.5.1-3.1 0 0 1-.3 3.2 1.2a11 11 0 0 1 5.8 0c2.2-1.5 3.2-1.2 3.2-1.2.6 1.6.2 2.8.1 3.1.8.8 1.2 1.8 1.2 3.1 0 4.4-2.7 5.4-5.3 5.7.4.4.8 1.1.8 2.2v3.3c0 .3.2.7.8.6a11.6 11.6 0 0 0 7.9-11C23.5 5.9 18.4.7 12 .7Z" />
    </svg>
  );
}
