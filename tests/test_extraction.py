from __future__ import annotations

import json

from app.processing.extractor import (
    ExtractedFact,
    ExtractedRelationship,
    Extractor,
    _facts_from_llm_payload,
    evaluate_extraction_quality,
)
from app.services.extraction_quality import extracted_fact_rejection_reason


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
        assert outcome.model_name == "Decision"
        assert outcome.fact_type == "outcome"
        assert "MVP" in outcome.value

    def test_extracts_only_explicitly_labelled_memory_types(self):
        ext = Extractor()
        facts = ext._regex_extract(
            "Requirement: Every memory row must cite its source.\n"
            "Constraint: Never promote a reported agent claim as verified.\n"
            "Assumption: The source revision is still current.\n"
            "Open question: Who owns the migration?\n"
            "Lesson: Exact evidence prevents false confidence.\n"
            "Failed attempt: Keyword buckets mixed unrelated sessions.\n"
            "Milestone: Finish the trust audit by Friday."
        )

        assert {fact.fact_type for fact in facts} >= {
            "requirement",
            "constraint",
            "assumption",
            "open_question",
            "lesson",
            "failed_attempt",
            "milestone",
        }

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

    def test_gmail_fallback_uses_subject_sender_and_snippet(self):
        ext = Extractor()
        facts = ext._regex_extract(
            "[Gmail] Launch plan\nFrom: PM <pm@example.com>\n\nQuick update from PM.",
            {
                "source_type": "gmail",
                "external_id": "gmail:18f98a7c",
                "subject": "Launch plan",
                "from": "PM <pm@example.com>",
                "snippet": "Quick update from PM.",
                "thread_id": "thread-1",
            },
        )

        assert len(facts) == 1
        fact = facts[0]
        assert fact.model_name == "Email"
        assert fact.fact_type == "email"
        assert "Launch plan" in fact.name
        assert "PM" in fact.name
        assert "18f98a7c" not in fact.name
        assert fact.excerpt == "Quick update from PM."
        assert fact.confidence >= 0.7
        assert fact.relationships == []
        provenance = json.loads(fact.provenance)
        assert provenance["external_id"] == "gmail:18f98a7c"

    def test_slack_pattern_facts_link_back_to_message_root(self):
        ext = Extractor()
        facts = ext._regex_extract(
            "Decision: we will use PostgreSQL for the production deployment",
            {
                "source_type": "slack",
                "external_id": "slack:C999:100.1",
                "channel_name": "engineering",
                "author_name": "Darshan",
                "user_id": "U1",
                "ts": "100.1",
            },
        )

        assert len(facts) == 3
        decision = next(f for f in facts if f.model_name == "Decision")
        root = next(f for f in facts if f.name.startswith("Slack: #engineering"))
        channel = next(f for f in facts if f.name == "Slack channel #engineering")

        assert len(decision.relationships) == 1
        rel = decision.relationships[0]
        assert rel.target_name == root.name
        assert rel.relationship_type == "discussed_in"
        assert rel.confidence == 0.9
        assert "PostgreSQL" in rel.evidence

        assert len(root.relationships) == 1
        channel_rel = root.relationships[0]
        assert channel_rel.target_name == channel.name
        assert channel_rel.relationship_type == "part_of"
        assert "#engineering" in channel_rel.evidence
        assert channel.relationships == []

    def test_non_slack_pattern_facts_get_no_message_root(self):
        ext = Extractor()
        facts = ext._regex_extract(
            "Decision: we will use PostgreSQL for the production deployment",
            {"source_type": "local", "external_id": "doc-1"},
        )

        assert len(facts) == 1
        assert facts[0].model_name == "Decision"
        assert facts[0].relationships == []

    def test_slack_fallback_uses_channel_author_and_message(self):
        ext = Extractor()
        facts = ext._regex_extract(
            "Please review the onboarding copy before launch.",
            {
                "source_type": "slack",
                "external_id": "slack:C123:1710000000.000100",
                "channel_name": "growth",
                "author_name": "Darshan",
                "user_id": "U123",
                "ts": "1710000000.000100",
            },
        )

        assert len(facts) == 2
        fact = facts[0]
        assert fact.model_name == "Message"
        assert fact.fact_type == "message"
        assert "#growth" in fact.name
        assert "Darshan" in fact.name
        assert "onboarding copy" in fact.name
        assert "C123" not in fact.name
        assert fact.excerpt == "Please review the onboarding copy before launch."

        channel = facts[1]
        assert channel.name == "Slack channel #growth"
        assert channel.model_name == "Message"
        assert len(fact.relationships) == 1
        assert fact.relationships[0].target_name == channel.name
        assert fact.relationships[0].relationship_type == "part_of"

    def test_slack_explicit_chat_patterns_keep_provenance(self):
        ext = Extractor()
        facts = ext._regex_extract(
            "We decided to ship thread-aware Slack ingest.\n"
            "Task - add permalink tests.\n"
            "Risk is Slack scopes may block reply access.",
            {
                "source_type": "slack",
                "external_id": "slack:C123:1710000000.000100",
                "channel_name": "engineering",
                "author_name": "Darshan",
                "user_id": "U123",
                "ts": "1710000000.000100",
                "thread_ts": "1710000000.000000",
                "parent_ts": "1710000000.000000",
                "is_thread_reply": True,
                "permalink": "https://slack.example/C123/p1710000000000100",
                "source_url": "https://slack.example/C123/p1710000000000100",
            },
        )

        decision = next(f for f in facts if f.model_name == "Decision")
        task = next(f for f in facts if f.model_name == "Task")
        risk = next(f for f in facts if f.model_name == "Risk")
        root = next(f for f in facts if f.name.startswith("Slack: #engineering"))

        assert "thread-aware Slack ingest" in decision.value
        assert "permalink tests" in task.value
        assert "scopes may block" in risk.value
        assert "Thread reply to: 1710000000.000000" in root.value

        provenance = json.loads(decision.provenance)
        assert provenance["source_url"] == "https://slack.example/C123/p1710000000000100"
        assert provenance["parent_ts"] == "1710000000.000000"
        assert provenance["is_thread_reply"] is True
        assert decision.excerpt is not None
        assert decision.relationships[0].relationship_type == "discussed_in"


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


