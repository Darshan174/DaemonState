import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { describe, expect, it } from "vitest";

import ContinuityRail, { stageForPath } from "./ContinuityRail";

describe("ContinuityRail", () => {
  it("maps product surfaces to their role in the continuity loop", () => {
    expect(stageForPath("/app/connectors")).toBe("connect");
    expect(stageForPath("/app/library")).toBe("prepare");
    expect(stageForPath("/app/execute")).toBe("observe");
    expect(stageForPath("/app/memory")).toBe("observe");
    expect(stageForPath("/app")).toBe("continue");
  });

  it("links every stage to a working product surface and updates the active step", () => {
    render(
      <MemoryRouter initialEntries={["/app/execute/inspector"]}>
        <ContinuityRailHarness />
      </MemoryRouter>,
    );

    expect(screen.getByRole("region", { name: "Continuity loop" })).toBeInTheDocument();
    expect(screen.getByText("Observe").closest("li")).toHaveAttribute("aria-current", "step");
    expect(screen.getByRole("link", { name: "Connect" })).toHaveAttribute("href", "/app/connectors");
    expect(screen.getByRole("link", { name: "Observe" })).toHaveAttribute("href", "/app/execute/inspector");
    expect(screen.getByRole("link", { name: "Prepare" })).toHaveAttribute("href", "/app/library");
    expect(screen.getByRole("link", { name: "Continue" })).toHaveAttribute("href", "/app");

    fireEvent.click(screen.getByRole("link", { name: "Prepare" }));

    expect(screen.getByTestId("location")).toHaveTextContent("/app/library");
    expect(screen.getByText("Prepare").closest("li")).toHaveAttribute("aria-current", "step");
  });
});

function ContinuityRailHarness() {
  const location = useLocation();
  return (
    <>
      <ContinuityRail pathname={location.pathname} />
      <output data-testid="location">{location.pathname}</output>
    </>
  );
}
