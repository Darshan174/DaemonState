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

  it("keeps task-specific context accessible while showing only the percentage", () => {
    render(
      <ProductLoadingState
        label="Opening session history…"
        detail="Reading local session stores."
        stages={["Scanning session stores", "Grouping workstreams", "Preparing the archive"]}
      />,
    );

    const status = screen.getByRole("status", { name: "Opening session history…" });
    expect(status).toHaveTextContent(/^8%$/);
    expect(status).toHaveClass("items-center", "justify-center", "bg-black");
    expect(screen.getByRole("progressbar", { name: "Loading progress" })).toHaveAttribute(
      "aria-valuetext",
      "8% — Scanning session stores",
    );
    expect(screen.queryByText("Opening session history…")).not.toBeInTheDocument();
    expect(screen.queryByText("Reading local session stores.")).not.toBeInTheDocument();
    expect(screen.queryByText("Scanning session stores")).not.toBeInTheDocument();
  });
});
