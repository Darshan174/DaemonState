from __future__ import annotations

import logging
import json
import re
from datetime import datetime

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Component, Relationship, SourceDocument
from app.agents.semantic_linker import SemanticRelationshipLinker
from app.services.ingest import IngestionService
from app.services.workspace_scope import (
    filter_components_for_workspace,
    filter_source_documents_for_workspace,
    workspace_connector_types,
)

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

    async def run(
        self,
        limit: int = 100,
        api_key: str | None = None,
        model: str | None = None,
        workspace_id: str | None = None,
    ) -> dict:
        started_at = datetime.utcnow()

        extractor = None
        if api_key or model:
            from app.processing.extractor import Extractor
            extractor = Extractor(api_key=api_key, model=model)
            ingestor = IngestionService(self.session, extractor=extractor)
        else:
            ingestor = self._ingestor

        workspace_scope: tuple[str, set[str]] | None = None
        pending_stmt = (
            select(SourceDocument)
            .where(SourceDocument.processed_at.is_(None))
            .order_by(SourceDocument.ingested_at.desc())
        )
        if workspace_id:
            workspace_scope = await workspace_connector_types(self.session, workspace_id)
            pending_candidates = list(await self.session.scalars(pending_stmt))
            pending = filter_source_documents_for_workspace(
                pending_candidates,
                workspace_scope[0],
                workspace_scope[1],
            )[:limit]
        else:
            pending = list(await self.session.scalars(pending_stmt.limit(limit)))

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

        relationships_inferred = await self._infer_deterministic_relationships(workspace_scope)
        relationships_inferred += await SemanticRelationshipLinker(
            self.session,
            threshold=0.84,
            max_candidates=250,
            require_cross_source_type=True,
            workspace_scope=workspace_scope,
        ).create_relationships(limit=100)
        relationships_inferred += await self._infer_cross_doc_relationships(workspace_scope)
        await self.session.commit()

        if workspace_scope:
            scoped_components = list(await self.session.scalars(
                select(Component)
                .options(selectinload(Component.source_document))
            ))
            scoped_components = filter_components_for_workspace(
                scoped_components,
                workspace_scope[0],
                workspace_scope[1],
            )
            component_ids = {component.id for component in scoped_components}
            total_components = len(scoped_components)
            if component_ids:
                total_relationships = await self.session.scalar(
                    select(func.count(Relationship.id)).where(
                        Relationship.source_component_id.in_(component_ids),
                        Relationship.target_component_id.in_(component_ids),
                    )
                ) or 0
            else:
                total_relationships = 0
            pending_after_candidates = list(await self.session.scalars(
                select(SourceDocument).where(SourceDocument.processed_at.is_(None))
            ))
            pending_after = len(filter_source_documents_for_workspace(
                pending_after_candidates,
                workspace_scope[0],
                workspace_scope[1],
            ))
        else:
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

    async def _infer_cross_doc_relationships(
        self,
        workspace_scope: tuple[str, set[str]] | None = None,
    ) -> int:
        components = list(await self.session.scalars(
            select(Component)
            .options(selectinload(Component.source_document))
            .where(Component.status == "active")
        ))
        if workspace_scope:
            components = filter_components_for_workspace(
                components,
                workspace_scope[0],
                workspace_scope[1],
            )
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
                        origin="ai_proposed",
                    ))
                    existing_pairs.add((comp.id, other.id))
                    inferred += 1

                    if inferred >= 300:
                        return inferred

        return inferred

    async def _infer_deterministic_relationships(
        self,
        workspace_scope: tuple[str, set[str]] | None = None,
    ) -> int:
        components = list(await self.session.scalars(
            select(Component)
            .options(selectinload(Component.source_document))
            .where(Component.status.in_(["active", "needs_review", "proposed"]))
        ))
        if workspace_scope:
            components = filter_components_for_workspace(
                components,
                workspace_scope[0],
                workspace_scope[1],
            )
        if not components:
            return 0

        existing = {
            (r.source_component_id, r.target_component_id, r.relationship_type)
            for r in await self.session.scalars(select(Relationship))
        }

        issues: dict[tuple[str, int], Component] = {}
        pull_requests: list[tuple[tuple[str, int], Component]] = []

        for component in components:
            identity = _github_component_identity(component)
            if identity is None:
                continue
            kind, repo, number = identity
            key = (repo, number)
            if kind == "issue":
                issues[key] = component
            elif kind == "pull_request":
                pull_requests.append((key, component))

        inferred = 0
        for key, pr_component in pull_requests:
            issue_component = issues.get(key)
            if issue_component is None or issue_component.id == pr_component.id:
                continue
            rel_key = (pr_component.id, issue_component.id, "part_of")
            if rel_key in existing:
                continue

            repo, number = key
            self.session.add(Relationship(
                source_component_id=pr_component.id,
                target_component_id=issue_component.id,
                relationship_type="part_of",
                confidence=1.0,
                evidence=f"GitHub metadata: PR #{number} and issue thread #{number} are the same item in {repo}.",
                origin="deterministic",
            ))
            existing.add(rel_key)
            inferred += 1

        return inferred


def _github_component_identity(component: Component) -> tuple[str, str, int] | None:
    doc = component.source_document
    if doc is None:
        return None

    metadata = _parse_metadata(doc.metadata_json)
    raw = " ".join([
        doc.source_type or "",
        str(metadata.get("source_type") or ""),
        str(metadata.get("item_type") or ""),
        component.fact_type or "",
        component.name or "",
    ]).lower()

    if "github" not in raw and doc.source_type not in {"github", "github_issue", "github_pr"}:
        return None

    kind = None
    if "pull_request" in raw or "github_pr" in raw or re.search(r"\bpr\s*#", component.name or "", re.I):
        kind = "pull_request"
    elif "issue" in raw or "github_issue" in raw:
        kind = "issue"
    if kind is None:
        return None

    repo = (
        metadata.get("repo_full_name")
        or metadata.get("repository")
        or metadata.get("repo")
        or ""
    )
    if not repo:
        return None

    raw_number = (
        metadata.get("number")
        or metadata.get("pr_number")
        or metadata.get("issue_number")
    )
    if raw_number is None:
        match = re.search(r"#(\d+)", component.name or "")
        raw_number = match.group(1) if match else None
    try:
        number = int(raw_number)
    except (TypeError, ValueError):
        return None

    return kind, str(repo), number


def _parse_metadata(raw: str | dict | None) -> dict:
    if isinstance(raw, dict):
        return raw
    if not raw or raw == "{}":
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}
