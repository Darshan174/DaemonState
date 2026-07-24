from __future__ import annotations

import hashlib
import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from app.api.dependencies import get_access_scope
from app.database import get_db_session
from app.models import SessionEvent, SourceDocument, Workspace
from app.services.access import AccessScope, source_access_predicate
from app.services.harness_launcher import HarnessLaunchError, launch_harness_session
from app.services.session_ledger import (
    SESSION_LEDGER_EVENT_TYPES,
    SESSION_LEDGER_FILE_TOOL_NAMES,
    build_session_ledger,
    build_session_ledgers,
    render_session_ledger_markdown,
)
from app.services.session_scope import (
    normalize_session_key,
    scoped_session_documents,
    session_document_is_in_scope,
    session_reference,
)
from app.services.session_summary import derive_session_topic, is_internal_session_content
from app.services.workspace_scope import current_source_documents


router = APIRouter()


class SessionContinuationRequest(BaseModel):
    workspace_id: UUID
    source_document_id: UUID
    launch_session: bool = False


@router.get("/session-continuity")
async def get_session_continuity(
    workspace_id: UUID,
    session: AsyncSession = Depends(get_db_session),
    access_scope: AccessScope = Depends(get_access_scope),
) -> dict:
    await _require_workspace(session, workspace_id, access_scope)
    documents = list(await session.scalars(
        select(SourceDocument).where(
            SourceDocument.workspace_id == workspace_id,
            SourceDocument.source_type == "agent_session",
            source_access_predicate(access_scope, workspace_id=workspace_id),
        )
    ))
    current_documents, _ = current_source_documents(documents)
    current_documents = [
        document
        for document in current_documents
        if not is_internal_session_content(document.content)
    ]
    scoped_documents = await scoped_session_documents(
        session,
        workspace_id,
        current_documents,
    )
    allowed_sessions = {
        normalize_session_key(*session_reference(document))
        for document in scoped_documents
    }
    allowed_sessions.discard(None)
    if not allowed_sessions:
        return {"sessions": []}
    events = list(await session.scalars(
        select(SessionEvent)
        .join(SourceDocument, SessionEvent.source_document_id == SourceDocument.id)
        .where(
            SessionEvent.workspace_id == workspace_id,
            _ledger_event_predicate(),
            SourceDocument.source_type == "agent_session",
            source_access_predicate(access_scope, workspace_id=workspace_id),
        )
        .options(load_only(
            SessionEvent.id,
            SessionEvent.source_document_id,
            SessionEvent.provider,
            SessionEvent.session_id,
            SessionEvent.provider_event_id,
            SessionEvent.sequence_number,
            SessionEvent.event_type,
            SessionEvent.role,
            SessionEvent.occurred_at,
            SessionEvent.content,
            SessionEvent.payload_json,
            SessionEvent.created_at,
        ))
        .order_by(
            SessionEvent.provider,
            SessionEvent.session_id,
            SessionEvent.sequence_number,
            SessionEvent.id,
        )
    ))
    events = [
        event
        for event in events
        if normalize_session_key(event.provider, event.session_id) in allowed_sessions
    ]
    return {"sessions": build_session_ledgers(events)}


@router.post("/session-continuity/continue")
async def continue_session_with_recovered_context(
    body: SessionContinuationRequest,
    session: AsyncSession = Depends(get_db_session),
    access_scope: AccessScope = Depends(get_access_scope),
) -> dict:
    await _require_workspace(session, body.workspace_id, access_scope)
    source = await session.scalar(select(SourceDocument).where(
        SourceDocument.id == body.source_document_id,
        SourceDocument.workspace_id == body.workspace_id,
        SourceDocument.source_type == "agent_session",
        source_access_predicate(access_scope, workspace_id=body.workspace_id),
    ))
    if (
        source is None
        or not await session_document_is_in_scope(
            session,
            body.workspace_id,
            source,
        )
    ):
        raise HTTPException(status_code=404, detail="Session source not found")

    metadata = _metadata(source.metadata_json)
    provider = str(
        metadata.get("connector_type") or metadata.get("tool") or "unknown"
    ).strip().lower()
    if provider == "claude_code":
        provider = "claude"
    session_id = str(
        metadata.get("session_id") or source.external_id.rsplit(":", 1)[-1]
    ).strip()
    events = list(await session.scalars(
        select(SessionEvent)
        .join(SourceDocument, SessionEvent.source_document_id == SourceDocument.id)
        .where(
            SessionEvent.workspace_id == body.workspace_id,
            SessionEvent.provider == provider,
            SessionEvent.session_id == session_id,
            _ledger_event_predicate(),
            SourceDocument.source_type == "agent_session",
            source_access_predicate(access_scope, workspace_id=body.workspace_id),
        )
        .options(load_only(
            SessionEvent.id,
            SessionEvent.source_document_id,
            SessionEvent.provider,
            SessionEvent.session_id,
            SessionEvent.provider_event_id,
            SessionEvent.sequence_number,
            SessionEvent.event_type,
            SessionEvent.role,
            SessionEvent.occurred_at,
            SessionEvent.content,
            SessionEvent.payload_json,
            SessionEvent.created_at,
        ))
        .order_by(SessionEvent.sequence_number, SessionEvent.id)
    ))
    if not events:
        raise HTTPException(status_code=404, detail="Session evidence not found")

    title = derive_session_topic(
        source.content,
        explicit_title=metadata.get("title"),
        tool=provider,
        session_id=session_id,
    ) or "Untitled session"
    ledger = build_session_ledger(events)
    content = render_session_ledger_markdown(ledger, session_title=title)
    launch = None
    if body.launch_session:
        if access_scope.principal_id != "local":
            raise HTTPException(
                status_code=403,
                detail="Native session resume is available only from the local app.",
            )
        if not metadata.get("source_path"):
            launch = {
                "launched": False,
                "message": "This session is not linked to local harness history.",
            }
        else:
            try:
                launch = launch_harness_session(
                    provider,
                    session_id,
                    cwd=metadata.get("cwd"),
                )
            except HarnessLaunchError as exc:
                launch = {
                    "launched": False,
                    "code": exc.code,
                    "message": str(exc),
                }

    return {
        "schema_version": "session_continuation.v1",
        "source_document_id": str(source.id),
        "provider": provider,
        "session_id": session_id,
        "content": content,
        "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "launch": launch,
    }


async def _require_workspace(
    session: AsyncSession,
    workspace_id: UUID,
    access_scope: AccessScope,
) -> Workspace:
    if not access_scope.allows_workspace(workspace_id):
        raise HTTPException(status_code=404, detail="Workspace not found")
    workspace = await session.get(Workspace, workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return workspace


def _metadata(value: str | dict | None) -> dict:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _ledger_event_predicate():
    file_edit_tool = or_(*(
        SessionEvent.payload_json.contains(f'"tool_name":"{tool_name}"')
        for tool_name in SESSION_LEDGER_FILE_TOOL_NAMES
    ))
    return or_(
        SessionEvent.event_type.in_(SESSION_LEDGER_EVENT_TYPES),
        and_(SessionEvent.event_type == "tool_call", file_edit_tool),
    )
