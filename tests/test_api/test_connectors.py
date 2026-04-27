"""Tests for connector management endpoints."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
from sqlalchemy import select

import app.services.connector_service as connector_module
from app.connectors.base import NormalizedDocument
from app.models.connector import Connector, ConnectorAppConfig, ConnectorStatus
from app.models.source import ConnectorType, SourceDocument
from app.utils.crypto import decrypt_token, encrypt_token

# Generate a stable test key (valid Fernet key) — used across callback & sync tests
from cryptography.fernet import Fernet

_TEST_FERNET_KEY = Fernet.generate_key().decode()


# ── List / Sync / Disconnect (unchanged from Phase 2a) ────────────


class TestListConnectors:
    async def test_list_empty(self, client, workspace):
        resp = await client.get(
            "/api/connectors", params={"workspace_id": str(workspace.id)}
        )
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_list_with_connected_slack(self, client, workspace, db_session):
        conn = Connector(
            workspace_id=workspace.id,
            connector_type=ConnectorType.SLACK,
            status=ConnectorStatus.CONNECTED,
            config={"document_count": 42},
        )
        db_session.add(conn)
        await db_session.flush()

        resp = await client.get(
            "/api/connectors", params={"workspace_id": str(workspace.id)}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 1
        assert body[0]["connector_type"] == "slack"
        assert body[0]["status"] == "connected"
        assert body[0]["config"]["document_count"] == 42
        assert body[0]["workspace_id"] == str(workspace.id)
        assert body[0]["provider"] == "native"
        assert body[0]["provider_label"] == "Built in"

    async def test_list_missing_workspace_returns_404(self, client):
        resp = await client.get(
            "/api/connectors", params={"workspace_id": str(uuid4())}
        )
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Workspace not found"


class TestConnectorSetupStatus:
    async def test_slack_reports_missing_oauth_configuration(self, client, monkeypatch):
        monkeypatch.setattr(connector_module.settings, "slack_client_id", None)
        monkeypatch.setattr(connector_module.settings, "slack_client_secret", None)
        monkeypatch.setattr(connector_module.settings, "slack_redirect_uri", None)

        resp = await client.get("/api/connectors/setup-status")

        assert resp.status_code == 200
        slack_status = next(item for item in resp.json() if item["connector_type"] == "slack")
        assert slack_status["configured"] is False
        assert slack_status["missing"] == [
            "SLACK_CLIENT_ID",
            "SLACK_CLIENT_SECRET",
            "SLACK_REDIRECT_URI",
        ]
        assert slack_status["docs_url"] == "/docs/slack.md"

    async def test_slack_reports_configured_oauth(self, client, monkeypatch):
        monkeypatch.setattr(connector_module.settings, "slack_client_id", "client-id")
        monkeypatch.setattr(connector_module.settings, "slack_client_secret", "secret")
        monkeypatch.setattr(
            connector_module.settings,
            "slack_redirect_uri",
            "https://example.com/api/connectors/slack/callback",
        )

        resp = await client.get("/api/connectors/setup-status")

        assert resp.status_code == 200
        slack_status = next(item for item in resp.json() if item["connector_type"] == "slack")
        assert slack_status["configured"] is True
        assert slack_status["missing"] == []

    async def test_slack_reports_managed_connector_availability(
        self, client, monkeypatch
    ):
        monkeypatch.setattr(
            connector_module.settings,
            "slack_managed_install_url",
            "https://connect.example/slack/install",
        )
        monkeypatch.setattr(connector_module.settings, "slack_client_id", None)
        monkeypatch.setattr(connector_module.settings, "slack_client_secret", None)
        monkeypatch.setattr(connector_module.settings, "slack_redirect_uri", None)

        resp = await client.get("/api/connectors/setup-status")

        assert resp.status_code == 200
        slack_status = next(item for item in resp.json() if item["connector_type"] == "slack")
        assert slack_status["configured"] is False
        assert slack_status["managed_available"] is True
        assert slack_status["managed_install_url"] == "/api/connectors/slack/managed/install"

    async def test_saves_slack_oauth_settings_for_dashboard_setup(
        self, client, monkeypatch
    ):
        monkeypatch.setattr(connector_module.settings, "encryption_key", _TEST_FERNET_KEY)

        resp = await client.post(
            "/api/connectors/slack/oauth-settings",
            json={
                "client_id": "111.222",
                "client_secret": "secret",
                "redirect_uri": "https://context.example.com/api/connectors/slack/callback",
            },
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["configured"] is True
        assert body["client_id"] == "111.222"
        assert body["secret_configured"] is True
        assert body["redirect_uri"] == "https://context.example.com/api/connectors/slack/callback"
        assert body["source"] == "database"
        assert "client_secret" not in body

    async def test_slack_setup_status_uses_saved_dashboard_settings(
        self, client, db_session, monkeypatch
    ):
        monkeypatch.setattr(connector_module.settings, "encryption_key", _TEST_FERNET_KEY)
        monkeypatch.setattr(connector_module.settings, "slack_client_id", None)
        monkeypatch.setattr(connector_module.settings, "slack_client_secret", None)
        monkeypatch.setattr(connector_module.settings, "slack_redirect_uri", None)
        db_session.add(
            ConnectorAppConfig(
                connector_type=ConnectorType.SLACK,
                client_id="saved-client",
                client_secret_encrypted=encrypt_token("saved-secret"),
                redirect_uri="https://context.example.com/api/connectors/slack/callback",
                config={"configured_from": "dashboard"},
            )
        )
        await db_session.flush()

        resp = await client.get("/api/connectors/setup-status")

        assert resp.status_code == 200
        slack_status = next(item for item in resp.json() if item["connector_type"] == "slack")
        assert slack_status["configured"] is True
        assert slack_status["missing"] == []
        assert slack_status["source"] == "database"


class TestDisconnectConnector:
    async def test_disconnect_clears_token_and_marks_disconnected(
        self, client, workspace, db_session
    ):
        conn = Connector(
            workspace_id=workspace.id,
            connector_type=ConnectorType.NOTION,
            status=ConnectorStatus.CONNECTED,
            oauth_token_encrypted="enc-token-abc",
            config={"document_count": 10},
        )
        db_session.add(conn)
        await db_session.flush()

        resp = await client.delete(f"/api/connectors/{conn.id}")
        assert resp.status_code == 204

        await db_session.refresh(conn)
        assert conn.status == ConnectorStatus.DISCONNECTED
        assert conn.oauth_token_encrypted is None

    async def test_disconnect_missing_connector_returns_404(self, client):
        resp = await client.delete(f"/api/connectors/{uuid4()}")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Connector not found"


# ── Slack install (with Redis state) ──────────────────────────────


class _FakeRedis:
    """Minimal Redis stub for testing OAuth state storage."""

    def __init__(self):
        self.store: dict[str, str] = {}

    async def setex(self, key: str, ttl: int, value: str):
        self.store[key] = value

    async def getdel(self, key: str) -> str | None:
        return self.store.pop(key, None)

    async def aclose(self):
        pass


class TestSlackInstall:
    async def test_managed_install_redirects_to_hosted_connector(
        self, client, workspace, monkeypatch
    ):
        monkeypatch.setattr(
            connector_module.settings,
            "slack_managed_install_url",
            "https://connect.example/slack/install",
        )

        resp = await client.get(
            "/api/connectors/slack/managed/install",
            params={"workspace_id": str(workspace.id)},
            follow_redirects=False,
        )

        assert resp.status_code == 302
        assert resp.headers["location"] == (
            f"https://connect.example/slack/install?workspace_id={workspace.id}"
        )

    async def test_redirect_with_dashboard_saved_oauth_settings(
        self, client, workspace, db_session, monkeypatch
    ):
        monkeypatch.setattr(connector_module.settings, "encryption_key", _TEST_FERNET_KEY)
        monkeypatch.setattr(connector_module.settings, "slack_client_id", None)
        monkeypatch.setattr(connector_module.settings, "slack_client_secret", None)
        monkeypatch.setattr(connector_module.settings, "slack_redirect_uri", None)
        db_session.add(
            ConnectorAppConfig(
                connector_type=ConnectorType.SLACK,
                client_id="saved-client",
                client_secret_encrypted=encrypt_token("saved-secret"),
                redirect_uri="https://context.example.com/api/connectors/slack/callback",
                config={"configured_from": "dashboard"},
            )
        )
        await db_session.flush()

        fake_redis = _FakeRedis()
        monkeypatch.setattr(
            connector_module.aioredis, "from_url", lambda *a, **kw: fake_redis
        )

        resp = await client.get(
            "/api/connectors/slack/install",
            params={"workspace_id": str(workspace.id)},
            follow_redirects=False,
        )

        assert resp.status_code == 302
        location = resp.headers["location"]
        assert "client_id=saved-client" in location
        assert "redirect_uri=https://context.example.com/api/connectors/slack/callback" in location

    async def test_redirect_when_configured(self, client, workspace, monkeypatch):
        monkeypatch.setattr(connector_module.settings, "slack_client_id", "xoxb-fake")
        monkeypatch.setattr(connector_module.settings, "slack_client_secret", "secret")
        monkeypatch.setattr(
            connector_module.settings,
            "slack_redirect_uri",
            "https://example.com/callback",
        )

        fake_redis = _FakeRedis()
        monkeypatch.setattr(
            connector_module.aioredis, "from_url", lambda *a, **kw: fake_redis
        )

        resp = await client.get(
            "/api/connectors/slack/install",
            params={"workspace_id": str(workspace.id)},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        location = resp.headers["location"]
        assert "https://slack.com/oauth/v2/authorize" in location
        assert "client_id=xoxb-fake" in location

        # State was persisted in Redis
        assert len(fake_redis.store) == 1
        stored_ws_id = list(fake_redis.store.values())[0]
        assert stored_ws_id == str(workspace.id)

    async def test_501_when_not_configured(self, client, workspace, monkeypatch):
        monkeypatch.setattr(connector_module.settings, "slack_client_id", None)
        monkeypatch.setattr(connector_module.settings, "slack_client_secret", None)

        resp = await client.get(
            "/api/connectors/slack/install",
            params={"workspace_id": str(workspace.id)},
        )
        assert resp.status_code == 501
        assert "SLACK_CLIENT_ID" in resp.json()["detail"]

    async def test_501_when_client_secret_missing(self, client, workspace, monkeypatch):
        monkeypatch.setattr(connector_module.settings, "slack_client_id", "xoxb-fake")
        monkeypatch.setattr(connector_module.settings, "slack_client_secret", None)

        resp = await client.get(
            "/api/connectors/slack/install",
            params={"workspace_id": str(workspace.id)},
        )
        assert resp.status_code == 501
        assert "SLACK_CLIENT_SECRET" in resp.json()["detail"]

    async def test_missing_workspace_returns_404(self, client, monkeypatch):
        monkeypatch.setattr(connector_module.settings, "slack_client_id", "xoxb-fake")
        monkeypatch.setattr(connector_module.settings, "slack_client_secret", "secret")

        resp = await client.get(
            "/api/connectors/slack/install",
            params={"workspace_id": str(uuid4())},
        )
        assert resp.status_code == 404


# ── Slack OAuth callback ──────────────────────────────────────────


class TestSlackCallback:
    """Tests for GET /api/connectors/slack/callback.

    We patch _exchange_slack_code at the service layer so we never hit
    the real Slack API, and use _FakeRedis for state validation.
    """

    def _setup_monkeypatch(self, monkeypatch, fake_redis):
        """Common monkeypatch setup for callback tests."""
        monkeypatch.setattr(connector_module.settings, "slack_client_id", "xoxb-fake")
        monkeypatch.setattr(connector_module.settings, "slack_client_secret", "secret")
        monkeypatch.setattr(
            connector_module.settings,
            "slack_redirect_uri",
            "https://example.com/api/connectors/slack/callback",
        )
        monkeypatch.setattr(connector_module.settings, "encryption_key", _TEST_FERNET_KEY)
        monkeypatch.setattr(
            connector_module.aioredis, "from_url", lambda *a, **kw: fake_redis
        )

    async def test_callback_with_slack_error(self, client):
        resp = await client.get(
            "/api/connectors/slack/callback",
            params={"error": "access_denied"},
        )
        assert resp.status_code == 502
        assert "access_denied" in resp.json()["detail"]

    async def test_callback_with_missing_state(self, client):
        resp = await client.get(
            "/api/connectors/slack/callback",
            params={"code": "some-code"},
        )
        assert resp.status_code == 400
        assert "state" in resp.json()["detail"].lower()

    async def test_callback_with_invalid_state(self, client, monkeypatch):
        fake_redis = _FakeRedis()
        self._setup_monkeypatch(monkeypatch, fake_redis)

        resp = await client.get(
            "/api/connectors/slack/callback",
            params={"code": "some-code", "state": "bogus-state"},
        )
        assert resp.status_code == 400
        assert "expired" in resp.json()["detail"].lower() or "invalid" in resp.json()["detail"].lower()

    async def test_successful_callback_creates_connector(
        self, client, workspace, db_session, monkeypatch
    ):
        fake_redis = _FakeRedis()
        self._setup_monkeypatch(monkeypatch, fake_redis)

        # Simulate state that install endpoint would have stored
        state = f"{workspace.id}:testnonce123"
        fake_redis.store[f"ce:oauth_state:{state}"] = str(workspace.id)

        # Mock the Slack token exchange
        mock_exchange = AsyncMock(return_value={
            "ok": True,
            "access_token": "xoxb-real-token-value",
            "scope": "channels:history,channels:read",
            "team": {"id": "T12345", "name": "Test Team"},
            "authed_user": {"id": "U99999"},
        })
        monkeypatch.setattr(
            connector_module.ConnectorService,
            "_exchange_slack_code",
            mock_exchange,
        )

        resp = await client.get(
            "/api/connectors/slack/callback",
            params={"code": "slack-auth-code", "state": state},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["connector_type"] == "slack"
        assert body["status"] == "connected"
        assert body["workspace_id"] == str(workspace.id)
        assert body["config"]["team_name"] == "Test Team"

        # State was consumed (deleted from Redis)
        assert state not in fake_redis.store

        # Token is stored encrypted, not plaintext
        connector = await db_session.scalar(
            select(Connector).where(Connector.id == body["id"])
        )
        assert connector.oauth_token_encrypted is not None
        assert connector.oauth_token_encrypted != "xoxb-real-token-value"
        assert decrypt_token(connector.oauth_token_encrypted) == "xoxb-real-token-value"

    async def test_successful_callback_updates_existing_connector(
        self, client, workspace, db_session, monkeypatch
    ):
        fake_redis = _FakeRedis()
        self._setup_monkeypatch(monkeypatch, fake_redis)

        # Pre-create a disconnected Slack connector with operational metadata
        existing = Connector(
            workspace_id=workspace.id,
            connector_type=ConnectorType.SLACK,
            status=ConnectorStatus.DISCONNECTED,
            oauth_token_encrypted=None,
            config={"document_count": 150, "sync_queued_at": "2026-03-28T12:00:00"},
        )
        db_session.add(existing)
        await db_session.flush()
        existing_id = existing.id

        state = f"{workspace.id}:updatenonce"
        fake_redis.store[f"ce:oauth_state:{state}"] = str(workspace.id)

        mock_exchange = AsyncMock(return_value={
            "ok": True,
            "access_token": "xoxb-new-token",
            "scope": "channels:history",
            "team": {"id": "T12345", "name": "Reconnected Team"},
            "authed_user": {"id": "U11111"},
        })
        monkeypatch.setattr(
            connector_module.ConnectorService,
            "_exchange_slack_code",
            mock_exchange,
        )

        resp = await client.get(
            "/api/connectors/slack/callback",
            params={"code": "new-code", "state": state},
        )
        assert resp.status_code == 200
        body = resp.json()

        # Same connector row was updated, not duplicated
        assert body["id"] == str(existing_id)
        assert body["status"] == "connected"
        assert body["config"]["team_name"] == "Reconnected Team"

        # Existing operational fields preserved (merge, not replace)
        assert body["config"]["document_count"] == 150
        assert body["config"]["sync_queued_at"] == "2026-03-28T12:00:00"

        await db_session.refresh(existing)
        assert decrypt_token(existing.oauth_token_encrypted) == "xoxb-new-token"

    async def test_callback_with_failed_token_exchange(
        self, client, workspace, monkeypatch
    ):
        fake_redis = _FakeRedis()
        self._setup_monkeypatch(monkeypatch, fake_redis)

        state = f"{workspace.id}:failnonce"
        fake_redis.store[f"ce:oauth_state:{state}"] = str(workspace.id)

        mock_exchange = AsyncMock(
            side_effect=connector_module.OAuthError("Slack token exchange failed: invalid_code")
        )
        monkeypatch.setattr(
            connector_module.ConnectorService,
            "_exchange_slack_code",
            mock_exchange,
        )

        resp = await client.get(
            "/api/connectors/slack/callback",
            params={"code": "bad-code", "state": state},
        )
        assert resp.status_code == 502
        assert "invalid_code" in resp.json()["detail"]

    async def test_callback_with_transport_error_returns_502(
        self, client, workspace, monkeypatch
    ):
        fake_redis = _FakeRedis()
        self._setup_monkeypatch(monkeypatch, fake_redis)

        state = f"{workspace.id}:transportnonce"
        fake_redis.store[f"ce:oauth_state:{state}"] = str(workspace.id)

        class _RaisingAsyncClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def post(self, *args, **kwargs):
                raise httpx.ConnectError("boom")

        monkeypatch.setattr(
            connector_module.httpx,
            "AsyncClient",
            lambda *args, **kwargs: _RaisingAsyncClient(),
        )

        resp = await client.get(
            "/api/connectors/slack/callback",
            params={"code": "bad-code", "state": state},
        )
        assert resp.status_code == 502
        assert "request failed" in resp.json()["detail"]

    async def test_callback_with_missing_encryption_key(
        self, client, workspace, monkeypatch
    ):
        fake_redis = _FakeRedis()
        # Set up everything EXCEPT encryption_key
        monkeypatch.setattr(connector_module.settings, "slack_client_id", "xoxb-fake")
        monkeypatch.setattr(connector_module.settings, "slack_client_secret", "secret")
        monkeypatch.setattr(
            connector_module.settings,
            "slack_redirect_uri",
            "https://example.com/api/connectors/slack/callback",
        )
        monkeypatch.setattr(connector_module.settings, "encryption_key", None)
        monkeypatch.setattr(
            connector_module.aioredis, "from_url", lambda *a, **kw: fake_redis
        )

        state = f"{workspace.id}:nokeynonce"
        fake_redis.store[f"ce:oauth_state:{state}"] = str(workspace.id)

        mock_exchange = AsyncMock(return_value={
            "ok": True,
            "access_token": "xoxb-token",
            "team": {"id": "T1", "name": "T"},
            "authed_user": {"id": "U1"},
        })
        monkeypatch.setattr(
            connector_module.ConnectorService,
            "_exchange_slack_code",
            mock_exchange,
        )

        resp = await client.get(
            "/api/connectors/slack/callback",
            params={"code": "code", "state": state},
        )
        assert resp.status_code == 501
        assert "ENCRYPTION_KEY" in resp.json()["detail"]

    async def test_callback_with_malformed_encryption_key(
        self, client, workspace, monkeypatch
    ):
        fake_redis = _FakeRedis()
        monkeypatch.setattr(connector_module.settings, "slack_client_id", "xoxb-fake")
        monkeypatch.setattr(connector_module.settings, "slack_client_secret", "secret")
        monkeypatch.setattr(
            connector_module.settings,
            "slack_redirect_uri",
            "https://example.com/api/connectors/slack/callback",
        )
        monkeypatch.setattr(connector_module.settings, "encryption_key", "not-a-valid-fernet-key")
        monkeypatch.setattr(
            connector_module.aioredis, "from_url", lambda *a, **kw: fake_redis
        )

        state = f"{workspace.id}:badkeynonce"
        fake_redis.store[f"ce:oauth_state:{state}"] = str(workspace.id)

        mock_exchange = AsyncMock(return_value={
            "ok": True,
            "access_token": "xoxb-token",
            "team": {"id": "T1", "name": "T"},
            "authed_user": {"id": "U1"},
        })
        monkeypatch.setattr(
            connector_module.ConnectorService,
            "_exchange_slack_code",
            mock_exchange,
        )

        resp = await client.get(
            "/api/connectors/slack/callback",
            params={"code": "code", "state": state},
        )
        assert resp.status_code == 501
        assert "malformed" in resp.json()["detail"].lower()


# ── Token encryption ──────────────────────────────────────────────


class TestTokenEncryption:
    def test_encrypt_decrypt_roundtrip(self, monkeypatch):
        monkeypatch.setattr(connector_module.settings, "encryption_key", _TEST_FERNET_KEY)

        ciphertext = encrypt_token("xoxb-secret-token")
        assert ciphertext != "xoxb-secret-token"
        assert decrypt_token(ciphertext) == "xoxb-secret-token"

    def test_encrypt_fails_without_key(self, monkeypatch):
        monkeypatch.setattr(connector_module.settings, "encryption_key", None)

        import pytest
        from app.utils.crypto import EncryptionError

        with pytest.raises(EncryptionError, match="ENCRYPTION_KEY"):
            encrypt_token("something")


# ── NormalizedDocument ────────────────────────────────────────────


class TestNormalizedDocument:
    def test_creation_with_defaults(self):
        doc = NormalizedDocument(external_id="abc", content="Hello")
        assert doc.external_id == "abc"
        assert doc.content == "Hello"
        assert doc.author is None
        assert doc.source_url is None
        assert doc.created_at is None
        assert doc.metadata == {}

    def test_creation_with_all_fields(self):
        dt = datetime(2026, 3, 29, tzinfo=timezone.utc)
        doc = NormalizedDocument(
            external_id="C1:123.4",
            content="Test message",
            author="U1",
            source_url="https://slack.com/archives/C1/p1234",
            created_at=dt,
            metadata={"channel_name": "general"},
        )
        assert doc.author == "U1"
        assert doc.source_url == "https://slack.com/archives/C1/p1234"
        assert doc.created_at == dt
        assert doc.metadata["channel_name"] == "general"

    def test_is_immutable(self):
        doc = NormalizedDocument(external_id="x", content="y")
        import pytest
        with pytest.raises(AttributeError):
            doc.content = "changed"


# ── SlackConnector unit tests ─────────────────────────────────────


class TestSlackConnector:
    def test_constructor_sets_auth_header(self):
        from app.connectors.slack import SlackConnector

        conn = SlackConnector("xoxb-my-token")
        assert conn._headers["Authorization"] == "Bearer xoxb-my-token"

    async def test_handle_webhook_returns_empty(self):
        from app.connectors.slack import SlackConnector

        conn = SlackConnector("xoxb-test")
        result = await conn.handle_webhook({"type": "event_callback"})
        assert result == []

    async def test_slack_get_raises_auth_error_on_token_revoked(self):
        import pytest
        from unittest.mock import MagicMock
        from app.connectors.base import AuthenticationError
        from app.connectors.slack import SlackConnector

        conn = SlackConnector("xoxb-bad")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"ok": False, "error": "token_revoked"}

        mock_http = AsyncMock()
        mock_http.get.return_value = mock_response

        with pytest.raises(AuthenticationError, match="token_revoked"):
            await conn._slack_get(mock_http, "conversations.list")

    async def test_slack_get_raises_rate_limit(self):
        import pytest
        from unittest.mock import MagicMock
        from app.connectors.base import RateLimitError
        from app.connectors.slack import SlackConnector

        conn = SlackConnector("xoxb-test")

        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.headers = {"Retry-After": "10"}

        mock_http = AsyncMock()
        mock_http.get.return_value = mock_response

        with pytest.raises(RateLimitError) as exc_info:
            await conn._slack_get(mock_http, "conversations.list")
        assert exc_info.value.retry_after == 10.0

    async def test_slack_get_wraps_transport_errors(self):
        import pytest
        from app.connectors.base import ConnectorError
        from app.connectors.slack import SlackConnector

        conn = SlackConnector("xoxb-test")
        mock_http = AsyncMock()
        mock_http.get.side_effect = httpx.ConnectError("boom")

        with pytest.raises(ConnectorError, match="request failed"):
            await conn._slack_get(mock_http, "conversations.list")

    async def test_fetch_channel_history_resolves_users_and_concatenates_threads(
        self, monkeypatch
    ):
        from app.connectors.slack import SlackConnector

        conn = SlackConnector("xoxb-test")

        async def fake_slack_get(http, method, params=None):
            if method == "conversations.history":
                return {
                    "ok": True,
                    "messages": [
                        {
                            "ts": "1711706400.0",
                            "text": "Launch is blocked",
                            "user": "U1",
                            "thread_ts": "1711706400.0",
                            "reply_count": 2,
                        },
                        {
                            "ts": "1711706460.0",
                            "text": "Need pricing approval",
                            "user": "U2",
                            "thread_ts": "1711706400.0",
                        },
                    ],
                    "response_metadata": {},
                }
            if method == "conversations.replies":
                return {
                    "ok": True,
                    "messages": [
                        {
                            "ts": "1711706400.0",
                            "text": "Launch is blocked",
                            "user": "U1",
                            "thread_ts": "1711706400.0",
                        },
                        {
                            "ts": "1711706460.0",
                            "text": "Need pricing approval",
                            "user": "U2",
                            "thread_ts": "1711706400.0",
                        },
                        {
                            "ts": "1711706520.0",
                            "text": "Waiting on finance",
                            "user": "U1",
                            "thread_ts": "1711706400.0",
                        },
                    ],
                    "response_metadata": {},
                }
            if method == "users.info":
                user_id = params["user"]
                names = {
                    "U1": {"display_name": "Alice"},
                    "U2": {"display_name": "Bob"},
                }
                return {
                    "ok": True,
                    "user": {
                        "id": user_id,
                        "profile": names[user_id],
                    },
                }
            raise AssertionError(f"Unexpected Slack method: {method}")

        monkeypatch.setattr(conn, "_slack_get", fake_slack_get)

        docs = [
            doc
            async for doc in conn._fetch_channel_history(
                AsyncMock(),
                {"id": "C1", "name": "general"},
                oldest=None,
            )
        ]

        assert len(docs) == 1
        doc = docs[0]
        assert doc.author == "Alice"
        assert doc.metadata["reply_count"] == 2
        assert doc.metadata["channel_name"] == "general"
        assert "Thread replies:" in doc.content
        assert "Bob: Need pricing approval" in doc.content
        assert "Alice: Waiting on finance" in doc.content


# ── Notion connect ─────────────────────────────────────────────────


class TestNotionConnect:
    """Tests for POST /api/connectors/notion/connect."""

    async def test_connect_creates_connector(
        self, client, workspace, db_session, monkeypatch
    ):
        monkeypatch.setattr(connector_module.settings, "encryption_key", _TEST_FERNET_KEY)

        resp = await client.post(
            "/api/connectors/notion/connect",
            json={
                "workspace_id": str(workspace.id),
                "token": "ntn_test_integration_token",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["connector_type"] == "notion"
        assert body["status"] == "connected"
        assert body["workspace_id"] == str(workspace.id)
        assert body["provider"] == "dlt"

        # Token is stored encrypted
        conn = await db_session.scalar(
            select(Connector).where(Connector.id == body["id"])
        )
        assert conn.oauth_token_encrypted is not None
        assert conn.oauth_token_encrypted != "ntn_test_integration_token"
        assert decrypt_token(conn.oauth_token_encrypted) == "ntn_test_integration_token"

    async def test_connect_updates_existing_connector(
        self, client, workspace, db_session, monkeypatch
    ):
        monkeypatch.setattr(connector_module.settings, "encryption_key", _TEST_FERNET_KEY)

        # Pre-create a disconnected Notion connector
        existing = Connector(
            workspace_id=workspace.id,
            connector_type=ConnectorType.NOTION,
            status=ConnectorStatus.DISCONNECTED,
            config={"document_count": 42},
        )
        db_session.add(existing)
        await db_session.flush()
        existing_id = existing.id

        resp = await client.post(
            "/api/connectors/notion/connect",
            json={
                "workspace_id": str(workspace.id),
                "token": "ntn_new_token",
            },
        )
        assert resp.status_code == 200
        body = resp.json()

        # Same connector row was updated, not duplicated
        assert body["id"] == str(existing_id)
        assert body["status"] == "connected"

        await db_session.refresh(existing)
        assert decrypt_token(existing.oauth_token_encrypted) == "ntn_new_token"

    async def test_connect_missing_workspace_returns_404(
        self, client, monkeypatch
    ):
        monkeypatch.setattr(connector_module.settings, "encryption_key", _TEST_FERNET_KEY)

        resp = await client.post(
            "/api/connectors/notion/connect",
            json={
                "workspace_id": str(uuid4()),
                "token": "ntn_whatever",
            },
        )
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Workspace not found"

    async def test_connect_blank_token_returns_422(
        self, client, workspace, monkeypatch
    ):
        monkeypatch.setattr(connector_module.settings, "encryption_key", _TEST_FERNET_KEY)

        resp = await client.post(
            "/api/connectors/notion/connect",
            json={
                "workspace_id": str(workspace.id),
                "token": "   ",
            },
        )
        assert resp.status_code == 422

    async def test_connect_missing_encryption_key_returns_501(
        self, client, workspace, monkeypatch
    ):
        monkeypatch.setattr(connector_module.settings, "encryption_key", None)

        resp = await client.post(
            "/api/connectors/notion/connect",
            json={
                "workspace_id": str(workspace.id),
                "token": "ntn_valid_token",
            },
        )
        assert resp.status_code == 501


# ── Source document browsing ────────────────────────────────────────


def _make_source_doc(connector, external_id, content, *, processed=False, deleted=False):
    """Helper to create a SourceDocument row."""
    from datetime import datetime, timezone

    doc = SourceDocument(
        connector_id=connector.id,
        connector_type=connector.connector_type,
        external_id=external_id,
        content=content,
        author="test-author",
        ingested_at=datetime.now(timezone.utc),
    )
    if processed:
        doc.processed_at = datetime.now(timezone.utc)
    if deleted:
        doc.deleted_at = datetime.now(timezone.utc)
    return doc


class TestListSourceDocuments:
    """Tests for GET /api/source-documents."""

    async def test_list_returns_documents(
        self, client, workspace, db_session
    ):
        conn = Connector(
            workspace_id=workspace.id,
            connector_type=ConnectorType.SLACK,
            status=ConnectorStatus.CONNECTED,
            config={},
        )
        db_session.add(conn)
        await db_session.flush()

        d1 = _make_source_doc(conn, "ext-1", "Hello world")
        d2 = _make_source_doc(conn, "ext-2", "Second doc")
        db_session.add_all([d1, d2])
        await db_session.flush()

        resp = await client.get(
            "/api/source-documents",
            params={"workspace_id": str(workspace.id)},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 2
        assert len(body["items"]) == 2
        assert body["has_more"] is False

    async def test_list_filters_by_connector_type(
        self, client, workspace, db_session
    ):
        slack_conn = Connector(
            workspace_id=workspace.id,
            connector_type=ConnectorType.SLACK,
            status=ConnectorStatus.CONNECTED,
            config={},
        )
        notion_conn = Connector(
            workspace_id=workspace.id,
            connector_type=ConnectorType.NOTION,
            status=ConnectorStatus.CONNECTED,
            config={},
        )
        db_session.add_all([slack_conn, notion_conn])
        await db_session.flush()

        db_session.add_all([
            _make_source_doc(slack_conn, "s1", "Slack msg"),
            _make_source_doc(notion_conn, "n1", "Notion page"),
        ])
        await db_session.flush()

        resp = await client.get(
            "/api/source-documents",
            params={
                "workspace_id": str(workspace.id),
                "connector_type": "notion",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert body["items"][0]["connector_type"] == "notion"

    async def test_list_filters_by_processed_status(
        self, client, workspace, db_session
    ):
        conn = Connector(
            workspace_id=workspace.id,
            connector_type=ConnectorType.SLACK,
            status=ConnectorStatus.CONNECTED,
            config={},
        )
        db_session.add(conn)
        await db_session.flush()

        db_session.add_all([
            _make_source_doc(conn, "p1", "Processed", processed=True),
            _make_source_doc(conn, "u1", "Unprocessed", processed=False),
        ])
        await db_session.flush()

        # Only processed
        resp = await client.get(
            "/api/source-documents",
            params={
                "workspace_id": str(workspace.id),
                "processed": "true",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert body["items"][0]["external_id"] == "p1"
        assert body["items"][0]["processed_at"] is not None

        # Only unprocessed
        resp = await client.get(
            "/api/source-documents",
            params={
                "workspace_id": str(workspace.id),
                "processed": "false",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert body["items"][0]["external_id"] == "u1"
        assert body["items"][0]["processed_at"] is None

    async def test_list_excludes_deleted_documents(
        self, client, workspace, db_session
    ):
        conn = Connector(
            workspace_id=workspace.id,
            connector_type=ConnectorType.ZOOM,
            status=ConnectorStatus.CONNECTED,
            config={},
        )
        db_session.add(conn)
        await db_session.flush()

        db_session.add_all([
            _make_source_doc(conn, "active-doc", "Active transcript"),
            _make_source_doc(conn, "deleted-doc", "Deleted transcript", deleted=True),
        ])
        await db_session.flush()

        resp = await client.get(
            "/api/source-documents",
            params={"workspace_id": str(workspace.id)},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert [item["external_id"] for item in body["items"]] == ["active-doc"]

    async def test_list_pagination(self, client, workspace, db_session):
        conn = Connector(
            workspace_id=workspace.id,
            connector_type=ConnectorType.SLACK,
            status=ConnectorStatus.CONNECTED,
            config={},
        )
        db_session.add(conn)
        await db_session.flush()

        for i in range(5):
            db_session.add(_make_source_doc(conn, f"pg-{i}", f"Doc {i}"))
        await db_session.flush()

        # First page — limit 2
        resp = await client.get(
            "/api/source-documents",
            params={
                "workspace_id": str(workspace.id),
                "limit": 2,
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["items"]) == 2
        assert body["total"] == 5
        assert body["has_more"] is True
        assert body["next_cursor"] is not None

        # Second page using cursor
        resp2 = await client.get(
            "/api/source-documents",
            params={
                "workspace_id": str(workspace.id),
                "limit": 2,
                "cursor": body["next_cursor"],
            },
        )
        assert resp2.status_code == 200
        body2 = resp2.json()
        assert len(body2["items"]) == 2
        assert body2["has_more"] is True

        # Ensure no overlap between pages
        page1_ids = {item["id"] for item in body["items"]}
        page2_ids = {item["id"] for item in body2["items"]}
        assert page1_ids.isdisjoint(page2_ids)

    async def test_list_pagination_same_timestamp(
        self, client, workspace, db_session
    ):
        """Docs batch-inserted with identical ingested_at must not be
        skipped or duplicated across pages."""
        conn = Connector(
            workspace_id=workspace.id,
            connector_type=ConnectorType.SLACK,
            status=ConnectorStatus.CONNECTED,
            config={},
        )
        db_session.add(conn)
        await db_session.flush()

        # All docs share the exact same ingested_at
        shared_ts = datetime(2026, 3, 30, 12, 0, tzinfo=timezone.utc)
        for i in range(6):
            doc = SourceDocument(
                connector_id=conn.id,
                connector_type=ConnectorType.SLACK,
                external_id=f"same-ts-{i}",
                content=f"Doc {i}",
                author="bot",
                ingested_at=shared_ts,
            )
            db_session.add(doc)
        await db_session.flush()

        all_ids: set[str] = set()
        cursor = None
        pages = 0
        while True:
            params: dict = {
                "workspace_id": str(workspace.id),
                "limit": 2,
            }
            if cursor:
                params["cursor"] = cursor
            resp = await client.get("/api/source-documents", params=params)
            assert resp.status_code == 200
            body = resp.json()
            page_ids = {item["id"] for item in body["items"]}

            # No duplicates
            assert all_ids.isdisjoint(page_ids), "Duplicate docs across pages"
            all_ids.update(page_ids)

            pages += 1
            if not body["has_more"]:
                break
            cursor = body["next_cursor"]

        # All 6 docs were returned exactly once
        assert len(all_ids) == 6

    async def test_list_pagination_ignores_cursor_from_other_workspace(
        self, client, workspace, db_session
    ):
        """A cursor from another workspace must not affect this workspace's page."""
        from app.models.user import Workspace

        other_ws = Workspace(id=uuid4(), name="Other Workspace")
        db_session.add(other_ws)
        await db_session.flush()

        conn = Connector(
            workspace_id=workspace.id,
            connector_type=ConnectorType.SLACK,
            status=ConnectorStatus.CONNECTED,
            config={},
        )
        other_conn = Connector(
            workspace_id=other_ws.id,
            connector_type=ConnectorType.SLACK,
            status=ConnectorStatus.CONNECTED,
            config={},
        )
        db_session.add_all([conn, other_conn])
        await db_session.flush()

        db_session.add_all([
            SourceDocument(
                connector_id=conn.id,
                connector_type=ConnectorType.SLACK,
                external_id="ws-newest",
                content="Newest in workspace",
                author="bot",
                ingested_at=datetime(2026, 3, 30, 13, 0, tzinfo=timezone.utc),
            ),
            SourceDocument(
                connector_id=conn.id,
                connector_type=ConnectorType.SLACK,
                external_id="ws-middle",
                content="Middle in workspace",
                author="bot",
                ingested_at=datetime(2026, 3, 30, 12, 0, tzinfo=timezone.utc),
            ),
            SourceDocument(
                connector_id=conn.id,
                connector_type=ConnectorType.SLACK,
                external_id="ws-oldest",
                content="Oldest in workspace",
                author="bot",
                ingested_at=datetime(2026, 3, 30, 11, 0, tzinfo=timezone.utc),
            ),
        ])

        foreign_cursor_doc = SourceDocument(
            connector_id=other_conn.id,
            connector_type=ConnectorType.SLACK,
            external_id="foreign-cursor",
            content="Foreign workspace doc",
            author="bot",
            ingested_at=datetime(2026, 3, 30, 11, 30, tzinfo=timezone.utc),
        )
        db_session.add(foreign_cursor_doc)
        await db_session.flush()

        resp = await client.get(
            "/api/source-documents",
            params={
                "workspace_id": str(workspace.id),
                "limit": 2,
                "cursor": str(foreign_cursor_doc.id),
            },
        )
        assert resp.status_code == 200

        body = resp.json()
        assert body["total"] == 3
        assert [item["external_id"] for item in body["items"]] == [
            "ws-newest",
            "ws-middle",
        ]
        assert body["has_more"] is True
        assert body["next_cursor"] is not None

    async def test_list_empty_workspace(self, client, workspace):
        resp = await client.get(
            "/api/source-documents",
            params={"workspace_id": str(workspace.id)},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 0
        assert body["items"] == []
        assert body["has_more"] is False

    async def test_list_missing_workspace_returns_404(self, client):
        resp = await client.get(
            "/api/source-documents",
            params={"workspace_id": str(uuid4())},
        )
        assert resp.status_code == 404

    async def test_list_invalid_connector_type_returns_400(
        self, client, workspace
    ):
        resp = await client.get(
            "/api/source-documents",
            params={
                "workspace_id": str(workspace.id),
                "connector_type": "invalid_type",
            },
        )
        assert resp.status_code == 400
        assert "Invalid connector_type" in resp.json()["detail"]

    async def test_list_invalid_limit_returns_400(self, client, workspace):
        resp = await client.get(
            "/api/source-documents",
            params={
                "workspace_id": str(workspace.id),
                "limit": 0,
            },
        )
        assert resp.status_code == 400
        assert "limit" in resp.json()["detail"].lower()

        resp = await client.get(
            "/api/source-documents",
            params={
                "workspace_id": str(workspace.id),
                "limit": 201,
            },
        )
        assert resp.status_code == 400


# ── Source document detail ──────────────────────────────────────────


class TestGetSourceDocument:
    """Tests for GET /api/source-documents/{document_id}."""

    async def test_get_existing_document(
        self, client, workspace, db_session
    ):
        conn = Connector(
            workspace_id=workspace.id,
            connector_type=ConnectorType.NOTION,
            status=ConnectorStatus.CONNECTED,
            config={},
        )
        db_session.add(conn)
        await db_session.flush()

        doc = _make_source_doc(conn, "notion-page-1", "Page content here")
        db_session.add(doc)
        await db_session.flush()

        resp = await client.get(
            f"/api/source-documents/{doc.id}",
            params={"workspace_id": str(workspace.id)},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["external_id"] == "notion-page-1"
        assert body["content"] == "Page content here"
        assert body["connector_type"] == "notion"

    async def test_get_existing_github_engineering_document(
        self, client, workspace, db_session
    ):
        conn = Connector(
            workspace_id=workspace.id,
            connector_type=ConnectorType.GITHUB,
            status=ConnectorStatus.CONNECTED,
            config={"repositories": ["acme/context-engine"]},
        )
        db_session.add(conn)
        await db_session.flush()

        doc = SourceDocument(
            connector_id=conn.id,
            connector_type=ConnectorType.GITHUB,
            external_id="github:acme/context-engine:pull_request:77",
            content="Decision: use the new rollout path.",
            author="octocat",
            source_url="https://github.com/acme/context-engine/pull/77",
            ingested_at=datetime.now(timezone.utc),
            metadata_json={
                "repo_full_name": "acme/context-engine",
                "title": "Rollout path",
                "item_type": "pull_request",
                "number": 77,
                "pull_request_references": ["acme/context-engine#13"],
                "issue_references": ["acme/context-engine#31"],
                "commit_references": ["abc1234"],
            },
        )
        db_session.add(doc)
        await db_session.flush()

        resp = await client.get(
            f"/api/source-documents/{doc.id}",
            params={"workspace_id": str(workspace.id)},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["connector_type"] == "github"
        assert body["metadata"]["repo_full_name"] == "acme/context-engine"
        assert body["metadata"]["item_type"] == "pull_request"
        assert body["metadata"]["issue_references"] == ["acme/context-engine#31"]

    async def test_get_deleted_document_returns_404(
        self, client, workspace, db_session
    ):
        conn = Connector(
            workspace_id=workspace.id,
            connector_type=ConnectorType.ZOOM,
            status=ConnectorStatus.CONNECTED,
            config={},
        )
        db_session.add(conn)
        await db_session.flush()

        doc = _make_source_doc(conn, "deleted-zoom-doc", "Transcript", deleted=True)
        db_session.add(doc)
        await db_session.flush()

        resp = await client.get(
            f"/api/source-documents/{doc.id}",
            params={"workspace_id": str(workspace.id)},
        )
        assert resp.status_code == 404

    async def test_get_missing_document_returns_404(self, client, workspace):
        resp = await client.get(
            f"/api/source-documents/{uuid4()}",
            params={"workspace_id": str(workspace.id)},
        )
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Source document not found"

    async def test_cross_workspace_returns_404(
        self, client, workspace, db_session
    ):
        """A valid doc ID from another workspace must not be readable."""
        from app.models.user import Workspace

        other_ws = Workspace(id=uuid4(), name="Other Workspace")
        db_session.add(other_ws)
        await db_session.flush()

        conn = Connector(
            workspace_id=other_ws.id,
            connector_type=ConnectorType.SLACK,
            status=ConnectorStatus.CONNECTED,
            config={},
        )
        db_session.add(conn)
        await db_session.flush()

        doc = _make_source_doc(conn, "secret-doc", "Sensitive content")
        db_session.add(doc)
        await db_session.flush()

        # Request with workspace.id should NOT see other_ws's doc
        resp = await client.get(
            f"/api/source-documents/{doc.id}",
            params={"workspace_id": str(workspace.id)},
        )
        assert resp.status_code == 404


# ── Processing summary ──────────────────────────────────────────────


class TestProcessingSummary:
    """Tests for GET /api/connectors/processing-summary."""

    async def test_summary_with_documents(
        self, client, workspace, db_session
    ):
        conn = Connector(
            workspace_id=workspace.id,
            connector_type=ConnectorType.SLACK,
            status=ConnectorStatus.CONNECTED,
            config={},
        )
        db_session.add(conn)
        await db_session.flush()

        db_session.add_all([
            _make_source_doc(conn, "ps-1", "Processed doc", processed=True),
            _make_source_doc(conn, "ps-2", "Unprocessed doc", processed=False),
            _make_source_doc(conn, "ps-3", "Another processed", processed=True),
        ])
        await db_session.flush()

        resp = await client.get(
            "/api/connectors/processing-summary",
            params={"workspace_id": str(workspace.id)},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 1
        summary = body[0]
        assert summary["connector_type"] == "slack"
        assert summary["total_documents"] == 3
        assert summary["processed_documents"] == 2
        assert summary["unprocessed_documents"] == 1

    async def test_summary_empty_workspace(self, client, workspace):
        resp = await client.get(
            "/api/connectors/processing-summary",
            params={"workspace_id": str(workspace.id)},
        )
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_summary_multiple_connectors(
        self, client, workspace, db_session
    ):
        slack = Connector(
            workspace_id=workspace.id,
            connector_type=ConnectorType.SLACK,
            status=ConnectorStatus.CONNECTED,
            config={},
        )
        notion = Connector(
            workspace_id=workspace.id,
            connector_type=ConnectorType.NOTION,
            status=ConnectorStatus.CONNECTED,
            config={},
        )
        db_session.add_all([slack, notion])
        await db_session.flush()

        db_session.add_all([
            _make_source_doc(slack, "s1", "Slack msg", processed=True),
            _make_source_doc(notion, "n1", "Page 1", processed=False),
            _make_source_doc(notion, "n2", "Page 2", processed=True),
        ])
        await db_session.flush()

        resp = await client.get(
            "/api/connectors/processing-summary",
            params={"workspace_id": str(workspace.id)},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 2

        by_type = {s["connector_type"]: s for s in body}
        assert by_type["slack"]["total_documents"] == 1
        assert by_type["slack"]["processed_documents"] == 1
        assert by_type["notion"]["total_documents"] == 2
        assert by_type["notion"]["unprocessed_documents"] == 1

    async def test_summary_missing_workspace_returns_404(self, client):
        resp = await client.get(
            "/api/connectors/processing-summary",
            params={"workspace_id": str(uuid4())},
        )
        assert resp.status_code == 404


# ── Connector Hardening (Slice 4) ─────────────────────────────────


class TestConnectorHardening:
    """Structured last_error and Notion sync_mode_note."""

    def _setup(self, monkeypatch):
        monkeypatch.setattr(connector_module.settings, "encryption_key", _TEST_FERNET_KEY)

    async def _make_connector(self, db_session, workspace, connector_type=ConnectorType.SLACK):
        conn = Connector(
            workspace_id=workspace.id,
            connector_type=connector_type,
            status=ConnectorStatus.CONNECTED,
            oauth_token_encrypted=encrypt_token("test-token"),
            config={},
        )
        db_session.add(conn)
        await db_session.flush()
        return conn

    async def test_auth_failure_stores_last_error_in_config(
        self, db_session, workspace, monkeypatch
    ):
        """AuthenticationError stores structured last_error in connector.config."""
        self._setup(monkeypatch)
        import app.services.sync_service as sync_module
        from app.connectors.base import AuthenticationError
        from app.services.sync_service import SyncExecutor

        conn = await self._make_connector(db_session, workspace)
        conn_id = conn.id

        mock_impl = AsyncMock()
        async def _raise_auth():
            raise AuthenticationError("token_revoked")
            yield  # make it an async generator
        mock_impl.fetch_initial = _raise_auth

        monkeypatch.setattr(
            sync_module.SyncExecutor,
            "_resolve_connector",
            lambda self, ct, token: mock_impl,
        )

        import pytest
        with pytest.raises(Exception):
            await SyncExecutor(db_session).run(conn, "test-token")

        db_session.expire_all()
        refreshed = await db_session.scalar(
            select(Connector).where(Connector.id == conn_id)
        )
        assert "last_error" in refreshed.config
        assert "error_type" in refreshed.config["last_error"]
        assert "error_message" in refreshed.config["last_error"]
        assert "failed_at" in refreshed.config["last_error"]

    async def test_notion_sync_stores_sync_mode_note(
        self, db_session, workspace, monkeypatch
    ):
        """After a successful Notion sync, sync_mode_note is set in connector.config."""
        self._setup(monkeypatch)
        import app.services.sync_service as sync_module
        from app.services.sync_service import SyncExecutor

        conn = await self._make_connector(db_session, workspace, ConnectorType.NOTION)
        conn_id = conn.id

        sample_docs = [
            NormalizedDocument(
                external_id="notion:page-1",
                content="decision: prioritize mobile",
                author="founder@example.com",
                source_url="https://notion.so/page-1",
            ),
        ]

        async def _mock_fetch():
            for d in sample_docs:
                yield d

        mock_impl = AsyncMock()
        mock_impl.fetch_initial = _mock_fetch

        monkeypatch.setattr(
            sync_module.SyncExecutor,
            "_resolve_connector",
            lambda self, ct, token: mock_impl,
        )

        await SyncExecutor(db_session).run(conn, "ntn_test_token")

        db_session.expire_all()
        refreshed = await db_session.scalar(
            select(Connector).where(Connector.id == conn_id)
        )
        assert "sync_mode_note" in refreshed.config
        assert "Notion API limitation" in refreshed.config["sync_mode_note"]
