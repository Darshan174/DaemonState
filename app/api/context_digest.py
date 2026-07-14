from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db_session
from app.models import (
    AgentRun,
    ClaimRevision,
    Component,
    Connector,
    ContextPack,
    EvidenceSpan,
    Relationship,
    SourceDocument,
)
from app.services.workspace_scope import (
    current_source_documents,
    filter_explicit_source_documents_for_workspace,
    metadata_dict,
    workspace_connector_types,
    workspace_scope_exists,
)
from app.services.evidence import sha256_text
from app.services.session_summary import derive_session_topic
from app.services.project_scope import workspace_references, workspace_relevance
from app.taxonomy import relationship_display_label, source_type_display
from app.time import utc_now

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
CardCategory = Literal[
    "agent_session", "decision", "pull_request", "issue", "blocker",
    "code_area", "document_finding", "task", "supporting_evidence",
]


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
    source_document_id: str | None = None
    revision_number: int | None = None
    verification_status: str | None = None


class CardClassification(BaseModel):
    basis: Literal["source_metadata", "fact_type", "verified_relationship", "supporting_only"]
    reason: str


class WorkspaceRelevance(BaseModel):
    status: Literal["relevant", "unknown", "not_relevant"]
    reasons: list[str]


class SourceSnapshot(BaseModel):
    source_document_id: str
    source_type: str
    external_id: str
    source_url: str | None = None
    revision_number: int
    content_sha256: str | None = None
    ingested_at: datetime | None = None
    processed_at: datetime | None = None
    provider_updated_at: datetime | None = None
    last_successful_sync_at: datetime | None = None
    provider_state: Literal["open", "closed", "merged", "draft", "unknown", "not_applicable"]
    freshness: Literal["observed", "stale", "unknown", "not_remote"]


class CardEvidence(BaseModel):
    evidence_span_id: str | None = None
    start_char: int | None = None
    end_char: int | None = None
    excerpt: str | None = None
    verification_status: Literal["verified", "needs_review", "unavailable"]


class DigestObjective(BaseModel):
    status: Literal["supplied", "not_supplied"]
    text: str | None = None
    source_kind: Literal["active_agent_run", "context_pack"] | None = None
    source_id: str | None = None
    recorded_at: datetime | None = None
    source_document_id: str | None = None
    excerpt: str | None = None


class ContextCard(BaseModel):
    id: str
    title: str
    type: CardType
    category: CardCategory
    classification: CardClassification
    workspace_relevance: WorkspaceRelevance
    source_snapshot: SourceSnapshot
    evidence: CardEvidence
    freshness: dict
    session: dict | None = None
    remote_item: dict | None = None
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
    origin: str
    evidence: str
    source_component_document_id: str | None = None


class RecommendedAction(BaseModel):
    id: str
    title: str
    summary: str
    card_ids: list[str]
    tone: BadgeTone = "gray"


