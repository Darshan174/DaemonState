import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, api, apiFetch } from "./client";


afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});


describe("ApiError", () => {
  it("uses a structured API message instead of raw JSON", () => {
    const error = new ApiError(422, {
      code: "focus_not_eligible",
      message: "Pull requests are delivery evidence.",
    });

    expect(error.message).toBe("Pull requests are delivery evidence.");
    expect(error.message).not.toContain("focus_not_eligible");
    expect(error.status).toBe(422);
  });
});


describe("apiFetch timeout", () => {
  it("aborts a stalled local request with a structured error", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("fetch", vi.fn((_url, options) => new Promise(
      (_resolve, reject) => {
        options.signal.addEventListener("abort", () => {
          reject(new DOMException("Aborted", "AbortError"));
        });
      },
    )));

    const request = apiFetch("/continuations/stage", {
      timeoutMs: 50,
      timeoutMessage: "Desktop handoff timed out.",
    });
    const assertion = expect(request).rejects.toMatchObject({
      status: 504,
      message: "Desktop handoff timed out.",
    });

    await vi.advanceTimersByTimeAsync(50);
    await assertion;
  });

  it("applies timeout options passed through api.get", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("fetch", vi.fn((_url, options) => new Promise(
      (_resolve, reject) => {
        options.signal.addEventListener("abort", () => {
          reject(new DOMException("Aborted", "AbortError"));
        });
      },
    )));

    const request = api.get("/continuations/providers", {
      timeoutMs: 50,
      timeoutMessage: "Desktop readiness timed out.",
    });
    const assertion = expect(request).rejects.toMatchObject({
      status: 504,
      message: "Desktop readiness timed out.",
    });

    await vi.advanceTimersByTimeAsync(50);
    await assertion;
  });

  it("keeps the deadline active while the response body is being read", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("fetch", vi.fn((_url, options) => Promise.resolve({
      ok: true,
      status: 200,
      json: () => new Promise((_resolve, reject) => {
        options.signal.addEventListener("abort", () => {
          reject(new DOMException("Aborted", "AbortError"));
        });
      }),
    })));

    const request = apiFetch("/continuations/stage", {
      timeoutMs: 50,
      timeoutMessage: "Desktop handoff timed out.",
    });
    const assertion = expect(request).rejects.toMatchObject({
      status: 504,
      message: "Desktop handoff timed out.",
    });

    await vi.advanceTimersByTimeAsync(50);
    await assertion;
  });
});
