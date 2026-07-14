from __future__ import annotations

import json
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Component, Relationship, RetrievalEvent, SourceDocument
from app.processing.embedder import BaseEmbedder, build_default_embedder, cosine_similarity
from app.services.reranker import RerankFeatures, score_component
from app.services.workspace_scope import (
    filter_components_for_workspace,
    normalize_workspace_id,
    workspace_connector_types,
)
from app.services.vector_search import (
    pgvector_candidate_limit,
    search_component_text,
    search_component_vectors,
)


@dataclass
class QueryComponent:
    id: UUID
    entity_id: UUID | None
    identity_key: str | None
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
    entity_id: UUID | None
    identity_key: str | None
    model_name: str
    name: str
    value: str
    score: float
    semantic_score: float
    lexical_score: float
    rerank_score: float
    exact_match_score: float
    token_coverage: float
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
    retrieval_strategy: str
    ranking_strategy: str
    calibration_strategy: str
    vector_candidate_count: int
    text_candidate_count: int
    vector_prefilter_limit: int | None
    text_prefilter_limit: int | None
    top_k: int
    min_confidence: float
    hybrid: bool
    candidate_component_count: int
    scoped_component_count: int
    scored_component_count: int
    entity_group_count: int
    entity_duplicate_count: int
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
        workspace_uuid: UUID | None = None
        vector_prefilter_limit = pgvector_candidate_limit(top_k)
        vector_search = await search_component_vectors(
            self.session,
            q_embedding,
            workspace_id=_event_workspace_id(workspace_id),
            min_confidence=min_confidence,
            limit=vector_prefilter_limit,
        )
        text_search = await search_component_text(
            self.session,
            question,
            workspace_id=_event_workspace_id(workspace_id),
            min_confidence=min_confidence,
            limit=vector_prefilter_limit,
        ) if hybrid else None
        vector_ids = [match.component_id for match in vector_search.matches]
        text_ids = [match.component_id for match in text_search.matches] if text_search else []
        candidate_ids = _ordered_unique_ids([*vector_ids, *text_ids])
        retrieval_strategy = _retrieval_strategy(
            vector_enabled=vector_search.enabled,
            vector_count=len(vector_ids),
            text_enabled=bool(text_search and text_search.enabled),
            text_count=len(text_ids),
        )
        vector_scores_by_id = {
            match.component_id: match.semantic_score
            for match in vector_search.matches
        }
        text_scores_by_id = {
            match.component_id: match.lexical_score
            for match in (text_search.matches if text_search else [])
        }

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
        if candidate_ids:
            component_stmt = component_stmt.where(Component.id.in_(candidate_ids))

        workspace_scope: tuple[str, set[str]] | None = None
        if workspace_id:
            _, workspace_uuid = normalize_workspace_id(workspace_id)
            component_stmt = component_stmt.where(
                or_(
                    Component.workspace_id == workspace_uuid,
                    Component.workspace_id.is_(None),
                )
            )

        components = list(await self.session.scalars(component_stmt))
        candidate_component_count = len(components)
        if workspace_id:
            workspace_scope = await workspace_connector_types(self.session, workspace_id)
            components = filter_components_for_workspace(
                components,
                workspace_scope[0],
                workspace_scope[1],
            )
        scoped_component_count = len(components)

        scored: list[tuple[float, RerankFeatures, Component]] = []
        for c in components:
            c_embedding = _parse_embedding(c.embedding)
            sem = vector_scores_by_id.get(c.id)
            if sem is None:
                sem = cosine_similarity(q_embedding, c_embedding)
            lexical = text_scores_by_id.get(c.id)
            if lexical is None:
                lexical = _lexical_score(question, c) if hybrid else 0.0
            features = score_component(
                question,
                c,
                semantic_score=sem,
                lexical_score=lexical,
            )
            scored.append((features.final_score, features, c))

        scored.sort(key=lambda x: x[0], reverse=True)
        entity_group_count = len({
            _component_entity_group_key(c)
            for _, _, c in scored
        })
        entity_duplicate_count = max(0, len(scored) - entity_group_count)
        top = _diversify_scored_by_entity(scored, top_k)

        if not top:
            empty_trace = QueryTrace(
                retrieval_strategy=retrieval_strategy,
                ranking_strategy="deterministic_rerank_v2",
                calibration_strategy="logistic_v1",
                vector_candidate_count=len(vector_ids),
                text_candidate_count=len(text_ids),
                vector_prefilter_limit=(
                    vector_prefilter_limit if vector_search.enabled else None
                ),
                text_prefilter_limit=(
                    vector_prefilter_limit if text_search and text_search.enabled else None
                ),
                top_k=top_k,
                min_confidence=min_confidence,
                hybrid=hybrid,
                candidate_component_count=candidate_component_count,
                scoped_component_count=scoped_component_count,
                scored_component_count=len(scored),
                entity_group_count=entity_group_count,
                entity_duplicate_count=entity_duplicate_count,
                matched_component_count=0,
                returned_component_count=0,
                expanded_relationship_count=0,
                facts_used=[],
                relationships_used=[],
            )
            result = QueryResult(
                question=question,
                schema_version="query.v1",
                answer=f'No matching context found for "{question}".',
                confidence=0.0,
                components=[],
                sources=[],
                trace=empty_trace,
            )
            await self._record_retrieval_event(result, workspace_id)
            return result

        related_ids = set()
        relationships_used: list[Relationship] = []
        for _, _, c in top:
            for rel in c.outgoing_relationships:
                if not _relationship_is_safe_for_expansion(rel):
                    continue
                related_ids.add(rel.target_component_id)
                relationships_used.append(rel)
            for rel in c.incoming_relationships:
                if not _relationship_is_safe_for_expansion(rel):
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

        visible_component_ids = {
            component.id for _, _, component in top
        } | {component.id for component in related}
        relationships_used = [
            relationship for relationship in relationships_used
            if relationship.source_component_id in visible_component_ids
            and relationship.target_component_id in visible_component_ids
        ]

        result_components = []
        sources_seen: set[UUID] = set()
        source_docs: dict[UUID, SourceDocument] = {}
        top_component_ids: set[UUID] = set()
        relationship_by_component_id: dict[UUID, Relationship] = {}
        for rel in relationships_used:
            relationship_by_component_id.setdefault(rel.source_component_id, rel)
            relationship_by_component_id.setdefault(rel.target_component_id, rel)

        facts_used: list[QueryTraceFact] = []
        for rank, (score, features, c) in enumerate(top, start=1):
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
                entity_id=c.entity_id,
                identity_key=c.identity_key,
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
                entity_id=c.entity_id,
                identity_key=c.identity_key,
                model_name=model_name,
                name=c.name,
                value=c.value,
                score=round(score, 4),
                semantic_score=round(features.semantic_score, 4),
                lexical_score=round(features.lexical_score, 4),
                rerank_score=round(features.raw_score, 4),
                exact_match_score=round(features.exact_match_score, 4),
                token_coverage=round(features.token_coverage, 4),
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
                    entity_id=c.entity_id,
                    identity_key=c.identity_key,
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

        avg_conf = sum(c.confidence for _, _, c in top) / len(top)

        # Try LLM-based answer synthesis
        answer = await self._generate_answer(question, [(score, c) for score, _, c in top])

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
            retrieval_strategy=retrieval_strategy,
            ranking_strategy="deterministic_rerank_v2",
            calibration_strategy="logistic_v1",
            vector_candidate_count=len(vector_ids),
            text_candidate_count=len(text_ids),
            vector_prefilter_limit=(
                vector_prefilter_limit if vector_search.enabled else None
            ),
            text_prefilter_limit=(
                vector_prefilter_limit if text_search and text_search.enabled else None
            ),
            top_k=top_k,
            min_confidence=min_confidence,
            hybrid=hybrid,
            candidate_component_count=candidate_component_count,
            scoped_component_count=scoped_component_count,
            scored_component_count=len(scored),
            entity_group_count=entity_group_count,
            entity_duplicate_count=entity_duplicate_count,
            matched_component_count=len(top_component_ids),
            returned_component_count=len(result_components),
            expanded_relationship_count=len(trace_relationships),
            facts_used=facts_used,
            relationships_used=trace_relationships,
        )

        result = QueryResult(
            question=question,
            schema_version="query.v1",
            answer=answer,
            confidence=round(avg_conf, 2),
            components=result_components,
            sources=sources,
            trace=trace,
        )
        await self._record_retrieval_event(result, workspace_id)
        return result

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

    async def _record_retrieval_event(
        self,
        result: QueryResult,
        workspace_id: str | UUID | None,
    ) -> None:
        self.session.add(RetrievalEvent(
            workspace_id=_event_workspace_id(workspace_id),
            question=result.question,
            answer=result.answer,
            schema_version=result.schema_version,
            confidence=result.confidence,
            top_k=result.trace.top_k,
            min_confidence=result.trace.min_confidence,
            hybrid=result.trace.hybrid,
            component_count=len(result.components),
            source_count=len(result.sources),
            trace_json=json.dumps(_query_trace_to_dict(result.trace), sort_keys=True),
        ))
        await self.session.flush()



