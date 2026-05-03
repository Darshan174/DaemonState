import { useRef, useState } from "react";
import { Link } from "react-router-dom";
import { motion } from "framer-motion";
import {
  CheckCircle2, History, Cpu, ArrowRight,
  BookOpen, AlertCircle, Database, Zap, MessageSquare,
  Network, PlugZap, BrainCircuit, Clock, GitBranch
} from "lucide-react";
import ThemeToggle from "../components/ThemeToggle";
import CeIcon from "../components/CeIcon";
import gdriveIcon from "@assets/gdrive-icon.png";
import gmailIcon from "@assets/gmail-icon.png";
import openaiIcon from "@assets/openai-icon.png";
import opencodeIcon from "@assets/opencode-icon.png";

const PROBLEMS = [
  {
    icon: BookOpen,
    title: "Context drifts faster than docs update",
    body: "Product truth changes in Slack, GitHub, and Notion long before any clean document catches up. AI reads stale docs.",
  },
  {
    icon: Database,
    title: "Critical knowledge stays siloed",
    body: "Founders and lead engineers become the source of truth. Everyone else — including your AI agents — works off partial context.",
  },
  {
    icon: AlertCircle,
    title: "Wrong context is expensive",
    body: "A stale roadmap answer, contradictory pricing, or outdated architecture assumption can create real product and customer damage.",
  },
];

const HOW_IT_WORKS = [
  {
    number: "01",
    title: "Connect your sources",
    body: "Sync Slack, Zoom, Google Drive, Gmail, and AI session imports (Claude, Codex, OpenCode). Context Engine ingests messages, documents, and discussions in real time.",
    icon: PlugZap,
    color: "from-blue-500 to-cyan-500",
    chip: "OAuth connectors",
  },
  {
    number: "02",
    title: "AI extracts atomic facts",
    body: "Every document passes through an intelligent extraction pipeline. Facts are organized into domain models with temporal awareness — current, past, or future.",
    icon: BrainCircuit,
    color: "from-brand-500 to-violet-500",
    chip: "Bring your own key",
  },
  {
    number: "03",
    title: "Query with full provenance",
    body: "Ask questions and get grounded answers with source citations. Every fact traces back to the exact original document.",
    icon: MessageSquare,
    color: "from-violet-500 to-pink-500",
    chip: "Temporal awareness",
  },
];

const CAPABILITIES = [
  {
    icon: Network,
    title: "Knowledge Graph",
    body: "Visualize domain models, atomic facts, and cross-domain relationships extracted from your sources. Filter by model, source, or temporal status.",
  },
  {
    icon: CheckCircle2,
    title: "Structured Extraction",
    body: "AI reads every ingested document and produces structured components — decisions, actions, risks, and blockers — with source provenance attached.",
  },
  {
    icon: History,
    title: "What Changed Timeline",
    body: "Rewind your knowledge graph. View a clear timeline of source ingestions, extraction runs, and component updates across your workspace.",
  },
  {
    icon: MessageSquare,
    title: "Natural Language Queries",
    body: "Ask questions in plain language and get grounded answers. Every response cites the exact source document it was derived from.",
  },
];

const DIFFERENTIATORS = [
  "Built for fast-moving teams, not generic enterprise search.",
  "Self-hostable, source-backed system for complete data control.",
  "Maintains explicit current truth, historical truth, and future plans.",
  "Auditable, structured context for both humans and AI agents.",
];

const containerVariants = {
  hidden: { opacity: 0 },
  visible: { opacity: 1, transition: { staggerChildren: 0.12 } },
};

const itemVariants = {
  hidden: { opacity: 0, y: 24 },
  visible: { opacity: 1, y: 0, transition: { duration: 0.5, ease: "easeOut" } },
};

