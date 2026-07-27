from __future__ import annotations

import asyncio
import ipaddress
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.dependencies import get_access_scope
from app.database import get_db_session
from app.models import AgentRun
from app.services.access import AccessScope
from app.services.context_compiler import (
    ContextBudgetExceededError,
    ContextPersistenceError,
    InvalidGoalError,
    InvalidRepoPathError,
)
from app.services.continuation import ContinuationError, ContinuationService
from app.services.harness_outcomes import HarnessOutcomeService
from app.services.harness_launcher import HarnessLaunchError, launch_harness_session
from app.services.harness_sessions import recorded_harness_session
from app.services.continuation_runtime import (
    ContinuationRunError,
    ContinuationRunService,
    ContinuationStageService,
    active_continuation_run,
    active_continuation_run_payload,
    awaiting_continuation_handoff,
    provider_readiness,
    reconcile_awaiting_continuation_handoffs,
    staged_continuation_payload,
)
from app.schemas.continuation_execution import (
    MAX_CONTINUATION_ARTIFACTS,
    ContinuationArtifactInput,
    TaskMode,
)


router = APIRouter()


class _ContinuationRequest(BaseModel):
    workspace_id: UUID
    repo_path: str | None = Field(default=None, min_length=1)
    objective: str | None = Field(default=None, min_length=1)
    objective_is_user_edited: bool = False
    task_mode: TaskMode | None = None
    checkpoint_id: str | None = Field(default=None, min_length=1, max_length=255)
    checkpoint_source_id: UUID | None = None
    source_provider: str | None = Field(default=None, min_length=1, max_length=50)
    source_session_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=255,
    )
    target_model: str | None = Field(default=None, min_length=1, max_length=255)
    token_budget: int | None = Field(default=None, ge=300)
    artifacts: tuple[ContinuationArtifactInput, ...] = Field(
        default=(),
        max_length=MAX_CONTINUATION_ARTIFACTS,
    )

    @field_validator(
        "repo_path",
        "target_model",
        "checkpoint_id",
        "source_session_id",
    )
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must contain visible characters")
        return normalized

    @field_validator("source_provider")
    @classmethod
    def normalize_source_provider(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if normalized == "claude_code":
            normalized = "claude"
        if not normalized:
            raise ValueError("value must contain visible characters")
        return normalized

    @field_validator("objective")
    @classmethod
    def validate_objective(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.strip():
            raise ValueError("value must contain visible characters")
        # The executable request is an immutable input. Matching and display
        # derivatives are compiled separately and must never replace it.
        return value

    @model_validator(mode="after")
    def validate_source_session_pair(self) -> "_ContinuationRequest":
        if (self.source_provider is None) != (self.source_session_id is None):
            raise ValueError(
                "source_provider and source_session_id must be provided together"
            )
        if self.objective_is_user_edited and self.objective is None:
            raise ValueError(
                "objective_is_user_edited requires an objective"
            )
        return self


class ContinuationPrepareRequest(_ContinuationRequest):
    sync_sessions: bool = False
    execute_commands: bool = False


class ContinuationRunRequest(_ContinuationRequest):
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=120)
    target_provider: Literal["codex", "claude", "opencode", "auto"] = "auto"
    provider_model: str | None = Field(default=None, min_length=1, max_length=255)
    provider_effort: Literal[
        "low",
        "medium",
        "high",
        "xhigh",
        "max",
        "ultra",
    ] | None = None

    @field_validator("idempotency_key", "provider_model")
    @classmethod
    def strip_run_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must contain visible characters")
        return normalized


class ContinuationHarnessOpenRequest(BaseModel):
    workspace_id: UUID


@router.get("/continuations/providers")
async def get_continuation_providers(
    request: Request,
    workspace_id: UUID | None = None,
    refresh: bool = False,
    session: AsyncSession = Depends(get_db_session),
    access_scope: AccessScope = Depends(get_access_scope),
) -> dict[str, Any]:
    _require_loopback_client(request)
    if access_scope.principal_id != "local":
        raise HTTPException(
            status_code=403,
            detail={
                "code": "local_action_required",
                "message": "Provider readiness is available only from the local app.",
            },
        )
    if workspace_id is not None and not access_scope.allows_workspace(workspace_id):
        raise HTTPException(status_code=404, detail="Workspace not found")
    providers = (
        await provider_readiness(force_refresh=True)
        if refresh
        else await provider_readiness()
    )
    if workspace_id is not None:
        await reconcile_awaiting_continuation_handoffs(
            session,
            workspace_id=workspace_id,
        )
    active_run = (
        await active_continuation_run(session, workspace_id=workspace_id)
        if workspace_id is not None
        else None
    )
    latest_run = (
        await HarnessOutcomeService(session).latest_continuation(
            workspace_id=workspace_id,
        )
        if workspace_id is not None
        else None
    )
    staged_handoff = (
        await awaiting_continuation_handoff(
            session,
            workspace_id=workspace_id,
        )
        if workspace_id is not None
        else None
    )
    return {
        "providers": [item.to_dict() for item in providers],
        "active_run": active_continuation_run_payload(active_run),
        "staged_handoff": staged_continuation_payload(staged_handoff),
        "latest_run": latest_run,
    }


@router.post("/continuations/{run_id}/open")
async def open_continuation_harness(
    run_id: UUID,
    payload: ContinuationHarnessOpenRequest,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    access_scope: AccessScope = Depends(get_access_scope),
) -> dict[str, Any]:
    _require_loopback_client(request)
    if access_scope.principal_id != "local":
        raise HTTPException(
            status_code=403,
            detail={
                "code": "local_action_required",
                "message": "Harness sessions can be opened only from the local app.",
            },
        )
    if not access_scope.allows_workspace(payload.workspace_id):
        raise HTTPException(status_code=404, detail="Continuation run not found")
    run = await session.scalar(
        select(AgentRun)
        .options(selectinload(AgentRun.observations))
        .where(
            AgentRun.id == run_id,
            AgentRun.workspace_id == payload.workspace_id,
            AgentRun.run_key.like("continuation:%"),
        )
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Continuation run not found")
    harness_session = recorded_harness_session(run.observations)
    if harness_session is None:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "harness_session_pending",
                "message": (
                    "The target harness has not reported a session that can be "
                    "opened yet."
                ),
            },
        )
    provider = str(harness_session["provider"])
    session_id = str(harness_session["session_id"])
    try:
        launch = await asyncio.to_thread(
            launch_harness_session,
            provider,
            session_id,
            cwd=str(harness_session.get("cwd") or "") or None,
        )
    except HarnessLaunchError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    return {
        "run_id": str(run.id),
        "provider": provider,
        "session_id": session_id,
        "launch": launch,
    }


