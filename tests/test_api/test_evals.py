from __future__ import annotations

from datetime import UTC, datetime

from app.evals.harness import EvalCase
from app.models import (
    Component,
    ComponentSource,
    Connector,
    ConnectorStatus,
    ConnectorType,
    KnowledgeModel,
    SourceDocument,
)
from app.processing.embedder import HashingEmbedder


_EMBEDDER = HashingEmbedder()


async def _seed_component(
    db_session,
    *,
    model_id,
    name: str,
    value: str,
    authority_weight: float = 0.9,
) -> Component:
    component = Component(
        model_id=model_id,
        name=name,
        value=value,
        confidence=0.95,
        authority_source="seeded-eval",
        authority_weight=authority_weight,
        last_verified_at=datetime.now(UTC),
        embedding=await _EMBEDDER.embed_text(f"{name}\n{value}"),
    )
    db_session.add(component)
    await db_session.flush()
    return component


async def _seed_eval_dataset(db_session, workspace):
    notion = Connector(
        workspace_id=workspace.id,
        connector_type=ConnectorType.NOTION,
        status=ConnectorStatus.CONNECTED,
        config={},
    )
    slack = Connector(
        workspace_id=workspace.id,
        connector_type=ConnectorType.SLACK,
        status=ConnectorStatus.CONNECTED,
        config={},
    )
    zoom = Connector(
        workspace_id=workspace.id,
        connector_type=ConnectorType.ZOOM,
        status=ConnectorStatus.CONNECTED,
        config={},
    )
    db_session.add_all([notion, slack, zoom])
    await db_session.flush()

    pricing = KnowledgeModel(
        workspace_id=workspace.id,
        name="Pricing",
        description="Pricing facts",
    )
    roadmap = KnowledgeModel(
        workspace_id=workspace.id,
        name="Roadmap",
        description="Roadmap facts",
    )
    db_session.add_all([pricing, roadmap])
    await db_session.flush()

    enterprise = await _seed_component(
        db_session,
        model_id=pricing.id,
        name="Enterprise Plan",
        value="Enterprise pricing is $600/seat with annual terms.",
    )
    blocker = await _seed_component(
        db_session,
        model_id=roadmap.id,
        name="SSO Blocker",
        value="SSO is blocked by engineering bandwidth.",
    )

    notion_doc = SourceDocument(
        connector_id=notion.id,
        connector_type=ConnectorType.NOTION,
        external_id="notion-enterprise-plan",
        content="Enterprise pricing is $600/seat.",
        author="seed",
        source_url="https://example.com/notion-enterprise-plan",
        created_at_source=datetime.now(UTC),
        metadata_json={"page_title": "Pricing Handbook"},
        processed_at=datetime.now(UTC),
    )
    zoom_doc = SourceDocument(
        connector_id=zoom.id,
        connector_type=ConnectorType.ZOOM,
        external_id="zoom-sso-blocker",
        content="Meeting blocker: engineering bandwidth is the blocker for SSO.",
        author="seed",
        source_url="https://example.com/zoom-sso-blocker",
        created_at_source=datetime.now(UTC),
        metadata_json={"meeting_topic": "Weekly Product Review"},
        processed_at=datetime.now(UTC),
    )
    db_session.add_all([notion_doc, zoom_doc])
    await db_session.flush()

    db_session.add_all(
        [
            ComponentSource(
                component_id=enterprise.id,
                source_document_id=notion_doc.id,
                extraction_context="Seeded eval pricing context",
                extractor_name="structured_llm",
                extractor_kind="llm_structured",
                extractor_schema_version="fact_extraction.v1",
            ),
            ComponentSource(
                component_id=blocker.id,
                source_document_id=zoom_doc.id,
                extraction_context="Seeded eval blocker context",
                extractor_name="structured_llm",
                extractor_kind="llm_structured",
                extractor_schema_version="fact_extraction.v1",
            ),
        ]
    )
    await db_session.flush()


