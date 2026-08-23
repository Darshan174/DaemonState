export const CLERK_WAITLIST_URL = "/#early-access";

export function clerkWaitlistEnabled(environment = import.meta.env) {
  return typeof environment?.VITE_CLERK_PUBLISHABLE_KEY === "string"
    && environment.VITE_CLERK_PUBLISHABLE_KEY.trim().length > 0;
}
