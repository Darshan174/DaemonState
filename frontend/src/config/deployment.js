const PUBLIC_WAITLIST_HOSTS = new Set([
  "daemonstate.com",
  "www.daemonstate.com",
]);

export function waitlistOnly(
  environment = {},
  hostname = globalThis.location?.hostname ?? "",
) {
  if (environment.VITE_WAITLIST_ONLY === "true") return true;
  if (environment.VITE_WAITLIST_ONLY === "false") return false;

  const normalizedHostname = String(hostname).trim().toLowerCase().replace(/\.$/, "");
  return PUBLIC_WAITLIST_HOSTS.has(normalizedHostname);
}

export const WAITLIST_ONLY = waitlistOnly(import.meta.env);
