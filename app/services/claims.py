from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Claim,
    ClaimRevision,
    Component,
    EvidenceSpan,
    Relationship,
    SourceDocument,
)
from app.services.evidence import EvidenceSpanResult, create_evidence_span_for_fact, sha256_text
from app.services.identity import identity_key_for_component_name
from app.taxonomy import canonical_fact_type, canonical_temporal


@dataclass(frozen=True)
class ClaimWriteResult:
    claim: Claim
    revision: ClaimRevision
    evidence: EvidenceSpan
    evidence_is_exact: bool


async def upsert_claim_for_fact(
    session: AsyncSession,
    *,
    source_document: SourceDocument,
    fact: Any,
    component_status: str,
    extraction_method: str,
) -> ClaimWriteResult:
    evidence_result = await create_evidence_span_for_fact(
        session,
        source_document=source_document,
        fact=fact,
        extraction_method=extraction_method,
    )
    identity_key = claim_identity_key(fact)
    claim_type = canonical_fact_type(getattr(fact, "fact_type", None))
    workspace_id = _coerce_uuid(getattr(source_document, "workspace_id", None))
    claim = await _find_claim(
        session,
        workspace_id=workspace_id,
        identity_key=identity_key,
        claim_type=claim_type,
    )
    confidence = _clamp(float(getattr(fact, "confidence", 0.5) or 0.5))
    temporal = canonical_temporal(getattr(fact, "temporal", None))
    status = _claim_status(
        component_status=component_status,
        evidence_result=evidence_result,
        confidence=confidence,
    )

    previous_value = None
    previous_confidence = 0.0
    if claim is None:
        claim = Claim(
            workspace_id=workspace_id,
            identity_key=identity_key,
            claim_type=claim_type,
            status=status,
            temporal=temporal,
            confidence=confidence,
            authority_weight=evidence_result.span.authority_weight,
        )
        session.add(claim)
        await session.flush()
        operation = "create"
    else:
        previous = await _latest_revision(session, claim.id)
        previous_value = previous.value if previous else None
        previous_confidence = claim.confidence
        operation = _revision_operation(previous_value, str(getattr(fact, "value", "") or ""))
        claim.status = _merge_status(claim.status, status)
        claim.temporal = temporal if temporal != "unknown" else claim.temporal
        claim.confidence = max(claim.confidence, confidence)
        claim.authority_weight = max(claim.authority_weight, evidence_result.span.authority_weight)

    revision = ClaimRevision(
        claim_id=claim.id,
        evidence_span_id=evidence_result.span.id,
        value=str(getattr(fact, "value", "") or ""),
        operation=operation,
        confidence_delta=round(confidence - previous_confidence, 4),
        status_after=claim.status,
        created_by=f"extractor:{extraction_method}",
    )
    session.add(revision)
    await session.flush()
    claim.current_revision_id = revision.id
    await session.flush()
    return ClaimWriteResult(
        claim=claim,
        revision=revision,
        evidence=evidence_result.span,
        evidence_is_exact=evidence_result.exact,
    )


def claim_identity_key(fact: Any) -> str:
    name_key = identity_key_for_component_name(str(getattr(fact, "name", "") or ""))
    if name_key:
        return name_key
    raw = (
        f"{getattr(fact, 'model_name', '')}:"
        f"{getattr(fact, 'fact_type', '')}:"
        f"{getattr(fact, 'value', '')}"
    )
    return f"claim:{sha256_text(raw)[:32]}"


