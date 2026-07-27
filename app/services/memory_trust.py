from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import ClaimRevision, Component, EvidenceSpan, SourceDocument
from app.services.provider_freshness import is_provider_source
from app.taxonomy import (
    AGENT_SESSION_SOURCE_TYPES,
    canonical_trust_zone,
)


MemoryVerification = Literal[
    "verified",
    "observed",
    "reported",
    "needs_review",
    "unavailable",
]
MemoryTruthState = Literal[
    "current",
    "reported",
    "needs_review",
    "stale",
    "contested",
    "resolved",
    "superseded",
    "rejected",
    "historical",
    "unknown",
]

AGENT_REPORTED_ACTIVITY_FACT_TYPES = frozenset(
    {
        "changed_file",
        "commit_reference",
        "failed_attempt",
        "github_pr",
        "observed_change",
        "outcome",
        "pr",
        "release",
        "run_outcome",
        "test",
        "verification",
    }
)
PROVIDER_OBSERVED_FACT_TYPES = frozenset(
    {
        "github_issue",
        "github_pr",
        "issue",
        "milestone",
        "owner",
        "pr",
    }
)
TERMINAL_TRUTH_STATES: dict[str, MemoryTruthState] = {
    "deprecated": "historical",
    "rejected": "rejected",
    "resolved": "resolved",
    "superseded": "superseded",
}


@dataclass(frozen=True)
class MemoryTrustAssessment:
    """One shared interpretation of provenance, evidence, and lifecycle.

    ``evidence_exact`` establishes that the quote is byte-for-byte present in
    the immutable source revision. It does not establish that the quoted
    assertion is true. ``current_truth`` is deliberately stricter.
    """

    verification: MemoryVerification
    truth_state: MemoryTruthState
    effective_status: str
    current_truth: bool
    requires_review: bool
    reported_activity: bool
    evidence_exact: bool
    trust_zone: str
    basis: str
    source_is_agent: bool
    source_is_remote: bool


