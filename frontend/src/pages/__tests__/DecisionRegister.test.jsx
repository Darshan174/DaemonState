import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import DecisionRegister from "../DecisionRegister";

vi.mock("../../api/hooks", () => ({
  useDecisionHistory: vi.fn(),
  useDecisionRegister: vi.fn(),
}));

import { useDecisionHistory, useDecisionRegister } from "../../api/hooks";

function renderDecisionRegister({ initialEntries = ["/app/decisions"] } = {}) {
  return render(
    <MemoryRouter initialEntries={initialEntries}>
      <DecisionRegister />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  useDecisionHistory.mockReturnValue({
    data: {
      entries: [
        {
          id: "sd3-hist",
          title: "Legacy pricing launch date",
          summary: "Historical decision from an older pricing plan.",
          status: "historical",
          sourceLabel: "Pricing Doc",
          author: "Alice",
          createdAt: "2026-03-20T08:00:00Z",
          averageConfidence: 0.8,
        },
      ],
    },
    isLoading: false,
    isError: false,
  });
});

describe("DecisionRegister", () => {
  it("shows loading state", () => {
    useDecisionRegister.mockReturnValue({
      isLoading: true,
      isError: false,
      data: undefined,
      refetch: vi.fn(),
    });

    renderDecisionRegister();

    expect(screen.getByText("Loading...")).toBeInTheDocument();
  });

  it("shows empty state when no decisions exist", () => {
    useDecisionRegister.mockReturnValue({
      isLoading: false,
      isError: false,
      isMock: false,
      data: [],
      refetch: vi.fn(),
    });

    renderDecisionRegister();

    expect(screen.getByText("No decisions have been registered yet.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Connect sources" })).toHaveAttribute(
      "href",
      "/app/connectors",
    );
  });

  it("renders decisions and filters by state", async () => {
    useDecisionRegister.mockReturnValue({
      isLoading: false,
      isError: false,
      isMock: false,
      data: [
        {
          id: "sd1",
          title: "Enterprise pricing moves to $600 per seat",
          summary: "Slack confirmed the pricing change for next quarter.",
          status: "needs_review",
          sourceDocumentId: "sd1",
          sourceLabel: "#pricing",
          author: "Alice",
          connectorType: "slack",
          createdAt: "2026-03-31T08:00:00Z",
          historyAvailable: true,
          modelNames: ["Pricing Strategy"],
          reviewItemIds: ["rq1"],
          rationaleSources: [
            {
              sourceDocumentId: "sd10",
              label: "Weekly Product Review",
              connectorType: "zoom",
              author: "Founder",
              extractedValue: "Launch the pricing page next Tuesday",
            },
            {
              sourceDocumentId: "sd12",
              label: "PR Review #77",
              connectorType: "github",
              author: "maintainer",
              extractedValue: "Ship after PR #13 lands",
            },
          ],
          affectedComponents: [
            { id: "p1", name: "Enterprise Seat Price", modelId: "pricing" },
          ],
          decisionHistory: [
            {
              id: "d1",
              newStatus: "needs_review",
              note: "Conflict generated automatically during ingestion.",
              createdAt: "2026-03-31T08:10:00Z",
            },
          ],
        },
        {
          id: "sd3",
          title: "Adopt SAML over OIDC",
          summary: "Roadmap page records the identity protocol decision.",
          status: "current",
          sourceDocumentId: "sd3",
          sourceLabel: "Engineering Roadmap",
          author: "Bob",
          connectorType: "notion",
          createdAt: "2026-03-30T08:00:00Z",
          historyAvailable: true,
          modelNames: ["Engineering Roadmap"],
          reviewItemIds: [],
          affectedComponents: [
            { id: "r1", name: "SSO Launch Target", modelId: "roadmap" },
          ],
          decisionHistory: [],
        },
      ],
      refetch: vi.fn(),
    });

    renderDecisionRegister();

    expect(screen.getByText("Decisions")).toBeInTheDocument();
    expect(screen.getByText("Current decisions")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Needs review" })).toBeInTheDocument();
    expect(screen.getByText("Enterprise pricing moves to $600 per seat")).toBeInTheDocument();
    expect(screen.getByText("Adopt SAML over OIDC")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open review queue" })).toHaveAttribute(
      "href",
      "/app/review",
    );
    expect(screen.getByRole("link", { name: "Open timeline" })).toHaveAttribute(
      "href",
      "/app/changes",
    );
    expect(screen.getByRole("link", { name: "Open meeting context" })).toHaveAttribute(
      "href",
      "/app/meetings/sd10",
    );
    expect(screen.getByRole("link", { name: "Open engineering trail" })).toHaveAttribute(
      "href",
      "/app/engineering/sd12",
    );
    expect(screen.getAllByRole("link", { name: "Explore graph" })[0]).toHaveAttribute(
      "href",
      "/app/graph?view=local&focus=Enterprise+Seat+Price&q=Enterprise+Seat+Price",
    );

    await userEvent.click(screen.getByRole("button", { name: "Needs review" }));

    expect(screen.getByText("Enterprise pricing moves to $600 per seat")).toBeInTheDocument();
    expect(screen.queryByText("Adopt SAML over OIDC")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open review thread" })).toHaveAttribute(
      "href",
      "/app/review/rq1",
    );

    await userEvent.click(screen.getByRole("button", { name: "Inspect history" }));

    expect(screen.getByText("Decision timeline")).toBeInTheDocument();
    expect(screen.getByText("Legacy pricing launch date")).toBeInTheDocument();
  });
});
