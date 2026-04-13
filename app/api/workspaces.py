"""Stable founder-facing workspace lifecycle and demo-seed routes."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import AliasChoices, BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db_session
from app.evals.demo_seed import (
    DEFAULT_WORKSPACE_NAME,
    SeedWorkspaceNotFoundError,
    seed_demo_into_workspace,
    seed_demo_workspace,
)
from app.models.user import Workspace
from app.schemas.user import WorkspaceCreate, WorkspaceRead


router = APIRouter()


class SeedDemoRequest(BaseModel):
    """Stable request contract for POST /api/seed-demo."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    workspace_id: UUID | None = Field(
        default=None,
        validation_alias=AliasChoices("workspace_id", "workspaceId"),
    )


class SeedDemoResponse(BaseModel):
    """Stable response contract for POST /api/seed-demo."""

    workspaceId: UUID
    workspaceName: str
    status: Literal["created", "existing"]
    seededCaseCount: int
    defaultWorkspaceName: str


@router.post(
    "/workspaces",
    response_model=WorkspaceRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_workspace(
    payload: WorkspaceCreate,
    session: AsyncSession = Depends(get_db_session),
) -> WorkspaceRead:
    workspace = Workspace(**payload.model_dump())
    session.add(workspace)
    await session.commit()
    await session.refresh(workspace)
    return WorkspaceRead.model_validate(workspace)


@router.post(
    "/seed-demo",
    response_model=SeedDemoResponse,
)
async def seed_demo(
    payload: SeedDemoRequest | None = None,
    session: AsyncSession = Depends(get_db_session),
) -> SeedDemoResponse:
    """Create or re-use the canonical deterministic demo workspace.

    Founder-facing flows should call this route directly. The request contract
    accepts either no body for the canonical demo workspace or a specific
    ``workspace_id``/``workspaceId`` for targeted seeding into an existing
    workspace.
    """
    try:
        if payload and payload.workspace_id is not None:
            result = await seed_demo_into_workspace(
                session,
                workspace_id=payload.workspace_id,
            )
        else:
            result = await seed_demo_workspace(session, replace_existing=False)
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Demo workspace is already being seeded by another request.",
        ) from exc
    except SeedWorkspaceNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    return SeedDemoResponse(
        workspaceId=result.workspace_id,
        workspaceName=result.workspace_name,
        status=result.status,
        seededCaseCount=result.seeded_case_count,
        defaultWorkspaceName=DEFAULT_WORKSPACE_NAME,
    )


@router.get("/workspaces", response_model=list[WorkspaceRead])
async def list_workspaces(
    session: AsyncSession = Depends(get_db_session),
) -> list[WorkspaceRead]:
    result = await session.scalars(select(Workspace).order_by(Workspace.created_at.desc()))
    return [WorkspaceRead.model_validate(item) for item in result]


@router.get("/workspaces/{workspace_id}", response_model=WorkspaceRead)
async def get_workspace(
    workspace_id: UUID,
    session: AsyncSession = Depends(get_db_session),
) -> WorkspaceRead:
    workspace = await session.scalar(select(Workspace).where(Workspace.id == workspace_id))
    if workspace is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")

    return WorkspaceRead.model_validate(workspace)
