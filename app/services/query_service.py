from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from itertools import chain
from typing import Iterable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.models.knowledge import Component, KnowledgeModel, Relationship, RelationshipType
from app.models.source import SourceDocument
from app.models.user import Workspace
from app.processing.embedder import BaseEmbedder, build_default_embedder, cosine_similarity
from app.processing.reranker import (
    BaseReranker,
    RerankCandidate,
    build_default_reranker,
)
from app.services.truth_visibility import (
    is_component_visible_as_of,
    is_component_visible_in_current_truth,
)
from app.schemas.query import (
    FreshnessStatus,
    QueryComponentRead,
    QueryFilters,
    QueryResult,
    QuerySourceRead,
)

STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "do",
    "for",
    "from",
    "how",
    "in",
    "is",
    "it",
    "of",
    "on",
    "our",
    "the",
    "to",
    "what",
    "when",
    "where",
    "which",
    "who",
    "why",
    "with",
}
RELATIONSHIP_HINT_TOKENS = {
    "affect",
    "because",
    "blocked",
    "blocker",
    "delay",
    "delayed",
    "depends",
    "dependency",
    "impact",
    "impacts",
    "related",
    "relationship",
    "why",
}
RELATIONSHIP_TYPE_WEIGHT = {
    RelationshipType.BLOCKED_BY: 2.5,
    RelationshipType.DEPENDS_ON: 2.0,
    RelationshipType.CONTRADICTS: 1.75,
    RelationshipType.ENABLES: 1.25,
    RelationshipType.SUPERSEDES: 1.0,
    RelationshipType.RELATED_TO: 0.75,
}


class QueryServiceError(Exception):
    """Base query service error."""


class QueryResourceNotFoundError(QueryServiceError):
    """Raised when a query references a missing workspace."""


@dataclass(slots=True)
class ScoredComponent:
    model: KnowledgeModel
    component: Component
    lexical_score: float
    semantic_score: float
    authority_score: float
    score: float
    blended_confidence: float


