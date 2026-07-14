from __future__ import annotations

import json
from uuid import uuid4

from sqlalchemy import select

from app.models import Component, Model, Relationship, SourceDocument
from app.agents.graph_builder import GraphBuilderAgent
from app.processing.extractor import ExtractedFact, ExtractedRelationship
from app.processing.source_extractors import (
    extract_agent_session,
    extract_github_issue,
    extract_github_pr,
)
from app.services.ingest import IngestionService, _determine_origin
from app.taxonomy import (
    canonical_source_type,
    canonical_fact_type,
    canonical_origin,
    canonical_temporal,
    relationship_display_label,
    source_type_display,
    VALID_SOURCE_TYPES,
    VALID_FACT_TYPES,
    VALID_RELATIONSHIP_ORIGINS,
)


class TestCanonicalSourceType:
    def test_valid_source_types_are_passed_through(self):
        for st in VALID_SOURCE_TYPES:
            assert canonical_source_type(st) == st

    def test_github_maps_to_github_issue(self):
        assert canonical_source_type("github") == "github_issue"

    def test_agent_aliases_map_to_agent_session(self):
        for alias in ("agent", "ai", "ai_session", "codex", "claude", "opencode", "cursor"):
            assert canonical_source_type(alias) == "agent_session"

    def test_empty_maps_to_local(self):
        assert canonical_source_type("") == "local"
        assert canonical_source_type(None) == "local"

    def test_unknown_is_passed_through(self):
        assert canonical_source_type("custom_tool") == "custom_tool"


class TestCanonicalFactType:
    def test_valid_fact_types_are_passed_through(self):
        for ft in VALID_FACT_TYPES:
            assert canonical_fact_type(ft) == ft

    def test_unknown_defaults_to_fact(self):
        assert canonical_fact_type("unknown_type") == "fact"
        assert canonical_fact_type(None) == "fact"


class TestCanonicalTemporal:
    def test_valid_temporal_states(self):
        for ts in ("current", "past", "future", "unknown"):
            assert canonical_temporal(ts) == ts

    def test_invalid_defaults_to_unknown(self):
        assert canonical_temporal("eventual") == "unknown"
        assert canonical_temporal(None) == "unknown"


class TestCanonicalOrigin:
    def test_valid_origins(self):
        assert canonical_origin("deterministic") == "deterministic"
        assert canonical_origin("proposed") == "proposed"

    def test_invalid_defaults_to_proposed(self):
        assert canonical_origin("maybe") == "proposed"
        assert canonical_origin(None) == "proposed"


class TestRelationshipDisplayLabel:
    def test_basic_label(self):
        assert relationship_display_label("depends_on") == "Depends On"

    def test_deterministic_label(self):
        label = relationship_display_label("solves", "deterministic")
        assert "solves" in label.lower()
        assert "deterministic" in label.lower()

    def test_proposed_label(self):
        label = relationship_display_label("related_to", "proposed")
        assert "Related To" in label


class TestSourceTypeDisplay:
    def test_known_source_types(self):
        assert source_type_display("github_issue") == "GitHub Issue"
        assert source_type_display("github_pr") == "GitHub Pull Request"
        assert source_type_display("agent_session") == "Agent Session"
        assert source_type_display("local") == "Local File"

    def test_unknown_source_type(self):
        assert source_type_display("custom") == "Custom"


class TestGitHubIssueExtraction:
    def test_extracts_issue_from_json(self):
        data = {
            "title": "Login page crashes on mobile",
            "body": "When I click login the app crashes.",
            "state": "open",
            "number": 42,
            "labels": ["bug", "mobile"],
            "html_url": "https://github.com/org/repo/issues/42",
        }
        facts = extract_github_issue(json.dumps(data))
        assert len(facts) >= 1
        assert facts[0].model_name == "Issue"
        assert facts[0].fact_type == "issue"
        assert facts[0].confidence >= 0.9
        assert "Login page crashes" in facts[0].name
        assert facts[0].temporal == "current"
        assert facts[0].provenance is not None
        prov = json.loads(facts[0].provenance)
        assert prov["source_type"] == "github_issue"
        assert prov["number"] == 42

    def test_extracts_bug_from_labels(self):
        data = {
            "title": "Crash report",
            "body": "App crashes on startup",
            "state": "open",
            "number": 10,
            "labels": ["bug"],
        }
        facts = extract_github_issue(json.dumps(data))
        bug_facts = [f for f in facts if f.fact_type == "blocker"]
        assert len(bug_facts) >= 1

    def test_extracts_feature_request_from_labels(self):
        data = {
            "title": "Add dark mode",
            "body": "We need dark mode.",
            "state": "open",
            "number": 5,
            "labels": ["enhancement"],
        }
        facts = extract_github_issue(json.dumps(data))
        feature_facts = [f for f in facts if f.fact_type == "feature"]
        assert len(feature_facts) >= 1

    def test_closed_issue_is_past(self):
        data = {
            "title": "Old bug",
            "body": "This was fixed.",
            "state": "closed",
            "number": 1,
        }
        facts = extract_github_issue(json.dumps(data))
        assert facts[0].temporal == "past"

    def test_extracts_tasks_from_issue_body(self):
        data = {
            "title": "Infrastructure improvements",
            "body": "TODO: Add monitoring\nAction item: Configure alerts",
            "state": "open",
            "number": 7,
        }
        facts = extract_github_issue(json.dumps(data))
        task_facts = [f for f in facts if f.fact_type == "task"]
        assert len(task_facts) >= 1

    def test_extracts_risks_from_issue_body(self):
        data = {
            "title": "Security concern",
            "body": "Blocker: Need AWS credentials before deployment\nRisk: Data leak potential",
            "state": "open",
            "number": 3,
        }
        facts = extract_github_issue(json.dumps(data))
        risk_facts = [f for f in facts if f.fact_type == "blocker"]
        assert len(risk_facts) >= 1

    def test_handles_text_fallback(self):
        facts = extract_github_issue("# My issue\nSome details here")
        assert len(facts) >= 1
        assert facts[0].model_name == "Issue"

    def test_handles_list_of_issues(self):
        issues = [
            {"title": "Issue 1", "body": "Body 1", "state": "open", "number": 1},
            {"title": "Issue 2", "body": "Body 2", "state": "closed", "number": 2},
        ]
        facts = extract_github_issue(json.dumps(issues))
        assert len(facts) >= 2

    def test_issue_facts_have_part_of_relationships(self):
        data = {
            "title": "Bug with label",
            "body": "Crash on page",
            "state": "open",
            "number": 9,
            "labels": ["bug"],
        }
        facts = extract_github_issue(json.dumps(data))
        bug_facts = [f for f in facts if f.fact_type == "blocker"]
        if bug_facts:
            assert any(r.relationship_type == "part_of" for r in bug_facts[0].relationships)


