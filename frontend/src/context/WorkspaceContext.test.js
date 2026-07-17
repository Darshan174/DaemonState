import { describe, expect, it } from "vitest";
import { resolveWorkspaceId } from "./WorkspaceContext";

const workspaces = [
  { id: "ws-default", name: "Default" },
  { id: "ws-engine", name: "Context engine" },
];

describe("resolveWorkspaceId", () => {
  it("returns null when there are no workspaces", () => {
    expect(resolveWorkspaceId([], null)).toBeNull();
    expect(resolveWorkspaceId(null, null)).toBeNull();
  });

  it("auto-selects the only real project", () => {
    expect(resolveWorkspaceId([workspaces[0]], null)).toBe("ws-default");
  });

  it("does not silently enter the only sample workspace", () => {
    expect(resolveWorkspaceId([{ id: "demo", kind: "demo" }], null)).toBeNull();
  });

  it("uses a persisted selection when it still exists", () => {
    expect(resolveWorkspaceId(workspaces, "ws-engine")).toBe("ws-engine");
  });

  it("requires an explicit pick when multiple workspaces exist", () => {
    expect(resolveWorkspaceId(workspaces, null)).toBeNull();
    expect(resolveWorkspaceId(workspaces, "deleted-id")).toBeNull();
  });
});
