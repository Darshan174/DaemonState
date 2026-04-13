import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, useLocation } from "react-router-dom";
import { WorkspaceProvider } from "../../context/WorkspaceContext";
import WorkspaceSwitcher from "../WorkspaceSwitcher";

vi.mock("../../api/hooks", () => ({
  useWorkspaces: vi.fn(),
}));

import { useWorkspaces } from "../../api/hooks";

let queryClient;

function renderSwitcher({ initialEntries = ["/"], extra } = {}) {
  queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  vi.spyOn(queryClient, "invalidateQueries");

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={initialEntries}>
        <WorkspaceProvider>
          <WorkspaceSwitcher />
          {extra}
        </WorkspaceProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function LocationDisplay() {
  const loc = useLocation();
  return <div data-testid="location">{loc.pathname}</div>;
}

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
});

describe("WorkspaceSwitcher", () => {
  it("renders nothing when loading", () => {
    useWorkspaces.mockReturnValue({ data: undefined, isLoading: true, isError: false });
    const { container } = renderSwitcher();
    expect(container.querySelector("select")).toBeNull();
  });

  it("renders nothing on error", () => {
    useWorkspaces.mockReturnValue({ data: undefined, isLoading: false, isError: true });
    const { container } = renderSwitcher();
    expect(container.querySelector("select")).toBeNull();
  });

  it("renders dropdown with workspace options", () => {
    useWorkspaces.mockReturnValue({
      data: [
        { id: "ws-1", name: "Alpha" },
        { id: "ws-2", name: "Beta" },
      ],
      isLoading: false,
      isError: false,
    });

    renderSwitcher();

    const select = screen.getByRole("combobox");
    expect(select).toBeInTheDocument();
    expect(screen.getByText("Alpha")).toBeInTheDocument();
    expect(screen.getByText("Beta")).toBeInTheDocument();
  });

  it("requires explicit selection when multiple workspaces exist and nothing is persisted", () => {
    useWorkspaces.mockReturnValue({
      data: [
        { id: "ws-1", name: "Alpha" },
        { id: "ws-2", name: "Beta" },
      ],
      isLoading: false,
      isError: false,
    });

    renderSwitcher();

    const select = screen.getByRole("combobox");
    expect(select).toHaveValue("");
    expect(screen.getByRole("option", { name: "Select workspace" })).toBeDisabled();
  });

  it("auto-selects the only workspace", () => {
    useWorkspaces.mockReturnValue({
      data: [{ id: "ws-1", name: "Alpha" }],
      isLoading: false,
      isError: false,
    });

    renderSwitcher();

    expect(screen.getByRole("combobox")).toHaveValue("ws-1");
    expect(localStorage.getItem("ce:selectedWorkspaceId")).toBe("ws-1");
  });

  it("invalidates workspace-scoped queries on change", async () => {
    useWorkspaces.mockReturnValue({
      data: [
        { id: "ws-1", name: "Alpha" },
        { id: "ws-2", name: "Beta" },
      ],
      isLoading: false,
      isError: false,
    });

    renderSwitcher();

    await userEvent.selectOptions(screen.getByRole("combobox"), "ws-2");

    expect(queryClient.invalidateQueries).toHaveBeenCalledWith({ queryKey: ["dashboard"] });
    expect(queryClient.invalidateQueries).toHaveBeenCalledWith({ queryKey: ["models"] });
    expect(queryClient.invalidateQueries).toHaveBeenCalledWith({ queryKey: ["model"] });
    expect(queryClient.invalidateQueries).toHaveBeenCalledWith({ queryKey: ["model-relationships"] });
  });

  it("persists selection to localStorage", async () => {
    useWorkspaces.mockReturnValue({
      data: [
        { id: "ws-1", name: "Alpha" },
        { id: "ws-2", name: "Beta" },
      ],
      isLoading: false,
      isError: false,
    });

    renderSwitcher();

    await userEvent.selectOptions(screen.getByRole("combobox"), "ws-2");

    expect(localStorage.getItem("ce:selectedWorkspaceId")).toBe("ws-2");
  });

  it("navigates away from model detail page on workspace change", async () => {
    useWorkspaces.mockReturnValue({
      data: [
        { id: "ws-1", name: "Alpha" },
        { id: "ws-2", name: "Beta" },
      ],
      isLoading: false,
      isError: false,
    });

    renderSwitcher({
      initialEntries: ["/app/model/abc-123"],
      extra: <LocationDisplay />,
    });

    expect(screen.getByTestId("location")).toHaveTextContent("/app/model/abc-123");

    await userEvent.selectOptions(screen.getByRole("combobox"), "ws-2");

    expect(screen.getByTestId("location")).toHaveTextContent("/app/models");
  });
});
