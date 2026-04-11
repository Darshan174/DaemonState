"""Tests for extraction pipeline hardening: truncation, chunking, malformed output,
batch embeddings, few-shot prompts, and fallback behavior.
"""

from __future__ import annotations

import math
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.config import settings
from app.models.source import ConnectorType, SourceDocument
from app.processing.embedder import (
    BaseEmbedder,
    HashingEmbedder,
    LiteLLMEmbedder,
    LocalEmbedder,
    build_default_embedder,
)
from app.processing.extractor import (
    ExtractedFact,
    ExtractionError,
    FallbackExtractor,
    RegexExtractor,
    StructuredExtractionPayload,
    StructuredFactPayload,
    StructuredLLMExtractor,
    FEW_SHOT_EXAMPLES,
)


def _make_doc(
    content: str,
    *,
    channel: str | None = "general",
    connector_type: ConnectorType = ConnectorType.SLACK,
    source_url: str | None = None,
    author: str = "test@example.com",
    metadata_json: dict | None = None,
):
    meta = metadata_json or {}
    if channel is not None:
        meta.setdefault("channel_name", channel)
    doc = MagicMock(spec=SourceDocument)
    doc.content = content
    doc.metadata_json = meta
    doc.author = author
    doc.connector_type = connector_type
    doc.source_url = source_url
    doc.external_id = f"{connector_type.value}:test:{uuid4().hex}"
    return doc


# ── Truncation / Chunking Tests ──────────────────────────────────────────


class TestDocumentTruncation:
    """Document content longer than ``extraction_max_input_chars`` is truncated."""

    async def test_long_content_is_truncated(self):
        extractor = StructuredLLMExtractor(
            completion_fn=AsyncMock(return_value='{"facts": []}')
        )
        max_chars = settings.extraction_max_input_chars
        long_content = "x" * (max_chars + 5000)
        doc = _make_doc(long_content)

        received_prompts: list[str] = []

        async def capture_fn(prompt: str) -> str:
            received_prompts.append(prompt)
            return '{"facts": []}'

        extractor._completion_fn = capture_fn
        await extractor.extract(doc)

        # Content is truncated to max_chars, then chunked into ~2 chunks
        assert len(received_prompts) >= 1
        # The total content across all prompts should be <= truncated size
        total_doc_content = sum(p.count("Document:\n") * max_chars for p in received_prompts)
        # Each prompt should contain the truncation marker or be within chunk limits
        assert any("[... truncated for extraction ...]" in p for p in received_prompts)

    async def test_short_content_is_not_truncated(self):
        received_prompts: list[str] = []

        async def capture_fn(prompt: str) -> str:
            received_prompts.append(prompt)
            return '{"facts": []}'

        extractor = StructuredLLMExtractor(completion_fn=capture_fn)
        doc = _make_doc("short content")
        await extractor.extract(doc)

        assert len(received_prompts) == 1
        assert "short content" in received_prompts[0]
        assert "[... truncated for extraction ...]" not in received_prompts[0]


