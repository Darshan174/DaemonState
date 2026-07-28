import { beforeEach, describe, expect, it } from "vitest";

import {
  MAX_EXECUTE_SESSION_CONTEXTS,
  normalizeExecuteSessionContexts,
  readExecuteSessionContexts,
  resolveExecuteSessionContexts,
  writeExecuteSessionContexts,
} from "./executeSessionSelection";


function session(id, overrides = {}) {
  return {
    source_document_id: `document-${id}`,
    connector_type: "codex",
    session_id: `session-${id}`,
    title: `Session ${id}`,
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
    })]);
  });
});
