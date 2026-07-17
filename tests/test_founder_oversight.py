from __future__ import annotations

import json
from datetime import datetime, timedelta
from uuid import uuid4

import pytest

from app.models import (
    AgentRun,
    Component,
    ContextPack,
    ContextPackItem,
    Model,
    RunObservation,
    SourceDocument,
    Workspace,
)
from app.services.founder_oversight import (
    FounderOversightNotFoundError,
    FounderOversightService,
)
from app.services.context_compiler import ContextCompiler


BASE_TIME = datetime(2026, 7, 14, 12, 0, 0)


def _manifest(
    *,
    include_second_command: bool = False,
    required_item: str = "component:focus",
    include_verification: bool = True,
):
    commands = [
        {
            "id": "V1",
            "command": "pytest -q tests/test_founder_oversight.py",
            "required": True,
        }
    ]
    if include_second_command:
        commands.append({"id": "V2", "command": "npm test", "required": True})
    return {
        "schema_version": "context_pack.v2",
        "selected_context": [{"id": required_item, "mandatory": True}],
        "verification": {"commands": commands if include_verification else []},
    }


async def _source(session, *, workspace_id, external_id, content, supersedes=None):
    document = SourceDocument(
        id=uuid4(),
        workspace_id=workspace_id,
        source_type="local",
        external_id=external_id,
        content=content,
        supersedes_source_document_id=supersedes,
        revision_number=2 if supersedes is not None else 1,
        metadata_json="{}",
        ingested_at=BASE_TIME,
    )
    session.add(document)
    await session.flush()
    return document


async def _fixture(session, *, include_second_command=False, include_verification=True):
    workspace = Workspace(id=uuid4(), name=f"Workspace {uuid4()}", slug=f"ws-{uuid4()}")
    model = Model(id=uuid4(), name=f"Model {uuid4()}")
    session.add_all([workspace, model])
    await session.flush()
    focus_source = await _source(
        session,
        workspace_id=workspace.id,
        external_id="focus-task",
        content="Task: make runtime writes retry-safe.",
    )
    focus = Component(
        id=uuid4(),
        workspace_id=workspace.id,
        model_id=model.id,
        source_document_id=focus_source.id,
        name="Retry-safe writes",
        value="Make runtime writes retry-safe",
        fact_type="task",
        status="active",
    )
    session.add(focus)
    await session.flush()
    pack = ContextPack(
        id=uuid4(),
        workspace_id=workspace.id,
        focus_component_id=focus.id,
        objective_origin="source_component",
        objective_source_document_id=focus_source.id,
        objective="Make runtime writes retry-safe",
        markdown="# Task",
        manifest=json.dumps(_manifest(
            include_second_command=include_second_command,
            include_verification=include_verification,
        )),
        repo_state_json="{}",
        created_at=BASE_TIME,
    )
    session.add(pack)
    await session.flush()
    item = ContextPackItem(
        id=uuid4(),
        context_pack_id=pack.id,
        manifest_item_id="component:focus",
        component_id=focus.id,
        source_document_id=focus_source.id,
        inclusion_reason="focused_component",
    )
    session.add(item)
    await session.flush()
    run = AgentRun(
        id=uuid4(),
        workspace_id=workspace.id,
        context_pack_id=pack.id,
        run_key="run-1",
        status="completed",
        tool="codex",
        model="gpt-5",
        branch="codex/oversight",
        started_at=BASE_TIME + timedelta(minutes=1),
        ended_at=BASE_TIME + timedelta(minutes=8),
    )
    session.add(run)
    await session.flush()
    return workspace, focus, focus_source, pack, item, run


async def _observation(
    session,
    *,
    workspace_id,
    run,
    event_key,
    event_type,
    payload,
    minute,
):
    document = await _source(
        session,
        workspace_id=workspace_id,
        external_id=f"agent_runtime:{run.id}:{event_key}",
        content=json.dumps(payload, sort_keys=True),
    )
    observation = RunObservation(
        id=uuid4(),
        agent_run_id=run.id,
        source_document_id=document.id,
        event_key=event_key,
        event_type=event_type,
        payload_json=json.dumps(payload, sort_keys=True, separators=(",", ":")),
        observed_at=BASE_TIME + timedelta(minutes=minute),
        content=payload.get("content") or payload.get("summary") or payload.get("blocker"),
        command=payload.get("command"),
        exit_code=payload.get("exit_code"),
    )
    session.add(observation)
    await session.flush()
    return observation


