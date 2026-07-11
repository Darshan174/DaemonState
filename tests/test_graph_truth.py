from __future__ import annotations

import json
from datetime import timedelta
from uuid import UUID, uuid4

import httpx
from sqlalchemy import select

from app.models import AgentRun, Component, Connector, ContextPack, EvidenceSpan, Model, SourceDocument, Workspace
from app.services.source_revisions import ingest_source_document_revision
from app.processing.source_extractors import extract_github_issue
from app.sync.ai_session import _parse_session_content
from app.sync import github
from app.time import utc_now


async def _workspace(db_session, name: str = "Graph truth") -> Workspace:
    workspace = Workspace(id=uuid4(), name=name, slug=f"graph-truth-{uuid4().hex}")
    db_session.add(workspace)
    await db_session.flush()
    return workspace


async def test_graph_build_modes_are_honest_and_rebuild_is_idempotent(client, db_session):
    workspace = await _workspace(db_session)
    document = SourceDocument(
        workspace_id=workspace.id,
        source_type="local",
        external_id="graph-build-mode",
        content="Decision: Keep graph updates source backed.",
        metadata_json=json.dumps({"workspace_id": str(workspace.id)}),
    )
    db_session.add(document)
    await db_session.flush()

    incremental = await client.post("/api/graph/build", json={
        "workspace_id": str(workspace.id),
        "mode": "incremental",
    })
    assert incremental.status_code == 200
    first = incremental.json()
    assert first["remote_sources_refreshed"] is False
    assert first["source_refresh"] is False
    assert first["documents"]["processed"] == 1
    assert first["documents"]["reprocessed"] == 0

    no_op = await client.post("/api/graph/build", json={
        "workspace_id": str(workspace.id),
        "mode": "incremental",
    })
    assert no_op.json()["documents"]["processed"] == 0

    rebuild = await client.post("/api/graph/build", json={
        "workspace_id": str(workspace.id),
        "mode": "rebuild",
    })
    rebuilt = rebuild.json()
    assert rebuilt["documents"]["processed"] == 1
    assert rebuilt["documents"]["reprocessed"] == 1
    assert rebuilt["components"]["created"] == 0
    assert rebuilt["components"]["reused"] >= 1


async def test_new_source_revision_supersedes_old_projection(client, db_session):
    workspace = await _workspace(db_session, "Revision projection")
    first = await ingest_source_document_revision(
        db_session,
        workspace_id=workspace.id,
        source_type="local",
        external_id="architecture-decision",
        content="Decision: Use SQLite for the project database.",
        metadata_json={"workspace_id": str(workspace.id)},
    )
    await client.post("/api/graph/build", json={"workspace_id": str(workspace.id)})
    old_components = list(await db_session.scalars(
        select(Component).where(Component.source_document_id == first.document.id)
    ))
    assert old_components

    second = await ingest_source_document_revision(
        db_session,
        workspace_id=workspace.id,
        source_type="local",
        external_id="architecture-decision",
        content="Decision: Use PostgreSQL for the project database.",
        metadata_json={"workspace_id": str(workspace.id)},
    )
    response = await client.post("/api/graph/build", json={"workspace_id": str(workspace.id)})
    assert response.json()["documents"]["historical_skipped"] == 1
    assert response.json()["components"]["superseded"] >= 1

    for component in old_components:
        await db_session.refresh(component)
        assert component.status == "superseded"
        assert component.valid_to is not None
        if component.fact_type == "decision":
            assert component.superseded_by_id is not None

    digest = (await client.get(
        "/api/context/digest", params={"workspace_id": str(workspace.id)}
    )).json()
    assert all(
        card["source_snapshot"]["source_document_id"] != str(first.document.id)
        for card in digest["cards"]
    )
    assert any(
        card["source_snapshot"]["source_document_id"] == str(second.document.id)
        for card in digest["cards"]
    )


