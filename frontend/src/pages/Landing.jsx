import { useEffect } from "react";
import { Link } from "react-router-dom";
import {
  Activity,
  ArrowRight,
  BrainCircuit,
  Check,
  Database,
  FileCode2,
  History,
  PlugZap,
  ShieldCheck,
  Sparkles,
  TestTube2,
  Waypoints,
} from "lucide-react";

import DaemonStateIcon from "../components/DaemonStateIcon";

const GITHUB_URL = "https://github.com/Darshan174/DaemonState";

const CONTINUATION_STEPS = [
  {
    number: "01",
    title: "Resolve the exact task",
    body: "Use the explicit request, selected workspace goal, or latest substantive session—without quietly turning the backlog into the plan.",
  },
  {
    number: "02",
    title: "Reconcile the checkpoint",
    body: "Check the saved task boundary against repository state, relevant files, event evidence, and recorded verification before it is trusted.",
  },
  {
    number: "03",
    title: "Build the right hierarchy",
    body: "Pair the durable Project Context parent with the task-specific Session Context child. Keep exclusions and missing evidence visible.",
  },
  {
    number: "04",
    title: "Continue and observe",
    body: "Stage a fresh Codex task in the app and wait for your confirmation, or use the CLI to launch, observe, and verify a selected provider.",
  },
];

const PRODUCT_SURFACES = [
  {
    group: "Work",
    title: "Continue",
    eyebrow: "Browser staging · Codex on macOS",
    body: "Resolve the selected task, reconcile its latest compatible checkpoint, and load a fresh Codex task. Nothing is submitted; Codex waits for you to confirm or narrow the compiled lead and press Enter.",
    to: "/app",
    action: "Open Continue",
    icon: Activity,
    featured: true,
  },
  {
    group: "Work",
    title: "Execute",
    eyebrow: "Workspace + session contexts",
    body: "Preview or copy Project Context, Current Session Context, and up to two selected Library sessions. Every boundary stays separate and quality-gated.",
    to: "/app/execute",
    action: "Open Execute",
    icon: BrainCircuit,
  },
  {
    group: "Inspect",
    title: "Library",
    eyebrow: "Local agent archives",
    body: "Search Codex, Claude Code, and OpenCode history by harness or topic. Select an exact session or recover a saved compaction checkpoint.",
    to: "/app/library",
    action: "Browse sessions",
    icon: History,
  },
  {
    group: "Inspect",
    title: "Evidence",
    eyebrow: "Provenance + conflicts",
    body: "Trace goals, decisions, sources, conflicts, and file relationships so a person can see why a claim was selected.",
    to: "/app/explain",
    action: "Trace the evidence",
    icon: Waypoints,
  },
  {
    group: "Setup",
    title: "Sources",
    eyebrow: "Raw material + revisions",
    body: "Inspect raw source previews, imports, extracted components, and source revisions behind graph claims and context packs.",
    to: "/app/sources",
    action: "Review sources",
    icon: Database,
  },
  {
    group: "Setup",
    title: "Integrations",
    eyebrow: "Connection state stays explicit",
    body: "See what is configured and what still needs setup. GitHub, Slack, Gmail, and Drive paths never masquerade as connected by default.",
    to: "/app/connectors",
    action: "Manage integrations",
    icon: PlugZap,
  },
];

const PROJECT_CONTEXT_ITEMS = [
  "Project identity and architecture",
  "Workflows and canonical commands",
  "Durable decisions and conventions",
  "Long-term constraints, risks, and direction",
];

const SESSION_CONTEXT_ITEMS = [
  "Goal and acceptance criteria",
  "Attempts, changes, and discoveries",
  "Touched files and verification",
  "Blockers and the exact next action",
];

