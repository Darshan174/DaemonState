import { useRef, useState } from "react";
import { Link } from "react-router-dom";
import { motion } from "framer-motion";
import { CheckCircle2, History, ShieldAlert, Cpu, ArrowRight, BookOpen, AlertCircle, Database } from "lucide-react";

const PROBLEMS = [
  {
    icon: BookOpen,
    title: "Context drifts faster than docs updates",
    body: "In small startups, product truth changes in Slack, GitHub, and Notion long before a clean document catches up.",
  },
  {
    icon: Database,
    title: "Critical knowledge is siloed",
    body: "Founders, PMs, and lead engineers become the source of truth. Everyone else, including AI, works off partial context.",
  },
  {
    icon: AlertCircle,
    title: "Wrong context is expensive",
    body: "A stale roadmap, wrong pricing answer, or contradictory PR can create real customer and execution damage.",
  },
];

const CAPABILITIES = [
  {
    icon: BookOpen,
    title: "Founder Brief & Review",
    body: "Automatically summarize what changed, what is risky, and resolve flagged conflicts in the Review Queue.",
  },
  {
    icon: CheckCircle2,
    title: "Decision Register",
    body: "Track current and historical decisions, including their rationale, blockers, and original source evidence.",
  },
  {
    icon: History,
    title: "What Changed Timeline",
    body: "Rewind your startup's brain. View a clear timeline across decision changes, tool ingests, and failures.",
  },
  {
    icon: ShieldAlert,
    title: "Launch Guard",
    body: "Check outbound copy and PRs against current company truth, review states, and verified facts.",
  },
];

const DIFFERENTIATORS = [
  "Built for fast-moving startup workflows, not generic enterprise search.",
  "Self-hostable, source-backed system for complete data control.",
  "Maintains explicit current truth, historical truth, and review states.",
  "Creates auditable, structurally proven context for both humans and AI agents.",
];

// Animation variants
const containerVariants = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: { staggerChildren: 0.15 },
  },
};

const itemVariants = {
  hidden: { opacity: 0, y: 20 },
  visible: { opacity: 1, y: 0, transition: { duration: 0.5, ease: "easeOut" } },
};

