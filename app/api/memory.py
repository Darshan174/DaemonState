from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

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
from app.services.evidence import sha256_text
from app.services.project_scope import (
    source_workspace_relevance,
    workspace_references,
    workspace_relevance,
)
from app.services.workspace_goals import resolve_current_goal
from app.services.workspace_scope import (
    current_source_documents,
    filter_explicit_source_documents_for_workspace,
    metadata_dict,
)
from app.taxonomy import AGENT_SESSION_SOURCE_TYPES, source_type_display
from app.time import utc_now


router = APIRouter()

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
    "superseded",
    "dismissed",
    "revisions",
]

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
    "superseded",
    "dismissed",
    "revisions",
)
ACTIVE_SECTIONS = frozenset({
    "goal", "requirements", "decisions", "work", "blockers", "risks",
    "learnings", "deliveries",
})
REVIEW_SECTIONS = frozenset({"unverified", "conflicts", "stale"})
PEOPLE_SECTIONS = frozenset({"owners", "milestones"})
HISTORY_SECTIONS = frozenset({"resolved", "superseded", "dismissed", "revisions"})
HISTORICAL_COMPONENT_STATUSES = frozenset({"resolved", "superseded", "rejected"})
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
    "code_area": ("deliveries", "Code area"),
    "repo_root": ("deliveries", "Repository"),
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


class MemoryRecord(BaseModel):
    id: str
    section: MemorySectionId
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
    component_id: str | None = None
    source: MemorySource | None = None
    evidence: MemoryEvidence | None = None
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


class ProjectMemoryResponse(BaseModel):
    workspace_id: str
    generated_at: datetime
    query: str
    selected_section: MemorySectionId | None = None
    current_goal: dict | None
    totals: dict[str, int]
    sections: list[MemorySection]
    scope: dict[str, int]