export default function Landing() {
  return (
    <div className="min-h-screen relative bg-slate-50 dark:bg-slate-950 text-slate-900 dark:text-slate-100 overflow-x-hidden transition-colors duration-300">
      {/* Background grid + blobs */}
      <div className="absolute inset-0 -z-10 h-full w-full bg-[linear-gradient(to_right,#8080800a_1px,transparent_1px),linear-gradient(to_bottom,#8080800a_1px,transparent_1px)] dark:bg-[linear-gradient(to_right,#ffffff06_1px,transparent_1px),linear-gradient(to_bottom,#ffffff06_1px,transparent_1px)] bg-[size:14px_24px]">
        <div className="absolute top-0 -left-4 w-96 h-96 bg-brand-300 dark:bg-brand-700 rounded-full mix-blend-multiply dark:mix-blend-screen filter blur-3xl opacity-25 dark:opacity-10 animate-blob" />
        <div className="absolute top-0 -right-4 w-96 h-96 bg-violet-300 dark:bg-violet-700 rounded-full mix-blend-multiply dark:mix-blend-screen filter blur-3xl opacity-25 dark:opacity-10 animate-blob" style={{ animationDelay: "2s" }} />
        <div className="absolute -bottom-8 left-20 w-96 h-96 bg-brand-400 dark:bg-brand-800 rounded-full mix-blend-multiply dark:mix-blend-screen filter blur-3xl opacity-20 dark:opacity-10 animate-blob" style={{ animationDelay: "4s" }} />
      </div>

      {/* Header */}
      <header className="sticky top-0 z-50 border-b border-slate-200/50 dark:border-slate-800/50 bg-white/70 dark:bg-slate-950/70 backdrop-blur-md transition-colors">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-3.5">
          <div className="flex items-center gap-3">
            <CeIcon size={38} />
            <div>
              <p className="text-sm font-bold text-slate-900 dark:text-white leading-tight">Context Engine</p>
              <p className="text-[11px] text-slate-500 dark:text-slate-400 leading-tight">Structured context for AI teams</p>
            </div>
          </div>

          <nav className="hidden items-center gap-6 text-sm font-medium text-slate-500 dark:text-slate-400 md:flex">
            <a href="#problem" className="transition-colors hover:text-brand-600 dark:hover:text-brand-400">Problem</a>
            <a href="#how" className="transition-colors hover:text-brand-600 dark:hover:text-brand-400">How it works</a>
            <a href="#fit" className="transition-colors hover:text-brand-600 dark:hover:text-brand-400">Why startups</a>
          </nav>

          <div className="flex items-center gap-3">
            <ThemeToggle />
            <Link
              to="/app"
              className="group relative flex items-center gap-2 overflow-hidden rounded-xl bg-brand-600 px-5 py-2.5 text-sm font-semibold text-white shadow-[0_0_15px_rgba(79,70,229,0.35)] transition-all duration-300 hover:bg-brand-500 hover:shadow-[0_0_28px_rgba(79,70,229,0.55)]"
            >
              <div className="absolute inset-0 flex h-full w-full justify-center [transform:skew(-12deg)_translateX(-100%)] group-hover:duration-700 group-hover:[transform:skew(-12deg)_translateX(100%)] z-10">
                <div className="relative h-full w-8 bg-white/20" />
              </div>
              <span className="relative z-20">Open Dashboard</span>
              <ArrowRight className="relative z-20 h-4 w-4 transition-transform group-hover:translate-x-1" />
            </Link>
          </div>
        </div>
      </header>

      <main>
        {/* ── Hero ─────────────────────────────────────── */}
        <section className="mx-auto grid max-w-6xl gap-12 px-6 py-24 lg:grid-cols-[minmax(0,1.15fr)_minmax(300px,0.85fr)] lg:items-center">
          <motion.div
            initial={{ opacity: 0, x: -30 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.65 }}
            className="space-y-8"
          >
            <div className="inline-flex items-center gap-2 rounded-full border border-brand-200 dark:border-brand-700 bg-brand-50 dark:bg-brand-900/40 px-4 py-1.5 text-xs font-bold uppercase tracking-wide text-brand-700 dark:text-brand-300 shadow-sm">
              <span className="relative flex h-2 w-2">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-brand-400 opacity-75" />
                <span className="relative inline-flex h-2 w-2 rounded-full bg-brand-500" />
              </span>
              Open-source · AI-native context infrastructure
            </div>

            <div className="space-y-5">
              <h1 className="max-w-3xl text-5xl font-black tracking-tight text-slate-950 dark:text-white md:text-[3.6rem] md:leading-[1.07]">
                The memory layer between your team and your{" "}
                <span className="inline-block text-transparent bg-clip-text bg-[linear-gradient(110deg,#4f46e5,40%,#a78bfa,55%,#4f46e5)] bg-[length:200%_100%] animate-shimmer">AI</span>.
              </h1>
              <p className="max-w-xl text-lg leading-relaxed text-slate-600 dark:text-slate-300">
                Connect your tools. AI extracts atomic facts into a living knowledge graph —
                temporally aware, source-backed, and queryable in natural language.
              </p>
            </div>

            <div className="flex flex-wrap items-center gap-4">
              <motion.div whileHover={{ scale: 1.04 }} whileTap={{ scale: 0.96 }} className="relative group">
                <div className="absolute -inset-1 rounded-2xl bg-brand-500/40 blur-xl transition-all duration-500 group-hover:bg-brand-500/60 animate-pulse" />
                <Link
                  to="/app"
                  className="group relative overflow-hidden flex items-center gap-2 rounded-2xl bg-brand-600 px-8 py-4 text-base font-bold text-white shadow-xl shadow-brand-600/25 transition-all duration-300 hover:bg-brand-500"
                >
                  <div className="absolute inset-0 flex h-full w-full justify-center [transform:skew(-12deg)_translateX(-100%)] group-hover:duration-700 group-hover:[transform:skew(-12deg)_translateX(100%)] z-10">
                    <div className="relative h-full w-10 bg-white/20" />
                  </div>
                  <span className="relative z-20">Start for free</span>
                  <ArrowRight className="h-5 w-5 relative z-20 transition-transform group-hover:translate-x-1" />
                </Link>
              </motion.div>
              <motion.a
                whileHover={{ scale: 1.04 }} whileTap={{ scale: 0.96 }}
                href="#how"
                className="rounded-2xl border border-slate-200 dark:border-slate-700 bg-white/80 dark:bg-slate-800/80 backdrop-blur-sm px-6 py-3.5 text-sm font-semibold text-slate-700 dark:text-slate-200 shadow-sm transition-all duration-300 hover:bg-slate-50 dark:hover:bg-slate-700"
              >
                See how it works ↓
              </motion.a>
            </div>

            <div className="grid gap-3 sm:grid-cols-3">
              <HeroStat icon={Network} label="Knowledge Graph" value="Graph-native" />
              <HeroStat icon={Clock} label="Temporal Layer" value="Past · Now · Future" />
              <HeroStat icon={Zap} label="Extraction" value="AI-powered" />
            </div>
          </motion.div>

          <motion.div
            initial={{ opacity: 0, scale: 0.94, y: 30 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            transition={{ duration: 0.75, delay: 0.2 }}
            className="rounded-[32px] border border-white/30 dark:border-slate-700/40 bg-white/50 dark:bg-slate-900/50 p-2 shadow-[0_32px_80px_-24px_rgba(79,70,229,0.18)] backdrop-blur-xl"
          >
            <ContextGraphAnimation />
          </motion.div>
        </section>

        {/* ── Logos marquee ───────────────────────────── */}
        <section className="border-y border-slate-200/50 dark:border-slate-800/50 bg-white/40 dark:bg-slate-900/40 py-10 backdrop-blur-sm overflow-hidden transition-colors">
          <div className="mx-auto max-w-6xl px-6 text-center mb-8">
            <p className="text-xs font-bold uppercase tracking-widest text-slate-400 dark:text-slate-500">Sync context from your favourite tools</p>
          </div>
          <div className="relative flex overflow-hidden group w-full opacity-60 hover:opacity-100 transition-opacity [mask-image:_linear-gradient(to_right,transparent_0,_black_128px,_black_calc(100%-128px),transparent_100%)]">
            <div className="animate-marquee flex min-w-full shrink-0 items-center justify-around gap-14 py-2">
              <Logos />
            </div>
            <div className="animate-marquee flex min-w-full shrink-0 items-center justify-around gap-14 py-2" aria-hidden="true">
              <Logos />
            </div>
          </div>
        </section>

        {/* ── Problem ─────────────────────────────────── */}
        <section id="problem" className="bg-white/70 dark:bg-slate-900/70 backdrop-blur-md transition-colors">
          <div className="mx-auto max-w-6xl px-6 py-24">
            <motion.div
              initial="hidden" whileInView="visible" viewport={{ once: true, margin: "-100px" }}
              variants={itemVariants}
              className="max-w-3xl"
            >
              <p className="text-sm font-bold uppercase tracking-widest text-brand-600 dark:text-brand-400">The Problem</p>
              <h2 className="mt-4 text-3xl font-bold tracking-tight text-slate-950 dark:text-white md:text-5xl">
                Your AI is only as good as the context you give it.{" "}
                <span className="text-slate-400 dark:text-slate-500">Most teams give it the wrong context.</span>
              </h2>
            </motion.div>

            <motion.div
              initial="hidden" whileInView="visible" viewport={{ once: true, margin: "-50px" }}
              variants={containerVariants}
              className="mt-12 grid gap-6 md:grid-cols-3"
            >
              {PROBLEMS.map((item) => (
                <motion.div variants={itemVariants} key={item.title} className="h-full">
                  <SpotlightCard className="group h-full p-8">
                    <div className="mb-6 inline-flex h-12 w-12 items-center justify-center rounded-2xl bg-brand-50 dark:bg-brand-900/40 text-brand-600 dark:text-brand-400 transition-colors group-hover:bg-brand-600 group-hover:text-white relative z-10">
                      <item.icon className="h-6 w-6" />
                    </div>
                    <h3 className="text-xl font-bold text-slate-900 dark:text-white relative z-10">{item.title}</h3>
                    <p className="mt-3 text-base leading-relaxed text-slate-600 dark:text-slate-300 relative z-10">{item.body}</p>
                  </SpotlightCard>
                </motion.div>
              ))}
            </motion.div>
          </div>
        </section>

        {/* ── How it works ────────────────────────────── */}
        <section id="how" className="mx-auto max-w-6xl px-6 py-24">
          <motion.div
            initial="hidden" whileInView="visible" viewport={{ once: true, margin: "-100px" }}
            variants={itemVariants}
            className="text-center max-w-2xl mx-auto mb-16"
          >
            <p className="text-sm font-bold uppercase tracking-widest text-brand-600 dark:text-brand-400">How it works</p>
            <h2 className="mt-4 text-3xl font-bold tracking-tight text-slate-950 dark:text-white md:text-5xl">
              From raw messages to{" "}
              <span className="text-transparent bg-clip-text bg-gradient-to-r from-brand-600 to-violet-500">structured intelligence</span>
            </h2>
            <p className="mt-4 text-lg text-slate-600 dark:text-slate-400 leading-relaxed">
              A three-stage pipeline that turns your scattered organizational knowledge into a queryable, AI-ready knowledge graph.
            </p>
          </motion.div>

          <div className="relative">
            {/* Connector line (desktop) */}
            <div className="hidden lg:block absolute top-[4.5rem] left-[calc(16.67%+2rem)] right-[calc(16.67%+2rem)] h-px bg-gradient-to-r from-blue-400/40 via-brand-400/40 to-violet-400/40" />

            <motion.div
              initial="hidden" whileInView="visible" viewport={{ once: true, margin: "-50px" }}
              variants={containerVariants}
              className="grid gap-8 lg:grid-cols-3"
            >
              {HOW_IT_WORKS.map((step, i) => (
                <motion.div variants={itemVariants} key={step.number}>
                  <div className="relative rounded-3xl border border-slate-200/80 dark:border-slate-700/80 bg-white dark:bg-slate-800/90 p-8 shadow-sm transition-all duration-300 hover:-translate-y-1.5 hover:shadow-xl hover:shadow-brand-500/10 group">
                    <div className="flex items-start gap-4 mb-5">
                      <div className={`relative flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl bg-gradient-to-br ${step.color} shadow-lg`}>
                        <step.icon className="h-7 w-7 text-white" />
                        <span className="absolute -top-2 -right-2 flex h-5 w-5 items-center justify-center rounded-full bg-white dark:bg-slate-800 border-2 border-slate-100 dark:border-slate-700 text-[9px] font-black text-slate-700 dark:text-slate-300">{i + 1}</span>
                      </div>
                      <span className="mt-1 inline-flex items-center rounded-full border border-brand-100 dark:border-brand-800/60 bg-brand-50 dark:bg-brand-900/30 px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wide text-brand-600 dark:text-brand-400">
                        {step.chip}
                      </span>
                    </div>
                    <h3 className="text-xl font-bold text-slate-900 dark:text-white mb-3">{step.title}</h3>
                    <p className="text-sm leading-relaxed text-slate-600 dark:text-slate-300">{step.body}</p>
                  </div>
                </motion.div>
              ))}
            </motion.div>
          </div>
        </section>

        {/* ── Extraction demo ─────────────────────────── */}
        <section className="bg-slate-950 py-24 overflow-hidden relative">
          <div className="absolute inset-0 bg-[radial-gradient(ellipse_80%_50%_at_50%_-10%,rgba(79,70,229,0.12),transparent)]" />
          <div className="mx-auto max-w-6xl px-6 relative">
            <motion.div
              initial="hidden" whileInView="visible" viewport={{ once: true, margin: "-100px" }}
              variants={itemVariants}
              className="text-center max-w-2xl mx-auto mb-14"
            >
              <p className="text-sm font-bold uppercase tracking-widest text-brand-400">AI Extraction in action</p>
              <h2 className="mt-4 text-3xl font-bold tracking-tight text-white md:text-4xl">
                Raw message → structured fact
              </h2>
              <p className="mt-4 text-slate-400">
                Context Engine reads your conversations and distills them into atomic, temporally-aware components your AI can actually use.
              </p>
            </motion.div>

            <motion.div
              initial={{ opacity: 0, y: 30 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, margin: "-60px" }}
              transition={{ duration: 0.6 }}
              className="grid gap-6 lg:grid-cols-[1fr_auto_1fr] items-center"
            >
              {/* Input card */}
              <div className="rounded-2xl border border-white/10 bg-white/5 p-6 backdrop-blur-sm">
                <div className="flex items-center gap-2.5 mb-5">
                  <div className="w-7 h-7 rounded-lg bg-[#4a154b] flex items-center justify-center">
                    <svg viewBox="0 0 24 24" className="w-4 h-4" fill="#fff"><path d="M5.042 15.165a2.528 2.528 0 0 1-2.52 2.523A2.528 2.528 0 0 1 0 15.165a2.527 2.527 0 0 1 2.522-2.52h2.52v2.52zm1.27 0a2.527 2.527 0 0 1 2.521-2.52 2.528 2.528 0 0 1 2.521 2.52v6.313A2.528 2.528 0 0 1 8.834 24a2.528 2.528 0 0 1-2.521-2.522v-6.313zM8.834 5.042a2.528 2.528 0 0 1-2.521-2.52A2.528 2.528 0 0 1 8.834 0a2.528 2.528 0 0 1 2.521 2.522v2.52H8.834zm0 1.27a2.528 2.528 0 0 1 2.521 2.521 2.528 2.528 0 0 1-2.521 2.521H2.522A2.528 2.528 0 0 1 0 8.834a2.528 2.528 0 0 1 2.522-2.521h6.312zm10.122 2.523a2.528 2.528 0 0 1 2.522-2.521A2.528 2.528 0 0 1 24 8.834a2.528 2.528 0 0 1-2.522 2.521h-2.522V8.835zm-1.27 0a2.528 2.528 0 0 1-2.521 2.521 2.528 2.528 0 0 1-2.521-2.521V2.522A2.528 2.528 0 0 1 15.166 0a2.528 2.528 0 0 1 2.52 2.522v6.313zM15.166 18.958a2.528 2.528 0 0 1 2.52 2.522A2.528 2.528 0 0 1 15.166 24a2.528 2.528 0 0 1-2.521-2.522v-2.52h2.521zm0-1.27a2.528 2.528 0 0 1-2.52-2.521 2.528 2.528 0 0 1 2.52-2.521h6.313A2.528 2.528 0 0 1 24 15.166a2.528 2.528 0 0 1-2.522 2.52h-6.313z"/></svg>
                  </div>
                  <div>
                    <span className="text-xs font-bold text-white">#product</span>
                    <span className="ml-2 text-[10px] text-slate-500">Slack · 2 min ago</span>
                  </div>
                </div>
                <div className="flex items-start gap-3">
                  <div className="w-8 h-8 rounded-full bg-gradient-to-br from-orange-400 to-red-500 flex items-center justify-center text-[11px] font-black text-white shrink-0">SR</div>
                  <div>
                    <span className="text-xs font-bold text-slate-300">sarah.r</span>
                    <p className="mt-1.5 text-sm text-slate-300 leading-relaxed">
                      Team — we're pausing the Enterprise tier launch until Q3. Pricing still TBD, waiting on legal sign-off from contracts team. @mike can you update the roadmap doc?
                    </p>
                  </div>
                </div>
              </div>

              {/* Arrow */}
              <div className="hidden lg:flex flex-col items-center gap-2">
                <div className="flex h-10 w-10 items-center justify-center rounded-full border border-brand-500/40 bg-brand-500/10">
                  <BrainCircuit className="h-5 w-5 text-brand-400" />
                </div>
                <ArrowRight className="h-5 w-5 text-brand-500" />
                <span className="text-[10px] font-bold uppercase tracking-wider text-brand-500">AI extracts</span>
              </div>

              {/* Output card */}
              <div className="rounded-2xl border border-brand-500/30 bg-brand-950/50 dark:bg-brand-950/70 p-6 backdrop-blur-sm shadow-[0_0_40px_rgba(79,70,229,0.12)]">
                <div className="flex items-center justify-between mb-4">
                  <span className="text-[10px] font-bold uppercase tracking-widest text-brand-400">Extracted component</span>
                  <span className="flex items-center gap-1.5 text-[10px] font-bold text-emerald-400">
                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" /> active
                  </span>
                </div>
                <div className="space-y-3">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="rounded-full bg-brand-500/20 border border-brand-500/30 px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wide text-brand-300">Pricing</span>
                    <span className="rounded-full bg-violet-500/20 border border-violet-500/30 px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wide text-violet-300">decision</span>
                    <span className="rounded-full bg-violet-500/20 border border-violet-500/30 px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wide text-violet-300">future</span>
                  </div>
                  <p className="text-sm font-bold text-white leading-tight">Enterprise Tier Launch — Delayed to Q3</p>
                  <p className="text-xs text-slate-400 leading-relaxed">
                    Enterprise launch paused until Q3; pricing TBD pending legal team sign-off. Roadmap doc update requested.
                  </p>
                  <div className="pt-2 border-t border-white/10 flex items-center gap-3 text-[10px] text-slate-500">
                    <span>Confidence: <span className="text-emerald-400 font-bold">91%</span></span>
                    <span>·</span>
                    <span>Source: <span className="text-slate-400 font-medium">Slack #product</span></span>
                  </div>
                </div>
              </div>
            </motion.div>
          </div>
        </section>

        {/* ── Capabilities ────────────────────────────── */}
        <section id="solution" className="mx-auto max-w-6xl px-6 py-24">
          <motion.div
            initial="hidden" whileInView="visible" viewport={{ once: true, margin: "-100px" }}
            variants={itemVariants}
            className="max-w-3xl"
          >
            <p className="text-sm font-bold uppercase tracking-widest text-brand-600 dark:text-brand-400">Built-in capabilities</p>
            <h2 className="mt-4 text-3xl font-bold tracking-tight text-slate-950 dark:text-white md:text-5xl">
              A{" "}
              <span className="text-transparent bg-clip-text bg-gradient-to-r from-brand-600 to-violet-500">grounded memory</span>
              {" "}your whole team can trust.
            </h2>
          </motion.div>

          <motion.div
            initial="hidden" whileInView="visible" viewport={{ once: true, margin: "-50px" }}
            variants={containerVariants}
            className="mt-16 grid gap-6 md:grid-cols-2 lg:grid-cols-4"
          >
            {CAPABILITIES.map((item) => (
              <motion.div variants={itemVariants} key={item.title} className="h-full">
                <SpotlightCard className="group h-full p-8">
                  <div className="mb-5 inline-flex h-10 w-10 items-center justify-center rounded-xl bg-slate-50 dark:bg-slate-800 text-slate-600 dark:text-slate-300 transition-colors group-hover:bg-brand-50 dark:group-hover:bg-brand-900/40 group-hover:text-brand-600 dark:group-hover:text-brand-400 relative z-10">
                    <item.icon className="h-5 w-5" />
                  </div>
                  <h3 className="text-lg font-bold text-slate-900 dark:text-white relative z-10">{item.title}</h3>
                  <p className="mt-3 text-sm leading-relaxed text-slate-600 dark:text-slate-300 relative z-10">{item.body}</p>
                </SpotlightCard>
              </motion.div>
            ))}
          </motion.div>
        </section>

        {/* ── Why startups ────────────────────────────── */}
        <section id="fit" className="relative overflow-hidden bg-slate-950 text-white">
          <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_right,_rgba(79,70,229,0.13),_transparent_40%)]" />
          <div className="relative mx-auto grid max-w-6xl gap-16 px-6 py-24 lg:grid-cols-[1fr_1.1fr] lg:items-center">
            <motion.div
              initial="hidden" whileInView="visible" viewport={{ once: true, margin: "-100px" }}
              variants={itemVariants}
            >
              <p className="text-sm font-bold uppercase tracking-widest text-brand-400">Why teams choose this</p>
              <h2 className="mt-4 text-3xl font-bold tracking-tight md:text-5xl">
                Generic search finds documents.
                <br /><span className="text-slate-400">Context Engine knows what's true.</span>
              </h2>
              <p className="mt-6 max-w-xl text-lg leading-relaxed text-slate-300">
                Small teams carry more context density per person than any enterprise. Decisions
                move fast, documentation lags, and a single contradiction can damage a launch,
                customer call, or roadmap commitment.
              </p>
            </motion.div>

            <motion.div
              initial="hidden" whileInView="visible" viewport={{ once: true, margin: "-50px" }}
              variants={containerVariants}
              className="space-y-4"
            >
              {DIFFERENTIATORS.map((item, i) => (
                <motion.div
                  variants={itemVariants}
                  key={i}
                  className="group flex items-center gap-4 rounded-2xl border border-white/10 bg-white/5 px-6 py-5 transition-colors hover:bg-white/10 hover:border-brand-500/50"
                >
                  <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-brand-500/20 text-brand-400 group-hover:bg-brand-500 group-hover:text-white transition-colors duration-300">
                    <CheckCircle2 className="h-5 w-5" />
                  </div>
                  <p className="text-base font-medium leading-relaxed text-slate-200">{item}</p>
                </motion.div>
              ))}
            </motion.div>
          </div>
        </section>

        {/* ── CTA ─────────────────────────────────────── */}
        <section className="mx-auto max-w-6xl px-6 py-24">
          <motion.div
            initial={{ opacity: 0, scale: 0.96 }}
            whileInView={{ opacity: 1, scale: 1 }}
            viewport={{ once: true, margin: "-100px" }}
            transition={{ duration: 0.6 }}
            className="relative overflow-hidden rounded-[40px] border border-brand-100 dark:border-slate-700 bg-white dark:bg-slate-900 p-10 shadow-2xl shadow-brand-500/10 md:p-16 transition-colors"
          >
            <div className="absolute top-0 right-0 -mr-16 -mt-16 h-64 w-64 rounded-full bg-brand-500/10 blur-3xl" />
            <div className="absolute bottom-0 left-0 -ml-16 -mb-16 h-64 w-64 rounded-full bg-violet-400/10 blur-3xl" />
            <div className="absolute inset-0 bg-[linear-gradient(to_right,#8080800a_1px,transparent_1px),linear-gradient(to_bottom,#8080800a_1px,transparent_1px)] dark:bg-[linear-gradient(to_right,#ffffff04_1px,transparent_1px),linear-gradient(to_bottom,#ffffff04_1px,transparent_1px)] bg-[size:20px_20px]" />

            <div className="relative flex flex-col items-start gap-8 lg:flex-row lg:items-center lg:justify-between">
              <div className="max-w-xl space-y-4">
                <div className="flex items-center gap-3">
                  <CeIcon size={44} />
                  <p className="text-sm font-bold uppercase tracking-widest text-brand-600 dark:text-brand-400">Context Engine</p>
                </div>
                <h2 className="text-3xl font-bold tracking-tight text-slate-950 dark:text-white md:text-4xl">
                  Give your AI the context it actually needs.
                </h2>
                <p className="text-lg leading-relaxed text-slate-600 dark:text-slate-300">
                  Open-source, self-hostable, and built for teams that move fast. Start syncing your
                  tools in minutes and watch your knowledge graph come alive.
                </p>
              </div>

              <div className="flex flex-col gap-3 lg:items-end shrink-0">
                <motion.div whileHover={{ scale: 1.04 }} whileTap={{ scale: 0.96 }} className="relative group">
                  <div className="absolute -inset-1 rounded-2xl bg-brand-500/30 blur-xl transition-all duration-500 group-hover:bg-brand-500/50 animate-pulse" />
                  <Link
                    to="/app"
                    className="group flex items-center gap-2 rounded-2xl bg-brand-600 px-8 py-4 text-base font-bold text-white shadow-lg shadow-brand-500/25 transition-all duration-300 hover:bg-brand-500 relative z-10"
                  >
                    Open the dashboard
                    <ArrowRight className="h-5 w-5 transition-transform group-hover:translate-x-1" />
                  </Link>
                </motion.div>
                <p className="text-xs text-slate-400 dark:text-slate-500 text-center lg:text-right">Free · Open-source · No credit card</p>
              </div>
            </div>
          </motion.div>
        </section>
      </main>

      {/* ── Footer ──────────────────────────────────── */}
      <footer className="border-t border-slate-200/50 dark:border-slate-800/50 bg-white/80 dark:bg-slate-950/80 py-10 backdrop-blur-sm transition-colors">
        <div className="mx-auto flex max-w-6xl flex-col items-center justify-between gap-6 px-6 md:flex-row">
          <div className="flex items-center gap-3">
            <CeIcon size={30} />
            <div>
              <p className="text-sm font-bold text-slate-900 dark:text-white">Context Engine</p>
              <p className="text-xs text-slate-400">© {new Date().getFullYear()} · Open-source</p>
            </div>
          </div>
          <div className="flex gap-8 text-sm text-slate-500 dark:text-slate-400">
            <a href="#" className="transition-colors hover:text-brand-600 dark:hover:text-brand-400">Documentation</a>
            <a href="#" className="transition-colors hover:text-brand-600 dark:hover:text-brand-400">GitHub</a>
            <a href="#" className="transition-colors hover:text-brand-600 dark:hover:text-brand-400">Privacy</a>
          </div>
        </div>
      </footer>
    </div>
  );
}

