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
      screen.getByRole("heading", { name: "Your next coding agent shouldn’t start from zero." }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: /search/i })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Prepare a run/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /View on GitHub/ })).toBeInTheDocument();
    expect(screen.getAllByText("context_pack.v2")).toHaveLength(2);
    expect(screen.getByText("Continuity, without another pile of notes.")).toBeInTheDocument();
    expect(screen.getByText("Keep the source")).toBeInTheDocument();
    expect(screen.getByText("Track what changed")).toBeInTheDocument();
    expect(screen.getByText("Prepare the next run")).toBeInTheDocument();
    expect(screen.getByText("Unsupported providers stay visibly unsupported.", { exact: false })).toBeInTheDocument();
    expect(screen.queryByText("Recently indexed")).not.toBeInTheDocument();
    expect(screen.queryByText("Auth refactor")).not.toBeInTheDocument();
    expect(screen.queryByText("PR #184")).not.toBeInTheDocument();
    expect(screen.queryByText("$ ctxe mcp")).not.toBeInTheDocument();
    expect(screen.queryByText(/Trusted by/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/10,000/i)).not.toBeInTheDocument();
  });
});
