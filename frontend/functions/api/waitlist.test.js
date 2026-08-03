import { afterEach, describe, expect, it, vi } from "vitest";

import { WAITLIST_CONSENT_VERSION, onRequestPost } from "./waitlist";


function createDatabase({ signup = null, fail = false } = {}) {
  const calls = [];
  let storedSignup = signup;

  return {
    calls,
    get signup() {
      return storedSignup;
    },
    prepare(sql) {
      let values = [];
      const statement = {
        bind(...nextValues) {
          values = nextValues;
          calls.push({ sql, values });
          return statement;
        },
        async first() {
          if (fail) throw new Error("database unavailable");
          return storedSignup;
        },
        async run() {
          if (fail) throw new Error("database unavailable");
          if (sql.includes("INSERT INTO waitlist_signups") && !storedSignup) {
            storedSignup = {
              id: values[0],
              email: values[1],
              source: "landing",
              referrer: values[2],
              utm_source: values[3],
              utm_medium: values[4],
              utm_campaign: values[5],
              utm_term: values[6],
              utm_content: values[7],
              consent_version: values[8],
              email_sync_status: "pending",
            };
          } else if (sql.includes("email_sync_status = 'synced'")) {
            storedSignup.email_sync_status = "synced";
          } else if (sql.includes("email_sync_status = 'failed'")) {
            storedSignup.email_sync_status = "failed";
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
    body: JSON.stringify({
      consent_version: WAITLIST_CONSENT_VERSION,
      ...body,
    }),
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Cloudflare waitlist function", () => {
  it("normalizes and stores a valid attributed signup", async () => {
    const database = createDatabase();
    const response = await onRequestPost({
      request: signupRequest({
        email: " Builder@Example.COM ",
        website: "",
        referrer: "https://news.example/launch?reader=private#comments",
        utm_source: " Newsletter ",
        utm_medium: "email",
        utm_campaign: "private-beta",
      }),
      env: { WAITLIST_DB: database },
    });

    expect(response.status).toBe(201);
    expect(await response.json()).toEqual({
      status: "registered",
      message: "You're on the DaemonState waitlist.",
    });
    expect(database.signup).toMatchObject({
      email: "builder@example.com",
      source: "landing",
      referrer: "https://news.example/launch",
      utm_source: "Newsletter",
      utm_medium: "email",
      utm_campaign: "private-beta",
      consent_version: WAITLIST_CONSENT_VERSION,
      email_sync_status: "pending",
    });
  });

  it("rejects invalid, cross-origin, and unknown-consent submissions", async () => {
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
    const unknownConsent = await onRequestPost({
      request: signupRequest({
        email: "builder@example.com",
        consent_version: "legacy",
      }),
      env: { WAITLIST_DB: createDatabase() },
    });
    const unsafeReferrer = await onRequestPost({
      request: signupRequest({
        email: "builder@example.com",
        referrer: "javascript:alert(1)",
      }),
      env: { WAITLIST_DB: createDatabase() },
    });

    expect(invalid.status).toBe(422);
    expect(crossOrigin.status).toBe(403);
    expect(unknownConsent.status).toBe(422);
    expect(unsafeReferrer.status).toBe(422);
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

  it("synchronizes Loops only after the signup is durable", async () => {
    const database = createDatabase();
    const pending = [];
    let resolveLoopsRequest;
    const fetchMock = vi.fn().mockImplementation(() => new Promise((resolve) => {
      resolveLoopsRequest = resolve;
    }));
    vi.stubGlobal("fetch", fetchMock);

    const response = await onRequestPost({
      request: signupRequest({
        email: "builder@example.com",
        utm_source: "launch-post",
      }),
      env: {
        WAITLIST_DB: database,
        LOOPS_API_KEY: "loops-secret",
        LOOPS_WAITLIST_EVENT: "waitlistJoined",
      },
      waitUntil(promise) {
        pending.push(promise);
      },
    });

    expect(response.status).toBe(201);
    expect(database.signup.email_sync_status).toBe("pending");
    resolveLoopsRequest(new Response(
      JSON.stringify({ success: true }),
      { status: 200, headers: { "content-type": "application/json" } },
    ));
    await Promise.all(pending);

    expect(fetchMock).toHaveBeenCalledOnce();
    const [, options] = fetchMock.mock.calls[0];
    const body = JSON.parse(options.body);
    expect(options.headers.Authorization).toBe("Bearer loops-secret");
    expect(options.headers["Idempotency-Key"]).toBe(`waitlist-${database.signup.id}`);
    expect(body).toMatchObject({
      email: "builder@example.com",
      userId: database.signup.id,
      eventName: "waitlistJoined",
      source: "DaemonState waitlist",
      userGroup: "Waitlist",
      eventProperties: {
        signupId: database.signup.id,
        signupSource: "landing",
        utmSource: "launch-post",
        consentVersion: WAITLIST_CONSENT_VERSION,
      },
    });
    expect(database.signup.email_sync_status).toBe("synced");
  });

  it("keeps a durable signup when Loops is unavailable", async () => {
    const database = createDatabase();
    const pending = [];
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network down")));

    const response = await onRequestPost({
      request: signupRequest({ email: "builder@example.com" }),
      env: { WAITLIST_DB: database, LOOPS_API_KEY: "loops-secret" },
      waitUntil(promise) {
        pending.push(promise);
      },
    });
    await Promise.all(pending);

    expect(response.status).toBe(201);
    expect(database.signup.email).toBe("builder@example.com");
    expect(database.signup.email_sync_status).toBe("failed");
  });
});
