import { beforeEach, describe, expect, it } from "vitest";

import {
  MAX_EXECUTE_SESSION_CONTEXTS,
  desktopOverlaySessionSelections,
  normalizeExecuteSessionContexts,
  readExecuteActiveSessionIdentities,
  readExecuteSessionContexts,
  resolveExecuteSessionContexts,
  writeExecuteSessionContexts,
  writeExecuteActiveSessionIdentities,
} from "./executeSessionSelection";


function session(id, overrides = {}) {
  return {
    source_document_id: `document-${id}`,
    connector_type: "codex",
    session_id: `session-${id}`,
    title: `Session ${id}`,
    compaction_checkpoints: [
      { id: `compaction-${id}-1` },
      { id: `compaction-${id}-2` },
    ],
    ...overrides,
  };
}


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


describe("Execute session-context selection", () => {
  it("deduplicates sessions and clamps the selection to three", () => {
    const selected = normalizeExecuteSessionContexts([
      session("one"),
      session("one"),
      session("two"),
      session("three"),
      session("four"),
    ]);

    expect(selected).toHaveLength(MAX_EXECUTE_SESSION_CONTEXTS);
    expect(selected.map((item) => item.sourceDocumentId)).toEqual([
      "document-one",
      "document-two",
      "document-three",
    ]);
  });

  it("keeps each workspace selection isolated and survives malformed storage", () => {
    writeExecuteSessionContexts("workspace-one", [
      session("one"),
      session("two"),
      session("three"),
    ]);

    expect(readExecuteSessionContexts("workspace-one")).toHaveLength(3);
    expect(readExecuteSessionContexts("workspace-two")).toEqual([]);

    localStorage.setItem(
      "daemonstate:workspace-preferences:workspace-one",
      "{not-json",
    );
    expect(readExecuteSessionContexts("workspace-one")).toEqual([]);
  });

  it("refreshes stored display data from the Library and drops stale sessions", () => {
    const stored = normalizeExecuteSessionContexts([
      session("one", { title: "Old title" }),
      session("missing"),
    ]);
    const resolved = resolveExecuteSessionContexts(stored, [
      session("one", { title: "Current title", latest_topic: "Current topic" }),
    ]);

    expect(resolved).toEqual([expect.objectContaining({
      sourceDocumentId: "document-one",
      title: "Current title",
      topic: "Current topic",
      compactionCount: 2,
    })]);
  });

  it("carries a zero-compaction lock into Execute", () => {
    const [selected] = normalizeExecuteSessionContexts([
      session("new", { compaction_checkpoints: [] }),
    ]);

    expect(selected.compactionCount).toBe(0);
  });

  it("maps the ordered selection to the bounded native overlay contract", () => {
    const selected = desktopOverlaySessionSelections([
      session("one", { connector_type: "claude-code", title: "Architecture" }),
      session("two", { connector_type: "open_code", title: "Terminal work" }),
      session("three", { title: "Implementation" }),
      session("four"),
    ]);

    expect(selected).toEqual([
      {
        provider: "claude",
        session_id: "session-one",
        title: "Architecture",
        ordinal: 1,
      },
      {
        provider: "opencode",
        session_id: "session-two",
        title: "Terminal work",
        ordinal: 2,
      },
      {
        provider: "codex",
        session_id: "session-three",
        title: "Implementation",
        ordinal: 3,
      },
    ]);
  });

  it("persists active numbered choices per workspace and provider", () => {
    writeExecuteActiveSessionIdentities("workspace-one", {
      codex: "codex:session-two",
      "claude-code": "claude:session-three",
      unknown: "unknown:session-four",
      opencode: "codex:wrong-provider",
    });

    expect(readExecuteActiveSessionIdentities("workspace-one")).toEqual({
      codex: "codex:session-two",
      claude: "claude:session-three",
    });
    expect(readExecuteActiveSessionIdentities("workspace-two")).toEqual({});
  });

  it("drops an active choice when its selected session is removed", () => {
    writeExecuteSessionContexts("workspace-one", [
      session("one"),
      session("two"),
    ]);
    writeExecuteActiveSessionIdentities("workspace-one", {
      codex: "codex:session-two",
    });

    writeExecuteSessionContexts("workspace-one", [session("one")]);

    expect(readExecuteActiveSessionIdentities("workspace-one")).toEqual({});
  });
});