async def test_verified_timeline_is_calm_and_ignores_ambiguous_prose(db_session):
    workspace, focus, _, _, _, run = await _fixture(db_session)
    await _observation(
        db_session,
        workspace_id=workspace.id,
        run=run,
        event_key="note-1",
        event_type="note",
        payload={"content": "Tests failed earlier and this code might be slop."},
        minute=2,
    )
    await _observation(
        db_session,
        workspace_id=workspace.id,
        run=run,
        event_key="patch-1",
        event_type="patch_summary",
        payload={
            "summary": "Implemented retry-safe writes.",
            "addresses_context_item_ids": ["component:focus"],
            "files": ["app/mcp/server.py"],
        },
        minute=3,
    )
    await _observation(
        db_session,
        workspace_id=workspace.id,
        run=run,
        event_key="verify-1",
        event_type="verification",
        payload={
            "command": "  pytest   -q tests/test_founder_oversight.py ",
            "exit_code": 0,
            "content": "Focused tests passed.",
        },
        minute=4,
    )
    await _observation(
        db_session,
        workspace_id=workspace.id,
        run=run,
        event_key="outcome",
        event_type="outcome",
        payload={"status": "completed", "summary": "Runtime writes are retry-safe."},
        minute=5,
    )

    result = await FounderOversightService(db_session).build_timeline(
        workspace_id=workspace.id,
        focus_component_id=focus.id,
        evaluated_at=BASE_TIME + timedelta(minutes=10),
    )

    assert result["state"] == "verified"
    assert result["findings"] == []
    assert result["attention"] == {"blocked": 0, "unverified": 0, "stale": 0}
    assert [event["event_key"] for event in result["runs"][0]["events"]] == [
        "patch-1",
        "verify-1",
        "outcome",
    ]
    assert result["latest_outcome"]["summary"] == "Runtime writes are retry-safe."


async def test_success_without_required_checks_is_completed_unverified(db_session):
    workspace, focus, _, _, _, run = await _fixture(
        db_session,
        include_verification=False,
    )
    await _observation(
        db_session,
        workspace_id=workspace.id,
        run=run,
        event_key="outcome",
        event_type="outcome",
        payload={"status": "completed", "summary": "Work was reported complete."},
        minute=5,
    )

    result = await FounderOversightService(db_session).build_timeline(
        workspace_id=workspace.id,
        focus_component_id=focus.id,
        evaluated_at=BASE_TIME + timedelta(minutes=10),
    )

    assert result["state"] == "completed_unverified"


async def test_finish_payload_verification_is_evaluated_and_visible(db_session):
    workspace, focus, _, _, _, run = await _fixture(db_session)
    await _observation(
        db_session,
        workspace_id=workspace.id,
        run=run,
        event_key="outcome",
        event_type="outcome",
        payload={
            "status": "completed",
            "summary": "Work was reported complete.",
            "completed_context_item_ids": ["component:focus"],
            "verification_results": [{
                "command": "pytest -q tests/test_founder_oversight.py",
                "exit_code": 0,
                "status": "passed",
            }],
        },
        minute=5,
    )

    result = await FounderOversightService(db_session).build_timeline(
        workspace_id=workspace.id,
        focus_component_id=focus.id,
        evaluated_at=BASE_TIME + timedelta(minutes=10),
    )

    assert result["state"] == "verified"
    outcome = result["runs"][0]["events"][0]
    assert outcome["verification_results"] == [{
        "command": "pytest -q tests/test_founder_oversight.py",
        "requirement_id": None,
        "status": "passed",
        "exit_code": 0,
    }]


