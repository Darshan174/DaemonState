import { useEffect, useId, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  ArrowRight,
  ArrowUpRight,
  Check,
  CircleDot,
  Code2,
  Database,
  FileCode2,
  Fingerprint,
  Layers3,
  Menu,
  ShieldCheck,
  Sparkles,
  X,
} from "lucide-react";

import DaemonStateIcon from "../components/DaemonStateIcon";
import openaiIcon from "../assets/openai-icon.png";
import { ApiError, api } from "../api/client";
import { WAITLIST_ONLY } from "../config/deployment";
import {
  WAITLIST_CONSENT_VERSION,
  analyticsAttribution,
  captureWaitlistEvent,
  waitlistAttribution,
} from "../waitlist/tracking";
import "./LandingReplica.css";

const GITHUB_URL = "https://github.com/Darshan174/DaemonState";
// 0.08s start delay + 0.55s color transition + 0.25s hold + 0.32s fade = 1.2s total.
const LOADER_MESSAGE_HOLD_SECONDS = 0.25;

const TOOL_NAMES = ["Codex", "Claude Code", "OpenCode", "Gemini", "Cursor", "Grok"];
const TOOL_MARQUEE_NAMES = TOOL_NAMES;
const ROTATING_AGENT_NAMES = [
  "Codex",
  "Claude Code",
  "OpenCode",
  "Cursor",
  "Gemini",
  "Grok",
];
const ROTATING_AGENT_INTERVAL_MS = 1000;

const DECK_CARDS = [
  {
    number: "01",
    eyebrow: "Session library",
    title: "Five sessions in. Still re-explaining the project.",
    type: "sessions",
  },
  {
    number: "02",
    eyebrow: "Decisions + evidence",
    title: "Context compaction kept the summary. It lost the nuance.",
    type: "graph",
  },
  {
    number: "03",
    eyebrow: "Workspace Context",
    title: "The session is still open. The model is already forgetting.",
    type: "memory",
  },
  {
    number: "04",
    eyebrow: "Session Context",
    title: "Claude looks better today. Too bad your context lives in Codex.",
    type: "handoff",
  },
  {
    number: "05",
    eyebrow: "Agent destination",
    title: "Every fresh chat starts with an expensive history lesson.",
    type: "continuity",
  },
];

const PROCESS_STEPS = [
  {
    number: "01",
    title: "Capture the working trail.",
    type: "capture",
  },
  {
    number: "02",
    title: "Verify it against the code.",
    type: "verify",
  },
  {
    number: "03",
    title: "Compose the next handoff.",
    type: "compose",
  },
];

const CAPTURE_SOURCES = [
  {
    name: "Codex",
    claim: "AuthMiddleware is mounted. The tests pass.",
  },
  {
    name: "Claude Code",
    claim: "The polling approach produced a race condition.",
  },
  {
    name: "Cursor",
    claim: "Migration 004 exists, but still needs verification.",
  },
  {
    name: "OpenCode",
    claim: "Next action: exercise the rollback path.",
  },
];

const CAPTURED_STATE = [
  ["Goal", "Finish the auth migration"],
  ["Decision", "Use AuthMiddleware"],
  ["Failed path", "Polling race condition"],
  ["Next", "Verify the rollback"],
];

const SESSION_CLAIMS = [
  "API now uses AuthMiddleware",
  "All tests pass",
  "Polling caused a race",
  "Migration 004 needs verification",
];

const REPOSITORY_EVIDENCE = [
  ["+", "app/api.py:48", "AuthMiddleware mounted"],
  ["○", "tests/", "No run at this snapshot"],
  ["!", "session cc_118", "Failure evidence preserved"],
  ["+", "migrations/004.py", "File exists; run absent"],
];

const RESOLVED_STATE = [
  ["API uses AuthMiddleware", "Supported by current source", "Verified", "verified"],
  ["All tests pass", "No run for this commit", "Unverified", "unverified"],
  ["Polling caused a race", "Preserved with its session", "Task-local", "task"],
];

const HANDOFF_CONTEXTS = [
  ["Foundation / required", "Workspace Context", "DaemonState"],
  ["Session 01", "Auth middleware", "Codex"],
  ["Session 02", "Polling failure", "Claude Code"],
  ["Session 03", "Rollback next step", "OpenCode"],
];

const HANDOFF_BRIEF = [
  ["Current state", "AuthMiddleware is mounted at the API boundary."],
  ["Known failure", "Do not retry polling; it produced a race condition."],
  ["Unverified", "Migration 004 has not run at the current snapshot."],
  ["First action", "Exercise the rollback path, then verify the migration."],
];

const HANDOFF_DESTINATIONS = ["Codex", "Claude Code", "Cursor", "OpenCode"];

const FEATURE_CARDS = [
  {
    number: "01",
    title: "Session Context",
    body: "The goal, progress, decisions, failed attempts, blockers, checks, and next action from one captured session.",
    icon: Fingerprint,
  },
  {
    number: "02",
    title: "Workspace Context",
    body: "Project-wide identity, architecture, capabilities, commands, repository state, and durable evidence.",
    icon: ShieldCheck,
  },
  {
    number: "03",
    title: "A clear boundary",
    body: "Task-local narration stays separate from project truth until current evidence supports it.",
    icon: FileCode2,
  },
];

function splitWords(text) {
  const words = text.split(" ");
  return words.map((word, index) => (
    <span className="dsr-reveal-word" key={`${word}-${index}`}>
      {word}
      {index < words.length - 1 ? " " : ""}
    </span>
  ));
}

function RotatingAgentName() {
  const [activeIndex, setActiveIndex] = useState(0);

  useEffect(() => {
    if (typeof window === "undefined") return undefined;

    const reducedMotion = typeof window.matchMedia === "function"
      ? window.matchMedia("(prefers-reduced-motion: reduce)")
      : null;
    let intervalId;

    const syncRotation = () => {
      if (intervalId) window.clearInterval(intervalId);
      intervalId = undefined;

      if (reducedMotion?.matches) return;
      intervalId = window.setInterval(() => {
        setActiveIndex((index) => (index + 1) % ROTATING_AGENT_NAMES.length);
      }, ROTATING_AGENT_INTERVAL_MS);
    };

    syncRotation();
    reducedMotion?.addEventListener?.("change", syncRotation);

    return () => {
      if (intervalId) window.clearInterval(intervalId);
      reducedMotion?.removeEventListener?.("change", syncRotation);
    };
  }, []);

  return (
    <span
      className="dsr-provider-rotator"
      aria-label="Codex, Claude Code, OpenCode, Cursor, Gemini, or Grok"
    >
      <span key={activeIndex} aria-hidden="true">
        {ROTATING_AGENT_NAMES[activeIndex]}
      </span>
    </span>
  );
}

