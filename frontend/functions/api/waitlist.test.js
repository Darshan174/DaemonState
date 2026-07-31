import { describe, expect, it } from "vitest";

import { onRequestPost } from "./waitlist";


function createDatabase() {
  const calls = [];
  return {
    calls,
    prepare(sql) {
      const statement = {
        bind(...values) {
          calls.push({ sql, values });
          return statement;
        },
        async run() {
          if (!calls.some((call) => call.sql === sql)) {
            calls.push({ sql, values: [] });
          }
          return { success: true };
        },
      };
      return statement;
    },
  };
}

function signupRequest(body, headers = {}) {
  return new Request("https://daemonstate.com/api/waitlist", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      origin: "https://daemonstate.com",
      ...headers,
    },
    body: JSON.stringify(body),
  });
}

describe("Cloudflare waitlist function", () => {
  it("normalizes and stores a valid email", async () => {
    const database = createDatabase();
    const response = await onRequestPost({
      request: signupRequest({ email: " Builder@Example.COM ", website: "" }),
      env: { WAITLIST_DB: database },
    });

    expect(response.status).toBe(201);
    expect(await response.json()).toEqual({
      status: "registered",
      message: "You're on the DaemonState waitlist.",
    });
    expect(database.calls.at(-1).values[1]).toBe("builder@example.com");
  });

  it("rejects invalid and cross-origin submissions", async () => {
    const invalid = await onRequestPost({
      request: signupRequest({ email: "not-an-email" }),
      env: { WAITLIST_DB: createDatabase() },
    });
    const crossOrigin = await onRequestPost({
      request: signupRequest(
        { email: "builder@example.com" },
        { origin: "https://spam.example" },
      ),
      env: { WAITLIST_DB: createDatabase() },
    });

    expect(invalid.status).toBe(422);
    expect(crossOrigin.status).toBe(403);
  });

  it("does not store honeypot submissions", async () => {
    const database = createDatabase();
    const response = await onRequestPost({
      request: signupRequest({
        email: "bot@example.com",
        website: "https://spam.example",
      }),
      env: { WAITLIST_DB: database },
    });

    expect(response.status).toBe(201);
    expect(database.calls).toHaveLength(0);
  });

  it("reports an unavailable database without losing the request contract", async () => {
    const response = await onRequestPost({
      request: signupRequest({ email: "builder@example.com" }),
      env: {},
    });

    expect(response.status).toBe(503);
    expect(await response.json()).toEqual({
      detail: "Waitlist registration is temporarily unavailable.",
    });
  });
});