class TestDocumentChunking:
    """Documents exceeding ``extraction_chunk_size_chars`` are split into chunks."""

    async def test_content_split_into_overlapping_chunks(self):
        chunk_size = 100
        overlap = 20

        with (
            patch.object(settings, "extraction_chunk_size_chars", chunk_size),
            patch.object(settings, "extraction_chunk_overlap_chars", overlap),
        ):
            content = "A" * 250  # Should produce 3 chunks: [0:100], [80:180], [160:250]
            chunks = StructuredLLMExtractor._chunk_content(content)

            assert len(chunks) == 3
            assert len(chunks[0]) == chunk_size
            assert len(chunks[1]) == chunk_size
            # Last chunk is remainder
            assert len(chunks[2]) == 90  # 250 - 160 = 90
            # Overlap: last chars of chunk 0 match first chars of chunk 1
            assert chunks[0][-overlap:] == chunks[1][:overlap]

    async def test_short_content_single_chunk(self):
        content = "short"
        with patch.object(settings, "extraction_chunk_size_chars", 100):
            chunks = StructuredLLMExtractor._chunk_content(content)

        assert len(chunks) == 1
        assert chunks[0] == content

    async def test_chunk_extraction_produces_merged_facts(self):
        """Each chunk is extracted independently, then deduped."""
        call_count = 0

        async def fake_complete(prompt: str) -> str:
            nonlocal call_count
            call_count += 1
            return (
                f'{{"facts": [{{"name": "Fact {call_count}", "value": "v", '
                f'"confidence": 0.8, "fact_type": "decision", "relationships": []}}]}}'
            )

        # Content must exceed chunk_size to trigger chunking
        # 250 chars with chunk_size=100, overlap=20 → 3 chunks
        content = "A" * 250
        with (
            patch.object(settings, "extraction_max_input_chars", 500),
            patch.object(settings, "extraction_chunk_size_chars", 100),
            patch.object(settings, "extraction_chunk_overlap_chars", 20),
        ):
            extractor = StructuredLLMExtractor(completion_fn=fake_complete)
            doc = _make_doc(content)
            facts = await extractor.extract(doc)

        # Should have called completion once per chunk
        assert call_count == 3
        # Facts should be deduplicated by (name, value, type) — here all unique
        assert len(facts) == 3

    async def test_duplicate_facts_across_chunks_are_deduped(self):
        """Same fact appearing in overlapping chunks should be deduplicated."""
        async def fake_complete(prompt: str) -> str:
            return (
                '{"facts": [{"name": "Same Fact", "value": "same value", '
                '"confidence": 0.8, "fact_type": "decision", "relationships": []}]}'
            )

        content = "A" * 250
        with (
            patch.object(settings, "extraction_max_input_chars", 500),
            patch.object(settings, "extraction_chunk_size_chars", 100),
            patch.object(settings, "extraction_chunk_overlap_chars", 20),
        ):
            extractor = StructuredLLMExtractor(completion_fn=fake_complete)
            doc = _make_doc(content)
            facts = await extractor.extract(doc)

        # All chunks produce same fact — dedup should leave only 1
        assert len(facts) == 1


# ── Few-Shot Examples Tests ─────────────────────────────────────────────


class TestFewShotExamples:
    """Few-shot examples are injected per connector type."""

    def test_few_shot_examples_exist_for_key_connectors(self):
        assert "slack" in FEW_SHOT_EXAMPLES
        assert "zoom" in FEW_SHOT_EXAMPLES
        assert "github" in FEW_SHOT_EXAMPLES

    def test_few_shot_examples_contain_expected_schema(self):
        for connector_key, example_text in FEW_SHOT_EXAMPLES.items():
            assert "facts" in example_text
            assert "fact_type" in example_text
            assert "confidence" in example_text

    async def test_prompt_includes_few_shot_for_slack(self):
        received_prompts: list[str] = []

        async def capture_fn(prompt: str) -> str:
            received_prompts.append(prompt)
            return '{"facts": []}'

        extractor = StructuredLLMExtractor(completion_fn=capture_fn)
        doc = _make_doc("decision: ship it", connector_type=ConnectorType.SLACK)
        await extractor.extract(doc)

        assert len(received_prompts) == 1
        assert "slack" in received_prompts[0].lower()
        assert "Examples for slack:" in received_prompts[0]
        assert FEW_SHOT_EXAMPLES["slack"] in received_prompts[0]

    async def test_prompt_includes_few_shot_for_github(self):
        received_prompts: list[str] = []

        async def capture_fn(prompt: str) -> str:
            received_prompts.append(prompt)
            return '{"facts": []}'

        extractor = StructuredLLMExtractor(completion_fn=capture_fn)
        doc = _make_doc(
            "Decision: use Postgres",
            connector_type=ConnectorType.GITHUB,
            channel=None,
            metadata_json={"repo_full_name": "acme/repo"},
        )
        await extractor.extract(doc)

        assert len(received_prompts) == 1
        assert "Examples for github:" in received_prompts[0]

    async def test_unknown_connector_gets_no_few_shot(self):
        received_prompts: list[str] = []

        async def capture_fn(prompt: str) -> str:
            received_prompts.append(prompt)
            return '{"facts": []}'

        extractor = StructuredLLMExtractor(completion_fn=capture_fn)
        # Use SLACK but pretend it's unknown by patching the connector type value
        doc = _make_doc("decision: ship it")
        doc.connector_type = MagicMock()
        doc.connector_type.value = "unknown_connector"

        await extractor.extract(doc)

        assert len(received_prompts) == 1
        assert "Examples for" not in received_prompts[0]


