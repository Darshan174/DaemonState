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
  it("positions the product as a visual project graph for AI builders", () => {
    renderLanding();

    expect(
      screen.getByRole("heading", { name: "See your AI-built project as a living graph." }),
    ).toBeInTheDocument();
    expect(screen.getByText(/One graph for every moving part/)).toBeInTheDocument();
    expect(screen.getByText(/Upload a coding session. Get a project graph/)).toBeInTheDocument();
    expect(screen.getByText("Generate next-agent packet")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Star on GitHub/ })).toBeInTheDocument();
    expect(screen.getAllByText("Google Drive").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Gmail").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Codex").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Claude").length).toBeGreaterThan(0);
    expect(screen.queryByText("Zoom")).not.toBeInTheDocument();
    expect(screen.queryByText("Notion")).not.toBeInTheDocument();
  });
});
