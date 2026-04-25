import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import Accuracy from "../Accuracy";

vi.mock("../../api/hooks", () => ({
  useEvalCases: vi.fn(),
  useEvalSummary: vi.fn(),
  useRunEvals: vi.fn(),
}));

import { useEvalCases, useEvalSummary, useRunEvals } from "../../api/hooks";

let mutateRunEvals;

function renderAccuracy({ initialEntries = ["/app/accuracy"] } = {}) {
  return render(
    <MemoryRouter initialEntries={initialEntries}>
      <Accuracy />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mutateRunEvals = vi.fn();
  useEvalCases.mockReturnValue({
    isLoading: false,
    isError: false,
    isMock: false,
    data: {
      selectedDomain: "pricing",
      cases: [
        {
          caseId: "pricing-1",
          domain: "pricing",
          question: "What is our current enterprise pricing?",
          predictedConfidence: 0.89,
          retrievalHitQuality: 0.92,
          extractedFactCorrectness: 0.86,
          finalAnswerCorrectness: 1,
          passed: true,
          detail: "Pulled the latest approved pricing decision.",
        },
      ],
    },
    refetch: vi.fn(),
  });
  useRunEvals.mockReturnValue({
    mutate: mutateRunEvals,
    isPending: false,
    isError: false,
    isSuccess: false,
    error: null,
  });
});

