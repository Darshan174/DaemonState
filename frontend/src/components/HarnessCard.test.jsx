import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { HarnessContinuationCard } from "./HarnessCard";


describe("HarnessContinuationCard", () => {
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

    fireEvent.click(screen.getByRole("button", { name: "Run task in Codex" }));

    expect(onContinue).toHaveBeenCalledWith("codex", {
      provider_model: "gpt-5.6-luna",
      provider_effort: "high",
    });
  });

  it("renders an unavailable harness monochrome and prevents execution", () => {
    const onContinue = vi.fn();
    render(
      <HarnessContinuationCard
        provider={{
          provider: "claude",
          ready: false,
          status: "unavailable",
          code: "desktop_app_missing",
          message: "Claude Desktop is missing.",
          action: "Install Claude Desktop.",
        }}
        taskReady
        onContinue={onContinue}
      />,
    );

    expect(screen.getByRole("article")).toHaveAttribute(
      "data-monochrome",
      "true",
    );
    const button = screen.getByRole("button", {
      name: "Run task in Claude Code",
    });
    expect(button).toBeDisabled();
    fireEvent.click(button);
    expect(onContinue).not.toHaveBeenCalled();
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  });
});