def assess_memory_trust(
    component: Component,
    evidence: EvidenceSpan | None,
    *,
    source: SourceDocument | None = None,
    source_is_current: bool = True,
    provider_fresh: bool = False,
    conflict: bool = False,
) -> MemoryTrustAssessment:
    """Classify whether a component is current truth, a report, or review work.

    Provider freshness is false by default because an indexed remote snapshot
    cannot prove its own present-day state. Callers may set it only after a
    successful provider refresh bound to this exact source revision.
    """

    source = source or getattr(component, "source_document", None)
    source_type = str(getattr(source, "source_type", "") or "").strip().lower()
    source_is_agent = is_agent_source_type(source_type)
    source_is_remote = is_remote_source(source)
    trust_zone = _effective_trust_zone(source, evidence)
    evidence_exact = exact_memory_evidence(source, evidence)
    evidence_verified = exact_verified_evidence(source, evidence)
    extraction_method = str(getattr(evidence, "extraction_method", "") or "").strip().lower()
    deterministic = extraction_method == "deterministic"
    fact_type = str(getattr(component, "fact_type", "") or "").strip().lower()
    component_status = str(getattr(component, "status", "") or "active").strip().lower()
    claim = getattr(component, "claim", None)
    claim_status = str(getattr(claim, "status", "") or "").strip().lower()
    effective_status = (
        component_status
        if component_status in TERMINAL_TRUTH_STATES
        else claim_status or component_status
    )

    if effective_status in TERMINAL_TRUTH_STATES:
        truth_state = TERMINAL_TRUTH_STATES[effective_status]
        return _assessment(
            verification=(
                "verified"
                if evidence_verified and trust_zone == "trusted_human"
                else "observed"
                if evidence_verified
                else "unavailable"
            ),
            truth_state=truth_state,
            effective_status=effective_status,
            evidence_exact=evidence_exact,
            trust_zone=trust_zone,
            basis=f"lifecycle_{effective_status}",
            source_is_agent=source_is_agent,
            source_is_remote=source_is_remote,
        )

    if conflict or effective_status == "contested":
        return _assessment(
            verification="needs_review",
            truth_state="contested",
            effective_status="contested",
            evidence_exact=evidence_exact,
            trust_zone=trust_zone,
            basis="unresolved_conflict",
            source_is_agent=source_is_agent,
            source_is_remote=source_is_remote,
            requires_review=True,
        )

    if not source_is_current or effective_status == "stale":
        return _assessment(
            verification="observed" if evidence_exact else "unavailable",
            truth_state="stale",
            effective_status="stale",
            evidence_exact=evidence_exact,
            trust_zone=trust_zone,
            basis="superseded_or_stale_source",
            source_is_agent=source_is_agent,
            source_is_remote=source_is_remote,
        )

    # A confirmation of a captured remote quote does not establish that the
    # provider still reports it. The live retrieval path must bind freshness
    # to this exact source revision before any remote fact can be current.
    if source_is_remote and not provider_fresh:
        return _assessment(
            verification="observed" if evidence_verified else "unavailable",
            truth_state="stale",
            effective_status="stale",
            evidence_exact=evidence_exact,
            trust_zone=trust_zone,
            basis="remote_freshness_unknown",
            source_is_agent=False,
            source_is_remote=True,
        )

    human_confirmed = evidence_verified and _human_confirmed(source, evidence)
    if human_confirmed and effective_status in {"active", "verified"}:
        return _assessment(
            verification="verified",
            truth_state="current",
            effective_status="active",
            current_truth=True,
            evidence_exact=True,
            trust_zone="trusted_human",
            basis="human_confirmed_exact_evidence",
            source_is_agent=source_is_agent,
            source_is_remote=source_is_remote,
        )

    if source_is_agent:
        if evidence_exact and fact_type in AGENT_REPORTED_ACTIVITY_FACT_TYPES:
            return _assessment(
                verification="reported",
                truth_state="reported",
                effective_status="reported",
                reported_activity=True,
                evidence_exact=True,
                trust_zone=trust_zone,
                basis="agent_reported_activity",
                source_is_agent=True,
                source_is_remote=False,
            )
        return _assessment(
            verification="needs_review" if evidence_exact else "unavailable",
            truth_state="needs_review" if evidence is not None else "unknown",
            effective_status="needs_review",
            evidence_exact=evidence_exact,
            trust_zone=trust_zone,
            basis=(
                "agent_assertion_requires_human_confirmation"
                if evidence_exact
                else "agent_assertion_lacks_exact_evidence"
            ),
            source_is_agent=True,
            source_is_remote=False,
            requires_review=evidence_exact,
        )

    if effective_status in {"needs_review", "proposed"}:
        return _assessment(
            verification="needs_review" if evidence_exact else "unavailable",
            truth_state="needs_review" if evidence is not None else "unknown",
            effective_status="needs_review",
            evidence_exact=evidence_exact,
            trust_zone=trust_zone,
            basis=f"lifecycle_{effective_status}",
            source_is_agent=False,
            source_is_remote=source_is_remote,
            requires_review=evidence_exact,
        )

    if (
        evidence_verified
        and trust_zone in {"trusted_repo", "trusted_system"}
        and effective_status in {"active", "verified"}
    ):
        return _assessment(
            verification="verified",
            truth_state="current",
            effective_status="active",
            current_truth=True,
            evidence_exact=True,
            trust_zone=trust_zone,
            basis=f"{trust_zone}_exact_verified_evidence",
            source_is_agent=False,
            source_is_remote=source_is_remote,
        )

    if (
        evidence_verified
        and deterministic
        and provider_fresh
        and trust_zone == "semi_trusted_tool"
        and fact_type in PROVIDER_OBSERVED_FACT_TYPES
        and effective_status in {"active", "verified"}
    ):
        return _assessment(
            verification="observed",
            truth_state="current",
            effective_status="active",
            current_truth=True,
            evidence_exact=True,
            trust_zone=trust_zone,
            basis="fresh_provider_structured_observation",
            source_is_agent=False,
            source_is_remote=source_is_remote,
        )

    return _assessment(
        verification="needs_review" if evidence_exact else "unavailable",
        truth_state="needs_review" if evidence is not None else "unknown",
        effective_status="needs_review",
        evidence_exact=evidence_exact,
        trust_zone=trust_zone,
        basis=(
            "source_assertion_requires_human_confirmation"
            if evidence_exact
            else "missing_or_inexact_evidence"
        ),
        source_is_agent=False,
        source_is_remote=source_is_remote,
        requires_review=evidence_exact,
    )


