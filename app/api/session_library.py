from __future__ import annotations

import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.api.dependencies import get_access_scope
from app.database import get_db_session
from app.models import SourceDocument
from app.services.access import AccessScope
from app.services.harness_launcher import HarnessLaunchError, launch_harness_session
from app.services.session_library import (
    SESSION_CONNECTOR_TYPES,
    build_session_library,
    sync_local_session_library,
)


router = APIRouter()


class SessionLibrarySyncRequest(BaseModel):
    workspace_id: UUID
    connector_types: list[str] = Field(default_factory=lambda: list(SESSION_CONNECTOR_TYPES))


class SessionLibraryOpenRequest(BaseModel):
    workspace_id: UUID
    source_document_id: UUID
    topic: str | None = Field(default=None, max_length=240)


@router.get("/session-library")
async def get_session_library(
    workspace_id: UUID,
    session: AsyncSession = Depends(get_db_session),
    access_scope: AccessScope = Depends(get_access_scope),
) -> dict:
    if not access_scope.allows_workspace(workspace_id):
        raise HTTPException(status_code=404, detail="Workspace not found")
    try:
        return await build_session_library(session, workspace_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/session-library/sync")
async def sync_session_library(
    body: SessionLibrarySyncRequest,
    session: AsyncSession = Depends(get_db_session),
    access_scope: AccessScope = Depends(get_access_scope),
) -> dict:
    if not access_scope.allows_workspace(body.workspace_id):
        raise HTTPException(status_code=404, detail="Workspace not found")

    unknown = sorted({value for value in body.connector_types if value not in SESSION_CONNECTOR_TYPES})
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported session harnesses: {', '.join(unknown)}",
        )
    try:
        sync_result = await sync_local_session_library(
            session,
            body.workspace_id,
            connector_types=body.connector_types,
        )
        library = await build_session_library(session, body.workspace_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"sync": sync_result, "library": library}


@router.post("/session-library/open")
async def open_session_in_harness(
    body: SessionLibraryOpenRequest,
    session: AsyncSession = Depends(get_db_session),
    access_scope: AccessScope = Depends(get_access_scope),
) -> dict:
    if not access_scope.allows_workspace(body.workspace_id):
        raise HTTPException(status_code=404, detail="Workspace not found")
    if access_scope.principal_id != "local":
        raise HTTPException(
            status_code=403,
            detail="Native harness launch is available only from the local Context Engine app.",
        )

    document = await session.scalar(select(SourceDocument).where(
        SourceDocument.id == body.source_document_id,
        SourceDocument.workspace_id == body.workspace_id,
        SourceDocument.source_type == "agent_session",
    ))
    if document is None:
        raise HTTPException(status_code=404, detail="Session source not found")

    metadata = _metadata_dict(document.metadata_json)
    connector_type = str(
        metadata.get("connector_type") or metadata.get("tool") or ""
    ).strip().lower()
    if connector_type == "claude_code":
        connector_type = "claude"
    session_id = str(
        metadata.get("session_id") or document.external_id.rsplit(":", 1)[-1]
    ).strip()
    if connector_type not in SESSION_CONNECTOR_TYPES or not session_id:
        raise HTTPException(status_code=422, detail="Session launch metadata is incomplete")
    if not metadata.get("source_path"):
        raise HTTPException(
            status_code=409,
            detail="This session is not linked to local harness history.",
        )

    try:
        result = launch_harness_session(
            connector_type,
            session_id,
            cwd=metadata.get("cwd"),
        )
    except HarnessLaunchError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    return {
        **result,
        "topic": body.topic,
        "message": _launch_message(result),
    }


def _metadata_dict(value) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            loaded = json.loads(value or "{}")
            return loaded if isinstance(loaded, dict) else {}
        except (TypeError, ValueError):
            return {}
    return {}


def _launch_message(result: dict) -> str:
    if result.get("navigation") == "session":
        return (
            f"Opened this session in the {result['harness']} desktop app. "
            "Topic highlighting stays here."
        )
    if result.get("navigation") == "project":
        return (
            f"Opened this project in the {result['harness']} desktop app. "
            "Select the session there; topic highlighting stays here."
        )
    return (
        f"Opened the {result['harness']} desktop app. "
        "Select the session there; topic highlighting stays here."
    )