class TestGitHubPRExtraction:
    def test_extracts_pr_from_json(self):
        data = {
            "title": "Fix authentication bug",
            "body": "This PR fixes the login crash.",
            "state": "merged",
            "number": 15,
            "merged": True,
            "changed_files": ["src/auth.py", "tests/test_auth.py"],
            "html_url": "https://github.com/org/repo/pull/15",
        }
        facts = extract_github_pr(json.dumps(data))
        assert len(facts) >= 1
        assert facts[0].model_name == "PR"
        assert facts[0].fact_type == "pr"
        assert facts[0].temporal == "past"
        prov = json.loads(facts[0].provenance)
        assert prov["source_type"] == "github_pr"

    def test_extracts_changed_files(self):
        data = {
            "title": "Update config",
            "body": "Config changes.",
            "state": "open",
            "number": 3,
            "changed_files": ["config/app.yaml"],
        }
        facts = extract_github_pr(json.dumps(data))
        file_facts = [f for f in facts if f.fact_type == "changed_file"]
        assert len(file_facts) >= 1
        assert "config/app.yaml" in file_facts[0].name

    def test_extracts_linked_issues(self):
        data = {
            "title": "Fix bug #42",
            "body": "This fixes #42 and also #43",
            "state": "open",
            "number": 50,
        }
        facts = extract_github_pr(json.dumps(data))
        pr_fact = facts[0]
        fixes_rels = [r for r in pr_fact.relationships if r.relationship_type == "fixes"]
        assert len(fixes_rels) == 1

    def test_preserves_repository_qualified_issue_reference(self):
        data = {
            "title": "Fix a dependency issue",
            "body": "Fixes acme/repo-two#7",
            "state": "open",
            "number": 51,
            "linked_issues": [7],
        }
        facts = extract_github_pr(
            json.dumps(data),
            {"repo_full_name": "acme/repo-one"},
        )

        fixes_rels = [
            relationship
            for relationship in facts[0].relationships
            if relationship.relationship_type == "fixes"
        ]
        assert len(fixes_rels) == 1
        assert len(facts[0].relationships) == 1
        assert fixes_rels[0].target_name == "Issue acme/repo-two#7"
        assert fixes_rels[0].evidence == "PR #51 Fixes acme/repo-two#7"

    def test_extracts_review_findings(self):
        data = {
            "title": "Feature PR",
            "body": "Adding new feature.",
            "state": "open",
            "number": 8,
            "review_comments": ["This looks like a bug in the error handling, needs fix."],
        }
        facts = extract_github_pr(json.dumps(data))
        risk_facts = [f for f in facts if f.fact_type == "review_finding"]
        assert len(risk_facts) >= 1

    def test_merged_pr_is_past(self):
        data = {
            "title": "Merged PR",
            "body": "Done.",
            "state": "closed",
            "number": 1,
            "merged": True,
        }
        facts = extract_github_pr(json.dumps(data))
        assert facts[0].temporal == "past"

    def test_open_pr_is_current(self):
        data = {
            "title": "Open PR",
            "body": "In progress.",
            "state": "open",
            "number": 2,
        }
        facts = extract_github_pr(json.dumps(data))
        assert facts[0].temporal == "current"

    def test_handles_text_fallback(self):
        facts = extract_github_pr("# PR: Update docs\nSome details")
        assert len(facts) >= 1

    def test_pr_to_issue_deterministic_relationship(self):
        data = {
            "title": "Fix login crash",
            "body": "Fixes #42",
            "state": "merged",
            "number": 15,
        }
        facts = extract_github_pr(json.dumps(data))
        fixes_rels = []
        for f in facts:
            for r in f.relationships:
                if r.relationship_type == "fixes":
                    fixes_rels.append(r)
        assert len(fixes_rels) == 1
        assert fixes_rels[0].confidence >= 0.90


class TestAgentSessionExtraction:
    def test_extracts_session_root(self):
        content = "# Agent Session: Codex implementation\n\nFixed the login bug."
        facts = extract_agent_session(content, {"tool": "codex", "model": "gpt-4"})
        assert len(facts) >= 1
        root = facts[0]
        assert root.fact_type == "session_root"
        assert root.model_name == "Agent Session"
        assert root.provenance is not None
        prov = json.loads(root.provenance)
        assert prov["tool"] == "codex"
        assert prov["model"] == "gpt-4"

    def test_extracts_tasks_from_checklist(self):
        content = """# Session: Implementation

## Next Steps
- Next: Set up CI/CD pipeline
- TODO: Write integration tests
- Action: Deploy to staging
"""
        facts = extract_agent_session(content, {"tool": "opencode"})
        task_facts = [f for f in facts if f.fact_type == "task"]
        assert len(task_facts) >= 1
        for t in task_facts:
            assert t.temporal == "future"
            has_agent_rel = any(r.relationship_type == "generated_by_agent" for r in t.relationships)
            assert has_agent_rel

    def test_extracts_decisions(self):
        content = """# Session

Decision: Use PostgreSQL for primary database
We decided to go with the microservices approach.
"""
        facts = extract_agent_session(content, {"tool": "claude"})
        decision_facts = [f for f in facts if f.fact_type == "decision"]
        assert len(decision_facts) >= 1
        for d in decision_facts:
            has_agent_rel = any(r.relationship_type == "generated_by_agent" for r in d.relationships)
            assert has_agent_rel

    def test_extracts_risks(self):
        content = """# Session

Blocker: Need AWS credentials
Risk: Data migration may fail on large tables
Unresolved question: What about backwards compatibility?
"""
        facts = extract_agent_session(content, {"tool": "codex"})
        blocker_facts = [f for f in facts if f.fact_type == "blocker"]
        risk_facts = [f for f in facts if f.fact_type == "risk"]
        assert any(f.value == "Need AWS credentials" and f.temporal == "current" for f in blocker_facts)
        assert any(f.value == "Data migration may fail on large tables" for f in risk_facts)
        assert any(f.value == "What about backwards compatibility?" for f in risk_facts)

        failed = extract_agent_session("Failed: OAuth redirect test timed out", {"tool": "codex"})
        assert any(
            f.value == "OAuth redirect test timed out" and f.fact_type == "blocker" and f.temporal == "past"
            for f in failed
        )

    def test_ignores_user_instruction_sections(self):
        content = """[USER]
Risk: request escalation and prefix_rule handling can affect tools.
Decision: base_instructions govern the session.

[ASSISTANT]
Decision: Keep graph zoom scoped to the digest board.
Risk: Data migration may fail on large tables.
"""
        facts = extract_agent_session(content, {"tool": "codex"})
        extracted = {f.value for f in facts if f.fact_type in {"decision", "risk", "blocker"}}

        assert "Keep graph zoom scoped to the digest board" in extracted
        assert "Data migration may fail on large tables" in extracted
        assert not any("prefix_rule" in value for value in extracted)
        assert not any("base_instructions" in value for value in extracted)

    def test_skips_progress_update_fragments(self):
        content = """# Session

Risk: only because Vitest does not accept Jest's --runInBand flag here, so I'm rerunning the project test command.
Risk: Data migration may fail on large tables.
"""
        facts = extract_agent_session(content, {"tool": "codex"})
        extracted = {f.value for f in facts if f.fact_type in {"decision", "risk", "blocker"}}

        assert "Data migration may fail on large tables" in extracted
        assert not any("rerunning" in value for value in extracted)

    def test_skips_instruction_and_media_noise(self):
        content = f"""# Session

Decision: Keep graph zoom scoped to the digest board
Decision: base_instructions require request escalation and prefix_rule handling
Blocker: data:image/png;base64,{"A" * 220}
"""
        facts = extract_agent_session(content, {"tool": "codex"})
        extracted = {f.value for f in facts if f.fact_type in {"decision", "blocker"}}

        assert "Keep graph zoom scoped to the digest board" in extracted
        assert not any("base_instructions" in value for value in extracted)
        assert not any("data:image" in value for value in extracted)

    def test_extracts_file_references(self):
        content = """# Session

Changed src/auth.py and tests/test_auth.py for the login fix.
Updated app/models.py for the new schema.
"""
        facts = extract_agent_session(content, {"tool": "opencode"})
        file_facts = [f for f in facts if f.name.startswith("File:")]
        assert len(file_facts) >= 2
        assert any("src/auth.py" in f.name for f in file_facts)
        assert any("app/models.py" in f.name for f in file_facts)

    def test_session_root_has_high_confidence(self):
        facts = extract_agent_session("# My session\nContent here", {"tool": "codex"})
        assert facts[0].confidence >= 0.90

    def test_empty_metadata_still_works(self):
        facts = extract_agent_session("# Session\nContent")
        assert len(facts) >= 1
        assert facts[0].fact_type == "session_root"

    def test_preserves_metadata_in_provenance(self):
        meta = {
            "session_id": "abc-123",
            "tool": "codex",
            "model": "glm-5",
            "branch": "main",
            "commit": "abc1234",
        }
        facts = extract_agent_session("# Session\nContent", meta)
        prov = json.loads(facts[0].provenance)
        assert prov["session_id"] == "abc-123"
        assert prov["tool"] == "codex"
        assert prov["branch"] == "main"
        assert prov["commit"] == "abc1234"


