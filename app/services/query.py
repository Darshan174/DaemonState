from __future__ import annotations

import json
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Component, Relationship, SourceDocument
from app.processing.embedder import BaseEmbedder, build_default_embedder, cosine_similarity
from app.services.workspace_scope import (
    filter_components_for_workspace,
    workspace_connector_types,
)


@dataclass
class QueryComponent:
    id: UUID
    model_name: str
    name: str
    value: str
    fact_type: str
    confidence: float
    authority_weight: float
    status: str
    source_document_id: UUID | None
    source_label: str | None
    source_url: str | None
    provenance: str | None
    excerpt: str | None
    score: float | None = None
    rank: int | None = None
    matched: bool = False
    relationship_type: str | None = None
    relationship_evidence: str | None = None
    relationship_origin: str | None = None


@dataclass
class QueryTraceFact:
    rank: int
    component_id: UUID
    model_name: str
    name: str
    value: str
    score: float
    semantic_score: float
    lexical_score: float
    confidence: float
    authority_weight: float
    source_document_id: UUID | None
    source_type: str | None
    source_url: str | None


@dataclass
class QueryTraceRelationship:
    id: UUID
    source_component_id: UUID
    target_component_id: UUID
    relationship_type: str
    confidence: float
    evidence: str | None
    origin: str


@dataclass
class QueryTrace:
    top_k: int
    min_confidence: float
    hybrid: bool
    matched_component_count: int
    returned_component_count: int
    expanded_relationship_count: int
    facts_used: list[QueryTraceFact]
    relationships_used: list[QueryTraceRelationship]


@dataclass
class QueryResult:
    question: str
    schema_version: str
    answer: str
    confidence: float
    components: list[QueryComponent]
    sources: list[dict]
    trace: QueryTrace


ANSWER_PROMPT = """You are a knowledge graph assistant for a startup. Answer the user's question using ONLY the facts provided below. Be direct and specific. If the facts don't contain enough information to answer, say so clearly.

Question: {question}

Relevant facts from the knowledge graph:
{facts}

Instructions:
- Answer the question directly in 1-3 sentences
- Reference specific facts by name when relevant
- If multiple facts are contradictory, note the conflict
- Do NOT make up information beyond what the facts contain
- Do NOT explain what you're doing — just answer
"""


