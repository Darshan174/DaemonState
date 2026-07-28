import { createElement } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  useCheckpoints,
  useLatestCheckpoint,
  useSessionLibrary,
} from "./hooks";
import {
  useContextDigest,
  useLatestLocalAISessionDiscovery,
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

  it("keeps secondary reads idle until enabled, then preserves checkpoint scope", async () => {
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
        useProjectMemory("workspace-1", { limit: 1, enabled });
      },
      { wrapper, initialProps: { enabled: false } },
    );

    expect(apiMock.get).not.toHaveBeenCalled();

    rerender({ enabled: true });

    await waitFor(() => expect(apiMock.get).toHaveBeenCalledTimes(4));
    expect(apiMock.get).toHaveBeenCalledWith(
      "/checkpoints/latest?workspace_id=workspace-1&provider=claude&session_id=session-1",
    );
    expect(apiMock.get).toHaveBeenCalledWith(
      "/checkpoints?workspace_id=workspace-1&limit=12&provider=claude&session_id=session-1",
    );
    expect(apiMock.get).toHaveBeenCalledWith(
      "/session-library?workspace_id=workspace-1",
    );
    expect(apiMock.get).toHaveBeenCalledWith(expect.stringContaining(
      "/context/memory?workspace_id=workspace-1",
    ));
  });

  it("keeps the digest idle until latest-session discovery has settled", async () => {
    const { rerender } = renderHook(
      ({ enabled }) => useContextDigest("workspace-1", {
        poll: true,
        enabled,
      }),
      { wrapper, initialProps: { enabled: false } },
    );

    expect(apiMock.get).not.toHaveBeenCalled();

    rerender({ enabled: true });

    await waitFor(() => expect(apiMock.get).toHaveBeenCalledWith(
      "/context/digest?workspace_id=workspace-1",
    ));
  });

  it("discovers unindexed local sessions and invalidates stale continuation data", async () => {
    const latestSession = {
      connector_type: "codex",
      session_id: "newest-session",
    };
    apiMock.post.mockResolvedValue({
      sync: { mode: "latest", discovered: 1, imported: 1 },
      session: latestSession,
    });
    queryClient.setQueryData(
      ["session-library", "workspace-1"],
      { sessions: [{ connector_type: "codex", session_id: "older-session" }] },
    );
    queryClient.setQueryData(
      ["context-digest", "workspace-1"],
      { activity: { recent_sessions: [{ session_id: "older-session" }] } },
    );

    const { result } = renderHook(
      () => useLatestLocalAISessionDiscovery("workspace-1"),
      { wrapper },
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(apiMock.post).toHaveBeenCalledWith(
      "/session-library/latest",
      { workspace_id: "workspace-1" },
    );
    expect(apiMock.post).not.toHaveBeenCalledWith(
      "/session-library/sync",
      expect.anything(),
    );
    expect(apiMock.post).not.toHaveBeenCalledWith(
      "/connectors/ai-session/refresh-linked",
      expect.anything(),
    );
    expect(queryClient.getQueryData(
      ["session-library", "workspace-1"],
    )).toEqual({
      sessions: [{ connector_type: "codex", session_id: "older-session" }],
    });
    expect(queryClient.getQueryState(
      ["context-digest", "workspace-1"],
    )?.isInvalidated).toBe(true);
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
