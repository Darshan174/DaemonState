from __future__ import annotations

import json
import re
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

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
from app.services.extraction_quality import (
    extracted_fact_dedupe_key,
    extracted_fact_rejection_reason,
)
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
    extract_local_repository,
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
            "relationships_rejected_missing_evidence": 0,
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
            "relationships_rejected_missing_evidence": 0,
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
        deterministic_empty_is_final = doc.source_type == "agent_run_observation"
        extraction_method = "deterministic" if facts else "fallback"
        if not facts and not deterministic_empty_is_final:
            facts_list = await self._extractor.extract(doc.content, metadata)
            facts = facts_list
            extraction_method = "llm_or_regex"
            self.last_extraction_error = getattr(self._extractor, "last_error", None)
            self.last_extraction_warnings = list(getattr(self._extractor, "last_warnings", []) or [])
            self.last_extraction_report = getattr(self._extractor, "last_report", None)
        if isinstance(facts, list):
            facts = [f for f in facts if isinstance(f, ExtractedFact)]
        accepted_facts: list[ExtractedFact] = []
        rejection_counts: dict[str, int] = {}
        seen_facts: dict[tuple[str, str, str], ExtractedFact] = {}
        for fact in facts or []:
            reason = extracted_fact_rejection_reason(fact, source_type=doc.source_type)
            fact_key = extracted_fact_dedupe_key(fact)
            if reason is None and fact_key in seen_facts:
                existing_fact = seen_facts[fact_key]
                existing_relationships = {
                    (
                        relationship.target_name,
                        relationship.relationship_type,
                        relationship.evidence,
                    )
                    for relationship in existing_fact.relationships
                }
                existing_fact.relationships.extend(
                    relationship for relationship in fact.relationships
                    if (
                        relationship.target_name,
                        relationship.relationship_type,
                        relationship.evidence,
                    ) not in existing_relationships
                )
                existing_fact.confidence = max(existing_fact.confidence, fact.confidence)
                if not existing_fact.excerpt and fact.excerpt:
                    existing_fact.excerpt = fact.excerpt
                if not existing_fact.provenance and fact.provenance:
                    existing_fact.provenance = fact.provenance
                reason = "duplicate"
            if reason is not None:
                rejection_counts[reason] = rejection_counts.get(reason, 0) + 1
                continue
            seen_facts[fact_key] = fact
            accepted_facts.append(fact)
        facts = accepted_facts
        self.last_extraction_report = evaluate_extraction_quality(facts)
        self.last_extraction_report.rejected_fact_count = sum(rejection_counts.values())
        self.last_extraction_report.rejection_reason_counts = rejection_counts
        if rejection_counts:
            rejection_summary = ", ".join(
                f"{reason}={count}" for reason, count in sorted(rejection_counts.items())
            )
            self.last_extraction_warnings.append(
                f"Rejected derived semantic facts: {rejection_summary}"
            )
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
                origin = _determine_origin(
                    doc.source_type,
                    rel,
                    extraction_method=extraction_method,
                )
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

        if doc.source_type == "local_repository":
            return extract_local_repository(doc.content, metadata)
        if doc.source_type == "agent_run_observation":
            return self._extract_runtime_observation(doc, metadata)

        return []

    def _extract_runtime_observation(
        self,
        doc: SourceDocument,
        metadata: dict,
    ) -> list[ExtractedFact]:
        """Project only explicitly structured durable runtime observations."""
        event_type = str(metadata.get("event_type") or "").strip().lower()
        payload = metadata.get("payload")
        if not isinstance(payload, dict):
            payload = {}
        run_id = str(metadata.get("run_id") or payload.get("run_id") or "unknown")
        content = str(payload.get("content") or "").strip()
        files = [str(item) for item in payload.get("files") or [] if str(item).strip()]
        provenance = f"agent_run:{run_id};source_document:{doc.id}"
        excerpt = doc.content[:2000]

        if event_type == "verification":
            command = str(payload.get("command") or "").strip()
            exit_code = payload.get("exit_code")
            if not command or not isinstance(exit_code, int) or isinstance(exit_code, bool):
                return []
            state = "passed" if exit_code == 0 else "failed"
            return [ExtractedFact(
                model_name="Metric",
                name=f"Verification: {command[:160]}",
                value=f"{command} {state} with exit code {exit_code}.",
                fact_type="metric",
                confidence=0.99,
                temporal="current",
                provenance=provenance,
                excerpt=excerpt,
            )]
        if event_type == "blocker":
            severity = str(payload.get("severity") or "").strip().lower()
            if not content or not severity:
                return []
            return [ExtractedFact(
                model_name="Risk",
                name=f"Blocker: {content[:160]}",
                value=f"{content} Severity: {severity}.",
                fact_type="blocker",
                confidence=0.98,
                temporal="current",
                provenance=provenance,
                excerpt=excerpt,
            )]
        if event_type == "decision":
            decision = str(payload.get("decision") or content).strip()
            if not decision:
                return []
            return [ExtractedFact(
                model_name="Decision",
                name=f"Decision: {decision[:160]}",
                value=decision,
                fact_type="decision",
                confidence=0.95,
                temporal="current",
                provenance=provenance,
                excerpt=excerpt,
            )]
        if event_type == "patch_summary":
            if not content or not files:
                return []
            return [ExtractedFact(
                model_name="Agent Session",
                name=f"Observed patch for run {run_id}",
                value=f"{content} Changed files: {', '.join(files)}.",
                fact_type="observed_change",
                confidence=0.98,
                temporal="current",
                provenance=provenance,
                excerpt=excerpt,
            )]
        if event_type == "outcome":
            status = str(payload.get("status") or "").strip().lower()
            if not content or status not in {"completed", "failed", "blocked", "cancelled"}:
                return []
            return [ExtractedFact(
                model_name="Agent Session",
                name=f"Run outcome: {run_id}",
                value=f"{status}: {content}",
                fact_type="run_outcome",
                confidence=0.99,
                temporal="current",
                provenance=provenance,
                excerpt=excerpt,
            )]
        if event_type == "blocker_resolution":
            resolves = str(payload.get("resolves_event_key") or "").strip()
            if not content or not resolves:
                return []
            return [ExtractedFact(
                model_name="Risk",
                name=f"Blocker resolution: {resolves}",
                value=content,
                fact_type="risk",
                confidence=0.98,
                temporal="current",
                provenance=provenance,
                excerpt=excerpt,
            )]
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
        source_document = (
            await self.session.get(SourceDocument, source.source_document_id)
            if source.source_document_id else None
        )
        github_reference_scope = _github_reference_scope(source_document, target_name)
        github_reference_scoped = github_reference_scope is not None
        if github_reference_scoped:
            target = await self._resolve_github_reference_target(
                scope=github_reference_scope,
                source=source,
                workspace_id=workspace_id,
                active_statuses=active_statuses,
            )

        if target is None and not github_reference_scoped and target_identity_key:
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

        if target is None and not github_reference_scoped:
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

        if target is None and not github_reference_scoped and target_identity_key:
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

        if target is None and not github_reference_scoped:
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

        if target is None and not github_reference_scoped:
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

        if target is None and not github_reference_scoped:
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

        evidence = str(getattr(rel, "evidence", None) or "").strip()
        if not evidence:
            self.last_projection_report["relationships_rejected_missing_evidence"] += 1
            return

        if target is None:
            await self._record_unresolved_relationship(
                source=source,
                target_name=target_name,
                target_identity_key=target_identity_key,
                relationship_type=rel_type,
                confidence=confidence,
                evidence=evidence,
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

        resolved_origin = canonical_origin(origin)
        relationship_status = (
            "proposed" if resolved_origin in {"ai_proposed", "proposed"} else "active"
        )

        self.session.add(Relationship(
            source_component_id=source.id,
            target_component_id=target.id,
            relationship_type=rel_type,
            confidence=confidence,
            evidence=evidence,
            origin=resolved_origin,
            status=relationship_status,
        ))
        await self.session.flush()

    async def _resolve_github_reference_target(
        self,
        *,
        scope: tuple[str, str, int],
        source: Component,
        workspace_id: UUID | None,
        active_statuses: list[str],
    ) -> Component | None:
        repo_full_name, target_kind, target_number = scope
        candidates = list(await self.session.scalars(
            _scope_component_query(
                select(Component)
                .options(selectinload(Component.source_document))
                .where(
                    Component.id != source.id,
                    Component.status.in_(active_statuses),
                ),
                workspace_id,
            ).order_by(Component.confidence.desc(), Component.id)
        ))
        matches: list[Component] = []
        for candidate in candidates:
            metadata = _parse_metadata(
                candidate.source_document.metadata_json
                if candidate.source_document else "{}"
            )
            candidate_kind = resolve_github_item_type(
                candidate.source_document.source_type if candidate.source_document else None,
                metadata,
            )
            expected_kind = "github_pr" if target_kind == "pr" else "github_issue"
            if candidate_kind != expected_kind:
                continue
            if str(metadata.get("repo_full_name") or "").casefold() != repo_full_name.casefold():
                continue
            try:
                candidate_number = int(metadata.get("number"))
            except (TypeError, ValueError):
                continue
            if candidate_number != target_number:
                continue
            root_types = {"pr", "pull_request"} if target_kind == "pr" else {"issue"}
            if str(candidate.fact_type or "").lower() not in root_types:
                continue
            matches.append(candidate)
        return matches[0] if len(matches) == 1 else None

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


def _determine_origin(
    source_type: str,
    rel,
    *,
    extraction_method: str = "deterministic",
) -> str:
    source_type = (source_type or "").strip().lower()
    explicit_origin = canonical_origin(getattr(rel, "origin", None))
    if getattr(rel, "origin", None) and explicit_origin in {
        "deterministic", "extracted", "ai_proposed", "human_verified", "proposed",
    }:
        return explicit_origin
    deterministic_types = {
        "solves", "fixes", "created_from", "part_of", "generated_by_agent",
        "implemented_in", "implements", "duplicates", "supersedes", "touches_file",
        "resolved_by", "discussed_in",
    }
    rel_type = canonical_relationship_type(getattr(rel, "relationship_type", "related_to"))
    if extraction_method == "deterministic" and rel_type in deterministic_types:
        return "deterministic"
    if extraction_method == "llm_or_regex":
        return "ai_proposed"
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


def _github_reference_scope(
    source_document: SourceDocument | None,
    target_name: str,
) -> tuple[str, str, int] | None:
    qualified_match = re.match(
        r"^(Issue|PR)\s+([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)#(\d+)\b",
        target_name,
        re.I,
    )
    bare_match = re.match(r"^(Issue|PR)\s+#(\d+)\b", target_name, re.I)
    match = qualified_match or bare_match
    if match is None or source_document is None:
        return None
    if qualified_match:
        repo_full_name = qualified_match.group(2)
        target_kind = qualified_match.group(1).lower()
        target_number = int(qualified_match.group(3))
    else:
        metadata = _parse_metadata(source_document.metadata_json)
        repo_full_name = str(metadata.get("repo_full_name") or "").strip()
        target_kind = bare_match.group(1).lower()
        target_number = int(bare_match.group(2))
    if not repo_full_name:
        return None
    return repo_full_name, target_kind, target_number
