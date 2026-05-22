from app.processing import embedder
from app.processing.embedder import LiteLLMEmbedder, build_default_embedder


def test_build_default_embedder_uses_configured_litellm_model(monkeypatch):
    monkeypatch.setattr(embedder.settings, "embedding_model", "openai/text-embedding-3-small")
    monkeypatch.setattr(embedder.settings, "litellm_api_key", "test-key")
    monkeypatch.setattr(embedder.settings, "embedding_dimension", 128)

    configured = build_default_embedder()

    assert isinstance(configured, LiteLLMEmbedder)
    assert configured.model == "openai/text-embedding-3-small"
    assert configured.api_key == "test-key"
    assert configured.dimension == 128
