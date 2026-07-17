from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
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
from app.time import utc_now


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
        for_update=True,
    )
    confidence = _clamp(float(getattr(fact, "confidence", 0.5) or 0.5))
    temporal = canonical_temporal(getattr(fact, "temporal", None))
    status = _claim_status(
        component_status=component_status,
        evidence_result=evidence_result,
        confidence=confidence,
    )

    previous: ClaimRevision | None = None
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

    status = claim.status
    observed_at, valid_from, validity_basis = _revision_time_from_evidence(
        evidence_result.span
    )
    incoming_value = str(getattr(fact, "value", "") or "")
    revision_key = _claim_revision_key(
        claim_id=claim.id,
        evidence_span=evidence_result.span,
        value=incoming_value,
        operation=operation,
    )
    existing_revision = await session.scalar(
        select(ClaimRevision).where(ClaimRevision.revision_key == revision_key)
    )
    if existing_revision is not None:
        claim.current_revision_id = existing_revision.id
        return ClaimWriteResult(
            claim=claim,
            revision=existing_revision,
            evidence=evidence_result.span,
            evidence_is_exact=evidence_result.exact,
        )
    now = utc_now()
    if previous is not None:
        if operation == "confirm":
            previous.transaction_to = previous.transaction_to or now
            valid_from = previous.valid_from
            validity_basis = previous.validity_basis
        elif operation == "update":
            if valid_from is not None:
                if previous.valid_from is None or valid_from >= previous.valid_from:
                    previous.transaction_to = previous.transaction_to or now
                    previous.valid_to = valid_from
                else:
                    # Late historical evidence remains in history and cannot
                    # silently replace the established current truth.
                    status = "contested"
            else:
                status = "contested"
    revision = ClaimRevision(
        claim_id=claim.id,
        evidence_span_id=evidence_result.span.id,
        revision_key=revision_key,
        value=incoming_value,
        operation=operation,
        confidence_delta=round(confidence - previous_confidence, 4),
        status_after=claim.status,
        created_by=f"extractor:{extraction_method}",
        valid_from=valid_from,
        observed_at=observed_at,
        validity_basis=validity_basis,
        created_at=now,
    )
    session.add(revision)
    try:
        await session.flush()
    except IntegrityError:
        # A concurrent identical writer won the deterministic revision key.
        existing_revision = await session.scalar(
            select(ClaimRevision).where(ClaimRevision.revision_key == revision_key)
        )
        if existing_revision is None:
            raise
        revision = existing_revision
    if status == "contested" and operation == "update" and (
        valid_from is None
        or (previous is not None and previous.valid_from is not None and valid_from < previous.valid_from)
    ):
        claim.status = "contested"
        claim.current_revision_id = None
    else:
        claim.status = status
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
    valid_from: datetime | None = None,
    observed_at: datetime | None = None,
    validity_basis: str | None = None,
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
    for target_id in (supersedes_target_id, contradicts_target_id):
        if target_id is None:
            continue
        target_claim = await session.get(Claim, target_id)
        if target_claim is None or target_claim.workspace_id != claim.workspace_id:
            raise ValueError("claim revision targets must exist in the same workspace")

    next_status = status_after or claim.status
    previous = await _latest_revision(session, claim.id, for_update=True)
    evidence_observed_at, evidence_valid_from, evidence_basis = _revision_time_from_evidence(
        evidence_span
    )
    effective_observed_at = observed_at or evidence_observed_at
    effective_valid_from = valid_from if valid_from is not None else evidence_valid_from
    effective_basis = validity_basis or evidence_basis
    if effective_basis not in {"source_time", "observation_time", "unknown"}:
        raise ValueError("invalid claim revision validity_basis")
    now = utc_now()
    if previous is not None:
        if operation == "confirm":
            previous.transaction_to = previous.transaction_to or now
            effective_valid_from = previous.valid_from
            effective_basis = previous.validity_basis
        elif operation not in {"contradict"} and effective_valid_from is not None:
            if previous.valid_from is None or effective_valid_from >= previous.valid_from:
                previous.transaction_to = previous.transaction_to or now
                previous.valid_to = effective_valid_from
            else:
                next_status = "contested"
    revision_key = _claim_revision_key(
        claim_id=claim.id,
        evidence_span=evidence_span,
        value=value,
        operation=operation,
        supersedes_claim_id=supersedes_target_id,
        contradicts_claim_id=contradicts_target_id,
    )
    existing_revision = await session.scalar(
        select(ClaimRevision).where(ClaimRevision.revision_key == revision_key)
    )
    if existing_revision is not None:
        return existing_revision
    revision = ClaimRevision(
        claim_id=claim.id,
        evidence_span_id=evidence_span.id,
        revision_key=revision_key,
        value=value,
        operation=operation,
        confidence_delta=round(float(confidence_delta), 4),
        status_after=next_status,
        supersedes_claim_id=supersedes_target_id,
        contradicts_claim_id=contradicts_target_id,
        created_by=created_by,
        valid_from=effective_valid_from,
        observed_at=effective_observed_at,
        validity_basis=effective_basis,
        created_at=now,
    )
    session.add(revision)
    await session.flush()
    claim.status = next_status
    claim.current_revision_id = (
        None
        if next_status == "contested" and operation not in {"contradict"}
        else revision.id
    )
    if operation == "supersede":
        target = supersedes_claim
        if target is None and supersedes_target_id is not None:
            target = await session.get(Claim, supersedes_target_id)
        if target is not None:
            target_revision = await _latest_revision(session, target.id, for_update=True)
            if effective_valid_from is None:
                target.status = "contested"
                claim.status = "contested"
                claim.current_revision_id = None
            else:
                target.status = "superseded"
                if target_revision is not None:
                    target_revision.valid_to = effective_valid_from
                    target_revision.transaction_to = target_revision.transaction_to or now
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
    for_update: bool = False,
) -> Claim | None:
    stmt = select(Claim).where(
        Claim.identity_key == identity_key,
        Claim.claim_type == claim_type,
    )
    if workspace_id:
        stmt = stmt.where(Claim.workspace_id == workspace_id)
    else:
        stmt = stmt.where(Claim.workspace_id.is_(None))
    stmt = stmt.order_by(Claim.created_at).limit(1)
    if for_update and session.get_bind().dialect.name == "postgresql":
        stmt = stmt.with_for_update()
    return await session.scalar(stmt)


