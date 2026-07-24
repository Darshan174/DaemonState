from __future__ import annotations

import hashlib
import json
from datetime import datetime
from uuid import uuid4

from app.config import settings
from app.models import CodeFile, SessionEvent, SourceDocument, WorkCheckpoint, Workspace
from app.services.source_revisions import ingest_source_document_revision


async def _workspace(db_session) -> Workspace:
    workspace = Workspace(
        id=uuid4(),
        name="Now payload filters",
        slug=f"now-payload-filters-{uuid4().hex}",
    )
    db_session.add(workspace)
    await db_session.flush()
    db_session.add(CodeFile(
        workspace_id=workspace.id,
        repo_root="/workspace/now-filter-project",
        path="app.py",
        identity_key=uuid4().hex * 2,
        language="python",
        sha256="a" * 64,
        size=10,
    ))
    await db_session.flush()
    return workspace


async def _session(
    db_session,
    workspace: Workspace,
    *,
    provider: str,
    session_id: str,
    occurred_at: datetime,
    checkpoint: bool = False,
    allowed_principal_ids: list[str] | None = None,
    sequence_number: int = 1,
    content: str | None = None,
    source_key: str | None = None,
) -> tuple[SourceDocument, SessionEvent, WorkCheckpoint | None]:
    content = content or f"Continue the scoped work for {session_id}."
    source_key = source_key or session_id
    metadata = {
        "tool": provider,
        "session_id": session_id,
        "cwd": "/workspace/now-filter-project",
    }
    if allowed_principal_ids is None:
        document = SourceDocument(
            workspace_id=workspace.id,
            source_type="agent_session",
            external_id=f"{provider}:session:{source_key}",
            content=content,
            metadata_json=json.dumps(metadata),
        )
        db_session.add(document)
        await db_session.flush()
    else:
        revision = await ingest_source_document_revision(
            db_session,
            workspace_id=workspace.id,
            source_type="agent_session",
            external_id=f"{provider}:session:{source_key}",
            content=content,
            metadata_json=metadata,
            visibility_scope="restricted",
            permission_source="test",
            allowed_principal_ids=allowed_principal_ids,
        )
        document = revision.document

    event = SessionEvent(
        workspace_id=workspace.id,
        source_document_id=document.id,
        provider=provider,
        session_id=session_id,
        provider_event_id=f"{provider}:{session_id}:{source_key}:request",
        sequence_number=sequence_number,
        event_type="user_request",
        role="user",
        occurred_at=occurred_at,
        content=content,
        payload_json="{}",
        content_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
    )
    db_session.add(event)
    await db_session.flush()

    saved = None
    if checkpoint:
        saved = WorkCheckpoint(
            workspace_id=workspace.id,
            source_document_id=document.id,
            provider=provider,
            session_id=session_id,
            boundary_event_id=event.id,
            trigger="manual",
            capture_status="incomplete",
            continuation_status="review_required",
            payload_json="{}",
            payload_sha256=hashlib.sha256(b"{}").hexdigest(),
        )
        db_session.add(saved)
        await db_session.flush()
    return document, event, saved


async def test_checkpoint_filter_is_applied_before_limit_and_normalizes_claude_alias(
    client,
    db_session,
) -> None:
    workspace = await _workspace(db_session)
    _, _, matching = await _session(
        db_session,
        workspace,
        provider="claude_code",
        session_id="target-session",
        occurred_at=datetime(2026, 7, 20, 9, 0),
        checkpoint=True,
    )
    _, _, newer_other = await _session(
        db_session,
        workspace,
        provider="codex",
        session_id="newer-session",
        occurred_at=datetime(2026, 7, 21, 9, 0),
        checkpoint=True,
    )

    scoped = await client.get("/api/checkpoints", params={
        "workspace_id": str(workspace.id),
        "provider": "claude",
        "session_id": "target-session",
        "limit": 1,
    })
    unscoped = await client.get("/api/checkpoints", params={
        "workspace_id": str(workspace.id),
        "limit": 10,
    })

    assert scoped.status_code == 200
    assert [item["id"] for item in scoped.json()["checkpoints"]] == [str(matching.id)]
    assert scoped.json()["checkpoints"][0]["provider"] == "claude"
    assert unscoped.status_code == 200
    assert [item["id"] for item in unscoped.json()["checkpoints"]] == [
        str(newer_other.id),
        str(matching.id),
    ]


