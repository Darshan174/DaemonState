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
from app.schemas.context_quality import ContextClaimEnvelope, ContextKind, canonical_sha256
from app.services.context_quality import (
    ContextActivationConflict,
    ContextEvidenceStale,
    access_scope_sha256,
    apply_quality_control,
    collect_source_document_ids,
    context_scope_key_sha256,
    delivery_profile_sha256,
    reconcile_context_candidate,
)
from app.services.harness_launcher import HarnessLaunchError, launch_harness_session
from app.services.project_scope import normalize_local_path, workspace_references
from app.services.session_library import latest_scoped_root_session_tip
from app.services.session_context_policy import (
    SessionContextCompactionsRequiredError,
    require_session_context_compactions,
    session_context_eligibility,
)
from app.services.session_context import (
    SESSION_BACKGROUND_SCHEMA_VERSION,
    SESSION_CONTEXT_COMPILER_VERSION,
    SESSION_CONTEXT_RENDERER_VERSION,
    build_session_context_artifact,
)
from app.services.session_scope import normalize_session_key, session_provider_values


router = APIRouter()


async def _session_context_evidence_source_document_ids(
    session: AsyncSession,
    checkpoint: WorkCheckpoint,
    supporting_context: list[dict[str, str]],
) -> tuple[UUID, ...]:
    """Return every exact source revision whose data can reach public Context."""

    source_ids = {
        checkpoint.source_document_id,
        *collect_source_document_ids(supporting_context),
    }
    session_event_ids: set[UUID] = set()
    for item in checkpoint.items:
        for evidence in item.evidence:
            if not evidence.supports:
                continue
            if evidence.source_document_id is not None:
                source_ids.add(evidence.source_document_id)
            if evidence.session_event_id is not None:
                session_event_ids.add(evidence.session_event_id)
    if session_event_ids:
        source_ids.update(await session.scalars(
            select(SessionEvent.source_document_id).where(
                SessionEvent.workspace_id == checkpoint.workspace_id,
                SessionEvent.id.in_(session_event_ids),
            )
        ))
    return tuple(sorted(source_ids, key=str))


