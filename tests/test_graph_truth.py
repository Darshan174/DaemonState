from __future__ import annotations

import json
from datetime import timedelta
from uuid import UUID, uuid4

import httpx
from sqlalchemy import select

from app.api.context_digest import (
    _clean_digest_text,
    _display_title,
    _excerpt,
    _is_digest_noise_component,
    _summary,
)
from app.models import (
    AgentRun,
    CodeFile,
    Component,
    Connector,
    ContextPack,
    EvidenceSpan,
    Model,
    Relationship,
    SourceDocument,
    Workspace,
)
from app.services.source_revisions import ingest_source_document_revision
from app.services.context_compiler import ContextCompiler
from app.processing.source_extractors import extract_github_issue
from app.sync.ai_session import _parse_session_content
from app.sync import github
from app.time import utc_now


async def _workspace(db_session, name: str = "Graph truth") -> Workspace:
    workspace = Workspace(id=uuid4(), name=name, slug=f"graph-truth-{uuid4().hex}")
    db_session.add(workspace)
    await db_session.flush()
    return workspace


def test_digest_rejects_punctuation_led_typed_fragments_and_cleans_legacy_display():
    component = Component(
        name="Task: , provenance, review queue, evals, and temporal support",
        value=", provenance, review queue, evals, and temporal support",
        excerpt=", provenance, review queue, evals, and temporal support",
        fact_type="task",
        confidence=0.78,
        status="active",
    )

    assert _is_digest_noise_component(component) is True
    assert _clean_digest_text(component.value) == "provenance, review queue, evals, and temporal support"
    assert _display_title(component, "task") == "Task: provenance, review queue, evals, and temporal support"
    assert _summary(component) == "provenance, review queue, evals, and temporal support"
    assert _excerpt(component) == "provenance, review queue, evals, and temporal support"


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
    assert first["reconciliation"] == {
        "projection_consistent": True,
        "current_source_revisions": 1,
        "historical_source_revisions": 0,
        "pending_current_revisions": 0,
        "historical_active_projections": 0,
        "dangling_relationships": 0,
        "upstream_refreshed": False,
    }

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


async def test_digest_links_preserve_stored_origin_and_evidence(client, db_session):
    workspace = await _workspace(db_session, "Digest edge truth")
    model = Model(id=uuid4(), name="Digest edge model")
    document = SourceDocument(
        id=uuid4(), workspace_id=workspace.id, source_type="local",
        external_id="digest-edge", content="Task A depends on Decision B.",
        metadata_json=json.dumps({"workspace_id": str(workspace.id)}),
    )
    task = Component(
        id=uuid4(), workspace_id=workspace.id, model_id=model.id,
        source_document_id=document.id, name="Task A", value="Implement Task A",
        fact_type="task", confidence=0.9, status="active",
    )
    decision = Component(
        id=uuid4(), workspace_id=workspace.id, model_id=model.id,
        source_document_id=document.id, name="Decision B", value="Use Decision B",
        fact_type="decision", confidence=0.9, status="active",
    )
    relationship = Relationship(
        id=uuid4(), source_component_id=task.id, target_component_id=decision.id,
        relationship_type="depends_on", confidence=0.97,
        evidence="Task A depends on Decision B.", status="active", origin="extracted",
    )
    db_session.add_all([workspace, model, document, task, decision, relationship])
    await db_session.flush()

    response = await client.get(
        "/api/context/digest", params={"workspace_id": str(workspace.id)}
    )
    assert response.status_code == 200
    link = next(
        item for item in response.json()["links"]
        if item["relationship_id"] == str(relationship.id)
    )
    assert link["origin"] == "extracted"
    assert link["evidence"] == "Task A depends on Decision B."
    assert link["source_component_document_id"] == str(document.id)


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
    assert response.json()["reconciliation"]["projection_consistent"] is True
    assert response.json()["reconciliation"]["historical_active_projections"] == 0

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
        content=(
            "Decision: Keep source-backed graph categories.\n"
            "Task: Verify the next-step category from exact evidence."
        ),
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

    task_cards = [card for card in digest["cards"] if card["category"] == "task"]
    assert task_cards
    assert task_cards[0]["evidence"]["verification_status"] == "verified"

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