export default function Landing({ waitlistOnlyMode = WAITLIST_ONLY }) {
  const pageRef = useRef(null);
  const landingViewCapturedRef = useRef(false);
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    if (landingViewCapturedRef.current) return;
    landingViewCapturedRef.current = true;
    const attribution = waitlistAttribution();
    captureWaitlistEvent("landing_viewed", analyticsAttribution(attribution));
  }, []);

  useEffect(() => {
    const themeColor = document.querySelector('meta[name="theme-color"]');
    if (!themeColor) return undefined;
    const previousColor = themeColor.getAttribute("content");
    themeColor.setAttribute("content", "#ffffff");
    return () => {
      if (previousColor === null) themeColor.removeAttribute("content");
      else themeColor.setAttribute("content", previousColor);
    };
  }, []);

  useEffect(() => {
    const root = pageRef.current;
    if (
      !root
      || typeof window === "undefined"
      || typeof window.matchMedia !== "function"
    ) {
      return undefined;
    }

    let cancelled = false;
    let context;
    let deckAdvanceCall;
    let deckTween;
    const cleanups = [];

    async function setupMotion() {
      const {
        gsap,
        ScrollTrigger,
      } = await import("gsap/all");

      if (cancelled || !root.isConnected) return;

      gsap.registerPlugin(ScrollTrigger);
      root.dataset.motion = "ready";

      const reducedMotion = window.matchMedia(
        "(prefers-reduced-motion: reduce)",
      ).matches;

      if (reducedMotion) {
        const loader = root.querySelector(".dsr-loader");
        if (loader) loader.setAttribute("hidden", "");
        return;
      }

      context = gsap.context(() => {
        const heroLeft = root.querySelector(".dsr-hero-heading-left");
        const heroRight = root.querySelector(".dsr-hero-heading-right");
        const heroDeck = root.querySelector(".dsr-deck-window");
        const nav = root.querySelector(".dsr-nav");
        const brand = root.querySelector(".dsr-brand");
        const navPill = root.querySelector(".dsr-nav-pill");
        const loader = root.querySelector(".dsr-loader");

        gsap.timeline({ defaults: { ease: "power3.inOut" } })
          .set([heroLeft, heroRight], { willChange: "transform" })
          .fromTo(
            loader,
            { autoAlpha: 1, backgroundColor: "#777775" },
            { backgroundColor: "#ffffff", duration: 0.55, delay: 0.08 },
          )
          .to(loader, {
            autoAlpha: 0,
            duration: 0.32,
            delay: LOADER_MESSAGE_HOLD_SECONDS,
          })
          .from(
            nav,
            { yPercent: -130, duration: 0.7, ease: "power4.out" },
            "-=0.12",
          )
          .fromTo(
            heroLeft,
            { x: () => Math.min(window.innerWidth * 0.28, 390) },
            { x: 0, duration: 1.05, ease: "expo.inOut" },
            "-=0.5",
          )
          .fromTo(
            heroRight,
            { x: () => -Math.min(window.innerWidth * 0.28, 390) },
            { x: 0, duration: 1.05, ease: "expo.inOut" },
            "<",
          )
          .from(
            heroDeck,
            {
              scale: 1.38,
              autoAlpha: 0,
              duration: 0.92,
              ease: "expo.out",
            },
            "-=0.72",
          )
          .from(
            ".dsr-hero-support",
            {
              y: 18,
              autoAlpha: 0,
              stagger: 0.08,
              duration: 0.6,
              ease: "power3.out",
            },
            "-=0.35",
          );

        const deckTrack = root.querySelector(".dsr-deck-track");
        const deckWindow = root.querySelector(".dsr-deck-window");
        const deckCards = gsap.utils.toArray(".dsr-deck-card", root);
        const deckCounter = root.querySelector(".dsr-deck-count");
        let deckStep = 0;
        let deckActiveIndex = 0;
        let deckDirection = 1;
        let deckPaused = false;
        const deckPauseReasons = new Set();

        const updateDeckCards = () => {
          const trackY = Number(gsap.getProperty(deckTrack, "y")) || 0;
          const activeIndex = Math.max(
            0,
            Math.min(
              deckCards.length - 1,
              Math.round(Math.abs(trackY) / Math.max(deckStep, 1)),
            ),
          );

          if (deckCounter) {
            deckCounter.textContent = String(activeIndex + 1).padStart(2, "0");
          }

          deckCards.forEach((card, index) => {
            const distance = Math.min(
              Math.abs(index * deckStep + trackY) / Math.max(deckStep, 1),
              1,
            );
            gsap.set(card, {
              scale: 1 - distance * 0.085,
              opacity: 1 - distance * 0.48,
              rotateZ: (index - activeIndex) * 0.65,
            });
          });
        };

        const sizeDeck = (activeIndex = deckActiveIndex) => {
          if (!deckCards.length || !deckTrack) return;
          const firstCard = deckCards[0];
          const styles = window.getComputedStyle(deckTrack);
          deckStep = firstCard.offsetHeight
            + Number.parseFloat(styles.rowGap || styles.gap || "0");
          deckActiveIndex = Math.max(
            0,
            Math.min(deckCards.length - 1, activeIndex),
          );
          gsap.set(deckTrack, {
            y: -deckStep * deckActiveIndex,
          });
          updateDeckCards();
        };

        const scheduleDeckAdvance = (delay = 2.35) => {
          deckAdvanceCall?.kill();
          if (deckPaused || !deckStep || deckCards.length < 2) return;
          deckAdvanceCall = gsap.delayedCall(delay, () => {
            if (deckActiveIndex >= deckCards.length - 1) deckDirection = -1;
            else if (deckActiveIndex <= 0) deckDirection = 1;

            const nextIndex = deckActiveIndex + deckDirection;
            deckActiveIndex = nextIndex;
            deckTween?.kill();
            deckTween = gsap.to(deckTrack, {
              y: -deckStep * deckActiveIndex,
              duration: 1.15,
              ease: "power3.inOut",
              onUpdate: updateDeckCards,
              onComplete: () => {
                updateDeckCards();
                scheduleDeckAdvance();
              },
            });
          });
        };

        const pauseDeck = (reason) => {
          deckPauseReasons.add(reason);
          if (deckPaused) return;
          deckPaused = true;
          deckWindow?.setAttribute("data-autoplay", "paused");
          deckAdvanceCall?.pause();
        };

        const resumeDeck = (reason) => {
          deckPauseReasons.delete(reason);
          if (deckPauseReasons.size) return;
          deckPaused = false;
          deckWindow?.setAttribute("data-autoplay", "playing");
          if (!deckTween?.isActive()) scheduleDeckAdvance(1.1);
        };

        sizeDeck(0);
        scheduleDeckAdvance(1.8);

        const handleDeckResize = () => {
          deckTween?.kill();
          deckAdvanceCall?.kill();
          sizeDeck(deckActiveIndex);
          if (!deckPaused) scheduleDeckAdvance(1.1);
        };

        const handleDeckVisibility = () => {
          if (document.hidden) pauseDeck("visibility");
          else resumeDeck("visibility");
        };
        const handleDeckMouseEnter = () => pauseDeck("pointer");
        const handleDeckMouseLeave = () => resumeDeck("pointer");
        const handleDeckFocusIn = () => pauseDeck("focus");
        const handleDeckFocusOut = () => resumeDeck("focus");

        window.addEventListener("resize", handleDeckResize, { passive: true });
        deckWindow?.addEventListener("mouseenter", handleDeckMouseEnter);
        deckWindow?.addEventListener("mouseleave", handleDeckMouseLeave);
        deckWindow?.addEventListener("focusin", handleDeckFocusIn);
        deckWindow?.addEventListener("focusout", handleDeckFocusOut);
        document.addEventListener("visibilitychange", handleDeckVisibility);
        cleanups.push(() => {
          window.removeEventListener("resize", handleDeckResize);
          deckWindow?.removeEventListener("mouseenter", handleDeckMouseEnter);
          deckWindow?.removeEventListener("mouseleave", handleDeckMouseLeave);
          deckWindow?.removeEventListener("focusin", handleDeckFocusIn);
          deckWindow?.removeEventListener("focusout", handleDeckFocusOut);
          document.removeEventListener("visibilitychange", handleDeckVisibility);
        });

        const hero = root.querySelector(".dsr-hero");
        const handleHeroMove = (event) => {
          if (event.pointerType === "touch") return;
          const x = (event.clientX / window.innerWidth - 0.5) * 5;
          const y = (event.clientY / window.innerHeight - 0.5) * -4;
          gsap.to(heroDeck, {
            rotateY: x,
            rotateX: y,
            transformPerspective: 1100,
            duration: 0.7,
            ease: "power3.out",
          });
        };
        const handleHeroLeave = () => {
          gsap.to(heroDeck, {
            rotateX: 0,
            rotateY: 0,
            duration: 0.8,
            ease: "power3.out",
          });
        };

        hero?.addEventListener("pointermove", handleHeroMove);
        hero?.addEventListener("pointerleave", handleHeroLeave);
        cleanups.push(() => {
          hero?.removeEventListener("pointermove", handleHeroMove);
          hero?.removeEventListener("pointerleave", handleHeroLeave);
        });

        gsap.to(".dsr-reveal-word", {
          color: "#f4f4ef",
          stagger: 0.08,
          ease: "none",
          scrollTrigger: {
            trigger: ".dsr-problem-copy",
            start: "top 68%",
            end: "bottom 38%",
            scrub: true,
          },
        });

        gsap.to(".dsr-tools-track", {
          xPercent: -50,
          duration: 24,
          ease: "none",
          repeat: -1,
        });

        const lightSections = gsap.utils.toArray(
          ".dsr-hero, .dsr-features, .dsr-final",
          root,
        );
        const updateBrandContrast = () => {
          const sampleY = 48;
          const isOnLight = lightSections.some((section) => {
            const rect = section.getBoundingClientRect();
            return rect.top <= sampleY && rect.bottom > sampleY;
          });
          brand?.classList.toggle("is-on-light", isOnLight);
          navPill?.classList.toggle("is-on-light", isOnLight);
        };

        ScrollTrigger.create({
          start: 0,
          end: "max",
          onUpdate: updateBrandContrast,
          onRefresh: updateBrandContrast,
        });
        updateBrandContrast();

        const stackCards = gsap.utils.toArray(".dsr-stack-card", root);
        if (stackCards.length === 3) {
          gsap.set(stackCards.slice(1), { yPercent: 112 });
          gsap.set(stackCards[1], { rotateZ: 2.2 });
          gsap.set(stackCards[2], { rotateZ: -1.8 });

          gsap.timeline({
            scrollTrigger: {
              trigger: ".dsr-stack",
              start: "top top",
              end: "+=2300",
              pin: ".dsr-stack-sticky",
              scrub: 1,
              anticipatePin: 1,
            },
          })
            .to(
              stackCards[0],
              { yPercent: -8, scale: 0.93, opacity: 0.38, ease: "none" },
              0,
            )
            .to(
              stackCards[1],
              { yPercent: 0, rotateZ: 0, ease: "none" },
              0,
            )
            .to(
              stackCards[1],
              { yPercent: -6, scale: 0.95, opacity: 0.42, ease: "none" },
              1,
            )
            .to(
              stackCards[2],
              { yPercent: 0, rotateZ: 0, ease: "none" },
              1,
            );
        }

        gsap.from(".dsr-feature-card", {
          y: 130,
          rotateZ: (index) => (index - 1) * 3,
          autoAlpha: 0,
          stagger: 0.12,
          duration: 1,
          ease: "power4.out",
          scrollTrigger: {
            trigger: ".dsr-features-grid",
            start: "top 78%",
            toggleActions: "play none none reverse",
          },
        });

        gsap.from(".dsr-final-letter", {
          yPercent: 110,
          rotateZ: 4,
          stagger: 0.035,
          duration: 1.05,
          ease: "power4.out",
          scrollTrigger: {
            trigger: ".dsr-final",
            start: "top 68%",
            toggleActions: "play none none reverse",
          },
        });

        ScrollTrigger.refresh();
      }, root);
    }

    setupMotion();

    return () => {
      cancelled = true;
      deckAdvanceCall?.kill();
      deckTween?.kill();
      cleanups.forEach((cleanup) => cleanup());
      context?.revert();
    };
  }, []);

  useEffect(() => {
    if (!menuOpen) return undefined;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previousOverflow;
    };
  }, [menuOpen]);

  const closeMenu = () => setMenuOpen(false);

  return (
    <div
      ref={pageRef}
      data-landing-theme="fixed"
      className="daemonstate-landing dsr-landing"
    >
      <div className="dsr-loader" aria-hidden="true">
        <span>Project state for the next session</span>
      </div>

      <LandingNav
        menuOpen={menuOpen}
        setMenuOpen={setMenuOpen}
        closeMenu={closeMenu}
        waitlistOnlyMode={waitlistOnlyMode}
      />

      <main>
        <section className="dsr-hero" aria-labelledby="hero-heading">
          <h1
            id="hero-heading"
            className="dsr-hero-heading"
            aria-label="The docking layer for AI agents."
          >
            <span className="dsr-hero-heading-left">The docking layer</span>
            <span className="dsr-hero-heading-right">for AI agents.</span>
          </h1>

          <HeroDeck />

          <div className="dsr-hero-support">
            <p>
              DaemonState keeps your project context alive across every session
              with <RotatingAgentName />.
            </p>
            <p>Self-hosted. Source-backed. User-reviewed.</p>
            <div className="dsr-hero-links">
              <a href="#how-it-works" className="dsr-hero-text-link">
                See how it works
                <ArrowRight aria-hidden="true" />
              </a>
            </div>
          </div>

          <a href="#problem" className="dsr-scroll-cue" aria-label="Scroll to learn more">
            <span />
          </a>
        </section>

        <section id="problem" className="dsr-problem">
          <div className="dsr-section-shell dsr-problem-copy">
            <SectionMarker label="The blind start" number="01" />
            <h2>Every new agent starts partially blind.</h2>
            <p className="dsr-problem-statement">
              {splitWords(
                "A fresh session can see the repository. It cannot see why the work is in its current state, which paths already failed, or what was actually verified.",
              )}
            </p>
            <div className="dsr-problem-foot">
              <p>
                DaemonState captures that missing working state and reconciles
                it with current project evidence.
              </p>
              <strong>Start from captured work, not a reconstructed prompt.</strong>
            </div>
          </div>
        </section>

        <ToolsBand />

        <section id="how-it-works" className="dsr-stack">
          <div className="dsr-stack-sticky">
            <div className="dsr-section-shell dsr-stack-heading">
              <SectionMarker label="The handoff loop" number="02" />
              <h2>Turn scattered sessions into trusted context.</h2>
              <p>Capture what each agent learned, check it against the code, and continue in any tool.</p>
            </div>

            <div className="dsr-stack-cards">
              {PROCESS_STEPS.map((step) => (
                <ProcessCard key={step.number} {...step} />
              ))}
            </div>
          </div>
        </section>

        <section className="dsr-features" aria-labelledby="features-heading">
          <div className="dsr-section-shell">
            <div className="dsr-features-heading">
              <SectionMarker label="The state model" number="03" dark />
              <h2 id="features-heading">Two contexts. One project.</h2>
            </div>
            <div className="dsr-features-grid">
              {FEATURE_CARDS.map((feature) => (
                <FeatureCard key={feature.number} {...feature} />
              ))}
            </div>
          </div>
        </section>

        <section id="early-access" className="dsr-final">
          <div className="dsr-final-topline">
            <span>The docking layer for AI coding agents</span>
            <span>Early access / 2026</span>
          </div>

          <div className="dsr-final-copy">
            <p>The state of your work should not belong to one session, model, or tool.</p>
            <h2 aria-label="The agents change. The project remembers.">
              <AnimatedPhrase text="The agents change." />
              <AnimatedPhrase text="The project remembers." offset />
            </h2>
          </div>

          <div className="dsr-final-actions">
            <WaitlistForm />
            <a
              href={GITHUB_URL}
              target="_blank"
              rel="noreferrer"
              className="dsr-text-link"
            >
              Follow the build
              <ArrowUpRight aria-hidden="true" />
            </a>
          </div>
        </section>
      </main>

      <LandingFooter waitlistOnlyMode={waitlistOnlyMode} />
    </div>
  );
}

