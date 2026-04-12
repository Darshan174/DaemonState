import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import Changes from "../Changes";

vi.mock("../../api/hooks", () => ({
  useTimeline: vi.fn(),
}));

import { useTimeline } from "../../api/hooks";

function renderChanges({ initialEntries = ["/app/changes"] } = {}) {
  return render(
    <MemoryRouter initialEntries={initialEntries}>
      <Changes />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  useTimeline.mockReturnValue({
    isLoading: false,
    isError: false,
    isMock: false,
    hasMore: false,
    fetchNextPage: vi.fn(),
    isFetchingNextPage: false,
    data: {
      generatedAt: "2026-04-02T10:00:00Z",
      totalEvents: 4,
      hasMore: false,
      nextCursor: null,
      items: [
        {
          id: "decision-1",
          type: "decision",
          occurredAt: "2026-03-31T10:00:00Z",
          title: "Launch the pricing page next Tuesday",
          summary: "Decision captured in the product review meeting.",
          status: "current",
          sourceDocumentId: "sd10",
          sourceLabel: "Weekly Product Review",
          modelName: "Launch Decisions",
        },
        {
          id: "review-1",
          type: "review",
          occurredAt: "2026-03-31T11:00:00Z",
          title: "Pricing conflict",
          summary: "needs review -> approved — Conflict resolved by operator.",
          status: "approved",
          reviewItemId: "rq1",
          modelName: "Pricing",
        },
        {
          id: "source-1",
          type: "source",
          occurredAt: "2026-03-31T10:16:00Z",
          title: "Weekly Product Review transcript ingested",
          summary: "Stored and processed into structured context.",
          status: "processed",
          sourceDocumentId: "sd10",
          connectorType: "zoom",
          sourceLabel: "Weekly Product Review",
        },
        {
          id: "connector-1",
          type: "connector",
          occurredAt: "2026-03-31T12:00:00Z",
          title: "Zoom connector",
          summary: "Connector health needs attention before new context can be trusted.",
          status: "error",
          connectorType: "zoom",
        },
      ],
    },
    refetch: vi.fn(),
  });
});

describe("Changes", () => {
  it("shows loading state", () => {
    useTimeline.mockReturnValue({
      isLoading: true,
      isError: false,
      isMock: false,
      hasMore: false,
      fetchNextPage: vi.fn(),
      isFetchingNextPage: false,
      data: { generatedAt: null, totalEvents: 0, hasMore: false, nextCursor: null, items: [] },
      refetch: vi.fn(),
    });

    renderChanges();

    expect(screen.getByText("Loading...")).toBeInTheDocument();
  });

  it("shows empty state when there is no timeline data", () => {
    useTimeline.mockReturnValue({
      isLoading: false,
      isError: false,
      isMock: false,
      hasMore: false,
      fetchNextPage: vi.fn(),
      isFetchingNextPage: false,
      data: { generatedAt: "2026-04-02T10:00:00Z", totalEvents: 0, hasMore: false, nextCursor: null, items: [] },
      refetch: vi.fn(),
    });

    renderChanges();

    expect(screen.getByText("No changes are visible yet.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Add context" })).toHaveAttribute(
      "href",
      "/app",
    );
  });

  it("renders the timeline and filters by type", async () => {
    renderChanges();

    expect(screen.getByText("Changes")).toBeInTheDocument();
    expect(screen.getByText("Launch the pricing page next Tuesday")).toBeInTheDocument();
    expect(screen.getByText("Pricing conflict")).toBeInTheDocument();
    expect(screen.getByText("Weekly Product Review transcript ingested")).toBeInTheDocument();
    expect(screen.getByText("Zoom connector")).toBeInTheDocument();
    expect(screen.getByText(/4 recent events/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open founder brief" })).toHaveAttribute(
      "href",
      "/app/brief",
    );
    expect(screen.getAllByRole("link", { name: "Explore graph" })[0]).toHaveAttribute(
      "href",
      "/app/graph?view=local&focus=Launch+Decisions&q=Launch+Decisions",
    );

    await userEvent.click(screen.getByRole("button", { name: /Decisions\s*1/i }));

    expect(screen.getByText("Launch the pricing page next Tuesday")).toBeInTheDocument();
    expect(screen.queryByText("Pricing conflict")).not.toBeInTheDocument();
    expect(screen.queryByText("Zoom connector")).not.toBeInTheDocument();
  });

  it("shows a load more button when the backend has more timeline pages", async () => {
    const fetchNextPage = vi.fn();
    useTimeline.mockReturnValue({
      isLoading: false,
      isError: false,
      isMock: false,
      hasMore: true,
      fetchNextPage,
      isFetchingNextPage: false,
      data: {
        generatedAt: "2026-04-02T10:00:00Z",
        totalEvents: 4,
        hasMore: true,
        nextCursor: "cursor-2",
        items: [
          {
            id: "decision-1",
            type: "decision",
            occurredAt: "2026-03-31T10:00:00Z",
            title: "Launch the pricing page next Tuesday",
            summary: "Decision captured in the product review meeting.",
            status: "current",
            sourceDocumentId: "sd10",
          },
        ],
      },
      refetch: vi.fn(),
    });

    renderChanges();

    await userEvent.click(screen.getByRole("button", { name: "Load more changes" }));

    expect(fetchNextPage).toHaveBeenCalledTimes(1);
  });
});