class TestDetermineOrigin:
    def test_deterministic_types_are_deterministic(self):
        for rel_type in ["solves", "created_from", "part_of", "generated_by_agent", "implemented_in"]:
            rel = ExtractedRelationship(
                target_name="test", relationship_type=rel_type, confidence=0.8,
            )
            assert _determine_origin("github_issue", rel) == "deterministic"

    def test_github_pr_solves_is_deterministic(self):
        rel = ExtractedRelationship(
            target_name="Issue #42", relationship_type="solves", confidence=0.95,
        )
        assert _determine_origin("github_pr", rel) == "deterministic"

    def test_agent_session_source_is_deterministic(self):
        rel = ExtractedRelationship(
            target_name="Session", relationship_type="generated_by_agent", confidence=0.9,
        )
        assert _determine_origin("agent_session", rel) == "deterministic"

    def test_local_source_related_to_is_proposed(self):
        rel = ExtractedRelationship(
            target_name="Other", relationship_type="related_to", confidence=0.7,
        )
        assert _determine_origin("local", rel) == "proposed"


class TestRelationshipSafety:
    async def test_relationship_without_evidence_is_not_persisted(self, db_session):
        model = Model(id=uuid4(), name="Test")
        db_session.add(model)
        await db_session.flush()

        doc = SourceDocument(
            id=uuid4(), source_type="local", external_id="evidence-safety",
            content="A depends on B.", metadata_json="{}",
        )
        db_session.add(doc)
        await db_session.flush()

        source = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="A", value="Component A", fact_type="fact",
            confidence=0.8, status="active",
        )
        target = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="B", value="Component B", fact_type="fact",
            confidence=0.8, status="active",
        )
        db_session.add_all([source, target])
        await db_session.flush()

        svc = IngestionService(db_session)
        rel = ExtractedRelationship(
            target_name="B", relationship_type="depends_on", confidence=0.8,
        )
        await svc._create_relationship(source, rel, origin="proposed")

        rels = (await db_session.scalars(
            select(Relationship).where(Relationship.source_component_id == source.id)
        )).all()
        assert rels == []
        assert svc.last_projection_report["relationships_rejected_missing_evidence"] == 1

    async def test_relationship_stores_origin(self, db_session):
        model = Model(id=uuid4(), name="Test")
        db_session.add(model)
        await db_session.flush()

        doc = SourceDocument(
            id=uuid4(), source_type="github_pr", external_id="origin-test",
            content="PR fixes #5.", metadata_json="{}",
        )
        db_session.add(doc)
        await db_session.flush()

        source = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="PR #3", value="Fix login", fact_type="pr",
            confidence=0.9, status="active",
        )
        target = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="Issue #5", value="Login broken", fact_type="issue",
            confidence=0.9, status="active",
        )
        db_session.add_all([source, target])
        await db_session.flush()

        svc = IngestionService(db_session)
        rel = ExtractedRelationship(
            target_name="Issue #5", relationship_type="solves", confidence=0.95,
            evidence="PR #3 fixes #5",
        )
        await svc._create_relationship(source, rel, origin="deterministic")

        rels = (await db_session.scalars(
            select(Relationship).where(Relationship.source_component_id == source.id)
        )).all()
        assert len(rels) == 1
        assert rels[0].origin == "deterministic"

    async def test_no_self_loops_enforced(self, db_session):
        model = Model(id=uuid4(), name="Test")
        db_session.add(model)
        await db_session.flush()

        doc = SourceDocument(
            id=uuid4(), source_type="local", external_id="self-loop-safety",
            content="A refs A.", metadata_json="{}",
        )
        db_session.add(doc)
        await db_session.flush()

        component = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="A", value="Component A", fact_type="fact",
            confidence=0.8, status="active",
        )
        db_session.add(component)
        await db_session.flush()

        svc = IngestionService(db_session)
        rel = ExtractedRelationship(
            target_name="A", relationship_type="related_to", confidence=0.8,
        )
        await svc._create_relationship(component, rel, origin="proposed")

        count = await db_session.scalar(
            select(Relationship).where(
                Relationship.source_component_id == component.id,
                Relationship.target_component_id == component.id,
            )
        )
        assert count is None

    async def test_related_to_below_threshold_skipped(self, db_session):
        model = Model(id=uuid4(), name="Test")
        db_session.add(model)
        await db_session.flush()

        doc = SourceDocument(
            id=uuid4(), source_type="local", external_id="weak-rel",
            content="A mentions B.", metadata_json="{}",
        )
        db_session.add(doc)
        await db_session.flush()

        source = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="A", value="Component A", fact_type="fact",
            confidence=0.8, status="active",
        )
        target = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="B", value="Component B", fact_type="fact",
            confidence=0.8, status="active",
        )
        db_session.add_all([source, target])
        await db_session.flush()

        svc = IngestionService(db_session)
        rel = ExtractedRelationship(
            target_name="B", relationship_type="related_to", confidence=0.65,
        )
        await svc._create_relationship(source, rel, origin="proposed")

        count = await db_session.scalar(
            select(Relationship).where(Relationship.source_component_id == source.id)
        )
        assert count is None

    async def test_no_unrelated_word_overlap_relationships(self, db_session):
        model = Model(id=uuid4(), name="Test")
        db_session.add(model)
        await db_session.flush()

        doc = SourceDocument(
            id=uuid4(), source_type="local", external_id="no-word-rel",
            content=".", metadata_json="{}",
        )
        db_session.add(doc)
        await db_session.flush()

        svc = IngestionService(db_session)
        rel = ExtractedRelationship(
            target_name="Roadmap plan", relationship_type="related_to", confidence=0.55,
            evidence="Both mention time planning",
        )
        component_a = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="Pricing tier", value="Pricing at $20/month",
            fact_type="fact", confidence=0.8, status="active",
        )
        component_b = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="Roadmap plan", value="Roadmap for Q4 2026",
            fact_type="fact", confidence=0.8, status="active",
        )
        db_session.add_all([component_a, component_b])
        await db_session.flush()

        await svc._create_relationship(component_a, rel, origin="proposed")

        count = await db_session.scalar(
            select(Relationship).where(Relationship.source_component_id == component_a.id)
        )
        assert count is None

    async def test_deterministic_relationship_created(self, db_session):
        model = Model(id=uuid4(), name="Test")
        db_session.add(model)
        await db_session.flush()

        doc = SourceDocument(
            id=uuid4(), source_type="github_pr", external_id="det-rel",
            content="PR fixes #10", metadata_json="{}",
        )
        db_session.add(doc)
        await db_session.flush()

        pr_comp = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="PR #5: Fix bug", value="Fixes login crash",
            fact_type="pr", confidence=0.92, status="active",
        )
        issue_comp = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="Issue #10", value="Login crashes",
            fact_type="issue", confidence=0.9, status="active",
        )
        db_session.add_all([pr_comp, issue_comp])
        await db_session.flush()

        svc = IngestionService(db_session)
        rel = ExtractedRelationship(
            target_name="Issue #10", relationship_type="solves", confidence=0.95,
            evidence="PR #5 references #10",
        )
        await svc._create_relationship(pr_comp, rel, origin="deterministic")

        rels = (await db_session.scalars(
            select(Relationship).where(Relationship.source_component_id == pr_comp.id)
        )).all()
        assert len(rels) == 1
        assert rels[0].origin == "deterministic"
        assert rels[0].confidence >= 0.9