function WaitlistForm() {
  const [email, setEmail] = useState("");
  const [website, setWebsite] = useState("");
  const [submission, setSubmission] = useState("idle");
  const [message, setMessage] = useState(
    "Private beta. No spam — just launch access and occasional progress notes.",
  );

  const handleSubmit = async (event) => {
    event.preventDefault();
    setSubmission("submitting");
    setMessage("Saving your place…");
    const attribution = waitlistAttribution();
    const analyticsProperties = analyticsAttribution(attribution);
    captureWaitlistEvent("waitlist_cta_clicked", analyticsProperties);

    try {
      const result = await api.post("/waitlist", {
        email,
        website,
        ...attribution,
        consent_version: WAITLIST_CONSENT_VERSION,
      });
      setSubmission("success");
      setEmail("");
      setMessage(result.message || "You're on the DaemonState waitlist.");
      captureWaitlistEvent("waitlist_joined", analyticsProperties);
    } catch (error) {
      setSubmission("error");
      setMessage(
        error instanceof ApiError && error.status === 429
          ? "Too many attempts. Please wait a minute and try again."
          : "We couldn't save your email. Please check it and try again.",
      );
    }
  };

  const isSubmitting = submission === "submitting";
  const isSuccess = submission === "success";

  return (
    <div className={`dsr-waitlist-card is-${submission}`}>
      <div className="dsr-waitlist-heading">
        <span>EARLY ACCESS / PRIVATE BETA</span>
        <h3>Join the private beta.</h3>
        <p>
          Get early access to DaemonState and help shape a practical continuity
          layer for coding agents.
        </p>
      </div>

      <form onSubmit={handleSubmit} aria-label="Join the early-access waitlist">
        <label htmlFor="waitlist-email">Email address</label>
        <div className="dsr-waitlist-field">
          <input
            id="waitlist-email"
            name="email"
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            placeholder="you@company.com"
            autoComplete="email"
            inputMode="email"
            maxLength={320}
            required
            disabled={isSubmitting || isSuccess}
            aria-describedby="waitlist-message waitlist-consent"
          />
          <button type="submit" disabled={isSubmitting || isSuccess}>
            <span>
              {isSubmitting ? "Joining…" : isSuccess ? "You're in" : "Join waitlist"}
            </span>
            {isSuccess ? <Check aria-hidden="true" /> : <ArrowRight aria-hidden="true" />}
          </button>
        </div>

        <div className="dsr-waitlist-honeypot" aria-hidden="true">
          <label htmlFor="waitlist-website">Website</label>
          <input
            id="waitlist-website"
            name="website"
            type="text"
            value={website}
            onChange={(event) => setWebsite(event.target.value)}
            autoComplete="off"
            tabIndex={-1}
          />
        </div>

        <p id="waitlist-consent" className="dsr-waitlist-consent">
          By joining, you agree to receive private-beta access and occasional
          product updates. Unsubscribe anytime.{" "}
          <Link to="/privacy" target="_blank" rel="noreferrer">Privacy notice</Link>.
        </p>
      </form>

      <p
        id="waitlist-message"
        className="dsr-waitlist-message"
        role="status"
        aria-live="polite"
      >
        {message}
      </p>
    </div>
  );
}

