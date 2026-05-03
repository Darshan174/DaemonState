from __future__ import annotations

from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db_session
from app.services.query import QueryService

router = APIRouter()


class QueryRequest(BaseModel):
    question: str = Field(min_length=1)
    api_key: str | None = None
    model: str | None = None


class QueryComponentRead(BaseModel):
    id: str
    model_name: str
    name: str
    value: str
    confidence: float
    authority_weight: float
    status: str
    source_document_id: str | None = None
    source_label: str | None = None


class QueryResultRead(BaseModel):
    question: str
    answer: str
    confidence: float
    components: list[QueryComponentRead]
    sources: list[dict]


@router.post("/query", response_model=QueryResultRead)
async def query_context(
    payload: QueryRequest,
    session: AsyncSession = Depends(get_db_session),
) -> QueryResultRead:
    svc = QueryService(session, api_key=payload.api_key, model=payload.model)
    result = await svc.query(payload.question)
    return QueryResultRead(
        question=result.question,
        answer=result.answer,
        confidence=result.confidence,
        components=[
            QueryComponentRead(
                id=str(c.id), model_name=c.model_name, name=c.name,
                value=c.value, confidence=c.confidence,
                authority_weight=c.authority_weight, status=c.status,
                source_document_id=str(c.source_document_id) if c.source_document_id else None,
                source_label=c.source_label,
            )
            for c in result.components
        ],
        sources=result.sources,
    )
