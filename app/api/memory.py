from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only, selectinload
from sqlalchemy.orm.attributes import set_committed_value

from app.api.dependencies import get_access_scope
from app.api.context_digest import _is_digest_noise_component
from app.database import get_db_session
from app.models import (
    ClaimRevision,
    Component,
    EvidenceSpan,
    MemoryReviewEvent,
    Relationship,
    SourceDocument,
    WorkCheckpoint,
    Workspace,
)
from app.services.access import AccessScope, source_access_predicate
from app.services.memory_trust import (
    assess_memory_trust,
    is_agent_source_type,
    is_remote_source,
)
from app.services.project_scope import (
    source_workspace_relevance,
    workspace_references,
    workspace_relevance,
)
from app.services.provider_freshness import (
    ProviderFreshnessStatus,
    load_provider_freshness,
)
from app.services.session_library import selected_session_selection
from app.services.workspace_goals import resolve_current_goal
from app.services.workspace_scope import (
    current_source_documents,
    filter_explicit_source_documents_for_workspace,
    metadata_dict,
)
from app.taxonomy import source_type_display
from app.time import utc_now


router = APIRouter()

_MEMORY_SOURCE_COLUMNS = (
    SourceDocument.id,
    SourceDocument.workspace_id,
    SourceDocument.source_type,
    SourceDocument.external_id,
    SourceDocument.content_sha256,
    SourceDocument.source_identity_sha256,
    SourceDocument.revision_number,
    SourceDocument.trust_zone,
    SourceDocument.source_created_at,
    SourceDocument.source_url,
    SourceDocument.metadata_json,
    SourceDocument.ingested_at,
    SourceDocument.processed_at,
)

MemorySectionId = Literal[
    "goal",
    "requirements",
    "decisions",
    "work",
    "blockers",
    "risks",
    "learnings",
    "deliveries",
    "unverified",
    "conflicts",
    "stale",
    "owners",
    "milestones",
    "resolved",
    "completed",
    "superseded",
    "dismissed",
    "revisions",
]
MemorySemanticSection = Literal[
    "goal",
    "requirements",
    "decisions",
    "work",
    "blockers",
    "risks",
    "learnings",
    "deliveries",
    "owners",
    "milestones",
]
MemoryScopeMode = Literal["agenda", "workspace"]
MemorySourceGroup = Literal[
    "all",
    "documents",
    "repository",
    "sessions",
    "integrations",
]
MemoryVerificationFilter = Literal[
    "all",
    "verified",
    "observed",
    "reported",
    "needs_review",
    "unavailable",
]
MemoryTemporalFilter = Literal["all", "current", "future", "past", "unknown"]

SECTION_ORDER: tuple[str, ...] = (
    "goal",
    "requirements",
    "decisions",
    "work",
    "blockers",
    "risks",
    "learnings",
    "deliveries",
    "unverified",
    "conflicts",
    "stale",
    "owners",
    "milestones",
    "resolved",
    "completed",
    "superseded",
    "dismissed",
    "revisions",
)
ACTIVE_SECTIONS = frozenset({
    "requirements", "decisions", "work", "blockers", "risks",
    "learnings", "deliveries",
})
REVIEW_SECTIONS = frozenset({"unverified", "conflicts"})
FRESHNESS_SECTIONS = frozenset({"stale"})
PEOPLE_SECTIONS = frozenset({"owners", "milestones"})
HISTORY_SECTIONS = frozenset({
    "resolved", "completed", "superseded", "dismissed", "revisions",
})
HISTORICAL_COMPONENT_STATUSES = frozenset({
    "resolved", "superseded", "rejected", "deprecated",
})
CURRENT_COMPONENT_STATUSES = frozenset({
    "active", "needs_review", "proposed", "stale", "verified", "contested",
})
FACT_ROUTES: dict[str, tuple[str, str]] = {
    "requirement": ("requirements", "Requirement"),
    "constraint": ("requirements", "Constraint"),
    "decision": ("decisions", "Decision"),
    "ai_decision": ("decisions", "Decision"),
    "assumption": ("decisions", "Assumption"),
    "alternative": ("decisions", "Alternative"),
    "task": ("work", "Task"),
    "action_item": ("work", "Task"),
    "ai_task": ("work", "Task"),
    "issue": ("work", "Issue"),
    "github_issue": ("work", "Issue"),
    "blocker": ("blockers", "Blocker"),
    "ai_blocker": ("blockers", "Blocker"),
    "risk": ("risks", "Risk"),
    "open_question": ("risks", "Open question"),
    "lesson": ("learnings", "Lesson"),
    "failed_attempt": ("learnings", "Failed attempt"),
    "changed_file": ("deliveries", "Changed file"),
    "commit_reference": ("deliveries", "Commit"),
    "pr": ("deliveries", "Pull request"),
    "github_pr": ("deliveries", "Pull request"),
    "release": ("deliveries", "Release"),
    "verification": ("deliveries", "Verification"),
    "test": ("deliveries", "Test"),
    "outcome": ("deliveries", "Outcome"),
    "run_outcome": ("deliveries", "Outcome"),
    "observed_change": ("deliveries", "Change"),
    "owner": ("owners", "Owner"),
    "milestone": ("milestones", "Milestone"),
    "pr_review_finding": ("risks", "Review finding"),
    "review_finding": ("risks", "Review finding"),
}
EXPLICIT_PREFIX_ROUTES: tuple[tuple[re.Pattern[str], tuple[str, str]], ...] = (
    (re.compile(r"^requirements?\s*:\s*", re.I), ("requirements", "Requirement")),
    (re.compile(r"^constraints?\s*:\s*", re.I), ("requirements", "Constraint")),
    (re.compile(r"^assumptions?\s*:\s*", re.I), ("decisions", "Assumption")),
    (re.compile(r"^(?:alternative|option)s?\s*:\s*", re.I), ("decisions", "Alternative")),
    (re.compile(r"^(?:lesson|learning|takeaway)s?\s*:\s*", re.I), ("learnings", "Lesson")),
    (re.compile(r"^open questions?\s*:\s*", re.I), ("risks", "Open question")),
    (re.compile(r"^(?:release|deployment)s?\s*:\s*", re.I), ("deliveries", "Release")),
    (re.compile(r"^(?:test|verification|check)s?\s*:\s*", re.I), ("deliveries", "Verification")),
    (re.compile(r"^(?:outcome|result)s?\s*:\s*", re.I), ("deliveries", "Outcome")),
    (re.compile(r"^owners?\s*:\s*", re.I), ("owners", "Owner")),
    (re.compile(r"^(?:milestone|deadline|target date)s?\s*:\s*", re.I), ("milestones", "Milestone")),
)


class MemorySource(BaseModel):
    label: str
    source_type: str
    document_id: str | None = None
    external_id: str | None = None
    url: str | None = None
    revision_number: int | None = None
    freshness: Literal["observed", "stale", "unknown", "not_remote"] = "unknown"


