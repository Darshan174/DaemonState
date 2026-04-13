"""Tests for stable workspace routes, health endpoints, and POST /api/seed-demo."""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

import app.main as main_module
from app.api import workspaces as workspace_api
from app.database import get_db_session
from app.evals.demo_seed import SeedResult, SeedWorkspaceNotFoundError
from app.main import app
from sqlalchemy.exc import IntegrityError


# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture
async def admin_client():
    """Lightweight client without DB session override — for monkeypatch tests."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


# ── Workspace CRUD ───────────────────────────────────────────────────────


class TestWorkspaceEndpoints:
    async def test_create_workspace(self, client):
        resp = await client.post(
            "/api/workspaces",
            json={
                "name": "Acme Demo",
                "description": "Local workspace bootstrap test",
            },
        )

        assert resp.status_code == 201
        body = resp.json()
        assert body["name"] == "Acme Demo"
        assert body["description"] == "Local workspace bootstrap test"
        assert "id" in body

    async def test_list_workspaces(self, client):
        created = await client.post(
            "/api/workspaces",
            json={"name": "Listed Workspace"},
        )
        assert created.status_code == 201

        resp = await client.get("/api/workspaces")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)
        assert any(item["name"] == "Listed Workspace" for item in body)

    async def test_get_workspace(self, client):
        created = await client.post(
            "/api/workspaces",
            json={"name": "Fetchable Workspace"},
        )
        workspace_id = created.json()["id"]

        resp = await client.get(f"/api/workspaces/{workspace_id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == workspace_id
        assert body["name"] == "Fetchable Workspace"

    async def test_get_missing_workspace_returns_404(self, client):
        resp = await client.get(f"/api/workspaces/{uuid4()}")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Workspace not found"


# ── Health ───────────────────────────────────────────────────────────────


class DummyConnection:
    async def execute(self, _statement):
        return 1


class DummyConnectContext:
    def __init__(self, *, should_fail: bool = False):
        self.should_fail = should_fail

    async def __aenter__(self):
        if self.should_fail:
            raise RuntimeError("database unavailable")
        return DummyConnection()

    async def __aexit__(self, exc_type, exc, tb):
        return False


class DummyEngine:
    def __init__(self, *, should_fail: bool = False):
        self.should_fail = should_fail

    def connect(self):
        return DummyConnectContext(should_fail=self.should_fail)


class DummyRedisClient:
    def __init__(self, *, should_fail: bool = False):
        self.should_fail = should_fail
        self.closed = False

    async def ping(self):
        if self.should_fail:
            raise RuntimeError("redis unavailable")
        return True

    async def aclose(self):
        self.closed = True


class TestHealthEndpoints:
    async def test_health_returns_ok(self, admin_client):
        resp = await admin_client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    async def test_readiness_returns_ready_when_dependencies_are_healthy(self, admin_client, monkeypatch):
        monkeypatch.setattr(main_module, "engine", DummyEngine())
        monkeypatch.setattr(
            main_module.redis,
            "from_url",
            lambda *_args, **_kwargs: DummyRedisClient(),
        )

        resp = await admin_client.get("/health/ready")
        assert resp.status_code == 200
        assert resp.json() == {
            "status": "ready",
            "checks": {"database": "ok", "redis": "ok"},
        }

    async def test_readiness_returns_503_when_database_check_fails(self, admin_client, monkeypatch):
        monkeypatch.setattr(main_module, "engine", DummyEngine(should_fail=True))
        monkeypatch.setattr(
            main_module.redis,
            "from_url",
            lambda *_args, **_kwargs: DummyRedisClient(),
        )

        resp = await admin_client.get("/health/ready")
        assert resp.status_code == 503
        detail = resp.json()["detail"]
        assert detail["status"] == "degraded"
        assert detail["checks"] == {"database": "error", "redis": "ok"}
        assert "database" in detail["errors"]

    async def test_readiness_returns_503_when_redis_check_fails(self, admin_client, monkeypatch):
        monkeypatch.setattr(main_module, "engine", DummyEngine())
        monkeypatch.setattr(
            main_module.redis,
            "from_url",
            lambda *_args, **_kwargs: DummyRedisClient(should_fail=True),
        )

        resp = await admin_client.get("/health/ready")
        assert resp.status_code == 503
        detail = resp.json()["detail"]
        assert detail["status"] == "degraded"
        assert detail["checks"] == {"database": "ok", "redis": "error"}
        assert "redis" in detail["errors"]


# ── Seed Demo ────────────────────────────────────────────────────────────


class DummySession:
    async def rollback(self):
        pass


class TestSeedDemoAPI:
    async def test_seed_demo_uses_canonical_seed_when_payload_omitted(self, admin_client, monkeypatch):
        workspace_id = uuid4()

        async def fake_seed_demo_workspace(session, *, replace_existing=False):
            assert isinstance(session, DummySession)
            assert replace_existing is False
            return SeedResult(
                workspace_id=workspace_id,
                workspace_name="Acme Accuracy Demo",
                status="created",
                seeded_case_count=5,
            )

        async def fail_if_called(*args, **kwargs):
            raise AssertionError("Targeted seed path should not be used without workspace_id")

        app.dependency_overrides[get_db_session] = lambda: DummySession()
        monkeypatch.setattr(workspace_api, "seed_demo_workspace", fake_seed_demo_workspace)
        monkeypatch.setattr(workspace_api, "seed_demo_into_workspace", fail_if_called)

        response = await admin_client.post("/api/seed-demo", json={})

        assert response.status_code == 200
        body = response.json()
        assert body["workspaceId"] == str(workspace_id)
        assert body["workspaceName"] == "Acme Accuracy Demo"
        assert body["status"] == "created"
        assert body["defaultWorkspaceName"] == workspace_api.DEFAULT_WORKSPACE_NAME

    async def test_seed_demo_targets_selected_workspace(self, admin_client, monkeypatch):
        workspace_id = uuid4()

        async def fake_seed_demo_into_workspace(session, *, workspace_id):
            assert isinstance(session, DummySession)
            return SeedResult(
                workspace_id=workspace_id,
                workspace_name="Selected Workspace",
                status="created",
                seeded_case_count=5,
            )

        async def fail_if_called(*args, **kwargs):
            raise AssertionError("Canonical seed path should not be used when workspace_id is provided")

        app.dependency_overrides[get_db_session] = lambda: DummySession()
        monkeypatch.setattr(workspace_api, "seed_demo_into_workspace", fake_seed_demo_into_workspace)
        monkeypatch.setattr(workspace_api, "seed_demo_workspace", fail_if_called)

        response = await admin_client.post(
            "/api/seed-demo",
            json={"workspace_id": str(workspace_id)},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["workspaceId"] == str(workspace_id)
        assert body["workspaceName"] == "Selected Workspace"
        assert body["status"] == "created"

    async def test_seed_demo_accepts_workspace_id_alias(self, admin_client, monkeypatch):
        workspace_id = uuid4()

        async def fake_seed_demo_into_workspace(session, *, workspace_id):
            return SeedResult(
                workspace_id=workspace_id,
                workspace_name="Selected Workspace",
                status="existing",
                seeded_case_count=5,
            )

        app.dependency_overrides[get_db_session] = lambda: DummySession()
        monkeypatch.setattr(workspace_api, "seed_demo_into_workspace", fake_seed_demo_into_workspace)

        response = await admin_client.post(
            "/api/seed-demo",
            json={"workspaceId": str(workspace_id)},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["workspaceId"] == str(workspace_id)
        assert body["status"] == "existing"

    async def test_seed_demo_returns_404_for_missing_workspace(self, admin_client, monkeypatch):
        async def fake_seed_demo_into_workspace(session, *, workspace_id):
            raise SeedWorkspaceNotFoundError("Workspace not found")

        app.dependency_overrides[get_db_session] = lambda: DummySession()
        monkeypatch.setattr(workspace_api, "seed_demo_into_workspace", fake_seed_demo_into_workspace)

        response = await admin_client.post(
            "/api/seed-demo",
            json={"workspace_id": str(uuid4())},
        )

        assert response.status_code == 404
        assert response.json()["detail"] == "Workspace not found"

    async def test_seed_demo_returns_409_on_integrity_error(self, admin_client, monkeypatch):
        async def fake_seed_demo_workspace(session, *, replace_existing=False):
            raise IntegrityError("insert", {}, RuntimeError("duplicate"))

        app.dependency_overrides[get_db_session] = lambda: DummySession()
        monkeypatch.setattr(workspace_api, "seed_demo_workspace", fake_seed_demo_workspace)

        response = await admin_client.post("/api/seed-demo", json={})

        assert response.status_code == 409
        assert response.json()["detail"] == "Demo workspace is already being seeded by another request."

    async def test_seed_demo_rejects_unknown_fields(self, admin_client):
        response = await admin_client.post(
            "/api/seed-demo",
            json={"workspace_id": str(uuid4()), "unexpected": True},
        )

        assert response.status_code == 422