async def test_digest_session_relevance_uses_repo_path_and_commit_for_entire_source(
    client, db_session, tmp_path
):
    workspace = await _workspace(db_session, "Session relevance")
    commit = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"
    connector = Connector(
        workspace_id=workspace.id,
        connector_type="github",
        status="connected",
        config_json=json.dumps({
            "repositories": ["git@github.com:Acme/Project.git"],
        }),
    )
    code_file = CodeFile(
        workspace_id=workspace.id,
        repo_root=str(tmp_path.resolve()),
        path="app/main.py",
        language="python",
        sha256="1" * 64,
        last_commit=commit,
        size=10,
    )
    model = Model(name=f"Session relevance {uuid4().hex}")

    def session_doc(name: str, metadata: dict) -> SourceDocument:
        return SourceDocument(
            workspace_id=workspace.id,
            source_type="agent_session",
            external_id=f"codex:session:{name}",
            content=f"[USER]\nWork on {name}.\n\n[ASSISTANT]\nSession evidence for {name}.",
            metadata_json=json.dumps({
                "workspace_id": str(workspace.id),
                "session_id": name,
                "tool": "codex",
                **metadata,
            }),
        )

    repo_match = session_doc(
        "repo-match", {"repository": "https://github.com/acme/project.git"}
    )
    cwd_match = session_doc(
        "cwd-match", {"cwd": str(tmp_path / "app" / "services")}
    )
    cwd_mismatch = session_doc(
        "cwd-mismatch", {"cwd": str(tmp_path.parent / "different-project")}
    )
    cwd_ancestor = session_doc(
        "cwd-ancestor", {"cwd": str(tmp_path.parent)}
    )
    commit_match = session_doc("commit-match", {"commit": commit[:12]})
    outside_commit_match = session_doc(
        "outside-commit-match",
        {
            "cwd": str(tmp_path.parent / "external-worktree"),
            "commit": commit[:12],
        },
    )
    repo_mismatch = session_doc("repo-mismatch", {"repository": "other/project"})
    unknown = session_doc("unknown", {})
    db_session.add_all([
        connector,
        code_file,
        model,
        repo_match,
        cwd_match,
        cwd_mismatch,
        cwd_ancestor,
        commit_match,
        outside_commit_match,
        repo_mismatch,
        unknown,
    ])
    await db_session.flush()

    roots: dict[str, Component] = {}
    for doc in (
        repo_match,
        cwd_match,
        cwd_mismatch,
        cwd_ancestor,
        commit_match,
        outside_commit_match,
        repo_mismatch,
        unknown,
    ):
        roots[doc.external_id] = Component(
            workspace_id=workspace.id,
            model_id=model.id,
            source_document_id=doc.id,
            name=f"Session: {doc.external_id}",
            value=(
                "Developer instructions are preserved as source evidence."
                if doc is unknown
                else f"Root for {doc.external_id}"
            ),
            fact_type="session_root",
            temporal="current",
            confidence=0.93,
            status="active",
            provenance=json.dumps({
                "source_type": "agent_session",
                "external_id": doc.external_id,
            }),
        )
    mismatch_child = Component(
        workspace_id=workspace.id,
        model_id=model.id,
        source_document_id=repo_mismatch.id,
        name="Blocker: unrelated deployment",
        value="Unrelated deployment is blocked.",
        fact_type="blocker",
        temporal="current",
        confidence=0.9,
        status="active",
    )
    relevant_child = Component(
        workspace_id=workspace.id,
        model_id=model.id,
        source_document_id=repo_match.id,
        name="Task: preserve repository provenance",
        value="Preserve repository provenance in the digest.",
        fact_type="task",
        temporal="current",
        confidence=0.9,
        status="active",
    )
    unknown_child = Component(
        workspace_id=workspace.id,
        model_id=model.id,
        source_document_id=unknown.id,
        name="Risk: unscoped regression",
        value="An unscoped regression may exist.",
        fact_type="risk",
        temporal="current",
        confidence=0.9,
        status="active",
    )
    db_session.add_all([*roots.values(), relevant_child, mismatch_child, unknown_child])
    await db_session.flush()
    hidden_relationship = Relationship(
        source_component_id=mismatch_child.id,
        target_component_id=unknown_child.id,
        relationship_type="blocks",
        confidence=0.9,
        evidence="Explicit but out-of-project session evidence.",
        status="active",
        origin="deterministic",
    )
    db_session.add(hidden_relationship)
    await db_session.flush()

    response = await client.get(
        "/api/context/digest", params={"workspace_id": str(workspace.id)}
    )
    assert response.status_code == 200
    digest = response.json()
    root_cards_by_source = {
        card["source_snapshot"]["external_id"]: card
        for card in digest["cards"]
        if card["category"] == "agent_session"
    }

    assert root_cards_by_source[repo_match.external_id]["workspace_relevance"]["status"] == "relevant"
    assert root_cards_by_source[cwd_match.external_id]["workspace_relevance"]["status"] == "relevant"
    assert root_cards_by_source[cwd_mismatch.external_id]["workspace_relevance"]["status"] == "not_relevant"
    assert root_cards_by_source[cwd_ancestor.external_id]["workspace_relevance"]["status"] == "unknown"
    assert root_cards_by_source[commit_match.external_id]["workspace_relevance"]["status"] == "relevant"
    assert root_cards_by_source[outside_commit_match.external_id]["workspace_relevance"]["status"] == "relevant"
    assert root_cards_by_source[repo_mismatch.external_id]["workspace_relevance"]["status"] == "not_relevant"
    assert root_cards_by_source[unknown.external_id]["workspace_relevance"]["status"] == "unknown"

    visible_component_ids = {card["id"] for card in digest["cards"]}
    relevant_child_card = next(
        card for card in digest["cards"]
        if card["id"] == f"component:{relevant_child.id}"
    )
    assert relevant_child_card["workspace_relevance"]["status"] == "relevant"
    assert f"component:{mismatch_child.id}" not in visible_component_ids
    assert f"component:{unknown_child.id}" not in visible_component_ids
    assert all(link["relationship_id"] != str(hidden_relationship.id) for link in digest["links"])
    assert digest["health"]["blocker_count"] == 0
    assert all(
        f"component:{mismatch_child.id}" not in action["card_ids"]
        and f"component:{unknown_child.id}" not in action["card_ids"]
        for action in digest["recommended_actions"]
    )
    clustered_ids = {
        card_id
        for cluster in digest["clusters"]
        for card_id in cluster["card_ids"]
    }
    assert f"component:{roots[repo_mismatch.external_id].id}" not in clustered_ids
    assert f"component:{roots[unknown.external_id].id}" not in clustered_ids
    assert str(tmp_path.resolve()) in digest["scope"]["project_paths"]
    assert "acme/project" in digest["scope"]["project_repositories"]
    assert digest["scope"]["candidate_session_count"] == 8

    handoff = await ContextCompiler(db_session).compile_context_pack(
        "Continue the source-backed project work.",
        workspace_id=workspace.id,
        repo_path=str(tmp_path),
        token_budget=3500,
        persist=False,
    )
    handoff_source_ids = {
        item.get("source_document_id")
        for item in [*handoff.selected_items, *handoff.excluded_items]
    }
    assert str(repo_match.id) in handoff_source_ids
    assert str(repo_mismatch.id) not in handoff_source_ids
    assert str(unknown.id) not in handoff_source_ids

    limited_response = await client.get(
        "/api/context/digest",
        params={"workspace_id": str(workspace.id), "limit": 8},
    )
    assert limited_response.status_code == 200
    limited = limited_response.json()
    assert limited["scope"]["candidate_session_count"] == 8
    assert len(limited["cards"]) == 8
    assert all(card["category"] == "agent_session" for card in limited["cards"])
    assert {
        card["source_snapshot"]["external_id"] for card in limited["cards"]
    } == set(roots)


