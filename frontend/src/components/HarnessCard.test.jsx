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

  it("restores Codex model and effort controls as requested desktop settings", () => {
    const onContinue = vi.fn();
    render(
      <HarnessContinuationCard
        provider={{
          provider: "codex",
          ready: true,
          status: "ready",
          code: "desktop_app_ready",
          desktop_handoff_supported: true,
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
    const model = screen.getByRole("combobox", { name: "Codex model" });
    const effort = screen.getByRole("combobox", {
      name: "Codex reasoning effort",
    });
    expect(model).toHaveValue("gpt-5.6-sol");
    expect(effort).toHaveValue("medium");
    expect(screen.getByText("Ready")).toBeVisible();
    expect(screen.getByText(/confirm them in Codex Desktop/i)).toBeVisible();
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

    fireEvent.change(model, { target: { value: "gpt-5.6-luna" } });
    expect(effort).toHaveValue("high");
    fireEvent.click(screen.getByRole("button", {
      name: "Open desktop handoff in Codex",
    }));

    expect(onContinue).toHaveBeenCalledWith("codex", {
      provider_model: "gpt-5.6-luna",
      provider_effort: "high",
    });
  });

  it("offers an explicit retry after a desktop open request", () => {
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
        handoffRequested
        onContinue={onContinue}
      />,
    );

    const button = screen.getByRole("button", { name: "Open desktop handoff in Codex" });
    expect(button).toBeEnabled();
    expect(button).toHaveAttribute("data-desktop-open-requested", "true");
    expect(button).toHaveTextContent("Request again");
    fireEvent.click(button);
    expect(onContinue).toHaveBeenCalledWith("codex", {});
  });

  it("separates provider readiness from a missing task and removes the disabled Continue label", () => {
    const onContinue = vi.fn();
    render(
      <HarnessContinuationCard
        provider={{
          provider: "codex",
          ready: true,
          status: "ready",
          code: "desktop_app_ready",
          desktop_handoff_supported: true,
          message: "Codex Desktop is installed.",
        }}
        taskReady={false}
        taskRequirement="Choose linked work before continuing."
        onContinue={onContinue}
      />,
    );

    const article = screen.getByRole("article");
    const button = screen.getByRole("button", { name: "Open desktop handoff in Codex" });
    expect(article).toHaveAttribute("data-provider-ready", "true");
    expect(article).toHaveAttribute("data-task-ready", "false");
    expect(article).toHaveAttribute("data-monochrome", "false");
    expect(button).toHaveAttribute("data-provider-ready", "true");
    expect(button).toHaveAttribute("data-task-ready", "false");
    expect(button).toBeDisabled();
    expect(screen.getByText("Ready")).toBeVisible();
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
      const button = screen.getByRole("button", { name: /Open desktop handoff in/ });
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
    fireEvent.click(screen.getByRole("button", { name: "Open desktop handoff in Codex" }));
    expect(onContinue).toHaveBeenCalledWith("codex", {});
  });

  it("shows cached Codex controls without treating installation as usable access", () => {
    const onContinue = vi.fn();
    render(
      <HarnessContinuationCard
        provider={{
          provider: "codex",
          ready: false,
          status: "access_unverified",
          code: "desktop_account_access_unverified",
          desktop_available: true,
          capabilities: {
            desktop_dispatch_available: true,
            account_access_confirmation_supported: true,
          },
          message: "Codex Desktop is installed, but account access is unverified.",
          action: "Verify account access in Codex Desktop.",
          models: [
            {
              id: "gpt-5.6-sol",
              label: "GPT-5.6 Sol",
              default: true,
              reasoning_efforts: ["low", "medium", "high"],
              default_reasoning_effort: "low",
            },
            {
              id: "gpt-5.6-terra",
              label: "GPT-5.6 Terra",
              default: false,
              reasoning_efforts: ["medium", "high"],
              default_reasoning_effort: "high",
            },
          ],
        }}
        taskReady
        onContinue={onContinue}
      />,
    );

    expect(screen.getByText("Access unverified")).toBeVisible();
    expect(screen.getByRole("combobox", { name: "Codex model" })).toBeEnabled();
    expect(screen.getByRole("combobox", {
      name: "Codex reasoning effort",
    })).toBeEnabled();
    const handoff = screen.getByRole("button", {
      name: "Open desktop handoff in Codex",
    });
    expect(handoff).toBeDisabled();
    const confirmation = screen.getByRole("checkbox", {
      name: /confirmed the selected model is usable/i,
    });
    expect(confirmation).not.toBeChecked();
    fireEvent.click(confirmation);
    expect(screen.getByText("User confirmed")).toBeVisible();
    expect(handoff).toBeEnabled();
    fireEvent.change(screen.getByRole("combobox", { name: "Codex model" }), {
      target: { value: "gpt-5.6-terra" },
    });
    expect(confirmation).not.toBeChecked();
    expect(handoff).toBeDisabled();
    fireEvent.click(confirmation);
    fireEvent.click(handoff);
    expect(confirmation).not.toBeChecked();
    expect(handoff).toBeDisabled();
    expect(onContinue).toHaveBeenCalledWith("codex", {
      provider_model: "gpt-5.6-terra",
      provider_effort: "high",
      desktop_access_confirmation: {
        provider: "codex",
        confirmation: "user_confirmed_usable_in_desktop",
      },
    });
  });

  it("requires truthful OpenCode provider or local-model confirmation", () => {
    const onContinue = vi.fn();
    render(
      <HarnessContinuationCard
        provider={{
          provider: "opencode",
          ready: false,
          status: "access_unverified",
          code: "desktop_account_access_unverified",
          desktop_available: true,
          capabilities: {
            desktop_dispatch_available: true,
            account_access_confirmation_supported: true,
          },
          message: "Installation does not prove usable access.",
          action: "Verify access in OpenCode.",
        }}
        taskReady
        onContinue={onContinue}
      />,
    );

    const handoff = screen.getByRole("button", {
      name: "Open desktop handoff in OpenCode",
    });
    const confirmation = screen.getByRole("checkbox", {
      name: /confirmed a usable provider or local model/i,
    });
    expect(screen.queryByText(/subscription verified/i)).not.toBeInTheDocument();
    expect(handoff).toBeDisabled();

    fireEvent.click(confirmation);
    expect(handoff).toBeEnabled();
    fireEvent.click(handoff);
    expect(confirmation).not.toBeChecked();
    expect(handoff).toBeDisabled();

    expect(onContinue).toHaveBeenCalledWith("opencode", {
      desktop_access_confirmation: {
        provider: "opencode",
        confirmation: "user_confirmed_usable_in_desktop",
      },
    });
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
