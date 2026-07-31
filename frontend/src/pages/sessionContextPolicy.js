export const MINIMUM_SESSION_CONTEXT_COMPACTIONS = 2;


export function sessionContextCompactionCount(session) {
  const explicitCount = normalizedCount(
    session?.compactionCount
    ?? session?.compaction_count,
  );
  const descriptors = [
    ...(Array.isArray(session?.compactionCheckpoints)
      ? session.compactionCheckpoints
      : []),
    ...(Array.isArray(session?.compaction_checkpoints)
      ? session.compaction_checkpoints
      : []),
  ];
  const descriptorCount = new Set(
    descriptors.map((item, index) => String(
      item?.id
      || item?.event_id
      || item?.window_id
      || item?.occurred_at
      || `compaction-${index}`,
    )),
  ).size;
  return Math.max(explicitCount, descriptorCount);
}


export function sessionContextIsEligible(session) {
  return (
    sessionContextCompactionCount(session)
    >= MINIMUM_SESSION_CONTEXT_COMPACTIONS
  );
}


export function sessionContextCompactionLabel(session) {
  return sessionContextCompactionProgress(
    sessionContextCompactionCount(session),
  );
}


export function sessionContextCompactionProgress(count) {
  return `${Math.min(normalizedCount(count), MINIMUM_SESSION_CONTEXT_COMPACTIONS)}`
    + `/${MINIMUM_SESSION_CONTEXT_COMPACTIONS} compactions`;
}


function normalizedCount(value) {
  const count = Number(value);
  return Number.isFinite(count) ? Math.max(0, Math.floor(count)) : 0;
}