@router.post("/continuations/prepare")
async def prepare_continuation(
    payload: ContinuationPrepareRequest,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    access_scope: AccessScope = Depends(get_access_scope),
) -> dict[str, Any]:
    if payload.sync_sessions or payload.artifacts:
        _require_loopback_client(request)
    if not access_scope.allows_workspace(payload.workspace_id):
        raise HTTPException(status_code=404, detail="Workspace not found")
    if (
        (payload.sync_sessions or payload.artifacts)
        and access_scope.principal_id != "local"
    ):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "local_action_required",
                "message": (
                    "Session sync, command verification, and local artifacts "
                    "are available only from the local app."
                ),
            },
        )
    if payload.execute_commands:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "checkpoint_command_replay_disabled",
                "message": (
                    "Imported session commands are untrusted evidence and are "
                    "not replayed automatically."
                ),
            },
        )

    try:
        result = await ContinuationService(session).prepare(
            workspace_id=payload.workspace_id,
            access_scope=access_scope,
            repo_path=payload.repo_path,
            objective=payload.objective,
            objective_is_user_edited=payload.objective_is_user_edited,
            checkpoint_id=payload.checkpoint_id,
            checkpoint_source_id=payload.checkpoint_source_id,
            source_provider=payload.source_provider,
            source_session_id=payload.source_session_id,
            target_model=payload.target_model,
            token_budget=payload.token_budget,
            task_mode=payload.task_mode,
            artifacts=payload.artifacts,
            sync_sessions=payload.sync_sessions,
        )
        await session.commit()
    except ContinuationError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
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
    except (InvalidGoalError, InvalidRepoPathError, ValueError) as exc:
        await session.rollback()
        raise HTTPException(
            status_code=422,
            detail={
                "code": "continuation_invalid_request",
                "message": str(exc),
            },
        ) from exc
    except ContextPersistenceError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=500,
            detail={
                "code": "continuation_persistence_failed",
                "message": str(exc),
            },
        ) from exc
    except Exception as exc:
        await session.rollback()
        raise HTTPException(
            status_code=500,
            detail={"code": "continuation_failed", "message": str(exc)},
        ) from exc
    return result.to_dict()


