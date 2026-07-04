from __future__ import annotations

import json
from types import SimpleNamespace
from uuid import UUID, uuid4

from sqlalchemy import select, text

from app.models import (
    Claim,
    Component,
    ContextPack,
    ContextPackItem,
    SourceDocument,
    Workspace,
)


def _patch_mcp_session(monkeypatch, db_session):
    from app.mcp import server as mcp_server

    class TestSessionContext:
        async def __aenter__(self):
            return db_session

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(mcp_server, "AsyncSessionLocal", lambda: TestSessionContext())
    return mcp_server


async def _insert_context_pack(
    session,
    *,
    pack_id,
    workspace_id,
    objective,
    target_model,
    token_budget,
    markdown,
    manifest,
    health_score=None,
):
    columns = {
        row[1]
        for row in (await session.execute(text("PRAGMA table_info(context_packs)"))).all()
    }
    if "repo_state_json" in columns:
        await session.execute(
            text(
                """
                INSERT INTO context_packs (
                    id,
                    workspace_id,
                    objective,
                    target_model,
                    token_budget,
                    pack_version,
                    health_score,
                    markdown,
                    manifest,
                    repo_state_json
                )
                VALUES (
                    :id,
                    :workspace_id,
                    :objective,
                    :target_model,
                    :token_budget,
                    :pack_version,
                    :health_score,
                    :markdown,
                    :manifest,
                    :repo_state_json
                )
                """
            ),
            {
                "id": _uuid_db_value(pack_id),
                "workspace_id": _uuid_db_value(workspace_id),
                "objective": objective,
                "target_model": target_model,
                "token_budget": token_budget,
                "pack_version": "context_pack.v2",
                "health_score": health_score,
                "markdown": markdown,
                "manifest": manifest,
                "repo_state_json": "{}",
            },
        )
        await session.flush()
        return

    pack = ContextPack(
        id=pack_id,
        workspace_id=workspace_id,
        objective=objective,
        target_model=target_model,
        token_budget=token_budget,
        pack_version="context_pack.v2",
        health_score=health_score,
        markdown=markdown,
        manifest=manifest,
    )
    session.add(pack)
    await session.flush()


async def _insert_context_pack_item(
    session,
    *,
    context_pack_id,
    score,
    inclusion_reason,
    token_cost,
    item_type="component",
):
    columns = {
        row[1]
        for row in (await session.execute(text("PRAGMA table_info(context_pack_items)"))).all()
    }
    if "item_type" in columns:
        await session.execute(
            text(
                """
                INSERT INTO context_pack_items (
                    id,
                    context_pack_id,
                    score,
                    inclusion_reason,
                    token_cost,
                    item_type
                )
                VALUES (
                    :id,
                    :context_pack_id,
                    :score,
                    :inclusion_reason,
                    :token_cost,
                    :item_type
                )
                """
            ),
            {
                "id": uuid4().hex,
                "context_pack_id": _uuid_db_value(context_pack_id),
                "score": score,
                "inclusion_reason": inclusion_reason,
                "token_cost": token_cost,
                "item_type": item_type,
            },
        )
        await session.flush()
        return

    session.add(
        ContextPackItem(
            context_pack_id=context_pack_id,
            score=score,
            inclusion_reason=inclusion_reason,
            token_cost=token_cost,
        )
    )
    await session.flush()


def _uuid_db_value(value):
    parsed = value if isinstance(value, UUID) else UUID(str(value))
    return parsed.hex


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


async def test_prepare_task_reports_compiler_unavailable(db_session, monkeypatch, tmp_path):
    workspace = Workspace(id=uuid4(), name="MCP Missing", slug=f"mcp-missing-{uuid4()}")
    db_session.add(workspace)
    await db_session.flush()

    mcp_server = _patch_mcp_session(monkeypatch, db_session)
    monkeypatch.setattr(mcp_server, "_ContextCompiler", None)
    monkeypatch.setattr(
        mcp_server,
        "_CONTEXT_COMPILER_IMPORT_ERROR",
        ModuleNotFoundError("app.services.context_compiler"),
    )

    result = await mcp_server._prepare_task(
        "fix app.py and run pytest -q",
        workspace_id=str(workspace.id),
        repo_path=str(tmp_path),
        target_model="qwen2.5-coder-7b",
        token_budget=2000,
    )
    data = json.loads(result[0].text)

    assert data["ok"] is False
    assert data["error"]["code"] == "compiler_unavailable"


