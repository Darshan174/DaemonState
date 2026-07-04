from __future__ import annotations

from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db_session
from app.services.context_compiler import ContextCompiler

router = APIRouter()


class PrepareContextRequest(BaseModel):
    goal: str | None = Field(default=None, min_length=1)
    objective: str | None = Field(default=None, min_length=1)
    workspace_id: UUID | None = None
    repo_path: str | None = None
    repo: str | None = None
    target_model: str | None = None
    token_budget: int | None = Field(default=None, ge=1)
    budget: int | None = Field(default=None, ge=1)


class PrepareContextResponse(BaseModel):
    pack_id: str | None = None
    markdown: str
    manifest: dict


@router.post("/context/prepare", response_model=PrepareContextResponse)
async def prepare_context(
    payload: PrepareContextRequest,
    session: AsyncSession = Depends(get_db_session),
) -> PrepareContextResponse:
    goal = payload.goal or payload.objective or ""
    repo_path = payload.repo_path or payload.repo or str(Path.cwd())
    token_budget = payload.token_budget if payload.token_budget is not None else payload.budget
    compiler = ContextCompiler(session)
    result = await compiler.compile_context_pack(
        goal,
        workspace_id=payload.workspace_id,
        repo_path=repo_path,
        target_model=payload.target_model,
        token_budget=token_budget,
    )
    return PrepareContextResponse(
        pack_id=result.pack_id,
        markdown=result.markdown,
        manifest=result.manifest,
    )