@router.post("/continuations/stage")
async def stage_continuation(
    payload: ContinuationRunRequest,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    access_scope: AccessScope = Depends(get_access_scope),
) -> dict[str, Any]:
    """Load context into a persistent harness thread without starting a turn."""

    _require_loopback_client(request)
    try:
        result = await ContinuationStageService(session).stage(
            workspace_id=payload.workspace_id,
            access_scope=access_scope,
            repo_path=payload.repo_path,
            objective=payload.objective,
            objective_is_user_edited=payload.objective_is_user_edited,
            checkpoint_id=payload.checkpoint_id,
            checkpoint_source_id=payload.checkpoint_source_id,
            source_provider=payload.source_provider,
            source_session_id=payload.source_session_id,
            target_model=payload.target_model,
            target_provider=payload.target_provider,
            provider_model=payload.provider_model,
            provider_effort=payload.provider_effort,
            token_budget=payload.token_budget,
            idempotency_key=payload.idempotency_key,
            task_mode=payload.task_mode,
            artifacts=payload.artifacts,
        )
    except (ContinuationRunError, ContinuationError) as exc:
        await session.rollback()
        detail: dict[str, Any] = {"code": exc.code, "message": str(exc)}
        if isinstance(exc, ContinuationRunError):
            if exc.readiness is not None:
                detail["readiness"] = exc.readiness
            if exc.blocker is not None:
                detail["blocker"] = exc.blocker
        raise HTTPException(
            status_code=exc.status_code,
            detail=detail,
        ) from exc
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
    except (InvalidGoalError, InvalidRepoPathError, ValueError) as exc:
        await session.rollback()
        raise HTTPException(
            status_code=422,
            detail={
                "code": "continuation_invalid_request",
                "message": str(exc),
            },
        ) from exc
    except ContextPersistenceError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=500,
            detail={
                "code": "continuation_persistence_failed",
                "message": str(exc),
            },
        ) from exc
    except Exception as exc:
        await session.rollback()
        raise HTTPException(
            status_code=500,
            detail={"code": "continuation_stage_failed", "message": str(exc)},
        ) from exc
    return result.to_dict()


@router.post("/continuations")
@router.post("/continuations/run")
async def run_continuation(
    payload: ContinuationRunRequest,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    access_scope: AccessScope = Depends(get_access_scope),
) -> dict[str, Any]:
    _require_loopback_client(request)
    try:
        result = await ContinuationRunService(session).run(
            workspace_id=payload.workspace_id,
            access_scope=access_scope,
            repo_path=payload.repo_path,
            objective=payload.objective,
            objective_is_user_edited=payload.objective_is_user_edited,
            checkpoint_id=payload.checkpoint_id,
            checkpoint_source_id=payload.checkpoint_source_id,
            source_provider=payload.source_provider,
            source_session_id=payload.source_session_id,
            target_model=payload.target_model,
            target_provider=payload.target_provider,
            provider_model=payload.provider_model,
            provider_effort=payload.provider_effort,
            token_budget=payload.token_budget,
            idempotency_key=payload.idempotency_key,
            task_mode=payload.task_mode,
            artifacts=payload.artifacts,
        )
    except (ContinuationRunError, ContinuationError) as exc:
        await session.rollback()
        detail: dict[str, Any] = {"code": exc.code, "message": str(exc)}
        if isinstance(exc, ContinuationRunError):
            if exc.readiness is not None:
                detail["readiness"] = exc.readiness
            if exc.blocker is not None:
                detail["blocker"] = exc.blocker
        raise HTTPException(
            status_code=exc.status_code,
            detail=detail,
        ) from exc
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
    except (InvalidGoalError, InvalidRepoPathError, ValueError) as exc:
        await session.rollback()
        raise HTTPException(
            status_code=422,
            detail={
                "code": "continuation_invalid_request",
                "message": str(exc),
            },
        ) from exc
    except ContextPersistenceError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=500,
            detail={
                "code": "continuation_persistence_failed",
                "message": str(exc),
            },
        ) from exc
    except Exception as exc:
        await session.rollback()
        raise HTTPException(
            status_code=500,
            detail={"code": "continuation_run_failed", "message": str(exc)},
        ) from exc
    return result.to_dict()


def _require_loopback_client(request: Request) -> None:
    client = request.client
    host = str(client.host if client is not None else "").strip()
    try:
        address = ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        address = None
    is_loopback = bool(
        address
        and (
            address.is_loopback
            or (
                isinstance(address, ipaddress.IPv6Address)
                and address.ipv4_mapped is not None
                and address.ipv4_mapped.is_loopback
            )
        )
    )
    if not is_loopback:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "local_action_required",
                "message": (
                    "This action is available only to a loopback client on "
                    "the local machine."
                ),
            },
        )
