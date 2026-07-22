import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import ContinuityRail, { stageForPath } from "./ContinuityRail";

describe("ContinuityRail", () => {
  it("maps product surfaces to their role in the continuity loop", () => {
    expect(stageForPath("/app/connectors")).toBe("connect");
    expect(stageForPath("/app/library")).toBe("observe");
    expect(stageForPath("/app/prepare")).toBe("prepare");
    expect(stageForPath("/app")).toBe("continue");
  });

  it("marks the active stage without turning the rail into duplicate navigation", () => {
    render(<ContinuityRail pathname="/app/memory" />);

    expect(screen.getByRole("region", { name: "Continuity loop" })).toBeInTheDocument();
    expect(screen.getByText("Observe").closest("li")).toHaveAttribute("aria-current", "step");
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });
});
