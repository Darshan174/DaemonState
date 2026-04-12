import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import Query from "../Query";

vi.mock("../../api/hooks", () => ({
  useComponentSources: vi.fn(),
  useContextQuery: vi.fn(),
}));

import { useComponentSources, useContextQuery } from "../../api/hooks";

const noopMut = {
  mutate: vi.fn(),
  data: undefined,
  isPending: false,
  isError: false,
  error: null,
};

beforeEach(() => {
  vi.clearAllMocks();
  useContextQuery.mockReturnValue(noopMut);
  useComponentSources.mockReturnValue({ data: [], isLoading: false, isError: false });
});

function renderQuery({ initialEntries = ["/"] } = {}) {
  return render(
    <MemoryRouter initialEntries={initialEntries}>
      <Query />
    </MemoryRouter>,
  );
}

describe("Query — empty state", () => {
  it("renders hint text and suggested question chips", () => {
    renderQuery();

    expect(screen.getByText("Ask a question to query your knowledge graph.")).toBeInTheDocument();
    expect(screen.getByText("Self-host query flow")).toBeInTheDocument();
    expect(screen.getByText("What is our current MRR?")).toBeInTheDocument();
    expect(screen.getByText("How healthy are our customers?")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Add context" })).toHaveAttribute("href", "/app");
    expect(screen.getByRole("link", { name: "Review trust issues" })).toHaveAttribute("href", "/app/review");
    expect(screen.getByRole("link", { name: "Inspect sources" })).toHaveAttribute("href", "/app/sources");
  });

  it("has Ask button disabled when input is blank", () => {
    renderQuery();

    expect(screen.getByText("Ask")).toBeDisabled();
  });

  it("prefills question, window, and as-of date from URL search params", () => {
    renderQuery({
      initialEntries: [
        "/app/query?question=What%20is%20our%20current%20enterprise%20pricing%3F&window=30&as_of=2026-03-15",
      ],
    });

    expect(screen.getByLabelText("Query input")).toHaveValue(
      "What is our current enterprise pricing?",
    );
    expect(screen.getByLabelText("Context window")).toHaveValue("30");
    expect(screen.getByLabelText("As of date")).toHaveValue("2026-03-15");
  });
});

describe("Query — submit flow", () => {
  it("calls mutate on form submit", async () => {
    const mutate = vi.fn();
    useContextQuery.mockReturnValue({ ...noopMut, mutate });

    renderQuery();

    await userEvent.type(
      screen.getByPlaceholderText("Ask a question about your company data..."),
      "What is our MRR?",
    );
    await userEvent.click(screen.getByText("Ask"));

    expect(mutate).toHaveBeenCalledWith("What is our MRR?");
  });

  it("calls mutate when clicking a suggested question chip", async () => {
    const mutate = vi.fn();
    useContextQuery.mockReturnValue({ ...noopMut, mutate });

    renderQuery();

    await userEvent.click(screen.getByText("What is our current MRR?"));

    expect(mutate).toHaveBeenCalledWith("What is our current MRR?");
  });

  it("passes a temporal window when a recent context filter is selected", async () => {
    const mutate = vi.fn();
    useContextQuery.mockReturnValue({ ...noopMut, mutate });

    renderQuery();

    await userEvent.selectOptions(screen.getByLabelText("Context window"), "7");
    await userEvent.type(
      screen.getByPlaceholderText("Ask a question about your company data..."),
      "What changed in pricing?",
    );
    await userEvent.click(screen.getByText("Ask"));

    expect(mutate).toHaveBeenCalledWith({
      question: "What changed in pricing?",
      maxAgeDays: 7,
    });
  });

  it("passes an as-of timestamp when historical mode is selected", async () => {
    const mutate = vi.fn();
    useContextQuery.mockReturnValue({ ...noopMut, mutate });

    renderQuery();

    await userEvent.type(
      screen.getByPlaceholderText("Ask a question about your company data..."),
      "What did pricing look like before the change?",
    );
    await userEvent.type(screen.getByLabelText("As of date"), "2026-03-15");
    await userEvent.click(screen.getByText("Ask"));

    expect(mutate).toHaveBeenCalledWith({
      question: "What did pricing look like before the change?",
      maxAgeDays: null,
      asOf: "2026-03-15T00:00:00.000Z",
    });
  });

  it("shows pending state", () => {
    useContextQuery.mockReturnValue({ ...noopMut, isPending: true });

    renderQuery();

    expect(screen.getByText("Querying knowledge graph...")).toBeInTheDocument();
    expect(screen.getByText("Thinking...")).toBeInTheDocument();
  });
});

describe("Query — mock response", () => {
  const mockResult = {
    question: "What is our MRR?",
    answer: "Current MRR is $2.4M.",
    confidence: 0.92,
    answeredAt: "just now",
    components: [
      { id: "c1", name: "MRR", value: "$2.4M", model: "Revenue Model" },
    ],
    sources: ["Stripe", "Internal DB"],
    _isMock: true,
  };

  it("shows answer and MockBadge for mock response", () => {
    useContextQuery.mockReturnValue({ ...noopMut, data: mockResult });

    renderQuery();

    expect(screen.getByText("Current MRR is $2.4M.")).toBeInTheDocument();
    expect(screen.getByText(/Demo data/)).toBeInTheDocument();
  });

  it("renders cited components", () => {
    useContextQuery.mockReturnValue({ ...noopMut, data: mockResult });

    renderQuery();

    expect(screen.getByText("Cited Components")).toBeInTheDocument();
    expect(screen.getByText("MRR")).toBeInTheDocument();
    expect(screen.getByText("$2.4M")).toBeInTheDocument();
    expect(screen.getByText("Revenue Model")).toBeInTheDocument();
  });

  it("renders source chips", () => {
    useContextQuery.mockReturnValue({ ...noopMut, data: mockResult });

    renderQuery();

    expect(screen.getByText("Sources")).toBeInTheDocument();
    expect(screen.getByText("Stripe")).toBeInTheDocument();
    expect(screen.getByText("Internal DB")).toBeInTheDocument();
  });
});

describe("Query — real response", () => {
  it("shows answer without MockBadge for real response", () => {
    const realResult = {
      question: "What is our MRR?",
      answer: "MRR is $3.1M as of this month.",
      confidence: 0.95,
      answeredAt: "2s ago",
      components: [],
      sources: [],
    };
    useContextQuery.mockReturnValue({ ...noopMut, data: realResult });

    renderQuery();

    expect(screen.getByText("MRR is $3.1M as of this month.")).toBeInTheDocument();
    expect(screen.queryByText(/Demo data/)).not.toBeInTheDocument();
  });
});

describe("Query — object sources", () => {
  it("renders structured source objects with type and author", () => {
    const result = {
      question: "Test?",
      answer: "Answer.",
      confidence: 0.9,
      sources: [
        { type: "Slack", author: "alice", date: "2024-03-01" },
        { type: "Notion", url: "https://notion.so/page" },
      ],
    };
    useContextQuery.mockReturnValue({ ...noopMut, data: result });

    renderQuery();

    expect(screen.getByText("Slack")).toBeInTheDocument();
    expect(screen.getByText(/alice/)).toBeInTheDocument();
    expect(screen.getByText("Notion")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Notion" })).toHaveAttribute(
      "href",
      "https://notion.so/page",
    );
  });

  it("renders mixed string and object sources", () => {
    const result = {
      question: "Test?",
      answer: "Answer.",
      confidence: 0.9,
      sources: ["CSV export", { type: "Gong", author: "bob" }],
    };
    useContextQuery.mockReturnValue({ ...noopMut, data: result });

    renderQuery();

    expect(screen.getByText("CSV export")).toBeInTheDocument();
    expect(screen.getByText("Gong")).toBeInTheDocument();
    expect(screen.getByText(/bob/)).toBeInTheDocument();
  });
});

describe("Query — freshness badge", () => {
  it("shows freshness badge when present on result", () => {
    const result = {
      question: "Test?",
      answer: "Answer.",
      confidence: 0.9,
      freshness: "2 min ago",
      answeredAt: "just now",
      sources: [],
    };
    useContextQuery.mockReturnValue({ ...noopMut, data: result });

    renderQuery();

    expect(screen.getByText("2 min ago")).toBeInTheDocument();
  });

  it("does not show freshness badge when absent", () => {
    const result = {
      question: "Test?",
      answer: "Answer.",
      confidence: 0.9,
      answeredAt: "just now",
      sources: [],
    };
    useContextQuery.mockReturnValue({ ...noopMut, data: result });

    renderQuery();

    expect(screen.getByText("just now")).toBeInTheDocument();
    // No freshness badge rendered
    expect(screen.queryByText(/min ago/)).not.toBeInTheDocument();
  });
});

describe("Query — semantic freshness", () => {
  it("shows 'Current' with green styling for freshness=current", () => {
    const result = {
      question: "Test?",
      answer: "Answer.",
      confidence: 0.9,
      freshness: "current",
      sources: [],
    };
    useContextQuery.mockReturnValue({ ...noopMut, data: result });

    renderQuery();

    const badge = screen.getByText("Current");
    expect(badge).toBeInTheDocument();
    expect(badge.className).toMatch(/emerald/);
  });

  it("shows 'Possibly stale' with amber styling", () => {
    const result = {
      question: "Test?",
      answer: "Answer.",
      confidence: 0.9,
      freshness: "possibly_stale",
      sources: [],
    };
    useContextQuery.mockReturnValue({ ...noopMut, data: result });

    renderQuery();

    const badge = screen.getByText("Possibly stale");
    expect(badge).toBeInTheDocument();
    expect(badge.className).toMatch(/amber/);
  });

  it("shows 'Stale' with red styling", () => {
    const result = {
      question: "Test?",
      answer: "Answer.",
      confidence: 0.9,
      freshness: "stale",
      sources: [],
    };
    useContextQuery.mockReturnValue({ ...noopMut, data: result });

    renderQuery();

    const badge = screen.getByText("Stale");
    expect(badge).toBeInTheDocument();
    expect(badge.className).toMatch(/red/);
  });
});

describe("Query — empty answer (non-zero confidence)", () => {
  it("shows fallback message when answer is empty string", () => {
    const result = {
      question: "Unknown?",
      answer: "",
      confidence: 0.5,
      sources: ["some source"],
    };
    useContextQuery.mockReturnValue({ ...noopMut, data: result });

    renderQuery();

    expect(screen.getByText("No answer could be determined for this query.")).toBeInTheDocument();
  });

  it("shows fallback message when answer is null", () => {
    const result = {
      question: "Unknown?",
      answer: null,
      confidence: 0.5,
      sources: ["some source"],
    };
    useContextQuery.mockReturnValue({ ...noopMut, data: result });

    renderQuery();

    expect(screen.getByText("No answer could be determined for this query.")).toBeInTheDocument();
  });
});

describe("Query — no-match response", () => {
  it("shows dedicated no-match state for confidence=0 with no components/sources", () => {
    const result = {
      question: "What is our churn rate?",
      answer: "I could not find matching structured context for this question.",
      confidence: 0,
      components: [],
      sources: [],
    };
    useContextQuery.mockReturnValue({ ...noopMut, data: result });

    renderQuery();

    expect(screen.getByText("No grounded answer found")).toBeInTheDocument();
    expect(screen.getByText(/could not find matching/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Connectors" })).toHaveAttribute("href", "/app/connectors");
    // Should NOT render like a normal answer card
    expect(screen.queryByText("Confidence")).not.toBeInTheDocument();
    expect(screen.queryByText("Cited Components")).not.toBeInTheDocument();
  });

  it("shows default no-match text when answer is empty", () => {
    const result = {
      question: "Unknown thing?",
      answer: "",
      confidence: 0,
      components: [],
      sources: [],
    };
    useContextQuery.mockReturnValue({ ...noopMut, data: result });

    renderQuery();

    expect(screen.getByText("No grounded answer found")).toBeInTheDocument();
    expect(screen.getByText(/does not contain enough structured context/)).toBeInTheDocument();
  });

  it("suggests widening the context window when a recent filter returns no match", async () => {
    const result = {
      question: "Unknown thing?",
      answer: "",
      confidence: 0,
      components: [],
      sources: [],
    };
    useContextQuery.mockReturnValue({ ...noopMut, data: result, mutate: vi.fn() });

    renderQuery();

    await userEvent.selectOptions(screen.getByLabelText("Context window"), "7");
    await userEvent.type(
      screen.getByPlaceholderText("Ask a question about your company data..."),
      "Unknown thing?",
    );
    await userEvent.click(screen.getByText("Ask"));

    expect(screen.getByText(/Try widening the context window/i)).toBeInTheDocument();
  });
});

describe("Query — real backend success response", () => {
  it("renders answer with confidence bar, freshness, components, and sources", () => {
    const result = {
      question: "What is our MRR?",
      answer: "Current MRR is $3.1M based on Stripe data.",
      confidence: 0.92,
      freshness: "current",
      answeredAt: "2s ago",
      components: [
        { id: "c1", name: "MRR", value: "$3.1M", model: "Revenue Model", confidence: 0.95, authority_source: "stripe", last_verified_at: "2026-03-29" },
      ],
      sources: [
        { type: "Stripe", url: "https://dashboard.stripe.com" },
        { type: "Internal DB", author: "system" },
      ],
    };
    useContextQuery.mockReturnValue({ ...noopMut, data: result });

    renderQuery();

    // Answer text
    expect(screen.getByText("Current MRR is $3.1M based on Stripe data.")).toBeInTheDocument();
    expect(screen.getByText("Live backend")).toBeInTheDocument();
    expect(screen.getByText("Live workspace context")).toBeInTheDocument();
    expect(screen.getByText("Grounded in 1 component from 2 sources.")).toBeInTheDocument();
    // Confidence
    expect(screen.getByText("92%")).toBeInTheDocument();
    // Freshness badge
    const badge = screen.getByText("Current");
    expect(badge).toBeInTheDocument();
    expect(badge.className).toMatch(/emerald/);
    // Components
    expect(screen.getByText("Cited Components")).toBeInTheDocument();
    expect(screen.getByText("MRR")).toBeInTheDocument();
    expect(screen.getByText("$3.1M")).toBeInTheDocument();
    // Component metadata
    expect(screen.getByText("95% confidence")).toBeInTheDocument();
    expect(screen.getByText("via stripe")).toBeInTheDocument();
    expect(screen.getByText(/^verified /)).toBeInTheDocument();
    // Sources
    expect(screen.getByText("Sources")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Stripe" })).toHaveAttribute("href", "https://dashboard.stripe.com");
    expect(screen.getByText("Internal DB")).toBeInTheDocument();
    // No mock badge
    expect(screen.queryByText(/Demo data/)).not.toBeInTheDocument();
  });

  it("shows the selected context window on live backend answers", async () => {
    const result = {
      question: "What changed in pricing?",
      answer: "Pricing changed this week.",
      confidence: 0.84,
      components: [],
      sources: [],
    };
    useContextQuery.mockReturnValue({ ...noopMut, data: result, mutate: vi.fn() });

    renderQuery();

    await userEvent.selectOptions(screen.getByLabelText("Context window"), "7");
    await userEvent.type(
      screen.getByPlaceholderText("Ask a question about your company data..."),
      "What changed in pricing?",
    );
    await userEvent.click(screen.getByText("Ask"));

    expect(screen.getByText("Window: last 7 days")).toBeInTheDocument();
  });

  it("shows the selected as-of date on live backend answers", async () => {
    const result = {
      question: "What did pricing look like before the change?",
      answer: "As of mid-March, pricing was still $500/seat.",
      confidence: 0.82,
      components: [],
      sources: [],
    };
    useContextQuery.mockReturnValue({ ...noopMut, data: result, mutate: vi.fn() });

    renderQuery();

    await userEvent.type(
      screen.getByPlaceholderText("Ask a question about your company data..."),
      "What did pricing look like before the change?",
    );
    await userEvent.type(screen.getByLabelText("As of date"), "2026-03-15");
    await userEvent.click(screen.getByText("Ask"));

    expect(screen.getByText(/As of:\s*(Mar 15, 2026|15 Mar 2026)/i)).toBeInTheDocument();
  });

  it("renders multiline causal answers as separate paragraphs", () => {
    const result = {
      question: "Why is MRR growing?",
      answer: "MRR is growing at 12% MoM.\nThis is driven by expansion revenue from existing customers.\nChurn remains low at 2%.",
      confidence: 0.88,
      freshness: "current",
      components: [],
      sources: [],
    };
    useContextQuery.mockReturnValue({ ...noopMut, data: result });

    renderQuery();

    expect(screen.getByText("MRR is growing at 12% MoM.")).toBeInTheDocument();
    expect(screen.getByText(/driven by expansion revenue/)).toBeInTheDocument();
    expect(screen.getByText(/Churn remains low/)).toBeInTheDocument();
  });

  it("renders supporting document links for the overall answer and cited components", () => {
    const result = {
      question: "Why did pricing change?",
      answer: "Pricing moved after the finance review.",
      confidence: 0.9,
      reviewStatus: "needs_review",
      reviewItemId: "rq1",
      reviewSummary: "Pricing changed recently and still needs final human confirmation.",
      components: [
        {
          id: "c1",
          name: "Enterprise Pricing",
          value: "$600/seat",
          model: "Pricing Strategy",
          reviewStatus: "superseded",
          reviewItemId: "rq4",
          temporalState: "historical",
          sourceDocuments: [
            { id: "sd1", label: "#pricing decision", connectorType: "slack" },
          ],
        },
      ],
      sourceDocuments: [
        { id: "sd4", label: "Pricing Strategy", connectorType: "notion" },
      ],
      sources: [],
    };
    useContextQuery.mockReturnValue({ ...noopMut, data: result });

    renderQuery();

    expect(screen.getByText("Needs review")).toBeInTheDocument();
    expect(screen.getByText(/still needs final human confirmation/i)).toBeInTheDocument();
    const reviewLinks = screen.getAllByRole("link", { name: "Open review item" });
    expect(reviewLinks.some((link) => link.getAttribute("href") === "/app/review/rq1")).toBe(true);
    expect(reviewLinks.some((link) => link.getAttribute("href") === "/app/review/rq4")).toBe(true);
    expect(screen.getByText("Historical context")).toBeInTheDocument();
    expect(screen.queryByText("Cited Components")).not.toBeInTheDocument();
    expect(screen.getByText("Historical Context")).toBeInTheDocument();
    expect(screen.getByText("Supporting documents")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Pricing Strategy/ })).toHaveAttribute(
      "href",
      "/app/sources/sd4",
    );
    expect(screen.getByText("Evidence")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /pricing decision/i })).toHaveAttribute(
      "href",
      "/app/sources/sd1",
    );
  });

  it("loads cited-component evidence from the component sources endpoint when needed", () => {
    useComponentSources.mockImplementation((componentId) => ({
      data:
        componentId === "c1"
          ? [
              {
                id: "sd7",
                label: "Pricing approval memo",
                connectorType: "notion",
                author: "CEO",
                extractionContext: "Approved during pricing review",
                extractorName: "Structured extractor",
                extractorSchemaVersion: "2",
              },
            ]
          : [],
      isLoading: false,
      isError: false,
    }));
    const result = {
      question: "Why did pricing change?",
      answer: "Pricing moved after the finance review.",
      confidence: 0.9,
      components: [
        {
          id: "c1",
          name: "Enterprise Pricing",
          value: "$600/seat",
          model: "Pricing Strategy",
        },
      ],
      sources: [],
    };
    useContextQuery.mockReturnValue({ ...noopMut, data: result });

    renderQuery();

    expect(screen.getByRole("link", { name: /Pricing approval memo/i })).toHaveAttribute(
      "href",
      "/app/sources/sd7",
    );
    expect(screen.getByText("Author: CEO")).toBeInTheDocument();
    expect(screen.getByText("Approved during pricing review")).toBeInTheDocument();
    expect(screen.getByText("Extracted by Structured extractor · schema v2")).toBeInTheDocument();
  });

  it("splits current and historical components into separate sections", () => {
    const result = {
      question: "What changed in churn?",
      answer: "Current churn is 2.8%, but the older benchmark was 3.2%.",
      confidence: 0.85,
      components: [
        { id: "c1", name: "Current Churn", value: "2.8%", model: "Health" },
        {
          id: "c2",
          name: "Old Churn",
          value: "3.2%",
          model: "Health",
          reviewStatus: "superseded",
          temporalState: "historical",
        },
      ],
      sources: [],
    };
    useContextQuery.mockReturnValue({ ...noopMut, data: result });

    renderQuery();

    expect(screen.getByText("Cited Components")).toBeInTheDocument();
    expect(screen.getByText("Historical Context")).toBeInTheDocument();
    expect(screen.getByText(/superseded facts are separated/i)).toBeInTheDocument();
  });

  it("omits component metadata line when fields are absent", () => {
    const result = {
      question: "Test?",
      answer: "Answer.",
      confidence: 0.9,
      components: [
        { id: "c1", name: "Metric", value: "100", model: "M1" },
      ],
      sources: [],
    };
    useContextQuery.mockReturnValue({ ...noopMut, data: result });

    renderQuery();

    expect(screen.getByText("Metric")).toBeInTheDocument();
    expect(screen.queryByText(/confidence$/)).not.toBeInTheDocument();
    expect(screen.queryByText(/^via /)).not.toBeInTheDocument();
    expect(screen.queryByText(/^verified /)).not.toBeInTheDocument();
  });
});

