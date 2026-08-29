import { createElement } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  useActivateContextCandidate,
  useContextQualityCandidates,
} from "./hooks";

const api = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
}));

vi.mock("./client", () => ({ api }));

function queryWrapper(queryClient) {
  return function QueryWrapper({ children }) {
    return createElement(QueryClientProvider, { client: queryClient }, children);
  };
}

describe("context quality hooks", () => {
  beforeEach(() => {
    api.get.mockReset();
    api.post.mockReset();
  });

  it("loads the scoped candidate evaluations used by Memory review", async () => {
    const response = { workspace_id: "workspace-1", candidates: [] };
    api.get.mockResolvedValue(response);
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const { result } = renderHook(
      () => useContextQualityCandidates("workspace-1", "session", {
        enabled: true,
        limit: 20,
      }),
      { wrapper: queryWrapper(queryClient) },
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(api.get).toHaveBeenCalledWith(
      "/context-quality/candidates?workspace_id=workspace-1&context_kind=session&limit=20",
    );
    expect(result.current.data).toEqual(response);
  });

  it("binds activation to the reviewed evaluation and pointer generation", async () => {
    api.post.mockResolvedValue({ quality_control: { status: "active" } });
    const queryClient = new QueryClient({
      defaultOptions: { mutations: { retry: false } },
    });
    const { result } = renderHook(
      () => useActivateContextCandidate(),
      { wrapper: queryWrapper(queryClient) },
    );

    await act(async () => {
      await result.current.mutateAsync({
        workspaceId: "workspace-1",
        candidateId: "candidate/one",
        evaluationId: "evaluation-1",
        expectedGeneration: 8,
        reason: "Reviewed the explicit claim gap.",
      });
    });

    expect(api.post).toHaveBeenCalledWith(
      "/context-quality/candidates/candidate%2Fone/activate",
      {
        workspace_id: "workspace-1",
        evaluation_id: "evaluation-1",
        expected_generation: 8,
        reason: "Reviewed the explicit claim gap.",
      },
    );
  });
});
