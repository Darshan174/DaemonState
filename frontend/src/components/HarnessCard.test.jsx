import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { HarnessArchiveCard, HarnessContinuationCard } from "./HarnessCard";


describe("HarnessContinuationCard", () => {
  it.each(["codex", "claude", "opencode"])(
    "uses transparent gold vector artwork for the %s continuation card",
    (provider) => {
      render(
        <HarnessContinuationCard
          provider={{
            provider,
            ready: true,
            status: "ready",
            message: "Ready.",
          }}
          taskReady
          onContinue={vi.fn()}
        />,
      );

      const article = screen.getByRole("article");
      const artwork = article.querySelector(
        `[data-harness-artwork="${provider}"]`,
      );
      expect(artwork?.tagName).toBe("svg");
      expect(artwork).toHaveStyle({ color: "#D4AF37" });
      expect(article).not.toHaveStyle({ color: "#D4AF37" });
    },
  );

  it("keeps a ready Codex card branded and forwards model plus effort", () => {
    const onContinue = vi.fn();
    render(
      <HarnessContinuationCard
        provider={{
          provider: "codex",
          ready: true,
          status: "ready",
          message: "Codex is ready.",
          models: [
            {
              id: "gpt-5.6-sol",
              label: "GPT-5.6 Sol",
              default: true,
              reasoning_efforts: ["low", "medium", "high"],
              default_reasoning_effort: "medium",
            },
            {
              id: "gpt-5.6-luna",
              label: "GPT-5.6 Luna",
              default: false,
              reasoning_efforts: ["low", "high"],
              default_reasoning_effort: "high",
            },
          ],
        }}
        taskReady
        onContinue={onContinue}
      />,
    );

    expect(screen.getByRole("article")).toHaveAttribute(
      "data-monochrome",
      "false",
    );
    fireEvent.change(screen.getByRole("combobox", { name: "Codex model" }), {
      target: { value: "gpt-5.6-luna" },
    });
    expect(
      screen.getByRole("combobox", { name: "Codex reasoning effort" }),
    ).toHaveValue("high");
    expect(screen.getByRole("combobox", { name: "Codex model" })).toHaveClass("h-11", "text-xs");
    expect(screen.getByRole("combobox", { name: "Codex reasoning effort" })).toHaveClass("h-11", "text-xs");
    expect(screen.getByRole("article")).toHaveClass(
      "daemonstate-harness-fan-card",
      "h-[23rem]",
      "min-h-[23rem]",
      "sm:h-[24rem]",
      "sm:min-h-[24rem]",
      "w-[calc(100vw-4rem)]",
      "max-w-[280px]",
      "snap-center",
      "snap-always",
      "dark:text-white",
    );
    expect(screen.getByRole("article")).toHaveStyle({
      "--tw-ring-color": "#10a37f",
      zIndex: "10",
    });
    expect(screen.getByRole("article")).toHaveAttribute("data-fan-position", "left");
    expect(screen.getByRole("article")).not.toHaveClass("-ml-[88px]", "sm:-ml-[58px]");

    fireEvent.click(screen.getByRole("button", { name: "Load context in Codex" }));

    expect(onContinue).toHaveBeenCalledWith("codex", {
      provider_model: "gpt-5.6-luna",
      provider_effort: "high",
    });
  });

  it("shows a staged provider as context loaded and prevents a duplicate thread", () => {
    const onContinue = vi.fn();
    render(
      <HarnessContinuationCard
        provider={{
          provider: "codex",
          ready: true,
          status: "ready",
          message: "Codex is ready.",
        }}
        taskReady
        contextLoaded
        onContinue={onContinue}
      />,
    );

    const button = screen.getByRole("button", { name: "Load context in Codex" });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("data-context-loaded", "true");
    expect(button).toHaveTextContent("Context loaded");
    fireEvent.click(button);
    expect(onContinue).not.toHaveBeenCalled();
  });

  it("separates provider readiness from a missing task and removes the disabled Continue label", () => {
    const onContinue = vi.fn();
    render(
      <HarnessContinuationCard
        provider={{
          provider: "codex",
          ready: true,
          status: "ready",
          message: "Codex CLI is installed and signed in.",
        }}
        taskReady={false}
        taskRequirement="Choose linked work before continuing."
        onContinue={onContinue}
      />,
    );

    const article = screen.getByRole("article");
    const button = screen.getByRole("button", { name: "Load context in Codex" });
    expect(article).toHaveAttribute("data-provider-ready", "true");
    expect(article).toHaveAttribute("data-task-ready", "false");
    expect(article).toHaveAttribute("data-monochrome", "false");
    expect(button).toHaveAttribute("data-provider-ready", "true");
    expect(button).toHaveAttribute("data-task-ready", "false");
    expect(button).toBeDisabled();
    expect(screen.getByText("CLI ready")).toBeVisible();
    expect(screen.getByText("Task required:")).toBeVisible();
    expect(screen.getByText("Choose linked work before continuing.")).toBeVisible();
    expect(screen.getByText("Task required", { exact: true })).toBeVisible();
    expect(screen.queryByText("Continue", { exact: true })).not.toBeInTheDocument();

    fireEvent.click(button);
    expect(onContinue).not.toHaveBeenCalled();
  });

  it.each(["codex", "claude", "opencode"])(
    "renders an unavailable %s harness monochrome without gold artwork and prevents execution",
    (provider) => {
      const onContinue = vi.fn();
      render(
        <HarnessContinuationCard
          provider={{
            provider,
            ready: false,
            status: "unavailable",
            code: "desktop_app_missing",
            message: `${provider} is unavailable.`,
            action: `Install ${provider}.`,
          }}
          taskReady
          onContinue={onContinue}
        />,
      );

      expect(screen.getByRole("article")).toHaveAttribute(
        "data-monochrome",
        "true",
      );
      expect(screen.getByRole("article")).not.toHaveClass("grayscale", "saturate-0");
      const artwork = screen.getByRole("article").querySelector(
        `[data-harness-artwork="${provider}"]`,
      );
      expect(artwork).toHaveClass("grayscale");
      expect(artwork).not.toHaveStyle({ color: "#D4AF37" });
      expect(screen.getByRole("article")).toHaveStyle({
        backgroundColor: "#171715",
      });
      const button = screen.getByRole("button", { name: /Load context in/ });
      expect(button).toBeDisabled();
      fireEvent.click(button);
      expect(onContinue).not.toHaveBeenCalled();
      expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
      expect(screen.getByText(`${provider} is unavailable.`)).toBeVisible();
      expect(screen.getByText(`Next: Install ${provider}.`)).toBeVisible();
      expect(screen.getByText(`${provider} is unavailable.`)).not.toHaveClass("hidden");
    },
  );

  it("does not invent Codex model choices when capability discovery reports none", () => {
    const onContinue = vi.fn();
    render(
      <HarnessContinuationCard
        provider={{
          provider: "codex",
          ready: true,
          status: "ready",
          message: "Codex is ready with its harness default.",
        }}
        taskReady
        onContinue={onContinue}
      />,
    );

    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Load context in Codex" }));
    expect(onContinue).toHaveBeenCalledWith("codex", {});
  });

  it("gives both card variants the same left-center-right fan positions", () => {
    const { unmount } = render(
      <HarnessContinuationCard
        index={1}
        provider={{
          provider: "claude",
          ready: true,
          status: "ready",
          message: "Claude Code is ready.",
        }}
        taskReady
        onContinue={vi.fn()}
      />,
    );

    expect(screen.getByRole("article")).toHaveAttribute("data-fan-position", "center");
    expect(screen.getByRole("article")).toHaveStyle({
      zIndex: "20",
      "--daemonstate-card-rotation": "0deg",
    });
    unmount();

    render(
      <HarnessArchiveCard
        index={2}
        item={{
          connector_type: "opencode",
          name: "OpenCode",
          company: "SST",
          adapter_state: "ready",
          session_count: 3,
          topic_count: 2,
        }}
        hovered={false}
        selected
        translateX={0}
        translateY={-18}
        onHover={vi.fn()}
        onSelect={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: "Open OpenCode sessions" })).toHaveClass(
      "daemonstate-harness-fan-card",
    );
    expect(screen.getByRole("button", { name: "Open OpenCode sessions" })).toHaveAttribute(
      "data-fan-position",
      "right",
    );
    expect(screen.getByRole("button", { name: "Open OpenCode sessions" })).toHaveStyle({
      zIndex: "40",
      "--daemonstate-card-rotation": "0deg",
    });
  });
});
