import { describe, expect, it, vi } from "vitest";
import { createIndexedProject } from "./hooks";

function fakeClient() {
  return {
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  };
}

describe("createIndexedProject", () => {
  it("keeps the workspace only after repository indexing succeeds", async () => {
    const client = fakeClient();
    const workspace = { id: "workspace-1", name: "Real Project" };
    const repository = { repo_path: "/code/real-project", files_indexed: 42 };
    client.post.mockResolvedValueOnce(workspace).mockResolvedValueOnce(repository);

    await expect(createIndexedProject(
      { name: "Real Project", repo_path: "/code/real-project" },
      client,
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
      { name: "Bad Path", repo_path: "/missing" },
      client,
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
      { name: "Recovered", repo_path: "/code/recovered" },
      client,
    )).resolves.toEqual({ workspace: recovered, repository: null, recovered: true });
    expect(client.patch).not.toHaveBeenCalled();
    expect(client.delete).not.toHaveBeenCalled();
  });
});
