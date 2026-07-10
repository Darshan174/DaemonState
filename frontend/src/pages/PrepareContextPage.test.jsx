import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import PrepareContextPage, { formatPrepareError } from "./PrepareContextPage";

const mocks = vi.hoisted(() => ({
  workspaces: [{ id: "11111111-1111-1111-1111-111111111111", name: "Context Engine" }],
}));

vi.mock("../api/hooks", () => ({
  useWorkspaces: () => ({ data: mocks.workspaces, isLoading: false }),
}));

vi.mock("../context/WorkspaceContext", () => ({
  useWorkspaceSelection: () => ({ selectedId: null, setSelectedId: vi.fn() }),
  resolveWorkspaceId: (workspaces) => workspaces[0]?.id || null,
}));

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <PrepareContextPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const successPayload = {
  context_pack_id: "pack-123",
  schema_version: "context_pack.v2",
  health_score: 82,
  markdown: "# Objective\nFix provenance",
  manifest: {
    objective: "Fix provenance",
    selected_context: [{
      id: "claim-1",
      lane: "decisions_and_invariants",
      item_type: "decision",
      title: "Preserve raw evidence",
      summary: "Source history is append-only.",
      truth_state: "current",
      inclusion_reason: "verified_current_claim",
      citations: [{ citation_id: "E1", source_revision_number: 2, start_char: 10, end_char: 32, quote: "Source history is append-only." }],
    }],
    excluded_context: [{ id: "old-1", title: "Old mutable-source rule", reason: "historical", reason_detail: "Superseded by revision 2." }],
    verification: {
      acceptance_criteria: [{ id: "AC1", text: "Changed content creates a new revision." }],
      commands: [{ id: "V1", command: "pytest -q tests/test_evidence_ledger.py", purpose: "Verify evidence integrity." }],
    },
    context_health: { readiness_score: 82, reasons: [{ code: "unknown_signal", message: "One source lacks an exact span." }] },
    token_accounting: { rendered_tokens: 2400 },
    risks: [],
    uncertainties: [],
  },
  selected_context: [],
  excluded_context: [],
};
successPayload.selected_context = successPayload.manifest.selected_context;
successPayload.excluded_context = successPayload.manifest.excluded_context;

