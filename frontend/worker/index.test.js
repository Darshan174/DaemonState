import { beforeEach, describe, expect, it, vi } from "vitest";

import worker from "./index";

vi.mock("../functions/api/waitlist.js", () => ({
  onRequestPost: vi.fn(async () => new Response("registered", { status: 201 })),
}));

import { onRequestPost } from "../functions/api/waitlist.js";

function executionContext() {
  return {
    waitUntil: vi.fn(),
  };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("Cloudflare Worker entrypoint", () => {
  it("routes waitlist submissions to the waitlist handler", async () => {
    const env = { WAITLIST_DB: { prepare: vi.fn() } };
    const context = executionContext();
    const request = new Request("https://daemonstate.com/api/waitlist", {
      method: "POST",
      body: "{}",
    });

    const response = await worker.fetch(request, env, context);

    expect(response.status).toBe(201);
    expect(onRequestPost).toHaveBeenCalledOnce();
    const handlerContext = onRequestPost.mock.calls[0][0];
    expect(handlerContext.request).toBe(request);
    expect(handlerContext.env).toBe(env);
    const pending = Promise.resolve();
    handlerContext.waitUntil(pending);
    expect(context.waitUntil).toHaveBeenCalledWith(pending);
  });

  it("returns method not allowed for non-POST waitlist requests", async () => {
    const response = await worker.fetch(
      new Request("https://daemonstate.com/api/waitlist"),
      {},
      executionContext(),
    );

    expect(response.status).toBe(405);
    expect(response.headers.get("allow")).toBe("POST");
    expect(onRequestPost).not.toHaveBeenCalled();
  });

  it("returns not found for other Worker routes", async () => {
    const response = await worker.fetch(
      new Request("https://daemonstate.com/api/unknown", { method: "POST" }),
      {},
      executionContext(),
    );

    expect(response.status).toBe(404);
    expect(onRequestPost).not.toHaveBeenCalled();
  });
});
