from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Component, Model, Relationship, SourceDocument, UnresolvedRelationship
from app.processing.embedder import BaseEmbedder, build_default_embedder
from app.processing.extractor import (
    ExtractedFact,
    ExtractionQualityReport,
    Extractor,
    evaluate_extraction_quality,
)
from app.services.identity import (
    ensure_entity_for_identity,
    identity_key_for_component_name,
    record_component_evidence,
)
from app.services.claims import upsert_claim_for_fact
from app.services.evidence import ensure_source_document_ledger_fields
from app.taxonomy import (
    canonical_model_name,
    canonical_origin,
    canonical_relationship_type,
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
from app.time import utc_now


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
        self.last_extraction_error: str | None = None
        self.last_extraction_warnings: list[str] = []
        self.last_extraction_report: ExtractionQualityReport | None = None
        self.last_projection_report = {
            "created": 0,
            "reused": 0,
            "superseded": 0,
            "relationships_superseded": 0,
        }

    async def process_document(self, doc_id: UUID, *, force: bool = False) -> int:
        self.last_extraction_error = None
        self.last_extraction_warnings = []
        self.last_extraction_report = None
        doc = await self.session.get(SourceDocument, doc_id)
        self.last_projection_report = {
            "created": 0,
            "reused": 0,
            "superseded": 0,
            "relationships_superseded": 0,
        }
        if doc is None or (doc.processed_at is not None and not force):
            return 0
        await ensure_source_document_ledger_fields(doc)

        metadata = _parse_metadata(doc.metadata_json)
        doc_workspace_id = _coerce_workspace_uuid(
            getattr(doc, "workspace_id", None) or metadata.get("workspace_id")
        )
        if doc_workspace_id and doc.workspace_id != doc_workspace_id:
            doc.workspace_id = doc_workspace_id
        metadata.setdefault("source_type", doc.source_type)
        metadata.setdefault("external_id", doc.external_id)
        if doc_workspace_id:
            metadata.setdefault("workspace_id", str(doc_workspace_id))
        if doc.author:
            metadata.setdefault("author", doc.author)
        if doc.source_url:
            metadata.setdefault("source_url", doc.source_url)
        facts = self._extract_source_facts(doc, metadata)
        extraction_method = "deterministic" if facts else "fallback"
        if not facts:
            facts_list = await self._extractor.extract(doc.content, metadata)
            facts = facts_list
            extraction_method = "llm_or_regex"
            self.last_extraction_error = getattr(self._extractor, "last_error", None)
            self.last_extraction_warnings = list(getattr(self._extractor, "last_warnings", []) or [])
            self.last_extraction_report = getattr(self._extractor, "last_report", None)
        if isinstance(facts, list):
            facts = [f for f in facts if isinstance(f, ExtractedFact)]
        if self.last_extraction_report is None:
            self.last_extraction_report = evaluate_extraction_quality(facts or [])
        if not facts:
            await self._reconcile_source_projection(doc, [])
            doc.processed_at = utc_now()
            await self.session.flush()
            return 0

        components = []
        for fact in facts:
            model = await self._get_or_create_model(fact.model_name)
            component = await self._upsert_component(
                model,
                doc,
                fact,
                extraction_method=extraction_method,
            )
            await record_component_evidence(
                self.session,
                component=component,
                extracted_fact=fact,
            )
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

        await self._reconcile_source_projection(
            doc,
            [component for component, _ in components],
        )

        doc.processed_at = utc_now()
        await self.session.flush()
        return len(components)

    def _extract_source_facts(self, doc: SourceDocument, metadata: dict) -> list[ExtractedFact]:
        github_item_type = resolve_github_item_type(doc.source_type, metadata)
        if github_item_type == "github_pr":
            return extract_github_pr(doc.content, metadata)
        if github_item_type == "github_issue":
            return extract_github_issue(doc.content, metadata)

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

    async def _upsert_component(
        self,
        model: Model,
        doc: SourceDocument,
        fact: ExtractedFact,
        extraction_method: str = "legacy",
    ) -> Component:
        workspace_id = _coerce_workspace_uuid(getattr(doc, "workspace_id", None))
        identity_key = identity_key_for_component_name(fact.name)
        status = "needs_review" if fact.confidence < 0.6 else "active"
        temporal = getattr(fact, "temporal_hint", getattr(fact, "temporal", "current"))
        if temporal == "future":
            status = "proposed"
        elif temporal == "past":
            status = "needs_review"

        claim_result = await upsert_claim_for_fact(
            self.session,
            source_document=doc,
            fact=fact,
            component_status=status,
            extraction_method=extraction_method,
        )
        if extraction_method != "legacy" and not claim_result.evidence_is_exact:
            status = "needs_review"

        existing_stmt = select(Component).where(
            Component.model_id == model.id,
            Component.source_document_id == doc.id,
            Component.value == fact.value,
            Component.status.in_(["active", "needs_review", "proposed"]),
        )
        if identity_key:
            existing_stmt = existing_stmt.where(or_(
                Component.identity_key == identity_key,
                Component.name == fact.name,
            ))
        else:
            existing_stmt = existing_stmt.where(Component.name == fact.name)
        if workspace_id:
            existing_stmt = existing_stmt.where(Component.workspace_id == workspace_id)
        else:
            existing_stmt = existing_stmt.where(Component.workspace_id.is_(None))
        existing = await self.session.scalar(existing_stmt)
        entity = await ensure_entity_for_identity(
            self.session,
            model_id=model.id,
            workspace_id=workspace_id,
            identity_key=identity_key,
            canonical_name=fact.name,
        )
        if existing is not None:
            self.last_projection_report["reused"] += 1
            existing.confidence = max(existing.confidence, fact.confidence)
            if workspace_id and not existing.workspace_id:
                existing.workspace_id = workspace_id
            if identity_key and not existing.identity_key:
                existing.identity_key = identity_key
            if entity and not existing.entity_id:
                existing.entity_id = entity.id
            if not existing.claim_id:
                existing.claim_id = claim_result.claim.id
            if extraction_method != "legacy" and not claim_result.evidence_is_exact:
                existing.status = "needs_review"
            if fact.temporal and fact.temporal != "unknown":
                existing.temporal = fact.temporal
            provenance = getattr(fact, "provenance", None)
            if provenance and not existing.provenance:
                existing.provenance = provenance
            excerpt = getattr(fact, "excerpt", None)
            if excerpt and not existing.excerpt:
                existing.excerpt = excerpt
            return existing

        component = Component(
            workspace_id=workspace_id,
            entity_id=entity.id if entity else None,
            claim_id=claim_result.claim.id,
            model_id=model.id,
            source_document_id=doc.id,
            identity_key=identity_key,
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
        self.last_projection_report["created"] += 1
        return component

    async def _reconcile_source_projection(
        self,
        doc: SourceDocument,
        current_components: list[Component],
    ) -> None:
        """Retire derived rows no longer produced by the current source revision."""
        active_statuses = ("active", "needs_review", "proposed", "stale")
        source_rows = list(await self.session.scalars(
            select(SourceDocument.id).where(
                SourceDocument.source_identity_sha256 == doc.source_identity_sha256
            )
        ))
        if not source_rows:
            return

        current_ids = {component.id for component in current_components}
        obsolete = list(await self.session.scalars(
            select(Component).where(
                Component.source_document_id.in_(source_rows),
                Component.status.in_(active_statuses),
            )
        ))
        obsolete = [component for component in obsolete if component.id not in current_ids]
        if not obsolete:
            return

        replacements: dict[tuple[str, str | None], Component] = {}
        replacements_by_fact_type: dict[str, list[Component]] = {}
        for component in current_components:
            replacements[(component.fact_type, component.identity_key)] = component
            replacements_by_fact_type.setdefault(component.fact_type, []).append(component)

        now = utc_now()
        obsolete_ids: set[UUID] = set()
        for component in obsolete:
            replacement = replacements.get((component.fact_type, component.identity_key))
            if replacement is None and len(replacements_by_fact_type.get(component.fact_type, [])) == 1:
                replacement = replacements_by_fact_type[component.fact_type][0]
            component.status = "superseded"
            component.valid_to = now
            component.superseded_by_id = replacement.id if replacement else None
            obsolete_ids.add(component.id)

        relationships = list(await self.session.scalars(
            select(Relationship).where(
                or_(
                    Relationship.source_component_id.in_(obsolete_ids),
                    Relationship.target_component_id.in_(obsolete_ids),
                ),
                Relationship.status != "superseded",
            )
        ))
        for relationship in relationships:
            relationship.status = "superseded"

        self.last_projection_report["superseded"] += len(obsolete)
        self.last_projection_report["relationships_superseded"] += len(relationships)
        await self.session.flush()

    async def _create_relationship(self, source: Component, rel, origin: str = "proposed") -> None:
        confidence = min(max(float(getattr(rel, "confidence", 0.7)), 0.0), 1.0)
        if confidence < 0.6:
            return

        target_name = getattr(rel, "target_name", "").strip()
        if not target_name:
            return

        if target_name == source.name:
            return

        active_statuses = ["active", "needs_review", "proposed"]
        workspace_id = _coerce_workspace_uuid(getattr(source, "workspace_id", None))
        source_identity_key = identity_key_for_component_name(source.name)
        target_identity_key = identity_key_for_component_name(target_name)
        if source_identity_key and not source.identity_key:
            source.identity_key = source_identity_key
        if target_identity_key and source.identity_key == target_identity_key:
            return

        target = None
        if target_identity_key:
            target = await self.session.scalar(
                _scope_component_query(
                    select(Component).where(
                        Component.model_id == source.model_id,
                        Component.identity_key == target_identity_key,
                        Component.id != source.id,
                        Component.status.in_(active_statuses),
                    ),
                    workspace_id,
                ).order_by(Component.confidence.desc()).limit(1)
            )

        if target is None:
            target = await self.session.scalar(
                _scope_component_query(
                    select(Component).where(
                        Component.model_id == source.model_id,
                        Component.name == target_name,
                        Component.id != source.id,
                        Component.status.in_(active_statuses),
                    ),
                    workspace_id,
                ).order_by(Component.confidence.desc()).limit(1)
            )

        if target is None and target_identity_key:
            target = await self.session.scalar(
                _scope_component_query(
                    select(Component).where(
                        Component.identity_key == target_identity_key,
                        Component.id != source.id,
                        Component.status.in_(active_statuses),
                    ),
                    workspace_id,
                ).order_by(Component.confidence.desc()).limit(1)
            )

        if target is None:
            target = await self.session.scalar(
                _scope_component_query(
                    select(Component).where(
                        Component.name == target_name,
                        Component.id != source.id,
                        Component.status.in_(active_statuses),
                    ),
                    workspace_id,
                ).order_by(Component.confidence.desc()).limit(1)
            )

        if target is None:
            target_prefix = f"{target_name}:"
            target = await self.session.scalar(
                _scope_component_query(
                    select(Component).where(
                        Component.model_id == source.model_id,
                        Component.name.startswith(target_prefix),
                        Component.id != source.id,
                        Component.status.in_(active_statuses),
                    ),
                    workspace_id,
                ).order_by(Component.confidence.desc()).limit(1)
            )

        if target is None:
            target_prefix = f"{target_name}:"
            target = await self.session.scalar(
                _scope_component_query(
                    select(Component).where(
                        Component.name.startswith(target_prefix),
                        Component.id != source.id,
                        Component.status.in_(active_statuses),
                    ),
                    workspace_id,
                ).order_by(Component.confidence.desc()).limit(1)
            )

        rel_type = canonical_relationship_type(rel.relationship_type)

        if rel_type == "related_to" and confidence < 0.7:
            return

        if target is None:
            await self._record_unresolved_relationship(
                source=source,
                target_name=target_name,
                target_identity_key=target_identity_key,
                relationship_type=rel_type,
                confidence=confidence,
                evidence=getattr(rel, "evidence", None),
                origin=origin,
            )
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

    async def _record_unresolved_relationship(
        self,
        *,
        source: Component,
        target_name: str,
        target_identity_key: str | None,
        relationship_type: str,
        confidence: float,
        evidence: str | None,
        origin: str,
    ) -> None:
        resolved_origin = canonical_origin(origin)
        existing = await self.session.scalar(
            select(UnresolvedRelationship).where(
                UnresolvedRelationship.source_component_id == source.id,
                UnresolvedRelationship.target_identity_key == target_identity_key,
                UnresolvedRelationship.target_name == target_name,
                UnresolvedRelationship.relationship_type == relationship_type,
                UnresolvedRelationship.status == "unresolved",
            )
        )
        if existing is not None:
            existing.confidence = max(existing.confidence, confidence)
            if evidence and not existing.evidence:
                existing.evidence = evidence
            if resolved_origin != "proposed":
                existing.origin = resolved_origin
            return

        self.session.add(UnresolvedRelationship(
            workspace_id=_coerce_workspace_uuid(getattr(source, "workspace_id", None)),
            source_component_id=source.id,
            source_document_id=getattr(source, "source_document_id", None),
            target_name=target_name,
            target_identity_key=target_identity_key,
            relationship_type=relationship_type,
            confidence=confidence,
            evidence=evidence,
            origin=resolved_origin,
            status="unresolved",
        ))
        await self.session.flush()


def _determine_origin(source_type: str, rel) -> str:
    source_type = (source_type or "").strip().lower()
    deterministic_types = {
        "solves", "fixes", "created_from", "part_of", "generated_by_agent",
        "implemented_in", "duplicates", "supersedes", "touches_file",
        "resolved_by", "discussed_in",
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


def _coerce_workspace_uuid(value: object) -> UUID | None:
    if value in (None, ""):
        return None
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except (TypeError, ValueError):
        return None


def _scope_component_query(stmt, workspace_id: UUID | None):
    if workspace_id:
        return stmt.where(Component.workspace_id == workspace_id)
    return stmt.where(Component.workspace_id.is_(None))
