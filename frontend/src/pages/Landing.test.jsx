import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import Landing from "./Landing";
import { ThemeProvider } from "../context/ThemeContext";

function renderLanding() {
  return render(
    <ThemeProvider>
      <MemoryRouter>
        <Landing />
      </MemoryRouter>
    </ThemeProvider>,
  );
}

describe("Landing", () => {
  it("mirrors the current product surfaces and removes retired navigation", () => {
    const { container } = renderLanding();

    expect(
      screen.getByRole("heading", { name: "Continue the work. Not the explanation." }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Source-available continuity for coding agents"),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Open-source continuity/i)).not.toBeInTheDocument();
    expect(container.querySelector(".daemonstate-landing")).toHaveAttribute(
      "data-landing-theme",
      "fixed",
    );

    const openContinueLinks = screen.getAllByRole("link", { name: "Open Continue" });
    expect(openContinueLinks).toHaveLength(2);
    openContinueLinks.forEach((link) => expect(link).toHaveAttribute("href", "/app"));
    expect(screen.getByRole("link", { name: "See how it works" })).toHaveAttribute(
      "href",
      "#how-it-works",
    );

    const productDestinations = [
      ["Open Execute", "/app/execute"],
      ["Browse sessions", "/app/library"],
      ["Trace the evidence", "/app/explain"],
      ["Review sources", "/app/sources"],
      ["Manage integrations", "/app/connectors"],
    ];
    productDestinations.forEach(([name, href]) => {
      expect(screen.getByRole("link", { name })).toHaveAttribute("href", href);
    });

    expect(screen.queryByText("Runs")).not.toBeInTheDocument();
    expect(screen.queryByText("Run history")).not.toBeInTheDocument();
    expect(container.querySelectorAll('a[href="/app/memory"]')).toHaveLength(0);
    expect(screen.queryByRole("textbox", { name: /search/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/Trusted by/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/10,000/i)).not.toBeInTheDocument();
  });

  it("keeps Project Context and Session Context separate and qualifies delivery support", () => {
    renderLanding();

    expect(screen.getAllByText("Project Context").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Current Session Context").length).toBeGreaterThan(0);
    expect(screen.getByText("Durable workspace parent")).toBeInTheDocument();
    expect(screen.getByText("Task-specific checkpoint")).toBeInTheDocument();
    expect(
      screen.getByText(/Failed attempts and transient blockers stay in Session Context/i),
    ).toBeInTheDocument();

    expect(screen.getByText("Codex on macOS")).toBeInTheDocument();
    expect(screen.getByText("Codex · Claude Code · OpenCode")).toBeInTheDocument();
    expect(
      screen.getByText(/Codex waits for you to confirm or narrow the compiled lead/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/GitHub, Slack, Gmail, and Drive paths never masquerade as connected/i),
    ).toBeInTheDocument();
  });

  it("describes observed outcomes without inventing verification", () => {
    renderLanding();

    expect(
      screen.getByRole("heading", { name: "“Done” is not a verification result." }),
    ).toBeInTheDocument();
    expect(screen.getByText("Verified complete")).toBeInTheDocument();
    expect(screen.getByText("Requirements unproven")).toBeInTheDocument();
    expect(screen.getByText("Blocked external")).toBeInTheDocument();
    expect(screen.getByText("Blocked ambiguity")).toBeInTheDocument();
    expect(screen.getByText("Execution failed")).toBeInTheDocument();
    expect(screen.getByText("No silent verification")).toBeInTheDocument();
  });
});
