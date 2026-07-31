from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select
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
    compaction_count = int(await session.scalar(
        select(func.count(func.distinct(SessionEvent.provider_event_id)))
        .select_from(SessionEvent)
        .join(
            SourceDocument,
            SessionEvent.source_document_id == SourceDocument.id,
        )
        .where(
            SessionEvent.workspace_id == workspace_id,
            SessionEvent.provider.in_(
                session_provider_values(normalized_provider)
            ),
            SessionEvent.session_id == normalized_session_id,
            SessionEvent.event_type == "compaction_boundary",
            source_access_predicate(
                access_scope,
                workspace_id=workspace_id,
            ),
        )
    ) or 0)
    return SessionContextEligibility(
        workspace_id=workspace_id,
        provider=normalized_provider,
        session_id=normalized_session_id,
        compaction_count=compaction_count,
    )


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
