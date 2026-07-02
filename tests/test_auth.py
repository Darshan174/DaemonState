from __future__ import annotations


async def test_api_routes_are_open_when_server_api_key_is_not_configured(client):
    response = await client.get("/api/workspaces")

    assert response.status_code == 200


async def test_api_routes_require_key_when_server_api_key_is_configured(client, monkeypatch):
    monkeypatch.setattr("app.config.settings.server_api_key", "server-secret", raising=False)

    missing = await client.get("/api/workspaces")
    wrong = await client.get("/api/workspaces", headers={"X-Context-Engine-API-Key": "wrong"})
    correct = await client.get("/api/workspaces", headers={"X-Context-Engine-API-Key": "server-secret"})

    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert correct.status_code == 200


async def test_api_key_auth_accepts_bearer_token_and_leaves_health_open(client, monkeypatch):
    monkeypatch.setattr("app.config.settings.server_api_key", "server-secret", raising=False)

    health = await client.get("/health")
    api = await client.get("/api/workspaces", headers={"Authorization": "Bearer server-secret"})

    assert health.status_code == 200
    assert api.status_code == 200


async def test_api_rate_limit_is_disabled_by_default(client):
    first = await client.get("/api/workspaces")
    second = await client.get("/api/workspaces")

    assert first.status_code == 200
    assert second.status_code == 200


async def test_api_rate_limit_returns_429_for_api_routes_only(client, monkeypatch):
    monkeypatch.setattr("app.config.settings.api_rate_limit_per_minute", 1, raising=False)

    first = await client.get("/api/workspaces")
    limited = await client.get("/api/workspaces")
    health = await client.get("/health")

    assert first.status_code == 200
    assert limited.status_code == 429
    assert limited.headers["Retry-After"]
    assert health.status_code == 200


async def test_readiness_reports_database_and_safe_config_flags(client, monkeypatch):
    monkeypatch.setattr("app.config.settings.server_api_key", "server-secret", raising=False)
    monkeypatch.setattr("app.config.settings.encryption_key", "not-a-real-fernet-key", raising=False)
    monkeypatch.setattr("app.config.settings.api_rate_limit_per_minute", 42, raising=False)

    response = await client.get("/health/ready")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert data["database"]
    assert data["api_auth_enabled"] is True
    assert data["api_rate_limit_per_minute"] == 42
    assert data["credential_encryption_enabled"] is True
    assert "not-a-real-fernet-key" not in response.text