class ContextDigest(BaseModel):
    workspace_id: str | None = None
    generated_at: datetime
    objective: DigestObjective
    scope: dict
    build: dict
    freshness: dict
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

    all_documents = list(await session.scalars(select(SourceDocument)))
    workspace_id_str = workspace_id
    if workspace_id:
        try:
            workspace_id_str, _ = await workspace_connector_types(session, workspace_id)
        except ValueError:
            raise HTTPException(status_code=422, detail="Invalid workspace_id")
        if not await workspace_scope_exists(session, workspace_id_str):
            raise HTTPException(status_code=404, detail="Workspace not found")
        scoped_documents = filter_explicit_source_documents_for_workspace(
            all_documents, workspace_id_str
        )
    else:
        scoped_documents = all_documents

    current_documents, _ = current_source_documents(scoped_documents)
    current_source_ids = {doc.id for doc in current_documents}
    stmt = (
        select(Component)
        .options(selectinload(Component.model), selectinload(Component.source_document))
        .where(Component.status.in_(["active", "needs_review", "proposed", "stale"]))
        .where(Component.source_document_id.in_(current_source_ids))
        .order_by(Component.created_at.desc())
    )
    components = list(await session.scalars(stmt)) if current_source_ids else []

    comp_ids = {component.id for component in components}
    components_by_id = {component.id: component for component in components}
    relationships: list[Relationship] = []
    if comp_ids:
        rel_stmt = (
            select(Relationship)
            .where(
                Relationship.source_component_id.in_(comp_ids),
                Relationship.target_component_id.in_(comp_ids),
                Relationship.status.not_in(["rejected", "superseded"]),
            )
            .order_by(Relationship.created_at.desc())
        )
        relationships = list(await session.scalars(rel_stmt))

    factual_relationships = [
        relationship for relationship in relationships
        if relationship.origin in {"deterministic", "extracted", "human_verified"}
        and bool(relationship.evidence)
    ]
    rel_ids_by_component = _relationship_ids_by_component(factual_relationships)
    conflict_component_ids = _component_ids_for_relationships(
        factual_relationships,
        {"conflicts_with", "contradicts"},
    )
    blocker_component_ids = _blocked_component_ids(factual_relationships)
    evidence_by_component = await _evidence_by_component(session, components)
    github_last_sync = await _github_last_sync(session, workspace_id_str)
    workspace_repositories, workspace_paths, workspace_commits = await workspace_references(
        session, workspace_id_str
    )

    # Session roots are the durable representation of an imported agent run.
    # Their transcript preview can legitimately contain prompt-like language,
    # so generic noise rules must only apply to extracted child facts.
    components = [
        component
        for component in components
        if (component.fact_type or "").lower() in {"session_root", "ai_session"}
        or not _is_digest_noise_component(component)
    ]

    cards: list[ContextCard] = []
    session_source_ids: set[UUID] = set()
    excluded_irrelevant_sources: set[UUID] = set()
    for component in components:
        if (component.fact_type or "").lower() in {"session_root", "ai_session"}:
            if component.source_document_id in session_source_ids:
                continue
            session_source_ids.add(component.source_document_id)
        card = _component_to_card(
            component,
            rel_ids_by_component.get(component.id, []),
            evidence=evidence_by_component.get(component.id),
            github_last_sync=github_last_sync,
            workspace_repositories=workspace_repositories,
            workspace_paths=workspace_paths,
            workspace_commits=workspace_commits,
            conflict=component.id in conflict_component_ids,
            relationship_blocker=component.id in blocker_component_ids,
        )
        is_session_source = _is_agent_source(component)
        is_session_root = (component.fact_type or "").lower() in {"session_root", "ai_session"}
        if (
            workspace_id_str
            and is_session_source
            and card.workspace_relevance.status != "relevant"
            and not is_session_root
        ):
            if card.workspace_relevance.status == "not_relevant":
                excluded_irrelevant_sources.add(component.source_document_id)
            continue
        if card.workspace_relevance.status == "not_relevant":
            excluded_irrelevant_sources.add(component.source_document_id)
        cards.append(card)
    relevance_priority = {"relevant": 2, "unknown": 1, "not_relevant": 0}
    all_session_roots = [card for card in cards if card.category == "agent_session"]
    candidate_session_count = len(all_session_roots)
    unknown_relevance_source_count = len({
        card.source_snapshot.source_document_id
        for card in all_session_roots
        if card.workspace_relevance.status == "unknown"
    })

    # A digest limit must not silently erase peripheral sessions behind a large
    # number of relevant extracted facts. Reserve space for session roots first,
    # ordered by attention/recency without using relevance as a visibility gate.
    all_session_roots.sort(
        key=lambda card: (
            card.attention_score,
            card.created_at or datetime.min,
        ),
        reverse=True,
    )
    supporting_cards = [card for card in cards if card.category != "agent_session"]
    supporting_cards.sort(
        key=lambda card: (
            relevance_priority.get(card.workspace_relevance.status, 0),
            card.attention_score,
            card.created_at or datetime.min,
        ),
        reverse=True,
    )
    cards = all_session_roots[:limit]
    cards.extend(supporting_cards[:max(0, limit - len(cards))])
    cards.sort(
        key=lambda card: (
            relevance_priority.get(card.workspace_relevance.status, 0),
            card.attention_score,
            card.created_at or datetime.min,
        ),
        reverse=True,
    )

    visible_card_ids = {
        card.id for card in cards
        if not workspace_id_str or card.workspace_relevance.status == "relevant"
    }
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
            origin=rel.origin or "proposed",
            evidence=rel.evidence,
            source_component_document_id=(
                str(components_by_id[rel.source_component_id].source_document_id)
                if components_by_id.get(rel.source_component_id)
                and components_by_id[rel.source_component_id].source_document_id
                else None
            ),
        )
        for rel in factual_relationships
        if f"component:{rel.source_component_id}" in visible_card_ids
        and f"component:{rel.target_component_id}" in visible_card_ids
    ]

    project_cards = (
        [card for card in cards if card.workspace_relevance.status == "relevant"]
        if workspace_id_str
        else cards
    )
    health = _digest_health(project_cards)
    return ContextDigest(
        workspace_id=workspace_id_str,
        generated_at=utc_now(),
        objective=await _digest_objective(session, workspace_id_str),
        scope={
            "included_source_count": len({card.source_snapshot.source_document_id for card in project_cards}),
            "excluded_unscoped_source_count": sum(
                1 for doc in all_documents
                if doc.workspace_id is None and not metadata_dict(doc).get("workspace_id")
            ) if workspace_id else 0,
            "excluded_irrelevant_source_count": len(excluded_irrelevant_sources),
            "candidate_session_count": candidate_session_count,
            "unknown_relevance_source_count": unknown_relevance_source_count,
            "pending_source_count": sum(1 for doc in current_documents if doc.processed_at is None),
            "project_paths": sorted(workspace_paths),
            "project_repositories": sorted(workspace_repositories),
        },
        build={
            "status": "pending" if any(doc.processed_at is None for doc in current_documents) else "up_to_date",
            "mode": None,
            "remote_sources_refreshed": False,
            "last_built_at": max(
                (doc.processed_at for doc in current_documents if doc.processed_at),
                default=None,
            ),
        },
        freshness=_freshness_summary(project_cards),
        health=health,
        cards=cards,
        clusters=_clusters(project_cards),
        links=links,
        recommended_actions=_recommended_actions(project_cards, health),
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


def _is_digest_noise_component(component: Component) -> bool:
    if _looks_like_agent_session_fragment(component):
        return True

    fact_type = (component.fact_type or "").lower()
    if fact_type in {
        "decision", "blocker", "risk", "task", "action_item",
        "ai_decision", "ai_blocker", "ai_task",
    }:
        for claim_text in (component.value, component.name):
            unlabelled = re.sub(
                r"^\s*(?:decision|task|risk|blocker|file|session|agent session)\s*:\s*",
                "",
                str(claim_text or ""),
                flags=re.IGNORECASE,
            ).lstrip()
            if re.match(r"^[,;:]", unlabelled):
                return True

    fields = [
        component.name,
        component.value,
        component.excerpt,
        component.provenance,
    ]
    source = component.source_document
    if source:
        fields.extend([
            source.external_id,
            source.source_url,
        ])
    text = " ".join(str(value) for value in fields if value)
    if _looks_like_digest_noise(text):
        return True

    clean = _clean_digest_text(" ".join(str(value) for value in (component.name, component.value, component.excerpt) if value))
    words = re.findall(r"[A-Za-z][A-Za-z0-9'-]{2,}", clean)
    if len(words) < 2 and fact_type in {"decision", "blocker", "risk", "ai_decision", "ai_blocker"}:
        return True
    return False


def _looks_like_agent_session_fragment(component: Component) -> bool:
    source_type = (component.source_document.source_type if component.source_document else "").lower()
    if not (
        source_type in {"agent_session", "codex", "claude", "opencode"}
        or source_type.startswith("ai_context")
    ):
        return False

    fact_type = (component.fact_type or "").lower()
    if fact_type not in {"decision", "blocker", "risk", "task", "action_item", "ai_decision", "ai_blocker", "ai_task"}:
        return False

    text = _strip_digest_label(_clean_digest_text(component.value or component.name or component.excerpt))
    if not text:
        return True
    words = re.findall(r"[A-Za-z][A-Za-z0-9'-]{2,}", text)
    if len(words) < 3:
        return True
    if re.match(r"^[,.;:]", text):
        return True
    if re.match(r"^[A-Za-z]\b[,.;:]?", text):
        return True
    if re.match(
        r"^(?:and|or|but|then|before|after|while|because|only because|once|when|whether|"
        r"which|that|is|are|was|were|appears)\b",
        text,
        re.IGNORECASE,
    ):
        return True
    if re.match(r"^\w{1,12},\s+(?:and|then|but|so)\b", text, re.IGNORECASE):
        return True
    if re.search(r"\b(?:I(?:'|’)m|I(?:'|’)ll|I am|I will)\b", text):
        return True
    if re.search(r"\bnext pass will\b", text, re.IGNORECASE):
        return True
    return False


def _strip_digest_label(text: str) -> str:
    return re.sub(
        r"^\s*(?:decision|task|risk|blocker|file|session|agent session)\s*:\s*",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip()


def _looks_like_digest_noise(value: str | None) -> bool:
    text = str(value or "")
    if not text.strip():
        return False
    if re.search(r"data:image/|base64|[A-Za-z0-9+/]{180,}={0,2}", text, re.IGNORECASE):
        return True
    if re.search(
        r"\b(base_instructions|permissions instructions|developer instructions|system message|"
        r"knowledge cutoff|request escalation|prefix_rule|sandbox_permissions|"
        r"function_call|function_call_output|internal_chat_message_metadata|local_images|"
        r"session_meta|tool_call|do not revert unrelated|working with the user)\b",
        text,
        re.IGNORECASE,
    ):
        return True
    compact = re.sub(r"\s+", "", text)
    if len(compact) >= 12:
        noisy_chars = sum(1 for ch in compact if ch in "/.\\{}[]<>_=+:;|")
        word_count = len(re.findall(r"[A-Za-z][A-Za-z0-9'-]{2,}", text))
        if word_count < 3 and noisy_chars / max(1, len(compact)) > 0.34:
            return True
    return False


def _clean_digest_text(value: str | None) -> str:
    text = str(value or "")
    text = re.sub(r"\s+From:\s+[^<\n]*<[^>]+>[\s\S]*$", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+Reply to this email[\s\S]*$", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"data:image/[a-z0-9.+-]+;base64,\S+", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"[A-Za-z0-9+/]{140,}={0,2}", " ", text)
    text = re.sub(r"[*_`>\[\](){}\"]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(
        r"^(\s*(?:decision|task|risk|blocker|file|session|agent session)\s*:)"
        r"\s*[,.;:!?…\-–—]+\s*",
        r"\1 ",
        text,
        flags=re.IGNORECASE,
    )
    return re.sub(r"^[,./\\\s:;!?…\-–—]+|[,./\\\s:;!?…\-–—]+$", "", text)


async def _evidence_by_component(
    session: AsyncSession,
    components: list[Component],
) -> dict[UUID, EvidenceSpan]:
    claim_ids = {component.claim_id for component in components if component.claim_id}
    if not claim_ids:
        return {}
    revisions = list(await session.scalars(
        select(ClaimRevision).where(ClaimRevision.claim_id.in_(claim_ids))
        .order_by(ClaimRevision.created_at.desc(), ClaimRevision.id.desc())
    ))
    latest_by_claim: dict[UUID, ClaimRevision] = {}
    for revision in revisions:
        latest_by_claim.setdefault(revision.claim_id, revision)
    span_ids = {revision.evidence_span_id for revision in latest_by_claim.values()}
    spans = {
        span.id: span for span in await session.scalars(
            select(EvidenceSpan).where(EvidenceSpan.id.in_(span_ids))
        )
    } if span_ids else {}
    return {
        component.id: spans[latest_by_claim[component.claim_id].evidence_span_id]
        for component in components
        if component.claim_id in latest_by_claim
        and latest_by_claim[component.claim_id].evidence_span_id in spans
    }


async def _github_last_sync(
    session: AsyncSession,
    workspace_id: str | None,
) -> datetime | None:
    if not workspace_id:
        return None
    return await session.scalar(
        select(Connector.last_sync_at)
        .where(
            Connector.workspace_id == UUID(workspace_id),
            Connector.connector_type == "github",
            Connector.status == "connected",
        )
        .order_by(Connector.last_sync_at.desc())
        .limit(1)
    )


def _evidence_read(source: SourceDocument, evidence: EvidenceSpan | None) -> CardEvidence:
    if evidence is None:
        return CardEvidence(verification_status="unavailable")
    exact = (
        evidence.start_char is not None
        and evidence.end_char is not None
        and 0 <= evidence.start_char < evidence.end_char <= len(source.content or "")
        and (source.content or "")[evidence.start_char:evidence.end_char] == (evidence.text or "")
        and sha256_text(evidence.text or "") == evidence.text_sha256
    )
    verified = exact and evidence.review_status == "verified"
    return CardEvidence(
        evidence_span_id=str(evidence.id),
        start_char=evidence.start_char,
        end_char=evidence.end_char,
        excerpt=evidence.text,
        verification_status="verified" if verified else "needs_review",
    )


def _classify_component(
    component: Component,
    metadata: dict,
    evidence: CardEvidence,
    *,
    relationship_blocker: bool,
) -> tuple[CardCategory, CardClassification]:
    fact_type = (component.fact_type or "").lower()
    source_type = (component.source_document.source_type or "").lower()
    item_type = str(metadata.get("item_type") or "").lower()
    source_url = str(metadata.get("source_url") or "")
    url_matches_type = (
        (item_type == "pull_request" and "/pull/" in source_url)
        or (item_type == "issue" and "/issues/" in source_url)
    )
    has_remote_identity = bool(
        metadata.get("repo_full_name")
        and isinstance(metadata.get("number"), int)
        and metadata.get("number") > 0
        and source_url
        and url_matches_type
    )
    if fact_type == "pr" and item_type == "pull_request" and has_remote_identity:
        return "pull_request", CardClassification(
            basis="source_metadata", reason="Typed GitHub pull-request metadata and PR root fact."
        )
    if fact_type == "issue" and item_type == "issue" and has_remote_identity:
        return "issue", CardClassification(
            basis="source_metadata", reason="Typed GitHub issue metadata and issue root fact."
        )
    if fact_type in {"session_root", "ai_session"}:
        return "agent_session", CardClassification(
            basis="fact_type", reason="One root fact for an imported AI session."
        )
    if fact_type in {"repo_root", "code_area"} and source_type == "local_repository":
        return "code_area", CardClassification(
            basis="fact_type",
            reason="Deterministic repository inventory from the selected local project.",
        )
    is_agent_source = (
        source_type in {"agent_session", "codex", "claude", "opencode"}
        or source_type.startswith("ai_context")
    )
    human_confirmed = bool(
        metadata.get("verified_by_human") is True
        or str(metadata.get("verification_status") or "").lower() == "human_verified"
    )
    if (
        fact_type in {"decision", "ai_decision"}
        and evidence.verification_status == "verified"
        and (not is_agent_source or human_confirmed)
    ):
        return "decision", CardClassification(
            basis="fact_type", reason="Typed decision with an exact verified source range."
        )
    if (
        fact_type in {"task", "action_item"}
        and evidence.verification_status == "verified"
        and (not is_agent_source or human_confirmed)
    ):
        return "task", CardClassification(
            basis="fact_type", reason="Typed task with an exact verified source range."
        )
    if (
        fact_type in {"blocker", "ai_blocker"}
        and (component.temporal or "").lower() == "current"
        and evidence.verification_status == "verified"
        and (not is_agent_source or human_confirmed)
    ):
        return "blocker", CardClassification(
            basis="fact_type", reason="Current typed blocker with exact verified evidence."
        )
    if (
        relationship_blocker
        and evidence.verification_status == "verified"
        and (not is_agent_source or human_confirmed)
    ):
        return "blocker", CardClassification(
            basis="verified_relationship", reason="Verified evidence participates in a blocking edge."
        )
    if (
        fact_type == "document_finding"
        and evidence.verification_status == "verified"
        and metadata.get("document_path")
        and metadata.get("finding_type") in {"broken", "stale", "missing", "incorrect"}
    ):
        return "document_finding", CardClassification(
            basis="fact_type", reason="Typed document finding with path, finding type, and verified evidence."
        )
    return "supporting_evidence", CardClassification(
        basis="supporting_only",
        reason="The source lacks the typed metadata or verified evidence required for a named panel.",
    )


def _source_snapshot(
    source: SourceDocument,
    metadata: dict,
    github_last_sync: datetime | None,
) -> SourceSnapshot:
    is_remote = str(metadata.get("item_type") or "") in {"issue", "pull_request"}
    provider_updated_at = _parse_datetime(metadata.get("updated_at"))
    provider_state = "not_applicable"
    if is_remote:
        if metadata.get("merged") or metadata.get("merged_at"):
            provider_state = "merged"
        elif metadata.get("draft"):
            provider_state = "draft"
        elif str(metadata.get("state") or "").lower() in {"open", "closed"}:
            provider_state = str(metadata.get("state")).lower()
        else:
            provider_state = "unknown"
    # Connector.last_sync_at proves only that a connector job finished. It does
    # not prove this individual item was returned (syncs can be partial and are
    # capped). Until per-source observations are persisted, remote freshness is
    # intentionally unknown and provider state is described as an imported
    # snapshot.
    freshness = "unknown" if is_remote else "not_remote"
    return SourceSnapshot(
        source_document_id=str(source.id),
        source_type=source.source_type,
        external_id=source.external_id,
        source_url=source.source_url,
        revision_number=int(source.revision_number or 1),
        content_sha256=source.content_sha256,
        ingested_at=source.ingested_at,
        processed_at=source.processed_at,
        provider_updated_at=provider_updated_at,
        last_successful_sync_at=None,
        provider_state=provider_state,
        freshness=freshness,
    )


def _session_info(source: SourceDocument, metadata: dict) -> dict:
    session_id = str(metadata.get("session_id") or source.external_id)
    tool = metadata.get("tool") or metadata.get("agent_tool")
    topic = derive_session_topic(
        source.content,
        explicit_title=metadata.get("title"),
        tool=str(tool or ""),
        session_id=session_id,
    )
    title = topic or f"{str(tool or 'AI').title()} session"
    return {
        "session_id": session_id,
        "title": title,
        "topic": topic,
        "tool": tool,
        "model": metadata.get("model") or metadata.get("agent_model"),
        "started_at": metadata.get("started_at") or metadata.get("created_at"),
        "ended_at": metadata.get("ended_at") or metadata.get("updated_at"),
        "message_count": metadata.get("message_count"),
        "cwd": metadata.get("cwd") or metadata.get("working_directory"),
        "repository": metadata.get("repository") or metadata.get("repo_full_name") or metadata.get("repo"),
        "branch": metadata.get("branch"),
        "commit": metadata.get("commit"),
        "content_available": bool(source.content),
        "inspection_source_id": str(source.id),
    }


def _remote_item(metadata: dict, snapshot: SourceSnapshot) -> dict:
    return {
        "kind": metadata.get("item_type"),
        "repository": metadata.get("repo_full_name"),
        "repo_full_name": metadata.get("repo_full_name"),
        "number": metadata.get("number"),
        "title": metadata.get("title"),
        "provider_state": snapshot.provider_state,
        "observed_status": snapshot.provider_state,
        "provider_updated_at": snapshot.provider_updated_at,
        "last_successful_sync_at": snapshot.last_successful_sync_at,
    }


def _parse_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


async def _digest_objective(
    session: AsyncSession,
    workspace_id: str | None,
) -> DigestObjective:
    if workspace_id:
        workspace_uuid = UUID(workspace_id)
        run = await session.scalar(
            select(AgentRun)
            .where(
                AgentRun.workspace_id == workspace_uuid,
                AgentRun.objective.is_not(None),
                AgentRun.status == "running",
                AgentRun.ended_at.is_(None),
            )
            .order_by(AgentRun.started_at.desc(), AgentRun.id.desc())
            .limit(1)
        )
        if run and run.objective and run.objective.strip():
            return DigestObjective(
                status="supplied",
                text=run.objective.strip(),
                source_kind="active_agent_run",
                source_id=str(run.id),
                recorded_at=run.started_at,
                excerpt=run.objective.strip(),
            )
        packs = list(await session.scalars(
            select(ContextPack)
            .where(ContextPack.workspace_id == workspace_uuid)
            .order_by(ContextPack.created_at.desc(), ContextPack.id.desc())
            .limit(20)
        ))
        for pack in packs:
            try:
                manifest = json.loads(pack.manifest or "{}")
            except (json.JSONDecodeError, TypeError):
                manifest = {}
            if manifest.get("objective_kind") == "project_snapshot":
                continue
            if pack.objective and pack.objective.strip():
                return DigestObjective(
                    status="supplied",
                    text=pack.objective.strip(),
                    source_kind="context_pack",
                    source_id=str(pack.id),
                    recorded_at=pack.created_at,
                    excerpt=pack.objective.strip(),
                )
    return DigestObjective(status="not_supplied")


def _freshness_summary(cards: list[ContextCard]) -> dict:
    remote_cards = [card for card in cards if card.source_snapshot.freshness != "not_remote"]
    return {
        "observed": sum(card.source_snapshot.freshness == "observed" for card in remote_cards),
        "stale": sum(card.source_snapshot.freshness == "stale" for card in remote_cards),
        "unknown": sum(card.source_snapshot.freshness == "unknown" for card in remote_cards),
    }


def _component_to_card(
    component: Component,
    relationship_ids: list[str],
    *,
    evidence: EvidenceSpan | None = None,
    github_last_sync: datetime | None = None,
    workspace_repositories: set[str] | None = None,
    workspace_paths: set[str] | None = None,
    workspace_commits: set[str] | None = None,
    conflict: bool = False,
    relationship_blocker: bool = False,
) -> ContextCard:
    card_type = _card_type(component)
    source = component.source_document
    source_ids = [str(source.id)] if source else []
    source_type = source.source_type if source else None
    source_label = _source_label(component)
    title = _display_title(component, card_type)
    metadata = metadata_dict(source) if source else {}
    if source and source.source_url:
        metadata.setdefault("source_url", source.source_url)
    evidence_read = _evidence_read(source, evidence)
    category, classification = _classify_component(
        component,
        metadata,
        evidence_read,
        relationship_blocker=relationship_blocker,
    )
    status = _card_status(
        component,
        "blocker" if category == "blocker" else card_type,
        conflict,
        relationship_blocker and category == "blocker",
    )
    if category != "blocker" and status == "blocked" and not conflict:
        status = "needs_review"
    score = _attention_score(component, card_type, status, relationship_ids)
    project_relevance = workspace_relevance(
        component,
        metadata,
        workspace_repositories or set(),
        workspace_paths or set(),
        workspace_commits or set(),
    )
    relevance = WorkspaceRelevance(
        status=project_relevance.status,
        reasons=project_relevance.reasons,
    )
    source_snapshot = _source_snapshot(source, metadata, github_last_sync)
    session_info = _session_info(source, metadata) if category == "agent_session" else None
    remote_item = _remote_item(metadata, source_snapshot) if category in {"pull_request", "issue"} else None

    return ContextCard(
        id=f"component:{component.id}",
        title=title,
        type=card_type,
        category=category,
        classification=classification,
        workspace_relevance=relevance,
        source_snapshot=source_snapshot,
        evidence=evidence_read,
        freshness={
            "status": source_snapshot.freshness,
            "provider_updated_at": source_snapshot.provider_updated_at,
            "last_successful_sync_at": source_snapshot.last_successful_sync_at,
        },
        session=session_info,
        remote_item=remote_item,
        summary=_summary(component),
        why_it_matters=_why_it_matters(component, card_type, status),
        next_action=_next_action(component, card_type, status),
        status=status,
        temporal=_temporal(component.temporal),
        confidence=round(float(component.confidence or 0), 3),
        authority_weight=round(float(component.authority_weight or 0), 3),
        attention_score=score,
        source_ids=source_ids,
        evidence_ids=[evidence_read.evidence_span_id] if evidence_read.evidence_span_id else [],
        relationship_ids=relationship_ids,
        model_ids=[str(component.model_id)] if component.model_id else [],
        badges=_badges(component, card_type, status, source_type),
        provenance=[
            DigestProvenance(
                source_type=source_type_display(source_type),
                source_label=source_label,
                source_url=source.source_url if source else None,
                excerpt=_excerpt(component),
                source_document_id=str(source.id) if source else None,
                revision_number=int(source.revision_number or 1) if source else None,
                verification_status=evidence_read.verification_status,
            )
        ],
        created_at=component.created_at,
        updated_at=source.ingested_at if source else component.created_at,
    )


def _card_type(component: Component) -> CardType:
    fact_type = (component.fact_type or "fact").lower()
    source_type = (component.source_document.source_type if component.source_document else "").lower()

    if fact_type == "risk":
        return "risk"
    if fact_type in {"blocker", "ai_blocker"}:
        title = _clean_digest_text(component.name)
        if title.lower().startswith("risk:"):
            return "risk"
        return "blocker"
    if fact_type in {"decision", "ai_decision", "outcome"}:
        return "decision"
    if fact_type in {"task", "action_item", "ai_task", "issue", "github_issue", "pr", "github_pr"}:
        return "task"
    if fact_type in {"changed_file", "commit_reference", "repo_root", "code_area"}:
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
    return utc_now() - timestamp.replace(tzinfo=None) <= timedelta(days=7)


def _is_agent_source(component: Component) -> bool:
    source_type = (component.source_document.source_type if component.source_document else "").lower()
    return source_type in {"agent_session", "codex", "claude", "opencode"} or source_type.startswith("ai_context")


def _is_recent_agent_or_pr(component: Component) -> bool:
    source_type = (component.source_document.source_type if component.source_document else "").lower()
    return _is_recent(component) and (_is_agent_source(component) or source_type in {"github_pr", "github"})


def _display_title(component: Component, card_type: CardType) -> str:
    title = _clean_digest_text(component.name) or _summary(component)
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
    value = _clean_digest_text(component.value)
    if not value:
        return _clean_digest_text(component.name) or "No summary available."
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
            return _clean_digest_text(value) or source_type_display(source.source_type)
    return _clean_digest_text(source.external_id) or source_type_display(source.source_type)


def _excerpt(component: Component) -> str | None:
    excerpt = _clean_digest_text(component.excerpt or component.provenance)
    if not excerpt:
        excerpt = _clean_digest_text(component.value)
    if not excerpt:
        return None
    return excerpt if len(excerpt) <= 260 else f"{excerpt[:257].rstrip()}..."


def _digest_health(cards: list[ContextCard]) -> DigestHealth:
    total = len(cards)
    blocker_count = sum(1 for card in cards if card.category == "blocker")
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
    blockers = [card.id for card in cards if card.category == "blocker"]
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
