import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  Activity,
  ArrowRight,
  BrainCircuit,
  Check,
  ChevronDown,
  Database,
  FileCode2,
  GitBranch,
  History,
  MessagesSquare,
  PlugZap,
  ShieldCheck,
  Sparkles,
  TestTube2,
  Waypoints,
} from "lucide-react";

import DaemonStateIcon from "../components/DaemonStateIcon";

const GITHUB_URL = "https://github.com/Darshan174/DaemonState";
const PIXEL_COUNT = 48;

const SOURCE_STREAMS = [
  { label: "Agent sessions", detail: "intent + reasoning", icon: MessagesSquare },
  { label: "Repository", detail: "files + diffs", icon: FileCode2 },
  { label: "Git activity", detail: "issues + reviews", icon: GitBranch },
  { label: "Test evidence", detail: "checks + outcomes", icon: TestTube2 },
];

const CONTINUITY_LOOP = [
  {
    number: "01",
    title: "Connect",
    body: "Bring sessions, repository state, pull requests, documents, and configured sources into one evidence layer.",
  },
  {
    number: "02",
    title: "Observe",
    body: "Track current activity without turning every historical artifact into an instruction.",
  },
  {
    number: "03",
    title: "Prepare",
    body: "Compile the current goal, relevant facts, files, blockers, exclusions, and verification commands.",
  },
  {
    number: "04",
    title: "Continue",
    body: "Resume from a reviewable checkpoint, then preserve the outcome as evidence for the next run.",
  },
];

const HANDOFF_ROWS = [
  ["Current goal", "Ship source revisions without breaking provenance", "selected"],
  ["Decision", "Source documents stay append-only", "source rev 3"],
  ["Relevant file", "app/services/context_compiler.py", "repo state"],
  ["Blocker", "PostgreSQL migration still needs verification", "evidence E4"],
  ["Exact next action", "Run the compiler contract tests, then review the migration", "checkpoint"],
];

const PRODUCT_SURFACES = [
  {
    id: "continue",
    number: "01",
    label: "Continue",
    surfaces: "Project + Session Context",
    title: "Start fresh or recover after compaction without losing the task.",
    body: "Resolve the current goal against repository state, then compile only the sessions, decisions, blockers, files, and checks needed for this continuation.",
    payoff: "The same work can move into a fresh session or a supported harness without a full rediscovery pass.",
    tags: ["current goal", "exact next action", "cross-harness"],
    to: "/app",
    action: "Continue work",
    icon: Activity,
  },
  {
    id: "review",
    number: "02",
    label: "Review",
    surfaces: "Library + History",
    title: "Find the exact session and see what actually happened.",
    body: "Search work by harness, topic, and checkpoint. Review requests, outcomes, Git changes, checks, blockers, and places where context is still incomplete.",
    payoff: "Session selection becomes deliberate, and the execution trail stays inspectable.",
    tags: ["session library", "run history", "checkpoints"],
    to: "/app/library",
    action: "Browse sessions",
    icon: History,
  },
  {
    id: "remember",
    number: "03",
    label: "Remember",
    surfaces: "Project Memory",
    title: "Keep the decisions and learnings that should outlive one chat.",
    body: "Turn requirements, decisions, blockers, risks, learnings, and outcomes into reviewable memory with provenance, freshness, and conflict states.",
    payoff: "Durable project knowledge stays useful without becoming an opaque transcript dump.",
    tags: ["durable facts", "freshness", "human review"],
    to: "/app/memory",
    action: "Inspect memory",
    icon: BrainCircuit,
  },
  {
    id: "explain",
    number: "04",
    label: "Explain",
    surfaces: "Evidence",
    title: "Trace every important conclusion back to what earned it.",
    body: "Follow goals, decisions, files, risks, checks, and source revisions through their relationships instead of trusting an unexplained summary.",
    payoff: "The agent gets focus. The person keeps provenance and auditability.",
    tags: ["relationships", "provenance", "conflicts"],
    to: "/app/explain",
    action: "Trace the evidence",
    icon: Waypoints,
  },
  {
    id: "connect",
    number: "05",
    label: "Connect",
    surfaces: "Sources + Integrations",
    title: "Grow the evidence layer without weakening source boundaries.",
    body: "Preserve raw material and its revisions, then bring configured systems into the same evidence model without silently promoting every imported claim to truth.",
    payoff: "Broad input coverage. Narrow, source-backed output.",
    tags: ["source revisions", "ingestion", "boundaries"],
    to: "/app/connectors",
    action: "Manage integrations",
    icon: PlugZap,
  },
];