def _parse_embedding(raw: str | None) -> list[float] | None:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


def _ordered_unique_ids(values: list[UUID]) -> list[UUID]:
    seen: set[UUID] = set()
    ordered: list[UUID] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def _retrieval_strategy(
    *,
    vector_enabled: bool,
    vector_count: int,
    text_enabled: bool,
    text_count: int,
) -> str:
    if vector_count and text_count:
        return "postgres_hybrid"
    if vector_count:
        return "postgres_vector"
    if text_count:
        return "postgres_text"
    if vector_enabled or text_enabled:
        return "python_scan"
    return "python_scan"


def _event_workspace_id(workspace_id: str | UUID | None) -> UUID | None:
    if workspace_id in (None, ""):
        return None
    try:
        return workspace_id if isinstance(workspace_id, UUID) else UUID(str(workspace_id))
    except (TypeError, ValueError):
        return None


def _query_trace_to_dict(trace: QueryTrace) -> dict:
    return {
        "retrieval_strategy": trace.retrieval_strategy,
        "ranking_strategy": trace.ranking_strategy,
        "calibration_strategy": trace.calibration_strategy,
        "vector_candidate_count": trace.vector_candidate_count,
        "text_candidate_count": trace.text_candidate_count,
        "vector_prefilter_limit": trace.vector_prefilter_limit,
        "text_prefilter_limit": trace.text_prefilter_limit,
        "top_k": trace.top_k,
        "min_confidence": trace.min_confidence,
        "hybrid": trace.hybrid,
        "candidate_component_count": trace.candidate_component_count,
        "scoped_component_count": trace.scoped_component_count,
        "scored_component_count": trace.scored_component_count,
        "entity_group_count": trace.entity_group_count,
        "entity_duplicate_count": trace.entity_duplicate_count,
        "matched_component_count": trace.matched_component_count,
        "returned_component_count": trace.returned_component_count,
        "expanded_relationship_count": trace.expanded_relationship_count,
        "facts_used": [
            {
                "rank": fact.rank,
                "component_id": str(fact.component_id),
                "entity_id": str(fact.entity_id) if fact.entity_id else None,
                "identity_key": fact.identity_key,
                "model_name": fact.model_name,
                "name": fact.name,
                "value": fact.value,
                "score": fact.score,
                "semantic_score": fact.semantic_score,
                "lexical_score": fact.lexical_score,
                "rerank_score": fact.rerank_score,
                "exact_match_score": fact.exact_match_score,
                "token_coverage": fact.token_coverage,
                "confidence": fact.confidence,
                "authority_weight": fact.authority_weight,
                "source_document_id": (
                    str(fact.source_document_id) if fact.source_document_id else None
                ),
                "source_type": fact.source_type,
                "source_url": fact.source_url,
            }
            for fact in trace.facts_used
        ],
        "relationships_used": [
            {
                "id": str(rel.id),
                "source_component_id": str(rel.source_component_id),
                "target_component_id": str(rel.target_component_id),
                "relationship_type": rel.relationship_type,
                "confidence": rel.confidence,
                "evidence": rel.evidence,
                "origin": rel.origin,
            }
            for rel in trace.relationships_used
        ],
    }


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


