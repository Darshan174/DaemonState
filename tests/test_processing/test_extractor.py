"""Unit tests for the RegexExtractor."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.models.source import ConnectorType, SourceDocument
from app.processing.extractor import (
    ExtractedRelationship,
    ExtractionError,
    FallbackExtractor,
    RegexExtractor,
    StructuredLLMExtractor,
    build_default_extractor,
)


def _make_doc(
    content,
    *,
    channel="general",
    reply_count=None,
    meeting_topic=None,
    title=None,
    connector_type=ConnectorType.SLACK,
):
    meta = {}
    if channel is not None:
        meta["channel_name"] = channel
    if meeting_topic is not None:
        meta["meeting_topic"] = meeting_topic
    if title is not None:
        meta["title"] = title
    if reply_count is not None:
        meta["reply_count"] = reply_count
    doc = MagicMock(spec=SourceDocument)
    doc.content = content
    doc.metadata_json = meta
    doc.author = "test@example.com"
    doc.connector_type = connector_type
    doc.external_id = f"slack:C123:{uuid4().hex}"
    return doc


@pytest.fixture
def extractor():
    return RegexExtractor()


class TestRegexExtractorPatterns:
    async def test_extracts_decision_fact(self, extractor):
        doc = _make_doc("decision: launch the pricing page next Tuesday")
        facts = await extractor.extract(doc)
        assert len(facts) == 1
        f = facts[0]
        assert f.fact_type == "decision"
        assert f.name == "Decision in #general"
        assert "launch the pricing page" in f.value
        assert f.confidence == 0.75

    async def test_extracts_decided_variant(self, extractor):
        doc = _make_doc("decided: go with option B")
        facts = await extractor.extract(doc)
        assert len(facts) == 1
        assert facts[0].fact_type == "decision"

    async def test_extracts_action_item(self, extractor):
        doc = _make_doc("action item: write the migration guide")
        facts = await extractor.extract(doc)
        assert len(facts) == 1
        f = facts[0]
        assert f.fact_type == "action_item"
        assert f.name == "Action Item in #general"
        assert f.confidence == 0.70

    async def test_extracts_todo_variant(self, extractor):
        doc = _make_doc("TODO: update the README")
        facts = await extractor.extract(doc)
        assert len(facts) == 1
        assert facts[0].fact_type == "action_item"

    async def test_extracts_blocker(self, extractor):
        doc = _make_doc("blocker: waiting on legal approval")
        facts = await extractor.extract(doc)
        assert len(facts) == 1
        f = facts[0]
        assert f.fact_type == "blocker"
        assert f.name == "Blocker in #general"
        assert f.confidence == 0.80

    async def test_extracts_multiple_facts(self, extractor):
        doc = _make_doc(
            "decision: go live Friday\n"
            "action item: prepare rollback plan\n"
            "blocker: staging env is down"
        )
        facts = await extractor.extract(doc)
        types = {f.fact_type for f in facts}
        assert types == {"decision", "action_item", "blocker"}

    async def test_fallback_discussion_for_thread_with_replies(self, extractor):
        doc = _make_doc("just a message with no structure", reply_count=5)
        facts = await extractor.extract(doc)
        assert len(facts) == 1
        assert facts[0].fact_type == "discussion"
        assert facts[0].confidence == 0.55

    async def test_no_fallback_when_no_reply_count(self, extractor):
        doc = _make_doc("just a message with no structure")
        facts = await extractor.extract(doc)
        assert len(facts) == 0

    async def test_channel_name_in_fact_name(self, extractor):
        doc = _make_doc("decision: deploy today", channel="product")
        facts = await extractor.extract(doc)
        assert facts[0].name == "Decision in #product"

    async def test_meeting_topic_used_when_channel_missing(self, extractor):
        doc = _make_doc(
            "decision: ship the onboarding flow",
            channel=None,
            meeting_topic="Weekly Product Review",
        )
        facts = await extractor.extract(doc)
        assert facts[0].name == "Decision in Weekly Product Review"


class TestRegexExtractorRelationships:
    async def test_blocker_detects_blocked_by_relationship(self, extractor):
        doc = _make_doc("blocker: deploy is blocked by Decision in #general")
        facts = await extractor.extract(doc)
        assert len(facts) == 1
        f = facts[0]
        assert len(f.relationships) == 1
        rel = f.relationships[0]
        assert rel.relationship_type == "blocked_by"
        assert rel.target_fact_name == "Decision in #general"
        assert rel.confidence == 0.70

    async def test_blocker_without_blocked_by_has_no_relationships(self, extractor):
        doc = _make_doc("blocker: waiting on legal")
        facts = await extractor.extract(doc)
        assert facts[0].relationships == []

    async def test_decision_has_no_relationships(self, extractor):
        doc = _make_doc("decision: ship it")
        facts = await extractor.extract(doc)
        assert facts[0].relationships == []

    async def test_github_explicit_decision_and_rationale(self, extractor):
        doc = _make_doc(
            (
                "Repository: acme/context-engine\n"
                "Pull Request #77: Migration plan\n"
                "Referenced Pull Requests: acme/context-engine#12\n"
                "Referenced Issues: acme/context-engine#31\n"
                "Referenced Commits: abc1234\n"
                "Review Commit: abc1234\n"
                "Decision: use Postgres 16 rolling migration.\n"
                "Rationale: avoids downtime during cutover.\n"
            ),
            channel=None,
            title="Migration plan",
            connector_type=ConnectorType.GITHUB,
        )
        facts = await extractor.extract(doc)

        assert len(facts) == 2
        decision = next(fact for fact in facts if fact.fact_type == "decision")
        rationale = next(fact for fact in facts if fact.fact_type == "discussion")
        assert decision.name == "Decision in Migration plan"
        assert decision.value == "use Postgres 16 rolling migration"
        assert rationale.name == "Discussion in Migration plan"
        assert rationale.value == "Rationale: avoids downtime during cutover"
        assert rationale.relationships[0].target_fact_name == "Decision in Migration plan"

    async def test_zoom_meeting_extracts_outcome_and_owned_action_items(self, extractor):
        doc = _make_doc(
            (
                "Founder: meeting outcome: launch pricing page on April 15.\n"
                "Alice: action item: prepare demo environment.\n"
                "Bob: AI: draft launch email.\n"
            ),
            channel=None,
            meeting_topic="Weekly Product Review",
            connector_type=ConnectorType.ZOOM,
        )
        facts = await extractor.extract(doc)

        decisions = [fact for fact in facts if fact.fact_type == "decision"]
        actions = [fact for fact in facts if fact.fact_type == "action_item"]
        assert [fact.value for fact in decisions] == ["launch pricing page on April 15"]
        assert [fact.value for fact in actions] == [
            "Owner: Alice - prepare demo environment",
            "Owner: Bob - draft launch email",
        ]


class TestStructuredLLMExtractor:
    async def test_validates_structured_output(self):
        doc = _make_doc("decision: launch the pricing page next Tuesday")

        async def _complete(prompt: str):
            return {
                "facts": [
                    {
                        "name": "Decision in #general",
                        "value": "launch the pricing page next Tuesday",
                        "confidence": 0.91,
                        "fact_type": "decision",
                        "relationships": [],
                    }
                ]
            }

        extractor = StructuredLLMExtractor(completion_fn=_complete)
        facts = await extractor.extract(doc)

        assert len(facts) == 1
        assert facts[0].name == "Decision in #general"
        assert facts[0].confidence == 0.91
        assert facts[0].extractor.extractor_kind == "llm_structured"

    async def test_normalizes_generic_fact_names_and_limits_fact_count(self, monkeypatch):
        monkeypatch.setattr(
            "app.processing.extractor.settings.extraction_max_facts_per_document",
            1,
        )
        doc = _make_doc(
            "decision: launch the pricing page next Tuesday",
            channel=None,
            meeting_topic="Weekly Product Review",
        )

        async def _complete(prompt: str):
            return {
                "facts": [
                    {
                        "name": "decision",
                        "value": " launch the pricing page next Tuesday ",
                        "confidence": 0.91,
                        "fact_type": "decision",
                        "relationships": [],
                    },
                    {
                        "name": "another fact",
                        "value": "should be trimmed by max facts",
                        "confidence": 0.2,
                        "fact_type": "discussion",
                        "relationships": [],
                    },
                ]
            }

        extractor = StructuredLLMExtractor(completion_fn=_complete)
        facts = await extractor.extract(doc)

        assert len(facts) == 1
        assert facts[0].name == "Decision in Weekly Product Review"
        assert facts[0].value == "launch the pricing page next Tuesday"

    async def test_malformed_output_raises(self):
        doc = _make_doc("decision: launch the pricing page next Tuesday")

        async def _complete(prompt: str):
            return '{"facts":[{"name":"Decision only"}]}'

        extractor = StructuredLLMExtractor(completion_fn=_complete)

        with pytest.raises(ExtractionError, match="malformed output"):
            await extractor.extract(doc)

    async def test_long_documents_are_truncated_and_chunked(self, monkeypatch):
        monkeypatch.setattr(
            "app.processing.extractor.settings.extraction_max_input_chars",
            64,
        )
        monkeypatch.setattr(
            "app.processing.extractor.settings.extraction_chunk_size_chars",
            24,
        )
        monkeypatch.setattr(
            "app.processing.extractor.settings.extraction_chunk_overlap_chars",
            4,
        )
        prompts: list[str] = []
        doc = _make_doc(
            "decision: keep first part. " * 8 + "TAIL-END-SHOULD-NOT-APPEAR",
            connector_type=ConnectorType.ZOOM,
        )

        async def _complete(prompt: str):
            prompts.append(prompt)
            return {"facts": []}

        extractor = StructuredLLMExtractor(completion_fn=_complete)
        facts = await extractor.extract(doc)

        assert facts == []
        assert len(prompts) > 1
        joined = "\n".join(prompts)
        assert any("truncated" in prompt or "extraction ...]" in prompt for prompt in prompts)
        assert "TAIL-END-SHOULD-NOT-APPEAR" not in joined

    async def test_connector_specific_examples_are_included_in_prompt(self):
        prompts: list[str] = []
        doc = _make_doc(
            "Decision: use Postgres 16 rolling migration.",
            channel=None,
            title="Migration plan",
            connector_type=ConnectorType.GITHUB,
        )

        async def _complete(prompt: str):
            prompts.append(prompt)
            return {"facts": []}

        extractor = StructuredLLMExtractor(completion_fn=_complete)
        await extractor.extract(doc)

        assert len(prompts) == 1
        assert "Examples for github" in prompts[0]
        assert "Expected output" in prompts[0]


class TestFallbackExtractor:
    async def test_falls_back_to_regex_when_structured_output_is_malformed(self):
        doc = _make_doc("decision: deploy today")

        async def _complete(prompt: str):
            return '{"unexpected": []}'

        extractor = FallbackExtractor(
            primary=StructuredLLMExtractor(completion_fn=_complete),
            fallback=RegexExtractor(extractor_name="regex_fallback"),
        )
        facts = await extractor.extract(doc)

        assert len(facts) == 1
        assert facts[0].name == "Decision in #general"
        assert facts[0].extractor.extractor_name == "regex_fallback"


class TestBuildDefaultExtractor:
    def test_chooses_structured_plus_fallback_when_model_is_configured(self, monkeypatch):
        monkeypatch.setattr(
            "app.processing.extractor.settings.extraction_model",
            "openai/gpt-4.1-mini",
        )
        extractor = build_default_extractor()
        assert isinstance(extractor, FallbackExtractor)

    def test_uses_default_provider_model_when_opted_in(self, monkeypatch):
        monkeypatch.setattr(
            "app.processing.extractor.settings.extraction_model",
            None,
        )
        monkeypatch.setattr(
            "app.processing.extractor.settings.litellm_api_key",
            "sk-live-test",
        )
        monkeypatch.setattr(
            "app.processing.extractor.settings.default_extraction_model",
            "openai/gpt-4.1-mini",
        )
        monkeypatch.setattr(
            "app.processing.extractor.settings.enable_default_provider_models",
            True,
        )
        extractor = build_default_extractor()
        assert isinstance(extractor, FallbackExtractor)

    def test_placeholder_key_does_not_force_provider_extractor(self, monkeypatch):
        monkeypatch.setattr(
            "app.processing.extractor.settings.extraction_model",
            None,
        )
        monkeypatch.setattr(
            "app.processing.extractor.settings.litellm_api_key",
            "your-litellm-api-key",
        )
        monkeypatch.setattr(
            "app.processing.extractor.settings.enable_default_provider_models",
            True,
        )

        extractor = build_default_extractor()
        assert isinstance(extractor, RegexExtractor)

    def test_production_requires_real_extraction_model(self, monkeypatch):
        monkeypatch.setattr(
            "app.processing.extractor.settings.environment",
            "production",
        )
        monkeypatch.setattr(
            "app.processing.extractor.settings.extraction_model",
            None,
        )
        monkeypatch.setattr(
            "app.processing.extractor.settings.litellm_api_key",
            None,
        )

        with pytest.raises(ExtractionError, match="Production extraction requires"):
            build_default_extractor()
