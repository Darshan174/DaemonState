export function waitlistOnly(environment) {
  return environment.VITE_WAITLIST_ONLY === "true";
}

export const WAITLIST_ONLY = waitlistOnly(import.meta.env);
