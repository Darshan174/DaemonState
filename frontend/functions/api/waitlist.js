const EMAIL_PATTERN = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
const MAX_REQUEST_BYTES = 4096;
const MAX_ATTRIBUTION_LENGTH = 255;
const MAX_REFERRER_LENGTH = 1024;
const LOOPS_EVENTS_URL = "https://app.loops.so/api/v1/events/send";

export const WAITLIST_CONSENT_VERSION = "2026-08-03";

const ATTRIBUTION_FIELDS = [
  "utm_source",
  "utm_medium",
  "utm_campaign",
  "utm_term",
  "utm_content",
];

function jsonResponse(body, status) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
      "x-content-type-options": "nosniff",
    },
  });
}

function normalizeEmail(value) {
  if (typeof value !== "string") return null;
  const email = value.trim().toLowerCase();
  const localPart = email.includes("@") ? email.split("@", 1)[0] : "";
  if (
    email.length < 3
    || email.length > 320
    || localPart.length > 64
    || email.startsWith(".")
    || email.includes("..")
    || !EMAIL_PATTERN.test(email)
  ) {
    return null;
  }
  return email;
}

function normalizeOptionalText(value, maxLength) {
  if (value === undefined || value === null || value === "") {
    return { valid: true, value: null };
  }
  if (typeof value !== "string") {
    return { valid: false, value: null };
  }
  const normalized = value.trim();
  if (!normalized) return { valid: true, value: null };
  if (
    normalized.length > maxLength
    || [...normalized].some((character) => {
      const codePoint = character.codePointAt(0);
      return codePoint < 32 || codePoint === 127;
    })
  ) {
    return { valid: false, value: null };
  }
  return { valid: true, value: normalized };
}

function normalizeReferrer(value) {
  const normalized = normalizeOptionalText(value, MAX_REFERRER_LENGTH);
  if (!normalized.valid || !normalized.value) return normalized;
  try {
    const url = new URL(normalized.value);
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) {
      return { valid: false, value: null };
    }
    url.search = "";
    url.hash = "";
    return { valid: true, value: url.toString() };
  } catch {
    return { valid: false, value: null };
  }
}

function normalizeAttribution(payload) {
  const referrer = normalizeReferrer(payload?.referrer);
  if (!referrer.valid) return null;

  const values = { referrer: referrer.value };
  for (const field of ATTRIBUTION_FIELDS) {
    const result = normalizeOptionalText(payload?.[field], MAX_ATTRIBUTION_LENGTH);
    if (!result.valid) return null;
    values[field] = result.value;
  }
  return values;
}

function loopsEventName(env) {
  const configured = typeof env.LOOPS_WAITLIST_EVENT === "string"
    ? env.LOOPS_WAITLIST_EVENT.trim()
    : "";
  return /^[A-Za-z][A-Za-z0-9_-]{0,63}$/.test(configured)
    ? configured
    : "waitlistJoined";
}

function compactProperties(signup) {
  const properties = {
    signupId: signup.id,
    signupSource: signup.source,
    referrer: signup.referrer,
    utmSource: signup.utm_source,
    utmMedium: signup.utm_medium,
    utmCampaign: signup.utm_campaign,
    utmTerm: signup.utm_term,
    utmContent: signup.utm_content,
    consentVersion: signup.consent_version,
  };
  return Object.fromEntries(
    Object.entries(properties).filter(([, value]) => value !== null && value !== ""),
  );
}

async function updateEmailSync(database, signupId, status, error = null) {
  if (status === "synced") {
    await database
      .prepare(`
        UPDATE waitlist_signups
        SET email_sync_status = 'synced',
            email_synced_at = CURRENT_TIMESTAMP,
            email_sync_error = NULL,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?1
      `)
      .bind(signupId)
      .run();
    return;
  }

  await database
    .prepare(`
      UPDATE waitlist_signups
      SET email_sync_status = 'failed',
          email_sync_error = ?2,
          updated_at = CURRENT_TIMESTAMP
      WHERE id = ?1
    `)
    .bind(signupId, error?.slice(0, 255) || "loops_sync_failed")
    .run();
}

