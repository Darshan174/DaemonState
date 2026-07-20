from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db_session
from app.api.dependencies import get_access_scope
from app.services.access import AccessScope, source_access_predicate
from app.models import (
    Claim,
    ClaimRevision,
    Component,
    ContextPack,
    EvidenceSpan,
    OpenLoop,
    SourceDocument,
    VerifiedPlaybook,
)
from sqlalchemy import select
from app.services.context_compiler import (
    ContextBudgetExceededError,
    ContextCompiler,
    ContextPersistenceError,
    FocusValidationError,
    InvalidGoalError,
    InvalidRepoPathError,
)
from app.services.founder_oversight import (
    FounderOversightNotFoundError,
    FounderOversightService,
)
from app.services.harness_outcomes import HarnessOutcomeService
from app.services.open_loops import (
    OpenLoopActionError,
    OpenLoopNotFoundError,
    OpenLoopService,
    open_loop_to_dict,
)
from app.services.playbooks import (
    PlaybookActionError,
    PlaybookNotFoundError,
    PlaybookService,
    playbook_to_dict,
)
from app.services.session_checkpoints import (
    SessionCheckpointNotFoundError,
    restore_session_checkpoint,
)
from app.services.session_summary import derive_session_topic
from app.services.workspace_scope import metadata_dict

router = APIRouter()


@router.get("/context/claims/{claim_id}/timeline")
async def get_claim_timeline(
    claim_id: UUID,
    workspace_id: UUID,
    valid_at: datetime | None = None,
    known_at: datetime | None = None,
    session: AsyncSession = Depends(get_db_session),
    access_scope: AccessScope = Depends(get_access_scope),
) -> dict[str, Any]:
    claim = await session.scalar(select(Claim).where(
        Claim.id == claim_id, Claim.workspace_id == workspace_id
    ))
    if claim is None or not access_scope.allows_workspace(workspace_id):
        raise HTTPException(status_code=404, detail="Claim not found")
    stmt = (
        select(ClaimRevision, EvidenceSpan, SourceDocument)
        .join(EvidenceSpan, ClaimRevision.evidence_span_id == EvidenceSpan.id)
        .join(SourceDocument, EvidenceSpan.source_document_id == SourceDocument.id)
        .where(
            ClaimRevision.claim_id == claim_id,
            source_access_predicate(access_scope, workspace_id=workspace_id),
        )
    )
    if valid_at is not None:
        stmt = stmt.where(
            (ClaimRevision.valid_from.is_(None) | (ClaimRevision.valid_from <= valid_at)),
            (ClaimRevision.valid_to.is_(None) | (ClaimRevision.valid_to > valid_at)),
        )
    if known_at is not None:
        stmt = stmt.where(
            ClaimRevision.created_at <= known_at,
            (ClaimRevision.transaction_to.is_(None) | (ClaimRevision.transaction_to > known_at)),
        )
    rows = (await session.execute(
        stmt.order_by(ClaimRevision.created_at, ClaimRevision.id)
    )).all()
    revisions = [{
        "id": str(revision.id),
        "value": revision.value,
        "operation": revision.operation,
        "status_after": revision.status_after,
        "valid_from": revision.valid_from,
        "valid_to": revision.valid_to,
        "observed_at": revision.observed_at,
        "transaction_from": revision.created_at,
        "transaction_to": revision.transaction_to,
        "validity_basis": revision.validity_basis,
        "evidence_span_id": str(evidence.id),
        "source_document_id": str(source.id),
        "source_revision_number": source.revision_number,
        "source_url": source.source_url,
    } for revision, evidence, source in rows]
    return {
        "claim_id": str(claim.id),
        "status": claim.status,
        "current_revision_id": (
            str(claim.current_revision_id) if claim.current_revision_id else None
        ),
        "valid_at": valid_at,
        "known_at": known_at,
        "revisions": revisions,
        "conflicting": claim.status == "contested" or len(revisions) > 1,
    }


class ContextPrepareRequest(BaseModel):
    objective: str | None = Field(default=None, min_length=1)
    goal: str | None = Field(default=None, min_length=1)
    workspace_id: UUID | None = None
    repo_path: str | None = Field(default=None, min_length=1)
    target_model: str | None = None
    token_budget: int | None = Field(default=None, ge=300)
    mode: Literal["task", "project_snapshot"] = "task"
    focus_component_id: UUID | None = None
    objective_origin: Literal[
        "trusted_human", "source_component", "project_snapshot"
    ] | None = None
    checkpoint_source_document_id: UUID | None = None
    checkpoint_id: str | None = Field(default=None, min_length=1, max_length=120)

    @model_validator(mode="after")
    def _has_objective(self) -> "ContextPrepareRequest":
        origin = self.objective_origin or (
            "project_snapshot" if self.mode == "project_snapshot" else "trusted_human"
        )
        if origin == "trusted_human" and not (self.objective or self.goal):
            raise ValueError("objective is required")
        if bool(self.checkpoint_source_document_id) != bool(self.checkpoint_id):
            raise ValueError(
                "checkpoint_source_document_id and checkpoint_id must be provided together"
            )
        return self


