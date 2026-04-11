from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db_session
from app.evals.demo_seed import DEFAULT_WORKSPACE_NAME, seed_demo_workspace
from app.models.user import Workspace
from app.schemas.user import WorkspaceCreate, WorkspaceRead


router = APIRouter()


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


@router.post("/seed-demo")
async def seed_demo(
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, object]:
    """Create (or return) the canonical deterministic demo workspace.

    This delegates to ``seed_demo_workspace`` — the same path exercised by
    ``scripts/seed_demo.py`` and covered by ``tests/test_evals/test_demo_seed.py``
    — so the workspace ends up with the full knowledge model, components,
    provenance links, and eval cases that Brief / Query / Accuracy depend on.

    Idempotent: calling this repeatedly returns the same workspace id with
    ``status="existing"`` after the first successful run. A race between two
    concurrent callers is mapped to a 409 instead of leaking an IntegrityError.
    """
    try:
        result = await seed_demo_workspace(session, replace_existing=False)
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Demo workspace is already being seeded by another request.",
        ) from exc

    return {
        "workspaceId": str(result.workspace_id),
        "workspaceName": result.workspace_name,
        "status": result.status,
        "seededCaseCount": result.seeded_case_count,
        "defaultWorkspaceName": DEFAULT_WORKSPACE_NAME,
    }


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
