from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AgentRun, ContextPack, WorkspaceGoal
from app.time import utc_now


ACTIVE_RUN_STATUSES = frozenset({"queued", "running", "in_progress"})


def goal_to_dict(goal: WorkspaceGoal) -> dict:
    return {
        "id": str(goal.id),
        "workspace_id": str(goal.workspace_id),
        "title": goal.title,
        "component_id": str(goal.component_id) if goal.component_id else None,
        "source_kind": goal.source_kind,
        "source_id": goal.source_id,
        "selected_by": goal.selected_by,
        "selected_at": goal.selected_at,
        "can_clear": True,
    }


async def resolve_current_goal(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    allowed_component_ids: set[UUID] | None = None,
) -> dict | None:
    """Return active work, never an objective inferred from an old context pack."""
    run = await session.scalar(
        select(AgentRun)
        .where(
            AgentRun.workspace_id == workspace_id,
            AgentRun.status.in_(ACTIVE_RUN_STATUSES),
            AgentRun.objective.is_not(None),
        )
        .order_by(AgentRun.started_at.desc(), AgentRun.id.desc())
        .limit(1)
    )
    if run is not None and str(run.objective or "").strip():
        component_id = None
        if run.context_pack_id:
            pack = await session.get(ContextPack, run.context_pack_id)
            candidate = pack.focus_component_id if pack is not None else None
            if candidate and (
                allowed_component_ids is None or candidate in allowed_component_ids
            ):
                component_id = candidate
        return {
            "id": f"run:{run.id}",
            "workspace_id": str(workspace_id),
            "title": str(run.objective).strip(),
            "component_id": str(component_id) if component_id else None,
            "source_kind": "active_agent_run",
            "source_id": str(run.id),
            "selected_by": run.tool or "agent_harness",
            "selected_at": run.started_at,
            "can_clear": False,
        }

    goal = await session.scalar(
        select(WorkspaceGoal)
        .where(
            WorkspaceGoal.workspace_id == workspace_id,
            WorkspaceGoal.status == "active",
        )
        .order_by(WorkspaceGoal.selected_at.desc(), WorkspaceGoal.id.desc())
        .limit(1)
    )
    return goal_to_dict(goal) if goal is not None else None


async def select_workspace_goal(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    title: str,
    component_id: UUID | None,
    source_kind: str,
    source_id: str | None,
    selected_by: str,
    selected_at: datetime | None = None,
) -> WorkspaceGoal:
    now = selected_at or utc_now()
    active = list(await session.scalars(
        select(WorkspaceGoal).where(
            WorkspaceGoal.workspace_id == workspace_id,
            WorkspaceGoal.status == "active",
        )
    ))
    for previous in active:
        previous.status = "replaced"
        previous.ended_at = now
    goal = WorkspaceGoal(
        workspace_id=workspace_id,
        title=" ".join(title.split()),
        component_id=component_id,
        status="active",
        source_kind=source_kind,
        source_id=source_id,
        selected_by=selected_by,
        selected_at=now,
    )
    session.add(goal)
    await session.flush()
    return goal


async def clear_workspace_goal(
    session: AsyncSession,
    *,
    workspace_id: UUID,
) -> WorkspaceGoal | None:
    goal = await session.scalar(
        select(WorkspaceGoal).where(
            WorkspaceGoal.workspace_id == workspace_id,
            WorkspaceGoal.status == "active",
        )
    )
    if goal is None:
        return None
    goal.status = "cleared"
    goal.ended_at = utc_now()
    await session.flush()
    return goal