function HeroStat({ icon: Icon, label, value }) {
  return (
    <div className="rounded-2xl border border-brand-100 dark:border-brand-800/50 bg-white/70 dark:bg-slate-800/70 px-4 py-3.5 shadow-sm backdrop-blur-sm transition-all hover:-translate-y-0.5 hover:border-brand-200 dark:hover:border-brand-700">
      <div className="flex items-center gap-2 mb-1">
        <Icon className="h-3.5 w-3.5 text-brand-500 dark:text-brand-400" />
        <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-brand-600 dark:text-brand-400">{label}</p>
      </div>
      <p className="text-sm font-bold text-slate-900 dark:text-white">{value}</p>
    </div>
  );
}

function SpotlightCard({ children, className = "" }) {
  const divRef = useRef(null);
  const [isFocused, setIsFocused] = useState(false);
  const [position, setPosition] = useState({ x: 0, y: 0 });
  const [opacity, setOpacity] = useState(0);

  const handleMouseMove = (e) => {
    if (!divRef.current || isFocused) return;
    const rect = divRef.current.getBoundingClientRect();
    setPosition({ x: e.clientX - rect.left, y: e.clientY - rect.top });
  };

  return (
    <div
      ref={divRef}
      onMouseMove={handleMouseMove}
      onFocus={() => { setIsFocused(true); setOpacity(1); }}
      onBlur={() => { setIsFocused(false); setOpacity(0); }}
      onMouseEnter={() => setOpacity(1)}
      onMouseLeave={() => setOpacity(0)}
      className={`relative overflow-hidden rounded-3xl border border-slate-200/80 dark:border-slate-700/80 bg-white dark:bg-slate-800/90 shadow-sm transition-all duration-300 hover:-translate-y-1.5 hover:border-brand-300 dark:hover:border-brand-600 hover:shadow-xl hover:shadow-brand-500/10 ${className}`}
    >
      <div
        className="pointer-events-none absolute -inset-px opacity-0 transition duration-300 z-0"
        style={{ opacity, background: `radial-gradient(400px circle at ${position.x}px ${position.y}px, rgba(99,102,241,0.08), transparent 40%)` }}
      />
      <div className="relative z-10 h-full w-full">{children}</div>
    </div>
  );
}

