import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ProductLoadingState from "./ProductLoadingState";

describe("ProductLoadingState", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("shows accessible numeric progress and advances while mounted", () => {
    render(<ProductLoadingState label="Loading observed project activity…" />);

    const progress = screen.getByRole("progressbar", { name: "Loading progress" });
    expect(progress).toHaveAttribute("aria-valuenow", "8");
    expect(screen.getByText("8%")).toBeInTheDocument();

    act(() => vi.advanceTimersByTime(720));

    expect(progress).toHaveAttribute("aria-valuenow", "22");
    expect(screen.getByText("22%")).toBeInTheDocument();
  });

  it("uses task-specific phases without claiming backend byte progress", () => {
    render(
      <ProductLoadingState
        label="Opening session history…"
        stages={["Scanning session stores", "Grouping workstreams", "Preparing the archive"]}
      />,
    );

    expect(screen.getByText("Scanning session stores")).toBeInTheDocument();
    expect(screen.getByRole("status", { name: "Opening session history…" })).toBeInTheDocument();
  });
});
