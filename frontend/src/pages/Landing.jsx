import { useEffect, useRef, useState } from "react";
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
  History,
  Layers3,
  Menu,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  Terminal,
  Waypoints,
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

const TOOL_NAMES = ["Codex", "Claude Code", "OpenCode", "Cursor", "Any agent"];

const MEMORY_ITEMS = [
  "What you are building",
  "What has already been completed",
  "Which decisions were made",
  "What failed and why",
  "Which files matter",
  "What needs to happen next",
];

const DECK_CARDS = [
  {
    number: "01",
    eyebrow: "Session history",
    title: "Every session, finally in one place.",
    type: "sessions",
  },
  {
    number: "02",
    eyebrow: "Decision graph",
    title: "The reasoning survives the chat window.",
    type: "graph",
  },
  {
    number: "03",
    eyebrow: "Persistent memory",
    title: "Project context stays alive.",
    type: "memory",
  },
  {
    number: "04",
    eyebrow: "Clean handoff",
    title: "The next agent starts up to speed.",
    type: "handoff",
  },
  {
    number: "05",
    eyebrow: "Continuous work",
    title: "Change the model. Keep the momentum.",
    type: "continuity",
  },
];

const PROCESS_STEPS = [
  {
    number: "01",
    title: "Import your sessions",
    body: "Bring together work from Codex, Claude Code, OpenCode, and the coding agents you use next.",
    icon: Layers3,
    tone: "lime",
    meta: "SESSIONS / CONNECTED",
  },
  {
    number: "02",
    title: "Recover what matters",
    body: "DaemonState extracts decisions, progress, failures, files, blockers, and the work that remains.",
    icon: Waypoints,
    tone: "blue",
    meta: "CONTEXT / RECONCILED",
  },
  {
    number: "03",
    title: "Continue anywhere",
    body: "Generate a clean handoff and continue in another session, model, or coding harness without starting over.",
    icon: RefreshCw,
    tone: "coral",
    meta: "HANDOFF / READY",
  },
];

