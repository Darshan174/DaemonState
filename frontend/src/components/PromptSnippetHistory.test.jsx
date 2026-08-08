import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import PromptSnippetHistory from "./PromptSnippetHistory";

const mocks = vi.hoisted(() => ({
  prompts: {
    data: { prompts: [] },
    isLoading: false,
    isFetching: false,
    isError: false,
    error: null,
  },
  create: {
    isPending: false,
    error: null,
    mutateAsync: vi.fn(),
    reset: vi.fn(),
  },
  remove: {
    isPending: false,
    error: null,
    variables: null,
    mutateAsync: vi.fn(),
    reset: vi.fn(),
  },
}));

vi.mock("../api/hooks", () => ({
  usePromptSnippets: () => mocks.prompts,
  useCreatePromptSnippet: () => mocks.create,
  useDeletePromptSnippet: () => mocks.remove,
}));

beforeEach(() => {
  mocks.prompts.data = { prompts: [] };
  mocks.prompts.isLoading = false;
  mocks.prompts.isFetching = false;
  mocks.prompts.isError = false;
  mocks.prompts.error = null;
  mocks.create.isPending = false;
  mocks.create.error = null;
  mocks.create.mutateAsync.mockReset();
  mocks.create.reset.mockReset();
  mocks.remove.isPending = false;
  mocks.remove.error = null;
  mocks.remove.variables = null;
  mocks.remove.mutateAsync.mockReset();
  mocks.remove.reset.mockReset();
  document.body.style.overflow = "";
});