async def load_component_evidence(
    session: AsyncSession,
    components: list[Component],
) -> dict[UUID, EvidenceSpan]:
    """Load the newest evidence occurrence from each component's own source."""

    claim_ids = {component.claim_id for component in components if component.claim_id is not None}
    if not claim_ids:
        return {}
    revisions = list(
        await session.scalars(
            select(ClaimRevision)
            .options(
                selectinload(ClaimRevision.evidence_span).selectinload(EvidenceSpan.source_document)
            )
            .where(ClaimRevision.claim_id.in_(claim_ids))
            .order_by(ClaimRevision.created_at.desc(), ClaimRevision.id.desc())
        )
    )
    revisions_by_id = {revision.id: revision for revision in revisions}
    revisions_by_claim_source: dict[
        tuple[UUID, UUID],
        ClaimRevision,
    ] = {}
    for revision in revisions:
        evidence = revision.evidence_span
        revisions_by_claim_source.setdefault(
            (revision.claim_id, evidence.source_document_id),
            revision,
        )

    result: dict[UUID, EvidenceSpan] = {}
    for component in components:
        claim = getattr(component, "claim", None)
        current_revision_id = getattr(claim, "current_revision_id", None)
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


def exact_verified_evidence(
    source: SourceDocument | None,
    evidence: EvidenceSpan | None,
) -> bool:
    """Validate exact span integrity and its stored extraction review state."""

    return bool(
        evidence is not None
        and evidence.review_status == "verified"
        and exact_memory_evidence(source, evidence)
    )


def exact_memory_evidence(
    source: SourceDocument | None,
    evidence: EvidenceSpan | None,
) -> bool:
    """Check immutable quote integrity without treating it as truth approval."""

    if (
        source is None
        or evidence is None
        or evidence.start_char is None
        or evidence.end_char is None
    ):
        return False
    excerpt = evidence.text or ""
    prechecked_source_text = evidence.__dict__.get("_source_text_matches")
    if prechecked_source_text is not None and "content" not in source.__dict__:
        source_length = evidence.__dict__.get("_source_content_length")
        source_sha256 = evidence.__dict__.get("_source_content_sha256")
        if not (
            prechecked_source_text
            and isinstance(source_length, int)
            and 0 <= evidence.start_char < evidence.end_char <= source_length
            and len(excerpt) == evidence.end_char - evidence.start_char
            and evidence.source_document_id == source.id
            and _sha256(excerpt) == evidence.text_sha256
            and isinstance(source_sha256, str)
            and source_sha256
        ):
            return False
        declared_source_hash = source.content_sha256
        return not declared_source_hash or declared_source_hash == source_sha256
    content = source.content or ""
    if not (
        0 <= evidence.start_char < evidence.end_char <= len(content)
        and evidence.source_document_id == source.id
        and content[evidence.start_char : evidence.end_char] == excerpt
        and _sha256(excerpt) == evidence.text_sha256
    ):
        return False
    declared_source_hash = source.content_sha256
    return not declared_source_hash or declared_source_hash == _sha256(content)


def is_agent_source_type(source_type: str | None) -> bool:
    raw = str(source_type or "").strip().lower()
    return raw in AGENT_SESSION_SOURCE_TYPES or raw.startswith("ai_context")


def is_remote_source(source: SourceDocument | None) -> bool:
    return is_provider_source(source)


def _assessment(
    *,
    verification: MemoryVerification,
    truth_state: MemoryTruthState,
    effective_status: str,
    evidence_exact: bool,
    trust_zone: str,
    basis: str,
    source_is_agent: bool,
    source_is_remote: bool,
    current_truth: bool = False,
    requires_review: bool = False,
    reported_activity: bool = False,
) -> MemoryTrustAssessment:
    return MemoryTrustAssessment(
        verification=verification,
        truth_state=truth_state,
        effective_status=effective_status,
        current_truth=current_truth,
        requires_review=requires_review,
        reported_activity=reported_activity,
        evidence_exact=evidence_exact,
        trust_zone=trust_zone,
        basis=basis,
        source_is_agent=source_is_agent,
        source_is_remote=source_is_remote,
    )


def _effective_trust_zone(
    source: SourceDocument | None,
    evidence: EvidenceSpan | None,
) -> str:
    evidence_zone = str(getattr(evidence, "trust_zone", "") or "").strip().lower()
    if evidence_zone:
        return canonical_trust_zone(
            evidence_zone,
            getattr(source, "source_type", None),
            _metadata(source),
        )
    return canonical_trust_zone(
        getattr(source, "trust_zone", None),
        getattr(source, "source_type", None),
        _metadata(source),
    )


def _human_confirmed(
    source: SourceDocument | None,
    evidence: EvidenceSpan | None,
) -> bool:
    if str(getattr(evidence, "trust_zone", "") or "").lower() == "trusted_human":
        return True
    metadata = _metadata(source)
    return bool(
        metadata.get("verified_by_human") is True
        or str(metadata.get("verification_status") or "").lower() == "human_verified"
    )


def _metadata(source: SourceDocument | None) -> dict:
    if source is None:
        return {}
    raw = source.metadata_json
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str) or not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
