from __future__ import annotations

import json
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_access_scope
from app.database import get_db_session
from app.models import (
    ActiveContextPointer,
    ContextArtifactCandidate,
    ContextCandidateEvaluation,
    ContextObservationBundle,
)
from app.services.access import AccessScope
from app.services.context_quality import (
    ContextActivationConflict,
    ContextEvidenceStale,
    ContextRollbackUnsafe,
    access_scope_sha256,
    activate_reviewed_candidate,
    assert_candidate_evidence_current,
    candidate_permissions_current,
    record_active_context_outcome,
    rollback_active_context,
)


router = APIRouter()


class ContextPointerRequest(BaseModel):
    workspace_id: UUID
    expected_generation: int = Field(ge=0)
    reason: str = Field(min_length=3, max_length=2_000)


class ContextActivationRequest(ContextPointerRequest):
    evaluation_id: UUID


class ContextRollbackRequest(ContextPointerRequest):
    target_candidate_id: UUID


class ContextOutcomeRequest(ContextPointerRequest):
    outcome: Literal["helpful", "incomplete", "incorrect", "unsafe", "stale"]


def _json_value(value: str | None, fallback: Any) -> Any:
    try:
        return json.loads(value or "")
    except (TypeError, json.JSONDecodeError):
        return fallback


def _require_workspace_access(access_scope: AccessScope, workspace_id: UUID) -> None:
    if not access_scope.allows_workspace(workspace_id):
        raise HTTPException(status_code=404, detail="Workspace not found")


@router.get("/context-quality/candidates")
async def list_context_candidates(
    workspace_id: UUID,
    context_kind: Literal["session", "workspace"] | None = None,
    include_content: bool = False,
    limit: int = Query(default=20, ge=1, le=100),
    session: AsyncSession = Depends(get_db_session),
    access_scope: AccessScope = Depends(get_access_scope),
) -> dict[str, Any]:
    _require_workspace_access(access_scope, workspace_id)
    access_fingerprint = access_scope_sha256(access_scope)
    statement = select(ContextArtifactCandidate).where(
        ContextArtifactCandidate.workspace_id == workspace_id,
        ContextArtifactCandidate.access_scope_sha256 == access_fingerprint,
    )
    if context_kind is not None:
        statement = statement.where(
            ContextArtifactCandidate.context_kind == context_kind
        )
    candidates = list(await session.scalars(
        statement.order_by(
            ContextArtifactCandidate.created_at.desc(),
            ContextArtifactCandidate.id.desc(),
        ).limit(limit)
    ))
    values: list[dict[str, Any]] = []
    for candidate in candidates:
        evaluation = await session.scalar(
            select(ContextCandidateEvaluation)
            .where(ContextCandidateEvaluation.candidate_id == candidate.id)
            .order_by(
                ContextCandidateEvaluation.created_at.desc(),
                ContextCandidateEvaluation.id.desc(),
            )
            .limit(1)
        )
        pointer = await session.scalar(select(ActiveContextPointer).where(
            ActiveContextPointer.workspace_id == workspace_id,
            ActiveContextPointer.context_kind == candidate.context_kind,
            ActiveContextPointer.scope_key_sha256 == candidate.scope_key_sha256,
            ActiveContextPointer.access_scope_sha256 == candidate.access_scope_sha256,
            ActiveContextPointer.delivery_profile_sha256
            == candidate.delivery_profile_sha256,
        ))
        observation = await session.get(
            ContextObservationBundle, candidate.observation_bundle_id
        )
        permissions_current = await candidate_permissions_current(
            session,
            candidate=candidate,
            access_scope=access_scope,
        )
        pointer_bound = bool(
            pointer
            and evaluation
            and pointer.active_candidate_id == candidate.id
            and pointer.active_evaluation_id == evaluation.id
        )
        runtime_current: bool | None = None
        if pointer_bound:
            runtime_current = False
            if permissions_current:
                try:
                    await assert_candidate_evidence_current(
                        session,
                        candidate=candidate,
                        access_scope=access_scope,
                        validate_runtime_snapshot=True,
                    )
                except ContextEvidenceStale:
                    pass
                else:
                    runtime_current = True
        active = bool(pointer_bound and permissions_current and runtime_current)
        item: dict[str, Any] = {
            "candidate_id": str(candidate.id),
            "context_kind": candidate.context_kind,
            "artifact_schema_version": candidate.artifact_schema_version,
            "compiler_version": candidate.compiler_version,
            "renderer_version": candidate.renderer_version,
            "policy_version": candidate.policy_version,
            "artifact_sha256": candidate.content_sha256,
            "semantic_sha256": candidate.semantic_sha256,
            "observation_sha256": (
                observation.observation_sha256 if observation is not None else None
            ),
            "repository_snapshot_sha256": (
                observation.repository_snapshot_sha256
                if observation is not None
                else None
            ),
            "decision": evaluation.decision if evaluation is not None else None,
            "evaluation_id": str(evaluation.id) if evaluation is not None else None,
            "hard_failures": _json_value(
                evaluation.hard_failures_json if evaluation is not None else None,
                [],
            ),
            "warnings": _json_value(
                evaluation.warnings_json if evaluation is not None else None,
                [],
            ),
            "quality_vector": _json_value(
                evaluation.metrics_json if evaluation is not None else None,
                {},
            ),
            "diff": _json_value(
                evaluation.diff_json if evaluation is not None else None,
                {},
            ),
            "pointer_id": str(pointer.id) if pointer is not None else None,
            "pointer_generation": pointer.generation if pointer is not None else 0,
            "active": active,
            "copy_allowed": active,
            "permissions_current": permissions_current,
            "runtime_current": runtime_current,
            "created_at": candidate.created_at,
        }
        if include_content and permissions_current:
            item["content"] = candidate.content
        values.append(item)
    return {"workspace_id": str(workspace_id), "candidates": values}