async def test_github_sync_filters_prs_from_issues_and_persists_temporal_metadata(
    db_session, monkeypatch
):
    workspace = await _workspace(db_session, "GitHub truth")
    connector = Connector(
        workspace_id=workspace.id,
        connector_type="github",
        status="connected",
        credentials_json=json.dumps({"access_token": "token"}),
        config_json=json.dumps({"repositories": ["acme/project"]}),
    )
    db_session.add(connector)
    await db_session.flush()

    pr = {
        "number": 12,
        "title": "Fix graph truth",
        "body": "Closes #7",
        "state": "closed",
        "draft": False,
        "merged_at": "2026-07-10T10:30:00Z",
        "closed_at": "2026-07-10T10:30:00Z",
        "created_at": "2026-07-09T10:00:00Z",
        "updated_at": "2026-07-10T10:30:00Z",
        "labels": [],
        "assignees": [],
        "user": {"login": "octocat"},
        "html_url": "https://github.com/acme/project/pull/12",
        "pull_request": {"url": "provider-marker"},
    }

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url, **kwargs):
            request = httpx.Request("GET", url)
            return httpx.Response(200, request=request, json=[pr])

    monkeypatch.setattr(github.httpx, "AsyncClient", FakeClient)
    result = await github.sync_github(connector, db_session)
    assert result["documents_persisted"] == 1

    documents = list(await db_session.scalars(
        select(SourceDocument).where(SourceDocument.workspace_id == workspace.id)
    ))
    assert [document.external_id for document in documents] == [
        "github:acme/project:pull_request:12"
    ]
    metadata = json.loads(documents[0].metadata_json)
    assert metadata["item_type"] == "pull_request"
    assert metadata["updated_at"] == "2026-07-10T10:30:00Z"
    assert metadata["closed_at"] == "2026-07-10T10:30:00Z"
    assert metadata["merged_at"] == "2026-07-10T10:30:00Z"
    assert metadata["draft"] is False


async def test_digest_categories_require_typed_metadata_and_verified_evidence(client, db_session):
    workspace = await _workspace(db_session, "Typed digest")
    connector = Connector(
        workspace_id=workspace.id,
        connector_type="github",
        status="connected",
        credentials_json="{}",
        config_json=json.dumps({"repositories": ["acme/project"]}),
        last_sync_at=utc_now() - timedelta(hours=1),
    )
    typed_pr = SourceDocument(
        workspace_id=workspace.id,
        source_type="github",
        external_id="github:acme/project:pull_request:18",
        source_url="https://github.com/acme/project/pull/18",
        content="[Pull Request] #18: Accurate state\n\nState: merged",
        metadata_json=json.dumps({
            "workspace_id": str(workspace.id),
            "item_type": "pull_request",
            "repo_full_name": "acme/project",
            "number": 18,
            "title": "Accurate state",
            "state": "closed",
            "merged": True,
            "updated_at": "2026-07-10T10:30:00Z",
        }),
    )
    untyped_pr = SourceDocument(
        workspace_id=workspace.id,
        source_type="local",
        external_id="looks-like-pr",
        source_url="https://github.com/acme/project/pull/99",
        content="PR #99 is active",
        metadata_json=json.dumps({"workspace_id": str(workspace.id)}),
    )
    session_doc = SourceDocument(
        workspace_id=workspace.id,
        source_type="agent_session",
        external_id="codex:session:truth",
        content="# Graph truth session\nDecision: Keep exact evidence ranges.",
        metadata_json=json.dumps({
            "workspace_id": str(workspace.id),
            "session_id": "truth-session",
            "tool": "codex",
            "repository": "acme/project",
            "started_at": "2026-07-10T09:00:00Z",
        }),
    )
    decision_doc = SourceDocument(
        workspace_id=workspace.id,
        source_type="local",
        external_id="human-authored-decision",
        content="Decision: Keep source-backed graph categories.",
        metadata_json=json.dumps({"workspace_id": str(workspace.id)}),
    )
    db_session.add_all([connector, typed_pr, untyped_pr, session_doc, decision_doc])
    await db_session.flush()
    await client.post("/api/graph/build", json={"workspace_id": str(workspace.id)})

    response = await client.get(
        "/api/context/digest", params={"workspace_id": str(workspace.id)}
    )
    assert response.status_code == 200
    digest = response.json()
    assert digest["objective"]["status"] == "not_supplied"

    pr_card = next(card for card in digest["cards"] if card["category"] == "pull_request")
    assert pr_card["remote_item"]["provider_state"] == "merged"
    assert pr_card["source_snapshot"]["freshness"] == "unknown"
    assert pr_card["source_snapshot"]["last_successful_sync_at"] is None

    session_card = next(card for card in digest["cards"] if card["category"] == "agent_session")
    assert session_card["session"]["session_id"] == "truth-session"
    assert session_card["workspace_relevance"]["status"] == "relevant"
    assert session_card["session"]["inspection_source_id"] == str(session_doc.id)

    decisions = [card for card in digest["cards"] if card["category"] == "decision"]
    assert decisions
    assert decisions[0]["evidence"]["verification_status"] == "verified"
    evidence_id = decisions[0]["evidence"]["evidence_span_id"]
    assert await db_session.get(EvidenceSpan, UUID(evidence_id)) is not None

    session_child_cards = [
        card for card in digest["cards"]
        if card["source_snapshot"]["source_document_id"] == str(session_doc.id)
        and card["category"] != "agent_session"
    ]
    assert session_child_cards
    assert all(card["category"] == "supporting_evidence" for card in session_child_cards)

    lookalike_cards = [
        card for card in digest["cards"]
        if card["source_snapshot"]["source_document_id"] == str(untyped_pr.id)
    ]
    assert all(card["category"] == "supporting_evidence" for card in lookalike_cards)