class ContextPrepareResponse(BaseModel):
    context_pack_id: str
    schema_version: Literal["context_pack.v2"]
    markdown: str
    manifest: dict[str, Any]
    health_score: float
    selected_context: list[dict[str, Any]]
    excluded_context: list[dict[str, Any]]
    focus: dict[str, Any]


class OpenLoopActionRequest(BaseModel):
    workspace_id: UUID
    action: Literal["dismiss", "resolve", "reopen", "assign"]
    reason: str = Field(min_length=1, max_length=2000)
    assignee: str | None = Field(default=None, min_length=1, max_length=255)


class PlaybookActionRequest(BaseModel):
    workspace_id: UUID
    action: Literal["approve", "disable"]
    reason: str = Field(min_length=1, max_length=2000)


@router.get("/context/open-loops")
async def list_open_loops(
    workspace_id: UUID,
    include_closed: bool = True,
    session: AsyncSession = Depends(get_db_session),
    access_scope: AccessScope = Depends(get_access_scope),
) -> dict[str, Any]:
    if not access_scope.allows_workspace(workspace_id):
        raise HTTPException(status_code=404, detail="Workspace not found")
    accessible_source_ids = set(await session.scalars(
        select(SourceDocument.id).where(
            source_access_predicate(access_scope, workspace_id=workspace_id)
        )
    ))
    accessible_component_ids = set(await session.scalars(
        select(Component.id)
        .join(SourceDocument, Component.source_document_id == SourceDocument.id)
        .where(source_access_predicate(access_scope, workspace_id=workspace_id))
    ))
    items = await OpenLoopService(session).list(
        workspace_id=workspace_id,
        include_closed=include_closed,
    )
    items = [
        item for item in items
        if (item.focus_component_id is None or item.focus_component_id in accessible_component_ids)
        and _source_id_json_is_accessible(item.sources_json, accessible_source_ids)
    ]
    return {
        "open_count": sum(item.status == "open" for item in items),
        "items": [open_loop_to_dict(item) for item in items],
    }


@router.patch("/context/open-loops/{loop_id}")
async def update_open_loop(
    loop_id: UUID,
    payload: OpenLoopActionRequest,
    session: AsyncSession = Depends(get_db_session),
    access_scope: AccessScope = Depends(get_access_scope),
) -> dict[str, Any]:
    if not access_scope.allows_workspace(payload.workspace_id):
        raise HTTPException(status_code=404, detail="Open loop not found")
    candidate = await session.scalar(select(OpenLoop).where(
        OpenLoop.id == loop_id,
        OpenLoop.workspace_id == payload.workspace_id,
    ))
    accessible_source_ids = set(await session.scalars(
        select(SourceDocument.id).where(
            source_access_predicate(access_scope, workspace_id=payload.workspace_id)
        )
    ))
    if candidate is None or not _source_id_json_is_accessible(
        candidate.sources_json, accessible_source_ids
    ):
        raise HTTPException(status_code=404, detail="Open loop not found")
    if candidate.focus_component_id is not None:
        accessible_focus = await session.scalar(
            select(Component.id)
            .join(SourceDocument, Component.source_document_id == SourceDocument.id)
            .where(
                Component.id == candidate.focus_component_id,
                source_access_predicate(
                    access_scope, workspace_id=payload.workspace_id
                ),
            )
        )
        if accessible_focus is None:
            raise HTTPException(status_code=404, detail="Open loop not found")
    try:
        loop = await OpenLoopService(session).apply_action(
            workspace_id=payload.workspace_id,
            loop_id=loop_id,
            action=payload.action,
            reason=payload.reason,
            assignee=payload.assignee,
        )
        await session.commit()
    except OpenLoopNotFoundError as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except OpenLoopActionError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return open_loop_to_dict(loop)