export default function Landing() {
  const landingRef = useRef(null);
  useLandingMotion(landingRef);

  return (
    <div ref={landingRef} data-landing-theme="fixed" className="daemonstate-landing min-h-screen text-[#171713] selection:bg-[#171713] selection:text-white">
      <Nav />

      <main>
        <section className="daemonstate-landing-hero mx-auto grid w-full max-w-[1440px] gap-12 px-5 pb-16 pt-12 sm:px-8 sm:pb-24 sm:pt-20 lg:grid-cols-[1.03fr_0.97fr] lg:items-center lg:gap-10 lg:px-12 lg:pb-28 lg:pt-24">
          <div className="daemonstate-hero-copy relative z-10">
            <p className="daemonstate-kicker">
              <span className="daemonstate-live-dot" aria-hidden="true" />
              Verified continuity for coding agents
            </p>
            <h1 className="mt-7 max-w-5xl text-[clamp(3.35rem,7vw,7.25rem)] font-semibold leading-[0.88] tracking-[-0.065em]">
              Your next coding agent should not start from zero.
            </h1>
            <p className="mt-8 max-w-2xl text-lg leading-8 text-[#5f5f57] sm:text-xl sm:leading-9">
              DaemonState turns coding sessions, repository state, decisions, blockers, and test evidence into task-relevant Project Context—ready for the harness you choose.
            </p>

            <div className="mt-9 flex flex-col gap-3 sm:flex-row">
              <Link to="/app" className="daemonstate-cta-primary">
                Open DaemonState <ArrowRight className="h-4 w-4" />
              </Link>
              <a href="#handoff" className="daemonstate-cta-secondary">
                See the handoff
              </a>
            </div>

            <div className="mt-8 flex flex-wrap gap-x-6 gap-y-3 text-sm text-[#6d6d64]">
              <span className="inline-flex items-center gap-2"><Check className="h-4 w-4" />Source-backed</span>
              <span className="inline-flex items-center gap-2"><Check className="h-4 w-4" />Codex · Claude Code · OpenCode</span>
              <span className="inline-flex items-center gap-2"><Check className="h-4 w-4" />Open source · self-hosted · active alpha</span>
            </div>
          </div>

          <ContinuityVisual />
        </section>

        <SourceRail />

        <ContinuityFlow />

        <section id="workflow" className="mx-auto w-full max-w-[1440px] px-5 py-24 sm:px-8 lg:px-12 lg:py-36">
          <SectionHeading
            number="01"
            label="The continuity loop"
            title="A project should accumulate understanding—not lose it between runs."
            body="DaemonState separates raw evidence, current observed work, and durable checkpoints so the next agent gets a focused continuation rather than an undifferentiated history dump."
          />
          <PixelReveal className="mt-16">
            <div className="grid border-l border-t border-[#9fb64a] sm:grid-cols-2 lg:grid-cols-4">
              {CONTINUITY_LOOP.map((step) => (
                <article
                  key={step.number}
                  className="daemonstate-loop-card min-h-[290px] border-b border-r border-[#9fb64a] p-6 sm:p-8"
                >
                  <span className="font-mono text-sm text-[#5c691f]">{step.number}</span>
                  <h3 className="mt-20 text-3xl font-semibold tracking-[-0.04em]">{step.title}</h3>
                  <p className="mt-4 text-sm leading-6 text-[#465212]">{step.body}</p>
                </article>
              ))}
            </div>
          </PixelReveal>
        </section>

        <ProductAtlas />

        <section id="handoff" className="daemonstate-dark-stage overflow-hidden border-y border-[#9fb64a]">
          <div className="mx-auto grid w-full max-w-[1440px] gap-14 px-5 py-24 sm:px-8 lg:grid-cols-[0.78fr_1.22fr] lg:gap-20 lg:px-12 lg:py-36">
            <div data-daemonstate-reveal="rise" className="lg:sticky lg:top-28 lg:self-start">
              <p className="daemonstate-kicker">03 · Compiled handoff</p>
              <h2 className="mt-7 max-w-xl text-[clamp(2.8rem,5vw,5.5rem)] font-semibold leading-[0.94] tracking-[-0.055em]">
                Everything needed to continue. Nothing that sends the agent sideways.
              </h2>
              <p className="mt-7 max-w-lg text-base leading-7 text-[#465212]">
                The handoff is deliberately finite. Every included claim is inspectable, every exclusion is explicit, and missing evidence remains missing.
              </p>
            </div>
            <PixelReveal><HandoffPreview /></PixelReveal>
          </div>
        </section>

        <section className="mx-auto w-full max-w-[1440px] px-5 py-24 sm:px-8 lg:px-12 lg:py-36">
          <SectionHeading
            number="04"
            label="Curation over accumulation"
            title="More context is not better context. Relevant context is."
            body="The product keeps the evidence layer broad and the agent handoff narrow. That distinction is what makes continuity useful instead of noisy."
          />
          <PixelReveal className="mt-16">
            <div className="grid gap-5 lg:grid-cols-2">
              <CurationCard
                tone="selected"
                eyebrow="Selected for this run"
                title="Current, relevant, and verifiable"
                items={[
                  "The explicit goal chosen for this workspace",
                  "Decisions and constraints that still apply",
                  "Files and checks needed for the exact next action",
                ]}
              />
              <CurationCard
                tone="excluded"
                eyebrow="Kept out of the handoff"
                title="Preserved, but not promoted"
                items={[
                  "Stale plans and superseded decisions",
                  "Unrelated sessions and background history",
                  "Claims without sufficient source evidence",
                ]}
              />
            </div>
          </PixelReveal>
        </section>

        <section className="border-y border-[#d7d7ce]">
          <div className="mx-auto grid w-full max-w-[1440px] lg:grid-cols-2">
            <div data-daemonstate-reveal="rise" className="border-b border-[#9fb64a] px-5 py-20 sm:px-8 lg:border-b-0 lg:border-r lg:px-12 lg:py-28">
              <p className="daemonstate-kicker">05 · One truth, two views</p>
              <h2 className="mt-7 max-w-2xl text-4xl font-semibold leading-[1] tracking-[-0.045em] sm:text-6xl">
                Compiled for agents. Explainable to people.
              </h2>
            </div>
            <div data-daemonstate-reveal="rise" className="flex flex-col justify-center px-5 py-20 sm:px-8 lg:px-12 lg:py-28">
              <p className="max-w-xl text-lg leading-8 text-[#465212]">
                Agents receive a compact continuation bundle. People can inspect the project graph, source revisions, conflicts, checkpoints, and evidence that produced it.
              </p>
              <Link to="/app/explain" className="mt-8 inline-flex w-fit items-center gap-2 border-b border-current pb-1 text-sm font-semibold">
                Explain the project <ArrowRight className="h-4 w-4" />
              </Link>
            </div>
          </div>
        </section>

        <section data-daemonstate-reveal="rise" className="daemonstate-final-cta mx-auto my-5 w-[calc(100%-2.5rem)] max-w-[1390px] overflow-hidden rounded-[2rem] bg-[#171713] px-6 py-16 text-white sm:my-8 sm:w-[calc(100%-4rem)] sm:px-10 sm:py-20 lg:px-14">
          <div className="relative z-10 flex flex-col items-start justify-between gap-10 lg:flex-row lg:items-end">
            <div>
              <p className="daemonstate-kicker text-[#c8e769]">Keep the project moving</p>
              <h2 className="mt-6 max-w-4xl text-[clamp(2.65rem,6vw,6.5rem)] font-semibold leading-[0.9] tracking-[-0.06em]">
                Make the next agent continue—not rediscover.
              </h2>
            </div>
            <Link to="/app" className="inline-flex shrink-0 items-center justify-center gap-2 rounded-full bg-[#d9ff68] px-6 py-4 text-sm font-semibold text-[#171713] transition duration-300 hover:-translate-y-1 hover:shadow-[0_14px_28px_rgba(0,0,0,0.22)]">
              Open DaemonState <ArrowRight className="h-4 w-4" />
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
    <header className="daemonstate-landing-nav sticky top-0 z-50 border-b border-[#9fb64a]/80 backdrop-blur-xl">
      <div className="mx-auto flex h-[4.5rem] w-full max-w-[1440px] items-center justify-between gap-3 px-5 sm:h-20 sm:px-8 lg:px-12">
        <Link to="/" aria-label="DaemonState home" className="group inline-flex min-w-0 items-center gap-3 text-base font-bold tracking-[-0.025em] sm:text-lg">
          <DaemonStateIcon size={32} className="shrink-0 transition-transform duration-300 group-hover:-rotate-3 group-hover:scale-105" />
          <span className="truncate">DaemonState</span>
        </Link>
        <nav aria-label="Main navigation" className="flex shrink-0 items-center gap-2 sm:gap-5">
          <a href="#workflow" className="hidden text-sm text-[#67675f] transition hover:text-[#171713] md:block">How it works</a>
          <a href="#product" className="hidden text-sm text-[#67675f] transition hover:text-[#171713] lg:block">Product</a>
          <a href={GITHUB_URL} target="_blank" rel="noreferrer" className="hidden text-sm text-[#67675f] transition hover:text-[#171713] sm:block">GitHub</a>
          <Link to="/app" className="rounded-full bg-[#171713] px-4 py-2.5 text-sm font-semibold text-white transition hover:-translate-y-0.5">Open app</Link>
        </nav>
      </div>
      <span className="daemonstate-scroll-progress" aria-hidden="true" />
    </header>
  );
}

