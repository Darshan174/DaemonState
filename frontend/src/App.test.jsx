import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import App from "./App";
import { ThemeProvider } from "./context/ThemeContext";
import { WorkspaceProvider } from "./context/WorkspaceContext";

vi.mock("./api/hooks", () => ({
  useWorkspaces: () => ({ data: [], isLoading: false }),
}));

vi.mock("./pages/ContextMapPage", () => ({
  default: () => <h1>Explain project</h1>,
}));

vi.mock("./pages/NowPage", () => ({
  default: () => <h1>Now page</h1>,
}));

vi.mock("./pages/PreparePage", () => ({
  default: () => <h1>Prepare page</h1>,
}));

vi.mock("./pages/RunsPage", () => ({
  default: () => <h1>Runs page</h1>,
}));

beforeEach(() => {
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
  expectResponsiveLinks("Prepare", "/app/prepare");
  expectResponsiveLinks("Runs", "/app/runs");
  expectResponsiveLinks("Explain", "/app/explain");
  expectResponsiveLinks("Sources", "/app/sources");
  expectResponsiveLinks("Connectors", "/app/connectors");
  expect(screen.queryByRole("link", { name: "Dashboard" })).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "Graph" })).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "Ask" })).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "Changes" })).not.toBeInTheDocument();
  expect(screen.queryByText("Work")).not.toBeInTheDocument();
  expect(screen.queryByText("Evidence")).not.toBeInTheDocument();
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
