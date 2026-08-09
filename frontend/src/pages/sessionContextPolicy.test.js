import { describe, expect, it } from "vitest";

import {
  sessionContextCompactionCount,
  sessionContextCompactionLabel,
  sessionContextIsEligible,
} from "./sessionContextPolicy";


describe("session context compaction authority", () => {
  it("uses the explicit event-ledger count even when stale descriptors disagree", () => {
    const session = {
      compaction_count: 1,
      compaction_checkpoints: [
        { id: "stale-one" },
        { id: "stale-two" },
      ],
    };

    expect(sessionContextCompactionCount(session)).toBe(1);
    expect(sessionContextCompactionLabel(session)).toBe("1/2 compactions");
    expect(sessionContextIsEligible(session)).toBe(false);
  });

  it("accepts an explicit eligible count without checkpoint descriptors", () => {
    const session = {
      compaction_count: 2,
      compaction_checkpoints: [],
    };

    expect(sessionContextCompactionCount(session)).toBe(2);
    expect(sessionContextIsEligible(session)).toBe(true);
  });

  it("treats explicit zero as authoritative", () => {
    expect(sessionContextCompactionCount({
      compaction_count: 0,
      compaction_checkpoints: [{ id: "stale" }],
    })).toBe(0);
  });

  it("counts descriptors only for legacy payloads without an explicit field", () => {
    expect(sessionContextCompactionCount({
      compaction_checkpoints: [{ id: "one" }, { id: "two" }],
    })).toBe(2);
  });
});