describe("PromptSnippetHistory", () => {
  it("defaults to the first prompt and switches the full detail view from the list", () => {
    mocks.prompts.data = {
      prompts: [
        promptFixture({
          id: "prompt-1",
          content: "Review the current diff\nReport concrete regressions only.",
          use_count: 3,
          last_used_at: new Date().toISOString(),
        }),
        promptFixture({
          id: "prompt-2",
          content: "Write release notes\nKeep them concise and user-facing.",
        }),
      ],
    };
    render(<PromptSnippetHistory workspaceId="workspace-1" />);

    const firstPrompt = screen.getByRole("button", {
      name: "Select prompt: Review the current diff",
    });
    const secondPrompt = screen.getByRole("button", {
      name: "Select prompt: Write release notes",
    });
    expect(firstPrompt).toHaveAttribute("aria-pressed", "true");
    expect(screen.getAllByText(/Used 3 times/)).toHaveLength(2);

    let detail = screen.getByRole("article", { name: "Selected prompt" });
    expect(detail).toHaveTextContent(
      "Review the current diff Report concrete regressions only.",
    );

    fireEvent.click(secondPrompt);

    expect(secondPrompt).toHaveAttribute("aria-pressed", "true");
    expect(firstPrompt).toHaveAttribute("aria-pressed", "false");
    detail = screen.getByRole("article", { name: "Selected prompt" });
    expect(detail).toHaveTextContent(
      "Write release notes Keep them concise and user-facing.",
    );
  });

  it("opens the add dialog, preserves formatting, then selects the saved prompt", async () => {
    const savedPrompt = promptFixture({
      id: "prompt-new",
      content: "Review the diff\nReturn only actionable findings.",
    });
    mocks.create.mutateAsync.mockResolvedValue(savedPrompt);
    render(<PromptSnippetHistory workspaceId="workspace-1" />);

    const library = screen.getByRole("region", {
      name: "Reusable prompt history",
    });
    const addButton = screen.getByRole("button", { name: "Add prompt manually" });
    expect(within(screen.getByTestId("prompt-library-header")).getByRole("button", {
      name: "Add prompt manually",
    })).toBe(addButton);
    addButton.focus();
    fireEvent.click(addButton);

    const dialog = screen.getByRole("dialog", { name: "Add a reusable prompt" });
    const editor = within(dialog).getByLabelText("Prompt text");
    expect(library).toHaveAttribute("inert");
    expect(document.body.style.overflow).toBe("hidden");
    await waitFor(() => expect(editor).toHaveFocus());

    fireEvent.change(editor, {
      target: { value: "  Review the diff\nReturn only actionable findings.  " },
    });
    expect(within(dialog).getByText("52 / 20,000")).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Save prompt" }));

    await waitFor(() => expect(mocks.create.mutateAsync).toHaveBeenCalledWith({
      workspaceId: "workspace-1",
      content: "Review the diff\nReturn only actionable findings.",
    }));
    expect(screen.queryByRole("dialog", { name: "Add a reusable prompt" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", {
      name: "Select prompt: Review the diff",
    })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("article", { name: "Selected prompt" })).toHaveTextContent(
      "Review the diff Return only actionable findings.",
    );
    expect(screen.getByRole("status")).toHaveTextContent(
      "Saved “Review the diff” to the floating button.",
    );
    expect(library).not.toHaveAttribute("inert");
    expect(document.body.style.overflow).toBe("");
    await waitFor(() => expect(addButton).toHaveFocus());
  });

  it("traps focus and supports Escape, backdrop, and the standalone red cross", async () => {
    render(<PromptSnippetHistory workspaceId="workspace-1" />);
    const addButton = screen.getByRole("button", { name: "Add prompt manually" });

    fireEvent.click(addButton);
    const dialog = screen.getByRole("dialog", { name: "Add a reusable prompt" });
    const editor = within(dialog).getByLabelText("Prompt text");
    const closeButton = within(dialog).getByRole("button", {
      name: "Close add prompt dialog",
    });
    expect(closeButton).toHaveClass("text-[#ff5f57]");
    expect(closeButton).not.toHaveClass("rounded-full", "bg-[#ff5f57]");
    fireEvent.change(editor, { target: { value: "Reusable prompt" } });
    const saveButton = within(dialog).getByRole("button", { name: "Save prompt" });
    saveButton.focus();
    fireEvent.keyDown(window, { key: "Tab" });
    expect(closeButton).toHaveFocus();

    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "Add a reusable prompt" })).not.toBeInTheDocument();
    await waitFor(() => expect(addButton).toHaveFocus());

    fireEvent.click(addButton);
    fireEvent.mouseDown(screen.getByTestId("prompt-editor-backdrop"));
    expect(screen.queryByRole("dialog", { name: "Add a reusable prompt" })).not.toBeInTheDocument();

    fireEvent.click(addButton);
    fireEvent.click(screen.getByRole("button", { name: "Close add prompt dialog" }));
    expect(screen.queryByRole("dialog", { name: "Add a reusable prompt" })).not.toBeInTheDocument();
  });

  it("keeps a save error inside the open dialog", async () => {
    mocks.create.mutateAsync.mockRejectedValue(new Error("Prompt service unavailable"));
    render(<PromptSnippetHistory workspaceId="workspace-1" />);

    fireEvent.click(screen.getByRole("button", { name: "Add prompt manually" }));
    const dialog = screen.getByRole("dialog", { name: "Add a reusable prompt" });
    fireEvent.change(within(dialog).getByLabelText("Prompt text"), {
      target: { value: "Keep this prompt" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save prompt" }));

    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      "Prompt service unavailable",
    );
    expect(screen.getByRole("dialog", { name: "Add a reusable prompt" })).toBeInTheDocument();
  });

  it("deletes the selected prompt and moves the detail view to the next available item", async () => {
    mocks.prompts.data = {
      prompts: [
        promptFixture({ id: "prompt-1", content: "Keep this prompt" }),
        promptFixture({ id: "prompt-2", content: "Delete this prompt" }),
      ],
    };
    mocks.remove.mutateAsync.mockResolvedValue(null);
    render(<PromptSnippetHistory workspaceId="workspace-1" />);

    fireEvent.click(screen.getByRole("button", {
      name: "Select prompt: Delete this prompt",
    }));
    fireEvent.click(screen.getByRole("button", {
      name: "Delete prompt: Delete this prompt",
    }));

    await waitFor(() => expect(mocks.remove.mutateAsync).toHaveBeenCalledWith({
      workspaceId: "workspace-1",
      promptId: "prompt-2",
    }));
    expect(screen.queryByRole("button", {
      name: "Select prompt: Delete this prompt",
    })).not.toBeInTheDocument();
    expect(screen.getByRole("article", { name: "Selected prompt" })).toHaveTextContent(
      "Keep this prompt",
    );
    expect(screen.getByText("1 saved")).toBeInTheDocument();
  });

  it("keeps the floating-dropdown path visible in the empty state", () => {
    render(<PromptSnippetHistory workspaceId="workspace-1" />);

    expect(screen.getByText("No saved prompts yet")).toBeInTheDocument();
    expect(document.querySelector(".lucide-sparkles")).not.toBeInTheDocument();
    expect(screen.getByText(
      "Use the green + button or paste one directly into the floating dropdown.",
    )).toBeInTheDocument();
    expect(screen.getByText("Nothing selected yet")).toBeInTheDocument();
  });
});

function promptFixture(overrides = {}) {
  return {
    id: "prompt-1",
    content: "Reusable prompt",
    use_count: 0,
    last_used_at: null,
    created_at: "2026-08-06T06:00:00Z",
    ...overrides,
  };
}