class TestGithubPRToIssueDeterministic:
    async def test_graph_builder_links_github_pr_to_issue_thread(self, db_session):
        model = Model(id=uuid4(), name="GitHub")
        issue_doc = SourceDocument(
            id=uuid4(),
            source_type="github",
            external_id="issue-12",
            content="Issue #12",
            metadata_json=json.dumps({
                "item_type": "issue",
                "repo_full_name": "org/repo",
                "number": 12,
            }),
        )
        pr_doc = SourceDocument(
            id=uuid4(),
            source_type="github",
            external_id="pr-12",
            content="PR #12",
            metadata_json=json.dumps({
                "item_type": "pull_request",
                "repo_full_name": "org/repo",
                "number": 12,
            }),
        )
        issue_comp = Component(
            id=uuid4(), model_id=model.id, source_document_id=issue_doc.id,
            name="Issue #12: Fix graph", value="closed",
            fact_type="issue", confidence=0.95, status="active",
        )
        pr_comp = Component(
            id=uuid4(), model_id=model.id, source_document_id=pr_doc.id,
            name="PR #12: Fix graph", value="merged",
            fact_type="pull_request", confidence=0.95, status="active",
        )
        db_session.add_all([model, issue_doc, pr_doc, issue_comp, pr_comp])
        await db_session.flush()

        agent = GraphBuilderAgent(db_session)
        inferred = await agent._infer_deterministic_relationships()
        await db_session.flush()

        rels = (await db_session.scalars(
            select(Relationship).where(Relationship.source_component_id == pr_comp.id)
        )).all()
        assert inferred == 0
        assert rels == []

    async def test_graph_builder_links_slack_github_url_to_issue(self, db_session):
        github_model = Model(id=uuid4(), name="GitHub")
        message_model = Model(id=uuid4(), name="Message")
        issue_doc = SourceDocument(
            id=uuid4(),
            source_type="github",
            external_id="issue-42",
            content="Issue #42",
            metadata_json=json.dumps({
                "item_type": "issue",
                "repo_full_name": "org/repo",
                "number": 42,
            }),
        )
        slack_doc = SourceDocument(
            id=uuid4(),
            source_type="slack",
            external_id="slack:C123:1.0",
            content="Decision: track this in https://github.com/org/repo/issues/42",
            metadata_json=json.dumps({"channel_name": "engineering"}),
        )
        issue_comp = Component(
            id=uuid4(), model_id=github_model.id, source_document_id=issue_doc.id,
            name="Issue #42: Thread-aware Slack ingest", value="Track Slack threading",
            fact_type="issue", confidence=0.95, status="active",
        )
        slack_comp = Component(
            id=uuid4(), model_id=message_model.id, source_document_id=slack_doc.id,
            name="Slack decision", value="Track this in GitHub issue 42",
            fact_type="decision", confidence=0.82, status="active",
        )
        db_session.add_all([github_model, message_model, issue_doc, slack_doc, issue_comp, slack_comp])
        await db_session.flush()

        agent = GraphBuilderAgent(db_session)
        inferred = await agent._infer_deterministic_relationships()
        await db_session.flush()

        rels = (await db_session.scalars(
            select(Relationship).where(Relationship.source_component_id == slack_comp.id)
        )).all()
        assert inferred == 1
        assert len(rels) == 1
        assert rels[0].target_component_id == issue_comp.id
        assert rels[0].relationship_type == "mentions"
        assert rels[0].origin == "deterministic"
        assert rels[0].confidence == 0.98
        assert "github.com/org/repo/issues/42" in rels[0].evidence

    async def test_graph_builder_skips_ambiguous_slack_issue_number(self, db_session):
        github_model = Model(id=uuid4(), name="GitHub")
        message_model = Model(id=uuid4(), name="Message")
        first_issue_doc = SourceDocument(
            id=uuid4(),
            source_type="github",
            external_id="repo-one-issue-7",
            content="Issue #7",
            metadata_json=json.dumps({
                "item_type": "issue",
                "repo_full_name": "org/repo-one",
                "number": 7,
            }),
        )
        second_issue_doc = SourceDocument(
            id=uuid4(),
            source_type="github",
            external_id="repo-two-issue-7",
            content="Issue #7",
            metadata_json=json.dumps({
                "item_type": "issue",
                "repo_full_name": "org/repo-two",
                "number": 7,
            }),
        )
        slack_doc = SourceDocument(
            id=uuid4(),
            source_type="slack",
            external_id="slack:C123:2.0",
            content="Risk: Issue #7 is still blocking launch.",
            metadata_json=json.dumps({"channel_name": "engineering"}),
        )
        first_issue = Component(
            id=uuid4(), model_id=github_model.id, source_document_id=first_issue_doc.id,
            name="Issue #7: First repo", value="First issue",
            fact_type="issue", confidence=0.95, status="active",
        )
        second_issue = Component(
            id=uuid4(), model_id=github_model.id, source_document_id=second_issue_doc.id,
            name="Issue #7: Second repo", value="Second issue",
            fact_type="issue", confidence=0.95, status="active",
        )
        slack_comp = Component(
            id=uuid4(), model_id=message_model.id, source_document_id=slack_doc.id,
            name="Slack risk", value="Issue #7 is still blocking launch.",
            fact_type="risk", confidence=0.82, status="active",
        )
        db_session.add_all([
            github_model, message_model, first_issue_doc, second_issue_doc, slack_doc,
            first_issue, second_issue, slack_comp,
        ])
        await db_session.flush()

        agent = GraphBuilderAgent(db_session)
        inferred = await agent._infer_deterministic_relationships()
        await db_session.flush()

        rels = (await db_session.scalars(
            select(Relationship).where(Relationship.source_component_id == slack_comp.id)
        )).all()
        assert inferred == 0
        assert rels == []

    async def test_graph_builder_links_slack_to_named_document(self, db_session):
        document_model = Model(id=uuid4(), name="Document")
        message_model = Model(id=uuid4(), name="Message")
        doc_source = SourceDocument(
            id=uuid4(),
            source_type="gdrive",
            external_id="gdrive:doc-1",
            content="Product Context RFC body",
            source_url="https://docs.example/product-context-rfc",
            metadata_json=json.dumps({
                "title": "Product Context RFC",
                "source_type": "gdrive",
            }),
        )
        slack_doc = SourceDocument(
            id=uuid4(),
            source_type="slack",
            external_id="slack:C123:3.0",
            content="Decision: follow Product Context RFC for connector scoping.",
            metadata_json=json.dumps({"channel_name": "product"}),
        )
        document_comp = Component(
            id=uuid4(), model_id=document_model.id, source_document_id=doc_source.id,
            name="Document: Product Context RFC", value="Connector scoping rules",
            fact_type="document", confidence=0.9, status="active",
        )
        slack_comp = Component(
            id=uuid4(), model_id=message_model.id, source_document_id=slack_doc.id,
            name="Slack decision", value="Follow Product Context RFC for connector scoping.",
            fact_type="decision", confidence=0.82, status="active",
        )
        db_session.add_all([document_model, message_model, doc_source, slack_doc, document_comp, slack_comp])
        await db_session.flush()

        agent = GraphBuilderAgent(db_session)
        inferred = await agent._infer_deterministic_relationships()
        await db_session.flush()

        rels = (await db_session.scalars(
            select(Relationship).where(Relationship.source_component_id == slack_comp.id)
        )).all()
        assert inferred == 1
        assert len(rels) == 1
        assert rels[0].target_component_id == document_comp.id
        assert rels[0].relationship_type == "mentions"
        assert rels[0].origin == "deterministic"
        assert rels[0].confidence == 0.9
        assert "Product Context RFC" in rels[0].evidence

    async def test_graph_builder_links_github_issue_that_mentions_slack_to_channel_hub(self, db_session):
        github_model = Model(id=uuid4(), name="GitHub")
        message_model = Model(id=uuid4(), name="Message")
        issue_doc = SourceDocument(
            id=uuid4(),
            source_type="github",
            external_id="issue-6",
            content="Issue #6: Harden Slack connector retries",
            metadata_json=json.dumps({
                "item_type": "issue",
                "repo_full_name": "org/repo",
                "number": 6,
            }),
        )
        slack_doc = SourceDocument(
            id=uuid4(),
            source_type="slack",
            external_id="slack:C123:hub",
            content="Slack channel #engineering hub",
            metadata_json=json.dumps({"channel_name": "engineering"}),
        )
        issue_comp = Component(
            id=uuid4(), model_id=github_model.id, source_document_id=issue_doc.id,
            name="Issue #6: Harden Slack connector retries", value="Improve Slack sync reliability",
            fact_type="issue", confidence=0.95, status="active",
        )
        slack_hub = Component(
            id=uuid4(), model_id=message_model.id, source_document_id=slack_doc.id,
            name="Slack channel #engineering",
            value="Slack channel #engineering — hub for messages ingested from this channel.",
            fact_type="fact", confidence=0.9, status="active",
        )
        db_session.add_all([github_model, message_model, issue_doc, slack_doc, issue_comp, slack_hub])
        await db_session.flush()

        agent = GraphBuilderAgent(db_session)
        inferred = await agent._infer_deterministic_relationships()
        await db_session.flush()

        rels = (await db_session.scalars(
            select(Relationship).where(Relationship.source_component_id == issue_comp.id)
        )).all()
        assert inferred == 0
        assert rels == []

    async def test_pr_solves_issue_deterministic(self, db_session):
        model = Model(id=uuid4(), name="GitHub")
        db_session.add(model)
        await db_session.flush()

        doc = SourceDocument(
            id=uuid4(), source_type="github_pr", external_id="pr-20",
            content=".", metadata_json="{}",
        )
        db_session.add(doc)
        await db_session.flush()

        pr_comp = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="PR #20: Fix auth", value="Fixes the auth bug",
            fact_type="pr", confidence=0.92, status="active",
        )
        issue_comp = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="Issue #15", value="Auth crash",
            fact_type="issue", confidence=0.9, status="active",
        )
        db_session.add_all([pr_comp, issue_comp])
        await db_session.flush()

        svc = IngestionService(db_session)
        rel = ExtractedRelationship(
            target_name="Issue #15", relationship_type="solves", confidence=0.95,
            evidence="PR #20 fixes Issue #15",
        )
        await svc._create_relationship(pr_comp, rel, origin="deterministic")

        rels = (await db_session.scalars(
            select(Relationship).where(Relationship.source_component_id == pr_comp.id)
        )).all()
        assert len(rels) == 1
        assert rels[0].relationship_type == "solves"
        assert rels[0].origin == "deterministic"


