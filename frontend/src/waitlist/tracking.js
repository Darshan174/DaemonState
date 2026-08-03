export const WAITLIST_CONSENT_VERSION = "2026-08-03";

const WAITLIST_EVENTS = new Set([
  "landing_viewed",
  "waitlist_cta_clicked",
  "waitlist_joined",
]);

const EVENT_PROPERTY_NAMES = new Set([
  "source",
  "referrer_host",
  "utm_source",
  "utm_medium",
  "utm_campaign",
  "utm_term",
  "utm_content",
]);

let analyticsClient = null;
let analyticsState = "disabled";
let pendingEvents = [];

function optionalValue(value, maxLength = 255) {
  if (typeof value !== "string") return null;
  const normalized = value.trim();
  if (!normalized || normalized.length > maxLength) return null;
  if ([...normalized].some((character) => {
    const codePoint = character.codePointAt(0);
    return codePoint < 32 || codePoint === 127;
  })) {
    return null;
  }
  return normalized;
}

function safePostHogHost(value) {
  const fallback = "https://us.i.posthog.com";
  const normalized = optionalValue(value, 512);
  if (!normalized) return fallback;
  try {
    const url = new URL(normalized);
    if (url.protocol !== "https:" || url.username || url.password) return fallback;
    return url.origin;
  } catch {
    return fallback;
  }
}

export async function initializeWaitlistAnalytics(environment, client = null) {
  const projectKey = optionalValue(environment?.VITE_POSTHOG_KEY, 255);
  if (!projectKey) {
    analyticsClient = null;
    analyticsState = "disabled";
    pendingEvents = [];
    return false;
  }

  analyticsState = "loading";
  try {
    const resolvedClient = client || (await import("posthog-js")).default;
    resolvedClient.init(projectKey, {
      api_host: safePostHogHost(environment?.VITE_POSTHOG_HOST),
      autocapture: false,
      capture_pageview: false,
      capture_pageleave: false,
      capture_performance: false,
      disable_capture_url_hashes: true,
      disable_session_recording: true,
      persistence: "memory",
      person_profiles: "never",
      property_denylist: [
        "$current_url",
        "$initial_current_url",
        "$session_entry_url",
        "$referrer",
        "$initial_referrer",
      ],
      respect_dnt: true,
      save_referrer: false,
    });
    analyticsClient = resolvedClient;
    analyticsState = "ready";
    for (const [eventName, properties] of pendingEvents) {
      analyticsClient.capture(eventName, properties);
    }
    pendingEvents = [];
    return true;
  } catch {
    analyticsClient = null;
    analyticsState = "disabled";
    pendingEvents = [];
    return false;
  }
}

export function waitlistAttribution(
  location = globalThis.location,
  referrer = globalThis.document?.referrer || "",
) {
  const search = new URLSearchParams(location?.search || "");
  const attribution = {
    referrer: null,
    utm_source: optionalValue(search.get("utm_source")),
    utm_medium: optionalValue(search.get("utm_medium")),
    utm_campaign: optionalValue(search.get("utm_campaign")),
    utm_term: optionalValue(search.get("utm_term")),
    utm_content: optionalValue(search.get("utm_content")),
  };

  const normalizedReferrer = optionalValue(referrer, 1024);
  if (!normalizedReferrer) return attribution;
  try {
    const url = new URL(normalizedReferrer);
    if (!["http:", "https:"].includes(url.protocol) || url.username || url.password) {
      return attribution;
    }
    url.search = "";
    url.hash = "";
    attribution.referrer = url.toString();
  } catch {
    // Invalid referrers are ignored rather than sent to the waitlist API.
  }
  return attribution;
}

export function analyticsAttribution(attribution) {
  let referrerHost = null;
  if (attribution?.referrer) {
    try {
      referrerHost = new URL(attribution.referrer).host;
    } catch {
      referrerHost = null;
    }
  }
  return {
    source: "landing",
    referrer_host: referrerHost,
    utm_source: attribution?.utm_source || null,
    utm_medium: attribution?.utm_medium || null,
    utm_campaign: attribution?.utm_campaign || null,
    utm_term: attribution?.utm_term || null,
    utm_content: attribution?.utm_content || null,
  };
}

export function captureWaitlistEvent(eventName, properties = {}) {
  if (!WAITLIST_EVENTS.has(eventName)) return false;
  const safeProperties = Object.fromEntries(
    Object.entries(properties).filter(([name, value]) => (
      EVENT_PROPERTY_NAMES.has(name)
      && ["string", "number", "boolean"].includes(typeof value)
      && value !== ""
    )),
  );
  if (analyticsState === "loading") {
    if (pendingEvents.length < 10) pendingEvents.push([eventName, safeProperties]);
    return true;
  }
  if (!analyticsClient || analyticsState !== "ready") return false;
  analyticsClient.capture(eventName, safeProperties);
  return true;
}

export function resetWaitlistAnalyticsForTests() {
  analyticsClient = null;
  analyticsState = "disabled";
  pendingEvents = [];
}