function LandingNav({ menuOpen, setMenuOpen, closeMenu, waitlistOnlyMode }) {
  const links = [
    { href: "#problem", label: "Why" },
    { href: "#docking-layer", label: "Layer" },
    { href: "#how-it-works", label: "Method" },
  ];

  return (
    <>
      <header className="dsr-nav">
        <Link to="/" aria-label="DaemonState home" className="dsr-brand">
          <DaemonStateIcon size={29} />
          <span>DaemonState</span>
        </Link>

        <nav aria-label="Main navigation" className="dsr-nav-pill">
          {links.map((link) => (
            <RollAnchor key={link.href} href={link.href}>
              <span>{link.label}</span>
            </RollAnchor>
          ))}
        </nav>

        <div className="dsr-nav-actions">
          {!waitlistOnlyMode && (
            <Link to="/app" className="dsr-nav-product">
              <span>Open product</span>
              <ArrowUpRight aria-hidden="true" />
            </Link>
          )}
          <a
            href="#early-access"
            className="dsr-nav-join"
            aria-label="Join waitlist"
          >
            <span>Join waitlist</span>
            <ArrowUpRight aria-hidden="true" />
          </a>
          <button
            type="button"
            className="dsr-menu-button"
            aria-label="Open navigation"
            aria-expanded={menuOpen}
            onClick={() => setMenuOpen(true)}
          >
            <Menu aria-hidden="true" />
          </button>
        </div>
      </header>

      <div
        className={`dsr-mobile-menu${menuOpen ? " is-open" : ""}`}
        role="dialog"
        aria-modal="true"
        aria-label="Navigation"
        aria-hidden={!menuOpen}
      >
        <button
          type="button"
          aria-label="Close navigation"
          onClick={closeMenu}
          className="dsr-mobile-close"
        >
          <X aria-hidden="true" />
        </button>
        <nav aria-label="Mobile navigation">
          {!waitlistOnlyMode && (
            <Link to="/app" onClick={closeMenu}>
              <span>Open product</span>
            </Link>
          )}
          {links.map((link) => (
            <a key={link.href} href={link.href} onClick={closeMenu}>
              <span>{link.label}</span>
            </a>
          ))}
        </nav>
        <a href="#early-access" onClick={closeMenu}>
          Join the waitlist
          <ArrowUpRight aria-hidden="true" />
        </a>
      </div>
    </>
  );
}

