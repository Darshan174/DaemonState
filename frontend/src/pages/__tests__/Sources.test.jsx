import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import Sources from "../Sources";

vi.mock("../../api/hooks", () => ({
  useConnectorProcessingSummary: vi.fn(),
  useReprocessSourceDocument: vi.fn(),
  useSourceDocument: vi.fn(),
  useSourceDocumentComponents: vi.fn(),
  useSourceDocumentReviewItems: vi.fn(),
  useSourceDocuments: vi.fn(),
}));

import {
  useConnectorProcessingSummary,
  useReprocessSourceDocument,
  useSourceDocument,
  useSourceDocumentComponents,
  useSourceDocumentReviewItems,
  useSourceDocuments,
} from "../../api/hooks";

const reprocessMut = {
  mutate: vi.fn(),
  isPending: false,
  variables: undefined,
};

const baseDocuments = [
  {
    id: "sd1",
    connectorType: "slack",
    externalId: "C-price:1",
    author: "Alice",
    content: "decision: enterprise pricing moves to $600/seat",
    preview: "decision: enterprise pricing moves to $600/seat",
    sourceUrl: "https://slack.com/doc/1",
    createdAtSource: "2026-03-29T09:20:00Z",
    ingestedAt: "2026-03-29T09:22:00Z",
    processedAt: "2026-03-29T09:23:00Z",
    processed: true,
    location: "#pricing",
  },
  {
    id: "sd2",
    connectorType: "slack",
    externalId: "C-prod:2",
    author: "Rahul",
    content: "blocker: SSO rollout is blocked by audit review",
    preview: "blocker: SSO rollout is blocked by audit review",
    sourceUrl: "https://slack.com/doc/2",
    createdAtSource: "2026-03-29T10:20:00Z",
    ingestedAt: "2026-03-29T10:21:00Z",
    processedAt: null,
    processed: false,
    location: "#product",
  },
  {
    id: "sd3",
    connectorType: "notion",
    externalId: "notion:page-1",
    author: "alice@example.com",
    content: "Engineering Roadmap\n\nWe are targeting Q3 for the SSO launch.",
    preview: "Engineering Roadmap",
    sourceUrl: "https://notion.so/page-1",
    createdAtSource: "2026-03-28T10:00:00Z",
    ingestedAt: "2026-03-29T14:05:00Z",
    processedAt: "2026-03-29T14:06:00Z",
    processed: true,
    location: "Engineering Roadmap",
  },
  {
    id: "sd4",
    connectorType: "zoom",
    externalId: "zoom:987654321:transcript-file-1",
    author: "founder@example.com",
    content:
      "Meeting: Weekly Product Review\nHost: founder@example.com\nParticipants: Founder, Ops\n\nFounder: decision: Launch the pricing page next Tuesday.",
    preview: "Meeting: Weekly Product Review",
    sourceUrl: "https://zoom.us/rec/play/transcript-file-1",
    createdAtSource: "2026-03-31T10:00:05Z",
    ingestedAt: "2026-03-31T10:16:00Z",
    processedAt: "2026-03-31T10:18:00Z",
    processed: true,
    location: "Weekly Product Review",
    meetingTopic: "Weekly Product Review",
    host: "founder@example.com",
    participants: ["Founder", "Ops"],
    recordingDate: "2026-03-31",
    sourceType: "zoom_transcript",
  },
  {
    id: "sd5",
    connectorType: "github",
    externalId: "github:acme/context-engine:pull_review_comment:8001",
    author: "maintainer",
    content:
      "Repository: acme/context-engine\nReview Comment on Pull Request #77: Add eval CLI\n\ndecision: ship after PR #13 and commit abc1234.",
    preview: "Review Comment on Pull Request #77: Add eval CLI",
    sourceUrl: "https://github.com/acme/context-engine/pull/77#discussion_r8001",
    createdAtSource: "2026-04-01T12:45:00Z",
    ingestedAt: "2026-04-01T12:50:00Z",
    processedAt: "2026-04-01T12:52:00Z",
    processed: true,
    location: "acme/context-engine",
    repository: "acme/context-engine",
    documentTitle: "Review Comment on Pull Request #77: Add eval CLI",
    githubItemType: "pull_request_review_comment",
    parentExternalId: "github:acme/context-engine:pull_request:77",
    pullRequestReferences: ["acme/context-engine#13"],
    commitReferences: ["abc1234"],
    sourceType: "github_pull_request_review_comment",
  },
];

