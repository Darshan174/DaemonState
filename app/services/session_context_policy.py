from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import SessionEvent, SourceDocument
from app.services.access import AccessScope, source_access_predicate
from app.services.session_scope import normalize_session_key, session_provider_values


MINIMUM_SESSION_CONTEXT_COMPACTIONS = 2
SESSION_CONTEXT_COMPACTIONS_REQUIRED_CODE = (
    "session_context_compactions_required"
)


@dataclass(frozen=True)
class SessionContextEligibility:
    workspace_id: UUID
    provider: str
    session_id: str
    compaction_count: int
    minimum_compactions: int = MINIMUM_SESSION_CONTEXT_COMPACTIONS

    @property
    def eligible(self) -> bool:
        return self.compaction_count >= self.minimum_compactions

    @property
    def message(self) -> str:
        return (
            f"{self.minimum_compactions} compactions required "
            f"({min(self.compaction_count, self.minimum_compactions)}"
            f"/{self.minimum_compactions})."
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "workspace_id": str(self.workspace_id),
            "provider": self.provider,
            "session_id": self.session_id,
            "eligible": self.eligible,
            "compaction_count": self.compaction_count,
            "minimum_compactions": self.minimum_compactions,
            "code": (
                None
                if self.eligible
                else SESSION_CONTEXT_COMPACTIONS_REQUIRED_CODE
            ),
            "message": self.message,
        }


class SessionContextCompactionsRequiredError(ValueError):
    code = SESSION_CONTEXT_COMPACTIONS_REQUIRED_CODE
    status_code = 409

    def __init__(self, eligibility: SessionContextEligibility) -> None:
        self.eligibility = eligibility
        super().__init__(eligibility.message)

    def detail(self) -> dict[str, object]:
        return {
            "code": self.code,
            "message": str(self),
            "compaction_count": self.eligibility.compaction_count,
            "minimum_compactions": self.eligibility.minimum_compactions,
        }


async def session_context_eligibility(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    provider: str,
    session_id: str,
    access_scope: AccessScope,
) -> SessionContextEligibility:
    session_key = normalize_session_key(provider, session_id)
    if session_key is None:
        raise ValueError("provider and session_id must be non-empty")
    normalized_provider, normalized_session_id = session_key
    compaction_counts = await session_context_compaction_counts(
        session,
        workspace_id=workspace_id,
        session_keys=(session_key,),
        access_scope=access_scope,
    )
    return SessionContextEligibility(
        workspace_id=workspace_id,
        provider=normalized_provider,
        session_id=normalized_session_id,
        compaction_count=compaction_counts[session_key],
    )


async def session_context_compaction_counts(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    session_keys: Iterable[tuple[str, str]],
    access_scope: AccessScope,
) -> dict[tuple[str, str], int]:
    """Return ledger-backed compaction counts for normalized session keys.

    The Session Library and the Execute eligibility gate must project the same
    persisted events.  Reading resolver metadata or checkpoint descriptors here
    would let legacy imports and schema upgrades disagree with the gate again.
    """

    normalized_keys = {
        normalized
        for provider, session_id in session_keys
        if (normalized := normalize_session_key(provider, session_id)) is not None
    }
    if not normalized_keys:
        return {}

    provider_values = tuple(sorted({
        value
        for provider, _ in normalized_keys
        for value in session_provider_values(provider)
    }))
    session_id_values = tuple(sorted({
        session_id for _, session_id in normalized_keys
    }))
    rows = await session.execute(
        select(
            SessionEvent.provider,
            SessionEvent.session_id,
            SessionEvent.provider_event_id,
        )
        .distinct()
        .select_from(SessionEvent)
        .join(
            SourceDocument,
            SessionEvent.source_document_id == SourceDocument.id,
        )
        .where(
            SessionEvent.workspace_id == workspace_id,
            SessionEvent.provider.in_(provider_values),
            SessionEvent.session_id.in_(session_id_values),
            SessionEvent.event_type == "compaction_boundary",
            source_access_predicate(
                access_scope,
                workspace_id=workspace_id,
            ),
        )
    )
    event_ids: dict[tuple[str, str], set[str]] = defaultdict(set)
    for provider, session_id, provider_event_id in rows:
        key = normalize_session_key(provider, session_id)
        if key in normalized_keys:
            event_ids[key].add(str(provider_event_id))
    return {
        key: len(event_ids[key])
        for key in normalized_keys
    }


async def require_session_context_compactions(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    provider: str,
    session_id: str,
    access_scope: AccessScope,
) -> SessionContextEligibility:
    eligibility = await session_context_eligibility(
        session,
        workspace_id=workspace_id,
        provider=provider,
        session_id=session_id,
        access_scope=access_scope,
    )
    if not eligibility.eligible:
        raise SessionContextCompactionsRequiredError(eligibility)
    return eligibility
