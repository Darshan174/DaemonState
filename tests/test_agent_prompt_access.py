from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

import pytest

import app.agents.context_pack as context_pack_module
import app.agents.gap_detector as gap_module
import app.agents.relationship_agent as relationship_module
from app.agents.context_pack import ContextPackAgent
from app.agents.gap_detector import GapDetectorAgent
from app.agents.relationship_agent import RelationshipAgent
from app.agents.semantic_linker import SemanticCandidate
from app.api.dependencies import get_access_scope
from app.main import app
from app.models import Component, Model, Relationship, SourceDocument, Workspace
from app.services.access import AccessScope


PUBLIC_DECISION = "Visible workspace decision"
PUBLIC_TASK = "Visible workspace task"
RESTRICTED_COMPONENT = "Restricted workspace strategy"
CROSS_WORKSPACE_COMPONENT = "Other workspace strategy"


async def _seed_scoped_graph(db_session) -> dict[str, Any]:
    primary = Workspace(
        id=uuid4(),
        name="Primary prompt boundary",
        slug=f"primary-prompt-boundary-{uuid4().hex}",
    )
    other = Workspace(
        id=uuid4(),
        name="Other prompt boundary",
        slug=f"other-prompt-boundary-{uuid4().hex}",
    )
    decision_model = Model(id=uuid4(), name=f"Decision {uuid4().hex}")
    task_model = Model(id=uuid4(), name=f"Task {uuid4().hex}")
    risk_model = Model(id=uuid4(), name=f"Risk {uuid4().hex}")
    feature_model = Model(id=uuid4(), name=f"Feature {uuid4().hex}")

    public_decision_source = SourceDocument(
        id=uuid4(),
        workspace_id=primary.id,
        source_type="local",
        external_id=f"public-decision-{uuid4().hex}",
        content=PUBLIC_DECISION,
        metadata_json=json.dumps({"workspace_id": str(primary.id)}),
        visibility_scope="workspace",
        permission_snapshot_sha256="public-decision-snapshot",
    )
    public_task_source = SourceDocument(
        id=uuid4(),
        workspace_id=primary.id,
        source_type="local",
        external_id=f"public-task-{uuid4().hex}",
        content=PUBLIC_TASK,
        metadata_json=json.dumps({"workspace_id": str(primary.id)}),
        visibility_scope="workspace",
        permission_snapshot_sha256="public-task-snapshot",
    )
    restricted_source = SourceDocument(
        id=uuid4(),
        workspace_id=primary.id,
        source_type="local",
        external_id=f"restricted-{uuid4().hex}",
        content=RESTRICTED_COMPONENT,
        metadata_json=json.dumps({"workspace_id": str(primary.id)}),
        visibility_scope="restricted",
        permission_source="explicit",
        permission_snapshot_sha256="restricted-snapshot",
    )
    cross_workspace_source = SourceDocument(
        id=uuid4(),
        workspace_id=other.id,
        source_type="local",
        external_id=f"cross-workspace-{uuid4().hex}",
        content=CROSS_WORKSPACE_COMPONENT,
        metadata_json=json.dumps({"workspace_id": str(other.id)}),
        visibility_scope="workspace",
        permission_snapshot_sha256="cross-workspace-snapshot",
    )

    public_decision = Component(
        id=uuid4(),
        workspace_id=primary.id,
        model_id=decision_model.id,
        source_document_id=public_decision_source.id,
        name=PUBLIC_DECISION,
        value="The primary workspace chose a guarded launch.",
        fact_type="decision",
        temporal="current",
        confidence=0.9,
        status="active",
    )
    public_task = Component(
        id=uuid4(),
        workspace_id=primary.id,
        model_id=task_model.id,
        source_document_id=public_task_source.id,
        name=PUBLIC_TASK,
        value="Ship the guarded launch task.",
        fact_type="task",
        temporal="current",
        confidence=0.9,
        status="active",
    )
    restricted = Component(
        id=uuid4(),
        workspace_id=primary.id,
        model_id=risk_model.id,
        source_document_id=restricted_source.id,
        name=RESTRICTED_COMPONENT,
        value="Private acquisition financing details.",
        fact_type="risk",
        temporal="current",
        confidence=0.95,
        status="active",
    )
    cross_workspace = Component(
        id=uuid4(),
        workspace_id=other.id,
        model_id=feature_model.id,
        source_document_id=cross_workspace_source.id,
        name=CROSS_WORKSPACE_COMPONENT,
        value="Another tenant's confidential roadmap.",
        fact_type="feature",
        temporal="current",
        confidence=0.95,
        status="active",
    )

    visible_relationship = Relationship(
        id=uuid4(),
        source_component_id=public_decision.id,
        target_component_id=public_task.id,
        relationship_type="implements",
    )
    restricted_relationship = Relationship(
        id=uuid4(),
        source_component_id=public_task.id,
        target_component_id=restricted.id,
        relationship_type="blocked_by",
    )
    cross_workspace_relationship = Relationship(
        id=uuid4(),
        source_component_id=public_task.id,
        target_component_id=cross_workspace.id,
        relationship_type="relates_to",
    )
    db_session.add_all([
        primary,
        other,
        decision_model,
        task_model,
        risk_model,
        feature_model,
        public_decision_source,
        public_task_source,
        restricted_source,
        cross_workspace_source,
        public_decision,
        public_task,
        restricted,
        cross_workspace,
        visible_relationship,
        restricted_relationship,
        cross_workspace_relationship,
    ])
    await db_session.flush()
    return {
        "primary": primary,
        "public_components": [public_decision, public_task],
        "all_components": [
            public_decision,
            public_task,
            restricted,
            cross_workspace,
        ],
        "public_source_ids": {
            public_decision_source.id,
            public_task_source.id,
        },
    }


