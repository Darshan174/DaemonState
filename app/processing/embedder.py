"""Embeddings generation used for hybrid retrieval.

Embedder hierarchy:

- ``HashingEmbedder`` — **TEST / OFFLINE ONLY**.
  Deterministic pseudo-random vectors derived from token hashing.
  Not suitable for semantic retrieval — use exclusively in unit tests
  and local development when no embedding provider is configured.

- ``LiteLLMEmbedder`` — provider-backed embedder for production.
  Supports single-text and batch embedding via ``embed_texts``.

- ``LocalEmbedder`` (optional) — thin wrapper around a local ONNX /
  sentence-transformers model for offline development that still
  produces meaningful semantic vectors.  Enabled via
  ``ENABLE_LOCAL_EMBEDDER=true`` in settings.
"""

from __future__ import annotations

import hashlib
import math
import re
from abc import ABC, abstractmethod

from app.config import settings
from app.services.llm_service import (
    LLMConfigurationError,
    LLMResponseError,
    LLMServiceError,
    LiteLLMService,
    has_live_litellm_api_key,
)


class EmbeddingError(Exception):
    """Raised when an embedding request fails."""


class BaseEmbedder(ABC):
    dimension: int = 1024

    @abstractmethod
    async def embed_text(self, text: str) -> list[float]:
        """Return a normalized embedding vector for a single text."""

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Return normalized embedding vectors for a batch of texts.

        Default implementation calls ``embed_text`` sequentially.
        Subclasses should override for true parallel / batch support.
        """
        return [await self.embed_text(t) for t in texts]


class HashingEmbedder(BaseEmbedder):
    """Deterministic local baseline embedder for tests and offline development.

    ⚠️  WARNING: This embedder does NOT produce semantically meaningful vectors.
    It is intended ONLY for unit tests and offline development where the
    embedding path must be deterministic and provider-free.
    DO NOT use this in production — retrieval quality will be poor.
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

        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            return vector
        return [value / norm for value in vector]

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Batch hashing — processes all texts in a single pass over tokens."""
        return [await self.embed_text(t) for t in texts]


class LiteLLMEmbedder(BaseEmbedder):
    """Optional provider-backed embedder for production deployments.

    Supports batch embedding via ``embed_texts`` using the underlying
    ``LiteLLMService.embed_texts`` method, which sends all texts in a
    single API call.
    """

    def __init__(
        self,
        model: str,
        dimension: int = 1024,
        *,
        service: LiteLLMService | None = None,
    ) -> None:
        self.model = model
        self.dimension = dimension
        self.service = service or LiteLLMService()

    async def embed_text(self, text: str) -> list[float]:
        return (await self.embed_texts([text]))[0]

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Batch embed multiple texts in a single API call.

        Texts are split into batches of ``settings.embedding_batch_size``
        to avoid exceeding provider limits.
        """
        if not texts:
            return []

        batch_size = settings.embedding_batch_size
        all_vectors: list[list[float]] = []

        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            try:
                vectors = await self.service.embed_texts(
                    model=self.model,
                    texts=batch,
                    dimensions=self.dimension,
                )
            except (
                LLMConfigurationError,
                LLMServiceError,
                LLMResponseError,
                Exception,
            ) as exc:
                raise EmbeddingError(str(exc)) from exc
            all_vectors.extend(vectors)

        return all_vectors


class LocalEmbedder(BaseEmbedder):
    """Offline semantic embedder using sentence-transformers / ONNX.

    This embedder produces **meaningful semantic vectors** suitable for
    retrieval during local development.  It requires the optional
    ``sentence-transformers`` package.

    Install with: ``pip install sentence-transformers``

    Falls back to raising ImportError if the library is not available,
    which ``build_default_embedder`` catches and continues to the
    hashing embedder.
    """

    def __init__(self, dimension: int = 1024) -> None:
        from sentence_transformers import SentenceTransformer  # noqa: PLC0415

        # Use a small model that fits ~384 dimensions natively; pad/truncate
        # to the requested dimension if needed.
        self._model = SentenceTransformer("all-MiniLM-L6-v2")
        self._native_dim = self._model.get_sentence_embedding_dimension() or 384
        self.dimension = dimension

    async def embed_text(self, text: str) -> list[float]:
        return (await self.embed_texts([text]))[0]

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        import asyncio  # noqa: PLC0415

        vectors = await asyncio.to_thread(self._model.encode, texts, normalize_embeddings=True)
        return [self._adjust_dim(v.tolist()) for v in vectors]

    def _adjust_dim(self, vector: list[float]) -> list[float]:
        """Pad or truncate to the target dimension."""
        if len(vector) == self.dimension:
            return vector
        if len(vector) < self.dimension:
            return vector + [0.0] * (self.dimension - len(vector))
        return vector[: self.dimension]


def build_default_embedder() -> BaseEmbedder:
    """Return the best available embedder for the current environment.

    Resolution order:
    1. Explicit ``EMBEDDING_MODEL`` → LiteLLMEmbedder
    2. Default provider models + live API key → LiteLLMEmbedder
    3. ``ENABLE_LOCAL_EMBEDDER=true`` → LocalEmbedder (semantic, offline)
    4. Fallback → HashingEmbedder (test-only, non-semantic)

    In production, options 1 or 2 are required — otherwise an error
    is raised to prevent silent degradation.
    """
    model = _resolved_embedding_model()
    if model:
        return LiteLLMEmbedder(
            model,
            dimension=settings.embedding_dimensions,
        )

    if settings.enable_local_embedder:
        try:
            return LocalEmbedder(dimension=settings.embedding_dimensions)
        except ImportError:
            pass  # Fall through to hashing embedder

    if settings.environment == "production":
        raise EmbeddingError(
            "Production retrieval requires EMBEDDING_MODEL or LITELLM_API_KEY "
            "with DEFAULT_EMBEDDING_MODEL."
        )
    return HashingEmbedder()


def cosine_similarity(lhs: list[float] | None, rhs: list[float] | None) -> float:
    if lhs is None or rhs is None:
        return 0.0
    if len(lhs) == 0 or len(rhs) == 0:
        return 0.0
    return float(sum(a * b for a, b in zip(lhs, rhs)))


def _resolved_embedding_model() -> str | None:
    if settings.embedding_model:
        return settings.embedding_model
    if (
        settings.enable_default_provider_models
        and has_live_litellm_api_key()
        and settings.default_embedding_model
    ):
        return settings.default_embedding_model
    return None