# ── Malformed Extraction Output Tests ────────────────────────────────────


class TestMalformedExtractionOutput:
    """The extractor handles malformed or unexpected output gracefully."""

    async def test_invalid_json_raises_extraction_error(self):
        async def bad_output(prompt: str) -> str:
            return "not json at all"

        extractor = StructuredLLMExtractor(completion_fn=bad_output)
        doc = _make_doc("decision: ship it")

        with pytest.raises(ExtractionError, match="malformed output"):
            await extractor.extract(doc)

    async def test_missing_fields_raises_extraction_error(self):
        async def bad_output(prompt: str) -> str:
            return '{"facts": [{"name": "Incomplete"}]}'

        extractor = StructuredLLMExtractor(completion_fn=bad_output)
        doc = _make_doc("decision: ship it")

        with pytest.raises(ExtractionError, match="malformed output"):
            await extractor.extract(doc)

    async def test_empty_facts_list_is_valid(self):
        async def empty_output(prompt: str) -> str:
            return '{"facts": []}'

        extractor = StructuredLLMExtractor(completion_fn=empty_output)
        doc = _make_doc("some content with no facts")

        facts = await extractor.extract(doc)
        assert len(facts) == 0

    async def test_fallback_extractor_handles_malformed_llm(self):
        """FallbackExtractor should fall back to regex when LLM output is malformed."""
        async def bad_output(prompt: str) -> str:
            return '{"broken": true}'

        fallback = FallbackExtractor(
            primary=StructuredLLMExtractor(completion_fn=bad_output),
            fallback=RegexExtractor(extractor_name="regex_fb"),
        )
        doc = _make_doc("decision: use FastAPI")

        facts = await fallback.extract(doc)
        assert len(facts) == 1
        assert facts[0].fact_type == "decision"
        assert facts[0].extractor.extractor_name == "regex_fb"


# ── Batch Embedding Tests ────────────────────────────────────────────────


class TestBatchEmbedding:
    """Embeddings are batched during ingestion."""

    async def test_hashing_embedder_batch_path(self):
        embedder = HashingEmbedder(dimension=16)
        texts = ["hello world", "foo bar", "test text"]

        vectors = await embedder.embed_texts(texts)
        assert len(vectors) == 3
        for vec in vectors:
            assert len(vec) == 16
            norm = math.sqrt(sum(v * v for v in vec))
            assert pytest.approx(norm, abs=1e-6) == 1.0

    async def test_litellm_embedder_batches_calls(self):
        """LiteLLMEmbedder should batch texts into a single API call."""
        call_args: list[list[str]] = []

        class FakeService:
            async def embed_texts(self, *, model, texts, dimensions):
                call_args.append(texts)
                return [[0.1] * dimensions for _ in texts]

        with patch.object(settings, "embedding_batch_size", 10):
            embedder = LiteLLMEmbedder(
                "openai/text-embedding-3-large",
                dimension=8,
                service=FakeService(),
            )
            texts = [f"text {i}" for i in range(5)]
            vectors = await embedder.embed_texts(texts)

        assert len(vectors) == 5
        assert len(vectors[0]) == 8
        # Should be called once with all 5 texts
        assert len(call_args) == 1
        assert len(call_args[0]) == 5

    async def test_litellm_embedder_splits_large_batch(self):
        """If more texts than batch_size, should split into multiple calls."""
        call_count = 0

        class FakeService:
            async def embed_texts(self, *, model, texts, dimensions):
                nonlocal call_count
                call_count += 1
                return [[0.1] * dimensions for _ in texts]

        with patch.object(settings, "embedding_batch_size", 3):
            embedder = LiteLLMEmbedder(
                "openai/text-embedding-3-large",
                dimension=4,
                service=FakeService(),
            )
            texts = [f"text {i}" for i in range(7)]  # 7 texts, batch_size=3
            vectors = await embedder.embed_texts(texts)

        assert len(vectors) == 7
        assert call_count == 3  # 3 + 3 + 1

    async def test_embed_texts_empty_list(self):
        embedder = HashingEmbedder(dimension=8)
        vectors = await embedder.embed_texts([])
        assert vectors == []


