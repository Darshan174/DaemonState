from __future__ import annotations

import math
import re
from dataclasses import dataclass

from app.models import Component


@dataclass(frozen=True)
class RerankFeatures:
    semantic_score: float
    lexical_score: float
    lexical_score_normalized: float
    exact_match_score: float
    token_coverage: float
    title_coverage: float
    confidence_score: float
    authority_score: float
    status_score: float
    provenance_score: float
    raw_score: float
    final_score: float


def score_component(
    question: str,
    component: Component,
    *,
    semantic_score: float,
    lexical_score: float,
) -> RerankFeatures:
    """Deterministic second-stage reranker for graph facts.

    The first retrieval stage finds candidates with pgvector/text indexes or a
    local scan. This stage favors source-backed exact evidence and query-token
    coverage over vector-only similarity so hash/dev vectors cannot dominate.
    """

    query_tokens = _tokenize(question)
    name_text = component.name or ""
    haystack = " ".join(
        [
            name_text,
            component.value or "",
            component.fact_type or "",
            component.status or "",
            component.temporal or "",
            component.model.name if component.model else "",
            component.source_document.source_type if component.source_document else "",
        ]
    )
    haystack_tokens = _tokenize(haystack)
    name_tokens = _tokenize(name_text)

    semantic = _clamp01(max(0.0, float(semantic_score or 0.0)))
    lexical_norm = _clamp01(float(lexical_score or 0.0) / 1.4)
    exact = _exact_match_score(question, haystack)
    coverage = _coverage(query_tokens, haystack_tokens)
    title_coverage = _coverage(query_tokens, name_tokens)
    confidence = _clamp01(component.confidence)
    authority = _clamp01(component.authority_weight)
    status = _status_score(component.status)
    provenance = _provenance_score(component)

    raw = (
        semantic * 0.28
        + lexical_norm * 0.24
        + coverage * 0.17
        + title_coverage * 0.12
        + exact * 0.10
        + confidence * 0.05
        + authority * 0.02
        + status * 0.01
        + provenance * 0.01
    )
    final = _calibrate(raw)
    return RerankFeatures(
        semantic_score=round(semantic, 6),
        lexical_score=round(float(lexical_score or 0.0), 6),
        lexical_score_normalized=round(lexical_norm, 6),
        exact_match_score=round(exact, 6),
        token_coverage=round(coverage, 6),
        title_coverage=round(title_coverage, 6),
        confidence_score=round(confidence, 6),
        authority_score=round(authority, 6),
        status_score=round(status, 6),
        provenance_score=round(provenance, 6),
        raw_score=round(raw, 6),
        final_score=round(final, 6),
    )


def _tokenize(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9][a-z0-9_-]{2,}", str(value or "").lower())
    }


def _coverage(query_tokens: set[str], haystack_tokens: set[str]) -> float:
    if not query_tokens:
        return 0.0
    return _clamp01(len(query_tokens & haystack_tokens) / len(query_tokens))


def _exact_match_score(question: str, haystack: str) -> float:
    normalized_question = " ".join(str(question or "").lower().split())
    normalized_haystack = " ".join(str(haystack or "").lower().split())
    if len(normalized_question) < 4:
        return 0.0
    if normalized_question in normalized_haystack:
        return 1.0
    query_tokens = re.findall(r"[a-z0-9][a-z0-9_-]{2,}", normalized_question)
    if len(query_tokens) < 2:
        return 0.0
    bigrams = {
        f"{query_tokens[idx]} {query_tokens[idx + 1]}"
        for idx in range(len(query_tokens) - 1)
    }
    if not bigrams:
        return 0.0
    hits = sum(1 for bigram in bigrams if bigram in normalized_haystack)
    return _clamp01(hits / len(bigrams))


def _status_score(status: str | None) -> float:
    return {
        "active": 1.0,
        "needs_review": 0.72,
        "proposed": 0.58,
        "stale": 0.22,
    }.get(str(status or "").lower(), 0.4)


def _provenance_score(component: Component) -> float:
    score = 0.0
    if component.source_document_id:
        score += 0.35
    if component.source_document and component.source_document.source_url:
        score += 0.15
    if component.provenance:
        score += 0.25
    if component.excerpt:
        score += 0.25
    return _clamp01(score)


def _calibrate(raw_score: float) -> float:
    # Logistic calibration keeps the public score in a stable 0..1 range while
    # preserving ordering from the deterministic feature blend.
    return _clamp01(1 / (1 + math.exp(-7.0 * (raw_score - 0.42))))


def _clamp01(value: float) -> float:
    if not math.isfinite(float(value)):
        return 0.0
    return max(0.0, min(float(value), 1.0))
