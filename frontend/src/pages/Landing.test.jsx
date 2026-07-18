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
  it("presents a restrained source-backed product story without fake activity", () => {
    renderLanding();

    expect(
      screen.getByRole("heading", { name: "Make every coding agent start with the project, not a blank chat." }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: /search/i })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Open the local app/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Explore on GitHub/ })).toBeInTheDocument();
    expect(screen.getAllByText("context_pack.v2")).toHaveLength(2);
    expect(screen.getByText("One project loop across every agent.")).toBeInTheDocument();
    expect(screen.getByText("Capture the evidence")).toBeInTheDocument();
    expect(screen.getByText("See work in motion")).toBeInTheDocument();
    expect(screen.getByText("Prepare the handoff")).toBeInTheDocument();
    expect(screen.getByText("Observe the result")).toBeInTheDocument();
    expect(screen.getByText("It prepares the handoff. It does not replace or silently launch your coding agent.")).toBeInTheDocument();
    expect(screen.getByText("The graph is an inspection surface", { exact: false })).toBeInTheDocument();
    expect(screen.getByText("Discord, Zoom, and Wispr Flow remain marked coming soon. Notion is not catalogued.")).toBeInTheDocument();
    expect(screen.queryByText("Recently indexed")).not.toBeInTheDocument();
    expect(screen.queryByText("Auth refactor")).not.toBeInTheDocument();
    expect(screen.queryByText("PR #184")).not.toBeInTheDocument();
    expect(screen.queryByText("$ ctxe mcp")).not.toBeInTheDocument();
    expect(screen.queryByText(/Trusted by/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/10,000/i)).not.toBeInTheDocument();
  });
});