# ── Fallback Behavior Tests ──────────────────────────────────────────────


class TestFallbackBehavior:
    """Fallback behavior when primary extraction or embedding fails."""

    async def test_fallback_extractor_on_empty_structured_facts(self):
        """FallbackExtractor should fall back to regex when structured returns no facts."""
        async def empty_output(prompt: str) -> str:
            return '{"facts": []}'

        fallback = FallbackExtractor(
            primary=StructuredLLMExtractor(completion_fn=empty_output),
            fallback=RegexExtractor(extractor_name="regex_fb"),
        )
        doc = _make_doc("decision: use FastAPI")

        facts = await fallback.extract(doc)
        assert len(facts) == 1
        assert facts[0].fact_type == "decision"
        assert facts[0].extractor.extractor_name == "regex_fb"

    async def test_fallback_extractor_uses_structured_when_valid(self):
        """FallbackExtractor should use structured facts when available."""
        async def valid_output(prompt: str) -> str:
            return (
                '{"facts": [{"name": "Structured Decision", "value": "use FastAPI", '
                '"confidence": 0.95, "fact_type": "decision", "relationships": []}]}'
            )

        fallback = FallbackExtractor(
            primary=StructuredLLMExtractor(completion_fn=valid_output),
            fallback=RegexExtractor(extractor_name="regex_fb"),
        )
        doc = _make_doc("decision: use FastAPI")

        facts = await fallback.extract(doc)
        assert len(facts) == 1
        assert facts[0].name == "Structured Decision"
        assert facts[0].extractor.extractor_kind == "llm_structured"


# ── Build Default Embedder Tests ─────────────────────────────────────────


class TestBuildDefaultEmbedder:
    """Tests for embedder resolution logic."""

    def test_hashing_embedder_is_test_only(self, monkeypatch):
        """When no model is configured and not production, returns HashingEmbedder."""
        monkeypatch.setattr("app.processing.embedder.settings.embedding_model", None)
        monkeypatch.setattr("app.processing.embedder.settings.litellm_api_key", None)
        monkeypatch.setattr(
            "app.processing.embedder.settings.enable_default_provider_models",
            False,
        )
        monkeypatch.setattr(
            "app.processing.embedder.settings.enable_local_embedder",
            False,
        )

        embedder = build_default_embedder()
        assert isinstance(embedder, HashingEmbedder)

    def test_provider_embedder_when_model_configured(self, monkeypatch):
        monkeypatch.setattr(
            "app.processing.embedder.settings.embedding_model",
            "openai/text-embedding-3-large",
        )
        embedder = build_default_embedder()
        assert isinstance(embedder, LiteLLMEmbedder)

    def test_local_embedder_flag_falls_through_when_not_installed(self, monkeypatch):
        monkeypatch.setattr("app.processing.embedder.settings.embedding_model", None)
        monkeypatch.setattr("app.processing.embedder.settings.litellm_api_key", None)
        monkeypatch.setattr(
            "app.processing.embedder.settings.enable_default_provider_models",
            False,
        )
        monkeypatch.setattr(
            "app.processing.embedder.settings.enable_local_embedder",
            True,
        )

        # sentence-transformers is not installed in test env, so should fall through
        embedder = build_default_embedder()
        assert isinstance(embedder, HashingEmbedder)

    def test_production_without_model_raises_error(self, monkeypatch):
        monkeypatch.setattr(
            "app.processing.embedder.settings.environment",
            "production",
        )
        monkeypatch.setattr("app.processing.embedder.settings.embedding_model", None)
        monkeypatch.setattr("app.processing.embedder.settings.litellm_api_key", None)
        monkeypatch.setattr(
            "app.processing.embedder.settings.enable_default_provider_models",
            False,
        )
        monkeypatch.setattr(
            "app.processing.embedder.settings.enable_local_embedder",
            False,
        )

        with pytest.raises(Exception, match="Production retrieval requires"):
            build_default_embedder()
