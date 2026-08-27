export function waitlistOnly(environment) {
  if (environment.VITE_WAITLIST_ONLY === "true") return true;
  if (environment.VITE_WAITLIST_ONLY === "false") return false;
  return environment.MODE === "production";
}

export const WAITLIST_ONLY = waitlistOnly(import.meta.env);