def _outbound_payload_text(artifact) -> str:
    envelope = json.loads(artifact.messages()[1]["content"])
    assert envelope["trust"] == "untrusted_data"
    return json.dumps(envelope["payload"], sort_keys=True)


def _assert_only_public_markers(payload: str) -> None:
    assert PUBLIC_DECISION in payload
    assert PUBLIC_TASK in payload
    assert RESTRICTED_COMPONENT not in payload
    assert CROSS_WORKSPACE_COMPONENT not in payload


@pytest.mark.asyncio
async def test_gap_prompt_filters_restricted_and_cross_workspace_evidence(
    db_session,
    monkeypatch,
):
    graph = await _seed_scoped_graph(db_session)
    captured = []

    async def fake_invoke(artifact, **_kwargs):
        captured.append(artifact)
        return {
            "summary": "No evidence-backed gaps were selected.",
            "gaps": [],
            "ready_to_ship": [],
            "blocked": [],
        }

    monkeypatch.setattr(gap_module, "invoke_prompt_artifact", fake_invoke)
    monkeypatch.setattr(gap_module, "provider_supports_json_schema", lambda _model: False)
    scope = AccessScope("bob", frozenset({graph["primary"].id}))

    await GapDetectorAgent(db_session, api_key="test", model="test-model").run(
        workspace_id=graph["primary"].id,
        access_scope=scope,
    )

    assert len(captured) == 1
    _assert_only_public_markers(_outbound_payload_text(captured[0]))


@pytest.mark.asyncio
async def test_context_pack_prompt_filters_requested_but_inaccessible_evidence(
    db_session,
    monkeypatch,
):
    graph = await _seed_scoped_graph(db_session)
    captured = []

    async def fake_invoke(artifact, **_kwargs):
        captured.append(artifact)
        return {
            "project_goal": [],
            "current_state": [],
            "open_decisions": [],
            "active_blockers": [],
            "past_agent_attempts": [],
            "next_tasks": [],
        }

    monkeypatch.setattr(context_pack_module, "invoke_prompt_artifact", fake_invoke)
    monkeypatch.setattr(
        context_pack_module,
        "provider_supports_json_schema",
        lambda _model: False,
    )
    scope = AccessScope("bob", frozenset({graph["primary"].id}))

    await ContextPackAgent(db_session, api_key="test", model="test-model").run(
        component_ids=[component.id for component in graph["all_components"]],
        workspace_id=graph["primary"].id,
        access_scope=scope,
    )

    assert len(captured) == 1
    _assert_only_public_markers(_outbound_payload_text(captured[0]))