function Logos() {
  return (
    <>
      <LogoItem name="Slack"><path d="M5.042 15.165a2.528 2.528 0 0 1-2.52 2.523A2.528 2.528 0 0 1 0 15.165a2.527 2.527 0 0 1 2.522-2.52h2.52v2.52zm1.27 0a2.527 2.527 0 0 1 2.521-2.52 2.528 2.528 0 0 1 2.521 2.52v6.313A2.528 2.528 0 0 1 8.834 24a2.528 2.528 0 0 1-2.521-2.522v-6.313zM8.834 5.042a2.528 2.528 0 0 1-2.521-2.52A2.528 2.528 0 0 1 8.834 0a2.528 2.528 0 0 1 2.521 2.522v2.52H8.834zm0 1.27a2.528 2.528 0 0 1 2.521 2.521 2.528 2.528 0 0 1-2.521 2.521H2.522A2.528 2.528 0 0 1 0 8.834a2.528 2.528 0 0 1 2.522-2.521h6.312zm10.122 2.523a2.528 2.528 0 0 1 2.522-2.521A2.528 2.528 0 0 1 24 8.834a2.528 2.528 0 0 1-2.522 2.521h-2.522V8.835zm-1.27 0a2.528 2.528 0 0 1-2.521 2.521 2.528 2.528 0 0 1-2.521-2.521V2.522A2.528 2.528 0 0 1 15.166 0a2.528 2.528 0 0 1 2.52 2.522v6.313zM15.166 18.958a2.528 2.528 0 0 1 2.52 2.522A2.528 2.528 0 0 1 15.166 24a2.528 2.528 0 0 1-2.521-2.522v-2.52h2.521zm0-1.27a2.528 2.528 0 0 1-2.52-2.521 2.528 2.528 0 0 1 2.52-2.521h6.313A2.528 2.528 0 0 1 24 15.166a2.528 2.528 0 0 1-2.522 2.52h-6.313z"/></LogoItem>
      <LogoItem name="GitHub"><path d="M12 .297c-6.63 0-12 5.373-12 12 0 5.303 3.438 9.8 8.205 11.385.6.113.82-.258.82-.577 0-.285-.01-1.04-.015-2.04-3.338.724-4.042-1.61-4.042-1.61C4.422 18.07 3.633 17.7 3.633 17.7c-1.087-.744.084-.729.084-.729 1.205.084 1.838 1.236 1.838 1.236 1.07 1.835 2.809 1.305 3.495.998.108-.776.417-1.305.76-1.605-2.665-.3-5.466-1.332-5.466-5.93 0-1.31.465-2.38 1.235-3.22-.135-.303-.54-1.523.105-3.176 0 0 1.005-.322 3.3 1.23.96-.267 1.98-.399 3-.405 1.02.006 2.04.138 3 .405 2.28-1.552 3.285-1.23 3.285-1.23.645 1.653.24 2.873.12 3.176.765.84 1.23 1.91 1.23 3.22 0 4.61-2.805 5.625-5.475 5.92.42.36.81 1.096.81 2.22 0 1.606-.015 2.896-.015 3.286 0 .315.21.69.825.57C20.565 22.092 24 17.592 24 12.297c0-6.627-5.373-12-12-12"/></LogoItem>
      <LogoItem name="Zoom"><path d="M4.5 9A2.5 2.5 0 0 0 2 11.5v4A2.5 2.5 0 0 0 4.5 18h8A2.5 2.5 0 0 0 15 15.5v-4A2.5 2.5 0 0 0 12.5 9h-8zm11.2 5.5v-4a1 1 0 0 1 1.5-.86l4 2.5a1 1 0 0 1 0 1.72l-4 2.5a1 1 0 0 1-1.5-.86z"/></LogoItem>
      <div className="flex items-center gap-2.5 text-xl font-bold tracking-tight text-slate-700 dark:text-slate-300">
        <img src={gdriveIcon} alt="Google Drive" className="h-6 w-6 object-contain" />
        Google Drive
      </div>
      <div className="flex items-center gap-2.5 text-xl font-bold tracking-tight text-slate-700 dark:text-slate-300">
        <img src={gmailIcon} alt="Gmail" className="h-6 w-6 object-contain" />
        Gmail
      </div>
      <div className="flex items-center gap-2.5 text-xl font-bold tracking-tight text-slate-700 dark:text-slate-300">
        <img src={openaiIcon} alt="Codex" className="h-6 w-6 object-contain dark:invert" />
        Codex
      </div>
      <div className="flex items-center gap-2.5 text-xl font-bold tracking-tight text-slate-700 dark:text-slate-300">
        <div className="h-6 w-6 rounded-md flex items-center justify-center text-[10px] font-black text-white" style={{ background: "#D97757" }}>A</div>
        Claude
      </div>
      <div className="flex items-center gap-2.5 text-xl font-bold tracking-tight text-slate-700 dark:text-slate-300">
        <img src={opencodeIcon} alt="OpenCode" className="h-6 w-6 object-contain rounded" />
        OpenCode
      </div>
    </>
  );
}

