from __future__ import annotations

import json
from uuid import uuid4

import pytest
from sqlalchemy import update

from app.config import settings
from app.models import SourceDocument, Workspace, WorkspaceGoal
from app.services import context_digest_cache as digest_cache_module
from app.services.access import AccessScope
from app.services.context_digest_cache import (
    ContextDigestCache,
    context_digest_cache,
    context_digest_cache_key,
)


@pytest.fixture(autouse=True)
def _clear_context_digest_cache():
    context_digest_cache.clear()
    yield
    context_digest_cache.clear()


async def _workspace(db_session, label: str) -> Workspace:
    workspace = Workspace(
        id=uuid4(),
        name=label,
        slug=f"{label.lower().replace(' ', '-')}-{uuid4().hex}",
    )
    db_session.add(workspace)
    await db_session.flush()
    return workspace


def _digest_path(workspace_id) -> str:
    return f"/api/context/digest?workspace_id={workspace_id}"


def test_cache_has_a_hard_ttl_and_does_not_store_after_invalidation(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(digest_cache_module, "monotonic", lambda: clock[0])
    cache = ContextDigestCache(ttl_seconds=2, max_entries=2)
    key = ("digest",)

    cache.set(key, {"value": "fresh"})
    clock[0] = 101.0
    assert cache.get(key) == {"value": "fresh"}
    clock[0] = 102.0
    assert cache.get(key) is None

    generation = cache.generation
    cache.clear()
    cache.set(key, {"value": "stale"}, expected_generation=generation)
    assert cache.get(key) is None


def test_cache_key_separates_permission_scopes():
    workspace_id = uuid4()
    alice = AccessScope("alice", frozenset({workspace_id}))
    bob = AccessScope("bob", frozenset({workspace_id}))

    assert context_digest_cache_key(
        access_scope=alice,
        workspace_id=workspace_id,
        limit=50,
    ) != context_digest_cache_key(
        access_scope=bob,
        workspace_id=workspace_id,
        limit=50,
    )


async def test_explicit_workspace_digest_reports_miss_then_hit(client, db_session):
    workspace = await _workspace(db_session, "Digest cache hit")

    first = await client.get(_digest_path(workspace.id))
    second = await client.get(_digest_path(workspace.id))

    assert first.status_code == 200
    assert first.headers["X-Context-Digest-Cache"] == "MISS"
    assert second.status_code == 200
    assert second.headers["X-Context-Digest-Cache"] == "HIT"
    assert second.json() == first.json()


async def test_orm_flush_invalidates_cached_workspace_digest(client, db_session):
    workspace = await _workspace(db_session, "Digest flush invalidation")
    assert (
        await client.get(_digest_path(workspace.id))
    ).headers["X-Context-Digest-Cache"] == "MISS"
    assert (
        await client.get(_digest_path(workspace.id))
    ).headers["X-Context-Digest-Cache"] == "HIT"

    db_session.add(SourceDocument(
        workspace_id=workspace.id,
        source_type="local",
        external_id="new-pending-source",
        content="A newly observed source must invalidate the cached digest.",
        metadata_json="{}",
    ))
    await db_session.flush()

    refreshed = await client.get(_digest_path(workspace.id))

    assert refreshed.status_code == 200
    assert refreshed.headers["X-Context-Digest-Cache"] == "MISS"
    assert refreshed.json()["scope"]["pending_source_count"] == 1


async def test_direct_orm_write_invalidates_cached_workspace_digest(client, db_session):
    workspace = await _workspace(db_session, "Digest direct write")
    await client.get(_digest_path(workspace.id))
    cached = await client.get(_digest_path(workspace.id))
    assert cached.headers["X-Context-Digest-Cache"] == "HIT"

    await db_session.execute(
        update(Workspace)
        .where(Workspace.id == workspace.id)
        .values(name="Digest direct write updated")
    )

    refreshed = await client.get(_digest_path(workspace.id))

    assert refreshed.status_code == 200
    assert refreshed.headers["X-Context-Digest-Cache"] == "MISS"


async def test_digest_without_workspace_bypasses_cache(client):
    first = await client.get("/api/context/digest")
    second = await client.get("/api/context/digest")

    assert first.status_code == 200
    assert first.headers["X-Context-Digest-Cache"] == "BYPASS"
    assert second.status_code == 200
    assert second.headers["X-Context-Digest-Cache"] == "BYPASS"


async def test_unknown_workspace_returns_only_not_found(client):
    response = await client.get(_digest_path(uuid4()))

    assert response.status_code == 404
    assert response.json() == {"detail": "Workspace not found"}
    assert "X-Context-Digest-Cache" not in response.headers


async def test_unauthorized_workspace_cannot_receive_a_cached_digest(
    client,
    db_session,
    monkeypatch,
):
    protected = await _workspace(db_session, "Protected digest")
    allowed = await _workspace(db_session, "Allowed digest")
    marker = f"private-goal-{uuid4().hex}"
    db_session.add(WorkspaceGoal(
        workspace_id=protected.id,
        title=marker,
        source_kind="user_selected",
        selected_by="test",
    ))
    await db_session.flush()

    populated = await client.get(_digest_path(protected.id))
    assert populated.status_code == 200
    assert populated.headers["X-Context-Digest-Cache"] == "MISS"
    assert populated.json()["current_goal"]["title"] == marker

    monkeypatch.setattr(
        settings,
        "principal_api_keys",
        json.dumps({
            "allowed-token": {
                "principal_id": "allowed-user",
                "workspace_ids": [str(allowed.id)],
            },
        }),
        raising=False,
    )
    denied = await client.get(
        _digest_path(protected.id),
        headers={"X-DaemonState-API-Key": "allowed-token"},
    )

    assert denied.status_code == 404
    assert denied.json() == {"detail": "Workspace not found"}
    assert marker not in denied.text
    assert "X-Context-Digest-Cache" not in denied.headers
