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
  it("keeps launch copy aligned with available source families", () => {
    renderLanding();

    expect(screen.getByText(/Slack, GitHub, Gmail, and Drive/)).toBeInTheDocument();
    expect(screen.getByText(/Sync Slack, GitHub, Google Drive, Gmail, and AI session imports/)).toBeInTheDocument();
    expect(screen.getAllByText("Google Drive").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Gmail").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Codex").length).toBeGreaterThan(0);
    expect(screen.queryByText("Zoom")).not.toBeInTheDocument();
    expect(screen.queryByText("Notion")).not.toBeInTheDocument();
  });
});
