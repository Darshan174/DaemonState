import { createElement } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createIndexedProject, useCreateProjectWorkspace } from "./hooks";

const defaultClient = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
  delete: vi.fn(),
}));

vi.mock("./client", () => ({ api: defaultClient }));

function fakeClient() {
  return {
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  };
}

describe("createIndexedProject", () => {
  beforeEach(() => {
    Object.values(defaultClient).forEach((mock) => mock.mockReset());
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

  it("does not confuse React Query's mutation context with the API client", async () => {
    const workspace = { id: "workspace-hook", name: "Hook Project" };
    const repository = { repo_path: "/code/hook-project", files_indexed: 12 };
    defaultClient.post.mockResolvedValueOnce(workspace).mockResolvedValueOnce(repository);
    const queryClient = new QueryClient({
      defaultOptions: { mutations: { retry: false }, queries: { retry: false } },
    });
    const wrapper = ({ children }) => createElement(
      QueryClientProvider,
      { client: queryClient },
      children,
    );
    const { result } = renderHook(() => useCreateProjectWorkspace(), { wrapper });

    await act(async () => {
      await result.current.mutateAsync({
        name: "Hook Project",
        repo_path: "/code/hook-project",
      });
    });

    expect(defaultClient.post).toHaveBeenNthCalledWith(1, "/workspaces", {
      name: "Hook Project",
      kind: "project",
    });
    expect(defaultClient.post).toHaveBeenNthCalledWith(2, "/repo/index", {
      workspace_id: "workspace-hook",
      repo_path: "/code/hook-project",
    });
  });

  it("keeps the workspace only after repository indexing succeeds", async () => {
    const client = fakeClient();
    const workspace = { id: "workspace-1", name: "Real Project" };
    const repository = { repo_path: "/code/real-project", files_indexed: 42 };
    client.post.mockResolvedValueOnce(workspace).mockResolvedValueOnce(repository);

    await expect(createIndexedProject(
      { name: "Real Project", repo_path: "/code/real-project", client },
    )).resolves.toEqual({ workspace, repository });
    expect(client.patch).not.toHaveBeenCalled();
    expect(client.delete).not.toHaveBeenCalled();
  });

  it("removes a new empty workspace when indexing rejects the path", async () => {
    const client = fakeClient();
    const workspace = { id: "workspace-2", name: "Bad Path" };
    const indexError = new Error("Repository does not exist");
    client.post.mockResolvedValueOnce(workspace).mockRejectedValueOnce(indexError);
    client.get.mockResolvedValue([workspace]);
    client.patch.mockResolvedValue({ ...workspace, status: "archived" });
    client.delete.mockResolvedValue(null);

    await expect(createIndexedProject(
      { name: "Bad Path", repo_path: "/missing", client },
    )).rejects.toBe(indexError);
    expect(client.patch).toHaveBeenCalledWith("/workspaces/workspace-2", { status: "archived" });
    expect(client.delete).toHaveBeenCalledWith("/workspaces/workspace-2?confirm_name=Bad%20Path");
  });

  it("recovers a committed index when only its response was lost", async () => {
    const client = fakeClient();
    const workspace = { id: "workspace-3", name: "Recovered" };
    const recovered = { ...workspace, repo_path: "/code/recovered" };
    client.post.mockResolvedValueOnce(workspace).mockRejectedValueOnce(new Error("Network lost"));
    client.get.mockResolvedValue([recovered]);

    await expect(createIndexedProject(
      { name: "Recovered", repo_path: "/code/recovered", client },
    )).resolves.toEqual({ workspace: recovered, repository: null, recovered: true });
    expect(client.patch).not.toHaveBeenCalled();
    expect(client.delete).not.toHaveBeenCalled();
  });
});
