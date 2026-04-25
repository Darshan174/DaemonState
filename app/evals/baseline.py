"""Naive source-only RAG baseline for before/after eval comparisons.

This baseline intentionally ignores the Context Engine trust layer: it retrieves
raw source documents by lexical overlap and returns concatenated snippets. The
point is not to be a strong RAG system; it is to provide a deterministic
"plain RAG" floor that highlights the value of structured facts, current-truth
filtering, provenance, and review state.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.connector import Connector
from app.models.source import SourceDocument

_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "do",
    "for",
    "from",
    "how",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "our",
    "the",
    "to",
    "what",
    "when",
    "where",
    "which",
    "who",
    "why",
    "with",
}


@dataclass(frozen=True, slots=True)
class BaselineResult:
    answer: str
    source_external_ids: tuple[str, ...]


class NaiveRagBaseline:
    """Deterministic raw-document retrieval baseline."""

    def __init__(self, session: AsyncSession, *, top_k: int = 3) -> None:
        self.session = session
        self.top_k = top_k

    async def answer(self, question: str, workspace_id: UUID) -> BaselineResult:
        docs = await self._load_documents(workspace_id)
        if not docs:
            return BaselineResult(
                answer=f'No raw source documents matched "{question}".',
                source_external_ids=(),
            )

        question_tokens = _tokenize(question)
        scored = [
            (self._score_document(question_tokens, doc), doc)
            for doc in docs
        ]
        scored = [item for item in scored if item[0] > 0]
        if not scored:
            return BaselineResult(
                answer=f'No raw source documents matched "{question}".',
                source_external_ids=(),
            )

        scored.sort(
            key=lambda item: (
                item[0],
                item[1].created_at_source or item[1].ingested_at or datetime.min,
            ),
            reverse=True,
        )
        selected = [doc for _, doc in scored[: self.top_k]]
        snippets = " ".join(_snippet(doc.content) for doc in selected)
        return BaselineResult(
            answer=f"Naive source-only answer: {snippets}",
            source_external_ids=tuple(doc.external_id for doc in selected),
        )

    async def _load_documents(self, workspace_id: UUID) -> list[SourceDocument]:
        result = await self.session.scalars(
            select(SourceDocument)
            .join(Connector, SourceDocument.connector_id == Connector.id)
            .where(
                Connector.workspace_id == workspace_id,
                SourceDocument.deleted_at.is_(None),
            )
        )
        return list(result)

    @staticmethod
    def _score_document(question_tokens: set[str], doc: SourceDocument) -> float:
        metadata_text = " ".join(str(v) for v in (doc.metadata_json or {}).values())
        text = f"{doc.external_id} {metadata_text} {doc.content}"
        doc_tokens = _tokenize(text)
        if not doc_tokens:
            return 0.0
        overlap = len(question_tokens & doc_tokens)
        exact_bonus = 1.0 if any(token in doc.content.lower() for token in question_tokens) else 0.0
        return overlap + exact_bonus


def _tokenize(text: str) -> set[str]:
    tokens = re.findall(r"[a-z0-9_]+", text.lower())
    return {token for token in tokens if token not in _STOPWORDS}


def _snippet(text: str, *, max_chars: int = 260) -> str:
    compact = " ".join(text.split())
    if len(compact) <= max_chars:
        return compact
    return compact[: max_chars - 3].rstrip() + "..."
