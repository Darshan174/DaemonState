import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import ReviewQueue from "../ReviewQueue";

vi.mock("../../api/hooks", () => ({
  useApproveReviewItem: vi.fn(),
  useRejectReviewItem: vi.fn(),
  useReviewQueue: vi.fn(),
  useSupersedeReviewItem: vi.fn(),
}));

import {
  useApproveReviewItem,
  useRejectReviewItem,
  useReviewQueue,
  useSupersedeReviewItem,
} from "../../api/hooks";

const approveMut = {
  mutate: vi.fn(),
  isPending: false,
  variables: undefined,
};

const rejectMut = {
  mutate: vi.fn(),
  isPending: false,
  variables: undefined,
};

const supersedeMut = {
  mutate: vi.fn(),
  isPending: false,
  variables: undefined,
};

const baseItems = [
  {
    id: "rq1",
    status: "needs_review",
    severity: "high",
    kind: "conflict",
    title: "Enterprise pricing changed across Slack and Notion",
    summary: "Slack says $600/seat, Notion still says $500/seat.",
    confidence: 0.58,
    freshness: "2 hr ago",
    lastSeenAt: "2026-03-31T10:00:00Z",
    model: "Pricing Strategy",
    modelId: "pricing",
    sources: ["Slack #pricing", "Notion Pricing Strategy"],
    sourceDocuments: [
      { id: "sd1", label: "#pricing enterprise decision", connectorType: "slack" },
      { id: "sd4", label: "Pricing strategy page", connectorType: "notion" },
    ],
    rationale: "Two high-authority sources disagree on the current price.",
    suggestedAction: "Choose the approved value and mark the old source superseded.",
    decisionHistory: [
      {
        id: "rqd1",
        previousStatus: null,
        newStatus: "needs_review",
        actorType: "system",
        note: "Conflict generated automatically during ingestion.",
        createdAt: "2026-03-31T09:00:00Z",
      },
    ],
  },
  {
    id: "rq2",
    status: "needs_review",
    severity: "medium",
    kind: "low_confidence",
    title: "SSO blocker extracted with low confidence",
    summary: "Blocker appears across Slack and Notion but the exact cause is unclear.",
    confidence: 0.44,
    freshness: "5 hr ago",
    model: "Engineering Roadmap",
    modelId: "roadmap",
    sources: ["Slack #product"],
    sourceDocuments: [
      { id: "sd2", label: "#product SSO blocker thread", connectorType: "slack" },
    ],
    rationale: "The blocker is ambiguous between audit review and procurement timing.",
    suggestedAction: "Confirm the canonical blocker.",
    decisionHistory: [],
  },
  {
    id: "rq3",
    status: "approved",
    severity: "low",
    kind: "fact_update",
    title: "Roadmap decision approved for Q3",
    summary: "The Q3 SSO target is already approved.",
    confidence: 0.92,
    freshness: "1 day ago",
    model: "Engineering Roadmap",
    modelId: "roadmap",
    sources: ["Notion Roadmap"],
    sourceDocuments: [
      { id: "sd3", label: "Engineering Roadmap", connectorType: "notion" },
    ],
    rationale: "No action needed.",
    suggestedAction: "No action needed.",
    decisionHistory: [
      {
        id: "rqd3a",
        previousStatus: "needs_review",
        newStatus: "approved",
        actorType: "human",
        note: "Confirmed against the roadmap page.",
        createdAt: "2026-03-30T10:00:00Z",
      },
    ],
  },
];

function renderReviewQueue(initialEntry = "/app/review") {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route path="/app/review" element={<ReviewQueue />} />
        <Route path="/app/review/:itemId" element={<ReviewQueue />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  approveMut.mutate.mockReset();
  rejectMut.mutate.mockReset();
  supersedeMut.mutate.mockReset();
  useApproveReviewItem.mockReturnValue(approveMut);
  useRejectReviewItem.mockReturnValue(rejectMut);
  useSupersedeReviewItem.mockReturnValue(supersedeMut);
});

