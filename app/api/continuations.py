from __future__ import annotations

import ipaddress
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_access_scope
from app.database import get_db_session
from app.services.access import AccessScope
from app.services.context_compiler import (
    ContextBudgetExceededError,
    ContextPersistenceError,
    InvalidGoalError,
    InvalidRepoPathError,
)
from app.services.continuation import ContinuationError, ContinuationService
from app.services.continuation_runtime import (
    ContinuationRunError,
    ContinuationRunService,
    provider_readiness,
)


router = APIRouter()


class _ContinuationRequest(BaseModel):
    workspace_id: UUID
    repo_path: str | None = Field(default=None, min_length=1)
    objective: str | None = Field(default=None, min_length=1, max_length=2_000)
    checkpoint_id: str | None = Field(default=None, min_length=1, max_length=255)
    checkpoint_source_id: UUID | None = None
    target_model: str | None = Field(default=None, min_length=1, max_length=255)
    token_budget: int | None = Field(default=None, ge=300)

    @field_validator("repo_path", "target_model", "checkpoint_id")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must contain visible characters")
        return normalized

    @field_validator("objective")
    @classmethod
    def normalize_objective(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("value must contain visible characters")
        return normalized


class ContinuationPrepareRequest(_ContinuationRequest):
    sync_sessions: bool = False
    execute_commands: bool = False


class ContinuationRunRequest(_ContinuationRequest):
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=120)
    target_provider: Literal["codex", "claude", "opencode", "auto"] = "auto"
    provider_model: str | None = Field(default=None, min_length=1, max_length=255)

    @field_validator("idempotency_key", "provider_model")
    @classmethod
    def strip_run_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must contain visible characters")
        return normalized


@router.get("/continuations/providers")
async def get_continuation_providers(
    request: Request,
    workspace_id: UUID | None = None,
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
    providers = await provider_readiness()
    return {"providers": [item.to_dict() for item in providers]}


@router.post("/continuations/prepare")
async def prepare_continuation(
    payload: ContinuationPrepareRequest,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    access_scope: AccessScope = Depends(get_access_scope),
) -> dict[str, Any]:
    if payload.sync_sessions:
        _require_loopback_client(request)
    if not access_scope.allows_workspace(payload.workspace_id):
        raise HTTPException(status_code=404, detail="Workspace not found")
    if payload.sync_sessions and access_scope.principal_id != "local":
        raise HTTPException(
            status_code=403,
            detail={
                "code": "local_action_required",
                "message": (
                    "Session sync and command verification are available only "
                    "from the local app."
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
            checkpoint_id=payload.checkpoint_id,
            checkpoint_source_id=payload.checkpoint_source_id,
            target_model=payload.target_model,
            token_budget=payload.token_budget,
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
            checkpoint_id=payload.checkpoint_id,
            checkpoint_source_id=payload.checkpoint_source_id,
            target_model=payload.target_model,
            target_provider=payload.target_provider,
            provider_model=payload.provider_model,
            token_budget=payload.token_budget,
            idempotency_key=payload.idempotency_key,
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
