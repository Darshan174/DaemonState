from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db_session
from app.api.dependencies import get_access_scope
from app.agents.gap_detector import GapDetectorAgent
from app.agents.context_pack import ContextPackAgent
from app.agents.relationship_agent import RelationshipAgent
from app.services.access import AccessScope

router = APIRouter()


class AgentRequest(BaseModel):
    api_key: str | None = None
    model: str | None = None
    workspace_id: UUID | None = None
    component_ids: list[UUID] | None = None


class GapItemOut(BaseModel):
    category: str
    severity: str
    title: str
    detail: str
    entity_name: str
    recommendation: str


class GapReportOut(BaseModel):
    summary: str
    gaps: list[GapItemOut]
    ready_to_ship: list[str]
    blocked: list[str]
    stats: dict


class ContextPackOut(BaseModel):
    content: str
    entity_count: int
    generated_at: str


class SuggestedRelOut(BaseModel):
    source_name: str
    target_name: str
    relationship_type: str
    confidence: float
    reasoning: str


class RelationshipReportOut(BaseModel):
    suggested: list[SuggestedRelOut]
    duplicates: list[dict]
    message: str


@router.post("/agents/gaps", response_model=GapReportOut)
async def run_gap_detector(
    payload: AgentRequest,
    session: AsyncSession = Depends(get_db_session),
    access_scope: AccessScope = Depends(get_access_scope),
) -> GapReportOut:
    _enforce_agent_workspace_access(payload, access_scope)
    agent = GapDetectorAgent(session, api_key=payload.api_key, model=payload.model)
    report = await agent.run(
        workspace_id=payload.workspace_id,
        access_scope=access_scope,
    )
    return GapReportOut(
        summary=report.summary,
        gaps=[GapItemOut(**g.__dict__) for g in report.gaps],
        ready_to_ship=report.ready_to_ship,
        blocked=report.blocked,
        stats=report.stats,
    )


@router.post("/agents/context-pack", response_model=ContextPackOut)
async def run_context_pack(
    payload: AgentRequest,
    session: AsyncSession = Depends(get_db_session),
    access_scope: AccessScope = Depends(get_access_scope),
) -> ContextPackOut:
    _enforce_agent_workspace_access(payload, access_scope)
    agent = ContextPackAgent(session, api_key=payload.api_key, model=payload.model)
    pack = await agent.run(
        component_ids=payload.component_ids,
        workspace_id=payload.workspace_id,
        access_scope=access_scope,
    )
    return ContextPackOut(
        content=pack.content,
        entity_count=pack.entity_count,
        generated_at=pack.generated_at,
    )


@router.post("/agents/relationships", response_model=RelationshipReportOut)
async def run_relationship_agent(
    payload: AgentRequest,
    session: AsyncSession = Depends(get_db_session),
    access_scope: AccessScope = Depends(get_access_scope),
) -> RelationshipReportOut:
    if payload.workspace_id is None:
        raise HTTPException(status_code=422, detail="workspace_id is required")
    _enforce_agent_workspace_access(payload, access_scope)
    agent = RelationshipAgent(session, api_key=payload.api_key, model=payload.model)
    try:
        report = await agent.run(
            workspace_id=str(payload.workspace_id),
            access_scope=access_scope,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return RelationshipReportOut(
        suggested=[SuggestedRelOut(**r.__dict__) for r in report.suggested],
        duplicates=report.duplicates,
        message=report.message,
    )


def _enforce_agent_workspace_access(
    payload: AgentRequest,
    access_scope: AccessScope,
) -> None:
    if payload.workspace_id is None:
        if not access_scope.unrestricted:
            raise HTTPException(
                status_code=422,
                detail="workspace_id is required",
            )
        return
    if not access_scope.allows_workspace(payload.workspace_id):
        raise HTTPException(status_code=404, detail="Workspace not found")
