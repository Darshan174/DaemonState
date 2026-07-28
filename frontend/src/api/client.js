/**
 * Centralized API client for DaemonState.
 *
 * - In dev, Vite proxies /api → http://localhost:8000/api
 * - Every request goes through `apiFetch`, which returns the JSON body
 *   or throws an `ApiError` with status + detail.
 */

const BASE = "/api";

export class ApiError extends Error {
  constructor(status, detail) {
    const message = typeof detail === "string"
      ? detail
      : detail?.message || detail?.detail?.message || "The request could not be completed.";
    super(message);
    this.status = status;
    this.detail = detail;
  }
}

export async function apiFetch(path, options = {}) {
  const url = `${BASE}${path}`;
  const {
    timeoutMs,
    timeoutMessage,
    signal: callerSignal,
    headers,
    ...fetchOptions
  } = options;
  const timeoutController = timeoutMs ? new AbortController() : null;
  let timedOut = false;
  let timeoutId;
  const abortFromCaller = () => timeoutController?.abort(callerSignal?.reason);
  if (timeoutController && callerSignal) {
    if (callerSignal.aborted) abortFromCaller();
    else callerSignal.addEventListener("abort", abortFromCaller, { once: true });
  }
  if (timeoutController) {
    timeoutId = globalThis.setTimeout(() => {
      timedOut = true;
      timeoutController.abort();
    }, timeoutMs);
  }

  try {
    const res = await fetch(url, {
      headers: { "Content-Type": "application/json", ...headers },
      ...fetchOptions,
      signal: timeoutController?.signal || callerSignal,
    });

    if (!res.ok) {
      let detail;
      try {
        const body = await res.json();
        detail = body.detail ?? body;
      } catch (error) {
        if (timedOut) throw error;
        detail = res.statusText;
      }
      throw new ApiError(res.status, detail);
    }

    if (res.status === 204) return null;
    return await res.json();
  } catch (error) {
    if (!timedOut) throw error;
    throw new ApiError(504, {
      code: "request_timeout",
      message: timeoutMessage
        || "The request timed out before the local service responded.",
    });
  } finally {
    if (timeoutId) globalThis.clearTimeout(timeoutId);
    callerSignal?.removeEventListener?.("abort", abortFromCaller);
  }
}

// ── Convenience methods ────────────────────────────────────────

export const api = {
  get: (path, options = {}) => apiFetch(path, options),
  post: (path, body, options = {}) => apiFetch(path, {
    ...options,
    method: "POST",
    body: JSON.stringify(body),
  }),
  put: (path, body, options = {}) => apiFetch(path, {
    ...options,
    method: "PUT",
    body: JSON.stringify(body),
  }),
  patch: (path, body, options = {}) => apiFetch(path, {
    ...options,
    method: "PATCH",
    body: JSON.stringify(body),
  }),
  delete: (path, options = {}) => apiFetch(path, {
    ...options,
    method: "DELETE",
  }),
};