describe("Accuracy", () => {
  it("shows loading state", () => {
    useEvalSummary.mockReturnValue({
      isLoading: true,
      isError: false,
      data: undefined,
      refetch: vi.fn(),
    });

    renderAccuracy({ initialEntries: ["/app/accuracy?domain=pricing"] });

    expect(screen.getByText("Loading...")).toBeInTheDocument();
  });

  it("shows a self-host onboarding state when no eval summary exists yet", () => {
    useEvalSummary.mockReturnValue({
      isLoading: false,
      isError: false,
      isMock: false,
      data: null,
      refetch: vi.fn(),
    });

    renderAccuracy();

    expect(screen.getByText("Accuracy data is not ready yet for this workspace.")).toBeInTheDocument();
    expect(screen.getByText(/python3 scripts\/run_eval_regression.py --workspace-id/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open sources" })).toHaveAttribute("href", "/app/sources");
    expect(screen.getByRole("button", { name: "Run evals now" })).toBeInTheDocument();
  });

  it("renders live accuracy summary, domains, metrics, and blockers", () => {
    useEvalSummary.mockReturnValue({
      isLoading: false,
      isError: false,
      isMock: false,
      data: {
        passRate: 0.72,
        passedCases: 18,
        totalCases: 25,
        threshold: 0.7,
        latestRunAt: "2026-04-01T09:30:00Z",
        domains: [
          { domain: "pricing", passRate: 0.8, passed: 4, total: 5 },
          { domain: "meeting", passRate: 0.6, passed: 3, total: 5 },
        ],
        metrics: [
          {
            key: "retrieval_recall",
            label: "Retrieval recall",
            value: 0.84,
            target: 0.9,
            direction: "up",
          },
        ],
        blockers: ["Meeting coverage is still thin."],
      },
      refetch: vi.fn(),
    });

    renderAccuracy({ initialEntries: ["/app/accuracy?domain=pricing"] });

    expect(screen.getByText("Accuracy")).toBeInTheDocument();
    expect(screen.getByText("Accuracy is above the current threshold")).toBeInTheDocument();
    expect(screen.getByText("72%")).toBeInTheDocument();
    expect(screen.getByText("Domain breakdown")).toBeInTheDocument();
    expect(screen.getByText("pricing")).toBeInTheDocument();
    expect(screen.getByText("meeting")).toBeInTheDocument();
    expect(screen.getByText("Metric summary")).toBeInTheDocument();
    expect(screen.getByText("Retrieval recall")).toBeInTheDocument();
    expect(screen.getByText("Meeting coverage is still thin.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open review queue" })).toHaveAttribute(
      "href",
      "/app/review",
    );
    expect(screen.getByRole("button", { name: "Run pricing evals" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run all evals" })).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "Try benchmark query" })[0]).toHaveAttribute(
      "href",
      "/app/query?question=What+is+our+current+enterprise+pricing%3F&window=30",
    );
    expect(screen.getByText("pricing cases")).toBeInTheDocument();
    expect(screen.getByText("Pulled the latest approved pricing decision.")).toBeInTheDocument();
  });

  it("shows mock badge and demo note when using fallback data", () => {
    useEvalSummary.mockReturnValue({
      isLoading: false,
      isError: false,
      isMock: true,
      data: {
        passRate: 0.58,
        passedCases: 14,
        totalCases: 25,
        threshold: 0.7,
        latestRunAt: "2026-04-01T09:30:00Z",
        domains: [],
        metrics: [],
        blockers: [],
      },
      refetch: vi.fn(),
    });

    renderAccuracy();

    expect(screen.getByText(/Demo data/)).toBeInTheDocument();
    expect(screen.getByText(/Showing demo accuracy data/)).toBeInTheDocument();
    expect(screen.getByText("Accuracy still needs hardening")).toBeInTheDocument();
  });

  it("lets the operator switch the case panel to another domain", async () => {
    useEvalSummary.mockReturnValue({
      isLoading: false,
      isError: false,
      isMock: false,
      data: {
        passRate: 0.72,
        passedCases: 18,
        totalCases: 25,
        threshold: 0.7,
        latestRunAt: "2026-04-01T09:30:00Z",
        domains: [
          { domain: "pricing", passRate: 0.8, passed: 4, total: 5 },
          { domain: "meeting", passRate: 0.6, passed: 3, total: 5 },
        ],
        metrics: [],
        blockers: [],
      },
      refetch: vi.fn(),
    });
    useEvalCases.mockReturnValue({
      isLoading: false,
      isError: false,
      isMock: false,
      data: {
        selectedDomain: "meeting",
        cases: [
          {
            caseId: "meeting-1",
            domain: "meeting",
            question: "What did we decide in the latest product review meeting?",
            predictedConfidence: 0.67,
            retrievalHitQuality: 0.72,
            extractedFactCorrectness: 0.63,
            finalAnswerCorrectness: 0.58,
            passed: false,
            detail: "Transcript retrieval found the right meeting, but the decision extraction still needs work.",
          },
        ],
      },
      refetch: vi.fn(),
    });

    renderAccuracy({ initialEntries: ["/app/accuracy?domain=meeting"] });

    expect(screen.getByText("meeting cases")).toBeInTheDocument();
    expect(screen.getByText(/decision extraction still needs work/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Run domain benchmark query" })).toHaveAttribute(
      "href",
      "/app/query?question=What+did+we+decide+in+the+latest+product+review+meeting%3F&window=30",
    );
  });

  it("runs evals for the selected domain from the accuracy header", () => {
    useEvalSummary.mockReturnValue({
      isLoading: false,
      isError: false,
      isMock: false,
      data: {
        passRate: 0.72,
        passedCases: 18,
        totalCases: 25,
        threshold: 0.7,
        latestRunAt: "2026-04-01T09:30:00Z",
        domains: [
          { domain: "pricing", passRate: 0.8, passed: 4, total: 5 },
        ],
        metrics: [],
        blockers: [],
      },
      refetch: vi.fn(),
    });

    renderAccuracy({ initialEntries: ["/app/accuracy?domain=pricing"] });

    fireEvent.click(screen.getByRole("button", { name: "Run pricing evals" }));

    expect(mutateRunEvals).toHaveBeenCalledWith({
      domains: ["pricing"],
      passThreshold: 0.7,
    });
  });

  it("shows eval run errors without breaking the page", () => {
    useEvalSummary.mockReturnValue({
      isLoading: false,
      isError: false,
      isMock: false,
      data: {
        passRate: 0.72,
        passedCases: 18,
        totalCases: 25,
        threshold: 0.7,
        latestRunAt: "2026-04-01T09:30:00Z",
        domains: [
          { domain: "pricing", passRate: 0.8, passed: 4, total: 5 },
        ],
        metrics: [],
        blockers: [],
      },
      refetch: vi.fn(),
    });
    useRunEvals.mockReturnValue({
      mutate: mutateRunEvals,
      isPending: false,
      isError: true,
      isSuccess: false,
      error: { detail: "Eval runs are restricted to local/admin access" },
    });

    renderAccuracy({ initialEntries: ["/app/accuracy?domain=pricing"] });

    expect(screen.getByText("Eval runs are restricted to local/admin access")).toBeInTheDocument();
  });
});