class QueryService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        embedder: BaseEmbedder | None = None,
        reranker: BaseReranker | None = None,
    ) -> None:
        self.session = session
        self._embedder = embedder or build_default_embedder()
        self._reranker = reranker or build_default_reranker()

    async def query(
        self,
        question: str,
        workspace_id: UUID,
        filters: QueryFilters | None = None,
    ) -> QueryResult:
        filters = filters or QueryFilters()
        workspace = await self.session.scalar(
            select(Workspace).where(Workspace.id == workspace_id).limit(1)
        )
        if workspace is None:
            raise QueryResourceNotFoundError("Workspace not found")

        models = await self._load_models(workspace_id, filters)
        question_embedding = await self._embedder.embed_text(question)
        scored = await self._score_components(question, question_embedding, models, filters)

        if not scored:
            return QueryResult(
                question=question,
                answer=(
                    f'I could not find matching structured context for "{question}" '
                    "in this workspace."
                ),
                confidence=0.0,
                freshness=FreshnessStatus.CURRENT,
                components=[],
                sources=[],
                answered_at=self._answered_at(),
            )

        selected = self._select_components(scored)
        components = [self._serialize_component(item) for item in selected]
        sources = self._serialize_sources(selected)
        answer = self._build_answer(question, selected, filters)
        confidence = round(
            sum(item.blended_confidence for item in selected) / len(selected),
            2,
        )
        freshness = self._calculate_freshness(
            (item.component for item in selected),
            as_of=filters.as_of,
        )

        return QueryResult(
            question=question,
            answer=answer,
            confidence=confidence,
            freshness=freshness,
            components=components,
            sources=sources,
            answered_at=self._answered_at(),
        )

    async def _load_models(
        self,
        workspace_id: UUID,
        filters: QueryFilters,
    ) -> list[KnowledgeModel]:
        stmt = (
            select(KnowledgeModel)
            .options(
                selectinload(KnowledgeModel.components).selectinload(Component.source_documents),
                selectinload(KnowledgeModel.components).selectinload(Component.review_item),
                selectinload(KnowledgeModel.components)
                .selectinload(Component.outgoing_relationships)
                .selectinload(Relationship.target_component),
                selectinload(KnowledgeModel.components)
                .selectinload(Component.incoming_relationships)
                .selectinload(Relationship.source_component),
            )
            .where(KnowledgeModel.workspace_id == workspace_id)
            .order_by(KnowledgeModel.name.asc())
        )

        if filters.model_names:
            lowered = {name.lower() for name in filters.model_names}
            result = await self.session.scalars(stmt)
            return [model for model in result if model.name.lower() in lowered]

        result = await self.session.scalars(stmt)
        return list(result)

    async def _score_components(
        self,
        question: str,
        question_embedding: list[float],
        models: Iterable[KnowledgeModel],
        filters: QueryFilters,
    ) -> list[ScoredComponent]:
        question_text = question.lower()
        question_tokens = self._tokenize(question)
        current_truth_focus = self._question_prefers_current_truth(question_tokens)
        scored: list[ScoredComponent] = []

        for model in models:
            model_tokens = self._tokenize(model.name)
            model_score = 0.0
            if model.name.lower() in question_text:
                model_score += 2.5
            model_score += 1.25 * len(model_tokens & question_tokens)

            for component in model.components:
                if not self._is_component_visible(component, filters):
                    continue
                if component.confidence < filters.min_confidence:
                    continue
                if not self._within_age_limit(component, filters.max_age_days, as_of=filters.as_of):
                    continue

                lexical_score = self._lexical_component_score(
                    question_text=question_text,
                    question_tokens=question_tokens,
                    model_score=model_score,
                    component=component,
                )
                semantic_score = self._semantic_component_score(
                    question_embedding=question_embedding,
                    component=component,
                )
                authority_score = component.authority_weight or 0.5
                source_support_score = self._source_support_score(component)
                review_adjustment = self._review_score_adjustment(
                    component,
                    current_truth_focus=current_truth_focus,
                )
                freshness_adjustment = self._freshness_score_adjustment(
                    component,
                    current_truth_focus=current_truth_focus,
                    as_of=filters.as_of,
                )
                current_truth_bonus = (
                    settings.retrieval_current_truth_bonus
                    if component.valid_to is None
                    else -settings.retrieval_current_truth_bonus
                )

                if lexical_score <= 0 and semantic_score < settings.retrieval_min_semantic_score:
                    continue

                score = (
                    lexical_score
                    + (settings.retrieval_semantic_weight * semantic_score)
                    + (settings.retrieval_authority_weight * authority_score)
                    + source_support_score
                    + review_adjustment
                    + freshness_adjustment
                    + current_truth_bonus
                )
                query_match_confidence = min(
                    max(min(lexical_score / 10.0, 1.0), semantic_score),
                    1.0,
                )
                blended_confidence = round(
                    (0.55 * component.confidence)
                    + (0.25 * query_match_confidence)
                    + (0.20 * authority_score),
                    2,
                )
                scored.append(
                    ScoredComponent(
                        model=model,
                        component=component,
                        lexical_score=lexical_score,
                        semantic_score=semantic_score,
                        authority_score=authority_score,
                        score=score,
                        blended_confidence=min(blended_confidence, 1.0),
                    )
                )

        if not scored:
            return []

        reranked = await self._rerank(question, scored)
        return reranked

    async def _rerank(
        self,
        question: str,
        scored: list[ScoredComponent],
    ) -> list[ScoredComponent]:
        candidates = [
            RerankCandidate(
                candidate_id=str(item.component.id),
                base_score=item.score,
                confidence=item.blended_confidence,
                authority_weight=item.authority_score,
                review_status=item.component.review_status,
                last_verified_at=item.component.last_verified_at,
                source_count=len(self._active_source_documents(item.component)),
                is_current=item.component.valid_to is None,
                is_stale=item.component.is_stale,
            )
            for item in scored
        ]
        ordered = await self._reranker.rerank(question, candidates)
        by_id = {str(item.component.id): item for item in scored}
        return [by_id[candidate.candidate_id] for candidate in ordered]

    def _lexical_component_score(
        self,
        *,
        question_text: str,
        question_tokens: set[str],
        model_score: float,
        component: Component,
    ) -> float:
        component_tokens = self._tokenize(component.name)
        value_tokens = self._tokenize(component.value)
        authority_tokens = self._tokenize(component.authority_source or "")

        score = model_score
        if component.name.lower() in question_text:
            score += 5.0
        score += 2.5 * len(component_tokens & question_tokens)
        score += 1.0 * min(3, len(value_tokens & question_tokens))
        score += 0.5 * min(2, len(authority_tokens & question_tokens))
        return score

    def _semantic_component_score(
        self,
        *,
        question_embedding: list[float],
        component: Component,
    ) -> float:
        similarity = cosine_similarity(question_embedding, component.embedding)
        return max(0.0, similarity)

    @staticmethod
    def _active_source_documents(component: Component) -> list[SourceDocument]:
        return [
            document
            for document in component.source_documents
            if document.deleted_at is None
        ]

    @classmethod
    def _source_support_score(cls, component: Component) -> float:
        return min(len(cls._active_source_documents(component)), 3) * settings.retrieval_source_support_bonus

    @staticmethod
    def _question_prefers_current_truth(question_tokens: set[str]) -> bool:
        return bool(
            question_tokens & {"active", "current", "latest", "now", "today"}
        )

    @staticmethod
    def _review_score_adjustment(
        component: Component,
        *,
        current_truth_focus: bool,
    ) -> float:
        if component.review_status == "approved":
            return settings.retrieval_approved_bonus
        if component.review_status == "needs_review":
            penalty = settings.retrieval_needs_review_penalty
            if current_truth_focus:
                penalty += 0.1
            return -penalty
        return 0.0

    @staticmethod
    def _freshness_score_adjustment(
        component: Component,
        *,
        current_truth_focus: bool,
        as_of: datetime | None = None,
    ) -> float:
        if component.last_verified_at is None:
            return 0.0
        reference = as_of or datetime.now(UTC)
        age_days = max((reference - component.last_verified_at).days, 0)
        if age_days <= 7:
            return 0.08 if current_truth_focus else 0.03
        if age_days <= 30:
            return 0.0
        return -settings.retrieval_stale_penalty

    def _is_component_visible(
        self,
        component: Component,
        filters: QueryFilters,
    ) -> bool:
        if filters.as_of is None:
            return is_component_visible_in_current_truth(component)
        return is_component_visible_as_of(component, as_of=filters.as_of)

    def _is_relationship_visible(
        self,
        relationship: Relationship,
        filters: QueryFilters,
    ) -> bool:
        if filters.as_of is None:
            return relationship.valid_to is None
        if relationship.valid_from > filters.as_of:
            return False
        if relationship.valid_to is not None and relationship.valid_to <= filters.as_of:
            return False
        return True

    def _select_components(self, scored: list[ScoredComponent]) -> list[ScoredComponent]:
        best = scored[0]
        selected = [best]
        seen_signatures = {self._component_signature(best.component)}
        minimum_score = max(best.score * 0.72, best.score - 1.5)

        for candidate in scored[1:]:
            if len(selected) >= 3:
                break
            if candidate.score < minimum_score:
                continue
            signature = self._component_signature(candidate.component)
            if signature in seen_signatures:
                continue
            selected.append(candidate)
            seen_signatures.add(signature)

        return selected

    def _serialize_component(self, scored: ScoredComponent) -> QueryComponentRead:
        return QueryComponentRead(
            id=scored.component.id,
            model=scored.model.name,
            name=scored.component.name,
            value=scored.component.value,
            confidence=scored.component.confidence,
            authority_source=scored.component.authority_source,
            authority_weight=scored.component.authority_weight,
            last_verified_at=scored.component.last_verified_at,
            valid_from=scored.component.valid_from,
            valid_to=scored.component.valid_to,
            superseded_by=scored.component.superseded_by,
            review_status=scored.component.review_status,
            review_summary=scored.component.review_summary,
            review_item_id=scored.component.review_item_id,
            temporal_state=scored.component.temporal_state,
            source_documents=[
                {
                    "id": document.id,
                    "label": document.label,
                    "connector_type": document.connector_type.value,
                }
                for document in self._active_source_documents(scored.component)
            ],
        )

    def _serialize_sources(self, scored: Iterable[ScoredComponent]) -> list[QuerySourceRead]:
        seen: set[UUID] = set()
        serialized: list[QuerySourceRead] = []
        documents: list[SourceDocument] = []

        for item in scored:
            documents.extend(self._active_source_documents(item.component))

        documents.sort(
            key=lambda doc: doc.created_at_source or doc.ingested_at,
            reverse=True,
        )

        for doc in documents:
            if doc.id in seen:
                continue
            seen.add(doc.id)
            serialized.append(
                QuerySourceRead(
                    type=doc.connector_type.value,
                    author=doc.author,
                    date=doc.created_at_source.date().isoformat()
                    if doc.created_at_source is not None
                    else None,
                    url=doc.source_url,
                    source_document_id=doc.id,
                )
            )
            if len(serialized) >= 5:
                break

        return serialized

    def _build_answer(
        self,
        question: str,
        scored: list[ScoredComponent],
        filters: QueryFilters,
    ) -> str:
        relationship_context = self._build_relationship_context(question, scored[0], filters)
        prefix = ""
        if filters.as_of is not None:
            prefix = f"As of {filters.as_of.date().isoformat()}, "

        if len(scored) == 1:
            item = scored[0]
            answer = f"{prefix}{item.component.name} ({item.model.name}): {item.component.value}."
            if relationship_context:
                return f"{answer} {relationship_context}"
            return answer

        models = {item.model.name for item in scored}
        summary = "; ".join(
            f"{item.component.name}: {item.component.value}" for item in scored[:3]
        )
        if len(models) == 1:
            model_name = next(iter(models))
            answer = f"{prefix}I found {len(scored)} relevant components in {model_name}: {summary}."
        else:
            answer = f"{prefix}I found {len(scored)} relevant components across the workspace: {summary}."
        if relationship_context:
            return f"{answer} {relationship_context}"
        return answer

    def _build_relationship_context(
        self,
        question: str,
        scored: ScoredComponent,
        filters: QueryFilters,
    ) -> str | None:
        question_tokens = self._tokenize(question)
        if not (question_tokens & RELATIONSHIP_HINT_TOKENS):
            return None

        relation_match = self._select_relationship(scored.component, question, filters)
        if relation_match is None:
            return None

        relation, other_component = relation_match
        sentence = self._relationship_sentence(scored.component, relation, other_component)
        if relation.description:
            description = relation.description.strip()
            if description:
                description = description.rstrip(".") + "."
                return f"{sentence} {description}"
        return sentence

    def _select_relationship(
        self,
        component: Component,
        question: str,
        filters: QueryFilters,
    ) -> tuple[Relationship, Component] | None:
        question_text = question.lower()
        question_tokens = self._tokenize(question)
        candidates: list[tuple[float, Relationship, Component]] = []

        for relation in chain(component.outgoing_relationships, component.incoming_relationships):
            if not self._is_relationship_visible(relation, filters):
                continue
            other_component = self._other_component(component, relation)
            if other_component is None:
                continue
            if not self._is_component_visible(other_component, filters):
                continue
            if other_component.confidence < filters.min_confidence:
                continue
            if not self._within_age_limit(other_component, filters.max_age_days):
                continue

            relation_tokens = self._tokenize(relation.relationship_type.value.replace("_", " "))
            other_tokens = self._tokenize(other_component.name)
            score = RELATIONSHIP_TYPE_WEIGHT.get(relation.relationship_type, 1.0) + relation.confidence
            score += 0.75 * len(relation_tokens & question_tokens)
            score += 0.5 * min(2, len(other_tokens & question_tokens))
            if other_component.name.lower() in question_text:
                score += 0.5
            if score <= 0:
                continue
            candidates.append((score, relation, other_component))

        if not candidates:
            return None

        candidates.sort(key=lambda item: item[0], reverse=True)
        _, relation, other_component = candidates[0]
        return relation, other_component

    def _relationship_sentence(
        self,
        component: Component,
        relation: Relationship,
        other_component: Component,
    ) -> str:
        source_is_subject = relation.source_component_id == component.id
        target_name = other_component.name

        if relation.relationship_type == RelationshipType.BLOCKED_BY:
            if source_is_subject:
                return f"{component.name} is blocked by {target_name}."
            return f"{component.name} blocks {target_name}."
        if relation.relationship_type == RelationshipType.DEPENDS_ON:
            if source_is_subject:
                return f"{component.name} depends on {target_name}."
            return f"{component.name} is a dependency for {target_name}."
        if relation.relationship_type == RelationshipType.ENABLES:
            if source_is_subject:
                return f"{component.name} enables {target_name}."
            return f"{component.name} is enabled by {target_name}."
        if relation.relationship_type == RelationshipType.CONTRADICTS:
            return f"{component.name} contradicts {target_name}."
        if relation.relationship_type == RelationshipType.SUPERSEDES:
            if source_is_subject:
                return f"{component.name} supersedes {target_name}."
            return f"{component.name} was superseded by {target_name}."
        return f"{component.name} is related to {target_name}."

    @staticmethod
    def _other_component(component: Component, relation: Relationship) -> Component | None:
        if relation.source_component_id == component.id:
            return relation.target_component
        if relation.target_component_id == component.id:
            return relation.source_component
        return None

    @staticmethod
    def _component_signature(component: Component) -> tuple[str, str]:
        return component.name.lower(), component.value.lower()

    @staticmethod
    def _tokenize(text: str) -> set[str]:
        tokens = re.findall(r"[a-z0-9_]+", text.lower())
        return {token for token in tokens if token not in STOPWORDS}

    @staticmethod
    def _within_age_limit(
        component: Component,
        max_age_days: int | None,
        *,
        as_of: datetime | None = None,
    ) -> bool:
        if max_age_days is None:
            return True
        reference = as_of or datetime.now(UTC)
        return component.last_verified_at >= reference - timedelta(days=max_age_days)

    @staticmethod
    def _calculate_freshness(
        components: Iterable[Component],
        *,
        as_of: datetime | None = None,
    ) -> FreshnessStatus:
        """Compute freshness based on recency and explicit staleness.

        A component is STALE if:
        - it is flagged ``is_stale`` **and** that flag was already set at the
          requested *as_of* time (i.e. the component was superseded/rejected
          *before* the reference point), or
        - its ``last_verified_at`` is older than 30 days relative to *as_of*
          (or wall-clock now if *as_of* is not provided).

        A component is POSSIBLY_STALE if ``last_verified_at`` is 7-30 days old
        relative to *as_of*.

        For ``as_of`` queries, the reference time is the requested point in time,
        so historical facts that were recently verified at that point are not
        mislabeled as stale just because time has passed since then.

        Crucially, a component that was superseded *after* the as_of time should
        not be considered stale at the as_of time — it was still the current truth.
        """
        reference = as_of or datetime.now(UTC)
        has_any_stale_flag = False
        latest_age = timedelta(0)

        for component in components:
            # Only honor the is_stale flag when the staleness boundary (valid_to)
            # occurred at or before the reference time.  If valid_to is in the
            # future relative to as_of, the component was still "active truth" at
            # that point and should not be penalized for being superseded later.
            if component.is_stale:
                stale_at = component.valid_to
                if stale_at is None or stale_at <= reference:
                    has_any_stale_flag = True
            if component.last_verified_at is not None:
                age = max(reference - component.last_verified_at, timedelta(0))
                if age > latest_age:
                    latest_age = age

        if has_any_stale_flag or latest_age > timedelta(days=30):
            return FreshnessStatus.STALE
        if latest_age > timedelta(days=7):
            return FreshnessStatus.POSSIBLY_STALE
        return FreshnessStatus.CURRENT

    @staticmethod
    def _answered_at() -> str:
        return datetime.now(UTC).isoformat()
