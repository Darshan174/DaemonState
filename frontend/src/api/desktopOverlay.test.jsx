import { createElement } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  useDesktopOverlayStatus,
  useSetDesktopOverlayVisibility,
} from "./hooks";

const api = vi.hoisted(() => ({
  get: vi.fn(),
  put: vi.fn(),
}));

vi.mock("./client", () => ({ api }));

function queryWrapper(queryClient) {
  return function QueryWrapper({ children }) {
    return createElement(QueryClientProvider, { client: queryClient }, children);
  };
}

describe("desktop overlay hooks", () => {
  beforeEach(() => {
    api.get.mockReset();
    api.put.mockReset();
  });

  it("loads status for the selected workspace", async () => {
    api.get.mockResolvedValue({ available: true, visible: false });
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const { result } = renderHook(
      () => useDesktopOverlayStatus("workspace-1"),
      { wrapper: queryWrapper(queryClient) },
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(api.get).toHaveBeenCalledWith(
      "/desktop/overlay?workspace_id=workspace-1",
    );
    expect(result.current.data).toEqual({ available: true, visible: false });
  });

  it("stores the server response as the authoritative visibility state", async () => {
    const serverStatus = {
      available: true,
      visible: true,
      workspace_id: "workspace-1",
    };
    api.put.mockResolvedValue(serverStatus);
    const queryClient = new QueryClient({
      defaultOptions: { mutations: { retry: false } },
    });
    queryClient.setQueryData(
      ["desktop-overlay", "workspace-1"],
      { available: true, visible: false },
    );
    queryClient.setQueryData(
      ["desktop-overlay", "workspace-2"],
      {
        available: true,
        visible: true,
        workspace_id: "workspace-2",
      },
    );
    const { result } = renderHook(
      () => useSetDesktopOverlayVisibility(),
      { wrapper: queryWrapper(queryClient) },
    );

    await act(async () => {
      await result.current.mutateAsync({
        visible: true,
        workspaceId: "workspace-1",
      });
    });

    expect(api.put).toHaveBeenCalledWith("/desktop/overlay", {
      visible: true,
      workspace_id: "workspace-1",
    });
    expect(queryClient.getQueryData(
      ["desktop-overlay", "workspace-1"],
    )).toEqual(serverStatus);
    expect(queryClient.getQueryData(
      ["desktop-overlay", "workspace-2"],
    )).toEqual(serverStatus);
  });
});
