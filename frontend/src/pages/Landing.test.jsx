import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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
  it("presents a compact project context directory", () => {
    renderLanding();

    expect(
      screen.getByRole("heading", { name: "The project memory graph for AI builders" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Search project context" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Add context/ })).toBeInTheDocument();
    expect(screen.getByText("Recently indexed")).toBeInTheDocument();
    expect(screen.getByText("Auth refactor")).toBeInTheDocument();
    expect(screen.getByText("PR #184")).toBeInTheDocument();
    expect(screen.getByText("Move from memory to work.")).toBeInTheDocument();
    expect(screen.getAllByText("Google Drive").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Gmail").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Codex").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Claude").length).toBeGreaterThan(0);
    expect(screen.queryByText("Zoom")).not.toBeInTheDocument();
    expect(screen.queryByText("Notion")).not.toBeInTheDocument();
  });

  it("filters recent context from the search field", async () => {
    const user = userEvent.setup();
    renderLanding();

    await user.type(screen.getByRole("textbox", { name: "Search project context" }), "schema");

    expect(screen.getByText("Matching context")).toBeInTheDocument();
    expect(screen.getByText("Schema approval")).toBeInTheDocument();
    expect(screen.queryByText("Auth refactor")).not.toBeInTheDocument();
  });
});