def _apply_session_background_activation_capabilities(
    artifact: dict,
    *,
    candidate_copy_allowed: bool,
) -> None:
    """Keep preview available when candidate activation blocks delivery operations."""

    if candidate_copy_allowed:
        return
    capabilities = artifact.get("operation_capabilities")
    if not isinstance(capabilities, dict):
        return
    preview = capabilities.get("preview")
    if isinstance(preview, dict):
        preview.update({"allowed": True, "status": "available"})
    clipboard = capabilities.get("clipboard_copy")
    if isinstance(clipboard, dict):
        clipboard["allowed"] = False
        clipboard["status"] = "blocked"
        issue_codes = clipboard.setdefault("blocking_issue_codes", [])
        if "context_candidate_not_active" not in issue_codes:
            issue_codes.append("context_candidate_not_active")
    delivery = artifact.get("delivery")
    if isinstance(delivery, dict):
        delivery["preview_ready"] = True
        delivery["clipboard_copy_ready"] = False
    readiness = artifact.get("readiness")
    if isinstance(readiness, dict):
        readiness.update({
            "status": "blocked",
            "label": "Preview available · Context review required",
        })


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
    evidence_source_document_ids = (
        await _session_context_evidence_source_document_ids(
            session,
            checkpoint,
            supporting_context,
        )
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
        artifact = build_session_context_artifact(
            checkpoint,
            request_verbatim=request_verbatim,
            supporting_context=supporting_context,
            trusted_attachment_descriptors=attachment_descriptors,
            allow_local_artifacts=access_scope.principal_id == "local",
            checkpoint_data=data,
            repository_comparison=repository_comparison,
            continuation_lead=body.continuation_lead,
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
    repository = artifact.get("repository") or {}
    repository_root = str(repository.get("root") or "").strip()
    repository_snapshot_sha256 = str(
        repository.get("status_fingerprint")
        or repository.get("snapshot_fingerprint")
        or ""
    ).strip()
    if len(repository_snapshot_sha256) != 64:
        repository_snapshot_sha256 = None
    claim_manifest = tuple(
        ContextClaimEnvelope.model_validate(item)
        for item in artifact.get("claim_manifest") or []
    )
    quality_evaluation = artifact.get("quality_evaluation") or {}
    currentness = artifact.get("currentness") or {}
    boundary = artifact.get("boundary") or {}
    try:
        activation = await reconcile_context_candidate(
            session,
            workspace_id=body.workspace_id,
            context_kind=ContextKind.SESSION,
            scope_key_sha256=context_scope_key_sha256(
                workspace_id=body.workspace_id,
                context_kind=ContextKind.SESSION,
                provider=checkpoint.provider,
                session_id=checkpoint.session_id,
            ),
            access_scope_sha256_value=access_scope_sha256(access_scope),
            delivery_profile_sha256_value=delivery_profile_sha256(
                artifact_schema_version=SESSION_BACKGROUND_SCHEMA_VERSION,
                renderer_version=SESSION_CONTEXT_RENDERER_VERSION,
                target_model=body.target_model,
                token_budget=body.token_budget,
            ),
            observation={
                "schema_version": "session_background_observation.v1",
                "workspace_id": str(body.workspace_id),
                "provider": checkpoint.provider,
                "session_id": checkpoint.session_id,
                "checkpoint_id": str(checkpoint.id),
                "checkpoint_payload_sha256": checkpoint.payload_sha256,
                "boundary_event_id": str(checkpoint.boundary_event_id),
                "boundary_sequence_number": boundary.get("sequence_number"),
                "source_document_id": str(checkpoint.source_document_id),
                "repository_root": repository_root or None,
                "repository_comparison_sha256": canonical_sha256(
                    repository_comparison or {}
                ),
                "repository_snapshot_sha256": repository_snapshot_sha256,
                "required_attachment_hashes": sorted(
                    str(item.get("sha256") or item.get("content_hash") or "")
                    for item in artifact.get("attachment_dependencies") or []
                    if item.get("required") is True
                ),
                "supporting_context_hashes": sorted(
                    str(item.get("sha256") or "")
                    for item in artifact.get("supporting_context") or []
                ),
            },
            artifact=artifact,
            content=str(artifact["content"]),
            claims=claim_manifest,
            evaluation_metadata={
                "context_role": "background_only",
                # Candidate activation evaluates semantic/source integrity. Receiver
                # delivery is an operation capability and must not suppress preview.
                "copy_ready": (
                    ((artifact.get("readiness_dimensions") or {}).get(
                        "semantic_readiness"
                    ) or {}).get("copy_ready")
                    is True
                ),
                "hash_valid": (
                    hashlib.sha256(str(artifact["content"]).encode("utf-8")).hexdigest()
                    == artifact.get("sha256")
                ),
                "snapshot_current": not bool(
                    boundary.get("has_newer_events") is True
                    or currentness.get("state") == "superseded"
                ),
                "permissions_current": access_scope.allows_workspace(body.workspace_id),
                "required_dependencies_complete": (
                    "REQUIRED_DEPENDENCY_MISSING"
                    not in quality_evaluation.get("hard_failures", [])
                ),
            },
            artifact_schema_version=SESSION_BACKGROUND_SCHEMA_VERSION,
            compiler_version=SESSION_CONTEXT_COMPILER_VERSION,
            renderer_version=SESSION_CONTEXT_RENDERER_VERSION,
            policy_name="session_background",
            checkpoint_id=checkpoint.id,
            boundary_event_id=checkpoint.boundary_event_id,
            repository_identity_sha256=(
                canonical_sha256(repository_root.casefold())
                if repository_root
                else None
            ),
            repository_snapshot_sha256=repository_snapshot_sha256,
            evidence_source_document_ids=evidence_source_document_ids,
            access_scope=access_scope,
            actor=access_scope.principal_id,
        )
        apply_quality_control(artifact, activation)
        _apply_session_background_activation_capabilities(
            artifact,
            candidate_copy_allowed=activation.copy_allowed,
        )
        if body.handoff_origin == "current_active":
            # Recheck the mutable session tip after evaluation and immediately
            # before the active pointer transaction commits.
            await _require_current_active_session_tip(
                session,
                workspace_id=body.workspace_id,
                checkpoint=checkpoint,
                access_scope=access_scope,
            )
        await session.commit()
    except (ContextActivationConflict, ContextEvidenceStale) as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception:
        await session.rollback()
        raise
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