function renderSources(initialEntries = ["/app/sources"]) {
  return render(
    <MemoryRouter initialEntries={initialEntries}>
      <Routes>
        <Route path="/app/sources" element={<Sources />} />
        <Route path="/app/sources/:documentId" element={<Sources />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  reprocessMut.mutate.mockReset();
  useReprocessSourceDocument.mockReturnValue(reprocessMut);
  useConnectorProcessingSummary.mockReturnValue({
    data: {
      items: [
        {
          connectorType: "slack",
          status: "connected",
          totalDocuments: 2,
          processedDocuments: 1,
          unprocessedDocuments: 1,
          lastSyncAt: "Mar 29, 2026, 3:51 PM",
        },
      ],
    },
  });
  useSourceDocument.mockReturnValue({
    data: null,
    isLoading: false,
    isError: false,
  });
  useSourceDocumentComponents.mockReturnValue({
    data: [],
    isLoading: false,
    isError: false,
  });
  useSourceDocumentReviewItems.mockReturnValue({
    data: [],
    isLoading: false,
    isError: false,
  });
});

describe("Sources", () => {
  it("shows loading state", () => {
    useSourceDocuments.mockReturnValue({
      data: undefined,
      isMock: false,
      isLoading: true,
      isError: false,
      refetch: vi.fn(),
    });

    renderSources();
    expect(screen.getByText("Loading...")).toBeInTheDocument();
  });

  it("shows a self-host onboarding state when no sources exist yet", () => {
    useSourceDocuments.mockReturnValue({
      data: [],
      isMock: false,
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });

    renderSources();

    expect(screen.getByText("No source documents yet.")).toBeInTheDocument();
    expect(screen.getByText(/connect Slack, Notion, or Zoom first/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Add context" })).toHaveAttribute("href", "/app");
  });

  it("renders mock badge, summary, and selected document detail", () => {
    useSourceDocuments.mockReturnValue({
      data: baseDocuments,
      isMock: true,
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });

    renderSources();

    const detail = screen.getByRole("region", { name: "Document detail" });

    expect(screen.getByText("Sources")).toBeInTheDocument();
    expect(screen.getByText(/Demo data/)).toBeInTheDocument();
    expect(screen.getByText(/5 stored · 4 processed · 1 pending/)).toBeInTheDocument();
    expect(within(detail).getByText("Alice")).toBeInTheDocument();
    expect(within(detail).getByText("Raw content")).toBeInTheDocument();
    expect(within(detail).getByRole("link", { name: "Explore graph" })).toHaveAttribute(
      "href",
      "/app/graph?view=local&focus=%23pricing&q=%23pricing",
    );
    expect(
      within(detail).getByText(/enterprise pricing moves to \$600\/seat/),
    ).toBeInTheDocument();
    expect(screen.getByText("1 processed · 1 pending")).toBeInTheDocument();
  });

  it("shows component and review backlinks for the selected document", () => {
    useSourceDocuments.mockReturnValue({
      data: baseDocuments,
      isMock: true,
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });
    useSourceDocumentComponents.mockReturnValue({
      data: [
        {
          id: "p1",
          name: "Enterprise Seat Price",
          value: "$600/seat",
          modelId: "pricing",
          modelName: "Pricing Strategy",
          reviewStatus: "needs_review",
          reviewSummary: "Finance still needs final confirmation.",
          temporalState: "historical",
          validFrom: "2026-03-20T00:00:00Z",
          validTo: "2026-03-29T00:00:00Z",
        },
      ],
      isLoading: false,
      isError: false,
    });
    useSourceDocumentReviewItems.mockReturnValue({
      data: [
        {
          id: "rq1",
          title: "Enterprise pricing changed across Slack and Notion",
          kind: "conflict",
          model: "Pricing Strategy",
          status: "needs_review",
          decisionHistory: [
            {
              id: "rqd1",
              previousStatus: null,
              newStatus: "needs_review",
              actorType: "system",
              note: "Conflict generated automatically during ingestion.",
              createdAt: "2026-03-29T09:30:00Z",
            },
            {
              id: "rqd2",
              previousStatus: "needs_review",
              newStatus: "approved",
              actorType: "human",
              note: "Finance confirmed the new price.",
              createdAt: "2026-03-29T10:00:00Z",
            },
          ],
        },
      ],
      isLoading: false,
      isError: false,
    });

    renderSources(["/app/sources/sd1"]);

    const detail = screen.getByRole("region", { name: "Document detail" });
    expect(within(detail).getByText("Used in components")).toBeInTheDocument();
    expect(
      within(detail)
        .getAllByRole("link")
        .find((link) => link.getAttribute("href") === "/app/model/pricing"),
    ).toBeTruthy();
    expect(within(detail).getByText("Related review items")).toBeInTheDocument();
    expect(
      within(detail).getByRole("link", { name: /Enterprise pricing changed across Slack and Notion/ }),
    ).toHaveAttribute("href", "/app/review/rq1");
    expect(within(detail).getByText(/Historical version/)).toBeInTheDocument();
    expect(within(detail).getByText(/Finance still needs final confirmation/)).toBeInTheDocument();
    expect(within(detail).getByText("Decision history")).toBeInTheDocument();
    expect(within(detail).getByText("Marked needs review")).toBeInTheDocument();
    expect(within(detail).getByText("needs review -> approved")).toBeInTheDocument();
    expect(within(detail).getByText("Conflict generated automatically during ingestion.")).toBeInTheDocument();
    expect(within(detail).getByText("Finance confirmed the new price.")).toBeInTheDocument();
    expect(within(detail).getByRole("link", { name: "Explore Enterprise Seat Price in graph" })).toHaveAttribute(
      "href",
      "/app/graph?view=local&focus=Enterprise+Seat+Price&q=Enterprise+Seat+Price",
    );
  });

  it("renders transcript metadata for Zoom source documents", () => {
    useSourceDocuments.mockReturnValue({
      data: baseDocuments,
      isMock: false,
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
      hasMore: false,
      fetchNextPage: vi.fn(),
      isFetchingNextPage: false,
      total: baseDocuments.length,
    });

    renderSources(["/app/sources/sd4"]);

    const detail = screen.getByRole("region", { name: "Document detail" });
    expect(within(detail).getByText("zoom")).toBeInTheDocument();
    expect(within(detail).getAllByText("Weekly Product Review")).toHaveLength(2);
    expect(within(detail).getAllByText("founder@example.com")).toHaveLength(2);
    expect(within(detail).getByText("Founder, Ops")).toBeInTheDocument();
    expect(within(detail).getByText("zoom transcript")).toBeInTheDocument();
  });

  it("renders GitHub metadata for engineering source documents", () => {
    useSourceDocuments.mockReturnValue({
      data: baseDocuments,
      isMock: false,
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
      hasMore: false,
      fetchNextPage: vi.fn(),
      isFetchingNextPage: false,
      total: baseDocuments.length,
    });

    renderSources(["/app/sources/sd5"]);

    const detail = screen.getByRole("region", { name: "Document detail" });
    expect(within(detail).getByText("github")).toBeInTheDocument();
    expect(within(detail).getAllByText("acme/context-engine")).toHaveLength(2);
    expect(within(detail).getByText("Review Comment on Pull Request #77: Add eval CLI")).toBeInTheDocument();
    expect(within(detail).getByText("pull request review comment")).toBeInTheDocument();
    expect(within(detail).getByText("acme/context-engine#13")).toBeInTheDocument();
    expect(within(detail).getByText("abc1234")).toBeInTheDocument();
  });

  it("queues reprocess for a live source document", async () => {
    const mutate = vi.fn((_documentId, opts) => {
      opts.onSuccess({ jobType: "reprocess", status: "pending" });
    });
    useReprocessSourceDocument.mockReturnValue({
      ...reprocessMut,
      mutate,
    });
    useSourceDocuments.mockReturnValue({
      data: baseDocuments,
      isMock: false,
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });

    renderSources(["/app/sources/sd1"]);

    await userEvent.click(screen.getByRole("button", { name: "Reprocess" }));

    expect(mutate).toHaveBeenCalledWith(
      "sd1",
      expect.objectContaining({
        onSuccess: expect.any(Function),
        onError: expect.any(Function),
      }),
    );
    expect(screen.getByText(/Reprocess queued as pending/i)).toBeInTheDocument();
  });

  it("filters by connector and processing state", async () => {
    useSourceDocuments.mockImplementation(({ connector = "all", processed = "all" }) => {
      const filtered = baseDocuments.filter((doc) => {
        const matchesConnector = connector === "all" || doc.connectorType === connector;
        const matchesProcessed =
          processed === "all" ||
          (processed === "processed" && doc.processed) ||
          (processed === "unprocessed" && !doc.processed);
        return matchesConnector && matchesProcessed;
      });
      return {
        data: filtered,
        isMock: false,
        isLoading: false,
        isError: false,
        refetch: vi.fn(),
      };
    });

    renderSources();

    await userEvent.selectOptions(
      screen.getByLabelText("Filter source documents by connector"),
      "notion",
    );
    await waitFor(() => {
      expect(
        within(screen.getByRole("region", { name: "Document detail" })).getByText("alice@example.com"),
      ).toBeInTheDocument();
    });
    expect(screen.queryByText("Rahul")).not.toBeInTheDocument();

    await userEvent.selectOptions(
      screen.getByLabelText("Filter source documents by processing state"),
      "unprocessed",
    );
    expect(screen.getByText("No source documents match the current filters.")).toBeInTheDocument();
    expect(screen.getByText(/Widen the current filters or sync another source/i)).toBeInTheDocument();
  });

  it("filters by search text", async () => {
    useSourceDocuments.mockImplementation(({ search = "" }) => {
      const q = search.trim().toLowerCase();
      const filtered = !q
        ? baseDocuments
        : baseDocuments.filter((doc) =>
            [doc.author, doc.content, doc.location].join(" ").toLowerCase().includes(q),
          );
      return {
        data: filtered,
        isMock: false,
        isLoading: false,
        isError: false,
        refetch: vi.fn(),
      };
    });

    renderSources();

    await userEvent.type(screen.getByLabelText("Search source documents"), "roadmap");

    await waitFor(() => {
      expect(
        within(screen.getByRole("region", { name: "Document detail" })).getByText("alice@example.com"),
      ).toBeInTheDocument();
    });
    expect(screen.queryByText("Rahul")).not.toBeInTheDocument();
  });

  it("switches selected document when a row is clicked", async () => {
    useSourceDocuments.mockReturnValue({
      data: baseDocuments,
      isMock: false,
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });

    renderSources(["/app/sources/sd1"]);

    await userEvent.click(screen.getByRole("button", { name: /Rahul/i }));

    const detail = screen.getByRole("region", { name: "Document detail" });

    expect(within(detail).getByText("Pending extraction")).toBeInTheDocument();
    expect(
      within(detail).getByText(/SSO rollout is blocked by audit review/),
    ).toBeInTheDocument();
  });

  it("loads a detail route even when the document is not in the current page", () => {
    useSourceDocuments.mockReturnValue({
      data: [baseDocuments[0]],
      total: 1,
      hasMore: false,
      fetchNextPage: vi.fn(),
      isFetchingNextPage: false,
      isMock: false,
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });
    useSourceDocument.mockReturnValue({
      data: baseDocuments[2],
      isLoading: false,
      isError: false,
    });

    renderSources(["/app/sources/sd3"]);

    const detail = screen.getByRole("region", { name: "Document detail" });
    expect(within(detail).getByText("alice@example.com")).toBeInTheDocument();
    expect(within(detail).getByText("Open original source")).toHaveAttribute(
      "href",
      "https://notion.so/page-1",
    );
  });

  it("loads more documents when pagination is available", async () => {
    const fetchNextPage = vi.fn();
    useSourceDocuments.mockReturnValue({
      data: baseDocuments.slice(0, 2),
      total: 6,
      hasMore: true,
      fetchNextPage,
      isFetchingNextPage: false,
      isMock: false,
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });

    renderSources(["/app/sources/sd1"]);

    await userEvent.click(screen.getByRole("button", { name: "Load more documents" }));
    expect(fetchNextPage).toHaveBeenCalled();
  });
});
