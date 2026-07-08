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
  it("presents implemented product surfaces without fake indexed activity", () => {
    renderLanding();

    expect(
      screen.getByRole("heading", { name: "Project memory graph for AI builders" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: /search/i })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Show dashboard/ })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Add context/ })).not.toBeInTheDocument();
    expect(screen.getByText("What exists today")).toBeInTheDocument();
    expect(screen.getByText("Source-first ingestion")).toBeInTheDocument();
    expect(screen.getByText("Knowledge graph")).toBeInTheDocument();
    expect(screen.getByText("Grounded Ask")).toBeInTheDocument();
    expect(screen.getByText("Connector guardrails")).toBeInTheDocument();
    expect(screen.getByText("For AI agents")).toBeInTheDocument();
    expect(screen.getByText("Every run should start with the same source-backed project memory.")).toBeInTheDocument();
    expect(screen.getByText("Prepare the next run")).toBeInTheDocument();
    expect(screen.getByText("Record what happened")).toBeInTheDocument();
    expect(screen.getByText("Unsupported stays unsupported")).toBeInTheDocument();
    expect(screen.getByTestId("source-active-block")).toBeInTheDocument();
    expect(screen.queryByText("Recently indexed")).not.toBeInTheDocument();
    expect(screen.queryByText("Auth refactor")).not.toBeInTheDocument();
    expect(screen.queryByText("PR #184")).not.toBeInTheDocument();
    expect(screen.queryByText("$ ctxe mcp")).not.toBeInTheDocument();
    expect(screen.getAllByText("Google Drive").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Gmail").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Codex").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Claude").length).toBeGreaterThan(0);
    expect(screen.getAllByText("OpenCode").length).toBeGreaterThan(0);
    expect(screen.getAllByText("GitHub").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Slack").length).toBeGreaterThan(0);
    expect(screen.queryByText("Zoom")).not.toBeInTheDocument();
    expect(screen.queryByText("Notion")).not.toBeInTheDocument();
  });
});
