import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

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

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Landing", () => {
  it("presents a source-backed continuity story without fake activity", () => {
    const { container } = renderLanding();

    expect(
      screen.getByRole("heading", { name: "Your next coding agent should not start from zero." }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: /search/i })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Open your context/ })).toHaveAttribute("href", "/app");
    expect(screen.getByRole("link", { name: "See a real handoff" })).toHaveAttribute("href", "#handoff");
    expect(screen.queryByRole("button", { name: /mode/i })).not.toBeInTheDocument();
    expect(container.querySelector(".ce-landing")).toHaveAttribute("data-landing-theme", "fixed");
    expect(screen.getAllByRole("link", { name: "GitHub" })).toHaveLength(2);
    expect(screen.getByText("context_pack.v2")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Every source keeps its identity. The handoff keeps only what matters." })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Evidence becomes a verified handoff" })).toBeInTheDocument();
    expect(screen.getByText("A project should accumulate understanding—not lose it between runs.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Connect" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Observe" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Prepare" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Continue" })).toBeInTheDocument();
    expect(screen.getByText("One engine. Four continuity surfaces.")).toBeInTheDocument();
    const observeSurface = screen.getByRole("button", { name: "Explore Observe" });
    const recallSurface = screen.getByRole("button", { name: "Explore Recall" });
    expect(observeSurface).toHaveAttribute("aria-expanded", "true");
    expect(recallSurface).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByRole("link", { name: /Open Now/ })).toHaveAttribute("href", "/app");
    fireEvent.click(recallSurface);
    expect(observeSurface).toHaveAttribute("aria-expanded", "false");
    expect(recallSurface).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("link", { name: /Inspect memory/ })).toHaveAttribute("href", "/app/memory");
    expect(screen.getByText("The handoff is deliberately finite. Every included claim is inspectable, every exclusion is explicit, and missing evidence remains missing.")).toBeInTheDocument();
    expect(screen.getByText("Illustrative continuation bundle")).toBeInTheDocument();
    expect(screen.getByText("More context is not better context. Relevant context is.")).toBeInTheDocument();
    expect(screen.getByText("Compiled for agents. Explainable to people.")).toBeInTheDocument();
    expect(screen.queryByText("Recently indexed")).not.toBeInTheDocument();
    expect(screen.queryByText("Auth refactor")).not.toBeInTheDocument();
    expect(screen.queryByText("PR #184")).not.toBeInTheDocument();
    expect(screen.queryByText("$ ctxe mcp")).not.toBeInTheDocument();
    expect(screen.queryByText(/Trusted by/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/10,000/i)).not.toBeInTheDocument();

    const pixelCurtains = container.querySelectorAll(".ce-pixel-curtain");
    expect(pixelCurtains).toHaveLength(4);
    pixelCurtains.forEach((curtain) => expect(curtain.children).toHaveLength(48));
    expect(container.querySelectorAll('[data-ce-reveal][data-visible="true"]')).toHaveLength(13);
  });

  it("reveals everything immediately when reduced motion is preferred", () => {
    const Observer = vi.fn(function Observer() {
      return { observe: vi.fn(), unobserve: vi.fn(), disconnect: vi.fn() };
    });
    vi.stubGlobal("IntersectionObserver", Observer);
    vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: true })));

    const { container } = renderLanding();
    const landing = container.querySelector(".ce-landing");

    expect(Observer).not.toHaveBeenCalled();
    expect(landing).not.toHaveClass("ce-motion-ready");
    expect(container.querySelectorAll('[data-ce-reveal][data-visible="true"]')).toHaveLength(13);
  });
});
