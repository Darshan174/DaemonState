from __future__ import annotations

import json
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Component, Model, Relationship, SourceDocument
from app.processing.embedder import BaseEmbedder, build_default_embedder, cosine_similarity


@dataclass
class QueryComponent:
    id: UUID
    model_name: str
    name: str
    value: str
    confidence: float
    authority_weight: float
    status: str
    source_document_id: UUID | None
    source_label: str | None


@dataclass
class QueryResult:
    question: str
    answer: str
    confidence: float
    components: list[QueryComponent]
    sources: list[dict]


class QueryService:
    def __init__(self, session: AsyncSession, embedder: BaseEmbedder | None = None) -> None:
        self.session = session
        self._embedder = embedder or build_default_embedder()

    async def query(self, question: str) -> QueryResult:
        q_embedding = await self._embedder.embed_text(question)

        components = list(await self.session.scalars(
            select(Component)
            .options(
                selectinload(Component.model),
                selectinload(Component.source_document),
                selectinload(Component.outgoing_relationships).selectinload(Relationship.target_component),
                selectinload(Component.incoming_relationships).selectinload(Relationship.source_component),
            )
            .where(Component.status.in_(["active", "needs_review"]))
        ))

        scored = []
        for c in components:
            c_embedding = _parse_embedding(c.embedding)
            sem = cosine_similarity(q_embedding, c_embedding)
            score = sem * 2.0 + c.confidence * 0.5 + c.authority_weight * 0.3
            scored.append((score, c))

        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:5]

        if not top:
            return QueryResult(
                question=question,
                answer=f'No matching context found for "{question}".',
                confidence=0.0,
                components=[],
                sources=[],
            )

        related_ids = set()
        for _, c in top:
            for rel in c.outgoing_relationships:
                related_ids.add(rel.target_component_id)
            for rel in c.incoming_relationships:
                related_ids.add(rel.source_component_id)

        if related_ids:
            related = list(await self.session.scalars(
                select(Component)
                .options(selectinload(Component.model), selectinload(Component.source_document))
                .where(Component.id.in_(related_ids))
            ))
        else:
            related = []

        result_components = []
        sources_seen = set()

        for score, c in top:
            src_label = None
            src_id = None
            if c.source_document:
                src_label = c.source_document.source_type
                src_id = c.source_document.id
                if src_id not in sources_seen:
                    sources_seen.add(src_id)

            result_components.append(QueryComponent(
                id=c.id,
                model_name=c.model.name if c.model else "Unknown",
                name=c.name,
                value=c.value,
                confidence=c.confidence,
                authority_weight=c.authority_weight,
                status=c.status,
                source_document_id=src_id,
                source_label=src_label,
            ))

        for c in related:
            if c.id not in {rc.id for rc in result_components}:
                src_label = None
                src_id = None
                if c.source_document:
                    src_label = c.source_document.source_type
                    src_id = c.source_document.id
                result_components.append(QueryComponent(
                    id=c.id,
                    model_name=c.model.name if c.model else "Unknown",
                    name=c.name,
                    value=c.value,
                    confidence=c.confidence,
                    authority_weight=c.authority_weight,
                    status=c.status,
                    source_document_id=src_id,
                    source_label=src_label,
                ))

        sources = []
        for sid in sources_seen:
            doc = await self.session.get(SourceDocument, sid)
            if doc:
                sources.append({"id": str(doc.id), "type": doc.source_type, "url": doc.source_url})

        best = top[0][1]
        answer = f"{best.name} ({best.model.name if best.model else ''}): {best.value}"
        avg_conf = sum(c.confidence for c, _ in top) / len(top)

        return QueryResult(
            question=question,
            answer=answer,
            confidence=round(avg_conf, 2),
            components=result_components,
            sources=sources,
        )


def _parse_embedding(raw: str | None) -> list[float] | None:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
