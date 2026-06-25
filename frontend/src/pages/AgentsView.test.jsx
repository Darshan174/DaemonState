import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import AgentsView from "./AgentsView";

describe("AgentsView", () => {
  it("keeps ingestion-agent copy aligned with launch-available sources", () => {
    render(<AgentsView />);

    expect(screen.getByText("Ingestion Agent")).toBeInTheDocument();
    expect(screen.getByText(/Slack, GitHub, Gmail, Drive, and AI sessions/)).toBeInTheDocument();
    expect(screen.queryByText(/Zoom/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Notion/)).not.toBeInTheDocument();
  });
});
