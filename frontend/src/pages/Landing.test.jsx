import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import Landing from "./Landing";
import { ThemeProvider } from "../context/ThemeContext";
import { WAITLIST_CONSENT_VERSION } from "../waitlist/tracking";

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
});

describe("Landing", () => {
  it("leads with the persistent-context promise and working calls to action", () => {
    const { container } = renderLanding();

    expect(
      screen.getByRole("heading", {
        name: "Your AI coding work shouldn’t reset every session.",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/keeps your project context alive across Codex, Claude Code/i),
    ).toBeInTheDocument();
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

  it("explains the recovery loop across supported coding agents", () => {
    renderLanding();

    expect(
      screen.getByRole("heading", { name: "Stop rebuilding context." }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("No re-explaining. No rediscovery. No starting over."),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", {
        name: "One project. Every agent. Continuous context.",
      }),
    ).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Import your sessions" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Recover what matters" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Continue anywhere" })).toBeInTheDocument();

    expect(screen.getAllByText("Codex").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Claude Code").length).toBeGreaterThan(0);
    expect(screen.getAllByText("OpenCode").length).toBeGreaterThan(0);
    expect(screen.queryByText(/Trusted by/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/10,000/i)).not.toBeInTheDocument();
  });

  it("positions project history as usable infrastructure without invented proof", () => {
    renderLanding();

    expect(
      screen.getByRole("heading", {
        name: "Your coding history becomes infrastructure.",
      }),
    ).toBeInTheDocument();
    expect(screen.getByText("Not another chat archive.")).toBeInTheDocument();

    [
      "What you are building",
      "What has already been completed",
      "Which decisions were made",
      "What failed and why",
      "Which files matter",
      "What needs to happen next",
    ].forEach((item) => expect(screen.getByText(item)).toBeInTheDocument());

    expect(
      screen.getByRole("heading", { name: "Change the model. Not the momentum." }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Follow the build" })).toHaveAttribute(
      "href",
      "https://github.com/Darshan174/DaemonState",
    );
  });

  it("keeps obvious product entry points in local product mode", () => {
    const { container } = renderLanding();
    const mainNavigation = screen.getByRole("navigation", {
      name: "Main navigation",
    });

    expect(container.querySelector(".dsr-landing")).toBeInTheDocument();
    expect(container.querySelectorAll(".dsr-deck-card")).toHaveLength(5);
    expect(container.querySelector(".dsr-deck-track")).toBeInTheDocument();
    expect(container.querySelector(".dsr-deck-window")).toHaveAttribute(
      "data-autoplay",
      "playing",
    );
    expect(screen.queryByText("Cards advance automatically")).not.toBeInTheDocument();
    expect(screen.queryByText(/Drag to explore/i)).not.toBeInTheDocument();
    expect(container.querySelector(".dsr-system-frame")).toBeInTheDocument();
    expect(container.querySelectorAll(".dsr-stack-card")).toHaveLength(3);
    expect(container.querySelectorAll(".dsr-agent-logo")).toHaveLength(11);
    expect(container.querySelectorAll(".dsr-tool-avatar")).toHaveLength(4);
    expect(container.querySelector(".dsr-agent-logo-any")).not.toBeInTheDocument();
    expect(container.querySelectorAll(".dsr-graph-connectors path")).toHaveLength(3);
    expect(container.querySelectorAll(".dsr-tools-track > .is-any-agent")).toHaveLength(2);
    expect(
      screen.getByRole("heading", { name: "Switch tools. Keep the thread." }),
    ).toBeInTheDocument();
    expect(screen.getByText("comes with you.")).toBeInTheDocument();
    expect(screen.getByText("Provider-neutral handoff")).toBeInTheDocument();
    expect(screen.queryByText("COMPATIBILITY / ONE MEMORY")).not.toBeInTheDocument();
    expect(screen.queryByText(/SHARED MEMORY/i)).not.toBeInTheDocument();
    expect(screen.queryByText("CONTEXT CORE")).not.toBeInTheDocument();
    expect(mainNavigation).not.toHaveTextContent("01");
    expect(mainNavigation).not.toHaveTextContent("02");
    expect(mainNavigation).not.toHaveTextContent("03");

    expect(container.querySelector("#problem")).toBeInTheDocument();
    expect(container.querySelector("#how-it-works")).toBeInTheDocument();
    expect(container.querySelector("#project-memory")).toBeInTheDocument();
    expect(container.querySelector("#early-access")).toBeInTheDocument();

    const productLinks = screen.getAllByRole("link", { name: "Open product" });
    expect(productLinks.length).toBeGreaterThanOrEqual(2);
    productLinks.forEach((link) => expect(link).toHaveAttribute("href", "/app"));
    screen.getAllByRole("link", { name: /Join (the early-access )?waitlist/i })
      .forEach((link) => expect(link).toHaveAttribute("href", "#early-access"));
  });

  it("removes every product entry point in public waitlist mode", () => {
    const { container } = renderLanding({ waitlistOnlyMode: true });

    expect(container.querySelector('a[href="/app"]')).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Open product" })).not.toBeInTheDocument();
    screen.getAllByRole("link", { name: /Join (the early-access )?waitlist/i })
      .forEach((link) => expect(link).toHaveAttribute("href", "#early-access"));
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
