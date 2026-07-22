import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import App from "./App";
import { ThemeProvider } from "./context/ThemeContext";
import { WorkspaceProvider } from "./context/WorkspaceContext";

const appMocks = vi.hoisted(() => ({ workspaces: [] }));

vi.mock("./api/hooks", () => ({
  useWorkspaces: () => ({ data: appMocks.workspaces, isLoading: false }),
}));

vi.mock("./pages/ContextMapPage", () => ({
  default: () => <h1>Explain project</h1>,
}));

vi.mock("./pages/NowPage", async () => {
  const { useState } = await vi.importActual("react");
  return {
    default: () => {
      const [draft, setDraft] = useState("");
      return (
        <>
          <h1>Now page</h1>
          <input aria-label="Transient goal draft" value={draft} onChange={(event) => setDraft(event.target.value)} />
        </>
      );
    },
  };
});

vi.mock("./pages/RunsPage", () => ({
  default: () => <h1>Runs page</h1>,
}));

vi.mock("./pages/SessionLibrary", () => ({
  default: () => <h1>Session library</h1>,
}));

vi.mock("./pages/ProjectMemory", () => ({
  default: () => <h1>Project memory</h1>,
}));

beforeEach(() => {
  appMocks.workspaces = [];
  const values = new Map();
  Object.defineProperty(globalThis, "localStorage", {
    configurable: true,
    value: {
      getItem: (key) => values.get(key) ?? null,
      setItem: (key, value) => values.set(key, String(value)),
      removeItem: (key) => values.delete(key),
    },
  });
});

it("remounts transient product state when the workspace changes", async () => {
  appMocks.workspaces = [
    { id: "workspace-one", name: "Workspace One", kind: "project" },
    { id: "workspace-two", name: "Workspace Two", kind: "project" },
  ];
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <WorkspaceProvider>
          <MemoryRouter initialEntries={["/app"]}>
            <App />
          </MemoryRouter>
        </WorkspaceProvider>
      </ThemeProvider>
    </QueryClientProvider>,
  );

  expect(await screen.findByRole("heading", { name: "Now page" })).toBeInTheDocument();
  fireEvent.click(screen.getAllByRole("button", { name: "Choose workspace" })[0]);
  fireEvent.click(screen.getByRole("menuitemradio", { name: /Workspace One/ }));
  fireEvent.change(screen.getByRole("textbox", { name: "Transient goal draft" }), {
    target: { value: "stale goal from workspace one" },
  });
  expect(screen.getByRole("textbox", { name: "Transient goal draft" })).toHaveValue("stale goal from workspace one");

  fireEvent.click(screen.getAllByRole("button", { name: "Choose workspace" })[0]);
  fireEvent.click(screen.getByRole("menuitemradio", { name: /Workspace Two/ }));

  expect(screen.getByRole("textbox", { name: "Transient goal draft" })).toHaveValue("");
});

it("makes Now the default and exposes the complete product loop", async () => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <WorkspaceProvider>
          <MemoryRouter initialEntries={["/app"]}>
            <App />
          </MemoryRouter>
        </WorkspaceProvider>
      </ThemeProvider>
    </QueryClientProvider>,
  );

  expect(await screen.findByRole("heading", { name: "Now page" })).toBeInTheDocument();
  const expectResponsiveLinks = (name, href) => {
    const links = screen.getAllByRole("link", { name });
    expect(links.length).toBeGreaterThanOrEqual(1);
    links.forEach((link) => expect(link).toHaveAttribute("href", href));
  };
  expectResponsiveLinks("Now", "/app");
  expectResponsiveLinks("Runs", "/app/runs");
  expectResponsiveLinks("Library", "/app/library");
  expectResponsiveLinks("Memory", "/app/memory");
  expectResponsiveLinks("Explain", "/app/explain");
  expectResponsiveLinks("Sources", "/app/sources");
  expectResponsiveLinks("Connectors", "/app/connectors");
  expect(screen.queryByRole("link", { name: "Dashboard" })).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "Graph" })).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "Ask" })).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "Changes" })).not.toBeInTheDocument();
  screen.getAllByRole("navigation", { name: "Application" }).forEach((navigation) => {
    expect(navigation.querySelector('a[aria-label="Prepare"]')).not.toBeInTheDocument();
  });
  expect(screen.queryByText("Work")).not.toBeInTheDocument();
  expect(screen.queryByText("Evidence")).not.toBeInTheDocument();
});

it("redirects legacy Prepare URLs to Now", async () => {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <WorkspaceProvider>
          <MemoryRouter initialEntries={["/app/prepare?objective=Fix%20the%20redirect"]}>
            <App />
          </MemoryRouter>
        </WorkspaceProvider>
      </ThemeProvider>
    </QueryClientProvider>,
  );

  expect(await screen.findByRole("heading", { name: "Now page" })).toBeInTheDocument();
});

it("redirects legacy dashboard and graph routes to their replacement surfaces", async () => {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const { unmount } = render(
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <WorkspaceProvider>
          <MemoryRouter initialEntries={["/app/dashboard"]}>
            <App />
          </MemoryRouter>
        </WorkspaceProvider>
      </ThemeProvider>
    </QueryClientProvider>,
  );
  expect(await screen.findByRole("heading", { name: "Now page" })).toBeInTheDocument();
  unmount();

  render(
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <WorkspaceProvider>
          <MemoryRouter initialEntries={["/app/graph"]}>
            <App />
          </MemoryRouter>
        </WorkspaceProvider>
      </ThemeProvider>
    </QueryClientProvider>,
  );
  expect(await screen.findByRole("heading", { name: "Explain project" })).toBeInTheDocument();
});

it("gives the Explain route a full-height frame", async () => {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <WorkspaceProvider>
          <MemoryRouter initialEntries={["/app/explain"]}>
            <App />
          </MemoryRouter>
        </WorkspaceProvider>
      </ThemeProvider>
    </QueryClientProvider>,
  );

  const heading = await screen.findByRole("heading", { name: "Explain project" });
  expect(heading.closest(".page-enter")).toHaveClass("h-full", "min-h-0");
});

it("collapses the desktop sidebar with an accessible persisted control", async () => {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <WorkspaceProvider>
          <MemoryRouter initialEntries={["/app"]}>
            <App />
          </MemoryRouter>
        </WorkspaceProvider>
      </ThemeProvider>
    </QueryClientProvider>,
  );

  const collapse = await screen.findByRole("button", { name: "Collapse sidebar" });
  expect(collapse).toHaveAttribute("aria-expanded", "true");
  fireEvent.click(collapse);
  const expand = screen.getByRole("button", { name: "Expand sidebar" });
  expect(expand).toHaveAttribute("aria-expanded", "false");
  expect(localStorage.getItem("ce_sidebar_collapsed")).toBe("true");
  expect(screen.getAllByRole("link", { name: "Now" }).length).toBeGreaterThan(0);
});
