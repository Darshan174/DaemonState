from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db_session
from app.models import Component, Relationship
from app.services.workspace_scope import (
    filter_components_for_workspace,
    metadata_dict,
    workspace_connector_types,
)
from app.taxonomy import relationship_display_label, source_type_display

router = APIRouter()

CardType = Literal[
    "source",
    "evidence",
    "claim",
    "task",
    "decision",
    "blocker",
    "risk",
    "file",
    "agent_session",
]
CardStatus = Literal[
    "active",
    "needs_review",
    "blocked",
    "stale",
    "verified",
    "conflict",
]
CardTemporal = Literal["past", "current", "future", "unknown"]
BadgeTone = Literal["gray", "blue", "green", "amber", "red", "violet"]
HealthStatus = Literal["empty", "healthy", "needs_review", "critical"]


class DigestHealth(BaseModel):
    status: HealthStatus
    summary: str
    blocker_count: int
    conflict_count: int
    stale_count: int
    unverified_count: int
    agent_ready_score: int


class DigestBadge(BaseModel):
    label: str
    tone: BadgeTone = "gray"


class DigestProvenance(BaseModel):
    source_type: str
    source_label: str
    source_url: str | None = None
    excerpt: str | None = None


class ContextCard(BaseModel):
    id: str
    title: str
    type: CardType
    summary: str
    why_it_matters: str
    next_action: str
    status: CardStatus
    temporal: CardTemporal
    confidence: float
    authority_weight: float
    attention_score: int
    source_ids: list[str]
    evidence_ids: list[str]
    relationship_ids: list[str]
    model_ids: list[str]
    badges: list[DigestBadge]
    provenance: list[DigestProvenance]
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ContextCluster(BaseModel):
    id: str
    title: str
    description: str
    card_ids: list[str]


class DigestLink(BaseModel):
    id: str
    source_card_id: str
    target_card_id: str
    relationship_id: str
    relationship_type: str
    label: str
    status: str
    confidence: float


class RecommendedAction(BaseModel):
    id: str
    title: str
    summary: str
    card_ids: list[str]
    tone: BadgeTone = "gray"


class ContextDigest(BaseModel):
    workspace_id: str | None = None
    generated_at: datetime
    health: DigestHealth
    cards: list[ContextCard]
    clusters: list[ContextCluster]
    links: list[DigestLink]
    recommended_actions: list[RecommendedAction]


@router.get("/context/digest", response_model=ContextDigest)
async def get_context_digest(
    workspace_id: str | None = None,
    limit: int = 50,
    session: AsyncSession = Depends(get_db_session),
) -> ContextDigest:
    if limit < 1 or limit > 200:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 200")

    stmt = (
        select(Component)
        .options(selectinload(Component.model), selectinload(Component.source_document))
        .where(Component.status.in_(["active", "needs_review", "proposed", "stale"]))
        .order_by(Component.created_at.desc())
    )
    components = list(await session.scalars(stmt))

    workspace_id_str = workspace_id
    if workspace_id:
        try:
            workspace_id_str, connector_types = await workspace_connector_types(session, workspace_id)
        except ValueError:
            raise HTTPException(status_code=422, detail="Invalid workspace_id")
        components = filter_components_for_workspace(components, workspace_id_str, connector_types)

    comp_ids = {component.id for component in components}
    relationships: list[Relationship] = []
    if comp_ids:
        rel_stmt = (
            select(Relationship)
            .where(
                Relationship.source_component_id.in_(comp_ids),
                Relationship.target_component_id.in_(comp_ids),
                Relationship.status != "rejected",
            )
            .order_by(Relationship.created_at.desc())
        )
        relationships = list(await session.scalars(rel_stmt))

    rel_ids_by_component = _relationship_ids_by_component(relationships)
    conflict_component_ids = _component_ids_for_relationships(
        relationships,
        {"conflicts_with", "contradicts"},
    )
    blocker_component_ids = _blocked_component_ids(relationships)

    cards = [
        _component_to_card(
            component,
            rel_ids_by_component.get(component.id, []),
            conflict=component.id in conflict_component_ids,
            relationship_blocker=component.id in blocker_component_ids,
        )
        for component in components
    ]
    cards.sort(key=lambda card: (card.attention_score, card.created_at or datetime.min), reverse=True)
    cards = cards[:limit]

    visible_card_ids = {card.id for card in cards}
    links = [
        DigestLink(
            id=f"link:{rel.id}",
            source_card_id=f"component:{rel.source_component_id}",
            target_card_id=f"component:{rel.target_component_id}",
            relationship_id=str(rel.id),
            relationship_type=rel.relationship_type,
            label=relationship_display_label(rel.relationship_type, getattr(rel, "origin", "proposed")),
            status=rel.status,
            confidence=rel.confidence,
        )
        for rel in relationships
        if f"component:{rel.source_component_id}" in visible_card_ids
        and f"component:{rel.target_component_id}" in visible_card_ids
    ]

    health = _digest_health(cards)
    return ContextDigest(
        workspace_id=workspace_id_str,
        generated_at=_utcnow(),
        health=health,
        cards=cards,
        clusters=_clusters(cards),
        links=links,
        recommended_actions=_recommended_actions(cards, health),
    )


