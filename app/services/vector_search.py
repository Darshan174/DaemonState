from __future__ import annotations

import math
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings


@dataclass(frozen=True)
class VectorSearchMatch:
    component_id: UUID
    semantic_score: float


@dataclass(frozen=True)
class VectorSearchResult:
    enabled: bool
    matches: list[VectorSearchMatch]
    reason: str | None = None


@dataclass(frozen=True)
class TextSearchMatch:
    component_id: UUID
    lexical_score: float


@dataclass(frozen=True)
class TextSearchResult:
    enabled: bool
    matches: list[TextSearchMatch]
    reason: str | None = None


async def search_component_vectors(
    session: AsyncSession,
    query_embedding: list[float],
    *,
    workspace_id: UUID | None,
    min_confidence: float,
    limit: int,
) -> VectorSearchResult:
    """Return nearest component ids from Postgres/pgvector when available.

    SQLite and Postgres databases without the pgvector extension deliberately
    return ``enabled=False`` so the caller can keep the existing Python path.
    """
    vector = _normalize_query_vector(query_embedding)
    if vector is None:
        return VectorSearchResult(enabled=False, matches=[], reason="invalid_query_vector")

    if _dialect_name(session) != "postgresql":
        return VectorSearchResult(enabled=False, matches=[], reason="non_postgres")

    if not await _pgvector_ready(session):
        return VectorSearchResult(enabled=False, matches=[], reason="pgvector_unavailable")

    dimension = len(vector)
    vector_literal = _to_pgvector_literal(vector)
    effective_limit = max(1, min(int(limit or settings.pgvector_candidate_limit), 1000))

    workspace_predicate = ""
    params: dict[str, object] = {
        "embedding": vector_literal,
        "dimension": dimension,
        "min_confidence": min_confidence,
        "limit": effective_limit,
    }
    if workspace_id is not None:
        workspace_predicate = """
          AND (workspace_id = :workspace_id OR workspace_id IS NULL)
        """
        params["workspace_id"] = str(workspace_id)

    try:
        async with session.begin_nested():
            rows = (await session.execute(text(f"""
                SELECT
                    id,
                    1 - (
                        embedding_vector::vector({dimension})
                        <=> CAST(:embedding AS vector({dimension}))
                    ) AS semantic_score
                FROM components
                WHERE embedding_vector IS NOT NULL
                  AND vector_dims(embedding_vector) = :dimension
                  AND status IN ('active', 'needs_review')
                  AND confidence >= :min_confidence
                  {workspace_predicate}
                ORDER BY
                    embedding_vector::vector({dimension})
                    <=> CAST(:embedding AS vector({dimension}))
                LIMIT :limit
            """), params)).fetchall()
    except SQLAlchemyError:
        return VectorSearchResult(enabled=False, matches=[], reason="query_failed")

    return VectorSearchResult(
        enabled=True,
        matches=[
            VectorSearchMatch(
                component_id=row[0] if isinstance(row[0], UUID) else UUID(str(row[0])),
                semantic_score=float(row[1] or 0.0),
            )
            for row in rows
        ],
    )


async def search_component_text(
    session: AsyncSession,
    query: str,
    *,
    workspace_id: UUID | None,
    min_confidence: float,
    limit: int,
) -> TextSearchResult:
    """Return lexical component candidates using Postgres full-text search."""
    normalized_query = " ".join(str(query or "").split())
    if not normalized_query:
        return TextSearchResult(enabled=False, matches=[], reason="empty_query")

    if _dialect_name(session) != "postgresql":
        return TextSearchResult(enabled=False, matches=[], reason="non_postgres")

    if not await _text_search_ready(session):
        return TextSearchResult(enabled=False, matches=[], reason="text_search_unavailable")

    effective_limit = max(1, min(int(limit or settings.pgvector_candidate_limit), 1000))
    workspace_predicate = ""
    params: dict[str, object] = {
        "query": normalized_query,
        "min_confidence": min_confidence,
        "limit": effective_limit,
    }
    if workspace_id is not None:
        workspace_predicate = """
          AND (workspace_id::text = :workspace_id OR workspace_id IS NULL)
        """
        params["workspace_id"] = str(workspace_id)

    try:
        async with session.begin_nested():
            rows = (await session.execute(text(f"""
                WITH q AS (
                    SELECT websearch_to_tsquery('english', :query) AS query
                )
                SELECT
                    components.id,
                    LEAST(ts_rank_cd(components.search_tsv, q.query, 32) * 8.0, 1.4)
                        AS lexical_score
                FROM components, q
                WHERE components.search_tsv IS NOT NULL
                  AND components.search_tsv @@ q.query
                  AND components.status IN ('active', 'needs_review')
                  AND components.confidence >= :min_confidence
                  {workspace_predicate}
                ORDER BY ts_rank_cd(components.search_tsv, q.query, 32) DESC
                LIMIT :limit
            """), params)).fetchall()
    except SQLAlchemyError:
        return TextSearchResult(enabled=False, matches=[], reason="query_failed")

    return TextSearchResult(
        enabled=True,
        matches=[
            TextSearchMatch(
                component_id=row[0] if isinstance(row[0], UUID) else UUID(str(row[0])),
                lexical_score=float(row[1] or 0.0),
            )
            for row in rows
        ],
    )


async def _pgvector_ready(session: AsyncSession) -> bool:
    try:
        async with session.begin_nested():
            row = (await session.execute(text("""
                SELECT
                    to_regtype('vector') IS NOT NULL AS has_vector_type,
                    EXISTS (
                        SELECT 1
                        FROM information_schema.columns
                        WHERE table_schema = current_schema()
                          AND table_name = 'components'
                          AND column_name = 'embedding_vector'
                    ) AS has_embedding_vector
            """))).one()
    except SQLAlchemyError:
        return False
    return bool(row[0] and row[1])


async def _text_search_ready(session: AsyncSession) -> bool:
    try:
        async with session.begin_nested():
            row = (await session.execute(text("""
                SELECT EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_schema = current_schema()
                      AND table_name = 'components'
                      AND column_name = 'search_tsv'
                ) AS has_search_tsv
            """))).one()
    except SQLAlchemyError:
        return False
    return bool(row[0])


def pgvector_index_dimension() -> int:
    dimension = settings.pgvector_index_dimension or settings.embedding_dimension or 1024
    return max(1, min(int(dimension), 2000))


def pgvector_candidate_limit(top_k: int) -> int:
    configured = max(1, int(settings.pgvector_candidate_limit or 200))
    recall_floor = max(int(top_k or 8) * 20, 100)
    return max(configured, recall_floor)


def _dialect_name(session: AsyncSession) -> str:
    try:
        return session.get_bind().dialect.name
    except Exception:
        return ""


def _normalize_query_vector(vector: list[float]) -> list[float] | None:
    if not vector:
        return None
    cleaned = []
    for value in vector:
        number = float(value)
        if not math.isfinite(number):
            return None
        cleaned.append(number)
    if not any(abs(value) > 1e-12 for value in cleaned):
        return None
    return cleaned


def _to_pgvector_literal(vector: list[float]) -> str:
    return "[" + ",".join(format(value, ".9g") for value in vector) + "]"
