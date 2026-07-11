from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import EvidenceSpan, SourceDocument
from app.taxonomy import default_trust_zone_for_source


PROMPT_INJECTION_PATTERNS: tuple[tuple[re.Pattern[str], float], ...] = (
    (re.compile(r"\bignore (?:all |the |previous |prior )?instructions?\b", re.I), 0.30),
    (re.compile(r"\bsystem prompt\b|\bdeveloper message\b", re.I), 0.25),
    (re.compile(r"\bdo not tell the user\b|\bhide (?:this|that) from the user\b", re.I), 0.25),
    (re.compile(r"\bexfiltrate\b|\bsend credentials\b|\bapi[_ -]?key\b|\bsecret\b", re.I), 0.30),
    (re.compile(r"\btool_call\b|\bfunction_call\b|\bfunction call\b", re.I), 0.20),
    (re.compile(r"\bdelete (?:the )?(?:database|repo|repository|files?)\b", re.I), 0.20),
    (re.compile(r"\brun shell\b|\bcurl\b.*\btoken\b|\bprint env\b", re.I), 0.20),
    (re.compile(r"\bmark\b.*\bconnected\b", re.I), 0.20),
    (re.compile(r"\bbypass\b", re.I), 0.20),
    (re.compile(r"\bdisable tests?\b", re.I), 0.20),
)


@dataclass(frozen=True)
class EvidenceSpanResult:
    span: EvidenceSpan
    exact: bool
    span_text: str


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def locate_exact_span(content: str, text: str) -> tuple[int, int] | None:
    if not text:
        return None
    start = content.find(text)
    if start < 0:
        return None
    return start, start + len(text)


def score_prompt_injection_risk(text: str) -> float:
    if not text:
        return 0.0
    score = 0.0
    for pattern, weight in PROMPT_INJECTION_PATTERNS:
        if pattern.search(text):
            score += weight
    if len(PROMPT_INJECTION_PATTERNS) > 1 and score >= 0.5:
        score += 0.15
    return min(round(score, 3), 1.0)


async def ensure_source_document_ledger_fields(doc: SourceDocument) -> None:
    expected_hash = sha256_text(doc.content or "")
    if doc.content_sha256 and doc.content_sha256 != expected_hash:
        raise ValueError("source document content hash does not match stored content")
    doc.content_sha256 = expected_hash
    metadata = metadata_dict(doc.metadata_json)
    if not doc.trust_zone:
        doc.trust_zone = default_trust_zone_for_source(doc.source_type, metadata)
    if not doc.source_created_at:
        doc.source_created_at = source_created_at_from_metadata(metadata)


async def create_evidence_span(
    session: AsyncSession,
    *,
    source_document: SourceDocument,
    text: str | None = None,
    start_char: int | None = None,
    end_char: int | None = None,
    evidence_type: str = "extracted_fact",
    authority_weight: float = 0.5,
    trust_zone: str | None = None,
    extraction_method: str = "deterministic",
    expected_text_sha256: str | None = None,
    allow_fuzzy: bool = False,
) -> EvidenceSpanResult:
    await ensure_source_document_ledger_fields(source_document)
    content = source_document.content or ""
    span_text = ""
    exact = False

    if start_char is not None or end_char is not None:
        if start_char is None or end_char is None:
            raise ValueError("start_char and end_char must be provided together")
        if start_char < 0 or end_char <= start_char or end_char > len(content):
            raise ValueError("evidence span range is outside source document content")
        span_text = content[start_char:end_char]
        if text is not None and span_text != text:
            raise ValueError("evidence span text does not match source document range")
        exact = True
    else:
        candidate = _clean_candidate_text(text)
        located = locate_exact_span(content, candidate)
        if located:
            start_char, end_char = located
            span_text = content[start_char:end_char]
            exact = True
        elif allow_fuzzy:
            start_char = None
            end_char = None
            span_text = candidate
        else:
            raise ValueError("evidence text does not occur in source document content")

    text_sha256 = sha256_text(span_text)
    if expected_text_sha256 and expected_text_sha256 != text_sha256:
        raise ValueError("evidence span hash mismatch")

    prompt_injection_risk_score = score_prompt_injection_risk(span_text)
    review_status = "verified" if exact and prompt_injection_risk_score < 0.5 else "needs_review"

    span = EvidenceSpan(
        workspace_id=_coerce_uuid(getattr(source_document, "workspace_id", None)),
        source_document_id=source_document.id,
        start_char=start_char,
        end_char=end_char,
        text=span_text,
        text_sha256=text_sha256,
        evidence_type=evidence_type,
        authority_weight=_clamp(authority_weight, 0.0, 1.0),
        trust_zone=trust_zone or source_document.trust_zone or "untrusted_external",
        prompt_injection_risk_score=prompt_injection_risk_score,
        extraction_method=extraction_method,
        review_status=review_status,
    )
    session.add(span)
    await session.flush()
    return EvidenceSpanResult(span=span, exact=exact, span_text=span_text)


async def create_evidence_span_for_fact(
    session: AsyncSession,
    *,
    source_document: SourceDocument,
    fact: Any,
    extraction_method: str,
) -> EvidenceSpanResult:
    candidates = [
        getattr(fact, "excerpt", None),
        getattr(fact, "value", None),
    ]
    for candidate in candidates:
        text = _clean_candidate_text(candidate)
        if not text:
            continue
        located = locate_exact_span(source_document.content or "", text)
        if located:
            return await create_evidence_span(
                session,
                source_document=source_document,
                text=text,
                evidence_type=getattr(fact, "fact_type", None) or "extracted_fact",
                authority_weight=float(getattr(fact, "confidence", 0.5) or 0.5),
                extraction_method=extraction_method,
            )

    fallback = _clean_candidate_text(getattr(fact, "excerpt", None)) or _clean_candidate_text(
        getattr(fact, "value", None)
    )
    return await create_evidence_span(
        session,
        source_document=source_document,
        text=fallback,
        evidence_type=getattr(fact, "fact_type", None) or "llm_extracted_quote",
        authority_weight=float(getattr(fact, "confidence", 0.5) or 0.5),
        extraction_method=extraction_method,
        allow_fuzzy=True,
    )


def metadata_dict(raw: object) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str) or not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def source_created_at_from_metadata(metadata: dict[str, Any]) -> datetime | None:
    for key in ("source_created_at", "created_at", "timestamp", "ts"):
        value = metadata.get(key)
        if isinstance(value, datetime):
            return value
        if not isinstance(value, str) or not value.strip():
            continue
        try:
            return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            continue
    return None


def _clean_candidate_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _coerce_uuid(value: object) -> UUID | None:
    if value in (None, ""):
        return None
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except (TypeError, ValueError):
        return None


def _clamp(value: float, low: float, high: float) -> float:
    return min(max(float(value), low), high)