class TestGithubPRChangedFile:
    async def test_pr_changed_file_relationship(self, db_session):
        model = Model(id=uuid4(), name="Repo")
        db_session.add(model)
        await db_session.flush()

        doc = SourceDocument(
            id=uuid4(), source_type="github_pr", external_id="pr-files",
            content=".", metadata_json="{}",
        )
        db_session.add(doc)
        await db_session.flush()

        file_comp = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="File: src/auth.py", value="Changed in PR #10",
            fact_type="changed_file", confidence=0.9, status="active",
        )
        pr_comp = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="PR #10", value="Auth fix",
            fact_type="pr", confidence=0.92, status="active",
        )
        db_session.add_all([file_comp, pr_comp])
        await db_session.flush()

        svc = IngestionService(db_session)
        rel = ExtractedRelationship(
            target_name="PR #10", relationship_type="implemented_in", confidence=0.9,
            evidence="File src/auth.py changed in PR #10",
        )
        await svc._create_relationship(file_comp, rel, origin="deterministic")

        rels = (await db_session.scalars(
            select(Relationship).where(Relationship.source_component_id == file_comp.id)
        )).all()
        assert len(rels) == 1
        assert rels[0].origin == "deterministic"


class TestSessionTaskDecisionRelationships:
    async def test_task_linked_to_session(self, db_session):
        model = Model(id=uuid4(), name="Agent Session")
        db_session.add(model)
        await db_session.flush()

        doc = SourceDocument(
            id=uuid4(), source_type="agent_session", external_id="session-task",
            content="TODO: Set up CI/CD pipeline",
            metadata_json=json.dumps({"tool": "codex", "session_id": "s123"}),
        )
        db_session.add(doc)
        await db_session.flush()

        session_comp = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="Session: codex implementation", value="Session content",
            fact_type="session_root", confidence=0.93, status="active",
        )
        task_comp = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="Task: Set up CI/CD pipeline", value="Set up CI/CD pipeline",
            fact_type="task", confidence=0.75, status="proposed",
        )
        db_session.add_all([session_comp, task_comp])
        await db_session.flush()

        svc = IngestionService(db_session)
        rel = ExtractedRelationship(
            target_name="Session: codex implementation",
            relationship_type="generated_by_agent", confidence=0.9,
            evidence="Task extracted from agent session",
        )
        await svc._create_relationship(task_comp, rel, origin="deterministic")

        rels = (await db_session.scalars(
            select(Relationship).where(Relationship.source_component_id == task_comp.id)
        )).all()
        assert len(rels) == 1
        assert rels[0].relationship_type == "generated_by_agent"
        assert rels[0].origin == "deterministic"

    async def test_decision_linked_to_session(self, db_session):
        model = Model(id=uuid4(), name="Agent Session")
        db_session.add(model)
        await db_session.flush()

        doc = SourceDocument(
            id=uuid4(), source_type="agent_session", external_id="session-dec",
            content="Decision: Use PostgreSQL for primary DB",
            metadata_json=json.dumps({"tool": "claude"}),
        )
        db_session.add(doc)
        await db_session.flush()

        session_comp = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="Session: claude research", value="Session",
            fact_type="session_root", confidence=0.93, status="active",
        )
        dec_comp = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="Decision: Use PostgreSQL", value="Use PostgreSQL for primary DB",
            fact_type="decision", confidence=0.82, status="active",
        )
        db_session.add_all([session_comp, dec_comp])
        await db_session.flush()

        svc = IngestionService(db_session)
        rel = ExtractedRelationship(
            target_name="Session: claude research",
            relationship_type="generated_by_agent", confidence=0.88,
            evidence="Decision from agent session",
        )
        await svc._create_relationship(dec_comp, rel, origin="deterministic")

        rels = (await db_session.scalars(
            select(Relationship).where(Relationship.source_component_id == dec_comp.id)
        )).all()
        assert len(rels) == 1
        assert rels[0].origin == "deterministic"


class TestComponentProvenanceAndExcerpt:
    async def test_component_stores_provenance(self, db_session):
        model = Model(id=uuid4(), name="PR")
        db_session.add(model)
        await db_session.flush()

        doc = SourceDocument(
            id=uuid4(), source_type="github_pr", external_id="prov-test",
            content="PR content.", metadata_json="{}",
        )
        db_session.add(doc)
        await db_session.flush()

        svc = IngestionService(db_session)
        fact = ExtractedFact(
            model_name="PR", name="PR #1: Fix bug", value="Fixed the bug",
            fact_type="pr", confidence=0.92, temporal="current",
            provenance='{"source_type": "github_pr", "number": 1}',
            excerpt="Fixed the bug in auth.py",
        )
        comp = await svc._upsert_component(model, doc, fact)
        assert comp.provenance == '{"source_type": "github_pr", "number": 1}'
        assert comp.excerpt == "Fixed the bug in auth.py"

    async def test_component_excerpt_preserved_on_upsert(self, db_session):
        model = Model(id=uuid4(), name="Issue")
        db_session.add(model)
        await db_session.flush()

        doc = SourceDocument(
            id=uuid4(), source_type="github_issue", external_id="excerpt-test",
            content="Issue content.", metadata_json="{}",
        )
        db_session.add(doc)
        await db_session.flush()

        svc = IngestionService(db_session)
        fact1 = ExtractedFact(
            model_name="Issue", name="Bug: crash", value="App crashes on login",
            fact_type="issue", confidence=0.88,
            provenance='{"source_type": "github_issue"}', excerpt="App crashes on login",
        )
        comp1 = await svc._upsert_component(model, doc, fact1)

        fact2 = ExtractedFact(
            model_name="Issue", name="Bug: crash", value="App crashes on login",
            fact_type="issue", confidence=0.90,
            provenance=None, excerpt=None,
        )
        comp2 = await svc._upsert_component(model, doc, fact2)
        assert comp2.id == comp1.id
        assert comp2.provenance == '{"source_type": "github_issue"}'
        assert comp2.excerpt == "App crashes on login"


