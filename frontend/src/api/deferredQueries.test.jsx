import { createElement } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  useCheckpoints,
  useLatestCheckpoint,
  useSessionContinuity,
  useSessionLibrary,
} from "./hooks";
import {
  useLinkedAISessionRefresh,
  useProjectMemory,
} from "../context-map/api";

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
  delete: vi.fn(),
}));

vi.mock("./client", () => ({ api: apiMock }));

let queryClient;

function wrapper({ children }) {
  return createElement(QueryClientProvider, { client: queryClient }, children);
}

describe("deferred Now queries", () => {
  beforeEach(() => {
    Object.values(apiMock).forEach((mock) => mock.mockReset());
    apiMock.get.mockResolvedValue({});
    apiMock.post.mockResolvedValue({});
    queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
  });

  afterEach(() => {
    queryClient.clear();
  });

  it("keeps secondary reads idle until enabled, then preserves their session scope", async () => {
    const { rerender } = renderHook(
      ({ enabled }) => {
        useLatestCheckpoint("workspace-1", {
          provider: "claude_code",
          sessionId: "session-1",
          enabled,
        });
        useCheckpoints("workspace-1", 12, {
          provider: "claude_code",
          sessionId: "session-1",
          enabled,
        });
        useSessionLibrary("workspace-1", { enabled });
        useSessionContinuity("workspace-1", {
          provider: "claude_code",
          sessionId: "session-1",
          limit: 50,
          enabled,
        });
        useProjectMemory("workspace-1", { limit: 1, enabled });
      },
      { wrapper, initialProps: { enabled: false } },
    );

    expect(apiMock.get).not.toHaveBeenCalled();

    rerender({ enabled: true });

    await waitFor(() => expect(apiMock.get).toHaveBeenCalledTimes(5));
    expect(apiMock.get).toHaveBeenCalledWith(
      "/checkpoints/latest?workspace_id=workspace-1&provider=claude&session_id=session-1",
    );
    expect(apiMock.get).toHaveBeenCalledWith(
      "/checkpoints?workspace_id=workspace-1&limit=12&provider=claude&session_id=session-1",
    );
    expect(apiMock.get).toHaveBeenCalledWith(
      "/session-continuity?workspace_id=workspace-1&provider=claude&session_id=session-1&limit=50",
    );
    expect(queryClient.getQueryCache().find({
      queryKey: ["session-continuity", "workspace-1", "claude", "session-1", 50],
    })).toBeDefined();
    expect(apiMock.get).toHaveBeenCalledWith(
      "/session-library?workspace_id=workspace-1",
    );
    expect(apiMock.get).toHaveBeenCalledWith(expect.stringContaining(
      "/context/memory?workspace_id=workspace-1",
    ));
  });

  it("delays linked refresh per workspace and uses the slower steady poll", async () => {
    const { rerender } = renderHook(
      ({ workspaceId }) => useLinkedAISessionRefresh(workspaceId, {
        enabled: true,
        initialDelayMs: 25,
      }),
      { wrapper, initialProps: { workspaceId: "workspace-1" } },
    );

    expect(apiMock.post).not.toHaveBeenCalled();
    const firstQuery = queryClient.getQueryCache().find({
      queryKey: ["linked-ai-session-refresh", "workspace-1"],
    });
    expect(firstQuery?.options.refetchInterval).toBe(120_000);

    await waitFor(() => expect(apiMock.post).toHaveBeenCalledWith(
      "/connectors/ai-session/refresh-linked",
      { workspace_id: "workspace-1" },
    ));

    apiMock.post.mockClear();
    await act(async () => {
      rerender({ workspaceId: "workspace-2" });
    });
    expect(apiMock.post).not.toHaveBeenCalled();
    await waitFor(() => expect(apiMock.post).toHaveBeenCalledWith(
      "/connectors/ai-session/refresh-linked",
      { workspace_id: "workspace-2" },
    ));
  });
});