function LogoItem({ name, children }) {
  return (
    <div className="flex items-center gap-2.5 text-xl font-bold tracking-tight text-slate-700 dark:text-slate-300">
      <svg role="img" viewBox="0 0 24 24" fill="currentColor" xmlns="http://www.w3.org/2000/svg" className="h-6 w-6">
        <title>{name}</title>
        {children}
      </svg>
      {name}
    </div>
  );
}

function ContextGraphAnimation() {
  return (
    <div className="relative w-full aspect-square rounded-[28px] bg-slate-950 overflow-hidden shadow-[inset_0_0_80px_rgba(0,0,0,0.7)] border border-slate-800">
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_center,rgba(79,70,229,0.22)_0%,transparent_65%)]" />
      <div className="absolute inset-0 bg-[linear-gradient(rgba(255,255,255,0.035)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,0.035)_1px,transparent_1px)] bg-[size:28px_28px] [mask-image:radial-gradient(ellipse_65%_65%_at_50%_50%,#000_20%,transparent_100%)]" />

      <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
        <motion.div animate={{ rotate: 360 }} transition={{ duration: 28, repeat: Infinity, ease: "linear" }} className="absolute w-52 h-52 border border-brand-500/25 rounded-full border-dashed" />
        <motion.div animate={{ rotate: -360 }} transition={{ duration: 45, repeat: Infinity, ease: "linear" }} className="absolute w-[22rem] h-[22rem] border border-brand-400/08 rounded-full" />
      </div>

      <svg className="absolute inset-0 w-full h-full pointer-events-none" viewBox="0 0 400 400" fill="none">
        <PulseLine x1="100" y1="100" x2="200" y2="200" delay={0} />
        <PulseLine x1="300" y1="110" x2="200" y2="200" delay={0.7} />
        <PulseLine x1="110" y1="300" x2="200" y2="200" delay={1.4} />
        <PulseLine x1="290" y1="290" x2="200" y2="200" delay={2.1} />
      </svg>

      <GraphNode x="25%" y="25%" delay={0} icon={<Database className="w-5 h-5" />} />
      <GraphNode x="75%" y="27.5%" delay={1} icon={<Cpu className="w-5 h-5" />} />
      <GraphNode x="27.5%" y="75%" delay={2} icon={<BookOpen className="w-5 h-5" />} />
      <GraphNode x="72.5%" y="72.5%" delay={1.5} icon={<GitBranch className="w-5 h-5" />} />

      {/* Center — use the icon */}
      <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
        <motion.div
          animate={{ boxShadow: ["0 0 20px rgba(79,70,229,0.3)", "0 0 60px rgba(99,102,241,0.8)", "0 0 20px rgba(79,70,229,0.3)"] }}
          transition={{ duration: 3, repeat: Infinity, ease: "easeInOut" }}
          className="z-10 rounded-[22px]"
        >
          <CeIcon size={88} className="drop-shadow-[0_0_18px_rgba(99,102,241,0.6)]" />
        </motion.div>
      </div>

      <div className="absolute bottom-5 inset-x-0 text-center pointer-events-none">
        <p className="text-[10px] uppercase font-bold tracking-[0.3em] text-brand-400/80">Knowledge Graph Active</p>
      </div>
    </div>
  );
}