export default function Landing() {
  return (
    <div className="min-h-screen relative bg-slate-50 text-slate-900 overflow-x-hidden">
      {/* Animated modern background */}
      <div className="absolute inset-0 -z-10 h-full w-full bg-[linear-gradient(to_right,#8080800a_1px,transparent_1px),linear-gradient(to_bottom,#8080800a_1px,transparent_1px)] bg-[size:14px_24px]">
        <div className="absolute top-0 -left-4 w-96 h-96 bg-brand-300 rounded-full mix-blend-multiply filter blur-3xl opacity-30 animate-blob"></div>
        <div className="absolute top-0 -right-4 w-96 h-96 bg-brand-200 rounded-full mix-blend-multiply filter blur-3xl opacity-30 animate-blob" style={{ animationDelay: "2s" }}></div>
        <div className="absolute -bottom-8 left-20 w-96 h-96 bg-brand-400 rounded-full mix-blend-multiply filter blur-3xl opacity-30 animate-blob" style={{ animationDelay: "4s" }}></div>
      </div>
      <header className="sticky top-0 z-50 border-b border-slate-200/50 bg-white/70 backdrop-blur-md supports-[backdrop-filter]:bg-white/60">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
          <div className="flex items-center gap-3">
            <span className="flex h-10 w-10 items-center justify-center rounded-2xl bg-brand-600 shadow-[0_4px_20px_rgba(79,70,229,0.4)] text-sm font-semibold text-white">
              CE
            </span>
            <div>
              <p className="text-sm font-semibold text-slate-900">Context Engine</p>
              <p className="text-xs text-slate-500">Source-backed startup memory</p>
            </div>
          </div>

          <nav className="hidden items-center gap-6 text-sm font-medium text-slate-500 md:flex">
            <a href="#problem" className="transition-colors hover:text-brand-600">Problem</a>
            <a href="#solution" className="transition-colors hover:text-brand-600">Solution</a>
            <a href="#fit" className="transition-colors hover:text-brand-600">Why startups</a>
          </nav>

          <div className="flex items-center gap-3">
            <motion.div whileHover={{ scale: 1.05 }} whileTap={{ scale: 0.95 }}>
              <Link
                to="/app"
                className="group relative flex items-center gap-2 overflow-hidden rounded-xl bg-brand-600 px-5 py-2.5 text-sm font-semibold text-white shadow-[0_0_15px_rgba(79,70,229,0.4)] transition-all duration-300 hover:bg-brand-500 hover:shadow-[0_0_30px_rgba(79,70,229,0.6)]"
              >
                <div className="absolute inset-0 flex h-full w-full justify-center [transform:skew(-12deg)_translateX(-100%)] group-hover:duration-1000 group-hover:[transform:skew(-12deg)_translateX(100%)] z-10">
                  <div className="relative h-full w-8 bg-white/20" />
                </div>
                <span className="relative z-20">Go to Dashboard</span>
                <ArrowRight className="relative z-20 h-4 w-4 transition-transform group-hover:translate-x-1" />
                <div className="absolute inset-0 z-0 bg-gradient-to-r from-brand-600 via-brand-400 to-brand-600 opacity-0 transition-opacity duration-300 group-hover:opacity-100" />
              </Link>
            </motion.div>
          </div>
        </div>
      </header>

      <main>
        <section className="mx-auto grid max-w-6xl gap-12 px-6 py-24 lg:grid-cols-[minmax(0,1.1fr)_minmax(320px,0.9fr)] lg:items-center">
          <motion.div
            initial={{ opacity: 0, x: -30 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.6 }}
            className="space-y-8"
          >
            <div className="inline-flex items-center gap-2 rounded-full border border-brand-200 bg-brand-50 px-4 py-1.5 text-xs font-semibold uppercase tracking-wide text-brand-700 shadow-sm">
              <span className="relative flex h-2 w-2">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-brand-400 opacity-75"></span>
                <span className="relative inline-flex h-2 w-2 rounded-full bg-brand-500"></span>
              </span>
              Built for high-velocity teams
            </div>

            <div className="space-y-5">
              <h1 className="max-w-3xl text-5xl font-bold tracking-tight text-slate-950 md:text-6xl md:leading-[1.05]">
                Your startup moves <span className="inline-block text-transparent bg-clip-text bg-[linear-gradient(110deg,#4f46e5,45%,#818cf8,55%,#4f46e5)] bg-[length:200%_100%] animate-shimmer">faster</span> than its docs.
              </h1>
              <p className="max-w-2xl text-lg leading-relaxed text-slate-600">
                Context Engine turns Slack, Notion, GitHub, and other internal sources into a
                source-backed memory of what your company believes, what changed, and why.
              </p>
            </div>

            <div className="flex flex-wrap items-center gap-4">
              <motion.div whileHover={{ scale: 1.05 }} whileTap={{ scale: 0.95 }} className="relative group">
                <div className="absolute -inset-1 rounded-2xl bg-brand-500/40 blur-xl transition-all duration-500 group-hover:bg-brand-500/60 group-hover:duration-200 animate-pulse"></div>
                <Link
                  to="/app"
                  className="group relative overflow-hidden flex items-center gap-2 rounded-2xl bg-brand-600 px-8 py-4 text-base font-bold text-white shadow-xl shadow-brand-600/30 transition-all duration-300 hover:bg-brand-500 hover:shadow-2xl hover:shadow-brand-500/50"
                >
                  <div className="absolute inset-0 flex h-full w-full justify-center [transform:skew(-12deg)_translateX(-100%)] group-hover:duration-1000 group-hover:[transform:skew(-12deg)_translateX(100%)] z-10">
                    <div className="relative h-full w-10 bg-white/20" />
                  </div>
                  <span className="relative z-20">Try Context Engine</span>
                  <ArrowRight className="h-5 w-5 relative z-20 transition-transform group-hover:translate-x-1" />
                </Link>
              </motion.div>
              <motion.a
                whileHover={{ scale: 1.05 }} whileTap={{ scale: 0.95 }}
                href="#solution"
                className="rounded-2xl border border-slate-200 bg-white/80 backdrop-blur-sm px-6 py-3.5 text-sm font-semibold text-slate-700 shadow-sm transition-all duration-300 hover:bg-slate-50 hover:shadow-md"
              >
                See how it works
              </motion.a>
            </div>

            <div className="grid gap-4 sm:grid-cols-3">
              <Metric label="Never Forget" value="Source-backed" />
              <Metric label="Rewind Time" value="Query old truth" />
              <Metric label="Catch Mistakes" value="Stop contradictions" />
            </div>
          </motion.div>

          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: 30 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            transition={{ duration: 0.7, delay: 0.2 }}
            className="rounded-[32px] border border-white/40 bg-white/60 p-2 shadow-[0_32px_80px_-24px_rgba(79,70,229,0.2)] backdrop-blur-xl"
          >
            <ContextGraphAnimation />
          </motion.div>
        </section>

        {/* LOGOS SECTION */}
        <section className="border-y border-slate-200/50 bg-white/40 py-10 backdrop-blur-sm overflow-hidden">
          <div className="mx-auto max-w-6xl px-6 text-center mb-8">
            <p className="text-xs font-semibold uppercase tracking-widest text-slate-400">Works smoothly with your favorite tools</p>
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

        <section id="problem" className="bg-white/70 backdrop-blur-md">
          <div className="mx-auto max-w-6xl px-6 py-24">
            <motion.div
              initial="hidden" whileInView="visible" viewport={{ once: true, margin: "-100px" }}
              variants={itemVariants}
              className="max-w-3xl"
            >
              <p className="text-lg font-bold uppercase tracking-widest text-brand-600">The Startup Problem</p>
              <h2 className="mt-4 text-3xl font-bold tracking-tight text-slate-950 md:text-5xl">
                Search is not the hard part. <span className="text-slate-400">Keeping company truth aligned is.</span>
              </h2>
            </motion.div>

            <motion.div
              initial="hidden" whileInView="visible" viewport={{ once: true, margin: "-50px" }}
              variants={containerVariants}
              className="mt-12 grid gap-6 md:grid-cols-3"
            >
              {PROBLEMS.map((item) => (
                <motion.div
                  variants={itemVariants}
                  key={item.title}
                  className="h-full"
                >
                  <SpotlightCard className="group h-full p-8">
                    <div className="mb-6 inline-flex h-12 w-12 items-center justify-center rounded-2xl bg-brand-50 text-brand-600 transition-colors group-hover:bg-brand-600 group-hover:text-white relative z-10">
                      <item.icon className="h-6 w-6" />
                    </div>
                    <h3 className="text-xl font-bold text-slate-900 relative z-10">{item.title}</h3>
                    <p className="mt-3 text-base leading-relaxed text-slate-600 relative z-10">{item.body}</p>
                  </SpotlightCard>
                </motion.div>
              ))}
            </motion.div>
          </div>
        </section>

        <section id="solution" className="mx-auto max-w-6xl px-6 py-24">
          <motion.div
            initial="hidden" whileInView="visible" viewport={{ once: true, margin: "-100px" }}
            variants={itemVariants}
            className="max-w-3xl"
          >
            <p className="text-lg font-bold uppercase tracking-widest text-brand-600">What Context Engine Does</p>
            <h2 className="mt-4 text-3xl font-bold tracking-tight text-slate-950 md:text-5xl">
              Gives your team a <span className="text-transparent bg-clip-text bg-gradient-to-r from-brand-600 to-brand-400">grounded memory.</span>
            </h2>
          </motion.div>

          <motion.div
            initial="hidden" whileInView="visible" viewport={{ once: true, margin: "-50px" }}
            variants={containerVariants}
            className="mt-16 grid gap-6 md:grid-cols-2 lg:grid-cols-4"
          >
            {CAPABILITIES.map((item) => (
                <motion.div
                  variants={itemVariants}
                  key={item.title}
                  className="h-full"
                >
                  <SpotlightCard className="group h-full p-8">
                    <div className="mb-5 inline-flex h-10 w-10 items-center justify-center rounded-xl bg-slate-50 text-slate-600 transition-colors group-hover:bg-brand-50 group-hover:text-brand-600 relative z-10">
                      <item.icon className="h-5 w-5" />
                    </div>
                    <h3 className="text-lg font-bold text-slate-900 relative z-10">{item.title}</h3>
                    <p className="mt-3 text-sm leading-relaxed text-slate-600 relative z-10">{item.body}</p>
                  </SpotlightCard>
                </motion.div>
            ))}
          </motion.div>
        </section>

        <section id="fit" className="relative overflow-hidden bg-slate-950 text-white">
          <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_right,_rgba(79,70,229,0.15),_transparent_40%)]" />

          <div className="relative mx-auto grid max-w-6xl gap-16 px-6 py-24 lg:grid-cols-[1fr_1.1fr] lg:items-center">
            <motion.div
              initial="hidden" whileInView="visible" viewport={{ once: true, margin: "-100px" }}
              variants={itemVariants}
            >
              <p className="text-lg font-bold uppercase tracking-widest text-brand-400">Why Startups Choose This</p>
              <h2 className="mt-4 text-3xl font-bold tracking-tight md:text-5xl">
                Corporate tools optimize for breadth. <br /><span className="text-slate-400">You need truth under velocity.</span>
              </h2>
              <p className="mt-6 max-w-xl text-lg leading-relaxed text-slate-300">
                Small teams have fewer employees, but far more context density per person. Decisions
                move quickly, documentation lags, and a single contradiction can damage a launch,
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

        <section className="mx-auto max-w-6xl px-6 py-24">
          <motion.div
            initial={{ opacity: 0, scale: 0.95 }}
            whileInView={{ opacity: 1, scale: 1 }}
            viewport={{ once: true, margin: "-100px" }}
            transition={{ duration: 0.6 }}
            className="relative overflow-hidden rounded-[40px] border border-brand-200 bg-white p-10 shadow-2xl shadow-brand-500/10 md:p-16"
          >
            <div className="absolute top-0 right-0 -mr-20 -mt-20 h-64 w-64 rounded-full bg-brand-500/10 blur-3xl mix-blend-multiply" />
            <div className="absolute bottom-0 left-0 -ml-20 -mb-20 h-64 w-64 rounded-full bg-brand-400/10 blur-3xl mix-blend-multiply" />

            <div className="relative max-w-3xl space-y-6">
              <p className="text-lg font-bold uppercase tracking-widest text-brand-600">The Pitch</p>
              <h2 className="text-4xl font-bold tracking-tight text-slate-950 md:text-5xl">
                Search finds documents. <br />Context Engine tells your team <span className="text-transparent bg-clip-text bg-gradient-to-r from-brand-600 to-brand-400">what is actually true.</span>
              </h2>
              <p className="text-lg leading-relaxed text-slate-600 md:text-xl">
                Use it to answer questions with provenance, understand how decisions evolved, and stop
                stale or contradictory context from slipping into product, engineering, or customer work.
              </p>
            </div>

            <div className="relative mt-10 flex flex-wrap gap-4">
              <motion.div whileHover={{ scale: 1.05 }} whileTap={{ scale: 0.95 }} className="relative group">
                <div className="absolute -inset-1 rounded-2xl bg-brand-500/30 blur-xl transition-all duration-500 group-hover:bg-brand-500/50 group-hover:duration-200 animate-pulse"></div>
                <Link
                  to="/app"
                  className="group flex items-center gap-2 rounded-2xl bg-brand-600 px-8 py-4 text-base font-bold text-white shadow-lg shadow-brand-500/30 transition-all duration-300 hover:bg-brand-500 hover:shadow-xl hover:shadow-brand-500/40 relative z-10"
                >
                  Try Context Engine
                  <ArrowRight className="h-5 w-5 transition-transform group-hover:translate-x-1" />
                </Link>
              </motion.div>
            </div>
          </motion.div>
        </section>
      </main>

      <footer className="border-t border-slate-200/50 bg-white/80 py-12 text-center text-sm font-medium text-slate-500 backdrop-blur-sm">
        <div className="mx-auto flex max-w-6xl flex-col items-center justify-between gap-6 px-6 md:flex-row">
          <div className="flex items-center gap-3">
            <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-brand-600 text-xs font-bold text-white">CE</span>
            <p>© {new Date().getFullYear()} Context Engine. All rights reserved.</p>
          </div>
          <div className="flex gap-8">
            <a href="#" className="transition-colors hover:text-brand-600">Documentation</a>
            <a href="#" className="transition-colors hover:text-brand-600">Pricing</a>
            <a href="#" className="transition-colors hover:text-brand-600">Privacy & Security</a>
            <a href="#" className="transition-colors hover:text-brand-600">GitHub</a>
          </div>
        </div>
      </footer>
    </div>
  );
}

