import { beforeEach, describe, expect, it } from "vitest";

import {
  readWorkspacePreferences,
  STORAGE_PREFIX,
  writeWorkspacePreferences,
} from "./workspacePreferences";

beforeEach(() => {
  const values = new Map();
  Object.defineProperty(globalThis, "localStorage", {
    configurable: true,
    value: {
      clear: () => values.clear(),
      getItem: (key) => values.get(key) ?? null,
      removeItem: (key) => values.delete(key),
      setItem: (key, value) => values.set(key, String(value)),
    },
  });
});

describe("workspace preferences", () => {
  it("starts a new workspace from defaults without copying another workspace", () => {
    writeWorkspacePreferences("workspace-one", "prepare", {
      targetModel: "older-coder",
      tokenBudget: "2200",
    });

    expect(readWorkspacePreferences("workspace-two", "prepare", {
      targetModel: "",
      tokenBudget: "4000",
    })).toEqual({ targetModel: "", tokenBudget: "4000" });
  });

  it("restores each workspace's own surface configuration", () => {
    writeWorkspacePreferences("workspace-one", "query", {
      topK: 4,
      minConfidence: 0.7,
      hybrid: false,
    });
    writeWorkspacePreferences("workspace-one", "prepare", {
      targetModel: "qwen2.5-coder-7b",
      tokenBudget: "2400",
    });

    expect(readWorkspacePreferences("workspace-one", "query", {})).toEqual({
      topK: 4,
      minConfidence: 0.7,
      hybrid: false,
    });
    expect(readWorkspacePreferences("workspace-one", "prepare", {})).toEqual({
      targetModel: "qwen2.5-coder-7b",
      tokenBudget: "2400",
    });
    expect(localStorage.getItem(`${STORAGE_PREFIX}workspace-one`)).toContain("qwen2.5-coder-7b");
  });
});