@router.post("/context-quality/candidates/{candidate_id}/activate")
async def activate_context_candidate(
    candidate_id: UUID,
    body: ContextActivationRequest,
    session: AsyncSession = Depends(get_db_session),
    access_scope: AccessScope = Depends(get_access_scope),
) -> dict[str, Any]:
    _require_workspace_access(access_scope, body.workspace_id)
    try:
        activation = await activate_reviewed_candidate(
            session,
            workspace_id=body.workspace_id,
            candidate_id=candidate_id,
            expected_generation=body.expected_generation,
            expected_evaluation_id=body.evaluation_id,
            access_scope_sha256_value=access_scope_sha256(access_scope),
            access_scope=access_scope,
            actor=access_scope.principal_id,
            reason=body.reason,
        )
        await session.commit()
    except LookupError as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ContextActivationConflict, ContextRollbackUnsafe) as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"quality_control": activation.model_dump(mode="json")}


@router.post("/context-quality/pointers/{pointer_id}/rollback")
async def rollback_context_pointer(
    pointer_id: UUID,
    body: ContextRollbackRequest,
    session: AsyncSession = Depends(get_db_session),
    access_scope: AccessScope = Depends(get_access_scope),
) -> dict[str, Any]:
    _require_workspace_access(access_scope, body.workspace_id)
    try:
        activation = await rollback_active_context(
            session,
            workspace_id=body.workspace_id,
            pointer_id=pointer_id,
            target_candidate_id=body.target_candidate_id,
            expected_generation=body.expected_generation,
            access_scope_sha256_value=access_scope_sha256(access_scope),
            access_scope=access_scope,
            actor=access_scope.principal_id,
            reason=body.reason,
        )
        await session.commit()
    except LookupError as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ContextActivationConflict, ContextRollbackUnsafe) as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"quality_control": activation.model_dump(mode="json")}


@router.post("/context-quality/pointers/{pointer_id}/outcome")
async def record_context_outcome(
    pointer_id: UUID,
    body: ContextOutcomeRequest,
    session: AsyncSession = Depends(get_db_session),
    access_scope: AccessScope = Depends(get_access_scope),
) -> dict[str, Any]:
    _require_workspace_access(access_scope, body.workspace_id)
    try:
        activation = await record_active_context_outcome(
            session,
            workspace_id=body.workspace_id,
            pointer_id=pointer_id,
            expected_generation=body.expected_generation,
            access_scope_sha256_value=access_scope_sha256(access_scope),
            access_scope=access_scope,
            outcome=body.outcome,
            actor=access_scope.principal_id,
            reason=body.reason,
        )
        await session.commit()
    except LookupError as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ContextActivationConflict, ContextRollbackUnsafe) as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"quality_control": activation.model_dump(mode="json")}
