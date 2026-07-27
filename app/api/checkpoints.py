from __future__ import annotations

import hashlib
import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_access_scope
from app.database import get_db_session
from app.models import SessionEvent, SourceDocument, Workspace, WorkCheckpoint
from app.services.access import AccessScope, source_access_predicate
from app.services.checkpoint_verifier import compare_checkpoint_repository, verify_checkpoint
from app.services.checkpoints import (
    SESSION_HANDOFF_SCHEMA_VERSION,
    build_session_handoff_contract,
    capture_checkpoint,
    checkpoint_to_dict,
    checkpoints_to_dicts,
    get_checkpoint,
    latest_checkpoint,
    list_checkpoints,
    render_resume_bundle,
    render_session_handoff,
    resolve_session_handoff_attachment_descriptors,
    resolve_session_handoff_request_verbatim,
    resolve_session_handoff_supporting_context,
)
from app.services.harness_launcher import HarnessLaunchError, launch_harness_session


router = APIRouter()


class CheckpointCaptureRequest(BaseModel):
    workspace_id: UUID
    provider: str = Field(min_length=1, max_length=50)
    session_id: str = Field(min_length=1, max_length=255)
    boundary_event_id: UUID | None = None


class CheckpointVerifyRequest(BaseModel):
    workspace_id: UUID
    execute_commands: bool = False


class CheckpointResumeRequest(BaseModel):
    workspace_id: UUID
    launch_session: bool = False


class CheckpointHandoffRequest(BaseModel):
    workspace_id: UUID


