from __future__ import annotations

import json
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Component, Relationship
from app.processing.embedder import cosine_similarity
from app.services.workspace_scope import filter_components_for_workspace


@dataclass(frozen=True)
class SemanticCandidate:
    source: Component
    target: Component
    score: float

    @property
    def evidence(self) -> str:
        source_type = self.source.source_document.source_type if self.source.source_document else "unknown"
        target_type = self.target.source_document.source_type if self.target.source_document else "unknown"
        return (
            f"Semantic similarity {self.score:.2f} between '{self.source.name}' "
            f"({source_type}) and '{self.target.name}' ({target_type}); "
            "candidate relationship, verify before trusting."
        )


class SemanticRelationshipLinker:
    def __init__(
        self,
        session: AsyncSession,
        *,
        threshold: float = 0.84,
        max_candidates: int = 300,
        neighbors_per_component: int = 5,
        require_cross_source_type: bool = True,
        workspace_scope: tuple[str, set[str]] | None = None,
    ) -> None:
        self.session = session
        self.threshold = threshold
        self.max_candidates = max_candidates
        self.neighbors_per_component = neighbors_per_component
        self.require_cross_source_type = require_cross_source_type
        self.workspace_scope = workspace_scope

    async def candidates(self) -> list[SemanticCandidate]:
        components = list(await self.session.scalars(
            select(Component)
            .options(selectinload(Component.model), selectinload(Component.source_document))
            .where(Component.status.in_(["active", "needs_review", "proposed"]))
            .where(Component.embedding.is_not(None))
        ))
        if self.workspace_scope:
            components = filter_components_for_workspace(
                components,
                self.workspace_scope[0],
                self.workspace_scope[1],
            )
        embedded = [
            (component, vector)
            for component in components
            if (vector := _parse_embedding(component.embedding)) is not None
        ]
        if len(embedded) < 2:
            return []

        existing = await self._existing_pairs()
        per_source: dict[UUID, list[SemanticCandidate]] = {}

        for i, (source, source_vec) in enumerate(embedded):
            for target, target_vec in embedded[i + 1:]:
                if source.id == target.id:
                    continue
                if source.source_document_id == target.source_document_id:
                    continue
                if self.require_cross_source_type and _source_type(source) == _source_type(target):
                    continue
                if _pair_key(source.id, target.id) in existing:
                    continue

                score = cosine_similarity(source_vec, target_vec)
                if score < self.threshold:
                    continue
                candidate = SemanticCandidate(source=source, target=target, score=score)
                per_source.setdefault(source.id, []).append(candidate)
                per_source.setdefault(target.id, []).append(candidate)

        candidates = _dedupe_candidates(
            candidate
            for source_candidates in per_source.values()
            for candidate in sorted(source_candidates, key=lambda c: c.score, reverse=True)[
                : self.neighbors_per_component
            ]
        )
        candidates.sort(
            key=lambda c: (
                c.score,
                c.source.confidence + c.target.confidence,
                c.source.authority_weight + c.target.authority_weight,
            ),
            reverse=True,
        )
        return candidates[: self.max_candidates]

    async def create_relationships(self, *, limit: int = 100) -> int:
        created = 0
        for candidate in (await self.candidates())[:limit]:
            self.session.add(Relationship(
                source_component_id=candidate.source.id,
                target_component_id=candidate.target.id,
                relationship_type="related_to",
                confidence=min(max(candidate.score, 0.0), 0.95),
                evidence=candidate.evidence,
                status="proposed",
                origin="ai_proposed",
            ))
            created += 1

        if created:
            await self.session.flush()
        return created

    async def _existing_pairs(self) -> set[tuple[UUID, UUID]]:
        rows = list(await self.session.scalars(select(Relationship)))
        pairs: set[tuple[UUID, UUID]] = set()
        for rel in rows:
            pairs.add(_pair_key(rel.source_component_id, rel.target_component_id))
        return pairs


def _parse_embedding(raw: str | None) -> list[float] | None:
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(parsed, list) or not parsed:
        return None
    try:
        return [float(value) for value in parsed]
    except (TypeError, ValueError):
        return None


def _source_type(component: Component) -> str | None:
    if not component.source_document:
        return None
    return component.source_document.source_type


def _pair_key(lhs: UUID, rhs: UUID) -> tuple[UUID, UUID]:
    return tuple(sorted((lhs, rhs), key=str))


def _dedupe_candidates(candidates) -> list[SemanticCandidate]:
    seen: set[tuple[UUID, UUID]] = set()
    unique: list[SemanticCandidate] = []
    for candidate in candidates:
        key = _pair_key(candidate.source.id, candidate.target.id)
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return unique