function ContinuityVisual() {
  return (
    <div className="daemonstate-continuity-visual relative min-h-[540px] overflow-hidden rounded-[2rem] border border-[#d5d5cc] bg-[#ecece5] p-5 shadow-[0_28px_80px_rgba(23,23,19,0.12)] sm:min-h-[620px] sm:p-7">
      <div className="daemonstate-visual-grid absolute inset-0" aria-hidden="true" />
      <div className="relative flex items-center justify-between">
        <span className="daemonstate-kicker">Observed evidence</span>
        <span className="rounded-full border border-[#cfcfc5] bg-white/70 px-3 py-1.5 text-[11px] font-semibold text-[#66665e]">
          Compiling <span className="daemonstate-ellipsis" aria-hidden="true">•••</span>
        </span>
      </div>

      <div className="relative mt-8 space-y-3">
        {SOURCE_STREAMS.map(({ label, detail, icon: Icon }, index) => (
          <div key={label} className="daemonstate-source-row" style={{ "--daemonstate-delay": String(index * 130) + "ms" }}>
            <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-white text-[#505048] shadow-sm">
              <Icon className="h-4 w-4" />
            </span>
            <span className="min-w-0 flex-1">
              <span className="block text-sm font-semibold">{label}</span>
              <span className="mt-0.5 block text-xs text-[#7b7b72]">{detail}</span>
            </span>
            <span className="daemonstate-source-line" aria-hidden="true"><span /></span>
          </div>
        ))}
      </div>

      <div className="daemonstate-merge-stem mx-auto h-12 w-px" aria-hidden="true" />

      <article className="daemonstate-checkpoint-card relative rounded-[1.5rem] border border-[#171713] bg-[#171713] p-5 text-white shadow-[0_22px_55px_rgba(23,23,19,0.24)] sm:p-6">
        <div className="flex items-center justify-between gap-3">
          <span className="inline-flex items-center gap-2 text-xs font-semibold text-[#d9ff68]">
            <ShieldCheck className="h-4 w-4" />Verified checkpoint
          </span>
          <span className="font-mono text-[11px] text-[#8f8f86]">Project Context</span>
        </div>
        <p className="mt-8 text-xs font-semibold text-[#9f9f96]">Exact next action</p>
        <h2 className="mt-2 max-w-lg text-2xl font-semibold leading-tight tracking-[-0.035em] sm:text-3xl">
          Verify the migration, then resume from the preserved decision boundary.
        </h2>
        <div className="mt-6 flex flex-wrap items-center gap-2 text-[11px] font-semibold text-[#bdbdb4]">
          <span className="rounded-full bg-white/10 px-3 py-1.5">4 facts selected</span>
          <span className="rounded-full bg-white/10 px-3 py-1.5">2 exclusions recorded</span>
          <span className="rounded-full bg-[#d9ff68] px-3 py-1.5 text-[#171713]">within budget</span>
        </div>
      </article>
    </div>
  );
}

function SourceRail() {
  const sources = ["Codex", "Claude Code", "OpenCode", "Repository", "GitHub", "Documents", "Test output"];
  return (
    <section aria-label="Supported evidence sources" className="daemonstate-source-rail overflow-hidden border-y border-[#9fb64a] py-4">
      <div className="daemonstate-source-marquee flex min-w-max items-center">
        {[...sources, ...sources].map((source, index) => (
          <span key={source + "-" + index} className="flex items-center">
            <span className="px-7 text-sm font-semibold text-[#5f5f57] sm:px-10">{source}</span>
            <span className="h-1.5 w-1.5 rounded-full bg-[#aeca49]" aria-hidden="true" />
          </span>
        ))}
      </div>
    </section>
  );
}

function ContinuityFlow() {
  return (
    <section id="flow" aria-labelledby="continuity-flow-title" className="daemonstate-flow-section overflow-hidden border-b border-[#9fb64a]">
      <div data-daemonstate-reveal="rise" className="mx-auto grid w-full max-w-[1440px] gap-7 px-5 pt-24 sm:px-8 lg:grid-cols-[0.72fr_1.28fr] lg:gap-20 lg:px-12 lg:pt-32">
        <p className="daemonstate-kicker">The continuity fabric</p>
        <div>
          <h2 id="continuity-flow-title" className="max-w-4xl text-[clamp(2.65rem,5.2vw,5.75rem)] font-semibold leading-[0.95] tracking-[-0.055em]">
            Every source keeps its identity. The handoff keeps only what matters.
          </h2>
          <p className="mt-7 max-w-2xl text-base leading-7 text-[#465212] sm:text-lg sm:leading-8">
            DaemonState routes sessions, repository state, decisions, and test outcomes through selection and provenance before anything reaches the next agent.
          </p>
        </div>
      </div>

      <div data-daemonstate-reveal="rise" className="daemonstate-flow-viewport">
        <svg
          className="daemonstate-flow-map"
          viewBox="0 0 1440 720"
          role="img"
          aria-label="Evidence becomes a verified handoff"
          preserveAspectRatio="xMidYMid meet"
        >
          <title id="continuity-flow-map-title">Evidence becomes a verified handoff</title>
          <desc id="continuity-flow-map-description">
            Agent sessions, repository and Git activity, decisions, blockers, and test evidence remain source-linked while DaemonState selects a verified context pack for the next agent run.
          </desc>

          <g className="daemonstate-flow-ghost-lines">
            <rect x="-64" y="128" width="460" height="270" rx="30" />
            <rect x="-82" y="148" width="460" height="270" rx="30" />
            <rect x="192" y="-78" width="554" height="300" rx="30" />
            <rect x="212" y="-58" width="554" height="300" rx="30" />
            <rect x="502" y="272" width="442" height="226" rx="30" />
            <rect x="522" y="292" width="442" height="226" rx="30" />
            <rect x="1050" y="116" width="430" height="304" rx="30" />
            <rect x="1070" y="136" width="430" height="304" rx="30" />
            <rect x="936" y="390" width="522" height="368" rx="30" />
            <rect x="956" y="410" width="522" height="368" rx="30" />
          </g>

          <g className="daemonstate-flow-primary-lines">
            <path d="M-48 180H354Q394 180 394 220V365Q394 405 434 405H502" />
            <path d="M222-38V28Q222 68 262 68H696Q736 68 736 108V174Q736 214 776 214H1010Q1050 214 1050 174V156Q1050 116 1090 116H1430" />
            <path d="M944 384H1010Q1050 384 1050 424V510Q1050 550 1090 550H1248Q1288 550 1288 590V740" />
            <path d="M380 344H462Q502 344 502 384" />
            <path d="M944 334H1010Q1050 334 1050 294" />
          </g>

          <path className="daemonstate-flow-trace" d="M-48 180H354Q394 180 394 220V365Q394 405 434 405H502H904Q944 405 944 365H1010Q1050 365 1050 405V510Q1050 550 1090 550H1248Q1288 550 1288 590V740" />

          <g className="daemonstate-flow-labels">
            <text x="58" y="190">AGENT SESSIONS</text>
            <text x="58" y="350">DECISIONS + BLOCKERS</text>
            <text x="282" y="58">REPOSITORY + GIT</text>
            <text x="552" y="324">SELECTION + PROVENANCE</text>
            <text className="daemonstate-flow-label-strong" x="552" y="446">VERIFIED CONTEXT PACK</text>
            <text x="1100" y="172">NEXT AGENT RUN</text>
            <text x="1084" y="522">OUTCOME + TEST EVIDENCE</text>
          </g>

          <g className="daemonstate-flow-nodes">
            <circle cx="502" cy="405" r="5" />
            <circle cx="944" cy="405" r="5" />
            <circle cx="1050" cy="550" r="5" />
          </g>
        </svg>

        <div className="daemonstate-flow-caption">
          <span>Source boundaries preserved</span>
          <p>Many evidence streams. One verified continuation.</p>
        </div>
      </div>
    </section>
  );
}

function SectionHeading({ number, label, title, body }) {
  return (
    <div data-daemonstate-reveal="rise" className="grid gap-8 lg:grid-cols-[0.72fr_1.28fr] lg:gap-20">
      <div><p className="daemonstate-kicker">{number} · {label}</p></div>
      <div>
        <h2 className="max-w-4xl text-[clamp(2.65rem,5.2vw,5.75rem)] font-semibold leading-[0.95] tracking-[-0.055em]">{title}</h2>
        <p className="mt-7 max-w-2xl text-base leading-7 text-[#465212] sm:text-lg sm:leading-8">{body}</p>
      </div>
    </div>
  );
}

function ProductAtlas() {
  const [activeId, setActiveId] = useState("continue");

  return (
    <section id="product" className="daemonstate-product-atlas border-y border-[#9fb64a]">
      <div className="mx-auto grid w-full max-w-[1440px] gap-14 px-5 py-24 sm:px-8 lg:grid-cols-[0.66fr_1.34fr] lg:gap-20 lg:px-12 lg:py-36">
        <div data-daemonstate-reveal="rise" className="lg:sticky lg:top-28 lg:self-start">
          <p className="daemonstate-kicker">02 · Product atlas</p>
          <h2 className="mt-7 max-w-xl text-[clamp(2.8rem,5vw,5.5rem)] font-semibold leading-[0.94] tracking-[-0.055em]">
            Everything continuity needs. Five focused surfaces.
          </h2>
          <p className="mt-7 max-w-lg text-base leading-7 text-[#465212]">
            Continue the work, inspect what happened, preserve what matters, trace the evidence, and control what comes in.
          </p>
        </div>

        <PixelReveal className="daemonstate-atlas-list border-t border-[#879d35]">
          {PRODUCT_SURFACES.map((surface) => {
            const open = activeId === surface.id;
            const Icon = surface.icon;
            return (
              <article key={surface.id} className="daemonstate-atlas-row border-b border-[#879d35]" data-open={open}>
                <button
                  type="button"
                  aria-label={"Explore " + surface.label}
                  aria-expanded={open}
                  aria-controls={"surface-" + surface.id}
                  onClick={() => setActiveId(open ? null : surface.id)}
                  className="daemonstate-atlas-trigger grid w-full grid-cols-[2.25rem_1fr_auto] items-center gap-3 px-3 py-6 text-left sm:grid-cols-[3.25rem_8rem_1fr_auto] sm:gap-5 sm:px-5"
                >
                  <span className="daemonstate-atlas-number font-mono text-xs">{surface.number}</span>
                  <span className="hidden text-sm font-semibold sm:block">{surface.label}</span>
                  <span className="min-w-0">
                    <span className="block text-xl font-semibold tracking-[-0.025em] sm:text-2xl">{surface.surfaces}</span>
                    <span className="mt-1.5 block text-xs leading-5 opacity-65 sm:text-sm">{surface.title}</span>
                  </span>
                  <span className="daemonstate-atlas-toggle flex h-10 w-10 items-center justify-center rounded-full border border-current/20">
                    <ChevronDown className="h-4 w-4" />
                  </span>
                </button>

                <div id={"surface-" + surface.id} className="daemonstate-atlas-panel" aria-hidden={!open}>
                  <div className="daemonstate-atlas-panel-inner">
                    <div className="grid gap-7 px-3 pb-7 pl-[3.25rem] sm:grid-cols-[1fr_0.8fr] sm:px-5 sm:pb-9 sm:pl-[12.5rem]">
                      <div>
                        <div className="flex h-10 w-10 items-center justify-center rounded-xl border border-current/15 bg-white/10">
                          <Icon className="h-4 w-4" />
                        </div>
                        <p className="mt-5 max-w-xl text-sm leading-6 opacity-80">{surface.body}</p>
                        <Link
                          to={surface.to}
                          tabIndex={open ? undefined : -1}
                          className="daemonstate-atlas-link mt-6 inline-flex items-center gap-2 text-sm font-semibold"
                        >
                          {surface.action} <ArrowRight className="h-4 w-4" />
                        </Link>
                      </div>
                      <div className="daemonstate-atlas-payoff rounded-2xl border border-current/15 p-4">
                        <p className="text-[11px] font-semibold opacity-60">Continuity payoff</p>
                        <p className="mt-2 text-sm font-semibold leading-6">{surface.payoff}</p>
                        <div className="mt-5 flex flex-wrap gap-2">
                          {surface.tags.map((tag) => <span key={tag} className="daemonstate-atlas-chip">{tag}</span>)}
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              </article>
            );
          })}
        </PixelReveal>
      </div>
    </section>
  );
}

function HandoffPreview() {
  return (
    <article className="daemonstate-handoff-preview rounded-[1.75rem] border border-white/15 bg-[#f7f7f2] p-3 text-[#171713] shadow-[0_38px_100px_rgba(0,0,0,0.35)] sm:p-5">
      <div className="rounded-[1.25rem] border border-[#d8d8cf] bg-white p-5 sm:p-7">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[#deded6] pb-5">
          <div>
            <p className="text-xs font-semibold text-[#74746c]">Illustrative continuation bundle</p>
            <h3 className="mt-1 text-lg font-semibold">Provenance-safe source revisions</h3>
          </div>
          <span className="inline-flex items-center gap-2 rounded-full bg-[#edf7d0] px-3 py-2 text-xs font-semibold text-[#4f5d21]">
            <ShieldCheck className="h-4 w-4" />Ready to review
          </span>
        </div>

        <div className="divide-y divide-[#e2e2da]">
          {HANDOFF_ROWS.map(([type, value, source], index) => (
            <div key={type} className="daemonstate-handoff-row grid gap-2 py-5 sm:grid-cols-[8rem_1fr_auto] sm:items-start sm:gap-5" style={{ "--daemonstate-delay": String(index * 70) + "ms" }}>
              <span className="text-xs font-semibold text-[#77776e]">{type}</span>
              <span className="text-sm font-semibold leading-6">{value}</span>
              <span className="font-mono text-[11px] text-[#8a8a80]">{source}</span>
            </div>
          ))}
        </div>

        <div className="mt-3 grid gap-3 sm:grid-cols-3">
          <HandoffMetric value="5" label="selected facts" />
          <HandoffMetric value="2" label="explicit exclusions" />
          <HandoffMetric value="100%" label="source-linked" />
        </div>
      </div>
    </article>
  );
}

function HandoffMetric({ value, label }) {
  return (
    <div className="rounded-xl bg-[#efefe8] p-4">
      <p className="text-2xl font-semibold tracking-[-0.04em]">{value}</p>
      <p className="mt-1 text-xs text-[#6f6f67]">{label}</p>
    </div>
  );
}

function CurationCard({ tone, eyebrow, title, items }) {
  const selected = tone === "selected";
  const toneClasses = selected
    ? "border-[#bfd764] bg-[#eef6d4]"
    : "border-[#d7d7ce] bg-[#efefe9]";
  return (
    <article className={"daemonstate-curation-card min-h-[390px] overflow-hidden rounded-[1.75rem] border p-6 sm:p-9 " + toneClasses}>
      <div className="flex items-center justify-between">
        <p className="daemonstate-kicker">{eyebrow}</p>
        {selected ? <Sparkles className="h-5 w-5 text-[#768d26]" /> : <Database className="h-5 w-5 text-[#8a8a80]" />}
      </div>
      <h3 className="mt-12 max-w-xl text-4xl font-semibold leading-[1] tracking-[-0.045em] sm:text-5xl">{title}</h3>
      <ul className="mt-10 space-y-4">
        {items.map((item) => (
          <li key={item} className="flex gap-3 border-t border-black/10 pt-4 text-sm leading-6">
            <Check className="mt-1 h-4 w-4 shrink-0" />
            <span>{item}</span>
          </li>
        ))}
      </ul>
    </article>
  );
}

function Footer() {
  return (
    <footer className="daemonstate-landing-footer border-t border-[#9fb64a]">
      <div className="mx-auto flex w-full max-w-[1440px] flex-col gap-5 px-5 py-10 text-sm text-[#465212] sm:flex-row sm:items-center sm:justify-between sm:px-8 lg:px-12">
        <span>DaemonState · Context that moves with the work</span>
        <div className="flex flex-wrap gap-5">
          <Link to="/app">App</Link>
          <Link to="/app/sources">Sources</Link>
          <a href={GITHUB_URL} target="_blank" rel="noreferrer">GitHub</a>
        </div>
      </div>
    </footer>
  );
}

function PixelReveal({ children, className = "" }) {
  return (
    <div data-daemonstate-reveal="pixels" className={"daemonstate-pixel-reveal " + className}>
      <div className="daemonstate-pixel-content">{children}</div>
      <div className="daemonstate-pixel-curtain" aria-hidden="true">
        {Array.from({ length: PIXEL_COUNT }, (_, index) => {
          const row = Math.floor(index / 8);
          const column = index % 8;
          const delay = (column * 34) + (row * 52) + ((index * 7) % 5) * 18;
          return <span key={index} className="daemonstate-pixel-block" style={{ "--daemonstate-pixel-delay": delay + "ms" }} />;
        })}
      </div>
    </div>
  );
}

function useLandingMotion(landingRef) {
  useEffect(() => {
    const root = landingRef.current;
    if (!root) return undefined;

    const targets = Array.from(root.querySelectorAll("[data-daemonstate-reveal]"));
    const prefersReducedMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    const Observer = window.IntersectionObserver;

    if (prefersReducedMotion || !Observer) {
      targets.forEach((target) => target.setAttribute("data-visible", "true"));
      return undefined;
    }

    root.classList.add("daemonstate-motion-ready");
    const observer = new Observer((entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        entry.target.setAttribute("data-visible", "true");
        observer.unobserve(entry.target);
      });
    }, { rootMargin: "0px 0px -8% 0px", threshold: 0.12 });

    targets.forEach((target) => observer.observe(target));
    return () => observer.disconnect();
  }, [landingRef]);
}
