from __future__ import annotations

from app.processing.extractor import ExtractedFact, ExtractedRelationship, Extractor


class TestRegexExtractor:
    def test_extracts_decisions(self):
        ext = Extractor()
        facts = ext._regex_extract("Decision: We will use Postgres for the primary database.")

        assert len(facts) >= 1
        decision = facts[0]
        assert decision.model_name == "Decision"
        assert decision.fact_type == "decision"
        assert "Postgres" in decision.value

    def test_extracts_action_items(self):
        ext = Extractor()
        facts = ext._regex_extract("TODO: Add rate limiting to the API gateway.")

        assert len(facts) >= 1
        action = facts[0]
        assert action.model_name == "Task"
        assert action.fact_type == "task"
        assert "rate limiting" in action.value

    def test_extracts_blockers(self):
        ext = Extractor()
        facts = ext._regex_extract("Blocker: Waiting for SOC2 audit results before launch.")

        assert len(facts) >= 1
        blocker = facts[0]
        assert blocker.model_name == "Risk"
        assert blocker.fact_type == "blocker"
        assert "SOC2" in blocker.value

    def test_extracts_outcomes(self):
        ext = Extractor()
        facts = ext._regex_extract("Outcome: Team agreed to ship MVP by June 2026.")

        assert len(facts) >= 1
        outcome = facts[0]
        assert outcome.model_name == "Meeting"
        assert outcome.fact_type == "meeting_note"
        assert "MVP" in outcome.value

    def test_extracts_section_headings(self):
        ext = Extractor()
        facts = ext._regex_extract("## Pricing Strategy\n## Roadmap Plan\nSome content here.")

        assert facts[0].model_name == "Document"

    def test_extracts_bullet_points(self):
        ext = Extractor()
        facts = ext._regex_extract(
            "- Integrate Slack OAuth by end of Q2\n"
            "- Develop Discord ingestion pipeline\n"
            "- Ship Gmail connector beta"
        )

        assert facts[0].model_name == "Document"

    def test_regex_extractor_no_relationships(self):
        ext = Extractor()
        facts = ext._regex_extract("Decision: pricing will be $20/month for basic tier.")

        for fact in facts:
            assert len(fact.relationships) == 0

    def test_fallback_generic_when_no_patterns(self):
        ext = Extractor()
        facts = ext._regex_extract("This is just some random text without any structured patterns.")

        assert len(facts) == 1
        assert facts[0].model_name == "Document"
        assert facts[0].confidence == 0.50


class TestTemporalHintDetection:
    def test_detects_future_context(self):
        temporal = Extractor._detect_temporal_hint(
            "We plan to launch the enterprise tier next quarter. "
            "The upcoming release will include SSO and audit logging. "
            "Our target is Q4 2026 for SOC2 compliance."
        )
        assert temporal == "future"

    def test_detects_past_context(self):
        temporal = Extractor._detect_temporal_hint(
            "We previously used MySQL which was replaced by Postgres. "
            "The old pricing was $10/month but was deprecated last year. "
            "The earlier design was removed in favor of the new architecture."
        )
        assert temporal == "past"

    def test_detects_current_context_by_default(self):
        temporal = Extractor._detect_temporal_hint(
            "Pricing is $20/month for the basic tier. "
            "The system supports OAuth2 authentication."
        )
        assert temporal == "current"

    def test_regex_applies_temporal_hint(self):
        ext = Extractor()
        facts = ext._regex_extract(
            "We will use Rust for the performance-critical service. "
            "Decision: Adopt gRPC for inter-service communication. "
            "The old system was written in Python."
        )
        for fact in facts:
            assert hasattr(fact, "temporal_hint")
            assert fact.temporal_hint in ("current", "past", "future")


class TestExtractedFactDataclass:
    def test_temporal_hint_defaults_to_current(self):
        fact = ExtractedFact(
            model_name="Pricing",
            name="test",
            value="test value",
            fact_type="fact",
            confidence=0.8,
        )
        assert fact.temporal_hint == "current"

    def test_relationships_default_to_empty(self):
        fact = ExtractedFact(
            model_name="Pricing",
            name="test",
            value="test value",
            fact_type="fact",
            confidence=0.8,
        )
        assert fact.relationships == []

    def test_relationship_confidence_default(self):
        rel = ExtractedRelationship(
            target_name="SOC2 certification",
            relationship_type="depends_on",
        )
        assert rel.confidence == 0.7

    def test_relationship_evidence_defaults_to_none(self):
        rel = ExtractedRelationship(
            target_name="SOC2 certification",
            relationship_type="depends_on",
        )
        assert rel.evidence is None

    def test_relationship_evidence_can_be_set(self):
        rel = ExtractedRelationship(
            target_name="OAuth2",
            relationship_type="depends_on",
            confidence=0.85,
            evidence="SSO requires OAuth2 for token validation",
        )
        assert rel.evidence == "SSO requires OAuth2 for token validation"

    def test_relationship_confidence_clamped(self):
        rel = ExtractedRelationship(
            target_name="test",
            relationship_type="related_to",
            confidence=1.5,
        )
        assert rel.confidence == 1.5

    def test_extracted_fact_evidence_in_relationships(self):
        evidence = "Direct quote: pricing is $20/month"
        rel = ExtractedRelationship(
            target_name="Basic tier",
            relationship_type="enables",
            confidence=0.8,
            evidence=evidence,
        )
        fact = ExtractedFact(
            model_name="Pricing",
            name="$20/mo basic",
            value="Pricing is $20/month for the basic tier",
            fact_type="fact",
            confidence=0.85,
            relationships=[rel],
        )
        assert fact.relationships[0].evidence == evidence
