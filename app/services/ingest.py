from __future__ import annotations

import json
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Component, Model, Relationship, SourceDocument
from app.processing.embedder import BaseEmbedder, build_default_embedder
from app.processing.extractor import ExtractedFact, Extractor
from app.taxonomy import (
    canonical_model_name,
    canonical_origin,
    canonical_relationship_type,
    canonical_source_type,
    AGENT_SESSION_SOURCE_TYPES,
    AI_CONTEXT_COMPAT_TYPES,
    GITHUB_SOURCE_TYPES,
    resolve_github_item_type,
    resolve_agent_session_type,
)
from app.processing.source_extractors import (
    extract_agent_session,
    extract_github_issue,
    extract_github_pr,
)


class IngestionService:
    def __init__(
        self,
        session: AsyncSession,
        extractor: Extractor | None = None,
        embedder: BaseEmbedder | None = None,
    ) -> None:
        self.session = session
        self._extractor = extractor or Extractor()
        self._embedder = embedder or build_default_embedder()

    async def process_document(self, doc_id: UUID) -> int:
        doc = await self.session.get(SourceDocument, doc_id)
        if doc is None or doc.processed_at is not None:
            return 0

        metadata = _parse_metadata(doc.metadata_json)
        facts = self._extract_source_facts(doc, metadata)
        if not facts:
            facts_list = await self._extractor.extract(doc.content, metadata)
            facts = facts_list
        if isinstance(facts, list):
            facts = [f for f in facts if isinstance(f, ExtractedFact)]
        if not facts:
            doc.processed_at = datetime.utcnow()
            await self.session.flush()
            return 0

        components = []
        for fact in facts:
            model = await self._get_or_create_model(fact.model_name)
            component = await self._upsert_component(model, doc, fact)
            components.append((component, fact))

        texts = [f"{c.name}\n{c.value}" for c, _ in components if c.embedding is None]
        if texts:
            vectors = await self._embedder.embed_texts(texts)
            idx = 0
            for c, _ in components:
                if c.embedding is None:
                    c.embedding = json.dumps(vectors[idx])
                    idx += 1

        for component, fact in components:
            for rel in fact.relationships:
                origin = _determine_origin(doc.source_type, rel)
                await self._create_relationship(component, rel, origin)

        doc.processed_at = datetime.utcnow()
        await self.session.flush()
        return len(components)

    def _extract_source_facts(self, doc: SourceDocument, metadata: dict) -> list[ExtractedFact]:
        github_item_type = resolve_github_item_type(doc.source_type, metadata)
        if github_item_type == "github_pr":
            return extract_github_pr(doc.content, metadata)
        if github_item_type == "github_issue":
            return extract_github_issue(doc.content, metadata)

        canonical_source_type(doc.source_type)

        resolved = resolve_agent_session_type(doc.source_type)
        if resolved == "agent_session":
            return extract_agent_session(doc.content, metadata)

        return []

    async def _get_or_create_model(self, name: str) -> Model:
        name = canonical_model_name(name)
        model = await self.session.scalar(select(Model).where(Model.name == name))
        if model is None:
            model = Model(name=name)
            self.session.add(model)
            await self.session.flush()
        return model

    async def _upsert_component(self, model: Model, doc: SourceDocument, fact: ExtractedFact) -> Component:
        existing = await self.session.scalar(
            select(Component).where(
                Component.model_id == model.id,
                Component.name == fact.name,
                Component.value == fact.value,
                Component.status.in_(["active", "needs_review", "proposed"]),
            )
        )
        if existing is not None:
            existing.confidence = max(existing.confidence, fact.confidence)
            if fact.temporal and fact.temporal != "unknown":
                existing.temporal = fact.temporal
            provenance = getattr(fact, "provenance", None)
            if provenance and not existing.provenance:
                existing.provenance = provenance
            excerpt = getattr(fact, "excerpt", None)
            if excerpt and not existing.excerpt:
                existing.excerpt = excerpt
            return existing

        status = "needs_review" if fact.confidence < 0.6 else "active"
        temporal = getattr(fact, "temporal_hint", getattr(fact, "temporal", "current"))
        if temporal == "future":
            status = "proposed"
        elif temporal == "past":
            status = "needs_review"

        component = Component(
            model_id=model.id,
            source_document_id=doc.id,
            name=fact.name,
            value=fact.value,
            fact_type=fact.fact_type,
            temporal=getattr(fact, "temporal", "unknown"),
            confidence=fact.confidence,
            status=status,
            provenance=getattr(fact, "provenance", None),
            excerpt=getattr(fact, "excerpt", None),
        )
        self.session.add(component)
        await self.session.flush()
        return component

    async def _create_relationship(self, source: Component, rel, origin: str = "proposed") -> None:
        confidence = min(max(float(getattr(rel, "confidence", 0.7)), 0.0), 1.0)
        if confidence < 0.6:
            return

        target_name = getattr(rel, "target_name", "").strip()
        if not target_name:
            return

        if target_name == source.name:
            return

        target = await self.session.scalar(
            select(Component).where(
                Component.model_id == source.model_id,
                Component.name == target_name,
                Component.id != source.id,
                Component.status.in_(["active", "needs_review", "proposed"]),
            ).order_by(Component.confidence.desc()).limit(1)
        )

        if target is None:
            target = await self.session.scalar(
                select(Component).where(
                    Component.name == target_name,
                    Component.id != source.id,
                    Component.status.in_(["active", "needs_review", "proposed"]),
                ).order_by(Component.confidence.desc()).limit(1)
            )

        if target is None:
            return

        rel_type = canonical_relationship_type(rel.relationship_type)

        if rel_type == "related_to" and confidence < 0.7:
            return

        exists = await self.session.scalar(
            select(Relationship).where(
                Relationship.source_component_id == source.id,
                Relationship.target_component_id == target.id,
                Relationship.relationship_type == rel_type,
            )
        )
        if exists is not None:
            return

        evidence = getattr(rel, "evidence", None)
        if not evidence:
            evidence = f"'{source.name}' {rel_type} '{target_name}' (template evidence)"

        resolved_origin = canonical_origin(origin)
        if resolved_origin == "ai_proposed" and confidence >= 0.85:
            resolved_origin = "ai_proposed"

        self.session.add(Relationship(
            source_component_id=source.id,
            target_component_id=target.id,
            relationship_type=rel_type,
            confidence=confidence,
            evidence=evidence,
            origin=resolved_origin,
        ))
        await self.session.flush()


def _determine_origin(source_type: str, rel) -> str:
    source_type = (source_type or "").strip().lower()
    deterministic_types = {
        "solves", "fixes", "created_from", "part_of", "generated_by_agent",
        "implemented_in", "duplicates", "supersedes", "touches_file",
        "resolved_by",
    }
    rel_type = canonical_relationship_type(getattr(rel, "relationship_type", "related_to"))
    if rel_type in deterministic_types:
        return "deterministic"
    if source_type in GITHUB_SOURCE_TYPES | AGENT_SESSION_SOURCE_TYPES | AI_CONTEXT_COMPAT_TYPES:
        return "extracted"
    return "proposed"


def _parse_metadata(raw: str) -> dict:
    if not raw or raw == "{}":
        return {}
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
