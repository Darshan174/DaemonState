from __future__ import annotations

import re
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_access_scope
from app.database import get_db_session
from app.models import Workspace
from app.services.access import AccessScope
from app.services.workspace_lifecycle import (
    WorkspaceHasActiveRunError,
    delete_workspace_graph,
    require_no_active_run,
    workspace_to_dict,
)
from app.time import utc_now


router = APIRouter()


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    slug: str | None = Field(default=None, max_length=255)
    kind: Literal["project", "demo", "sandbox"] = "project"

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("name must contain a visible character")
        return normalized


class WorkspaceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    status: Literal["active", "archived"] | None = None
    kind: Literal["project", "demo", "sandbox"] | None = None

    @field_validator("name")
    @classmethod
    def clean_optional_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("name must contain a visible character")
        return normalized


async def _workspace_for_scope(
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


@router.get("/workspaces")
async def list_workspaces(
    include_archived: bool = False,
    session: AsyncSession = Depends(get_db_session),
    access_scope: AccessScope = Depends(get_access_scope),
) -> list[dict]:
    stmt = select(Workspace).order_by(Workspace.created_at, Workspace.id)
    if not include_archived:
        stmt = stmt.where(Workspace.status == "active")
    if not access_scope.unrestricted:
        stmt = stmt.where(Workspace.id.in_(access_scope.workspace_ids))
    workspaces = list(await session.scalars(stmt))
    return [await workspace_to_dict(session, workspace) for workspace in workspaces]


@router.post("/workspaces", status_code=201)
async def create_workspace(
    payload: WorkspaceCreate,
    session: AsyncSession = Depends(get_db_session),
    access_scope: AccessScope = Depends(get_access_scope),
) -> dict:
    if not access_scope.unrestricted:
        raise HTTPException(status_code=403, detail="This API key cannot create workspaces")
    slug = await _available_slug(session, payload.slug or payload.name)
    workspace = Workspace(
        name=payload.name,
        slug=slug,
        kind=payload.kind,
        status="active",
    )
    session.add(workspace)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Workspace slug already exists") from exc
    await session.refresh(workspace)
    return await workspace_to_dict(session, workspace)


@router.patch("/workspaces/{workspace_id}")
async def update_workspace(
    workspace_id: UUID,
    payload: WorkspaceUpdate,
    session: AsyncSession = Depends(get_db_session),
    access_scope: AccessScope = Depends(get_access_scope),
) -> dict:
    workspace = await _workspace_for_scope(session, workspace_id, access_scope)
    if payload.name is not None:
        workspace.name = payload.name
    if payload.kind is not None:
        workspace.kind = payload.kind
    if payload.status is not None:
        if payload.status == "archived":
            try:
                await require_no_active_run(session, workspace.id)
            except WorkspaceHasActiveRunError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
        workspace.status = payload.status
        workspace.archived_at = utc_now() if payload.status == "archived" else None
    await session.commit()
    await session.refresh(workspace)
    return await workspace_to_dict(session, workspace)


@router.delete("/workspaces/{workspace_id}", status_code=204)
async def delete_workspace(
    workspace_id: UUID,
    confirm_name: str = Query(min_length=1),
    session: AsyncSession = Depends(get_db_session),
    access_scope: AccessScope = Depends(get_access_scope),
) -> Response:
    workspace = await _workspace_for_scope(session, workspace_id, access_scope)
    if workspace.status != "archived":
        raise HTTPException(status_code=409, detail="Archive the workspace before deleting it")
    if confirm_name.strip() != workspace.name:
        raise HTTPException(status_code=422, detail="Workspace name confirmation does not match")
    try:
        await delete_workspace_graph(session, workspace.id)
        await session.commit()
    except WorkspaceHasActiveRunError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return Response(status_code=204)


async def _available_slug(session: AsyncSession, value: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-") or "project"
    base = base[:240].rstrip("-") or "project"
    candidate = base
    suffix = 2
    while await session.scalar(select(Workspace.id).where(Workspace.slug == candidate)):
        candidate = f"{base[:240 - len(str(suffix))]}-{suffix}"
        suffix += 1
    return candidate