async def test_session_continuity_filter_returns_only_the_requested_ledger_and_aliases_provider(
    client,
    db_session,
) -> None:
    workspace = await _workspace(db_session)
    await _session(
        db_session,
        workspace,
        provider="claude",
        session_id="target-session",
        occurred_at=datetime(2026, 7, 20, 9, 0),
    )
    await _session(
        db_session,
        workspace,
        provider="codex",
        session_id="other-session",
        occurred_at=datetime(2026, 7, 21, 9, 0),
    )

    scoped = await client.get("/api/session-continuity", params={
        "workspace_id": str(workspace.id),
        "provider": "claude_code",
        "session_id": "target-session",
    })
    unscoped = await client.get("/api/session-continuity", params={
        "workspace_id": str(workspace.id),
    })

    assert scoped.status_code == 200
    assert [
        (item["provider"], item["session_id"])
        for item in scoped.json()["sessions"]
    ] == [("claude", "target-session")]
    assert unscoped.status_code == 200
    assert {
        (item["provider"], item["session_id"])
        for item in unscoped.json()["sessions"]
    } == {
        ("claude", "target-session"),
        ("codex", "other-session"),
    }


async def test_now_payload_filters_require_provider_and_session_id_together(
    client,
    db_session,
) -> None:
    workspace = await _workspace(db_session)

    for path in ("/api/checkpoints", "/api/session-continuity"):
        provider_only = await client.get(path, params={
            "workspace_id": str(workspace.id),
            "provider": "codex",
        })
        session_only = await client.get(path, params={
            "workspace_id": str(workspace.id),
            "session_id": "target-session",
        })
        whitespace = await client.get(path, params={
            "workspace_id": str(workspace.id),
            "provider": " ",
            "session_id": " ",
        })

        assert provider_only.status_code == 422
        assert provider_only.json()["detail"] == (
            "provider and session_id must be provided together"
        )
        assert session_only.status_code == 422
        assert session_only.json()["detail"] == (
            "provider and session_id must be provided together"
        )
        assert whitespace.status_code == 422
        assert whitespace.json()["detail"] == (
            "provider and session_id must be non-empty"
        )


async def test_scoped_now_payloads_do_not_leak_restricted_session_evidence(
    client,
    db_session,
    monkeypatch,
) -> None:
    workspace = await _workspace(db_session)
    _, _, alice_checkpoint = await _session(
        db_session,
        workspace,
        provider="codex",
        session_id="alice-session",
        occurred_at=datetime(2026, 7, 20, 9, 0),
        checkpoint=True,
        allowed_principal_ids=["alice"],
    )
    await _session(
        db_session,
        workspace,
        provider="codex",
        session_id="bob-session",
        occurred_at=datetime(2026, 7, 21, 9, 0),
        checkpoint=True,
        allowed_principal_ids=["bob"],
    )
    monkeypatch.setattr(
        settings,
        "principal_api_keys",
        json.dumps({
            "alice-token": {
                "principal_id": "alice",
                "workspace_ids": [str(workspace.id)],
            },
        }),
        raising=False,
    )
    headers = {"X-Context-Engine-API-Key": "alice-token"}

    alice_continuity = await client.get("/api/session-continuity", params={
        "workspace_id": str(workspace.id),
        "provider": "codex",
        "session_id": "alice-session",
    }, headers=headers)
    bob_continuity = await client.get("/api/session-continuity", params={
        "workspace_id": str(workspace.id),
        "provider": "codex",
        "session_id": "bob-session",
    }, headers=headers)
    alice_checkpoints = await client.get("/api/checkpoints", params={
        "workspace_id": str(workspace.id),
        "provider": "codex",
        "session_id": "alice-session",
    }, headers=headers)
    bob_checkpoints = await client.get("/api/checkpoints", params={
        "workspace_id": str(workspace.id),
        "provider": "codex",
        "session_id": "bob-session",
    }, headers=headers)

    assert alice_continuity.status_code == 200
    assert [
        item["session_id"] for item in alice_continuity.json()["sessions"]
    ] == ["alice-session"]
    assert bob_continuity.status_code == 200
    assert bob_continuity.json() == {"sessions": []}
    assert alice_checkpoints.status_code == 200
    assert [
        item["id"] for item in alice_checkpoints.json()["checkpoints"]
    ] == [str(alice_checkpoint.id)]
    assert bob_checkpoints.status_code == 200
    assert bob_checkpoints.json() == {"checkpoints": []}


