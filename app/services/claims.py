from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Claim, ClaimRevision, EvidenceSpan, SourceDocument
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
    raw = f"{getattr(fact, 'model_name', '')}:{getattr(fact, 'fact_type', '')}:{getattr(fact, 'value', '')}"
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
    created_by: str | None = None,
) -> ClaimRevision:
    revision = ClaimRevision(
        claim_id=claim.id,
        evidence_span_id=evidence_span.id,
        value=value,
        operation=operation,
        confidence_delta=round(float(confidence_delta), 4),
        status_after=status_after or claim.status,
        created_by=created_by,
    )
    session.add(revision)
    await session.flush()
    claim.current_revision_id = revision.id
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
    value = incoming_value.lower()
    if re.search(r"\b(supersedes|replaces|deprecates)\b", value):
        return "supersede"
    if re.search(r"\b(contradicts|conflicts with|conflict)\b", value):
        return "contradict"
    if previous_value is None:
        return "create"
    if previous_value == incoming_value:
        return "confirm"
    return "update"


def _coerce_uuid(value: object) -> UUID | None:
    if value in (None, ""):
        return None
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except (TypeError, ValueError):
        return None


def _clamp(value: float) -> float:
    return min(max(float(value), 0.0), 1.0)