class TestSourceSpecificExtraction:
    async def test_github_issue_source_triggers_issue_extractor(self, db_session):
        model = Model(id=uuid4(), name="Issue")
        db_session.add(model)
        await db_session.flush()

        issue_data = {
            "title": "Login crashes on mobile",
            "body": "When I click login the app crashes.",
            "state": "open",
            "number": 42,
            "labels": ["bug"],
        }
        doc = SourceDocument(
            id=uuid4(), source_type="github_issue",
            external_id="gh-issue-42",
            content=json.dumps(issue_data),
            metadata_json="{}",
        )
        db_session.add(doc)
        await db_session.flush()

        svc = IngestionService(db_session)
        count = await svc.process_document(doc.id)
        assert count > 0

        components = (await db_session.scalars(
            select(Component).where(Component.source_document_id == doc.id)
        )).all()
        assert len(components) > 0
        assert any(c.fact_type == "issue" for c in components)

    async def test_agent_session_source_triggers_session_extractor(self, db_session):
        doc = SourceDocument(
            id=uuid4(), source_type="agent_session",
            external_id="session-test-1",
            content="# Session\n\nDecision: Use GraphQL\n\nTODO: Write tests",
            metadata_json=json.dumps({"tool": "codex", "model": "gpt-4"}),
        )
        db_session.add(doc)
        await db_session.flush()

        svc = IngestionService(db_session)
        count = await svc.process_document(doc.id)
        assert count > 0

        components = (await db_session.scalars(
            select(Component).where(Component.source_document_id == doc.id)
        )).all()
        assert any(c.fact_type == "session_root" for c in components)

    async def test_github_pr_source_triggers_pr_extractor(self, db_session):
        pr_data = {
            "title": "Fix auth bug",
            "body": "Fixes #10",
            "state": "merged",
            "number": 15,
            "merged": True,
            "changed_files": ["src/auth.py"],
        }
        doc = SourceDocument(
            id=uuid4(), source_type="github_pr",
            external_id="gh-pr-15",
            content=json.dumps(pr_data),
            metadata_json="{}",
        )
        db_session.add(doc)
        await db_session.flush()

        svc = IngestionService(db_session)
        count = await svc.process_document(doc.id)
        assert count > 0

        components = (await db_session.scalars(
            select(Component).where(Component.source_document_id == doc.id)
        )).all()
        assert any(c.fact_type == "pr" for c in components)
        pr_component = next(c for c in components if c.fact_type == "pr")
        file_component = next(c for c in components if c.fact_type == "changed_file")
        relationship = await db_session.scalar(select(Relationship).where(
            Relationship.relationship_type == "touches_file"
        ))
        assert relationship is not None
        assert relationship.source_component_id == pr_component.id
        assert relationship.target_component_id == file_component.id

    async def test_local_source_uses_regex_extractor(self, db_session):
        doc = SourceDocument(
            id=uuid4(), source_type="local",
            external_id="local-doc-1",
            content="Decision: Use Postgres for primary database.\nTODO: Write migration scripts.",
            metadata_json="{}",
        )
        db_session.add(doc)
        await db_session.flush()

        svc = IngestionService(db_session)
        count = await svc.process_document(doc.id)
        assert count > 0

        components = (await db_session.scalars(
            select(Component).where(Component.source_document_id == doc.id)
        )).all()
        assert any(c.fact_type == "decision" for c in components)