def _relationship_ids_by_component(relationships: list[Relationship]) -> dict[UUID, list[str]]:
    rel_ids: dict[UUID, list[str]] = {}
    for rel in relationships:
        rel_id = str(rel.id)
        rel_ids.setdefault(rel.source_component_id, []).append(rel_id)
        rel_ids.setdefault(rel.target_component_id, []).append(rel_id)
    return rel_ids


def _component_ids_for_relationships(
    relationships: list[Relationship],
    relationship_types: set[str],
) -> set[UUID]:
    component_ids: set[UUID] = set()
    for rel in relationships:
        if rel.relationship_type in relationship_types:
            component_ids.add(rel.source_component_id)
            component_ids.add(rel.target_component_id)
    return component_ids


def _blocked_component_ids(relationships: list[Relationship]) -> set[UUID]:
    component_ids: set[UUID] = set()
    for rel in relationships:
        if rel.relationship_type == "blocks":
            component_ids.add(rel.target_component_id)
        elif rel.relationship_type == "blocked_by":
            component_ids.add(rel.source_component_id)
    return component_ids


def _component_to_card(
    component: Component,
    relationship_ids: list[str],
    *,
    conflict: bool = False,
    relationship_blocker: bool = False,
) -> ContextCard:
    card_type = _card_type(component)
    status = _card_status(component, card_type, conflict, relationship_blocker)
    score = _attention_score(component, card_type, status, relationship_ids)
    source = component.source_document
    source_ids = [str(source.id)] if source else []
    source_type = source.source_type if source else None
    source_label = _source_label(component)
    title = _display_title(component, card_type)

    return ContextCard(
        id=f"component:{component.id}",
        title=title,
        type=card_type,
        summary=_summary(component),
        why_it_matters=_why_it_matters(component, card_type, status),
        next_action=_next_action(component, card_type, status),
        status=status,
        temporal=_temporal(component.temporal),
        confidence=round(float(component.confidence or 0), 3),
        authority_weight=round(float(component.authority_weight or 0), 3),
        attention_score=score,
        source_ids=source_ids,
        evidence_ids=[str(component.id), *source_ids],
        relationship_ids=relationship_ids,
        model_ids=[str(component.model_id)] if component.model_id else [],
        badges=_badges(component, card_type, status, source_type),
        provenance=[
            DigestProvenance(
                source_type=source_type_display(source_type),
                source_label=source_label,
                source_url=source.source_url if source else None,
                excerpt=_excerpt(component),
            )
        ],
        created_at=component.created_at,
        updated_at=source.ingested_at if source else component.created_at,
    )