export default function Landing() {
  useEffect(() => {
    const themeColor = document.querySelector('meta[name="theme-color"]');
    if (!themeColor) return undefined;
    const previousColor = themeColor.getAttribute("content");
    themeColor.setAttribute("content", "#f4f3ed");
    return () => {
      if (previousColor === null) {
        themeColor.removeAttribute("content");
      } else {
        themeColor.setAttribute("content", previousColor);
      }
    };
  }, []);

  return (
    <div
      data-landing-theme="fixed"
      className="daemonstate-landing min-h-screen text-[#171713] selection:bg-[#171713] selection:text-white"
    >
      <LandingNav />

      <main>
        <section className="daemonstate-landing-shell daemonstate-landing-hero">
          <div className="daemonstate-hero-grid">
            <div className="daemonstate-hero-copy min-w-0">
              <p className="daemonstate-eyebrow">
                <span className="daemonstate-live-dot" aria-hidden="true" />
                Source-available continuity for coding agents
              </p>
              <h1 className="daemonstate-display-hero">
                Continue the work. <span>Not the explanation.</span>
              </h1>
              <p className="daemonstate-hero-lede">
                DaemonState keeps durable Project Context separate from task-specific Session Context,
                reconciles both with the repository, and prepares the next agent to continue from
                evidence—not memory.
              </p>

              <div className="daemonstate-hero-actions">
                <Link to="/app" className="daemonstate-button daemonstate-button-primary">
                  Open Continue <ArrowRight className="h-4 w-4" aria-hidden="true" />
                </Link>
                <a href="#how-it-works" className="daemonstate-button daemonstate-button-secondary">
                  See how it works
                </a>
              </div>

              <ul className="daemonstate-trust-list" aria-label="Product qualities">
                <li><Check className="h-4 w-4" aria-hidden="true" />Local-first and self-hosted</li>
                <li><Check className="h-4 w-4" aria-hidden="true" />Source-backed context</li>
                <li><Check className="h-4 w-4" aria-hidden="true" />Active alpha</li>
              </ul>
            </div>

            <ContinuationPreview />
          </div>
        </section>

        <AvailabilityStrip />

        <section id="how-it-works" className="daemonstate-landing-section daemonstate-landing-shell">
          <SectionIntro
            eyebrow="How continuation works"
            title="A continuation, not a context dump."
            body="DaemonState does the retrieval and reconciliation work before the next agent sees a prompt. Broad evidence stays broad; the handoff stays finite."
          />

          <div className="daemonstate-step-grid">
            {CONTINUATION_STEPS.map((step) => (
              <article key={step.number} className="daemonstate-step-card">
                <span className="daemonstate-step-number">{step.number}</span>
                <div>
                  <h3>{step.title}</h3>
                  <p>{step.body}</p>
                </div>
              </article>
            ))}
          </div>
        </section>

        <section id="product" className="daemonstate-product-section">
          <div className="daemonstate-landing-shell daemonstate-landing-section">
            <SectionIntro
              eyebrow="The product today"
              title="Six focused surfaces. One continuity loop."
              body="The landing page now mirrors the app: Continue and Execute for the work, Library and Evidence for inspection, Sources and Integrations for setup."
              inverse
            />

            <div className="daemonstate-feature-grid">
              {PRODUCT_SURFACES.map((surface) => (
                <ProductCard key={surface.title} {...surface} />
              ))}
            </div>
          </div>
        </section>

        <section id="context-model" className="daemonstate-landing-section daemonstate-landing-shell">
          <SectionIntro
            eyebrow="Context without contamination"
            title="Two contexts. One clean boundary."
            body="Project knowledge should survive a task. Task debris should not automatically become project truth."
          />

          <div className="daemonstate-context-stage">
            <ContextCard
              label="Durable parent"
              title="Project Context"
              description="Objective-independent knowledge compiled across the workspace."
              items={PROJECT_CONTEXT_ITEMS}
              tone="project"
            />

            <div className="daemonstate-context-join" aria-hidden="true">
              <span />
              <ShieldCheck className="h-5 w-5" />
              <span />
            </div>

            <ContextCard
              label="Task-specific child"
              title="Current Session Context"
              description="The latest individual session boundary for the work in front of you."
              items={SESSION_CONTEXT_ITEMS}
              tone="session"
            />
          </div>

          <p className="daemonstate-context-note">
            Failed attempts and transient blockers stay in Session Context. Only durable project facts may enter Project Context, and only when mechanically verified, human-confirmed, or independently corroborated.
          </p>
        </section>

        <DeveloperSurface />

        <section className="daemonstate-landing-shell daemonstate-landing-section">
          <div className="daemonstate-proof-grid">
            <div className="daemonstate-proof-copy">
              <p className="daemonstate-eyebrow">Evidence before confidence</p>
              <h2 className="daemonstate-display-section">
                “Done” is not a verification result.
              </h2>
              <p>
                Automatic CLI and local runs report only what observed execution earned. Missing,
                failed, skipped, malformed, or unsupported evidence remains unproven instead of
                being polished into certainty.
              </p>
              <Link to="/app/explain" className="daemonstate-text-link">
                Inspect the evidence model <ArrowRight className="h-4 w-4" aria-hidden="true" />
              </Link>
            </div>

            <div className="daemonstate-outcome-panel" aria-label="Observed continuation outcomes">
              <OutcomeRow icon={ShieldCheck} label="Verified complete" detail="Every MUST requirement has passing required evidence" tone="verified" />
              <OutcomeRow icon={TestTube2} label="Requirements unproven" detail="Mandatory evidence is missing, failed, skipped, malformed, or unsupported" tone="unproven" />
              <OutcomeRow icon={PlugZap} label="Blocked external" detail="Provider access, credentials, permissions, billing, or infrastructure stopped execution" tone="external" />
              <OutcomeRow icon={Waypoints} label="Blocked ambiguity" detail="Explicit user intent is required before execution can proceed" tone="ambiguity" />
              <OutcomeRow icon={FileCode2} label="Execution failed" detail="The worker or an ordinary execution step failed" tone="failed" />
            </div>
          </div>
        </section>

        <section className="daemonstate-final-cta">
          <div className="daemonstate-landing-shell">
            <p className="daemonstate-eyebrow daemonstate-eyebrow-on-dark">
              Keep the project moving
            </p>
            <div className="daemonstate-final-cta-row">
              <h2>Give the next agent the state your project has already earned.</h2>
              <Link to="/app" className="daemonstate-button daemonstate-button-accent">
                Open DaemonState <ArrowRight className="h-4 w-4" aria-hidden="true" />
              </Link>
            </div>
          </div>
        </section>
      </main>

      <LandingFooter />
    </div>
  );
}