@router.get("/context/playbooks")
async def list_playbooks(
    workspace_id: UUID,
    session: AsyncSession = Depends(get_db_session),
    access_scope: AccessScope = Depends(get_access_scope),
) -> dict[str, Any]:
    if not access_scope.allows_workspace(workspace_id):
        raise HTTPException(status_code=404, detail="Workspace not found")
    accessible_source_ids = set(await session.scalars(
        select(SourceDocument.id).where(
            source_access_predicate(access_scope, workspace_id=workspace_id)
        )
    ))
    items = [
        item for item in await PlaybookService(session).list(workspace_id=workspace_id)
        if _source_id_list_is_accessible(item.source_document_ids_json, accessible_source_ids)
    ]
    return {"items": [playbook_to_dict(item) for item in items]}


@router.patch("/context/playbooks/{playbook_id}")
async def update_playbook(
    playbook_id: UUID,
    payload: PlaybookActionRequest,
    session: AsyncSession = Depends(get_db_session),
    access_scope: AccessScope = Depends(get_access_scope),
) -> dict[str, Any]:
    if not access_scope.allows_workspace(payload.workspace_id):
        raise HTTPException(status_code=404, detail="Playbook not found")
    candidate = await session.scalar(select(VerifiedPlaybook).where(
        VerifiedPlaybook.id == playbook_id,
        VerifiedPlaybook.workspace_id == payload.workspace_id,
    ))
    accessible_source_ids = set(await session.scalars(
        select(SourceDocument.id).where(
            source_access_predicate(access_scope, workspace_id=payload.workspace_id)
        )
    ))
    if candidate is None or not _source_id_list_is_accessible(
        candidate.source_document_ids_json, accessible_source_ids
    ):
        raise HTTPException(status_code=404, detail="Playbook not found")
    try:
        playbook = await PlaybookService(session).apply_action(
            workspace_id=payload.workspace_id,
            playbook_id=playbook_id,
            action=payload.action,
            reason=payload.reason,
        )
        await session.commit()
    except PlaybookNotFoundError as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PlaybookActionError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return playbook_to_dict(playbook)


def _source_id_json_is_accessible(raw: str, accessible_source_ids: set[UUID]) -> bool:
    try:
        sources = json.loads(raw or "[]")
        if not isinstance(sources, list):
            return False
        ids = {
            UUID(str(item["source_document_id"]))
            for item in sources
            if isinstance(item, dict) and item.get("source_document_id")
        }
    except (TypeError, ValueError, json.JSONDecodeError):
        return False
    return ids <= accessible_source_ids


def _source_id_list_is_accessible(raw: str, accessible_source_ids: set[UUID]) -> bool:
    try:
        values = json.loads(raw or "[]")
        ids = {UUID(str(value)) for value in values}
    except (TypeError, ValueError, json.JSONDecodeError):
        return False
    return ids <= accessible_source_ids


@router.get("/context/run-timeline")
async def get_run_timeline(
    workspace_id: UUID,
    focus_component_id: UUID,
    session: AsyncSession = Depends(get_db_session),
    access_scope: AccessScope = Depends(get_access_scope),
) -> dict[str, Any]:
    focus_exists = await session.scalar(
        select(Component.id)
        .join(SourceDocument, Component.source_document_id == SourceDocument.id)
        .where(
            Component.id == focus_component_id,
            Component.workspace_id == workspace_id,
            source_access_predicate(access_scope, workspace_id=workspace_id),
        )
    )
    if focus_exists is None:
        raise HTTPException(status_code=404, detail={
            "code": "focus_not_found", "message": "Focus was not found in this access scope."
        })
    try:
        timeline = await FounderOversightService(session).build_timeline(
            workspace_id=workspace_id,
            focus_component_id=focus_component_id,
        )
        accessible_source_ids = set(await session.scalars(
            select(SourceDocument.id).where(
                source_access_predicate(access_scope, workspace_id=workspace_id)
            )
        ))
        loops = [
            item for item in await OpenLoopService(session).list(workspace_id=workspace_id)
            if item.focus_component_id == focus_component_id
            and _source_id_json_is_accessible(item.sources_json, accessible_source_ids)
        ]
        timeline["open_loops"] = [open_loop_to_dict(item) for item in loops]
        latest_pack_id = next(
            (run.get("context_pack_id") for run in timeline.get("runs") or [] if run.get("context_pack_id")),
            None,
        )
        if latest_pack_id:
            pack = await session.get(ContextPack, UUID(str(latest_pack_id)))
            manifest = json.loads(pack.manifest or "{}") if pack is not None else {}
            known = manifest.get("known_playbook") if isinstance(manifest, dict) else None
            if known:
                timeline["known_playbook"] = known
        return timeline
    except FounderOversightNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "focus_not_found", "message": str(exc)},
        ) from exc


