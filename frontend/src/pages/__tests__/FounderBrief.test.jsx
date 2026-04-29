import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import FounderBrief from "../FounderBrief";

vi.mock("../../api/hooks", () => ({
  useEvalSummary: vi.fn(),
  useFounderBrief: vi.fn(),
  useSourceDocuments: vi.fn(),
}));

import {
  useEvalSummary,
  useFounderBrief,
  useSourceDocuments,
} from "../../api/hooks";

function renderFounderBrief() {
  return render(
    <MemoryRouter>
      <FounderBrief />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  useFounderBrief.mockReturnValue({
    isLoading: false,
    isError: false,
    isMock: false,
    data: {
      changedFacts: [
        {
          componentId: "c1",
          modelId: "pricing",
          modelName: "Pricing Strategy",
          name: "Decision: Pricing page launch",
          value: "Launch the pricing page next Tuesday",
          confidence: 0.92,
          authorityWeight: 0.9,
          validFrom: "2026-03-31T10:00:00Z",
          reviewStatus: null,
          reviewItemId: null,
          sourceLabels: ["Weekly Product Review"],
        },
      ],
      newBlockers: [
        {
          componentId: "c2",
          modelId: "roadmap",
          modelName: "Engineering Roadmap",
          name: "Blocker: pricing page launch",
          value: "Waiting on legal approval",
          confidence: 0.81,
          authorityWeight: 0.7,
          validFrom: "2026-03-31T10:00:00Z",
          reviewStatus: "needs_review",
          reviewItemId: "rq1",
          sourceLabels: ["Weekly Product Review"],
        },
      ],
      openConflicts: [
        {
          reviewItemId: "rq1",
          componentId: "c3",
          componentName: "Enterprise Seat Price",
          status: "needs_review",
          severity: "high",
          kind: "conflict",
          title: "Pricing conflict",
          summary: "Slack and Notion disagree on the current enterprise price.",
          updatedAt: "2026-04-01T08:00:00Z",
        },
      ],
      staleHighRiskItems: [
        {
          componentId: "c4",
          name: "Enterprise Seat Price",
          value: "$600/seat",
          reason: "Current fact still has an open cross-source conflict.",
          confidence: 0.86,
          reviewStatus: "needs_review",
          sourceLabels: ["#pricing", "Pricing Strategy"],
        },
      ],
      recentConnectorFailures: [
        {
          jobId: "job1",
          connectorId: "conn_zoom",
          connectorType: "zoom",
          jobType: "sync",
          failedAt: "2026-04-01T09:00:00Z",
          errorType: "AuthError",
          errorMessage: "Zoom token expired before transcript sync finished.",
        },
      ],
    },
    refetch: vi.fn(),
  });
  useEvalSummary.mockReturnValue({
    isLoading: false,
    isError: false,
    isMock: false,
    data: {
      threshold: 0.7,
      latestRunAt: "2026-04-01T09:30:00Z",
      domains: [
        { domain: "meeting", passRate: 0.6, passed: 3, total: 5 },
      ],
      blockers: ["Meeting domain still depends on a small seeded gold set."],
    },
    refetch: vi.fn(),
  });
  useSourceDocuments.mockReturnValue({
    isLoading: false,
    isError: false,
    isMock: false,
    data: [
      {
        id: "sd12",
        connectorType: "github",
        repository: "acme/context-engine",
        documentTitle: "Review Comment on Pull Request #77: Add eval CLI",
        githubItemType: "pull_request_review_comment",
        author: "maintainer",
        createdAtSource: "2026-04-01T12:45:00Z",
        ingestedAt: "2026-04-01T12:50:00Z",
        processed: true,
        pullRequestReferences: ["acme/context-engine#13"],
        commitReferences: ["abc1234"],
      },
    ],
    refetch: vi.fn(),
  });
});

describe("FounderBrief", () => {
  it("shows loading state", () => {
    useFounderBrief.mockReturnValue({
      isLoading: true,
      isError: false,
      data: undefined,
      refetch: vi.fn(),
    });

    renderFounderBrief();

    expect(screen.getByText("Loading...")).toBeInTheDocument();
  });

  it("shows empty state when nothing is available yet", () => {
    useFounderBrief.mockReturnValue({
      isLoading: false,
      isError: false,
      isMock: false,
      data: null,
      refetch: vi.fn(),
    });
    useEvalSummary.mockReturnValue({
      isLoading: false,
      isError: false,
      isMock: false,
      data: null,
      refetch: vi.fn(),
    });
    useSourceDocuments.mockReturnValue({
      isLoading: false,
      isError: false,
      isMock: false,
      data: [],
      refetch: vi.fn(),
    });

    renderFounderBrief();

    expect(screen.getByText("No founder brief is available yet.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Add context" })).toHaveAttribute(
      "href",
      "/app",
    );
  });

  it("renders the founder brief workflow", () => {
    renderFounderBrief();

    expect(screen.getByText("Workspace Brief")).toBeInTheDocument();
    expect(screen.getByText("Current picture")).toBeInTheDocument();
    expect(screen.getByText("What changed")).toBeInTheDocument();
    expect(screen.getByText("Needs attention")).toBeInTheDocument();
    expect(screen.getByText("Pipeline risk")).toBeInTheDocument();
    expect(screen.getByText("Engineering movement")).toBeInTheDocument();
    expect(screen.getByText("Accuracy watch")).toBeInTheDocument();
    expect(screen.getByText("Decision: Pricing page launch")).toBeInTheDocument();
    expect(screen.getByText("Pricing conflict")).toBeInTheDocument();
    expect(screen.getByText("Zoom token expired before transcript sync finished.")).toBeInTheDocument();
    expect(screen.getByText("Review Comment on Pull Request #77: Add eval CLI")).toBeInTheDocument();
    expect(screen.getByText("Meeting domain still depends on a small seeded gold set.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open engineering trail" })).toHaveAttribute(
      "href",
      "/app/engineering/sd12",
    );
    expect(screen.getByRole("link", { name: "Open timeline" })).toHaveAttribute(
      "href",
      "/app/changes",
    );
    expect(screen.getByRole("link", { name: "Open decision register" })).toHaveAttribute(
      "href",
      "/app/decisions",
    );
  });
});