async def test_focused_compile_mcp_run_and_scrutiny_full_loop(
    db_session,
    monkeypatch,
    tmp_path,
):
    from app.mcp import server as mcp_server

    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_runtime.py").write_text(
        "def test_runtime():\n    assert True\n",
    )
    workspace = Workspace(id=uuid4(), name="Full loop", slug=f"full-loop-{uuid4()}")
    model = Model(id=uuid4(), name=f"Task-{uuid4()}")
    source = SourceDocument(
        id=uuid4(),
        workspace_id=workspace.id,
        source_type="local",
        external_id="full-loop-task",
        content="Task: add focused runtime verification with tests.",
        metadata_json="{}",
    )
    focus = Component(
        id=uuid4(),
        workspace_id=workspace.id,
        model_id=model.id,
        source_document_id=source.id,
        name="Focused runtime verification",
        value="Add focused runtime verification with tests.",
        fact_type="task",
        status="active",
        confidence=0.9,
        authority_weight=0.9,
    )
    db_session.add_all([workspace, model, source, focus])
    await db_session.flush()

    pack_result = await ContextCompiler(db_session).compile_context_pack(
        "",
        workspace_id=workspace.id,
        repo_path=str(tmp_path),
        token_budget=3000,
        focus_component_id=focus.id,
        objective_origin="source_component",
    )
    manifest = pack_result.manifest
    required = next(
        command
        for command in manifest["verification"]["commands"]
        if command.get("required") is True
    )
    mandatory_item_ids = [
        item["id"]
        for item in manifest["selected_context"]
        if item.get("mandatory") is True
    ]
    assert any(
        item.get("component_id") == str(focus.id)
        for item in manifest["selected_context"]
        if item["id"] in mandatory_item_ids
    )

    class TestSessionContext:
        async def __aenter__(self):
            return db_session

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(mcp_server, "AsyncSessionLocal", lambda: TestSessionContext())
    started = json.loads((await mcp_server._record_agent_run_start(
        tool="codex",
        model="gpt-5",
        branch="codex/full-loop",
        base_commit="abc123",
        objective=manifest["objective"],
        context_pack_id=pack_result.context_pack_id,
        run_key="full-loop-run",
    ))[0].text)
    run_id = started["run_id"]
    await mcp_server._record_patch_summary(
        run_id=run_id,
        changed_files=["tests/test_runtime.py"],
        summary="Added focused runtime verification.",
        tests_run=[required["command"]],
        event_key="patch",
        addresses_context_item_ids=mandatory_item_ids,
    )
    finished = json.loads((await mcp_server._record_agent_run_finish(
        run_id=run_id,
        status="completed",
        head_commit="def456",
        summary="Focused runtime verification completed.",
        changed_files=["tests/test_runtime.py"],
        verification_results=[{
            "requirement_id": required.get("id"),
            "command": required["command"],
            "exit_code": 0,
            "status": "passed",
        }],
        event_key="outcome",
        completed_context_item_ids=mandatory_item_ids,
    ))[0].text)

    timeline = await FounderOversightService(db_session).build_timeline(
        workspace_id=workspace.id,
        focus_component_id=focus.id,
    )

    assert finished["status"] == "completed"
    assert timeline["state"] == "verified"
    assert timeline["findings"] == []
    assert [event["event_type"] for event in timeline["runs"][0]["events"]] == [
        "patch_summary",
        "outcome",
    ]


async def test_all_scrutiny_rules_require_structured_exact_evidence(db_session):
    workspace, focus, focus_source, _, item, run = await _fixture(
        db_session, include_second_command=True
    )
    blocker = await _observation(
        db_session,
        workspace_id=workspace.id,
        run=run,
        event_key="blocker-1",
        event_type="blocker",
        payload={"blocker": "Migration cannot run.", "severity": "high"},
        minute=2,
    )
    verification = await _observation(
        db_session,
        workspace_id=workspace.id,
        run=run,
        event_key="verify-1",
        event_type="verification",
        payload={
            "requirement_id": "V1",
            "command": "something unrelated",
            "exit_code": 1,
        },
        minute=3,
    )
    outcome = await _observation(
        db_session,
        workspace_id=workspace.id,
        run=run,
        event_key="outcome",
        event_type="outcome",
        payload={"status": "success", "summary": "Everything completed."},
        minute=4,
    )
    await _source(
        db_session,
        workspace_id=workspace.id,
        external_id="focus-task",
        content="Task: make runtime writes retry-safe and observable.",
        supersedes=focus_source.id,
    )

    service = FounderOversightService(db_session)
    first = await service.build_timeline(
        workspace_id=workspace.id,
        focus_component_id=focus.id,
        evaluated_at=BASE_TIME + timedelta(minutes=10),
    )
    second = await service.build_timeline(
        workspace_id=workspace.id,
        focus_component_id=focus.id,
        evaluated_at=BASE_TIME + timedelta(minutes=10),
    )

    assert first["state"] == "conflicting_evidence"
    by_rule = {finding["rule_id"]: finding for finding in first["findings"]}
    assert set(by_rule) == {
        "verification.missing.v1",
        "verification.failed.v1",
        "blocker.unresolved.v1",
        "completion.evidence_missing.v1",
        "outcome.check_conflict.v1",
        "source.stale.v1",
    }
    assert by_rule["blocker.unresolved.v1"]["severity"] == "critical"
    assert by_rule["verification.failed.v1"]["trigger_ids"] == [str(verification.id), "V1"]
    assert str(blocker.id) in by_rule["blocker.unresolved.v1"]["trigger_ids"]
    assert str(item.id) in by_rule["completion.evidence_missing.v1"]["trigger_ids"]
    assert str(outcome.id) in by_rule["outcome.check_conflict.v1"]["trigger_ids"]
    assert all(finding["sources"][0]["source_document_id"] for finding in first["findings"])
    assert [finding["id"] for finding in first["findings"]] == [
        finding["id"] for finding in second["findings"]
    ]
    assert first["attention"] == {"blocked": 1, "unverified": 4, "stale": 1}


