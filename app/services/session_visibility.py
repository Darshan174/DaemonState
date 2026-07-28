from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import SourceDocument
from app.services.session_summary import (
    is_internal_session_content,
    persisted_session_internal,
)
from app.services.workspace_scope import metadata_dict


_INTERNAL_ASSESSMENT_MARKER = (
    "the following is the codex agent history whose request action you are assessing"
)
_INTERNAL_TRANSCRIPT_MARKER = ">>> transcript start"


async def internal_session_document_ids(
    session: AsyncSession,
    documents: Iterable[SourceDocument],
) -> set[UUID]:
    """Classify internal assessment sessions without trusting a text prefix."""

    internal_ids: set[UUID] = set()
    unresolved_ids: set[UUID] = set()
    for document in documents:
        if document.source_type != "agent_session":
            continue
        persisted = persisted_session_internal(
            metadata_dict(document),
            content_sha256=document.content_sha256,
        )
        if persisted is True:
            internal_ids.add(document.id)
        elif persisted is None:
            unresolved_ids.add(document.id)

    if not unresolved_ids:
        return internal_ids

    # An internal assessment must contain both markers. Let the database reject
    # obvious non-candidates, then run the exact first-three-user-turn parser on
    # the small candidate set so a long opening envelope cannot evade filtering.
    lowered_content = func.lower(SourceDocument.content)
    rows = await session.execute(
        select(SourceDocument.id, SourceDocument.content).where(
            SourceDocument.id.in_(unresolved_ids),
            lowered_content.contains(
                _INTERNAL_ASSESSMENT_MARKER,
                autoescape=True,
            ),
            lowered_content.contains(
                _INTERNAL_TRANSCRIPT_MARKER,
                autoescape=True,
            ),
        )
    )
    internal_ids.update(
        source_id
        for source_id, content in rows
        if is_internal_session_content(content)
    )
    return internal_ids
