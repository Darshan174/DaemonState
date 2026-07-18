const STORAGE_PREFIX = "ce:workspace-preferences:";

function storageKey(workspaceId) {
  return workspaceId ? `${STORAGE_PREFIX}${workspaceId}` : null;
}

export function readWorkspacePreferences(workspaceId, surface, defaults = {}) {
  const key = storageKey(workspaceId);
  if (!key || !surface) return { ...defaults };
  try {
    const stored = JSON.parse(localStorage.getItem(key) || "{}");
    const surfacePreferences = stored?.[surface];
    return surfacePreferences && typeof surfacePreferences === "object"
      ? { ...defaults, ...surfacePreferences }
      : { ...defaults };
  } catch {
    return { ...defaults };
  }
}

export function writeWorkspacePreferences(workspaceId, surface, preferences) {
  const key = storageKey(workspaceId);
  if (!key || !surface) return;
  try {
    const stored = JSON.parse(localStorage.getItem(key) || "{}");
    const next = stored && typeof stored === "object" ? stored : {};
    next[surface] = { ...preferences };
    localStorage.setItem(key, JSON.stringify(next));
  } catch {
    // Browser storage is an enhancement; workspace navigation must still work.
  }
}

export { STORAGE_PREFIX };
