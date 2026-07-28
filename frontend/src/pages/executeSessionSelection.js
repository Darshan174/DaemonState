import {
  readWorkspacePreferences,
  writeWorkspacePreferences,
} from "../context/workspacePreferences";

export const MAX_EXECUTE_SESSION_CONTEXTS = 3;

const EXECUTE_PREFERENCES_SURFACE = "execute";
const SESSION_CONTEXTS_KEY = "sessionContexts";


export function executeSessionIdentity(session) {
  const provider = normalizeProvider(
    session?.provider
    || session?.connector_type,
  );
  const sessionId = cleanText(
    session?.sessionId
    || session?.session_id,
  );
  return provider && sessionId ? `${provider}:${sessionId}` : "";
}


export function normalizeExecuteSessionContext(session) {
  const sourceDocumentId = cleanText(
    session?.sourceDocumentId
    || session?.source_document_id,
  );
  const provider = normalizeProvider(
    session?.provider
    || session?.connector_type,
  );
  const sessionId = cleanText(
    session?.sessionId
    || session?.session_id,
  );
  if (!sourceDocumentId || !provider || !sessionId) return null;

  return {
    sourceDocumentId,
    provider,
    sessionId,
    title: cleanText(session?.title) || "Untitled session",
    harness: cleanText(session?.harness),
    topic: cleanText(
      session?.topic
      || session?.selected_topic
      || session?.latest_topic,
    ),
    preview: cleanText(session?.preview),
    updatedAt: cleanText(
      session?.updatedAt
      || session?.updated_at,
    ),
  };
}


export function normalizeExecuteSessionContexts(sessions) {
  const result = [];
  const seenSources = new Set();
  const seenSessions = new Set();
  for (const value of Array.isArray(sessions) ? sessions : []) {
    const session = normalizeExecuteSessionContext(value);
    if (!session) continue;
    const identity = executeSessionIdentity(session);
    if (
      seenSources.has(session.sourceDocumentId)
      || seenSessions.has(identity)
    ) continue;
    seenSources.add(session.sourceDocumentId);
    seenSessions.add(identity);
    result.push(session);
    if (result.length === MAX_EXECUTE_SESSION_CONTEXTS) break;
  }
  return result;
}


export function readExecuteSessionContexts(workspaceId) {
  const preferences = readWorkspacePreferences(
    workspaceId,
    EXECUTE_PREFERENCES_SURFACE,
    { [SESSION_CONTEXTS_KEY]: [] },
  );
  return normalizeExecuteSessionContexts(preferences[SESSION_CONTEXTS_KEY]);
}


export function writeExecuteSessionContexts(workspaceId, sessions) {
  const preferences = readWorkspacePreferences(
    workspaceId,
    EXECUTE_PREFERENCES_SURFACE,
    {},
  );
  const normalized = normalizeExecuteSessionContexts(sessions);
  writeWorkspacePreferences(workspaceId, EXECUTE_PREFERENCES_SURFACE, {
    ...preferences,
    [SESSION_CONTEXTS_KEY]: normalized,
  });
  return normalized;
}


export function resolveExecuteSessionContexts(storedSessions, librarySessions) {
  const stored = normalizeExecuteSessionContexts(storedSessions);
  if (!Array.isArray(librarySessions)) return stored;

  const libraryBySource = new Map(
    librarySessions
      .map((session) => normalizeExecuteSessionContext(session))
      .filter(Boolean)
      .map((session) => [session.sourceDocumentId, session]),
  );
  const libraryByIdentity = new Map(
    [...libraryBySource.values()]
      .map((session) => [executeSessionIdentity(session), session]),
  );
  return normalizeExecuteSessionContexts(
    stored
      .map((session) => (
        libraryBySource.get(session.sourceDocumentId)
        || libraryByIdentity.get(executeSessionIdentity(session))
      ))
      .filter(Boolean),
  );
}


function cleanText(value) {
  return value === null || value === undefined ? "" : String(value).trim();
}


function normalizeProvider(value) {
  const provider = cleanText(value).toLowerCase().replace(/^daemonstate:/, "");
  if (["claude code", "claude_code", "claude-code"].includes(provider)) {
    return "claude";
  }
  if (["open code", "open_code", "open-code"].includes(provider)) {
    return "opencode";
  }
  return provider;
}