function LandingNav() {
  return (
    <header className="daemonstate-landing-nav">
      <div className="daemonstate-landing-shell daemonstate-nav-inner">
        <Link to="/" aria-label="DaemonState home" className="daemonstate-wordmark">
          <DaemonStateIcon size={32} className="shrink-0" />
          <span>DaemonState</span>
        </Link>

        <nav aria-label="Main navigation" className="daemonstate-nav-links">
          <a href="#how-it-works">How it works</a>
          <a href="#product">Product</a>
          <a href={GITHUB_URL} target="_blank" rel="noreferrer">GitHub</a>
          <Link to="/app" className="daemonstate-nav-cta">Open app</Link>
        </nav>
      </div>
    </header>
  );
}

function ContinuationPreview() {
  return (
    <aside className="daemonstate-continuation-preview" aria-label="Illustrative continuation preview">
      <div className="daemonstate-preview-glow" aria-hidden="true" />
      <header className="daemonstate-preview-header">
        <span className="daemonstate-preview-title">
          <Sparkles className="h-4 w-4" aria-hidden="true" />
          Continuation ready
        </span>
        <span className="daemonstate-preview-status">
          <span aria-hidden="true" />Codex staging
        </span>
      </header>

      <div className="daemonstate-preview-task">
        <span>Example task</span>
        <h2>Ship source revisions without breaking provenance</h2>
      </div>

      <div className="daemonstate-context-stack">
        <article className="daemonstate-preview-context daemonstate-preview-project">
          <div className="daemonstate-preview-context-heading">
            <span className="daemonstate-preview-context-icon"><Database className="h-4 w-4" /></span>
            <div>
              <p>Project Context</p>
              <span>Durable workspace parent</span>
            </div>
            <strong>Foundation ready</strong>
          </div>
          <div className="daemonstate-preview-lines" aria-hidden="true">
            <span /><span /><span />
          </div>
          <p className="daemonstate-preview-context-copy">
            Architecture · workflows · decisions · commands
          </p>
        </article>

        <article className="daemonstate-preview-context daemonstate-preview-session">
          <div className="daemonstate-preview-context-heading">
            <span className="daemonstate-preview-context-icon"><Activity className="h-4 w-4" /></span>
            <div>
              <p>Current Session Context</p>
              <span>Task-specific checkpoint</span>
            </div>
            <strong>Reconciled</strong>
          </div>
          <div className="daemonstate-preview-session-grid">
            <span>Goal</span><b>Preserve revision lineage</b>
            <span>Next</span><b>Run compiler contract tests</b>
          </div>
        </article>
      </div>

      <div className="daemonstate-preview-verification">
        <ShieldCheck className="h-4 w-4" aria-hidden="true" />
        <span>Repository fingerprint matched</span>
        <small>source-backed</small>
      </div>

      <div className="daemonstate-preview-action">
        <span>Stage fresh Codex task</span>
        <ArrowRight className="h-4 w-4" aria-hidden="true" />
      </div>
      <p className="daemonstate-preview-footnote">
        No turn submitted · waiting for you to confirm or narrow the lead
      </p>
    </aside>
  );
}

function AvailabilityStrip() {
  return (
    <section className="daemonstate-availability" aria-label="Current product availability">
      <div className="daemonstate-landing-shell daemonstate-availability-grid">
        <AvailabilityItem label="Browser staging" value="Codex on macOS" />
        <AvailabilityItem label="CLI adapters" value="Codex · Claude Code · OpenCode" />
        <AvailabilityItem label="Local inputs" value="Repositories + agent sessions" />
        <AvailabilityItem label="Proof standard" value="No silent verification" />
      </div>
    </section>
  );
}

