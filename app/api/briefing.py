from __future__ import annotations

from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db_session
from app.models import Component, Model

router = APIRouter()


class BriefingComponent(BaseModel):
    id: str
    model_name: str
    name: str
    value: str
    confidence: float
    status: str
    created_at: datetime | None = None


class BriefingResponse(BaseModel):
    recent_components: list[BriefingComponent]
    needs_review: list[BriefingComponent]
    stale: list[BriefingComponent]


@router.get("/briefing", response_model=BriefingResponse)
async def get_briefing(
    days: int = 7,
    session: AsyncSession = Depends(get_db_session),
) -> BriefingResponse:
    since = datetime.now(timezone.utc) - timedelta(days=days)

    all_components = list(await session.scalars(
        select(Component)
        .options(selectinload(Component.model))
        .where(Component.status.in_(["active", "needs_review", "stale"]))
        .order_by(Component.created_at.desc())
    ))

    recent = [c for c in all_components if c.created_at and c.created_at >= since]
    needs_review = [c for c in all_components if c.status == "needs_review"]
    stale = [c for c in all_components if c.status == "stale"]

    def serialize(c: Component) -> BriefingComponent:
        return BriefingComponent(
            id=str(c.id),
            model_name=c.model.name if c.model else "Unknown",
            name=c.name, value=c.value,
            confidence=c.confidence, status=c.status,
            created_at=c.created_at,
        )

    return BriefingResponse(
        recent_components=[serialize(c) for c in recent[:20]],
        needs_review=[serialize(c) for c in needs_review[:20]],
        stale=[serialize(c) for c in stale[:20]],
    )
