import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import Dashboard from "../Dashboard";

vi.mock("../../components/Onboarding", () => ({
  default: () => (
    <div>
      <div>Welcome to Context Engine</div>
      <div>Run Demo Workspace</div>
      <div>Import Local Files</div>
    </div>
  ),
}));

vi.mock("../../api/hooks", () => ({
  useConnectorProcessingSummary: vi.fn(),
  useConnectors: vi.fn(),
  useDashboard: vi.fn(),
  useEvalSummary: vi.fn(),
  useReviewQueue: vi.fn(),
  useSeedDemoData: vi.fn(),
  useUploadSourceFile: vi.fn(),
}));

import {
  useConnectorProcessingSummary,
  useConnectors,
  useDashboard,
  useEvalSummary,
  useReviewQueue,
  useSeedDemoData,
  useUploadSourceFile,
} from "../../api/hooks";

function renderDashboard() {
  return render(
    <MemoryRouter>
      <Dashboard />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  useConnectors.mockReturnValue({
    isLoading: false,
    isError: false,
    isMock: false,
    data: [],
    refetch: vi.fn(),
  });
  useConnectorProcessingSummary.mockReturnValue({
    data: { items: [] },
    refetch: vi.fn(),
  });
  useReviewQueue.mockReturnValue({
    isLoading: false,
    isError: false,
    data: [],
    refetch: vi.fn(),
  });
  useSeedDemoData.mockReturnValue({
    mutate: vi.fn(),
    isPending: false,
  });
  useUploadSourceFile.mockReturnValue({
    mutateAsync: vi.fn(),
    isPending: false,
  });
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
      blockers: ["Meeting domain still depends on a small gold set."],
      metrics: [],
    },
    refetch: vi.fn(),
  });
});

describe("Dashboard", () => {
  it("shows loading state", () => {
    useDashboard.mockReturnValue({
      isLoading: true,
      isError: false,
      data: undefined,
      refetch: vi.fn(),
    });

    const { container } = renderDashboard();
    expect(container.querySelector(".animate-spin")).toBeInTheDocument();
  });

  it("shows workspace summary with data", () => {
    useDashboard.mockReturnValue({
      isLoading: false,
      isError: false,
      data: {
        stats: [
          { label: "Sources", value: 42, delta: "1 connector active" },
          { label: "Models", value: 2, delta: "—" },
          { label: "Components", value: 15, delta: "—" },
          { label: "Relationships", value: 8, delta: "—" },
        ],
        activity: [],
        alerts: [],
      },
      refetch: vi.fn(),
    });

    renderDashboard();
    expect(screen.getByText("Workspace Overview")).toBeInTheDocument();
    expect(screen.getByText(/42 source documents/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "View Founder Brief" })).toHaveAttribute("href", "/app/brief");
    
    expect(screen.getByText("Ask Context")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Ask Context.*Ask a question/i })).toHaveAttribute("href", "/app/query");
    
    expect(screen.getByText("Decision Register")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Decision Register.*Review decisions/i })).toHaveAttribute("href", "/app/decisions");
    
    expect(screen.queryByText("Welcome to Context Engine")).not.toBeInTheDocument();
  });

  it("renders recent changes card and view timeline link", () => {
    useDashboard.mockReturnValue({
      isLoading: false,
      isError: false,
      data: {
        stats: [
          { label: "Sources", value: 4, delta: "1 connector active" },
          { label: "Models", value: 1, delta: "—" },
        ],
        activity: [],
        alerts: [],
      },
      refetch: vi.fn(),
    });

    renderDashboard();

    expect(screen.getByText("Recent Changes")).toBeInTheDocument();
    expect(screen.getByText(/View a single timeline of all workspace context updates/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Recent Changes.*View timeline/i })).toHaveAttribute("href", "/app/changes");
  });

  it("shows onboarding when no sources exist", () => {
    useDashboard.mockReturnValue({
      isLoading: false,
      isError: false,
      data: {
        stats: [{ label: "Sources", value: 0 }],
        activity: [],
      },
      refetch: vi.fn(),
    });

    renderDashboard();
    expect(screen.getByText("Welcome to Context Engine")).toBeInTheDocument();
    expect(screen.getByText("Run Demo Workspace")).toBeInTheDocument();
    expect(screen.getByText("Import Local Files")).toBeInTheDocument();
  });
});