async def test_same_session_private_events_do_not_change_visible_ledger_or_tip(
    client,
    db_session,
    monkeypatch,
) -> None:
    workspace = await _workspace(db_session)
    _, alice_event, alice_checkpoint = await _session(
        db_session,
        workspace,
        provider="codex",
        session_id="shared-session",
        source_key="alice-source",
        sequence_number=1,
        content="Build the public-safe Now view.",
        occurred_at=datetime(2026, 7, 20, 9, 0),
        checkpoint=True,
        allowed_principal_ids=["alice"],
    )
    await _session(
        db_session,
        workspace,
        provider="codex",
        session_id="shared-session",
        source_key="bob-source",
        sequence_number=99,
        content="Bob private secret must never appear.",
        occurred_at=datetime(2026, 7, 21, 9, 0),
        allowed_principal_ids=["bob"],
    )
    monkeypatch.setattr(
        settings,
        "principal_api_keys",
        json.dumps({
            "alice-token": {
                "principal_id": "alice",
                "workspace_ids": [str(workspace.id)],
            },
        }),
        raising=False,
    )
    headers = {"X-Context-Engine-API-Key": "alice-token"}
    params = {
        "workspace_id": str(workspace.id),
        "provider": "codex",
        "session_id": "shared-session",
    }

    continuity = await client.get(
        "/api/session-continuity",
        params=params,
        headers=headers,
    )
    checkpoints = await client.get(
        "/api/checkpoints",
        params=params,
        headers=headers,
    )

    assert continuity.status_code == 200
    ledger = continuity.json()["sessions"][0]
    assert ledger["coverage"] == {
        "event_count": 1,
        "first_sequence_number": 1,
        "last_sequence_number": 1,
        "post_compaction_context_observable": False,
    }
    assert "Bob private secret" not in json.dumps(ledger)
    assert checkpoints.status_code == 200
    checkpoint = checkpoints.json()["checkpoints"][0]
    assert checkpoint["id"] == str(alice_checkpoint.id)
    assert checkpoint["boundary"]["session_tip_sequence"] == 1
    assert checkpoint["boundary"]["session_tip_at"].startswith(
        alice_event.occurred_at.isoformat()
    )


async def test_hidden_checkpoints_do_not_consume_visible_result_limit(
    client,
    db_session,
    monkeypatch,
) -> None:
    workspace = await _workspace(db_session)
    _, _, alice_checkpoint = await _session(
        db_session,
        workspace,
        provider="codex",
        session_id="alice-session",
        occurred_at=datetime(2026, 7, 20, 9, 0),
        checkpoint=True,
        allowed_principal_ids=["alice"],
    )
    for offset in range(3):
        await _session(
            db_session,
            workspace,
            provider="codex",
            session_id=f"bob-session-{offset}",
            occurred_at=datetime(2026, 7, 21, 9, offset),
            checkpoint=True,
            allowed_principal_ids=["bob"],
        )
    monkeypatch.setattr(
        settings,
        "principal_api_keys",
        json.dumps({
            "alice-token": {
                "principal_id": "alice",
                "workspace_ids": [str(workspace.id)],
            },
        }),
        raising=False,
    )

    response = await client.get(
        "/api/checkpoints",
        params={"workspace_id": str(workspace.id), "limit": 1},
        headers={"X-Context-Engine-API-Key": "alice-token"},
    )

    assert response.status_code == 200
    assert [
        item["id"] for item in response.json()["checkpoints"]
    ] == [str(alice_checkpoint.id)]