function RollAnchor({ href, children }) {
  return (
    <a href={href} className="dsr-roll-link">
      <span className="dsr-roll-current">{children}</span>
      <span className="dsr-roll-next" aria-hidden="true">
        {children}
      </span>
    </a>
  );
}

function SectionMarker({ label, number, dark = false }) {
  return (
    <div className={`dsr-section-marker${dark ? " is-dark" : ""}`}>
      <span aria-hidden="true" />
      <p>{label}</p>
      <small>{number}</small>
    </div>
  );
}

function HeroDeck() {
  return (
    <div
      aria-label="Project memory examples carousel."
      className="dsr-deck-window"
      data-autoplay="playing"
      tabIndex={0}
    >
      <div className="dsr-deck-track-shell">
        <div className="dsr-deck-track">
          {DECK_CARDS.map((card) => (
            <DeckCard key={card.number} {...card} />
          ))}
        </div>
      </div>
      <span className="dsr-deck-index">
        / <b className="dsr-deck-count">01</b>
      </span>
    </div>
  );
}

function DeckCard({ number, eyebrow, title, type }) {
  return (
    <article className={`dsr-deck-card dsr-deck-card-${type}`}>
      <header>
        <span>{eyebrow}</span>
        <small>/{number}</small>
      </header>
      <h3>{title}</h3>
      <DeckVisual type={type} />
    </article>
  );
}

function DeckVisual({ type }) {
  if (type === "sessions") {
    return (
      <div className="dsr-deck-visual dsr-session-orbit" aria-hidden="true">
        {TOOL_NAMES.map((name, index) => (
          <span
            className="dsr-session-agent"
            key={name}
            style={{ "--index": index }}
          >
            <AgentLogo name={name} />
          </span>
        ))}
        <i><Layers3 /></i>
      </div>
    );
  }

  if (type === "graph") {
    return (
      <div className="dsr-deck-visual dsr-graph-visual" aria-hidden="true">
        <span className="dsr-graph-node is-main">Decision</span>
        <span className="dsr-graph-node is-one">Evidence</span>
        <span className="dsr-graph-node is-two">Files</span>
        <span className="dsr-graph-node is-three">Failed path</span>
        <svg
          className="dsr-graph-connectors"
          viewBox="0 0 100 100"
          preserveAspectRatio="none"
        >
          <path d="M50 38 C42 49 25 52 19 70" />
          <path d="M50 38 C50 49 48 60 48 76" />
          <path d="M50 38 C59 48 76 51 82 67" />
        </svg>
      </div>
    );
  }

  if (type === "memory") {
    return (
      <div className="dsr-deck-visual dsr-memory-mosaic" aria-hidden="true">
        <span className="dsr-mosaic-tile tile-a"><Code2 /></span>
        <span className="dsr-mosaic-tile tile-b">14<br /><small>DECISIONS</small></span>
        <span className="dsr-mosaic-tile tile-c"><DaemonStateIcon size={42} /></span>
        <span className="dsr-mosaic-tile tile-d">08<br /><small>KEY FILES</small></span>
        <span className="dsr-mosaic-tile tile-e"><Database /></span>
        <i className="dsr-mosaic-ring" />
      </div>
    );
  }

  if (type === "handoff") {
    return (
      <div className="dsr-deck-visual dsr-handoff-visual" aria-hidden="true">
        <div>
          <span><CircleDot /> STATE COMPILED</span>
          <strong>Continue provider adapter work</strong>
          <small>Decision sourced · Blocker surfaced · Next action clear</small>
        </div>
        <ArrowRight />
      </div>
    );
  }

  return (
    <div className="dsr-deck-visual dsr-continuity-visual" aria-hidden="true">
      {["Codex", "Claude Code", "OpenCode"].map((name, index) => (
        <span className="dsr-continuity-step" key={name}>
          <span className="dsr-continuity-agent">
            <AgentLogo name={name} />
          </span>
          {index < 2 && <i />}
        </span>
      ))}
    </div>
  );
}