describe("PrepareContextPage", () => {
  beforeEach(() => {
    mocks.workspaces = [{ id: "11111111-1111-1111-1111-111111111111", name: "Context Engine" }];
    const values = new Map();
    Object.defineProperty(globalThis, "localStorage", {
      configurable: true,
      value: {
        clear: () => values.clear(),
        getItem: (key) => values.get(key) ?? null,
        removeItem: (key) => values.delete(key),
        setItem: (key, value) => values.set(key, String(value)),
      },
    });
    localStorage.clear();
    vi.restoreAllMocks();
    Object.assign(navigator, { clipboard: { writeText: vi.fn().mockResolvedValue(undefined) } });
  });

  it("validates required fields without issuing a request", () => {
    global.fetch = vi.fn();
    renderPage();

    fireEvent.click(screen.getByRole("button", { name: "Compile context pack" }));

    expect(screen.getByRole("alert")).toHaveTextContent("Describe the objective");
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it("supports repository-only compilation when no workspace exists", () => {
    mocks.workspaces = [];
    global.fetch = vi.fn();
    renderPage();

    expect(screen.getByText("Repository only")).toBeInTheDocument();
    expect(screen.getByText("No context pack compiled yet")).toBeInTheDocument();
  });

  it("shows an honest submitting state", async () => {
    global.fetch = vi.fn().mockReturnValue(new Promise(() => {}));
    renderPage();
    fireEvent.change(screen.getByLabelText("Objective"), { target: { value: "Compile a focused pack" } });
    fireEvent.change(screen.getByLabelText("Repository path"), { target: { value: "/workspace/context-engine" } });
    fireEvent.click(screen.getByRole("button", { name: "Compile context pack" }));

    expect(await screen.findByRole("button", { name: "Compiling source-backed context…" })).toBeDisabled();
  });

  it("posts the canonical prepare request and renders auditable output", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => successPayload,
    });
    renderPage();

    fireEvent.change(screen.getByLabelText("Objective"), { target: { value: "Fix provenance" } });
    fireEvent.change(screen.getByLabelText("Repository path"), { target: { value: "/workspace/context-engine" } });
    fireEvent.change(screen.getByLabelText("Target model"), { target: { value: "qwen2.5-coder-7b" } });
    fireEvent.change(screen.getByLabelText("Token budget"), { target: { value: "4000" } });
    fireEvent.click(screen.getByRole("button", { name: "Compile context pack" }));

    await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(1));
    const [url, options] = global.fetch.mock.calls[0];
    expect(url).toBe("/api/context/prepare");
    expect(JSON.parse(options.body)).toEqual({
      objective: "Fix provenance",
      workspace_id: "11111111-1111-1111-1111-111111111111",
      repo_path: "/workspace/context-engine",
      target_model: "qwen2.5-coder-7b",
      token_budget: 4000,
    });
    expect(await screen.findByText("Context pack ready")).toBeInTheDocument();
    expect(screen.getByText("Preserve raw evidence")).toBeInTheDocument();
    expect(screen.getByText("Old mutable-source rule")).toBeInTheDocument();
    expect(screen.getByText("Changed content creates a new revision.")).toBeInTheDocument();
    expect(screen.getByText("pytest -q tests/test_evidence_ledger.py")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Fix provenance" })).toHaveFocus();

    fireEvent.click(screen.getByRole("button", { name: "Copy compiler markdown" }));
    await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledWith("# Objective\nFix provenance"));
  });

  it("keeps values and displays a typed compiler error", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 422,
      json: async () => ({ detail: { code: "context_budget_too_small", message: "Required sections need 620 tokens." } }),
    });
    renderPage();
    fireEvent.change(screen.getByLabelText("Objective"), { target: { value: "Fix budget handling" } });
    fireEvent.change(screen.getByLabelText("Repository path"), { target: { value: "/workspace/context-engine" } });
    fireEvent.click(screen.getByRole("button", { name: "Compile context pack" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Required sections need 620 tokens.");
    expect(alert).toHaveFocus();
    expect(screen.getByLabelText("Objective")).toHaveValue("Fix budget handling");
  });

  it("normalizes Pydantic validation details in the form", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 422,
      json: async () => ({ detail: [{ msg: "repo_path must be an absolute directory" }] }),
    });
    renderPage();
    fireEvent.change(screen.getByLabelText("Objective"), { target: { value: "Fix path validation" } });
    fireEvent.change(screen.getByLabelText("Repository path"), { target: { value: "relative" } });
    fireEvent.click(screen.getByRole("button", { name: "Compile context pack" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("repo_path must be an absolute directory");
  });

  it("preserves form values across a persistence failure", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      json: async () => ({ detail: { code: "context_persistence_failed", message: "Pack persistence failed." } }),
    });
    renderPage();
    fireEvent.change(screen.getByLabelText("Objective"), { target: { value: "Persist exact pack" } });
    fireEvent.change(screen.getByLabelText("Repository path"), { target: { value: "/workspace/context-engine" } });
    fireEvent.click(screen.getByRole("button", { name: "Compile context pack" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Pack persistence failed.");
    expect(screen.getByLabelText("Objective")).toHaveValue("Persist exact pack");
    expect(screen.getByRole("button", { name: "Compile context pack" })).toBeEnabled();
  });

  it("allows retry after a network failure", async () => {
    global.fetch = vi.fn()
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValueOnce({ ok: true, status: 200, json: async () => successPayload });
    renderPage();
    fireEvent.change(screen.getByLabelText("Objective"), { target: { value: "Retry compilation" } });
    fireEvent.change(screen.getByLabelText("Repository path"), { target: { value: "/workspace/context-engine" } });
    fireEvent.click(screen.getByRole("button", { name: "Compile context pack" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("context compiler is unavailable");
    fireEvent.click(screen.getByRole("button", { name: "Compile context pack" }));
    expect(await screen.findByText("Context pack ready")).toBeInTheDocument();
    expect(global.fetch).toHaveBeenCalledTimes(2);
  });
});

describe("formatPrepareError", () => {
  it("normalizes Pydantic and network failures", () => {
    expect(formatPrepareError({ detail: [{ msg: "repo_path is required" }] })).toBe("repo_path is required");
    expect(formatPrepareError({ status: 503 })).toContain("unavailable");
  });
});
