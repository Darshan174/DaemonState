from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Component, Model, Relationship, SourceDocument
from app.services.ingest import IngestionService

logger = logging.getLogger(__name__)


class GraphBuilderAgent:
    """
    Processes pending SourceDocuments through the extraction pipeline,
    then infers cross-document relationships between active components.

    Phase 1 — Extraction:
        Calls IngestionService.process_document() for every unprocessed doc.
        Uses LLM extraction when LITELLM_API_KEY + EXTRACTION_MODEL are set;
        falls back to regex extraction otherwise.

    Phase 2 — Cross-document inference:
        Scans each component's value for names of other components that live
        in different source documents and creates 'related_to' edges.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._ingestor = IngestionService(session)

    async def run(self, limit: int = 100, api_key: str | None = None, model: str | None = None) -> dict:
        started_at = datetime.utcnow()

        extractor = None
        if api_key or model:
            from app.processing.extractor import Extractor
            extractor = Extractor(api_key=api_key, model=model)
            ingestor = IngestionService(self.session, extractor=extractor)
        else:
            ingestor = self._ingestor

        pending = list(await self.session.scalars(
            select(SourceDocument)
            .where(SourceDocument.processed_at.is_(None))
            .order_by(SourceDocument.ingested_at.desc())
            .limit(limit)
        ))

        docs_processed = 0
        components_created = 0
        errors: list[dict] = []

        for doc in pending:
            try:
                n = await ingestor.process_document(doc.id)
                components_created += n
                docs_processed += 1
                extraction_error = getattr(ingestor._extractor, "last_error", None)
                if extraction_error:
                    errors.append({
                        "doc_id": str(doc.id),
                        "warning": "llm_extraction_failed_regex_fallback",
                        "error": extraction_error,
                    })
            except Exception as exc:
                errors.append({"doc_id": str(doc.id), "error": str(exc)})
                logger.warning("graph_builder: error processing doc %s: %s", doc.id, exc)

        await self.session.commit()

        relationships_inferred = await self._infer_cross_doc_relationships()
        await self.session.commit()

        total_components = await self.session.scalar(select(func.count(Component.id))) or 0
        total_relationships = await self.session.scalar(select(func.count(Relationship.id))) or 0
        pending_after = await self.session.scalar(
            select(func.count(SourceDocument.id)).where(SourceDocument.processed_at.is_(None))
        ) or 0

        from app.config import settings
        llm_active = bool(
            (api_key or settings.litellm_api_key) and (model or settings.extraction_model)
        )

        return {
            "started_at": started_at.isoformat(),
            "finished_at": datetime.utcnow().isoformat(),
            "llm_extraction": llm_active,
            "docs_processed": docs_processed,
            "docs_pending_before": len(pending),
            "components_created": components_created,
            "relationships_inferred": relationships_inferred,
            "errors": errors,
            "stats": {
                "total_components": total_components,
                "total_relationships": total_relationships,
                "pending_docs": pending_after,
            },
        }

    async def _infer_cross_doc_relationships(self) -> int:
        components = list(await self.session.scalars(
            select(Component).where(Component.status == "active")
        ))
        if not components:
            return 0

        name_map: dict[str, list[Component]] = {}
        for comp in components:
            key = comp.name.lower().strip()
            if len(key) > 5:
                name_map.setdefault(key, []).append(comp)

        inferred = 0
        existing_pairs: set[tuple] = set()

        existing_rels = list(await self.session.scalars(select(Relationship)))
        for r in existing_rels:
            existing_pairs.add((r.source_component_id, r.target_component_id))

        for comp in components:
            value_lower = (comp.value or "").lower()
            for other_name, others in name_map.items():
                if other_name not in value_lower:
                    continue
                for other in others:
                    if other.id == comp.id:
                        continue
                    if other.source_document_id == comp.source_document_id:
                        continue
                    if (comp.id, other.id) in existing_pairs:
                        continue

                    self.session.add(Relationship(
                        source_component_id=comp.id,
                        target_component_id=other.id,
                        relationship_type="related_to",
                        confidence=0.5,
                        evidence=f"Name mention: '{other_name}' found in '{comp.name}' — cross-document candidate, verify before trusting",
                        origin="proposed",
                    ))
                    existing_pairs.add((comp.id, other.id))
                    inferred += 1

                    if inferred >= 300:
                        return inferred

        return inferred
