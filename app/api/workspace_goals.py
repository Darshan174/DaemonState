from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_access_scope
from app.database import get_db_session
from app.models import Component, SourceDocument, Workspace
from app.services.access import AccessScope, source_access_predicate
from app.services.focus_policy import focus_eligibility
from app.services.workspace_goals import (
    clear_workspace_goal,
    goal_to_dict,
    select_workspace_goal,
)


router = APIRouter()


class WorkspaceGoalSelect(BaseModel):
    title: str = Field(min_length=3, max_length=2000)
    component_id: UUID | None = None
    source_kind: Literal["user_selected", "suggested_card"] = "user_selected"
    source_id: str | None = Field(default=None, max_length=255)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if len(normalized) < 3:
            raise ValueError("title must contain at least 3 visible characters")
        return normalized


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


@router.put("/workspaces/{workspace_id}/current-goal")
async def set_current_goal(
    workspace_id: UUID,
    payload: WorkspaceGoalSelect,
    session: AsyncSession = Depends(get_db_session),
    access_scope: AccessScope = Depends(get_access_scope),
) -> dict:
    await _require_workspace(session, workspace_id, access_scope)
    if payload.component_id is not None:
        component = await session.scalar(
            select(Component)
            .join(SourceDocument, Component.source_document_id == SourceDocument.id)
            .where(
                Component.id == payload.component_id,
                Component.workspace_id == workspace_id,
                source_access_predicate(access_scope, workspace_id=workspace_id),
            )
        )
        if component is None:
            raise HTTPException(status_code=404, detail="Goal component not found")
        eligible, reason = focus_eligibility(component.fact_type, component.status)
        if not eligible:
            raise HTTPException(status_code=422, detail=reason)
    goal = await select_workspace_goal(
        session,
        workspace_id=workspace_id,
        title=payload.title,
        component_id=payload.component_id,
        source_kind=payload.source_kind,
        source_id=payload.source_id,
        selected_by=access_scope.principal_id,
    )
    await session.commit()
    return goal_to_dict(goal)


@router.delete("/workspaces/{workspace_id}/current-goal", status_code=204)
async def delete_current_goal(
    workspace_id: UUID,
    session: AsyncSession = Depends(get_db_session),
    access_scope: AccessScope = Depends(get_access_scope),
) -> Response:
    await _require_workspace(session, workspace_id, access_scope)
    await clear_workspace_goal(session, workspace_id=workspace_id)
    await session.commit()
    return Response(status_code=204)