async def test_resolution_must_be_later_and_command_matching_is_exact(db_session):
    workspace, focus, _, _, _, run = await _fixture(db_session)
    await _observation(
        db_session,
        workspace_id=workspace.id,
        run=run,
        event_key="blocker-1",
        event_type="blocker",
        payload={"blocker": "Need a schema decision.", "severity": "medium"},
        minute=2,
    )
    await _observation(
        db_session,
        workspace_id=workspace.id,
        run=run,
        event_key="resolve-1",
        event_type="blocker_resolution",
        payload={"resolves_event_key": "blocker-1", "content": "Schema decision recorded."},
        minute=3,
    )
    await _observation(
        db_session,
        workspace_id=workspace.id,
        run=run,
        event_key="wrong-command",
        event_type="verification",
        payload={
            "command": "pytest -q tests/test_mcp.py",
            "exit_code": 1,
            "content": "This is a different check.",
        },
        minute=4,
    )
    await _observation(
        db_session,
        workspace_id=workspace.id,
        run=run,
        event_key="outcome",
        event_type="outcome",
        payload={"status": "completed", "completed_context_item_ids": ["component:focus"]},
        minute=5,
    )

    result = await FounderOversightService(db_session).build_timeline(
        workspace_id=workspace.id,
        focus_component_id=focus.id,
        evaluated_at=BASE_TIME + timedelta(minutes=10),
    )

    assert result["state"] == "verification_missing"
    assert {item["rule_id"] for item in result["findings"]} == {"verification.missing.v1"}


async def test_workspace_scope_hides_cross_workspace_focus(db_session):
    workspace, focus, _, _, _, _ = await _fixture(db_session)
    other = Workspace(id=uuid4(), name="Other", slug=f"other-{uuid4()}")
    db_session.add(other)
    await db_session.flush()

    with pytest.raises(FounderOversightNotFoundError):
        await FounderOversightService(db_session).build_timeline(
            workspace_id=other.id,
            focus_component_id=focus.id,
        )

    result = await FounderOversightService(db_session).build_timeline(
        workspace_id=workspace.id,
        focus_component_id=focus.id,
    )
    assert result["workspace_id"] == str(workspace.id)
    assert result["focus"]["component_id"] == str(focus.id)


async def test_timeline_api_and_digest_expose_latest_focused_oversight(client, db_session):
    workspace, focus, _, pack, _, run = await _fixture(db_session)
    manifest = json.loads(pack.manifest)
    manifest["affected_code"] = {
        "schema_version": "affected_code.v1",
        "snapshot": {"head_commit": "abc123", "dirty": False},
        "files": [
            {
                "path": "app/services/founder_oversight.py",
                "role": "likely_implementation",
                "why": "Matches the focused task.",
                "related_tests": [
                    {
                        "path": "tests/test_founder_oversight.py",
                        "why": "Linked by an exact test path.",
                    }
                ],
            }
        ],
    }
    pack.manifest = json.dumps(manifest)
    await db_session.flush()
    await _observation(
        db_session,
        workspace_id=workspace.id,
        run=run,
        event_key="verify-api",
        event_type="verification",
        payload={
            "command": "pytest -q tests/test_founder_oversight.py",
            "exit_code": 0,
            "content": "Focused oversight tests passed.",
        },
        minute=3,
    )
    await _observation(
        db_session,
        workspace_id=workspace.id,
        run=run,
        event_key="outcome",
        event_type="outcome",
        payload={
            "status": "completed",
            "summary": "Founder oversight is source backed.",
            "completed_context_item_ids": ["component:focus"],
        },
        minute=4,
    )

    timeline_response = await client.get(
        "/api/context/run-timeline",
        params={
            "workspace_id": str(workspace.id),
            "focus_component_id": str(focus.id),
        },
    )
    assert timeline_response.status_code == 200
    timeline = timeline_response.json()
    assert timeline["schema_version"] == "run_timeline.v1"
    assert timeline["state"] == "verified"
    assert timeline["latest_outcome"]["summary"] == "Founder oversight is source backed."
    assert timeline["affected_code"]["files"][0]["path"] == (
        "app/services/founder_oversight.py"
    )

    selected = await client.put(
        f"/api/workspaces/{workspace.id}/current-goal",
        json={"title": focus.name, "component_id": str(focus.id)},
    )
    assert selected.status_code == 200

    digest_response = await client.get(
        "/api/context/digest", params={"workspace_id": str(workspace.id)}
    )
    assert digest_response.status_code == 200
    oversight = digest_response.json()["oversight"]
    assert oversight["current_focus"] == {
        "component_id": str(focus.id),
        "title": focus.name,
        "context_pack_id": str(pack.id),
    }
    assert oversight["state"] == "verified"
    assert oversight["attention"] == {"blocked": 0, "unverified": 0, "stale": 0}