const FEATURE_CARDS = [
  {
    number: "01",
    title: "Decisions, not transcripts",
    body: "Recover the choices that shaped the project and the evidence behind them.",
    icon: Fingerprint,
  },
  {
    number: "02",
    title: "Failures stay useful",
    body: "Keep dead ends visible so the next session does not repeat expensive mistakes.",
    icon: ShieldCheck,
  },
  {
    number: "03",
    title: "Files stay connected",
    body: "Carry forward the repository paths, commands, and open loops that matter now.",
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

        gsap.timeline({
          scrollTrigger: {
            trigger: ".dsr-system-reveal",
            start: "top 82%",
            end: "bottom 42%",
            scrub: 1,
          },
        })
          .from(".dsr-system-frame", {
            y: 130,
            scale: 0.86,
            borderRadius: 44,
            ease: "none",
          })
          .from(
            ".dsr-system-sidebar",
            { xPercent: -72, autoAlpha: 0, ease: "none" },
            0.08,
          )
          .from(
            ".dsr-system-inspector",
            { xPercent: 72, autoAlpha: 0, ease: "none" },
            0.08,
          )
          .from(
            ".dsr-system-memory-card",
            {
              y: 90,
              autoAlpha: 0,
              stagger: 0.08,
              ease: "none",
            },
            0.18,
          );

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

        gsap.timeline({
          scrollTrigger: {
            trigger: ".dsr-memory-title",
            start: "top 88%",
            end: "top 28%",
            scrub: 1,
          },
        })
          .from(".dsr-memory-title-line span", {
            yPercent: 110,
            stagger: 0.1,
            ease: "none",
          });

        gsap.timeline({
          scrollTrigger: {
            trigger: ".dsr-memory-layout",
            start: "top 88%",
            end: "top 30%",
            scrub: 1,
          },
        })
          .from(
            ".dsr-memory-console",
            { y: 130, rotateX: 12, autoAlpha: 0, ease: "none" },
            0,
          )
          .from(
            ".dsr-memory-list li",
            { x: -32, autoAlpha: 0, stagger: 0.05, ease: "none" },
            0,
          );

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
        <span>Persistent context for every session</span>
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
            aria-label="Your AI coding work shouldn’t reset every session."
          >
            <span className="dsr-hero-heading-left">Your AI coding work</span>
            <span className="dsr-hero-heading-right">
              shouldn’t reset every session.
            </span>
          </h1>

          <HeroDeck />

          <div className="dsr-hero-support">
            <p>
              DaemonState keeps your project context alive across Codex, Claude
              Code, OpenCode, and every session in between.
            </p>
            <p>
              Switch tools. Start fresh sessions. Continue exactly where you
              left off.
            </p>
            <div className="dsr-hero-links">
              {waitlistOnlyMode ? (
                <a href="#early-access" className="dsr-hero-primary-link">
                  Join the waitlist
                  <ArrowRight aria-hidden="true" />
                </a>
              ) : (
                <Link to="/app" className="dsr-hero-primary-link">
                  Open product
                  <ArrowRight aria-hidden="true" />
                </Link>
              )}
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
            <SectionMarker label="The context gap" number="01" />
            <h2>Stop rebuilding context.</h2>
            <p className="dsr-problem-statement">
              {splitWords(
                "Your decisions, failed attempts, relevant files, blockers, commands, and next steps should not disappear when a session ends.",
              )}
            </p>
            <div className="dsr-problem-foot">
              <p>
                DaemonState turns fragmented coding sessions into context your
                next agent can immediately use.
              </p>
              <strong>
                No re-explaining. No rediscovery. No starting over.
              </strong>
            </div>
          </div>

          <div className="dsr-system-reveal">
            <SystemFrame />
          </div>
        </section>

        <ToolsBand />

        <section id="how-it-works" className="dsr-stack">
          <div className="dsr-stack-sticky">
            <div className="dsr-section-shell dsr-stack-heading">
              <SectionMarker label="How it works" number="02" />
              <h2>One project. Every agent. Continuous context.</h2>
              <p>Three steps. One uninterrupted line of work.</p>
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
              <SectionMarker label="What survives" number="03" dark />
              <h2 id="features-heading">
                Keep the useful parts. Leave the noise behind.
              </h2>
            </div>
            <div className="dsr-features-grid">
              {FEATURE_CARDS.map((feature) => (
                <FeatureCard key={feature.number} {...feature} />
              ))}
            </div>
          </div>
        </section>

        <section id="project-memory" className="dsr-memory">
          <div className="dsr-section-shell">
            <SectionMarker label="Persistent project memory" number="04" />
            <h2
              className="dsr-memory-title"
              aria-label="Your coding history becomes infrastructure."
            >
              <span className="dsr-memory-title-line">
                <span>Your coding history</span>
              </span>
              <span className="dsr-memory-title-line dsr-memory-title-right">
                <span>becomes infrastructure.</span>
              </span>
            </h2>
            <p className="dsr-memory-not-archive">Not another chat archive.</p>

            <div className="dsr-memory-layout">
              <div className="dsr-memory-copy">
                <p>
                  DaemonState gives every new coding session a current, usable
                  understanding of:
                </p>
                <ul className="dsr-memory-list">
                  {MEMORY_ITEMS.map((item) => (
                    <li key={item}>
                      <Check aria-hidden="true" />
                      <span>{item}</span>
                    </li>
                  ))}
                </ul>
              </div>
              <MemoryConsole />
            </div>
          </div>
        </section>

        <section id="early-access" className="dsr-final">
          <div className="dsr-final-topline">
            <span>Persistent context for AI coding agents</span>
            <span>Early access / 2026</span>
          </div>

          <div className="dsr-final-copy">
            <p>Use the right AI tool for the job without losing what came before.</p>
            <h2 aria-label="Change the model. Not the momentum.">
              <AnimatedPhrase text="Change the model." />
              <AnimatedPhrase text="Not the momentum." offset />
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
        <h3>Be first in line.</h3>
        <p>
          Join builders who want every AI coding session to start with the
          context it needs.
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
    { href: "#how-it-works", label: "Method" },
    { href: "#project-memory", label: "Memory" },
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
          <span><CircleDot /> HANDOFF READY</span>
          <strong>Continue provider adapter work</strong>
          <small>Decisions restored · Blocker surfaced · Next action clear</small>
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
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="M22 24H2V0h20zM17 4.8H7v14.4h10z" />
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

  return (
    <span className="dsr-agent-logo dsr-agent-logo-any" title="Any agent">
      <Sparkles aria-hidden="true" />
    </span>
  );
}

function SystemFrame() {
  return (
    <div className="dsr-system-frame" aria-label="DaemonState project memory preview">
      <div className="dsr-system-chrome">
        <div>
          <span />
          <span />
          <span />
        </div>
        <p>PROJECT / DAEMONSTATE</p>
        <small><i /> CONTEXT LIVE</small>
      </div>

      <aside className="dsr-system-sidebar">
        <DaemonStateIcon size={34} />
        <nav aria-label="Preview navigation">
          <span className="is-active"><Layers3 /> Continue</span>
          <span><History /> Sessions</span>
          <span><Waypoints /> Evidence</span>
          <span><Database /> Sources</span>
        </nav>
        <small>23 SESSIONS INDEXED</small>
      </aside>

      <div className="dsr-system-main">
        <div className="dsr-system-main-heading">
          <div>
            <small>READY TO CONTINUE</small>
            <h3>Resume the work,<br />not the explanation.</h3>
          </div>
          <span>DEMO / CURRENT STATE</span>
        </div>

        <div className="dsr-system-memory-grid">
          <article className="dsr-system-memory-card is-wide">
            <header><span>Current objective</span><small>ACTIVE</small></header>
            <h4>Ship provider-neutral continuation</h4>
            <p>Keep approval in the foreground while adapters share one contract.</p>
          </article>
          <article className="dsr-system-memory-card">
            <header><span>Decisions</span><small>14</small></header>
            <strong>One adapter contract</strong>
            <p>Chosen in session 22</p>
          </article>
          <article className="dsr-system-memory-card">
            <header><span>Failed path</span><small>03</small></header>
            <strong>Background delivery</strong>
            <p>Loses foreground approval</p>
          </article>
          <article className="dsr-system-memory-card is-command">
            <Terminal />
            <code>pytest tests/test_harness.py</code>
            <span>READY</span>
          </article>
        </div>
      </div>

      <aside className="dsr-system-inspector">
        <header>
          <span>Next session</span>
          <CircleDot />
        </header>
        <div className="dsr-inspector-score">
          <strong>100%</strong>
          <span>HANDOFF READY</span>
        </div>
        <ul>
          <li><Check /> Decisions restored</li>
          <li><Check /> Blocker surfaced</li>
          <li><Check /> Files attached</li>
          <li><Check /> Next action clear</li>
        </ul>
        <button type="button" tabIndex={-1}>
          Open in any agent
          <ArrowRight />
        </button>
      </aside>
    </div>
  );
}

function ToolsBand() {
  const repeatedTools = [...TOOL_NAMES, ...TOOL_NAMES];

  return (
    <section className="dsr-tools" aria-label="Works across AI coding agents">
      <div className="dsr-tools-proof">
        <span className="dsr-tools-proof-kicker">COMPATIBILITY / ONE MEMORY</span>
        <div className="dsr-tools-proof-diagram">
          <div
            className="dsr-tool-avatars"
            aria-label="Codex, Claude Code, OpenCode, Cursor, and any agent"
          >
            {TOOL_NAMES.map((tool) => (
              <span className="dsr-tool-avatar" key={tool} title={tool}>
                <AgentLogo name={tool} />
              </span>
            ))}
          </div>
          <span className="dsr-tools-proof-line" aria-hidden="true" />
          <div className="dsr-tools-proof-core">
            <Layers3 aria-hidden="true" />
            <span>SHARED<br />MEMORY</span>
          </div>
        </div>
        <p>
          <strong>Your agents, in sync.</strong>
          <span>Switch tools without resetting the work.</span>
        </p>
      </div>
      <div className="dsr-tools-marquee">
        <div className="dsr-tools-track">
          {repeatedTools.map((tool, index) => (
            <div
              className={tool === "Any agent" ? "is-any-agent" : undefined}
              key={`${tool}-${index}`}
            >
              <span>{tool}</span>
              <i aria-hidden="true" />
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

function ProcessCard({ number, title, body, icon: Icon, tone, meta }) {
  return (
    <article className={`dsr-stack-card dsr-stack-card-${tone}`}>
      <header>
        <span>STEP / {number}</span>
        <Icon aria-hidden="true" />
      </header>
      <div className="dsr-stack-card-copy">
        <h3>{title}</h3>
        <p>{body}</p>
      </div>
      <div className="dsr-stack-card-visual" aria-hidden="true">
        <span>{meta}</span>
        <div>
          <i />
          <i />
          <i />
          <b><DaemonStateIcon size={46} /></b>
        </div>
      </div>
      <small>{number} / 03</small>
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

function MemoryConsole() {
  return (
    <div className="dsr-memory-console" aria-label="Persistent project memory architecture">
      <header>
        <span><Code2 /> PROJECT MEMORY</span>
        <span className="dsr-memory-live"><i /> LIVE</span>
      </header>

      <div className="dsr-memory-console-body">
        <div className="dsr-memory-inputs">
          <span><History /> Session history</span>
          <span><Code2 /> Repository state</span>
          <span><Database /> Decisions + evidence</span>
        </div>
        <div className="dsr-memory-flow" aria-hidden="true">
          <i /><i /><i />
        </div>
        <div className="dsr-memory-core">
          <span><DaemonStateIcon size={58} /></span>
          <small>DAEMONSTATE</small>
          <strong>CONTEXT CORE</strong>
          <p>Continuously reconciled</p>
        </div>
        <div className="dsr-memory-output-line" aria-hidden="true" />
        <div className="dsr-memory-output">
          <Sparkles aria-hidden="true" />
          <div>
            <span>NEXT AGENT</span>
            <strong>Already up to speed.</strong>
          </div>
          <ArrowRight aria-hidden="true" />
        </div>
      </div>

      <footer>
        <span>State integrity</span>
        <div><i /></div>
        <strong>VERIFIED / DEMO</strong>
      </footer>
    </div>
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
        <p>Persistent project context for every coding agent.</p>
      </div>

      <nav aria-label="Footer navigation">
        <div>
          <span>Explore</span>
          <a href="#problem">Why</a>
          <a href="#how-it-works">How it works</a>
          <a href="#project-memory">Project memory</a>
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
        <span>Built for uninterrupted work.</span>
      </div>
    </footer>
  );
}
