import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import SystemHealth from "../SystemHealth";

vi.mock("../../api/hooks", () => ({
  useOperatorStatus: vi.fn(),
}));

import { useOperatorStatus } from "../../api/hooks";

beforeEach(() => {
  vi.clearAllMocks();
});

describe("SystemHealth", () => {
  it("shows loading state", () => {
    useOperatorStatus.mockReturnValue({
      data: undefined,
      isError: false,
      isFetching: false,
      isLoading: true,
      refetch: vi.fn(),
    });

    render(<SystemHealth />);

    expect(screen.getByRole("status")).toHaveTextContent("Loading system status");
  });

  it("shows endpoint unavailable state when the backend route is missing", async () => {
    const refetch = vi.fn();
    useOperatorStatus.mockReturnValue({
      data: undefined,
      error: { status: 404, message: "Not Found" },
      isError: true,
      isFetching: false,
      isLoading: false,
      refetch,
    });

    render(<SystemHealth />);

    expect(screen.getByRole("alert")).toHaveTextContent("Status endpoint unavailable");
    expect(screen.getByText(/api\/operator\/status and \/api\/admin\/status/)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(refetch).toHaveBeenCalledTimes(1);
  });

  it("shows an empty state for an empty status payload", () => {
    useOperatorStatus.mockReturnValue({
      data: { endpoint: "/api/operator/status", data: {} },
      isError: false,
      isFetching: false,
      isLoading: false,
      refetch: vi.fn(),
    });

    render(<SystemHealth />);

    expect(screen.getByText("No status data returned.")).toBeInTheDocument();
    expect(screen.getByText("Endpoint:")).toHaveTextContent("/api/operator/status");
  });

  it("renders status summary, checks, and runtime details", () => {
    useOperatorStatus.mockReturnValue({
      data: {
        endpoint: "/api/operator/status",
        data: {
          status: "degraded",
          summary: "Redis is unavailable; API and database are ready.",
          updated_at: "2026-04-18T09:30:00Z",
          version: "1.0.0-oss",
          uptime_seconds: 7320,
          models: {
            providerApiConfigured: true,
            litellmTimeoutSeconds: 45,
            embedding: {
              provider: "litellm",
              model: "openai/text-embedding-3-large",
              dimensions: 1024,
            },
            extraction: {
              provider: "structured_llm",
              model: "openai/gpt-4.1-mini",
            },
          },
          checks: {
            api: "ok",
            database: { status: "ready", message: "Postgres accepting connections" },
            redis: { status: "failed", error: "Connection refused" },
          },
        },
      },
      isError: false,
      isFetching: false,
      isLoading: false,
      refetch: vi.fn(),
    });

    render(<SystemHealth />);

    expect(screen.getByText("System Health")).toBeInTheDocument();
    expect(screen.getAllByText("Degraded")).toHaveLength(2);
    expect(screen.getByText("2/3")).toBeInTheDocument();
    expect(screen.getByText("Redis")).toBeInTheDocument();
    expect(screen.getByText("Connection refused")).toBeInTheDocument();

    const runtime = screen.getByText("Runtime details").closest("section");
    expect(within(runtime).getByText("Version")).toBeInTheDocument();
    expect(within(runtime).getByText("1.0.0-oss")).toBeInTheDocument();
    expect(within(runtime).getByText("Uptime seconds")).toBeInTheDocument();
    expect(within(runtime).getByText("2h 2m")).toBeInTheDocument();
    expect(within(runtime).getByText("Embedding provider")).toBeInTheDocument();
    expect(within(runtime).getByText("litellm")).toBeInTheDocument();
    expect(within(runtime).getByText("Extraction model")).toBeInTheDocument();
    expect(within(runtime).getByText("openai/gpt-4.1-mini")).toBeInTheDocument();
  });
});