@router.get("/checkpoints")
async def get_checkpoints(
    workspace_id: UUID,
    provider: str | None = Query(default=None, min_length=1, max_length=50),
    session_id: str | None = Query(default=None, min_length=1, max_length=255),
    limit: int = Query(default=50, ge=1, le=100),
    session: AsyncSession = Depends(get_db_session),
    access_scope: AccessScope = Depends(get_access_scope),
) -> dict:
    await _require_workspace(session, workspace_id, access_scope)
    try:
        checkpoints = await list_checkpoints(
            session,
            workspace_id=workspace_id,
            limit=limit,
            provider=provider,
            session_id=session_id,
            access_scope=access_scope,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    visible = [
        checkpoint for checkpoint in checkpoints
        if await _checkpoint_sources_allowed(
            session,
            checkpoint,
            workspace_id,
            access_scope,
        )
    ]
    return {
        "checkpoints": await checkpoints_to_dicts(
            session,
            visible,
            access_scope=access_scope,
        )
    }


@router.get("/checkpoints/latest")
async def get_latest_checkpoint(
    workspace_id: UUID,
    provider: str | None = Query(default=None, min_length=1, max_length=50),
    session_id: str | None = Query(default=None, min_length=1, max_length=255),
    session: AsyncSession = Depends(get_db_session),
    access_scope: AccessScope = Depends(get_access_scope),
) -> dict:
    await _require_workspace(session, workspace_id, access_scope)
    try:
        checkpoint = await latest_checkpoint(
            session,
            workspace_id=workspace_id,
            provider=provider,
            session_id=session_id,
            access_scope=access_scope,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if checkpoint is None or not await _checkpoint_sources_allowed(
        session,
        checkpoint,
        workspace_id,
        access_scope,
    ):
        raise HTTPException(status_code=404, detail="Checkpoint not found")
    return (
        await checkpoints_to_dicts(
            session,
            [checkpoint],
            access_scope=access_scope,
        )
    )[0]


@router.get("/checkpoints/{checkpoint_id}")
async def get_checkpoint_by_id(
    checkpoint_id: UUID,
    workspace_id: UUID,
    session: AsyncSession = Depends(get_db_session),
    access_scope: AccessScope = Depends(get_access_scope),
) -> dict:
    checkpoint = await _accessible_checkpoint(
        session, checkpoint_id, workspace_id, access_scope
    )
    return (
        await checkpoints_to_dicts(
            session,
            [checkpoint],
            access_scope=access_scope,
        )
    )[0]


@router.post("/checkpoints/capture")
async def create_checkpoint(
    body: CheckpointCaptureRequest,
    session: AsyncSession = Depends(get_db_session),
    access_scope: AccessScope = Depends(get_access_scope),
) -> dict:
    await _require_workspace(session, body.workspace_id, access_scope)
    event = await session.scalar(
        select(SessionEvent)
        .join(SourceDocument, SessionEvent.source_document_id == SourceDocument.id)
        .where(
            SessionEvent.workspace_id == body.workspace_id,
            SessionEvent.provider == body.provider.strip().lower(),
            SessionEvent.session_id == body.session_id.strip(),
            source_access_predicate(access_scope, workspace_id=body.workspace_id),
        )
        .order_by(SessionEvent.sequence_number.desc())
        .limit(1)
    )
    if event is None:
        raise HTTPException(status_code=404, detail="Session events not found")
    session_source_ids = set(await session.scalars(
        select(SessionEvent.source_document_id).where(
            SessionEvent.workspace_id == body.workspace_id,
            SessionEvent.provider == body.provider.strip().lower(),
            SessionEvent.session_id == body.session_id.strip(),
        ).distinct()
    ))
    if not await _source_ids_allowed(
        session, session_source_ids, body.workspace_id, access_scope
    ):
        raise HTTPException(status_code=404, detail="Session events not found")
    try:
        checkpoint = await capture_checkpoint(
            session,
            workspace_id=body.workspace_id,
            provider=body.provider.strip().lower(),
            session_id=body.session_id.strip(),
            boundary_event_id=body.boundary_event_id,
            trigger="manual",
        )
        await session.commit()
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    loaded = await get_checkpoint(session, checkpoint.id)
    assert loaded is not None
    return (
        await checkpoints_to_dicts(
            session,
            [loaded],
            access_scope=access_scope,
        )
    )[0]


@router.post("/checkpoints/{checkpoint_id}/verify")
async def run_checkpoint_verification(
    checkpoint_id: UUID,
    body: CheckpointVerifyRequest,
    session: AsyncSession = Depends(get_db_session),
    access_scope: AccessScope = Depends(get_access_scope),
) -> dict:
    await _accessible_checkpoint(session, checkpoint_id, body.workspace_id, access_scope)
    if body.execute_commands and access_scope.principal_id != "local":
        raise HTTPException(
            status_code=403,
            detail="Command verification is available only from the local app.",
        )
    try:
        await verify_checkpoint(
            session,
            checkpoint_id=checkpoint_id,
            execute_commands=body.execute_commands,
        )
        await session.commit()
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    loaded = await get_checkpoint(session, checkpoint_id)
    assert loaded is not None
    return (
        await checkpoints_to_dicts(
            session,
            [loaded],
            access_scope=access_scope,
        )
    )[0]


@router.get("/checkpoints/{checkpoint_id}/compare")
async def compare_checkpoint_with_repository(
    checkpoint_id: UUID,
    workspace_id: UUID,
    session: AsyncSession = Depends(get_db_session),
    access_scope: AccessScope = Depends(get_access_scope),
) -> dict:
    checkpoint = await _accessible_checkpoint(
        session,
        checkpoint_id,
        workspace_id,
        access_scope,
    )
    return await compare_checkpoint_repository(checkpoint)


@router.post("/checkpoints/{checkpoint_id}/resume")
async def create_resume_bundle(
    checkpoint_id: UUID,
    body: CheckpointResumeRequest,
    session: AsyncSession = Depends(get_db_session),
    access_scope: AccessScope = Depends(get_access_scope),
) -> dict:
    checkpoint = await _accessible_checkpoint(
        session, checkpoint_id, body.workspace_id, access_scope
    )
    bundle = render_resume_bundle(checkpoint)
    launch = None
    if body.launch_session:
        if access_scope.principal_id != "local":
            raise HTTPException(
                status_code=403,
                detail="Native session resume is available only from the local app.",
            )
        source = await session.get(SourceDocument, checkpoint.source_document_id)
        metadata = _metadata(source.metadata_json if source else None)
        if not metadata.get("source_path"):
            launch = {
                "launched": False,
                "message": "The checkpoint is not linked to local harness history.",
            }
        else:
            try:
                launch = launch_harness_session(
                    checkpoint.provider,
                    checkpoint.session_id,
                    cwd=metadata.get("cwd"),
                )
            except HarnessLaunchError as exc:
                launch = {
                    "launched": False,
                    "code": exc.code,
                    "message": str(exc),
                }
    return {
        "checkpoint_id": str(checkpoint.id),
        "schema_version": "resume_bundle.v1",
        "content": bundle,
        "sha256": hashlib.sha256(bundle.encode("utf-8")).hexdigest(),
        "launch": launch,
    }


@router.post("/checkpoints/{checkpoint_id}/handoff")
async def create_session_handoff(
    checkpoint_id: UUID,
    body: CheckpointHandoffRequest,
    session: AsyncSession = Depends(get_db_session),
    access_scope: AccessScope = Depends(get_access_scope),
) -> dict:
    checkpoint = await _accessible_checkpoint(
        session, checkpoint_id, body.workspace_id, access_scope
    )
    request_verbatim = await resolve_session_handoff_request_verbatim(
        session,
        checkpoint,
        access_scope=access_scope,
    )
    if request_verbatim is None:
        raise HTTPException(
            status_code=422,
            detail=(
                "The checkpoint does not contain a lossless session goal and its "
                "original goal event is unavailable."
            ),
        )
    supporting_context = await resolve_session_handoff_supporting_context(
        session,
        checkpoint,
        request_verbatim=request_verbatim,
        access_scope=access_scope,
    )
    attachment_descriptors = (
        await resolve_session_handoff_attachment_descriptors(
            session,
            checkpoint,
            request_verbatim=request_verbatim,
            access_scope=access_scope,
        )
    )
    current_projection = (
        await checkpoints_to_dicts(
            session,
            [checkpoint],
            access_scope=access_scope,
        )
    )[0]
    current_boundary = current_projection.get("boundary") or {}
    data = checkpoint_to_dict(
        checkpoint,
        recovered_goal=request_verbatim,
        session_tip={
            "sequence_number": current_boundary.get("session_tip_sequence"),
            "occurred_at": current_boundary.get("session_tip_at"),
        },
    )
    repository_comparison = await compare_checkpoint_repository(checkpoint)
    try:
        contract = build_session_handoff_contract(
            checkpoint,
            request_verbatim=request_verbatim,
            supporting_context=supporting_context,
            trusted_attachment_descriptors=attachment_descriptors,
            allow_local_artifacts=access_scope.principal_id == "local",
            checkpoint_data=data,
            repository_comparison=repository_comparison,
        )
        content = render_session_handoff(
            checkpoint,
            request_verbatim=request_verbatim,
            supporting_context=supporting_context,
            contract=contract,
            checkpoint_data=data,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "schema_version": SESSION_HANDOFF_SCHEMA_VERSION,
        "scope": "session",
        "provider": data["provider"],
        "session_id": data["session_id"],
        "checkpoint_id": data["id"],
        "source_document_id": data["source_document_id"],
        "boundary": data["boundary"],
        "snapshot_phase": data["boundary"].get("snapshot_phase"),
        "captured_at": data["boundary"].get("occurred_at"),
        "currentness": data.get("currentness"),
        **contract,
        "content": content,
        "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "estimated_tokens": max(1, (len(content) + 3) // 4),
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


async def _accessible_checkpoint(
    session: AsyncSession,
    checkpoint_id: UUID,
    workspace_id: UUID,
    access_scope: AccessScope,
) -> WorkCheckpoint:
    await _require_workspace(session, workspace_id, access_scope)
    checkpoint = await get_checkpoint(session, checkpoint_id)
    if (
        checkpoint is None
        or checkpoint.workspace_id != workspace_id
        or not await _checkpoint_sources_allowed(
            session,
            checkpoint,
            workspace_id,
            access_scope,
        )
    ):
        raise HTTPException(status_code=404, detail="Checkpoint not found")
    return checkpoint


async def _checkpoint_sources_allowed(
    session: AsyncSession,
    checkpoint: WorkCheckpoint,
    workspace_id: UUID,
    access_scope: AccessScope,
) -> bool:
    source_ids = {checkpoint.source_document_id}
    source_ids.update(
        evidence.source_document_id
        for item in checkpoint.items
        for evidence in item.evidence
        if evidence.source_document_id is not None
    )
    return await _source_ids_allowed(session, source_ids, workspace_id, access_scope)


async def _source_ids_allowed(
    session: AsyncSession,
    source_document_ids: set[UUID],
    workspace_id: UUID,
    access_scope: AccessScope,
) -> bool:
    if not source_document_ids:
        return False
    visible = set(await session.scalars(
        select(SourceDocument.id).where(
            SourceDocument.id.in_(source_document_ids),
            source_access_predicate(access_scope, workspace_id=workspace_id),
        )
    ))
    return visible == source_document_ids


def _metadata(value) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            loaded = json.loads(value or "{}")
        except (TypeError, ValueError):
            return {}
        return loaded if isinstance(loaded, dict) else {}
    return {}
