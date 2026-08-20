from __future__ import annotations

import hashlib
import json
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_access_scope
from app.database import get_db_session
from app.models import SessionEvent, SourceDocument, Workspace, WorkCheckpoint
from app.services.access import AccessScope, source_access_predicate
from app.services.checkpoint_verifier import compare_checkpoint_repository, verify_checkpoint
from app.services.checkpoints import (
    MAX_CONTINUATION_LEAD_CHARS,
    SessionContextMaterializationRequiredError,
    build_session_handoff_artifact,
    capture_checkpoint,
    checkpoint_to_dict,
    checkpoints_to_dicts,
    get_checkpoint,
    latest_checkpoint,
    list_checkpoints,
    render_resume_bundle,
    resolve_session_handoff_attachment_descriptors,
    resolve_session_handoff_request_verbatim,
    resolve_session_handoff_supporting_context,
    validate_continuation_lead,
)
from app.services.harness_launcher import HarnessLaunchError, launch_harness_session
from app.services.project_scope import normalize_local_path, workspace_references
from app.services.session_library import latest_scoped_root_session_tip
from app.services.session_context_policy import (
    SessionContextCompactionsRequiredError,
    require_session_context_compactions,
    session_context_eligibility,
)
from app.services.session_scope import normalize_session_key, session_provider_values


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
    handoff_origin: Literal["selected", "current_active"] = "selected"
    repo_path: str | None = Field(default=None, min_length=1)
    continuation_lead: str | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_CONTINUATION_LEAD_CHARS,
    )
    target_model: str | None = Field(default=None, min_length=1, max_length=255)
    token_budget: int | None = Field(default=None, ge=300, le=1_000_000)

    @field_validator("repo_path")
    @classmethod
    def validate_repo_path(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        if not normalized:
            raise ValueError("repo_path must contain visible characters")
        return normalized

    @field_validator("continuation_lead")
    @classmethod
    def validate_lead(cls, value: str | None) -> str | None:
        return validate_continuation_lead(value)


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


@router.get("/checkpoints/session-context-eligibility")
async def get_session_context_eligibility(
    workspace_id: UUID,
    provider: str = Query(min_length=1, max_length=50),
    session_id: str = Query(min_length=1, max_length=255),
    session: AsyncSession = Depends(get_db_session),
    access_scope: AccessScope = Depends(get_access_scope),
) -> dict:
    await _require_workspace(session, workspace_id, access_scope)
    try:
        eligibility = await session_context_eligibility(
            session,
            workspace_id=workspace_id,
            provider=provider,
            session_id=session_id,
            access_scope=access_scope,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return eligibility.to_dict()


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
    session_key = normalize_session_key(body.provider, body.session_id)
    if session_key is None:
        raise HTTPException(
            status_code=422,
            detail="provider and session_id must be non-empty",
        )
    normalized_provider, normalized_session_id = session_key
    event = await session.scalar(
        select(SessionEvent)
        .join(SourceDocument, SessionEvent.source_document_id == SourceDocument.id)
        .where(
            SessionEvent.workspace_id == body.workspace_id,
            SessionEvent.provider.in_(
                session_provider_values(normalized_provider)
            ),
            SessionEvent.session_id == normalized_session_id,
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
            SessionEvent.provider.in_(
                session_provider_values(normalized_provider)
            ),
            SessionEvent.session_id == normalized_session_id,
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
            provider=event.provider,
            session_id=event.session_id,
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
    repo_path: str | None = Query(default=None, min_length=1),
    session: AsyncSession = Depends(get_db_session),
    access_scope: AccessScope = Depends(get_access_scope),
) -> dict:
    checkpoint = await _accessible_checkpoint(
        session,
        checkpoint_id,
        workspace_id,
        access_scope,
    )
    return await _resolved_checkpoint_repository_comparison(
        session,
        checkpoint,
        workspace_id=workspace_id,
        selected_repo_path=repo_path,
    )


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
    if body.handoff_origin == "current_active":
        await _require_current_active_session_tip(
            session,
            workspace_id=body.workspace_id,
            checkpoint=checkpoint,
            access_scope=access_scope,
        )
    else:
        try:
            await require_session_context_compactions(
                session,
                workspace_id=body.workspace_id,
                provider=checkpoint.provider,
                session_id=checkpoint.session_id,
                access_scope=access_scope,
            )
        except SessionContextCompactionsRequiredError as exc:
            raise HTTPException(
                status_code=exc.status_code,
                detail=exc.detail(),
            ) from exc
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
    repository_comparison = await _resolved_checkpoint_repository_comparison(
        session,
        checkpoint,
        workspace_id=body.workspace_id,
        selected_repo_path=body.repo_path,
    )
    try:
        artifact = build_session_handoff_artifact(
            checkpoint,
            request_verbatim=request_verbatim,
            supporting_context=supporting_context,
            trusted_attachment_descriptors=attachment_descriptors,
            allow_local_artifacts=access_scope.principal_id == "local",
            checkpoint_data=data,
            repository_comparison=repository_comparison,
            continuation_lead=body.continuation_lead,
            delivery_mode="direct_copy",
            target_model=body.target_model,
            token_budget=body.token_budget,
        )
    except SessionContextMaterializationRequiredError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail=exc.detail(),
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if body.handoff_origin == "current_active":
        await _require_current_active_session_tip(
            session,
            workspace_id=body.workspace_id,
            checkpoint=checkpoint,
            access_scope=access_scope,
        )
    return artifact


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


async def _require_current_active_session_tip(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    checkpoint: WorkCheckpoint,
    access_scope: AccessScope,
) -> None:
    """Authorize the narrow current-session exception to the maturity gate."""

    if access_scope.principal_id != "local":
        raise HTTPException(
            status_code=403,
            detail={
                "code": "local_action_required",
                "message": (
                    "Current-active Session Context handoff is available only "
                    "from the local app."
                ),
            },
        )

    current_tip = await latest_scoped_root_session_tip(
        session,
        workspace_id,
    )
    current_session_key = (
        (current_tip.provider, current_tip.session_id)
        if current_tip is not None
        else None
    )
    checkpoint_key = normalize_session_key(
        checkpoint.provider,
        checkpoint.session_id,
    )
    if current_session_key is None or checkpoint_key != current_session_key:
        raise _current_active_handoff_conflict()
    assert checkpoint_key is not None

    boundary = checkpoint.boundary_event
    boundary_key = normalize_session_key(
        getattr(boundary, "provider", ""),
        getattr(boundary, "session_id", ""),
    )
    if (
        boundary is None
        or boundary_key != checkpoint_key
        or current_tip is None
        or boundary.provider_event_id != current_tip.provider_event_id
        or boundary.sequence_number != current_tip.sequence_number
    ):
        raise _current_active_handoff_conflict()

    normalized_provider, normalized_session_id = checkpoint_key
    latest_event = await session.scalar(
        select(SessionEvent)
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
            source_access_predicate(
                access_scope,
                workspace_id=workspace_id,
            ),
        )
        .order_by(
            SessionEvent.sequence_number.desc(),
            SessionEvent.id.desc(),
        )
        .limit(1)
    )
    if latest_event is None or latest_event.id != checkpoint.boundary_event_id:
        raise _current_active_handoff_conflict()


def _current_active_handoff_conflict() -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "code": "current_active_handoff_mismatch",
            "message": (
                "Current-active handoff requires the workspace's latest root "
                "session and its exact current session-tip checkpoint."
            ),
        },
    )