class TestEvalApis:
    async def test_eval_summary_returns_empty_state_before_any_run(
        self, client, workspace
    ):
        resp = await client.get(
            "/api/evals/summary",
            params={"workspace_id": str(workspace.id)},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["latest_run_timestamp"] is None
        assert body["total"] == 0
        assert body["pass_rate"] == 0.0
        assert body["pass_threshold"] == 0.5
        assert body["confidence_calibration_error"] == 0.0
        assert body["average_citation_accuracy"] == 0.0
        assert body["average_stale_context_detection"] == 0.0
        assert body["average_naive_answer_correctness"] == 0.0
        assert body["average_context_answer_lift"] == 0.0
        assert body["blockers"] == []
        assert body["domain_summaries"] == []

    async def test_run_evals_persists_summary_and_cases(
        self, client, workspace, db_session, monkeypatch
    ):
        await _seed_eval_dataset(db_session, workspace)
        monkeypatch.setattr(
            "app.services.eval_service.load_default_cases",
            lambda domains=None, ids=None: [
                EvalCase(
                    question="What is our enterprise pricing?",
                    expected_answer_substrings=("$600/seat",),
                    expected_component_names=("Enterprise Plan",),
                    expected_source_types=("notion",),
                    case_id="pricing-001",
                    domain="pricing",
                ),
                EvalCase(
                    question="Why is SSO blocked?",
                    expected_answer_substrings=("engineering bandwidth",),
                    expected_component_names=("SSO Blocker",),
                    expected_source_types=("zoom",),
                    case_id="blocker-001",
                    domain="blocker",
                ),
            ],
        )

        resp = await client.post(
            "/api/evals/run",
            json={"workspace_id": str(workspace.id)},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["latest_run_timestamp"] is not None
        assert body["total"] == 2
        assert body["passed_count"] == 2
        assert body["failed_count"] == 0
        assert body["pass_rate"] == 1.0
        assert body["pass_threshold"] == 0.5
        assert body["confidence_calibration_error"] >= 0.0
        assert body["average_citation_accuracy"] == 1.0
        assert body["average_stale_context_detection"] == 1.0
        assert body["average_context_answer_lift"] >= 0.0
        assert body["blockers"] == []
        assert len(body["domain_summaries"]) == 2
        assert len(body["cases"]) == 2
        assert body["cases"][0]["predicted_confidence"] >= 0.0
        assert body["cases"][0]["citation_accuracy"] == 1.0
        assert body["cases"][0]["stale_context_detection"] == 1.0
        assert body["cases"][0]["context_answer_lift"] >= 0.0

        summary = await client.get(
            "/api/evals/summary",
            params={"workspace_id": str(workspace.id)},
        )
        assert summary.status_code == 200
        assert summary.json()["pass_rate"] == 1.0

    async def test_eval_cases_filters_domain(
        self, client, workspace, db_session, monkeypatch
    ):
        await _seed_eval_dataset(db_session, workspace)
        monkeypatch.setattr(
            "app.services.eval_service.load_default_cases",
            lambda domains=None, ids=None: [
                EvalCase(
                    question="What is our enterprise pricing?",
                    expected_answer_substrings=("$600/seat",),
                    expected_component_names=("Enterprise Plan",),
                    expected_source_types=("notion",),
                    case_id="pricing-001",
                    domain="pricing",
                ),
                EvalCase(
                    question="What blockers are active?",
                    expected_answer_substrings=("engineering bandwidth",),
                    expected_component_names=("SSO Blocker",),
                    expected_source_types=("zoom",),
                    case_id="blocker-001",
                    domain="blocker",
                ),
            ],
        )

        run_resp = await client.post(
            "/api/evals/run",
            json={"workspace_id": str(workspace.id)},
        )
        assert run_resp.status_code == 200

        cases_resp = await client.get(
            "/api/evals/cases",
            params={"workspace_id": str(workspace.id), "domain": "pricing"},
        )
        assert cases_resp.status_code == 200
        body = cases_resp.json()
        assert body["selected_domain"] == "pricing"
        assert len(body["cases"]) == 1
        assert body["cases"][0]["domain"] == "pricing"

    async def test_eval_summary_exposes_blockers_for_failed_cases(
        self, client, workspace, db_session, monkeypatch
    ):
        await _seed_eval_dataset(db_session, workspace)
        monkeypatch.setattr(
            "app.services.eval_service.load_default_cases",
            lambda domains=None, ids=None: [
                EvalCase(
                    question="What is our enterprise pricing?",
                    expected_answer_substrings=("$999/seat",),
                    expected_component_names=("Enterprise Plan",),
                    expected_source_types=("notion",),
                    case_id="pricing-fail-001",
                    domain="pricing",
                ),
            ],
        )

        run_resp = await client.post(
            "/api/evals/run",
            json={"workspace_id": str(workspace.id), "pass_threshold": 0.7},
        )
        assert run_resp.status_code == 200
        body = run_resp.json()
        assert body["pass_threshold"] == 0.7
        assert body["failed_count"] == 1
        assert len(body["blockers"]) == 1
        assert body["blockers"][0]["case_id"] == "pricing-fail-001"
        assert "answer missing" in body["blockers"][0]["detail"]

    async def test_run_evals_requires_admin_when_request_is_not_local(
        self, client, workspace, db_session, monkeypatch
    ):
        await _seed_eval_dataset(db_session, workspace)
        monkeypatch.setattr("app.api.evals.settings.environment", "production")
        monkeypatch.setattr("app.api.evals.settings.eval_allow_local_requests", True)
        monkeypatch.setattr("app.api.evals.settings.eval_admin_token", "secret-token")
        monkeypatch.setattr(
            "app.services.eval_service.load_default_cases",
            lambda domains=None, ids=None: [
                EvalCase(
                    question="What is our enterprise pricing?",
                    expected_answer_substrings=("$600/seat",),
                    expected_component_names=("Enterprise Plan",),
                    expected_source_types=("notion",),
                    case_id="pricing-001",
                    domain="pricing",
                ),
            ],
        )

        denied = await client.post(
            "/api/evals/run",
            headers={"X-Forwarded-For": "203.0.113.10"},
            json={"workspace_id": str(workspace.id)},
        )
        assert denied.status_code == 403

        allowed = await client.post(
            "/api/evals/run",
            headers={
                "X-Forwarded-For": "203.0.113.10",
                "X-Eval-Admin-Token": "secret-token",
            },
            json={"workspace_id": str(workspace.id)},
        )
        assert allowed.status_code == 200
