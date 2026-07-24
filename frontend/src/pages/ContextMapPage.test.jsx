import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ContextMapPage from "./ContextMapPage";


const mocks = vi.hoisted(() => ({
  digest: {
    generated_at: "2026-07-23T12:00:00Z",
    cards: [
      {
        id: "component:11111111-1111-4111-8111-111111111111",
        title: "Current evidence",
        focus_eligible: false,
      },
    ],
    links: [],
    scope: { project_paths: [] },
  },
}));

vi.mock("../api/hooks", () => ({
  useWorkspaces: () => ({
    data: [{ id: "workspace-1", name: "Context engine" }],
    isLoading: false,
  }),
}));

vi.mock("../context/WorkspaceContext", () => ({
  resolveWorkspaceId: (_workspaces, selectedId) => selectedId,
  useWorkspaceSelection: () => ({
    selectedId: "workspace-1",
    setSelectedId: vi.fn(),
  }),
}));

vi.mock("../context-map/api", () => ({
  useBuildContext: () => ({ mutateAsync: vi.fn(), isPending: false, isError: false }),
  useContextDigest: () => ({ data: mocks.digest, isLoading: false, isError: false }),
  useIndexProject: () => ({ mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false, isError: false }),
  useOpenLoops: () => ({ data: null, isLoading: false, isError: false }),
  usePlaybooks: () => ({ data: { items: [] }, isLoading: false }),
  usePrepareContext: () => ({ mutateAsync: vi.fn(), isPending: false, isError: false }),
  useRunTimeline: () => ({ data: null, isLoading: false, isError: false, refetch: vi.fn() }),
  useUpdateOpenLoop: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useUpdatePlaybook: () => ({ mutateAsync: vi.fn(), isPending: false }),
}));

vi.mock("../context-map/components/DigestBoard", () => ({
  default: () => <div data-testid="digest-board">Current evidence map</div>,
}));

vi.mock("../context-map/components/ContextInspector", () => ({
  default: ({ card }) => <div data-testid="context-inspector">{card.title}</div>,
}));

vi.mock("../context-map/components/OpenLoopsPanel", () => ({
  default: () => <div data-testid="open-loops-panel" />,
}));


beforeEach(() => {
  mocks.digest.cards = [
    {
      id: "component:11111111-1111-4111-8111-111111111111",
      title: "Current evidence",
      focus_eligible: false,
    },
  ];
});


describe("ContextMapPage deep links", () => {
  it("shows a recovery panel when a requested evidence record is no longer in the digest", () => {
    render(
      <MemoryRouter initialEntries={["/app/explain?card=component%3Abdb8ac53-de4e-4bd9-8d2a-aa0400fa5000"]}>
        <ContextMapPage />
      </MemoryRouter>,
    );

    expect(screen.getByTestId("digest-board")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Evidence record unavailable" })).toBeInTheDocument();
    expect(screen.getByText(/superseded, archived, or filtered/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Return to current evidence" }));

    expect(screen.queryByRole("heading", { name: "Evidence record unavailable" })).not.toBeInTheDocument();
    expect(screen.getByTestId("digest-board")).toBeInTheDocument();
  });

  it("opens the inspector when the requested evidence record is current", async () => {
    render(
      <MemoryRouter initialEntries={["/app/explain?card=component%3A11111111-1111-4111-8111-111111111111"]}>
        <ContextMapPage />
      </MemoryRouter>,
    );

    expect(await screen.findByTestId("context-inspector")).toHaveTextContent("Current evidence");
    expect(screen.queryByRole("heading", { name: "Evidence record unavailable" })).not.toBeInTheDocument();
  });
});