def _diversify_scored_by_entity(
    scored: list[tuple[float, RerankFeatures, Component]],
    limit: int,
) -> list[tuple[float, RerankFeatures, Component]]:
    selected: list[tuple[float, RerankFeatures, Component]] = []
    deferred: list[tuple[float, RerankFeatures, Component]] = []
    seen_groups: set[tuple[str, str]] = set()

    for item in scored:
        group_key = _component_entity_group_key(item[2])
        if group_key in seen_groups:
            deferred.append(item)
            continue
        seen_groups.add(group_key)
        selected.append(item)
        if len(selected) >= limit:
            return selected

    for item in deferred:
        selected.append(item)
        if len(selected) >= limit:
            break
    return selected


def _component_entity_group_key(component: Component) -> tuple[str, str]:
    if component.entity_id:
        return ("entity", str(component.entity_id))
    if component.identity_key:
        return ("identity", component.identity_key)
    return ("component", str(component.id))


def _dedupe_relationships(relationships: list[Relationship]) -> list[Relationship]:
    seen: set[UUID] = set()
    deduped: list[Relationship] = []
    for rel in relationships:
        if rel.id in seen:
            continue
        seen.add(rel.id)
        deduped.append(rel)
    return deduped


def _relationship_is_safe_for_expansion(relationship: Relationship) -> bool:
    return bool(
        relationship.status == "active"
        and relationship.origin in {"deterministic", "extracted", "human_verified"}
        and str(relationship.evidence or "").strip()
    )