def _card_type(component: Component) -> CardType:
    fact_type = (component.fact_type or "fact").lower()
    source_type = (component.source_document.source_type if component.source_document else "").lower()

    if fact_type in {"blocker", "ai_blocker"}:
        return "blocker"
    if fact_type == "risk":
        return "risk"
    if fact_type in {"decision", "ai_decision", "outcome"}:
        return "decision"
    if fact_type in {"task", "action_item", "ai_task", "issue", "github_issue", "pr", "github_pr"}:
        return "task"
    if fact_type in {"changed_file", "commit_reference"}:
        return "file"
    if fact_type in {"ai_session", "session_root", "ai_step"} or "agent" in source_type or source_type.startswith("ai_context"):
        return "agent_session"
    if fact_type in {"meeting_note", "message", "pr_review_finding", "review_finding"}:
        return "evidence"
    return "claim"


def _card_status(
    component: Component,
    card_type: CardType,
    conflict: bool,
    relationship_blocker: bool,
) -> CardStatus:
    raw_status = (component.status or "active").lower()
    if conflict:
        return "conflict"
    if card_type == "blocker" or relationship_blocker:
        return "blocked"
    if raw_status in {"stale", "deprecated", "superseded"}:
        return "stale"
    if raw_status in {"needs_review", "proposed"} or float(component.confidence or 0) < 0.6:
        return "needs_review"
    if float(component.confidence or 0) >= 0.85 and float(component.authority_weight or 0) >= 0.7:
        return "verified"
    return "active"


def _attention_score(
    component: Component,
    card_type: CardType,
    status: CardStatus,
    relationship_ids: list[str],
) -> int:
    score = 0
    if status == "blocked":
        score += 100
    if status == "conflict":
        score += 90
    if _missing_evidence(component):
        score += 70
    if float(component.confidence or 0) < 0.6:
        score += 60
    if status == "stale":
        score += 50
    if card_type == "decision" and component.status in {"needs_review", "proposed"}:
        score += 40
    if card_type == "task" and component.temporal == "future":
        score += 35
    if _is_recent(component):
        score += 25
    if len(relationship_ids) >= 3:
        score += 20
    if _is_agent_source(component):
        score += 15
    if _is_recent_agent_or_pr(component):
        score += 10
    return score


def _missing_evidence(component: Component) -> bool:
    return not (
        component.source_document_id
        or component.source_document
        or component.excerpt
        or component.provenance
    )


def _is_recent(component: Component) -> bool:
    source = component.source_document
    timestamp = source.ingested_at if source else component.created_at
    if not timestamp:
        return False
    return _utcnow() - timestamp.replace(tzinfo=None) <= timedelta(days=7)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _is_agent_source(component: Component) -> bool:
    source_type = (component.source_document.source_type if component.source_document else "").lower()
    return source_type in {"agent_session", "codex", "claude", "opencode"} or source_type.startswith("ai_context")


def _is_recent_agent_or_pr(component: Component) -> bool:
    source_type = (component.source_document.source_type if component.source_document else "").lower()
    return _is_recent(component) and (_is_agent_source(component) or source_type in {"github_pr", "github"})


def _display_title(component: Component, card_type: CardType) -> str:
    title = (component.name or "").strip() or _summary(component)
    prefixes = {
        "decision": "Decision",
        "task": "Task",
        "blocker": "Blocker",
        "risk": "Risk",
        "file": "File",
        "agent_session": "Agent session",
    }
    prefix = prefixes.get(card_type)
    if prefix and not title.lower().startswith(prefix.lower()):
        return f"{prefix}: {title}"
    return title


def _summary(component: Component) -> str:
    value = (component.value or "").strip()
    if not value:
        return (component.name or "No summary available.").strip()
    return value if len(value) <= 320 else f"{value[:317].rstrip()}..."


def _why_it_matters(component: Component, card_type: CardType, status: CardStatus) -> str:
    if status == "blocked":
        return "A future agent may continue adjacent work without clearing this blocker."
    if status == "conflict":
        return "Conflicting context can cause the next agent to choose the wrong implementation path."
    if status == "stale":
        return "This context may still influence work but should be rechecked before reuse."
    if status == "needs_review":
        return "This context is not strong enough to hand off without review."
    if card_type == "decision":
        return "Decisions constrain future work and should be visible before another agent starts."
    if card_type == "task":
        return "Tasks define the next executable work and need source-backed handoff context."
    return "This context may affect planning, implementation, or agent handoff."