@router.get("/context/memory", response_model=ProjectMemoryResponse)
async def get_project_memory(
    workspace_id: UUID,
    query: str = Query(default="", max_length=200),
    section: MemorySectionId | None = None,
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
        .where(source_access_predicate(access_scope, workspace_id=workspace_id))
        .order_by(SourceDocument.ingested_at.desc(), SourceDocument.id.desc())
    ))
    documents = filter_explicit_source_documents_for_workspace(
        documents, str(workspace_id)
    )
    current_documents, _ = current_source_documents(documents)
    current_document_ids = {item.id for item in current_documents}
    accessible_document_ids = {item.id for item in documents}

    components: list[Component] = []
    if accessible_document_ids:
        components = list(await session.scalars(
            select(Component)
            .options(
                selectinload(Component.source_document),
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

    visible_components, occurrence_count_by_component, excluded_duplicate_claims = (
        _canonical_current_components(visible_components)
    )

    evidence_by_component = await _evidence_by_component(
        session, visible_components
    )
    reviews_by_component = await _latest_reviews_by_component(
        session, visible_components
    )
    component_by_id = {item.id: item for item in visible_components}
    records: list[dict[str, Any]] = []
    conflict_component_ids: set[UUID] = set()
    excluded_unconfirmable_agent_components = 0

    current_component_ids = {
        item.id for item in visible_components
        if item.source_document_id in current_document_ids
        and item.status not in HISTORICAL_COMPONENT_STATUSES
    }
    relationships: list[Relationship] = []
    if current_component_ids:
        relationships = list(await session.scalars(
            select(Relationship)
            .where(
                Relationship.source_component_id.in_(current_component_ids),
                Relationship.target_component_id.in_(current_component_ids),
                Relationship.status.not_in(["rejected", "superseded"]),
            )
            .order_by(Relationship.created_at.desc(), Relationship.id.desc())
        ))
    for relationship in relationships:
        if relationship.relationship_type in {"conflicts_with", "contradicts"}:
            conflict_component_ids.update({
                relationship.source_component_id,
                relationship.target_component_id,
            })

    for component in visible_components:
        evidence = evidence_by_component.get(component.id)
        if (
            component.status not in HISTORICAL_COMPONENT_STATUSES
            and component.source_document is not None
            and _agent_source(component.source_document.source_type)
            and not _exact_evidence(component.source_document, evidence)
        ):
            excluded_unconfirmable_agent_components += 1
            continue
        record = _component_record(
            component,
            evidence,
            reviews_by_component.get(component.id),
            conflict=component.id in conflict_component_ids,
            occurrence_count=occurrence_count_by_component.get(component.id, 1),
        )
        if record is not None:
            records.append(record)

    records.extend(_relationship_records(relationships, component_by_id))
    records.extend(
        _source_metadata_records(
            current_documents,
            repositories,
            paths,
            commits,
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
        allowed_component_ids=current_component_ids,
    )
    if current_goal is not None:
        records.append(_goal_record(current_goal))

    records = _dedupe_records(records)
    normalized_query = " ".join(query.split()).casefold()
    if normalized_query:
        records = [
            record for record in records
            if normalized_query in _record_search_text(record)
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
        "people_and_dates": sum(counts[item] for item in PEOPLE_SECTIONS),
        "history": sum(counts[item] for item in HISTORY_SECTIONS),
        "all": sum(counts.values()),
    }
    return ProjectMemoryResponse(
        workspace_id=str(workspace_id),
        generated_at=utc_now(),
        query=" ".join(query.split()),
        selected_section=section,
        current_goal=current_goal,
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
            "collapsed_duplicate_current_claims": excluded_duplicate_claims,
        },
    )


def _canonical_current_components(
    components: list[Component],
) -> tuple[list[Component], dict[UUID, int], int]:
    """Keep one current component per canonical claim; retain all explicit history."""
    result: list[Component] = []
    representative_by_claim: dict[UUID, Component] = {}
    occurrence_count: dict[UUID, int] = {}
    collapsed = 0
    for component in components:
        if (
            component.status in HISTORICAL_COMPONENT_STATUSES
            or component.claim_id is None
        ):
            result.append(component)
            occurrence_count[component.id] = 1
            continue
        representative = representative_by_claim.get(component.claim_id)
        if representative is None:
            representative_by_claim[component.claim_id] = component
            result.append(component)
            occurrence_count[component.id] = 1
            continue
        occurrence_count[representative.id] += 1
        collapsed += 1
    return result, occurrence_count, collapsed


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
) -> dict[str, Any] | None:
    fact_type = (component.fact_type or "fact").lower()
    if fact_type in {"session_root", "ai_session", "ai_step"}:
        return None
    route = FACT_ROUTES.get(fact_type) or _explicit_route(component)
    if route is None:
        return None
    semantic_section, kind = route
    exact = _exact_evidence(component.source_document, evidence)
    source = component.source_document
    source_metadata = metadata_dict(source) if source is not None else {}
    agent_derived = bool(source and _agent_source(source.source_type))
    remote_source = _remote_source(source)
    human_confirmed = bool(
        evidence
        and (evidence.trust_zone or "").lower() == "trusted_human"
    ) or bool(
        source_metadata.get("verified_by_human") is True
        or str(source_metadata.get("verification_status") or "").lower()
        == "human_verified"
    )
    evidence_zone = (evidence.trust_zone or "").lower() if evidence else ""
    verified = bool(
        evidence
        and exact
        and evidence.review_status == "verified"
        and evidence_zone in {"trusted_human", "trusted_repo", "trusted_system"}
        and (not agent_derived or human_confirmed)
    )
    provider_observed = bool(
        evidence
        and exact
        and evidence.review_status == "verified"
        and not agent_derived
        and evidence_zone == "semi_trusted_tool"
    )
    accepted = verified or provider_observed
    raw_status = (component.status or "active").lower()
    if raw_status == "resolved" and kind == "Blocker":
        section = "resolved"
        status = "resolved"
    elif raw_status == "superseded":
        section = "superseded"
        status = "superseded"
    elif raw_status == "rejected":
        section = "dismissed"
        status = "dismissed"
    elif raw_status in {"stale", "deprecated"}:
        section = "stale"
        status = "stale"
    elif conflict or raw_status == "contested":
        section = "conflicts"
        status = "conflict"
    elif remote_source:
        section = "stale"
        status = "stale"
    elif not accepted:
        section = "unverified"
        status = "needs_review"
    else:
        section = semantic_section
        status = "verified" if verified else "observed"

    actions: list[str]
    if raw_status in HISTORICAL_COMPONENT_STATUSES:
        actions = ["reopen"] if exact else []
    else:
        actions = []
        if exact and not verified:
            actions.append("confirm")
        if kind == "Blocker":
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
                "verified" if verified else ("observed" if provider_observed else "needs_review")
            ),
            "stored_review_status": evidence.review_status,
            "trust_zone": evidence.trust_zone,
            "extraction_method": evidence.extraction_method,
            "exact": exact,
        }
    if section == "stale" and remote_source:
        explanation = (
            f"Typed `{fact_type}` record from a provider snapshot whose current remote "
            "state has not been refreshed."
        )
    elif verified:
        explanation = f"Typed `{fact_type}` record with exact verified evidence."
    elif provider_observed:
        explanation = (
            f"Typed `{fact_type}` record observed in exact provider evidence; remote "
            "freshness is shown separately."
        )
    elif exact:
        explanation = (
            f"Typed `{fact_type}` record awaiting human confirmation of its exact evidence."
        )
    else:
        explanation = f"Typed `{fact_type}` record without confirmable exact evidence."
    return {
        "id": f"component:{component.id}",
        "section": section,
        "kind": kind,
        "title": _clean_text(component.name) or _clean_text(component.value),
        "summary": _clean_text(component.value) or _clean_text(component.name),
        "status": status,
        "verification": (
            "verified" if verified else (
                "observed" if provider_observed else (
                    "needs_review" if evidence is not None else "unavailable"
                )
            )
        ),
        "temporal": component.temporal or "unknown",
        "origin": "component",
        "component_id": str(component.id),
        "source": _source_payload(source, stale=section == "stale"),
        "evidence": evidence_payload,
        "explanation": explanation,
        "allowed_actions": actions,
        "last_review": _review_payload(review),
        "occurred_at": component.created_at,
        "first_observed_at": component.valid_from,
        "last_observed_at": source.ingested_at if source else component.created_at,
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
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
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
        section, kind = route
        is_conflict = section == "conflicts"
        result.append({
            "id": f"relationship:{relationship.id}",
            "section": section,
            "kind": kind,
            "title": (
                f"{_clean_text(source_component.name)} "
                f"{relationship.relationship_type.replace('_', ' ')} "
                f"{_clean_text(target_component.name)}"
            ),
            "summary": _clean_text(relationship.evidence),
            "status": "conflict" if is_conflict else "observed",
            "verification": "observed",
            "temporal": "current",
            "origin": "relationship",
            "component_id": None,
            "source": _source_payload(source_component.source_document),
            "evidence": {
                "excerpt": relationship.evidence,
                "review_status": "observed",
                "exact": False,
            },
            "explanation": (
                f"Stored {relationship.relationship_type.replace('_', ' ')} relationship "
                f"with {relationship.origin} provenance."
            ),
            "allowed_actions": [],
            "occurred_at": relationship.created_at,
            "last_observed_at": relationship.created_at,
        })
    return result


def _source_metadata_records(
    documents: list[SourceDocument],
    repositories: set[str],
    paths: set[str],
    commits: set[str],
) -> list[dict[str, Any]]:
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
            for assignee in _metadata_people(metadata.get("assignees")):
                records.append(_metadata_record(
                    document,
                    section="owners",
                    kind="Owner",
                    title=assignee,
                    summary=f"Assigned to {document.external_id}",
                    explanation="Observed from typed provider assignee metadata.",
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
                    section="milestones",
                    kind="Milestone",
                    title=milestone_title,
                    summary=f"Milestone for {document.external_id}",
                    explanation="Observed from typed provider milestone metadata.",
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
            ))
    return records


def _metadata_record(
    document: SourceDocument,
    *,
    section: str,
    kind: str,
    title: str,
    summary: str,
    explanation: str,
    status: str = "observed",
) -> dict[str, Any]:
    return {
        "id": f"metadata:{section}:{document.id}:{_slug(title)}",
        "section": section,
        "kind": kind,
        "title": _clean_text(title),
        "summary": _clean_text(summary),
        "status": status,
        "verification": "observed",
        "temporal": "current" if status == "observed" else "past",
        "origin": "source_metadata",
        "component_id": None,
        "source": _source_payload(document),
        "evidence": {
            "excerpt": None,
            "review_status": "provider_observed",
            "exact": False,
        },
        "explanation": explanation,
        "allowed_actions": [],
        "occurred_at": document.ingested_at,
        "last_observed_at": document.ingested_at,
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
        "kind": "Active run objective" if active_run else "Selected goal",
        "title": _clean_text(goal.get("title")),
        "summary": (
            "Controls the currently running agent session and cannot be cleared here."
            if active_run
            else (
                "Display-only workspace focus shown in Memory and Now. It does not start "
                "work, edit files, or change agent context by itself."
            )
        ),
        "status": "active",
        "verification": "observed" if active_run else "verified",
        "temporal": "current",
        "origin": "workspace_goal",
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


def _source_payload(
    source: SourceDocument | None,
    *,
    stale: bool = False,
    label: str | None = None,
) -> dict[str, Any] | None:
    if source is None:
        return None
    remote = source.source_type in {
        "github", "github_issue", "github_pr", "slack", "discord", "gmail",
        "gdrive", "zoom", "notion",
    }
    return {
        "label": label or f"{source_type_display(source.source_type)} · {source.external_id}",
        "source_type": source.source_type,
        "document_id": str(source.id),
        "external_id": source.external_id,
        "url": source.source_url,
        "revision_number": int(source.revision_number or 1),
        "freshness": "stale" if stale else ("unknown" if remote else "not_remote"),
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


def _exact_evidence(source: SourceDocument | None, evidence: EvidenceSpan | None) -> bool:
    if (
        source is None
        or evidence is None
        or evidence.start_char is None
        or evidence.end_char is None
    ):
        return False
    content = source.content or ""
    excerpt = evidence.text or ""
    return bool(
        0 <= evidence.start_char < evidence.end_char <= len(content)
        and evidence.source_document_id == source.id
        and content[evidence.start_char:evidence.end_char] == excerpt
        and sha256_text(excerpt) == evidence.text_sha256
    )


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
    raw = (source_type or "").lower()
    return raw in AGENT_SESSION_SOURCE_TYPES or raw.startswith("ai_context")


def _remote_source(source: SourceDocument | None) -> bool:
    if source is None:
        return False
    metadata = metadata_dict(source)
    item_type = str(metadata.get("item_type") or "").lower()
    source_type = (source.source_type or "").lower()
    return item_type in {"issue", "pull_request"} or source_type in {
        "github", "slack", "notion", "gmail", "google_drive",
    }


def _clean_text(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text if len(text) <= 800 else text[:797].rstrip() + "…"


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")[:80]