class QueryService:
    def __init__(
        self,
        session: AsyncSession,
        embedder: BaseEmbedder | None = None,
        api_key: str | None = None,
        model: str | None = None,
    ) -> None:
        self.session = session
        self._embedder = embedder or build_default_embedder()
        self._api_key = api_key
        self._model = model

    async def query(
        self,
        question: str,
        workspace_id: str | UUID | None = None,
        top_k: int = 8,
        min_confidence: float = 0.0,
        hybrid: bool = True,
    ) -> QueryResult:
        top_k = max(1, min(int(top_k or 8), 20))
        min_confidence = max(0.0, min(float(min_confidence or 0.0), 1.0))
        q_embedding = await self._embedder.embed_text(question)

        component_stmt = (
            select(Component)
            .options(
                selectinload(Component.model),
                selectinload(Component.source_document),
                selectinload(Component.outgoing_relationships).selectinload(Relationship.target_component),
                selectinload(Component.incoming_relationships).selectinload(Relationship.source_component),
            )
            .where(Component.status.in_(["active", "needs_review"]))
        )
        if min_confidence > 0:
            component_stmt = component_stmt.where(Component.confidence >= min_confidence)

        components = list(await self.session.scalars(component_stmt))
        workspace_scope: tuple[str, set[str]] | None = None
        if workspace_id:
            workspace_scope = await workspace_connector_types(self.session, workspace_id)
            components = filter_components_for_workspace(
                components,
                workspace_scope[0],
                workspace_scope[1],
            )

        scored: list[tuple[float, float, float, Component]] = []
        for c in components:
            c_embedding = _parse_embedding(c.embedding)
            sem = cosine_similarity(q_embedding, c_embedding)
            lexical = _lexical_score(question, c) if hybrid else 0.0
            score = sem * 2.0 + lexical + c.confidence * 0.5 + c.authority_weight * 0.3
            scored.append((score, sem, lexical, c))

        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:top_k]

        if not top:
            empty_trace = QueryTrace(
                top_k=top_k,
                min_confidence=min_confidence,
                hybrid=hybrid,
                matched_component_count=0,
                returned_component_count=0,
                expanded_relationship_count=0,
                facts_used=[],
                relationships_used=[],
            )
            return QueryResult(
                question=question,
                schema_version="query.v1",
                answer=f'No matching context found for "{question}".',
                confidence=0.0,
                components=[],
                sources=[],
                trace=empty_trace,
            )

        related_ids = set()
        relationships_used: list[Relationship] = []
        for _, _, _, c in top:
            for rel in c.outgoing_relationships:
                if rel.status == "rejected":
                    continue
                related_ids.add(rel.target_component_id)
                relationships_used.append(rel)
            for rel in c.incoming_relationships:
                if rel.status == "rejected":
                    continue
                related_ids.add(rel.source_component_id)
                relationships_used.append(rel)

        if related_ids:
            related = list(await self.session.scalars(
                select(Component)
                .options(selectinload(Component.model), selectinload(Component.source_document))
                .where(Component.id.in_(related_ids))
            ))
            if workspace_scope:
                related = filter_components_for_workspace(
                    related,
                    workspace_scope[0],
                    workspace_scope[1],
                )
        else:
            related = []

        result_components = []
        sources_seen: set[UUID] = set()
        source_docs: dict[UUID, SourceDocument] = {}
        top_component_ids: set[UUID] = set()
        relationship_by_component_id: dict[UUID, Relationship] = {}
        for rel in relationships_used:
            relationship_by_component_id.setdefault(rel.source_component_id, rel)
            relationship_by_component_id.setdefault(rel.target_component_id, rel)

        facts_used: list[QueryTraceFact] = []
        for rank, (score, sem, lexical, c) in enumerate(top, start=1):
            top_component_ids.add(c.id)
            src_label = None
            src_id = None
            source_url = None
            if c.source_document:
                src_label = c.source_document.source_type
                src_id = c.source_document.id
                source_url = c.source_document.source_url
                if src_id not in sources_seen:
                    sources_seen.add(src_id)
                    source_docs[src_id] = c.source_document

            model_name = c.model.name if c.model else "Unknown"

            result_components.append(QueryComponent(
                id=c.id,
                model_name=model_name,
                name=c.name,
                value=c.value,
                fact_type=c.fact_type,
                confidence=c.confidence,
                authority_weight=c.authority_weight,
                status=c.status,
                source_document_id=src_id,
                source_label=src_label,
                source_url=source_url,
                provenance=c.provenance,
                excerpt=c.excerpt,
                score=round(score, 4),
                rank=rank,
                matched=True,
            ))
            facts_used.append(QueryTraceFact(
                rank=rank,
                component_id=c.id,
                model_name=model_name,
                name=c.name,
                value=c.value,
                score=round(score, 4),
                semantic_score=round(sem, 4),
                lexical_score=round(lexical, 4),
                confidence=c.confidence,
                authority_weight=c.authority_weight,
                source_document_id=src_id,
                source_type=src_label,
                source_url=source_url,
            ))

        result_component_ids = {rc.id for rc in result_components}
        for c in related:
            if c.id not in result_component_ids:
                src_label = None
                src_id = None
                source_url = None
                if c.source_document:
                    src_label = c.source_document.source_type
                    src_id = c.source_document.id
                    source_url = c.source_document.source_url
                    if src_id not in sources_seen:
                        sources_seen.add(src_id)
                        source_docs[src_id] = c.source_document
                rel = relationship_by_component_id.get(c.id)
                result_components.append(QueryComponent(
                    id=c.id,
                    model_name=c.model.name if c.model else "Unknown",
                    name=c.name,
                    value=c.value,
                    fact_type=c.fact_type,
                    confidence=c.confidence,
                    authority_weight=c.authority_weight,
                    status=c.status,
                    source_document_id=src_id,
                    source_label=src_label,
                    source_url=source_url,
                    provenance=c.provenance,
                    excerpt=c.excerpt,
                    matched=False,
                    relationship_type=rel.relationship_type if rel else None,
                    relationship_evidence=rel.evidence if rel else None,
                    relationship_origin=rel.origin if rel else None,
                ))
                result_component_ids.add(c.id)

        sources = []
        for sid in sources_seen:
            doc = source_docs.get(sid) or await self.session.get(SourceDocument, sid)
            if doc:
                sources.append({
                    "id": str(doc.id),
                    "type": doc.source_type,
                    "url": doc.source_url,
                    "external_id": doc.external_id,
                    "author": doc.author,
                })

        avg_conf = sum(c.confidence for _, _, _, c in top) / len(top)

        # Try LLM-based answer synthesis
        answer = await self._generate_answer(question, [(score, c) for score, _, _, c in top])

        trace_relationships = [
            QueryTraceRelationship(
                id=rel.id,
                source_component_id=rel.source_component_id,
                target_component_id=rel.target_component_id,
                relationship_type=rel.relationship_type,
                confidence=rel.confidence,
                evidence=rel.evidence,
                origin=rel.origin,
            )
            for rel in _dedupe_relationships(relationships_used)
        ]
        trace = QueryTrace(
            top_k=top_k,
            min_confidence=min_confidence,
            hybrid=hybrid,
            matched_component_count=len(top_component_ids),
            returned_component_count=len(result_components),
            expanded_relationship_count=len(trace_relationships),
            facts_used=facts_used,
            relationships_used=trace_relationships,
        )

        return QueryResult(
            question=question,
            schema_version="query.v1",
            answer=answer,
            confidence=round(avg_conf, 2),
            components=result_components,
            sources=sources,
            trace=trace,
        )

    async def _generate_answer(self, question: str, top: list[tuple[float, Component]]) -> str:
        """Generate a coherent answer using LLM if API key available, else summarise top facts."""
        facts_text = "\n".join(
            f"- [{c.model.name if c.model else 'Unknown'}] {c.name}: {c.value}"
            for _, c in top[:6]
        )

        if self._api_key and self._model:
            model = self._model
            try:
                from litellm import acompletion
                prompt = ANSWER_PROMPT.format(question=question, facts=facts_text)
                response = await acompletion(
                    model=model,
                    api_key=self._api_key,
                    messages=[
                        {"role": "system", "content": "You are a startup knowledge graph assistant. Answer questions using only the provided facts. Be concise and direct."},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.1,
                    max_tokens=300,
                )
                return response.choices[0].message.content.strip()
            except Exception as e:
                err = str(e)
                if "RateLimitError" in err or "quota" in err.lower() or "exceeded" in err.lower() or "billing" in err.lower():
                    return (
                        f"Your OpenAI account has exceeded its quota or has no billing set up. "
                        f"Either add credits at platform.openai.com/account/billing, "
                        f"or open Configure AI and switch to Anthropic (claude-3-5-haiku-20241022 is fast and cheap).\n\n"
                        f"Top matching facts:\n{facts_text}"
                    )
                if "NotFoundError" in err or "does not exist" in err or "invalid_model" in err.lower():
                    return (
                        f"Model \"{model}\" is not available on your API key. "
                        f"Open Configure AI and pick a different model — "
                        f"try gpt-4o-mini (OpenAI) or claude-3-5-haiku-20241022 (Anthropic).\n\n"
                        f"Top matching facts:\n{facts_text}"
                    )
                if "AuthenticationError" in err or "Unauthorized" in err or "invalid_api_key" in err.lower():
                    return (
                        f"Your API key was rejected. Open Configure AI and check the key is correct.\n\n"
                        f"Top matching facts:\n{facts_text}"
                    )
                return f"AI error: {err}\n\nTop matching facts:\n{facts_text}"

        return _fallback_answer_from_facts(question, top)



def _parse_embedding(raw: str | None) -> list[float] | None:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


def _fallback_answer_from_facts(question: str, top: list[tuple[float, Component]]) -> str:
    facts = []
    for _, component in top[:3]:
        model_name = component.model.name if component.model else "Fact"
        value = _compact_text(component.value, 180)
        facts.append(f"{model_name} - {component.name}: {value}")
    if not facts:
        return f'No matching context found for "{question}".'
    return (
        f'No AI answer model is configured, so this answer is a source-backed fact summary for "{question}": '
        + " | ".join(facts)
    )


def _compact_text(value: str, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return f"{text[:limit - 3].rstrip()}..."


def _tokenize(value: str) -> set[str]:
    import re
    return {token for token in re.findall(r"[a-z0-9][a-z0-9_-]{2,}", value.lower())}


def _lexical_score(question: str, component: Component) -> float:
    query_tokens = _tokenize(question)
    if not query_tokens:
        return 0.0
    haystack = " ".join([
        component.name or "",
        component.value or "",
        component.fact_type or "",
        component.status or "",
        component.temporal or "",
        component.model.name if component.model else "",
        component.source_document.source_type if component.source_document else "",
    ])
    overlap = query_tokens & _tokenize(haystack)
    return min(len(overlap) * 0.35, 1.4)


def _dedupe_relationships(relationships: list[Relationship]) -> list[Relationship]:
    seen: set[UUID] = set()
    deduped: list[Relationship] = []
    for rel in relationships:
        if rel.id in seen:
            continue
        seen.add(rel.id)
        deduped.append(rel)
    return deduped