async def _resolved_checkpoint_repository_comparison(
    session: AsyncSession,
    checkpoint: WorkCheckpoint,
    *,
    workspace_id: UUID,
    selected_repo_path: str | None = None,
) -> dict:
    _repositories, workspace_paths, _commits = await workspace_references(
        session,
        workspace_id,
    )
    selected = normalize_local_path(selected_repo_path)
    allowed_paths = {
        path
        for raw in workspace_paths
        if (path := normalize_local_path(raw)) is not None
    }
    checkpoint_root = normalize_local_path(checkpoint.repo_root)
    if checkpoint_root:
        allowed_paths.add(checkpoint_root)
    if selected_repo_path is not None and (
        selected is None or selected not in allowed_paths
    ):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "checkpoint_repository_selection_invalid",
                "message": (
                    "Choose a repository already verified for this workspace."
                ),
            },
        )
    return await compare_checkpoint_repository(
        checkpoint,
        fallback_repo_paths=sorted(allowed_paths),
        selected_repo_path=selected,
        recorded_session_path=await _checkpoint_recorded_session_directory(
            session,
            checkpoint,
        ),
    )


async def _checkpoint_recorded_session_directory(
    session: AsyncSession,
    checkpoint: WorkCheckpoint,
) -> str | None:
    source = await session.get(SourceDocument, checkpoint.source_document_id)
    if source is None:
        return None
    try:
        metadata = json.loads(source.metadata_json or "{}")
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(metadata, dict):
        return None
    for key in ("cwd", "workdir", "repo_path"):
        value = normalize_local_path(metadata.get(key))
        if value:
            return value
    return None


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