describe("Query — network failure mock fallback", () => {
  it("shows mock badge when response has _isMock flag", () => {
    const mockResult = {
      question: "What is our MRR?",
      answer: "Current MRR is $2.4M.",
      confidence: 0.92,
      answeredAt: "just now",
      components: [
        { id: "c1", name: "MRR", value: "$2.4M", model: "Revenue Model" },
      ],
      sources: ["Stripe"],
      _isMock: true,
    };
    useContextQuery.mockReturnValue({ ...noopMut, data: mockResult });

    renderQuery();

    expect(screen.getByText("Current MRR is $2.4M.")).toBeInTheDocument();
    expect(screen.getByText(/Demo data/)).toBeInTheDocument();
  });
});

describe("Query — error state", () => {
  it("shows error message and retry button", () => {
    useContextQuery.mockReturnValue({
      ...noopMut,
      isError: true,
      error: { message: "Server returned 500" },
    });

    renderQuery();

    expect(screen.getByText("Server returned 500")).toBeInTheDocument();
    expect(screen.getByText("Retry")).toBeInTheDocument();
  });

  it("retry button calls mutate with current input", async () => {
    const mutate = vi.fn();
    useContextQuery.mockReturnValue({
      ...noopMut,
      mutate,
      isError: true,
      error: { message: "Server error" },
    });

    renderQuery();

    await userEvent.type(
      screen.getByPlaceholderText("Ask a question about your company data..."),
      "What is our MRR?",
    );
    await userEvent.click(screen.getByText("Retry"));

    expect(mutate).toHaveBeenCalledWith("What is our MRR?");
  });

  it("retry preserves the selected temporal window", async () => {
    const mutate = vi.fn();
    useContextQuery.mockReturnValue({
      ...noopMut,
      mutate,
      isError: true,
      error: { message: "Server error" },
    });

    renderQuery();

    await userEvent.selectOptions(screen.getByLabelText("Context window"), "30");
    await userEvent.type(
      screen.getByPlaceholderText("Ask a question about your company data..."),
      "What changed in onboarding?",
    );
    await userEvent.click(screen.getByText("Retry"));

    expect(mutate).toHaveBeenCalledWith({
      question: "What changed in onboarding?",
      maxAgeDays: 30,
    });
  });

  it("retry preserves the selected as-of date", async () => {
    const mutate = vi.fn();
    useContextQuery.mockReturnValue({
      ...noopMut,
      mutate,
      isError: true,
      error: { message: "Server error" },
    });

    renderQuery();

    await userEvent.type(
      screen.getByPlaceholderText("Ask a question about your company data..."),
      "What was our onboarding policy?",
    );
    await userEvent.type(screen.getByLabelText("As of date"), "2026-02-01");
    await userEvent.click(screen.getByText("Retry"));

    expect(mutate).toHaveBeenCalledWith({
      question: "What was our onboarding policy?",
      maxAgeDays: null,
      asOf: "2026-02-01T00:00:00.000Z",
    });
  });

  it("hides empty state when error is shown", () => {
    useContextQuery.mockReturnValue({
      ...noopMut,
      isError: true,
      error: { message: "fail" },
    });

    renderQuery();

    expect(screen.queryByText("Ask a question to query your knowledge graph.")).not.toBeInTheDocument();
  });

  it("shows real 4xx/5xx errors without mock fallback", () => {
    useContextQuery.mockReturnValue({
      ...noopMut,
      isError: true,
      error: { message: "422 Unprocessable Entity", status: 422 },
    });

    renderQuery();

    expect(screen.getByText("422 Unprocessable Entity")).toBeInTheDocument();
    expect(screen.queryByText(/Demo data/)).not.toBeInTheDocument();
  });
});