class TestLLMExtractionContract:
    def test_llm_payload_skips_invalid_items_and_clamps_fields(self):
        facts, warnings = _facts_from_llm_payload({
            "facts": [
                {
                    "model_name": "Decisions",
                    "name": "OAuth2 auth decision",
                    "value": "Use OAuth2 for auth.",
                    "fact_type": "decision",
                    "confidence": 1.7,
                    "temporal": "later",
                    "relationships": [
                        {
                            "target_name": "Auth service",
                            "relationship_type": "depends",
                            "confidence": "-0.3",
                        },
                        {"relationship_type": "mentions"},
                    ],
                },
                {"value": "Missing name"},
                "not an object",
            ],
        })

        assert len(facts) == 1
        fact = facts[0]
        assert fact.model_name == "Decision"
        assert fact.confidence == 1.0
        assert fact.temporal == "unknown"
        assert len(fact.relationships) == 1
        assert fact.relationships[0].target_name == "Auth service"
        assert fact.relationships[0].confidence == 0.0
        assert "fact_0_invalid_temporal" in warnings
        assert "fact_1_missing_name" in warnings
        assert "fact_2_not_object" in warnings

    def test_extraction_quality_report_counts_risks(self):
        rel = ExtractedRelationship(
            target_name="Auth service",
            relationship_type="depends_on",
            confidence=0.8,
        )
        facts = [
            ExtractedFact(
                model_name="Decision",
                name="OAuth2 auth decision",
                value="Use OAuth2 for auth.",
                fact_type="decision",
                confidence=0.9,
                relationships=[rel],
            ),
            ExtractedFact(
                model_name="Decision",
                name="OAuth2 auth decision",
                value="Use OAuth2 for auth.",
                fact_type="decision",
                confidence=0.4,
            ),
        ]

        report = evaluate_extraction_quality(facts)

        assert report.fact_count == 2
        assert report.relationship_count == 1
        assert report.low_confidence_count == 1
        assert report.missing_provenance_count == 2
        assert report.missing_relationship_evidence_count == 1
        assert report.duplicate_fact_count == 1
        assert report.model_counts == {"Decision": 2}
        assert report.fact_type_counts == {"decision": 2}


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


def test_session_quality_gate_preserves_first_person_and_temporal_project_intent():
    valid_claims = [
        "I will use PostgreSQL for the evidence ledger.",
        "After launch, add billing reconciliation.",
        "When the migration completes, verify every evidence hash.",
    ]
    for value in valid_claims:
        fact = ExtractedFact(
            model_name="Task", name=f"Task: {value}", value=value,
            fact_type="task", confidence=0.9,
        )
        assert extracted_fact_rejection_reason(
            fact, source_type="agent_session"
        ) is None
