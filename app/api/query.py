from __future__ import annotations

from uuid import UUID

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
    workspace_id: UUID | None = None
    top_k: int = Field(default=8, ge=1, le=20)
    min_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    hybrid: bool = True


class QueryComponentRead(BaseModel):
    id: str
    model_name: str
    name: str
    value: str
    fact_type: str
    confidence: float
    authority_weight: float
    status: str
    source_document_id: str | None = None
    source_label: str | None = None
    source_url: str | None = None
    provenance: str | None = None
    excerpt: str | None = None
    score: float | None = None
    rank: int | None = None
    matched: bool = False
    relationship_type: str | None = None
    relationship_evidence: str | None = None
    relationship_origin: str | None = None


class QueryTraceFactRead(BaseModel):
    rank: int
    component_id: str
    model_name: str
    name: str
    value: str
    score: float
    semantic_score: float
    lexical_score: float
    confidence: float
    authority_weight: float
    source_document_id: str | None = None
    source_type: str | None = None
    source_url: str | None = None


class QueryTraceRelationshipRead(BaseModel):
    id: str
    source_component_id: str
    target_component_id: str
    relationship_type: str
    confidence: float
    evidence: str | None = None
    origin: str


class QueryTraceRead(BaseModel):
    top_k: int
    min_confidence: float
    hybrid: bool
    matched_component_count: int
    returned_component_count: int
    expanded_relationship_count: int
    facts_used: list[QueryTraceFactRead]
    relationships_used: list[QueryTraceRelationshipRead]


class QueryResultRead(BaseModel):
    question: str
    schema_version: str
    answer: str
    confidence: float
    components: list[QueryComponentRead]
    sources: list[dict]
    trace: QueryTraceRead


@router.post("/query", response_model=QueryResultRead)
async def query_context(
    payload: QueryRequest,
    session: AsyncSession = Depends(get_db_session),
) -> QueryResultRead:
    svc = QueryService(session, api_key=payload.api_key, model=payload.model)
    result = await svc.query(
        payload.question,
        workspace_id=str(payload.workspace_id) if payload.workspace_id else None,
        top_k=payload.top_k,
        min_confidence=payload.min_confidence,
        hybrid=payload.hybrid,
    )
    return QueryResultRead(
        question=result.question,
        schema_version=result.schema_version,
        answer=result.answer,
        confidence=result.confidence,
        components=[
            QueryComponentRead(
                id=str(c.id), model_name=c.model_name, name=c.name,
                value=c.value, fact_type=c.fact_type, confidence=c.confidence,
                authority_weight=c.authority_weight, status=c.status,
                source_document_id=str(c.source_document_id) if c.source_document_id else None,
                source_label=c.source_label,
                source_url=c.source_url,
                provenance=c.provenance,
                excerpt=c.excerpt,
                score=c.score,
                rank=c.rank,
                matched=c.matched,
                relationship_type=c.relationship_type,
                relationship_evidence=c.relationship_evidence,
                relationship_origin=c.relationship_origin,
            )
            for c in result.components
        ],
        sources=result.sources,
        trace=QueryTraceRead(
            top_k=result.trace.top_k,
            min_confidence=result.trace.min_confidence,
            hybrid=result.trace.hybrid,
            matched_component_count=result.trace.matched_component_count,
            returned_component_count=result.trace.returned_component_count,
            expanded_relationship_count=result.trace.expanded_relationship_count,
            facts_used=[
                QueryTraceFactRead(
                    rank=f.rank,
                    component_id=str(f.component_id),
                    model_name=f.model_name,
                    name=f.name,
                    value=f.value,
                    score=f.score,
                    semantic_score=f.semantic_score,
                    lexical_score=f.lexical_score,
                    confidence=f.confidence,
                    authority_weight=f.authority_weight,
                    source_document_id=str(f.source_document_id) if f.source_document_id else None,
                    source_type=f.source_type,
                    source_url=f.source_url,
                )
                for f in result.trace.facts_used
            ],
            relationships_used=[
                QueryTraceRelationshipRead(
                    id=str(r.id),
                    source_component_id=str(r.source_component_id),
                    target_component_id=str(r.target_component_id),
                    relationship_type=r.relationship_type,
                    confidence=r.confidence,
                    evidence=r.evidence,
                    origin=r.origin,
                )
                for r in result.trace.relationships_used
            ],
        ),
    )