function AvailabilityItem({ label, value }) {
  return (
    <div>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function SectionIntro({ eyebrow, title, body, inverse = false }) {
  return (
    <div className={`daemonstate-section-intro${inverse ? " daemonstate-section-intro-inverse" : ""}`}>
      <p className="daemonstate-eyebrow">{eyebrow}</p>
      <div>
        <h2 className="daemonstate-display-section">{title}</h2>
        <p className="daemonstate-section-lede">{body}</p>
      </div>
    </div>
  );
}

function ProductCard({ group, title, eyebrow, body, to, action, icon: Icon, featured = false }) {
  return (
    <article className={`daemonstate-feature-card${featured ? " daemonstate-feature-card-featured" : ""}`}>
      <div className="daemonstate-feature-card-topline">
        <span>{group}</span>
        <span className="daemonstate-feature-icon"><Icon className="h-5 w-5" aria-hidden="true" /></span>
      </div>
      <div>
        <p className="daemonstate-feature-eyebrow">{eyebrow}</p>
        <h3>{title}</h3>
        <p>{body}</p>
      </div>
      <Link to={to} className="daemonstate-feature-link">
        {action} <ArrowRight className="h-4 w-4" aria-hidden="true" />
      </Link>
    </article>
  );
}

function ContextCard({ label, title, description, items, tone }) {
  return (
    <article className={`daemonstate-context-card daemonstate-context-card-${tone}`}>
      <header>
        <p>{label}</p>
        <h3>{title}</h3>
        <span>{description}</span>
      </header>
      <ul>
        {items.map((item) => (
          <li key={item}>
            <Check className="h-4 w-4" aria-hidden="true" />
            <span>{item}</span>
          </li>
        ))}
      </ul>
    </article>
  );
}

function DeveloperSurface() {
  return (
    <section className="daemonstate-developer-section">
      <div className="daemonstate-landing-shell daemonstate-developer-grid">
        <div className="daemonstate-developer-copy">
          <p className="daemonstate-eyebrow daemonstate-eyebrow-on-dark">Agent-native by design</p>
          <h2 className="daemonstate-display-section">The same contract from UI to terminal.</h2>
          <p>
            Use Continue for a reviewable waiting handoff, the CLI for direct provider delivery,
            or MCP to return a context pack to the calling agent.
          </p>

          <div className="daemonstate-command-card" aria-label="DaemonState CLI continuation example">
            <div className="daemonstate-command-dots" aria-hidden="true"><span /><span /><span /></div>
            <code>
              <span>daemonstate continue \</span>
              <span>  --workspace-id &lt;workspace-uuid&gt; \</span>
              <span>  --repo . \</span>
              <span>  --into codex</span>
            </code>
          </div>
        </div>

        <div className="daemonstate-developer-cards">
          <DeveloperCard
            icon={FileCode2}
            title="CLI delivery"
            body="Audited adapters for Codex, Claude Code, and OpenCode—without permission-bypass flags or silent fallback."
          />
          <DeveloperCard
            icon={Waypoints}
            title="MCP handoff"
            body="Prepare, query, and return a continuation pack to the calling agent. MCP does not edit code or run shell commands."
          />
          <DeveloperCard
            icon={Sparkles}
            title="macOS floating control"
            body="Verify and copy Session Context or Workspace Context, then paste into the editor that retained focus when Accessibility access is available—never submit it."
          />
        </div>
      </div>
    </section>
  );
}

function DeveloperCard({ icon: Icon, title, body }) {
  return (
    <article>
      <span><Icon className="h-5 w-5" aria-hidden="true" /></span>
      <div>
        <h3>{title}</h3>
        <p>{body}</p>
      </div>
    </article>
  );
}

function OutcomeRow({ icon: Icon, label, detail, tone }) {
  return (
    <div className={`daemonstate-outcome-row daemonstate-outcome-${tone}`}>
      <span className="daemonstate-outcome-icon"><Icon className="h-4 w-4" aria-hidden="true" /></span>
      <div>
        <strong>{label}</strong>
        <p>{detail}</p>
      </div>
      <span className="daemonstate-outcome-dot" aria-hidden="true" />
    </div>
  );
}

function LandingFooter() {
  return (
    <footer className="daemonstate-landing-footer">
      <div className="daemonstate-landing-shell daemonstate-footer-inner">
        <Link to="/" aria-label="DaemonState home" className="daemonstate-wordmark">
          <DaemonStateIcon size={30} className="shrink-0" />
          <span>DaemonState</span>
        </Link>
        <p>Verified project history in. Minimum task-ready context out.</p>
        <nav aria-label="Footer navigation">
          <Link to="/app">Continue</Link>
          <Link to="/app/execute">Execute</Link>
          <Link to="/app/library">Library</Link>
          <a href="/assets/legal/LICENSE">License</a>
          <a href="/assets/legal/THIRD_PARTY_NOTICES.txt">Notices</a>
          <a href={GITHUB_URL} target="_blank" rel="noreferrer">GitHub</a>
        </nav>
      </div>
    </footer>
  );
}
