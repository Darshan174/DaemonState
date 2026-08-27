import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import Landing from "./Landing";
import { ThemeProvider } from "../context/ThemeContext";
import { WAITLIST_CONSENT_VERSION } from "../waitlist/tracking";

const landingReplicaCss = readFileSync(
  resolve(process.cwd(), "src/pages/LandingReplica.css"),
  "utf8",
);

const clerkMock = vi.hoisted(() => ({
  errors: { fields: {} },
  fetchStatus: "idle",
  id: undefined,
  join: vi.fn(),
}));

vi.mock("@clerk/react", () => ({
  useWaitlist: () => ({
    errors: clerkMock.errors,
    fetchStatus: clerkMock.fetchStatus,
    waitlist: {
      id: clerkMock.id,
      join: clerkMock.join,
    },
  }),
}));

function renderLanding({ waitlistOnlyMode = false } = {}) {
  return render(
    <ThemeProvider>
      <MemoryRouter>
        <Landing waitlistOnlyMode={waitlistOnlyMode} />
      </MemoryRouter>
    </ThemeProvider>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
  clerkMock.errors = { fields: {} };
  clerkMock.fetchStatus = "idle";
  clerkMock.id = undefined;
  clerkMock.join.mockReset();
});

describe("Landing", () => {
  it("leads with the docking-layer category and working calls to action", () => {
    const { container } = renderLanding();

    expect(
      screen.getByRole("heading", {
        name: "The docking layer for AI agents.",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/keeps your project context alive across/i),
    ).toBeInTheDocument();
    expect(screen.getByText("Self-hosted. Source-backed. User-reviewed."))
      .toBeInTheDocument();
    expect(container.querySelector(".daemonstate-landing")).toHaveAttribute(
      "data-landing-theme",
      "fixed",
    );

    screen.getAllByRole("link", { name: /Join (the early-access )?waitlist/i })
      .forEach((link) => expect(link).toHaveAttribute("href", "#early-access"));
    expect(screen.getByRole("link", { name: "See how it works" })).toHaveAttribute(
      "href",
      "#how-it-works",
    );
    expect(screen.getByRole("textbox", { name: "Email address" })).toHaveAttribute(
      "type",
      "email",
    );
    expect(screen.getByRole("button", { name: "Join waitlist" })).toBeInTheDocument();
    const privacyLinks = screen.getAllByRole("link", { name: "Privacy notice" });
    expect(privacyLinks.some((link) => link.getAttribute("href") === "/privacy"))
      .toBe(true);
    expect(privacyLinks.some((link) => link.getAttribute("target") === "_blank"))
      .toBe(true);
    expect(screen.getByRole("link", { name: "Permissions & terms" }))
      .toHaveAttribute("href", "/permissions-terms");
  });

  it("explains the blind start and source-backed handoff loop", () => {
    const { container } = renderLanding();

    expect(
      screen.getByRole("heading", { name: "Every new agent starts partially blind." }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Start from captured work, not a reconstructed prompt."),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", {
        name: "Turn scattered sessions into trusted context.",
      }),
    ).toBeInTheDocument();
    expect(screen.getByText("The handoff loop")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Capture what each agent learned, check it against the code, and continue in any tool.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Capture the working trail." }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Verify it against the code." }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Compose the next handoff." }),
    ).toBeInTheDocument();

    const [captureCard, verifyCard, composeCard] = container.querySelectorAll(
      ".dsr-stack-card",
    );

    ["Codex", "Claude Code", "Cursor", "OpenCode"].forEach((tool) => {
      expect(within(captureCard).getByText(tool)).toBeInTheDocument();
    });
    ["Goal", "Decision", "Failed path", "Next"].forEach((field) => {
      expect(within(captureCard).getByText(field)).toBeInTheDocument();
    });

    expect(within(verifyCard).getByRole("heading", { name: "Session account" }))
      .toBeInTheDocument();
    expect(within(verifyCard).getByRole("heading", { name: "Repository now" }))
      .toBeInTheDocument();
    ["Verified", "Unverified", "Task-local"].forEach((status) => {
      expect(within(verifyCard).getByText(status)).toBeInTheDocument();
    });

    expect(within(composeCard).getByText("Workspace Context")).toBeInTheDocument();
    expect(
      within(composeCard).getByRole("heading", {
        name: "Resume the authentication migration",
      }),
    ).toBeInTheDocument();
    expect(within(composeCard).getByRole("button", { name: "Claude Code" }))
      .toHaveAttribute("aria-pressed", "true");

    expect(screen.getAllByText("Codex").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Claude Code").length).toBeGreaterThan(0);
    expect(screen.getAllByText("OpenCode").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Gemini").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Cursor").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Grok").length).toBeGreaterThan(0);
    expect(screen.queryByText("Any agent")).not.toBeInTheDocument();
    expect(screen.queryByText(/Trusted by/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/10,000/i)).not.toBeInTheDocument();
  });

  it("rotates supported agent names every second in the requested order", () => {
    vi.useFakeTimers();
    const { container, unmount } = renderLanding();
    const provider = container.querySelector(".dsr-provider-rotator");

    expect(provider).toHaveAttribute(
      "aria-label",
      "Codex, Claude Code, OpenCode, Cursor, Gemini, or Grok",
    );
    expect(provider).toHaveTextContent("Codex");

    ["Claude Code", "OpenCode", "Cursor", "Gemini", "Grok", "Codex"].forEach(
      (name) => {
        act(() => vi.advanceTimersByTime(1000));
        expect(provider).toHaveTextContent(name);
      },
    );

    unmount();
    vi.useRealTimers();
  });

  it("keeps cursor swiping and keyboard navigation usable with reduced motion", async () => {
    vi.stubGlobal("matchMedia", vi.fn().mockReturnValue({
      matches: true,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }));
    const { container } = renderLanding();
    const heroDeck = container.querySelector(".dsr-deck-stage");
    const deckWindow = heroDeck.querySelector(".dsr-deck-window");
    const deckCards = [...heroDeck.querySelectorAll(".dsr-deck-card")];
    Object.defineProperty(deckCards[0], "offsetHeight", {
      configurable: true,
      value: 340,
    });

    await waitFor(() => expect(heroDeck).toHaveAttribute("data-autoplay", "paused"));
    expect(deckCards[0]).toHaveClass("is-active");
    expect(deckCards[0]).toHaveAttribute("aria-hidden", "false");
    expect(deckCards.slice(1).every(
      (card) => card.getAttribute("aria-hidden") === "true",
    )).toBe(true);
    fireEvent(deckWindow, new MouseEvent("pointerdown", {
      bubbles: true,
      button: 0,
      clientY: 260,
    }));
    fireEvent(deckWindow, new MouseEvent("pointermove", {
      bubbles: true,
      cancelable: true,
      clientY: 180,
    }));
    fireEvent(deckWindow, new MouseEvent("pointerup", {
      bubbles: true,
      clientY: 180,
    }));

    expect(heroDeck.querySelector("[data-deck-status]")).toHaveTextContent(
      "Showing card 2 of 5.",
    );
    expect(deckCards[1]).toHaveClass("is-active");
    expect(deckCards[1]).toHaveAttribute("aria-hidden", "false");
    expect(deckCards[0]).toHaveAttribute("data-deck-position", "previous");
    expect(deckCards[2]).toHaveAttribute("data-deck-position", "next");
    expect(deckWindow).not.toHaveClass("is-dragging");

    fireEvent.keyDown(heroDeck, { key: "ArrowDown" });
    expect(heroDeck.querySelector("[data-deck-status]")).toHaveTextContent(
      "Showing card 3 of 5.",
    );
  });

  it("keeps drag listeners without registering cursor-follow tilt", async () => {
    vi.stubGlobal("matchMedia", vi.fn().mockReturnValue({
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }));
    vi.stubGlobal("scrollTo", vi.fn());
    const addEventListener = vi.spyOn(EventTarget.prototype, "addEventListener");

    try {
      const { container } = renderLanding();
      const landing = container.querySelector(".dsr-landing");

      await waitFor(() => expect(landing).toHaveAttribute("data-motion", "ready"));

      const hero = container.querySelector(".dsr-hero");
      const deckWindow = container.querySelector(".dsr-deck-window");
      const eventTypesFor = (element) => addEventListener.mock.calls
        .filter((_, index) => addEventListener.mock.instances[index] === element)
        .map(([eventType]) => eventType);

      expect(eventTypesFor(hero)).not.toContain("pointermove");
      expect(eventTypesFor(hero)).not.toContain("pointerleave");
      expect(eventTypesFor(deckWindow)).not.toContain("mouseenter");
      expect(eventTypesFor(deckWindow)).not.toContain("mouseleave");
      expect(eventTypesFor(deckWindow)).toEqual(expect.arrayContaining([
        "pointerdown",
        "pointermove",
        "pointerup",
      ]));
    } finally {
      addEventListener.mockRestore();
    }
  });

  it("moves directly from the product story into the final call to action", () => {
    const { container } = renderLanding();

    expect(container.querySelector("#project-memory")).not.toBeInTheDocument();
    expect(container.querySelector(".dsr-features")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "Not chat history. Working state." }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "Two contexts. One project." }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "The agents change. The project remembers." }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("contentinfo").querySelector(".dsr-footer-brand svg"),
    ).toHaveAttribute("width", "68");
    expect(screen.getByRole("link", { name: "Follow the build" })).toHaveAttribute(
      "href",
      "https://github.com/Darshan174/DaemonState",
    );
    expect(
      within(screen.getByRole("contentinfo")).getByRole("link", { name: "GitHub" }),
    ).toHaveAttribute("href", "https://github.com/Darshan174/DaemonState");
  });

  it("reserves vertical touch gestures for the card carousel", () => {
    const deckWindowRule = landingReplicaCss.match(
      /\.dsr-deck-window\s*\{([^}]*)\}/,
    )?.[1];
    const deckTrackRule = landingReplicaCss.match(
      /\.dsr-deck-track\s*\{([^}]*)\}/,
    )?.[1];

    expect(deckWindowRule).toMatch(/touch-action:\s*pan-x pinch-zoom\s*;/);
    expect(deckTrackRule).toMatch(/touch-action:\s*pan-x pinch-zoom\s*;/);
  });

  it("keeps obvious product entry points in local product mode", () => {
    const { container } = renderLanding();
    const mainNavigation = screen.getByRole("navigation", {
      name: "Main navigation",
    });

    expect(container.querySelector(".dsr-landing")).toBeInTheDocument();
    expect(container.querySelectorAll(".dsr-deck-card")).toHaveLength(5);
    expect(container.querySelector(".dsr-deck-track")).toBeInTheDocument();
    const heroDeck = container.querySelector(".dsr-deck-stage");
    expect(heroDeck).toHaveAttribute(
      "data-autoplay",
      "playing",
    );
    expect(heroDeck).toHaveAttribute("data-autoplay-delay", "3200");
    expect(heroDeck).toHaveAttribute("aria-roledescription", "carousel");
    expect(within(heroDeck).queryByRole("button", { name: "Show previous card" }))
      .not.toBeInTheDocument();
    expect(within(heroDeck).queryByRole("button", { name: "Show next card" }))
      .not.toBeInTheDocument();
    expect(heroDeck.querySelectorAll(".dsr-deck-controls")).toHaveLength(0);
    expect(heroDeck.querySelectorAll("[data-deck-index]")).toHaveLength(0);
    expect(within(heroDeck).getByText(/Drag or swipe the cards vertically/i))
      .toBeInTheDocument();
    expect(heroDeck.querySelector(".dsr-deck-index")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Scroll to learn more" }))
      .not.toBeInTheDocument();
    expect(heroDeck.querySelectorAll(".dsr-deck-card > header")).toHaveLength(0);
    expect(within(heroDeck).queryByText("Session library")).not.toBeInTheDocument();
    expect(within(heroDeck).queryByText("Decisions + evidence")).not.toBeInTheDocument();
    expect(heroDeck.querySelectorAll(".dsr-session-row")).toHaveLength(5);
    expect(heroDeck.querySelectorAll(".dsr-window-track > span")).toHaveLength(10);
    expect(heroDeck.querySelector(".dsr-chat-window")).toBeInTheDocument();
    expect(heroDeck.querySelector(".dsr-price-change")).toHaveTextContent(
      "Pricing changed",
    );
    expect(heroDeck.querySelectorAll(".dsr-history-steps > div")).toHaveLength(4);
    expect(screen.queryByText("Cards advance automatically")).not.toBeInTheDocument();
    expect(screen.queryByText(/Drag to explore/i)).not.toBeInTheDocument();
    expect(container.querySelector(".dsr-system-frame")).not.toBeInTheDocument();
    expect(container.querySelectorAll(".dsr-stack-card")).toHaveLength(3);
    expect(container.querySelectorAll(".dsr-agent-logo")).toHaveLength(6);
    expect(container.querySelectorAll(".dsr-tool-avatar")).toHaveLength(6);
    expect(container.querySelectorAll(".dsr-agent-logo-gemini")).toHaveLength(1);
    expect(container.querySelectorAll(".dsr-agent-logo-cursor")).toHaveLength(1);
    expect(container.querySelectorAll(".dsr-agent-logo-grok")).toHaveLength(1);
    expect(container.querySelectorAll(".dsr-agent-logo-any")).toHaveLength(0);
    expect(container.querySelectorAll(".dsr-tools-track > .is-any-agent")).toHaveLength(0);
    expect(
      screen.getByRole("heading", { name: "One project. Many sessions." }),
    ).toBeInTheDocument();
    expect(screen.getByText("Working state, compiled.")).toBeInTheDocument();
    expect(screen.queryByText("COMPATIBILITY / ONE MEMORY")).not.toBeInTheDocument();
    expect(screen.queryByText(/SHARED MEMORY/i)).not.toBeInTheDocument();
    expect(screen.queryByText("CONTEXT CORE")).not.toBeInTheDocument();
    expect(mainNavigation).not.toHaveTextContent("01");
    expect(mainNavigation).not.toHaveTextContent("02");
    expect(mainNavigation).not.toHaveTextContent("03");

    expect(container.querySelector("#problem")).toBeInTheDocument();
    expect(container.querySelector("#docking-layer")).toBeInTheDocument();
    expect(container.querySelector("#how-it-works")).toBeInTheDocument();
    expect(container.querySelector("#project-memory")).not.toBeInTheDocument();
    expect(container.querySelector("#early-access")).toBeInTheDocument();

    const productLinks = screen.getAllByRole("link", { name: "Open product" });
    expect(productLinks.length).toBeGreaterThanOrEqual(2);
    productLinks.forEach((link) => expect(link).toHaveAttribute("href", "/app"));
    expect(container.querySelector(".dsr-hero-primary-link")).not.toBeInTheDocument();
    screen.getAllByRole("link", { name: /Join (the early-access )?waitlist/i })
      .forEach((link) => expect(link).toHaveAttribute("href", "#early-access"));
  });

  it("removes every product entry point in public waitlist mode", () => {
    const { container } = renderLanding({ waitlistOnlyMode: true });

    expect(container.querySelector('a[href="/app"]')).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Open product" })).not.toBeInTheDocument();
    expect(container.querySelector(".dsr-hero-primary-link")).not.toBeInTheDocument();
    screen.getAllByRole("link", { name: /Join (the early-access )?waitlist/i })
      .forEach((link) => expect(link).toHaveAttribute("href", "#early-access"));
  });

  it("uses Clerk's managed waitlist when its publishable key is configured", async () => {
    vi.stubEnv("VITE_CLERK_PUBLISHABLE_KEY", "pk_test_daemonstate");
    clerkMock.join.mockResolvedValue({ error: null });
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const { container } = renderLanding();

    expect(container.querySelector(".dsr-waitlist-card"))
      .toHaveAttribute("data-waitlist-provider", "clerk");
    expect(screen.getByText(/account invitations managed by Clerk/i))
      .toBeInTheDocument();

    fireEvent.change(screen.getByRole("textbox", { name: "Email address" }), {
      target: { value: "Builder@Example.com" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Join waitlist" }));

    await waitFor(() => {
      expect(clerkMock.join).toHaveBeenCalledWith({
        emailAddress: "Builder@Example.com",
      });
    });
    expect(fetchMock).not.toHaveBeenCalled();
    expect(await screen.findByText(/check your inbox for confirmation/i))
      .toBeInTheDocument();
    expect(screen.getByRole("button", { name: "You're in" })).toBeDisabled();
  });

  it("registers an email without leaving the landing page", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 201,
      json: async () => ({
        status: "registered",
        message: "You're on the DaemonState waitlist.",
      }),
    });
    vi.stubGlobal("fetch", fetchMock);
    renderLanding();

    fireEvent.change(screen.getByRole("textbox", { name: "Email address" }), {
      target: { value: "Builder@Example.com" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Join waitlist" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/waitlist",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({
            email: "Builder@Example.com",
            website: "",
            referrer: null,
            utm_source: null,
            utm_medium: null,
            utm_campaign: null,
            utm_term: null,
            utm_content: null,
            consent_version: WAITLIST_CONSENT_VERSION,
          }),
        }),
      );
    });
    expect(await screen.findByText("You're on the DaemonState waitlist."))
      .toBeInTheDocument();
    expect(screen.getByRole("button", { name: "You're in" })).toBeDisabled();
  });
});