function AgentLogo({ name }) {
  const geminiGradientId = useId().replaceAll(":", "");

  if (name === "Codex") {
    return (
      <span className="dsr-agent-logo dsr-agent-logo-codex" title="Codex">
        <img src={openaiIcon} alt="" />
      </span>
    );
  }

  if (name === "Claude Code") {
    return (
      <span className="dsr-agent-logo dsr-agent-logo-claude" title="Claude Code">
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="m4.7144 15.9555 4.7174-2.6471.079-.2307-.079-.1275h-.2307l-.7893-.0486-2.6956-.0729-2.3375-.0971-2.2646-.1214-.5707-.1215-.5343-.7042.0546-.3522.4797-.3218.686.0608 1.5179.1032 2.2767.1578 1.6514.0972 2.4468.255h.3886l.0546-.1579-.1336-.0971-.1032-.0972L6.973 9.8356l-2.55-1.6879-1.3356-.9714-.7225-.4918-.3643-.4614-.1578-1.0078.6557-.7225.8803.0607.2246.0607.8925.686 1.9064 1.4754 2.4893 1.8336.3643.3035.1457-.1032.0182-.0728-.164-.2733-1.3539-2.4467-1.445-2.4893-.6435-1.032-.17-.6194c-.0607-.255-.1032-.4674-.1032-.7285L6.287.1335 6.6997 0l.9957.1336.419.3642.6192 1.4147 1.0018 2.2282 1.5543 3.0296.4553.8985.2429.8318.091.255h.1579v-.1457l.1275-1.706.2368-2.0947.2307-2.6957.0789-.7589.3764-.9107.7468-.4918.5828.2793.4797.686-.0668.4433-.2853 1.8517-.5586 2.9021-.3643 1.9429h.2125l.2429-.2429.9835-1.3053 1.6514-2.0643.7286-.8196.85-.9046.5464-.4311h1.0321l.759 1.1293-.34 1.1657-1.0625 1.3478-.8804 1.1414-1.2628 1.7-.7893 1.36.0729.1093.1882-.0183 2.8535-.607 1.5421-.2794 1.8396-.3157.8318.3886.091.3946-.3278.8075-1.967.4857-2.3072.4614-3.4364.8136-.0425.0304.0486.0607 1.5482.1457.6618.0364h1.621l3.0175.2247.7892.522.4736.6376-.079.4857-1.2142.6193-1.6393-.3886-3.825-.9107-1.3113-.3279h-.1822v.1093l1.0929 1.0686 2.0035 1.8092 2.5075 2.3314.1275.5768-.3218.4554-.34-.0486-2.2039-1.6575-.85-.7468-1.9246-1.621h-.1275v.17l.4432.6496 2.3436 3.5214.1214 1.0807-.17.3521-.6071.2125-.6679-.1214-1.3721-1.9246L14.38 17.959l-1.1414-1.9428-.1397.079-.674 7.2552-.3156.3703-.7286.2793-.6071-.4614-.3218-.7468.3218-1.4753.3886-1.9246.3157-1.53.2853-1.9004.17-.6314-.0121-.0425-.1397.0182-1.4328 1.9672-2.1796 2.9446-1.7243 1.8456-.4128.164-.7164-.3704.0667-.6618.4008-.5889 2.386-3.0357 1.4389-1.882.929-1.0868-.0062-.1579h-.0546l-6.3385 4.1164-1.1293.1457-.4857-.4554.0608-.7467.2307-.2429 1.9064-1.3114Z" />
        </svg>
      </span>
    );
  }

  if (name === "OpenCode") {
    return (
      <span className="dsr-agent-logo dsr-agent-logo-opencode" title="OpenCode">
        <svg viewBox="0 0 96 96" aria-hidden="true">
          <rect className="dsr-opencode-frame" x="24" y="24" width="48" height="48" />
          <rect className="dsr-opencode-cutout" x="36" y="36" width="24" height="12" />
          <rect className="dsr-opencode-screen" x="36" y="48" width="24" height="12" />
        </svg>
      </span>
    );
  }

  if (name === "Gemini") {
    return (
      <span className="dsr-agent-logo dsr-agent-logo-gemini" title="Gemini">
        <svg viewBox="0 0 48 48" aria-hidden="true">
          <defs>
            <linearGradient
              id={geminiGradientId}
              x1="7"
              y1="5"
              x2="42"
              y2="43"
              gradientUnits="userSpaceOnUse"
            >
              <stop offset="0" stopColor="#ea4335" />
              <stop offset="0.32" stopColor="#fbbc04" />
              <stop offset="0.62" stopColor="#34a853" />
              <stop offset="1" stopColor="#4285f4" />
            </linearGradient>
          </defs>
          <path
            d="M24 3C25.6 14.7 33.3 22.4 45 24C33.3 25.6 25.6 33.3 24 45C22.4 33.3 14.7 25.6 3 24C14.7 22.4 22.4 14.7 24 3Z"
            fill={`url(#${geminiGradientId})`}
          />
        </svg>
      </span>
    );
  }

  if (name === "Cursor") {
    return (
      <span className="dsr-agent-logo dsr-agent-logo-cursor" title="Cursor">
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="M11.503.131 1.891 5.678a.84.84 0 0 0-.42.726v11.188c0 .3.162.575.42.724l9.609 5.55a1 1 0 0 0 .998 0l9.61-5.55a.84.84 0 0 0 .42-.724V6.404a.84.84 0 0 0-.42-.726L12.497.131a1.01 1.01 0 0 0-.996 0M2.657 6.338h18.55c.263 0 .43.287.297.515L12.23 22.918c-.062.107-.229.064-.229-.06V12.335a.59.59 0 0 0-.295-.51l-9.11-5.257c-.109-.063-.064-.23.061-.23" />
        </svg>
      </span>
    );
  }

  if (name === "Grok") {
    return (
      <span className="dsr-agent-logo dsr-agent-logo-grok" title="Grok">
        <svg viewBox="0 0 34 32" fill="none" aria-hidden="true">
          <path
            d="M13.374 20.5407L24.4555 12.3506C24.9988 11.9491 25.7753 12.1057 26.0342 12.7294C27.3966 16.0185 26.7879 19.9712 24.0772 22.6851C21.3666 25.3989 17.595 25.9941 14.1477 24.6386L10.3818 26.3843C15.7832 30.0806 22.3422 29.1665 26.4409 25.0601C29.692 21.8051 30.6989 17.3683 29.7574 13.3673L29.7659 13.3758C28.4006 7.49809 30.1016 5.14871 33.5859 0.344576C33.6683 0.230667 33.7508 0.116757 33.8333 0L29.2482 4.59055V4.57631L13.3712 20.5436"
            fill="currentColor"
          />
          <path
            d="M11.0867 22.5312C7.20979 18.8234 7.87821 13.0852 11.1862 9.77618C13.6323 7.3271 17.64 6.32755 21.1385 7.79698L24.8959 6.05986C24.219 5.57005 23.3514 5.04322 22.3559 4.67301C17.8562 2.81914 12.469 3.7418 8.81115 7.40114C5.29271 10.9238 4.18626 16.3402 6.08628 20.9621C7.5056 24.4164 5.17893 26.8597 2.8352 29.3259C2.00465 30.2001 1.17126 31.0744 0.5 31.9999L11.0838 22.534"
            fill="currentColor"
          />
        </svg>
      </span>
    );
  }

  return (
    <span className="dsr-agent-logo dsr-agent-logo-any" title={name}>
      <Sparkles aria-hidden="true" />
    </span>
  );
}

