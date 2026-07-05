from app.processing import embedder
from app.processing.embedder import (
    HashingEmbedder,
    LexicalOnlyEmbedder,
    LiteLLMEmbedder,
    build_default_embedder,
)


def test_build_default_embedder_uses_configured_litellm_model(monkeypatch):
    monkeypatch.setattr(embedder.settings, "embedding_model", "openai/text-embedding-3-small")
    monkeypatch.setattr(embedder.settings, "litellm_api_key", "test-key")
    monkeypatch.setattr(embedder.settings, "embedding_dimension", 128)
    monkeypatch.setattr(embedder.settings, "allow_hashing_embedder", False)

    configured = build_default_embedder()

    assert isinstance(configured, LiteLLMEmbedder)
    assert configured.model == "openai/text-embedding-3-small"
    assert configured.api_key == "test-key"
    assert configured.dimension == 128


def test_build_default_embedder_is_lexical_only_without_semantic_config(monkeypatch):
    monkeypatch.setattr(embedder.settings, "embedding_model", None)
    monkeypatch.setattr(embedder.settings, "enable_local_embedder", False)
    monkeypatch.setattr(embedder.settings, "allow_hashing_embedder", False)
    monkeypatch.setattr(embedder.settings, "embedding_dimension", 16)

    configured = build_default_embedder()

    assert isinstance(configured, LexicalOnlyEmbedder)
    assert configured.dimension == 16


def test_build_default_embedder_hashing_requires_explicit_opt_in(monkeypatch):
    monkeypatch.setattr(embedder.settings, "embedding_model", None)
    monkeypatch.setattr(embedder.settings, "enable_local_embedder", False)
    monkeypatch.setattr(embedder.settings, "allow_hashing_embedder", True)
    monkeypatch.setattr(embedder.settings, "embedding_dimension", 16)

    configured = build_default_embedder()

    assert isinstance(configured, HashingEmbedder)
    assert configured.dimension == 16
