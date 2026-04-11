import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import KnowledgeGraph from "../KnowledgeGraph";

vi.mock("../../api/hooks", () => ({
  useKnowledgeGraph: vi.fn(),
}));

vi.mock("../../components/GraphVisualizer", () => ({
  default: ({ nodes, edges, selectedNodeId }) => (
    <div data-testid="graph-viz">
      {nodes.length} nodes, {edges.length} edges, selected={selectedNodeId ?? "none"}
    </div>
  ),
}));

vi.mock("../../components/RelationshipEdge", () => ({
  default: ({ sourceLabel, targetLabel, label }) => (
    <div data-testid="rel-edge">
      {sourceLabel} —{label}— {targetLabel}
    </div>
  ),
}));

import { useKnowledgeGraph } from "../../api/hooks";

const mockNodes = [
  { id: "n1", label: "Revenue Model", type: "model", x: 300, y: 200 },
  { id: "n2", label: "Slack #eng", type: "source", x: 120, y: 300 },
  { id: "n3", label: "MRR", type: "component", x: 480, y: 340 },
];
const mockEdges = [
  { source: "n2", target: "n1", label: "feeds" },
  { source: "n1", target: "n3", label: "drives" },
];

beforeEach(() => {
  vi.clearAllMocks();
});

function renderGraph() {
  return render(
    <MemoryRouter>
      <KnowledgeGraph />
    </MemoryRouter>,
  );
}

describe("KnowledgeGraph", () => {
  it("shows loading state", () => {
    useKnowledgeGraph.mockReturnValue({
      data: undefined,
      isMock: false,
      isLoading: true,
      isError: false,
    });

    renderGraph();
    expect(screen.getByText("Loading...")).toBeInTheDocument();
  });

  it("renders graph with MockBadge when mock-backed", () => {
    useKnowledgeGraph.mockReturnValue({
      data: { nodes: mockNodes, edges: mockEdges },
      isMock: true,
      isLoading: false,
      isError: false,
    });

    renderGraph();

    expect(screen.getByText("Graph Explorer")).toBeInTheDocument();
    expect(screen.getByText("How to use this graph")).toBeInTheDocument();
    expect(screen.getByText(/Demo data/)).toBeInTheDocument();
    expect(screen.getByText(/Showing demo data/)).toBeInTheDocument();
    expect(screen.getByTestId("graph-viz")).toHaveTextContent("3 nodes, 2 edges");
    expect(screen.getByText("Inspector")).toBeInTheDocument();
  });

  it("hides MockBadge for real data", () => {
    useKnowledgeGraph.mockReturnValue({
      data: { nodes: mockNodes, edges: mockEdges },
      isMock: false,
      isLoading: false,
      isError: false,
    });

    renderGraph();

    expect(screen.getByText("Graph Explorer")).toBeInTheDocument();
    expect(screen.queryByText(/Demo data/)).not.toBeInTheDocument();
  });

  it("filters nodes by search text", async () => {
    useKnowledgeGraph.mockReturnValue({
      data: { nodes: mockNodes, edges: mockEdges },
      isMock: false,
      isLoading: false,
      isError: false,
    });

    renderGraph();

    await userEvent.type(screen.getByLabelText("Search graph nodes"), "Revenue");

    // Only Revenue Model matches, so MRR and Slack are excluded
    expect(screen.getByTestId("graph-viz")).toHaveTextContent("1 nodes, 0 edges");
  });

  it("filters nodes by type", async () => {
    useKnowledgeGraph.mockReturnValue({
      data: { nodes: mockNodes, edges: mockEdges },
      isMock: false,
      isLoading: false,
      isError: false,
    });

    renderGraph();

    await userEvent.click(screen.getByText("source"));

    // Only Slack #eng is a source
    expect(screen.getByTestId("graph-viz")).toHaveTextContent("1 nodes, 0 edges");
    expect(screen.getByText(/If the graph still looks empty after syncing sources/i)).toBeInTheDocument();
  });

  it("switches to local graph mode when asked", async () => {
    useKnowledgeGraph.mockReturnValue({
      data: { nodes: mockNodes, edges: mockEdges },
      isMock: false,
      isLoading: false,
      isError: false,
    });

    renderGraph();

    await userEvent.click(screen.getByText("Local graph"));

    expect(screen.getByTestId("graph-viz")).toHaveTextContent("3 nodes, 2 edges");
    expect(screen.getByText(/Showing first-degree neighborhood/i)).toBeInTheDocument();
  });

  it("renders edge list", () => {
    useKnowledgeGraph.mockReturnValue({
      data: { nodes: mockNodes, edges: mockEdges },
      isMock: false,
      isLoading: false,
      isError: false,
    });

    renderGraph();

    const edgeTexts = screen
      .getAllByTestId("rel-edge")
      .map((edge) => edge.textContent);
    expect(edgeTexts).toEqual(
      expect.arrayContaining([
        expect.stringContaining("Slack #eng"),
        expect.stringContaining("feeds"),
        expect.stringContaining("Revenue Model"),
      ]),
    );
  });

  it("shows count summary", () => {
    useKnowledgeGraph.mockReturnValue({
      data: { nodes: mockNodes, edges: mockEdges },
      isMock: false,
      isLoading: false,
      isError: false,
    });

    renderGraph();

    expect(screen.getByText(/3\/3 nodes/)).toBeInTheDocument();
    expect(screen.getByText(/2\/2 edges/)).toBeInTheDocument();
  });

  it("shows linked nodes in the inspector", () => {
    useKnowledgeGraph.mockReturnValue({
      data: { nodes: mockNodes, edges: mockEdges },
      isMock: false,
      isLoading: false,
      isError: false,
    });

    renderGraph();

    expect(screen.getByRole("button", { name: "Slack #eng" })).toBeInTheDocument();
  });
});