class MemoryEvidence(BaseModel):
    excerpt: str | None = None
    evidence_span_id: str | None = None
    start_char: int | None = None
    end_char: int | None = None
    text_sha256: str | None = None
    review_status: str
    stored_review_status: str | None = None
    trust_zone: str | None = None
    extraction_method: str | None = None
    exact: bool = False


class MemoryReviewSummary(BaseModel):
    action: str
    reviewed_by: str
    reason: str | None = None
    reviewed_at: datetime


class MemoryResolution(BaseModel):
    summary: str
    source: MemorySource | None = None
    evidence: MemoryEvidence | None = None
    occurred_at: datetime | None = None


class MemoryRecord(BaseModel):
    id: str
    section: MemorySectionId
    semantic_section: MemorySectionId
    kind: str
    title: str
    summary: str
    status: str
    verification: Literal[
        "verified", "observed", "reported", "needs_review", "unavailable"
    ]
    temporal: str = "unknown"
    origin: Literal[
        "workspace_goal", "component", "relationship", "source_metadata"
    ]
    source_group: Literal[
        "documents", "repository", "sessions", "integrations"
    ]
    relevance: str
    component_id: str | None = None
    source: MemorySource | None = None
    evidence: MemoryEvidence | None = None
    resolution: MemoryResolution | None = None
    explanation: str
    allowed_actions: list[Literal["confirm", "dismiss", "resolve", "supersede", "reopen"]]
    last_review: MemoryReviewSummary | None = None
    occurred_at: datetime | None = None
    first_observed_at: datetime | None = None
    last_observed_at: datetime | None = None
    occurrence_count: int = 1


class MemorySection(BaseModel):
    id: MemorySectionId
    total: int
    records: list[MemoryRecord]
    has_more: bool


class MemoryFacets(BaseModel):
    sections: dict[str, int]
    kinds: dict[str, int]
    source_groups: dict[str, int]
    verification: dict[str, int]
    temporal: dict[str, int]
    review_semantic_sections: dict[str, int]
    reviewable_semantic_sections: dict[str, int]
    stale_semantic_sections: dict[str, int]
    kinds_by_section: dict[str, dict[str, int]]


class ProjectMemoryResponse(BaseModel):
    workspace_id: str
    generated_at: datetime
    query: str
    selected_section: MemorySectionId | None = None
    selected_semantic_section: MemorySemanticSection | None = None
    current_goal: dict | None
    agenda: dict | None
    filters: dict[str, str | None]
    facets: MemoryFacets
    matches: int
    totals: dict[str, int]
    sections: list[MemorySection]
    scope: dict[str, Any]


async def _attach_remote_source_contents(
    session: AsyncSession,
    documents: list[SourceDocument],
) -> None:
    remote_documents = [
        document for document in documents if is_remote_source(document)
    ]
    if not remote_documents:
        return
    rows = await session.execute(
        select(SourceDocument.id, SourceDocument.content).where(
            SourceDocument.id.in_({
                document.id for document in remote_documents
            })
        )
    )
    contents = {source_id: content for source_id, content in rows}
    for document in remote_documents:
        set_committed_value(
            document,
            "content",
            contents.get(document.id) or "",
        )