async def append_claim_revision(
    session: AsyncSession,
    *,
    claim: Claim,
    evidence_span: EvidenceSpan,
    value: str,
    operation: str = "update",
    confidence_delta: float = 0.0,
    status_after: str | None = None,
    supersedes_claim: Claim | None = None,
    contradicts_claim: Claim | None = None,
    supersedes_claim_id: UUID | None = None,
    contradicts_claim_id: UUID | None = None,
    created_by: str | None = None,
) -> ClaimRevision:
    operation = operation.strip().lower()
    supersedes_target_id = supersedes_claim_id or (
        supersedes_claim.id if supersedes_claim else None
    )
    contradicts_target_id = contradicts_claim_id or (
        contradicts_claim.id if contradicts_claim else None
    )
    if operation == "supersede" and supersedes_target_id is None:
        raise ValueError("supersede revisions require supersedes_claim_id")
    if operation == "contradict" and contradicts_target_id is None:
        raise ValueError("contradict revisions require contradicts_claim_id")

    next_status = status_after or claim.status
    revision = ClaimRevision(
        claim_id=claim.id,
        evidence_span_id=evidence_span.id,
        value=value,
        operation=operation,
        confidence_delta=round(float(confidence_delta), 4),
        status_after=next_status,
        supersedes_claim_id=supersedes_target_id,
        contradicts_claim_id=contradicts_target_id,
        created_by=created_by,
    )
    session.add(revision)
    await session.flush()
    claim.status = next_status
    claim.current_revision_id = revision.id
    if operation == "supersede":
        target = supersedes_claim
        if target is None and supersedes_target_id is not None:
            target = await session.get(Claim, supersedes_target_id)
        if target is not None:
            target.status = "superseded"
            await _sync_claim_components(session, target, "superseded")
            await _link_claim_components(
                session,
                source_claim=claim,
                target_claim=target,
                relationship_type="supersedes",
                evidence=value,
                confidence=claim.confidence,
            )
    elif operation == "contradict":
        target = contradicts_claim
        if target is None and contradicts_target_id is not None:
            target = await session.get(Claim, contradicts_target_id)
        if target is not None:
            await _link_claim_components(
                session,
                source_claim=claim,
                target_claim=target,
                relationship_type="contradicts",
                evidence=value,
                confidence=claim.confidence,
            )

    if next_status in {"resolved", "stale", "rejected", "superseded"}:
        await _sync_claim_components(session, claim, next_status)
    await session.flush()
    return revision


async def _find_claim(
    session: AsyncSession,
    *,
    workspace_id: UUID | None,
    identity_key: str,
    claim_type: str,
) -> Claim | None:
    stmt = select(Claim).where(
        Claim.identity_key == identity_key,
        Claim.claim_type == claim_type,
    )
    if workspace_id:
        stmt = stmt.where(Claim.workspace_id == workspace_id)
    else:
        stmt = stmt.where(Claim.workspace_id.is_(None))
    return await session.scalar(stmt.order_by(Claim.created_at).limit(1))


async def _latest_revision(session: AsyncSession, claim_id: UUID) -> ClaimRevision | None:
    return await session.scalar(
        select(ClaimRevision)
        .where(ClaimRevision.claim_id == claim_id)
        .order_by(ClaimRevision.created_at.desc(), ClaimRevision.id.desc())
        .limit(1)
    )


def _claim_status(
    *,
    component_status: str,
    evidence_result: EvidenceSpanResult,
    confidence: float,
) -> str:
    if not evidence_result.exact:
        return "needs_review"
    if evidence_result.span.prompt_injection_risk_score >= 0.5:
        return "needs_review"
    if confidence < 0.6:
        return "needs_review"
    return "active" if component_status == "active" else "needs_review"


def _merge_status(existing_status: str, incoming_status: str) -> str:
    if existing_status == "active" and incoming_status == "active":
        return "active"
    if existing_status in {"rejected", "superseded", "stale", "resolved"}:
        return existing_status
    return incoming_status


def _revision_operation(previous_value: str | None, incoming_value: str) -> str:
    if previous_value is None:
        return "create"
    if previous_value == incoming_value:
        return "confirm"
    return "update"


async def _sync_claim_components(
    session: AsyncSession,
    claim: Claim,
    status: str,
) -> None:
    components = (
        await session.scalars(select(Component).where(Component.claim_id == claim.id))
    ).all()
    for component in components:
        component.status = status


async def _link_claim_components(
    session: AsyncSession,
    *,
    source_claim: Claim,
    target_claim: Claim,
    relationship_type: str,
    evidence: str,
    confidence: float,
) -> None:
    source_component = await session.scalar(
        select(Component)
        .where(Component.claim_id == source_claim.id)
        .order_by(Component.created_at.desc())
        .limit(1)
    )
    target_component = await session.scalar(
        select(Component)
        .where(Component.claim_id == target_claim.id)
        .order_by(Component.created_at.desc())
        .limit(1)
    )
    if source_component is None or target_component is None:
        return
    if source_component.id == target_component.id:
        return
    exists = await session.scalar(
        select(Relationship).where(
            Relationship.source_component_id == source_component.id,
            Relationship.target_component_id == target_component.id,
            Relationship.relationship_type == relationship_type,
        )
    )
    if exists is not None:
        return
    session.add(
        Relationship(
            source_component_id=source_component.id,
            target_component_id=target_component.id,
            relationship_type=relationship_type,
            confidence=_clamp(confidence),
            evidence=evidence or f"Claim revision {relationship_type} target claim.",
            origin="deterministic",
            status="active",
        )
    )


def _coerce_uuid(value: object) -> UUID | None:
    if value in (None, ""):
        return None
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except (TypeError, ValueError):
        return None


def _clamp(value: float) -> float:
    return min(max(float(value), 0.0), 1.0)
