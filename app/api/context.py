from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db_session
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

router = APIRouter()


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

    @model_validator(mode="after")
    def _has_objective(self) -> "ContextPrepareRequest":
        origin = self.objective_origin or (
            "project_snapshot" if self.mode == "project_snapshot" else "trusted_human"
        )
        if origin == "trusted_human" and not (self.objective or self.goal):
            raise ValueError("objective is required")
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


@router.get("/context/run-timeline")
async def get_run_timeline(
    workspace_id: UUID,
    focus_component_id: UUID,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    try:
        return await FounderOversightService(session).build_timeline(
            workspace_id=workspace_id,
            focus_component_id=focus_component_id,
        )
    except FounderOversightNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "focus_not_found", "message": str(exc)},
        ) from exc


@router.post("/context/prepare", response_model=ContextPrepareResponse)
async def prepare_context(
    payload: ContextPrepareRequest,
    session: AsyncSession = Depends(get_db_session),
) -> ContextPrepareResponse:
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
