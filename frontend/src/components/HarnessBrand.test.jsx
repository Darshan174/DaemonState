import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { HarnessLogo } from "./HarnessBrand";


describe("HarnessLogo", () => {
  it.each([
    ["codex", "Codex"],
    ["opencode", "OpenCode"],
  ])(
    "keeps the original white treatment for %s even when Anthropic fill is requested",
    (provider, accessibleName) => {
      render(<HarnessLogo type={provider} anthropicFilled />);

      const logo = screen.getByRole("img", { name: accessibleName });

      expect(logo).toHaveAttribute("data-harness-logo-treatment", "soft");
      expect(logo).toHaveClass("bg-white");
      expect(logo.style.backgroundColor).toBe("");
      expect(logo.querySelector(".opacity-20")).toBeInTheDocument();
    },
  );

  it("fills only the Claude tile with tan and centers the black mark without an inset box", () => {
    render(<HarnessLogo type="claude" anthropicFilled />);

    const logo = screen.getByRole("img", { name: "Claude Code" });
    const artwork = logo.querySelector('[data-harness-artwork="claude"]');

    expect(logo).toHaveAttribute("data-harness-logo-treatment", "anthropic-filled");
    expect(logo).toHaveStyle({ backgroundColor: "#C99E7B" });
    expect(artwork?.tagName).toBe("svg");
    expect(artwork).toHaveStyle({ color: "#252525" });
    expect(logo.querySelector("img")).not.toBeInTheDocument();
    expect(logo.querySelector(".opacity-20")).not.toBeInTheDocument();
  });

  it.each([
    ["codex", "Codex"],
    ["opencode", "OpenCode"],
  ])(
    "matches the native floating button for %s without a raster box or colored glow",
    (provider, accessibleName) => {
      render(<HarnessLogo type={provider} floatingButtonStyle />);

      const logo = screen.getByRole("img", { name: accessibleName });
      const artwork = logo.querySelector(`[data-harness-artwork="${provider}"]`);

      expect(logo).toHaveAttribute("data-harness-logo-treatment", "floating-button");
      expect(logo).toHaveClass("bg-white");
      expect(logo.style.backgroundColor).toBe("");
      expect(logo).toHaveStyle({
        boxShadow: "0 8px 20px rgba(23,23,19,0.09)",
      });
      expect(artwork?.tagName).toBe("svg");
      expect(artwork).toHaveStyle({ color: "#171713" });
      expect(logo.querySelector("img")).not.toBeInTheDocument();
      expect(logo.querySelector(".opacity-20")).not.toBeInTheDocument();
    },
  );

  it("keeps the full tan Claude treatment in floating-button mode", () => {
    render(<HarnessLogo type="claude" floatingButtonStyle />);

    const logo = screen.getByRole("img", { name: "Claude Code" });
    const artwork = logo.querySelector('[data-harness-artwork="claude"]');

    expect(logo).toHaveAttribute("data-harness-logo-treatment", "floating-button");
    expect(logo).toHaveStyle({ backgroundColor: "#C99E7B" });
    expect(artwork).toHaveStyle({ color: "#252525" });
    expect(logo.querySelector("img")).not.toBeInTheDocument();
    expect(logo.querySelector(".opacity-20")).not.toBeInTheDocument();
  });
});
