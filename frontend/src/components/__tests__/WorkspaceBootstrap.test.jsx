import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { WorkspaceProvider } from "../../context/WorkspaceContext";
import WorkspaceBootstrap from "../WorkspaceBootstrap";

vi.mock("../../api/hooks", () => ({
  useWorkspaces: vi.fn(),
  useCreateWorkspace: vi.fn(),
}));

import { useWorkspaces, useCreateWorkspace } from "../../api/hooks";

const defaultCreateMut = {
  mutate: vi.fn(),
  isPending: false,
  isError: false,
  error: null,
};

function renderBootstrap(children = <div>App Content</div>) {
  return render(
    <WorkspaceProvider>
      <WorkspaceBootstrap>{children}</WorkspaceBootstrap>
    </WorkspaceProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  useCreateWorkspace.mockReturnValue(defaultCreateMut);
  localStorage.clear();
});

describe("WorkspaceBootstrap", () => {
  it("shows loading state while fetching workspaces", () => {
    useWorkspaces.mockReturnValue({
      data: undefined,
      isLoading: true,
      isError: false,
      error: null,
      refetch: vi.fn(),
    });

    renderBootstrap();

    expect(container.querySelector(".animate-spin")).toBeInTheDocument();
    expect(screen.queryByText("App Content")).not.toBeInTheDocument();
  });

  it("renders children when workspaces exist", () => {
    useWorkspaces.mockReturnValue({
      data: [{ id: "ws-1", name: "Test" }],
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    });

    renderBootstrap();

    expect(screen.getByText("App Content")).toBeInTheDocument();
  });

  it("passes through on network error (no status) for mock fallback", () => {
    useWorkspaces.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: true,
      error: new TypeError("Failed to fetch"),
      refetch: vi.fn(),
    });

    renderBootstrap();

    expect(screen.getByText("App Content")).toBeInTheDocument();
  });

  it("shows error screen on server error (has status)", async () => {
    const refetch = vi.fn();
    const err = new Error("Internal Server Error");
    err.status = 500;

    useWorkspaces.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: true,
      error: err,
      refetch,
    });

    renderBootstrap();

    expect(screen.getByText("Failed to load workspaces")).toBeInTheDocument();
    expect(screen.queryByText("App Content")).not.toBeInTheDocument();

    await userEvent.click(screen.getByText("Retry"));
    expect(refetch).toHaveBeenCalled();
  });

  it("shows creation form when no workspaces exist", () => {
    useWorkspaces.mockReturnValue({
      data: [],
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    });

    renderBootstrap();

    expect(screen.getByText("Create Workspace")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("e.g. Acme Corp")).toBeInTheDocument();
    expect(screen.queryByText("App Content")).not.toBeInTheDocument();
  });

  it("disables submit when name is empty", () => {
    useWorkspaces.mockReturnValue({
      data: [],
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    });

    renderBootstrap();

    expect(screen.getByRole("button", { name: /Create Workspace/ })).toBeDisabled();
  });

  it("submits creation form with name", async () => {
    const mutate = vi.fn();
    useCreateWorkspace.mockReturnValue({ ...defaultCreateMut, mutate });
    useWorkspaces.mockReturnValue({
      data: [],
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    });

    renderBootstrap();

    await userEvent.type(screen.getByPlaceholderText("e.g. Acme Corp"), "Acme Corp");
    await userEvent.click(screen.getByRole("button", { name: /Create Workspace/ }));

    expect(mutate).toHaveBeenCalledWith(
      { name: "Acme Corp" },
      expect.objectContaining({ onSuccess: expect.any(Function) }),
    );
  });

  it("shows pending state during creation", () => {
    useCreateWorkspace.mockReturnValue({ ...defaultCreateMut, isPending: true });
    useWorkspaces.mockReturnValue({
      data: [],
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    });

    renderBootstrap();

    expect(screen.getByText("Initializing...")).toBeInTheDocument();
  });
});