describe("ReviewQueue", () => {
  it("shows loading state", () => {
    useReviewQueue.mockReturnValue({
      data: undefined,
      isLoading: true,
      isError: false,
      refetch: vi.fn(),
    });

    renderReviewQueue();
    expect(screen.getByText("Loading...")).toBeInTheDocument();
  });

  it("renders summary counts and selected detail", () => {
    useReviewQueue.mockReturnValue({
      data: baseItems,
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });

    renderReviewQueue();

    const detail = screen.getByRole("region", { name: "Review detail" });
    expect(screen.getByText("Review Queue")).toBeInTheDocument();
    expect(screen.getByText("Self-host review loop")).toBeInTheDocument();
    expect(screen.getByText(/3 matching items/)).toBeInTheDocument();
    expect(within(detail).getByText("Enterprise pricing changed across Slack and Notion")).toBeInTheDocument();
    expect(within(detail).getByText(/Two high-authority sources disagree/)).toBeInTheDocument();
    expect(within(detail).getByText("Slack #pricing")).toBeInTheDocument();
    expect(within(detail).getByText(/Last seen/)).toBeInTheDocument();
    expect(within(detail).getByText("Decision history")).toBeInTheDocument();
    expect(within(detail).getByText("Marked needs review")).toBeInTheDocument();
    expect(within(detail).getByText(/System · /)).toBeInTheDocument();
    expect(within(detail).getByText("Conflict generated automatically during ingestion.")).toBeInTheDocument();
    expect(within(detail).getByRole("link", { name: "Pricing Strategy" })).toHaveAttribute("href", "/app/model/pricing");
    expect(within(detail).getByRole("link", { name: /#pricing enterprise decision/ })).toHaveAttribute("href", "/app/sources/sd1");
  });

  it("renders a full transition in decision history when previous status exists", () => {
    useReviewQueue.mockReturnValue({
      data: baseItems,
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });

    renderReviewQueue("/app/review/rq3");

    const detail = screen.getByRole("region", { name: "Review detail" });
    expect(within(detail).getByText("needs review -> approved")).toBeInTheDocument();
    expect(within(detail).getByText(/Human reviewer/)).toBeInTheDocument();
    expect(within(detail).getByText("Confirmed against the roadmap page.")).toBeInTheDocument();
  });

  it("filters by status and severity", async () => {
    useReviewQueue.mockImplementation(({ status = "all", severity = "all", kind = "all" }) => {
      const filtered = baseItems.filter((item) => {
        const matchesStatus = status === "all" || item.status === status;
        const matchesSeverity = severity === "all" || item.severity === severity;
        const matchesKind = kind === "all" || item.kind === kind;
        return matchesStatus && matchesSeverity && matchesKind;
      });
      return {
        data: filtered,
        isLoading: false,
        isError: false,
        refetch: vi.fn(),
      };
    });

    renderReviewQueue();

    await userEvent.selectOptions(screen.getByLabelText("Filter review queue by status"), "approved");
    expect(
      within(screen.getByRole("region", { name: "Review detail" })).getByText("Roadmap decision approved for Q3"),
    ).toBeInTheDocument();
    expect(screen.queryByText("Enterprise pricing changed across Slack and Notion")).not.toBeInTheDocument();

    await userEvent.selectOptions(screen.getByLabelText("Filter review queue by severity"), "high");
    expect(screen.getByText("No review items match the current filters.")).toBeInTheDocument();
    expect(screen.getByText(/Widen the current filters or inspect the underlying source documents/i)).toBeInTheDocument();
  });

  it("shows an onboarding state when the queue has no items", () => {
    useReviewQueue.mockReturnValue({
      data: [],
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });

    renderReviewQueue();

    expect(screen.getByText("No review items yet.")).toBeInTheDocument();
    expect(screen.getByText(/workspace has not been synced yet/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open sources" })).toHaveAttribute("href", "/app/sources");
  });

  it("filters by type", async () => {
    useReviewQueue.mockImplementation(({ status = "all", severity = "all", kind = "all" }) => {
      const filtered = baseItems.filter((item) => {
        const matchesStatus = status === "all" || item.status === status;
        const matchesSeverity = severity === "all" || item.severity === severity;
        const matchesKind = kind === "all" || item.kind === kind;
        return matchesStatus && matchesSeverity && matchesKind;
      });
      return {
        data: filtered,
        isLoading: false,
        isError: false,
        refetch: vi.fn(),
      };
    });

    renderReviewQueue();

    await userEvent.selectOptions(screen.getByLabelText("Filter review queue by type"), "conflict");

    const detail = screen.getByRole("region", { name: "Review detail" });
    expect(within(detail).getByText("Enterprise pricing changed across Slack and Notion")).toBeInTheDocument();
    expect(screen.queryByText("SSO blocker extracted with low confidence")).not.toBeInTheDocument();
  });

  it("switches selected item when a row is clicked", async () => {
    useReviewQueue.mockReturnValue({
      data: baseItems,
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });

    renderReviewQueue();
    await userEvent.click(screen.getByRole("button", { name: /SSO blocker extracted/i }));

    const detail = screen.getByRole("region", { name: "Review detail" });
    expect(within(detail).getByText("SSO blocker extracted with low confidence")).toBeInTheDocument();
    expect(within(detail).getByText(/Confirm the canonical blocker/)).toBeInTheDocument();
  });

  it("preselects the review item from the route param", () => {
    useReviewQueue.mockReturnValue({
      data: baseItems,
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });

    renderReviewQueue("/app/review/rq2");

    const detail = screen.getByRole("region", { name: "Review detail" });
    expect(within(detail).getByText("SSO blocker extracted with low confidence")).toBeInTheDocument();
  });

  it("initializes filters from the URL search params", () => {
    useReviewQueue.mockImplementation(({ status = "all", severity = "all", kind = "all" }) => {
      const filtered = baseItems.filter((item) => {
        const matchesStatus = status === "all" || item.status === status;
        const matchesSeverity = severity === "all" || item.severity === severity;
        const matchesKind = kind === "all" || item.kind === kind;
        return matchesStatus && matchesSeverity && matchesKind;
      });
      return {
        data: filtered,
        isLoading: false,
        isError: false,
        refetch: vi.fn(),
      };
    });

    renderReviewQueue("/app/review?kind=conflict");

    expect(screen.getByLabelText("Filter review queue by type")).toHaveDisplayValue("Conflict");
    const detail = screen.getByRole("region", { name: "Review detail" });
    expect(within(detail).getByText("Enterprise pricing changed across Slack and Notion")).toBeInTheDocument();
    expect(screen.queryByText("SSO blocker extracted with low confidence")).not.toBeInTheDocument();
  });

  it("shows demo state and disables actions when mock-backed", () => {
    useReviewQueue.mockReturnValue({
      data: baseItems,
      isMock: true,
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });

    renderReviewQueue();

    expect(screen.getByText(/Demo data/)).toBeInTheDocument();
    expect(screen.getByText(/staged in demo mode/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Approve" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Supersede" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Reject" })).toBeDisabled();
  });

  it("calls approve mutation for a live review item", async () => {
    useReviewQueue.mockReturnValue({
      data: baseItems,
      isMock: false,
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });

    renderReviewQueue();
    await userEvent.click(screen.getByRole("button", { name: "Approve" }));

    expect(approveMut.mutate).toHaveBeenCalledWith(
      "rq1",
      expect.objectContaining({
        onSuccess: expect.any(Function),
        onError: expect.any(Function),
      }),
    );
  });

  it("calls reject mutation for a live review item", async () => {
    useReviewQueue.mockReturnValue({
      data: baseItems,
      isMock: false,
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });

    renderReviewQueue();
    await userEvent.click(screen.getByRole("button", { name: "Reject" }));

    expect(rejectMut.mutate).toHaveBeenCalledWith(
      "rq1",
      expect.objectContaining({
        onSuccess: expect.any(Function),
        onError: expect.any(Function),
      }),
    );
  });

  it("calls supersede mutation for a live review item", async () => {
    useReviewQueue.mockReturnValue({
      data: baseItems,
      isMock: false,
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });

    renderReviewQueue();
    await userEvent.click(screen.getByRole("button", { name: "Supersede" }));

    expect(supersedeMut.mutate).toHaveBeenCalledWith(
      "rq1",
      expect.objectContaining({
        onSuccess: expect.any(Function),
        onError: expect.any(Function),
      }),
    );
  });
});
