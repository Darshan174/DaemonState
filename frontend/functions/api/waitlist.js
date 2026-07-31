const EMAIL_PATTERN = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
const MAX_REQUEST_BYTES = 2048;

const CREATE_TABLE_SQL = `
  CREATE TABLE IF NOT EXISTS waitlist_signups (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
    source TEXT NOT NULL DEFAULT 'landing',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
  )
`;

const CREATE_INDEX_SQL = `
  CREATE INDEX IF NOT EXISTS ix_waitlist_signups_created_at
  ON waitlist_signups (created_at)
`;

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

export async function onRequestPost({ request, env }) {
  const requestUrl = new URL(request.url);
  const origin = request.headers.get("origin");
  if (origin) {
    try {
      if (new URL(origin).host !== requestUrl.host) {
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

  let payload;
  try {
    payload = await request.json();
  } catch {
    return jsonResponse({ detail: "Enter a valid email address." }, 422);
  }

  const email = normalizeEmail(payload?.email);
  if (!email) {
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

  try {
    await database.prepare(CREATE_TABLE_SQL).run();
    await database.prepare(CREATE_INDEX_SQL).run();
    await database
      .prepare(`
        INSERT INTO waitlist_signups (id, email, source)
        VALUES (?1, ?2, 'landing')
        ON CONFLICT(email) DO NOTHING
      `)
      .bind(crypto.randomUUID(), email)
      .run();
  } catch {
    return jsonResponse({
      detail: "Waitlist registration is temporarily unavailable.",
    }, 503);
  }

  return jsonResponse({
    status: "registered",
    message: "You're on the DaemonState waitlist.",
  }, 201);
}
