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
        github_targets: list[tuple[str, str, int, Component]] = []
        document_targets = _document_reference_targets(components)
        slack_hubs = _slack_channel_hubs(components)

        for component in components:
            identity = _github_component_identity(component)
            if identity is None:
                continue
            kind, repo, number = identity
            github_targets.append((kind, repo, number, component))
            key = (repo, number)
            if kind == "issue":
                issues[key] = component
            elif kind == "pull_request":
                pull_requests.append((key, component))

        inferred = 0
        inferred += self._infer_slack_github_references(components, github_targets, existing)
        inferred += self._infer_slack_document_references(components, document_targets, existing)
        inferred += self._infer_github_slack_references(components, slack_hubs, existing)
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

    def _infer_github_slack_references(
        self,
        components: list[Component],
        slack_hubs: list[tuple[Component, str]],
        existing: set[tuple],
    ) -> int:
        inferred = 0
        if not slack_hubs:
            return inferred

        for github_component in components:
            if _github_component_identity(github_component) is None:
                continue

            ref = _slack_reference_in_component(github_component, slack_hubs)
            if ref is None:
                continue

            target, matched_text, confidence = ref
            if target.id == github_component.id:
                continue
            if target.source_document_id == github_component.source_document_id:
                continue

            rel_key = (github_component.id, target.id, "mentions")
            if rel_key in existing:
                continue

            self.session.add(Relationship(
                source_component_id=github_component.id,
                target_component_id=target.id,
                relationship_type="mentions",
                confidence=confidence,
                evidence=f"GitHub source explicitly referenced Slack '{matched_text}'.",
                origin="deterministic",
            ))
            existing.add(rel_key)
            inferred += 1

        return inferred

    def _infer_slack_document_references(
        self,
        components: list[Component],
        document_targets: list[tuple[Component, list[dict]]],
        existing: set[tuple],
    ) -> int:
        inferred = 0
        if not document_targets:
            return inferred

        for slack_component in components:
            if not _is_slack_component(slack_component):
                continue

            text_lower = _component_reference_text(slack_component).lower()
            if not text_lower.strip():
                continue

            for target, identifiers in document_targets:
                if target.id == slack_component.id:
                    continue
                if target.source_document_id == slack_component.source_document_id:
                    continue
                rel_key = (slack_component.id, target.id, "mentions")
                if rel_key in existing:
                    continue

                matched_identifier = next(
                    (
                        identifier for identifier in identifiers
                        if identifier["value"].lower() in text_lower
                    ),
                    None,
                )
                if matched_identifier is None:
                    continue

                self.session.add(Relationship(
                    source_component_id=slack_component.id,
                    target_component_id=target.id,
                    relationship_type="mentions",
                    confidence=matched_identifier["confidence"],
                    evidence=(
                        f"Slack source explicitly referenced document "
                        f"{matched_identifier['kind']} '{matched_identifier['value']}'."
                    ),
                    origin="deterministic",
                ))
                existing.add(rel_key)
                inferred += 1

        return inferred

    def _infer_slack_github_references(
        self,
        components: list[Component],
        github_targets: list[tuple[str, str, int, Component]],
        existing: set[tuple],
    ) -> int:
        inferred = 0
        if not github_targets:
            return inferred

        for slack_component in components:
            if not _is_slack_component(slack_component):
                continue

            for ref in _github_references_in_component(slack_component):
                for target in _matching_github_targets(ref, github_targets):
                    if target.id == slack_component.id:
                        continue
                    if target.source_document_id == slack_component.source_document_id:
                        continue
                    rel_key = (slack_component.id, target.id, "mentions")
                    if rel_key in existing:
                        continue

                    self.session.add(Relationship(
                        source_component_id=slack_component.id,
                        target_component_id=target.id,
                        relationship_type="mentions",
                        confidence=ref["confidence"],
                        evidence=(
                            f"Slack source explicitly referenced GitHub {ref['label']} "
                            f"'{ref['matched_text']}'."
                        ),
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


def _is_slack_component(component: Component) -> bool:
    doc = component.source_document
    if doc is None:
        return False
    metadata = _parse_metadata(doc.metadata_json)
    raw = " ".join([
        doc.source_type or "",
        str(metadata.get("source_type") or ""),
    ]).lower()
    return "slack" in raw


def _component_reference_text(component: Component) -> str:
    doc = component.source_document
    metadata = _parse_metadata(doc.metadata_json if doc else None)
    return "\n".join(
        str(value or "")
        for value in (
            component.name,
            component.value,
            component.excerpt,
            component.provenance,
            doc.content if doc else "",
            metadata.get("permalink"),
            metadata.get("source_url"),
            metadata.get("url"),
            metadata.get("title"),
            metadata.get("name"),
            metadata.get("source_path"),
            metadata.get("file_path"),
            metadata.get("filename"),
        )
    )


def _github_references_in_component(component: Component) -> list[dict]:
    text = _component_reference_text(component)
    refs: list[dict] = []
    seen: set[tuple[str | None, str | None, int, str]] = set()

    def add_ref(
        *,
        kind: str | None,
        repo: str | None,
        number: int,
        matched_text: str,
        confidence: float,
    ) -> None:
        normalized_repo = repo.strip() if repo else None
        key = (kind, normalized_repo, number, matched_text)
        if key in seen:
            return
        seen.add(key)
        label = f"{normalized_repo or ''} {kind or 'item'} #{number}".strip()
        refs.append({
            "kind": kind,
            "repo": normalized_repo,
            "number": number,
            "matched_text": matched_text.strip(),
            "confidence": confidence,
            "label": label,
        })

    for match in re.finditer(
        r"https?://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/(issues|pull)/(\d+)",
        text,
        re.IGNORECASE,
    ):
        path_kind = match.group(2).lower()
        add_ref(
            kind="pull_request" if path_kind == "pull" else "issue",
            repo=match.group(1),
            number=int(match.group(3)),
            matched_text=match.group(0),
            confidence=0.98,
        )

    for match in re.finditer(
        r"\b([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)#(\d+)\b",
        text,
        re.IGNORECASE,
    ):
        add_ref(
            kind=None,
            repo=match.group(1),
            number=int(match.group(2)),
            matched_text=match.group(0),
            confidence=0.94,
        )

    for match in re.finditer(
        r"\b(issue|issues|pr|pull request|pull)\s*#(\d+)\b",
        text,
        re.IGNORECASE,
    ):
        raw_kind = match.group(1).lower()
        add_ref(
            kind="pull_request" if raw_kind in {"pr", "pull", "pull request"} else "issue",
            repo=None,
            number=int(match.group(2)),
            matched_text=match.group(0),
            confidence=0.9,
        )

    return refs


def _document_reference_targets(components: list[Component]) -> list[tuple[Component, list[dict]]]:
    targets: list[tuple[Component, list[dict]]] = []
    for component in components:
        if not _is_document_reference_target(component):
            continue
        identifiers = _document_reference_identifiers(component)
        if identifiers:
            targets.append((component, identifiers))
    return targets


def _is_document_reference_target(component: Component) -> bool:
    doc = component.source_document
    if doc is None:
        return False
    metadata = _parse_metadata(doc.metadata_json)
    raw = " ".join([
        doc.source_type or "",
        str(metadata.get("source_type") or ""),
        component.fact_type or "",
        component.name or "",
    ]).lower()
    if "slack" in raw or "github" in raw:
        return False
    document_source_types = {
        "local", "local_folder", "browser_upload", "paste", "gdrive", "notion",
    }
    return (
        doc.source_type in document_source_types
        or str(metadata.get("source_type") or "") in document_source_types
        or component.fact_type in {"document", "fact"}
    )


def _document_reference_identifiers(component: Component) -> list[dict]:
    doc = component.source_document
    metadata = _parse_metadata(doc.metadata_json if doc else None)
    candidates = [
        ("url", doc.source_url if doc else None, 0.96),
        ("url", metadata.get("source_url") or metadata.get("url") or metadata.get("web_url"), 0.96),
        ("title", metadata.get("title") or metadata.get("name"), 0.9),
        ("path", metadata.get("source_path") or metadata.get("file_path") or metadata.get("filename"), 0.88),
        ("external id", doc.external_id if doc else None, 0.86),
        ("component name", component.name, 0.84),
    ]

    identifiers: list[dict] = []
    seen: set[str] = set()
    for kind, raw_value, confidence in candidates:
        value = _clean_reference_identifier(raw_value)
        if not value or value.lower() in seen:
            continue
        if not _useful_document_identifier(kind, value):
            continue
        seen.add(value.lower())
        identifiers.append({"kind": kind, "value": value, "confidence": confidence})
    return identifiers


def _clean_reference_identifier(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _useful_document_identifier(kind: str, value: str) -> bool:
    lower = value.lower()
    if kind == "url":
        return lower.startswith(("http://", "https://")) and len(value) >= 12
    if len(value) < 8:
        return False
    if lower in {"document", "untitled", "source", "local", "paste"}:
        return False
    if kind == "component name" and lower.startswith(("document:", "slack:", "email:")):
        value = value.split(":", 1)[1].strip()
        return len(value) >= 8
    return bool(re.search(r"[A-Za-z]", value))


def _matching_github_targets(
    ref: dict,
    targets: list[tuple[str, str, int, Component]],
) -> list[Component]:
    ref_kind = ref.get("kind")
    ref_repo = ref.get("repo")
    ref_number = ref.get("number")
    candidates = [
        component
        for kind, repo, number, component in targets
        if number == ref_number
        and (ref_kind is None or kind == ref_kind)
        and (ref_repo is None or repo.lower() == str(ref_repo).lower())
    ]

    if ref_repo is None:
        unique_by_identity = {
            (kind, repo, number)
            for kind, repo, number, component in targets
            if component in candidates
        }
        if len(unique_by_identity) != 1:
            return []

    return candidates


def _slack_channel_hubs(components: list[Component]) -> list[tuple[Component, str]]:
    hubs: list[tuple[Component, str]] = []
    for component in components:
        if not _is_slack_component(component):
            continue
        channel = _slack_channel_name(component)
        if not channel:
            continue
        text = " ".join([component.name or "", component.value or ""]).lower()
        if "slack channel" not in text or "hub for messages" not in text:
            continue
        hubs.append((component, channel))
    return hubs


def _slack_reference_in_component(
    component: Component,
    slack_hubs: list[tuple[Component, str]],
) -> tuple[Component, str, float] | None:
    text = _component_reference_text(component)
    if not re.search(r"\bslack\b", text, re.IGNORECASE):
        return None

    text_lower = text.lower()
    explicit_matches = [
        (hub, channel)
        for hub, channel in slack_hubs
        if f"#{channel}".lower() in text_lower
        or re.search(rf"\b{re.escape(channel)}\b", text, re.IGNORECASE)
    ]
    if explicit_matches:
        hub, channel = explicit_matches[0]
        return hub, f"#{channel}", 0.94

    if len(slack_hubs) == 1:
        hub, channel = slack_hubs[0]
        return hub, "Slack", 0.86

    return None


def _slack_channel_name(component: Component) -> str | None:
    doc = component.source_document
    metadata = _parse_metadata(doc.metadata_json if doc else None)
    raw = metadata.get("channel_name")
    if not raw:
        match = re.search(r"Slack channel\s+#?([A-Za-z0-9_.-]+)", component.name or component.value or "", re.I)
        raw = match.group(1) if match else None
    channel = str(raw or "").strip().lstrip("#").lower()
    if not channel or not re.search(r"[a-z]", channel):
        return None
    return channel


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