def _next_action(component: Component, card_type: CardType, status: CardStatus) -> str:
    if status == "blocked":
        return "Assign an owner or generate an agent pack for the blocker."
    if status == "conflict":
        return "Review the evidence path and mark the winning context verified."
    if status == "stale":
        return "Re-open the source and mark this current or stale."
    if status == "needs_review":
        return "Verify the source evidence before including it in an agent pack."
    if card_type in {"task", "decision", "blocker", "risk"}:
        return "Include this in the next agent pack if it matches the goal."
    return "Keep as supporting context with citations."


def _temporal(value: str | None) -> CardTemporal:
    raw = (value or "unknown").lower()
    return raw if raw in {"past", "current", "future", "unknown"} else "unknown"


def _badges(
    component: Component,
    card_type: CardType,
    status: CardStatus,
    source_type: str | None,
) -> list[DigestBadge]:
    badges = [
        DigestBadge(label=card_type.replace("_", " ").title(), tone=_type_tone(card_type)),
        DigestBadge(label=source_type_display(source_type), tone=_source_tone(source_type)),
        DigestBadge(label=_confidence_label(component.confidence), tone=_confidence_tone(component.confidence)),
    ]
    if status not in {"active", "verified"}:
        badges.append(DigestBadge(label=status.replace("_", " ").title(), tone=_status_tone(status)))
    return badges


def _type_tone(card_type: CardType) -> BadgeTone:
    return {
        "blocker": "red",
        "risk": "amber",
        "decision": "violet",
        "task": "blue",
        "agent_session": "green",
        "file": "gray",
        "evidence": "green",
    }.get(card_type, "gray")


def _source_tone(source_type: str | None) -> BadgeTone:
    source = (source_type or "").lower()
    if "github" in source:
        return "blue"
    if "agent" in source or source.startswith("ai_context") or source in {"codex", "claude", "opencode"}:
        return "violet"
    if source in {"slack", "gmail", "gdrive"}:
        return "green"
    return "gray"


def _confidence_label(confidence: float | None) -> str:
    return f"{round(float(confidence or 0) * 100)}% confidence"


def _confidence_tone(confidence: float | None) -> BadgeTone:
    value = float(confidence or 0)
    if value >= 0.8:
        return "green"
    if value >= 0.6:
        return "amber"
    return "red"


def _status_tone(status: CardStatus) -> BadgeTone:
    return {
        "blocked": "red",
        "conflict": "red",
        "needs_review": "amber",
        "stale": "amber",
        "verified": "green",
    }.get(status, "gray")


def _source_label(component: Component) -> str:
    source = component.source_document
    if not source:
        return "Unknown source"
    metadata = metadata_dict(source)
    for key in (
        "title",
        "subject",
        "repo_full_name",
        "session_id",
        "thread_id",
        "channel_name",
        "file_path",
        "file_name",
    ):
        value = metadata.get(key)
        if value:
            return str(value)
    return source.external_id or source_type_display(source.source_type)


def _excerpt(component: Component) -> str | None:
    excerpt = (component.excerpt or component.provenance or "").strip()
    if not excerpt:
        excerpt = (component.value or "").strip()
    if not excerpt:
        return None
    return excerpt if len(excerpt) <= 260 else f"{excerpt[:257].rstrip()}..."