async def test_non_github_connector_config_cannot_define_project_identity(
    client, db_session
):
    workspace = await _workspace(db_session, "Connector scope isolation")
    connector = Connector(
        workspace_id=workspace.id,
        connector_type="slack",
        status="connected",
        config_json=json.dumps({
            "repositories": ["acme/unrelated"],
            "repo_path": "/tmp/unrelated",
        }),
    )
    document = SourceDocument(
        workspace_id=workspace.id,
        source_type="agent_session",
        external_id="codex:session:connector-only",
        content="[USER]\nInspect the project.\n\n[ASSISTANT]\nI inspected it.",
        metadata_json=json.dumps({
            "workspace_id": str(workspace.id),
            "repository": "acme/unrelated",
            "cwd": "/tmp/unrelated",
        }),
    )
    model = Model(name=f"Connector isolation {uuid4().hex}")
    db_session.add_all([connector, document, model])
    await db_session.flush()
    root = Component(
        workspace_id=workspace.id,
        model_id=model.id,
        source_document_id=document.id,
        name="Session: connector-only",
        value="Imported session root.",
        fact_type="session_root",
        temporal="current",
        confidence=0.9,
        status="active",
    )
    db_session.add(root)
    await db_session.flush()

    response = await client.get(
        "/api/context/digest", params={"workspace_id": str(workspace.id)}
    )

    assert response.status_code == 200
    digest = response.json()
    assert digest["scope"]["project_paths"] == []
    assert digest["scope"]["project_repositories"] == []
    session_card = next(
        card for card in digest["cards"] if card["category"] == "agent_session"
    )
    assert session_card["workspace_relevance"]["status"] == "unknown"
