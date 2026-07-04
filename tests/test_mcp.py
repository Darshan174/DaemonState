from __future__ import annotations

import json
from uuid import UUID, uuid4

from sqlalchemy import select

from app.models import Claim, Component, ContextPack, SourceDocument, Workspace


def _patch_mcp_session(monkeypatch, db_session):
    from app.mcp import server as mcp_server

    class TestSessionContext:
        async def __aenter__(self):
            return db_session

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(mcp_server, "AsyncSessionLocal", lambda: TestSessionContext())
    return mcp_server


async def test_mcp_lists_runtime_bridge_tools_with_trust_warning():
    from app.mcp.server import list_tools

    tools = await list_tools()
    by_name = {tool.name: tool for tool in tools}

    required = {
        "prepare_task",
        "record_agent_run_start",
        "record_agent_event",
        "record_decision",
        "record_blocker",
        "record_patch_summary",
        "verify_context_item",
        "close_task",
    }
    assert required <= set(by_name)
    assert "untrusted project data" in by_name["prepare_task"].description
    assert "untrusted project data" in by_name["record_decision"].description
    assert "untrusted project data" in by_name["query_context"].description


async def test_prepare_task_calls_compiler_and_persists_pack(db_session, monkeypatch, tmp_path):
    workspace = Workspace(id=uuid4(), name="MCP", slug=f"mcp-{uuid4()}")
    db_session.add(workspace)
    await db_session.flush()
    (tmp_path / "app.py").write_text("def handler():\n    return True\n")

    mcp_server = _patch_mcp_session(monkeypatch, db_session)
    result = await mcp_server._prepare_task(
        "fix app.py and run pytest -q",
        workspace_id=str(workspace.id),
        repo_path=str(tmp_path),
        target_model="qwen2.5-coder-7b",
        token_budget=2000,
    )
    data = json.loads(result[0].text)

    assert data["schema_version"] == "context_pack.v2"
    assert data["context_pack_id"]
    assert data["manifest"]["target_model"]["profile"] == "small_coder_model"
    assert "## Objective" in data["markdown"]
    pack = await db_session.get(ContextPack, UUID(data["context_pack_id"]))
    assert pack is not None
    assert pack.pack_version == "context_pack.v2"


async def test_mcp_runtime_write_tools_persist_source_backed_loop(
    db_session,
    monkeypatch,
):
    workspace = Workspace(id=uuid4(), name="Runtime", slug=f"runtime-{uuid4()}")
    pack = ContextPack(
        id=uuid4(),
        workspace_id=workspace.id,
        objective="finish runtime bridge",
        target_model="qwen2.5-coder-7b",
        token_budget=2000,
        markdown="# Context Pack v2",
        manifest=json.dumps({"schema_version": "context_pack.v2"}),
    )
    db_session.add_all([workspace, pack])
    await db_session.flush()

    mcp_server = _patch_mcp_session(monkeypatch, db_session)
    run_result = await mcp_server._record_agent_run_start(
        tool="codex",
        model="qwen2.5-coder-7b",
        branch="agent/4-mcp-evals-oss-readiness",
        base_commit="abc123",
        objective="finish runtime bridge",
        context_pack_id=str(pack.id),
    )
    run_id = json.loads(run_result[0].text)["run_id"]

    event_result = await mcp_server._record_agent_event(
        run_id=run_id,
        event_type="test",
        content="pytest passed",
        files=["tests/test_mcp.py"],
        command="pytest -q tests/test_mcp.py",
        exit_code=0,
    )
    event = json.loads(event_result[0].text)
    source_doc = await db_session.get(SourceDocument, UUID(event["source_document_id"]))
    assert source_doc is not None
    assert source_doc.trust_zone == "semi_trusted_tool"
    assert "pytest passed" in source_doc.content

    decision_result = await mcp_server._record_decision(
        run_id=run_id,
        decision="Use the compiler service from MCP prepare_task.",
        rationale="MCP must not duplicate compiler logic.",
        files=["app/mcp/server.py"],
        evidence="MCP must not duplicate compiler logic.",
    )
    decision = json.loads(decision_result[0].text)
    assert decision["component_id"]
    assert decision["claim_id"]

    blocker_result = await mcp_server._record_blocker(
        run_id=run_id,
        blocker="Runtime bridge waits on persistence tables.",
        severity="high",
        attempted_fix="Verified AgentRun and RunObservation tables exist.",
        evidence="Runtime bridge waits on persistence tables.",
    )
    blocker = json.loads(blocker_result[0].text)
    blocker_component = await db_session.get(Component, UUID(blocker["component_id"]))
    assert blocker_component is not None
    assert blocker_component.fact_type == "blocker"

    patch_result = await mcp_server._record_patch_summary(
        run_id=run_id,
        changed_files=["app/mcp/server.py", "tests/test_mcp.py"],
        summary="Added MCP runtime bridge tools.",
        tests_run=["pytest -q tests/test_mcp.py"],
    )
    patch = json.loads(patch_result[0].text)
    assert patch["source_document_id"]

    verify_result = await mcp_server._verify_context_item(
        component_id=decision["component_id"],
        claim_id=decision["claim_id"],
        verdict="verified",
        evidence="Decision was implemented in app/mcp/server.py.",
    )
    verified = json.loads(verify_result[0].text)
    assert verified["status"] == "active"
    verified_claim = await db_session.get(Claim, UUID(decision["claim_id"]))
    assert verified_claim.status == "active"

    close_result = await mcp_server._close_task(
        task_component_id=blocker["component_id"],
        task_claim_id=blocker["claim_id"],
        resolution="Persistence tables are available and writes are covered.",
        commit="abc123",
    )
    closed = json.loads(close_result[0].text)
    assert closed["status"] == "resolved"
    closed_claim = await db_session.get(Claim, UUID(blocker["claim_id"]))
    assert closed_claim.status == "resolved"

    decisions = (
        await db_session.scalars(select(Component).where(Component.fact_type == "decision"))
    ).all()
    assert any(item.source_document_id for item in decisions)
