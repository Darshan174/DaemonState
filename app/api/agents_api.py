from __future__ import annotations

from pydantic import BaseModel
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db_session
from app.agents.gap_detector import GapDetectorAgent, GapReport, GapItem
from app.agents.context_pack import ContextPackAgent, ContextPack
from app.agents.relationship_agent import RelationshipAgent, RelationshipReport, SuggestedRelationship

router = APIRouter()


class AgentRequest(BaseModel):
    api_key: str | None = None
    model: str | None = None


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
) -> GapReportOut:
    agent = GapDetectorAgent(session, api_key=payload.api_key, model=payload.model)
    report = await agent.run()
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
) -> ContextPackOut:
    agent = ContextPackAgent(session, api_key=payload.api_key, model=payload.model)
    pack = await agent.run()
    return ContextPackOut(
        content=pack.content,
        entity_count=pack.entity_count,
        generated_at=pack.generated_at,
    )


@router.post("/agents/relationships", response_model=RelationshipReportOut)
async def run_relationship_agent(
    payload: AgentRequest,
    session: AsyncSession = Depends(get_db_session),
) -> RelationshipReportOut:
    agent = RelationshipAgent(session, api_key=payload.api_key, model=payload.model)
    report = await agent.run()
    return RelationshipReportOut(
        suggested=[SuggestedRelOut(**r.__dict__) for r in report.suggested],
        duplicates=report.duplicates,
        message=report.message,
    )