async function syncSignupToLoops(signup, env, database) {
  const apiKey = typeof env.LOOPS_API_KEY === "string"
    ? env.LOOPS_API_KEY.trim()
    : "";
  if (!apiKey || signup.email_sync_status === "synced") return;

  try {
    const response = await fetch(LOOPS_EVENTS_URL, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${apiKey}`,
        "Content-Type": "application/json",
        "Idempotency-Key": `waitlist-${signup.id}`,
      },
      body: JSON.stringify({
        email: signup.email,
        userId: signup.id,
        eventName: loopsEventName(env),
        source: "DaemonState waitlist",
        userGroup: "Waitlist",
        eventProperties: compactProperties(signup),
      }),
    });
    // A 409 means Loops already accepted this idempotency key within its
    // replay window, which is equivalent to a successful synchronization.
    if (!response.ok && response.status !== 409) {
      throw new Error(`loops_http_${response.status}`);
    }
    await updateEmailSync(database, signup.id, "synced");
  } catch (error) {
    const message = error instanceof Error ? error.message : "loops_sync_failed";
    try {
      await updateEmailSync(database, signup.id, "failed", message);
    } catch {
      // The signup itself is already durable. A later duplicate submission or
      // the admin retry path can recover a provider-sync failure.
    }
  }
}

function scheduleLoopsSync(context, signup) {
  const apiKey = typeof context.env.LOOPS_API_KEY === "string"
    ? context.env.LOOPS_API_KEY.trim()
    : "";
  if (!apiKey || signup.email_sync_status === "synced") return null;

  const sync = syncSignupToLoops(signup, context.env, context.env.WAITLIST_DB);
  if (typeof context.waitUntil === "function") {
    context.waitUntil(sync);
    return null;
  }
  return sync;
}

export async function onRequestPost(context) {
  const { request, env } = context;
  const requestUrl = new URL(request.url);
  const origin = request.headers.get("origin");
  if (origin) {
    try {
      if (new URL(origin).origin !== requestUrl.origin) {
        return jsonResponse({ detail: "Cross-origin submissions are not allowed." }, 403);
      }
    } catch {
      return jsonResponse({ detail: "Cross-origin submissions are not allowed." }, 403);
    }
  }

  const contentLength = Number(request.headers.get("content-length") || 0);
  if (contentLength > MAX_REQUEST_BYTES) {
    return jsonResponse({ detail: "Request body is too large." }, 413);
  }

  let rawBody;
  try {
    rawBody = await request.text();
  } catch {
    return jsonResponse({ detail: "Enter a valid email address." }, 422);
  }
  if (new TextEncoder().encode(rawBody).byteLength > MAX_REQUEST_BYTES) {
    return jsonResponse({ detail: "Request body is too large." }, 413);
  }

  let payload;
  try {
    payload = JSON.parse(rawBody);
  } catch {
    return jsonResponse({ detail: "Enter a valid email address." }, 422);
  }

  const email = normalizeEmail(payload?.email);
  const attribution = normalizeAttribution(payload);
  if (
    !email
    || !attribution
    || payload?.consent_version !== WAITLIST_CONSENT_VERSION
  ) {
    return jsonResponse({ detail: "Enter a valid email address." }, 422);
  }

  if (typeof payload.website === "string" && payload.website.trim()) {
    return jsonResponse({
      status: "registered",
      message: "You're on the DaemonState waitlist.",
    }, 201);
  }

  const database = env.WAITLIST_DB;
  if (!database) {
    return jsonResponse({
      detail: "Waitlist registration is temporarily unavailable.",
    }, 503);
  }

  let signup;
  try {
    await database
      .prepare(`
        INSERT INTO waitlist_signups (
          id,
          email,
          source,
          referrer,
          utm_source,
          utm_medium,
          utm_campaign,
          utm_term,
          utm_content,
          consent_at,
          consent_version
        )
        VALUES (
          ?1, ?2, 'landing', ?3, ?4, ?5, ?6, ?7, ?8,
          CURRENT_TIMESTAMP, ?9
        )
        ON CONFLICT(email) DO NOTHING
      `)
      .bind(
        crypto.randomUUID(),
        email,
        attribution.referrer,
        attribution.utm_source,
        attribution.utm_medium,
        attribution.utm_campaign,
        attribution.utm_term,
        attribution.utm_content,
        WAITLIST_CONSENT_VERSION,
      )
      .run();
    signup = await database
      .prepare(`
        SELECT
          id,
          email,
          source,
          referrer,
          utm_source,
          utm_medium,
          utm_campaign,
          utm_term,
          utm_content,
          consent_version,
          email_sync_status
        FROM waitlist_signups
        WHERE email = ?1
        LIMIT 1
      `)
      .bind(email)
      .first();
    if (!signup) throw new Error("waitlist_signup_not_found");
  } catch {
    return jsonResponse({
      detail: "Waitlist registration is temporarily unavailable.",
    }, 503);
  }

  const pendingSync = scheduleLoopsSync(context, signup);
  if (pendingSync) await pendingSync;

  return jsonResponse({
    status: "registered",
    message: "You're on the DaemonState waitlist.",
  }, 201);
}