function ToolsBand() {
  const repeatedTools = [...TOOL_MARQUEE_NAMES, ...TOOL_MARQUEE_NAMES];

  return (
    <section id="docking-layer" className="dsr-tools" aria-labelledby="tools-heading">
      <div className="dsr-tools-proof">
        <div className="dsr-tools-proof-copy">
          <h2 id="tools-heading">
            One project. <span>Many sessions.</span>
          </h2>
          <p>
            A source-backed continuity layer between the repository, the captured
            session, and the coding agent you choose next.
          </p>
        </div>
        <div
          className="dsr-tools-proof-diagram"
          role="img"
          aria-label="Codex, Claude Code, OpenCode, Gemini, Cursor, and Grok sessions connect through DaemonState."
        >
          <div
            className="dsr-tool-avatars"
            aria-hidden="true"
          >
            {TOOL_NAMES.map((tool) => (
              <span className="dsr-tool-avatar" key={tool} title={tool}>
                <AgentLogo name={tool} />
              </span>
            ))}
          </div>
          <svg
            className="dsr-tools-proof-thread"
            viewBox="0 0 96 44"
            fill="none"
            aria-hidden="true"
          >
            <path d="M3 25C19 25 18 10 34 12C50 14 47 34 64 32C80 30 78 18 93 20" />
            <circle cx="3" cy="25" r="2.5" />
            <circle cx="93" cy="20" r="2.5" />
          </svg>
          <aside className="dsr-tools-context-note" aria-hidden="true">
            <span>DAEMONSTATE / DOCKING LAYER</span>
            <strong>Working state, compiled.</strong>
            <ul>
              <li><i /> Workspace Context</li>
              <li><i /> Session Context</li>
              <li><i /> Next action</li>
            </ul>
          </aside>
        </div>
      </div>
      <div className="dsr-tools-marquee" aria-hidden="true">
        <div className="dsr-tools-track">
          {repeatedTools.map((tool, index) => (
            <div key={`${tool}-${index}`}>
              <span>{tool}</span>
              <i aria-hidden="true" />
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

function ProcessAgentLogo({ name }) {
  if (name === "Codex") {
    return (
      <span className="dsr-process-agent-logo" aria-hidden="true">
        <img src={openaiIcon} alt="" />
      </span>
    );
  }

  if (name === "Claude Code") {
    return (
      <span className="dsr-process-agent-logo is-claude" aria-hidden="true">
        <svg viewBox="0 0 24 24">
          <path d="M13.827 3.52h3.603L24 20h-3.603l-6.57-16.48zm-7.258 0h3.767L16.906 20h-3.674l-1.343-3.461H5.017L3.674 20H0L6.57 3.52zm2.285 5.357-2.07 5.675h4.14l-2.07-5.675z" />
        </svg>
      </span>
    );
  }

  if (name === "Cursor") {
    return (
      <span className="dsr-process-agent-logo" aria-hidden="true">
        <svg viewBox="0 0 24 24">
          <path d="M11.503.131 1.891 5.678a.84.84 0 0 0-.42.726v11.188c0 .3.162.575.42.724l9.609 5.55a1 1 0 0 0 .998 0l9.61-5.55a.84.84 0 0 0 .42-.724V6.404a.84.84 0 0 0-.42-.726L12.497.131a1.01 1.01 0 0 0-.996 0M2.657 6.338h18.55c.263 0 .43.287.297.515L12.23 22.918c-.062.107-.229.064-.229-.06V12.335a.59.59 0 0 0-.295-.51l-9.11-5.257c-.109-.063-.064-.23.061-.23" />
        </svg>
      </span>
    );
  }

  if (name === "OpenCode") {
    return (
      <span className="dsr-process-agent-logo" aria-hidden="true">
        <svg viewBox="0 0 24 30">
          <path d="M18 24H6V12H18V24Z" opacity=".55" />
          <path fillRule="evenodd" d="M18 6H6V24H18V6ZM24 30H0V0H24V30Z" />
        </svg>
      </span>
    );
  }

  return (
    <span className="dsr-process-agent-logo" aria-hidden="true">
      <Sparkles />
    </span>
  );
}

function ProcessDaemonMark({ className = "" }) {
  return (
    <span className={`dsr-process-daemon-mark ${className}`.trim()} aria-hidden="true">
      <DaemonStateIcon size={46} />
    </span>
  );
}

function CaptureProcessStory() {
  return (
    <div className="dsr-process-capture">
      <ul
        className="dsr-process-source-spread"
        aria-label="Four attributed AI-tool session accounts"
      >
        {CAPTURE_SOURCES.map((source) => (
          <li className="dsr-process-source-sheet" key={source.name}>
            <div className="dsr-process-provider-head">
              <ProcessAgentLogo name={source.name} />
              <strong>{source.name}</strong>
            </div>
            <blockquote>“{source.claim}”</blockquote>
          </li>
        ))}
      </ul>

      <div className="dsr-process-convergence" aria-hidden="true">
        <svg viewBox="0 0 640 104" preserveAspectRatio="none" fill="none">
          <path d="M76 0V26L320 74" />
          <path d="M240 0V32L320 74" />
          <path d="M400 0V32L320 74" />
          <path d="M564 0V26L320 74" />
        </svg>
        <ProcessDaemonMark className="dsr-process-central-mark" />
      </div>

      <dl className="dsr-process-state-ribbon" aria-label="Captured working state">
        {CAPTURED_STATE.map(([label, value]) => (
          <div className="dsr-process-state-piece" key={label}>
            <dt>{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

function VerifyProcessStory() {
  return (
    <div className="dsr-process-verify">
      <div className="dsr-process-verify-inputs">
        <article className="dsr-process-evidence-sheet dsr-process-account-sheet">
          <header className="dsr-process-sheet-title">
            <h4>Session account</h4>
            <span
              className="dsr-process-mini-logos"
              role="img"
              aria-label="Codex, Claude Code, Cursor, and OpenCode sessions"
            >
              {HANDOFF_DESTINATIONS.map((name) => (
                <ProcessAgentLogo name={name} key={name} />
              ))}
            </span>
          </header>
          <ol className="dsr-process-claim-list">
            {SESSION_CLAIMS.map((claim, index) => (
              <li key={claim}>
                <span>{String(index + 1).padStart(2, "0")}</span>
                <p>{claim}</p>
              </li>
            ))}
          </ol>
        </article>

        <div className="dsr-process-verify-bridge" aria-hidden="true">
          <ProcessDaemonMark />
        </div>

        <article className="dsr-process-evidence-sheet dsr-process-repo-sheet">
          <header className="dsr-process-sheet-title">
            <h4>Repository now</h4>
            <code>2f91ac7</code>
          </header>
          <ul className="dsr-process-file-list">
            {REPOSITORY_EVIDENCE.map(([marker, source, evidence]) => (
              <li key={source}>
                <span>{marker}</span>
                <p><code>{source}</code><small>{evidence}</small></p>
              </li>
            ))}
          </ul>
        </article>
      </div>

      <ul className="dsr-process-proof" aria-label="Resolved state for the handoff">
        {RESOLVED_STATE.map(([claim, evidence, status, tone]) => (
          <li key={claim}>
            <strong>{claim}</strong>
            <span>{evidence}</span>
            <em className={`is-${tone}`}>{status}</em>
          </li>
        ))}
      </ul>
    </div>
  );
}

function ComposeProcessStory() {
  const [destination, setDestination] = useState("Claude Code");

  return (
    <div className="dsr-process-compose">
      <ul
        className="dsr-process-context-stack"
        aria-label="Workspace Context plus three selected Session Contexts"
      >
        {HANDOFF_CONTEXTS.map(([kind, name, provider]) => (
          <li key={kind}>
            <span className="dsr-process-context-kind">{kind}</span>
            <strong>
              {provider === "DaemonState"
                ? <ProcessDaemonMark />
                : <ProcessAgentLogo name={provider} />}
              {name}
            </strong>
          </li>
        ))}
      </ul>

      <div className="dsr-process-compose-join" aria-hidden="true">
        <ProcessDaemonMark />
      </div>

      <article className="dsr-process-handoff-sheet">
        <h4>Resume the authentication migration</h4>
        <dl>
          {HANDOFF_BRIEF.map(([label, value]) => (
            <div key={label}>
              <dt>{label}</dt>
              <dd>{value}</dd>
            </div>
          ))}
        </dl>
      </article>

      <div className="dsr-process-destinations" aria-label="Choose a destination tool">
        <span className="dsr-process-destination-title">Continue in</span>
        {HANDOFF_DESTINATIONS.map((name) => (
          <button
            type="button"
            aria-pressed={destination === name}
            onClick={() => setDestination(name)}
            key={name}
          >
            <ProcessAgentLogo name={name} />
            <span>{name}</span>
          </button>
        ))}
        <p>
          Copy the reviewed brief
          <span>Use it in any other composer.</span>
        </p>
      </div>
    </div>
  );
}

function ProcessCard({ number, title, type }) {
  const headingId = `process-step-${number}`;

  return (
    <article
      className={`dsr-stack-card dsr-stack-card-${type}`}
      aria-labelledby={headingId}
    >
      <h3 className="dsr-process-heading" id={headingId}>{title}</h3>
      <div className="dsr-process-canvas">
        {type === "capture" && <CaptureProcessStory />}
        {type === "verify" && <VerifyProcessStory />}
        {type === "compose" && <ComposeProcessStory />}
      </div>
    </article>
  );
}

function FeatureCard({ number, title, body, icon: Icon }) {
  return (
    <article className="dsr-feature-card">
      <header>
        <span>/{number}</span>
        <Icon aria-hidden="true" />
      </header>
      <div>
        <h3>{title}</h3>
        <p>{body}</p>
      </div>
      <span className="dsr-feature-arrow" aria-hidden="true">
        <ArrowUpRight />
      </span>
    </article>
  );
}

function AnimatedPhrase({ text, offset = false }) {
  return (
    <span className={`dsr-final-word${offset ? " dsr-final-word-offset" : ""}`}>
      {text.split(" ").map((word, wordIndex) => (
        <span className="dsr-final-phrase-word" key={`${word}-${wordIndex}`}>
          {word.split("").map((letter, letterIndex) => (
            <span
              className="dsr-final-letter"
              key={`${letter}-${wordIndex}-${letterIndex}`}
            >
              {letter}
            </span>
          ))}
        </span>
      ))}
    </span>
  );
}

function LandingFooter({ waitlistOnlyMode }) {
  return (
    <footer className="dsr-footer">
      <div className="dsr-footer-brand">
        <Link to="/" aria-label="DaemonState home">
          <DaemonStateIcon size={34} />
          <span>DaemonState</span>
        </Link>
        <p>Source-backed continuity for coding agents.</p>
      </div>

      <nav aria-label="Footer navigation">
        <div>
          <span>Explore</span>
          <a href="#problem">Why</a>
          <a href="#docking-layer">The layer</a>
          <a href="#how-it-works">How it works</a>
        </div>
        <div>
          <span>Product</span>
          {!waitlistOnlyMode && <Link to="/app">Open product</Link>}
          <a href="#early-access">Join waitlist</a>
          <a href={GITHUB_URL} target="_blank" rel="noreferrer">GitHub</a>
        </div>
        <div>
          <span>Legal</span>
          <Link to="/permissions-terms">Permissions &amp; terms</Link>
          <Link to="/privacy">Privacy notice</Link>
        </div>
      </nav>

      <div className="dsr-footer-bottom">
        <span>© 2026 DaemonState</span>
        <span>Built for source-backed continuity.</span>
      </div>
    </footer>
  );
}
