"""Embeddings generation for retrieval.

Provides two embedders:
  - HashingEmbedder — deterministic, no external deps (dev/test only)
  - LocalEmbedder — offline sentence-transformers (optional, semantic)
"""

from __future__ import annotations

import hashlib
import math
import re
from abc import ABC, abstractmethod
from typing import Any

from app.config import settings


class EmbeddingError(Exception):
    pass


class BaseEmbedder(ABC):
    dimension: int = 1024

    @abstractmethod
    async def embed_text(self, text: str) -> list[float]:
        pass

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [await self.embed_text(t) for t in texts]


class HashingEmbedder(BaseEmbedder):
    """Deterministic pseudo-random vectors from token hashing.

    NOT suitable for semantic retrieval. Use only in tests and
    offline development when no embedding provider is configured.
    """

    def __init__(self, dimension: int = 1024) -> None:
        self.dimension = dimension

    async def embed_text(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        tokens = re.findall(r"[a-z0-9_]+", text.lower())
        if not tokens:
            return vector

        for token in tokens:
            digest = hashlib.blake2b(token.encode(), digest_size=16).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimension
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            magnitude = 1.0 + (digest[5] / 255.0)
            vector[index] += sign * magnitude

        norm = math.sqrt(sum(v * v for v in vector))
        if norm == 0:
            return vector
        return [v / norm for v in vector]

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [await self.embed_text(t) for t in texts]


class LocalEmbedder(BaseEmbedder):
    """Offline semantic embedder using sentence-transformers.

    Produces meaningful vectors suitable for retrieval.
    Requires the optional ``sentence-transformers`` package.
    Install with: ``pip install sentence-transformers``
    """

    def __init__(self, dimension: int = 1024) -> None:
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer("all-MiniLM-L6-v2")
        self._native_dim = self._model.get_sentence_embedding_dimension() or 384
        self.dimension = dimension

    async def embed_text(self, text: str) -> list[float]:
        return (await self.embed_texts([text]))[0]

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        import asyncio

        vectors = await asyncio.to_thread(self._model.encode, texts, normalize_embeddings=True)
        return [self._adjust_dim(v.tolist()) for v in vectors]

    def _adjust_dim(self, vector: list[float]) -> list[float]:
        if len(vector) == self.dimension:
            return vector
        if len(vector) < self.dimension:
            return vector + [0.0] * (self.dimension - len(vector))
        return vector[: self.dimension]


class LiteLLMEmbedder(BaseEmbedder):
    """Semantic embedder backed by any LiteLLM-supported embedding provider."""

    def __init__(
        self,
        model: str,
        *,
        api_key: str | None = None,
        dimension: int | None = None,
    ) -> None:
        self.model = model
        self.api_key = api_key
        self.dimension = dimension or 0

    async def embed_text(self, text: str) -> list[float]:
        return (await self.embed_texts([text]))[0]

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        try:
            from litellm import aembedding
        except ImportError as exc:
            raise EmbeddingError("litellm is required for configured embedding models") from exc

        kwargs: dict[str, Any] = {"model": self.model, "input": texts}
        if self.api_key:
            kwargs["api_key"] = self.api_key
        try:
            response = await aembedding(**kwargs)
        except Exception as exc:  # pragma: no cover - provider-specific errors
            raise EmbeddingError(f"Embedding provider failed: {exc}") from exc

        data = response.get("data") if isinstance(response, dict) else getattr(response, "data", None)
        if not data:
            raise EmbeddingError("Embedding provider returned no vectors")

        vectors = []
        for item in data:
            raw = item.get("embedding") if isinstance(item, dict) else getattr(item, "embedding", None)
            if raw is None:
                raise EmbeddingError("Embedding provider returned an item without an embedding")
            vectors.append(_normalize(_adjust_dimension([float(v) for v in raw], self.dimension)))
        return vectors


def build_default_embedder() -> BaseEmbedder:
    """Return the best available embedder for the current environment.

    Resolution order:
    1. ``EMBEDDING_MODEL`` set → LiteLLMEmbedder
    2. ``ENABLE_LOCAL_EMBEDDER=true`` → LocalEmbedder (offline semantic)
    3. Fallback → HashingEmbedder (test-only, non-semantic)
    """
    if settings.embedding_model:
        return LiteLLMEmbedder(
            settings.embedding_model,
            api_key=settings.litellm_api_key,
            dimension=settings.embedding_dimension,
        )

    if settings.enable_local_embedder:
        try:
            return LocalEmbedder(dimension=settings.embedding_dimension or 1024)
        except ImportError:
            pass

    return HashingEmbedder()


def cosine_similarity(lhs: list[float] | None, rhs: list[float] | None) -> float:
    if lhs is None or rhs is None:
        return 0.0
    if len(lhs) == 0 or len(rhs) == 0:
        return 0.0
    return float(sum(a * b for a, b in zip(lhs, rhs)))


def _adjust_dimension(vector: list[float], dimension: int | None) -> list[float]:
    if not dimension or len(vector) == dimension:
        return vector
    if len(vector) < dimension:
        return vector + [0.0] * (dimension - len(vector))
    return vector[:dimension]


def _normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vector))
    if norm == 0:
        return vector
    return [v / norm for v in vector]