def _digest_health(cards: list[ContextCard]) -> DigestHealth:
    total = len(cards)
    blocker_count = sum(1 for card in cards if card.status == "blocked" or card.type == "blocker")
    conflict_count = sum(1 for card in cards if card.status == "conflict")
    stale_count = sum(1 for card in cards if card.status == "stale")
    unverified_count = sum(
        1
        for card in cards
        if card.status in {"needs_review", "stale", "conflict"} or card.confidence < 0.7
    )
    if total == 0:
        return DigestHealth(
            status="empty",
            summary="No context has been extracted yet.",
            blocker_count=0,
            conflict_count=0,
            stale_count=0,
            unverified_count=0,
            agent_ready_score=0,
        )

    score = max(0, min(100, 100 - blocker_count * 12 - conflict_count * 10 - unverified_count * 3 - stale_count * 4))
    if blocker_count or conflict_count:
        status: HealthStatus = "critical"
    elif unverified_count or stale_count:
        status = "needs_review"
    else:
        status = "healthy"
    summary = (
        f"{blocker_count} blockers, {conflict_count} conflicts, "
        f"{unverified_count} unverified cards."
    )
    return DigestHealth(
        status=status,
        summary=summary,
        blocker_count=blocker_count,
        conflict_count=conflict_count,
        stale_count=stale_count,
        unverified_count=unverified_count,
        agent_ready_score=score,
    )


def _clusters(cards: list[ContextCard]) -> list[ContextCluster]:
    attention = [
        card
        for card in cards
        if card.status in {"blocked", "conflict", "needs_review", "stale"} or card.attention_score >= 70
    ]
    changed = sorted(cards, key=lambda card: card.updated_at or card.created_at or datetime.min, reverse=True)
    decisions = [card for card in cards if card.type == "decision"]
    handoff = [
        card
        for card in cards
        if card.type in {"task", "decision", "blocker", "risk", "agent_session", "file"}
        and card.status != "stale"
    ]
    return [
        ContextCluster(
            id="needs_attention",
            title="Needs Attention",
            description="Blockers, conflicts, stale assumptions, and low-confidence claims.",
            card_ids=[card.id for card in attention[:12]],
        ),
        ContextCluster(
            id="changed_recently",
            title="Changed Recently",
            description="Fresh source evidence and recently extracted context.",
            card_ids=[card.id for card in changed[:12]],
        ),
        ContextCluster(
            id="open_decisions",
            title="Open Decisions",
            description="Decisions and assumptions that constrain future work.",
            card_ids=[card.id for card in decisions[:12]],
        ),
        ContextCluster(
            id="agent_handoff",
            title="Next Agent Should Know",
            description="Ranked context worth considering for an agent pack.",
            card_ids=[card.id for card in handoff[:12]],
        ),
    ]


def _recommended_actions(cards: list[ContextCard], health: DigestHealth) -> list[RecommendedAction]:
    actions: list[RecommendedAction] = []
    blockers = [card.id for card in cards if card.status == "blocked" or card.type == "blocker"]
    conflicts = [card.id for card in cards if card.status == "conflict"]
    unverified = [card.id for card in cards if card.status == "needs_review" or card.confidence < 0.7]

    if blockers:
        actions.append(RecommendedAction(
            id="resolve_blockers",
            title="Resolve blockers",
            summary="Generate a focused agent pack around the highest scoring blockers.",
            card_ids=blockers[:8],
            tone="red",
        ))
    if conflicts:
        actions.append(RecommendedAction(
            id="review_conflicts",
            title="Review conflicts",
            summary="Inspect relationship evidence and verify the winning context.",
            card_ids=conflicts[:8],
            tone="amber",
        ))
    if unverified:
        actions.append(RecommendedAction(
            id="verify_context",
            title="Verify handoff context",
            summary="Mark low-confidence or proposed context before including it in an agent pack.",
            card_ids=unverified[:8],
            tone="blue",
        ))
    if not cards:
        actions.append(RecommendedAction(
            id="build_context",
            title="Build context",
            summary="Import sources and run graph build to create digest cards.",
            card_ids=[],
            tone="gray",
        ))
    elif health.agent_ready_score >= 75:
        actions.append(RecommendedAction(
            id="generate_agent_pack",
            title="Generate agent pack",
            summary="The current digest is ready enough to assemble a source-backed handoff.",
            card_ids=[card.id for card in cards[:10]],
            tone="green",
        ))
    return actions
