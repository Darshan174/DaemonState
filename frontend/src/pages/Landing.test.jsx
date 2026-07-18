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
      screen.getByRole("heading", { name: "Give every coding agent the context this project already earned." }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: /search/i })).not.toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: /Explore the alpha/ })).toHaveLength(2);
    expect(screen.getByRole("link", { name: /View on GitHub/ })).toBeInTheDocument();
    expect(screen.getAllByText("context_pack.v2")).toHaveLength(2);
    expect(screen.getByText("Project history in. Focused context out.")).toBeInTheDocument();
    expect(screen.getByText("Preserve the evidence")).toBeInTheDocument();
    expect(screen.getByText("Choose the current task")).toBeInTheDocument();
    expect(screen.getByText("Compile only what matters")).toBeInTheDocument();
    expect(screen.getByText("Every selected fact keeps its source. Missing evidence stays missing.")).toBeInTheDocument();
    expect(screen.getByText("Compiled for agents. Explainable to people.")).toBeInTheDocument();
    expect(screen.queryByText("Recently indexed")).not.toBeInTheDocument();
    expect(screen.queryByText("Auth refactor")).not.toBeInTheDocument();
    expect(screen.queryByText("PR #184")).not.toBeInTheDocument();
    expect(screen.queryByText("$ ctxe mcp")).not.toBeInTheDocument();
    expect(screen.queryByText(/Trusted by/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/10,000/i)).not.toBeInTheDocument();
  });
});