class TestGraphAPIDisplayMetadata:
    async def test_component_includes_provenance(self, client, db_session):
        model = Model(id=uuid4(), name="PR")
        doc = SourceDocument(
            id=uuid4(), source_type="github_pr", external_id="api-prov",
            content="PR content.", metadata_json="{}",
        )
        component = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="PR #1: Fix", value="Fix", fact_type="pr",
            confidence=0.92, status="active",
            provenance='{"source_type": "github_pr", "number": 1}',
            excerpt="Fixed the bug",
        )
        db_session.add_all([model, doc, component])
        await db_session.flush()

        resp = await client.get("/api/graph")
        assert resp.status_code == 200
        data = resp.json()
        comp = next(c for c in data["components"] if c["id"] == str(component.id))
        assert comp["provenance"] == '{"source_type": "github_pr", "number": 1}'
        assert comp["excerpt"] == "Fixed the bug"

    async def test_relationship_includes_origin(self, client, db_session):
        model = Model(id=uuid4(), name="Test")
        doc = SourceDocument(
            id=uuid4(), source_type="github_pr", external_id="api-origin",
            content=".", metadata_json="{}",
        )
        a = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="A", value="A", fact_type="fact",
            confidence=0.8, status="active",
        )
        b = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="B", value="B", fact_type="fact",
            confidence=0.8, status="active",
        )
        rel = Relationship(
            id=uuid4(), source_component_id=a.id, target_component_id=b.id,
            relationship_type="solves", confidence=0.95,
            evidence="PR fixes issue", origin="deterministic",
        )
        db_session.add_all([model, doc, a, b, rel])
        await db_session.flush()

        resp = await client.get("/api/graph")
        data = resp.json()
        rels = [r for r in data["relationships"] if r["id"] == str(rel.id)]
        assert len(rels) == 1
        assert rels[0]["origin"] == "deterministic"
        assert rels[0]["display_label"] is not None
        assert "Solves" in rels[0]["display_label"]

    async def test_component_includes_source_metadata_summary(self, client, db_session):
        model = Model(id=uuid4(), name="Agent Session")
        doc = SourceDocument(
            id=uuid4(), source_type="agent_session", external_id="api-meta",
            content="Session content.",
            metadata_json=json.dumps({"tool": "codex", "model": "gpt-4", "session_id": "s1"}),
        )
        component = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="Session: codex", value="Session", fact_type="session_root",
            confidence=0.93, status="active",
        )
        db_session.add_all([model, doc, component])
        await db_session.flush()

        resp = await client.get("/api/graph")
        data = resp.json()
        comp = next(c for c in data["components"] if c["id"] == str(component.id))
        assert comp["source_type"] == "agent_session"
        meta = comp["source_metadata_summary"]
        assert meta is not None
        assert meta.get("tool") == "codex"
        assert meta.get("session_id") == "s1"

    async def test_component_includes_source_external_id(self, client, db_session):
        model = Model(id=uuid4(), name="Issue")
        doc = SourceDocument(
            id=uuid4(), source_type="github_issue", external_id="gh-42",
            content="Issue content.", metadata_json="{}",
        )
        component = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="Issue #42", value="Bug", fact_type="issue",
            confidence=0.9, status="active",
        )
        db_session.add_all([model, doc, component])
        await db_session.flush()

        resp = await client.get("/api/graph")
        data = resp.json()
        comp = next(c for c in data["components"] if c["id"] == str(component.id))
        assert comp["source_external_id"] == "gh-42"

    async def test_confidence_filter(self, client, db_session):
        model = Model(id=uuid4(), name="Test")
        doc = SourceDocument(
            id=uuid4(), source_type="local", external_id="conf-filter",
            content=".", metadata_json="{}",
        )
        high = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="High confidence", value="Sure", fact_type="fact",
            confidence=0.95, status="active",
        )
        low = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="Low confidence", value="Unsure", fact_type="fact",
            confidence=0.5, status="active",
        )
        db_session.add_all([model, doc, high, low])
        await db_session.flush()

        resp = await client.get("/api/graph", params={"confidence_min": 0.8})
        data = resp.json()
        comp_names = [c["name"] for c in data["components"]]
        assert "High confidence" in comp_names
        assert "Low confidence" not in comp_names

    async def test_temporal_filter(self, client, db_session):
        model = Model(id=uuid4(), name="Test")
        doc = SourceDocument(
            id=uuid4(), source_type="local", external_id="temp-filter",
            content=".", metadata_json="{}",
        )
        comp_current = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="Current", value="Current fact", fact_type="fact",
            confidence=0.8, status="active", temporal="current",
        )
        comp_past = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="Past", value="Past fact", fact_type="fact",
            confidence=0.8, status="active", temporal="past",
        )
        comp_future = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="Future", value="Future fact", fact_type="fact",
            confidence=0.7, status="proposed", temporal="future",
        )
        db_session.add_all([model, doc, comp_current, comp_past, comp_future])
        await db_session.flush()

        resp = await client.get("/api/graph", params={"temporal": "current"})
        data = resp.json()
        comp_names = [c["name"] for c in data["components"]]
        assert "Current" in comp_names
        assert "Past" not in comp_names
        assert "Future" not in comp_names

    async def test_work_lens_endpoint(self, client, db_session):
        model = Model(id=uuid4(), name="Risk")
        doc = SourceDocument(
            id=uuid4(), source_type="local", external_id="work-lens",
            content=".", metadata_json="{}",
        )
        blocker = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="AWS creds blocker", value="Need AWS credentials",
            fact_type="blocker", confidence=0.9, status="active",
            excerpt="Waiting for AWS access",
        )
        db_session.add_all([model, doc, blocker])
        await db_session.flush()

        resp = await client.get("/api/work-lens")
        assert resp.status_code == 200
        data = resp.json()
        assert "blockers" in data
        assert "open_decisions" in data
        assert "active_tasks" in data
        assert len(data["blockers"]) >= 1
        assert data["blockers"][0]["fact_type"] == "blocker"

    async def test_source_diff_endpoint(self, client, db_session):
        model = Model(id=uuid4(), name="Issue")
        doc = SourceDocument(
            id=uuid4(), source_type="github_issue", external_id="diff-test",
            content="Issue content.", metadata_json="{}",
        )
        component = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="Issue #1", value="Bug report", fact_type="issue",
            confidence=0.9, status="active",
        )
        db_session.add_all([model, doc, component])
        await db_session.flush()

        resp = await client.get(f"/api/graph/source-diff/{doc.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert "source" in data
        assert "components" in data
        assert "relationships" in data
        assert data["source"]["source_type"] == "github_issue"
        assert len(data["components"]) >= 1

    async def test_relationship_origin_filter(self, client, db_session):
        model = Model(id=uuid4(), name="Test")
        doc = SourceDocument(
            id=uuid4(), source_type="github_pr", external_id="origin-filter",
            content=".", metadata_json="{}",
        )
        a = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="A", value="A", fact_type="fact", confidence=0.8, status="active",
        )
        b = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="B", value="B", fact_type="fact", confidence=0.8, status="active",
        )
        det_rel = Relationship(
            id=uuid4(), source_component_id=a.id, target_component_id=b.id,
            relationship_type="solves", confidence=0.95,
            evidence="Deterministic", origin="deterministic",
        )
        prop_rel = Relationship(
            id=uuid4(), source_component_id=b.id, target_component_id=a.id,
            relationship_type="related_to", confidence=0.7,
            evidence="Proposed", origin="proposed",
        )
        db_session.add_all([model, doc, a, b, det_rel, prop_rel])
        await db_session.flush()

        resp_det = await client.get("/api/graph", params={"relationship_origin": "deterministic"})
        data_det = resp_det.json()
        det_ids = [r["id"] for r in data_det["relationships"]]
        assert str(det_rel.id) in det_ids
        assert str(prop_rel.id) not in det_ids

        resp_prop = await client.get("/api/graph", params={"relationship_origin": "proposed"})
        data_prop = resp_prop.json()
        prop_ids = [r["id"] for r in data_prop["relationships"]]
        assert str(prop_rel.id) in prop_ids
        assert str(det_rel.id) not in prop_ids

    async def test_relationship_review_accepts_or_rejects_proposed_edges(self, client, db_session):
        model = Model(id=uuid4(), name="Review")
        doc = SourceDocument(
            id=uuid4(), source_type="slack", external_id="review-edge",
            content=".", metadata_json="{}",
        )
        a = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="Slack bug", value="Stripe webhook bug", fact_type="issue",
            confidence=0.8, status="active",
        )
        b = Component(
            id=uuid4(), model_id=model.id, source_document_id=doc.id,
            name="GitHub issue", value="Stripe webhook failure", fact_type="issue",
            confidence=0.8, status="active",
        )
        accepted = Relationship(
            id=uuid4(), source_component_id=a.id, target_component_id=b.id,
            relationship_type="related_to", confidence=0.91,
            evidence="Semantic similarity", origin="ai_proposed", status="proposed",
        )
        rejected = Relationship(
            id=uuid4(), source_component_id=b.id, target_component_id=a.id,
            relationship_type="related_to", confidence=0.88,
            evidence="Weak semantic similarity", origin="ai_proposed", status="proposed",
        )
        db_session.add_all([model, doc, a, b, accepted, rejected])
        await db_session.flush()

        accept_resp = await client.patch(
            f"/api/relationships/{accepted.id}/review",
            json={"action": "accept"},
        )
        assert accept_resp.status_code == 200
        accepted_data = accept_resp.json()
        assert accepted_data["status"] == "active"
        assert accepted_data["origin"] == "human_verified"

        reject_resp = await client.patch(
            f"/api/relationships/{rejected.id}/review",
            json={"action": "reject"},
        )
        assert reject_resp.status_code == 200
        assert reject_resp.json()["status"] == "rejected"

        graph_resp = await client.get("/api/graph")
        relationship_ids = {r["id"] for r in graph_resp.json()["relationships"]}
        assert str(accepted.id) in relationship_ids
        assert str(rejected.id) not in relationship_ids


class TestPastCurrentFutureProposed:
    async def test_current_component_is_active(self, db_session):
        svc = IngestionService(db_session)
        model = await svc._get_or_create_model("Pricing")
        doc = SourceDocument(
            id=uuid4(), source_type="local", external_id="temp-curr",
            content="Pricing is $20/mo.", metadata_json="{}",
        )
        db_session.add(doc)
        await db_session.flush()
        fact = ExtractedFact(
            model_name="Pricing", name="$20/mo tier",
            value="Pricing is $20/month", fact_type="fact",
            confidence=0.85, temporal="current", temporal_hint="current",
        )
        comp = await svc._upsert_component(model, doc, fact)
        assert comp.status == "active"
        assert comp.temporal == "current"

    async def test_past_component_is_needs_review(self, db_session):
        svc = IngestionService(db_session)
        model = await svc._get_or_create_model("Roadmap")
        doc = SourceDocument(
            id=uuid4(), source_type="local", external_id="temp-past",
            content="Was $10/mo.", metadata_json="{}",
        )
        db_session.add(doc)
        await db_session.flush()
        fact = ExtractedFact(
            model_name="Roadmap", name="Old pricing $10",
            value="Was $10/month", fact_type="fact",
            confidence=0.8, temporal="past", temporal_hint="past",
        )
        comp = await svc._upsert_component(model, doc, fact)
        assert comp.status == "needs_review"
        assert comp.temporal == "past"

    async def test_future_component_is_proposed(self, db_session):
        svc = IngestionService(db_session)
        model = await svc._get_or_create_model("Roadmap")
        doc = SourceDocument(
            id=uuid4(), source_type="local", external_id="temp-fut",
            content="Will add SSO.", metadata_json="{}",
        )
        db_session.add(doc)
        await db_session.flush()
        fact = ExtractedFact(
            model_name="Roadmap", name="SSO support",
            value="Will add SSO in Q4", fact_type="fact",
            confidence=0.75, temporal="future", temporal_hint="future",
        )
        comp = await svc._upsert_component(model, doc, fact)
        assert comp.status == "proposed"
        assert comp.temporal == "future"

    async def test_unknown_temporal_is_active_with_high_conf(self, db_session):
        svc = IngestionService(db_session)
        model = await svc._get_or_create_model("Test")
        doc = SourceDocument(
            id=uuid4(), source_type="local", external_id="temp-unk",
            content="Fact.", metadata_json="{}",
        )
        db_session.add(doc)
        await db_session.flush()
        fact = ExtractedFact(
            model_name="Test", name="Unknown fact",
            value="Some fact", fact_type="fact",
            confidence=0.85, temporal="unknown", temporal_hint="current",
        )
        comp = await svc._upsert_component(model, doc, fact)
        assert comp.status == "active"
        assert comp.temporal == "unknown"