@pytest.mark.asyncio
async def test_relationship_prompt_filters_before_candidate_generation_and_outbound_data(
    db_session,
    monkeypatch,
):
    graph = await _seed_scoped_graph(db_session)
    captured = []
    candidate_inputs = []

    async def fake_candidate_pairs(
        self,
        components=None,
        workspace_scope=None,
        *,
        allowed_source_document_ids=None,
    ):
        candidate_inputs.append((components, workspace_scope, allowed_source_document_ids))
        return [SemanticCandidate(source=components[0], target=components[1], score=0.91)]

    async def fake_invoke(artifact, **_kwargs):
        captured.append(artifact)
        return {"suggested_relationships": [], "duplicates": []}

    monkeypatch.setattr(RelationshipAgent, "_candidate_pairs", fake_candidate_pairs)
    monkeypatch.setattr(relationship_module, "invoke_prompt_artifact", fake_invoke)
    monkeypatch.setattr(
        relationship_module,
        "provider_supports_json_schema",
        lambda _model: False,
    )
    scope = AccessScope("bob", frozenset({graph["primary"].id}))

    await RelationshipAgent(db_session, api_key="test", model="test-model").run(
        workspace_id=str(graph["primary"].id),
        access_scope=scope,
    )

    assert len(candidate_inputs) == 1
    components, workspace_scope, allowed_source_document_ids = candidate_inputs[0]
    assert {component.name for component in components} == {PUBLIC_DECISION, PUBLIC_TASK}
    assert workspace_scope[0] == str(graph["primary"].id)
    assert allowed_source_document_ids == graph["public_source_ids"]
    assert len(captured) == 1
    _assert_only_public_markers(_outbound_payload_text(captured[0]))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "agent_type",
    [GapDetectorAgent, ContextPackAgent, RelationshipAgent],
)
async def test_bounded_agents_require_an_explicit_workspace(db_session, agent_type):
    scope = AccessScope("bob", frozenset({uuid4()}))

    with pytest.raises(ValueError, match="workspace_id is required"):
        await agent_type(db_session).run(access_scope=scope)


@pytest.mark.asyncio
async def test_gap_prompt_keeps_unrestricted_local_no_workspace_compatibility(
    db_session,
    monkeypatch,
):
    await _seed_scoped_graph(db_session)
    captured = []

    async def fake_invoke(artifact, **_kwargs):
        captured.append(artifact)
        return {
            "summary": "No evidence-backed gaps were selected.",
            "gaps": [],
            "ready_to_ship": [],
            "blocked": [],
        }

    monkeypatch.setattr(gap_module, "invoke_prompt_artifact", fake_invoke)
    monkeypatch.setattr(gap_module, "provider_supports_json_schema", lambda _model: False)

    await GapDetectorAgent(db_session, api_key="test", model="test-model").run()

    assert len(captured) == 1
    payload = _outbound_payload_text(captured[0])
    assert RESTRICTED_COMPONENT in payload
    assert CROSS_WORKSPACE_COMPONENT in payload


@pytest.mark.asyncio
async def test_context_pack_keeps_unrestricted_local_no_workspace_compatibility(
    db_session,
    monkeypatch,
):
    await _seed_scoped_graph(db_session)
    captured = []

    async def fake_invoke(artifact, **_kwargs):
        captured.append(artifact)
        return {
            "project_goal": [],
            "current_state": [],
            "open_decisions": [],
            "active_blockers": [],
            "past_agent_attempts": [],
            "next_tasks": [],
        }

    monkeypatch.setattr(context_pack_module, "invoke_prompt_artifact", fake_invoke)
    monkeypatch.setattr(
        context_pack_module,
        "provider_supports_json_schema",
        lambda _model: False,
    )

    await ContextPackAgent(db_session, api_key="test", model="test-model").run()

    assert len(captured) == 1
    payload = _outbound_payload_text(captured[0])
    assert RESTRICTED_COMPONENT in payload
    assert CROSS_WORKSPACE_COMPONENT in payload


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint", ["gaps", "context-pack"])
async def test_agent_api_requires_workspace_for_bounded_principals(
    client,
    endpoint,
):
    async def bounded_scope():
        return AccessScope("bob", frozenset({uuid4()}))

    app.dependency_overrides[get_access_scope] = bounded_scope

    response = await client.post(f"/api/agents/{endpoint}", json={})

    assert response.status_code == 422
    assert response.json()["detail"] == "workspace_id is required"


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint", ["gaps", "context-pack", "relationships"])
async def test_agent_api_hides_unauthorized_workspaces(client, endpoint):
    allowed_workspace_id = uuid4()

    async def bounded_scope():
        return AccessScope("bob", frozenset({allowed_workspace_id}))

    app.dependency_overrides[get_access_scope] = bounded_scope

    response = await client.post(
        f"/api/agents/{endpoint}",
        json={"workspace_id": str(uuid4())},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Workspace not found"