@router.get("/context/memory", response_model=ProjectMemoryResponse)
async def get_project_memory(
    workspace_id: UUID,
    query: str = Query(default="", max_length=200),
    section: MemorySectionId | None = None,
    semantic_section: MemorySemanticSection | None = None,
    scope_mode: MemoryScopeMode = Query(default="agenda", alias="scope"),
    source_group: MemorySourceGroup = "all",
    verification: MemoryVerificationFilter = "all",
    temporal: MemoryTemporalFilter = "all",
    kind: str | None = Query(default=None, max_length=80),
    limit_per_section: int = Query(default=3, ge=1, le=500),
    session: AsyncSession = Depends(get_db_session),
    access_scope: AccessScope = Depends(get_access_scope),
) -> ProjectMemoryResponse:
    if not access_scope.allows_workspace(workspace_id):
        raise HTTPException(status_code=404, detail="Workspace not found")
    workspace = await session.get(Workspace, workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found")

    documents = list(await session.scalars(
        select(SourceDocument)
        .options(load_only(*_MEMORY_SOURCE_COLUMNS))
        .where(source_access_predicate(access_scope, workspace_id=workspace_id))
        .order_by(SourceDocument.ingested_at.desc(), SourceDocument.id.desc())
    ))
    documents = filter_explicit_source_documents_for_workspace(
        documents, str(workspace_id)
    )
    current_documents, _ = current_source_documents(documents)
    await _attach_remote_source_contents(session, current_documents)
    provider_freshness_by_source = await load_provider_freshness(
        session,
        current_documents,
    )
    current_document_ids = {item.id for item in current_documents}
    accessible_document_ids = {item.id for item in documents}
    selected_session = await selected_session_selection(session, workspace_id)
    selected_session_external_id = selected_session.get("external_id")
    selected_session_document = next(
        (
            item for item in current_documents
            if selected_session_external_id
            and item.external_id == selected_session_external_id
        ),
        None,
    )
    selected_session_document_id = (
        selected_session_document.id if selected_session_document is not None else None
    )

    components: list[Component] = []
    if accessible_document_ids:
        components = list(await session.scalars(
            select(Component)
            .options(
                selectinload(Component.source_document).load_only(
                    *_MEMORY_SOURCE_COLUMNS
                ),
                selectinload(Component.claim),
            )
            .where(
                Component.workspace_id == workspace_id,
                Component.source_document_id.in_(accessible_document_ids),
            )
            .order_by(Component.created_at.desc(), Component.id.desc())
        ))
    components = [
        item for item in components
        if (
            item.status in HISTORICAL_COMPONENT_STATUSES
            or (
                item.source_document_id in current_document_ids
                and item.status in CURRENT_COMPONENT_STATUSES
            )
        )
    ]

    repositories, paths, commits = await workspace_references(session, str(workspace_id))
    visible_components: list[Component] = []
    excluded_unknown_sessions = 0
    excluded_irrelevant_sessions = 0
    for component in components:
        if _is_digest_noise_component(component):
            continue
        source = component.source_document
        if source is None or not _agent_source(source.source_type):
            visible_components.append(component)
            continue
        if source.id == selected_session_document_id:
            visible_components.append(component)
            continue
        relevance = workspace_relevance(
            component,
            metadata_dict(source),
            repositories,
            paths,
            commits,
        )
        if relevance.status == "relevant":
            visible_components.append(component)
        elif relevance.status == "unknown":
            excluded_unknown_sessions += 1
        else:
            excluded_irrelevant_sessions += 1

    human_superseded_component_ids = set(await session.scalars(
        select(MemoryReviewEvent.component_id).where(
            MemoryReviewEvent.workspace_id == workspace_id,
            MemoryReviewEvent.action == "supersede",
        )
    ))
    semantic_superseded_component_ids = set(await session.scalars(
        select(Relationship.target_component_id).where(
            Relationship.relationship_type == "supersedes",
            Relationship.status.not_in(["rejected", "superseded"]),
        )
    ))

    def is_mechanical_source_supersession(item: Component) -> bool:
        return (
            item.status == "superseded"
            and item.id not in human_superseded_component_ids
            and item.id not in semantic_superseded_component_ids
        )

    collapsed_source_revision_components = sum(
        1 for item in visible_components if is_mechanical_source_supersession(item)
    )
    visible_components = [
        item
        for item in visible_components
        if not is_mechanical_source_supersession(item)
    ]

    evidence_by_component = await _evidence_by_component(
        session, visible_components
    )
    relationship_components = list(visible_components)
    (
        visible_components,
        occurrence_count_by_component,
        excluded_duplicate_claims,
        canonical_component_ids,
    ) = (
        _canonical_current_components(
            visible_components,
            evidence_by_component=evidence_by_component,
            provider_freshness_by_source=provider_freshness_by_source,
        )
    )
    visible_component_ids = {item.id for item in visible_components}
    evidence_by_component = {
        component_id: evidence
        for component_id, evidence in evidence_by_component.items()
        if component_id in visible_component_ids
    }
    reviews_by_component = await _latest_reviews_by_component(
        session, visible_components
    )
    component_by_id = {item.id: item for item in relationship_components}
    record_by_component_id: dict[UUID, dict[str, Any]] = {}
    records: list[dict[str, Any]] = []
    conflict_component_ids: set[UUID] = set()
    excluded_unconfirmable_agent_components = 0

    relationship_component_ids = {
        item.id for item in relationship_components
        if item.source_document_id in current_document_ids
        and item.status not in HISTORICAL_COMPONENT_STATUSES
    }
    relationships: list[Relationship] = []
    if relationship_component_ids:
        relationships = list(await session.scalars(
            select(Relationship)
            .where(
                Relationship.source_component_id.in_(relationship_component_ids),
                Relationship.target_component_id.in_(relationship_component_ids),
                Relationship.status.not_in(["rejected", "superseded"]),
            )
            .order_by(Relationship.created_at.desc(), Relationship.id.desc())
        ))
    for relationship in relationships:
        if (
            relationship.relationship_type in {"conflicts_with", "contradicts"}
            and relationship.status == "active"
            and relationship.origin in {"deterministic", "human_verified"}
        ):
            conflict_component_ids.update({
                canonical_component_ids.get(
                    relationship.source_component_id,
                    relationship.source_component_id,
                ),
                canonical_component_ids.get(
                    relationship.target_component_id,
                    relationship.target_component_id,
                ),
            })

    for component in visible_components:
        evidence = evidence_by_component.get(component.id)
        if (
            component.status not in HISTORICAL_COMPONENT_STATUSES
            and component.source_document is not None
            and _agent_source(component.source_document.source_type)
            and not assess_memory_trust(
                component,
                evidence,
                source=component.source_document,
            ).evidence_exact
        ):
            excluded_unconfirmable_agent_components += 1
            continue
        record = _component_record(
            component,
            evidence,
            reviews_by_component.get(component.id),
            conflict=component.id in conflict_component_ids,
            occurrence_count=occurrence_count_by_component.get(component.id, 1),
            provider_freshness=provider_freshness_by_source.get(
                component.source_document_id
            ),
        )
        if record is not None:
            records.append(record)
            record_by_component_id[component.id] = record
    for component_id, canonical_id in canonical_component_ids.items():
        canonical_record = record_by_component_id.get(canonical_id)
        if canonical_record is not None:
            record_by_component_id[component_id] = canonical_record

    resolved_blocker_ids = {
        component.id
        for component in visible_components
        if (
            component.status == "resolved"
            and (component.fact_type or "").lower() in {"blocker", "ai_blocker"}
        )
    }
    if resolved_blocker_ids:
        resolution_relationships = list(await session.scalars(
            select(Relationship)
            .where(
                Relationship.source_component_id.in_(resolved_blocker_ids),
                Relationship.target_component_id.in_(
                    set(canonical_component_ids) | visible_component_ids
                ),
                Relationship.relationship_type == "resolved_by",
                Relationship.status == "active",
                Relationship.origin.in_(["deterministic", "human_verified"]),
            )
            .order_by(Relationship.created_at.desc(), Relationship.id.desc())
        ))
        for relationship in resolution_relationships:
            blocker_record = record_by_component_id.get(
                relationship.source_component_id
            )
            resolution_record = record_by_component_id.get(
                relationship.target_component_id
            )
            if (
                blocker_record is None
                or resolution_record is None
                or blocker_record.get("resolution") is not None
            ):
                continue
            blocker_record["resolution"] = {
                "summary": _clean_text(relationship.evidence),
                "source": resolution_record.get("source"),
                "evidence": resolution_record.get("evidence"),
                "occurred_at": (
                    resolution_record.get("occurred_at")
                    or relationship.created_at
                ),
            }

    relationship_records, excluded_untrusted_relationships = _relationship_records(
        relationships,
        component_by_id,
        record_by_component_id,
        canonical_component_ids,
        provider_freshness_by_source=provider_freshness_by_source,
    )
    records.extend(relationship_records)
    records.extend(
        _source_metadata_records(
            current_documents,
            repositories,
            paths,
            commits,
            provider_freshness_by_source=provider_freshness_by_source,
        )
    )

    checkpoint_count = await _checkpoint_count(
        session,
        workspace_id,
        access_scope,
    )

    current_goal = await resolve_current_goal(
        session,
        workspace_id=workspace_id,
        allowed_component_ids=relationship_component_ids,
        allowed_source_document_ids=accessible_document_ids,
    )
    if current_goal is not None and current_goal.get("component_id"):
        try:
            goal_component_id = UUID(str(current_goal["component_id"]))
        except ValueError:
            goal_component_id = None
        if goal_component_id is not None:
            current_goal["component_id"] = str(
                canonical_component_ids.get(
                    goal_component_id,
                    goal_component_id,
                )
            )
    if current_goal is not None:
        records.append(_goal_record(current_goal))

    workspace_records = _dedupe_records(records)
    scoped_records, agenda, effective_scope = _apply_memory_scope(
        workspace_records,
        requested_scope=scope_mode,
        current_goal=current_goal,
        selected_session=selected_session,
        selected_session_document=selected_session_document,
        relationships=relationships,
        canonical_component_ids=canonical_component_ids,
    )
    workspace_record_count = len(workspace_records)
    agenda_record_count = len(scoped_records) if agenda is not None else 0
    records = scoped_records

    normalized_query = " ".join(query.split()).casefold()
    if normalized_query:
        records = [
            record for record in records
            if normalized_query in _record_search_text(record)
        ]
    normalized_kind = " ".join((kind or "").split()).casefold()
    records = [
        record for record in records
        if (
            (source_group == "all" or record["source_group"] == source_group)
            and (verification == "all" or record["verification"] == verification)
            and (temporal == "all" or record["temporal"] == temporal)
            and (
                semantic_section is None
                or record["semantic_section"] == semantic_section
            )
        )
    ]
    facet_records = (
        [record for record in records if record["section"] == section]
        if section is not None else records
    )
    facets = _memory_facets(facet_records)
    records = [
        record for record in records
        if (
            not normalized_kind
            or str(record.get("kind") or "").casefold() == normalized_kind
        )
    ]

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[record["section"]].append(record)
    for section_records in grouped.values():
        section_records.sort(key=_record_sort_key, reverse=True)

    sections: list[MemorySection] = []
    for section_id in SECTION_ORDER:
        section_records = grouped.get(section_id, [])
        include_records = section is None or section == section_id
        visible_records = section_records[:limit_per_section] if include_records else []
        sections.append(MemorySection(
            id=section_id,
            total=len(section_records),
            records=[MemoryRecord.model_validate(item) for item in visible_records],
            has_more=include_records and len(section_records) > len(visible_records),
        ))

    counts = {item.id: item.total for item in sections}
    totals = {
        "active": sum(counts[item] for item in ACTIVE_SECTIONS),
        "needs_review": sum(counts[item] for item in REVIEW_SECTIONS),
        "ready_to_review": sum(
            1
            for record in records
            if (
                record["section"] == "unverified"
                and "confirm" in record.get("allowed_actions", [])
            )
        ),
        "conflicts": counts["conflicts"],
        "needs_refresh": sum(counts[item] for item in FRESHNESS_SECTIONS),
        "people_and_dates": sum(counts[item] for item in PEOPLE_SECTIONS),
        "history": sum(counts[item] for item in HISTORY_SECTIONS),
        "reported_activity": sum(
            1
            for record in records
            if (
                record["section"] == "completed"
                and record["status"] == "reported"
            )
        ),
        "source_revisions": counts["revisions"],
        "all": sum(counts.values()),
    }
    totals["attention"] = totals["needs_review"] + totals["needs_refresh"]
    matches = (
        counts.get(section, 0)
        if section is not None
        else totals["all"]
    )
    return ProjectMemoryResponse(
        workspace_id=str(workspace_id),
        generated_at=utc_now(),
        query=" ".join(query.split()),
        selected_section=section,
        selected_semantic_section=semantic_section,
        current_goal=current_goal,
        agenda=agenda,
        filters={
            "scope": scope_mode,
            "effective_scope": effective_scope,
            "source_group": source_group,
            "verification": verification,
            "temporal": temporal,
            "kind": " ".join((kind or "").split()) or None,
            "semantic_section": semantic_section,
        },
        facets=facets,
        matches=matches,
        totals=totals,
        sections=sections,
        scope={
            "accessible_source_revisions": len(documents),
            "current_sources": len(current_documents),
            "source_backed_components": len(visible_components),
            "checkpoint_count": checkpoint_count,
            "excluded_unknown_session_components": excluded_unknown_sessions,
            "excluded_irrelevant_session_components": excluded_irrelevant_sessions,
            "excluded_unconfirmable_agent_components": excluded_unconfirmable_agent_components,
            "excluded_untrusted_relationships": excluded_untrusted_relationships,
            "collapsed_duplicate_current_claims": excluded_duplicate_claims,
            "collapsed_source_revision_components": collapsed_source_revision_components,
            "requested_mode": scope_mode,
            "effective_mode": effective_scope,
            "workspace_records": workspace_record_count,
            "agenda_records": agenda_record_count,
            "selected_session_document_id": (
                str(selected_session_document_id)
                if selected_session_document_id is not None else None
            ),
        },
    )


def _canonical_current_components(
    components: list[Component],
    *,
    evidence_by_component: dict[UUID, EvidenceSpan] | None = None,
    provider_freshness_by_source: (
        dict[UUID, ProviderFreshnessStatus] | None
    ) = None,
) -> tuple[list[Component], dict[UUID, int], int, dict[UUID, UUID]]:
    """Keep the strongest current evidence per claim; retain explicit history."""
    evidence_by_component = evidence_by_component or {}
    provider_freshness_by_source = provider_freshness_by_source or {}
    passthrough_ids: set[UUID] = set()
    components_by_claim: dict[UUID, list[Component]] = defaultdict(list)
    occurrence_count: dict[UUID, int] = {}
    canonical_component_ids: dict[UUID, UUID] = {}
    for component in components:
        if (
            component.status in HISTORICAL_COMPONENT_STATUSES
            or component.claim_id is None
        ):
            passthrough_ids.add(component.id)
            occurrence_count[component.id] = 1
            canonical_component_ids[component.id] = component.id
            continue
        components_by_claim[component.claim_id].append(component)

    representative_ids: set[UUID] = set()
    collapsed = 0
    for claim_components in components_by_claim.values():
        representative = max(
            claim_components,
            key=lambda item: _component_evidence_rank(
                item,
                evidence_by_component.get(item.id),
                provider_fresh=(
                    item.source_document_id in provider_freshness_by_source
                ),
            ),
        )
        representative_ids.add(representative.id)
        occurrence_count[representative.id] = len(claim_components)
        collapsed += len(claim_components) - 1
        for component in claim_components:
            canonical_component_ids[component.id] = representative.id

    retained_ids = passthrough_ids | representative_ids
    result = [item for item in components if item.id in retained_ids]
    return result, occurrence_count, collapsed, canonical_component_ids


def _component_evidence_rank(
    component: Component,
    evidence: EvidenceSpan | None,
    *,
    provider_fresh: bool = False,
) -> tuple[int, int, int, int, float, float, datetime, str]:
    """Prefer exact human/system evidence over recency for duplicate claims."""
    source = component.source_document
    assessment = assess_memory_trust(
        component,
        evidence,
        source=source,
        provider_fresh=provider_fresh,
    )
    return (
        int(
            assessment.current_truth
            and assessment.verification == "verified"
        ),
        int(
            assessment.current_truth
            and assessment.verification == "observed"
        ),
        int(assessment.evidence_exact),
        int(assessment.verification in {"verified", "observed", "reported"}),
        float(component.authority_weight or 0),
        float(component.confidence or 0),
        component.created_at,
        str(component.id),
    )


async def _evidence_by_component(
    session: AsyncSession,
    components: list[Component],
) -> dict[UUID, EvidenceSpan]:
    claim_ids = {item.claim_id for item in components if item.claim_id is not None}
    if not claim_ids:
        return {}
    revisions = list(await session.scalars(
        select(ClaimRevision)
        .options(selectinload(ClaimRevision.evidence_span))
        .where(ClaimRevision.claim_id.in_(claim_ids))
        .order_by(ClaimRevision.created_at.desc(), ClaimRevision.id.desc())
    ))
    revisions_by_id = {item.id: item for item in revisions}
    revisions_by_claim_source: dict[tuple[UUID, UUID], ClaimRevision] = {}
    for revision in revisions:
        key = (revision.claim_id, revision.evidence_span.source_document_id)
        revisions_by_claim_source.setdefault(key, revision)

    result: dict[UUID, EvidenceSpan] = {}
    for component in components:
        current_revision_id = (
            component.claim.current_revision_id if component.claim is not None else None
        )
        revision = revisions_by_id.get(current_revision_id)
        if (
            revision is None
            or revision.evidence_span.source_document_id != component.source_document_id
        ):
            revision = revisions_by_claim_source.get(
                (component.claim_id, component.source_document_id)
            )
        if revision is not None:
            result[component.id] = revision.evidence_span
    evidence_spans = {
        evidence.id: evidence for evidence in result.values()
    }
    if evidence_spans:
        source_rows = await session.execute(
            select(SourceDocument.id, SourceDocument.content).where(
                SourceDocument.id.in_({
                    evidence.source_document_id
                    for evidence in evidence_spans.values()
                })
            )
        )
        source_contents = {
            source_id: content or "" for source_id, content in source_rows
        }
        for evidence in evidence_spans.values():
            source_content = source_contents.get(evidence.source_document_id)
            start = evidence.start_char
            end = evidence.end_char
            evidence._source_text_matches = bool(
                source_content is not None
                and start is not None
                and end is not None
                and 0 <= start < end <= len(source_content)
                and source_content[start:end] == (evidence.text or "")
            )
            evidence._source_content_length = (
                len(source_content) if source_content is not None else -1
            )
            evidence._source_content_sha256 = (
                hashlib.sha256(source_content.encode("utf-8")).hexdigest()
                if source_content is not None
                else ""
            )
    return result


async def _latest_reviews_by_component(
    session: AsyncSession,
    components: list[Component],
) -> dict[UUID, MemoryReviewEvent]:
    component_ids = {item.id for item in components}
    if not component_ids:
        return {}
    events = list(await session.scalars(
        select(MemoryReviewEvent)
        .where(MemoryReviewEvent.component_id.in_(component_ids))
        .order_by(MemoryReviewEvent.created_at.desc(), MemoryReviewEvent.id.desc())
    ))
    result: dict[UUID, MemoryReviewEvent] = {}
    for event in events:
        result.setdefault(event.component_id, event)
    return result


def _component_record(
    component: Component,
    evidence: EvidenceSpan | None,
    review: MemoryReviewEvent | None,
    *,
    conflict: bool,
    occurrence_count: int = 1,
    provider_freshness: ProviderFreshnessStatus | None = None,
) -> dict[str, Any] | None:
    fact_type = (component.fact_type or "fact").lower()
    if fact_type in {"session_root", "ai_session", "ai_step"}:
        return None
    route = FACT_ROUTES.get(fact_type) or _explicit_route(component)
    if route is None:
        return None
    semantic_section, kind = route
    temporal = (component.temporal or "unknown").lower()
    if semantic_section == "blockers" and temporal == "future":
        semantic_section = "risks"
        kind = "Potential blocker"
    source = component.source_document
    provider_fresh = bool(
        provider_freshness is not None and provider_freshness.fresh
    )
    assessment = assess_memory_trust(
        component,
        evidence,
        source=source,
        provider_fresh=provider_fresh,
        conflict=conflict,
    )
    exact = assessment.evidence_exact
    remote_source = assessment.source_is_remote
    verified = bool(
        assessment.current_truth
        and assessment.verification == "verified"
    )
    provider_observed = bool(
        assessment.current_truth
        and assessment.verification == "observed"
    )
    accepted = assessment.current_truth
    agent_reported_activity = assessment.reported_activity
    raw_status = (component.status or "active").lower()
    if raw_status == "resolved":
        section = (
            "resolved"
            if fact_type in {"blocker", "ai_blocker"}
            else "completed"
        )
        status = "resolved"
    elif raw_status == "superseded":
        section = "superseded"
        status = "superseded"
    elif raw_status == "deprecated":
        section = "superseded"
        status = "deprecated"
    elif raw_status == "rejected":
        section = "dismissed"
        status = "dismissed"
    elif agent_reported_activity:
        # Test summaries, outcomes, and delivery prose written by an assistant
        # are useful as a point-in-time activity trail. Re-reading the same
        # prose cannot establish durable project truth, so it must not create
        # human review work or become compiler-eligible Current Memory.
        section = "completed"
        status = "reported"
    elif raw_status in {"stale", "deprecated"}:
        section = "stale"
        status = "stale"
    elif conflict or raw_status == "contested":
        section = "conflicts"
        status = "conflict"
    elif remote_source and not provider_fresh:
        section = "stale"
        status = "stale"
    elif raw_status in {"needs_review", "proposed"}:
        section = "unverified"
        status = raw_status
    elif (
        temporal == "past"
        and semantic_section in {"requirements", "work", "blockers", "risks"}
    ):
        section = "stale"
        status = "stale"
    elif not accepted:
        section = "unverified"
        status = "needs_review"
    else:
        section = semantic_section
        status = "active"

    actions: list[str]
    if agent_reported_activity:
        actions = []
    elif raw_status in HISTORICAL_COMPONENT_STATUSES:
        actions = ["reopen"] if exact else []
    else:
        actions = []
        if (
            section == "unverified"
            and exact
            and (not verified or raw_status in {"needs_review", "proposed"})
        ):
            actions.append("confirm")
        if kind == "Blocker" and section in {"blockers", "unverified"}:
            actions.append("resolve")
        actions.extend(["supersede", "dismiss"])

    evidence_payload = None
    if evidence is not None:
        evidence_payload = {
            "excerpt": evidence.text,
            "evidence_span_id": str(evidence.id),
            "start_char": evidence.start_char,
            "end_char": evidence.end_char,
            "text_sha256": evidence.text_sha256,
            "review_status": (
                assessment.verification
                if evidence is not None
                else "unavailable"
            ),
            "stored_review_status": evidence.review_status,
            "trust_zone": evidence.trust_zone,
            "extraction_method": evidence.extraction_method,
            "exact": exact,
        }
    if agent_reported_activity:
        explanation = (
            "Assistant-reported activity retained as point-in-time history. "
            "It is not a durable project claim and does not require confirmation."
        )
    elif section == "stale" and remote_source:
        explanation = (
            f"Typed `{fact_type}` record from a provider snapshot. Refresh the source "
            "before treating it as current; confirming the captured quote is not enough."
        )
    elif verified:
        explanation = (
            f"A person or trusted system confirmed this source-backed `{fact_type}` "
            "claim as current project memory."
        )
    elif provider_observed:
        explanation = (
            f"Typed `{fact_type}` record observed in exact provider evidence; remote "
            "freshness is shown separately."
        )
    elif exact:
        explanation = (
            f"Exact source evidence is attached to this `{fact_type}` claim. A person "
            "must decide whether it is correct, relevant, and still current."
        )
    else:
        explanation = f"Typed `{fact_type}` record without confirmable exact evidence."
    return {
        "id": f"component:{component.id}",
        "section": section,
        "semantic_section": semantic_section,
        "kind": kind,
        "title": _clean_text(component.name) or _clean_text(component.value),
        "summary": _clean_text(component.value) or _clean_text(component.name),
        "status": status,
        "verification": (
            assessment.verification
            if evidence is not None
            else "unavailable"
        ),
        "temporal": temporal,
        "origin": "component",
        "source_group": _source_group_for_source(source),
        "relevance": "Included because its source belongs to this workspace.",
        "component_id": str(component.id),
        "source": _source_payload(
            source,
            stale=section == "stale",
            provider_fresh=provider_fresh,
        ),
        "evidence": evidence_payload,
        "explanation": explanation,
        "allowed_actions": actions,
        "last_review": _review_payload(review),
        "occurred_at": component.created_at,
        "first_observed_at": component.valid_from,
        "last_observed_at": (
            (
                provider_freshness.observed_at
                if provider_freshness is not None
                else None
            )
            or (source.ingested_at if source else component.created_at)
        ),
        "occurrence_count": occurrence_count,
    }


def _explicit_route(component: Component) -> tuple[str, str] | None:
    for raw in (component.name, component.value):
        text = _clean_text(raw)
        for pattern, route in EXPLICIT_PREFIX_ROUTES:
            if pattern.match(text):
                return route
    return None


def _relationship_records(
    relationships: list[Relationship],
    components: dict[UUID, Component],
    component_records: dict[UUID, dict[str, Any]],
    canonical_component_ids: dict[UUID, UUID],
    *,
    provider_freshness_by_source: (
        dict[UUID, ProviderFreshnessStatus] | None
    ) = None,
) -> tuple[list[dict[str, Any]], int]:
    provider_freshness_by_source = provider_freshness_by_source or {}
    result: list[dict[str, Any]] = []
    excluded_untrusted = 0
    seen_relationships: set[tuple[str, str, str, str]] = set()
    routes = {
        "depends_on": ("blockers", "Dependency"),
        "blocked_by": ("blockers", "Dependency"),
        "blocks": ("blockers", "Dependency"),
        "owned_by": ("owners", "Owner"),
        "assigned_to": ("owners", "Owner"),
        "conflicts_with": ("conflicts", "Conflict"),
        "contradicts": ("conflicts", "Conflict"),
    }
    for relationship in relationships:
        route = routes.get(relationship.relationship_type)
        if route is None or not relationship.evidence:
            continue
        if relationship.origin not in {"deterministic", "extracted", "human_verified"}:
            continue
        source_component = components.get(relationship.source_component_id)
        target_component = components.get(relationship.target_component_id)
        if source_component is None or target_component is None:
            continue
        source_record = component_records.get(source_component.id)
        target_record = component_records.get(target_component.id)
        if source_record is None or target_record is None:
            excluded_untrusted += 1
            continue
        section, kind = route
        is_conflict = section == "conflicts"
        endpoints_are_current = all(
            record.get("section") in ACTIVE_SECTIONS | PEOPLE_SECTIONS
            and record.get("verification") in {"verified", "observed"}
            for record in (source_record, target_record)
        )
        relationship_is_trusted = (
            relationship.status == "active"
            and relationship.origin in {"deterministic", "human_verified"}
            and endpoints_are_current
        )
        if not is_conflict and not relationship_is_trusted:
            excluded_untrusted += 1
            continue
        canonical_source_id = canonical_component_ids.get(
            source_component.id,
            source_component.id,
        )
        canonical_target_id = canonical_component_ids.get(
            target_component.id,
            target_component.id,
        )
        semantic_key = (
            str(canonical_source_id),
            str(canonical_target_id),
            relationship.relationship_type,
            _clean_text(relationship.evidence).casefold(),
        )
        if semantic_key in seen_relationships:
            continue
        seen_relationships.add(semantic_key)
        result.append({
            "id": f"relationship:{relationship.id}",
            "section": section,
            "semantic_section": section,
            "kind": kind,
            "title": (
                f"{_clean_text(source_component.name)} "
                f"{relationship.relationship_type.replace('_', ' ')} "
                f"{_clean_text(target_component.name)}"
            ),
            "summary": _clean_text(relationship.evidence),
            "status": "conflict" if is_conflict else "observed",
            "verification": (
                "observed" if relationship_is_trusted else "needs_review"
            ),
            "temporal": "current",
            "origin": "relationship",
            "source_group": _source_group_for_source(
                source_component.source_document
            ),
            "relevance": "Included because both linked records belong to this workspace.",
            "component_id": None,
            "source": _source_payload(
                source_component.source_document,
                provider_fresh=(
                    source_component.source_document_id
                    in provider_freshness_by_source
                ),
            ),
            "evidence": {
                "excerpt": relationship.evidence,
                "review_status": (
                    "observed" if relationship_is_trusted else "needs_review"
                ),
                "exact": False,
            },
            "explanation": (
                f"Stored {relationship.relationship_type.replace('_', ' ')} relationship "
                f"with {relationship.origin} provenance."
            ),
            "allowed_actions": [],
            "occurred_at": relationship.created_at,
            "last_observed_at": relationship.created_at,
            "_related_component_ids": {
                str(canonical_source_id),
                str(canonical_target_id),
            },
        })
    return result, excluded_untrusted


def _source_metadata_records(
    documents: list[SourceDocument],
    repositories: set[str],
    paths: set[str],
    commits: set[str],
    *,
    provider_freshness_by_source: (
        dict[UUID, ProviderFreshnessStatus] | None
    ) = None,
) -> list[dict[str, Any]]:
    provider_freshness_by_source = provider_freshness_by_source or {}
    records: list[dict[str, Any]] = []
    for document in documents:
        metadata = metadata_dict(document)
        if _agent_source(document.source_type):
            relevance = source_workspace_relevance(
                document.source_type,
                metadata,
                repositories,
                paths,
                commits,
            )
            if relevance.status != "relevant":
                continue
        item_type = str(metadata.get("item_type") or "").lower()
        if item_type in {"issue", "pull_request"}:
            provider_freshness = provider_freshness_by_source.get(document.id)
            provider_fresh = bool(
                provider_freshness is not None
                and provider_freshness.fresh
            )
            provider_section = "owners" if provider_fresh else "stale"
            provider_status = "observed" if provider_fresh else "stale"
            for assignee in _metadata_people(metadata.get("assignees")):
                records.append(_metadata_record(
                    document,
                    section=provider_section,
                    semantic_section="owners",
                    kind="Owner",
                    title=assignee,
                    summary=f"Assigned to {document.external_id}",
                    explanation=(
                        "Observed from typed provider assignee metadata during a "
                        "recent successful refresh."
                        if provider_fresh
                        else "Observed from typed provider assignee metadata whose "
                        "current remote state has not been refreshed."
                    ),
                    status=provider_status,
                    provider_freshness=provider_freshness,
                ))
            milestone = metadata.get("milestone")
            milestone_title = (
                str(milestone.get("title") or "").strip()
                if isinstance(milestone, dict)
                else str(milestone or "").strip()
            )
            if milestone_title:
                records.append(_metadata_record(
                    document,
                    section="milestones" if provider_fresh else "stale",
                    semantic_section="milestones",
                    kind="Milestone",
                    title=milestone_title,
                    summary=f"Milestone for {document.external_id}",
                    explanation=(
                        "Observed from typed provider milestone metadata during a "
                        "recent successful refresh."
                        if provider_fresh
                        else "Observed from typed provider milestone metadata whose "
                        "current remote state has not been refreshed."
                    ),
                    status=provider_status,
                    provider_freshness=provider_freshness,
                ))
        revision_number = int(document.revision_number or 1)
        if revision_number > 1:
            records.append(_metadata_record(
                document,
                section="revisions",
                kind="Source revision",
                title=document.external_id,
                summary=(
                    f"Current source revision is {revision_number}; earlier revisions remain "
                    "in the immutable source ledger."
                ),
                explanation="Derived from the source ledger's immutable revision number.",
                status="historical",
                provider_freshness=provider_freshness_by_source.get(document.id),
            ))
    return records


def _metadata_record(
    document: SourceDocument,
    *,
    section: str,
    semantic_section: str | None = None,
    kind: str,
    title: str,
    summary: str,
    explanation: str,
    status: str = "observed",
    provider_freshness: ProviderFreshnessStatus | None = None,
) -> dict[str, Any]:
    provider_fresh = bool(
        provider_freshness is not None and provider_freshness.fresh
    )
    return {
        "id": f"metadata:{section}:{document.id}:{_slug(title)}",
        "section": section,
        "semantic_section": semantic_section or section,
        "kind": kind,
        "title": _clean_text(title),
        "summary": _clean_text(summary),
        "status": status,
        "verification": "observed",
        "temporal": "current" if status == "observed" else "unknown",
        "origin": "source_metadata",
        "source_group": _source_group_for_source(document),
        "relevance": "Included because its source belongs to this workspace.",
        "component_id": None,
        "source": _source_payload(
            document,
            stale=status == "stale",
            provider_fresh=provider_fresh,
        ),
        "evidence": {
            "excerpt": None,
            "review_status": "provider_observed",
            "exact": False,
        },
        "explanation": explanation,
        "allowed_actions": [],
        "occurred_at": document.ingested_at,
        "last_observed_at": (
            (
                provider_freshness.observed_at
                if provider_freshness is not None
                else None
            )
            or document.ingested_at
        ),
    }


async def _checkpoint_count(
    session: AsyncSession,
    workspace_id: UUID,
    access_scope: AccessScope,
) -> int:
    count = await session.scalar(
        select(func.count(WorkCheckpoint.id))
        .join(SourceDocument, WorkCheckpoint.source_document_id == SourceDocument.id)
        .where(
            WorkCheckpoint.workspace_id == workspace_id,
            source_access_predicate(access_scope, workspace_id=workspace_id),
        )
    )
    return int(count or 0)


def _goal_record(goal: dict[str, Any]) -> dict[str, Any]:
    active_run = goal.get("source_kind") == "active_agent_run"
    return {
        "id": f"goal:{goal['id']}",
        "section": "goal",
        "semantic_section": "goal",
        "kind": "Active run objective" if active_run else "Selected goal",
        "title": _clean_text(goal.get("title")),
        "summary": (
            "Controls the currently running agent session and cannot be cleared here."
            if active_run
            else (
                "Scopes Current Memory and is also shown in Now. It does not start work, "
                "edit files, or change agent context by itself."
            )
        ),
        "status": "active",
        "verification": "observed" if active_run else "verified",
        "temporal": "current",
        "origin": "workspace_goal",
        "source_group": "documents",
        "relevance": "This is the workspace's selected agenda.",
        "component_id": goal.get("component_id"),
        "source": MemorySource(
            label="Active agent run" if active_run else "User-selected workspace goal",
            source_type=goal.get("source_kind") or "workspace_goal",
            freshness="observed",
        ).model_dump(),
        "evidence": None,
        "explanation": (
            "Objective reported by an active agent run."
            if active_run
            else "Explicitly entered by a user and retained in workspace goal history."
        ),
        "allowed_actions": [],
        "occurred_at": goal.get("selected_at"),
        "last_observed_at": goal.get("selected_at"),
    }


def _apply_memory_scope(
    records: list[dict[str, Any]],
    *,
    requested_scope: MemoryScopeMode,
    current_goal: dict[str, Any] | None,
    selected_session: dict[str, str | None],
    selected_session_document: SourceDocument | None,
    relationships: list[Relationship],
    canonical_component_ids: dict[UUID, UUID],
) -> tuple[list[dict[str, Any]], dict[str, Any] | None, str]:
    agenda: dict[str, Any] | None = None
    if current_goal is not None:
        agenda = {
            "kind": "current_goal",
            "title": _clean_text(current_goal.get("title")),
            "source_kind": current_goal.get("source_kind"),
            "component_id": current_goal.get("component_id"),
            "source_document_id": None,
            "topic": None,
            "match_mode": (
                "linked_component"
                if current_goal.get("component_id")
                else "text_match"
            ),
        }
    elif selected_session_document is not None:
        metadata = metadata_dict(selected_session_document)
        topic = _clean_text(selected_session.get("topic"))
        agenda = {
            "kind": "selected_session",
            "title": (
                topic
                or _clean_text(metadata.get("title"))
                or _clean_text(selected_session_document.external_id)
            ),
            "source_kind": "selected_session",
            "component_id": None,
            "source_document_id": str(selected_session_document.id),
            "topic": topic or None,
            "match_mode": "selected_source",
        }

    if requested_scope == "workspace" or agenda is None:
        return (
            [
                {
                    **record,
                    "relevance": (
                        record["relevance"]
                        if record.get("origin") == "workspace_goal"
                        else "Included because its source belongs to this workspace."
                    ),
                }
                for record in records
            ],
            agenda,
            "workspace",
        )

    if agenda["kind"] == "selected_session":
        source_document_id = agenda["source_document_id"]
        scoped = []
        for record in records:
            source = record.get("source") or {}
            if source.get("document_id") != source_document_id:
                continue
            scoped.append({
                **record,
                "relevance": "Shown because it comes from the session selected for this workspace.",
            })
        return scoped, agenda, "agenda"

    component_id = str(agenda.get("component_id") or "").strip()
    related_component_ids = {component_id} if component_id else set()
    if component_id:
        for relationship in relationships:
            if (
                relationship.status != "active"
                or relationship.origin not in {"deterministic", "human_verified"}
            ):
                continue
            source_id = str(canonical_component_ids.get(
                relationship.source_component_id,
                relationship.source_component_id,
            ))
            target_id = str(canonical_component_ids.get(
                relationship.target_component_id,
                relationship.target_component_id,
            ))
            if component_id == source_id:
                related_component_ids.add(target_id)
            elif component_id == target_id:
                related_component_ids.add(source_id)
    focus_source_document_id = next(
        (
            str((record.get("source") or {}).get("document_id") or "")
            for record in records
            if str(record.get("component_id") or "") == component_id
        ),
        "",
    )
    agenda_terms = _agenda_terms(agenda.get("title"))
    scoped: list[dict[str, Any]] = []
    for record in records:
        if record.get("origin") == "workspace_goal":
            scoped.append({
                **record,
                "relevance": "This is the workspace's selected agenda.",
            })
            continue
        record_component_id = str(record.get("component_id") or "")
        relationship_component_ids = {
            str(value) for value in record.get("_related_component_ids", set())
        }
        if component_id and (
            record_component_id in related_component_ids
            or bool(relationship_component_ids & related_component_ids)
        ):
            scoped.append({
                **record,
                "relevance": "Directly linked to the selected agenda record.",
            })
            continue
        source_document_id = str((record.get("source") or {}).get("document_id") or "")
        if (
            focus_source_document_id
            and source_document_id == focus_source_document_id
        ):
            scoped.append({
                **record,
                "relevance": "Backed by the same source as the selected agenda.",
            })
            continue
        matched_terms = _matching_agenda_terms(record, agenda_terms)
        if matched_terms:
            scoped.append({
                **record,
                "relevance": (
                    "Matches the selected agenda terms: "
                    f"{', '.join(matched_terms)}."
                ),
            })
    return (
        scoped,
        agenda,
        "agenda" if component_id else "agenda_match",
    )


def _agenda_terms(value: Any) -> list[str]:
    stop_words = {
        "about", "after", "again", "against", "also", "and", "are", "build",
        "current", "for", "from", "goal", "into", "make", "project", "that",
        "the", "this", "through", "with", "work", "workspace",
    }
    terms: list[str] = []
    for term in _normalized_search_terms(value):
        if term in stop_words or term in terms:
            continue
        terms.append(term)
    return terms[:12]


def _matching_agenda_terms(
    record: dict[str, Any],
    agenda_terms: list[str],
) -> list[str]:
    if not agenda_terms:
        return []
    evidence = record.get("evidence") or {}
    text = " ".join(str(value or "") for value in (
        record.get("title"),
        record.get("summary"),
        record.get("kind"),
        evidence.get("excerpt"),
    ))
    record_terms = set(_normalized_search_terms(text))
    matched = [term for term in agenda_terms if term in record_terms]
    required = 1 if len(agenda_terms) == 1 else 2
    return matched if len(matched) >= required else []


def _normalized_search_terms(value: Any) -> list[str]:
    terms: list[str] = []
    for raw in re.findall(
        r"[a-z0-9][a-z0-9_-]{2,}",
        str(value or "").casefold(),
    ):
        for term in (raw, *re.split(r"[-_]+", raw)):
            if len(term) >= 3 and term not in terms:
                terms.append(term)
    return terms


def _memory_facets(records: list[dict[str, Any]]) -> dict[str, Any]:
    facet_fields = {
        "sections": "section",
        "kinds": "kind",
        "source_groups": "source_group",
        "verification": "verification",
        "temporal": "temporal",
    }
    result: dict[str, dict[str, int]] = {}
    for facet_name, field_name in facet_fields.items():
        counts: dict[str, int] = defaultdict(int)
        for record in records:
            value = str(record.get(field_name) or "unknown")
            counts[value] += 1
        result[facet_name] = dict(sorted(counts.items()))
    review_semantic_counts: dict[str, int] = defaultdict(int)
    reviewable_semantic_counts: dict[str, int] = defaultdict(int)
    stale_semantic_counts: dict[str, int] = defaultdict(int)
    for record in records:
        if record.get("section") in REVIEW_SECTIONS:
            semantic_section = str(
                record.get("semantic_section") or "unknown"
            )
            review_semantic_counts[semantic_section] += 1
            if (
                record.get("section") == "unverified"
                and "confirm" in record.get("allowed_actions", [])
            ):
                reviewable_semantic_counts[semantic_section] += 1
        if record.get("section") in FRESHNESS_SECTIONS:
            stale_semantic_counts[
                str(record.get("semantic_section") or "unknown")
            ] += 1
    result["review_semantic_sections"] = dict(
        sorted(review_semantic_counts.items())
    )
    result["reviewable_semantic_sections"] = dict(
        sorted(reviewable_semantic_counts.items())
    )
    result["stale_semantic_sections"] = dict(
        sorted(stale_semantic_counts.items())
    )
    kinds_by_section: dict[str, dict[str, int]] = defaultdict(
        lambda: defaultdict(int)
    )
    for record in records:
        section_id = str(record.get("section") or "unknown")
        kind = str(record.get("kind") or "unknown")
        kinds_by_section[section_id][kind] += 1
    result["kinds_by_section"] = {
        section_id: dict(sorted(counts.items()))
        for section_id, counts in sorted(kinds_by_section.items())
    }
    return result


def _source_group_for_source(
    source: SourceDocument | None,
) -> Literal["documents", "repository", "sessions", "integrations"]:
    if source is None:
        return "documents"
    source_type = (source.source_type or "").lower()
    if _agent_source(source_type):
        return "sessions"
    if source_type in {
        "local_repository", "repository", "repo", "git", "code_index",
    }:
        return "repository"
    if source_type in {
        "github", "github_issue", "github_pr", "github_pull_request", "slack",
        "discord", "gmail", "gdrive", "google_drive", "zoom", "notion",
    }:
        return "integrations"
    return "documents"


def _source_payload(
    source: SourceDocument | None,
    *,
    stale: bool = False,
    label: str | None = None,
    provider_fresh: bool = False,
) -> dict[str, Any] | None:
    if source is None:
        return None
    remote = _remote_source(source)
    return {
        "label": label or f"{source_type_display(source.source_type)} · {source.external_id}",
        "source_type": source.source_type,
        "document_id": str(source.id),
        "external_id": source.external_id,
        "url": source.source_url,
        "revision_number": int(source.revision_number or 1),
        "freshness": (
            "stale"
            if stale
            else "observed"
            if remote and provider_fresh
            else "unknown"
            if remote
            else "not_remote"
        ),
    }


def _review_payload(review: MemoryReviewEvent | None) -> dict[str, Any] | None:
    if review is None:
        return None
    return {
        "action": review.action,
        "reviewed_by": review.reviewed_by,
        "reason": review.reason,
        "reviewed_at": review.created_at,
    }


def _dedupe_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for record in records:
        if not record.get("title") or record["id"] in seen_ids:
            continue
        seen_ids.add(record["id"])
        result.append(record)
    return result


def _record_search_text(record: dict[str, Any]) -> str:
    source = record.get("source") or {}
    evidence = record.get("evidence") or {}
    return " ".join(str(value or "") for value in (
        record.get("title"),
        record.get("summary"),
        record.get("kind"),
        record.get("status"),
        record.get("verification"),
        record.get("source_group"),
        record.get("relevance"),
        source.get("label"),
        source.get("external_id"),
        evidence.get("excerpt"),
    )).casefold()


def _record_sort_key(record: dict[str, Any]) -> tuple[datetime, str]:
    occurred = (
        record.get("last_observed_at")
        or record.get("occurred_at")
        or datetime.min
    )
    return occurred, record["id"]


def _metadata_people(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        name = (
            str(item.get("login") or item.get("name") or "").strip()
            if isinstance(item, dict)
            else str(item or "").strip()
        )
        if name and name not in result:
            result.append(name)
    return result


def _agent_source(source_type: str | None) -> bool:
    return is_agent_source_type(source_type)


def _remote_source(source: SourceDocument | None) -> bool:
    return is_remote_source(source)


def _clean_text(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text if len(text) <= 800 else text[:797].rstrip() + "…"


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")[:80]
