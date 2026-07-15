from __future__ import annotations

import hashlib
import json
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select

from app.models import CodeFile, Connector, SourceDocument, Workspace
from app.services.credentials import dump_credentials
from app.services.live_retrieval import LiveRetrievalError, retrieve_live_context
from app.services.query import QueryService


async def test_local_live_retrieval_uses_current_files_inside_the_indexed_scope(db_session, tmp_path):
    workspace = Workspace(id=uuid4(), name="Live local", slug=f"live-local-{uuid4().hex[:8]}")
    db_session.add(workspace)
    (tmp_path / ".git").mkdir()
    source = tmp_path / "app.py"
    source.write_text("def prepare_context():\n    return 'source backed context'\n", encoding="utf-8")
    secret = tmp_path / ".env"
    secret.write_text("CONTEXT_SECRET=source backed context\n", encoding="utf-8")
    db_session.add_all([
        CodeFile(
            workspace_id=workspace.id,
            repo_root=str(tmp_path),
            path="app.py",
            identity_key=hashlib.sha256(f"{workspace.id}:app.py".encode()).hexdigest(),
            language="python",
            sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
            size=source.stat().st_size,
        ),
        CodeFile(
            workspace_id=workspace.id,
            repo_root=str(tmp_path),
            path=".env",
            identity_key=hashlib.sha256(f"{workspace.id}:.env".encode()).hexdigest(),
            sha256=hashlib.sha256(secret.read_bytes()).hexdigest(),
            size=secret.stat().st_size,
        ),
    ])
    await db_session.flush()

    lanes = await retrieve_live_context(
        db_session,
        workspace_id=workspace.id,
        question="Where is source backed context prepared?",
        sources=["local_repo"],
    )

    assert lanes[0].status == "checked_live"
    assert [item.path for item in lanes[0].items] == ["app.py"]
    assert lanes[0].items[0].line == 2
    assert lanes[0].items[0].sha256 == hashlib.sha256(source.read_bytes()).hexdigest()

    source.write_text("def prepare_context():\n    return 'changed outside the index'\n", encoding="utf-8")
    changed = await retrieve_live_context(
        db_session,
        workspace_id=workspace.id,
        question="Where is changed outside the index?",
        sources=["local_repo"],
    )
    assert [item.path for item in changed[0].items] == ["app.py"]
    assert changed[0].items[0].sha256 == hashlib.sha256(source.read_bytes()).hexdigest()


async def test_live_retrieval_rejects_unsupported_lanes_without_fallback(db_session):
    with pytest.raises(LiveRetrievalError) as exc_info:
        await retrieve_live_context(
            db_session,
            workspace_id=uuid4(),
            question="latest decision",
            sources=["slack"],
        )

    assert exc_info.value.code == "live_source_unsupported"


async def test_github_live_result_is_persisted_before_it_is_returned(db_session):
    workspace = Workspace(id=uuid4(), name="Live GitHub", slug=f"live-github-{uuid4().hex[:8]}")
    connector = Connector(
        workspace_id=workspace.id,
        connector_type="github",
        status="connected",
        config_json=json.dumps({
            "auth_mode": "manual_token",
            "repositories": ["acme/context"],
        }),
        credentials_json=dump_credentials({"access_token": "test-token"}),
    )
    db_session.add_all([workspace, connector])
    await db_session.flush()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer test-token"
        assert "repo%3Aacme%2Fcontext" in str(request.url)
        return httpx.Response(200, json={"items": [{
            "number": 42,
            "title": "Preserve context provenance",
            "body": "The task packet must retain its source evidence.",
            "state": "open",
            "updated_at": "2026-07-15T08:00:00Z",
            "html_url": "https://github.com/acme/context/issues/42",
            "user": {"login": "founder"},
        }]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        lanes = await retrieve_live_context(
            db_session,
            workspace_id=workspace.id,
            question="context provenance",
            sources=["github"],
            http_client=http_client,
        )

    assert len(lanes[0].items) == 1
    returned = lanes[0].items[0]
    document = await db_session.scalar(
        select(SourceDocument).where(SourceDocument.id == UUID(returned.source_document_id))
    )
    assert document is not None
    assert document.external_id == "github:acme/context:issue:42"
    assert document.content_sha256
    assert document.processed_at is not None


async def test_github_live_auth_error_is_explicit(db_session):
    workspace = Workspace(
        id=uuid4(),
        name="Bad GitHub auth",
        slug=f"bad-github-{uuid4().hex[:8]}",
    )
    connector = Connector(
        workspace_id=workspace.id,
        connector_type="github",
        status="connected",
        config_json=json.dumps({
            "auth_mode": "manual_token",
            "repositories": ["acme/context"],
        }),
        credentials_json=dump_credentials({"access_token": "expired"}),
    )
    db_session.add_all([workspace, connector])
    await db_session.flush()

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _request: httpx.Response(401, json={}))
    ) as http_client:
        with pytest.raises(LiveRetrievalError) as exc_info:
            await retrieve_live_context(
                db_session,
                workspace_id=workspace.id,
                question="current issue",
                sources=["github"],
                http_client=http_client,
            )

    assert exc_info.value.code == "github_credentials_expired"


async def test_combined_github_network_failure_stays_visible_as_lane_error(db_session):
    workspace = Workspace(
        id=uuid4(), name="GitHub offline", slug=f"github-offline-{uuid4().hex[:8]}"
    )
    connector = Connector(
        workspace_id=workspace.id,
        connector_type="github",
        status="connected",
        config_json=json.dumps({
            "auth_mode": "manual_token",
            "repositories": ["acme/context"],
        }),
        credentials_json=dump_credentials({"access_token": "test-token"}),
    )
    db_session.add_all([workspace, connector])
    await db_session.flush()

    def fail_network(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(fail_network)
    ) as http_client:
        lanes = await retrieve_live_context(
            db_session,
            workspace_id=workspace.id,
            question="current issue",
            sources=["github"],
            http_client=http_client,
            fail_fast=False,
        )

    assert lanes[0].status == "error"
    assert lanes[0].error_code == "live_retrieval_failed"
    assert "offline" not in (lanes[0].error_message or "")


async def test_query_combined_mode_keeps_live_lane_errors_visible(db_session):
    workspace = Workspace(
        id=uuid4(), name="Combined", slug=f"combined-{uuid4().hex[:8]}"
    )
    db_session.add(workspace)
    await db_session.flush()

    result = await QueryService(db_session).query(
        "current decision",
        workspace_id=workspace.id,
        retrieval_mode="combined",
        live_sources=["slack"],
    )

    assert result.trace.retrieval_mode == "combined"
    assert result.live_lanes[0]["status"] == "error"
    assert result.live_lanes[0]["error_code"] == "live_source_unsupported"


async def test_query_api_live_mode_never_silently_falls_back(client, db_session):
    workspace = Workspace(id=uuid4(), name="Live API", slug=f"live-api-{uuid4().hex[:8]}")
    db_session.add(workspace)
    await db_session.flush()

    response = await client.post("/api/query", json={
        "question": "latest Slack decision",
        "workspace_id": str(workspace.id),
        "retrieval_mode": "live",
        "live_sources": ["slack"],
    })

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "live_source_unsupported"
