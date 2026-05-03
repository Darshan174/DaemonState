from __future__ import annotations

import json
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Component, Model, Relationship, SourceDocument
from app.processing.embedder import BaseEmbedder, build_default_embedder
from app.processing.extractor import ExtractedFact, Extractor


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

        facts = await self._extractor.extract(doc.content, _parse_metadata(doc.metadata_json))
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
                await self._create_relationship(component, rel)

        doc.processed_at = datetime.utcnow()
        await self.session.flush()
        return len(components)

    async def _get_or_create_model(self, name: str) -> Model:
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
        )
        self.session.add(component)
        await self.session.flush()
        return component

    async def _create_relationship(self, source: Component, rel) -> None:

        confidence = float(getattr(rel, "confidence", 0.7))
        if confidence < 0.6:
            return

        target_name = getattr(rel, "target_name", "").strip()
        if not target_name:
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

        exists = await self.session.scalar(
            select(Relationship).where(
                Relationship.source_component_id == source.id,
                Relationship.target_component_id == target.id,
                Relationship.relationship_type == rel.relationship_type,
            )
        )
        if exists is not None:
            return

        evidence = getattr(rel, "evidence", None)
        if not evidence:
            evidence = f"'{source.name}' {rel.relationship_type} '{target.name}'"

        self.session.add(Relationship(
            source_component_id=source.id,
            target_component_id=target.id,
            relationship_type=rel.relationship_type,
            confidence=confidence,
            evidence=evidence,
        ))
        await self.session.flush()


def _parse_metadata(raw: str) -> dict:
    if not raw or raw == "{}":
        return {}
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
