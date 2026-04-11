"""Ingestion pipeline — processes raw SourceDocuments into knowledge graph facts."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.knowledge import (
    Component,
    ComponentSource,
    KnowledgeModel,
    Relationship,
    RelationshipType,
)
from app.models.review import ReviewDecision, ReviewItem
from app.models.source import ConnectorType, SourceDocument
from app.processing.embedder import BaseEmbedder, build_default_embedder
from app.processing.extractor import (
    BaseExtractor,
    ExtractedFact,
    ExtractedRelationship,
    build_default_extractor,
)


class IngestionServiceError(Exception):
    """Base ingestion error."""


class IngestionService:
    """Reads unprocessed SourceDocuments and creates knowledge graph entries."""

    _LOW_CONFIDENCE_THRESHOLD = 0.60
    _HIGH_RISK_CONFIDENCE_THRESHOLD = 0.45
    _CONNECTOR_AUTHORITY_WEIGHTS: dict[ConnectorType, float] = {
        ConnectorType.NOTION: 0.95,
        ConnectorType.ZOOM: 0.90,
        ConnectorType.GONG: 0.90,
        ConnectorType.GITHUB: 0.86,
        ConnectorType.GDRIVE: 0.88,
        ConnectorType.SLACK: 0.75,
    }
    _AUTO_MODEL_NAMES: dict[ConnectorType, tuple[str, str]] = {
        ConnectorType.SLACK: ("Slack Insights", "Auto-generated from Slack connector sync"),
        ConnectorType.NOTION: ("Notion Insights", "Auto-generated from Notion connector sync"),
        ConnectorType.ZOOM: ("Zoom Insights", "Auto-generated from Zoom connector sync"),
        ConnectorType.GITHUB: ("GitHub Insights", "Auto-generated from GitHub connector sync"),
    }
    _FALLBACK_MODEL = ("Connector Insights", "Auto-generated from connector sync")

    def __init__(
        self,
        session: AsyncSession,
        extractor: BaseExtractor | None = None,
        embedder: BaseEmbedder | None = None,
    ) -> None:
        self.session = session
        self._extractor: BaseExtractor = extractor or build_default_extractor()
        self._embedder: BaseEmbedder = embedder or build_default_embedder()

    async def process_single_document(
        self,
        workspace_id: UUID,
        document: SourceDocument,
        connector_type: ConnectorType | None = None,
    ) -> int:
        """Process a single SourceDocument (used by reprocess endpoint).

        Returns 1 if the document was processed, 0 if already processed.
        Uses a savepoint for isolation.
        """
        if document.processed_at is not None:
            return 0

        model_name, model_desc = self._AUTO_MODEL_NAMES.get(
            connector_type, self._FALLBACK_MODEL
        )
        model = await self._get_or_create_model(workspace_id, model_name, model_desc)

        async with self.session.begin_nested():
            await self._ingest_document(model, document)
            document.processed_at = datetime.now(timezone.utc)
        await self.session.flush()
        return 1

    async def process_connector_documents(
        self,
        workspace_id: UUID,
        connector_id: UUID,
        connector_type: ConnectorType | None = None,
    ) -> int:
        """Process all unprocessed SourceDocuments for a specific connector.

        Returns the number of documents processed.

        Each document is processed inside a nested savepoint so that a
        failure in one document does not roll back the entire batch.
        Embeddings are collected and flushed in batches after extraction.
        """
        docs = await self._select_unprocessed(connector_id)
        if not docs:
            return 0

        model_name, model_desc = self._AUTO_MODEL_NAMES.get(
            connector_type, self._FALLBACK_MODEL
        )
        model = await self._get_or_create_model(workspace_id, model_name, model_desc)

        processed = 0
        for doc in docs:
            ok = await self._ingest_document_with_savepoint(model, doc)
            if ok:
                processed += 1

        await self.session.flush()
        return processed

    # ── Private helpers ───────────────────────────────────────────

    async def _select_unprocessed(
        self, connector_id: UUID
    ) -> list[SourceDocument]:
        """Return SourceDocuments for this connector that have not been processed yet.

        Uses populate_existing so that ORM objects are refreshed from the
        DB — necessary because _persist_documents uses Core-level SQL
        that bypasses the ORM identity map when resetting processed_at.
        """
        result = await self.session.scalars(
            select(SourceDocument)
            .where(
                SourceDocument.connector_id == connector_id,
                SourceDocument.processed_at.is_(None),
                SourceDocument.deleted_at.is_(None),
            )
            .order_by(SourceDocument.ingested_at)
            .execution_options(populate_existing=True)
        )
        return list(result)

    async def _get_or_create_model(
        self, workspace_id: UUID, model_name: str, model_desc: str,
    ) -> KnowledgeModel:
        """Return the auto-generated KnowledgeModel, creating it if needed."""
        model = await self.session.scalar(
            select(KnowledgeModel).where(
                KnowledgeModel.workspace_id == workspace_id,
                KnowledgeModel.name == model_name,
            )
        )
        if model is None:
            model = KnowledgeModel(
                workspace_id=workspace_id,
                name=model_name,
                description=model_desc,
                auto_generated=True,
            )
            self.session.add(model)
            await self.session.flush()
        return model

    async def _ingest_document_with_savepoint(
        self,
        model: KnowledgeModel,
        doc: SourceDocument,
    ) -> bool:
        """Ingest a single document inside a savepoint.

        Returns True on success, False if the document failed to ingest.
        This isolates failures — a bad document won't abort the batch.
        """
        try:
            async with self.session.begin_nested():
                await self._ingest_document(model, doc)
                doc.processed_at = datetime.now(timezone.utc)
                await self.session.flush()
        except Exception:
            return False
        return True

    async def _create_component(
        self,
        model: KnowledgeModel,
        name: str,
        value: str,
        confidence: float,
        doc: SourceDocument,
        authority_weight: float,
        embedding: list[float] | None = None,
    ) -> Component:
        """Create a new component version for a fact."""
        component = Component(
            model_id=model.id,
            name=name,
            value=value,
            confidence=confidence,
            authority_source=doc.source_url,
            authority_weight=authority_weight,
            valid_from=datetime.now(timezone.utc),
            embedding=embedding,
        )
        self.session.add(component)
        await self.session.flush()
        return component

    async def _link_source(
        self,
        component: Component,
        doc: SourceDocument,
        fact: ExtractedFact,
    ) -> None:
        """Create or update a ComponentSource link with fingerprint tracking."""
        content_hash = hashlib.sha256(
            f"{fact.name}:{fact.value}".encode()
        ).hexdigest()
        ctx = f"Extracted from {doc.connector_type.value} document {doc.external_id}"

        existing = await self.session.scalar(
            select(ComponentSource).where(
                ComponentSource.component_id == component.id,
                ComponentSource.source_document_id == doc.id,
            )
        )
        if existing is not None:
            metadata_changed = any(
                (
                    existing.extractor_name != fact.extractor.extractor_name,
                    existing.extractor_kind != fact.extractor.extractor_kind,
                    existing.extractor_schema_version != fact.extractor.schema_version,
                )
            )
            if existing.content_hash == content_hash and not metadata_changed:
                return  # idempotent — same (name, value) pair
            existing.content_hash = content_hash
            existing.extracted_value = fact.value
            existing.extraction_context = ctx
            existing.extractor_name = fact.extractor.extractor_name
            existing.extractor_kind = fact.extractor.extractor_kind
            existing.extractor_schema_version = fact.extractor.schema_version
            await self.session.flush()
            return

        link = ComponentSource(
            component_id=component.id,
            source_document_id=doc.id,
            content_hash=content_hash,
            extracted_value=fact.value,
            extraction_context=ctx,
            extractor_name=fact.extractor.extractor_name,
            extractor_kind=fact.extractor.extractor_kind,
            extractor_schema_version=fact.extractor.schema_version,
        )
        self.session.add(link)
        await self.session.flush()

    async def _create_relationship_if_target_exists(
        self,
        model: KnowledgeModel,
        source_component: Component,
        rel: ExtractedRelationship,
    ) -> None:
        """Create a Relationship row if the named target component exists."""
        try:
            rel_type = RelationshipType(rel.relationship_type)
        except ValueError:
            return

        target = await self.session.scalar(
            select(Component).where(
                Component.model_id == model.id,
                Component.name == rel.target_fact_name,
                Component.valid_to.is_(None),
            )
        )
        if target is None or target.id == source_component.id:
            return

        exists = await self.session.scalar(
            select(Relationship).where(
                Relationship.source_component_id == source_component.id,
                Relationship.target_component_id == target.id,
                Relationship.relationship_type == rel_type,
                Relationship.valid_to.is_(None),
            )
        )
        if exists is not None:
            return

        new_rel = Relationship(
            source_component_id=source_component.id,
            target_component_id=target.id,
            relationship_type=rel_type,
            confidence=rel.confidence,
            description=(
                f"Auto-detected: {source_component.name} "
                f"{rel.relationship_type} {target.name}"
            ),
        )
        self.session.add(new_rel)
        await self.session.flush()

    async def _ingest_document(
        self,
        model: KnowledgeModel,
        doc: SourceDocument,
    ) -> None:
        now = datetime.now(timezone.utc)
        raw_facts = await self._extractor.extract(doc)
        facts = self._collapse_facts(raw_facts)
        existing_links = await self._load_document_links(doc.id)
        retained_component_ids: set[UUID] = set()

        # Phase 1: resolve components and collect texts that need embedding
        embedding_tasks: list[tuple[int, str, Component | None]] = []
        resolved_components: list[Component | None] = [None] * len(facts)

        for idx, fact in enumerate(facts):
            component, needs_embed = await self._resolve_component_for_fact(
                model=model,
                fact=fact,
                doc=doc,
                observed_at=now,
            )
            resolved_components[idx] = component
            if needs_embed:
                embedding_tasks.append(
                    (idx, f"{component.name}\n{component.value}", component)
                )

        # Phase 2: batch embed all new / missing-embedding components
        if embedding_tasks:
            texts = [text for _, text, _ in embedding_tasks]
            vectors = await self._embedder.embed_texts(texts)
            for (idx, _text, component), vector in zip(embedding_tasks, vectors):
                component.embedding = vector
            await self.session.flush()

        # Phase 3: link sources and create relationships
        for idx, fact in enumerate(facts):
            component = resolved_components[idx]
            await self._link_source(component, doc, fact)
            retained_component_ids.add(component.id)

            for rel in fact.relationships:
                await self._create_relationship_if_target_exists(model, component, rel)

        for link, component in existing_links:
            if component.id in retained_component_ids:
                continue
            await self.session.delete(link)
            await self.session.flush()
            await self._retire_if_orphaned(
                component,
                reason=(
                    f"Source document {doc.external_id} no longer supports "
                    f"{component.name}."
                ),
                retired_at=now,
            )

    async def retire_source_document(
        self,
        document: SourceDocument,
        *,
        reason: str,
        retired_at: datetime | None = None,
    ) -> int:
        retired_at = retired_at or datetime.now(timezone.utc)
        existing_links = await self._load_document_links(document.id)
        for link, component in existing_links:
            await self.session.delete(link)
            await self.session.flush()
            await self._retire_if_orphaned(
                component,
                reason=reason,
                retired_at=retired_at,
            )
        return len(existing_links)

    async def _resolve_component_for_fact(
        self,
        *,
        model: KnowledgeModel,
        fact: ExtractedFact,
        doc: SourceDocument,
        observed_at: datetime,
    ) -> tuple[Component, bool]:
        """Resolve or create a component for a fact.

        Returns ``(component, needs_embedding)`` where ``needs_embedding``
        is True when the component's embedding field is None and must be
        computed by the caller.
        """
        name = fact.name
        value = fact.value
        confidence = fact.confidence
        authority_weight = self._source_authority_weight(doc)
        active_components = await self._select_active_components(model.id, name)
        same_value = next(
            (component for component in active_components if component.value == value),
            None,
        )
        if same_value is not None:
            same_value.confidence = max(same_value.confidence, confidence)
            same_value.last_verified_at = observed_at
            same_value.is_stale = False
            same_value.authority_source = doc.source_url
            same_value.authority_weight = max(
                same_value.authority_weight,
                authority_weight,
            )
            needs_embed = same_value.embedding is None
            await self._sync_active_review_item(
                same_value,
                confidence=confidence,
                conflicting_with=[],
            )
            await self.session.flush()
            return same_value, needs_embed

        component = await self._create_component(
            model,
            name,
            value,
            confidence,
            doc,
            authority_weight,
            embedding=None,  # will be filled by batch embedding phase
        )
        strongest_active = max(
            active_components,
            key=lambda existing: (
                existing.authority_weight,
                existing.confidence,
                existing.valid_from,
            ),
            default=None,
        )
        authority_delta = (
            authority_weight - strongest_active.authority_weight
            if strongest_active is not None
            else 0.0
        )
        decisive_authority_gap = (
            strongest_active is not None
            and abs(authority_delta) >= settings.authority_conflict_auto_resolve_margin
        )
        should_activate = (
            strongest_active is None
            or authority_delta >= 0
        )

        if not should_activate and strongest_active is not None:
            component.valid_to = observed_at
            component.is_stale = True
            auto_rejected = decisive_authority_gap and authority_delta < 0
            await self._upsert_review_item(
                component,
                status="rejected" if auto_rejected else "needs_review",
                severity="medium" if auto_rejected else "high",
                kind="conflict",
                title=(
                    f"{component.name} was rejected by source-authority conflict"
                    if auto_rejected
                    else f"{component.name} conflicts with a higher-authority fact"
                ),
                summary=(
                    f'The extracted value "{component.value}" conflicts with the current '
                    f'authoritative value "{strongest_active.value}".'
                ),
                confidence=confidence,
                rationale=(
                    f"Incoming source authority {authority_weight:.2f} was lower than the "
                    f"current active authority {strongest_active.authority_weight:.2f}, "
                    + (
                        "so the new fact was automatically rejected."
                        if auto_rejected
                        else "so the new fact did not replace current truth."
                    )
                ),
                suggested_action=(
                    "No action needed unless the lower-authority source should override current truth."
                    if auto_rejected
                    else "Review the conflicting source and decide whether to promote or reject it."
                ),
            )
            await self.session.flush()
            return component, True

        for previous in active_components:
            await self._supersede_component(
                previous,
                successor=component,
                reason=(
                    f"{name} changed from {previous.value!r} to {value!r} "
                    f"based on source document {doc.external_id}."
                ),
                superseded_at=observed_at,
            )

        await self._sync_active_review_item(
            component,
            confidence=confidence,
            conflicting_with=[] if decisive_authority_gap else active_components,
        )
        await self.session.flush()
        return component, True

    async def _sync_active_review_item(
        self,
        component: Component,
        *,
        confidence: float,
        conflicting_with: list[Component],
    ) -> None:
        if conflicting_with:
            title = f"{component.name} changed across sources"
            summary = (
                f'The latest extracted value is "{component.value}", but a prior active fact '
                f"was superseded during ingestion and still needs human confirmation."
            )
            await self._upsert_review_item(
                component,
                status="needs_review",
                severity="high",
                kind="conflict",
                title=title,
                summary=summary,
                confidence=confidence,
                rationale=(
                    f"{component.name} replaced an earlier active fact during ingestion. "
                    "A human should confirm that the newest higher-authority or later fact "
                    "is canonical."
                ),
                suggested_action=(
                    "Confirm whether the latest value should remain active or mark it superseded."
                ),
            )
            return

        if confidence < self._LOW_CONFIDENCE_THRESHOLD:
            severity = (
                "high" if confidence < self._HIGH_RISK_CONFIDENCE_THRESHOLD else "medium"
            )
            await self._upsert_review_item(
                component,
                status="needs_review",
                severity=severity,
                kind="low_confidence",
                title=f"{component.name} extracted with low confidence",
                summary=(
                    f'The extracted value "{component.value}" still needs human review '
                    "before it should be treated as reliable truth."
                ),
                confidence=confidence,
                rationale=(
                    f"Extractor confidence {confidence:.2f} is below the "
                    f"{self._LOW_CONFIDENCE_THRESHOLD:.2f} review threshold."
                ),
                suggested_action="Confirm the canonical value or supersede this fact.",
            )
            return

        await self._resolve_pending_review_item(component)

    async def _resolve_pending_review_item(self, component: Component) -> None:
        item = await self._get_review_item(component.id)
        if item is None or item.status != "needs_review":
            return
        if item.kind not in {"conflict", "low_confidence"}:
            return

        previous_status = item.status
        item.status = "approved"
        item.summary = f"{component.name} no longer requires review."
        item.rationale = (
            "A later ingestion pass resolved the previously flagged trust issue."
        )
        item.suggested_action = "No action needed."
        await self.session.flush()
        await self._record_decision(
            item,
            previous_status=previous_status,
            new_status="approved",
            note="Auto-resolved by ingestion pipeline — trust issue no longer applies.",
        )

    async def _supersede_component(
        self,
        component: Component,
        *,
        successor: Component | None,
        reason: str,
        superseded_at: datetime,
    ) -> None:
        if component.valid_to is None:
            component.valid_to = superseded_at
        component.is_stale = True
        if successor is not None:
            component.superseded_by_id = successor.id
            await self._upsert_supersedes_relationship(
                successor,
                component,
                description=reason,
            )
        await self._retire_component_relationships(
            component,
            retired_at=superseded_at,
        )

        await self._upsert_review_item(
            component,
            status="superseded",
            severity="low",
            kind="superseded_fact",
            title=f"{component.name} is now historical",
            summary=(
                f'The fact "{component.value}" has been superseded by a newer extraction.'
                if successor is not None
                else f'The fact "{component.value}" is no longer supported by the source.'
            ),
            confidence=component.confidence,
            rationale=reason,
            suggested_action=(
                "No action needed unless the historical fact is still being cited."
            ),
        )

    async def _retire_if_orphaned(
        self,
        component: Component,
        *,
        reason: str,
        retired_at: datetime,
    ) -> None:
        has_sources = await self.session.scalar(
            select(ComponentSource.component_id)
            .where(ComponentSource.component_id == component.id)
            .limit(1)
        )
        if has_sources is not None:
            return
        await self._supersede_component(
            component,
            successor=None,
            reason=reason,
            superseded_at=retired_at,
        )

    async def _retire_component_relationships(
        self,
        component: Component,
        *,
        retired_at: datetime,
    ) -> None:
        relationships = await self.session.scalars(
            select(Relationship).where(
                Relationship.valid_to.is_(None),
                Relationship.relationship_type != RelationshipType.SUPERSEDES,
                or_(
                    Relationship.source_component_id == component.id,
                    Relationship.target_component_id == component.id,
                ),
            )
        )
        for relationship in relationships:
            relationship.valid_to = retired_at
        await self.session.flush()

    async def _upsert_supersedes_relationship(
        self,
        successor: Component,
        predecessor: Component,
        *,
        description: str,
    ) -> None:
        relationship = await self.session.scalar(
            select(Relationship).where(
                Relationship.source_component_id == successor.id,
                Relationship.target_component_id == predecessor.id,
                Relationship.relationship_type == RelationshipType.SUPERSEDES,
            )
        )
        if relationship is None:
            relationship = Relationship(
                source_component_id=successor.id,
                target_component_id=predecessor.id,
                relationship_type=RelationshipType.SUPERSEDES,
                confidence=1.0,
                description=description,
            )
            self.session.add(relationship)
        else:
            relationship.confidence = 1.0
            relationship.description = description
        await self.session.flush()

    async def _upsert_review_item(
        self,
        component: Component,
        *,
        status: str,
        severity: str,
        kind: str,
        title: str,
        summary: str,
        confidence: float | None,
        rationale: str | None,
        suggested_action: str | None,
    ) -> None:
        item = await self._get_review_item(component.id)
        if item is None:
            item = ReviewItem(
                component_id=component.id,
                status=status,
                severity=severity,
                kind=kind,
                title=title,
                summary=summary,
                confidence=confidence,
                rationale=rationale,
                suggested_action=suggested_action,
            )
            self.session.add(item)
            await self.session.flush()
            await self._record_decision(
                item,
                previous_status=None,
                new_status=status,
                note=f"Created by ingestion pipeline ({kind}).",
            )
            return

        if item.status not in {"needs_review", "superseded"} and status == "needs_review":
            return

        previous_status = item.status
        item.status = status
        item.severity = severity
        item.kind = kind
        item.title = title
        item.summary = summary
        item.confidence = confidence
        item.rationale = rationale
        item.suggested_action = suggested_action
        await self.session.flush()
        if previous_status != status:
            await self._record_decision(
                item,
                previous_status=previous_status,
                new_status=status,
                note=f"Transition by ingestion pipeline ({kind}).",
            )

    async def _record_decision(
        self,
        item: ReviewItem,
        *,
        previous_status: str | None,
        new_status: str,
        note: str | None,
    ) -> None:
        """Record a ReviewDecision for audit trail."""
        self.session.add(
            ReviewDecision(
                review_item_id=item.id,
                previous_status=previous_status,
                new_status=new_status,
                actor_type="system",
                note=note,
            )
        )
        await self.session.flush()

    async def _get_review_item(self, component_id: UUID) -> ReviewItem | None:
        return await self.session.scalar(
            select(ReviewItem).where(ReviewItem.component_id == component_id)
        )

    async def _select_active_components(
        self,
        model_id: UUID,
        name: str,
    ) -> list[Component]:
        result = await self.session.scalars(
            select(Component)
            .where(
                Component.model_id == model_id,
                Component.name == name,
                Component.valid_to.is_(None),
            )
            .order_by(Component.valid_from.desc(), Component.id.desc())
        )
        return list(result)

    def _source_authority_weight(self, doc: SourceDocument) -> float:
        metadata = doc.metadata_json or {}
        explicit = metadata.get("authority_weight")
        if isinstance(explicit, (int, float)):
            return max(0.0, min(float(explicit), 1.0))
        return self._CONNECTOR_AUTHORITY_WEIGHTS.get(doc.connector_type, 0.5)

    async def _load_document_links(
        self,
        document_id: UUID,
    ) -> list[tuple[ComponentSource, Component]]:
        rows = await self.session.execute(
            select(ComponentSource, Component)
            .join(Component, ComponentSource.component_id == Component.id)
            .where(ComponentSource.source_document_id == document_id)
        )
        return list(rows.all())

    @staticmethod
    def _collapse_facts(facts: list[ExtractedFact]) -> list[ExtractedFact]:
        """Deduplicate by name — last writer wins within the same document."""
        latest_by_name: dict[str, ExtractedFact] = {}
        for fact in facts:
            latest_by_name[fact.name] = fact
        return list(latest_by_name.values())
