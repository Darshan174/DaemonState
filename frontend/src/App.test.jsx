import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import App from "./App";
import { ThemeProvider } from "./context/ThemeContext";
import { WorkspaceProvider } from "./context/WorkspaceContext";

vi.mock("./api/hooks", () => ({
  useWorkspaces: () => ({ data: [], isLoading: false }),
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

it("makes objective-first preparation the default app route and keeps inspection routes reachable", async () => {
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

  expect(await screen.findByRole("heading", {
    name: "Compile the evidence your next agent actually needs.",
  })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Prepare" })).toHaveAttribute("href", "/app");
  expect(screen.getByRole("link", { name: "Dashboard" })).toHaveAttribute("href", "/app/dashboard");
  expect(screen.getByRole("link", { name: "Graph" })).toHaveAttribute("href", "/app/graph");
  expect(screen.getByRole("link", { name: "Ask" })).toHaveAttribute("href", "/app/query");
  expect(screen.getByRole("link", { name: "Sources" })).toHaveAttribute("href", "/app/sources");
  expect(screen.getByRole("link", { name: "Connectors" })).toHaveAttribute("href", "/app/connectors");
  expect(screen.getByRole("link", { name: "Changes" })).toHaveAttribute("href", "/app/changes");
  expect(screen.queryByText("Live")).not.toBeInTheDocument();
});