function Metric({ label, value }) {
  return (
    <div className="rounded-2xl border border-brand-100 bg-white/60 px-5 py-4 shadow-[0_4px_20px_-4px_rgba(79,70,229,0.05)] backdrop-blur-sm transition-all hover:-translate-y-0.5 hover:border-brand-200 hover:shadow-[0_8px_30px_-4px_rgba(79,70,229,0.1)]">
      <p className="text-[11px] font-bold uppercase tracking-[0.2em] text-brand-600">{label}</p>
      <p className="mt-2 text-sm font-bold text-slate-900">{value}</p>
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

  const handleFocus = () => {
    setIsFocused(true);
    setOpacity(1);
  };

  const handleBlur = () => {
    setIsFocused(false);
    setOpacity(0);
  };

  const handleMouseEnter = () => {
    setOpacity(1);
  };

  const handleMouseLeave = () => {
    setOpacity(0);
  };

  return (
    <div
      ref={divRef}
      onMouseMove={handleMouseMove}
      onFocus={handleFocus}
      onBlur={handleBlur}
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
      className={`relative overflow-hidden rounded-3xl border border-slate-200/80 bg-white shadow-sm transition-all duration-300 hover:-translate-y-1.5 hover:border-brand-300 hover:shadow-xl hover:shadow-brand-500/10 ${className}`}
    >
      <div
        className="pointer-events-none absolute -inset-px opacity-0 transition duration-300 z-0"
        style={{
          opacity,
          background: `radial-gradient(400px circle at ${position.x}px ${position.y}px, rgba(99,102,241,0.08), transparent 40%)`,
        }}
      />
      <div className="relative z-10 h-full w-full">{children}</div>
    </div>
  );
}

function Logos() {
  return (
    <>
      <div className="flex items-center gap-2.5 text-2xl font-bold tracking-tight text-slate-800">
        <svg role="img" viewBox="0 0 24 24" fill="currentColor" xmlns="http://www.w3.org/2000/svg" className="h-7 w-7"><title>Slack</title><path d="M5.042 15.165a2.528 2.528 0 0 1-2.52 2.523A2.528 2.528 0 0 1 0 15.165a2.527 2.527 0 0 1 2.522-2.52h2.52v2.52zm1.27 0a2.527 2.527 0 0 1 2.521-2.52 2.528 2.528 0 0 1 2.521 2.52v6.313A2.528 2.528 0 0 1 8.834 24a2.528 2.528 0 0 1-2.521-2.522v-6.313zM8.834 5.042a2.528 2.528 0 0 1-2.521-2.52A2.528 2.528 0 0 1 8.834 0a2.528 2.528 0 0 1 2.521 2.522v2.52H8.834zm0 1.27a2.528 2.528 0 0 1 2.521 2.521 2.528 2.528 0 0 1-2.521 2.521H2.522A2.528 2.528 0 0 1 0 8.834a2.528 2.528 0 0 1 2.522-2.521h6.312zm10.122 2.523a2.528 2.528 0 0 1 2.522-2.521A2.528 2.528 0 0 1 24 8.834a2.528 2.528 0 0 1-2.522 2.521h-2.522V8.835zm-1.27 0a2.528 2.528 0 0 1-2.521 2.521 2.528 2.528 0 0 1-2.521-2.521V2.522A2.528 2.528 0 0 1 15.166 0a2.528 2.528 0 0 1 2.52 2.522v6.313zM15.166 18.958a2.528 2.528 0 0 1 2.52 2.522A2.528 2.528 0 0 1 15.166 24a2.528 2.528 0 0 1-2.521-2.522v-2.52h2.521zm0-1.27a2.528 2.528 0 0 1-2.52-2.521 2.528 2.528 0 0 1 2.52-2.521h6.313A2.528 2.528 0 0 1 24 15.166a2.528 2.528 0 0 1-2.522 2.52h-6.313z"/></svg>
        Slack
      </div>
      <div className="flex items-center gap-2.5 text-2xl font-bold tracking-tight text-slate-800">
        <svg role="img" viewBox="0 0 24 24" fill="currentColor" xmlns="http://www.w3.org/2000/svg" className="h-7 w-7"><title>Notion</title><path d="M4.1 3.511a1.27 1.27 0 0 1 1.282-1.2h12.5a1.27 1.27 0 0 1 1.283 1.2l.006 17a1.27 1.27 0 0 1-1.281 1.21h-12.5a1.28 1.28 0 0 1-1.283-1.196zm2.4 2.87v10.15l7.98-10.15h1.99V17h-1.84V7.53L7.33 17.02H5.34v-10.64h1.16z" /></svg>
        Notion
      </div>
      <div className="flex items-center gap-2.5 text-2xl font-bold tracking-tight text-slate-800">
        <svg role="img" viewBox="0 0 24 24" fill="currentColor" xmlns="http://www.w3.org/2000/svg" className="h-7 w-7"><title>GitHub</title><path d="M12 .297c-6.63 0-12 5.373-12 12 0 5.303 3.438 9.8 8.205 11.385.6.113.82-.258.82-.577 0-.285-.01-1.04-.015-2.04-3.338.724-4.042-1.61-4.042-1.61C4.422 18.07 3.633 17.7 3.633 17.7c-1.087-.744.084-.729.084-.729 1.205.084 1.838 1.236 1.838 1.236 1.07 1.835 2.809 1.305 3.495.998.108-.776.417-1.305.76-1.605-2.665-.3-5.466-1.332-5.466-5.93 0-1.31.465-2.38 1.235-3.22-.135-.303-.54-1.523.105-3.176 0 0 1.005-.322 3.3 1.23.96-.267 1.98-.399 3-.405 1.02.006 2.04.138 3 .405 2.28-1.552 3.285-1.23 3.285-1.23.645 1.653.24 2.873.12 3.176.765.84 1.23 1.91 1.23 3.22 0 4.61-2.805 5.625-5.475 5.92.42.36.81 1.096.81 2.22 0 1.606-.015 2.896-.015 3.286 0 .315.21.69.825.57C20.565 22.092 24 17.592 24 12.297c0-6.627-5.373-12-12-12"/></svg>
        GitHub
      </div>
      <div className="flex items-center gap-2.5 text-2xl font-bold tracking-tight text-slate-800">
        <svg role="img" viewBox="0 0 24 24" fill="currentColor" xmlns="http://www.w3.org/2000/svg" className="h-7 w-7"><title>Jira</title><path d="M11.53 17.53A4.53 4.53 0 0 1 7 13V2.47a.47.47 0 0 0-.47-.47H2.47A.47.47 0 0 0 2 2.47V13a9.06 9.06 0 0 0 9.06 9.06h8.47a.47.47 0 0 0 .47-.47v-4.06a.47.47 0 0 0-.47-.47h-8.06zM21.53 9.47A9.06 9.06 0 0 0 12.47.41h-2A.47.47 0 0 0 10 .88v4.06A.47.47 0 0 0 10.47 5.4h2A4.53 4.53 0 0 1 17 9.94v8.06a.47.47 0 0 0 .47.47h4.06a.47.47 0 0 0 .47-.47V9.47z"/></svg>
        Jira
      </div>
      <div className="flex items-center gap-2.5 text-2xl font-bold tracking-tight text-slate-800">
        <svg role="img" viewBox="0 0 24 24" fill="currentColor" xmlns="http://www.w3.org/2000/svg" className="h-8 w-8 -ml-1"><title>Zoom</title><path d="M4.5 9A2.5 2.5 0 0 0 2 11.5v4A2.5 2.5 0 0 0 4.5 18h8A2.5 2.5 0 0 0 15 15.5v-4A2.5 2.5 0 0 0 12.5 9h-8zm11.2 5.5v-4a1 1 0 0 1 1.5-.86l4 2.5a1 1 0 0 1 0 1.72l-4 2.5a1 1 0 0 1-1.5-.86z"/></svg>
        Zoom
      </div>
    </>
  );
}

function ContextGraphAnimation() {
  return (
    <div className="relative w-full aspect-square rounded-[32px] bg-slate-950 overflow-hidden shadow-[inset_0_0_100px_rgba(0,0,0,0.8)] border border-slate-800">
      {/* Deep Background Glow */}
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_center,rgba(79,70,229,0.25)_0%,transparent_60%)]" />

      {/* Cyber Grid */}
      <div className="absolute inset-0 bg-[linear-gradient(rgba(255,255,255,0.04)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,0.04)_1px,transparent_1px)] bg-[size:28px_28px] [mask-image:radial-gradient(ellipse_60%_60%_at_50%_50%,#000_20%,transparent_100%)]" />

      {/* Animated Rings */}
      <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
        <motion.div animate={{ rotate: 360 }} transition={{ duration: 25, repeat: Infinity, ease: "linear" }} className="absolute w-56 h-56 border border-brand-500/30 rounded-full border-dashed" />
        <motion.div animate={{ rotate: -360 }} transition={{ duration: 40, repeat: Infinity, ease: "linear" }} className="absolute w-80 h-80 border border-brand-400/10 rounded-full" />
      </div>

      {/* Pulse Lines */}
      <svg className="absolute inset-0 w-full h-full pointer-events-none" viewBox="0 0 400 400" fill="none">
        <PulseLine x1="100" y1="100" x2="200" y2="200" delay={0} />
        <PulseLine x1="300" y1="110" x2="200" y2="200" delay={0.7} />
        <PulseLine x1="110" y1="300" x2="200" y2="200" delay={1.4} />
        <PulseLine x1="290" y1="290" x2="200" y2="200" delay={2.1} />
      </svg>

      {/* Outer Floating Nodes */}
      <GraphNode x="25%" y="25%" delay={0} icon={<Database className="w-5 h-5" />} />
      <GraphNode x="75%" y="27.5%" delay={1} icon={<Cpu className="w-5 h-5" />} />
      <GraphNode x="27.5%" y="75%" delay={2} icon={<BookOpen className="w-5 h-5" />} />
      <GraphNode x="72.5%" y="72.5%" delay={1.5} icon={<History className="w-5 h-5" />} />

      {/* Inner Engine Core */}
      <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
        <motion.div 
          animate={{ boxShadow: ["0 0 20px rgba(79,70,229,0.3)", "0 0 70px rgba(79,70,229,0.9)", "0 0 20px rgba(79,70,229,0.3)"] }}
          transition={{ duration: 2.8, repeat: Infinity, ease: "easeInOut" }}
          className="z-10 flex h-24 w-24 items-center justify-center rounded-[20px] bg-slate-900 border border-brand-400 backdrop-blur-md"
        >
          <div className="absolute inset-0 rounded-[20px] bg-gradient-to-br from-brand-500/40 to-brand-700/80 mix-blend-screen"></div>
          <span className="relative text-3xl font-black text-white tracking-tighter drop-shadow-md">CE</span>
        </motion.div>
      </div>

      <div className="absolute bottom-6 inset-x-0 text-center pointer-events-none">
        <p className="text-[10px] uppercase font-bold tracking-[0.3em] text-brand-400/80">Context Engine Active</p>
      </div>
    </div>
  );
}

function GraphNode({ x, y, icon, delay = 0 }) {
  return (
    <motion.div
      className="absolute flex h-14 w-14 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-2xl border border-white/10 bg-slate-800/80 text-brand-300 shadow-[0_0_20px_rgba(79,70,229,0.2)] backdrop-blur-md"
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
      <line x1={x1} y1={y1} x2={x2} y2={y2} stroke="rgba(99,102,241,0.15)" strokeWidth="1.5" />
      <motion.line
        x1={x1} y1={y1} x2={x2} y2={y2}
        stroke="rgba(129,140,248,0.8)"
        strokeWidth="3"
        strokeLinecap="round"
        style={{ filter: "drop-shadow(0 0 8px rgba(129,140,248,0.8))" }}
        initial={{ pathLength: 0, opacity: 0 }}
        animate={{ pathLength: 1, opacity: [0, 1, 0] }}
        transition={{ duration: 2.1, repeat: Infinity, ease: "circIn", delay }}
      />
    </>
  );
}
