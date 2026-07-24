from __future__ import annotations

import json
import hashlib
from datetime import timedelta
from uuid import UUID, uuid4

import httpx
from sqlalchemy import select

from app.api.context_digest import (
    _agent_reported_summary,
    _clean_digest_text,
    _display_title,
    _excerpt,
    _is_digest_noise_component,
    _reported_summary_text,
    _summary,
)
from app.models import (
    AgentRun,
    Claim,
    ClaimRevision,
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
from app.services.session_events import NormalizedSessionEvent, persist_session_events
from app.processing.source_extractors import extract_github_issue
from app.sync.ai_session import _parse_session_content
from app.sync import github
from app.time import utc_now


def test_agent_reported_summary_prefers_completion_over_newer_progress_update():
    summary = _agent_reported_summary([
        "Implemented the session result compiler and verified the focused tests.",
        "I’m implementing this as a product-wide result compiler; verified evidence will stay separate.",
    ])

    assert summary == {
        "text": "Implemented the session result compiler and verified the focused tests",
        "kind": "completion",
        "provenance": "agent_reported",
        "source": "transcript_heuristic",
    }


def test_reported_summary_is_scannable_without_another_model():
    summary = _reported_summary_text(
        "Exactly. The adapter can extract the latest final answer and use it as the summary. "
        "Verification remains a separate evidence layer for files, tests, builds, commits, and pull requests. "
        "This trailing explanation should not make the card excessively tall.",
        max_chars=200,
    )

    assert summary == (
        "The adapter can extract the latest final answer and use it as the summary. "
        "Verification remains a separate evidence layer for files, tests, builds, commits, and pull requests."
    )


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


async def test_memory_review_moves_resolved_records_to_recoverable_history(client, db_session):
    workspace = await _workspace(db_session, "Memory review")
    model = Model(id=uuid4(), name="Memory review model")
    document = SourceDocument(
        id=uuid4(), workspace_id=workspace.id, source_type="local",
        external_id="memory-review", content="Blocker: staging credentials are missing.",
        metadata_json=json.dumps({"workspace_id": str(workspace.id)}),
    )
    evidence_text = "staging credentials are missing."
    evidence = EvidenceSpan(
        workspace_id=workspace.id,
        source_document_id=document.id,
        start_char=document.content.index(evidence_text),
        end_char=document.content.index(evidence_text) + len(evidence_text),
        text=evidence_text,
        text_sha256=hashlib.sha256(evidence_text.encode()).hexdigest(),
        review_status="verified",
        trust_zone="trusted_human",
        extraction_method="deterministic",
    )
    claim = Claim(
        workspace_id=workspace.id,
        identity_key=f"blocker:{uuid4().hex}",
        scope_identity_sha256=hashlib.sha256(uuid4().bytes).hexdigest(),
        claim_type="blocker",
        status="active",
        temporal="current",
    )
    db_session.add_all([model, document, evidence, claim])
    await db_session.flush()
    revision = ClaimRevision(
        claim_id=claim.id,
        evidence_span_id=evidence.id,
        value=evidence_text,
        operation="create",
        status_after="active",
    )
    db_session.add(revision)
    await db_session.flush()
    claim.current_revision_id = revision.id
    blocker = Component(
        id=uuid4(), workspace_id=workspace.id, model_id=model.id,
        source_document_id=document.id, claim_id=claim.id,
        identity_key=claim.identity_key, name="Staging credentials are missing",
        value="Staging credentials are missing", fact_type="blocker",
        confidence=0.9, authority_weight=0.8, status="active",
    )
    db_session.add(blocker)
    await db_session.flush()

    active = (await client.get(
        "/api/context/digest", params={"workspace_id": str(workspace.id)}
    )).json()
    card_id = f"component:{blocker.id}"
    assert any(card["id"] == card_id for card in active["cards"])

    resolved = await client.patch(
        f"/api/context/memory/{blocker.id}",
        json={"workspace_id": str(workspace.id), "action": "resolve"},
    )
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "resolved"

    historical = (await client.get(
        "/api/context/digest", params={"workspace_id": str(workspace.id)}
    )).json()
    assert all(card["id"] != card_id for card in historical["cards"])
    history_card = next(card for card in historical["history_cards"] if card["id"] == card_id)
    assert history_card["status"] == "resolved"

    reopened = await client.patch(
        f"/api/context/memory/{blocker.id}",
        json={"workspace_id": str(workspace.id), "action": "reopen"},
    )
    assert reopened.status_code == 200
    assert reopened.json()["status"] == "active"


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
    assert any(
        card["source_snapshot"]["source_document_id"] == str(first.document.id)
        and card["status"] == "superseded"
        for card in digest["history_cards"]
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


async def test_digest_objective_skips_internal_runtime_instructions(client, db_session):
    workspace = await _workspace(db_session, "Objective noise")
    db_session.add(ContextPack(
        workspace_id=workspace.id,
        objective="Ship trustworthy project memory",
        markdown="",
        manifest="{}",
        repo_state_json="{}",
        created_at=utc_now() - timedelta(minutes=5),
    ))
    db_session.add(ContextPack(
        workspace_id=workspace.id,
        objective="Note that collaboration tools cannot be called from inside functions.exec",
        markdown="",
        manifest="{}",
        repo_state_json="{}",
        created_at=utc_now(),
    ))
    await db_session.flush()

    digest = (await client.get(
        "/api/context/digest", params={"workspace_id": str(workspace.id)}
    )).json()
    assert digest["objective"]["text"] == "Ship trustworthy project memory"


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


async def test_digest_defaults_to_latest_session_topic_until_user_selects_one(client, db_session):
    workspace = await _workspace(db_session, "Session activity")
    connector = Connector(
        workspace_id=workspace.id,
        connector_type="github",
        status="connected",
        config_json=json.dumps({"repositories": ["acme/project"]}),
    )
    model = Model(id=uuid4(), name=f"Session activity {uuid4().hex}")
    source = SourceDocument(
        id=uuid4(),
        workspace_id=workspace.id,
        source_type="agent_session",
        external_id="codex:session:activity",
        content=(
            "[USER]\nFix the authentication redirect loop.\n\n"
            "[ASSISTANT]\nI updated the callback handler because redirect state was being lost.\n\n"
            "[USER]\nThe redirect is still broken in the app.\n\n"
            "[ASSISTANT]\nI’m using the in-app browser to review the rendered page."
        ),
        metadata_json=json.dumps({
            "workspace_id": str(workspace.id),
            "session_id": "activity",
            "tool": "codex",
            "repository": "acme/project",
            "branch": "codex/auth-redirect",
        }),
    )
    root = Component(
        workspace_id=workspace.id,
        model_id=model.id,
        source_document_id=source.id,
        name="Session: codex authentication redirect",
        value=source.content[:500],
        fact_type="session_root",
        temporal="current",
        confidence=0.93,
        status="active",
    )
    db_session.add_all([connector, model, source, root])
    await db_session.flush()

    response = await client.get(
        "/api/context/digest", params={"workspace_id": str(workspace.id)}
    )
    assert response.status_code == 200
    activity = response.json()["activity"]

    assert activity["state"] == "snapshot"
    assert activity["primary"]["selected_for_now"] is False
    assert activity["primary"]["latest_topic"] == "The redirect is still broken in the app"
    assert activity["primary"]["title"] == "The redirect is still broken in the app"
    assert activity["primary"]["evidence_level"] == "session_reported"
    assert activity["primary"]["result_summary"] is None
    assert activity["primary"]["latest_update"] == (
        "I’m using the in-app browser to review the rendered page"
    )
    assert activity["recent_sessions"][0]["request"] == "The redirect is still broken in the app"
    assert activity["primary"]["attention_items"][0]["kind"] == "user_correction"
    assert activity["primary"]["attention_items"][0]["title"] == (
        "The redirect is still broken in the app"
    )

    selected = await client.put(
        "/api/session-library/selection",
        json={
            "workspace_id": str(workspace.id),
            "source_document_id": str(source.id),
            "topic": "Fix the authentication redirect loop",
        },
    )
    assert selected.status_code == 200

    selected_response = await client.get(
        "/api/context/digest", params={"workspace_id": str(workspace.id)}
    )
    assert selected_response.status_code == 200
    activity = selected_response.json()["activity"]

    assert activity["state"] == "snapshot"
    assert activity["primary"]["evidence_level"] == "session_reported"
    assert activity["primary"]["selected_for_now"] is True
    assert activity["primary"]["selected_topic"] == "Fix the authentication redirect loop"
    assert activity["primary"]["session_title"] == "Fix the authentication redirect loop"
    assert activity["primary"]["request"] == "The redirect is still broken in the app"
    assert activity["primary"]["latest_update"] == (
        "I’m using the in-app browser to review the rendered page"
    )
    assert activity["primary"]["rationale"] is None
    assert activity["primary"]["changed_files"] == []
    assert activity["primary"]["outcome"] is None
    assert activity["primary"]["source_card_id"] == f"component:{root.id}"


async def test_digest_default_preview_uses_newest_session_even_when_unassigned(
    client, db_session
):
    workspace = await _workspace(db_session, "Newest session preview")
    connector = Connector(
        workspace_id=workspace.id,
        connector_type="github",
        status="connected",
        config_json=json.dumps({"repositories": ["acme/project"]}),
    )
    model = Model(name=f"Newest session preview {uuid4().hex}")
    older = SourceDocument(
        workspace_id=workspace.id,
        source_type="agent_session",
        external_id="codex:session:older-relevant",
        content="[USER]\nReview the older project session.\n\n[ASSISTANT]\nReviewed.",
        metadata_json=json.dumps({
            "session_id": "older-relevant",
            "tool": "codex",
            "repository": "acme/project",
        }),
        ingested_at=utc_now() - timedelta(hours=2),
    )
    newer_modified_at = utc_now() - timedelta(hours=5)
    newer_observed_at = utc_now()
    newer = SourceDocument(
        workspace_id=workspace.id,
        source_type="agent_session",
        external_id="codex:session:newer-unassigned",
        content=(
            "[USER]\nStart the newer session.\n\n"
            "[ASSISTANT]\nStarted.\n\n"
            "[USER]\nShip the newest topic by default."
        ),
        metadata_json=json.dumps({
            "session_id": "newer-unassigned",
            "tool": "codex",
            "source_modified_at": newer_modified_at.isoformat(),
            "updated_at": newer_observed_at.isoformat(),
        }),
        ingested_at=newer_observed_at,
    )
    db_session.add_all([connector, model, older, newer])
    await db_session.flush()
    older_root = Component(
        workspace_id=workspace.id,
        model_id=model.id,
        source_document_id=older.id,
        name="Session: older relevant",
        value=older.content,
        fact_type="session_root",
        temporal="current",
        confidence=0.9,
        status="active",
    )
    db_session.add(older_root)
    await db_session.flush()

    response = await client.get(
        "/api/context/digest", params={"workspace_id": str(workspace.id)}
    )

    assert response.status_code == 200
    primary = response.json()["activity"]["primary"]
    assert primary["source_document_id"] == str(newer.id)
    assert primary["latest_topic"] == "Ship the newest topic by default"
    assert primary["selected_for_now"] is False
    assert primary["evidence_level"] == "session_unassigned"
    assert primary["source_card_id"] is None
    assert primary["result_summary"]["kind"] == "update"
    assert primary["result_summary"]["text"] == "Started"
    assert primary["updated_at"].startswith(newer_observed_at.isoformat(timespec="seconds"))
    assert primary["updated_at"].endswith(("Z", "+00:00"))


async def test_digest_matches_a_new_session_before_extraction_creates_cards(
    client, db_session
):
    workspace = await _workspace(db_session, "Direct session match")
    connector = Connector(
        workspace_id=workspace.id,
        connector_type="github",
        status="connected",
        config_json=json.dumps({"repositories": ["acme/project"]}),
    )
    source = SourceDocument(
        workspace_id=workspace.id,
        source_type="agent_session",
        external_id="codex:session:direct-match",
        content=(
            "[USER]\nFix automatic project matching.\n\n"
            "[ASSISTANT]\nImplemented deterministic repository matching."
        ),
        metadata_json=json.dumps({
            "session_id": "direct-match",
            "tool": "codex",
            "repository": "acme/project",
            "updated_at": (utc_now() - timedelta(hours=1)).isoformat(),
        }),
    )
    duplicate = SourceDocument(
        workspace_id=workspace.id,
        source_type="agent_session",
        external_id="codex:session:direct-match:duplicate-import",
        content="[USER]\nOld duplicate import.\n\n[ASSISTANT]\nImported.",
        metadata_json=json.dumps({
            "session_id": "direct-match",
            "tool": "codex",
            "repository": "acme/project",
            "updated_at": (utc_now() - timedelta(hours=2)).isoformat(),
        }),
    )
    db_session.add_all([connector, source, duplicate])
    await db_session.flush()

    response = await client.get(
        "/api/context/digest", params={"workspace_id": str(workspace.id)}
    )

    assert response.status_code == 200
    primary = response.json()["activity"]["primary"]
    assert primary["source_document_id"] == str(source.id)
    assert primary["source_card_id"] is None
    assert primary["evidence_level"] == "session_reported"
    assert primary["project_match"] == {
        "status": "relevant",
        "reasons": [
            "Session repository matches a configured workspace repository."
        ],
        "automatic": True,
    }
    recent = response.json()["activity"]["recent_sessions"]
    assert [item["session_id"] for item in recent] == ["direct-match"]


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
    assert digest["activity"]["state"] == "unassigned"
    assert digest["activity"]["primary"]["latest_topic"] == "Inspect the project"
    assert digest["activity"]["primary"]["selected_for_now"] is False

    selected = await client.put(
        "/api/session-library/selection",
        json={
            "workspace_id": str(workspace.id),
            "source_document_id": str(document.id),
            "topic": "Inspect the project",
        },
    )
    assert selected.status_code == 200

    selected_response = await client.get(
        "/api/context/digest", params={"workspace_id": str(workspace.id)}
    )
    assert selected_response.status_code == 200
    selected_digest = selected_response.json()
    selected_card = next(
        card for card in selected_digest["cards"]
        if card["category"] == "agent_session"
    )
    assert selected_card["workspace_relevance"]["status"] == "relevant"
    assert selected_card["workspace_relevance"]["reasons"] == [
        "Session was explicitly selected for this project."
    ]
    assert selected_digest["activity"]["primary"]["request"] == "Inspect the project"
    assert selected_digest["activity"]["primary"]["selected_for_now"] is True
    assert selected_digest["activity"]["primary"]["selected_topic"] == "Inspect the project"
    assert selected_digest["activity"]["primary"]["evidence_level"] == "session_reported"


async def test_digest_never_uses_runtime_instructions_as_session_work(client, db_session):
    workspace = await _workspace(db_session, "Clean session activity")
    model = Model(id=uuid4(), name=f"Clean session activity {uuid4().hex}")
    source = SourceDocument(
        id=uuid4(),
        workspace_id=workspace.id,
        source_type="agent_session",
        external_id="codex:session:runtime-noise",
        content=(
            "[USER]\nFix Prepare so it uses the actual user task.\n\n"
            "[ASSISTANT]\nI will inspect the session handoff.\n\n"
            "[USER]\nNote that collaboration tools cannot be called from inside functions.exec"
        ),
        metadata_json=json.dumps({
            "workspace_id": str(workspace.id),
            "session_id": "runtime-noise",
            "tool": "codex",
            "cwd": "/tmp/clean-session-activity",
            "title": "Prepare handoff behavior",
        }),
    )
    root = Component(
        workspace_id=workspace.id,
        model_id=model.id,
        source_document_id=source.id,
        name="Session: codex Prepare handoff behavior",
        value=source.content[:500],
        fact_type="session_root",
        temporal="current",
        confidence=0.93,
        status="active",
    )
    db_session.add_all([model, source, root])
    await db_session.flush()
    offending = "Note that collaboration tools cannot be called from inside functions.exec"
    await persist_session_events(
        db_session,
        workspace_id=workspace.id,
        source_document=source,
        provider="codex",
        session_id="runtime-noise",
        events=[
            NormalizedSessionEvent(
                provider_event_id="developer-policy",
                sequence_number=1,
                event_type="runtime_instruction",
                role="developer",
                content=offending,
            ),
            NormalizedSessionEvent(
                provider_event_id="real-request",
                sequence_number=2,
                event_type="user_request",
                role="user",
                content="Fix Prepare so it uses the actual user task.",
            ),
            NormalizedSessionEvent(
                provider_event_id="real-update",
                sequence_number=3,
                event_type="assistant_update",
                role="assistant",
                content="I will inspect the session handoff because the request boundary was wrong.",
            ),
            NormalizedSessionEvent(
                provider_event_id="mislabelled-policy",
                sequence_number=4,
                event_type="user_request",
                role="user",
                content=offending,
            ),
            NormalizedSessionEvent(
                provider_event_id="delegated-user-task",
                sequence_number=5,
                event_type="runtime_instruction",
                role="user",
                content=(
                    "<codex_delegation><input>Continue the checkpoint repair; the live "
                    "product is wrong.\n\nObserved defect: "
                    f"{offending}</input></codex_delegation>"
                ),
            ),
            NormalizedSessionEvent(
                provider_event_id="delegated-update",
                sequence_number=6,
                event_type="assistant_update",
                role="assistant",
                content="I traced the coherent session boundary because the selector was wrong.",
            ),
        ],
    )

    response = await client.get(
        "/api/context/digest", params={"workspace_id": str(workspace.id)}
    )

    assert response.status_code == 200
    primary = response.json()["activity"]["primary"]
    assert primary["request"] == (
        "Continue the checkpoint repair; the live product is wrong"
    )
    for field in ("title", "request", "latest_update", "rationale"):
        assert "collaboration tools" not in (primary[field] or "").lower()
    assert primary["provider"] == "codex"
    assert primary["session_id"] == "runtime-noise"
    assert primary["recency_basis"] == "imported_at_fallback"
