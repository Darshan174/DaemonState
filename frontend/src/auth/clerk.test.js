import { describe, expect, it } from "vitest";

import { CLERK_WAITLIST_URL, clerkWaitlistEnabled } from "./clerk";

describe("Clerk waitlist configuration", () => {
  it("enables the managed waitlist only when a publishable key is present", () => {
    expect(clerkWaitlistEnabled({})).toBe(false);
    expect(clerkWaitlistEnabled({ VITE_CLERK_PUBLISHABLE_KEY: "   " })).toBe(false);
    expect(clerkWaitlistEnabled({
      VITE_CLERK_PUBLISHABLE_KEY: "pk_test_daemonstate",
    })).toBe(true);
  });

  it("returns approved users to the early-access entry point", () => {
    expect(CLERK_WAITLIST_URL).toBe("/#early-access");
  });
});
