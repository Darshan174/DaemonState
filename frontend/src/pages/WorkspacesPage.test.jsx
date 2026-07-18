import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import WorkspacesPage from "./WorkspacesPage";

const mocks = vi.hoisted(() => ({
  update: vi.fn(),
  remove: vi.fn(),
  create: vi.fn(),
  setSelectedId: vi.fn(),
}));

vi.mock("../api/hooks", () => ({
  useAllWorkspaces: () => ({
    data: [
      { id: "active", name: "Real Project", kind: "project", status: "active", repo_path: "/code/real", source_count: 5, component_count: 12, run_count: 2, connector_count: 1 },
      { id: "demo", name: "Product Tour", kind: "demo", status: "active", source_count: 3, component_count: 8, run_count: 0, connector_count: 0 },
      { id: "archived", name: "Old Project", kind: "project", status: "archived", source_count: 4, component_count: 9, run_count: 1, connector_count: 0 },
    ],
    isLoading: false,
    isError: false,
  }),
  useUpdateWorkspace: () => ({ mutateAsync: mocks.update }),
  useDeleteWorkspace: () => ({ mutateAsync: mocks.remove }),
  useCreateProjectWorkspace: () => ({ mutateAsync: mocks.create, isPending: false }),
}));

vi.mock("../context/WorkspaceContext", () => ({
  useWorkspaceSelection: () => ({ selectedId: "active", setSelectedId: mocks.setSelectedId }),
}));

beforeEach(() => {
  mocks.update.mockReset().mockImplementation(async ({ id, ...body }) => ({ id, ...body }));
  mocks.remove.mockReset().mockResolvedValue(null);
  mocks.create.mockReset();
  mocks.setSelectedId.mockReset();
});

function LocationProbe() {
  const location = useLocation();
  return <output data-testid="location">{location.pathname}</output>;
}

it("opens an active workspace card on its isolated Now page", async () => {
  const user = userEvent.setup();
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter initialEntries={["/app/workspaces"]}>
        <WorkspacesPage />
        <LocationProbe />
      </MemoryRouter>
    </QueryClientProvider>,
  );

  await user.click(screen.getByRole("button", { name: "Open Product Tour" }));

  expect(mocks.setSelectedId).toHaveBeenCalledWith("demo");
  expect(screen.getByTestId("location")).toHaveTextContent("/app");
});

it("manages active, sample, and archived workspaces without mixing their roles", async () => {
  const user = userEvent.setup();
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter><WorkspacesPage /></MemoryRouter>
    </QueryClientProvider>,
  );

  expect(screen.getByRole("heading", { name: /Projects/ })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: /Samples/ })).toBeInTheDocument();
  expect(screen.getByText("Product Tour")).toBeInTheDocument();

  await user.click(within(screen.getByText("Real Project").closest("article")).getByRole("button", { name: "Archive" }));
  await waitFor(() => expect(mocks.update).toHaveBeenCalledWith({ id: "active", status: "archived" }));
  expect(mocks.setSelectedId).toHaveBeenCalledWith(null);

  await user.click(screen.getByRole("button", { name: "Delete" }));
  const permanentDelete = screen.getByRole("button", { name: "Delete permanently" });
  expect(permanentDelete).toBeDisabled();
  await user.type(screen.getByLabelText("Type Old Project to confirm deletion"), "Old Project");
  await user.click(permanentDelete);
  await waitFor(() => expect(mocks.remove).toHaveBeenCalledWith({ id: "archived", confirmName: "Old Project" }));
});
