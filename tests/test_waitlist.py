from __future__ import annotations

import sqlite3
from pathlib import Path

from sqlalchemy import func, select

from app.api.waitlist import WAITLIST_CONSENT_VERSION
from app.models import WaitlistSignup


def test_d1_waitlist_migration_preserves_email_only_rows():
    migration_path = (
        Path(__file__).resolve().parents[1]
        / "frontend"
        / "migrations"
        / "0001_waitlist_tracking.sql"
    )
    database = sqlite3.connect(":memory:")
    try:
        database.executescript("""
            CREATE TABLE waitlist_signups (
              id TEXT PRIMARY KEY,
              email TEXT NOT NULL UNIQUE COLLATE NOCASE,
              source TEXT NOT NULL DEFAULT 'landing',
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX ix_waitlist_signups_created_at
              ON waitlist_signups (created_at);
            INSERT INTO waitlist_signups (id, email, source, created_at)
              VALUES ('signup-1', 'Builder@Example.com', 'landing', '2026-08-01 10:00:00');
        """)

        database.executescript(migration_path.read_text(encoding="utf-8"))

        columns = {
            row[1]
            for row in database.execute("PRAGMA table_info(waitlist_signups)")
        }
        assert {
            "email",
            "referrer",
            "utm_source",
            "status",
            "consent_at",
            "email_sync_status",
            "updated_at",
        } <= columns
        row = database.execute("""
            SELECT email, source, status, email_sync_status, created_at, updated_at
            FROM waitlist_signups
        """).fetchone()
        assert row == (
            "builder@example.com",
            "landing",
            "new",
            "pending",
            "2026-08-01 10:00:00",
            "2026-08-01 10:00:00",
        )
    finally:
        database.close()


async def test_registers_and_normalizes_waitlist_email(client, db_session):
    response = await client.post(
        "/api/waitlist",
        json={
            "email": "  Builder@Example.COM  ",
            "website": "",
            "referrer": "https://news.example/launch?reader=private#comments",
            "utm_source": " Newsletter ",
            "utm_medium": "email",
            "utm_campaign": "private-beta",
            "consent_version": WAITLIST_CONSENT_VERSION,
        },
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
    assert signup.referrer == "https://news.example/launch"
    assert signup.utm_source == "Newsletter"
    assert signup.utm_medium == "email"
    assert signup.utm_campaign == "private-beta"
    assert signup.status == "new"
    assert signup.priority_score == 0
    assert signup.consent_at is not None
    assert signup.consent_version == WAITLIST_CONSENT_VERSION
    assert signup.email_sync_status == "pending"


async def test_waitlist_registration_is_idempotent(client, db_session):
    first = await client.post(
        "/api/waitlist",
        json={"email": "same@example.com", "utm_source": "first-touch"},
    )
    duplicate = await client.post(
        "/api/waitlist",
        json={"email": "SAME@example.com", "utm_source": "later-touch"},
    )

    assert first.status_code == 201
    assert duplicate.status_code == 201
    count = await db_session.scalar(select(func.count()).select_from(WaitlistSignup))
    assert count == 1
    signup = await db_session.scalar(select(WaitlistSignup))
    assert signup is not None
    assert signup.utm_source == "first-touch"


async def test_waitlist_rejects_invalid_email(client):
    response = await client.post("/api/waitlist", json={"email": "not-an-email"})

    assert response.status_code == 422


async def test_waitlist_rejects_unsafe_attribution_and_unknown_consent(client):
    unsafe_referrer = await client.post(
        "/api/waitlist",
        json={
            "email": "builder@example.com",
            "referrer": "javascript:alert(1)",
        },
    )
    unknown_consent = await client.post(
        "/api/waitlist",
        json={
            "email": "builder@example.com",
            "consent_version": "legacy",
        },
    )

    assert unsafe_referrer.status_code == 422
    assert unknown_consent.status_code == 422


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
