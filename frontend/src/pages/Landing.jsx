import { Link } from "react-router-dom";
import { ArrowRight, Check } from "lucide-react";

import CeIcon from "../components/CeIcon";
import ThemeToggle from "../components/ThemeToggle";

const GITHUB_URL = "https://github.com/Darshan174/Context-Engine";

const PRODUCT_LOOP = [
  ["01", "Capture the evidence", "Keep repository state, issues, pull requests, coding sessions, documents, decisions, and checks with their sources."],
  ["02", "See work in motion", "Now shows the active or latest coding session, its newest update and stated reason, verified results, blockers, and risks."],
  ["03", "Prepare the handoff", "Compile a bounded context_pack.v2 with relevant facts, files, constraints, checks, citations, and explicit exclusions."],
  ["04", "Observe the result", "Optionally wrap your own local worker command to record Git changes, verification results, and a factual outcome for the next run."],
];

const PACK_ROWS = [
  ["Current goal", "Fix workspace onboarding", "selected by you"],
  ["Relevant file", "frontend/src/pages/WorkspacesPage.jsx", "repo snapshot"],
  ["Constraint", "Keep project selection explicit", "decision D3"],
  ["Required check", "npm test -- WorkspacesPage.test.jsx", "not run"],
];

export default function Landing() {
  return (
    <div className="min-h-screen bg-[#f7f7f2] text-[#171713] selection:bg-[#d9ff68] selection:text-black dark:bg-[#0d0d0b] dark:text-[#f4f4ec]">
      <Nav />

      <main>
        <section className="mx-auto grid w-full max-w-6xl gap-14 px-5 pb-24 pt-16 sm:px-8 sm:pt-24 lg:grid-cols-[1.04fr_0.96fr] lg:items-center lg:gap-20 lg:pb-32 lg:pt-28">
          <div>
            <p className="mb-7 text-xs font-semibold uppercase tracking-[0.18em] text-[#68685f] dark:text-[#a2a298]">
              Open source · self-hosted · active alpha
            </p>
            <h1 className="max-w-3xl text-[clamp(3rem,7vw,5.8rem)] font-semibold leading-[0.94] tracking-[-0.055em]">
              Make every coding agent start with the project, not a blank chat.
            </h1>
            <p className="mt-8 max-w-xl text-lg leading-8 text-[#5c5c54] dark:text-[#b3b3a9]">
              Context Engine keeps source-backed project evidence, an explicit current goal, and observed run results—then compiles the focused brief your next agent needs.
            </p>

            <div className="mt-9 flex flex-col gap-3 sm:flex-row">
              <Link
                to="/app"
                className="inline-flex h-12 items-center justify-center gap-2 rounded-md bg-[#171713] px-5 text-sm font-semibold text-white transition hover:bg-black focus:outline-none focus-visible:ring-2 focus-visible:ring-[#171713] focus-visible:ring-offset-4 focus-visible:ring-offset-[#f7f7f2] dark:bg-[#f4f4ec] dark:text-black dark:hover:bg-white dark:focus-visible:ring-[#f4f4ec] dark:focus-visible:ring-offset-[#0d0d0b]"
              >
                Open the local app <ArrowRight className="h-4 w-4" />
              </Link>
              <a
                href={GITHUB_URL}
                target="_blank"
                rel="noreferrer"
                className="inline-flex h-12 items-center justify-center gap-2 rounded-md border border-[#cecec5] bg-transparent px-5 text-sm font-semibold transition hover:border-[#171713] dark:border-[#35352f] dark:hover:border-[#f4f4ec]"
              >
                Explore on GitHub
              </a>
            </div>

            <p className="mt-5 text-sm text-[#77776e] dark:text-[#929289]">
              It prepares the handoff. It does not replace or silently launch your coding agent.
            </p>
          </div>

          <PackPreview />
        </section>

        <section className="border-y border-[#d9d9d0] dark:border-[#292925]">
          <div className="mx-auto grid w-full max-w-6xl divide-y divide-[#d9d9d0] px-5 sm:px-8 md:grid-cols-3 md:divide-x md:divide-y-0 dark:divide-[#292925]">
            <Proof label="Project focus" value="Explicit current work" />
            <Proof label="Agent handoff" value="context_pack.v2" />
            <Proof label="Run history" value="Observed, not assumed" />
          </div>
        </section>

        <section className="mx-auto w-full max-w-6xl px-5 py-24 sm:px-8 lg:py-32">
          <div className="grid gap-12 lg:grid-cols-[0.8fr_1.2fr] lg:gap-20">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[#68685f] dark:text-[#a2a298]">How it works</p>
              <h2 className="mt-5 max-w-md text-4xl font-semibold leading-[1.05] tracking-[-0.04em] sm:text-5xl">
                One project loop across every agent.
              </h2>
            </div>
            <div className="border-t border-[#bdbdb4] dark:border-[#3a3a34]">
              {PRODUCT_LOOP.map(([number, title, body]) => (
                <article key={number} className="grid gap-4 border-b border-[#d9d9d0] py-7 sm:grid-cols-[3rem_12rem_1fr] dark:border-[#292925]">
                  <span className="font-mono text-xs text-[#83837a]">{number}</span>
                  <h3 className="text-base font-semibold">{title}</h3>
                  <p className="max-w-xl text-sm leading-6 text-[#68685f] dark:text-[#aaa9a0]">{body}</p>
                </article>
              ))}
            </div>
          </div>
        </section>

        <section className="bg-[#171713] text-white dark:bg-[#f1f1e9] dark:text-[#171713]">
          <div className="mx-auto grid w-full max-w-6xl gap-14 px-5 py-24 sm:px-8 lg:grid-cols-2 lg:items-center lg:gap-24 lg:py-28">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[#a7a79e] dark:text-[#66665e]">Prepare, then observe</p>
              <h2 className="mt-5 text-4xl font-semibold leading-[1.02] tracking-[-0.04em] sm:text-5xl">
                Review the brief. Run the agent you choose.
              </h2>
            </div>
            <ul className="space-y-5 text-base text-[#d1d1c8] dark:text-[#45453f]">
              {[
                "See what Prepare selected, excluded, and why.",
                "Inspect citations, source revisions, and context health.",
                "Copy the compiled brief into any coding agent.",
                "Use the optional local harness to record changes and checks.",
              ].map((item) => (
                <li key={item} className="flex gap-3 border-b border-white/15 pb-5 last:border-b-0 dark:border-black/15">
                  <Check className="mt-0.5 h-5 w-5 shrink-0" />
                  <span>{item}</span>
                </li>
              ))}
            </ul>
          </div>
        </section>

        <section className="mx-auto w-full max-w-6xl px-5 py-24 sm:px-8 lg:py-32">
          <div className="grid gap-12 lg:grid-cols-2 lg:gap-24">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[#68685f] dark:text-[#a2a298]">What works in this alpha</p>
              <h2 className="mt-5 text-4xl font-semibold tracking-[-0.04em] sm:text-5xl">Project evidence in. A focused handoff out.</h2>
            </div>
            <div className="space-y-8 text-[#62625a] dark:text-[#aaa9a0]">
              <p className="text-lg leading-8">
                Use local repositories and files, import Codex, Claude Code, or OpenCode sessions, and configure GitHub, Slack, Gmail, or Google Drive when you need them.
              </p>
              <p className="text-lg leading-8">
                Explain visualizes the evidence behind Now, Prepare, and Runs. The graph is an inspection surface—not a generic company knowledge graph and not the agent handoff.
              </p>
              <p className="text-sm leading-6">
                Discord, Zoom, and Wispr Flow remain marked coming soon. Notion is not catalogued.
              </p>
              <Link to="/app/sources" className="inline-flex items-center gap-2 border-b border-current pb-1 text-sm font-semibold text-[#171713] dark:text-[#f4f4ec]">
                Inspect source evidence <ArrowRight className="h-4 w-4" />
              </Link>
            </div>
          </div>
        </section>

        <section className="border-t border-[#d9d9d0] dark:border-[#292925]">
          <div className="mx-auto flex w-full max-w-6xl flex-col items-start justify-between gap-8 px-5 py-20 sm:px-8 md:flex-row md:items-end">
            <h2 className="max-w-2xl text-4xl font-semibold leading-[1.02] tracking-[-0.04em] sm:text-5xl">
              Keep the context each run earned for the one that follows.
            </h2>
            <Link to="/app" className="inline-flex h-12 shrink-0 items-center gap-2 rounded-md bg-[#d9ff68] px-5 text-sm font-semibold text-black transition hover:bg-[#cfff3c]">
              Open Context Engine <ArrowRight className="h-4 w-4" />
            </Link>
          </div>
        </section>
      </main>

      <Footer />
    </div>
  );
}

function Nav() {
  return (
    <header className="border-b border-[#d9d9d0] dark:border-[#292925]">
      <div className="mx-auto flex h-16 w-full max-w-6xl items-center justify-between px-5 sm:px-8">
        <Link to="/" className="inline-flex items-center gap-2.5 font-semibold tracking-[-0.02em]">
          <CeIcon size={24} />
          Context Engine
        </Link>
        <nav aria-label="Main navigation" className="flex items-center gap-2 sm:gap-5">
          <a href={GITHUB_URL} target="_blank" rel="noreferrer" className="hidden text-sm text-[#62625a] transition hover:text-[#171713] sm:block dark:text-[#aaa9a0] dark:hover:text-white">
            GitHub
          </a>
          <Link to="/app" className="text-sm font-semibold">Open app</Link>
          <ThemeToggle />
        </nav>
      </div>
    </header>
  );
}

function PackPreview() {
  return (
    <div className="border border-[#bdbdb4] bg-[#efefe8] p-3 shadow-[8px_8px_0_#d9ff68] dark:border-[#41413a] dark:bg-[#171713] dark:shadow-[8px_8px_0_#6d7e2b]">
      <div className="bg-[#fafaf6] dark:bg-[#0d0d0b]">
        <div className="flex items-center justify-between border-b border-[#d9d9d0] px-4 py-3 dark:border-[#292925]">
          <span className="font-mono text-[11px] font-semibold">context_pack.v2</span>
          <span className="rounded-full bg-[#e9e9e1] px-2 py-1 font-mono text-[10px] text-[#66665e] dark:bg-[#292925] dark:text-[#b0b0a6]">example</span>
        </div>
        <div className="p-4 sm:p-5">
          <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-[#77776e]">Task</p>
          <p className="mt-2 text-base font-semibold">Fix workspace onboarding without hiding project state</p>
          <div className="mt-5 divide-y divide-[#e2e2d9] border-y border-[#e2e2d9] dark:divide-[#292925] dark:border-[#292925]">
            {PACK_ROWS.map(([type, value, source]) => (
              <div key={value} className="grid gap-1 py-3 sm:grid-cols-[6.5rem_1fr_auto] sm:items-center sm:gap-3">
                <span className="font-mono text-[10px] uppercase text-[#77776e]">{type}</span>
                <span className="text-xs font-medium">{value}</span>
                <span className="font-mono text-[10px] text-[#8a8a80]">{source}</span>
              </div>
            ))}
          </div>
          <div className="mt-4 flex items-center justify-between text-[11px] text-[#77776e]">
            <span>4 selected · 2 excluded</span>
            <span className="font-mono">within budget</span>
          </div>
        </div>
      </div>
    </div>
  );
}

function Proof({ label, value }) {
  return (
    <div className="py-6 md:px-7">
      <p className="font-mono text-[11px] uppercase tracking-[0.12em] text-[#77776e]">{label}</p>
      <p className="mt-2 text-base font-semibold">{value}</p>
    </div>
  );
}

function Footer() {
  return (
    <footer className="border-t border-[#d9d9d0] dark:border-[#292925]">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-4 px-5 py-8 text-sm text-[#77776e] sm:flex-row sm:items-center sm:justify-between sm:px-8">
        <span>Context Engine · Source-backed continuity for coding agents</span>
        <div className="flex gap-5">
          <Link to="/app">App</Link>
          <Link to="/app/sources">Sources</Link>
          <a href={GITHUB_URL} target="_blank" rel="noreferrer">GitHub</a>
        </div>
      </div>
    </footer>
  );
}
