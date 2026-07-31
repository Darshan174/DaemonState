from __future__ import annotations

from sqlalchemy import func, select

from app.models import WaitlistSignup


async def test_registers_and_normalizes_waitlist_email(client, db_session):
    response = await client.post(
        "/api/waitlist",
        json={"email": "  Builder@Example.COM  ", "website": ""},
    )

    assert response.status_code == 201
    assert response.json() == {
        "status": "registered",
        "message": "You're on the DaemonState waitlist.",
    }
    signup = await db_session.scalar(select(WaitlistSignup))
    assert signup is not None
    assert signup.email == "builder@example.com"
    assert signup.source == "landing"


async def test_waitlist_registration_is_idempotent(client, db_session):
    first = await client.post("/api/waitlist", json={"email": "same@example.com"})
    duplicate = await client.post("/api/waitlist", json={"email": "SAME@example.com"})

    assert first.status_code == 201
    assert duplicate.status_code == 201
    count = await db_session.scalar(select(func.count()).select_from(WaitlistSignup))
    assert count == 1


async def test_waitlist_rejects_invalid_email(client):
    response = await client.post("/api/waitlist", json={"email": "not-an-email"})

    assert response.status_code == 422


async def test_waitlist_honeypot_does_not_persist_signup(client, db_session):
    response = await client.post(
        "/api/waitlist",
        json={"email": "bot@example.com", "website": "https://spam.example"},
    )

    assert response.status_code == 201
    count = await db_session.scalar(select(func.count()).select_from(WaitlistSignup))
    assert count == 0


async def test_waitlist_post_remains_public_when_api_auth_is_enabled(
    client,
    monkeypatch,
):
    monkeypatch.setattr("app.config.settings.server_api_key", "server-secret", raising=False)

    response = await client.post(
        "/api/waitlist",
        json={"email": "public@example.com"},
    )
    protected = await client.get("/api/workspaces")

    assert response.status_code == 201
    assert protected.status_code == 401
