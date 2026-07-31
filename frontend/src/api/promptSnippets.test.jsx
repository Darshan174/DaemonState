import { createElement } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  useCreatePromptSnippet,
  useDeletePromptSnippet,
  usePromptSnippets,
} from "./hooks";

const api = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  delete: vi.fn(),
}));

vi.mock("./client", () => ({ api }));

function queryWrapper(queryClient) {
  return function QueryWrapper({ children }) {
    return createElement(QueryClientProvider, { client: queryClient }, children);
  };
}

describe("prompt snippet hooks", () => {
  beforeEach(() => {
    api.get.mockReset();
    api.post.mockReset();
    api.delete.mockReset();
  });

  it("loads the active workspace prompt library", async () => {
    const response = { workspace_id: "workspace-1", prompts: [] };
    api.get.mockResolvedValue(response);
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const { result } = renderHook(
      () => usePromptSnippets("workspace-1"),
      { wrapper: queryWrapper(queryClient) },
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(api.get).toHaveBeenCalledWith(
      "/workspaces/workspace-1/prompt-snippets",
    );
    expect(result.current.data).toEqual(response);
  });

  it("adds the authoritative saved prompt to the query cache", async () => {
    const saved = { id: "prompt-1", content: "Review the diff." };
    api.post.mockResolvedValue(saved);
    const queryClient = new QueryClient({
      defaultOptions: { mutations: { retry: false } },
    });
    queryClient.setQueryData(["prompt-snippets", "workspace-1"], {
      workspace_id: "workspace-1",
      prompts: [{ id: "prompt-old", content: "Old prompt" }],
    });
    const { result } = renderHook(
      () => useCreatePromptSnippet(),
      { wrapper: queryWrapper(queryClient) },
    );

    await act(async () => {
      await result.current.mutateAsync({
        workspaceId: "workspace-1",
        content: "Review the diff.",
      });
    });

    expect(api.post).toHaveBeenCalledWith(
      "/workspaces/workspace-1/prompt-snippets",
      { content: "Review the diff." },
    );
    expect(queryClient.getQueryData(
      ["prompt-snippets", "workspace-1"],
    ).prompts.map((prompt) => prompt.id)).toEqual(["prompt-1", "prompt-old"]);
  });

  it("deletes a prompt and removes it from the query cache", async () => {
    api.delete.mockResolvedValue(null);
    const queryClient = new QueryClient({
      defaultOptions: { mutations: { retry: false } },
    });
    queryClient.setQueryData(["prompt-snippets", "workspace-1"], {
      workspace_id: "workspace-1",
      prompts: [
        { id: "prompt-1", content: "Keep" },
        { id: "prompt-2", content: "Delete" },
      ],
    });
    const { result } = renderHook(
      () => useDeletePromptSnippet(),
      { wrapper: queryWrapper(queryClient) },
    );

    await act(async () => {
      await result.current.mutateAsync({
        workspaceId: "workspace-1",
        promptId: "prompt-2",
      });
    });

    expect(api.delete).toHaveBeenCalledWith(
      "/workspaces/workspace-1/prompt-snippets/prompt-2",
    );
    expect(queryClient.getQueryData(
      ["prompt-snippets", "workspace-1"],
    ).prompts.map((prompt) => prompt.id)).toEqual(["prompt-1"]);
  });
});