@router.get("/context/run-outcomes")
async def get_run_outcomes(
    workspace_id: UUID,
    session: AsyncSession = Depends(get_db_session),
    access_scope: AccessScope = Depends(get_access_scope),
) -> dict[str, Any]:
    if not access_scope.allows_workspace(workspace_id):
        raise HTTPException(status_code=404, detail="Workspace not found")
    accessible_source_ids = set(await session.scalars(
        select(SourceDocument.id).where(
            source_access_predicate(access_scope, workspace_id=workspace_id)
        )
    ))
    report = await HarnessOutcomeService(session).summarize(
        workspace_id=workspace_id,
        accessible_source_ids=accessible_source_ids,
    )
    return report.to_dict()


@router.post("/context/prepare", response_model=ContextPrepareResponse)
async def prepare_context(
    payload: ContextPrepareRequest,
    session: AsyncSession = Depends(get_db_session),
    access_scope: AccessScope = Depends(get_access_scope),
) -> ContextPrepareResponse:
    restored_checkpoint = None
    if payload.checkpoint_source_document_id and payload.checkpoint_id:
        checkpoint_document = await session.scalar(select(SourceDocument).where(
            SourceDocument.id == payload.checkpoint_source_document_id,
            SourceDocument.workspace_id == payload.workspace_id,
            SourceDocument.source_type == "agent_session",
            source_access_predicate(access_scope, workspace_id=payload.workspace_id),
        ))
        if checkpoint_document is None:
            raise HTTPException(status_code=404, detail="Session checkpoint source not found")
        checkpoint_metadata = metadata_dict(checkpoint_document)
        connector_type = str(
            checkpoint_metadata.get("connector_type")
            or checkpoint_metadata.get("tool")
            or "unknown"
        ).strip().lower()
        if connector_type == "claude_code":
            connector_type = "claude"
        session_id = str(
            checkpoint_metadata.get("session_id")
            or checkpoint_document.external_id.rsplit(":", 1)[-1]
        ).strip()
        session_title = derive_session_topic(
            checkpoint_document.content,
            explicit_title=checkpoint_metadata.get("title"),
            tool=connector_type,
            session_id=session_id,
        ) or "Untitled session"
        try:
            restored_checkpoint = restore_session_checkpoint(
                checkpoint_document.content,
                checkpoint_metadata,
                payload.checkpoint_id,
                session_title=session_title,
                source_document_id=str(checkpoint_document.id),
                session_id=session_id,
                harness=connector_type,
                source_revision_number=int(checkpoint_document.revision_number or 1),
                source_content_sha256=checkpoint_document.content_sha256,
            )
        except SessionCheckpointNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
    compiler = ContextCompiler(session)
    try:
        result = await compiler.compile_context_pack(
            payload.objective or payload.goal or "",
            workspace_id=payload.workspace_id,
            repo_path=payload.repo_path,
            target_model=payload.target_model,
            token_budget=payload.token_budget,
            persist=True,
            objective_kind=("project_snapshot" if payload.mode == "project_snapshot" else "observed"),
            focus_component_id=payload.focus_component_id,
            objective_origin=payload.objective_origin,
            restored_checkpoint=restored_checkpoint,
            access_scope=access_scope,
        )
        await session.commit()
    except ContextBudgetExceededError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=422,
            detail={
                "code": "context_budget_too_small",
                "message": str(exc),
                "minimum_required_tokens": exc.minimum_required_tokens,
            },
        ) from exc
    except FocusValidationError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    except (InvalidGoalError, InvalidRepoPathError, ValueError) as exc:
        await session.rollback()
        raise HTTPException(
            status_code=422,
            detail={"code": "context_prepare_invalid_request", "message": str(exc)},
        ) from exc
    except ContextPersistenceError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=500,
            detail={"code": "context_persistence_failed", "message": str(exc)},
        ) from exc
    except Exception as exc:
        await session.rollback()
        raise HTTPException(
            status_code=500,
            detail={"code": "context_prepare_failed", "message": str(exc)},
        ) from exc

    if not result.context_pack_id:
        raise HTTPException(
            status_code=500,
            detail={
                "code": "context_persistence_failed",
                "message": "compiler returned no durable context_pack_id",
            },
        )
    return ContextPrepareResponse(
        context_pack_id=result.context_pack_id,
        schema_version=result.schema_version,
        markdown=result.markdown,
        manifest=result.manifest,
        health_score=result.health_score,
        selected_context=result.selected_items,
        excluded_context=result.excluded_items,
        focus=dict(result.manifest.get("focus") or {}),
    )