async def _latest_revision(
    session: AsyncSession,
    claim_id: UUID,
    *,
    for_update: bool = False,
) -> ClaimRevision | None:
    stmt = (
        select(ClaimRevision)
        .where(ClaimRevision.claim_id == claim_id)
        .order_by(ClaimRevision.created_at.desc(), ClaimRevision.id.desc())
        .limit(1)
    )
    if for_update and session.get_bind().dialect.name == "postgresql":
        stmt = stmt.with_for_update()
    return await session.scalar(stmt)


async def claim_revisions_as_of(
    session: AsyncSession,
    *,
    claim_id: UUID,
    valid_at: datetime | None = None,
    known_at: datetime | None = None,
) -> list[ClaimRevision]:
    """Return every revision true at validity time and known at transaction time."""
    stmt = select(ClaimRevision).where(ClaimRevision.claim_id == claim_id)
    if valid_at is not None:
        stmt = stmt.where(
            (ClaimRevision.valid_from.is_(None) | (ClaimRevision.valid_from <= valid_at)),
            (ClaimRevision.valid_to.is_(None) | (ClaimRevision.valid_to > valid_at)),
        )
    if known_at is not None:
        stmt = stmt.where(
            ClaimRevision.created_at <= known_at,
            (ClaimRevision.transaction_to.is_(None) | (ClaimRevision.transaction_to > known_at)),
        )
    else:
        stmt = stmt.where(ClaimRevision.transaction_to.is_(None))
    return list(await session.scalars(
        stmt.order_by(ClaimRevision.valid_from, ClaimRevision.created_at, ClaimRevision.id)
    ))


def _revision_time_from_evidence(
    evidence_span: EvidenceSpan,
) -> tuple[datetime, datetime | None, str]:
    source = evidence_span.__dict__.get("source_document")
    if source is not None and source.source_created_at is not None:
        return source.ingested_at or utc_now(), source.source_created_at, "source_time"
    if source is not None and source.ingested_at is not None:
        return source.ingested_at, source.ingested_at, "observation_time"
    observed_at = evidence_span.created_at or utc_now()
    return observed_at, None, "unknown"


def _claim_revision_key(
    *,
    claim_id: UUID,
    evidence_span: EvidenceSpan,
    value: str,
    operation: str,
    supersedes_claim_id: UUID | None = None,
    contradicts_claim_id: UUID | None = None,
) -> str:
    source_id = getattr(evidence_span, "source_document_id", None)
    payload = "\x1f".join([
        str(claim_id),
        str(source_id or ""),
        str(evidence_span.text_sha256 or ""),
        operation,
        value,
        str(supersedes_claim_id or ""),
        str(contradicts_claim_id or ""),
    ])
    return sha256_text(payload)


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
    if source_component.workspace_id != target_component.workspace_id:
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
