import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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
});

describe("PromptSnippetHistory", () => {
  it("saves a formatted reusable prompt and clears the editor", async () => {
    mocks.create.mutateAsync.mockResolvedValue({
      id: "prompt-1",
      content: "Review the diff\nReturn only actionable findings.",
    });
    render(<PromptSnippetHistory workspaceId="workspace-1" />);

    const editor = screen.getByLabelText("Add a prompt");
    fireEvent.change(editor, {
      target: { value: "  Review the diff\nReturn only actionable findings.  " },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save prompt" }));

    await waitFor(() => expect(mocks.create.mutateAsync).toHaveBeenCalledWith({
      workspaceId: "workspace-1",
      content: "Review the diff\nReturn only actionable findings.",
    }));
    expect(editor).toHaveValue("");
    expect(screen.getByRole("status")).toHaveTextContent(
      "Saved “Review the diff” to the floating button.",
    );
  });

  it("renders usage history and deletes a selected prompt", async () => {
    mocks.prompts.data = {
      prompts: [{
        id: "prompt-2",
        content: "Write a concise release note.",
        use_count: 3,
        last_used_at: new Date().toISOString(),
        created_at: new Date().toISOString(),
      }],
    };
    mocks.remove.mutateAsync.mockResolvedValue(null);
    render(<PromptSnippetHistory workspaceId="workspace-1" />);

    expect(screen.getAllByText("Write a concise release note.")).toHaveLength(2);
    expect(screen.getByText(/Used 3 times/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", {
      name: "Delete prompt: Write a concise release note.",
    }));

    await waitFor(() => expect(mocks.remove.mutateAsync).toHaveBeenCalledWith({
      workspaceId: "workspace-1",
      promptId: "prompt-2",
    }));
  });

  it("explains that prompts can also be pasted into the floating dropdown", () => {
    render(<PromptSnippetHistory workspaceId="workspace-1" />);

    expect(screen.getByText("No saved prompts yet")).toBeInTheDocument();
    expect(screen.getByText(
      "Save one here or paste one directly into the floating dropdown.",
    )).toBeInTheDocument();
  });
});