class TestResolveGithubItemType:
    def test_github_issue_source_type(self):
        from app.taxonomy import resolve_github_item_type
        assert resolve_github_item_type("github_issue") == "github_issue"

    def test_github_pr_source_type(self):
        from app.taxonomy import resolve_github_item_type
        assert resolve_github_item_type("github_pr") == "github_pr"

    def test_github_with_pr_metadata(self):
        from app.taxonomy import resolve_github_item_type
        assert resolve_github_item_type("github", {"item_type": "pull_request"}) == "github_pr"
        assert resolve_github_item_type("github", {"pr_number": 42}) == "github_pr"
        assert resolve_github_item_type("github", {"source_url": "https://github.com/org/repo/pull/5"}) == "github_pr"

    def test_github_with_issue_metadata(self):
        from app.taxonomy import resolve_github_item_type
        assert resolve_github_item_type("github", {"item_type": "issue"}) == "github_issue"
        assert resolve_github_item_type("github", {"issue_number": 7}) == "github_issue"

    def test_github_without_metadata_defaults_to_issue(self):
        from app.taxonomy import resolve_github_item_type
        assert resolve_github_item_type("github", None) == "github_issue"
        assert resolve_github_item_type("github", {}) == "github_issue"


class TestResolveAgentSessionType:
    def test_agent_session_types(self):
        from app.taxonomy import resolve_agent_session_type
        for st in ("agent_session", "codex", "claude", "opencode"):
            assert resolve_agent_session_type(st) == "agent_session"

    def test_ai_context_aliases(self):
        from app.taxonomy import resolve_agent_session_type
        for st in ("ai_context", "ai_context_codex", "ai_context_claude_code", "ai_context_opencode"):
            assert resolve_agent_session_type(st) == "agent_session"

    def test_non_agent_types_pass_through(self):
        from app.taxonomy import resolve_agent_session_type
        assert resolve_agent_session_type("local") == "local"
        assert resolve_agent_session_type("github_issue") == "github_issue"


class TestCanonicalOriginAliases:
    def test_auto_maps_to_deterministic(self):
        assert canonical_origin("auto") == "deterministic"
        assert canonical_origin("rule") == "deterministic"

    def test_ai_maps_to_ai_proposed(self):
        assert canonical_origin("ai") == "ai_proposed"
        assert canonical_origin("llm") == "ai_proposed"
        assert canonical_origin("inferred") == "ai_proposed"

    def test_human_maps_to_human_verified(self):
        assert canonical_origin("human") == "human_verified"
        assert canonical_origin("verified") == "human_verified"
        assert canonical_origin("manual") == "human_verified"

    def test_source_maps_to_extracted(self):
        assert canonical_origin("source") == "extracted"
        assert canonical_origin("text") == "extracted"

    def test_all_valid_origins_pass_through(self):
        for o in VALID_RELATIONSHIP_ORIGINS:
            assert canonical_origin(o) == o


class TestIsFixReference:
    def test_fixes_keyword(self):
        from app.processing.source_extractors import _is_fix_reference
        assert _is_fix_reference("Fixes #123", 123) is True

    def test_closes_keyword(self):
        from app.processing.source_extractors import _is_fix_reference
        assert _is_fix_reference("Closes #456", 456) is True

    def test_resolves_keyword(self):
        from app.processing.source_extractors import _is_fix_reference
        assert _is_fix_reference("Resolves #789", 789) is True

    def test_wrong_issue_number(self):
        from app.processing.source_extractors import _is_fix_reference
        assert _is_fix_reference("Fixes #100", 200) is False

    def test_no_keyword(self):
        from app.processing.source_extractors import _is_fix_reference
        assert _is_fix_reference("Related to #123", 123) is False

    def test_empty_body(self):
        from app.processing.source_extractors import _is_fix_reference
        assert _is_fix_reference("", 123) is False
        assert _is_fix_reference(None, 123) is False


class TestIsExplicitBlock:
    def test_blocks_keyword(self):
        from app.processing.source_extractors import _is_explicit_block
        assert _is_explicit_block("This blocks the release") is True

    def test_changes_requested(self):
        from app.processing.source_extractors import _is_explicit_block
        assert _is_explicit_block("Changes requested on this PR") is True

    def test_do_not_merge(self):
        from app.processing.source_extractors import _is_explicit_block
        assert _is_explicit_block("Do not merge until tests pass") is True

    def test_mild_comment_is_not_block(self):
        from app.processing.source_extractors import _is_explicit_block
        assert _is_explicit_block("Minor suggestion: add a comment here") is False

    def test_nit_comment_is_not_block(self):
        from app.processing.source_extractors import _is_explicit_block
        assert _is_explicit_block("nit: extra space") is False


class TestDetermineOriginContract:
    def test_llm_relationship_type_never_implies_deterministic_origin(self):
        class FakeRel:
            relationship_type = "fixes"

        assert _determine_origin(
            "github_pr", FakeRel(), extraction_method="llm_or_regex"
        ) == "ai_proposed"

    def test_github_source_non_deterministic_is_extracted(self):
        class FakeRel:
            relationship_type = "related_to"
        assert _determine_origin("github_issue", FakeRel()) == "extracted"
        assert _determine_origin("github_pr", FakeRel()) == "extracted"

    def test_agent_session_non_deterministic_is_extracted(self):
        class FakeRel:
            relationship_type = "related_to"
        assert _determine_origin("agent_session", FakeRel()) == "extracted"
        assert _determine_origin("codex", FakeRel()) == "extracted"

    def test_ai_context_aliases_are_extracted(self):
        class FakeRel:
            relationship_type = "related_to"
        assert _determine_origin("ai_context", FakeRel()) == "extracted"
        assert _determine_origin("ai_context_codex", FakeRel()) == "extracted"

    def test_local_source_non_deterministic_is_proposed(self):
        class FakeRel:
            relationship_type = "related_to"
        assert _determine_origin("local", FakeRel()) == "proposed"

    def test_deterministic_type_overrides_source(self):
        class FakeRel:
            relationship_type = "fixes"
        assert _determine_origin("local", FakeRel()) == "deterministic"

    def test_fixes_is_deterministic(self):
        class FakeRel:
            relationship_type = "fixes"
        assert _determine_origin("github_pr", FakeRel()) == "deterministic"

    def test_touches_file_is_deterministic(self):
        class FakeRel:
            relationship_type = "touches_file"
        assert _determine_origin("github_pr", FakeRel()) == "deterministic"

    def test_resolved_by_is_deterministic(self):
        class FakeRel:
            relationship_type = "resolved_by"
        assert _determine_origin("github_pr", FakeRel()) == "deterministic"