async def test_unknown_workspace_is_not_an_empty_success_and_models_are_scoped(client, db_session):
    unknown = str(uuid4())
    assert (await client.get("/api/graph", params={"workspace_id": unknown})).status_code == 404
    assert (await client.get("/api/context/digest", params={"workspace_id": unknown})).status_code == 404
    assert (await client.post("/api/graph/build", json={"workspace_id": unknown})).status_code == 404

    workspace = await _workspace(db_session, "Model scope")
    represented = Model(name=f"Represented {uuid4().hex}")
    unrelated = Model(name=f"Unrelated {uuid4().hex}")
    document = SourceDocument(
        workspace_id=workspace.id,
        source_type="local",
        external_id="model-scope",
        content="A scoped fact.",
        metadata_json=json.dumps({"workspace_id": str(workspace.id)}),
    )
    component = Component(
        model=represented,
        source_document=document,
        name="Scoped fact",
        value="A scoped fact.",
        fact_type="fact",
        confidence=0.8,
        status="active",
    )
    db_session.add_all([represented, unrelated, document, component])
    await db_session.flush()
    graph = (await client.get(
        "/api/graph", params={"workspace_id": str(workspace.id)}
    )).json()
    assert [model["id"] for model in graph["models"]] == [str(represented.id)]


async def test_digest_objective_comes_from_persisted_execution_context(client, db_session):
    workspace = await _workspace(db_session, "Objective truth")
    db_session.add(AgentRun(
        workspace_id=workspace.id,
        objective="Historical completed run objective",
        status="completed",
        started_at=utc_now() - timedelta(days=2),
        ended_at=utc_now() - timedelta(days=1),
    ))
    db_session.add(ContextPack(
        workspace_id=workspace.id,
        objective="Ship the source-backed graph inspector",
        markdown="",
        manifest="{}",
        repo_state_json="{}",
    ))
    await db_session.flush()

    digest = (await client.get(
        "/api/context/digest", params={"workspace_id": str(workspace.id)}
    )).json()
    assert digest["objective"]["status"] == "supplied"
    assert digest["objective"]["text"] == "Ship the source-backed graph inspector"
    assert digest["objective"]["source_kind"] == "context_pack"
    assert digest["objective"]["source_id"] is not None
    assert digest["objective"]["recorded_at"] is not None


async def test_closed_issue_children_are_historical_not_current_blockers():
    facts = extract_github_issue(
        "[Issue] #9: Historical outage\n\nState: closed\n\nBlocker: deployment access was unavailable.",
        {
            "item_type": "issue",
            "repo_full_name": "acme/project",
            "number": 9,
            "title": "Historical outage",
            "state": "closed",
            "closed_at": "2026-07-01T10:00:00Z",
        },
    )
    blockers = [fact for fact in facts if fact.fact_type == "blocker"]
    assert blockers
    assert all(fact.temporal == "past" for fact in blockers)


async def test_bracketed_session_transcripts_keep_real_message_counts():
    messages = _parse_session_content(
        "[USER]\nMake the graph factual.\n\n[ASSISTANT]\nI will inspect it.\n\n[USER]\nShow the source."
    )
    assert [message["role"] for message in messages] == ["user", "assistant", "user"]
    assert len(messages) == 3