function GraphNode({ x, y, icon, delay = 0 }) {
  return (
    <motion.div
      className="absolute flex h-14 w-14 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-2xl border border-white/10 bg-slate-800/80 text-brand-300 shadow-[0_0_20px_rgba(79,70,229,0.15)] backdrop-blur-md"
      style={{ left: x, top: y }}
      initial={{ y: 0 }}
      animate={{ y: [-6, 6, -6], rotateZ: [-2, 2, -2] }}
      transition={{ duration: 5, repeat: Infinity, ease: "easeInOut", delay }}
    >
      <div className="opacity-90">{icon}</div>
    </motion.div>
  );
}

function PulseLine({ x1, y1, x2, y2, delay }) {
  return (
    <>
      <line x1={x1} y1={y1} x2={x2} y2={y2} stroke="rgba(99,102,241,0.12)" strokeWidth="1.5" />
      <motion.line
        x1={x1} y1={y1} x2={x2} y2={y2}
        stroke="rgba(129,140,248,0.85)"
        strokeWidth="2.5"
        strokeLinecap="round"
        style={{ filter: "drop-shadow(0 0 7px rgba(129,140,248,0.8))" }}
        initial={{ pathLength: 0, opacity: 0 }}
        animate={{ pathLength: 1, opacity: [0, 1, 0] }}
        transition={{ duration: 2.2, repeat: Infinity, ease: "circIn", delay }}
      />
    </>
  );
}