async def test_prepare_task_calls_compiler_and_persists_pack(db_session, monkeypatch, tmp_path):
    workspace = Workspace(id=uuid4(), name="MCP", slug=f"mcp-{uuid4()}")
    db_session.add(workspace)
    await db_session.flush()
    (tmp_path / "app.py").write_text("def handler():\n    return True\n")

    mcp_server = _patch_mcp_session(monkeypatch, db_session)

    class FakeCompiler:
        def __init__(self, session):
            self.session = session

        async def compile_context_pack(
            self,
            goal,
            *,
            workspace_id,
            repo_path,
            target_model,
            token_budget,
        ):
            pack_id = uuid4()
            markdown = "# Objective\n\nfix app.py and run pytest -q\n"
            manifest = {
                "schema_version": "context_pack.v2",
                "context_pack_id": str(pack_id),
                "objective": goal,
                "created_at": "2026-07-04T00:00:00Z",
                "workspace_id": workspace_id,
                "target_model": {
                    "name": target_model,
                    "profile": "small_coder_model",
                    "context_budget_tokens": token_budget,
                },
                "repo_state": {
                    "repo_path": repo_path,
                    "branch": None,
                    "base_commit": None,
                    "head_commit": None,
                    "dirty": False,
                    "changed_files": [],
                    "untracked_files": [],
                    "relevant_files": [
                        {
                            "path": "app.py",
                            "reason": "goal_file_match",
                            "exists": True,
                            "sha256": None,
                        }
                    ],
                    "test_files": [],
                    "manifest_files": [],
                    "env_files": [],
                    "last_indexed_at": None,
                },
                "selected_context": [
                    {
                        "id": "file:app.py",
                        "item_type": "file",
                        "title": "app.py",
                        "summary": "Goal mentions app.py.",
                        "status": "active",
                        "temporal": "current",
                        "score": 0.9,
                        "token_cost": 32,
                        "inclusion_reason": "goal_file_match",
                        "trust_zone": "trusted_repo",
                        "confidence": 0.9,
                        "authority_weight": 0.85,
                        "prompt_injection_risk_score": 0.0,
                        "claim_id": None,
                        "component_id": None,
                        "evidence_span_id": None,
                        "source_document_id": None,
                        "citations": [
                            {
                                "citation_id": "E1",
                                "source_document_id": None,
                                "evidence_span_id": None,
                                "source_type": "repo_file",
                                "source_url": "app.py",
                                "quote": "Goal file selected by repo inspection.",
                                "trust_zone": "trusted_repo",
                            }
                        ],
                        "files": ["app.py"],
                        "relationships": [],
                        "conflict_state": "none",
                    }
                ],
                "excluded_context": [],
                "risks": [],
                "verification": {
                    "commands": [
                        {
                            "id": "V1",
                            "command": "pytest -q",
                            "cwd": repo_path,
                            "purpose": "Run tests.",
                            "required": True,
                            "expected": "exit_code == 0",
                        }
                    ],
                    "acceptance_criteria": [
                        {
                            "id": "AC1",
                            "text": "Tests pass.",
                            "evidence_required": "test_result",
                        }
                    ],
                },
                "stop_conditions": [],
                "rendering": {
                    "markdown_sha256": "sha256-markdown",
                    "estimated_tokens": 12,
                    "estimation_method": "chars_div_4.v1",
                },
            }
            await _insert_context_pack(
                self.session,
                pack_id=pack_id,
                workspace_id=UUID(workspace_id),
                objective=goal,
                target_model=target_model,
                token_budget=token_budget,
                health_score=0.78,
                markdown=markdown,
                manifest=json.dumps(manifest, sort_keys=True),
            )
            await _insert_context_pack_item(
                self.session,
                context_pack_id=pack_id,
                score=0.9,
                inclusion_reason="goal_file_match",
                token_cost=32,
                item_type="file",
            )
            return SimpleNamespace(
                context_pack_id=pack_id,
                schema_version="context_pack.v2",
                markdown=markdown,
                manifest=manifest,
                health_score=0.78,
            )

    monkeypatch.setattr(mcp_server, "_ContextCompiler", FakeCompiler)
    monkeypatch.setattr(mcp_server, "_CONTEXT_COMPILER_IMPORT_ERROR", None)
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
    assert "# Objective" in data["markdown"]
    pack = await db_session.get(ContextPack, UUID(data["context_pack_id"]))
    assert pack is not None
    assert pack.pack_version == "context_pack.v2"
    assert json.loads(pack.manifest) == data["manifest"]
    assert pack.markdown == data["markdown"]
    items = (
        await db_session.scalars(
            select(ContextPackItem).where(ContextPackItem.context_pack_id == pack.id)
        )
    ).all()
    assert len(items) == len(data["manifest"]["selected_context"])


async def test_mcp_write_tool_errors_are_structured(db_session, monkeypatch):
    mcp_server = _patch_mcp_session(monkeypatch, db_session)

    invalid_run = await mcp_server._record_agent_event(
        run_id="not-a-uuid",
        event_type="test",
        content="pytest failed",
    )
    invalid_data = json.loads(invalid_run[0].text)
    assert invalid_data["ok"] is False
    assert invalid_data["error"]["code"] == "invalid_input"

    missing_pack = await mcp_server._record_agent_run_start(
        tool="codex",
        model="qwen2.5-coder-7b",
        branch="main",
        base_commit="abc123",
        objective="missing pack",
        context_pack_id=str(uuid4()),
    )
    missing_pack_data = json.loads(missing_pack[0].text)
    assert missing_pack_data["ok"] is False
    assert missing_pack_data["error"]["code"] == "context_pack_not_found"

    missing_run = await mcp_server._record_agent_event(
        run_id=str(uuid4()),
        event_type="test",
        content="pytest failed",
    )
    missing_run_data = json.loads(missing_run[0].text)
    assert missing_run_data["ok"] is False
    assert missing_run_data["error"]["code"] == "agent_run_not_found"


async def test_mcp_runtime_write_tools_persist_source_backed_loop(
    db_session,
    monkeypatch,
):
    workspace = Workspace(id=uuid4(), name="Runtime", slug=f"runtime-{uuid4()}")
    pack_id = uuid4()
    db_session.add(workspace)
    await db_session.flush()
    await _insert_context_pack(
        db_session,
        pack_id=pack_id,
        workspace_id=workspace.id,
        objective="finish runtime bridge",
        target_model="qwen2.5-coder-7b",
        token_budget=2000,
        markdown="# Context Pack v2",
        manifest=json.dumps({"schema_version": "context_pack.v2"}),
    )
    pack = await db_session.get(ContextPack, pack_id)
    assert pack is not None

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
