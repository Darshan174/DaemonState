import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import App from "./App";
import { ThemeProvider } from "./context/ThemeContext";
import { WorkspaceProvider } from "./context/WorkspaceContext";

const appMocks = vi.hoisted(() => ({
  workspaces: [],
  nowError: false,
}));

vi.mock("./api/hooks", () => ({
  useWorkspaces: () => ({ data: appMocks.workspaces, isLoading: false }),
}));

vi.mock("./pages/ContextMapPage", () => ({
  default: () => <h1>Explain project</h1>,
}));

vi.mock("./pages/NowPage", async () => {
  const { useState } = await vi.importActual("react");
  const { useLocation } = await vi.importActual("react-router-dom");
  return {
    default: () => {
      if (appMocks.nowError) {
        throw new Error("Now route render failed");
      }
      const [draft, setDraft] = useState("");
      const location = useLocation();
      return (
        <>
          <h1>Now page</h1>
          <input aria-label="Transient goal draft" value={draft} onChange={(event) => setDraft(event.target.value)} />
          <span data-testid="now-search">{location.search}</span>
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

vi.mock("./pages/MemoryNow", () => ({
  default: () => <h1>Memory now</h1>,
}));

vi.mock("./pages/ProjectMemory", async () => {
  const { useLocation } = await vi.importActual("react-router-dom");
  return {
    default: () => {
      const location = useLocation();
      return (
        <>
          <h1>Project memory</h1>
          <span data-testid="memory-inspector-search">{location.search}</span>
        </>
      );
    },
  };
});

beforeEach(() => {
  appMocks.workspaces = [];
  appMocks.nowError = false;
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

it("contains a route render failure and lets the user recover without losing the shell", async () => {
  const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
  const preventExpectedWindowError = (event) => {
    if (event.error?.message === "Now route render failed") {
      event.preventDefault();
    }
  };
  window.addEventListener("error", preventExpectedWindowError);
  appMocks.nowError = true;
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });

  try {
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

    const recovery = await screen.findByRole("alert");
    expect(within(recovery).getByRole("heading", {
      name: "This view could not be opened",
    })).toBeInTheDocument();
    expect(within(recovery).getByText(/workspace and saved context are still intact/i)).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "Continue" }).length).toBeGreaterThan(0);

    appMocks.nowError = false;
    fireEvent.click(within(recovery).getByRole("button", {
      name: "Try this view again",
    }));

    expect(await screen.findByRole("heading", { name: "Now page" })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  } finally {
    window.removeEventListener("error", preventExpectedWindowError);
    consoleError.mockRestore();
  }
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

it("makes Continue the default and groups inspection history separately", async () => {
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
  expectResponsiveLinks("Continue", "/app");
  expectResponsiveLinks("Library", "/app/library");
  expectResponsiveLinks("History", "/app/runs");
  expectResponsiveLinks("Memory", "/app/memory");
  expectResponsiveLinks("Evidence", "/app/explain");
  expectResponsiveLinks("Sources", "/app/sources");
  expectResponsiveLinks("Integrations", "/app/connectors");
  expect(screen.queryByRole("link", { name: "Runs" })).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "Explain" })).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "Connectors" })).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "Dashboard" })).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "Graph" })).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "Ask" })).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "Changes" })).not.toBeInTheDocument();
  expect(screen.queryByRole("region", { name: "Continuity loop" })).not.toBeInTheDocument();

  const mobileNavigation = screen.getByRole("navigation", { name: "Mobile navigation" });
  expect(within(mobileNavigation).getAllByRole("link")).toHaveLength(2);
  expect(mobileNavigation.children).toHaveLength(3);
  expect(mobileNavigation).toHaveClass("grid-flow-col", "auto-cols-fr");
  expect(mobileNavigation).not.toHaveClass("grid-cols-5");
  expect(within(mobileNavigation).getByRole("link", { name: "Continue" })).toHaveAttribute("href", "/app");
  expect(within(mobileNavigation).getByRole("link", { name: "Library" })).toHaveAttribute("href", "/app/library");
  expect(within(mobileNavigation).queryByRole("link", { name: "History" })).not.toBeInTheDocument();
  expect(within(mobileNavigation).queryByRole("link", { name: "Memory" })).not.toBeInTheDocument();
  expect(within(mobileNavigation).queryByRole("link", { name: "Evidence" })).not.toBeInTheDocument();

  const more = within(mobileNavigation).getByRole("button", { name: "More destinations" });
  expect(more).toHaveAttribute("aria-expanded", "false");
  fireEvent.click(more);

  expect(more).toHaveAttribute("aria-expanded", "true");
  const moreDestinations = screen.getByRole("region", { name: "More destinations" });
  expect(within(moreDestinations).getByRole("link", { name: "History" })).toHaveAttribute("href", "/app/runs");
  expect(within(moreDestinations).getByRole("link", { name: "Memory" })).toHaveAttribute("href", "/app/memory");
  expect(within(moreDestinations).getByRole("link", { name: "Evidence" })).toHaveAttribute("href", "/app/explain");
  expect(within(moreDestinations).getByRole("link", { name: "Sources" })).toHaveAttribute("href", "/app/sources");
  expect(within(moreDestinations).getByRole("link", { name: "Integrations" })).toHaveAttribute("href", "/app/connectors");
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
  expect(screen.getByTestId("now-search")).toHaveTextContent("?objective=Fix%20the%20redirect");
});

it("makes Memory continuation-first while preserving the Inspector and legacy deep links", async () => {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const renderRoute = (route) => render(
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <WorkspaceProvider>
          <MemoryRouter initialEntries={[route]}>
            <App />
          </MemoryRouter>
        </WorkspaceProvider>
      </ThemeProvider>
    </QueryClientProvider>,
  );

  const now = renderRoute("/app/memory");
  expect(await screen.findByRole("heading", { name: "Memory now" })).toBeInTheDocument();
  now.unmount();

  const inspector = renderRoute("/app/memory/inspector?view=history");
  expect(await screen.findByRole("heading", { name: "Project memory" })).toBeInTheDocument();
  expect(screen.getByTestId("memory-inspector-search")).toHaveTextContent("?view=history");
  inspector.unmount();

  renderRoute("/app/memory?view=review&scope=workspace&q=timeout");
  expect(await screen.findByRole("heading", { name: "Project memory" })).toBeInTheDocument();
  expect(screen.getByTestId("memory-inspector-search")).toHaveTextContent(
    "?view=review&scope=workspace&q=timeout",
  );
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
  expect(localStorage.getItem("daemonstate_sidebar_collapsed")).toBe("true");
  expect(screen.getAllByRole("link", { name: "Continue" }).length).toBeGreaterThan(0);
});
