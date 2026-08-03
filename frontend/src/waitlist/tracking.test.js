import { afterEach, describe, expect, it, vi } from "vitest";

import {
  analyticsAttribution,
  captureWaitlistEvent,
  initializeWaitlistAnalytics,
  resetWaitlistAnalyticsForTests,
  waitlistAttribution,
} from "./tracking";


afterEach(() => {
  resetWaitlistAnalyticsForTests();
});

describe("waitlist tracking", () => {
  it("keeps analytics disabled when no project key is configured", async () => {
    const client = { init: vi.fn(), capture: vi.fn() };

    await expect(initializeWaitlistAnalytics({}, client)).resolves.toBe(false);
    expect(captureWaitlistEvent("landing_viewed", { source: "landing" })).toBe(false);
    expect(client.init).not.toHaveBeenCalled();
    expect(client.capture).not.toHaveBeenCalled();
  });

  it("initializes manual, memory-only analytics", async () => {
    const client = { init: vi.fn(), capture: vi.fn() };

    await expect(initializeWaitlistAnalytics({
      VITE_POSTHOG_KEY: "phc_project",
      VITE_POSTHOG_HOST: "https://eu.i.posthog.com/path",
    }, client)).resolves.toBe(true);

    expect(client.init).toHaveBeenCalledWith("phc_project", expect.objectContaining({
      api_host: "https://eu.i.posthog.com",
      autocapture: false,
      capture_pageview: false,
      capture_pageleave: false,
      capture_performance: false,
      disable_capture_url_hashes: true,
      disable_session_recording: true,
      persistence: "memory",
      person_profiles: "never",
      property_denylist: expect.arrayContaining([
        "$current_url",
        "$referrer",
      ]),
      respect_dnt: true,
      save_referrer: false,
    }));
  });

  it("captures only allow-listed, non-PII waitlist properties", async () => {
    const client = { init: vi.fn(), capture: vi.fn() };
    await initializeWaitlistAnalytics({ VITE_POSTHOG_KEY: "phc_project" }, client);

    expect(captureWaitlistEvent("waitlist_joined", {
      source: "landing",
      utm_source: "launch-post",
      referrer_host: "news.example",
      email: "private@example.com",
      notes: "secret",
      utm_term: null,
    })).toBe(true);
    expect(captureWaitlistEvent("unexpected_event", {})).toBe(false);

    expect(client.capture).toHaveBeenCalledOnce();
    expect(client.capture).toHaveBeenCalledWith("waitlist_joined", {
      source: "landing",
      utm_source: "launch-post",
      referrer_host: "news.example",
    });
  });

  it("extracts campaign fields and removes private referrer details", () => {
    const attribution = waitlistAttribution(
      {
        search: "?utm_source=Launch%20Post&utm_medium=social&utm_campaign=beta",
      },
      "https://news.example/launch?reader=private#comments",
    );

    expect(attribution).toEqual({
      referrer: "https://news.example/launch",
      utm_source: "Launch Post",
      utm_medium: "social",
      utm_campaign: "beta",
      utm_term: null,
      utm_content: null,
    });
    expect(analyticsAttribution(attribution)).toMatchObject({
      source: "landing",
      referrer_host: "news.example",
      utm_source: "Launch Post",
    });
  });
});
