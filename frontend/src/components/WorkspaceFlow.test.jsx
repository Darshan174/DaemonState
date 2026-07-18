import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import WorkspaceSwitcher from "./WorkspaceSwitcher";
import WorkspaceTopicGate from "./WorkspaceTopicGate";

const mocks = vi.hoisted(() => ({
  createProject: vi.fn(),
  setSelectedId: vi.fn(),
  workspaces: [],
}));

vi.mock("../api/hooks", () => ({
  useWorkspaces: () => ({ data: mocks.workspaces, isLoading: false, isError: false }),
  useCreateProjectWorkspace: () => ({
    mutateAsync: mocks.createProject,
    isPending: false,
  }),
}));

vi.mock("../context/WorkspaceContext", async () => {
  const actual = await vi.importActual("../context/WorkspaceContext");
  return {
    ...actual,
    useWorkspaceSelection: () => ({ selectedId: null, setSelectedId: mocks.setSelectedId }),
  };
});

function LocationProbe() {
  return <output data-testid="location">{useLocation().pathname}</output>;
}

function renderWithProviders(element, initialEntries = ["/app"]) {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter initialEntries={initialEntries}>{element}<LocationProbe /></MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mocks.createProject.mockReset();
  mocks.setSelectedId.mockReset();
  mocks.workspaces = [];
});

describe("workspace entry flow", () => {
  it("separates real projects from sample workspaces in the switcher", async () => {
    mocks.workspaces = [
      { id: "project-1", name: "Actual Product", kind: "project", repo_path: "/code/actual-product" },
      { id: "demo-1", name: "Context Engine Demo", kind: "demo" },
    ];
    renderWithProviders(<WorkspaceSwitcher />, ["/app/prepare?objective=Old%20workspace"]);

    fireEvent.click(screen.getByRole("button", { name: "Choose workspace" }));
    expect(screen.getByText("Projects")).toBeInTheDocument();
    expect(screen.getByText("Samples")).toBeInTheDocument();
    expect(screen.getByText("Sample data")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("menuitemradio", { name: /Actual Product/ }));
    expect(mocks.setSelectedId).toHaveBeenCalledWith("project-1");
    expect(screen.getByTestId("location")).toHaveTextContent("/app");
  });

  it("creates and indexes a repository before selecting its workspace", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    mocks.createProject.mockResolvedValue({
      workspace: { id: "project-2", name: "actual project" },
      repository: { files_indexed: 42 },
    });
    renderWithProviders(<WorkspaceTopicGate workspaces={[]} onSelect={onSelect} />);

    await user.type(screen.getByLabelText(/Local repository path/), "/code/actual-project");
    expect(screen.getByLabelText("Project name")).toHaveValue("actual project");
    await user.click(screen.getByRole("button", { name: "Connect project" }));

    await waitFor(() => expect(mocks.createProject).toHaveBeenCalledWith({
      name: "actual project",
      repo_path: "/code/actual-project",
    }));
    expect(onSelect).toHaveBeenCalledWith("project-2");
  });
});
